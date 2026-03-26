"""Fish Audio TTS Provider — voice-actor-quality synthesis with voice cloning.

Uses Fish Audio S1/S2-Pro API for high-quality character voices.
Key features:
  - 10-second voice cloning via reference_id
  - Emotion control via inline tags: S1 uses (happy), S2-Pro uses [happy]
  - Prosody: speed (0.5-2.0), volume (-20 to +20 dB)
  - Streaming chunked audio response
"""

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ai_core.config import settings
from ai_core.services.tts.base import TTSProvider

logger = structlog.get_logger()

_API_BASE = "https://api.fish.audio"
_TTS_ENDPOINT = f"{_API_BASE}/v1/tts"

_RETRYABLE = (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, TimeoutError, ConnectionError)

# ── Fish Audio Voice Library with personality vectors ──
# Same 4D vector system as voice_matcher.py (warmth, energy, maturity, gravity)
# Each voice is profiled so the matching algorithm works for ANY character.

import math

FISH_VOICES = {
    # ─── Male voices ─────────────────────────────
    "15896f78e288417db16cc34da8fc6f09": {
        "w": 45, "e": 55, "m": 30, "g": 20,
        "gender": "male", "label": "少侠公子 (清冷少年)",
    },
    "7a02aebcd8f94d8283a02842ce4ddd33": {
        "w": 55, "e": 70, "m": 25, "g": 10,
        "gender": "male", "label": "少年感 (元气少年)",
    },
    "d99547e2dad64ce0aa085319a3c9cc56": {
        "w": 80, "e": 30, "m": 40, "g": 15,
        "gender": "male", "label": "温柔男声 (温暖大哥)",
    },
    "f4fead56f51646dfbc37ec450a06fc07": {
        "w": 35, "e": 20, "m": 65, "g": 55,
        "gender": "male", "label": "沉稳男声 (成熟稳重)",
    },
    "204900525e1243cc9a616c82c8c02636": {
        "w": 70, "e": 40, "m": 35, "g": 10,
        "gender": "male", "label": "男4温柔 (轻柔男声)",
    },
    # ─── Female voices ────────────────────────────
    "564dc2631c624222a21864b17f3c66a8": {
        "w": 80, "e": 70, "m": 8, "g": 3,
        "gender": "female", "label": "萝莉幼态 (软萌童声)",
    },
    "65c4eb56353d42e5b576d01f812e1d1f": {
        "w": 70, "e": 65, "m": 20, "g": 8,
        "gender": "female", "label": "可爱女配 (甜美少女)",
    },
    "f82e3885ac22468eb6c773b96f2c5752": {
        "w": 75, "e": 60, "m": 15, "g": 5,
        "gender": "female", "label": "萝莉萌妹 (活泼软萌)",
    },
    "c1b7b0d5f19b46aa944e80de970662a1": {
        "w": 65, "e": 35, "m": 35, "g": 20,
        "gender": "female", "label": "温柔女声 (温婉姐姐)",
    },
    "a6b29d0ef2404ca1aa8d1fdd8d7a2a90": {
        "w": 40, "e": 80, "m": 22, "g": 8,
        "gender": "female", "label": "青春活泼女 (元气少女)",
    },
}


def _fish_voice_distance(char_vec: dict, voice: dict) -> float:
    """Weighted Euclidean distance between character and voice personality vectors.

    Compared to DashScope matcher, Fish Audio has fewer voices so we
    weight maturity higher to better differentiate child vs adult voices.
    """
    dw = (char_vec["w"] - voice["w"]) * 1.0
    de = (char_vec["e"] - voice["e"]) * 0.8
    dm = (char_vec["m"] - voice["m"]) * 1.5   # maturity matters most for voice age
    dg = (char_vec["g"] - voice["g"]) * 0.6
    return math.sqrt(dw*dw + de*de + dm*dm + dg*dg)


def resolve_fish_voice(
    voice_id: str | None = None,
    species: str = "",
    personality: dict | None = None,
    age_setting: int | None = None,
    relationship: str | None = None,
) -> str:
    """Universal voice matching for Fish Audio — works for ANY character.

    Uses the same personality vector algorithm as voice_matcher.py,
    but matches against Fish Audio's voice library.

    Priority:
    1. Custom Fish Audio ID (32-char hex) → use directly
    2. Personality vector matching → closest Fish Audio voice
    """
    # Custom Fish Audio reference ID
    if voice_id and not voice_id.startswith("long") and len(voice_id) >= 20:
        return voice_id

    # Build character vector using voice_matcher's algorithm
    from ai_core.services.voice_matcher import _build_character_vector, _classify_species
    char_vec = _build_character_vector(species, age_setting, personality, relationship)
    sp = _classify_species(species)
    gender_hint = sp.get("gender_hint")

    # For small/cute characters, push maturity down hard
    # so they match the youngest-sounding voices (萝莉童声 > 甜美少女)
    m_offset = sp.get("m_offset", 0)
    if m_offset <= -10:  # tiny/child categories
        char_vec["m"] = max(0, min(12, char_vec["m"] - 20))
        char_vec["g"] = max(0, char_vec["g"] - 8)

    # Find closest Fish Audio voice by vector distance + gender penalty
    best_vid = ""
    best_dist = float("inf")
    for vid, voice in FISH_VOICES.items():
        dist = _fish_voice_distance(char_vec, voice)

        voice_gender = voice.get("gender", "neutral")
        if gender_hint:
            if voice_gender != "neutral" and voice_gender != gender_hint:
                dist += 40  # wrong gender: heavy penalty
            elif voice_gender == "neutral":
                dist += 15

        if dist < best_dist:
            best_dist = dist
            best_vid = vid

    label = FISH_VOICES[best_vid]["label"]
    logger.info("tts.fish_voice_matched", species=species, voice=best_vid, label=label, dist=f"{best_dist:.0f}")
    return best_vid

# PAD emotion → Fish Audio emotion tag mapping
# S1 uses (tag), S2-Pro uses [tag]
_EMOTION_FROM_PAD: list[tuple[str, callable]] = []  # populated below

# Discrete emotion → Fish Audio inline tag
EMOTION_TAGS = {
    "happy":    "happy",
    "sad":      "sad",
    "shy":      "shy and nervous",
    "angry":    "angry",
    "playful":  "playful and teasing",
    "curious":  "curious",
    "worried":  "worried and concerned",
    "calm":     "",  # no tag for neutral
    "excited":  "excited",
}


def _pad_to_emotion_tag(p: float, a: float, d: float) -> str:
    """Convert PAD values to the most fitting emotion tag for Fish Audio."""
    if p > 0.4 and a > 0.3:
        return "excited and happy"
    elif p > 0.3 and a <= 0.3:
        return "warm and gentle"
    elif p > 0.1 and d < -0.3:
        return "shy and nervous"
    elif p < -0.4 and a > 0.3:
        return "angry"
    elif p < -0.4:
        return "sad"
    elif a > 0.4:
        return "curious and energetic"
    elif a < -0.4:
        return "calm and sleepy"
    elif d > 0.4:
        return "confident"
    elif d < -0.4:
        return "timid and soft"
    return ""  # neutral


def _pad_to_prosody(p: float, a: float, d: float) -> dict:
    """Convert PAD values to Fish Audio prosody parameters."""
    # Speed: arousal drives it. Excited = faster, calm = slower.
    speed = 1.0 + a * 0.15 + p * 0.05
    speed = max(0.75, min(1.3, speed))

    # Volume: arousal + pleasure. Excited/happy = louder, sad/calm = softer.
    volume = int(a * 8 + p * 3)
    volume = max(-10, min(10, volume))

    return {"speed": round(speed, 2), "volume": volume}


class FishAudioTTSProvider(TTSProvider):
    """Fish Audio TTS provider with voice cloning and emotion support."""

    name = "fish"

    def __init__(self):
        self.api_key = settings.fish_audio_api_key
        self.model = settings.fish_audio_model  # "s1" or "s2-pro"
        self._char_context: dict = {}  # set by chat endpoint before synthesis
        if not self.api_key:
            raise RuntimeError("FISH_AUDIO_API_KEY not configured")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        logger.info("tts.fish_audio_init", model=self.model)

    def set_character_context(self, species: str = "", personality: dict | None = None,
                               age_setting: int | None = None, relationship: str | None = None):
        """Set character context for voice resolution. Call before synthesize."""
        self._char_context = {
            "species": species, "personality": personality,
            "age_setting": age_setting, "relationship": relationship,
        }

    def _wrap_emotion(self, text: str, emotion_tag: str) -> str:
        """Prepend emotion tag to text based on model version."""
        if not emotion_tag:
            return text
        if self.model == "s1":
            return f"({emotion_tag}) {text}"
        else:
            # S2-Pro uses [bracket] syntax
            return f"[{emotion_tag}] {text}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def _call_api(self, text: str, voice: str | None, prosody: dict) -> bytes:
        """Call Fish Audio TTS API and return audio bytes."""
        body: dict = {
            "text": text,
            "format": "mp3",
            "mp3_bitrate": 128,
            "normalize": True,
            "temperature": 0.7,
            "top_p": 0.8,
            "chunk_length": 200,
            "latency": "balanced",
        }

        # Resolve voice to Fish Audio reference ID using personality vector matching
        resolved = resolve_fish_voice(
            voice_id=voice,
            species=self._char_context.get("species", ""),
            personality=self._char_context.get("personality"),
            age_setting=self._char_context.get("age_setting"),
            relationship=self._char_context.get("relationship"),
        )
        if resolved:
            body["reference_id"] = resolved

        if prosody:
            body["prosody"] = prosody

        resp = await self._client.post(
            _TTS_ENDPOINT,
            json=body,
            headers={"model": self.model},
        )

        if resp.status_code == 401:
            raise RuntimeError("Fish Audio: authentication failed")
        if resp.status_code == 402:
            raise RuntimeError("Fish Audio: insufficient credits")
        if resp.status_code != 200:
            raise RuntimeError(f"Fish Audio: HTTP {resp.status_code} - {resp.text[:200]}")

        audio = resp.content
        if not audio or len(audio) < 100:
            raise RuntimeError("Fish Audio: empty audio response")

        logger.info(
            "tts.fish_audio_synthesize",
            text_len=len(text),
            voice_input=voice or "none",
            voice_resolved=resolved or "none",
            audio_bytes=len(audio),
            speed=prosody.get("speed", 1.0),
        )
        return audio

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        pitch_rate: int = 0,
        speech_rate: int = 0,
        ssml_pitch: float = 1.0,
        ssml_rate: float = 1.0,
        ssml_effect: str = "",
    ) -> bytes:
        # Convert SSML params to Fish Audio prosody
        # ssml_pitch/ssml_rate come from the structured response voice params
        fish_speed = ssml_rate * speed
        fish_speed = max(0.5, min(2.0, fish_speed))

        # Derive emotion from ssml params (if pitch significantly deviates from 1.0)
        emotion_tag = ""
        if ssml_effect and ssml_effect in EMOTION_TAGS:
            emotion_tag = EMOTION_TAGS[ssml_effect]

        text_with_emotion = self._wrap_emotion(text, emotion_tag)
        prosody = {"speed": round(fish_speed, 2), "volume": 0}

        return await self._call_api(text_with_emotion, voice, prosody)

    async def synthesize_to_wav(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        pitch_rate: int = 0,
        speech_rate: int = 0,
        ssml_pitch: float = 1.0,
        ssml_rate: float = 1.0,
        ssml_effect: str = "",
    ) -> bytes:
        # Same as synthesize — Fish Audio returns MP3 directly
        return await self.synthesize(
            text=text, voice=voice, speed=speed,
            pitch_rate=pitch_rate, speech_rate=speech_rate,
            ssml_pitch=ssml_pitch, ssml_rate=ssml_rate, ssml_effect=ssml_effect,
        )

    async def synthesize_with_pad(
        self,
        text: str,
        voice: str | None = None,
        pad_p: float = 0.0,
        pad_a: float = 0.0,
        pad_d: float = 0.0,
    ) -> bytes:
        """Synthesize with PAD-driven emotion and prosody — the preferred method."""
        emotion_tag = _pad_to_emotion_tag(pad_p, pad_a, pad_d)
        prosody = _pad_to_prosody(pad_p, pad_a, pad_d)
        text_with_emotion = self._wrap_emotion(text, emotion_tag)
        return await self._call_api(text_with_emotion, voice, prosody)

    def get_voices(self) -> dict[str, str]:
        return {
            "default": "Fish Audio default voice",
        }

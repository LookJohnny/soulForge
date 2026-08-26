"""Life loop — per-session idle behavior scheduler.

A real character doesn't only exist when spoken to. After a while of
silence it gets bored (hums, mumbles a thought), then sleepy (yawns),
then falls asleep (soft snores). This task watches idle time and plays
spontaneous sounds through the same TTS playback path conversations use.

Design constraints:
- Never interfere with a conversation: skipped while the session is
  playing TTS, processing a turn, or the user is mid-utterance.
- Cheap by default: ambient sounds are short cached TTS clips in the
  character's own voice. Occasionally (life_llm_thought_prob) a bored
  sound is upgraded to a full LLM "spontaneous thought", which goes
  through the normal pipeline in idle_mode — memory-aware but writing
  no memories and earning no relationship points.
- Crash-proof: everything is wrapped; a failure only skips one sound.
"""

import asyncio
import logging
import random
import time
from enum import Enum

from gateway.config import settings
from gateway.life import vocab

logger = logging.getLogger(__name__)


class LifeState(str, Enum):
    AWAKE = "awake"
    BORED = "bored"
    SLEEPY = "sleepy"
    ASLEEP = "asleep"


# Min/max seconds between ambient sounds per state
GAP_RANGES: dict[LifeState, tuple[float, float]] = {
    LifeState.BORED: (60.0, 180.0),
    LifeState.SLEEPY: (90.0, 240.0),
    LifeState.ASLEEP: (180.0, 420.0),
}

_TICK_S = 5.0

# Shared TTS clip cache: (character_id, text) -> mp3 bytes
_tts_cache: dict[tuple[str | None, str], bytes] = {}
_TTS_CACHE_MAX = 128


def is_night(hour: int, night_start: int, night_end: int) -> bool:
    return hour >= night_start or hour < night_end


def compute_state(
    idle_s: float,
    hour: int,
    *,
    bored_after: float,
    sleepy_after: float,
    asleep_after: float,
    night_start: int,
    night_end: int,
    energy: int = 100,
) -> LifeState:
    """Map idle duration + local hour (+ relationship energy) to a life state.

    At night the sleepy/asleep thresholds halve — the character gets
    drowsy sooner, like anything alive would. Low ``energy`` (the five-axis
    relationship's 0–100 stamina, refilled by rest) has the same effect on a
    sliding scale: 0 energy halves the thresholds, 100 leaves them alone.
    """
    night = is_night(hour, night_start, night_end)
    tired = 0.5 + 0.5 * max(0, min(100, energy)) / 100
    sleepy_th = (sleepy_after / 2 if night else sleepy_after) * tired
    asleep_th = (asleep_after / 2 if night else asleep_after) * tired
    if idle_s >= asleep_th:
        return LifeState.ASLEEP
    if idle_s >= sleepy_th:
        return LifeState.SLEEPY
    if idle_s >= bored_after:
        return LifeState.BORED
    return LifeState.AWAKE


def next_gap(state: LifeState, rng: random.Random | None = None) -> float:
    lo, hi = GAP_RANGES.get(state, GAP_RANGES[LifeState.BORED])
    return (rng or random).uniform(lo, hi)


class LifeLoop:
    """Per-connection idle behavior driver."""

    def __init__(self, server, ws, adapter, session):
        self.server = server
        self.ws = ws
        self.adapter = adapter
        self.session = session
        self.last_user_activity = time.monotonic()
        self._next_due: float | None = None
        self._task: asyncio.Task | None = None
        self._filler_clips: list[bytes] = []

    # ── lifecycle ───────────────────────────────────

    def start(self) -> None:
        if settings.life_loop_enabled:
            self._task = asyncio.create_task(self._run())
        if settings.thinking_filler_enabled:
            asyncio.create_task(self._prewarm_fillers())

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def notify_activity(self) -> None:
        """User interacted (speech/touch) — reset idle clock and schedule."""
        self.last_user_activity = time.monotonic()
        self._next_due = None

    # ── thinking filler ─────────────────────────────

    def pop_filler(self) -> bytes | None:
        """Return a cached filler clip, or None (cold cache / dice roll)."""
        if not settings.thinking_filler_enabled or not self._filler_clips:
            return None
        if random.random() > settings.thinking_filler_prob:
            return None
        return random.choice(self._filler_clips)

    async def _prewarm_fillers(self) -> None:
        try:
            texts = random.sample(vocab.THINKING_FILLERS, k=min(3, len(vocab.THINKING_FILLERS)))
            for text in texts:
                clip = await self._tts(text)
                if clip:
                    self._filler_clips.append(clip)
        except Exception:
            logger.warning("life.filler_prewarm_failed", exc_info=True)

    # ── main loop ───────────────────────────────────

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(_TICK_S)
                now = time.monotonic()
                idle = now - self.last_user_activity
                state = compute_state(
                    idle,
                    time.localtime().tm_hour,
                    bored_after=settings.life_bored_after_s,
                    sleepy_after=settings.life_sleepy_after_s,
                    asleep_after=settings.life_asleep_after_s,
                    night_start=settings.life_night_start_hour,
                    night_end=settings.life_night_end_hour,
                    energy=int(getattr(self.session, "_energy", 100) or 100),
                )
                if state is LifeState.AWAKE:
                    self._next_due = None
                    continue
                if self._busy():
                    continue
                if self._next_due is None:
                    # Just entered a living state — schedule the first sound
                    self._next_due = now + next_gap(state)
                    continue
                if now < self._next_due:
                    continue
                try:
                    await self._do_ambient(state)
                except Exception:
                    logger.exception("life.ambient_error")
                self._next_due = time.monotonic() + next_gap(state)
        except asyncio.CancelledError:
            pass

    def _busy(self) -> bool:
        s = self.session
        return (
            getattr(s, "_playing", False)
            or getattr(s, "_processing", False)
            or self.server.audio_handler.has_speech(s)
        )

    # ── behaviors ───────────────────────────────────

    async def _do_ambient(self, state: LifeState) -> None:
        text = None
        audio = None

        # Occasionally upgrade a bored hum to a memory-aware LLM musing,
        # or a sleepy yawn to a drowsy mumble. Never while asleep.
        if (
            state in (LifeState.BORED, LifeState.SLEEPY)
            and self.session.character_id
            and random.random() < settings.life_llm_thought_prob
        ):
            try:
                idle_state = "sleepy" if state is LifeState.SLEEPY else "bored"
                result = await self.server.orchestrator.process_idle(self.session, idle_state)
                text, audio = result.get("text"), result.get("audio_data")
                if text and audio:
                    # The character remembers what it said to itself
                    await self.server.session_manager.add_to_history(
                        self.session.session_id, "assistant", text
                    )
            except Exception:
                logger.warning("life.idle_thought_failed", exc_info=True)

        if not audio:
            text = vocab.pick_ambient(state.value)
            audio = await self._tts(text)
        if not audio:
            return

        logger.info("life.ambient state=%s text=%s", state.value, (text or "")[:30])
        await self._play(text or "", audio)

    async def _tts(self, text: str) -> bytes | None:
        key = (self.session.character_id, text)
        cached = _tts_cache.get(key)
        if cached:
            return cached
        try:
            audio = await self.server.orchestrator.synthesize_tts(
                text,
                character_id=self.session.character_id,
                brand_id=self.session.brand_id,
            )
        except Exception:
            logger.warning("life.tts_failed text=%s", text[:20], exc_info=True)
            return None
        if audio:
            if len(_tts_cache) >= _TTS_CACHE_MAX:
                _tts_cache.pop(next(iter(_tts_cache)))
            _tts_cache[key] = audio
        return audio

    async def _play(self, text: str, mp3: bytes) -> None:
        """Play an ambient clip using the same protocol dance as quick replies."""
        from gateway.playback import PlaybackChannel

        s = self.session
        if self._busy():
            return
        async with PlaybackChannel(self.ws, self.adapter, s) as pb:
            await pb.send_start()
            if text:
                await pb.send_sentence(text)
            await pb.send_clip(mp3)
            await pb.finish(wait_drain=False)
            # Let the device drain its buffer before the mic counts again
            await asyncio.sleep(0.3)

        # Reset listening so speaker echo doesn't linger in the VAD buffers
        try:
            if getattr(s, "_silence_task", None):
                s._silence_task.cancel()
                self.server.audio_handler.start_listening(s)
                s._silence_task = asyncio.create_task(
                    self.server._vad_monitor(self.ws, self.adapter, s)
                )
        except Exception:
            logger.exception("life.listen_reset_error")

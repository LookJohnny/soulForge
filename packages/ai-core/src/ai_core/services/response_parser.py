"""Structured LLM Response Parser.

The LLM is instructed to output JSON with dialogue, action, thought,
PAD emotion values, voice parameters, and behavioral stance.
This module parses that JSON robustly, with fallback for plain text.
"""

import json
import re
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()

# Regex to extract JSON from LLM output that may have markdown fences or preamble
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BARE_RE = re.compile(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", re.DOTALL)

# Tone keywords that map to SSML effects or TTS behavior
TONE_SSML_MAP: dict[str, str] = {
    "whisper": "lolita",    # CosyVoice doesn't have whisper, lolita is softest
    "cute": "lolita",
    "echo": "echo",
    "robot": "robot",
    "muffled": "lowpass",
}


@dataclass
class VoiceParams:
    speed: float = 1.0    # 0.7 – 1.3
    pitch: float = 0.0    # -0.15 – 0.15
    tone: str = ""        # descriptive: gentle, cheerful, teasing, firm, trembling, whisper

    def to_ssml(self, base_pitch: float = 1.0, base_rate: float = 1.0) -> dict:
        """Convert to TTS parameters."""
        return {
            "ssml_pitch": max(0.5, min(2.0, base_pitch + self.pitch)),
            "ssml_rate": max(0.5, min(2.0, base_rate * self.speed)),
            "ssml_effect": TONE_SSML_MAP.get(self.tone, ""),
        }


@dataclass
class PADValues:
    p: float = 0.0   # pleasure  -1..1
    a: float = 0.0   # arousal   -1..1
    d: float = 0.0   # dominance -1..1

    def clamp(self) -> "PADValues":
        self.p = max(-1.0, min(1.0, self.p))
        self.a = max(-1.0, min(1.0, self.a))
        self.d = max(-1.0, min(1.0, self.d))
        return self


@dataclass
class StructuredResponse:
    dialogue: str = ""
    action: str = ""
    thought: str = ""
    pad: PADValues = field(default_factory=PADValues)
    voice: VoiceParams = field(default_factory=VoiceParams)
    stance: str = ""
    raw: str = ""          # original LLM output for debugging
    parsed_ok: bool = True  # whether JSON parsing succeeded


def _extract_json_str(text: str) -> str | None:
    """Try to extract a JSON object string from LLM output."""
    # Try markdown fenced block first
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1)

    # Try bare JSON object
    m = _JSON_BARE_RE.search(text)
    if m:
        return m.group(1)

    # Maybe the entire text is JSON
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    return None


def _safe_float(val, default: float = 0.0, lo: float = -2.0, hi: float = 2.0) -> float:
    try:
        f = float(val)
        return max(lo, min(hi, f))
    except (TypeError, ValueError):
        return default


def parse_llm_response(raw_text: str) -> StructuredResponse:
    """Parse structured JSON response from LLM.

    Handles:
    - Clean JSON
    - JSON inside markdown code fences
    - JSON with preamble text
    - Partial/malformed JSON (falls back to plain text)
    - Complete plain text (no JSON at all)
    """
    resp = StructuredResponse(raw=raw_text)

    json_str = _extract_json_str(raw_text)
    data = None

    if json_str:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            fixed = _try_fix_json(json_str)
            if fixed is not None:
                data = fixed

    # Validate: parsed dict must have a dialogue/text key to be the right object
    if isinstance(data, dict) and not (data.get("dialogue") or data.get("text")):
        data = None  # Matched a sub-object (e.g. PAD), not the full response

    # Fallback 1: YAML-like format (key: value lines)
    if not isinstance(data, dict):
        yaml_data = _parse_yaml_like(raw_text)
        if yaml_data and yaml_data.get("dialogue"):
            data = yaml_data
            logger.debug("response_parser.yaml_fallback_used")

    # Fallback 2: Concatenated JSON fragments — dialogue{"action":"..."}{"pad":{...}}
    if not isinstance(data, dict):
        concat_data = _parse_concat_json(raw_text)
        if concat_data and concat_data.get("dialogue"):
            data = concat_data
            logger.debug("response_parser.concat_fallback_used")

    if not isinstance(data, dict):
        logger.debug("response_parser.no_structured_data")
        resp.dialogue = _clean_legacy_text(raw_text)
        resp.parsed_ok = False
        return resp

    # Extract fields with defaults
    resp.dialogue = str(data.get("dialogue", data.get("text", ""))).strip()
    resp.action = str(data.get("action", "")).strip()
    resp.thought = str(data.get("thought", data.get("inner_thought", ""))).strip()
    resp.stance = str(data.get("stance", "")).strip()

    # PAD
    pad_raw = data.get("pad", {})
    if isinstance(pad_raw, dict):
        resp.pad = PADValues(
            p=_safe_float(pad_raw.get("p", 0), lo=-1, hi=1),
            a=_safe_float(pad_raw.get("a", 0), lo=-1, hi=1),
            d=_safe_float(pad_raw.get("d", 0), lo=-1, hi=1),
        ).clamp()
    elif isinstance(pad_raw, (list, tuple)) and len(pad_raw) >= 3:
        resp.pad = PADValues(
            p=_safe_float(pad_raw[0], lo=-1, hi=1),
            a=_safe_float(pad_raw[1], lo=-1, hi=1),
            d=_safe_float(pad_raw[2], lo=-1, hi=1),
        ).clamp()

    # Voice
    voice_raw = data.get("voice", {})
    if isinstance(voice_raw, dict):
        resp.voice = VoiceParams(
            speed=_safe_float(voice_raw.get("speed", 1.0), default=1.0, lo=0.7, hi=1.3),
            pitch=_safe_float(voice_raw.get("pitch", 0.0), default=0.0, lo=-0.15, hi=0.15),
            tone=str(voice_raw.get("tone", "")),
        )

    # If dialogue is empty but we have raw text, fall back
    if not resp.dialogue:
        resp.dialogue = _clean_legacy_text(raw_text)
        resp.parsed_ok = False

    return resp


def _clean_legacy_text(text: str) -> str:
    """Clean up plain-text LLM response (strip emotion tags, etc.)."""
    from ai_core.services.emotion import extract_inline_emotion
    cleaned, _ = extract_inline_emotion(text)
    # Also strip action tags in parens for the dialogue portion
    cleaned = re.sub(r"[（(][^）)]{1,40}[）)]", "", cleaned)
    return cleaned.strip()


def _try_fix_json(s: str) -> dict | None:
    """Attempt to fix common LLM JSON mistakes."""
    # Trailing comma before closing brace
    fixed = re.sub(r",\s*}", "}", s)
    fixed = re.sub(r",\s*]", "]", fixed)

    # Single quotes instead of double
    if '"' not in fixed:
        fixed = fixed.replace("'", '"')

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return None


# ── YAML-like fallback parser ──
# Some models output:
#   dialogue text
#   thought: inner thought
#   action: action text
#   pad: {"p":0.2,"a":0.0,"d":0.7}
#   voice: {"speed":1.0,"pitch":0.0,"tone":"gentle"}
#   stance: caring

def _parse_concat_json(raw: str) -> dict | None:
    """Parse concatenated JSON fragments: dialogue{"key":"val"}{"key":"val"}...

    Some models output: spoken text{"action":"..."}{"thought":"..."}{"pad":{...}}{"voice":{...}}{"stance":"..."}
    """
    # Find the first { that starts a JSON fragment
    first_brace = raw.find("{")
    if first_brace == -1:
        return None

    dialogue = raw[:first_brace].strip()
    if not dialogue:
        return None

    json_part = raw[first_brace:]
    result: dict = {"dialogue": dialogue}

    # Extract all top-level JSON objects from the remaining text
    # Pattern: {"key": value} possibly concatenated
    pos = 0
    while pos < len(json_part):
        if json_part[pos] != "{":
            pos += 1
            continue

        # Find matching closing brace (handle nested braces)
        depth = 0
        start = pos
        for i in range(start, len(json_part)):
            if json_part[i] == "{":
                depth += 1
            elif json_part[i] == "}":
                depth -= 1
                if depth == 0:
                    fragment = json_part[start:i + 1]
                    try:
                        obj = json.loads(fragment)
                        if isinstance(obj, dict):
                            result.update(obj)
                    except json.JSONDecodeError:
                        pass
                    pos = i + 1
                    break
        else:
            break  # Unbalanced braces

    # Must have found at least one field beyond dialogue
    if len(result) <= 1:
        return None

    return result


_FIELD_RE = re.compile(
    r"^(thought|action|pad|voice|stance)\s*[:：]\s*(.+)",
    re.IGNORECASE,
)


def _parse_yaml_like(raw: str) -> dict | None:
    """Parse a YAML-like format that some models produce instead of JSON."""
    lines = raw.strip().split("\n")
    result: dict = {}
    dialogue_lines: list[str] = []
    found_fields = False

    for line in lines:
        m = _FIELD_RE.match(line.strip())
        if m:
            found_fields = True
            key = m.group(1).lower()
            val = m.group(2).strip()

            if key in ("pad", "voice"):
                # Try to parse as JSON object
                try:
                    result[key] = json.loads(val)
                except json.JSONDecodeError:
                    result[key] = val
            else:
                result[key] = val
        elif not found_fields:
            # Lines before any field are dialogue
            dialogue_lines.append(line)

    if not found_fields:
        return None

    result["dialogue"] = "\n".join(dialogue_lines).strip()
    return result

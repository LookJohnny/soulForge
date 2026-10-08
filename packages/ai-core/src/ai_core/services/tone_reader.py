"""Per-sentence tone readouts for spoken dialogue, from a local Nous Tone server.

The readout probe reads the model's residual stream, not keywords: each dialogue
line is forced in as a reply to the user's words under the probe's reference
prompt (``POST /v1/tone/read``), so the reading reflects what is said rather than
the JSON decision that carried it. Each sentence gets its own reading, shrunk
toward the line's mean so a short sentence keeps the reply's tone.

Sentences are split exactly like the gateway splits them for TTS, so every
synthesized clip has a matching expression cue. A failed or slow read returns
None: expressions then fall back to PAD, and speech is never held up.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

import httpx
import structlog

from ai_core.config import settings

logger = structlog.get_logger()

# Same pattern as the gateway's per-sentence TTS split
# (gateway/pipeline/orchestrator.py, Character Runtime path).
SENTENCE_RE = re.compile(r"[^。！？!?]+[。！？!?]*")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of the sentences the gateway will synthesize."""
    return [m.span() for m in SENTENCE_RE.finditer(text) if m.group().strip()]


def tone_base_url() -> str:
    """NOUS_TONE_URL, or the server root of LLM_BASE_URL when chat runs on Nous Tone."""
    if settings.nous_tone_url:
        return settings.nous_tone_url.rstrip("/")
    if settings.llm_provider != "nous_tone":
        return ""
    from ai_core.services.llm.registry import PROVIDER_CONFIGS

    base = settings.llm_base_url or PROVIDER_CONFIGS["nous_tone"]["base_url"]
    parts = urlsplit(base)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


class ToneReader:
    def __init__(self, base_url: str | None = None, timeout: float | None = None, client=None):
        self.base_url = tone_base_url() if base_url is None else base_url.rstrip("/")
        self.timeout = settings.nous_tone_read_timeout if timeout is None else timeout
        # Local server: never route through a system proxy.
        self._client = client or httpx.AsyncClient(proxy=None, timeout=self.timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url) and settings.nous_tone_read_enabled

    async def read_line(self, text: str, user_text: str = "") -> dict | None:
        """{"readout", "expression", "sentences": [{"text", "readout", "expression"}]} or None."""
        spans = sentence_spans(text)
        if not self.enabled or not spans:
            return None
        try:
            resp = await self._client.post(
                f"{self.base_url}/v1/tone/read",
                json={"text": text, "segments": [list(s) for s in spans], "user": user_text[:4000]},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            segments = data["segments"]
            if len(segments) != len(spans):
                raise ValueError("segment count mismatch")
            return {
                "readout": data["readout"],
                "expression": data["expression"],
                "sentences": [
                    {"text": text[s:e], "readout": seg["readout"], "expression": seg["expression"]}
                    for (s, e), seg in zip(spans, segments, strict=True)
                ],
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("tone_reader.read_failed", error=str(exc)[:200], base_url=self.base_url)
            return None

"""Device TTS playback channel — the single owner of the xiaozhi playback
protocol dance.

Every spoken reply follows the same wire sequence:

    "start" → per sentence: "sentence"(text) → "sentence_start" → Opus frames
    → "stop" → wait for the device to drain its audio buffer

Before this module the dance was copy-pasted across six call sites (four
respond paths in server.py, quick replies, and the life loop) with slightly
drifting pacing/interrupt behaviour. PlaybackChannel owns:

- claiming/releasing ``session._playing`` / ``_interrupted`` / ``_interrupt_count``
- frame pacing: PRE_BUFFER frames sent immediately, then one per FRAME_SECS
- barge-in checks between frames
- the pre-stop settle delay and the post-stop playback wait formula
- first-frame timing for latency metrics

Callers keep pipeline concerns (chunk streaming, receipts, history).
"""

import asyncio
import time

import structlog

from gateway.protocols.base import MessageType, OutboundMessage

logger = structlog.get_logger()

FRAME_SECS = 0.06  # one Opus frame's worth of audio (60ms)
PRE_BUFFER_FRAMES = 5  # sent immediately so the device can start playing
SETTLE_SECS = 0.42  # pause before "stop" on normal completion
INTERRUPT_SETTLE_SECS = 0.2  # pause after "stop" when barged in
DRAIN_MARGIN_SECS = 2.0  # device-side buffer already consumed while sending
MIN_DRAIN_SECS = 0.5

# Optional observer of the playing state (claimed playback only). The
# gateway-side face engine uses this to hand the mouth to the firmware's
# speaking animation during TTS. Set once at startup; never raises.
speaking_hook = None


class PlaybackChannel:
    """One TTS playback transaction to a device.

    Use as an async context manager: entering claims the session playing
    state; exiting always releases it, even on error.
    """

    def __init__(
        self,
        ws,
        adapter,
        session,
        *,
        pace: bool = True,
        check_interrupt: bool = True,
        claim: bool = True,
    ):
        self._ws = ws
        self._adapter = adapter
        self._session = session
        self._pace = pace
        self._check_interrupt = check_interrupt
        self._claim = claim  # False: don't touch session._playing (e.g. text-chat path)
        self.total_frames = 0
        self.first_frame_at: float | None = None  # time.monotonic() of first frame
        self._frames_sent = 0  # prebuffer counter, global across the response

    # ── session playing state ──────────────────────────────

    async def __aenter__(self) -> "PlaybackChannel":
        if self._claim:
            s = self._session
            s._playing = True
            s._interrupted = False
            s._interrupt_count = 0
            if speaking_hook:
                try:
                    speaking_hook(True)
                except Exception:
                    logger.debug("playback.speaking_hook_error", exc_info=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._claim:
            s = self._session
            s._playing = False
            s._interrupted = False
            s._interrupt_count = 0
            if speaking_hook:
                try:
                    speaking_hook(False)
                except Exception:
                    logger.debug("playback.speaking_hook_error", exc_info=True)

    @property
    def interrupted(self) -> bool:
        return bool(getattr(self._session, "_interrupted", False))

    # ── wire protocol ──────────────────────────────────────

    async def _send_state(self, state: str) -> None:
        msg = OutboundMessage(type=MessageType.TEXT, payload="", metadata={"state": state})
        await self._ws.send_text(await self._adapter.encode(msg))

    async def send_start(self) -> None:
        await self._send_state("start")

    async def send_sentence(self, text: str) -> None:
        msg = OutboundMessage(type=MessageType.TEXT, payload=text, metadata={"state": "sentence"})
        await self._ws.send_text(await self._adapter.encode(msg))

    async def send_sentence_start(self) -> None:
        await self._send_state("sentence_start")

    async def send_frames(self, frames: list[bytes], *, pace: bool | None = None) -> bool:
        """Send raw Opus frames with prebuffer + realtime pacing.

        Returns False if playback was interrupted mid-way (barge-in).
        """
        do_pace = self._pace if pace is None else pace
        for frame in frames:
            if self._check_interrupt and self.interrupted:
                return False
            if self.first_frame_at is None:
                self.first_frame_at = time.monotonic()
            await self._ws.send_bytes(frame)
            self.total_frames += 1
            if do_pace and self._frames_sent >= PRE_BUFFER_FRAMES:
                await asyncio.sleep(FRAME_SECS)
            else:
                self._frames_sent += 1
        return True

    async def send_clip(
        self,
        audio_data: bytes,
        *,
        sentence_start: bool = True,
        pace: bool | None = None,
    ) -> bool:
        """Encode one audio clip via the adapter and stream it.

        Returns False if interrupted.
        """
        if sentence_start:
            await self.send_sentence_start()
        raw = await self._adapter.encode(
            OutboundMessage(type=MessageType.AUDIO, payload=audio_data)
        )
        if isinstance(raw, list):
            return await self.send_frames(raw, pace=pace)
        if isinstance(raw, bytes):
            if self.first_frame_at is None:
                self.first_frame_at = time.monotonic()
            await self._ws.send_bytes(raw)
        return True

    # ── completion ─────────────────────────────────────────

    def drain_secs(self) -> float:
        """How long the device still needs to finish playing buffered audio."""
        return max(self.total_frames * FRAME_SECS - DRAIN_MARGIN_SECS, MIN_DRAIN_SECS)

    async def finish(self, *, wait_drain: bool = True, settle: bool = True) -> None:
        """Send "stop" with the settle timing the firmware expects, then
        optionally wait for the device-side buffer to drain.

        Interrupted: stop immediately, short settle, no drain wait.
        Normal: settle first (audio tail), then stop, then drain wait.
        """
        if self._check_interrupt and self.interrupted:
            await self._send_state("stop")
            await asyncio.sleep(INTERRUPT_SETTLE_SECS)
            return
        if settle:
            await asyncio.sleep(SETTLE_SECS)
        await self._send_state("stop")
        if wait_drain and self.total_frames:
            await asyncio.sleep(self.drain_secs())

    def first_frame_ms(self, t_ref: float) -> float | None:
        """Milliseconds from t_ref to the first frame, or None if no audio."""
        if self.first_frame_at is None:
            return None
        return (self.first_frame_at - t_ref) * 1000

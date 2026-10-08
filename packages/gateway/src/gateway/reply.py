"""One way to deliver a character's reply to a device.

Voice (streaming ASR), batch ASR and text turns used to be three ~120-line copies
of the same loop: receipts, side channels, expression cues, sentences, clips,
latency, history and the error tail. A fix in one (an expression cue, a receipt
rule) had to be repeated in all three. They now share ``render_turn``; a
``TurnStyle`` says how the device plays it.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import structlog

from gateway.playback import PlaybackChannel
from gateway.protocols.base import MessageType, OutboundMessage

logger = structlog.get_logger()


def speech_lock(session) -> asyncio.Lock:
    """One reply plays at a time per session: user turns, unsolicited runtime
    speech and touch replies never interleave on the speaker (text turns do not
    claim the mic flag, so the flag alone could not serialize them)."""
    lock = getattr(session, "_speech_lock", None)
    if lock is None:
        lock = session._speech_lock = asyncio.Lock()
    return lock


@dataclass
class TurnStyle:
    # voice: paced realtime playback, barge-in, claims the mic-suppression flag.
    # text: the device buffers freely, no barge-in, the mic flag is untouched.
    voice: bool
    route: str | None = None  # latency route (voice turns)
    filler: bytes | None = None  # instant "嗯？" while the brain works (voice)
    user_text: str = ""  # known up front, or learned from the done chunk (batch ASR)


@dataclass
class TurnResult:
    full_text: str = ""
    user_text: str = ""
    interrupted: bool = False
    need_vision: str | None = None  # Path A asked for a camera frame
    failed: bool = False
    frames: int = 0


async def render_turn(server, ws, adapter, session, chunks: AsyncIterator, style: TurnStyle) -> TurnResult:
    """Play one turn's chunks on the device, then settle receipts and history."""
    from gateway.handlers.audio_codec import StreamingMp3OpusEncoder

    result = TurnResult(user_text=style.user_text)
    receipts: set[str] = set()
    # Latency is measured from VAD speech-end when the turn came from the mic.
    t_speech_end = getattr(session, "_t_speech_end", None)
    session._t_speech_end = None
    t_ref = t_speech_end if t_speech_end is not None else time.monotonic()
    first_chunk_ms = None
    core_stages = None
    options = {} if style.voice else {"pace": False, "check_interrupt": False, "claim": False}
    try:
        async with speech_lock(session), PlaybackChannel(ws, adapter, session, **options) as pb:
            await pb.send_start()
            if style.filler:
                try:
                    await pb.send_clip(style.filler, pace=False)
                except Exception:
                    logger.exception("gateway.filler_error")
                # the filler is not the reply's first word; the mouth idles until it starts
                pb.mark_aside_done()

            encoder = None
            try:
                async for chunk in chunks:
                    if chunk.playback_receipt:
                        receipts.add(chunk.playback_receipt)
                    if chunk.is_done:
                        result.full_text = chunk.full_text or result.full_text
                        result.user_text = chunk.user_text or result.user_text
                        core_stages = chunk.stages
                        break
                    if first_chunk_ms is None:
                        first_chunk_ms = (time.monotonic() - t_ref) * 1000
                    if pb.interrupted:
                        logger.info("gateway.interrupted by user")
                        result.interrupted = True
                        break

                    if chunk.kind == "emotion":
                        await server._send_emotion(ws, adapter, chunk)
                    elif chunk.kind == "relationship":
                        server._remember_energy(session, chunk.relationship)
                        await server._send_relationship(ws, adapter, chunk)
                    elif chunk.kind == "event":
                        await server._send_event(ws, adapter, chunk)
                    elif chunk.kind == "need_vision":
                        result.need_vision = chunk.text
                        break
                    elif chunk.kind == "audio_chunk":
                        if chunk.audio_data:
                            if encoder is None:
                                encoder = StreamingMp3OpusEncoder()
                                await pb.send_sentence_start()
                            frames = await encoder.feed(chunk.audio_data)
                            if frames and not await pb.send_frames(frames):
                                result.interrupted = True
                    elif chunk.kind == "audio_end":
                        if encoder is not None:
                            frames = await encoder.finish()
                            encoder = None
                            if frames and not await pb.send_frames(frames):
                                result.interrupted = True
                    else:  # a sentence: its expression cue, its text, its clip
                        await server._send_expression(ws, adapter, chunk)
                        await pb.send_sentence(chunk.text)
                        result.full_text += chunk.text
                        if chunk.audio_data and not await pb.send_clip(
                            chunk.audio_data, sentence_start=style.voice
                        ):
                            result.interrupted = True
                    if result.interrupted:
                        break
            finally:
                # Leaving the loop early must close the producer (an open HTTP
                # stream on the legacy path) instead of waiting for GC.
                aclose = getattr(chunks, "aclose", None)
                if aclose is not None:
                    with contextlib.suppress(Exception):
                        await aclose()

            if encoder is not None and not result.interrupted:
                tail = await encoder.finish()
                if tail:
                    await pb.send_frames(tail)
            if style.route:
                server._record_voice_turn(
                    session,
                    t_ref,
                    first_chunk_ms,
                    pb.first_frame_ms(t_ref),
                    core_stages,
                    result.interrupted,
                    route=style.route,
                )
            if style.voice:
                await pb.finish()
            else:
                await pb.finish(settle=False)
            result.frames = pb.total_frames
        await server._confirm_playback_receipts(
            receipts,
            played=not result.interrupted,
            detail="user barge-in interrupted playback" if result.interrupted else "",
        )
        receipts.clear()
    except asyncio.CancelledError:
        # aborted by the user or the connection closed: nothing more will play
        await server._confirm_playback_receipts(receipts, played=False, detail="turn cancelled")
        raise
    except Exception:
        detail = "gateway playback error" if style.voice else "gateway text playback error"
        await server._confirm_playback_receipts(receipts, played=False, detail=detail)
        logger.exception("gateway.pipeline_error")
        result.failed = True
        with contextlib.suppress(Exception):
            out = OutboundMessage(type=MessageType.CONTROL, payload={"type": "tts", "state": "stop"})
            await ws.send_text(await adapter.encode(out))
        return result

    if result.user_text:
        await server.session_manager.add_to_history(session.session_id, "user", result.user_text)
    if result.full_text:
        await server.session_manager.add_to_history(session.session_id, "assistant", result.full_text)
    session._last_activity = time.monotonic()
    if getattr(session, "_life", None):
        session._life.notify_activity()
    logger.info(
        "gateway.responding done",
        text=result.full_text[:50],
        frames=result.frames,
        interrupted=result.interrupted,
    )
    return result

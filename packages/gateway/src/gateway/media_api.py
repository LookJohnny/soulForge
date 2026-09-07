"""Authenticated media bodies over NDJSON; one Runtime decision per user turn.

Audio is currently synthesized per sentence, not token-streamed cognition.
One receipt covers the complete turn. Consumers acknowledge only after both
the stream's done marker and actual playback; byte delivery is never playback.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import time
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.responses import StreamingResponse

from gateway.config import settings
from gateway.http_auth import require_gateway_token
from gateway.pipeline.character_bridge import CharacterBridge, RuntimeNoDialogueError
from gateway.session import Session


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSession(StrictRequest):
    body_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class TurnRequest(StrictRequest):
    text: str = Field(min_length=1, max_length=4000)
    turn_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class InterruptRequest(StrictRequest):
    turn_id: str = Field(min_length=1, max_length=128)


class ReceiptRequest(StrictRequest):
    receipt_id: str = Field(min_length=1, max_length=128)
    played: StrictBool
    detail: str = Field(default="", max_length=256)


class TranscribeRequest(StrictRequest):
    audio_base64: str = Field(min_length=1, max_length=1_280_000)
    format: str = "pcm16"
    sample_rate: int = 16000
    channels: int = 1


@dataclass
class Receipt:
    turn_id: str
    commands: tuple[str, ...]
    bridge: object
    ready: bool = False


@dataclass
class Turn:
    turn_id: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=4))
    task: asyncio.Task | None = None
    cancelled: bool = False


@dataclass
class MediaSession:
    session: Session
    body_label: str
    bridge: object | None = None
    identity: dict = field(default_factory=dict)
    active: Turn | None = None
    turns: set[str] = field(default_factory=set)
    receipts: dict[str, Receipt] = field(default_factory=dict)
    touched: float = field(default_factory=time.monotonic)
    closed: bool = False
    asr_task: asyncio.Task | None = None
    interrupting: bool = False
    binding: asyncio.Lock = field(default_factory=asyncio.Lock)
    control: asyncio.Lock = field(default_factory=asyncio.Lock)


class MediaStreamResponse(StreamingResponse):
    """Also close the producer when ASGI send fails before/during iteration."""

    def __init__(self, *args, cleanup, **kwargs):
        super().__init__(*args, **kwargs)
        self.cleanup = cleanup

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await asyncio.shield(self.body_iterator.aclose())
            await asyncio.shield(self.cleanup())


class MediaSessions:
    def __init__(
        self,
        orchestrator,
        *,
        bridge_factory=CharacterBridge,
        turn_timeout=90.0,
        idle_timeout=600.0,
        max_sessions=32,
    ):
        self.orchestrator = orchestrator
        self.bridge_factory = bridge_factory
        self.turn_timeout = turn_timeout
        self.idle_timeout = idle_timeout
        self.max_sessions = max_sessions
        self.sessions: dict[str, MediaSession] = {}

    async def _bind(self, entry):
        async with entry.binding:
            if entry.closed:
                raise RuntimeError("Media session closed")
            if entry.bridge is not None:
                return
            bridge = self.bridge_factory(
                body_id=f"media-{entry.body_label[:32]}-{uuid.uuid4().hex}",
                timeout_s=settings.character_runtime_timeout_s,
                autonomous_speech=False,
            )
            try:
                identity = await self.orchestrator._resolve_runtime_identity(
                    bridge.body_id,
                    entry.session.session_id,
                    agent_id=bridge.agent_id,
                )
                await bridge.start()
                if entry.closed:
                    raise RuntimeError("Media session closed")
            except BaseException:
                await bridge.close()
                raise
            entry.bridge, entry.identity = bridge, identity
            entry.session.character_id = identity["character_id"]
            entry.session.end_user_id = identity["user_id"]
            entry.session.brand_id = settings.soulforge_brand_id

    async def create(self, body_id):
        if not (
            settings.character_runtime_url
            and settings.soulforge_brand_id
            and settings.service_token
        ):
            raise HTTPException(503, "Unified Runtime is not configured")
        if len(self.sessions) >= self.max_sessions:
            raise HTTPException(503, "Media session capacity reached")
        sid = uuid.uuid4().hex
        entry = MediaSession(Session(sid, f"media-{sid}", protocol="media"), body_id)
        # Reserve capacity before awaits; no device/user identity comes from the body label.
        self.sessions[sid] = entry
        try:
            async with asyncio.timeout(settings.character_runtime_timeout_s + 5):
                await self._bind(entry)
        except (Exception, asyncio.CancelledError) as exc:
            await self.close(sid)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise HTTPException(502, "Runtime identity or connection unavailable") from None
        return {"session_id": sid, "body_id": entry.bridge.body_id}

    def get(self, sid):
        entry = self.sessions.get(sid)
        if entry is None or entry.closed:
            raise HTTPException(404, "Media session not found")
        entry.touched = time.monotonic()
        return entry

    async def _settle(self, entry, receipt_id, *, played, detail):
        receipt = entry.receipts.pop(receipt_id, None)
        if receipt is None:
            return False
        # Consume before awaiting, including transport failures: no duplicate acknowledgements.
        for command in receipt.commands:
            await receipt.bridge.confirm_spoken(command, played=played, detail=detail)
        return True

    async def _fail_receipts(self, entry, turn_id, detail):
        for rid, receipt in list(entry.receipts.items()):
            if turn_id is None or receipt.turn_id == turn_id:
                try:
                    await self._settle(entry, rid, played=False, detail=detail)
                except Exception:
                    pass  # disconnected body cannot truthfully acknowledge playback

    async def _retire(self, entry, bridge):
        if entry.bridge is bridge:
            entry.bridge = None
            entry.identity = {}
        if bridge is not None:
            try:
                await bridge.close()
            except Exception:
                pass

    @staticmethod
    def _finish_error(turn, error):
        while not turn.queue.empty():
            turn.queue.get_nowait()
        turn.queue.put_nowait({"type": "error", "turn_id": turn.turn_id, "error": error})
        turn.queue.put_nowait(None)

    async def _produce(self, entry, turn, text):
        bridge = None
        try:
            async with asyncio.timeout(self.turn_timeout):
                await self._bind(entry)
                bridge = entry.bridge
                decision = await bridge.process_utterance(
                    text,
                    payload={
                        "identity": dict(entry.identity),
                        # Runtime preserves only 1-64 alphanumeric/-/_ correlation IDs.
                        # Raw session/turn IDs can contain punctuation or exceed that
                        # limit, causing speech to be routed to the unsolicited queue.
                        "event_id": "media-"
                        + uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"soulforge:media:{entry.session.session_id}:{turn.turn_id}",
                        ).hex,
                    },
                )
                if turn.cancelled or entry.closed:
                    raise asyncio.CancelledError
                actions = decision.get("commands", [])
                cognitive = next(
                    (
                        c.get("params", {}).get("cognitive_state")
                        for c in actions
                        if c.get("params", {}).get("cognitive_state")
                    ),
                    {},
                )
                command_ids = tuple(
                    c["command_id"] for c in actions if c.get("dialogue") and c.get("command_id")
                )
                rid = uuid.uuid4().hex if command_ids else None
                if rid:
                    entry.receipts[rid] = Receipt(turn.turn_id, command_ids, bridge)
                await turn.queue.put(
                    {
                        "type": "decision",
                        "turn_id": turn.turn_id,
                        "emotion": cognitive.get("emotion", ""),
                        "pad": cognitive.get("pad"),
                        "actions": actions,
                    }
                )
                count = 0
                for command in actions or [{"dialogue": decision.get("text", "")}]:
                    emotion = self.orchestrator._beat_emotion([command])
                    for sentence in re.findall(
                        r"[^。！？!?]+[。！？!?]*", command.get("dialogue") or ""
                    ):
                        if not sentence.strip():
                            continue
                        # The existing TTS-only endpoint accepts at most 500 characters.
                        for start in range(0, len(sentence), 500):
                            line = sentence[start : start + 500]
                            audio = await self.orchestrator.synthesize_tts(
                                line,
                                entry.session.character_id,
                                entry.session.brand_id,
                                emotion=emotion,
                            )
                            if turn.cancelled or entry.closed:
                                raise asyncio.CancelledError
                            if not audio:
                                raise RuntimeError("TTS returned no audio")
                            await turn.queue.put(
                                {
                                    "type": "audio",
                                    "turn_id": turn.turn_id,
                                    "text": line,
                                    "emotion": emotion or "",
                                    "audio_base64": base64.b64encode(audio).decode(),
                                    "format": "mp3",
                                    "receipt_id": rid,
                                }
                            )
                            count += 1
                if count == 0:
                    raise RuntimeError("Runtime returned no dialogue")
                if rid and rid in entry.receipts:
                    entry.receipts[rid].ready = True
                await turn.queue.put({"type": "done", "turn_id": turn.turn_id})
                await turn.queue.put(None)
        except (Exception, asyncio.CancelledError) as exc:
            turn.cancelled = True
            await self._fail_receipts(entry, turn.turn_id, "media turn interrupted or failed")
            await self._retire(entry, bridge or entry.bridge)
            self._finish_error(
                turn,
                "turn_interrupted"
                if isinstance(exc, asyncio.CancelledError)
                else "runtime_no_dialogue"
                if isinstance(exc, RuntimeNoDialogueError)
                else "turn_timeout"
                if isinstance(exc, TimeoutError)
                else "media_turn_failed",
            )
        finally:
            if entry.active is turn:
                entry.active = None
            entry.touched = time.monotonic()

    def turn(self, sid, request):
        entry = self.get(sid)
        if not request.text.strip():
            raise HTTPException(400, "Text must not be empty")
        if entry.active is not None or entry.interrupting:
            raise HTTPException(409, "Another media turn is active")
        if request.turn_id in entry.turns:
            raise HTTPException(409, "Turn was already submitted")
        if len(entry.turns) >= 256:
            raise HTTPException(409, "Open a new media session")
        entry.turns.add(request.turn_id)
        turn = entry.active = Turn(request.turn_id)
        turn.task = asyncio.create_task(self._produce(entry, turn, request.text.strip()))
        completed = False

        async def cleanup():
            if not completed:
                await self.interrupt(sid, turn.turn_id, "media stream disconnected")

        async def stream():
            nonlocal completed
            try:
                while True:
                    item = await turn.queue.get()
                    if item is None:
                        completed = True
                        break
                    if turn.cancelled and item.get("type") != "error":
                        continue
                    yield json.dumps(item, ensure_ascii=False) + "\n"
            finally:
                if not completed:
                    await asyncio.shield(cleanup())

        return MediaStreamResponse(
            stream(),
            cleanup=cleanup,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def interrupt(self, sid, turn_id, detail="media playback interrupted"):
        entry = self.sessions.get(sid)
        if entry is None or entry.closed:
            return {"ok": True, "interrupted": False}
        async with entry.control:
            return await self._interrupt(entry, turn_id, detail)

    async def _interrupt(self, entry, turn_id, detail):
        entry.touched = time.monotonic()
        turn = entry.active
        matched = turn is not None and turn.turn_id == turn_id
        had_receipts = any(r.turn_id == turn_id for r in entry.receipts.values())
        if matched:
            entry.interrupting = True
            bridge = entry.bridge
            if not turn.cancelled:
                turn.cancelled = True
                turn.task.cancel()
            try:
                await asyncio.wait({turn.task}, timeout=1.0)
                # A cancellation-resistant upstream can finish later; the epoch gate
                # prevents it publishing audio, and no next turn starts until it exits.
                await self._retire(entry, bridge)
                if turn.task.done() and entry.active is turn:
                    entry.active = None
                self._finish_error(turn, "turn_interrupted")
            finally:
                entry.interrupting = False
        await self._fail_receipts(entry, turn_id, detail)
        return {"ok": True, "interrupted": bool(matched or had_receipts)}

    async def receipt(self, sid, request):
        entry = self.get(sid)
        receipt = entry.receipts.get(request.receipt_id)
        if receipt is None:
            raise HTTPException(404, "Playback receipt not found")
        if request.played and (entry.interrupting or (entry.active and entry.active.cancelled)):
            raise HTTPException(409, "Media turn was interrupted")
        if not receipt.ready and request.played:
            raise HTTPException(409, "Media turn is not fully delivered")
        try:
            await self._settle(
                entry, request.receipt_id, played=request.played, detail=request.detail
            )
        except Exception:
            raise HTTPException(502, "Playback acknowledgement could not be delivered") from None
        return {"ok": True}

    async def transcribe(self, sid, request):
        entry = self.get(sid)
        if (request.format, request.sample_rate, request.channels) != ("pcm16", 16000, 1):
            raise HTTPException(400, "Only PCM16 little-endian mono 16kHz is supported")
        try:
            audio = base64.b64decode(request.audio_base64, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(400, "Invalid audio encoding") from None
        if not audio or len(audio) % 2 or len(audio) > 960_000:
            raise HTTPException(400, "Audio must contain at most 30 seconds of PCM16")
        if entry.asr_task and not entry.asr_task.done():
            raise HTTPException(409, "ASR is already active")
        task = entry.asr_task = asyncio.create_task(
            self.orchestrator._transcribe_audio(audio, "pcm")
        )
        try:
            async with asyncio.timeout(20):
                text = await task
            if not text or entry.closed:
                raise HTTPException(502, "ASR returned no transcript")
            return {"text": text}
        except (TimeoutError, RuntimeError):
            raise HTTPException(502, "ASR unavailable") from None
        except HTTPException:
            raise
        except asyncio.CancelledError:
            if entry.closed:
                raise HTTPException(409, "Media session was closed") from None
            raise
        except Exception:
            raise HTTPException(502, "ASR unavailable") from None
        finally:
            if entry.asr_task is task:
                entry.asr_task = None

    async def close(self, sid):
        entry = self.sessions.get(sid)
        if entry is None:
            return {"ok": True}
        async with entry.control:
            entry.closed = True
            self.sessions.pop(sid, None)
            if entry.active:
                await self._interrupt(entry, entry.active.turn_id, "media session closed")
            if entry.asr_task:
                entry.asr_task.cancel()
            await self._fail_receipts(entry, None, "media session closed")
            await self._retire(entry, entry.bridge)
        return {"ok": True}

    async def reap(self):
        for sid, entry in list(self.sessions.items()):
            if not entry.active and time.monotonic() - entry.touched > self.idle_timeout:
                await self.close(sid)

    async def close_all(self):
        for sid in list(self.sessions):
            await self.close(sid)

    async def housekeeping(self):
        while True:
            await asyncio.sleep(30)
            await self.reap()


def build_router(manager):
    router = APIRouter(prefix="/media", dependencies=[Depends(require_gateway_token)])

    @router.get("/health")
    async def health():
        runtime = bool(settings.character_runtime_url and settings.soulforge_brand_id)
        core = bool(settings.ai_core_url and settings.service_token)
        configured = runtime and core
        return {
            "service": "gateway-media",
            "protocol": "ndjson-v1",
            "ready": configured,
            "configured": configured,
            "readiness_scope": "configuration_only",
            "end_to_end_verified": False,
            "dependencies": {
                "runtime": {"configured": runtime, "reachable": None},
                "ai_core": {"configured": core, "reachable": None},
                "asr": {"configured": bool(settings.dashscope_api_key)},
            },
        }

    @router.post("/sessions")
    async def create(request: CreateSession):
        await manager.reap()
        return await manager.create(request.body_id)

    @router.post("/sessions/{sid}/turn")
    async def turn(sid: str, request: TurnRequest):
        return manager.turn(sid, request)

    @router.post("/sessions/{sid}/interrupt")
    async def interrupt(sid: str, request: InterruptRequest):
        return await manager.interrupt(sid, request.turn_id)

    @router.post("/sessions/{sid}/receipt")
    async def receipt(sid: str, request: ReceiptRequest):
        return await manager.receipt(sid, request)

    @router.post("/sessions/{sid}/transcribe")
    async def transcribe(sid: str, request: TranscribeRequest):
        return await manager.transcribe(sid, request)

    @router.post("/sessions/{sid}/close")
    async def close(sid: str):
        return await manager.close(sid)

    return router

"""CharacterBridge: the gateway as a *voice body* of the Character Runtime.

Single-decision-path wiring (Phase 6):

    audio frames -> (existing Opus/VAD/StreamingASR) -> transcript
        -> WireEvent(user_utterance)  ------------->  SoulForge Runtime Server
        <- ActionCommand(dialogue, correlation_id) <-  (the ONLY decision maker)
    dialogue -> existing TTS;  motion commands flow to other bodies unchanged.

When `settings.character_runtime_url` is set the legacy ai-core /pipeline/chat
dialogue path is bypassed entirely — one utterance, one LLM decision.
The bridge holds no persona/memory state; it is a body, not a brain.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import websockets

from gateway.config import settings


def _frame(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


@dataclass
class CharacterBridge:
    url: str = ""
    agent_id: str = ""
    timeout_s: float = 12.0
    body_id: str = field(default_factory=lambda: f"gateway-voice-{uuid.uuid4().hex[:6]}")

    _socket: Any = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _reader_task: asyncio.Task | None = None
    _waiters: dict[str, asyncio.Queue] = field(default_factory=dict)
    _unsolicited: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=128),
    )

    def __post_init__(self) -> None:
        self.url = self.url or settings.character_runtime_url
        self.agent_id = self.agent_id or settings.character_runtime_agent
        self.timeout_s = self.timeout_s or settings.character_runtime_timeout_s

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    # ------------------------------------------------------------ connection
    async def _ensure_connected(self):
        async with self._connect_lock:
            if (self._socket is not None and self._reader_task is not None
                    and not self._reader_task.done()):
                try:
                    await self._socket.ping()
                    return self._socket
                except Exception:
                    await self._disconnect()
            socket = await websockets.connect(f"{self.url.rstrip('/')}/body")
            await socket.send(_frame({
                "type": "hello",
                "protocol": "0.2",
                "body_id": self.body_id,
                "backend": "voice",
                "agent_ids": [self.agent_id],
                "manifest": {
                    # This connection only renders speech. Gaze, nods, waits and
                    # motion are executed (and acknowledged) by their real bodies.
                    "supported_steps": ["speak_line"],
                    # Speech may accompany any template, so do not template-filter
                    # it. Step negotiation above is the fail-closed capability gate.
                    "supported_templates": [],
                    "features": {
                        "speech": True,
                        "speech_only": True,
                        "gaze": False,
                        "nav": False,
                    },
                },
            }))
            welcome = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
            if welcome.get("type") != "welcome":
                await socket.close()
                raise ConnectionError(f"runtime server refused hello: {welcome}")
            self._socket = socket
            self._reader_task = asyncio.create_task(
                self._reader_loop(socket), name=f"character-voice-{self.body_id}",
            )
            return socket

    async def start(self) -> None:
        """Keep the voice body online so visual/system events can speak too."""
        await self._ensure_connected()

    async def _reader_loop(self, socket) -> None:
        try:
            async for raw in socket:
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(data, dict):
                    continue
                if (data.get("type") != "action"
                        or data.get("agent_id") != self.agent_id
                        or not data.get("dialogue")):
                    continue
                correlation = data.get("correlation_id")
                waiter = self._waiters.get(correlation)
                if waiter is None and self._unsolicited.full():
                    await socket.send(_frame({
                        "type": "observation",
                        "command_id": data.get("command_id", ""),
                        "agent_id": self.agent_id,
                        "status": "rejected",
                        "detail": "voice playback queue full",
                        "body_id": self.body_id,
                    }))
                    continue
                # Receipt only. Terminal status comes from actual playback.
                await socket.send(_frame({
                    "type": "observation",
                    "command_id": data.get("command_id", ""),
                    "agent_id": self.agent_id,
                    "status": "accepted",
                    "body_id": self.body_id,
                }))
                if waiter is not None:
                    await waiter.put(data)
                else:
                    await self._unsolicited.put(data)
        except (websockets.ConnectionClosed, OSError):
            pass
        finally:
            if self._socket is socket:
                self._socket = None

    # ---------------------------------------------------------------- decide
    async def process_utterance(self, text: str, *, payload: dict[str, Any] | None = None,
                                ) -> dict[str, Any]:
        """Send one user utterance, collect this decision's dialogue commands.

        Returns {"text": str, "correlation_id": str|None, "commands": [...]} in a
        shape orchestrator can hand to the existing TTS stage unchanged.
        """
        async with self._lock:                     # one in-flight decision per body
            socket = await self._ensure_connected()
            event_payload = dict(payload or {})
            event_id = event_payload.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                event_id = uuid.uuid4().hex[:12]
            event_payload["event_id"] = event_id
            inbox: asyncio.Queue = asyncio.Queue()
            self._waiters[event_id] = inbox
            dialogue_parts: list[str] = []
            commands: list[dict[str, Any]] = []
            loop = asyncio.get_event_loop()
            deadline = loop.time() + self.timeout_s
            # collect until the decision's dialogue arrives (correlation closes
            # after a short quiet period) or the deadline hits
            quiet_after = None
            try:
                await socket.send(_frame({
                    "type": "event", "kind": "user_utterance", "source": "user",
                    "text": text, "target_agent": self.agent_id,
                    "payload": event_payload,
                }))
                while loop.time() < deadline:
                    budget = (quiet_after or deadline) - loop.time()
                    if budget <= 0:
                        break
                    try:
                        data = await asyncio.wait_for(inbox.get(), timeout=budget)
                    except asyncio.TimeoutError:
                        break
                    commands.append(data)
                    dialogue_parts.append(data["dialogue"])
                    quiet_after = loop.time() + 0.6      # flush trailing speech
            finally:
                self._waiters.pop(event_id, None)
            return {"text": "".join(dialogue_parts), "correlation_id": event_id,
                    "commands": commands}

    async def next_unsolicited(self, *, timeout_s: float | None = None) -> dict[str, Any]:
        """Wait for dialogue caused by perception/system events, not a voice turn."""
        await self._ensure_connected()
        if timeout_s is None:
            return await self._unsolicited.get()
        return await asyncio.wait_for(self._unsolicited.get(), timeout=timeout_s)

    async def confirm_spoken(
        self,
        command_id: str,
        *,
        played: bool = True,
        detail: str = "",
    ) -> None:
        """Report the terminal speech result after downstream playback.

        ``played=False`` is an honest interruption (disconnect, barge-in, or
        decoder failure); synthesis alone is never treated as completion.
        """
        if self._socket is None or not command_id:
            return
        await self._socket.send(_frame({
            "type": "observation", "command_id": command_id,
            "agent_id": self.agent_id,
            "status": "done" if played else "interrupted",
            "detail": detail,
            "body_id": self.body_id,
        }))

    async def close(self) -> None:
        await self._disconnect()

    async def _disconnect(self) -> None:
        socket, self._socket = self._socket, None
        task, self._reader_task = self._reader_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if socket is not None:
            await socket.close()

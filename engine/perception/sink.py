"""Production bridge from PerceptionRuntime events to Character Runtime WS."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

import websockets

from engine.perception.models import PerceptionEvent
from engine.server.protocol import encode


@dataclass
class RuntimePerceptionSink:
    """Bounded asynchronous ``PerceptionRuntime.emit`` callback.

    ``start`` establishes the Character Runtime control connection.  The
    synchronous ``emit`` method is safe to call from camera/audio worker
    threads; it transfers events onto the owning asyncio loop without carrying
    raw media bytes.  Transport failures reconnect with bounded backoff.
    """

    runtime_url: str
    queue_limit: int = 256
    reconnect_delay_s: float = 0.1
    sent: int = 0
    dropped: int = 0
    reconnects: int = 0
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _queue: asyncio.Queue[PerceptionEvent] | None = field(default=None, init=False, repr=False)
    _socket: Any = field(default=None, init=False, repr=False)
    _worker: asyncio.Task | None = field(default=None, init=False, repr=False)
    _closing: bool = field(default=False, init=False, repr=False)

    @property
    def control_url(self) -> str:
        return f"{self.runtime_url.rstrip('/')}/control"

    async def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self.queue_limit)
        self._closing = False
        # Fail startup explicitly instead of silently capturing media while no
        # Character Runtime is reachable.
        self._socket = await websockets.connect(self.control_url)
        self._worker = asyncio.create_task(self._run(), name="perception-runtime-sink")

    def emit(self, event: PerceptionEvent) -> None:
        """Queue one structured event; compatible with PerceptionRuntime.emit."""
        if self._loop is None or self._queue is None or self._closing:
            raise RuntimeError("RuntimePerceptionSink is not started")

        def enqueue() -> None:
            if self._queue is None or self._closing:
                self.dropped += 1
                return
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                self.dropped += 1

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is self._loop:
            enqueue()
        else:
            self._loop.call_soon_threadsafe(enqueue)

    async def drain(self) -> None:
        if self._queue is not None:
            await self._queue.join()

    async def close(self) -> None:
        self._closing = True
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        self._worker = None
        await self._close_socket()
        self._queue = None
        self._loop = None

    def health(self) -> dict[str, Any]:
        return {
            "running": self._worker is not None and not self._worker.done(),
            "queue_depth": self._queue.qsize() if self._queue is not None else 0,
            "sent": self.sent,
            "dropped": self.dropped,
            "reconnects": self.reconnects,
        }

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            try:
                await self._send_with_reconnect(event)
            finally:
                self._queue.task_done()

    async def _send_with_reconnect(self, event: PerceptionEvent) -> None:
        from engine.perception import to_wire_event

        frame = encode(to_wire_event(event))
        while not self._closing:
            try:
                if self._socket is None:
                    self._socket = await websockets.connect(self.control_url)
                    self.reconnects += 1
                await self._socket.send(frame)
                self.sent += 1
                return
            except (OSError, websockets.ConnectionClosed):
                await self._close_socket()
                await asyncio.sleep(max(0.01, self.reconnect_delay_s))
        self.dropped += 1

    async def _close_socket(self) -> None:
        if self._socket is not None:
            with contextlib.suppress(Exception):
                await self._socket.close()
            self._socket = None


__all__ = ["RuntimePerceptionSink"]

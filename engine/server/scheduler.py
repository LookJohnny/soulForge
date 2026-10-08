"""Decision scheduling for the runtime server: per-agent lanes, user priority, preemption.

One serial worker used to run every event: a user's utterance waited behind any
character's ambient musing (10-20 s on a local model), and the decision thread
mutated runtime state while the tick loop used it. Now:

- each agent has a lane; a lane serves its "user" queue before its ambient one
  (classes from ``runtime.event_class``), so per-agent order holds within a class;
- lanes of different agents run concurrently behind a ``PriorityGate``: at most
  ``max_concurrent`` model calls, and ambient work can never take the last slot,
  so a user turn always finds one;
- a user event preempts its agent's in-flight *droppable* ambient decision: the
  user turn starts at once and the ambient result is discarded when it arrives
  (threads cannot be killed; the provider call finishes in the background);
- only ``runtime.think`` leaves the event-loop thread. ``prepare_event`` and
  ``commit`` run on the loop, the same thread as ``tick``, so runtime state has a
  single writer.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from soulforge_harness.runtime.runtime import event_class


class PriorityGate:
    """Counting gate: high-priority callers take any free slot and go first;
    low-priority callers never take the last slot."""

    def __init__(self, slots: int):
        if slots < 1:
            raise ValueError("slots must be >= 1")
        self.slots = slots
        self.used = 0
        self._high_waiting = 0
        self._cond = asyncio.Condition()

    def _low_limit(self) -> int:
        return max(1, self.slots - 1)

    @contextlib.asynccontextmanager
    async def slot(self, high: bool):
        async with self._cond:
            if high:
                self._high_waiting += 1
                try:
                    await self._cond.wait_for(lambda: self.used < self.slots)
                finally:
                    self._high_waiting -= 1
            else:
                await self._cond.wait_for(
                    lambda: self.used < self._low_limit() and self._high_waiting == 0
                )
            self.used += 1
        try:
            yield
        finally:
            async with self._cond:
                self.used -= 1
                self._cond.notify_all()


@dataclass
class Lane:
    key: str
    user: deque = field(default_factory=deque)
    ambient: deque = field(default_factory=deque)
    epoch: int = 0  # bumped by every user event: stale droppable results are discarded
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    background: set = field(default_factory=set)

    def __len__(self) -> int:
        return len(self.user) + len(self.ambient)


class DecisionScheduler:
    """Owns the lanes. ``on_done(event, error)`` runs after each event (flush,
    broadcast, decision_complete); ``log(agent, kind, detail)`` writes the trace."""

    def __init__(
        self,
        runtime,
        *,
        minute: Callable[[], float],
        on_done: Callable[[Any, str], Awaitable[None]],
        log: Callable[[str, str, dict], None],
        max_concurrent: int = 2,
        max_queued: int = 256,
        on_speech: Callable[[], Awaitable[None]] | None = None,
    ):
        self.runtime = runtime
        self.minute = minute
        self.on_done = on_done
        self.log = log
        self.on_speech = on_speech  # deliver lines spoken before a decision completes
        self.gate = PriorityGate(max_concurrent)
        self.max_queued = max_queued
        self.lanes: dict[str, Lane] = {}
        # a slot-holder whose provider hangs keeps its thread; a little headroom
        # keeps new turns from queueing behind abandoned threads
        self.pool = ThreadPoolExecutor(max_workers=max_concurrent + 2, thread_name_prefix="think")
        self._stopped = False

    # ------------------------------------------------------------------ intake
    def queued(self) -> int:
        return sum(len(lane) for lane in self.lanes.values())

    def submit(self, event) -> bool:
        """Queue an event on its agent's lane. False when shed for backpressure."""
        key = event.target_agent or "*"  # untargeted events keep one fan-out turn
        if self.queued() >= self.max_queued:
            self.log(key, "event_dropped", {"reason": "event queue full (backpressure)"})
            return False
        lane = self.lanes.get(key)
        if lane is None:
            lane = self.lanes[key] = Lane(key)
        if event_class(event) == "user":
            lane.user.append(event)
            lane.epoch += 1
        else:
            lane.ambient.append(event)
        lane.wake.set()
        if lane.task is None or lane.task.done():
            lane.task = asyncio.get_running_loop().create_task(self._run_lane(lane))
        return True

    # ------------------------------------------------------------------- lanes
    async def _run_lane(self, lane: Lane) -> None:
        while not self._stopped and len(lane):
            if lane.user:
                await self._process(lane.user.popleft(), lane, None)
                continue
            event = lane.ambient.popleft()
            droppable = event_class(event) == "droppable"
            task = asyncio.create_task(self._process(event, lane, lane.epoch if droppable else None))
            # Wait for the ambient turn, unless a user event arrives first:
            # then serve the user now and let the ambient turn finish (or be
            # discarded) in the background. Non-droppable ambient work (a
            # conversation turn, deferred motion) still commits when it lands.
            while not task.done():
                if lane.user:
                    lane.background.add(task)
                    task.add_done_callback(lane.background.discard)
                    break
                lane.wake.clear()
                waiter = asyncio.create_task(lane.wake.wait())
                await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
                waiter.cancel()
            else:
                await task

    async def _process(self, event, lane: Lane, epoch: int | None) -> None:
        error = ""
        try:
            for turn in self.runtime.prepare_event(event, self.minute()):
                if turn.deferred_decision is not None:
                    decision = turn.deferred_decision  # cached: no model call
                else:
                    async with self.gate.slot(high=event_class(event) == "user"):
                        if self._stale(lane, epoch, turn.agent_id):
                            continue
                        loop = asyncio.get_running_loop()
                        on_line = self._line_relay(loop, turn) if turn.stream else None
                        decision = await loop.run_in_executor(
                            self.pool, self.runtime.think, turn, on_line
                        )
                if self._stale(lane, epoch, turn.agent_id):
                    continue
                self.runtime.commit(turn, decision, self.minute())
        except Exception as exc:  # a decision failure must not kill the lane
            error = type(exc).__name__
            self.log(event.target_agent or "*", "event_error", {"error": error})
        await self.on_done(event, error)

    def _line_relay(self, loop, turn):
        """Called on the think thread for each streamed line: speak it now on the
        loop thread (the only thread that mutates the runtime) and deliver it."""

        def speak(line):
            self.runtime.speak_early(turn, line, self.minute())
            if self.on_speech is not None:
                loop.create_task(self.on_speech())

        return lambda line: loop.call_soon_threadsafe(speak, line)

    def _stale(self, lane: Lane, epoch: int | None, agent_id: str) -> bool:
        if epoch is None or lane.epoch == epoch:
            return False
        self.log(agent_id, "event_dropped", {"reason": "preempted by a user turn"})
        return True

    # ---------------------------------------------------------------- shutdown
    async def stop(self) -> None:
        self._stopped = True
        tasks = [t for lane in self.lanes.values() for t in (lane.task, *lane.background) if t]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self.pool.shutdown(wait=False, cancel_futures=True)

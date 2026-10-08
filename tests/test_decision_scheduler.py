"""Per-agent lanes: a user's turn is never blocked behind (or dropped for) ambient work."""

import asyncio
import threading
import time

import pytest

from engine.planner import CompanionRuntime, MockBehaviorLLM, Persona, WorldState
from engine.server.scheduler import DecisionScheduler, PriorityGate
from soulforge_harness.runtime.models import Event, EventKind


def personas():
    return [
        Persona(
            "luna", "Luna", "creative_care", relationships={"user": 0.8, "kai": 0.7}
        ),
        Persona(
            "kai", "Kai", "steady_caretaker", relationships={"user": 0.75, "luna": 0.7}
        ),
    ]


class SleepyLLM(MockBehaviorLLM):
    """Ambient decisions take `slow` seconds, user turns `fast`; records start/finish order."""

    def __init__(self, slow=0.6, fast=0.05):
        super().__init__()
        self.slow, self.fast = slow, fast
        self.log, self.active, self.peak = [], 0, 0
        self._lock = threading.Lock()

    def decide(self, event, *args, **kwargs):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.log.append(("start", event.kind.value, event.target_agent))
        time.sleep(self.fast if event.kind == EventKind.USER_UTTERANCE else self.slow)
        with self._lock:
            self.active -= 1
            self.log.append(("end", event.kind.value, event.target_agent))
        return super().decide(event, *args, **kwargs)


def arrival(to):
    return Event(
        t_min=900,
        kind=EventKind.AGENT_STATE,
        source="luna",
        text="Luna来了客厅",
        target_agent=to,
    )


def utterance(to, text="你好"):
    return Event(
        t_min=900,
        kind=EventKind.USER_UTTERANCE,
        source="user",
        text=text,
        target_agent=to,
    )


async def make(llm, **kw):
    rt = CompanionRuntime(personas(), WorldState(sim_minute=900), llm=llm)
    rt.tick(900)
    done = []

    async def on_done(event, error):
        done.append((event.kind.value, event.target_agent, error, time.monotonic()))

    sched = DecisionScheduler(
        rt,
        minute=lambda: 900.0,
        on_done=on_done,
        log=lambda a, k, d: rt.log(900, a, k, d),
        **kw,
    )
    return rt, sched, done


async def settle(sched, done, n, timeout=5.0):
    deadline = time.monotonic() + timeout
    while len(done) < n and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert len(done) >= n, f"only {len(done)} of {n} events finished"


@pytest.mark.asyncio
async def test_user_turn_is_not_blocked_by_an_in_flight_ambient_decision():
    llm = SleepyLLM(slow=0.8)
    rt, sched, done = await make(llm)
    t0 = time.monotonic()
    sched.submit(arrival("kai"))
    await asyncio.sleep(0.1)  # the ambient decision is now running
    sched.submit(utterance("kai"))
    await settle(sched, done, 2)
    user_done = next(d for d in done if d[0] == "user_utterance")
    assert user_done[3] - t0 < 0.5, "the user turn waited for the ambient decision"
    # the arrival notice was preempted: its result never reached the plan
    assert any(
        t.kind == "event_dropped"
        and t.detail.get("reason") == "preempted by a user turn"
        for t in rt.trace
    )
    assert [t.agent_id for t in rt.trace if t.kind == "decision"] == ["kai"]
    await sched.stop()


@pytest.mark.asyncio
async def test_conversation_turns_are_never_preempted():
    llm = SleepyLLM(slow=0.4)
    rt, sched, done = await make(llm)
    rt.start_conversation("kai", "luna", 900)
    opener = rt.event_queue.pop()  # AGENT_STATE with a conversation payload
    sched.submit(opener)
    await asyncio.sleep(0.05)
    sched.submit(utterance("kai"))
    await settle(sched, done, 2)
    assert not any(t.kind == "event_dropped" for t in rt.trace)
    assert sum(t.kind == "decision" and t.agent_id == "kai" for t in rt.trace) == 2
    await sched.stop()


@pytest.mark.asyncio
async def test_agents_decide_concurrently_but_ambient_never_takes_the_last_slot():
    llm = SleepyLLM(slow=0.4)
    rt, sched, done = await make(llm, max_concurrent=2)
    t0 = time.monotonic()
    sched.submit(arrival("kai"))
    sched.submit(arrival("luna"))  # second ambient must wait: one slot is reserved
    await asyncio.sleep(0.05)
    sched.submit(
        utterance("luna")
    )  # preempts luna's queued arrival, takes the reserved slot
    await settle(sched, done, 3)
    assert llm.peak == 2
    user_done = next(d for d in done if d[0] == "user_utterance")
    assert user_done[3] - t0 < 0.35
    await sched.stop()


@pytest.mark.asyncio
async def test_per_agent_user_turns_keep_their_order_and_state_is_written_on_the_loop_thread():
    llm = SleepyLLM()
    rt, sched, done = await make(llm)
    writers = set()
    original = rt.log

    def tracking_log(*a, **k):
        writers.add(threading.current_thread().name)
        return original(*a, **k)

    rt.log = rt._log = tracking_log
    for text in ("一", "二", "三"):
        sched.submit(utterance("kai", text))
    await settle(sched, done, 3)
    heard = [t.detail["text"] for t in rt.trace if t.kind == "event"]
    assert heard == ["一", "二", "三"]
    assert writers == {threading.current_thread().name}  # never a think-pool thread
    await sched.stop()


@pytest.mark.asyncio
async def test_backpressure_sheds_and_logs_instead_of_raising():
    rt, sched, done = await make(SleepyLLM(slow=0.3), max_queued=2)
    accepted = [sched.submit(arrival("kai")) for _ in range(4)]
    assert accepted.count(False) >= 1
    assert any(
        t.detail.get("reason") == "event queue full (backpressure)" for t in rt.trace
    )
    await sched.stop()


@pytest.mark.asyncio
async def test_priority_gate():
    gate = PriorityGate(2)
    order = []

    async def use(name, high, hold):
        async with gate.slot(high):
            order.append(name)
            await asyncio.sleep(hold)

    low1 = asyncio.create_task(use("low1", False, 0.2))
    await asyncio.sleep(0.01)
    low2 = asyncio.create_task(
        use("low2", False, 0.01)
    )  # blocked: the last slot is reserved
    high = asyncio.create_task(
        use("high", True, 0.01)
    )  # takes the reserved slot at once
    await asyncio.sleep(0.05)
    assert order == ["low1", "high"]
    await asyncio.gather(low1, low2, high)
    assert order == ["low1", "high", "low2"]
    with pytest.raises(ValueError):
        PriorityGate(0)

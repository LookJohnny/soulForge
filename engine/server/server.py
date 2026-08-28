"""SoulForge Runtime Server — one brain, many bodies, JSON over WebSocket.

Paths on a single port:
  /body     embodiments: send `hello` (+manifest), then receive `action`,
            `plan_state`, `tick`; send back `event` and `observation`
  /control  UIs / test harnesses: send `event`, receive `plan_state` broadcasts;
            send {"type":"query","what":"state"|"trace"} for snapshots

Execution feedback loop: every dispatched ActionCommand is tracked; an
Observation with status "failed" triggers the owning template's declared
recovery clip and is logged in the decision trace.

Run standalone:
  uv run python -m engine.server.server --port 8765 --start-clock 20:47 --time-scale 6
(time-scale = simulated minutes per real second)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import websockets

from engine.planner import CompanionRuntime, Persona, WorldState
from engine.planner.conversation import SocialPolicy
from engine.planner.llm_interface import MockBehaviorLLM
from engine.planner.models import Event as PlannerEvent, EventKind, MicroAction
from engine.planner.templates import TEMPLATE_REGISTRY
from engine.server.capability import EmbodimentManifest
from engine.server.protocol import (
    PROTOCOL_VERSION,
    ActionCommand,
    BodyHello,
    Event as WireEvent,
    Observation,
    PlanState,
    Tick,
    Welcome,
    decode,
    encode,
)


@dataclass
class BodyConnection:
    socket: Any
    manifest: EmbodimentManifest
    agent_ids: list[str]
    sent_commands: dict[str, ActionCommand] = field(default_factory=dict)
    next_sequence: int = 1


def _require_finite_positive(name: str, value: float) -> float:
    import math

    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number, got {value!r}")
    return float(value)


class SoulForgeRuntimeServer:
    def __init__(
        self,
        personas: list[Persona],
        *,
        start_minute: float = 20 * 60 + 47,
        time_scale: float = 6.0,
        tick_hz: float = 1.0,
        llm=None,
        llm_timeout_s: float = 6.0,
        social: bool = False,
    ):
        """time_scale: simulated minutes advanced per real second.
        social: characters strike up small talk with each other on their own."""
        import math

        self.time_scale = _require_finite_positive("time_scale", time_scale)
        self.tick_hz = _require_finite_positive("tick_hz", tick_hz)
        if not math.isfinite(start_minute) or start_minute < 0:
            raise ValueError(
                f"start_minute must be finite and >= 0, got {start_minute!r}"
            )
        # LLM isolation: whatever decision-maker we got runs behind a thread
        # pool with a hard timeout and a deterministic fallback
        from engine.planner.llm_interface import SafeDecisionLLM, build_llm

        self.llm = SafeDecisionLLM(llm or build_llm(), timeout_s=llm_timeout_s)
        self.runtime = CompanionRuntime(
            personas,
            WorldState(sim_minute=start_minute),
            llm=self.llm,
            adapter=self._on_planner_dispatch,
            social_policy=SocialPolicy(auto_start=social, turn_gap_min=30.0),
        )
        self.sim_minute = start_minute
        self.bodies: dict[str, BodyConnection] = {}
        self.controls: set[Any] = set()
        self._pending_micro: list[tuple[str, MicroAction]] = []
        self._trace_cursor = 0
        self._last_plan_frame: dict[str, str] = {}
        self._stop = asyncio.Event()
        self.ready = asyncio.Event()
        self.bound_port: int | None = None
        # events are handled on a worker so a slow LLM can never stall the tick
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=256)

    # ------------------------------------------------------------------ core
    def _on_planner_dispatch(self, agent_id: str, action: MicroAction) -> None:
        """CompanionRuntime adapter hook: queue micro-actions for broadcast."""
        self._pending_micro.append((agent_id, action))

    def _drain_runtime_events(self) -> None:
        """Events the runtime queued for itself (conversation turns, deferred
        events) become due on the sim clock; hand them to the event worker."""
        due = [e for e in list(self.runtime.event_queue) if e.t_min <= self.sim_minute]
        for event in due:
            with contextlib.suppress(ValueError):
                self.runtime.event_queue.remove(event)
            self._event_queue.put_nowait(event)

    async def _tick_loop(self) -> None:
        """Drift-corrected: next tick is scheduled on the absolute clock, so a
        slow tick doesn't permanently slow the simulated day."""
        interval = 1.0 / self.tick_hz
        loop = asyncio.get_event_loop()
        next_at = loop.time()
        while not self._stop.is_set():
            try:
                # consume_events=False: the event worker owns LLM-bound work
                self.runtime.tick(self.sim_minute, consume_events=False)
                self._drain_runtime_events()
                await self._flush_pending()
                await self._broadcast_new_trace()
                await self._broadcast(
                    encode(
                        Tick(
                            sim_minute=self.sim_minute, clock=self.runtime.world.clock()
                        )
                    )
                )
            except Exception as exc:  # one bad tick must not kill the brain
                self.runtime.log(
                    self.sim_minute, "*", "tick_error", {"error": str(exc)[:200]}
                )
            self.sim_minute += self.time_scale * interval
            next_at += interval
            delay = max(0.0, next_at - loop.time())
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay or 0.001)

    async def _flush_pending(self) -> None:
        pending, self._pending_micro = self._pending_micro, []
        for agent_id, action in pending:
            command = ActionCommand(
                agent_id=agent_id,
                name=action.name,
                template_id=action.template_id,
                params=action.params,
                adapter_command=action.adapter_command,
                dialogue=action.dialogue,
                gaze_target=action.gaze_target,
                duration_s=action.duration_s,
                sim_minute=self.sim_minute,
                correlation_id=action.correlation_id,
            )
            await self._send_to_embodying_bodies(command)

    async def _send_to_embodying_bodies(self, command: ActionCommand) -> None:
        for body in list(self.bodies.values()):
            if command.agent_id not in body.agent_ids:
                continue
            manifest = body.manifest
            if not manifest.accepts_template(command.template_id):
                continue
            if not manifest.accepts_step(command.name):
                continue  # capability negotiation: body never sees what it can't do
            outgoing = ActionCommand(**{**command.__dict__})
            outgoing.name = manifest.resolve_step(command.name)
            if not manifest.wants_dialogue():
                outgoing.dialogue = None
            # canonical IR envelope
            outgoing.sequence = body.next_sequence
            body.next_sequence += 1
            outgoing.target_body = manifest.body_id
            outgoing.issued_at = self.sim_minute
            outgoing.deadline = self.sim_minute + max(
                1.0, command.duration_s / 60.0 * self.time_scale + 2.0
            )
            template = (
                TEMPLATE_REGISTRY.get(command.template_id)
                if command.template_id
                else None
            )
            outgoing.interruptible = template.interruptible if template else True
            outgoing.safety_class = (
                "physical" if manifest.is_fail_closed() else "expressive"
            )
            body.sent_commands[outgoing.command_id] = outgoing
            while len(body.sent_commands) > 256:  # bounded: bodies may never ack
                body.sent_commands.pop(next(iter(body.sent_commands)))
            await self._safe_send(body.socket, encode(outgoing))

    async def _broadcast_new_trace(self) -> None:
        """Push plan_state to everyone whenever a decision / plan change lands."""
        fresh = self.runtime.trace_since(self._trace_cursor)
        if fresh:
            self._trace_cursor = fresh[-1].seq
        if not any(t.kind in ("decision", "plan_change") for t in fresh):
            return
        for agent_id in self.runtime.personas:
            state = self._plan_state(agent_id)
            frame = encode(state)
            if self._last_plan_frame.get(agent_id) == frame:
                continue  # dedupe: identical snapshots are noise for HUDs
            self._last_plan_frame[agent_id] = frame
            await self._broadcast_plan(agent_id, frame)

    async def _broadcast_plan(self, agent_id: str, frame: str) -> None:
        """plan_state is agent-scoped: bodies only receive state for agents
        they declared; control connections (trusted UIs) receive everything."""
        for body in list(self.bodies.values()):
            if agent_id in body.agent_ids:
                await self._safe_send(body.socket, frame)
        for socket in list(self.controls):
            await self._safe_send(socket, frame)

    def _plan_state(self, agent_id: str) -> PlanState:
        hour = self.runtime.hour_plans.get(agent_id)
        day = self.runtime.day_plans[agent_id]
        # last_decision is per agent — Luna's decision must never surface as Kai's
        last = next(
            (
                t.detail
                for t in reversed(self.runtime.trace)
                if t.kind == "decision" and t.agent_id == agent_id
            ),
            {},
        )
        return PlanState(
            agent_id=agent_id,
            clock=self.runtime.world.clock(),
            hour_goal=hour.goal if hour else "",
            activities=[
                {
                    "template_id": a.template_id,
                    "start_min": a.start_min,
                    "duration_min": a.duration_min,
                    "params": a.params,
                    "interruptible": a.interruptible,
                }
                for a in (hour.activities if hour else [])
            ],
            day_blocks=[
                {
                    "start_min": b.start_min,
                    "end_min": b.end_min,
                    "activity_key": b.activity_key,
                    "intent": b.intent,
                }
                for b in day.blocks
            ],
            last_decision=last,
        )

    # ---------------------------------------------------------- feedback loop
    async def _handle_observation(self, body: BodyConnection, obs: Observation) -> None:
        command = body.sent_commands.get(obs.command_id)
        if command is None:
            self.runtime.log(
                self.sim_minute,
                obs.agent_id,
                "observation_rejected",
                {"reason": "unknown command_id", "command_id": obs.command_id},
            )
            return
        # the command's agent is authoritative: a body cannot forge a cross-agent
        # receipt and steer another character's recovery
        if obs.agent_id != command.agent_id:
            self.runtime.log(
                self.sim_minute,
                command.agent_id,
                "observation_rejected",
                {
                    "reason": "agent_id mismatch",
                    "claimed": obs.agent_id,
                    "actual": command.agent_id,
                    "body": body.manifest.body_id,
                },
            )
            return
        agent_id = command.agent_id
        self.runtime.log(
            self.sim_minute,
            agent_id,
            "observation",
            {
                "status": obs.status,
                "step": command.name,
                "detail": obs.detail,
            },
        )
        # accepted/running are progress receipts, not completion.  Keep the
        # command pending until a terminal status arrives so a voice body can
        # first accept a line and later confirm that playback really finished.
        # The agent check above deliberately happens before this pop: a forged
        # cross-agent receipt must never consume the legitimate command.
        if obs.status in {"done", "failed", "interrupted", "rejected"}:
            body.sent_commands.pop(obs.command_id, None)
            if (
                command.dialogue
            ):  # the line has been spoken (or won't be): partner may answer
                self.runtime.conversations.release(agent_id, self.sim_minute)
        if obs.status == "failed" and command and command.template_id:
            template = TEMPLATE_REGISTRY.get(command.template_id)
            if template:
                recovery = MicroAction(
                    name=template.recovery,
                    template_id=command.template_id,
                    params={"recovering_from": command.name},
                    duration_s=2.0,
                )
                self.runtime.log(
                    self.sim_minute,
                    agent_id,
                    "plan_change",
                    {
                        "level": "recovery",
                        "template": command.template_id,
                        "failed_step": command.name,
                        "recovery_clip": template.recovery,
                    },
                )
                self._pending_micro.append((agent_id, recovery))
                await self._flush_pending()

    def _ingest_event(self, wire: WireEvent) -> None:
        try:
            kind = EventKind(wire.kind)
        except ValueError:
            self.runtime.log(
                self.sim_minute,
                wire.target_agent or "*",
                "event_dropped",
                {"reason": f"unknown event kind {wire.kind!r}"},
            )
            return
        event = PlannerEvent(
            t_min=self.sim_minute,
            kind=kind,
            source=wire.source,
            text=wire.text,
            payload=wire.payload if isinstance(wire.payload, dict) else {},
            target_agent=wire.target_agent,
        )
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            self.runtime.log(
                self.sim_minute,
                wire.target_agent or "*",
                "event_dropped",
                {"reason": "event queue full (backpressure)"},
            )

    async def _event_worker(self) -> None:
        """Runs LLM-bound event handling off the tick path with no blocking."""
        loop = asyncio.get_event_loop()
        while not self._stop.is_set():
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.25)
            except asyncio.TimeoutError:
                continue
            try:
                await loop.run_in_executor(
                    None, self.runtime.handle_event_now, event, self.sim_minute
                )
                await self._flush_pending()
                await self._broadcast_new_trace()
            except Exception as exc:  # decision failure must not kill the worker
                self.runtime.log(
                    self.sim_minute,
                    event.target_agent or "*",
                    "event_error",
                    {"error": str(exc)[:200]},
                )

    # ------------------------------------------------------------ connections
    async def _handle_connection(self, socket) -> None:
        path = socket.request.path if socket.request else "/body"
        if path.startswith("/control"):
            await self._serve_control(socket)
        else:
            await self._serve_body(socket)

    async def _serve_body(self, socket) -> None:
        try:
            hello = decode(await socket.recv())
        except Exception:
            await socket.close(code=4000, reason="expected hello frame")
            return
        if not isinstance(hello, BodyHello):
            await socket.close(code=4001, reason="first frame must be hello")
            return
        manifest = EmbodimentManifest.from_dict(
            {**hello.manifest, "body_id": hello.body_id, "backend": hello.backend}
        )
        accepted = [a for a in hello.agent_ids if a in self.runtime.personas]
        body = BodyConnection(socket=socket, manifest=manifest, agent_ids=accepted)
        # reconnect with the same body_id replaces the stale connection: close the
        # old socket, and make sure its teardown can never evict the new one
        previous = self.bodies.get(hello.body_id)
        if previous is not None and previous.socket is not socket:
            with contextlib.suppress(Exception):
                await previous.socket.close(code=4002, reason="replaced by reconnect")
        self.bodies[hello.body_id] = body
        await self._safe_send(
            socket,
            encode(
                Welcome(
                    body_id=hello.body_id,
                    accepted_agents=accepted,
                    supported_steps=manifest.negotiated_steps(),
                )
            ),
        )
        for agent_id in accepted:
            await self._safe_send(socket, encode(self._plan_state(agent_id)))
        try:
            async for raw in socket:
                try:
                    message = decode(raw)
                except (ValueError, TypeError) as exc:
                    self.runtime.log(
                        self.sim_minute,
                        hello.body_id,
                        "wire_error",
                        {"reason": str(exc)[:120]},
                    )
                    continue  # a malformed frame must never kill the connection
                if isinstance(message, Observation):
                    await self._handle_observation(body, message)
                elif isinstance(message, WireEvent):
                    self._ingest_event(message)
        except websockets.ConnectionClosed:
            pass
        finally:
            # identity check: only remove the registry entry if it is still OURS —
            # a reconnected body must not be evicted by the old connection's teardown
            if self.bodies.get(hello.body_id) is body:
                self.bodies.pop(hello.body_id, None)

    async def _serve_control(self, socket) -> None:
        self.controls.add(socket)
        try:
            async for raw in socket:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "event":
                    self._ingest_event(decode(raw))
                elif data.get("type") == "start_conversation":
                    agents = data.get("agents") or []
                    try:
                        conv = self.runtime.start_conversation(
                            agents[0],
                            agents[1],
                            self.sim_minute,
                            data.get("topic", ""),
                            data.get("max_turns"),
                        )
                        await self._safe_send(
                            socket,
                            json.dumps(
                                {
                                    "type": "conversation",
                                    "id": conv.id,
                                    "agents": list(conv.participants),
                                    "topic": conv.topic,
                                }
                            ),
                        )
                    except (IndexError, ValueError) as exc:
                        await self._safe_send(
                            socket, json.dumps({"type": "error", "error": str(exc)})
                        )
                elif data.get("type") == "query":
                    if data.get("what") == "trace":
                        await self._safe_send(socket, self.runtime.dump_trace_json())
                    else:
                        for agent_id in self.runtime.personas:
                            await self._safe_send(
                                socket, encode(self._plan_state(agent_id))
                            )
        except websockets.ConnectionClosed:
            pass
        finally:
            self.controls.discard(socket)

    async def _broadcast(self, frame: str) -> None:
        for body in list(self.bodies.values()):
            await self._safe_send(body.socket, frame)
        for socket in list(self.controls):
            await self._safe_send(socket, frame)

    @staticmethod
    async def _safe_send(socket, frame: str) -> None:
        with contextlib.suppress(Exception):
            await socket.send(frame)

    # ---------------------------------------------------------------- runners
    async def serve(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Pass port=0 to bind an ephemeral port; read it from `bound_port`."""
        async with websockets.serve(
            self._handle_connection, host, port, ping_interval=20, ping_timeout=90
        ) as ws_server:
            self.bound_port = ws_server.sockets[0].getsockname()[1]
            self.ready.set()
            ticker = asyncio.create_task(self._tick_loop())
            event_worker = asyncio.create_task(self._event_worker())
            print(
                f"SoulForge runtime server @ ws://{host}:{self.bound_port}  "
                f"(protocol {PROTOCOL_VERSION}, clock {self.runtime.world.clock()}, "
                f"x{self.time_scale} sim-min/s)"
            )
            try:
                await self._stop.wait()
            finally:
                ticker.cancel()
                event_worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticker
                with contextlib.suppress(asyncio.CancelledError):
                    await event_worker

    def stop(self) -> None:
        self._stop.set()


def default_personas() -> list[Persona]:
    """Characters come from configs/characters.json — swap the roster there."""
    from engine.planner.characters import load_personas

    return load_personas()


def main() -> None:
    parser = argparse.ArgumentParser(description="SoulForge runtime server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--start-clock", default="20:47")
    parser.add_argument(
        "--time-scale",
        type=float,
        default=6.0,
        help="simulated minutes per real second",
    )
    parser.add_argument("--tick-hz", type=float, default=1.0)
    parser.add_argument("--llm-timeout", type=float, default=6.0)
    parser.add_argument(
        "--mock-llm", action="store_true", help="offline: deterministic MockBehaviorLLM"
    )
    parser.add_argument(
        "--social",
        action="store_true",
        help="let characters start small talk with each other on their own",
    )
    args = parser.parse_args()
    hours, minutes = args.start_clock.split(":")
    start_minute = int(hours) * 60 + int(minutes)
    server = SoulForgeRuntimeServer(
        default_personas(),
        start_minute=start_minute,
        time_scale=args.time_scale,
        tick_hz=args.tick_hz,
        social=args.social,
        llm_timeout_s=args.llm_timeout,
        llm=MockBehaviorLLM() if args.mock_llm else None,
    )
    asyncio.run(server.serve(args.host, args.port))


if __name__ == "__main__":
    main()

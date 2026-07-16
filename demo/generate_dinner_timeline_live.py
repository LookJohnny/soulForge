"""Generate the dinner-demo timeline with LIVE LLM decisions AND dialogue.

Unlike generate_dinner_timeline.py (hand-written lines), every spoken line here
is produced by the real LLM at generation time:

  pass 1  CompanionRuntime + SafeDecisionLLM(build_llm())
          -> real interruption decisions (impact/scope/reason) + decision dialogue
  pass 2  scene-writer call (same LLM provider)
          -> the connecting household lines + zh/en for every beat, conditioned
             on the ACTUAL decisions from pass 1

The beat *structure* (who is on camera, which shot) is a deterministic
trace->beats converter; the words are not authored by a human.

Run:  uv run python demo/generate_dinner_timeline_live.py
Out:  demo/vtuber_life_web/dinner_timeline.json (+ dinner_voice_events.json)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.planner import (
    CompanionRuntime, Event, EventKind, WorldState,
)
from engine.planner.characters import load_personas
from engine.planner.llm_interface import SafeDecisionLLM, build_llm

OUT = ROOT / "demo" / "vtuber_life_web" / "dinner_timeline.json"
START_MIN = 20 * 60 + 47  # 20:47

# emotions the renderer + voice pipeline understand
KNOWN_EMOTIONS = {"warm", "soft", "calm", "robot", "moved"}


def load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


class RecordingLLM:
    """Delegates to the real decision LLM and keeps the full BehaviorDecision
    (the runtime trace drops the dialogue field)."""

    def __init__(self, inner):
        self.inner = inner
        self.decisions: dict[str, object] = {}

    def decide(self, event, persona, world, current_template, current_interruptible):
        decision = self.inner.decide(event, persona, world,
                                     current_template, current_interruptible)
        self.decisions[persona.agent_id] = decision
        return decision


def chat(prompt: str, *, temperature: float = 0.6, force_json: bool = True) -> str:
    # this machine's network path resets Python-OpenSSL TLS handshakes to
    # api.openai.com (same as fish.audio) — curl passes, so curl is the transport.
    # provider preference mirrors build_llm(): DeepSeek first, then OpenAI.
    if os.environ.get("DEEPSEEK_API_KEY"):
        api_key = os.environ["DEEPSEEK_API_KEY"]
        default_base, default_model = "https://api.deepseek.com/v1", "deepseek-chat"
    else:
        api_key = os.environ["OPENAI_API_KEY"]
        default_base, default_model = "https://api.openai.com/v1", "gpt-4o-mini"
    base_url = os.environ.get("BEHAVIOR_LLM_BASE_URL", default_base)
    model = os.environ.get("BEHAVIOR_LLM_MODEL", default_model)
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if force_json:
        body["response_format"] = {"type": "json_object"}
    result = subprocess.run(
        ["curl", "-sS", "--max-time", "90", "--retry", "3", "--retry-all-errors",
         f"{base_url.rstrip('/')}/chat/completions",
         "-H", "Content-Type: application/json",
         "-H", f"Authorization: Bearer {api_key}",
         "-d", json.dumps(body)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    if "error" in data:
        raise RuntimeError(f"llm error: {data['error']}")
    return data["choices"][0]["message"]["content"]


def decision_brief(decision) -> dict:
    if decision is None:
        return {}
    return {
        "selected_intent": decision.selected_intent,
        "impact": decision.impact.name,
        "plan_delta": decision.plan_delta,
        "template_to_call": decision.template_to_call,
        "interrupt_policy": decision.interrupt_policy,
        "reason": decision.reason,
        "decision_dialogue": decision.dialogue,
    }


def write_scene(personas, luna_decision, pipo_decision, hour_goal: str) -> list[dict]:
    """Pass 2: the scene writer produces zh+en for all seven spoken beats,
    conditioned on the engine's real decisions."""
    persona_notes = "; ".join(
        f"{p.agent_id}={p.name}({p.archetype}, traits {p.traits})" for p in personas
    )
    prompt = (
        "You write natural spoken dialogue for a 30s product demo of a companion-AI "
        "household. Scene: 20:47, apartment. Kai (male caretaker) is cooking, Luna "
        "(female artist VTuber) has been drawing all afternoon, Pipo (small robot) "
        "patrols plants.\n"
        f"Personas: {persona_notes}\n\n"
        "Two real events were processed by the planning engine and these are its "
        "ACTUAL decisions (do not contradict them):\n"
        f"EVENT A: user says '我今天有点累……' -> Luna's decision: "
        f"{json.dumps(luna_decision, ensure_ascii=False)}\n"
        f"Luna's hour plan after replanning: {hour_goal!r}\n"
        f"EVENT B: plant sensor reports right pot humidity 22% -> Pipo's decision: "
        f"{json.dumps(pipo_decision, ensure_ascii=False)}\n\n"
        "Write exactly these 7 lines, in order:\n"
        "1 opening_kai: Kai, while cooking, warmly asks Luna about dinner.\n"
        "2 reply_luna: Luna answers what she'd like.\n"
        "3 event_luna: Luna responds to the tired user, faithfully expressing her "
        "decision above (what she pauses, how tonight changes). If "
        "decision_dialogue has text, keep its meaning.\n"
        "4 followup_kai: Kai acknowledges the plan change while finishing the food.\n"
        "5 event_pipo: Pipo reports the plant reading and what its decision above "
        "actually did (insert/reschedule — be faithful to plan_delta).\n"
        "6 ack_kai: Kai briefly accepts Pipo's arrangement.\n"
        "7 thanks_luna: Luna, moved, thanks them; one short warm closing line.\n\n"
        "Rules: natural companion speech, never device-log tone. zh is spoken "
        "Mandarin, 10-30 characters. en is a faithful English subtitle. emotion is "
        "one of warm|soft|calm|robot|moved (pipo always robot).\n"
        'Respond ONLY with JSON: {"lines": [{"slot": str, "zh": str, "en": str, '
        '"emotion": str}, ...]} with exactly 7 items in the order above.'
    )
    data = json.loads(chat(prompt))
    lines = data["lines"]
    assert len(lines) == 7, f"scene writer returned {len(lines)} lines"
    for line in lines:
        assert line["zh"].strip(), f"empty zh for slot {line.get('slot')}"
        if line["emotion"] not in KNOWN_EMOTIONS:
            line["emotion"] = "warm"
    lines[4]["emotion"] = "robot"  # pipo voice styling is fixed
    return lines


def main() -> None:
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("no LLM key in env/.env — live generation needs one")

    personas = load_personas()
    world = WorldState(sim_minute=START_MIN, user_present=True,
                       sensors={"plant_humidity_right": 0.22})
    inner = build_llm()
    if not hasattr(inner, "_chat"):
        raise SystemExit("build_llm() returned the mock — key not picked up")

    # honesty guard: if any decision call fails, OpenAICompatibleBehaviorLLM
    # silently falls back to the mock — a "live" video must never ship that way
    failures: list[str] = []

    def decision_chat(prompt: str) -> str:
        try:
            return chat(prompt, temperature=0.4, force_json=False)
        except Exception as exc:
            failures.append(str(exc))
            raise

    inner._chat = decision_chat  # curl transport (Python TLS is blocked here)
    recorder = RecordingLLM(SafeDecisionLLM(inner, timeout_s=25.0))
    runtime = CompanionRuntime(personas, world, llm=recorder)

    runtime.push_event(Event(t_min=START_MIN + 1, kind=EventKind.USER_UTTERANCE,
                             source="user", text="我今天有点累……", target_agent="luna"))
    runtime.push_event(Event(t_min=START_MIN + 2, kind=EventKind.ENVIRONMENT,
                             source="plant_sensor", text="右侧盆栽湿度偏低 22%",
                             payload={"humidity": 0.22}, target_agent="pipo"))
    runtime.run(start_min=START_MIN, duration_min=4)
    recorder.inner.shutdown()
    if failures:
        raise SystemExit(
            "ABORT: decision LLM call(s) failed and fell back to the mock — "
            f"refusing to label this run as live. First error: {failures[0]}")

    trace_decisions = {t.agent_id: t.detail for t in runtime.trace if t.kind == "decision"}
    luna_brief = decision_brief(recorder.decisions.get("luna"))
    pipo_brief = decision_brief(recorder.decisions.get("pipo"))
    hour_goal = runtime.hour_plans["luna"].goal
    provider_model = os.environ.get(
        "BEHAVIOR_LLM_MODEL",
        "deepseek-chat" if os.environ.get("DEEPSEEK_API_KEY") else "gpt-4o-mini")

    print("live decisions:")
    for agent_id, detail in trace_decisions.items():
        print(f"  {agent_id}: [{detail['impact']}] {detail['scope']} :: {detail['reason']}")

    lines = write_scene(personas, luna_brief, pipo_brief, hour_goal)
    by_slot = {line["slot"]: line for line in lines}

    # ---- deterministic trace->beats converter -------------------------------
    # (speaker order / camera / action steps are a fixed directing grammar;
    #  every word and every decision card comes from the LLM passes above)
    luna_trace = trace_decisions.get("luna", {})
    pipo_trace = trace_decisions.get("pipo", {})
    plan = [
        ("opening_kai", "kai", ["luna"], "kitchen", "cooking", "stir_pan", None),
        ("reply_luna", "luna", ["kai"], "desk", "drawing", "lean_back_review", None),
        ("event_luna", "luna", ["user"], "luna_close", "chatting", "look_at_user",
         {"t_off": -1.2, "source": "user", "text": "我今天有点累……",
          "impact": luna_trace.get("impact", "HIGH"),
          "scope": luna_trace.get("scope", "hour"),
          "decision": f"{luna_brief.get('selected_intent', '')} → 重规划 "
                      f"{luna_trace.get('scope', 'hour')} → {hour_goal}"}),
        ("followup_kai", "kai", ["user", "luna"], "kitchen_close", "cooking", "plate_up", None),
        ("event_pipo", "pipo", ["kai", "luna"], "plant", "plant_care", "scan_leaves",
         {"t_off": -0.6, "source": "plant_sensor", "text": "右侧盆栽湿度 22%",
          "impact": pipo_trace.get("impact", "LOW"),
          "scope": pipo_trace.get("scope", "micro"),
          "decision": f"{pipo_brief.get('selected_intent', '')} → "
                      f"{pipo_brief.get('plan_delta', 'insert')} → 不打断当前活动"}),
        ("ack_kai", "kai", ["pipo"], "two_shot", "cooking", "announce_ready", None),
        ("thanks_luna", "luna", ["kai", "pipo"], "group", "chatting", "perform:Clapping", None),
    ]

    beats, cursor = [], 1.0
    for slot, speaker, targets, camera, template, step, event in plan:
        line = by_slot[slot]
        duration = min(5.4, max(2.2, 1.5 + 0.155 * len(line["zh"])))  # retimer refines
        entry = {
            "start": round(cursor, 2), "end": round(cursor + duration, 2),
            "speaker": speaker, "targets": targets, "camera": camera,
            "text": line["zh"], "text_en": line["en"], "emotion": line["emotion"],
            "template": template, "step": step,
        }
        if event:
            t_off = event.pop("t_off")
            entry["event"] = {"t": round(cursor + t_off, 2), **event}
        beats.append(entry)
        cursor = entry["end"] + 0.4
    beats.append({  # wordless closer: luna quiet gaze + robot wave, endcard
        "start": round(cursor, 2), "end": round(cursor + 1.6, 2),
        "speaker": "luna", "targets": ["user"], "camera": "wide_end",
        "text": "", "text_en": "", "emotion": "moved",
        "template": "chatting", "step": "look_at_user",
    })

    payload = {
        "meta": {
            "title": "SoulForge · Evening Companion Replanning Demo (unscripted)",
            "duration_s": round(beats[-1]["end"] + 1.0, 1),  # retimer overrides
            "sim_clock_start": "20:47",
            "generated_by": (f"engine.planner CompanionRuntime + {provider_model} "
                             "(live decisions + live dialogue, unscripted)"),
            "hour_goal_after_rewrite": hour_goal,
        },
        "agents": [
            {
                "id": p.agent_id, "name": p.name, "archetype": p.archetype,
                "voice": p.voice, "role_label": p.meta.get("role_label", ""),
                "color": p.meta.get("color", "#8ecae6"),
                "embodiment": p.meta.get("embodiment", {}),
            }
            for p in personas
        ],
        "plan_before": ["20:00 画画/做饭/植物巡检", "21:00 一起复盘今天", "22:30 休息"],
        "plan_after": [f"20:47 {hour_goal}",
                       f"计划变更: {luna_trace.get('scope', 'hour')} 级重写",
                       "明早 盆栽浇水（Pipo 插入）"],
        "beats": beats,
        "events": [b["event"] for b in beats if b.get("event")],
        "decision_trace": [
            {"t_min": t.t_min, "agent": t.agent_id, "kind": t.kind, "detail": t.detail}
            for t in runtime.trace if t.kind in ("event", "decision", "plan_change")
        ],
        "llm_decisions_full": {"luna": luna_brief, "pipo": pipo_brief},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")

    display = {p.agent_id: p.name for p in personas}
    voice_events = [
        {"time": b["start"], "agentName": display[b["speaker"]], "dialogue": b["text"],
         "emotion": b["emotion"], "actionTemplateId": b["template"], "cameraShot": b["camera"]}
        for b in beats if b["text"]
    ]
    voice_out = OUT.parent / "dinner_voice_events.json"
    voice_out.write_text(json.dumps({"events": voice_events}, ensure_ascii=False, indent=2), "utf-8")
    print(f"wrote {OUT}")
    print(f"wrote {voice_out}")
    print("lines:")
    for b in beats:
        if b["text"]:
            print(f"  [{b['speaker']}] {b['text']}  /  {b['text_en']}")


if __name__ == "__main__":
    main()

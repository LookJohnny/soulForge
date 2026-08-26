"""Web (browser VRM) embodiment: step table, translation, manifest negotiation,
and parity with the JS copy of the table."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.embodiment.web_adapter import (
    PERFORMANCE_TO_CLIP,
    STEP_TO_WEB,
    WebEmbodimentAdapter,
    translate,
    web_manifest,
)
from engine.planner.templates import TEMPLATE_REGISTRY
from engine.server.capability import EmbodimentManifest
from engine.server.protocol import ActionCommand

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "studio" / "web" / "lib" / "action_map.js"


def test_every_planner_micro_step_is_mapped():
    steps = {s for t in TEMPLATE_REGISTRY.values() for s in t.micro_steps}
    steps |= {t.recovery for t in TEMPLATE_REGISTRY.values() if t.recovery}
    missing = sorted(s for s in steps if s not in STEP_TO_WEB)
    assert not missing, missing


def test_primitive_kinds_are_known():
    for step, prim in STEP_TO_WEB.items():
        assert prim["kind"] in {"clip", "gaze", "pose", "idle", "speak"}, step
        if prim["kind"] == "clip":
            assert (
                ROOT / "assets" / "animations" / f"vrma_{prim['clip']}.vrma"
            ).exists(), step


def test_translate_maps_steps_performances_and_unknowns():
    t = translate(ActionCommand(agent_id="luna", name="wave", duration_s=3))
    assert (
        t["kind"] == "clip"
        and t["clip"] == "Goodbye"
        and t["mapped"]
        and t["duration_s"] == 3
    )
    t = translate(
        ActionCommand(agent_id="luna", name="idle", params={"performance": "think"})
    )
    assert t["clip"] == "Thinking"
    t = translate(ActionCommand(agent_id="luna", name="stir_pan", gaze_target="user"))
    assert t["kind"] == "pose" and t["gaze"] == "user"
    t = translate(ActionCommand(agent_id="luna", name="teleport"))
    assert t["kind"] == "gaze" and t["mapped"] is False  # degrade, never reject


def test_manifest_negotiation_accepts_full_vocabulary():
    m = EmbodimentManifest.from_dict(web_manifest("web-1"))
    assert not m.is_fail_closed()
    assert not m.wants_dialogue()  # gateway speaks
    negotiated = set(m.negotiated_steps())
    for t in TEMPLATE_REGISTRY.values():
        for s in t.micro_steps:
            assert m.accepts_step(s), s
    assert "look_at_user" in negotiated and "speak_line" in negotiated
    assert m.accepts_template(next(iter(TEMPLATE_REGISTRY)))
    assert EmbodimentManifest.from_dict(web_manifest("w", speech=True)).wants_dialogue()


def test_adapter_dispatch_complete_interrupt():
    sent: list[dict] = []
    ad = WebEmbodimentAdapter(send=sent.append, body_id="web-x")
    cmd = ActionCommand(agent_id="luna", name="celebrate", duration_s=2.5)
    obs = ad.dispatch(cmd)
    assert (
        obs.status == "accepted"
        and obs.body_id == "web-x"
        and obs.payload["primitive"] == "clip"
    )
    assert sent[0]["type"] == "body_action" and sent[0]["clip"] == "Clapping"
    done = ad.complete(cmd.command_id)
    assert done.status == "done" and ad.complete(cmd.command_id) is None
    ad.dispatch(ActionCommand(agent_id="luna", name="wait"))
    ad.dispatch(ActionCommand(agent_id="kai", name="wave"))
    interrupted = ad.interrupt_all()
    assert {o.status for o in interrupted} == {"interrupted"} and len(interrupted) == 2
    failed = ad.dispatch(ActionCommand(agent_id="luna", name="jump"))
    assert ad.complete(failed.command_id, ok=False).error_code == "E_WEB_ANIM"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_table_matches_python():
    script = f"""
    import {{ STEP_TO_WEB, PERFORMANCE_TO_CLIP }} from {json.dumps(JS.as_uri())};
    process.stdout.write(JSON.stringify({{ steps: STEP_TO_WEB, perf: PERFORMANCE_TO_CLIP }}));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    js = json.loads(proc.stdout)
    assert js["steps"] == STEP_TO_WEB
    assert js["perf"] == PERFORMANCE_TO_CLIP

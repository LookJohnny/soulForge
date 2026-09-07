"""Tavus CVI 接入：真人脸 × SoulForge 大脑。

    .venv/bin/python scripts/tavus_setup.py faces               # 列库存脸
    .venv/bin/python scripts/tavus_setup.py up <tunnel_base>    # 建 PAL+会话，输出加入链接
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "outputs" / "tavus.json"
BASE = "https://tavusapi.com"

SYSTEM_PROMPT = (
    "你是 Joi。你的每一句话都由后端人格引擎生成，请原样说出，不要添加内容。"
)


def setting(name: str) -> str:
    return (os.environ.get(name) or dotenv_values(ROOT / ".env", interpolate=False).get(name) or "").strip()


def api_key() -> str:
    value = setting("TAVUS_API_KEY")
    if not value:
        raise SystemExit("TAVUS_API_KEY is required")
    return value


def connection_config(tunnel: str | None = None) -> dict:
    tunnel = (tunnel or setting("TAVUS_PUBLIC_BASE_URL")).rstrip("/")
    url = urlsplit(tunnel)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path):
        raise SystemExit("TAVUS_PUBLIC_BASE_URL must be an HTTPS origin")
    token = setting("GATEWAY_API_TOKEN")
    if not token:
        raise SystemExit("GATEWAY_API_TOKEN is required before creating a Tavus connection")
    return {"model": "soulforge-brain", "base_url": tunnel + "/v1", "api_key": token,
            # Speculative calls must not create extra persistent decisions.
            "speculative_inference": False}


def call(method: str, path: str, body: dict | list | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-api-key": api_key(), "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def list_faces() -> list[dict]:
    for path in ("/v2/faces?limit=30", "/v2/replicas?limit=30&replica_type=system"):
        status, data = call("GET", path)
        if status == 200:
            items = data.get("data") or data.get("faces") or data.get("replicas") or []
            if items:
                return items
        print(f"  ({path} -> {status})")
    return []


def cmd_faces() -> None:
    for item in list_faces():
        fid = item.get("face_id") or item.get("replica_id")
        name = item.get("face_name") or item.get("replica_name") or ""
        print(fid, "|", name)


def cmd_sync() -> None:
    """Update only the existing PAL's LLM connection; create no conversation."""
    import re

    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    pal_id = setting("TAVUS_PAL_ID") or state.get("pal_id") or state.get("persona_id")
    if not isinstance(pal_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", pal_id):
        raise SystemExit("An existing TAVUS_PAL_ID is required")
    wanted = connection_config()
    path = f"/v2/pals/{pal_id}"
    status, current = call("GET", path)
    if status == 404:
        path = f"/v2/personas/{pal_id}"
        status, current = call("GET", path)
    if status != 200:
        raise SystemExit(f"Cannot read existing PAL: HTTP {status}")
    existing = (current.get("layers") or {}).get("llm") or {}
    if not existing:
        raise SystemExit("PAL has no custom LLM layer; existing configuration left intact")
    operations = [{"op": "replace" if key in existing else "add",
                   "path": f"/layers/llm/{key}", "value": value}
                  for key, value in wanted.items()]
    status, _ = call("PATCH", path, operations)
    if status not in (200, 204, 304):
        raise SystemExit(f"PAL LLM connection update failed: HTTP {status}; no forced overwrite")
    status, verified = call("GET", path)
    actual = (verified.get("layers") or {}).get("llm") or {}
    if status != 200 or any(actual.get(k) != wanted[k]
                            for k in ("model", "base_url", "speculative_inference")):
        raise SystemExit("PAL connection readback did not match; inspect Tavus configuration")
    print("Existing PAL LLM connection synchronized; credentials redacted; no conversation created")


def cmd_up(tunnel: str | None = None) -> None:
    llm_layer = connection_config(tunnel)
    faces = list_faces()
    if not faces:
        raise SystemExit("拿不到库存脸列表——把上面的状态码发我")
    face = faces[0]
    face_id = face.get("face_id") or face.get("replica_id")
    print("face:", face_id, face.get("face_name") or face.get("replica_name"))

    pal_id = None
    for path, name_key, face_key in (
        ("/v2/pals", "pal_name", "default_face_id"),
        ("/v2/personas", "persona_name", "default_replica_id"),
    ):
        status, data = call(
            "POST",
            path,
            {
                name_key: "SoulForge Joi",
                "system_prompt": SYSTEM_PROMPT,
                "pipeline_mode": "full",
                face_key: face_id,
                "layers": {"llm": llm_layer},
            },
        )
        print(f"  create {path} -> {status}")
        pal_id = data.get("pal_id") or data.get("persona_id")
        if status in (200, 201) and pal_id:
            break
    if not pal_id:
        raise SystemExit("PAL/persona 创建失败——把上面的响应发我")

    for body in (
        {"pal_id": pal_id, "face_id": face_id, "conversation_name": "SoulForge 面对面"},
        {"persona_id": pal_id, "replica_id": face_id, "conversation_name": "SoulForge 面对面"},
    ):
        status, data = call("POST", "/v2/conversations", body)
        print(f"  conversation -> {status}")
        if status in (200, 201) and data.get("conversation_url"):
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(
                {"pal_id": pal_id, "face_id": face_id, **data}, ensure_ascii=False, indent=2))
            print("\n✓ 加入链接:", data["conversation_url"])
            return
    raise SystemExit("会话创建失败——把上面的响应发我")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "faces":
        cmd_faces()
    elif len(sys.argv) >= 2 and sys.argv[1] == "up":
        cmd_up(sys.argv[2] if len(sys.argv) >= 3 else None)
    elif len(sys.argv) >= 2 and sys.argv[1] == "--check":
        connection_config()
        api_key()
        print("Tavus connection configuration valid (credentials redacted); no API calls made")
    elif len(sys.argv) >= 2 and sys.argv[1] == "sync":
        cmd_sync()
    else:
        print(__doc__)

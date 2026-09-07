"""Same-origin controls for the local self-hosted WebRTC media service."""

import json
import re
from urllib.parse import urlsplit
from uuid import UUID

import aiohttp
from aiohttp import web

from studio.gateway_proxy import local_url
from studio.tavus_session import require_session_browser

MAX_BODY = 96 * 1024
SESSION_PATH = re.compile(r"sessions/([0-9a-f-]{36})/(turn|interrupt|close)\Z")


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid identifier")
    return value


def _request_body(path, body):
    if not isinstance(body, dict):
        raise ValueError("Expected an object")
    client = _uuid(body.get("client_id"))
    if path == "sessions":
        if set(body) != {"client_id", "sdp", "type"} or body.get("type") != "offer":
            raise ValueError("Expected a WebRTC offer")
        sdp = body.get("sdp")
        if not isinstance(sdp, str) or not sdp.startswith("v=0") or len(sdp) > 65536:
            raise ValueError("Invalid WebRTC offer")
        return {"client_id": client, "sdp": sdp, "type": "offer"}
    if path.endswith("/turn"):
        text = body.get("text")
        if (
            set(body) != {"client_id", "text"}
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 4000
        ):
            raise ValueError("Invalid text")
        return {"client_id": client, "text": text.strip()}
    if set(body) != {"client_id"}:
        raise ValueError("Unexpected fields")
    return {"client_id": client}


def _response(data, status=200):
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


def _safe_result(path, data):
    if not isinstance(data, dict):
        raise ValueError("Invalid upstream response")
    if path == "health":
        # Health never relays credentials, internal URLs, or raw worker errors.
        ready = data.get("ready") is True
        result = {"ready": ready, "status": "ready" if ready else "unavailable"}
        if data.get("status") in {
            "unconfigured",
            "unavailable",
            "degraded",
            "ready",
            "ok",
        }:
            result["status"] = data["status"]
        if data.get("readiness_scope") == "worker_loaded_and_brain_route_configured":
            result["readiness_scope"] = data["readiness_scope"]
        if type(data.get("end_to_end_verified")) is bool:
            result["end_to_end_verified"] = data["end_to_end_verified"]
        brain = data.get("brain")
        if isinstance(brain, dict):
            safe_brain = {
                key: brain[key]
                for key in ("ready", "configured", "end_to_end_verified")
                if type(brain.get(key)) is bool
            }
            if brain.get("readiness_scope") in {
                "config-only",
                "configuration_only",
                "configured",
            }:
                safe_brain["readiness_scope"] = brain["readiness_scope"]
            dependencies = brain.get("dependencies")
            if isinstance(dependencies, dict):
                safe_dependencies = {}
                for name in ("runtime", "ai_core", "asr"):
                    source = dependencies.get(name)
                    if not isinstance(source, dict):
                        continue
                    item = (
                        {"configured": source["configured"]}
                        if type(source.get("configured")) is bool
                        else {}
                    )
                    if "reachable" in source and (
                        source["reachable"] is None or type(source["reachable"]) is bool
                    ):
                        item["reachable"] = source["reachable"]
                    if item:
                        safe_dependencies[name] = item
                if safe_dependencies:
                    safe_brain["dependencies"] = safe_dependencies
            if safe_brain:
                result["brain"] = safe_brain
        return result
    if path == "sessions":
        sid = _uuid(data.get("session_id"))
        sdp = data.get("sdp")
        if (
            data.get("type") != "answer"
            or not isinstance(sdp, str)
            or not sdp.startswith("v=0")
            or len(sdp) > 65536
        ):
            raise ValueError("Invalid WebRTC answer")
        return {"session_id": sid, "sdp": sdp, "type": "answer"}
    if data.get("ok") is False or data.get("error"):
        raise ValueError("Upstream operation failed")
    result = {"ok": True}
    if isinstance(data.get("turn_id"), str) and re.fullmatch(
        r"[A-Za-z0-9_-]{1,128}", data["turn_id"]
    ):
        result["turn_id"] = data["turn_id"]
    if type(data.get("epoch")) is int and 0 <= data["epoch"] < 2**53:
        result["epoch"] = data["epoch"]
    return result


async def proxy(request, *, setting):
    require_session_browser(request)
    path = request.match_info.get("path", "")
    match = SESSION_PATH.fullmatch(path)
    valid = (request.method == "GET" and path == "health") or (
        request.method == "POST"
        and (path in {"sessions", "sessions/close-owned"} or match is not None)
    )
    if not valid or request.query_string:
        return _response({"error": "Unsupported media operation"}, 404)
    try:
        if match:
            _uuid(match[1])
    except (ValueError, TypeError):
        return _response({"error": "Unsupported media operation"}, 404)
    try:
        url = local_url(setting("SELFHOST_MEDIA_URL") or "http://127.0.0.1:8902")
        if urlsplit(url).path not in ("", "/"):
            raise ValueError("Unexpected upstream path")
        token = (setting("SELFHOST_MEDIA_TOKEN") or "").strip()
        if not token:
            raise ValueError("Missing media credential")
    except (ValueError, TypeError):
        return _response(
            {"ready": False, "status": "unconfigured", "error": "GPU 服务未配置"}, 503
        )
    body = None
    if request.method == "POST":
        try:
            raw = bytearray()
            async for chunk in request.content.iter_chunked(8192):
                raw.extend(chunk)
                if len(raw) > MAX_BODY:
                    return _response({"error": "Request is too large"}, 413)
            body = _request_body(path, json.loads(raw))
        except (ValueError, TypeError, UnicodeDecodeError):
            return _response({"error": "Invalid media request"}, 400)
    try:
        async with aiohttp.ClientSession(trust_env=False) as client:
            async with client.request(
                request.method,
                url + "/" + path,
                json=body,
                headers={"Authorization": "Bearer " + token},
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=40 if path == "sessions" else 15),
            ) as upstream:
                if not 200 <= upstream.status < 300:
                    status = (
                        upstream.status
                        if upstream.status in {400, 403, 404, 409, 429, 503}
                        else 502
                    )
                    message = (
                        "GPU 服务未就绪，请检查服务状态"
                        if status == 503
                        else "视频服务暂时无法处理此操作"
                    )
                    return _response({"ready": False, "error": message}, status)
                raw = bytearray()
                async for chunk in upstream.content.iter_chunked(8192):
                    raw.extend(chunk)
                    if len(raw) > MAX_BODY:
                        raise ValueError("Oversized upstream response")
                data = json.loads(raw) if raw else {}
                return _response(_safe_result(path, data))
    except (OSError, TimeoutError, ValueError, TypeError, aiohttp.ClientError):
        return _response(
            {"ready": False, "status": "unavailable", "error": "GPU 视频服务无法连接"},
            503,
        )


def register(app, *, setting):
    async def handler(request):
        return await proxy(request, setting=setting)

    app.router.add_route("*", "/api/selfhost/{path:.*}", handler)

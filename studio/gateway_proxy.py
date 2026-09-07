"""Local browser controls; server credentials never cross into the webview."""

import asyncio
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from aiohttp import web
import websockets


def local_url(url: str, *, websocket: bool = False) -> str:
    parsed = urlsplit(url)
    schemes = {"ws", "wss"} if websocket else {"http", "https"}
    if (
        parsed.scheme not in schemes
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Upstream must be a loopback service URL")
    return url.rstrip("/")


def require_local_browser(request: web.Request) -> None:
    try:
        is_loopback = ipaddress.ip_address(request.remote or "").is_loopback
    except ValueError:
        is_loopback = False
    origin = urlsplit(request.headers.get("Origin", ""))
    if (
        not is_loopback
        or origin.scheme != request.scheme
        or origin.netloc != request.host
        or origin.hostname not in {"localhost", "127.0.0.1", "::1"}
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise web.HTTPForbidden(text="Local same-origin browser access required")


async def switch_agent(
    request: web.Request,
    *,
    gateway_url: str,
    token: str,
    runtime_url: str,
    agent_ids: set[str],
) -> web.Response:
    require_local_browser(request)
    if not token.strip():
        return web.json_response(
            {"error": "Gateway HTTP access is not configured"}, status=503
        )
    try:
        gateway_url = local_url(gateway_url)
        runtime_url = local_url(runtime_url, websocket=True).removesuffix("/body")
    except ValueError:
        return web.json_response(
            {"error": "Local upstream configuration is invalid"}, status=503
        )
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return web.json_response({"error": "Invalid JSON"}, status=400)
    agent_id = body.get("agent_id") if isinstance(body, dict) else None
    if not isinstance(agent_id, str) or agent_id not in agent_ids:
        return web.json_response({"error": "Unknown installed character"}, status=400)

    try:
        # Reload only the installed roster, never arbitrary browser events or URLs.
        async with websockets.connect(
            runtime_url + "/control", open_timeout=5, proxy=None
        ) as ws:
            await ws.send(json.dumps({"type": "reload_personas"}))
            async with asyncio.timeout(10):
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("type") == "error":
                        raise RuntimeError("Runtime reload rejected")
                    if data.get("type") == "personas":
                        if agent_id not in data.get("agents", []):
                            raise RuntimeError("Runtime did not install the character")
                        break
                else:
                    raise RuntimeError("Runtime closed before confirming reload")
        async with aiohttp.ClientSession(trust_env=False) as client:
            async with client.post(
                gateway_url + "/admin/runtime-agent",
                json={"agent_id": agent_id},
                headers={"Authorization": "Bearer " + token.strip()},
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    return web.json_response(
                        {
                            "error": f"Gateway refused character switch (HTTP {response.status})"
                        },
                        status=502,
                    )
                result = await response.json()
                if not result.get("ok") or result.get("agent_id") != agent_id:
                    raise RuntimeError("Gateway did not confirm character switch")
        return web.json_response({"ok": True, "agent_id": agent_id})
    except (
        OSError,
        ValueError,
        RuntimeError,
        TimeoutError,
        aiohttp.ClientError,
        websockets.WebSocketException,
    ):
        return web.json_response(
            {"error": "Character switch failed; check local service logs"}, status=502
        )


async def _read_health(
    url: str,
    *,
    headers: dict | None = None,
    allow_text_json: bool = False,
) -> dict:
    async with aiohttp.ClientSession(trust_env=False) as client:
        async with client.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=3),
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise RuntimeError("Provider health request failed")
            data = await response.json(
                content_type=None if allow_text_json else "application/json"
            )
            if not isinstance(data, dict) or not isinstance(data.get("status"), str):
                raise ValueError("Invalid provider health response")
            return data


async def _runtime_health(runtime_url: str) -> dict:
    try:
        parsed = urlsplit(local_url(runtime_url, websocket=True))
        url = urlunsplit(
            (
                "https" if parsed.scheme == "wss" else "http",
                parsed.netloc,
                "/health/providers",
                "",
                "",
            )
        )
        # websockets.respond() may retain its default text/plain header when
        # Runtime adds application/json. This fixed local endpoint still must
        # return valid JSON with a status; a MIME mismatch isn't disconnection.
        return await _read_health(url, allow_text_json=True)
    except (OSError, ValueError, RuntimeError, TimeoutError, aiohttp.ClientError):
        return {"status": "unavailable"}


async def _ai_core_health(ai_core_url: str, token: str, brand_id: str) -> dict:
    # Both headers are needed by AI Core's service authentication middleware.
    if not token.strip() or not brand_id.strip():
        return {"status": "unavailable"}
    try:
        url = local_url(ai_core_url) + "/health/providers"
        return await _read_health(
            url,
            headers={
                "X-Service-Token": token.strip(),
                "X-Brand-Id": brand_id.strip(),
            },
        )
    except (OSError, ValueError, RuntimeError, TimeoutError, aiohttp.ClientError):
        return {"status": "unavailable"}


def _health_text(value, secret: str) -> str | None:
    if not isinstance(value, str):
        return None
    if secret:
        value = value.replace(secret, "[redacted]")
    return re.sub(r"(?:https?|wss?)://\S+", "[endpoint]", value)[:500]


def _health_status(value) -> str:
    return (
        value
        if value in ("ok", "unknown", "degraded", "unavailable", "mock")
        else "unknown"
    )


def _health_count(value):
    return value if type(value) is int and value >= 0 else None


def _provider_rows(data: dict, service: str, secret: str) -> list[dict]:
    raw = data.get("providers")
    rows = []
    for provider in raw[:64] if isinstance(raw, list) else []:
        if not isinstance(provider, dict):
            continue
        name = _health_text(provider.get("provider"), secret) or "provider"
        kind = _health_text(provider.get("kind"), secret)
        successes = _health_count(
            provider.get("successes", provider.get("success_count"))
        )
        failures = _health_count(
            provider.get("failures", provider.get("failure_count"))
        )
        calls = _health_count(provider.get("calls"))
        if calls is None and successes is not None and failures is not None:
            calls = successes + failures
        error = provider.get("last_error")
        if isinstance(error, dict):
            error_type = _health_text(error.get("type"), secret)
            code = _health_count(error.get("status_code"))
            error = f"{error_type} (HTTP {code})" if error_type and code else error_type
        rows.append(
            {
                "service": service,
                "provider": " · ".join(part for part in (service, kind, name) if part),
                "kind": kind,
                "model": _health_text(provider.get("model"), secret),
                "status": _health_status(provider.get("status")),
                "calls": calls,
                "successes": successes,
                "failures": failures,
                "consecutive_failures": _health_count(
                    provider.get("consecutive_failures")
                ),
                "fallback_count": _health_count(provider.get("fallback_count")),
                "fallback_active": provider.get("fallback_active") is True,
                "last_success_at": _health_text(
                    provider.get("last_success_at"), secret
                ),
                "last_failure_at": _health_text(
                    provider.get("last_failure_at"), secret
                ),
                "last_error": _health_text(error, secret),
            }
        )
    if not rows:
        rows.append(
            {
                "service": service,
                "provider": service,
                "status": "unavailable"
                if data.get("status") == "unavailable"
                else "unknown",
            }
        )
    return rows


async def provider_health(
    runtime_url: str,
    *,
    ai_core_url: str = "",
    service_token: str = "",
    brand_id: str = "",
) -> dict:
    """Observation only: report both brain layers, without triggering providers."""
    runtime, core = await asyncio.gather(
        _runtime_health(runtime_url),
        _ai_core_health(ai_core_url, service_token, brand_id),
    )
    providers = _provider_rows(
        runtime, "runtime", service_token.strip()
    ) + _provider_rows(core, "ai-core", service_token.strip())
    fallback_active = runtime.get("fallback_active") is True or any(
        p.get("fallback_active") is True for p in providers
    )
    statuses = [
        _health_status(runtime.get("status")),
        _health_status(core.get("status")),
    ]
    statuses.extend(p["status"] for p in providers)
    if runtime.get("status") == "unavailable":
        status = "unavailable"
    elif fallback_active or any(
        s in {"degraded", "unavailable", "mock"} for s in statuses
    ):
        status = "degraded"
    else:
        status = "ok" if all(s == "ok" for s in statuses) else "unknown"

    raw_memory = runtime.get("memory")
    memory = {}
    if isinstance(raw_memory, dict):
        memory = {
            "persistent": raw_memory.get("persistent")
            if type(raw_memory.get("persistent")) is bool
            else None,
            "ready": raw_memory.get("ready")
            if type(raw_memory.get("ready")) is bool
            else None,
            "pending_writes": _health_count(raw_memory.get("pending_writes")),
            "writes_completed": _health_count(raw_memory.get("writes_completed")),
            "status": _health_text(raw_memory.get("status"), service_token.strip()),
            "last_error": _health_text(
                raw_memory.get("last_error"), service_token.strip()
            ),
        }
    ready = runtime.get("ready") is True
    if status == "ok" and (
        not ready
        or memory.get("persistent") is not True
        or memory.get("ready") is not True
        or memory.get("last_error")
    ):
        status = "unknown"
    return {
        "service": "studio",
        "source": "character-runtime",
        "status": status,
        "ready": ready,
        "fallback_active": fallback_active,
        "fallback_count": _health_count(runtime.get("fallback_count")),
        "providers": providers,
        "memory": memory,
    }

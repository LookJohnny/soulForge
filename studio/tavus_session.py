"""A single, explicitly started Tavus room owned by this local Studio.

Contract checked against https://docs.tavus.io/openapi.yaml (2026-09-07).
Only an existing PAL is used. Credentials and room tokens are never persisted;
the private journal records ownership before POST so uncertain creates can be
reconciled after a crash. This module never adopts outputs/tavus.json rooms.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Callable
from urllib.parse import urlsplit
import uuid

import aiohttp
from aiohttp import web

from studio.gateway_proxy import require_local_browser

API_BASE = "https://tavusapi.com"
MAX_CALL_SECONDS = 300
ABSENT_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 30
ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
APP_KEY = web.AppKey("joi_tavus_session", object)


class SessionError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


async def tavus_request(method: str, path: str, key: str, body: dict | None = None):
    """Fixed API host, no proxy/redirects, and no raw provider error disclosure."""
    try:
        async with aiohttp.ClientSession(trust_env=False) as client:
            async with client.request(
                method,
                API_BASE + path,
                headers={"x-api-key": key},
                json=body,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS),
                allow_redirects=False,
            ) as response:
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > 256 * 1024:
                        raise SessionError("Tavus response exceeded the supported size")
                    chunks.append(chunk)
                payload = b"".join(chunks)
                try:
                    data = json.loads(payload) if payload else {}
                except (ValueError, UnicodeDecodeError):
                    data = {}
                return response.status, data if isinstance(data, dict) else {}
    except (OSError, TimeoutError, aiohttp.ClientError):
        raise SessionError("Tavus request failed; the room may need cleanup") from None


def _identifier(value) -> bool:
    return isinstance(value, str) and ID.fullmatch(value) is not None


def _client_id(value) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def require_session_browser(request: web.Request) -> None:
    # Same-origin GET fetch normally omits Origin. Fetch Metadata is browser
    # controlled; never accept same-site, navigation, or an unmarked request.
    if request.method == "GET" and not request.headers.get("Origin"):
        if (
            request.headers.get("Sec-Fetch-Site") != "same-origin"
            or request.headers.get("Sec-Fetch-Mode") not in {"cors", "same-origin"}
            or request.headers.get("Sec-Fetch-Dest") != "empty"
        ):
            raise web.HTTPForbidden(text="Local same-origin browser access required")
        request = request.clone(
            headers={
                **request.headers,
                "Origin": f"{request.scheme}://{request.host}",
            }
        )
    require_local_browser(request)


class TavusSessionManager:
    def __init__(
        self,
        setting: Callable[[str], str],
        state_path: Path,
        *,
        request=tavus_request,
        clock=time.time,
    ):
        self.setting = setting
        self.state_path = Path(state_path)
        self.request = request
        self.clock = clock
        self.record: dict | None = None
        self.join_info: dict | None = None
        self.last_error: str | None = None
        self.credential_verification = "not_checked"
        self._lock = asyncio.Lock()
        self._file_lock = None
        self._reaper = None
        self._closed = False
        self._blocked = False

    def _config(self) -> tuple[str, str, dict]:
        key = self.setting("TAVUS_API_KEY").strip()
        pal = self.setting("TAVUS_PAL_ID").strip()
        origin = self.setting("TAVUS_PUBLIC_BASE_URL").strip().rstrip("/")
        token = self.setting("GATEWAY_API_TOKEN").strip()
        try:
            parsed = urlsplit(origin)
            valid_url = (
                parsed.scheme == "https"
                and parsed.hostname
                and not (
                    parsed.username
                    or parsed.password
                    or parsed.path
                    or parsed.query
                    or parsed.fragment
                )
            )
        except ValueError:
            valid_url = False
        if not key or not _identifier(pal) or not token or not valid_url:
            raise SessionError(
                "Tavus and the local brain connection are not configured", 503
            )
        return (
            key,
            pal,
            {
                "model": "soulforge-brain",
                "base_url": origin + "/v1",
                "api_key": token,
                "speculative_inference": False,
            },
        )

    async def start(self):
        """Acquire sole ownership before loading the private recovery journal."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(
                self.state_path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600
            )
            self._file_lock = os.fdopen(fd, "a")
            fcntl.flock(self._file_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text())
                record = data.get("record") if isinstance(data, dict) else None
                if (
                    not isinstance(data, dict)
                    or data.get("version") != 1
                    or (record is not None and not self._valid_record(record))
                ):
                    raise ValueError("Invalid ownership journal")
                self.record = record
                if self.record:
                    # A restart has no browser or room token to resume. End only
                    # this module's own room, never an unrelated legacy room.
                    self.record["phase"] = "cleanup_pending"
                    self._save()
        except (OSError, ValueError, TypeError):
            self._blocked = True
            self.last_error = (
                "Session ownership storage is unavailable; creation is disabled"
            )
        if not self._blocked:
            self._reaper = asyncio.create_task(self._reap(), name="joi-room-cleanup")

    @staticmethod
    def _valid_record(record) -> bool:
        if not isinstance(record, dict):
            return False
        nonce = record.get("nonce", "")
        created, expires = record.get("created_at"), record.get("expires_at")
        return (
            isinstance(nonce, str)
            and re.fullmatch(r"[a-f0-9]{32}", nonce) is not None
            and record.get("conversation_name") == f"SoulForge Joi {nonce}"
            and _client_id(record.get("client_id"))
            and _identifier(record.get("pal_id"))
            and isinstance(record.get("key_hash"), str)
            and re.fullmatch(r"[a-f0-9]{64}", record["key_hash"]) is not None
            and record.get("phase") in {"creating", "active", "cleanup_pending"}
            and (
                record.get("conversation_id") is None
                or _identifier(record["conversation_id"])
            )
            and type(created) in (int, float)
            and type(expires) in (int, float)
            and math.isfinite(created)
            and math.isfinite(expires)
            and 0 < created < 253402300000
            and 0 < expires - created <= MAX_CALL_SECONDS
        )

    def _save(self):
        # Atomic replacement + fsync before network mutation; no token/API key.
        fd, temp = tempfile.mkstemp(prefix=".joi-", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"version": 1, "record": self.record}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.state_path)
            parent_fd = os.open(self.state_path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temp)

    def _clear(self):
        previous = self.record
        self.record = None
        self.join_info = None
        try:
            self._save()
        except OSError:
            self.record = previous
            raise SessionError(
                "Session cleanup could not be saved; retry cleanup", 503
            ) from None
        self.last_error = None

    def snapshot(self) -> dict:
        try:
            self._config()
            configured = True
        except SessionError:
            configured = False
        state = (
            "unavailable"
            if self._blocked or not configured or self._closed
            else "idle"
            if not self.record
            else "active"
            if self.record["phase"] == "active"
            else "cleanup_pending"
        )
        session = None
        if self.record and self.record.get("conversation_id"):
            session = {
                "conversation_id": self.record["conversation_id"],
                "expires_at": _timestamp(self.record["expires_at"]),
            }
        result = {
            "ok": True,
            "configured": configured,
            "status": state,
            "session": session,
            "credential_verification": self.credential_verification,
            "max_call_duration_s": MAX_CALL_SECONDS,
            "participant_absent_timeout_s": ABSENT_SECONDS,
        }
        if self.last_error:
            result["error"] = self.last_error
        return result

    async def _verify_pal(self, key, pal, expected):
        self.credential_verification = "not_checked"
        status, data = await self.request("GET", f"/v2/pals/{pal}", key)
        layers = data.get("layers")
        llm = layers.get("llm") if isinstance(layers, dict) else None
        if (
            status != 200
            or data.get("pal_id") != pal
            or not _identifier(data.get("default_face_id"))
        ):
            raise SessionError(
                "The configured Tavus PAL or its existing face is unavailable", 503
            )
        if (
            not isinstance(llm, dict)
            or any(llm.get(name) != expected[name] for name in ("model", "base_url"))
            or llm.get("speculative_inference") is not False
        ):
            raise SessionError(
                "The Tavus PAL does not match the local brain connection; sync it first",
                409,
            )
        remote_key = llm.get("api_key")
        # Tavus GET PAL redacts the configured key with exactly eight stars.
        # This is not a credential readback verification. The existing startup
        # scripts/tavus_setup.py cmd_sync PATCH supplies the actual Gateway key;
        # Gateway authentication remains the authority when a real call arrives.
        if remote_key == "********":
            self.credential_verification = "provider_redacted"
        elif isinstance(remote_key, str) and hmac.compare_digest(
            remote_key.encode(), expected["api_key"].encode()
        ):
            self.credential_verification = "matched"
        else:
            raise SessionError(
                "The Tavus PAL does not match the local brain connection; sync it first",
                409,
            )

    def _join_response(self, reused: bool) -> dict:
        result = self.snapshot()
        result["session"] = {**result["session"], **self.join_info}
        result["reused"] = reused
        return result

    async def create(self, client_id: str) -> dict:
        async with self._lock:
            if not _client_id(client_id):
                raise SessionError("A valid browser client_id is required", 400)
            if self._blocked or self._closed or self._file_lock is None:
                raise SessionError(
                    "Session ownership storage is unavailable; creation is disabled",
                    503,
                )
            key, pal, expected = self._config()
            if self.record:
                if self.record["client_id"] != client_id:
                    raise SessionError(
                        "Another browser page owns the active session", 409
                    )
                if (
                    self.record["phase"] == "active"
                    and self.join_info
                    and self.clock() < self.record["expires_at"]
                ):
                    return self._join_response(True)
                raise SessionError(
                    "The previous room is awaiting cleanup; retry after it ends", 409
                )
            await self._verify_pal(key, pal, expected)
            nonce = uuid.uuid4().hex
            created = self.clock()
            self.record = {
                "nonce": nonce,
                "conversation_name": f"SoulForge Joi {nonce}",
                "client_id": client_id,
                "pal_id": pal,
                "key_hash": hashlib.sha256(key.encode()).hexdigest(),
                "created_at": created,
                "expires_at": created + MAX_CALL_SECONDS,
                "conversation_id": None,
                "phase": "creating",
            }
            try:
                self._save()
            except OSError:
                self.record = None
                raise SessionError(
                    "Cannot save session ownership; no room was created", 503
                ) from None
            payload = {
                "pal_id": pal,
                "conversation_name": self.record["conversation_name"],
                "require_auth": True,
                "max_participants": 2,
                "properties": {
                    "max_call_duration": MAX_CALL_SECONDS,
                    "participant_absent_timeout": ABSENT_SECONDS,
                    "participant_left_timeout": 10,
                    "enable_recording": False,
                    "auto_start_recording": False,
                },
            }
            try:
                status, data = await self.request(
                    "POST", "/v2/conversations", key, payload
                )
                if status not in (200, 201):
                    # A 4xx is a rejected creation. 5xx/network failures can occur
                    # after creation; retain the nonce and never retry POST blind.
                    if 400 <= status < 500:
                        self._clear()
                    raise SessionError(
                        f"Tavus refused session creation (HTTP {status})"
                    )
                cid = data.get("conversation_id")
                if _identifier(cid):
                    self.record["conversation_id"] = cid
                    self._save()
                url, token = data.get("conversation_url"), data.get("meeting_token")
                try:
                    parsed = urlsplit(url) if isinstance(url, str) else None
                except ValueError:
                    parsed = None
                if (
                    not _identifier(cid)
                    or data.get("status") != "active"
                    or parsed is None
                    or parsed.scheme != "https"
                    or not parsed.hostname
                    or not parsed.hostname.endswith(".daily.co")
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                    or not isinstance(token, str)
                    or not token.strip()
                    or len(token) > 16384
                ):
                    raise SessionError(
                        "Tavus did not return a usable private room; cleanup requested"
                    )
                self.join_info = {"conversation_url": url, "meeting_token": token}
                self.record["phase"] = "active"
                self._save()
                self.last_error = None
                return self._join_response(False)
            except (SessionError, OSError, ValueError, asyncio.CancelledError):
                if self.record:
                    self.record["phase"] = "cleanup_pending"
                    self.join_info = None
                    with suppress(OSError):
                        self._save()
                    self.last_error = (
                        "Session creation was not completed; cleanup is pending"
                    )
                    # Cancellation/crash still leaves a durable intent for reaper.
                    with suppress(SessionError, OSError):
                        await self._cleanup_locked()
                raise

    def _owned(self, data: dict) -> bool:
        return (
            data.get("conversation_name") == self.record["conversation_name"]
            and data.get("pal_id") == self.record["pal_id"]
            and _identifier(data.get("conversation_id"))
            and (
                self.record.get("conversation_id") is None
                or data["conversation_id"] == self.record["conversation_id"]
            )
        )

    def _cleanup_key(self) -> str:
        key = self.setting("TAVUS_API_KEY").strip()
        if not key or not hmac.compare_digest(
            hashlib.sha256(key.encode()).hexdigest(), self.record["key_hash"]
        ):
            raise SessionError(
                "Session cleanup needs the same Tavus account credential", 503
            )
        return key

    async def _find_uncertain_room(self, key: str) -> bool:
        # Exact unpredictable name + PAL matching; never clean another room merely
        # because it appears in the same account. Pagination is explicitly bounded.
        for page in range(1, 21):
            status, data = await self.request(
                "GET", f"/v2/conversations?limit=100&page={page}", key
            )
            items, total = data.get("data"), data.get("total_count")
            if status != 200 or not isinstance(items, list) or type(total) is not int:
                raise SessionError("Unable to reconcile an uncertain room creation")
            matches = [
                item for item in items if isinstance(item, dict) and self._owned(item)
            ]
            if len(matches) > 1:
                raise SessionError(
                    "Ambiguous session ownership; automatic cleanup is paused", 409
                )
            if matches:
                self.record["conversation_id"] = matches[0]["conversation_id"]
                self._save()
                return True
            if page * 100 >= total:
                # Let an in-flight POST settle before deciding that no room exists.
                if self.clock() > self.record["expires_at"] + HTTP_TIMEOUT_SECONDS:
                    self._clear()
                return False
        raise SessionError(
            "Room reconciliation exceeded its page limit; cleanup remains pending"
        )

    async def _read_owned(self, key: str) -> dict | None:
        status, data = await self.request(
            "GET", f"/v2/conversations/{self.record['conversation_id']}", key
        )
        if status in (404, 410):
            self._clear()
            return None
        if status != 200:
            raise SessionError("Unable to verify the owned Tavus room")
        if not self._owned(data):
            raise SessionError(
                "Room ownership did not match; no remote session was ended", 409
            )
        if data.get("status") == "ended":
            self._clear()
            return None
        if data.get("status") != "active":
            raise SessionError("Tavus room status is unknown; cleanup remains pending")
        return data

    async def _cleanup_locked(self):
        if not self.record:
            return
        self.record["phase"] = "cleanup_pending"
        self.join_info = None
        self._save()
        key = self._cleanup_key()
        if not self.record.get(
            "conversation_id"
        ) and not await self._find_uncertain_room(key):
            return
        if await self._read_owned(key) is None:
            return
        status, _ = await self.request(
            "POST", f"/v2/conversations/{self.record['conversation_id']}/end", key
        )
        if status != 200:
            raise SessionError(f"Tavus did not confirm session cleanup (HTTP {status})")
        self._clear()

    async def end(self, conversation_id: str | None, client_id: str) -> dict:
        async with self._lock:
            if not _client_id(client_id):
                raise SessionError("A valid browser client_id is required", 400)
            if self._blocked or self._closed or self._file_lock is None:
                raise SessionError("Session ownership storage is unavailable", 503)
            if self.record and client_id != self.record["client_id"]:
                raise SessionError("This browser page does not own the session", 403)
            if self.record and conversation_id != self.record.get("conversation_id"):
                raise SessionError(
                    "The requested room is not the current owned session", 409
                )
            try:
                await self._cleanup_locked()
            except (SessionError, OSError) as error:
                self.last_error = (
                    str(error)
                    if isinstance(error, SessionError)
                    else "Session cleanup storage failed; cleanup remains pending"
                )
                raise
            if self.record:
                raise SessionError(
                    "Session cleanup is still pending; it will be retried", 503
                )
            return self.snapshot()

    async def maintain(self):
        """Periodic cleanup also observes Tavus's 120 s absent-participant cap."""
        async with self._lock:
            if not self.record:
                return
            try:
                if (
                    self.record["phase"] != "active"
                    or self.clock() >= self.record["expires_at"]
                ):
                    await self._cleanup_locked()
                else:
                    await self._read_owned(self._cleanup_key())
                self.last_error = None
            except (SessionError, OSError) as error:
                self.last_error = (
                    str(error)
                    if isinstance(error, SessionError)
                    else "Session cleanup storage failed; cleanup remains pending"
                )

    async def _reap(self):
        while True:
            await self.maintain()
            await asyncio.sleep(10)

    async def close(self):
        self._closed = True
        if self._reaper:
            self._reaper.cancel()
            with suppress(asyncio.CancelledError):
                await self._reaper
        try:
            if not self._blocked and self._file_lock is not None:
                async with self._lock:
                    with suppress(SessionError, OSError, TimeoutError):
                        async with asyncio.timeout(15):
                            await self._cleanup_locked()
        finally:
            if self._file_lock:
                self._file_lock.close()
                self._file_lock = None


def register(
    app: web.Application,
    *,
    setting: Callable[[str], str],
    state_path: Path,
    request=tavus_request,
) -> TavusSessionManager:
    manager = TavusSessionManager(setting, state_path, request=request)
    app[APP_KEY] = manager

    async def lifecycle(_app):
        await manager.start()
        try:
            yield
        finally:
            await manager.close()

    def response(data: dict, status: int = 200):
        return web.json_response(
            data, status=status, headers={"Cache-Control": "no-store"}
        )

    async def status_handler(req):
        require_session_browser(req)
        return response(manager.snapshot())

    async def mutate(req, *, ending: bool):
        require_session_browser(req)
        try:
            body = await req.json() if req.can_read_body else {}
            allowed = {"client_id", "conversation_id"} if ending else {"client_id"}
            if not isinstance(body, dict) or set(body) - allowed:
                raise SessionError("Unsupported session request fields", 400)
            cid = body.get("conversation_id")
            client_id = body.get("client_id")
            if ending and cid is not None and not _identifier(cid):
                raise SessionError("Invalid conversation identifier", 400)
            data = (
                await manager.end(cid, client_id)
                if ending
                else await manager.create(client_id)
            )
            return response(data)
        except (ValueError, UnicodeDecodeError):
            return response({"ok": False, "error": "Invalid session request JSON"}, 400)
        except SessionError as error:
            return response(
                {**manager.snapshot(), "ok": False, "error": str(error)}, error.status
            )
        except OSError:
            return response(
                {
                    **manager.snapshot(),
                    "ok": False,
                    "error": "Session storage failed; cleanup remains pending",
                },
                503,
            )

    async def create_handler(req):
        return await mutate(req, ending=False)

    async def end_handler(req):
        return await mutate(req, ending=True)

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/api/joi/session", status_handler)
    app.router.add_post("/api/joi/session", create_handler)
    app.router.add_post("/api/joi/session/end", end_handler)
    return manager

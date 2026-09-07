"""Supervise the local stack and optional video body; read .env as data."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener
from uuid import UUID

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parent.parent


def load_environment(root: Path, overrides: dict[str, str] | None = None) -> dict[str, str]:
    configured = {k: v for k, v in dotenv_values(root / ".env", interpolate=False).items() if v is not None}
    # In ordinary launches the file wins over stale shell exports. Explicit
    # programmatic overrides remain available for isolated tests.
    env = dict(os.environ) if overrides is None else {}
    env.update(configured)
    if overrides is not None:
        env.update(overrides)
    defaults = {"AI_CORE_URL": "http://127.0.0.1:8100", "GATEWAY_PORT": "8081",
                "CHARACTER_RUNTIME_URL": "ws://127.0.0.1:8765", "CHARACTER_RUNTIME_AGENT": "joi",
                "STUDIO_PORT": "8899", "SOULFORGE_MEMORY_BACKEND": "ai-core",
                "RUNTIME_TIME_SCALE": "2", "RUNTIME_LLM_TIMEOUT": "30", "RUNTIME_SOCIAL": "false",
                "LIVE_TUNNEL_PROVIDER": "none", "LIVE_TUNNEL_PORT": "8091"}
    for key, value in defaults.items():
        env.setdefault(key, value)
    env.setdefault("SOULFORGE_COGNITION_URL", env["AI_CORE_URL"])
    env["GATEWAY_WS_URL"] = f"ws://127.0.0.1:{env['GATEWAY_PORT']}/ws"
    env["GATEWAY_API_URL"] = f"http://127.0.0.1:{env['GATEWAY_PORT']}"
    env.setdefault("SELFHOST_MEDIA_ENABLED", "false")
    env.setdefault("SELFHOST_MEDIA_PORT", "8902")
    env.setdefault("SELFHOST_MEDIA_URL", f"http://127.0.0.1:{env['SELFHOST_MEDIA_PORT']}")
    env["RUNTIME_WS_URL"] = env["CHARACTER_RUNTIME_URL"].rstrip("/").removesuffix("/body") + "/body"
    for key in ("NO_PROXY", "no_proxy"):
        env[key] = ",".join(filter(None, [env.get(key), "localhost", "127.0.0.1", "::1"]))
    return env


def _port(value: str, name: str) -> int:
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    raise ValueError(f"{name} must be a port from 1 to 65535")


def _local_endpoint(value: str, scheme: str, name: str) -> int:
    url = urlsplit(value)
    if (url.scheme != scheme or url.hostname not in {"127.0.0.1", "localhost"}
            or url.path not in {"", "/"} or url.query or url.fragment or url.username or url.password):
        raise ValueError(f"{name} must be a plain {scheme}://127.0.0.1:<port> local base URL")
    return _port(str(url.port or (80 if scheme == "http" else 8765)), name)


def validate(env: dict[str, str]) -> dict[str, int]:
    for key in ("SOULFORGE_BRAND_ID", "SERVICE_TOKEN", "GATEWAY_API_TOKEN"):
        if not env.get(key, "").strip() or env[key].strip().lower() in {
            "change-me", "soulforge", "your-token", "your-gateway-api-token",
        }:
            raise ValueError(f"{key} must be configured in the root .env")
    try:
        UUID(env["SOULFORGE_BRAND_ID"])
        if env.get("SOULFORGE_USER_ID"):
            UUID(env["SOULFORGE_USER_ID"])
    except ValueError:
        raise ValueError("SOULFORGE_BRAND_ID and optional SOULFORGE_USER_ID must be UUIDs") from None
    if env["SOULFORGE_MEMORY_BACKEND"] != "ai-core":
        raise ValueError("The live stack requires SOULFORGE_MEMORY_BACKEND=ai-core")
    if env["SOULFORGE_COGNITION_URL"].rstrip("/") != env["AI_CORE_URL"].rstrip("/"):
        raise ValueError("SOULFORGE_COGNITION_URL must match AI_CORE_URL in this local stack")
    ports = {"ai-core": _local_endpoint(env["AI_CORE_URL"], "http", "AI_CORE_URL"),
             "runtime": _local_endpoint(env["CHARACTER_RUNTIME_URL"], "ws", "CHARACTER_RUNTIME_URL"),
             "gateway": _port(env["GATEWAY_PORT"], "GATEWAY_PORT"),
             "studio": _port(env["STUDIO_PORT"], "STUDIO_PORT")}
    if env["LIVE_TUNNEL_PROVIDER"] not in {"none", "ngrok", "cloudflared"}:
        raise ValueError("LIVE_TUNNEL_PROVIDER must be none, ngrok or cloudflared")
    if env["LIVE_TUNNEL_PROVIDER"] != "none":
        ports["public-relay"] = _port(env["LIVE_TUNNEL_PORT"], "LIVE_TUNNEL_PORT")
    if env.get("SELFHOST_MEDIA_ENABLED", "false") not in {"true", "false"}:
        raise ValueError("SELFHOST_MEDIA_ENABLED must be true or false")
    if env.get("SELFHOST_MEDIA_ENABLED") == "true":
        ports["media-body"] = _port(env["SELFHOST_MEDIA_PORT"], "SELFHOST_MEDIA_PORT")
        if len(env.get("SELFHOST_MEDIA_TOKEN", "")) < 24:
            raise ValueError("SELFHOST_MEDIA_TOKEN must be a random secret of at least 24 characters")
        if _local_endpoint(env["SELFHOST_MEDIA_URL"], "http", "SELFHOST_MEDIA_URL") != ports["media-body"]:
            raise ValueError("SELFHOST_MEDIA_URL must match SELFHOST_MEDIA_PORT")
    if len(set(ports.values())) != len(ports):
        raise ValueError("Service ports must be distinct")
    for key in ("RUNTIME_TIME_SCALE", "RUNTIME_LLM_TIMEOUT"):
        try:
            if not 0 < float(env[key]) < 86400:
                raise ValueError
        except ValueError:
            raise ValueError(f"{key} must be a positive finite number") from None
    if env["RUNTIME_SOCIAL"].lower() not in {"true", "false"}:
        raise ValueError("RUNTIME_SOCIAL must be true or false")
    return ports


def service_commands(env: dict[str, str], ports: dict[str, int], python: str) -> list[tuple[str, list[str]]]:
    commands = [
        ("ai-core", [python, "-m", "uvicorn", "ai_core.main:app", "--host", "127.0.0.1", "--port", str(ports["ai-core"])]),
        ("runtime", [python, "-m", "engine.server.server", "--host", "127.0.0.1", "--port", str(ports["runtime"]),
                     "--time-scale", env["RUNTIME_TIME_SCALE"], "--llm-timeout", env["RUNTIME_LLM_TIMEOUT"]]),
        ("gateway", [python, "-m", "uvicorn", "gateway.main:app", "--host", "127.0.0.1", "--port", str(ports["gateway"])]),
        ("studio", [python, "studio/server.py", "--host", "127.0.0.1", "--port", str(ports["studio"]),
                    "--runtime-url", env["CHARACTER_RUNTIME_URL"].rstrip("/")]),
    ]
    if env["RUNTIME_SOCIAL"].lower() == "true":
        commands[1][1].append("--social")
    if "media-body" in ports:
        commands.append(("media-body", ["bash", str(ROOT / "scripts/selfhost-up.sh")]))
    if env["LIVE_TUNNEL_PROVIDER"] != "none":
        commands.append(("public-relay", [python, "-m", "scripts.gateway_public", "--port", str(ports["public-relay"])]))
    return commands


def health(name: str, port: int) -> bool:
    # A CPU media process may run with GPU unavailable. Full GPU readiness is
    # exposed separately by its authenticated /health and the Studio page.
    path = "/api/status" if name == "studio" else "/livez" if name == "media-body" else "/health"
    try:
        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            data = json.load(response)
        if name == "studio":
            return bool(data.get("linked_runtime"))
        if name == "runtime":
            # Readiness is separate from provider success. A new provider may
            # remain unknown until a real conversation, without blocking boot.
            return data.get("ready") is True
        if name == "ai-core":
            return data.get("status") == "ok" and data.get("database") == "ok" and data.get("redis") == "ok"
        return data.get("status") == "ok"
    except (OSError, ValueError):
        return False


def assert_ports_free(ports: dict[str, int]) -> None:
    for name, port in ports.items():
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(f"{name}: port {port} is already occupied; no process was stopped") from None


def cloudflare_origin(log: str) -> str | None:
    matches = re.findall(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\b", log)
    return matches[-1] if matches else None


class LiveStack:
    def __init__(self, root: Path, env: dict[str, str], ports: dict[str, int]):
        self.root, self.env, self.ports = root, env, ports
        self.directory = root / "outputs" / "live-stack"
        self.children: list[tuple[str, subprocess.Popen]] = []
        self.logs = []
        self.lock = None
        self._owns_state = False

    def _acquire_lock(self) -> None:
        if self.lock is not None:
            raise RuntimeError("This live-stack supervisor already holds the lock")
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = (self.directory / "supervisor.lock").open("a")
        try:
            # Keep one persistent inode. The OS releases flock after a crash;
            # unlinking the file could let two supervisors lock different inodes.
            os.set_inheritable(lock.fileno(), False)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("A live-stack supervisor is already running; the lock file must not be deleted") from None
        except BaseException:
            lock.close()
            raise
        self.lock = lock

    def _release_lock(self) -> None:
        lock, self.lock = self.lock, None
        if lock is not None:
            lock.close()

    def _record(self) -> None:
        state = {"supervisor_pid": os.getpid(), "root": str(self.root),
                 "children": [{"service": name, "pid": proc.pid} for name, proc in self.children]}
        temporary = self.directory / "state.tmp"
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(self.directory / "state.json")
        self._owns_state = True

    def spawn(self, name: str, command: list[str]) -> subprocess.Popen:
        log = (self.directory / f"{name}.log").open("ab")
        self.logs.append(log)
        proc = subprocess.Popen(command, cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                close_fds=True)
        self.children.append((name, proc))
        self._record()
        return proc

    def wait_ready(self, name: str, proc: subprocess.Popen, timeout: float = 60) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"{name} exited before ready; inspect outputs/live-stack/{name}.log")
            if health(name, self.ports[name]):
                print(f"ready: {name} (PID {proc.pid}, port {self.ports[name]})", flush=True)
                return
            time.sleep(0.25)
        raise RuntimeError(f"{name} health timed out; inspect outputs/live-stack/{name}.log")

    def start(self) -> None:
        assert_ports_free(self.ports)
        self._acquire_lock()
        try:
            # Old metadata is diagnostic only, never permission to kill a PID
            # or evidence that the kernel lock is still held.
            self._record()
            self._start_services()
        except BaseException:
            self.close()
            raise

    def _start_services(self) -> None:
        for name, command in service_commands(self.env, self.ports, sys.executable):
            proc = self.spawn(name, command)
            self.wait_ready(name, proc)
        provider = self.env["LIVE_TUNNEL_PROVIDER"]
        if provider != "none":
            executable = shutil.which(provider)
            if not executable:
                raise RuntimeError(f"{provider} is not installed")
            target = f"http://127.0.0.1:{self.ports['public-relay']}"
            if provider == "ngrok":
                command = [executable, "http", target, "--log", "stdout"]
                if self.env.get("NGROK_DOMAIN"):
                    command += ["--domain", self.env["NGROK_DOMAIN"]]
            else:
                # cloudflared otherwise loads ~/.cloudflared/config.yml: an
                # unrelated named tunnel's ingress can override this --url.
                quick_config = self.directory / "cloudflared-quick.yml"
                quick_config.write_text("{}\n", encoding="utf-8")
                quick_config.chmod(0o600)
                command = [executable, "tunnel", "--config", str(quick_config),
                           "--url", target, "--no-autoupdate"]
            tunnel_log = self.directory / "tunnel.log"
            offset = tunnel_log.stat().st_size if tunnel_log.exists() else 0
            proc = self.spawn("tunnel", command)
            if provider == "cloudflared":
                deadline = time.monotonic() + 60
                origin = None
                while time.monotonic() < deadline and proc.poll() is None:
                    with tunnel_log.open() as current:
                        current.seek(offset)
                        origin = cloudflare_origin(current.read())
                    if origin:
                        break
                    time.sleep(0.25)
                if not origin:
                    raise RuntimeError("Cloudflare did not publish a tunnel URL; inspect tunnel.log")
                self.env["TAVUS_PUBLIC_BASE_URL"] = origin
                set_key(self.root / ".env", "TAVUS_PUBLIC_BASE_URL", origin, quote_mode="always")
                (self.root / ".env").chmod(0o600)
            if self.env.get("TAVUS_SYNC_ON_START", "false").lower() == "true":
                result = subprocess.run(
                    [sys.executable, str(self.root / "scripts/tavus_setup.py"), "sync"],
                    cwd=self.root, env=self.env, capture_output=True, text=True, timeout=150,
                )
                if result.returncode:
                    # Never echo provider bodies or credentials into launcher output.
                    raise RuntimeError("Tavus connection sync failed; local config retained for retry")
                print("Tavus connection synchronized to the authenticated public relay", flush=True)
            print("tunnel launched; public URL/readiness: outputs/live-stack/tunnel.log", flush=True)

    def close(self) -> None:
        # No state-file or port-derived PID is ever killed: only owned children.
        try:
            for _, proc in reversed(self.children):
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            for _, proc in reversed(self.children):
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
            for log in self.logs:
                log.close()
            if self._owns_state and self.lock is not None:
                (self.directory / "state.json").unlink(missing_ok=True)
            self._owns_state = False
            self.children.clear()
            self.logs.clear()
        finally:
            # Even cleanup failures must not strand an advisory lock in a
            # surviving caller. Never unlink supervisor.lock on any exit path.
            self._release_lock()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "check", "status"), nargs="?", default="up")
    parser.add_argument("--check", "--dry-run", action="store_true", help="Validate without starting anything")
    args = parser.parse_args(argv)
    try:
        env = load_environment(ROOT)
        ports = validate(env)
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    if args.command == "check" or args.check:
        print("Configuration valid; no services started.")
        print("Services: " + ", ".join(f"{name}:{port}" for name, port in ports.items()))
        print("Cognition and memory: ai-core; required credentials: configured (redacted)")
        print("Tunnel: " + env["LIVE_TUNNEL_PROVIDER"])
        return 0
    if args.command == "status":
        state = {name: "ready" if health(name, port) else "unavailable" for name, port in ports.items()}
        print(json.dumps(state, indent=2))
        return 0 if all(value == "ready" for value in state.values()) else 1
    stack = LiveStack(ROOT, env, ports)
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        stack.start()
        print(f"Live: http://127.0.0.1:{ports['studio']}/live | Joi: http://127.0.0.1:{ports['studio']}/joi", flush=True)
        print("Ctrl-C stops only processes started by this launcher.", flush=True)
        while True:
            for name, proc in stack.children:
                if proc.poll() is not None:
                    raise RuntimeError(f"{name} exited; stopping this stack")
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        stack.close()


if __name__ == "__main__":
    raise SystemExit(main())

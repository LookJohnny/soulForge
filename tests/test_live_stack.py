"""Launcher checks are offline; lifecycle tests use only owned fake processes."""

import errno
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import live_stack


def configured(tmp_path, **overrides):
    # Keep service topology explicit: individual tests opt into a tunnel/social
    # behavior rather than inheriting it from a file, parent shell or defaults.
    values = {
        "SOULFORGE_BRAND_ID": "bbbbbbbb-0000-4000-8000-000000000001",
        "SERVICE_TOKEN": "test-service-private",
        "GATEWAY_API_TOKEN": "test-gateway-private",
        "AI_CORE_URL": "http://127.0.0.1:8100",
        "SOULFORGE_COGNITION_URL": "http://127.0.0.1:8100",
        "SOULFORGE_MEMORY_BACKEND": "ai-core",
        "CHARACTER_RUNTIME_URL": "ws://127.0.0.1:8765",
        "CHARACTER_RUNTIME_AGENT": "joi",
        "GATEWAY_PORT": "8081",
        "STUDIO_PORT": "8899",
        "RUNTIME_TIME_SCALE": "2",
        "RUNTIME_LLM_TIMEOUT": "30",
        "RUNTIME_SOCIAL": "false",
        "LIVE_TUNNEL_PROVIDER": "none",
        "LIVE_TUNNEL_PORT": "8091",
        "TAVUS_SYNC_ON_START": "false",
    }
    values.update(overrides)
    return live_stack.load_environment(tmp_path, values)


def test_configured_fixture_isolated_from_enabled_tunnel_and_social_settings(
    tmp_path, monkeypatch
):
    for key, value in {
        "LIVE_TUNNEL_PROVIDER": "cloudflared",
        "TAVUS_SYNC_ON_START": "true",
        "RUNTIME_SOCIAL": "true",
        "GATEWAY_PORT": "9999",
    }.items():
        monkeypatch.setenv(key, value)
    (tmp_path / ".env").write_text(
        "LIVE_TUNNEL_PROVIDER=ngrok\nRUNTIME_SOCIAL=true\nTAVUS_SYNC_ON_START=true\n"
    )
    env = configured(tmp_path)
    assert env["LIVE_TUNNEL_PROVIDER"] == "none"
    assert env["RUNTIME_SOCIAL"] == env["TAVUS_SYNC_ON_START"] == "false"
    assert env["GATEWAY_PORT"] == "8081"
    commands = dict(
        live_stack.service_commands(env, live_stack.validate(env), "/python")
    )
    assert set(commands) == {"ai-core", "runtime", "gateway", "studio"}
    assert "--social" not in commands["runtime"]


def test_root_env_is_data_and_explicit_test_overrides_win(tmp_path):
    (tmp_path / ".env").write_text("GATEWAY_PORT=8090\nVALUE='$(touch never-run)'\n")
    env = configured(tmp_path, GATEWAY_PORT="8092")
    assert env["GATEWAY_PORT"] == "8092"
    assert env["VALUE"] == "$(touch never-run)"
    assert not (tmp_path / "never-run").exists()
    assert env["GATEWAY_WS_URL"] == "ws://127.0.0.1:8092/ws"


def test_ordinary_launch_prefers_root_env_to_stale_shell_exports(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "GATEWAY_PORT=8090\nTAVUS_PUBLIC_BASE_URL=https://current.example\n"
    )
    monkeypatch.setenv("GATEWAY_PORT", "8089")
    monkeypatch.setenv("TAVUS_PUBLIC_BASE_URL", "https://stale.example")
    monkeypatch.setenv("SHELL_ONLY_SETTING", "preserved")
    env = live_stack.load_environment(tmp_path)
    assert env["GATEWAY_PORT"] == "8090"
    assert env["GATEWAY_WS_URL"] == "ws://127.0.0.1:8090/ws"
    assert env["TAVUS_PUBLIC_BASE_URL"] == "https://current.example"
    assert env["SHELL_ONLY_SETTING"] == "preserved"


@pytest.mark.parametrize(
    "key,value",
    [
        ("GATEWAY_API_TOKEN", ""),
        ("SERVICE_TOKEN", "change-me"),
        ("SOULFORGE_BRAND_ID", ""),
        ("SOULFORGE_MEMORY_BACKEND", "memory"),
        ("CHARACTER_RUNTIME_URL", "ws://remote.example:8765"),
        ("SOULFORGE_COGNITION_URL", "http://other.example"),
        ("GATEWAY_PORT", "8100"),
    ],
)
def test_invalid_live_config_fails_closed(tmp_path, key, value):
    with pytest.raises(ValueError):
        live_stack.validate(configured(tmp_path, **{key: value}))


def test_commands_connect_four_services_to_one_runtime(tmp_path):
    env = configured(tmp_path)
    commands = dict(
        live_stack.service_commands(env, live_stack.validate(env), "/python")
    )
    assert set(commands) == {"ai-core", "runtime", "gateway", "studio"}
    assert commands["studio"][-2:] == ["--runtime-url", env["CHARACTER_RUNTIME_URL"]]
    assert "--mock-llm" not in commands["runtime"]
    assert "--social" not in commands["runtime"]


def test_check_does_not_spawn_or_write_and_redacts(tmp_path, monkeypatch, capsys):
    env = configured(
        tmp_path, LIVE_TUNNEL_PROVIDER="cloudflared", TAVUS_SYNC_ON_START="true"
    )
    monkeypatch.setattr(live_stack, "ROOT", tmp_path)
    monkeypatch.setattr(live_stack, "load_environment", lambda _: env)
    monkeypatch.setattr(
        live_stack.subprocess,
        "Popen",
        Mock(side_effect=AssertionError("must not spawn")),
    )
    monkeypatch.setattr(
        live_stack.subprocess, "run", Mock(side_effect=AssertionError("must not sync"))
    )
    assert live_stack.main(["--check"]) == 0
    output = capsys.readouterr().out
    assert "test-service-private" not in output and "test-gateway-private" not in output
    assert not (tmp_path / "outputs").exists()
    assert not (tmp_path / ".env").exists()


def test_occupied_port_does_not_kill_anyone(tmp_path, monkeypatch):
    env = configured(tmp_path)
    stack = live_stack.LiveStack(tmp_path, env, live_stack.validate(env))
    monkeypatch.setattr(
        live_stack, "assert_ports_free", Mock(side_effect=RuntimeError("occupied"))
    )
    kill = Mock()
    monkeypatch.setattr(live_stack.os, "killpg", kill)
    with pytest.raises(RuntimeError, match="occupied"):
        stack.start()
    stack.close()
    kill.assert_not_called()
    assert not (tmp_path / "outputs").exists()


def test_cleanup_only_current_children_never_stale_registry(tmp_path, monkeypatch):
    env = configured(tmp_path)
    stack = live_stack.LiveStack(tmp_path, env, live_stack.validate(env))
    stack.directory.mkdir(parents=True)
    (stack.directory / "state.json").write_text('{"children":[{"pid":999999}]}')
    alive = SimpleNamespace(pid=101, poll=lambda: None, wait=Mock())
    exited = SimpleNamespace(pid=102, poll=lambda: 0, wait=Mock())
    stack.children = [("owned", alive), ("already-exited", exited)]
    kill = Mock()
    monkeypatch.setattr(live_stack.os, "killpg", kill)
    stack.close()
    kill.assert_called_once_with(101, live_stack.signal.SIGTERM)


def test_tunnel_uses_allowlisted_relay_not_gateway(tmp_path):
    env = configured(tmp_path, LIVE_TUNNEL_PROVIDER="ngrok")
    commands = dict(
        live_stack.service_commands(env, live_stack.validate(env), "/python")
    )
    assert commands["public-relay"] == [
        "/python",
        "-m",
        "scripts.gateway_public",
        "--port",
        "8091",
    ]


@pytest.mark.parametrize("active_listener", [False, True])
def test_port_probe_reuses_time_wait_but_still_rejects_active_listener(
    monkeypatch, active_listener
):
    class FakePort:
        reuse_address = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def setsockopt(self, level, option, value):
            self.reuse_address = (level, option, value) == (
                live_stack.socket.SOL_SOCKET,
                live_stack.socket.SO_REUSEADDR,
                1,
            )

        def bind(self, address):
            assert address == ("127.0.0.1", 8081)
            if active_listener or not self.reuse_address:
                raise OSError(errno.EADDRINUSE, "address already in use")

    port = FakePort()
    monkeypatch.setattr(live_stack.socket, "socket", lambda: port)
    if active_listener:
        with pytest.raises(
            RuntimeError, match="already occupied; no process was stopped"
        ):
            live_stack.assert_ports_free({"gateway": 8081})
    else:
        live_stack.assert_ports_free({"gateway": 8081})
    assert port.reuse_address


@pytest.mark.parametrize(
    "log,expected",
    [
        ("", None),
        ("https://dash.cloudflare.com is not the public origin", None),
        ("http://only-http.trycloudflare.com", None),
        (
            "INF | https://gentle-river-12.trycloudflare.com |",
            "https://gentle-river-12.trycloudflare.com",
        ),
        (
            "https://old-link.trycloudflare.com\nhttps://new-link.trycloudflare.com\n",
            "https://new-link.trycloudflare.com",
        ),
    ],
)
def test_cloudflare_origin_extracts_latest_quick_tunnel_url(log, expected):
    assert live_stack.cloudflare_origin(log) == expected


@pytest.mark.parametrize(
    "sync_enabled,sync_status", [(False, 0), (True, 0), (True, 409)]
)
def test_cloudflare_launch_persists_only_new_origin_and_optionally_syncs_existing_pal(
    tmp_path,
    monkeypatch,
    capsys,
    sync_enabled,
    sync_status,
):
    env_file = tmp_path / ".env"
    env_file.write_text("TAVUS_PUBLIC_BASE_URL=https://stale.example\nUNCHANGED=kept\n")
    env = configured(
        tmp_path,
        LIVE_TUNNEL_PROVIDER="cloudflared",
        TAVUS_SYNC_ON_START=str(sync_enabled).lower(),
        TAVUS_PAL_ID="existing-pal",
    )
    stack = live_stack.LiveStack(tmp_path, env, live_stack.validate(env))
    stack.directory.mkdir(parents=True)
    log = stack.directory / "tunnel.log"
    log.write_text("https://previous-run.trycloudflare.com\n")
    monkeypatch.setattr(live_stack, "assert_ports_free", Mock())
    monkeypatch.setattr(live_stack, "service_commands", lambda *_args: [])
    monkeypatch.setattr(live_stack.shutil, "which", lambda _name: "/fake/cloudflared")
    commands = []

    def fake_spawn(name, command):
        commands.append((name, command))
        with log.open("a") as output:
            output.write("INF | https://current-run.trycloudflare.com |\n")
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(stack, "spawn", fake_spawn)
    sync = Mock(
        return_value=SimpleNamespace(
            returncode=sync_status, stdout="private-token", stderr="private-token"
        )
    )
    monkeypatch.setattr(live_stack.subprocess, "run", sync)
    try:
        if sync_status:
            with pytest.raises(
                RuntimeError, match="sync failed; local config retained"
            ):
                stack.start()
        else:
            stack.start()
        quick_config = stack.directory / "cloudflared-quick.yml"
        assert commands == [
            (
                "tunnel",
                [
                    "/fake/cloudflared",
                    "tunnel",
                    "--config",
                    str(quick_config),
                    "--url",
                    "http://127.0.0.1:8091",
                    "--no-autoupdate",
                ],
            )
        ]
        # An explicit, empty task config prevents a user's named-tunnel ingress
        # (including catch-all http_status:404) from overriding the relay URL.
        assert quick_config.read_text() == "{}\n"
        assert quick_config.stat().st_mode & 0o777 == 0o600
        saved = live_stack.dotenv_values(env_file)
        assert saved["TAVUS_PUBLIC_BASE_URL"] == "https://current-run.trycloudflare.com"
        assert saved["UNCHANGED"] == "kept"
        assert env_file.stat().st_mode & 0o777 == 0o600
        if sync_enabled:
            sync.assert_called_once()
            assert sync.call_args.args[0] == [
                live_stack.sys.executable,
                str(tmp_path / "scripts/tavus_setup.py"),
                "sync",
            ]
            assert sync.call_args.kwargs["env"]["TAVUS_PAL_ID"] == "existing-pal"
            assert (
                sync.call_args.kwargs["env"]["TAVUS_PUBLIC_BASE_URL"]
                == saved["TAVUS_PUBLIC_BASE_URL"]
            )
        else:
            sync.assert_not_called()
        assert "private-token" not in capsys.readouterr().out
    finally:
        stack.close()


def test_cloudflare_launch_never_reuses_origin_from_previous_log(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TAVUS_PUBLIC_BASE_URL=https://configured.example\n")
    original = env_file.read_bytes()
    env = configured(
        tmp_path, LIVE_TUNNEL_PROVIDER="cloudflared", TAVUS_SYNC_ON_START="true"
    )
    stack = live_stack.LiveStack(tmp_path, env, live_stack.validate(env))
    stack.directory.mkdir(parents=True)
    (stack.directory / "tunnel.log").write_text(
        "https://previous-run.trycloudflare.com\n"
    )
    monkeypatch.setattr(live_stack, "assert_ports_free", Mock())
    monkeypatch.setattr(live_stack, "service_commands", lambda *_args: [])
    monkeypatch.setattr(live_stack.shutil, "which", lambda _name: "/fake/cloudflared")
    monkeypatch.setattr(
        stack, "spawn", lambda *_args: SimpleNamespace(poll=lambda: None)
    )
    clock = iter([0, 0, 61])
    monkeypatch.setattr(live_stack.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(live_stack.time, "sleep", lambda _duration: None)
    sync = Mock(side_effect=AssertionError("must not sync a stale origin"))
    monkeypatch.setattr(live_stack.subprocess, "run", sync)
    try:
        with pytest.raises(RuntimeError, match="did not publish a tunnel URL"):
            stack.start()
        assert env_file.read_bytes() == original
        sync.assert_not_called()
    finally:
        stack.close()


def test_optional_media_body_has_isolated_python_and_local_port(tmp_path):
    env = configured(
        tmp_path,
        SELFHOST_MEDIA_ENABLED="true",
        SELFHOST_MEDIA_TOKEN="test-media-private-000000000000",
    )
    ports = live_stack.validate(env)
    assert ports["media-body"] == 8902
    commands = dict(live_stack.service_commands(env, ports, "/python"))
    assert commands["media-body"] == [
        "bash",
        str(live_stack.ROOT / "scripts/selfhost-up.sh"),
    ]
    assert env["SELFHOST_MEDIA_URL"] == "http://127.0.0.1:8902"


@pytest.mark.parametrize(
    "overrides",
    [
        {"SELFHOST_MEDIA_TOKEN": ""},
        {"SELFHOST_MEDIA_PORT": "8081"},
        {"SELFHOST_MEDIA_URL": "http://remote.example:8902"},
        {"SELFHOST_MEDIA_ENABLED": "yes"},
    ],
)
def test_optional_media_body_rejects_bad_configuration(tmp_path, overrides):
    values = {
        "SELFHOST_MEDIA_ENABLED": "true",
        "SELFHOST_MEDIA_TOKEN": "test-media-private-000000000000",
        **overrides,
    }
    with pytest.raises(ValueError):
        live_stack.validate(configured(tmp_path, **values))

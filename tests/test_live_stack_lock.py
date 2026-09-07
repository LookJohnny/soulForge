"""Kernel-lock lifecycle tests with owned, temporary Python processes only.

No configured services, ports, tunnels, API calls or repository output files.
"""

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import live_stack


_HOLDER = """
import os
from pathlib import Path
import sys
from scripts import live_stack

root = Path(sys.argv[1])
mode = sys.argv[2]
# This process exercises start/close, but never builds any service command.
live_stack.service_commands = lambda *args: []
stack = live_stack.LiveStack(root, {"LIVE_TUNNEL_PROVIDER": "none"}, {})
try:
    stack.start()
except RuntimeError:
    print("BLOCKED", flush=True)
    raise SystemExit(23)
print("LOCKED", flush=True)
if mode == "crash":
    os._exit(17)
sys.stdin.read(1)
stack.close()
"""


@pytest.fixture
def holder_process():
    owned = []

    def start(root: Path, mode: str = "hold"):
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", _HOLDER, str(root), mode],
            cwd=live_stack.ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        owned.append(proc)
        with selectors.DefaultSelector() as ready:
            ready.register(proc.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=5), "temporary lock holder did not respond"
        message = proc.stdout.readline().strip()
        assert message in {"LOCKED", "BLOCKED"}, (
            "temporary lock holder failed before acquiring"
        )
        return proc, message

    yield start
    for proc in owned:
        if proc.poll() is None:
            proc.kill()  # Only a Popen created by this fixture, never a metadata PID.
        proc.communicate(timeout=5)


def paths(root):
    directory = root / "outputs" / "live-stack"
    return directory / "supervisor.lock", directory / "state.json"


@pytest.mark.parametrize("exit_mode", ["crash", "sigkill"])
def test_crash_releases_kernel_lock_and_reuses_file_without_manual_deletion(
    tmp_path,
    holder_process,
    exit_mode,
):
    first, status = holder_process(
        tmp_path, "crash" if exit_mode == "crash" else "hold"
    )
    assert status == "LOCKED"
    lock, metadata = paths(tmp_path)
    original_inode = lock.stat().st_ino
    if exit_mode == "sigkill":
        first.kill()
    first.wait(timeout=5)
    assert first.returncode == (17 if exit_mode == "crash" else -9)
    assert json.loads(metadata.read_text())["supervisor_pid"] == first.pid
    assert lock.exists(), "a persistent lock file is normal after a crash"

    second, status = holder_process(tmp_path)
    assert status == "LOCKED"
    assert lock.stat().st_ino == original_inode
    assert json.loads(metadata.read_text())["supervisor_pid"] == second.pid
    second.communicate(input="x", timeout=5)
    assert second.returncode == 0
    assert not metadata.exists()
    assert lock.exists() and lock.stat().st_ino == original_inode


def test_active_supervisor_refuses_second_start_even_if_pid_metadata_is_missing(
    tmp_path, holder_process
):
    first, status = holder_process(tmp_path)
    assert status == "LOCKED"
    lock, metadata = paths(tmp_path)
    inode = lock.stat().st_ino
    metadata.unlink()  # This is test-owned temporary metadata, not the real stack.
    second, status = holder_process(tmp_path)
    assert status == "BLOCKED"
    second.wait(timeout=5)
    assert second.returncode == 23
    assert first.poll() is None
    assert lock.exists() and lock.stat().st_ino == inode
    assert not metadata.exists(), "a rejected contender cannot write owner state"
    first.communicate(input="x", timeout=5)

    third, status = holder_process(tmp_path)
    assert status == "LOCKED"
    third.communicate(input="x", timeout=5)
    assert not metadata.exists() and lock.stat().st_ino == inode


@pytest.mark.parametrize(
    "stale_metadata", ["not valid JSON", '{"supervisor_pid":1,"children":[{"pid":1}]}']
)
def test_stale_metadata_and_lock_file_contents_do_not_authorize_or_block_start(
    tmp_path,
    holder_process,
    stale_metadata,
):
    lock, metadata = paths(tmp_path)
    lock.parent.mkdir(parents=True)
    lock.write_text("stale PID data is not a lock\n")
    metadata.write_text(stale_metadata)
    inode = lock.stat().st_ino
    proc, status = holder_process(tmp_path)
    assert status == "LOCKED"
    assert json.loads(metadata.read_text())["supervisor_pid"] == proc.pid
    proc.communicate(input="x", timeout=5)
    assert proc.returncode == 0
    assert not metadata.exists()
    assert lock.stat().st_ino == inode


def test_child_exec_cannot_inherit_the_supervisors_lock(tmp_path):
    stack = live_stack.LiveStack(tmp_path, {}, {})
    stack._acquire_lock()
    lock, _ = paths(tmp_path)
    descriptor = stack.lock.fileno()
    assert os.get_inheritable(descriptor) is False
    code = """
import os
from pathlib import Path
import sys
try:
    fd_stat = os.fstat(int(sys.argv[1]))
except OSError:
    raise SystemExit(0)
lock_stat = Path(sys.argv[2]).stat()
assert (fd_stat.st_dev, fd_stat.st_ino) != (lock_stat.st_dev, lock_stat.st_ino), 'inherited lock'
"""
    try:
        child = stack.spawn(
            "fake-fd-check", [sys.executable, "-c", code, str(descriptor), str(lock)]
        )
        assert child.wait(timeout=5) == 0
    finally:
        stack.close()
    assert lock.exists()


def test_start_failure_releases_lock_and_close_is_safe_after_a_new_owner_starts(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        live_stack,
        "service_commands",
        Mock(side_effect=RuntimeError("fake startup failure")),
    )
    failed = live_stack.LiveStack(tmp_path, {"LIVE_TUNNEL_PROVIDER": "none"}, {})
    with pytest.raises(RuntimeError, match="fake startup failure"):
        failed.start()
    assert failed.lock is None
    lock, metadata = paths(tmp_path)
    inode = lock.stat().st_ino
    assert not metadata.exists()

    successor = live_stack.LiveStack(tmp_path, {}, {})
    successor._acquire_lock()
    successor._record()
    try:
        recorded = metadata.read_bytes()
        failed.close()  # A main() finally block may close it a second time.
        assert metadata.read_bytes() == recorded
        assert lock.stat().st_ino == inode
    finally:
        successor.close()


def test_cleanup_exception_still_releases_advisory_lock(tmp_path):
    failed = live_stack.LiveStack(tmp_path, {}, {})
    failed._acquire_lock()
    failed._record()
    child = SimpleNamespace(
        poll=lambda: 0, wait=Mock(side_effect=RuntimeError("fake wait failure"))
    )
    failed.children = [("owned-fake", child)]
    with pytest.raises(RuntimeError, match="fake wait failure"):
        failed.close()
    assert failed.lock is None
    successor = live_stack.LiveStack(tmp_path, {}, {})
    try:
        successor._acquire_lock()
        successor._record()
        _, metadata = paths(tmp_path)
        current_state = metadata.read_bytes()
        child.wait = Mock()
        failed.close()
        assert metadata.read_bytes() == current_state
    finally:
        successor.close()

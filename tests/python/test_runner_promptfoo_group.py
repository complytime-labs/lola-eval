"""runner._run_promptfoo kills the whole process group on timeout, so
orphaned agent/judge grandchildren are cleaned up (not just promptfoo)."""

from __future__ import annotations

import os
import time

from lola_eval import runner


def _is_dead(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return False
    except (ProcessLookupError, PermissionError):
        return True


def test_run_promptfoo_kills_grandchildren_on_timeout(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    # bash spawns a long-sleeping grandchild (records its PID), then sleeps
    # itself. On timeout the whole group must be killed, grandchild included.
    script = f"sleep 60 & echo $! > {pidfile}; sleep 60"
    rc, timed_out = runner._run_promptfoo(["bash", "-c", script], dict(os.environ), 1)

    assert timed_out is True
    assert rc is None
    assert pidfile.exists(), "grandchild should have recorded its PID before timeout"
    gc = int(pidfile.read_text().strip())

    deadline = time.time() + 3
    while time.time() < deadline and not _is_dead(gc):
        time.sleep(0.05)
    assert _is_dead(gc), f"grandchild {gc} survived the process-group kill"


def test_run_promptfoo_returns_rc_on_normal_exit(tmp_path):
    rc, timed_out = runner._run_promptfoo(["bash", "-c", "exit 3"], dict(os.environ), 10)
    assert timed_out is False
    assert rc == 3

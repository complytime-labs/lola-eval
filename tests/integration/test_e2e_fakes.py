"""End-to-end CLI smoke against bash-fake CLIs.

Exercises the read-side commands against an empty SQLite, verifying
the harness boots and ``lola-eval drift`` does not crash on a clean
state. The Phase-1 ``test_full_pipeline_persists_a_row`` test that
exercised ``lola-eval gen`` + ``npx promptfoo eval`` end-to-end was
removed alongside the ``gen`` subcommand: the ``lola-eval test`` flow
is covered by ``tests/integration/test_lola_eval_test.py`` against a
stub provider, and the orchestrator-level wiring is covered by the
unit tests under ``tests/python/``.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def hermetic_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    state.mkdir()
    cache.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv(
        "PATH",
        f"{REPO}/tests/fixtures/fake-claude:{REPO}/tests/fixtures/fake-opencode:{os.environ['PATH']}",
    )
    return tmp_path


@pytest.mark.integration
def test_drift_command_runs_against_empty_db(hermetic_env):
    """`lola-eval drift` on a clean state should not crash."""
    rc = subprocess.run(
        [sys.executable, "-m", "lola_eval", "drift"],
        cwd=hermetic_env,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, (
        f"drift command failed:\nstdout: {rc.stdout}\nstderr: {rc.stderr}"
    )

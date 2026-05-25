"""`check_invariants.check` must flag a missing expected profile."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from lola_eval import store

_SPEC = importlib.util.spec_from_file_location(
    "check_invariants",
    Path(__file__).resolve().parents[2] / "tests" / "live" / "check_invariants.py",
)
check_invariants = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_invariants)


def _seed(db: Path, profile_id: str) -> None:
    store.insert_run(db, {
        "run_id": f"r-{profile_id}",
        "timestamp": "2026-05-25T00:00:00Z",
        "fingerprint": f"fp-{profile_id}",
        "target_cli": "claude-code",
        "target_model": "haiku",
        "target_cli_ver": "1",
        "pack_id": "project",
        "profile_id": profile_id,
        "task_id": "case-greeting",
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "headless",
        "invocation": "passive",
        "judge_cli": "claude-code",
        "judge_model": "sonnet",
        "scores_json": json.dumps({"composite": 0.8}),
        "transcript_path": "/dev/null",
        "exit_status": "success",
        "git_sha": "abc1234",
        "fingerprint_version": "2",
        "target_model_resolved": "claude-haiku-4-5-20251001",
    })


def test_missing_expected_profile_fails(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    _seed(db, "none")
    _seed(db, "greet")
    rc = check_invariants.check(db, expected_profiles={"none", "greet", "greet-salute"})
    assert rc == 1


def test_all_expected_profiles_present_passes(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    _seed(db, "none")
    _seed(db, "greet")
    rc = check_invariants.check(db, expected_profiles={"none", "greet"})
    assert rc == 0

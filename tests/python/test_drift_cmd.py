"""`lola-eval drift` CLI smoke test.

Verifies the command resolves the Layout and routes LOLA_RESULTS_DIR to
layout.out_root so resolve_db_path() can find the database.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from lola_eval import store
from lola_eval.cli import app


def _seed_target(tmp_path):
    """Scaffold a minimal .lola-eval/ tree with one run in runs.db."""
    lola_dir = tmp_path / ".lola-eval"
    lola_dir.mkdir()
    (lola_dir / "config.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    out = lola_dir / "out"
    out.mkdir()
    db = out / "runs.db"
    store.init_db(db)
    store.insert_run(db, {
        "run_id": "r1",
        "timestamp": "2026-05-25T10:00:00Z",
        "fingerprint": "a" * 64,
        "target_cli": "claude-code",
        "target_model": "sonnet",
        "target_cli_ver": "1",
        "pack_id": "project",
        "task_id": "case-fix-bug",
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "autonomous",
        "invocation": "passive",
        "judge_cli": "claude-code",
        "judge_model": "sonnet",
        "scores_json": json.dumps({"composite": 0.85}),
        "transcript_path": "/tmp/t.jsonl",
        "exit_status": "success",
    })
    return tmp_path


def test_drift_reads_from_layout_out_root(tmp_path, monkeypatch):
    """drift command exits 0 and prints a fingerprint row from runs.db
    resolved via Layout.out_root (not an XDG fallback)."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)
    cfg = target / ".lola-eval" / "config.yaml"

    res = CliRunner().invoke(app, ["drift", "--config", str(cfg)])
    assert res.exit_code == 0, res.output
    assert "fingerprint" in res.output.lower()


def test_drift_tolerates_missing_config(tmp_path, monkeypatch):
    """No .lola-eval/config.yaml: drift runs in standalone XDG mode rather
    than failing setup. With an empty XDG runs.db it returns 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    res = CliRunner().invoke(app, ["drift"])
    assert res.exit_code == 0, res.output
    assert "setup error" not in res.output.lower()

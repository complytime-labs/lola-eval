"""`lola-eval transcript-diff` CLI."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from lola_eval import store
from lola_eval.cli import app


def _seed(tmp_path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    common = {
        "target_cli": "claude-code", "target_model": "sonnet", "target_cli_ver": "2.1",
        "pack_id": "project", "task_id": "case-001", "task_version": "1",
        "rubric_version": "1", "exec_mode": "autonomous", "invocation": "passive",
        "judge_cli": "claude-code", "judge_model": "sonnet",
        "transcript_path": "/tmp/t.jsonl", "exit_status": "success",
    }
    store.insert_run(db, {**common, "run_id": "AAA", "timestamp": "2026-05-20T00:00:00Z",
                          "fingerprint": "fp1",
                          "scores_json": json.dumps({"composite": 0.80, "components": {"correctness": 0.9}})})
    store.insert_run(db, {**common, "run_id": "BBB", "timestamp": "2026-05-21T00:00:00Z",
                          "fingerprint": "fp1",
                          "scores_json": json.dumps({"composite": 0.92, "components": {"correctness": 0.95}})})
    return db


def _cfg(tmp_path):
    (tmp_path / "lola-eval.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    return tmp_path / "lola-eval.yaml"


def test_transcript_diff_renders_deltas(tmp_path):
    _seed(tmp_path)
    cfg = _cfg(tmp_path)
    res = CliRunner().invoke(app, ["transcript-diff", "AAA", "BBB", "--config", str(cfg)])
    assert res.exit_code == 0
    assert "composite" in res.output
    assert "+0.12" in res.output


def test_transcript_diff_missing_run_errors(tmp_path):
    _seed(tmp_path)
    cfg = _cfg(tmp_path)
    res = CliRunner().invoke(app, ["transcript-diff", "AAA", "NOPE", "--config", str(cfg)])
    assert res.exit_code == 1
    assert "NOPE" in res.output

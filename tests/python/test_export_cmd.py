"""`lola-eval export` CLI."""
from __future__ import annotations

import csv
import io
import json

from typer.testing import CliRunner

from lola_eval import store
from lola_eval.cli import app


def _seed(tmp_path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, {
        "run_id": "r1", "timestamp": "2026-05-20T00:00:00Z", "fingerprint": "fp1",
        "target_cli": "claude-code", "target_model": "sonnet", "target_cli_ver": "2.1",
        "pack_id": "project", "task_id": "case-001", "task_version": "1",
        "rubric_version": "1", "exec_mode": "autonomous", "invocation": "passive",
        "judge_cli": "claude-code", "judge_model": "sonnet",
        "scores_json": json.dumps({"composite": 0.8}),
        "transcript_path": "/tmp/t.jsonl", "exit_status": "success",
        "workdir_diff": "HUGE",
    })
    return db


def _cfg(tmp_path):
    (tmp_path / "lola-eval.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    return tmp_path / "lola-eval.yaml"


def test_export_json_excludes_heavy_columns(tmp_path):
    _seed(tmp_path)
    cfg = _cfg(tmp_path)
    out = tmp_path / "out.json"
    res = CliRunner().invoke(app, ["export", "--config", str(cfg), "--out", str(out)])
    assert res.exit_code == 0
    data = json.loads(out.read_text())
    assert data[0]["run_id"] == "r1"
    assert "workdir_diff" not in data[0]
    assert "transcript_path" not in data[0]


def test_export_csv_format(tmp_path):
    _seed(tmp_path)
    cfg = _cfg(tmp_path)
    out = tmp_path / "out.csv"
    res = CliRunner().invoke(app, ["export", "--config", str(cfg), "--format", "csv", "--out", str(out)])
    assert res.exit_code == 0
    reader = list(csv.DictReader(io.StringIO(out.read_text())))
    assert reader[0]["run_id"] == "r1"


def test_export_empty_is_graceful(tmp_path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    cfg = _cfg(tmp_path)
    res = CliRunner().invoke(app, ["export", "--config", str(cfg), "--task", "nope"])
    assert res.exit_code == 0
    assert "no runs" in res.output.lower()

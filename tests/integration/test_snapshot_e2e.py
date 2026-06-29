"""End-to-end: seed history, snapshot, verify idempotency and incremental capture."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lola_eval.cli import app
from lola_eval.store import init_db, insert_run


def _row(run_id: str, ts: str, task_id: str) -> dict:
    return {
        "run_id": run_id,
        "timestamp": ts,
        "fingerprint": f"fp-{run_id}",
        "target_cli": "claude-code",
        "target_model": "sonnet",
        "target_cli_ver": "2.1",
        "pack_id": "project",
        "task_id": task_id,
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "autonomous",
        "invocation": "passive",
        "judge_cli": "claude-code",
        "judge_model": "sonnet",
        "scores_json": json.dumps(
            {"composite": 0.9, "components": {"correctness": 0.9}, "explanation": "solid"}
        ),
        "transcript_path": "/tmp/t.jsonl",
        "exit_status": "success",
        "cost_usd": 1.0,
        "duration_s": 60.0,
        "input_tokens": 1000,
        "output_tokens": 200,
        "git_sha": "b" * 40,
        "git_branch": "main",
        "git_author": "Eval Bot",
        "git_dirty": 0,
        "task_description": "Synthetic case.",
        "rubric_pass_threshold": 0.6,
    }


def _target(tmp_path) -> Path:
    eval_dir = tmp_path / ".lola-eval"
    eval_dir.mkdir()
    (eval_dir / "config.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [claude-sonnet-4-6]\n"
    )
    db = eval_dir / "out" / "runs.db"
    db.parent.mkdir(parents=True)
    init_db(db)
    return eval_dir


def test_snapshot_full_lifecycle(tmp_path, monkeypatch):
    eval_dir = _target(tmp_path)
    db = eval_dir / "out" / "runs.db"
    insert_run(db, _row("r1", "2026-07-01T00:00:00Z", "case-001"))
    insert_run(db, _row("r2", "2026-07-01T01:00:00Z", "case-002"))
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    # First snapshot captures both runs.
    res = runner.invoke(app, ["snapshot"])
    assert res.exit_code == 0, res.output
    ledger = eval_dir / "ledger.jsonl"
    assert len(ledger.read_text().splitlines()) == 2
    snaps = sorted((eval_dir / "snapshots").glob("*.md"))
    assert len(snaps) == 1
    md = snaps[0].read_text()
    assert "case-001" in md and "case-002" in md
    assert "Total (2 cells)" in md

    # Re-run: idempotent, no new files.
    res = runner.invoke(app, ["snapshot"])
    assert res.exit_code == 0, res.output
    assert "nothing to snapshot" in res.output
    assert len(ledger.read_text().splitlines()) == 2
    assert len(list((eval_dir / "snapshots").glob("*.md"))) == 1

    # A third run lands; only it is captured, in a second snapshot file.
    insert_run(db, _row("r3", "2026-07-02T00:00:00Z", "case-003"))
    res = runner.invoke(app, ["snapshot"])
    assert res.exit_code == 0, res.output
    lines = [json.loads(ln) for ln in ledger.read_text().splitlines()]
    assert len(lines) == 3
    assert lines[2]["run_id"] == "r3"
    assert lines[2]["snapshot_id"] != lines[0]["snapshot_id"]
    assert len(list((eval_dir / "snapshots").glob("*.md"))) == 2
    # Each snapshot file covers exactly its own append, named by snapshot_id.
    md2 = (eval_dir / "snapshots" / f"{lines[2]['snapshot_id']}.md").read_text()
    assert "case-003" in md2 and "case-001" not in md2


def test_snapshot_migrated_legacy_ledger_preserved(tmp_path, monkeypatch):
    """A snapshot.sh-era ledger (no run_id) survives untouched; native rows
    append after it."""
    eval_dir = _target(tmp_path)
    db = eval_dir / "out" / "runs.db"
    insert_run(db, _row("r1", "2026-07-01T00:00:00Z", "case-001"))
    legacy = json.dumps({"snapshot_id": "20260520T221435Z", "task_id": "case-000"})
    (eval_dir / "ledger.jsonl").write_text(legacy + "\n")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    res = runner.invoke(app, ["snapshot"])

    assert res.exit_code == 0, res.output
    lines = (eval_dir / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert lines[0] == legacy  # untouched
    assert json.loads(lines[1])["run_id"] == "r1"

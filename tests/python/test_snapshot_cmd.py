"""`lola-eval snapshot` CLI."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from lola_eval import store
from lola_eval.cli import app


def _seed_target(tmp_path):
    """A minimal target repo: config.yaml + a seeded runs.db in out/."""
    eval_dir = tmp_path / ".lola-eval"
    eval_dir.mkdir()
    (eval_dir / "config.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [claude-sonnet-4-6]\n"
    )
    db = eval_dir / "out" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(
        db,
        {
            "run_id": "r1",
            "timestamp": "2026-07-01T00:00:00Z",
            "fingerprint": "fp1",
            "target_cli": "claude-code",
            "target_model": "sonnet",
            "target_cli_ver": "2.1",
            "pack_id": "project",
            "task_id": "case-001",
            "task_version": "1",
            "rubric_version": "1",
            "exec_mode": "autonomous",
            "invocation": "passive",
            "judge_cli": "claude-code",
            "judge_model": "sonnet",
            "scores_json": json.dumps({"composite": 0.8, "components": {}, "explanation": "ok"}),
            "transcript_path": "/tmp/t.jsonl",
            "exit_status": "success",
        },
    )
    return eval_dir


def test_snapshot_appends_and_reports(tmp_path, monkeypatch):
    eval_dir = _seed_target(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot"])

    assert result.exit_code == 0, result.output
    assert "appended 1 cell(s)" in result.output
    assert (eval_dir / "ledger.jsonl").exists()
    assert len(list((eval_dir / "snapshots").glob("*.md"))) == 1


def test_snapshot_second_run_is_noop(tmp_path, monkeypatch):
    eval_dir = _seed_target(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["snapshot"])

    result = runner.invoke(app, ["snapshot"])

    assert result.exit_code == 0, result.output
    assert "nothing to snapshot" in result.output
    assert len((eval_dir / "ledger.jsonl").read_text().splitlines()) == 1


def test_snapshot_dry_run_writes_nothing(tmp_path, monkeypatch):
    eval_dir = _seed_target(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would append 1 cell(s)" in result.output
    assert "r1" in result.output
    assert not (eval_dir / "ledger.jsonl").exists()


def test_snapshot_out_flag_overrides_ledger_dir(tmp_path, monkeypatch):
    _seed_target(tmp_path)
    monkeypatch.chdir(tmp_path)
    other = tmp_path / "history"
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot", "--out", str(other)])

    assert result.exit_code == 0, result.output
    assert (other / "ledger.jsonl").exists()
    # The markdown snapshot relocates with the ledger, not split across dirs.
    assert len(list((other / "snapshots").glob("*.md"))) == 1


def test_snapshot_no_runs_db_exits_2(tmp_path, monkeypatch):
    eval_dir = tmp_path / ".lola-eval"
    eval_dir.mkdir()
    (eval_dir / "config.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [claude-sonnet-4-6]\n"
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot"])

    assert result.exit_code == 2
    assert "no runs.db" in result.output


def test_snapshot_corrupt_ledger_exits_2(tmp_path, monkeypatch):
    eval_dir = _seed_target(tmp_path)
    (eval_dir / "ledger.jsonl").write_text("NOT JSON\n")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot"])

    assert result.exit_code == 2
    assert "invalid JSON" in result.output

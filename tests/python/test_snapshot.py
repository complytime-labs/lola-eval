"""Committed eval-history snapshots: dedup, ledger shape, markdown."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lola_eval import store
from lola_eval.snapshot import (
    read_ledger_run_ids,
    select_new_rows,
    snapshot_id_for,
    write_snapshot,
)


def _db_row(run_id: str, ts: str, **overrides) -> dict:
    base = {
        "run_id": run_id,
        "timestamp": ts,
        "fingerprint": "fp-" + run_id,
        "target_cli": "claude-code",
        "target_model": "sonnet",
        "target_cli_ver": "2.1.0",
        "pack_id": "project",
        "profile_id": "none",
        "task_id": "case-001",
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "autonomous",
        "invocation": "passive",
        "judge_cli": "claude-code",
        "judge_model": "sonnet",
        "scores_json": json.dumps(
            {"composite": 0.85, "components": {"correctness": 0.9}, "explanation": "fine"}
        ),
        "transcript_path": "/tmp/t.jsonl",
        "exit_status": "success",
        "cost_usd": 1.50,
        "duration_s": 120.0,
        "input_tokens": 1000,
        "output_tokens": 500,
        "git_sha": "a" * 40,
        "git_branch": "main",
        "git_remote": "git@github.com:me/repo.git",
        "git_author": "Test Author",
        "git_date": "2026-07-02T00:00:00-04:00",
        "git_commit_msg": "feat: thing",
        "git_dirty": 0,
        "task_description": "A test case.",
        "rubric_pass_threshold": 0.6,
    }
    base.update(overrides)
    return base


@pytest.fixture
def db(tmp_path) -> Path:
    p = tmp_path / "runs.db"
    store.init_db(p)
    return p


def test_read_ledger_missing_file_is_empty(tmp_path):
    assert read_ledger_run_ids(tmp_path / "ledger.jsonl") == set()


def test_read_ledger_tolerates_legacy_lines_without_run_id(tmp_path):
    """snapshot.sh-era lines have no run_id; they must not break dedup."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps({"snapshot_id": "20260520T221435Z", "task_id": "case-001"}) + "\n"
        + json.dumps({"run_id": "r1", "task_id": "case-001"}) + "\n"
    )
    assert read_ledger_run_ids(ledger) == {"r1"}


def test_read_ledger_raises_on_corrupt_line(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text('{"run_id": "r1"}\nNOT JSON\n')
    with pytest.raises(ValueError, match="ledger.jsonl:2"):
        read_ledger_run_ids(ledger)


def test_select_new_rows_filters_and_orders_oldest_first(db):
    store.insert_run(db, _db_row("r1", "2026-07-01T00:00:00Z"))
    store.insert_run(db, _db_row("r2", "2026-07-02T00:00:00Z"))
    rows = select_new_rows(db, {"r1"})
    assert [r["run_id"] for r in rows] == ["r2"]
    rows = select_new_rows(db, set())
    assert [r["run_id"] for r in rows] == ["r1", "r2"]


def test_snapshot_id_from_newest_run_timestamp():
    rows = [
        {"timestamp": "2026-07-01T00:00:00Z"},
        {"timestamp": "2026-07-02T13:41:54Z"},
    ]
    assert snapshot_id_for(rows) == "20260702T134154Z"


def test_write_snapshot_appends_and_renders(db, tmp_path):
    store.insert_run(db, _db_row("r1", "2026-07-01T00:00:00Z"))
    store.insert_run(db, _db_row("r2", "2026-07-02T00:00:00Z", task_id="case-002"))
    ledger_dir = tmp_path / ".lola-eval"

    result = write_snapshot(ledger_dir, db)

    assert result["appended"] == 2
    lines = [
        json.loads(ln)
        for ln in (ledger_dir / "ledger.jsonl").read_text().splitlines()
    ]
    assert len(lines) == 2
    row = lines[0]
    # report-row shape + identifiers + enrichment
    assert row["run_id"] == "r1"
    assert row["snapshot_id"] == result["snapshot_id"]
    assert row["cli"] == "claude-code"        # mapped from target_cli
    assert row["model"] == "sonnet"           # mapped from target_model
    assert row["composite"] == 0.85           # parsed out of scores_json
    assert row["components"] == {"correctness": 0.9}
    assert row["explanation"] == "fine"
    assert row["git_sha_short"] == "a" * 7
    assert row["git_dirty"] is False          # int -> bool
    assert row["git_author"] == "Test Author"
    assert row["task_description"] == "A test case."
    assert "scores_json" not in row
    assert "transcript_path" not in row
    assert "workdir_diff" not in row

    md = result["markdown"].read_text()
    assert md.startswith(f"# Eval Snapshot — {result['snapshot_id']}")
    assert "## Matrix Summary" in md
    assert "## Judge Notes" in md
    assert "## Token Economics" in md
    assert "claude-code/sonnet/case-001" in md


def test_write_snapshot_is_idempotent(db, tmp_path):
    store.insert_run(db, _db_row("r1", "2026-07-01T00:00:00Z"))
    ledger_dir = tmp_path / ".lola-eval"

    first = write_snapshot(ledger_dir, db)
    second = write_snapshot(ledger_dir, db)

    assert first["appended"] == 1
    assert second["appended"] == 0
    assert second["markdown"] is None
    assert len((ledger_dir / "ledger.jsonl").read_text().splitlines()) == 1


def test_write_snapshot_captures_only_new_runs(db, tmp_path):
    store.insert_run(db, _db_row("r1", "2026-07-01T00:00:00Z"))
    ledger_dir = tmp_path / ".lola-eval"
    write_snapshot(ledger_dir, db)

    store.insert_run(db, _db_row("r2", "2026-07-02T00:00:00Z"))
    result = write_snapshot(ledger_dir, db)

    assert result["appended"] == 1
    assert result["run_ids"] == ["r2"]
    lines = (ledger_dir / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 2
    # two snapshot markdown files now exist
    assert len(list((ledger_dir / "snapshots").glob("*.md"))) == 2


def test_write_snapshot_dry_run_writes_nothing(db, tmp_path):
    store.insert_run(db, _db_row("r1", "2026-07-01T00:00:00Z"))
    ledger_dir = tmp_path / ".lola-eval"

    result = write_snapshot(ledger_dir, db, dry_run=True)

    assert result["appended"] == 1
    assert result["run_ids"] == ["r1"]
    assert not (ledger_dir / "ledger.jsonl").exists()
    assert not (ledger_dir / "snapshots").exists()


def test_write_snapshot_tolerates_unparseable_scores(db, tmp_path):
    """A run with corrupt scores_json is still recorded (score fields null)
    rather than silently dropped from history."""
    store.insert_run(db, _db_row("r1", "2026-07-01T00:00:00Z", scores_json="not json"))
    ledger_dir = tmp_path / ".lola-eval"

    result = write_snapshot(ledger_dir, db)

    assert result["appended"] == 1
    row = json.loads((ledger_dir / "ledger.jsonl").read_text().splitlines()[0])
    assert row["composite"] is None
    assert row["components"] == {}


def test_write_snapshot_renders_none_heavy_rows(db, tmp_path):
    """Rows with None composite/cost/threshold must render without crashing
    and count as neither pass nor fail in the Total row."""
    store.insert_run(
        db,
        _db_row(
            "r1",
            "2026-07-01T00:00:00Z",
            scores_json=json.dumps({"composite": None, "components": {}, "explanation": ""}),
            cost_usd=None,
            duration_s=None,
            rubric_pass_threshold=None,
        ),
    )
    store.insert_run(db, _db_row("r2", "2026-07-02T00:00:00Z", task_id="case-002"))
    ledger_dir = tmp_path / ".lola-eval"

    result = write_snapshot(ledger_dir, db)

    assert result["appended"] == 2
    md = result["markdown"].read_text()
    # r2 passes (0.85 >= 0.6); r1 is unknown -> neither pass nor fail
    assert "1p/0f" in md

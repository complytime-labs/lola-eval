"""store.export_rows: filtered historical export with heavy-column exclusion."""

from __future__ import annotations

import json

from lola_eval import store


def _row(**ov) -> dict:
    base = {
        "run_id": "r1",
        "timestamp": "2026-05-20T00:00:00Z",
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
        "scores_json": json.dumps({"composite": 0.8, "components": {}, "explanation": ""}),
        "transcript_path": "/tmp/t.jsonl",
        "exit_status": "success",
        "workdir_diff": "HUGE" * 1000,
    }
    base.update(ov)
    return base


def test_export_rows_excludes_heavy_columns_by_default(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    store.insert_run(db, _row())
    rows = store.export_rows(db)
    assert len(rows) == 1
    assert "workdir_diff" not in rows[0]
    assert "transcript_path" not in rows[0]
    assert rows[0]["run_id"] == "r1"


def test_export_rows_can_include_heavy_columns(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    store.insert_run(db, _row())
    rows = store.export_rows(db, include_diff=True, include_paths=True)
    assert "workdir_diff" in rows[0]
    assert "transcript_path" in rows[0]


def test_export_rows_filters_by_task_since_fingerprint(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    store.insert_run(
        db,
        _row(run_id="a", task_id="case-001", timestamp="2026-05-19T00:00:00Z", fingerprint="fpA"),
    )
    store.insert_run(
        db,
        _row(run_id="b", task_id="case-002", timestamp="2026-05-21T00:00:00Z", fingerprint="fpB"),
    )
    assert [r["run_id"] for r in store.export_rows(db, task="case-002")] == ["b"]
    assert [r["run_id"] for r in store.export_rows(db, since="2026-05-20T00:00:00Z")] == ["b"]
    assert [r["run_id"] for r in store.export_rows(db, fingerprint="fpA")] == ["a"]


def test_export_rows_orders_by_timestamp_desc(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    store.insert_run(db, _row(run_id="old", timestamp="2026-05-19T00:00:00Z"))
    store.insert_run(db, _row(run_id="new", timestamp="2026-05-21T00:00:00Z"))
    assert [r["run_id"] for r in store.export_rows(db)] == ["new", "old"]

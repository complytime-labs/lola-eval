"""SQLite drift store.

Schema must match the design doc Section 4. Connection helper creates
the DB on first use (idempotent), and exposes parameterised queries
for inserting rows and looking up by fingerprint.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

import pytest

from lola_eval import store


@pytest.fixture
def db(tmp_path) -> Path:
    p = tmp_path / "runs.db"
    store.init_db(p)
    return p


def test_init_db_creates_schema(db):
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
    )
    assert cur.fetchone() is not None
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_fingerprint_time'"
    )
    assert cur.fetchone() is not None
    conn.close()


def test_init_db_is_idempotent(db):
    store.init_db(db)
    store.init_db(db)  # second call must not raise


def _row(**overrides):
    base = dict(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        timestamp="2026-05-08T00:00:00Z",
        fingerprint="abc123",
        target_cli="claude-code",
        target_model="claude-sonnet-4-6",
        target_cli_ver="2.1.131",
        pack_id="none",
        task_id="case-001-fix-bug",
        task_version="1",
        rubric_version="1",
        exec_mode="autonomous",
        invocation="passive",
        judge_cli="opencode",
        judge_model="claude-sonnet-4-6",
        scores_json=json.dumps({"composite": 0.8}),
        transcript_path="/tmp/t.jsonl",
        workdir_diff="--- a\n+++ b\n",
        cost_usd=0.05,
        duration_s=42.0,
        exit_status="success",
        error_message=None,
    )
    base.update(overrides)
    return base


def test_insert_and_fetch(db):
    row = _row()
    store.insert_run(db, row)
    fetched = store.fetch_by_run_id(db, row["run_id"])
    assert fetched is not None
    assert fetched["fingerprint"] == "abc123"
    assert json.loads(fetched["scores_json"])["composite"] == 0.8


def test_fetch_by_fingerprint_orders_newest_first(db):
    store.insert_run(db, _row(run_id="A", timestamp="2026-05-01T00:00:00Z"))
    store.insert_run(db, _row(run_id="B", timestamp="2026-05-08T00:00:00Z"))
    rows = store.fetch_by_fingerprint(db, "abc123")
    assert [r["run_id"] for r in rows] == ["B", "A"]


def test_fetch_unknown_run_returns_none(db):
    assert store.fetch_by_run_id(db, "missing") is None


def test_required_fields_enforced(db):
    bad = _row()
    del bad["fingerprint"]
    with pytest.raises((sqlite3.IntegrityError, KeyError, TypeError)):
        store.insert_run(db, bad)

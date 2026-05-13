"""Schema migration must be idempotent and additive (no data loss)."""
import sqlite3

import pytest

from lola_eval.store import init_db, insert_run

REQUIRED_FIELDS = {
    "run_id": "abc-123",
    "timestamp": "2026-05-09T00:00:00Z",
    "fingerprint": "deadbeef" * 8,
    "target_cli": "claude-code",
    "target_model": "sonnet",
    "target_cli_ver": "1.0.0",
    "pack_id": "none",
    "task_id": "case-001-fix-bug",
    "task_version": "1",
    "rubric_version": "1",
    "exec_mode": "autonomous",
    "invocation": "passive",
    "judge_cli": "claude-code",
    "judge_model": "sonnet",
    "scores_json": '{"composite": 1.0}',
    "transcript_path": "/tmp/x.jsonl",
    "exit_status": "success",
}


def test_init_db_creates_schema_with_new_columns(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    conn = sqlite3.connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    conn.close()
    assert {"turns", "tool_calls_count", "diff_bytes"}.issubset(cols)


def test_init_db_creates_token_count_columns(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    conn = sqlite3.connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    conn.close()
    assert {"input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"}.issubset(cols)


def test_init_db_migrates_legacy_db_to_add_token_columns(tmp_path):
    """An existing DB without the four token columns should gain them via ALTER TABLE."""
    db = tmp_path / "legacy.db"
    init_db(db)
    # Drop the four token columns by recreating the table without them.
    conn = sqlite3.connect(db)
    conn.executescript("""
      CREATE TABLE runs_legacy AS SELECT
        run_id, timestamp, fingerprint, target_cli, target_model, target_cli_ver,
        pack_id, task_id, task_version, rubric_version, exec_mode, invocation,
        judge_cli, judge_model, scores_json, transcript_path, workdir_diff,
        cost_usd, duration_s, exit_status, error_message,
        turns, tool_calls_count, diff_bytes
      FROM runs;
      DROP TABLE runs;
      ALTER TABLE runs_legacy RENAME TO runs;
    """)
    conn.execute(
        f"INSERT INTO runs ({','.join(REQUIRED_FIELDS)}) VALUES ({','.join('?' for _ in REQUIRED_FIELDS)})",
        list(REQUIRED_FIELDS.values()),
    )
    conn.commit()
    conn.close()

    init_db(db)  # Re-run migration.
    conn = sqlite3.connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.close()
    assert {"input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"}.issubset(cols)
    assert n == 1  # Pre-existing row preserved.


def test_insert_run_accepts_token_count_fields(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    row = {
        **REQUIRED_FIELDS,
        "input_tokens": 8,
        "output_tokens": 2563,
        "cache_read_tokens": 1024,
        "cache_creation_tokens": 256,
    }
    insert_run(db, row)
    conn = sqlite3.connect(db)
    fetched = conn.execute(
        "SELECT input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens FROM runs"
    ).fetchone()
    conn.close()
    assert fetched == (8, 2563, 1024, 256)


def test_init_db_migrates_legacy_db_without_new_columns(tmp_path):
    db = tmp_path / "legacy.db"
    legacy_schema = """
    CREATE TABLE runs (
      run_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, fingerprint TEXT NOT NULL,
      target_cli TEXT NOT NULL, target_model TEXT NOT NULL, target_cli_ver TEXT NOT NULL,
      pack_id TEXT NOT NULL, task_id TEXT NOT NULL, task_version TEXT NOT NULL,
      rubric_version TEXT NOT NULL, exec_mode TEXT NOT NULL, invocation TEXT NOT NULL,
      judge_cli TEXT NOT NULL, judge_model TEXT NOT NULL, scores_json TEXT NOT NULL,
      transcript_path TEXT NOT NULL, workdir_diff TEXT, cost_usd REAL, duration_s REAL,
      exit_status TEXT NOT NULL, error_message TEXT
    );
    """
    conn = sqlite3.connect(db)
    conn.executescript(legacy_schema)
    conn.execute(
        f"INSERT INTO runs ({','.join(REQUIRED_FIELDS)}) VALUES ({','.join('?' for _ in REQUIRED_FIELDS)})",
        list(REQUIRED_FIELDS.values()),
    )
    conn.commit()
    conn.close()
    init_db(db)
    conn = sqlite3.connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.close()
    assert {"turns", "tool_calls_count", "diff_bytes"}.issubset(cols)
    assert n == 1


def test_insert_run_accepts_new_optional_fields(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    row = {**REQUIRED_FIELDS, "turns": 7, "tool_calls_count": 12, "diff_bytes": 4096}
    insert_run(db, row)
    conn = sqlite3.connect(db)
    fetched = conn.execute("SELECT turns, tool_calls_count, diff_bytes FROM runs").fetchone()
    conn.close()
    assert fetched == (7, 12, 4096)


def test_insert_run_works_without_new_fields(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    insert_run(db, REQUIRED_FIELDS)
    conn = sqlite3.connect(db)
    fetched = conn.execute("SELECT turns, tool_calls_count, diff_bytes FROM runs").fetchone()
    conn.close()
    assert fetched == (None, None, None)


def test_init_db_creates_judge_consensus_columns(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    conn = sqlite3.connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    conn.close()
    assert {"judge_scores_json", "judge_disagreement"}.issubset(cols)


def test_insert_run_accepts_judge_consensus_fields(tmp_path):
    import json as _json
    db = tmp_path / "runs.db"
    init_db(db)
    per_judge = [{"judge_id": "claude-code/sonnet", "scores": {"correctness": 0.9}, "explanation": "ok"}]
    row = {
        **REQUIRED_FIELDS,
        "judge_scores_json": _json.dumps(per_judge),
        "judge_disagreement": 0.05,
    }
    insert_run(db, row)
    conn = sqlite3.connect(db)
    fetched = conn.execute(
        "SELECT judge_scores_json, judge_disagreement FROM runs"
    ).fetchone()
    conn.close()
    assert _json.loads(fetched[0]) == per_judge
    assert fetched[1] == pytest.approx(0.05)

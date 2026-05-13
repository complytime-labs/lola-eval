"""SQLite drift store: schema, connection, insert/fetch helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id          TEXT PRIMARY KEY,
  timestamp       TEXT NOT NULL,
  fingerprint     TEXT NOT NULL,
  target_cli      TEXT NOT NULL,
  target_model    TEXT NOT NULL,
  target_cli_ver  TEXT NOT NULL,
  pack_id         TEXT NOT NULL,
  task_id         TEXT NOT NULL,
  task_version    TEXT NOT NULL,
  rubric_version  TEXT NOT NULL,
  exec_mode       TEXT NOT NULL,
  invocation      TEXT NOT NULL,
  judge_cli       TEXT NOT NULL,
  judge_model     TEXT NOT NULL,
  scores_json     TEXT NOT NULL,
  transcript_path TEXT NOT NULL,
  workdir_diff    TEXT,
  cost_usd        REAL,
  duration_s      REAL,
  exit_status     TEXT NOT NULL,
  error_message   TEXT,
  turns           INTEGER,
  tool_calls_count INTEGER,
  diff_bytes      INTEGER,
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  cache_read_tokens INTEGER,
  cache_creation_tokens INTEGER
);
CREATE INDEX IF NOT EXISTS idx_fingerprint_time ON runs(fingerprint, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_target_pack      ON runs(target_model, pack_id);
"""

REQUIRED_COLUMNS = (
    "run_id", "timestamp", "fingerprint",
    "target_cli", "target_model", "target_cli_ver",
    "pack_id", "task_id", "task_version", "rubric_version",
    "exec_mode", "invocation",
    "judge_cli", "judge_model",
    "scores_json", "transcript_path", "exit_status",
)

OPTIONAL_NEW_COLUMNS = (
    "turns",
    "tool_calls_count",
    "diff_bytes",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "judge_scores_json",
    "judge_disagreement",
)

# SQLite type for each optional column. Defaults to INTEGER when absent.
_OPTIONAL_COLUMN_TYPE: dict[str, str] = {
    "judge_scores_json": "TEXT",
    "judge_disagreement": "REAL",
}


def _connect(db: Path) -> sqlite3.Connection:
    """Open `db` for reads and writes with the lola_eval-standard PRAGMAs.

    Both writers (insert_run from trajectory_judge subprocesses) and
    readers (runner._collect_rows, report._connect, compare/graph helpers)
    share this entry point so the 30-second busy_timeout applies to every
    contention scenario, not just the migration step in init_db.
    """
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def connect_read(db: Path) -> sqlite3.Connection:
    """Public alias for read-side callers (runner, compare, graph, report).

    Same as the private _connect helper. Exposed so the three previously
    duplicated `_connect_for_read` helpers can collapse to one definition.
    """
    return _connect(db)


def init_db(db: Path) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db)
    try:
        with conn:
            conn.executescript(SCHEMA)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
            for col in OPTIONAL_NEW_COLUMNS:
                if col not in existing:
                    col_type = _OPTIONAL_COLUMN_TYPE.get(col, "INTEGER")
                    conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {col_type}")
    finally:
        conn.close()


def insert_run(db: Path, row: dict[str, Any]) -> None:
    for col in REQUIRED_COLUMNS:
        if col not in row or row[col] is None:
            raise KeyError(f"missing required column: {col}")
    cols = ",".join(row.keys())
    placeholders = ",".join(f":{k}" for k in row.keys())
    conn = _connect(db)
    try:
        with conn:
            conn.execute(f"INSERT INTO runs ({cols}) VALUES ({placeholders})", row)
    finally:
        conn.close()


def fetch_by_run_id(db: Path, run_id: str) -> dict | None:
    conn = _connect(db)
    try:
        cur = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        r = cur.fetchone()
    finally:
        conn.close()
    return dict(r) if r else None


def fetch_by_fingerprint(db: Path, fingerprint: str) -> list[dict]:
    conn = _connect(db)
    try:
        cur = conn.execute(
            "SELECT * FROM runs WHERE fingerprint = ? ORDER BY timestamp DESC",
            (fingerprint,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

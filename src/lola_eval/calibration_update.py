# src/lola_eval/calibration_update.py
"""SELECT calibration columns from a runs.db, dedup last-write-wins
against the bundled JSONL, write back, recompute sha256."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from lola_eval import pricing
from lola_eval.calibration import (
    CalibrationRow,
    _data_dir,
    _dedup_last_write_wins,
    _parse_jsonl,
)


_SELECT = """
SELECT
  run_id, timestamp, target_cli, target_cli_ver, target_model,
  pack_id, task_id, profile_id, exec_mode,
  input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
  turns, tool_calls_count, duration_s, cost_usd, exit_status
FROM runs
WHERE exit_status = 'success'
"""


def _row_to_calibration(
    row: sqlite3.Row, resolver: pricing.Resolver
) -> CalibrationRow | None:
    """Convert a runs.db row to a CalibrationRow, deriving target_family
    via pricing.Resolver. Returns None if any required field is null."""
    try:
        target_model = str(row["target_model"])
        res = resolver.lookup(target_model)
        target_family = res.pricing.family if res.pricing is not None else ""
        return CalibrationRow(
            run_id=str(row["run_id"]),
            timestamp=str(row["timestamp"]),
            target_cli=str(row["target_cli"]),
            target_cli_ver=str(row["target_cli_ver"]),
            target_model=target_model,
            target_family=target_family,
            pack_id=str(row["pack_id"]),
            task_id=str(row["task_id"]),
            profile_id=str(row["profile_id"]),
            exec_mode=str(row["exec_mode"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cache_read_tokens=int(row["cache_read_tokens"] or 0),
            cache_creation_tokens=int(row["cache_creation_tokens"] or 0),
            turns=int(row["turns"] or 0),
            tool_calls_count=int(row["tool_calls_count"] or 0),
            duration_s=float(row["duration_s"]),
            cost_usd=float(row["cost_usd"]),
        )
    except (TypeError, ValueError, KeyError):
        return None


def _row_to_jsonl_dict(r: CalibrationRow) -> dict:
    return {
        "run_id": r.run_id,
        "timestamp": r.timestamp,
        "target_cli": r.target_cli,
        "target_cli_ver": r.target_cli_ver,
        "target_model": r.target_model,
        "target_family": r.target_family,
        "pack_id": r.pack_id,
        "task_id": r.task_id,
        "profile_id": r.profile_id,
        "exec_mode": r.exec_mode,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cache_read_tokens": r.cache_read_tokens,
        "cache_creation_tokens": r.cache_creation_tokens,
        "turns": r.turns,
        "tool_calls_count": r.tool_calls_count,
        "duration_s": r.duration_s,
        "cost_usd": r.cost_usd,
    }


def update(src_db: Path, target_jsonl: Path) -> tuple[int, int, int]:
    """Append/merge rows from `src_db` into `target_jsonl`.

    Returns (new_rows, replaced_rows, total_rows). Recomputes sidecar.
    """
    conn = sqlite3.connect(src_db)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(_SELECT)
        sqlite_rows = list(cur.fetchall())
    finally:
        conn.close()

    resolver = pricing.Resolver()
    new_rows: list[CalibrationRow] = []
    for sr in sqlite_rows:
        c = _row_to_calibration(sr, resolver)
        if c is not None:
            new_rows.append(c)

    existing_body = target_jsonl.read_bytes() if target_jsonl.exists() else b""
    existing_rows = _parse_jsonl(existing_body)

    before_ids = {r.run_id for r in existing_rows}
    merged = _dedup_last_write_wins(existing_rows + new_rows)
    after_ids = {r.run_id for r in merged}

    added = len(after_ids - before_ids)
    replaced = sum(
        1 for r in new_rows
        if r.run_id in before_ids
        and any(e.run_id == r.run_id and e.timestamp != r.timestamp for e in existing_rows)
    )

    merged.sort(key=lambda r: r.timestamp)
    target_jsonl.write_text(
        "\n".join(json.dumps(_row_to_jsonl_dict(r), separators=(",", ":")) for r in merged)
        + ("\n" if merged else "")
    )

    sidecar = target_jsonl.with_suffix(target_jsonl.suffix + ".sha256")
    sidecar.write_text(hashlib.sha256(target_jsonl.read_bytes()).hexdigest() + "\n")

    return added, replaced, len(merged)


def main():
    parser = argparse.ArgumentParser(prog="lola_eval.calibration_update")
    parser.add_argument("--src", required=True, type=Path, help="Path to runs.db")
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Path to bundled runs.jsonl (default: src/lola_eval/_data/calibration/runs.jsonl)",
    )
    args = parser.parse_args()

    target = args.target or Path(str(_data_dir().joinpath("runs.jsonl")))
    added, replaced, total = update(args.src, target)
    print(f"[calibration:update] + {added} new rows, {replaced} replaced, total = {total}")


if __name__ == "__main__":
    main()

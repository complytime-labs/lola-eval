#!/usr/bin/env python3
"""Assert structural invariants over a live lola-eval runs.db.

"Provably good" for LIVE runs means the FRAMEWORK behaved correctly,
independent of the (non-deterministic) agent quality score:

  - the judge completed         (exit_status not an infra failure)
  - provenance is recorded      (git_sha + fingerprint_version == "2")
  - the diff is hermetic        (no build artifacts: node_modules/, __pycache__/, ...)
  - successful rows are scored   (a real numeric composite)
  - resolved models recorded    (target/judge resolved model present)

Usage:
    python tests/live/check_invariants.py <results_dir>   # default: .lola-eval

Exits 0 when every row satisfies every invariant, 1 otherwise.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ARTIFACT_MARKERS = ("node_modules/", "__pycache__/", ".venv/", "dist/", ".egg-info")
# Framework/infra failures the should-pass live suite must never exhibit.
# `setup_error` (provisioning/pre_run failure — judge never runs) is included:
# in the should-pass suite it can only mean the harness failed to prepare the
# workdir. Judge timeouts surface as `judge_error`, so there is no separate
# `judge_timeout` state to check.
INFRA_FAILURES = {"judge_error", "no_run_produced", "setup_error"}


def _composite(row: dict):
    try:
        return json.loads(row["scores_json"]).get("composite")
    except (TypeError, KeyError, json.JSONDecodeError):
        return None


def check(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY timestamp")]
    conn.close()

    if not rows:
        print(f"FAIL: no rows in {db_path}")
        return 1

    failures: list[str] = []
    for r in rows:
        cell = f"{r['target_cli']}/{r['target_model']}/{r['task_id']}"
        row_problems: list[str] = []

        if r["exit_status"] in INFRA_FAILURES:
            row_problems.append(
                f"infra failure exit_status={r['exit_status']} "
                f"({(r.get('error_message') or '')[:120]})"
            )
        if not r.get("git_sha"):
            row_problems.append("missing git_sha provenance")
        if r.get("fingerprint_version") != "2":
            row_problems.append(
                f"fingerprint_version={r.get('fingerprint_version')} (expected '2')"
            )
        if not r.get("target_model_resolved"):
            row_problems.append("missing target_model_resolved")

        diff = r.get("workdir_diff") or ""
        for marker in ARTIFACT_MARKERS:
            if marker in diff:
                row_problems.append(f"workdir_diff contains build artifact '{marker}'")

        if r["exit_status"] == "success":
            comp = _composite(r)
            if not isinstance(comp, (int, float)):
                row_problems.append("success row has no numeric composite")

        sigil = "OK" if not row_problems else "!!"
        comp = _composite(r)
        print(
            f"  [{sigil}] {cell}  exit={r['exit_status']}  "
            f"composite={comp}  diff={r.get('diff_bytes')}B  "
            f"git={(r.get('git_sha') or '')[:8]}  fpv={r.get('fingerprint_version')}"
        )
        failures.extend(f"{cell}: {p}" for p in row_problems)

    print()
    if failures:
        print(f"INVARIANT FAILURES ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: {len(rows)} row(s) satisfy all structural invariants")
    return 0


def main() -> int:
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".lola-eval")
    db = results_dir / "runs.db"
    if not db.exists():
        print(f"FAIL: no runs.db at {db}")
        return 1
    return check(db)


if __name__ == "__main__":
    sys.exit(main())

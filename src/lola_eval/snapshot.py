"""Committed eval-history snapshots: append-only JSONL ledger + markdown.

The ledger at ``<eval_dir>/ledger.jsonl`` is the durable, committed record of
eval history — one report-shaped row per cell, enriched with git provenance.
It is also the dedup state: a run whose ``run_id`` already appears in the
ledger is never appended again, so ``lola-eval snapshot`` is idempotent and
needs no separate high-water-mark file.

Lines written by the pre-native ``snapshot.sh`` wrapper carry no ``run_id``;
they are tolerated (and preserved) but contribute nothing to dedup.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lola_eval import store
from lola_eval.markdown_report import (
    _dimension_breakdown,
    _judge_notes,
    _matrix_summary,
    _provenance,
    _token_economics,
)

LEDGER_NAME = "ledger.jsonl"
SNAPSHOTS_DIRNAME = "snapshots"


def read_ledger_run_ids(ledger_path: Path) -> set[str]:
    """Return the run_ids already recorded in the ledger.

    Legacy lines without a ``run_id`` key are skipped. A line that is not
    valid JSON raises ValueError with its line number — an append-only
    history file that has been hand-edited into corruption should be fixed,
    not silently ignored.
    """
    if not ledger_path.exists():
        return set()
    seen: set[str] = set()
    for n, line in enumerate(ledger_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{ledger_path}:{n}: invalid JSON in ledger: {e}") from e
        rid = obj.get("run_id")
        if rid:
            seen.add(rid)
    return seen


def select_new_rows(db: Path, seen: set[str]) -> list[dict]:
    """All runs.db rows not yet in the ledger, oldest first (append order).

    Heavy columns (workdir_diff, transcript_path) are already dropped by
    store.export_rows.
    """
    rows = store.export_rows(db)  # newest first
    fresh = [r for r in rows if r.get("run_id") not in seen]
    fresh.reverse()
    return fresh


def snapshot_id_for(rows: list[dict]) -> str:
    """Snapshot id from the newest captured run's timestamp.

    Derived from data already in runs.db — not the wall clock — so the same
    capture always produces the same id. ``2026-07-02T13:41:54Z`` ->
    ``20260702T134154Z`` (the same shape snapshot.sh used).
    """
    newest = max(r["timestamp"] for r in rows)
    return re.sub(r"[-:]", "", newest)


def _ledger_row(db_row: dict, snapshot_id: str) -> dict:
    """One ledger line: the report-row shape (cli/model, parsed scores) plus
    run identifiers, matching the key set snapshot.sh produced so existing
    tooling over a migrated ledger keeps working."""
    row = dict(db_row)
    raw = row.pop("scores_json", None)
    try:
        scores = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        # Keep the run in history with null score fields rather than
        # dropping it — a corrupt judge payload is itself a fact worth
        # recording. (Mirrors _fetch_rows' leniency, without the row loss.)
        scores = {}
    sha = row.pop("git_sha", None)
    dirty = row.pop("git_dirty", None)
    out = {
        "run_id": row.pop("run_id"),
        "snapshot_id": snapshot_id,
        "timestamp": row.pop("timestamp"),
        "cli": row.pop("target_cli"),
        "model": row.pop("target_model"),
        "composite": scores.get("composite"),
        "components": scores.get("components", {}),
        "explanation": scores.get("explanation", ""),
        "git_sha": sha,
        "git_sha_short": sha[:7] if sha else None,
        "git_dirty": bool(dirty) if dirty is not None else None,
    }
    # Remaining columns keep their runs.db names. If a future runs.db column
    # is ever named like a computed key above (composite, cli, model, ...),
    # this update would silently shadow the computed value — rename the
    # column instead.
    out.update(row)
    return out


def write_snapshot(ledger_dir: Path, db: Path, *, dry_run: bool = False) -> dict:
    """Append every not-yet-recorded run to the ledger and render a markdown
    snapshot covering the newly captured rows.

    Returns ``{"appended": int, "snapshot_id": str | None, "ledger": Path,
    "markdown": Path | None, "run_ids": list[str]}``. ``appended`` is the
    cell (row) count; ``run_ids`` the distinct runs captured. With
    ``dry_run`` nothing is written and ``markdown`` is None.
    """
    ledger = ledger_dir / LEDGER_NAME
    seen = read_ledger_run_ids(ledger)
    fresh = select_new_rows(db, seen)
    if not fresh:
        return {
            "appended": 0,
            "snapshot_id": None,
            "ledger": ledger,
            "markdown": None,
            "run_ids": [],
        }
    sid = snapshot_id_for(fresh)
    lrows = [_ledger_row(r, sid) for r in fresh]
    run_ids = sorted({r["run_id"] for r in lrows})
    if dry_run:
        return {
            "appended": len(lrows),
            "snapshot_id": sid,
            "ledger": ledger,
            "markdown": None,
            "run_ids": run_ids,
        }
    ledger_dir.mkdir(parents=True, exist_ok=True)
    # Markdown first, ledger last: the ledger is the dedup state, so a
    # failure between the two writes must leave the run_ids UNrecorded —
    # an orphaned .md is overwritten on retry, but rows recorded without
    # their snapshot would never be re-captured.
    md_path = ledger_dir / SNAPSHOTS_DIRNAME / f"{sid}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_render_markdown(sid, lrows))
    # Single buffered write narrows the partial-line crash window that
    # would otherwise trip read_ledger_run_ids' strict JSON parsing.
    payload = "".join(json.dumps(r, sort_keys=True) + "\n" for r in lrows)
    with ledger.open("a") as fh:
        fh.write(payload)
    return {
        "appended": len(lrows),
        "snapshot_id": sid,
        "ledger": ledger,
        "markdown": md_path,
        "run_ids": run_ids,
    }


def _render_markdown(sid: str, rows: list[dict]) -> str:
    """Snapshot markdown from the same section renderers `report` uses.

    Only the newly captured rows are rendered — each snapshot file is the
    human-readable record of exactly what its ledger append covered.
    """
    has_profiles = any(r.get("profile_id", "none") != "none" for r in rows)
    has_packs = len({r.get("pack_id") for r in rows}) > 1
    parts = [f"# Eval Snapshot — {sid}\n"]
    parts.append(_provenance(rows, has_profiles, has_packs))
    parts.append(_matrix_summary(rows, has_profiles, has_packs))
    parts.append(_dimension_breakdown(rows, has_profiles, has_packs))
    parts.append(_judge_notes(rows, has_profiles, has_packs))
    parts.append(_token_economics(rows, has_profiles, has_packs))
    return "\n".join(p for p in parts if p)

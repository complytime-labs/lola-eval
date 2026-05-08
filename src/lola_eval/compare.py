"""Baseline-vs-pack comparison engine.

Aggregates run rows from the SQLite store into per-cell comparisons.
A "cell" is the tuple (target_cli, target_model, task_id). Within a
cell, the rows tagged ``pack_id="none"`` form the baseline and every
other ``pack_id`` becomes its own ComparisonRow contrasted against
that baseline.

The output is consumed by ``print_compare`` (CLI) and the HTML report
template; both treat ComparisonRow as a frozen, read-only view.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path

from lola_eval import xdg
from lola_eval.math import lift_percent
from lola_eval.store import connect_read as _connect_for_read


@dataclass
class ComparisonRow:
    """One baseline-vs-pack contrast for a single cell."""

    target_cli: str
    target_model: str
    task_id: str
    pack_id: str
    n_baseline: int
    n_pack: int
    composite: dict
    components: dict
    success_rate: dict
    cost: dict
    duration: dict
    turns: dict
    tools: dict
    diff: dict
    # Token aggregates: each is {baseline_mean, pack_mean, delta}, with
    # None when neither side recorded the metric (legacy rows / opencode).
    input_tokens: dict
    output_tokens: dict
    cache_read_tokens: dict
    cache_creation_tokens: dict


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.fmean(values)


def _composite_of(row: sqlite3.Row) -> float | None:
    """Parse the composite score from scores_json; return None on any defect."""
    raw = row["scores_json"]
    if not raw:
        return None
    try:
        comp = json.loads(raw).get("composite")
    except (ValueError, TypeError):
        return None
    if comp is None:
        return None
    try:
        return float(comp)
    except (ValueError, TypeError):
        return None


def _components_of(row: sqlite3.Row) -> dict[str, float]:
    """Parse component scores; return {} if absent or malformed."""
    raw = row["scores_json"]
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    comps = parsed.get("components") or {}
    if not isinstance(comps, dict):
        return {}
    out: dict[str, float] = {}
    for name, value in comps.items():
        if value is None:
            continue
        try:
            out[name] = float(value)
        except (ValueError, TypeError):
            continue
    return out


def _column_means(rows: list[sqlite3.Row], column: str) -> float | None:
    """Mean of a numeric column, ignoring NULLs. None if no non-NULL values."""
    values: list[float] = []
    for r in rows:
        v = r[column]
        if v is None:
            continue
        try:
            values.append(float(v))
        except (ValueError, TypeError):
            continue
    return _mean_or_none(values)


def _success_rate(rows: list[sqlite3.Row]) -> float:
    if not rows:
        return 0.0
    successes = sum(1 for r in rows if r["exit_status"] == "success")
    return successes / len(rows)


def _composite_stats(rows: list[sqlite3.Row]) -> tuple[float | None, float | None]:
    """Return (mean, latest) composite. Latest = newest by timestamp DESC."""
    parsed: list[tuple[str, float]] = []
    for r in rows:
        c = _composite_of(r)
        if c is None:
            continue
        parsed.append((r["timestamp"], c))
    if not parsed:
        return (None, None)
    mean = statistics.fmean(c for _, c in parsed)
    parsed.sort(key=lambda t: t[0], reverse=True)
    return (mean, parsed[0][1])


def _component_means(rows: list[sqlite3.Row]) -> dict[str, float]:
    """Mean of each criterion across all rows that contained it."""
    buckets: dict[str, list[float]] = {}
    for r in rows:
        for name, value in _components_of(r).items():
            buckets.setdefault(name, []).append(value)
    return {name: statistics.fmean(values) for name, values in buckets.items() if values}


def _delta(pack: float | None, baseline: float | None) -> float | None:
    if pack is None or baseline is None:
        return None
    return pack - baseline


def _telemetry(baseline_rows, pack_rows, column: str) -> dict:
    bm = _column_means(baseline_rows, column)
    pm = _column_means(pack_rows, column)
    return {"baseline_mean": bm, "pack_mean": pm, "delta": _delta(pm, bm)}


def _build_row(
    target_cli: str,
    target_model: str,
    task_id: str,
    pack_id: str,
    baseline_rows: list[sqlite3.Row],
    pack_rows: list[sqlite3.Row],
) -> ComparisonRow:
    b_mean, b_latest = _composite_stats(baseline_rows)
    p_mean, p_latest = _composite_stats(pack_rows)
    composite = {
        "baseline_mean": b_mean,
        "baseline_latest": b_latest,
        "pack_mean": p_mean,
        "pack_latest": p_latest,
        "lift_percent": lift_percent(p_mean, b_mean),
    }

    b_components = _component_means(baseline_rows)
    p_components = _component_means(pack_rows)
    components: dict[str, dict] = {}
    for name in sorted(set(b_components) | set(p_components)):
        bv = b_components.get(name)
        pv = p_components.get(name)
        components[name] = {
            "baseline_mean": bv,
            "pack_mean": pv,
            "delta": _delta(pv, bv),
        }

    return ComparisonRow(
        target_cli=target_cli,
        target_model=target_model,
        task_id=task_id,
        pack_id=pack_id,
        n_baseline=len(baseline_rows),
        n_pack=len(pack_rows),
        composite=composite,
        components=components,
        success_rate={
            "baseline": _success_rate(baseline_rows),
            "pack": _success_rate(pack_rows),
        },
        cost=_telemetry(baseline_rows, pack_rows, "cost_usd"),
        duration=_telemetry(baseline_rows, pack_rows, "duration_s"),
        turns=_telemetry(baseline_rows, pack_rows, "turns"),
        tools=_telemetry(baseline_rows, pack_rows, "tool_calls_count"),
        diff=_telemetry(baseline_rows, pack_rows, "diff_bytes"),
        input_tokens=_telemetry(baseline_rows, pack_rows, "input_tokens"),
        output_tokens=_telemetry(baseline_rows, pack_rows, "output_tokens"),
        cache_read_tokens=_telemetry(baseline_rows, pack_rows, "cache_read_tokens"),
        cache_creation_tokens=_telemetry(baseline_rows, pack_rows, "cache_creation_tokens"),
    )


def compare_all(db: Path) -> list[ComparisonRow]:
    """Read the run store and produce one ComparisonRow per (cell × non-baseline pack).

    Cells without a ``pack_id="none"`` baseline are omitted: a comparison
    needs both sides. Cells are keyed by (target_cli, target_model, task_id);
    rubric/exec/invocation differences inside one cell are folded together
    by mean. Result rows are sorted by (target_cli, target_model, task_id,
    pack_id) for stable output.
    """
    if not db.exists():
        return []
    conn = _connect_for_read(db)
    try:
        all_rows = list(conn.execute("SELECT * FROM runs"))
    finally:
        conn.close()

    # Group by (target_cli, target_model, task_id) -> {pack_id: [rows]}
    cells: dict[tuple[str, str, str], dict[str, list[sqlite3.Row]]] = {}
    for r in all_rows:
        key = (r["target_cli"], r["target_model"], r["task_id"])
        cells.setdefault(key, {}).setdefault(r["pack_id"], []).append(r)

    out: list[ComparisonRow] = []
    for (cli, model, task), packs in cells.items():
        baseline_rows = packs.get("none")
        if not baseline_rows:
            continue
        for pack_id, pack_rows in packs.items():
            if pack_id == "none":
                continue
            out.append(_build_row(cli, model, task, pack_id, baseline_rows, pack_rows))

    out.sort(key=lambda r: (r.target_cli, r.target_model, r.task_id, r.pack_id))
    return out


_RULE = "─" * 72


def _fmt(value, spec: str = ".3f") -> str:
    """Format a value with the given spec, returning ``n/a`` for None."""
    if value is None:
        return "n/a"
    return format(value, spec)


def _fmt_signed(value: float | None, spec: str = "+.3f") -> str:
    if value is None:
        return "n/a"
    return format(value, spec)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"


def _composite_marker(lift_pct: float | None) -> str:
    if lift_pct is None:
        return ""
    if lift_pct > 0:
        return "  ▲"
    if lift_pct < 0:
        return "  ▼"
    return ""


def _print_telemetry_line(label: str, block: dict, spec: str, signed_spec: str) -> None:
    bm = _fmt(block["baseline_mean"], spec)
    pm = _fmt(block["pack_mean"], spec)
    delta = _fmt_signed(block["delta"], signed_spec)
    print(f"  {label:<14}  baseline={bm}  pack={pm}  Δ={delta}")


def print_compare(threshold_fail: float | None = None) -> int:
    """Print one stanza per (cell × pack) baseline-vs-pack contrast.

    Reads ``xdg.db_path()`` and writes to stdout. Returns 1 if
    ``threshold_fail`` is set and any composite lift % falls below it,
    otherwise 0. Returns 0 with a friendly message when the DB is absent
    or holds no comparable rows.
    """
    db = xdg.resolve_db_path()
    if not db.exists():
        print("(no runs.db yet)")
        return 0

    rows = compare_all(db)

    print()
    noun = "cell" if len(rows) == 1 else "cells"
    print(f"COMPARE  ({len(rows)} {noun})")
    print(_RULE)

    if not rows:
        print("  (no pack-vs-baseline cells yet — run a non-baseline pack alongside a")
        print("   matching pack=none row to populate)")
        return 0

    failed = False
    for r in rows:
        lp = r.composite["lift_percent"]
        marker = _composite_marker(lp)
        print(f"  target          {r.target_cli} / {r.target_model}")
        print(f"  task            {r.task_id}")
        print(f"  pack            {r.pack_id}")
        print(f"  n               baseline={r.n_baseline}  pack={r.n_pack}")
        bm = _fmt(r.composite["baseline_mean"], ".3f")
        pm = _fmt(r.composite["pack_mean"], ".3f")
        print(f"  composite mean  baseline={bm}  pack={pm}{marker}")
        print(f"  lift            {_fmt_pct(lp)}")

        for name, block in r.components.items():
            cbm = _fmt(block["baseline_mean"], ".3f")
            cpm = _fmt(block["pack_mean"], ".3f")
            cdelta = _fmt_signed(block["delta"], "+.3f")
            print(f"    {name:<12}  baseline={cbm}  pack={cpm}  Δ={cdelta}")

        _print_telemetry_line("cost (USD)", r.cost, ".4f", "+.4f")
        _print_telemetry_line("duration (s)", r.duration, ".1f", "+.1f")
        _print_telemetry_line("turns", r.turns, ".1f", "+.1f")
        _print_telemetry_line("tool calls", r.tools, ".1f", "+.1f")
        _print_telemetry_line("diff bytes", r.diff, ".0f", "+.0f")
        _print_telemetry_line("input tokens", r.input_tokens, ".1f", "+.1f")
        _print_telemetry_line("output tokens", r.output_tokens, ".1f", "+.1f")
        _print_telemetry_line("cache read tk", r.cache_read_tokens, ".1f", "+.1f")
        _print_telemetry_line("cache creat tk", r.cache_creation_tokens, ".1f", "+.1f")

        sb = _fmt_rate(r.success_rate["baseline"])
        sp = _fmt_rate(r.success_rate["pack"])
        print(f"  success rate    baseline={sb}    pack={sp}")
        print(_RULE)

        if threshold_fail is not None and lp is not None and lp < threshold_fail:
            failed = True

    if threshold_fail is not None:
        verdict = "FAIL" if failed else "OK"
        print(f"  threshold {threshold_fail:+.2f}%: {verdict}")
        print()

    return 1 if failed else 0

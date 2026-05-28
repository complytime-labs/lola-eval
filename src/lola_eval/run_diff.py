"""Semantic diff of two runs' persisted structured outputs (#10).

Compares stored data (scores, exit_status, counters) rather than raw
transcript text — robust to agent output format and far more actionable
than a score delta alone. Two runs with different fingerprints are not
strictly comparable; the diff says so but still renders the deltas.
"""

from __future__ import annotations

import json
from typing import Any


def _scores(row: dict) -> tuple[float | None, dict[str, float]]:
    try:
        s = json.loads(row.get("scores_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return None, {}
    composite = s.get("composite")
    components = s.get("components") or {}
    return composite, {k: float(v) for k, v in components.items()}


def _fmt_delta(a: float | None, b: float | None) -> str:
    if a is None or b is None:
        return f"{a} → {b}"
    return f"{a:.2f} → {b:.2f}  ({b - a:+.2f})"


def _fmt_int_delta(a, b) -> str:
    if a is None or b is None:
        return f"{a} → {b}"
    delta = b - a
    sign = f"{delta:+d}" if isinstance(a, int) and isinstance(b, int) else f"{delta:+.0f}"
    return f"{a} → {b}  ({sign})"


def build_run_diff(row_a: dict, row_b: dict) -> str:
    """Render a human-readable structured diff of two run rows."""
    lines: list[str] = []
    lines.append(
        f"Run A: {str(row_a.get('run_id', ''))[:8]}  "
        f"{row_a.get('target_cli', '?')}/{row_a.get('target_model', '?')}  "
        f"task={row_a.get('task_id', '?')}  fp={str(row_a.get('fingerprint', ''))[:12]}"
    )
    lines.append(
        f"Run B: {str(row_b.get('run_id', ''))[:8]}  "
        f"{row_b.get('target_cli', '?')}/{row_b.get('target_model', '?')}  "
        f"task={row_b.get('task_id', '?')}  fp={str(row_b.get('fingerprint', ''))[:12]}"
    )
    if row_a.get("fingerprint") != row_b.get("fingerprint"):
        lines.append(
            "[!] fingerprints differ — these runs are NOT strictly comparable "
            "(different identity: cli/task/version/profile/subject)."
        )
    lines.append("")

    comp_a, comps_a = _scores(row_a)
    comp_b, comps_b = _scores(row_b)
    lines.append(f"composite:   {_fmt_delta(comp_a, comp_b)}")
    for crit in sorted(set(comps_a) | set(comps_b)):
        lines.append(f"  {crit}: {_fmt_delta(comps_a.get(crit), comps_b.get(crit))}")

    lines.append("")
    lines.append(f"exit_status: {row_a.get('exit_status', '?')} → {row_b.get('exit_status', '?')}")
    for label, key in (("tool_calls", "tool_calls_count"), ("diff_bytes", "diff_bytes")):
        lines.append(f"{label}:  {_fmt_int_delta(row_a.get(key), row_b.get(key))}")
    for label, key in (
        ("turns", "turns"),
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("cache_read_tokens", "cache_read_tokens"),
        ("cache_creation_tokens", "cache_creation_tokens"),
    ):
        lines.append(f"{label}:  {_fmt_int_delta(row_a.get(key), row_b.get(key))}")
    for label, key in (("cost_usd", "cost_usd"), ("duration_s", "duration_s")):
        a_val: Any = row_a.get(key)
        b_val: Any = row_b.get(key)
        lines.append(f"{label}:   {_fmt_delta(a_val, b_val)}")
    return "\n".join(lines) + "\n"

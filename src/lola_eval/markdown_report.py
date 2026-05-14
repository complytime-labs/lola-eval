"""Markdown comparison report renderer."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from lola_eval.store import connect_read


def build_markdown(out_path: Path | None = None,
                   results_dir: Path | None = None) -> Path:
    if results_dir is None:
        rd = os.environ.get("LOLA_RESULTS_DIR")
        results_dir = Path(rd) if rd else Path(".lola-eval")

    db = results_dir / "runs.db"
    if not db.exists():
        raise FileNotFoundError(f"no runs.db at {db}")
    last_run_path = results_dir / "last-run.json"
    if not last_run_path.exists():
        raise FileNotFoundError(f"no last-run.json at {last_run_path}")

    entries = json.loads(last_run_path.read_text())
    conn = connect_read(db)
    rows = _fetch_rows(conn, entries)
    conn.close()

    has_profiles = any(r.get("profile_id", "none") != "none" for r in rows)

    lines: list[str] = []
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"# Evaluation Report — {ts}\n")
    lines.append(_matrix_summary(rows, has_profiles))
    lines.append(_dimension_breakdown(rows, has_profiles))
    lines.append(_judge_notes(rows, has_profiles))
    lines.append(_token_economics(rows, has_profiles))
    lines.append(_run_details(rows, has_profiles))

    content = "\n".join(lines)
    if out_path is None:
        ts_file = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = results_dir / "reports" / f"{ts_file}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    print(f"wrote {out_path}")
    return out_path


def build_json(out_path: Path | None = None,
               results_dir: Path | None = None) -> Path:
    if results_dir is None:
        rd = os.environ.get("LOLA_RESULTS_DIR")
        results_dir = Path(rd) if rd else Path(".lola-eval")

    db = results_dir / "runs.db"
    last_run_path = results_dir / "last-run.json"
    entries = json.loads(last_run_path.read_text())
    conn = connect_read(db)
    rows = _fetch_rows(conn, entries)
    conn.close()

    if out_path is None:
        ts_file = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = results_dir / "reports" / f"{ts_file}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"wrote {out_path}")
    return out_path


def _fetch_rows(conn, entries: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cli = entry.get("cli")
        model = entry.get("model")
        task_id = entry.get("task_id")
        pack_id = entry.get("pack_id")
        profile_id = entry.get("profile_id", "none")
        if not all([cli, model, task_id, pack_id]):
            continue
        row = conn.execute(
            "SELECT * FROM runs "
            "WHERE target_cli=? AND target_model=? AND task_id=? AND pack_id=? "
            "AND profile_id=? ORDER BY timestamp DESC LIMIT 1",
            (cli, model, task_id, pack_id, profile_id),
        ).fetchone()
        if row is None:
            continue
        try:
            scores = json.loads(row["scores_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        row_dict = dict(row)
        rows.append({
            "cli": cli, "model": model, "task_id": task_id,
            "pack_id": pack_id, "profile_id": profile_id,
            "composite": scores.get("composite"),
            "components": scores.get("components", {}),
            "explanation": scores.get("explanation", ""),
            "cost_usd": row["cost_usd"], "duration_s": row["duration_s"],
            "turns": row["turns"], "tool_calls_count": row["tool_calls_count"],
            "diff_bytes": row["diff_bytes"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "cache_read_tokens": row_dict.get("cache_read_tokens"),
            "cache_creation_tokens": row_dict.get("cache_creation_tokens"),
            "transcript_path": row["transcript_path"],
            "exit_status": row["exit_status"],
            "target_cli_ver": row["target_cli_ver"],
            "judge_cli": row["judge_cli"], "judge_model": row["judge_model"],
        })
    return rows


def _cell_label(r: dict, has_profiles: bool) -> str:
    label = f"{r['cli']}/{r['model']}"
    if has_profiles:
        label += f"/{r['profile_id']}"
    return label


def _matrix_summary(rows: list[dict], has_profiles: bool) -> str:
    cols = ["Cell", "Composite", "Cost", "Tokens", "Duration"]
    if has_profiles:
        cols.insert(1, "Profile")
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = ["## Matrix Summary\n", header, sep]
    for r in rows:
        total_tok = (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
        vals = [
            f"{r['cli']}/{r['model']}",
            f"**{_format_composite(r['composite'])}**",
            _format_cost(r["cost_usd"]),
            _format_tokens(total_tok if total_tok else None),
            _format_duration(r["duration_s"]),
        ]
        if has_profiles:
            vals.insert(1, r["profile_id"])
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def _dimension_breakdown(rows: list[dict], has_profiles: bool) -> str:
    if not rows:
        return ""
    all_dims: set[str] = set()
    for r in rows:
        all_dims.update(r.get("components", {}).keys())
    dims = sorted(all_dims)
    if not dims:
        return ""
    cols = ["Cell"]
    if has_profiles:
        cols.append("Profile")
    cols.extend(dims)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = ["## Per-Dimension Breakdown\n", header, sep]
    for r in rows:
        comps = r.get("components", {})
        vals = [f"{r['cli']}/{r['model']}"]
        if has_profiles:
            vals.append(r["profile_id"])
        for d in dims:
            v = comps.get(d)
            vals.append(f"{v:.2f}" if v is not None else "-")
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def _judge_notes(rows: list[dict], has_profiles: bool) -> str:
    lines = ["## Judge Notes\n"]
    for r in rows:
        label = _cell_label(r, has_profiles)
        explanation = r.get("explanation", "").strip() or "(no explanation)"
        lines.append(f"### {label}\n")
        lines.append(f"{explanation}\n")
    return "\n".join(lines) + "\n"


def _token_economics(rows: list[dict], has_profiles: bool) -> str:
    cols = ["Cell"]
    if has_profiles:
        cols.append("Profile")
    cols.extend(["Input", "Output", "Cache Read", "Cache Write", "Cost"])
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = ["## Token Economics\n", header, sep]
    for r in rows:
        vals = [f"{r['cli']}/{r['model']}"]
        if has_profiles:
            vals.append(r["profile_id"])
        vals.extend([
            _format_tokens(r.get("input_tokens")),
            _format_tokens(r.get("output_tokens")),
            _format_tokens(r.get("cache_read_tokens")),
            _format_tokens(r.get("cache_creation_tokens")),
            _format_cost(r["cost_usd"]),
        ])
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def _run_details(rows: list[dict], has_profiles: bool) -> str:
    lines = ["## Run Details\n"]
    for r in rows:
        label = _cell_label(r, has_profiles)
        lines.append(f"### {label}\n")
        lines.append(f"- **CLI version**: {r.get('target_cli_ver', 'unknown')}")
        lines.append(f"- **Judge**: {r.get('judge_cli', '?')}/{r.get('judge_model', '?')}")
        lines.append(f"- **Tool calls**: {r.get('tool_calls_count', '?')}")
        lines.append(f"- **Diff size**: {r.get('diff_bytes', '?')} bytes")
        lines.append(f"- **Transcript**: `{r.get('transcript_path', '?')}`")
        lines.append(f"- **Exit status**: {r.get('exit_status', '?')}")
        lines.append("")
    return "\n".join(lines)


def _format_tokens(n) -> str:
    if n is None or n == 0:
        return "-"
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)


def _format_cost(usd) -> str:
    if usd is None:
        return "-"
    return f"${usd:.2f}"


def _format_duration(s) -> str:
    if s is None:
        return "-"
    if s >= 60:
        return f"{s / 60:.1f}m"
    return f"{s:.0f}s"


def _format_composite(v) -> str:
    if v is None:
        return "-"
    return f"{v:.2f}"

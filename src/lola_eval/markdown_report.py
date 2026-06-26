"""Markdown comparison report renderer."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from lola_eval import __version__
from lola_eval.store import connect_read

# Bump when the JSON envelope shape changes incompatibly so consumers can
# detect breaks. The bare-array output predates the envelope (no version).
JSON_SCHEMA_VERSION = "1"


def build_markdown(out_path: Path | None = None, results_dir: Path | None = None) -> Path:
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

    from lola_eval.compare import compare_all
    from lola_eval.report import _drift_rows, _lift_rows

    agg_conn = connect_read(db)
    try:
        drift_rows = _drift_rows(agg_conn)
        lift_rows = _lift_rows(agg_conn)
        infra_section = _infra_md(agg_conn)
    finally:
        agg_conn.close()
    compare_rows = compare_all(db)

    has_profiles = any(r.get("profile_id", "none") != "none" for r in rows)

    lines: list[str] = []
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"# Evaluation Report — {ts}\n")
    lines.append(_matrix_summary(rows, has_profiles))
    lines.append(_dimension_breakdown(rows, has_profiles))
    lines.append(_judge_notes(rows, has_profiles))
    lines.append(_token_economics(rows, has_profiles))
    lines.append(_run_details(rows, has_profiles))
    lines.append(_provenance(rows, has_profiles))
    lines.append(_drift_md(drift_rows))
    lines.append(_lift_md(lift_rows))
    lines.append(_compare_md(compare_rows))
    lines.append(infra_section)

    content = "\n".join(lines)
    if out_path is None:
        ts_file = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = results_dir / "reports" / f"{ts_file}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    print(f"wrote {out_path}")
    return out_path


def build_json(out_path: Path | None = None, results_dir: Path | None = None) -> Path:
    """Write the last run's rows as a versioned JSON envelope.

    Wraps the per-cell rows in run-level metadata (schema version, lola-eval
    version, generation time, pass/fail/cost summary) plus the drift, lift,
    and compare aggregations the HTML report already computes, so machine
    consumers can detect breaking changes and read aggregates without
    re-deriving them from the bare rows.
    """
    from dataclasses import asdict

    from lola_eval.compare import compare_all
    from lola_eval.report import _drift_rows, _lift_rows

    if results_dir is None:
        rd = os.environ.get("LOLA_RESULTS_DIR")
        results_dir = Path(rd) if rd else Path(".lola-eval")

    db = results_dir / "runs.db"
    last_run_path = results_dir / "last-run.json"
    entries = json.loads(last_run_path.read_text())
    conn = connect_read(db)
    rows = _fetch_rows(conn, entries)
    drift = _drift_rows(conn)
    lift = _lift_rows(conn)
    conn.close()
    # compare_all returns ComparisonRow dataclasses; flatten to plain dicts so
    # the envelope is JSON-serializable when a baseline-vs-pack pair exists.
    compare = [asdict(r) for r in compare_all(db)] if db.exists() else []

    envelope = {
        "schema_version": JSON_SCHEMA_VERSION,
        "lola_eval_version": __version__,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "summary": _json_summary(rows),
        "rows": rows,
        "drift": drift,
        "lift": lift,
        "compare": compare,
    }

    if out_path is None:
        ts_file = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = results_dir / "reports" / f"{ts_file}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2) + "\n")
    print(f"wrote {out_path}")
    return out_path


def _row_passed(row: dict) -> bool | None:
    """True/False when both composite and threshold are known, else None
    (insufficient data — counted as neither pass nor fail)."""
    composite = row.get("composite")
    threshold = row.get("rubric_pass_threshold")
    if composite is None or threshold is None:
        return None
    return composite >= threshold


def _json_summary(rows: list[dict]) -> dict:
    passed = sum(1 for r in rows if _row_passed(r) is True)
    failed = sum(1 for r in rows if _row_passed(r) is False)
    cost = sum(r["cost_usd"] for r in rows if r.get("cost_usd") is not None)
    return {
        "total_cells": len(rows),
        "passed": passed,
        "failed": failed,
        "cost_usd": cost,
    }


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
        rubric_pass_threshold = entry.get("rubric_pass_threshold")
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
        rows.append(
            {
                "cli": cli,
                "model": model,
                "task_id": task_id,
                "pack_id": pack_id,
                "profile_id": profile_id,
                "composite": scores.get("composite"),
                "rubric_pass_threshold": rubric_pass_threshold,
                "components": scores.get("components", {}),
                "explanation": scores.get("explanation", ""),
                "cost_usd": row["cost_usd"],
                "duration_s": row["duration_s"],
                "turns": row["turns"],
                "tool_calls_count": row["tool_calls_count"],
                "diff_bytes": row["diff_bytes"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_read_tokens": row_dict.get("cache_read_tokens"),
                "cache_creation_tokens": row_dict.get("cache_creation_tokens"),
                "transcript_path": row["transcript_path"],
                "exit_status": row["exit_status"],
                "target_cli_ver": row["target_cli_ver"],
                "judge_cli": row["judge_cli"],
                "judge_model": row["judge_model"],
                "git_sha": row_dict.get("git_sha"),
                "git_branch": row_dict.get("git_branch"),
                "git_remote": row_dict.get("git_remote"),
                "subject_version": row_dict.get("subject_version"),
                "fingerprint_version": row_dict.get("fingerprint_version"),
                "target_model_resolved": row_dict.get("target_model_resolved"),
                "judge_model_resolved": row_dict.get("judge_model_resolved"),
            }
        )
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
        vals.extend(
            [
                _format_tokens(r.get("input_tokens")),
                _format_tokens(r.get("output_tokens")),
                _format_tokens(r.get("cache_read_tokens")),
                _format_tokens(r.get("cache_creation_tokens")),
                _format_cost(r["cost_usd"]),
            ]
        )
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def _embed_transcript_md(path) -> str:
    """Return a collapsible markdown block embedding the transcript file
    content, or a not-found fallback line when the file is unreadable."""
    if not path:
        return "- **Transcript**: (none)"
    try:
        # Transcripts are model/CLI output and not guaranteed valid UTF-8;
        # errors="replace" degrades undecodable bytes instead of raising
        # UnicodeDecodeError and crashing the whole report build.
        content = Path(path).read_text(errors="replace")
    except OSError:
        return f"- **Transcript**: `{path}` (not found)"
    name = os.path.basename(path)
    return (
        f"<details><summary>Transcript: {name}</summary>\n\n"
        f"```jsonl\n{content}\n```\n\n"
        f"</details>"
    )


def _run_details(rows: list[dict], has_profiles: bool) -> str:
    lines = ["## Run Details\n"]
    for r in rows:
        label = _cell_label(r, has_profiles)
        lines.append(f"### {label}\n")
        lines.append(f"- **CLI version**: {r.get('target_cli_ver', 'unknown')}")
        lines.append(f"- **Judge**: {r.get('judge_cli', '?')}/{r.get('judge_model', '?')}")
        if r.get("target_model_resolved"):
            lines.append(f"- **Resolved target model**: {r['target_model_resolved']}")
        if r.get("judge_model_resolved"):
            lines.append(f"- **Resolved judge model**: {r['judge_model_resolved']}")
        lines.append(f"- **Tool calls**: {r.get('tool_calls_count', '?')}")
        lines.append(f"- **Diff size**: {r.get('diff_bytes', '?')} bytes")
        lines.append(_embed_transcript_md(r.get("transcript_path")))
        lines.append(f"- **Exit status**: {r.get('exit_status', '?')}")
        lines.append("")
    return "\n".join(lines)


def _provenance(rows: list[dict], has_profiles: bool) -> str:
    """Render a Provenance section, or '' when no row carries provenance.

    Only emitted when at least one row has a git_sha or subject_version, so
    runs without provenance (older rows, non-git targets) degrade silently.
    """
    present = [r for r in rows if r.get("git_sha") or r.get("subject_version")]
    if not present:
        return ""
    lines = ["## Provenance\n"]
    for r in present:
        label = _cell_label(r, has_profiles)
        lines.append(f"### {label}\n")
        if r.get("subject_version"):
            lines.append(f"- **Subject version**: {r['subject_version']}")
        if r.get("git_sha"):
            branch = r.get("git_branch")
            suffix = f" ({branch})" if branch else ""
            lines.append(f"- **Commit**: {r['git_sha']}{suffix}")
        if r.get("git_remote"):
            lines.append(f"- **Remote**: {r['git_remote']}")
        lines.append("")
    return "\n".join(lines)


def _drift_md(drift_rows: list[dict]) -> str:
    lines = ["## Drift Δ\n"]
    if not drift_rows:
        lines.append("(no drift records yet)\n")
        return "\n".join(lines)
    cols = ["Fingerprint", "Task", "Pack", "Now model", "Then model", "Δ", "n runs"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for r in drift_rows:
        delta = r.get("delta")
        delta_str = f"{delta:+.2f}" if delta is not None else "-"
        vals = [
            r["fingerprint"][:12],
            r["task_id"],
            r["pack_id"],
            r["now_model"],
            r["then_model"],
            delta_str,
            str(r["n_runs"]),
        ]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def _lift_md(lift_rows: list[dict]) -> str:
    lines = ["## Lift %\n"]
    if not lift_rows:
        lines.append("(no pack-vs-baseline pairs yet)\n")
        return "\n".join(lines)
    cols = ["CLI", "Model", "Task", "Pack", "Baseline", "Pack", "Lift %"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for r in lift_rows:
        lp = r.get("lift_percent")
        lp_str = f"{lp:+.2f}" if lp is not None else "-"
        vals = [
            r["target_cli"],
            r["target_model"],
            r["task_id"],
            r["pack_id"],
            f"{r['baseline_score']:.2f}",
            f"{r['pack_score']:.2f}",
            lp_str,
        ]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def _compare_md(compare_rows: list) -> str:
    lines = ["## Compare (baseline vs pack)\n"]
    if not compare_rows:
        lines.append("(no baseline-vs-pack pairs yet)\n")
        return "\n".join(lines)
    cols = [
        "CLI",
        "Model",
        "Task",
        "Pack",
        "n base",
        "n pack",
        "Baseline mean",
        "Pack mean",
        "Lift %",
    ]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for r in compare_rows:
        bm = r.composite.get("baseline_mean")
        pm = r.composite.get("pack_mean")
        lp = r.composite.get("lift_percent")
        vals = [
            r.target_cli,
            r.target_model,
            r.task_id,
            r.pack_id,
            str(r.n_baseline),
            str(r.n_pack),
            f"{bm:.3f}" if bm is not None else "-",
            f"{pm:.3f}" if pm is not None else "-",
            f"{lp:+.2f}" if lp is not None else "-",
        ]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def _infra_md(conn) -> str:
    rows = list(
        conn.execute(
            "SELECT run_id, timestamp, target_cli, target_model, task_id, exit_status, error_message "
            "FROM runs WHERE exit_status IN ('setup_error','judge_error') ORDER BY timestamp DESC"
        )
    )
    lines = ["## Infra failures\n"]
    if not rows:
        lines.append("(no infra failures)\n")
        return "\n".join(lines)
    cols = ["Run", "Timestamp", "Target CLI", "Target model", "Task", "Exit", "Error"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")
    for r in rows:
        vals = [
            (r["run_id"] or "")[:8],
            r["timestamp"] or "",
            r["target_cli"] or "",
            r["target_model"] or "",
            r["task_id"] or "",
            r["exit_status"] or "",
            _md_cell(r["error_message"]),
        ]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def _md_cell(text) -> str:
    """Flatten a free-text value (e.g. a CLI stderr snippet) for a single
    markdown table cell: collapse whitespace/newlines and escape pipes so the
    row can't break the table."""
    if not text:
        return ""
    return " ".join(str(text).split()).replace("|", "\\|")


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

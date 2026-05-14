"""Drift / Lift query + HTML render."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from lola_eval import xdg
from lola_eval.compare import compare_all
from lola_eval.math import drift_delta, lift_percent
from lola_eval.store import connect_read


def _connect():
    db = xdg.resolve_db_path()
    if not db.exists():
        return None
    return connect_read(db)


def _drift_rows(conn) -> list[dict]:
    """For each fingerprint, compute Δ between latest and earliest rows."""
    fps = [r["fingerprint"] for r in conn.execute("SELECT DISTINCT fingerprint FROM runs")]
    out = []
    for fp in fps:
        rows = list(conn.execute(
            "SELECT * FROM runs WHERE fingerprint=? ORDER BY timestamp DESC", (fp,),
        ).fetchall())
        if not rows:
            continue
        latest = rows[0]
        baseline = rows[-1]
        try:
            latest_composite = json.loads(latest["scores_json"]).get("composite")
            baseline_composite = json.loads(baseline["scores_json"]).get("composite")
        except Exception:
            continue
        out.append({
            "fingerprint": fp,
            "now_model": latest["target_model"],
            "then_model": baseline["target_model"],
            "delta": drift_delta(latest_composite, baseline_composite),
            "n_runs": len(rows),
            "task_id": latest["task_id"],
            "pack_id": latest["pack_id"],
        })
    return out


def _lift_rows(conn) -> list[dict]:
    """For each (target_cli, target_model, task_id, exec_mode, invocation),
    compare each non-none pack to the matching pack=none baseline."""
    rows = list(conn.execute("""
        SELECT target_cli, target_model, task_id, task_version, rubric_version,
               exec_mode, invocation, pack_id, scores_json
        FROM runs
        WHERE exit_status IN ('success','target_timeout','target_error')
        ORDER BY timestamp DESC
    """).fetchall())

    by_key: dict[tuple, dict[str, float]] = {}
    for r in rows:
        key = (r["target_cli"], r["target_model"], r["task_id"], r["task_version"],
               r["rubric_version"], r["exec_mode"], r["invocation"])
        try:
            comp = json.loads(r["scores_json"]).get("composite")
        except Exception:
            continue
        if comp is None:
            continue
        bucket = by_key.setdefault(key, {})
        bucket.setdefault(r["pack_id"], comp)

    out = []
    for key, packs in by_key.items():
        baseline = packs.get("none")
        if baseline is None:
            continue
        for pack_id, score in packs.items():
            if pack_id == "none":
                continue
            out.append({
                "target_cli": key[0], "target_model": key[1],
                "task_id": key[2],
                "exec_mode": key[5], "invocation": key[6],
                "pack_id": pack_id,
                "baseline_score": baseline,
                "pack_score": score,
                "lift_percent": lift_percent(score, baseline),
            })
    return out


_RULE = "─" * 72


def _fmt_signed(value: float | None, width: int = 7) -> str:
    if value is None:
        return "n/a".rjust(width)
    return f"{value:+.2f}".rjust(width)


def _fmt_pct(value: float | None, width: int = 8) -> str:
    if value is None:
        return "n/a".rjust(width)
    return f"{value:+.2f}%".rjust(width)


def print_drift(fingerprint: str | None = None, threshold_fail: float | None = None) -> int:
    """Print one stanza per fingerprint. Wide-friendly, no horizontal squish."""
    conn = _connect()
    if conn is None:
        print("(no runs.db yet)")
        return 0
    rows = _drift_rows(conn)
    conn.close()
    if fingerprint:
        rows = [r for r in rows if r["fingerprint"].startswith(fingerprint)]

    print()
    print(f"DRIFT Δ  ({len(rows)} fingerprint{'s' if len(rows) != 1 else ''})")
    print(_RULE)
    if not rows:
        print("  (no drift records yet — run `task run` to populate)")
        return 0

    failed = False
    for r in rows:
        d = r["delta"]
        marker = ""
        if d is not None and d < 0:
            marker = "  ▼ regression"
        elif d is not None and d > 0:
            marker = "  ▲ improvement"
        print(f"  fingerprint   {r['fingerprint']}")
        print(f"  task          {r['task_id']}")
        print(f"  pack          {r['pack_id']}")
        print(f"  model (now)   {r['now_model']}")
        print(f"  model (then)  {r['then_model']}")
        if r["now_model"] != r["then_model"]:
            print(f"  ▶ model swap   {r['then_model']} → {r['now_model']}")
        print(f"  Δ composite   {_fmt_signed(d)}{marker}")
        print(f"  runs          {r['n_runs']}")
        print(_RULE)
        if threshold_fail is not None and d is not None and d < threshold_fail:
            failed = True

    if threshold_fail is not None:
        verdict = "FAIL" if failed else "OK"
        print(f"  threshold {threshold_fail:+.2f}: {verdict}")
        print()
    return 1 if failed else 0


def print_lift(threshold_fail: float | None = None) -> int:
    """Print one stanza per (target × pack) lift comparison."""
    conn = _connect()
    if conn is None:
        print("(no runs.db yet)")
        return 0
    rows = _lift_rows(conn)
    conn.close()

    print()
    print(f"LIFT %  ({len(rows)} pack-vs-baseline comparison{'s' if len(rows) != 1 else ''})")
    print(_RULE)
    if not rows:
        print("  (no pack-vs-baseline pairs yet — run a non-baseline pack alongside a")
        print("   matching pack=none row to populate)")
        return 0

    failed = False
    for r in rows:
        lp = r["lift_percent"]
        marker = ""
        if lp is not None and lp < 0:
            marker = "  ▼ pack regressed the agent"
        elif lp is not None and lp > 0:
            marker = "  ▲ pack improved the agent"
        print(f"  target        {r['target_cli']} / {r['target_model']}")
        print(f"  task          {r['task_id']}")
        print(f"  pack          {r['pack_id']}")
        print(f"  baseline      {r['baseline_score']:.3f}")
        print(f"  pack          {r['pack_score']:.3f}")
        print(f"  lift          {_fmt_pct(lp)}{marker}")
        print(_RULE)
        if threshold_fail is not None and lp is not None and lp < threshold_fail:
            failed = True

    if threshold_fail is not None:
        verdict = "FAIL" if failed else "OK"
        print(f"  threshold {threshold_fail:+.2f}%: {verdict}")
        print()
    return 1 if failed else 0


def build_html(out_path: str | Path | None = None) -> Path:
    """Render the drift / lift / compare HTML report.

    Args:
        out_path: Full file path to write. When omitted, falls back to
            ``<XDG_STATE>/lola-eval/reports/<timestamp>.html`` for
            standalone ``lola-eval report`` invocations outside a target
            repo.

    Both ``lola-eval test`` and ``lola-eval report`` now write a single
    file named ``<results_dir>/reports/<timestamp>.html`` so consumers
    have one convention to glob for. Parent directories are created on
    demand.
    """
    if out_path is None:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = xdg.reports_dir() / f"{ts}.html"
    else:
        out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    conn = _connect()
    drift_rows = _drift_rows(conn) if conn else []
    lift_rows = _lift_rows(conn) if conn else []
    infra_rows = []
    if conn:
        infra_rows = [dict(r) for r in conn.execute(
            "SELECT run_id, timestamp, target_cli, target_model, task_id, exit_status, error_message "
            "FROM runs WHERE exit_status IN ('setup_error','judge_error') ORDER BY timestamp DESC"
        )]

    db = xdg.resolve_db_path()
    compare_rows = compare_all(db) if db.exists() else []

    results_dir_env = os.environ.get("LOLA_RESULTS_DIR")
    if results_dir_env:
        results_dir = Path(results_dir_env)
    else:
        results_dir = out_file.parent.parent
    last_run_rows = _last_run_rows(conn, results_dir) if conn else []
    if conn:
        conn.close()

    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(['html']),
    )
    tpl = env.get_template("report.html.j2")
    html = tpl.render(
        generated=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        drift=drift_rows,
        lift=lift_rows,
        infra=infra_rows,
        compare=compare_rows,
        last_run_rows=last_run_rows,
    )
    out_file.write_text(html)
    print(f"wrote {out_file}")
    return out_file


def _last_run_rows(conn, results_dir: Path) -> list[dict]:
    """Build the per-row breakdown list from ``last-run.json``.

    For each cell in ``last-run.json`` (the just-completed batch), find
    the most recent matching row in ``runs.db`` and extract the rich
    judge data (per-criterion scores, rationale, tokens, etc.) needed
    for the in-report breakdown. Rows whose ``scores_json`` is missing
    or malformed are skipped silently so a single bad row cannot crash
    the report build.
    """
    last_run_path = results_dir / "last-run.json"
    if not last_run_path.exists():
        return []
    try:
        entries = json.loads(last_run_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(entries, list):
        return []

    out: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cli = entry.get("cli")
        model = entry.get("model")
        task_id = entry.get("task_id")
        pack_id = entry.get("pack_id")
        profile_id = entry.get("profile_id", "none")
        if cli is None or model is None or task_id is None or pack_id is None:
            continue
        row = conn.execute(
            "SELECT scores_json, transcript_path, cost_usd, duration_s, "
            "turns, tool_calls_count, input_tokens, output_tokens, exit_status "
            "FROM runs "
            "WHERE target_cli=? AND target_model=? AND task_id=? AND pack_id=? "
            "AND profile_id=? "
            "ORDER BY timestamp DESC LIMIT 1",
            (cli, model, task_id, pack_id, profile_id),
        ).fetchone()
        if row is None:
            continue
        try:
            scores = json.loads(row["scores_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(scores, dict):
            continue
        composite = scores.get("composite")
        components = scores.get("components") or {}
        if not isinstance(components, dict):
            components = {}
        per_criterion = sorted(
            ((k, v) for k, v in components.items()),
            key=lambda kv: kv[0],
        )
        threshold = entry.get("rubric_pass_threshold")
        passed = (
            composite is not None
            and threshold is not None
            and composite >= threshold
        )
        out.append({
            "cli": cli,
            "model": model,
            "task_id": task_id,
            "pack_id": pack_id,
            "profile_id": profile_id,
            "composite": composite,
            "threshold": threshold,
            "per_criterion": per_criterion,
            "explanation": scores.get("explanation") or "",
            "transcript_path": row["transcript_path"],
            "cost_usd": row["cost_usd"],
            "duration_s": row["duration_s"],
            "turns": row["turns"],
            "tool_calls_count": row["tool_calls_count"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "exit_status": row["exit_status"],
            "passed": passed,
        })
    return out

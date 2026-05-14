"""`lola-eval test` -- run the eval matrix against a target repo."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env

# Per-call upper bound used by --estimate-cost. Matches the default
# budget_usd in the example task.yaml fixtures and is intentionally
# pessimistic: the goal is to catch surprise CI bills before they
# happen, not to model real spend.
ESTIMATE_PER_CALL_USD = 2.50


def _print_cost_estimate(cfg, target_root: Path) -> None:
    """Print an upper-bound cost estimate for the configured matrix.

    Calculation:
      passes_per_cell = (len(cfg.packs) if cfg.packs else 1)
                        + (1 if cfg.calculate_baseline else 0)
      rows            = (sum models per target) * passes_per_cell * len(cases)
      calls           = rows * (1 agent + N judges)
      total           = calls * $ESTIMATE_PER_CALL_USD
    """
    tests_dir = target_root / cfg.tests_dir
    if not tests_dir.exists():
        cases = 0
    else:
        cases = sum(1 for p in tests_dir.iterdir() if p.is_dir())
    target_models = sum(len(t.models) for t in cfg.targets)
    base_packs = len(cfg.packs) if cfg.packs is not None else 1
    passes = base_packs + (1 if cfg.calculate_baseline else 0)
    judges = len(cfg.judges) if cfg.judges else 1
    n_profiles = 1
    if cfg.profiles_dir:
        profiles_path = target_root / cfg.profiles_dir
        if profiles_path.exists():
            from lola_eval.profile import load_profiles
            loaded = load_profiles(profiles_path, cfg.profiles_common, cfg.profiles)
            n_profiles = max(len(loaded), 1)
    rows = target_models * passes * cases * n_profiles
    total = rows * (1 + judges) * ESTIMATE_PER_CALL_USD

    mode_label = "Mode 2 (external pack review)" if cfg.packs is not None else "Mode 1 (in-repo)"
    baseline_label = "on" if cfg.calculate_baseline else "off"
    # `targets` counts entries in cfg.targets (typically one per CLI);
    # `cells` is the real (cli × model) fanout — what a reader needs to
    # understand why `rows` is what it is.
    cells = target_models
    print("Cost estimate (upper bound):")
    print(f"  mode:     {mode_label}")
    print(f"  cases:    {cases}")
    print(f"  targets:  {len(cfg.targets)}")
    print(f"  cells:    {cells}  (cli × model)")
    print(f"  packs:    {base_packs}")
    print(f"  baseline: {baseline_label}")
    print(f"  profiles: {n_profiles}")
    print(f"  rows:     {rows}")
    print(f"  judges:   {judges}")
    print(f"  per-call: ${ESTIMATE_PER_CALL_USD:.2f}")
    print("  -----")
    print(f"  TOTAL:    ${total:.2f}")
    print()
    print(f"Note: per-call uses a ${ESTIMATE_PER_CALL_USD:.2f} upper bound. Real cost varies 10x")
    print("across model tiers (haiku < sonnet < opus). Treat this as a")
    print("conservative ceiling, not a forecast.")


def _print_cost_summary(cfg, target_root: Path, since: str, n_rows: int) -> None:
    """Print total cost for rows persisted since ``since`` to stderr.

    Silent when the runs.db is missing (no rows persisted yet) or when
    every cost_usd is NULL (target CLIs that don't expose cost — e.g.
    opencode at the moment). The row count is the number of *rows the
    threshold engine saw*, not the number of priced rows; we report both
    via the message wording to keep the line meaningful even when only
    some providers reported cost.
    """
    from lola_eval import xdg
    from lola_eval.store import connect_read

    db = xdg.db_path_for_target(target_root, cfg)
    if not db.exists():
        return
    conn = connect_read(db)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) AS total, "
            "COUNT(cost_usd) AS priced "
            "FROM runs WHERE timestamp >= ?",
            (since,),
        ).fetchone()
    finally:
        conn.close()
    total = float(row["total"] or 0.0)
    priced = int(row["priced"] or 0)
    if priced == 0:
        return
    sys.stderr.write(
        f"[lola-eval-test] total cost: ${total:.2f} across {n_rows} rows\n"
    )


@app.command("test")
def test(
    pack: str | None = typer.Option(
        None, "--pack",
        help="Limit to one pack_id (Mode 2 iteration aid; pass 'project' or 'none' to filter in Mode 1).",
    ),
    case: str | None = typer.Option(None, "--case", help="Limit to one task_id"),
    profile: str | None = typer.Option(None, "--profile", help="Limit to one profile name"),
    no_baseline: bool = typer.Option(
        False, "--no-baseline",
        help="Skip the baseline (pack_id=none) pass; no-op when calculate_baseline is false.",
    ),
    concurrency: int | None = typer.Option(None, "--concurrency", help="Override config concurrency"),
    estimate_cost: bool = typer.Option(
        False, "--estimate-cost",
        help="Print upper-bound cost for the configured matrix; do not run.",
    ),
    config: Path | None = typer.Option(
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)",
    ),
) -> None:
    """Run the configured eval matrix and emit pass/fail + artifacts."""
    from lola_eval.config import load_config, ConfigError
    from lola_eval.threshold import ThresholdEngine, BaselineMissing
    from lola_eval.ci import write_junit_xml, write_github_summary
    from lola_eval import runner, report as report_mod
    from lola_eval.runner import RunnerError

    cfg_path = config if config is not None else (Path.cwd() / "lola-eval.yaml")
    target_root = cfg_path.parent.resolve() if config is not None else Path.cwd()
    try:
        cfg = load_config(cfg_path)
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2)

    if estimate_cost:
        _print_cost_estimate(cfg, target_root)
        raise typer.Exit(0)

    # Centralize the env-var mutation: one hook drives every downstream
    # consumer (runner subprocess, build_html, drift/lift readers).
    # Scoped via context manager so consecutive in-process CLI invocations
    # don't leak LOLA_RESULTS_DIR across boundaries (I11).
    with _activate_target_env(cfg_path):
        # Mark when this invocation started so we can scope the cost
        # rollup below to rows written by this run only. Truncating to
        # seconds matches the format trajectory_judge uses for the
        # ``timestamp`` column, so an inclusive >= filter is correct.
        run_started_at = (
            datetime.now(tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        try:
            rows = runner.run_matrix(
                cfg, target_root,
                pack_filter=pack, case_filter=case,
                no_baseline=no_baseline, concurrency=concurrency,
                profile_filter=profile,
            )
        except (FileNotFoundError, ValueError, RunnerError) as e:
            # FileNotFoundError: missing tests_dir / fixture file.
            # ValueError: malformed rubric (no frontmatter) or unknown target cli.
            # RunnerError: empty matrix after filters.
            # All three are user-facing setup errors -- no traceback.
            typer.echo(f"setup error: {e}", err=True)
            raise typer.Exit(2)

        results_dir = target_root / cfg.results_dir
        engine = ThresholdEngine(
            mode=cfg.threshold.mode,
            tolerance=cfg.threshold.tolerance,
            results_dir=results_dir,
            timeout_is_failure=cfg.threshold.timeout_is_failure,
        )
        try:
            threshold_report = engine.check(rows)
        except BaselineMissing as e:
            typer.echo(f"setup error: {e}", err=True)
            raise typer.Exit(2)

        html_path: Path | None = None
        if cfg.ci.junit_xml:
            write_junit_xml(results_dir / "junit.xml", rows, threshold_report)
        if cfg.ci.github_summary:
            write_github_summary(rows, threshold_report)
        if cfg.ci.html_report:
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            html_path = results_dir / "reports" / f"{ts}.html"
            report_mod.build_html(out_path=html_path)

        try:
            from lola_eval.markdown_report import build_markdown
            md_ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            md_path = results_dir / "reports" / f"{md_ts}.md"
            build_markdown(out_path=md_path, results_dir=results_dir)
        except Exception:
            pass

        # Surface multi-judge disagreement when disagreement_action="warn"
        # (the default). Empty for single-judge configs since the judge
        # writes NULL for that column. When action="fail" the judge has
        # already marked the row failed (failure_kind="judge_disagreement")
        # and the failure list below carries the message; no extra warning
        # needed. When action="off" we stay silent.
        if cfg.disagreement_action == "warn":
            for r in rows:
                if r.judge_disagreement is not None and r.judge_disagreement > cfg.disagreement_threshold:
                    typer.echo(
                        f"⚠ judge disagreement on {r.cell_key}: "
                        f"{r.judge_disagreement:.3f} > threshold {cfg.disagreement_threshold:.3f}",
                        err=True,
                    )

        # Run summary: one line covering rows/failures/timeouts, plus a
        # cost rollup when runs.db carries cost_usd. Printed to stderr so
        # it doesn't pollute promptfoo's structured output on stdout.
        n_rows = len(rows)
        n_failures = len(threshold_report.failures)
        n_timeouts = len(threshold_report.timeouts)
        sys.stderr.write(
            f"[lola-eval-test] {n_rows} rows complete; "
            f"{n_failures} failures; {n_timeouts} timeouts\n"
        )
        _print_cost_summary(cfg, target_root, run_started_at, n_rows)
        sys.stderr.flush()

        if threshold_report.failures:
            typer.echo("Failures:", err=True)
            for f in threshold_report.failures:
                typer.echo(f"  {f.cell_key}: {f.reason}", err=True)
            if html_path is not None:
                # Make the HTML report discoverable from CI logs (UX11).
                typer.echo(
                    f"See {html_path} for the judge's per-row rationale.",
                    err=True,
                )
        if threshold_report.timeouts:
            typer.echo(f"Timeouts: {len(threshold_report.timeouts)}", err=True)

        raise typer.Exit(threshold_report.exit_code)

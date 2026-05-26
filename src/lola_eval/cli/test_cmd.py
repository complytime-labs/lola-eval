"""`lola-eval test` -- run the eval matrix against a target repo."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1000}K"
    return str(n)


def _per_call_cost(model_id: str, cost_cfg, flat_override_usd, resolver):
    """Return ``(cost_usd, breakdown_str, source_tag)`` for a single
    agent/judge call.

    Resolution order, all upper-bound:
      1. ``--cost-per-call`` flag (``flat_override_usd``)
      2. ``cost_estimate.flat_per_call_usd`` in config
      3. ``cost_estimate.rates[<id>]`` × ``cost_estimate.tokens_per_call[<id>]``
         (inline overrides); either half falls back to the resolver
      4. ``resolver.lookup(<id>)`` — external file (if configured),
         then bundled snapshot, then fuzzy match
    """
    if flat_override_usd is not None:
        return flat_override_usd, f"--cost-per-call ${flat_override_usd:.2f}", "flag"
    if cost_cfg.flat_per_call_usd is not None:
        return (
            cost_cfg.flat_per_call_usd,
            f"flat ${cost_cfg.flat_per_call_usd:.2f} (cost_estimate.flat_per_call_usd)",
            "config-flat",
        )

    rate_override = cost_cfg.rates.get(model_id)
    tpc_override = cost_cfg.tokens_per_call.get(model_id)
    res = resolver.lookup(model_id)
    snap = res.pricing

    if rate_override is not None:
        rate_in, rate_out = rate_override.input, rate_override.output
    elif snap is not None:
        rate_in, rate_out = snap.input_per_mtok_usd, snap.output_per_mtok_usd
    else:
        return None, "no rate (set cost_estimate.rates or pricing_file)", "unknown"

    if tpc_override is not None:
        tok_in, tok_out = tpc_override.input, tpc_override.output
    elif snap is not None:
        tok_in, tok_out = snap.input_token_ceiling, snap.output_token_ceiling
    else:
        return None, "no token budget (set cost_estimate.tokens_per_call)", "unknown"

    cost = (rate_in * tok_in + rate_out * tok_out) / 1_000_000.0
    breakdown = (
        f"{_fmt_tokens(tok_in)} in × ${rate_in:.2f}/Mtok + "
        f"{_fmt_tokens(tok_out)} out × ${rate_out:.2f}/Mtok"
    )
    # The source tag carries fuzzy provenance so the caller can annotate
    # ``(≈ <matched_id>, guessed from "<query>")``. If the user pinned the
    # rate via inline override, that overrides any fuzzy match too.
    if rate_override is not None:
        tag = "inline"
    elif res.source.startswith("fuzzy-"):
        tag = f"{res.source}:{res.matched_id}"
    else:
        tag = res.source
    return cost, breakdown, tag


def _print_cost_estimate(
    cfg,
    layout,
    *,
    case_filter: str | None = None,
    profile_filter: str | None = None,
    pack_filter: str | None = None,
    flat_override_usd: float | None = None,
) -> None:
    """Print an upper-bound cost estimate for the configured matrix.

    Per-model rates and token budgets come from the bundled models.dev
    snapshot (see :mod:`lola_eval.pricing`); ``cost_estimate`` in
    ``config.yaml`` and ``--cost-per-call`` override them. Filters
    (``--case``/``--profile``/``--pack``) narrow the estimate to what
    would actually run.
    """
    tests_dir = layout.test_sets_dir
    if not tests_dir.exists():
        case_dirs: list[str] = []
    else:
        case_dirs = sorted(p.name for p in tests_dir.iterdir() if p.is_dir())
    if case_filter is not None:
        case_dirs = [c for c in case_dirs if c == case_filter]
    cases = len(case_dirs)

    target_models = sum(len(t.models) for t in cfg.targets)
    explicit_packs = list(cfg.packs) if cfg.packs is not None else ["project"]
    all_packs = (["none"] if cfg.calculate_baseline else []) + explicit_packs
    if pack_filter is not None:
        explicit_packs = [p for p in explicit_packs if p == pack_filter]
        all_packs = [p for p in all_packs if p == pack_filter]
    n_explicit_packs = len(explicit_packs)
    n_total_packs = len(all_packs)
    baseline_active = "none" in all_packs
    n_profiles = 1
    if cfg.profiles:
        profiles_path = layout.profiles_dir
        if profiles_path.exists():
            from lola_eval.profile import load_profiles

            loaded = load_profiles(profiles_path, cfg.profiles_common, cfg.profiles)
            if profile_filter is not None:
                loaded = [p for p in loaded if p.name == profile_filter]
            n_profiles = max(len(loaded), 1) if loaded else 0
    rows = target_models * n_total_packs * cases * n_profiles
    rows_per_cell = n_total_packs * cases * n_profiles

    pack_mode = "Mode 2 (external pack review)" if cfg.packs is not None else "Mode 1 (in-repo)"
    target_mode = (
        f"external → XDG ({layout.out_root})"
        if layout.is_external
        else f"in-repo → {layout.out_root}"
    )
    cells = target_models
    cost_cfg = cfg.cost_estimate

    target_cells = [(t.cli, m) for t in cfg.targets for m in t.models]
    judge_pairs = [(j.cli, j.model) for j in (cfg.judges or [])]
    unique_models = sorted({m for _, m in target_cells} | {m for _, m in judge_pairs})

    using_flat = flat_override_usd is not None or cost_cfg.flat_per_call_usd is not None

    # Build the resolver (bundled + optional external file). Path is resolved
    # relative to the eval dir; ``~`` expanded.
    from pathlib import Path as _Path

    from lola_eval import pricing

    resolver = None
    if not using_flat:
        external_path: _Path | None = None
        if cost_cfg.pricing_file:
            p = _Path(cost_cfg.pricing_file).expanduser()
            if not p.is_absolute():
                p = (layout.eval_dir / p).resolve()
            external_path = p
        resolver = pricing.Resolver(external_path=external_path)

    model_cost = {
        m: _per_call_cost(m, cost_cfg, flat_override_usd, resolver) for m in unique_models
    }
    unknown = sorted(m for m, (c, _, _) in model_cost.items() if c is None)
    name_w = max((len(m) for m in unique_models), default=0)

    print("Cost estimate (upper bound):")
    print(f"  target:    {target_mode}")
    print(f"  pack mode: {pack_mode}")
    print(f"  cases:    {cases}")
    print(f"  targets:  {len(cfg.targets)}")
    print(f"  cells:    {cells}  (cli × model)")
    print(f"  packs:    {n_explicit_packs}")
    print(f"  baseline: {'on' if baseline_active else 'off'}")
    print(f"  profiles: {n_profiles}")
    print(f"  rows:     {rows}")
    print(f"  judges:   {len(judge_pairs)}")
    print()

    # Surface load diagnostics BEFORE the per-model block so users see why a
    # column might be missing or why every model is unknown. Never raises.
    if resolver is not None:
        if resolver.bundled_diag.error:
            print(f"  ⚠ bundled snapshot: {resolver.bundled_diag.error}")
        if resolver.external_diag.error:
            print(f"  ⚠ external pricing_file: {resolver.external_diag.error}")
            print("    (falling back to bundled snapshot only)")
        if resolver.external_diag.error or resolver.bundled_diag.error:
            print()

    if using_flat:
        flat_value = flat_override_usd if flat_override_usd is not None else cost_cfg.flat_per_call_usd
        print(f"  Cost basis: flat ${flat_value:.2f}/call (no per-model lookup)")
    else:
        header_bits = []
        bundled_sha = resolver.bundled_diag.sha256 or ""
        if bundled_sha:
            header_bits.append(f"bundled {bundled_sha[:12]}…")
        if cost_cfg.pricing_file and not resolver.external_diag.error:
            header_bits.append(f"custom {cost_cfg.pricing_file}")
        header = " + ".join(header_bits) if header_bits else "no source available"
        print(f"  Per-model upper bound ({header}):")
        for mid in unique_models:
            cost, breakdown, tag = model_cost[mid]
            annotated = _render_source_tag(mid, tag)
            if cost is None:
                print(f"    {mid:<{name_w}}  $?/call    ({breakdown})")
            else:
                print(f"    {mid:<{name_w}}  ${cost:.2f}/call    {breakdown}  {annotated}")
    print()

    print(f"  Per cell (× {rows_per_cell} row{'s' if rows_per_cell != 1 else ''}):")
    grand_total = 0.0
    cell_w = max(
        (len(f"{cli}/{m}") for cli, m in target_cells),
        default=0,
    )
    for cli, model in sorted(target_cells):
        target_cost = model_cost[model][0]
        judge_costs = [model_cost[jm][0] for _, jm in judge_pairs]
        if target_cost is None or any(jc is None for jc in judge_costs):
            print(f"    {cli + '/' + model:<{cell_w}}  unknown (missing pricing)")
            continue
        sum_judges = sum(judge_costs)
        per_row = target_cost + sum_judges
        cell_total = per_row * rows_per_cell
        grand_total += cell_total
        nj = len(judge_pairs)
        if nj == 0:
            detail = f"${target_cost:.2f}"
        elif nj == 1:
            detail = f"${target_cost:.2f} + ${sum_judges:.2f}"
        else:
            detail = f"${target_cost:.2f} + ${sum_judges:.2f} ({nj} judges)"
        print(
            f"    {cli + '/' + model:<{cell_w}}  {detail} = ${per_row:.2f}/row × {rows_per_cell} = ${cell_total:.2f}"
        )

    print("  -----")
    suffix = ""
    if unknown:
        suffix = f"  (excluding unknown: {', '.join(unknown)})"
    print(f"  TOTAL:    ${grand_total:.2f}{suffix}")

    if unknown and not using_flat:
        print()
        print(f"Unknown models: {', '.join(unknown)}. Set `cost_estimate.rates.<id>`")
        print("(or point `cost_estimate.pricing_file` at your source), or pass")
        print("`--cost-per-call <usd>` for a flat estimate.")

    print()
    print("Note: upper bound assumes worst-case token usage per call (the model's")
    print("context window minus output budget). Tune `cost_estimate.tokens_per_call`")
    print("in config or use `--cost-per-call` for a flat estimate.")


def _render_source_tag(query: str, tag: str) -> str:
    """Map a resolver-source string to a user-facing annotation."""
    if tag == "bundled":
        return "[bundled]"
    if tag == "external":
        return "[custom]"
    if tag == "inline":
        return "[inline override]"
    if tag.startswith("fuzzy-bundled:"):
        matched = tag.split(":", 1)[1]
        return f'[bundled, ≈ {matched}, guessed from "{query}"]'
    if tag.startswith("fuzzy-external:"):
        matched = tag.split(":", 1)[1]
        return f'[custom, ≈ {matched}, guessed from "{query}"]'
    return ""


def _print_cost_summary(cfg, layout, since: str, n_rows: int) -> None:
    """Print total cost for rows persisted since ``since`` to stderr.

    Silent when the runs.db is missing (no rows persisted yet) or when
    every cost_usd is NULL (target CLIs that don't expose cost — e.g.
    opencode at the moment). The row count is the number of *rows the
    threshold engine saw*, not the number of priced rows; we report both
    via the message wording to keep the line meaningful even when only
    some providers reported cost.
    """
    from lola_eval.store import connect_read

    db = layout.out_root / "runs.db"
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
    sys.stderr.write(f"[lola-eval-test] total cost: ${total:.2f} across {n_rows} rows\n")


@app.command("test", rich_help_panel="Run")
def test(
    pack: str | None = typer.Option(
        None,
        "--pack",
        help="Limit to one pack_id (Mode 2 iteration aid; pass 'project' or 'none' to filter in Mode 1).",
    ),
    case: str | None = typer.Option(None, "--case", help="Limit to one task_id"),
    profile: str | None = typer.Option(None, "--profile", help="Limit to one profile name"),
    no_baseline: bool = typer.Option(
        False,
        "--no-baseline",
        help="Skip the baseline (pack_id=none) pass; no-op when calculate_baseline is false.",
    ),
    concurrency: int | None = typer.Option(
        None, "--concurrency", help="Override config concurrency"
    ),
    estimate_cost: bool = typer.Option(
        False,
        "--estimate-cost",
        help="Print upper-bound cost for the configured matrix; do not run.",
    ),
    cost_per_call: float | None = typer.Option(
        None,
        "--cost-per-call",
        help="Flat USD/call override for --estimate-cost; skips per-model lookup.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default: ./.lola-eval/config.yaml)",
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Force the out-root (default: .lola-eval/out, or XDG for external targets)"
    ),
) -> None:
    """Run the configured eval matrix and emit pass/fail + artifacts."""
    from lola_eval.config import load_config, ConfigError
    from lola_eval.threshold import ThresholdEngine, BaselineMissing
    from lola_eval.ci import write_junit_xml, write_github_summary
    from lola_eval import runner, report as report_mod
    from lola_eval.runner import RunnerError
    from lola_eval.cli import _resolve_layout_or_exit

    layout = _resolve_layout_or_exit(config, out)
    try:
        cfg = load_config(layout.config_path)
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2)

    from lola_eval.model_alias import alias_drift_warnings

    for _warning in alias_drift_warnings(cfg):
        typer.echo(f"⚠ {_warning}", err=True)

    if estimate_cost:
        _print_cost_estimate(
            cfg,
            layout,
            case_filter=case,
            profile_filter=profile,
            pack_filter=pack,
            flat_override_usd=cost_per_call,
        )
        raise typer.Exit(0)

    # Centralize the env-var mutation: one hook drives every downstream
    # consumer (runner subprocess, build_html, drift/lift readers).
    # Scoped via context manager so consecutive in-process CLI invocations
    # don't leak LOLA_RESULTS_DIR across boundaries (I11).
    with _activate_target_env(layout):
        # Mark when this invocation started so we can scope the cost
        # rollup below to rows written by this run only. Truncating to
        # seconds matches the format trajectory_judge uses for the
        # ``timestamp`` column, so an inclusive >= filter is correct.
        run_started_at = (
            datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        )
        try:
            rows = runner.run_matrix(
                cfg,
                layout,
                pack_filter=pack,
                case_filter=case,
                no_baseline=no_baseline,
                concurrency=concurrency,
                profile_filter=profile,
            )
        except (FileNotFoundError, ValueError, RunnerError) as e:
            # FileNotFoundError: missing test_sets/ dir or fixture file.
            # ValueError: malformed rubric (no frontmatter) or unknown target cli.
            # RunnerError: empty matrix after filters.
            # All three are user-facing setup errors -- no traceback.
            typer.echo(f"setup error: {e}", err=True)
            raise typer.Exit(2)

        results_dir = layout.out_root
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
                if (
                    r.judge_disagreement is not None
                    and r.judge_disagreement > cfg.disagreement_threshold
                ):
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
        target_mode = (
            f"external (XDG: {layout.out_root})"
            if layout.is_external
            else f"in-repo ({layout.out_root})"
        )
        sys.stderr.write(f"[lola-eval-test] target: {target_mode}\n")
        sys.stderr.write(
            f"[lola-eval-test] {n_rows} rows complete; "
            f"{n_failures} failures; {n_timeouts} timeouts\n"
        )
        _print_cost_summary(cfg, layout, run_started_at, n_rows)
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

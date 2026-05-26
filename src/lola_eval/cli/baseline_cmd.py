"""`lola-eval baseline {update,show,diff}` -- baseline management subcommands."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from lola_eval.cli import app

baseline_app = typer.Typer(
    name="baseline",
    help="Inspect and update the regression baseline.",
    no_args_is_help=True,
)
app.add_typer(baseline_app, name="baseline")

_CONFIG_OPT = typer.Option(
    None,
    "--config",
    help="Path to config.yaml (default: ./.lola-eval/config.yaml)",
)


def _load_layout_and_cfg(config: Path | None):
    from lola_eval.config import load_config, ConfigError
    from lola_eval.cli import _resolve_layout_or_exit

    layout = _resolve_layout_or_exit(config)
    try:
        cfg = load_config(layout.config_path)
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2)
    return cfg, layout


def _last_run_path(layout) -> Path:
    return layout.out_root / "last-run.json"


def _baseline_path(layout) -> Path:
    return layout.baseline_path


def _last_run_to_baseline(rows: list[dict]) -> dict:
    """Convert a last-run.json list into a baseline keyed by cell."""
    return {
        f"{r['cli']}/{r['model']}/{r['task_id']}/{r['pack_id']}": {
            "composite": r["composite"],
            "rubric_pass_threshold": r["rubric_pass_threshold"],
        }
        for r in rows
    }


@baseline_app.command("update")
def update(config: Path | None = _CONFIG_OPT) -> None:
    """Promote the most recent run's results to baseline.json."""
    cfg, layout = _load_layout_and_cfg(config)
    last = _last_run_path(layout)
    if not last.exists():
        typer.echo(f"no last-run.json at {last}; run `lola-eval test` first", err=True)
        raise typer.Exit(2)
    rows = json.loads(last.read_text())
    baseline = _last_run_to_baseline(rows)
    out = _baseline_path(layout)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    typer.echo(f"wrote {out} ({len(baseline)} rows)")


@baseline_app.command("show")
def show(config: Path | None = _CONFIG_OPT) -> None:
    """Print the current baseline.json."""
    cfg, layout = _load_layout_and_cfg(config)
    bp = _baseline_path(layout)
    if not bp.exists():
        typer.echo(f"no baseline at {bp}", err=True)
        typer.echo(
            "(create one by running `lola-eval test` followed by `lola-eval baseline update`)",
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(bp.read_text())


@baseline_app.command("diff")
def diff(config: Path | None = _CONFIG_OPT) -> None:
    """Show last-run.json composites vs current baseline.json."""
    cfg, layout = _load_layout_and_cfg(config)
    bp = _baseline_path(layout)
    last = _last_run_path(layout)
    if not bp.exists():
        typer.echo(f"no baseline at {bp}", err=True)
        typer.echo(
            "(diff compares last-run.json composites to baseline.json — create the baseline first with `lola-eval baseline update`)",
            err=True,
        )
        raise typer.Exit(1)
    if not last.exists():
        typer.echo(f"no last-run at {last}", err=True)
        typer.echo("(run `lola-eval test` first to populate last-run.json)", err=True)
        raise typer.Exit(1)
    baseline = json.loads(bp.read_text())
    rows = json.loads(last.read_text())
    typer.echo(f"{'cell':<60} {'baseline':>10} {'last':>10} {'delta':>10}")
    for r in rows:
        key = f"{r['cli']}/{r['model']}/{r['task_id']}/{r['pack_id']}"
        b = baseline.get(key)
        if b is None:
            typer.echo(f"{key:<60} {'-':>10} {r['composite']:>10.3f} {'(new)':>10}")
            continue
        delta = r["composite"] - float(b["composite"])
        typer.echo(
            f"{key:<60} {float(b['composite']):>10.3f} {r['composite']:>10.3f} {delta:>+10.3f}"
        )

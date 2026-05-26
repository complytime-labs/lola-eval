"""`lola-eval drift` -- print signed drift Δ table."""

from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("drift")
def drift(
    fingerprint: str | None = typer.Option(None, help="Limit to one fingerprint"),
    threshold_fail: float | None = typer.Option(
        None,
        "--threshold-fail",
        help="Exit non-zero if any drift Δ < this value (e.g. -0.10)",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default discovered in cwd; standalone XDG fallback if absent)",
    ),
) -> None:
    """Print signed drift Δ table; optionally fail on regression."""
    from lola_eval.layout import resolve as resolve_layout

    try:
        layout = resolve_layout(config_opt=config, out_opt=None)
    except FileNotFoundError:
        layout = None
    with _activate_target_env(layout):
        from lola_eval.report import print_drift

        raise typer.Exit(print_drift(fingerprint=fingerprint, threshold_fail=threshold_fail))

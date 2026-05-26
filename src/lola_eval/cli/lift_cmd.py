"""`lola-eval lift` -- print signed lift % table."""

from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("lift")
def lift(
    threshold_fail: float | None = typer.Option(
        None,
        "--threshold-fail",
        help="Exit non-zero if any lift % < this value (e.g. -10.0)",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default discovered in cwd; standalone XDG fallback if absent)",
    ),
) -> None:
    """Print signed lift % table; optionally fail on regression."""
    from lola_eval.layout import resolve as resolve_layout

    try:
        layout = resolve_layout(config_opt=config, out_opt=None)
    except FileNotFoundError:
        layout = None
    with _activate_target_env(layout):
        from lola_eval.report import print_lift

        raise typer.Exit(print_lift(threshold_fail=threshold_fail))

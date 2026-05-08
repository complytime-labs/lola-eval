"""`lola-eval compare` -- baseline-vs-pack comparison."""
from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("compare")
def compare(
    threshold_fail: float | None = typer.Option(
        None, "--threshold-fail",
        help="Exit non-zero if any composite lift % < this value (e.g. -10.0)",
    ),
    config: Path | None = typer.Option(
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)",
    ),
) -> None:
    """Print exhaustive baseline-vs-pack comparison per (cli, model, task)."""
    with _activate_target_env(config):
        from lola_eval.compare import print_compare
        raise typer.Exit(print_compare(threshold_fail=threshold_fail))

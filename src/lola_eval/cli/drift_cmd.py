"""`lola-eval drift` -- print signed drift Δ table."""
from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("drift")
def drift(
    fingerprint: str | None = typer.Option(None, help="Limit to one fingerprint"),
    threshold_fail: float | None = typer.Option(
        None, "--threshold-fail",
        help="Exit non-zero if any drift Δ < this value (e.g. -0.10)",
    ),
    config: Path | None = typer.Option(
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)",
    ),
) -> None:
    """Print signed drift Δ table; optionally fail on regression."""
    with _activate_target_env(config):
        from lola_eval.report import print_drift
        raise typer.Exit(print_drift(fingerprint=fingerprint, threshold_fail=threshold_fail))

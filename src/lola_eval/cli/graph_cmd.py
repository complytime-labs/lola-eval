"""`lola-eval graph` -- time-series chart of composite over runs."""
from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("graph")
def graph(
    cell: str | None = typer.Option(None, "--cell", help="cli/model/task_id; omit for all"),
    config: Path | None = typer.Option(
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)",
    ),
) -> None:
    """Print time-series chart of composite over runs (CLI-friendly)."""
    with _activate_target_env(config):
        from lola_eval.graph import print_graph
        raise typer.Exit(print_graph(cell=cell))

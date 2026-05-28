"""`lola-eval graph` -- time-series chart of composite over runs."""

from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("graph", rich_help_panel="Inspect")
def graph(
    cell: str | None = typer.Option(None, "--cell", help="cli/model/task_id; omit for all"),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default discovered in cwd; standalone XDG fallback if absent)",
    ),
) -> None:
    """Print time-series chart of composite over runs (CLI-friendly)."""
    from lola_eval.layout import resolve as resolve_layout

    try:
        layout = resolve_layout(config_opt=config, out_opt=None)
    except FileNotFoundError:
        layout = None
    with _activate_target_env(layout):
        from lola_eval.graph import print_graph

        raise typer.Exit(print_graph(cell=cell))

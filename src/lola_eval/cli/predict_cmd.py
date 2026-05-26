"""Standalone cost-prediction command: what-if estimates without
running the harness."""

from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _resolve_layout_or_exit


@app.command("predict", rich_help_panel="Estimation")
def predict_command(
    config: Path = typer.Option(
        None, "--config", "-c", help="Path to .lola-eval/config.yaml"
    ),
):
    """Print three-tier cost estimates for every cell, with --predict
    enabled (kNN bridges the gap between calibrated and static
    pricing). Equivalent to `lola-eval test --estimate-cost --predict`
    but skips the test machinery."""
    from lola_eval.config import load_config, ConfigError
    from lola_eval.cli.test_cmd import _print_cost_estimate

    layout = _resolve_layout_or_exit(config)
    try:
        cfg = load_config(layout.config_path)
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2)

    _print_cost_estimate(cfg, layout, predict=True)

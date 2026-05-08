"""`lola-eval clean` -- wipe regenerable cache or destructive state."""
from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app


@app.command("clean")
def clean(
    cache: bool = typer.Option(False, "--cache", help="Wipe regenerable workspace/transcripts/reports"),
    state: bool = typer.Option(False, "--state", help="Wipe runs.db + last-run.json (DESTRUCTIVE; baseline.json preserved)"),
    config: Path | None = typer.Option(
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)",
    ),
) -> None:
    """Wipe regenerable cache or destructive state directories.

    When invoked inside a target repo (cwd contains ``lola-eval.yaml``,
    or ``--config`` is supplied), wipes operate on
    ``<target>/.lola-eval/`` per the embeddable-runner pivot. Outside a
    target repo, falls back to the XDG cache / state roots so existing
    standalone usage keeps working.
    """
    if not cache and not state:
        # Reject the no-op invocation. Silently exiting 0 with no output
        # convinces users they cleaned something when they didn't.
        typer.echo(
            "clean: specify --cache and/or --state. "
            "Run 'lola-eval clean --help' for details.",
            err=True,
        )
        raise typer.Exit(2)
    from lola_eval.doctor import clean_dirs
    cfg_path = config if config is not None else (Path.cwd() / "lola-eval.yaml")
    target_results_dir = None
    if cfg_path.exists():
        from lola_eval.config import load_config, ConfigError
        try:
            cfg = load_config(cfg_path)
        except ConfigError as e:
            typer.echo(f"config error: {e}", err=True)
            raise typer.Exit(2)
        target_root = cfg_path.parent.resolve()
        target_results_dir = target_root / cfg.results_dir
    clean_dirs(cache=cache, state=state, target_results_dir=target_results_dir)

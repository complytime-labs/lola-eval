"""`lola-eval clean` -- wipe regenerable cache or destructive state."""

from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app


@app.command("clean")
def clean(
    cache: bool = typer.Option(
        False, "--cache", help="Wipe regenerable workspace/transcripts/reports"
    ),
    state: bool = typer.Option(
        False, "--state", help="Wipe runs.db + last-run.json (DESTRUCTIVE; baseline.json preserved)"
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config.yaml (default: ./.lola-eval/config.yaml)",
    ),
) -> None:
    """Wipe regenerable cache or destructive state directories.

    When invoked inside a target repo (cwd contains ``.lola-eval/config.yaml``,
    or ``--config`` is supplied), wipes operate on ``<eval_dir>/out/``.
    """
    if not cache and not state:
        # Reject the no-op invocation. Silently exiting 0 with no output
        # convinces users they cleaned something when they didn't.
        typer.echo(
            "clean: specify --cache and/or --state. Run 'lola-eval clean --help' for details.",
            err=True,
        )
        raise typer.Exit(2)
    from lola_eval.doctor import clean_dirs
    from lola_eval.cli import _resolve_layout_or_exit

    layout = _resolve_layout_or_exit(config)
    target_out = layout.out_root
    clean_dirs(cache=cache, state=state, target_results_dir=target_out)
    if cache and (target_out / "staging").exists():
        import shutil

        shutil.rmtree(target_out / "staging")
        typer.echo(f"cleaned staging dir: {target_out / 'staging'}")

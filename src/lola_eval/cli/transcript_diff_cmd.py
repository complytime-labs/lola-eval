"""`lola-eval transcript-diff` -- semantic diff of two runs by run_id.

Compares persisted structured outputs (scores, exit_status, counters),
not raw transcript text. Despite the name (which mirrors the original
feature request), the diff is over stored run data, which is robust and
format-independent.
"""

from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("transcript-diff")
def transcript_diff(
    run_a: str = typer.Argument(..., help="First run_id"),
    run_b: str = typer.Argument(..., help="Second run_id"),
    config: Path | None = typer.Option(
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)"
    ),
) -> None:
    """Diff two runs' structured outputs (scores, exit_status, counters)."""
    with _activate_target_env(config):
        from lola_eval import store, xdg
        from lola_eval.run_diff import build_run_diff

        db = xdg.resolve_db_path()
        if not db.exists():
            typer.echo(f"no runs.db at {db}", err=True)
            raise typer.Exit(1)
        row_a = store.fetch_by_run_id(db, run_a)
        row_b = store.fetch_by_run_id(db, run_b)
    missing = [rid for rid, row in ((run_a, row_a), (run_b, row_b)) if row is None]
    if missing:
        typer.echo(f"run_id not found: {', '.join(missing)}", err=True)
        raise typer.Exit(1)
    typer.echo(build_run_diff(row_a, row_b))

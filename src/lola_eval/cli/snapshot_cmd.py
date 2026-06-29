"""`lola-eval snapshot` -- append eval history to the committed ledger."""

from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env, _resolve_layout_or_exit


@app.command("snapshot", rich_help_panel="Inspect")
def snapshot(
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Ledger directory (default: the eval dir, committed alongside config.yaml)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would be appended; write nothing"
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default: ./.lola-eval/config.yaml)",
    ),
) -> None:
    """Capture runs not yet recorded in the committed history ledger.

    Appends one JSONL line per cell to ``<eval_dir>/ledger.jsonl`` and writes
    a markdown snapshot to ``<eval_dir>/snapshots/<id>.md``. Runs already in
    the ledger (matched by run_id) are skipped, so re-running is idempotent —
    the ledger itself is the high-water mark. Unlike ``out/`` artifacts,
    these files are meant to be committed.
    """
    layout = _resolve_layout_or_exit(config)
    with _activate_target_env(layout):
        from lola_eval import xdg
        from lola_eval.snapshot import write_snapshot

        db = xdg.resolve_db_path()
        if not db.exists():
            typer.echo(
                f"no runs.db at {db}; nothing to snapshot. Run `lola-eval test` first.",
                err=True,
            )
            raise typer.Exit(2)

        ledger_dir = out if out is not None else layout.eval_dir
        try:
            result = write_snapshot(ledger_dir, db, dry_run=dry_run)
        except ValueError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(2)

        if result["appended"] == 0:
            typer.echo("nothing to snapshot (ledger is up to date)")
            return
        if dry_run:
            typer.echo(
                f"would append {result['appended']} cell(s) "
                f"from {len(result['run_ids'])} run(s) to {result['ledger']}:"
            )
            for rid in result["run_ids"]:
                typer.echo(f"  {rid}")
            return
        typer.echo(f"appended {result['appended']} cell(s) to {result['ledger']}")
        typer.echo(f"wrote {result['markdown']}")

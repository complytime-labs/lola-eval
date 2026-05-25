"""`lola-eval export` -- export runs.db history as JSON or CSV."""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("export")
def export(
    task: str | None = typer.Option(None, "--task", help="Filter to one task_id"),
    since: str | None = typer.Option(
        None, "--since", help="Only runs with timestamp >= this ISO8601 value"
    ),
    fingerprint: str | None = typer.Option(None, "--fingerprint", help="Filter to one fingerprint"),
    fmt: str = typer.Option("json", "--format", help="Output format: json or csv"),
    out: Path | None = typer.Option(None, "--out", help="Write to file (default: stdout)"),
    include_diff: bool = typer.Option(
        False, "--include-diff", help="Include the workdir_diff column"
    ),
    include_paths: bool = typer.Option(
        False, "--include-paths", help="Include the transcript_path column"
    ),
    config: Path | None = typer.Option(
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)"
    ),
) -> None:
    """Export historical runs from runs.db (all matching rows, not just the last run)."""
    if fmt not in ("json", "csv"):
        typer.echo(f"unknown --format '{fmt}' (expected json or csv)", err=True)
        raise typer.Exit(2)
    with _activate_target_env(config):
        from lola_eval import store, xdg

        db = xdg.resolve_db_path()
        if not db.exists():
            typer.echo(f"no runs.db at {db}", err=True)
            raise typer.Exit(1)
        rows = store.export_rows(
            db,
            task=task,
            since=since,
            fingerprint=fingerprint,
            include_diff=include_diff,
            include_paths=include_paths,
        )
    if not rows:
        typer.echo("no runs matched the given filters", err=True)
        raise typer.Exit(0)

    if fmt == "json":
        text = json.dumps(rows, indent=2) + "\n"
    else:
        buf = io.StringIO()
        # Union of keys preserves the first row's column order, then appends
        # any columns only later rows have (rows are uniform in practice).
        fieldnames = list(rows[0].keys())
        for r in rows:
            for k in r:
                if k not in fieldnames:
                    fieldnames.append(k)
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        text = buf.getvalue()

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        typer.echo(f"wrote {len(rows)} rows to {out}", err=True)
    else:
        sys.stdout.write(text)

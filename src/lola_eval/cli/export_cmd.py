"""`lola-eval export` -- export runs.db history as JSON or CSV."""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("export", rich_help_panel="Inspect")
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
    bundle: bool = typer.Option(
        False,
        "--bundle",
        help="Package DB rows + transcripts + diffs + reports into a portable .tar.gz",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default discovered in cwd; standalone XDG fallback if absent)",
    ),
) -> None:
    """Export historical runs from runs.db (all matching rows, not just the last run)."""
    if not bundle and fmt not in ("json", "csv"):
        typer.echo(f"unknown --format '{fmt}' (expected json or csv)", err=True)
        raise typer.Exit(2)
    from lola_eval.layout import resolve as resolve_layout

    try:
        layout = resolve_layout(config_opt=config, out_opt=None)
    except FileNotFoundError:
        layout = None
    with _activate_target_env(layout):
        from lola_eval import store, xdg

        db = xdg.resolve_db_path()
        if not db.exists():
            typer.echo(f"no runs.db at {db}", err=True)
            raise typer.Exit(1)
        if bundle:
            rows = store.export_rows(
                db,
                task=task,
                since=since,
                fingerprint=fingerprint,
                include_diff=True,
                include_paths=True,
            )
            if not rows:
                typer.echo("no runs matched the given filters", err=True)
                raise typer.Exit(0)
            from datetime import datetime, timezone

            from lola_eval import __version__
            from lola_eval import bundle as bundle_mod

            out_path = out if out is not None else Path("evidence-bundle.tar.gz")
            reports = xdg.reports_dir()
            bundle_mod.build_bundle(
                out_path=out_path,
                db_path=db,
                rows=rows,
                reports_dir=reports if reports.is_dir() else None,
                lola_eval_version=__version__,
                generated_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            )
            typer.echo(f"wrote bundle with {len(rows)} rows to {out_path}", err=True)
            return
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

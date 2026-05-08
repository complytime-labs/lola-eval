"""`lola-eval report` -- build HTML drift report."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("report")
def report(
    out: str = typer.Option(None, "--out", help="Output file path (.html)"),
    config: Path | None = typer.Option(
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)",
    ),
) -> None:
    """Build HTML drift report for the latest run.

    When invoked from inside a target repo (cwd contains lola-eval.yaml,
    or ``--config`` is supplied) and ``--out`` is omitted, writes to
    ``<target>/.lola-eval/reports/<timestamp>.html``. Outside a target
    repo, falls back to the XDG state directory for Phase-1 standalone
    usage.
    """
    with _activate_target_env(config) as cfg_path:
        from lola_eval import xdg
        from lola_eval.report import build_html

        # Refuse to write an empty report when there is no data — running
        # `lola-eval report` against a fresh target before any test has
        # populated runs.db would otherwise emit a placeholder HTML file
        # and exit 0, which CI consumers misread as "report succeeded".
        # This check is target-aware: we resolve the same db path the
        # report builder will read from.
        db = xdg.resolve_db_path()
        if not db.exists():
            typer.echo(
                f"no runs.db at {db}; nothing to report. "
                f"Run `lola-eval test` first.",
                err=True,
            )
            raise typer.Exit(2)

        out_path: Path | None = None
        if out is not None:
            out_path = Path(out)
        elif cfg_path is not None:
            from lola_eval.config import load_config
            cfg = load_config(cfg_path)
            target_root = cfg_path.parent.resolve()
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out_path = xdg.reports_dir_for_target(target_root, cfg) / f"{ts}.html"
        build_html(out_path=out_path)

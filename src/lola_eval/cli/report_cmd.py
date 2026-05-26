"""`lola-eval report` -- build HTML drift report."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from lola_eval.cli import app, _activate_target_env


@app.command("report")
def report(
    out: str = typer.Option(None, "--out", help="Output file path"),
    format: str = typer.Option("html", "--format", help="Output format: html, markdown, json"),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to lola-eval.yaml (default: ./lola-eval.yaml)",
    ),
) -> None:
    """Build HTML drift report for the latest run.

    When invoked from inside a target repo (cwd contains .lola-eval/config.yaml,
    or ``--config`` is supplied) and ``--out`` is omitted, writes to
    ``<eval_dir>/out/reports/<timestamp>.html``. Outside a target
    repo, falls back to the XDG state directory for Phase-1 standalone
    usage.
    """
    from lola_eval.layout import resolve as resolve_layout

    try:
        layout = resolve_layout(config_opt=config, out_opt=None)
    except FileNotFoundError:
        layout = None

    with _activate_target_env(layout):
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
                f"no runs.db at {db}; nothing to report. Run `lola-eval test` first.",
                err=True,
            )
            raise typer.Exit(2)

        out_path: Path | None = None
        if out is not None:
            out_path = Path(out)
        elif layout is not None:
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            reports_dir = layout.out_root / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            out_path = reports_dir / f"{ts}.html"

        if format == "markdown":
            from lola_eval.markdown_report import build_markdown

            results_dir = layout.out_root if layout is not None else None
            build_markdown(out_path=Path(out) if out else None, results_dir=results_dir)
        elif format == "json":
            from lola_eval.markdown_report import build_json

            results_dir = layout.out_root if layout is not None else None
            build_json(out_path=Path(out) if out else None, results_dir=results_dir)
        else:
            build_html(out_path=out_path)

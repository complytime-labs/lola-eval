"""`lola-eval profile-compare` -- compare composites across installed-skill
profiles and flag skill conflicts."""
from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app, _resolve_layout_or_exit


@app.command("profile-compare", rich_help_panel="Inspect")
def profile_compare(
    case: str | None = typer.Option(None, "--case", help="Limit to one task_id"),
    since: str | None = typer.Option(
        None, "--since", help="Only runs with timestamp >= this ISO8601 value"
    ),
    tolerance: float = typer.Option(
        0.05, "--tolerance",
        help="A superset profile scoring more than this below a subset flags a conflict",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default: ./.lola-eval/config.yaml)",
    ),
) -> None:
    """Compare composites across installed-skill profiles and flag conflicts.

    A conflict is a profile whose installed skills are a superset of another's
    yet whose composite is lower -- i.e. adding a skill degraded the agent.
    """
    layout = _resolve_layout_or_exit(config)

    from lola_eval.config import load_config, ConfigError
    from lola_eval import profile_compare as pc

    try:
        cfg = load_config(layout.config_path)
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2)

    db = layout.out_root / "runs.db"
    if not db.exists():
        typer.echo(f"no runs.db at {db}; run `lola-eval test` first.", err=True)
        raise typer.Exit(2)

    skillsets = pc.load_profile_skillsets(cfg, layout)
    composites = pc.gather_composites(db, case=case, since=since)
    conflicts = pc.detect_conflicts(skillsets, composites, tolerance)
    typer.echo(pc.render(skillsets, composites, conflicts))

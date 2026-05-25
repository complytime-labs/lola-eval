"""`lola-eval profile-compare` -- compare composites across installed-skill
profiles and flag skill conflicts."""
from __future__ import annotations

from pathlib import Path

import typer

from lola_eval.cli import app


@app.command("profile-compare")
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
        None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)"
    ),
) -> None:
    """Compare composites across installed-skill profiles and flag conflicts.

    A conflict is a profile whose installed skills are a superset of another's
    yet whose composite is lower -- i.e. adding a skill degraded the agent.
    """
    cfg_path = (config if config is not None else (Path.cwd() / "lola-eval.yaml")).resolve()
    if not cfg_path.exists():
        typer.echo(f"config not found: {cfg_path}", err=True)
        raise typer.Exit(2)

    from lola_eval.config import load_config, ConfigError
    from lola_eval import xdg, profile_compare as pc

    try:
        cfg = load_config(cfg_path)
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2)
    target_root = cfg_path.parent.resolve()
    db = xdg.db_path_for_target(target_root, cfg)
    if not db.exists():
        typer.echo(f"no runs.db at {db}; run `lola-eval test` first.", err=True)
        raise typer.Exit(2)

    skillsets = pc.load_profile_skillsets(cfg, target_root)
    composites = pc.gather_composites(db, case=case, since=since)
    conflicts = pc.detect_conflicts(skillsets, composites, tolerance)
    typer.echo(pc.render(skillsets, composites, conflicts))

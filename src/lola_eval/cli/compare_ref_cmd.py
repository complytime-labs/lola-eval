"""`lola-eval compare-ref` -- eval at two git refs and diff (non-destructive)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from lola_eval.cli import app


@app.command("compare-ref")
def compare_ref(
    ref_a: str = typer.Argument(..., help="First git ref (e.g. main or a SHA)"),
    ref_b: str = typer.Argument(..., help="Second git ref (e.g. HEAD)"),
    case: str | None = typer.Option(None, "--case", help="Limit to one task_id"),
    concurrency: int | None = typer.Option(None, "--concurrency", help="Override config concurrency"),
    config: Path | None = typer.Option(None, "--config", help="Path to lola-eval.yaml (default: ./lola-eval.yaml)"),
) -> None:
    """Evaluate the repo at two refs (via git worktrees) and diff per-cell composites.

    Runs the full matrix twice -- once per ref -- against real agent CLIs.
    Non-destructive: the current branch and working tree are untouched.
    """
    cfg_path = (config if config is not None else (Path.cwd() / "lola-eval.yaml")).resolve()
    if not cfg_path.exists():
        typer.echo(f"config not found: {cfg_path}", err=True)
        raise typer.Exit(2)
    top = subprocess.run(
        ["git", "-C", str(cfg_path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if top.returncode != 0:
        typer.echo(f"not a git repository: {cfg_path.parent} ({top.stderr.strip()[:200]})", err=True)
        raise typer.Exit(2)
    repo_root = Path(top.stdout.strip())
    try:
        config_rel = cfg_path.relative_to(repo_root)
    except ValueError:
        typer.echo(f"config {cfg_path} is not under the git repo {repo_root}", err=True)
        raise typer.Exit(2)

    # Unlike other run-invoking commands, compare-ref deliberately does NOT
    # use _activate_target_env: each ref is evaluated inside its own git
    # worktree, where the runner scopes LOLA_RESULTS_DIR to that worktree's
    # .lola-eval on a subprocess env copy. The caller's results dir is never
    # the target, so there is nothing to activate here.
    from lola_eval.compare_ref import compare_refs, CompareRefError
    try:
        text = compare_refs(
            repo_root, ref_a, ref_b, str(config_rel),
            case_filter=case, concurrency=concurrency,
        )
    except CompareRefError as e:
        typer.echo(f"compare-ref failed: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(text)

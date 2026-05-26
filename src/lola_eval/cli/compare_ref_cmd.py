"""`lola-eval compare-ref` -- eval at two git refs and diff (non-destructive)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from lola_eval.cli import app, _resolve_layout_or_exit


@app.command("compare-ref", rich_help_panel="Inspect")
def compare_ref(
    ref_a: str = typer.Argument(..., help="First git ref (e.g. main or a SHA)"),
    ref_b: str = typer.Argument(..., help="Second git ref (e.g. HEAD)"),
    case: str | None = typer.Option(None, "--case", help="Limit to one task_id"),
    concurrency: int | None = typer.Option(
        None, "--concurrency", help="Override config concurrency"
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default: ./.lola-eval/config.yaml)",
    ),
) -> None:
    """Evaluate the repo at two refs (via git worktrees) and diff per-cell composites.

    Runs the full matrix twice -- once per ref -- against real agent CLIs.
    Non-destructive: the current branch and working tree are untouched.
    """
    layout = _resolve_layout_or_exit(config)

    top = subprocess.run(
        ["git", "-C", str(layout.project_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if top.returncode != 0:
        typer.echo(
            f"not a git repository: {layout.project_root} ({top.stderr.strip()[:200]})",
            err=True,
        )
        raise typer.Exit(2)
    repo_root = Path(top.stdout.strip())
    try:
        config_rel = layout.config_path.relative_to(repo_root)
    except ValueError:
        typer.echo(
            f"config {layout.config_path} is not under the git repo {repo_root}", err=True
        )
        raise typer.Exit(2)

    # Unlike other run-invoking commands, compare-ref deliberately does NOT
    # use _activate_target_env: each ref is evaluated inside its own git
    # worktree, where the runner scopes LOLA_RESULTS_DIR to that worktree's
    # .lola-eval on a subprocess env copy. The caller's results dir is never
    # the target, so there is nothing to activate here.
    from lola_eval.compare_ref import compare_refs, CompareRefError

    try:
        text = compare_refs(
            repo_root,
            ref_a,
            ref_b,
            str(config_rel),
            case_filter=case,
            concurrency=concurrency,
        )
    except CompareRefError as e:
        typer.echo(f"compare-ref failed: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(text)

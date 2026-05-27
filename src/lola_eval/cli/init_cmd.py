"""`lola-eval init` -- scaffold .lola-eval/ with config + example test in a target repo."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import typer

from lola_eval.cli import app

GITIGNORE_LINES = [".lola-eval/out/"]


def _append_gitignore(target: Path) -> list[str]:
    """Add lola-eval entries to .gitignore idempotently.

    If the file does not exist, create it with the entries. If it exists,
    append only the entries not already present (compared line-stripped).

    Returns the list of lines actually appended (empty if the file was
    already up-to-date) so the caller can show the user what changed.
    """
    gi = target / ".gitignore"
    existing: set[str] = set()
    if gi.exists():
        existing = {ln.strip() for ln in gi.read_text().splitlines() if ln.strip()}
    new = [ln for ln in GITIGNORE_LINES if ln not in existing]
    if not new:
        return []
    # When creating the file from scratch, prepend a section comment so the
    # entries are self-explanatory. Include it in the returned list so the
    # caller's "appended N line(s)" message matches what landed on disk.
    appended = ["# lola-eval results", *new] if not gi.exists() else new
    if gi.exists() and not gi.read_text().endswith("\n"):
        appended = ["", *appended]
    block = "\n".join(appended) + "\n"
    if gi.exists():
        with gi.open("a", encoding="utf-8") as f:
            f.write(block)
    else:
        gi.write_text(block)
    return [ln for ln in appended if ln]


def _copy_resource_tree(src, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            _copy_resource_tree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())


@app.command("init", rich_help_panel="Setup")
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing .lola-eval/config.yaml"),
) -> None:
    """Scaffold a .lola-eval/ directory with config + example test in the current directory."""
    target = Path.cwd()
    eval_dir = target / ".lola-eval"
    cfg_path = eval_dir / "config.yaml"
    template_root = files("lola_eval").joinpath("_data").joinpath("init_template")

    if cfg_path.exists() and not force:
        typer.echo(f"refusing to overwrite {cfg_path}; pass --force to override", err=True)
        # Exit 2 = setup error per the spec.
        raise typer.Exit(2)
    eval_dir.mkdir(parents=True, exist_ok=True)
    cfg_template = template_root.joinpath("config.yaml").read_text(encoding="utf-8")
    cfg_path.write_text(cfg_template, encoding="utf-8")
    typer.echo(f"wrote {cfg_path}")

    test_sets = eval_dir / "test_sets"
    if not test_sets.exists() or not any(test_sets.iterdir()):
        example_src = template_root.joinpath("test_sets").joinpath("example")
        example_dst = test_sets / "example"
        _copy_resource_tree(example_src, example_dst)
        typer.echo(f"wrote example test at {example_dst}")
    else:
        typer.echo(f"{test_sets} already populated; skipping example copy")

    appended = _append_gitignore(target)
    gi_path = target / ".gitignore"
    if appended:
        typer.echo(f"appended {len(appended)} line(s) to {gi_path}:")
        for ln in appended:
            typer.echo(f"  {ln}")
    else:
        typer.echo(f"{gi_path} already contains all lola-eval entries; no changes")

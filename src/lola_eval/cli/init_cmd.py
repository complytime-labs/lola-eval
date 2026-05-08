"""`lola-eval init` -- scaffold lola-eval.yaml + example test in a target repo."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import typer

from lola_eval.cli import app

GITIGNORE_LINES = [
    ".lola-eval/runs.db",
    ".lola-eval/transcripts/",
    ".lola-eval/reports/",
    ".lola-eval/junit.xml",
    ".lola-eval/workspace/",
]


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
    block = "\n".join(new)
    if gi.exists() and not gi.read_text().endswith("\n"):
        block = "\n" + block
    if not gi.exists():
        gi.write_text("# lola-eval results\n" + block + "\n")
    else:
        with gi.open("a", encoding="utf-8") as f:
            f.write(block + "\n")
    return new


def _copy_resource_tree(src, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            _copy_resource_tree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())


@app.command("init")
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing lola-eval.yaml"),
) -> None:
    """Scaffold a lola-eval.yaml + example test in the current directory."""
    target = Path.cwd()
    cfg_path = target / "lola-eval.yaml"
    examples_root = files("lola_eval").joinpath("_data").joinpath("examples")

    if cfg_path.exists() and not force:
        typer.echo(f"refusing to overwrite {cfg_path}; pass --force to override", err=True)
        # Exit code 2 = setup error (per the spec's exit-code precedence:
        # 2 > 3 > 1 > 0). An existing config without --force is a setup
        # problem the user must resolve, not a threshold-style failure.
        raise typer.Exit(2)
    cfg_template = examples_root.joinpath("lola-eval.yaml").read_text(encoding="utf-8")
    cfg_path.write_text(cfg_template, encoding="utf-8")
    typer.echo(f"wrote {cfg_path}")

    tests_dir = target / "tests" / "lola-eval"
    if not tests_dir.exists() or not any(tests_dir.iterdir()):
        tests_dir.mkdir(parents=True, exist_ok=True)
        example_src = examples_root.joinpath("tests").joinpath("lola-eval").joinpath("example")
        example_dst = tests_dir / "example"
        _copy_resource_tree(example_src, example_dst)
        typer.echo(f"wrote example test at {example_dst}")
    else:
        typer.echo(f"{tests_dir} already populated; skipping example copy")

    appended = _append_gitignore(target)
    gi_path = target / ".gitignore"
    if appended:
        typer.echo(f"appended {len(appended)} line(s) to {gi_path}:")
        for ln in appended:
            typer.echo(f"  {ln}")
    else:
        typer.echo(f"{gi_path} already contains all lola-eval entries; no changes")

"""`lola-eval graph` -- time-series chart of composite over runs."""

from __future__ import annotations

import re
from pathlib import Path

import typer
import yaml

from lola_eval.cli import app, _activate_target_env


def _rubric_thresholds(layout) -> dict[str, float]:
    """Map task_id -> rubric ``pass_threshold`` by reading each case's
    ``rubric.md`` frontmatter. Missing/unparseable rubrics are skipped so a
    single bad case can't break the whole graph."""
    out: dict[str, float] = {}
    tests_dir = getattr(layout, "test_sets_dir", None)
    if tests_dir is None or not tests_dir.is_dir():
        return out
    for case_dir in tests_dir.iterdir():
        rubric = case_dir / "rubric.md"
        if not rubric.is_file():
            continue
        try:
            text = rubric.read_text()
            m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
            fm = yaml.safe_load(m.group(1)) if m else {}
            if isinstance(fm, dict) and "pass_threshold" in fm:
                out[case_dir.name] = float(fm["pass_threshold"])
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return out


@app.command("graph", rich_help_panel="Inspect")
def graph(
    cell: str | None = typer.Option(None, "--cell", help="cli/model/task_id; omit for all"),
    threshold: float | None = typer.Option(
        None,
        "--threshold",
        help="Draw a horizontal pass line at this composite; overrides the rubric pass_threshold.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to .lola-eval/config.yaml (default discovered in cwd; standalone XDG fallback if absent)",
    ),
) -> None:
    """Print time-series chart of composite over runs (CLI-friendly)."""
    from lola_eval.layout import resolve as resolve_layout

    try:
        layout = resolve_layout(config_opt=config, out_opt=None)
    except FileNotFoundError:
        layout = None
    # Auto-read per-task rubric thresholds when an eval dir is available; the
    # explicit --threshold flag still overrides them inside print_graph.
    thresholds = _rubric_thresholds(layout) if layout is not None else {}
    with _activate_target_env(layout):
        from lola_eval.graph import print_graph

        raise typer.Exit(print_graph(cell=cell, override=threshold, thresholds=thresholds))

"""CLI-friendly time-series graphs using plotext."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import plotext as plt

from lola_eval.store import connect_read as _connect_for_read


def build_series(db: Path) -> dict[tuple[str, str, str], dict[str, list[tuple[str, float]]]]:
    """Return {(cli, model, task): {pack_id: [(timestamp, composite), …]}} sorted by timestamp asc."""
    if not Path(db).exists():
        return {}
    with _connect_for_read(db) as conn:
        rows = list(conn.execute(
            "SELECT target_cli, target_model, task_id, pack_id, timestamp, scores_json "
            "FROM runs ORDER BY timestamp ASC"
        ))
    out: dict[tuple, dict[str, list[tuple[str, float]]]] = {}
    for r in rows:
        try:
            comp = json.loads(r["scores_json"]).get("composite")
        except Exception:
            continue
        if comp is None:
            continue
        key = (r["target_cli"], r["target_model"], r["task_id"])
        out.setdefault(key, {}).setdefault(r["pack_id"], []).append((r["timestamp"], float(comp)))
    return out


def render_chart_text(
    db: Path,
    cell_key: tuple[str, str, str],
    width: int | None = None,
    height: int | None = None,
) -> str:
    """Render one chart for one cell as ANSI-coloured text."""
    series = build_series(db).get(cell_key)
    cli, model, task = cell_key
    if not series:
        return f"(no data for cell {cli}/{model}/{task})\n"
    if width is None:
        width = max(60, min(120, shutil.get_terminal_size((100, 24)).columns))
    if height is None:
        height = 18

    plt.clf()
    # `pro` emits foreground-only ANSI colors per series — readable in both
    # terminal and HTML pre-blocks without inverse-video backgrounds.
    plt.theme("pro")
    plt.title(f"{cli} / {model}  —  {task}")
    plt.xlabel("run sequence")
    plt.ylabel("composite")
    plt.plot_size(width, height)
    plt.ylim(0, 1.05)
    for pack_id in sorted(series):
        ys = [y for _, y in series[pack_id]]
        xs = list(range(1, len(ys) + 1))
        plt.plot(xs, ys, label=pack_id, marker="braille")
    return plt.build()


def render_all(db: Path) -> str:
    series = build_series(db)
    if not series:
        return "(no runs.db yet — run `lola-eval test` to populate)\n"
    chunks = []
    for cell_key in sorted(series):
        chunks.append(render_chart_text(db, cell_key))
    return "\n".join(chunks)


def print_graph(cell: str | None = None) -> int:
    from lola_eval import xdg
    db = xdg.resolve_db_path()
    if cell is None:
        sys.stdout.write(render_all(db))
        return 0
    parts = cell.split("/")
    if len(parts) != 3:
        sys.stderr.write("--cell must be <cli>/<model>/<task_id>\n")
        return 2
    sys.stdout.write(render_chart_text(db, tuple(parts)))
    return 0

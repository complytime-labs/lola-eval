"""CLI-friendly time-series graphs using plotext."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import plotext as plt

from lola_eval.store import connect_read as _connect_for_read

# Below this many points, braille markers collapse several distinct composite
# values into a single visible dot. Use a per-cell "dot" marker for sparse
# series and fall back to braille once the series is dense enough to need it.
_SMALL_SERIES_LIMIT = 20


def _marker_for(n_points: int) -> str:
    return "braille" if n_points >= _SMALL_SERIES_LIMIT else "dot"


def _short_date(timestamp: str) -> str:
    """Format an ISO timestamp as ``MM-DD`` for an x-axis tick. Degrades to
    the raw string when it can't be parsed (never raises mid-render)."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return timestamp
    return dt.strftime("%m-%d")


def _thin(positions: list[int], labels: list[str], keep: int = 8):
    """Down-sample tick positions/labels to at most ``keep`` evenly spaced
    entries so dense x-axes don't render an unreadable wall of dates."""
    if len(positions) <= keep:
        return positions, labels
    step = (len(positions) - 1) / (keep - 1)
    idx = sorted({round(i * step) for i in range(keep)})
    return [positions[i] for i in idx], [labels[i] for i in idx]


def build_series(db: Path) -> dict[tuple[str, str, str], dict[str, list[tuple[str, float]]]]:
    """Return {(cli, model, task): {pack_id: [(timestamp, composite), …]}} sorted by timestamp asc."""
    if not Path(db).exists():
        return {}
    conn = _connect_for_read(db)
    try:
        rows = list(
            conn.execute(
                "SELECT target_cli, target_model, task_id, pack_id, timestamp, scores_json "
                "FROM runs ORDER BY timestamp ASC"
            )
        )
    finally:
        conn.close()
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
    threshold: float | None = None,
) -> str:
    """Render one chart for one cell as ANSI-coloured text.

    ``threshold`` (the rubric ``pass_threshold`` or a ``--threshold``
    override) draws a horizontal pass line and is annotated in the title so
    passing vs. failing runs are visible at a glance.
    """
    series = build_series(db).get(cell_key)
    cli, model, task = cell_key
    if not series:
        return f"(no data for cell {cli}/{model}/{task})\n"
    if width is None:
        width = max(60, min(120, shutil.get_terminal_size((100, 24)).columns))
    if height is None:
        height = 18

    # Shared temporal x-axis: pack series may have different lengths, so map
    # every distinct run timestamp in the cell to one ordered position and
    # plot each pack against those positions. Ticks then carry real dates.
    all_ts = sorted({ts for pts in series.values() for ts, _ in pts})
    pos_of = {ts: i + 1 for i, ts in enumerate(all_ts)}

    plt.clf()
    # `pro` emits foreground-only ANSI colors per series — readable in both
    # terminal and HTML pre-blocks without inverse-video backgrounds.
    plt.theme("pro")
    title = f"{cli} / {model}  —  {task}"
    if threshold is not None:
        title += f"   (pass >= {threshold:.2f})"
    plt.title(title)
    plt.xlabel("run date")
    plt.ylabel("composite")
    plt.plot_size(width, height)
    plt.ylim(0, 1.05)
    for pack_id in sorted(series):
        pts = series[pack_id]
        xs = [pos_of[ts] for ts, _ in pts]
        ys = [y for _, y in pts]
        plt.plot(xs, ys, label=pack_id, marker=_marker_for(len(pts)))
    positions = list(range(1, len(all_ts) + 1))
    labels = [_short_date(ts) for ts in all_ts]
    plt.xticks(*_thin(positions, labels))
    if threshold is not None:
        plt.hline(threshold, color="red")
    return plt.build()


def _resolve_threshold(
    task_id: str,
    override: float | None,
    thresholds: dict[str, float] | None,
) -> float | None:
    """An explicit ``--threshold`` override wins over the per-task rubric
    value; otherwise look the task up in the rubric-derived map."""
    if override is not None:
        return override
    if thresholds:
        return thresholds.get(task_id)
    return None


def render_all(
    db: Path,
    override: float | None = None,
    thresholds: dict[str, float] | None = None,
) -> str:
    series = build_series(db)
    if not series:
        return f"no runs.db at {db} (run `lola-eval test` to populate)\n"
    chunks = []
    for cell_key in sorted(series):
        task_id = cell_key[2]
        chunks.append(
            render_chart_text(
                db, cell_key, threshold=_resolve_threshold(task_id, override, thresholds)
            )
        )
    return "\n".join(chunks)


def print_graph(
    cell: str | None = None,
    override: float | None = None,
    thresholds: dict[str, float] | None = None,
) -> int:
    from lola_eval import xdg

    db = xdg.resolve_db_path()
    if cell is None:
        sys.stdout.write(render_all(db, override=override, thresholds=thresholds))
        return 0
    parts = cell.split("/")
    if len(parts) != 3:
        sys.stderr.write("--cell must be <cli>/<model>/<task_id>\n")
        return 2
    threshold = _resolve_threshold(parts[2], override, thresholds)
    sys.stdout.write(render_chart_text(db, tuple(parts), threshold=threshold))
    return 0

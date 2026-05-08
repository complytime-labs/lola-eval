"""End-to-end: seed synthetic history, run all reporting commands."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lola_eval.compare import compare_all
from lola_eval.graph import build_series, render_chart_text, render_all
from lola_eval.store import init_db, insert_run


CLIS = ("claude-code", "opencode")
MODELS = ("sonnet", "haiku")
TASKS = ("case-001-fix-bug", "case-002-review-py")
PACKS = ("none", "example-pack@local")
N_PER_CELL = 5


def _seed(db: Path) -> None:
    init_db(db)
    base_time = datetime(2026, 5, 1, tzinfo=timezone.utc)
    rid = 0
    for cli in CLIS:
        for model in MODELS:
            for task in TASKS:
                for pack in PACKS:
                    for k in range(N_PER_CELL):
                        # Seed signal: pack adds +0.20 to score, baseline grows +0.05/run.
                        score = min(1.0, 0.5 + (0.20 if pack != "none" else 0.0) + 0.03 * k)
                        rid += 1
                        ts = (base_time + timedelta(hours=rid)).isoformat().replace("+00:00", "Z")
                        insert_run(db, {
                            "run_id": f"row-{rid}",
                            "timestamp": ts,
                            "fingerprint": "f" * 64,
                            "target_cli": cli,
                            "target_model": model,
                            "target_cli_ver": "1.0.0",
                            "pack_id": pack,
                            "task_id": task,
                            "task_version": "1",
                            "rubric_version": "1",
                            "exec_mode": "autonomous",
                            "invocation": "passive",
                            "judge_cli": "claude-code",
                            "judge_model": "sonnet",
                            "scores_json": json.dumps({
                                "composite": score,
                                "components": {
                                    "correctness": score,
                                    "trajectory": max(0.0, score - 0.1),
                                },
                                "explanation": "synthetic",
                            }),
                            "transcript_path": "/tmp/synthetic.jsonl",
                            "cost_usd": 0.10 + 0.01 * k,
                            "duration_s": 20.0 + k,
                            "exit_status": "success",
                            "turns": 5 + k,
                            "tool_calls_count": 10 + k,
                            "diff_bytes": 500 + 50 * k,
                            # Pack rows burn more tokens than baseline; the
                            # +k drift mirrors the existing per-cell shape.
                            "input_tokens": (143 if pack != "none" else 8) + k,
                            "output_tokens": (4422 if pack != "none" else 2563) + 10 * k,
                            "cache_read_tokens": (1024 if pack != "none" else 100) + 5 * k,
                            "cache_creation_tokens": (256 if pack != "none" else 10) + k,
                        })


def test_seed_inserts_expected_row_count(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    import sqlite3
    n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    expected = len(CLIS) * len(MODELS) * len(TASKS) * len(PACKS) * N_PER_CELL
    assert n == expected == 80


def test_compare_produces_one_row_per_cell(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    rows = compare_all(db)
    expected_cells = len(CLIS) * len(MODELS) * len(TASKS)  # 8
    assert len(rows) == expected_cells


def test_compare_pack_lift_is_positive_under_synthetic_signal(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    rows = compare_all(db)
    for r in rows:
        assert r.composite["pack_mean"] is not None
        assert r.composite["baseline_mean"] is not None
        assert r.composite["pack_mean"] > r.composite["baseline_mean"]
        assert r.composite["lift_percent"] > 0


def test_compare_aggregate_telemetry_is_present(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    rows = compare_all(db)
    sample = rows[0]
    # Every cell has full telemetry seeded.
    assert sample.cost["baseline_mean"] is not None
    assert sample.duration["baseline_mean"] is not None
    assert sample.turns["baseline_mean"] is not None
    assert sample.tools["baseline_mean"] is not None
    assert sample.diff["baseline_mean"] is not None


def test_compare_aggregate_token_counts_are_present(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    rows = compare_all(db)
    for r in rows:
        assert r.input_tokens["baseline_mean"] is not None
        assert r.input_tokens["pack_mean"] is not None
        assert r.input_tokens["delta"] is not None
        assert r.output_tokens["delta"] is not None
        assert r.cache_read_tokens["delta"] is not None
        assert r.cache_creation_tokens["delta"] is not None
        # Pack burns more tokens than baseline by construction.
        assert r.output_tokens["pack_mean"] > r.output_tokens["baseline_mean"]


def test_compare_per_criterion_deltas_are_computed(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    rows = compare_all(db)
    sample = rows[0]
    assert "correctness" in sample.components
    assert "trajectory" in sample.components
    assert sample.components["correctness"]["delta"] is not None


def test_graph_series_produces_one_per_cell(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    series = build_series(db)
    expected_cells = len(CLIS) * len(MODELS) * len(TASKS)
    assert len(series) == expected_cells
    sample_cell = next(iter(series.values()))
    # Each cell has both packs.
    assert "none" in sample_cell
    assert "example-pack@local" in sample_cell


def test_graph_render_specific_cell(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    text = render_chart_text(db, ("claude-code", "sonnet", "case-001-fix-bug"))
    assert "case-001-fix-bug" in text
    # Both packs should appear in the legend.
    assert "none" in text
    assert "example-pack@local" in text
    assert len(text) > 200


def test_graph_render_all_includes_every_cell_title(tmp_path):
    db = tmp_path / "runs.db"
    _seed(db)
    text = render_all(db)
    # Title for each cell appears: "<cli> / <model>  —  <task>"
    for cli in CLIS:
        for model in MODELS:
            for task in TASKS:
                assert task in text


def test_html_report_renders_with_seeded_history(tmp_path, monkeypatch):
    db = tmp_path / "runs.db"
    _seed(db)
    out_dir = tmp_path / "report"
    monkeypatch.setattr("lola_eval.xdg.db_path", lambda: db)

    from lola_eval.report import build_html
    out_path = out_dir / "report.html"
    path = build_html(out_path=out_path)
    text = Path(path).read_text()

    assert "<h2>Compare" in text
    # The browser-illegible ANSI <pre> charts were dropped from the HTML
    # report in favor of pointing users at `lola-eval graph`. Verify the
    # section is still present but rendered as a stub, not as <pre> art.
    assert "Time-series" in text or "time-series" in text.lower()
    assert "<pre" not in text, "HTML report must not embed ANSI chart art"
    assert "lola-eval graph" in text
    # Table content should reference cells.
    assert "case-001-fix-bug" in text
    assert "example-pack@local" in text


def test_compare_threshold_fail_returns_nonzero_when_lift_drops(tmp_path, monkeypatch):
    """If we manually craft a regression in the seed, threshold_fail should trip."""
    db = tmp_path / "runs.db"
    _seed(db)
    # Override one pack row to be worse than baseline.
    import sqlite3
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE runs SET scores_json=? WHERE pack_id=? AND target_cli=? AND target_model=? AND task_id=?",
            (json.dumps({"composite": 0.1, "components": {"correctness": 0.1, "trajectory": 0.0}}),
             "example-pack@local", "claude-code", "sonnet", "case-001-fix-bug"),
        )

    monkeypatch.setattr("lola_eval.xdg.db_path", lambda: db)
    from lola_eval.compare import print_compare
    rc = print_compare(threshold_fail=-5.0)
    assert rc == 1  # at least one cell now has lift < -5%

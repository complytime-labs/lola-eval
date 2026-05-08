"""Comparison engine: aggregates baseline-vs-pack stats per cell."""
import json

from lola_eval.compare import compare_all
from lola_eval.store import init_db, insert_run

BASE_ROW = {
    "run_id": "", "timestamp": "2026-05-09T00:00:00Z", "fingerprint": "f" * 64,
    "target_cli": "claude-code", "target_model": "sonnet", "target_cli_ver": "1",
    "pack_id": "none", "task_id": "case-001-fix-bug", "task_version": "1",
    "rubric_version": "1", "exec_mode": "autonomous", "invocation": "passive",
    "judge_cli": "claude-code", "judge_model": "sonnet",
    "transcript_path": "/tmp/x", "exit_status": "success",
}


def _row(rid, pack, composite, components, cost, duration, turns, tools, diff_b,
         ts="2026-05-09T00:00:00Z", exit_status="success",
         input_tokens=None, output_tokens=None,
         cache_read_tokens=None, cache_creation_tokens=None):
    return {**BASE_ROW, "run_id": rid, "pack_id": pack, "timestamp": ts, "exit_status": exit_status,
            "scores_json": json.dumps({"composite": composite, "components": components}),
            "cost_usd": cost, "duration_s": duration,
            "turns": turns, "tool_calls_count": tools, "diff_bytes": diff_b,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens}


def test_compare_computes_per_cell_aggregates(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    insert_run(db, _row("a", "none",     0.50, {"correctness": 0.5, "trajectory": 0.5}, 0.10, 20, 5,  10, 500))
    insert_run(db, _row("b", "none",     0.60, {"correctness": 0.6, "trajectory": 0.6}, 0.12, 22, 6,  11, 600))
    insert_run(db, _row("c", "review@x", 0.80, {"correctness": 0.8, "trajectory": 0.8}, 0.15, 30, 8,  16, 800))
    insert_run(db, _row("d", "review@x", 0.90, {"correctness": 0.9, "trajectory": 0.9}, 0.18, 28, 9,  17, 900))

    rows = compare_all(db)
    assert len(rows) == 1
    r = rows[0]
    assert r.pack_id == "review@x"
    assert r.target_model == "sonnet"
    assert r.task_id == "case-001-fix-bug"
    assert r.n_baseline == 2 and r.n_pack == 2
    assert abs(r.composite["baseline_mean"] - 0.55) < 1e-9
    assert abs(r.composite["pack_mean"] - 0.85) < 1e-9
    assert abs(r.composite["lift_percent"] - ((0.85 - 0.55) / 0.55 * 100)) < 1e-9
    assert "correctness" in r.components
    assert abs(r.components["correctness"]["delta"] - 0.30) < 1e-9
    assert r.success_rate["baseline"] == 1.0 and r.success_rate["pack"] == 1.0
    # cost mean: baseline (0.10+0.12)/2=0.11, pack (0.15+0.18)/2=0.165
    assert abs(r.cost["baseline_mean"] - 0.11) < 1e-9
    assert abs(r.cost["pack_mean"] - 0.165) < 1e-9
    assert abs(r.cost["delta"] - 0.055) < 1e-9


def test_compare_handles_missing_telemetry_gracefully(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    insert_run(db, _row("a", "none",     0.5, {"x": 0.5}, 0.1, 10, None, None, None))
    insert_run(db, _row("b", "review@x", 0.7, {"x": 0.7}, 0.2, 12, None, None, None))
    rows = compare_all(db)
    assert len(rows) == 1
    assert rows[0].turns["baseline_mean"] is None
    assert rows[0].tools["baseline_mean"] is None
    assert rows[0].diff["baseline_mean"] is None


def test_compare_skips_cells_without_baseline(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    insert_run(db, _row("a", "review@x", 0.8, {"x": 0.8}, 0.1, 10, 5, 10, 100))
    rows = compare_all(db)
    assert rows == []


def test_compare_segregates_by_cell(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    # Two cells (different model), each with baseline + pack.
    insert_run(db, {**_row("a", "none",     0.5, {}, 0.1, 10, 5, 10, 100), "target_model": "sonnet"})
    insert_run(db, {**_row("b", "review@x", 0.8, {}, 0.1, 10, 5, 10, 100), "target_model": "sonnet"})
    insert_run(db, {**_row("c", "none",     0.4, {}, 0.1, 10, 5, 10, 100), "target_model": "haiku"})
    insert_run(db, {**_row("d", "review@x", 0.6, {}, 0.1, 10, 5, 10, 100), "target_model": "haiku"})
    rows = compare_all(db)
    assert len(rows) == 2
    by_model = {r.target_model: r for r in rows}
    assert "sonnet" in by_model and "haiku" in by_model
    assert abs(by_model["sonnet"].composite["lift_percent"] - 60.0) < 1e-9
    assert abs(by_model["haiku"].composite["lift_percent"] - 50.0) < 1e-9


def test_compare_aggregates_token_counts_when_present(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    insert_run(db, _row("a", "none", 0.5, {}, 0.1, 10, 5, 10, 100,
                        input_tokens=8, output_tokens=2563,
                        cache_read_tokens=100, cache_creation_tokens=10))
    insert_run(db, _row("b", "none", 0.6, {}, 0.1, 10, 5, 10, 100,
                        input_tokens=8, output_tokens=2563,
                        cache_read_tokens=100, cache_creation_tokens=10))
    insert_run(db, _row("c", "review@x", 0.8, {}, 0.1, 10, 5, 10, 100,
                        input_tokens=143, output_tokens=4422,
                        cache_read_tokens=1024, cache_creation_tokens=256))
    insert_run(db, _row("d", "review@x", 0.9, {}, 0.1, 10, 5, 10, 100,
                        input_tokens=143, output_tokens=4422,
                        cache_read_tokens=1024, cache_creation_tokens=256))
    rows = compare_all(db)
    assert len(rows) == 1
    r = rows[0]
    assert r.input_tokens["baseline_mean"] == 8.0
    assert r.input_tokens["pack_mean"] == 143.0
    assert r.input_tokens["delta"] == 135.0
    assert r.output_tokens["baseline_mean"] == 2563.0
    assert r.output_tokens["pack_mean"] == 4422.0
    assert abs(r.output_tokens["delta"] - 1859.0) < 1e-9
    assert r.cache_read_tokens["delta"] == 924.0
    assert r.cache_creation_tokens["delta"] == 246.0


def test_compare_token_aggregates_are_none_for_legacy_rows(tmp_path):
    """Rows seeded before this feature shipped have NULL token columns;
    means must degrade to None rather than crash or default to 0."""
    db = tmp_path / "runs.db"
    init_db(db)
    insert_run(db, _row("a", "none", 0.5, {}, 0.1, 10, 5, 10, 100))
    insert_run(db, _row("b", "review@x", 0.7, {}, 0.2, 12, 6, 11, 200))
    rows = compare_all(db)
    assert len(rows) == 1
    r = rows[0]
    assert r.input_tokens["baseline_mean"] is None
    assert r.input_tokens["pack_mean"] is None
    assert r.input_tokens["delta"] is None
    assert r.output_tokens["delta"] is None
    assert r.cache_read_tokens["delta"] is None
    assert r.cache_creation_tokens["delta"] is None


def test_compare_counts_failures_in_success_rate(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    insert_run(db, _row("a", "none",     0.5, {}, 0.1, 10, 5, 10, 100, exit_status="success"))
    insert_run(db, _row("b", "none",     0.0, {}, 0.0, 0,  0, 0,  0,   exit_status="target_error"))
    insert_run(db, _row("c", "review@x", 0.8, {}, 0.1, 10, 5, 10, 100, exit_status="success"))
    insert_run(db, _row("d", "review@x", 0.9, {}, 0.1, 10, 5, 10, 100, exit_status="success"))
    rows = compare_all(db)
    assert len(rows) == 1
    assert rows[0].success_rate["baseline"] == 0.5
    assert rows[0].success_rate["pack"] == 1.0

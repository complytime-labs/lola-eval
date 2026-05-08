"""Time-series graph rendering."""
from lola_eval.graph import build_series, render_chart_text
from lola_eval.store import init_db, insert_run


def _seed_row(db, run_id, pack, score, ts, target_model="sonnet", task_id="case-001-fix-bug"):
    insert_run(db, {
        "run_id": run_id, "timestamp": ts, "fingerprint": "f"*64,
        "target_cli": "claude-code", "target_model": target_model, "target_cli_ver": "1",
        "pack_id": pack, "task_id": task_id, "task_version": "1",
        "rubric_version": "1", "exec_mode": "autonomous", "invocation": "passive",
        "judge_cli": "claude-code", "judge_model": "sonnet",
        "scores_json": f'{{"composite": {score}}}',
        "transcript_path": "/tmp/x", "exit_status": "success",
    })


def test_build_series_groups_by_cell_and_pack(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    _seed_row(db, "1", "none",     0.5, "2026-05-09T01:00:00Z")
    _seed_row(db, "2", "none",     0.6, "2026-05-09T02:00:00Z")
    _seed_row(db, "3", "review@x", 0.85, "2026-05-09T03:00:00Z")

    series = build_series(db)
    cell_key = ("claude-code", "sonnet", "case-001-fix-bug")
    assert cell_key in series
    cell = series[cell_key]
    assert "none" in cell and "review@x" in cell
    assert len(cell["none"]) == 2
    assert len(cell["review@x"]) == 1
    # Earliest timestamp first.
    assert cell["none"][0][1] == 0.5
    assert cell["none"][1][1] == 0.6


def test_build_series_skips_rows_with_unparseable_composite(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    insert_run(db, {
        "run_id": "1", "timestamp": "2026-05-09T01:00:00Z", "fingerprint": "f"*64,
        "target_cli": "claude-code", "target_model": "sonnet", "target_cli_ver": "1",
        "pack_id": "none", "task_id": "case-001-fix-bug", "task_version": "1",
        "rubric_version": "1", "exec_mode": "autonomous", "invocation": "passive",
        "judge_cli": "claude-code", "judge_model": "sonnet",
        "scores_json": "not-json",
        "transcript_path": "/tmp/x", "exit_status": "success",
    })
    insert_run(db, {
        "run_id": "2", "timestamp": "2026-05-09T02:00:00Z", "fingerprint": "f"*64,
        "target_cli": "claude-code", "target_model": "sonnet", "target_cli_ver": "1",
        "pack_id": "none", "task_id": "case-001-fix-bug", "task_version": "1",
        "rubric_version": "1", "exec_mode": "autonomous", "invocation": "passive",
        "judge_cli": "claude-code", "judge_model": "sonnet",
        "scores_json": '{"composite": null}',
        "transcript_path": "/tmp/x", "exit_status": "success",
    })
    series = build_series(db)
    assert series == {}


def test_render_chart_text_returns_nonempty_string(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    for i, (pack, score) in enumerate([("none", 0.5), ("none", 0.6), ("review@x", 0.85), ("review@x", 0.88)]):
        _seed_row(db, str(i), pack, score, f"2026-05-09T0{i}:00:00Z")

    text = render_chart_text(db, ("claude-code", "sonnet", "case-001-fix-bug"))
    assert isinstance(text, str) and len(text) > 100
    # Headline includes target + task.
    assert "sonnet" in text
    assert "case-001-fix-bug" in text


def test_render_chart_text_handles_missing_data_gracefully(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)  # empty DB
    text = render_chart_text(db, ("claude-code", "sonnet", "case-001-fix-bug"))
    assert "no data" in text.lower() or "(no" in text.lower()


def test_render_chart_text_with_nonexistent_db(tmp_path):
    text = render_chart_text(tmp_path / "missing.db", ("x", "y", "z"))
    assert "no data" in text.lower() or "(no" in text.lower()


def test_render_all_handles_empty_db(tmp_path):
    from lola_eval.graph import render_all
    db = tmp_path / "missing.db"
    text = render_all(db)
    assert "no" in text.lower()


def test_render_all_renders_multiple_cells(tmp_path):
    from lola_eval.graph import render_all
    db = tmp_path / "runs.db"
    init_db(db)
    _seed_row(db, "a", "none",     0.5, "2026-05-09T01:00:00Z", target_model="sonnet")
    _seed_row(db, "b", "review@x", 0.7, "2026-05-09T02:00:00Z", target_model="sonnet")
    _seed_row(db, "c", "none",     0.4, "2026-05-09T01:00:00Z", target_model="haiku")
    _seed_row(db, "d", "review@x", 0.6, "2026-05-09T02:00:00Z", target_model="haiku")
    text = render_all(db)
    assert "sonnet" in text and "haiku" in text

"""Calibration module tests.

Tests modeled on tests/python/test_pricing.py shape:
  - dataclass invariants
  - load (bundled, external, sha256, graceful)
  - lookup (exact and family-filtered neighbors)
  - feature extraction + kNN
  - calibration:update merge semantics
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_calibration_row_is_frozen():
    from lola_eval.calibration import CalibrationRow

    row = CalibrationRow(
        run_id="r1",
        timestamp="2026-05-26T00:00:00Z",
        target_cli="claude-code",
        target_cli_ver="2.1.150",
        target_model="claude-sonnet-4-6",
        target_family="claude-sonnet",
        pack_id="showcase",
        task_id="case-A-tiny-fix",
        profile_id="none",
        exec_mode="project",
        input_tokens=10000,
        output_tokens=500,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        turns=2,
        tool_calls_count=4,
        duration_s=30.5,
        cost_usd=0.05,
    )
    with pytest.raises((AttributeError, TypeError)):
        row.cost_usd = 99.0


def test_load_diagnostics_default():
    from lola_eval.calibration import LoadDiagnostics

    diag = LoadDiagnostics()
    assert diag.error is None
    assert diag.sha_verified is False
    assert diag.row_count == 0


def test_load_bundled_consistent():
    """Bundled snapshot loads with verified sha256 and consistent row count.
    Row count itself is not asserted (it grows as calibration data accumulates)."""
    from lola_eval.calibration import _load_bundled

    rows, diag = _load_bundled()
    assert diag.error is None
    assert diag.sha_verified is True
    assert len(rows) == diag.row_count
    # Sanity: every row has a non-empty target_model
    for r in rows[:5]:
        assert r.target_model != ""


def test_load_external_round_trip(tmp_path):
    from lola_eval.calibration import _load_file

    jsonl = tmp_path / "test.jsonl"
    jsonl.write_text(
        '{"run_id":"r1","timestamp":"2026-05-26T00:00:00Z","target_cli":"claude-code",'
        '"target_cli_ver":"2.1.150","target_model":"claude-sonnet-4-6",'
        '"target_family":"claude-sonnet","pack_id":"p","task_id":"t","profile_id":"none",'
        '"exec_mode":"project","input_tokens":100,"output_tokens":50,'
        '"cache_read_tokens":0,"cache_creation_tokens":0,"turns":1,"tool_calls_count":0,'
        '"duration_s":10.0,"cost_usd":0.01,"exit_status":"ok"}\n'
    )
    rows, diag = _load_file(jsonl)
    assert len(rows) == 1
    assert rows[0].target_family == "claude-sonnet"
    assert diag.row_count == 1
    assert diag.error is None


def test_load_sha256_mismatch(tmp_path):
    from lola_eval.calibration import _load_file

    jsonl = tmp_path / "test.jsonl"
    jsonl.write_text('{"junk":1}\n')  # one line of unrelated content
    sidecar = tmp_path / "test.jsonl.sha256"
    sidecar.write_text("0" * 64 + "\n")  # known-wrong sha
    rows, diag = _load_file(jsonl)
    assert rows == []  # graceful: no rows on sha mismatch
    assert "sha256 mismatch" in (diag.error or "")


def test_load_malformed_row_skipped(tmp_path):
    from lola_eval.calibration import _load_file

    jsonl = tmp_path / "test.jsonl"
    jsonl.write_text(
        '{"run_id":"r1"}\n'  # missing required fields
        + '{"run_id":"r2","timestamp":"2026-05-26T00:00:00Z","target_cli":"claude-code",'
        + '"target_cli_ver":"2.1.150","target_model":"claude-sonnet-4-6",'
        + '"target_family":"claude-sonnet","pack_id":"p","task_id":"t","profile_id":"none",'
        + '"exec_mode":"project","input_tokens":100,"output_tokens":50,'
        + '"cache_read_tokens":0,"cache_creation_tokens":0,"turns":1,"tool_calls_count":0,'
        + '"duration_s":10.0,"cost_usd":0.01,"exit_status":"ok"}\n'
    )
    rows, diag = _load_file(jsonl)
    assert len(rows) == 1  # bad row dropped, good one kept
    assert rows[0].run_id == "r2"


def _make_row(**overrides):
    from lola_eval.calibration import CalibrationRow

    defaults = dict(
        run_id="r",
        timestamp="2026-05-26T00:00:00Z",
        target_cli="claude-code",
        target_cli_ver="2.1.150",
        target_model="claude-sonnet-4-6",
        target_family="claude-sonnet",
        pack_id="showcase",
        task_id="case-A-tiny-fix",
        profile_id="none",
        exec_mode="project",
        input_tokens=10000,
        output_tokens=500,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        turns=2,
        tool_calls_count=4,
        duration_s=30.0,
        cost_usd=0.05,
    )
    defaults.update(overrides)
    return CalibrationRow(**defaults)


def test_resolver_lookup_no_match():
    from lola_eval.calibration import Resolver

    r = Resolver()
    r._bundled = []  # type: ignore[attr-defined]
    r._external = []  # type: ignore[attr-defined]
    result = r.lookup("claude-sonnet-4-6", "showcase", "case-A-tiny-fix", "none", "project")
    assert result.n == 0
    assert result.rows == []


def test_resolver_lookup_exact_match_median():
    from lola_eval.calibration import Resolver

    rows = [
        _make_row(
            run_id="r1", input_tokens=10000, output_tokens=500, duration_s=30.0, cost_usd=0.05
        ),
        _make_row(
            run_id="r2", input_tokens=12000, output_tokens=600, duration_s=35.0, cost_usd=0.06
        ),
        _make_row(
            run_id="r3", input_tokens=11000, output_tokens=550, duration_s=33.0, cost_usd=0.055
        ),
    ]
    r = Resolver()
    r._bundled = rows  # type: ignore[attr-defined]
    r._external = []
    result = r.lookup("claude-sonnet-4-6", "showcase", "case-A-tiny-fix", "none", "project")
    assert result.n == 3
    assert result.median_input_tokens == 11000
    assert result.median_output_tokens == 550
    assert result.median_duration_s == 33.0
    assert abs(result.median_cost_usd - 0.055) < 1e-9


def test_resolver_lookup_external_wins_on_collision():
    from lola_eval.calibration import Resolver

    bundled = [_make_row(run_id="r1", cost_usd=999.0)]
    external = [_make_row(run_id="r1", cost_usd=0.05)]
    r = Resolver()
    r._bundled = bundled  # type: ignore[attr-defined]
    r._external = external  # type: ignore[attr-defined]
    # External + bundled merge with external winning per run_id.
    # Implementation must dedup before computing median.
    result = r.lookup("claude-sonnet-4-6", "showcase", "case-A-tiny-fix", "none", "project")
    assert result.n == 1
    assert abs(result.median_cost_usd - 0.05) < 1e-9


def test_neighbors_filters_by_family():
    from lola_eval.calibration import Resolver

    rows = [
        _make_row(run_id="s1", target_model="claude-sonnet-4-6", target_family="claude-sonnet"),
        _make_row(run_id="s2", target_model="claude-sonnet-4-5", target_family="claude-sonnet"),
        _make_row(run_id="o1", target_model="claude-opus-4-7", target_family="claude-opus"),
        _make_row(run_id="h1", target_model="claude-haiku-4-5", target_family="claude-haiku"),
    ]
    r = Resolver()
    r._bundled = rows
    r._external = []
    neighbors = r.neighbors("claude-sonnet")
    assert {n.run_id for n in neighbors} == {"s1", "s2"}


def test_neighbors_excludes_empty_family():
    from lola_eval.calibration import Resolver

    rows = [
        _make_row(run_id="x1", target_family=""),
        _make_row(run_id="s1", target_family="claude-sonnet"),
    ]
    r = Resolver()
    r._bundled = rows
    r._external = []
    assert {n.run_id for n in r.neighbors("claude-sonnet")} == {"s1"}
    assert r.neighbors("") == []


def _seed_runs_db(db_path: Path, rows: list[dict]) -> None:
    """Create a minimal runs.db with the given rows."""
    from lola_eval.store import init_db, insert_run

    init_db(db_path)
    for r in rows:
        insert_run(db_path, r)


def test_calibration_update_round_trips_runs_db(tmp_path, monkeypatch):
    """SELECT ok rows from runs.db, write JSONL, recompute sha256."""
    db = tmp_path / "runs.db"
    base_row = {
        "run_id": "r1",
        "timestamp": "2026-05-26T00:00:00Z",
        "fingerprint": "f1",
        "target_cli": "claude-code",
        "target_model": "claude-sonnet-4-6",
        "target_cli_ver": "2.1.150",
        "pack_id": "showcase",
        "profile_id": "none",
        "task_id": "case-A-tiny-fix",
        "task_version": "1.0",
        "rubric_version": "1.0",
        "exec_mode": "project",
        "invocation": "test",
        "judge_cli": "claude-code",
        "judge_model": "claude-sonnet-4-6",
        "scores_json": "{}",
        "transcript_path": "transcript.json",
        "exit_status": "success",
        "input_tokens": 10000,
        "output_tokens": 500,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "turns": 2,
        "tool_calls_count": 4,
        "duration_s": 30.0,
        "cost_usd": 0.05,
    }
    err_row = {**base_row, "run_id": "r2", "exit_status": "target_error"}
    _seed_runs_db(db, [base_row, err_row])

    fake_calibration = tmp_path / "calibration"
    fake_calibration.mkdir()
    jsonl = fake_calibration / "runs.jsonl"
    jsonl.write_text("")
    (fake_calibration / "runs.jsonl.sha256").write_text(
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lola_eval.calibration_update",
            "--src",
            str(db),
            "--target",
            str(jsonl),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    import json as _json

    body = jsonl.read_text().strip().splitlines()
    assert len(body) == 1
    parsed = _json.loads(body[0])
    assert parsed["run_id"] == "r1"
    assert parsed["target_family"] != ""


def test_calibration_verify_passes_on_empty_bundled():
    """Strict verify on the empty bundled JSONL must return 0."""
    result = subprocess.run(
        [sys.executable, "-m", "lola_eval.calibration_verify"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_extract_features_from_task_dir(tmp_path):
    """Feature extraction reads a task_set directory and returns the
    6-tuple feature vector."""
    from lola_eval.calibration import extract_features

    task_dir = tmp_path / "case-X"
    task_dir.mkdir()
    (task_dir / "prompt.md").write_text("Fix the failing test. Run pytest.")
    (task_dir / "rubric.md").write_text("# Rubric\n- [ ] one\n- [ ] two\n- [ ] three\n")
    starter = task_dir / "starter"
    starter.mkdir()
    (starter / "f1.py").write_text("print('hi')")
    (starter / "f2.py").write_text("print('there')")

    features = extract_features(
        task_dir=task_dir,
        profile_skill_count=2,
        exec_mode="project",
    )
    assert features.prompt_word_count == 6
    assert features.rubric_criteria_count == 3
    assert features.starter_file_count == 2
    assert features.starter_total_bytes == len("print('hi')") + len("print('there')")
    assert features.profile_skill_count == 2
    assert features.baseline_indicator == 0


def test_extract_features_baseline_mode(tmp_path):
    from lola_eval.calibration import extract_features

    task_dir = tmp_path / "case-Y"
    task_dir.mkdir()
    (task_dir / "prompt.md").write_text("one two three")
    (task_dir / "rubric.md").write_text("- a\n- b\n")
    f = extract_features(task_dir, profile_skill_count=0, exec_mode="none")
    assert f.baseline_indicator == 1


def test_knn_predict_returns_median_of_neighbors():
    """kNN with k=3, normalized features, family filter, median over neighbors."""
    from lola_eval.calibration import TaskFeatures, knn_predict

    rows = [
        _make_row(
            run_id=f"s{i}",
            target_family="claude-sonnet",
            input_tokens=10000 + i * 100,
            output_tokens=500 + i * 10,
            duration_s=30.0 + i,
            cost_usd=0.05 + i * 0.001,
        )
        for i in range(5)
    ]
    feature_vectors = [
        TaskFeatures(
            prompt_word_count=10 + i,
            rubric_criteria_count=3,
            starter_file_count=2,
            starter_total_bytes=200,
            profile_skill_count=0,
            baseline_indicator=0,
        )
        for i in range(5)
    ]
    query_features = TaskFeatures(
        prompt_word_count=11,
        rubric_criteria_count=3,
        starter_file_count=2,
        starter_total_bytes=200,
        profile_skill_count=0,
        baseline_indicator=0,
    )

    pred = knn_predict(
        query=query_features,
        candidates=list(zip(rows, feature_vectors)),
        k=3,
    )
    assert pred is not None
    # Three nearest = i=0,1,2 (closest three). Median input_tokens 10000, 10100, 10200 = 10100.
    assert pred.median_input_tokens == 10100
    assert pred.median_output_tokens == 510
    assert pred.k == 3
    assert pred.n_candidates == 5


def test_knn_predict_returns_none_when_too_few_neighbors():
    from lola_eval.calibration import TaskFeatures, knn_predict

    rows = [_make_row(run_id="s1", target_family="claude-sonnet")]
    fv = [TaskFeatures(10, 3, 2, 200, 0, 0)]
    query = TaskFeatures(11, 3, 2, 200, 0, 0)
    assert knn_predict(query, list(zip(rows, fv)), k=3) is None

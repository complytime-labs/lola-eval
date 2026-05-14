"""Pass/fail engine for absolute, regression, and both modes."""
from pathlib import Path

import pytest

from lola_eval.threshold import (
    BaselineMissing,
    RowResult,
    ThresholdEngine,
)


def _row(cell, pack, composite, pass_threshold=0.6, timed_out=False):
    return RowResult(
        cli=cell[0], model=cell[1], task_id=cell[2], pack_id=pack,
        composite=composite, rubric_pass_threshold=pass_threshold, timed_out=timed_out,
    )


def test_absolute_pass(tmp_path: Path):
    eng = ThresholdEngine(mode="absolute", tolerance=0.05, results_dir=tmp_path)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.85)]
    rep = eng.check(rows)
    assert rep.exit_code == 0
    assert rep.failures == []


def test_absolute_below_threshold(tmp_path: Path):
    eng = ThresholdEngine(mode="absolute", tolerance=0.05, results_dir=tmp_path)
    rows = [
        _row(("claude-code", "sonnet", "case-001"), "none", 0.40, pass_threshold=0.6),
        _row(("claude-code", "sonnet", "case-002"), "none", 0.85, pass_threshold=0.6),
    ]
    rep = eng.check(rows)
    assert rep.exit_code == 1
    assert len(rep.failures) == 1
    assert rep.failures[0].task_id == "case-001"


def test_regression_missing_baseline(tmp_path: Path):
    eng = ThresholdEngine(mode="regression", tolerance=0.05, results_dir=tmp_path)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.85)]
    with pytest.raises(BaselineMissing):
        eng.check(rows)


def test_regression_within_tolerance(tmp_path: Path):
    (tmp_path / "baseline.json").write_text(
        '{"claude-code/sonnet/case-001/none": {"composite": 0.85}}'
    )
    eng = ThresholdEngine(mode="regression", tolerance=0.05, results_dir=tmp_path)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.82)]
    rep = eng.check(rows)
    assert rep.exit_code == 0


def test_regression_below_tolerance(tmp_path: Path):
    (tmp_path / "baseline.json").write_text(
        '{"claude-code/sonnet/case-001/none": {"composite": 0.85}}'
    )
    eng = ThresholdEngine(mode="regression", tolerance=0.05, results_dir=tmp_path)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.70)]
    rep = eng.check(rows)
    assert rep.exit_code == 1
    assert "regressed" in rep.failures[0].reason.lower()


def test_both_mode_either_fails(tmp_path: Path):
    (tmp_path / "baseline.json").write_text(
        '{"claude-code/sonnet/case-001/none": {"composite": 0.85}}'
    )
    eng = ThresholdEngine(mode="both", tolerance=0.05, results_dir=tmp_path)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.40, pass_threshold=0.6)]
    rep = eng.check(rows)
    assert rep.exit_code == 1
    assert len(rep.failures) == 1


def test_timeout_is_failure_true(tmp_path: Path):
    eng = ThresholdEngine(mode="absolute", tolerance=0.05, results_dir=tmp_path, timeout_is_failure=True)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.85, timed_out=True)]
    rep = eng.check(rows)
    assert rep.exit_code == 3


def test_timeout_is_failure_false(tmp_path: Path):
    eng = ThresholdEngine(mode="absolute", tolerance=0.05, results_dir=tmp_path, timeout_is_failure=False)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.85, timed_out=True)]
    rep = eng.check(rows)
    assert rep.exit_code == 0


def test_setup_takes_precedence_over_timeout(tmp_path: Path):
    """Per spec: precedence is 2 > 3 > 1."""
    eng = ThresholdEngine(mode="regression", tolerance=0.05, results_dir=tmp_path)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.85, timed_out=True)]
    with pytest.raises(BaselineMissing):
        eng.check(rows)


def test_no_run_produced_is_setup_class_failure(tmp_path: Path):
    """C1: judge never persisted a row -> exit 3, not silently passing."""
    eng = ThresholdEngine(mode="absolute", tolerance=0.05, results_dir=tmp_path)
    row = RowResult(
        cli="claude-code", model="sonnet", task_id="case-001", pack_id="none",
        composite=0.0, rubric_pass_threshold=0.6,
        failure_kind="no_run_produced",
        failure_reason="judge did not persist a row",
    )
    rep = eng.check([row])
    assert rep.exit_code == 3
    assert len(rep.failures) == 1
    assert "no_run_produced" in rep.failures[0].reason
    assert "judge did not persist a row" in rep.failures[0].reason


def test_judge_error_surfaces_with_message(tmp_path: Path):
    """C2: judge subprocess crashed -> exit 3 with the original message."""
    eng = ThresholdEngine(mode="absolute", tolerance=0.05, results_dir=tmp_path)
    row = RowResult(
        cli="claude-code", model="sonnet", task_id="case-001", pack_id="none",
        composite=0.0, rubric_pass_threshold=0.6,
        failure_kind="judge_error",
        failure_reason="claude-code/sonnet: connection refused",
    )
    rep = eng.check([row])
    assert rep.exit_code == 3
    assert len(rep.failures) == 1
    assert "judge_error" in rep.failures[0].reason
    assert "connection refused" in rep.failures[0].reason


def test_setup_error_surfaces_with_install_pack_message(tmp_path: Path):
    """Regression: when `lola install` fails (e.g. module not found), the
    runner emits a setup_error RowResult carrying the lola message. The
    threshold engine must treat that as infrastructure (exit 3) and
    surface the actionable message — NOT collapse it into a generic
    "composite 0.0 below threshold" line that hides the real cause.
    """
    eng = ThresholdEngine(mode="absolute", tolerance=0.05, results_dir=tmp_path)
    row = RowResult(
        cli="claude-code", model="sonnet", task_id="case-001",
        pack_id="example-pack@local",
        composite=0.0, rubric_pass_threshold=0.6,
        failure_kind="setup_error",
        failure_reason=(
            "install_pack.sh: FAILED pack=example-pack@local target=claude-code: "
            "Module 'example-pack' not found"
        ),
    )
    rep = eng.check([row])
    assert rep.exit_code == 3, "setup_error is infrastructure, not threshold"
    assert len(rep.failures) == 1
    assert "setup_error" in rep.failures[0].reason
    assert "Module 'example-pack' not found" in rep.failures[0].reason


def test_judge_disagreement_is_row_level_failure(tmp_path: Path):
    """Variance-aware: judge_disagreement is a quality signal (exit 1), not
    infrastructure (exit 3). The composite was real; the judges just
    disagreed too much under disagreement_action='fail'."""
    eng = ThresholdEngine(mode="absolute", tolerance=0.05, results_dir=tmp_path)
    row = RowResult(
        cli="claude-code", model="sonnet", task_id="case-001", pack_id="none",
        composite=0.85,  # would have passed on score alone
        rubric_pass_threshold=0.6,
        judge_disagreement=0.42,
        failure_kind="judge_disagreement",
        failure_reason="judge_disagreement 0.4200 > threshold 0.1500 (N=2 judges)",
    )
    rep = eng.check([row])
    assert rep.exit_code == 1, "judge_disagreement is a row-level failure, not infra"
    assert len(rep.failures) == 1
    assert "judge_disagreement" in rep.failures[0].reason
    assert "0.4200" in rep.failures[0].reason


def test_row_result_cell_key_with_profile():
    r = RowResult(
        cli="claude-code", model="sonnet", task_id="case-001",
        pack_id="project", composite=0.8, rubric_pass_threshold=0.6,
        profile_id="superpowers",
    )
    assert r.cell_key == "claude-code/sonnet/case-001/project/superpowers"


def test_row_result_cell_key_without_profile():
    r = RowResult(
        cli="claude-code", model="sonnet", task_id="case-001",
        pack_id="project", composite=0.8, rubric_pass_threshold=0.6,
    )
    assert r.cell_key == "claude-code/sonnet/case-001/project"


def test_corrupt_baseline_raises_baseline_missing(tmp_path: Path):
    """I9: corrupt baseline.json raises BaselineMissing, not JSONDecodeError."""
    (tmp_path / "baseline.json").write_text("{invalid json")
    eng = ThresholdEngine(mode="regression", tolerance=0.05, results_dir=tmp_path)
    rows = [_row(("claude-code", "sonnet", "case-001"), "none", 0.85)]
    with pytest.raises(BaselineMissing) as exc_info:
        eng.check(rows)
    # Message must distinguish corrupt-from-missing so the user knows what to fix.
    assert "failed to parse" in str(exc_info.value)

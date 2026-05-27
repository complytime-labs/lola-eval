"""End-to-end: profiled rows match their baseline entries through ThresholdEngine.

Regression for findings #2 (baseline path), #3 (cell_key drift), and #4
(baseline writer dict-collision). Fails on all three until the design's
canonical 5-segment cell-key shape is applied across writer, RowResult,
and engine reader.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lola_eval.threshold import RowResult, ThresholdEngine


def _row(cli, model, task, pack, profile, composite, threshold=0.6):
    return RowResult(
        cli=cli,
        model=model,
        task_id=task,
        pack_id=pack,
        composite=composite,
        rubric_pass_threshold=threshold,
        profile_id=profile,
    )


def test_profiled_row_matches_5_segment_baseline(tmp_path: Path):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "claude-code/sonnet/case-001/project/superpowers": {
                    "composite": 0.80,
                    "rubric_pass_threshold": 0.6,
                },
            }
        )
    )
    engine = ThresholdEngine(
        mode="regression",
        tolerance=0.05,
        results_dir=tmp_path / "out",
        baseline_path=baseline_path,
    )
    # composite regressed by 0.10 (> tolerance 0.05) → should fail.
    report = engine.check(
        [_row("claude-code", "sonnet", "case-001", "project", "superpowers", 0.70)]
    )
    assert report.exit_code == 1, f"expected regression failure, got {report.exit_code}"
    assert report.failures, "expected one failure row"
    assert "superpowers" in report.failures[0].cell_key


def test_unprofiled_row_uses_none_in_5_segment_key(tmp_path: Path):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "claude-code/sonnet/case-001/project/none": {
                    "composite": 0.80,
                    "rubric_pass_threshold": 0.6,
                },
            }
        )
    )
    engine = ThresholdEngine(
        mode="regression",
        tolerance=0.05,
        results_dir=tmp_path / "out",
        baseline_path=baseline_path,
    )
    report = engine.check(
        [_row("claude-code", "sonnet", "case-001", "project", "none", 0.82)]
    )
    assert report.exit_code == 0, f"expected pass, got {report.exit_code}"


def test_legacy_4_segment_baseline_is_rejected(tmp_path: Path):
    from lola_eval.threshold import BaselineMissing

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "claude-code/sonnet/case-001/project": {
                    "composite": 0.80,
                    "rubric_pass_threshold": 0.6,
                },
            }
        )
    )
    engine = ThresholdEngine(
        mode="regression",
        tolerance=0.05,
        results_dir=tmp_path / "out",
        baseline_path=baseline_path,
    )
    with pytest.raises(BaselineMissing) as exc_info:
        engine.check([_row("claude-code", "sonnet", "case-001", "project", "none", 0.82)])
    msg = str(exc_info.value)
    assert "legacy key shape" in msg
    assert "lola-eval baseline update" in msg

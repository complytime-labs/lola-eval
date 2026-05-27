"""Regression tests for `lola-eval baseline update` (finding #4)."""
from __future__ import annotations

from lola_eval.cli.baseline_cmd import _last_run_to_baseline


def test_last_run_to_baseline_keeps_all_profiles_per_cell():
    """N profile rows per cell must produce N baseline entries, not 1."""
    rows = [
        {
            "cli": "claude-code",
            "model": "sonnet",
            "task_id": "case-001",
            "pack_id": "project",
            "profile_id": "profile-a",
            "composite": 0.80,
            "rubric_pass_threshold": 0.6,
        },
        {
            "cli": "claude-code",
            "model": "sonnet",
            "task_id": "case-001",
            "pack_id": "project",
            "profile_id": "profile-b",
            "composite": 0.72,
            "rubric_pass_threshold": 0.6,
        },
        {
            "cli": "claude-code",
            "model": "sonnet",
            "task_id": "case-001",
            "pack_id": "project",
            "profile_id": "profile-c",
            "composite": 0.68,
            "rubric_pass_threshold": 0.6,
        },
    ]
    baseline = _last_run_to_baseline(rows)
    assert len(baseline) == 3, f"expected 3 entries (one per profile), got {len(baseline)}: {list(baseline)}"
    assert "claude-code/sonnet/case-001/project/profile-a" in baseline
    assert "claude-code/sonnet/case-001/project/profile-b" in baseline
    assert "claude-code/sonnet/case-001/project/profile-c" in baseline
    assert baseline["claude-code/sonnet/case-001/project/profile-a"]["composite"] == 0.80
    assert baseline["claude-code/sonnet/case-001/project/profile-b"]["composite"] == 0.72


def test_last_run_to_baseline_unprofiled_rows_use_none():
    rows = [
        {
            "cli": "claude-code",
            "model": "sonnet",
            "task_id": "case-001",
            "pack_id": "project",
            "composite": 0.85,
            "rubric_pass_threshold": 0.6,
        },
    ]
    baseline = _last_run_to_baseline(rows)
    assert list(baseline) == ["claude-code/sonnet/case-001/project/none"]

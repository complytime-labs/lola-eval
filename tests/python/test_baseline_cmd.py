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
    # 3 cell entries + 1 _schema_version sentinel = 4 total keys.
    assert len(baseline) == 4, f"expected 4 entries (3 cells + schema sentinel), got {len(baseline)}: {list(baseline)}"
    assert baseline["_schema_version"] == 2
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
    assert baseline["_schema_version"] == 2
    assert "claude-code/sonnet/case-001/project/none" in baseline
    assert len(baseline) == 2  # sentinel + 1 cell entry

"""runner._build_test_vars wiring of per-task judge overrides."""
from __future__ import annotations

from lola_eval.config import LolaEvalConfig, TargetEntry, JudgeEntry
from lola_eval.runner import _build_test_vars


def _cfg() -> LolaEvalConfig:
    return LolaEvalConfig(
        targets=[TargetEntry(cli="claude-code", models=["sonnet"])],
        judges=[JudgeEntry(cli="claude-code", model="sonnet")],
    )


def _case_dir(tmp_path):
    d = tmp_path / "case-x"
    d.mkdir()
    (d / "prompt.md").write_text("do the thing")
    return d


def test_judge_transcript_limit_flows_into_vars(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target, "sonnet", "none", _case_dir(tmp_path),
        {"task_version": "1", "judge_transcript_limit": 120000},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(), None, "",
    )
    assert v["judge_transcript_limit"] == 120000


def test_judge_transcript_limit_defaults_empty_when_absent(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target, "sonnet", "none", _case_dir(tmp_path),
        {"task_version": "1"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(), None, "",
    )
    assert v["judge_transcript_limit"] == ""


def test_subject_version_flows_into_vars(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target, "sonnet", "none", _case_dir(tmp_path),
        {"task_version": "1", "subject_version": "mymod@1.0.0"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(), None, "",
    )
    assert v["subject_version"] == "mymod@1.0.0"


def test_subject_version_defaults_empty(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target, "sonnet", "none", _case_dir(tmp_path),
        {"task_version": "1"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(), None, "",
    )
    assert v["subject_version"] == ""

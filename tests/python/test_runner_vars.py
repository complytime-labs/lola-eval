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
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1", "judge_transcript_limit": 120000},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["judge_transcript_limit"] == 120000


def test_judge_transcript_limit_defaults_empty_when_absent(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["judge_transcript_limit"] == ""


def test_subject_version_flows_into_vars(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1", "subject_version": "mymod@1.0.0"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["subject_version"] == "mymod@1.0.0"


def test_subject_version_defaults_empty(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["subject_version"] == ""


def test_pre_run_flows_into_vars(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1", "pre_run": "bash provision.sh"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["pre_run"] == "bash provision.sh"


def test_pre_run_defaults_empty(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["pre_run"] == ""


def test_include_ignored_paths_joins_into_vars(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1", "include_ignored_paths": ["vendor/", "*.log"]},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["include_ignored_paths"] == "vendor/ *.log"


def test_include_ignored_paths_defaults_empty(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["include_ignored_paths"] == ""


def test_judge_fanout_and_base_flow_from_config(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1"},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["judge_fanout_seconds"] == 600
    assert v["judge_subprocess_base_seconds"] == 120


def test_agent_timeout_defaults_from_config(tmp_path):
    from lola_eval.config import TimeoutConfig

    target = TargetEntry(cli="claude-code", models=["sonnet"])
    cfg = LolaEvalConfig(
        targets=[target],
        judges=[JudgeEntry(cli="claude-code", model="sonnet")],
        timeouts=TimeoutConfig(agent_seconds=900),
    )
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1"},  # no per-task timeout_seconds -> config default
        {"rubric_version": "1", "pass_threshold": 0.6},
        cfg,
        None,
        "",
    )
    assert v["timeout_seconds"] == 900


def test_task_timeout_overrides_config_default(tmp_path):
    target = TargetEntry(cli="claude-code", models=["sonnet"])
    v = _build_test_vars(
        target,
        "sonnet",
        "none",
        _case_dir(tmp_path),
        {"task_version": "1", "timeout_seconds": 1200},
        {"rubric_version": "1", "pass_threshold": 0.6},
        _cfg(),
        None,
        "",
    )
    assert v["timeout_seconds"] == 1200

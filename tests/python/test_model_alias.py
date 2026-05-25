"""Unpinned-alias detection and drift warnings (#4)."""

from __future__ import annotations

from lola_eval.config import LolaEvalConfig, TargetEntry, JudgeEntry
from lola_eval.model_alias import is_model_alias, alias_drift_warnings


def test_is_model_alias_bare_names():
    assert is_model_alias("sonnet") is True
    assert is_model_alias("opus") is True
    assert is_model_alias("haiku") is True


def test_is_model_alias_pinned_ids():
    assert is_model_alias("claude-sonnet-4-6") is False
    assert is_model_alias("claude-haiku-4-5-20251001") is False
    assert is_model_alias("google-vertex/claude-sonnet-4-6@default") is False


def test_is_model_alias_digitless_string_is_alias():
    assert is_model_alias("some-codename") is True


def test_is_model_alias_empty_is_not_alias():
    assert is_model_alias("") is False


def test_alias_warnings_flags_target_and_judge():
    cfg = LolaEvalConfig(
        targets=[TargetEntry(cli="claude-code", models=["sonnet", "claude-haiku-4-5-20251001"])],
        judges=[JudgeEntry(cli="claude-code", model="opus")],
    )
    warnings = alias_drift_warnings(cfg)
    joined = "\n".join(warnings)
    assert "sonnet" in joined  # alias target flagged
    assert "opus" in joined  # alias judge flagged
    assert "claude-haiku-4-5-20251001" not in joined  # pinned target not flagged
    assert len(warnings) == 2


def test_alias_warnings_empty_when_all_pinned():
    cfg = LolaEvalConfig(
        targets=[TargetEntry(cli="claude-code", models=["claude-sonnet-4-6"])],
        judges=[JudgeEntry(cli="claude-code", model="claude-sonnet-4-6")],
    )
    assert alias_drift_warnings(cfg) == []

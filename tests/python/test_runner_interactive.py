"""Runner tests for exec_mode=interactive.

These are hermetic: they exercise ``_build_promptfoo_config`` directly
to verify the interactive provider gets picked and the per-row vars
include the persona body and dialog settings. End-to-end (subprocess
+ promptfoo) coverage requires real CLIs and lives in the smoke layer.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from lola_eval.config import LolaEvalConfig, TargetEntry, JudgeEntry
from lola_eval.runner import _build_promptfoo_config


def _write_case(case_dir: Path, with_persona: bool = True) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "task.yaml").write_text(
        "task_version: 1\ntimeout_seconds: 60\n"
    )
    (case_dir / "prompt.md").write_text("Fix the failing test.")
    (case_dir / "rubric.md").write_text(textwrap.dedent("""\
        ---
        rubric_version: 1
        pass_threshold: 0.6
        weights:
          correctness: 1.0
        ---
        Grade on correctness.
    """))
    if with_persona:
        (case_dir / "simulated_user.md").write_text(textwrap.dedent("""\
            ---
            stop_phrase: DONE
            ---
            Be terse. Ask one question per turn.
        """))


def _build_cfg(*, exec_mode: str = "interactive",
               max_turns: int = 5,
               simulated_user_cli: str = "opencode",
               simulated_user_model: str = "") -> LolaEvalConfig:
    return LolaEvalConfig(
        targets=[TargetEntry(
            cli="claude-code", models=["sonnet"],
            exec_mode=exec_mode, max_turns=max_turns,
            simulated_user_cli=simulated_user_cli,
            simulated_user_model=simulated_user_model,
        )],
        # Mode 1 (in-repo, no explicit packs). The derived pack_id list
        # used by these tests is supplied directly to _build_promptfoo_config
        # as the `packs=` arg below, so the field-level shape is irrelevant.
        judges=[JudgeEntry(cli="claude-code", model="sonnet")],
    )


def test_interactive_target_uses_interactive_provider(tmp_path):
    case_dir = tmp_path / "tests/lola-eval/example"
    _write_case(case_dir)
    cfg = _build_cfg(exec_mode="interactive")
    workspace = tmp_path / "workspace"

    pf = _build_promptfoo_config(
        cfg=cfg, target_root=tmp_path,
        cases=[case_dir], packs=["none"],
        workspace=workspace, concurrency=1,
    )
    assert len(pf["tests"]) == 1
    test = pf["tests"][0]
    # Each test inlines its own provider object — see the matrix-doubling
    # comment in runner._build_promptfoo_config. No top-level providers
    # list; each test→provider relationship is 1:1.
    assert isinstance(test["provider"], dict)
    assert "claude_code_interactive_provider.js" in test["provider"]["id"]
    assert "[interactive]" in test["description"]


def test_autonomous_target_uses_autonomous_provider(tmp_path):
    case_dir = tmp_path / "tests/lola-eval/example"
    _write_case(case_dir, with_persona=False)
    cfg = _build_cfg(exec_mode="autonomous")
    workspace = tmp_path / "workspace"

    pf = _build_promptfoo_config(
        cfg=cfg, target_root=tmp_path,
        cases=[case_dir], packs=["none"],
        workspace=workspace, concurrency=1,
    )
    test = pf["tests"][0]
    # Default autonomous provider, NOT interactive.
    assert isinstance(test["provider"], dict)
    assert "claude_code_provider.js" in test["provider"]["id"]
    assert "claude_code_interactive_provider.js" not in test["provider"]["id"]


def test_interactive_test_vars_include_persona_and_settings(tmp_path):
    case_dir = tmp_path / "tests/lola-eval/example"
    _write_case(case_dir)
    cfg = _build_cfg(
        exec_mode="interactive", max_turns=7,
        simulated_user_cli="opencode",
        simulated_user_model="claude-sonnet-4-6",
    )
    workspace = tmp_path / "workspace"

    pf = _build_promptfoo_config(
        cfg=cfg, target_root=tmp_path,
        cases=[case_dir], packs=["none"],
        workspace=workspace, concurrency=1,
    )
    v = pf["tests"][0]["vars"]
    assert v["exec_mode"] == "interactive"
    assert v["invocation"] == "active", "interactive flips invocation to active"
    assert v["max_turns"] == 7
    assert v["simulated_user_cli"] == "opencode"
    assert v["simulated_user_model"] == "claude-sonnet-4-6"
    assert "Be terse" in v["simulated_user_persona"]
    assert "DONE" in v["simulated_user_persona"]


def test_simulated_user_model_falls_back_to_target_model(tmp_path):
    """Empty simulated_user_model means 'use the target's first model'.
    Cheap default for first-time setups."""
    case_dir = tmp_path / "tests/lola-eval/example"
    _write_case(case_dir)
    cfg = _build_cfg(simulated_user_model="")
    workspace = tmp_path / "workspace"

    pf = _build_promptfoo_config(
        cfg=cfg, target_root=tmp_path,
        cases=[case_dir], packs=["none"],
        workspace=workspace, concurrency=1,
    )
    v = pf["tests"][0]["vars"]
    assert v["simulated_user_model"] == "sonnet"  # = target's first model


def test_interactive_without_persona_raises(tmp_path):
    """Clear, actionable error when interactive is configured but the case
    is missing simulated_user.md. Must mention the file path."""
    case_dir = tmp_path / "tests/lola-eval/example"
    _write_case(case_dir, with_persona=False)
    cfg = _build_cfg(exec_mode="interactive")
    workspace = tmp_path / "workspace"

    with pytest.raises(ValueError, match="simulated_user.md"):
        _build_promptfoo_config(
            cfg=cfg, target_root=tmp_path,
            cases=[case_dir], packs=["none"],
            workspace=workspace, concurrency=1,
        )


def test_provider_ids_unique_per_cli_model(tmp_path):
    """Regression: promptfoo runs every test against every top-level
    provider whose id matches the test's `provider:` selector. When
    multiple (cli, model) combinations share a single provider .js
    file, that fan-out silently doubles (or worse) the row count.

    Fix: drop the top-level `providers:` list entirely and inline a
    full provider object on each test. promptfoo then has no other
    provider to fan out to, so each test runs exactly once.
    """
    case_dir = tmp_path / "tests/lola-eval/example"
    _write_case(case_dir, with_persona=False)
    # Same .js file (claude_code_provider.js) backs both models.
    cfg = LolaEvalConfig(
        targets=[TargetEntry(
            cli="claude-code", models=["sonnet", "haiku"],
            exec_mode="autonomous",
        )],
        judges=[JudgeEntry(cli="claude-code", model="sonnet")],
    )
    workspace = tmp_path / "workspace"

    pf = _build_promptfoo_config(
        cfg=cfg, target_root=tmp_path,
        cases=[case_dir], packs=["none"],
        workspace=workspace, concurrency=1,
    )

    # promptfoo's schema requires `providers:` at top level, so a single
    # placeholder MUST be present — but the real invariant we care about
    # is that every test inlines its own provider object (which then
    # overrides the placeholder, preventing fan-out). Verify both.
    assert "providers" in pf and len(pf["providers"]) == 1, (
        "exactly one placeholder top-level provider is expected; more "
        "than one would reintroduce the matrix-doubling bug"
    )
    assert len(pf["tests"]) == 2, "expected one test per (cli × model)"
    for test in pf["tests"]:
        prov = test["provider"]
        assert isinstance(prov, dict), (
            "test-level provider must be a full object (not an id string) "
            "so it overrides the top-level placeholder"
        )
        assert prov["id"].endswith("claude_code_provider.js")
        assert prov["config"]["target_model"] in {"sonnet", "haiku"}
    # The two tests target different models — confirm we didn't collapse.
    models = {t["provider"]["config"]["target_model"] for t in pf["tests"]}
    assert models == {"sonnet", "haiku"}


def test_autonomous_without_persona_is_fine(tmp_path):
    """Autonomous targets don't need simulated_user.md; the runner must
    not insist on it for back-compat with existing setups."""
    case_dir = tmp_path / "tests/lola-eval/example"
    _write_case(case_dir, with_persona=False)
    cfg = _build_cfg(exec_mode="autonomous")
    workspace = tmp_path / "workspace"

    # No exception.
    pf = _build_promptfoo_config(
        cfg=cfg, target_root=tmp_path,
        cases=[case_dir], packs=["none"],
        workspace=workspace, concurrency=1,
    )
    # Autonomous test vars must NOT carry interactive-only fields, which
    # would otherwise confuse the autonomous provider / judge.
    v = pf["tests"][0]["vars"]
    assert "max_turns" not in v
    assert "simulated_user_persona" not in v

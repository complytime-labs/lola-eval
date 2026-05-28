"""lola-eval.yaml schema validation and loader."""

from pathlib import Path
import textwrap

import pytest

from lola_eval.config import load_config, ConfigError


def test_minimal_valid_config(tmp_path: Path):
    """The smallest valid config: just `targets`. Mode 1 by default.

    Omitting `packs:` selects Mode 1 (in-repo / CI workhorse): the
    project under evaluation provisions its own packs, the harness runs
    a single pack_id="project" pass per cell.
    """
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
    """)
    )
    cfg = load_config(cfg_path)
    assert cfg.targets[0].cli == "claude-code"
    assert cfg.targets[0].models == ["sonnet"]
    assert cfg.packs is None
    assert cfg.calculate_baseline is False
    assert cfg.threshold.mode == "absolute"
    assert cfg.threshold.tolerance == 0.05
    assert cfg.threshold.timeout_is_failure is True
    assert cfg.concurrency == 4
    assert cfg.aggregation == "mean"
    assert cfg.disagreement_threshold == 0.15
    assert cfg.ci.junit_xml is True
    assert len(cfg.judges) == 1


def test_mode2_external_packs(tmp_path: Path):
    """Mode 2: explicit `packs:` list with `calculate_baseline: true`."""
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        packs:
          - example-pack@1a2b3c4d
          - threat-model@9f8e7d6c
        calculate_baseline: true
    """)
    )
    cfg = load_config(cfg_path)
    assert cfg.packs == ["example-pack@1a2b3c4d", "threat-model@9f8e7d6c"]
    assert cfg.calculate_baseline is True


def test_packs_rejects_empty_list(tmp_path: Path):
    """An empty `packs: []` is ambiguous — reject with a hint to omit instead."""
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        packs: []
    """)
    )
    with pytest.raises(ConfigError, match="cannot be an empty list"):
        load_config(cfg_path)


def test_packs_rejects_reserved_sentinels(tmp_path: Path):
    """`none` and `project` are derived pack_ids, not user-listable."""
    for sentinel in ("none", "project"):
        cfg_path = tmp_path / "lola-eval.yaml"
        cfg_path.write_text(
            textwrap.dedent(f"""
            targets:
              - cli: claude-code
                models: [sonnet]
            packs:
              - {sentinel}
        """)
        )
        with pytest.raises(ConfigError, match="reserved sentinel"):
            load_config(cfg_path)


def test_calculate_baseline_defaults_false(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
    """)
    )
    cfg = load_config(cfg_path)
    assert cfg.calculate_baseline is False


def test_legacy_singular_judge_shim(tmp_path: Path):
    """Legacy `judge: {cli, model}` accepted; wrapped as a one-element list."""
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        judge:
          cli: claude-code
          model: sonnet
    """)
    )
    cfg = load_config(cfg_path)
    assert len(cfg.judges) == 1
    assert cfg.judges[0].cli == "claude-code"


def test_invalid_threshold_mode(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        threshold:
          mode: nonsense
    """)
    )
    with pytest.raises(ConfigError, match="threshold.mode"):
        load_config(cfg_path)


def test_invalid_aggregation(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        aggregation: vote
    """)
    )
    with pytest.raises(ConfigError, match="aggregation"):
        load_config(cfg_path)


def test_missing_required_targets(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text("calculate_baseline: true\n")
    with pytest.raises(ConfigError, match="targets"):
        load_config(cfg_path)


def test_unknown_cli_value(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: aider
            models: [v0]
    """)
    )
    with pytest.raises(ConfigError, match="cli"):
        load_config(cfg_path)


def test_file_not_found(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nonexistent.yaml")


def test_disagreement_action_default(tmp_path: Path):
    """disagreement_action defaults to 'warn' (back-compat with pre-Phase-2)."""
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
    """)
    )
    cfg = load_config(cfg_path)
    assert cfg.disagreement_action == "warn"


def test_disagreement_action_fail(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        disagreement_action: fail
    """)
    )
    cfg = load_config(cfg_path)
    assert cfg.disagreement_action == "fail"


def test_invalid_disagreement_action(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        disagreement_action: panic
    """)
    )
    with pytest.raises(ConfigError, match="disagreement_action"):
        load_config(cfg_path)


def test_trimmed_mean_requires_three_judges(tmp_path: Path):
    """trimmed_mean is undefined for N<3; loader rejects the config."""
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        aggregation: trimmed_mean
        judges:
          - {cli: claude-code, model: sonnet}
          - {cli: claude-code, model: opus}
    """)
    )
    with pytest.raises(ConfigError, match="trimmed_mean.*at least 3"):
        load_config(cfg_path)


def test_interactive_target_defaults(tmp_path: Path):
    """A target with exec_mode=interactive picks sensible defaults."""
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
            exec_mode: interactive
    """)
    )
    cfg = load_config(cfg_path)
    t = cfg.targets[0]
    assert t.exec_mode == "interactive"
    assert t.max_turns == 5
    assert t.simulated_user_cli == "opencode"
    # Empty string means "fall back to target's first model" — runner
    # resolves it.
    assert t.simulated_user_model == ""


def test_interactive_target_custom_settings(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: opencode
            models: [google/gemini-2.5-pro]
            exec_mode: interactive
            max_turns: 10
            simulated_user_cli: claude-code
            simulated_user_model: claude-sonnet-4-6
    """)
    )
    cfg = load_config(cfg_path)
    t = cfg.targets[0]
    assert t.exec_mode == "interactive"
    assert t.max_turns == 10
    assert t.simulated_user_cli == "claude-code"
    assert t.simulated_user_model == "claude-sonnet-4-6"


def test_max_turns_lower_bound(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
            exec_mode: interactive
            max_turns: 0
    """)
    )
    with pytest.raises(ConfigError, match="max_turns"):
        load_config(cfg_path)


def test_autonomous_default_when_exec_mode_omitted(tmp_path: Path):
    """Existing configs without exec_mode keep their old behavior."""
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
    """)
    )
    cfg = load_config(cfg_path)
    assert cfg.targets[0].exec_mode == "autonomous"


def test_trimmed_mean_accepts_three_judges(tmp_path: Path):
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg_path.write_text(
        textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [sonnet]
        aggregation: trimmed_mean
        judges:
          - {cli: claude-code, model: sonnet}
          - {cli: claude-code, model: opus}
          - {cli: opencode, model: gemini-2.5-pro}
    """)
    )
    cfg = load_config(cfg_path)
    assert cfg.aggregation == "trimmed_mean"
    assert len(cfg.judges) == 3


class TestProfileConfigFields:
    def test_profiles_without_dir_key_is_valid(self, tmp_path: Path):
        """profiles: list no longer requires profiles_dir; directory is fixed by layout.py."""
        cfg = tmp_path / "lola-eval.yaml"
        cfg.write_text(
            textwrap.dedent("""\
            targets:
              - cli: claude-code
                models: [sonnet]
            profiles:
              - bare
        """)
        )
        config = load_config(cfg)
        assert config.profiles == ["bare"]

    def test_empty_profiles_list_rejected(self, tmp_path: Path):
        cfg = tmp_path / "lola-eval.yaml"
        cfg.write_text(
            textwrap.dedent("""\
            targets:
              - cli: claude-code
                models: [sonnet]
            profiles: []
        """)
        )
        with pytest.raises(ConfigError, match="empty"):
            load_config(cfg)

    def test_profiles_common_default(self, tmp_path: Path):
        cfg = tmp_path / "lola-eval.yaml"
        cfg.write_text(
            textwrap.dedent("""\
            targets:
              - cli: claude-code
                models: [sonnet]
            profiles:
              - bare
        """)
        )
        config = load_config(cfg)
        assert config.profiles_common == "common.yaml"

    def test_no_profile_fields_is_valid(self, tmp_path: Path):
        cfg = tmp_path / "lola-eval.yaml"
        cfg.write_text(
            textwrap.dedent("""\
            targets:
              - cli: claude-code
                models: [sonnet]
        """)
        )
        config = load_config(cfg)
        assert config.profiles is None


def _write(tmp_path, body):
    p = tmp_path / "lola-eval.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_timeouts_defaults(tmp_path: Path):
    cfg = load_config(
        _write(
            tmp_path,
            """
        targets:
          - cli: claude-code
            models: [sonnet]
    """,
        )
    )
    assert cfg.timeouts.agent_seconds == 600
    assert cfg.timeouts.runner_seconds == 3600
    assert cfg.timeouts.judge_fanout_seconds == 600
    assert cfg.timeouts.judge_subprocess_base_seconds == 120
    assert cfg.timeouts.heartbeat_seconds == 30


def test_timeouts_custom_override(tmp_path: Path):
    cfg = load_config(
        _write(
            tmp_path,
            """
        targets:
          - cli: claude-code
            models: [sonnet]
        timeouts:
          agent_seconds: 1800
          runner_seconds: 14400
          judge_fanout_seconds: 900
          judge_subprocess_base_seconds: 300
          heartbeat_seconds: 15
    """,
        )
    )
    assert cfg.timeouts.agent_seconds == 1800
    assert cfg.timeouts.runner_seconds == 14400
    assert cfg.timeouts.heartbeat_seconds == 15


def test_timeouts_runner_smaller_than_row_budget_is_flagged(tmp_path: Path):
    with pytest.raises(ConfigError) as e:
        load_config(
            _write(
                tmp_path,
                """
            targets:
              - cli: claude-code
                models: [sonnet]
            timeouts:
              agent_seconds: 600
              judge_fanout_seconds: 600
              runner_seconds: 800
        """,
            )
        )
    msg = str(e.value)
    assert "runner_seconds" in msg
    assert "1200" in msg  # the required minimum (agent+fanout)


def test_timeouts_fanout_below_subprocess_base_is_flagged(tmp_path: Path):
    with pytest.raises(ConfigError) as e:
        load_config(
            _write(
                tmp_path,
                """
            targets:
              - cli: claude-code
                models: [sonnet]
            timeouts:
              judge_fanout_seconds: 60
              judge_subprocess_base_seconds: 120
              runner_seconds: 3600
        """,
            )
        )
    assert "judge_fanout_seconds" in str(e.value)


def test_old_timeout_keys_rejected_with_migration_hint(tmp_path: Path):
    with pytest.raises(ConfigError) as e:
        load_config(
            _write(
                tmp_path,
                """
            targets:
              - cli: claude-code
                models: [sonnet]
            runner_timeout_seconds: 3600
        """,
            )
        )
    msg = str(e.value)
    assert "timeouts.runner_seconds" in msg


def test_old_judge_timeout_key_rejected_with_migration_hint(tmp_path: Path):
    with pytest.raises(ConfigError) as e:
        load_config(
            _write(
                tmp_path,
                """
            targets:
              - cli: claude-code
                models: [sonnet]
            judge_timeout_seconds: 600
        """,
            )
        )
    assert "timeouts.judge_fanout_seconds" in str(e.value)


def test_timeouts_heartbeat_not_below_agent_is_flagged(tmp_path: Path):
    with pytest.raises(ConfigError) as e:
        load_config(
            _write(
                tmp_path,
                """
            targets:
              - cli: claude-code
                models: [sonnet]
            timeouts:
              agent_seconds: 20
              heartbeat_seconds: 30
              judge_fanout_seconds: 600
              runner_seconds: 3600
        """,
            )
        )
    assert "heartbeat_seconds" in str(e.value)


def test_removed_path_keys_are_rejected(tmp_path):
    from lola_eval.config import load_config, ConfigError

    p = tmp_path / "config.yaml"
    p.write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "results_dir: .lola-eval\n"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert "results_dir" in str(exc.value)


def test_profiles_enabled_by_list_without_dir_key(tmp_path):
    from lola_eval.config import load_config

    p = tmp_path / "config.yaml"
    p.write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "profiles: [greet]\n"
    )
    cfg = load_config(p)  # must NOT raise (old code required profiles_dir)
    assert cfg.profiles == ["greet"]

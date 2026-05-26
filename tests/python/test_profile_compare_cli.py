"""End-to-end smoke for `lola-eval profile-compare` against a temp runs.db."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from lola_eval import store
from lola_eval.cli import app

runner = CliRunner()


def _seed_row(db: Path, profile_id: str, composite: float) -> None:
    store.insert_run(db, {
        "run_id": f"r-{profile_id}",
        "timestamp": "2026-05-25T00:00:00Z",
        "fingerprint": f"fp-{profile_id}",
        "target_cli": "claude-code",
        "target_model": "haiku",
        "target_cli_ver": "1",
        "pack_id": "project",
        "profile_id": profile_id,
        "task_id": "case-greeting",
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "headless",
        "invocation": "passive",
        "judge_cli": "claude-code",
        "judge_model": "sonnet",
        "scores_json": json.dumps({"composite": composite}),
        "transcript_path": "/dev/null",
        "exit_status": "success",
    })


def _write_config(tmp_path: Path) -> Path:
    lola_dir = tmp_path / ".lola-eval"
    lola_dir.mkdir(exist_ok=True)
    profiles_dir = lola_dir / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "greet.yaml").write_text(textwrap.dedent("""
        name: greet
        compatible_targets: [claude-code]
        setup:
          claude-code:
            install_modules: [greeter-mod]
    """).strip() + "\n")
    (profiles_dir / "greet-salute.yaml").write_text(textwrap.dedent("""
        name: greet-salute
        compatible_targets: [claude-code]
        setup:
          claude-code:
            install_modules: [greeter-mod, salute-mod]
    """).strip() + "\n")
    cfg = lola_dir / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        targets:
          - cli: claude-code
            models: [haiku]
        judges:
          - {cli: claude-code, model: sonnet}
        profiles: [greet, greet-salute]
    """).strip() + "\n")
    return cfg


def test_profile_compare_flags_conflict(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _write_config(tmp_path)
    db = tmp_path / ".lola-eval" / "out" / "runs.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    store.init_db(db)
    _seed_row(db, "greet", 0.9)
    _seed_row(db, "greet-salute", 0.3)

    result = runner.invoke(app, ["profile-compare", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "Conflicts detected" in result.output
    assert "salute-mod" in result.output


def test_profile_compare_no_conflict_happy_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _write_config(tmp_path)
    db = tmp_path / ".lola-eval" / "out" / "runs.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    store.init_db(db)
    _seed_row(db, "greet", 0.8)
    _seed_row(db, "greet-salute", 0.85)  # superset scores higher: no conflict

    result = runner.invoke(app, ["profile-compare", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "No conflicts detected" in result.output


def test_profile_compare_missing_db_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _write_config(tmp_path)
    result = runner.invoke(app, ["profile-compare", "--config", str(cfg)])
    assert result.exit_code == 2


def test_profile_compare_malformed_config_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lola_dir = tmp_path / ".lola-eval"
    lola_dir.mkdir()
    cfg = lola_dir / "config.yaml"
    cfg.write_text("targets: []\n")  # min_length=1 violated -> ConfigError
    result = runner.invoke(app, ["profile-compare", "--config", str(cfg)])
    assert result.exit_code == 2
    assert "config error" in result.output

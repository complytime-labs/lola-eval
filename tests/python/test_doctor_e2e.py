"""End-to-end coverage of `lola-eval doctor` invoked inside a target
repo. Asserts fixture-validation problems propagate from
_validate_fixture through _check_target_repo into the CliRunner output."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lola_eval.cli import app

runner = CliRunner()


def _make_target(tmp_path: Path, weights_sum: float = 1.0) -> Path:
    """Create a minimal well-formed target repo."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "lola-eval.yaml").write_text(
        "targets:\n"
        "  - cli: claude-code\n"
        "    models: [sonnet]\n"
    )
    case = target / "tests/lola-eval/case-x"
    case.mkdir(parents=True)
    (case / "task.yaml").write_text("task_version: '1'\ntimeout_seconds: 60\n")
    (case / "prompt.md").write_text("noop")
    half = weights_sum * 0.5
    weights_block = f"weights:\n  coverage: {half}\n  structure: {half}\n"
    (case / "rubric.md").write_text(
        "---\nrubric_version: '1'\npass_threshold: 0.6\n" + weights_block + "---\n"
    )
    (case / "starter").mkdir()
    return target


def test_doctor_inside_clean_target_passes(tmp_path: Path, monkeypatch):
    """Clean target repo (all fixtures well-formed) exits 0 with OK.

    Bundle-health checks (engines compat, version pins) are stubbed out
    so the assertion is sensitive only to target-repo state: a developer
    box whose bundled Node lags the manifest must not break this test.
    """
    target = _make_target(tmp_path, weights_sum=1.0)
    monkeypatch.chdir(target)
    monkeypatch.setattr(
        "lola_eval.cli.doctor_cmd._check_engines_compatibility",
        lambda _msg: ["  [OK] promptfoo engines  (stubbed in test)"],
    )
    monkeypatch.setattr(
        "lola_eval.cli.doctor_cmd._check_bundle_versions_pinned",
        lambda: ["  [OK] bundle pin  (stubbed in test)"],
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "result: OK" in result.stdout


def test_doctor_flags_weights_sum_mismatch(tmp_path: Path, monkeypatch):
    """Fixture with weights not summing to 1.0 triggers [ERR] and exits non-zero.

    Fixture problems are authoring bugs that CI must catch before paying for
    LLM runs — they cannot be non-fatal.
    """
    target = _make_target(tmp_path, weights_sum=0.8)  # 0.4 + 0.4 = 0.8
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["doctor"])
    assert "weights" in result.stdout.lower()
    assert result.exit_code != 0


def test_doctor_flags_missing_starter(tmp_path: Path, monkeypatch):
    """Missing starter/ directory triggers [ERR] and exits non-zero."""
    target = _make_target(tmp_path)
    (target / "tests/lola-eval/case-x/starter").rmdir()
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["doctor"])
    assert "starter" in result.stdout.lower()
    assert result.exit_code != 0


def test_doctor_flags_missing_prompt(tmp_path: Path, monkeypatch):
    """Missing prompt.md triggers [ERR] and exits non-zero."""
    target = _make_target(tmp_path)
    (target / "tests/lola-eval/case-x/prompt.md").unlink()
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["doctor"])
    assert "prompt" in result.stdout.lower()
    assert result.exit_code != 0

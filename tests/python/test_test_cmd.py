"""CLI-level tests for ``lola-eval test``.

Covers I3 (--estimate-cost) and I4 (disagreement_threshold warning).
The full happy-path is exercised by the integration suite under
``tests/integration/test_lola_eval_test.py``; the tests here are
fast, hermetic, and avoid spawning ``promptfoo``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lola_eval.cli import app
from lola_eval.threshold import RowResult


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """``lola-eval test`` mutates ``LOLA_RESULTS_DIR`` via
    ``_activate_target_env``; without explicit isolation that leaks into
    every later test in the same process, breaking trajectory_judge
    fixtures that call ``xdg.resolve_db_path``.

    monkeypatch.delenv only records a restore action if the var was set
    at fixture time, so we ``setenv`` to a sentinel first to force the
    snapshot, then ``delenv`` to clear it for the test body. Teardown
    then restores whatever was in the parent env (typically nothing)."""
    for var in ("LOLA_RESULTS_DIR", "LOLA_DB_PATH"):
        monkeypatch.setenv(var, "")
        monkeypatch.delenv(var, raising=False)


_VALID_CONFIG = """\
targets:
  - cli: claude-code
    models: [sonnet, haiku]
packs: [example-pack]
calculate_baseline: true
threshold:
  mode: absolute
tests_dir: tests/lola-eval
results_dir: .lola-eval
judges:
  - {cli: claude-code, model: sonnet}
  - {cli: opencode, model: haiku}
disagreement_threshold: 0.20
ci:
  junit_xml: false
  github_summary: false
  html_report: false
"""


def _seed_target(tmp_path: Path) -> Path:
    (tmp_path / "lola-eval.yaml").write_text(_VALID_CONFIG)
    cases = tmp_path / "tests/lola-eval"
    cases.mkdir(parents=True)
    (cases / "case-a").mkdir()
    (cases / "case-b").mkdir()
    (cases / "case-c").mkdir()  # 3 cases
    return tmp_path


def test_estimate_cost_prints_breakdown(tmp_path, monkeypatch):
    """I3: --estimate-cost prints the upper-bound and exits 0 without
    running the matrix.

    config: 1 target * 2 models * (1 pack + 1 baseline) * 3 cases = 12 rows
            * (1 agent + 2 judges) = 36 calls
            * $2.50/call = $90.00
    """
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)

    r = CliRunner().invoke(app, ["test", "--estimate-cost"])
    assert r.exit_code == 0, r.output
    out = r.output
    assert "Mode 2" in out
    assert "cases:    3" in out
    assert "targets:  1" in out
    assert "cells:    2" in out
    assert "packs:    1" in out
    assert "baseline: on" in out
    assert "rows:     12" in out
    assert "judges:   2" in out
    assert "per-call: $2.50" in out
    assert "TOTAL:    $90.00" in out


def test_estimate_cost_does_not_invoke_runner(tmp_path, monkeypatch):
    """I3: the runner must not be called when --estimate-cost is set."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)

    called = {"n": 0}

    def fake_run_matrix(*args, **kwargs):
        called["n"] += 1
        return []

    from lola_eval import runner
    monkeypatch.setattr(runner, "run_matrix", fake_run_matrix)

    r = CliRunner().invoke(app, ["test", "--estimate-cost"])
    assert r.exit_code == 0, r.output
    assert called["n"] == 0


def test_disagreement_warning_emitted_when_threshold_exceeded(tmp_path, monkeypatch):
    """I4: rows whose judge_disagreement exceeds cfg.disagreement_threshold
    produce a stderr warning. Exit code is unchanged (informational only)."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)

    high_disagreement_row = RowResult(
        cli="claude-code", model="sonnet",
        task_id="case-a", pack_id="none",
        composite=0.9, rubric_pass_threshold=0.5,
        timed_out=False, judge_disagreement=0.42,  # > 0.20 threshold
    )
    low_disagreement_row = RowResult(
        cli="claude-code", model="haiku",
        task_id="case-b", pack_id="none",
        composite=0.85, rubric_pass_threshold=0.5,
        timed_out=False, judge_disagreement=0.05,  # below threshold
    )
    no_disagreement_row = RowResult(
        cli="claude-code", model="sonnet",
        task_id="case-c", pack_id="none",
        composite=0.85, rubric_pass_threshold=0.5,
        timed_out=False, judge_disagreement=None,  # single-judge fallback
    )

    from lola_eval import runner
    monkeypatch.setattr(
        runner, "run_matrix",
        lambda *a, **kw: [high_disagreement_row, low_disagreement_row, no_disagreement_row],
    )

    r = CliRunner().invoke(app, ["test"])
    assert r.exit_code == 0, r.output
    # Only the high-disagreement row triggers the warning.
    assert "judge disagreement on claude-code/sonnet/case-a/none" in r.output
    assert "case-b" not in r.output
    assert "case-c" not in r.output


def test_disagreement_warning_does_not_change_exit_code(tmp_path, monkeypatch):
    """I4: even with sky-high disagreement, exit code follows the
    threshold engine — disagreement is signal, not pass/fail."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)

    failing_row_with_disagreement = RowResult(
        cli="claude-code", model="sonnet",
        task_id="case-a", pack_id="none",
        composite=0.10,  # below the rubric threshold; will fail
        rubric_pass_threshold=0.5,
        timed_out=False, judge_disagreement=0.99,
    )
    from lola_eval import runner
    monkeypatch.setattr(
        runner, "run_matrix",
        lambda *a, **kw: [failing_row_with_disagreement],
    )

    r = CliRunner().invoke(app, ["test"])
    # Threshold-driven failure; the disagreement warning is also present
    # but does not change exit code 1.
    assert r.exit_code == 1
    assert "judge disagreement" in r.output
    assert "Failures:" in r.output


def test_runner_error_surfaces_as_setup_error(tmp_path, monkeypatch):
    """C3/UX1: RunnerError raised by run_matrix becomes 'setup error: ...'
    on stderr with exit 2 — no Python traceback for the user."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)

    from lola_eval import runner

    def fake_run_matrix(*a, **kw):
        raise runner.RunnerError(
            "matrix is empty after filters (cases=0, packs=2); nothing to run"
        )
    monkeypatch.setattr(runner, "run_matrix", fake_run_matrix)

    r = CliRunner().invoke(app, ["test"])
    assert r.exit_code == 2
    assert "setup error" in r.output
    assert "matrix is empty" in r.output
    # No traceback leaked.
    assert "Traceback" not in r.output


def test_value_error_in_runner_surfaces_as_setup_error(tmp_path, monkeypatch):
    """UX1: malformed-rubric ValueError -> setup error, not traceback."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)

    from lola_eval import runner

    def fake_run_matrix(*a, **kw):
        raise ValueError("rubric.md: missing frontmatter")
    monkeypatch.setattr(runner, "run_matrix", fake_run_matrix)

    r = CliRunner().invoke(app, ["test"])
    assert r.exit_code == 2
    assert "setup error" in r.output
    assert "missing frontmatter" in r.output
    assert "Traceback" not in r.output


def test_empty_matrix_after_filters_is_runner_error(tmp_path, monkeypatch):
    """C3: filter combination that yields zero packs/cases must raise
    RunnerError so the CLI returns exit 2 instead of silent green."""
    from lola_eval.config import load_config
    from lola_eval.runner import run_matrix, RunnerError

    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)
    cfg = load_config(target / "lola-eval.yaml")

    # case_filter pointing at a name that doesn't exist -> empty cases.
    with pytest.raises(RunnerError, match="matrix is empty"):
        run_matrix(cfg, target, case_filter="nonexistent-case")


def test_html_report_hint_appears_on_failure(tmp_path, monkeypatch):
    """UX11: when a row fails AND html_report is enabled, the failure
    block must point at the generated HTML so reviewers can find it."""
    cfg_with_html = _VALID_CONFIG.replace(
        "html_report: false", "html_report: true",
    )
    (tmp_path / "lola-eval.yaml").write_text(cfg_with_html)
    cases = tmp_path / "tests/lola-eval"
    cases.mkdir(parents=True)
    for n in ("case-a", "case-b", "case-c"):
        (cases / n).mkdir()
    monkeypatch.chdir(tmp_path)

    failing_row = RowResult(
        cli="claude-code", model="sonnet",
        task_id="case-a", pack_id="none",
        composite=0.10, rubric_pass_threshold=0.5,
    )
    from lola_eval import runner, report as report_mod
    monkeypatch.setattr(runner, "run_matrix", lambda *a, **kw: [failing_row])
    # Stub HTML rendering so the test does not exercise the full report
    # pipeline (fingerprints, sqlite, etc.). Just ensure the file lands.
    def _stub_build_html(out_path, **_kw):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("<html/>")
    monkeypatch.setattr(report_mod, "build_html", _stub_build_html)

    r = CliRunner().invoke(app, ["test"])
    assert r.exit_code == 1
    assert "Failures:" in r.output
    assert "See " in r.output
    assert ".lola-eval/reports/" in r.output
    assert "judge's per-row rationale" in r.output


def test_summary_line_emitted_on_success(tmp_path, monkeypatch):
    """Successful runs should print a one-line summary so the operator
    sees row/failure/timeout counts even without rich promptfoo output."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)

    passing = RowResult(
        cli="claude-code", model="sonnet",
        task_id="case-a", pack_id="none",
        composite=0.95, rubric_pass_threshold=0.5,
    )
    from lola_eval import runner
    monkeypatch.setattr(runner, "run_matrix", lambda *a, **kw: [passing])

    r = CliRunner().invoke(app, ["test"])
    assert r.exit_code == 0, r.output
    # CliRunner merges stderr into r.output in this click version, so the
    # summary line lands there.
    assert "[lola-eval-test] 1 rows complete; 0 failures; 0 timeouts" in r.output


def test_summary_line_emitted_on_failure(tmp_path, monkeypatch):
    """Summary line must precede the failure block so log scrapers can
    pick up the counts regardless of exit code."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)

    failing = RowResult(
        cli="claude-code", model="sonnet",
        task_id="case-a", pack_id="none",
        composite=0.10, rubric_pass_threshold=0.5,
    )
    from lola_eval import runner
    monkeypatch.setattr(runner, "run_matrix", lambda *a, **kw: [failing])

    r = CliRunner().invoke(app, ["test"])
    assert r.exit_code == 1
    assert "[lola-eval-test] 1 rows complete; 1 failures; 0 timeouts" in r.output
    # Summary must appear before the per-failure detail block.
    assert r.output.index("[lola-eval-test]") < r.output.index("Failures:")


def test_html_report_hint_not_emitted_when_no_failures(tmp_path, monkeypatch):
    """UX11: hint only fires alongside failures, never on a green run."""
    cfg_with_html = _VALID_CONFIG.replace(
        "html_report: false", "html_report: true",
    )
    (tmp_path / "lola-eval.yaml").write_text(cfg_with_html)
    cases = tmp_path / "tests/lola-eval"
    cases.mkdir(parents=True)
    for n in ("case-a", "case-b", "case-c"):
        (cases / n).mkdir()
    monkeypatch.chdir(tmp_path)

    passing_row = RowResult(
        cli="claude-code", model="sonnet",
        task_id="case-a", pack_id="none",
        composite=0.95, rubric_pass_threshold=0.5,
    )
    from lola_eval import runner, report as report_mod
    monkeypatch.setattr(runner, "run_matrix", lambda *a, **kw: [passing_row])
    def _stub_build_html(out_path, **_kw):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("<html/>")
    monkeypatch.setattr(report_mod, "build_html", _stub_build_html)

    r = CliRunner().invoke(app, ["test"])
    assert r.exit_code == 0
    assert "judge's per-row rationale" not in r.output

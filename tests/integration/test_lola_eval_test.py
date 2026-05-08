"""End-to-end test of `lola-eval test` against a stubbed provider.

Requires `promptfoo` on PATH (or invocable as `npx promptfoo`). The runner
calls `promptfoo` as a subprocess, so without the binary the test cannot
exercise the full code path. When unavailable, the test is skipped.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_TARGET = REPO_ROOT / "tests/integration/fixtures/sample-target"
STUB_FIXTURES = REPO_ROOT / "tests/integration/fixtures/canned"
STUB_PROVIDER = REPO_ROOT / "tests/integration/fixtures/stub_provider.js"


def _resolve_local_promptfoo() -> str | None:
    """Locate a runnable promptfoo binary independent of cwd.

    The integration test copies the target into tmp_path which has no
    node_modules, so we have to point the runner at this repo's local
    promptfoo install (or a system-wide one) explicitly.
    """
    on_path = shutil.which("promptfoo")
    if on_path:
        return on_path
    local = REPO_ROOT / "node_modules" / ".bin" / "promptfoo"
    if local.exists():
        return str(local)
    return None


PROMPTFOO_BIN = _resolve_local_promptfoo()
pytestmark = pytest.mark.skipif(
    PROMPTFOO_BIN is None,
    reason="promptfoo binary not found on PATH or in node_modules/.bin",
)


@pytest.fixture
def target_dir(tmp_path):
    dst = tmp_path / "target"
    shutil.copytree(SAMPLE_TARGET, dst)
    return dst


def _run_lola_eval(*args, cwd, env_extra=None):
    env = {
        **os.environ,
        "LOLA_STUB_FIXTURES": str(STUB_FIXTURES),
        "LOLA_PROMPTFOO_BIN": PROMPTFOO_BIN or "",
        "LOLA_PROVIDER_OVERRIDE": str(STUB_PROVIDER),
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "lola_eval", *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


@pytest.mark.integration
def test_absolute_mode_pass(target_dir):
    proc = _run_lola_eval("test", cwd=target_dir)
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert (target_dir / ".lola-eval/junit.xml").exists()


@pytest.mark.integration
def test_absolute_mode_fail_below_threshold(target_dir, tmp_path):
    bad_fixtures = tmp_path / "bad_fixtures"
    bad_fixtures.mkdir()
    for name in ["case-stub__none.json", "case-stub__example-pack@stubsha.json"]:
        original = json.loads((STUB_FIXTURES / name).read_text())
        original["scores"]["correctness"] = 0.10
        original["scores"]["composite"] = 0.10
        (bad_fixtures / name).write_text(json.dumps(original))
    proc = _run_lola_eval("test", cwd=target_dir, env_extra={"LOLA_STUB_FIXTURES": str(bad_fixtures)})
    assert proc.returncode == 1, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"


@pytest.mark.integration
def test_regression_mode_missing_baseline(target_dir):
    cfg = (target_dir / "lola-eval.yaml").read_text()
    cfg = cfg.replace("mode: absolute", "mode: regression")
    (target_dir / "lola-eval.yaml").write_text(cfg)
    proc = _run_lola_eval("test", cwd=target_dir)
    assert proc.returncode == 2
    assert "baseline" in proc.stderr.lower()


@pytest.mark.integration
def test_runs_db_lands_in_target_results_dir(target_dir, tmp_path, monkeypatch):
    """C1: runs.db must be written to <target>/.lola-eval/runs.db, NOT XDG.

    Regression test for the embeddable-runner pivot's central premise. If
    two CI projects share a runner host they must not commingle results.
    We point XDG_STATE_HOME at an isolated tmp dir and assert the judge
    writes nothing under it (it should land under the target instead).
    """
    isolated_xdg = tmp_path / "xdg-state"
    isolated_xdg.mkdir()
    proc = _run_lola_eval(
        "test", cwd=target_dir,
        env_extra={"XDG_STATE_HOME": str(isolated_xdg)},
    )
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"

    target_db = target_dir / ".lola-eval" / "runs.db"
    xdg_db = isolated_xdg / "lola-eval" / "runs.db"
    assert target_db.exists(), f"runs.db missing in target results_dir: {target_db}"
    assert not xdg_db.exists(), (
        f"runs.db leaked into XDG state at {xdg_db}; pivot regression."
    )


@pytest.mark.integration
def test_html_report_lands_in_target_reports_dir(target_dir, tmp_path):
    """C2/C3: when ci.html_report is true, the report lands under
    <target>/.lola-eval/reports/<timestamp>.html — not XDG."""
    cfg = (target_dir / "lola-eval.yaml").read_text()
    cfg = cfg.replace("html_report: false", "html_report: true")
    (target_dir / "lola-eval.yaml").write_text(cfg)

    isolated_xdg = tmp_path / "xdg-state"
    isolated_xdg.mkdir()
    proc = _run_lola_eval(
        "test", cwd=target_dir,
        env_extra={"XDG_STATE_HOME": str(isolated_xdg)},
    )
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"

    reports_dir = target_dir / ".lola-eval" / "reports"
    assert reports_dir.exists()
    html_files = list(reports_dir.glob("*.html"))
    assert len(html_files) == 1, f"expected exactly one HTML report, got {html_files}"
    # Must NOT have leaked into XDG.
    assert not (isolated_xdg / "lola-eval" / "reports").exists(), (
        "HTML report leaked into XDG state."
    )


@pytest.mark.integration
def test_init_exits_2_on_existing_config(target_dir):
    """I1: spec mandates exit 2 (setup error) when lola-eval.yaml already
    exists and --force was not passed."""
    proc = _run_lola_eval("init", cwd=target_dir)
    assert proc.returncode == 2, (
        f"expected exit 2, got {proc.returncode}. stdout: {proc.stdout} stderr: {proc.stderr}"
    )


@pytest.mark.integration
def test_disagreement_threshold_warning(target_dir, tmp_path):
    """I4: when a row's judge_disagreement exceeds cfg.disagreement_threshold,
    `lola-eval test` emits a stderr warning. Exit code is unaffected."""
    # Lower the threshold below what we'll inject so the warning fires;
    # also ensure two judges declared (so a non-stub run would aggregate;
    # stub envelopes carry their own disagreement value below).
    cfg = (target_dir / "lola-eval.yaml").read_text()
    cfg = cfg.replace(
        "judges:\n  - {cli: claude-code, model: stub-sonnet}",
        "judges:\n  - {cli: claude-code, model: stub-sonnet}\n"
        "  - {cli: opencode, model: stub-haiku}\n"
        "disagreement_threshold: 0.10",
    )
    (target_dir / "lola-eval.yaml").write_text(cfg)

    # Inject high disagreement into the stub envelopes used by both packs.
    high_disagreement_fixtures = tmp_path / "fixtures-high-disagreement"
    high_disagreement_fixtures.mkdir()
    for name in ("case-stub__none.json", "case-stub__example-pack@stubsha.json"):
        original = json.loads((STUB_FIXTURES / name).read_text())
        original["judge_disagreement"] = 0.42  # > 0.10 threshold
        (high_disagreement_fixtures / name).write_text(json.dumps(original))

    proc = _run_lola_eval(
        "test", cwd=target_dir,
        env_extra={"LOLA_STUB_FIXTURES": str(high_disagreement_fixtures)},
    )
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert "judge disagreement on" in proc.stderr
    assert "0.42" in proc.stderr or "0.420" in proc.stderr
    assert "threshold 0.100" in proc.stderr


@pytest.mark.integration
def test_test_accepts_explicit_config_path(target_dir, tmp_path):
    """I2: --config <path> must work when invoked from a different cwd.

    We move the config into a sibling dir, run from a parent that has no
    lola-eval.yaml, and pass --config so the test still finds and uses it.
    """
    # Run from tmp_path (not target_dir); pass --config explicitly.
    cfg_path = target_dir / "lola-eval.yaml"
    proc = _run_lola_eval("test", "--config", str(cfg_path), cwd=tmp_path)
    assert proc.returncode == 0, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    # Results still landed in the target's .lola-eval/, not in tmp_path.
    assert (target_dir / ".lola-eval" / "runs.db").exists()
    assert not (tmp_path / ".lola-eval").exists()


@pytest.mark.integration
def test_disagreement_action_fail(target_dir, tmp_path):
    """Variance-aware: disagreement_action='fail' converts a high-disagreement
    row into a row-level failure (exit 1), distinct from infrastructure
    failures (exit 3). Composite is still reported truthfully."""
    cfg = (target_dir / "lola-eval.yaml").read_text()
    cfg = cfg.replace(
        "judges:\n  - {cli: claude-code, model: stub-sonnet}",
        "judges:\n  - {cli: claude-code, model: stub-sonnet}\n"
        "  - {cli: opencode, model: stub-haiku}\n"
        "disagreement_threshold: 0.10\n"
        "disagreement_action: fail",
    )
    (target_dir / "lola-eval.yaml").write_text(cfg)

    high_disagreement_fixtures = tmp_path / "fixtures-high-disagreement-fail"
    high_disagreement_fixtures.mkdir()
    for name in ("case-stub__none.json", "case-stub__example-pack@stubsha.json"):
        original = json.loads((STUB_FIXTURES / name).read_text())
        original["judge_disagreement"] = 0.42  # > 0.10 threshold
        (high_disagreement_fixtures / name).write_text(json.dumps(original))

    proc = _run_lola_eval(
        "test", cwd=target_dir,
        env_extra={"LOLA_STUB_FIXTURES": str(high_disagreement_fixtures)},
    )
    # Exit 1 = row-level failure (not 3, which would be infra). Stderr must
    # name the failure_kind so the user knows why a high-composite row failed.
    assert proc.returncode == 1, f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert "judge_disagreement" in proc.stderr
    # The "warn" path's emoji warning should NOT fire under action=fail
    # (the failure list already carries the message).
    assert "judge disagreement on" not in proc.stderr

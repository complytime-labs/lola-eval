"""CLI-level tests for ``lola-eval clean``.

Unit-level coverage for ``clean_dirs`` lives in ``test_doctor.py``; this
file exercises the typer wrapper that loads ``lola-eval.yaml`` and routes
to the target-aware path. IM3 of the post-fix review.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lola_eval.cli import app


_VALID_CONFIG = """\
targets:
  - cli: claude-code
    models: [stub]
threshold:
  mode: absolute
tests_dir: tests/lola-eval
results_dir: .lola-eval
judges:
  - {cli: claude-code, model: stub}
"""


def _seed_target(tmp_path: Path) -> Path:
    """Lay down a target repo with a populated .lola-eval/ tree."""
    (tmp_path / "lola-eval.yaml").write_text(_VALID_CONFIG)
    results = tmp_path / ".lola-eval"
    (results / "workspace").mkdir(parents=True)
    (results / "workspace" / "pf.yaml").write_text("stale")
    (results / "transcripts").mkdir()
    (results / "transcripts" / "t.jsonl").write_text("...")
    (results / "reports").mkdir()
    (results / "reports" / "old.html").write_text("<html/>")
    (results / "runs.db").write_text("DB")
    (results / "last-run.json").write_text("[]")
    (results / "baseline.json").write_text("{}")
    return tmp_path


def test_clean_cache_in_target_repo(tmp_path, monkeypatch):
    """`lola-eval clean --cache` from a target repo wipes regenerable
    artifacts but leaves runs.db and baseline.json intact."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)
    r = CliRunner().invoke(app, ["clean", "--cache"])
    assert r.exit_code == 0, r.output

    results = target / ".lola-eval"
    assert not (results / "workspace").exists()
    assert not (results / "transcripts").exists()
    assert not (results / "reports").exists()
    assert (results / "runs.db").exists()
    assert (results / "baseline.json").exists()


def test_clean_state_in_target_repo(tmp_path, monkeypatch):
    """`lola-eval clean --state` wipes runs.db + last-run.json but
    preserves baseline.json (the user committed it)."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)
    r = CliRunner().invoke(app, ["clean", "--state"])
    assert r.exit_code == 0, r.output

    results = target / ".lola-eval"
    assert not (results / "runs.db").exists()
    assert not (results / "last-run.json").exists()
    assert (results / "baseline.json").exists()


def test_clean_in_target_repo_with_broken_config_exits_2(tmp_path, monkeypatch):
    """A malformed lola-eval.yaml must produce a clean exit-2 error,
    not a pydantic traceback."""
    (tmp_path / "lola-eval.yaml").write_text("targets: not-a-list\n")
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["clean", "--cache"])
    assert r.exit_code == 2
    assert "config error" in (r.output + (r.stderr or "")).lower()


def test_clean_with_no_flags_exits_2_with_hint(tmp_path, monkeypatch):
    """UX8: `lola-eval clean` with no flags must not silently exit 0.
    It must print a usage hint and exit 2."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)
    r = CliRunner().invoke(app, ["clean"])
    assert r.exit_code == 2
    out = r.output + (r.stderr or "")
    assert "--cache" in out
    assert "--state" in out

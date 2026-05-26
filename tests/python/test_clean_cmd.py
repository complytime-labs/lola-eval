"""CLI-level tests for ``lola-eval clean``.

Unit-level coverage for ``clean_dirs`` lives in ``test_doctor.py``; this
file exercises the typer wrapper that loads ``config.yaml`` and routes
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
judges:
  - {cli: claude-code, model: stub}
"""


def _seed_target(tmp_path: Path) -> Path:
    """Lay down a target repo with a populated .lola-eval/ tree."""
    eval_dir = tmp_path / ".lola-eval"
    (eval_dir).mkdir(parents=True)
    (eval_dir / "config.yaml").write_text(_VALID_CONFIG)
    out = eval_dir / "out"
    (out / "workspace").mkdir(parents=True)
    (out / "workspace" / "pf.yaml").write_text("stale")
    (out / "transcripts").mkdir()
    (out / "transcripts" / "t.jsonl").write_text("...")
    (out / "reports").mkdir()
    (out / "reports" / "old.html").write_text("<html/>")
    (out / "runs.db").write_text("DB")
    (out / "last-run.json").write_text("[]")
    # baseline lives at eval_dir level, not under out/
    (eval_dir / "baseline.json").write_text("{}")
    return tmp_path


def test_clean_cache_in_target_repo(tmp_path, monkeypatch):
    """`lola-eval clean --cache` from a target repo wipes regenerable
    artifacts but leaves runs.db and baseline.json intact."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)
    r = CliRunner().invoke(app, ["clean", "--cache"])
    assert r.exit_code == 0, r.output

    out = target / ".lola-eval" / "out"
    assert not (out / "workspace").exists()
    assert not (out / "transcripts").exists()
    assert not (out / "reports").exists()
    assert (out / "runs.db").exists()
    assert (target / ".lola-eval" / "baseline.json").exists()


def test_clean_state_in_target_repo(tmp_path, monkeypatch):
    """`lola-eval clean --state` wipes runs.db + last-run.json but
    preserves baseline.json (the user committed it)."""
    target = _seed_target(tmp_path)
    monkeypatch.chdir(target)
    r = CliRunner().invoke(app, ["clean", "--state"])
    assert r.exit_code == 0, r.output

    out = target / ".lola-eval" / "out"
    assert not (out / "runs.db").exists()
    assert not (out / "last-run.json").exists()
    assert (target / ".lola-eval" / "baseline.json").exists()


def test_clean_with_missing_config_exits_2(tmp_path, monkeypatch):
    """No .lola-eval/config.yaml present: setup error → exit 2."""
    monkeypatch.chdir(tmp_path)  # empty dir, no .lola-eval/config.yaml
    r = CliRunner().invoke(app, ["clean", "--cache"])
    assert r.exit_code == 2
    assert "error" in (r.output + (r.stderr or "")).lower()


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

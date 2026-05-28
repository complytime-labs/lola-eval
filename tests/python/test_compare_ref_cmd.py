"""`lola-eval compare-ref` CLI."""

from __future__ import annotations

import subprocess as _sp

from typer.testing import CliRunner

from lola_eval import compare_ref as cr
from lola_eval.cli import app


def _git(cwd, *args):
    _sp.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    lola_dir = repo / ".lola-eval"
    lola_dir.mkdir()
    (lola_dir / "config.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    _git(repo, "add", ".lola-eval")
    _git(repo, "commit", "-m", "c1")
    (repo / "x.txt").write_text("x")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-m", "c2")
    return repo


def test_compare_ref_cli_renders_diff(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    # Stub the per-ref eval so no matrix runs.
    def stub_at_ref(repo_root, ref, config_rel, **kw):
        return {"claude-code/sonnet/case-001/project": 0.70 if ref == "HEAD~1" else 0.90}

    monkeypatch.setattr(cr, "_eval_at_ref", stub_at_ref)
    res = CliRunner().invoke(
        app,
        ["compare-ref", "HEAD~1", "HEAD", "--config", str(repo / ".lola-eval" / "config.yaml")],
    )
    assert res.exit_code == 0, res.output
    assert "HEAD~1" in res.output and "HEAD" in res.output
    assert "+0.20" in res.output


def test_compare_ref_cli_errors_when_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lola_dir = tmp_path / ".lola-eval"
    lola_dir.mkdir()
    (lola_dir / "config.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    res = CliRunner().invoke(
        app, ["compare-ref", "a", "b", "--config", str(lola_dir / "config.yaml")]
    )
    assert res.exit_code != 0
    assert "git" in res.output.lower()

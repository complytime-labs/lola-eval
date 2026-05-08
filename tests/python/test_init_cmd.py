"""CLI-level tests for ``lola-eval init``.

Covers the scaffolding behaviour: existing-config refusal, .gitignore
visibility (UX14), and idempotent re-runs.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lola_eval.cli import app


def test_init_scaffolds_config_and_lists_gitignore_lines(tmp_path: Path, monkeypatch):
    """UX14: init must announce which .gitignore lines it appended so
    the user understands the file was modified."""
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "lola-eval.yaml").exists()
    gi = (tmp_path / ".gitignore").read_text()
    assert ".lola-eval/runs.db" in gi
    assert ".lola-eval/transcripts/" in gi
    # Output mentions the appended lines.
    assert "appended" in r.output
    assert ".lola-eval/runs.db" in r.output


def test_init_is_idempotent_on_gitignore(tmp_path: Path, monkeypatch):
    """Re-running init when .gitignore is already populated must not
    re-append. Output reports 'already contains'."""
    (tmp_path / ".gitignore").write_text(
        ".lola-eval/runs.db\n"
        ".lola-eval/transcripts/\n"
        ".lola-eval/reports/\n"
        ".lola-eval/junit.xml\n"
        ".lola-eval/workspace/\n"
    )
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    assert "already contains" in r.output
    # File still has only one occurrence of each line.
    gi = (tmp_path / ".gitignore").read_text()
    assert gi.count(".lola-eval/runs.db") == 1


def test_init_refuses_existing_config_without_force(tmp_path: Path, monkeypatch):
    (tmp_path / "lola-eval.yaml").write_text("# preexisting\n")
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["init"])
    assert r.exit_code == 2
    # Original content untouched.
    assert (tmp_path / "lola-eval.yaml").read_text() == "# preexisting\n"

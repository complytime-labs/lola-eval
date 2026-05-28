from __future__ import annotations

from typer.testing import CliRunner

from lola_eval.cli import app

runner = CliRunner()


def test_init_scaffolds_consolidated_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".lola-eval" / "config.yaml").exists()
    assert (tmp_path / ".lola-eval" / "test_sets" / "example").is_dir()
    assert (tmp_path / ".lola-eval" / "test_sets" / "example" / "task.yaml").exists()
    gi = (tmp_path / ".gitignore").read_text().splitlines()
    lines = [ln.strip() for ln in gi]
    assert ".lola-eval/out/" in lines
    # exactly one lola-eval gitignore entry
    assert sum(1 for ln in lines if ".lola-eval" in ln) == 1


def test_init_refuses_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 2


def test_init_force_overwrites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0


def test_init_appends_gitignore_idempotently(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    first = (tmp_path / ".gitignore").read_text()
    runner.invoke(app, ["init", "--force"])
    second = (tmp_path / ".gitignore").read_text()
    assert first == second


def test_init_message_matches_lines_actually_written(tmp_path, monkeypatch):
    """The "appended N line(s)" stdout must match what landed on disk.

    Previously the writer added a header comment when creating the file
    from scratch but only counted the pattern lines, so the message
    under-reported by one (`appended 1 line(s)` for a 2-line file).
    """
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    on_disk = (tmp_path / ".gitignore").read_text().splitlines()
    non_empty = [ln for ln in on_disk if ln.strip()]
    # Extract "appended N line(s)" from the captured output.
    import re

    match = re.search(r"appended (\d+) line", result.output)
    assert match, f"no 'appended N line' message in:\n{result.output}"
    assert int(match.group(1)) == len(non_empty)

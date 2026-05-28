"""CLI entrypoint smoke test."""

from __future__ import annotations

import os

from typer.testing import CliRunner

from lola_eval.cli import app, _activate_target_env
from lola_eval.layout import resolve


def _make_layout(root, monkeypatch):
    """Scaffold a .lola-eval/config.yaml under ``root`` and resolve it."""
    ed = root / ".lola-eval"
    (ed / "test_sets").mkdir(parents=True)
    (ed / "config.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "threshold:\n  mode: absolute\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    monkeypatch.chdir(root)
    return resolve(config_opt=None, out_opt=None)


def test_help_runs():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "doctor" in r.output
    assert "drift" in r.output
    assert "lift" in r.output
    assert "report" in r.output
    assert "clean" in r.output
    assert "init" in r.output
    assert "test" in r.output
    assert "baseline" in r.output


def test_no_args_shows_help():
    r = CliRunner().invoke(app, [])
    assert "Usage" in r.output


def test_version_flag_prints_version(monkeypatch):
    """UX9: --version prints the package version and exits 0."""
    r = CliRunner().invoke(app, ["--version"])
    assert r.exit_code == 0
    assert r.output.startswith("lola-eval ")
    # Trailing version is non-empty
    assert r.output.strip().split(" ", 1)[1]


def test_version_module_attribute_present():
    """UX9: lola_eval.__version__ exists and is a non-empty string."""
    import lola_eval

    assert isinstance(lola_eval.__version__, str)
    assert lola_eval.__version__


def test_activate_target_env_restores_on_exit(tmp_path, monkeypatch):
    """I11: ``_activate_target_env`` must not leak ``LOLA_RESULTS_DIR``
    into the surrounding process. Two consecutive in-process invocations
    must not see each other's env state.
    """
    layout = _make_layout(tmp_path / "a", monkeypatch)

    monkeypatch.delenv("LOLA_RESULTS_DIR", raising=False)
    assert "LOLA_RESULTS_DIR" not in os.environ

    with _activate_target_env(layout) as got:
        assert got is layout
        assert os.environ["LOLA_RESULTS_DIR"] == str(layout.out_root)

    # After exit, env restored to prior state (unset).
    assert "LOLA_RESULTS_DIR" not in os.environ


def test_activate_target_env_restores_prior_value(tmp_path, monkeypatch):
    """I11: when LOLA_RESULTS_DIR was already set, restore it on exit."""
    layout = _make_layout(tmp_path / "inner", monkeypatch)

    monkeypatch.setenv("LOLA_RESULTS_DIR", "/preexisting/value")
    with _activate_target_env(layout):
        assert os.environ["LOLA_RESULTS_DIR"] == str(layout.out_root)
    assert os.environ["LOLA_RESULTS_DIR"] == "/preexisting/value"


def test_activate_target_env_none_is_noop(tmp_path, monkeypatch):
    """No layout (e.g. read-only command outside an eval dir): env untouched."""
    monkeypatch.delenv("LOLA_RESULTS_DIR", raising=False)
    with _activate_target_env(None) as got:
        assert got is None
        assert "LOLA_RESULTS_DIR" not in os.environ
    assert "LOLA_RESULTS_DIR" not in os.environ

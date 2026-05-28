from __future__ import annotations

from pathlib import Path

import pytest

from lola_eval.layout import resolve


def _make_eval_dir(root: Path) -> Path:
    d = root / ".lola-eval"
    (d / "test_sets").mkdir(parents=True)
    (d / "config.yaml").write_text("targets: []\n")
    return d


def test_default_in_repo_resolves_local_out(tmp_path, monkeypatch):
    _make_eval_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    lay = resolve(config_opt=None, out_opt=None)
    assert lay.config_path == (tmp_path / ".lola-eval" / "config.yaml").resolve()
    assert lay.eval_dir == (tmp_path / ".lola-eval").resolve()
    assert lay.project_root == tmp_path.resolve()
    assert lay.test_sets_dir == (tmp_path / ".lola-eval" / "test_sets").resolve()
    assert lay.profiles_dir == (tmp_path / ".lola-eval" / "profiles").resolve()
    assert lay.baseline_path == (tmp_path / ".lola-eval" / "baseline.json").resolve()
    assert lay.out_root == (tmp_path / ".lola-eval" / "out").resolve()
    assert lay.is_external is False


def test_explicit_config_inside_cwd_is_local(tmp_path, monkeypatch):
    ed = _make_eval_dir(tmp_path)
    (ed / "config.live.yaml").write_text("targets: []\n")
    monkeypatch.chdir(tmp_path)
    lay = resolve(config_opt=Path(".lola-eval/config.live.yaml"), out_opt=None)
    assert lay.config_path.name == "config.live.yaml"
    assert lay.out_root == (ed / "out").resolve()
    assert lay.is_external is False


def test_external_config_resolves_xdg_out(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    foreign = tmp_path / "foreign"
    ed = _make_eval_dir(foreign)
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.chdir(work)
    lay = resolve(config_opt=ed / "config.yaml", out_opt=None)
    assert lay.is_external is True
    assert lay.out_root.is_relative_to(state / "lola-eval" / "targets")
    assert foreign.name in lay.out_root.name


def test_out_override_wins(tmp_path, monkeypatch):
    ed = _make_eval_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    forced = tmp_path / "somewhere" / "out"
    lay = resolve(config_opt=ed / "config.yaml", out_opt=forced)
    assert lay.out_root == forced.resolve()


def test_distinct_external_targets_get_distinct_keys(tmp_path, monkeypatch):
    a = _make_eval_dir(tmp_path / "a" / "proj")
    b = _make_eval_dir(tmp_path / "b" / "proj")  # same basename, different path
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    la = resolve(config_opt=a / "config.yaml", out_opt=None)
    lb = resolve(config_opt=b / "config.yaml", out_opt=None)
    assert la.out_root != lb.out_root


def test_missing_config_raises_with_init_hint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError) as exc:
        resolve(config_opt=None, out_opt=None)
    assert "lola-eval init" in str(exc.value)


def test_config_pointing_at_eval_dir_auto_redirects(tmp_path, monkeypatch):
    """A common slip: --config .lola-eval (the directory) instead of the file.
    Should auto-resolve to <dir>/config.yaml rather than silently misroute."""
    ed = _make_eval_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    lay = resolve(config_opt=ed, out_opt=None)
    assert lay.config_path == (ed / "config.yaml").resolve()
    assert lay.eval_dir == ed.resolve()


def test_config_pointing_at_eval_dir_without_config_yaml_errors(tmp_path, monkeypatch):
    """If --config is a directory but it has no config.yaml, error rather than
    accept whatever path."""
    bare = tmp_path / "bare-dir"
    bare.mkdir()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve(config_opt=bare, out_opt=None)

"""XDG path resolution.

The harness must respect XDG_STATE_HOME, XDG_CACHE_HOME, XDG_CONFIG_HOME,
falling back to spec defaults when unset. All paths namespace under
'lola-eval'. Directories are created on first access.
"""
from __future__ import annotations


from lola_eval import xdg


def test_state_home_uses_env_var_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    p = xdg.state_dir()
    assert p == tmp_path / "state" / "lola-eval"
    assert p.is_dir()


def test_state_home_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    p = xdg.state_dir()
    assert p == tmp_path / ".local" / "state" / "lola-eval"


def test_cache_home_uses_env_var_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    p = xdg.cache_dir()
    assert p == tmp_path / "cache" / "lola-eval"


def test_cache_home_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    p = xdg.cache_dir()
    assert p == tmp_path / ".cache" / "lola-eval"


def test_config_home_uses_env_var_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    p = xdg.config_dir()
    assert p == tmp_path / "config" / "lola-eval"


def test_config_home_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    p = xdg.config_dir()
    assert p == tmp_path / ".config" / "lola-eval"


def test_subdirs_named(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert xdg.transcripts_dir().name == "transcripts"
    assert xdg.transcripts_dir().parent == tmp_path / "state" / "lola-eval"
    assert xdg.diffs_dir().name == "diffs"
    assert xdg.logs_dir().name == "logs"
    assert xdg.reports_dir().name == "reports"
    assert xdg.work_dir().name == "work"
    assert xdg.work_dir().parent == tmp_path / "cache" / "lola-eval"
    assert xdg.packs_cache_dir().name == "packs"


def test_db_path_under_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    p = xdg.db_path()
    assert p == tmp_path / "state" / "lola-eval" / "runs.db"


def test_resolve_db_path_prefers_explicit_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("LOLA_DB_PATH", str(tmp_path / "explicit.db"))
    monkeypatch.setenv("LOLA_RESULTS_DIR", str(tmp_path / "ignored"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert xdg.resolve_db_path() == tmp_path / "explicit.db"


def test_resolve_db_path_uses_results_dir_when_set(tmp_path, monkeypatch):
    monkeypatch.delenv("LOLA_DB_PATH", raising=False)
    monkeypatch.setenv("LOLA_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert xdg.resolve_db_path() == tmp_path / "results" / "runs.db"


def test_resolve_db_path_falls_back_to_xdg(tmp_path, monkeypatch):
    """Phase-1 standalone path: no target env vars → XDG state."""
    monkeypatch.delenv("LOLA_DB_PATH", raising=False)
    monkeypatch.delenv("LOLA_RESULTS_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert xdg.resolve_db_path() == tmp_path / "state" / "lola-eval" / "runs.db"


def test_db_path_for_target_uses_results_dir(tmp_path):
    from lola_eval.config import LolaEvalConfig, TargetEntry
    cfg = LolaEvalConfig(
        targets=[TargetEntry(cli="claude-code", models=["claude-sonnet-4-6"])],
        results_dir=".lola-eval",
    )
    p = xdg.db_path_for_target(tmp_path, cfg)
    assert p == tmp_path / ".lola-eval" / "runs.db"

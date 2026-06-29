import pytest
from pathlib import Path

from lola_eval.config import LolaEvalConfig
from lola_eval.runner import _assert_clean_starters, _mode1_packs, _install_scope_for_pack


def _cfg(**kw):
    base = dict(targets=[{"cli": "claude-code", "models": ["sonnet"]}])
    base.update(kw)
    return LolaEvalConfig(**base)


def test_mode1_packs_default_project_only():
    assert _mode1_packs(_cfg()) == ["project"]


def test_mode1_packs_user_scope_maps_to_project_user():
    cfg = _cfg(module_source="./m", install_scopes=["user"])
    assert _mode1_packs(cfg) == ["project-user"]


def test_mode1_packs_both_scopes_ordered():
    cfg = _cfg(module_source="./m", install_scopes=["project", "user"])
    assert _mode1_packs(cfg) == ["project", "project-user"]


def test_install_scope_for_pack():
    assert _install_scope_for_pack("project") == "project"
    assert _install_scope_for_pack("project-user") == "user"
    assert _install_scope_for_pack("none") == "project"


def _make_case(tmp_path: Path, with_module=False, marker=False) -> Path:
    case = tmp_path / "case-x"
    starter = case / "starter"
    starter.mkdir(parents=True)
    (starter / "src.py").write_text("x = 1\n")
    if with_module:
        (starter / ".lola" / "modules" / "m").mkdir(parents=True)
    if marker:
        (starter / "CLAUDE.md").write_text(
            "# ctx\n<!-- lola:module:m:start -->\nx\n<!-- lola:module:m:end -->\n"
        )
    return case


def test_guard_passes_on_clean_starter(tmp_path):
    case = _make_case(tmp_path)
    _assert_clean_starters([case], module_source="/some/mod")  # no raise


def test_guard_rejects_committed_lola_modules(tmp_path):
    case = _make_case(tmp_path, with_module=True)
    with pytest.raises(ValueError) as exc:
        _assert_clean_starters([case], module_source="/some/mod")
    assert ".lola/modules" in str(exc.value)


def test_guard_rejects_stale_marker_block(tmp_path):
    case = _make_case(tmp_path, marker=True)
    with pytest.raises(ValueError) as exc:
        _assert_clean_starters([case], module_source="/some/mod")
    assert "lola:module" in str(exc.value)


def test_guard_noop_without_module_source(tmp_path):
    case = _make_case(tmp_path, with_module=True)
    _assert_clean_starters([case], module_source="")  # no raise when unset

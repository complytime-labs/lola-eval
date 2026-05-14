"""Tool registry: declarative mapping of CLI names to config conventions."""
from __future__ import annotations

import json
from importlib.resources import files


def _load_registry() -> dict:
    data = files("lola_eval").joinpath("_data/tools.json")
    return json.loads(data.read_text())


def test_registry_has_claude_code():
    reg = _load_registry()
    assert "claude-code" in reg
    cc = reg["claude-code"]
    assert cc["config_dir"] == ".claude"
    assert cc["config_env"] == "CLAUDE_CONFIG_DIR"
    assert isinstance(cc["clear_env"], list)
    assert "CLAUDE_CODE_PLUGIN_SEED_DIR" in cc["clear_env"]
    assert isinstance(cc["permission_flag"], str)


def test_registry_has_opencode():
    reg = _load_registry()
    assert "opencode" in reg
    oc = reg["opencode"]
    assert oc["config_dir"] == ".opencode"
    assert oc["config_env"] == "OPENCODE_CONFIG_DIR"
    assert isinstance(oc["clear_env"], list)
    assert isinstance(oc["permission_flag"], str)


def test_every_entry_has_required_keys():
    reg = _load_registry()
    required = {"config_dir", "config_env", "clear_env", "permission_flag"}
    for name, entry in reg.items():
        missing = required - set(entry.keys())
        assert not missing, f"{name} missing keys: {missing}"

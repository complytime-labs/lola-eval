"""Profile schema validation and loader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from lola_eval.profile import ProfileConfig, CopyDirective, SetupDirectives, load_profiles


class TestProfileConfig:
    def test_minimal_valid(self):
        p = ProfileConfig(name="bare")
        assert p.name == "bare"
        assert p.compatible_targets == ["claude-code", "opencode"]
        assert p.skip_permissions is True
        assert p.pre_prompt == ""
        assert p.prompt is None
        assert p.post_prompt is None
        assert p.system_prompt_file is None
        assert p.setup == {}

    def test_full_profile(self):
        p = ProfileConfig(
            name="superpowers",
            description="Superpowers plugin",
            compatible_targets=["claude-code"],
            pre_prompt="/unleash",
            post_prompt=["Are you satisfied?"],
            system_prompt_file="/etc/claude-code/CLAUDE.md",
            budget=15.0,
            timeout=2400,
            setup={
                "claude-code": SetupDirectives(
                    flags=["--bare", "--plugin-dir", "/tmp/sp"],
                    replace_config="configs/claude-bare",
                    remove=["CLAUDE.md"],
                    copy=[CopyDirective(src="fixtures/AGENTS.md", dst="AGENTS.md", mode="append", tag="agents")],
                ),
            },
        )
        assert p.compatible_targets == ["claude-code"]
        assert len(p.setup["claude-code"].copy) == 1
        assert p.setup["claude-code"].copy[0].mode == "append"

    def test_null_vs_empty_system_prompt(self):
        inherit = ProfileConfig(name="a")
        assert inherit.system_prompt_file is None
        override = ProfileConfig(name="b", system_prompt_file="")
        assert override.system_prompt_file == ""

    def test_null_vs_empty_post_prompt(self):
        inherit = ProfileConfig(name="a")
        assert inherit.post_prompt is None
        override = ProfileConfig(name="b", post_prompt=[])
        assert override.post_prompt == []

    def test_copy_directive_defaults(self):
        c = CopyDirective(src="a.md", dst="b.md")
        assert c.mode == "replace"
        assert c.tag == ""


class TestLoadProfiles:
    def test_load_with_common_inheritance(self, tmp_path: Path):
        common = tmp_path / "common.yaml"
        common.write_text(textwrap.dedent("""\
            name: common
            budget: 10
            timeout: 1800
            skip_permissions: true
            post_prompt:
              - "Are you satisfied?"
        """))
        bare = tmp_path / "bare.yaml"
        bare.write_text(textwrap.dedent("""\
            name: bare
            post_prompt: []
            system_prompt_file: ""
            setup:
              claude-code:
                replace_config: configs/claude-bare
              opencode:
                replace_config: configs/opencode-bare
        """))
        profiles = load_profiles(tmp_path, "common.yaml", selected=None)
        assert len(profiles) == 1
        p = profiles[0]
        assert p.name == "bare"
        assert p.budget == 10
        assert p.post_prompt == []
        assert p.system_prompt_file == ""

    def test_selected_filter(self, tmp_path: Path):
        for name in ["a", "b", "c"]:
            (tmp_path / f"{name}.yaml").write_text(
                f"name: {name}\ncompatible_targets:\n  - claude-code\nsetup:\n  claude-code:\n    flags: []\n"
            )
        profiles = load_profiles(tmp_path, "common.yaml", selected=["a", "c"])
        names = [p.name for p in profiles]
        assert names == ["a", "c"]

    def test_setup_not_inherited(self, tmp_path: Path):
        common = tmp_path / "common.yaml"
        common.write_text(textwrap.dedent("""\
            name: common
            budget: 10
            setup:
              claude-code:
                flags: ["--should-not-inherit"]
        """))
        child = tmp_path / "child.yaml"
        child.write_text(textwrap.dedent("""\
            name: child
            compatible_targets:
              - claude-code
            setup:
              claude-code:
                flags: ["--bare"]
        """))
        profiles = load_profiles(tmp_path, "common.yaml", selected=None)
        assert profiles[0].setup["claude-code"].flags == ["--bare"]

    def test_missing_common_is_ok(self, tmp_path: Path):
        p = tmp_path / "solo.yaml"
        p.write_text("name: solo\ncompatible_targets:\n  - claude-code\nsetup:\n  claude-code:\n    flags: []\n")
        profiles = load_profiles(tmp_path, "common.yaml", selected=None)
        assert len(profiles) == 1

    def test_compatible_targets_without_setup_raises(self, tmp_path: Path):
        p = tmp_path / "bad.yaml"
        p.write_text(textwrap.dedent("""\
            name: bad
            compatible_targets:
              - opencode
            setup:
              claude-code:
                flags: []
        """))
        with pytest.raises(ValueError, match="compatible_targets.*opencode.*setup"):
            load_profiles(tmp_path, "common.yaml", selected=None)

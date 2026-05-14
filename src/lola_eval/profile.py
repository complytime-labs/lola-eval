"""Profile schema and loader.

Profiles control environment configuration (config dirs, CLI flags,
prompt tiers, permissions). They are orthogonal to packs (content).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from lola_eval.config import JudgeEntry


class CopyDirective(BaseModel):
    model_config = ConfigDict(extra="forbid")
    src: str
    dst: str
    mode: Literal["replace", "append"] = "replace"
    tag: str = ""


class SetupDirectives(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flags: list[str] = Field(default_factory=list)
    replace_config: str = ""
    remove: list[str] = Field(default_factory=list)
    copy: list[CopyDirective] = Field(  # noqa: A003 — domain name, not builtin
        default_factory=list,
    )


class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    compatible_targets: list[str] = Field(default_factory=lambda: ["claude-code", "opencode"])
    pre_prompt: str = ""
    prompt: str | None = None
    post_prompt: list[str] | None = None
    system_prompt_file: str | None = None
    skip_permissions: bool = True
    permissions: str = ""
    budget: float = 10.0
    timeout: int = 1800
    max_turns: int = 50
    judges: list[JudgeEntry] | None = None
    setup: dict[str, SetupDirectives] = Field(default_factory=dict)


def load_profiles(
    profiles_dir: Path,
    common_name: str = "common.yaml",
    selected: list[str] | None = None,
) -> list[ProfileConfig]:
    """Load profile YAMLs from a directory with optional common.yaml inheritance.

    Raises ValueError if a profile declares compatible_targets without a
    matching setup section, or if a selected profile name doesn't exist.
    """
    common_path = profiles_dir / common_name
    common: dict = {}
    if common_path.exists():
        raw = yaml.safe_load(common_path.read_text()) or {}
        common = {k: v for k, v in raw.items() if k not in ("name", "setup")}

    profile_files = sorted(
        p for p in profiles_dir.glob("*.yaml")
        if p.name != common_name
    )

    if selected is not None:
        selected_set = set(selected)
        profile_files = [p for p in profile_files if p.stem in selected_set]
        found = {p.stem for p in profile_files}
        missing = selected_set - found
        if missing:
            raise ValueError(
                f"profiles not found in {profiles_dir}: {sorted(missing)}"
            )

    profiles: list[ProfileConfig] = []
    for pf in profile_files:
        raw = yaml.safe_load(pf.read_text()) or {}
        merged = {**common, **raw}
        if "setup" not in raw:
            merged.pop("setup", None)
        else:
            merged["setup"] = raw["setup"]

        profile = ProfileConfig(**merged)
        _validate_setup_coverage(profile, pf)
        profiles.append(profile)

    return profiles


def _validate_setup_coverage(profile: ProfileConfig, source: Path) -> None:
    for target in profile.compatible_targets:
        if target not in profile.setup:
            raise ValueError(
                f"{source.name}: compatible_targets includes '{target}' but "
                f"setup does not have a '{target}' section. Either add "
                f"setup.{target} or remove '{target}' from compatible_targets."
            )

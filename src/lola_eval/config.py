"""lola-eval.yaml schema and loader.

Schema is defined in spec Section 5. Validation uses pydantic v2.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(ValueError):
    """Raised when lola-eval.yaml is missing, malformed, or schema-invalid."""


class TargetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cli: Literal["claude-code", "opencode"]
    models: list[str] = Field(min_length=1)
    # Phase-2 interactive support. exec_mode=autonomous (default) keeps the
    # one-shot, fire-and-collect flow that's been there since Phase 1.
    # exec_mode=interactive runs a multi-turn dialog driven by a separate
    # simulated-user CLI. The fingerprint already accepts "interactive"
    # (see src/lola_eval/fingerprint.py); this exposes it in the schema.
    exec_mode: Literal["autonomous", "interactive"] = "autonomous"
    # Hard cap on dialog turns. Honored only when exec_mode=interactive.
    # A "turn" is one user message + one agent response. Five is generous
    # for the bug-fix / code-review cases the harness was designed around;
    # set higher for open-ended tasks.
    max_turns: int = Field(default=5, ge=1, le=50)
    # CLI used to spawn the simulated user. Defaults to opencode because
    # opencode's agent-mode flag (--agent) is the cleanest way to pin a
    # tools-disabled persona without leaking auth state.
    simulated_user_cli: Literal["claude-code", "opencode"] = "opencode"
    # Model the simulated user runs as. Empty string means "fall back to
    # the target's first model" — handy default for first-time setups.
    simulated_user_model: str = ""


class JudgeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cli: Literal["claude-code", "opencode"]
    model: str


class ThresholdConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["absolute", "regression", "both"] = "absolute"
    tolerance: float = Field(default=0.05, ge=0.0, le=1.0)
    timeout_is_failure: bool = True


class CIConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    junit_xml: bool = True
    github_summary: bool = True
    html_report: bool = True


class LolaEvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[TargetEntry] = Field(min_length=1)
    # Two modes, picked by whether ``packs:`` is present:
    #
    #   Mode 1 (in-repo / CI workhorse): ``packs:`` is omitted. The project
    #     under evaluation provisions its own packs (user-scope `lola
    #     install` before CI, project-level install script, etc.); the
    #     harness does no installation. Each cell produces one pack_id:
    #     "project". Set ``calculate_baseline: true`` to also run a
    #     clean-workdir "none" pass for lift comparison.
    #
    #   Mode 2 (external pack review): ``packs:`` lists one or more
    #     pack identifiers (e.g. ``name@<sha>``). The harness installs
    #     each via the bundled ``install_pack.sh`` -> ``lola install``
    #     path. Each pack becomes its own pack_id. Set
    #     ``calculate_baseline: true`` to also include a "none" baseline
    #     pass — usually what you want, since lift% needs a denominator.
    #
    # The validator enforces mutual exclusion: ``packs:`` must not contain
    # the reserved sentinels "none" (controlled by calculate_baseline) or
    # "project" (Mode 1 only). An empty list is rejected — omit the key
    # instead.
    packs: list[str] | None = None
    calculate_baseline: bool = False
    threshold: ThresholdConfig = Field(default_factory=ThresholdConfig)
    concurrency: int = Field(default=4, ge=1, le=64)
    tests_dir: str = "tests/lola-eval"
    results_dir: str = ".lola-eval"
    judges: list[JudgeEntry] = Field(default_factory=list)
    aggregation: Literal["mean", "median", "min", "trimmed_mean"] = "mean"
    disagreement_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    # How to react when judge_disagreement exceeds disagreement_threshold:
    #   warn (default) -- log to stderr; row still passes/fails on composite alone
    #   fail           -- mark the row failed with failure_kind="judge_disagreement"
    #   off            -- compute disagreement but emit no warning
    disagreement_action: Literal["warn", "fail", "off"] = "warn"
    ci: CIConfig = Field(default_factory=CIConfig)
    # Hard upper bound on the promptfoo subprocess. A wedged provider can
    # otherwise hang CI indefinitely. One hour covers a healthy multi-row
    # matrix run with margin; tune downward in lola-eval.yaml if you have
    # tighter SLAs.
    runner_timeout_seconds: int = Field(default=3600, ge=1)
    # Wall-clock cap for the per-row judge fan-out. Defense in depth: each
    # individual judge subprocess already has its own timeout (120 s by
    # default), but if that mis-fires (NFS-mounted CLI, signal weirdness) the
    # ThreadPoolExecutor would hang indefinitely. This budget bounds the whole
    # fan-out and surfaces a judge_error instead of hanging the row forever.
    judge_timeout_seconds: int = Field(default=600, ge=10)
    profiles_dir: str | None = None
    profiles_common: str = "common.yaml"
    profiles: list[str] | None = None

    @model_validator(mode="after")
    def _trimmed_mean_needs_three_judges(self) -> LolaEvalConfig:
        if self.aggregation == "trimmed_mean" and len(self.judges) < 3:
            raise ValueError(
                f"aggregation='trimmed_mean' requires at least 3 judges; "
                f"got {len(self.judges)}. Use 'mean', 'median', or 'min', "
                f"or add more entries to judges:."
            )
        return self

    @model_validator(mode="after")
    def _validate_pack_mode(self) -> LolaEvalConfig:
        if self.packs is None:
            return self
        if not self.packs:
            raise ValueError(
                "packs: cannot be an empty list. Omit the key entirely "
                "for in-repo mode (the project provisions its own packs), "
                "or list one or more pack ids like 'name@<sha>'."
            )
        reserved = {"none", "project"}
        offenders = sorted(set(self.packs) & reserved)
        if offenders:
            raise ValueError(
                f"packs: must not contain the reserved sentinel(s) "
                f"{offenders}. Use 'calculate_baseline: true' to include a "
                f"clean-workdir baseline pass, and omit 'packs:' entirely "
                f"to evaluate the project's own pack setup."
            )
        return self

    @model_validator(mode="after")
    def _validate_profile_config(self) -> LolaEvalConfig:
        if self.profiles is not None and self.profiles_dir is None:
            raise ValueError(
                "profiles: requires profiles_dir to be set. "
                "Add profiles_dir: ./profiles (or the path to your profile YAMLs)."
            )
        if self.profiles is not None and not self.profiles:
            raise ValueError(
                "profiles: cannot be an empty list. Omit the key entirely "
                "to skip profile-based evaluation, or list profile names."
            )
        return self


def load_config(path: Path) -> LolaEvalConfig:
    """Load and validate a lola-eval.yaml.

    Raises ConfigError on any failure (missing file, invalid YAML, schema
    violation). The error message is human-readable and points at the field.
    """
    if not path.exists():
        raise ConfigError(f"lola-eval.yaml not found at {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error in {path}: {e}") from e

    if "judge" in raw and "judges" not in raw:
        raw["judges"] = [raw.pop("judge")]
    elif "judge" in raw and "judges" in raw:
        raise ConfigError("Both 'judge' (legacy singular) and 'judges' (list) set; pick one.")

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level YAML must be a mapping, got {type(raw).__name__}")

    if not raw.get("judges"):
        targets_raw = raw.get("targets") or [{}]
        first_target = targets_raw[0] if isinstance(targets_raw, list) and targets_raw else {}
        if isinstance(first_target, dict) and first_target.get("cli") and first_target.get("models"):
            raw["judges"] = [{"cli": first_target["cli"], "model": first_target["models"][0]}]

    try:
        return LolaEvalConfig(**raw)
    except ValidationError as e:
        details = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in e.errors()
        )
        raise ConfigError(f"Schema error in {path}: {details}") from e

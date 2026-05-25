"""Detect unpinned model aliases that risk silent score drift (#4).

A bare alias like `sonnet` resolves to whatever the CLI considers the
latest matching model at run time. When that resolution changes, eval
scores shift with no change to the code or rubric — drift the framework
cannot attribute. This module flags aliases so eval authors can pin a
concrete model id for reproducible drift tracking.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lola_eval.config import LolaEvalConfig

# Bare aliases the agent CLIs accept that resolve to a moving target.
KNOWN_ALIASES = frozenset({"sonnet", "opus", "haiku"})


def is_model_alias(model: str) -> bool:
    """True if `model` is an unpinned alias (resolves to a moving version).

    Pinned ids carry a concrete version: a digit (`claude-sonnet-4-6`,
    `...-20251001`) or a provider-qualified id (`/` or `@version`). Bare
    known aliases, or any digit-free name, are treated as unpinned.

    Note: digit-free names without `/` or `@` (e.g. `gemini-pro`, a codename
    family) are also classified as aliases by this heuristic. Provider-specific
    model families that have no version number in their id will therefore
    trigger spurious alias warnings even when they are effectively pinned.
    """
    m = model.strip().lower()
    if not m:
        return False
    if m in KNOWN_ALIASES:
        return True
    if "@" in m or "/" in m:
        return False
    return not any(ch.isdigit() for ch in m)


def alias_drift_warnings(cfg: "LolaEvalConfig") -> list[str]:
    """One warning line per distinct unpinned target/judge model in `cfg`."""
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for t in cfg.targets:
        for model in t.models:
            key = ("target", model)
            if is_model_alias(model) and key not in seen:
                seen.add(key)
                lines.append(
                    f"target model '{model}' is an unpinned alias; scores may "
                    f"drift as it resolves to newer versions. Pin a concrete id "
                    f"(e.g. claude-sonnet-4-6) for reproducible drift tracking."
                )
    for j in cfg.judges:
        key = ("judge", j.model)
        if is_model_alias(j.model) and key not in seen:
            seen.add(key)
            lines.append(
                f"judge model '{j.model}' is an unpinned alias; judge scores may "
                f"drift as it resolves to newer versions. Pin a concrete id for "
                f"reproducible drift tracking."
            )
    return lines

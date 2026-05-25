"""Compare composites across the profile (installed-skill) dimension and
flag skill conflicts.

A *conflict* is a profile whose installed-skill set is a proper superset of
another profile's, yet scores meaningfully lower — i.e. adding skill(s) hurt.
Detection is deterministic and works on already-collected composites, so it is
unit-tested independently of any live agent run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lola_eval import store


@dataclass(frozen=True)
class Conflict:
    cell: str
    base_profile: str
    super_profile: str
    added: tuple[str, ...]   # modules in super − base, sorted
    delta: float             # composite(super) − composite(base); negative


def load_profile_skillsets(cfg, target_root: Path) -> dict[str, frozenset[str]]:
    """Map each profile_id to the set of modules it installs.

    ``none`` is always present (empty set). When the config lists profiles,
    each profile's installed modules are the union of its per-target
    ``install_modules`` lists.
    """
    from lola_eval.profile import load_profiles

    sets: dict[str, frozenset[str]] = {"none": frozenset()}
    if cfg.profiles_dir is None:
        return sets
    profiles = load_profiles(
        target_root / cfg.profiles_dir,
        common_name=cfg.profiles_common,
        selected=cfg.profiles,
    )
    for p in profiles:
        mods: set[str] = set()
        for sd in p.setup.values():
            mods.update(sd.install_modules)
        sets[p.name] = frozenset(mods)
    return sets


def _composite(scores_json: str | None) -> float | None:
    if not scores_json:
        return None
    try:
        value = json.loads(scores_json).get("composite")
    except (json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, (int, float)) else None


def gather_composites(
    db_path: Path, *, case: str | None = None, since: str | None = None,
) -> dict[str, dict[str, float | None]]:
    """Return {cell: {profile_id: composite}} from runs.db (latest per profile).

    A *cell* is ``target_cli/target_model/task_id``. ``store.export_rows``
    returns rows newest-first, so the first row seen per (cell, profile) is the
    most recent.
    """
    rows = store.export_rows(db_path, task=case, since=since)
    out: dict[str, dict[str, float | None]] = {}
    for r in rows:
        cell = f"{r['target_cli']}/{r['target_model']}/{r['task_id']}"
        profile = r.get("profile_id", "none")
        bucket = out.setdefault(cell, {})
        if profile not in bucket:
            bucket[profile] = _composite(r.get("scores_json"))
    return out


def detect_conflicts(
    skillsets: dict[str, frozenset[str]],
    composites: dict[str, dict[str, float | None]],
    tolerance: float,
) -> list[Conflict]:
    """Flag every (A, B) pair within a cell where A's skill-set is a proper
    subset of B's and composite(B) < composite(A) − tolerance."""
    conflicts: list[Conflict] = []
    for cell, by_profile in composites.items():
        profiles = list(by_profile)
        for a in profiles:
            for b in profiles:
                if a == b:
                    continue
                sa = skillsets.get(a)
                sb = skillsets.get(b)
                if sa is None or sb is None or not (sa < sb):
                    continue
                ca = by_profile.get(a)
                cb = by_profile.get(b)
                if ca is None or cb is None:
                    continue
                if cb < ca - tolerance:
                    conflicts.append(Conflict(
                        cell=cell, base_profile=a, super_profile=b,
                        added=tuple(sorted(sb - sa)), delta=cb - ca,
                    ))
    conflicts.sort(key=lambda c: (c.cell, len(c.added), c.super_profile, c.base_profile))
    return conflicts


def render(
    skillsets: dict[str, frozenset[str]],
    composites: dict[str, dict[str, float | None]],
    conflicts: list[Conflict],
) -> str:
    """Render a per-cell profile table plus a conflict section."""
    lines = ["profile-compare", ""]
    for cell in sorted(composites):
        by_profile = composites[cell]
        base = by_profile.get("none")
        lines.append(f"## {cell}")
        lines.append("")
        lines.append("| profile | skills | composite | delta vs none |")
        lines.append("| --- | --- | --- | --- |")
        ordered = sorted(
            by_profile,
            key=lambda p: (len(skillsets.get(p, frozenset())), p),
        )
        for prof in ordered:
            comp = by_profile[prof]
            mods = ", ".join(sorted(skillsets.get(prof, frozenset()))) or "-"
            cs = f"{comp:.2f}" if comp is not None else "-"
            if base is not None and comp is not None and prof != "none":
                ds = f"{comp - base:+.2f}"
            else:
                ds = "-"
            lines.append(f"| {prof} | {mods} | {cs} | {ds} |")
        lines.append("")
    if conflicts:
        lines.append("## Conflicts detected")
        lines.append("")
        for c in conflicts:
            lines.append(
                f"- {c.cell}: adding [{', '.join(c.added)}] dropped composite "
                f"{c.delta:+.2f} ({c.super_profile} vs {c.base_profile})"
            )
    else:
        n = sum(len(v) for v in composites.values())
        lines.append(f"No conflicts detected ({n} profile rows compared).")
    return "\n".join(lines) + "\n"

"""Skill-conflict detection over a profile sweep."""

from __future__ import annotations

import json

from lola_eval import store
from lola_eval.profile_compare import detect_conflicts, gather_composites, render

CELL = "claude-code/haiku/case-greeting"

SKILLSETS = {
    "none": frozenset(),
    "greet": frozenset({"greeter-mod"}),
    "greet-farewell": frozenset({"greeter-mod", "farewell-mod"}),
    "greet-salute": frozenset({"greeter-mod", "salute-mod"}),
}


def _composites(**by_profile):
    return {CELL: dict(by_profile)}


def test_flat_control_sweep_flags_nothing():
    comps = _composites(none=0.3, greet=0.9, **{"greet-farewell": 0.9})
    assert detect_conflicts(SKILLSETS, comps, tolerance=0.05) == []


def test_superset_drop_is_flagged_with_added_module():
    comps = _composites(none=0.3, greet=0.9, **{"greet-salute": 0.4})
    conflicts = detect_conflicts(SKILLSETS, comps, tolerance=0.05)
    # greet-salute drops vs both greet and none (it is a proper superset of both)
    by_base = {c.base_profile: c for c in conflicts}
    assert "greet" in by_base
    assert by_base["greet"].super_profile == "greet-salute"
    assert by_base["greet"].added == ("salute-mod",)
    assert by_base["greet"].delta < 0


def test_non_subset_pairs_are_not_compared():
    # greet-farewell vs greet-salute are siblings (neither is a subset),
    # so even a large gap must not be flagged.
    comps = _composites(**{"greet-farewell": 0.9, "greet-salute": 0.1})
    assert detect_conflicts(SKILLSETS, comps, tolerance=0.05) == []


def test_tolerance_boundary():
    # Drop exactly at tolerance is NOT a conflict; just beyond it is.
    at = _composites(greet=0.90, **{"greet-salute": 0.85})
    assert detect_conflicts(SKILLSETS, at, tolerance=0.05) == []
    beyond = _composites(greet=0.90, **{"greet-salute": 0.84})
    assert any(c.super_profile == "greet-salute" for c in
               detect_conflicts(SKILLSETS, beyond, tolerance=0.05))


def test_none_composite_rows_are_skipped():
    comps = _composites(greet=None, **{"greet-salute": 0.1})
    assert detect_conflicts(SKILLSETS, comps, tolerance=0.05) == []


def test_profile_absent_from_skillsets_is_skipped():
    # A composite for a profile not present in skillsets (e.g. a stale runs.db
    # row from a since-removed profile) must be ignored, not crash.
    comps = _composites(greet=0.9, ghost=0.1)
    assert detect_conflicts(SKILLSETS, comps, tolerance=0.05) == []


def _seed(db, profile_id, composite, timestamp):
    store.insert_run(db, {
        "run_id": f"r-{profile_id}-{timestamp}",
        "timestamp": timestamp,
        "fingerprint": f"fp-{profile_id}",
        "target_cli": "claude-code",
        "target_model": "haiku",
        "target_cli_ver": "1",
        "pack_id": "project",
        "profile_id": profile_id,
        "task_id": "case-greeting",
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "headless",
        "invocation": "passive",
        "judge_cli": "claude-code",
        "judge_model": "sonnet",
        "scores_json": json.dumps({"composite": composite}),
        "transcript_path": "/dev/null",
        "exit_status": "success",
    })


def test_gather_composites_keeps_newest_per_profile(tmp_path):
    db = tmp_path / "runs.db"
    store.init_db(db)
    _seed(db, "greet", 0.4, "2026-05-25T00:00:00Z")  # older
    _seed(db, "greet", 0.9, "2026-05-25T01:00:00Z")  # newer wins
    comps = gather_composites(db)
    assert comps["claude-code/haiku/case-greeting"]["greet"] == 0.9


def test_render_shows_table_and_conflict_section():
    comps = _composites(none=0.3, greet=0.9, **{"greet-salute": 0.4})
    conflicts = detect_conflicts(SKILLSETS, comps, tolerance=0.05)
    text = render(SKILLSETS, comps, conflicts)
    assert CELL in text
    assert "delta vs none" in text
    assert "Conflicts detected" in text
    assert "salute-mod" in text


def test_render_no_conflicts_message():
    comps = _composites(none=0.3, greet=0.9)
    text = render(SKILLSETS, comps, [])
    assert "No conflicts detected" in text

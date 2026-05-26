"""The example sweep profiles must load and form the expected skill-set diamond."""

from __future__ import annotations

from pathlib import Path

from lola_eval.profile import load_profiles

PROFILES_DIR = Path(__file__).resolve().parents[2] / "examples" / "conflict" / ".lola-eval" / "profiles"

EXPECTED = {
    "none": set(),
    "greet": {"greeter-mod"},
    "greet-farewell": {"greeter-mod", "farewell-mod"},
    "greet-salute": {"greeter-mod", "salute-mod"},
    "greet-farewell-salute": {"greeter-mod", "farewell-mod", "salute-mod"},
}


def test_sweep_profiles_load_with_expected_skillsets():
    profiles = load_profiles(PROFILES_DIR, selected=list(EXPECTED))
    got = {
        p.name: set(p.setup["claude-code"].install_modules)
        for p in profiles
    }
    assert got == EXPECTED


def test_two_skill_profiles_have_same_count_different_modules():
    # The diamond: greet-farewell and greet-salute both add one skill to greet,
    # so a composite difference isolates the *module*, not the count.
    assert len(EXPECTED["greet-farewell"]) == len(EXPECTED["greet-salute"]) == 2
    assert EXPECTED["greet-farewell"] != EXPECTED["greet-salute"]

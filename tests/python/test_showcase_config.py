"""Validate the showcase config loads and enumerates the expected cells."""
from __future__ import annotations

from pathlib import Path

from lola_eval.config import load_config


SHOWCASE = Path(__file__).resolve().parents[2] / "examples" / "showcase" / ".lola-eval" / "config.yaml"


def test_showcase_loads():
    cfg = load_config(SHOWCASE)
    assert cfg is not None


def test_showcase_has_three_target_models():
    cfg = load_config(SHOWCASE)
    assert len(cfg.targets) == 1
    assert len(cfg.targets[0].models) == 3
    assert {"claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"} == set(cfg.targets[0].models)


def test_showcase_has_five_profiles():
    cfg = load_config(SHOWCASE)
    assert cfg.profiles is not None
    assert len(cfg.profiles) == 5
    assert {"none", "small", "medium", "large", "combined"} == set(cfg.profiles)


def test_showcase_has_two_judges():
    cfg = load_config(SHOWCASE)
    assert len(cfg.judges) == 2


def test_showcase_baseline_enabled():
    cfg = load_config(SHOWCASE)
    assert cfg.calculate_baseline is True


def test_showcase_test_sets_directory_has_four_cases():
    test_sets_dir = SHOWCASE.parent / "test_sets"
    cases = sorted(p.name for p in test_sets_dir.iterdir() if p.is_dir())
    assert cases == [
        "case-A-tiny-fix",
        "case-B-medium-review",
        "case-C-large-feature",
        "case-D-negative-skill-fail",
    ]

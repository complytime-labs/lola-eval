"""Drift Δ, Lift %, weighted-composite math.

Both lift and drift are SIGNED. Negative values are first-class
findings, not bugs to clamp. The negative-lift test in particular
exists to catch a future refactor that accidentally clamps lift to ≥0
(see design Section 8).
"""
from __future__ import annotations

import pytest

from lola_eval.math import (
    drift_delta,
    lift_percent,
    weighted_composite,
)


# ---------- Drift Δ ----------

def test_drift_zero_when_scores_match():
    assert drift_delta(latest=0.7, baseline=0.7) == 0.0


def test_drift_positive_when_score_improved():
    assert drift_delta(latest=0.8, baseline=0.6) == pytest.approx(0.2)


def test_drift_negative_when_score_regressed():
    assert drift_delta(latest=0.4, baseline=0.7) == pytest.approx(-0.3)


def test_drift_with_zero_baseline_is_well_defined():
    assert drift_delta(latest=0.5, baseline=0.0) == pytest.approx(0.5)


def test_drift_returns_none_when_either_score_is_none():
    assert drift_delta(latest=None, baseline=0.5) is None
    assert drift_delta(latest=0.5, baseline=None) is None


# ---------- Lift % ----------

def test_lift_zero_when_pack_matches_baseline():
    assert lift_percent(pack=0.5, baseline=0.5) == 0.0


def test_lift_positive_when_pack_improves():
    assert lift_percent(pack=0.6, baseline=0.5) == pytest.approx(20.0)


def test_lift_negative_when_pack_regresses():
    """A pack that hurts the agent must produce negative lift.
    DO NOT clamp this to 0 or take absolute value."""
    assert lift_percent(pack=0.3, baseline=0.5) == pytest.approx(-40.0)


def test_lift_undefined_when_baseline_zero():
    """baseline=0 → undefined. NOT infinity, NOT zero, NOT |Δ|."""
    assert lift_percent(pack=0.5, baseline=0.0) is None
    assert lift_percent(pack=0.0, baseline=0.0) is None


def test_lift_returns_none_when_either_score_is_none():
    assert lift_percent(pack=None, baseline=0.5) is None
    assert lift_percent(pack=0.5, baseline=None) is None


def test_lift_amplification_at_small_baseline_is_truthful():
    """Tiny baseline + tiny absolute change = huge percentage.
    The math IS this — display layer is responsible for context."""
    result = lift_percent(pack=0.03, baseline=0.01)
    assert result == pytest.approx(200.0)


# ---------- Weighted composite ----------

def test_composite_weighted_sum():
    components = {"correctness": 0.8, "trajectory": 0.6, "tools": 1.0}
    weights    = {"correctness": 0.5, "trajectory": 0.3, "tools": 0.2}
    # 0.8*0.5 + 0.6*0.3 + 1.0*0.2 = 0.78
    assert weighted_composite(components, weights) == pytest.approx(0.78)


def test_composite_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="weights must sum to 1"):
        weighted_composite({"a": 0.5}, {"a": 0.7})


def test_composite_weights_must_match_components():
    with pytest.raises(ValueError, match="missing weight"):
        weighted_composite({"a": 0.5, "b": 0.6}, {"a": 1.0})


def test_composite_clamps_components_into_zero_one():
    """Defensive: judges can return rogue scores. Clamp at the
    composite layer, never silently drop."""
    components = {"a": 1.5, "b": -0.3}
    weights    = {"a": 0.5, "b": 0.5}
    # clamped to (1.0 + 0.0) / 2 = 0.5
    assert weighted_composite(components, weights) == pytest.approx(0.5)

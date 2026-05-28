"""Regression tests for finding #5: _per_call_cost must not crash when
flat-pricing mode is in use and the bundled calibration has a tier-1 hit.

The production bug was at the call site: _print_cost_estimate passed
calibration=cal_resolver (non-None) even when resolver=None (flat mode),
and _per_call_cost's tier-1 branch then dereferenced None.

Two tests:
  1. Behaviour: _per_call_cost short-circuits to the flat number when
     calibration=None + resolver=None.
  2. Defense-in-depth: _per_call_cost falls back to static pricing rather
     than AttributeError when the contract is violated (calibration!=None,
     resolver=None).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from lola_eval.cli.test_cmd import _per_call_cost


def test_per_call_cost_flat_short_circuits_when_calibration_none():
    """Post-fix shape: flat + no calibration returns flat number, no crash."""
    cost_cfg = SimpleNamespace(flat_per_call_usd=None, pricing_file=None)
    cost, breakdown, tag = _per_call_cost(
        "sonnet-4-6",
        cost_cfg,
        flat_override_usd=1.50,
        resolver=None,
        calibration=None,
        cell_keys=None,
        predict=False,
        feature_vector=None,
    )
    assert cost == 1.50, f"expected flat 1.50, got {cost}"
    # Tag should indicate flat/static pricing, not calibration/prediction.
    assert "calibrated" not in tag.lower()
    assert "predicted" not in tag.lower()


def test_per_call_cost_with_calibration_but_no_resolver_falls_back_safely():
    """Defense in depth: even if a caller forgets to gate calibration on
    using_flat, _per_call_cost itself must not deref resolver=None.

    This is the post-fix contract: calibration != None requires resolver
    != None; the function falls back to static pricing rather than
    crashing if the contract is violated.
    """
    from lola_eval.calibration import Resolver as CalResolver

    cost_cfg = SimpleNamespace(flat_per_call_usd=None, pricing_file=None)
    # Build a calibration resolver (uses bundled JSONL).
    calibration = CalResolver()

    # Critical: resolver=None violates the contract. Pre-defense, this would
    # AttributeError on resolver.lookup(...) inside tier-1 or tier-2.
    cost, breakdown, tag = _per_call_cost(
        "sonnet-4-6",
        cost_cfg,
        flat_override_usd=1.50,
        resolver=None,
        calibration=calibration,
        cell_keys=("some-pack", "some-case", "none", "autonomous"),
        predict=False,
        feature_vector=None,
    )
    # Must return without raising. The flat override wins because static
    # pricing prefers an explicit flat_override over the (missing) resolver.
    assert cost == 1.50, f"expected flat 1.50 (static fallback), got {cost!r}"


def test_per_call_cost_with_calibration_no_resolver_no_flat_returns_unknown():
    """Defense in depth: even with no flat override and no resolver, the
    function must return (None, ...) rather than AttributeError.
    """
    from lola_eval.calibration import Resolver as CalResolver

    cost_cfg = SimpleNamespace(flat_per_call_usd=None, pricing_file=None)
    calibration = CalResolver()

    cost, breakdown, tag = _per_call_cost(
        "sonnet-4-6",
        cost_cfg,
        flat_override_usd=None,  # no flat path
        resolver=None,
        calibration=calibration,
        cell_keys=("some-pack", "some-case", "none", "autonomous"),
        predict=False,
        feature_vector=None,
    )
    assert cost is None, f"expected None cost, got {cost!r}"
    assert (
        "unknown" in tag.lower()
        or "no pricing source" in breakdown.lower()
        or "no source" in breakdown.lower()
    )

"""Signed lift / drift / weighted-composite math.

Lift and drift are both SIGNED. Negative values mean regression and
are first-class findings — never clamp, never absolute-value. Spec
Section 4 and Section 8 are the contracts.
"""
from __future__ import annotations

WEIGHT_TOLERANCE = 1e-9


def drift_delta(latest: float | None, baseline: float | None) -> float | None:
    if latest is None or baseline is None:
        return None
    return float(latest) - float(baseline)


def lift_percent(pack: float | None, baseline: float | None) -> float | None:
    if pack is None or baseline is None:
        return None
    if baseline == 0:
        return None
    return ((float(pack) - float(baseline)) / float(baseline)) * 100.0


def weighted_composite(
    components: dict[str, float],
    weights: dict[str, float],
) -> float:
    missing = set(components) - set(weights)
    if missing:
        raise ValueError(f"missing weight for components: {sorted(missing)}")
    extra = set(weights) - set(components)
    if extra:
        raise ValueError(f"weight without component: {sorted(extra)}")
    s = sum(weights.values())
    if abs(s - 1.0) > WEIGHT_TOLERANCE:
        raise ValueError(f"weights must sum to 1.0, got {s}")
    total = 0.0
    for name, value in components.items():
        clamped = max(0.0, min(1.0, float(value)))
        total += clamped * float(weights[name])
    return total

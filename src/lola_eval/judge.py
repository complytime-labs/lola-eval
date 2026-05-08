"""Multi-judge aggregation logic (pure functions; no I/O).

The judge subprocess invocation lives in judges/trajectory_judge.py because
it has to interface with promptfoo's python-assert callback. This module
holds the math so it is unit-testable in isolation.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal


@dataclass
class AggregateResult:
    aggregated_criteria: dict[str, float]
    composite: float
    disagreement: float


def _trimmed_mean(values: list[float]) -> float:
    """Mean after dropping one min and one max. Requires len(values) >= 3.

    For n=3 this is equivalent to the median (drop high+low, return the
    remaining value). For n>=4 it gives a stable middle-mean that resists
    a single outlier judge in either direction.
    """
    if len(values) < 3:
        raise ValueError(
            f"trimmed_mean requires at least 3 judges; got {len(values)}"
        )
    sorted_vals = sorted(values)
    return statistics.fmean(sorted_vals[1:-1])


def aggregate_judge_scores(
    judge_scores: list[dict],
    weights: dict[str, float],
    aggregation: Literal["mean", "median", "min", "trimmed_mean"] = "mean",
) -> AggregateResult:
    """Aggregate per-judge criterion scores into a canonical result.

    judge_scores: list of {"judge_id": str, "scores": {criterion: float, ...}}
    weights: rubric weights, e.g., {"correctness": 0.5, "tools": 0.3}
    aggregation: how to combine across judges per criterion. ``trimmed_mean``
                 drops the highest and lowest score before averaging and
                 requires N>=3 judges (raises ValueError otherwise).
    """
    if not judge_scores:
        raise ValueError("judge_scores is empty")
    criteria = list(weights.keys())

    for js in judge_scores:
        for c in criteria:
            if c not in js["scores"]:
                raise ValueError(
                    f"judge {js['judge_id']} missing criterion {c!r}"
                )

    aggregator = {
        "mean": statistics.fmean,
        "median": statistics.median,
        "min": min,
        "trimmed_mean": _trimmed_mean,
    }[aggregation]

    aggregated: dict[str, float] = {}
    stddevs: list[float] = []
    for c in criteria:
        values = [float(js["scores"][c]) for js in judge_scores]
        aggregated[c] = aggregator(values)
        stddevs.append(statistics.pstdev(values) if len(values) > 1 else 0.0)

    composite = sum(weights[c] * aggregated[c] for c in criteria)
    composite = max(0.0, min(1.0, composite))
    disagreement = max(stddevs) if stddevs else 0.0

    return AggregateResult(
        aggregated_criteria=aggregated,
        composite=composite,
        disagreement=disagreement,
    )

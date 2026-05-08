"""Multi-judge aggregation logic (spec Section 7)."""
import pytest

from lola_eval.judge import aggregate_judge_scores


def test_single_judge_passthrough():
    weights = {"a": 0.6, "b": 0.4}
    judge_scores = [{"judge_id": "j1", "scores": {"a": 0.8, "b": 0.6}}]
    res = aggregate_judge_scores(judge_scores, weights, aggregation="mean")
    assert res.aggregated_criteria == {"a": 0.8, "b": 0.6}
    assert res.composite == pytest.approx(0.72)
    assert res.disagreement == 0.0


def test_three_judges_mean():
    weights = {"a": 0.5, "b": 0.5}
    judge_scores = [
        {"judge_id": "j1", "scores": {"a": 0.6, "b": 0.4}},
        {"judge_id": "j2", "scores": {"a": 0.8, "b": 0.6}},
        {"judge_id": "j3", "scores": {"a": 0.7, "b": 0.5}},
    ]
    res = aggregate_judge_scores(judge_scores, weights, aggregation="mean")
    assert res.aggregated_criteria["a"] == pytest.approx(0.7)
    assert res.aggregated_criteria["b"] == pytest.approx(0.5)
    assert res.composite == pytest.approx(0.6)
    assert res.disagreement == pytest.approx(0.0816, abs=0.001)


def test_three_judges_median():
    weights = {"a": 1.0}
    judge_scores = [
        {"judge_id": "j1", "scores": {"a": 0.0}},
        {"judge_id": "j2", "scores": {"a": 0.7}},
        {"judge_id": "j3", "scores": {"a": 1.0}},
    ]
    res = aggregate_judge_scores(judge_scores, weights, aggregation="median")
    assert res.aggregated_criteria["a"] == pytest.approx(0.7)


def test_min_aggregation_pessimistic():
    weights = {"a": 1.0}
    judge_scores = [
        {"judge_id": "j1", "scores": {"a": 0.4}},
        {"judge_id": "j2", "scores": {"a": 0.8}},
    ]
    res = aggregate_judge_scores(judge_scores, weights, aggregation="min")
    assert res.aggregated_criteria["a"] == pytest.approx(0.4)


def test_disagreement_zero_when_judges_agree():
    weights = {"a": 1.0}
    judge_scores = [
        {"judge_id": "j1", "scores": {"a": 0.7}},
        {"judge_id": "j2", "scores": {"a": 0.7}},
    ]
    res = aggregate_judge_scores(judge_scores, weights, aggregation="mean")
    assert res.disagreement == 0.0


def test_missing_criterion_raises():
    weights = {"a": 0.5, "b": 0.5}
    judge_scores = [
        {"judge_id": "j1", "scores": {"a": 0.8, "b": 0.6}},
        {"judge_id": "j2", "scores": {"a": 0.7}},
    ]
    with pytest.raises(ValueError, match="missing criterion"):
        aggregate_judge_scores(judge_scores, weights, aggregation="mean")


def test_trimmed_mean_three_judges_drops_outliers():
    """N=3: drop highest+lowest, return the middle. Equivalent to median here."""
    weights = {"a": 1.0}
    judge_scores = [
        {"judge_id": "low", "scores": {"a": 0.1}},
        {"judge_id": "mid", "scores": {"a": 0.7}},
        {"judge_id": "hi",  "scores": {"a": 0.9}},
    ]
    res = aggregate_judge_scores(judge_scores, weights, aggregation="trimmed_mean")
    assert res.aggregated_criteria["a"] == pytest.approx(0.7)


def test_trimmed_mean_four_judges_averages_middle_two():
    """N=4: drop one min + one max, average the middle pair."""
    weights = {"a": 1.0}
    judge_scores = [
        {"judge_id": "j1", "scores": {"a": 0.2}},
        {"judge_id": "j2", "scores": {"a": 0.5}},
        {"judge_id": "j3", "scores": {"a": 0.6}},
        {"judge_id": "j4", "scores": {"a": 1.0}},
    ]
    res = aggregate_judge_scores(judge_scores, weights, aggregation="trimmed_mean")
    assert res.aggregated_criteria["a"] == pytest.approx(0.55)


def test_trimmed_mean_rejects_two_judges():
    """N<3: trimmed_mean is undefined; the loader should reject the config,
    but if someone bypasses it the aggregator must raise rather than
    silently degrade."""
    weights = {"a": 1.0}
    judge_scores = [
        {"judge_id": "j1", "scores": {"a": 0.5}},
        {"judge_id": "j2", "scores": {"a": 0.7}},
    ]
    with pytest.raises(ValueError, match="trimmed_mean requires at least 3"):
        aggregate_judge_scores(judge_scores, weights, aggregation="trimmed_mean")

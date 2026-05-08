"""trajectory_judge must enforce a wall-clock cap on the judge fan-out
even when individual subprocess timeouts mis-fire."""
import threading
import time

import pytest


def test_judge_fanout_respects_total_timeout(monkeypatch):
    from lola_eval._data.judges import trajectory_judge

    # Use an Event so the test can release the worker after asserting
    # the timeout fired. Without this, time.sleep(60) keeps the worker
    # thread alive in the pool's atexit joiner and slows pytest shutdown.
    release = threading.Event()

    def slow_judge(judge_spec, transcript, diff, vars_, rubric_body, weights):
        # Wait a short bound, well over the test's 1-second budget. The
        # release Event lets the test wake us up after the timeout assertion.
        release.wait(timeout=5)
        return {"correctness": 0.5}

    judges = [{"cli": "claude-code", "model": "x"},
              {"cli": "claude-code", "model": "y"}]

    monkeypatch.setattr(trajectory_judge, "_call_one_judge", slow_judge)
    start = time.time()
    try:
        with pytest.raises(trajectory_judge.JudgeTimeoutError):
            trajectory_judge._fan_out_judges(
                judges=judges, transcript="", diff="", vars_={}, rubric_body="",
                weights={"correctness": 1.0},
                wall_clock_timeout_s=1,
            )
        elapsed = time.time() - start
        assert elapsed < 3, f"fan-out should have aborted within wall-clock budget, took {elapsed:.1f}s"
    finally:
        # Wake the workers so they don't keep the process alive.
        release.set()


def test_judge_fanout_completes_normally(monkeypatch):
    from lola_eval._data.judges import trajectory_judge

    def fast_judge(judge_spec, transcript, diff, vars_, rubric_body, weights):
        return {"correctness": 0.8}

    judges = [{"cli": "claude-code", "model": "x"}]

    monkeypatch.setattr(trajectory_judge, "_call_one_judge", fast_judge)
    results = trajectory_judge._fan_out_judges(
        judges=judges, transcript="", diff="", vars_={}, rubric_body="",
        weights={"correctness": 1.0},
        wall_clock_timeout_s=10,
    )
    assert len(results) == 1
    assert results[0]["scores"]["correctness"] == 0.8

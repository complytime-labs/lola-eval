"""build_run_diff: semantic diff of two runs' stored structured outputs."""

from __future__ import annotations

import json

from lola_eval.run_diff import build_run_diff


def _row(**ov) -> dict:
    base = {
        "run_id": "aaaaaaaaaaaa",
        "fingerprint": "fp1" + "0" * 12,
        "target_cli": "claude-code",
        "target_model": "sonnet",
        "task_id": "case-001",
        "exit_status": "success",
        "scores_json": json.dumps(
            {
                "composite": 0.80,
                "components": {"correctness": 0.9, "trajectory": 0.7, "tools": 0.8},
            }
        ),
        "tool_calls_count": 12,
        "diff_bytes": 500,
        "cost_usd": 1.50,
        "duration_s": 120.0,
    }
    base.update(ov)
    return base


def test_diff_reports_composite_and_component_deltas():
    a = _row()
    b = _row(
        run_id="bbbbbbbbbbbb",
        scores_json=json.dumps(
            {
                "composite": 0.92,
                "components": {"correctness": 0.95, "trajectory": 0.9, "tools": 0.8},
            }
        ),
    )
    text = build_run_diff(a, b)
    assert "composite" in text
    assert "0.80" in text and "0.92" in text
    assert "+0.12" in text  # composite delta
    assert "correctness" in text
    assert "trajectory" in text


def test_diff_warns_on_different_fingerprints():
    a = _row(fingerprint="fpA")
    b = _row(run_id="bbbbbbbbbbbb", fingerprint="fpB")
    text = build_run_diff(a, b)
    assert "not strictly comparable" in text.lower()


def test_diff_no_warning_on_same_fingerprint():
    a = _row(fingerprint="same")
    b = _row(run_id="bbbbbbbbbbbb", fingerprint="same")
    text = build_run_diff(a, b)
    assert "not strictly comparable" not in text.lower()


def test_diff_reports_counter_deltas_and_exit_status():
    a = _row(tool_calls_count=12, exit_status="success")
    b = _row(run_id="bbbbbbbbbbbb", tool_calls_count=9, exit_status="target_error")
    text = build_run_diff(a, b)
    assert "tool_calls" in text
    assert "-3" in text
    assert "success" in text and "target_error" in text


def test_diff_reports_token_and_turns_deltas():
    a = _row(input_tokens=1000, output_tokens=200, turns=5)
    b = _row(run_id="bbbbbbbbbbbb", input_tokens=1500, output_tokens=250, turns=7)
    text = build_run_diff(a, b)
    assert "input_tokens" in text and "+500" in text
    assert "output_tokens" in text and "+50" in text
    assert "turns" in text and "+2" in text

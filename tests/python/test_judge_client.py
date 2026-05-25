"""Universal judge client: wraps `opencode run --agent judge`."""

from __future__ import annotations
import os
from pathlib import Path

import pytest

from lola_eval import judge_client
from lola_eval.judge_client import judge, JudgeError

REPO = Path(__file__).resolve().parents[2]
FAKE_OPENCODE_DIR = REPO / "tests" / "fixtures" / "fake-opencode"


@pytest.fixture
def fake_path(monkeypatch):
    monkeypatch.setenv("PATH", f"{FAKE_OPENCODE_DIR}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_MODE", "judge")


def test_judge_returns_parsed_components(fake_path):
    result = judge(
        rubric_text="rubric body",
        transcript="<transcript>",
        diff="<diff>",
        judge_model="claude-sonnet-4-6",
    )
    assert "components" in result
    assert result["components"]["correctness"] == 1.0
    assert result["explanation"]


def test_judge_raises_on_crash(monkeypatch):
    monkeypatch.setenv("PATH", f"{FAKE_OPENCODE_DIR}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_MODE", "crash")
    with pytest.raises(JudgeError):
        judge(rubric_text="r", transcript="t", diff="d", judge_model="x")


def test_transcript_limit_sonnet_reserves_headroom():
    # 800_000 char window * 0.8 reserved for rubric/diff/reasoning
    assert judge_client._transcript_limit("claude-sonnet-4-6") == 640_000


def test_transcript_limit_matches_on_alias_substring():
    assert judge_client._transcript_limit("sonnet") == 640_000
    assert judge_client._transcript_limit("opus") == 640_000
    assert judge_client._transcript_limit("claude-haiku-4-5-20251001") == 640_000


def test_transcript_limit_unknown_model_falls_back_to_50k():
    assert judge_client._transcript_limit("some-unknown-model") == 50_000


def test_judge_timeout_scales_with_transcript_length():
    # ~2s per 1000 chars == len // 500, floored at the 120s base
    assert judge_client._judge_timeout(700_000) == 1400
    assert judge_client._judge_timeout(50_000) == 120  # 100 < base -> floor
    assert judge_client._judge_timeout(0) == 120


def test_build_prompt_preserves_verdict_past_old_50k_cutoff():
    # The verdict lives at the very end of a large transcript — exactly the
    # region the old `transcript[:50_000]` cut dropped. With the sonnet
    # window it must survive.
    verdict = "FINAL_VERDICT: PASS — all findings verified"
    transcript = ("x" * 600_000) + verdict
    limit = judge_client._transcript_limit("claude-sonnet-4-6")
    prompt = judge_client._build_prompt("rubric body", transcript, "diff", limit)
    assert verdict in prompt


def test_build_prompt_truncates_at_explicit_limit():
    transcript = "A" * 100
    prompt = judge_client._build_prompt("r", transcript, "d", 10)
    assert "A" * 10 in prompt
    assert "A" * 11 not in prompt


def test_judge_uses_explicit_transcript_limit(fake_path, monkeypatch):
    captured = {}
    real_build = judge_client._build_prompt

    def spy(rubric_text, transcript, diff, transcript_limit):
        captured["limit"] = transcript_limit
        return real_build(rubric_text, transcript, diff, transcript_limit)

    monkeypatch.setattr(judge_client, "_build_prompt", spy)
    judge(
        rubric_text="r",
        transcript="t" * 5000,
        diff="d",
        judge_model="claude-sonnet-4-6",
        transcript_limit=100,
    )
    assert captured["limit"] == 100


def test_judge_defaults_transcript_limit_from_model(fake_path, monkeypatch):
    captured = {}
    real_build = judge_client._build_prompt

    def spy(rubric_text, transcript, diff, transcript_limit):
        captured["limit"] = transcript_limit
        return real_build(rubric_text, transcript, diff, transcript_limit)

    monkeypatch.setattr(judge_client, "_build_prompt", spy)
    judge(rubric_text="r", transcript="t" * 5000, diff="d", judge_model="claude-sonnet-4-6")
    assert captured["limit"] == 640_000


def test_fit_transcript_under_limit_is_unchanged():
    t = "x" * 1000
    assert judge_client._fit_transcript(t, 5000) == t


def test_fit_transcript_over_limit_keeps_head_and_tail():
    head = "HEAD_SETUP_CONTEXT "
    tail = " FINAL_VERDICT: PASS"
    transcript = head + ("m" * 1_000_000) + tail
    limit = 40_000
    out = judge_client._fit_transcript(transcript, limit)
    # Stays within the window...
    assert len(out) <= limit
    # ...preserves BOTH the opening setup and the closing verdict...
    assert out.startswith("HEAD_SETUP_CONTEXT")
    assert out.endswith("FINAL_VERDICT: PASS")
    # ...and marks the elision so the judge knows content was dropped.
    assert "elided" in out


def test_build_prompt_preserves_verdict_when_transcript_exceeds_window():
    # Verdict at the very end of a transcript LARGER than the window must
    # survive (head+tail), not be dropped by a plain head cut.
    verdict = "FINAL_VERDICT: all findings verified"
    transcript = ("z" * 900_000) + verdict
    limit = judge_client._transcript_limit("claude-sonnet-4-6")  # 640_000 < 900_000
    prompt = judge_client._build_prompt("rubric", transcript, "diff", limit)
    assert verdict in prompt
    assert "elided" in prompt


def test_run_with_heartbeat_emits_while_running(capsys, monkeypatch):
    monkeypatch.setenv("LOLA_HEARTBEAT_S", "0.05")
    proc = judge_client._run_with_heartbeat(["bash", "-c", "sleep 0.4"], 5, "test-model")
    assert proc.returncode == 0
    err = capsys.readouterr().err
    assert "still running" in err
    assert "test-model" in err


def test_run_with_heartbeat_quiet_for_fast_call(capsys, monkeypatch):
    monkeypatch.setenv("LOLA_HEARTBEAT_S", "30")
    judge_client._run_with_heartbeat(["bash", "-c", "true"], 5, "m")
    assert "still running" not in capsys.readouterr().err

"""Universal judge client: wraps `opencode run --agent judge`."""
from __future__ import annotations
import os
from pathlib import Path

import pytest

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

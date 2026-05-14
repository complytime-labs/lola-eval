"""Markdown report renderer."""
from __future__ import annotations

import json
from pathlib import Path

from lola_eval import store
from lola_eval.markdown_report import build_markdown, _format_tokens, _format_cost, _format_duration


def _make_row(**overrides) -> dict:
    base = {
        "run_id": "test-run-001",
        "timestamp": "2026-05-14T00:00:00Z",
        "fingerprint": "abc123",
        "target_cli": "claude-code",
        "target_model": "sonnet",
        "target_cli_ver": "2.1.0",
        "pack_id": "project",
        "profile_id": "none",
        "task_id": "case-001",
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "autonomous",
        "invocation": "passive",
        "judge_cli": "claude-code",
        "judge_model": "opus",
        "scores_json": json.dumps({
            "composite": 0.85,
            "components": {"correctness": 0.9, "trajectory": 0.8, "tools": 0.85},
            "explanation": "Good work",
        }),
        "transcript_path": "/tmp/transcript.jsonl",
        "exit_status": "success",
        "cost_usd": 1.50,
        "duration_s": 120.0,
        "turns": 5,
        "tool_calls_count": 12,
        "diff_bytes": 500,
        "input_tokens": 50000,
        "output_tokens": 3000,
    }
    base.update(overrides)
    return base


def test_format_tokens():
    assert _format_tokens(1234) == "1.2K"
    assert _format_tokens(12345) == "12.3K"
    assert _format_tokens(123) == "123"
    assert _format_tokens(None) == "-"


def test_format_cost():
    assert _format_cost(1.5) == "$1.50"
    assert _format_cost(0.042) == "$0.04"
    assert _format_cost(None) == "-"


def test_format_duration():
    assert _format_duration(120.0) == "2.0m"
    assert _format_duration(45.0) == "45s"
    assert _format_duration(None) == "-"


def test_build_markdown_basic(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row())
    last_run = tmp_path / ".lola-eval" / "last-run.json"
    last_run.write_text(json.dumps([{
        "cli": "claude-code", "model": "sonnet",
        "task_id": "case-001", "pack_id": "project",
        "profile_id": "none",
        "composite": 0.85, "rubric_pass_threshold": 0.6,
    }]))
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "## Matrix Summary" in content
    assert "sonnet" in content
    assert "0.85" in content


def test_build_markdown_with_profiles(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(run_id="r1", profile_id="bare"))
    store.insert_run(db, _make_row(
        run_id="r2", profile_id="superpowers",
        scores_json=json.dumps({
            "composite": 0.92,
            "components": {"correctness": 0.95, "trajectory": 0.9, "tools": 0.9},
            "explanation": "Excellent",
        }),
    ))
    last_run = tmp_path / ".lola-eval" / "last-run.json"
    last_run.write_text(json.dumps([
        {"cli": "claude-code", "model": "sonnet", "task_id": "case-001",
         "pack_id": "project", "profile_id": "bare", "composite": 0.85,
         "rubric_pass_threshold": 0.6},
        {"cli": "claude-code", "model": "sonnet", "task_id": "case-001",
         "pack_id": "project", "profile_id": "superpowers", "composite": 0.92,
         "rubric_pass_threshold": 0.6},
    ]))
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "Profile" in content
    assert "bare" in content
    assert "superpowers" in content

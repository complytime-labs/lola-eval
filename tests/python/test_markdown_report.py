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
        "scores_json": json.dumps(
            {
                "composite": 0.85,
                "components": {"correctness": 0.9, "trajectory": 0.8, "tools": 0.85},
                "explanation": "Good work",
            }
        ),
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
    last_run.write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "## Matrix Summary" in content
    assert "sonnet" in content
    assert "0.85" in content


def test_report_renders_provenance_when_present(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(
        db,
        _make_row(
            git_sha="abc1234def",
            git_branch="feature/x",
            subject_version="mymod@1.2.3",
            fingerprint_version="2",
        ),
    )
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "## Provenance" in content
    assert "abc1234def" in content
    assert "mymod@1.2.3" in content


def test_report_hides_provenance_when_absent(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row())  # no provenance fields set
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    assert "## Provenance" not in out.read_text()


def test_report_renders_partial_provenance(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(git_sha="deadbeefcafe"))  # sha only
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "## Provenance" in content
    assert "deadbeefcafe" in content
    assert "**Remote**" not in content


def test_run_details_embeds_transcript_content(tmp_path: Path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text('{"type":"x"}\n')
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(transcript_path=str(transcript)))
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "<details>" in content
    assert '{"type":"x"}' in content


def test_run_details_transcript_not_found_falls_back(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(transcript_path=str(tmp_path / "nope.jsonl")))
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    assert "(not found)" in out.read_text()


def test_run_details_embeds_non_utf8_transcript_without_crashing(tmp_path: Path):
    """A transcript with invalid UTF-8 bytes must not crash the report build
    (transcripts are model/CLI output and aren't guaranteed UTF-8)."""
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_bytes(b'{"type":"x"}\n\xff\xfe bad bytes\n')
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(transcript_path=str(transcript)))
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert '{"type":"x"}' in content  # valid prefix survives; bad bytes replaced


def test_build_markdown_with_profiles(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(run_id="r1", profile_id="bare"))
    store.insert_run(
        db,
        _make_row(
            run_id="r2",
            profile_id="superpowers",
            scores_json=json.dumps(
                {
                    "composite": 0.92,
                    "components": {"correctness": 0.95, "trajectory": 0.9, "tools": 0.9},
                    "explanation": "Excellent",
                }
            ),
        ),
    )
    last_run = tmp_path / ".lola-eval" / "last-run.json"
    last_run.write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "bare",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                },
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "superpowers",
                    "composite": 0.92,
                    "rubric_pass_threshold": 0.6,
                },
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "Profile" in content
    assert "bare" in content
    assert "superpowers" in content


def test_report_shows_resolved_judge_model(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(judge_model_resolved="claude-sonnet-4-6-judge"))
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    assert "claude-sonnet-4-6-judge" in out.read_text()


def test_report_shows_resolved_target_model(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(target_model_resolved="claude-sonnet-4-6-real"))
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "claude-sonnet-4-6-real" in content

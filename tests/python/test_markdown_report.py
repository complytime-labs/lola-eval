"""Markdown report renderer."""

from __future__ import annotations

import json
from pathlib import Path

from lola_eval import store
from lola_eval.markdown_report import (
    build_markdown,
    build_json,
    _commit_url,
    _format_tokens,
    _format_cost,
    _format_duration,
    _rationale_md,
)


def _seed_one(tmp_path, **row_overrides):
    """Seed a runs.db + last-run.json with a single matching cell."""
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    store.init_db(db)
    store.insert_run(db, _make_row(**row_overrides))
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
    return tmp_path / ".lola-eval"


def test_build_json_wraps_rows_in_metadata_envelope(tmp_path: Path):
    """JSON output is a metadata envelope (schema version, run-level summary,
    drift/lift) rather than a bare array, so machine consumers can detect
    breaking changes and read aggregates."""
    results_dir = _seed_one(tmp_path)
    out = tmp_path / "report.json"
    build_json(out_path=out, results_dir=results_dir)
    doc = json.loads(out.read_text())
    assert doc["schema_version"] == "1"
    assert doc["lola_eval_version"]
    assert "generated_at" in doc
    assert isinstance(doc["rows"], list) and len(doc["rows"]) == 1
    assert doc["summary"]["total_cells"] == 1
    assert doc["summary"]["passed"] == 1
    assert doc["summary"]["failed"] == 0
    assert doc["summary"]["cost_usd"] == 1.5
    assert "drift" in doc and "lift" in doc and "compare" in doc


def test_build_json_counts_failures(tmp_path: Path):
    """A composite below the rubric threshold counts as failed in the summary."""
    results_dir = _seed_one(
        tmp_path,
        scores_json=json.dumps({"composite": 0.40, "components": {}, "explanation": ""}),
    )
    out = tmp_path / "report.json"
    build_json(out_path=out, results_dir=results_dir)
    doc = json.loads(out.read_text())
    assert doc["summary"]["passed"] == 0
    assert doc["summary"]["failed"] == 1


def test_build_json_serializes_populated_compare(tmp_path: Path):
    """A baseline (pack=none) plus a matching pack row makes compare_all return
    ComparisonRow dataclasses; the envelope must serialize them to JSON dicts
    instead of crashing on the dataclass."""
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(run_id="b1", pack_id="none"))
    store.insert_run(db, _make_row(run_id="p1", pack_id="mypack@abc123"))
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "mypack@abc123",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.json"
    build_json(out_path=out, results_dir=tmp_path / ".lola-eval")
    doc = json.loads(out.read_text())
    assert isinstance(doc["compare"], list) and len(doc["compare"]) >= 1
    assert all(isinstance(r, dict) for r in doc["compare"])
    assert doc["compare"][0]["pack_id"] == "mypack@abc123"


def test_rationale_md_preserves_line_breaks_as_hard_breaks():
    """Single newlines in the judge output become markdown hard breaks so the
    structure survives rendering instead of collapsing into one line."""
    out = _rationale_md("Detection: correct.\nEvidence: strong.\nSeverity: ok.")
    assert out == "Detection: correct.  \nEvidence: strong.  \nSeverity: ok."


def test_rationale_md_keeps_paragraph_separation():
    out = _rationale_md("First para line.\n\nSecond para line.")
    assert out == "First para line.\n\nSecond para line."


def test_rationale_md_empty_falls_back():
    assert _rationale_md("") == "(no explanation)"
    assert _rationale_md("   ") == "(no explanation)"


def test_commit_url_from_ssh_github():
    assert (
        _commit_url("git@github.com:org/repo.git", "abc123def")
        == "https://github.com/org/repo/commit/abc123def"
    )


def test_commit_url_from_https_gitlab():
    assert (
        _commit_url("https://gitlab.com/group/sub/repo.git", "deadbeef")
        == "https://gitlab.com/group/sub/repo/commit/deadbeef"
    )


def test_commit_url_strips_embedded_credentials():
    assert (
        _commit_url("https://x-access-token:SECRET@github.com/org/repo.git", "f00")
        == "https://github.com/org/repo/commit/f00"
    )


def test_commit_url_unknown_host_returns_none():
    assert _commit_url("git@bitbucket.org:org/repo.git", "abc123") is None


def test_commit_url_missing_inputs_returns_none():
    assert _commit_url(None, "abc") is None
    assert _commit_url("git@github.com:org/repo.git", None) is None


def test_commit_url_rejects_markdown_injection_in_path():
    """A remote whose host is github.com but whose path carries markdown-link
    breakout characters must not produce a clickable link."""
    evil = "https://github.com/a)](javascript:alert(1))x/repo"
    assert _commit_url(evil, "abc123") is None


def test_commit_url_host_match_is_case_insensitive():
    assert (
        _commit_url("git@GitHub.com:org/repo.git", "abc123")
        == "https://github.com/org/repo/commit/abc123"
    )


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


def test_md_cell_sanitizes_pipes_and_newlines():
    """Free-text infra error_message must not break the markdown table."""
    from lola_eval.markdown_report import _md_cell

    assert _md_cell("a | b\nc   d") == "a \\| b c d"
    assert _md_cell(None) == ""
    assert _md_cell("") == ""


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


def test_provenance_deduplicates_identical_git_data(tmp_path: Path):
    """All cells in one run share a git checkout, so provenance should appear
    once — listing the cells it covers — not once per cell."""
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    prov = dict(git_sha="abc1234def", git_branch="main", git_remote="git@github.com:o/r.git")
    store.insert_run(db, _make_row(run_id="r1", task_id="case-001", **prov))
    store.insert_run(db, _make_row(run_id="r2", task_id="case-002", **prov))
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
                },
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-002",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                },
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    # One Provenance section, one block, the full SHA printed exactly once.
    assert content.count("## Provenance") == 1
    assert content.count("abc1234def") == 1
    # Both cells named as covered by that one block.
    assert "case-001" in content
    assert "case-002" in content


def test_provenance_keeps_distinct_blocks_for_distinct_checkouts(tmp_path: Path):
    """Two different commits remain two separate blocks."""
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(run_id="r1", task_id="case-001", git_sha="aaaa111", git_branch="main"))
    store.insert_run(db, _make_row(run_id="r2", task_id="case-002", git_sha="bbbb222", git_branch="main"))
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
                },
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-002",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                },
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "aaaa111" in content
    assert "bbbb222" in content


def test_provenance_renders_clickable_commit_link(tmp_path: Path):
    """A GitHub/GitLab remote turns the commit into a clickable link; the
    redundant standalone Remote bullet is dropped once it's encoded there."""
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(
        db,
        _make_row(
            git_sha="abc1234def",
            git_branch="main",
            git_remote="git@github.com:org/repo.git",
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
    assert "](https://github.com/org/repo/commit/abc1234def)" in content
    assert "**Remote**" not in content


def test_provenance_keeps_remote_bullet_for_unlinkable_host(tmp_path: Path):
    """When no web URL can be built, fall back to plain commit + remote text."""
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(
        db,
        _make_row(git_sha="abc1234def", git_remote="git@bitbucket.org:org/repo.git"),
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
    assert "/commit/" not in content
    assert "**Remote**: git@bitbucket.org:org/repo.git" in content


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
    # Profiles are carried in the cell label (cli/model/task/profile), not a
    # separate Profile column.
    assert "claude-code/sonnet/case-001/bare" in content
    assert "claude-code/sonnet/case-001/superpowers" in content


def test_markdown_has_drift_lift_compare_infra_sections(tmp_path: Path):
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    # baseline + pack rows for the same cell so compare/lift have a pair
    store.insert_run(db, _make_row(run_id="base", pack_id="none"))
    store.insert_run(
        db,
        _make_row(
            run_id="pack",
            pack_id="project",
            scores_json=json.dumps(
                {
                    "composite": 0.92,
                    "components": {"correctness": 0.95},
                    "explanation": "good",
                }
            ),
        ),
    )
    # infra-failure row
    store.insert_run(
        db,
        _make_row(
            run_id="infra",
            pack_id="project",
            exit_status="setup_error",
            error_message="boom",
            scores_json=json.dumps({"composite": None}),
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
                    "composite": 0.92,
                    "rubric_pass_threshold": 0.6,
                }
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "## Drift" in content
    assert "## Lift" in content
    assert "## Compare" in content
    assert "## Infra failures" in content


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


def test_cell_headers_include_task_id_to_avoid_collisions(tmp_path: Path):
    """Two tasks sharing one cli/model must produce distinct section headers;
    otherwise markdown anchors collide and in-page links break."""
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(run_id="r1", task_id="case-001"))
    store.insert_run(db, _make_row(run_id="r2", task_id="case-002"))
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
                },
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-002",
                    "pack_id": "project",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                },
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "### claude-code/sonnet/case-001" in content
    assert "### claude-code/sonnet/case-002" in content


def test_cell_headers_include_pack_id_when_multiple_packs(tmp_path: Path):
    """When a cell is run against more than one pack, the pack_id is part of
    the label so per-pack sections stay distinct."""
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True)
    store.init_db(db)
    store.insert_run(db, _make_row(run_id="r1", pack_id="none"))
    store.insert_run(db, _make_row(run_id="r2", pack_id="mypack@abc123"))
    (tmp_path / ".lola-eval" / "last-run.json").write_text(
        json.dumps(
            [
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "none",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                },
                {
                    "cli": "claude-code",
                    "model": "sonnet",
                    "task_id": "case-001",
                    "pack_id": "mypack@abc123",
                    "profile_id": "none",
                    "composite": 0.85,
                    "rubric_pass_threshold": 0.6,
                },
            ]
        )
    )
    out = tmp_path / "report.md"
    build_markdown(out_path=out, results_dir=tmp_path / ".lola-eval")
    content = out.read_text()
    assert "### claude-code/sonnet/case-001/none" in content
    assert "### claude-code/sonnet/case-001/mypack@abc123" in content


def _report_row(**overrides) -> dict:
    """A report-shaped row (what _fetch_rows produces), for section helpers."""
    base = {
        "cli": "claude-code",
        "model": "sonnet",
        "task_id": "case-001",
        "pack_id": "project",
        "profile_id": "none",
        "composite": 0.80,
        "rubric_pass_threshold": 0.6,
        "components": {"correctness": 0.8},
        "explanation": "ok",
        "cost_usd": 2.00,
        "duration_s": 60.0,
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_tokens": None,
        "cache_creation_tokens": None,
        "exit_status": "success",
    }
    base.update(overrides)
    return base


def test_matrix_summary_labels_include_task_id_and_exit_status():
    from lola_eval.markdown_report import _matrix_summary

    md = _matrix_summary([_report_row()], has_profiles=False, has_packs=False)
    assert "claude-code/sonnet/case-001" in md
    assert "| Exit |" in md
    assert "| success |" in md


def test_matrix_summary_total_row_aggregates():
    from lola_eval.markdown_report import _matrix_summary

    rows = [
        _report_row(task_id="case-001", composite=0.90, cost_usd=1.00, duration_s=30.0),
        _report_row(task_id="case-002", composite=0.50, cost_usd=3.00, duration_s=90.0),
    ]
    md = _matrix_summary(rows, has_profiles=False, has_packs=False)
    total = [ln for ln in md.splitlines() if "Total" in ln]
    assert len(total) == 1
    # mean composite 0.70, summed cost $4.00, summed duration 2.0m, 1 pass / 1 fail
    assert "0.70" in total[0]
    assert "$4.00" in total[0]
    assert "2.0m" in total[0]
    assert "1p/1f" in total[0]


def test_matrix_summary_total_row_absent_when_no_rows():
    from lola_eval.markdown_report import _matrix_summary

    md = _matrix_summary([], has_profiles=False, has_packs=False)
    assert "Total" not in md


def test_dimension_breakdown_labels_include_task_id():
    from lola_eval.markdown_report import _dimension_breakdown

    md = _dimension_breakdown([_report_row()], has_profiles=False, has_packs=False)
    assert "claude-code/sonnet/case-001" in md


def test_token_economics_labels_and_total_row():
    from lola_eval.markdown_report import _token_economics

    rows = [
        _report_row(task_id="case-001", input_tokens=1000, output_tokens=500, cost_usd=1.00),
        _report_row(task_id="case-002", input_tokens=2000, output_tokens=500, cost_usd=2.00),
    ]
    md = _token_economics(rows, has_profiles=False, has_packs=False)
    assert "claude-code/sonnet/case-001" in md
    total = [ln for ln in md.splitlines() if "Total" in ln]
    assert len(total) == 1
    assert "3.0K" in total[0]  # summed input
    assert "1.0K" in total[0]  # summed output
    assert "$3.00" in total[0]


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

"""runner.run_matrix inherits BOTH stdout and stderr so users see real-time
progress from promptfoo (per-row breadcrumbs and the result table land on
stdout, not stderr). The runner prints a one-line diagnostic when promptfoo
times out or exits non-zero."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from lola_eval import runner
from lola_eval.config import LolaEvalConfig, TargetEntry, JudgeEntry


def _minimal_cfg(tmp_path: Path) -> LolaEvalConfig:
    return LolaEvalConfig(
        targets=[TargetEntry(cli="claude-code", models=["sonnet"])],
        # Mode 1: no explicit packs. Single pack_id="project" pass per cell.
        judges=[JudgeEntry(cli="claude-code", model="sonnet")],
        tests_dir="tests",
        results_dir=str(tmp_path / ".lola-eval"),
    )


def _make_minimal_case(target_root: Path) -> None:
    case = target_root / "tests" / "case-x"
    case.mkdir(parents=True)
    (case / "task.yaml").write_text("task_version: '1'\ntimeout_seconds: 60\n")
    (case / "prompt.md").write_text("noop")
    (case / "rubric.md").write_text(
        "---\nrubric_version: '1'\npass_threshold: 0.6\nweights:\n  c: 1.0\n---\n"
    )
    (case / "starter").mkdir()


def test_promptfoo_timeout_emits_diagnostic(tmp_path: Path, monkeypatch, capsys):
    """On timeout the runner prints a single diagnostic line citing the
    configured timeout. The subprocess's stderr is inherited (streamed
    live during the run), so the runner no longer replays a captured
    buffer after the fact."""
    cfg = _minimal_cfg(tmp_path)
    target_root = tmp_path
    _make_minimal_case(target_root)

    def fake_run(*args, **kwargs):
        # Both streams must be inherited so the user sees real-time
        # progress. promptfoo writes breadcrumbs and the result table to
        # stdout (not stderr); capturing stdout silences them. Sanity-
        # check both contracts so a future refactor that re-introduces
        # capturing breaks loudly here.
        assert kwargs.get("stdout") is None, (
            "runner must inherit stdout so promptfoo progress is visible"
        )
        assert kwargs.get("stderr") is None, (
            "runner must inherit stderr so provider breadcrumbs stream live"
        )
        raise subprocess.TimeoutExpired(
            cmd=args[0] if args else kwargs.get("args", ["promptfoo"]),
            timeout=10,
            output=b"",
            stderr=b"",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_resolve_promptfoo_cmd", lambda: ["promptfoo"])

    runner.run_matrix(cfg, target_root)
    err = capsys.readouterr().err
    assert "promptfoo timed out after" in err, (
        f"runner should announce the timeout on stderr. Got stderr: {err!r}"
    )


def test_promptfoo_nonzero_exit_emits_diagnostic(tmp_path: Path, monkeypatch, capsys):
    """Non-zero exit prints a single diagnostic line; the live stderr
    stream is the substantive output, the diagnostic just flags
    the failure for log scrapers."""
    cfg = _minimal_cfg(tmp_path)
    target_root = tmp_path
    _make_minimal_case(target_root)

    fake_completed = MagicMock(returncode=2, stdout="")

    def fake_run(*args, **kwargs):
        # Same contract check as the timeout test.
        assert kwargs.get("stdout") is None
        assert kwargs.get("stderr") is None
        return fake_completed

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_resolve_promptfoo_cmd", lambda: ["promptfoo"])

    runner.run_matrix(cfg, target_root)
    err = capsys.readouterr().err
    assert "promptfoo exited 2" in err


def test_setup_error_row_surfaces_install_pack_message(tmp_path: Path, monkeypatch):
    """Regression: a runs.db row with exit_status=setup_error must be
    converted to a RowResult with failure_kind='setup_error' and the
    error_message preserved as failure_reason. Without this, install_pack
    failures get reduced to 'composite 0.0 below threshold' or fall through
    to 'no_run_produced', hiding the actual lola message ('Module not
    found') that the user needs to act on."""
    import json as _json
    import sqlite3

    from lola_eval import runner, store

    cfg = _minimal_cfg(tmp_path)
    target_root = tmp_path
    _make_minimal_case(target_root)

    # Seed runs.db with a setup_error row for the cell we'll query.
    db = tmp_path / ".lola-eval" / "runs.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    store.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO runs ("
        "run_id, timestamp, fingerprint, target_cli, target_model, "
        "target_cli_ver, pack_id, task_id, task_version, rubric_version, "
        "exec_mode, invocation, judge_cli, judge_model, scores_json, "
        "transcript_path, exit_status, error_message"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "run-x", "2026-05-11T00:00:00Z", "fp-x",
            "claude-code", "sonnet", "claude 2.1",
            "project", "case-x", "1", "1",
            "autonomous", "passive", "claude-code", "sonnet",
            _json.dumps({"composite": 0.0, "components": {}, "explanation": "setup_error"}),
            "/tmp/t.jsonl", "setup_error",
            "install_pack.sh: FAILED pack=example-pack@local "
            "target=claude-code: Module 'example-pack' not found",
        ),
    )
    conn.commit()
    conn.close()

    rows = runner._collect_rows(
        cfg, target_root, cases=[target_root / "tests" / "case-x"],
        packs=["project"], since="2026-01-01T00:00:00Z",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.failure_kind == "setup_error"
    assert "Module 'example-pack' not found" in (row.failure_reason or "")

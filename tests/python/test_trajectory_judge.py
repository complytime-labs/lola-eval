"""Trajectory judge: Promptfoo python-assert integration."""

from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "lola_eval" / "_data" / "judges"))

import trajectory_judge  # noqa: E402


def _write_transcript(path: Path) -> None:
    path.write_text(
        '{"type":"system","subtype":"init","model":"x"}\n'
        '{"type":"result","subtype":"success","total_cost_usd":0.01,"duration_ms":1,"num_turns":1,"is_error":false}\n'
    )


def _envelope(transcript_path: str, exit_status: str = "success") -> str:
    return json.dumps(
        {
            "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "transcript_path": transcript_path,
            "turns": 1,
            "tool_calls": [],
            "exit_status": exit_status,
            "duration_s": 1.2,
            "diff": "diff --git a b\n",
            "cost_usd": 0.01,
        }
    )


def _vars():
    return {
        "target_cli": "claude-code",
        "target_model": "claude-sonnet-4-6",
        "pack_id": "none",
        "task_id": "case-001-fix-bug",
        "task_version": "1",
        "rubric_version": "1",
        "exec_mode": "autonomous",
        "invocation": "passive",
        "judge_cli": "opencode",
        "judge_model": "claude-sonnet-4-6",
    }


def test_get_assert_returns_structured_result(tmp_path, monkeypatch):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HARNESS_TARGET_CLI_VER", "claude 2.1.131")
    monkeypatch.setenv("LOLA_TEST_SETS_DIR", str(REPO / "examples" / "default" / ".lola-eval" / "test_sets"))

    fake_judge_result = {
        "components": {"correctness": 1.0, "trajectory": 0.9, "tools": 1.0},
        "explanation": "clean fix",
    }
    with patch.object(trajectory_judge, "judge", return_value=fake_judge_result):
        r = trajectory_judge.get_assert(
            output=_envelope(str(transcript)),
            context={"vars": _vars()},
        )

    assert r["pass"] is True
    assert 0.9 <= r["score"] <= 1.0
    assert "componentResults" in r


def test_setup_error_skips_judge_and_marks_unscored(tmp_path, monkeypatch):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("")

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HARNESS_TARGET_CLI_VER", "claude 2.1.131")

    with patch.object(trajectory_judge, "judge") as mock:
        r = trajectory_judge.get_assert(
            output=_envelope(str(transcript), exit_status="setup_error"),
            context={"vars": _vars()},
        )
        mock.assert_not_called()
    assert r["pass"] is False
    assert r["score"] == 0.0
    assert "setup_error" in r["reason"]


def test_setup_error_persists_envelope_error_message_to_db(tmp_path, monkeypatch):
    """Regression: when the provider ships exit_status=setup_error with an
    error_message (e.g. "install_pack.sh: FAILED ... Module 'foo' not
    found"), the judge MUST persist that string to runs.db's
    error_message column. Otherwise the runner falls back to
    "no_run_produced" or surfaces an empty reason, hiding the actual
    cause from the user.
    """
    import sqlite3

    transcript = tmp_path / "t.jsonl"
    transcript.write_text("")

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HARNESS_TARGET_CLI_VER", "claude 2.1.131")

    envelope = json.loads(_envelope(str(transcript), exit_status="setup_error"))
    envelope["error_message"] = (
        "install_pack.sh: FAILED pack=example-pack@local "
        "target=claude-code: Module 'example-pack' not found"
    )

    r = trajectory_judge.get_assert(
        output=json.dumps(envelope),
        context={"vars": _vars()},
    )
    assert r["pass"] is False
    assert "Module 'example-pack' not found" in r["reason"], (
        f"reason must surface the install_pack message; got {r['reason']!r}"
    )

    # Verify the row landed in runs.db with the actionable error_message.
    db = tmp_path / "state" / "lola-eval" / "runs.db"
    assert db.exists(), "judge must persist setup_error rows to runs.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT exit_status, error_message FROM runs WHERE run_id=?",
        (envelope["run_id"],),
    ).fetchone()
    conn.close()
    assert row is not None, "setup_error row must be persisted"
    assert row["exit_status"] == "setup_error"
    assert "Module 'example-pack' not found" in (row["error_message"] or "")


def test_persists_row_to_sqlite(tmp_path, monkeypatch):
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HARNESS_TARGET_CLI_VER", "claude 2.1.131")
    monkeypatch.setenv("LOLA_TEST_SETS_DIR", str(REPO / "examples" / "default" / ".lola-eval" / "test_sets"))

    fake_judge_result = {
        "components": {"correctness": 1.0, "trajectory": 0.9, "tools": 1.0},
        "explanation": "clean fix",
    }
    with patch.object(trajectory_judge, "judge", return_value=fake_judge_result):
        trajectory_judge.get_assert(
            output=_envelope(str(transcript)),
            context={"vars": _vars()},
        )

    from lola_eval import store, xdg

    rows = store.fetch_by_fingerprint(xdg.db_path(), fingerprint=_any_fingerprint(xdg.db_path()))
    assert len(rows) == 1
    assert rows[0]["target_cli"] == "claude-code"
    assert json.loads(rows[0]["scores_json"])["composite"] > 0.9


def _any_fingerprint(db_path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    fp = conn.execute("SELECT fingerprint FROM runs LIMIT 1").fetchone()[0]
    conn.close()
    return fp


def test_persist_writes_new_telemetry_columns(tmp_path, monkeypatch):
    """_persist must write turns, tool_calls_count, diff_bytes from envelope."""
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)

    envelope = json.loads(_envelope(str(transcript), exit_status="success"))
    envelope["turns"] = 7
    envelope["tool_calls"] = [{"name": "Read"}, {"name": "Edit"}, {"name": "Bash"}]
    envelope["diff"] = "x" * 1024  # 1024 bytes when utf-8 encoded

    fp = "f" * 64
    scores = {"composite": 0.8, "components": {"correctness": 0.8}, "explanation": "test"}

    trajectory_judge._persist(envelope, _vars(), scores, fp)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT turns, tool_calls_count, diff_bytes FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    assert row == (7, 3, 1024)


def test_persist_writes_token_count_columns(tmp_path, monkeypatch):
    """_persist must propagate input/output/cache token counts from the envelope."""
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)

    envelope = json.loads(_envelope(str(transcript), exit_status="success"))
    envelope["input_tokens"] = 143
    envelope["output_tokens"] = 4422
    envelope["cache_read_tokens"] = 1024
    envelope["cache_creation_tokens"] = 256

    fp = "h" * 64
    scores = {"composite": 0.8, "components": {"correctness": 0.8}, "explanation": "tok"}

    trajectory_judge._persist(envelope, _vars(), scores, fp)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
        "FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    assert row == (143, 4422, 1024, 256)


def test_persist_handles_missing_token_fields(tmp_path, monkeypatch):
    """When the envelope omits token fields, the row stores NULL — not 0."""
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)

    envelope = json.loads(_envelope(str(transcript), exit_status="success"))
    # Token fields entirely absent (e.g. opencode envelope).

    fp = "i" * 64
    scores = {"composite": 0.5, "components": {}, "explanation": ""}
    trajectory_judge._persist(envelope, _vars(), scores, fp)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
        "FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    assert row == (None, None, None, None)


def test_get_assert_threads_scaled_timeout_and_limit(tmp_path, monkeypatch):
    """get_assert must derive the per-judge timeout from the real transcript
    length and pass any per-task judge_transcript_limit through to judge()."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("y" * 700_000)  # -> _judge_timeout == 1400

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HARNESS_TARGET_CLI_VER", "claude 2.1.131")
    monkeypatch.setenv("LOLA_TEST_SETS_DIR", str(REPO / "examples" / "default" / ".lola-eval" / "test_sets"))

    captured = {}

    def fake_judge(
        *,
        rubric_text,
        transcript,
        diff,
        judge_model,
        judge_cli,
        timeout_s=None,
        transcript_limit=None,
    ):
        captured["timeout_s"] = timeout_s
        captured["transcript_limit"] = transcript_limit
        return {
            "components": {"correctness": 1.0, "trajectory": 1.0, "tools": 1.0},
            "explanation": "ok",
        }

    monkeypatch.setattr(trajectory_judge, "judge", fake_judge)

    v = _vars()
    v["judge_transcript_limit"] = "120000"
    trajectory_judge.get_assert(
        output=_envelope(str(transcript)),
        context={"vars": v},
    )
    assert captured["timeout_s"] >= 1400, captured
    assert captured["transcript_limit"] == 120000, captured


def test_persist_handles_missing_telemetry_fields(tmp_path, monkeypatch):
    """If envelope omits turns/tool_calls/diff, persist gracefully (NULL/0/0)."""
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)

    envelope = json.loads(_envelope(str(transcript), exit_status="success"))
    envelope.pop("turns", None)
    envelope.pop("tool_calls", None)
    envelope.pop("diff", None)

    fp = "g" * 64
    scores = {"composite": 0.5, "components": {}, "explanation": ""}
    trajectory_judge._persist(envelope, _vars(), scores, fp)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT turns, tool_calls_count, diff_bytes FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    # turns -> None; tool_calls_count -> 0 (missing list treated as empty); diff_bytes -> 0
    assert row == (None, 0, 0)


def test_persist_writes_provenance_and_subject_version(tmp_path, monkeypatch):
    """_persist must read git provenance from LOLA_GIT_* env, subject_version
    from vars, and stamp the current fingerprint_version."""
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")
    monkeypatch.setenv("LOLA_GIT_SHA", "abc1234")
    monkeypatch.setenv("LOLA_GIT_BRANCH", "main")
    monkeypatch.setenv("LOLA_GIT_REMOTE", "git@example.com:me/repo.git")

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)
    envelope = json.loads(_envelope(str(transcript), exit_status="success"))

    v = _vars()
    v["subject_version"] = "mymod@9.9.9"

    fp = "p" * 64
    scores = {"composite": 0.8, "components": {"correctness": 0.8}, "explanation": "prov"}
    trajectory_judge._persist(envelope, v, scores, fp)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT git_sha, git_branch, git_remote, subject_version, fingerprint_version "
        "FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    assert row["git_sha"] == "abc1234"
    assert row["git_branch"] == "main"
    assert row["git_remote"] == "git@example.com:me/repo.git"
    assert row["subject_version"] == "mymod@9.9.9"
    assert row["fingerprint_version"] == "2"


def test_get_assert_includes_subject_version_in_fingerprint(tmp_path, monkeypatch):
    """Two rows that differ only by subject_version must get different
    fingerprints (the #5 guarantee), observed end-to-end through get_assert."""
    import sqlite3

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HARNESS_TARGET_CLI_VER", "claude 2.1.131")
    monkeypatch.setenv("LOLA_TEST_SETS_DIR", str(REPO / "examples" / "default" / ".lola-eval" / "test_sets"))

    fake = {
        "components": {"correctness": 1.0, "trajectory": 1.0, "tools": 1.0},
        "explanation": "ok",
    }

    def run_once(subject_version, run_id):
        transcript = tmp_path / f"{run_id}.jsonl"
        _write_transcript(transcript)
        env = json.loads(_envelope(str(transcript)))
        env["run_id"] = run_id
        v = _vars()
        v["subject_version"] = subject_version
        with patch.object(trajectory_judge, "judge", return_value=fake):
            trajectory_judge.get_assert(output=json.dumps(env), context={"vars": v})

    run_once("v1", "01ARZ3NDEKTSV4RRFFQ69G5FA1")
    run_once("v2", "01ARZ3NDEKTSV4RRFFQ69G5FA2")

    db = tmp_path / "state" / "lola-eval" / "runs.db"
    conn = sqlite3.connect(db)
    fps = [r[0] for r in conn.execute("SELECT fingerprint FROM runs ORDER BY subject_version")]
    conn.close()
    assert len(fps) == 2
    assert fps[0] != fps[1], "subject_version must partition the fingerprint"


def test_extract_resolved_model_from_transcript():
    text = (
        '{"type":"system","subtype":"init","model":"claude-sonnet-4-6-xyz"}\n'
        '{"type":"result","subtype":"success"}\n'
    )
    assert trajectory_judge._extract_resolved_model(text) == "claude-sonnet-4-6-xyz"
    assert trajectory_judge._extract_resolved_model("no json here") is None


def test_persist_records_resolved_models(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)
    envelope = json.loads(_envelope(str(transcript), exit_status="success"))

    v = _vars()
    v["target_model"] = "sonnet"  # alias target
    v["judge_model"] = "claude-sonnet-4-6"  # pinned judge

    fp = "q" * 64
    scores = {"composite": 0.8, "components": {"correctness": 0.8}, "explanation": "rm"}
    # Pass the resolved target model as get_assert would (extracted from transcript).
    trajectory_judge._persist(
        envelope, v, scores, fp, target_model_resolved="claude-sonnet-4-6-real"
    )

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT target_model_resolved, judge_model_resolved FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    assert row["target_model_resolved"] == "claude-sonnet-4-6-real"  # from extraction
    assert row["judge_model_resolved"] == "claude-sonnet-4-6"  # pinned -> itself


def test_persist_resolved_model_falls_back_to_pinned_target(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)
    envelope = json.loads(_envelope(str(transcript), exit_status="success"))

    v = _vars()
    v["target_model"] = "claude-sonnet-4-6"  # pinned, no transcript extraction passed
    fp = "r" * 64
    scores = {"composite": 0.5, "components": {}, "explanation": ""}
    trajectory_judge._persist(envelope, v, scores, fp)  # no target_model_resolved kwarg

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT target_model_resolved FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    assert row["target_model_resolved"] == "claude-sonnet-4-6"  # pinned fallback


def test_persist_writes_history_enrichment_fields(tmp_path, monkeypatch):
    """_persist must read the extended git provenance from LOLA_GIT_* env,
    and task_description / rubric_pass_threshold from vars."""
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")
    monkeypatch.setenv("LOLA_GIT_AUTHOR", "Test Author")
    monkeypatch.setenv("LOLA_GIT_DATE", "2026-07-02T00:00:00-04:00")
    monkeypatch.setenv("LOLA_GIT_COMMIT_MSG", "fix: the thing")
    monkeypatch.setenv("LOLA_GIT_DIRTY", "1")

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)
    envelope = json.loads(_envelope(str(transcript), exit_status="success"))

    v = _vars()
    v["task_description"] = "Go server with four flaws."
    v["rubric_pass_threshold"] = 0.7

    fp = "q" * 64
    scores = {"composite": 0.8, "components": {}, "explanation": "x"}
    trajectory_judge._persist(envelope, v, scores, fp)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT git_author, git_date, git_commit_msg, git_dirty, "
        "task_description, rubric_pass_threshold FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    assert row["git_author"] == "Test Author"
    assert row["git_date"] == "2026-07-02T00:00:00-04:00"
    assert row["git_commit_msg"] == "fix: the thing"
    assert row["git_dirty"] == 1
    assert row["task_description"] == "Go server with four flaws."
    assert row["rubric_pass_threshold"] == 0.7


def test_persist_enrichment_fields_null_when_absent(tmp_path, monkeypatch):
    """No LOLA_GIT_* env and no vars -> NULLs, not zeros or empty strings."""
    import sqlite3

    db = tmp_path / "runs.db"
    monkeypatch.setattr(trajectory_judge.xdg, "db_path", lambda: db)
    monkeypatch.setattr(trajectory_judge, "_target_cli_version", lambda *a, **kw: "test-1.0.0")
    for var in ("LOLA_GIT_AUTHOR", "LOLA_GIT_DATE", "LOLA_GIT_COMMIT_MSG", "LOLA_GIT_DIRTY"):
        monkeypatch.delenv(var, raising=False)

    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript)
    envelope = json.loads(_envelope(str(transcript), exit_status="success"))

    # The runner always sets task_description, defaulting to "" — the
    # `or None` in _persist must collapse that to NULL, not store "".
    v = _vars()
    v["task_description"] = ""

    fp = "r" * 64
    trajectory_judge._persist(envelope, v, {"composite": 0.8}, fp)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT git_author, git_dirty, task_description, rubric_pass_threshold "
        "FROM runs WHERE fingerprint=?",
        (fp,),
    ).fetchone()
    conn.close()
    assert row["git_author"] is None
    assert row["git_dirty"] is None
    assert row["task_description"] is None
    assert row["rubric_pass_threshold"] is None

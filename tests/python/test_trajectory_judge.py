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
    return json.dumps({
        "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "transcript_path": transcript_path,
        "turns": 1,
        "tool_calls": [],
        "exit_status": exit_status,
        "duration_s": 1.2,
        "diff": "diff --git a b\n",
        "cost_usd": 0.01,
    })


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

"""Unit tests for the multi-turn dialog orchestrator.

Uses small shell-script "stub CLIs" that pretend to be claude / opencode
so we can validate the orchestration logic without standing up real
agent processes.
"""
from __future__ import annotations

import json
import stat
import subprocess
import sys
import textwrap
from pathlib import Path


from lola_eval._data.interactive.orchestrator import (
    DialogResult,
    Turn,
    parse_persona_file,
    run_dialog,
    write_transcript,
)


def _make_stub(tmp_path: Path, name: str, body: str) -> Path:
    """Write an executable shell script and return its path."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(body).lstrip())
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def test_dialog_completes_via_stop_phrase(tmp_path):
    """Simulated user emits DONE after one round-trip; dialog ends cleanly."""
    sim = _make_stub(tmp_path, "sim.sh", """
        #!/bin/sh
        # Read prompt from stdin (we don't need it). On first call return
        # a starter question; on subsequent calls, return DONE.
        cat > /dev/null
        if [ ! -f "$0.called" ]; then
            touch "$0.called"
            echo "Please fix the failing test in src/calc/core.py"
        else
            echo "OK that looks good. DONE"
        fi
    """)
    agent = _make_stub(tmp_path, "agent.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "I edited core.py and the tests pass now."
    """)
    res = run_dialog(
        target_command=[str(agent)],
        simulated_user_command=[str(sim)],
        persona_body="You are a senior engineer.",
        initial_prompt="Fix the bug.",
        max_turns=5,
        stop_phrase="DONE",
        per_turn_timeout_s=10,
    )
    assert res.stop_reason == "stop_phrase"
    assert len(res.turns) == 3, f"expected user/agent/user, got {[t.role for t in res.turns]}"
    assert res.turns[0].role == "user"
    assert res.turns[1].role == "assistant"
    assert res.turns[2].role == "user"
    assert "DONE" in res.turns[2].content


def test_dialog_hits_max_turns(tmp_path):
    """Neither side ever says DONE; orchestrator stops at max_turns."""
    sim = _make_stub(tmp_path, "sim.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "keep going"
    """)
    agent = _make_stub(tmp_path, "agent.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "ok"
    """)
    res = run_dialog(
        target_command=[str(agent)],
        simulated_user_command=[str(sim)],
        persona_body="",
        initial_prompt="x",
        max_turns=3,
        stop_phrase="DONE",
        per_turn_timeout_s=10,
    )
    assert res.stop_reason == "max_turns"
    # 3 user turns + 3 assistant turns = 6 total.
    assert res.turn_count == 3
    assert len(res.turns) == 6


def test_dialog_handles_target_subprocess_error(tmp_path):
    """Target agent exits non-zero -> dialog ends with subprocess_error."""
    sim = _make_stub(tmp_path, "sim.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "do the thing"
    """)
    agent = _make_stub(tmp_path, "agent.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "boom" >&2
        exit 7
    """)
    res = run_dialog(
        target_command=[str(agent)],
        simulated_user_command=[str(sim)],
        persona_body="",
        initial_prompt="x",
        max_turns=3,
        stop_phrase="DONE",
        per_turn_timeout_s=10,
    )
    assert res.stop_reason == "subprocess_error"
    assert "target-agent exit 7" in res.error_message
    # The simulated user's first message is in the transcript even though
    # the agent failed afterward.
    assert len(res.turns) == 1
    assert res.turns[0].role == "user"


def test_dialog_handles_simulated_user_subprocess_error(tmp_path):
    """Simulated user exits non-zero on first turn -> subprocess_error
    with no turns recorded."""
    sim = _make_stub(tmp_path, "sim.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "user crashed" >&2
        exit 5
    """)
    agent = _make_stub(tmp_path, "agent.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "doesn't matter"
    """)
    res = run_dialog(
        target_command=[str(agent)],
        simulated_user_command=[str(sim)],
        persona_body="",
        initial_prompt="x",
        max_turns=3,
        stop_phrase="DONE",
        per_turn_timeout_s=10,
    )
    assert res.stop_reason == "subprocess_error"
    assert "simulated-user exit 5" in res.error_message
    assert len(res.turns) == 0


def test_dialog_per_turn_timeout(tmp_path):
    """Subprocess that never returns -> subprocess_timeout."""
    sim = _make_stub(tmp_path, "sim.sh", """
        #!/bin/sh
        cat > /dev/null
        sleep 30
    """)
    agent = _make_stub(tmp_path, "agent.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "ok"
    """)
    res = run_dialog(
        target_command=[str(agent)],
        simulated_user_command=[str(sim)],
        persona_body="",
        initial_prompt="x",
        max_turns=3,
        stop_phrase="DONE",
        per_turn_timeout_s=1,
    )
    assert res.stop_reason == "subprocess_timeout"
    assert "per-turn timeout" in res.error_message


def test_persona_file_with_frontmatter(tmp_path):
    p = tmp_path / "simulated_user.md"
    p.write_text(textwrap.dedent("""\
        ---
        persona_version: 2
        max_turns: 7
        stop_phrase: SHIP_IT
        ---
        You are a terse senior engineer.
    """))
    body, fm = parse_persona_file(p)
    assert "terse senior engineer" in body
    assert fm["persona_version"] == 2
    assert fm["max_turns"] == 7
    assert fm["stop_phrase"] == "SHIP_IT"


def test_persona_file_without_frontmatter(tmp_path):
    """A persona file with no frontmatter is allowed; defaults apply."""
    p = tmp_path / "simulated_user.md"
    p.write_text("Just a persona body, no frontmatter.")
    body, fm = parse_persona_file(p)
    assert body == "Just a persona body, no frontmatter."
    assert fm == {}


def test_write_transcript_jsonl_shape(tmp_path):
    res = DialogResult(
        turns=[
            Turn(role="user", content="hello", duration_s=0.1),
            Turn(role="assistant", content="hi back", duration_s=0.2),
            Turn(role="user", content="DONE", duration_s=0.05),
        ],
        stop_reason="stop_phrase",
    )
    out = tmp_path / "transcript.jsonl"
    write_transcript(res, out)
    lines = out.read_text().splitlines()
    assert len(lines) == 4  # 3 turns + 1 dialog_end
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["type"] == "user_turn"
    assert parsed[0]["text"] == "hello"
    assert parsed[1]["type"] == "agent_turn"
    assert parsed[3]["type"] == "dialog_end"
    assert parsed[3]["stop_reason"] == "stop_phrase"
    assert parsed[3]["turn_count"] == 2  # two user turns


def test_main_cli_entrypoint_writes_envelope_and_transcript(tmp_path):
    """The orchestrator's __main__ entry point is the JS provider's contract.
    It must read all inputs from CLI args, write the transcript to disk,
    and print the envelope JSON to stdout."""
    sim = _make_stub(tmp_path, "sim.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "Please review my code. DONE"
    """)
    agent = _make_stub(tmp_path, "agent.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "ok looks good"
    """)
    persona = tmp_path / "sim.md"
    persona.write_text("---\nstop_phrase: DONE\n---\nYou are a tester.\n")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Review the diff.")
    transcript = tmp_path / "out" / "transcript.jsonl"

    proc = subprocess.run(
        [
            sys.executable,
            "-m", "lola_eval._data.interactive.orchestrator",
            "--target-command", json.dumps([str(agent)]),
            "--simulated-user-command", json.dumps([str(sim)]),
            "--persona-file", str(persona),
            "--prompt-file", str(prompt),
            "--max-turns", "3",
            "--stop-phrase", "STOP_DEFAULT",  # frontmatter overrides this
            "--per-turn-timeout-s", "10",
            "--transcript-path", str(transcript),
        ],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    env = json.loads(proc.stdout)
    assert env["exit_status"] == "success"
    assert env["turns"] == 1, "one user turn before DONE"
    assert env["transcript_path"] == str(transcript)
    assert transcript.exists()


def test_stop_phrase_matched_as_whole_word(tmp_path):
    """Stop phrase 'DONE' must not match 'DONE' inside the word 'undone'.

    This is important: an agent saying 'I left the work undone' should
    not be misread as the simulated user signaling completion. We use
    word-boundary regex; the stop-phrase check is on the simulated user's
    output, not the agent's, but the same word-boundary discipline applies.
    """
    sim = _make_stub(tmp_path, "sim.sh", """
        #!/bin/sh
        cat > /dev/null
        if [ ! -f "$0.called" ]; then
            touch "$0.called"
            echo "the work is undone, please finish"
        else
            echo "great. DONE"
        fi
    """)
    agent = _make_stub(tmp_path, "agent.sh", """
        #!/bin/sh
        cat > /dev/null
        echo "I will continue."
    """)
    res = run_dialog(
        target_command=[str(agent)],
        simulated_user_command=[str(sim)],
        persona_body="",
        initial_prompt="x",
        max_turns=5,
        stop_phrase="DONE",
        per_turn_timeout_s=10,
    )
    # First user turn says "undone" but should NOT trigger stop. Second
    # user turn says "DONE" as a whole word and ends the dialog.
    assert res.stop_reason == "stop_phrase"
    assert len(res.turns) == 3  # user, agent, user(DONE)
    assert "undone" in res.turns[0].content

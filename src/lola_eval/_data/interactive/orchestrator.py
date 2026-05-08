"""Multi-turn dialog orchestrator for exec_mode=interactive.

Phase-2 of the harness: instead of running the target agent once and
grading the result (autonomous), simulate a multi-turn conversation
between the agent and a "simulated user" (a separate CLI playing the
human role).

Design: subprocess-per-turn. Each turn re-invokes the CLI with the full
conversation history as a flat-text prompt. This is dramatically simpler
than maintaining long-lived stream-JSON pipes and matches how `claude
--print` is designed to be used. The cost is duplicated context tokens,
which is acceptable for the typical 3-10 turn tasks the harness targets.

This module is invoked by the JS interactive providers (which know the
real CLI flags) and is also exercised directly by unit tests using stub
commands. See ``tests/python/test_interactive_orchestrator.py``.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Turn:
    role: str       # "user" | "assistant"
    content: str
    duration_s: float


@dataclass
class DialogResult:
    turns: list[Turn] = field(default_factory=list)
    stop_reason: str = ""    # "stop_phrase" | "max_turns" | "subprocess_error" | "subprocess_timeout"
    error_message: str = ""

    @property
    def turn_count(self) -> int:
        # One full turn = user + assistant. We count user-issued turns
        # since the simulated user always speaks first.
        return sum(1 for t in self.turns if t.role == "user")


def _flatten_history(persona_body: str, turns: list[Turn], who_is_speaking: str) -> str:
    """Build a single-string prompt from persona + history.

    ``who_is_speaking`` is "user" or "assistant" — describes which side
    is being asked to produce the next message. Used to frame the prompt
    appropriately so the receiving CLI knows what role to play.
    """
    lines: list[str] = []
    if who_is_speaking == "user":
        lines.append("# Persona")
        lines.append(persona_body.strip())
        lines.append("")
        lines.append("# Conversation so far")
    else:
        lines.append("# Conversation so far")
    if not turns:
        lines.append("(no messages yet)")
    else:
        for t in turns:
            tag = "User" if t.role == "user" else "Assistant"
            lines.append(f"## {tag}")
            lines.append(t.content.strip())
            lines.append("")
    if who_is_speaking == "user":
        lines.append(
            "# Your next message"
        )
        lines.append(
            "Reply as the user described in the persona. Output only your "
            "next message — no meta-commentary, no role labels."
        )
    else:
        lines.append("# Your next response")
        lines.append(
            "Reply as the assistant. Output only your next message — no "
            "meta-commentary, no role labels."
        )
    return "\n".join(lines)


def _run_subprocess_turn(
    command: list[str],
    prompt: str,
    timeout_s: float,
    cwd: Path | None = None,
) -> tuple[str, float]:
    """Run a single subprocess turn. Returns (stdout, duration_s).

    ``prompt`` is sent on stdin. We use stdin (not argv) so the prompt
    can contain multi-paragraph history without OS argv-length limits.
    Raises subprocess.TimeoutExpired or subprocess.CalledProcessError on
    failure; orchestrator handles both.
    """
    started = time.monotonic()
    res = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        cwd=str(cwd) if cwd else None,
        check=False,
    )
    duration = time.monotonic() - started
    if res.returncode != 0:
        raise subprocess.CalledProcessError(
            res.returncode, command, output=res.stdout, stderr=res.stderr,
        )
    return res.stdout.strip(), duration


def run_dialog(
    *,
    target_command: list[str],
    simulated_user_command: list[str],
    persona_body: str,
    initial_prompt: str,
    max_turns: int,
    stop_phrase: str = "DONE",
    per_turn_timeout_s: float = 300.0,
    cwd: Path | None = None,
) -> DialogResult:
    """Run the dialog and return the result.

    The simulated user always speaks first. The initial_prompt is the
    case's prompt.md content — the simulated user reads this as their
    starting context (the task they're asking the agent to do).

    Stop conditions:
      * The simulated user emits ``stop_phrase`` (case-insensitive, as
        a whole word) anywhere in their message.
      * ``max_turns`` user-issued turns have completed.
      * Either subprocess exits non-zero or hits ``per_turn_timeout_s``.
    """
    if max_turns < 1:
        raise ValueError(f"max_turns must be >= 1, got {max_turns}")

    result = DialogResult()
    # Seed: the simulated user's first message is *generated* from the
    # persona + the case prompt. Subsequent user messages incorporate the
    # whole agent conversation history.
    seeded_persona = (
        f"{persona_body.strip()}\n\n"
        f"# Task you're asking the agent to complete\n"
        f"{initial_prompt.strip()}"
    )

    stop_re = re.compile(rf"\b{re.escape(stop_phrase)}\b", flags=re.IGNORECASE)

    for turn_index in range(max_turns):
        # Simulated user's turn. They see the entire prior conversation
        # (assistant turns only — they don't echo their own prior messages
        # back in; the flatten function handles formatting).
        user_prompt = _flatten_history(
            persona_body=seeded_persona,
            turns=result.turns,
            who_is_speaking="user",
        )
        try:
            user_msg, user_dur = _run_subprocess_turn(
                simulated_user_command,
                user_prompt,
                timeout_s=per_turn_timeout_s,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            result.stop_reason = "subprocess_timeout"
            result.error_message = (
                f"simulated-user subprocess hit per-turn timeout "
                f"({per_turn_timeout_s}s) on turn {turn_index + 1}"
            )
            return result
        except subprocess.CalledProcessError as e:
            result.stop_reason = "subprocess_error"
            result.error_message = (
                f"simulated-user exit {e.returncode} on turn {turn_index + 1}: "
                f"{(e.stderr or '').strip()[:500]}"
            )
            return result

        result.turns.append(Turn(role="user", content=user_msg, duration_s=user_dur))

        if stop_re.search(user_msg):
            result.stop_reason = "stop_phrase"
            return result

        # Target agent's turn. They see the full prior conversation
        # (which now includes the simulated user's just-issued message).
        agent_prompt = _flatten_history(
            persona_body=persona_body,  # agents don't get the persona
            turns=result.turns,
            who_is_speaking="assistant",
        )
        try:
            agent_msg, agent_dur = _run_subprocess_turn(
                target_command,
                agent_prompt,
                timeout_s=per_turn_timeout_s,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            result.stop_reason = "subprocess_timeout"
            result.error_message = (
                f"target-agent subprocess hit per-turn timeout "
                f"({per_turn_timeout_s}s) on turn {turn_index + 1}"
            )
            return result
        except subprocess.CalledProcessError as e:
            result.stop_reason = "subprocess_error"
            result.error_message = (
                f"target-agent exit {e.returncode} on turn {turn_index + 1}: "
                f"{(e.stderr or '').strip()[:500]}"
            )
            return result

        result.turns.append(Turn(role="assistant", content=agent_msg, duration_s=agent_dur))

    result.stop_reason = "max_turns"
    return result


def parse_persona_file(path: Path) -> tuple[str, dict]:
    """Parse simulated_user.md → (body_text, frontmatter_dict).

    Frontmatter keys (all optional):
      persona_version: int
      max_turns: int          (overrides per-target max_turns)
      stop_phrase: str        (default "DONE")
    """
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        # No frontmatter is allowed — treat entire file as persona body.
        return text.strip(), {}
    import yaml
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).strip()
    return body, fm


def write_transcript(
    result: DialogResult,
    transcript_path: Path,
) -> None:
    """Write the dialog transcript as JSONL.

    One JSON object per turn-boundary. Schema:
      {"type": "user_turn"|"agent_turn", "text": str, "duration_s": float}

    Plus a final dict capturing stop_reason and total turn count, so the
    judge can quickly read meta without re-parsing every line.
    """
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("w") as f:
        for t in result.turns:
            event_type = "user_turn" if t.role == "user" else "agent_turn"
            f.write(json.dumps({
                "type": event_type,
                "text": t.content,
                "duration_s": t.duration_s,
            }) + "\n")
        f.write(json.dumps({
            "type": "dialog_end",
            "stop_reason": result.stop_reason,
            "turn_count": result.turn_count,
            "error_message": result.error_message,
        }) + "\n")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint used by the JS interactive providers.

    Reads dialog config from argv, runs the dialog, writes the transcript,
    and prints the envelope JSON to stdout. The JS provider passes the
    envelope through to promptfoo as the row's output.
    """
    p = argparse.ArgumentParser(
        prog="lola-eval-interactive-orchestrator",
        description="Drive a multi-turn dialog between a target agent and a simulated user.",
    )
    p.add_argument("--target-command", required=True,
                   help="JSON array: argv to invoke the target agent.")
    p.add_argument("--simulated-user-command", required=True,
                   help="JSON array: argv to invoke the simulated user.")
    p.add_argument("--persona-file", required=True, type=Path,
                   help="Path to simulated_user.md.")
    p.add_argument("--prompt-file", required=True, type=Path,
                   help="Path to prompt.md (the task description).")
    p.add_argument("--max-turns", type=int, required=True)
    p.add_argument("--stop-phrase", default="DONE")
    p.add_argument("--per-turn-timeout-s", type=float, default=300.0)
    p.add_argument("--workdir", type=Path, default=None,
                   help="Working directory for both subprocesses (target's git tree).")
    p.add_argument("--transcript-path", required=True, type=Path)
    p.add_argument("--run-id", default=None,
                   help="UUIDv7 for this row. Generated if omitted.")
    args = p.parse_args(argv)

    target_cmd = json.loads(args.target_command)
    sim_cmd = json.loads(args.simulated_user_command)
    persona_body, fm = parse_persona_file(args.persona_file)
    initial_prompt = args.prompt_file.read_text()

    # Frontmatter overrides argparse where present (the persona file is
    # closer to the user's intent than the matrix-level default).
    max_turns = int(fm.get("max_turns") or args.max_turns)
    stop_phrase = str(fm.get("stop_phrase") or args.stop_phrase)

    started = time.monotonic()
    result = run_dialog(
        target_command=target_cmd,
        simulated_user_command=sim_cmd,
        persona_body=persona_body,
        initial_prompt=initial_prompt,
        max_turns=max_turns,
        stop_phrase=stop_phrase,
        per_turn_timeout_s=args.per_turn_timeout_s,
        cwd=args.workdir,
    )
    total_duration = time.monotonic() - started

    write_transcript(result, args.transcript_path)

    # Map dialog stop_reason to envelope exit_status. The trajectory judge
    # already understands target_timeout and target_error.
    if result.stop_reason == "subprocess_timeout":
        exit_status = "target_timeout"
    elif result.stop_reason == "subprocess_error":
        exit_status = "target_error"
    else:
        exit_status = "success"

    # Compute git diff if a workdir was provided. Errors here are
    # non-fatal — the judge can still grade based on the transcript.
    diff_text = ""
    if args.workdir and (args.workdir / ".git").exists():
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "--no-color", "HEAD"],
                cwd=str(args.workdir), capture_output=True, text=True, timeout=30,
            )
            diff_text = diff_proc.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            diff_text = ""

    envelope = {
        "run_id": args.run_id or str(uuid.uuid4()),
        "transcript_path": str(args.transcript_path),
        "turns": result.turn_count,
        "tool_calls": [],
        "exit_status": exit_status,
        "duration_s": total_duration,
        "diff": diff_text,
        "error_message": result.error_message or None,
    }
    sys.stdout.write(json.dumps(envelope))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

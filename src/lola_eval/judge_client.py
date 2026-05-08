"""Universal judge client.

Wraps a single model call returning strict JSON. Two backends supported:

  - `opencode` (the original "universal client" — provider-agnostic via opencode auth)
  - `claude-code` (calls `claude -p` with tools disabled — useful when only one CLI
    is reachable, e.g., subscription-auth claude with no opencode model configured)

Adding a third backend is a single function plus a dispatch arm.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

DEFAULT_TIMEOUT_S = 120


class JudgeError(RuntimeError):
    pass


def _build_prompt(rubric_text: str, transcript: str, diff: str) -> str:
    return (
        "You are a code-trajectory judge. Read the rubric below, then the "
        "transcript and the final diff. Return STRICT JSON matching the "
        "schema in the rubric.\n\n"
        "===== RUBRIC =====\n"
        f"{rubric_text}\n\n"
        "===== TRANSCRIPT =====\n"
        f"{transcript[:50_000]}\n\n"
        "===== FINAL DIFF =====\n"
        f"{diff[:20_000]}\n\n"
        "Now respond with JSON only. No prose."
    )


def _judge_via_opencode(prompt: str, judge_model: str, timeout_s: int) -> str:
    try:
        proc = subprocess.run(
            ["opencode", "run", "--agent", "judge", "--format", "json",
             "-m", judge_model, prompt],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise JudgeError(f"judge timeout after {timeout_s}s") from e
    if proc.returncode != 0:
        raise JudgeError(f"opencode exit {proc.returncode}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _judge_via_claude(prompt: str, judge_model: str, timeout_s: int,
                      max_budget_usd: float = 2.00) -> str:
    # `--tools ""` disables every tool so the judge can only emit text.
    # Without this, a sufficiently helpful claude could try to "fix" the
    # bug it's supposed to grade by spawning Bash/Edit tool calls.
    #
    # Default budget is $2.00 — judging requires reading the full transcript
    # (~50KB) plus rubric plus diff plus the judge's own reasoning output.
    # $0.10 was way too tight; $1 was just enough; $2 gives headroom for
    # larger transcripts on harder tasks.
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt,
             "--model", judge_model,
             "--tools", "",
             "--output-format", "text",
             "--max-budget-usd", str(max_budget_usd),
             "--permission-mode", "default"],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise JudgeError(f"judge timeout after {timeout_s}s") from e
    # Claude reports certain errors (e.g. "Exceeded USD budget") on stdout
    # while still exiting non-zero. Surface both streams in diagnostics.
    if proc.returncode != 0:
        diag = (proc.stderr.strip() or proc.stdout.strip())[:300]
        raise JudgeError(f"claude exit {proc.returncode}: {diag}")
    # Claude can also signal a budget exceedance on stdout with exit 0
    # (yes, really — see Test 1 in the diagnostic exploration).
    if proc.stdout.startswith("Error:"):
        raise JudgeError(f"claude reported error on stdout: {proc.stdout.strip()[:300]}")
    return proc.stdout


def judge(
    *,
    rubric_text: str,
    transcript: str,
    diff: str,
    judge_model: str,
    judge_cli: str = "opencode",
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    prompt = _build_prompt(rubric_text, transcript, diff)
    if judge_cli == "opencode":
        out = _judge_via_opencode(prompt, judge_model, timeout_s)
    elif judge_cli == "claude-code":
        out = _judge_via_claude(prompt, judge_model, timeout_s)
    else:
        raise JudgeError(f"unsupported judge_cli={judge_cli}")

    parsed = _extract_json(out.strip())
    if parsed is None:
        raise JudgeError(f"could not parse JSON from judge output: {out[:200]}")
    return parsed


def _extract_json(text: str) -> dict | None:
    """Find a JSON object in `text` by trying three strategies in order.

    1. Whole-string parse — covers the bare-JSON judge output and the
       fake-CLI test path.
    2. Single-line scan — pick the *last* line that starts with '{' and
       parses on its own. Cheap; covers the common case where the judge
       emits a single-line JSON object after a preamble. Does NOT handle
       multi-line / pretty-printed JSON; that case falls through to (3).
    3. Balanced-brace search — walk character-by-character matching '{'
       to '}', returning the first balanced span that parses. Handles
       fenced code blocks and pretty-printed JSON.

    Returns None when none of the three find a parseable object.
    """
    # 1. Whole-string parse.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. Single-line scan.
    last = None
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    if last is not None:
        return last
    # 3. Balanced-brace search.
    return _find_first_json_object(text)


def _find_first_json_object(text: str) -> dict | None:
    """Find the first balanced {...} substring and parse it as JSON."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = -1  # reset and look for the next one
    return None

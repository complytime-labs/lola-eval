---
rubric_version: "1"
pass_threshold: 0.6
weights:
  correctness: 0.5
  trajectory: 0.3
  tools: 0.2
---

# Rubric: case-001-fix-bug

Score the trajectory in three components, each in [0.0, 1.0]:

## correctness (weight 0.5)

Did the agent's edits make `pytest` green?

- 1.0 — final state of `src/calc/core.py` produces `pytest -q` exit 0.
- 0.5 — partial fix: some tests pass that didn't before, but at least one is still failing.
- 0.0 — no relevant edit, or final pytest still fails the same way.

You will be given the final `git diff` and the final `pytest` exit status.

## trajectory (weight 0.3)

Did the agent reach the fix efficiently?

- 1.0 — straight-line: read the failing test, read the source, made the edit, ran pytest, exited.
- 0.5 — some wasted motion (re-reading files, running pytest more than 3 times, exploring unrelated files), but still arrived at the fix.
- 0.0 — got stuck in a loop, made off-task edits, or spent more than 10 turns without progress.

Penalize: ignored MCP/tool affordances offered by the lola pack (when one is installed),
hallucinated file paths, fabricated commands.

## tools (weight 0.2)

Did the agent use tools accurately?

- 1.0 — every tool call had correct arguments, no failed reads, edits applied to the right file.
- 0.5 — one or two tool failures recovered from.
- 0.0 — three or more failed tool calls, or repeated arg errors on the same tool.

## output

Return strict JSON:

```
{
  "components": {
    "correctness": <float>,
    "trajectory": <float>,
    "tools": <float>
  },
  "explanation": "<one-paragraph rationale>"
}
```

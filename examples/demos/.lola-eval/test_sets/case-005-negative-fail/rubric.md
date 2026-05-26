---
rubric_version: "1"
pass_threshold: 0.6
weights:
  correctness: 0.8
  trajectory: 0.1
  tools: 0.1
---

# Rubric: case-005-negative-fail

This case is unsatisfiable on purpose. correctness is weighted high enough
(0.8) that no amount of clean trajectory/tools can push the composite above
the 0.6 pass threshold — so a compliant, cleanly-running agent still FAILS on
quality. That is the point: it must surface as a threshold/quality failure
(exit_status=success, composite < threshold), NOT as an infrastructure error.

## correctness (weight 0.8)

- 1.0 — a file `SOLUTION.md` exists at the project root whose contents are
  exactly the token `XYZZY-42`.
- 0.0 — otherwise (the prompt never reveals this token and instructs the agent
  to create no files, so this is unreachable by design).

You will be given the final `git diff` and the transcript.

## trajectory (weight 0.1)

- 1.0 — the agent read the prompt, did nothing of substance, and ended cleanly.
- 0.0 — the agent thrashed or made off-task edits.

## tools (weight 0.1)

- 1.0 — no failed tool calls.
- 0.0 — repeated tool errors.

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

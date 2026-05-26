---
rubric_version: "1"
pass_threshold: 0.6
weights:
  correctness: 0.5
  trajectory: 0.3
  tools: 0.2
---

# Rubric: case-006-profile-skill

Validates that the `withgreet` profile's `install_modules` made the `/greet`
skill discoverable. You will be given the transcript and the final diff.

## correctness (weight 0.5)

Did the agent produce `GREETING.md` containing exactly the single line
`Hello from the greeter module!` (as the greet skill instructs)?

- 1.0 — `GREETING.md` exists with exactly that line and nothing else.
- 0.5 — exists but content deviates.
- 0.0 — no `GREETING.md`, or unrelated content.

## trajectory (weight 0.3)

- 1.0 — the agent discovered and followed the `/greet` skill.
- 0.5 — produced the file without clearly using the skill.
- 0.0 — "Unknown skill" / could not find `/greet` and floundered (profile
  install_modules failed to provision the skill).

## tools (weight 0.2)

- 1.0 — every tool call correct; file written correctly.
- 0.5 — one or two recovered failures.
- 0.0 — three or more failed tool calls.

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

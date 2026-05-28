---
rubric_version: "1"
pass_threshold: 0.6
weights:
  correctness: 0.5
  trajectory: 0.3
  tools: 0.2
---

# Rubric: case-004-project-skill

This case validates that the in-repo `greet` skill was scaffolded and was
discoverable by the agent (Mode-1 auto-scaffold, #7). You will be given the
transcript and the final diff.

## correctness (weight 0.5)

Did the agent produce `GREETING.md` containing exactly the single line
`Hello from the greeter module!` (as the greet skill instructs)?

- 1.0 — `GREETING.md` exists with exactly that line and nothing else.
- 0.5 — `GREETING.md` exists but content deviates (extra text, wrong wording).
- 0.0 — no `GREETING.md`, or unrelated content.

## trajectory (weight 0.3)

Did the agent discover and use the `greet` skill rather than guessing?

- 1.0 — the agent invoked/consulted the `greet` skill and followed it directly.
- 0.5 — produced the file without clearly using the skill, but got it right.
- 0.0 — got "Unknown skill" / could not find the skill and floundered, or
  spent many turns exploring without producing the file.

Penalize heavily any sign of "Unknown skill" or inability to locate `/greet`:
that indicates provisioning failed.

## tools (weight 0.2)

Did the agent use tools accurately?

- 1.0 — every tool call had correct arguments; the file was written correctly.
- 0.5 — one or two recovered tool failures.
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

---
rubric_version: "1"
pass_threshold: 0.6
weights:
  correctness: 0.6
  trajectory: 0.4
---

# Rubric: case-greeting (skill-conflict sweep)

You are given the transcript and the final diff. The correct "standard
greeting" is a file `GREETING.md` at the repo root containing exactly the
single line `Hello from the greeter module!`.

## correctness (weight 0.6)

- 1.0 — `GREETING.md` exists with exactly that line and nothing else.
- 0.5 — a greeting file exists but the name or content deviates (e.g. the
  agent wrote `HELLO.txt`, or different text).
- 0.0 — no greeting file, or unrelated content.

## trajectory (weight 0.4)

- 1.0 — the agent followed the greet skill cleanly to the correct artifact.
- 0.5 — produced something greeting-like but wavered between conflicting
  instructions or guessed without a skill.
- 0.0 — floundered, produced the wrong artifact, or never produced a file.

## output

Return strict JSON:

```
{
  "components": {
    "correctness": <float>,
    "trajectory": <float>
  },
  "explanation": "<one-paragraph rationale>"
}
```

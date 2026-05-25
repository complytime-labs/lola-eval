---
rubric_version: "1"
pass_threshold: 0.6
weights:
  correctness: 0.5
  trajectory: 0.3
  tools: 0.2
---

# Rubric: case-003-ts-npm

Score the trajectory in three components, each in [0.0, 1.0].

You will be given the final `git diff` and the transcript. NOTE: the diff
reflects only the intentional source change — build artifacts such as
`node_modules/` are excluded by the harness and will not appear, even
though the agent ran `npm install`.

## correctness (weight 0.5)

Did the agent implement `sum(a, b)` to return `a + b`?

- 1.0 — `src/index.ts` `sum` returns `a + b` (the throw is removed).
- 0.5 — partial/incorrect implementation that still changes `sum`.
- 0.0 — `sum` unchanged or wrong (e.g. returns `a - b`).

## trajectory (weight 0.3)

Did the agent reach the result efficiently?

- 1.0 — read the source, made the edit, ran `npm install`, exited.
- 0.5 — some wasted motion but arrived at the result.
- 0.0 — got stuck, made off-task edits, or never ran `npm install`.

## tools (weight 0.2)

Did the agent use tools accurately?

- 1.0 — every tool call had correct arguments; `npm install` succeeded.
- 0.5 — one or two recovered tool failures.
- 0.0 — three or more failed tool calls, or `npm install` failed unrecovered.

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

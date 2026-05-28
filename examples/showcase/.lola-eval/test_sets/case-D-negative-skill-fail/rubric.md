---
rubric_version: "1"
pass_threshold: 0.6
weights:
  acknowledges-conflict: 0.15
  invokes-protocol: 0.25
  protocol-correct: 0.30
  concrete-next-steps: 0.20
  response-md-written: 0.10
---

# Rubric: case-D-negative-skill-fail

Score the trajectory in five components, each in [0.0, 1.0]:

## acknowledges-conflict (weight 0.15)

Did the agent's response name the conflict explicitly?

- 1.0 — RESPONSE.md contains a direct statement that two advisors are in
  conflict and names that as the problem to resolve (e.g. "two advisors
  are giving contradictory recommendations" or equivalent phrasing).
- 0.5 — acknowledges there is a problem but frames it vaguely (e.g. "you
  have conflicting advice") without tying it specifically to two loaded
  advisor skills.
- 0.0 — no acknowledgement of the conflict, or the response treats the
  situation as a normal question without noting the contradiction.

## invokes-protocol (weight 0.25)

Did the agent reference a named skill-conflict resolution protocol?

This is a skill-gated criterion. A model without the
`python-overlapping-advisor` skill loaded has no defined protocol to
reference and is unlikely to fabricate one that matches. A model with
the skill loaded should cite the protocol by name.

- 1.0 — RESPONSE.md explicitly names a conflict-resolution protocol
  (e.g. "skill-conflict resolution protocol" or a named rule such as
  "last-registered advisor wins") and attributes it to the loaded skills
  or the harness, not to generic best-practice.
- 0.5 — mentions that a protocol should exist or that the system should
  have a tiebreaker, but does not name or describe one.
- 0.0 — no mention of any protocol; response is purely generic advice
  (e.g. "review both recommendations manually").

## protocol-correct (weight 0.30)

Does the cited protocol match the one in the loaded skill?

This is the highest-weight criterion and acts as the deterministic lift
signal. The `python-overlapping-advisor` skill specifies: when two
Python advisor skills overlap on the same file, the skill registered
later takes precedence and the model must surface both recommendations
to the user with an explicit conflict notice before applying either.

- 1.0 — RESPONSE.md states (or paraphrases) both of the following:
  (a) the later-registered advisor takes precedence, and
  (b) both recommendations must be surfaced to the user with an explicit
      conflict notice before any action is taken.
- 0.5 — states one of the two required elements correctly but omits or
  misrepresents the other.
- 0.0 — protocol description absent, contradicts the skill's rule (e.g.
  claims earlier-registered wins, or says the model picks silently), or
  the model confabulates a different mechanism.

## concrete-next-steps (weight 0.20)

Did the agent provide actionable advice for the user?

- 1.0 — RESPONSE.md includes at least two concrete steps the user can
  take (e.g. review the surfaced conflict notice, decide which advisor's
  recommendation to accept, or adjust skill registration order).
- 0.5 — one concrete step or vague guidance ("consult documentation").
- 0.0 — no actionable advice; purely explanatory text with no steps.

## response-md-written (weight 0.10)

Is RESPONSE.md present in the working directory?

- 1.0 — RESPONSE.md exists and is non-empty.
- 0.0 — RESPONSE.md absent or empty.

## output

Return strict JSON:

```
{
  "components": {
    "acknowledges-conflict": <float>,
    "invokes-protocol": <float>,
    "protocol-correct": <float>,
    "concrete-next-steps": <float>,
    "response-md-written": <float>
  },
  "explanation": "<one-paragraph rationale>"
}
```

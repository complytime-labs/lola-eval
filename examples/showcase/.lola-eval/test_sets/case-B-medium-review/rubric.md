---
rubric_version: "1"
pass_threshold: 0.6
weights:
  finds-sqli: 0.08
  finds-validation: 0.08
  finds-race: 0.08
  fixes-sqli: 0.18
  fixes-validation: 0.18
  fixes-race: 0.18
  review-md-written: 0.12
  tests-pass: 0.10
---

# Rubric: case-B-medium-review

Score the trajectory in eight components, each in [0.0, 1.0]:

## finds-sqli (weight 0.08)

Did the agent identify the SQL injection in `lookup()`?

- 1.0 — REVIEW.md explicitly names SQL injection in `lookup()`, cites the f-string interpolation of `name`, and identifies the affected line(s).
- 0.5 — mentions a security issue in `lookup()` but does not name SQL injection or misidentifies the mechanism.
- 0.0 — no mention of the injection vulnerability.

## finds-validation (weight 0.08)

Did the agent identify the missing input validation in `add_user()`?

- 1.0 — REVIEW.md explicitly notes that `add_user()` accepts any type/length without checking, and identifies the affected line(s).
- 0.5 — mentions a validation concern in `add_user()` but is vague or incomplete.
- 0.0 — no mention of the missing validation.

## finds-race (weight 0.08)

Did the agent identify the race condition in `update_email()`?

- 1.0 — REVIEW.md explicitly names the read-modify-write race condition, explains that two concurrent callers can interleave, and identifies the affected lines.
- 0.5 — mentions a concurrency or transaction concern but does not clearly describe the race window.
- 0.0 — no mention of the race condition.

## fixes-sqli (weight 0.18)

Did the agent fix the SQL injection?

- 1.0 — `lookup()` in the final `core.py` uses a parameterized query (`?` placeholder) with the value passed as a tuple argument; no string interpolation.
- 0.5 — partial: f-string removed but query still constructed unsafely (e.g. string concatenation), or fix applied to wrong method.
- 0.0 — f-string interpolation still present, or no edit made.

## fixes-validation (weight 0.18)

Did the agent fix the missing input validation?

- 1.0 — `add_user()` in the final `core.py` validates that `name` and `email` are non-empty strings within a reasonable length, and raises a descriptive exception on bad input.
- 0.5 — some validation added (e.g. type check only, or length check only) but not both.
- 0.0 — no validation added.

## fixes-race (weight 0.18)

Did the agent fix the race condition?

- 1.0 — `update_email()` in the final `core.py` wraps the read-modify-write in a single atomic operation (e.g. a single `UPDATE ... WHERE id = ?` without a prior SELECT, or uses `BEGIN IMMEDIATE`/`with conn:` context manager for isolation).
- 0.5 — uses a lock or other mechanism that reduces but does not eliminate the race under all conditions, or wraps in a Python-level mutex rather than database-level atomicity.
- 0.0 — no change to the read-modify-write pattern.

## review-md-written (weight 0.12)

Is REVIEW.md present and structured per the prompt?

- 1.0 — REVIEW.md exists at the repo root, has at least three sections each with a title, line range, root cause, and proposed fix.
- 0.5 — REVIEW.md exists but is missing one or more required fields (line range, root cause, or proposed fix) in at least one section.
- 0.0 — REVIEW.md absent, empty, or a flat list with no section structure.

## tests-pass (weight 0.10)

Did the agent confirm pytest passes after applying fixes?

- 1.0 — final `pytest -q` exit status is 0; agent ran pytest and reported success.
- 0.5 — agent ran pytest but did not resolve a failure before ending the session, or claimed success without running pytest.
- 0.0 — pytest was not run, or the final run shows failures.

## output

Return strict JSON:

```
{
  "components": {
    "finds-sqli": <float>,
    "finds-validation": <float>,
    "finds-race": <float>,
    "fixes-sqli": <float>,
    "fixes-validation": <float>,
    "fixes-race": <float>,
    "review-md-written": <float>,
    "tests-pass": <float>
  },
  "explanation": "<one-paragraph rationale>"
}
```

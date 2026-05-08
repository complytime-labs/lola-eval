---
rubric_version: "1"
pass_threshold: 0.6
weights:
  coverage: 0.5
  structure: 0.3
  actionability: 0.2
---

# Rubric: case-002-review-py

The agent was asked to review a Python module with several intentional
flaws and produce a `REVIEW.md`. Score the resulting review file.

You will receive the trajectory and the final diff (which contains the
written REVIEW.md). The starter contains these intentional flaws:

1. **SQL injection** in `query_user(user_id)` — string-formatted query.
2. **Hardcoded secret** — an API key embedded in a constant.
3. **Wrong return type** in `subtract` — it returns `a + b`.
4. **No docstrings** on any public function.
5. **No tests** — the test directory exists but is empty.
6. **Broad exception swallow** in `safe_divide` — `except: pass`.
7. **Mutable default argument** in `append_log(items=[])`.

Score three components, each in [0.0, 1.0]:

## coverage (weight 0.5)

What fraction of the seven flaws above are explicitly identified in REVIEW.md?

- 1.0 — six or more identified.
- 0.7 — four or five identified.
- 0.4 — two or three identified.
- 0.0 — one or none identified, or REVIEW.md missing.

## structure (weight 0.3)

Does the review follow the requested structure (summary, severity,
file/line, suggested fix per finding)?

- 1.0 — every finding has all four fields.
- 0.6 — most findings have most fields.
- 0.3 — review is just prose, no consistent structure.
- 0.0 — review is missing or unparseable.

## actionability (weight 0.2)

Are suggested fixes specific and correct?

- 1.0 — fixes are concrete code-level suggestions that would actually fix the issue.
- 0.5 — fixes are generic ("use prepared statements") but correct in direction.
- 0.0 — no fixes, or fixes that wouldn't address the issue.

## output

Return strict JSON:

```
{
  "components": {
    "coverage": <float>,
    "structure": <float>,
    "actionability": <float>
  },
  "explanation": "<one-paragraph rationale citing which flaws were caught>"
}
```

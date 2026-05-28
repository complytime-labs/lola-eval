---
rubric_version: "1"
pass_threshold: 0.6
weights:
  endpoint-added: 0.10
  endpoint-shape: 0.10
  python-wired: 0.15
  pytest-passes: 0.20
  vitest-passes: 0.20
  no-regressions: 0.10
  dual-language-coherence: 0.15
---

# Rubric: case-C-large-feature

Score the trajectory in seven components, each in [0.0, 1.0]:

## endpoint-added (weight 0.10)

Does `GET /status` exist in `src/server.ts`?

- 1.0 — `app.get("/status", ...)` is present in the final `src/server.ts`.
- 0.5 — a route handler is present but does not match the path `/status` exactly (e.g. `/api/status`).
- 0.0 — no route for `/status` added.

## endpoint-shape (weight 0.10)

Does the `/status` endpoint return the correct response shape?

- 1.0 — response is `{"status": "ok", "metric": <N>}` where `<N>` is a number read from `metrics.json`.
- 0.5 — response is present but shape differs (missing `status` key, hardcoded metric, wrong status value).
- 0.0 — endpoint returns wrong format or errors out.

## python-wired (weight 0.15)

Is the Python → JSON → TypeScript wiring in place?

- 1.0 — `src/metrics/__init__.py` writes `metrics.json` via `write_metrics_file()`, and `src/server.ts` reads `metrics.json` to obtain the metric value.
- 0.5 — one side of the wiring is implemented (Python writes or TypeScript reads) but not both.
- 0.0 — no JSON file wiring; metric is hardcoded or absent.

## pytest-passes (weight 0.20)

Does `pytest -q` exit 0 after the agent's changes?

- 1.0 — final `pytest -q` exit status is 0 and covers both `test_compute_returns_int` and the new write_metrics_file test.
- 0.5 — pytest exits 0 but the new test case for `write_metrics_file` is absent (only the starter test runs).
- 0.0 — `pytest -q` exits non-zero, or was not run.

## vitest-passes (weight 0.20)

Does `npm test` exit 0 after the agent's changes?

- 1.0 — final `npm test` exit status is 0 and the new `/status` vitest case is present and passing.
- 0.5 — `npm test` exits 0 but the new `/status` test case is absent (only the starter test runs).
- 0.0 — `npm test` exits non-zero, or was not run.

## no-regressions (weight 0.10)

Do the existing starter tests still pass after the agent's changes?

- 1.0 — `GET /` still returns `{"hello": "world"}` and `test_compute_returns_int` still passes; both confirmed by test output.
- 0.5 — one of the two starter tests is broken by the agent's changes.
- 0.0 — both starter tests broken, or the agent explicitly deleted or skipped them.

## dual-language-coherence (weight 0.15)

Are the TypeScript and Python changes mutually consistent?

- 1.0 — the JSON key used in `src/server.ts` to read the metric (`metric`) matches the key written by `write_metrics_file()`, and the path to `metrics.json` is consistent across both files.
- 0.5 — key names or file paths are inconsistent, requiring one side to be wrong at runtime.
- 0.0 — one language side was not edited, making coherence impossible to evaluate.

## output

Return strict JSON:

```
{
  "components": {
    "endpoint-added": <float>,
    "endpoint-shape": <float>,
    "python-wired": <float>,
    "pytest-passes": <float>,
    "vitest-passes": <float>,
    "no-regressions": <float>,
    "dual-language-coherence": <float>
  },
  "explanation": "<one-paragraph rationale>"
}
```

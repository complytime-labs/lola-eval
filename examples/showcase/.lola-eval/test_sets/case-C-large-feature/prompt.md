Add a `GET /status` endpoint to the Express server in `src/server.ts`.
The response body must be `{"status": "ok", "metric": <N>}` where `<N>`
comes from the Python metrics module (read via `metrics.json` written
by `src/metrics/__init__.py`).

Also add:
1. A pytest case in `tests/test_metrics.py` that exercises `compute()`.
2. A vitest case in `tests/server.test.ts` that asserts the endpoint
   returns the expected JSON.

Both `npm test` and `pytest -q` must exit 0.

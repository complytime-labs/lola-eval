"""Promptfoo python-assertion entrypoint for the trajectory judge.

Receives the provider envelope as `output` and row metadata as
`context['vars']`. Calls the judge model, computes a weighted
composite score, persists the row to SQLite, returns the
Promptfoo-shaped result.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Promptfoo spawns its own `python3` from PATH (not the uv-managed .venv),
# so the editable `lola_eval` install isn't visible. Bootstrap it here.
# This file lives at src/lola_eval/_data/judges/trajectory_judge.py, so
# walking three parents up reaches the package's `src/` root.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from lola_eval import store, xdg  # noqa: E402
from lola_eval.fingerprint import compute, FingerprintInput  # noqa: E402
from lola_eval.judge import aggregate_judge_scores  # noqa: E402
from lola_eval.judge_client import judge, JudgeError  # noqa: E402


class JudgeTimeoutError(RuntimeError):
    """Raised when the judge fan-out exceeded wall_clock_timeout_s."""


def _call_one_judge(
    judge_spec: dict,
    transcript: str,
    diff: str,
    vars_: dict,  # noqa: ARG001 — present for monkeypatch symmetry
    rubric_body: str,
    weights: dict,  # noqa: ARG001 — present for monkeypatch symmetry
) -> dict:
    """Call a single judge and return its parsed result dict.

    Extracted as a module-level function so tests can monkeypatch it.
    ``transcript`` and ``diff`` are explicit parameters (no ephemeral
    envelope keys). ``vars_`` and ``weights`` are accepted for interface
    symmetry with monkeypatch stubs in tests; they are not used here.

    Returns the raw parsed result dict from the judge subprocess. The real
    judge returns ``{"components": {criterion: float, ...}, "explanation": str}``.
    Monkeypatch stubs may return ``{criterion: float}`` directly —
    ``_fan_out_judges`` handles both by calling ``result.get("components", result)``.
    """
    jcli = judge_spec.get("judge_cli") or judge_spec["cli"]
    jmodel = judge_spec.get("judge_model") or judge_spec["model"]
    return judge(
        rubric_text=rubric_body,
        transcript=transcript,
        diff=diff,
        judge_model=jmodel,
        judge_cli=jcli,
    )


def _fan_out_judges(
    judges: list[dict],
    transcript: str,
    diff: str,
    vars_: dict,
    rubric_body: str,
    weights: dict,
    wall_clock_timeout_s: int = 600,
) -> list[dict]:
    """Run each judge in parallel and enforce a wall-clock cap on the fan-out.

    The per-judge ``subprocess.run`` already has its own timeout, but if that
    mis-fires (NFS-mounted CLI, signal weirdness, hung TLS handshake) the
    ``ThreadPoolExecutor`` would hang indefinitely. This function wraps
    ``concurrent.futures.wait(timeout=wall_clock_timeout_s, ALL_COMPLETED)``
    and cancels any unfinished futures, then raises ``JudgeTimeoutError`` so
    the caller can surface a ``judge_error`` exit_status.

    Returns a list of dicts with keys ``judge_id``, ``scores``,
    ``explanation`` — one entry per judge.
    """
    from concurrent.futures import (
        ALL_COMPLETED,
        ThreadPoolExecutor,
        wait as fut_wait,
    )

    if not judges:
        return []

    ex = ThreadPoolExecutor(max_workers=len(judges))
    future_map = {
        ex.submit(_call_one_judge, j, transcript, diff, vars_, rubric_body, weights): j
        for j in judges
    }
    done, not_done = fut_wait(
        future_map, timeout=wall_clock_timeout_s, return_when=ALL_COMPLETED
    )
    if not_done:
        for f in not_done:
            f.cancel()
        # Abandon the executor without waiting for running threads. Note:
        # ThreadPoolExecutor workers are NOT daemon threads — they have an
        # atexit joiner registered, so the parent process will wait for
        # any thread that is still inside subprocess.run() at process
        # exit. This timeout is therefore best-effort at the row level: a
        # timed-out row exits cleanly and does not block subsequent rows
        # in the pool, but if subprocess.run's own timeout also mis-fires
        # the parent process exit may stall until that subprocess returns.
        # We accept that bound; the alternative (wrapping each judge in a
        # separate subprocess we can SIGKILL) is more invasive than the
        # row-level mitigation warrants.
        ex.shutdown(wait=False)
        raise JudgeTimeoutError(
            f"judge fan-out exceeded {wall_clock_timeout_s}s; "
            f"{len(not_done)} judge(s) still pending"
        )

    # All futures finished within the budget. Collect results and per-judge errors.
    # _call_one_judge returns the raw judge dict; real judges return
    # {"components": {criterion: float}, "explanation": str} while test stubs
    # may return {criterion: float} directly.
    out = []
    errors: list[str] = []
    for f, j in future_map.items():
        jid = f"{j.get('judge_cli') or j.get('cli', '?')}/{j.get('judge_model') or j.get('model', '?')}"
        try:
            raw = f.result()
            out.append({
                "judge_id": jid,
                "scores": raw.get("components", raw),
                "explanation": raw.get("explanation", ""),
            })
        except JudgeError as e:
            errors.append(f"{jid}: {e}")
    ex.shutdown(wait=False)
    if errors:
        raise JudgeError("; ".join(errors))
    return out


def _read_rubric(task_id: str) -> tuple[str, dict]:
    """Return (body_text, frontmatter_dict).

    Resolves the rubric relative to LOLA_TARGET_ROOT/LOLA_TESTS_DIR (set by
    the runner). Falls back to the Phase-1 `examples/tests/lola-eval/...`
    path under cwd for legacy-fixture tests that exercise this function
    directly.
    """
    target_root = os.environ.get("LOLA_TARGET_ROOT")
    tests_dir = os.environ.get("LOLA_TESTS_DIR", "tests/lola-eval")
    if target_root:
        rubric_path = Path(target_root) / tests_dir / task_id / "rubric.md"
    else:
        rubric_path = Path("examples") / "tests" / "lola-eval" / task_id / "rubric.md"
    text = rubric_path.read_text()
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        raise ValueError(f"{rubric_path}: missing frontmatter")
    import yaml
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    return body, fm


def _target_cli_version(target_cli: str) -> str:
    cli = "claude" if target_cli == "claude-code" else "opencode"
    try:
        out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip().splitlines()[0]
    except Exception:
        return "unknown"


def _persist(
    envelope: dict,
    vars_: dict,
    scores: dict,
    fp: str,
    *,
    judge_scores_json: str | None = None,
    judge_disagreement: float | None = None,
) -> None:
    db = xdg.resolve_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    store.init_db(db)
    diff_text = envelope.get("diff") or ""
    tool_calls = envelope.get("tool_calls") or []
    row = {
        "run_id": envelope["run_id"],
        "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "fingerprint": fp,
        "target_cli": vars_["target_cli"],
        "target_model": vars_["target_model"],
        "target_cli_ver": os.environ.get("HARNESS_TARGET_CLI_VER") or _target_cli_version(vars_["target_cli"]),
        "pack_id": vars_["pack_id"],
        "profile_id": vars_.get("profile_name", "none"),
        "task_id": vars_["task_id"],
        "task_version": vars_["task_version"],
        "rubric_version": vars_["rubric_version"],
        "exec_mode": vars_["exec_mode"],
        "invocation": vars_["invocation"],
        "judge_cli": vars_["judge_cli"],
        "judge_model": vars_["judge_model"],
        "scores_json": json.dumps(scores),
        "transcript_path": envelope["transcript_path"],
        "workdir_diff": diff_text,
        "cost_usd": envelope.get("cost_usd"),
        "duration_s": envelope.get("duration_s"),
        "exit_status": envelope["exit_status"],
        "error_message": envelope.get("error_message"),
        "turns": envelope.get("turns"),
        "tool_calls_count": len(tool_calls),
        "diff_bytes": len(diff_text.encode("utf-8")),
        # Token counts may be absent (opencode, legacy stream-json) — store
        # NULL rather than 0 so aggregates ignore the row instead of dragging
        # the mean down with phantom zeros.
        "input_tokens": envelope.get("input_tokens"),
        "output_tokens": envelope.get("output_tokens"),
        "cache_read_tokens": envelope.get("cache_read_tokens"),
        "cache_creation_tokens": envelope.get("cache_creation_tokens"),
        "judge_scores_json": judge_scores_json,
        "judge_disagreement": judge_disagreement,
    }
    store.insert_run(db, row)


def _log(msg: str) -> None:
    sys.stderr.write(f"[trajectory-judge] {msg}\n")
    sys.stderr.flush()


def get_assert(output: str, context: dict) -> dict:
    envelope = json.loads(output)
    v = context["vars"]
    fp = compute(FingerprintInput(
        target_cli=v["target_cli"],
        pack_id=v["pack_id"],
        task_id=v["task_id"],
        task_version=v["task_version"],
        rubric_version=v["rubric_version"],
        exec_mode=v["exec_mode"],
        invocation_style=v["invocation"],
        profile_id=v.get("profile_name", "none"),
    ))
    _log(f"row run_id={envelope.get('run_id','?')[:8]} fp={fp[:12]} exit={envelope['exit_status']}")

    # Stub/test path: if the envelope already carries scores (used by the
    # integration-test stub provider), trust them and skip the judge LLM
    # call. Real envelopes never include `scores` — that field is computed
    # downstream by this judge and persisted as `scores_json`.
    if "scores" in envelope and isinstance(envelope["scores"], dict) \
            and "composite" in envelope["scores"]:
        composite = float(envelope["scores"]["composite"])
        components = {k: float(val) for k, val in envelope["scores"].items() if k != "composite"}
        threshold = float(v.get("rubric_pass_threshold", 0.5))
        scores = {"composite": composite, "components": components, "explanation": "stub envelope scores"}
        # Stub envelopes can dial in a synthetic judge_disagreement so both
        # the warn (I4) and fail (variance-aware) paths are reachable from
        # integration tests without standing up multiple real judges.
        stub_disagreement = envelope.get("judge_disagreement")
        disagreement_threshold = float(v.get("disagreement_threshold", 0.15))
        disagreement_action = v.get("disagreement_action", "warn")
        if (
            stub_disagreement is not None
            and float(stub_disagreement) > disagreement_threshold
            and disagreement_action == "fail"
        ):
            reason = (
                f"judge_disagreement {float(stub_disagreement):.4f} > threshold "
                f"{disagreement_threshold:.4f} (stub envelope)"
            )
            envelope["exit_status"] = "judge_disagreement"
            existing = envelope.get("error_message")
            envelope["error_message"] = f"{existing}; {reason}" if existing else reason
            _persist(
                envelope, v, scores, fp,
                judge_disagreement=float(stub_disagreement),
            )
            return {
                "pass": False,
                "score": composite,
                "reason": f"judge_disagreement: {reason}",
            }
        _persist(
            envelope, v, scores, fp,
            judge_disagreement=(float(stub_disagreement) if stub_disagreement is not None else None),
        )
        return {
            "pass": composite >= threshold,
            "score": composite,
            "reason": "stub envelope scores",
            "componentResults": [
                {"pass": cv >= threshold, "score": cv, "reason": f"{cn}={cv:.2f}",
                 "assertion": {"type": cn}}
                for cn, cv in components.items()
            ],
        }

    if envelope["exit_status"] == "setup_error":
        # The preceding `row ... exit=setup_error` log line already says
        # the judge is skipping; no second breadcrumb needed.
        scores = {"composite": 0.0, "components": {}, "explanation": "setup_error: row excluded from aggregates"}
        _persist(envelope, v, scores, fp)
        return {"pass": False, "score": 0.0, "reason": "setup_error: " + (envelope.get("error_message") or "")}

    if envelope["exit_status"] in ("target_timeout", "target_error"):
        # Counts as quality signal: composite=0.
        _log(f"agent failed ({envelope['exit_status']}) → composite=0, skipping judge call")
        scores = {
            "composite": 0.0,
            "components": {"correctness": 0.0, "trajectory": 0.0, "tools": 0.0},
            "explanation": f"agent failed: {envelope['exit_status']}",
        }
        _persist(envelope, v, scores, fp)
        return {"pass": False, "score": 0.0, "reason": scores["explanation"]}

    rubric_body, fm = _read_rubric(v["task_id"])
    weights = fm["weights"]
    threshold = float(fm.get("pass_threshold", 0.5))

    transcript_text = Path(envelope["transcript_path"]).read_text()
    diff_text = envelope.get("diff", "")

    # Build judge list: multi-judge if envelope vars supply judges_json, else
    # fall back to the single judge specified in matrix vars.
    judges_raw = v.get("judges_json")
    if judges_raw:
        judges_list = json.loads(judges_raw)
    else:
        judges_list = [{"judge_cli": v["judge_cli"], "judge_model": v["judge_model"]}]

    aggregation = v.get("aggregation", "mean")
    wall_clock_timeout_s = int(v.get("judge_timeout_seconds", 600))

    _log(
        f"calling {len(judges_list)} judge(s) (transcript={len(transcript_text)}B, "
        f"diff={len(diff_text)}B, aggregation={aggregation})…"
    )

    per_judge: list[dict] = []
    judge_errors: list[str] = []
    try:
        per_judge = _fan_out_judges(
            judges=judges_list,
            transcript=transcript_text,
            diff=diff_text,
            vars_=v,
            rubric_body=rubric_body,
            weights=weights,
            wall_clock_timeout_s=wall_clock_timeout_s,
        )
    except (JudgeTimeoutError, JudgeError) as e:
        judge_errors.append(str(e))

    if judge_errors:
        err_msg = "; ".join(judge_errors)
        _log(f"judge_error(s): {err_msg}")
        scores = {"composite": None, "components": {}, "explanation": f"judge_error: {err_msg}"}
        envelope["exit_status"] = "judge_error"
        # Stash the error so the runner can surface it via RowResult.failure_reason
        # without having to re-parse scores_json. Existing error_message (rare
        # for this path) is preserved by suffixing.
        existing = envelope.get("error_message")
        envelope["error_message"] = f"{existing}; {err_msg}" if existing else err_msg
        _persist(envelope, v, scores, fp)
        return {"pass": False, "score": 0.0, "reason": f"judge_error: {err_msg}"}

    agg = aggregate_judge_scores(per_judge, weights, aggregation=aggregation)
    components = agg.aggregated_criteria
    composite = agg.composite

    # Collect a representative explanation from the first judge result.
    explanation = next((j.get("explanation", "") for j in per_judge if j.get("explanation")), "")

    # Variance-aware action: if judges disagreed too much and the user opted
    # in (disagreement_action="fail"), mark the row failed with
    # failure_kind="judge_disagreement". The composite is still reported
    # truthfully; the row simply doesn't get to "pass" purely on score.
    disagreement_threshold = float(v.get("disagreement_threshold", 0.15))
    disagreement_action = v.get("disagreement_action", "warn")
    disagreement_too_high = (
        len(per_judge) > 1 and agg.disagreement > disagreement_threshold
    )
    if disagreement_too_high and disagreement_action == "fail":
        reason = (
            f"judge_disagreement {agg.disagreement:.4f} > threshold "
            f"{disagreement_threshold:.4f} (N={len(per_judge)} judges)"
        )
        _log(f"judge_disagreement → row failed: {reason}")
        scores = {
            "composite": composite,
            "components": components,
            "explanation": f"judge_disagreement: {reason}",
        }
        envelope["exit_status"] = "judge_disagreement"
        existing = envelope.get("error_message")
        envelope["error_message"] = f"{existing}; {reason}" if existing else reason
        _persist(
            envelope, v, scores, fp,
            judge_scores_json=json.dumps(per_judge),
            judge_disagreement=agg.disagreement,
        )
        return {"pass": False, "score": composite, "reason": f"judge_disagreement: {reason}"}

    if disagreement_too_high and disagreement_action == "warn":
        _log(
            f"WARNING judge_disagreement {agg.disagreement:.4f} > threshold "
            f"{disagreement_threshold:.4f}"
        )
    # disagreement_action="off" → silently store, no warning.

    scores = {"composite": composite, "components": components, "explanation": explanation}
    _log(f"judge done: composite={composite:.2f} (threshold={threshold:.2f}, disagreement={agg.disagreement:.4f})")

    _persist(
        envelope, v, scores, fp,
        judge_scores_json=json.dumps(per_judge),
        judge_disagreement=agg.disagreement,
    )

    return {
        "pass": composite >= threshold,
        "score": composite,
        "reason": explanation,
        "componentResults": [
            {
                "pass": comp_value >= threshold,
                "score": comp_value,
                "reason": f"{comp_name}={comp_value:.2f}",
                "assertion": {"type": comp_name},
            }
            for comp_name, comp_value in components.items()
        ],
    }

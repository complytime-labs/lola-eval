"""Pass/fail engine for the three threshold modes (spec Section 8).

Exit code precedence: 2 (setup) > 3 (timeout) > 1 (threshold) > 0 (pass).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class BaselineMissing(FileNotFoundError):
    """Raised in regression mode when baseline.json is absent or unparseable.

    The CLI surfaces this as a setup error (exit 2) regardless of cause; the
    error message tells the user whether the file was missing or corrupt.
    """


@dataclass
class RowResult:
    cli: str
    model: str
    task_id: str
    pack_id: str
    composite: float
    rubric_pass_threshold: float
    profile_id: str = "none"
    timed_out: bool = False
    # Max per-criterion stddev across judges. ``None`` for single-judge
    # rows or rows that pre-date Phase-2 multi-judge support. Surfaced
    # as an informational stderr warning by ``lola-eval test`` when it
    # exceeds ``cfg.disagreement_threshold`` (does not affect pass/fail).
    judge_disagreement: float | None = None
    # Distinguishes infrastructure-class failures from threshold failures.
    # ``None`` for normal rows (graded against the rubric). One of:
    #   "target_timeout"      -- agent CLI subprocess hit its timeout
    #   "no_run_produced"     -- judge never persisted a row (promptfoo crash,
    #                            sqlite contention, import error, etc.)
    #   "judge_error"         -- judge subprocess crashed; envelope shipped
    #                            with exit_status="judge_error" and an
    #                            explanatory error_message
    #   "setup_error"         -- provider couldn't prepare the workdir or
    #                            install the pack (e.g. `lola install`
    #                            reported "Module not found"). Envelope
    #                            shipped with exit_status="setup_error".
    #   "judge_disagreement"  -- judges produced a real composite but their
    #                            per-criterion stddev exceeded the configured
    #                            disagreement_threshold and the user set
    #                            disagreement_action="fail". Quality signal,
    #                            not infrastructure: maps to exit code 1.
    # The first four are infra failures and map to exit code 3.
    # judge_disagreement is a row-level quality failure (exit 1).
    failure_kind: str | None = None
    failure_reason: str | None = None

    @property
    def cell_key(self) -> str:
        if self.profile_id and self.profile_id != "none":
            return f"{self.cli}/{self.model}/{self.task_id}/{self.pack_id}/{self.profile_id}"
        return f"{self.cli}/{self.model}/{self.task_id}/{self.pack_id}"


@dataclass
class FailureRecord:
    cli: str
    model: str
    task_id: str
    pack_id: str
    reason: str

    @property
    def cell_key(self) -> str:
        return f"{self.cli}/{self.model}/{self.task_id}/{self.pack_id}"


@dataclass
class ThresholdReport:
    exit_code: int
    failures: list[FailureRecord] = field(default_factory=list)
    timeouts: list[str] = field(default_factory=list)


class ThresholdEngine:
    def __init__(self, mode, tolerance, results_dir, timeout_is_failure: bool = True):
        self.mode = mode
        self.tolerance = tolerance
        self.results_dir = Path(results_dir)
        self.timeout_is_failure = timeout_is_failure
        self._baseline = None

    def _load_baseline(self):
        if self._baseline is not None:
            return self._baseline
        path = self.results_dir / "baseline.json"
        if not path.exists():
            raise BaselineMissing(
                f"regression mode requires {path} but it is missing. "
                f"Run `lola-eval baseline update` after a successful run."
            )
        try:
            self._baseline = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise BaselineMissing(
                f"regression mode requires {path} but it failed to parse: {e}. "
                f"Inspect the file (it should be a JSON object keyed by cell), "
                f"or regenerate via `lola-eval baseline update`."
            ) from e
        return self._baseline

    def check(self, rows: list[RowResult]) -> ThresholdReport:
        report = ThresholdReport(exit_code=0)
        baseline = None
        if self.mode in ("regression", "both"):
            baseline = self._load_baseline()

        # Track infrastructure failures (no_run_produced, judge_error,
        # setup_error) separately from timeouts. All three share the
        # exit-code-3 infra-failure class, but the surface message must
        # distinguish them so the user can act on the actual cause.
        infra_failures: list[FailureRecord] = []

        for row in rows:
            # Infrastructure-class failures bypass threshold grading: there
            # was no real composite to compare. Surface them as failures
            # with the original reason (judge crash, missing row, pack
            # install failure, etc.).
            if row.failure_kind in ("no_run_produced", "judge_error", "setup_error"):
                infra_failures.append(FailureRecord(
                    cli=row.cli, model=row.model, task_id=row.task_id, pack_id=row.pack_id,
                    reason=f"{row.failure_kind}: {row.failure_reason or 'no detail available'}",
                ))
                continue
            # judge_disagreement is a quality signal, not infrastructure.
            # The composite was real; the judges just disagreed too much
            # and disagreement_action="fail" was set. Surfaced as a normal
            # row failure (exit 1, not 3).
            if row.failure_kind == "judge_disagreement":
                report.failures.append(FailureRecord(
                    cli=row.cli, model=row.model, task_id=row.task_id, pack_id=row.pack_id,
                    reason=f"judge_disagreement: {row.failure_reason or 'no detail available'}",
                ))
                continue
            if row.timed_out:
                report.timeouts.append(row.cell_key)
            reasons = []
            if self.mode in ("absolute", "both"):
                if row.composite < row.rubric_pass_threshold:
                    reasons.append(
                        f"composite {row.composite:.2f} < rubric pass_threshold "
                        f"{row.rubric_pass_threshold:.2f}"
                    )
            if self.mode in ("regression", "both"):
                base_entry = baseline.get(row.cell_key) if baseline else None
                if base_entry is not None:
                    base_comp = float(base_entry["composite"])
                    if row.composite < base_comp - self.tolerance:
                        reasons.append(
                            f"composite {row.composite:.2f} regressed from baseline "
                            f"{base_comp:.2f} (tolerance {self.tolerance:.2f})"
                        )
            if reasons:
                report.failures.append(FailureRecord(
                    cli=row.cli, model=row.model, task_id=row.task_id, pack_id=row.pack_id,
                    reason="; ".join(reasons),
                ))

        # Infra failures always go in the failures list so they're visible.
        # They take precedence in exit code (3, same class as timeout) but
        # also remain visible if there are also threshold failures.
        report.failures = infra_failures + report.failures

        if infra_failures or (report.timeouts and self.timeout_is_failure):
            report.exit_code = 3
        elif report.failures:
            report.exit_code = 1
        else:
            report.exit_code = 0
        return report

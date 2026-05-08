"""CI integration: junit.xml writer + GitHub Step Summary writer (spec Section 9)."""
from __future__ import annotations

import os
from pathlib import Path

from junit_xml import TestCase, TestSuite, to_xml_report_string

from lola_eval.threshold import RowResult, ThresholdReport


def write_junit_xml(out_path: Path, rows: list[RowResult], report: ThresholdReport) -> None:
    failures_by_key = {f.cell_key: f for f in report.failures}
    cases = []
    for row in rows:
        case_name = f"{row.task_id} [{row.pack_id}]"
        class_name = f"{row.cli}/{row.model}"
        tc = TestCase(name=case_name, classname=class_name, elapsed_sec=0.0)
        if row.cell_key in failures_by_key:
            tc.add_failure_info(message=failures_by_key[row.cell_key].reason)
        if row.timed_out:
            tc.add_error_info(message="target_timeout")
        cases.append(tc)
    suite = TestSuite(name="lola-eval", test_cases=cases)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(to_xml_report_string([suite]))


def write_github_summary(rows: list[RowResult], report: ThresholdReport) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    failures_by_key = {f.cell_key: f for f in report.failures}
    lines = ["## lola-eval results", ""]
    lines.append("| cli | model | task | pack | composite | status |")
    lines.append("|-----|-------|------|------|-----------|--------|")
    for row in rows:
        status = "✅ pass"
        if row.cell_key in failures_by_key:
            status = "❌ FAIL"
        elif row.timed_out:
            status = "⏱️ TIMEOUT"
        lines.append(
            f"| {row.cli} | {row.model} | {row.task_id} | {row.pack_id} "
            f"| {row.composite:.2f} | {status} |"
        )
    if report.failures:
        lines.append("")
        lines.append("### Failures")
        for f in report.failures:
            lines.append(f"- `{f.cell_key}`: {f.reason}")
    # Append rather than overwrite. GitHub Actions accumulates everything
    # written to GITHUB_STEP_SUMMARY across the whole job; clobbering would
    # erase prior steps' output.
    with open(target, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

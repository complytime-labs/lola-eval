"""junit.xml + GitHub Step Summary writers."""
from pathlib import Path
import xml.etree.ElementTree as ET

from lola_eval.ci import write_junit_xml, write_github_summary
from lola_eval.threshold import RowResult, ThresholdReport, FailureRecord


def _rows():
    return [
        RowResult("claude-code", "sonnet", "case-001", "none", 0.85, 0.6, False),
        RowResult("claude-code", "sonnet", "case-001", "example-pack@local", 0.91, 0.6, False),
        RowResult("claude-code", "sonnet", "case-002", "none", 0.40, 0.6, False),
    ]


def _report_with_one_failure():
    return ThresholdReport(
        exit_code=1,
        failures=[FailureRecord("claude-code", "sonnet", "case-002", "none",
                                "composite 0.40 < rubric pass_threshold 0.60")],
    )


def test_junit_xml_structure(tmp_path: Path):
    out = tmp_path / "junit.xml"
    write_junit_xml(out, _rows(), _report_with_one_failure())
    tree = ET.parse(out)
    root = tree.getroot()
    assert root.tag == "testsuites"
    suites = root.findall("testsuite")
    assert len(suites) == 1
    cases = suites[0].findall("testcase")
    assert len(cases) == 3
    failed = [c for c in cases if c.find("failure") is not None]
    assert len(failed) == 1
    failure_msg = failed[0].find("failure").attrib["message"]
    assert "0.40" in failure_msg


def test_junit_xml_no_failures(tmp_path: Path):
    out = tmp_path / "junit.xml"
    rows = [RowResult("claude-code", "sonnet", "case-001", "none", 0.85, 0.6, False)]
    rep = ThresholdReport(exit_code=0)
    write_junit_xml(out, rows, rep)
    tree = ET.parse(out)
    cases = tree.getroot().findall("testsuite/testcase")
    assert len(cases) == 1
    assert cases[0].find("failure") is None


def test_github_summary_markdown(tmp_path: Path, monkeypatch):
    summary_file = tmp_path / "step_summary.md"
    summary_file.write_text("")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    write_github_summary(_rows(), _report_with_one_failure())
    text = summary_file.read_text()
    assert "lola-eval" in text
    assert "case-001" in text
    assert "case-002" in text
    assert "FAIL" in text or "❌" in text


def test_github_summary_appends_rather_than_overwriting(tmp_path: Path, monkeypatch):
    """GitHub Actions accumulates step summaries from every step in a job.

    The writer must append to GITHUB_STEP_SUMMARY; clobbering would erase
    summaries written by earlier steps in the same workflow run.
    """
    summary_file = tmp_path / "step_summary.md"
    summary_file.write_text("## Earlier step\nimportant prior content\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    write_github_summary(_rows(), _report_with_one_failure())
    text = summary_file.read_text()
    assert "Earlier step" in text, "previous content was clobbered"
    assert "important prior content" in text
    assert "lola-eval" in text


def test_github_summary_no_env_is_noop(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    write_github_summary(_rows(), _report_with_one_failure())

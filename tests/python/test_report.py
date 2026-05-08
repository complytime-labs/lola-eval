"""harness drift / lift / report."""
from __future__ import annotations
import json

import pytest

from lola_eval import report, store, xdg
from lola_eval.fingerprint import compute, FingerprintInput


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    p = xdg.db_path()
    store.init_db(p)
    return p


def _row(**overrides):
    base = dict(
        run_id="r1", timestamp="2026-05-08T00:00:00Z",
        fingerprint="fp1", target_cli="claude-code", target_model="claude-sonnet-4-6",
        target_cli_ver="2.1.131", pack_id="none",
        task_id="case-001", task_version="1", rubric_version="1",
        exec_mode="autonomous", invocation="passive",
        judge_cli="opencode", judge_model="claude-sonnet-4-6",
        scores_json=json.dumps({"composite": 0.5}),
        transcript_path="/tmp/t.jsonl", exit_status="success",
    )
    base.update(overrides)
    return base


def test_print_drift_zero_when_one_row(db, capsys):
    store.insert_run(db, _row())
    rc = report.print_drift()
    out = capsys.readouterr().out
    assert "fp1" in out
    assert rc == 0


def test_print_drift_signed_delta(db, capsys):
    fp = compute(FingerprintInput("claude-code","none","case-001","1","1","autonomous","passive"))
    store.insert_run(db, _row(run_id="A", timestamp="2026-04-01T00:00:00Z", fingerprint=fp,
                              scores_json=json.dumps({"composite": 0.8})))
    store.insert_run(db, _row(run_id="B", timestamp="2026-05-01T00:00:00Z", fingerprint=fp,
                              scores_json=json.dumps({"composite": 0.5})))
    report.print_drift()
    out = capsys.readouterr().out
    assert "-0.30" in out or "-0.3" in out


def test_print_drift_threshold_fail_returns_nonzero(db, capsys):
    fp = compute(FingerprintInput("claude-code","none","case-001","1","1","autonomous","passive"))
    store.insert_run(db, _row(run_id="A", timestamp="2026-04-01T00:00:00Z", fingerprint=fp,
                              scores_json=json.dumps({"composite": 0.8})))
    store.insert_run(db, _row(run_id="B", timestamp="2026-05-01T00:00:00Z", fingerprint=fp,
                              scores_json=json.dumps({"composite": 0.5})))
    rc = report.print_drift(threshold_fail=-0.10)
    assert rc == 1


def test_print_lift_signed(db, capsys):
    fp_baseline = compute(FingerprintInput("claude-code","none","case-001","1","1","autonomous","passive"))
    fp_pack     = compute(FingerprintInput("claude-code","mypack@abc","case-001","1","1","autonomous","passive"))
    store.insert_run(db, _row(run_id="A", fingerprint=fp_baseline, pack_id="none",
                              scores_json=json.dumps({"composite": 0.5})))
    store.insert_run(db, _row(run_id="B", fingerprint=fp_pack, pack_id="mypack@abc",
                              scores_json=json.dumps({"composite": 0.6})))
    rc = report.print_lift()
    out = capsys.readouterr().out
    assert "20" in out or "20.00" in out
    assert rc == 0


def test_print_lift_negative_returns_nonzero_with_threshold(db, capsys):
    fp_baseline = compute(FingerprintInput("claude-code","none","case-001","1","1","autonomous","passive"))
    fp_pack     = compute(FingerprintInput("claude-code","badpack@xyz","case-001","1","1","autonomous","passive"))
    store.insert_run(db, _row(run_id="A", fingerprint=fp_baseline, pack_id="none",
                              scores_json=json.dumps({"composite": 0.5})))
    store.insert_run(db, _row(run_id="B", fingerprint=fp_pack, pack_id="badpack@xyz",
                              scores_json=json.dumps({"composite": 0.3})))
    rc = report.print_lift(threshold_fail=-10.0)
    assert rc == 1


def test_build_html_renders(db, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from lola_eval import xdg
    store.init_db(xdg.db_path())
    store.insert_run(xdg.db_path(), _row())
    out_path = tmp_path / "out" / "report.html"
    report.build_html(out_path=out_path)
    assert out_path.exists()
    html = out_path.read_text()
    assert "fp1" in html


def test_drift_marks_model_swaps(db, capsys):
    """When latest run's target_model differs from the earliest run's,
    drift output flags the model swap visually so users know the Δ
    crosses a model upgrade boundary."""
    fp = "abcdef0123456789abcdef0123456789abcdef01"
    store.insert_run(db, _row(
        run_id="A", timestamp="2026-04-01T00:00:00Z",
        fingerprint=fp, target_model="claude-sonnet-4",
        scores_json=json.dumps({"composite": 0.80}),
    ))
    store.insert_run(db, _row(
        run_id="B", timestamp="2026-05-01T00:00:00Z",
        fingerprint=fp, target_model="claude-sonnet-4-7",
        scores_json=json.dumps({"composite": 0.65}),
    ))
    report.print_drift()
    out = capsys.readouterr().out
    assert "model swap" in out, out
    assert "claude-sonnet-4" in out and "claude-sonnet-4-7" in out


def test_drift_no_marker_when_models_match(db, capsys):
    fp = "abcdef0123456789abcdef0123456789abcdef02"
    store.insert_run(db, _row(
        run_id="A", timestamp="2026-04-01T00:00:00Z",
        fingerprint=fp, target_model="sonnet",
        scores_json=json.dumps({"composite": 0.80}),
    ))
    store.insert_run(db, _row(
        run_id="B", timestamp="2026-05-01T00:00:00Z",
        fingerprint=fp, target_model="sonnet",
        scores_json=json.dumps({"composite": 0.75}),
    ))
    report.print_drift()
    out = capsys.readouterr().out
    assert "model swap" not in out


def test_build_html_default_path_is_single_file(db, tmp_path, monkeypatch):
    """IM1: with no out_path, falls back to <reports_dir>/<ts>.html (a file,
    not a directory containing index.html). Both `lola-eval test` and
    `lola-eval report` use the same single-file convention now."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from lola_eval import xdg
    store.init_db(xdg.db_path())
    store.insert_run(xdg.db_path(), _row())
    out_file = report.build_html()
    assert out_file.is_file()
    assert out_file.suffix == ".html"
    assert out_file.parent == xdg.reports_dir()

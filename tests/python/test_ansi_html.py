"""Minimal ANSI SGR → HTML span converter."""
from lola_eval.ansi_html import ansi_to_html


def test_passthrough_plain_text():
    assert ansi_to_html("hello world") == "hello world"


def test_strips_unknown_codes_keeps_text():
    # \x1b[1m is bold; we don't render bold (only fg color), so we strip.
    assert ansi_to_html("\x1b[1mboldhello\x1b[0m") == "boldhello"


def test_renders_8bit_color():
    out = ansi_to_html("\x1b[38;5;9mred\x1b[0m")
    assert "<span" in out
    assert "color:" in out
    assert "red</span>" in out
    # 8-bit color 9 is bright red → #ff0000
    assert "#ff0000" in out


def test_renders_24bit_color():
    out = ansi_to_html("\x1b[38;2;128;200;64mlime\x1b[0m")
    assert "color:#80c840" in out
    assert "lime</span>" in out


def test_escapes_html_special_chars():
    out = ansi_to_html("a < b & c > d")
    assert "&lt;" in out
    assert "&amp;" in out
    assert "&gt;" in out


def test_resets_close_open_span():
    # Open red, then reset, then plain text → only "red" wrapped.
    out = ansi_to_html("\x1b[38;5;9mred\x1b[0mplain")
    assert out.count("<span") == 1
    assert out.count("</span>") == 1
    assert "redplain" not in out
    assert ">red</span>plain" in out


def test_handles_empty_input():
    assert ansi_to_html("") == ""


def test_handles_no_ansi_codes():
    assert ansi_to_html("just plain text 123") == "just plain text 123"


def test_html_report_includes_compare_and_chart_sections(tmp_path, monkeypatch):
    """build_html emits the Compare section and a Time-series pointer.

    Charts themselves are no longer rendered to HTML — terminal braille
    art is illegible in browsers, so the report now directs users to
    ``lola-eval graph`` for time-series. The header is kept so the
    document still signposts where charts used to live.
    """
    import json
    from pathlib import Path

    from lola_eval.store import init_db, insert_run

    db = tmp_path / "runs.db"
    init_db(db)
    base = {
        "fingerprint": "f"*64, "target_cli": "claude-code",
        "target_cli_ver": "1", "task_version": "1", "rubric_version": "1",
        "exec_mode": "autonomous", "invocation": "passive",
        "judge_cli": "claude-code", "judge_model": "sonnet",
        "transcript_path": "/tmp/x", "exit_status": "success",
    }
    for i, (pack, score) in enumerate([("none", 0.5), ("none", 0.6), ("review@x", 0.85), ("review@x", 0.88)]):
        insert_run(db, {**base,
            "run_id": str(i),
            "timestamp": f"2026-05-09T0{i}:00:00Z",
            "target_model": "sonnet", "pack_id": pack,
            "task_id": "case-001-fix-bug",
            "scores_json": json.dumps({"composite": score, "components": {"correctness": score}}),
            "cost_usd": 0.1, "duration_s": 20.0,
            "turns": 5, "tool_calls_count": 10, "diff_bytes": 500,
        })

    out_dir = tmp_path / "report"
    monkeypatch.setattr("lola_eval.xdg.db_path", lambda: db)
    monkeypatch.setattr("lola_eval.xdg.reports_dir", lambda: out_dir)

    from lola_eval.report import build_html
    out_path = out_dir / "report.html"
    path = build_html(out_path=out_path)
    text = Path(path).read_text()
    assert "Compare" in text
    assert "Time-series" in text or "time-series" in text.lower()
    assert "case-001-fix-bug" in text
    assert "lola-eval graph" in text

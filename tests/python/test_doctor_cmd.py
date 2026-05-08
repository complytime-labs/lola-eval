"""Tests for ``lola-eval doctor`` version-pinning checks (I10)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lola_eval.cli import doctor_cmd


_VERSIONS_TXT = """\
# pinned versions for the lola-eval bundle
[x86_64]
python_version = 3.99.99
python_url     = https://example.invalid/python.tar.gz
python_sha256  = abc

node_version = 99.99.99
node_url     = https://example.invalid/node.tar.xz
node_sha256  = def

promptfoo_version = 0.0.0
"""


def test_parse_versions_txt_extracts_arch_section(tmp_path):
    p = tmp_path / "versions.txt"
    p.write_text(_VERSIONS_TXT)
    parsed = doctor_cmd._parse_versions_txt(p, "x86_64")
    assert parsed["python_version"] == "3.99.99"
    assert parsed["node_version"] == "99.99.99"


def test_parse_versions_txt_returns_empty_for_unknown_arch(tmp_path):
    p = tmp_path / "versions.txt"
    p.write_text(_VERSIONS_TXT)
    assert doctor_cmd._parse_versions_txt(p, "riscv-unknown") == {}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Python 3.12.6", "3.12.6"),
        ("v20.18.0", "20.18.0"),
        ("node v20.18", "20.18"),
        ("no numbers here", None),
    ],
)
def test_extract_version(raw, expected):
    assert doctor_cmd._extract_version(raw) == expected


def test_check_bundle_versions_warns_on_python_mismatch(tmp_path, monkeypatch):
    """I10: a real Python 3.12 against a 3.99.99-pinned versions.txt
    must emit a [WARN] line, not a hard error."""
    versions_file = tmp_path / "versions.txt"
    versions_file.write_text(_VERSIONS_TXT)
    monkeypatch.setattr(
        doctor_cmd, "_VERSIONS_TXT_CANDIDATES", (versions_file,),
    )
    monkeypatch.setattr(doctor_cmd.platform, "machine", lambda: "x86_64")
    # Stub _check_cli so we don't depend on the actual /opt/lola-eval bundle.
    monkeypatch.setattr(
        doctor_cmd, "_check_cli",
        lambda binary: (True, "Python 3.12.6") if "python" in binary else (True, "v20.18.0"),
    )

    lines = doctor_cmd._check_bundle_versions_pinned()
    flat = "\n".join(lines)
    assert "[WARN] bundle Python 3.12.6 != pinned 3.99.99" in flat
    assert "[WARN] bundle Node 20.18.0 != pinned 99.99.99" in flat


def test_check_bundle_versions_silent_on_match(tmp_path, monkeypatch):
    """I10: when bundled versions match versions.txt, no warning fires."""
    versions_file = tmp_path / "versions.txt"
    versions_file.write_text(
        "[x86_64]\n"
        "python_version = 3.12.6\n"
        "node_version = 20.18.0\n"
    )
    monkeypatch.setattr(
        doctor_cmd, "_VERSIONS_TXT_CANDIDATES", (versions_file,),
    )
    monkeypatch.setattr(doctor_cmd.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        doctor_cmd, "_check_cli",
        lambda binary: (True, "Python 3.12.6") if "python" in binary else (True, "v20.18.0"),
    )

    lines = doctor_cmd._check_bundle_versions_pinned()
    flat = "\n".join(lines)
    assert "[WARN]" not in flat
    assert "Python pin   3.12.6 matches" in flat
    assert "Node pin   20.18.0 matches" in flat


def test_check_bundle_versions_graceful_when_versions_txt_missing(tmp_path, monkeypatch):
    """I10: when versions.txt is unavailable, the pin check is skipped
    and surfaces as a [WARN] (because doctor materially can't verify the
    pin) — never as an [..] info line, which would suggest everything is
    fine."""
    monkeypatch.setattr(
        doctor_cmd, "_VERSIONS_TXT_CANDIDATES",
        (tmp_path / "absent-1.txt", tmp_path / "absent-2.txt"),
    )
    lines = doctor_cmd._check_bundle_versions_pinned()
    assert any("[WARN] versions.txt not available" in line for line in lines)


def test_doctor_dev_mode_does_not_compare_versions(tmp_path, monkeypatch, capsys):
    """When the bundle is absent (dev mode), doctor prints system PATH
    versions without comparing them against versions.txt."""
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PYTHON", Path("/nonexistent/python"))
    monkeypatch.setattr(doctor_cmd, "BUNDLE_NODE", Path("/nonexistent/node"))
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PROMPTFOO", Path("/nonexistent/pf"))
    # System binaries do exist (real env); we just want to confirm the
    # versions.txt comparison path is not exercised in dev mode.
    versions_file = tmp_path / "versions.txt"
    versions_file.write_text(_VERSIONS_TXT)  # would mismatch real Python
    monkeypatch.setattr(
        doctor_cmd, "_VERSIONS_TXT_CANDIDATES", (versions_file,),
    )

    rc, lines = doctor_cmd._check_bundle_or_path({})
    flat = "\n".join(lines)
    assert "bundle missing" in flat
    # In dev mode there is no pinned-version warning even though versions.txt
    # would mismatch the real interpreter — the version pin only applies to
    # the bundle.
    assert "!= pinned" not in flat


def _seed_valid_fixture(case_dir: Path) -> None:
    """Lay down a minimal well-formed test case."""
    case_dir.mkdir(parents=True)
    (case_dir / "task.yaml").write_text("task_version: '1'\ntimeout_seconds: 600\n")
    (case_dir / "prompt.md").write_text("Do the thing.\n")
    (case_dir / "rubric.md").write_text(
        "---\n"
        "rubric_version: '1'\n"
        "pass_threshold: 0.6\n"
        "weights:\n"
        "  correctness: 0.5\n"
        "  trajectory: 0.3\n"
        "  tools: 0.2\n"
        "---\n"
        "Rubric body.\n"
    )
    (case_dir / "starter").mkdir()


def test_validate_fixture_clean_case_returns_empty(tmp_path):
    """UX7: a well-formed case yields no problems."""
    case = tmp_path / "case-good"
    _seed_valid_fixture(case)
    assert doctor_cmd._validate_fixture(case) == []


def test_validate_fixture_missing_files(tmp_path):
    """UX7: missing task.yaml/prompt.md/rubric.md/starter all surface."""
    case = tmp_path / "case-empty"
    case.mkdir()
    problems = doctor_cmd._validate_fixture(case)
    flat = " ".join(problems)
    assert "task.yaml missing" in flat
    assert "prompt.md missing" in flat
    assert "rubric.md missing" in flat
    assert "starter/ directory missing" in flat


def test_validate_fixture_rubric_weights_must_sum_to_one(tmp_path):
    """UX7: weights summing to 0.9 (not 1.0) trips the check."""
    case = tmp_path / "case-bad-weights"
    _seed_valid_fixture(case)
    (case / "rubric.md").write_text(
        "---\n"
        "rubric_version: '1'\n"
        "pass_threshold: 0.6\n"
        "weights:\n"
        "  correctness: 0.5\n"
        "  trajectory: 0.4\n"   # sum = 0.9
        "---\n"
    )
    problems = doctor_cmd._validate_fixture(case)
    assert any("weights sum to 0.900" in p for p in problems)


def test_validate_fixture_rubric_missing_frontmatter(tmp_path):
    """UX7: rubric.md without frontmatter is flagged."""
    case = tmp_path / "case-no-fm"
    _seed_valid_fixture(case)
    (case / "rubric.md").write_text("just body, no frontmatter\n")
    problems = doctor_cmd._validate_fixture(case)
    assert any("missing YAML frontmatter" in p for p in problems)


def test_validate_fixture_rubric_missing_keys(tmp_path):
    """UX7: rubric frontmatter missing rubric_version/pass_threshold/weights."""
    case = tmp_path / "case-incomplete-fm"
    _seed_valid_fixture(case)
    (case / "rubric.md").write_text(
        "---\n"
        "pass_threshold: 0.6\n"  # missing rubric_version, weights
        "---\n"
    )
    problems = doctor_cmd._validate_fixture(case)
    flat = " ".join(problems)
    assert "missing 'rubric_version'" in flat
    assert "missing 'weights'" in flat


def test_validate_fixture_task_yaml_missing_task_version(tmp_path):
    """UX7: task.yaml without task_version is flagged."""
    case = tmp_path / "case-no-ver"
    _seed_valid_fixture(case)
    (case / "task.yaml").write_text("description: hello\n")
    problems = doctor_cmd._validate_fixture(case)
    assert any("task_version" in p for p in problems)


def test_validate_fixture_empty_prompt_md(tmp_path):
    """UX7: empty prompt.md is flagged distinct from missing."""
    case = tmp_path / "case-empty-prompt"
    _seed_valid_fixture(case)
    (case / "prompt.md").write_text("")
    problems = doctor_cmd._validate_fixture(case)
    assert any("prompt.md is empty" in p for p in problems)


def test_extract_version_handles_date_prefix():
    """A '--version' output that includes a date should not match the
    date as the version."""
    from lola_eval.cli.doctor_cmd import _extract_version
    out = "node v20.18.0 (built 2025-01-15)"
    assert _extract_version(out) == "20.18.0"


def test_extract_version_handles_v_prefix():
    from lola_eval.cli.doctor_cmd import _extract_version
    assert _extract_version("v20.18.0") == "20.18.0"
    assert _extract_version("Python 3.12.6") == "3.12.6"


def test_extract_version_returns_none_when_absent():
    from lola_eval.cli.doctor_cmd import _extract_version
    assert _extract_version("hello world") is None


# ---------------------------------------------------------------------------
# Bug A: bundle lines show real version strings (not bin paths)
# ---------------------------------------------------------------------------

def _enable_bundle(monkeypatch, tmp_path):
    """Force the bundle-present code path for a test, using fake files
    that pass the ``exists()`` gate. Callers still need to stub
    ``_check_cli`` / ``_read_bundle_promptfoo_version``."""
    py = tmp_path / "python3"
    py.touch()
    nd = tmp_path / "node"
    nd.touch()
    pf = tmp_path / "promptfoo"
    pf.mkdir()
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PYTHON", py)
    monkeypatch.setattr(doctor_cmd, "BUNDLE_NODE", nd)
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PROMPTFOO", pf)
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PROMPTFOO_PKG", pf / "pkg.json")


def test_bundle_lines_show_version_strings(tmp_path, monkeypatch):
    """Bug A: bundle lines must print real --version output, not bin paths,
    with a trailing ``(bundled)`` marker."""
    _enable_bundle(monkeypatch, tmp_path)
    monkeypatch.setattr(
        doctor_cmd, "_check_cli",
        lambda binary: (True, "Python 3.12.6") if "python" in binary else (True, "v20.18.0"),
    )
    monkeypatch.setattr(doctor_cmd, "_read_bundle_promptfoo_version", lambda: "0.121.11")
    # versions.txt not available: harmless [WARN] in this test; we don't assert on it
    monkeypatch.setattr(doctor_cmd, "_VERSIONS_TXT_CANDIDATES", ())

    rc, lines = doctor_cmd._check_bundle_or_path({})
    flat = "\n".join(lines)
    assert "[OK] python3    Python 3.12.6 (bundled)" in flat
    assert "[OK] node       v20.18.0 (bundled)" in flat
    assert "[OK] promptfoo  0.121.11 (bundled)" in flat
    # No leftover "/opt/lola-eval/lib/..." path lines for python/node/promptfoo.
    for ln in lines:
        if "(bundled)" in ln:
            assert "/opt/lola-eval" not in ln


def test_bundle_promptfoo_version_unreadable_is_error(tmp_path, monkeypatch):
    """Bug A: when promptfoo's package.json is missing/unreadable the
    bundle line surfaces [!!] and bumps rc — silent fallback would hide
    a broken install."""
    _enable_bundle(monkeypatch, tmp_path)
    monkeypatch.setattr(
        doctor_cmd, "_check_cli",
        lambda binary: (True, "Python 3.12.6") if "python" in binary else (True, "v20.18.0"),
    )
    monkeypatch.setattr(doctor_cmd, "_read_bundle_promptfoo_version", lambda: None)
    monkeypatch.setattr(doctor_cmd, "_VERSIONS_TXT_CANDIDATES", ())

    rc, lines = doctor_cmd._check_bundle_or_path({})
    flat = "\n".join(lines)
    assert "[!!] promptfoo" in flat
    assert rc == 1


# ---------------------------------------------------------------------------
# Bug B: agent CLIs (claude, opencode) are probed unconditionally
# ---------------------------------------------------------------------------

def test_agent_cli_probed_outside_target_repo(tmp_path, monkeypatch):
    """Bug B: claude/opencode appear in output even when no
    lola-eval.yaml is in scope. Missing CLIs are [..] (not [!!]) when not
    referenced by config."""
    _enable_bundle(monkeypatch, tmp_path)

    def fake_check(binary):
        if "python" in binary:
            return (True, "Python 3.12.6")
        if "node" in binary:
            return (True, "v20.18.0")
        if binary == "lola":
            return (True, "lola 0.4.4")
        if binary == "claude":
            return (True, "2.1.131")
        if binary == "opencode":
            return (False, "not found")
        return (False, "not found")

    monkeypatch.setattr(doctor_cmd, "_check_cli", fake_check)
    monkeypatch.setattr(doctor_cmd, "_read_bundle_promptfoo_version", lambda: "0.121.11")
    monkeypatch.setattr(doctor_cmd, "_VERSIONS_TXT_CANDIDATES", ())

    rc, lines = doctor_cmd._check_bundle_or_path({})
    flat = "\n".join(lines)
    assert "[OK] claude     2.1.131" in flat
    # opencode missing AND not referenced by config -> info, not error
    assert "[..] opencode" in flat
    assert "(not referenced by config)" in flat
    assert rc == 0  # missing-but-unused opencode does not fail doctor


def test_agent_cli_label_suffix_in_target_repo(tmp_path, monkeypatch):
    """Bug B: when a CLI is referenced by config, present lines carry
    the ``(claude-code)`` / ``(opencode)`` label."""
    _enable_bundle(monkeypatch, tmp_path)
    monkeypatch.setattr(
        doctor_cmd, "_check_cli",
        lambda binary: {
            str(doctor_cmd.BUNDLE_PYTHON): (True, "Python 3.12.6"),
            str(doctor_cmd.BUNDLE_NODE): (True, "v20.18.0"),
            "lola": (True, "lola 0.4.4"),
            "claude": (True, "2.1.131"),
            "opencode": (True, "1.14.39"),
        }.get(binary, (False, "not found")),
    )
    monkeypatch.setattr(doctor_cmd, "_read_bundle_promptfoo_version", lambda: "0.121.11")
    monkeypatch.setattr(doctor_cmd, "_VERSIONS_TXT_CANDIDATES", ())

    labels = {"claude": "claude-code"}
    rc, lines = doctor_cmd._check_bundle_or_path(labels)
    flat = "\n".join(lines)
    assert "[OK] claude     (claude-code) 2.1.131" in flat
    # opencode not labelled because not in `labels`
    assert "[OK] opencode   1.14.39" in flat


def test_agent_cli_missing_when_referenced_is_error(tmp_path, monkeypatch):
    """Bug B: missing claude when config references claude-code → [!!]
    and bumps rc."""
    _enable_bundle(monkeypatch, tmp_path)
    monkeypatch.setattr(
        doctor_cmd, "_check_cli",
        lambda binary: {
            str(doctor_cmd.BUNDLE_PYTHON): (True, "Python 3.12.6"),
            str(doctor_cmd.BUNDLE_NODE): (True, "v20.18.0"),
            "lola": (True, "lola 0.4.4"),
        }.get(binary, (False, "not found")),
    )
    monkeypatch.setattr(doctor_cmd, "_read_bundle_promptfoo_version", lambda: "0.121.11")
    monkeypatch.setattr(doctor_cmd, "_VERSIONS_TXT_CANDIDATES", ())

    rc, lines = doctor_cmd._check_bundle_or_path({"claude": "claude-code"})
    flat = "\n".join(lines)
    assert "[!!] claude     (claude-code) not found" in flat
    assert rc == 1


# ---------------------------------------------------------------------------
# Bug C: fixture problems are errors that bump rc, not just warnings
# ---------------------------------------------------------------------------

def test_target_repo_weights_violation_emits_err_and_bumps_rc(tmp_path):
    """Bug C: rubric weights-sum mismatch must yield [ERR] and rc=1 so
    doctor refuses a $5 LLM run with broken fixtures."""
    # Build a minimal target repo
    (tmp_path / "lola-eval.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    case = tmp_path / "tests" / "lola-eval" / "case-001"
    _seed_valid_fixture(case)
    (case / "rubric.md").write_text(
        "---\n"
        "rubric_version: '1'\n"
        "pass_threshold: 0.6\n"
        "weights:\n"
        "  correctness: 1.0\n"
        "  trajectory: 1.0\n"   # sums to 2.0
        "---\n"
    )
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg, err = doctor_cmd._load_target_cfg(cfg_path)
    assert err is None and cfg is not None

    rc, lines = doctor_cmd._check_target_repo(cfg_path, cfg, None)
    flat = "\n".join(lines)
    assert "[ERR]" in flat
    assert "weights sum to 2.000" in flat
    assert rc == 1


def test_target_repo_empty_tests_dir_stays_warn(tmp_path):
    """Bug C: 'no test cases yet' should remain [WARN] (the only fixture-
    related condition that does), not block doctor with [ERR]."""
    (tmp_path / "lola-eval.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    (tmp_path / "tests" / "lola-eval").mkdir(parents=True)
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg, _ = doctor_cmd._load_target_cfg(cfg_path)
    rc, lines = doctor_cmd._check_target_repo(cfg_path, cfg, None)
    flat = "\n".join(lines)
    assert "[WARN]" in flat and "no case directories" in flat
    assert "[ERR]" not in flat
    assert rc == 0


def test_target_repo_missing_task_yaml_is_err(tmp_path):
    """Bug C: a fixture missing task.yaml is an [ERR] that bumps rc."""
    (tmp_path / "lola-eval.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    case = tmp_path / "tests" / "lola-eval" / "case-001"
    case.mkdir(parents=True)  # totally empty case
    cfg_path = tmp_path / "lola-eval.yaml"
    cfg, _ = doctor_cmd._load_target_cfg(cfg_path)
    rc, lines = doctor_cmd._check_target_repo(cfg_path, cfg, None)
    flat = "\n".join(lines)
    assert "[ERR]" in flat and "task.yaml missing" in flat
    assert rc == 1


# ---------------------------------------------------------------------------
# Bug D: runs.db path is project-local inside a target repo
# ---------------------------------------------------------------------------

def test_runs_db_path_is_project_local_inside_target_repo(tmp_path, monkeypatch, capsys):
    """Bug D: doctor prints <target>/<results_dir>/runs.db when invoked
    from inside a target repo — not the XDG state path."""
    import typer
    cfg_text = (
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
        "results_dir: .lola-eval\n"
    )
    (tmp_path / "lola-eval.yaml").write_text(cfg_text)
    (tmp_path / "tests" / "lola-eval").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    # Don't make tests depend on the real bundle.
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PYTHON", Path("/nonexistent/py"))
    monkeypatch.setattr(doctor_cmd, "BUNDLE_NODE", Path("/nonexistent/node"))
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PROMPTFOO", Path("/nonexistent/pf"))

    try:
        doctor_cmd.doctor(config=None)
    except typer.Exit:
        pass
    out = capsys.readouterr().out
    expected = str((tmp_path / ".lola-eval" / "runs.db").resolve())
    assert f"runs.db        -> {expected}" in out
    # The XDG path should not appear as the runs.db line.
    assert "/.local/state/lola-eval/runs.db" not in out


def test_runs_db_path_is_xdg_outside_target_repo(tmp_path, monkeypatch, capsys):
    """Bug D: outside a target repo, runs.db falls back to XDG state."""
    import typer
    from lola_eval import xdg as xdg_mod
    monkeypatch.chdir(tmp_path)  # no lola-eval.yaml here

    monkeypatch.setattr(doctor_cmd, "BUNDLE_PYTHON", Path("/nonexistent/py"))
    monkeypatch.setattr(doctor_cmd, "BUNDLE_NODE", Path("/nonexistent/node"))
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PROMPTFOO", Path("/nonexistent/pf"))

    try:
        doctor_cmd.doctor(config=None)
    except typer.Exit:
        pass
    out = capsys.readouterr().out
    assert f"runs.db        -> {xdg_mod.db_path()}" in out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_read_bundle_promptfoo_version_parses_package_json(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg.json"
    pkg.write_text('{"name":"promptfoo","version":"0.121.11"}')
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PROMPTFOO_PKG", pkg)
    assert doctor_cmd._read_bundle_promptfoo_version() == "0.121.11"


def test_read_bundle_promptfoo_version_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PROMPTFOO_PKG", tmp_path / "nope.json")
    assert doctor_cmd._read_bundle_promptfoo_version() is None


def test_read_bundle_promptfoo_version_returns_none_on_bad_json(tmp_path, monkeypatch):
    pkg = tmp_path / "pkg.json"
    pkg.write_text("{not valid json")
    monkeypatch.setattr(doctor_cmd, "BUNDLE_PROMPTFOO_PKG", pkg)
    assert doctor_cmd._read_bundle_promptfoo_version() is None

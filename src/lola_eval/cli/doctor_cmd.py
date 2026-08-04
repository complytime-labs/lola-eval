"""`lola-eval doctor` -- environment health check (target-aware).

Always checks: bundle integrity (Python, Node, promptfoo), `lola` on
PATH, and the agent CLIs (claude, opencode). When run inside a target
repo (cwd contains lola-eval.yaml), additionally verifies that fixtures
parse and (if regression mode) that baseline.json exists, and tags the
agent CLIs referenced by ``targets:``/``judges:`` with their config
label.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

import typer
import yaml

from lola_eval.cli import app

BUNDLE_PYTHON = Path("/opt/lola-eval/lib/python/bin/python3")
BUNDLE_NODE = Path("/opt/lola-eval/lib/node/bin/node")
BUNDLE_PROMPTFOO = Path("/opt/lola-eval/share/promptfoo")
BUNDLE_PROMPTFOO_PKG = BUNDLE_PROMPTFOO / "node_modules" / "promptfoo" / "package.json"
BUNDLE_PROMPTFOO_BIN = BUNDLE_PROMPTFOO / "node_modules" / ".bin" / "promptfoo"

# CLI name (as used in lola-eval.yaml's `targets:`/`judges:`) → binary on PATH.
_AGENT_CLI_TO_BIN = {"claude-code": "claude", "opencode": "opencode"}

# Candidate locations for ``packaging/versions.txt`` at runtime. The
# bundle path is hypothetical (the file isn't currently shipped in the
# RPM); listing it first keeps the door open for shipping it later
# without changing this code.
_VERSIONS_TXT_CANDIDATES = (
    Path("/opt/lola-eval/share/versions.txt"),
    Path(__file__).resolve().parents[3] / "packaging" / "versions.txt",
)


def _check_cli(cli: str) -> tuple[bool, str]:
    try:
        out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (False, "not found")
    if out.returncode != 0:
        return (False, out.stderr.strip()[:80] or "non-zero exit")
    return (True, out.stdout.strip().splitlines()[0])


def _find_versions_txt() -> Path | None:
    """Return the first existing versions.txt candidate, or ``None``."""
    for p in _VERSIONS_TXT_CANDIDATES:
        if p.is_file():
            return p
    return None


def _parse_versions_txt(path: Path, arch: str) -> dict[str, str]:
    """Tiny [arch]-section INI reader. Returns ``{key: value}`` for the
    requested architecture; an empty dict if the section is absent.

    Mirrors the parser in ``packaging/rpm/build.sh`` so dev/build/runtime
    all read versions.txt the same way.
    """
    in_section = False
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1] == arch
            continue
        if not in_section:
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _extract_version(version_output: str) -> str | None:
    """Extract a semver-ish version from a CLI's --version output.

    Anchored on a `v?` prefix at a word boundary; tolerates trailing
    text. Does NOT match arbitrary dotted numbers later in the string
    (which could be dates, build IDs, etc.).
    """
    m = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", version_output)
    return m.group(1) if m else None


def _read_bundle_promptfoo_version() -> str | None:
    """Return the bundled promptfoo's version from its package.json, or None.

    Reading package.json is cheap and avoids invoking the promptfoo CLI
    (which would spawn Node and dominate doctor's runtime).
    """
    try:
        data = json.loads(BUNDLE_PROMPTFOO_PKG.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    v = data.get("version")
    return v if isinstance(v, str) and v else None


def _bundle_promptfoo_bin_ok() -> bool:
    """True if the bundled promptfoo binary exists and is executable.

    doctor historically only read package.json, which passes even when the
    actual binary the runner needs is absent — the "doctor OK, runtime
    fails" mismatch from #6. This closes that gap with a cheap exists+X_OK
    check (no subprocess spawn, keeping doctor fast).
    """
    return BUNDLE_PROMPTFOO_BIN.exists() and os.access(BUNDLE_PROMPTFOO_BIN, os.X_OK)


def _npx_promptfoo_probe() -> tuple[bool, str]:
    """Probe whether ``npx --no-install promptfoo`` can resolve promptfoo.

    Mirrors the runner's exact PATH fallback (``runner.py``
    ``_resolve_promptfoo_cmd`` → ``npx --no-install promptfoo``). ``--no-install``
    refuses to download in a non-interactive shell, so a bare ``shutil.which('npx')``
    success does NOT mean the runner can obtain promptfoo. Running the same
    invocation here is what turns the silent "doctor OK but every cell
    ``no_run_produced``" mismatch into a loud, actionable doctor failure.

    Returns ``(ok, detail)``: on success ``detail`` is the resolved version;
    on failure it is the decisive error line (npx's own complaint).
    """
    try:
        out = subprocess.run(
            ["npx", "--no-install", "promptfoo", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return (False, "npx not found")
    except subprocess.TimeoutExpired:
        return (False, "npx --no-install promptfoo timed out")
    if out.returncode != 0:
        detail = [ln for ln in (out.stderr or out.stdout).splitlines() if ln.strip()]
        return (False, detail[-1].strip() if detail else "npx --no-install exited non-zero")
    # promptfoo prints an update-nag banner before the version; the version is
    # the final non-empty stdout line.
    stdout_lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    version = _extract_version(stdout_lines[-1]) if stdout_lines else None
    return (True, version or "unknown")


def _read_bundle_promptfoo_node_engine() -> str | None:
    """Return the bundled promptfoo's `engines.node` constraint, or None."""
    try:
        data = json.loads(BUNDLE_PROMPTFOO_PKG.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    engines = data.get("engines") or {}
    n = engines.get("node")
    return n if isinstance(n, str) and n else None


def _semver_tuple(v: str) -> tuple[int, int, int] | None:
    """Parse a semver-ish "X.Y.Z" (or "X.Y") into a tuple; None if unparseable."""
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", v.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _node_satisfies(node_version: str, constraint: str) -> bool | None:
    """Check whether `node_version` satisfies an npm-style `constraint`.

    Supports the subset of npm semver actually used by promptfoo:
      * `^X.Y.Z`  → >= X.Y.Z and < (X+1).0.0
      * `>=X.Y.Z` → >= X.Y.Z
      * `X.Y.Z`   → exact match
      * `A || B`  → satisfies A or B
    Returns ``None`` if the constraint uses an operator we don't model;
    the caller treats None as "couldn't verify" rather than "incompatible".
    """
    nv = _semver_tuple(node_version)
    if nv is None:
        return None
    for clause in constraint.split("||"):
        c = clause.strip()
        if not c:
            continue
        if c.startswith("^"):
            target = _semver_tuple(c[1:])
            if target is None:
                return None
            upper = (target[0] + 1, 0, 0)
            if target <= nv < upper:
                return True
        elif c.startswith(">="):
            target = _semver_tuple(c[2:])
            if target is None:
                return None
            if nv >= target:
                return True
        elif c.startswith(">"):
            target = _semver_tuple(c[1:])
            if target is None:
                return None
            if nv > target:
                return True
        elif re.match(r"\d", c):
            target = _semver_tuple(c)
            if target is None:
                return None
            if nv == target:
                return True
        else:
            return None
    return False


def _check_engines_compatibility(node_msg: str) -> list[str]:
    """Validate bundled Node against promptfoo's `engines.node` constraint.

    Returns a single line — either an [OK] confirmation, a [!!] failure
    that the caller MUST escalate to a non-zero exit code, or an info
    line when we can't determine the answer (no engines field, unknown
    operator, etc.).

    Calling sites: only invoked when the bundle is present, after the
    bundled Node `--version` succeeded. ``node_msg`` is the raw stdout
    of `node --version`.
    """
    constraint = _read_bundle_promptfoo_node_engine()
    if constraint is None:
        return ["  [..] promptfoo engines.node not declared; skipping compat check"]
    node_v = _extract_version(node_msg)
    if node_v is None:
        return [f"  [WARN] could not parse bundled Node version from {node_msg!r}"]
    satisfies = _node_satisfies(node_v, constraint)
    if satisfies is None:
        return [
            f"  [..] promptfoo engines.node='{constraint}' uses an operator we don't model; "
            f"skipping compat check"
        ]
    if satisfies:
        return [f"  [OK] promptfoo engines  node {node_v} satisfies '{constraint}'"]
    return [
        f"  [!!] promptfoo engines  node {node_v} does NOT satisfy '{constraint}'. "
        f"Bundled Node is incompatible with bundled promptfoo — `lola-eval test` will fail. "
        f"Rebuild the RPM with a newer Node in packaging/versions.txt."
    ]


def _check_bundle_or_path(target_cli_labels: dict[str, str]) -> tuple[int, list[str]]:
    """Verify the bundled toolchain at /opt/lola-eval, falling back to PATH.

    When the bundle is present, also compares the bundled Python and Node
    versions against ``packaging/versions.txt`` (I10): mismatch is a
    warning, not a hard error, since it indicates the bundle was built
    against a different version manifest than what's currently checked
    out — a developer concern, not a runtime correctness one.

    Always also checks ``lola``, ``claude``, and ``opencode`` on PATH.
    ``lola`` is required (the bundle does not ship it). The agent CLIs are
    informational by default: a missing CLI that isn't referenced by the
    current target repo's config is ``[..]``, not an error. When a CLI IS
    referenced (``target_cli_labels`` maps binary → cli-name), missing
    becomes ``[!!]`` and bumps rc; present gains a ``(<cli-name>)`` suffix.

    Returns (exit_code_contribution, output_lines).
    """
    lines: list[str] = []
    rc = 0
    bundle_present = BUNDLE_PYTHON.exists() and BUNDLE_NODE.exists() and BUNDLE_PROMPTFOO.exists()
    if bundle_present:
        py_ok, py_msg = _check_cli(str(BUNDLE_PYTHON))
        node_ok, node_msg = _check_cli(str(BUNDLE_NODE))
        pf_version = _read_bundle_promptfoo_version()
        lines.append(
            f"  {'[OK]' if py_ok else '[!!]'} python3    "
            f"{py_msg if py_ok else 'bundled python failed: ' + py_msg} (bundled)"
        )
        lines.append(
            f"  {'[OK]' if node_ok else '[!!]'} node       "
            f"{node_msg if node_ok else 'bundled node failed: ' + node_msg} (bundled)"
        )
        if pf_version is not None:
            if _bundle_promptfoo_bin_ok():
                lines.append(f"  [OK] promptfoo  {pf_version} (bundled, invocable)")
            else:
                lines.append(
                    f"  [!!] promptfoo  {pf_version} present but binary not invocable "
                    f"at {BUNDLE_PROMPTFOO_BIN}. The runner needs this on disk; "
                    f"symlink it into the bundle bin or rebuild the bundle."
                )
                rc = 1
        else:
            lines.append(f"  [!!] promptfoo  package.json unreadable at {BUNDLE_PROMPTFOO_PKG}")
            rc = 1
        if not py_ok or not node_ok:
            rc = max(rc, 1)
        # Engines compat check catches the specific class of bug where a
        # newer promptfoo bumps its required Node and the bundle's pinned
        # Node falls below the floor — release-blocker discovered by a
        # user only when `lola-eval test` crashes on the first row.
        if node_ok and pf_version is not None:
            eng_lines = _check_engines_compatibility(node_msg)
            lines.extend(eng_lines)
            if any("[!!]" in ln for ln in eng_lines):
                rc = max(rc, 1)
        lines.extend(_check_bundle_versions_pinned())
    else:
        lines.append("  [..] bundle missing -- using system PATH (dev mode)")
        for binary in ("python3", "node"):
            ok, msg = _check_cli(binary)
            sigil = "[OK]" if ok else "[!!]"
            lines.append(f"  {sigil} {binary:10s} {msg}")
            if not ok:
                rc = 1
        promptfoo_path = shutil.which("promptfoo")
        if promptfoo_path is not None:
            lines.append(f"  [OK] promptfoo  {promptfoo_path}")
        elif shutil.which("npx") is not None:
            # `npx` on PATH is not enough — the runner uses `--no-install`,
            # which won't download promptfoo in a non-interactive shell.
            # Probe the same command so doctor fails here instead of the run
            # failing every cell with `no_run_produced`.
            ok, detail = _npx_promptfoo_probe()
            if ok:
                lines.append(f"  [OK] promptfoo  (via npx) {detail}")
            else:
                lines.append(
                    f"  [!!] promptfoo  npx cannot resolve promptfoo without a download "
                    f"({detail}). `lola-eval test` will fail every cell with no_run_produced. "
                    f"Install promptfoo (npm i -g promptfoo) or run inside the bundle."
                )
                rc = 1
        else:
            lines.append("  [!!] promptfoo  not on PATH and `npx` unavailable")
            rc = 1

    # `lola` (the pack CLI) is required regardless of bundle presence: it's
    # invoked by orchestrator/install_pack.sh to install/uninstall packs.
    # Bundle does not ship it; user installs it separately.
    ok, msg = _check_cli("lola")
    sigil = "[OK]" if ok else "[!!]"
    lines.append(f"  {sigil} lola       {msg}")
    if not ok:
        rc = max(rc, 1)

    # Agent CLIs: always probed. When referenced by the active config they
    # carry a `(cli-name)` prefix and missing is an error; otherwise they
    # are informational. The label is a *prefix* (between binary and
    # version string) so it stays legible when a CLI's own --version
    # output already contains parenthetical text. Sorted for deterministic
    # output.
    for binary in sorted(_AGENT_CLI_TO_BIN.values()):
        cli_label = target_cli_labels.get(binary)
        ok, msg = _check_cli(binary)
        prefix = f"({cli_label}) " if cli_label else ""
        if ok:
            lines.append(f"  [OK] {binary:10s} {prefix}{msg}")
        elif cli_label is not None:
            lines.append(f"  [!!] {binary:10s} {prefix}{msg}")
            rc = max(rc, 1)
        else:
            lines.append(f"  [..] {binary:10s} {msg} (not referenced by config)")
    return rc, lines


def _check_bundle_versions_pinned() -> list[str]:
    """Compare bundled Python/Node versions against ``versions.txt``.

    Only invoked when the bundle is present. Each mismatch produces a
    ``[WARN]`` line; missing versions.txt produces an ``[..]`` info
    line. Never sets the exit code — see the caller's docstring.
    """
    lines: list[str] = []
    versions_path = _find_versions_txt()
    if versions_path is None:
        lines.append("  [WARN] versions.txt not available; skipping pin check")
        return lines

    arch = platform.machine() or "x86_64"
    pinned = _parse_versions_txt(versions_path, arch)
    expected_python = pinned.get("python_version")
    expected_node = pinned.get("node_version")
    if not expected_python or not expected_node:
        lines.append(
            f"  [WARN] versions.txt has no [{arch}] python/node entries; skipping pin check"
        )
        return lines

    for binary, label, expected in (
        (BUNDLE_PYTHON, "Python", expected_python),
        (BUNDLE_NODE, "Node", expected_node),
    ):
        ok, raw = _check_cli(str(binary))
        if not ok:
            lines.append(f"  [WARN] bundle {label} --version failed: {raw}")
            continue
        actual = _extract_version(raw)
        if actual is None:
            lines.append(f"  [WARN] bundle {label} version unparseable: {raw}")
            continue
        if actual != expected:
            lines.append(
                f"  [WARN] bundle {label} {actual} != pinned {expected} "
                f"(versions.txt; bundle was built against an older manifest)"
            )
        else:
            lines.append(f"  [OK] bundle {label} pin   {actual} matches versions.txt")
    return lines


def _validate_fixture(case_dir: Path) -> list[str]:
    """Return a list of problem strings for one test-case directory.

    Empty list means the fixture is well-formed. Caller surfaces each
    string as a [WARN] line — fixture problems do not change the doctor
    exit code (they're authoring guidance).

    Validates:
      * task.yaml exists and parses; has ``task_version``.
      * prompt.md exists and is non-empty.
      * rubric.md exists, has YAML frontmatter, frontmatter has
        ``rubric_version``, ``pass_threshold``, and ``weights`` summing
        to 1.0 (± 0.001).
      * starter/ exists (may be empty; just needs to be a directory).
    """
    problems: list[str] = []
    label = case_dir.name

    task_yaml = case_dir / "task.yaml"
    if not task_yaml.is_file():
        problems.append(f"{label}: task.yaml missing")
    else:
        try:
            data = yaml.safe_load(task_yaml.read_text()) or {}
            if "task_version" not in data:
                problems.append(f"{label}: task.yaml missing required key 'task_version'")
        except yaml.YAMLError as e:
            problems.append(f"{label}: task.yaml does not parse: {e}")

    prompt = case_dir / "prompt.md"
    if not prompt.is_file():
        problems.append(f"{label}: prompt.md missing")
    elif prompt.stat().st_size == 0:
        problems.append(f"{label}: prompt.md is empty")

    rubric = case_dir / "rubric.md"
    if not rubric.is_file():
        problems.append(f"{label}: rubric.md missing")
    else:
        text = rubric.read_text()
        m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            problems.append(f"{label}: rubric.md missing YAML frontmatter")
        else:
            try:
                fm = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError as e:
                problems.append(f"{label}: rubric.md frontmatter does not parse: {e}")
                fm = None
            if isinstance(fm, dict):
                for key in ("rubric_version", "pass_threshold", "weights"):
                    if key not in fm:
                        problems.append(f"{label}: rubric.md frontmatter missing '{key}'")
                weights = fm.get("weights")
                if isinstance(weights, dict) and weights:
                    total = sum(float(v) for v in weights.values())
                    if abs(total - 1.0) > 0.001:
                        problems.append(
                            f"{label}: rubric.md weights sum to {total:.3f}, expected 1.0 (±0.001)"
                        )

    starter = case_dir / "starter"
    if not starter.is_dir():
        problems.append(f"{label}: starter/ directory missing")

    return problems


def _load_target_cfg(cfg_path: Path):
    """Load a target repo's lola-eval.yaml.

    Returns ``(cfg, error_line)``. On success, ``cfg`` is the parsed
    config and ``error_line`` is ``None``. On parse failure, ``cfg`` is
    ``None`` and ``error_line`` is a pre-formatted ``[!!] ...`` doctor
    line. When ``cfg_path`` does not exist, returns ``(None, None)``.
    """
    if not cfg_path.exists():
        return None, None
    from lola_eval.config import load_config, ConfigError

    try:
        return load_config(cfg_path), None
    except ConfigError as e:
        return None, f"  [!!] {cfg_path} invalid: {e}"


def _target_cli_labels(cfg) -> dict[str, str]:
    """Return ``{binary_name: cli_label}`` for CLIs referenced by cfg.

    Used to tag agent-CLI lines with their config label and to escalate
    missing-CLI from informational to error.
    """
    if cfg is None:
        return {}
    needed = {t.cli for t in cfg.targets} | {j.cli for j in cfg.judges}
    return {_AGENT_CLI_TO_BIN.get(c, c): c for c in needed}


def _check_target_repo(layout, cfg, cfg_error: str | None) -> tuple[int, list[str]]:
    """When run in a target repo, validate fixtures and baseline.

    Agent-CLI probes are handled in ``_check_bundle_or_path`` so they run
    unconditionally; this helper covers only the per-repo concerns:
    fixture well-formedness and baseline existence.

    Fixture problems (missing files, parse errors, weights-sum mismatch)
    are real errors that would break a run — they emit ``[ERR]`` and bump
    rc to 1. An empty tests_dir (``no case directories``) stays a
    ``[WARN]`` since the repo may be mid-bootstrap.
    """
    lines: list[str] = []
    rc = 0
    if cfg_error is not None:
        lines.append(cfg_error)
        return 2, lines
    if cfg is None:
        lines.append("  [..] not in a target repo (no config.yaml); skipping target checks")
        return rc, lines

    test_sets_dir = layout.test_sets_dir
    if not test_sets_dir.is_dir():
        lines.append(f"  [ERR] test_sets/ not found at {test_sets_dir}")
        rc = max(rc, 1)
    else:
        case_dirs = sorted(p for p in test_sets_dir.iterdir() if p.is_dir())
        if not case_dirs:
            lines.append(f"  [WARN] test_sets/ {test_sets_dir} contains no case directories")
        n_problems = 0
        for case_dir in case_dirs:
            problems = _validate_fixture(case_dir)
            if problems:
                rc = max(rc, 1)
                n_problems += len(problems)
                for problem in problems:
                    lines.append(f"  [ERR] {problem}")
        if case_dirs and n_problems == 0:
            n = len(case_dirs)
            lines.append(f"  [OK] test_sets/    {n} case{'s' if n != 1 else ''} validated")

    if cfg.threshold.mode in ("regression", "both"):
        bp = layout.baseline_path
        if bp.exists():
            lines.append(f"  [OK] baseline at        {bp}")
        else:
            lines.append(f"  [!!] baseline missing at {bp} (mode={cfg.threshold.mode})")
            rc = 2
    return rc, lines


@app.command("doctor", rich_help_panel="Setup")
def doctor(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config.yaml (default: ./.lola-eval/config.yaml)",
    ),
) -> None:
    """Check environment health (bundle, CLIs, target repo configuration)."""
    print("== lola-eval doctor ==")

    from lola_eval.layout import resolve as resolve_layout

    try:
        layout = resolve_layout(config_opt=config, out_opt=None)
    except FileNotFoundError:
        layout = None

    cfg_path = layout.config_path if layout is not None else (
        config if config is not None else Path.cwd() / ".lola-eval" / "config.yaml"
    )
    cfg, cfg_error = _load_target_cfg(cfg_path)
    bundle_rc, bundle_lines = _check_bundle_or_path(_target_cli_labels(cfg))
    for ln in bundle_lines:
        print(ln)

    target_rc, target_lines = _check_target_repo(layout, cfg, cfg_error)
    for ln in target_lines:
        print(ln)

    from lola_eval import xdg

    print(f"  [..] XDG_STATE_HOME -> {xdg.state_dir()}")
    print(f"  [..] XDG_CACHE_HOME -> {xdg.cache_dir()}")
    runs_db = (layout.out_root / "runs.db") if layout is not None else xdg.db_path()
    print(f"  [..] runs.db        -> {runs_db}")

    rc = max(bundle_rc, target_rc)
    print(f"\nresult: {'OK' if rc == 0 else 'FAILED'}")
    raise typer.Exit(rc)

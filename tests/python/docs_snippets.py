"""Explicit registry of doc snippets to live-verify.

Each Snippet is one command from README or walkthrough that must keep
working. The test_id is included verbatim in pytest output so a failing
snippet points back to the exact markdown section.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Absolute path to the project root and its venv python.  Used in snippets
# that run from a directory other than the project root (e.g. cwd_is_empty_tmp)
# where relative paths like ".venv/bin/python" would not resolve.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_VENV_PYTHON = str(_PROJECT_ROOT / ".venv" / "bin" / "python")


@dataclass(frozen=True)
class Snippet:
    test_id: str
    doc_file: str          # "README.md" or "docs/walkthrough.md"
    heading: str           # e.g. "Quick start"
    command: list[str]     # argv list
    cwd: Path = Path(".")  # relative to project root, OR ignored when cwd_is_tmp
    cwd_is_tmp: bool = False        # run inside a tmp copy of examples/default/
    cwd_is_empty_tmp: bool = False  # run inside a fresh empty tmp dir (e.g. for init)
    expected_exit: int = 0
    env: dict[str, str] = field(default_factory=dict)


SNIPPETS: list[Snippet] = [
    Snippet(
        test_id="readme-quickstart-help",
        doc_file="README.md",
        heading="Quick start",
        command=[".venv/bin/python", "-m", "lola_eval", "--help"],
        cwd=Path("."),
    ),
    # init: must run in a fresh empty dir so it can write config.yaml without --force.
    # cwd_is_tmp=True would copy examples/default/ first, causing init to refuse.
    # Use the absolute venv python so the executable resolves regardless of cwd.
    Snippet(
        test_id="readme-init-creates-dotdir",
        doc_file="README.md",
        heading="Quick start",
        command=[_VENV_PYTHON, "-m", "lola_eval", "init"],
        cwd_is_empty_tmp=True,
    ),
    # estimate-cost: --config points at examples/default so this works from project root.
    Snippet(
        test_id="readme-estimate-cost",
        doc_file="README.md",
        heading="Cost estimation (`--estimate-cost`)",
        command=[
            ".venv/bin/python", "-m", "lola_eval", "test",
            "--estimate-cost", "--config", "examples/default/.lola-eval/config.yaml",
        ],
        cwd=Path("."),
    ),
    # --cost-per-call flag: verifies the CLI knob documented in the cost estimation section.
    Snippet(
        test_id="readme-estimate-cost-per-call",
        doc_file="README.md",
        heading="Cost estimation (`--estimate-cost`)",
        command=[
            ".venv/bin/python", "-m", "lola_eval", "test",
            "--estimate-cost", "--cost-per-call", "0.50",
            "--config", "examples/default/.lola-eval/config.yaml",
        ],
        cwd=Path("."),
    ),
    # profile-compare --help: verifies the subcommand and its flags are present.
    Snippet(
        test_id="readme-profile-compare-help",
        doc_file="README.md",
        heading="`lola-eval profile-compare`",
        command=[".venv/bin/python", "-m", "lola_eval", "profile-compare", "--help"],
        cwd=Path("."),
    ),
    # export --help: spot-checks the flags documented in the lola-eval export section.
    Snippet(
        test_id="readme-export-help",
        doc_file="README.md",
        heading="`lola-eval export`",
        command=[".venv/bin/python", "-m", "lola_eval", "export", "--help"],
        cwd=Path("."),
    ),
    # transcript-diff --help: live invocations need real run-IDs unavailable in CI;
    # --help is the feasible registry hook for the section.
    Snippet(
        test_id="readme-transcript-diff-help",
        doc_file="README.md",
        heading="`lola-eval transcript-diff <run_a> <run_b>`",
        command=[".venv/bin/python", "-m", "lola_eval", "transcript-diff", "--help"],
        cwd=Path("."),
    ),
    # compare-ref --help: live invocations need real git refs; --help is the registry hook.
    Snippet(
        test_id="readme-compare-ref-help",
        doc_file="README.md",
        heading="`lola-eval compare-ref <ref_a> <ref_b>`",
        command=[".venv/bin/python", "-m", "lola_eval", "compare-ref", "--help"],
        cwd=Path("."),
    ),
    # ------------------------------------------------------------------ #
    # Walkthrough                                                         #
    # ------------------------------------------------------------------ #

    # Step 2: init — must run in a fresh empty dir so it can write config.yaml.
    # Uses absolute venv python so the executable resolves regardless of cwd.
    Snippet(
        test_id="walkthrough-step2-init",
        doc_file="docs/walkthrough.md",
        heading="Step 2: Bootstrap a target project",
        command=[_VENV_PYTHON, "-m", "lola_eval", "init"],
        cwd_is_empty_tmp=True,
    ),
    # Step 4: estimate-cost from a copy of examples/default/ — exercises the
    # "Estimate cost first" step in the walkthrough's example run section.
    Snippet(
        test_id="walkthrough-step4-estimate",
        doc_file="docs/walkthrough.md",
        heading="Step 4: Run the example",
        command=[_VENV_PYTHON, "-m", "lola_eval", "test", "--estimate-cost"],
        cwd_is_tmp=True,
    ),
    # Step 10 / Detecting skill conflicts: profile-compare --help verifies the
    # subcommand and its flags are present.  Live profile-compare runs need a
    # populated runs.db and are covered by task test:profiles instead.
    Snippet(
        test_id="walkthrough-profile-compare-help",
        doc_file="docs/walkthrough.md",
        heading="Detecting skill conflicts",
        command=[".venv/bin/python", "-m", "lola_eval", "profile-compare", "--help"],
        cwd=Path("."),
    ),
]


# Mutual-exclusion guard: cwd_is_tmp (copies examples/default/) and
# cwd_is_empty_tmp (creates a bare tmp dir) cannot both be true — the
# harness branches on cwd_is_empty_tmp first and would silently skip
# the copytree. Validate at import time.
for _s in SNIPPETS:
    assert not (_s.cwd_is_tmp and _s.cwd_is_empty_tmp), (
        f"{_s.test_id}: cwd_is_tmp and cwd_is_empty_tmp are mutually exclusive"
    )

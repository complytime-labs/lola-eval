"""Live-verify documentation snippets against a real fixture.

Each entry in docs_snippets.SNIPPETS is one runnable command pulled
from README.md or docs/walkthrough.md. Failures must point reviewers
to the markdown section that drifted.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.python.docs_snippets import SNIPPETS


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("snippet", SNIPPETS, ids=lambda s: s.test_id)
def test_doc_snippet(snippet, project_root, tmp_path, monkeypatch):
    """Run one documented command against a fixture; assert exit code."""
    if snippet.cwd_is_empty_tmp:
        cwd_root = tmp_path
    elif snippet.cwd_is_tmp:
        cwd_root = tmp_path
        # Copy examples/default/ into tmp so we don't pollute repo state.
        shutil.copytree(project_root / "examples" / "default", tmp_path, dirs_exist_ok=True)
    else:
        cwd_root = project_root / snippet.cwd
    # Default HOME to tmp_path so snippets never touch the developer's real
    # ~/.config or ~/.local state. Snippet-supplied env wins if it sets HOME
    # or PATH explicitly.
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), **snippet.env}
    result = subprocess.run(
        snippet.command,
        cwd=cwd_root,
        env=env,
        capture_output=True,
        text=True,
        # 120s: heavy estimate paths do per-cell kNN over 300+ calibration rows
        timeout=120,
    )
    assert result.returncode == snippet.expected_exit, (
        f"snippet {snippet.test_id!r} from {snippet.doc_file}#{snippet.heading} "
        f"exited {result.returncode} (expected {snippet.expected_exit}):\n"
        f"stdout: {result.stdout[-500:]}\n"
        f"stderr: {result.stderr[-500:]}"
    )

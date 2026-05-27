"""Argv-injection regression test for `compare_ref._worktree`.

The CLI-supplied ref is appended to `git worktree add`; without a `--`
separator a ref like `--upload-pack=...` is parsed as a git flag.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

from lola_eval import compare_ref


def test_worktree_add_inserts_dashdash_before_user_ref(tmp_path, monkeypatch):
    captured: list[list[str]] = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Stub mkdtemp and shutil.rmtree to avoid actual filesystem operations.
    monkeypatch.setattr(
        compare_ref.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "wt-parent")
    )
    monkeypatch.setattr(compare_ref.shutil, "rmtree", lambda path, **kw: None)
    (tmp_path / "wt-parent").mkdir()
    (tmp_path / "wt-parent" / "worktree").mkdir()

    hostile_ref = "--upload-pack=/tmp/payload.sh"
    # The context manager will succeed with our stubbed subprocess calls.
    # We just care about verifying the argv before it's passed to git.
    with compare_ref._worktree(tmp_path, hostile_ref):
        pass

    add_cmds = [c for c in captured if c[:4] == ["git", "-C", str(tmp_path), "worktree"]]
    assert add_cmds, f"expected a git worktree invocation, got: {captured}"
    add_cmd = add_cmds[0]
    assert "--" in add_cmd, f"argv missing -- separator: {add_cmd}"
    assert add_cmd.index("--") < add_cmd.index(hostile_ref), (
        f"`--` must precede the user-controlled ref: {add_cmd}"
    )

"""Argv-injection regression test for `runner._stage_starters`.

CVE-2017-1000117 class: if a `git clone` argv places a user-controlled URL
without a `--` end-of-options marker, a URL like `--upload-pack=...` is
parsed as a git flag and can execute attacker-controlled code.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import yaml

from lola_eval import runner


def test_stage_starters_inserts_dashdash_before_user_url(tmp_path, monkeypatch):
    case_dir = tmp_path / "case-001"
    case_dir.mkdir()
    (case_dir / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "starter_url": "--upload-pack=/tmp/payload.sh",
                "starter_ref": "main",
            }
        )
    )

    captured: list[list[str]] = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner._stage_starters([case_dir], tmp_path / "results")

    clone_cmds = [c for c in captured if c[:2] == ["git", "clone"]]
    assert clone_cmds, f"expected a git clone invocation, got: {captured}"
    cmd = clone_cmds[0]
    assert "--" in cmd, f"argv missing -- separator: {cmd}"
    assert cmd.index("--") < cmd.index("--upload-pack=/tmp/payload.sh"), (
        f"`--` must precede the user-controlled URL: {cmd}"
    )

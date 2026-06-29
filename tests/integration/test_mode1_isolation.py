"""End-to-end integration tests for Mode-1 isolated provisioning.

Drives the real ``install_pack.sh`` against the real ``lola`` CLI using the
``tests/fixtures/module-mini`` fixture and asserts three isolation invariants:

1. Project scope installs skills into workdir, restores the instruction file
   without any injected context.
2. User scope installs skills into ``$HOME/.claude``, leaves no ``CLAUDE.md``
   there, and leaves the workdir entirely untouched.
3. None / no-install baseline: the workdir is identical to the starter tree
   (install_pack.sh is never called for the ``none`` pack_id; this test
   emulates that by skipping the call and diffing the trees).

Requires ``lola`` on PATH; skipped otherwise.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL_PACK = REPO / "src/lola_eval/_data/orchestrator/install_pack.sh"
FIXTURE_MODULE = REPO / "tests/fixtures/module-mini"

pytestmark = pytest.mark.skipif(
    shutil.which("lola") is None, reason="requires real lola CLI"
)


def _run(pack, scope, workdir, home, cli="claude-code"):
    env = {
        **os.environ,
        "HOME": str(home),
        "LOLA_MODULE_SOURCE": str(FIXTURE_MODULE),
        "LOLA_INSTALL_SCOPE": scope,
    }
    return subprocess.run(
        ["bash", str(INSTALL_PACK), pack, cli, str(workdir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_project_scope_installs_and_restores(tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "CLAUDE.md").write_text("# starter ctx\n")
    home = tmp_path / "home"
    home.mkdir()
    r = _run("project", "project", wd, home)
    assert r.returncode == 0, r.stderr
    assert (wd / ".claude/skills/demo/SKILL.md").exists()        # skills installed
    assert (wd / "CLAUDE.md").read_text() == "# starter ctx\n"   # instruction file restored
    assert "lola:module" not in (wd / "CLAUDE.md").read_text()   # no injected context


def test_user_scope_isolated_to_home(tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir()
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    r = _run("project-user", "user", wd, home)
    assert r.returncode == 0, r.stderr
    assert (home / ".claude/skills/demo/SKILL.md").exists()  # user-scope install present
    assert not (home / ".claude/CLAUDE.md").exists()         # injected file removed
    assert not (wd / ".claude").exists()                     # workdir untouched


def test_none_is_bare(tmp_path):
    # Two things must hold for the baseline: the provider never calls
    # install_pack.sh for "none" (so a copied starter is unchanged), AND
    # install_pack.sh itself is a genuine no-op for "none" even when a
    # module_source is configured (its early exit must not touch anything).
    starter = tmp_path / "starter"
    starter.mkdir()
    (starter / "src.py").write_text("x = 1\n")
    wd = tmp_path / "wd"
    shutil.copytree(starter, wd)
    home = tmp_path / "home"
    home.mkdir()

    # Invoke the real script with pack_id=none and a module_source set: it must
    # exit 0 and leave the workdir byte-identical to the starter.
    r = _run("none", "project", wd, home)
    assert r.returncode == 0, r.stderr
    diff = subprocess.run(
        ["diff", "-r", str(starter), str(wd)],
        capture_output=True,
        text=True,
    )
    assert diff.returncode == 0, diff.stdout

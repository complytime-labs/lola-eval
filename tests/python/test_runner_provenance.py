"""runner._git_provenance reads git metadata from the source repo."""

from __future__ import annotations

import subprocess

from lola_eval.runner import _git_provenance


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_git_provenance_reads_sha_and_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    _git(repo, "remote", "add", "origin", "git@example.com:me/repo.git")
    (repo / "f.txt").write_text("hi")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "init")

    prov = _git_provenance(repo)
    assert len(prov["sha"]) == 40
    assert prov["branch"] == "main"
    assert prov["remote"] == "git@example.com:me/repo.git"


def test_git_provenance_non_repo_returns_none(tmp_path):
    prov = _git_provenance(tmp_path)
    assert prov["sha"] is None
    assert prov["branch"] is None
    assert prov["remote"] is None


def test_git_provenance_detached_head_records_HEAD(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("1")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "c1")
    first = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "b.txt").write_text("2")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "c2")
    _git(repo, "checkout", first)  # detached HEAD
    prov = _git_provenance(repo)
    assert prov["branch"] == "HEAD"
    assert prov["sha"] == first

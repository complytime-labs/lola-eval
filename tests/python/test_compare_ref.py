"""compare-ref: worktree-based two-ref evaluation diff."""

from __future__ import annotations

import subprocess as _sp

import pytest

from lola_eval import compare_ref as cr
from lola_eval.compare_ref import _render_ref_diff


def test_render_ref_diff_shows_per_cell_deltas():
    a = {"claude-code/sonnet/case-001/project": 0.80}
    b = {"claude-code/sonnet/case-001/project": 0.92}
    text = _render_ref_diff("main", "HEAD", a, b)
    assert "main" in text and "HEAD" in text
    assert "0.80" in text and "0.92" in text
    assert "+0.12" in text


def test_render_ref_diff_handles_cells_missing_on_one_side():
    a = {"cellX": 0.5}
    b = {"cellY": 0.7}
    text = _render_ref_diff("a", "b", a, b)
    assert "cellX" in text and "cellY" in text
    # Missing-side cells render a dash for value and delta, no crash.
    assert "-" in text


def _git(cwd, *args):
    _sp.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo_with_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    (repo / "marker.txt").write_text("v1")
    _git(repo, "add", "marker.txt")
    _git(repo, "commit", "-m", "c1")
    return repo


def test_worktree_materializes_ref_and_cleans_up(tmp_path):
    repo = _repo_with_commit(tmp_path)
    head_before = _sp.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    seen = {}
    with cr._worktree(repo, "HEAD") as wt:
        assert wt.exists()
        assert (wt / "marker.txt").read_text() == "v1"  # ref materialized
        seen["wt"] = wt
    # After the context: worktree dir removed, registration gone, main repo untouched.
    assert not seen["wt"].exists()
    listed = _sp.run(
        ["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True
    ).stdout
    assert str(seen["wt"]) not in listed
    head_after = _sp.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    assert head_after == head_before  # non-destructive


def test_worktree_cleans_up_on_exception(tmp_path):
    repo = _repo_with_commit(tmp_path)
    captured = {}
    with pytest.raises(RuntimeError):
        with cr._worktree(repo, "HEAD") as wt:
            captured["wt"] = wt
            raise RuntimeError("boom")
    assert not captured["wt"].exists()


def test_compare_refs_diffs_two_ref_evals(tmp_path, monkeypatch):
    repo = _repo_with_commit(tmp_path)

    # Never run a real matrix: stub _eval_at_ref to return different scores per ref.
    def stub_at_ref(repo_root, ref, config_rel, **kw):
        return {"claude-code/sonnet/case-001/project": 0.80 if ref == "main" else 0.95}

    monkeypatch.setattr(cr, "_eval_at_ref", stub_at_ref)
    text = cr.compare_refs(repo, "main", "HEAD", "lola-eval.yaml")
    assert "main" in text and "HEAD" in text
    assert "+0.15" in text


def test_eval_at_ref_uses_config_dir_as_eval_dir(tmp_path, monkeypatch):
    """Regression: when the config lives in a subdir (e.g. evaldir/.lola-eval/),
    the layout's eval_dir must be that .lola-eval/ directory — not the worktree
    root — so test_sets_dir and profiles_dir resolve correctly."""
    from lola_eval import runner as _runner

    repo = _repo_with_commit(tmp_path)
    sub = repo / "evaldir" / ".lola-eval"
    sub.mkdir(parents=True)
    (sub / "config.yaml").write_text(
        "targets:\n  - cli: claude-code\n    models: [sonnet]\n"
        "judges:\n  - {cli: claude-code, model: sonnet}\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add evaldir config")

    captured = {}

    def fake_run_matrix(cfg, layout, **kw):
        captured["layout"] = layout
        return []

    monkeypatch.setattr(_runner, "run_matrix", fake_run_matrix)
    cr._eval_at_ref(repo, "HEAD", "evaldir/.lola-eval/config.yaml")
    assert captured["layout"].eval_dir.name == ".lola-eval", captured["layout"].eval_dir
    assert captured["layout"].eval_dir.parent.name == "evaldir", captured["layout"].eval_dir

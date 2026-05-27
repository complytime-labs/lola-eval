"""Regression test for finding #6: compare-ref must not leak runs.db into
the persistent XDG state dir; ephemeral state lives inside the worktree
and is removed with the worktree.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from lola_eval import compare_ref


def test_eval_at_ref_routes_out_root_into_worktree(tmp_path, monkeypatch):
    """resolve_layout must receive an out_opt pointing inside the worktree;
    no XDG state dir is created.
    """
    fake_xdg = tmp_path / "xdg-state"
    fake_xdg.mkdir()
    # Patch xdg.state_dir so any escape would land in our tmp dir.
    from lola_eval import xdg as xdg_mod
    monkeypatch.setattr(xdg_mod, "state_dir", lambda: fake_xdg)

    # Capture the out_opt passed to resolve_layout.
    captured_kwargs: dict = {}

    def fake_resolve(*, config_opt, out_opt=None):
        captured_kwargs["config_opt"] = config_opt
        captured_kwargs["out_opt"] = out_opt
        # Return a stub layout that has the bare attrs the caller might touch.
        layout = MagicMock()
        layout.eval_dir = Path(config_opt).parent
        layout.out_root = Path(out_opt) if out_opt else fake_xdg
        return layout

    monkeypatch.setattr("lola_eval.layout.resolve", fake_resolve)
    # Stub out the worktree context manager AND runner.run_matrix so the test
    # doesn't actually clone or run anything.
    fake_wt = tmp_path / "fake-worktree"
    fake_wt.mkdir()
    (fake_wt / ".lola-eval").mkdir()
    (fake_wt / ".lola-eval" / "config.yaml").touch()

    import contextlib
    @contextlib.contextmanager
    def fake_worktree(repo_root, ref):
        yield fake_wt

    monkeypatch.setattr(compare_ref, "_worktree", fake_worktree)

    # Stub load_config and runner.run_matrix.
    from lola_eval import runner as runner_mod
    monkeypatch.setattr("lola_eval.config.load_config", lambda p: MagicMock())
    monkeypatch.setattr(runner_mod, "run_matrix", lambda *a, **kw: [])

    compare_ref._eval_at_ref(tmp_path, "HEAD", ".lola-eval/config.yaml")

    out_opt = captured_kwargs.get("out_opt")
    assert out_opt is not None, "compare_ref must pass an explicit out_opt to resolve_layout"
    out_opt_path = Path(out_opt)
    assert out_opt_path == fake_wt / ".lola-eval-cmpref-out", (
        f"out_opt must be {fake_wt / '.lola-eval-cmpref-out'!s}, got {out_opt_path}"
    )
    # XDG was never written to.
    assert list(fake_xdg.rglob("*")) == [], (
        f"XDG state dir must remain empty, found: {list(fake_xdg.rglob('*'))}"
    )

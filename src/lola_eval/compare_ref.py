"""Evaluate the repo at two git refs and diff per-cell composites (#1).

Non-destructive: each ref is checked out into a throwaway `git worktree`,
evaluated, and removed. The caller's branch and working tree are never
touched. This is the worktree-based replacement for the stash/checkout
dance described in IMPROVEMENTS.md #1.

Public surface: `compare_refs` (orchestrator), `_render_ref_diff`
(renderer), and `CompareRefError` (raised when a worktree cannot be
created). Each ref is run through the FULL configured matrix (every
pack/profile cell); only `case_filter` narrows the run in this version.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator


def _render_ref_diff(
    ref_a: str,
    ref_b: str,
    a: dict[str, float | None],
    b: dict[str, float | None],
) -> str:
    """Render a per-cell composite diff table between two refs."""
    cells = sorted(set(a) | set(b))
    lines = [f"compare-ref: {ref_a} -> {ref_b}", ""]
    lines.append(f"| Cell | {ref_a} | {ref_b} | delta |")
    lines.append("| --- | --- | --- | --- |")
    for cell in cells:
        va = a.get(cell)
        vb = b.get(cell)
        sa = f"{va:.2f}" if va is not None else "-"
        sb = f"{vb:.2f}" if vb is not None else "-"
        delta = f"{vb - va:+.2f}" if (va is not None and vb is not None) else "-"
        lines.append(f"| {cell} | {sa} | {sb} | {delta} |")
    return "\n".join(lines) + "\n"


class CompareRefError(RuntimeError):
    pass


@contextlib.contextmanager
def _worktree(repo_root: Path, ref: str) -> Iterator[Path]:
    """Materialize `ref` in a throwaway detached git worktree.

    Yields the worktree path. On exit (success OR exception) the worktree
    is removed and its temp parent deleted, so the caller's main tree and
    branch are never modified.
    """
    parent = Path(tempfile.mkdtemp(prefix="lola-eval-cmpref-"))
    wt = parent / "worktree"
    add = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "--detach", str(wt), ref],
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        shutil.rmtree(parent, ignore_errors=True)
        raise CompareRefError(
            f"git worktree add failed for ref '{ref}': {add.stderr.strip()[:300]}"
        )
    try:
        yield wt
    finally:
        subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(wt)],
            capture_output=True,
            text=True,
            check=False,
        )
        shutil.rmtree(parent, ignore_errors=True)


def _eval_at_ref(
    repo_root: Path,
    ref: str,
    config_rel: str,
    *,
    case_filter: str | None = None,
    concurrency: int | None = None,
) -> dict[str, float | None]:
    """Run the eval matrix at `ref` in a worktree; return {cell_key: composite}.

    The matrix runs in full at the ref (all packs/profiles); `case_filter`
    is the only narrowing exposed here. Results land in the worktree's own
    `.lola-eval/` and are discarded with the worktree, so the caller's
    results directory is never written.
    """
    from lola_eval.config import load_config
    from lola_eval import runner

    with _worktree(repo_root, ref) as wt:
        cfg_path = wt / config_rel
        cfg = load_config(cfg_path)
        # target_root is the config's directory (matching `lola-eval test`,
        # which uses cfg_path.parent), NOT the worktree root — cfg.tests_dir /
        # results_dir are resolved relative to it.
        rows = runner.run_matrix(
            cfg,
            cfg_path.parent,
            case_filter=case_filter,
            concurrency=concurrency,
        )
        return {r.cell_key: r.composite for r in rows}


def compare_refs(
    repo_root: Path,
    ref_a: str,
    ref_b: str,
    config_rel: str,
    *,
    case_filter: str | None = None,
    concurrency: int | None = None,
) -> str:
    """Evaluate `ref_a` and `ref_b` and render their per-cell composite diff."""
    a = _eval_at_ref(repo_root, ref_a, config_rel, case_filter=case_filter, concurrency=concurrency)
    b = _eval_at_ref(repo_root, ref_b, config_rel, case_filter=case_filter, concurrency=concurrency)
    return _render_ref_diff(ref_a, ref_b, a, b)

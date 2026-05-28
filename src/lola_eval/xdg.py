"""XDG Base Directory resolution for the harness.

Resolves XDG_STATE_HOME / XDG_CACHE_HOME / XDG_CONFIG_HOME (or their
spec defaults), all namespaced under 'lola-eval'. Directories are
created on first access — the caller never has to mkdir.

The embeddable-runner pivot keeps eval results inside each target repo
(under ``<target>/.lola-eval/``) instead of the per-user XDG state, so
that two CI projects sharing a runner host never commingle results.
The XDG path remains as a Phase-1 fallback when no target-aware
override is in scope (e.g. ad-hoc ``lola-eval drift`` outside a repo,
or older standalone tests that pre-date the pivot).
"""

from __future__ import annotations

import os
from pathlib import Path

NAMESPACE = "lola-eval"


def _resolve(env_var: str, default_subpath: str) -> Path:
    base = os.environ.get(env_var)
    if base:
        root = Path(base)
    else:
        root = Path(os.environ.get("HOME", str(Path.home()))) / default_subpath
    p = root / NAMESPACE
    p.mkdir(parents=True, exist_ok=True)
    return p


def state_dir() -> Path:
    return _resolve("XDG_STATE_HOME", ".local/state")


def cache_dir() -> Path:
    return _resolve("XDG_CACHE_HOME", ".cache")


def config_dir() -> Path:
    return _resolve("XDG_CONFIG_HOME", ".config")


def _sub(parent: Path, name: str) -> Path:
    p = parent / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def transcripts_dir() -> Path:
    return _sub(state_dir(), "transcripts")


def diffs_dir() -> Path:
    return _sub(state_dir(), "diffs")


def logs_dir() -> Path:
    return _sub(state_dir(), "logs")


def reports_dir() -> Path:
    return _sub(state_dir(), "reports")


def work_dir() -> Path:
    return _sub(cache_dir(), "work")


def packs_cache_dir() -> Path:
    return _sub(cache_dir(), "packs")


def db_path() -> Path:
    return state_dir() / "runs.db"


def resolve_db_path() -> Path:
    """Resolve the SQLite database path for the current invocation.

    Resolution order:
      1. ``LOLA_DB_PATH`` env var (set explicitly).
      2. ``LOLA_RESULTS_DIR`` env var → ``<results_dir>/runs.db`` (set by
         the runner so promptfoo subprocesses inherit a target-relative
         path).
      3. Phase-1 XDG fallback: ``<XDG_STATE_HOME>/lola-eval/runs.db``.

    Used by ``trajectory_judge``, ``runner._collect_rows``, ``report``,
    ``compare``, and ``graph`` so all five share one resolution rule.
    Subcommands that hold a resolved ``Layout`` should prefer
    ``layout.out_root / "runs.db"`` for directness.
    """
    explicit = os.environ.get("LOLA_DB_PATH")
    if explicit:
        return Path(explicit)
    results_dir = os.environ.get("LOLA_RESULTS_DIR")
    if results_dir:
        return Path(results_dir) / "runs.db"
    return db_path()



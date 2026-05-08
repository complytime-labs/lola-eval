"""Skill drift harness."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lola-eval")
except PackageNotFoundError:
    # Source-tree fallback (no `pip install -e .` yet). Read pyproject.toml
    # so the dev-mode value tracks the canonical declaration instead of
    # drifting silently as a hard-coded string. This branch should not run
    # in the shipped RPM.
    from pathlib import Path
    try:
        import tomllib
    except ImportError:  # Python < 3.11; lola-eval requires >= 3.11 in
        # pyproject, so this is defensive against an exotic dev setup.
        tomllib = None
    _pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
    if tomllib is not None and _pyproject.exists():
        __version__ = tomllib.loads(_pyproject.read_text())["project"]["version"]
    else:
        __version__ = "0.0.0+unknown"

__all__ = ["__version__"]

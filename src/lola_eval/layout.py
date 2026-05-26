"""Resolve the consolidated ``.lola-eval/`` directory layout.

One place owns the dir structure and the local-vs-XDG out-root rule:

  <eval_dir>/                 the .lola-eval directory (config's parent)
    config.yaml               the chosen config file
    test_sets/                committed cases
    profiles/                 committed profile YAMLs + skill modules
    baseline.json             committed regression state
    out/                      gitignored artifacts (LOCAL mode only)

Out-root is local (``<eval_dir>/out``) when the eval dir lives inside the
current working directory; otherwise it is the per-user XDG state path
(``xdg.state_dir()/targets/<key>``), so driving a foreign repo's eval
definition never writes into that foreign checkout.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from lola_eval import xdg

DEFAULT_EVAL_DIRNAME = ".lola-eval"
DEFAULT_CONFIG_NAME = "config.yaml"


@dataclass(frozen=True)
class Layout:
    config_path: Path
    eval_dir: Path
    project_root: Path
    test_sets_dir: Path
    profiles_dir: Path
    baseline_path: Path
    out_root: Path
    is_external: bool


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _external_out_root(project_root: Path) -> Path:
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()[:12]
    key = f"{project_root.name}-{digest}"
    return xdg.state_dir() / "targets" / key


def resolve(config_opt: Path | None, out_opt: Path | None) -> Layout:
    """Resolve the layout for one invocation.

    ``config_opt`` is the ``--config`` value (a path to a config file) or
    ``None`` to use ``./.lola-eval/config.yaml``. ``out_opt`` forces the
    out-root regardless of mode. Raises ``FileNotFoundError`` (with an
    init hint) when the config file does not exist.
    """
    cwd = Path.cwd().resolve()
    if config_opt is None:
        config_path = cwd / DEFAULT_EVAL_DIRNAME / DEFAULT_CONFIG_NAME
    else:
        config_path = Path(config_opt)
        if not config_path.is_absolute():
            config_path = cwd / config_path
        # User slip: passing the eval dir (e.g. ``--config .lola-eval``) instead
        # of the config file. Auto-redirect to ``<dir>/config.yaml`` so the
        # intent works rather than silently misrouting to the dir's parent.
        if config_path.is_dir():
            config_path = config_path / DEFAULT_CONFIG_NAME
    config_path = config_path.resolve()
    if not config_path.exists():
        raise FileNotFoundError(
            f"config not found at {config_path}; run `lola-eval init` to scaffold "
            f"a .lola-eval/ directory"
        )
    if not config_path.is_file():
        raise FileNotFoundError(
            f"config path is not a file: {config_path}"
        )

    eval_dir = config_path.parent
    project_root = eval_dir.parent
    is_external = not _is_inside(eval_dir, cwd)

    if out_opt is not None:
        out_root = Path(out_opt)
        if not out_root.is_absolute():
            out_root = cwd / out_root
        out_root = out_root.resolve()
    elif is_external:
        out_root = _external_out_root(project_root)
    else:
        out_root = eval_dir / "out"

    return Layout(
        config_path=config_path,
        eval_dir=eval_dir,
        project_root=project_root,
        test_sets_dir=eval_dir / "test_sets",
        profiles_dir=eval_dir / "profiles",
        baseline_path=eval_dir / "baseline.json",
        out_root=out_root,
        is_external=is_external,
    )

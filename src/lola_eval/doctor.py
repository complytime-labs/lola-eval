"""harness doctor: environment health check + clean helpers."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from lola_eval import xdg


def _check_cli(cli: str) -> tuple[bool, str]:
    try:
        out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (False, "not found")
    if out.returncode != 0:
        return (False, out.stderr.strip()[:80] or "non-zero exit")
    return (True, out.stdout.strip().splitlines()[0])


def _ephemeral_home_warning() -> str | None:
    home = Path(os.environ.get("HOME", ""))
    if "XDG_STATE_HOME" in os.environ:
        return None
    try:
        mounts = Path("/proc/self/mountinfo").read_text()
    except Exception:
        return None
    if str(home) in mounts and "bind" in mounts:
        return None
    if "/workspace" in mounts and str(home) not in mounts.split("/workspace")[0]:
        return (
            f"$HOME ({home}) appears non-persistent in this container. "
            f"Set XDG_STATE_HOME=/workspace/.xdg-state to keep drift history across rebuilds."
        )
    return None


def run() -> int:
    print("== harness doctor ==")
    rc = 0

    for cli in ("claude", "opencode", "lola"):
        ok, msg = _check_cli(cli)
        sigil = "[OK]" if ok else "[!!]"
        print(f"  {sigil} {cli:10s} {msg}")
        if not ok and cli != "lola":
            rc = 1
        elif not ok and cli == "lola":
            print("        (lola is required for non-baseline rows; install via: uv tool install lola-ai)")
            rc = 1

    print(f"  [..] XDG_STATE_HOME -> {xdg.state_dir()}")
    print(f"  [..] XDG_CACHE_HOME -> {xdg.cache_dir()}")
    print(f"  [..] XDG_CONFIG_HOME-> {xdg.config_dir()}")
    print(f"  [..] runs.db        -> {xdg.db_path()}")

    warn = _ephemeral_home_warning()
    if warn:
        print(f"  [WARN] {warn}")

    print(f"\nresult: {'OK' if rc == 0 else 'FAILED'}")
    return rc


def clean_dirs(*, cache: bool = False, state: bool = False,
               target_results_dir: Path | None = None) -> None:
    """Wipe cache or state directories.

    When ``target_results_dir`` is supplied (i.e. the CLI was invoked
    inside a target repo), the wipes operate on that directory:

      * ``cache=True`` removes ``workspace/``, ``transcripts/``, ``reports/``
      * ``state=True`` removes ``runs.db`` and ``last-run.json``
        (``baseline.json`` is preserved — the user committed it)

    Without ``target_results_dir`` we keep the Phase-1 standalone
    behavior of wiping the XDG cache / state roots wholesale.
    """
    if target_results_dir is not None:
        if cache:
            for sub in ("workspace", "transcripts", "reports"):
                d = target_results_dir / sub
                if d.exists():
                    print(f"wiping {d}")
                    shutil.rmtree(d)
        if state:
            for name in ("runs.db", "last-run.json"):
                f = target_results_dir / name
                if f.exists():
                    print(f"wiping {f}")
                    f.unlink()
        return

    if cache:
        d = xdg.cache_dir()
        print(f"wiping {d}")
        if d.exists():
            shutil.rmtree(d)
    if state:
        d = xdg.state_dir()
        print(f"wiping {d}")
        if d.exists():
            shutil.rmtree(d)

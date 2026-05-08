"""lola-eval CLI -- typer entrypoint with one module per subcommand."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path

import typer

app = typer.Typer(
    name="lola-eval",
    help="Embeddable agent eval runner for lola packs.",
    no_args_is_help=True,
    # Pin prog_name so all `--help` and error output reads as `lola-eval`
    # whether invoked via the wrapper script (/opt/lola-eval/bin/lola-eval),
    # the /usr/bin/lola-eval symlink, or `python -m lola_eval` in dev mode.
    # Without this, `python -m` invocations leak the module path into help.
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _main() -> None:  # pragma: no cover - thin wrapper
    """Module entrypoint that pins the Click ``prog_name`` so help and
    usage strings always read as ``lola-eval``, regardless of how Python
    was invoked.

    Used by ``__main__.py``. In RPM installs this also runs (the wrapper
    script does ``python3 -m lola_eval``); pinning prog_name here means
    we don't depend on the wrapper to set it.
    """
    app(prog_name="lola-eval")


def _version_callback(value: bool) -> None:
    """Eager --version handler: prints and exits 0 before any subcommand runs."""
    if value:
        from lola_eval import __version__
        typer.echo(f"lola-eval {__version__}")
        raise typer.Exit(0)


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the lola-eval version and exit.",
    ),
) -> None:
    """Top-level entrypoint; --version is the only flag here."""


@contextlib.contextmanager
def _activate_target_env(config_path: Path | None = None):
    """Context manager: scope ``LOLA_RESULTS_DIR`` to one CLI invocation.

    If invoked inside a target repo (cwd contains ``lola-eval.yaml``,
    or ``config_path`` resolves to a valid file), export
    ``LOLA_RESULTS_DIR`` so read-only subcommands (``compare``,
    ``graph``, ``drift``, ``lift``, ``report``) and the runner's
    promptfoo subprocess pick up the per-target results directory.

    Restores the prior environment on exit so consecutive CLI calls
    inside the same Python process (tests, REPL drivers, embedders)
    don't leak state across boundaries.

    Yields the resolved config path on success, ``None`` if no
    ``lola-eval.yaml`` was found.
    """
    cfg_path = config_path or (Path.cwd() / "lola-eval.yaml")
    sentinel = object()
    prior = os.environ.get("LOLA_RESULTS_DIR", sentinel)
    yielded: Path | None = None

    if cfg_path.exists():
        from lola_eval.config import load_config, ConfigError
        try:
            cfg = load_config(cfg_path)
            target_root = cfg_path.parent.resolve()
            os.environ["LOLA_RESULTS_DIR"] = str(target_root / cfg.results_dir)
            yielded = cfg_path
        except ConfigError:
            # Invalid config: don't mutate env; let the caller surface
            # the error via load_config when it tries to load again.
            pass

    try:
        yield yielded
    finally:
        if prior is sentinel:
            os.environ.pop("LOLA_RESULTS_DIR", None)
        else:
            os.environ["LOLA_RESULTS_DIR"] = prior

# Subcommand modules register themselves on import.
from lola_eval.cli import (  # noqa: F401, E402
    init_cmd,
    test_cmd,
    baseline_cmd,
    doctor_cmd,
    compare_cmd,
    graph_cmd,
    report_cmd,
    drift_cmd,
    lift_cmd,
    clean_cmd,
)

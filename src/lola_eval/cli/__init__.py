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
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the lola-eval version and exit.",
    ),
) -> None:
    """Top-level entrypoint; --version is the only flag here."""


def _resolve_layout_or_exit(config: Path | None, out: Path | None = None):
    """Resolve the :class:`~lola_eval.layout.Layout` for an invocation, or
    exit 2 with a setup error.

    Shared by every subcommand that previously hand-rolled
    ``cfg_path.parent`` math. ``config`` is the ``--config`` value (a path
    to a config file, or ``None`` for ``./.lola-eval/config.yaml``);
    ``out`` forces the out-root.
    """
    from lola_eval.layout import resolve

    try:
        return resolve(config_opt=config, out_opt=out)
    except FileNotFoundError as e:
        typer.echo(f"setup error: {e}", err=True)
        raise typer.Exit(2)


@contextlib.contextmanager
def _activate_target_env(layout=None):
    """Context manager: scope ``LOLA_RESULTS_DIR`` to one CLI invocation.

    Subcommands resolve a :class:`~lola_eval.layout.Layout` first and pass
    it here; ``LOLA_RESULTS_DIR`` is set to ``layout.out_root`` so the
    runner's promptfoo subprocess and read-only readers (``compare``,
    ``graph``, ``drift``, ``lift``, ``report``) share one out-root.
    Passing ``None`` (e.g. a read-only command run outside any eval dir)
    is a no-op.

    Restores the prior environment on exit so consecutive in-process CLI
    calls (tests, REPL drivers, embedders) don't leak state.
    """
    sentinel = object()
    prior = os.environ.get("LOLA_RESULTS_DIR", sentinel)
    if layout is not None:
        os.environ["LOLA_RESULTS_DIR"] = str(layout.out_root)
    try:
        yield layout
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
    compare_ref_cmd,
    graph_cmd,
    report_cmd,
    snapshot_cmd,
    drift_cmd,
    lift_cmd,
    clean_cmd,
    export_cmd,
    transcript_diff_cmd,
    profile_compare_cmd,
    predict_cmd,
)

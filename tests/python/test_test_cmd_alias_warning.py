"""The `test` command surfaces unpinned-alias warnings before running."""
from __future__ import annotations

from typer.testing import CliRunner

from lola_eval.cli import app


def test_alias_warning_shown_on_estimate(tmp_path):
    cfg = tmp_path / "lola-eval.yaml"
    cfg.write_text(
        "targets:\n"
        "  - cli: claude-code\n"
        "    models: [sonnet]\n"
        "judges:\n"
        "  - {cli: claude-code, model: sonnet}\n"
    )
    result = CliRunner().invoke(app, ["test", "--estimate-cost", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "unpinned alias" in result.output

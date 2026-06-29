"""_repair_results_provider_identity rewrites row provider identity in results.json.

promptfoo (<= 0.121.17) serializes every result row's top-level ``provider``
from the top-level providers list (our single placeholder) instead of the
per-test provider override that actually ran, and never populates the
row-level ``description``. The true values survive under each row's
``testCase``. See BUG.md.
"""

from __future__ import annotations

import json

from lola_eval import runner


def _results_file(tmp_path, rows):
    """Write a minimal promptfoo v3 --output file and return its path."""
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                "evalId": "eval-test",
                "results": {"version": 3, "results": rows, "stats": {}},
                "config": {},
            }
        )
    )
    return path


def _row(tc_provider, tc_description):
    return {
        "provider": {"id": "claude-code", "label": "claude-code:claude-sonnet-4-6"},
        "testCase": {
            "provider": tc_provider,
            "description": tc_description,
            "vars": {"target_cli": "opencode"},
        },
        "vars": {"target_cli": "opencode"},
        "success": True,
    }


def test_repair_copies_provider_identity_and_description_from_testcase(tmp_path):
    path = _results_file(
        tmp_path,
        [
            _row({"id": "claude-code", "label": "claude-code:claude-sonnet-4-6"}, "row A"),
            _row({"id": "opencode", "label": "opencode:claude-sonnet-4-6"}, "row B"),
        ],
    )

    runner._repair_results_provider_identity(path)

    data = json.loads(path.read_text())
    rows = data["results"]["results"]
    assert rows[0]["provider"] == {
        "id": "claude-code",
        "label": "claude-code:claude-sonnet-4-6",
    }
    assert rows[1]["provider"] == {
        "id": "opencode",
        "label": "opencode:claude-sonnet-4-6",
    }
    assert rows[0]["description"] == "row A"
    assert rows[1]["description"] == "row B"
    assert data["_lola_eval_provider_repair"] is True


def test_repair_is_idempotent(tmp_path):
    path = _results_file(
        tmp_path,
        [_row({"id": "opencode", "label": "opencode:claude-sonnet-4-6"}, "row B")],
    )

    runner._repair_results_provider_identity(path)
    first = path.read_text()
    runner._repair_results_provider_identity(path)

    assert path.read_text() == first


def test_repair_skips_rows_without_testcase_provider(tmp_path):
    intact = _row({"id": "opencode", "label": "opencode:claude-sonnet-4-6"}, "good row")
    broken = _row(None, None)
    del broken["testCase"]
    path = _results_file(tmp_path, [broken, intact])

    runner._repair_results_provider_identity(path)

    rows = json.loads(path.read_text())["results"]["results"]
    # Row without testCase keeps whatever promptfoo wrote.
    assert rows[0]["provider"]["id"] == "claude-code"
    assert "description" not in rows[0]
    # The well-formed row is still repaired.
    assert rows[1]["provider"]["id"] == "opencode"
    assert rows[1]["description"] == "good row"


def test_repair_warns_and_preserves_file_on_corrupt_json(tmp_path, capsys):
    path = tmp_path / "results.json"
    path.write_text("{not json")

    runner._repair_results_provider_identity(path)

    assert path.read_text() == "{not json"
    err = capsys.readouterr().err
    assert "[lola-eval-runner]" in err
    assert "repair" in err

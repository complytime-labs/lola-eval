# src/lola_eval/calibration_verify.py
"""Strict integrity check for the bundled calibration JSONL.

Verifies: sha256 sidecar matches; each line is valid JSON; each row
parses to a CalibrationRow. Raises CalibrationError on any failure.
"""

from __future__ import annotations

import hashlib
import sys

from lola_eval.calibration import (
    CalibrationError,
    _data_dir,
    _parse_jsonl,
)


def verify() -> str:
    """Return a status string. Raise CalibrationError on failure."""
    pkg = _data_dir()
    body = pkg.joinpath("runs.jsonl").read_bytes()
    expected = pkg.joinpath("runs.jsonl.sha256").read_text().strip()
    actual = hashlib.sha256(body).hexdigest()
    if expected != actual:
        raise CalibrationError(
            f"calibration snapshot sha256 mismatch: expected {expected}, got {actual}. "
            f"Run `task calibration:update` to refresh."
        )
    rows = _parse_jsonl(body)
    raw_lines = [ln for ln in body.decode().splitlines() if ln.strip()]
    if len(rows) != len(raw_lines):
        raise CalibrationError(
            f"calibration parse mismatch: {len(rows)} parseable rows, "
            f"{len(raw_lines)} non-empty lines. Some rows malformed."
        )
    return f"[calibration:verify] OK ({actual}, {len(rows)} rows)"


def main():
    try:
        print(verify())
    except CalibrationError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

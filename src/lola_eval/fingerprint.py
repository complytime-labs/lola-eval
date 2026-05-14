"""Row identity fingerprint.

The fingerprint anchors drift comparison. Two rows with the same
fingerprint can be compared; rows with different fingerprints can not.
It is a stable, content-addressed hash of the inputs that define a row's
identity, omitting the free variables that drift measures (target_model,
judge_model, run_timestamp).

CHANGING THIS ALGORITHM BREAKS HISTORICAL DRIFT COMPARISONS. The golden
vector test in tests/python/test_fingerprint.py guards against accidental
change.
"""
from __future__ import annotations

import hashlib
from typing import NamedTuple

VALID_TARGET_CLIS = frozenset({"claude-code", "opencode"})
VALID_EXEC_MODES = frozenset({"autonomous", "interactive"})
VALID_INVOCATION_STYLES = frozenset({"passive", "active"})


class FingerprintInput(NamedTuple):
    target_cli: str
    pack_id: str
    task_id: str
    task_version: str
    rubric_version: str
    exec_mode: str
    invocation_style: str
    profile_id: str = "none"


def compute(inp: FingerprintInput) -> str:
    if inp.target_cli not in VALID_TARGET_CLIS:
        raise ValueError(f"target_cli must be one of {sorted(VALID_TARGET_CLIS)}")
    if inp.exec_mode not in VALID_EXEC_MODES:
        raise ValueError(f"exec_mode must be one of {sorted(VALID_EXEC_MODES)}")
    if inp.invocation_style not in VALID_INVOCATION_STYLES:
        raise ValueError(f"invocation_style must be one of {sorted(VALID_INVOCATION_STYLES)}")

    payload = "\x1f".join([
        inp.target_cli,
        inp.pack_id,
        inp.task_id,
        inp.task_version,
        inp.rubric_version,
        inp.exec_mode,
        inp.invocation_style,
        inp.profile_id,
    ]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

"""Row identity hashing.

Fingerprint must be stable across machines forever (golden vector test
locks the algorithm). Any change forces a deliberate decision: rotate
fingerprints + bump rubric_version. Pack identity uses the resolved
SHA, not the version tag — see spec Section 4.
"""
from __future__ import annotations
import pytest

from lola_eval.fingerprint import compute, FingerprintInput


GOLDEN_INPUT = FingerprintInput(
    target_cli="claude-code",
    pack_id="none",
    task_id="case-001-fix-bug",
    task_version="1",
    rubric_version="1",
    exec_mode="autonomous",
    invocation_style="passive",
)
# Pinned in Step 4 — DO NOT REGENERATE without a deliberate fingerprint rotation.
GOLDEN_OUTPUT = "74d014c916bbf80cb95e6ad034c65c9e0edc0e9a9e1e70c50f2c6d5037f6861f"


def test_golden_vector_stable():
    """Locks the algorithm. CHANGING THIS BREAKS DRIFT HISTORY."""
    assert compute(GOLDEN_INPUT) == GOLDEN_OUTPUT


def test_changing_target_cli_changes_fingerprint():
    a = compute(GOLDEN_INPUT)
    b = compute(GOLDEN_INPUT._replace(target_cli="opencode"))
    assert a != b


def test_changing_pack_id_changes_fingerprint():
    a = compute(GOLDEN_INPUT)
    b = compute(GOLDEN_INPUT._replace(pack_id="example@deadbeef"))
    assert a != b


def test_changing_rubric_version_changes_fingerprint():
    a = compute(GOLDEN_INPUT)
    b = compute(GOLDEN_INPUT._replace(rubric_version="2"))
    assert a != b


def test_changing_invocation_changes_fingerprint():
    a = compute(GOLDEN_INPUT)
    b = compute(GOLDEN_INPUT._replace(invocation_style="active"))
    assert a != b


def test_target_model_NOT_in_fingerprint():
    """target_model is the FREE VARIABLE drift measures over.
    It MUST NOT be part of the fingerprint."""
    compute(GOLDEN_INPUT)  # smoke: should not crash
    assert "target_model" not in GOLDEN_INPUT._fields


def test_judge_model_NOT_in_fingerprint():
    """Same logic — judge_model is metadata, not identity."""
    assert "judge_model" not in GOLDEN_INPUT._fields


def test_invalid_exec_mode_rejected():
    with pytest.raises(ValueError):
        compute(GOLDEN_INPUT._replace(exec_mode="bogus"))


def test_invalid_invocation_style_rejected():
    with pytest.raises(ValueError):
        compute(GOLDEN_INPUT._replace(invocation_style="bogus"))


def test_invalid_target_cli_rejected():
    with pytest.raises(ValueError):
        compute(GOLDEN_INPUT._replace(target_cli="bogus"))


def test_profile_id_changes_fingerprint():
    base = FingerprintInput(
        target_cli="claude-code", pack_id="none", task_id="case-001",
        task_version="1", rubric_version="1", exec_mode="autonomous",
        invocation_style="passive", profile_id="none",
    )
    with_profile = base._replace(profile_id="superpowers")
    assert compute(base) != compute(with_profile)


def test_profile_id_none_default():
    fp = FingerprintInput(
        target_cli="claude-code", pack_id="none", task_id="case-001",
        task_version="1", rubric_version="1", exec_mode="autonomous",
        invocation_style="passive",
    )
    assert fp.profile_id == "none"
    h = compute(fp)
    assert len(h) == 64

"""Tests for the bundled-pricing module."""

from __future__ import annotations

import hashlib
import json

import pytest

from lola_eval import pricing


def _make_snapshot(models: dict) -> bytes:
    """Build a minimal valid models.dev shape and return its bytes."""
    body = json.dumps({"anthropic": {"models": models}}).encode("utf-8")
    return body


def test_bundled_snapshot_loads_and_has_anthropic():
    """Smoke test: the real bundled snapshot parses and exposes a familiar
    anthropic model id with non-zero rates and token ceilings."""
    pricing._load_bundled.cache_clear()
    p = pricing.lookup("claude-sonnet-4-6")
    assert p is not None
    assert p.input_per_mtok_usd > 0
    assert p.output_per_mtok_usd > 0
    assert p.input_token_ceiling > 0
    assert p.output_token_ceiling > 0


def test_lookup_unknown_model_returns_none():
    pricing._load_bundled.cache_clear()
    assert pricing.lookup("no-such-model-id-1234567") is None


def test_verify_and_build_parses_minimal_shape():
    body = _make_snapshot(
        {
            "test-model-1": {
                "cost": {"input": 3.0, "output": 15.0},
                "limit": {"context": 200000, "output": 64000},
            }
        }
    )
    sha = hashlib.sha256(body).hexdigest()
    out = pricing._verify_and_build(body, sha)
    assert "test-model-1" in out
    m = out["test-model-1"]
    assert m.input_per_mtok_usd == 3.0
    assert m.output_per_mtok_usd == 15.0
    # input_token_ceiling = context - output (true input upper bound when
    # the output budget is reserved)
    assert m.input_token_ceiling == 200000 - 64000
    assert m.output_token_ceiling == 64000


def test_sha256_mismatch_raises_with_actionable_message():
    body = _make_snapshot({"x": {"cost": {"input": 1, "output": 2}, "limit": {"context": 1000, "output": 100}}})
    with pytest.raises(pricing.PricingError) as exc:
        pricing._verify_and_build(body, "0" * 64)
    msg = str(exc.value)
    assert "integrity check failed" in msg
    assert "task pricing:update" in msg


def test_models_without_cost_data_are_skipped():
    body = _make_snapshot(
        {
            "model-priced": {
                "cost": {"input": 1.0, "output": 2.0},
                "limit": {"context": 100, "output": 50},
            },
            "model-no-cost": {
                "cost": {},
                "limit": {"context": 100, "output": 50},
            },
            "model-zero-cost": {
                "cost": {"input": 0, "output": 0},
                "limit": {"context": 100, "output": 50},
            },
        }
    )
    sha = hashlib.sha256(body).hexdigest()
    out = pricing._verify_and_build(body, sha)
    assert "model-priced" in out
    assert "model-no-cost" not in out
    assert "model-zero-cost" not in out


def test_canonical_provider_wins_over_reseller():
    """Multiple providers re-list the same model id at different rates. The
    authoritative owner (e.g. anthropic for claude-*) must win."""
    body = json.dumps(
        {
            "qihang-ai": {
                "models": {
                    "claude-test-1": {
                        "cost": {"input": 0.14, "output": 0.71},
                        "limit": {"context": 200000, "output": 64000},
                    }
                }
            },
            "anthropic": {
                "models": {
                    "claude-test-1": {
                        "cost": {"input": 1.0, "output": 5.0},
                        "limit": {"context": 200000, "output": 64000},
                    }
                }
            },
        }
    ).encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    out = pricing._verify_and_build(body, sha)
    assert out["claude-test-1"].input_per_mtok_usd == 1.0
    assert out["claude-test-1"].output_per_mtok_usd == 5.0


def test_bundled_haiku_rates_match_anthropic_not_reseller():
    """Regression: confirm against the real bundled snapshot. Anthropic lists
    claude-haiku-4-5-20251001 at $1/$5; an obscure reseller lists it at
    $0.14/$0.71. The lookup must return anthropic's authoritative number."""
    pricing._load_bundled.cache_clear()
    m = pricing.lookup("claude-haiku-4-5-20251001")
    assert m is not None
    assert m.input_per_mtok_usd == 1.0, m
    assert m.output_per_mtok_usd == 5.0, m


def test_snapshot_sha256_matches_recorded_file():
    """The recorded sha256 must match the actual bytes — i.e. the snapshot
    and its attestation are consistent."""
    pkg = pricing._data_dir()
    body = pkg.joinpath("models.json").read_bytes()
    recorded = pricing.snapshot_sha256()
    assert hashlib.sha256(body).hexdigest() == recorded


def _write_external(tmp_path, models, *, sidecar=True, bad_sha=False):
    """Write a tmp pricing file, optionally with a sha256 sidecar."""
    body = json.dumps({"anthropic": {"models": models}}).encode("utf-8")
    f = tmp_path / "ext.json"
    f.write_bytes(body)
    if sidecar:
        sha = "0" * 64 if bad_sha else hashlib.sha256(body).hexdigest()
        (tmp_path / "ext.json.sha256").write_text(sha + "\n")
    return f


def test_resolver_external_wins_over_bundled(tmp_path):
    """External-file rates override bundled rates for matching ids."""
    f = _write_external(
        tmp_path,
        {
            "claude-haiku-4-5-20251001": {
                "cost": {"input": 0.50, "output": 2.50},  # negotiated half-price
                "limit": {"context": 200000, "output": 64000},
            }
        },
    )
    r = pricing.Resolver(external_path=f)
    res = r.lookup("claude-haiku-4-5-20251001")
    assert res.source == "external"
    assert res.pricing.input_per_mtok_usd == 0.50


def test_resolver_bundled_fills_in_models_external_lacks(tmp_path):
    """An external file with one model still benefits from the bundle
    for everything else."""
    f = _write_external(
        tmp_path,
        {
            "my-private-model": {
                "cost": {"input": 1.0, "output": 5.0},
                "limit": {"context": 1000, "output": 500},
            }
        },
    )
    r = pricing.Resolver(external_path=f)
    # External-only model resolves from external.
    assert r.lookup("my-private-model").source == "external"
    # Snapshot model still resolves from bundled.
    res = r.lookup("claude-sonnet-4-6")
    assert res.source == "bundled"
    assert res.pricing.input_per_mtok_usd > 0


def test_resolver_sidecar_mismatch_drops_external_gracefully(tmp_path):
    """A sha256 sidecar present but wrong → external silently disabled,
    diagnostic populated, bundled still works."""
    f = _write_external(
        tmp_path,
        {
            "claude-haiku-4-5-20251001": {
                "cost": {"input": 0.01, "output": 0.05},
                "limit": {"context": 200000, "output": 64000},
            }
        },
        bad_sha=True,
    )
    r = pricing.Resolver(external_path=f)
    assert r.external_diag.error is not None
    assert "sha256 mismatch" in r.external_diag.error
    assert r.external == {}
    # Falls through to bundled — original anthropic rates intact.
    res = r.lookup("claude-haiku-4-5-20251001")
    assert res.source == "bundled"
    assert res.pricing.input_per_mtok_usd == 1.0


def test_resolver_missing_external_is_graceful(tmp_path):
    """Pointing at a non-existent file populates the diagnostic but
    doesn't crash; bundled still resolves."""
    r = pricing.Resolver(external_path=tmp_path / "nope.json")
    assert r.external_diag.error and "not found" in r.external_diag.error
    assert r.lookup("claude-sonnet-4-6").source == "bundled"


def test_resolver_malformed_external_is_graceful(tmp_path):
    """Invalid JSON in the external file → diagnostic, not an exception."""
    f = tmp_path / "ext.json"
    f.write_bytes(b"{not json")
    r = pricing.Resolver(external_path=f)
    assert r.external_diag.error and "invalid JSON" in r.external_diag.error
    assert r.lookup("claude-sonnet-4-6").source == "bundled"


def test_resolver_fuzzy_matches_via_family_field():
    """The query 'sonnet' should land on a claude-sonnet-* model from the
    bundle by family field, picking the most recent release_date."""
    r = pricing.Resolver()
    res = r.lookup("sonnet")
    assert res.source == "fuzzy-bundled"
    assert "sonnet" in res.matched_id.lower()
    assert res.pricing is not None


def test_resolver_fuzzy_picks_latest_release_date(tmp_path):
    """Among matches, pick the candidate with the highest release_date."""
    body = json.dumps(
        {
            "anthropic": {
                "models": {
                    "claude-sonnet-2020": {
                        "family": "claude-sonnet",
                        "release_date": "2020-01-01",
                        "cost": {"input": 1, "output": 1},
                        "limit": {"context": 100, "output": 10},
                    },
                    "claude-sonnet-2024": {
                        "family": "claude-sonnet",
                        "release_date": "2024-12-01",
                        "cost": {"input": 2, "output": 2},
                        "limit": {"context": 100, "output": 10},
                    },
                }
            }
        }
    ).encode("utf-8")
    f = tmp_path / "ext.json"
    f.write_bytes(body)
    (tmp_path / "ext.json.sha256").write_text(hashlib.sha256(body).hexdigest())
    r = pricing.Resolver(external_path=f)
    # Use a query that misses bundled (so fuzzy lands in the external file).
    res = r.lookup("claude-sonnet")
    assert res.source == "fuzzy-external"
    assert res.matched_id == "claude-sonnet-2024"


def test_resolver_unknown_model_returns_explicit_unknown_source():
    r = pricing.Resolver()
    res = r.lookup("totally-fake-model-id-zzz")
    assert res.pricing is None
    assert res.source == "unknown"


def test_bundled_load_diagnostics_have_sha_when_healthy():
    pricing._load_bundled.cache_clear()
    _, diag = pricing._load_bundled()
    assert diag.error is None
    assert diag.sha256
    assert diag.sha_verified is True

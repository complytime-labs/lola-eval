"""Per-model pricing pulled from the bundled models.dev snapshot, with
optional override from a user-supplied file.

The bundled snapshot ships at ``src/lola_eval/_data/pricing/models.json``
with a companion ``models.json.sha256`` attestation. Refresh via
``task pricing:update``; verify integrity via ``task pricing:verify``.
No network access at runtime.

Users can point at an external file via ``cost_estimate.pricing_file``
in ``config.yaml`` — same shape as the bundled snapshot. When the
external file is present it merges with the bundle, **external wins on
collision**, so a small corp-maintained file (5 models, your negotiated
rates) overrides those models while the bundle covers everything else.

Lookups are exact first; on miss they fall back to a best-effort fuzzy
match on the ``family`` field and id substring, picking the candidate
with the latest release date. Callers must surface the guess with the
``(≈ <matched-id>, guessed from "<query>")`` annotation so the user can
see when the heuristic fired.

Errors loading either file (missing, malformed, sha256 mismatch) are
captured in :class:`LoadDiagnostics` rather than raised. Callers can
surface them in their own output without exploding the user's terminal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True)
class ModelPricing:
    """Upper-bound pricing inputs for one model."""

    model_id: str
    input_per_mtok_usd: float
    output_per_mtok_usd: float
    # ``limit.context - limit.output``: largest possible input window when
    # the output budget is reserved.
    input_token_ceiling: int
    # ``limit.output``: max output tokens per turn.
    output_token_ceiling: int
    # Family + release_date drive fuzzy matching ("sonnet" → most recent
    # family=claude-sonnet entry). Empty strings when source data omits them.
    family: str = ""
    release_date: str = ""


@dataclass
class LoadDiagnostics:
    """Why a pricing source did or didn't load."""

    path: Path | None = None
    sha256: str | None = None
    error: str | None = None
    sha_verified: bool = False


class PricingError(RuntimeError):
    """Raised only by the verify subcommand. The runtime loader captures
    errors into :class:`LoadDiagnostics` instead."""


_CANONICAL_PROVIDERS = (
    "anthropic",
    "openai",
    "google",
    "google-vertex",
    "google-vertex-anthropic",
    "amazon-bedrock",
    "azure",
    "mistral",
    "groq",
    "cohere",
    "deepseek",
    "openrouter",
)


def _data_dir():
    return files("lola_eval").joinpath("_data").joinpath("pricing")


def _entry(model_id: str, model: dict) -> ModelPricing | None:
    cost = model.get("cost") or {}
    limit = model.get("limit") or {}
    try:
        input_rate = float(cost.get("input", 0) or 0)
        output_rate = float(cost.get("output", 0) or 0)
        context = int(limit.get("context", 0) or 0)
        output_limit = int(limit.get("output", 0) or 0)
    except (TypeError, ValueError):
        return None
    if input_rate == 0 and output_rate == 0:
        return None
    return ModelPricing(
        model_id=model_id,
        input_per_mtok_usd=input_rate,
        output_per_mtok_usd=output_rate,
        input_token_ceiling=max(context - output_limit, 0),
        output_token_ceiling=output_limit,
        family=str(model.get("family") or ""),
        release_date=str(model.get("release_date") or model.get("last_updated") or ""),
    )


def _parse(data: dict) -> dict[str, ModelPricing]:
    """Walk the models.dev shape into a flat ``{model_id: ModelPricing}``.
    Canonical providers are processed first with first-write-wins so
    obscure resellers can't clobber authoritative rates."""
    out: dict[str, ModelPricing] = {}

    def absorb(provider):
        if not isinstance(provider, dict):
            return
        models = provider.get("models") or {}
        if not isinstance(models, dict):
            return
        for model_id, model in models.items():
            if model_id in out or not isinstance(model, dict):
                continue
            entry = _entry(model_id, model)
            if entry is not None:
                out[model_id] = entry

    for prov_id in _CANONICAL_PROVIDERS:
        absorb(data.get(prov_id))
    for prov_id, provider in data.items():
        if prov_id in _CANONICAL_PROVIDERS:
            continue
        absorb(provider)
    return out


def _verify_and_build(body: bytes, expected_sha: str) -> dict[str, ModelPricing]:
    """Strict verify-and-parse used by ``task pricing:verify`` and the
    test suite. Raises :class:`PricingError` on mismatch."""
    actual = hashlib.sha256(body).hexdigest()
    if expected_sha and expected_sha != actual:
        raise PricingError(
            f"snapshot integrity check failed: expected sha256 {expected_sha}, "
            f"got {actual}. Run `task pricing:update` to refresh."
        )
    return _parse(json.loads(body))


def _load_file(json_path: Path) -> tuple[dict[str, ModelPricing], LoadDiagnostics]:
    """Load a snapshot file gracefully. Sha256 sidecar (``<file>.sha256``)
    is honored when present. Returns an empty map + a populated
    :class:`LoadDiagnostics` on any failure rather than raising."""
    diag = LoadDiagnostics(path=json_path)
    try:
        body = json_path.read_bytes()
    except FileNotFoundError:
        diag.error = f"file not found: {json_path}"
        return {}, diag
    except OSError as e:
        diag.error = f"could not read {json_path}: {e}"
        return {}, diag

    diag.sha256 = hashlib.sha256(body).hexdigest()
    sidecar = json_path.with_suffix(json_path.suffix + ".sha256")
    if sidecar.exists():
        try:
            expected = sidecar.read_text().strip()
        except OSError as e:
            diag.error = f"could not read sha256 sidecar {sidecar}: {e}"
            return {}, diag
        if expected and expected != diag.sha256:
            diag.error = (
                f"sha256 mismatch for {json_path}: expected {expected}, got {diag.sha256}"
            )
            return {}, diag
        diag.sha_verified = True

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        diag.error = f"invalid JSON in {json_path}: {e}"
        return {}, diag
    return _parse(data), diag


@lru_cache(maxsize=1)
def _load_bundled() -> tuple[dict[str, ModelPricing], LoadDiagnostics]:
    pkg = _data_dir()
    try:
        body = pkg.joinpath("models.json").read_bytes()
        expected = pkg.joinpath("models.json.sha256").read_text().strip()
    except (FileNotFoundError, OSError) as e:
        return {}, LoadDiagnostics(error=f"bundled pricing snapshot unavailable: {e}")
    diag = LoadDiagnostics(sha256=hashlib.sha256(body).hexdigest())
    if expected and expected != diag.sha256:
        diag.error = (
            f"bundled snapshot sha256 mismatch: expected {expected}, got {diag.sha256}. "
            f"Run `task pricing:update` to refresh."
        )
        return {}, diag
    diag.sha_verified = bool(expected)
    try:
        return _parse(json.loads(body)), diag
    except json.JSONDecodeError as e:
        diag.error = f"bundled snapshot is malformed JSON: {e}"
        return {}, diag


def _fuzzy_lookup(query: str, table: dict[str, ModelPricing]) -> ModelPricing | None:
    """Best-effort match on family field, falling back to id substring.
    Among candidates, prefer the one with the highest release_date (ISO
    dates sort lexicographically). Caller MUST annotate the guess."""
    q = query.lower().strip()
    if not q:
        return None
    family_matches = [p for p in table.values() if q in p.family.lower()]
    id_matches = [p for p in table.values() if q in p.model_id.lower()]
    candidates = family_matches or id_matches
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.release_date, p.model_id))


@dataclass(frozen=True)
class Resolution:
    """One lookup's result + provenance for source-tagging in output."""

    pricing: ModelPricing | None
    # One of: "external", "bundled", "fuzzy-external", "fuzzy-bundled",
    # "unknown". When fuzzy, ``pricing.model_id`` is the matched id (not
    # the user's query).
    source: str
    matched_id: str = ""  # set when source starts with "fuzzy-"


class Resolver:
    """Stateful pricing lookup that combines an optional external file
    with the bundled snapshot. Build one per CLI invocation."""

    def __init__(self, external_path: Path | None = None):
        self.bundled, self.bundled_diag = _load_bundled()
        if external_path is not None:
            self.external, self.external_diag = _load_file(external_path)
        else:
            self.external, self.external_diag = {}, LoadDiagnostics()

    def lookup(self, model_id: str) -> Resolution:
        if model_id in self.external:
            return Resolution(self.external[model_id], "external")
        if model_id in self.bundled:
            return Resolution(self.bundled[model_id], "bundled")
        if (m := _fuzzy_lookup(model_id, self.external)) is not None:
            return Resolution(m, "fuzzy-external", m.model_id)
        if (m := _fuzzy_lookup(model_id, self.bundled)) is not None:
            return Resolution(m, "fuzzy-bundled", m.model_id)
        return Resolution(None, "unknown")


def lookup(model_id: str) -> ModelPricing | None:
    """Convenience: exact lookup against the bundled snapshot only. Used
    by tests; production code uses :class:`Resolver`."""
    return _load_bundled()[0].get(model_id)


def snapshot_sha256() -> str:
    """The sha256 of the bundled snapshot, or empty when unavailable."""
    _, diag = _load_bundled()
    return diag.sha256 or ""

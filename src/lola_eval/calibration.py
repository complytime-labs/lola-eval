"""Empirical token/cost/duration data, captured per-row from runs.db,
shipped as a bundled JSONL with sha256 attestation.

Mirrors :mod:`lola_eval.pricing` in shape on purpose: bundled snapshot
plus optional external override; LoadDiagnostics over exceptions;
``task X:update`` / ``task X:verify`` pair. One mental model, two
snapshots.

Three-tier degradation when ``--estimate-cost`` consults this module:
  1. exact match by (target_model, pack_id, task_id, profile_id, exec_mode)
     → ``[calibrated: n=N, median ±spread]``
  2. else if --predict and target_family has >=k neighbors → ``[predicted: knn-k=3]``
  3. else → fall through to pricing.Resolver

All cost values returned by this module are re-priced using current
:func:`lola_eval.pricing.compute` against archived tokens, never the
archived ``cost_usd`` field (which is informational only — rates drift,
model behavior does not).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class CalibrationRow:
    """One row in the calibration JSONL. Subset of runs.db.runs columns."""
    run_id: str
    timestamp: str                  # ISO-8601, used for dedup last-write-wins
    target_cli: str
    target_cli_ver: str             # analytical only; NOT part of lookup key
    target_model: str
    target_family: str              # pricing.Resolver-derived at insert time
    pack_id: str
    task_id: str
    profile_id: str
    exec_mode: str                  # "project" or "none"
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    turns: int
    tool_calls_count: int
    duration_s: float
    cost_usd: float                 # target-side only; archival


@dataclass
class LoadDiagnostics:
    """Why a calibration source did or didn't load."""
    path: Path | None = None
    sha256: str | None = None
    error: str | None = None
    sha_verified: bool = False
    row_count: int = 0


class CalibrationError(RuntimeError):
    """Raised only by the verify subcommand. The runtime loader captures
    errors into :class:`LoadDiagnostics` instead."""


_REQUIRED_FIELDS = (
    "run_id", "timestamp", "target_cli", "target_cli_ver", "target_model",
    "target_family", "pack_id", "task_id", "profile_id", "exec_mode",
    "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_creation_tokens", "turns", "tool_calls_count", "duration_s",
    "cost_usd",
)


def _data_dir():
    return files("lola_eval").joinpath("_data").joinpath("calibration")


def _parse_row(d: dict) -> CalibrationRow | None:
    """Strict parse: return None if any required field is missing or
    cannot be coerced to its expected type. Caller logs the drop."""
    try:
        for f in _REQUIRED_FIELDS:
            if f not in d:
                return None
        return CalibrationRow(
            run_id=str(d["run_id"]),
            timestamp=str(d["timestamp"]),
            target_cli=str(d["target_cli"]),
            target_cli_ver=str(d["target_cli_ver"]),
            target_model=str(d["target_model"]),
            target_family=str(d["target_family"]),
            pack_id=str(d["pack_id"]),
            task_id=str(d["task_id"]),
            profile_id=str(d["profile_id"]),
            exec_mode=str(d["exec_mode"]),
            input_tokens=int(d["input_tokens"]),
            output_tokens=int(d["output_tokens"]),
            cache_read_tokens=int(d["cache_read_tokens"]),
            cache_creation_tokens=int(d["cache_creation_tokens"]),
            turns=int(d["turns"]),
            tool_calls_count=int(d["tool_calls_count"]),
            duration_s=float(d["duration_s"]),
            cost_usd=float(d["cost_usd"]),
        )
    except (TypeError, ValueError):
        return None


def _parse_jsonl(body: bytes) -> list[CalibrationRow]:
    """Parse a JSONL body. Malformed/invalid rows are dropped silently;
    the caller surfaces row_count vs expected via LoadDiagnostics."""
    out: list[CalibrationRow] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        row = _parse_row(d)
        if row is not None:
            out.append(row)
    return out


def _load_file(json_path: Path) -> tuple[list[CalibrationRow], LoadDiagnostics]:
    diag = LoadDiagnostics(path=json_path)
    try:
        body = json_path.read_bytes()
    except FileNotFoundError:
        diag.error = f"file not found: {json_path}"
        return [], diag
    except OSError as e:
        diag.error = f"could not read {json_path}: {e}"
        return [], diag

    diag.sha256 = hashlib.sha256(body).hexdigest()
    sidecar = json_path.with_suffix(json_path.suffix + ".sha256")
    if sidecar.exists():
        try:
            expected = sidecar.read_text().strip()
        except OSError as e:
            diag.error = f"could not read sha256 sidecar {sidecar}: {e}"
            return [], diag
        if expected and expected != diag.sha256:
            diag.error = f"sha256 mismatch for {json_path}: expected {expected}, got {diag.sha256}"
            return [], diag
        diag.sha_verified = True

    rows = _parse_jsonl(body)
    diag.row_count = len(rows)
    return rows, diag


@lru_cache(maxsize=1)
def _load_bundled() -> tuple[list[CalibrationRow], LoadDiagnostics]:
    pkg = _data_dir()
    try:
        body = pkg.joinpath("runs.jsonl").read_bytes()
        expected = pkg.joinpath("runs.jsonl.sha256").read_text().strip()
    except (FileNotFoundError, OSError) as e:
        return [], LoadDiagnostics(error=f"bundled calibration unavailable: {e}")
    diag = LoadDiagnostics(sha256=hashlib.sha256(body).hexdigest())
    if expected and expected != diag.sha256:
        diag.error = (
            f"bundled snapshot sha256 mismatch: expected {expected}, got {diag.sha256}. "
            f"Run `task calibration:update` to refresh."
        )
        return [], diag
    diag.sha_verified = bool(expected)
    rows = _parse_jsonl(body)
    diag.row_count = len(rows)
    return rows, diag


@dataclass(frozen=True)
class CalibrationLookup:
    """Result of an exact-key calibration lookup.

    The estimator re-prices tokens with CURRENT rates using
    :func:`lola_eval.pricing.compute` — ``median_cost_usd`` is archival
    only and surfaced for users who explicitly ask for the raw row.
    """
    rows: list[CalibrationRow]
    median_input_tokens: int
    median_output_tokens: int
    median_duration_s: float
    median_cost_usd: float          # archival
    spread_cost_usd: float          # max - min of cost_usd; "spread" label not "IQR" — see spec
    n: int


def _dedup_last_write_wins(rows: list[CalibrationRow]) -> list[CalibrationRow]:
    """Dedup by run_id; newer timestamp wins on collision."""
    by_id: dict[str, CalibrationRow] = {}
    for r in rows:
        existing = by_id.get(r.run_id)
        if existing is None or r.timestamp > existing.timestamp:
            by_id[r.run_id] = r
    return list(by_id.values())


def _spread(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return max(values) - min(values)


class Resolver:
    """Stateful calibration lookup that combines an optional external
    file with the bundled snapshot. Build one per CLI invocation."""

    def __init__(self, external_path: Path | None = None):
        self._bundled, self.bundled_diag = _load_bundled()
        if external_path is not None:
            self._external, self.external_diag = _load_file(external_path)
        else:
            self._external, self.external_diag = [], LoadDiagnostics()

    def _all_rows(self) -> list[CalibrationRow]:
        # External wins on run_id collision: list it first, then bundled.
        merged = list(self._external) + list(self._bundled)
        return _dedup_last_write_wins(merged)

    def lookup(
        self,
        target_model: str,
        pack_id: str,
        task_id: str,
        profile_id: str,
        exec_mode: str,
    ) -> CalibrationLookup:
        matches = [
            r for r in self._all_rows()
            if r.target_model == target_model
            and r.pack_id == pack_id
            and r.task_id == task_id
            and r.profile_id == profile_id
            and r.exec_mode == exec_mode
        ]
        if not matches:
            return CalibrationLookup(
                rows=[], median_input_tokens=0, median_output_tokens=0,
                median_duration_s=0.0, median_cost_usd=0.0,
                spread_cost_usd=0.0, n=0,
            )
        costs = sorted(r.cost_usd for r in matches)
        return CalibrationLookup(
            rows=matches,
            median_input_tokens=int(median(r.input_tokens for r in matches)),
            median_output_tokens=int(median(r.output_tokens for r in matches)),
            median_duration_s=float(median(r.duration_s for r in matches)),
            median_cost_usd=float(median(r.cost_usd for r in matches)),
            spread_cost_usd=_spread(costs),
            n=len(matches),
        )

    def neighbors(self, target_family: str) -> list[CalibrationRow]:
        """Return all calibration rows in the same target_family.

        Empty-family query returns []. Rows whose own target_family is
        empty are excluded (they're rows for which pricing.Resolver
        could not determine a family at insert time)."""
        if not target_family:
            return []
        return [
            r for r in self._all_rows()
            if r.target_family == target_family and r.target_family != ""
        ]


# ---------------------------------------------------------------------------
# Feature extraction (Task 21)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskFeatures:
    """6-tuple feature vector for the predictor."""
    prompt_word_count: int
    rubric_criteria_count: int
    starter_file_count: int
    starter_total_bytes: int
    profile_skill_count: int
    baseline_indicator: int     # 0 if exec_mode=="project", 1 if "none"

    def to_vector(self) -> tuple[float, ...]:
        return (
            float(self.prompt_word_count),
            float(self.rubric_criteria_count),
            float(self.starter_file_count),
            float(self.starter_total_bytes),
            float(self.profile_skill_count),
            float(self.baseline_indicator),
        )


def _count_rubric_criteria(text: str) -> int:
    """Count bullet lines starting with '- ' (with or without checkbox)."""
    count = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- "):
            count += 1
    return count


def extract_features(
    task_dir: Path,
    profile_skill_count: int,
    exec_mode: str,
) -> TaskFeatures:
    prompt_path = task_dir / "prompt.md"
    rubric_path = task_dir / "rubric.md"
    starter_dir = task_dir / "starter"

    prompt_text = prompt_path.read_text() if prompt_path.exists() else ""
    rubric_text = rubric_path.read_text() if rubric_path.exists() else ""

    starter_file_count = 0
    starter_total_bytes = 0
    if starter_dir.exists():
        for p in starter_dir.rglob("*"):
            if p.is_file():
                starter_file_count += 1
                try:
                    starter_total_bytes += p.stat().st_size
                except OSError:
                    continue

    return TaskFeatures(
        prompt_word_count=len(prompt_text.split()),
        rubric_criteria_count=_count_rubric_criteria(rubric_text),
        starter_file_count=starter_file_count,
        starter_total_bytes=starter_total_bytes,
        profile_skill_count=profile_skill_count,
        baseline_indicator=1 if exec_mode == "none" else 0,
    )


# ---------------------------------------------------------------------------
# kNN predictor (Task 22)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KnnPrediction:
    """Result of a kNN prediction over calibration neighbors."""
    median_input_tokens: int
    median_output_tokens: int
    median_duration_s: float
    median_cost_usd: float          # archival; estimator re-prices
    spread_cost_usd: float          # max-min of cost_usd over neighbors (archival)
    k: int                          # actual neighbors used
    n_candidates: int               # total in family before kNN cut
    target_family: str
    neighbor_run_ids: tuple[str, ...]


def _normalize_columns(vectors: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
    """Z-score normalize each column. Constant columns map to 0.0."""
    if not vectors:
        return []
    n_cols = len(vectors[0])
    out: list[list[float]] = [[] for _ in range(n_cols)]
    for v in vectors:
        for i, x in enumerate(v):
            out[i].append(x)
    means = [sum(col) / len(col) for col in out]
    variances = [
        sum((x - means[i]) ** 2 for x in col) / len(col)
        for i, col in enumerate(out)
    ]
    stds = [math.sqrt(v) if v > 0 else 0.0 for v in variances]
    normalized: list[tuple[float, ...]] = []
    for v in vectors:
        normalized.append(tuple(
            (x - means[i]) / stds[i] if stds[i] > 0 else 0.0
            for i, x in enumerate(v)
        ))
    return normalized


def _normalize_query(
    query: tuple[float, ...], reference: list[tuple[float, ...]]
) -> tuple[float, ...]:
    """Apply the same z-score normalization as `reference` to a single
    out-of-set query vector."""
    if not reference:
        return query
    n_cols = len(reference[0])
    cols: list[list[float]] = [[] for _ in range(n_cols)]
    for v in reference:
        for i, x in enumerate(v):
            cols[i].append(x)
    means = [sum(col) / len(col) for col in cols]
    variances = [
        sum((x - means[i]) ** 2 for x in col) / len(col)
        for i, col in enumerate(cols)
    ]
    stds = [math.sqrt(v) if v > 0 else 0.0 for v in variances]
    return tuple(
        (query[i] - means[i]) / stds[i] if stds[i] > 0 else 0.0
        for i in range(n_cols)
    )


def knn_predict(
    query: "TaskFeatures",
    candidates: list[tuple[CalibrationRow, "TaskFeatures"]],
    k: int = 3,
) -> KnnPrediction | None:
    """k-nearest-neighbors over feature vectors with z-score normalization.

    Returns None if `len(candidates) < k`. Among candidates, distances
    are Euclidean over normalized features. Ties broken by timestamp
    DESC (newer rows preferred).
    """
    if len(candidates) < k:
        return None

    rows = [c[0] for c in candidates]
    cand_vectors = [c[1].to_vector() for c in candidates]
    normalized = _normalize_columns(cand_vectors)
    query_norm = _normalize_query(query.to_vector(), cand_vectors)

    def dist(v: tuple[float, ...]) -> float:
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(query_norm, v)))

    indexed = list(enumerate(normalized))
    # Sort by distance ASC, then timestamp DESC (newer rows preferred on ties).
    indexed.sort(key=lambda t: (dist(t[1]), rows[t[0]].timestamp), reverse=False)
    # Apply timestamp descending as secondary: re-sort stably on timestamp DESC
    # for equal distances. Python's sort is stable, so two passes work:
    # pass 1: sort by timestamp DESC, pass 2: sort by dist ASC.
    indexed.sort(key=lambda t: rows[t[0]].timestamp, reverse=True)
    indexed.sort(key=lambda t: dist(t[1]))

    chosen = [rows[i] for i, _ in indexed[:k]]
    costs = sorted(r.cost_usd for r in chosen)

    return KnnPrediction(
        median_input_tokens=int(median(r.input_tokens for r in chosen)),
        median_output_tokens=int(median(r.output_tokens for r in chosen)),
        median_duration_s=float(median(r.duration_s for r in chosen)),
        median_cost_usd=float(median(r.cost_usd for r in chosen)),
        spread_cost_usd=_spread(costs),
        k=k,
        n_candidates=len(candidates),
        target_family=chosen[0].target_family,
        neighbor_run_ids=tuple(r.run_id for r in chosen),
    )

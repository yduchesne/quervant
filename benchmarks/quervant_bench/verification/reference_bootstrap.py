"""Independent deterministic paired-block bootstrap interval.

The algorithm is re-derived from the frozen written contract and uses only
Python's standard-library :mod:`hashlib` plus the shared canonical JSON encoder.
It never imports :mod:`quervant_bench.analysis.bootstrap`, never uses
``random``, an OS entropy source, interpolation, a normal approximation or a
BCa correction.

Algorithm ``sha256-rejection-paired-block-v1``:

* bind a closed payload of frozen identities into a domain key;
* derive an unsigned 64-bit big-endian counter stream from the key;
* reject an eight-byte value below the modulo-bias limit and increment the
  counter on **every** attempt, accepted or rejected;
* draw exactly ``nblocks`` paired block rows with replacement per replicate and
  apply the configured estimator to the same draw for both arms;
* take nearest-rank zero-based endpoints and quantise only those endpoints.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..config.codec import canonical_payload_bytes
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id, validate_uint64
from .contracts import (
    BASIS_POINTS_TOTAL,
    BOOTSTRAP_ALGORITHM,
    CONFIDENCE_BASIS_POINTS,
    DIRECTIONS,
    ESTIMATORS,
    MAX_RESAMPLES,
    MAX_TOTAL_DRAWS,
    MIN_RESAMPLES,
    TAIL_BASIS_POINTS,
)
from .reference_math import compute_estimator, quantize_12

DOMAIN_PREFIX = b"quervant-bench/paired-bootstrap/v1\x00"
UINT64_MAX = 2**64 - 1
MIN_INTERVAL_BLOCKS = 2

BINDING_KEYS = frozenset(
    {
        "baseline_id",
        "campaign_index",
        "candidate_id",
        "estimator_id",
        "lane_id",
        "protocol_digest",
        "seed",
    }
)


def _invalid(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def _identity(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class BootstrapInterval:
    """One independently computed nearest-rank interval plus its stream identity."""

    low: Decimal
    high: Decimal
    stream_digest: str


# ---------------------------------------------------------------------------
# Percentile indexes and draw budget
# ---------------------------------------------------------------------------


def _require_int(value: object, field_path: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{field_path} must be an integer", field_path)
    if value < minimum or value > maximum:
        raise _invalid(
            f"{field_path} must be in [{minimum}, {maximum}]", field_path
        )
    return value


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def nearest_rank_indexes(resamples: int) -> tuple[int, int]:
    """Return the frozen zero-based nearest-rank interval indexes."""

    count = _require_int(
        resamples, "resamples", minimum=MIN_RESAMPLES, maximum=MAX_RESAMPLES
    )
    low = _ceil_div(TAIL_BASIS_POINTS * count, BASIS_POINTS_TOTAL) - 1
    high = _ceil_div(
        (BASIS_POINTS_TOTAL - TAIL_BASIS_POINTS) * count, BASIS_POINTS_TOTAL
    ) - 1
    return max(low, 0), max(high, 0)


def ensure_draw_budget(*, resamples: int, blocks: int, comparisons: int) -> int:
    """Reject an over-budget derivation before any resampling happens."""

    count = _require_int(
        resamples, "resamples", minimum=MIN_RESAMPLES, maximum=MAX_RESAMPLES
    )
    block_count = _require_int(blocks, "blocks", minimum=1, maximum=2**32)
    comparison_count = _require_int(
        comparisons, "comparisons", minimum=0, maximum=MAX_TOTAL_DRAWS
    )
    draws = count * block_count * comparison_count
    if draws > MAX_TOTAL_DRAWS:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"the derivation would need {draws} bootstrap draws, above the "
            f"{MAX_TOTAL_DRAWS} budget",
            field_path="bootstrap.resamples",
        )
    return draws


# ---------------------------------------------------------------------------
# Closed binding and domain stream
# ---------------------------------------------------------------------------


def binding_payload(
    *,
    baseline_id: str,
    campaign_index: int,
    candidate_id: str,
    estimator_id: str,
    lane_id: str,
    protocol_digest: str,
    seed: int,
) -> dict[str, Any]:
    """Return the closed bootstrap binding payload from frozen inputs only."""

    return {
        "baseline_id": validate_semantic_id(baseline_id, "baseline_id"),
        "campaign_index": _require_int(
            campaign_index, "campaign_index", minimum=0, maximum=2**63 - 1
        ),
        "candidate_id": validate_semantic_id(candidate_id, "candidate_id"),
        "estimator_id": (
            estimator_id
            if estimator_id in ESTIMATORS
            else _invalid(
                f"estimator_id must be one of {sorted(ESTIMATORS)}", "estimator_id"
            )
        ),
        "lane_id": validate_semantic_id(lane_id, "lane_id"),
        "protocol_digest": validate_digest(protocol_digest, "protocol_digest"),
        "seed": validate_uint64(seed, "seed"),
    }


def domain_key(payload: dict[str, Any]) -> bytes:
    """Return ``SHA256(prefix || canonical_payload_bytes(binding))``."""

    if set(payload) != BINDING_KEYS:
        raise _identity("the bootstrap binding must use the closed key set", "binding")
    return hashlib.sha256(DOMAIN_PREFIX + canonical_payload_bytes(payload)).digest()


def _modulo_limit(block_count: int) -> int:
    return (UINT64_MAX + 1) // block_count * block_count


def _reduce_value(value: int, block_count: int) -> int | None:
    """Return the unbiased index for one raw draw value, or ``None``.

    ``value`` must be an unsigned 64-bit integer. Values at or above the largest
    multiple of ``block_count`` are rejected so the modulo mapping stays uniform.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid("a raw bootstrap draw must be an integer", "value")
    if value < 0 or value > UINT64_MAX:
        raise _invalid("a raw bootstrap draw must be an unsigned 64-bit integer", "value")
    blocks = _require_int(block_count, "block_count", minimum=1, maximum=2**32)
    if value >= _modulo_limit(blocks):
        return None
    return value % blocks


def _draw_index(key: bytes, block_count: int, counter: int) -> int | None:
    """Return the accepted index for one counter, or ``None`` when rejected."""

    digest = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
    return _reduce_value(int.from_bytes(digest[:8], "big"), block_count)


def _index_stream(
    key: bytes, block_count: int, count: int, start_counter: int
) -> Iterator[int]:
    if not isinstance(key, bytes) or len(key) != 32:
        raise _invalid("the domain key must be 32 raw bytes", "domain_key")
    blocks = _require_int(block_count, "block_count", minimum=1, maximum=2**32)
    wanted = _require_int(
        count, "count", minimum=0, maximum=MAX_TOTAL_DRAWS
    )
    counter = _require_int(
        start_counter, "counter", minimum=0, maximum=UINT64_MAX
    )

    produced = 0
    while produced < wanted:
        if counter >= UINT64_MAX:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "the bootstrap stream exhausted the 64-bit counter space",
                field_path="counter",
            )
        index = _draw_index(key, blocks, counter)
        counter += 1
        if index is None:
            continue
        produced += 1
        yield index


def index_stream(key: bytes, block_count: int, count: int) -> Iterator[int]:
    """Yield accepted zero-based block indexes from the frozen stream."""

    return _index_stream(key, block_count, count, 0)


# ---------------------------------------------------------------------------
# Interval
# ---------------------------------------------------------------------------


def _validate_rows(
    rows: Sequence[tuple[int, Decimal, Decimal]]
) -> tuple[tuple[int, Decimal, Decimal], ...]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
        raise _invalid("paired block rows must be a non-empty sequence", "block_rows")
    validated: list[tuple[int, Decimal, Decimal]] = []
    for position, row in enumerate(rows):
        field = f"block_rows[{position}]"
        if not isinstance(row, tuple) or len(row) != 3:
            raise _invalid(
                "each block row must be a (block, baseline, candidate) tuple", field
            )
        block, baseline, candidate = row
        if isinstance(block, bool) or not isinstance(block, int) or block < 1:
            raise _invalid(f"{field}[0] must be a positive integer block id", field)
        for name, value in (("baseline", baseline), ("candidate", candidate)):
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise _invalid(
                    f"{field}.{name} must be a finite positive Decimal", field
                )
        validated.append((block, baseline, candidate))
    return tuple(validated)


def compute_interval(
    rows: Sequence[tuple[int, Decimal, Decimal]],
    *,
    seed: int,
    protocol_digest: str,
    campaign_index: int,
    lane_id: str,
    candidate_id: str,
    baseline_id: str,
    estimator_id: str,
    direction: str,
    resamples: int,
    confidence_basis_points: int = CONFIDENCE_BASIS_POINTS,
) -> BootstrapInterval:
    """Compute one independent ``sha256-rejection-paired-block-v1`` interval."""

    if direction not in DIRECTIONS:
        raise _invalid(
            f"direction must be one of {sorted(DIRECTIONS)}", "direction"
        )
    if confidence_basis_points != CONFIDENCE_BASIS_POINTS:
        raise _identity(
            f"v1 requires confidence_basis_points {CONFIDENCE_BASIS_POINTS}",
            "confidence_basis_points",
        )
    validated = _validate_rows(rows)
    block_count = len(validated)
    if block_count < MIN_INTERVAL_BLOCKS:
        raise _invalid(
            f"an interval requires at least {MIN_INTERVAL_BLOCKS} paired blocks",
            "block_rows",
        )
    count = _require_int(
        resamples, "resamples", minimum=MIN_RESAMPLES, maximum=MAX_RESAMPLES
    )
    ensure_draw_budget(resamples=count, blocks=block_count, comparisons=1)
    payload = binding_payload(
        baseline_id=baseline_id,
        campaign_index=campaign_index,
        candidate_id=candidate_id,
        estimator_id=estimator_id,
        lane_id=lane_id,
        protocol_digest=protocol_digest,
        seed=seed,
    )
    key = domain_key(payload)
    stream_digest = "sha256:" + key.hex()
    indexes = list(index_stream(key, block_count, count * block_count))
    estimates: list[Decimal] = []
    for replicate in range(count):
        start = replicate * block_count
        drawn = tuple(
            validated[index] for index in indexes[start : start + block_count]
        )
        estimates.append(compute_estimator(drawn, direction, estimator_id))
    estimates.sort()
    low_index, high_index = nearest_rank_indexes(count)
    return BootstrapInterval(
        low=quantize_12(estimates[low_index], "ci_low"),
        high=quantize_12(estimates[high_index], "ci_high"),
        stream_digest=stream_digest,
    )


__all__ = [
    "BINDING_KEYS",
    "DOMAIN_PREFIX",
    "BootstrapInterval",
    "binding_payload",
    "compute_interval",
    "domain_key",
    "ensure_draw_budget",
    "index_stream",
    "nearest_rank_indexes",
]

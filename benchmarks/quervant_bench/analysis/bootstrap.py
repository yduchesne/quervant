"""Deterministic paired-block bootstrap intervals.

Two algorithms exist here and they are deliberately separated:

``sha256-rejection-paired-block-v1``
    The **only** algorithm a new analysis profile may select. It derives an
    honest, source-independent SHA-256 counter stream from a closed binding
    payload, draws whole paired blocks with rejection sampling against a modulo
    bias limit, and applies the *same* frozen estimator to the drawn rows.

``legacy-python-randrange-v1``
    An isolated historical compatibility helper for read-only D3-C/T7 replay. It
    uses a local ``random.Random(seed)`` instance and a *ratio of median
    arm-block values*. It is never a default and is never reachable from a new
    analysis profile.

No global RNG, no ``random.choice``/``shuffle``, no OS entropy, no interpolation,
no normal approximation, no BCa correction and no hidden standard error.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from decimal import Decimal, localcontext
from typing import Any

from ..config.codec import canonical_payload_bytes
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id, validate_uint64
from .arithmetic import (
    compute_paired_effect,
    median,
    normalized_effect,
    require_block_rows,
)
from .contracts import (
    BASIS_POINTS_TOTAL,
    CONFIDENCE_BASIS_POINTS,
    DIRECTION_LOWER_IS_BETTER,
    ESTIMATORS,
    BootstrapInterval,
    decimal_context,
    quantize_effect,
    require_enum,
    require_int,
)

ALGORITHM_SHA256_REJECTION = "sha256-rejection-paired-block-v1"
ALGORITHM_LEGACY_RANDOM = "legacy-python-randrange-v1"

DOMAIN_PREFIX = b"quervant-bench/paired-bootstrap/v1\x00"

MIN_RESAMPLES = 100
MAX_RESAMPLES = 20_000
UINT64_MAX = 2**64 - 1

_BINDING_KEYS = frozenset(
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


def _fail(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _invalid(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


# ---------------------------------------------------------------------------
# Nearest-rank percentile indexes
# ---------------------------------------------------------------------------


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def percentile_indexes(
    resamples: int, confidence_basis_points: int = CONFIDENCE_BASIS_POINTS
) -> tuple[int, int]:
    """Return the frozen zero-based nearest-rank interval indexes.

    ``R=1000`` yields ``(24, 974)`` and ``R=10000`` yields ``(249, 9749)``.
    """

    count = require_int(
        resamples, "resamples", minimum=MIN_RESAMPLES, maximum=MAX_RESAMPLES
    )
    confidence = require_int(confidence_basis_points, "confidence_basis_points")
    if not 0 < confidence < BASIS_POINTS_TOTAL:  # pragma: no cover - v1 fixes 9500
        raise _invalid("confidence_basis_points must be in (0, 10000)", "confidence_basis_points")
    tail = (BASIS_POINTS_TOTAL - confidence) // 2
    low = _ceil_div(tail * count, BASIS_POINTS_TOTAL) - 1
    high = _ceil_div((BASIS_POINTS_TOTAL - tail) * count, BASIS_POINTS_TOTAL) - 1
    if low < 0:  # pragma: no cover - guarded by MIN_RESAMPLES
        low = 0
    if high < low:  # pragma: no cover - guarded by construction
        high = low
    return low, max(high, 0)


# ---------------------------------------------------------------------------
# Frozen SHA-256 rejection stream
# ---------------------------------------------------------------------------


def binding_payload(
    *,
    seed: int,
    protocol_digest: str,
    campaign_index: int,
    lane_id: str,
    candidate_id: str,
    baseline_id: str,
    estimator_id: str,
) -> dict[str, Any]:
    """Return the closed, canonical bootstrap binding payload."""

    return {
        "baseline_id": validate_semantic_id(baseline_id, "baseline_id"),
        "campaign_index": require_int(campaign_index, "campaign_index"),
        "candidate_id": validate_semantic_id(candidate_id, "candidate_id"),
        "estimator_id": require_enum(estimator_id, "estimator_id", ESTIMATORS),
        "lane_id": validate_semantic_id(lane_id, "lane_id"),
        "protocol_digest": validate_digest(protocol_digest, "protocol_digest"),
        "seed": validate_uint64(seed, "seed"),
    }


def domain_key(payload: dict[str, Any]) -> bytes:
    """Return ``SHA256(prefix || canonical_payload_bytes(binding))``."""

    if set(payload) != _BINDING_KEYS:  # pragma: no cover - callers use binding_payload
        raise _invalid("the bootstrap binding must use the closed key set", "binding")
    return hashlib.sha256(DOMAIN_PREFIX + canonical_payload_bytes(payload)).digest()


def index_stream(
    key: bytes, block_count: int, count: int
) -> Iterator[int]:
    """Yield ``count`` accepted zero-based block indexes from the frozen stream.

    The counter increments **once per attempted draw** (accepted or rejected), so
    a rejected candidate never silently reuses a counter value.
    """

    if not isinstance(key, bytes) or len(key) != 32:
        raise _invalid("the domain key must be 32 raw bytes", "domain_key")
    blocks = require_int(block_count, "block_count", minimum=1)
    wanted = require_int(count, "count")
    limit = (UINT64_MAX + 1) // blocks * blocks
    counter = 0
    produced = 0
    while produced < wanted:
        if counter >= UINT64_MAX:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "the bootstrap stream exhausted the 64-bit counter space",
                field_path="counter",
            )
        digest = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        counter += 1
        value = int.from_bytes(digest[:8], "big")
        if value >= limit:
            continue
        produced += 1
        yield value % blocks


def bootstrap_interval(
    block_rows: Sequence[tuple[int, Decimal, Decimal]],
    *,
    seed: int,
    protocol_digest: str,
    campaign_index: int,
    lane_id: str,
    candidate_id: str,
    baseline_id: str,
    estimator_id: str,
    resamples: int,
    confidence_basis_points: int,
    direction: str = DIRECTION_LOWER_IS_BETTER,
) -> BootstrapInterval:
    """Return one ``sha256-rejection-paired-block-v1`` interval.

    ``block_rows`` must already be pruned **symmetrically** and carry whole paired
    rows ``(block_id, baseline_value, candidate_value)`` in ascending block order.
    Each replicate draws exactly ``nblocks`` rows with replacement and applies the
    *same* frozen estimator, so the two arms always come from the same draw.
    """

    rows = require_block_rows(block_rows)
    resolved_estimator = require_enum(estimator_id, "estimator_id", ESTIMATORS)
    count = require_int(
        resamples, "resamples", minimum=MIN_RESAMPLES, maximum=MAX_RESAMPLES
    )
    confidence = require_int(confidence_basis_points, "confidence_basis_points")
    if confidence != CONFIDENCE_BASIS_POINTS:
        raise _fail(
            f"v1 requires confidence_basis_points {CONFIDENCE_BASIS_POINTS}",
            "confidence_basis_points",
        )
    payload = binding_payload(
        seed=seed,
        protocol_digest=protocol_digest,
        campaign_index=campaign_index,
        lane_id=lane_id,
        candidate_id=candidate_id,
        baseline_id=baseline_id,
        estimator_id=resolved_estimator,
    )
    key = domain_key(payload)
    block_count = len(rows)
    draws = list(index_stream(key, block_count, count * block_count))
    estimates: list[Decimal] = []
    with localcontext(decimal_context()):
        for replicate in range(count):
            start = replicate * block_count
            drawn = tuple(rows[index] for index in draws[start : start + block_count])
            estimates.append(
                compute_paired_effect(drawn, direction, resolved_estimator)
            )
    estimates.sort()
    low_index, high_index = percentile_indexes(count, confidence)
    return BootstrapInterval(
        low=quantize_effect(estimates[low_index]),
        high=quantize_effect(estimates[high_index]),
        seed=payload["seed"],
        resamples=count,
        algorithm_id=ALGORITHM_SHA256_REJECTION,
        estimator_id=resolved_estimator,
        confidence_basis_points=confidence,
        paired_block_count=block_count,
        stream_digest="sha256:" + key.hex(),
    )


# ---------------------------------------------------------------------------
# Historical-only compatibility helper (never a default)
# ---------------------------------------------------------------------------


def legacy_percentile_indexes(resamples: int) -> tuple[int, int]:
    """Return the frozen historical T7 order-statistic indexes (249/9749)."""

    return percentile_indexes(resamples, CONFIDENCE_BASIS_POINTS)


def legacy_t7_seed(
    historical_protocol_sha: str,
    campaign_name: str,
    lane_id: str,
    numerator: str,
    denominator: str,
) -> int:
    """Return the frozen historical T7 ``random.Random`` seed for one lane CI."""

    for name, value in (
        ("historical_protocol_sha", historical_protocol_sha),
        ("campaign_name", campaign_name),
        ("lane_id", lane_id),
        ("numerator", numerator),
        ("denominator", denominator),
    ):
        if not isinstance(value, str) or not value:
            raise _fail(f"{name} must be a non-empty string", name)
    material = (
        f"{historical_protocol_sha}|{campaign_name}|{lane_id}|"
        f"{numerator}/{denominator}"
    )
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")


def legacy_bootstrap_interval(
    block_rows: Sequence[tuple[int, Decimal, Decimal]],
    *,
    seed: int,
    resamples: int = 10_000,
    confidence_basis_points: int = CONFIDENCE_BASIS_POINTS,
    direction: str = DIRECTION_LOWER_IS_BETTER,
) -> BootstrapInterval:
    """Return the isolated historical ``legacy-python-randrange-v1`` interval.

    Historical T7 draws blocks with a seeded ``random.Random`` instance and takes
    the ratio of the **medians of the two arms' block values**, not the median of
    the per-block ratios. This is a compatibility calculator for read-only
    historical replay; it is never selected by a new analysis profile.
    """

    from random import Random

    rows = require_block_rows(block_rows)
    count = require_int(resamples, "resamples", minimum=1)
    confidence = require_int(confidence_basis_points, "confidence_basis_points")
    resolved_seed = validate_uint64(seed, "seed")
    generator = Random(resolved_seed)
    block_count = len(rows)
    estimates: list[Decimal] = []
    with localcontext(decimal_context()):
        for _replicate in range(count):
            drawn = [rows[generator.randrange(block_count)] for _ in range(block_count)]
            baseline_median = median([row[1] for row in drawn])
            candidate_median = median([row[2] for row in drawn])
            estimates.append(
                normalized_effect(candidate_median, baseline_median, direction)
            )
    estimates.sort()
    low_index, high_index = percentile_indexes(count, confidence)
    return BootstrapInterval(
        low=quantize_effect(estimates[low_index]),
        high=quantize_effect(estimates[high_index]),
        seed=resolved_seed,
        resamples=count,
        algorithm_id=ALGORITHM_LEGACY_RANDOM,
        estimator_id="ratio-of-arm-medians-v1",
        confidence_basis_points=confidence,
        paired_block_count=block_count,
        stream_digest="sha256:" + hashlib.sha256(str(resolved_seed).encode()).hexdigest(),
    )


__all__ = [
    "ALGORITHM_LEGACY_RANDOM",
    "ALGORITHM_SHA256_REJECTION",
    "DOMAIN_PREFIX",
    "binding_payload",
    "bootstrap_interval",
    "domain_key",
    "index_stream",
    "legacy_bootstrap_interval",
    "legacy_percentile_indexes",
    "legacy_t7_seed",
    "percentile_indexes",
]

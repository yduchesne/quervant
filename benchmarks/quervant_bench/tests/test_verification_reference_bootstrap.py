"""Independent bootstrap stream, bounds and paired-draw tests (V-BOOT)."""

from __future__ import annotations

import hashlib
import json
import unittest
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path

from quervant_bench.config.errors import BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from quervant_bench.verification.reference_bootstrap import (
    DOMAIN_PREFIX,
    UINT64_MAX,
    _index_stream,
    _modulo_limit,
    _reduce_value,
    binding_payload,
    compute_interval,
    domain_key,
    ensure_draw_budget,
    index_stream,
    nearest_rank_indexes,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "verification"
VECTORS = json.loads((FIXTURES / "reference-vectors.v1.json").read_text(encoding="utf-8"))
CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


def _rows(vector: dict) -> tuple[tuple[int, Decimal, Decimal], ...]:
    return tuple(
        (block, Decimal(baseline), Decimal(candidate))
        for block, baseline, candidate in vector["paired_block_rows"]
    )


class BootstrapStreamTests(unittest.TestCase):
    def test_v_boot_01_published_seed_binding_matches_the_checked_in_golden(self) -> None:
        vector = VECTORS["bootstrap_published_seed42"]
        payload = binding_payload(**vector["binding"])
        key = domain_key(payload)
        self.assertEqual(key.hex(), vector["domain_key"])
        self.assertEqual(
            list(index_stream(key, vector["block_count"], 16)),
            vector["first_16_indexes"],
        )
        # Independent standard-library reproduction of the same bytes.
        canonical = json.dumps(
            vector["binding"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(DOMAIN_PREFIX + canonical).digest().hex(),
            vector["domain_key"],
        )

    def test_v_boot_02_percentile_indexes_match_the_frozen_nearest_rank(self) -> None:
        self.assertEqual(nearest_rank_indexes(1000), tuple(VECTORS["percentile_indexes"]["1000"]))
        self.assertEqual(
            nearest_rank_indexes(10000), tuple(VECTORS["percentile_indexes"]["10000"])
        )
        self.assertNotEqual(nearest_rank_indexes(1000), (25, 974))
        self.assertNotEqual(nearest_rank_indexes(1000), (24, 975))
        with self.assertRaises(BenchError) as caught:
            nearest_rank_indexes(99)
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_v_boot_03_small_non_degenerate_vector_matches_hand_derived_goldens(self) -> None:
        vector = VECTORS["bootstrap_small"]
        rows = _rows(vector)
        binding = vector["binding"]
        key = domain_key(binding_payload(**binding))
        self.assertEqual(key.hex(), vector["domain_key"])
        indexes = list(index_stream(key, vector["block_count"], 16))
        self.assertEqual(indexes, vector["first_16_indexes"])

        # Independent replicate oracle built only from stdlib primitives.
        draws = list(index_stream(key, vector["block_count"], 100 * vector["block_count"]))
        replicate_medians: list[str] = []
        estimates: list[Decimal] = []
        for replicate in range(100):
            drawn = [
                rows[index]
                for index in draws[
                    replicate * vector["block_count"] : (replicate + 1) * vector["block_count"]
                ]
            ]
            with localcontext(CONTEXT):
                ratios = sorted(candidate / baseline for _b, baseline, candidate in drawn)
                median = ratios[len(ratios) // 2] if len(ratios) % 2 else (
                    ratios[len(ratios) // 2 - 1] + ratios[len(ratios) // 2]
                ) / 2
            estimates.append(median)
            if replicate < 12:
                with localcontext(CONTEXT):
                    replicate_medians.append(
                        format(median.quantize(Decimal("0.000000000001")), "f")
                    )
        self.assertEqual(replicate_medians, vector["first_12_replicate_medians"])
        ordered = sorted(estimates)
        low_index, high_index = nearest_rank_indexes(100)
        self.assertEqual([low_index, high_index], vector["nearest_rank_indexes"])
        with localcontext(CONTEXT):
            low = format(ordered[low_index].quantize(Decimal("0.000000000001")), "f")
            high = format(ordered[high_index].quantize(Decimal("0.000000000001")), "f")
        self.assertEqual(low, vector["ci_lower"])
        self.assertEqual(high, vector["ci_upper"])

        interval = compute_interval(
            rows,
            seed=binding["seed"],
            protocol_digest=binding["protocol_digest"],
            campaign_index=binding["campaign_index"],
            lane_id=binding["lane_id"],
            candidate_id=binding["candidate_id"],
            baseline_id=binding["baseline_id"],
            estimator_id=binding["estimator_id"],
            direction="lower-is-better",
            resamples=100,
        )
        self.assertEqual(format(interval.low, "f"), vector["ci_lower"])
        self.assertEqual(format(interval.high, "f"), vector["ci_upper"])
        self.assertEqual(interval.stream_digest, "sha256:" + vector["domain_key"])
        self.assertEqual(len(draws), vector["accepted_draw_count"])

    def test_v_boot_04_binding_changes_change_the_stream_identity(self) -> None:
        base = dict(VECTORS["bootstrap_small"]["binding"])
        baseline_key = domain_key(binding_payload(**base))
        for name, replacement in (
            ("candidate_id", "other-candidate"),
            ("lane_id", "common-query"),
            ("campaign_index", 1),
            ("estimator_id", "ratio-of-arm-medians-v1"),
            ("protocol_digest", "sha256:" + "1" * 64),
            ("seed", 8),
        ):
            with self.subTest(field=name):
                changed = dict(base)
                changed[name] = replacement
                self.assertNotEqual(
                    domain_key(binding_payload(**changed)), baseline_key
                )

    def test_v_boot_05_modulo_bound_is_rejection_sampling_not_bias(self) -> None:
        vector = VECTORS["bootstrap_modulo_bound"]
        blocks = vector["block_count"]
        self.assertEqual(_modulo_limit(blocks), vector["rejected_value"])
        self.assertEqual(
            _reduce_value(vector["accepted_value"], blocks), vector["accepted_index"]
        )
        self.assertIsNone(_reduce_value(vector["rejected_value"], blocks))
        with self.assertRaises(BenchError) as caught:
            _reduce_value(-1, blocks)
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_v_boot_06_counter_exhaustion_is_a_typed_rejection(self) -> None:
        key = bytes(range(32))
        with self.assertRaises(BenchError) as caught:
            next(_index_stream(key, 4, 1, UINT64_MAX))
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
        with self.assertRaises(BenchError) as caught:
            list(_index_stream(key, 4, 2, UINT64_MAX - 1))
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_v_boot_07_counter_increments_on_every_attempt(self) -> None:
        key = bytes(range(32))
        # A stream that starts one counter below the limit consumes the last
        # available counter and then fails rather than wrapping silently.
        with self.assertRaises(BenchError):
            list(_index_stream(key, 3, 64, UINT64_MAX - 1))
        with self.assertRaises(BenchError) as caught:
            ensure_draw_budget(
                resamples=20000, blocks=256, comparisons=1
            )
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)


class BootstrapIntervalTests(unittest.TestCase):
    def _compute(self, rows, **overrides):
        arguments = dict(
            seed=1,
            protocol_digest="sha256:" + "0" * 64,
            campaign_index=0,
            lane_id="rare-query",
            candidate_id="candidate",
            baseline_id="baseline",
            estimator_id="median-paired-ratios-v1",
            direction="lower-is-better",
            resamples=100,
        )
        arguments.update(overrides)
        return compute_interval(rows, **arguments)

    def test_v_boot_08_constant_ratio_dataset_stays_degenerate(self) -> None:
        rows = (
            (1, Decimal(10), Decimal(8)),
            (2, Decimal(20), Decimal(16)),
            (3, Decimal(30), Decimal(24)),
            (4, Decimal(40), Decimal(32)),
        )
        interval = self._compute(rows)
        self.assertEqual(interval.low, Decimal("0.800000000000"))
        self.assertEqual(interval.high, Decimal("0.800000000000"))

    def test_v_boot_09_independent_arm_draws_would_spread_and_are_not_used(self) -> None:
        rows = (
            (1, Decimal(10), Decimal(8)),
            (2, Decimal(20), Decimal(16)),
            (3, Decimal(30), Decimal(24)),
            (4, Decimal(40), Decimal(32)),
        )
        interval = self._compute(rows)
        key = domain_key(
            binding_payload(
                seed=1,
                protocol_digest="sha256:" + "0" * 64,
                campaign_index=0,
                lane_id="rare-query",
                candidate_id="candidate",
                baseline_id="baseline",
                estimator_id="median-paired-ratios-v1",
            )
        )
        indexes = list(index_stream(key, 4, 400))
        divergent: set[Decimal] = set()
        for replicate in range(100):
            drawn = indexes[replicate * 4 : (replicate + 1) * 4]
            baseline_median = sorted(rows[index][1] for index in drawn)[2]
            candidate_median = sorted(
                rows[(index + 1) % 4][2] for index in drawn
            )[2]
            divergent.add(candidate_median / baseline_median)
        self.assertGreater(len(divergent), 1)
        self.assertEqual(interval.low, interval.high)

    def test_v_boot_10_row_order_changes_the_drawn_estimates(self) -> None:
        rows = _rows(VECTORS["bootstrap_small"])
        forward = self._compute(rows)
        backward = self._compute(tuple(reversed(rows)))
        self.assertNotEqual((forward.low, forward.high), (backward.low, backward.high))
        self.assertEqual(forward.stream_digest, backward.stream_digest)

    def test_v_boot_11_endpoint_quantization_and_grammar(self) -> None:
        interval = self._compute(_rows(VECTORS["bootstrap_small"]), seed=7)
        self.assertEqual(format(interval.low, "f"), VECTORS["bootstrap_small"]["ci_lower"])
        self.assertEqual(interval.low.as_tuple().exponent, -12)
        self.assertEqual(interval.high.as_tuple().exponent, -12)

    def test_v_boot_12_insufficient_block_count_is_a_typed_rejection(self) -> None:
        with self.assertRaises(BenchError) as caught:
            self._compute(((1, Decimal(10), Decimal(8)),))
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_v_boot_13_profile_shape_is_validated(self) -> None:
        rows = _rows(VECTORS["bootstrap_small"])
        with self.assertRaises(BenchError):
            self._compute(rows, confidence_basis_points=9000)
        with self.assertRaises(BenchError):
            self._compute(rows, resamples=99)
        with self.assertRaises(BenchError):
            self._compute(rows, estimator_id="unknown")
        with self.assertRaises(BenchError):
            self._compute(rows, direction="sideways")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

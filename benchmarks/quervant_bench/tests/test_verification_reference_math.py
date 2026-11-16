"""Independent reference arithmetic, pruning and statistics tests (V-MATH/V-PRUNE)."""

from __future__ import annotations

import copy
import json
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BenchError
from quervant_bench.protocol.schedule import ScheduleSlot
from quervant_bench.verification.reference_math import (
    BlockEffectStatistics,
    build_analysis_document,
    compare_statistics,
    compute_estimator,
    compute_statistics,
    format_12,
    geometric_mean,
    mean_of,
    median_of,
    normalized_effect,
    quantize_12,
    raw_ratio,
    slot_median,
    within_arm_spread,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "verification"
VECTORS = json.loads((FIXTURES / "reference-vectors.v1.json").read_text(encoding="utf-8"))


def _slots(blocks: int, arms: tuple[str, ...], per_arm: int = 1) -> tuple[ScheduleSlot, ...]:
    built: list[ScheduleSlot] = []
    ordinal = 1
    for block in range(1, blocks + 1):
        position = 1
        for arm_id in arms:
            for _ in range(per_arm):
                built.append(ScheduleSlot(block, position, ordinal, arm_id))
                position += 1
                ordinal += 1
    return tuple(built)


def _samples(
    slots: tuple[ScheduleSlot, ...],
    values: dict[tuple[int, str, int], tuple[int, ...]],
) -> dict[tuple[int, str, int, str, int], tuple[int, ...]]:
    samples: dict[tuple[int, str, int, str, int], tuple[int, ...]] = {}
    counters: dict[tuple[int, str], int] = {}
    for slot in slots:
        key = (slot.block, slot.arm_id)
        index = counters.get(key, 0) + 1
        counters[key] = index
        samples[(0, "rare-query", slot.block, slot.arm_id, slot.position)] = values[
            (slot.block, slot.arm_id, index)
        ]
    return samples


def _statistics(
    *,
    arms: tuple[str, ...] = ("baseline", "candidate"),
    blocks: int = 4,
    per_arm: int = 1,
    baseline: str = "baseline",
    candidates: tuple[str, ...] = ("candidate",),
    cap: Decimal = Decimal("1.5"),
    minimum_retained: int = 3,
    values: dict[tuple[int, str, int], tuple[int, ...]] | None = None,
):
    slots = _slots(blocks, arms, per_arm)
    if values is None:
        values = {}
        counters: dict[tuple[int, str], int] = {}
        for slot in slots:
            key = (slot.block, slot.arm_id)
            index = counters.get(key, 0) + 1
            counters[key] = index
            values[(slot.block, slot.arm_id, index)] = (10,)
    return compute_statistics(
        campaign_indices=(0,),
        lane_ids=("rare-query",),
        slots=slots,
        arms=arms,
        samples=_samples(slots, values),
        baseline_arm_id=baseline,
        candidate_ids=candidates,
        direction="lower-is-better",
        caps={"rare-query": cap},
        blocks_total=blocks,
        minimum_retained=minimum_retained,
        estimator_id="median-paired-ratios-v1",
    )


class ReferenceMathTests(unittest.TestCase):
    def test_v_math_01_even_median_is_exact_and_never_floored(self) -> None:
        self.assertEqual(
            slot_median(tuple(VECTORS["median"]["even_vector"])),
            Decimal(VECTORS["median"]["even_value"]),
        )
        self.assertEqual(slot_median([1, 3, 7]), Decimal("3"))
        self.assertEqual(slot_median([1, 2]), Decimal("1.5"))
        self.assertNotEqual(slot_median([10, 20, 100, 200]), Decimal(45))

    def test_v_math_02_estimators_diverge_on_the_published_counterexample(self) -> None:
        rows = tuple(
            (block, Decimal(baseline), Decimal(candidate))
            for block, baseline, candidate in VECTORS["estimator_distinction"]["rows"]
        )
        self.assertEqual(
            format_12(
                compute_estimator(rows, "lower-is-better", "median-paired-ratios-v1")
            ),
            VECTORS["estimator_distinction"]["median_paired_ratios"],
        )
        self.assertEqual(
            format_12(
                compute_estimator(rows, "lower-is-better", "ratio-of-arm-medians-v1")
            ),
            VECTORS["estimator_distinction"]["ratio_of_arm_medians"],
        )

    def test_v_math_03_direction_is_a_reciprocal_without_swapping_identity(self) -> None:
        lower = VECTORS["direction"]["lower"]
        higher = VECTORS["direction"]["higher"]
        baseline = Decimal(lower["baseline"])
        candidate = Decimal(lower["candidate"])
        self.assertEqual(
            format_12(normalized_effect(candidate, baseline, "lower-is-better")),
            lower["normalized"],
        )
        self.assertEqual(
            format_12(normalized_effect(candidate, baseline, "higher-is-better")),
            higher["normalized"],
        )
        self.assertEqual(format_12(raw_ratio(candidate, baseline)), lower["raw"])
        with localcontext() as context:
            context.prec = 50
            product = normalized_effect(
                candidate, baseline, "lower-is-better"
            ) * normalized_effect(candidate, baseline, "higher-is-better")
        self.assertEqual(product, Decimal(1))

    def test_v_math_04_a_degenerate_constant_ratio_stays_degenerate(self) -> None:
        statistics = _statistics(
            values={
                (block, "baseline", 1): (10,)
                for block in range(1, 5)
            }
            | {(block, "candidate", 1): (8,) for block in range(1, 5)}
        )
        candidate = statistics[0].lanes[0].candidates[0]
        self.assertEqual(format_12(candidate.raw_point), "0.800000000000")
        self.assertEqual(format_12(candidate.retained_point), "0.800000000000")

    def test_v_math_05_non_first_baseline_keeps_identity(self) -> None:
        statistics = _statistics(
            arms=("candidate", "baseline"),
            candidates=("candidate",),
            values={
                (block, "baseline", 1): (10,)
                for block in range(1, 5)
            }
            | {(block, "candidate", 1): (8,) for block in range(1, 5)},
        )
        candidate = statistics[0].lanes[0].candidates[0]
        self.assertEqual(format_12(candidate.raw_point), "0.800000000000")
        self.assertEqual(candidate.candidate_arm_id, "candidate")

    def test_v_math_06_three_arms_share_the_same_frozen_baseline(self) -> None:
        values = {
            (block, "baseline", 1): (100,)
            for block in range(1, 5)
        }
        values |= {(block, "alpha", 1): (90,) for block in range(1, 5)}
        values |= {(block, "beta", 1): (80,) for block in range(1, 5)}
        statistics = _statistics(
            arms=("alpha", "baseline", "beta"),
            candidates=("alpha", "beta"),
            values=values,
        )
        lane = statistics[0].lanes[0]
        self.assertEqual([c.candidate_arm_id for c in lane.candidates], ["alpha", "beta"])
        self.assertEqual(format_12(lane.candidates[0].raw_point), "0.900000000000")
        self.assertEqual(format_12(lane.candidates[1].raw_point), "0.800000000000")

    def test_v_math_07_block_value_uses_slot_medians_not_pooled_samples(self) -> None:
        # Slot medians 10 and 1000 -> block value 505; pooling six samples gives 10.
        self.assertEqual(mean_of([Decimal("10"), Decimal("1000")]), Decimal("505"))
        self.assertEqual(slot_median([10, 10, 10, 1000, 1000, 10]), Decimal("10"))

    def test_v_math_08_geometric_mean_and_quantization_boundaries(self) -> None:
        self.assertEqual(
            format_12(geometric_mean([Decimal("0.8"), Decimal("1.25")])),
            "1.000000000000",
        )
        self.assertEqual(
            format_12(geometric_mean([Decimal("0.25"), Decimal("0.25"), Decimal("4"), Decimal("4")])),
            "1.000000000000",
        )
        self.assertEqual(format_12(Decimal("0.8333333333335")), "0.833333333334")
        self.assertEqual(format_12(Decimal("0.8333333333325")), "0.833333333332")
        self.assertEqual(format_12(Decimal("0.8000000000005")), "0.800000000000")
        self.assertEqual(quantize_12(Decimal("1")), Decimal("1.000000000000"))

    def test_v_math_09_invalid_numeric_inputs_are_typed_rejections(self) -> None:
        for invalid in ([True], [1.5], [0], [-1], [], "abc"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(BenchError) as caught:
                    slot_median(invalid)  # type: ignore[arg-type]
                self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)
        with self.assertRaises(BenchError) as caught:
            compute_estimator(
                [(1, Decimal(0), Decimal(1))],  # type: ignore[tuple-item]
                "lower-is-better",
                "median-paired-ratios-v1",
            )
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)
        with self.assertRaises(BenchError) as caught:
            compute_estimator(
                [(1, Decimal(1), Decimal(1))],
                "lower-is-better",
                "unknown-estimator",
            )
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)
        with self.assertRaises(BenchError) as caught:
            normalized_effect(Decimal(1), Decimal(2), "sideways")
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)
        with self.assertRaises(BenchError):
            format_12(Decimal("NaN"))


class ReferencePruningTests(unittest.TestCase):
    def test_v_prune_01_spread_equal_to_cap_retains_the_whole_block(self) -> None:
        statistics = _statistics(
            per_arm=2,
            values={
                (1, "baseline", 1): (10,),
                (1, "baseline", 2): (15,),
                (1, "candidate", 1): (10,),
                (1, "candidate", 2): (10,),
            }
            | {
                (block, arm, position): (10,)
                for block in range(2, 5)
                for arm in ("baseline", "candidate")
                for position in (1, 2)
            },
        )
        lane = statistics[0].lanes[0]
        self.assertEqual(lane.retained_blocks, (1, 2, 3, 4))
        self.assertEqual(lane.excluded_blocks, ())
        self.assertEqual(lane.ledger[0].trigger_arms, ())

    def test_v_prune_02_one_offending_arm_excludes_every_arm(self) -> None:
        statistics = _statistics(
            per_arm=2,
            minimum_retained=1,
            values={
                (1, "baseline", 1): (10,),
                (1, "baseline", 2): (16,),
                (1, "candidate", 1): (8,),
                (1, "candidate", 2): (8,),
            }
            | {
                (block, arm, position): (10,)
                for block in range(2, 5)
                for arm in ("baseline", "candidate")
                for position in (1, 2)
            },
        )
        lane = statistics[0].lanes[0]
        self.assertEqual(lane.excluded_blocks, (1,))
        self.assertEqual(lane.retained_blocks, (2, 3, 4))
        self.assertEqual(lane.ledger[0].trigger_arms, ("baseline",))
        self.assertEqual(
            [arm for arm, _spread in lane.ledger[0].arm_spreads],
            ["baseline", "candidate"],
        )

    def test_v_prune_03_insufficient_retained_blocks_keep_raw_and_null_retained(self) -> None:
        statistics = _statistics(
            per_arm=2,
            minimum_retained=3,
            values={
                (1, "baseline", 1): (10,),
                (1, "baseline", 2): (16,),
                (2, "baseline", 1): (10,),
                (2, "baseline", 2): (16,),
                (3, "baseline", 1): (10,),
                (3, "baseline", 2): (10,),
                (4, "baseline", 1): (10,),
                (4, "baseline", 2): (10,),
            }
            | {
                (block, "candidate", position): (8,)
                for block in range(1, 5)
                for position in (1, 2)
            },
        )
        lane = statistics[0].lanes[0]
        candidate = lane.candidates[0]
        self.assertEqual(lane.retained_blocks, (3, 4))
        self.assertEqual(candidate.status, "inconclusive-insufficient-blocks")
        self.assertIsNotNone(candidate.raw_point)
        self.assertIsNone(candidate.retained_point)
        self.assertEqual(candidate.retained_effects, ())
        self.assertEqual(len(candidate.raw_effects), 4)

    def test_v_prune_04_exclusion_is_outcome_blind(self) -> None:
        def build(candidate_value: int):
            return _statistics(
                per_arm=2,
                minimum_retained=1,
                values={
                    (1, "baseline", 1): (10,),
                    (1, "baseline", 2): (16,),
                    (2, "baseline", 1): (10,),
                    (2, "baseline", 2): (10,),
                    (3, "baseline", 1): (10,),
                    (3, "baseline", 2): (10,),
                    (4, "baseline", 1): (10,),
                    (4, "baseline", 2): (10,),
                    (1, "candidate", 1): (candidate_value,),
                    (1, "candidate", 2): (candidate_value,),
                }
                | {
                    (block, "candidate", position): (candidate_value,)
                    for block in range(1, 5)
                    for position in (1, 2)
                },
            )

        before = build(8)[0].lanes[0]
        after = build(1000)[0].lanes[0]
        self.assertEqual(before.excluded_blocks, after.excluded_blocks)
        self.assertEqual(before.retained_blocks, after.retained_blocks)
        self.assertNotEqual(
            before.candidates[0].raw_point, after.candidates[0].raw_point
        )

    def test_v_prune_05_ledger_covers_every_block_with_sorted_arms(self) -> None:
        statistics = _statistics(
            arms=("baseline", "candidate"),
            values={
                (block, arm, 1): (10,)
                for block in range(1, 5)
                for arm in ("baseline", "candidate")
            },
        )
        lane = statistics[0].lanes[0]
        self.assertEqual([row.block for row in lane.ledger], [1, 2, 3, 4])
        for row in lane.ledger:
            self.assertEqual(
                [arm for arm, _ in row.arm_spreads], ["baseline", "candidate"]
            )
            self.assertEqual(row.status, "retained")
            self.assertEqual(row.reason, "none")

    def test_v_prune_06_spread_of_one_retains(self) -> None:
        self.assertEqual(within_arm_spread([Decimal("10")]), Decimal(1))
        self.assertEqual(within_arm_spread([Decimal("10"), Decimal("15")]), Decimal("1.5"))


class ReferenceComparisonTests(unittest.TestCase):
    def _document(self, statistics) -> dict:
        intervals = {
            (0, "rare-query", candidate.candidate_arm_id): type(
                "Interval",
                (),
                {
                    "low": candidate.retained_point,
                    "high": candidate.retained_point,
                    "stream_digest": "sha256:" + "0" * 64,
                },
            )()
            for candidate in statistics[0].lanes[0].candidates
            if candidate.retained_point is not None
        }
        return build_analysis_document(
            experiment_id="synthetic-analysis-smoke",
            run_id="00000000-0000-4000-8000-000000000000",
            source_seal_digest="sha256:" + "1" * 64,
            freeze_digest="sha256:" + "2" * 64,
            protocol_digest="sha256:" + "3" * 64,
            analysis_profile_digest="sha256:" + "4" * 64,
            analysis_id="paired-block-analysis",
            analysis_version=1,
            estimator_id="median-paired-ratios-v1",
            algorithm_id="sha256-rejection-paired-block-v1",
            confidence_basis_points=9500,
            resamples=1000,
            seed=1,
            baseline_arm_id="baseline",
            candidate_ids=("candidate",),
            lane_ids=("rare-query",),
            direction="lower-is-better",
            campaigns=statistics,
            intervals=intervals,
        )

    def test_compare_statistics_accepts_the_independent_document(self) -> None:
        statistics = _statistics()
        document = self._document(statistics)
        compare_statistics(document, statistics)

    def test_compare_statistics_rejects_a_forged_statistic(self) -> None:
        statistics = _statistics()
        document = self._document(statistics)
        forged = copy.deepcopy(document)
        forged["campaigns"][0]["lanes"][0]["candidates"][0]["raw_point_effect"] = (
            "0.999999999999"
        )
        with self.assertRaises(BenchError) as caught:
            compare_statistics(forged, statistics)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertIn("raw_point_effect", caught.exception.field_path or "")

    def test_compare_statistics_rejects_a_forged_spread(self) -> None:
        statistics = _statistics()
        document = self._document(statistics)
        forged = copy.deepcopy(document)
        forged["campaigns"][0]["lanes"][0]["exclusion_ledger"][0]["arm_spreads"][0][
            "spread"
        ] = "1.000000000001"
        with self.assertRaises(BenchError) as caught:
            compare_statistics(forged, statistics)
        self.assertIn("exclusion_ledger", caught.exception.field_path or "")

    def test_block_effect_records_are_complete_and_ordered(self) -> None:
        statistics = _statistics()
        candidate = statistics[0].lanes[0].candidates[0]
        self.assertEqual([effect.block for effect in candidate.raw_effects], [1, 2, 3, 4])
        self.assertIsInstance(candidate.raw_effects[0], BlockEffectStatistics)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

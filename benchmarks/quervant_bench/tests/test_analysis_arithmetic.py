"""AN-MATH-01…07 and AN-DIR-01…06: exact arithmetic and metric direction.

Every expected value in this module is hand-computed and written literally. No
test calls the production function under test to build its own expected answer.
"""

from __future__ import annotations

import unittest
from decimal import Decimal, localcontext

from quervant_bench.analysis.arithmetic import (
    arm_block_value,
    compute_paired_effect,
    geometric_mean,
    median,
    median_paired_ratios,
    normalized_effect,
    ratio_of_arm_medians,
    relative_delta,
    slot_median,
    worst_campaign_gm,
)
from quervant_bench.analysis.contracts import (
    decimal_context,
    format_effect,
    parse_decimal_literal,
    quantize_effect,
)
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BenchError,
)
from quervant_bench.tests.analysis_support import (
    analysis_document,
    default_campaigns,
    effect,
    lane_row,
    candidate_row,
    make_policy_profile,
    make_resources,
)
from quervant_bench.analysis.policy import evaluate_policy


def dec(value: str) -> Decimal:
    return Decimal(value)


class SlotAndBlockArithmeticTests(unittest.TestCase):
    """AN-MATH-01…03, AN-MATH-05."""

    def test_an_math_01_odd_and_even_slot_medians_are_exact(self) -> None:
        self.assertEqual(slot_median([1, 3, 7]), Decimal(3))
        self.assertEqual(slot_median([7, 1, 3]), Decimal(3))
        self.assertEqual(slot_median([1, 3, 7, 9]), Decimal(5))

    def test_an_math_01_booleans_and_non_integers_are_rejected(self) -> None:
        for samples in ([True], [1, False], [1.0], ["1"]):
            with self.subTest(samples=samples):
                with self.assertRaises(BenchError) as caught:
                    slot_median(samples)  # type: ignore[arg-type]
                self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_an_math_02_block_mean_and_lower_better_effect(self) -> None:
        baseline = arm_block_value([dec("10"), dec("14")])
        candidate = arm_block_value([dec("8"), dec("10")])
        self.assertEqual(baseline, Decimal(12))
        self.assertEqual(candidate, Decimal(9))
        self.assertEqual(
            format_effect(normalized_effect(candidate, baseline, "lower-is-better")),
            "0.750000000000",
        )

    def test_an_math_03_slots_are_never_pooled_across_samples(self) -> None:
        # Two slots of three samples each. The block value is the mean of the two
        # slot medians (10 and 1000 => 505); pooling all six samples would yield
        # the median 10 and would therefore hide the slow second slot entirely.
        slot_one = slot_median([10, 10, 10])
        slot_two = slot_median([10, 1000, 1000])
        self.assertEqual(slot_one, Decimal(10))
        self.assertEqual(slot_two, Decimal(1000))
        self.assertEqual(arm_block_value([slot_one, slot_two]), Decimal(505))
        pooled = slot_median([10, 10, 10, 10, 1000, 1000])
        self.assertEqual(pooled, Decimal(10))
        self.assertNotEqual(arm_block_value([slot_one, slot_two]), pooled)

    def test_an_math_05_half_integer_median_and_half_even_quantisation(self) -> None:
        self.assertEqual(slot_median([1, 2]), dec("1.5"))
        self.assertEqual(slot_median([2, 1, 4, 3]), dec("2.5"))
        with localcontext(decimal_context()):
            self.assertEqual(
                format(dec("0.8333333333335").quantize(dec("0.000000000001")), "f"),
                "0.833333333334",
            )
            self.assertEqual(
                format(dec("0.8333333333325").quantize(dec("0.000000000001")), "f"),
                "0.833333333332",
            )
            self.assertEqual(
                format(dec("0.8000000000005").quantize(dec("0.000000000001")), "f"),
                "0.800000000000",
            )
        self.assertEqual(format_effect(Decimal(1)), "1.000000000000")

    def test_an_math_06_corrupt_inputs_are_typed_rejections(self) -> None:
        cases = [
            lambda: slot_median([]),
            lambda: slot_median([0]),
            lambda: slot_median([-1]),
            lambda: arm_block_value([]),
            lambda: arm_block_value([dec("Infinity")]),
            lambda: normalized_effect(dec("1"), dec("0"), "lower-is-better"),
            lambda: normalized_effect(dec("NaN"), dec("1"), "lower-is-better"),
            lambda: normalized_effect(dec("1"), dec("1"), "sideways"),
            lambda: median([]),
            lambda: geometric_mean([dec("0")]),
        ]
        for index, call in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(BenchError) as caught:
                    call()
                self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_an_math_06_unpaired_duplicate_and_out_of_order_block_rows_reject(self) -> None:
        from quervant_bench.analysis.arithmetic import require_block_rows

        duplicate = ((1, dec("10"), dec("8")), (1, dec("10"), dec("9")))
        out_of_order = ((2, dec("10"), dec("8")), (1, dec("10"), dec("9")))
        with self.assertRaises(BenchError) as caught:
            require_block_rows(duplicate)
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)
        with self.assertRaises(BenchError):
            require_block_rows(out_of_order)
        # A malformed row is still rejected by the estimator itself.
        with self.assertRaises(BenchError) as short:
            median_paired_ratios(((1, dec("10")),), "lower-is-better")  # type: ignore[arg-type]
        self.assertEqual(short.exception.code, BM_SCHEMA_INVALID)


class EstimatorDistinctionTests(unittest.TestCase):
    """AN-MATH-04 and AN-MATH-07: the two estimators are not equivalent."""

    ROWS = (
        (1, dec("10"), dec("10")),
        (2, dec("20"), dec("50")),
        (3, dec("100"), dec("50")),
    )

    def test_an_math_04_median_of_ratios_differs_from_ratio_of_medians(self) -> None:
        ratios = [dec("1"), dec("2.5"), dec("0.5")]
        self.assertEqual(sorted(ratios), [dec("0.5"), dec("1"), dec("2.5")])
        self.assertEqual(
            format_effect(median_paired_ratios(self.ROWS, "lower-is-better")),
            "1.000000000000",
        )
        self.assertEqual(
            format_effect(ratio_of_arm_medians(self.ROWS, "lower-is-better")),
            "2.500000000000",
        )
        self.assertNotEqual(
            median_paired_ratios(self.ROWS, "lower-is-better"),
            ratio_of_arm_medians(self.ROWS, "lower-is-better"),
        )
        self.assertEqual(
            format_effect(
                compute_paired_effect(self.ROWS, "lower-is-better", "median-paired-ratios-v1")
            ),
            "1.000000000000",
        )
        self.assertEqual(
            format_effect(
                compute_paired_effect(self.ROWS, "lower-is-better", "ratio-of-arm-medians-v1")
            ),
            "2.500000000000",
        )
        with self.assertRaises(BenchError):
            compute_paired_effect(self.ROWS, "lower-is-better", "invented-estimator-v1")

    def test_an_math_07_geometric_mean_goldens(self) -> None:
        self.assertEqual(
            format_effect(geometric_mean([dec("0.8"), dec("1.25")])),
            "1.000000000000",
        )
        self.assertEqual(
            format_effect(geometric_mean([dec("0.25"), dec("0.25"), dec("4"), dec("4")])),
            "1.000000000000",
        )

    def test_an_math_07_worst_campaign_gm_is_the_maximum(self) -> None:
        self.assertEqual(
            worst_campaign_gm([dec("0.8"), dec("0.9")]), dec("0.9")
        )
        # A single campaign GM of zero/negative is impossible to construct safely.
        with self.assertRaises(BenchError):
            worst_campaign_gm([])


class DirectionAwarenessTests(unittest.TestCase):
    """AN-DIR-01…06."""

    def test_an_dir_01_lower_is_better_normalises_to_candidate_over_baseline(self) -> None:
        self.assertEqual(
            format_effect(normalized_effect(dec("80"), dec("100"), "lower-is-better")),
            "0.800000000000",
        )

    def test_an_dir_02_higher_is_better_normalises_to_baseline_over_candidate(self) -> None:
        self.assertEqual(
            format_effect(normalized_effect(dec("125"), dec("100"), "higher-is-better")),
            "0.800000000000",
        )
        self.assertEqual(
            format_effect(normalized_effect(dec("80"), dec("100"), "higher-is-better")),
            "1.250000000000",
        )

    def test_an_dir_03_target_thresholds_behave_identically_across_directions(self) -> None:
        for direction in ("lower-is-better", "higher-is-better"):
            with self.subTest(direction=direction):
                profile = make_policy_profile(metric_direction=direction)
                document = analysis_document(
                    default_campaigns(campaigns=2)
                )
                decision = evaluate_policy(
                    document, profile, make_resources(), minimum_retained_blocks=3
                )
                self.assertEqual(decision.selected_arm_id, "candidate")
                self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")

    def test_an_dir_04_guardrails_behave_identically_across_directions(self) -> None:
        failing = ("0.833333333333", "0.833333333333", "1.100000000001", "1.100000000001", "analyzed")
        for direction in ("lower-is-better", "higher-is-better"):
            with self.subTest(direction=direction):
                profile = make_policy_profile(metric_direction=direction)
                document = analysis_document(
                    default_campaigns(common=failing, campaigns=2)
                )
                decision = evaluate_policy(
                    document, profile, make_resources(), minimum_retained_blocks=3
                )
                self.assertEqual(decision.selected_arm_id, None)
                self.assertEqual(decision.decision_status, "INCONCLUSIVE")
                codes = {reason.code for reason in decision.reasons}
                self.assertIn("GUARDRAIL_UNPROVEN", codes)

    def test_an_dir_05_candidate_identity_is_never_silently_swapped(self) -> None:
        forward = normalized_effect(dec("80"), dec("100"), "lower-is-better")
        reversed_identity = normalized_effect(dec("100"), dec("80"), "lower-is-better")
        self.assertEqual(format_effect(forward), "0.800000000000")
        self.assertEqual(format_effect(reversed_identity), "1.250000000000")
        self.assertEqual(
            format_effect(forward * reversed_identity), "1.000000000000"
        )

    def test_an_dir_06_direction_binding_mismatch_rejects(self) -> None:
        from quervant_bench.analysis.policy import validate_policy_profile
        from quervant_bench.tests.analysis_support import (
            load_bundle,
            policy_profile_document,
        )

        document = policy_profile_document()
        document["metric_direction"] = "higher-is-better"
        with self.assertRaises(BenchError) as caught:
            validate_policy_profile(document, load_bundle())
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "metric_direction")

    def test_an_dir_06_non_canonical_decimal_literals_reject(self) -> None:
        for literal in ("+0.8", "0.8000000000000", "1e-1", " 0.8", True, 0.8):
            with self.subTest(literal=literal):
                with self.assertRaises(BenchError) as caught:
                    parse_decimal_literal(literal, "value")
                self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)


class ExactBoundaryArithmeticTests(unittest.TestCase):
    """Supporting checks used by the policy-matrix tests."""

    def test_relative_delta_is_exact(self) -> None:
        self.assertEqual(
            format_effect(relative_delta(dec("1"), dec("1.03"))),
            "0.030000000000",
        )
        self.assertEqual(quantize_effect(dec("1.0")), dec("1.000000000000"))

    def test_effect_literals_require_twelve_places(self) -> None:
        from quervant_bench.analysis.contracts import require_formatted_effect

        self.assertEqual(
            require_formatted_effect("0.800000000000", "value"), dec("0.8")
        )
        with self.assertRaises(BenchError):
            require_formatted_effect("0.8", "value")
        with self.assertRaises(BenchError):
            require_formatted_effect(0.8, "value")  # type: ignore[arg-type]

    def test_hand_authored_lane_rows_are_usable(self) -> None:
        rows = lane_row("rare-query", [candidate_row()])
        self.assertEqual(rows["retained_blocks"], [1, 2, 3, 4])
        self.assertEqual(effect("0.8"), dec("0.8"))


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    unittest.main()

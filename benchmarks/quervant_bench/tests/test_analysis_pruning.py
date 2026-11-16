"""AN-PRUNE-01…09: symmetric whole-pair exclusions and retained-block processing.

Positive cases assert retention; negative cases assert that the *entire* lane/block
is removed for every arm — never just the offending one — and that a missing or
duplicated slot is a typed structural error rather than a plausible exclusion.
"""

from __future__ import annotations

import copy
import unittest
from decimal import Decimal

from quervant_bench.analysis.contracts import LANE_STATUS_INSUFFICIENT
from quervant_bench.analysis.derive import derive_lane_estimates
from quervant_bench.analysis.pruning import (
    apply_lane_block_exclusions,
    arm_block_values,
    within_arm_spread,
)
from quervant_bench.analysis.profiles import validate_analysis_profile
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BenchError,
)
from quervant_bench.tests.analysis_support import (
    analysis_profile_document,
    effect,
    load_analysis_profile,
    load_bundle,
    make_policy_profile,
    make_resources,
    analysis_document,
    lane_row,
    candidate_row,
)
from quervant_bench.analysis.policy import evaluate_policy


def medians(*values: str) -> list[Decimal]:
    return [effect(value) for value in values]


def two_arm_blocks(
    baseline: list[list[str]], candidate: list[list[str]]
) -> dict[int, dict[str, list[Decimal]]]:
    """Build ``block -> arm -> slot medians`` from per-block literal lists."""

    return {
        index + 1: {
            "baseline": medians(*baseline[index]),
            "candidate": medians(*candidate[index]),
        }
        for index in range(len(baseline))
    }


class ExclusionRuleTests(unittest.TestCase):
    """AN-PRUNE-01…05, AN-PRUNE-07…09."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_analysis_profile()

    def test_an_prune_01_spread_exactly_at_the_cap_is_retained(self) -> None:
        board = two_arm_blocks([["10", "15"]], [["10", "10"]])
        self.assertEqual(within_arm_spread(medians("10", "15")), Decimal("1.5"))
        ledger = apply_lane_block_exclusions(board, self.profile, "rare-query")
        self.assertEqual(ledger.retained_blocks, (1,))
        self.assertEqual(ledger.excluded_blocks, ())
        self.assertEqual(ledger.rows[0].status, "retained")
        self.assertEqual(ledger.rows[0].reason, "none")
        self.assertEqual(ledger.rows[0].trigger_arms, ())

    def test_an_prune_02_baseline_spread_over_cap_excludes_the_whole_pair(self) -> None:
        board = two_arm_blocks([["10", "16"]], [["10", "10"]])
        ledger = apply_lane_block_exclusions(board, self.profile, "rare-query")
        self.assertEqual(ledger.retained_blocks, ())
        self.assertEqual(ledger.excluded_blocks, (1,))
        self.assertEqual(ledger.rows[0].trigger_arms, ("baseline",))
        # Both arms are removed from the retained set, not only the offender.
        values = arm_block_values(board)
        self.assertIn("candidate", values[1])
        self.assertEqual(ledger.rows[0].arm_spreads[0][0], "baseline")

    def test_an_prune_03_candidate_spread_over_cap_excludes_the_whole_pair(self) -> None:
        board = two_arm_blocks([["10", "10"]], [["10", "16"]])
        ledger = apply_lane_block_exclusions(board, self.profile, "rare-query")
        self.assertEqual(ledger.retained_blocks, ())
        self.assertEqual(ledger.excluded_blocks, (1,))
        self.assertEqual(ledger.rows[0].trigger_arms, ("candidate",))
        mirror = apply_lane_block_exclusions(
            two_arm_blocks([["10", "16"]], [["10", "10"]]),
            self.profile,
            "rare-query",
        )
        # The rule is symmetric: the same spread on either arm excludes both.
        self.assertEqual(ledger.excluded_blocks, mirror.excluded_blocks)

    def test_an_prune_04_other_blocks_and_lanes_are_unaffected(self) -> None:
        board = {
            1: {"baseline": medians("10", "10"), "candidate": medians("10", "10")},
            2: {"baseline": medians("10", "16"), "candidate": medians("10", "10")},
            3: {"baseline": medians("10", "10"), "candidate": medians("10", "10")},
            4: {"baseline": medians("10", "10"), "candidate": medians("10", "10")},
        }
        ledger = apply_lane_block_exclusions(board, self.profile, "rare-query")
        self.assertEqual(ledger.retained_blocks, (1, 3, 4))
        self.assertEqual(ledger.excluded_blocks, (2,))
        self.assertEqual([row.block for row in ledger.rows], [1, 2, 3, 4])
        # Raw input is preserved verbatim; nothing was deleted or rewritten.
        self.assertEqual(board[2]["baseline"], medians("10", "16"))
        other = apply_lane_block_exclusions(
            {
                block: {
                    "baseline": medians("10", "10"),
                    "candidate": medians("10", "10"),
                }
                for block in (1, 2, 3, 4)
            },
            self.profile,
            "common-query",
        )
        self.assertEqual(other.retained_blocks, (1, 2, 3, 4))

    def test_an_prune_05_exclusion_ignores_the_effect_direction(self) -> None:
        favorable = two_arm_blocks([["10", "16"]], [["5", "5"]])
        unfavorable = two_arm_blocks([["10", "16"]], [["40", "40"]])
        favorable_ledger = apply_lane_block_exclusions(
            favorable, self.profile, "rare-query"
        )
        unfavorable_ledger = apply_lane_block_exclusions(
            unfavorable, self.profile, "rare-query"
        )
        self.assertEqual(favorable_ledger.excluded_blocks, (1,))
        self.assertEqual(unfavorable_ledger.excluded_blocks, (1,))

    def test_an_prune_07_missing_arm_or_slot_is_a_typed_error(self) -> None:
        inconsistent = {
            1: {"baseline": medians("10"), "candidate": medians("10")},
            2: {"baseline": medians("10")},
        }
        with self.assertRaises(BenchError) as caught:
            apply_lane_block_exclusions(inconsistent, self.profile, "rare-query")
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        empty_arm = {1: {"baseline": [], "candidate": medians("10")}}
        with self.assertRaises(BenchError) as empty:
            apply_lane_block_exclusions(empty_arm, self.profile, "rare-query")
        self.assertEqual(empty.exception.code, BM_SCHEMA_INVALID)
        non_contiguous = {1: {"baseline": medians("10")}, 3: {"baseline": medians("10")}}
        with self.assertRaises(BenchError) as gap:
            apply_lane_block_exclusions(non_contiguous, self.profile, "rare-query")
        self.assertEqual(gap.exception.code, BM_IDENTITY_INVALID)

    def test_an_prune_08_one_step_over_the_cap_is_excluded(self) -> None:
        board = two_arm_blocks([["10", "15.000000000001"]], [["10", "10"]])
        ledger = apply_lane_block_exclusions(board, self.profile, "rare-query")
        self.assertEqual(ledger.excluded_blocks, (1,))

    def test_an_prune_09_a_changed_frozen_cap_rejects_via_the_digest(self) -> None:
        document = analysis_profile_document()
        document["exclusion"]["per_lane_caps"][0]["max_within_arm_ratio"] = "1.400000000000"
        with self.assertRaises(BenchError) as caught:
            validate_analysis_profile(document, load_bundle())
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "analysis_digest")

    def test_an_prune_unknown_lane_cap_rejects(self) -> None:
        board = two_arm_blocks([["10", "10"]], [["10", "10"]])
        with self.assertRaises(BenchError) as caught:
            apply_lane_block_exclusions(board, self.profile, "undeclared-lane")
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)


class InsufficientRetainedBlocksTests(unittest.TestCase):
    """AN-PRUNE-06: two retained blocks under a three-block minimum."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_analysis_profile()

    def board(self) -> dict[int, dict[str, list[Decimal]]]:
        return two_arm_blocks(
            [["10", "10"], ["10", "16"], ["10", "10"], ["10", "16"]],
            [["8", "8"], ["8", "8"], ["8", "8"], ["8", "8"]],
        )

    def test_an_prune_06_ledger_retains_two_blocks(self) -> None:
        ledger = apply_lane_block_exclusions(self.board(), self.profile, "rare-query")
        self.assertEqual(ledger.retained_blocks, (1, 3))
        self.assertEqual(ledger.excluded_blocks, (2, 4))

    def test_an_prune_06_insufficient_lane_nulls_the_retained_estimate(self) -> None:
        ledger, candidates = derive_lane_estimates(
            block_slot_medians=self.board(),
            analysis_profile=self.profile,
            campaign_index=0,
            lane_id="rare-query",
            baseline_arm_id="baseline",
            candidate_ids=("candidate",),
            direction="lower-is-better",
            protocol_digest=load_bundle().protocol_digest,
            minimum_retained=3,
        )
        self.assertEqual(ledger.retained_blocks, (1, 3))
        estimate = candidates[0]
        self.assertEqual(estimate.status, LANE_STATUS_INSUFFICIENT)
        self.assertIsNone(estimate.retained_point_effect)
        self.assertIsNone(estimate.ci_low)
        self.assertIsNone(estimate.ci_high)
        self.assertIsNone(estimate.bootstrap_stream_digest)
        # The raw unfiltered point estimate and every raw block effect survive.
        self.assertIsNotNone(estimate.raw_point_effect)
        self.assertEqual([effect.block for effect in estimate.raw_block_effects], [1, 2, 3, 4])
        self.assertEqual(estimate.retained_block_effects, ())

    def test_an_prune_06_policy_reports_inconclusive_and_never_selects(self) -> None:
        insufficient = ("0.800000000000", None, None, None, "inconclusive-insufficient-blocks")
        document = analysis_document(
            [
                [
                    lane_row(
                        "rare-query",
                        [candidate_row(raw="0.800000000000", retained=None, low=None, high=None, status="inconclusive-insufficient-blocks")],
                        retained_blocks=2,
                    ),
                    lane_row(
                        "common-query",
                        [candidate_row()],
                    ),
                ],
                [
                    lane_row(
                        "rare-query",
                        [candidate_row(raw="0.800000000000", retained=None, low=None, high=None, status="inconclusive-insufficient-blocks")],
                        retained_blocks=2,
                    ),
                    lane_row(
                        "common-query",
                        [candidate_row()],
                    ),
                ],
            ]
        )
        del insufficient
        decision = evaluate_policy(
            document,
            make_policy_profile(),
            make_resources(),
            minimum_retained_blocks=3,
        )
        self.assertIsNone(decision.selected_arm_id)
        self.assertEqual(decision.decision_status, "INCONCLUSIVE")
        codes = {reason.code for reason in decision.reasons}
        self.assertIn("INSUFFICIENT_RETAINED_BLOCKS", codes)
        self.assertEqual(decision.ranking, ())


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    unittest.main()

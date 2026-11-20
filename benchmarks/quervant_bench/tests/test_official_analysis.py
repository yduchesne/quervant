"""O09-ANA: frozen per-family Gate B arithmetic and policy semantics."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.errors import BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID, BenchError
from quervant_bench.official import admission, analysis
from quervant_bench.tests import official_support as support


class PrimitiveTests(unittest.TestCase):
    def test_o09_ana_01_three_trial_median_is_the_middle_trial(self) -> None:
        self.assertEqual(analysis.lower_median([20, 10, 15]), 15)
        self.assertEqual(analysis.lower_median([30, 15, 18]), 18)

    def test_o09_ana_02_comparator_ratio_is_not_reciprocal(self) -> None:
        ratio = analysis.exact_ratio(18, 15)
        self.assertEqual(f"{ratio.numerator}/{ratio.denominator}", "6/5")
        self.assertGreater(ratio, 1)

    def test_o09_ana_03_dispersion_boundary_is_inclusive(self) -> None:
        self.assertEqual(analysis.dispersion([100, 110]), analysis.CROSS_ENGINE_DISPERSION_LIMIT)
        self.assertGreater(analysis.dispersion([100, 111]), analysis.CROSS_ENGINE_DISPERSION_LIMIT)

    def test_o09_ana_04_twenty_sample_median_is_sorted_9(self) -> None:
        values = [index for index in range(1, 21)]
        self.assertEqual(analysis.lower_median(values), 10)
        self.assertEqual(analysis.nearest_rank(values, 95), 19)

    def test_o09_ana_09_retained_key_four_value_median_is_lower_middle(self) -> None:
        self.assertEqual(analysis.lower_median([1, 2, 100, 200]), 2)
        self.assertNotEqual(analysis.lower_median([1, 2, 100, 200]), 51)


class CrossEngineAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_cross_engine_fixture(cls.root)
        cls.admitted = support.admit_fixture_cross_engine(cls.fixture)
        cls.analysis, cls.policy = analysis.analyze_official_study(
            admitted=cls.admitted, template=cls.fixture.template
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_o09_ana_05_only_warm_lanes_are_eligible(self) -> None:
        self.assertEqual(len(self.analysis["eligible_lane_ids"]), 16)
        cold = self.analysis["campaigns"][1]["descriptive_process_cold"]
        self.assertEqual(len(cold), 16)
        self.assertEqual(self.analysis["excluded_lane_classes"], ["process_cold", "scored_bm25", "throughput"])

    def test_o09_ana_06_all_sixteen_warm_lanes_are_present(self) -> None:
        lanes = self.analysis["statistics"]["lanes"]
        self.assertEqual(len(lanes), 16)
        self.assertEqual(
            [lane["lane_id"] for lane in lanes], sorted(lane["lane_id"] for lane in lanes)
        )

    def test_o09_ana_07_throughput_is_not_part_of_the_ratio_statistics(self) -> None:
        for lane in self.analysis["statistics"]["lanes"]:
            self.assertNotIn("throughput", lane)
            self.assertEqual(self.analysis["statistics"]["unit"], "nanoseconds")

    def test_o09_ana_08_missing_lane_forces_a_rejection(self) -> None:
        from quervant_bench.official.contracts import validate_official_analysis

        analysis_document = copy.deepcopy(self.analysis)
        analysis_document["eligible_lane_ids"] = analysis_document["eligible_lane_ids"][:-1]
        with self.assertRaises(BenchError) as raised:
            validate_official_analysis(analysis_document)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_ana_10_dispersion_and_overlap_are_recorded(self) -> None:
        lane = self.analysis["statistics"]["lanes"][0]
        for comparison in lane["comparisons"]:
            self.assertIn(comparison["comparator"], ("lucene", "tantivy"))
            self.assertEqual(
                comparison["inconclusive"],
                (not comparison["dispersion_ok"]) or comparison["ranges_overlap"],
            )

    def test_o09_ana_11_cross_engine_policy_is_inconclusive_and_claims_nothing(self) -> None:
        self.assertEqual(self.policy["decision_status"], "INCONCLUSIVE")
        self.assertIsNone(self.policy["selected_arm_id"])
        self.assertFalse(self.policy["performance_claim_allowed"])

    def test_o09_ana_12_adverse_or_favourable_ratios_never_change_the_policy(self) -> None:
        decisions = analysis._cross_engine_decisions()
        policy = analysis.derive_official_policy(
            study_id="cross-engine-keyword-real-v1",
            subject=self.analysis["subject"],
            analysis_document=self.analysis,
            policy_profile_digest=self.policy["policy_digest"],
            decisions=decisions,
        )
        self.assertEqual(policy["decision_status"], "INCONCLUSIVE")
        with self.assertRaises(BenchError):
            analysis.derive_official_policy(
                study_id="cross-engine-keyword-real-v1",
                subject=self.analysis["subject"],
                analysis_document=self.analysis,
                policy_profile_digest=self.policy["policy_digest"],
                decisions=dict(decisions, decision_status="SELECTED_ELIGIBLE_REAL"),
            )


class RetainedKeyAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.fixture = support.make_retained_key_fixture(cls.root)
        cls.admitted = support.admit_fixture_retained_key(cls.fixture)
        cls.analysis, cls.policy = analysis.analyze_official_study(
            admitted=cls.admitted, template=cls.fixture.template
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_o09_ana_13_each_campaign_and_lane_appears_once(self) -> None:
        lanes = self.analysis["statistics"]["lanes"]
        self.assertEqual(len(lanes), 144)
        coordinates = {(lane["campaign_id"], lane["lane_id"]) for lane in lanes}
        self.assertEqual(len(coordinates), len(lanes))
        self.assertEqual(len(self.analysis["eligible_lane_ids"]), 72)

    def test_o09_ana_14_arm_identities_are_the_frozen_four(self) -> None:
        self.assertEqual(self.analysis["statistics"]["arms"], ["base", "exact-set", "linear", "prefilter"])
        for lane in self.analysis["statistics"]["lanes"]:
            self.assertEqual(
                set(lane["arms"]), {"base", "exact-set", "linear", "prefilter"}
            )

    def test_o09_ana_15_retained_and_excluded_blocks_partition_the_blocks(self) -> None:
        for lane in self.analysis["statistics"]["lanes"]:
            for arm in lane["arms"].values():
                self.assertEqual(
                    sorted(arm["retained_block_indices"] + arm["excluded_block_indices"]),
                    list(range(1, 13)),
                )

    def test_o09_ana_16_within_arm_cap_is_class_specific(self) -> None:
        template = self.fixture.template
        self.assertEqual(
            analysis.within_arm_cap(template, n=100_000, class_name="medium"),
            analysis.within_arm_cap(template, n=100_000, class_name="common"),
        )
        self.assertLess(
            analysis.within_arm_cap(template, n=100_000, class_name="medium"),
            analysis.within_arm_cap(template, n=10_000, class_name="medium"),
        )
        self.assertEqual(
            analysis.within_arm_cap(template, n=10_000, class_name="medium"),
            analysis.within_arm_cap(template, n=100_000, class_name="absent"),
        )

    def test_o09_ana_16b_symmetric_pruning_keeps_only_in_range_blocks(self) -> None:
        retained = analysis.retained_block_indices([100, 100, 100, 200], analysis.within_arm_cap(
            self.fixture.template, n=10_000, class_name="absent"
        ))
        self.assertEqual(retained, [1, 2, 3])

    def test_o09_ana_16c_insufficient_blocks_are_flagged(self) -> None:
        values = [100, 100, 300, 300]
        retained = analysis.retained_block_indices(
            values, analysis.within_arm_cap(self.fixture.template, n=10_000, class_name="absent")
        )
        self.assertLess(len(retained), 4)

    def test_o09_ana_16d_undeducible_policy_is_never_selected(self) -> None:
        self.assertEqual(self.policy["decision_status"], "POLICY_NOT_DERIVABLE")
        self.assertIsNone(self.policy["selected_arm_id"])
        self.assertFalse(self.policy["performance_claim_allowed"])
        with self.assertRaises(BenchError) as raised:
            analysis.require_resolved_policy(self.policy)
        self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)

    def test_o09_ana_16e_tie_preference_never_claims_a_speed_win(self) -> None:
        decisions = analysis.nine_k_decisions(
            selected_arm_id="prefilter",
            tie=True,
            reasons=["tie-preference"],
            candidate_statuses={"prefilter": "ELIGIBLE"},
        )
        self.assertEqual(decisions["decision_status"], "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertFalse(decisions["performance_claim_allowed"])


class PolicyRecordTests(unittest.TestCase):
    def test_o09_ana_20_policy_profile_digest_is_pure(self) -> None:
        first = analysis.policy_profile_digest("retained-key-topk-real-v1", "t7-f2-nine-k-v1")
        second = analysis.policy_profile_digest("retained-key-topk-real-v1", "t7-f2-nine-k-v1")
        self.assertEqual(first, second)
        self.assertNotEqual(
            first, analysis.policy_profile_digest("retained-key-topk-real-v1", "other-chain")
        )

    def test_o09_ana_20b_invalid_policy_subject_is_rejected(self) -> None:
        with self.assertRaises(BenchError):
            analysis.derive_official_policy(
                study_id="retained-key-topk-real-v1",
                subject={
                    "experiment_id": "retained-key-topk-real-v1",
                    "run_id": "not-a-uuid",
                    "protocol_digest": "sha256:" + "a" * 64,
                    "workload_digest": "sha256:" + "b" * 64,
                },
                analysis_document={},
                policy_profile_digest="sha256:" + "c" * 64,
                template=None,
            )


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()

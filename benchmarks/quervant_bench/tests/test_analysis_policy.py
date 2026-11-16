"""AN-POL-01…18 and AN-SEL-01…10: exact policy boundaries and selection.

Every case here uses a **hand-authored** analysis record so that a boundary
assertion can never be produced by bootstrap variability. Threshold comparisons are
exact `Decimal` comparisons against the canonical 12-place values.
"""

from __future__ import annotations

import unittest

from quervant_bench.analysis.policy import (
    evaluate_policy,
    validate_policy_profile,
    validate_resource_observations,
)
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BenchError,
)
from quervant_bench.tests.analysis_support import (
    analysis_document,
    campaigns_for,
    default_campaigns,
    load_bundle,
    make_policy_profile,
    make_resources,
    policy_profile_document,
    resource_document,
)

PASSING = ("0.800000000000", "0.800000000000", "0.800000000000", "0.800000000000", "analyzed")


def evaluate(
    *,
    rare=PASSING,
    common=PASSING,
    profile=None,
    resources=None,
    campaigns=2,
):
    return evaluate_policy(
        analysis_document(default_campaigns(rare=rare, common=common, campaigns=campaigns)),
        profile or make_policy_profile(),
        resources or make_resources(),
        minimum_retained_blocks=3,
    )


def codes(decision) -> set[str]:
    return {reason.code for reason in decision.reasons}


class TargetBoundaryTests(unittest.TestCase):
    """AN-POL-01…04: strict CI upper bound and inclusive point bound."""

    def test_an_pol_01_ci_high_strictly_below_passes(self) -> None:
        decision = evaluate(
            rare=("0.900000000000", "0.900000000000", "0.800000000000", "0.999999999999", "analyzed")
        )
        self.assertEqual(decision.selected_arm_id, "candidate")
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")

    def test_an_pol_02_point_exactly_at_the_target_bound_passes(self) -> None:
        decision = evaluate(
            rare=("0.950000000000", "0.950000000000", "0.800000000000", "0.999999999999", "analyzed")
        )
        self.assertEqual(decision.selected_arm_id, "candidate")

    def test_an_pol_03_ci_high_exactly_at_the_strict_bound_is_unproven(self) -> None:
        decision = evaluate(
            rare=("0.900000000000", "0.900000000000", "0.800000000000", "1.000000000000", "analyzed")
        )
        self.assertIsNone(decision.selected_arm_id)
        self.assertEqual(decision.decision_status, "INCONCLUSIVE")
        self.assertIn("TARGET_UNPROVEN", codes(decision))
        self.assertNotIn("TARGET_DECISIVE_FAILURE", codes(decision))

    def test_an_pol_04_point_over_target_but_ci_below_is_unproven(self) -> None:
        decision = evaluate(
            rare=("0.960000000000", "0.960000000000", "0.900000000000", "0.999999999999", "analyzed")
        )
        self.assertIsNone(decision.selected_arm_id)
        self.assertIn("TARGET_UNPROVEN", codes(decision))


class GuardrailBoundaryTests(unittest.TestCase):
    """AN-POL-05…08: inclusive CI upper bound and decisive-failure conditions."""

    def test_an_pol_05_guardrail_ci_high_at_the_inclusive_bound_passes(self) -> None:
        decision = evaluate(
            common=("1.050000000000", "1.050000000000", "1.000000000000", "1.100000000000", "analyzed")
        )
        self.assertEqual(decision.selected_arm_id, "candidate")

    def test_an_pol_06_guardrail_above_the_bound_is_unproven(self) -> None:
        decision = evaluate(
            common=("1.050000000000", "1.050000000000", "1.000000000000", "1.100000000001", "analyzed")
        )
        self.assertIsNone(decision.selected_arm_id)
        self.assertIn("GUARDRAIL_UNPROVEN", codes(decision))
        self.assertNotIn("GUARDRAIL_DECISIVE_FAILURE", codes(decision))

    def test_an_pol_07_decisive_guardrail_failure_requires_both_bounds(self) -> None:
        decision = evaluate(
            common=("1.200000000000", "1.200000000000", "1.150000000000", "1.300000000000", "analyzed")
        )
        self.assertEqual(decision.candidate_results[0].status, "INELIGIBLE")
        self.assertIn("GUARDRAIL_DECISIVE_FAILURE", codes(decision))
        self.assertEqual(decision.selected_arm_id, "baseline")
        self.assertEqual(decision.decision_status, "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE")

    def test_an_pol_08_point_at_the_bound_is_not_a_decisive_failure(self) -> None:
        decision = evaluate(
            common=("1.100000000000", "1.100000000000", "1.150000000000", "1.300000000000", "analyzed")
        )
        self.assertEqual(decision.candidate_results[0].status, "INCONCLUSIVE")
        self.assertIn("GUARDRAIL_UNPROVEN", codes(decision))
        self.assertNotIn("GUARDRAIL_DECISIVE_FAILURE", codes(decision))


class ResourceBoundaryTests(unittest.TestCase):
    """AN-POL-09…12: exact integer caps and typed resource rejection."""

    def test_an_pol_09_exact_resource_equality_is_eligible(self) -> None:
        decision = evaluate(resources=make_resources(("candidate", "aux-memory-bytes", 2097152)))
        self.assertEqual(decision.selected_arm_id, "candidate")

    def test_an_pol_10_one_byte_over_the_cap_is_ineligible(self) -> None:
        decision = evaluate(resources=make_resources(("candidate", "aux-memory-bytes", 2097153)))
        self.assertEqual(decision.candidate_results[0].status, "INELIGIBLE")
        self.assertIn("RESOURCE_OVER_LIMIT", codes(decision))
        self.assertEqual(decision.selected_arm_id, "baseline")

    def test_an_pol_11_missing_resource_is_inconclusive_not_zero(self) -> None:
        decision = evaluate(resources=make_resources(("baseline", "aux-memory-bytes", 1)))
        self.assertEqual(decision.candidate_results[0].status, "INCONCLUSIVE")
        self.assertIn("MISSING_RESOURCE", codes(decision))
        self.assertIsNone(decision.selected_arm_id)
        self.assertEqual(decision.decision_status, "INCONCLUSIVE")

    def test_an_pol_12_malformed_resource_documents_are_typed_rejections(self) -> None:
        bundle = load_bundle()
        mutations = {
            "extra-key": lambda doc: doc.update({"unexpected": 1}),
            "bool-value": lambda doc: doc["records"][0].update({"value_bytes": True}),
            "negative": lambda doc: doc["records"][0].update({"value_bytes": -1}),
            "wrong-experiment": lambda doc: doc.update({"experiment_id": "other-experiment"}),
            "scope-promotion": lambda doc: doc.update(
                {"qualification_scope": "official", "evidence_origin": "real"}
            ),
            "duplicate": lambda doc: doc["records"].append(dict(doc["records"][0])),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                document = resource_document()
                mutate(document)
                with self.assertRaises(BenchError):
                    validate_resource_observations(document, bundle)
        with self.assertRaises(BenchError) as caught:
            validate_resource_observations({"kind": "not-resources"}, bundle)
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)


class PrecedenceTests(unittest.TestCase):
    """AN-POL-13…16 and AN-SEL-01…04."""

    def test_an_pol_13_ineligible_dominates_inconclusive(self) -> None:
        decision = evaluate(
            rare=("0.800000000000", None, None, None, "inconclusive-insufficient-blocks"),
            resources=make_resources(("candidate", "aux-memory-bytes", 2097153)),
        )
        self.assertEqual(decision.candidate_results[0].status, "INELIGIBLE")
        self.assertIn("RESOURCE_OVER_LIMIT", codes(decision))
        self.assertIn("INSUFFICIENT_RETAINED_BLOCKS", codes(decision))
        self.assertEqual(decision.selected_arm_id, "baseline")

    def test_an_pol_14_insufficient_evidence_never_selects(self) -> None:
        decision = evaluate(
            rare=("0.800000000000", None, None, None, "inconclusive-insufficient-blocks"),
        )
        self.assertIsNone(decision.selected_arm_id)
        self.assertEqual(decision.decision_status, "INCONCLUSIVE")
        self.assertEqual(decision.ranking, ())

    def test_an_pol_15_all_candidates_ineligible_selects_baseline_only(self) -> None:
        decision = evaluate(
            common=("1.200000000000", "1.200000000000", "1.150000000000", "1.300000000000", "analyzed"),
        )
        self.assertEqual(decision.selected_arm_id, "baseline")
        self.assertEqual(decision.decision_status, "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE")
        # A baseline-only outcome is explicitly not a proof the baseline is faster.
        self.assertNotIn("PASS", decision.decision_status)
        self.assertNotIn("winner_proven", decision.to_document(
            experiment_id="synthetic-analysis-smoke",
            run_id="00000000-0000-4000-8000-000000000000",
            analysis_digest="sha256:" + "0" * 64,
            policy_profile=make_policy_profile(),
            resource_digest="sha256:" + "0" * 64,
        ))

    def test_an_pol_16_reasons_are_complete_sorted_and_closed(self) -> None:
        decision = evaluate(
            rare=("0.960000000000", "0.960000000000", "0.900000000000", "1.000000000000", "analyzed"),
            common=("1.050000000000", "1.050000000000", "1.000000000000", "1.100000000001", "analyzed"),
        )
        self.assertIn("TARGET_UNPROVEN", codes(decision))
        self.assertIn("GUARDRAIL_UNPROVEN", codes(decision))
        keys = [
            (
                -1 if reason.campaign_index is None else reason.campaign_index,
                "" if reason.lane_id is None else reason.lane_id,
                reason.code,
            )
            for reason in decision.reasons
        ]
        self.assertEqual(keys, sorted(keys))

    def test_an_sel_01_exactly_one_eligible_candidate_is_selected(self) -> None:
        decision = evaluate()
        self.assertEqual(decision.selected_arm_id, "candidate")
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")
        self.assertEqual([entry.arm_id for entry in decision.ranking], ["candidate"])

    def test_an_sel_02_no_eligible_and_no_inconclusive_is_baseline_only(self) -> None:
        decision = evaluate(resources=make_resources(("candidate", "aux-memory-bytes", 2097153)))
        self.assertEqual(decision.decision_status, "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE")

    def test_an_sel_03_one_inconclusive_never_selects(self) -> None:
        decision = evaluate(
            common=("1.050000000000", "1.050000000000", "1.000000000000", "1.100000000001", "analyzed")
        )
        self.assertIsNone(decision.selected_arm_id)
        self.assertEqual(decision.decision_status, "INCONCLUSIVE")

    def test_an_sel_04_multiple_candidates_follow_the_exact_precedence(self) -> None:
        profile = make_policy_profile(
            candidate_order=("alpha", "beta"),
            tie_preference=("alpha", "beta"),
        )
        values = {
            "alpha": ("0.800000000000", "0.800000000000", "0.800000000000", "0.800000000000", "analyzed"),
            "beta": ("1.200000000000", "1.200000000000", "1.150000000000", "1.300000000000", "analyzed"),
        }
        document = analysis_document(campaigns_for(values))
        decision = evaluate_policy(
            document, profile, make_resources(), minimum_retained_blocks=3
        )
        statuses = {result.arm_id: result.status for result in decision.candidate_results}
        self.assertEqual(statuses, {"alpha": "ELIGIBLE", "beta": "INELIGIBLE"})
        self.assertEqual(decision.selected_arm_id, "alpha")


class FilterSensitivityTests(unittest.TestCase):
    """AN-POL-17 and AN-POL-18."""

    def test_an_pol_17_raw_to_retained_sign_change_is_filter_sensitive(self) -> None:
        decision = evaluate(
            rare=("1.050000000000", "0.800000000000", "0.800000000000", "0.800000000000", "analyzed")
        )
        self.assertIn("FILTER_SENSITIVE", codes(decision))
        self.assertIsNone(decision.selected_arm_id)
        self.assertEqual(decision.decision_status, "INCONCLUSIVE")

    def test_an_pol_18_unchanged_sign_is_not_filter_sensitive(self) -> None:
        decision = evaluate(
            rare=("0.900000000000", "0.800000000000", "0.800000000000", "0.800000000000", "analyzed")
        )
        self.assertNotIn("FILTER_SENSITIVE", codes(decision))
        self.assertEqual(decision.selected_arm_id, "candidate")


class SelectionTieTests(unittest.TestCase):
    """AN-SEL-05…10."""

    def two_candidate_decision(self, alpha: str, beta: str, *, tie_preference=("beta", "alpha"), direction="lower-is-better"):
        profile = make_policy_profile(
            candidate_order=("alpha", "beta"),
            tie_preference=tie_preference,
            metric_direction=direction,
        )
        values = {
            "alpha": (alpha, alpha, alpha, alpha, "analyzed"),
            "beta": (beta, beta, beta, beta, "analyzed"),
        }
        document = analysis_document(
            campaigns_for(values, direction=direction)
        )
        return evaluate_policy(
            document, profile, make_resources(), minimum_retained_blocks=3
        )

    def test_an_sel_05_delta_below_the_tie_threshold_prefers_the_declared_order(self) -> None:
        # |0.90 - 0.92| / 0.90 = 0.0222... < 0.03, so this is a tie.
        decision = self.two_candidate_decision("0.900000000000", "0.920000000000")
        self.assertEqual(decision.selected_arm_id, "beta")
        self.assertEqual(decision.decision_status, "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertEqual([entry.arm_id for entry in decision.ranking], ["alpha", "beta"])

    def test_an_sel_06_delta_exactly_at_the_threshold_is_not_a_tie(self) -> None:
        # |0.90 - 0.927| / 0.90 = 0.03 exactly, which is *not* strictly below.
        decision = self.two_candidate_decision("0.900000000000", "0.927000000000")
        self.assertEqual(decision.selected_arm_id, "alpha")
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")

    def test_an_sel_07_exact_gm_equality_always_ties(self) -> None:
        decision = self.two_candidate_decision("0.900000000000", "0.900000000000")
        self.assertEqual(decision.decision_status, "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertEqual(decision.selected_arm_id, "beta")
        flipped = self.two_candidate_decision(
            "0.900000000000", "0.900000000000", tie_preference=("alpha", "beta")
        )
        self.assertEqual(flipped.selected_arm_id, "alpha")

    def test_an_sel_08_higher_better_ranking_uses_normalised_effects(self) -> None:
        decision = self.two_candidate_decision(
            "0.900000000000", "0.940000000000", direction="higher-is-better"
        )
        # Normalised effects still rank lower-is-better, so alpha wins outright.
        self.assertEqual(decision.selected_arm_id, "alpha")
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")

    def test_an_sel_09_candidate_order_and_tie_preference_are_validated(self) -> None:
        bundle = load_bundle()
        mutations = {
            "missing-candidate": lambda doc: doc.update({"candidate_order": []}),
            "unknown-candidate": lambda doc: doc.update({"candidate_order": ["ghost-agent"]}),
            "baseline-as-candidate": lambda doc: doc.update({"candidate_order": ["baseline"]}),
            "duplicate-candidate": lambda doc: doc.update(
                {"candidate_order": ["candidate", "candidate"]}
            ),
            "bad-tie-preference": lambda doc: doc["selection"].update(
                {"tie_preference": ["someone-else"]}
            ),
            "unsorted-ranking-lanes": lambda doc: doc["selection"].update(
                {"ranking_lanes": ["rare-query", "common-query"]}
            ),
            "unlisted-ranking-lane": lambda doc: doc["selection"].update(
                {"ranking_lanes": ["missing-lane"]}
            ),
            "overlapping-target-guardrail": lambda doc: doc["guardrails"].append(
                dict(doc["targets"][0])
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                document = policy_profile_document()
                mutate(document)
                with self.assertRaises(BenchError) as caught:
                    validate_policy_profile(document, bundle)
                self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_an_sel_10_missing_ranking_lane_fails_closed(self) -> None:
        profile = make_policy_profile()
        document = analysis_document(
            [
                [
                    {
                        "lane_id": "rare-query",
                        "retained_blocks": [1, 2, 3, 4],
                        "candidates": [
                            {
                                "candidate_arm_id": "candidate",
                                "raw_point_effect": "0.800000000000",
                                "retained_point_effect": "0.800000000000",
                                "ci_low": "0.800000000000",
                                "ci_high": "0.800000000000",
                                "status": "analyzed",
                            }
                        ],
                    }
                ]
            ]
        )
        with self.assertRaises(BenchError) as caught:
            evaluate_policy(
                document, profile, make_resources(), minimum_retained_blocks=3
            )
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    unittest.main()

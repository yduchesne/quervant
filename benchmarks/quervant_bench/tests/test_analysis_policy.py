"""AN-POL-01…18 and AN-SEL-01…10: exact policy boundaries and selection.

Every case here uses a **hand-authored** analysis record so that a boundary
assertion can never be produced by bootstrap variability. Threshold comparisons are
exact `Decimal` comparisons against the canonical 12-place values.
"""

from __future__ import annotations

import copy
import unittest
from decimal import Decimal
from pathlib import Path

from quervant_bench.analysis.contracts import format_effect, validate_policy_decision
from quervant_bench.analysis.policy import (
    evaluate_policy,
    read_policy_profile,
    read_resource_observations,
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
    build_isolated_catalog,
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


# ---------------------------------------------------------------------------
# FX04 (independent-review fixup): RF04-01 multi-candidate selection validation,
# RF04-03 policy decimal rendering, RF04-04 policy campaign inventory.
#
# Expected rankings, statuses and selections below are hand-written literals; the
# production selector is exercised only as the system under test, never as the
# source of an expected value.
# ---------------------------------------------------------------------------

FIXED_RUN_ID = "00000000-0000-4000-8000-000000000000"
OPAQUE_DIGEST = "sha256:" + "1" * 64
TWO_CANDIDATE_ARGS = dict(
    experiment_id="synthetic-analysis-smoke",
    arms=("baseline", "alpha", "beta"),
    baseline_arm_id="baseline",
    candidate_order=("alpha", "beta"),
    tie_preference=("beta", "alpha"),
)
THREE_CANDIDATE_ARGS = dict(
    experiment_id="synthetic-analysis-smoke",
    arms=("baseline", "alpha", "beta", "gamma"),
    baseline_arm_id="baseline",
    candidate_order=("alpha", "beta", "gamma"),
    tie_preference=("alpha", "beta", "gamma"),
    targets=(("rare-query", "1.000000000000", "1.000000000000", "lt"),),
    guardrails=(("common-query", "1.100000000000", "1.100000000000", "le"),),
)


def _lanes(arm_id, value):
    return (str(value), str(value), str(value), str(value), "analyzed")


def _effect(value) -> str:
    return format_effect(effect(value))


class IsolatedPolicyCatalog:
    """A temp catalog plus its validated policy profile and resource records."""

    def __init__(self, temporary: Path, **arguments) -> None:
        self.root = temporary
        self.catalog = build_isolated_catalog(temporary, **arguments)
        self.bundle = self.catalog["bundle"]
        self.experiment_root = self.catalog["experiment_root"]
        self.profile = read_policy_profile(self.experiment_root, self.bundle)
        self.resources = read_resource_observations(self.experiment_root, self.bundle)

    def evaluate(self, values_by_arm, *, minimum_retained=3):
        document = analysis_document(campaigns_for(values_by_arm))
        return evaluate_policy(
            document,
            self.profile,
            self.resources,
            minimum_retained_blocks=minimum_retained,
        )

    def as_document(self, decision):
        return decision.to_document(
            experiment_id=self.bundle.experiment.experiment_id,
            run_id=FIXED_RUN_ID,
            analysis_digest=OPAQUE_DIGEST,
            policy_profile=self.profile,
            resource_digest=self.resources.digest,
        )

    def validate(self, document):
        return validate_policy_decision(
            document,
            self.bundle,
            self.profile,
            OPAQUE_DIGEST,
            self.resources.digest,
        )

    def assert_rejected(self, test, document, field_path=None):
        with test.assertRaises(BenchError) as caught:
            self.validate(document)
        test.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        if field_path is not None:
            test.assertEqual(caught.exception.field_path, field_path)


class PolicyCatalogMixin:
    """Build one two-candidate and one three-candidate catalog per test class."""

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile

        cls._two_tmp = tempfile.TemporaryDirectory()
        cls._three_tmp = tempfile.TemporaryDirectory()
        cls.two = IsolatedPolicyCatalog(
            Path(cls._two_tmp.name), **TWO_CANDIDATE_ARGS
        )
        cls.three = IsolatedPolicyCatalog(
            Path(cls._three_tmp.name), **THREE_CANDIDATE_ARGS
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._two_tmp.cleanup()
        cls._three_tmp.cleanup()


class MultiCandidateRankingTests(PolicyCatalogMixin, unittest.TestCase):
    """FX04-SEL-01…05: eligible ranking is sorted by GM, not declaration order."""

    def test_fx04_sel_01_gm_order_reversed_from_declaration_validates(self) -> None:
        decision = self.two.evaluate(
            {"alpha": _lanes("alpha", "0.900000000000"),
             "beta": _lanes("beta", "0.800000000000")}
        )
        # Literal expectations: beta has the smaller GM, so it ranks first and wins.
        self.assertEqual([entry.arm_id for entry in decision.ranking], ["beta", "alpha"])
        self.assertEqual(decision.selected_arm_id, "beta")
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")
        document = self.two.as_document(decision)
        self.two.validate(document)
        self.assertEqual(
            [entry["arm_id"] for entry in document["ranking"]], ["beta", "alpha"]
        )

    def test_fx04_sel_02_declaration_ordered_ranking_rejects(self) -> None:
        decision = self.two.evaluate(
            {"alpha": _lanes("alpha", "0.900000000000"),
             "beta": _lanes("beta", "0.800000000000")}
        )
        document = self.two.as_document(decision)
        document["ranking"] = list(reversed(document["ranking"]))
        self.two.assert_rejected(self, document, "ranking")

    def test_fx04_sel_03_forged_rank_gm_rejects(self) -> None:
        decision = self.two.evaluate(
            {"alpha": _lanes("alpha", "0.900000000000"),
             "beta": _lanes("beta", "0.800000000000")}
        )
        document = self.two.as_document(decision)
        # Keep the ascending order valid but disagree with the candidate result.
        document["ranking"][0]["worst_campaign_gm"] = "0.790000000000"
        self.two.assert_rejected(self, document, "ranking")

    def test_fx04_sel_04_equal_gm_ranks_by_declaration_and_ties(self) -> None:
        decision = self.two.evaluate(
            {"alpha": _lanes("alpha", "0.900000000000"),
             "beta": _lanes("beta", "0.900000000000")}
        )
        self.assertEqual([entry.arm_id for entry in decision.ranking], ["alpha", "beta"])
        self.assertEqual(decision.decision_status, "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertEqual(decision.selected_arm_id, "beta")
        self.two.validate(self.two.as_document(decision))

    def test_fx04_sel_05_equal_gm_ranked_by_preference_order_rejects(self) -> None:
        decision = self.two.evaluate(
            {"alpha": _lanes("alpha", "0.900000000000"),
             "beta": _lanes("beta", "0.900000000000")}
        )
        document = self.two.as_document(decision)
        document["ranking"] = list(reversed(document["ranking"]))
        self.two.assert_rejected(self, document, "ranking")


class MultiCandidateDecisionTests(PolicyCatalogMixin, unittest.TestCase):
    """FX04-SEL-06…12: decision status follows the frozen best-two/tie rule."""

    def test_fx04_sel_06_exact_three_percent_delta_is_not_a_tie(self) -> None:
        decision = self.two.evaluate(
            {"alpha": _lanes("alpha", "0.900000000000"),
             "beta": _lanes("beta", "0.927000000000")}
        )
        self.assertEqual(decision.selected_arm_id, "alpha")
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")
        document = self.two.as_document(decision)
        self.two.validate(document)
        document["decision_status"] = "TIE_PREFERENCE_NOT_PROVEN_FASTER"
        self.two.assert_rejected(self, document, "decision_status")

    def test_fx04_sel_07_below_threshold_is_a_tie_and_prefers_the_frozen_member(self) -> None:
        decision = self.two.evaluate(
            {"alpha": _lanes("alpha", "0.900000000000"),
             "beta": _lanes("beta", "0.920000000000")}
        )
        self.assertEqual(decision.decision_status, "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertEqual(decision.selected_arm_id, "beta")
        document = self.two.as_document(decision)
        self.two.validate(document)
        wrong_member = self.two.as_document(decision)
        wrong_member["selected_arm_id"] = "alpha"
        self.two.assert_rejected(self, wrong_member, "decision_status")
        wrong_status = self.two.as_document(decision)
        wrong_status["decision_status"] = "SELECTED_ELIGIBLE_SYNTHETIC"
        self.two.assert_rejected(self, wrong_status, "decision_status")

    def test_fx04_sel_08_three_eligible_clear_winner_ranks_last_declared(self) -> None:
        decision = self.three.evaluate(
            {
                "alpha": _lanes("alpha", "0.930000000000"),
                "beta": _lanes("beta", "0.900000000000"),
                "gamma": _lanes("gamma", "0.800000000000"),
            }
        )
        self.assertEqual(
            [entry.arm_id for entry in decision.ranking], ["gamma", "beta", "alpha"]
        )
        self.assertEqual(decision.selected_arm_id, "gamma")
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")
        self.three.validate(self.three.as_document(decision))

    def test_fx04_sel_09_only_the_top_pair_competes_in_a_tie(self) -> None:
        decision = self.three.evaluate(
            {
                "alpha": _lanes("alpha", "0.990000000000"),
                "beta": _lanes("beta", "0.810000000000"),
                "gamma": _lanes("gamma", "0.800000000000"),
            }
        )
        # alpha precedes in the preference order but is not in the top pair.
        self.assertEqual(decision.decision_status, "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertEqual(decision.selected_arm_id, "beta")
        document = self.three.as_document(decision)
        self.three.validate(document)
        document["selected_arm_id"] = "alpha"
        self.three.assert_rejected(self, document, "decision_status")

    def test_fx04_sel_10_no_eligible_with_inconclusive_never_falls_back(self) -> None:
        decision = self.two.evaluate(
            {
                "alpha": ("0.960000000000", "0.960000000000", "0.900000000000",
                          "0.990000000000", "analyzed"),
                "beta": ("1.200000000000", "1.200000000000", "1.150000000000",
                         "1.300000000000", "analyzed"),
            }
        )
        self.assertIsNone(decision.selected_arm_id)
        self.assertEqual(decision.decision_status, "INCONCLUSIVE")
        document = self.two.as_document(decision)
        self.two.validate(document)
        fallback = self.two.as_document(decision)
        fallback["selected_arm_id"] = "baseline"
        fallback["decision_status"] = "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE"
        self.two.assert_rejected(self, fallback, "decision_status")

    def test_fx04_sel_11_all_ineligible_selects_the_declared_baseline(self) -> None:
        ineligible = ("1.200000000000", "1.200000000000", "1.150000000000",
                      "1.300000000000", "analyzed")
        decision = self.two.evaluate(
            {"alpha": ineligible, "beta": ineligible}
        )
        self.assertEqual(decision.selected_arm_id, "baseline")
        self.assertEqual(decision.decision_status, "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE")
        document = self.two.as_document(decision)
        self.two.validate(document)
        forged = self.two.as_document(decision)
        forged["selected_arm_id"] = "alpha"
        forged["decision_status"] = "SELECTED_ELIGIBLE_SYNTHETIC"
        # The selection and the decision status must agree; the validator reports
        # the composite contract at the decision-status path.
        self.two.assert_rejected(self, forged, "decision_status")

    def test_fx04_sel_12_one_eligible_with_another_inconclusive_is_selected(self) -> None:
        decision = self.two.evaluate(
            {
                "alpha": _lanes("alpha", "0.900000000000"),
                "beta": ("0.960000000000", "0.960000000000", "0.900000000000",
                         "0.990000000000", "analyzed"),
            }
        )
        self.assertEqual(decision.selected_arm_id, "alpha")
        self.assertEqual(decision.decision_status, "SELECTED_ELIGIBLE_SYNTHETIC")
        document = self.two.as_document(decision)
        self.two.validate(document)
        forged = self.two.as_document(decision)
        forged["selected_arm_id"] = "beta"
        self.two.assert_rejected(self, forged, "decision_status")
        forged_status = self.two.as_document(decision)
        forged_status["decision_status"] = "TIE_PREFERENCE_NOT_PROVEN_FASTER"
        self.two.assert_rejected(self, forged_status, "decision_status")


class PolicyDecimalRenderingTests(unittest.TestCase):
    """FX04-DEC-01…05: canonical fixed-12-place policy output numbers."""

    def lane(self, *, point_limit, ci_limit, point_effect=None, ci_low=None, ci_high=None):
        from quervant_bench.analysis.policy import LanePolicyResult

        return LanePolicyResult(
            lane_id="rare-query",
            kind="target",
            point_effect=point_effect,
            ci_low=ci_low,
            ci_high=ci_high,
            point_limit=Decimal(point_limit),
            ci_limit=Decimal(ci_limit),
            ci_operator="lt",
            retained_blocks=4,
            status="unproven",
            reasons=("TARGET_UNPROVEN",),
        )

    def test_fx04_dec_01_short_target_limits_render_twelve_places(self) -> None:
        document = self.lane(point_limit="0.95", ci_limit="1").to_document()
        self.assertEqual(document["point_limit"], "0.950000000000")
        self.assertEqual(document["ci_limit"], "1.000000000000")

    def test_fx04_dec_02_short_guardrail_limits_render_twelve_places(self) -> None:
        document = self.lane(point_limit="1.1", ci_limit="1").to_document()
        self.assertEqual(document["point_limit"], "1.100000000000")
        self.assertEqual(document["ci_limit"], "1.000000000000")

    def test_fx04_dec_03_zero_limit_renders_twelve_places(self) -> None:
        document = self.lane(point_limit="0", ci_limit="0").to_document()
        self.assertEqual(document["point_limit"], "0.000000000000")
        self.assertEqual(document["ci_limit"], "0.000000000000")

    def test_fx04_dec_04_absent_effects_stay_json_null(self) -> None:
        from quervant_bench.analysis.policy import LanePolicyResult

        document = LanePolicyResult(
            lane_id="rare-query",
            kind="target",
            point_effect=None,
            ci_low=None,
            ci_high=None,
            point_limit=Decimal("0.95"),
            ci_limit=Decimal("1"),
            ci_operator="lt",
            retained_blocks=2,
            status="insufficient",
            reasons=("INSUFFICIENT_RETAINED_BLOCKS",),
        ).to_document()
        self.assertIsNone(document["point_effect"])
        self.assertIsNone(document["ci_low"])
        self.assertIsNone(document["ci_high"])
        self.assertEqual(document["point_limit"], "0.950000000000")

    def test_fx04_dec_04_gm_renderers_are_fixed_twelve_places(self) -> None:
        from quervant_bench.analysis.policy import CandidatePolicyResult, RankedCandidate

        candidate = CandidatePolicyResult(
            arm_id="alpha",
            status="ELIGIBLE",
            worst_campaign_gm=Decimal("0.9"),
            campaign_results=(),
        )
        self.assertEqual(candidate.to_document()["worst_campaign_gm"], "0.900000000000")
        ranked = RankedCandidate(arm_id="alpha", worst_campaign_gm=Decimal("1"))
        self.assertEqual(ranked.to_document()["worst_campaign_gm"], "1.000000000000")

    def test_fx04_dec_05_malformed_policy_literals_still_reject(self) -> None:
        bundle = load_bundle()
        cases = {
            "json-float": 0.95,
            "exponent": "1e0",
            "overprecise": "1.0000000000000",
            "nan": "NaN",
            "negative": "-0.950000000000",
            "sign": "+0.950000000000",
        }
        for name, literal in cases.items():
            with self.subTest(name=name):
                document = policy_profile_document()
                document["targets"][0]["point_upper"] = literal
                with self.assertRaises(BenchError) as caught:
                    validate_policy_profile(document, bundle)
                self.assertIn(
                    caught.exception.code, {BM_SCHEMA_INVALID, BM_IDENTITY_INVALID}
                )
        # A short *valid* literal is accepted by the parser (RF04-03 is a renderer bug).
        document = policy_profile_document()
        document["targets"][0]["point_upper"] = "0.95"
        document["targets"][0]["ci_upper"] = "1"
        with self.assertRaises(BenchError) as caught:
            validate_policy_profile(document, bundle)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "policy_id")


class PolicyCampaignInventoryTests(PolicyCatalogMixin, unittest.TestCase):
    """FX04-INV-05…07: per-candidate campaign inventories must be complete."""

    def good_document(self):
        decision = self.two.evaluate(
            {"alpha": _lanes("alpha", "0.900000000000"),
             "beta": _lanes("beta", "0.800000000000")}
        )
        document = self.two.as_document(decision)
        self.two.validate(document)
        return document

    def test_fx04_inv_05_shortened_candidate_campaigns_reject(self) -> None:
        document = self.good_document()
        self.assertEqual(len(document["candidate_results"][0]["campaign_results"]), 2)
        document["candidate_results"][0]["campaign_results"].pop()
        self.two.assert_rejected(
            self, document, "candidate_results[0].campaign_results"
        )

    def test_fx04_inv_06_empty_candidate_campaigns_reject(self) -> None:
        document = self.good_document()
        document["candidate_results"][1]["campaign_results"] = []
        self.two.assert_rejected(
            self, document, "candidate_results[1].campaign_results"
        )

    def test_fx04_inv_07_only_one_candidate_truncated_rejects(self) -> None:
        document = self.good_document()
        document["candidate_results"][1]["campaign_results"].pop()
        self.two.assert_rejected(
            self, document, "candidate_results[1].campaign_results"
        )
        # alpha remains complete; the rejection is scoped to beta, not a global pass.
        self.assertEqual(len(document["candidate_results"][0]["campaign_results"]), 2)

    def test_fx04_inv_04_extra_campaign_rejects(self) -> None:
        document = self.good_document()
        extra = copy.deepcopy(document["candidate_results"][0]["campaign_results"][-1])
        extra["campaign_index"] = 2
        document["candidate_results"][0]["campaign_results"].append(extra)
        self.two.assert_rejected(
            self, document, "candidate_results[0].campaign_results"
        )


if __name__ == "__main__":  # pragma: no cover - manual invocation only
    unittest.main()

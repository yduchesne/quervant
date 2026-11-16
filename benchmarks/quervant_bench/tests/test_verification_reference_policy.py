"""Independent policy truth-table tests (V-POL)."""

from __future__ import annotations

import unittest

from quervant_bench.tests.analysis_support import (
    ANALYSIS_FIXTURES,
    EXPERIMENT_ID,
    ZERO_DIGEST,
    analysis_document,
    candidate_row,
    lane_row,
    make_policy_profile,
    make_resources,
    make_threshold,
)
from quervant_bench.verification.reference_policy import (
    _filter_sensitive,
    _project_analysis,
    evaluate_reference_policy,
)

RUN_ID = "00000000-0000-4000-8000-000000000000"


def _lane(
    lane_id: str,
    values: dict[str, tuple[object, object, object, object, str]],
) -> dict:
    return lane_row(
        lane_id,
        [
            candidate_row(
                arm_id=arm_id,
                raw=raw,
                retained=retained,
                low=low,
                high=high,
                status=status,
            )
            for arm_id, (raw, retained, low, high, status) in values.items()
        ],
    )


def _campaigns(
    *,
    rare: dict[str, tuple[object, object, object, object, str]],
    common: dict[str, tuple[object, object, object, object, str]],
    count: int = 2,
) -> list[list[dict]]:
    return [
        [_lane("rare-query", rare), _lane("common-query", common)]
        for _ in range(count)
    ]


PASSING = ("0.800000000000", "0.800000000000", "0.700000000000", "0.900000000000", "analyzed")
PASSING_COMMON = (
    "0.833333333333",
    "0.833333333333",
    "0.700000000000",
    "0.900000000000",
    "analyzed",
)


def _evaluate(campaigns, *, profile=None, resources=None, minimum_retained=3):
    return evaluate_reference_policy(
        analysis_document=analysis_document(campaigns),
        policy_profile=profile if profile is not None else make_policy_profile(),
        observations=resources if resources is not None else make_resources(),
        minimum_retained=minimum_retained,
        experiment_id=EXPERIMENT_ID,
        run_id=RUN_ID,
        analysis_digest=ZERO_DIGEST,
    )


class PolicyThresholdTests(unittest.TestCase):
    def test_v_pol_01_target_pass_boundary(self) -> None:
        document = _evaluate(_campaigns(rare={"candidate": PASSING}, common={"candidate": PASSING_COMMON}))
        candidate = document["candidate_results"][0]
        self.assertEqual(candidate["status"], "ELIGIBLE")
        self.assertEqual(document["selected_arm_id"], "candidate")
        self.assertEqual(document["decision_status"], "SELECTED_ELIGIBLE_SYNTHETIC")

    def test_v_pol_02_strict_lt_ci_equality_is_unproven(self) -> None:
        equal = ("0.900000000000", "0.900000000000", "0.800000000000", "1.000000000000", "analyzed")
        document = _evaluate(_campaigns(rare={"candidate": equal}, common={"candidate": PASSING_COMMON}))
        lane = document["candidate_results"][0]["campaign_results"][0]["lanes"][0]
        self.assertEqual(lane["status"], "unproven")
        self.assertEqual(lane["reasons"], ["TARGET_UNPROVEN"])
        self.assertEqual(document["candidate_results"][0]["status"], "INCONCLUSIVE")
        self.assertIsNone(document["selected_arm_id"])
        self.assertEqual(document["decision_status"], "INCONCLUSIVE")

    def test_v_pol_03_le_ci_equality_passes(self) -> None:
        at_limit = ("1.050000000000", "1.050000000000", "1.000000000000", "1.100000000000", "analyzed")
        document = _evaluate(_campaigns(rare={"candidate": PASSING}, common={"candidate": at_limit}))
        guardrail = document["candidate_results"][0]["campaign_results"][0]["lanes"][1]
        self.assertEqual(guardrail["status"], "pass")
        self.assertEqual(document["candidate_results"][0]["status"], "ELIGIBLE")
        over = ("1.050000000000", "1.050000000000", "1.000000000000", "1.100000000001", "analyzed")
        rejected = _evaluate(_campaigns(rare={"candidate": PASSING}, common={"candidate": over}))
        guardrail = rejected["candidate_results"][0]["campaign_results"][0]["lanes"][1]
        self.assertEqual(guardrail["status"], "unproven")
        self.assertEqual(guardrail["reasons"], ["GUARDRAIL_UNPROVEN"])

    def test_v_pol_04_target_decisive_failure_is_ineligible(self) -> None:
        failing = ("1.200000000000", "1.200000000000", "1.100000000000", "1.300000000000", "analyzed")
        document = _evaluate(_campaigns(rare={"candidate": failing}, common={"candidate": PASSING_COMMON}))
        lane = document["candidate_results"][0]["campaign_results"][0]["lanes"][0]
        self.assertEqual(lane["status"], "decisive-failure")
        self.assertEqual(lane["reasons"], ["TARGET_DECISIVE_FAILURE"])
        self.assertEqual(document["candidate_results"][0]["status"], "INELIGIBLE")

    def test_v_pol_05_resource_cap_boundaries(self) -> None:
        profile = make_policy_profile()
        at_cap = _evaluate(
            _campaigns(rare={"candidate": PASSING}, common={"candidate": PASSING_COMMON}),
            profile=profile,
            resources=make_resources(("candidate", "aux-memory-bytes", 2097152)),
        )
        self.assertEqual(at_cap["candidate_results"][0]["status"], "ELIGIBLE")
        over = _evaluate(
            _campaigns(rare={"candidate": PASSING}, common={"candidate": PASSING_COMMON}),
            profile=profile,
            resources=make_resources(("candidate", "aux-memory-bytes", 2097153)),
        )
        self.assertEqual(over["candidate_results"][0]["status"], "INELIGIBLE")
        self.assertIn("RESOURCE_OVER_LIMIT", [item["code"] for item in over["reasons"]])
        missing = _evaluate(
            _campaigns(rare={"candidate": PASSING}, common={"candidate": PASSING_COMMON}),
            profile=profile,
            resources=make_resources(("other-arm", "aux-memory-bytes", 1)),
        )
        self.assertEqual(missing["candidate_results"][0]["status"], "INCONCLUSIVE")
        self.assertIn("MISSING_RESOURCE", [item["code"] for item in missing["reasons"]])
        self.assertIsNone(missing["selected_arm_id"])
        self.assertEqual(missing["decision_status"], "INCONCLUSIVE")

    def test_v_pol_06_all_applicable_resource_reasons_are_retained(self) -> None:
        from quervant_bench.analysis.policy import ResourceRule

        profile = make_policy_profile(
            resource_rules=(
                ResourceRule("candidate", "aux-memory-bytes", 10),
                ResourceRule("candidate", "secondary-bytes", 10),
            )
        )
        resources = make_resources(("candidate", "aux-memory-bytes", 11))
        document = _evaluate(
            _campaigns(rare={"candidate": PASSING}, common={"candidate": PASSING_COMMON}),
            profile=profile,
            resources=resources,
        )
        codes = {
            (item["campaign_index"], item["code"])
            for item in document["reasons"]
            if item["candidate_arm_id"] == "candidate"
        }
        self.assertIn((0, "RESOURCE_OVER_LIMIT"), codes)
        self.assertIn((0, "MISSING_RESOURCE"), codes)
        self.assertEqual(document["candidate_results"][0]["status"], "INELIGIBLE")

    def test_v_pol_07_filter_sensitivity_is_descriptive_only(self) -> None:
        changed = ("0.800000000000", "1.050000000000", "0.900000000000", "1.050000000000", "analyzed")
        document = _evaluate(_campaigns(rare={"candidate": changed}, common={"candidate": PASSING_COMMON}))
        codes = [item["code"] for item in document["reasons"]]
        self.assertIn("FILTER_SENSITIVE", codes)
        self.assertEqual(document["candidate_results"][0]["status"], "INCONCLUSIVE")

    def test_v_pol_08_stable_order_with_changing_distance_is_not_sensitive(self) -> None:
        document = analysis_document(
            [
                [
                    lane_row(
                        "rare-query",
                        [
                            candidate_row(arm_id="alpha", raw="3.000000000000",
                                          retained="1.500000000000", low="1.100000000000",
                                          high="1.900000000000"),
                            candidate_row(arm_id="beta", raw="1.500000000000",
                                          retained="1.100000000000", low="1.000000000000",
                                          high="1.400000000000"),
                        ],
                    )
                ]
            ]
        )
        campaigns = _project_analysis(document)
        affected = _filter_sensitive(campaigns, ("alpha", "beta"))
        # RF05-01 erratum: this case keeps alpha above beta; the old expectation
        # (both candidates sensitive) was the false positive under review.
        self.assertEqual(affected, set())


class PolicyRankingTests(unittest.TestCase):
    def _two_candidate_profile(self, **overrides):
        arguments = dict(
            candidate_order=("alpha", "beta"),
            targets=(make_threshold("rare-query", "0.950000000000", "1.000000000000", "lt"),),
            guardrails=(make_threshold("common-query", "1.100000000000", "1.100000000000", "le"),),
            resource_rules=(),
            ranking_lanes=("rare-query",),
        )
        arguments.update(overrides)
        return make_policy_profile(**arguments)

    def _two_candidates(self, alpha: str, beta: str) -> list[list[dict]]:
        return _campaigns(
            rare={
                "alpha": (alpha, alpha, alpha, "0.980000000000", "analyzed"),
                "beta": (beta, beta, beta, "0.980000000000", "analyzed"),
            },
            common={
                "alpha": ("0.900000000000",) * 4 + ("analyzed",),
                "beta": ("0.900000000000",) * 4 + ("analyzed",),
            },
        )

    def test_v_pol_09_gm_order_overrides_declaration_order(self) -> None:
        document = _evaluate(
            self._two_candidates("0.900000000000", "0.800000000000"),
            profile=self._two_candidate_profile(),
        )
        self.assertEqual([entry["arm_id"] for entry in document["ranking"]], ["beta", "alpha"])
        self.assertEqual(document["selected_arm_id"], "beta")
        self.assertEqual(document["decision_status"], "SELECTED_ELIGIBLE_SYNTHETIC")

    def test_v_pol_10_exact_equal_gm_uses_tie_preference(self) -> None:
        document = _evaluate(
            self._two_candidates("0.800000000000", "0.800000000000"),
            profile=self._two_candidate_profile(tie_preference=("beta", "alpha")),
        )
        self.assertEqual(document["selected_arm_id"], "beta")
        self.assertEqual(document["decision_status"], "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertEqual([entry["arm_id"] for entry in document["ranking"]], ["alpha", "beta"])

    def test_v_pol_11_tie_relative_delta_boundary_is_strict(self) -> None:
        profile = self._two_candidate_profile(tie_preference=("beta", "alpha"))
        tied = _evaluate(self._two_candidates("0.900000000000", "0.920000000000"), profile=profile)
        self.assertEqual(tied["decision_status"], "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertEqual(tied["selected_arm_id"], "beta")
        exact_boundary = _evaluate(
            self._two_candidates("0.900000000000", "0.927000000000"), profile=profile
        )
        self.assertEqual(exact_boundary["decision_status"], "SELECTED_ELIGIBLE_SYNTHETIC")
        self.assertEqual(exact_boundary["selected_arm_id"], "alpha")

    def test_v_pol_12_tie_preference_is_restricted_to_the_best_two(self) -> None:
        profile = self._two_candidate_profile(
            candidate_order=("third", "first", "second"),
            tie_preference=("third", "second", "first"),
        )
        campaigns = _campaigns(
            rare={
                "third": ("0.930000000000",) * 4 + ("analyzed",),
                "first": ("0.900000000000",) * 4 + ("analyzed",),
                "second": ("0.905000000000",) * 4 + ("analyzed",),
            },
            common={
                "third": ("0.900000000000",) * 4 + ("analyzed",),
                "first": ("0.900000000000",) * 4 + ("analyzed",),
                "second": ("0.900000000000",) * 4 + ("analyzed",),
            },
        )
        document = _evaluate(campaigns, profile=profile)
        self.assertEqual([entry["arm_id"] for entry in document["ranking"]], ["first", "second", "third"])
        self.assertEqual(document["selected_arm_id"], "second")
        self.assertEqual(document["decision_status"], "TIE_PREFERENCE_NOT_PROVEN_FASTER")

    def test_v_pol_13_no_eligible_with_inconclusive_never_falls_back_to_baseline(self) -> None:
        missing = ("0.800000000000", "0.800000000000", "0.700000000000", "0.900000000000", "inconclusive-insufficient-blocks")
        document = _evaluate(_campaigns(rare={"candidate": missing}, common={"candidate": PASSING_COMMON}))
        self.assertIsNone(document["selected_arm_id"])
        self.assertEqual(document["decision_status"], "INCONCLUSIVE")

    def test_v_pol_14_every_candidate_decisively_ineligible_selects_baseline(self) -> None:
        failing = ("1.200000000000", "1.200000000000", "1.100000000000", "1.300000000000", "analyzed")
        failing_guardrail = ("1.200000000000", "1.200000000000", "1.150000000000", "1.300000000000", "analyzed")
        document = _evaluate(_campaigns(rare={"candidate": failing}, common={"candidate": failing_guardrail}))
        self.assertEqual(document["selected_arm_id"], "baseline")
        self.assertEqual(document["decision_status"], "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE")

    def test_v_pol_15_one_eligible_plus_one_inconclusive_selects_the_eligible(self) -> None:
        from quervant_bench.analysis.policy import ResourceRule

        profile = self._two_candidate_profile(
            resource_rules=(ResourceRule("beta", "aux-memory-bytes", 10),)
        )
        document = _evaluate(
            self._two_candidates("0.800000000000", "0.800000000000"),
            profile=profile,
            resources=make_resources(("alpha", "aux-memory-bytes", 1)),
        )
        statuses = {item["arm_id"]: item["status"] for item in document["candidate_results"]}
        self.assertEqual(statuses, {"alpha": "ELIGIBLE", "beta": "INCONCLUSIVE"})
        self.assertEqual(document["selected_arm_id"], "alpha")
        self.assertEqual(document["decision_status"], "SELECTED_ELIGIBLE_SYNTHETIC")

    def test_v_pol_16_reason_records_are_sorted_and_unique(self) -> None:
        missing = ("0.800000000000", "0.800000000000", "0.700000000000", "0.900000000000", "inconclusive-insufficient-blocks")
        document = _evaluate(_campaigns(rare={"candidate": missing}, common={"candidate": PASSING_COMMON}))
        keys = [
            (item["candidate_arm_id"], item["campaign_index"], item["lane_id"], item["code"])
            for item in document["reasons"]
        ]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(
            keys,
            sorted(keys, key=lambda key: (key[1], key[2] or "", key[3])),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


def _two_candidate_document(
    *,
    alpha_raw: str,
    alpha_retained: str | None,
    beta_raw: str,
    beta_retained: str | None,
    alpha_status: str = "analyzed",
    beta_status: str = "analyzed",
) -> dict:
    """Hand-authored policy-only analysis record; never claimed as sealed BM-03 data."""

    def row(arm_id: str, raw: str, retained: str | None, status: str):
        analyzed = retained is not None
        return candidate_row(
            arm_id=arm_id,
            raw=raw,
            retained=retained,
            low="0.700000000000" if analyzed else None,
            high="0.940000000000" if analyzed else None,
            status=status,
        )

    def campaign():
        return [
            lane_row(
                "rare-query",
                [
                    row("alpha", alpha_raw, alpha_retained, alpha_status),
                    row("beta", beta_raw, beta_retained, beta_status),
                ],
            ),
            lane_row(
                "common-query",
                [
                    candidate_row(
                        arm_id="alpha",
                        raw="0.900000000000",
                        retained="0.900000000000",
                        low="0.800000000000",
                        high="1.000000000000",
                    ),
                    candidate_row(
                        arm_id="beta",
                        raw="0.900000000000",
                        retained="0.900000000000",
                        low="0.800000000000",
                        high="1.000000000000",
                    ),
                ],
            ),
        ]

    return analysis_document([campaign(), campaign()])


def _two_candidate_profile(**overrides):
    arguments = dict(
        candidate_order=("alpha", "beta"),
        targets=(make_threshold("rare-query", "0.950000000000", "1.000000000000", "lt"),),
        guardrails=(make_threshold("common-query", "1.100000000000", "1.100000000000", "le"),),
        resource_rules=(),
        ranking_lanes=("rare-query",),
        tie_preference=("alpha", "beta"),
    )
    arguments.update(overrides)
    return make_policy_profile(**arguments)


def _reference_decision(document: dict, profile=None):
    return evaluate_reference_policy(
        analysis_document=document,
        policy_profile=profile if profile is not None else _two_candidate_profile(),
        observations=make_resources(),
        minimum_retained=3,
        experiment_id=EXPERIMENT_ID,
        run_id=RUN_ID,
        analysis_digest=ZERO_DIGEST,
    )


class ReferenceFilterSensitivityTests(unittest.TestCase):
    """F05-REF-01…07/09/10: relative order, parity, ties, missing and lane-wide marking."""

    def _affected(self, **values) -> set:
        document = _two_candidate_document(**values)
        return _filter_sensitive(_project_analysis(document), ("alpha", "beta"))

    def test_f05_ref_01_true_order_reversal_is_sensitive(self) -> None:
        self.assertEqual(
            self._affected(
                alpha_raw="0.800000000000",
                alpha_retained="0.900000000000",
                beta_raw="0.900000000000",
                beta_retained="0.800000000000",
            ),
            {
                (0, "rare-query", "alpha"),
                (0, "rare-query", "beta"),
                (1, "rare-query", "alpha"),
                (1, "rare-query", "beta"),
            },
        )

    def test_f05_ref_02_stable_order_with_changing_distance_is_not_sensitive(self) -> None:
        self.assertEqual(
            self._affected(
                alpha_raw="3.000000000000",
                alpha_retained="1.500000000000",
                beta_raw="1.500000000000",
                beta_retained="1.100000000000",
            ),
            set(),
        )

    def test_f05_ref_03_unequal_to_tie_is_sensitive(self) -> None:
        self.assertEqual(
            self._affected(
                alpha_raw="0.800000000000",
                alpha_retained="0.900000000000",
                beta_raw="0.900000000000",
                beta_retained="0.900000000000",
            ),
            {
                (0, "rare-query", "alpha"),
                (0, "rare-query", "beta"),
                (1, "rare-query", "alpha"),
                (1, "rare-query", "beta"),
            },
        )

    def test_f05_ref_04_tie_to_unequal_is_sensitive(self) -> None:
        self.assertEqual(
            self._affected(
                alpha_raw="0.900000000000",
                alpha_retained="0.800000000000",
                beta_raw="0.900000000000",
                beta_retained="0.900000000000",
            ),
            {
                (0, "rare-query", "alpha"),
                (0, "rare-query", "beta"),
                (1, "rare-query", "alpha"),
                (1, "rare-query", "beta"),
            },
        )

    def test_f05_ref_05_missing_effect_is_not_a_zero_or_tie(self) -> None:
        self.assertEqual(
            self._affected(
                alpha_raw="0.800000000000",
                alpha_retained=None,
                beta_raw="0.900000000000",
                beta_retained="0.900000000000",
            ),
            set(),
        )

    def test_f05_ref_06_individual_parity_flip_marks_only_that_candidate(self) -> None:
        self.assertEqual(
            self._affected(
                alpha_raw="0.950000000000",
                alpha_retained="1.050000000000",
                beta_raw="0.800000000000",
                beta_retained="0.800000000000",
            ),
            {(0, "rare-query", "alpha"), (1, "rare-query", "alpha")},
        )

    def test_f05_ref_07_order_flip_forces_inconclusive_and_null_selection(self) -> None:
        document = _two_candidate_document(
            alpha_raw="0.800000000000",
            alpha_retained="0.900000000000",
            beta_raw="0.900000000000",
            beta_retained="0.800000000000",
        )
        decision = _reference_decision(document)
        self.assertEqual(
            [item["status"] for item in decision["candidate_results"]],
            ["INCONCLUSIVE", "INCONCLUSIVE"],
        )
        self.assertIsNone(decision["selected_arm_id"])
        self.assertEqual(decision["decision_status"], "INCONCLUSIVE")
        self.assertEqual(decision["ranking"], [])
        self.assertEqual(
            [
                (
                    item["candidate_arm_id"],
                    item["campaign_index"],
                    item["lane_id"],
                    item["code"],
                )
                for item in decision["reasons"]
            ],
            [
                ("alpha", 0, "rare-query", "FILTER_SENSITIVE"),
                ("beta", 0, "rare-query", "FILTER_SENSITIVE"),
                ("alpha", 1, "rare-query", "FILTER_SENSITIVE"),
                ("beta", 1, "rare-query", "FILTER_SENSITIVE"),
            ],
        )

    def test_f05_ref_08_zero_policy_limits_render_and_fail_decisively(self) -> None:
        profile = make_policy_profile(
            candidate_order=("candidate",),
            targets=(make_threshold("rare-query", "0", "0", "lt"),),
            guardrails=(make_threshold("common-query", "0", "0", "le"),),
            resource_rules=(),
            ranking_lanes=("rare-query",),
            tie_preference=("candidate",),
        )
        document = analysis_document(
            [
                [
                    lane_row(
                        "rare-query",
                        [candidate_row(raw="0.800000000000", retained="0.800000000000",
                                        low="0.700000000000", high="0.900000000000")],
                    ),
                    lane_row(
                        "common-query",
                        [candidate_row(raw="0.800000000000", retained="0.800000000000",
                                        low="0.700000000000", high="0.900000000000")],
                    ),
                ]
            ]
        )
        decision = _reference_decision(document, profile)
        lanes = decision["candidate_results"][0]["campaign_results"][0]["lanes"]
        self.assertEqual(lanes[0]["point_limit"], "0.000000000000")
        self.assertEqual(lanes[0]["ci_limit"], "0.000000000000")
        self.assertEqual(lanes[0]["status"], "decisive-failure")
        self.assertEqual(lanes[0]["reasons"], ["TARGET_DECISIVE_FAILURE"])
        self.assertEqual(lanes[1]["point_limit"], "0.000000000000")
        self.assertEqual(lanes[1]["ci_limit"], "0.000000000000")
        self.assertEqual(lanes[1]["status"], "decisive-failure")
        self.assertEqual(lanes[1]["reasons"], ["GUARDRAIL_DECISIVE_FAILURE"])
        self.assertEqual(decision["candidate_results"][0]["status"], "INELIGIBLE")
        self.assertEqual(decision["selected_arm_id"], "baseline")
        self.assertEqual(
            decision["decision_status"], "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE"
        )

    def test_f05_ref_09_three_arm_single_pair_flip_flags_every_candidate(self) -> None:
        document = analysis_document(
            [
                [
                    lane_row(
                        "rare-query",
                        [
                            candidate_row(arm_id="alpha", raw="0.800000000000",
                                          retained="0.910000000000",
                                          low="0.700000000000", high="0.940000000000"),
                            candidate_row(arm_id="beta", raw="0.900000000000",
                                          retained="0.850000000000",
                                          low="0.700000000000", high="0.940000000000"),
                            candidate_row(arm_id="gamma", raw="0.950000000000",
                                          retained="0.950000000000",
                                          low="0.700000000000", high="0.940000000000"),
                        ],
                    )
                ]
            ]
        )
        self.assertEqual(
            _filter_sensitive(_project_analysis(document), ("alpha", "beta", "gamma")),
            {
                (0, "rare-query", "alpha"),
                (0, "rare-query", "beta"),
                (0, "rare-query", "gamma"),
            },
        )

    def test_f05_ref_10_changed_magnitudes_with_stable_order_are_not_sensitive(self) -> None:
        self.assertEqual(
            self._affected(
                alpha_raw="0.800000000000",
                alpha_retained="0.810000000000",
                beta_raw="0.900000000000",
                beta_retained="0.920000000000",
            ),
            set(),
        )

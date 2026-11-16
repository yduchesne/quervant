"""End-to-end synthetic vertical slices for BM-05 (V-EVID / V-MUT positive)."""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from quervant_bench.analysis.derive import analyze_synthetic_run
from quervant_bench.config.codec import content_digest, load_document
from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.tests.analysis_support import (
    EXPERIMENT_ID,
    SealedRun,
    build_isolated_catalog,
    cached_derivation,
    cached_sealed_run,
    experiment_root,
)
from quervant_bench.verification import verify_synthetic_run
from quervant_bench.verification.contracts import CHECK_IDS
from quervant_bench.verification.reference_math import (
    format_12,
    geometric_mean,
)

THREE_ARM_VALUES = {
    ("baseline", "common-query"): (1_000_000, 1_000_000, 1_000_000),
    ("baseline", "rare-query"): (1_000_000, 1_000_000, 1_000_000),
    ("alpha", "common-query"): (1_050_000, 1_050_000, 1_050_000),
    ("alpha", "rare-query"): (900_000, 900_000, 900_000),
    ("beta", "common-query"): (900_000, 900_000, 900_000),
    ("beta", "rare-query"): (800_000, 800_000, 800_000),
}

TIE_VALUES = {
    ("baseline", "common-query"): (1_200_000, 1_200_000, 1_200_000),
    ("baseline", "rare-query"): (1_000_000, 1_000_000, 1_000_000),
    ("candidate-a", "common-query"): (1_000_000, 1_000_000, 1_000_000),
    ("candidate-a", "rare-query"): (800_000, 800_000, 800_000),
    ("candidate-b", "common-query"): (1_000_000, 1_000_000, 1_000_000),
    ("candidate-b", "rare-query"): (800_000, 800_000, 800_000),
}


def _derive(catalog: dict, run: SealedRun):
    return analyze_synthetic_run(
        bundle=catalog["bundle"],
        run_dir=run.run_dir,
        scenario_root=run.evidence,
        profiles_root=catalog["experiment_root"],
        resources_root=catalog["experiment_root"],
    )


def _verify(catalog: dict, run: SealedRun, analysis: dict, policy: dict):
    return verify_synthetic_run(
        bundle=catalog["bundle"],
        run_dir=run.run_dir,
        scenario_root=run.evidence,
        profiles_root=catalog["experiment_root"],
        resources_root=catalog["experiment_root"],
        analysis_document=analysis,
        policy_document=policy,
    )


def _rebind_estimator(catalog: dict, estimator_id: str) -> dict:
    root = catalog["experiment_root"]
    profile = load_document(root / "analysis-profile.v1.json")
    profile["estimator_id"] = estimator_id
    digest = content_digest(profile)
    from quervant_bench.tests.analysis_support import write_canonical

    write_canonical(root / "analysis-profile.v1.json", profile)
    experiment = load_document(root / "experiment.yaml")
    protocol = load_document(root / "protocol.yaml")
    experiment["analysis"]["analysis_digest"] = digest
    protocol["statistics"]["method_id"] = estimator_id
    (root / "experiment.yaml").write_text(
        json.dumps(experiment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "protocol.yaml").write_text(
        json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return load_experiment_bundle(EXPERIMENT_ID, catalog["catalog_root"])


class VerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        cls.cases: dict[str, dict] = {}

        def register(name: str, catalog: dict) -> None:
            run = SealedRun(bundle=catalog["bundle"], source_root=catalog["experiment_root"])
            analysis, policy = _derive(catalog, run)
            assessment = _verify(catalog, run, analysis, policy)
            cls.cases[name] = {
                "catalog": catalog,
                "run": run,
                "analysis": analysis,
                "policy": policy,
                "assessment": assessment,
            }

        register(
            "reversed",
            build_isolated_catalog(
                root / "reversed",
                experiment_id=EXPERIMENT_ID,
                arms=("candidate", "baseline"),
                baseline_arm_id="baseline",
                candidate_order=("candidate",),
            ),
        )
        register(
            "three",
            build_isolated_catalog(
                root / "three",
                experiment_id=EXPERIMENT_ID,
                arms=("alpha", "baseline", "beta"),
                baseline_arm_id="baseline",
                candidate_order=("alpha", "beta"),
                tie_preference=("alpha", "beta"),
                scenario_values=THREE_ARM_VALUES,
                blocks=6,
            ),
        )
        register(
            "short",
            build_isolated_catalog(
                root / "short",
                experiment_id=EXPERIMENT_ID,
                arms=("baseline", "candidate"),
                baseline_arm_id="baseline",
                candidate_order=("candidate",),
                targets=(("rare-query", "0.95", "1", "lt"),),
                guardrails=(("common-query", "1.1", "1.1", "le"),),
                tie_relative_delta="0.03",
            ),
        )
        register(
            "tie",
            build_isolated_catalog(
                root / "tie",
                experiment_id=EXPERIMENT_ID,
                arms=("baseline", "candidate-a", "candidate-b"),
                baseline_arm_id="baseline",
                candidate_order=("candidate-a", "candidate-b"),
                tie_preference=("candidate-b", "candidate-a"),
                scenario_values=TIE_VALUES,
                blocks=6,
            ),
        )
        ratio_catalog = build_isolated_catalog(
            root / "ratio",
            experiment_id=EXPERIMENT_ID,
            arms=("baseline", "candidate"),
            baseline_arm_id="baseline",
            candidate_order=("candidate",),
        )
        rebound = _rebind_estimator(ratio_catalog, "ratio-of-arm-medians-v1")
        ratio_catalog = {
            **ratio_catalog,
            "bundle": rebound,
        }
        register("ratio", ratio_catalog)

    @classmethod
    def tearDownClass(cls) -> None:
        for case in cls.cases.values():
            case["run"].close()
        cls._temporary.cleanup()

    def test_checked_in_fixture_matches_frozen_literals_and_verifies(self) -> None:
        run = cached_sealed_run()
        analysis, policy = cached_derivation()
        assessment = _verify(
            {"bundle": run.bundle, "experiment_root": experiment_root()},
            run,
            analysis,
            policy,
        )
        self.assertEqual(assessment.status, "verified-synthetic")
        self.assertEqual(assessment.check_ids, CHECK_IDS)
        self.assertEqual(
            assessment.analysis_digest, content_digest(analysis)
        )
        self.assertEqual(assessment.policy_digest, content_digest(policy))
        self.assertEqual(
            assessment.source_seal_digest, analysis["source_seal_digest"]
        )
        rare = [
            lane["candidates"][0]["retained_point_effect"]
            for campaign in analysis["campaigns"]
            for lane in campaign["lanes"]
            if lane["lane_id"] == "rare-query"
        ]
        common = [
            lane["candidates"][0]["retained_point_effect"]
            for campaign in analysis["campaigns"]
            for lane in campaign["lanes"]
            if lane["lane_id"] == "common-query"
        ]
        self.assertEqual(rare, ["0.800000000000"] * 2)
        self.assertEqual(common, ["0.833333333333"] * 2)
        self.assertEqual(
            format_12(
                geometric_mean(
                    [Decimal("0.800000000000"), Decimal("0.833333333333")]
                )
            ),
            "0.816496580928",
        )
        self.assertEqual(policy["candidate_results"][0]["worst_campaign_gm"], "0.816496580928")
        self.assertEqual(policy["selected_arm_id"], "candidate")
        self.assertEqual(policy["decision_status"], "SELECTED_ELIGIBLE_SYNTHETIC")
        for campaign in analysis["campaigns"]:
            for lane in campaign["lanes"]:
                self.assertEqual(lane["excluded_blocks"], [])
                self.assertEqual(lane["blocks_total"], 4)

    def test_non_first_baseline_slice(self) -> None:
        case = self.cases["reversed"]
        self.assertEqual(case["analysis"]["candidate_ids"], ["candidate"])
        self.assertEqual(case["analysis"]["baseline_arm_id"], "baseline")
        self.assertEqual(case["policy"]["selected_arm_id"], "candidate")
        self.assertEqual(case["assessment"].status, "verified-synthetic")

    def test_three_arm_gm_order_reversal_slice(self) -> None:
        case = self.cases["three"]
        policy = case["policy"]
        self.assertEqual(case["analysis"]["candidate_ids"], ["alpha", "beta"])
        self.assertEqual(
            [entry["arm_id"] for entry in policy["ranking"]], ["beta", "alpha"]
        )
        self.assertEqual(policy["selected_arm_id"], "beta")
        self.assertTrue(policy["ranking"][0]["worst_campaign_gm"].startswith("0.8485"))
        self.assertTrue(policy["ranking"][1]["worst_campaign_gm"].startswith("0.9721"))
        self.assertEqual(case["assessment"].status, "verified-synthetic")

    def test_short_profile_literals_normalize_slice(self) -> None:
        case = self.cases["short"]
        lane = case["policy"]["candidate_results"][0]["campaign_results"][0]["lanes"][0]
        self.assertEqual(lane["point_limit"], "0.950000000000")
        self.assertEqual(lane["ci_limit"], "1.000000000000")
        guardrail = case["policy"]["candidate_results"][0]["campaign_results"][0]["lanes"][1]
        self.assertEqual(guardrail["point_limit"], "1.100000000000")
        self.assertEqual(guardrail["ci_limit"], "1.100000000000")
        self.assertEqual(case["policy"]["selected_arm_id"], "candidate")
        self.assertEqual(case["assessment"].status, "verified-synthetic")

    def test_multi_candidate_tie_slice(self) -> None:
        case = self.cases["tie"]
        policy = case["policy"]
        self.assertEqual(policy["decision_status"], "TIE_PREFERENCE_NOT_PROVEN_FASTER")
        self.assertEqual(policy["selected_arm_id"], "candidate-b")
        self.assertEqual(
            [entry["arm_id"] for entry in policy["ranking"]],
            ["candidate-a", "candidate-b"],
        )
        self.assertEqual(case["assessment"].status, "verified-synthetic")

    def test_both_estimators_are_authorized_and_verified(self) -> None:
        case = self.cases["ratio"]
        self.assertEqual(
            case["analysis"]["estimator_id"], "ratio-of-arm-medians-v1"
        )
        self.assertEqual(
            case["analysis"]["algorithm_id"], "sha256-rejection-paired-block-v1"
        )
        self.assertEqual(case["assessment"].status, "verified-synthetic")

    def test_insufficient_retained_blocks_is_not_constructible_on_frozen_bm03(self) -> None:
        # The frozen synthetic adapter replays one sample vector per arm and lane
        # for every slot, so each arm has exactly one within-block value and the
        # spread is always 1. The sealed corpus therefore cannot produce a
        # retained-block shortfall. Insufficient behaviour is proven at the
        # reference-math level and by forged-document rejection instead.
        run = cached_sealed_run()
        analysis, _policy = cached_derivation()
        for campaign in analysis["campaigns"]:
            for lane in campaign["lanes"]:
                self.assertEqual(lane["excluded_blocks"], [])
                for row in lane["exclusion_ledger"]:
                    self.assertEqual(row["status"], "retained")
                    for spread in row["arm_spreads"]:
                        self.assertEqual(spread["spread"], "1.000000000000")
        self.assertEqual(run.replay().status, "verified-synthetic-structure")

    def test_repeated_verification_is_byte_identical(self) -> None:
        case = self.cases["three"]
        first = case["assessment"]
        second = _verify(
            case["catalog"],
            case["run"],
            case["analysis"],
            case["policy"],
        )
        self.assertEqual(first, second)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


class ZeroThresholdVerticalSliceTests(unittest.TestCase):
    """F05-VERT-01/02: BM-04 zero limits derive and independently verify."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        cls.cases: dict[str, dict] = {}
        for name, zero_literal in (
            ("zero-short", "0"),
            ("zero-explicit", "0.000000000000"),
        ):
            catalog = build_isolated_catalog(
                root / name,
                experiment_id=EXPERIMENT_ID,
                arms=("baseline", "candidate"),
                baseline_arm_id="baseline",
                candidate_order=("candidate",),
                targets=(("rare-query", zero_literal, zero_literal, "lt"),),
                guardrails=(("common-query", zero_literal, zero_literal, "le"),),
            )
            run = SealedRun(bundle=catalog["bundle"], source_root=catalog["experiment_root"])
            analysis, policy = _derive(catalog, run)
            cls.cases[name] = {
                "catalog": catalog,
                "run": run,
                "analysis": analysis,
                "policy": policy,
            }

    @classmethod
    def tearDownClass(cls) -> None:
        for case in cls.cases.values():
            case["run"].close()
        cls._temporary.cleanup()

    def _assert_zero_limits(self, policy: dict) -> None:
        for campaign in policy["candidate_results"][0]["campaign_results"]:
            for lane in campaign["lanes"]:
                self.assertEqual(lane["point_limit"], "0.000000000000")
                self.assertEqual(lane["ci_limit"], "0.000000000000")
        self.assertEqual(policy["candidate_results"][0]["status"], "INELIGIBLE")
        self.assertEqual(
            policy["decision_status"], "BASELINE_ONLY_NO_ELIGIBLE_CANDIDATE"
        )
        self.assertEqual(policy["selected_arm_id"], "baseline")

    def _verify_case(self, name: str) -> None:
        case = self.cases[name]
        self._assert_zero_limits(case["policy"])
        before = _snapshot(case["run"].run_dir)
        assessment = _verify(
            case["catalog"], case["run"], case["analysis"], case["policy"]
        )
        self.assertEqual(assessment.status, "verified-synthetic")
        self.assertEqual(assessment.check_ids, CHECK_IDS)
        self.assertEqual(
            assessment.source_seal_digest, case["analysis"]["source_seal_digest"]
        )
        self.assertEqual(_snapshot(case["run"].run_dir), before)

    def test_f05_vert_01_short_zero_thresholds_derive_and_verify(self) -> None:
        self._verify_case("zero-short")

    def test_f05_vert_02_explicit_twelve_place_zero_limits_derive_and_verify(self) -> None:
        self._verify_case("zero-explicit")

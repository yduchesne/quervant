"""Oracle-independence audit and structurally valid false-PASS rejection (V-IND)."""

from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path
from unittest import mock

import quervant_bench.analysis.aggregation as aggregation
import quervant_bench.analysis.arithmetic as arithmetic
import quervant_bench.analysis.bootstrap as bootstrap
import quervant_bench.analysis.derive as derive
import quervant_bench.analysis.pruning as pruning
import quervant_bench.analysis.policy as primary_policy
from quervant_bench.analysis.contracts import (
    validate_analysis_result,
    validate_policy_decision,
)
from quervant_bench.config.codec import content_digest
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BenchError
from quervant_bench.tests.analysis_support import (
    EXPERIMENT_ID,
    ZERO_DIGEST,
    analysis_document,
    cached_derivation,
    cached_sealed_run,
    candidate_row,
    experiment_root,
    lane_row,
    load_analysis_profile,
    load_policy_profile,
    load_resource_observations,
    make_policy_profile,
    make_resources,
    make_threshold,
)
from quervant_bench.verification import verify_synthetic_run
from quervant_bench.verification.contracts import CHECK_IDS
from quervant_bench.verification.reference_policy import evaluate_reference_policy
from quervant_bench.verification.verify import _first_difference

PACKAGE = Path(__file__).resolve().parents[1] / "verification"

ALLOWED_MODULES = frozenset(
    {
        "config.codec",
        "config.contracts",
        "config.errors",
        "config.identity",
        "evidence.paths",
        "execution.contracts",
        "execution.recorder",
        "execution.replay",
        "execution.scenario",
        "protocol.controls",
        "protocol.schedule",
    }
)
ALLOWED_ANALYSIS_NAMES = {
    "analysis.contracts": frozenset(
        {"require_bounded_document", "validate_analysis_result", "validate_policy_decision"}
    ),
    "analysis.profiles": frozenset({"read_analysis_profile"}),
    "analysis.policy": frozenset(
        {"read_policy_profile", "read_resource_observations"}
    ),
}
FORBIDDEN_CALLS = frozenset(
    {
        "analyze_synthetic_run",
        "apply_lane_block_exclusions",
        "bootstrap_interval",
        "compute_paired_effect",
        "evaluate_policy",
        "_select",
        "format_effect",
        "median_paired_ratios",
        "quantize_effect",
        "ratio_of_arm_medians",
        "read_treatment_samples",
    }
)


def _module_of(node: ast.AST) -> tuple[str, int]:
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if node.level >= 2:
            return module, node.level
        if node.level == 1:
            return f"verification.{module}" if module else "verification", node.level
        return module, node.level
    raise AssertionError("not an import-from node")


class ImportAuditTests(unittest.TestCase):
    def test_v_ind_01_no_forbidden_primary_module_is_imported(self) -> None:
        forbidden_modules = {
            "analysis.arithmetic",
            "analysis.aggregation",
            "analysis.bootstrap",
            "analysis.derive",
            "analysis.history",
            "analysis.pruning",
        }
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module, _level = _module_of(node)
                    if module.startswith("quervant_bench."):
                        module = module[len("quervant_bench.") :]
                    self.assertNotIn(
                        module, forbidden_modules, f"{path.name} imports {module}"
                    )
                    if module in ALLOWED_ANALYSIS_NAMES:
                        for alias in node.names:
                            self.assertIn(
                                alias.name,
                                ALLOWED_ANALYSIS_NAMES[module],
                                f"{path.name} imports forbidden {module}.{alias.name}",
                            )
                    elif module.startswith("analysis."):
                        self.fail(f"{path.name} imports unexpected {module}")
                    elif module.startswith(
                        (
                            "execution.controller",
                            "execution.synthetic",
                            "cli",
                            "host.",
                        )
                    ):
                        self.fail(f"{path.name} imports forbidden project module {module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.name
                        if name.startswith("quervant_bench."):
                            name = name[len("quervant_bench.") :]
                        self.assertFalse(
                            name.startswith("analysis.")
                            or name.startswith("quervant_bench.analysis."),
                            f"{path.name} uses a module import of {alias.name}",
                        )

    def test_v_ind_02_no_dynamic_import_or_forbidden_call_site(self) -> None:
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    function = node.func
                    if isinstance(function, ast.Name):
                        self.assertNotIn(
                            function.id,
                            {"eval", "exec", "__import__"},
                            f"{path.name} calls {function.id}",
                        )
                        self.assertNotIn(function.id, FORBIDDEN_CALLS)
                    elif isinstance(function, ast.Attribute):
                        self.assertNotEqual(
                            function.attr, "import_module", f"{path.name} dynamic import"
                        )
                        self.assertNotIn(function.attr, FORBIDDEN_CALLS)

    def test_v_ind_03_no_global_subscriber_or_receipt_surface(self) -> None:
        forbidden_names = {
            "write",
            "publish",
            "attest",
            "to_receipt",
            "receipt",
            "configure_tracing",
        }
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertNotIn(node.name, forbidden_names, f"{path.name}.{node.name}")
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, forbidden_names, f"{path.name}.{node.attr}")


class RuntimeIndependenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sealed = cached_sealed_run()
        cls.analysis, cls.policy = cached_derivation()

    def _verify(self, analysis=None, policy=None):
        return verify_synthetic_run(
            bundle=self.sealed.bundle,
            run_dir=self.sealed.run_dir,
            scenario_root=self.sealed.evidence,
            profiles_root=experiment_root(),
            resources_root=experiment_root(),
            analysis_document=self.analysis if analysis is None else analysis,
            policy_document=self.policy if policy is None else policy,
        )

    def test_v_ind_04_poisoned_primary_calculators_are_never_called(self) -> None:
        def poisoned(*_args, **_kwargs):
            raise AssertionError("the verifier reached a primary calculation function")

        targets = [
            (primary_policy, "_select"),
            (primary_policy, "evaluate_policy"),
            (bootstrap, "bootstrap_interval"),
            (arithmetic, "compute_paired_effect"),
            (arithmetic, "median_paired_ratios"),
            (arithmetic, "ratio_of_arm_medians"),
            (pruning, "apply_lane_block_exclusions"),
            (derive, "analyze_synthetic_run"),
            (aggregation, "read_treatment_samples"),
        ]
        patchers = []
        try:
            for module, name in targets:
                patcher = mock.patch.object(module, name, poisoned)
                patcher.start()
                patchers.append(patcher)
            assessment = self._verify()
        finally:
            for patcher in reversed(patchers):
                patcher.stop()
        self.assertEqual(assessment.check_ids, CHECK_IDS)

    def test_v_ind_05_structurally_valid_forged_analysis_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["campaigns"][0]["lanes"][0]["candidates"][0]["raw_point_effect"] = (
            "0.799999999999"
        )
        validate_analysis_result(
            forged,
            self.sealed.bundle,
            load_analysis_profile(),
            forged["source_seal_digest"],
        )
        with self.assertRaises(BenchError) as caught:
            self._verify(analysis=forged)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertIn("raw_point_effect", caught.exception.field_path or "")

    def test_v_ind_06_structurally_valid_forged_policy_gm_is_rejected(self) -> None:
        forged = copy.deepcopy(self.policy)
        forged["candidate_results"][0]["worst_campaign_gm"] = "0.700000000000"
        forged["ranking"][0]["worst_campaign_gm"] = "0.700000000000"
        validate_policy_decision(
            forged,
            self.sealed.bundle,
            load_policy_profile(),
            content_digest(self.analysis),
            load_resource_observations().digest,
        )
        with self.assertRaises(BenchError) as caught:
            self._verify(policy=forged)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertIn("worst_campaign_gm", caught.exception.field_path or "")

    def test_v_ind_07_structurally_valid_forged_lane_outcome_is_rejected(self) -> None:
        forged = copy.deepcopy(self.policy)
        lane = forged["candidate_results"][0]["campaign_results"][0]["lanes"][0]
        lane["point_effect"] = "0.800000000001"
        validate_policy_decision(
            forged,
            self.sealed.bundle,
            load_policy_profile(),
            content_digest(self.analysis),
            load_resource_observations().digest,
        )
        with self.assertRaises(BenchError) as caught:
            self._verify(policy=forged)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_v_ind_08_forged_reason_sequence_is_rejected_or_structurally_invalid(self) -> None:
        fabricated = {
            "candidate_arm_id": "candidate",
            "campaign_index": 0,
            "lane_id": None,
            "code": "MISSING_RESOURCE",
        }
        for label, reasons in (
            ("fabricated", [fabricated]),
            ("duplicated", [fabricated, fabricated]),
            (
                "permuted",
                [
                    {**fabricated, "campaign_index": 1},
                    {**fabricated, "campaign_index": 0},
                ],
            ),
        ):
            with self.subTest(label=label):
                forged = copy.deepcopy(self.policy)
                forged["reasons"] = reasons
                with self.assertRaises(BenchError) as caught:
                    self._verify(policy=forged)
                self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


F05_RUN_ID = "00000000-0000-4000-8000-000000000000"


def _f05_document() -> dict:
    def row(arm_id: str, raw: str, retained: str):
        return candidate_row(
            arm_id=arm_id,
            raw=raw,
            retained=retained,
            low="0.700000000000",
            high="0.940000000000",
        )

    def campaign():
        return [
            lane_row(
                "rare-query",
                [
                    row("alpha", "0.800000000000", "0.900000000000"),
                    row("beta", "0.900000000000", "0.800000000000"),
                ],
            ),
            lane_row(
                "common-query",
                [
                    candidate_row(arm_id="alpha", raw="0.900000000000",
                                  retained="0.900000000000",
                                  low="0.800000000000", high="1.000000000000"),
                    candidate_row(arm_id="beta", raw="0.900000000000",
                                  retained="0.900000000000",
                                  low="0.800000000000", high="1.000000000000"),
                ],
            ),
        ]

    return analysis_document([campaign(), campaign()])


def _f05_profile():
    return make_policy_profile(
        candidate_order=("alpha", "beta"),
        targets=(make_threshold("rare-query", "0.950000000000", "1.000000000000", "lt"),),
        guardrails=(make_threshold("common-query", "1.100000000000", "1.100000000000", "le"),),
        resource_rules=(),
        ranking_lanes=("rare-query",),
        tie_preference=("alpha", "beta"),
    )


class PolicyFilterIndependenceTests(unittest.TestCase):
    """F05-IND-01: a poisoned primary filter result is rejected by the reference."""

    def test_f05_ind_01_poisoned_primary_filter_is_rejected_by_reference(self) -> None:
        document = _f05_document()
        profile = _f05_profile()
        resources = make_resources()
        expected = evaluate_reference_policy(
            analysis_document=document,
            policy_profile=profile,
            observations=resources,
            minimum_retained=3,
            experiment_id=EXPERIMENT_ID,
            run_id=F05_RUN_ID,
            analysis_digest=ZERO_DIGEST,
        )
        self.assertEqual(
            [
                (
                    item["candidate_arm_id"],
                    item["campaign_index"],
                    item["lane_id"],
                    item["code"],
                )
                for item in expected["reasons"]
            ],
            [
                ("alpha", 0, "rare-query", "FILTER_SENSITIVE"),
                ("beta", 0, "rare-query", "FILTER_SENSITIVE"),
                ("alpha", 1, "rare-query", "FILTER_SENSITIVE"),
                ("beta", 1, "rare-query", "FILTER_SENSITIVE"),
            ],
        )
        self.assertIsNone(expected["selected_arm_id"])
        self.assertEqual(expected["decision_status"], "INCONCLUSIVE")

        def produce():
            decision = primary_policy.evaluate_policy(
                document, profile, resources, minimum_retained_blocks=3
            )
            return decision.to_document(
                experiment_id=EXPERIMENT_ID,
                run_id=F05_RUN_ID,
                analysis_digest=ZERO_DIGEST,
                policy_profile=profile,
                resource_digest=resources.digest,
            )

        self.assertEqual(produce(), expected)
        with mock.patch.object(
            primary_policy, "_filter_sensitive_lanes", return_value=set()
        ):
            forged = produce()
        self.assertNotEqual(forged, expected)
        self.assertIsNotNone(forged["selected_arm_id"])
        self.assertEqual(forged["decision_status"], "SELECTED_ELIGIBLE_SYNTHETIC")
        difference = _first_difference(expected, forged, "policy")
        self.assertIsNotNone(difference)
        self.assertIn("candidate_results", difference[0])

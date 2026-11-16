"""PRO/SIM/ANA/VER/E2E/REU/SCOPE evidence for the retained-key reference."""

from __future__ import annotations

import atexit
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import mock

from quervant_bench.analysis.contracts import (
    CANDIDATE_ELIGIBLE,
    CANDIDATE_INELIGIBLE,
    DECISION_SELECTED,
    DECISION_TIE_PREFERENCE,
    validate_analysis_result,
    validate_policy_decision,
)
from quervant_bench.analysis.derive import analyze_synthetic_run
from quervant_bench.analysis.policy import (
    REASON_RESOURCE_OVER_LIMIT,
    evaluate_policy,
    read_policy_profile,
    read_resource_observations,
    validate_resource_observations,
)
from quervant_bench.analysis.profiles import read_analysis_profile
from quervant_bench.analysis.pruning import apply_lane_block_exclusions
from quervant_bench.config.codec import (
    canonical_document_bytes,
    content_digest,
    load_document,
)
from quervant_bench.config.contracts import (
    ArmMultiplicity,
    load_experiment_bundle,
)
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_SCOPE_MISMATCH, BenchError
from quervant_bench.evidence.provenance import repository_root
from quervant_bench.execution import (
    FaultPlan,
    FaultPoint,
    LogicalClock,
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    execute_synthetic,
    load_synthetic_scenario,
    replay_sealed_synthetic,
    synthetic_adapter_factory,
)
from quervant_bench.execution.replay import VERIFIED_STATUS
from quervant_bench.migrations.retained_key import (
    REFERENCE_EXPERIMENT_ID,
    load_reference_bundle,
)
from quervant_bench.protocol.controls import build_control_schedule
from quervant_bench.protocol.schedule import ScheduleSpec, _compile_spec, compile_schedule
from quervant_bench.qualification import coordinator
from quervant_bench.qualification.contracts import (
    GATE_ORDER,
    MANIFEST_MEMBERS,
    MEMBER_NAMES,
    validate_acceptance_summary,
    validate_manifest,
)
from quervant_bench.qualification.identity import compute_source_set_digest
from quervant_bench.qualification.profiles import default_profile_path
from quervant_bench.qualification.publication import load_bundle
from quervant_bench.tests.test_qualification_contracts import (
    FIXTURES as QUALIFICATION_FIXTURES,
    qa_workspace,
    rehash_gate_d,
    trust_anchors,
    write_bundle_documents,
)
from quervant_bench.verification.contracts import CHECK_IDS
from quervant_bench.verification.verify import verify_synthetic_run

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
CATALOG = EXPERIMENTS / REFERENCE_EXPERIMENT_ID
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "retained-key"
LEDGER = json.loads((FIXTURES / "reference-expectations.v1.json").read_text())
EFFECTS = LEDGER["expected_effects"]


def profile_digest() -> str:
    return content_digest(load_document(default_profile_path()))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_canonical(path: Path, document: dict[str, Any]) -> None:
    path.write_bytes(canonical_document_bytes(document))


def run_fault(fault: FaultPoint) -> Any:
    bundle = load_reference_bundle(EXPERIMENTS)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        evidence = root / "evidence"
        evidence.mkdir()
        shutil.copyfile(CATALOG / "synthetic-scenario.v1.json", evidence / "synthetic-scenario.v1.json")
        output = root / "out"
        output.mkdir()
        scenario = load_synthetic_scenario(evidence, bundle=bundle)
        return execute_synthetic(
            bundle=bundle,
            scenario=scenario,
            run_id=str(uuid.uuid4()),
            evidence_root=evidence,
            output_base=output,
            adapter_factory=synthetic_adapter_factory(bundle),
            capability_provider=SimulatedCapabilityProvider(),
            readiness_provider=ScenarioReadinessProvider(scenario),
            clock=LogicalClock(),
            faults=FaultPlan(point=fault),
        )


class ReferenceWorkspace:
    """One real BM-03 → BM-06 reference workspace with temporary QA anchors."""

    def __init__(self, *, checked_in_anchors: bool = False) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.catalog = CATALOG
        self.bundle = load_reference_bundle(EXPERIMENTS)
        self.run_id = str(uuid.uuid4())
        self.scenario_root = self.workspace / "scenarios" / REFERENCE_EXPERIMENT_ID / self.run_id
        self.scenario_root.mkdir(parents=True)
        self.scenario_bytes = (CATALOG / "synthetic-scenario.v1.json").read_bytes()
        (self.scenario_root / "synthetic-scenario.v1.json").write_bytes(self.scenario_bytes)
        (self.workspace / "runs").mkdir()
        self.scenario = load_synthetic_scenario(self.scenario_root, bundle=self.bundle)
        self.execution = execute_synthetic(
            bundle=self.bundle,
            scenario=self.scenario,
            run_id=self.run_id,
            evidence_root=self.scenario_root,
            output_base=self.workspace / "runs",
            adapter_factory=synthetic_adapter_factory(self.bundle),
            capability_provider=SimulatedCapabilityProvider(),
            readiness_provider=ScenarioReadinessProvider(self.scenario),
            clock=LogicalClock(),
        )
        if self.execution.status != "sealed":  # pragma: no cover - fixture guard
            raise AssertionError(f"reference fixture did not seal: {self.execution.reason}")
        self.run_dir = self.execution.run_dir
        self.qa_root = self.workspace / "qa"
        if checked_in_anchors:
            self.qa_root.mkdir()
            for name in ("framework-qa-evidence.json", "source-qa-evidence.json"):
                shutil.copyfile(QUALIFICATION_FIXTURES / name, self.qa_root / name)
            for name in ("framework-qa", "source-qa"):
                shutil.copytree(QUALIFICATION_FIXTURES / name, self.qa_root / name)
            checked_in = trust_anchors()
            self.anchors = {
                "kind": "simulated-qualification-trust-anchors",
                "schema_version": 1,
                "profile_digest": checked_in["profile_digest"],
                "framework_qa_digest": checked_in["framework_qa_digest"],
                "source_qa_digest": checked_in["source_qa_digest"],
                "source_set_digest": checked_in["source_set_digest"],
            }
        else:
            source_digest = compute_source_set_digest(REPO_ROOT)
            _qa_root, qa_digests = qa_workspace(
                self.qa_root, source_set_digest=source_digest
            )
            self.anchors = {
                "kind": "simulated-qualification-trust-anchors",
                "schema_version": 1,
                "profile_digest": profile_digest(),
                "framework_qa_digest": qa_digests["framework_qa_digest"],
                "source_qa_digest": qa_digests["source_qa_digest"],
                "source_set_digest": source_digest,
            }
        write_canonical(self.workspace / "qualification-anchors.v1.json", self.anchors)
        (self.workspace / "qualified").mkdir()
        self.result = coordinator.qualify_synthetic_run(
            bundle=self.bundle,
            run_dir=self.run_dir,
            scenario_root=self.scenario_root,
            profiles_root=self.catalog,
            resources_root=self.catalog,
            qualification_profile_path=default_profile_path(),
            qa_evidence_root=self.qa_root,
            expected_profile_digest=self.anchors["profile_digest"],
            expected_framework_qa_digest=self.anchors["framework_qa_digest"],
            expected_source_qa_digest=self.anchors["source_qa_digest"],
            source_root=REPO_ROOT,
            expected_source_set_digest=self.anchors["source_set_digest"],
            output_base=self.workspace / "qualified",
        )
        self.committed = load_bundle(
            output_base=self.workspace / "qualified",
            experiment_id=REFERENCE_EXPERIMENT_ID,
            run_id=self.run_id,
        )
        self.documents = self.committed.documents

    def close(self) -> None:
        self._temporary.cleanup()


_CACHE: dict[str, Any] = {}


def cached_workspace() -> ReferenceWorkspace:
    if "workspace" not in _CACHE:
        workspace = ReferenceWorkspace()
        _CACHE["workspace"] = workspace
        atexit.register(workspace.close)
    return _CACHE["workspace"]


def load_workspace(workspace: Path, run_id: str) -> Any:
    anchors = read_json(workspace / "qualification-anchors.v1.json")
    return coordinator.load_qualified_synthetic_run(
        bundle=load_reference_bundle(EXPERIMENTS),
        run_dir=workspace / "runs" / REFERENCE_EXPERIMENT_ID / run_id,
        scenario_root=workspace / "scenarios" / REFERENCE_EXPERIMENT_ID / run_id,
        profiles_root=CATALOG,
        resources_root=CATALOG,
        qualification_profile_path=default_profile_path(),
        qa_evidence_root=workspace / "qa",
        expected_profile_digest=anchors["profile_digest"],
        expected_framework_qa_digest=anchors["framework_qa_digest"],
        expected_source_qa_digest=anchors["source_qa_digest"],
        source_root=REPO_ROOT,
        expected_source_set_digest=anchors["source_set_digest"],
        output_base=workspace / "qualified",
    )


def copy_workspace() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
    target = Path(temporary.name) / "workspace"
    shutil.copytree(cached_workspace().workspace, target)
    return temporary, target


class ScheduleTests(unittest.TestCase):
    """PRO-01/PRO-02."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_reference_bundle(EXPERIMENTS)

    def test_pro_01_schedule_has_two_appearances_of_every_treatment_arm(self) -> None:
        schedule = compile_schedule(self.bundle)
        self.assertEqual(schedule.blocks, 4)
        self.assertEqual(schedule.slots_per_block, 8)
        self.assertEqual(len(schedule.slots), 32)
        for block in range(1, 5):
            counts = {
                arm: sum(
                    1 for slot in schedule.slots
                    if slot.block == block and slot.arm_id == arm
                )
                for arm in ("baseline", "linear", "prefilter", "exact-set")
            }
            self.assertEqual(set(counts.values()), {2})
        self.assertEqual(schedule.seed, 42)
        self.assertEqual(schedule, compile_schedule(self.bundle))
        control = build_control_schedule(self.bundle, control_source_arm_id="baseline")
        self.assertEqual(control.status, "scheduled")
        self.assertEqual(control.campaign_count, 1)
        self.assertEqual(control.compiled.blocks, 4)
        self.assertEqual(control.compiled.slots_per_block, 2)

    def test_pro_02_missing_or_duplicate_arm_slot_is_rejected(self) -> None:
        base = compile_schedule(self.bundle)
        missing = ScheduleSpec(
            schedule_id=base.schedule_id,
            mode="seeded-balanced",
            blocks=4,
            slots_per_block=8,
            seed=42,
            multiplicities=(
                ArmMultiplicity(arm_id="baseline", slots_per_block=2),
                ArmMultiplicity(arm_id="linear", slots_per_block=2),
                ArmMultiplicity(arm_id="prefilter", slots_per_block=2),
            ),
            explicit_orders=None,
            protocol_digest=self.bundle.protocol_digest,
        )
        with self.assertRaises(BenchError) as raised:
            _compile_spec(missing)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        duplicate = ScheduleSpec(
            schedule_id=base.schedule_id,
            mode="seeded-balanced",
            blocks=4,
            slots_per_block=8,
            seed=42,
            multiplicities=(
                ArmMultiplicity(arm_id="baseline", slots_per_block=2),
                ArmMultiplicity(arm_id="baseline", slots_per_block=2),
                ArmMultiplicity(arm_id="linear", slots_per_block=2),
                ArmMultiplicity(arm_id="prefilter", slots_per_block=2),
            ),
            explicit_orders=None,
            protocol_digest=self.bundle.protocol_digest,
        )
        with self.assertRaises(BenchError) as raised:
            _compile_spec(duplicate)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


class SyntheticExecutionTests(unittest.TestCase):
    """SIM-01…SIM-03."""

    def test_sim_01_real_seeded_execution_and_replay_are_deterministic(self) -> None:
        workspace = cached_workspace()
        scenario_before = hashlib.sha256(
            (workspace.scenario_root / "synthetic-scenario.v1.json").read_bytes()
        ).hexdigest()
        source_before = {
            name: hashlib.sha256((CATALOG / name).read_bytes()).hexdigest()
            for name in ("workloads.yaml", "protocol.yaml", "synthetic-scenario.v1.json")
        }
        replay = replay_sealed_synthetic(
            workspace.run_dir,
            bundle=workspace.bundle,
            scenario_root=workspace.scenario_root,
        )
        self.assertEqual(replay.status, VERIFIED_STATUS)
        self.assertEqual(replay.controls_completed, 1)
        self.assertEqual(replay.treatments_completed, 2)
        self.assertEqual(replay.slots_completed, 72)
        self.assertEqual(replay.lane_envelopes, 576)
        self.assertEqual(replay.synthetic_samples, 1728)
        self.assertEqual(
            scenario_before,
            hashlib.sha256(
                (workspace.scenario_root / "synthetic-scenario.v1.json").read_bytes()
            ).hexdigest(),
        )
        after = {
            name: hashlib.sha256((CATALOG / name).read_bytes()).hexdigest()
            for name in source_before
        }
        self.assertEqual(source_before, after)

    def test_sim_02_blocked_readiness_stops_before_qualification(self) -> None:
        result = run_fault(FaultPoint.READINESS_BLOCKED)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "host-not-ready")

    def test_sim_03_failed_oracle_stops_before_qualification(self) -> None:
        result = run_fault(FaultPoint.ORACLE_FAIL)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "oracle-failed")


class AnalysisTests(unittest.TestCase):
    """ANA-01…ANA-04."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = cached_workspace()
        cls.analysis, cls.policy = analyze_synthetic_run(
            bundle=cls.workspace.bundle,
            run_dir=cls.workspace.run_dir,
            scenario_root=cls.workspace.scenario_root,
            profiles_root=CATALOG,
            resources_root=CATALOG,
        )
        cls.profile = read_analysis_profile(CATALOG, cls.workspace.bundle)
        cls.policy_profile = read_policy_profile(CATALOG, cls.workspace.bundle)

    def test_ana_01_paired_effects_and_policy_are_exact_and_synthetic(self) -> None:
        validate_analysis_result(
            self.analysis,
            self.workspace.bundle,
            self.profile,
            self.analysis["source_seal_digest"],
        )
        for campaign in self.analysis["campaigns"]:
            for lane in campaign["lanes"]:
                for candidate in lane["candidates"]:
                    arm = candidate["candidate_arm_id"]
                    self.assertEqual(candidate["status"], "analyzed")
                    self.assertEqual(candidate["retained_point_effect"], EFFECTS[arm])
                    self.assertEqual(candidate["ci_low"], EFFECTS[arm])
                    self.assertEqual(candidate["ci_high"], EFFECTS[arm])
        self.assertEqual(self.policy["decision_status"], DECISION_SELECTED)
        self.assertEqual(self.policy["selected_arm_id"], "prefilter")
        self.assertEqual(
            [entry["arm_id"] for entry in self.policy["ranking"]],
            ["prefilter", "exact-set", "linear"],
        )
        self.assertEqual(self.policy["evidence_origin"], "synthetic")
        self.assertEqual(self.policy["qualification_scope"], "simulated")
        validate_policy_decision(
            self.policy,
            self.workspace.bundle,
            self.policy_profile,
            content_digest(self.analysis),
            read_resource_observations(CATALOG, self.workspace.bundle).digest,
        )

    def test_ana_02_symmetric_pruning_is_outcome_blind(self) -> None:
        medians = {
            1: {"baseline": [Decimal(100), Decimal(100)], "linear": [Decimal(94), Decimal(94)]},
            2: {"baseline": [Decimal(100), Decimal(170)], "linear": [Decimal(94), Decimal(94)]},
            3: {"baseline": [Decimal(100), Decimal(100)], "linear": [Decimal(94), Decimal(94)]},
            4: {"baseline": [Decimal(100), Decimal(100)], "linear": [Decimal(94), Decimal(94)]},
        }
        ledger = apply_lane_block_exclusions(medians, self.profile, "large-medium")
        self.assertEqual(ledger.retained_blocks, (1, 3, 4))
        self.assertEqual(ledger.excluded_blocks, (2,))
        excluded = [row for row in ledger.rows if row.status == "excluded"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0].trigger_arms, ("baseline",))

    def test_ana_03_resource_boundary_is_exact(self) -> None:
        base = read_json(CATALOG / "resource-observations.v1.json")
        for value, expected in ((2097152, CANDIDATE_ELIGIBLE), (2097153, CANDIDATE_INELIGIBLE)):
            document = copy.deepcopy(base)
            for record in document["records"]:
                if record["arm_id"] == "exact-set":
                    record["value_bytes"] = value
            observations = validate_resource_observations(document, self.workspace.bundle)
            decision = evaluate_policy(
                self.analysis,
                self.policy_profile,
                observations,
                minimum_retained_blocks=self.profile.exclusion.minimum_retained_blocks,
            )
            exact = next(
                item for item in decision.candidate_results if item.arm_id == "exact-set"
            )
            self.assertEqual(exact.status, expected)
            if value == 2097153:
                self.assertTrue(
                    any(
                        reason.code == REASON_RESOURCE_OVER_LIMIT
                        and reason.candidate_arm_id == "exact-set"
                        for reason in decision.reasons
                    )
                )

    def test_ana_04_threshold_and_tie_operators_are_exact(self) -> None:
        mutated = copy.deepcopy(self.analysis)
        for campaign in mutated["campaigns"]:
            for lane in campaign["lanes"]:
                if lane["lane_id"] != "large-medium":
                    continue
                for candidate in lane["candidates"]:
                    if candidate["candidate_arm_id"] == "exact-set":
                        candidate["raw_point_effect"] = "0.950000000000"
                        candidate["retained_point_effect"] = "0.950000000000"
                        candidate["ci_low"] = "0.950000000000"
                        candidate["ci_high"] = "1.000000000000"
        observations = read_resource_observations(CATALOG, self.workspace.bundle)
        decision = evaluate_policy(
            mutated,
            self.policy_profile,
            observations,
            minimum_retained_blocks=self.profile.exclusion.minimum_retained_blocks,
        )
        exact = next(item for item in decision.candidate_results if item.arm_id == "exact-set")
        self.assertEqual(exact.status, "INCONCLUSIVE")
        self.assertTrue(
            any(
                reason.code == "TARGET_UNPROVEN"
                and reason.candidate_arm_id == "exact-set"
                and reason.lane_id == "large-medium"
                for reason in decision.reasons
            )
        )

        guardrail_boundary = copy.deepcopy(self.analysis)
        for campaign in guardrail_boundary["campaigns"]:
            for lane in campaign["lanes"]:
                if lane["lane_id"] != "large-common":
                    continue
                for candidate in lane["candidates"]:
                    if candidate["candidate_arm_id"] == "linear":
                        candidate["raw_point_effect"] = "1.100000000000"
                        candidate["retained_point_effect"] = "1.100000000000"
                        candidate["ci_low"] = "1.100000000000"
                        candidate["ci_high"] = "1.100000000000"
        boundary_decision = evaluate_policy(
            guardrail_boundary,
            self.policy_profile,
            observations,
            minimum_retained_blocks=self.profile.exclusion.minimum_retained_blocks,
        )
        linear = next(
            item for item in boundary_decision.candidate_results if item.arm_id == "linear"
        )
        self.assertEqual(linear.status, CANDIDATE_ELIGIBLE)

        tied = copy.deepcopy(self.analysis)
        for campaign in tied["campaigns"]:
            for lane in campaign["lanes"]:
                if lane["lane_id"] not in ("large-common", "large-medium"):
                    continue
                for candidate in lane["candidates"]:
                    if candidate["candidate_arm_id"] == "exact-set":
                        candidate["raw_point_effect"] = "0.790000000000"
                        candidate["retained_point_effect"] = "0.790000000000"
                        candidate["ci_low"] = "0.790000000000"
                        candidate["ci_high"] = "0.790000000000"
        tie_decision = evaluate_policy(
            tied,
            self.policy_profile,
            observations,
            minimum_retained_blocks=self.profile.exclusion.minimum_retained_blocks,
        )
        self.assertEqual(tie_decision.decision_status, DECISION_TIE_PREFERENCE)
        self.assertEqual(tie_decision.selected_arm_id, "prefilter")


class VerificationTests(unittest.TestCase):
    """VER-01…VER-03."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = cached_workspace()
        cls.analysis = cls.workspace.documents["analysis.json"]
        cls.policy = cls.workspace.documents["policy.json"]

    def test_ver_01_nine_independent_checks_pass(self) -> None:
        assessment = verify_synthetic_run(
            bundle=self.workspace.bundle,
            run_dir=self.workspace.run_dir,
            scenario_root=self.workspace.scenario_root,
            profiles_root=CATALOG,
            resources_root=CATALOG,
            analysis_document=self.analysis,
            policy_document=self.policy,
        )
        self.assertEqual(assessment.status, "verified-synthetic")
        self.assertEqual(tuple(assessment.check_ids), CHECK_IDS)
        self.assertEqual(len(CHECK_IDS), 9)

    def test_ver_02_forged_analysis_is_rejected(self) -> None:
        forged = copy.deepcopy(self.analysis)
        forged["campaigns"][0]["lanes"][0]["candidates"][0]["ci_low"] = "0.000000000000"
        with self.assertRaises(BenchError):
            verify_synthetic_run(
                bundle=self.workspace.bundle,
                run_dir=self.workspace.run_dir,
                scenario_root=self.workspace.scenario_root,
                profiles_root=CATALOG,
                resources_root=CATALOG,
                analysis_document=forged,
                policy_document=self.policy,
            )

    def test_ver_03_forged_policy_selection_is_rejected(self) -> None:
        forged = copy.deepcopy(self.policy)
        forged["selected_arm_id"] = "linear"
        with self.assertRaises(BenchError):
            verify_synthetic_run(
                bundle=self.workspace.bundle,
                run_dir=self.workspace.run_dir,
                scenario_root=self.workspace.scenario_root,
                profiles_root=CATALOG,
                resources_root=CATALOG,
                analysis_document=self.analysis,
                policy_document=forged,
            )


class QualificationTests(unittest.TestCase):
    """E2E-01, REU-01, SCOPE-01/02."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = cached_workspace()

    def test_e2e_01_exact_simulated_fifteen_file_bundle_and_receipts(self) -> None:
        self.assertEqual(self.workspace.result.disposition, "SIMULATED_QUALIFIED")
        directory = self.workspace.result.output_directory
        self.assertEqual(
            sorted(entry.name for entry in directory.iterdir()), sorted(MEMBER_NAMES)
        )
        self.assertEqual(len(MEMBER_NAMES), 15)
        manifest = validate_manifest(self.workspace.documents["manifest.json"])
        self.assertEqual(len(manifest["members"]), len(MANIFEST_MEMBERS))
        receipts = {
            name: self.workspace.documents[name]["gate"]
            for name in (
                "admission.json",
                "analysis-receipt.json",
                "verification.json",
                "framework-qa.json",
                "source-qa.json",
                "acceptance.json",
                "attestation.json",
            )
        }
        self.assertEqual(set(receipts.values()), set(GATE_ORDER))
        summary = validate_acceptance_summary(
            self.workspace.documents["acceptance-summary.json"]
        )
        self.assertEqual(summary["policy_decision_status"], DECISION_SELECTED)
        self.assertEqual(summary["qualification_scope"], "simulated")
        self.assertNotIn("official", json.dumps(self.workspace.documents).lower())

    def test_e2e_02_missing_seal_prevents_any_attestation(self) -> None:
        temporary, copy_root = copy_workspace()
        self.addCleanup(temporary.cleanup)
        seal = copy_root / "runs" / REFERENCE_EXPERIMENT_ID / self.workspace.run_id / "seal.json"
        seal.unlink()
        with self.assertRaises(BenchError):
            load_workspace(copy_root, self.workspace.run_id)

    def test_e2e_03_coherently_rehashed_forged_receipt_is_rejected(self) -> None:
        temporary, copy_root = copy_workspace()
        self.addCleanup(temporary.cleanup)
        directory = copy_root / "qualified" / REFERENCE_EXPERIMENT_ID / self.workspace.run_id
        documents = {name: read_json(directory / name) for name in MEMBER_NAMES}
        documents["acceptance-summary.json"]["policy_decision_status"] = (
            "TIE_PREFERENCE_NOT_PROVEN_FASTER"
        )
        rehash_gate_d(documents)
        write_bundle_documents(
            copy_root / "qualified", REFERENCE_EXPERIMENT_ID, self.workspace.run_id, documents
        )
        with self.assertRaises(BenchError):
            load_workspace(copy_root, self.workspace.run_id)

    def test_reu_01_identical_reuse_never_recomputes_or_writes(self) -> None:
        workspace = self.workspace
        with mock.patch.object(
            coordinator, "analyze_synthetic_run", side_effect=AssertionError("derived")
        ), mock.patch.object(
            coordinator, "verify_synthetic_run", side_effect=AssertionError("verified")
        ), mock.patch.object(
            coordinator, "publish_bundle", side_effect=AssertionError("published")
        ), mock.patch(
            "quervant_bench.execution.controller.execute_synthetic",
            side_effect=AssertionError("executed"),
        ):
            result = load_workspace(workspace.workspace, workspace.run_id)
        self.assertEqual(result.disposition, "REUSED_VERIFIED")
        self.assertEqual(result.manifest_digest, workspace.result.manifest_digest)

    def test_reu_02_scenario_or_seal_change_is_rejected(self) -> None:
        temporary, copy_root = copy_workspace()
        self.addCleanup(temporary.cleanup)
        scenario = copy_root / "scenarios" / REFERENCE_EXPERIMENT_ID / self.workspace.run_id / "synthetic-scenario.v1.json"
        scenario.write_bytes(scenario.read_bytes() + b" ")
        with self.assertRaises(BenchError):
            load_workspace(copy_root, self.workspace.run_id)

        temporary, copy_root = copy_workspace()
        self.addCleanup(temporary.cleanup)
        lane = next((copy_root / "runs" / REFERENCE_EXPERIMENT_ID / self.workspace.run_id / "slots").rglob("large-absent.json"))
        lane.write_bytes(lane.read_bytes() + b" ")
        with self.assertRaises(BenchError):
            load_workspace(copy_root, self.workspace.run_id)

    def test_reu_03_qa_manifest_or_anchor_change_is_rejected(self) -> None:
        temporary, copy_root = copy_workspace()
        self.addCleanup(temporary.cleanup)
        record = copy_root / "qa" / "framework-qa" / "python-contracts.json"
        record.write_bytes(record.read_bytes() + b" ")
        with self.assertRaises(BenchError):
            load_workspace(copy_root, self.workspace.run_id)

        temporary, copy_root = copy_workspace()
        self.addCleanup(temporary.cleanup)
        manifest = (
            copy_root
            / "qualified"
            / REFERENCE_EXPERIMENT_ID
            / self.workspace.run_id
            / "manifest.json"
        )
        manifest.write_bytes(manifest.read_bytes() + b" ")
        with self.assertRaises(BenchError):
            load_workspace(copy_root, self.workspace.run_id)

        temporary, copy_root = copy_workspace()
        self.addCleanup(temporary.cleanup)
        anchors = read_json(copy_root / "qualification-anchors.v1.json")
        anchors["source_set_digest"] = "sha256:" + "0" * 64
        write_canonical(copy_root / "qualification-anchors.v1.json", anchors)
        with self.assertRaises(BenchError):
            load_workspace(copy_root, self.workspace.run_id)

    def test_scope_01_committed_evidence_remains_synthetic(self) -> None:
        for name in MEMBER_NAMES:
            document = self.workspace.documents[name]
            if "evidence_origin" in document:
                self.assertEqual(document["evidence_origin"], "synthetic", name)
            if "qualification_scope" in document:
                self.assertEqual(document["qualification_scope"], "simulated", name)

    def test_scope_02_relabelled_and_coherently_rehashed_scope_is_rejected(self) -> None:
        temporary, copy_root = copy_workspace()
        self.addCleanup(temporary.cleanup)
        directory = copy_root / "qualified" / REFERENCE_EXPERIMENT_ID / self.workspace.run_id
        documents = {name: read_json(directory / name) for name in MEMBER_NAMES}
        documents["acceptance-summary.json"]["evidence_origin"] = "official"
        documents["acceptance-summary.json"]["qualification_scope"] = "official"
        rehash_gate_d(documents)
        write_bundle_documents(
            copy_root / "qualified", REFERENCE_EXPERIMENT_ID, self.workspace.run_id, documents
        )
        with self.assertRaises(BenchError) as raised:
            load_workspace(copy_root, self.workspace.run_id)
        self.assertIn(
            raised.exception.code,
            {BM_SCOPE_MISMATCH, BM_IDENTITY_INVALID, "BM_SCHEMA_INVALID"},
        )


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

"""SCH/SIM/ANA/VER/E2E/REU/SCOPE/SAFE evidence for the cross-engine family."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from quervant_bench.analysis.contracts import (
    DECISION_INCONCLUSIVE,
    validate_analysis_result,
    validate_policy_decision,
)
from quervant_bench.analysis.derive import analyze_synthetic_run
from quervant_bench.analysis.policy import (
    evaluate_policy,
    read_policy_profile,
    read_resource_observations,
)
from quervant_bench.analysis.profiles import read_analysis_profile
from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.contracts import ArmMultiplicity
from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BenchError,
)
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
from quervant_bench.migrations import cross_engine as cross_engine_module
from quervant_bench.migrations import offline
from quervant_bench.migrations.cross_engine import (
    REFERENCE_EXPERIMENT_ID,
    load_cross_engine_reference,
    qualify_cross_engine_synthetic,
    reference_catalog_root,
    validate_cross_engine_reference,
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
from quervant_bench.qualification.profiles import default_profile_path
from quervant_bench.tests.cross_engine_support import (
    CATALOG,
    EXPECTATIONS,
    FIXTURES,
    LEGACY_MATRIX,
    REPO_ROOT,
    CatalogEditor,
    CrossEngineWorkspace,
    cached_workspace,
    copy_catalog,
    copy_workspace,
    read_json,
    snapshot,
    write_canonical,
)
from quervant_bench.tests.test_qualification_contracts import (
    rehash_gate_d,
    write_bundle_documents,
)
from quervant_bench.verification.contracts import CHECK_IDS

ARMS = EXPECTATIONS["arm_ids"]
LANES = EXPECTATIONS["lane_ids"]
COUNTS = EXPECTATIONS["expected_counts"]
EFFECTS = EXPECTATIONS["expected_effects"]


def documents_of(directory: Path) -> dict[str, Any]:
    """Return the canonical documents of one committed 15-file bundle."""

    return {
        path.name: read_json(path)
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def run_fault(fault: FaultPoint, *, catalog_root: Path | None = None) -> object:
    root = reference_catalog_root(REPO_ROOT) if catalog_root is None else catalog_root
    experiment_root = root / REFERENCE_EXPERIMENT_ID
    bundle, _digests = validate_cross_engine_reference(root, REPO_ROOT)
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        evidence = base / "evidence"
        evidence.mkdir()
        shutil.copyfile(
            experiment_root / "synthetic-scenario.v1.json",
            evidence / "synthetic-scenario.v1.json",
        )
        output = base / "out"
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


class ScheduleTests(unittest.TestCase):
    """SCH-01…SCH-03."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_cross_engine_reference(reference_catalog_root(REPO_ROOT))

    def test_sch_01_balanced_schedule_multiplicity_and_seed(self) -> None:
        schedule = compile_schedule(self.bundle)
        self.assertEqual(schedule.blocks, EXPECTATIONS["schedule"]["blocks"])
        self.assertEqual(
            schedule.slots_per_block, EXPECTATIONS["schedule"]["slots_per_block"]
        )
        self.assertEqual(
            len(schedule.slots),
            EXPECTATIONS["schedule"]["blocks"]
            * EXPECTATIONS["schedule"]["slots_per_block"],
        )
        for block in range(1, EXPECTATIONS["schedule"]["blocks"] + 1):
            counts = {
                arm: sum(
                    1
                    for slot in schedule.slots
                    if slot.block == block and slot.arm_id == arm
                )
                for arm in ARMS
            }
            self.assertEqual(
                set(counts.values()),
                {EXPECTATIONS["schedule"]["slots_per_arm_per_block"]},
            )
        self.assertEqual(schedule.seed, EXPECTATIONS["schedule"]["seed"])
        self.assertEqual(schedule, compile_schedule(self.bundle))
        control = build_control_schedule(self.bundle, control_source_arm_id="quervant")
        self.assertEqual(control.status, "scheduled")
        self.assertEqual(control.campaign_count, 1)
        self.assertEqual(control.compiled.blocks, EXPECTATIONS["schedule"]["blocks"])
        self.assertEqual(control.compiled.slots_per_block, 2)

    def test_sch_02_missing_duplicate_or_unknown_arm_slot_is_rejected(self) -> None:
        base = compile_schedule(self.bundle)
        for multiplicities in (
            (
                ArmMultiplicity(arm_id="quervant", slots_per_block=2),
                ArmMultiplicity(arm_id="tantivy", slots_per_block=2),
            ),
            (
                ArmMultiplicity(arm_id="quervant", slots_per_block=3),
                ArmMultiplicity(arm_id="tantivy", slots_per_block=2),
                ArmMultiplicity(arm_id="lucene", slots_per_block=2),
            ),
            (
                ArmMultiplicity(arm_id="quervant", slots_per_block=2),
                ArmMultiplicity(arm_id="tantivy", slots_per_block=2),
                ArmMultiplicity(arm_id="lucene", slots_per_block=2),
                ArmMultiplicity(arm_id="opensearch", slots_per_block=2),
            ),
        ):
            with self.subTest(multiplicities=multiplicities):
                spec = ScheduleSpec(
                    schedule_id=base.schedule_id,
                    mode="seeded-balanced",
                    blocks=EXPECTATIONS["schedule"]["blocks"],
                    slots_per_block=EXPECTATIONS["schedule"]["slots_per_block"],
                    seed=EXPECTATIONS["schedule"]["seed"],
                    multiplicities=multiplicities,
                    explicit_orders=None,
                    protocol_digest=self.bundle.protocol_digest,
                )
                with self.assertRaises(BenchError):
                    _compile_spec(spec)

    def test_sch_03_wrong_seed_changes_the_schedule(self) -> None:
        base = compile_schedule(self.bundle)
        other = ScheduleSpec(
            schedule_id=base.schedule_id,
            mode="seeded-balanced",
            blocks=EXPECTATIONS["schedule"]["blocks"],
            slots_per_block=EXPECTATIONS["schedule"]["slots_per_block"],
            seed=EXPECTATIONS["schedule"]["seed"] + 1,
            multiplicities=tuple(
                ArmMultiplicity(arm_id=arm, slots_per_block=2) for arm in ARMS
            ),
            explicit_orders=None,
            protocol_digest=self.bundle.protocol_digest,
        )
        compiled = _compile_spec(other)
        self.assertNotEqual(
            [(slot.block, slot.position, slot.arm_id) for slot in compiled.slots],
            [(slot.block, slot.position, slot.arm_id) for slot in base.slots],
        )


class SyntheticExecutionTests(unittest.TestCase):
    """SIM-01…SIM-05."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = cached_workspace()

    def test_sim_01_real_seeded_execution_counts_and_inputs_are_frozen(self) -> None:
        workspace = self.workspace
        scenario_before = hashlib.sha256(
            (workspace.scenario_root / "synthetic-scenario.v1.json").read_bytes()
        ).hexdigest()
        catalog_before = {
            name: hashlib.sha256((CATALOG / name).read_bytes()).hexdigest()
            for name in sorted(p.name for p in CATALOG.iterdir())
        }
        replay = replay_sealed_synthetic(
            workspace.run_dir, bundle=workspace.bundle, scenario_root=workspace.scenario_root
        )
        self.assertEqual(replay.status, VERIFIED_STATUS)
        self.assertEqual(replay.controls_completed, COUNTS["controls_completed"])
        self.assertEqual(replay.treatments_completed, COUNTS["treatments_completed"])
        self.assertEqual(replay.slots_completed, COUNTS["slots_completed"])
        self.assertEqual(replay.lane_envelopes, COUNTS["lane_envelopes"])
        self.assertEqual(replay.synthetic_samples, COUNTS["synthetic_samples"])
        self.assertEqual(
            scenario_before,
            hashlib.sha256(
                (workspace.scenario_root / "synthetic-scenario.v1.json").read_bytes()
            ).hexdigest(),
        )
        catalog_after = {
            name: hashlib.sha256((CATALOG / name).read_bytes()).hexdigest()
            for name in sorted(p.name for p in CATALOG.iterdir())
        }
        self.assertEqual(catalog_before, catalog_after)

    def test_sim_02_blocked_readiness_stops_before_qualification(self) -> None:
        result = run_fault(FaultPoint.READINESS_BLOCKED)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "host-not-ready")

    def test_sim_03_failed_oracle_stops_before_qualification(self) -> None:
        result = run_fault(FaultPoint.ORACLE_FAIL)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "oracle-failed")

    def test_sim_04_wrong_measured_count_and_missing_seal_stop_the_run(self) -> None:
        wrong_count = run_fault(FaultPoint.MEASUREMENT_WRONG_COUNT)
        self.assertEqual(wrong_count.status, "stopped")
        unsealed = run_fault(FaultPoint.BEFORE_SEAL)
        self.assertEqual(unsealed.status, "stopped")
        self.assertNotEqual(
            getattr(unsealed, "status", None), "sealed"
        )

    def test_sim_05_only_the_synthetic_simulator_can_execute(self) -> None:
        bundle = load_cross_engine_reference(reference_catalog_root(REPO_ROOT))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            evidence = base / "evidence"
            evidence.mkdir()
            shutil.copyfile(
                CATALOG / "synthetic-scenario.v1.json",
                evidence / "synthetic-scenario.v1.json",
            )
            output = base / "out"
            output.mkdir()
            scenario = load_synthetic_scenario(evidence, bundle=bundle)
            # A source-and-binary identity is refused before any acquisition.
            forged = mock.Mock()
            with self.assertRaises(BenchError) as raised:
                synthetic_adapter_factory(forged)
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            import dataclasses

            real_bundle = load_cross_engine_reference(
                reference_catalog_root(REPO_ROOT)
            )
            source_and_binary = dataclasses.replace(
                real_bundle,
                adapter=dataclasses.replace(
                    real_bundle.adapter,
                    build_identity=dataclasses.replace(
                        real_bundle.adapter.build_identity,
                        kind="source-and-binary",
                        source_digest="sha256:" + "1" * 64,
                        executable_digest="sha256:" + "2" * 64,
                    ),
                ),
            )
            with self.assertRaises(BenchError) as raised:
                synthetic_adapter_factory(source_and_binary)
            self.assertEqual(raised.exception.code, BM_ACQUISITION_PROHIBITED)
            # And the real controller refuses a non-synthetic bundle.
            with self.assertRaises(BenchError) as raised:
                execute_synthetic(
                    bundle=forged,
                    scenario=scenario,
                    run_id=str(uuid.uuid4()),
                    evidence_root=evidence,
                    output_base=output,
                    adapter_factory=synthetic_adapter_factory(bundle),
                    capability_provider=SimulatedCapabilityProvider(),
                    readiness_provider=ScenarioReadinessProvider(scenario),
                    clock=LogicalClock(),
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
            self.assertFalse((output / REFERENCE_EXPERIMENT_ID).exists())


class AnalysisTests(unittest.TestCase):
    """ANA-01…ANA-05."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = cached_workspace()
        cls.analysis, cls.policy = analyze_synthetic_run(
            bundle=cls.workspace.bundle,
            run_dir=cls.workspace.run_dir,
            scenario_root=cls.workspace.scenario_root,
            profiles_root=cls.workspace.experiment_root,
            resources_root=cls.workspace.experiment_root,
        )
        cls.profile = read_analysis_profile(cls.workspace.experiment_root, cls.workspace.bundle)
        cls.policy_profile = read_policy_profile(
            cls.workspace.experiment_root, cls.workspace.bundle
        )
        cls.resources = read_resource_observations(
            cls.workspace.experiment_root, cls.workspace.bundle
        )

    def test_ana_01_effects_and_confidence_bounds_are_independently_known(self) -> None:
        validate_analysis_result(
            self.analysis,
            self.workspace.bundle,
            self.profile,
            self.analysis["source_seal_digest"],
        )
        self.assertEqual(len(self.analysis["campaigns"]), 2)
        for campaign in self.analysis["campaigns"]:
            self.assertEqual(len(campaign["lanes"]), 16)
            for lane in campaign["lanes"]:
                for candidate in lane["candidates"]:
                    arm = candidate["candidate_arm_id"]
                    self.assertEqual(candidate["status"], "analyzed")
                    self.assertEqual(candidate["retained_point_effect"], EFFECTS[arm])
                    self.assertEqual(candidate["ci_low"], EFFECTS[arm])
                    self.assertEqual(candidate["ci_high"], EFFECTS[arm])

    def test_ana_02_decision_is_inconclusive_and_synthetic(self) -> None:
        self.assertEqual(self.policy["decision_status"], DECISION_INCONCLUSIVE)
        self.assertIsNone(self.policy["selected_arm_id"])
        self.assertEqual(self.policy["ranking"], [])
        self.assertEqual(self.policy["evidence_origin"], "synthetic")
        self.assertEqual(self.policy["qualification_scope"], "simulated")
        validate_policy_decision(
            self.policy,
            self.workspace.bundle,
            self.policy_profile,
            content_digest(self.analysis),
            self.resources.digest,
        )

    def test_ana_03_thresholds_are_strict_and_not_adjusted(self) -> None:
        self.assertEqual(
            str(self.policy_profile.targets[0].point_upper),
            EXPECTATIONS["target_point_upper"],
        )
        self.assertEqual(
            str(self.policy_profile.targets[0].ci_upper),
            EXPECTATIONS["target_ci_upper"],
        )
        self.assertEqual(self.policy_profile.targets[0].ci_operator, "lt")
        self.assertEqual(
            str(self.policy_profile.guardrails[0].point_upper),
            EXPECTATIONS["guardrail_point_upper"],
        )
        self.assertEqual(
            str(self.policy_profile.guardrails[0].ci_upper),
            EXPECTATIONS["guardrail_ci_upper"],
        )
        self.assertEqual(self.policy_profile.guardrails[0].ci_operator, "le")
        # Point 1.0 is above the 0.95 target and CI 1.0 is not < 1.0, so no
        # candidate can be proven eligible by the frozen rules.
        decision = evaluate_policy(
            self.analysis,
            self.policy_profile,
            self.resources,
            minimum_retained_blocks=3,
        )
        self.assertEqual(decision.decision_status, DECISION_INCONCLUSIVE)
        self.assertIsNone(decision.selected_arm_id)

    def test_ana_04_altered_selection_or_threshold_is_rejected(self) -> None:
        altered = json.loads(json.dumps(self.policy))
        altered["selected_arm_id"] = "tantivy"
        with self.assertRaises(BenchError):
            validate_policy_decision(
                altered,
                self.workspace.bundle,
                self.policy_profile,
                content_digest(self.analysis),
                self.resources.digest,
            )
        altered_ci = json.loads(json.dumps(self.analysis))
        altered_ci["campaigns"][0]["lanes"][0]["candidates"][0]["ci_high"] = (
            "0.990000000000"
        )
        with self.assertRaises(BenchError):
            validate_analysis_result(
                altered_ci,
                self.workspace.bundle,
                self.profile,
                altered_ci["source_seal_digest"],
            )

    def test_ana_05_no_excluded_lane_enters_analysis_or_selection(self) -> None:
        lane_ids = {lane["lane_id"] for campaign in self.analysis["campaigns"] for lane in campaign["lanes"]}
        self.assertEqual(lane_ids, set(LANES))
        excluded = set(EXPECTATIONS["excluded_class_ids"])
        self.assertTrue(lane_ids.isdisjoint(excluded))
        named = {
            rule["lane_id"]
            for rule in self.policy_profile.document["targets"]
            + self.policy_profile.document["guardrails"]
        }
        self.assertTrue(named.issubset(lane_ids))


class VerificationTests(unittest.TestCase):
    """VER-01…VER-03."""

    def test_ver_01_nine_independent_check_ids_are_present(self) -> None:
        from quervant_bench.verification.verify import verify_synthetic_run

        workspace = cached_workspace()
        analysis, policy = analyze_synthetic_run(
            bundle=workspace.bundle,
            run_dir=workspace.run_dir,
            scenario_root=workspace.scenario_root,
            profiles_root=workspace.experiment_root,
            resources_root=workspace.experiment_root,
        )
        assessment = verify_synthetic_run(
            bundle=workspace.bundle,
            run_dir=workspace.run_dir,
            scenario_root=workspace.scenario_root,
            profiles_root=workspace.experiment_root,
            resources_root=workspace.experiment_root,
            analysis_document=analysis,
            policy_document=policy,
        )
        self.assertEqual(assessment.status, "verified-synthetic")
        self.assertEqual(assessment.check_ids, CHECK_IDS)
        self.assertEqual(len(assessment.check_ids), 9)
        self.assertEqual(assessment.source_seal_digest, analysis["source_seal_digest"])

    def test_ver_02_forged_policy_and_ci_are_rejected(self) -> None:
        from quervant_bench.verification.verify import verify_synthetic_run

        workspace = cached_workspace()
        analysis, policy = analyze_synthetic_run(
            bundle=workspace.bundle,
            run_dir=workspace.run_dir,
            scenario_root=workspace.scenario_root,
            profiles_root=workspace.experiment_root,
            resources_root=workspace.experiment_root,
        )
        forged = json.loads(json.dumps(policy))
        forged["decision_status"] = "SELECTED"
        forged["selected_arm_id"] = "lucene"
        with self.assertRaises(BenchError):
            verify_synthetic_run(
                bundle=workspace.bundle,
                run_dir=workspace.run_dir,
                scenario_root=workspace.scenario_root,
                profiles_root=workspace.experiment_root,
                resources_root=workspace.experiment_root,
                analysis_document=analysis,
                policy_document=forged,
            )

    def test_ver_03_committed_verification_is_independently_reverified(self) -> None:
        workspace = cached_workspace()
        self.assertEqual(workspace.documents["verification-assessment.json"]["status"], "verified-synthetic")
        self.assertEqual(
            workspace.documents["verification.json"]["status"], "pass"
        )


class EndToEndTests(unittest.TestCase):
    """E2E-01…E2E-06."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = cached_workspace()

    def test_e2e_01_exact_fifteen_members_and_seven_gates(self) -> None:
        directory = self.workspace.result.output_directory
        names = sorted(path.name for path in directory.iterdir())
        self.assertEqual(names, sorted(MEMBER_NAMES))
        self.assertEqual(len(names), EXPECTATIONS["manifest_members"])
        manifest = self.workspace.documents["manifest.json"]
        validate_manifest(manifest)
        self.assertEqual(
            tuple(record["path"] for record in manifest["members"]), MANIFEST_MEMBERS
        )
        validate_acceptance_summary(
            self.workspace.documents["acceptance-summary.json"]
        )
        gates = {
            self.workspace.documents[name]["gate"]
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
        self.assertEqual(gates, set(GATE_ORDER))
        self.assertEqual(len(gates), EXPECTATIONS["receipt_gates"])
        for name in MEMBER_NAMES:
            document = self.workspace.documents[name]
            if isinstance(document, dict) and "evidence_origin" in document:
                self.assertEqual(document["evidence_origin"], "synthetic", name)
            if isinstance(document, dict) and "qualification_scope" in document:
                self.assertEqual(document["qualification_scope"], "simulated", name)

    def test_e2e_02_admission_is_bound_to_the_cross_engine_ledger(self) -> None:
        admission = self.workspace.documents["admission-index.json"]
        self.assertEqual(
            admission["subject"]["workload_digest"],
            self.workspace.bundle.workload_digest,
        )
        self.assertEqual(
            admission["subject"]["protocol_digest"],
            self.workspace.bundle.protocol_digest,
        )
        self.assertEqual(
            self.workspace.documents["analysis.json"]["source_seal_digest"],
            self.workspace.documents["verification-assessment.json"]["source_seal_digest"],
        )

    def test_e2e_03_missing_seal_and_stale_qa_are_rejected(self) -> None:
        workspace = CrossEngineWorkspace()
        try:
            unsealed_run_id = str(uuid.uuid4())
            scenario = load_synthetic_scenario(
                workspace.scenario_root, bundle=workspace.bundle
            )
            unsealed = execute_synthetic(
                bundle=workspace.bundle,
                scenario=scenario,
                run_id=unsealed_run_id,
                evidence_root=workspace.scenario_root,
                output_base=workspace.run_output_base,
                adapter_factory=synthetic_adapter_factory(workspace.bundle),
                capability_provider=SimulatedCapabilityProvider(),
                readiness_provider=ScenarioReadinessProvider(scenario),
                clock=LogicalClock(),
                faults=FaultPlan(point=FaultPoint.BEFORE_SEAL),
            )
            self.assertEqual(unsealed.status, "stopped")
            arguments = workspace.coordinator_arguments()
            arguments["run_dir"] = (
                workspace.run_output_base / REFERENCE_EXPERIMENT_ID / unsealed_run_id
            )
            with self.assertRaises(BenchError):
                coordinator.qualify_synthetic_run(**arguments)
        finally:
            workspace.close()

    def test_e2e_04_altered_qa_or_receipt_is_rejected(self) -> None:
        temporary, root = copy_workspace(self.workspace.workspace)
        self.addCleanup(temporary.cleanup)
        record = root / "qa" / "source-qa" / "rust-stable.json"
        record.write_bytes(record.read_bytes() + b" ")
        with self.assertRaises(BenchError):
            offline.open_verified_artifacts(root, self.workspace.run_id)

        temporary, root = copy_workspace(self.workspace.workspace)
        self.addCleanup(temporary.cleanup)
        directory = root / "qualified" / REFERENCE_EXPERIMENT_ID / self.workspace.run_id
        documents = {name: read_json(directory / name) for name in MEMBER_NAMES}
        documents["acceptance-summary.json"]["subject"]["run_id"] = (
            "00000000-0000-4000-8000-000000000011"
        )
        rehash_gate_d(documents)
        write_bundle_documents(
            root / "qualified", REFERENCE_EXPERIMENT_ID, self.workspace.run_id, documents
        )
        with self.assertRaises(BenchError):
            offline.open_verified_artifacts(root, self.workspace.run_id)

    def test_e2e_05_output_collision_and_republish_are_refused(self) -> None:
        workspace = self.workspace
        before = snapshot(workspace.qualification_output_base)
        result = coordinator.qualify_synthetic_run(**workspace.coordinator_arguments())
        self.assertEqual(result.disposition, "REUSED_VERIFIED")
        self.assertEqual(snapshot(workspace.qualification_output_base), before)

    def test_e2e_06_postqualification_ledger_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = copy_catalog(Path(temporary) / "catalog")
            workspace = CrossEngineWorkspace(catalog_root=root)
            try:
                ledger_path = (
                    root
                    / REFERENCE_EXPERIMENT_ID
                    / "semantic-comparability.v1.json"
                )
                ledger = read_json(ledger_path)
                ledger["comparable_lane_ids"] = list(reversed(ledger["comparable_lane_ids"]))
                write_canonical(ledger_path, ledger)
                with self.assertRaises(BenchError):
                    workspace.qualify()
            finally:
                workspace.close()


class ReuseTests(unittest.TestCase):
    """REU-01…REU-03."""

    def test_reu_01_verified_reuse_does_not_rederive_or_reverify(self) -> None:
        workspace = cached_workspace()
        calls = {"derive": 0, "verify": 0}
        real_derive = coordinator.analyze_synthetic_run
        real_verify = coordinator.verify_synthetic_run

        def derive(*args, **kwargs):
            calls["derive"] += 1
            return real_derive(*args, **kwargs)

        def verify(*args, **kwargs):
            calls["verify"] += 1
            return real_verify(*args, **kwargs)

        with mock.patch.object(coordinator, "analyze_synthetic_run", side_effect=derive), mock.patch.object(
            coordinator, "verify_synthetic_run", side_effect=verify
        ):
            result = coordinator.qualify_synthetic_run(**workspace.coordinator_arguments())
        self.assertEqual(result.disposition, "REUSED_VERIFIED")
        self.assertEqual(calls, {"derive": 0, "verify": 0})
        self.assertEqual(result.manifest_digest, workspace.result.manifest_digest)

    def test_reu_02_changed_scenario_ledger_or_source_fails_reuse(self) -> None:
        temporary, root = copy_workspace(cached_workspace().workspace)
        self.addCleanup(temporary.cleanup)
        scenario = root / "scenarios" / REFERENCE_EXPERIMENT_ID / cached_workspace().run_id / "synthetic-scenario.v1.json"
        scenario.write_bytes(scenario.read_bytes() + b" ")
        with self.assertRaises(BenchError):
            offline.open_verified_artifacts(root, cached_workspace().run_id)

    def test_reu_03_reuse_requires_matching_anchors(self) -> None:
        temporary, root = copy_workspace(cached_workspace().workspace)
        self.addCleanup(temporary.cleanup)
        anchors = read_json(root / "qualification-anchors.v1.json")
        anchors["source_set_digest"] = "sha256:" + "0" * 64
        write_canonical(root / "qualification-anchors.v1.json", anchors)
        with self.assertRaises(BenchError):
            offline.open_verified_artifacts(root, cached_workspace().run_id)


class ScopeAndSafetyTests(unittest.TestCase):
    """SCOPE-01/02 and SAFE-01…SAFE-05."""

    def test_scope_01_synthetic_labels_never_become_official(self) -> None:
        workspace = cached_workspace()
        documents = workspace.documents
        for name, document in documents.items():
            if isinstance(document, dict):
                self.assertNotEqual(document.get("qualification_scope"), "official", name)
                self.assertNotEqual(document.get("evidence_origin"), "real", name)
        self.assertEqual(documents["attestation.json"]["evidence_origin"], "synthetic")
        self.assertEqual(documents["attestation.json"]["qualification_scope"], "simulated")

    def test_scope_02_coherent_official_relabel_is_rejected(self) -> None:
        temporary, root = copy_workspace(cached_workspace().workspace)
        self.addCleanup(temporary.cleanup)
        directory = root / "qualified" / REFERENCE_EXPERIMENT_ID / cached_workspace().run_id
        documents = {name: read_json(directory / name) for name in MEMBER_NAMES}
        for document in documents.values():
            if isinstance(document, dict) and "qualification_scope" in document:
                document["qualification_scope"] = "official"
        write_bundle_documents(
            root / "qualified",
            REFERENCE_EXPERIMENT_ID,
            cached_workspace().run_id,
            documents,
        )
        with self.assertRaises(BenchError) as raised:
            offline.open_verified_artifacts(root, cached_workspace().run_id)
        self.assertIn(
            raised.exception.code,
            {BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BM_SCOPE_MISMATCH},
        )

    def test_safe_01_new_modules_have_no_engine_or_process_imports(self) -> None:
        forbidden = (
            "subprocess",
            "shutil.which",
            "os.system",
            "os.spawn",
            "Popen",
            "harness.run",
            "benchmarks/pr15d/harness",
        )
        for name in ("cross_engine.py", "cross_engine_contract.py"):
            source = (
                Path(__file__).resolve().parents[1] / "migrations" / name
            ).read_text(encoding="utf-8")
            for needle in forbidden:
                self.assertNotIn(needle, source, f"{name} must not reference {needle}")

    def test_safe_02_offline_verbs_never_launch_a_process(self) -> None:
        workspace = cached_workspace(checked_in_anchors=True)
        before = snapshot(workspace.workspace)
        with mock.patch.dict(
            os.environ, {offline.OFFLINE_WORKSPACE_ENV: str(workspace.workspace)}
        ):
            for verb in ("validate", "analyze", "verify", "accept", "report"):
                document = offline.render_offline_stage_view(verb, workspace.run_id)
                self.assertIsInstance(document, dict)
        self.assertEqual(snapshot(workspace.workspace), before)

    def test_safe_03_run_verb_is_prohibited_before_any_workspace_access(self) -> None:
        from quervant_bench import cli

        with mock.patch.object(
            offline, "dispatch_stage", side_effect=AssertionError("offline")
        ), tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            status = cli.main(
                [
                    "run",
                    "--experiment",
                    REFERENCE_EXPERIMENT_ID,
                    "--protocol",
                    "protocol.yaml",
                    "--out",
                    str(output),
                ]
            )
            self.assertEqual(status, 77)
            self.assertFalse(output.exists())

    def test_safe_04_reference_catalog_declares_no_real_evidence(self) -> None:
        for name in sorted(p.name for p in CATALOG.iterdir()):
            payload = (CATALOG / name).read_text(encoding="utf-8")
            lowered = payload.lower()
            for needle in (
                '"evidence_origin":"real"',
                '"qualification_scope":"official"',
                "measured engine",
            ):
                self.assertNotIn(needle, lowered, f"{name} must not claim {needle}")

    def test_safe_05_legacy_matrix_records_blocked_historical_gate(self) -> None:
        self.assertEqual(
            LEGACY_MATRIX["historical_status"],
            {
                "HISTORICAL_NUMERIC_PARITY": "NOT_EXECUTED",
                "HISTORICAL_DECISION_PARITY": "NOT_EXECUTED",
                "HISTORICAL_ACCEPTANCE_GATE": "BLOCKED",
                "LEGACY_PATHS_RETIRED": "NO",
            },
        )


class CatalogDriftTests(unittest.TestCase):
    """CFX-06…CFX-08, CFX-15, CFX-16: catalog identity across the producer path."""

    def _drift_after_bm06(self, member: str, mutate) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = copy_catalog(Path(temporary) / "catalog")
            workspace = CrossEngineWorkspace(catalog_root=catalog, qualify=False)
            real_qualify = cross_engine_module.qualify_synthetic_run
            try:
                def drifting(**kwargs: Any):
                    result = real_qualify(**kwargs)
                    editor = CatalogEditor(catalog)
                    mutate(editor)
                    editor.write()
                    return result

                with mock.patch.object(
                    cross_engine_module, "qualify_synthetic_run", side_effect=drifting
                ):
                    with self.assertRaises(BenchError) as raised:
                        workspace.qualify()
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(
                    raised.exception.field_path, f"catalog.{member}"
                )
                # (b) the committed synthetic bundle exists and is untouched.
                directory = (
                    workspace.qualification_output_base
                    / REFERENCE_EXPERIMENT_ID
                    / workspace.run_id
                )
                self.assertTrue(directory.is_dir())
                first = snapshot(directory)
                self.assertEqual(len(documents_of(directory)), 15)
                # (c)/(d) no repair/retry and no successful stale reuse.
                with self.assertRaises(BenchError) as repeated:
                    workspace.qualify()
                self.assertEqual(repeated.exception.code, BM_IDENTITY_INVALID)
                self.assertEqual(snapshot(directory), first)
            finally:
                workspace.close()

    def test_cfx_06_real_simulated_qualification(self) -> None:
        workspace = cached_workspace()
        self.assertEqual(workspace.result.disposition, "SIMULATED_QUALIFIED")
        self.assertEqual(len(documents_of(workspace.result.output_directory)), 15)
        policy = workspace.documents["policy.json"]
        self.assertEqual(policy["decision_status"], "INCONCLUSIVE")
        self.assertIsNone(policy["selected_arm_id"])
        self.assertEqual(policy["evidence_origin"], "synthetic")
        self.assertEqual(policy["qualification_scope"], "simulated")

    def test_cfx_07_post_publication_protocol_drift_is_rejected(self) -> None:
        def mutate(editor: CatalogEditor) -> None:
            editor.documents["protocol.yaml"]["schedule"]["seed"] = 43

        self._drift_after_bm06("protocol.yaml", mutate)

    def test_cfx_08_post_publication_resource_drift_is_rejected(self) -> None:
        def mutate(editor: CatalogEditor) -> None:
            editor.documents["resource-observations.v1.json"]["records"][0][
                "value_bytes"
            ] = 1048577

        self._drift_after_bm06("resource-observations.v1.json", mutate)

    def test_cfx_15_excluded_lanes_never_yield_a_numeric_projection(self) -> None:
        import dataclasses

        from quervant_bench.migrations.cross_engine_contract import (
            validate_keyword_reply_projection,
        )

        bundle = load_cross_engine_reference(reference_catalog_root(REPO_ROOT))
        lane = next(
            item for item in bundle.workload.lanes
            if item.lane_id == "n010000-medium-k010-warm"
        )
        cold = dataclasses.replace(lane, cache_regime="process-cold")
        row = {
            "lane_id": lane.lane_id,
            "corpus_size": 10000,
            "selectivity_class": "medium",
            "field": "group",
            "term": "medium",
            "top_k": 10,
            "total_hits": 1250,
            "doc_ids": ["d%08d" % index for index in range(0, 80, 8)],
        }
        reply = {
            "schema": "pr15d-adapter-v1",
            "engine": "quervant",
            "request_id": "query-" + lane.lane_id,
            "status": "ok",
            "total_hits": 1250,
            "doc_ids": list(row["doc_ids"]),
        }
        with self.assertRaises(BenchError) as raised:
            validate_keyword_reply_projection(cold, "quervant", reply, row)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

        workspace = cached_workspace()
        for document in (
            workspace.documents["analysis.json"],
            workspace.documents["policy.json"],
        ):
            serialized = json.dumps(document)
            for needle in ("scored-bm25", "process-cold", "index-throughput"):
                self.assertNotIn(needle, serialized)

    def test_cfx_16_no_successful_stale_reuse_after_drift(self) -> None:
        def mutate(editor: CatalogEditor) -> None:
            editor.documents["oracle-golden.v1.json"]["rows"][0]["term"] = "neverx"

        self._drift_after_bm06("oracle-golden.v1.json", mutate)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

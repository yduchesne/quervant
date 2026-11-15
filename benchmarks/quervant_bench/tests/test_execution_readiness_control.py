"""READY-01…READY-06 and CTRL-01…CTRL-04: fresh readiness and synthetic A/A."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from quervant_bench.config.codec import canonical_document_bytes
from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BenchError,
)
from quervant_bench.execution import (
    LogicalClock,
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    execute_synthetic,
    load_synthetic_scenario,
    synthetic_adapter_factory,
)
from quervant_bench.execution.synthetic import SyntheticAdapter
from quervant_bench.host.readiness import ReadinessObservation

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"
EXPERIMENT_ID = "synthetic-execution-smoke"


def load_bundle():
    return load_experiment_bundle(EXPERIMENT_ID, EXPERIMENTS)


def protocol_variant(bundle, **campaigns):
    document = json.loads(json.dumps(dict(bundle.protocol_document)))
    document["campaigns"].update(campaigns)
    return replace(bundle, protocol_document=document)


class ReadinessTestBase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "out"
        self.output.mkdir()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        shutil.copy(FIXTURES / SCENARIO_NAME, self.evidence / SCENARIO_NAME)
        self.bundle = load_bundle()
        self.scenario = load_synthetic_scenario(self.evidence, bundle=self.bundle)

    def run_default(self, **overrides):
        parameters = {
            "bundle": self.bundle,
            "scenario": self.scenario,
            "run_id": str(uuid.uuid4()),
            "evidence_root": self.evidence,
            "output_base": self.output,
            "adapter_factory": synthetic_adapter_factory(self.bundle),
            "capability_provider": SimulatedCapabilityProvider(),
            "readiness_provider": ScenarioReadinessProvider(self.scenario),
            "clock": LogicalClock(),
        }
        parameters.update(overrides)
        return execute_synthetic(**parameters)

    def files(self, run_dir: Path, prefix: str = "") -> list[str]:
        return sorted(
            path.relative_to(run_dir).as_posix()
            for path in run_dir.rglob("*")
            if path.is_file() and path.relative_to(run_dir).as_posix().startswith(prefix)
        )


class ReadinessTests(ReadinessTestBase):
    def test_ready_01_each_campaign_consumes_its_own_fresh_batch(self) -> None:
        provider = ScenarioReadinessProvider(self.scenario)
        result = self.run_default(readiness_provider=provider)
        self.assertEqual(result.status, "sealed")
        self.assertEqual(
            provider.calls,
            [("control", 0), ("treatment", 0), ("treatment", 1)],
        )
        observation_count = 0
        for path in sorted((result.run_dir / "readiness").glob("*.json")):
            observation_count += len(json.loads(path.read_bytes())["observations"])
        self.assertEqual(observation_count, 6)

    def test_ready_02_blocked_control_readiness_stops_before_any_adapter_call(self) -> None:
        from quervant_bench.execution import FaultPlan, FaultPoint

        counts: dict[str, int] = {}

        def factory(assignment, slot, scenario):
            counts["factory"] = counts.get("factory", 0) + 1
            return synthetic_adapter_factory(self.bundle)(assignment, slot, scenario)

        result = self.run_default(
            adapter_factory=factory,
            faults=FaultPlan(point=FaultPoint.READINESS_BLOCKED),
        )
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "host-not-ready")
        self.assertEqual(counts, {})
        readiness = json.loads(
            (result.run_dir / "readiness" / "control-0000.json").read_bytes()
        )
        self.assertEqual(readiness["diagnostic"]["status"], "blocked")
        self.assertTrue(readiness["diagnostic"]["reasons"])
        self.assertEqual(self.files(result.run_dir, "readiness/treatment"), [])
        self.assertEqual(self.files(result.run_dir, "slots/"), [])
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_ready_03_blocked_treatment_readiness_preserves_the_control(self) -> None:
        class BlockingTreatmentZero(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                if (campaign_kind, campaign_index) == ("treatment", 0):
                    return (ReadinessObservation(5, 900, 500),)
                return super().next_observations(campaign_kind, campaign_index)

        result = self.run_default(
            readiness_provider=BlockingTreatmentZero(self.scenario)
        )
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "host-not-ready")
        report = json.loads((result.run_dir / "controls" / "control-0000.json").read_bytes())
        self.assertEqual(report["checked_pairs"], 8)
        self.assertTrue(self.files(result.run_dir, "slots/control-0000"))
        self.assertEqual(self.files(result.run_dir, "slots/treatment"), [])
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_ready_04_blocked_second_treatment_keeps_the_first_complete(self) -> None:
        class BlockingTreatmentOne(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                if (campaign_kind, campaign_index) == ("treatment", 1):
                    return (ReadinessObservation(5, 900, 500),)
                return super().next_observations(campaign_kind, campaign_index)

        result = self.run_default(
            readiness_provider=BlockingTreatmentOne(self.scenario)
        )
        self.assertEqual(result.status, "stopped")
        first = self.files(result.run_dir, "slots/treatment-0000")
        self.assertEqual(sum(name.endswith("complete.json") for name in first), 8)
        self.assertEqual(self.files(result.run_dir, "slots/treatment-0001"), [])
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_ready_05_unsupported_simulated_capabilities_block_before_slots(self) -> None:
        result = self.run_default(
            capability_provider=SimulatedCapabilityProvider(include_topology=False)
        )
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "host-not-ready")
        self.assertEqual(self.files(result.run_dir, "readiness/"), [])
        self.assertEqual(self.files(result.run_dir, "slots/"), [])

        unsupported = self.run_default(
            capability_provider=SimulatedCapabilityProvider(system="Windows")
        )
        self.assertEqual(unsupported.status, "stopped")
        self.assertEqual(unsupported.reason, "host-not-ready")

    def test_ready_06_reused_missing_or_duplicated_batches_are_rejected(self) -> None:
        class RepeatedObservation(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                observations = super().next_observations(campaign_kind, campaign_index)
                if (campaign_kind, campaign_index) == ("treatment", 1):
                    return (observations[0], observations[0])
                return observations

        class MissingObservation(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                observations = super().next_observations(campaign_kind, campaign_index)
                if (campaign_kind, campaign_index) == ("treatment", 0):
                    return observations[:1]
                return observations

        class CachingProvider(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                if (campaign_kind, campaign_index) == ("control", 0):
                    return super().next_observations(campaign_kind, campaign_index)
                if (campaign_kind, campaign_index) == ("treatment", 0):
                    return super().next_observations(campaign_kind, campaign_index)
                raise BenchError(
                    BM_IDENTITY_INVALID,
                    "the provider refuses to serve a previously consumed batch",
                    field_path="readiness",
                )

        for provider_class, later_only in (
            (RepeatedObservation, True),
            (MissingObservation, False),
            (CachingProvider, True),
        ):
            with self.subTest(provider=provider_class.__name__):
                result = self.run_default(
                    readiness_provider=provider_class(self.scenario)
                )
                self.assertEqual(result.status, "stopped")
                self.assertEqual(result.reason, "host-not-ready")
                self.assertEqual(self.files(result.run_dir, "slots/treatment-0001"), [])
                if not later_only:
                    self.assertEqual(self.files(result.run_dir, "slots/treatment-0000"), [])
                self.assertFalse((result.run_dir / "seal.json").exists())


class ControlTests(ReadinessTestBase):
    def test_ctrl_01_one_complete_control_produces_eight_paired_checks(self) -> None:
        result = self.run_default()
        self.assertEqual(result.status, "sealed")
        reports = self.files(result.run_dir, "controls/")
        self.assertEqual(reports, ["controls/control-0000.json"])
        report = json.loads((result.run_dir / reports[0]).read_bytes())
        self.assertEqual(report["checked_pairs"], 8)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["control_contract_id"], "synthetic-exact-equality")
        self.assertEqual(report["source_arm_id"], "baseline")
        self.assertEqual(report["lane_ids"], ["rare-query", "common-query"])

    def test_ctrl_02_mismatched_replica_stops_before_any_treatment(self) -> None:
        bucket = {"perturbed": 0}

        class PerturbingControlRight(SyntheticAdapter):
            def measure(self, adapter_context, prepared, lane):
                result = super().measure(adapter_context, prepared, lane)
                assignment = self.identity_fields
                if (
                    assignment.campaign_kind == "control"
                    and assignment.display_arm_id == "control-right"
                    and assignment.slot.block == 1
                    and lane.lane_id == "rare-query"
                ):
                    bucket["perturbed"] += 1
                    samples = list(result.samples or ())
                    samples[0] = samples[0] + 1
                    return replace(result, samples=tuple(samples))
                return result

        counts: dict[str, int] = {}

        def factory(assignment, slot, scenario):
            counts["factory"] = counts.get("factory", 0) + 1
            return PerturbingControlRight(self.bundle, assignment, slot, scenario)

        result = self.run_default(adapter_factory=factory)
        self.assertEqual(bucket["perturbed"], 1)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "control-mismatch")
        self.assertEqual(self.files(result.run_dir, "slots/treatment"), [])
        self.assertFalse((result.run_dir / "controls" / "control-0000.json").exists())
        self.assertFalse((result.run_dir / "seal.json").exists())
        self.assertEqual(counts["factory"], 8)

    def test_ctrl_03_zero_required_controls_is_explicitly_not_required(self) -> None:
        bundle = protocol_variant(self.bundle, required_controls=0)
        document = json.loads((FIXTURES / SCENARIO_NAME).read_bytes())
        document["readiness"] = [
            entry for entry in document["readiness"] if entry["campaign_kind"] != "control"
        ]
        (self.evidence / SCENARIO_NAME).write_bytes(canonical_document_bytes(document))
        scenario = load_synthetic_scenario(self.evidence, bundle=bundle)

        provider = ScenarioReadinessProvider(scenario)
        result = self.run_default(
            bundle=bundle,
            scenario=scenario,
            adapter_factory=synthetic_adapter_factory(bundle),
            readiness_provider=provider,
        )
        self.assertEqual(result.status, "sealed")
        self.assertEqual(provider.calls, [("treatment", 0), ("treatment", 1)])
        control_schedule = json.loads(
            (result.run_dir / "control-schedule.json").read_bytes()
        )
        self.assertEqual(control_schedule["status"], "not-required")
        self.assertEqual(control_schedule["campaign_count"], 0)
        self.assertEqual(control_schedule["slots"], [])
        self.assertEqual(self.files(result.run_dir, "controls/"), [])
        slot_files = self.files(result.run_dir, "slots/")
        self.assertTrue(slot_files)
        self.assertTrue(all("/treatment-" in name for name in slot_files))

    def test_ctrl_04_unknown_control_contract_fails_before_any_output(self) -> None:
        bundle = protocol_variant(
            self.bundle, control_contract_id="synthetic-other-control"
        )
        with self.assertRaises(BenchError) as caught:
            self.run_default(bundle=bundle)
        self.assertEqual(caught.exception.code, BM_NOT_IMPLEMENTED)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_ctrl_04_odd_blocks_with_required_controls_is_rejected(self) -> None:
        from quervant_bench.config.contracts import ArmMultiplicity
        from quervant_bench.protocol.controls import build_control_schedule

        bundle = load_bundle()
        names = ("alpha", "beta", "gamma")
        arms = tuple(replace(bundle.experiment.arms[0], arm_id=name) for name in names)
        multiplicity = tuple(
            ArmMultiplicity(arm_id=name, slots_per_block=1) for name in names
        )
        schedule = replace(bundle.protocol.schedule, blocks=3, slots_per_block=3)
        odd = replace(
            bundle,
            experiment=replace(bundle.experiment, arms=arms),
            protocol=replace(
                bundle.protocol,
                arm_multiplicity=multiplicity,
                schedule=schedule,
            ),
        )
        with self.assertRaises(BenchError) as caught:
            build_control_schedule(odd, control_source_arm_id="alpha")
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

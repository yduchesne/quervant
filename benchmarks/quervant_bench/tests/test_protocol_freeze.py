"""FREEZE-01…FREEZE-06: freeze binding, ordering and mutation refusal."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from quervant_bench.config.codec import (
    canonical_document_bytes,
    content_digest,
    load_document,
)
from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCOPE_MISMATCH,
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
from quervant_bench.execution.scenario import validate_scenario_document
from quervant_bench.protocol.controls import build_control_schedule
from quervant_bench.protocol.freeze import (
    FREEZE_KEYS,
    build_freeze_document,
    validate_freeze_document,
)
from quervant_bench.protocol.schedule import compile_schedule

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"
EXPERIMENT_ID = "synthetic-execution-smoke"


def load_bundle():
    return load_experiment_bundle(EXPERIMENT_ID, EXPERIMENTS)


class FreezeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "out"
        self.output.mkdir()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        shutil.copy(
            FIXTURES / SCENARIO_NAME, self.evidence / SCENARIO_NAME
        )
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

    def scenario_path(self) -> Path:
        return self.evidence / SCENARIO_NAME


class FreezeBindingTests(FreezeTestBase):
    def test_freeze_01_every_binding_is_recomputable_from_source_documents(self) -> None:
        schedule = compile_schedule(self.bundle)
        control = build_control_schedule(
            self.bundle,
            control_source_arm_id=self.scenario.control_source_arm_id,
        )
        document, digest = build_freeze_document(
            bundle=self.bundle,
            run_id=str(uuid.uuid4()),
            schedule=schedule,
            control_schedule=control,
            scenario_digest=self.scenario.scenario_digest,
        )
        experiment = load_document(EXPERIMENTS / EXPERIMENT_ID / "experiment.yaml")
        workload = load_document(EXPERIMENTS / EXPERIMENT_ID / "workloads.yaml")
        protocol = load_document(EXPERIMENTS / EXPERIMENT_ID / "protocol.yaml")
        adapter = load_document(EXPERIMENTS / EXPERIMENT_ID / "adapter.yaml")

        self.assertEqual(set(document), FREEZE_KEYS)
        self.assertEqual(document["experiment_digest"], content_digest(experiment))
        self.assertEqual(document["workload_digest"], content_digest(workload))
        self.assertEqual(document["protocol_digest"], content_digest(protocol))
        self.assertEqual(document["adapter_digest"], content_digest(adapter))
        self.assertEqual(document["schedule_digest"], schedule.schedule_digest)
        self.assertEqual(document["control_schedule_digest"], control.digest)
        self.assertEqual(document["scenario_digest"], self.scenario.scenario_digest)
        self.assertEqual(document["policy_digest"], experiment["policy"]["policy_digest"])
        self.assertEqual(document["analysis_digest"], experiment["analysis"]["analysis_digest"])
        self.assertEqual(document["arm_ids"], ["baseline", "candidate"])
        self.assertEqual(document["lane_ids"], ["common-query", "rare-query"])
        self.assertEqual(document["required_controls"], 1)
        self.assertEqual(document["required_treatments"], 2)
        self.assertEqual(document["evidence_origin"], "synthetic")
        self.assertEqual(document["qualification_scope"], "simulated")
        self.assertEqual(
            document["source_binding_digest"],
            content_digest(
                {
                    "kind": "synthetic-source-binding",
                    "scenario_digest": self.scenario.scenario_digest,
                }
            ),
        )
        self.assertEqual(content_digest(document), digest)
        self.assertEqual(validate_freeze_document(document).freeze_digest, digest)
        for value in document.values():
            if isinstance(value, str):
                self.assertFalse(value.startswith("/"), value)

    def test_freeze_02_scenario_mutation_after_freeze_never_seals(self) -> None:
        original = self.scenario_path().read_bytes()
        document = json.loads(original)
        document["samples"][0]["values"][0] = document["samples"][0]["values"][0] + 1
        mutated_bytes = canonical_document_bytes(document)

        class MutatingProvider(ScenarioReadinessProvider):
            def __init__(self, scenario, path):
                super().__init__(scenario)
                self._path = path
                self._mutated = False

            def next_observations(self, campaign_kind, campaign_index):
                observations = super().next_observations(campaign_kind, campaign_index)
                if not self._mutated:
                    self._mutated = True
                    self._path.write_bytes(mutated_bytes)
                return observations

        provider = MutatingProvider(self.scenario, self.scenario_path())
        result = self.run_default(readiness_provider=provider)

        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "input-mutated")
        self.assertFalse((result.run_dir / "seal.json").exists())
        self.assertEqual(self.scenario_path().read_bytes(), mutated_bytes)

    def test_freeze_03_protocol_or_build_identity_mutation_is_detected(self) -> None:
        class MutatingProtocolProvider(ScenarioReadinessProvider):
            mutated = False

            def __init__(self, scenario, bundle):
                super().__init__(scenario)
                self._bundle = bundle

            def next_observations(self, campaign_kind, campaign_index):
                observations = super().next_observations(campaign_kind, campaign_index)
                if not MutatingProtocolProvider.mutated:
                    MutatingProtocolProvider.mutated = True
                    self._bundle.protocol_document["schedule"]["seed"] = 43
                return observations

        MutatingProtocolProvider.mutated = False
        result = self.run_default(
            readiness_provider=MutatingProtocolProvider(self.scenario, self.bundle)
        )
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "freeze-mismatch")
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_freeze_04_real_or_official_markers_are_refused(self) -> None:
        document = json.loads(self.scenario_path().read_bytes())
        document["qualification_scope"] = "official"
        with self.assertRaises(BenchError) as caught:
            validate_scenario_document(document, bundle=self.bundle)
        self.assertEqual(caught.exception.code, BM_SCOPE_MISMATCH)

        schedule = compile_schedule(self.bundle)
        control = build_control_schedule(
            self.bundle, control_source_arm_id=self.scenario.control_source_arm_id
        )
        freeze, _ = build_freeze_document(
            bundle=self.bundle,
            run_id=str(uuid.uuid4()),
            schedule=schedule,
            control_schedule=control,
            scenario_digest=self.scenario.scenario_digest,
        )
        forged = dict(freeze)
        forged["evidence_origin"] = "real"
        forged["qualification_scope"] = "official"
        with self.assertRaises(BenchError) as caught:
            validate_freeze_document(forged)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)


class FreezeOrderingTests(FreezeTestBase):
    def test_freeze_05_failed_freeze_publication_touches_nothing_else(self) -> None:
        calls = {"prepare": 0, "readiness": 0, "capability": 0}

        class CountingReadiness(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                calls["readiness"] += 1
                return super().next_observations(campaign_kind, campaign_index)

        class CountingCapability(SimulatedCapabilityProvider):
            def platform_record(self):
                calls["capability"] += 1
                return super().platform_record()

        def factory(assignment, slot, scenario):
            calls["prepare"] += 1
            return synthetic_adapter_factory(self.bundle)(assignment, slot, scenario)

        from quervant_bench.execution import FaultPlan, FaultPoint

        result = self.run_default(
            readiness_provider=CountingReadiness(self.scenario),
            capability_provider=CountingCapability(),
            adapter_factory=factory,
            faults=FaultPlan(point=FaultPoint.BEFORE_FREEZE_PUBLISH),
        )
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "freeze-missing")
        self.assertEqual(calls, {"prepare": 0, "readiness": 0, "capability": 0})
        self.assertFalse((result.run_dir / "freeze.json").exists())
        self.assertFalse((result.run_dir / "seal.json").exists())
        self.assertEqual(
            sorted(
                path.relative_to(result.run_dir).as_posix()
                for path in result.run_dir.rglob("*")
                if path.is_file()
            ),
            ["events/00000001.json", "events/00000002.json"],
        )

    def test_freeze_06_freeze_is_visible_before_any_readiness_or_adapter_call(self) -> None:
        snapshots: dict[str, tuple[str, ...]] = {}

        def inventory(base: Path) -> tuple[str, ...]:
            return tuple(
                sorted(
                    path.relative_to(base).as_posix()
                    for path in base.rglob("*")
                    if path.is_file()
                )
            )

        output = self.output

        class SnapshotCapability(SimulatedCapabilityProvider):
            def platform_record(self):
                snapshots["capability"] = inventory(output)
                return super().platform_record()

        class SnapshotReadiness(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                snapshots.setdefault(
                    "readiness",
                    tuple(
                        sorted(
                            path.relative_to(output)
                            .as_posix()
                            for path in output.rglob("*")
                            if path.is_file()
                        )
                    ),
                )
                return super().next_observations(campaign_kind, campaign_index)

        bundle = self.bundle

        def factory(assignment, slot, scenario):
            snapshots.setdefault(
                "adapter",
                tuple(
                    sorted(
                        path.relative_to(output).as_posix()
                        for path in output.rglob("*")
                        if path.is_file()
                    )
                ),
            )
            return synthetic_adapter_factory(bundle)(assignment, slot, scenario)

        result = self.run_default(
            capability_provider=SnapshotCapability(),
            readiness_provider=SnapshotReadiness(self.scenario),
            adapter_factory=factory,
        )
        self.assertEqual(result.status, "sealed")
        for label in ("capability", "readiness", "adapter"):
            self.assertIn(f"{EXPERIMENT_ID}/{result.run_id}/freeze.json", snapshots[label])
        self.assertFalse(
            any("slots/" in entry for entry in snapshots["readiness"]),
            "no slot may run before readiness",
        )


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

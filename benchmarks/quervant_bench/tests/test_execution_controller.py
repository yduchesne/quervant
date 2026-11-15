"""FLOW-01…FLOW-03 and STATE-01…STATE-04: controller accounting and state machine."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BenchError
from quervant_bench.execution import (
    FaultPlan,
    FaultPoint,
    LogicalClock,
    RunState,
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    execute_synthetic,
    load_synthetic_scenario,
    synthetic_adapter_factory,
)
from quervant_bench.execution.contracts import check_transition
from quervant_bench.execution.recorder import event_relative_path
from quervant_bench.execution.synthetic import SyntheticAdapter

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"
GOLDEN = json.loads(
    (FIXTURES / "golden-structural-summary.v1.json").read_text(encoding="utf-8")
)


def load_bundle():
    return load_experiment_bundle("synthetic-execution-smoke", EXPERIMENTS)


class ControllerTestBase(unittest.TestCase):
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

    def instrumented_factory(self, counts, seen):
        bundle = self.bundle

        def factory(assignment, slot, scenario):
            seen.append((assignment.campaign_kind, assignment.display_arm_id))
            adapter = SyntheticAdapter(bundle, assignment, slot, scenario)
            for name in ("prepare", "check_oracle", "warmup", "measure", "cleanup"):
                bound = getattr(adapter, name)

                def wrapper(*args, _bound=bound, _name=name, **kwargs):
                    counts[_name] = counts.get(_name, 0) + 1
                    return _bound(*args, **kwargs)

                setattr(adapter, name, wrapper)
            return adapter

        return factory

    def documents(self, run_dir: Path) -> list[tuple[str, object]]:
        loaded = []
        for path in sorted(run_dir.rglob("*.json")):
            loaded.append(
                (path.relative_to(run_dir).as_posix(), json.loads(path.read_bytes()))
            )
        return loaded


class AccountingTests(ControllerTestBase):
    def test_flow_01_full_fixture_matches_the_hand_constructed_counts(self) -> None:
        counts: dict[str, int] = {}
        seen: list[tuple[str, str]] = []
        result = self.run_default(adapter_factory=self.instrumented_factory(counts, seen))
        self.assertEqual(result.status, "sealed")
        self.assertIsNotNone(result.seal_digest)

        files = [
            path.relative_to(result.run_dir).as_posix()
            for path in result.run_dir.rglob("*")
            if path.is_file()
        ]
        self.assertEqual(sum(name.endswith("complete.json") for name in files), GOLDEN["slots_total"])
        lane_files = [
            name for name in files if "/slot-" in name and not name.endswith("complete.json")
        ]
        self.assertEqual(len(lane_files), GOLDEN["lane_envelopes"])
        samples = sum(
            len(json.loads((result.run_dir / name).read_bytes())["samples"])
            for name in lane_files
        )
        self.assertEqual(samples, GOLDEN["synthetic_samples"])

        self.assertEqual(counts["prepare"], GOLDEN["prepare_invocations"])
        self.assertEqual(counts["check_oracle"], GOLDEN["oracle_invocations"])
        self.assertEqual(counts["warmup"], GOLDEN["warmup_invocations"])
        self.assertEqual(counts["measure"], GOLDEN["lane_envelopes"])
        self.assertEqual(counts["cleanup"], GOLDEN["cleanup_invocations"])

        control_slots = sum(1 for kind, _ in seen if kind == "control")
        treatment_slots = sum(1 for kind, _ in seen if kind == "treatment")
        self.assertEqual(control_slots, GOLDEN["control_slots"])
        self.assertEqual(treatment_slots, GOLDEN["treatment_slots"])

        observations = 0
        for name, document in self.documents(result.run_dir):
            if name.startswith("readiness/"):
                observations += len(document["observations"])
        self.assertEqual(observations, GOLDEN["readiness_observations"])

        seal = json.loads((result.run_dir / "seal.json").read_bytes())
        self.assertEqual(seal["controls_completed"], GOLDEN["control_campaigns"])
        self.assertEqual(seal["treatments_completed"], GOLDEN["treatment_campaigns"])
        self.assertEqual(seal["slots_completed"], GOLDEN["slots_total"])
        self.assertEqual(seal["lane_envelopes"], GOLDEN["lane_envelopes"])
        self.assertEqual(seal["synthetic_samples"], GOLDEN["synthetic_samples"])
        report = json.loads((result.run_dir / "controls" / "control-0000.json").read_bytes())
        self.assertEqual(report["checked_pairs"], GOLDEN["control_checked_pairs"])

    def test_flow_02_one_adapter_path_serves_control_and_treatment(self) -> None:
        counts: dict[str, int] = {}
        seen: list[tuple[str, str]] = []
        result = self.run_default(adapter_factory=self.instrumented_factory(counts, seen))
        self.assertEqual(result.status, "sealed")
        kinds = {kind for kind, _ in seen}
        self.assertEqual(kinds, {"control", "treatment"})
        displays = {display for kind, display in seen if kind == "control"}
        self.assertEqual(displays, {"control-left", "control-right"})
        slot_directories = {
            name.split("/")[1]
            for name in (
                path.relative_to(result.run_dir).as_posix()
                for path in result.run_dir.rglob("*")
                if path.is_file()
            )
            if name.startswith("slots/")
        }
        self.assertEqual(
            slot_directories, {"control-0000", "treatment-0000", "treatment-0001"}
        )

    def test_flow_03_no_output_claims_a_performance_decision(self) -> None:
        result = self.run_default()
        self.assertEqual(result.status, "sealed")
        forbidden_keys = {
            "analysis",
            "policy-verdict",
            "policy_verdict",
            "attestation",
            "official",
            "winner",
            "p_value",
            "confidence_interval",
            "gate",
            "receipt",
            "recommendation",
        }
        for name, document in self.documents(result.run_dir):
            stack = [document]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    self.assertFalse(
                        set(value) & forbidden_keys,
                        f"{name} contains a decision field: {set(value) & forbidden_keys}",
                    )
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
                elif isinstance(value, str):
                    lowered = value.lower()
                    self.assertNotIn("gate-a", lowered, name)
                    self.assertNotIn("official", lowered, name)
                    self.assertNotIn("winner", lowered, name)
        seal = json.loads((result.run_dir / "seal.json").read_bytes())
        self.assertEqual(seal["status"], "sealed-structural")


class StateMachineTests(ControllerTestBase):
    def test_state_01_normal_transition_series_is_exact(self) -> None:
        result = self.run_default()
        self.assertEqual(result.status, "sealed")
        events = []
        sequence = 1
        while True:
            path = result.run_dir / event_relative_path(sequence)
            if not path.exists():
                break
            events.append(json.loads(path.read_bytes()))
            sequence += 1
        observed = [(event["from_state"], event["to_state"], event["reason"]) for event in events]
        expected = [
            ("none", "planned", "new-run"),
            ("planned", "frozen", "freeze-published"),
            ("frozen", "ready", "readiness-clear"),
            ("ready", "acquiring", "slot-acquiring"),
            ("acquiring", "ready", "readiness-clear"),
            ("ready", "acquiring", "slot-acquiring"),
            ("acquiring", "ready", "readiness-clear"),
            ("ready", "acquiring", "slot-acquiring"),
            ("acquiring", "completed", "campaigns-complete"),
        ]
        self.assertEqual(observed, expected)
        self.assertEqual(len(events), GOLDEN["state_events"])
        self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
        self.assertTrue((result.run_dir / "seal.json").exists())

    def test_state_02_unknown_transitions_are_rejected(self) -> None:
        with self.assertRaises(BenchError) as caught:
            check_transition(RunState.PLANNED, RunState.ACQUIRING, "slot-acquiring")
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        with self.assertRaises(BenchError):
            check_transition(RunState.STOPPED, RunState.READY, "readiness-clear")
        with self.assertRaises(BenchError):
            check_transition(RunState.ACQUIRING, RunState.COMPLETED, "readiness-clear")
        with self.assertRaises(BenchError):
            check_transition(RunState.PLANNED, RunState.SEALED, "sealed")
        with self.assertRaises(BenchError):
            check_transition(RunState.PLANNED, RunState.STOPPED, "not-a-stop-reason")

    def test_state_03_first_slot_failure_is_never_retried(self) -> None:
        result = self.run_default(faults=FaultPlan(point=FaultPoint.ORACLE_FAIL))
        self.assertEqual(result.status, "stopped")
        events = sorted(
            (result.run_dir / "events").glob("*.json")
        )
        last = json.loads(events[-1].read_bytes())
        self.assertEqual(last["to_state"], "stopped")
        self.assertEqual(last["reason"], "oracle-failed")
        # The suite-level invariant: the run stopped at the first injected fault and
        # no replacement slot or campaign was attempted.
        lane_files = [
            path
            for path in result.run_dir.rglob("*.json")
            if path.parent.name.startswith("slot-")
        ]
        self.assertEqual(lane_files, [])

    def test_state_04_a_stopped_run_is_never_reused(self) -> None:
        stopped = self.run_default(faults=FaultPlan(point=FaultPoint.BEFORE_SEAL))
        self.assertEqual(stopped.status, "stopped")
        self.assertEqual(stopped.reason, "crash-interrupted")
        before = {
            path.relative_to(stopped.run_dir).as_posix(): path.read_bytes()
            for path in stopped.run_dir.rglob("*")
            if path.is_file()
        }
        self.assertFalse((stopped.run_dir / "seal.json").exists())

        with self.assertRaises(BenchError):
            execute_synthetic(
                bundle=self.bundle,
                scenario=self.scenario,
                run_id=stopped.run_id,
                evidence_root=self.evidence,
                output_base=self.output,
                adapter_factory=synthetic_adapter_factory(self.bundle),
                capability_provider=SimulatedCapabilityProvider(),
                readiness_provider=ScenarioReadinessProvider(self.scenario),
                clock=LogicalClock(),
            )
        after = {
            path.relative_to(stopped.run_dir).as_posix(): path.read_bytes()
            for path in stopped.run_dir.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)

        replacement = self.run_default()
        self.assertEqual(replacement.status, "sealed")
        self.assertNotEqual(replacement.run_id, stopped.run_id)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

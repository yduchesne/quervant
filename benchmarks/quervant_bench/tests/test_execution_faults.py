"""FAULT-01…FAULT-05: injected faults, interruption and hard termination."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path

from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_PUBLICATION_CONFLICT,
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
from quervant_bench.execution.synthetic import SyntheticAdapter

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"
EXPERIMENT_ID = "synthetic-execution-smoke"


def load_bundle():
    return load_experiment_bundle(EXPERIMENT_ID, EXPERIMENTS)


class FaultTestBase(unittest.TestCase):
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


class FaultTests(FaultTestBase):
    def test_fault_01_freeze_publication_failure_prevents_all_acquisition(self) -> None:
        calls = {"factory": 0, "readiness": 0, "capability": 0}

        class CountingReadiness(ScenarioReadinessProvider):
            def next_observations(self, campaign_kind, campaign_index):
                calls["readiness"] += 1
                return super().next_observations(campaign_kind, campaign_index)

        class CountingCapability(SimulatedCapabilityProvider):
            def platform_record(self):
                calls["capability"] += 1
                return super().platform_record()

        def factory(assignment, slot, scenario):
            calls["factory"] += 1
            return synthetic_adapter_factory(self.bundle)(assignment, slot, scenario)

        result = self.run_default(
            readiness_provider=CountingReadiness(self.scenario),
            capability_provider=CountingCapability(),
            adapter_factory=factory,
            faults=FaultPlan(point=FaultPoint.BEFORE_FREEZE_PUBLISH),
        )
        self.assertEqual(calls, {"factory": 0, "readiness": 0, "capability": 0})
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "freeze-missing")
        self.assertFalse((result.run_dir / "freeze.json").exists())
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_fault_02_adapter_exception_mid_slot_preserves_earlier_lanes(self) -> None:
        class FailsOnSecondLane(SyntheticAdapter):
            def measure(self, adapter_context, prepared, lane):
                if lane.lane_id == "common-query":
                    raise RuntimeError("simulated adapter crash")
                return super().measure(adapter_context, prepared, lane)

        def factory(assignment, slot, scenario):
            return FailsOnSecondLane(self.bundle, assignment, slot, scenario)

        result = self.run_default(adapter_factory=factory)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "adapter-failure")
        lanes = [
            name for name in self.files(result.run_dir, "slots/") if "/slot-" in name
        ]
        self.assertTrue(any(name.endswith("rare-query.json") for name in lanes))
        self.assertFalse(any(name.endswith("complete.json") for name in lanes))
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_fault_03_interruption_after_a_completed_slot_keeps_that_slot(self) -> None:
        result = self.run_default(
            faults=FaultPlan(
                point=FaultPoint.AFTER_SLOT_PUBLISH,
                campaign_kind="control",
                campaign_index=0,
                block=1,
                position=1,
            )
        )
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "crash-interrupted")
        completed = [
            name for name in self.files(result.run_dir, "slots/") if name.endswith("complete.json")
        ]
        self.assertEqual(len(completed), 1)
        self.assertIn("slots/control-0000/block-0001/slot-0001/complete.json", completed)
        self.assertEqual(
            len(self.files(result.run_dir, "slots/control-0000")), 3
        )
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_fault_04_hard_process_termination_leaves_an_interrupted_run(self) -> None:
        script = textwrap.dedent(
            """
            import os
            import shutil
            import sys
            import uuid
            from pathlib import Path

            from quervant_bench.config.contracts import load_experiment_bundle
            from quervant_bench.execution import (
                LogicalClock,
                ScenarioReadinessProvider,
                SimulatedCapabilityProvider,
                execute_synthetic,
                load_synthetic_scenario,
                synthetic_adapter_factory,
            )

            output = Path(sys.argv[1])
            evidence = Path(sys.argv[2])
            fixture = Path(sys.argv[3])
            shutil.copy(fixture, evidence / "synthetic-scenario.v1.json")
            bundle = load_experiment_bundle("synthetic-execution-smoke", Path("benchmarks/experiments"))
            scenario = load_synthetic_scenario(evidence, bundle=bundle)

            class KillingProvider(ScenarioReadinessProvider):
                def next_observations(self, campaign_kind, campaign_index):
                    observations = super().next_observations(campaign_kind, campaign_index)
                    if (campaign_kind, campaign_index) == ("treatment", 0):
                        os._exit(7)
                    return observations

            execute_synthetic(
                bundle=bundle,
                scenario=scenario,
                run_id=str(uuid.uuid4()),
                evidence_root=evidence,
                output_base=output,
                adapter_factory=synthetic_adapter_factory(bundle),
                capability_provider=SimulatedCapabilityProvider(),
                readiness_provider=KillingProvider(scenario),
                clock=LogicalClock(),
            )
            """
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(repository_root() / "benchmarks")
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(self.output),
                str(self.evidence),
                str(FIXTURES / SCENARIO_NAME),
            ],
            cwd=str(repository_root()),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 7, completed.stderr.decode("utf-8"))

        run_dirs = [
            path for path in (self.output / EXPERIMENT_ID).iterdir() if path.is_dir()
        ]
        self.assertEqual(len(run_dirs), 1)
        run_dir = run_dirs[0]
        self.assertFalse((run_dir / "seal.json").exists())
        self.assertTrue(list((run_dir / "events").glob("*.json")))
        self.assertTrue(list((run_dir / "slots" / "control-0000").rglob("complete.json")))
        with self.assertRaises(BenchError) as caught:
            replay_sealed_synthetic(
                run_dir, bundle=self.bundle, scenario_root=self.evidence
            )
        self.assertEqual(caught.exception.code, BM_EVIDENCE_UNAVAILABLE)
        self.assertIn("crash-interrupted", caught.exception.message)

    def test_fault_05_before_seal_never_publishes_or_retries(self) -> None:
        result = self.run_default(faults=FaultPlan(point=FaultPoint.BEFORE_SEAL))
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "crash-interrupted")
        self.assertFalse((result.run_dir / "seal.json").exists())
        before = {
            path.relative_to(result.run_dir).as_posix(): path.read_bytes()
            for path in result.run_dir.rglob("*")
            if path.is_file()
        }
        with self.assertRaises(BenchError) as caught:
            execute_synthetic(
                bundle=self.bundle,
                scenario=self.scenario,
                run_id=result.run_id,
                evidence_root=self.evidence,
                output_base=self.output,
                adapter_factory=synthetic_adapter_factory(self.bundle),
                capability_provider=SimulatedCapabilityProvider(),
                readiness_provider=ScenarioReadinessProvider(self.scenario),
                clock=LogicalClock(),
            )
        self.assertEqual(caught.exception.code, BM_PUBLICATION_CONFLICT)
        after = {
            path.relative_to(result.run_dir).as_posix(): path.read_bytes()
            for path in result.run_dir.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse((result.run_dir / "seal.json").exists())
        events = sorted((result.run_dir / "events").glob("*.json"))
        last = json.loads(events[-1].read_bytes())
        self.assertEqual(last["reason"], "crash-interrupted")

    def test_fault_measurement_variants_stop_before_any_seal(self) -> None:
        for point in (
            FaultPoint.MEASUREMENT_ERROR,
            FaultPoint.MEASUREMENT_WRONG_COUNT,
            FaultPoint.MEASUREMENT_WRONG_UNIT,
            FaultPoint.MEASUREMENT_WRONG_SCOPE,
            FaultPoint.WARMUP_ERROR,
            FaultPoint.BEFORE_WARMUP,
            FaultPoint.BEFORE_MEASURE,
            FaultPoint.BEFORE_ORACLE,
            FaultPoint.BEFORE_LANE_PUBLISH,
            FaultPoint.AFTER_LANE_PUBLISH,
            FaultPoint.BEFORE_SLOT_PUBLISH,
            FaultPoint.BEFORE_READINESS,
        ):
            with self.subTest(point=point.value):
                result = self.run_default(faults=FaultPlan(point=point))
                self.assertEqual(result.status, "stopped")
                self.assertIn(
                    result.reason,
                    {
                        "adapter-failure",
                        "invalid-measurement",
                        "crash-interrupted",
                        "host-not-ready",
                    },
                )
                self.assertFalse((result.run_dir / "seal.json").exists())

    def test_fault_target_outside_the_schedule_is_rejected_before_output(self) -> None:
        for plan in (
            FaultPlan(point=FaultPoint.BEFORE_SEAL, campaign_index=9),
            FaultPlan(point=FaultPoint.BEFORE_SEAL, block=9),
            FaultPlan(point=FaultPoint.BEFORE_SEAL, position=9),
            FaultPlan(point=FaultPoint.BEFORE_SEAL, lane_id="missing-lane"),
        ):
            with self.subTest(plan=plan):
                with self.assertRaises(BenchError):
                    self.run_default(faults=plan)
                self.assertEqual(list(self.output.iterdir()), [])


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

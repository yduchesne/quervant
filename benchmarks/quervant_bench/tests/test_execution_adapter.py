"""ADAPT-01…ADAPT-07 and CLOCK-01/CLOCK-02.

Adapter-contract fidelity, adversarial envelope rejection and the injected
logical clock. Nothing here times, sleeps or invokes a real adapter.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from quervant_bench.config.contracts import (
    AdapterContext,
    BenchmarkAdapter,
    BuildIdentity,
    load_experiment_bundle,
)
from quervant_bench.config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.execution import (
    ArmAssignment,
    LogicalClock,
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    SlotKey,
    execute_synthetic,
    load_synthetic_scenario,
    synthetic_adapter_factory,
)
from quervant_bench.execution.synthetic import SyntheticAdapter

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"
LANES = ("rare-query", "common-query")


def load_bundle():
    return load_experiment_bundle("synthetic-execution-smoke", EXPERIMENTS)


class AdapterTestBase(unittest.TestCase):
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

    def instrumented_factory(self, adapter_class, counts):
        bundle = self.bundle

        def factory(assignment, slot, scenario):
            adapter = adapter_class(bundle, assignment, slot, scenario)
            for name in ("prepare", "check_oracle", "warmup", "measure", "cleanup"):
                bound = getattr(adapter, name)

                def wrapper(*args, _bound=bound, _name=name, **kwargs):
                    counts[_name] = counts.get(_name, 0) + 1
                    return _bound(*args, **kwargs)

                setattr(adapter, name, wrapper)
            return adapter

        return factory

    def run_with(self, adapter_class):
        counts: dict[str, int] = {}
        result = self.run_default(
            adapter_factory=self.instrumented_factory(adapter_class, counts)
        )
        return result, counts

    def files(self, run_dir: Path, prefix: str = "") -> list[str]:
        return sorted(
            path.relative_to(run_dir).as_posix()
            for path in run_dir.rglob("*")
            if path.is_file() and path.relative_to(run_dir).as_posix().startswith(prefix)
        )


def context(run_id: str | None = None) -> AdapterContext:
    return AdapterContext(
        experiment_id="synthetic-execution-smoke",
        run_id=run_id or str(uuid.uuid4()),
        lane_ids=LANES,
        evidence_origin="synthetic",
        qualification_scope="simulated",
    )


class SyntheticAdapterTests(AdapterTestBase):
    def test_adapt_01_adapter_returns_exact_bm01_dataclasses(self) -> None:
        assignment = ArmAssignment(
            display_arm_id="baseline",
            declared_arm_id="baseline",
            variant="baseline",
            campaign_kind="treatment",
        )
        slot = SlotKey(
            campaign_kind="treatment", campaign_index=0, block=1, position=1, ordinal=1
        )
        adapter = SyntheticAdapter(self.bundle, assignment, slot, self.scenario)
        self.assertIsInstance(adapter, BenchmarkAdapter)
        adapter_context = context()
        prepared = adapter.prepare(adapter_context)
        self.assertEqual(prepared.status, "prepared")
        self.assertEqual(prepared.digest, self.scenario.scenario_digest)
        self.assertEqual(prepared.evidence_origin, "synthetic")
        oracle = adapter.check_oracle(adapter_context, prepared)
        self.assertEqual(oracle.status, "pass")
        self.assertEqual(oracle.oracle_id, self.bundle.workload.oracle_id)
        lane = self.bundle.workload.lanes[0]
        self.assertEqual(adapter.warmup(adapter_context, prepared, lane).lane_id, lane.lane_id)
        measurement = adapter.measure(adapter_context, prepared, lane)
        self.assertEqual(measurement.unit, "nanoseconds")
        self.assertEqual(measurement.direction, "lower-is-better")
        self.assertEqual(
            measurement.samples, self.scenario.values_for("baseline", lane.lane_id)
        )
        self.assertIsNone(adapter.cleanup(adapter_context, prepared))
        for name in ("prepare", "check_oracle", "warmup", "measure", "cleanup"):
            self.assertTrue(callable(getattr(adapter, name)))

    def test_adapt_01_real_build_manifest_is_refused_at_construction(self) -> None:
        real_bundle = replace(
            self.bundle,
            adapter=replace(
                self.bundle.adapter,
                build_identity=BuildIdentity(
                    kind="source-and-binary",
                    source_digest="sha256:" + "0" * 64,
                    executable_digest="sha256:" + "1" * 64,
                ),
            ),
        )
        with self.assertRaises(BenchError) as caught:
            SyntheticAdapter(
                real_bundle,
                ArmAssignment("baseline", "baseline", "baseline", "treatment"),
                SlotKey("treatment", 0, 1, 1, 1),
                self.scenario,
            )
        self.assertEqual(caught.exception.code, BM_ACQUISITION_PROHIBITED)

    def test_adapt_02_failed_oracle_prevents_every_warmup_and_measure(self) -> None:
        class OracleFail(SyntheticAdapter):
            def check_oracle(self, adapter_context, prepared):
                return replace(super().check_oracle(adapter_context, prepared), status="fail")

        result, counts = self.run_with(OracleFail)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "oracle-failed")
        self.assertEqual(counts["prepare"], 1)
        self.assertEqual(counts["check_oracle"], 1)
        self.assertEqual(counts.get("warmup", 0), 0)
        self.assertEqual(counts.get("measure", 0), 0)
        self.assertEqual(counts["cleanup"], 1)
        self.assertEqual(self.files(result.run_dir, "slots/"), [])
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_adapt_03_wrong_oracle_identity_stops_without_a_completed_slot(self) -> None:
        class WrongOracleId(SyntheticAdapter):
            def check_oracle(self, adapter_context, prepared):
                return replace(
                    super().check_oracle(adapter_context, prepared),
                    oracle_id="synthetic-other-oracle",
                )

        result, counts = self.run_with(WrongOracleId)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "adapter-failure")
        self.assertEqual(counts.get("warmup", 0), 0)
        self.assertEqual(counts["cleanup"], 1)
        self.assertNotIn("complete.json", "".join(self.files(result.run_dir, "slots/")))
        self.assertFalse((result.run_dir / "seal.json").exists())

    def test_adapt_04_wrong_sample_cardinality_is_rejected(self) -> None:
        class TooFewSamples(SyntheticAdapter):
            def measure(self, adapter_context, prepared, lane):
                result = super().measure(adapter_context, prepared, lane)
                return replace(result, samples=tuple(result.samples or ())[:-1])

        class TooManySamples(SyntheticAdapter):
            def measure(self, adapter_context, prepared, lane):
                result = super().measure(adapter_context, prepared, lane)
                return replace(result, samples=tuple(result.samples or ()) + (1,))

        for adapter_class in (TooFewSamples, TooManySamples):
            with self.subTest(adapter=adapter_class.__name__):
                result, counts = self.run_with(adapter_class)
                self.assertEqual(result.status, "stopped")
                self.assertEqual(result.reason, "invalid-measurement")
                self.assertEqual(counts["measure"], 1)
                self.assertEqual(counts["cleanup"], 1)
                self.assertEqual(self.files(result.run_dir, "slots/"), [])
                self.assertFalse((result.run_dir / "seal.json").exists())

    def test_adapt_05_unit_direction_lane_and_sample_domain_are_rejected(self) -> None:
        cases = {
            "wrong-unit": lambda result: replace(result, unit="bytes"),
            "wrong-direction": lambda result: replace(result, direction="higher-is-better"),
            "wrong-lane": lambda result: replace(result, lane_id="common-query"),
            "wrong-origin": lambda result: replace(
                result, evidence_origin="real", qualification_scope="official"
            ),
            "wrong-scope": lambda result: replace(
                result, qualification_scope="official"
            ),
            "negative": lambda result: replace(result, samples=(-1, 1, 1)),
            "float": lambda result: replace(result, samples=(1.5, 1, 1)),
            "boolean": lambda result: replace(result, samples=(True, 1, 1)),
            "zero": lambda result: replace(result, samples=(0, 1, 1)),
        }
        for label, transform in cases.items():
            with self.subTest(case=label):
                class Mutated(SyntheticAdapter):
                    def measure(self, adapter_context, prepared, lane, _transform=transform):
                        return _transform(
                            super().measure(adapter_context, prepared, lane)
                        )

                clock = LogicalClock()
                counts: dict[str, int] = {}
                result = self.run_default(
                    adapter_factory=self.instrumented_factory(Mutated, counts),
                    clock=clock,
                )
                self.assertEqual(result.status, "stopped")
                self.assertEqual(result.reason, "invalid-measurement")
                self.assertEqual(self.files(result.run_dir, "slots/"), [])
                self.assertFalse((result.run_dir / "seal.json").exists())
                self.assertEqual(
                    clock.now_ns(),
                    2,
                    "the measurement must not advance the logical clock",
                )

    def test_adapt_06_warmup_error_stops_the_lane_and_cleans_up_once(self) -> None:
        class WarmupError(SyntheticAdapter):
            def warmup(self, adapter_context, prepared, lane):
                return replace(
                    super().warmup(adapter_context, prepared, lane), status="error"
                )

        result, counts = self.run_with(WarmupError)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "adapter-failure")
        self.assertEqual(counts["warmup"], 1)
        self.assertEqual(counts.get("measure", 0), 0)
        self.assertEqual(counts["cleanup"], 1)
        self.assertEqual(self.files(result.run_dir, "slots/"), [])

    def test_adapt_07_cleanup_failure_prevents_slot_completion(self) -> None:
        class CleanupFails(SyntheticAdapter):
            def cleanup(self, adapter_context, prepared):
                raise RuntimeError("simulated cleanup defect")

        result, counts = self.run_with(CleanupFails)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.reason, "adapter-failure")
        self.assertEqual(counts["cleanup"], 1)
        lane_files = self.files(result.run_dir, "slots/")
        self.assertTrue(lane_files)
        self.assertFalse(any(name.endswith("complete.json") for name in lane_files))
        self.assertFalse((result.run_dir / "seal.json").exists())


class LogicalClockTests(unittest.TestCase):
    def test_clock_01_advances_only_by_explicit_simulated_increments(self) -> None:
        clock = LogicalClock(0)
        self.assertEqual(clock.now_ns(), 0)
        self.assertEqual(clock.advance_ns(1), 1)
        self.assertEqual(clock.advance_ns(0), 1)
        self.assertEqual(clock.advance_ns(10), 11)
        self.assertFalse(hasattr(clock, "perf_counter"))
        self.assertFalse(hasattr(clock, "sleep"))

    def test_clock_02_overflow_and_invalid_inputs_fail_closed(self) -> None:
        clock = LogicalClock(9_223_372_036_854_775_806)
        with self.assertRaises(BenchError) as caught:
            clock.advance_ns(2)
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
        self.assertEqual(clock.now_ns(), 9_223_372_036_854_775_806)
        for bad in (-1, True, 1.5, "1"):
            with self.assertRaises(BenchError):
                clock.advance_ns(bad)  # type: ignore[arg-type]
        with self.assertRaises(BenchError):
            LogicalClock(-1)
        with self.assertRaises(BenchError):
            LogicalClock(True)  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

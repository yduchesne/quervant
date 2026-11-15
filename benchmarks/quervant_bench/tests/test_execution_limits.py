"""LIMIT-01…LIMIT-04: frozen simulator budgets and bounded failure."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from quervant_bench.config.codec import canonical_document_bytes
from quervant_bench.config.contracts import (
    ArmMultiplicity,
    Lane,
    Workload,
    load_experiment_bundle,
)
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.execution import (
    LogicalClock,
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    execute_synthetic,
    load_synthetic_scenario,
    replay_sealed_synthetic,
    synthetic_adapter_factory,
)
from quervant_bench.execution.contracts import (
    MAX_BLOCKS,
    MAX_LANES,
    MAX_SAMPLES_PER_LANE_SLOT,
    MAX_SLOTS_PER_BLOCK,
    MAX_TOTAL_LANE_SLOTS,
    MAX_WARMUPS_PER_LANE_SLOT,
    total_lane_slots,
)
from quervant_bench.execution.recorder import record_bytes
from quervant_bench.execution.scenario import validate_scenario_document
from quervant_bench.protocol.schedule import ScheduleSpec, _compile_spec

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"


def load_bundle():
    return load_experiment_bundle("synthetic-execution-smoke", EXPERIMENTS)


def schedule_spec(multiplicities, blocks, slots_per_block):
    return ScheduleSpec(
        schedule_id="synthetic-execution-balanced",
        mode="seeded-balanced",
        blocks=blocks,
        slots_per_block=slots_per_block,
        seed=42,
        multiplicities=tuple(
            ArmMultiplicity(arm_id=arm_id, slots_per_block=count)
            for arm_id, count in multiplicities
        ),
        explicit_orders=None,
        protocol_digest="sha256:" + "0" * 64,
    )


class LimitTests(unittest.TestCase):
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

    def scenario_document(self) -> dict:
        return json.loads((FIXTURES / SCENARIO_NAME).read_bytes())

    def test_limit_01_arm_block_and_slot_budgets_are_enforced(self) -> None:
        too_many_arms = tuple(
            (f"arm-{index}", 1) for index in range(17)
        )
        with self.assertRaises(BenchError):
            _compile_spec(schedule_spec(too_many_arms, 4, 17))
        with self.assertRaises(BenchError):
            _compile_spec(schedule_spec((("baseline", 8), ("candidate", 8)), MAX_BLOCKS + 1, 16))
        with self.assertRaises(BenchError):
            _compile_spec(
                schedule_spec(
                    (("baseline", 8), ("candidate", 9)), 4, MAX_SLOTS_PER_BLOCK + 1
                )
            )
        with self.assertRaises(BenchError) as caught:
            total_lane_slots(
                control_campaigns=4,
                control_blocks=MAX_BLOCKS,
                control_slots_per_block=MAX_SLOTS_PER_BLOCK,
                treatment_campaigns=8,
                blocks=MAX_BLOCKS,
                slots_per_block=MAX_SLOTS_PER_BLOCK,
                lanes=MAX_LANES,
            )
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertLessEqual(MAX_TOTAL_LANE_SLOTS, 50_000)

    def test_limit_01_sample_warmup_and_lane_budgets_are_enforced(self) -> None:
        oversampled = replace(self.bundle.protocol, samples_per_lane_slot=MAX_SAMPLES_PER_LANE_SLOT + 1)
        with self.assertRaises(BenchError) as caught:
            validate_scenario_document(
                self.scenario_document(),
                bundle=replace(self.bundle, protocol=oversampled),
            )
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

        overwarm = replace(
            self.bundle.protocol, warmups_per_lane_slot=MAX_WARMUPS_PER_LANE_SLOT + 1
        )
        with self.assertRaises(BenchError):
            validate_scenario_document(
                self.scenario_document(), bundle=replace(self.bundle, protocol=overwarm)
            )

        lanes = tuple(
            Lane(
                lane_id=f"lane-{index:03d}",
                operation="search",
                cache_regime="warm",
                params={},
            )
            for index in range(MAX_LANES + 1)
        )
        workload_document = json.loads(json.dumps(dict(self.bundle.workload_document)))
        workload_document["lanes"] = [
            {
                "lane_id": lane.lane_id,
                "operation": lane.operation,
                "cache_regime": lane.cache_regime,
                "params": {},
            }
            for lane in lanes
        ]
        from quervant_bench.config.codec import content_digest

        protocol_document = json.loads(json.dumps(dict(self.bundle.protocol_document)))
        protocol_document["workload_digest"] = content_digest(workload_document)
        crowded = replace(
            self.bundle,
            workload=replace(self.bundle.workload, lanes=lanes),
            workload_document=workload_document,
            protocol_document=protocol_document,
        )
        with self.assertRaises(BenchError) as caught:
            validate_scenario_document(self.scenario_document(), bundle=crowded)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_limit_02_nanosecond_and_clock_overflow_fail_closed(self) -> None:
        document = self.scenario_document()
        document["samples"][0]["values"][0] = 9_223_372_036_854_775_808
        with self.assertRaises(BenchError):
            validate_scenario_document(document, bundle=self.bundle)

        clock = LogicalClock(9_223_372_036_854_775_807)
        with self.assertRaises(BenchError) as caught:
            clock.advance_ns(1)
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
        self.assertEqual(clock.now_ns(), 9_223_372_036_854_775_807)

        (self.evidence / SCENARIO_NAME).write_bytes(canonical_document_bytes(document))
        with self.assertRaises(BenchError):
            load_synthetic_scenario(self.evidence, bundle=self.bundle)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_limit_03_oversized_documents_are_rejected_before_allocation(self) -> None:
        oversized = self.scenario_document()
        oversized["samples"][0]["values"] = [1] * 700_000
        (self.evidence / SCENARIO_NAME).write_bytes(canonical_document_bytes(oversized))
        with self.assertRaises(BenchError) as caught:
            load_synthetic_scenario(self.evidence, bundle=self.bundle)
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

        huge_record = {
            "kind": "synthetic-state-event",
            "schema_version": 1,
            "sequence": 1,
            "from_state": "none",
            "to_state": "planned",
            "reason": "new-run",
            "logical_ns": 0,
            "evidence_origin": "synthetic",
            "qualification_scope": "simulated",
            "padding": "x" * 1_100_000,
        }
        with self.assertRaises(BenchError) as caught:
            record_bytes(huge_record)
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_limit_04_unexpected_records_are_never_truncated(self) -> None:
        document = self.scenario_document()
        document["samples"].append(
            {"arm_id": "baseline", "lane_id": "extra-query", "values": [1, 1, 1]}
        )
        with self.assertRaises(BenchError):
            validate_scenario_document(document, bundle=self.bundle)

        document = self.scenario_document()
        document["readiness"].append(
            {
                "campaign_kind": "treatment",
                "campaign_index": 2,
                "observations": [
                    {"elapsed_ms": 10, "busy_permille": 20, "steal_permille": 0}
                ],
            }
        )
        with self.assertRaises(BenchError):
            validate_scenario_document(document, bundle=self.bundle)

        result = execute_synthetic(
            bundle=self.bundle,
            scenario=self.scenario,
            run_id=str(uuid.uuid4()),
            evidence_root=self.evidence,
            output_base=self.output,
            adapter_factory=synthetic_adapter_factory(self.bundle),
            capability_provider=SimulatedCapabilityProvider(),
            readiness_provider=ScenarioReadinessProvider(self.scenario),
            clock=LogicalClock(),
        )
        self.assertEqual(result.status, "sealed")
        shutil.copy(
            result.run_dir / "events" / "00000009.json",
            result.run_dir / "events" / "00000010.json",
        )
        with self.assertRaises(BenchError):
            replay_sealed_synthetic(
                result.run_dir, bundle=self.bundle, scenario_root=self.evidence
            )


class WorkloadLaneBudgetTests(unittest.TestCase):
    def test_workload_type_allows_exactly_max_lanes(self) -> None:
        bundle = load_bundle()
        lanes = tuple(
            Lane(
                lane_id=f"lane-{index:03d}",
                operation="search",
                cache_regime="warm",
                params={},
            )
            for index in range(MAX_LANES)
        )
        workload: Workload = replace(bundle.workload, lanes=lanes)
        self.assertEqual(len(workload.lanes), MAX_LANES)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

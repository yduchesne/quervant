"""REPLAY-01…REPLAY-05 and SEAL-01…SEAL-05: read-only structural replay."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.config.errors import (
    BM_DUPLICATE_KEY,
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
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
from quervant_bench.execution.recorder import event_relative_path

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"
GOLDEN = json.loads(
    (FIXTURES / "golden-structural-summary.v1.json").read_text(encoding="utf-8")
)


def load_bundle():
    return load_experiment_bundle("synthetic-execution-smoke", EXPERIMENTS)


class ReplayTestBase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "out"
        self.output.mkdir()
        self.scenario_root = self.root / "scenarios"
        self.scenario_root.mkdir()
        shutil.copy(FIXTURES / SCENARIO_NAME, self.scenario_root / SCENARIO_NAME)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        shutil.copy(FIXTURES / SCENARIO_NAME, self.evidence / SCENARIO_NAME)
        self.bundle = load_bundle()
        self.scenario = load_synthetic_scenario(self.evidence, bundle=self.bundle)
        self.result = execute_synthetic(
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
        self.assertEqual(self.result.status, "sealed")
        self.run_dir = self.result.run_dir

    def replay(self):
        return replay_sealed_synthetic(
            self.run_dir, bundle=self.bundle, scenario_root=self.scenario_root
        )

    def rewrite(self, relative: str, document: dict) -> None:
        (self.run_dir / relative).write_bytes(canonical_document_bytes(document))

    def read(self, relative: str) -> dict:
        return json.loads((self.run_dir / relative).read_bytes())

    def refresh_seal(self, changed: list[str]) -> None:
        seal = self.read("seal.json")
        expected = {entry["path"]: entry for entry in seal["files"]}
        for relative in changed:
            payload = (self.run_dir / relative).read_bytes()
            expected[relative]["digest"] = (
                "sha256:" + hashlib.sha256(payload).hexdigest()
            )
            expected[relative]["byte_length"] = len(payload)
        seal["files"] = [expected[path] for path in sorted(expected)]
        (self.run_dir / "seal.json").write_bytes(canonical_document_bytes(seal))

    def sealed_run_with_clock(self, start_ns: int):
        """Execute one additional sealed run whose logical clock starts at ``start_ns``."""

        output = self.root / f"out-{start_ns}"
        output.mkdir()
        scenario = load_synthetic_scenario(self.evidence, bundle=self.bundle)
        result = execute_synthetic(
            bundle=self.bundle,
            scenario=scenario,
            run_id=str(uuid.uuid4()),
            evidence_root=self.evidence,
            output_base=output,
            adapter_factory=synthetic_adapter_factory(self.bundle),
            capability_provider=SimulatedCapabilityProvider(),
            readiness_provider=ScenarioReadinessProvider(scenario),
            clock=LogicalClock(start_ns),
        )
        self.assertEqual(result.status, "sealed")
        return result

    def event_times(self, run_dir: Path, count: int) -> list[int]:
        return [
            json.loads((run_dir / event_relative_path(sequence)).read_bytes())["logical_ns"]
            for sequence in range(1, count + 1)
        ]

    def campaign_bounds(self, run_dir: Path) -> list[tuple[int, int]]:
        """Independent oracle: first/last lane envelope of each declared campaign."""

        bounds = []
        for kind, index in (("control", 0), ("treatment", 0), ("treatment", 1)):
            prefix = run_dir / "slots" / f"{kind}-{index:04d}"
            first = json.loads(
                (prefix / "block-0001" / "slot-0001" / "rare-query.json").read_bytes()
            )
            last = json.loads(
                (prefix / "block-0004" / "slot-0002" / "common-query.json").read_bytes()
            )
            bounds.append((first["logical_start_ns"], last["logical_end_ns"]))
        return bounds

    def state(self) -> dict[str, tuple[int, int, int]]:
        observed = {}
        for path in self.run_dir.rglob("*"):
            if path.is_file():
                info = path.stat()
                observed[path.relative_to(self.run_dir).as_posix()] = (
                    info.st_ino,
                    info.st_mtime_ns,
                    info.st_size,
                )
        return observed


class ReplayTests(ReplayTestBase):
    def test_replay_01_verification_is_repeatable_and_read_only(self) -> None:
        before = self.state()
        first = self.replay()
        second = self.replay()
        self.assertEqual(first, second)
        self.assertEqual(first.status, "verified-synthetic-structure")
        self.assertEqual(self.state(), before)

    def test_seal_01_structural_counts_match_the_manual_oracle(self) -> None:
        replay = self.replay()
        self.assertEqual(replay.controls_completed, GOLDEN["control_campaigns"])
        self.assertEqual(replay.treatments_completed, GOLDEN["treatment_campaigns"])
        self.assertEqual(replay.slots_completed, GOLDEN["slots_total"])
        self.assertEqual(replay.lane_envelopes, GOLDEN["lane_envelopes"])
        self.assertEqual(replay.synthetic_samples, GOLDEN["synthetic_samples"])
        self.assertEqual(replay.run_id, self.result.run_id)
        self.assertEqual(replay.seal_digest, content_digest(self.read("seal.json")))

    def test_seal_02_missing_slot_or_campaign_records_are_rejected(self) -> None:
        lane = sorted((self.run_dir / "slots").rglob("*.json"))
        lane_file = next(path for path in lane if not path.name.endswith("complete.json"))
        lane_file.unlink()
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertIn(caught.exception.code, {BM_UNSAFE_INPUT, "BM_IDENTITY_INVALID"})

        self.setUp()
        control_report = self.run_dir / "controls" / "control-0000.json"
        control_report.unlink()
        with self.assertRaises(BenchError):
            self.replay()

    def test_seal_03_duplicate_or_unexpected_records_are_rejected(self) -> None:
        source = sorted((self.run_dir / "slots" / "treatment-0000").rglob("*.json"))[0]
        shutil.copy(source, source.parent / "duplicate.json")
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_seal_04_changed_samples_are_rejected_even_with_updated_hashes(self) -> None:
        lane = next(
            path
            for path in sorted((self.run_dir / "slots").rglob("*.json"))
            if not path.name.endswith("complete.json")
        )
        relative = lane.relative_to(self.run_dir).as_posix()
        document = self.read(relative)
        document["samples"][0] = document["samples"][0] + 1
        self.rewrite(relative, document)
        self.refresh_seal([relative])
        with self.assertRaises(BenchError):
            self.replay()

    def test_seal_05_a_seal_never_claims_a_performance_decision(self) -> None:
        replay = self.replay()
        fields = {field for field in replay.__dataclass_fields__}
        self.assertEqual(
            fields,
            {
                "status",
                "run_id",
                "seal_digest",
                "controls_completed",
                "treatments_completed",
                "slots_completed",
                "lane_envelopes",
                "synthetic_samples",
            },
        )
        self.assertFalse(hasattr(replay, "winner"))
        self.assertFalse(hasattr(replay, "p_value"))
        seal = self.read("seal.json")
        flattened = json.dumps(seal).lower()
        for forbidden in ("winner", "attestation", "gate-a", "official"):
            self.assertNotIn(forbidden, flattened)

    def test_replay_02_missing_freeze_schedule_or_control_report_is_rejected(self) -> None:
        for relative in ("freeze.json", "schedule.json", "control-schedule.json"):
            with self.subTest(relative=relative):
                self.setUp()
                (self.run_dir / relative).unlink()
                with self.assertRaises(BenchError):
                    self.replay()

    def test_replay_03_forged_scope_is_rejected_despite_a_new_seal_digest(self) -> None:
        seal = self.read("seal.json")
        seal["qualification_scope"] = "official"
        (self.run_dir / "seal.json").write_bytes(canonical_document_bytes(seal))
        with self.assertRaises(BenchError):
            self.replay()

    def test_replay_04_a_changed_scenario_is_rejected(self) -> None:
        path = self.scenario_root / SCENARIO_NAME
        raw = path.read_bytes()
        document = json.loads(raw)
        document["samples"][0]["values"][0] = document["samples"][0]["values"][0] + 1
        path.write_bytes(canonical_document_bytes(document))
        self.assertEqual(len(canonical_document_bytes(document)), len(raw))
        with self.assertRaises(BenchError):
            self.replay()

    def test_replay_05_corrupt_or_non_canonical_records_are_rejected(self) -> None:
        target = self.run_dir / "readiness" / "control-0000.json"
        original = target.read_bytes()

        target.write_bytes(original[:-20])
        self.refresh_seal(["readiness/control-0000.json"])
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

        target.write_bytes(b'{"kind":"synthetic-readiness","kind":"synthetic-readiness"}')
        self.refresh_seal(["readiness/control-0000.json"])
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_DUPLICATE_KEY)

        target.write_bytes(json.dumps(json.loads(original), indent=2).encode("utf-8"))
        self.refresh_seal(["readiness/control-0000.json"])
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_replay_requires_an_absolute_evidence_seal(self) -> None:
        (self.run_dir / "seal.json").unlink()
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_EVIDENCE_UNAVAILABLE)
        self.assertIn("crash-interrupted", caught.exception.message)

class FixupSealBindingTests(ReplayTestBase):
    """RF03-01 / INV-F01: the seal must bind the canonical freeze document."""

    def test_fx_seal_01_golden_replay_binds_freeze_and_is_read_only(self) -> None:
        before = self.state()
        seal = self.read("seal.json")
        self.assertEqual(seal["freeze_digest"], content_digest(self.read("freeze.json")))
        first = self.replay()
        second = self.replay()
        self.assertEqual(first.status, "verified-synthetic-structure")
        self.assertEqual(first, second)
        self.assertEqual(self.state(), before)

    def test_fx_seal_02_wrong_freeze_digest_in_the_seal_is_rejected(self) -> None:
        seal = self.read("seal.json")
        original = seal["freeze_digest"]
        forged = "sha256:" + ("1" * 64)
        if forged == original:  # pragma: no cover - astronomically unlikely
            forged = "sha256:" + ("2" * 64)
        seal["freeze_digest"] = forged
        self.rewrite("seal.json", seal)
        before = self.state()
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "seal.freeze_digest")
        self.assertEqual(self.state(), before)

    def test_fx_seal_03_a_second_valid_shaped_digest_is_also_rejected(self) -> None:
        seal = self.read("seal.json")
        seal["freeze_digest"] = "sha256:" + ("f" * 64)
        self.rewrite("seal.json", seal)
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "seal.freeze_digest")
        self.assertNotIn(caught.exception.code, {BM_EVIDENCE_UNAVAILABLE, BM_UNSAFE_INPUT})
        self.assertNotIn("canonical", caught.exception.message)
        self.assertIn("freeze", caught.exception.message)


class FixupTimelineTests(ReplayTestBase):
    """RF03-03 / INV-F04: events bind to exact campaign boundaries."""

    def test_fx_time_01_event_times_equal_the_campaign_boundaries(self) -> None:
        self.assertEqual(self.replay().status, "verified-synthetic-structure")
        bounds = self.campaign_bounds(self.run_dir)
        expected = [bounds[0][0], bounds[0][0]]
        for start, _end in bounds:
            expected.extend((start, start))
        expected.append(bounds[-1][1])
        self.assertEqual(self.event_times(self.run_dir, len(expected)), expected)

    def test_fx_time_02_nonzero_logical_epoch_is_supported(self) -> None:
        result = self.sealed_run_with_clock(1000)
        replay = replay_sealed_synthetic(
            result.run_dir, bundle=self.bundle, scenario_root=self.scenario_root
        )
        self.assertEqual(replay.status, "verified-synthetic-structure")
        bounds = self.campaign_bounds(result.run_dir)
        times = self.event_times(result.run_dir, 9)
        self.assertEqual(times[0], 1000)
        self.assertEqual(times[1], 1000)
        self.assertEqual(times[2], bounds[0][0])
        self.assertEqual(bounds[0][0], 1000)
        self.assertEqual(times[-1], bounds[-1][1])

    def test_fx_time_03_uniformly_inflated_event_times_are_rejected(self) -> None:
        sequence_count = 9
        for sequence in range(1, sequence_count + 1):
            relative = event_relative_path(sequence)
            document = self.read(relative)
            document["logical_ns"] = 10**12
            self.rewrite(relative, document)
        self.refresh_seal([event_relative_path(n) for n in range(1, sequence_count + 1)])
        before = self.state()
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "events")
        self.assertEqual(self.state(), before)

    def test_fx_time_04_shifted_first_campaign_boundary_is_rejected(self) -> None:
        boundary = self.campaign_bounds(self.run_dir)[0][0]
        for sequence in (3, 4):
            relative = event_relative_path(sequence)
            document = self.read(relative)
            self.assertEqual(document["logical_ns"], boundary)
            document["logical_ns"] = boundary + 1
            self.rewrite(relative, document)
        self.refresh_seal([event_relative_path(3), event_relative_path(4)])
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "events")

    def test_fx_time_05_early_completion_event_is_rejected(self) -> None:
        times = self.event_times(self.run_dir, 9)
        relative = event_relative_path(9)
        document = self.read(relative)
        document["logical_ns"] = times[7]
        self.rewrite(relative, document)
        self.refresh_seal([relative])
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "events")

    def test_fx_time_06_shifted_middle_campaign_boundary_is_rejected(self) -> None:
        times = self.event_times(self.run_dir, 9)
        self.assertEqual(times[4], times[5])
        self.assertGreater(
            times[6],
            times[4] + 1,
            "prescribed fixture precondition for this counterexample",
        )
        for sequence in (5, 6):
            relative = event_relative_path(sequence)
            document = self.read(relative)
            document["logical_ns"] = times[4] + 1
            self.rewrite(relative, document)
        self.refresh_seal([event_relative_path(5), event_relative_path(6)])
        with self.assertRaises(BenchError) as caught:
            self.replay()
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)
        self.assertEqual(caught.exception.field_path, "events")

    def test_fx_time_07_timeline_rejection_never_rewrites_or_reorders(self) -> None:
        relative = event_relative_path(9)
        document = self.read(relative)
        document["logical_ns"] = self.event_times(self.run_dir, 9)[7]
        self.rewrite(relative, document)
        self.refresh_seal([relative])
        before = self.state()
        bytes_before = {
            path.relative_to(self.run_dir).as_posix(): path.read_bytes()
            for path in self.run_dir.rglob("*")
            if path.is_file()
        }
        with self.assertRaises(BenchError):
            self.replay()
        self.assertEqual(self.state(), before)
        self.assertEqual(
            bytes_before,
            {
                path.relative_to(self.run_dir).as_posix(): path.read_bytes()
                for path in self.run_dir.rglob("*")
                if path.is_file()
            },
        )
        self.assertEqual(self.event_times(self.run_dir, 9)[8], document["logical_ns"])



if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

"""STORE-01…STORE-06 and PATH-01…PATH-03: exclusive durable publication."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from quervant_bench.config.codec import canonical_document_bytes
from quervant_bench.config.contracts import load_experiment_bundle
from quervant_bench.config.errors import (
    BM_FILE_MISSING,
    BM_INTERNAL_ERROR,
    BM_NOT_IMPLEMENTED,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.evidence.provenance import repository_root
from quervant_bench.execution import (
    ExecutionStore,
    FaultPlan,
    FaultPoint,
    LogicalClock,
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    execute_synthetic,
    load_synthetic_scenario,
    synthetic_adapter_factory,
)

EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"
EXPERIMENT_ID = "synthetic-execution-smoke"


def load_bundle():
    return load_experiment_bundle(EXPERIMENT_ID, EXPERIMENTS)


def fd_count() -> int:
    """Return the number of descriptors this process currently holds."""

    return len(os.listdir("/proc/self/fd"))


class StoreTestBase(unittest.TestCase):
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

    def snapshot(self, run_dir: Path) -> dict[str, bytes]:
        return {
            path.relative_to(run_dir).as_posix(): path.read_bytes()
            for path in run_dir.rglob("*")
            if path.is_file()
        }

    def store(self, run_id: str | None = None) -> ExecutionStore:
        return ExecutionStore.create(
            self.output,
            EXPERIMENT_ID,
            run_id or str(uuid.uuid4()),
            evidence_root=self.evidence,
            repo_root=repository_root(),
        )


class PublicationTests(StoreTestBase):
    def test_store_01_seal_is_the_last_complete_canonical_inventory(self) -> None:
        result = self.run_default()
        self.assertEqual(result.status, "sealed")
        seal = json.loads((result.run_dir / "seal.json").read_bytes())
        listed = {entry["path"]: entry for entry in seal["files"]}
        actual = self.snapshot(result.run_dir)
        self.assertEqual(set(listed) | {"seal.json"}, set(actual))
        for path, entry in listed.items():
            payload = actual[path]
            self.assertEqual(entry["byte_length"], len(payload))
            self.assertEqual(
                entry["digest"], "sha256:" + hashlib.sha256(payload).hexdigest()
            )
            self.assertEqual(canonical_document_bytes(json.loads(payload)), payload)
        self.assertNotIn("seal.json", listed)
        self.assertEqual(seal["status"], "sealed-structural")
        leftovers = [name for name in actual if name.endswith(".pending") or "tmp" in name]
        self.assertEqual(leftovers, [])

    def test_store_02_reusing_a_run_identity_never_overwrites(self) -> None:
        sealed = self.run_default()
        before = self.snapshot(sealed.run_dir)
        with self.assertRaises(BenchError) as caught:
            self.run_default(run_id=sealed.run_id)
        self.assertEqual(caught.exception.code, BM_PUBLICATION_CONFLICT)
        self.assertEqual(self.snapshot(sealed.run_dir), before)

        partial = self.run_default(faults=FaultPlan(point=FaultPoint.BEFORE_SEAL))
        self.assertEqual(partial.status, "stopped")
        partial_before = self.snapshot(partial.run_dir)
        with self.assertRaises(BenchError) as caught:
            self.run_default(run_id=partial.run_id)
        self.assertEqual(caught.exception.code, BM_PUBLICATION_CONFLICT)
        self.assertEqual(self.snapshot(partial.run_dir), partial_before)

    def test_store_03_write_failure_before_freeze_leaves_only_the_planned_root(self) -> None:
        store = self.store()
        store.write_new(
            "events/00000001.json",
            {
                "kind": "synthetic-state-event",
                "schema_version": 1,
                "sequence": 1,
                "from_state": "none",
                "to_state": "planned",
                "reason": "new-run",
                "logical_ns": 0,
                "evidence_origin": "synthetic",
                "qualification_scope": "simulated",
            },
        )
        with mock.patch.object(
            ExecutionStore,
            "_write_exclusive",
            side_effect=BenchError(BM_NOT_IMPLEMENTED, "simulated publication failure"),
        ):
            with self.assertRaises(BenchError):
                store.write_new("schedule.json", {"kind": "synthetic-schedule"})
        self.assertEqual(store.list_existing(), ("events/00000001.json",))
        self.assertFalse((store.run_dir / "seal.json").exists())

    def test_store_04_failure_after_a_lane_record_preserves_that_record(self) -> None:
        original = ExecutionStore._write_exclusive
        state = {"lane_written": False, "failed": False}

        def wrapper(store_self, member, document):
            if state["lane_written"] and not state["failed"]:
                state["failed"] = True
                raise BenchError(
                    BM_NOT_IMPLEMENTED,
                    "simulated unsupported fsync after a lane record",
                )
            digest = original(store_self, member, document)
            if member.startswith("slots/") and not member.endswith("complete.json"):
                state["lane_written"] = True
            return digest

        with mock.patch.object(ExecutionStore, "_write_exclusive", new=wrapper):
            with self.assertRaises(BenchError) as caught:
                self.run_default()
        self.assertEqual(caught.exception.code, BM_NOT_IMPLEMENTED)

        experiment_dir = self.output / EXPERIMENT_ID
        run_dirs = [path for path in experiment_dir.iterdir() if path.is_dir()]
        self.assertEqual(len(run_dirs), 1)
        run_dir = run_dirs[0]
        lane_files = sorted((run_dir / "slots").rglob("*.json"))
        self.assertEqual(len(lane_files), 1)
        document = json.loads(lane_files[0].read_bytes())
        self.assertEqual(document["kind"], "synthetic-lane-envelope")
        self.assertEqual(canonical_document_bytes(document), lane_files[0].read_bytes())
        self.assertEqual(list((run_dir / "slots").rglob("complete.json")), [])
        self.assertFalse((run_dir / "seal.json").exists())

    def test_store_05_symlinked_or_protected_output_is_refused(self) -> None:
        real = self.root / "real-output"
        real.mkdir()
        link = self.root / "linked-output"
        os.symlink(real, link)
        with self.assertRaises(BenchError) as caught:
            ExecutionStore.create(
                link,
                EXPERIMENT_ID,
                str(uuid.uuid4()),
                evidence_root=self.evidence,
                repo_root=repository_root(),
            )
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
        self.assertEqual(list(real.iterdir()), [])

        repository = repository_root()
        with self.assertRaises(BenchError) as caught:
            ExecutionStore.create(
                repository / "docs",
                EXPERIMENT_ID,
                str(uuid.uuid4()),
                evidence_root=self.evidence,
                repo_root=repository,
            )
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_store_06_concurrent_creation_has_exactly_one_winner(self) -> None:
        run_id = str(uuid.uuid4())
        results: list[object] = []
        barrier = threading.Barrier(2)

        def attempt() -> None:
            barrier.wait()
            try:
                results.append(
                    ExecutionStore.create(
                        self.output,
                        EXPERIMENT_ID,
                        run_id,
                        evidence_root=self.evidence,
                        repo_root=repository_root(),
                    )
                )
            except BenchError as error:
                results.append(error)

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        winners = [item for item in results if isinstance(item, ExecutionStore)]
        conflicts = [
            item
            for item in results
            if isinstance(item, BenchError) and item.code == BM_PUBLICATION_CONFLICT
        ]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(conflicts), 1)
        winner = winners[0]
        self.assertEqual(list(winner.run_dir.iterdir()), [])


class PathSafetyTests(StoreTestBase):
    def test_path_01_overlapping_evidence_and_output_roots_are_refused(self) -> None:
        with self.assertRaises(BenchError) as caught:
            ExecutionStore.create(
                self.evidence,
                EXPERIMENT_ID,
                str(uuid.uuid4()),
                evidence_root=self.evidence,
                repo_root=repository_root(),
            )
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

        nested = self.evidence / "nested"
        nested.mkdir()
        with self.assertRaises(BenchError) as caught:
            ExecutionStore.create(
                nested,
                EXPERIMENT_ID,
                str(uuid.uuid4()),
                evidence_root=self.evidence,
                repo_root=repository_root(),
            )
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)

    def test_path_02_historical_repository_paths_are_unwritable(self) -> None:
        repository = self.root / "isolated-repository"
        repository.mkdir()
        for relative in ("benchmarks", "docs", "target"):
            (repository / relative).mkdir()
        for relative in ("benchmarks", "docs", "target"):
            with self.subTest(path=relative):
                protected = repository / relative
                with self.assertRaises(BenchError) as caught:
                    ExecutionStore.create(
                        protected,
                        EXPERIMENT_ID,
                        str(uuid.uuid4()),
                        evidence_root=self.evidence,
                        repo_root=repository,
                    )
                self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
                self.assertEqual(list(protected.iterdir()), [])

    def test_fx_path_02_absent_protected_root_is_a_missing_input(self) -> None:
        repository = self.root / "isolated-repository-absent"
        repository.mkdir()
        missing = repository / "target"
        self.assertFalse(missing.exists())
        with self.assertRaises(BenchError) as caught:
            ExecutionStore.create(
                missing,
                EXPERIMENT_ID,
                str(uuid.uuid4()),
                evidence_root=self.evidence,
                repo_root=repository,
            )
        self.assertEqual(caught.exception.code, BM_FILE_MISSING)
        self.assertFalse(missing.exists())
        self.assertEqual(list(repository.iterdir()), [])

    def test_fx_path_03_external_output_is_accepted_and_confined(self) -> None:
        store = self.store()
        digest = store.write_new("events/00000001.json", _event_document())
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(store.list_existing(), ("events/00000001.json",))
        self.assertTrue(
            store.run_dir.resolve().is_relative_to(self.output.resolve())
        )
        self.assertFalse((store.run_dir / "seal.json").exists())

    def test_fx_path_04_protected_path_fixture_is_checkout_independent(self) -> None:
        self.assertFalse(
            str(self.root.resolve()).startswith(str(repository_root().resolve())),
            "the protected-path fixture must live outside the checkout",
        )
        repository = self.root / "isolated-repository-mixed"
        repository.mkdir()
        (repository / "benchmarks").mkdir()
        (repository / "docs").mkdir()
        # deliberately no target/ directory, as on a clean CI checkout
        for relative, expected in (("benchmarks", BM_UNSAFE_INPUT), ("docs", BM_UNSAFE_INPUT), ("target", BM_FILE_MISSING)):
            with self.subTest(path=relative):
                with self.assertRaises(BenchError) as caught:
                    ExecutionStore.create(
                        repository / relative,
                        EXPERIMENT_ID,
                        str(uuid.uuid4()),
                        evidence_root=self.evidence,
                        repo_root=repository,
                    )
                self.assertEqual(caught.exception.code, expected)
        self.assertEqual(sorted(path.name for path in repository.iterdir()), ["benchmarks", "docs"])

    def test_path_03_links_fifos_and_traversal_are_rejected(self) -> None:
        store = self.store()
        store.write_new("events/00000001.json", _event_document())
        os.mkfifo(store.run_dir / "events" / "pipe")
        with self.assertRaises(BenchError) as caught:
            store.list_existing()
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
        os.unlink(store.run_dir / "events" / "pipe")

        (store.run_dir / "events" / "link.json").symlink_to(
            store.run_dir / "events" / "00000001.json"
        )
        with self.assertRaises(BenchError):
            store.list_existing()
        (store.run_dir / "events" / "link.json").unlink()

        for unsafe in ("events/../../escape.json", "/absolute.json", "events/./x.json", "seal.json"):
            with self.subTest(path=unsafe):
                with self.assertRaises(BenchError):
                    store.write_new(unsafe, _event_document())
        self.assertEqual(store.list_existing(), ("events/00000001.json",))


def _event_document() -> dict:
    return {
        "kind": "synthetic-state-event",
        "schema_version": 1,
        "sequence": 1,
        "from_state": "none",
        "to_state": "planned",
        "reason": "new-run",
        "logical_ns": 0,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
    }

class DescriptorOwnershipTests(StoreTestBase):
    """RF03-04 / INV-F05: every opened descriptor is closed exactly once."""

    def test_fx_fd_01_repeated_creation_never_leaks_descriptors(self) -> None:
        before = fd_count()
        for _ in range(32):
            store = self.store()
            self.assertTrue(store.run_dir.is_dir())
        self.assertEqual(fd_count(), before)

    def test_fx_fd_02_nested_write_does_not_leak_descriptors(self) -> None:
        store = self.store()
        before = fd_count()
        store.write_new("events/nested/one.json", _event_document())
        self.assertEqual(fd_count(), before)
        self.assertEqual(
            store.read_raw("events/nested/one.json"),
            canonical_document_bytes(_event_document()),
        )
        self.assertEqual(fd_count(), before)
        self.assertFalse((store.run_dir / "seal.json").exists())

    def _fsync_spy(self, target_inode: int):
        original_fsync = os.fsync
        calls = {"target": 0}

        def spy(descriptor: int) -> None:
            if os.fstat(descriptor).st_ino == target_inode:
                calls["target"] += 1
                raise OSError(errno.EIO, "simulated fsync failure")
            original_fsync(descriptor)

        return spy, calls

    def test_fx_fd_03_fsync_failure_on_the_experiment_directory_is_typed(self) -> None:
        experiment_dir = self.output / EXPERIMENT_ID
        experiment_dir.mkdir()
        spy, calls = self._fsync_spy(experiment_dir.stat().st_ino)
        before = fd_count()
        with mock.patch("quervant_bench.execution.store.os.fsync", spy):
            with self.assertRaises(BenchError) as caught:
                ExecutionStore.create(
                    self.output,
                    EXPERIMENT_ID,
                    str(uuid.uuid4()),
                    evidence_root=self.evidence,
                    repo_root=repository_root(),
                )
        self.assertEqual(calls["target"], 1)
        self.assertEqual(caught.exception.code, BM_INTERNAL_ERROR)
        self.assertEqual(fd_count(), before)
        run_dirs = [path for path in experiment_dir.iterdir() if path.is_dir()]
        self.assertEqual(len(run_dirs), 1)
        self.assertEqual(
            [path for path in run_dirs[0].rglob("*") if path.is_file()], []
        )
        self.assertFalse((experiment_dir / "seal.json").exists())

    def test_fx_fd_04_fsync_failure_on_the_output_base_is_typed(self) -> None:
        spy, calls = self._fsync_spy(self.output.stat().st_ino)
        before = fd_count()
        with mock.patch("quervant_bench.execution.store.os.fsync", spy):
            with self.assertRaises(BenchError) as caught:
                ExecutionStore.create(
                    self.output,
                    EXPERIMENT_ID,
                    str(uuid.uuid4()),
                    evidence_root=self.evidence,
                    repo_root=repository_root(),
                )
        self.assertEqual(calls["target"], 1)
        self.assertEqual(caught.exception.code, BM_INTERNAL_ERROR)
        self.assertEqual(fd_count(), before)
        experiment_dirs = [path for path in self.output.iterdir()]
        self.assertEqual(len(experiment_dirs), 1)
        run_dirs = [path for path in experiment_dirs[0].iterdir() if path.is_dir()]
        self.assertEqual(len(run_dirs), 1)
        self.assertEqual(
            [path for path in run_dirs[0].rglob("*") if path.is_file()], []
        )

    def test_fx_fd_05_missing_first_child_closes_the_base_descriptor(self) -> None:
        store = self.store()
        before = fd_count()
        with self.assertRaises(BenchError) as caught:
            store._open_directory_chain(("missing-child",), create=False)
        self.assertEqual(caught.exception.code, BM_INTERNAL_ERROR)
        self.assertEqual(fd_count(), before)
        self.assertEqual(list(store.run_dir.iterdir()), [])

    def test_fx_fd_06_missing_second_child_closes_the_opened_parent(self) -> None:
        store = self.store()
        store.write_new("events/one.json", _event_document())
        before = fd_count()
        with self.assertRaises(BenchError) as caught:
            store._open_directory_chain(("events", "missing-child"), create=False)
        self.assertEqual(caught.exception.code, BM_INTERNAL_ERROR)
        self.assertEqual(fd_count(), before)
        self.assertEqual(
            sorted(path.name for path in (store.run_dir / "events").iterdir()),
            ["one.json"],
        )

    def test_fx_fd_07_permission_error_on_a_child_closes_the_parent(self) -> None:
        store = self.store()
        store.write_new("events/one.json", _event_document())
        original_open = os.open

        def spy(path, flags, *args, **kwargs):
            if path == "blocked-child" and kwargs.get("dir_fd") is not None:
                raise PermissionError(errno.EACCES, "simulated permission failure")
            return original_open(path, flags, *args, **kwargs)

        before = fd_count()
        with mock.patch("quervant_bench.execution.store.os.open", spy):
            with self.assertRaises(BenchError) as caught:
                store._open_directory_chain(("events", "blocked-child"), create=False)
        self.assertEqual(caught.exception.code, BM_UNSAFE_INPUT)
        self.assertEqual(fd_count(), before)
        self.assertEqual(
            sorted(path.name for path in (store.run_dir / "events").iterdir()),
            ["one.json"],
        )


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

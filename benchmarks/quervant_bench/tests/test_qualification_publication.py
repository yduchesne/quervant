"""PUB-01…09, PUBL-01…12, E-01…06 — exclusive publication and acyclic attestation.

Publication tests republish a genuinely produced committed bundle (from the real
A→E coordinator) into fresh destinations, and inject exactly one deterministic
``OSError`` at every production I/O boundary through a stateful wrapper around
``OsPublicationIO``. No global ``os`` function is monkeypatched and no in-memory
fake replaces the real filesystem implementation.
"""

from __future__ import annotations

import collections
import copy
import errno
import hashlib
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_INTERNAL_ERROR,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.qualification.contracts import (
    MANIFEST_MEMBERS,
    MEMBER_NAMES,
    PENDING_NAME,
    validate_manifest,
)
from quervant_bench.qualification.publication import (
    ABSENT,
    COMMITTED,
    INCOMPLETE,
    OsPublicationIO,
    destination_state,
    load_bundle,
    publish_bundle,
)
from quervant_bench.tests.test_qualification_contracts import (
    committed_documents,
    load_committed,
    qualified_once,
    read_json,
    rehash_gate_e,
    sealed_run,
    write_bundle_documents,
    write_canonical,
)

EXPERIMENT = "synthetic-analysis-smoke"


def _member_pairs(documents: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [(name, documents[name]) for name in MEMBER_NAMES[:14]]


class FaultIO(OsPublicationIO):
    """Stateful deterministic single-failpoint wrapper around the real boundary."""

    def __init__(self, point: str) -> None:
        self.point = point
        self.calls: collections.Counter[str] = collections.Counter()
        self.directory_fsyncs = 0

    def _boom(self) -> None:
        raise OSError(errno.EIO, f"injected failure at {self.point}")

    def create_directory(self, path: Path) -> None:
        self.calls["mkdir"] += 1
        if self.point == "mkdir-experiment" and self.calls["mkdir"] == 1:
            self._boom()
        if self.point == "mkdir-run" and self.calls["mkdir"] == 2:
            self._boom()
        super().create_directory(path)

    def create_exclusive(self, path: Path) -> int:
        self.calls["open"] += 1
        if path.name == PENDING_NAME and self.point == "pending-open":
            self._boom()
        if self.point == f"open:{self.calls['open']}":
            self._boom()
        return super().create_exclusive(path)

    def write_all(self, descriptor: int, payload: bytes) -> None:
        self.calls["write"] += 1
        index = self.calls["write"]
        if self.point == "pending-write" and index == 15:
            self._boom()
        if self.point == f"write:{index}":
            super().write_all(descriptor, payload[: max(1, len(payload) // 2)])
            self._boom()
        super().write_all(descriptor, payload)

    def fsync_file(self, descriptor: int) -> None:
        self.calls["fsync"] += 1
        index = self.calls["fsync"]
        if self.point == "pending-fsync" and index == 15:
            self._boom()
        if self.point == f"fsync:{index}":
            self._boom()
        super().fsync_file(descriptor)

    def fsync_dir(self, directory: Path) -> None:
        self.directory_fsyncs += 1
        if self.point == "dir-before-marker" and self.directory_fsyncs == 1:
            self._boom()
        if self.point == "dir-after-marker" and self.directory_fsyncs == 2:
            self._boom()
        if self.point == "dir-final" and self.directory_fsyncs == 3:
            self._boom()
        super().fsync_dir(directory)

    def hardlink_no_replace(self, source: Path, destination: Path) -> None:
        if self.point == "hardlink-before":
            self._boom()
        super().hardlink_no_replace(source, destination)
        if self.point == "hardlink-after":
            self._boom()

    def unlink_pending(self, path: Path) -> None:
        if self.point == "unlink":
            self._boom()
        super().unlink_pending(path)


class PublicationTests(unittest.TestCase):
    """PUB-01…09 and E-01…06."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base, cls.result = qualified_once()
        cls.documents = committed_documents()
        cls.members = _member_pairs(cls.documents)
        cls.manifest = cls.documents["manifest.json"]
        cls.run_id = cls.result.run_id
        cls.seal_bytes = (sealed_run().run_dir / "seal.json").read_bytes()

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.base = Path(self._temporary.name) / "results"
        self.base.mkdir()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def publish(self, io: OsPublicationIO | None = None) -> Path:
        return publish_bundle(
            output_base=self.base,
            experiment_id=EXPERIMENT,
            run_id=self.run_id,
            members=self.members,
            manifest=self.manifest,
            io=io,
        )

    def load(self) -> Any:
        return load_bundle(
            output_base=self.base, experiment_id=EXPERIMENT, run_id=self.run_id
        )

    def destination(self) -> Path:
        return self.base / EXPERIMENT / self.run_id

    # -- PUB-01…09 --------------------------------------------------------

    def test_pub_01_exact_inventory_canonical_bytes_and_reload(self) -> None:
        directory = self.publish()
        names = sorted(entry.name for entry in directory.iterdir())
        self.assertEqual(names, sorted(MEMBER_NAMES))
        self.assertFalse((directory / PENDING_NAME).exists())
        for name in MEMBER_NAMES:
            payload = (directory / name).read_bytes()
            self.assertEqual(payload, canonical_document_bytes(read_json(directory / name)))
            self.assertTrue(payload.endswith(b"\n"))
            self.assertLessEqual(len(payload), 1_048_576)
        manifest = validate_manifest(self.documents["manifest.json"])
        for member in manifest["members"]:
            payload = (directory / member["path"]).read_bytes()
            self.assertEqual(member["byte_length"], len(payload))
            self.assertEqual(
                member["digest"],
                "sha256:" + hashlib.sha256(payload[:-1]).hexdigest(),
            )
        loaded = self.load()
        self.assertEqual(loaded.manifest_digest, self.result.manifest_digest)
        self.assertEqual(set(loaded.documents), set(MEMBER_NAMES))
        self.assertEqual(
            destination_state(self.base, EXPERIMENT, self.run_id), COMMITTED
        )
        self.assertEqual((sealed_run().run_dir / "seal.json").read_bytes(), self.seal_bytes)

    def test_pub_02_existing_destination_is_never_overwritten(self) -> None:
        directory = self.publish()
        before = {name: (directory / name).read_bytes() for name in MEMBER_NAMES}
        with self.assertRaises(BenchError) as raised:
            self.publish()
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        for name, payload in before.items():
            self.assertEqual((directory / name).read_bytes(), payload)

    def test_pub_03_symlinked_destination_or_member_is_rejected(self) -> None:
        directory = self.publish()
        (directory / "verification.json").unlink()
        (directory / "verification.json").symlink_to(directory / "analysis.json")
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

        fresh = Path(self._temporary.name) / "linked"
        fresh.mkdir()
        target = Path(self._temporary.name) / "target"
        target.mkdir()
        (fresh / EXPERIMENT).symlink_to(target)
        with self.assertRaises(BenchError) as linked:
            destination_state(fresh, EXPERIMENT, self.run_id)
        self.assertEqual(linked.exception.code, BM_UNSAFE_INPUT)

    def test_pub_04_rehashed_but_byte_flipped_receipt_is_rejected(self) -> None:
        directory = self.publish()
        tampered = copy.deepcopy(read_json(directory / "verification.json"))
        tampered["outputs"][0]["digest"] = "sha256:" + "d" * 64
        payload = {k: v for k, v in tampered.items() if k != "receipt_id"}
        tampered["receipt_id"] = content_digest(payload)
        write_canonical(directory / "verification.json", tampered)
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_pub_05_pending_marker_is_never_accepted(self) -> None:
        directory = self.publish()
        (directory / PENDING_NAME).write_bytes(b"{}\n")
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        self.assertEqual(
            destination_state(self.base, EXPERIMENT, self.run_id), INCOMPLETE
        )

    def test_pub_06_extra_committed_member_is_rejected(self) -> None:
        directory = self.publish()
        (directory / "extra.json").write_bytes(canonical_document_bytes({"kind": "x"}))
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        (directory / "extra.json").unlink()
        (directory / "nested").mkdir()
        with self.assertRaises(BenchError) as nested:
            self.load()
        self.assertEqual(nested.exception.code, BM_PUBLICATION_CONFLICT)

    def test_pub_07_absent_and_partial_destinations_are_not_loadable(self) -> None:
        with self.assertRaises(BenchError) as absent:
            self.load()
        self.assertEqual(absent.exception.code, BM_PUBLICATION_CONFLICT)
        self.assertEqual(
            destination_state(self.base, EXPERIMENT, self.run_id), ABSENT
        )
        (self.base / EXPERIMENT / self.run_id).mkdir(parents=True)
        write_canonical(
            self.base / EXPERIMENT / self.run_id / "admission.json",
            self.documents["admission.json"],
        )
        self.assertEqual(
            destination_state(self.base, EXPERIMENT, self.run_id), INCOMPLETE
        )
        with self.assertRaises(BenchError) as incomplete:
            self.load()
        self.assertEqual(incomplete.exception.code, BM_PUBLICATION_CONFLICT)

    def test_pub_08_manifest_self_hash_and_undeclared_member_are_rejected(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["manifest_digest"] = content_digest(manifest)
        with self.assertRaises(BenchError):
            validate_manifest(manifest)
        snapshot = copy.deepcopy(manifest["freeze_snapshot"])
        snapshot["members"].append(
            {"path": "manifest.json", "byte_length": 1, "digest": "sha256:" + "a" * 64}
        )
        snapshot["members"].sort(key=lambda member: member["path"])
        manifest = copy.deepcopy(self.manifest)
        manifest["freeze_snapshot"] = snapshot
        with self.assertRaises(BenchError):
            validate_manifest(manifest)

    def test_pub_09_two_publishers_have_exactly_one_winner(self) -> None:
        barrier = threading.Barrier(2)
        results: list[Any] = []
        lock = threading.Lock()

        class BarrierIO(OsPublicationIO):
            def create_directory(self, path: Path) -> None:
                if path.name == self.run_id_name:
                    barrier.wait(timeout=5)
                super().create_directory(path)

        barrier_io = BarrierIO()
        barrier_io.run_id_name = self.run_id  # type: ignore[attr-defined]

        def worker() -> None:
            try:
                directory = publish_bundle(
                    output_base=self.base,
                    experiment_id=EXPERIMENT,
                    run_id=self.run_id,
                    members=self.members,
                    manifest=self.manifest,
                    io=barrier_io,
                )
                outcome: Any = ("winner", directory)
            except BenchError as error:
                outcome = ("loser", error.code)
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        winners = [entry for entry in results if entry[0] == "winner"]
        losers = [entry for entry in results if entry[0] == "loser"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        self.assertEqual(losers[0][1], BM_PUBLICATION_CONFLICT)
        self.assertEqual(
            destination_state(self.base, EXPERIMENT, self.run_id), COMMITTED
        )
        self.assertFalse((self.destination() / PENDING_NAME).exists())

    # -- PUBL-01…12 -------------------------------------------------------

    def _assert_failed_publication(self, point: str) -> None:
        io = FaultIO(point)
        with self.assertRaises(BenchError) as raised:
            self.publish(io=io)
        self.assertIn(
            raised.exception.code,
            {BM_INTERNAL_ERROR, BM_PUBLICATION_CONFLICT, BM_UNSAFE_INPUT},
            point,
        )
        state = destination_state(self.base, EXPERIMENT, self.run_id)
        if point == "dir-final":
            # Content is complete; only the last durability barrier failed. The
            # publication still returns a typed non-success and never claims the
            # call completed.
            self.assertEqual(state, COMMITTED, point)
            self.load()
            self.assertFalse((self.destination() / PENDING_NAME).exists(), point)
        else:
            self.assertIn(state, {ABSENT, INCOMPLETE}, point)
            with self.assertRaises(BenchError) as incomplete:
                self.load()
            self.assertEqual(incomplete.exception.code, BM_PUBLICATION_CONFLICT, point)
            manifest_exists = (self.destination() / "manifest.json").exists()
            if point in {"hardlink-after", "dir-after-marker", "unlink"}:
                self.assertTrue(manifest_exists, point)
                self.assertTrue((self.destination() / PENDING_NAME).exists(), point)
            else:
                self.assertFalse(manifest_exists, point)
        self.assertEqual(
            (sealed_run().run_dir / "seal.json").read_bytes(), self.seal_bytes
        )

    def test_publ_01_to_05_directory_and_file_open_failures(self) -> None:
        for point in ("mkdir-experiment", "mkdir-run"):
            with self.subTest(point=point):
                self._temporary.cleanup()
                self._temporary = tempfile.TemporaryDirectory()
                self.base = Path(self._temporary.name) / "results"
                self.base.mkdir()
                self._assert_failed_publication(point)

    def test_publ_03_file_open_failures(self) -> None:
        for index in range(1, 15):
            with self.subTest(index=index):
                self._temporary.cleanup()
                self._temporary = tempfile.TemporaryDirectory()
                self.base = Path(self._temporary.name) / "results"
                self.base.mkdir()
                self._assert_failed_publication(f"open:{index}")

    def test_publ_04_partial_write_failures(self) -> None:
        for index in range(1, 15):
            with self.subTest(index=index):
                self._temporary.cleanup()
                self._temporary = tempfile.TemporaryDirectory()
                self.base = Path(self._temporary.name) / "results"
                self.base.mkdir()
                self._assert_failed_publication(f"write:{index}")

    def test_publ_05_file_fsync_failures(self) -> None:
        for index in range(1, 15):
            with self.subTest(index=index):
                self._temporary.cleanup()
                self._temporary = tempfile.TemporaryDirectory()
                self.base = Path(self._temporary.name) / "results"
                self.base.mkdir()
                self._assert_failed_publication(f"fsync:{index}")

    def test_publ_06_to_11_marker_protocol_failures(self) -> None:
        for point in (
            "dir-before-marker",
            "pending-open",
            "pending-write",
            "pending-fsync",
            "hardlink-before",
            "hardlink-after",
            "dir-after-marker",
            "unlink",
            "dir-final",
        ):
            with self.subTest(point=point):
                self._temporary.cleanup()
                self._temporary = tempfile.TemporaryDirectory()
                self.base = Path(self._temporary.name) / "results"
                self.base.mkdir()
                self._assert_failed_publication(point)

    # -- E-01…06 ----------------------------------------------------------

    def test_e_01_attestation_and_manifest_are_acyclic(self) -> None:
        attestation = self.documents["attestation.json"]
        manifest = self.documents["manifest.json"]
        snapshot = manifest["freeze_snapshot"]
        self.assertEqual(
            attestation["outputs"],
            [{"name": "freeze-snapshot", "digest": content_digest(snapshot)}],
        )
        self.assertNotIn("manifest", [entry["name"] for entry in attestation["dependencies"]])
        self.assertEqual(
            [entry["name"] for entry in attestation["dependencies"]],
            ["acceptance", "admission", "analysis", "framework-qa", "source-qa", "verification"],
        )
        self.assertEqual(
            manifest["attestation_digest"], content_digest(attestation)
        )
        self.assertNotIn("manifest.json", [member["path"] for member in manifest["members"]])
        self.assertEqual(
            [member["path"] for member in manifest["members"]], list(MANIFEST_MEMBERS)
        )
        self.assertEqual(
            [member["path"] for member in snapshot["members"]],
            sorted(MEMBER_NAMES[:13]),
        )
        self.assertNotEqual(content_digest(manifest), content_digest(snapshot))

    def _rewrite_bundle(self, documents: dict[str, dict[str, Any]]) -> None:
        directory = self.publish()
        for name in MEMBER_NAMES:
            write_canonical(directory / name, documents[name])

    def _refresh_manifest_attestation(
        self, documents: dict[str, dict[str, Any]]
    ) -> None:
        manifest = documents["manifest.json"]
        attestation = documents["attestation.json"]
        attestation_payload = canonical_document_bytes(attestation)
        manifest["attestation_digest"] = content_digest(attestation)
        manifest["members"] = [
            (
                {
                    "path": "attestation.json",
                    "byte_length": len(attestation_payload),
                    "digest": content_digest(attestation),
                }
                if member["path"] == "attestation.json"
                else member
            )
            for member in manifest["members"]
        ]

    def test_e_02_stale_attestation_with_matching_manifest_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        attestation = documents["attestation.json"]
        attestation["inputs"] = [
            (
                {**entry, "digest": "sha256:" + "c" * 64}
                if entry["name"] == "source-set"
                else entry
            )
            for entry in attestation["inputs"]
        ]
        payload = {key: value for key, value in attestation.items() if key != "receipt_id"}
        attestation["receipt_id"] = content_digest(payload)
        self._refresh_manifest_attestation(documents)
        self._rewrite_bundle(documents)
        with self.assertRaises(BenchError) as raised:
            load_committed(self.base)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_e_03_manifest_member_digest_tamper_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        manifest = documents["manifest.json"]
        manifest["members"] = [
            (
                {**member, "digest": "sha256:" + "e" * 64}
                if member["path"] == "policy.json"
                else member
            )
            for member in manifest["members"]
        ]
        self._rewrite_bundle(documents)
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_e_04_modified_snapshot_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        manifest = documents["manifest.json"]
        manifest["freeze_snapshot"]["members"][0]["digest"] = "sha256:" + "f" * 64
        self._rewrite_bundle(documents)
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_e_05_forged_manifest_dependency_cycle_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        attestation = documents["attestation.json"]
        manifest_digest = content_digest(documents["manifest.json"])
        attestation["dependencies"].append(
            {
                "name": "manifest",
                "digest": manifest_digest,
                "gate": "acceptance",
                "receipt_id": manifest_digest,
            }
        )
        attestation["dependencies"].sort(key=lambda entry: entry["name"])
        payload = {key: value for key, value in attestation.items() if key != "receipt_id"}
        attestation["receipt_id"] = content_digest(payload)
        self._refresh_manifest_attestation(documents)
        self._rewrite_bundle(documents)
        with self.assertRaises(BenchError) as raised:
            load_committed(self.base)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_e_06_undeclared_pending_or_extra_file_is_rejected(self) -> None:
        directory = self.publish()
        (directory / PENDING_NAME).write_bytes(b"{}\n")
        with self.assertRaises(BenchError) as raised:
            self.load()
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        (directory / PENDING_NAME).unlink()
        shutil.copyfile(directory / "analysis.json", directory / "analysis-copy.json")
        with self.assertRaises(BenchError) as extra:
            self.load()
        self.assertEqual(extra.exception.code, BM_PUBLICATION_CONFLICT)


class GateEIdentityFixupTests(unittest.TestCase):
    """F06-E-01…04 — Gate E must bind the admitted subject and trusted anchors."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base, cls.result = qualified_once()
        cls.documents = committed_documents()
        cls.run_id = cls.result.run_id

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.forged_base = Path(self._temporary.name) / "results"
        self.forged_base.mkdir()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _persist_forged(self, documents: dict[str, Any]) -> None:
        write_bundle_documents(
            self.forged_base, EXPERIMENT, self.run_id, documents
        )

    def _load_forged(self) -> Any:
        return load_bundle(
            output_base=self.forged_base, experiment_id=EXPERIMENT, run_id=self.run_id
        )

    def _expect_semantic_rejection(self, expected_field: str | None = None) -> None:
        # Structural self-consistency must succeed first: only the missing trusted
        # comparison can reject this forged bundle.
        self._load_forged()
        with self.assertRaises(BenchError) as raised:
            load_committed(self.forged_base)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        if expected_field is not None:
            self.assertEqual(raised.exception.field_path, expected_field)

    def test_f06_e_01_ordinary_load_preserves_exact_identities(self) -> None:
        self._persist_forged(copy.deepcopy(self.documents))
        self._load_forged()  # unmodified copy loads structurally
        reused = load_committed(self.forged_base)
        self.assertEqual(reused.disposition, "REUSED_VERIFIED")
        self.assertEqual(reused.manifest_digest, self.result.manifest_digest)
        self.assertEqual(
            reused.attestation_receipt_id,
            self.documents["attestation.json"]["receipt_id"],
        )
        manifest = self.documents["manifest.json"]
        self.assertEqual(
            manifest["subject"], self.documents["admission-index.json"]["subject"]
        )
        self.assertEqual(
            manifest["freeze_snapshot"]["subject"],
            self.documents["admission-index.json"]["subject"],
        )

    def test_f06_e_02_coherently_rehashed_foreign_manifest_subject_is_rejected(self) -> None:
        documents = copy.deepcopy(self.documents)
        foreign = "00000000-0000-4000-8000-000000000011"
        documents["manifest.json"]["subject"]["run_id"] = foreign
        documents["manifest.json"]["freeze_snapshot"]["subject"]["run_id"] = foreign
        rehash_gate_e(documents)
        self._persist_forged(documents)
        self._expect_semantic_rejection("manifest.subject")

    def test_f06_e_03_alternate_valid_subject_fields_are_rejected(self) -> None:
        for field, value in (
            ("experiment_id", "synthetic-analysis-other"),
            ("protocol_digest", "sha256:" + "9" * 64),
            ("workload_digest", "sha256:" + "8" * 64),
        ):
            with self.subTest(field=field):
                self._temporary.cleanup()
                self._temporary = tempfile.TemporaryDirectory()
                self.forged_base = Path(self._temporary.name) / "results"
                self.forged_base.mkdir()
                documents = copy.deepcopy(self.documents)
                documents["manifest.json"]["subject"][field] = value
                documents["manifest.json"]["freeze_snapshot"]["subject"][field] = value
                rehash_gate_e(documents)
                self._persist_forged(documents)
                self._expect_semantic_rejection("manifest.subject")

    def test_f06_e_04_coherently_rehashed_anchor_fields_are_rejected(self) -> None:
        for field in ("profile_digest", "source_set_digest"):
            with self.subTest(field=field):
                self._temporary.cleanup()
                self._temporary = tempfile.TemporaryDirectory()
                self.forged_base = Path(self._temporary.name) / "results"
                self.forged_base.mkdir()
                documents = copy.deepcopy(self.documents)
                forged = "sha256:" + "7" * 64
                documents["manifest.json"][field] = forged
                documents["manifest.json"]["freeze_snapshot"][field] = forged
                rehash_gate_e(documents)
                self._persist_forged(documents)
                self._expect_semantic_rejection(f"manifest.{field}")


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()

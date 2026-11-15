"""STORE-01…STORE-08: exclusive, crash-aware publication and committed loading."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quervant_bench.config.codec import canonical_document_bytes, content_digest
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_INTERNAL_ERROR,
    BM_PUBLICATION_CONFLICT,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.evidence import publication
from quervant_bench.evidence.admission import admit_synthetic
from quervant_bench.evidence.publication import (
    INDEX_NAME,
    PENDING_NAME,
    RECEIPT_NAME,
    load_committed_admission,
    publish_admission,
)

from test_evidence_admission import (
    FIXTURE,
    GOLDEN_SPEC_DIGEST,
    golden_spec,
    verified_locks,
)


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = golden_spec()
        locks = verified_locks(spec)
        with tempfile.TemporaryDirectory() as tmp:
            admit_synthetic(
                spec=spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=FIXTURE,
                output_base=Path(tmp),
                verified_locks=locks,
            )
            cls.index, cls.receipt = load_committed_admission(
                Path(tmp), spec.subject.experiment_id, spec.subject.run_id
            )
        cls.experiment = spec.subject.experiment_id
        cls.run_id = spec.subject.run_id

    def _output(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def _publish(self, output: Path) -> Path:
        return publish_admission(
            output, self.experiment, self.run_id, self.index, self.receipt
        )

    def test_store_01_publishes_exactly_two_canonical_files(self) -> None:
        output = self._output()
        run_dir = self._publish(output)
        self.assertEqual(
            sorted(path.name for path in run_dir.iterdir()),
            [INDEX_NAME, RECEIPT_NAME],
        )
        self.assertEqual(
            (run_dir / INDEX_NAME).read_bytes(), canonical_document_bytes(self.index)
        )
        self.assertEqual(
            (run_dir / RECEIPT_NAME).read_bytes(),
            canonical_document_bytes(self.receipt),
        )
        index, receipt = load_committed_admission(output, self.experiment, self.run_id)
        self.assertEqual(index, self.index)
        self.assertEqual(receipt, self.receipt)

    def test_store_02_collision_never_overwrites(self) -> None:
        output = self._output()
        self._publish(output)
        before = {
            path.name: path.read_bytes()
            for path in (output / self.experiment / self.run_id).iterdir()
        }
        with self.assertRaises(BenchError) as raised:
            self._publish(output)
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)
        after = {
            path.name: path.read_bytes()
            for path in (output / self.experiment / self.run_id).iterdir()
        }
        self.assertEqual(before, after)

    def test_store_03_failure_before_index_leaves_no_pass(self) -> None:
        output = self._output()
        with mock.patch.object(
            publication,
            "_write_exclusive",
            side_effect=BenchError(BM_INTERNAL_ERROR, "injected"),
        ):
            with self.assertRaises(BenchError):
                self._publish(output)
        run_dir = output / self.experiment / self.run_id
        self.assertTrue(run_dir.is_dir())
        self.assertFalse((run_dir / RECEIPT_NAME).exists())
        with self.assertRaises(BenchError) as raised:
            load_committed_admission(output, self.experiment, self.run_id)
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)

    def test_store_04_failure_between_index_and_receipt_leaves_no_pass(self) -> None:
        output = self._output()
        original = publication._write_exclusive
        calls = {"count": 0}

        def failing(path, payload):
            calls["count"] += 1
            if calls["count"] >= 2:
                raise BenchError(BM_INTERNAL_ERROR, "injected receipt failure")
            return original(path, payload)

        with mock.patch.object(publication, "_write_exclusive", side_effect=failing):
            with self.assertRaises(BenchError):
                self._publish(output)
        run_dir = output / self.experiment / self.run_id
        self.assertTrue((run_dir / INDEX_NAME).exists())
        self.assertFalse((run_dir / RECEIPT_NAME).exists())
        with self.assertRaises(BenchError):
            load_committed_admission(output, self.experiment, self.run_id)

    def test_store_05_failure_during_staging_fsync_or_cleanup(self) -> None:
        # Failure before the completion link leaves an invalid staging file.
        output = self._output()
        calls = {"count": 0}
        original_fsync = publication._fsync_file

        def failing_fsync(descriptor):
            calls["count"] += 1
            if calls["count"] >= 2:
                raise OSError("injected fsync failure")
            return original_fsync(descriptor)

        with mock.patch.object(publication, "_fsync_file", side_effect=failing_fsync):
            with self.assertRaises(BenchError):
                self._publish(output)
        run_dir = output / self.experiment / self.run_id
        self.assertFalse((run_dir / RECEIPT_NAME).exists())
        self.assertTrue((run_dir / PENDING_NAME).exists())
        with self.assertRaises(BenchError) as raised:
            load_committed_admission(output, self.experiment, self.run_id)
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)

        # Failure after the link but before pending cleanup still invalidates it.
        output = self._output()
        with mock.patch.object(
            publication.os, "unlink", side_effect=OSError("injected unlink failure")
        ):
            with self.assertRaises(BenchError):
                self._publish(output)
        run_dir = output / self.experiment / self.run_id
        self.assertTrue((run_dir / RECEIPT_NAME).exists())
        self.assertTrue((run_dir / PENDING_NAME).exists())
        with self.assertRaises(BenchError) as raised:
            load_committed_admission(output, self.experiment, self.run_id)
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)

    def test_store_06_symlinked_output_base_or_experiment_is_rejected(self) -> None:
        real = self._output()
        alias = real / "alias"
        os.symlink(real, alias)
        with self.assertRaises(BenchError) as raised:
            self._publish(alias)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

        output = self._output()
        target = self._output()
        os.symlink(target, output / self.experiment)
        with self.assertRaises(BenchError) as raised:
            self._publish(output)
        self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_store_07_extra_committed_file_is_rejected(self) -> None:
        output = self._output()
        run_dir = self._publish(output)
        (run_dir / "pass.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(BenchError) as raised:
            load_committed_admission(output, self.experiment, self.run_id)
        self.assertEqual(raised.exception.code, BM_PUBLICATION_CONFLICT)

    def test_store_08_repeated_loading_writes_nothing(self) -> None:
        output = self._output()
        run_dir = self._publish(output)
        before = {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
            for path in run_dir.iterdir()
        }
        first = load_committed_admission(output, self.experiment, self.run_id)
        second = load_committed_admission(output, self.experiment, self.run_id)
        after = {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
            for path in run_dir.iterdir()
        }
        self.assertEqual(first, second)
        self.assertEqual(before, after)

    def test_store_noncanonical_committed_bytes_are_rejected(self) -> None:
        output = self._output()
        run_dir = self._publish(output)
        index_path = run_dir / INDEX_NAME
        index_path.write_text(
            json.dumps(self.index, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaises(BenchError) as raised:
            load_committed_admission(output, self.experiment, self.run_id)
        self.assertEqual(raised.exception.code, "BM_UNSAFE_INPUT")




    def test_root_06_08_direct_publication_to_protected_repository_paths(self) -> None:
        repository = Path(__file__).resolve().parents[3]
        protected = [
            repository / "benchmarks",
            repository / "docs",
            repository,
        ]
        if (repository / "target").exists():
            protected.append(repository / "target")
        for output in protected:
            with self.subTest(output=str(output)):
                with mock.patch.object(publication.os, "mkdir") as make_directory:
                    with self.assertRaises(BenchError) as raised:
                        self._publish(output)
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
                make_directory.assert_not_called()
                with self.assertRaises(BenchError) as raised:
                    load_committed_admission(
                        output, self.experiment, self.run_id
                    )
                self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)

    def test_root_10_external_output_still_publishes_and_loads(self) -> None:
        output = self._output()
        run_dir = self._publish(output)
        self.assertEqual(
            sorted(path.name for path in run_dir.iterdir()),
            [INDEX_NAME, RECEIPT_NAME],
        )
        loaded = load_committed_admission(output, self.experiment, self.run_id)
        self.assertEqual(loaded, (self.index, self.receipt))

    def test_err_01_to_03_invalid_receipt_outputs_are_typed(self) -> None:
        mutations = {
            "empty": lambda receipt: receipt.__setitem__("outputs", []),
            "name": lambda receipt: receipt["outputs"][0].__setitem__(
                "name", "incorrect-index"
            ),
            "digest": lambda receipt: receipt["outputs"][0].__setitem__(
                "digest", "sha256:" + "0" * 64
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label):
                output = self._output()
                run_dir = self._publish(output)
                receipt_path = run_dir / RECEIPT_NAME
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                mutate(receipt)
                payload = {
                    key: value
                    for key, value in receipt.items()
                    if key != "receipt_id"
                }
                receipt["receipt_id"] = content_digest(payload)
                receipt_path.write_bytes(canonical_document_bytes(receipt))
                before = {
                    path.name: path.read_bytes() for path in run_dir.iterdir()
                }
                with self.assertRaises(BenchError) as raised:
                    load_committed_admission(output, self.experiment, self.run_id)
                self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
                after = {
                    path.name: path.read_bytes() for path in run_dir.iterdir()
                }
                self.assertEqual(before, after)

    def test_err_04_valid_receipt_still_loads(self) -> None:
        output = self._output()
        self._publish(output)
        index, receipt = load_committed_admission(
            output, self.experiment, self.run_id
        )
        self.assertEqual(index, self.index)
        self.assertEqual(receipt, self.receipt)


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()

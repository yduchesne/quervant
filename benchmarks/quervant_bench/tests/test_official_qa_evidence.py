"""RF09-09 / QAE: every mandated QA check needs its executed artifact and log."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from quervant_bench.official import contracts, qa_evidence
from quervant_bench.tests import official_support as support


class ExecutedQaEvidenceTests(unittest.TestCase):
    """The reader validates 33 check records and 33 raw logs, twice."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.bundle = support.qa_evidence_sandbox(cls.root)
        cls.freeze = cls.bundle.freeze

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _verify(self, *, root: Path | None = None, framework=None, source=None):
        return qa_evidence.verify_executed_qa_evidence(
            qa_evidence_root=root or self.bundle.root,
            framework_summary=framework or self.bundle.framework_summary,
            source_summary=source or self.bundle.source_summary,
            freeze=self.freeze,
            output_root=self.root / "output",
            raw_root=self.bundle.raw_root,
        )

    def test_qae_01_complete_evidence_verifies_and_returns_66_member_snapshot(self) -> None:
        snapshot = self._verify()
        self.assertEqual(len(snapshot), 66)
        self.assertEqual(
            list(snapshot), sorted(snapshot)
        )

    def test_qae_02_missing_roster_record_is_rejected(self) -> None:
        path = self.bundle.root / "framework-qa" / "python-full-suite.json"
        original = path.read_bytes()
        try:
            path.unlink()
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        finally:
            path.write_bytes(original)

    def test_qae_04_missing_check_record_blocks(self) -> None:
        path = self.bundle.root / "source-qa" / "rust-coverage-85.json"
        original = path.read_bytes()
        try:
            path.unlink()
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)

    def test_qae_05_changed_check_record_is_rejected(self) -> None:
        path = self.bundle.root / "framework-qa" / "python-mutations.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["job_name"] = "rust"
            support.write_json(path, document)
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_qae_07_empty_log_is_rejected(self) -> None:
        path = self.bundle.root / "logs" / "framework-qa" / "python-full-suite.log"
        original = path.read_bytes()
        try:
            path.write_bytes(b"")
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_EVIDENCE_UNAVAILABLE)
        finally:
            path.write_bytes(original)

    def test_qae_08_symlinked_log_is_rejected(self) -> None:
        path = self.bundle.root / "logs" / "source-qa" / "rust-doc.log"
        original = path.read_bytes()
        target = self.root.parent / "outside-qa-root.log"
        target.write_bytes(original)
        try:
            path.unlink()
            os.symlink(target, path)
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_UNSAFE_INPUT)
        finally:
            path.unlink()
            path.write_bytes(original)
            target.unlink()

    def test_qae_09_changed_log_bytes_are_rejected(self) -> None:
        path = self.bundle.root / "logs" / "framework-qa" / "benchmark-scripts.log"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"tampered\n")
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_qae_10_coherently_rehashed_record_and_log_still_fail_the_pin(self) -> None:
        record_path = self.bundle.root / "framework-qa" / "cross-engine-l2.json"
        log_path = self.bundle.root / "logs" / "framework-qa" / "cross-engine-l2.log"
        record_original = record_path.read_bytes()
        log_original = log_path.read_bytes()
        try:
            log_path.write_bytes(log_original + b"coherent tamper\n")
            record = support.read_json(record_path)
            record["log_raw_sha256"] = (
                "sha256:" + __import__("hashlib").sha256(log_path.read_bytes()).hexdigest()
            )
            support.write_json(record_path, record)
            with self.assertRaises(BenchError) as raised:
                self._verify()
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            record_path.write_bytes(record_original)
            log_path.write_bytes(log_original)

    def test_qae_13_wrong_job_identity_is_rejected(self) -> None:
        path = self.bundle.root / "source-qa" / "rust-fmt-msrv.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["job_name"] = "rust"
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)

    def test_qae_14_nonzero_exit_code_is_rejected(self) -> None:
        path = self.bundle.root / "framework-qa" / "python-compileall.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["command_exit_code"] = 1
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)

    def test_qae_15_boolean_flag_is_rejected(self) -> None:
        path = self.bundle.root / "framework-qa" / "retained-key-l2.json"
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document["failed"] = False
            support.write_json(path, document)
            with self.assertRaises(BenchError):
                self._verify()
        finally:
            path.write_bytes(original)

    def test_qae_18_unapproved_summary_pin_is_rejected(self) -> None:
        document = copy.deepcopy(dict(self.bundle.framework_summary))
        document["checks"][0]["evidence_digest"] = "sha256:" + "9" * 64
        with self.assertRaises(BenchError) as raised:
            self._verify(framework=document)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_qae_19_reverify_detects_post_gate_change(self) -> None:
        snapshot = self._verify()
        path = self.bundle.root / "logs" / "source-qa" / "rust-test-stable-default.log"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"late\n")
            with self.assertRaises(BenchError) as raised:
                qa_evidence.reverify_executed_qa_evidence(
                    qa_evidence_root=self.bundle.root,
                    expected_snapshot=snapshot,
                    framework_summary=self.bundle.framework_summary,
                    source_summary=self.bundle.source_summary,
                    freeze=self.freeze,
                    output_root=self.root / "output",
                    raw_root=self.bundle.raw_root,
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        finally:
            path.write_bytes(original)

    def test_qae_20_unsafe_evidence_root_is_rejected(self) -> None:
        with self.assertRaises(BenchError) as raised:
            qa_evidence.verify_executed_qa_evidence(
                qa_evidence_root=support.REPO_ROOT / "target" / "bm09-venv",
                framework_summary=self.bundle.framework_summary,
                source_summary=self.bundle.source_summary,
                freeze=self.freeze,
                output_root=self.root / "output",
                raw_root=self.bundle.raw_root,
            )
        self.assertIn(raised.exception.code, (BM_UNSAFE_INPUT, BM_EVIDENCE_UNAVAILABLE))


class RosterMappingTests(unittest.TestCase):
    def test_qae_21_job_map_covers_both_rosters_exactly(self) -> None:
        mapping = qa_evidence.GATE_CHECK_EXECUTORS
        framework = {key for (gate, key) in mapping if gate == "framework-qa"}
        source = {key for (gate, key) in mapping if gate == "source-qa"}
        self.assertEqual(framework, set(contracts.FRAMEWORK_QA_ROSTER))
        self.assertEqual(source, set(contracts.SOURCE_QA_ROSTER))
        self.assertEqual(len(framework), 15)
        self.assertEqual(len(source), 18)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()


class ExecutedQaProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        cls.bundle = support.qa_evidence_sandbox(cls.root / "qa")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _verify(self, *, root: Path | None = None):
        return qa_evidence.verify_executed_qa_evidence(
            qa_evidence_root=root or self.bundle.root,
            framework_summary=self.bundle.framework_summary,
            source_summary=self.bundle.source_summary,
            freeze=self.bundle.freeze,
            output_root=self.root / "output",
            raw_root=self.bundle.raw_root,
        )

    def _mutate(self, relative: str, field: str, value):
        path = self.bundle.root / relative
        original = path.read_bytes()
        try:
            document = support.read_json(path)
            document[field] = value
            support.write_json(path, document)
            with self.assertRaises(BenchError) as raised:
                self._verify()
            return raised.exception.code
        finally:
            path.write_bytes(original)

    def test_qae_12_wrong_source_commit_is_rejected(self) -> None:
        code = self._mutate("framework-qa/python-full-suite.json", "source_commit", "b" * 40)
        self.assertEqual(code, BM_IDENTITY_INVALID)

    def test_qae_12b_wrong_source_set_is_rejected(self) -> None:
        code = self._mutate(
            "framework-qa/python-full-suite.json", "source_set_digest", "sha256:" + "3" * 64
        )
        self.assertEqual(code, BM_IDENTITY_INVALID)

    def test_qae_13b_fake_hosted_url_is_rejected(self) -> None:
        code = self._mutate(
            "framework-qa/benchmark-scripts.json",
            "execution_reference",
            "https://github.com/yduchesne/quervant/actions/runs/0",
        )
        self.assertEqual(code, BM_IDENTITY_INVALID)

    def test_qae_13c_operator_check_labelled_hosted_is_rejected(self) -> None:
        code = self._mutate(
            "framework-qa/official-g0-review.json", "executor", "hosted-ci"
        )
        self.assertEqual(code, BM_IDENTITY_INVALID)

    def test_qae_15b_non_executed_check_is_rejected(self) -> None:
        code = self._mutate("framework-qa/python-mutations.json", "executed", 1)
        self.assertIn(code, (BM_IDENTITY_INVALID, "BM_SCHEMA_INVALID"))

    def test_qae_17_reverify_accepts_an_unchanged_snapshot(self) -> None:
        snapshot = self._verify()
        qa_evidence.reverify_executed_qa_evidence(
            qa_evidence_root=self.bundle.root,
            expected_snapshot=snapshot,
            framework_summary=self.bundle.framework_summary,
            source_summary=self.bundle.source_summary,
            freeze=self.bundle.freeze,
            output_root=self.root / "output",
            raw_root=self.bundle.raw_root,
        )

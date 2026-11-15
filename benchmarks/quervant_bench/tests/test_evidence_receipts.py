"""REUSE-07 and receipt binding: v1 admission receipt construction/verification."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import content_digest
from quervant_bench.config.contracts import validate_receipt
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BenchError
from quervant_bench.evidence.admission import admit_synthetic
from quervant_bench.evidence.manifests import validate_admission_index
from quervant_bench.evidence.publication import load_committed_admission
from quervant_bench.evidence.receipts import (
    build_admission_receipt,
    require_verified_locks,
    verify_admission_receipt,
)

from test_evidence_admission import (
    FIXTURE,
    GOLDEN_SPEC_DIGEST,
    golden_spec,
    verified_locks,
)


def _recompute(document: dict) -> dict:
    payload = {key: value for key, value in document.items() if key != "receipt_id"}
    document["receipt_id"] = content_digest(payload)
    return document


class ReceiptConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = golden_spec()
        cls.locks = verified_locks(cls.spec)
        cls._temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls._temporary.name)
        admit_synthetic(
            spec=cls.spec,
            spec_expected_digest=GOLDEN_SPEC_DIGEST,
            evidence_root=FIXTURE,
            output_base=cls.output,
            verified_locks=cls.locks,
        )
        cls.index, cls.receipt = load_committed_admission(
            cls.output, cls.spec.subject.experiment_id, cls.spec.subject.run_id
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_build_reproduces_the_committed_receipt(self) -> None:
        built = build_admission_receipt(
            self.index, self.spec, GOLDEN_SPEC_DIGEST, self.locks
        )
        self.assertEqual(built, self.receipt)
        validate_receipt(built)
        self.assertEqual(built["gate"], "admission")
        self.assertEqual(built["status"], "pass")
        self.assertEqual(built["dependencies"], [])
        input_names = [entry["name"] for entry in built["inputs"]]
        self.assertEqual(input_names, sorted(input_names))
        self.assertEqual(len(input_names), len(set(input_names)))

    def test_build_rejects_wrong_anchor_and_bad_locks(self) -> None:
        with self.assertRaises(BenchError):
            build_admission_receipt(
                self.index, self.spec, "sha256:" + "0" * 64, self.locks
            )
        missing = dict(self.locks)
        missing.pop("build-lock")
        with self.assertRaises(BenchError):
            build_admission_receipt(
                self.index, self.spec, GOLDEN_SPEC_DIGEST, missing
            )
        extra = dict(self.locks)
        extra["unexpected-lock"] = "sha256:" + "1" * 64
        with self.assertRaises(BenchError):
            build_admission_receipt(
                self.index, self.spec, GOLDEN_SPEC_DIGEST, extra
            )
        changed = dict(self.locks)
        changed["build-lock"] = "sha256:" + "2" * 64
        with self.assertRaises(BenchError):
            build_admission_receipt(
                self.index, self.spec, GOLDEN_SPEC_DIGEST, changed
            )

    def test_build_rejects_index_locks_that_do_not_match_spec(self) -> None:
        tampered = json.loads(json.dumps(self.index))
        tampered["locks"][0]["digest"] = "sha256:" + "3" * 64
        with self.assertRaises(BenchError):
            build_admission_receipt(
                tampered, self.spec, GOLDEN_SPEC_DIGEST, self.locks
            )


class ReceiptVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = golden_spec()
        cls.locks = verified_locks(cls.spec)
        cls._temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls._temporary.name)
        admit_synthetic(
            spec=cls.spec,
            spec_expected_digest=GOLDEN_SPEC_DIGEST,
            evidence_root=FIXTURE,
            output_base=cls.output,
            verified_locks=cls.locks,
        )
        cls.index, cls.receipt = load_committed_admission(
            cls.output, cls.spec.subject.experiment_id, cls.spec.subject.run_id
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _verify(self, receipt, index=None):
        return verify_admission_receipt(
            receipt,
            self.index if index is None else index,
            self.spec,
            GOLDEN_SPEC_DIGEST,
            self.locks,
        )

    def test_verify_accepts_the_committed_receipt(self) -> None:
        verified = self._verify(self.receipt)
        self.assertEqual(verified.gate, "admission")
        self.assertEqual(verified.status, "pass")
        self.assertEqual(len(verified.inputs), 21)

    def test_verify_rejects_wrong_anchor(self) -> None:
        with self.assertRaises(BenchError) as raised:
            verify_admission_receipt(
                self.receipt,
                self.index,
                self.spec,
                "sha256:" + "4" * 64,
                self.locks,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_verify_rejects_incomplete_inputs(self) -> None:
        forged = json.loads(json.dumps(self.receipt))
        forged["inputs"].pop()
        _recompute(forged)
        with self.assertRaises(BenchError):
            self._verify(forged)

    def test_verify_rejects_extra_inputs(self) -> None:
        forged = json.loads(json.dumps(self.receipt))
        forged["inputs"].append({"name": "zzz-extra", "digest": "sha256:" + "5" * 64})
        _recompute(forged)
        with self.assertRaises(BenchError):
            self._verify(forged)

    def test_verify_rejects_wrong_validator_policy_or_qa(self) -> None:
        mutations = {
            "validator_version": lambda doc: doc["validator"].__setitem__("validator_version", 2),
            "validator_source": lambda doc: doc["validator"].__setitem__(
                "source_digest", "sha256:" + "6" * 64
            ),
            "policy": lambda doc: doc.__setitem__("policy_digest", "sha256:" + "7" * 64),
            "qa": lambda doc: doc.__setitem__("qa_roster_digest", "sha256:" + "8" * 64),
            "subject": lambda doc: doc["subject"].__setitem__(
                "workload_digest", "sha256:" + "9" * 64
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(mutation=label):
                forged = json.loads(json.dumps(self.receipt))
                mutate(forged)
                _recompute(forged)
                with self.assertRaises(BenchError):
                    self._verify(forged)

    def test_verify_rejects_non_admission_gate_or_status(self) -> None:
        for field, value in (("gate", "source-qa"), ("status", "fail"), ("status", "blocked")):
            with self.subTest(field=field, value=value):
                forged = json.loads(json.dumps(self.receipt))
                forged[field] = value
                _recompute(forged)
                with self.assertRaises(BenchError):
                    self._verify(forged)

    def test_verify_rejects_dependencies_and_bad_outputs(self) -> None:
        forged = json.loads(json.dumps(self.receipt))
        forged["dependencies"] = [
            {
                "name": "framework-qa",
                "digest": "sha256:" + "a" * 64,
                "gate": "framework-qa",
                "receipt_id": "sha256:" + "a" * 64,
            }
        ]
        _recompute(forged)
        with self.assertRaises(BenchError):
            self._verify(forged)

        forged = json.loads(json.dumps(self.receipt))
        forged["outputs"][0]["digest"] = "sha256:" + "b" * 64
        _recompute(forged)
        with self.assertRaises(BenchError):
            self._verify(forged)

    def test_verify_rejects_changed_index(self) -> None:
        tampered = json.loads(json.dumps(self.index))
        tampered["files"][0]["digest"] = "sha256:" + "c" * 64
        with self.assertRaises(BenchError):
            self._verify(self.receipt, index=tampered)

    def test_verify_rejects_forged_receipt_id(self) -> None:
        forged = json.loads(json.dumps(self.receipt))
        forged["receipt_id"] = "sha256:" + "d" * 64
        with self.assertRaises(BenchError):
            self._verify(forged)

    def test_require_verified_locks_is_closed(self) -> None:
        with self.assertRaises(BenchError):
            require_verified_locks(self.spec, {})
        with self.assertRaises(BenchError):
            require_verified_locks(
                self.spec, {**self.locks, "extra-lock": "sha256:" + "e" * 64}
            )
        self.assertEqual(require_verified_locks(self.spec, self.locks), self.locks)


class AdmissionIndexShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = golden_spec()
        self.locks = verified_locks(self.spec)
        with tempfile.TemporaryDirectory() as tmp:
            admit_synthetic(
                spec=self.spec,
                spec_expected_digest=GOLDEN_SPEC_DIGEST,
                evidence_root=FIXTURE,
                output_base=Path(tmp),
                verified_locks=self.locks,
            )
            self.index, _receipt = load_committed_admission(
                Path(tmp), self.spec.subject.experiment_id, self.spec.subject.run_id
            )

    def test_index_rejects_extra_or_missing_fields(self) -> None:
        extra = json.loads(json.dumps(self.index))
        extra["timestamp"] = "2026-01-01T00:00:00Z"
        with self.assertRaises(BenchError):
            validate_admission_index(extra)
        missing = json.loads(json.dumps(self.index))
        missing.pop("locks")
        with self.assertRaises(BenchError):
            validate_admission_index(missing)

    def test_index_rejects_non_synthetic_scope(self) -> None:
        forged = json.loads(json.dumps(self.index))
        forged["evidence_origin"] = "real"
        forged["qualification_scope"] = "official"
        with self.assertRaises(BenchError):
            validate_admission_index(forged)

    def test_index_rejects_absolute_paths(self) -> None:
        forged = json.loads(json.dumps(self.index))
        forged["files"][0]["path"] = "/absolute/evidence.json"
        with self.assertRaises(BenchError):
            validate_admission_index(forged)


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()

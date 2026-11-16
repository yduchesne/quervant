"""QA-01…10 — pinned framework/source QA evidence, rosters and receipts.

The fixtures are *simulated* QA assertions of the qualification mechanism. They do
not prove that any named program ran or that CI passed, and no test here may claim
that. Every mutation recomputes its own document self-digest so only the pinned
anchor, roster, per-check bytes or semantic binding can reject it.
"""

from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from quervant_bench.config.codec import content_digest
from quervant_bench.config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BenchError,
)
from quervant_bench.qualification import qa
from quervant_bench.qualification.contracts import (
    FRAMEWORK_QA_ROSTER,
    SOURCE_QA_ROSTER,
    validate_qa_evidence,
)
from quervant_bench.tests.test_qualification_contracts import (
    FIXTURES,
    read_json,
    trust_anchors,
    write_canonical,
)

_DEFAULT = object()

SUBJECT = {
    "experiment_id": "synthetic-analysis-smoke",
    "run_id": "00000000-0000-4000-8000-000000000020",
    "protocol_digest": "sha256:" + "1" * 64,
    "workload_digest": "sha256:" + "2" * 64,
}


class QaTests(unittest.TestCase):
    """QA-01…10."""

    def setUp(self) -> None:
        self.anchors = trust_anchors()
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name) / "qa"
        shutil.copytree(FIXTURES, self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    # -- helpers ----------------------------------------------------------

    def _evidence(self, gate: str) -> dict[str, Any]:
        return read_json(self.root / f"{gate}-evidence.json")

    def _read(self, gate: str, *, anchor: Any = _DEFAULT) -> Any:
        expected = (
            self.anchors[gate.replace("-", "_") + "_digest"]
            if anchor is _DEFAULT
            else anchor
        )
        return qa.read_qa_evidence(
            qa_evidence_root=self.root,
            gate=gate,
            expected_document_digest=expected,
            profile_digest=self.anchors["profile_digest"],
            source_set_digest=self.anchors["source_set_digest"],
        )

    def _rewrite(self, gate: str, document: dict[str, Any]) -> str:
        write_canonical(self.root / f"{gate}-evidence.json", document)
        return content_digest(document)

    def _expect(self, code: str, callable_: Any) -> None:
        with self.assertRaises(BenchError) as raised:
            callable_()
        self.assertEqual(raised.exception.code, code)

    # -- cases ------------------------------------------------------------

    def test_qa_01_exact_pinned_rosters_are_accepted_and_receipted(self) -> None:
        framework, framework_digest = self._read("framework-qa")
        source, source_digest = self._read("source-qa")
        self.assertEqual(
            tuple(check["check_id"] for check in framework["checks"]),
            FRAMEWORK_QA_ROSTER,
        )
        self.assertEqual(
            tuple(check["check_id"] for check in source["checks"]),
            SOURCE_QA_ROSTER,
        )
        for gate, evidence, evidence_digest in (
            ("framework-qa", framework, framework_digest),
            ("source-qa", source, source_digest),
        ):
            receipt = qa.build_qa_receipt(
                gate=gate,
                subject=SUBJECT,
                evidence_document=evidence,
                evidence_digest=evidence_digest,
                profile_digest=self.anchors["profile_digest"],
                source_set_digest=self.anchors["source_set_digest"],
            )
            qa.verify_qa_receipt(
                gate=gate,
                receipt_document=receipt,
                subject=SUBJECT,
                evidence_document=evidence,
                evidence_digest=evidence_digest,
                profile_digest=self.anchors["profile_digest"],
                source_set_digest=self.anchors["source_set_digest"],
            )

    def test_qa_02_missing_check_is_rejected(self) -> None:
        document = self._evidence("framework-qa")
        del document["checks"][-1]
        anchor = self._rewrite("framework-qa", document)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa", anchor=anchor))

    def test_qa_03_duplicate_check_is_rejected(self) -> None:
        document = self._evidence("framework-qa")
        document["checks"].append(copy.deepcopy(document["checks"][0]))
        anchor = self._rewrite("framework-qa", document)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa", anchor=anchor))

    def test_qa_04_reordered_roster_is_rejected(self) -> None:
        document = self._evidence("framework-qa")
        document["checks"].reverse()
        anchor = self._rewrite("framework-qa", document)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa", anchor=anchor))

    def test_qa_05_extra_unknown_check_is_rejected(self) -> None:
        document = self._evidence("source-qa")
        document["checks"][-1]["check_id"] = "rust-extra"
        anchor = self._rewrite("source-qa", document)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("source-qa", anchor=anchor))

    def test_qa_06_passed_but_not_executed_is_rejected(self) -> None:
        document = self._evidence("framework-qa")
        document["checks"][0]["executed"] = False
        anchor = self._rewrite("framework-qa", document)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa", anchor=anchor))

    def test_qa_07_failed_blocked_skipped_are_rejected(self) -> None:
        for index, field, value in (
            (0, ("status", "fail"), None),
            (0, ("status", "blocked"), None),
            (0, ("status", "not-executed"), None),
            (0, ("failed", 1), None),
            (1, ("mandatory_skipped", 1), None),
        ):
            document = self._evidence("framework-qa")
            key, setting = field
            document["checks"][index][key] = value if setting is None else setting
            anchor = self._rewrite("framework-qa", document)
            self._expect(
                BM_IDENTITY_INVALID, lambda anchor=anchor: self._read("framework-qa", anchor=anchor)
            )

    def test_qa_08_missing_stale_or_weak_anchor_is_rejected(self) -> None:
        for anchor in ("", None, "sha256:" + "0" * 64):
            expected_code = (
                BM_EVIDENCE_UNAVAILABLE
                if anchor in ("", None)
                else BM_IDENTITY_INVALID
            )
            self._expect(
                expected_code,
                lambda anchor=anchor: self._read("framework-qa", anchor=anchor),
            )
        # A public gate document rehashed to a new self-digest still fails the anchor.
        document = self._evidence("framework-qa")
        document["checks"][0]["failed"] = 0
        document["toolchain_id"] = "python-3-13"
        anchor = self._rewrite("framework-qa", document)
        self._expect(
            BM_IDENTITY_INVALID, lambda: self._read("framework-qa", anchor=self.anchors["framework_qa_digest"])
        )

    def test_qa_09_toolchain_and_source_drift_are_rejected(self) -> None:
        document = self._evidence("source-qa")
        document["toolchain_id"] = "rust-1-86-and-1-99"
        anchor = self._rewrite("source-qa", document)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("source-qa", anchor=anchor))

        document = self._evidence("source-qa")
        document["source_set_digest"] = "sha256:" + "3" * 64
        anchor = self._rewrite("source-qa", document)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("source-qa", anchor=anchor))

        document = self._evidence("framework-qa")
        document["profile_digest"] = "sha256:" + "4" * 64
        anchor = self._rewrite("framework-qa", document)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa", anchor=anchor))

    def test_qa_10_per_check_record_tampering_is_rejected(self) -> None:
        # Missing record.
        (self.root / "framework-qa" / "python-vertical.json").unlink()
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa"))
        shutil.copyfile(
            FIXTURES / "framework-qa" / "python-vertical.json",
            self.root / "framework-qa" / "python-vertical.json",
        )
        # Extra record.
        shutil.copyfile(
            self.root / "framework-qa" / "python-vertical.json",
            self.root / "framework-qa" / "python-extra.json",
        )
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa"))
        (self.root / "framework-qa" / "python-extra.json").unlink()
        # Mutated record bytes without a summary update.
        record_path = self.root / "framework-qa" / "python-contracts.json"
        record = read_json(record_path)
        record["failed"] = 1
        write_canonical(record_path, record)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa"))
        # Mutated record with a matching summary digest still fails the record shape.
        write_canonical(record_path, read_json(FIXTURES / "framework-qa" / "python-contracts.json"))
        evidence = self._evidence("framework-qa")
        evidence["checks"][0]["evidence_digest"] = content_digest(record)
        anchor = self._rewrite("framework-qa", evidence)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa", anchor=anchor))
        # Wrong gate/check identity in the record.
        write_canonical(record_path, read_json(FIXTURES / "framework-qa" / "python-contracts.json"))
        record = read_json(record_path)
        record["check_id"] = "python-mutations"
        write_canonical(record_path, record)
        evidence = self._evidence("framework-qa")
        evidence["checks"][0]["evidence_digest"] = content_digest(record)
        anchor = self._rewrite("framework-qa", evidence)
        self._expect(BM_IDENTITY_INVALID, lambda: self._read("framework-qa", anchor=anchor))

    def test_qa_11_cross_gate_or_foreign_run_receipt_is_rejected(self) -> None:
        framework, framework_digest = self._read("framework-qa")
        receipt = qa.build_qa_receipt(
            gate="framework-qa",
            subject=SUBJECT,
            evidence_document=framework,
            evidence_digest=framework_digest,
            profile_digest=self.anchors["profile_digest"],
            source_set_digest=self.anchors["source_set_digest"],
        )
        with self.assertRaises(BenchError):
            qa.verify_qa_receipt(
                gate="source-qa",
                receipt_document=receipt,
                subject=SUBJECT,
                evidence_document=framework,
                evidence_digest=framework_digest,
                profile_digest=self.anchors["profile_digest"],
                source_set_digest=self.anchors["source_set_digest"],
            )
        foreign_subject = {**SUBJECT, "run_id": "00000000-0000-4000-8000-000000000021"}
        with self.assertRaises(BenchError) as raised:
            qa.verify_qa_receipt(
                gate="framework-qa",
                receipt_document=receipt,
                subject=foreign_subject,
                evidence_document=framework,
                evidence_digest=framework_digest,
                profile_digest=self.anchors["profile_digest"],
                source_set_digest=self.anchors["source_set_digest"],
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_qa_12_unsafe_root_is_rejected(self) -> None:
        self._expect(
            BM_FILE_MISSING,
            lambda: qa.read_qa_evidence(
                qa_evidence_root=Path("/does/not/exist"),
                gate="framework-qa",
                expected_document_digest=self.anchors["framework_qa_digest"],
                profile_digest=self.anchors["profile_digest"],
                source_set_digest=self.anchors["source_set_digest"],
            ),
        )
        document = self._evidence("framework-qa")
        validate_qa_evidence(document, "framework-qa")
        extra = copy.deepcopy(document)
        extra["checks"] = []
        self._expect(BM_IDENTITY_INVALID, lambda: validate_qa_evidence(extra, "framework-qa"))


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()

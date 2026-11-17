"""O09-REC / O09-E2E: the official seven-gate receipt graph."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config.codec import content_digest
from quervant_bench.config.contracts import validate_receipt
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BM_SCOPE_MISMATCH, BenchError
from quervant_bench.official import contracts, coordinator, receipts
from quervant_bench.official.publication import GATE_RECEIPT_NAMES
from quervant_bench.tests import official_support as support


class ReceiptGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary.name)
        (
            cls.result,
            cls.fixture,
            cls.admitted,
            cls.analysis,
            cls.policy,
        ) = support.published_cross_engine(cls.root)
        from quervant_bench.official.publication import load_official_bundle

        cls.bundle = load_official_bundle(
            output_base=cls.root / "output",
            study_id=cls.result.study_id,
            run_id=cls.result.run_id,
            anchors=cls.result.anchors,
        )
        cls.receipts = {
            gate: cls.bundle.documents[name] for gate, name in GATE_RECEIPT_NAMES.items()
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_o09_rec_01_all_seven_receipts_are_real_official(self) -> None:
        self.assertEqual(len(self.receipts), 7)
        for gate, document in self.receipts.items():
            receipt = validate_receipt(document)
            self.assertEqual(receipt.gate, gate)
            self.assertEqual(receipt.status, "pass")
            self.assertEqual(
                (receipt.evidence_origin, receipt.qualification_scope),
                ("real", "official"),
            )
            self.assertEqual(receipt.validator.validator_id, f"official-{gate}")

    def test_o09_rec_02_dependency_graph_matches_the_frozen_edges(self) -> None:
        for gate, document in self.receipts.items():
            observed = tuple(sorted(entry["gate"] for entry in document["dependencies"]))
            self.assertEqual(observed, contracts.DEPENDENCY_GATES[gate])

    def test_o09_rec_03_q_and_policy_bindings_are_exact(self) -> None:
        for gate, document in self.receipts.items():
            if gate in contracts.QA_ROSTER_GATES:
                self.assertEqual(
                    document["qa_roster_digest"], coordinator.qa_roster_digest()
                )
            else:
                self.assertNotIn("qa_roster_digest", document)
            if gate in contracts.POLICY_GATES:
                self.assertIn("policy_digest", document)
            else:
                self.assertNotIn("policy_digest", document)

    def test_o09_rec_04_forged_dependency_edge_is_rejected(self) -> None:
        document = copy.deepcopy(self.receipts["attestation"])
        document["dependencies"] = document["dependencies"][:-1]
        from quervant_bench.config.codec import canonical_payload_bytes

        document["receipt_id"] = content_digest(
            {key: value for key, value in document.items() if key != "receipt_id"}
        )
        with self.assertRaises(BenchError):
            receipts.verify_official_receipt(
                document,
                gate="attestation",
                subject=self.result.anchors.subject,
                source_set_digest=self.result.anchors.source_set_digest,
                inputs={
                    entry["name"]: entry["digest"]
                    for entry in self.receipts["attestation"]["inputs"]
                },
                outputs={
                    entry["name"]: entry["digest"]
                    for entry in self.receipts["attestation"]["outputs"]
                },
                dependencies=[
                    self.receipts[gate]
                    for gate in contracts.DEPENDENCY_GATES["attestation"]
                ],
                qa_roster_digest=coordinator.qa_roster_digest(),
                policy_digest=self.policy["policy_digest"],
            )
        del canonical_payload_bytes

    def test_o09_rec_05_status_relabel_is_rejected(self) -> None:
        document = copy.deepcopy(self.receipts["admission"])
        document["status"] = "fail"
        document["receipt_id"] = content_digest(
            {key: value for key, value in document.items() if key != "receipt_id"}
        )
        with self.assertRaises(BenchError) as raised:
            receipts.verify_official_receipt(
                document,
                gate="admission",
                subject=self.result.anchors.subject,
                source_set_digest=self.result.anchors.source_set_digest,
                inputs={entry["name"]: entry["digest"] for entry in document["inputs"]},
                outputs={entry["name"]: entry["digest"] for entry in document["outputs"]},
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_rec_06_subject_mismatch_is_rejected(self) -> None:
        document = copy.deepcopy(self.receipts["admission"])
        other = dict(self.result.anchors.subject, run_id="33333333-3333-4333-8333-333333333333")
        document["subject"] = other
        document["receipt_id"] = content_digest(
            {key: value for key, value in document.items() if key != "receipt_id"}
        )
        with self.assertRaises(BenchError) as raised:
            receipts.verify_official_receipt(
                document,
                gate="admission",
                subject=self.result.anchors.subject,
                source_set_digest=self.result.anchors.source_set_digest,
                inputs={entry["name"]: entry["digest"] for entry in document["inputs"]},
                outputs={entry["name"]: entry["digest"] for entry in document["outputs"]},
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_o09_rec_07_synthetic_receipt_is_rejected_by_official_verification(self) -> None:
        synthetic = {
            "receipt_id": "sha256:" + "0" * 64,
            "kind": "receipt",
            "schema_version": 1,
            "gate": "admission",
            "status": "pass",
            "evidence_origin": "synthetic",
            "qualification_scope": "simulated",
            "subject": dict(self.result.anchors.subject),
            "validator": {
                "validator_id": "synthetic-admission",
                "validator_version": 1,
                "source_digest": "sha256:" + "1" * 64,
            },
            "inputs": [],
            "dependencies": [],
            "outputs": [],
        }
        synthetic["receipt_id"] = content_digest(
            {key: value for key, value in synthetic.items() if key != "receipt_id"}
        )
        with self.assertRaises(BenchError) as raised:
            receipts.verify_official_receipt(
                synthetic,
                gate="admission",
                subject=self.result.anchors.subject,
                source_set_digest=self.result.anchors.source_set_digest,
                inputs={},
                outputs={},
            )
        self.assertEqual(raised.exception.code, BM_SCOPE_MISMATCH)

    def test_o09_rec_08_missing_input_binding_is_rejected(self) -> None:
        document = copy.deepcopy(self.receipts["admission"])
        with self.assertRaises(BenchError) as raised:
            receipts.build_official_receipt(
                gate="admission",
                subject=self.result.anchors.subject,
                source_set_digest=self.result.anchors.source_set_digest,
                inputs={"authorization": "sha256:" + "a" * 64},
                outputs={"admission-index": "sha256:" + "b" * 64},
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)
        self.assertIn("inputs", str(raised.exception.field_path))

    def test_o09_rec_09_missing_qa_roster_binding_is_rejected(self) -> None:
        with self.assertRaises(BenchError):
            receipts.build_official_receipt(
                gate="framework-qa",
                subject=self.result.anchors.subject,
                source_set_digest=self.result.anchors.source_set_digest,
                inputs={
                    "framework-qa-evidence": "sha256:" + "a" * 64,
                    "qa-roster": "sha256:" + "b" * 64,
                    "source-set": "sha256:" + "c" * 64,
                    "toolchain": "sha256:" + "d" * 64,
                },
                outputs={"framework-qa-evidence": "sha256:" + "a" * 64},
            )

    def test_o09_rec_10_manifest_excludes_itself_and_binds_attestation(self) -> None:
        manifest = self.bundle.documents["manifest.json"]
        self.assertEqual(len(manifest["members"]), 14)
        self.assertNotIn("manifest.json", [member["path"] for member in manifest["members"]])
        self.assertEqual(
            manifest["attestation_digest"],
            content_digest(self.bundle.documents["attestation.json"]),
        )
        self.assertEqual(len(manifest["freeze_snapshot"]["members"]), 13)

    def test_o09_rec_11_receipt_digest_is_stable(self) -> None:
        for document in self.receipts.values():
            self.assertEqual(receipts.receipt_digest(document), document["receipt_id"])

    def test_o09_rec_12_e2e_both_families_share_the_builder_and_outcome_taxonomy(self) -> None:
        from quervant_bench.official import report

        self.assertEqual(
            report.disposition_for(closeout="READY_FOR_REVIEW"),
            report.DISPOSITION_REAL_AND_HISTORICAL,
        )
        self.assertEqual(
            report.disposition_for(closeout="BLOCKED", real_series_attempted=True),
            report.DISPOSITION_REAL_PARTIAL,
        )
        self.assertEqual(
            report.disposition_for(
                closeout="BLOCKED", real_series_valid=True, historical_parity_pass=False
            ),
            report.DISPOSITION_REAL_ONLY,
        )
        self.assertEqual(
            report.disposition_for(closeout="BLOCKED"),
            report.DISPOSITION_IMPLEMENTATION_ONLY,
        )


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()

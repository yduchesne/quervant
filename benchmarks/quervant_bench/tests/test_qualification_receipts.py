"""REC-01…09 — exact BM-01 receipt graph and semantic edge verification.

The expected graph is a hand-authored truth table, not something produced by
``build_stage_receipt``. Every forged case recomputes its own outer content digest
so that only semantic validation can reject it.
"""

from __future__ import annotations

import copy
import hashlib
import unittest
from typing import Any, Mapping

from quervant_bench.config.codec import content_digest
from quervant_bench.config.contracts import validate_receipt
from quervant_bench.config.errors import BM_IDENTITY_INVALID, BenchError
from quervant_bench.qualification import receipts
from quervant_bench.qualification.receipts import (
    build_stage_receipt,
    validator_identity,
    verify_stage_receipt,
)

SUBJECT = {
    "experiment_id": "synthetic-analysis-smoke",
    "run_id": "00000000-0000-4000-8000-000000000010",
    "protocol_digest": "sha256:" + hashlib.sha256(b"protocol").hexdigest(),
    "workload_digest": "sha256:" + hashlib.sha256(b"workload").hexdigest(),
}
OTHER_RUN_SUBJECT = {**SUBJECT, "run_id": "00000000-0000-4000-8000-000000000011"}

SOURCE_DIGEST = "sha256:" + hashlib.sha256(b"source").hexdigest()
PROFILE_DIGEST = "sha256:" + hashlib.sha256(b"profile").hexdigest()
POLICY_DIGEST = "sha256:" + hashlib.sha256(b"policy").hexdigest()

#: Independent declarative truth table (plan §6), sorted ascending.
TRUTH_TABLE: dict[str, tuple[str, ...]] = {
    "admission": (),
    "analysis": ("admission",),
    "verification": ("admission", "analysis"),
    "framework-qa": (),
    "source-qa": (),
    "acceptance": (
        "admission",
        "analysis",
        "framework-qa",
        "source-qa",
        "verification",
    ),
    "attestation": (
        "acceptance",
        "admission",
        "analysis",
        "framework-qa",
        "source-qa",
        "verification",
    ),
}
TRUTH_INPUTS: dict[str, tuple[str, ...]] = {
    "admission": (
        "protocol",
        "qualification-profile",
        "scenario",
        "seal",
        "source-set",
        "workload",
    ),
    "analysis": (
        "admission-index",
        "analysis-profile",
        "policy-profile",
        "resource-observations",
        "source-set",
    ),
    "verification": ("analysis", "policy", "source-seal", "source-set"),
    "framework-qa": (
        "framework-qa-evidence",
        "qa-toolchain",
        "qualification-profile",
        "source-set",
    ),
    "source-qa": (
        "qa-toolchain",
        "qualification-profile",
        "source-qa-evidence",
        "source-set",
    ),
    "acceptance": (
        "admission-index",
        "analysis",
        "framework-qa-evidence",
        "policy",
        "qualification-profile",
        "source-qa-evidence",
        "source-set",
        "verification-assessment",
    ),
    "attestation": ("freeze-snapshot", "qualification-profile", "source-set"),
}
TRUTH_OUTPUTS: dict[str, tuple[str, ...]] = {
    "admission": ("admission-index",),
    "analysis": ("analysis", "policy"),
    "verification": ("verification-assessment",),
    "framework-qa": ("framework-qa-evidence",),
    "source-qa": ("source-qa-evidence",),
    "acceptance": ("acceptance-summary",),
    "attestation": ("freeze-snapshot",),
}


def digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _document_inputs(gate: str) -> dict[str, str]:
    return {name: digest(f"{gate}-{name}") for name in TRUTH_INPUTS[gate]}


def _document_outputs(gate: str) -> dict[str, str]:
    return {name: digest(f"{gate}-out-{name}") for name in TRUTH_OUTPUTS[gate]}


def _rehash(document: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in document.items() if key != "receipt_id"}
    document["receipt_id"] = content_digest(payload)
    return document


def make_receipt(
    *,
    gate: str,
    subject: Mapping[str, Any] = SUBJECT,
    source_digest: str = SOURCE_DIGEST,
    dependencies: tuple[Mapping[str, Any], ...] = (),
    inputs: Mapping[str, str] | None = None,
    outputs: Mapping[str, str] | None = None,
    profile_digest: str | None = None,
    policy_digest: str | None = None,
) -> dict[str, Any]:
    """Hand-author one receipt without calling the production builder."""

    input_map = _document_inputs(gate) if inputs is None else dict(inputs)
    output_map = _document_outputs(gate) if outputs is None else dict(outputs)
    payload: dict[str, Any] = {
        "kind": "receipt",
        "schema_version": 1,
        "gate": gate,
        "status": "pass",
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "subject": dict(subject),
        "validator": {
            "validator_id": receipts.VALIDATOR_IDS[gate],
            "validator_version": 1,
            "source_digest": source_digest,
        },
        "inputs": [
            {"name": name, "digest": input_map[name]} for name in sorted(input_map)
        ],
        "dependencies": sorted(
            (
                {
                    "name": dependency["gate"],
                    "digest": content_digest(dict(dependency)),
                    "gate": dependency["gate"],
                    "receipt_id": dependency["receipt_id"],
                }
                for dependency in dependencies
            ),
            key=lambda entry: entry["name"],
        ),
        "outputs": [
            {"name": name, "digest": output_map[name]} for name in sorted(output_map)
        ],
    }
    if gate in receipts.QA_ROSTER_GATES:
        payload["qa_roster_digest"] = profile_digest or PROFILE_DIGEST
    if gate in receipts.POLICY_GATES:
        payload["policy_digest"] = policy_digest or POLICY_DIGEST
    document = dict(payload)
    document["receipt_id"] = content_digest(payload)
    validate_receipt(document)
    return document


def build_graph() -> dict[str, dict[str, Any]]:
    """Build the complete seven-receipt graph from the truth table."""

    graph: dict[str, dict[str, Any]] = {}
    for gate in (
        "admission",
        "analysis",
        "verification",
        "framework-qa",
        "source-qa",
        "acceptance",
        "attestation",
    ):
        graph[gate] = make_receipt(
            gate=gate,
            dependencies=tuple(graph[name] for name in TRUTH_TABLE[gate]),
        )
    return graph


def verify(
    document: Mapping[str, Any],
    gate: str,
    dependencies: tuple[Mapping[str, Any], ...],
    *,
    subject: Mapping[str, Any] = SUBJECT,
) -> Any:
    return verify_stage_receipt(
        document,
        gate=gate,
        source_set_digest=SOURCE_DIGEST,
        expected_subject=subject,
        inputs=_document_inputs(gate),
        outputs=_document_outputs(gate),
        dependencies=dependencies,
        profile_digest=PROFILE_DIGEST if gate in receipts.QA_ROSTER_GATES else None,
        policy_digest=POLICY_DIGEST if gate in receipts.POLICY_GATES else None,
    )


class ReceiptGraphTests(unittest.TestCase):
    """REC-01…09."""

    def test_rec_01_complete_graph_matches_the_declarative_truth_table(self) -> None:
        self.assertEqual(receipts.DEPENDENCY_GATES, TRUTH_TABLE)
        self.assertEqual(receipts.INPUT_NAMES, TRUTH_INPUTS)
        self.assertEqual(receipts.OUTPUT_NAMES, TRUTH_OUTPUTS)
        graph = build_graph()
        for gate, expected in TRUTH_TABLE.items():
            verify(graph[gate], gate, tuple(graph[name] for name in expected))
        built = build_stage_receipt(
            gate="acceptance",
            subject=SUBJECT,
            validator=validator_identity("acceptance", SOURCE_DIGEST),
            inputs=_document_inputs("acceptance"),
            dependencies=(
                graph["admission"],
                graph["analysis"],
                graph["verification"],
                graph["framework-qa"],
                graph["source-qa"],
            ),
            outputs=_document_outputs("acceptance"),
            profile_digest=PROFILE_DIGEST,
            policy_digest=POLICY_DIGEST,
        )
        self.assertEqual(built, graph["acceptance"])

    def test_rec_02_missing_dependency_is_rejected(self) -> None:
        graph = build_graph()
        with self.assertRaises(BenchError) as raised:
            verify(
                graph["acceptance"],
                "acceptance",
                (
                    graph["admission"],
                    graph["analysis"],
                    graph["verification"],
                    graph["framework-qa"],
                ),
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_rec_03_extra_dependency_is_rejected(self) -> None:
        graph = build_graph()
        with self.assertRaises(BenchError) as raised:
            verify(
                graph["framework-qa"],
                "framework-qa",
                (graph["admission"],),
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_rec_04_unsorted_dependency_entries_are_rejected(self) -> None:
        graph = build_graph()
        tampered = copy.deepcopy(graph["attestation"])
        tampered["dependencies"] = list(reversed(tampered["dependencies"]))
        _rehash(tampered)
        with self.assertRaises(BenchError) as raised:
            validate_receipt(tampered)
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_rec_05_foreign_run_subject_is_rejected(self) -> None:
        graph = build_graph()
        with self.assertRaises(BenchError) as raised:
            verify(
                graph["admission"],
                "admission",
                (),
                subject=OTHER_RUN_SUBJECT,
            )
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_rec_06_cross_run_dependency_with_valid_self_hash_is_rejected(self) -> None:
        graph = build_graph()
        foreign = make_receipt(gate="admission", subject=OTHER_RUN_SUBJECT)
        tampered = copy.deepcopy(graph["analysis"])
        tampered["dependencies"] = [
            {
                "name": "admission",
                "digest": content_digest(foreign),
                "gate": "admission",
                "receipt_id": foreign["receipt_id"],
            }
        ]
        _rehash(tampered)
        validate_receipt(tampered)
        with self.assertRaises(BenchError) as raised:
            verify(tampered, "analysis", (graph["admission"],))
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

        substituted = copy.deepcopy(graph["analysis"])
        substituted["dependencies"][0]["receipt_id"] = foreign["receipt_id"]
        _rehash(substituted)
        validate_receipt(substituted)
        with self.assertRaises(BenchError) as second:
            verify(substituted, "analysis", (graph["admission"],))
        self.assertEqual(second.exception.code, BM_IDENTITY_INVALID)

    def test_rec_07_non_passing_status_is_rejected(self) -> None:
        graph = build_graph()
        for status in ("fail", "blocked", "not-executed"):
            tampered = copy.deepcopy(graph["verification"])
            tampered["status"] = status
            _rehash(tampered)
            with self.assertRaises(BenchError) as raised:
                verify(
                    tampered,
                    "verification",
                    (graph["admission"], graph["analysis"]),
                )
            self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)

    def test_rec_08_wrong_validator_or_source_digest_is_rejected(self) -> None:
        graph = build_graph()
        wrong_id = copy.deepcopy(graph["admission"])
        wrong_id["validator"]["validator_id"] = "synthetic-analysis"
        _rehash(wrong_id)
        with self.assertRaises(BenchError):
            verify(wrong_id, "admission", ())
        wrong_source = copy.deepcopy(graph["admission"])
        wrong_source["validator"]["source_digest"] = digest("other-source")
        _rehash(wrong_source)
        with self.assertRaises(BenchError):
            verify(wrong_source, "admission", ())

    def test_rec_09_output_mismatch_is_rejected(self) -> None:
        graph = build_graph()
        tampered = copy.deepcopy(graph["analysis"])
        tampered["outputs"][0]["digest"] = digest("other-analysis")
        _rehash(tampered)
        with self.assertRaises(BenchError) as raised:
            verify(tampered, "analysis", (graph["admission"],))
        self.assertEqual(raised.exception.code, BM_IDENTITY_INVALID)


if __name__ == "__main__":  # pragma: no cover - unittest entrypoint
    unittest.main()

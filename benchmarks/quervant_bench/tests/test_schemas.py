"""Schema, cross-field protocol/binding and origin/scope contract tests.

Covers SCH-01..02, PROTO-01..09, BIND-01..09 and SCOPE-01..07.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from quervant_bench.config import schemas
from quervant_bench.config.codec import content_digest, load_document, loads_yaml
from quervant_bench.config.contracts import (
    ALLOWED_ORIGIN_SCOPES,
    load_experiment_bundle,
    validate_outcome,
    validate_protocol,
    validate_receipt,
    validate_workload,
)
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BenchError,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic-contract-smoke"
EXPERIMENT_ID = "synthetic-contract-smoke"
FIXTURE_FILES = ("experiment.yaml", "workloads.yaml", "protocol.yaml", "adapter.yaml")

ARCHITECTURE_ILLUSTRATIVE_YAML = """
schema_version: 1
experiment:
  id: retained-key-dedup
workload:
  id: search-topk
  digest: "<content digest>"
arms:
  - id: baseline
    adapter: quervant
  - id: prefilter-bitset
    adapter: quervant
protocol:
  id: balanced-paired
  version: 1
  profile: qualification
  blocks: 12
  bootstrap_resamples: 10000
policy:
  id: retained-key-selection
  version: 1
"""


def _fixture(name: str) -> dict:
    document = load_document(FIXTURES / name)
    assert isinstance(document, dict)
    return document


def _seal(payload: dict) -> dict:
    sealed = dict(payload)
    sealed["receipt_id"] = content_digest(payload)
    return sealed


def _receipt(
    origin: str = "synthetic",
    scope: str = "simulated",
    status: str = "not-executed",
    gate: str = "framework-qa",
) -> dict:
    bundle_receipt = copy.deepcopy(_fixture("receipt.synthetic.json"))
    bundle_receipt["evidence_origin"] = origin
    bundle_receipt["qualification_scope"] = scope
    bundle_receipt["status"] = status
    bundle_receipt["gate"] = gate
    bundle_receipt.pop("receipt_id")
    return _seal(bundle_receipt)


class SchemaRegistryTests(unittest.TestCase):
    def test_sch_01_all_six_schemas_compile_with_semantic_ids(self) -> None:
        checked = schemas.check_all_schemas()
        self.assertEqual(len(checked), 6)
        kinds = {kind for kind, _version in checked}
        self.assertEqual(
            kinds,
            {"experiment", "workload", "protocol", "adapter", "receipt", "outcome"},
        )
        identifiers = set()
        for kind, version in checked:
            document = schemas.schema_document(kind, version)
            self.assertEqual(document["$id"], schemas.schema_id(kind, version))
            self.assertEqual(
                document["$id"], f"urn:quervant-bench:contract:{kind}:v1"
            )
            self.assertNotIn("pr15", document["$id"])
            identifiers.add(document["$id"])
        self.assertEqual(len(identifiers), 6)

    def test_fixture_copies_are_byte_identical_to_the_catalog_example(self) -> None:
        catalog = Path(__file__).resolve().parents[2] / "experiments" / EXPERIMENT_ID
        for name in FIXTURE_FILES:
            self.assertEqual(
                (FIXTURES / name).read_bytes(), (catalog / name).read_bytes(), name
            )

    def test_sch_02_architecture_example_cannot_validate_as_a_protocol(self) -> None:
        document = loads_yaml(ARCHITECTURE_ILLUSTRATIVE_YAML)
        with self.assertRaises(BenchError) as caught:
            validate_protocol(document)
        self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_sch_02_same_entrypoint_rejects_the_illustrative_example(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            experiments = Path(tmp) / "experiments"
            root = experiments / EXPERIMENT_ID
            root.mkdir(parents=True)
            for name in FIXTURE_FILES:
                (root / name).write_text(
                    json.dumps(_fixture(name), indent=2), encoding="utf-8"
                )
            illustrative = loads_yaml(ARCHITECTURE_ILLUSTRATIVE_YAML)
            (root / "protocol.yaml").write_text(
                json.dumps(illustrative, indent=2), encoding="utf-8"
            )
            with self.assertRaises(BenchError) as caught:
                load_experiment_bundle(EXPERIMENT_ID, experiments)
            self.assertEqual(caught.exception.code, BM_SCHEMA_INVALID)

    def test_unsupported_schema_version_fails_closed(self) -> None:
        document = _fixture("workloads.yaml")
        document["schema_version"] = 9
        with self.assertRaises(BenchError) as caught:
            validate_workload(document)
        self.assertEqual(caught.exception.code, BM_SCHEMA_UNSUPPORTED)


class CrossFieldProtocolTests(unittest.TestCase):
    def assertCode(self, code: str, call, *args) -> BenchError:
        with self.assertRaises(BenchError) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_proto_01_fixture_slot_arithmetic(self) -> None:
        protocol = validate_protocol(_fixture("protocol.yaml"))
        total = sum(item.slots_per_block for item in protocol.arm_multiplicity)
        self.assertEqual(total, protocol.schedule.slots_per_block)
        self.assertEqual(protocol.schedule.blocks, 2)
        self.assertEqual(protocol.schedule.mode, "seeded-balanced")
        self.assertEqual(protocol.schedule.seed, 42)

    def test_proto_02_explicit_orders_with_matching_counts_are_accepted(self) -> None:
        document = copy.deepcopy(_fixture("protocol.yaml"))
        document["schedule"]["mode"] = "explicit"
        document["schedule"]["explicit_orders"] = [
            ["baseline", "candidate"],
            ["candidate", "baseline"],
        ]
        protocol = validate_protocol(document)
        self.assertEqual(
            protocol.schedule.explicit_orders,
            (("baseline", "candidate"), ("candidate", "baseline")),
        )

    def test_proto_03_boundary_seeds_are_accepted(self) -> None:
        for seed in (0, 2**32 - 1, 2**64 - 1):
            document = copy.deepcopy(_fixture("protocol.yaml"))
            document["schedule"]["seed"] = seed
            document["statistics"]["seed"] = seed
            protocol = validate_protocol(document)
            self.assertEqual(protocol.schedule.seed, seed)
            self.assertEqual(protocol.statistics_seed, seed)

    def test_proto_04_slot_sum_mismatch_is_rejected(self) -> None:
        document = copy.deepcopy(_fixture("protocol.yaml"))
        document["arm_multiplicity"][0]["slots_per_block"] = 2
        self.assertCode(BM_IDENTITY_INVALID, validate_protocol, document)

    def test_proto_05_missing_or_duplicated_arm_is_rejected(self) -> None:
        document = copy.deepcopy(_fixture("protocol.yaml"))
        document["arm_multiplicity"].append(
            {"arm_id": "baseline", "slots_per_block": 2}
        )
        document["schedule"]["slots_per_block"] = 4
        self.assertCode(BM_IDENTITY_INVALID, validate_protocol, document)

    def test_proto_06_malformed_explicit_orders_are_rejected(self) -> None:
        missing_slot = copy.deepcopy(_fixture("protocol.yaml"))
        missing_slot["schedule"]["mode"] = "explicit"
        missing_slot["schedule"]["explicit_orders"] = [
            ["baseline"],
            ["baseline", "candidate"],
        ]
        self.assertCode(BM_IDENTITY_INVALID, validate_protocol, missing_slot)

        extra_block = copy.deepcopy(_fixture("protocol.yaml"))
        extra_block["schedule"]["mode"] = "explicit"
        extra_block["schedule"]["explicit_orders"] = [
            ["baseline", "candidate"],
            ["baseline", "candidate"],
            ["baseline", "candidate"],
        ]
        self.assertCode(BM_IDENTITY_INVALID, validate_protocol, extra_block)

        wrong_count = copy.deepcopy(_fixture("protocol.yaml"))
        wrong_count["schedule"]["mode"] = "explicit"
        wrong_count["schedule"]["explicit_orders"] = [
            ["baseline", "baseline"],
            ["baseline", "candidate"],
        ]
        self.assertCode(BM_IDENTITY_INVALID, validate_protocol, wrong_count)

        missing_orders = copy.deepcopy(_fixture("protocol.yaml"))
        missing_orders["schedule"]["mode"] = "explicit"
        self.assertCode(BM_IDENTITY_INVALID, validate_protocol, missing_orders)

    def test_proto_07_seeded_mode_forbids_explicit_orders(self) -> None:
        document = copy.deepcopy(_fixture("protocol.yaml"))
        document["schedule"]["explicit_orders"] = [
            ["baseline", "candidate"],
            ["baseline", "candidate"],
        ]
        self.assertCode(BM_IDENTITY_INVALID, validate_protocol, document)

    def test_proto_08_retained_blocks_cannot_exceed_total(self) -> None:
        document = copy.deepcopy(_fixture("protocol.yaml"))
        document["exclusion"]["minimum_retained_blocks"] = 3
        self.assertCode(BM_IDENTITY_INVALID, validate_protocol, document)

    def test_proto_09_zero_samples_unknown_mode_and_negative_retries_fail(self) -> None:
        samples = copy.deepcopy(_fixture("protocol.yaml"))
        samples["measurement"]["samples_per_lane_slot"] = 0
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, samples)

        mode = copy.deepcopy(_fixture("protocol.yaml"))
        mode["schedule"]["mode"] = "random"
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, mode)

        retries = copy.deepcopy(_fixture("protocol.yaml"))
        retries["recovery"]["measurement_retries"] = -1
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, retries)


class CrossDocumentBindingTests(unittest.TestCase):
    def assertCode(self, code: str, call, *args) -> BenchError:
        with self.assertRaises(BenchError) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def _load(self, mutate=None):
        with tempfile.TemporaryDirectory() as tmp:
            experiments = Path(tmp) / "experiments"
            root = experiments / EXPERIMENT_ID
            root.mkdir(parents=True)
            documents = {name: _fixture(name) for name in FIXTURE_FILES}
            if mutate is not None:
                mutate(documents)
            for name, document in documents.items():
                (root / name).write_text(
                    json.dumps(document, indent=2), encoding="utf-8"
                )
            return load_experiment_bundle(EXPERIMENT_ID, experiments)

    def test_bind_01_referenced_declarations_resolve(self) -> None:
        bundle = self._load()
        self.assertEqual(bundle.experiment.experiment_id, EXPERIMENT_ID)
        self.assertEqual(bundle.adapter.adapter_id, "synthetic-smoke")
        self.assertEqual(bundle.protocol.experiment_id, EXPERIMENT_ID)

    def test_bind_02_distinct_lanes_and_arms_are_preserved(self) -> None:
        bundle = self._load()
        self.assertEqual(
            [lane.lane_id for lane in bundle.workload.lanes],
            ["rare-query", "common-query"],
        )
        self.assertEqual(
            [arm.arm_id for arm in bundle.experiment.arms],
            ["baseline", "candidate"],
        )
        self.assertEqual(bundle.workload.lanes[0].operation, "search")
        self.assertEqual(bundle.workload.lanes[0].cache_regime, "warm")

    def test_bind_03_workload_digest_matches_canonical_payload(self) -> None:
        bundle = self._load()
        self.assertEqual(bundle.workload_digest, content_digest(bundle.workload_document))
        self.assertEqual(bundle.protocol.workload_digest, bundle.workload_digest)

    def test_bind_04_protocol_referencing_unknown_arm_is_rejected(self) -> None:
        def mutate(documents):
            documents["protocol.yaml"]["arm_multiplicity"][0]["arm_id"] = "unknown-arm"

        self.assertCode(BM_IDENTITY_INVALID, self._load, mutate)

    def test_bind_05_wrong_workload_digest_is_rejected(self) -> None:
        def mutate(documents):
            documents["protocol.yaml"]["workload_digest"] = "sha256:" + "0" * 64

        self.assertCode(BM_IDENTITY_INVALID, self._load, mutate)

    def test_bind_06_missing_adapter_declaration_is_rejected(self) -> None:
        def mutate(documents):
            for arm in documents["experiment.yaml"]["arms"]:
                arm["adapter_id"] = "missing-adapter"

        self.assertCode(BM_IDENTITY_INVALID, self._load, mutate)

    def test_bind_07_duplicate_lane_id_is_rejected(self) -> None:
        def mutate(documents):
            duplicate = copy.deepcopy(documents["workloads.yaml"]["lanes"][0])
            duplicate["params"]["top_k"] = 25
            documents["workloads.yaml"]["lanes"].append(duplicate)

        self.assertCode(BM_IDENTITY_INVALID, self._load, mutate)

    def test_bind_08_unsupported_operation_and_metric_are_rejected(self) -> None:
        def mutate(documents):
            documents["workloads.yaml"]["lanes"][0]["operation"] = "index"

        self.assertCode(BM_IDENTITY_INVALID, self._load, mutate)

        def metric(documents):
            documents["adapter.yaml"]["measurement_envelope"]["unit"] = "seconds"

        self.assertCode(BM_SCHEMA_INVALID, self._load, metric)

    def test_bind_09_path_traversal_and_symlinks_fail_closed(self) -> None:
        def traversal(documents):
            documents["experiment.yaml"]["workloads_file"] = "../workloads.yaml"

        self.assertCode(BM_SCHEMA_INVALID, self._load, traversal)

        def disallowed(documents):
            documents["experiment.yaml"]["workloads_file"] = "evil.yaml"

        self.assertCode(BM_UNSAFE_INPUT, self._load, disallowed)

        outside = load_document(FIXTURES / "workloads.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            experiments = Path(tmp) / "experiments"
            root = experiments / EXPERIMENT_ID
            root.mkdir(parents=True)
            for name in FIXTURE_FILES:
                if name == "workloads.yaml":
                    continue
                (root / name).write_text(
                    json.dumps(_fixture(name), indent=2), encoding="utf-8"
                )
            target = Path(tmp) / "outside-workloads.yaml"
            target.write_text(json.dumps(outside), encoding="utf-8")
            (root / "workloads.yaml").symlink_to(target)
            self.assertCode(
                BM_UNSAFE_INPUT, load_experiment_bundle, EXPERIMENT_ID, experiments
            )


class OriginScopeTests(unittest.TestCase):
    def assertCode(self, code: str, call, *args) -> BenchError:
        with self.assertRaises(BenchError) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_scope_matrix_table_is_exactly_the_three_allowed_pairs(self) -> None:
        self.assertEqual(
            ALLOWED_ORIGIN_SCOPES,
            {
                ("synthetic", "simulated"),
                ("real", "official"),
                ("real", "historical_replay"),
            },
        )

    def test_scope_01_synthetic_simulated_is_accepted(self) -> None:
        receipt = validate_receipt(_fixture("receipt.synthetic.json"))
        self.assertEqual(
            (receipt.evidence_origin, receipt.qualification_scope),
            ("synthetic", "simulated"),
        )
        self.assertEqual(receipt.status, "not-executed")

    def test_scope_02_real_historical_replay_is_recognised_without_verdict(self) -> None:
        receipt = validate_receipt(_receipt("real", "historical_replay"))
        self.assertEqual(receipt.evidence_origin, "real")
        self.assertEqual(receipt.qualification_scope, "historical_replay")
        self.assertNotIn(receipt.status, {"pass"})

    def test_scope_03_synthetic_official_is_rejected(self) -> None:
        self.assertCode(BM_SCOPE_MISMATCH, validate_receipt, _receipt("synthetic", "official"))

    def test_scope_04_missing_origin_is_rejected(self) -> None:
        receipt = _fixture("receipt.synthetic.json")
        receipt = copy.deepcopy(receipt)
        receipt.pop("evidence_origin")
        receipt.pop("receipt_id")
        self.assertCode(BM_SCHEMA_INVALID, validate_receipt, _seal(receipt))

    def test_scope_05_real_simulated_is_rejected(self) -> None:
        self.assertCode(BM_SCOPE_MISMATCH, validate_receipt, _receipt("real", "simulated"))

    def test_scope_06_synthetic_historical_replay_is_rejected(self) -> None:
        self.assertCode(
            BM_SCOPE_MISMATCH, validate_receipt, _receipt("synthetic", "historical_replay")
        )

    def test_scope_07_synthetic_pass_cannot_claim_official_acceptance(self) -> None:
        self.assertCode(
            BM_SCOPE_MISMATCH,
            validate_receipt,
            _receipt("synthetic", "official", status="pass", gate="acceptance"),
        )

    def test_receipt_requires_sorted_unique_evidence_entries(self) -> None:
        receipt = copy.deepcopy(_fixture("receipt.synthetic.json"))
        receipt.pop("receipt_id")
        receipt["inputs"] = list(reversed(receipt["inputs"]))
        self.assertCode(BM_IDENTITY_INVALID, validate_receipt, _seal(receipt))

        receipt = copy.deepcopy(_fixture("receipt.synthetic.json"))
        receipt.pop("receipt_id")
        duplicate = dict(receipt["outputs"][0])
        receipt["outputs"].append(duplicate)
        with self.assertRaises(BenchError) as caught:
            validate_receipt(_seal(receipt))
        self.assertIn(caught.exception.code, (BM_IDENTITY_INVALID, BM_SCHEMA_INVALID))

    def test_outcome_rejects_ok_with_an_error_detail_and_vice_versa(self) -> None:
        good = {
            "kind": "outcome",
            "schema_version": 1,
            "status": "ok",
            "code": "BM_OK",
            "message": "ok",
            "data": {
                "kind": "inspect-summary",
                "experiment_id": EXPERIMENT_ID,
                "profile": "development",
                "workload_id": "synthetic-contract-lanes",
                "protocol_id": "synthetic-balanced-pair",
                "protocol_digest": "sha256:" + "1" * 64,
                "arm_ids": ["baseline"],
                "lane_ids": ["rare-query"],
                "evidence_origin": "synthetic",
                "qualification_scope": "simulated",
            },
        }
        validate_outcome(good)

        mixed = copy.deepcopy(good)
        mixed["data"] = {"kind": "error-detail", "reason": "success"}
        self.assertCode(BM_SCHEMA_INVALID, validate_outcome, mixed)

        wrong_reason = copy.deepcopy(good)
        wrong_reason.update(status="error", code="BM_FILE_MISSING", message="missing")
        wrong_reason["data"] = {"kind": "error-detail", "reason": "invalid-document"}
        self.assertCode(BM_IDENTITY_INVALID, validate_outcome, wrong_reason)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

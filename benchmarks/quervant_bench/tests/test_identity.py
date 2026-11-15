"""Identity and canonical content-encoding contract tests.

Covers ID-01..04 and CAN-01..08.
"""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from quervant_bench.config.codec import (
    canonical_document_bytes,
    canonical_payload_bytes,
    content_digest,
    load_document,
    loads_json,
)
from quervant_bench.config.contracts import validate_experiment, validate_receipt
from quervant_bench.config.errors import (
    BM_IDENTITY_INVALID,
    BenchError,
)
from quervant_bench.config.identity import (
    SLUG_MAX_LENGTH,
    binding_digest,
    contains_pr_phase_token,
    is_canonical_uuid4,
    normalize_uuid4,
    validate_digest,
    validate_positive_int,
    validate_semantic_id,
    validate_source_commit,
    validate_uint64,
    validate_uuid4,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic-contract-smoke"
RUN_ID = "00000000-0000-4000-8000-0000000000ab"
DIGEST = "sha256:" + "a" * 64


class IdentityTests(unittest.TestCase):
    def assertCode(self, code: str, call, *args) -> BenchError:
        with self.assertRaises(BenchError) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_id_01_valid_slugs_uuid4_and_digests_are_accepted(self) -> None:
        for slug in (
            "baseline",
            "rare-query",
            "retained-key-dedup",
            "synthetic-contract-smoke",
            "top-k",
        ):
            self.assertEqual(validate_semantic_id(slug, "id"), slug)
        self.assertEqual(validate_uuid4(RUN_ID), RUN_ID)
        self.assertTrue(is_canonical_uuid4(RUN_ID))
        self.assertEqual(validate_digest(DIGEST, "digest"), DIGEST)
        self.assertEqual(
            validate_source_commit("ea9bef647cf155bb0176f159a8b304319ed6f7de"),
            "ea9bef647cf155bb0176f159a8b304319ed6f7de",
        )
        self.assertEqual(validate_uint64(2**64 - 1, "seed"), 2**64 - 1)
        self.assertEqual(validate_positive_int(1, "version"), 1)

    def test_id_02_uuid_normalization_and_slug_length_boundaries(self) -> None:
        upper = RUN_ID.upper()
        self.assertFalse(is_canonical_uuid4(upper))
        self.assertEqual(normalize_uuid4(upper), RUN_ID)
        self.assertCode(BM_IDENTITY_INVALID, normalize_uuid4, "not-a-uuid")

        not_v4 = "00000000-0000-1000-8000-000000000001"
        self.assertCode(BM_IDENTITY_INVALID, normalize_uuid4, not_v4)

        self.assertEqual(validate_semantic_id("abc", "id"), "abc")
        shortest = "a" * 3
        longest = "a" * SLUG_MAX_LENGTH
        self.assertEqual(validate_semantic_id(shortest, "id"), shortest)
        self.assertEqual(validate_semantic_id(longest, "id"), longest)
        self.assertCode(BM_IDENTITY_INVALID, validate_semantic_id, "ab", "id")
        self.assertCode(
            BM_IDENTITY_INVALID, validate_semantic_id, "a" * (SLUG_MAX_LENGTH + 1), "id"
        )

    def test_id_03_pr_phase_tokens_are_rejected_in_new_ids(self) -> None:
        for slug in (
            "pr15d-run",
            "pr15i-d3-c",
            "bm-01-contracts",
            "bm01-foundation",
            "t7f2-analysis",
            "t7-f2-analysis",
        ):
            self.assertTrue(contains_pr_phase_token(slug), slug)
            self.assertCode(BM_IDENTITY_INVALID, validate_semantic_id, slug, "id")

        for slug in ("baseline", "candidate", "top-k", "retained-key-dedup"):
            self.assertFalse(contains_pr_phase_token(slug), slug)

        experiment = copy.deepcopy(
            load_document(FIXTURES / "experiment.yaml")
        )
        experiment["provenance"]["source_pr"] = "pr15d"
        experiment["provenance"]["historical_label"] = "bm-01 t7f2"
        validated = validate_experiment(experiment)
        self.assertEqual(validated.provenance.source_pr, "pr15d")

    def test_id_04_malformed_identifiers_are_rejected(self) -> None:
        for slug in (
            "Baseline",
            "rare/query",
            "rare query",
            "r\u0430re-query",  # Cyrillic 'a' confusable
            "",
            "-leading",
            "trailing-",
            "double--hyphen",
            "9leading-digit",
        ):
            self.assertCode(BM_IDENTITY_INVALID, validate_semantic_id, slug, "id")

        for digest in (
            "sha256:" + "A" * 64,
            "a" * 64,
            "sha256:" + "a" * 63,
            "sha256:" + "g" * 64,
        ):
            self.assertCode(BM_IDENTITY_INVALID, validate_digest, digest, "digest")

        self.assertCode(BM_IDENTITY_INVALID, validate_uint64, True, "seed")
        self.assertCode(BM_IDENTITY_INVALID, validate_uint64, 2**64, "seed")
        self.assertCode(BM_IDENTITY_INVALID, validate_positive_int, 0, "version")
        self.assertCode(BM_IDENTITY_INVALID, validate_positive_int, True, "version")


class CanonicalEncodingTests(unittest.TestCase):
    def test_can_01_object_insertion_order_does_not_change_bytes(self) -> None:
        first = {"b": 2, "a": 1, "c": {"z": 1, "y": 2}}
        second = {"c": {"y": 2, "z": 1}, "a": 1, "b": 2}
        self.assertEqual(
            canonical_payload_bytes(first), canonical_payload_bytes(second)
        )
        self.assertEqual(content_digest(first), content_digest(second))

    def test_can_02_array_order_changes_bytes(self) -> None:
        self.assertNotEqual(
            canonical_payload_bytes({"steps": ["a", "b"]}),
            canonical_payload_bytes({"steps": ["b", "a"]}),
        )
        self.assertNotEqual(
            content_digest({"steps": ["a", "b"]}),
            content_digest({"steps": ["b", "a"]}),
        )

    def test_can_03_encode_decode_encode_is_idempotent(self) -> None:
        document = {"unicode": "\u00e9\u4e2d\U0001f600", "list": [3, 2, 1]}
        encoded = canonical_payload_bytes(document)
        self.assertEqual(loads_json(encoded.decode("utf-8")), document)
        self.assertEqual(canonical_payload_bytes(loads_json(encoded.decode("utf-8"))), encoded)
        self.assertEqual(canonical_document_bytes(document), encoded + b"\n")

    def test_can_04_independently_computed_golden_digest(self) -> None:
        document = {"a": 1, "b": [True, None, "\u00e9"]}
        # Independently computed with:
        # printf '%s' '{"a":1,"b":[true,null,"\xc3\xa9"]}' | sha256sum
        self.assertEqual(
            content_digest(document),
            "sha256:9488dd13ca33d3291f5a91a1833dfa164811755ffba538c2b340780f8c31a0cb",
        )
        self.assertEqual(
            binding_digest({"policy_id": "synthetic-contract-policy", "policy_version": 1}),
            "sha256:5a176b32750515dc9710ccc1fc28b0ec4cc136f24a51a3527216995849b0bc70",
        )

    def test_can_05_one_changed_byte_breaks_the_digest(self) -> None:
        document = {"alpha": 1, "beta": 2}
        digest = content_digest(document)
        document["beta"] = 3
        self.assertNotEqual(content_digest(document), digest)

    def test_can_06_altered_receipt_dependency_breaks_receipt_id(self) -> None:
        receipt = load_document(FIXTURES / "receipt.synthetic.json")
        self.assertEqual(validate_receipt(receipt).status, "not-executed")
        receipt = copy.deepcopy(receipt)
        receipt["dependencies"][0]["receipt_id"] = "sha256:" + "0" * 64
        with self.assertRaises(BenchError) as caught:
            validate_receipt(receipt)
        self.assertEqual(caught.exception.code, BM_IDENTITY_INVALID)

    def test_can_07_no_recursive_self_hash(self) -> None:
        payload = {"kind": "receipt", "status": "not-executed"}
        receipt_id = content_digest(payload)
        sealed = dict(payload)
        sealed["receipt_id"] = receipt_id
        self.assertNotEqual(content_digest(sealed), receipt_id)
        self.assertEqual(
            content_digest(
                {key: value for key, value in sealed.items() if key != "receipt_id"}
            ),
            receipt_id,
        )

    def test_can_08_distinct_unicode_is_not_silently_normalized(self) -> None:
        composed = {"value": "\u00e9"}
        decomposed = {"value": "e\u0301"}
        self.assertNotEqual(
            canonical_payload_bytes(composed), canonical_payload_bytes(decomposed)
        )
        self.assertNotEqual(content_digest(composed), content_digest(decomposed))
        self.assertEqual(loads_json('{"value": "\\u00e9"}'), composed)
        self.assertNotEqual(loads_json('{"value": "\\u00e9"}'), decomposed)


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

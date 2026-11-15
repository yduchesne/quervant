"""Strict parsing and canonical encoding contract tests (L1).

Covers PARSE-01..PARSE-10. No timing, no sleeping, no external services.
"""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from quervant_bench.config import codec
from quervant_bench.config.codec import (
    MAX_DOCUMENT_BYTES,
    canonical_payload_bytes,
    content_digest,
    decode_text,
    load_document,
    loads_json,
    loads_yaml,
)
from quervant_bench.config.contracts import (
    validate_adapter,
    validate_experiment,
    validate_protocol,
    validate_workload,
)
from quervant_bench.config.errors import (
    BM_DUPLICATE_KEY,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_UNSAFE_INPUT,
    BenchError,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic-contract-smoke"


def _fixture(name: str) -> dict:
    document = load_document(FIXTURES / name)
    assert isinstance(document, dict)
    return document


class CodecParsingTests(unittest.TestCase):
    def assertCode(self, code: str, call, *args, **kwargs) -> BenchError:
        with self.assertRaises(BenchError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_parse_01_json_and_yaml_semantics_are_equivalent(self) -> None:
        yaml_text = "alpha: 1\nbeta:\n  - true\n  - null\n  - 'caf\u00e9'\n"
        json_text = '{"alpha": 1, "beta": [true, null, "caf\u00e9"]}'
        from_yaml = loads_yaml(yaml_text)
        from_json = loads_json(json_text)
        self.assertEqual(from_yaml, from_json)
        self.assertEqual(
            canonical_payload_bytes(from_yaml), canonical_payload_bytes(from_json)
        )
        self.assertEqual(content_digest(from_yaml), content_digest(from_json))
        self.assertIn("caf\u00e9", canonical_payload_bytes(from_yaml).decode("utf-8"))

    def test_parse_02_duplicate_json_key_is_rejected(self) -> None:
        self.assertCode(BM_DUPLICATE_KEY, loads_json, '{"a": 1, "a": 2}')

    def test_parse_03_duplicate_yaml_key_is_rejected(self) -> None:
        self.assertCode(BM_DUPLICATE_KEY, loads_yaml, "a: 1\na: 2\n")
        self.assertCode(
            BM_DUPLICATE_KEY, loads_yaml, "outer:\n  inner: 1\n  inner: 2\n"
        )

    def test_parse_04_unsafe_yaml_tags_are_rejected(self) -> None:
        self.assertCode(
            BM_UNSAFE_INPUT,
            loads_yaml,
            "value: !!python/object/apply:os.system ['echo hi']\n",
        )
        self.assertCode(BM_UNSAFE_INPUT, loads_yaml, "value: !CustomTag 1\n")
        self.assertCode(BM_UNSAFE_INPUT, loads_yaml, "value: !!set {a: null}\n")
        self.assertCode(BM_UNSAFE_INPUT, loads_yaml, "value: !!binary aGk=\n")

    def test_parse_05_yaml_anchor_alias_and_merge_keys_are_rejected(self) -> None:
        self.assertCode(BM_UNSAFE_INPUT, loads_yaml, "a: &anchor 1\nb: *anchor\n")
        self.assertCode(
            BM_UNSAFE_INPUT,
            loads_yaml,
            "base: &base {x: 1}\nchild:\n  <<: *base\n  y: 2\n",
        )

    def test_parse_06_multiple_yaml_documents_are_rejected(self) -> None:
        self.assertCode(BM_UNSAFE_INPUT, loads_yaml, "a: 1\n---\nb: 2\n")

    def test_parse_07_non_finite_numbers_are_rejected(self) -> None:
        self.assertCode(BM_UNSAFE_INPUT, loads_json, '{"a": NaN}')
        self.assertCode(BM_UNSAFE_INPUT, loads_json, '{"a": Infinity}')
        self.assertCode(BM_UNSAFE_INPUT, loads_json, '{"a": -Infinity}')
        self.assertCode(BM_UNSAFE_INPUT, loads_yaml, "a: .nan\n")
        self.assertCode(BM_UNSAFE_INPUT, loads_yaml, "a: .inf\n")

    def test_parse_08_invalid_utf8_and_bom_are_rejected(self) -> None:
        self.assertCode(BM_UNSAFE_INPUT, decode_text, b"\xff\xfe\x00")
        self.assertCode(BM_UNSAFE_INPUT, decode_text, b"\xef\xbb\xbf{}")

    def test_parse_09_size_depth_and_node_limits(self) -> None:
        element = '"' + "x" * (codec.MAX_SCALAR_BYTES - 2) + '"'
        tail = '"' + "y" * 3837 + '"'
        exact = "[" + ",".join([element] * 255 + [tail]) + "]"
        self.assertEqual(len(exact.encode("utf-8")), MAX_DOCUMENT_BYTES)
        self.assertEqual(len(loads_json(exact)), 256)

        self.assertCode(
            BM_UNSAFE_INPUT, decode_text, (exact + " ").encode("utf-8")
        )

        self.assertCode(
            BM_UNSAFE_INPUT, loads_json, '["' + "x" * (codec.MAX_SCALAR_BYTES + 1) + '"]'
        )
        loads_json('["' + "x" * codec.MAX_SCALAR_BYTES + '"]')

        allowed = "[" * 32 + "0" + "]" * 32
        loads_json(allowed)
        rejected = "[" * 33 + "0" + "]" * 33
        self.assertCode(BM_UNSAFE_INPUT, loads_json, rejected)

        too_many = "[" + ",".join(["[]"] * (codec.MAX_COLLECTION_NODES + 1)) + "]"
        self.assertCode(BM_UNSAFE_INPUT, loads_json, too_many)

    def test_parse_10_invalid_types_and_versions_fail_closed(self) -> None:
        protocol = copy.deepcopy(_fixture("protocol.yaml"))
        protocol["schedule"]["seed"] = True
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, protocol)

        protocol = copy.deepcopy(_fixture("protocol.yaml"))
        protocol["schedule"]["seed"] = -1
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, protocol)

        protocol = copy.deepcopy(_fixture("protocol.yaml"))
        protocol["schedule"]["seed"] = 2**64
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, protocol)

        protocol = copy.deepcopy(_fixture("protocol.yaml"))
        protocol["schedule"]["unexpected"] = 1
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, protocol)

        protocol = copy.deepcopy(_fixture("protocol.yaml"))
        protocol["schema_version"] = 2
        self.assertCode(BM_SCHEMA_UNSUPPORTED, validate_protocol, protocol)

        protocol = copy.deepcopy(_fixture("protocol.yaml"))
        del protocol["kind"]
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, protocol)

        protocol = copy.deepcopy(_fixture("protocol.yaml"))
        protocol["schedule"]["mode"] = "seeded"
        self.assertCode(BM_SCHEMA_INVALID, validate_protocol, protocol)

        workload = copy.deepcopy(_fixture("workloads.yaml"))
        duplicate = copy.deepcopy(workload["lanes"][0])
        duplicate["params"]["top_k"] = 20
        workload["lanes"].append(duplicate)
        self.assertCode(BM_IDENTITY_INVALID, validate_workload, workload)

        experiment = copy.deepcopy(_fixture("experiment.yaml"))
        experiment["arms"].append(
            {
                "arm_id": "baseline",
                "adapter_id": "synthetic-smoke",
                "variant": "shadow",
            }
        )
        self.assertCode(BM_IDENTITY_INVALID, validate_experiment, experiment)

        adapter = copy.deepcopy(_fixture("adapter.yaml"))
        adapter["timeouts"]["setup_ms"] = 0
        self.assertCode(BM_SCHEMA_INVALID, validate_adapter, adapter)

        self.assertCode(BM_UNSAFE_INPUT, loads_yaml, "when: 2020-01-01\n")
        self.assertCode(BM_SCHEMA_INVALID, loads_yaml, "a: [1, 2\n")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()

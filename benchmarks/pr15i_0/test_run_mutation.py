#!/usr/bin/env python3
"""Deterministic tests for ``benchmarks/pr15i_0/run_mutation.py``.

The wrapper is exercised with a synthetic prepared-index tree and a *fake probe*
executable that emits a well-formed (or deliberately broken) breakdown. The real
probe's own semantics are covered by the Rust contract suite; these tests prove
the wrapper cross-checks the inventory, the active object identity and index
immutability, and never writes inside a prepared index.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_mutation  # noqa: E402  (module under test)

SOURCE = "0123456789abcdef0123456789abcdef01234567"
OTHER_SOURCE = "fedcba9876543210fedcba9876543210fedcba98"
CORPUS_MANIFEST = "1" * 64

FAKE_PROBE = r'''#!/usr/bin/env python3
"""Fake probe: emits a breakdown derived from the prepared index it is given."""
import argparse, hashlib, json, os, sys

parser = argparse.ArgumentParser(allow_abbrev=False)
parser.add_argument("--index-root", required=True)
parser.add_argument("--max-bytes", required=True, type=int)
parser.add_argument("--source-sha", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()

state_dir = os.path.join(args.index_root, "index", "state")
names = sorted(os.listdir(state_dir))
relative = "index/state/" + names[0]
path = os.path.join(args.index_root, relative)
data = open(path, "rb").read()
digest = hashlib.sha256(data).hexdigest()

components = {
    "state_header_bytes": 6,
    "row_key_prefix_bytes": 2,
    "row_key_bytes": 4,
    "row_revision_bytes": 8,
    "row_status_bytes": 1,
    "live_pointer_prefix_bytes": 2,
    "live_pointer_id_bytes": 3,
    "live_doc_id_bytes": 8,
    "replay_header_bytes": 4,
    "replay_token_prefix_bytes": 0,
    "replay_token_bytes": 0,
    "replay_fingerprint_bytes": 0,
    "replay_key_prefix_bytes": 0,
    "replay_key_bytes": 0,
    "replay_intent_bytes": 0,
    "replay_revision_bytes": 0,
    "batch_replay_opaque_bytes": 0,
}
fixed = sum(
    value for key, value in components.items() if key != "batch_replay_opaque_bytes"
)
components["batch_replay_opaque_bytes"] = len(data) - fixed
payload = len(data)
report = {
    "schema": "pr15i-0-mutation-breakdown-v1",
    "source_sha": args.source_sha,
    "qualified": True,
    "active_state_key": MUTATED_KEY or relative,
    "sidecar_sha256": MUTATED_DIGEST or digest,
    "sidecar_file_bytes": len(data),
    "payload_bytes": payload,
    "container_overhead_bytes": 0,
    "payload_version": 1,
    "row_count": 0,
    "live_count": 0,
    "deleted_count": 0,
    "replay_count": 0,
    "batch_replay_detail": "NOT_APPLICABLE",
    "component_bytes": components,
}
if MUTATED_COMPONENT:
    report["component_bytes"]["row_key_bytes"] += 1
with open(args.out, "x", encoding="utf-8") as handle:
    handle.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
print("captured")
'''


def canonical_json_bytes(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        + b"\n"
    )


def write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(canonical_json_bytes(payload))


class Tree:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="pr15i0-mutation-")
        os.makedirs(os.path.join(self.root, "benchmarks", "pr15i_0"), exist_ok=True)
        with open(
            os.path.join(self.root, run_mutation.PROTOCOL_REL), "wb"
        ) as handle:
            handle.write(canonical_json_bytes(run_mutation_protocol()))
        self.prepared = os.path.join(self.root, "target", "pr15e", "prepared-01")
        self.pr15f_run = os.path.join(self.root, "target", "pr15f", "run-01")
        self.out = os.path.join(self.root, "target", "pr15i-0", "mutation-01")
        self.probe = os.path.join(self.root, "target", "pr15i-0", "fake-probe.py")
        self._build()

    def _build(self):
        indexes = {}
        for n in (10000, 100000):
            index_root = os.path.join(self.prepared, "indexes", f"n{n}")
            state_bytes = (f"state-payload-{n}".ljust(128, "x")).encode()
            digest = hashlib.sha256(state_bytes).hexdigest()
            files = {
                "index/CURRENT": b"current-" + str(n).encode(),
                "index/manifests/g-0000000000000001.manifest": b"manifest" + str(n).encode(),
                f"index/state/{digest}.state": state_bytes,
                "index/segments/segment.seg": b"segment" + str(n).encode(),
            }
            entries = []
            for relative, payload in files.items():
                path = os.path.join(index_root, relative)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(payload)
                entries.append(
                    {
                        "path": relative,
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
            entries.sort(key=lambda entry: entry["path"])
            content = hashlib.sha256(canonical_json_bytes(entries)).hexdigest()
            indexes[str(n)] = {
                "path": f"indexes/n{n}",
                "inventory": {
                    "bytes": sum(entry["bytes"] for entry in entries),
                    "entries": entries,
                    "file_count": len(entries),
                    "sha256": content,
                },
            }
            state_entry = [entry for entry in entries if entry["path"].startswith("index/state/")][0]
            write_json(
                os.path.join(self.pr15f_run, "inventory", f"n{n}.json"),
                {
                    "schema": "pr15f-index-inventory-v1",
                    "n": n,
                    "read_only": True,
                    "files": entries,
                    "total_file_bytes": sum(entry["bytes"] for entry in entries),
                    "mutation_state_file_bytes": state_entry["bytes"],
                    "content_sha256": content,
                },
            )
        write_json(
            os.path.join(self.prepared, "prepare.json"),
            {
                "schema": "pr15e-prepare-v1",
                "status": "PREPARED",
                "source": {"head_sha": SOURCE},
                "indexes": indexes,
            },
        )
        os.makedirs(os.path.dirname(self.probe), exist_ok=True)
        with open(self.probe, "w", encoding="utf-8") as handle:
            handle.write(
                FAKE_PROBE.replace(
                    "MUTATED_KEY or relative", repr(os.environ.get("FAKE_KEY", "")) + " or relative"
                )
                .replace(
                    "MUTATED_DIGEST or digest",
                    repr(os.environ.get("FAKE_DIGEST", "")) + " or digest",
                )
                .replace(
                    "MUTATED_COMPONENT",
                    "True" if os.environ.get("FAKE_COMPONENT") else "False",
                )
            )
        os.chmod(self.probe, os.stat(self.probe).st_mode | stat.S_IEXEC)

    def argv(self, **overrides):
        values = {
            "--root": self.root,
            "--prepared-run": self.prepared,
            "--pr15f-run": self.pr15f_run,
            "--source-sha": SOURCE,
            "--out": self.out,
            "--probe": self.probe,
        }
        values.update(overrides)
        argv = []
        for key, value in values.items():
            argv.extend([key, value])
        return argv

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def run_mutation_protocol() -> dict:
    return {
        "schema": "pr15i-0-measurement-contract-v1",
        "corpus": "pr15d_v1",
        "document_counts": [10000, 100000],
        "three_engine": {
            "engines": ["quervant", "tantivy", "lucene"],
            "trials": 3,
            "require_original_oracle": True,
            "require_clear_contention": True,
            "require_native_filesystem": True,
        },
        "quervant_profile": {
            "runner": "benchmarks/pr15f/run.py",
            "warm_query_lanes": 9,
            "reopen_single_processes": 42,
            "allocation_optional": True,
            "report_inclusive_exclusive_separately": True,
        },
        "mutation_probe": {
            "allowed_payload_versions": [1, 2],
            "read_only": True,
            "max_file_bytes": 268435456,
            "unsupported_batch_detail": "opaque_remainder",
            "require_exact_byte_reconciliation": True,
        },
        "prohibited": [
            "production_code_change",
            "frozen_input_change",
            "historical_seal_change",
            "new_codec_candidate",
        ],
    }


class MutationRunTests(unittest.TestCase):
    def setUp(self):
        for name in ("FAKE_KEY", "FAKE_DIGEST", "FAKE_COMPONENT"):
            os.environ.pop(name, None)
        self.tree = Tree()

    def tearDown(self):
        for name in ("FAKE_KEY", "FAKE_DIGEST", "FAKE_COMPONENT"):
            os.environ.pop(name, None)
        self.tree.cleanup()

    def test_captures_both_corpora_and_writes_manifest(self):
        code = run_mutation.main(self.tree.argv())
        self.assertEqual(code, 0)
        with open(
            os.path.join(self.tree.out, "manifest.json"), encoding="utf-8"
        ) as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["schema"], "pr15i-0-mutation-run-v1")
        self.assertTrue(manifest["read_only"])
        self.assertEqual(sorted(manifest["n"]), ["10000", "100000"])
        self.assertTrue(manifest["n"]["10000"]["index_files_unchanged"])
        self.assertEqual(len(manifest["probe"]["sha256"]), 64)

    def test_output_directory_is_exclusive(self):
        self.assertEqual(run_mutation.main(self.tree.argv()), 0)
        code = run_mutation.main(self.tree.argv())
        self.assertNotEqual(code, 0)

    def test_source_mismatch_is_refused(self):
        code = run_mutation.main(self.tree.argv(**{"--source-sha": OTHER_SOURCE}))
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(self.tree.out))

    def test_malformed_source_is_refused(self):
        code = run_mutation.main(self.tree.argv(**{"--source-sha": "NOPE"}))
        self.assertNotEqual(code, 0)

    def test_probe_key_mismatch_is_refused(self):
        os.environ["FAKE_KEY"] = "index/state/not-the-active-object.state"
        self.tree = Tree()
        code = run_mutation.main(self.tree.argv())
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tree.out, "manifest.json")))

    def test_probe_digest_mismatch_is_refused(self):
        os.environ["FAKE_DIGEST"] = "0" * 64
        self.tree = Tree()
        code = run_mutation.main(self.tree.argv())
        self.assertNotEqual(code, 0)

    def test_component_mismatch_is_refused(self):
        os.environ["FAKE_COMPONENT"] = "1"
        self.tree = Tree()
        code = run_mutation.main(self.tree.argv())
        self.assertNotEqual(code, 0)

    def test_probe_failure_writes_no_manifest(self):
        broken = os.path.join(self.tree.root, "target", "pr15i-0", "broken-probe.sh")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 3\n")
        os.chmod(broken, 0o755)
        code = run_mutation.main(self.tree.argv(**{"--probe": broken}))
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tree.out, "manifest.json")))

    def test_protocol_retuning_is_refused(self):
        protocol = run_mutation_protocol()
        protocol["mutation_probe"]["max_file_bytes"] = 1024
        write_json(
            os.path.join(self.tree.root, run_mutation.PROTOCOL_REL), protocol
        )
        code = run_mutation.main(self.tree.argv())
        self.assertNotEqual(code, 0)

    def test_retuned_max_bytes_flag_is_refused(self):
        code = run_mutation.main(self.tree.argv(**{"--max-bytes": "999999999"}))
        self.assertNotEqual(code, 0)

    def test_prepared_index_is_not_mutated(self):
        protected = os.path.join(self.tree.prepared, "indexes", "n100000", "index", "state")
        before = {
            name: os.path.getmtime(os.path.join(protected, name))
            for name in os.listdir(protected)
        }
        self.assertEqual(run_mutation.main(self.tree.argv()), 0)
        after = {
            name: os.path.getmtime(os.path.join(protected, name))
            for name in os.listdir(protected)
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()

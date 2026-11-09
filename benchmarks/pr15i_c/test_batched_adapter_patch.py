#!/usr/bin/env python3
"""Tests for the source-locked derived diagnostic adapter patch (B-V adapter proof).

A handful of these tests build the derived adapter against the workspace core so
that the patched crate is proven to compile and that its untouched single-query
path still answers the frozen oracle. The build is cached in a module-level
temporary directory so the suite stays bounded.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load():
    spec = importlib.util.spec_from_file_location(
        "pr15i_c_batched_adapter_patch", os.path.join(HERE, "batched_adapter_patch.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patcher = load()

_CACHE = {}


def derived_crate():
    """Materialize + build one derived adapter, cached for the whole test run."""
    if "crate" in _CACHE:
        return _CACHE["crate"]
    workdir = tempfile.mkdtemp(prefix="pr15i-batched-adapter-")
    destination = os.path.join(workdir, "crate")
    record = patcher.materialize(
        ROOT, destination, os.path.join(ROOT, "crates", "quervant-core"))
    binary = patcher.build(destination, os.path.join(workdir, "target"))
    record["binary"] = binary
    record["destination"] = destination
    _CACHE["crate"] = record
    return record


def cleanup():
    crate = _CACHE.pop("crate", None)
    if crate:
        shutil.rmtree(os.path.dirname(crate["destination"]), ignore_errors=True)


def tearDownModule():
    cleanup()


class FrozenSourceTests(unittest.TestCase):
    def test_frozen_blob_hash_is_pinned(self):
        source = patcher.frozen_source(ROOT)
        self.assertEqual(patcher.sha256_bytes(source.encode("utf-8")),
                         patcher.EXPECTED_MAIN_SHA)

    def test_bv01_source_drift_is_rejected(self):
        source = patcher.frozen_source(ROOT)
        drifted = source.replace("const SCHEMA: &str = \"pr15d-adapter-v1\";",
                                 "const SCHEMA: &str = \"pr15d-adapter-v2\";")
        self.assertNotEqual(drifted, source)
        with self.assertRaises(patcher.PatchError):
            patcher.patch_source(drifted)

    def test_bv02_missing_handler_anchor_is_rejected(self):
        source = patcher.frozen_source(ROOT)
        poisoned = source.replace(patcher.BATCH_HANDLER_ANCHOR, "\n// anchor removed\n")
        with self.assertRaises(patcher.PatchError):
            patcher.patch_source(poisoned)

    def test_bv03_duplicate_anchor_is_rejected(self):
        source = patcher.frozen_source(ROOT)
        poisoned = source.replace(patcher.ARM_ANCHOR,
                                  patcher.ARM_ANCHOR + "\n" + patcher.ARM_ANCHOR, 1)
        with self.assertRaises(patcher.PatchError):
            patcher.patch_source(poisoned)

    def test_bv04_altered_frozen_function_is_rejected(self):
        source = patcher.frozen_source(ROOT)
        poisoned = source.replace(
            "    let started = Instant::now();\n    let response = searcher",
            "    let started = Instant::now();\n    // tampered\n    let response = searcher", 1)
        self.assertNotEqual(poisoned, source)
        with self.assertRaises(patcher.PatchError):
            patcher.patch_source(poisoned)

    def test_protocol_pin_is_enforced(self):
        protocol = patcher.load_protocol(ROOT)
        self.assertEqual(protocol["frozen_adapter_main_rs_sha256"],
                         patcher.EXPECTED_MAIN_SHA)
        self.assertEqual(protocol["repeat_count_short"], 100)
        self.assertEqual(protocol["repeat_count_control"], 1)


class PatchContentTests(unittest.TestCase):
    def setUp(self):
        self.derived, self.frozen_hashes = patcher.patch_source(
            patcher.frozen_source(ROOT))

    def test_bv05_query_batch_is_routed_exactly_once(self):
        self.assertEqual(self.derived.count('"query_batch" =>'), 1)
        self.assertEqual(self.derived.count("fn handle_query_batch("), 1)
        self.assertEqual(self.derived.count("fn query_batch("), 1)

    def test_bv06_batched_reply_has_no_engine_ns(self):
        region = self.derived[self.derived.index("fn handle_query_batch("):]
        region = region[:region.index("\n}\n")]
        self.assertNotIn('"engine_ns"', region)
        self.assertIn('"batch_ns"', region)
        self.assertIn('"repeat_count"', region)

    def test_bv07_repeat_count_is_restricted_to_one_or_hundred(self):
        region = self.derived[self.derived.index("fn handle_query_batch("):]
        region = region[:region.index("\n}\n")]
        self.assertIn("repeat_count != 1 && repeat_count != 100", region)

    def test_bv08_single_outer_instant_and_sequential_search(self):
        region = self.derived[self.derived.index("fn handle_query_batch("):]
        region = region[:region.index("\n}\n")]
        self.assertEqual(region.count("Instant::now()"), 1)
        self.assertIn("for _ in 0..iterations", region)
        self.assertIn("search(snapshot, field, term, k)?", region)

    def test_bv09_iteration_parity_check_is_present(self):
        region = self.derived[self.derived.index("fn handle_query_batch("):]
        region = region[:region.index("\n}\n")]
        self.assertIn("batch_mismatch", region)

    def test_bv10_frozen_functions_are_unchanged(self):
        after = {
            "search": patcher.function_sha(self.derived, "fn search("),
            "handle_query": patcher.function_sha(self.derived, "fn handle_query("),
            "query": patcher.function_sha(
                self.derived,
                "    fn query(&self, request: &Value) -> Result<Value, AdapterError> {"),
        }
        self.assertEqual(after, self.frozen_hashes)

    def test_bv11_existing_query_path_is_untouched(self):
        original = patcher.frozen_source(ROOT)
        for marker in ('"query" => {', '"build" => {', '"metadata" => Ok(json!({',
                       '"shutdown" => {'):
            self.assertEqual(self.derived.count(marker), original.count(marker))

    def test_bv12_derived_source_is_deterministic(self):
        first = patcher.sha256_bytes(self.derived.encode("utf-8"))
        second = patcher.sha256_bytes(
            patcher.patch_source(patcher.frozen_source(ROOT))[0].encode("utf-8"))
        self.assertEqual(first, second)

    def test_bv13_no_new_dependency_is_added(self):
        blobs = patcher.frozen_blobs(ROOT)
        manifest = blobs["Cargo.toml"].decode("utf-8")
        self.assertEqual(manifest.count("[dependencies]"), 1)
        self.assertIn("serde_json", manifest)
        self.assertNotIn("unsafe", self.derived)


class DerivedCrateTests(unittest.TestCase):
    def test_bv14_derived_crate_builds_and_keeps_the_original_query_path(self):
        crate = derived_crate()
        self.assertTrue(os.path.isfile(crate["binary"]))
        self.assertEqual(len(crate["derived_main_sha256"]), 64)
        # Feed the frozen single-query protocol: the derived adapter must answer
        # exactly like the original (schema/engine/status + engine_ns present).
        index_dir = build_fixture_index()
        result = subprocess.run(
            [crate["binary"], "--index-dir", index_dir],
            input=json.dumps({
                "request_id": "q1", "op": "query", "field": "key",
                "term": "common", "k": 10, "mode": "warm",
            }) + "\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        reply = json.loads(result.stdout.strip())
        self.assertEqual(reply["schema"], "pr15d-adapter-v1")
        self.assertEqual(reply["status"], "ok")
        self.assertIn("engine_ns", reply)
        self.assertEqual(reply["total_hits"], 40)
        self.assertEqual(len(reply["doc_ids"]), 10)

    def test_bv15_query_batch_returns_raw_batch_ns_only(self):
        crate = derived_crate()
        index_dir = build_fixture_index()
        result = subprocess.run(
            [crate["binary"], "--index-dir", index_dir],
            input=json.dumps({
                "request_id": "b1", "op": "query_batch", "field": "key",
                "term": "common", "k": 10, "repeat_count": 100,
            }) + "\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        reply = json.loads(result.stdout.strip())
        self.assertNotIn("engine_ns", reply)
        self.assertEqual(reply["repeat_count"], 100)
        self.assertIsInstance(reply["batch_ns"], int)
        self.assertGreater(reply["batch_ns"], 0)
        self.assertEqual(reply["total_hits"], 40)

    def test_bv16_invalid_repeat_count_is_a_typed_error(self):
        crate = derived_crate()
        index_dir = build_fixture_index()
        for repeat in (0, 2, 50, 101):
            result = subprocess.run(
                [crate["binary"], "--index-dir", index_dir],
                input=json.dumps({
                    "request_id": f"bad{repeat}", "op": "query_batch", "field": "key",
                    "term": "common", "k": 10, "repeat_count": repeat,
                }) + "\n",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            reply = json.loads(result.stdout.strip())
            self.assertEqual(reply["status"], "error")
            self.assertEqual(reply["error"]["kind"], "request")


def build_fixture_index():
    """Build one tiny real index with the frozen adapter's own build op."""
    if "index" in _CACHE:
        return _CACHE["index"]
    crate = derived_crate()
    directory = os.path.join(os.path.dirname(crate["destination"]), "fixture")
    os.makedirs(directory, exist_ok=True)
    corpus = os.path.join(directory, "corpus.tsv")
    with open(corpus, "w", encoding="utf-8") as handle:
        handle.write("doc_id\tkey\tgroup\tbody\tpayload\n")
        for position in range(40):
            handle.write(f"d{position:04}\tcommon\tg\tbody{position}\tp{position}\n")
        for position in range(40, 80):
            handle.write(f"d{position:04}\tother\tg\tbody{position}\tp{position}\n")
    index_dir = os.path.join(directory, "index")
    payload = json.dumps({
        "request_id": "build", "op": "build",
        "corpus_path": corpus, "index_dir": index_dir,
    }) + "\n"
    result = subprocess.run(
        [crate["binary"]], input=payload, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"fixture build failed: {result.stderr[-500:]}")
    _CACHE["index"] = index_dir
    return index_dir


if __name__ == "__main__":
    unittest.main()

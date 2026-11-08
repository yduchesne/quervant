"""Adversarial independent-verifier tests (PR 15I-A review fixup).

Synthetic fixtures contain the full accepted raw schema and are mutated one
field at a time. They live in a temporary fake checkout under the system temp
directory; no production evidence or published benchmark result is created.
The real-campaign class (FT-A49..A53) runs read-only against
``target/pr15i-a/campaigns/paired-04``.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("pr15i_a_run_for_verify_tests", os.path.join(HERE, "run.py"))
verify = _load("pr15i_a_verify_under_test", os.path.join(HERE, "verify.py"))
test_run = _load("pr15i_a_run_test_helpers", os.path.join(HERE, "test_run.py"))

REAL_CAMPAIGN = os.path.join(ROOT, "target", "pr15i-a", "campaigns", "paired-04")
SOURCES = dict(verify.EXPECTED_SOURCES)
SCOPE = [
    "benchmarks/pr15i_a/run.py",
    "crates/quervant-core/src/segment/format.rs",
]
DESCRIPTORS = run.base.stage_lanes("final")
ROWS = [
    ("d000", "common", "medium", "body", "payload"),
    ("d001", "common", "medium", "body", "payload"),
    ("d002", "singleton", "other", "body", "payload"),
    ("d003", "common", "other", "body", "payload"),
    ("d004", "other", "other", "body", "payload"),
]


def _sizes() -> dict:
    return {
        "A": {
            "10000": {
                "sidecar_bytes": 960_180,
                "segment_bytes": 2_129_038,
                "manifest_bytes": 636,
                "current_bytes": 183,
                "committed_index_bytes": 3_090_037,
                "state_containers": [
                    {
                        "bytes": 960_180,
                        "path": "a" * 64 + ".state",
                        "payload_bytes": 960_010,
                        "payload_version": 1,
                        "required_features": [[1, 1], [8, 1]],
                        "sha256": "a" * 64,
                    }
                ],
            },
            "100000": {
                "sidecar_bytes": 9_600_180,
                "segment_bytes": 21_364_026,
                "manifest_bytes": 636,
                "current_bytes": 183,
                "committed_index_bytes": 30_965_025,
                "state_containers": [
                    {
                        "bytes": 9_600_180,
                        "path": "b" * 64 + ".state",
                        "payload_bytes": 9_600_010,
                        "payload_version": 1,
                        "required_features": [[1, 1], [8, 1]],
                        "sha256": "b" * 64,
                    }
                ],
            },
        },
        "B": {
            "10000": {
                "sidecar_bytes": 230_132,
                "segment_bytes": 2_129_038,
                "manifest_bytes": 644,
                "current_bytes": 183,
                "committed_index_bytes": 2_359_997,
                "state_containers": [
                    {
                        "bytes": 230_132,
                        "path": "c" * 64 + ".state",
                        "payload_bytes": 229_958,
                        "payload_version": 3,
                        "required_features": [[1, 1], [8, 1], [12, 1]],
                        "sha256": "c" * 64,
                    }
                ],
            },
            "100000": {
                "sidecar_bytes": 2_383_748,
                "segment_bytes": 21_364_026,
                "manifest_bytes": 644,
                "current_bytes": 183,
                "committed_index_bytes": 23_748_601,
                "state_containers": [
                    {
                        "bytes": 2_383_748,
                        "path": "d" * 64 + ".state",
                        "payload_bytes": 2_383_574,
                        "payload_version": 3,
                        "required_features": [[1, 1], [8, 1], [12, 1]],
                        "sha256": "d" * 64,
                    }
                ],
            },
        },
    }


def _binary_hashes() -> dict:
    return {
        arm: {
            name: hashlib.sha256(f"{arm}:{name}".encode("utf-8")).hexdigest()
            for name in verify.BINARY_RELATIVE
        }
        for arm in ("A", "B")
    }


def _slots(binary: dict) -> list:
    slots = []
    index = 0
    for block, order in enumerate(run.SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            index += 1
            lanes = []
            for descriptor in DESCRIPTORS:
                expected = run.base.oracle.expected(
                    rows=ROWS,
                    field=descriptor["field"],
                    term=descriptor["term"],
                    k=descriptor["k"],
                )
                samples = [10_000 + 10 * sample + index for sample in range(run.MEASURED)]
                lanes.append(
                    {
                        "id": descriptor["id"],
                        "n": descriptor["n"],
                        "class": descriptor["class"],
                        "field": descriptor["field"],
                        "term": descriptor["term"],
                        "k": descriptor["k"],
                        "regime": descriptor["regime"],
                        "warmups": run.WARMUPS,
                        "warmup_ids": [
                            f"{descriptor['id']}:warmup:{warmup}"
                            for warmup in range(run.WARMUPS)
                        ],
                        "samples_ns": samples,
                        "summary_ns": run.base.pr15d_run.summarize(samples),
                        "total_hits": expected["total_hits"],
                        "expected_total_hits": expected["total_hits"],
                        "doc_ids": expected["doc_ids"],
                        "expected_doc_ids": expected["doc_ids"],
                        "oracle_ok": True,
                        "contention": {"state": "clear", "reason_codes": []},
                    }
                )
            contention = {"state": "clear", "reason_codes": []}
            slots.append(
                {
                    "slot_index": index,
                    "block": block,
                    "position": position,
                    "arm": arm,
                    "source_sha": SOURCES[arm],
                    "binary_sha256": binary[arm]["adapter"],
                    "trial": {
                        "index": index,
                        "started_utc": "2026-11-07T00:00:00Z",
                        "ended_utc": "2026-11-07T00:01:00Z",
                        "contention_before": contention,
                        "contention_after": copy.deepcopy(contention),
                        "lanes": lanes,
                    },
                }
            )
    return slots


def _blocks() -> dict:
    result = {"A": {}, "B": {}}
    for arm in ("A", "B"):
        result[arm]["reopen"] = [
            {
                "block": block,
                "samples": [
                    {"block": block, "sample": sample, "open_ns": 1_000_000_000,
                     "maxrss_bytes": 128 * 1024 * 1024, "documents": 100_000}
                    for sample in range(2)
                ],
            }
            for block in range(1, run.BLOCKS + 1)
        ]
        result[arm]["build_commit"] = [
            {
                "block": block,
                "samples": [
                    {
                        "block": block,
                        "sample": sample,
                        "index_ns": 2_000_000_000,
                        "commit_ns": 1_000_000_000,
                        "maxrss_bytes": 256 * 1024 * 1024,
                        "documents_indexed": 100_000,
                        "documents_verified": 100_000,
                        "index_bytes": 23_748_601,
                        "measured_index_bytes": 23_748_601,
                    }
                    for sample in range(2)
                ],
            }
            for block in range(1, run.BLOCKS + 1)
        ]
        result[arm]["remote"] = [
            {
                "block": block,
                "samples": [
                    {"block": block, "sample": sample, "open_ns": 2_000_000_000,
                     "maxrss_bytes": 192 * 1024 * 1024, "documents": 100_000}
                    for sample in range(2)
                ],
            }
            for block in range(1, run.BLOCKS + 1)
        ]
    result["block_arm_order"] = [list(order) for order in run.BLOCK_ARM_ORDER]
    return result


def _arm_for(arm: str, sizes: dict, blocks: dict, slots: list, binary: dict) -> dict:
    return {
        "arm": arm,
        "source_sha": SOURCES[arm],
        "sizes": {"n": sizes[arm], "indices": {}},
        "blocks": {kind: blocks[arm][kind] for kind in ("reopen", "build_commit", "remote")},
        "warm": [slot for slot in slots if slot["arm"] == arm],
        "oracles_ok": True,
        "feature_checks_ok": True,
        "adapter_sha256": binary[arm]["adapter"],
        "reopen_sha256": binary[arm]["reopen"],
        "remote_sha256": binary[arm]["remote"],
    }


def _documents(binary: dict, sizes: dict | None = None) -> dict:
    sizes = sizes or _sizes()
    blocks = _blocks()
    slots = _slots(binary)
    derived, _ = run.derive(
        _arm_for("A", sizes, blocks, slots, binary),
        _arm_for("B", sizes, blocks, slots, binary),
    )
    measurements = {
        **derived,
        "schema": run.SCHEMA,
        "sources": dict(SOURCES),
        "binary_sha256": copy.deepcopy(binary),
        "scope_diff": sorted(SCOPE),
        "environment_fingerprint": verify.EXPECTED_ENV_FINGERPRINT,
        "corpus_manifest_sha256": verify.EXPECTED_CORPUS_MANIFEST,
    }
    manifest = {
        "schema": run.SCHEMA,
        "sources": dict(SOURCES),
        "binary_sha256": copy.deepcopy(binary),
        "sizes": copy.deepcopy(sizes),
        "environment_fingerprint": verify.EXPECTED_ENV_FINGERPRINT,
        "corpus_manifest_sha256": verify.EXPECTED_CORPUS_MANIFEST,
        "filesystem": "ext4",
    }
    authorization = {
        "schema": run.SCHEMA,
        "operator_idle_authorized_by_user": True,
        "recorded_utc": "2026-11-07T00:00:00Z",
        "filesystem": "ext4",
    }
    return {
        "manifest": manifest,
        "measurements": measurements,
        "authorization": authorization,
        "blocks": blocks,
        "slots": slots,
    }


class FixtureGit:
    def __init__(self, *, blob=None, production=True, protocol_clean=True, head=None):
        self.blob = blob or verify.EXPECTED_PROTOCOL_BLOB
        self.production = production
        self.protocol_clean = protocol_clean
        self.head_sha = head or "f" * 40

    def head(self):
        return self.head_sha

    def cat_file_type(self, _sha):
        return "commit"

    def is_ancestor(self, _ancestor, _descendant):
        return True

    def changed_paths(self, _base, _candidate):
        return sorted(SCOPE)

    def hash_object(self, _relative):
        return self.blob

    def diff_empty(self, _base, _candidate, _relative):
        return self.protocol_clean

    def production_identical(self, _base, _candidate):
        return self.production


def _size_seam(_campaign, _sizes):
    """Synthetic filesystem-proof seam: exactly the mandatory four-group mapping."""
    return dict(verify.EXPECTED_SIZE_REPRODUCIBILITY)


def _corpus_seam(_campaign):
    return verify.EXPECTED_CORPUS_MANIFEST, {10_000: ROWS, 100_000: ROWS}


def _state_container(payload_version: int, payload_bytes: int, features) -> bytes:
    """Build a minimally valid mutation-state container of the exact size."""
    header = bytearray(24)
    header[0:8] = b"TRWMSV01"
    struct.pack_into("<H", header, 8, 1)
    struct.pack_into("<H", header, 10, 0)
    header[12] = 1
    header[13] = 24
    struct.pack_into("<Q", header, 16, 0)
    body = bytearray(payload_bytes)
    struct.pack_into("<H", body, 0, payload_version)
    footer = bytearray()
    footer += struct.pack("<H", 1)
    footer += struct.pack("<I", 1)
    footer += struct.pack("<I", len(features))
    for feature_id, version in features:
        footer += struct.pack("<HH", feature_id, version)
    footer += struct.pack("<I", 0)
    footer += struct.pack("<H", 0x000F)
    footer += struct.pack("<H", 0)
    footer += struct.pack("<Q", 0)
    footer += struct.pack("<Q", 24)
    footer += struct.pack("<Q", payload_bytes)
    footer += b"\x00" * 32
    trailer = bytearray()
    trailer += b"TRWSTR01"
    trailer += struct.pack("<Q", 24 + payload_bytes)
    trailer += struct.pack("<Q", len(footer))
    trailer += struct.pack("<I", 1)
    trailer += struct.pack("<H", 1)
    trailer += struct.pack("<H", 0)
    trailer += b"\x00" * 32
    return bytes(header) + bytes(body) + bytes(footer) + bytes(trailer)


def _write_sparse(path: str, size: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.truncate(size)


def _write_size_index(directory: str, record: dict) -> None:
    container_record = record["state_containers"][0]
    container = _state_container(
        container_record["payload_version"],
        container_record["payload_bytes"],
        container_record["required_features"],
    )
    if len(container) != record["sidecar_bytes"]:
        raise AssertionError("synthetic state container size mismatch")
    digest = hashlib.sha256(container).hexdigest()
    state_dir = os.path.join(directory, "index", "state")
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, f"{digest}.state"), "wb") as handle:
        handle.write(container)
    _write_sparse(os.path.join(directory, "index", "segments", "x.seg"), record["segment_bytes"])
    _write_sparse(os.path.join(directory, "index", "manifests", "m.manifest"), record["manifest_bytes"])
    _write_sparse(os.path.join(directory, "index", "CURRENT"), record["current_bytes"])


def _build_real_sizes(campaign: str) -> dict:
    template = _sizes()
    sizes = {"A": {}, "B": {}}
    for arm in ("A", "B"):
        for n in ("10000", "100000"):
            record = copy.deepcopy(template[arm][n])
            for attempt in (1, 2, 3):
                directory = os.path.join(campaign, "setup", "sizes", arm, f"n{n}-run{attempt}")
                _write_size_index(directory, record)
            measured = run.measure_sizes(
                os.path.join(campaign, "setup", "sizes", arm, f"n{n}-run3")
            )
            sizes[arm][n] = measured
    return sizes


class Fixture:
    def __init__(self, tag, *, mutate=None, drop_primary=(), extra_raw=None,
                 delete_after_seal=None, tamper_after_seal=None, aux_mutate=None,
                 delete_aux=None, binary_mutation=None, git=None, corpus_loader=None,
                 size_artifacts=None, symlink_after_seal=None, symlink_dir_after_seal=None,
                 real_sizes=False, delete_size_run=None, modify_size_run=None,
                 symlink_size_run=None):
        self.root = tempfile.mkdtemp(prefix=f"pr15ia-fixture-{tag}-")
        os.makedirs(os.path.join(self.root, "benchmarks", "pr15i_a"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "benchmarks", "reports", "pr15i-a"), exist_ok=True)
        shutil.copy2(
            os.path.join(ROOT, "benchmarks", "pr15i_a", "protocol.json"),
            os.path.join(self.root, "benchmarks", "pr15i_a", "protocol.json"),
        )
        self.campaign = os.path.join(self.root, "target", "pr15i-a", "campaigns", "fixture")
        os.makedirs(os.path.join(self.campaign, "raw", "slots"), exist_ok=True)
        binary = _binary_hashes()
        if real_sizes:
            sizes = _build_real_sizes(self.campaign)
            if delete_size_run is not None:
                arm, n, attempt = delete_size_run
                shutil.rmtree(
                    os.path.join(
                        self.campaign, "setup", "sizes", arm, f"n{n}-run{attempt}"
                    )
                )
            if modify_size_run is not None:
                arm, n, attempt = modify_size_run
                path = os.path.join(
                    self.campaign, "setup", "sizes", arm, f"n{n}-run{attempt}",
                    "index", "segments", "x.seg",
                )
                with open(path, "r+b") as handle:
                    handle.truncate(1)
            if symlink_size_run is not None:
                arm, n, attempt, target = symlink_size_run
                path = os.path.join(self.campaign, "setup", "sizes", arm, f"n{n}-run{attempt}")
                shutil.rmtree(path)
                os.symlink(target, path)
            documents = _documents(binary, sizes)
        else:
            documents = _documents(binary)
        if mutate is not None:
            mutate(documents)
        self.documents = documents
        raw = os.path.join(self.campaign, "raw")
        primary = {
            "authorization.json": documents["authorization"],
            "blocks.json": documents["blocks"],
            "manifest.json": documents["manifest"],
            "measurements.json": documents["measurements"],
        }
        for name, value in primary.items():
            if name in drop_primary:
                continue
            _write(os.path.join(raw, name), value)
        for slot in documents["slots"]:
            _write(os.path.join(raw, "slots", f"slot-{slot['slot_index']:02d}.json"), slot)
        for arm in ("A", "B"):
            for name, parts in verify.BINARY_RELATIVE.items():
                relative = os.path.join("setup", "build", arm, *parts)
                path = os.path.join(self.campaign, relative)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                content = f"{arm}:{name}".encode("utf-8")
                if binary_mutation is not None and (arm, name) in binary_mutation:
                    content = binary_mutation[(arm, name)]
                with open(path, "wb") as handle:
                    handle.write(content)
                if binary_mutation is not None and (arm, name) == "delete":
                    os.unlink(path)
        # Auxiliary contention probes are unsealed but bound to the sealed slots.
        for slot in documents["slots"]:
            index = slot["slot_index"]
            for phase in ("before", "after"):
                _write(
                    os.path.join(
                        raw, "slots", f"slot-{index:02d}", "contention",
                        f"trial{index}-{phase}.json",
                    ),
                    slot["trial"][f"contention_{phase}"],
                )
        sealed = [relative for relative in verify.EXPECTED_RAW_FILES if relative not in drop_primary]
        seal = {
            "schema": run.SEAL_SCHEMA,
            "files": {
                relative: verify._sha256_file(os.path.join(raw, relative))
                for relative in sealed
            },
        }
        _write(os.path.join(raw, "seal.json"), seal)
        # Published and sanitized copies are derived from the same documents.
        for directory in (
            os.path.join(self.campaign, "sanitized"),
            os.path.join(self.root, "benchmarks", "reports", "pr15i-a"),
        ):
            os.makedirs(directory, exist_ok=True)
            _write(os.path.join(directory, "results.json"), documents["measurements"])
            _write(
                os.path.join(directory, "decision.json"),
                {
                    "decision": documents["measurements"]["decision"],
                    "gates": documents["measurements"]["gates"],
                },
            )
        if extra_raw is not None:
            _write(os.path.join(raw, extra_raw), {"note": "unexpected"})
        if aux_mutate is not None:
            relative, value = aux_mutate
            _write(os.path.join(raw, relative), value)
        if delete_aux is not None:
            os.unlink(os.path.join(raw, delete_aux))
        if symlink_dir_after_seal is not None:
            target = os.path.join(self.root, "outside-dir")
            os.makedirs(target, exist_ok=True)
            os.symlink(target, os.path.join(raw, symlink_dir_after_seal))
        if symlink_after_seal is not None:
            target = os.path.join(self.root, "outside.json")
            _write(target, {"outside": True})
            path = os.path.join(raw, symlink_after_seal)
            os.unlink(path)
            os.symlink(target, path)
        if tamper_after_seal is not None:
            relative, value = tamper_after_seal
            _write(os.path.join(raw, relative), value)
        if delete_after_seal is not None:
            os.unlink(os.path.join(raw, delete_after_seal))
        self.git = git or FixtureGit()
        self.corpus_loader = corpus_loader or _corpus_seam
        self.size_artifacts = size_artifacts or (_size_seam if not real_sizes else None)

    def verify(self):
        return verify.verify_campaign(
            self.root,
            self.campaign,
            git=self.git,
            corpus_loader=self.corpus_loader,
            size_artifacts=self.size_artifacts,
        )

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _write(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _read(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class FixtureTestCase(unittest.TestCase):
    def fixture(self, tag, **kwargs):
        fixture = Fixture(tag, **kwargs)
        self.addCleanup(fixture.close)
        return fixture

    def assertRejected(self, fixture, code):
        with self.assertRaises(verify.VerifyError) as context:
            fixture.verify()
        self.assertEqual(context.exception.code, code, context.exception.detail)
        return context.exception


class AcceptanceTests(FixtureTestCase):
    def test_ft_a01_complete_fixture_passes(self):
        fixture = self.fixture("a01")
        receipt = fixture.verify()
        self.assertTrue(receipt["qualified"])
        self.assertEqual(receipt["raw_files_verified"], 20)
        self.assertEqual(receipt["auxiliary_contention_files_verified"], 32)
        self.assertEqual(receipt["lane_records"], 144)
        self.assertEqual(receipt["sample_records"], 2880)


class SealTests(FixtureTestCase):
    def test_ft_a02_missing_authorization(self):
        fixture = self.fixture("a02", drop_primary={"authorization.json"})
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a03_extra_raw_file(self):
        fixture = self.fixture("a03", extra_raw="notes.txt")
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a04_missing_slot_after_reseal(self):
        fixture = self.fixture("a04", delete_after_seal="slots/slot-16.json")
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a05_unsafe_relative_path(self):
        def mutate(documents):
            documents["manifest"]["unused"] = True

        fixture = self.fixture("a05", mutate=mutate)
        seal_path = os.path.join(fixture.campaign, "raw", "seal.json")
        seal = _read(seal_path)
        seal["files"]["../escape.json"] = seal["files"].pop("authorization.json")
        _write(seal_path, seal)
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a06_symlink_to_outside(self):
        fixture = self.fixture("a06", symlink_after_seal="slots/slot-01.json")
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a07_uppercase_digest(self):
        fixture = self.fixture("a07")
        seal_path = os.path.join(fixture.campaign, "raw", "seal.json")
        seal = _read(seal_path)
        seal["files"]["authorization.json"] = seal["files"]["authorization.json"].upper()
        _write(seal_path, seal)
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a08_modified_record_without_reseal(self):
        fixture = self.fixture("a08")
        path = os.path.join(fixture.campaign, "raw", "measurements.json")
        value = _read(path)
        value["decision"] = "A_PERF_REJECTED_SAFE_ROLLBACK"
        _write(path, value)
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a08b_auxiliary_contention_differs(self):
        fixture = self.fixture(
            "a08b",
            aux_mutate=("slots/slot-03/contention/trial3-before.json", {"state": "clear"}),
        )
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a08c_missing_auxiliary_contention(self):
        fixture = self.fixture(
            "a08c", delete_aux="slots/slot-07/contention/trial7-after.json"
        )
        self.assertRejected(fixture, "A_SEAL")


class P0EvidenceTests(FixtureTestCase):
    """PR 15I-B P0: mandatory twelve rebuilds and safe raw directory inventory."""

    def test_p0_complete_real_size_fixture_passes(self):
        fixture = self.fixture("p0-complete", real_sizes=True)
        receipt = fixture.verify()
        self.assertEqual(
            receipt["three_build_reproducibility"],
            verify.EXPECTED_SIZE_REPRODUCIBILITY,
        )

    def test_ft_a55_missing_rebuild_run_fails(self):
        fixture = self.fixture(
            "p0-a55", real_sizes=True, delete_size_run=("A", "100000", 2)
        )
        self.assertRejected(fixture, "A_PROVENANCE_BLOCKED_SIZE_ARTIFACTS")

    def test_ft_a55_one_and_two_missing_rebuilds_fail(self):
        for missing in (("B", "10000", 1), ("A", "10000", 2), ("B", "100000", 3)):
            fixture = self.fixture(
                f"p0-a55-{missing[0]}-{missing[1]}-{missing[2]}",
                real_sizes=True,
                delete_size_run=missing,
            )
            self.assertRejected(fixture, "A_PROVENANCE_BLOCKED_SIZE_ARTIFACTS")

    def test_ft_a56_unexpected_directory_in_raw_fails(self):
        fixture = self.fixture("p0-a56-dir", real_sizes=True)
        os.makedirs(os.path.join(fixture.campaign, "raw", "unexpected"))
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a56_symlinked_directory_in_raw_fails(self):
        fixture = self.fixture("p0-a56-symlink", real_sizes=True)
        outside = os.path.join(fixture.root, "outside-dir")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(fixture.campaign, "raw", "unexpected"))
        self.assertRejected(fixture, "A_SEAL")

        fixture = self.fixture("p0-a56-inside", real_sizes=True)
        os.symlink(
            os.path.join(fixture.campaign, "raw", "slots"),
            os.path.join(fixture.campaign, "raw", "unexpected"),
        )
        self.assertRejected(fixture, "A_SEAL")

        fixture = self.fixture("p0-a56-dangling", real_sizes=True)
        os.symlink(
            os.path.join(fixture.root, "missing-target"),
            os.path.join(fixture.campaign, "raw", "unexpected"),
        )
        self.assertRejected(fixture, "A_SEAL")

    def test_ft_a57_injected_partial_size_mapping_fails(self):
        partial = {"A/10000": "INDEPENDENTLY_RE_VERIFIED"}
        fixture = self.fixture(
            "p0-a57", size_artifacts=lambda _campaign, _sizes: partial
        )
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a58_symlinked_rebuild_directory_fails(self):
        fixture = self.fixture("p0-a58", real_sizes=True)
        arm, n, attempt = "B", 100_000, 1
        path = os.path.join(fixture.campaign, "setup", "sizes", arm, f"n{n}-run{attempt}")
        shutil.rmtree(path)
        os.symlink(
            os.path.join(fixture.campaign, "setup", "sizes", arm, f"n{n}-run2"), path
        )
        self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a59_modified_rebuild_after_seal_fails(self):
        fixture = self.fixture(
            "p0-a59", real_sizes=True, modify_size_run=("B", 10_000, 2)
        )
        self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a60_source_and_receipt_are_stable(self):
        fixture = self.fixture("p0-a60", real_sizes=True)
        seal_path = os.path.join(fixture.campaign, "raw", "seal.json")
        before = verify._sha256_file(seal_path)
        first = fixture.verify()
        second = fixture.verify()
        self.assertEqual(first, second)
        self.assertEqual(before, verify._sha256_file(seal_path))


class SourceTests(FixtureTestCase):
    def test_ft_a09_candidate_source_not_measured(self):
        def mutate(documents):
            documents["manifest"]["sources"]["B"] = "e" * 40
            documents["measurements"]["sources"]["B"] = "e" * 40

        fixture = self.fixture("a09", mutate=mutate)
        self.assertRejected(fixture, "A_SOURCE")

    def test_ft_a10_baseline_source_not_accepted(self):
        def mutate(documents):
            documents["manifest"]["sources"]["A"] = "e" * 40
            documents["measurements"]["sources"]["A"] = "e" * 40

        fixture = self.fixture("a10", mutate=mutate)
        self.assertRejected(fixture, "A_SOURCE")

    def test_ft_a11_scope_diff_changed(self):
        def mutate(documents):
            documents["measurements"]["scope_diff"] = sorted(SCOPE + ["crates/quervant-core/src/index/writer.rs"])

        fixture = self.fixture("a11", mutate=mutate)
        self.assertRejected(fixture, "A_SOURCE")

    def test_ft_a24_warm_slot_source_hash(self):
        def mutate(documents):
            documents["slots"][0]["source_sha"] = "e" * 40

        fixture = self.fixture("a24", mutate=mutate)
        self.assertRejected(fixture, "A_SOURCE")


class ProvenanceTests(FixtureTestCase):
    def test_ft_a12_protocol_blob_mismatch(self):
        fixture = self.fixture("a12", git=FixtureGit(blob="e" * 40))
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a13_corpus_digest_changed_in_one_source(self):
        def mutate(documents):
            documents["measurements"]["corpus_manifest_sha256"] = "e" * 64

        fixture = self.fixture("a13", mutate=mutate)
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a14_corpus_content_changed(self):
        fixture = self.fixture(
            "a14", corpus_loader=lambda _campaign: ("e" * 64, {10_000: ROWS, 100_000: ROWS})
        )
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a15_idle_authorization_invalid(self):
        for tag, value in (("false", False), ("string", "true"), ("missing", None)):
            def mutate(documents, value=value):
                if value is None:
                    del documents["authorization"]["operator_idle_authorized_by_user"]
                else:
                    documents["authorization"]["operator_idle_authorized_by_user"] = value

            fixture = self.fixture(f"a15-{tag}", mutate=mutate)
            self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a16_filesystem_mismatch_or_nonnative(self):
        def mismatch(documents):
            documents["authorization"]["filesystem"] = "nfs"

        def nonnative(documents):
            documents["authorization"]["filesystem"] = "nfs"
            documents["manifest"]["filesystem"] = "nfs"

        for tag, mutation in (("mismatch", mismatch), ("nonnative", nonnative)):
            fixture = self.fixture(f"a16-{tag}", mutate=mutation)
            self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a17_environment_fingerprint_mismatch(self):
        def mutate(documents):
            documents["measurements"]["environment_fingerprint"] = "e" * 64

        fixture = self.fixture("a17", mutate=mutate)
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a18_binary_hash_swapped(self):
        def mutate(documents):
            digest = "e" * 64
            documents["manifest"]["binary_sha256"]["A"]["adapter"] = digest
            documents["measurements"]["binary_sha256"]["A"]["adapter"] = digest

        fixture = self.fixture("a18", mutate=mutate)
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a19_missing_original_binary(self):
        fixture = self.fixture("a19")
        os.unlink(
            os.path.join(
                fixture.campaign, "setup", "build", "A", "reopen", "build", "release",
                "pr15i-a-reopen-probe",
            )
        )
        self.assertRejected(fixture, "A_PROVENANCE_BLOCKED_MISSING_ORIGINAL_BINARY")

    def test_ft_a25_slot_adapter_digest(self):
        def mutate(documents):
            documents["slots"][0]["binary_sha256"] = "e" * 64

        fixture = self.fixture("a25", mutate=mutate)
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a26_trial_contention_not_clear(self):
        def mutate(documents):
            documents["slots"][2]["trial"]["contention_before"] = {
                "state": "contended", "reason_codes": ["cpu_busy"]
            }

        fixture = self.fixture("a26", mutate=mutate)
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a27_lane_contention_not_clear(self):
        def mutate(documents):
            documents["slots"][4]["trial"]["lanes"][0]["contention"] = {
                "state": "contended", "reason_codes": ["cpu_busy"]
            }

        fixture = self.fixture("a27", mutate=mutate)
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a42_provenance_field_omitted(self):
        def mutate(documents):
            del documents["authorization"]["filesystem"]

        fixture = self.fixture("a42", mutate=mutate)
        self.assertRejected(fixture, "A_PROVENANCE")

    def test_ft_a54_missing_setup_material_fails_closed(self):
        def loader(_campaign):
            raise verify.VerifyError(3, "A_PROVENANCE_BLOCKED_CORPUS", "missing")

        fixture = self.fixture("a54", corpus_loader=loader)
        self.assertRejected(fixture, "A_PROVENANCE_BLOCKED_CORPUS")


class MatrixTests(FixtureTestCase):
    def test_ft_a20_block_arm_order(self):
        def mutate(documents):
            documents["blocks"]["block_arm_order"] = [["A", "B"]]

        fixture = self.fixture("a20", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a21_reopen_block_duplicate(self):
        def mutate(documents):
            documents["blocks"]["A"]["reopen"][1] = copy.deepcopy(
                documents["blocks"]["A"]["reopen"][0]
            )

        fixture = self.fixture("a21", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a22_build_sample_invalid(self):
        def mutate(documents):
            documents["blocks"]["B"]["build_commit"][0]["samples"][0]["index_ns"] = -1

        fixture = self.fixture("a22", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a23_remote_sample_invalid(self):
        def mutate(documents):
            documents["blocks"]["B"]["remote"][0]["samples"][0]["open_ns"] = 0

        fixture = self.fixture("a23", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a28_lane_set_missing(self):
        def mutate(documents):
            documents["slots"][0]["trial"]["lanes"].pop()

        fixture = self.fixture("a28", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a29_sample_count_and_type(self):
        mutations = {
            "count": lambda lane: lane["samples_ns"].pop(),
            "boolean": lambda lane: lane["samples_ns"].__setitem__(0, True),
            "nonpositive": lambda lane: lane["samples_ns"].__setitem__(0, 0),
        }
        for tag, mutation in mutations.items():
            def mutate(documents, mutation=mutation):
                mutation(documents["slots"][1]["trial"]["lanes"][0])

            fixture = self.fixture(f"a29-{tag}", mutate=mutate)
            self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a30_warmup_ids(self):
        def mutate(documents):
            documents["slots"][2]["trial"]["lanes"][0]["warmup_ids"].pop()

        fixture = self.fixture("a30", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a31_lane_descriptor(self):
        def mutate(documents):
            documents["slots"][3]["trial"]["lanes"][0]["term"] = "wrong"

        fixture = self.fixture("a31", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a34_summary_tampered(self):
        def mutate(documents):
            documents["slots"][4]["trial"]["lanes"][0]["summary_ns"]["median"] += 1

        fixture = self.fixture("a34", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")

    def test_ft_a44_oracle_proof_missing(self):
        def mutate(documents):
            documents["slots"][5]["trial"]["lanes"][0]["samples_ns"] = []

        fixture = self.fixture("a44", mutate=mutate)
        self.assertRejected(fixture, "A_MATRIX")


class OracleTests(FixtureTestCase):
    def test_ft_a32_doc_ids_differ(self):
        def mutate(documents):
            documents["slots"][0]["trial"]["lanes"][2]["doc_ids"] = ["d999"]

        fixture = self.fixture("a32", mutate=mutate)
        self.assertRejected(fixture, "A_ORACLE")

    def test_ft_a33_total_hits_differ(self):
        def mutate(documents):
            documents["slots"][0]["trial"]["lanes"][2]["total_hits"] += 1

        fixture = self.fixture("a33", mutate=mutate)
        self.assertRejected(fixture, "A_ORACLE")


class FormatTests(FixtureTestCase):
    def test_ft_a35_a_payload_version(self):
        def mutate(documents):
            documents["manifest"]["sizes"]["A"]["100000"]["state_containers"][0]["payload_version"] = 3

        fixture = self.fixture("a35", mutate=mutate)
        self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a36_b_payload_version(self):
        def mutate(documents):
            documents["manifest"]["sizes"]["B"]["100000"]["state_containers"][0]["payload_version"] = 1

        fixture = self.fixture("a36", mutate=mutate)
        self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a37_b_feature_missing(self):
        def mutate(documents):
            documents["manifest"]["sizes"]["B"]["10000"]["state_containers"][0][
                "required_features"
            ] = [[1, 1], [8, 1]]

        fixture = self.fixture("a37", mutate=mutate)
        self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a38_duplicate_and_unknown_features(self):
        def duplicate(documents):
            documents["manifest"]["sizes"]["B"]["100000"]["state_containers"][0][
                "required_features"
            ].append([12, 1])

        def unknown(documents):
            documents["manifest"]["sizes"]["B"]["100000"]["state_containers"][0][
                "required_features"
            ].append([13, 1])

        for tag, mutation in (("duplicate", duplicate), ("unknown", unknown)):
            fixture = self.fixture(f"a38-{tag}", mutate=mutation)
            self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a39_sidecar_length_mismatch(self):
        def mutate(documents):
            documents["manifest"]["sizes"]["B"]["100000"]["sidecar_bytes"] += 1

        fixture = self.fixture("a39", mutate=mutate)
        self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a40_sidecar_sha_mismatch(self):
        def mutate(documents):
            documents["manifest"]["sizes"]["A"]["10000"]["state_containers"][0]["sha256"] = "e" * 64

        fixture = self.fixture("a40", mutate=mutate)
        self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a41_baseline_sentinel_changed(self):
        def mutate(documents):
            documents["manifest"]["sizes"]["A"]["100000"]["committed_index_bytes"] += 1

        fixture = self.fixture("a41", mutate=mutate)
        self.assertRejected(fixture, "A_FORMAT")

    def test_ft_a43_format_proof_missing(self):
        def mutate(documents):
            documents["manifest"]["sizes"]["A"]["100000"]["state_containers"] = []

        fixture = self.fixture("a43", mutate=mutate)
        self.assertRejected(fixture, "A_FORMAT")


class DerivedGateTests(FixtureTestCase):
    def test_ft_a45_reported_gate_changed(self):
        def mutate(documents):
            documents["measurements"]["gates"]["A-P01"] = "FAIL"

        fixture = self.fixture("a45", mutate=mutate)
        self.assertRejected(fixture, "A_INPUT_MISMATCH")

    def test_ft_a51_production_tree_differs(self):
        fixture = self.fixture("a51", git=FixtureGit(production=False))
        self.assertRejected(fixture, "A_SOURCE_BLOCKED")


class ReceiptTests(unittest.TestCase):
    def test_ft_a46_receipt_outside_reviews(self):
        receipt = {"schema": verify.RECEIPT_SCHEMA, "qualified": True}
        with self.assertRaises(verify.VerifyError) as context:
            verify.write_receipt(ROOT, receipt, "/tmp/forbidden-receipt.json")
        self.assertEqual(context.exception.code, "A_RECEIPT")

    def test_ft_a47_receipt_overwrite_and_symlink(self):
        directory = os.path.join(ROOT, "target", "pr15i-a", "reviews")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"unit-{os.getpid()}-receipt.json")
        if os.path.exists(path):
            os.unlink(path)
        try:
            verify.write_receipt(ROOT, {"schema": verify.RECEIPT_SCHEMA}, path)
            with self.assertRaises(verify.VerifyError):
                verify.write_receipt(ROOT, {"schema": verify.RECEIPT_SCHEMA}, path)
            link = os.path.join(directory, f"unit-{os.getpid()}-link.json")
            if os.path.lexists(link):
                os.unlink(link)
            os.symlink(path, link)
            with self.assertRaises(verify.VerifyError):
                verify.write_receipt(ROOT, {"schema": verify.RECEIPT_SCHEMA}, link)
            os.unlink(link)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class LegacyRouteTests(unittest.TestCase):
    def test_ft_a48_legacy_verify_only_fails_closed(self):
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(HERE, "run.py"),
                "--checkout-root",
                ROOT,
                "--campaign",
                REAL_CAMPAIGN,
                "--verify-only",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("A_USE_INDEPENDENT_VERIFIER", result.stderr)
        self.assertNotIn("VERIFIED", result.stdout + result.stderr)


@unittest.skipUnless(os.path.isdir(REAL_CAMPAIGN), "original campaign is not available")
class RealCampaignTests(unittest.TestCase):
    def test_ft_a49_real_campaign_verifies(self):
        receipt = verify.verify_campaign(ROOT, REAL_CAMPAIGN)
        self.assertTrue(receipt["qualified"])
        self.assertEqual(receipt["raw_files_verified"], 20)
        self.assertEqual(receipt["auxiliary_contention_files_verified"], 32)
        self.assertEqual(receipt["measured_sources"], verify.EXPECTED_SOURCES)
        self.assertEqual(receipt["oracle_records"], 144)
        self.assertEqual(receipt["sample_records"], 2880)
        self.assertEqual(receipt["hosted_ci"], "SEPARATE_EXTERNAL_STATUS")

    def test_ft_a50_real_campaign_is_read_only(self):
        seal_path = os.path.join(REAL_CAMPAIGN, "raw", "seal.json")
        before = verify._sha256_file(seal_path)
        verify.verify_campaign(ROOT, REAL_CAMPAIGN)
        self.assertEqual(before, verify._sha256_file(seal_path))
        self.assertEqual(
            before, "af7f6c1a85515dbc58c8c31a3b1b7f68dd6a9246d33747a529952b941b852b2f"
        )

    def test_ft_a51_real_production_tree_unchanged(self):
        result = subprocess.run(
            [
                "git", "-C", ROOT, "diff", "--exit-code",
                "db9007fb7239a5cce94e20c7c43ac7200da8047f", "HEAD", "--",
                "crates/quervant-core/src", "crates/quervant-core/Cargo.toml",
                "Cargo.lock", ".github/workflows/ci.yml",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ft_a52_published_sentinels_and_gates_unchanged(self):
        published = _read(os.path.join(ROOT, "benchmarks", "reports", "pr15i-a", "results.json"))
        self.assertEqual(published["sizes"]["A"]["100000"]["committed_index_bytes"], 30_965_025)
        self.assertEqual(published["sizes"]["A"]["100000"]["sidecar_bytes"], 9_600_180)
        self.assertEqual(published["sizes"]["B"]["100000"]["committed_index_bytes"], 23_748_601)
        self.assertEqual(published["sizes"]["B"]["100000"]["sidecar_bytes"], 2_383_748)
        self.assertTrue(all(value == "PASS" for value in published["gates"].values()))
        self.assertEqual(published["decision"], "A_CANDIDATE_ACCEPTED_PENDING_QA")

    def test_ft_a53_statuses_are_separate(self):
        receipt = verify.verify_campaign(ROOT, REAL_CAMPAIGN)
        self.assertEqual(receipt["local_qa"], "SEPARATE_REPORTED_STATUS")
        self.assertEqual(receipt["hosted_ci"], "SEPARATE_EXTERNAL_STATUS")
        self.assertEqual(
            receipt["host_observation"],
            "HISTORICAL_ATTESTATION_NOT_INDEPENDENTLY_REPRODUCED",
        )


class ArithmeticTests(unittest.TestCase):
    def _report(self, sidecar: int, total: int) -> dict:
        a = test_run.synthetic_arm()
        b = test_run.synthetic_arm(sidecar=sidecar, total=total, sha="b" * 40)
        report, _ = run.derive(a, b)
        return report

    def test_exact_boundary_passes(self):
        report = self._report(9_600_180 * 3 // 4, 30_965_025 * 19 // 20)
        verify._check_integer_size_gates(report)

    def test_one_byte_over_boundary_fails(self):
        report = self._report(9_600_180 * 3 // 4 + 1, 30_965_025 * 19 // 20)
        with self.assertRaises(verify.VerifyError):
            verify._check_integer_size_gates(report)


if __name__ == "__main__":
    unittest.main()

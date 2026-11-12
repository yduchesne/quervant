#!/usr/bin/env python3
"""Independent negative-matrix tests (T01..T56) for the PR 15I-D3-B-F1 verifier.

This module imports only ``verify.py`` (the subject under test). Fixtures are
constructed here from the frozen F1 protocol values and independent arithmetic;
no controller helper is imported and no real campaign is used as a fixture.

Run::

    python3 -m unittest discover -s benchmarks/pr15i_d3_b_f1_2 -p 'test_*.py' -v
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BLOCKS = 4
SAMPLES = 20
BASE_SHA = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
CANDIDATE_SHA = "48d9abf3eeefbccb480d89eac95f6e6911e078d5"
V1_PROTOCOL_SHA256 = "8c113091507528450f9dd8f406fc3ac0a390c164b9a7a603583f48d752c6d1be"
LANE_IDS = [
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/medium/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
]
HITS = {
    "pr15d_v1/10000/absent/k100": 0,
    "pr15d_v1/10000/rare/k100": 1,
    "pr15d_v1/10000/medium/k100": 1250,
    "pr15d_v1/10000/common/k100": 4999,
    "pr15d_v1/100000/absent/k100": 0,
    "pr15d_v1/100000/rare/k100": 1,
    "pr15d_v1/100000/medium/k100": 12500,
    "pr15d_v1/100000/common/k100": 49999,
    "pr15d_v1/100000/common/k10": 49999,
}
ARM_ORDER = [("A", "B", "B", "A"), ("B", "A", "A", "B"), ("B", "A", "A", "B"), ("A", "B", "B", "A")]
FS_ROLES = [
    "repository",
    "campaign_output",
    "compile_source",
    "target_A",
    "target_B",
    "corpus",
    "indexes",
]
PROTOCOL_SHA = "4" * 64


def _load(name: str, filename: str):
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_2", filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load("pr15i_d3_b_f1_verify_matrix", "verify.py")
PROTOCOL = VERIFY.PROTOCOL


def descriptor(lane_id: str) -> dict:
    parts = lane_id.split("/")
    n = int(parts[1])
    class_name = parts[2]
    k = int(parts[3][1:])
    return {
        "id": lane_id,
        "n": n,
        "class": class_name,
        "field": "group" if class_name == "medium" else "key",
        "term": {"absent": "never", "rare": "singleton", "medium": "medium", "common": "common"}[class_name],
        "k": k,
    }


LANES = [descriptor(lane_id) for lane_id in LANE_IDS]
DIGESTS = {"10000": "c" * 64, "100000": "d" * 64}


def lane_record(lane: dict, median: int, controller: int = 1, adapter: int = 0) -> dict:
    hits = HITS[lane["id"]]
    samples = [median] * SAMPLES
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "regime": "warm",
        "warmups": 5,
        "warmup_ids": [f"warmup-{index}" for index in range(5)],
        "samples_ns": samples,
        "summary_ns": {"count": SAMPLES, "median": sorted(samples)[9]},
        "total_hits": hits,
        "doc_ids": [],
        "expected_total_hits": hits,
        "expected_doc_ids": [],
        "oracle_ok": True,
        "adapter_pid": 4242,
        "adapter_affinity_before": [adapter],
        "adapter_affinity_after": [adapter],
        "affinity_capture_stages": ["pre_warmup", "post_timed_sample_20"],
    }


def constant_arm(ns: int) -> dict:
    return {block: {lane["id"]: ns for lane in LANES} for block in range(1, BLOCKS + 1)}


def slots(per_arm: dict, controller: int = 1, adapter: int = 0) -> list[dict]:
    plan = []
    for block, order in enumerate(ARM_ORDER, start=1):
        for position, arm in enumerate(order, start=1):
            plan.append({"slot": (block - 1) * 4 + position, "block": block, "position": position, "arm": arm})
    result = []
    for entry in plan:
        values = per_arm[entry["arm"]][entry["block"]]
        result.append(
            {
                "schema": VERIFY.SCHEMA_SLOT,
                "slot": entry["slot"],
                "block": entry["block"],
                "position": entry["position"],
                "arm": entry["arm"],
                "source_sha": BASE_SHA if entry["arm"] == "A" else CANDIDATE_SHA,
                "binary_sha256": ("b" if entry["arm"] == "A" else "e") * 64,
                "index_digests": dict(DIGESTS),
                "contention_before": {"state": "clear", "reason_codes": []},
                "contention_after": {"state": "clear", "reason_codes": []},
                "controller_affinity_before": [controller],
                "controller_affinity_after": [controller],
                "lanes": [lane_record(lane, values[lane["id"]], controller, adapter) for lane in LANES],
            }
        )
    return result


def metrics(overrides: dict | None = None, ratios: dict | None = None) -> dict:
    diffs = {lane["id"]: [0, 0, 0, 0] for lane in LANES}
    for lane_id, values in (overrides or {}).items():
        diffs[lane_id] = list(values)
    result = {}
    for lane in LANES:
        values = diffs[lane["id"]]
        a_values = [10_000_000] * 4
        b_values = [a - value for a, value in zip(a_values, values)]
        block_ratios = [b / a for a, b in zip(a_values, b_values)]
        if ratios and lane["id"] in ratios:
            block_ratios = list(ratios[lane["id"]])
            b_values = [int(10_000_000 * value) for value in block_ratios]
        result[lane["id"]] = {
            "id": lane["id"],
            "class": lane["class"],
            "n": lane["n"],
            "a_block_medians_ns": a_values,
            "b_block_medians_ns": b_values,
            "diffs_ns": values,
            "median_diff_ns": sorted(values)[1],
            "median_diff_ms": sorted(values)[1] / 1_000_000,
            "b_over_a_block": block_ratios,
            "b_over_a_median": sorted(block_ratios)[1],
        }
    return result


def gates(overrides: dict | None = None, ratios: dict | None = None) -> dict:
    return VERIFY.compute_gates("d3bf12-base", metrics(overrides, ratios))


def structural(**overrides) -> dict:
    value = {
        "build_provenance": "PASS",
        "host_attestation": "PASS",
        "affinity_observations": "PASS",
    }
    value.update(overrides)
    return value


def build_pair(kind: str = "paired") -> tuple[dict, dict]:
    """Return a consistent manifest + build-provenance pair."""
    control = kind == "control"
    campaign = "d3bf12-base-aa-01" if control else "d3bf12-base-01"
    candidate_sha = BASE_SHA if control else CANDIDATE_SHA
    canonical = f"/campaigns/{campaign}/compile-source"
    binary_a = "a" * 64
    binary_b = binary_a if control else "b" * 64
    bytes_a = 4_478_176
    bytes_b = bytes_a if control else bytes_a + 480
    events = []
    for arm, sha, binary, size in (
        ("A", BASE_SHA, binary_a, bytes_a),
        ("B", candidate_sha, binary_b, bytes_b),
    ):
        target = f"/campaigns/{campaign}/build/{arm}"
        events.append(
            {
                "build_id": f"{arm}-100-2026-11-12T00:00:0{1 if arm == 'A' else 9}Z",
                "arm": arm,
                "expected_source_sha": sha,
                "pre_checkout_sha": sha,
                "post_checkout_sha": sha,
                "pre_source_sha256": "f" * 64,
                "post_source_sha256": "f" * 64,
                "source_tree_clean": True,
                "command_argv": [
                    "cargo",
                    "build",
                    "--release",
                    "--locked",
                    "--manifest-path",
                    f"{canonical}/benchmarks/pr15d/adapters/quervant/Cargo.toml",
                    "--target-dir",
                    target,
                ],
                "cwd": f"{canonical}/benchmarks/pr15d/adapters/quervant",
                "manifest_path": f"{canonical}/benchmarks/pr15d/adapters/quervant/Cargo.toml",
                "target_dir": target,
                "canonical_source": canonical,
                "binary_path": f"{target}/release/pr15d-quervant-adapter",
                "binary_sha256": binary,
                "binary_bytes": size,
                "exit_status": 0,
                "started_utc": f"2026-11-12T00:00:0{1 if arm == 'A' else 9}Z",
                "ended_utc": f"2026-11-12T00:00:0{1 if arm == 'A' else 9}Z",
                "duration_seconds": 1.0,
                "toolchain": {"rustc": "rustc 1.98.1", "cargo": "cargo 1.98.1"},
                "build_environment": {"PATH": "/usr/bin"},
                "environment_fingerprint": "e" * 64,
                "codegen_flags": {"forbidden_present": [], "profile": "release", "locked": True},
                "canonical_build_mode": PROTOCOL["canonical_build"]["mode"],
                "protocol_sha256": PROTOCOL_SHA,
            }
        )
    provenance = {
        "schema": VERIFY.SCHEMA_BUILD_PROVENANCE,
        "protocol_sha256": PROTOCOL_SHA,
        "campaign": campaign,
        "kind": kind,
        "canonical_build_mode": PROTOCOL["canonical_build"]["mode"],
        "canonical_source_path": canonical,
        "canonical_subdir": "compile-source",
        "target_subdirs": ["build/A", "build/B"],
        "expected_source_sha": {"A": BASE_SHA, "B": candidate_sha},
        "source_transition": None
        if control
        else {
            "from_sha": BASE_SHA,
            "to_sha": CANDIDATE_SHA,
            "from_unified_sha256": "f" * 64,
            "to_unified_sha256": "g" * 64,
            "argv": ["git", "-C", canonical, "switch", "--detach", CANDIDATE_SHA],
            "recorded_utc": "2026-11-12T00:00:05Z",
        },
        "events": events,
        "target_dirs": {
            "A": f"/campaigns/{campaign}/build/A",
            "B": f"/campaigns/{campaign}/build/B",
        },
        "binary_sha256": {"A": binary_a, "B": binary_b},
        "binary_bytes": {"A": bytes_a, "B": bytes_b},
        "aa_identical": control,
        "ab_distinct": not control,
        "pre_timing_snapshot": {
            "A": {"binary_sha256": binary_a, "binary_bytes": bytes_a},
            "B": {"binary_sha256": binary_b, "binary_bytes": bytes_b},
        },
        "post_timing_snapshot": {
            "A": {"binary_sha256": binary_a, "binary_bytes": bytes_a},
            "B": {"binary_sha256": binary_b, "binary_bytes": bytes_b},
        },
        "recorded_utc": "2026-11-12T00:00:20Z",
    }
    manifest = {
        "schema": VERIFY.SCHEMA_MANIFEST,
        "campaign": campaign,
        "kind": kind,
        "comparison": "d3bf12-base",
        "tooling_sha": "1" * 40,
        "tooling_manifest_sha256": "7" * 64,
        "controller_sha256": "2" * 64,
        "verifier_sha256": "3" * 64,
        "protocol_sha256": PROTOCOL_SHA,
        "base_source_sha": BASE_SHA,
        "candidate_source_sha": candidate_sha,
        "source_fingerprints": {
            "A": {"crates/quervant-core/src/search/unified.rs": "e" * 64},
            "B": {"crates/quervant-core/src/search/unified.rs": "e" * 64},
        },
        "environment_fingerprint": None,
        "build_provenance_sha256": "8" * 64,
        "host_attestation_sha256": "9" * 64,
        "corpus": {"manifest_sha256": VERIFY.CORPUS_MANIFEST_SHA256},
        "expected_by_lane": {},
        "arms": {
            arm: {
                "source_sha": event["expected_source_sha"],
                "binary_sha256": event["binary_sha256"],
                "binary_bytes": event["binary_bytes"],
                "index_digests": dict(DIGESTS),
            }
            for arm, event in zip(("A", "B"), events, strict=True)
        },
        "builds": {"adapters": ["A", "B"], "indices": []},
        "control": None,
    }
    host = host_record()
    manifest["environment_fingerprint"] = host["host_fingerprint"]
    return manifest, provenance


def host_record(*, controller: int = 1, adapter: int = 0) -> dict:
    record = {
        "schema": VERIFY.SCHEMA_HOST_ATTESTATION,
        "protocol_sha256": PROTOCOL_SHA,
        "kernel": "test-kernel",
        "machine": "x86_64",
        "cpu_model": "test-cpu",
        "cpu_count": 12,
        "allowed_cpus_before_pin": list(range(12)),
        "controller_cpu": controller,
        "adapter_cpu": adapter,
        "controller_affinity_after_pin": [controller],
        "filesystems": [
            {"role": role, "path": f"/x/{role}", "harness_fstype": "ext4", "findmnt_fstype": "ext4"}
            for role in FS_ROLES
        ],
        "native_filesystem": True,
        "toolchains": {"rustc": "rustc 1.98.1", "cargo": "cargo 1.98.1", "python3": "Python 3.12"},
        "recorded_utc": "2026-11-12T00:00:00Z",
    }
    record["host_fingerprint"] = VERIFY.host_fingerprint(record)
    return record


def write_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)


class F1MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr15i-d3bf12-verify-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # T01
    def test_t01_campaign_names(self):
        for name in ("d3bf12-base-aa-01", "d3bf12-base-aa-02", "d3bf12-base-01", "d3bf12-base-02", "d3bf12-base-03"):
            comparison, kind = VERIFY.campaign_kind(name, PROTOCOL)
            self.assertEqual(comparison, "d3bf12-base")
        for name in ("d3b-base-aa-01", "d3b-base-01", "d3bf11-base-01", "d3bf12-base-04", "d3bf12-base-aa-03"):
            with self.assertRaises(VERIFY.VerifyError):
                VERIFY.campaign_kind(name, PROTOCOL)

    # T02
    def test_t02_protocol_literal_matches_file(self):
        path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_2", "protocol_v1.json")
        with open(path, "rb") as handle:
            on_disk = json.loads(handle.read().decode("utf-8"))
        self.assertEqual(on_disk, VERIFY.PROTOCOL)
        changed = copy.deepcopy(on_disk)
        changed["gates"]["D3B-P01"]["median_min_ns"] += 1
        self.assertNotEqual(changed, VERIFY.PROTOCOL)

    # T03 / T54
    def test_t03_tooling_manifest_inventory_and_freeze(self):
        directory = os.path.join(self.tmp, "tooling")
        os.makedirs(directory)
        for name in ("run.py", "verify.py"):
            with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
                handle.write(name)
        members = {
            name: VERIFY.sha256_file(os.path.join(directory, name))
            for name in ("run.py", "verify.py")
        }
        write_json(
            os.path.join(directory, "tooling_manifest.json"),
            {"schema": VERIFY.SCHEMA_TOOLING, "files": members},
        )
        original = VERIFY.tooling_dir
        VERIFY.tooling_dir = lambda: directory
        try:
            self.assertEqual(len(VERIFY.verify_tooling_manifest()["files"]), 2)
            with open(os.path.join(directory, "extra.py"), "w", encoding="utf-8") as handle:
                handle.write("x")
            with self.assertRaises(VERIFY.VerifyError):
                VERIFY.verify_tooling_manifest()
            os.remove(os.path.join(directory, "extra.py"))
            with open(os.path.join(directory, "run.py"), "a", encoding="utf-8") as handle:
                handle.write("# changed after freeze")
            with self.assertRaises(VERIFY.VerifyError):
                VERIFY.verify_tooling_manifest()
        finally:
            VERIFY.tooling_dir = original

    # T04
    def test_t04_base_dual_build_records(self):
        manifest, provenance = build_pair("control")
        self.assertEqual(VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA), [])
        self.assertTrue(provenance["aa_identical"])
        self.assertEqual(len({event["build_id"] for event in provenance["events"]}), 2)

    def test_t04_reject_copied_binary(self):
        manifest, provenance = build_pair("control")
        provenance["events"][1]["target_dir"] = provenance["events"][0]["target_dir"]
        provenance["events"][1]["build_id"] = provenance["events"][0]["build_id"]
        failures = VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA)
        self.assertTrue(failures)

    # T05
    def test_t05_ab_sequential_checkout(self):
        manifest, provenance = build_pair("paired")
        self.assertEqual(VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA), [])
        self.assertEqual(provenance["events"][1]["pre_checkout_sha"], CANDIDATE_SHA)
        self.assertEqual(
            provenance["source_transition"]["argv"],
            ["git", "-C", provenance["canonical_source_path"], "switch", "--detach", CANDIDATE_SHA],
        )

    # T06
    def test_t06_different_source_paths_rejected(self):
        manifest, provenance = build_pair("paired")
        provenance["events"][1]["canonical_source"] = "/elsewhere/compile-source"
        self.assertTrue(VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA))

    # T07
    def test_t07_aa_identical_qualifies(self):
        manifest, provenance = build_pair("control")
        self.assertEqual(VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA), [])

    def test_t07_aa_binary_mismatch_blocks(self):
        manifest, provenance = build_pair("control")
        provenance["events"][1]["binary_sha256"] = "c" * 64
        provenance["events"][1]["binary_bytes"] += 1
        failures = VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA)
        self.assertTrue(any(failure["code"] == "V_BINARY" for failure in failures))
        self.assertTrue(any(failure["code"] == "V_AA_BINARY" for failure in failures))

    # T08
    def test_t08_ab_identical_binary_rejected(self):
        manifest, provenance = build_pair("paired")
        provenance["events"][1]["binary_sha256"] = provenance["events"][0]["binary_sha256"]
        manifest["arms"]["B"]["binary_sha256"] = manifest["arms"]["A"]["binary_sha256"]
        failures = VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA)
        self.assertTrue(any(failure["code"] == "V_AB_BINARY" for failure in failures))

    # T09
    def test_t09_identical_target_dir_rejected(self):
        manifest, provenance = build_pair("paired")
        provenance["events"][1]["target_dir"] = provenance["events"][0]["target_dir"]
        self.assertTrue(VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA))

    # T10
    def test_t10_overlapping_builds_rejected(self):
        manifest, provenance = build_pair("paired")
        provenance["events"][1]["started_utc"] = "2026-11-12T00:00:00Z"
        provenance["events"][0]["ended_utc"] = "2026-11-12T00:00:09Z"
        failures = VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA)
        self.assertTrue(any("before the first finished" in f["detail"] for f in failures))

    # T11 / T12
    def test_t11_source_tree_not_clean_rejected(self):
        manifest, provenance = build_pair("paired")
        provenance["events"][1]["source_tree_clean"] = False
        self.assertTrue(VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA))

    def test_t12_source_changed_mid_build(self):
        manifest, provenance = build_pair("paired")
        provenance["events"][0]["post_source_sha256"] = "0" * 64
        failures = VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA)
        self.assertTrue(any("source changed" in f["detail"] for f in failures))

    # T13
    def test_t13_wrong_source_revision_rejected(self):
        manifest, provenance = build_pair("paired")
        provenance["events"][1]["expected_source_sha"] = BASE_SHA
        provenance["events"][1]["pre_checkout_sha"] = BASE_SHA
        provenance["events"][1]["post_checkout_sha"] = BASE_SHA
        self.assertTrue(VERIFY.build_provenance_failures(provenance, manifest, PROTOCOL_SHA))

    # T14 / T15 / V01
    def test_v01_frozen_inputs_match_git(self):
        result = VERIFY.verify_frozen_inputs_for_revision(BASE_SHA)
        self.assertEqual(result["revision"], BASE_SHA)
        self.assertIn("benchmarks/pr15d/adapters/quervant/Cargo.lock", result["files"])
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_frozen_inputs_for_revision("0" * 40)

    def test_t14_changed_corpus_blob(self):
        real = VERIFY._default_blob_reader

        def reader(sha, relative):
            payload = real(sha, relative)
            if relative == "benchmarks/pr15d/corpus/oracle.py":
                return payload + b"# tampered"
            return payload

        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_frozen_inputs_for_revision(BASE_SHA, blob_reader=reader)

    def test_t15_changed_adapter_lock_blob(self):
        real = VERIFY._default_blob_reader

        def reader(sha, relative):
            payload = real(sha, relative)
            if relative.endswith("Cargo.lock"):
                return b"tampered"
            return payload

        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_frozen_inputs_for_revision(BASE_SHA, blob_reader=reader)

    # T16 / T55
    def test_t16_old_manifest_detected(self):
        path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b", "protocol_v1.json")
        self.assertEqual(VERIFY.sha256_file(path), V1_PROTOCOL_SHA256)

    def test_t55_historical_v1_unaffected(self):
        result = subprocess.run(
            ["git", "-C", TOOLING_ROOT, "diff", "--exit-code", "155ebafafa29fb0e6b6cbf953f89445f4880fd2f", "--", "benchmarks/pr15i_d3_b"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    # T17 / T18 / T19 / V04
    def _record_fixture(self) -> tuple[str, dict]:
        manifest, provenance = build_pair("paired")
        host = host_record()
        manifest["environment_fingerprint"] = host["host_fingerprint"]
        root = os.path.join(self.tmp, "campaign")
        write_json(os.path.join(root, "authorization.json"), {
            "schema": VERIFY.SCHEMA_AUTHORIZATION,
            "campaign": manifest["campaign"],
            "kind": manifest["kind"],
            "comparison": manifest["comparison"],
            "base_source_sha": manifest["base_source_sha"],
            "candidate_source_sha": manifest["candidate_source_sha"],
            "protocol_sha256": PROTOCOL_SHA,
            "idle_confirmed": True,
        })
        write_json(os.path.join(root, "manifest.json"), manifest)
        write_json(os.path.join(root, "raw", "build-provenance.json"), provenance)
        write_json(os.path.join(root, "raw", "host-attestation.json"), host)
        return root, manifest

    def test_v04_protocol_in_all_records(self):
        root, manifest = self._record_fixture()
        VERIFY.verify_protocol_records(root, manifest, PROTOCOL_SHA)

    def test_t17_wrong_protocol_digest_authorization(self):
        root, manifest = self._record_fixture()
        record = json.load(open(os.path.join(root, "authorization.json"), encoding="utf-8"))
        record["protocol_sha256"] = "0" * 64
        write_json(os.path.join(root, "authorization.json"), record)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_protocol_records(root, manifest, PROTOCOL_SHA)

    def test_t18_wrong_build_protocol_digest(self):
        root, manifest = self._record_fixture()
        record = json.load(open(os.path.join(root, "raw", "build-provenance.json"), encoding="utf-8"))
        record["protocol_sha256"] = "0" * 64
        write_json(os.path.join(root, "raw", "build-provenance.json"), record)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_protocol_records(root, manifest, PROTOCOL_SHA)

    def test_t19_wrong_host_protocol_digest(self):
        root, manifest = self._record_fixture()
        record = json.load(open(os.path.join(root, "raw", "host-attestation.json"), encoding="utf-8"))
        record["protocol_sha256"] = "0" * 64
        write_json(os.path.join(root, "raw", "host-attestation.json"), record)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_protocol_records(root, manifest, PROTOCOL_SHA)

    # T20
    def test_t20_missing_member_rejected(self):
        root, manifest = self._record_fixture()
        seal = {
            "schema": VERIFY.SCHEMA_SEAL,
            "kind": "paired",
            "files": {"authorization.json": VERIFY.sha256_file(os.path.join(root, "authorization.json"))},
        }
        write_json(os.path.join(root, "raw", "seal.json"), seal)
        VERIFY.verify_seal(root)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_inventory(root, seal)

    # T21
    def test_t21_duplicate_json_key_rejected(self):
        path = os.path.join(self.tmp, "duplicate.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"schema":"a","schema":"b"}')
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.read_json(path)

    # T22 / T52
    def test_t22_symlink_traversal_rejected(self):
        root = os.path.join(self.tmp, "traversal")
        os.makedirs(os.path.join(root, "raw"))
        with open(os.path.join(root, "raw", "member.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        digest = VERIFY.sha256_file(os.path.join(root, "raw", "member.json"))
        write_json(
            os.path.join(root, "raw", "seal.json"),
            {"schema": VERIFY.SCHEMA_SEAL, "kind": "paired", "files": {"../escape.json": digest}},
        )
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_seal(root)
        link = os.path.join(root, "raw", "link.json")
        os.symlink(os.path.join(root, "raw", "member.json"), link)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.read_json(link)

    # T23 / T27 / T30 / T28 / T29
    def test_t23_controller_equals_adapter_rejected(self):
        manifest, _ = build_pair("control")
        failures = VERIFY.host_attestation_failures(host_record(controller=1, adapter=1), manifest, PROTOCOL_SHA)
        self.assertTrue(any(failure["code"] == "V_AFFINITY" for failure in failures))

    def test_t27_controller_observed_cpu_differs(self):
        manifest, _ = build_pair("control")
        record = host_record(controller=1, adapter=0)
        record["controller_affinity_after_pin"] = [2]
        failures = VERIFY.host_attestation_failures(record, manifest, PROTOCOL_SHA)
        self.assertTrue(any(failure["code"] == "V_AFFINITY" for failure in failures))

    def test_t28_findmnt_overlay_rejected(self):
        manifest, _ = build_pair("control")
        record = host_record()
        record["filesystems"][1]["findmnt_fstype"] = "overlay"
        failures = VERIFY.host_attestation_failures(record, manifest, PROTOCOL_SHA)
        self.assertTrue(any(failure["code"] == "V_HOST" for failure in failures))

    def test_t29_non_native_rejected(self):
        manifest, _ = build_pair("control")
        record = host_record()
        for item in record["filesystems"]:
            item["harness_fstype"] = "tmpfs"
            item["findmnt_fstype"] = "tmpfs"
        failures = VERIFY.host_attestation_failures(record, manifest, PROTOCOL_SHA)
        self.assertTrue(any(failure["code"] == "V_HOST" for failure in failures))

    def test_t30_host_fingerprint_mismatch(self):
        manifest, _ = build_pair("control")
        record = host_record()
        record["host_fingerprint"] = "0" * 64
        failures = VERIFY.host_attestation_failures(record, manifest, PROTOCOL_SHA)
        self.assertTrue(any("fingerprint" in failure["detail"] for failure in failures))

    def test_host_attestation_accepts_native(self):
        manifest, _ = build_pair("control")
        self.assertEqual(VERIFY.host_attestation_failures(host_record(), manifest, PROTOCOL_SHA), [])

    # T24 / T25 / T26
    def test_v03_affinity_observations_accept(self):
        slot_records = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        self.assertEqual(VERIFY.affinity_failures(slot_records, 1, 0), [])

    def test_t24_missing_pre_capture(self):
        slot_records = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        slot_records[0]["lanes"][0]["adapter_affinity_before"] = None
        self.assertTrue(VERIFY.affinity_failures(slot_records, 1, 0))

    def test_t25_missing_post_capture(self):
        slot_records = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        del slot_records[0]["lanes"][0]["adapter_affinity_after"]
        self.assertTrue(VERIFY.affinity_failures(slot_records, 1, 0))

    def test_t26_post_capture_moved(self):
        slot_records = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        slot_records[3]["lanes"][4]["adapter_affinity_after"] = [7]
        self.assertTrue(VERIFY.affinity_failures(slot_records, 1, 0))

    # T31 / T32 / T33 / T34
    def test_t31_exempt_single_outlier(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][1]["pr15d_v1/10000/absent/k100"] = int(10_000_000 * 1.30)
        self.assertTrue(VERIFY.compute_control(slots(per_arm), LANES)["passes"])

    def test_t32_two_exempt_outliers(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        for block in (1, 2):
            per_arm["B"][block]["pr15d_v1/10000/rare/k100"] = int(10_000_000 * 1.30)
        self.assertFalse(VERIFY.compute_control(slots(per_arm), LANES)["passes"])

    def test_t33_non_exempt_outlier(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][1]["pr15d_v1/10000/common/k100"] = int(10_000_000 * 1.30)
        self.assertFalse(VERIFY.compute_control(slots(per_arm), LANES)["passes"])
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][1]["pr15d_v1/10000/rare/k100"] = int(10_000_000 * 1.60)
        self.assertFalse(VERIFY.compute_control(slots(per_arm), LANES)["passes"])

    def test_t34_median_bounds(self):
        for ratio, expected in ((1.15, True), (1.1501, False), (0.85, True), (0.8499, False)):
            per_arm = {
                "A": constant_arm(10_000_000),
                "B": {block: {lane["id"]: int(10_000_000 * ratio) for lane in LANES} for block in range(1, 5)},
            }
            self.assertEqual(VERIFY.compute_control(slots(per_arm), LANES)["passes"], expected, ratio)

    # T35 / T36 / T37 / T38
    def test_t35_p01_boundaries(self):
        lane = "pr15d_v1/100000/common/k100"
        self.assertEqual(gates({lane: [2_000_000, 2_000_000, 2_000_000, -1]})["D3B-P01"], "PASS")
        self.assertEqual(gates({lane: [1_999_999] * 4})["D3B-P01"], "FAIL")
        self.assertEqual(gates({lane: [2_000_000, 2_000_000, -1, -1]})["D3B-P01"], "FAIL")

    def test_t36_k10_boundaries(self):
        lane = "pr15d_v1/100000/common/k10"
        self.assertEqual(
            gates({lane: [-500_000, -500_000, -500_000, -1_500_000]}, {lane: [1.05] * 4})["D3B-P03"],
            "PASS",
        )
        self.assertEqual(gates({lane: [-500_001] * 4}, {lane: [1.05] * 4})["D3B-P03"], "FAIL")
        self.assertEqual(
            gates({lane: [-100_000] * 4}, {lane: [1.0500001] * 4})["D3B-P03"], "FAIL"
        )

    def test_t37_low_hit_boundaries(self):
        lane = "pr15d_v1/10000/absent/k100"
        self.assertEqual(gates({}, {lane: [1.15] * 4})["D3B-P04"], "PASS")
        self.assertEqual(gates({}, {lane: [1.150001] * 4})["D3B-P04"], "FAIL")
        self.assertEqual(gates({}, {lane: [1.15, 1.15, 1.15, 1.500001]})["D3B-P04"], "FAIL")

    def test_t38_p05_p06_guards(self):
        self.assertEqual(
            gates({"pr15d_v1/10000/common/k100": [-2_000_000] * 4})["D3B-P05"], "FAIL"
        )
        self.assertEqual(
            gates({"pr15d_v1/10000/common/k100": [-1_999_999, -1_999_999, -1_999_999, -3_000_000]})["D3B-P05"],
            "PASS",
        )
        self.assertEqual(
            gates({"pr15d_v1/100000/common/k100": [3_000_000, 3_000_000, 3_000_000, -1_500_001]})["D3B-P06"],
            "FAIL",
        )

    # T39 / T40 / T48
    def _slot_dir(self, slot_records: list[dict]) -> str:
        root = os.path.join(self.tmp, "slots")
        os.makedirs(os.path.join(root, "raw", "slots"), exist_ok=True)
        for slot in slot_records:
            write_json(os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), slot)
        return root

    def _expected(self) -> dict:
        return {lane["id"]: {"total_hits": HITS[lane["id"]], "doc_ids": []} for lane in LANES}

    def test_t39_shape_rejections(self):
        manifest, _ = build_pair("paired")
        base = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._slot_dir(base[:-1]), manifest, self._expected())
        reordered = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        reordered[0]["lanes"] = list(reversed(reordered[0]["lanes"]))
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._slot_dir(reordered), manifest, self._expected())
        bad_samples = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        bad_samples[0]["lanes"][0]["samples_ns"][0] = 0
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._slot_dir(bad_samples), manifest, self._expected())

    def test_t40_oracle_tamper(self):
        manifest, _ = build_pair("paired")
        tampered = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        tampered[5]["lanes"][3]["total_hits"] += 1
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._slot_dir(tampered), manifest, self._expected())
        tampered = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        tampered[5]["lanes"][3]["doc_ids"] = ["forged"]
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._slot_dir(tampered), manifest, self._expected())

    def test_t48_partial_campaign_not_qualified(self):
        manifest, _ = build_pair("paired")
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(
                self._slot_dir(slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})[:8]),
                manifest,
                self._expected(),
            )

    # T41
    def test_t41_drift_and_contention(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][2] = {lane["id"]: 12_500_001 for lane in LANES}
        violations = VERIFY.drift_violations(slots(per_arm), LANES, BLOCKS)
        self.assertTrue(any(item["gate"] == "BLOCK_DRIFT" for item in violations))
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)}
        busy = slots(per_arm)
        busy[0]["contention_before"] = {"state": "busy", "reason_codes": ["cpu_load"]}
        manifest, _ = build_pair("paired")
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._slot_dir(busy), manifest, self._expected())

    # T42 / T43 / T44
    def test_t42_structural_then_02_rejected(self):
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {
                "aa-01": "MEASUREMENT_BLOCKED",
                "aa-02": "CONTROL_QUALIFIED",
            })

    def test_t43_numerical_then_qualified_02(self):
        self.assertEqual(
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {
                "aa-01": "CONTROL_NUMERICAL_BLOCKED",
                "aa-02": "CONTROL_QUALIFIED",
            }),
            "d3bf12-base-aa-02",
        )
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {
                "aa-01": "CONTROL_NUMERICAL_BLOCKED",
                "aa-02": "CONTROL_NUMERICAL_BLOCKED",
            })

    def test_t44_qualified_01_and_02_rejected(self):
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {
                "aa-01": "CONTROL_QUALIFIED",
                "aa-02": "CONTROL_QUALIFIED",
            })
        self.assertEqual(
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {"aa-01": "CONTROL_QUALIFIED"}),
            "d3bf12-base-aa-01",
        )
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {})

    # T45 / T46 / T47
    def _series(self, statuses: dict) -> str:
        root = os.path.join(self.tmp, "series")
        os.makedirs(root, exist_ok=True)
        for name in ("d3bf12-base-aa-01", "d3bf12-base-01", "d3bf12-base-02"):
            directory = os.path.join(root, name)
            if name in statuses:
                os.makedirs(directory, exist_ok=True)
                write_json(os.path.join(directory, "manifest.json"), {
                    "control": {"campaign": "d3bf12-base-aa-01"},
                })
        return root

    def test_t45_series_history(self):
        root = self._series({"d3bf12-base-aa-01": "CONTROL_QUALIFIED", "d3bf12-base-01": "CAMPAIGN_REJECTED"})
        original = VERIFY.verify_campaign_dir

        def fake(path):
            name = os.path.basename(os.path.normpath(path))
            status = "CAMPAIGN_REJECTED" if name.endswith("-01") else "CAMPAIGN_QUALIFIED"
            return {"campaign": name, "campaign_status": status, "gates": {"D3B-P01": "FAIL"}}

        VERIFY.verify_campaign_dir = fake
        original_protocol = VERIFY.load_protocol
        VERIFY.load_protocol = lambda: (PROTOCOL, PROTOCOL_SHA)
        try:
            with self.assertRaises(VERIFY.VerifyError):
                VERIFY.aggregate_series(root, "d3bf12-base")
        finally:
            VERIFY.verify_campaign_dir = original
            VERIFY.load_protocol = original_protocol

    def test_t46_series_both_qualified(self):
        self.assertEqual(
            VERIFY.succession_next(["QUALIFIED_PASSED", "QUALIFIED_PASSED"])["terminal"],
            "ACCEPTED",
        )
        self.assertEqual(
            VERIFY.succession_next([])["next"],
            "01",
        )

    def test_t47_series_second_fails(self):
        self.assertEqual(
            VERIFY.succession_next(["QUALIFIED_PASSED", "QUALIFIED_REJECTED"])["terminal"],
            "REJECTED",
        )
        self.assertEqual(
            VERIFY.succession_next(["QUALIFIED_PASSED", "QUALIFIED_PASSED"])["terminal"],
            "ACCEPTED",
        )

    # T49 / T50
    def _provenance_fixture(self, kind: str = "paired", live: bool = False):
        manifest, provenance = build_pair(kind)
        mutating = copy.deepcopy(manifest)
        mutating["environment_fingerprint"] = host_record()["host_fingerprint"]
        root = os.path.join(self.tmp, f"build-{kind}-{live}")
        os.makedirs(root, exist_ok=True)
        write_json(os.path.join(root, "raw", "build-provenance.json"), provenance)
        mutating["build_provenance_sha256"] = VERIFY.sha256_file(
            os.path.join(root, "raw", "build-provenance.json")
        )
        for arm, event in zip(("A", "B"), provenance["events"], strict=True):
            write_json(
                os.path.join(root, "raw", "setup", f"adapter-{arm}.json"),
                {
                    "arm": arm,
                    "binary_sha256": event["binary_sha256"],
                    "binary_bytes": event["binary_bytes"],
                },
            )
            if live:
                target = os.path.join(root, "build", arm, "release")
                os.makedirs(target, exist_ok=True)
                with open(os.path.join(target, "pr15d-quervant-adapter"), "wb") as handle:
                    handle.write(b"adapter:" + event["binary_sha256"].encode())
                real = VERIFY.sha256_file(os.path.join(target, "pr15d-quervant-adapter"))
                event["binary_sha256"] = real
                mutating["arms"][arm]["binary_sha256"] = real
        if live:
            write_json(os.path.join(root, "raw", "build-provenance.json"), provenance)
            mutating["build_provenance_sha256"] = VERIFY.sha256_file(
                os.path.join(root, "raw", "build-provenance.json")
            )
        return root, mutating, provenance

    def test_t49_archive_only_provenance(self):
        root, manifest, _ = self._provenance_fixture("paired", live=False)
        result = VERIFY.verify_build_provenance(root, manifest, PROTOCOL_SHA)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["live_binary_rehash"], "UNAVAILABLE_ARCHIVE")

    def test_t50_live_binary_tamper(self):
        root, manifest, _ = self._provenance_fixture("paired", live=True)
        binary = os.path.join(root, "build", "A", "release", "pr15d-quervant-adapter")
        with open(binary, "ab") as handle:
            handle.write(b"tampered")
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_build_provenance(root, manifest, PROTOCOL_SHA)

    # T51
    def test_t51_exclusive_archive(self):
        path = os.path.join(self.tmp, "archive.tar.gz")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(descriptor)
        with self.assertRaises(FileExistsError):
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(descriptor)

    # T53
    def test_t53_controller_verifier_disagreement(self):
        manifest, _ = build_pair("paired")
        slot_records = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        first = VERIFY.recompute_summary(manifest, slot_records, LANES, PROTOCOL_SHA, structural())
        slot_records[0]["lanes"][0]["samples_ns"] = [1] * SAMPLES
        slot_records[0]["lanes"][0]["summary_ns"]["median"] = 1
        second = VERIFY.recompute_summary(manifest, slot_records, LANES, PROTOCOL_SHA, structural())
        self.assertNotEqual(
            VERIFY.canonical_json_bytes(first["lanes"]),
            VERIFY.canonical_json_bytes(second["lanes"]),
        )

    # T56
    def test_t56_inverted_expectation_fails(self):
        failing = gates({"pr15d_v1/100000/common/k100": [1_000_000] * 4})
        self.assertNotEqual(failing["D3B-P01"], "PASS")
        with self.assertRaises(AssertionError):
            self.assertEqual(failing["D3B-P01"], "PASS")

    # V05
    def test_v05_summary_recompute_and_control_reference(self):
        manifest, _ = build_pair("paired")
        manifest["control"] = {
            "campaign": "d3bf12-base-aa-01",
            "base_source_sha": BASE_SHA,
            "status": "CONTROL_QUALIFIED",
            "predecessor_status": "NONE",
            "seal_sha256": "a" * 64,
            "summary_sha256": "b" * 64,
            "build_provenance_sha256": "c" * 64,
            "host_attestation_sha256": "d" * 64,
        }
        VERIFY.verify_control_reference(manifest, PROTOCOL_SHA)
        broken = copy.deepcopy(manifest)
        broken["control"]["status"] = "CONTROL_NUMERICAL_BLOCKED"
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_control_reference(broken, PROTOCOL_SHA)
        broken = copy.deepcopy(manifest)
        broken["control"]["campaign"] = "d3bf12-base-aa-02"
        broken["control"]["predecessor_status"] = "NONE"
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_control_reference(broken, PROTOCOL_SHA)


if __name__ == "__main__":
    unittest.main()

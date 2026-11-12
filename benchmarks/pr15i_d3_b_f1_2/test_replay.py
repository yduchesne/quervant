#!/usr/bin/env python3
"""F1.1 fixup, invariant and rehearsal-harness unit tests (T01–T48).

These tests exercise the two prescribed repairs, the unchanged protocol/gates,
the rehearsal-only publication guard and the synthetic harness helpers. The
full external verifier rehearsal itself is executed by ``replay.py``.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLING_DIR = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_2")
F1_DIR = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_1")
BASE_SHA = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
CANDIDATE_SHA = "48d9abf3eeefbccb480d89eac95f6e6911e078d5"
FS_ROLES = [
    "repository",
    "campaign_output",
    "compile_source",
    "target_A",
    "target_B",
    "corpus",
    "indexes",
]


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPLAY = _load("f11_replay_tests", os.path.join(TOOLING_DIR, "replay.py"))
RUN = REPLAY.RUN
VERIFY = REPLAY.VERIFY
PROTOCOL = RUN.PROTOCOL
F1_PROTOCOL = json.load(open(os.path.join(F1_DIR, "protocol_v1.json"), encoding="utf-8"))


def attestation(*, allowed=None, controller=1, adapter=0) -> dict:
    record = {
        "schema": VERIFY.SCHEMA_HOST_ATTESTATION,
        "protocol_sha256": "4" * 64,
        "kernel": "test-kernel",
        "machine": "x86_64",
        "cpu_model": "test-cpu",
        "cpu_count": 12,
        "allowed_cpus_before_pin": list(allowed if allowed is not None else [0, 1, 4, 5]),
        "controller_cpu": controller,
        "adapter_cpu": adapter,
        "controller_affinity_after_pin": [controller],
        "filesystems": [
            {"role": role, "path": f"/x/{role}", "harness_fstype": "ext4", "findmnt_fstype": "ext4"}
            for role in FS_ROLES
        ],
        "native_filesystem": True,
        "toolchains": {"rustc": "r", "cargo": "c", "python3": "p"},
        "recorded_utc": "2026-11-12T00:00:00Z",
    }
    record["host_fingerprint"] = RUN.host_fingerprint(record)
    return record


def _manifest_for_host(record: dict) -> dict:
    return {
        "environment_fingerprint": record.get("host_fingerprint"),
        "host_attestation_sha256": "9" * 64,
    }


class FingerprintTests(unittest.TestCase):
    # T01
    def test_f11_t01_controller_verifier_digest_parity(self):
        record = attestation(allowed=[0, 1, 4, 5])
        digest = RUN.host_fingerprint(record)
        self.assertEqual(digest, VERIFY.host_fingerprint(record))
        self.assertEqual(len(digest), 64)
        self.assertNotEqual(record["host_fingerprint"], "0" * 64)

    # T02
    def test_f11_t02_allowed_list_changes_digest(self):
        first = RUN.host_fingerprint(attestation(allowed=[0, 1, 4, 5]))
        second = RUN.host_fingerprint(attestation(allowed=[0, 1, 4, 6]))
        self.assertNotEqual(first, second)
        self.assertEqual(second, VERIFY.host_fingerprint(attestation(allowed=[0, 1, 4, 6])))

    # T03
    def test_f11_t03_preflight_only_shape_rejected_for_campaign(self):
        record = attestation()
        record["allowed_cpus"] = record.pop("allowed_cpus_before_pin")
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        failures = VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64)
        self.assertTrue(any(failure["code"] == "V_HOST" for failure in failures))

    # T04
    def test_f11_t04_attestation_key_accepted(self):
        record = attestation()
        self.assertEqual(RUN.host_fingerprint(record), VERIFY.host_fingerprint(record))
        self.assertEqual(VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64), [])

    # T05
    def test_f11_t05_missing_allowed_list_rejected(self):
        record = attestation()
        del record["allowed_cpus_before_pin"]
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        failures = VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64)
        self.assertTrue(any(failure["code"] == "V_HOST" for failure in failures))

    # T06
    def test_f11_t06_duplicate_cpu_rejected(self):
        record = attestation()
        record["allowed_cpus_before_pin"] = [0, 1, 1, 4, 5]
        record["host_fingerprint"] = "0" * 64
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        self.assertTrue(
            any(f["code"] == "V_HOST" for f in VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64))
        )

    # T07
    def test_f11_t07_boolean_cpu_rejected(self):
        record = attestation()
        record["allowed_cpus_before_pin"] = [0, 1, 4, True]
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        self.assertTrue(
            any(f["code"] == "V_HOST" for f in VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64))
        )

    # T08
    def test_f11_t08_negative_cpu_rejected(self):
        record = attestation()
        record["allowed_cpus_before_pin"] = [-1, 0, 1, 4, 5]
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        self.assertTrue(
            any(f["code"] == "V_HOST" for f in VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64))
        )

    # T09
    def test_f11_t09_equal_pinned_cpus_rejected(self):
        record = attestation()
        record["adapter_cpu"] = 1
        record["controller_affinity_after_pin"] = [1]
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        failures = VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64)
        self.assertTrue(any(f["code"] == "V_AFFINITY" for f in failures))

    # T10
    def test_f11_t10_pinned_cpu_outside_allowed_rejected(self):
        record = attestation()
        record["controller_cpu"] = 9
        record["controller_affinity_after_pin"] = [9]
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        failures = VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64)
        self.assertTrue(any(f["code"] == "V_AFFINITY" for f in failures))

    # T11
    def test_f11_t11_unsorted_allowed_list_rejected(self):
        record = attestation()
        record["allowed_cpus_before_pin"] = [5, 4, 1, 0]
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        self.assertTrue(
            any(f["code"] == "V_HOST" for f in VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64))
        )

    # T12
    def test_f11_t12_missing_role_rejected(self):
        record = attestation()
        record["filesystems"] = record["filesystems"][:-1]
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        self.assertTrue(
            any(f["code"] == "V_HOST" for f in VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64))
        )

    # T13
    def test_f11_t13_duplicate_role_rejected(self):
        record = attestation()
        record["filesystems"][-1] = dict(record["filesystems"][-2])
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        self.assertTrue(
            any(f["code"] == "V_HOST" for f in VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64))
        )

    # T14
    def test_f11_t14_extra_role_rejected(self):
        record = attestation()
        record["filesystems"].append(
            {"role": "extra", "path": "/x/extra", "harness_fstype": "ext4", "findmnt_fstype": "ext4"}
        )
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        self.assertTrue(
            any(f["code"] == "V_HOST" for f in VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64))
        )

    # T15
    def test_f11_t15_non_native_filesystem_rejected(self):
        record = attestation()
        for item in record["filesystems"]:
            item["harness_fstype"] = "tmpfs"
            item["findmnt_fstype"] = "tmpfs"
        failures = VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64)
        self.assertTrue(any(f["code"] == "V_HOST" for f in failures))

    # T16
    def test_f11_t16_harness_findmnt_disagreement_rejected(self):
        record = attestation()
        record["filesystems"][2]["findmnt_fstype"] = "overlay"
        failures = VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64)
        self.assertTrue(any(f["code"] == "V_HOST" for f in failures))

    # T17
    def test_f11_t17_invalid_host_fields_typed_error(self):
        record = attestation()
        record["kernel"] = ""
        record["cpu_count"] = True
        with self.assertRaises(RUN.D3BBlocked):
            RUN.host_fingerprint(record)
        failures = VERIFY.host_attestation_failures(record, _manifest_for_host(record), "4" * 64)
        self.assertTrue(any(f["code"] == "V_HOST" for f in failures))

    # T18
    def test_f11_t18_preflight_cpu_list_changes_fingerprint(self):
        first = {"allowed_cpus": [0, 1], "kernel": "k", "machine": "x", "cpu_model": "c", "cpu_count": 2}
        second = dict(first)
        second["allowed_cpus"] = [0, 1, 2, 3]
        self.assertNotEqual(RUN.preflight_host_fingerprint(first), RUN.preflight_host_fingerprint(second))

    # T19
    def test_f11_t19_preflight_and_campaign_scopes_distinct(self):
        environment = {
            "allowed_cpus": [0, 1, 4, 5],
            "kernel": "k",
            "machine": "x",
            "cpu_model": "c",
            "cpu_count": 6,
        }
        campaign = attestation(allowed=[0, 1, 4, 5])
        self.assertNotEqual(
            RUN.preflight_host_fingerprint(environment),
            RUN.host_fingerprint(campaign),
        )

    # T20
    def test_f11_t20_explicit_valid_attestation_parity(self):
        record = attestation(allowed=[0, 2, 4, 6], controller=2, adapter=0)
        digest = RUN.host_fingerprint(record)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, VERIFY.host_fingerprint(record))


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f11-inventory-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _campaign(self, *, checkout: bool = True) -> tuple[str, dict]:
        root = os.path.join(self.tmp, "campaign")
        os.makedirs(os.path.join(root, "raw"), exist_ok=True)
        with open(os.path.join(root, "authorization.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        if checkout:
            os.makedirs(os.path.join(root, "compile-source"))
            with open(os.path.join(root, "compile-source", ".git"), "w", encoding="utf-8") as handle:
                handle.write("synthetic\n")
        seal = {
            "schema": VERIFY.SCHEMA_SEAL,
            "kind": "control",
            "files": {"authorization.json": VERIFY.sha256_file(os.path.join(root, "authorization.json"))},
        }
        with open(os.path.join(root, "raw", "seal.json"), "w", encoding="utf-8") as handle:
            json.dump(seal, handle)
        return root, seal

    # T21
    def test_f11_t21_root_compile_source_excluded(self):
        root, seal = self._campaign()
        self.assertEqual(VERIFY.verify_inventory(root, seal), {"member_count": 1})

    # T22
    def test_f11_t22_archive_without_compile_source(self):
        root, seal = self._campaign(checkout=False)
        self.assertEqual(VERIFY.verify_inventory(root, seal), {"member_count": 1})

    # T23
    def test_f11_t23_compile_source_file_rejected(self):
        root, seal = self._campaign(checkout=False)
        with open(os.path.join(root, "compile-source"), "w", encoding="utf-8") as handle:
            handle.write("not a directory")
        with self.assertRaises(VERIFY.VerifyError) as caught:
            VERIFY.verify_inventory(root, seal)
        self.assertEqual(caught.exception.code, "V_INVENTORY")

    # T24
    def test_f11_t24_compile_source_symlink_rejected(self):
        root, seal = self._campaign(checkout=False)
        target = os.path.join(self.tmp, "target")
        os.makedirs(target)
        os.symlink(target, os.path.join(root, "compile-source"))
        with self.assertRaises(VERIFY.VerifyError) as caught:
            VERIFY.verify_inventory(root, seal)
        self.assertEqual(caught.exception.code, "V_SYMLINK")

    # T25
    def test_f11_t25_sealed_compile_source_rejected(self):
        root, seal = self._campaign()
        with open(os.path.join(root, "compile-source", "secret"), "w", encoding="utf-8") as handle:
            handle.write("secret")
        seal["files"]["compile-source/secret"] = VERIFY.sha256_file(os.path.join(root, "compile-source", "secret"))
        with self.assertRaises(VERIFY.VerifyError) as caught:
            VERIFY.verify_inventory(root, seal)
        self.assertEqual(caught.exception.code, "V_SEAL")

    # T26
    def test_f11_t26_root_intruder_rejected(self):
        root, seal = self._campaign()
        with open(os.path.join(root, "intruder.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        with self.assertRaises(VERIFY.VerifyError) as caught:
            VERIFY.verify_inventory(root, seal)
        self.assertEqual(caught.exception.code, "V_INVENTORY")

    # T27
    def test_f11_t27_nested_compile_source_not_exempt(self):
        root, seal = self._campaign()
        os.makedirs(os.path.join(root, "other", "compile-source"))
        with open(os.path.join(root, "other", "compile-source", "x"), "w", encoding="utf-8") as handle:
            handle.write("x")
        with self.assertRaises(VERIFY.VerifyError) as caught:
            VERIFY.verify_inventory(root, seal)
        self.assertEqual(caught.exception.code, "V_INVENTORY")

    # T28
    def test_f11_t28_historical_excluded_dirs_unchanged(self):
        root, seal = self._campaign()
        for name in ("build", "indexes", "corpus"):
            os.makedirs(os.path.join(root, name))
            with open(os.path.join(root, name, "artifact"), "w", encoding="utf-8") as handle:
                handle.write(name)
        self.assertEqual(VERIFY.verify_inventory(root, seal), {"member_count": 1})

    # T29
    def test_f11_t29_tampered_sealed_file_still_rejected(self):
        root, seal = self._campaign()
        with open(os.path.join(root, "authorization.json"), "w", encoding="utf-8") as handle:
            handle.write('{"tampered":true}')
        with self.assertRaises(VERIFY.VerifyError) as caught:
            VERIFY.verify_seal(root)
        self.assertEqual(caught.exception.code, "V_SEAL")

    # T30
    def test_f11_t30_duplicate_json_key_rejected(self):
        path = os.path.join(self.tmp, "duplicate.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"schema":"a","schema":"b"}')
        with self.assertRaises(VERIFY.VerifyError) as caught:
            VERIFY.read_json(path)
        self.assertEqual(caught.exception.code, "V_JSON")


class ProtocolInvariantTests(unittest.TestCase):
    # T31
    def test_f11_t31_protocol_exactly_nine_changes(self):
        expected = {
            "schema",
            "study_type",
            "comparisons",
            "tooling_directory",
            "target_subroot",
            "evidence_root_relative",
            "campaign_suffixes",
            "host_readiness",
            "paired_structural_replacement",
        }
        changed = set()
        for key in set(F1_PROTOCOL) | set(PROTOCOL):
            if F1_PROTOCOL.get(key) != PROTOCOL.get(key):
                changed.add(key)
        self.assertEqual(changed, expected)
        self.assertEqual(set(PROTOCOL["comparisons"]), {"d3bf12-base"})
        self.assertEqual(PROTOCOL["comparisons"]["d3bf12-base"], F1_PROTOCOL["comparisons"]["d3bf11-base"])

    # T32
    def test_f11_t32_aa_configuration_unchanged(self):
        self.assertEqual(PROTOCOL["a_a"], F1_PROTOCOL["a_a"])

    # T33
    def test_f11_t33_gates_unchanged(self):
        self.assertEqual(PROTOCOL["gates"], F1_PROTOCOL["gates"])
        self.assertEqual(PROTOCOL["comparisons"]["d3bf12-base"]["gates"], F1_PROTOCOL["comparisons"]["d3bf11-base"]["gates"])

    # T34
    def test_f11_t34_lanes_and_schedule_unchanged(self):
        self.assertEqual(PROTOCOL["lane_ids"], F1_PROTOCOL["lane_ids"])
        self.assertEqual(PROTOCOL["arm_order_by_block"], F1_PROTOCOL["arm_order_by_block"])
        self.assertEqual(PROTOCOL["samples_per_lane_slot"], 20)
        self.assertEqual(PROTOCOL["warmups_per_lane_slot"], 5)
        self.assertEqual(PROTOCOL["contention_probes_per_slot"], 2)
        self.assertEqual(PROTOCOL["slots_per_campaign"], 16)

    # T35
    def test_f11_t35_corpus_and_sentinels_unchanged(self):
        for key in (
            "corpus_manifest_sha256",
            "expected_total_hits",
            "100k_lz4_committed_index_sentinel",
            "100k_lz4_stored_section_sentinel",
            "drift",
            "canonical_build",
            "source_policy",
        ):
            self.assertEqual(PROTOCOL[key], F1_PROTOCOL[key], key)

    # T36
    def test_f11_t36_campaign_names(self):
        for name in ("d3bf12-base-aa-01", "d3bf12-base-aa-02", "d3bf12-base-01", "d3bf12-base-02", "d3bf12-base-03"):
            self.assertEqual(VERIFY.campaign_kind(name, PROTOCOL), ("d3bf12-base", "control" if "aa" in name else "paired"))
        for name in ("d3bf1-base-aa-01", "d3bf11-base-01", "d3bf12-base-04", "d3bf12-base-aa-03"):
            with self.assertRaises(VERIFY.VerifyError):
                VERIFY.campaign_kind(name, PROTOCOL)

    # T37
    def test_f11_t37_tooling_manifest_exact_inventory(self):
        directory = tempfile.mkdtemp(prefix="f11-tooling-")
        try:
            for name in ("run.py", "verify.py"):
                with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
                    handle.write(name)
            files = {name: VERIFY.sha256_file(os.path.join(directory, name)) for name in ("run.py", "verify.py")}
            with open(os.path.join(directory, "tooling_manifest.json"), "w", encoding="utf-8") as handle:
                json.dump({"schema": VERIFY.SCHEMA_TOOLING, "files": files}, handle)
            original = VERIFY.tooling_dir
            VERIFY.tooling_dir = lambda: directory
            try:
                self.assertEqual(len(VERIFY.verify_tooling_manifest()["files"]), 2)
                with open(os.path.join(directory, "extra.py"), "w", encoding="utf-8") as handle:
                    handle.write("extra")
                with self.assertRaises(VERIFY.VerifyError):
                    VERIFY.verify_tooling_manifest()
                os.remove(os.path.join(directory, "extra.py"))
                with open(os.path.join(directory, "run.py"), "a", encoding="utf-8") as handle:
                    handle.write("# changed")
                with self.assertRaises(VERIFY.VerifyError):
                    VERIFY.verify_tooling_manifest()
            finally:
                VERIFY.tooling_dir = original
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    # T38
    def test_f11_t38_source_policy_and_candidate(self):
        self.assertTrue(RUN.path_allowed("crates/quervant-core/src/search/unified.rs"))
        self.assertTrue(RUN.path_allowed("crates/quervant-core/tests/pr15i_d3_b.rs"))
        self.assertTrue(RUN.path_allowed("docs/pr-artifacts/pr-15i-d3-b/preflight.md"))
        self.assertTrue(RUN.path_allowed("benchmarks/pr15i_d3_b_f1_2/run.py"))
        self.assertFalse(RUN.path_allowed("crates/quervant-core/src/search/execute.rs"))
        self.assertEqual(
            RUN.rejected_design_symbols("struct RetainedKeyFingerprintIndex;", PROTOCOL),
            ["RetainedKeyFingerprintIndex"],
        )
        RUN.assert_d3b_source_proof(TOOLING_ROOT, CANDIDATE_SHA, PROTOCOL)

    # T39
    def test_f11_t39_controller_verifier_aa_parity(self):
        per_arm = {
            "A": {block: {lane["id"]: 10_000_000 for lane in VERIFY.lane_descriptors(PROTOCOL)} for block in range(1, 5)},
            "B": {block: {lane["id"]: 10_000_000 for lane in VERIFY.lane_descriptors(PROTOCOL)} for block in range(1, 5)},
        }
        plan = []
        for block, order in enumerate(PROTOCOL["arm_order_by_block"], start=1):
            for position, arm in enumerate(order, start=1):
                plan.append({"slot": (block - 1) * 4 + position, "block": block, "position": position, "arm": arm})
        slots = []
        for entry in plan:
            values = per_arm[entry["arm"]][entry["block"]]
            slots.append(
                {
                    "schema": VERIFY.SCHEMA_SLOT,
                    "slot": entry["slot"],
                    "block": entry["block"],
                    "position": entry["position"],
                    "arm": entry["arm"],
                    "source_sha": BASE_SHA,
                    "binary_sha256": "a" * 64,
                    "index_digests": {"10000": "c" * 64, "100000": "d" * 64},
                    "contention_before": {"state": "clear", "reason_codes": []},
                    "contention_after": {"state": "clear", "reason_codes": []},
                    "controller_affinity_before": [1],
                    "controller_affinity_after": [1],
                    "lanes": [
                        {
                            "id": lane["id"],
                            "n": lane["n"],
                            "class": lane["class"],
                            "field": lane["field"],
                            "term": lane["term"],
                            "k": lane["k"],
                            "regime": "warm",
                            "warmups": 5,
                            "warmup_ids": ["w"] * 5,
                            "samples_ns": [values[lane["id"]]] * 20,
                            "summary_ns": {"count": 20, "median": values[lane["id"]]},
                            "total_hits": HITS[lane["id"]],
                            "doc_ids": [],
                            "expected_total_hits": HITS[lane["id"]],
                            "expected_doc_ids": [],
                            "oracle_ok": True,
                            "adapter_pid": 1,
                            "adapter_affinity_before": [0],
                            "adapter_affinity_after": [0],
                            "affinity_capture_stages": ["pre_warmup", "post_timed_sample_20"],
                        }
                        for lane in VERIFY.lane_descriptors(PROTOCOL)
                    ],
                }
            )
        lanes = VERIFY.lane_descriptors(PROTOCOL)
        controller = RUN.control_qualification(slots, lanes, PROTOCOL)
        verifier = VERIFY.compute_control(slots, lanes)
        self.assertEqual(controller["passes"], verifier["passes"])
        self.assertEqual(controller["passes"], True)

    # T40
    def test_f11_t40_controller_verifier_gate_parity(self):
        lanes = VERIFY.lane_descriptors(PROTOCOL)
        diffs = {lane["id"]: [0, 0, 0, 0] for lane in lanes}
        diffs["pr15d_v1/100000/common/k100"] = [2_000_000, 2_000_000, 2_000_000, -1]
        metrics = {}
        for lane in lanes:
            values = diffs[lane["id"]]
            a_values = [10_000_000] * 4
            b_values = [a - value for a, value in zip(a_values, values)]
            metrics[lane["id"]] = {
                "id": lane["id"],
                "class": lane["class"],
                "n": lane["n"],
                "a_block_medians_ns": a_values,
                "b_block_medians_ns": b_values,
                "diffs_ns": values,
                "median_diff_ns": sorted(values)[1],
                "median_diff_ms": sorted(values)[1] / 1_000_000,
                "b_over_a_block": [b / a for a, b in zip(a_values, b_values)],
                "b_over_a_median": sorted([b / a for a, b in zip(a_values, b_values)])[1],
            }
        self.assertEqual(RUN.paired_gate_table("d3bf12-base", metrics, PROTOCOL), VERIFY.compute_gates("d3bf12-base", metrics))
        self.assertEqual(VERIFY.compute_gates("d3bf12-base", metrics)["D3B-P01"], "PASS")

    # T41
    def test_f11_t41_control_numerical_retry(self):
        self.assertEqual(
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {"aa-01": "CONTROL_NUMERICAL_BLOCKED", "aa-02": "CONTROL_QUALIFIED"}),
            "d3bf12-base-aa-02",
        )
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {"aa-01": "CONTROL_NUMERICAL_BLOCKED", "aa-02": "CONTROL_NUMERICAL_BLOCKED"})

    # T42
    def test_f11_t42_structural_control_blocks_retry(self):
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {"aa-01": "MEASUREMENT_BLOCKED", "aa-02": "CONTROL_QUALIFIED"})
        self.assertEqual(
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {"aa-01": "CONTROL_QUALIFIED"}),
            "d3bf12-base-aa-01",
        )
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.eligible_control_name(PROTOCOL, "d3bf12-base", {"aa-01": "CONTROL_QUALIFIED", "aa-02": "CONTROL_QUALIFIED"})

    # T43
    def test_f11_t43_first_paired_rejection_stops_series(self):
        self.assertEqual(
            VERIFY.aggregate_statuses(["CAMPAIGN_REJECTED"]),
            "COMPARISON_PERFORMANCE_REJECTED",
        )
        # A rejected first campaign must not be rescued by a second one.
        self.assertEqual(
            VERIFY.aggregate_statuses(["CAMPAIGN_REJECTED", "CAMPAIGN_QUALIFIED"]),
            "COMPARISON_PERFORMANCE_REJECTED",
        )

    # T44
    def test_f11_t44_incomplete_series_not_accepted(self):
        self.assertEqual(VERIFY.aggregate_statuses(["CAMPAIGN_QUALIFIED"]), "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY")
        self.assertEqual(VERIFY.aggregate_statuses(["CAMPAIGN_QUALIFIED", "MEASUREMENT_BLOCKED"]), "MEASUREMENT_BLOCKED")
        self.assertEqual(VERIFY.aggregate_statuses(["CAMPAIGN_REJECTED"]), "COMPARISON_PERFORMANCE_REJECTED")

    # T45
    def test_f11_t45_rehearsal_marker_publish_guard(self):
        root = RUN.target_root()
        os.makedirs(root, exist_ok=True)
        marker = tempfile.mkdtemp(prefix="f11-marker-", dir=root)
        path_marked = tempfile.mkdtemp(prefix="f11-path-", dir=os.path.join(root, "rehearsal")) if os.path.isdir(os.path.join(root, "rehearsal")) else None
        if path_marked is None:
            os.makedirs(os.path.join(root, "rehearsal"), exist_ok=True)
            path_marked = tempfile.mkdtemp(prefix="f11-path-", dir=os.path.join(root, "rehearsal"))
        try:
            for directory in (marker, path_marked):
                with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as handle:
                    json.dump({"campaign": "f11-fixture"}, handle)
                with open(os.path.join(directory, "authorization.json"), "w", encoding="utf-8") as handle:
                    json.dump({"rehearsal_only": True} if directory == marker else {}, handle)
            self.assertTrue(RUN.is_rehearsal_campaign(marker))
            self.assertTrue(RUN.is_rehearsal_campaign(path_marked))
            with open(os.path.join(path_marked, "authorization.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            self.assertTrue(RUN.is_rehearsal_campaign(path_marked))
            original = RUN.load_protocol
            RUN.load_protocol = lambda: (RUN.PROTOCOL, "0" * 64)
            try:
                evidence = tempfile.mkdtemp(prefix="f11-evidence-")
                for directory in (marker, path_marked):
                    with self.assertRaises(RUN.D3BInvalid) as caught:
                        RUN.cmd_publish(
                            type("Args", (), {"campaign_dir": directory, "evidence_root": evidence})()
                        )
                    self.assertIn("D3B_REHEARSAL_PUBLISH_FORBIDDEN", str(caught.exception))
                    self.assertEqual(os.listdir(evidence), [])
            finally:
                RUN.load_protocol = original
        finally:
            shutil.rmtree(marker, ignore_errors=True)
            shutil.rmtree(path_marked, ignore_errors=True)

    # T46
    def test_f11_t46_rehearsal_path_publish_guard(self):
        root = RUN.target_root()
        os.makedirs(root, exist_ok=True)
        os.makedirs(os.path.join(root, "rehearsal"), exist_ok=True)
        directory = tempfile.mkdtemp(prefix="f11-path-only-", dir=os.path.join(root, "rehearsal"))
        try:
            with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump({"campaign": "f11-fixture"}, handle)
            with open(os.path.join(directory, "authorization.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            self.assertTrue(RUN.is_rehearsal_campaign(directory))
            original = RUN.load_protocol
            RUN.load_protocol = lambda: (RUN.PROTOCOL, "0" * 64)
            try:
                evidence = tempfile.mkdtemp(prefix="f11-evidence-")
                with self.assertRaises(RUN.D3BInvalid) as caught:
                    RUN.cmd_publish(type("Args", (), {"campaign_dir": directory, "evidence_root": evidence})())
                self.assertIn("D3B_REHEARSAL_PUBLISH_FORBIDDEN", str(caught.exception))
                self.assertEqual(os.listdir(evidence), [])
            finally:
                RUN.load_protocol = original
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    # T47
    def test_f11_t47_original_inventory_detects_change(self):
        root = tempfile.mkdtemp(prefix="f11-inv-audit-")
        try:
            os.makedirs(os.path.join(root, "raw"))
            with open(os.path.join(root, "raw", "seal.json"), "w", encoding="utf-8") as handle:
                handle.write("{}")
            with open(os.path.join(root, "member"), "w", encoding="utf-8") as handle:
                handle.write("one")
            seal = {"files": {"member": VERIFY.sha256_file(os.path.join(root, "member"))}}
            first = REPLAY.original_inventory(root, seal)
            self.assertTrue(REPLAY.original_inventory(root, seal) == first)
            with open(os.path.join(root, "member"), "a", encoding="utf-8") as handle:
                handle.write("two")
            self.assertNotEqual(REPLAY.original_inventory(root, seal), first)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # T48
    def test_f11_t48_harness_fails_closed_on_wrong_expectation(self):
        self_test = REPLAY.harness_self_test()
        self.assertFalse(self_test["matched_expectation"])
        self.assertTrue(self_test["harness_fail_closed"])
        good = {
            "status": "SYNTHETIC_REHEARSAL_ONLY",
            "original_files_unchanged": True,
            "publish_guard": "PASS",
            "archive_published": False,
            "performance_claim": "NONE",
            "negative_cases": [{"case": "x", "matched": True} for _ in range(6)],
        }
        self.assertEqual(REPLAY.report_exit_code(good), 0)
        broken = copy.deepcopy(good)
        broken["negative_cases"][0]["matched"] = False
        self.assertNotEqual(REPLAY.report_exit_code(broken), 0)

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


if __name__ == "__main__":
    unittest.main()

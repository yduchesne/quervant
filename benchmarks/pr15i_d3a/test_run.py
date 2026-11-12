#!/usr/bin/env python3
"""Targeted controller/protocol/archive tests for PR 15I-D3-A."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name):
    path = os.path.join(ROOT, "benchmarks", "pr15i_d3a", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"d3a_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("run")
verify = _load("verify")


class ProtocolTests(unittest.TestCase):
    """VT-01 and the frozen protocol contract."""

    def test_frozen_protocol_matches_both_literals(self):
        path = os.path.join(ROOT, "benchmarks", "pr15i_d3a", "protocol_v3.json")
        with open(path, encoding="utf-8") as handle:
            protocol = json.load(handle)
        self.assertEqual(protocol, run.EXPECTED_PROTOCOL)
        self.assertEqual(protocol, verify.EXPECTED_PROTOCOL)
        self.assertEqual(protocol["base_sha"], verify.BASE_SHA)

    def test_protocol_has_the_exact_stage_and_counter_schema(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(len(protocol["stages"]), 25)
        self.assertEqual(len(protocol["counters"]), 15)
        self.assertEqual(protocol["measurement_family"], "D3AF2_FIVE_PAIRED_LANE_SCOPED")
        self.assertEqual(protocol["control_campaign"], "d3af2-base-aa-01")
        self.assertEqual(protocol["control_retry_campaign"], "d3af2-base-aa-02")
        self.assertTrue(protocol["lane_scoped_paired_qualification"])
        self.assertEqual(len(protocol["campaigns"]), 5)
        self.assertEqual(protocol["stages"][0], "plan_ns")
        self.assertEqual(protocol["stages"][-1], "candidate_heap_ns")
        self.assertEqual(protocol["counters"][-1], "candidate_samples_key")

    def test_nine_lane_matrix_is_exact(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(
            protocol["lane_ids"],
            [
                "pr15d_v1/10000/absent/k100",
                "pr15d_v1/10000/rare/k100",
                "pr15d_v1/10000/medium/k100",
                "pr15d_v1/10000/common/k100",
                "pr15d_v1/100000/absent/k100",
                "pr15d_v1/100000/rare/k100",
                "pr15d_v1/100000/medium/k100",
                "pr15d_v1/100000/common/k100",
                "pr15d_v1/100000/common/k10",
            ],
        )

    def test_paired_and_control_schedules_are_frozen(self):
        protocol, _ = run.load_protocol()
        paired = run.slot_plan(protocol)
        self.assertEqual(len(paired), 24)
        self.assertEqual(
            [entry["arm"] for entry in paired[:6]], list("AQPPQA")
        )
        control = run.control_plan(protocol)
        self.assertEqual(len(control), 16)
        self.assertEqual([entry["arm"] for entry in control[:4]], ["A1", "A2", "A2", "A1"])


class ProtocolDiffTests(unittest.TestCase):
    """F2-V01/F2-V02: v3 is exactly the frozen v2 override set."""

    def test_v3_diff_is_exactly_thirteen_keys(self):
        with open(os.path.join(ROOT, "benchmarks", "pr15i_d3a", "protocol_v2.json"), encoding="utf-8") as handle:
            v2 = json.load(handle)
        with open(os.path.join(ROOT, "benchmarks", "pr15i_d3a", "protocol_v3.json"), encoding="utf-8") as handle:
            v3 = json.load(handle)
        changed = sorted(set(v2) ^ set(v3)) + sorted(
            key for key in set(v2) & set(v3) if v2[key] != v3[key]
        )
        self.assertEqual(
            sorted(changed),
            sorted([
                "campaigns", "control_campaign", "control_retry_campaign",
                "lane_scoped_excluded_run_policy", "lane_scoped_global_integrity_policy",
                "lane_scoped_joint_min_runs", "lane_scoped_min_eligible_runs",
                "lane_scoped_paired_qualification", "lane_scoped_primary_min_lanes",
                "lane_scoped_report_all_nine_lanes", "lane_scoped_statistic_policy",
                "measurement_family", "schema",
            ]),
        )

    def test_v2_protocol_is_rejected_by_v3_validator(self):
        with open(os.path.join(ROOT, "benchmarks", "pr15i_d3a", "protocol_v2.json"), encoding="utf-8") as handle:
            v2 = json.load(handle)
        with self.assertRaises(run.D3AError):
            run.validate_protocol(v2)


class HostTests(unittest.TestCase):
    """VT-18: contention and affinity gates."""

    def test_clear_probe_passes(self):
        module = mock.Mock()
        module.check_contention.return_value = {"state": "clear", "reason_codes": []}
        record = run.contention_probe(module, "/tmp/unused.json")
        self.assertEqual(record["state"], "clear")

    def test_nonclear_probe_blocks(self):
        module = mock.Mock()
        module.check_contention.return_value = {"state": "busy", "reason_codes": ["x"]}
        with self.assertRaises(run.D3ABlocked):
            run.contention_probe(module, "/tmp/unused.json")

    def test_single_allowed_cpu_blocks(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={0}):
            with self.assertRaises(run.D3ABlocked):
                run.affinity_plan()

    def test_two_cpus_pin_controller_second_adapter_first(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={1, 3}):
            with mock.patch.object(run.shutil, "which", return_value="/usr/bin/taskset"):
                self.assertEqual(run.affinity_plan(), (3, 1))


class PathAndWriteTests(unittest.TestCase):
    """VT-23/VT-25 support: exclusive writes and traversal refusal."""

    def test_exclusive_write_refuses_existing_and_preserves_bytes(self):
        root = tempfile.mkdtemp(prefix="d3a-write-")
        try:
            path = os.path.join(root, "evidence.json")
            run.write_json_exclusive(path, {"value": 1})
            with open(path, "rb") as handle:
                before = handle.read()
            with self.assertRaises(run.D3AError):
                run.write_json_exclusive(path, {"value": 2})
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), before)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(run.D3AError):
            run.confined("/tmp/d3a-root", "/tmp/d3a-root/../escape", "out")


class ArchiveTests(unittest.TestCase):
    """VT-23, VT-24 and VT-25."""

    def _campaign(self):
        root = tempfile.mkdtemp(prefix="d3a-archive-")
        files = {
            "raw/a.json": b'{"a":1}\n',
            "setup/contention/c.json": b'{"state":"clear"}\n',
            "setup/indexes/x/segment": b"excluded",
            "sanitized/summary.json": b'{"summary":1}\n',
        }
        for relative, payload in files.items():
            path = os.path.join(root, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(payload)
        return root

    def test_archive_members_exclude_indexes(self):
        protocol, _ = run.load_protocol()
        root = self._campaign()
        try:
            members = run._archive_members(root, protocol)
            self.assertIn("raw/a.json", members)
            self.assertIn("setup/contention/c.json", members)
            self.assertNotIn("setup/indexes/x/segment", members)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_archive_round_trip_and_member_tamper_is_rejected(self):
        protocol, _ = run.load_protocol()
        root = self._campaign()
        archive_dir = tempfile.mkdtemp(prefix="d3a-archive-out-")
        try:
            members = run._archive_members(root, protocol)
            archive = os.path.join(archive_dir, "campaign.tar.gz")
            inventory = run._write_archive(root, archive, members)
            with self.assertRaises(run.D3ABlocked):
                run._verify_archive(archive, {"raw/a.json": inventory["raw/a.json"]})
            inventory["raw/a.json"] = "0" * 64
            with self.assertRaises(run.D3ABlocked):
                run._verify_archive(archive, inventory)
            inventory = run._write_archive(root, archive + ".2", members)
            sidecar = archive + ".2.sha256"
            with open(sidecar, "w", encoding="utf-8") as handle:
                handle.write(
                    f"{run.sha256_file(archive + '.2')}  {os.path.basename(archive + '.2')}\n"
                )
            run.verify_archive_bundle(archive + ".2", sidecar, inventory)
            with open(sidecar, "w", encoding="utf-8") as handle:
                handle.write(f"{'0' * 64}  {os.path.basename(archive + '.2')}\n")
            with self.assertRaises(run.D3ABlocked):
                run.verify_archive_bundle(archive + ".2", sidecar, inventory)
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(archive_dir, ignore_errors=True)

    def test_symlink_member_is_rejected(self):
        protocol, _ = run.load_protocol()
        root = self._campaign()
        try:
            os.symlink(
                os.path.join(root, "raw/a.json"), os.path.join(root, "raw/link.json")
            )
            with self.assertRaises(run.D3AError):
                run._archive_members(root, protocol)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_safe_member_rejects_traversal_and_absolute_paths(self):
        for bad in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(verify.VerifyError):
                verify.safe_member(bad)
        self.assertEqual(verify.safe_member("raw/a.json"), "raw/a.json")


def control_timing(lane_id, ratios):
    ordered = sorted(ratios)
    median = (ordered[1] + ordered[2]) / 2
    return {
        "lanes": {
        lane_id: {
            "class": "absent" if "absent" in lane_id else "common",
            "kind": "low_match" if ("absent" in lane_id or "rare" in lane_id) else "medium_common",
            "campaign": {"a1_a2": median},
            "blocks": [
                {"block": index, "a1_a2": value}
                for index, value in enumerate(ratios, start=1)
            ],
        }
        }
    }


class ControlPolicyTests(unittest.TestCase):
    """F-CT01..F-CT11: prospective v2 A/A soft-outlier policy."""

    strict = "pr15d_v1/100000/common/k100"
    absent = "pr15d_v1/10000/absent/k100"
    rare = "pr15d_v1/10000/rare/k100"

    def _policy(self, lane, ratios):
        protocol, _ = run.load_protocol()
        return run.control_failures(control_timing(lane, ratios), protocol)

    def test_strict_lane_soft_bounds_are_inclusive(self):
        failures, tolerated = self._policy(self.strict, [0.80, 1.0, 1.0, 1.25])
        self.assertEqual(failures, [])
        self.assertEqual(tolerated, [])

    def test_strict_lane_one_unit_outside_fails(self):
        failures, _ = self._policy(self.strict, [0.80, 1.0, 1.0, 1.250001])
        self.assertTrue(any(item["gate"] == "CONTROL_BLOCK_RATIO" for item in failures))

    def test_exempt_absent_one_soft_outlier_is_tolerated(self):
        failures, tolerated = self._policy(
            self.absent, [1.2963446475195823, 1.0, 1.0, 1.0]
        )
        self.assertEqual(failures, [])
        self.assertEqual(len(tolerated), 1)
        self.assertEqual(tolerated[0]["block"], 1)

    def test_exempt_rare_one_soft_outlier_is_tolerated(self):
        failures, tolerated = self._policy(
            self.rare, [1.0, 1.0, 1.3114080164439876, 1.0]
        )
        self.assertEqual(failures, [])
        self.assertEqual(len(tolerated), 1)
        self.assertEqual(tolerated[0]["block"], 3)

    def test_each_exempt_lane_may_tolerate_one(self):
        protocol, _ = run.load_protocol()
        timing = {
            "lanes": {
                **control_timing(self.absent, [1.30, 1.0, 1.0, 1.0])["lanes"],
                **control_timing(self.rare, [1.0, 1.0, 1.30, 1.0])["lanes"],
            }
        }
        failures, tolerated = run.control_failures(timing, protocol)
        self.assertEqual(failures, [])
        self.assertEqual(len(tolerated), 2)

    def test_two_soft_outliers_in_one_exempt_lane_fail(self):
        failures, _ = self._policy(self.absent, [1.30, 1.31, 1.0, 1.0])
        self.assertEqual(sum(1 for item in failures if item["gate"] == "CONTROL_BLOCK_RATIO"), 2)

    def test_hard_outlier_fails_even_when_exempt(self):
        failures, _ = self._policy(self.absent, [1.500001, 1.0, 1.0, 1.0])
        self.assertTrue(any(item["gate"] == "CONTROL_HARD_OUTLIER" for item in failures))

    def test_hard_boundaries_are_inclusive(self):
        for value in (0.67, 1.50):
            failures, tolerated = self._policy(self.absent, [value, 1.0, 1.0, 1.0])
            self.assertFalse(any(item["gate"] == "CONTROL_HARD_OUTLIER" for item in failures))
            self.assertEqual(len(tolerated), 1)

    def test_median_failure_is_not_waived_by_soft_tolerance(self):
        failures, _ = self._policy(self.absent, [1.150001] * 4)
        self.assertTrue(any(item["gate"] == "CONTROL_LOWER_MEDIAN" for item in failures))

    def test_strict_10k_lane_soft_outlier_fails(self):
        failures, _ = self._policy("pr15d_v1/10000/medium/k100", [1.30, 1.0, 1.0, 1.0])
        self.assertTrue(any(item["gate"] == "CONTROL_BLOCK_RATIO" for item in failures))

    def test_nonfinite_or_negative_ratio_is_invalid(self):
        for value in (float("nan"), float("inf"), -1.0, True):
            with self.assertRaises(run.D3AInvalid):
                self._policy(self.strict, [value, 1.0, 1.0, 1.0])


class BuildNamespaceTests(unittest.TestCase):
    """F-BD01/F-BD05: distinct build groups and exclusive metadata."""

    def test_control_groups_are_distinct(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(run._control_build_group(protocol["control_campaign"], protocol), run.CONTROL_BUILD_GROUP_01)
        self.assertEqual(run._control_build_group(protocol["control_retry_campaign"], protocol), run.CONTROL_BUILD_GROUP_02)
        self.assertNotEqual(
            run._build_binary_path("/root", run.CONTROL_BUILD_GROUP_01, "A1"),
            run._build_binary_path("/root", run.CONTROL_BUILD_GROUP_02, "A1"),
        )
        self.assertNotEqual(
            run._build_meta_path("/root", run.SERIES_BUILD_GROUP, "A"),
            run._build_meta_path("/root", run.CONTROL_BUILD_GROUP_01, "A"),
        )

    def test_existing_build_metadata_is_refused_before_overwrite(self):
        root = tempfile.mkdtemp(prefix="d3af-build-")
        try:
            meta = run._build_meta_path(root, "group", "A")
            os.makedirs(os.path.dirname(meta), exist_ok=True)
            with open(meta, "w", encoding="utf-8") as handle:
                handle.write("sentinel")
            before = open(meta, "rb").read()
            with self.assertRaises(run.D3AError):
                run.cargo_build(root, "group", "A", None)
            self.assertEqual(open(meta, "rb").read(), before)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class CampaignIdentityTests(unittest.TestCase):
    """F-SE01/F-SE07/F-SE08: exact v2 campaign names and schedules."""

    def test_v2_names_are_recognized_and_v1_names_are_rejected(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(run.campaign_kind(protocol["control_campaign"], protocol), "control")
        self.assertEqual(run.campaign_kind(protocol["control_retry_campaign"], protocol), "control")
        for name in protocol["campaigns"]:
            self.assertEqual(run.campaign_kind(name, protocol), "paired")
        for old in ("d3af-base-aa-01", "d3af-unbatched-01", "d3af2-unbatched-06"):
            with self.assertRaises(run.D3AInvalid):
                run.campaign_kind(old, protocol)

    def test_schedules_are_unchanged(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(len(run.slot_plan(protocol)), 24)
        self.assertEqual(len(run.control_plan(protocol)), 16)


class ResponseValidationTests(unittest.TestCase):
    """VT-06 and VT-07 helper contracts."""

    def test_engine_ns_and_oracle_are_checked(self):
        lane = {"id": "pr15d_v1/10000/absent/k100"}
        expected = {"total_hits": 0, "doc_ids": []}
        run._validate_response(
            {"request_id": "r", "engine_ns": 1, "total_hits": 0, "doc_ids": []},
            lane, expected, "r",
        )
        for bad in (
            {"request_id": "r", "engine_ns": 0, "total_hits": 0, "doc_ids": []},
            {"request_id": "r", "engine_ns": -1, "total_hits": 0, "doc_ids": []},
            {"request_id": "r", "engine_ns": True, "total_hits": 0, "doc_ids": []},
            {"request_id": "r", "engine_ns": 1, "total_hits": 1, "doc_ids": []},
            {"request_id": "r", "engine_ns": 1, "total_hits": 0, "doc_ids": ["x"]},
        ):
            with self.assertRaises(run.D3AInvalid):
                run._validate_response(bad, lane, expected, "r")


if __name__ == "__main__":
    unittest.main()

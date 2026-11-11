#!/usr/bin/env python3
"""Controller tests for the PR 15I-D2-A tooling (BT matrix subset)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"d2a_{name}", os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("run")
verify = _load("verify")


class ProtocolTests(unittest.TestCase):
    """BT-22 and BT-01: frozen closed protocol and nine-lane schedule."""

    def test_frozen_protocol_matches_literal(self):
        protocol, digest = run.load_protocol()
        self.assertEqual(protocol, run.EXPECTED_PROTOCOL)
        self.assertEqual(len(digest), 64)

    def test_unknown_protocol_key_is_rejected(self):
        protocol = json.loads(json.dumps(run.EXPECTED_PROTOCOL))
        protocol["extra_threshold"] = 1
        with self.assertRaises(run.D2AError):
            run.validate_protocol(protocol)

    def test_protocol_schema_and_threshold_are_frozen(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(protocol["schema"], "pr15i-d2a-scoring-attribution-v1")
        self.assertEqual(protocol["q_a_ratio_ceiling_low_match"], 1.15)
        self.assertEqual(protocol["p_q_ratio_ceiling_medium_common"], 1.15)
        self.assertEqual(protocol["a_a_drift_median_min"], 0.85)
        self.assertEqual(protocol["a_a_drift_median_max"], 1.15)
        self.assertEqual(protocol["priority_gate"]["min_median_accumulate_ns"], 2_000_000)
        self.assertEqual(protocol["priority_gate"]["min_median_accumulate_share"], 0.08)

    def test_nine_lane_matrix_is_exact(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(len(protocol["lane_ids"]), 9)
        self.assertEqual(protocol["lane_ids"][-1], "pr15d_v1/100000/common/k10")
        self.assertEqual(
            [lane["id"] for lane in run.lane_descriptors(protocol)],
            protocol["lane_ids"],
        )

    def test_paired_and_control_schedules(self):
        protocol, _ = run.load_protocol()
        paired = run.slot_plan(protocol)
        self.assertEqual(len(paired), 24)
        self.assertEqual(
            [entry["arm"] for entry in paired[:6]], ["A", "Q", "P", "P", "Q", "A"]
        )
        control = run.control_plan(protocol)
        self.assertEqual(len(control), 16)
        self.assertEqual(
            [entry["arm"] for entry in control[:4]], ["A1", "A2", "A2", "A1"]
        )
        self.assertEqual(run.campaign_kind("d2a-base-aa-01", protocol), "control")
        self.assertEqual(run.campaign_kind("d2a-unbatched-01", protocol), "paired")


class StatisticsTests(unittest.TestCase):
    """BT-11/BT-12/BT-13/BT-14: exact frozen boundaries."""

    def _control_timing(self, ratio, block_ratios=None):
        block_ratios = block_ratios or [ratio, ratio, ratio, ratio]
        return {
            "lanes": {
                "pr15d_v1/100000/common/k100": {
                    "kind": "medium_common",
                    "blocks": [
                        {"block": index + 1, "a1_a2": value}
                        for index, value in enumerate(block_ratios)
                    ],
                    "campaign": {"a1_a2": ratio},
                }
            }
        }

    def _paired_timing(self, q_a, p_q):
        block = {
            "block": 1,
            "q_a": q_a,
            "p_q": p_q,
            "p_a": q_a * p_q,
            "a_a_drift": 1.0,
        }
        return {
            "lanes": {
                "pr15d_v1/100000/common/k100": {
                    "kind": "medium_common",
                    "blocks": [block],
                    "campaign": {"q_a": q_a, "p_q": p_q, "p_a": q_a * p_q, "a_a_drift": 1.0},
                }
            }
        }

    def test_control_lower_median_inclusive_boundaries(self):
        protocol, _ = run.load_protocol()
        for ratio in (0.85, 1.15):
            self.assertEqual(
                run.control_failures(self._control_timing(ratio), protocol), []
            )

    def test_control_lower_median_outside_boundaries_is_blocked(self):
        protocol, _ = run.load_protocol()
        for ratio in (0.84, 1.16):
            failures = run.control_failures(self._control_timing(ratio), protocol)
            self.assertTrue(
                any(item["gate"] == "CONTROL_LOWER_MEDIAN" for item in failures)
            )

    def test_control_block_boundaries_and_hard_outlier(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(
            run.control_failures(
                self._control_timing(1.0, [0.80, 1.0, 1.0, 1.25]), protocol
            ),
            [],
        )
        failures = run.control_failures(
            self._control_timing(1.0, [0.79, 1.0, 1.0, 1.0]), protocol
        )
        self.assertTrue(any(item["gate"] == "CONTROL_BLOCK_RATIO" for item in failures))
        failures = run.control_failures(
            self._control_timing(1.0, [1.51, 1.0, 1.0, 1.0]), protocol
        )
        self.assertTrue(any(item["gate"] == "CONTROL_HARD_OUTLIER" for item in failures))

    def test_intrusion_ceilings_are_inclusive(self):
        protocol, _ = run.load_protocol()
        self.assertEqual(
            run.intrusion_failures(self._paired_timing(1.10, 1.15), protocol), []
        )
        self.assertTrue(
            run.intrusion_failures(self._paired_timing(1.10 + 1e-9, 1.15), protocol)
        )
        self.assertTrue(
            run.intrusion_failures(self._paired_timing(1.10, 1.15 + 1e-9), protocol)
        )

    def test_low_match_ceilings(self):
        protocol, _ = run.load_protocol()
        timing = self._paired_timing(1.15, 1.25)
        timing["lanes"]["pr15d_v1/100000/common/k100"]["kind"] = "low_match"
        self.assertEqual(run.intrusion_failures(timing, protocol), [])


class PairValidationTests(unittest.TestCase):
    """BT-08/BT-15: exact closed stage and counter pairs."""

    def test_stage_pairs_require_exact_thirteen(self):
        pairs = [(label, 1) for label in run.STAGE_LABELS]
        self.assertEqual(len(pairs), 13)
        self.assertEqual(run._stage_pairs_to_arrays(pairs), [1] * 13)
        with self.assertRaises(run.D2AError):
            run._stage_pairs_to_arrays(pairs[:-1])
        with self.assertRaises(run.D2AError):
            run._stage_pairs_to_arrays(list(reversed(pairs)))
        with self.assertRaises(run.D2AError):
            run._stage_pairs_to_arrays(pairs + [("score_map_ns", 1)])

    def test_counter_pairs_require_exact_six(self):
        pairs = [(label, 2) for label in run.COUNTER_LABELS]
        self.assertEqual(len(pairs), 6)
        self.assertEqual(run._counter_pairs_to_arrays(pairs), [2] * 6)
        with self.assertRaises(run.D2AError):
            run._counter_pairs_to_arrays(pairs[:-1])
        with self.assertRaises(run.D2AError):
            run._counter_pairs_to_arrays(list(reversed(pairs)))

    def test_negative_counter_is_rejected(self):
        pairs = [(label, 1) for label in run.COUNTER_LABELS]
        pairs[3] = (run.COUNTER_LABELS[3], -1)
        with self.assertRaises(run.D2AError):
            run._counter_pairs_to_arrays(pairs)


class HostTests(unittest.TestCase):
    """BT-10: contention and affinity gates."""

    def test_clear_probe_passes(self):
        module = mock.Mock()
        module.check_contention.return_value = {"state": "clear", "reason_codes": []}
        record = run.contention_probe(module, "/tmp/unused.json")
        self.assertEqual(record["state"], "clear")

    def test_nonclear_probe_blocks(self):
        module = mock.Mock()
        module.check_contention.return_value = {"state": "busy", "reason_codes": ["x"]}
        with self.assertRaises(run.D2ABlocked):
            run.contention_probe(module, "/tmp/unused.json")

    def test_single_allowed_cpu_blocks(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={0}):
            with self.assertRaises(run.D2ABlocked):
                run.affinity_plan()

    def test_two_cpus_pin_controller_second_adapter_first(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={3, 1}):
            with mock.patch.object(run.shutil, "which", return_value="/usr/bin/taskset"):
                self.assertEqual(run.affinity_plan(), (3, 1))


class PathAndWriteTests(unittest.TestCase):
    """BT-24: exclusive evidence writes and traversal refusal."""

    def test_exclusive_write_refuses_existing_and_preserves_bytes(self):
        root = tempfile.mkdtemp(prefix="d2a-write-")
        try:
            path = os.path.join(root, "evidence.json")
            run.write_json_exclusive(path, {"value": 1})
            before = open(path, "rb").read()
            with self.assertRaises(run.D2AError):
                run.write_json_exclusive(path, {"value": 2})
            self.assertEqual(open(path, "rb").read(), before)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(run.D2AError):
            run.confined("/tmp/d2a-root", "/tmp/d2a-root/../escape", "out")


class ArchiveTests(unittest.TestCase):
    """BT-16: archive inventory, traversal, symlinks and digest mismatch."""

    def _campaign(self):
        root = tempfile.mkdtemp(prefix="d2a-archive-")
        files = {
            "raw/a.json": b'{"a":1}\\n',
            "setup/contention/c.json": b'{"state":"clear"}\\n',
            "setup/indexes/x/segment": b"excluded",
            "sanitized/summary.json": b'{"summary":1}\\n',
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

    def test_archive_round_trip_and_extra_member_rejected(self):
        protocol, _ = run.load_protocol()
        root = self._campaign()
        archive_dir = tempfile.mkdtemp(prefix="d2a-archive-out-")
        try:
            members = run._archive_members(root, protocol)
            archive = os.path.join(archive_dir, "campaign.tar.gz")
            inventory = run._write_archive(root, archive, members)
            self.assertTrue(os.path.isfile(archive))
            with self.assertRaises(run.D2ABlocked):
                run._verify_archive(archive, {"raw/a.json": inventory["raw/a.json"]})
            inventory["raw/a.json"] = "0" * 64
            with self.assertRaises(run.D2ABlocked):
                run._verify_archive(archive, inventory)
            inventory = run._write_archive(root, archive + ".2", members)
            sidecar = archive + ".2.sha256"
            with open(sidecar, "w", encoding="utf-8") as handle:
                handle.write(f"{run.sha256_file(archive + '.2')}  {os.path.basename(archive + '.2')}\n")
            run.verify_archive_bundle(archive + ".2", sidecar, inventory)
            with open(sidecar, "w", encoding="utf-8") as handle:
                handle.write(f"{'0' * 64}  {os.path.basename(archive + '.2')}\n")
            with self.assertRaises(run.D2ABlocked):
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
            with self.assertRaises(run.D2AError):
                run._archive_members(root, protocol)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

"""Deterministic unit tests for the PR 15I-A controller.

These tests use synthetic in-memory measurements only. They never claim a
production benchmark result.
"""

from __future__ import annotations

import importlib.util
import json
import os
import struct
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load_controller():
    spec = importlib.util.spec_from_file_location(
        "pr15i_a_run_under_test", os.path.join(HERE, "run.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = load_controller()


def container_bytes(payload: bytes, features, magic=b"TRWMSV01", bad_magic=False):
    """Build a minimal one-section mutation-state container."""
    header = bytearray(24)
    header[0:8] = b"BADMAGIC" if bad_magic else magic
    struct.pack_into("<H", header, 8, 1)   # major
    struct.pack_into("<H", header, 10, 0)  # minor
    header[12] = 1                          # little endian
    header[13] = 24                         # header length
    body = payload
    footer = bytearray()
    footer += struct.pack("<H", 1)          # footer version
    footer += struct.pack("<I", 1)          # section count
    footer += struct.pack("<I", len(features))
    for feature_id, version in features:
        footer += struct.pack("<HH", feature_id, version)
    footer += struct.pack("<I", 0)          # optional features
    footer += struct.pack("<H", 0x000F)     # kind MutationState
    footer += struct.pack("<H", 0)          # flags
    footer += struct.pack("<Q", 0)          # aux
    footer += struct.pack("<Q", len(header))  # body offset
    footer += struct.pack("<Q", len(body))    # body length
    footer += b"\x00" * 32                    # section digest (unused here)
    trailer_offset = len(header) + len(body) + len(footer)
    trailer = bytearray()
    trailer += b"TRWSTR01"
    trailer += struct.pack("<Q", len(header) + len(body))
    trailer += struct.pack("<Q", len(footer))
    trailer += struct.pack("<I", 1)
    trailer += struct.pack("<H", 1)
    trailer += struct.pack("<H", 0)
    trailer += b"\x00" * 32
    return bytes(header) + body + bytes(footer) + bytes(trailer)


def synthetic_arm(
    sidecar=9_600_180,
    total=30_965_025,
    factor=1.0,
    rss=128 * 1024 * 1024,
    remote_ns=2_000_000_000,
    lane_ns=1_000_000,
    samples_per_lane=run.MEASURED,
    sha="a" * 40,
):
    sizes = {
        "10000": {
            "sidecar_bytes": sidecar // 10,
            "segment_bytes": total // 2,
            "manifest_bytes": 600,
            "current_bytes": 183,
            "committed_index_bytes": total // 10,
            "state_containers": [{"payload_version": 3, "required_features": [[12, 1]]}],
        },
        "100000": {
            "sidecar_bytes": sidecar,
            "segment_bytes": total - sidecar,
            "manifest_bytes": 644,
            "current_bytes": 183,
            "committed_index_bytes": total,
            "state_containers": [{"payload_version": 3, "required_features": [[12, 1]]}],
        },
    }

    def blocks():
        return {
            "reopen": [
                {
                    "block": block,
                    "samples": [
                        {"open_ns": int(1_000_000_000 * factor), "maxrss_bytes": rss}
                        for _ in range(run.BLOCK_SAMPLES)
                    ],
                }
                for block in range(1, run.BLOCKS + 1)
            ],
            "build_commit": [
                {
                    "block": block,
                    "samples": [
                        {
                            "index_ns": int(2_000_000_000 * factor),
                            "commit_ns": int(1_000_000_000 * factor),
                            "maxrss_bytes": rss,
                        }
                        for _ in range(run.BLOCK_SAMPLES)
                    ],
                }
                for block in range(1, run.BLOCKS + 1)
            ],
            "remote": [
                {
                    "block": block,
                    "samples": [
                        {"open_ns": int(remote_ns * factor), "maxrss_bytes": rss}
                        for _ in range(run.BLOCK_SAMPLES)
                    ],
                }
                for block in range(1, run.BLOCKS + 1)
            ],
        }

    warm = []
    for block in range(1, run.BLOCKS + 1):
        for _ in range(2):
            warm.append(
                {
                    "block": block,
                    "arm": "A" if sha[0] == "a" else "B",
                    "trial": {
                        "lanes": [
                            {
                                "id": lane,
                                "summary_ns": {"median": int(lane_ns * factor)},
                                "samples_ns": [int(lane_ns * factor)] * samples_per_lane,
                                "oracle_ok": True,
                            }
                            for lane in run.LANE_IDS
                        ]
                    },
                }
            )
    return {
        "source_sha": sha,
        "sizes": {"n": sizes},
        "blocks": blocks(),
        "warm": warm,
        "oracles_ok": True,
        "feature_checks_ok": True,
        "adapter_sha256": "1" * 64,
        "reopen_sha256": "2" * 64,
        "remote_sha256": "3" * 64,
    }


class ProtocolTests(unittest.TestCase):
    def test_protocol_mirrors_controller_constants(self):
        root = os.path.dirname(HERE)
        root = os.path.dirname(root)
        protocol = run.load_protocol(root)
        self.assertEqual(protocol["limits"], run.LIMITS)
        self.assertEqual(protocol["measured"], run.MEASURED)
        self.assertEqual(protocol["warmups"], run.WARMUPS)
        self.assertEqual(len(protocol["schedule"]), run.BLOCKS)

    def test_schedule_is_balanced(self):
        self.assertEqual(len(run.SCHEDULE), 4)
        for order in run.SCHEDULE:
            self.assertEqual(sorted(order), ["A", "A", "B", "B"])
        for arm in ("A", "B"):
            count = sum(1 for order in run.SCHEDULE for candidate in order if candidate == arm)
            self.assertEqual(count, 8)
        self.assertEqual(sum(1 for order in run.BLOCK_ARM_ORDER for a in order if a == "A"), 4)


class ArithmeticTests(unittest.TestCase):
    def test_conventional_median_uses_two_middle_values(self):
        self.assertAlmostEqual(run.conventional_median([1.0, 2.0, 3.0, 4.0]), 2.5)
        self.assertAlmostEqual(run.conventional_median([4.0, 2.0, 1.0, 3.0]), 2.5)

    def test_ratio_rejects_zero_baseline(self):
        with self.assertRaises(run.RunBlocked):
            run.ratio(1.0, 0.0)

    def test_gate_boundaries(self):
        self.assertEqual(run.gate([1.10] * 4, 1.10, 1.30), "PASS")
        self.assertEqual(run.gate([1.100001] * 4, 1.10, 1.30), "FAIL")
        self.assertEqual(run.gate([1.0, 1.0, 1.0, 1.30], 1.5, 1.30), "PASS")
        self.assertEqual(run.gate([1.0, 1.0, 1.0, 1.300001], 1.5, 1.30), "FAIL")


class DeriveTests(unittest.TestCase):
    def accepted_b(self, sidecar=4_800_090, total=29_416_770, **kwargs):
        # A storage-improving candidate: 50% sidecar, just under 95% total.
        return synthetic_arm(sidecar=sidecar, total=total, sha="b" * 40, **kwargs)

    def test_improving_candidate_passes_every_campaign_gate(self):
        a = synthetic_arm()
        b = self.accepted_b()
        report, _ = run.derive(a, b)
        self.assertEqual(report["decision"], "A_CANDIDATE_ACCEPTED_PENDING_QA")
        self.assertTrue(all(value == "PASS" for value in report["gates"].values()))
        self.assertAlmostEqual(report["size_ratios"]["100000_sidecar"], 0.5, places=6)

    def test_identical_size_candidate_is_rejected(self):
        a = synthetic_arm()
        b = synthetic_arm(sha="b" * 40)
        report, _ = run.derive(a, b)
        self.assertEqual(report["gates"]["A-P01"], "FAIL")
        self.assertEqual(report["decision"], "A_SIZE_REJECTED_SAFE_ROLLBACK")

    def test_size_regression_is_rejected(self):
        a = synthetic_arm()
        b = self.accepted_b(sidecar=9_000_000, total=30_500_000)
        report, _ = run.derive(a, b)
        self.assertEqual(report["gates"]["A-P01"], "FAIL")
        self.assertEqual(report["gates"]["A-P02"], "FAIL")
        self.assertEqual(report["decision"], "A_SIZE_REJECTED_SAFE_ROLLBACK")

    def test_ten_k_growth_is_rejected(self):
        a = synthetic_arm()
        b = self.accepted_b()
        b["sizes"]["n"]["10000"]["sidecar_bytes"] = int(
            a["sizes"]["n"]["10000"]["sidecar_bytes"] * 1.03
        )
        report, _ = run.derive(a, b)
        self.assertEqual(report["gates"]["A-P03"], "FAIL")
        self.assertEqual(report["decision"], "A_SIZE_REJECTED_SAFE_ROLLBACK")

    def test_latency_regression_is_rejected(self):
        a = synthetic_arm()
        b = self.accepted_b(factor=2.0)
        report, _ = run.derive(a, b)
        self.assertEqual(report["gates"]["A-P04"], "FAIL")
        self.assertEqual(report["decision"], "A_PERF_REJECTED_SAFE_ROLLBACK")

    def test_memory_regression_is_rejected(self):
        a = synthetic_arm()
        b = self.accepted_b(rss=160 * 1024 * 1024)
        report, _ = run.derive(a, b)
        self.assertEqual(report["gates"]["A-P08"], "FAIL")
        self.assertEqual(report["decision"], "A_PERF_REJECTED_SAFE_ROLLBACK")

    def test_remote_regression_is_rejected(self):
        a = synthetic_arm()
        b = self.accepted_b(remote_ns=10_000_000_000)
        report, _ = run.derive(a, b)
        self.assertEqual(report["gates"]["A-P09"], "FAIL")
        self.assertEqual(report["decision"], "A_PERF_REJECTED_SAFE_ROLLBACK")

    def test_missing_sample_is_a_typed_failure(self):
        a = synthetic_arm()
        b = self.accepted_b(samples_per_lane=run.MEASURED - 1)
        with self.assertRaises(run.RunBlocked):
            run.derive(a, b)

    def test_missing_lane_is_a_typed_failure(self):
        a = synthetic_arm()
        b = self.accepted_b()
        b["warm"][0]["trial"]["lanes"] = b["warm"][0]["trial"]["lanes"][:-1]
        with self.assertRaises(run.RunBlocked):
            run.derive(a, b)


class LayoutTests(unittest.TestCase):
    def test_mutation_state_layout_reads_version_and_features(self):
        payload = struct.pack("<H", 3) + struct.pack("<I", 0) + struct.pack("<I", 0)
        payload += struct.pack("<I", 0)
        data = container_bytes(payload, [(1, 1), (8, 1), (12, 1)])
        with tempfile.NamedTemporaryFile(suffix=".state", delete=False) as handle:
            handle.write(data)
            path = handle.name
        try:
            layout = run.mutation_state_layout(path)
        finally:
            os.unlink(path)
        self.assertEqual(layout["payload_version"], 3)
        self.assertIn([12, 1], layout["required_features"])
        self.assertGreater(layout["payload_bytes"], 0)

    def test_bad_magic_is_rejected(self):
        data = container_bytes(struct.pack("<H", 3), [(1, 1)], bad_magic=True)
        with tempfile.NamedTemporaryFile(suffix=".state", delete=False) as handle:
            handle.write(data)
            path = handle.name
        try:
            with self.assertRaises(run.RunBlocked):
                run.mutation_state_layout(path)
        finally:
            os.unlink(path)


class SourcePreflightTests(unittest.TestCase):
    def test_equal_arm_is_rejected(self):
        root = os.path.dirname(os.path.dirname(HERE))
        head = run._git(root, "rev-parse", "HEAD")
        with self.assertRaises(run.RunBlocked):
            run._check_preflight(root, head, head)

    def test_malformed_sha_is_rejected(self):
        root = os.path.dirname(os.path.dirname(HERE))
        with self.assertRaises(run.RunBlocked):
            run._check_preflight(root, "not-a-sha", "b" * 40)

    def test_outside_out_path_is_rejected(self):
        root = os.path.dirname(os.path.dirname(HERE))
        with self.assertRaises(run.RunBlocked):
            run.validate_out(root, "/tmp/pr15i-a-campaign")


if __name__ == "__main__":
    unittest.main()

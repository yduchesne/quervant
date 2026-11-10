#!/usr/bin/env python3
"""Pure-logic tests for the D0 controller (no Rust build required)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"d0_{name}", os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("run")


class ProtocolTests(unittest.TestCase):
    def test_frozen_protocol_matches_literal(self):
        protocol, digest = run.load_protocol()
        self.assertEqual(protocol, run.EXPECTED_PROTOCOL)
        self.assertEqual(digest, run.sha256_bytes(open(run.protocol_path(), "rb").read()))

    def test_one_hex_digit_difference_is_rejected(self):
        protocol = dict(run.EXPECTED_PROTOCOL)
        protocol["base_sha"] = protocol["base_sha"][:-1] + (
            "0" if protocol["base_sha"][-1] != "0" else "1"
        )
        with self.assertRaises(run.D0Error) as context:
            run.validate_protocol(protocol)
        self.assertEqual(context.exception.code, "D0_PROTOCOL")

    def test_unknown_protocol_key_is_rejected(self):
        protocol = dict(run.EXPECTED_PROTOCOL)
        protocol["unexpected"] = True
        with self.assertRaises(run.D0Error):
            run.validate_protocol(protocol)

    def test_stage_label_order_is_closed(self):
        protocol = dict(run.EXPECTED_PROTOCOL)
        protocol["stages"] = list(reversed(run.STAGE_LABELS))
        with self.assertRaises(run.D0Error):
            run.validate_protocol(protocol)


class ScheduleAndLaneTests(unittest.TestCase):
    def setUp(self):
        self.protocol = run.EXPECTED_PROTOCOL

    def test_frozen_schedule_literal(self):
        plan = run.slot_plan(self.protocol)
        self.assertEqual(len(plan), 24)
        self.assertEqual([entry["arm"] for entry in plan[:6]], list("AQPPQA"))
        self.assertEqual([entry["arm"] for entry in plan[6:12]], list("PQAAQP"))
        self.assertEqual([entry["arm"] for entry in plan[12:18]], list("QAPPAQ"))
        self.assertEqual([entry["arm"] for entry in plan[18:24]], list("PAQQAP"))
        for block in range(1, 5):
            arms = [entry["arm"] for entry in plan if entry["block"] == block]
            self.assertEqual(sorted(arms), ["A", "A", "P", "P", "Q", "Q"])

    def test_nine_lane_order(self):
        lanes = run.lane_descriptors(self.protocol)
        self.assertEqual([lane["id"] for lane in lanes], self.protocol["lane_ids"])
        self.assertEqual(lanes[-1]["k"], 10)
        self.assertEqual(lanes[-1]["kind"], "medium_common")

    def test_lane_descriptor_drift_is_rejected(self):
        with self.assertRaises(run.D0Invalid):
            run.parse_lane("pr15d_v1/20000/absent/k100")
        with self.assertRaises(run.D0Invalid):
            run.parse_lane("pr15d_v1/10000/absent/k0")


class SampleAndStageTests(unittest.TestCase):
    def test_samples_must_be_twenty_positive_integers(self):
        run.validate_samples([1] * 20)
        for bad in ([1] * 19, [1] * 21, [True] * 20, [0] * 20, [-1] * 20, ["1"] * 20):
            with self.subTest(bad=bad[:2]):
                with self.assertRaises(run.D0Invalid):
                    run.validate_samples(bad)

    def test_nearest_rank_median_uses_index_nine(self):
        samples = list(range(1, 21))
        self.assertEqual(run.nearest_rank_median_20(samples), 10)

    def test_exact_stage_partition_sums(self):
        engine = 1000
        stages = [1, 1, 1, 1, 990, 1, 1, 0, 0, 0]
        category = run.decompose_sample(engine, stages, [7, 7, 7], 7)
        self.assertEqual(sum(category.values()), engine)

    def test_negative_evaluate_residual_is_rejected(self):
        with self.assertRaises(run.D0Invalid) as context:
            run.decompose_sample(1000, [1, 1, 1, 1, 1, 1, 1, 5, 0, 0], [0, 0, 0], 0)
        self.assertEqual(context.exception.code, "D0_STAGE_PARTITION_INVALID")

    def test_stage_sum_overflow_is_rejected(self):
        with self.assertRaises(run.D0Invalid) as context:
            run.decompose_sample(10, [100, 0, 0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0], 0)
        self.assertEqual(context.exception.code, "D0_STAGE_PARTITION_INVALID")

    def test_counter_disagreement_is_rejected(self):
        with self.assertRaises(run.D0Invalid) as context:
            run.decompose_sample(100, [1, 1, 1, 1, 90, 1, 1, 0, 0, 0], [1, 1, 2], 2)
        self.assertEqual(context.exception.code, "D0_STAGE_COUNTER")

    def test_counter_type_is_rejected(self):
        with self.assertRaises(run.D0Invalid):
            run.decompose_sample(100, [1, 1, 1, 1, 90, 1, 1, 0, 0, 0], [True, 0, 0], 0)


class RankingTests(unittest.TestCase):
    def _lanes(self):
        lanes = {}
        for lane in run.lane_descriptors(run.EXPECTED_PROTOCOL):
            lanes[lane["id"]] = {
                category: {"median_ns": 10, "median_share": 0.1}
                for category in run.EXCLUSIVE_CATEGORIES
            }
            lanes[lane["id"]]["other_ns"]["median_ns"] = 5
            lanes[lane["id"]]["eval_residual_ns"]["median_ns"] = 5
        return lanes

    def test_tie_break_is_the_fixed_hypothesis_order(self):
        ranking = run.rank_hypotheses(self._lanes(), run.EXPECTED_PROTOCOL)
        self.assertEqual(ranking["primary"][0], "H-CANDIDATE")
        self.assertEqual(ranking["primary"][1], "H-LEAF")

    def test_other_tops_without_inventing_a_new_hypothesis(self):
        lanes = self._lanes()
        for lane in lanes:
            lanes[lane]["other_ns"]["median_ns"] = 1000
        ranking = run.rank_hypotheses(lanes, run.EXPECTED_PROTOCOL)
        self.assertTrue(ranking["other_tops"])
        self.assertEqual({item["id"] for item in ranking["register"]}, {
            "H-CANDIDATE", "H-LEAF", "H-MEMBERSHIP", "H-SCORE", "H-LIVE",
            "H-STATS", "H-PLAN", "H-PROJECTION", "H-OTHER",
        })


class EvidenceWritingTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(run.TARGET_ROOT, exist_ok=True)
        self.directory = tempfile.mkdtemp(prefix="run-", dir=run.TARGET_ROOT)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_exclusive_write_refuses_existing_and_preserves_bytes(self):
        path = os.path.join(self.directory, "evidence.json")
        run.write_json_exclusive(path, {"value": 1})
        original = open(path, "rb").read()
        with self.assertRaises(run.D0Error) as context:
            run.write_json_exclusive(path, {"value": 2})
        self.assertEqual(context.exception.code, "D0_WRITE_EXISTS")
        self.assertEqual(open(path, "rb").read(), original)

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(run.D0Error):
            run.confined(self.directory, os.path.join(self.directory, "..", "escape"), "out")
        with self.assertRaises(run.D0Error):
            run.confined(self.directory, "/tmp/escape", "out")

    def test_symlink_escape_is_rejected(self):
        outside = tempfile.mkdtemp(prefix="outside-")
        try:
            link = os.path.join(self.directory, "link")
            os.symlink(outside, link)
            with self.assertRaises(run.D0Error):
                run.confined(self.directory, os.path.join(link, "file"), "out")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_symlink_inside_root_is_allowed(self):
        inside = os.path.join(self.directory, "inner")
        os.makedirs(inside)
        link = os.path.join(self.directory, "link")
        os.symlink(inside, link)
        result = run.confined(self.directory, os.path.join(link, "file"), "out")
        self.assertTrue(result.startswith(os.path.realpath(self.directory)))


class AffinityAndContentionTests(unittest.TestCase):
    def test_two_allowed_cpus_select_controller_second_and_adapter_first(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={3, 7}):
            with mock.patch.object(run.shutil, "which", return_value="/usr/bin/taskset"):
                self.assertEqual(run.affinity_plan(), (7, 3))

    def test_single_allowed_cpu_blocks(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={5}):
            with self.assertRaises(run.D0Blocked):
                run.affinity_plan()

    def test_missing_taskset_blocks(self):
        with mock.patch.object(run.os, "sched_getaffinity", return_value={1, 2}):
            with mock.patch.object(run.shutil, "which", return_value=None):
                with self.assertRaises(run.D0Blocked):
                    run.affinity_plan()

    def _probe(self, record):
        module = mock.Mock()
        module.check_contention.return_value = record
        return module

    def test_clear_probe_passes(self):
        record = run.contention_probe(self._probe({"state": "clear", "reason_codes": []}), "/dev/null")
        self.assertEqual(record["state"], "clear")

    def test_nonclear_probe_blocks_the_campaign(self):
        for record in (
            {"state": "suspected", "reason_codes": ["cpu_busy"]},
            {"state": "unknown", "reason_codes": ["probe_failed"]},
            {"state": "clear", "reason_codes": ["unexpected"]},
        ):
            with self.subTest(record=record):
                with self.assertRaises(run.D0Blocked):
                    run.contention_probe(self._probe(record), "/dev/null")


class IndexSentinelTests(unittest.TestCase):
    def _layout(self, committed, stored, a_digest="a" * 64, qp_digest="a" * 64):
        entry = {
            "committed_index_bytes": committed,
            "stored_bytes": stored,
            "digest": a_digest,
            "files": [],
        }
        return {
            "builds": {
                "A": {"10000": dict(entry), "100000": dict(entry)},
                "QP": {
                    "10000": dict(entry, digest=qp_digest),
                    "100000": dict(entry, digest=qp_digest),
                },
            }
        }

    def test_frozen_sentinels_pass(self):
        protocol = run.EXPECTED_PROTOCOL
        layout = self._layout(
            protocol["100k_lz4_committed_index_sentinel"],
            protocol["100k_lz4_stored_section_sentinel"],
        )
        self.assertEqual(run.index_sentinel_failures(layout, protocol), [])

    def test_committed_sentinel_mismatch_is_rejected(self):
        protocol = run.EXPECTED_PROTOCOL
        layout = self._layout(
            protocol["100k_lz4_committed_index_sentinel"] + 1,
            protocol["100k_lz4_stored_section_sentinel"],
        )
        failures = run.index_sentinel_failures(layout, protocol)
        self.assertTrue(any(item["gate"] == "COMMITTED_INDEX_BYTES" for item in failures))

    def test_stored_sentinel_mismatch_is_rejected(self):
        protocol = run.EXPECTED_PROTOCOL
        layout = self._layout(
            protocol["100k_lz4_committed_index_sentinel"],
            protocol["100k_lz4_stored_section_sentinel"] + 1,
        )
        failures = run.index_sentinel_failures(layout, protocol)
        self.assertTrue(any(item["gate"] == "STORED_SECTION_BYTES" for item in failures))

    def test_a_qp_digest_mismatch_is_rejected(self):
        protocol = run.EXPECTED_PROTOCOL
        layout = self._layout(
            protocol["100k_lz4_committed_index_sentinel"],
            protocol["100k_lz4_stored_section_sentinel"],
            qp_digest="b" * 64,
        )
        failures = run.index_sentinel_failures(layout, protocol)
        self.assertTrue(any(item["gate"] == "A_QP_INDEX_DIGEST" for item in failures))


class StagePairTests(unittest.TestCase):
    def test_stage_pairs_require_exact_order(self):
        pairs = [(label, 1) for label in run.STAGE_LABELS]
        self.assertEqual(run._stage_pairs_to_arrays(pairs), [1] * 10)
        for bad in (
            pairs[:-1],
            list(reversed(pairs)),
            pairs + [("extra", 1)],
            [(pairs[0][0], True)] + pairs[1:],
        ):
            with self.subTest(length=len(bad)):
                with self.assertRaises(run.D0Invalid):
                    run._stage_pairs_to_arrays(bad)

    def test_counter_pairs_require_exact_order(self):
        pairs = [(label, 2) for label in run.COUNTER_LABELS]
        self.assertEqual(run._counter_pairs_to_arrays(pairs), [2, 2, 2])
        with self.assertRaises(run.D0Invalid):
            run._counter_pairs_to_arrays(list(reversed(pairs)))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Deterministic tests for the PR 15G-D isolated D2 A/X controller."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "pr15g_d_isolate_under_test", os.path.join(HERE, "isolate_d2.py")
)
iso = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(iso)


def fake_slots(a_median=100.0, x_median=90.0, overrides=None):
    overrides = overrides or {}
    slots = []
    for index, arm in enumerate(iso.flat_schedule(), start=1):
        lanes = []
        for lane in iso.LANE_IDS:
            base = a_median if arm == "A" else x_median
            median = overrides.get((arm, lane, index), base)
            lanes.append(
                {
                    "id": lane,
                    "oracle_ok": True,
                    "total_hits": 1,
                    "samples_ns": [1] * iso.SAMPLES,
                    "summary_ns": {"median": median},
                }
            )
        slots.append(
            {
                "slot_index": index,
                "block": 1 + (index - 1) // 4,
                "position": 1 + (index - 1) % 4,
                "arm": arm,
                "trial": {
                    "index": index,
                    "lanes": lanes,
                    "contention_before": {"state": "clear"},
                    "contention_after": {"state": "clear"},
                },
            }
        )
    return slots


def lanes_with(verdicts):
    return [{"id": lane_id, "verdict": verdicts.get(lane_id, "INCONCLUSIVE")} for lane_id in iso.LANE_IDS]


class ScheduleTests(unittest.TestCase):
    def test_literal_schedule_and_balance(self):
        self.assertEqual(
            iso.SCHEDULE,
            (
                ("A", "X", "X", "A"),
                ("X", "A", "A", "X"),
                ("X", "A", "A", "X"),
                ("A", "X", "X", "A"),
            ),
        )
        self.assertEqual(len(iso.flat_schedule()), 16)
        self.assertEqual(iso.flat_schedule().count("A"), 8)
        self.assertEqual(iso.flat_schedule().count("X"), 8)

    def test_raw_validation_rejects_partial_sample_and_contention(self):
        slots = fake_slots()
        iso.validate_raw({"schema": iso.SCHEMA}, slots)
        with self.assertRaises(Exception):
            iso.validate_raw({}, slots[:-1])
        slots[0]["trial"]["lanes"][0]["samples_ns"] = [1] * 19
        with self.assertRaises(Exception):
            iso.validate_raw({}, slots)
        slots = fake_slots()
        slots[0]["trial"]["contention_after"]["state"] = "busy"
        with self.assertRaises(Exception):
            iso.validate_raw({}, slots)

    def test_raw_validation_rejects_lane_reorder(self):
        slots = fake_slots()
        slots[0]["trial"]["lanes"][0], slots[0]["trial"]["lanes"][1] = (
            slots[0]["trial"]["lanes"][1],
            slots[0]["trial"]["lanes"][0],
        )
        with self.assertRaises(Exception):
            iso.validate_raw({}, slots)


class ArithmeticTests(unittest.TestCase):
    def test_block_medians_and_ratios(self):
        slots = fake_slots()
        self.assertEqual(iso.block_medians(slots, "A", iso.LANE_IDS[0]), [100.0] * 4)
        self.assertEqual(iso.block_medians(slots, "X", iso.LANE_IDS[0]), [90.0] * 4)
        ratios = iso.pair_ratios(slots, iso.LANE_IDS[0])
        self.assertEqual(ratios, [0.9] * 4)
        self.assertEqual(iso.lane_verdict(ratios), "X_FASTER")

    def test_arithmetic_median_of_two_slots(self):
        slots = fake_slots()
        lane = iso.LANE_IDS[0]
        slots[0]["trial"]["lanes"][0]["summary_ns"]["median"] = 80.0
        slots[3]["trial"]["lanes"][0]["summary_ns"]["median"] = 100.0
        self.assertEqual(iso.block_medians(slots, "A", lane)[0], 90.0)

    def test_verdict_equality_and_mixed_signs(self):
        self.assertEqual(iso.lane_verdict([1.0, 0.9, 0.9, 0.9]), "INCONCLUSIVE")
        self.assertEqual(iso.lane_verdict([0.9, 1.01, 0.9, 0.9]), "INCONCLUSIVE")
        self.assertEqual(iso.lane_verdict([1.1, 1.2, 1.05, 1.0]), "INCONCLUSIVE")
        self.assertEqual(iso.lane_verdict([1.1, 1.2, 1.05, 1.01]), "A_FASTER")

    def test_drift_boundaries(self):
        slots = fake_slots()
        lane_index = 4
        # Give the two 100K A slots in block 1 exactly 1.25 apart.
        slots[0]["trial"]["lanes"][lane_index]["summary_ns"]["median"] = 80.0
        slots[3]["trial"]["lanes"][lane_index]["summary_ns"]["median"] = 100.0
        iso.drift_report(slots)
        slots[3]["trial"]["lanes"][lane_index]["summary_ns"]["median"] = 100.1
        with self.assertRaises(Exception):
            iso.drift_report(slots)


class GateTests(unittest.TestCase):
    def test_both_common_lanes_required(self):
        verdicts = {
            "pr15d_v1/100000/common/k100": "X_FASTER",
            "pr15d_v1/100000/common/k10": "X_FASTER",
        }
        gates = iso.gate_verdicts(lanes_with(verdicts))
        self.assertEqual(gates["DX-P01"], "PASS")
        self.assertEqual(gates["DX-P02"], "PASS")
        self.assertEqual(gates["status"], "ACCEPT_D2_ONLY")
        verdicts["pr15d_v1/100000/common/k10"] = "INCONCLUSIVE"
        self.assertEqual(iso.gate_verdicts(lanes_with(verdicts))["DX-P01"], "FAIL")

    def test_guardrail_blocks_acceptance(self):
        verdicts = {
            "pr15d_v1/100000/common/k100": "X_FASTER",
            "pr15d_v1/100000/common/k10": "X_FASTER",
            "pr15d_v1/10000/rare/k100": "A_FASTER",
        }
        gates = iso.gate_verdicts(lanes_with(verdicts))
        self.assertEqual(gates["DX-P02"], "FAIL")
        self.assertEqual(gates["status"], "D2_ONLY_PERFORMANCE_REJECTED")


class OutputTests(unittest.TestCase):
    def test_out_must_be_inside_campaign_tree(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(Exception):
                iso.validate_out(root, os.path.join(root, "elsewhere"))
            target = os.path.join(root, "target", "pr15g-d-d2-isolation", "campaigns", "x")
            self.assertEqual(iso.validate_out(root, target), os.path.realpath(target))

    def test_sanitizer_rejects_absolute_paths(self):
        with self.assertRaises(Exception):
            iso._clean("/home/x")

    def test_render_json_and_markdown_are_canonical_bytes(self):
        report = {
            "schema": iso.SCHEMA,
            "source_shas": {"A": iso.ARM_A, "X": "x" * 40},
            "lanes": [{"id": lane, "verdict": "INCONCLUSIVE"} for lane in iso.LANE_IDS],
            "comparisons": {
                lane: {
                    "a_block_medians_ns": [1.0] * 4,
                    "x_block_medians_ns": [1.0] * 4,
                    "ratios": [1.0] * 4,
                    "verdict": "INCONCLUSIVE",
                }
                for lane in iso.LANE_IDS
            },
            "drift": {},
            "gates": {"status": "D2_ONLY_PERFORMANCE_REJECTED"},
        }
        self.assertTrue(iso.render_json(report).endswith(b"\n"))
        self.assertEqual(iso.render_json(report), iso.render_json(report))
        self.assertIn(b"PR 15G-D D2-only", iso.render_markdown(report))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Deterministic tests for the PR 15G-D three-arm confirmation controller."""

from __future__ import annotations

import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "pr15g_d_confirm_under_test", os.path.join(HERE, "confirm.py")
)
confirm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(confirm)


def fake_slots(base_medians=None):
    base_medians = base_medians or {"A": 100.0, "B": 90.0, "C": 80.0}
    slots = []
    for index, arm in enumerate(confirm.flat_schedule(), start=1):
        lanes = []
        for lane in confirm.LANE_IDS:
            median = base_medians[arm] + (0.5 if index % 2 == 0 else 0.0)
            lanes.append(
                {
                    "id": lane,
                    "oracle_ok": True,
                    "total_hits": 1,
                    "samples_ns": [1] * confirm.BASE.pr15d_run.MEASURED,
                    "summary_ns": {"median": median},
                }
            )
        slots.append(
            {
                "slot_index": index,
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


class ScheduleTests(unittest.TestCase):
    def test_schedule_is_literal_and_balanced(self):
        self.assertEqual(
            confirm.SCHEDULE,
            (
                ("A", "B", "C", "C", "B", "A"),
                ("B", "C", "A", "A", "C", "B"),
                ("C", "A", "B", "B", "A", "C"),
            ),
        )
        self.assertEqual(confirm.arm_counts(), {"A": 6, "B": 6, "C": 6})
        self.assertEqual(len(confirm.flat_schedule()), 18)

    def test_raw_validation_rejects_partial_and_contention(self):
        slots = fake_slots()
        manifest = {"schema": confirm.SCHEMA}
        confirm.validate_raw(manifest, slots)
        with self.assertRaises(Exception):
            confirm.validate_raw(manifest, slots[:-1])
        slots[0]["trial"]["contention_before"]["state"] = "busy"
        with self.assertRaises(Exception):
            confirm.validate_raw(manifest, slots)


class ArithmeticTests(unittest.TestCase):
    def test_hand_computed_block_medians_and_ratios(self):
        slots = fake_slots()
        self.assertEqual(confirm.block_medians(slots, "A", confirm.LANE_IDS[0]), [100.25, 100.25, 100.25])
        self.assertEqual(confirm.block_medians(slots, "B", confirm.LANE_IDS[0]), [90.25, 90.25, 90.25])
        self.assertEqual(confirm.block_medians(slots, "C", confirm.LANE_IDS[0]), [80.25, 80.25, 80.25])
        ratios = confirm.pairwise_ratios([90.25, 90.25, 90.25], [100.25, 100.25, 100.25])
        self.assertEqual(confirm.pairwise_verdict(ratios), "B_FASTER")

    def test_verdict_boundaries(self):
        self.assertEqual(confirm.pairwise_verdict([0.9, 0.99, 0.8]), "B_FASTER")
        self.assertEqual(confirm.pairwise_verdict([1.1, 1.01, 1.2]), "A_FASTER")
        self.assertEqual(confirm.pairwise_verdict([0.9, 1.01, 0.8]), "INCONCLUSIVE")
        self.assertEqual(confirm.pairwise_verdict([1.0, 0.9, 0.9]), "INCONCLUSIVE")

    def test_drift_thresholds(self):
        slots = fake_slots()
        report = confirm.drift_report(slots)
        self.assertTrue(report["A"][confirm.LANE_IDS[0]]["within_ok"])
        self.assertTrue(report["A"][confirm.LANE_IDS[0]]["cross_ok"])
        slots[0]["trial"]["lanes"][0]["summary_ns"]["median"] = 100.0
        slots[6]["trial"]["lanes"][0]["summary_ns"]["median"] = 100.0
        self.assertTrue(confirm.drift_metrics(slots, "A", confirm.LANE_IDS[0])["within_ok"])


class GateTests(unittest.TestCase):
    def comparisons(self, verdicts):
        rows = []
        for lane in confirm.LANE_IDS:
            rows.append({"id": lane, "ratios": [1.0, 1.0, 1.0], "verdict": verdicts.get(lane, "INCONCLUSIVE")})
        return {"B/A": rows, "C/B": rows, "C/A": rows}

    def test_d1_gate_requires_absent_and_no_guardrail(self):
        comparisons = self.comparisons({"pr15d_v1/100000/absent/k100": "B_FASTER"})
        gates = confirm.gate_verdicts(comparisons)
        self.assertEqual(gates["CF-P01"], "PASS")
        self.assertEqual(gates["CF-P02"], "PASS")
        comparisons = self.comparisons(
            {
                "pr15d_v1/100000/absent/k100": "B_FASTER",
                "pr15d_v1/10000/rare/k100": "A_FASTER",
            }
        )
        self.assertEqual(confirm.gate_verdicts(comparisons)["CF-P02"], "FAIL")

    def test_d2_gate_accepts_either_target(self):
        comparisons = self.comparisons({"pr15d_v1/100000/common/k100": "B_FASTER"})
        gates = confirm.gate_verdicts(comparisons)
        self.assertEqual(gates["CF-P03"], "PASS")
        self.assertEqual(gates["CF-P04"], "PASS")


class SanitizerTests(unittest.TestCase):
    def test_sanitizer_rejects_paths_and_accepts_hashes(self):
        report = {
            "schema": confirm.SCHEMA,
            "source_shas": {"A": confirm.ARM_A},
            "lanes": list(confirm.LANE_IDS),
            "comparisons": {},
            "drift": {},
            "gates": {"status": "FULLY_RECONFIRMED"},
        }
        self.assertEqual(confirm.sanitize(report["comparisons"], report["gates"], report["drift"])["schema"], confirm.SCHEMA)
        with self.assertRaises(Exception):
            confirm.sanitize({"x": "/home/user"}, {}, {})


if __name__ == "__main__":
    unittest.main()

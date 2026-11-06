#!/usr/bin/env python3
"""Deterministic tests for the PR 15G-E A/E runner."""

from __future__ import annotations

import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("pr15g_e_run", os.path.join(HERE, "run.py"))
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


def fake_slots(a=100, e=90):
    slots = []
    for index, arm in enumerate(run.flat_schedule(), 1):
        lanes = []
        for lane in run.LANE_IDS:
            ns = a if arm == "A" else e
            samples = [int(ns)] * run.SAMPLES
            lanes.append({
                "id": lane,
                "samples_ns": samples,
                "summary_ns": run.BASE.pr15d_run.summarize(samples),
                "oracle_ok": True,
            })
        slots.append({
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
        })
    return slots


class ScheduleTests(unittest.TestCase):
    def test_literal_balance(self):
        self.assertEqual(
            run.SCHEDULE,
            (("A", "E", "E", "A"), ("E", "A", "A", "E"), ("E", "A", "A", "E"), ("A", "E", "E", "A")),
        )
        self.assertEqual(run.flat_schedule().count("A"), 8)
        self.assertEqual(run.flat_schedule().count("E"), 8)

    def test_medians_and_results(self):
        slots = fake_slots()
        self.assertEqual(run._medians(slots, "A", run.LANE_IDS[0]), [100.0] * 4)
        self.assertEqual(run._medians(slots, "E", run.LANE_IDS[0]), [90.0] * 4)
        rows = run._results(slots)
        self.assertTrue(all(row["verdict"] == "E_FASTER" for row in rows))

    def test_gates_require_rare_win_and_no_regression(self):
        rows = [{"id": lane, "verdict": "INCONCLUSIVE"} for lane in run.LANE_IDS]
        self.assertEqual(run._gates(rows)["E-P03"], "FAIL")
        rows[5]["verdict"] = "E_FASTER"
        self.assertEqual(run._gates(rows)["E-P03"], "PASS")
        rows[0]["verdict"] = "A_FASTER"
        gates = run._gates(rows)
        self.assertEqual(gates["E-P04"], "FAIL")
        self.assertEqual(gates["status"], "REJECT_E_ROLLED_BACK")

    def test_drift_boundaries(self):
        slots = fake_slots()
        drift, violations = run._drift(slots)
        self.assertEqual(violations, [])
        # 100K rare lane, block 1 A slots are 1 and 4.
        slots[0]["trial"]["lanes"][4] = {
            "id": run.LANE_IDS[4],
            "samples_ns": [80] * run.SAMPLES,
            "summary_ns": run.BASE.pr15d_run.summarize([80] * run.SAMPLES),
            "oracle_ok": True,
        }
        slots[4]["trial"]["lanes"][4] = {
            "id": run.LANE_IDS[4],
            "samples_ns": [101] * run.SAMPLES,
            "summary_ns": run.BASE.pr15d_run.summarize([101] * run.SAMPLES),
            "oracle_ok": True,
        }
        # slot index 4 is E in this schedule; adjust an A slot instead: block1 A is index 1 and 4? index4=A.
        slots[3]["trial"]["lanes"][4] = {
            "id": run.LANE_IDS[4],
            "samples_ns": [101] * run.SAMPLES,
            "summary_ns": run.BASE.pr15d_run.summarize([101] * run.SAMPLES),
            "oracle_ok": True,
        }
        drift, violations = run._drift(slots)
        self.assertTrue(violations)


if __name__ == "__main__":
    unittest.main()

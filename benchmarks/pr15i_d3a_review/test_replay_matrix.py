#!/usr/bin/env python3
"""Deterministic tests for the F2 review replay harness."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "benchmarks", "pr15i_d3a_review", "replay_matrix.py")


def load():
    spec = importlib.util.spec_from_file_location("review_replay", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


replay = load()


def valid_records():
    records = []
    for scenario, expectation in replay.EXPECTATIONS.items():
        result = expectation["result"]
        if result == "EXPECTED_KNOWN_GAP":
            record = {"scenario": scenario, "actual_result": "ACCEPTED"}
        elif result == "REJECTED":
            record = {
                "scenario": scenario,
                "actual_result": "REJECTED",
                "status": expectation.get("status"),
                "code": expectation["code"],
            }
        elif scenario == "positive_aggregate":
            record = {
                "scenario": scenario,
                "actual_result": "PASS",
                "completion_state": expectation["completion_state"],
                "verdict": expectation["verdict"],
                "campaign_count": expectation["campaign_count"],
                "control_qualified": expectation["control_qualified"],
                "component": expectation["component"],
                "lanes": expectation["lanes"],
                "runs": expectation["runs"],
            }
        elif scenario == "four_shared":
            record = {
                "scenario": scenario,
                "actual_result": "PASS",
                "verdict": expectation["verdict"],
                "component": expectation["component"],
            }
        elif scenario == "three_shared":
            record = {
                "scenario": scenario,
                "actual_result": "NOT_LOCALIZED",
                "verdict": expectation["verdict"],
            }
        else:
            raise AssertionError(f"unhandled scenario {scenario}")
        records.append(record)
    return records


class ValidationTests(unittest.TestCase):
    def test_complete_valid_matrix_passes(self):
        result = replay.validate_results(valid_records())
        self.assertEqual(result["overall_status"], "PASS")
        self.assertEqual(result["expected_scenario_count"], 11)
        self.assertEqual(result["executed_scenario_count"], 11)
        self.assertEqual(result["unexpected_outcome_count"], 0)

    def test_unexpected_acceptance_fails(self):
        records = valid_records()
        next(item for item in records if item["scenario"] == "oracle_tamper").update(
            {"actual_result": "ACCEPTED", "status": "PASS", "code": None}
        )
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertGreaterEqual(result["unexpected_outcome_count"], 1)

    def test_wrong_rejection_code_fails(self):
        records = valid_records()
        next(item for item in records if item["scenario"] == "oracle_tamper")["code"] = "V_SEAL"
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")

    def test_three_run_localization_fails(self):
        records = valid_records()
        next(item for item in records if item["scenario"] == "three_shared").update(
            {"actual_result": "PASS", "verdict": "D3A_CANDIDATE_HOTSPOT_LOCALIZED"}
        )
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")

    def test_wrong_positive_component_fails(self):
        records = valid_records()
        next(item for item in records if item["scenario"] == "positive_aggregate")[
            "component"
        ] = "candidate_key"
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")

    def test_missing_scenario_fails(self):
        records = [item for item in valid_records() if item["scenario"] != "oracle_tamper"]
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertIn("oracle_tamper", result["missing_scenarios"])

    def test_duplicate_scenario_fails(self):
        records = valid_records()
        records.append(copy.deepcopy(next(item for item in records if item["scenario"] == "oracle_tamper")))
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertIn("oracle_tamper", result["duplicate_scenarios"])

    def test_unexpected_scenario_fails(self):
        records = valid_records()
        records.append({"scenario": "unexpected_case", "actual_result": "PASS"})
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertIn("unexpected_case", result["extra_scenarios"])

    def test_known_gap_behavior_change_fails(self):
        records = valid_records()
        next(item for item in records if item["scenario"] == "altered_protocol").update(
            {"actual_result": "REJECTED", "status": "INVALID", "code": "V_SOURCES"}
        )
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")

    def test_exception_cannot_produce_pass(self):
        records = valid_records()
        next(item for item in records if item["scenario"] == "oracle_tamper").update(
            {"actual_result": "ERROR", "status": "ERROR", "code": "RuntimeError"}
        )
        result = replay.validate_results(records)
        self.assertEqual(result["overall_status"], "FAIL")

    def test_wrong_expectation_sanity_check_fails(self):
        expectations = copy.deepcopy(replay.EXPECTATIONS)
        expectations["oracle_tamper"] = {"result": "PASS"}
        result = replay.validate_results(valid_records(), expectations)
        self.assertEqual(result["overall_status"], "FAIL")


class PathTests(unittest.TestCase):
    def test_positive_replay_paths_are_review_owned(self):
        copied_series, copied_control = replay.positive_paths()
        self.assertTrue(copied_series.startswith(replay.REVIEW))
        self.assertTrue(copied_control.startswith(replay.REVIEW))
        self.assertNotEqual(copied_series, replay.SERIES)
        self.assertNotEqual(copied_control, replay.CONTROL)

    def test_snapshot_detects_change_and_ignores_unchanged(self):
        root = tempfile.mkdtemp(prefix="d3af2-review-snapshot-")
        try:
            path = os.path.join(root, "evidence.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"value":1}\n')
            before = replay.snapshot_tree(root)
            same = replay.compare_snapshot(before, replay.snapshot_tree(root))
            self.assertTrue(same["unchanged"])
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"value":2}\n')
            changed = replay.compare_snapshot(before, replay.snapshot_tree(root))
            self.assertFalse(changed["unchanged"])
            self.assertTrue(changed["changed"])
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

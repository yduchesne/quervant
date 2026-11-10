#!/usr/bin/env python3
"""PR 15I-C controller tests: fail-closed paths and derivation arithmetic."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load():
    spec = importlib.util.spec_from_file_location("pr15i_c_run", os.path.join(HERE, "run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = load()


def synthetic_slots(lane_ids, a_medians, b_medians):
    """Build a full 16-slot schedule with the given per-block A/B medians."""
    slots = []
    index = 0
    for block, order in enumerate(run.SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            index += 1
            base = a_medians[block - 1] if arm == "A" else b_medians[block - 1]
            lanes = [
                {
                    "id": lane_id,
                    "samples_ns": [base] * run.MEASURED,
                    "summary_ns": run.base.pr15d_run.summarize([base] * run.MEASURED),
                    "oracle_ok": True,
                    "total_hits": 1,
                }
                for lane_id in lane_ids
            ]
            slots.append({"slot_index": index, "block": block, "position": position,
                          "arm": arm, "trial": {"lanes": lanes}})
    return slots


class ProtocolTests(unittest.TestCase):
    def test_protocol_matches_frozen_constants(self):
        protocol = run.load_protocol(ROOT)
        self.assertEqual(protocol["schema"], "pr15i-c-physical-v1")
        self.assertEqual(protocol["baseline_source"], run.BASE_15IB)

    def test_protocol_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, run.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["primary_median_ratio_max"] = 0.95
            with open(os.path.join(root, run.PROTOCOL_REL), "w", encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(run.RunBlocked):
                run.load_protocol(root)

    def test_schedule_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, run.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["slot_schedule"] = ["ABBA", "ABBA", "BAAB", "BAAB"]
            with open(os.path.join(root, run.PROTOCOL_REL), "w", encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(run.RunBlocked):
                run.load_protocol(root)


class OutputPathTests(unittest.TestCase):
    def test_relative_out_is_rejected(self):
        with self.assertRaises(run.RunBlocked):
            run.validate_out(ROOT, "target/pr15i-c/campaigns/run")

    def test_outside_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(run.RunBlocked):
                run.validate_out(ROOT, os.path.join(directory, "campaign"))

    def test_existing_out_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            allowed = os.path.join(directory, "target", "pr15i-c", "campaigns", "paired-01")
            os.makedirs(allowed)
            with self.assertRaises(run.RunBlocked):
                run.validate_out(directory, allowed)

    def test_fresh_out_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = os.path.join(directory, "target", "pr15i-c", "campaigns", "paired-01")
            self.assertEqual(run.validate_out(directory, candidate), os.path.realpath(candidate))


class ExecuteGuardTests(unittest.TestCase):
    def test_idle_confirmation_is_required(self):
        parser = run.build_parser()
        args = parser.parse_args([
            "--checkout-root", ROOT, "--baseline-sha", run.BASE_15IB,
            "--candidate-sha", run.BASE_15IB, "--out",
            os.path.join(ROOT, "target", "pr15i-c", "campaigns", "never-created"),
        ])
        self.assertEqual(run.execute(args), 3)

    def test_candidate_equal_to_baseline_is_rejected(self):
        parser = run.build_parser()
        args = parser.parse_args([
            "--checkout-root", ROOT, "--baseline-sha", run.BASE_15IB,
            "--candidate-sha", run.BASE_15IB, "--out",
            os.path.join(ROOT, "target", "pr15i-c", "campaigns", "never-created"),
            "--idle-confirmed",
        ])
        with self.assertRaises(run.RunBlocked):
            run.execute(args)

    def test_pr15ia_baseline_is_rejected(self):
        parser = run.build_parser()
        args = parser.parse_args([
            "--checkout-root", ROOT, "--baseline-sha", run.P0_15IA,
            "--candidate-sha", run.BASE_15IB, "--out",
            os.path.join(ROOT, "target", "pr15i-c", "campaigns", "never-created"),
            "--idle-confirmed",
        ])
        with self.assertRaises(run.RunBlocked):
            run.execute(args)


class DerivationTests(unittest.TestCase):
    def test_ratios_and_gates_are_computed_from_block_means(self):
        slots = synthetic_slots(run.LANE_IDS, [100, 100, 100, 100], [85, 88, 90, 80])
        a_slots = [slot for slot in slots if slot["arm"] == "A"]
        b_slots = [slot for slot in slots if slot["arm"] == "B"]
        values = run.block_ratios(a_slots, b_slots, run.PRIMARY_LANES[0])
        self.assertEqual(len(values), 4)
        for value, expected in zip(values, [0.85, 0.88, 0.90, 0.80]):
            self.assertAlmostEqual(value, expected, places=12)
        self.assertAlmostEqual(run.lane_median(values), 0.865, places=12)

    def test_missing_block_samples_are_rejected(self):
        slots = synthetic_slots(run.LANE_IDS, [100] * 4, [90] * 4)
        a_slots = [slot for slot in slots if slot["arm"] == "A"]
        b_slots = [slot for slot in slots if slot["arm"] == "B"]
        target = run.PRIMARY_LANES[0]
        a_slots[0]["trial"]["lanes"] = [
            lane for lane in a_slots[0]["trial"]["lanes"] if lane["id"] != target
        ]
        with self.assertRaises(run.RunBlocked):
            run.block_ratios(a_slots, b_slots, run.PRIMARY_LANES[0])


if __name__ == "__main__":
    unittest.main()


class ScopeAllowlistTests(unittest.TestCase):
    """The final-campaign allowlist must name the authorized candidate paths and
    nothing more. `search/score.rs` is allowed **only** for the preapproved
    `#[cfg(test)]` invalid-df fixture (plan §5.6)."""

    def test_allowlist_is_exactly_the_authorized_production_paths(self):
        expected = {
            "crates/quervant-core/Cargo.toml",
            "crates/quervant-core/src/search/unified.rs",
            "crates/quervant-core/src/search/execute.rs",
            "crates/quervant-core/src/search/score.rs",
            "crates/quervant-core/src/search/diagnostics.rs",
            "crates/quervant-core/src/search/mod.rs",
            "crates/quervant-core/tests/pr15i_c_physical.rs",
            "crates/quervant-core/tests/pr15i_c_rustfs.rs",
            "docs/ROADMAP.md",
            "docs/ARCHITECTURE.md",
            "docs/BENCHMARKING.md",
            "docs/TESTING.md",
            "docs/ROADMAP_V01.md",
            ".github/workflows/ci.yml",
        }
        self.assertEqual(run.ALLOWED_EXACT, expected)
        self.assertIn("crates/quervant-core/src/search/score.rs", run.ALLOWED_EXACT)
        # Index/segment/storage/contract sources remain forbidden by prefix.
        for prefix in ("crates/quervant-core/src/segment/",
                       "crates/quervant-core/src/index/",
                       "crates/quervant-core/src/storage/",
                       "crates/quervant-core/src/contract/"):
            self.assertTrue(any(item == prefix for item in run.FORBIDDEN_PREFIXES))

    def test_protocol_numeric_limits_are_untouched(self):
        protocol = run.load_protocol(ROOT)
        self.assertEqual(protocol["primary_median_ratio_max"], 0.90)
        self.assertEqual(protocol["primary_each_block_ratio_max"], 1.15)
        self.assertEqual(protocol["nonprimary_median_ratio_max"], 1.05)
        self.assertEqual(protocol["nonprimary_each_block_ratio_max"], 1.15)
        self.assertEqual(protocol["warmups"], 5)
        self.assertEqual(protocol["samples_per_lane_slot"], 20)
        self.assertEqual(protocol["slot_schedule"], ["ABBA", "BAAB", "BAAB", "ABBA"])

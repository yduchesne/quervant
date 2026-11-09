#!/usr/bin/env python3
"""PR 15I-C follow-up — noise controller tests (predeclared protocol + arithmetic)."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


noise = load("pr15i_c_noise_diag", "noise_diag.py")


def synthetic_slots(a_median, b_median):
    slots = []
    index = 0
    for block, order in enumerate(noise.BLOCK_ORDERS, start=1):
        for position, letter in enumerate(order, start=1):
            index += 1
            value = a_median if letter == "A" else b_median
            lanes = []
            for lane_id in noise.LANE_IDS:
                samples = [value] * noise.MEASURED
                lanes.append({
                    "id": lane_id,
                    "samples_ns": samples,
                    "summary_ns": noise.base.pr15d_run.summarize(samples),
                })
            slots.append({"slot_index": index, "block": block, "position": position,
                          "arm": letter, "trial": {"lanes": lanes}})
    return slots


class ProtocolTests(unittest.TestCase):
    def test_predeclared_protocol_loads(self):
        protocol = noise.load_protocol(ROOT)
        self.assertEqual(protocol["schema"], "pr15i-c-noise-v1")
        self.assertEqual(protocol["baseline_source"], noise.BASELINE_SHA)
        self.assertEqual(protocol["generic_control_source"], noise.GENERIC_CONTROL_SHA)
        self.assertEqual(protocol["final_pr15ic_gate_unchanged"], True)

    def test_protocol_digest_is_stable(self):
        first = noise.protocol_digest(ROOT)
        second = noise.protocol_digest(ROOT)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_retuned_threshold_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, noise.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["AG_aggregate_median_max"] = 1.20
            with open(os.path.join(root, noise.PROTOCOL_REL), "w", encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(noise.RunBlocked):
                noise.load_protocol(root)

    def test_lane_or_schedule_drift_is_rejected(self):
        for mutation in ("lane_ids", "block_orders"):
            with tempfile.TemporaryDirectory() as directory:
                root = os.path.join(directory, "root")
                os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
                with open(os.path.join(ROOT, noise.PROTOCOL_REL), encoding="utf-8") as handle:
                    protocol = json.load(handle)
                if mutation == "lane_ids":
                    protocol["lane_ids"] = protocol["lane_ids"][:-1]
                else:
                    protocol["block_orders"][0] = "BAAB"
                with open(os.path.join(root, noise.PROTOCOL_REL), "w",
                          encoding="utf-8") as handle:
                    json.dump(protocol, handle)
                with self.assertRaises(noise.RunBlocked):
                    noise.load_protocol(root)

    def test_final_gate_flag_must_remain_true(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, noise.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["final_pr15ic_gate_unchanged"] = False
            with open(os.path.join(root, noise.PROTOCOL_REL), "w", encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(noise.RunBlocked):
                noise.load_protocol(root)


class CliAndPathTests(unittest.TestCase):
    def test_idle_confirmation_is_required(self):
        args = noise.build_parser().parse_args([
            "--checkout-root", ROOT, "--mode", "aa",
            "--baseline-sha", noise.BASELINE_SHA, "--control-sha", noise.BASELINE_SHA,
            "--out", os.path.join(ROOT, "target", "never-created"),
        ])
        self.assertEqual(noise.execute(args), 3)

    def test_relative_and_outside_paths_are_rejected(self):
        with self.assertRaises(noise.RunBlocked):
            noise.validate_out(ROOT, "target/pr15i-c/noise-diagnostics/aa-01")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(noise.RunBlocked):
                noise.validate_out(ROOT, os.path.join(directory, "aa-01"))

    def test_existing_output_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = os.path.join(directory, "target", "pr15i-c",
                                    "noise-diagnostics", "aa-01")
            os.makedirs(existing)
            with self.assertRaises(noise.RunBlocked):
                noise.validate_out(directory, existing)

    def test_fresh_output_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = os.path.join(directory, "target", "pr15i-c",
                                     "noise-diagnostics", "aa-01")
            self.assertEqual(noise.validate_out(directory, candidate),
                             os.path.realpath(candidate))


class SourceGuardTests(unittest.TestCase):
    def test_aa_requires_identical_source(self):
        proof = noise.verify_sources(ROOT, "aa", noise.BASELINE_SHA, noise.BASELINE_SHA)
        self.assertEqual(proof["baseline_body_sha256"], noise.EXPECTED_GENERIC_BODY_SHA)

    def test_aa_rejects_two_different_sources(self):
        with self.assertRaises(noise.RunBlocked):
            noise.verify_sources(ROOT, "aa", noise.BASELINE_SHA, noise.GENERIC_CONTROL_SHA)

    def test_aa_rejects_non_baseline_source(self):
        with self.assertRaises(noise.RunBlocked):
            noise.verify_sources(ROOT, "aa", noise.GENERIC_CONTROL_SHA,
                                 noise.GENERIC_CONTROL_SHA)

    def test_ag_requires_pinned_generic_control(self):
        proof = noise.verify_sources(ROOT, "ag", noise.BASELINE_SHA, noise.GENERIC_CONTROL_SHA)
        self.assertEqual(proof["baseline_body_sha256"], noise.EXPECTED_GENERIC_BODY_SHA)

    def test_ag_rejects_other_control_commits(self):
        with self.assertRaises(noise.RunBlocked):
            noise.verify_sources(ROOT, "ag", noise.BASELINE_SHA, noise.BASELINE_SHA)

    def test_unknown_commit_is_rejected(self):
        with self.assertRaises(noise.RunBlocked):
            noise.verify_sources(ROOT, "aa", "0" * 40, "0" * 40)


class ArithmeticTests(unittest.TestCase):
    def test_neutral_campaign_is_qualified(self):
        ratios = noise.campaign_ratios(synthetic_slots(1_000_000, 1_000_000))
        report = noise.derive(ratios, "aa", {"baseline_body_sha256": "x"})
        for lane_id in noise.LANE_IDS:
            self.assertAlmostEqual(report["campaign_medians"][lane_id], 1.0, places=12)
            self.assertEqual(ratios[lane_id]["outliers_above_1_15"], 0)
        self.assertEqual(report["decision"], "AA_CAMPAIGN_QUALIFIED")

    def test_median_of_eight_uses_middle_two(self):
        slots = synthetic_slots(1_000_000, 1_000_000)
        ramp = [0.90, 0.95, 1.00, 1.02, 1.04, 1.06, 1.08, 1.12]
        for block in range(1, noise.BLOCKS + 1):
            for record in slots:
                if record["block"] != block or record["arm"] != "B":
                    continue
                for lane in record["trial"]["lanes"]:
                    if lane["id"] != noise.LANE_IDS[0]:
                        continue
                    value = int(1_000_000 * ramp[block - 1])
                    lane["samples_ns"] = [value] * noise.MEASURED
                    lane["summary_ns"] = noise.base.pr15d_run.summarize(lane["samples_ns"])
        ratios = noise.campaign_ratios(slots)
        self.assertAlmostEqual(ratios[noise.LANE_IDS[0]]["campaign_median"],
                               (1.02 + 1.04) / 2, places=12)

    def test_outlier_counts_are_recorded_not_gating(self):
        slots = synthetic_slots(1_000_000, 1_000_000)
        for record in slots:
            if record["arm"] != "B" or record["block"] != 3:
                continue
            for lane in record["trial"]["lanes"]:
                if lane["id"] != noise.LANE_IDS[1]:
                    continue
                lane["samples_ns"] = [1_300_000] * noise.MEASURED
                lane["summary_ns"] = noise.base.pr15d_run.summarize(lane["samples_ns"])
        ratios = noise.campaign_ratios(slots)
        self.assertEqual(ratios[noise.LANE_IDS[1]]["outliers_above_1_15"], 1)
        report = noise.derive(ratios, "ag", {"baseline_body_sha256": "x"})
        # A single diagnostic block outlier is observed, not automatically fatal.
        self.assertEqual(report["decision"], "AG_CAMPAIGN_OBSERVED")
        self.assertEqual(report["per_block_observation_only"], 1.15)

    def test_below_inverse_outliers_are_counted(self):
        slots = synthetic_slots(1_000_000, 1_000_000)
        for record in slots:
            if record["arm"] != "B" or record["block"] != 5:
                continue
            for lane in record["trial"]["lanes"]:
                if lane["id"] != noise.LANE_IDS[2]:
                    continue
                lane["samples_ns"] = [500_000] * noise.MEASURED
                lane["summary_ns"] = noise.base.pr15d_run.summarize(lane["samples_ns"])
        ratios = noise.campaign_ratios(slots)
        self.assertEqual(ratios[noise.LANE_IDS[2]]["outliers_below_inverse_1_15"], 1)

    def test_missing_block_sample_is_rejected(self):
        slots = synthetic_slots(1_000_000, 900_000)
        slots[0]["trial"]["lanes"] = [
            lane for lane in slots[0]["trial"]["lanes"]
            if lane["id"] != noise.LANE_IDS[0]
        ]
        with self.assertRaises(noise.RunBlocked):
            noise.campaign_ratios(slots)

    def test_campaign_median_drift_marks_unstable(self):
        ratios = noise.campaign_ratios(synthetic_slots(1_000_000, 1_200_000))
        report = noise.derive(ratios, "aa", {"baseline_body_sha256": "x"})
        self.assertEqual(report["decision"], "AA_CAMPAIGN_UNSTABLE")


class ToolingReuseTests(unittest.TestCase):
    def test_reuses_existing_measurement_primitive(self):
        # The controller must not fork the canonical adapter/query executor.
        with open(os.path.join(HERE, "noise_diag.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("layout.measure_slot", source)
        self.assertIn("run.prepare_arm", source)
        self.assertIn("run.size_builds", source)
        self.assertNotIn("AdapterProcess(", source)

    def test_protocol_is_not_the_frozen_acceptance_contract(self):
        self.assertNotEqual(os.path.basename(noise.PROTOCOL_REL), "protocol.json")


if __name__ == "__main__":
    unittest.main()

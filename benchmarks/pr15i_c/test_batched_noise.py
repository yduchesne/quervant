#!/usr/bin/env python3
"""PR 15I-C — batched-noise controller tests (predeclared protocol + arithmetic)."""

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


noise = load("pr15i_c_batched_noise", "batched_noise.py")


def synthetic_slots(short_ratio=1.0, control_ratio=1.0, a_short=6_000_000):
    b_short = int(a_short * short_ratio)
    b_control = int(20_000_000 * control_ratio)
    slots = []
    index = 0
    for block, order in enumerate(noise.BLOCK_ORDERS, start=1):
        for position, letter in enumerate(order, start=1):
            index += 1
            lanes = []
            for lane_id in noise.LANE_IDS:
                repeat = noise.repeat_count_for(lane_id)
                value = (a_short if letter == "A" else b_short) \
                    if lane_id in noise.SHORT_LANE_IDS \
                    else (20_000_000 if letter == "A" else b_control)
                samples = [value] * noise.MEASURED_BATCHES
                summary = noise.base.pr15d_run.summarize(samples)
                lanes.append({
                    "id": lane_id,
                    "sample_unit": "batch",
                    "timing_basis": "outer_Rust_Instant_full_batch",
                    "repeat_count": repeat,
                    "batch_count": noise.MEASURED_BATCHES,
                    "warmup_count": noise.WARMUPS,
                    "raw_batch_ns": samples,
                    "summary_ns": summary,
                    "mean_per_query_ns": summary["median"] / repeat,
                    "search_count": noise.MEASURED_BATCHES * repeat + noise.WARMUPS,
                })
            slots.append({"slot_index": index, "block": block, "position": position,
                          "arm": letter, "trial": {"lanes": lanes}})
    return slots


class ProtocolTests(unittest.TestCase):
    def test_predeclared_protocol_loads(self):
        protocol = noise.load_protocol(ROOT)
        self.assertEqual(protocol["schema"], "pr15i-c-batched-noise-v1")
        self.assertEqual(protocol["baseline_source"], noise.BASELINE_SHA)
        self.assertEqual(protocol["frozen_adapter_main_rs_sha256"], noise.FROZEN_MAIN_SHA)
        self.assertEqual(protocol["sample_unit"], "batch")
        self.assertEqual(protocol["final_pr15ic_gate_unchanged"], True)

    def test_frozen_counts_match_the_plan(self):
        self.assertEqual(noise.MEASURED_BATCHES_PER_CAMPAIGN, 2240)
        self.assertEqual(noise.WARMUPS_PER_CAMPAIGN, 1120)
        self.assertEqual(noise.SEARCH_CALLS_PER_CAMPAIGN, 130080)
        self.assertEqual(noise.REPEAT_SHORT, 100)
        self.assertEqual(noise.REPEAT_CONTROL, 1)

    def test_retuned_repeat_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, noise.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["repeat_count_short"] = 200
            with open(os.path.join(root, noise.PROTOCOL_REL), "w", encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(noise.RunBlocked):
                noise.load_protocol(root)

    def test_retuned_gate_is_rejected(self):
        for key, value in (("AA_aggregate_median_min", 0.90),
                           ("AG_aggregate_median_max", 1.10),
                           ("short_lane_slot_median_floor_ns", 1),
                           ("sample_unit", "single_query")):
            with tempfile.TemporaryDirectory() as directory:
                root = os.path.join(directory, "root")
                os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
                with open(os.path.join(ROOT, noise.PROTOCOL_REL), encoding="utf-8") as handle:
                    protocol = json.load(handle)
                protocol[key] = value
                with open(os.path.join(root, noise.PROTOCOL_REL), "w",
                          encoding="utf-8") as handle:
                    json.dump(protocol, handle)
                with self.assertRaises(noise.RunBlocked):
                    noise.load_protocol(root)

    def test_lane_and_schedule_drift_are_rejected(self):
        for mutation in ("lane_ids", "short_lane_ids", "block_orders", "series_order"):
            with tempfile.TemporaryDirectory() as directory:
                root = os.path.join(directory, "root")
                os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
                with open(os.path.join(ROOT, noise.PROTOCOL_REL), encoding="utf-8") as handle:
                    protocol = json.load(handle)
                protocol[mutation] = protocol[mutation][:-1]
                with open(os.path.join(root, noise.PROTOCOL_REL), "w",
                          encoding="utf-8") as handle:
                    json.dump(protocol, handle)
                with self.assertRaises(noise.RunBlocked):
                    noise.load_protocol(root)

    def test_final_gate_flag_must_stay_true(self):
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
            noise.validate_out(ROOT, "target/pr15i-c/batched-noise-v1/aa-01")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(noise.RunBlocked):
                noise.validate_out(ROOT, os.path.join(directory, "aa-01"))

    def test_existing_output_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = os.path.join(directory, "target", "pr15i-c",
                                    "batched-noise-v1", "aa-01")
            os.makedirs(existing)
            with self.assertRaises(noise.RunBlocked):
                noise.validate_out(directory, existing)

    def test_fresh_output_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = os.path.join(directory, "target", "pr15i-c",
                                     "batched-noise-v1", "aa-01")
            self.assertEqual(noise.validate_out(directory, candidate),
                             os.path.realpath(candidate))


class SourceGuardTests(unittest.TestCase):
    def test_aa_requires_identical_baseline(self):
        proof = noise.verify_sources(ROOT, "aa", noise.BASELINE_SHA, noise.BASELINE_SHA)
        self.assertEqual(proof["frozen_main_sha256"], noise.FROZEN_MAIN_SHA)

    def test_aa_rejects_two_sources(self):
        with self.assertRaises(noise.RunBlocked):
            noise.verify_sources(ROOT, "aa", noise.BASELINE_SHA, noise.GENERIC_CONTROL_SHA)

    def test_ag_requires_pinned_control(self):
        noise.verify_sources(ROOT, "ag", noise.BASELINE_SHA, noise.GENERIC_CONTROL_SHA)

    def test_ag_rejects_other_control(self):
        with self.assertRaises(noise.RunBlocked):
            noise.verify_sources(ROOT, "ag", noise.BASELINE_SHA, noise.BASELINE_SHA)

    def test_unknown_commit_is_rejected(self):
        with self.assertRaises(noise.RunBlocked):
            noise.verify_sources(ROOT, "aa", "0" * 40, "0" * 40)


class AffinityTests(unittest.TestCase):
    def test_affinity_mode_is_predeclared_and_stable(self):
        first = noise.resolve_affinity()
        second = noise.resolve_affinity()
        self.assertEqual(first, second)
        self.assertIn(first["mode"], ("PINNED", "NO_AFFINITY"))
        if first["mode"] == "PINNED":
            self.assertNotEqual(first["adapter_cpu"], first["controller_cpu"])

    def test_adapter_command_prefixes_taskset_only_when_pinned(self):
        pinned = {"mode": "PINNED", "adapter_cpu": 3, "controller_cpu": 4}
        command = noise.adapter_command("/bin/adapter", "/tmp/idx", pinned)
        self.assertEqual(command[:4], ["taskset", "-c", "3", "/bin/adapter"])
        unpinned = {"mode": "NO_AFFINITY"}
        self.assertEqual(noise.adapter_command("/bin/adapter", "/tmp/idx", unpinned),
                         ["/bin/adapter", "--index-dir", "/tmp/idx"])

    def test_frequency_observation_is_read_only(self):
        observation = noise.frequency_observation()
        self.assertIn("governor", observation)
        self.assertIn("scaling_cur_freq_khz", observation)


class ArithmeticTests(unittest.TestCase):
    def test_neutral_campaign_is_qualified(self):
        ratios = noise.campaign_ratios(synthetic_slots())
        report = noise.derive(ratios, "aa", {"frozen_main_sha256": noise.FROZEN_MAIN_SHA})
        for lane_id in noise.LANE_IDS:
            self.assertAlmostEqual(report["campaign_medians"][lane_id], 1.0, places=12)
        self.assertEqual(report["decision"], "AA_CAMPAIGN_QUALIFIED")
        self.assertTrue(report["short_lane_duration_ok"])

    def test_median_of_eight_uses_middle_two(self):
        slots = synthetic_slots()
        ramp = [0.90, 0.95, 1.00, 1.02, 1.04, 1.06, 1.08, 1.12]
        for block in range(1, noise.BLOCKS + 1):
            for record in slots:
                if record["block"] != block or record["arm"] != "B":
                    continue
                for lane in record["trial"]["lanes"]:
                    if lane["id"] != noise.LANE_IDS[0]:
                        continue
                    value = int(6_000_000 * ramp[block - 1])
                    lane["raw_batch_ns"] = [value] * noise.MEASURED_BATCHES
                    lane["summary_ns"] = noise.base.pr15d_run.summarize(
                        lane["raw_batch_ns"])
        ratios = noise.campaign_ratios(slots)
        self.assertAlmostEqual(ratios[noise.LANE_IDS[0]]["campaign_median"],
                               (1.02 + 1.04) / 2, places=12)

    def test_short_lane_duration_floor_blocks(self):
        ratios = noise.campaign_ratios(synthetic_slots(a_short=500_000))
        report = noise.derive(ratios, "aa", {"frozen_main_sha256": noise.FROZEN_MAIN_SHA})
        self.assertFalse(report["short_lane_duration_ok"])
        self.assertEqual(report["decision"], "BATCH_DURATION_BLOCKED")

    def test_outlier_counts_are_recorded_not_gating(self):
        slots = synthetic_slots()
        for record in slots:
            if record["arm"] != "B" or record["block"] != 3:
                continue
            for lane in record["trial"]["lanes"]:
                if lane["id"] != noise.LANE_IDS[1]:
                    continue
                lane["raw_batch_ns"] = [9_000_000] * noise.MEASURED_BATCHES
                lane["summary_ns"] = noise.base.pr15d_run.summarize(lane["raw_batch_ns"])
        ratios = noise.campaign_ratios(slots)
        self.assertEqual(ratios[noise.LANE_IDS[1]]["outliers_above_1_15"], 1)
        report = noise.derive(ratios, "ag", {"frozen_main_sha256": noise.FROZEN_MAIN_SHA})
        self.assertEqual(report["decision"], "AG_CAMPAIGN_OBSERVED")
        self.assertEqual(report["per_block_observation_only"], 1.15)

    def test_missing_block_sample_is_rejected(self):
        slots = synthetic_slots()
        slots[0]["trial"]["lanes"] = [
            lane for lane in slots[0]["trial"]["lanes"]
            if lane["id"] != noise.LANE_IDS[0]
        ]
        with self.assertRaises(noise.RunBlocked):
            noise.campaign_ratios(slots)

    def test_repeat_count_assignment(self):
        for lane_id in noise.SHORT_LANE_IDS:
            self.assertEqual(noise.repeat_count_for(lane_id), 100)
        for lane_id in (noise.LANE_IDS[2], noise.LANE_IDS[5], noise.LANE_IDS[6]):
            self.assertEqual(noise.repeat_count_for(lane_id), 1)


class ReuseTests(unittest.TestCase):
    def test_reuses_existing_harness_helpers(self):
        with open(os.path.join(HERE, "batched_noise.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("run.size_builds", source)
        self.assertIn("run._worktree", source)
        self.assertIn("patcher.prepare_derived_adapter", source)
        self.assertNotIn("layout.measure_lane_diagnostic", source)
        self.assertNotIn("layout.measure_slot(", source)

    def test_no_python_side_batch_timing(self):
        with open(os.path.join(HERE, "batched_noise.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"op": "query_batch"', source)
        self.assertNotIn("sum(", source.split("def campaign_ratios")[0].split(
            "def measure_lane_batch")[1] if "def measure_lane_batch" in source else "")


if __name__ == "__main__":
    unittest.main()

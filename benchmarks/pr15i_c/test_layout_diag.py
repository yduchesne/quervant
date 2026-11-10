#!/usr/bin/env python3
"""PR 15I-C fixup — generic-boundary diagnostic controller tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load():
    spec = importlib.util.spec_from_file_location(
        "pr15i_c_layout_diag", os.path.join(HERE, "layout_diag.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diag = load()

SYNTHETIC_SOURCE = """\
impl Searcher {
    fn helper(&self) -> u64 {
        1
    }

    #[allow(clippy::needless_option_as_deref)]
    fn collect_mixed(&self) -> u64 {
        let mut total = 0u64;
        total += self.helper();
        total
    }
}
"""

CONTROL_SOURCE = SYNTHETIC_SOURCE.replace(
    "    #[allow(clippy::needless_option_as_deref)]\n    fn collect_mixed",
    "    #[inline(never)]\n    #[allow(clippy::needless_option_as_deref)]\n    fn collect_mixed",
)

CHANGED_BODY_SOURCE = SYNTHETIC_SOURCE.replace("total += self.helper();",
                                               "total += self.helper() + 1;")

DOUBLE_INLINE_SOURCE = SYNTHETIC_SOURCE.replace(
    "    #[allow(clippy::needless_option_as_deref)]\n    fn collect_mixed",
    "    #[inline(never)]\n    #[inline(always)]\n"
    "    #[allow(clippy::needless_option_as_deref)]\n    fn collect_mixed",
)

# Same body, but the file content differs so a real commit exists.
NO_ATTRIBUTE_CONTROL = SYNTHETIC_SOURCE + "\n// no layout annotation here\n"


def write_repo(directory, baseline, candidate):
    os.makedirs(os.path.join(directory, "crates", "quervant-core", "src", "search"))
    path = os.path.join(directory, diag.UNIFIED_REL)
    git = ["git", "-C", directory]

    def commit(text, message):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        subprocess.run([*git, "add", "-A"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "-m", message], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return subprocess.run([*git, "rev-parse", "HEAD"], stdout=subprocess.PIPE,
                              text=True, check=True).stdout.strip()

    subprocess.run([*git, "init", "-q"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    baseline_sha = commit(baseline, "baseline")
    candidate_sha = commit(candidate, "candidate")
    return baseline_sha, candidate_sha


class ControlSourceTests(unittest.TestCase):
    def test_single_annotation_with_identical_body_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            a, g = write_repo(directory, SYNTHETIC_SOURCE, CONTROL_SOURCE)
            proof = diag.verify_control_source(directory, a, g)
            self.assertEqual(proof["baseline_body_sha256"], proof["candidate_body_sha256"])
            self.assertIn("#[inline(never)]", proof["attributes"])
            self.assertEqual(proof["changed_paths"], [diag.UNIFIED_REL])

    def test_changed_generic_body_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            a, g = write_repo(directory, SYNTHETIC_SOURCE, CHANGED_BODY_SOURCE)
            with self.assertRaises(diag.RunBlocked):
                diag.verify_control_source(directory, a, g)

    def test_missing_inline_never_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            a, g = write_repo(directory, SYNTHETIC_SOURCE, NO_ATTRIBUTE_CONTROL)
            with self.assertRaises(diag.RunBlocked):
                diag.verify_control_source(directory, a, g)

    def test_two_inline_attributes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            a, g = write_repo(directory, SYNTHETIC_SOURCE, DOUBLE_INLINE_SOURCE)
            with self.assertRaises(diag.RunBlocked):
                diag.verify_control_source(directory, a, g)


class CliGuardTests(unittest.TestCase):
    def test_idle_confirmation_is_required(self):
        args = diag.build_parser().parse_args([
            "--checkout-root", ROOT, "--baseline-sha", "a" * 40,
            "--candidate-sha", "b" * 40,
            "--out", os.path.join(ROOT, "target", "never-created"),
        ])
        self.assertEqual(diag.execute(args), 3)

    def test_relative_out_is_rejected(self):
        with self.assertRaises(diag.RunBlocked):
            diag.validate_out(ROOT, "target/pr15i-c/layout-diagnostics/x")

    def test_outside_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(diag.RunBlocked):
                diag.validate_out(ROOT, os.path.join(directory, "x"))

    def test_existing_out_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = os.path.join(directory, "target", "pr15i-c",
                                    "layout-diagnostics", "generic-boundary-01")
            os.makedirs(existing)
            with self.assertRaises(diag.RunBlocked):
                diag.validate_out(directory, existing)

    def test_fresh_out_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = os.path.join(directory, "target", "pr15i-c",
                                     "layout-diagnostics", "generic-boundary-01")
            self.assertEqual(diag.validate_out(directory, candidate),
                             os.path.realpath(candidate))


class ScheduleTests(unittest.TestCase):
    def test_frozen_constants(self):
        self.assertEqual(diag.SLOTS, 32)
        self.assertEqual(diag.BLOCKS, 8)
        self.assertEqual(len(diag.LANE_IDS), 7)
        self.assertEqual(len(diag.BLOCK_ORDERS), 8)
        self.assertEqual(diag.WARMUPS, 5)
        self.assertEqual(diag.MEASURED, 10)
        self.assertEqual(diag.RATIO_MEDIAN_MAX, 1.05)
        self.assertEqual(diag.RATIO_BLOCK_MAX, 1.15)
        for order in diag.BLOCK_ORDERS:
            self.assertEqual(order.count("A"), 2)
            self.assertEqual(order.count("B"), 2)

    def test_lane_subset_is_part_of_frozen_pr15d_lanes(self):
        lanes = {lane["id"] for lane in diag.base.stage_lanes("final")}
        for lane_id in diag.LANE_IDS:
            self.assertIn(lane_id, lanes)


def synthetic_slots(a_median, b_median):
    slots = []
    index = 0
    for block, order in enumerate(diag.BLOCK_ORDERS, start=1):
        for position, arm in enumerate(order, start=1):
            index += 1
            value = a_median if arm == "A" else b_median
            lanes = []
            for lane_id in diag.LANE_IDS:
                samples = [value] * diag.MEASURED
                lanes.append({
                    "id": lane_id,
                    "samples_ns": samples,
                    "summary_ns": diag.base.pr15d_run.summarize(samples),
                })
            slots.append({"slot_index": index, "block": block, "position": position,
                          "arm": arm, "trial": {"lanes": lanes}})
    return slots


class DerivationTests(unittest.TestCase):
    def test_neutral_control_passes(self):
        report = diag.derive(synthetic_slots(1_000_000, 1_000_000),
                             {"candidate_body_sha256": "x", "baseline_body_sha256": "x"})
        self.assertTrue(report["qualified"])
        self.assertEqual(report["decision"], "GENERIC_BOUNDARY_CONTROL_PASS")
        for lane_id in diag.LANE_IDS:
            self.assertAlmostEqual(report["medians"][lane_id], 1.0, places=12)

    def test_eight_block_median_uses_middle_two(self):
        slots = synthetic_slots(1_000_000, 1_000_000)
        # Overwrite the medians of one lane per block to a known ramp.
        ramp = [1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12, 1.14]
        for block in range(1, diag.BLOCKS + 1):
            for record in slots:
                if record["block"] != block or record["arm"] != "B":
                    continue
                for lane in record["trial"]["lanes"]:
                    if lane["id"] != diag.LANE_IDS[0]:
                        continue
                    value = int(1_000_000 * ramp[block - 1])
                    lane["samples_ns"] = [value] * diag.MEASURED
                    lane["summary_ns"] = diag.base.pr15d_run.summarize(lane["samples_ns"])
        report = diag.derive(slots, {"candidate_body_sha256": "x",
                                     "baseline_body_sha256": "x"})
        self.assertAlmostEqual(report["medians"][diag.LANE_IDS[0]], (1.06 + 1.08) / 2,
                               places=12)
        self.assertEqual(report["gates"][diag.LANE_IDS[0]], "FAIL")

    def test_missing_block_sample_is_rejected(self):
        slots = synthetic_slots(1_000_000, 900_000)
        slots[0]["trial"]["lanes"] = [
            lane for lane in slots[0]["trial"]["lanes"]
            if lane["id"] != diag.LANE_IDS[0]
        ]
        with self.assertRaises(diag.RunBlocked):
            diag.derive(slots, {"candidate_body_sha256": "x",
                                "baseline_body_sha256": "x"})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""PR 15I-C follow-up — adversarial tests for the noise verifier (N-V*)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load("pr15i_c_verify_noise", "verify_noise_diag.py")

SYNTHETIC_SOURCE = """\
impl Searcher {
    fn collect_mixed(&self) -> u64 {
        let mut total = 0u64;
        total
    }
}
"""

CONTROL_SOURCE = SYNTHETIC_SOURCE.replace(
    "    fn collect_mixed",
    "    #[inline(never)]\n    fn collect_mixed",
)


def synthetic_slots(a_median, b_median):
    slots = []
    index = 0
    for block, order in enumerate(verify.BLOCK_ORDERS, start=1):
        for position, letter in enumerate(order, start=1):
            index += 1
            value = a_median if letter == "A" else b_median
            lanes = []
            for lane_id in verify.LANE_IDS:
                samples = [value] * verify.MEASURED
                lanes.append({
                    "id": lane_id,
                    "samples_ns": samples,
                    "summary_ns": verify.base.pr15d_run.summarize(samples),
                    "warmups": verify.WARMUPS,
                    "warmup_ids": [f"w{position}" for _ in range(verify.WARMUPS)],
                    "oracle_ok": True,
                    "total_hits": 1,
                    "doc_ids": [],
                })
            slots.append({
                "slot_index": index,
                "block": block,
                "position": position,
                "arm": letter,
                "executed_binary_path": "/tmp/shared-adapter",
                "binary_sha256": "0" * 64,
                "trial": {
                    "lanes": lanes,
                    "contention_before": {"state": "clear"},
                    "contention_after": {"state": "clear"},
                },
            })
    return slots


def uniform_slots(ratio):
    return synthetic_slots(1_000_000, int(1_000_000 * ratio))


class SlotTopologyTests(unittest.TestCase):
    def test_complete_matrix_is_accepted(self):
        measured, warmed = verify.validate_slot_matrix(uniform_slots(1.0))
        self.assertEqual(measured, 2240)
        self.assertEqual(warmed, 1120)

    def test_missing_slot_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(uniform_slots(1.0)[:-1])

    def test_duplicate_slot_index_is_rejected(self):
        slots = uniform_slots(1.0)
        slots[1]["slot_index"] = slots[0]["slot_index"]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_wrong_block_order_is_rejected(self):
        slots = uniform_slots(1.0)
        slots[0]["arm"], slots[1]["arm"] = slots[1]["arm"], slots[0]["arm"]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_missing_lane_is_rejected(self):
        slots = uniform_slots(1.0)
        for record in slots:
            record["trial"]["lanes"] = [
                lane for lane in record["trial"]["lanes"]
                if lane["id"] != verify.LANE_IDS[0]
            ]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_wrong_sample_counts_are_rejected(self):
        for count in (9, 11):
            slots = uniform_slots(1.0)
            lane = slots[0]["trial"]["lanes"][0]
            lane["samples_ns"] = [1_000_000] * count
            lane["summary_ns"] = verify.base.pr15d_run.summarize(lane["samples_ns"])
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)

    def test_wrong_warmup_counts_are_rejected(self):
        for count in (4, 6):
            slots = uniform_slots(1.0)
            slots[0]["trial"]["lanes"][0]["warmups"] = count
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)

    def test_unclear_contention_is_rejected(self):
        slots = uniform_slots(1.0)
        slots[7]["trial"]["contention_before"] = {"state": "busy"}
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_forged_summary_is_rejected(self):
        slots = uniform_slots(1.0)
        slots[0]["trial"]["lanes"][0]["summary_ns"]["median"] = 1
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_invalid_sample_values_are_rejected(self):
        for bad in (True, 0, -1, 1.5, float("nan")):
            slots = uniform_slots(1.0)
            slots[0]["trial"]["lanes"][0]["samples_ns"] = [bad] * verify.MEASURED
            slots[0]["trial"]["lanes"][0]["summary_ns"] = {
                "count": verify.MEASURED, "median": 1, "p95": 1, "p99": 1,
                "min": 1, "max": 1,
            }
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)


class RatioTests(unittest.TestCase):
    def test_neutral_ratios_and_medians(self):
        ratios = verify.recompute_ratios(uniform_slots(1.0))
        for lane_id in verify.LANE_IDS:
            self.assertAlmostEqual(ratios[lane_id]["campaign_median"], 1.0, places=12)
            self.assertEqual(len(ratios[lane_id]["block_ratios"]), 8)

    def test_missing_block_samples_are_rejected(self):
        slots = uniform_slots(1.0)
        slots[0]["trial"]["lanes"] = [
            lane for lane in slots[0]["trial"]["lanes"]
            if lane["id"] != verify.LANE_IDS[0]
        ]
        with self.assertRaises(verify.VerificationFailed):
            verify.recompute_ratios(slots)

    def test_controller_disagreement_is_rejected(self):
        ratios = verify.recompute_ratios(uniform_slots(1.0))
        forged = {
            "ratios": {
                lane: {"block_ratios": value["block_ratios"],
                       "campaign_median": value["campaign_median"],
                       "outliers_above_1_15": value["outliers_above_1_15"]}
                for lane, value in ratios.items()
            },
            "campaign_medians": {lane: value["campaign_median"]
                                 for lane, value in ratios.items()},
        }
        forged["ratios"][verify.LANE_IDS[0]]["campaign_median"] = 0.5
        with self.assertRaises(verify.VerificationFailed):
            verify.compare_with_controller(ratios, forged)

    def test_consistent_controller_is_accepted(self):
        ratios = verify.recompute_ratios(uniform_slots(0.9))
        consistent = {
            "ratios": {
                lane: {"block_ratios": value["block_ratios"],
                       "campaign_median": value["campaign_median"],
                       "outliers_above_1_15": value["outliers_above_1_15"]}
                for lane, value in ratios.items()
            },
            "campaign_medians": {lane: value["campaign_median"]
                                 for lane, value in ratios.items()},
        }
        reported = verify.compare_with_controller(ratios, consistent)
        self.assertEqual(reported, consistent["ratios"])


class SeriesCriteriaTests(unittest.TestCase):
    def series(self, aa_values, ag_values):
        aa = {f"aa-0{index + 1}": {lane: aa_values[index] for lane in verify.LANE_IDS}
              for index in range(4)}
        ag = {f"ag-0{index + 1}": {lane: ag_values[index] for lane in verify.LANE_IDS}
              for index in range(4)}
        return verify.evaluate_series(aa, ag)

    def test_neutral_series_passes(self):
        _, _, aa_pass, ag_pass, decision = self.series([1.0] * 4, [1.0] * 4)
        self.assertTrue(aa_pass)
        self.assertTrue(ag_pass)
        self.assertEqual(decision, "15IC_LAYOUT_COMPATIBLE_DIAGNOSTIC")

    def test_aa_boundaries_are_inclusive(self):
        _, _, aa_pass, _, _ = self.series([0.90, 1.10, 0.95, 1.05], [1.0] * 4)
        self.assertTrue(aa_pass)

    def test_aa_aggregate_outside_band_blocks(self):
        _, _, aa_pass, ag_pass, decision = self.series([1.09, 1.09, 1.09, 1.09], [1.0] * 4)
        self.assertFalse(aa_pass)
        self.assertFalse(ag_pass)
        self.assertEqual(decision, "15IC_NOISE_DIAGNOSTIC_BLOCKED")

    def test_aa_single_campaign_outside_band_blocks(self):
        _, _, aa_pass, _, _ = self.series([1.0, 1.0, 1.0, 1.11], [1.0] * 4)
        self.assertFalse(aa_pass)

    def test_ag_aggregate_above_ceiling_rejects(self):
        _, _, _, ag_pass, decision = self.series([1.0] * 4, [1.06] * 4)
        self.assertFalse(ag_pass)
        self.assertEqual(decision, "15IC_LAYOUT_DIAGNOSTIC_REJECTED_NO_NEW_IMPLEMENTATION")

    def test_ag_requires_three_runs_at_or_below(self):
        _, _, _, ag_pass, _ = self.series([1.0] * 4, [1.05, 1.05, 1.06, 1.06])
        self.assertFalse(ag_pass)

    def test_ag_single_block_outlier_style_single_campaign_drift_rejects(self):
        _, _, _, ag_pass, _ = self.series([1.0] * 4, [1.0, 1.0, 1.0, 1.11])
        self.assertFalse(ag_pass)

    def test_series_size_is_enforced(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.evaluate_series(
                {"aa-01": {lane: 1.0 for lane in verify.LANE_IDS}},
                {f"ag-0{index}": {lane: 1.0 for lane in verify.LANE_IDS}
                 for index in range(1, 5)})


class InventoryTests(unittest.TestCase):
    def make_raw(self, directory):
        raw = os.path.join(directory, "raw")
        os.makedirs(raw)
        for relative in verify.REQUIRED_RAW:
            path = os.path.join(raw, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"schema": "synthetic"}, handle)
        seal = {
            "schema": verify.SEAL_SCHEMA,
            "files": {relative: verify.sha256_file(os.path.join(raw, relative))
                      for relative in verify.REQUIRED_RAW},
        }
        with open(os.path.join(raw, "seal.json"), "w", encoding="utf-8") as handle:
            json.dump(seal, handle)
        return raw

    def test_extra_raw_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            with open(os.path.join(raw, "extra.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.inventory(directory)

    def test_complete_inventory_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_raw(directory)
            self.assertEqual(len(verify.inventory(directory)),
                             len(verify.REQUIRED_RAW) + 1)

    def test_missing_seal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            os.remove(os.path.join(raw, "seal.json"))
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_seal(directory)

    def test_tamper_without_reseal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            with open(os.path.join(raw, "measurements.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({"schema": "tampered"}, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_seal(directory)

    def test_symlinked_slot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            target = os.path.join(directory, "outside.json")
            with open(target, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            link = os.path.join(raw, "slots", "slot-99.json")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(verify.VerificationFailed):
                verify.inventory(directory)

    def test_receipt_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            reviews = os.path.join(directory, "target", "pr15i-c")
            os.makedirs(reviews)
            first = verify.write_receipt(directory, "noise-v2-aa-01.json", {"schema": "x"})
            self.assertTrue(os.path.isfile(first))
            with self.assertRaises(verify.VerificationFailed):
                verify.write_receipt(directory, "noise-v2-aa-01.json", {"schema": "y"})


class ExecutableIdentityTests(unittest.TestCase):
    def make_campaign(self, mode, a_path, b_path, a_digest, b_digest):
        directory = tempfile.mkdtemp()
        raw = os.path.join(directory, "raw")
        os.makedirs(raw)
        with open(os.path.join(raw, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({
                "schema": verify.SCHEMA,
                "mode": mode,
                "identical_executable": mode == "aa",
                "executed_binary": {
                    "A": {"path": a_path, "sha256": a_digest},
                    "B": {"path": b_path, "sha256": b_digest},
                },
            }, handle)
        with open(os.path.join(raw, "toolchain.json"), "w", encoding="utf-8") as handle:
            json.dump({
                "schema": verify.SCHEMA,
                "executed_binary_sha256": {
                    "A": {"path": a_path, "sha256": a_digest},
                    "B": {"path": b_path, "sha256": b_digest},
                },
            }, handle)
        return directory

    def test_aa_same_path_and_bytes_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = os.path.join(directory, "adapter")
            with open(binary, "wb") as handle:
                handle.write(b"\x7fELF-shared")
            digest = verify.sha256_file(binary)
            campaign = self.make_campaign("aa", binary, binary, digest, digest)
            executed = verify.verify_executables(campaign, verify.read_json(
                os.path.join(campaign, "raw", "manifest.json")), "aa")
            self.assertEqual(executed["A"]["path"], executed["B"]["path"])

    def test_aa_two_different_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "one")
            second = os.path.join(directory, "two")
            for path in (first, second):
                with open(path, "wb") as handle:
                    handle.write(b"\x7fELF-identical-bytes")
            digest = verify.sha256_file(first)
            campaign = self.make_campaign("aa", first, second, digest, digest)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_executables(campaign, verify.read_json(
                    os.path.join(campaign, "raw", "manifest.json")), "aa")

    def test_aa_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = os.path.join(directory, "adapter")
            with open(binary, "wb") as handle:
                handle.write(b"\x7fELF-shared")
            digest = verify.sha256_file(binary)
            campaign = self.make_campaign("aa", binary, binary, digest, "f" * 64)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_executables(campaign, verify.read_json(
                    os.path.join(campaign, "raw", "manifest.json")), "aa")

    def test_missing_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = os.path.join(directory, "adapter")
            with open(binary, "wb") as handle:
                handle.write(b"\x7fELF")
            digest = verify.sha256_file(binary)
            campaign = self.make_campaign("aa", binary, binary, digest, digest)
            os.remove(binary)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_executables(campaign, verify.read_json(
                    os.path.join(campaign, "raw", "manifest.json")), "aa")


class SourceSeriesTests(unittest.TestCase):
    def test_aa_source_must_match(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_source(ROOT, {"A_sha": verify.BASELINE_SHA,
                                        "B_sha": verify.GENERIC_CONTROL_SHA,
                                        "generic_body_sha256":
                                            verify.EXPECTED_GENERIC_BODY_SHA}, "aa")

    def test_ag_source_requires_pinned_control(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_source(ROOT, {"A_sha": verify.BASELINE_SHA,
                                        "B_sha": verify.BASELINE_SHA,
                                        "generic_body_sha256":
                                            verify.EXPECTED_GENERIC_BODY_SHA}, "ag")

    def test_unknown_commit_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_source(ROOT, {"A_sha": "0" * 40, "B_sha": "0" * 40,
                                        "generic_body_sha256": "x"}, "aa")

    def test_series_identity_is_fixed(self):
        self.assertEqual([campaign for campaign, _ in verify.SERIES],
                         ["aa-01", "ag-01", "aa-02", "ag-02",
                          "aa-03", "ag-03", "aa-04", "ag-04"])

    def test_verifier_never_claims_feature_acceptance(self):
        with open(os.path.join(HERE, "verify_noise_diag.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"diagnostic_only": True', source)
        self.assertIn('"final_feature_acceptance": False', source)
        self.assertIn("OBSERVATION_ONLY", source)


if __name__ == "__main__":
    unittest.main()

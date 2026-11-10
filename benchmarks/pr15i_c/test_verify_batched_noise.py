#!/usr/bin/env python3
"""PR 15I-C — adversarial tests for the batched-noise verifier (B-V matrix).

Every test builds a synthetic fixture in a temporary directory; no real sealed
campaign is ever touched. Structural/contract helpers use hand-built raw trees;
the numerical helpers use synthetic slot records with real integer batch times.
"""

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


verify = load("pr15i_c_verify_batched", "verify_batched_noise.py")

MEDIAN_A = 6_000_000     # 100-rep short-lane batch, ~60us/query
MEDIAN_CONTROL = 20_000_000


def synthetic_slots(short_ratio=1.0, control_ratio=1.0, a_short=MEDIAN_A,
                    b_short=None, a_control=MEDIAN_CONTROL, b_control=None):
    b_short = b_short if b_short is not None else int(a_short * short_ratio)
    b_control = b_control if b_control is not None else int(a_control * control_ratio)
    slots = []
    index = 0
    for block, order in enumerate(verify.BLOCK_ORDERS, start=1):
        for position, letter in enumerate(order, start=1):
            index += 1
            lanes = []
            for lane_id in verify.LANE_IDS:
                repeat = verify.repeat_count_for(lane_id)
                value = (a_short if letter == "A" else b_short) \
                    if lane_id in verify.SHORT_LANE_IDS else \
                    (a_control if letter == "A" else b_control)
                samples = [value] * verify.MEASURED_BATCHES
                summary = verify.base.pr15d_run.summarize(samples)
                lanes.append({
                    "id": lane_id,
                    "sample_unit": "batch",
                    "timing_basis": "outer_Rust_Instant_full_batch",
                    "repeat_count": repeat,
                    "batch_count": verify.MEASURED_BATCHES,
                    "warmup_count": verify.WARMUPS,
                    "warmup_ids": [f"w{position}" for _ in range(verify.WARMUPS)],
                    "raw_batch_ns": samples,
                    "summary_ns": summary,
                    "mean_per_query_ns": summary["median"] / repeat,
                    "search_count": verify.MEASURED_BATCHES * repeat + verify.WARMUPS,
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


def lane_of(slots, slot_index, lane_id):
    for record in slots:
        if record["slot_index"] == slot_index:
            for lane in record["trial"]["lanes"]:
                if lane["id"] == lane_id:
                    return lane
    raise AssertionError("lane not found")


class SlotTopologyTests(unittest.TestCase):
    def test_bv01_missing_slot_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(synthetic_slots()[:-1], "aa")

    def test_bv02_extra_slot_is_rejected(self):
        slots = synthetic_slots()
        slots.append(dict(slots[-1], slot_index=33))
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots, "aa")

    def test_bv03_duplicate_slot_index_is_rejected(self):
        slots = synthetic_slots()
        slots[1]["slot_index"] = slots[0]["slot_index"]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots, "aa")

    def test_bv04_wrong_schedule_position_is_rejected(self):
        slots = synthetic_slots()
        slots[0]["arm"], slots[1]["arm"] = slots[1]["arm"], slots[0]["arm"]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots, "aa")

    def test_complete_matrix_counts(self):
        batches, warmups, searches = verify.validate_slot_matrix(synthetic_slots(), "aa")
        self.assertEqual(batches, verify.MEASURED_BATCHES_PER_CAMPAIGN)
        self.assertEqual(warmups, verify.WARMUPS_PER_CAMPAIGN)
        self.assertEqual(searches, verify.SEARCH_CALLS_PER_CAMPAIGN)

    def test_bv16_wrong_repeat_count_is_rejected(self):
        for repeat in (1, 10, 200):
            slots = synthetic_slots()
            lane = lane_of(slots, 1, verify.SHORT_LANE_IDS[0])
            lane["repeat_count"] = repeat
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots, "aa")

    def test_bv17_wrong_warmup_count_is_rejected(self):
        for count in (4, 6, 0):
            slots = synthetic_slots()
            lane_of(slots, 1, verify.LANE_IDS[0])["warmup_count"] = count
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots, "aa")

    def test_bv18_wrong_sample_count_is_rejected(self):
        for count in (9, 11):
            slots = synthetic_slots()
            lane = lane_of(slots, 1, verify.LANE_IDS[0])
            lane["raw_batch_ns"] = [MEDIAN_A] * count
            lane["summary_ns"] = verify.base.pr15d_run.summarize(lane["raw_batch_ns"])
            lane["mean_per_query_ns"] = lane["summary_ns"]["median"] / lane["repeat_count"]
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots, "aa")

    def test_bv19_zero_or_negative_batch_ns_is_rejected(self):
        for bad in (0, -1, True, 1.5):
            slots = synthetic_slots()
            lane = lane_of(slots, 1, verify.LANE_IDS[0])
            lane["raw_batch_ns"] = [bad] * verify.MEASURED_BATCHES
            lane["summary_ns"] = {"count": verify.MEASURED_BATCHES, "median": 1,
                                  "p95": 1, "p99": 1, "min": 1, "max": 1}
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots, "aa")

    def test_bv20_forged_mean_per_query_ns_is_rejected(self):
        slots = synthetic_slots()
        lane_of(slots, 1, verify.LANE_IDS[0])["mean_per_query_ns"] = 1.0
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots, "aa")

    def test_bv21_engine_ns_in_batch_lane_record_is_rejected(self):
        # The controller records the validated batch reply; a reply carrying
        # engine_ns must never reach the record. Simulate the controller-side
        # rejection directly.
        from_batched = load("pr15i_c_batched_noise_under_test",
                            "batched_noise.py")
        expected = {"total_hits": 1, "doc_ids": []}
        lane = {"id": verify.SHORT_LANE_IDS[0]}
        with self.assertRaises(Exception):
            from_batched.validate_batch_response(
                {"request_id": "x", "schema": "pr15d-adapter-v1", "engine": "quervant",
                 "status": "ok", "repeat_count": 100, "batch_ns": 1000,
                 "engine_ns": 10, "total_hits": 1, "doc_ids": []},
                lane, expected, 100, "x")

    def test_bv22_mixed_single_and_batch_units_are_rejected(self):
        for mutation in ("sample_unit", "timing_basis", "search_count"):
            slots = synthetic_slots()
            lane = lane_of(slots, 1, verify.LANE_IDS[0])
            if mutation == "sample_unit":
                lane["sample_unit"] = "single_query"
            elif mutation == "timing_basis":
                lane["timing_basis"] = "per_query_engine_ns_sum"
            else:
                lane["search_count"] = verify.MEASURED_BATCHES
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots, "aa")

    def test_bv25_false_contention_claim_is_rejected(self):
        slots = synthetic_slots()
        slots[4]["trial"]["contention_after"] = {"state": "busy"}
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots, "aa")

    def test_bv06_aa_slots_must_share_one_binary(self):
        slots = synthetic_slots()
        slots[0]["executed_binary_path"] = "/tmp/other-adapter"
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots, "aa")


class RatioTests(unittest.TestCase):
    def test_neutral_ratios(self):
        ratios = verify.recompute_ratios(synthetic_slots())
        for lane_id in verify.LANE_IDS:
            self.assertAlmostEqual(ratios[lane_id]["campaign_median"], 1.0, places=12)
            self.assertEqual(len(ratios[lane_id]["block_ratios"]), verify.BLOCKS)

    def test_bv37_short_lane_duration_floor_is_enforced(self):
        ratios = verify.recompute_ratios(synthetic_slots(a_short=500_000))
        self.assertFalse(ratios[verify.SHORT_LANE_IDS[0]]["short_lane_duration_ok"])
        self.assertTrue(ratios[verify.LANE_IDS[2]]["short_lane_duration_ok"])

    def test_bv13_missing_block_lane_is_rejected(self):
        slots = synthetic_slots()
        slots[0]["trial"]["lanes"] = [
            lane for lane in slots[0]["trial"]["lanes"]
            if lane["id"] != verify.LANE_IDS[0]
        ]
        with self.assertRaises(verify.VerificationFailed):
            verify.recompute_ratios(slots)

    def test_bv30_controller_disagreement_is_rejected(self):
        ratios = verify.recompute_ratios(synthetic_slots())
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
        ratios = verify.recompute_ratios(synthetic_slots(short_ratio=0.95))
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
        self.assertEqual(verify.compare_with_controller(ratios, consistent),
                         consistent["ratios"])

    def test_bv40_expected_counts_are_fixed(self):
        self.assertEqual(verify.MEASURED_BATCHES_PER_CAMPAIGN, 2240)
        self.assertEqual(verify.WARMUPS_PER_CAMPAIGN, 1120)
        self.assertEqual(verify.SEARCH_CALLS_PER_CAMPAIGN, 130080)
        self.assertEqual(len(verify.SERIES), 8)
        self.assertEqual(sum(verify.MEASURED_BATCHES_PER_CAMPAIGN for _ in verify.SERIES),
                         17920)


class SeriesCriteriaTests(unittest.TestCase):
    def series(self, aa_values, ag_values):
        aa = {f"aa-0{index + 1}": {lane: aa_values[index] for lane in verify.LANE_IDS}
              for index in range(4)}
        ag = {f"ag-0{index + 1}": {lane: ag_values[index] for lane in verify.LANE_IDS}
              for index in range(4)}
        return verify.evaluate_series(aa, ag)

    def test_neutral_series_passes(self):
        aa, ag, aa_pass, ag_pass, decision = self.series([1.0] * 4, [1.0] * 4)
        self.assertTrue(aa_pass)
        self.assertTrue(ag_pass)
        self.assertEqual(decision, "15IC_AG_DIAGNOSTIC_NEUTRAL")
        self.assertAlmostEqual(aa[verify.LANE_IDS[0]]["aggregate_median"], 1.0, places=12)

    def test_bv38_aa_boundaries_are_inclusive(self):
        _, _, aa_pass, _, _ = self.series([0.94, 1.06, 0.94, 1.06], [1.0] * 4)
        self.assertTrue(aa_pass)
        _, _, aa_pass, _, _ = self.series([0.94, 0.94, 0.94, 0.94], [1.0] * 4)
        self.assertFalse(aa_pass)  # aggregate 0.94 outside [0.97, 1.03]

    def test_aa_aggregate_band_is_enforced(self):
        _, _, aa_pass, _, decision = self.series([1.04] * 4, [1.0] * 4)
        self.assertFalse(aa_pass)
        self.assertEqual(decision, "15IC_BATCHED_NOISE_BLOCKED")

    def test_aa_requires_three_campaigns_in_band(self):
        _, _, aa_pass, _, _ = self.series([0.92, 0.92, 1.0, 1.0], [1.0] * 4)
        self.assertFalse(aa_pass)

    def test_aa_hard_bounds_are_enforced(self):
        _, _, aa_pass, _, _ = self.series([0.84, 1.0, 1.0, 1.0], [1.0] * 4)
        self.assertFalse(aa_pass)

    def test_bv39_ag_drift_does_not_block_when_aa_is_stable(self):
        _, _, aa_pass, ag_pass, decision = self.series([1.0] * 4, [1.20] * 4)
        self.assertTrue(aa_pass)
        self.assertFalse(ag_pass)
        self.assertEqual(decision, "15IC_AG_DIAGNOSTIC_DRIFT")

    def test_ag_requires_three_runs_at_or_below(self):
        _, _, _, ag_pass, _ = self.series([1.0] * 4, [1.05, 1.05, 1.08, 1.08])
        self.assertFalse(ag_pass)

    def test_bv31_truncated_series_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.evaluate_series({"aa-01": {lane: 1.0 for lane in verify.LANE_IDS}},
                                   {f"ag-0{index}": {lane: 1.0 for lane in verify.LANE_IDS}
                                    for index in range(1, 5)})

    def test_bv32_favorable_run_substitution_is_rejected(self):
        # The aggregate requires exactly the four fixed A/A ids.
        substituted = {"aa-01": {lane: 1.0 for lane in verify.LANE_IDS},
                       "aa-02": {lane: 1.0 for lane in verify.LANE_IDS},
                       "aa-03": {lane: 1.0 for lane in verify.LANE_IDS},
                       "aa-99": {lane: 1.0 for lane in verify.LANE_IDS}}
        with self.assertRaises(verify.VerificationFailed):
            verify.evaluate_series(
                substituted,
                {f"ag-0{index}": {lane: 1.0 for lane in verify.LANE_IDS}
                 for index in range(1, 5)})


class InventoryAndSealTests(unittest.TestCase):
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

    def test_bv27_unexpected_raw_file_is_rejected(self):
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

    def test_bv28_changed_seal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            with open(os.path.join(raw, "measurements.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({"schema": "tampered"}, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_seal(directory)

    def test_missing_seal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            os.remove(os.path.join(raw, "seal.json"))
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_seal(directory)

    def test_bv26_raw_symlink_is_rejected(self):
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
            os.makedirs(os.path.join(directory, "target", "pr15i-c"))
            first = verify.write_receipt(directory, "batched-v1-aa-01.json", {"schema": "x"})
            self.assertTrue(os.path.isfile(first))
            with self.assertRaises(verify.VerificationFailed):
                verify.write_receipt(directory, "batched-v1-aa-01.json", {"schema": "y"})


class ProvenanceTests(unittest.TestCase):
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

    def test_bv06_aa_two_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "one")
            second = os.path.join(directory, "two")
            for path in (first, second):
                with open(path, "wb") as handle:
                    handle.write(b"\x7fELF-identical")
            digest = verify.sha256_file(first)
            campaign = self.make_campaign("aa", first, second, digest, digest)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_executables(
                    campaign, verify.read_json(os.path.join(campaign, "raw", "manifest.json")),
                    "aa")

    def test_bv29_modified_binary_after_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = os.path.join(directory, "adapter")
            with open(binary, "wb") as handle:
                handle.write(b"\x7fELF-shared")
            digest = verify.sha256_file(binary)
            campaign = self.make_campaign("aa", binary, binary, digest, digest)
            with open(binary, "ab") as handle:
                handle.write(b"tampered")
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_executables(
                    campaign, verify.read_json(os.path.join(campaign, "raw", "manifest.json")),
                    "aa")

    def test_bv24_changed_toolchain_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = os.path.join(directory, "adapter")
            with open(binary, "wb") as handle:
                handle.write(b"\x7fELF-shared")
            digest = verify.sha256_file(binary)
            campaign = self.make_campaign("aa", binary, binary, digest, digest)
            path = os.path.join(campaign, "raw", "toolchain.json")
            record = verify.read_json(path)
            record["executed_binary_sha256"]["A"]["sha256"] = "f" * 64
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_executables(
                    campaign, verify.read_json(os.path.join(campaign, "raw", "manifest.json")),
                    "aa")

    def test_bv05_swapped_source_sha_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_source(ROOT, {"A_sha": verify.BASELINE_SHA,
                                        "B_sha": verify.GENERIC_CONTROL_SHA}, "aa")

    def test_bv07_forged_source_blob_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, verify.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["frozen_adapter_main_rs_sha256"] = "0" * 64
            with open(os.path.join(root, verify.PROTOCOL_REL), "w", encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_protocol(root, {"protocol_sha256": verify.sha256_file(
                    os.path.join(root, verify.PROTOCOL_REL))})

    def test_bv08_wrong_g_candidate_commit_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_source(ROOT, {"A_sha": verify.BASELINE_SHA,
                                        "B_sha": verify.BASELINE_SHA}, "ag")

    def test_bv33_protocol_version_spoof_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "root")
            os.makedirs(os.path.join(root, "benchmarks", "pr15i_c"))
            with open(os.path.join(ROOT, verify.PROTOCOL_REL), encoding="utf-8") as handle:
                protocol = json.load(handle)
            protocol["schema"] = "pr15i-c-batched-noise-v2"
            with open(os.path.join(root, verify.PROTOCOL_REL), "w", encoding="utf-8") as handle:
                json.dump(protocol, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_protocol(root, {})

    def test_bv23_wrong_affinity_mode_is_rejected(self):
        pinned = {"mode": "PINNED", "adapter_cpu": 0, "controller_cpu": 1}
        frequency = {"governor": "performance", "scaling_cur_freq_khz": 3_000_000}
        verify.verify_affinity(
            {"cpu_affinity": pinned},
            {"cpu_affinity": pinned, "frequency_before": frequency},
            {"cpu_affinity": pinned})
        for bad in ({"mode": "SOMETIMES"}, {"mode": "PINNED", "adapter_cpu": 0},
                    {"mode": "PINNED", "adapter_cpu": 1, "controller_cpu": 1},
                    {}):
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_affinity(
                    {"cpu_affinity": bad},
                    {"cpu_affinity": bad, "frequency_before": frequency},
                    {"cpu_affinity": bad})
        # Records that disagree about the mode are rejected even when each is valid.
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_affinity(
                {"cpu_affinity": pinned},
                {"cpu_affinity": {"mode": "NO_AFFINITY"}, "frequency_before": frequency},
                {"cpu_affinity": pinned})
        # A missing frequency observation is rejected.
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_affinity(
                {"cpu_affinity": pinned},
                {"cpu_affinity": pinned},
                {"cpu_affinity": pinned})


class FrozenContractTests(unittest.TestCase):
    def test_bv34_original_protocol_is_untouched(self):
        self.assertEqual(
            verify.sha256_file(os.path.join(ROOT, "benchmarks", "pr15i_c", "protocol.json")),
            "5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e")
        self.assertEqual(
            verify.sha256_file(os.path.join(
                ROOT, "benchmarks", "pr15i_c", "noise_protocol_v2.json")),
            "f99ecce69db5815ac798aed826c8c9e0e11ab75a1c68840f3e887488fcd8203d")

    def test_bv35_diagnostics_never_claim_feature_acceptance(self):
        with open(os.path.join(HERE, "verify_batched_noise.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"diagnostic_only": True', source)
        self.assertIn('"final_feature_acceptance": False', source)
        self.assertIn("OBSERVATION_ONLY", source)

    def test_bv36_series_identity_and_order_are_fixed(self):
        self.assertEqual(verify.SERIES_ORDER,
                         ["aa-01", "ag-01", "aa-02", "ag-02",
                          "aa-03", "ag-03", "aa-04", "ag-04"])

    def test_bv09_bv10_sizes_helpers_reject_bad_layouts(self):
        # Wrong codec / sentinel / missing rebuild are structural rejections in
        # `verify_sizes`; exercise them through the helper's pure inputs.
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "raw"))
            sizes = {"A": {}, "B": {}}
            for arm in ("A", "B"):
                for n in ("10000", "100000"):
                    sizes[arm][n] = [
                        {"attempt": attempt, "layout": {}, "segment_digest": "0" * 64}
                        for attempt in (1, 2, 3)
                    ]
            with open(os.path.join(directory, "raw", "sizes.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(sizes, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_sizes(directory)

    def test_bv11_bv12_duplicate_attempt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "raw"))
            sizes = {"A": {}, "B": {}}
            for arm in ("A", "B"):
                for n in ("10000", "100000"):
                    sizes[arm][n] = [
                        {"attempt": 1, "layout": {}, "segment_digest": "0" * 64},
                        {"attempt": 1, "layout": {}, "segment_digest": "0" * 64},
                        {"attempt": 3, "layout": {}, "segment_digest": "0" * 64},
                    ]
            with open(os.path.join(directory, "raw", "sizes.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(sizes, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_sizes(directory)


if __name__ == "__main__":
    unittest.main()

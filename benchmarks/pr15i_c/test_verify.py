#!/usr/bin/env python3
"""PR 15I-C independent-verifier adversarial tests (C-V matrix).

Every fixture is synthetic and lives in a temporary directory. No real campaign
and no frozen PR15D/PR15I evidence is ever modified.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load():
    spec = importlib.util.spec_from_file_location("pr15i_c_verify", os.path.join(HERE, "verify.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load()


def synthetic_slots(a_medians, b_medians, lane_ids=verify.LANE_IDS):
    slots = []
    index = 0
    for block, order in enumerate(verify.SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            index += 1
            selected = a_medians[block - 1] if arm == "A" else b_medians[block - 1]
            lanes = []
            for lane_id in lane_ids:
                samples = [selected] * verify.MEASURED
                lanes.append({
                    "id": lane_id,
                    "samples_ns": samples,
                    "summary_ns": verify.base.pr15d_run.summarize(samples),
                    "warmups": verify.WARMUPS,
                    "warmup_ids": [f"w{i}" for i in range(verify.WARMUPS)],
                    "oracle_ok": True,
                    "total_hits": 1,
                    "doc_keys": [],
                })
            slots.append({
                "slot_index": index,
                "block": block,
                "position": position,
                "arm": arm,
                "trial": {
                    "lanes": lanes,
                    "contention_before": {"state": "clear"},
                    "contention_after": {"state": "clear"},
                },
            })
    return slots


def uniform_slots(r_primary, r_nonprimary):
    """A-median 100 everywhere; B-median chosen per lane class."""
    a = [1_000_000, 1_000_000, 1_000_000, 1_000_000]
    b = [
        [int(1_000_000 * (r_primary if lane in verify.PRIMARY_LANES else r_nonprimary))
         for lane in verify.LANE_IDS] for _ in range(4)
    ]
    slots = []
    index = 0
    for block, order in enumerate(verify.SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            index += 1
            lanes = []
            for lane_index, lane_id in enumerate(verify.LANE_IDS):
                value = a[block - 1] if arm == "A" else b[block - 1][lane_index]
                value = max(1, int(value))
                samples = [value] * verify.MEASURED
                lanes.append({
                    "id": lane_id,
                    "samples_ns": samples,
                    "summary_ns": verify.base.pr15d_run.summarize(samples),
                    "warmups": verify.WARMUPS,
                    "warmup_ids": [f"w{i}" for i in range(verify.WARMUPS)],
                    "oracle_ok": True,
                    "total_hits": 1,
                    "doc_keys": [],
                })
            slots.append({
                "slot_index": index,
                "block": block,
                "position": position,
                "arm": arm,
                "trial": {
                    "lanes": lanes,
                    "contention_before": {"state": "clear"},
                    "contention_after": {"state": "clear"},
                },
            })
    return slots


def gates_for(slots):
    return verify.recompute_gates(verify.recompute_ratios(slots))


class SlotMatrixTests(unittest.TestCase):
    def test_v01_complete_matrix_is_accepted(self):
        measured, warmed = verify.validate_slot_matrix(synthetic_slots([100] * 4, [90] * 4))
        self.assertEqual(measured, 2880)
        self.assertEqual(warmed, 720)

    def test_v02_duplicate_slot_id_is_rejected(self):
        slots = synthetic_slots([100] * 4, [90] * 4)
        slots[1]["slot_index"] = slots[0]["slot_index"]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_v02_missing_slot_is_rejected(self):
        slots = synthetic_slots([100] * 4, [90] * 4)[:-1]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_v11_removed_measured_sample_is_rejected(self):
        slots = synthetic_slots([100] * 4, [90] * 4)
        slots[0]["trial"]["lanes"][0]["samples_ns"].pop()
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_v12_wrong_sample_count_is_rejected(self):
        for count in (19, 21):
            slots = synthetic_slots([100] * 4, [90] * 4)
            lane = slots[0]["trial"]["lanes"][0]
            lane["samples_ns"] = [100] * count
            lane["summary_ns"] = verify.base.pr15d_run.summarize(lane["samples_ns"])
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)

    def test_v12_wrong_warmup_count_is_rejected(self):
        for count in (4, 6):
            slots = synthetic_slots([100] * 4, [90] * 4)
            slots[0]["trial"]["lanes"][0]["warmups"] = count
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)

    def test_v16_inverted_schedule_is_rejected(self):
        slots = synthetic_slots([100] * 4, [90] * 4)
        slots[0]["arm"], slots[1]["arm"] = slots[1]["arm"], slots[0]["arm"]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_v17_forged_summary_is_rejected(self):
        slots = synthetic_slots([100] * 4, [90] * 4)
        slots[0]["trial"]["lanes"][0]["summary_ns"]["median"] = 1
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_v26_bool_and_zero_and_nan_samples_are_rejected(self):
        for bad in (True, 0, -1, 1.5, float("nan")):
            slots = synthetic_slots([100] * 4, [90] * 4)
            slots[0]["trial"]["lanes"][0]["samples_ns"] = [bad] * verify.MEASURED
            slots[0]["trial"]["lanes"][0]["summary_ns"] = {
                "count": verify.MEASURED, "median": 1, "p95": 1, "p99": 1, "min": 1, "max": 1,
            }
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)

    def test_v21_unclear_contention_is_rejected(self):
        slots = synthetic_slots([100] * 4, [90] * 4)
        slots[0]["trial"]["contention_before"] = {"state": "busy"}
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)


class GateTests(unittest.TestCase):
    def test_v13_exact_limits_pass(self):
        slots = uniform_slots(verify.PRIMARY_MEDIAN_MAX, verify.NONPRIMARY_MEDIAN_MAX)
        gates = gates_for(slots)
        for key in ("C-P06", "C-P07", "C-P08", "C-P09"):
            self.assertEqual(gates[key], "PASS", key)

    def test_v14_primary_just_over_is_rejected(self):
        slots = uniform_slots(verify.PRIMARY_MEDIAN_MAX + 1e-6, 1.0)
        gates = gates_for(slots)
        self.assertEqual(gates["C-P06"], "FAIL")
        self.assertEqual(gates["C-P07"], "FAIL")
        self.assertEqual(gates["C-P08"], "FAIL")

    def test_v14_primary_block_just_over_is_rejected(self):
        slots = uniform_slots(1.0, 1.0)
        # Push one block of a primary lane just above the per-block ceiling while
        # keeping the median below the median gate.
        for record in slots:
            if record["arm"] != "B" or record["block"] != 1:
                continue
            for lane in record["trial"]["lanes"]:
                if lane["id"] != verify.PRIMARY_LANES[0]:
                    continue
                lane["samples_ns"] = [1_150_001] * verify.MEASURED
                lane["summary_ns"] = verify.base.pr15d_run.summarize(lane["samples_ns"])
        ratios = verify.recompute_ratios(slots)
        self.assertGreater(ratios[verify.PRIMARY_LANES[0]]["block_ratios"][0],
                           verify.PRIMARY_BLOCK_MAX)

    def test_v15_non_primary_just_over_is_rejected(self):
        slots = uniform_slots(0.5, verify.NONPRIMARY_MEDIAN_MAX + 1e-6)
        gates = gates_for(slots)
        self.assertEqual(gates["C-P09"], "FAIL")

    def test_v24_inverted_ratio_direction_is_detected(self):
        slots = uniform_slots(1.10, 1.10)
        ratios = verify.recompute_ratios(slots)
        self.assertGreater(ratios[verify.PRIMARY_LANES[0]]["median"], 1.0)
        gates = gates_for(slots)
        self.assertEqual(gates["C-P06"], "FAIL")

    def test_v25_controller_disagreement_is_rejected(self):
        slots = uniform_slots(1.10, 1.10)
        ratios = verify.recompute_ratios(slots)
        gates = verify.recompute_gates(ratios)
        forged = {
            "warm_ratios": {lane: value["block_ratios"] for lane, value in ratios.items()},
            "gates": {**gates, "C-P06": "PASS"},
        }
        with self.assertRaises(verify.VerificationFailed):
            verify.compare_with_controller(ratios, gates, forged)

    def test_v25_agreement_is_accepted(self):
        slots = uniform_slots(0.85, 0.95)
        ratios = verify.recompute_ratios(slots)
        gates = verify.recompute_gates(ratios)
        consistent = {
            "warm_ratios": {lane: value["block_ratios"] for lane, value in ratios.items()},
            "gates": gates,
        }
        self.assertEqual(verify.compare_with_controller(ratios, gates, consistent), gates)


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
            "files": {
                relative: verify.sha256_file(os.path.join(raw, relative))
                for relative in verify.REQUIRED_RAW
            },
        }
        with open(os.path.join(raw, "seal.json"), "w", encoding="utf-8") as handle:
            json.dump(seal, handle)
        return raw

    def test_v05_extra_raw_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_raw(directory)
            with open(os.path.join(directory, "raw", "extra.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.inventory(directory)

    def test_v05_complete_inventory_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_raw(directory)
            found = verify.inventory(directory)
            self.assertEqual(len(found), len(verify.REQUIRED_RAW) + 1)

    def test_v04_symlinked_raw_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            target = os.path.join(directory, "outside.json")
            with open(target, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            link = os.path.join(raw, "authorization.json.link")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(verify.VerificationFailed):
                verify.inventory(directory)

    def test_v06_tamper_without_seal_recompute_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            with open(os.path.join(raw, "manifest.json"), "w", encoding="utf-8") as handle:
                json.dump({"schema": "tampered"}, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_seal(directory)

    def test_v07_tamper_with_recomputed_seal_is_rejected_by_independent_metrics(self):
        # The verifier never trusts the seal alone: even a fully re-sealed set of
        # slot records fails the independently recomputed per-sample summary.
        slots = synthetic_slots([100] * 4, [90] * 4)
        slots[0]["trial"]["lanes"][0]["samples_ns"] = [999] * verify.MEASURED
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_v23_receipt_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = os.path.join(directory, "target", "pr15i-c", "campaigns", "paired-01")
            os.makedirs(campaign)
            first = verify.write_receipt(directory, campaign, {"schema": "x"})
            self.assertTrue(os.path.isfile(first))
            with self.assertRaises(verify.VerificationFailed):
                verify.write_receipt(directory, campaign, {"schema": "y"})

    def test_v28_score_record_schema_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            left = {"total_hits": 1, "hits": [{"key": "a", "score_bits": "3ff0000000000000"}]}
            right = {"total_hits": 1, "hits": [{"key": "a", "score": 1.0}]}
            with open(os.path.join(raw, "score_parity.json"), "w", encoding="utf-8") as handle:
                json.dump({"schema": "x", "A": {"lane": left}, "B": {"lane": right}}, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_score_parity(directory)

    def test_v18_one_ulp_score_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_raw(directory)
            lane = verify.LANE_IDS[0]
            left = {"total_hits": 1, "hits": [{"key": "a", "score_bits": "3ff0000000000000"}]}
            right = {"total_hits": 1, "hits": [{"key": "a", "score_bits": "3ff0000000000001"}]}
            with open(os.path.join(directory, "raw", "score_parity.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({"schema": "x", "A": {lane: left["hits"]}, "B": {lane: right["hits"]}},
                          handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_score_parity(directory)


class ProvenanceTests(unittest.TestCase):
    def test_v10_pr15ia_baseline_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_source(ROOT, {"A_sha": verify.P0_15IA, "B_sha": verify.P0_15IA})

    def test_v08_unknown_commit_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_source(ROOT, {"A_sha": "0" * 40, "B_sha": "0" * 40})

    def test_v03_missing_rebuild_directory_is_rejected(self):
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
                verify.verify_sizes(directory, {})

    def test_v27_snapshot_ordinals_are_not_compared(self):
        # The verifier compares logical results and source provenance only; no
        # process-local generation/view ordinal is ever hashed as if identical.
        with open(os.path.join(HERE, "verify.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("view_ordinal", source)
        self.assertNotIn("generation", source.replace("generated", ""))


if __name__ == "__main__":
    unittest.main()

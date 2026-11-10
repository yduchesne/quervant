#!/usr/bin/env python3
"""PR 15I-C fixup — adversarial tests for the generic-boundary verifier (FX-V*).

Every fixture is synthetic and lives in a temporary directory. Historical
campaigns are never touched.
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


verify = load("pr15i_c_verify_layout_diag", "verify_layout_diag.py")

SYNTHETIC_SOURCE = """\
impl Searcher {
    fn helper(&self) -> u64 {
        1
    }

    fn collect_mixed(&self) -> u64 {
        let mut total = 0u64;
        total += self.helper();
        total
    }
}
"""

CONTROL_SOURCE = SYNTHETIC_SOURCE.replace(
    "    fn collect_mixed",
    "    #[inline(never)]\n    fn collect_mixed",
)

CHANGED_SOURCE = SYNTHETIC_SOURCE.replace("total += self.helper();",
                                          "total += self.helper() + 1;")


def write_repo(directory, baseline, candidate):
    os.makedirs(os.path.join(directory, "crates", "quervant-core", "src", "search"))
    path = os.path.join(directory, verify.UNIFIED_REL)
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
    return commit(baseline, "baseline"), commit(candidate, "candidate")


def synthetic_slots(a_median, b_median):
    slots = []
    index = 0
    for block, order in enumerate(verify.BLOCK_ORDERS, start=1):
        for position, arm in enumerate(order, start=1):
            index += 1
            value = a_median if arm == "A" else b_median
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
                "arm": arm,
                "trial": {
                    "lanes": lanes,
                    "contention_before": {"state": "clear"},
                    "contention_after": {"state": "clear"},
                },
            })
    return slots


def uniform_slots(ratio):
    return synthetic_slots(1_000_000, int(1_000_000 * ratio))


class SlotMatrixTests(unittest.TestCase):
    def test_fx_v01_complete_matrix_is_accepted(self):
        measured, warmed = verify.validate_slot_matrix(uniform_slots(1.0))
        self.assertEqual(measured, 2240)
        self.assertEqual(warmed, 1120)

    def test_fx_v02_missing_slot_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(uniform_slots(1.0)[:-1])

    def test_fx_v03_duplicated_slot_id_is_rejected(self):
        slots = uniform_slots(1.0)
        slots[1]["slot_index"] = slots[0]["slot_index"]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_fx_v14_wrong_block_order_is_rejected(self):
        slots = uniform_slots(1.0)
        slots[0]["arm"], slots[1]["arm"] = slots[1]["arm"], slots[0]["arm"]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_fx_v15_missing_lane_is_rejected(self):
        slots = uniform_slots(1.0)
        for record in slots:
            record["trial"]["lanes"] = [
                lane for lane in record["trial"]["lanes"]
                if lane["id"] != verify.LANE_IDS[0]
            ]
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_fx_v16_wrong_sample_count_is_rejected(self):
        for count in (9, 11):
            slots = uniform_slots(1.0)
            lane = slots[0]["trial"]["lanes"][0]
            lane["samples_ns"] = [1_000_000] * count
            lane["summary_ns"] = verify.base.pr15d_run.summarize(lane["samples_ns"])
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)

    def test_fx_v16_wrong_warmup_count_is_rejected(self):
        for count in (4, 6):
            slots = uniform_slots(1.0)
            slots[0]["trial"]["lanes"][0]["warmups"] = count
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)

    def test_fx_v17_unclear_contention_is_rejected(self):
        slots = uniform_slots(1.0)
        slots[3]["trial"]["contention_after"] = {"state": "busy"}
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_fx_v07_forged_summary_is_rejected(self):
        slots = uniform_slots(1.0)
        slots[0]["trial"]["lanes"][0]["summary_ns"]["median"] = 1
        with self.assertRaises(verify.VerificationFailed):
            verify.validate_slot_matrix(slots)

    def test_non_integer_samples_are_rejected(self):
        for bad in (True, 0, -5, 1.5, float("nan")):
            slots = uniform_slots(1.0)
            slots[0]["trial"]["lanes"][0]["samples_ns"] = [bad] * verify.MEASURED
            slots[0]["trial"]["lanes"][0]["summary_ns"] = {
                "count": verify.MEASURED, "median": 1, "p95": 1, "p99": 1,
                "min": 1, "max": 1,
            }
            with self.assertRaises(verify.VerificationFailed):
                verify.validate_slot_matrix(slots)


class GateTests(unittest.TestCase):
    def test_fx_v18_exact_limits_pass(self):
        gates = verify.recompute_gates(verify.recompute_ratios(uniform_slots(1.05)))
        self.assertEqual(gates["CONTROL"], "PASS")
        for lane_id in verify.LANE_IDS:
            self.assertEqual(gates[lane_id], "PASS")

    def test_fx_v19_median_just_over_is_rejected(self):
        slots = synthetic_slots(1_000_000, 1_050_001)
        gates = verify.recompute_gates(verify.recompute_ratios(slots))
        for lane_id in verify.LANE_IDS:
            self.assertEqual(gates[lane_id], "FAIL")
        self.assertEqual(gates["CONTROL"], "FAIL")

    def test_fx_v19_single_block_just_over_is_rejected(self):
        slots = uniform_slots(1.0)
        for record in slots:
            if record["arm"] != "B" or record["block"] != 2:
                continue
            lane = record["trial"]["lanes"][0]
            lane["samples_ns"] = [1_150_001] * verify.MEASURED
            lane["summary_ns"] = verify.base.pr15d_run.summarize(lane["samples_ns"])
        ratios = verify.recompute_ratios(slots)
        self.assertGreater(ratios[verify.LANE_IDS[0]]["block_ratios"][1],
                           verify.RATIO_BLOCK_MAX)
        gates = verify.recompute_gates(ratios)
        self.assertEqual(gates[verify.LANE_IDS[0]], "FAIL")
        self.assertEqual(gates["CONTROL"], "FAIL")

    def test_fx_v24_inverted_ratio_direction_is_detected(self):
        gates = verify.recompute_gates(verify.recompute_ratios(uniform_slots(1.10)))
        self.assertEqual(gates["CONTROL"], "FAIL")

    def test_fx_v22_controller_disagreement_is_rejected(self):
        ratios = verify.recompute_ratios(uniform_slots(1.10))
        gates = verify.recompute_gates(ratios)
        forged = {
            "ratios": {lane: value["block_ratios"] for lane, value in ratios.items()},
            "medians": {lane: value["median"] for lane, value in ratios.items()},
            "gates": {**gates, verify.LANE_IDS[0]: "PASS"},
            "qualified": gates["CONTROL"] == "PASS",
        }
        with self.assertRaises(verify.VerificationFailed):
            verify.compare_with_controller(ratios, gates, forged)

    def test_controller_agreement_is_accepted(self):
        ratios = verify.recompute_ratios(uniform_slots(0.95))
        gates = verify.recompute_gates(ratios)
        consistent = {
            "ratios": {lane: value["block_ratios"] for lane, value in ratios.items()},
            "medians": {lane: value["median"] for lane, value in ratios.items()},
            "gates": gates,
            "qualified": gates["CONTROL"] == "PASS",
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
            "files": {relative: verify.sha256_file(os.path.join(raw, relative))
                      for relative in verify.REQUIRED_RAW},
        }
        with open(os.path.join(raw, "seal.json"), "w", encoding="utf-8") as handle:
            json.dump(seal, handle)
        return raw

    def test_fx_v03_extra_raw_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            with open(os.path.join(raw, "extra.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.inventory(directory)

    def test_complete_inventory_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_raw(directory)
            found = verify.inventory(directory)
            self.assertEqual(len(found), len(verify.REQUIRED_RAW) + 1)

    def test_fx_v02_missing_seal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            os.remove(os.path.join(raw, "seal.json"))
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_seal(directory)

    def test_fx_v04_symlinked_slot_is_rejected(self):
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

    def test_fx_v06_tamper_without_seal_recompute_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            with open(os.path.join(raw, "measurements.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({"schema": "tampered"}, handle)
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_seal(directory)

    def test_fx_v23_read_only_on_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = self.make_raw(directory)
            first = verify.verify_seal(directory)
            second = verify.verify_seal(directory)
            self.assertEqual(first, second)
            with open(os.path.join(raw, "seal.json"), "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["schema"], verify.SEAL_SCHEMA)

    def test_fx_v24_receipt_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = os.path.join(directory, "target", "pr15i-c",
                                    "layout-diagnostics", "generic-boundary-01")
            os.makedirs(campaign)
            first = verify.write_receipt(directory, campaign, {"schema": "x"})
            self.assertTrue(os.path.isfile(first))
            with self.assertRaises(verify.VerificationFailed):
                verify.write_receipt(directory, campaign, {"schema": "y"})


class SourceProofTests(unittest.TestCase):
    def test_control_source_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            a, g = write_repo(directory, SYNTHETIC_SOURCE, CONTROL_SOURCE)
            manifest = {
                "A_sha": a,
                "G_sha": g,
                "baseline_body_sha256": verify.source_proof.body_sha(
                    SYNTHETIC_SOURCE, verify.GENERIC_METHOD),
                "generic_body_sha256": verify.source_proof.body_sha(
                    CONTROL_SOURCE, verify.GENERIC_METHOD),
            }
            changed, body = verify.verify_source(directory, manifest)
            self.assertEqual(changed, [verify.UNIFIED_REL])
            self.assertEqual(body, manifest["baseline_body_sha256"])

    def test_fx_v10_changed_generic_body_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            a, g = write_repo(directory, SYNTHETIC_SOURCE, CHANGED_SOURCE)
            manifest = {
                "A_sha": a,
                "G_sha": g,
                "baseline_body_sha256": verify.source_proof.body_sha(
                    SYNTHETIC_SOURCE, verify.GENERIC_METHOD),
                "generic_body_sha256": verify.source_proof.body_sha(
                    SYNTHETIC_SOURCE, verify.GENERIC_METHOD),
            }
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_source(directory, manifest)

    def test_fx_v08_unknown_commit_is_rejected(self):
        with self.assertRaises(verify.VerificationFailed):
            verify.verify_source(ROOT, {"A_sha": "0" * 40, "G_sha": "0" * 40})

    def test_fx_v09_non_descendant_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "crates", "quervant-core",
                                     "src", "search"))
            path = os.path.join(directory, verify.UNIFIED_REL)
            git = ["git", "-C", directory]
            subprocess.run([*git, "init", "-q"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(SYNTHETIC_SOURCE)
            subprocess.run([*git, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@t",
                            "commit", "-q", "-m", "one"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            first = subprocess.run([*git, "rev-parse", "HEAD"],
                                   stdout=subprocess.PIPE, text=True,
                                   check=True).stdout.strip()
            subprocess.run([*git, "checkout", "-q", "--orphan", "other"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(CONTROL_SOURCE)
            subprocess.run([*git, "add", "-A"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@t",
                            "commit", "-q", "-m", "two"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            second = subprocess.run([*git, "rev-parse", "HEAD"],
                                    stdout=subprocess.PIPE, text=True,
                                    check=True).stdout.strip()
            with self.assertRaises(verify.VerificationFailed):
                verify.verify_source(directory, {"A_sha": first, "G_sha": second})


class SizeProofTests(unittest.TestCase):
    def test_fx_v20_missing_rebuild_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "raw"))
            sizes = {"A": {}, "G": {}}
            for arm in ("A", "G"):
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


class ScopeTests(unittest.TestCase):
    def test_diagnostic_never_claims_feature_acceptance(self):
        with open(os.path.join(HERE, "verify_layout_diag.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"diagnostic_only": True', source)
        self.assertIn('"final_feature_acceptance": False', source)


if __name__ == "__main__":
    unittest.main()

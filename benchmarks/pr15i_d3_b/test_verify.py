#!/usr/bin/env python3
"""Independent negative-matrix tests (V01..V28) for the PR 15I-D3-B verifier.

This module imports only ``verify.py`` (the subject under test). Every fixture
is constructed here from the frozen lane list, and every expected gate, A/A and
drift verdict is recomputed by this file's own arithmetic. No controller helper
is imported and no real campaign is used as a fixture.

Run::

    python3 -m unittest discover -s benchmarks/pr15i_d3_b -p 'test_*.py' -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BLOCKS = 4
SAMPLES = 20
LANE_IDS = [
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/medium/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
]
HITS = {
    "pr15d_v1/10000/absent/k100": 0,
    "pr15d_v1/10000/rare/k100": 1,
    "pr15d_v1/10000/medium/k100": 1250,
    "pr15d_v1/10000/common/k100": 4999,
    "pr15d_v1/100000/absent/k100": 0,
    "pr15d_v1/100000/rare/k100": 1,
    "pr15d_v1/100000/medium/k100": 12500,
    "pr15d_v1/100000/common/k100": 49999,
    "pr15d_v1/100000/common/k10": 49999,
}
ARM_ORDER = [("A", "B", "B", "A"), ("B", "A", "A", "B"), ("B", "A", "A", "B"), ("A", "B", "B", "A")]


def _load(name: str, filename: str):
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b", filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load("pr15i_d3_b_verify_matrix", "verify.py")


def descriptor(lane_id: str) -> dict:
    parts = lane_id.split("/")
    n = int(parts[1])
    class_name = parts[2]
    k = int(parts[3][1:])
    return {
        "id": lane_id,
        "n": n,
        "class": class_name,
        "field": "group" if class_name == "medium" else "key",
        "term": {"absent": "never", "rare": "singleton", "medium": "medium", "common": "common"}[class_name],
        "k": k,
    }


LANES = [descriptor(lane_id) for lane_id in LANE_IDS]
DIGESTS = {"10000": "c" * 64, "100000": "d" * 64}


def lane_record(lane: dict, median: int, hits: int | None = None) -> dict:
    hits = HITS[lane["id"]] if hits is None else hits
    samples = [median] * SAMPLES
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "regime": "warm",
        "warmups": 5,
        "warmup_ids": [f"warmup-{index}" for index in range(5)],
        "samples_ns": samples,
        "summary_ns": {"count": SAMPLES, "median": sorted(samples)[9]},
        "total_hits": hits,
        "doc_ids": [],
        "expected_total_hits": hits,
        "expected_doc_ids": [],
        "oracle_ok": True,
    }


def constant_arm(ns: int) -> dict:
    return {block: {lane["id"]: ns for lane in LANES} for block in range(1, BLOCKS + 1)}


def slots(per_arm: dict, kind: str = "paired") -> list[dict]:
    plan = []
    for block, order in enumerate(ARM_ORDER, start=1):
        for position, arm in enumerate(order, start=1):
            plan.append(
                {
                    "slot": (block - 1) * 4 + position,
                    "block": block,
                    "position": position,
                    "arm": arm,
                }
            )
    result = []
    for entry in plan:
        values = per_arm[entry["arm"]][entry["block"]]
        result.append(
            {
                "schema": "pr15i-d3b-slot-v1",
                "slot": entry["slot"],
                "block": entry["block"],
                "position": entry["position"],
                "arm": entry["arm"],
                "source_sha": "a" * 40,
                "binary_sha256": ("b" if entry["arm"] == "A" else "e") * 64,
                "index_digests": dict(DIGESTS),
                "contention_before": {"state": "clear", "reason_codes": []},
                "contention_after": {"state": "clear", "reason_codes": []},
                "lanes": [lane_record(lane, values[lane["id"]]) for lane in LANES],
            }
        )
    return result


def metrics(overrides: dict | None = None, ratios: dict | None = None) -> dict:
    """Independent block arithmetic: a = 10,000,000 ns, b = a - d."""
    diffs = {lane["id"]: [0, 0, 0, 0] for lane in LANES}
    for lane_id, values in (overrides or {}).items():
        diffs[lane_id] = list(values)
    result = {}
    for lane in LANES:
        values = diffs[lane["id"]]
        a_values = [10_000_000] * 4
        b_values = [a - value for a, value in zip(a_values, values)]
        block_ratios = [b / a for a, b in zip(a_values, b_values)]
        if ratios and lane["id"] in ratios:
            block_ratios = list(ratios[lane["id"]])
            b_values = [int(10_000_000 * value) for value in block_ratios]
        result[lane["id"]] = {
            "id": lane["id"],
            "class": lane["class"],
            "n": lane["n"],
            "a_block_medians_ns": a_values,
            "b_block_medians_ns": b_values,
            "diffs_ns": values,
            "median_diff_ns": sorted(values)[1],
            "median_diff_ms": sorted(values)[1] / 1_000_000,
            "b_over_a_block": block_ratios,
            "b_over_a_median": sorted(block_ratios)[1],
        }
    return result


def gates(overrides: dict | None = None, ratios: dict | None = None) -> dict:
    return VERIFY.compute_gates("d3b-base", metrics(overrides, ratios))


def manifest(kind: str = "paired", campaign: str | None = None) -> dict:
    control = kind == "control"
    campaign = campaign or ("d3b-base-aa-01" if control else "d3b-base-01")
    indices = (
        [{"arm": "A", "n": 10000}, {"arm": "A", "n": 100000}]
        if control
        else [
            {"arm": "A", "n": 10000},
            {"arm": "A", "n": 100000},
            {"arm": "B", "n": 10000},
            {"arm": "B", "n": 100000},
        ]
    )
    return {
        "schema": "pr15i-d3b-manifest-v1",
        "campaign": campaign,
        "kind": kind,
        "comparison": "d3b-base",
        "tooling_sha": "1" * 40,
        "tooling_manifest_sha256": "7" * 64,
        "controller_sha256": "2" * 64,
        "verifier_sha256": "3" * 64,
        "protocol_sha256": "4" * 64,
        "base_source_sha": VERIFY.BASE_SHA,
        "candidate_source_sha": VERIFY.BASE_SHA if control else "b" * 40,
        "source_fingerprints": {
            "A": {"crates/quervant-core/src/search/unified.rs": "e" * 64},
            "B": {"crates/quervant-core/src/search/unified.rs": "e" * 64},
        },
        "environment_fingerprint": "f" * 64,
        "corpus": {"manifest_sha256": VERIFY.CORPUS_MANIFEST_SHA256},
        "expected_by_lane": {},
        "arms": {
            "A": {"source_sha": VERIFY.BASE_SHA, "binary_sha256": "5" * 64, "index_digests": dict(DIGESTS)},
            "B": {
                "source_sha": VERIFY.BASE_SHA if control else "b" * 40,
                "binary_sha256": "6" * 64,
                "index_digests": dict(DIGESTS),
            },
        },
        "builds": {"adapters": ["A", "B"], "indices": indices},
        "control": None,
    }


class VerifierMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr15i-d3-b-verify-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _campaign_dir(self, slot_records: list[dict]) -> str:
        root = os.path.join(self.tmp, "campaign")
        os.makedirs(os.path.join(root, "raw", "slots"), exist_ok=True)
        for slot in slot_records:
            with open(
                os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(slot, handle)
        return root

    def _expected(self) -> dict:
        return {lane["id"]: {"total_hits": HITS[lane["id"]], "doc_ids": []} for lane in LANES}

    # V01
    def test_v01_pristine_control_qualifies(self):
        report = VERIFY.compute_control(slots({"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}, "control"), LANES)
        self.assertTrue(report["passes"])
        self.assertTrue(all(entry["passes"] for entry in report["lanes"].values()))

    # V02
    def test_v02_pristine_paired_both_k100_wins(self):
        table = gates(
            {
                "pr15d_v1/100000/common/k100": [2_500_000, 2_500_000, 2_500_000, 100_000],
                "pr15d_v1/100000/medium/k100": [1_500_000, 1_500_000, 1_500_000, 100_000],
            }
        )
        self.assertEqual(table["D3B-P01"], "PASS")
        self.assertEqual(table["D3B-P02"], "PASS")
        self.assertTrue(all(result == "PASS" for result in table.values()))

    # V03
    def test_v03_zero_effect_is_rejected(self):
        table = gates()
        self.assertEqual(table["D3B-P01"], "FAIL")
        self.assertEqual(table["D3B-P02"], "FAIL")

    # V04
    def test_v04_common_k100_one_ns_short(self):
        table = gates({"pr15d_v1/100000/common/k100": [1_999_999] * 4})
        self.assertEqual(table["D3B-P01"], "FAIL")

    # V05
    def test_v05_common_k100_exact_boundary_and_blocks(self):
        table = gates({"pr15d_v1/100000/common/k100": [2_000_000, 2_000_000, 2_000_000, -1]})
        self.assertEqual(table["D3B-P01"], "PASS")
        table = gates({"pr15d_v1/100000/common/k100": [2_000_000, 2_000_000, -1, -1]})
        self.assertEqual(table["D3B-P01"], "FAIL")

    # V06
    def test_v06_medium_k100_exact_boundary(self):
        table = gates(
            {
                "pr15d_v1/100000/medium/k100": [1_000_000, 1_000_000, 1_000_000, 0],
                "pr15d_v1/100000/common/k100": [2_000_000, 2_000_000, 2_000_000, 0],
            }
        )
        self.assertEqual(table["D3B-P02"], "PASS")

    # V07
    def test_v07_medium_k100_one_ns_short(self):
        table = gates({"pr15d_v1/100000/medium/k100": [999_999] * 4})
        self.assertEqual(table["D3B-P02"], "FAIL")

    # V08
    def test_v08_k10_inclusive_boundaries(self):
        lane_id = "pr15d_v1/100000/common/k10"
        table = gates(
            {lane_id: [-500_000, -500_000, -500_000, -1_500_000]},
            {lane_id: [1.05, 1.05, 1.05, 1.05]},
        )
        self.assertEqual(table["D3B-P03"], "PASS")

    # V09
    def test_v09_k10_below_median_or_block(self):
        lane_id = "pr15d_v1/100000/common/k10"
        self.assertEqual(gates({lane_id: [-500_001] * 4})["D3B-P03"], "FAIL")
        self.assertEqual(
            gates({lane_id: [-100_000, -100_000, -100_000, -1_500_001]})["D3B-P03"],
            "FAIL",
        )

    # V10
    def test_v10_k10_ratio_ceiling(self):
        lane_id = "pr15d_v1/100000/common/k10"
        table = gates(
            {lane_id: [-1_000_000] * 4},
            {lane_id: [1.050_001] * 4},
        )
        self.assertEqual(table["D3B-P03"], "FAIL")

    # V11
    def test_v11_low_hit_ratio_exact_ceiling(self):
        lane_id = "pr15d_v1/10000/absent/k100"
        table = gates({}, {lane_id: [1.15] * 4})
        self.assertEqual(table["D3B-P04"], "PASS")

    # V12
    def test_v12_low_hit_ratio_over_median_or_block(self):
        lane_id = "pr15d_v1/10000/rare/k100"
        self.assertEqual(gates({}, {lane_id: [1.150_001] * 4})["D3B-P04"], "FAIL")
        self.assertEqual(
            gates({}, {lane_id: [1.15, 1.15, 1.15, 1.500_001]})["D3B-P04"],
            "FAIL",
        )

    # V13
    def test_v13_small_common_strict_median(self):
        table = gates({"pr15d_v1/10000/common/k100": [-2_000_000] * 4})
        self.assertEqual(table["D3B-P05"], "FAIL")

    # V14
    def test_v14_small_common_block_floor(self):
        table = gates({"pr15d_v1/10000/common/k100": [-1_000_000, -1_000_000, -1_000_000, -3_000_001]})
        self.assertEqual(table["D3B-P05"], "FAIL")

    # V15
    def test_v15_high_k100_block_guard(self):
        table = gates(
            {
                "pr15d_v1/100000/common/k100": [3_000_000, 3_000_000, 3_000_000, -1_500_001],
                "pr15d_v1/100000/medium/k100": [2_000_000, 2_000_000, 2_000_000, -1_500_000],
            }
        )
        self.assertEqual(table["D3B-P06"], "FAIL")

    # V16
    def test_v16_only_two_nonnegative_target_blocks(self):
        table = gates({"pr15d_v1/100000/common/k100": [2_000_000, 2_000_000, -1, -1]})
        self.assertEqual(table["D3B-P01"], "FAIL")

    # V17
    def test_v17_control_one_exempt_soft_outlier_qualifies(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][1] = {lane["id"]: 13_000_000 for lane in LANES}
        for exempt in ("pr15d_v1/10000/absent/k100", "pr15d_v1/10000/rare/k100"):
            per_arm["B"][1][exempt] = int(10_000_000 * 1.30)
        per_arm["B"][1]["pr15d_v1/10000/absent/k100"] = int(10_000_000 * 1.30)
        # Only the two exempt lanes may be out of the soft band.
        per_arm["B"][1] = {lane["id"]: 10_000_000 for lane in LANES}
        per_arm["B"][1]["pr15d_v1/10000/rare/k100"] = int(10_000_000 * 1.30)
        report = VERIFY.compute_control(slots(per_arm, "control"), LANES)
        self.assertTrue(report["passes"], report)

    # V18
    def test_v18_control_two_exempt_soft_outliers_blocked(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        for block in (1, 2):
            per_arm["B"][block]["pr15d_v1/10000/absent/k100"] = int(10_000_000 * 1.30)
        self.assertFalse(VERIFY.compute_control(slots(per_arm, "control"), LANES)["passes"])

    # V19
    def test_v19_control_non_exempt_soft_or_any_hard_outlier_blocked(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][1]["pr15d_v1/10000/common/k100"] = int(10_000_000 * 1.30)
        self.assertFalse(VERIFY.compute_control(slots(per_arm, "control"), LANES)["passes"])
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][1]["pr15d_v1/10000/rare/k100"] = int(10_000_000 * 1.60)
        self.assertFalse(VERIFY.compute_control(slots(per_arm, "control"), LANES)["passes"])

    # V20
    def test_v20_control_median_outside_bounds_blocked(self):
        for ratio in (1.150_1, 0.849_9):
            per_arm = {
                "A": constant_arm(10_000_000),
                "B": {
                    block: {lane["id"]: int(10_000_000 * ratio) for lane in LANES}
                    for block in range(1, BLOCKS + 1)
                },
            }
            self.assertFalse(VERIFY.compute_control(slots(per_arm, "control"), LANES)["passes"])

    # V21
    def test_v21_high_hit_block_drift_blocked(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][2] = {lane["id"]: 12_500_001 for lane in LANES}
        violations = VERIFY.drift_violations(slots(per_arm), LANES, BLOCKS)
        self.assertTrue(any(item["gate"] == "BLOCK_DRIFT" for item in violations))

    # V22
    def test_v22_low_hit_block_drift_blocked(self):
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(10_000_000)}
        per_arm["B"][4] = {lane["id"]: 15_000_001 for lane in LANES}
        violations = VERIFY.drift_violations(slots(per_arm), LANES, BLOCKS)
        self.assertTrue(any(item["gate"] == "BLOCK_DRIFT" for item in violations))

    # V23
    def test_v23_missing_duplicate_or_reordered_slot_and_lane_invalid(self):
        base = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._campaign_dir(base[:-1]), manifest(), self._expected())
        duplicate = [dict(base[0])] + list(base)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._campaign_dir(duplicate), manifest(), self._expected())
        reordered = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        reordered[0]["lanes"] = list(reversed(reordered[0]["lanes"]))
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._campaign_dir(reordered), manifest(), self._expected())

    # V24
    def test_v24_oracle_document_id_tamper_invalid(self):
        tampered = slots({"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)})
        tampered[7]["lanes"][2]["doc_ids"] = ["forged"]
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._campaign_dir(tampered), manifest(), self._expected())

    # V25
    def test_v25_binary_index_and_sentinel_tamper_invalid(self):
        broken = manifest()
        broken["arms"]["B"]["binary_sha256"] = "not-a-digest"
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_binaries(broken)

        setup = os.path.join(self.tmp, "campaign", "raw", "setup")
        os.makedirs(setup, exist_ok=True)
        for entry in manifest()["builds"]["indices"]:
            arm = entry["arm"]
            n = entry["n"]
            payload = {
                "arm": arm,
                "n": n,
                "protocol_sha256": "4" * 64,
                "build": {},
                "layout": {
                    "committed_index_bytes": 10,
                    "stored_bytes": 5,
                    "files": [{"path": "index/CURRENT", "size": 10, "sha256": "0" * 64}],
                    "digest": VERIFY.sha256_bytes(
                        VERIFY.canonical_json_bytes(
                            [{"path": "index/CURRENT", "size": 10, "sha256": "0" * 64}]
                        )
                    ),
                },
            }
            if n == 100000:
                payload["layout"]["committed_index_bytes"] = 15_747_551
                payload["layout"]["stored_bytes"] = 1_661_455
                payload["layout"]["files"] = [{"path": "index/CURRENT", "size": 15_747_551, "sha256": "0" * 64}]
                payload["layout"]["digest"] = VERIFY.sha256_bytes(
                    VERIFY.canonical_json_bytes(
                        [{"path": "index/CURRENT", "size": 15_747_551, "sha256": "0" * 64}]
                    )
                )
            with open(os.path.join(setup, f"index-{arm}-n{n}.json"), "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        campaign_dir = os.path.join(self.tmp, "campaign")
        broken = manifest()
        broken["arms"]["A"]["index_digests"]["100000"] = "f" * 64
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_indexes(campaign_dir, broken)
        broken = manifest()
        for arm in ("A", "B"):
            broken["arms"][arm]["index_digests"] = dict(DIGESTS)
        path = os.path.join(setup, "index-A-n100000.json")
        record = json.load(open(path, encoding="utf-8"))
        record["layout"]["stored_bytes"] = 1_661_456
        json.dump(record, open(path, "w", encoding="utf-8"))
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_indexes(campaign_dir, broken)

    # V26
    def test_v26_wrong_protocol_digest_invalid(self):
        setup = os.path.join(self.tmp, "campaign", "raw", "setup")
        os.makedirs(setup, exist_ok=True)
        for name in ("corpus.json", "adapter-A.json", "adapter-B.json", "index-A-n10000.json", "index-A-n100000.json"):
            with open(os.path.join(setup, name), "w", encoding="utf-8") as handle:
                json.dump({"protocol_sha256": "0" * 64}, handle)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_setup_protocol(manifest(), os.path.join(self.tmp, "campaign"), "4" * 64)

    # V27
    def test_v27_duplicate_manifest_path_traversal_symlink_unlisted_invalid(self):
        root = os.path.join(self.tmp, "seal")
        os.makedirs(os.path.join(root, "raw", "slots"))
        target = os.path.join(root, "raw", "slots", "slot-01.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("one")
        digest = VERIFY.sha256_file(target)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.read_json(os.path.join(root, "..", "missing.json"))
        bad = {"schema": "pr15i-d3b-seal-v1", "kind": "paired", "files": {"../escape.json": digest}}
        with open(os.path.join(root, "raw", "seal.json"), "w", encoding="utf-8") as handle:
            json.dump(bad, handle)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_seal(root)
        good = {"schema": "pr15i-d3b-seal-v1", "kind": "paired", "files": {"raw/slots/slot-01.json": digest}}
        with open(os.path.join(root, "raw", "seal.json"), "w", encoding="utf-8") as handle:
            json.dump(good, handle)
        with open(os.path.join(root, "raw", "slots", "slot-02.json"), "w", encoding="utf-8") as handle:
            handle.write("extra")
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_inventory(root, good)
        os.remove(os.path.join(root, "raw", "slots", "slot-02.json"))
        link = os.path.join(root, "raw", "slots", "slot-03.json")
        os.symlink(target, link)
        good["files"]["raw/slots/slot-03.json"] = digest
        with open(os.path.join(root, "raw", "seal.json"), "w", encoding="utf-8") as handle:
            json.dump(good, handle)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_seal(root)

    # V28
    def test_v28_series_history_rejects_campaign_02_after_failed_01(self):
        root = os.path.join(self.tmp, "series")
        os.makedirs(os.path.join(root, "d3b-base-01"))
        os.makedirs(os.path.join(root, "d3b-base-02"))

        def fake_verify(path: str) -> dict:
            status = "CAMPAIGN_REJECTED" if path.endswith("-01") else "CAMPAIGN_QUALIFIED"
            return {
                "campaign": os.path.basename(path),
                "campaign_status": status,
                "gates": {"D3B-P01": "FAIL" if status == "CAMPAIGN_REJECTED" else "PASS"},
            }

        original = VERIFY.verify_campaign_dir
        VERIFY.verify_campaign_dir = fake_verify
        try:
            with self.assertRaises(VERIFY.VerifyError):
                VERIFY.aggregate_series(root, "d3b-base")
        finally:
            VERIFY.verify_campaign_dir = original

    # Extra: exclusive create and tampered controller summary
    def test_extra_exclusive_create_and_summary_recompute(self):
        path = os.path.join(self.tmp, "exclusive.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{}")
        with self.assertRaises(FileExistsError):
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(descriptor)
        per_arm = {"A": constant_arm(10_000_000), "B": constant_arm(9_000_000)}
        slot_records = slots(per_arm)
        first = VERIFY.recompute_summary(manifest(), slot_records, LANES, "4" * 64)
        slot_records[0]["lanes"][0]["samples_ns"] = [1] * SAMPLES
        slot_records[0]["lanes"][0]["summary_ns"] = {"count": SAMPLES, "median": 1}
        second = VERIFY.recompute_summary(manifest(), slot_records, LANES, "4" * 64)
        self.assertNotEqual(
            VERIFY.canonical_json_bytes(first["lanes"]),
            VERIFY.canonical_json_bytes(second["lanes"]),
        )


if __name__ == "__main__":
    unittest.main()

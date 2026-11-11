#!/usr/bin/env python3
"""Adversarial controller/verifier tests for PR 15I-D1-F (B01..B17).

All fixtures are synthetic, live in fresh ``tempfile`` directories outside the
production ``target/`` tree, and are used only to verify the controller and
independent verifier. They are never evidence for a real campaign.

Run::

    python3 -m unittest discover -s benchmarks/pr15i_d1_f -p 'test_*.py' -v
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name: str, filename: str):
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d1_f", filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = _load("pr15i_d1_f_run_tests", "run.py")
VERIFY = _load("pr15i_d1_f_verify_tests", "verify.py")
PROTOCOL = RUN.PROTOCOL
LANES = RUN.lane_descriptors(PROTOCOL)


def _lane_record(lane: dict, median: int, *, hits: int | None = None, ids=None) -> dict:
    hits = RUN.EXPECTED_TOTAL_HITS[lane["id"]] if hits is None else hits
    ids = [] if ids is None else ids
    samples = [median] * PROTOCOL["samples_per_lane_slot"]
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "regime": "warm",
        "warmups": PROTOCOL["warmups_per_lane_slot"],
        "warmup_ids": [f"warmup-{index}" for index in range(PROTOCOL["warmups_per_lane_slot"])],
        "samples_ns": samples,
        "summary_ns": {"count": len(samples), "median": median},
        "total_hits": hits,
        "doc_ids": ids,
        "expected_total_hits": hits,
        "expected_doc_ids": ids,
        "oracle_ok": True,
    }


def _slots(per_arm: dict) -> list[dict]:
    plan = RUN.slot_plan(PROTOCOL, "paired")
    slots = []
    for entry in plan:
        values = per_arm[entry["arm"]][entry["block"]]
        slots.append(
            {
                "schema": "pr15i-d1-f-slot-v1",
                "slot": entry["slot"],
                "block": entry["block"],
                "position": entry["position"],
                "arm": entry["arm"],
                "source_sha": "a" * 40,
                "binary_sha256": "b" * 64,
                "index_digests": {"10000": "c" * 64, "100000": "d" * 64},
                "contention_before": {"state": "clear", "reason_codes": []},
                "contention_after": {"state": "clear", "reason_codes": []},
                "lanes": [_lane_record(lane, values[lane["id"]]) for lane in LANES],
            }
        )
    return slots


def _constant_arm(value: int) -> dict:
    return {block: {lane["id"]: value for lane in LANES} for block in (1, 2, 3, 4)}


def _manifest(kind: str = "paired", campaign: str | None = None) -> dict:
    control = kind == "control"
    campaign = campaign or ("c2-base-aa-01" if control else "c2-base-01")
    digests = {"10000": "c" * 64, "100000": "d" * 64}
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
        "schema": "pr15i-d1-f-manifest-v1",
        "campaign": campaign,
        "kind": kind,
        "comparison": "c2-base",
        "tooling_sha": "1" * 40,
        "controller_sha256": "2" * 64,
        "verifier_sha256": "3" * 64,
        "protocol_sha256": "4" * 64,
        "base_source_sha": RUN.BASE_SHA,
        "candidate_source_sha": RUN.BASE_SHA if control else "b" * 40,
        "source_fingerprints": {
            "A": {"crates/quervant-core/src/search/unified.rs": "e" * 64},
            "B": {"crates/quervant-core/src/search/unified.rs": "e" * 64},
        },
        "environment_fingerprint": "f" * 64,
        "corpus": {"manifest_sha256": RUN.CORPUS_MANIFEST_SHA256},
        "expected_by_lane": {},
        "arms": {
            "A": {"source_sha": RUN.BASE_SHA, "binary_sha256": "5" * 64, "index_digests": dict(digests)},
            "B": {
                "source_sha": RUN.BASE_SHA if control else "b" * 40,
                "binary_sha256": "6" * 64,
                "index_digests": dict(digests),
            },
        },
        "builds": {"adapters": ["A", "B"], "indices": indices},
        "control": None,
    }


def _campaign(kind: str) -> dict:
    return {
        "campaign": "c2-base-aa-01" if kind == "control" else "c2-base-01",
        "kind": kind,
        "comparison": "c2-base",
    }


def _metrics(diffs: dict, ratios: dict | None = None) -> dict:
    metrics = {}
    for lane in LANES:
        values = diffs[lane["id"]]
        a_values = [10_000_000 for _ in values]
        b_values = [a - diff for a, diff in zip(a_values, values)]
        block_ratios = [b / a for a, b in zip(a_values, b_values)]
        if ratios and lane["id"] in ratios:
            block_ratios = list(ratios[lane["id"]])
            b_values = [int(10_000_000 * value) for value in block_ratios]
        metrics[lane["id"]] = {
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
    return metrics


class ScheduleAndSampleTests(unittest.TestCase):
    def test_B04_frozen_schedule(self):
        plan = RUN.slot_plan(PROTOCOL, "paired")
        self.assertEqual(len(plan), 16)
        self.assertEqual([e["arm"] for e in plan if e["block"] == 1], ["A", "B", "B", "A"])
        self.assertEqual([e["arm"] for e in plan if e["block"] == 2], ["B", "A", "A", "B"])
        self.assertEqual(sum(1 for e in plan if e["arm"] == "A"), 8)
        self.assertEqual(sum(1 for e in plan if e["arm"] == "B"), 8)

    def test_B05_reordered_or_unbalanced_schedule_rejected(self):
        bad = copy.deepcopy(PROTOCOL)
        bad["arm_order_by_block"][0] = ["A", "B", "B", "B"]
        with self.assertRaises(RUN.D1Invalid):
            RUN.slot_plan(bad, "paired")
        for name in ("c2-base-03", "c1-base-01", "c2-base-aa-02"):
            with self.assertRaises(RUN.D1Invalid):
                RUN.campaign_kind(name, PROTOCOL)

    def test_B06_bad_samples_rejected(self):
        for samples in ([0] * 20, [-1] * 20, [1.5] * 20, [True] * 20, [1] * 19, [1] * 21):
            with self.assertRaises(RUN.D1Invalid):
                RUN.validate_samples(samples)
            with self.assertRaises(VERIFY.VerifyError):
                VERIFY.median20(samples, "fixture")


class GateMathTests(unittest.TestCase):
    def test_controller_and_verifier_agree(self):
        cases = [
            {lane["id"]: [0, 0, 0, 0] for lane in LANES},
            {lane["id"]: [2_000_000, 2_000_000, 2_000_000, 2_000_000] for lane in LANES},
            {lane["id"]: [-5_000_000, 1_000_000, 1_000_000, 1_000_000] for lane in LANES},
        ]
        for case in cases:
            metrics = _metrics(case)
            self.assertEqual(
                RUN.paired_gate_table("c2-base", metrics, PROTOCOL),
                VERIFY.compute_gates("c2-base", metrics),
            )

    def test_B10_p01_exact_boundary(self):
        base = {lane["id"]: [0, 0, 0, 0] for lane in LANES}
        lane_id = "pr15d_v1/100000/common/k100"
        exact = dict(base)
        exact[lane_id] = [2_000_000, 2_000_000, 2_000_000, -1]
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(exact), PROTOCOL)["FC2-P01"], "PASS")
        no_win = dict(base)
        no_win[lane_id] = [1_999_999, 1_999_999, 1_999_999, 1_999_999]
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(no_win), PROTOCOL)["FC2-P01"], "FAIL")
        one_negative = dict(base)
        one_negative[lane_id] = [2_000_000, 2_000_000, 0, -1]
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(one_negative), PROTOCOL)["FC2-P01"], "FAIL")
        two_negative = dict(base)
        two_negative[lane_id] = [2_000_000, 2_000_000, -1, -1]
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(two_negative), PROTOCOL)["FC2-P01"], "FAIL")

    def test_B11_k10_guard_boundaries(self):
        base = {lane["id"]: [0, 0, 0, 0] for lane in LANES}
        k10 = "pr15d_v1/100000/common/k10"
        at_floor = dict(base)
        at_floor[k10] = [0, 0, 0, -3_000_000]
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(at_floor), PROTOCOL)["FC2-P02"], "PASS")
        below = dict(base)
        below[k10] = [0, 0, 0, -3_000_001]
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(below), PROTOCOL)["FC2-P02"], "FAIL")
        strict = dict(base)
        strict[k10] = [-2_000_000, -2_000_000, -2_000_000, -2_000_000]
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(strict), PROTOCOL)["FC2-P02"], "FAIL")
        above = dict(base)
        above[k10] = [-1_999_999, -1_999_999, -1_999_999, -1_999_999]
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(above), PROTOCOL)["FC2-P02"], "PASS")

    def test_B12_low_hit_ratio_boundaries(self):
        base = {lane["id"]: [0, 0, 0, 0] for lane in LANES}
        lane_id = "pr15d_v1/10000/absent/k100"
        at_ceiling = {lane_id: [1.15, 1.15, 1.15, 1.15]}
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(base, at_ceiling), PROTOCOL)["FC2-P04"], "PASS")
        over = {lane_id: [1.1500001, 1.1500001, 1.1500001, 1.1500001]}
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(base, over), PROTOCOL)["FC2-P04"], "FAIL")
        block_ok = {lane_id: [1.15, 1.15, 1.15, 1.50]}
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(base, block_ok), PROTOCOL)["FC2-P04"], "PASS")
        block_bad = {lane_id: [1.15, 1.15, 1.15, 1.5001]}
        self.assertEqual(RUN.paired_gate_table("c2-base", _metrics(base, block_bad), PROTOCOL)["FC2-P04"], "FAIL")

    def test_B17_zero_effect_and_slower_rejected(self):
        zero = _metrics({lane["id"]: [0, 0, 0, 0] for lane in LANES})
        self.assertEqual(RUN.paired_gate_table("c2-base", zero, PROTOCOL)["FC2-P01"], "FAIL")
        slower = _metrics({lane["id"]: [-5_000_000] * 4 for lane in LANES})
        self.assertEqual(RUN.paired_gate_table("c2-base", slower, PROTOCOL)["FC2-P02"], "FAIL")
        self.assertEqual(RUN.paired_gate_table("c2-base", slower, PROTOCOL)["FC2-P03"], "FAIL")

    def test_B13_one_pass_one_reject(self):
        self.assertEqual(
            VERIFY.aggregate_statuses(["CAMPAIGN_QUALIFIED", "CAMPAIGN_REJECTED"]),
            "COMPARISON_PERFORMANCE_REJECTED",
        )
        self.assertEqual(
            VERIFY.aggregate_statuses(["CAMPAIGN_QUALIFIED", "CAMPAIGN_QUALIFIED"]),
            "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY",
        )
        self.assertEqual(
            VERIFY.aggregate_statuses(["CAMPAIGN_QUALIFIED", "MEASUREMENT_BLOCKED"]),
            "MEASUREMENT_BLOCKED",
        )

    def test_B09_aa_boundaries(self):
        def control_values(ratio: float, block_ratio: float | None = None) -> dict:
            per_arm = {
                "A": _constant_arm(10_000_000),
                "B": {block: {lane["id"]: int(10_000_000 * ratio) for lane in LANES} for block in (1, 2, 3, 4)},
            }
            if block_ratio is not None:
                per_arm["B"][1] = {lane["id"]: int(10_000_000 * block_ratio) for lane in LANES}
            return per_arm

        report = VERIFY.compute_control(_slots(control_values(1.0)), LANES)
        self.assertTrue(report["passes"])
        self.assertTrue(VERIFY.compute_control(_slots(control_values(1.15)), LANES)["passes"])
        self.assertFalse(VERIFY.compute_control(_slots(control_values(1.1501)), LANES)["passes"])
        self.assertTrue(VERIFY.compute_control(_slots(control_values(1.0, 1.25)), LANES)["passes"])
        self.assertFalse(VERIFY.compute_control(_slots(control_values(1.0, 1.2501)), LANES)["passes"])
        self.assertTrue(VERIFY.compute_control(_slots(control_values(1.0, 0.80)), LANES)["passes"])
        self.assertFalse(VERIFY.compute_control(_slots(control_values(1.0, 0.7999)), LANES)["passes"])
        two_low = control_values(1.0)
        for block in (1, 2):
            two_low["B"][block] = {lane["id"]: int(10_000_000 * 0.84) for lane in LANES}
        self.assertFalse(VERIFY.compute_control(_slots(two_low), LANES)["passes"])

    def test_B09_low_median_ratio_boundary(self):
        per_arm = {"A": _constant_arm(10_000_000), "B": {}}
        # Median ratio 0.85 with every block inside [0.80, 1.25] passes.
        for block, ratio in ((1, 0.85), (2, 0.85), (3, 1.20), (4, 1.20)):
            per_arm["B"][block] = {lane["id"]: int(10_000_000 * ratio) for lane in LANES}
        self.assertTrue(VERIFY.compute_control(_slots(per_arm), LANES)["passes"])
        per_arm["B"][1] = {lane["id"]: int(10_000_000 * 0.8499) for lane in LANES}
        per_arm["B"][2] = {lane["id"]: int(10_000_000 * 0.8499) for lane in LANES}
        self.assertFalse(VERIFY.compute_control(_slots(per_arm), LANES)["passes"])

    def test_drift_over_limit_blocks(self):
        per_arm = {"A": _constant_arm(10_000_000), "B": _constant_arm(10_000_000)}
        per_arm["B"][4] = {lane["id"]: 20_000_000 for lane in LANES}
        summary = RUN.assemble_campaign(_campaign("paired"), _manifest(), PROTOCOL, _slots(per_arm), LANES)
        self.assertEqual(summary["status"], "MEASUREMENT_BLOCKED")
        self.assertEqual(summary["drift"]["status"], "FAIL")


class SourcePolicyTests(unittest.TestCase):
    def test_B02_c1_symbols_rejected(self):
        self.assertEqual(RUN.forbidden_c1_symbols("fn retained_key_exists() {}", PROTOCOL), ["retained_key_exists"])
        self.assertEqual(RUN.forbidden_c1_symbols("struct RetainedKeyFingerprintIndex;", PROTOCOL), ["RetainedKeyFingerprintIndex"])
        self.assertEqual(RUN.forbidden_c1_symbols("fn doc_key_view() {}", PROTOCOL), [])

    def test_B02_path_allowlist(self):
        self.assertTrue(RUN.path_allowed("crates/quervant-core/src/search/unified.rs"))
        self.assertTrue(RUN.path_allowed("crates/quervant-core/src/segment/reader.rs"))
        self.assertTrue(RUN.path_allowed("crates/quervant-core/tests/pr15i_d1_f_keys.rs"))
        self.assertTrue(RUN.path_allowed("benchmarks/pr15i_d1_f/run.py"))
        self.assertTrue(RUN.path_allowed("docs/pr-artifacts/pr-15i-d1-f/preflight.md"))
        self.assertFalse(RUN.path_allowed("crates/quervant-core/src/search/execute.rs"))
        self.assertFalse(RUN.path_allowed("Cargo.lock"))
        self.assertFalse(RUN.path_allowed("crates/quervant-core/src/segment/column.rs"))

    def test_B03_index_sentinel(self):
        manifest = _manifest()
        for arm in ("A", "B"):
            manifest["arms"][arm]["index_layout"] = {
                "10000": {"committed_index_bytes": 1, "stored_bytes": 1, "digest": "x"},
                "100000": {
                    "committed_index_bytes": PROTOCOL["100k_lz4_committed_index_sentinel"],
                    "stored_bytes": PROTOCOL["100k_lz4_stored_section_sentinel"],
                    "digest": "d" * 64,
                },
            }
        self.assertEqual(RUN.index_sentinel_failures(manifest, PROTOCOL), [])
        manifest["arms"]["B"]["index_layout"]["100000"]["stored_bytes"] += 1
        self.assertTrue(RUN.index_sentinel_failures(manifest, PROTOCOL))
        manifest["arms"]["B"]["index_layout"]["100000"]["stored_bytes"] -= 1
        manifest["arms"]["B"]["index_digests"]["100000"] = "e" * 64
        self.assertTrue(RUN.index_sentinel_failures(manifest, PROTOCOL))


class SummaryAgreementTests(unittest.TestCase):
    def test_controller_and_verifier_recompute_identically(self):
        for kind in ("paired", "control"):
            per_arm = {
                "A": _constant_arm(10_000_000),
                "B": _constant_arm(10_000_000 + (1_000_000 if kind == "paired" else 0)),
            }
            slots = _slots(per_arm)
            manifest = _manifest(kind)
            manifest["controller_sha256"] = RUN.sha256_file(os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d1_f/run.py"))
            manifest["verifier_sha256"] = RUN.sha256_file(os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d1_f/verify.py"))
            summary = RUN.assemble_campaign(_campaign(kind), manifest, PROTOCOL, slots, LANES)
            recomputed = VERIFY.recompute_summary(manifest, slots, LANES, manifest["protocol_sha256"])
            self.assertEqual(RUN.canonical_json_bytes(summary), VERIFY.canonical_json_bytes(recomputed))

    def test_tampered_sample_changes_summary(self):
        per_arm = {"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)}
        slots = _slots(per_arm)
        manifest = _manifest()
        first = VERIFY.recompute_summary(manifest, slots, LANES, manifest["protocol_sha256"])
        slots[0]["lanes"][0]["samples_ns"] = [value + 5_000_000 for value in slots[0]["lanes"][0]["samples_ns"]]
        slots[0]["lanes"][0]["summary_ns"]["median"] += 5_000_000
        second = VERIFY.recompute_summary(manifest, slots, LANES, manifest["protocol_sha256"])
        self.assertNotEqual(VERIFY.canonical_json_bytes(first), VERIFY.canonical_json_bytes(second))


class SlotAndSealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr15i-d1-f-tests-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _campaign_dir(self, slots: list[dict]) -> str:
        root = os.path.join(self.tmp, "campaign")
        os.makedirs(os.path.join(root, "raw", "slots"), exist_ok=True)
        for slot in slots:
            with open(os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), "w", encoding="utf-8") as handle:
                json.dump(slot, handle)
        return root

    def _expected(self) -> dict:
        return {lane["id"]: {"total_hits": RUN.EXPECTED_TOTAL_HITS[lane["id"]], "doc_ids": []} for lane in LANES}

    def test_B05_missing_lane_and_reorder_rejected(self):
        slots = _slots({"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)})
        slots[0]["lanes"] = slots[0]["lanes"][:-1]
        root = self._campaign_dir(slots)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(root, _manifest(), self._expected())
        slots = _slots({"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)})
        slots[0]["lanes"] = list(reversed(slots[0]["lanes"]))
        root = self._campaign_dir(slots)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(root, _manifest(), self._expected())

    def test_B08_nonclear_contention_rejected(self):
        slots = _slots({"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)})
        slots[3]["contention_after"] = {"state": "busy", "reason_codes": ["cpu_load"]}
        root = self._campaign_dir(slots)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(root, _manifest(), self._expected())

    def test_B07_oracle_tamper_rejected(self):
        slots = _slots({"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)})
        slots[5]["lanes"][3]["total_hits"] += 1
        root = self._campaign_dir(slots)
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(root, _manifest(), self._expected())

    def test_B14_seal_tamper_inventory_and_traversal(self):
        root = os.path.join(self.tmp, "seal-fixture")
        os.makedirs(os.path.join(root, "raw", "slots"))
        members = {"raw/slots/slot-01.json": "one", "sanitized/summary.json": "two"}
        for relative, content in members.items():
            full = os.path.join(root, relative)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(content)
        files = {relative: VERIFY.sha256_file(os.path.join(root, relative)) for relative in members}
        seal = {"schema": "pr15i-d1-f-seal-v1", "kind": "paired", "files": files}
        with open(os.path.join(root, "raw", "seal.json"), "w", encoding="utf-8") as handle:
            json.dump(seal, handle)
        self.assertEqual(VERIFY.verify_seal(root)["kind"], "paired")
        VERIFY.verify_inventory(root, seal)
        with open(os.path.join(root, "raw", "slots", "slot-01.json"), "w", encoding="utf-8") as handle:
            handle.write("tampered")
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_seal(root)
        with open(os.path.join(root, "raw", "slots", "slot-01.json"), "w", encoding="utf-8") as handle:
            handle.write("one")
        with open(os.path.join(root, "raw", "slots", "slot-02.json"), "w", encoding="utf-8") as handle:
            handle.write("extra")
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_inventory(root, seal)
        bad = {"schema": "pr15i-d1-f-seal-v1", "kind": "paired", "files": {"../escape.json": "0" * 64}}
        with self.assertRaises(VERIFY.VerifyError):
            for relative, expected in bad["files"].items():
                if relative.startswith(".."):
                    raise VERIFY.VerifyError("V_SEAL", "unsafe member")

    def test_B01_B16_archive_round_trip_and_tamper(self):
        root = os.path.join(self.tmp, "campaign")
        os.makedirs(os.path.join(root, "build", "A"))
        os.makedirs(os.path.join(root, "indexes", "A-n10000"))
        os.makedirs(os.path.join(root, "corpus"))
        os.makedirs(os.path.join(root, "raw", "slots"))
        os.makedirs(os.path.join(root, "sanitized"))
        payloads = {
            "authorization.json": "auth",
            "manifest.json": "manifest",
            "raw/slots/slot-01.json": "slot",
            "sanitized/summary.json": "summary",
            "build/A/binary": "binary",
            "indexes/A-n10000/file": "index",
            "corpus/pr15d_v1_N10000.tsv": "corpus",
        }
        for relative, content in payloads.items():
            with open(os.path.join(root, relative), "w", encoding="utf-8") as handle:
                handle.write(content)
        members = RUN._archive_members(root, PROTOCOL)
        self.assertNotIn("build/A/binary", members)
        self.assertNotIn("indexes/A-n10000/file", members)
        self.assertNotIn("corpus/pr15d_v1_N10000.tsv", members)
        archive = os.path.join(self.tmp, "campaign.tar.gz")
        inventory = RUN.write_archive(root, archive, members)
        RUN.verify_archive(archive, inventory)
        with self.assertRaises(RUN.D1Invalid):
            RUN.write_archive(root, archive, members)
        # A tampered member inventory must be refused.
        tampered = dict(inventory)
        tampered["raw/slots/slot-01.json"] = "0" * 64
        with self.assertRaises(RUN.D1Blocked):
            RUN.verify_archive(archive, tampered)
        # Unsafe archive member names must be refused.
        evil = os.path.join(self.tmp, "evil.tar.gz")
        with tarfile.open(evil, "w:gz") as tar:
            data = b"evil"
            info = tarfile.TarInfo("../escape.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(RUN.D1Blocked):
            RUN.verify_archive(evil, {"../escape.txt": RUN.sha256_bytes(b"evil")})

    def test_B15_existing_outputs_refused(self):
        existing = os.path.join(self.tmp, "existing.json")
        RUN.write_exclusive_json(existing, {"ok": True})
        with self.assertRaises(FileExistsError):
            RUN.write_exclusive_json(existing, {"ok": False})


class CliContractTests(unittest.TestCase):
    def test_help_works(self):
        parser = RUN.build_parser()
        for command in ("preflight", "paired", "verify", "publish"):
            with self.assertRaises(SystemExit):
                parser.parse_args([command, "--help"])

    def test_preflight_campaign_is_optional_and_negative_inputs_rejected(self):
        parser = RUN.build_parser()
        args = parser.parse_args(
            [
                "preflight",
                "--base-tree", "/abs/base",
                "--base-sha", "a" * 40,
                "--candidate-tree", "/abs/c2",
                "--candidate-sha", "b" * 40,
                "--out", "/abs/out.json",
            ]
        )
        self.assertEqual(args.campaign, "c2-base-01")
        with self.assertRaises(SystemExit):
            parser.parse_args(["paired", "--out", "relative"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["publish"])


if __name__ == "__main__":
    unittest.main()

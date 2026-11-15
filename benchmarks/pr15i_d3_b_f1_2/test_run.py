#!/usr/bin/env python3
"""Adversarial controller/verifier tests for PR 15I-D3-B.

All fixtures are synthetic, live in fresh ``tempfile`` directories outside the
production ``target/`` tree, and are used only to verify the controller and the
independent verifier. They are never evidence for a real campaign.

Run::

    python3 -m unittest discover -s benchmarks/pr15i_d3_b -p 'test_*.py' -v
"""

from __future__ import annotations

import argparse
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
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_2", filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = _load("pr15i_d3_b_run_tests", "run.py")
VERIFY = _load("pr15i_d3_b_verify_tests", "verify.py")
PROTOCOL = RUN.PROTOCOL
LANES = RUN.lane_descriptors(PROTOCOL)
DIGESTS = {"10000": "c" * 64, "100000": "d" * 64}


def _lane_record(lane: dict, median: int) -> dict:
    hits = RUN.EXPECTED_TOTAL_HITS[lane["id"]]
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
        "doc_ids": [],
        "expected_total_hits": hits,
        "expected_doc_ids": [],
        "oracle_ok": True,
        "adapter_pid": 1234,
        "adapter_affinity_before": [0],
        "adapter_affinity_after": [0],
        "affinity_capture_stages": ["pre_warmup", "post_timed_sample_20"],
    }


def _slots(per_arm: dict, kind: str = "paired") -> list[dict]:
    plan = RUN.slot_plan(PROTOCOL, kind)
    slots = []
    for entry in plan:
        values = per_arm[entry["arm"]][entry["block"]]
        slots.append(
            {
                "schema": "pr15i-d3bf12-slot-v1",
                "slot": entry["slot"],
                "block": entry["block"],
                "position": entry["position"],
                "arm": entry["arm"],
                "source_sha": "a" * 40,
                "binary_sha256": ("b" if entry["arm"] == "A" else "e") * 64,
                "index_digests": dict(DIGESTS),
                "contention_before": {"state": "clear", "reason_codes": []},
                "contention_after": {"state": "clear", "reason_codes": []},
                "controller_affinity_before": [1],
                "controller_affinity_after": [1],
                "lanes": [_lane_record(lane, values[lane["id"]]) for lane in LANES],
            }
        )
    return slots


def _constant_arm(value: int) -> dict:
    return {block: {lane["id"]: value for lane in LANES} for block in (1, 2, 3, 4)}


def _manifest(kind: str = "paired", campaign: str | None = None) -> dict:
    control = kind == "control"
    campaign = campaign or ("d3bf12-base-aa-01" if control else "d3bf12-base-01")
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
        "schema": "pr15i-d3bf12-manifest-v1",
        "campaign": campaign,
        "kind": kind,
        "comparison": "d3bf12-base",
        "tooling_sha": "1" * 40,
        "tooling_manifest_sha256": "7" * 64,
        "build_provenance_sha256": "8" * 64,
        "host_attestation_sha256": "9" * 64,
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
            "A": {"source_sha": RUN.BASE_SHA, "binary_sha256": "5" * 64, "index_digests": dict(DIGESTS)},
            "B": {
                "source_sha": RUN.BASE_SHA if control else "b" * 40,
                "binary_sha256": "6" * 64,
                "index_digests": dict(DIGESTS),
            },
        },
        "builds": {"adapters": ["A", "B"], "indices": indices},
        "control": None,
    }


def _campaign(kind: str) -> dict:
    return {
        "campaign": "d3bf12-base-aa-01" if kind == "control" else "d3bf12-base-01",
        "kind": kind,
        "comparison": "d3bf12-base",
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


def _zero() -> dict:
    return {lane["id"]: [0, 0, 0, 0] for lane in LANES}


def _structural() -> dict:
    return {
        "build_provenance": "PASS",
        "host_attestation": "PASS",
        "affinity_observations": "PASS",
        "host_readiness": "PASS",
    }


def _gate(metrics: dict) -> dict:
    return RUN.paired_gate_table("d3bf12-base", metrics, PROTOCOL)


class ScheduleAndSampleTests(unittest.TestCase):
    def test_d3b_b01_frozen_schedule(self):
        plan = RUN.slot_plan(PROTOCOL, "paired")
        self.assertEqual(len(plan), 16)
        self.assertEqual([e["arm"] for e in plan if e["block"] == 1], ["A", "B", "B", "A"])
        self.assertEqual([e["arm"] for e in plan if e["block"] == 2], ["B", "A", "A", "B"])
        self.assertEqual(sum(1 for e in plan if e["arm"] == "A"), 8)
        self.assertEqual(sum(1 for e in plan if e["arm"] == "B"), 8)

    def test_d3b_b02_reordered_or_unbalanced_schedule_rejected(self):
        bad = copy.deepcopy(PROTOCOL)
        bad["arm_order_by_block"][0] = ["A", "B", "B", "B"]
        with self.assertRaises(RUN.D3BInvalid):
            RUN.slot_plan(bad, "paired")
        for name in ("d3b-base-03", "d3b-base-aa-03", "c2-base-01", "c1-base-01"):
            with self.assertRaises(RUN.D3BInvalid):
                RUN.campaign_kind(name, PROTOCOL)

    def test_d3b_b03_authorized_campaign_names(self):
        self.assertEqual(RUN.campaign_kind("d3bf12-base-aa-01", PROTOCOL), ("d3bf12-base", "control"))
        self.assertEqual(RUN.campaign_kind("d3bf12-base-aa-02", PROTOCOL), ("d3bf12-base", "control"))
        self.assertEqual(RUN.campaign_kind("d3bf12-base-01", PROTOCOL), ("d3bf12-base", "paired"))
        self.assertEqual(RUN.campaign_kind("d3bf12-base-02", PROTOCOL), ("d3bf12-base", "paired"))

    def test_d3b_b04_bad_samples_rejected(self):
        for samples in ([0] * 20, [-1] * 20, [1.5] * 20, [True] * 20, [1] * 19, [1] * 21):
            with self.assertRaises(RUN.D3BInvalid):
                RUN.validate_samples(samples)
            with self.assertRaises(VERIFY.VerifyError):
                VERIFY.median20(samples, "fixture")


class GateMathTests(unittest.TestCase):
    def test_d3b_b05_controller_and_verifier_agree(self):
        cases = [
            _zero(),
            {lane["id"]: [2_000_000, 2_000_000, 2_000_000, 2_000_000] for lane in LANES},
            {lane["id"]: [-5_000_000, 1_000_000, 1_000_000, 1_000_000] for lane in LANES},
        ]
        for case in cases:
            metrics = _metrics(case)
            self.assertEqual(_gate(metrics), VERIFY.compute_gates("d3bf12-base", metrics))

    def test_d3b_b06_primary_target_boundaries(self):
        lane_id = "pr15d_v1/100000/common/k100"
        exact = dict(_zero())
        exact[lane_id] = [2_000_000, 2_000_000, 2_000_000, -1]
        self.assertEqual(_gate(_metrics(exact))["D3B-P01"], "PASS")
        no_win = dict(_zero())
        no_win[lane_id] = [1_999_999, 1_999_999, 1_999_999, 1_999_999]
        self.assertEqual(_gate(_metrics(no_win))["D3B-P01"], "FAIL")
        two_negative = dict(_zero())
        two_negative[lane_id] = [2_000_000, 2_000_000, -1, -1]
        self.assertEqual(_gate(_metrics(two_negative))["D3B-P01"], "FAIL")

    def test_d3b_b07_medium_target_boundaries(self):
        lane_id = "pr15d_v1/100000/medium/k100"
        exact = dict(_zero())
        exact[lane_id] = [1_000_000, 1_000_000, 1_000_000, 0]
        self.assertEqual(_gate(_metrics(exact))["D3B-P02"], "PASS")
        below = dict(_zero())
        below[lane_id] = [999_999, 999_999, 999_999, 999_999]
        self.assertEqual(_gate(_metrics(below))["D3B-P02"], "FAIL")

    def test_d3b_b08_k10_guard_boundaries(self):
        lane_id = "pr15d_v1/100000/common/k10"
        at_floor = dict(_zero())
        at_floor[lane_id] = [-500_000, -500_000, -500_000, -1_500_000]
        self.assertEqual(_gate(_metrics(at_floor))["D3B-P03"], "PASS")
        below = dict(_zero())
        below[lane_id] = [-500_000, -500_000, -500_000, -1_500_001]
        self.assertEqual(_gate(_metrics(below))["D3B-P03"], "FAIL")
        below_median = dict(_zero())
        below_median[lane_id] = [-500_001, -500_001, -500_001, -500_001]
        self.assertEqual(_gate(_metrics(below_median))["D3B-P03"], "FAIL")
        ratio = dict(_zero())
        ratio[lane_id] = [-100_000, -100_000, -100_000, -100_000]
        metrics = _metrics(ratio, {lane_id: [1.0500001, 1.0500001, 1.0500001, 1.0500001]})
        self.assertEqual(_gate(metrics)["D3B-P03"], "FAIL")
        at_ratio = _metrics(ratio, {lane_id: [1.05, 1.05, 1.05, 1.05]})
        self.assertEqual(_gate(at_ratio)["D3B-P03"], "PASS")
        consistent = dict(_zero())
        consistent[lane_id] = [-500_000, -500_000, -500_000, -500_000]
        consistent_metrics = _metrics(consistent, {lane_id: [1.05, 1.05, 1.05, 1.05]})
        self.assertEqual(_gate(consistent_metrics)["D3B-P03"], "PASS")

    def test_d3b_b09_low_hit_ratio_boundaries(self):
        lane_id = "pr15d_v1/10000/absent/k100"
        at_ceiling = _metrics(_zero(), {lane_id: [1.15, 1.15, 1.15, 1.15]})
        self.assertEqual(_gate(at_ceiling)["D3B-P04"], "PASS")
        over = _metrics(_zero(), {lane_id: [1.150001, 1.150001, 1.150001, 1.150001]})
        self.assertEqual(_gate(over)["D3B-P04"], "FAIL")
        block_bad = _metrics(_zero(), {lane_id: [1.15, 1.15, 1.15, 1.500001]})
        self.assertEqual(_gate(block_bad)["D3B-P04"], "FAIL")

    def test_d3b_b10_small_lane_guards(self):
        common = "pr15d_v1/10000/common/k100"
        medium = "pr15d_v1/10000/medium/k100"
        strict = dict(_zero())
        strict[common] = [-2_000_000, -2_000_000, -2_000_000, -2_000_000]
        self.assertEqual(_gate(_metrics(strict))["D3B-P05"], "FAIL")
        inside = dict(_zero())
        inside[common] = [-1_999_999, -1_999_999, -1_999_999, -3_000_000]
        inside[medium] = [-1_999_999, -1_999_999, -1_999_999, -3_000_000]
        self.assertEqual(_gate(_metrics(inside))["D3B-P05"], "PASS")
        block_bad = dict(_zero())
        block_bad[medium] = [-1_000_000, -1_000_000, -1_000_000, -3_000_001]
        self.assertEqual(_gate(_metrics(block_bad))["D3B-P05"], "FAIL")

    def test_d3b_b11_high_k100_block_guards(self):
        common = "pr15d_v1/100000/common/k100"
        medium = "pr15d_v1/100000/medium/k100"
        values = dict(_zero())
        values[common] = [3_000_000, 3_000_000, 3_000_000, -1_500_001]
        self.assertEqual(_gate(_metrics(values))["D3B-P06"], "FAIL")
        values[common] = [3_000_000, 3_000_000, 3_000_000, -1_500_000]
        values[medium] = [2_000_000, 2_000_000, 2_000_000, -1_500_000]
        self.assertEqual(_gate(_metrics(values))["D3B-P06"], "PASS")

    def test_d3b_b12_zero_effect_and_slower_rejected(self):
        self.assertEqual(_gate(_metrics(_zero()))["D3B-P01"], "FAIL")
        slower = _metrics({lane["id"]: [-5_000_000] * 4 for lane in LANES})
        self.assertEqual(_gate(slower)["D3B-P03"], "FAIL")
        self.assertEqual(_gate(slower)["D3B-P05"], "FAIL")

    def test_d3b_b13_series_statuses(self):
        self.assertEqual(
            VERIFY.aggregate_statuses(["CAMPAIGN_QUALIFIED", "CAMPAIGN_QUALIFIED"]),
            "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY",
        )
        self.assertEqual(
            VERIFY.aggregate_statuses(["CAMPAIGN_REJECTED"]),
            "COMPARISON_PERFORMANCE_REJECTED",
        )
        self.assertEqual(
            VERIFY.aggregate_statuses(["CAMPAIGN_QUALIFIED", "MEASUREMENT_BLOCKED"]),
            "MEASUREMENT_BLOCKED",
        )


class ControlPolicyTests(unittest.TestCase):
    def _control(self, per_arm: dict) -> dict:
        return VERIFY.compute_control(_slots(per_arm, "control"), LANES)

    def _uniform(self, ratio: float) -> dict:
        return {
            "A": _constant_arm(10_000_000),
            "B": {
                block: {lane["id"]: int(10_000_000 * ratio) for lane in LANES}
                for block in (1, 2, 3, 4)
            },
        }

    def test_d3b_b14_median_and_soft_bounds(self):
        self.assertTrue(self._control(self._uniform(1.0))["passes"])
        self.assertTrue(self._control(self._uniform(1.15))["passes"])
        self.assertFalse(self._control(self._uniform(1.1501))["passes"])
        self.assertTrue(self._control(self._uniform(0.85))["passes"])
        self.assertFalse(self._control(self._uniform(0.8499))["passes"])

    def test_d3b_b15_exempt_lane_single_soft_outlier(self):
        per_arm = self._uniform(1.0)
        per_arm["B"][1] = {lane["id"]: int(10_000_000 * 1.40) for lane in LANES}
        report = self._control(per_arm)
        self.assertFalse(report["passes"], "a non-exempt lane may not tolerate an outlier")

        per_arm = self._uniform(1.0)
        for exempt in ("pr15d_v1/10000/absent/k100", "pr15d_v1/10000/rare/k100"):
            per_arm["B"][1][exempt] = int(10_000_000 * 1.40)
        report = self._control(per_arm)
        self.assertTrue(report["passes"], report)
        self.assertEqual(report["lanes"]["pr15d_v1/10000/absent/k100"]["soft_outliers"], [1])

    def test_d3b_b16_exempt_lane_two_outliers_or_hard_outlier(self):
        per_arm = self._uniform(1.0)
        for block in (1, 2):
            per_arm["B"][block]["pr15d_v1/10000/absent/k100"] = int(10_000_000 * 1.30)
        self.assertFalse(self._control(per_arm)["passes"])
        per_arm = self._uniform(1.0)
        per_arm["B"][1]["pr15d_v1/10000/rare/k100"] = int(10_000_000 * 1.51)
        self.assertFalse(self._control(per_arm)["passes"])

    def test_d3b_b17_no_median_exception(self):
        per_arm = {
            "A": _constant_arm(10_000_000),
            "B": {},
        }
        for block, ratio in ((1, 1.0), (2, 1.0), (3, 1.0), (4, 0.79)):
            per_arm["B"][block] = {lane["id"]: int(10_000_000 * ratio) for lane in LANES}
        report = self._control(per_arm)
        self.assertFalse(report["passes"], "one soft outlier is not tolerated on normal lanes")


class DriftAndSummaryTests(unittest.TestCase):
    def test_d3b_b18_drift_blocks_campaign(self):
        per_arm = {"A": _constant_arm(10_000_000), "B": _constant_arm(10_000_000)}
        per_arm["B"][4] = {lane["id"]: 20_000_000 for lane in LANES}
        summary = RUN.assemble_campaign(_campaign("paired"), _manifest(), PROTOCOL, _slots(per_arm), LANES, _structural())
        self.assertEqual(summary["status"], "MEASUREMENT_BLOCKED")
        self.assertEqual(summary["drift"]["status"], "FAIL")

    def test_d3b_b19_controller_and_verifier_summary_agree(self):
        for kind in ("paired", "control"):
            per_arm = {
                "A": _constant_arm(10_000_000),
                "B": _constant_arm(10_000_000 + (3_000_000 if kind == "paired" else 0)),
            }
            slots = _slots(per_arm, kind)
            manifest = _manifest(kind)
            manifest["controller_sha256"] = RUN.sha256_file(
                os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b/run.py")
            )
            manifest["verifier_sha256"] = RUN.sha256_file(
                os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b/verify.py")
            )
            summary = RUN.assemble_campaign(_campaign(kind), manifest, PROTOCOL, slots, LANES, _structural())
            recomputed = VERIFY.recompute_summary(manifest, slots, LANES, manifest["protocol_sha256"], _structural())
            self.assertEqual(RUN.canonical_json_bytes(summary), VERIFY.canonical_json_bytes(recomputed))

    def test_d3b_b20_tampered_sample_changes_summary(self):
        per_arm = {"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)}
        slots = _slots(per_arm)
        manifest = _manifest()
        first = VERIFY.recompute_summary(manifest, slots, LANES, manifest["protocol_sha256"], _structural())
        slots[0]["lanes"][0]["samples_ns"] = [value + 5_000_000 for value in slots[0]["lanes"][0]["samples_ns"]]
        slots[0]["lanes"][0]["summary_ns"]["median"] += 5_000_000
        second = VERIFY.recompute_summary(manifest, slots, LANES, manifest["protocol_sha256"], _structural())
        self.assertNotEqual(VERIFY.canonical_json_bytes(first), VERIFY.canonical_json_bytes(second))

    def test_d3b_b21_structural_failure_blocks(self):
        per_arm = {"A": _constant_arm(10_000_000), "B": _constant_arm(10_000_000)}
        structural = _structural()
        structural["build_provenance"] = "MEASUREMENT_BLOCKED"
        summary = RUN.assemble_campaign(
            _campaign("control"), _manifest("control"), PROTOCOL, _slots(per_arm, "control"), LANES, structural
        )
        self.assertEqual(summary["status"], "MEASUREMENT_BLOCKED")

    def test_d3b_b21b_numerical_control_failure_status(self):
        per_arm = {"A": _constant_arm(10_000_000), "B": _constant_arm(13_000_000)}
        summary = RUN.assemble_campaign(
            _campaign("control"), _manifest("control"), PROTOCOL, _slots(per_arm, "control"), LANES, _structural()
        )
        self.assertEqual(summary["status"], "CONTROL_NUMERICAL_BLOCKED")


class SourcePolicyTests(unittest.TestCase):
    def test_d3b_b22_path_allowlist(self):
        self.assertTrue(RUN.path_allowed("crates/quervant-core/src/search/unified.rs"))
        self.assertTrue(RUN.path_allowed("crates/quervant-core/tests/pr15i_d3_b.rs"))
        self.assertTrue(RUN.path_allowed("benchmarks/pr15i_d3_b/run.py"))
        self.assertTrue(RUN.path_allowed("docs/pr-artifacts/pr-15i-d3-b/preflight.md"))
        for path in (
            "crates/quervant-core/src/search/execute.rs",
            "crates/quervant-core/src/segment/reader.rs",
            "crates/quervant-core/src/segment/column.rs",
            "Cargo.lock",
            "Cargo.toml",
            "docs/pr-artifacts/pr-15i-d1-f/c2-performance.md",
        ):
            self.assertFalse(RUN.path_allowed(path), path)

    def test_d3b_b23_source_symbol_proof(self):
        policy = PROTOCOL["source_policy"]
        for symbol in policy["required_unified_symbols"]:
            self.assertIn(symbol, "request.top_k.limit == 100 RetainedKeyPrefilter D3B_FILTER_BITS "
                           "D3B_FILTER_WORDS D3B_MAX_ADMISSIONS "
                           "duplicate live document key across segments")
        self.assertEqual(
            RUN.rejected_design_symbols("fn retained_key_exists() {}", PROTOCOL),
            ["retained_key_exists"],
        )
        self.assertEqual(
            RUN.rejected_design_symbols("struct RetainedKeyFingerprintIndex;", PROTOCOL),
            ["RetainedKeyFingerprintIndex"],
        )
        self.assertEqual(RUN.rejected_design_symbols("fn doc_key_view() {}", PROTOCOL), ["doc_key_view"])
        self.assertEqual(RUN.rejected_design_symbols("struct RetainedKeyPrefilter;", PROTOCOL), [])

    def test_d3b_b24_index_sentinel(self):
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


class SlotAndSealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pr15i-d3bf12-tests-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _campaign_dir(self, slots: list[dict]) -> str:
        root = os.path.join(self.tmp, "campaign")
        os.makedirs(os.path.join(root, "raw", "slots"), exist_ok=True)
        for slot in slots:
            with open(os.path.join(root, "raw", "slots", f"slot-{slot['slot']:02d}.json"), "w", encoding="utf-8") as handle:
                import json

                json.dump(slot, handle)
        return root

    def _expected(self) -> dict:
        return {lane["id"]: {"total_hits": RUN.EXPECTED_TOTAL_HITS[lane["id"]], "doc_ids": []} for lane in LANES}

    def test_d3b_b25_missing_lane_and_reorder_rejected(self):
        slots = _slots({"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)})
        slots[0]["lanes"] = slots[0]["lanes"][:-1]
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._campaign_dir(slots), _manifest(), self._expected())
        slots = _slots({"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)})
        slots[0]["lanes"] = list(reversed(slots[0]["lanes"]))
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._campaign_dir(slots), _manifest(), self._expected())

    def test_d3b_b26_nonclear_contention_rejected(self):
        slots = _slots({"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)})
        slots[3]["contention_after"] = {"state": "busy", "reason_codes": ["cpu_load"]}
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._campaign_dir(slots), _manifest(), self._expected())

    def test_d3b_b27_oracle_tamper_rejected(self):
        slots = _slots({"A": _constant_arm(10_000_000), "B": _constant_arm(9_000_000)})
        slots[5]["lanes"][3]["total_hits"] += 1
        with self.assertRaises(VERIFY.VerifyError):
            VERIFY.verify_slots(self._campaign_dir(slots), _manifest(), self._expected())

    def test_d3b_b28_seal_tamper_inventory_and_traversal(self):
        root = os.path.join(self.tmp, "seal-fixture")
        os.makedirs(os.path.join(root, "raw", "slots"))
        members = {"raw/slots/slot-01.json": "one", "sanitized/summary.json": "two"}
        for relative, content in members.items():
            full = os.path.join(root, relative)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(content)
        files = {relative: VERIFY.sha256_file(os.path.join(root, relative)) for relative in members}
        seal = {"schema": "pr15i-d3bf12-seal-v1", "kind": "paired", "files": files}
        with open(os.path.join(root, "raw", "seal.json"), "w", encoding="utf-8") as handle:
            import json

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

    def test_d3b_b29_archive_round_trip_and_tamper(self):
        root = os.path.join(self.tmp, "campaign")
        for relative in (
            "build/A",
            "indexes/A-n10000",
            "corpus",
            "raw/slots",
            "sanitized",
        ):
            os.makedirs(os.path.join(root, relative))
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
        with self.assertRaises(RUN.D3BInvalid):
            RUN.write_archive(root, archive, members)
        tampered = dict(inventory)
        tampered["raw/slots/slot-01.json"] = "0" * 64
        with self.assertRaises(RUN.D3BBlocked):
            RUN.verify_archive(archive, tampered)
        evil = os.path.join(self.tmp, "evil.tar.gz")
        with tarfile.open(evil, "w:gz") as tar:
            data = b"evil"
            info = tarfile.TarInfo("../escape.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(RUN.D3BBlocked):
            RUN.verify_archive(evil, {"../escape.txt": RUN.sha256_bytes(b"evil")})

    def test_d3b_b30_existing_outputs_refused(self):
        existing = os.path.join(self.tmp, "existing.json")
        RUN.write_exclusive_json(existing, {"ok": True})
        with self.assertRaises(FileExistsError):
            RUN.write_exclusive_json(existing, {"ok": False})


class CliContractTests(unittest.TestCase):
    def test_d3b_b31_help_works(self):
        parser = RUN.build_parser()
        for command in ("preflight", "paired", "verify", "publish"):
            with self.assertRaises(SystemExit):
                parser.parse_args([command, "--help"])

    def test_d3b_b32_default_preflight_campaign_and_negative_inputs(self):
        parser = RUN.build_parser()
        args = parser.parse_args(
            [
                "preflight",
                "--base-tree", "/abs/base",
                "--base-sha", "a" * 40,
                "--candidate-tree", "/abs/candidate",
                "--candidate-sha", "b" * 40,
                "--out", "/abs/out.json",
            ]
        )
        self.assertEqual(args.campaign, "d3bf12-base-01")
        with self.assertRaises(SystemExit):
            parser.parse_args(["paired", "--out", "relative"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["publish"])


if __name__ == "__main__":
    unittest.main()


class PairedOrchestrationTests(unittest.TestCase):
    """Synthetic wiring test for cmd_paired: real file ordering, fake builds/slots."""

    def setUp(self):
        os.makedirs(RUN.target_root(), exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix="pr15i-d3bf12-1-wire-", dir=RUN.target_root())
        self.out = os.path.join(self.tmp, "d3bf12-base-aa-01")
        self.saved = {}
        self.tooling = os.path.join(self.tmp, "tooling")
        os.makedirs(self.tooling)
        with open(os.path.join(self.tooling, "tooling_manifest.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")

    def tearDown(self):
        import shutil

        for name, value in self.saved.items():
            setattr(RUN, name, value)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, name, value):
        self.saved[name] = getattr(RUN, name)
        setattr(RUN, name, value)

    def test_control_campaign_wiring_and_seal(self):
        protocol = RUN.PROTOCOL
        protocol_sha = "4" * 64
        lanes = RUN.lane_descriptors(protocol)
        self._patch("tooling_dir", lambda: self.tooling)
        self._patch("load_protocol", lambda: (protocol, protocol_sha))
        self._patch("assert_tooling_clean", lambda: None)
        self._patch("resolve_tree", lambda path, sha, role: {"tree": path, "sha": sha})
        self._patch("verify_frozen_inputs", lambda tree, label: None)
        self._patch(
            "source_fingerprints",
            lambda tree: {"crates/quervant-core/src/search/unified.rs": "f" * 64},
        )
        self._patch("collect_environment", lambda: {
            "kernel": "k", "machine": "x86_64", "cpu_model": "cpu", "cpu_count": 12,
            "filesystem": "ext4", "native_filesystem": True, "allowed_cpus": [0, 1],
            "toolchains": {"rustc": "r", "cargo": "c", "python3": "p"},
        })
        self._patch("affinity_plan", lambda: (1, 0))
        self._patch("pin_controller", lambda cpu: None)
        import hashlib

        binary_sha = hashlib.sha256(b"adapter").hexdigest()

        def fake_build(canonical, campaign_dir, arm, expected, protocol, protocol_sha):
            target = os.path.join(campaign_dir, "build", arm)
            os.makedirs(os.path.join(target, "release"), exist_ok=False)
            binary = os.path.join(target, "release", RUN.ADAPTER_BINARY)
            with open(binary, "wb") as handle:
                handle.write(b"adapter")
            return {
                "build_id": f"{arm}-1",
                "arm": arm,
                "expected_source_sha": expected,
                "pre_checkout_sha": expected,
                "post_checkout_sha": expected,
                "pre_source_sha256": "f" * 64,
                "post_source_sha256": "f" * 64,
                "source_tree_clean": True,
                "command_argv": [], "cwd": canonical, "manifest_path": canonical,
                "target_dir": target, "canonical_source": canonical,
                "binary_path": binary, "binary_sha256": binary_sha, "binary_bytes": 7,
                "exit_status": 0, "started_utc": "t0", "ended_utc": "t1",
                "duration_seconds": 1.0,
                "toolchain": {"rustc": "r", "cargo": "c"},
                "build_environment": {}, "environment_fingerprint": "e" * 64,
                "codegen_flags": {"forbidden_present": [], "profile": "release", "locked": True},
                "canonical_build_mode": "ONE_PATH_SEQUENTIAL_CHECKOUT",
                "protocol_sha256": protocol_sha,
            }

        self._patch("build_adapter", fake_build)

        def fake_worktree(campaign_dir, sha, protocol):
            path = os.path.join(campaign_dir, "compile-source")
            os.makedirs(path, exist_ok=False)
            return path

        self._patch("make_canonical_worktree", fake_worktree)

        def fake_host(campaign_dir, canonical, controller, adapter, environment, protocol_sha):
            record = {
                "schema": RUN.SCHEMA_HOST_ATTESTATION,
                "protocol_sha256": protocol_sha,
                "kernel": "k", "machine": "x86_64", "cpu_model": "cpu", "cpu_count": 12,
                "allowed_cpus_before_pin": [0, 1],
                "controller_cpu": controller, "adapter_cpu": adapter,
                "controller_affinity_after_pin": [controller],
                "filesystems": [
                    {"role": role, "path": f"/{role}", "harness_fstype": "ext4", "findmnt_fstype": "ext4"}
                    for role in ("repository", "campaign_output", "compile_source", "target_A", "target_B", "corpus", "indexes")
                ],
                "native_filesystem": True,
                "toolchains": environment["toolchains"],
                "recorded_utc": "t",
            }
            record["host_fingerprint"] = RUN.host_fingerprint(record)
            return record

        self._patch("collect_host_attestation", fake_host)
        self._patch("measure_host_readiness", lambda campaign, adapter, controller, fingerprint, protocol, protocol_sha: {
            "schema": RUN.SCHEMA_HOST_READINESS,
            "protocol_sha256": protocol_sha,
            "campaign": campaign,
            "role_cpus": {"adapter": adapter, "controller": controller},
            "host_fingerprint": fingerprint,
            "readiness_status": "READY",
            "failure_codes": [],
            "queries_executed": 0,
        })

        def fake_corpus(campaign_dir, protocol):
            os.makedirs(os.path.join(campaign_dir, "corpus"), exist_ok=True)
            return {
                "dir": os.path.join(campaign_dir, "corpus"),
                "manifest_sha256": protocol["corpus_manifest_sha256"],
                "corpora": {},
                "expected_by_lane": {lane["id"]: {"total_hits": RUN.EXPECTED_TOTAL_HITS[lane["id"]], "doc_ids": []} for lane in lanes},
            }

        self._patch("prepare_corpus", fake_corpus)

        def fake_index(harness, oracle, binary, corpus_dir, campaign_dir, arm, n):
            index_dir = os.path.join(campaign_dir, "indexes", f"{arm}-n{n}")
            os.makedirs(index_dir, exist_ok=True)
            layout = {
                "committed_index_bytes": 15_747_551 if n == 100000 else 1,
                "stored_bytes": 1_661_455 if n == 100000 else 1,
                "stored_version": 1,
                "digest": f"digest-{n}",
                "files": [],
            }
            return {"n": n, "index_dir": index_dir, "build": {"index_bytes": layout["committed_index_bytes"]}, "layout": layout}

        self._patch("build_index_for_arm", fake_index)

        def fake_slot(harness, adapter_cpu, entry, campaign_dir, lanes, expected, arms, protocol):
            arm = entry["arm"]
            probe_dir = os.path.join(campaign_dir, "raw", "contention")
            os.makedirs(probe_dir, exist_ok=True)
            for stage in ("before", "after"):
                with open(os.path.join(probe_dir, f"slot-{entry['slot']:02d}-{stage}.json"), "w", encoding="utf-8") as handle:
                    json.dump({"state": "clear", "reason_codes": []}, handle)
            return {
                "schema": RUN.SCHEMA_SLOT,
                "slot": entry["slot"], "block": entry["block"], "position": entry["position"], "arm": arm,
                "source_sha": arms[arm]["source_sha"], "binary_sha256": arms[arm]["binary_sha256"],
                "index_digests": {str(n): item["layout"]["digest"] for n, item in arms[arm]["indices"].items()},
                "started_utc": "t", "ended_utc": "t",
                "contention_before": {"state": "clear", "reason_codes": []},
                "contention_after": {"state": "clear", "reason_codes": []},
                "controller_affinity_before": [1], "controller_affinity_after": [1],
                "lanes": [
                    {
                        "id": lane["id"], "n": lane["n"], "class": lane["class"], "field": lane["field"],
                        "term": lane["term"], "k": lane["k"], "regime": "warm",
                        "warmups": 5, "warmup_ids": ["w"] * 5,
                        "samples_ns": [10_000_000] * 20,
                        "summary_ns": {"count": 20, "median": 10_000_000},
                        "total_hits": RUN.EXPECTED_TOTAL_HITS[lane["id"]],
                        "doc_ids": [], "expected_total_hits": RUN.EXPECTED_TOTAL_HITS[lane["id"]],
                        "expected_doc_ids": [], "oracle_ok": True,
                        "adapter_pid": 1, "adapter_affinity_before": [0],
                        "adapter_affinity_after": [0],
                        "affinity_capture_stages": ["pre_warmup", "post_timed_sample_20"],
                    }
                    for lane in lanes
                ],
            }

        self._patch("run_slot", fake_slot)

        args = argparse.Namespace(
            campaign="d3bf12-base-aa-01",
            out=self.out,
            base_tree="/base",
            base_sha=RUN.BASE_SHA,
            candidate_tree="/control-base",
            candidate_sha=RUN.BASE_SHA,
            idle_confirmed=True,
        )
        self.assertEqual(RUN.cmd_paired(args), 0)
        for relative in (
            "authorization.json",
            "manifest.json",
            "raw/build-provenance.json",
            "raw/host-attestation.json",
            "raw/setup/corpus.json",
            "sanitized/summary.json",
            "raw/seal.json",
        ):
            self.assertTrue(os.path.isfile(os.path.join(self.out, relative)), relative)
        manifest = json.load(open(os.path.join(self.out, "manifest.json"), encoding="utf-8"))
        self.assertEqual(manifest["environment_fingerprint"], manifest["environment"]["host_fingerprint"])
        provenance = json.load(open(os.path.join(self.out, "raw", "build-provenance.json"), encoding="utf-8"))
        self.assertTrue(provenance["aa_identical"])
        self.assertEqual(len(provenance["events"]), 2)
        seal = json.load(open(os.path.join(self.out, "raw", "seal.json"), encoding="utf-8"))
        self.assertIn("raw/build-provenance.json", seal["files"])
        self.assertIn("raw/host-attestation.json", seal["files"])
        summary = json.load(open(os.path.join(self.out, "sanitized", "summary.json"), encoding="utf-8"))
        self.assertEqual(summary["status"], "CONTROL_QUALIFIED")
        self.assertEqual(summary["structural"]["build_provenance"], "PASS")

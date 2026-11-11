#!/usr/bin/env python3
"""Targeted verifier tests for PR 15I-D3-A (VT-07..VT-30)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name):
    path = os.path.join(ROOT, "benchmarks", "pr15i_d3a", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"d3a_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("run")
verify = _load("verify")

BINARY = "a" * 64
DERIVATIVE = "b" * 64
INDEX = "c" * 64


def expected_match_samples(matched: int, protocol: dict) -> int:
    if matched < protocol["match_insert_min_n"]:
        return 0
    return (matched - protocol["match_insert_min_n"]) // protocol["match_insert_stride"] + 1


def valid_payload(hits: int = 2000, protocol: dict | None = None, n: int | None = None):
    protocol = protocol or verify.load_protocol()
    n = hits if n is None else n
    stage = [0] * 25
    stage[0] = 100
    stage[1] = 100
    stage[2] = 100
    stage[3] = 100
    stage[4] = 1000
    stage[5] = 500000
    stage[6] = 100
    stage[7] = 400
    stage[8] = 300
    stage[9] = 200
    stage[10] = 80
    stage[11] = 30
    stage[12] = 60
    stage[13] = 50
    stage[14] = 20
    stage[15] = 25
    stage[17] = 1000
    stage[18] = 400
    stage[19] = 100
    stage[20] = 50
    stage[21] = 100
    stage[22] = 50
    stage[23] = 100
    stage[24] = 100
    first, steady = verify.expected_sample_counts(n, protocol)
    total = first + steady
    stage[16] = 0
    match = expected_match_samples(n, protocol)
    engine = stage[0] + stage[1] + stage[2] + stage[3] + stage[4] + stage[5] + stage[6] + 50
    counters = [
        hits, hits, hits, hits, hits, 0 if hits == 0 else 1,
        first, steady, total, 0, total, 0, 0, match, total,
    ]
    segments = [[n, first, steady, match]]
    strata_ns = [[0] * 8, [stage[17], stage[18], stage[19], stage[20], stage[21], stage[22], stage[23], stage[24]]]
    strata_count = [first, steady]
    return {
        "engine_ns": engine,
        "stages": stage,
        "counters": counters,
        "segments": segments,
        "strata_ns": strata_ns,
        "strata_count": strata_count,
        "segments_unsupported": False,
        "expected_hits": hits,
        "top_k": 100,
    }


def decompose(payload, protocol=None):
    protocol = protocol or verify.load_protocol()
    return verify.decompose(
        payload["engine_ns"], payload["stages"], payload["counters"],
        payload["segments"], payload["strata_ns"], payload["strata_count"],
        payload["segments_unsupported"], payload["expected_hits"],
        payload["top_k"], protocol,
    )


def lane_hits(lane_id):
    parts = lane_id.split("/")
    return {"absent": 0, "rare": 1, "medium": 12500, "common": 49999}[parts[2]]


def lane_record(lane_id, samples, probe=False, protocol=None):
    protocol = protocol or verify.load_protocol()
    hits = lane_hits(lane_id)
    n = hits
    payload = valid_payload(hits=hits, protocol=protocol, n=n)
    return {
        "id": lane_id,
        "warmups": 5,
        "samples_ns": samples,
        "expected_total_hits": hits,
        "observed_total_hits": hits,
        "doc_ids": [],
        "stage_samples": [payload["stages"] for _ in samples] if probe else None,
        "counter_samples": [payload["counters"] for _ in samples] if probe else None,
        "segment_samples": [payload["segments"] for _ in samples] if probe else None,
        "strata_ns_samples": [payload["strata_ns"] for _ in samples] if probe else None,
        "strata_count_samples": [payload["strata_count"] for _ in samples] if probe else None,
        "segments_unsupported_samples": [False for _ in samples] if probe else None,
    }


def slot_record(entry, protocol, kind):
    arm = entry["arm"]
    probe = arm == "P"
    lanes = [
        lane_record(lane_id, [1_000_000 + index] * 20, probe=probe, protocol=protocol)
        for index, lane_id in enumerate(protocol["lane_ids"])
    ]
    return {
        "schema": "pr15i-d3a-slot-v1",
        "slot": entry["slot"],
        "block": entry["block"],
        "position": entry["position"],
        "arm": arm,
        "base_sha": verify.BASE_SHA,
        "diagnostic_derivative_sha256": (
            DERIVATIVE if (kind == "paired" and arm in ("Q", "P")) else None
        ),
        "binary_sha256": BINARY,
        "index_sha256": INDEX,
        "lane_ids": protocol["lane_ids"],
        "lanes": lanes,
        "contention_before": "clear",
        "contention_after": "clear",
    }


def oracle_lanes(protocol):
    return {
        lane_id: {"total_hits": lane_hits(lane_id), "doc_ids": []}
        for lane_id in protocol["lane_ids"]
    }


def write_campaign(root, protocol, kind):
    name = protocol["control_campaign"] if kind == "control" else protocol["campaigns"][0]
    campaign = os.path.join(root, name)
    plan = verify.control_schedule(protocol) if kind == "control" else verify.slot_schedule(protocol)
    os.makedirs(os.path.join(campaign, "raw", "slots"), exist_ok=True)
    for entry in plan:
        path = os.path.join(campaign, "raw", "slots", f"slot-{entry['slot']:02d}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(slot_record(entry, protocol, kind), handle)
    return campaign, plan


class SampleShapeTests(unittest.TestCase):
    """VT-14 and the fixed 25/15/segment/strata schema."""

    def test_stage_counter_and_strata_shapes(self):
        protocol = verify.load_protocol()
        verify.strict_array(valid_payload(protocol=protocol)["stages"], 25, "stage")
        verify.strict_array(valid_payload(protocol=protocol)["counters"], 15, "counter")
        for bad in (
            [True] * 25,
            [1.5] * 25,
            [-1] + [0] * 24,
            [0] * 24,
        ):
            with self.assertRaises(verify.VerifyError):
                verify.strict_array(bad, 25, "stage")

    def test_pair_arrays_reject_reordered_and_duplicate_names(self):
        protocol = verify.load_protocol()
        pairs = [[name, 0] for name in protocol["stages"]]
        run._stage_pairs_to_arrays(pairs)
        with self.assertRaises(run.D3AInvalid):
            run._stage_pairs_to_arrays(list(reversed(pairs)))
        bad = [list(item) for item in pairs]
        bad[1][0] = bad[0][0]
        with self.assertRaises(run.D3AInvalid):
            run._stage_pairs_to_arrays(bad)
        with self.assertRaises(run.D3AInvalid):
            run._stage_pairs_to_arrays(pairs[:-1])
        counters = [[name, 0] for name in protocol["counters"]]
        run._counter_pairs_to_arrays(counters)
        with self.assertRaises(run.D3AInvalid):
            run._counter_pairs_to_arrays(counters[:-1])

    def test_segment_and_strata_validators(self):
        run._segment_descriptors([[10, 0, 0, 0]])
        for bad in ([[1, 2, 3]], [[True, 0, 0, 0]], [[-1, 0, 0, 0]], [[1, 2, 3, 4]] * 33):
            with self.assertRaises(run.D3AInvalid):
                run._segment_descriptors(bad)
        run._strata_ns([[0] * 8, [0] * 8])
        with self.assertRaises(run.D3AInvalid):
            run._strata_ns([[0] * 8])
        with self.assertRaises(run.D3AInvalid):
            run._strata_ns([[0] * 7, [0] * 8])
        self.assertEqual(run._strata_count([0, 0]), [0, 0])
        with self.assertRaises(run.D3AInvalid):
            run._strata_count([0])


class DecomposeTests(unittest.TestCase):
    """VT-09, VT-10, VT-15, VT-16, VT-17 and counter checks."""

    def test_valid_partition_is_accepted(self):
        sample = decompose(valid_payload())
        self.assertTrue(sample["partition_ok"])
        self.assertEqual(sample["reconstructed_ns"], sample["engine_ns"])

    def test_child_over_candidate_parent_is_flagged(self):
        payload = valid_payload()
        payload["stages"][24] = 200_000
        payload["strata_ns"][1][7] = 200_000
        sample = decompose(payload)
        self.assertFalse(sample["partition_ok"])
        self.assertTrue(sample["candidate_violation"])

    def test_candidate_sample_over_candidate_stage_is_flagged(self):
        payload = valid_payload()
        payload["stages"][17] = 1_000_000
        payload["strata_ns"][1][0] = 1_000_000
        payload["stages"][18] = 1_000_000
        payload["strata_ns"][1][1] = 1_000_000
        sample = decompose(payload)
        self.assertTrue(sample["candidate_over_parent"])

    def test_score_children_over_parent_is_flagged(self):
        payload = valid_payload()
        payload["stages"][10] = 200_000
        sample = decompose(payload)
        self.assertTrue(sample["score_violation"])
        self.assertFalse(sample["partition_ok"])

    def test_evaluate_children_over_parent_is_flagged(self):
        payload = valid_payload()
        payload["stages"][13] = 20_000
        sample = decompose(payload)
        self.assertTrue(sample["evaluate_violation"])
        self.assertFalse(sample["partition_ok"])

    def test_top_level_partition_overflow_is_flagged(self):
        payload = valid_payload()
        payload["stages"][6] = 2_000_000
        sample = decompose(payload)
        self.assertTrue(sample["top_violation"])
        self.assertFalse(sample["partition_ok"])

    def test_intermediate_disjoint_sum_excludes_nested_score(self):
        payload = valid_payload()
        payload["stages"][4] = 300_000
        payload["stages"][9] = 200_000
        payload["stages"][12] = 100_000
        payload["engine_ns"] = sum(payload["stages"][:7]) + 50
        sample = decompose(payload)
        self.assertTrue(sample["partition_ok"])
        self.assertEqual(sample["intermediate_disjoint_ns"], 80 + 20 + 50 + 25)

    def test_strata_totals_off_by_one_are_rejected(self):
        payload = valid_payload()
        payload["strata_ns"][1][1] += 1
        with self.assertRaises(verify.VerifyError):
            decompose(payload)

    def test_counter_mismatch_is_rejected(self):
        payload = valid_payload()
        payload["counters"][3] += 1
        with self.assertRaises(verify.VerifyError):
            decompose(payload)

    def test_sampling_descriptor_mismatch_is_flagged(self):
        payload = valid_payload()
        payload["segments"][0][1] += 1
        sample = decompose(payload)
        self.assertTrue(sample["sampling_violation"])

    def test_segment_unsupported_blocks_substage_support(self):
        payload = valid_payload()
        payload["segments_unsupported"] = True
        sample = decompose(payload)
        self.assertTrue(sample["sampling_violation"])


class SamplingFormulaTests(unittest.TestCase):
    """VT-11 and VT-12."""

    def test_first_and_steady_counts(self):
        protocol = verify.load_protocol()
        table = {
            0: (0, 0), 1: (0, 0), 127: (0, 0), 511: (0, 0),
            512: (128, 6), 513: (128, 7), 12500: (128, 194), 50000: (128, 780),
        }
        for n, expected in table.items():
            self.assertEqual(verify.expected_sample_counts(n, protocol), expected)

    def test_two_small_segments_get_no_samples(self):
        payload = valid_payload(hits=1000)
        payload["segments"] = [[500, 0, 0, 0], [500, 0, 0, 0]]
        payload["counters"][6] = 0
        payload["counters"][7] = 0
        payload["counters"][8] = 0
        payload["counters"][10] = 0
        payload["counters"][12] = 0
        payload["counters"][13] = 0
        payload["counters"][14] = 0
        payload["stages"][16] = 0
        payload["stages"][17] = 0
        for index in range(18, 25):
            payload["stages"][index] = 0
        payload["strata_ns"] = [[0] * 8, [0] * 8]
        payload["strata_count"] = [0, 0]
        sample = decompose(payload)
        self.assertTrue(sample["partition_ok"])
        self.assertEqual(sample["counters"]["candidate_samples_first"], 0)
        self.assertEqual(sample["counters"]["candidate_samples_steady"], 0)

    def test_one_eligible_segment_gets_samples(self):
        payload = valid_payload(hits=1000)
        sample = decompose(payload)
        self.assertEqual(sample["counters"]["candidate_samples_first"], 128)
        self.assertEqual(sample["counters"]["candidate_samples_steady"], 14)


class SlotLoaderTests(unittest.TestCase):
    """VT-05, VT-06, VT-07 and VT-22."""

    def test_slot_loader_accepts_valid_p_and_rejects_probe_fields_in_q(self):
        protocol = verify.load_protocol()
        root = tempfile.mkdtemp(prefix="d3a-slots-")
        try:
            campaign, plan = write_campaign(root, protocol, "paired")
            records = verify.load_slots(campaign, protocol, oracle_lanes(protocol))
            self.assertEqual(len(records), len(plan))
            target = next(entry for entry in plan if entry["arm"] == "Q")
            path = os.path.join(campaign, "raw", "slots", f"slot-{target['slot']:02d}.json")
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
            record["lanes"][0]["stage_samples"] = [valid_payload(protocol=protocol)["stages"]] * 20
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            with self.assertRaises(verify.VerifyError):
                verify.load_slots(campaign, protocol, oracle_lanes(protocol))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_p_missing_segments_is_rejected(self):
        protocol = verify.load_protocol()
        root = tempfile.mkdtemp(prefix="d3a-slots-")
        try:
            campaign, plan = write_campaign(root, protocol, "paired")
            target = next(entry for entry in plan if entry["arm"] == "P")
            path = os.path.join(campaign, "raw", "slots", f"slot-{target['slot']:02d}.json")
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
            record["lanes"][0]["segment_samples"] = None
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            with self.assertRaises(verify.VerifyError):
                verify.load_slots(campaign, protocol, oracle_lanes(protocol))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_changed_oracle_doc_ids_are_rejected(self):
        protocol = verify.load_protocol()
        root = tempfile.mkdtemp(prefix="d3a-slots-")
        try:
            campaign, _plan = write_campaign(root, protocol, "paired")
            oracle = oracle_lanes(protocol)
            oracle[protocol["lane_ids"][0]]["doc_ids"] = ["tampered"]
            with self.assertRaises(verify.VerifyError):
                verify.load_slots(campaign, protocol, oracle)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ClassificationTests(unittest.TestCase):
    """VT-19 and VT-20."""

    def _control_timing(self, ratios):
        ordered = sorted(ratios)
        median = (ordered[1] + ordered[2]) / 2
        return {
            "lane": {
                "class": "common",
                "kind": "medium_common",
                "campaign": {"a1_a2": median},
                "blocks": [
                    {"block": index, "a1_a2": value}
                    for index, value in enumerate(ratios, start=1)
                ],
            }
        }

    def test_control_drift_boundaries_are_inclusive(self):
        protocol = verify.load_protocol()
        for values, expected in (
            ([0.849999] * 4, "D3A_CONTROL_NOT_QUALIFIED"),
            ([0.85] * 4, "D3A_CONTROL_QUALIFIED"),
            ([1.15] * 4, "D3A_CONTROL_QUALIFIED"),
            ([1.150001] * 4, "D3A_CONTROL_NOT_QUALIFIED"),
        ):
            result = verify.recompute_classification(
                self._control_timing(values), protocol, "control"
            )
            self.assertEqual(result["status"], expected)

    def _paired_timing(self, q_a, p_q, drift=1.0):
        return {
            "lane": {
                "class": "common",
                "kind": "medium_common",
                "campaign": {"q_a": q_a, "p_q": p_q, "p_a": q_a * p_q, "a_a_drift": drift},
                "blocks": [
                    {"block": block, "q_a": q_a, "p_q": p_q, "p_a": q_a * p_q, "a_a_drift": drift}
                    for block in range(1, 5)
                ],
            }
        }

    def test_intrusion_ceiling_is_inclusive(self):
        protocol = verify.load_protocol()
        self.assertEqual(
            verify.recompute_classification(
                self._paired_timing(1.10, 1.15), protocol, "paired"
            )["status"],
            "D3A_ATTRIBUTION_LOW_INTRUSION",
        )
        self.assertEqual(
            verify.recompute_classification(
                self._paired_timing(1.100001, 1.15), protocol, "paired"
            )["status"],
            "D3A_DIAGNOSTIC_PERTURBED",
        )
        self.assertEqual(
            verify.recompute_classification(
                self._paired_timing(1.0, 1.150001), protocol, "paired"
            )["status"],
            "D3A_DIAGNOSTIC_PERTURBED",
        )

    def test_single_block_guard_blocks_any_block_above_one_and_a_half(self):
        protocol = verify.load_protocol()
        timing = self._paired_timing(1.0, 1.0)
        timing["lane"]["blocks"][2]["p_q"] = 1.50
        self.assertEqual(
            verify.recompute_classification(timing, protocol, "paired")["status"],
            "D3A_ATTRIBUTION_LOW_INTRUSION",
        )
        timing["lane"]["blocks"][2]["p_q"] = 1.500001
        self.assertEqual(
            verify.recompute_classification(timing, protocol, "paired")["status"],
            "D3A_DIAGNOSTIC_PERTURBED",
        )


def metric_sample(
    engine,
    candidate,
    intermediate,
    parent,
    children,
    first=0,
    steady=1,
    fallback=0,
    overrides=None,
):
    overrides = overrides or {}
    stage = {
        name: 0
        for name in (
            "candidate", "candidate_sample", "score_map", "score_owner",
            "score_accumulate", "score_vector", "scored_vec_build",
            "matched_reserve", "temp_release", "leaf", "membership",
            "key", "sort_view", "sort_charge", "duplicate", "compare",
            "materialize", "heap", "match_insert_sample", "evaluate",
        )
    }
    stage["candidate"] = candidate
    stage["candidate_sample"] = parent
    stage.update(overrides)
    return {
        "engine_ns": engine,
        "stage": stage,
        "intermediate_disjoint_ns": intermediate,
        "strata_ns": [[0] * 8, [parent] + list(children)],
        "counters": {
            "candidate_samples_first": first,
            "candidate_samples_steady": steady,
            "candidate_samples_fallback": fallback,
            "match_insert_samples": 0,
        },
        "candidate_residual_ns": max(0, parent - sum(children)),
    }


def make_metrics(
    protocol,
    lane_id,
    *,
    engine=25_000_000,
    candidate=3_500_000,
    children=(5, 5, 5, 50, 5, 5, 5),
    intermediate=7_000_000,
    overrides=None,
):
    defaults = {
        "score_map": 4_000_000,
        "scored_vec_build": 1_000_000,
        "matched_reserve": 1_000_000,
        "temp_release": 1_000_000,
    }
    if overrides:
        defaults.update(overrides)
    samples = [
        metric_sample(engine, candidate, intermediate, 100, list(children), overrides=defaults)
        for _ in range(20)
    ]
    return verify._lane_metrics(samples, {"id": lane_id}, protocol)


def make_run(protocol, name, priority_overrides):
    lanes = {}
    for lane in verify.lane_descriptors(protocol):
        lane_id = lane["id"]
        if lane_id in priority_overrides:
            lanes[lane_id] = make_metrics(protocol, lane_id, **priority_overrides[lane_id])
        else:
            lanes[lane_id] = make_metrics(
                protocol,
                lane_id,
                engine=10_000_000,
                candidate=0,
                children=(0, 0, 0, 0, 0, 0, 0),
                intermediate=0,
            )
    return {"campaign": name, "stage_summary": {"lanes": lanes}}


def five_runs(protocol, per_run_overrides):
    names = protocol["campaigns"]
    return [
        make_run(protocol, names[index], per_run_overrides[index])
        for index in range(5)
    ]


class StatisticsTests(unittest.TestCase):
    """F-ST01..F-ST04: run-level median and MAD."""

    def test_median_and_mad_examples(self):
        self.assertEqual(verify._median5([1, 2, 3, 4, 100]), 3)
        self.assertEqual(verify._mad5([1, 2, 3, 4, 100]), 1)
        self.assertEqual(verify._median5([7, 7, 7, 7, 7]), 7)
        self.assertEqual(verify._mad5([7, 7, 7, 7, 7]), 0)

    def test_zero_values_do_not_divide_by_zero(self):
        self.assertEqual(verify._mad5([0, 0, 0, 0, 0]), 0)

    def test_fraction_stat_is_exact(self):
        values = [Fraction(8, 100), Fraction(8, 100), Fraction(10, 100), Fraction(14, 100), Fraction(14, 100)]
        stat = verify._stat(values, fraction=True)
        self.assertEqual(stat["median_exact"], [1, 10])
        self.assertEqual(stat["mad_exact"], [1, 50])

    def test_exact_share_threshold_ignores_display_rounding(self):
        below = Fraction(11999999, 100000000)
        at = Fraction(12, 100)
        self.assertLess(below, Fraction(12, 100))
        self.assertGreaterEqual(at, Fraction(12, 100))
        self.assertEqual(round(float(below), 2), 0.12)
        self.assertEqual(round(float(at), 2), 0.12)


class PriorityTests(unittest.TestCase):
    """F-PR01..F-PR10: five-run persistence and precedence."""

    def _overrides(self, protocol, candidate=True, child_dominant=True, intermediate=False, largest="score_map"):
        material = {
            "engine": 25_000_000,
            "candidate": 3_500_000 if candidate else 0,
            "children": (5, 5, 5, 50, 5, 5, 5) if child_dominant else (25, 21, 11, 11, 11, 11, 10),
            "intermediate": 7_000_000 if intermediate else 0,
        }
        if intermediate:
            material["overrides"] = {
                "score_map": 4_000_000 if largest == "score_map" else 1_000_000,
                "scored_vec_build": 1_000_000,
                "matched_reserve": 4_000_000 if largest == "matched_reserve" else 1_000_000,
                "temp_release": 1_000_000,
            }
        return {lane: dict(material) for lane in protocol["candidate_priority"]["lanes"]}

    def test_four_of_five_stable_candidate_with_shared_child_localizes(self):
        protocol = verify.load_protocol()
        overrides = [self._overrides(protocol) for _ in range(5)]
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        decision = verify.five_run_decision(stats, protocol)
        self.assertEqual(decision["verdict"], "D3A_CANDIDATE_HOTSPOT_LOCALIZED")
        self.assertEqual(decision["candidate_localized_component"], "candidate_duplicate")

    def test_three_of_five_is_not_stable(self):
        protocol = verify.load_protocol()
        good = self._overrides(protocol)
        bad = self._overrides(protocol, candidate=False)
        overrides = [good, good, good, bad, bad]
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        decision = verify.five_run_decision(stats, protocol)
        self.assertNotEqual(decision["verdict"], "D3A_CANDIDATE_HOTSPOT_LOCALIZED")

    def test_three_of_five_with_high_medians_is_not_stable(self):
        protocol = verify.load_protocol()
        good = self._overrides(protocol)
        bad = self._overrides(protocol, candidate=False)
        overrides = [good, good, good, bad, bad]
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        lane = protocol["candidate_priority"]["lanes"][0]
        self.assertFalse(stats["lanes"][lane]["candidate_stable"])

    def test_exactly_four_of_five_at_share_boundary_is_stable(self):
        protocol = verify.load_protocol()
        boundary = self._overrides(protocol)
        boundary = {
            lane: {**value, "candidate": 3_000_000, "engine": 25_000_000}
            for lane, value in boundary.items()
        }
        missing = self._overrides(protocol, candidate=False)
        overrides = [boundary, boundary, boundary, boundary, missing]
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        lane = protocol["candidate_priority"]["lanes"][0]
        self.assertTrue(stats["lanes"][lane]["candidate_stable"])

    def test_different_children_across_lanes_is_unresolved(self):
        protocol = verify.load_protocol()
        primary = protocol["candidate_priority"]["lanes"]
        overrides = []
        for _ in range(5):
            item = self._overrides(protocol)
            item[primary[0]] = {**item[primary[0]], "children": (50, 5, 5, 5, 5, 5, 5)}
            item[primary[1]] = {**item[primary[1]], "children": (5, 5, 5, 50, 5, 5, 5)}
            item[primary[2]] = {**item[primary[2]], "children": (5, 5, 5, 5, 5, 50, 5)}
            overrides.append(item)
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        decision = verify.five_run_decision(stats, protocol)
        self.assertEqual(decision["verdict"], "D3A_CANDIDATE_STAGE_UNRESOLVED")

    def test_intermediate_priority_when_candidate_absent(self):
        protocol = verify.load_protocol()
        overrides = [
            self._overrides(protocol, candidate=False, child_dominant=False, intermediate=True)
            for _ in range(5)
        ]
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        decision = verify.five_run_decision(stats, protocol)
        self.assertEqual(decision["verdict"], "D3A_INTERMEDIATE_MATERIALIZATION_PRIORITY")
        self.assertEqual(decision["intermediate_localized_component"], "score_map")

    def test_candidate_precedence_over_intermediate(self):
        protocol = verify.load_protocol()
        overrides = [self._overrides(protocol, intermediate=True) for _ in range(5)]
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        decision = verify.five_run_decision(stats, protocol)
        self.assertEqual(decision["verdict"], "D3A_CANDIDATE_HOTSPOT_LOCALIZED")

    def test_no_actionable_hotspot(self):
        protocol = verify.load_protocol()
        overrides = [
            self._overrides(protocol, candidate=False, child_dominant=False, intermediate=False)
            for _ in range(5)
        ]
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        decision = verify.five_run_decision(stats, protocol)
        self.assertEqual(decision["verdict"], "D3A_NO_ACTIONABLE_HOTSPOT")

    def test_residual_above_thirty_percent_has_no_dominant_child(self):
        protocol = verify.load_protocol()
        overrides = [
            self._overrides(protocol) | {
                lane: {**self._overrides(protocol)[lane], "children": (5, 5, 5, 5, 5, 5, 5)}
                for lane in protocol["candidate_priority"]["lanes"]
            }
            for _ in range(5)
        ]
        stats = verify.five_run_stats(five_runs(protocol, overrides), protocol)
        decision = verify.five_run_decision(stats, protocol)
        self.assertEqual(decision["verdict"], "D3A_CANDIDATE_STAGE_UNRESOLVED")

    def test_five_run_stats_rejects_wrong_count(self):
        protocol = verify.load_protocol()
        overrides = [self._overrides(protocol) for _ in range(5)]
        runs = five_runs(protocol, overrides)
        with self.assertRaises(verify.VerifyError):
            verify.five_run_stats(runs[:4], protocol)
        with self.assertRaises(verify.VerifyError):
            verify.five_run_stats(runs + [runs[0]], protocol)


class AreaMappingTests(unittest.TestCase):
    """F-ME01/F-ME03/F-ME04/F-ME05: seven-area mapping stays disjoint."""

    def test_sampled_areas_use_disjoint_child_time(self):
        protocol = verify.load_protocol()
        sample = metric_sample(
            25_000_000,
            3_500_000,
            7_000_000,
            100,
            [5, 6, 7, 8, 9, 10, 11],
            overrides={
                "score_map": 4_000_000,
                "scored_vec_build": 1_000_000,
                "score_accumulate": 9_000_000,
                "matched_reserve": 1_000_000,
                "temp_release": 1_000_000,
            },
        )
        areas = verify._area_metrics([sample])
        self.assertEqual(areas["heap_compare_update"]["steady"]["ns"], 9 + 11)
        self.assertEqual(areas["scored_map_vector"]["ns"], 5_000_000)
        self.assertEqual(areas["scored_map_vector"]["share"], [1, 5])
        self.assertNotIn("score_accumulate", areas["scored_map_vector"])

    def test_zero_match_insert_samples_is_not_estimable(self):
        sample = metric_sample(1_000_000, 0, 0, 0, [0] * 7)
        areas = verify._area_metrics([sample])
        self.assertFalse(areas["match_set_construction"]["estimable"])
        self.assertEqual(areas["match_set_construction"]["samples"], 0)

    def test_sort_charge_is_kept_separate_from_sort_view(self):
        sample = metric_sample(
            25_000_000,
            3_500_000,
            7_000_000,
            100,
            [5, 6, 7, 8, 9, 10, 11],
        )
        areas = verify._area_metrics([sample])
        self.assertEqual(areas["sort_extraction"]["steady"]["ns"], 6)
        self.assertEqual(areas["sort_charge"]["steady"]["ns"], 7)


class SeriesIdentityTests(unittest.TestCase):
    """F-SE07/F-NE01: historical or unknown control names are rejected."""

    def test_v1_control_name_is_rejected(self):
        protocol = verify.load_protocol()
        with self.assertRaises(verify.VerifyError):
            verify._series_control(protocol, "target/pr15i-d3a/aa/d3a-base-aa-01", "/tmp")

    def test_retained_area_names_are_exact(self):
        protocol = verify.load_protocol()
        self.assertEqual(
            protocol["run_reported_areas"],
            [
                "document_key",
                "duplicate_detection",
                "sort_extraction",
                "heap_compare_update",
                "candidate_materialization",
                "match_set_construction",
                "scored_map_vector",
            ],
        )


class ManifestTests(unittest.TestCase):
    """F-NE02/F-NE03: v2 manifest covers the exact final tooling set."""

    def test_v2_manifest_matches_directory(self):
        manifest = verify.load_tooling_manifest()
        self.assertEqual(manifest["schema"], "pr15i-d3a-tooling-manifest-v2")


class SentinelAndBinaryTests(unittest.TestCase):
    """VT-21 and the binary identity contract."""

    def test_index_sentinel_mismatch_blocks(self):
        protocol = verify.load_protocol()
        layout = {
            "builds": {
                "A": {
                    "10000": {"digest": "d1"},
                    "100000": {
                        "digest": "d2",
                        "committed_index_bytes": protocol["100k_lz4_committed_index_sentinel"],
                        "stored_bytes": protocol["100k_lz4_stored_section_sentinel"] + 1,
                    },
                },
                "QP": {
                    "10000": {"digest": "d1"},
                    "100000": {
                        "digest": "d2",
                        "committed_index_bytes": protocol["100k_lz4_committed_index_sentinel"],
                        "stored_bytes": protocol["100k_lz4_stored_section_sentinel"],
                    },
                },
            }
        }
        failures = run.index_sentinel_failures(layout, protocol)
        self.assertTrue(any(item["gate"] == "STORED_SECTION_BYTES" for item in failures))

    def test_identical_a_qp_digest_blocks(self):
        protocol = verify.load_protocol()
        layout = {
            "builds": {
                "A": {
                    "10000": {"digest": "d1"},
                    "100000": {
                        "digest": "d2",
                        "committed_index_bytes": protocol["100k_lz4_committed_index_sentinel"],
                        "stored_bytes": protocol["100k_lz4_stored_section_sentinel"],
                    },
                },
                "QP": {
                    "10000": {"digest": "d9"},
                    "100000": {
                        "digest": "d2",
                        "committed_index_bytes": protocol["100k_lz4_committed_index_sentinel"],
                        "stored_bytes": protocol["100k_lz4_stored_section_sentinel"],
                    },
                },
            }
        }
        failures = run.index_sentinel_failures(layout, protocol)
        self.assertTrue(any(item["gate"] == "A_QP_INDEX_DIGEST" for item in failures))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Targeted verifier tests for PR 15I-D3-A (VT-07..VT-30)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest

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


def metric_sample(engine, candidate, intermediate, parent, children, first=0, steady=1, fallback=0):
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
    return {
        "engine_ns": engine,
        "stage": stage,
        "intermediate_disjoint_ns": intermediate,
        "strata_ns": [[0] * 8, [parent] + list(children)],
        "counters": {
            "candidate_samples_first": first,
            "candidate_samples_steady": steady,
            "candidate_samples_fallback": fallback,
        },
        "candidate_residual_ns": max(0, parent - sum(children)),
    }


class PriorityTests(unittest.TestCase):
    """VT-27, VT-28, VT-29 and VT-30."""

    def _lane(self, material, dominant=None, intermediate=False, largest=None):
        return {
            "candidate_material": material,
            "dominant_component": dominant,
            "intermediate_material": intermediate,
            "intermediate_largest_component": largest,
        }

    def _summary(self, mapping):
        return {"lanes": mapping}

    def test_candidate_materiality_boundaries_are_inclusive(self):
        protocol = verify.load_protocol()
        lane = {"id": "x"}
        samples = [metric_sample(25_000_000, 3_000_000, 0, 1000, [100] * 7) for _ in range(20)]
        self.assertTrue(verify._lane_metrics(samples, lane, protocol)["candidate_material"])
        samples = [metric_sample(25_000_000, 2_999_999, 0, 1000, [100] * 7) for _ in range(20)]
        self.assertFalse(verify._lane_metrics(samples, lane, protocol)["candidate_material"])
        samples = [metric_sample(25_000_001, 3_000_000, 0, 1000, [100] * 7) for _ in range(20)]
        self.assertFalse(verify._lane_metrics(samples, lane, protocol)["candidate_material"])

    def test_dominant_share_ratio_and_residual_boundaries(self):
        protocol = verify.load_protocol()
        lane = {"id": "x"}
        passing = metric_sample(50_000_000, 10_000_000, 0, 100, [25, 20, 10, 10, 10, 10, 15])
        metrics = verify._lane_metrics([passing] * 20, lane, protocol)
        self.assertEqual(metrics["dominant_component"], "candidate_key")
        unstable = metric_sample(50_000_000, 10_000_000, 0, 100, [25, 21, 11, 11, 11, 11, 10])
        self.assertIsNone(verify._lane_metrics([unstable] * 20, lane, protocol)["dominant_component"])
        residual_bad = metric_sample(50_000_000, 10_000_000, 0, 100, [25, 20, 5, 5, 5, 5, 4])
        self.assertIsNone(
            verify._lane_metrics([residual_bad] * 20, lane, protocol)["dominant_component"]
        )

    def test_localized_requires_two_shared_dominant_lanes_in_both_campaigns(self):
        protocol = verify.load_protocol()
        primary = protocol["candidate_priority"]["lanes"]
        first = self._summary(
            {lane: self._lane(True, "candidate_duplicate") for lane in primary}
        )
        second = self._summary(
            {lane: self._lane(True, "candidate_duplicate") for lane in primary}
        )
        result = verify.series_decision(first, second, protocol)
        self.assertEqual(result["verdict"], "D3A_CANDIDATE_HOTSPOT_LOCALIZED")

    def test_one_campaign_material_only_is_not_localized(self):
        protocol = verify.load_protocol()
        primary = protocol["candidate_priority"]["lanes"]
        first = self._summary(
            {
                primary[0]: self._lane(True, "candidate_duplicate"),
                primary[1]: self._lane(True, "candidate_duplicate"),
                primary[2]: self._lane(False),
            }
        )
        second = self._summary(
            {lane: self._lane(False) for lane in primary}
        )
        result = verify.series_decision(first, second, protocol)
        self.assertEqual(result["verdict"], "D3A_NO_ACTIONABLE_HOTSPOT")

    def test_intermediate_priority_is_used_when_candidate_is_unresolved(self):
        protocol = verify.load_protocol()
        primary = protocol["candidate_priority"]["lanes"]
        first = self._summary(
            {
                primary[0]: self._lane(True, None),
                primary[1]: self._lane(True, None),
                primary[2]: self._lane(False, None, True, "score_map"),
            }
        )
        second = self._summary(
            {
                primary[0]: self._lane(True, None),
                primary[1]: self._lane(True, None),
                primary[2]: self._lane(False, None, True, "score_map"),
            }
        )
        # Only one lane has intermediate input, so the intermediate gate fails and
        # the candidate storm remains unresolved.
        result = verify.series_decision(first, second, protocol)
        self.assertEqual(result["verdict"], "D3A_CANDIDATE_STAGE_UNRESOLVED")

    def test_intermediate_priority_requires_same_largest_component(self):
        protocol = verify.load_protocol()
        primary = protocol["candidate_priority"]["lanes"]
        first = self._summary(
            {
                lane: self._lane(False, None, True, "score_map") for lane in primary
            }
        )
        second = self._summary(
            {
                lane: self._lane(False, None, True, "score_map") for lane in primary
            }
        )
        result = verify.series_decision(first, second, protocol)
        self.assertEqual(result["verdict"], "D3A_INTERMEDIATE_MATERIALIZATION_PRIORITY")
        second = self._summary(
            {
                primary[0]: self._lane(False, None, True, "score_map"),
                primary[1]: self._lane(False, None, True, "matched_reserve"),
                primary[2]: self._lane(False, None, True, "score_map"),
            }
        )
        result = verify.series_decision(first, second, protocol)
        self.assertEqual(result["verdict"], "D3A_NO_ACTIONABLE_HOTSPOT")


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

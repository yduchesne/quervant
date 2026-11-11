#!/usr/bin/env python3
"""Independent-verifier tests for the PR 15I-D2-A tooling (BT matrix subset)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"d2a_{name}", os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("run")
verify = _load("verify")

BINARY = "a" * 64
DERIVATIVE = "b" * 64
INDEX = "c" * 64


def lane_hits(lane_id):
    parts = lane_id.split("/")
    return {"absent": 0, "rare": 1, "medium": 12500, "common": 49999}[parts[2]]


def valid_stage():
    return [1000, 1000, 1000, 1000, 500000, 1000, 1000, 100000, 50000, 200000, 20000, 30000, 100000]


def valid_counters(hits):
    return [hits, hits, hits, hits, hits, 0 if hits == 0 else 1]


def lane_record(lane_id, samples, probe=False):
    hits = lane_hits(lane_id)
    record = {
        "id": lane_id,
        "warmups": 5,
        "samples_ns": samples,
        "expected_total_hits": hits,
        "observed_total_hits": hits,
        "doc_ids": [],
        "stage_samples": [valid_stage() for _ in samples] if probe else None,
        "counter_samples": [valid_counters(hits) for _ in samples] if probe else None,
    }
    return record


def slot_record(entry, protocol, kind):
    arm = entry["arm"]
    probe = arm == "P"
    lanes = [
        lane_record(lane_id, [1_000_000 + index] * 20, probe=probe)
        for index, lane_id in enumerate(protocol["lane_ids"])
    ]
    return {
        "schema": "pr15i-d2a-slot-v1",
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
    os.makedirs(os.path.join(campaign, "setup", "contention"), exist_ok=True)
    for entry in plan:
        path = os.path.join(campaign, "raw", "slots", f"slot-{entry['slot']:02d}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(slot_record(entry, protocol, kind), handle)
        for phase in ("before", "after"):
            with open(
                os.path.join(
                    campaign,
                    "setup", "contention", f"slot-{entry['slot']:02d}-{phase}.json"
                ),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"state": "clear"}, handle)
    return campaign, plan


class ShapeTests(unittest.TestCase):
    """BT-03/BT-15: sample/array shape and domain."""

    def test_samples_must_be_twenty_positive_integers(self):
        verify.validate_samples([1] * 20, "ok")
        for bad in ([1] * 19, [1] * 21, [0] * 20, [-1] + [1] * 19, [True] + [1] * 19, [1.0] * 20):
            with self.assertRaises(verify.VerifyError):
                verify.validate_samples(bad, "bad")

    def test_stage_and_counter_arrays_are_exact(self):
        verify.strict_array(valid_stage(), 13, "stage")
        verify.strict_array(valid_counters(1), 6, "counter")
        with self.assertRaises(verify.VerifyError):
            verify.strict_array(valid_stage()[:-1], 13, "stage")
        with self.assertRaises(verify.VerifyError):
            verify.strict_array([-1] + valid_stage()[1:], 13, "stage")

    def test_missing_warmup_shape_is_rejected_by_slot_loader(self):
        protocol = verify.load_protocol()
        root = tempfile.mkdtemp(prefix="d2a-slot-")
        try:
            campaign, _plan = write_campaign(root, protocol, "paired")
            path = os.path.join(campaign, "raw", "slots", "slot-01.json")
            record = json.load(open(path))
            record["lanes"][0]["warmups"] = 4
            json.dump(record, open(path, "w"))
            with self.assertRaises(verify.VerifyError):
                verify.load_slots(campaign, protocol, oracle_lanes(protocol))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_slot_file_is_blocked(self):
        protocol = verify.load_protocol()
        root = tempfile.mkdtemp(prefix="d2a-slot-")
        try:
            campaign, _plan = write_campaign(root, protocol, "paired")
            os.unlink(os.path.join(campaign, "raw", "slots", "slot-24.json"))
            with self.assertRaises(verify.VerifyError) as context:
                verify.load_slots(campaign, protocol, oracle_lanes(protocol))
            self.assertEqual(context.exception.status, "BLOCKED")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class SlotModeTests(unittest.TestCase):
    """BT-02/BT-04/BT-06: lane/arm/mode/oracle integrity."""

    def setUp(self):
        self.protocol = verify.load_protocol()
        self.root = tempfile.mkdtemp(prefix="d2a-slot-")
        self.campaign, self.plan = write_campaign(self.root, self.protocol, "paired")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _mutate(self, slot, mutate):
        path = os.path.join(self.campaign, "raw", "slots", f"slot-{slot:02d}.json")
        record = json.load(open(path))
        mutate(record)
        json.dump(record, open(path, "w"))

    def test_duplicate_or_missing_lane_is_rejected(self):
        self._mutate(1, lambda record: record["lanes"][1].update(id=record["lanes"][0]["id"]))
        with self.assertRaises(verify.VerifyError):
            verify.load_slots(self.campaign, self.protocol, oracle_lanes(self.protocol))

    def test_q_carrying_probe_fields_is_rejected(self):
        self._mutate(
            2,
            lambda record: record["lanes"][0].update(
                stage_samples=[valid_stage()] * 20,
                counter_samples=[valid_counters(0)] * 20,
            ),
        )
        with self.assertRaises(verify.VerifyError):
            verify.load_slots(self.campaign, self.protocol, oracle_lanes(self.protocol))

    def test_p_missing_probe_fields_is_rejected(self):
        self._mutate(
            3,
            lambda record: record["lanes"][0].update(
                stage_samples=None, counter_samples=None
            ),
        )
        with self.assertRaises(verify.VerifyError):
            verify.load_slots(self.campaign, self.protocol, oracle_lanes(self.protocol))

    def test_changed_oracle_answer_is_rejected(self):
        self._mutate(4, lambda record: record["lanes"][0].update(observed_total_hits=999))
        with self.assertRaises(verify.VerifyError):
            verify.load_slots(self.campaign, self.protocol, oracle_lanes(self.protocol))

    def test_wrong_operation_arm_is_rejected(self):
        self._mutate(1, lambda record: record.update(arm="Q"))
        with self.assertRaises(verify.VerifyError):
            verify.load_slots(self.campaign, self.protocol, oracle_lanes(self.protocol))


class DecomposeTests(unittest.TestCase):
    """BT-08/BT-09/BT-15/BT-20: counters and nested score partition."""

    def test_valid_partition_is_accepted(self):
        sample = verify.decompose(1_000_000, valid_stage(), valid_counters(1), 1, 100)
        self.assertTrue(sample["score_partition_ok"])
        self.assertEqual(sample["categories"]["other_ns"], 494_000)

    def test_score_stage_over_enclosing_window_is_flagged(self):
        stage = valid_stage()
        stage[12] = 250_000
        sample = verify.decompose(1_000_000, stage, valid_counters(1), 1, 100)
        self.assertFalse(sample["score_partition_ok"])

    def test_bm25_counter_one_too_high_is_rejected(self):
        counters = valid_counters(1)
        counters[3] = 2
        with self.assertRaises(verify.VerifyError):
            verify.decompose(1_000_000, valid_stage(), counters, 1, 100)

    def test_mixed_scorer_counter_mismatch_is_rejected(self):
        # A phrase/two-term shape would call BM25 more than once per hit.
        counters = valid_counters(12500)
        counters[3] = 25000
        with self.assertRaises(verify.VerifyError):
            verify.decompose(1_000_000, valid_stage(), counters, 12500, 100)

    def test_negative_or_short_stage_array_is_rejected(self):
        with self.assertRaises(verify.VerifyError):
            verify.decompose(1_000_000, valid_stage()[:-1], valid_counters(1), 1, 100)
        stage = valid_stage()
        stage[0] = -1
        with self.assertRaises(verify.VerifyError):
            verify.decompose(1_000_000, stage, valid_counters(1), 1, 100)

    def test_no_hit_denominator_is_not_applicable(self):
        sample = verify.decompose(1_000_000, valid_stage(), valid_counters(0), 0, 100)
        self.assertEqual(sample["returned_hits"], 0)
        self.assertEqual(sample["bm25_calls"], 0)


class ClassificationTests(unittest.TestCase):
    """BT-11/BT-12/BT-13/BT-14: drift and intrusion boundaries."""

    def _timing(self, drift, q_a=1.0, p_q=1.0, kind="medium_common", blocks=4):
        block = {
            "block": 1,
            "q_a": q_a,
            "p_q": p_q,
            "p_a": q_a * p_q,
            "a_a_drift": drift,
        }
        return {
            "pr15d_v1/100000/common/k100": {
                "kind": kind,
                "class": "common",
                "blocks": [dict(block, block=index + 1) for index in range(blocks)],
                "campaign": {
                    "q_a": q_a,
                    "p_q": p_q,
                    "p_a": q_a * p_q,
                    "a_a_drift": drift,
                },
            }
        }

    def test_drift_boundaries_are_inclusive(self):
        protocol = verify.load_protocol()
        for drift in (0.85, 1.15):
            result = verify.recompute_classification(self._timing(drift), protocol, "paired")
            self.assertEqual(result["status"], "D2A_ATTRIBUTION_LOW_INTRUSION")
        for drift in (0.849, 1.151):
            result = verify.recompute_classification(self._timing(drift), protocol, "paired")
            self.assertEqual(result["status"], "D2A_UNSTABLE")

    def test_one_outlier_block_allowed_two_not(self):
        protocol = verify.load_protocol()
        timing = self._timing(1.0)
        timing["pr15d_v1/100000/common/k100"]["blocks"][0]["a_a_drift"] = 1.60
        self.assertEqual(
            verify.recompute_classification(timing, protocol, "paired")["status"],
            "D2A_ATTRIBUTION_LOW_INTRUSION",
        )
        timing["pr15d_v1/100000/common/k100"]["blocks"][1]["a_a_drift"] = 1.60
        self.assertEqual(
            verify.recompute_classification(timing, protocol, "paired")["status"],
            "D2A_UNSTABLE",
        )

    def test_intrusion_boundary_is_inclusive(self):
        protocol = verify.load_protocol()
        self.assertEqual(
            verify.recompute_classification(
                self._timing(1.0, q_a=1.10, p_q=1.15), protocol, "paired"
            )["status"],
            "D2A_ATTRIBUTION_LOW_INTRUSION",
        )
        self.assertEqual(
            verify.recompute_classification(
                self._timing(1.0, q_a=1.10 + 1e-9), protocol, "paired"
            )["status"],
            "D2A_DIAGNOSTIC_PERTURBED",
        )
        self.assertEqual(
            verify.recompute_classification(
                self._timing(1.0, p_q=1.15 + 1e-9), protocol, "paired"
            )["status"],
            "D2A_DIAGNOSTIC_PERTURBED",
        )


class PriorityTests(unittest.TestCase):
    """BT-19/BT-23: closed-form priority boundaries and no missing denominators."""

    def _lane(self, accumulate_ns, share, calls, returned):
        return {
            "score_accumulate_ns": {"median_ns": accumulate_ns, "median_share": share},
            "bm25_calls": calls,
            "returned_hits": returned,
        }

    def test_two_of_three_primary_lanes_at_boundaries_pass(self):
        protocol = verify.load_protocol()
        gate = protocol["priority_gate"]
        lanes = {
            gate["lanes"][0]: self._lane(2_000_000, 0.08, 12500, 100),
            gate["lanes"][1]: self._lane(2_000_000, 0.08, 49999, 100),
            gate["lanes"][2]: self._lane(1_999_999, 0.08, 49999, 10),
        }
        result = verify.recompute_priority(lanes, protocol)
        self.assertTrue(result["quantitative_gate_pass"])
        self.assertEqual(result["qualifying_lanes"], 2)

    def test_one_unit_below_fails(self):
        protocol = verify.load_protocol()
        gate = protocol["priority_gate"]
        lanes = {
            gate["lanes"][0]: self._lane(1_999_999, 0.08, 12500, 100),
            gate["lanes"][1]: self._lane(2_000_000, 0.08, 49999, 100),
            gate["lanes"][2]: self._lane(1_999_999, 0.08, 49999, 10),
        }
        result = verify.recompute_priority(lanes, protocol)
        self.assertFalse(result["quantitative_gate_pass"])
        self.assertEqual(result["qualifying_lanes"], 1)

    def test_missing_returned_hits_is_not_applicable(self):
        protocol = verify.load_protocol()
        gate = protocol["priority_gate"]
        lanes = {
            gate["lanes"][0]: self._lane(2_000_000, 0.08, 0, 0),
            gate["lanes"][1]: self._lane(2_000_000, 0.08, 0, 0),
            gate["lanes"][2]: self._lane(2_000_000, 0.08, 0, 0),
        }
        result = verify.recompute_priority(lanes, protocol)
        self.assertFalse(result["quantitative_gate_pass"])
        self.assertIsNone(result["lanes"][gate["lanes"][0]]["bm25_calls_per_returned_hit"])


class BinaryAndSealTests(unittest.TestCase):
    """BT-05/BT-17: binary identity and post-seal tamper rejection."""

    def test_q_p_binary_digest_mismatch_is_rejected(self):
        protocol = verify.load_protocol()
        entries = {
            "A": {"path": "/dev/null", "sha256": "a" * 64},
            "QP": {"path": "/dev/null", "sha256": "b" * 64},
        }
        record = {
            "arm": "Q",
            "binary_sha256": "a" * 64,
            "diagnostic_derivative_sha256": DERIVATIVE,
        }
        with self.assertRaises(verify.VerifyError):
            verify.verify_slot_binaries({1: record}, entries, protocol, "paired")

    def _sealed_control(self):
        protocol = verify.load_protocol()
        os.makedirs(run.TARGET_ROOT, exist_ok=True)
        parent = tempfile.mkdtemp(prefix="d2a-seal-", dir=run.TARGET_ROOT)
        root, _plan = write_campaign(parent, protocol, "control")
        for relative in verify.RAW_MEMBERS:
            path = os.path.join(root, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({}, handle)
        run.seal_campaign(
            root,
            kind="control",
            slot_count=protocol["control_slots_per_campaign"],
            expected_timed=protocol["control_slots_per_campaign"] * 9 * 20,
            expected_warmups=protocol["control_slots_per_campaign"] * 9 * 5,
            index_builds=2,
        )
        return protocol, root

    def test_sealed_member_tamper_is_rejected(self):
        protocol, root = self._sealed_control()
        try:
            verify.verify_seal(root, protocol)
            path = os.path.join(root, "raw", "slots", "slot-01.json")
            record = json.load(open(path))
            record["lanes"][0]["samples_ns"][0] += 1
            json.dump(record, open(path, "w"))
            with self.assertRaises(verify.VerifyError):
                verify.verify_seal(root, protocol)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class SeriesAndSummaryTests(unittest.TestCase):
    """BT-18/BT-21: no cherry-picking and deterministic sanitized output."""

    def test_divergent_campaign_gate_is_inconclusive(self):
        self.assertEqual(
            verify.series_verdict(True, [True, True], [True, False]),
            "D2A_SCORE_COST_INCONCLUSIVE",
        )
        self.assertEqual(
            verify.series_verdict(True, [True, True], [True, True]),
            "D2A_SCORE_COST_WORTH_DESIGNING",
        )
        self.assertEqual(
            verify.series_verdict(True, [True, True], [False, False]),
            "D2A_SCORE_COST_LOW_PRIORITY",
        )
        self.assertEqual(
            verify.series_verdict(True, [True, False], [True, True]),
            "D2A_ATTRIBUTION_NOT_QUALIFIED",
        )

    def test_sanitized_write_is_byte_stable_and_never_silently_replaced(self):
        root = tempfile.mkdtemp(prefix="d2a-summary-")
        try:
            path = os.path.join(root, "sanitized", "summary.json")
            self.assertEqual(verify._write_or_check(path, b'{"a":1}\\n'), "CREATED")
            self.assertEqual(verify._write_or_check(path, b'{"a":1}\\n'), "UNCHANGED")
            with self.assertRaises(verify.VerifyError):
                verify._write_or_check(path, b'{"a":2}\\n')
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Frozen-protocol tests for PR 15I-D2-A (BT-01/BT-22)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROTOCOL = os.path.join(HERE, "protocol_v1.json")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"d2a_{name}", os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("run")
verify = _load("verify")


class FrozenProtocolTests(unittest.TestCase):
    def test_protocol_is_canonical_and_sha_pinned(self):
        raw = open(PROTOCOL, "rb").read()
        parsed = json.loads(raw.decode("utf-8"))
        canonical = json.dumps(
            parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        self.assertEqual(raw, canonical + b"\n")
        self.assertEqual(len(hashlib.sha256(raw).hexdigest()), 64)

    def test_duplicate_keys_are_rejected(self):
        raw = open(PROTOCOL, encoding="utf-8").read()

        def no_duplicates(pairs):
            seen = set()
            for key, _value in pairs:
                if key in seen:
                    raise ValueError(f"duplicate key {key}")
                seen.add(key)
            return dict(pairs)

        json.loads(raw, object_pairs_hook=no_duplicates)

    def test_controller_and_verifier_agree_on_the_literal(self):
        self.assertEqual(run.EXPECTED_PROTOCOL, verify.EXPECTED_PROTOCOL)
        self.assertEqual(json.load(open(PROTOCOL)), run.EXPECTED_PROTOCOL)

    def test_schema_and_closed_stage_names(self):
        protocol = json.load(open(PROTOCOL))
        self.assertEqual(protocol["schema"], "pr15i-d2a-scoring-attribution-v1")
        self.assertEqual(
            protocol["stages"],
            [
                "plan_ns",
                "reader_live_ns",
                "expand_ns",
                "stats_ns",
                "evaluate_ns",
                "candidate_ns",
                "projection_ns",
                "leaf_decode_ns",
                "membership_ns",
                "score_vector_ns",
                "score_map_ns",
                "score_owner_ns",
                "score_accumulate_ns",
            ],
        )
        self.assertEqual(
            protocol["counters"],
            [
                "matched_docs",
                "scored_docs",
                "candidate_docs",
                "bm25_calls",
                "scoring_map_entries",
                "positive_term_owners",
            ],
        )

    def test_frozen_acceptance_parameters(self):
        protocol = json.load(open(PROTOCOL))
        self.assertEqual(protocol["base_sha"], "9429dce99827f25766a92c1fbded8f78a0b168f1")
        self.assertEqual(protocol["arms"], ["A", "Q", "P"])
        self.assertEqual(protocol["arm_order_by_block"], ["AQPPQA", "PQAAQP", "QAPPAQ", "PAQQAP"])
        self.assertEqual(protocol["slots_per_campaign"], 24)
        self.assertEqual(protocol["control_slots_per_campaign"], 16)
        self.assertEqual(protocol["samples_per_lane_slot"], 20)
        self.assertEqual(protocol["warmups_per_lane_slot"], 5)
        self.assertEqual(protocol["contention_probes_per_slot"], 2)
        self.assertEqual(protocol["stage_partition_overhead_abs_ns"], 10_000)
        self.assertEqual(protocol["stage_partition_overhead_share"], 0.02)
        self.assertEqual(protocol["stage_partition_max_violation_fraction"], 0.01)
        self.assertEqual(protocol["archive_root_relative"], "benchmark-evidence/pr15i-d2a")

    def test_priority_gate_is_numerically_closed(self):
        gate = json.load(open(PROTOCOL))["priority_gate"]
        self.assertEqual(
            gate["lanes"],
            [
                "pr15d_v1/100000/medium/k100",
                "pr15d_v1/100000/common/k100",
                "pr15d_v1/100000/common/k10",
            ],
        )
        self.assertEqual(gate["min_median_accumulate_ns"], 2_000_000)
        self.assertEqual(gate["min_median_accumulate_share"], 0.08)
        self.assertEqual(gate["min_bm25_calls_per_returned_hit"], 10)
        self.assertEqual(gate["required_qualifying_lanes_per_campaign"], 2)
        self.assertEqual(gate["required_campaigns"], 2)

    def test_unknown_or_missing_key_is_refused(self):
        protocol = json.load(open(PROTOCOL))
        protocol["unexpected"] = True
        with self.assertRaises(run.D2AError):
            run.validate_protocol(protocol)
        protocol = json.load(open(PROTOCOL))
        del protocol["priority_gate"]
        with self.assertRaises(run.D2AError):
            run.validate_protocol(protocol)

    def test_changed_threshold_is_refused(self):
        protocol = json.load(open(PROTOCOL))
        protocol["q_a_ratio_ceiling_low_match"] = 1.16
        with self.assertRaises(run.D2AError):
            run.validate_protocol(protocol)

    def test_changed_corpus_or_base_identity_is_refused(self):
        protocol = json.load(open(PROTOCOL))
        protocol["corpus_manifest_sha256"] = "0" * 64
        with self.assertRaises(run.D2AError):
            run.validate_protocol(protocol)
        protocol = json.load(open(PROTOCOL))
        protocol["base_sha"] = "1" * 40
        with self.assertRaises(run.D2AError):
            run.validate_protocol(protocol)


if __name__ == "__main__":
    unittest.main()

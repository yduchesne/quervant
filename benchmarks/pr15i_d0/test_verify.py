#!/usr/bin/env python3
"""Adversarial tests for the independent PR 15I-D0 verifier.

Every fixture is synthetic JSON evidence under an ignored temporary directory.
The full engine performance is never faked as a real measurement: these tests
exercise parser, arithmetic, seal, oracle, stage-partition and classification
logic only.  ``check_external=False`` skips binary/index rehashing because those
require the real build artifacts; the corresponding pure checks are tested
separately with synthetic layouts.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
TESTS_ROOT = os.path.join(REPO_ROOT, "target", "pr15i-d0", "tests")


def _load(name):
    spec = importlib.util.spec_from_file_location(f"d0_{name}", os.path.join(HERE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("run")
verify = _load("verify")


def _lane_factors(lane_id, factors, default):
    if factors and lane_id in factors:
        return factors[lane_id]
    return default


def _stage_array(engine_ns: int) -> list[int]:
    # plan, reader, expand, stats, evaluate, candidate, projection,
    # leaf, membership, score.  evaluate = engine - 6, residual = evaluate.
    if engine_ns < 6:
        raise AssertionError("fixture engine_ns too small")
    return [1, 1, 1, 1, engine_ns - 6, 1, 1, 0, 0, 0]


def make_campaign(
    directory: str,
    *,
    block_drifts=None,
    q_factor=1.0,
    p_factor=1.0,
    lane_factors=None,
    timing_override=None,
    stage_mutator=None,
    slot_mutator=None,
    lane_mutator=None,
) -> str:
    protocol = verify.load_protocol()
    loops = verify.lane_descriptors(protocol)
    oracle = verify.load_oracle(REPO_ROOT)
    oracle_lanes = verify.recompute_oracle(oracle, protocol)["lanes"]
    plan = verify.slot_schedule(protocol)
    block_drifts = block_drifts or [1.0] * 4

    raw = os.path.join(directory, "raw")
    slots_dir = os.path.join(raw, "slots")
    contention = os.path.join(directory, "setup", "contention")
    for path in (raw, slots_dir, contention):
        os.makedirs(path, exist_ok=True)

    base = 1_000_000
    slots = {}
    seen_a = {}
    for entry in plan:
        slot = entry["slot"]
        block = entry["block"]
        arm = entry["arm"]
        lanes_out = []
        if arm == "A":
            index = seen_a.get(block, 0)
            seen_a[block] = index + 1
            a_median = base if index == 0 else round(base * block_drifts[block - 1])
        for lane in loops:
            lane_id = lane["id"]
            q_med, p_med = _lane_factors(lane_id, lane_factors, (q_factor, p_factor))
            if arm == "A":
                median = a_median
            elif arm == "Q":
                median = round(base * q_med)
            else:
                median = round(base * q_med * p_med)
            samples = [median] * 20
            expected = oracle_lanes[lane_id]
            lane_record = {
                "id": lane_id,
                "warmups": 5,
                "samples_ns": samples,
                "expected_total_hits": expected["total_hits"],
                "observed_total_hits": expected["total_hits"],
                "doc_ids": expected["doc_ids"],
                "stage_samples": None,
                "counter_samples": None,
            }
            if arm == "P":
                stage_samples = []
                counter_samples = []
                for engine_ns in samples:
                    stages = _stage_array(engine_ns)
                    counters = [expected["total_hits"]] * 3
                    if stage_mutator:
                        stages, counters = stage_mutator(stages, counters, lane_id)
                    stage_samples.append(stages)
                    counter_samples.append(counters)
                lane_record["stage_samples"] = stage_samples
                lane_record["counter_samples"] = counter_samples
            lanes_out.append(lane_record)
        record = {
            "schema": "pr15i-d0-slot-v1",
            "slot": slot,
            "block": block,
            "position": entry["position"],
            "arm": arm,
            "base_sha": verify.BASE_SHA,
            "diagnostic_derivative_sha256": None if arm == "A" else "a" * 64,
            "binary_sha256": "b" * 64,
            "index_sha256": "c" * 64,
            "lane_ids": protocol["lane_ids"],
            "lanes": lanes_out,
            "contention_before": "clear",
            "contention_after": "clear",
        }
        slots[slot] = record

    timing = run.compute_timing(slots, protocol)
    if timing_override:
        timing = timing_override(timing)

    for entry in plan:
        slot = entry["slot"]
        record = copy.deepcopy(slots[slot])
        if slot_mutator:
            slot_mutator(record)
        if lane_mutator:
            for lane_record in record["lanes"]:
                lane_mutator(lane_record, record["arm"], lane_record["id"])
        run.write_json_exclusive(os.path.join(slots_dir, f"slot-{slot:02d}.json"), record)

    for slot in range(1, 25):
        run.write_json_exclusive(
            os.path.join(contention, f"slot-{slot:02d}-before.json"),
            {"state": "clear", "reason_codes": []},
        )
        run.write_json_exclusive(
            os.path.join(contention, f"slot-{slot:02d}-after.json"),
            {"state": "clear", "reason_codes": []},
        )

    for name, value in (
        ("authorization.json", {"schema": "pr15i-d0-authorization-v1", "campaign": "synthetic"}),
        ("environment.json", {"schema": "pr15i-d0-environment-v1"}),
        ("toolchains.json", {}),
        ("corpus.json", {"schema": "pr15i-d0-corpus-v1"}),
        (
            "sources.json",
            {
                "schema": "pr15i-d0-sources-v1",
                "source_inventory": {
                    relative: {"base_sha256": "d" * 64, "derivative_sha256": "e" * 64}
                    for relative in verify.DERIVATIVE_FILES
                },
                "diagnostic_derivative_sha256": "a" * 64,
                "tooling": {"benchmarks/pr15i_d0/run.py": "f" * 64},
                "source_proof": {"status": "VERIFIED", "derivative_fingerprint_sha256": "a" * 64},
            },
        ),
        (
            "binaries.json",
            {
                "schema": "pr15i-d0-binaries-v1",
                "A": {"path": "/nonexistent/A", "sha256": "1" * 64},
                "QP": {"path": "/nonexistent/QP", "sha256": "2" * 64},
                "q_and_p_exact_same_binary": True,
            },
        ),
        (
            "index-layout.json",
            {"schema": "pr15i-d0-index-layout-v1", "builds": {}},
        ),
        ("oracle.json", {"schema": "pr15i-d0-oracle-v1", "lanes": oracle_lanes}),
        ("mode-proof.json", {"schema": "pr15i-d0-mode-proof-v1"}),
        ("timing.json", timing),
    ):
        run.write_json_exclusive(os.path.join(raw, name), value)
    run.seal_campaign(directory)
    return directory


def synthetic_layout(committed: int, stored: int, digest: str | None = None) -> dict:
    if digest is None:
        digest = verify.sha256_bytes(verify.canonical_json_bytes([]))
    return {
        "builds": {
            "A": {
                "10000": {
                    "committed_index_bytes": committed,
                    "stored_bytes": stored,
                    "digest": digest,
                    "files": [],
                    "index_dir": "/nonexistent",
                },
                "100000": {
                    "committed_index_bytes": committed,
                    "stored_bytes": stored,
                    "digest": digest,
                    "files": [],
                    "index_dir": "/nonexistent",
                },
            },
            "QP": {
                "10000": {
                    "committed_index_bytes": committed,
                    "stored_bytes": stored,
                    "digest": digest,
                    "files": [],
                    "index_dir": "/nonexistent",
                },
                "100000": {
                    "committed_index_bytes": committed,
                    "stored_bytes": stored,
                    "digest": digest,
                    "files": [],
                    "index_dir": "/nonexistent",
                },
            },
        }
    }


class VerifyFixture(unittest.TestCase):
    def setUp(self):
        os.makedirs(TESTS_ROOT, exist_ok=True)
        self.directory = tempfile.mkdtemp(prefix="verify-", dir=TESTS_ROOT)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def build(self, **kwargs):
        return make_campaign(self.directory, **kwargs)

    def verify(self, campaign=None):
        return verify.verify_campaign(campaign or self.directory, REPO_ROOT, check_external=False)

    def assertInvalid(self, code: str, **kwargs):
        self.build(**kwargs)
        with self.assertRaises(verify.VerifyError) as context:
            self.verify()
        self.assertEqual(context.exception.status, "INVALID")
        self.assertEqual(context.exception.code, code)
        return context.exception

    # -- baseline ---------------------------------------------------------

    def test_valid_synthetic_campaign_verifies(self):
        self.build()
        result = self.verify()
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["classification"], "D0_ATTRIBUTION_LOW_INTRUSION")
        self.assertEqual(result["ranking_status"], "QUALIFIED_NONCAUSAL_REGISTER")
        self.assertEqual(result["sealed_member_count"], 83)

    def test_schedule_is_exactly_the_frozen_literal(self):
        protocol = verify.load_protocol()
        plan = verify.slot_schedule(protocol)
        self.assertEqual(len(plan), 24)
        self.assertEqual([entry["arm"] for entry in plan[:6]], list("AQPPQA"))
        self.assertEqual([entry["arm"] for entry in plan[6:12]], list("PQAAQP"))
        self.assertEqual([entry["arm"] for entry in plan[12:18]], list("QAPPAQ"))
        self.assertEqual([entry["arm"] for entry in plan[18:24]], list("PAQQAP"))

    # -- oracle / mode ----------------------------------------------------

    def test_p_doc_ids_differ_from_oracle(self):
        def mutate(lane, arm, lane_id):
            if arm == "P":
                lane["doc_ids"] = ["wrong"]

        self.assertInvalid("V_ORACLE", lane_mutator=mutate)

    def test_q_total_hits_differs_from_oracle(self):
        def mutate(lane, arm, lane_id):
            if arm == "Q":
                lane["observed_total_hits"] = -1

        self.assertInvalid("V_ORACLE", lane_mutator=mutate)

    def test_q_carries_probe_fields(self):
        def mutate(lane, arm, lane_id):
            if arm == "Q":
                lane["stage_samples"] = []

        self.assertInvalid("V_MODE", lane_mutator=mutate)

    def test_p_misses_probe_fields(self):
        def mutate(lane, arm, lane_id):
            if arm == "P":
                lane["stage_samples"] = None

        self.assertInvalid("V_STAGES", lane_mutator=mutate)

    def test_a_carries_derivative_fingerprint(self):
        def mutate(record):
            if record["arm"] == "A":
                record["diagnostic_derivative_sha256"] = "a" * 64

        self.assertInvalid("V_SLOT", slot_mutator=mutate)

    # -- counts, types, order --------------------------------------------

    def test_nineteen_samples_is_rejected(self):
        def mutate(lane, arm, lane_id):
            lane["samples_ns"] = lane["samples_ns"][:19]

        self.assertInvalid("V_SAMPLE_COUNT", lane_mutator=mutate)

    def test_bool_and_zero_samples_are_rejected(self):
        for bad in (True, 0, -5, "100"):
            with self.subTest(bad=bad):
                directory = tempfile.mkdtemp(prefix="verify-", dir=TESTS_ROOT)
                try:
                    def mutate(lane, arm, lane_id, bad=bad):
                        lane["samples_ns"][0] = bad

                    make_campaign(directory, lane_mutator=mutate)
                    with self.assertRaises(verify.VerifyError) as context:
                        verify.verify_campaign(directory, REPO_ROOT, check_external=False)
                    self.assertIn(context.exception.code, {"V_SAMPLE_TYPE", "V_SAMPLE_DOMAIN"})
                finally:
                    shutil.rmtree(directory, ignore_errors=True)

    def test_wrong_warmup_count_is_rejected(self):
        def mutate(lane, arm, lane_id):
            lane["warmups"] = 4

        self.assertInvalid("V_WARMUP", lane_mutator=mutate)

    def test_reordered_lanes_are_rejected(self):
        def mutate(record):
            record["lanes"] = list(reversed(record["lanes"]))

        self.assertInvalid("V_SLOT", slot_mutator=mutate)

    # -- stability and intrusion -----------------------------------------

    def test_drift_at_inclusive_boundaries_passes(self):
        self.build(block_drifts=[0.85, 0.85, 0.85, 0.85])
        self.assertEqual(self.verify()["classification"], "D0_ATTRIBUTION_LOW_INTRUSION")

    def test_drift_just_outside_boundary_is_unstable(self):
        self.build(block_drifts=[0.849999, 0.849999, 0.849999, 0.849999])
        self.assertEqual(self.verify()["classification"], "D0_UNSTABLE")

    def test_one_outlier_block_is_allowed(self):
        self.build(block_drifts=[1.0, 1.0, 1.0, 1.3])
        self.assertEqual(self.verify()["classification"], "D0_ATTRIBUTION_LOW_INTRUSION")

    def test_two_outlier_blocks_are_unstable(self):
        self.build(block_drifts=[1.0, 1.0, 1.3, 1.3])
        self.assertEqual(self.verify()["classification"], "D0_UNSTABLE")

    def test_q_a_at_ceiling_passes(self):
        self.build(q_factor=1.10)
        self.assertEqual(self.verify()["classification"], "D0_ATTRIBUTION_LOW_INTRUSION")

    def test_q_a_above_ceiling_is_perturbed(self):
        self.build(q_factor=1.100001)
        self.assertEqual(self.verify()["classification"], "D0_DIAGNOSTIC_PERTURBED")

    def test_p_q_above_ceiling_is_perturbed(self):
        self.build(p_factor=1.150001)
        self.assertEqual(self.verify()["classification"], "D0_DIAGNOSTIC_PERTURBED")

    def test_one_block_above_single_block_guard_is_perturbed(self):
        self.build(lane_factors={"pr15d_v1/100000/common/k100": (1.0, 1.55)})
        self.assertEqual(self.verify()["classification"], "D0_DIAGNOSTIC_PERTURBED")

    def test_two_campaign_average_cannot_rescue_one_failure(self):
        passing = {"a": "D0_ATTRIBUTION_LOW_INTRUSION", "b": "D0_ATTRIBUTION_LOW_INTRUSION"}
        failing = {"a": "D0_ATTRIBUTION_LOW_INTRUSION", "b": "D0_DIAGNOSTIC_PERTURBED"}
        self.assertEqual(verify.series_status(passing), "D0_ATTRIBUTION_LOW_INTRUSION")
        self.assertEqual(verify.series_status(failing), "D0_DIAGNOSTIC_PERTURBED")

    def test_perturbed_series_withholds_ranking(self):
        self.build(q_factor=1.2)
        result = self.verify()
        self.assertEqual(result["classification"], "D0_DIAGNOSTIC_PERTURBED")
        self.assertEqual(result["ranking_status"], "D0_RANKING_NOT_QUALIFIED")
        self.assertIsNone(result["ranking"])

    # -- stage partition --------------------------------------------------

    def test_negative_evaluate_residual_is_invalid(self):
        def mutate(stages, counters, lane_id):
            stages[4] = 1  # evaluate < leaf+membership+score is impossible here
            stages[7] = 5
            return stages, counters

        self.assertInvalid("V_STAGE_PARTITION", stage_mutator=mutate)

    def test_top_level_stages_exceeding_engine_are_invalid(self):
        def mutate(stages, counters, lane_id):
            stages[0] = 10_000_000
            return stages, counters

        self.assertInvalid("V_STAGE_PARTITION", stage_mutator=mutate)

    def test_exact_partition_passes(self):
        self.build()
        result = self.verify()
        self.assertEqual(result["status"], "VERIFIED")

    def test_counter_disagreement_is_invalid(self):
        def mutate(stages, counters, lane_id):
            return stages, [0, 0, 0]

        self.assertInvalid("V_COUNTER", stage_mutator=mutate)

    def test_counter_type_is_invalid(self):
        def mutate(stages, counters, lane_id):
            return stages, [True, 0, 0]

        self.assertInvalid("V_SAMPLE_TYPE", stage_mutator=mutate)

    # -- timing producer lies --------------------------------------------

    def test_producer_timing_lie_is_rejected(self):
        def override(timing):
            lane = next(iter(timing["lanes"].values()))
            lane["campaign"]["q_a"] = lane["campaign"]["q_a"] + 0.5
            return timing

        self.assertInvalid("V_TIMING", timing_override=override)

    def test_malformed_derived_timing_is_rejected(self):
        def override(timing):
            timing["lanes"].pop(next(iter(timing["lanes"])))
            return timing

        self.assertInvalid("V_TIMING", timing_override=override)

    # -- ranking ----------------------------------------------------------

    def test_tie_break_uses_fixed_hypothesis_order(self):
        protocol = verify.load_protocol()
        lanes = {}
        for lane in verify.lane_descriptors(protocol):
            lanes[lane["id"]] = {
                category: {"median_ns": 10, "median_share": 0.1, "p95_ns": 10}
                for category in verify.EXCLUSIVE
            }
            lanes[lane["id"]]["other_ns"]["median_ns"] = 5
            lanes[lane["id"]]["eval_residual_ns"]["median_ns"] = 5
        ranking = verify.recompute_ranking(lanes)
        self.assertEqual(ranking["primary"][0], "H-CANDIDATE")

    def test_other_top_mandates_further_attribution(self):
        self.build()
        result = self.verify()
        self.assertTrue(result["ranking"]["other_tops"])

    # -- seal tampering ---------------------------------------------------

    def test_corrupted_seal_digest_is_rejected(self):
        self.build()
        seal_path = os.path.join(self.directory, "raw", "seal.json")
        seal = json.load(open(seal_path))
        seal["members"]["raw/slots/slot-01.json"] = "0" * 64
        json.dump(seal, open(seal_path, "w"))
        with self.assertRaises(verify.VerifyError) as context:
            self.verify()
        self.assertEqual(context.exception.code, "V_SEAL")

    def test_missing_contention_probe_is_rejected(self):
        self.build()
        os.unlink(os.path.join(self.directory, "setup/contention/slot-01-before.json"))
        with self.assertRaises(verify.VerifyError) as context:
            self.verify()
        self.assertIn(context.exception.code, {"V_SEAL", "V_PATH"})

    def test_extra_unlisted_raw_file_is_rejected(self):
        self.build()
        run.write_json_exclusive(
            os.path.join(self.directory, "raw", "extra.json"), {"x": 1}
        )
        with self.assertRaises(verify.VerifyError) as context:
            self.verify()
        self.assertEqual(context.exception.code, "V_SEAL")

    def test_path_traversal_in_seal_is_rejected(self):
        self.build()
        seal_path = os.path.join(self.directory, "raw", "seal.json")
        seal = json.load(open(seal_path))
        seal["members"]["../escape.json"] = "0" * 64
        json.dump(seal, open(seal_path, "w"))
        with self.assertRaises(verify.VerifyError) as context:
            self.verify()
        self.assertEqual(context.exception.code, "V_SEAL")

    def test_missing_slot_prevents_seal(self):
        with self.assertRaises(run.D0Blocked):
            # a campaign without slots cannot be sealed
            os.makedirs(os.path.join(self.directory, "raw"))
            run.seal_campaign(self.directory)


    def test_tooling_hash_mismatch_is_rejected(self):
        self.build()
        sources_path = os.path.join(self.directory, "raw", "sources.json")
        sources = json.load(open(sources_path))
        sources["tooling"]["benchmarks/pr15i_d0/run.py"] = "0" * 64
        json.dump(sources, open(sources_path, "w"))
        with self.assertRaises(verify.VerifyError) as context:
            verify.verify_sources(self.directory)
        self.assertEqual(context.exception.code, "V_SOURCES")

    def test_a_q_binary_identical_is_rejected(self):
        binary = os.path.join(self.directory, "binary")
        open(binary, "wb").write(b"same-bytes")
        os.makedirs(os.path.join(self.directory, "raw"), exist_ok=True)
        run.write_json_exclusive(
            os.path.join(self.directory, "raw", "binaries.json"),
            {
                "schema": "pr15i-d0-binaries-v1",
                "A": {"path": binary, "sha256": verify.sha256_file(binary)},
                "QP": {"path": binary, "sha256": verify.sha256_file(binary)},
                "q_and_p_exact_same_binary": True,
            },
        )
        with self.assertRaises(verify.VerifyError) as context:
            verify.verify_binaries(self.directory)
        self.assertEqual(context.exception.code, "V_BINARY")

    def test_slot_binary_digest_mismatch_is_rejected(self):
        self.build()
        protocol = verify.load_protocol()
        oracle = verify.load_oracle(REPO_ROOT)
        lanes = verify.recompute_oracle(oracle, protocol)["lanes"]
        records = verify.load_slots(self.directory, protocol, lanes)
        entries = {"A": {"sha256": "b" * 64}, "QP": {"sha256": "c" * 64}}
        with self.assertRaises(verify.VerifyError) as context:
            verify.verify_slot_binaries(records, entries, protocol)
        self.assertEqual(context.exception.code, "V_BINARY")

    def test_duplicate_slot_number_is_rejected(self):
        def mutate(record):
            record["slot"] = 1

        self.assertInvalid("V_SLOT", slot_mutator=mutate)

    def test_drift_upper_inclusive_boundary_passes(self):
        self.build(block_drifts=[1.15, 1.15, 1.15, 1.15])
        self.assertEqual(self.verify()["classification"], "D0_ATTRIBUTION_LOW_INTRUSION")

    # -- lanes and index format ------------------------------------------

    def test_lane_descriptor_drift_is_rejected(self):
        with self.assertRaises(verify.VerifyError):
            verify.parse_lane("pr15d_v1/20000/absent/k100")

    def test_index_sentinel_mismatch_is_rejected(self):
        protocol = verify.load_protocol()
        layout = synthetic_layout(1, 1)
        directory = tempfile.mkdtemp(prefix="layout-", dir=TESTS_ROOT)
        try:
            os.makedirs(os.path.join(directory, "raw"))
            run.write_json_exclusive(
                os.path.join(directory, "raw", "index-layout.json"), layout
            )
            with self.assertRaises(verify.VerifyError) as context:
                verify.verify_index_layout(directory, protocol, check_files=False)
            self.assertEqual(context.exception.code, "V_INDEX_FORMAT")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_index_a_qp_digest_mismatch_is_rejected(self):
        protocol = verify.load_protocol()
        layout = synthetic_layout(
            protocol["100k_lz4_committed_index_sentinel"],
            protocol["100k_lz4_stored_section_sentinel"],
        )
        layout["builds"]["QP"]["100000"]["digest"] = "b" * 64
        directory = tempfile.mkdtemp(prefix="layout-", dir=TESTS_ROOT)
        try:
            os.makedirs(os.path.join(directory, "raw"))
            run.write_json_exclusive(
                os.path.join(directory, "raw", "index-layout.json"), layout
            )
            with self.assertRaises(verify.VerifyError) as context:
                verify.verify_index_layout(directory, protocol, check_files=False)
            self.assertEqual(context.exception.code, "V_INDEX")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_matching_index_sentinels_pass(self):
        protocol = verify.load_protocol()
        layout = synthetic_layout(
            protocol["100k_lz4_committed_index_sentinel"],
            protocol["100k_lz4_stored_section_sentinel"],
        )
        directory = tempfile.mkdtemp(prefix="layout-", dir=TESTS_ROOT)
        try:
            os.makedirs(os.path.join(directory, "raw"))
            run.write_json_exclusive(
                os.path.join(directory, "raw", "index-layout.json"), layout
            )
            result = verify.verify_index_layout(directory, protocol, check_files=False)
            self.assertIn("digests", result)
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

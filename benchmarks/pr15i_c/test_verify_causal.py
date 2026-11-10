#!/usr/bin/env python3
"""PR 15I-C causal verifier — mandatory 40-case adversarial matrix (CV-01..40).

Each case builds a minimal sealed synthetic campaign, mutates exactly one fact
(recomputing the seal when raw content changes), and asserts the typed rejection.
The real campaign directories are never touched.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load("pr15i_c_verify_causal", "verify_causal.py")

SEGMENT_A = "TRWSEG01"
STORED_LEN = 40
SYNTH_TOTAL = 190
SYNTH_STORED = STORED_LEN
ROWS = {10000: [{"row": index} for index in range(3)],
        100000: [{"row": index} for index in range(3)]}
EXPECTED = {"total_hits": 1, "doc_ids": ["d0"]}


def build_segment():
    payload = bytearray(STORED_LEN)
    payload[0:2] = (2).to_bytes(2, "little")
    payload[12] = 1
    footer = bytearray()
    footer += (1).to_bytes(2, "little") + b"\0" * 4
    footer += (1).to_bytes(4, "little")
    footer += (13).to_bytes(2, "little") + (1).to_bytes(2, "little")
    footer += (0).to_bytes(4, "little")
    entry = bytearray(60)
    entry[0:2] = (0x0007).to_bytes(2, "little")
    entry[12:20] = (8).to_bytes(8, "little")
    entry[20:28] = (STORED_LEN).to_bytes(8, "little")
    footer += entry
    footer_offset = 8 + STORED_LEN
    trailer = bytearray(64)
    trailer[8:16] = footer_offset.to_bytes(8, "little")
    trailer[16:24] = len(footer).to_bytes(8, "little")
    trailer[24:28] = (1).to_bytes(4, "little")
    return bytes(SEGMENT_A.encode() + bytes(payload) + bytes(footer) + bytes(trailer))


def lanes():
    table = {
        10000: [("absent", "key", "absent", 100), ("rare", "key", "rare", 100),
                ("medium", "key", "medium", 100), ("common", "key", "common", 100)],
        100000: [("absent", "key", "absent", 100), ("rare", "key", "rare", 100),
                 ("medium", "key", "medium", 100), ("common", "key", "common", 100),
                 ("common", "key", "common", 10)],
    }
    result = []
    for n in (10000, 100000):
        for class_name, field, term, k in table[n]:
            result.append({"id": f"pr15d_v1/{n}/{class_name}/k{k}", "n": n,
                           "class": class_name, "field": field, "term": term,
                           "k": k, "regime": "warm"})
    return result


def oracle_expected(rows, field, term, k):
    return dict(EXPECTED)


class SyntheticCampaign:
    """Minimal but structurally faithful sealed three-arm campaign."""

    def __init__(self, root, name, regime="unbatched", ratios=None):
        self.root = root
        self.name = name
        self.regime = regime
        self.campaign = os.path.join(root, "target", "pr15i-c",
                                     "causal-campaigns-v1", name)
        self.ratios = ratios or {"B/A": 1.70, "C/A": 1.00, "B/C": 1.70}
        os.makedirs(self.campaign)
        self.write_all()
        verify.seal_campaign_for_tests(self.campaign)

    # ---- helpers -------------------------------------------------------
    def raw(self, relative):
        return os.path.join(self.campaign, "raw", relative)

    def write_json(self, relative, value):
        path = self.raw(relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)

    def write_all(self):
        batched = self.regime == "batched"
        os.makedirs(os.path.join(self.campaign, "setup", "corpus"), exist_ok=True)
        os.makedirs(os.path.join(self.campaign, "setup", "slots"), exist_ok=True)
        binary_a = os.path.join(self.campaign, "setup", "build", "A", "adapter")
        binary_bc = os.path.join(self.campaign, "setup", "build", "BC", "adapter")
        for path, payload in ((binary_a, b"ELF-A-binary"), (binary_bc, b"ELF-BC-binary")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(payload)
        self.binary_a, self.binary_bc = binary_a, binary_bc
        segment = build_segment()
        layouts, digests, builds = {}, {}, {}
        for arm in ("A", "BC"):
            layouts[arm], digests[arm], builds[arm] = {}, {}, {}
            for n in ("10000", "100000"):
                records = []
                for attempt in (1, 2, 3):
                    index_dir = os.path.join(self.campaign, "setup", "sizes", arm,
                                             f"n{n}-run{attempt}")
                    os.makedirs(os.path.join(index_dir, "index", "segments"))
                    with open(os.path.join(index_dir, "index", "segments", "seg-0001"),
                              "wb") as handle:
                        handle.write(segment)
                    records.append({
                        "attempt": attempt,
                        "layout": verify.independent_layout(index_dir),
                        "segment_digest": verify.independent_segment_digest(index_dir),
                    })
                builds[arm][n] = records
                layouts[arm][n] = records[-1]["layout"]
                digests[arm][n] = records[-1]["segment_digest"]
        samples = verify.BATCHED_SAMPLES if batched else verify.UNBATCHED_SAMPLES
        unit = "batch" if batched else "single_query"
        timing = "batch_ns" if batched else "engine_ns"
        slot_records = []
        base_value = 10_000_000
        for block in range(1, 5):
            for position in range(1, 7):
                arm = verify.ARM_ORDER_BY_BLOCK[block - 1][position - 1]
                slot_index = (block - 1) * 6 + position
                lane_records = []
                for lane in lanes():
                    value = base_value
                    if arm == "B":
                        value = int(base_value * self.ratios["B/A"]) if lane["id"] in \
                            verify.LOW_MATCH_LANES else base_value
                    elif arm == "C":
                        value = int(base_value * self.ratios["C/A"]) if lane["id"] in \
                            verify.LOW_MATCH_LANES else base_value
                    values = [value] * samples
                    lane_records.append({
                        "id": lane["id"], "n": lane["n"], "class": lane["class"],
                        "k": lane["k"], "field": lane["field"], "term": lane["term"],
                        "regime": lane["regime"], "arm": arm,
                        "mode": {"A": None, "B": "enabled", "C": "disabled"}[arm],
                        "binary_path": binary_a if arm == "A" else binary_bc,
                        "binary_sha256": verify.sha256_file(
                            binary_a if arm == "A" else binary_bc),
                        "sample_unit": unit, "timing_field": timing,
                        "repeat_count": verify.repeat_count_for(lane["id"]) if batched else 1,
                        "warmup_ids": [f"w{index}" for index in range(verify.WARMUPS)],
                        "samples_ns": values,
                        "summary_ns": {"median": verify.nearest_rank_median(values)},
                        "total_hits": EXPECTED["total_hits"],
                        "doc_ids": EXPECTED["doc_ids"],
                        "oracle_ok": True,
                        "analyzer": "keyword-exact",
                    })
                record = {
                    "slot_index": slot_index, "block": block, "position": position,
                    "arm": arm,
                    "source_sha": verify.BASELINE_SHA if arm == "A" else "c" * 40,
                    "executed_binary_path": binary_a if arm == "A" else binary_bc,
                    "binary_sha256": verify.sha256_file(
                        binary_a if arm == "A" else binary_bc),
                    "mode": {"A": None, "B": "enabled", "C": "disabled"}[arm],
                    "sample_unit": unit,
                    "lanes": lane_records,
                    "contention_before": {"state": "clear"},
                    "contention_after": {"state": "clear"},
                }
                slot_records.append(record)
                self.write_json(f"slots/slot-{slot_index:02d}.json", record)
        self.slots = slot_records
        self.layouts, self.digests, self.builds = layouts, digests, builds

        self.write_json("authorization.json", {
            "schema": verify.SCHEMA, "campaign": self.name, "regime": self.regime,
            "diagnostic_only": True})
        self.write_json("corpus.json", {"schema": verify.SCHEMA,
                                        "manifest_sha256": verify.CORPUS_SHA,
                                        "corpora": {}})
        self.write_json("environment.json", {
            "schema": verify.SCHEMA, "host_fingerprint": "synth-host",
            "cpu_affinity": {"mode": "PINNED", "adapter_cpu": 0, "controller_cpu": 1}})
        self.write_json("toolchain.json", {
            "schema": verify.SCHEMA, "feature": verify.SOURCE_FEATURE,
            "adapter_sha256": {"A": verify.sha256_file(binary_a),
                               "BC": verify.sha256_file(binary_bc)},
            "score_probe_path": binary_bc})
        self.write_json("source_proof.json", {
            "schema": verify.SCHEMA,
            "generic_body_sha256": source_proof_report()["generic_body_sha256"],
            "feature": verify.SOURCE_FEATURE})
        self.write_json("mode_proof.json", {
            "schema": verify.SCHEMA,
            "probes": [
                {"arm": "A", "environment_mode": None, "expected": "ok",
                 "observed_status": "ok"},
                {"arm": "B", "environment_mode": "enabled", "expected": "ok",
                 "observed_status": "ok"},
                {"arm": "C", "environment_mode": "disabled", "expected": "ok",
                 "observed_status": "ok"},
                {"arm": "INVALID", "environment_mode": "invalid-mode",
                 "expected": "error", "observed_status": "error"},
                {"arm": "MISSING", "environment_mode": None, "expected": "error",
                 "observed_status": "error"},
            ]})
        self.write_json("sizes.json", {
            "schema": verify.SCHEMA, "A": builds["A"], "BC": builds["BC"],
            "layouts": layouts, "segment_digests": digests})
        self.write_json("score_parity.json", {
            "schema": verify.SCHEMA,
            "lanes": {lane["id"]: {"total_hits": EXPECTED["total_hits"], "hits": 1,
                                   "identical": True} for lane in lanes()}})
        measurements = {
            "schema": verify.SCHEMA, "campaign": self.name, "regime": self.regime,
            "ratios": self.controller_ratios(),
            "a_drift": {lane["id"]: {"block_ratios": [1.0] * 4,
                                     "campaign_median": 1.0} for lane in lanes()},
            "diagnostic_only": True,
        }
        self.write_json("measurements.json", measurements)
        self.write_json("manifest.json", {
            "schema": verify.SCHEMA,
            "protocol_schema": verify.PROTOCOL_SCHEMA,
            "protocol_sha256": verify.sha256_file(
                os.path.join(self.root, "benchmarks", "pr15i_c",
                             "causal_protocol_v1.json")),
            "campaign": self.name, "regime": self.regime,
            "baseline_sha": verify.BASELINE_SHA,
            "candidate_sha": "c" * 40,
            "adapter_sha256": {"A": verify.sha256_file(binary_a),
                               "BC": verify.sha256_file(binary_bc)},
            "adapter_path": {"A": binary_a, "BC": binary_bc},
            "cpu_affinity": {"mode": "PINNED", "adapter_cpu": 0, "controller_cpu": 1},
        })

    def controller_ratios(self):
        ratios = {}
        for lane in lanes():
            if lane["id"] in verify.LOW_MATCH_LANES:
                ba, ca = self.ratios["B/A"], self.ratios["C/A"]
            else:
                ba, ca = 1.0, 1.0
            entry = {"B/A": [ba] * 4, "C/A": [ca] * 4, "B/C": [ba / ca] * 4,
                     "campaign_medians": {"B/A": ba, "C/A": ca, "B/C": ba / ca}}
            ratios[lane["id"]] = entry
        return ratios

    # ---- per-case mutation helpers ------------------------------------
    def mutate_json(self, relative, mutate):
        path = self.raw(relative)
        value = verify.read_json(path)
        mutate(value)
        self.write_json(relative, value)
        verify.seal_campaign_for_tests(self.campaign)


def source_proof_report():
    return {"generic_body_sha256": verify.source_proof.EXPECTED_GENERIC_BODY_SHA,
            "baseline_sha": verify.BASELINE_SHA, "candidate_sha": "c" * 40,
            "changed_production_paths": [], "causal_delta": [],
            "baseline_generic_body_sha256": verify.source_proof.EXPECTED_GENERIC_BODY_SHA,
            "generic_attributes": [], "feature": verify.SOURCE_FEATURE,
            "mode_variable": verify.MODE_VARIABLE,
            "restored_files_identical_to_historical": True}


class Matrix(unittest.TestCase):
    """One test per CV row; each builds its own synthetic campaign."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="causal-verify-")
        self._patches = []
        self.patch("A_100K_TOTAL", SYNTH_TOTAL)
        self.patch("A_100K_STORED", SYNTH_STORED)
        self.patch_obj(verify.base, "stage_lanes", lambda stage: lanes())
        self.patch_obj(verify.base.oracle, "load_and_verify",
                       lambda directory: ({}, ROWS))
        self.patch_obj(verify.base.oracle, "expected", oracle_expected)
        self.real_source_proof = verify.source_proof.verify_causal_source
        self.patch_obj(verify.source_proof, "verify_causal_source",
                       lambda root, candidate, baseline=None: source_proof_report())
        setattr(verify, "seal_campaign_for_tests", seal_campaign)
        self.addCleanup(lambda: verify.__dict__.pop("seal_campaign_for_tests", None))
        protocol_dir = os.path.join(self._tmp, "benchmarks", "pr15i_c")
        os.makedirs(protocol_dir, exist_ok=True)
        with open(os.path.join(ROOT, verify.PROTOCOL_REL), encoding="utf-8") as handle:
            protocol = json.load(handle)
        # The synthetic segment is tiny, so the copied protocol carries the
        # synthetic sentinels; every other literal stays identical and is still
        # asserted by `verify_protocol`. `test_cv35` covers a real mismatch.
        protocol["historical_100k_committed_bytes"] = SYNTH_TOTAL
        protocol["historical_100k_stored_bytes"] = SYNTH_STORED
        with open(os.path.join(protocol_dir, "causal_protocol_v1.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(protocol, handle)
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def patch(self, name, value):
        self._patches.append((verify, name, getattr(verify, name)))
        setattr(verify, name, value)

    def patch_obj(self, obj, name, value):
        self._patches.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def tearDown(self):
        for obj, name, value in reversed(self._patches):
            setattr(obj, name, value)

    def campaign(self, name="causal-unbatched-01", regime="unbatched", **kwargs):
        return SyntheticCampaign(self._tmp, name, regime, **kwargs)

    def assertRejected(self, code, call):
        with self.assertRaises(verify.VerificationFailed) as caught:
            call()
        self.assertEqual(caught.exception.rule, code)

    # CV-01..04 ---------------------------------------------------------
    def test_cv01_valid_unbatched_passes(self):
        campaign = self.campaign()
        payload = verify.verify(self._tmp, campaign.campaign, verify_only=True, write=False)
        self.assertEqual(payload["regime"], "unbatched")

    def test_cv02_valid_batched_passes(self):
        campaign = self.campaign("causal-batched-01", "batched")
        payload = verify.verify(self._tmp, campaign.campaign, verify_only=True, write=False)
        self.assertEqual(payload["regime"], "batched")

    def test_cv03_verify_only_writes_nothing(self):
        campaign = self.campaign()
        before = sorted(os.listdir(os.path.join(self._tmp, "target")))
        verify.verify(self._tmp, campaign.campaign, verify_only=True, write=False)
        self.assertEqual(sorted(os.listdir(os.path.join(self._tmp, "target"))), before)

    def test_cv04_receipt_is_created_exclusively(self):
        campaign = self.campaign()
        payload = verify.verify(self._tmp, campaign.campaign, verify_only=False, write=True)
        path = os.path.join(self._tmp, "target", "pr15i-c", "reviews",
                            "causal-unbatched-01-verification.json")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(payload["receipt_path"], path)

    # CV-05..08 ---------------------------------------------------------
    def test_cv05_missing_raw_is_rejected(self):
        campaign = self.campaign()
        os.remove(campaign.raw("score_parity.json"))
        self.assertRejected("CV_INVENTORY",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv06_extra_raw_is_rejected(self):
        campaign = self.campaign()
        campaign.write_json("extra.json", {"schema": "x"})
        self.assertRejected("CV_INVENTORY",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv07_symlinked_raw_is_rejected(self):
        campaign = self.campaign()
        target = os.path.join(self._tmp, "outside.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump({}, handle)
        link = campaign.raw("slots/slot-99.json")
        os.symlink(target, link)
        self.assertRejected("CV_PATH",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv08_path_escape_is_rejected(self):
        self.assertRejected("CV_PATH",
                            lambda: verify.canonical_campaign(self._tmp, "/tmp/elsewhere"))

    # CV-09..12 ---------------------------------------------------------
    def test_cv09_missing_seal_is_rejected(self):
        campaign = self.campaign()
        os.remove(campaign.raw("seal.json"))
        self.assertRejected("CV_SEAL",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv10_wrong_seal_is_rejected(self):
        campaign = self.campaign()
        path = campaign.raw("seal.json")
        seal = verify.read_json(path)
        seal["files"]["corpus.json"] = "0" * 64
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(seal, handle)
        self.assertRejected("CV_SEAL",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv11_resealed_forgery_is_caught_semantically(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-01.json",
                             lambda value: value["lanes"][0]["samples_ns"].__setitem__(0, -1))
        self.assertRejected("CV_SAMPLE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv12_mid_verification_change_is_rejected(self):
        campaign = self.campaign()
        original = verify.verify_oracle_and_scores

        def tamper(*args, **kwargs):
            result = original(*args, **kwargs)
            with open(campaign.raw("corpus.json"), "a", encoding="utf-8") as handle:
                handle.write("\n")
            return result

        self.patch_obj(verify, "verify_oracle_and_scores", tamper)
        self.assertRejected("CV_TAMPER",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    # CV-13..16 ---------------------------------------------------------
    def test_cv13_wrong_baseline_sha_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("manifest.json",
                             lambda value: value.update({"baseline_sha": "0" * 40}))
        self.assertRejected("CV_SOURCE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv14_non_descendant_candidate_is_rejected(self):
        with self.assertRaises(verify.source_proof.SourceProofError):
            self.real_source_proof(ROOT, verify.BASELINE_SHA, verify.BASELINE_SHA)

    def test_cv15_changed_generic_body_is_rejected(self):
        with self.assertRaises(verify.source_proof.SourceProofError):
            self.real_source_proof(
                ROOT, "50b56e9fe7b22bb266ca7b0d9e209500dfc785ff")

    def test_cv16_unauthorized_production_file_is_rejected(self):
        # Narrowing the allowlist makes the real candidate delta (which includes
        # score.rs) unauthorised, exercising the allowlist branch on real source.
        narrowed = tuple(path for path in verify.source_proof.ALLOWED_PRODUCTION_DELTA
                         if not path.endswith("score.rs"))
        self.patch_obj(verify.source_proof, "ALLOWED_PRODUCTION_DELTA", narrowed)
        with self.assertRaises(verify.source_proof.SourceProofError):
            self.real_source_proof(ROOT,
                                   "658a2dde0e15c17e2b0c92278b5c922f5260fe60")

    # CV-17..20 ---------------------------------------------------------
    def test_cv17_bc_different_realpath_is_rejected(self):
        campaign = self.campaign()
        other = os.path.join(self._tmp, "other-adapter")
        with open(campaign.binary_bc, "rb") as handle:
            payload = handle.read()
        with open(other, "wb") as handle:
            handle.write(payload)
        campaign.mutate_json("manifest.json",
                             lambda value: value["adapter_path"].update({"BC": other}))
        self.assertRejected("CV_BINARY",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv18_bc_different_bytes_is_rejected(self):
        campaign = self.campaign()
        with open(campaign.binary_bc, "ab") as handle:
            handle.write(b"tampered")
        self.assertRejected("CV_BINARY",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv19_wrong_feature_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("toolchain.json",
                             lambda value: value.update({"feature": "pr15ic-probe"}))
        self.assertRejected("CV_MODE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv20_invalid_env_mode_probe_is_rejected(self):
        campaign = self.campaign()

        def mutate(value):
            for probe in value["probes"]:
                if probe["arm"] == "INVALID":
                    probe["observed_status"] = "ok"

        campaign.mutate_json("mode_proof.json", mutate)
        self.assertRejected("CV_MODE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    # CV-21..24 ---------------------------------------------------------
    def test_cv21_batch_sample_in_unbatched_slot_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-01.json",
                             lambda value: value.update({"sample_unit": "batch"}))
        self.assertRejected("CV_UNIT",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv22_mislabeled_derived_value_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-01.json",
                             lambda value: value["lanes"][0].update(
                                 {"timing_field": "batch_ns"}))
        self.assertRejected("CV_UNIT",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv23_missing_warmup_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-01.json",
                             lambda value: value["lanes"][0].update({"warmup_ids": []}))
        self.assertRejected("CV_SAMPLE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv24_wrong_sample_count_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json(
            "slots/slot-01.json",
            lambda value: value["lanes"][0].update(
                {"samples_ns": value["lanes"][0]["samples_ns"][:-1]}))
        self.assertRejected("CV_SAMPLE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    # CV-25..28 ---------------------------------------------------------
    def test_cv25_reordered_slots_are_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-02.json",
                             lambda value: value.update({"slot_index": 99}))
        self.assertRejected("CV_SCHEDULE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv26_missing_arm_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-01.json",
                             lambda value: value.update({"arm": "B"}))
        self.assertRejected("CV_SCHEDULE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv27_malformed_schedule_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-01.json",
                             lambda value: value.update({"position": 6, "arm": "B"}))
        self.assertRejected("CV_SCHEDULE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv28_block_imbalance_is_rejected(self):
        campaign = self.campaign()
        for index in range(1, 7):
            campaign.mutate_json(f"slots/slot-{index:02d}.json",
                                 lambda value: value.update({"arm": "A"}))
        self.assertRejected("CV_SCHEDULE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    # CV-29..32 ---------------------------------------------------------
    def test_cv29_forged_oracle_hit_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-01.json",
                             lambda value: value["lanes"][0].update({"doc_ids": ["zzz"]}))
        self.assertRejected("CV_ORACLE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv30_wrong_score_parity_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("score_parity.json",
                             lambda value: value["lanes"][verify.LANE_IDS[0]].update(
                                 {"identical": False}))
        self.assertRejected("CV_SCORE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv31_missing_warmup_proof_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("mode_proof.json",
                             lambda value: value.update({"probes": value["probes"][:3]}))
        self.assertRejected("CV_MODE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv32_changed_lane_term_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-01.json",
                             lambda value: value["lanes"][0].update({"id": "pr15d_v1/1/x/k1"}))
        self.assertRejected("CV_SCHEDULE",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    # CV-33..36 ---------------------------------------------------------
    def test_cv33_changed_codec_is_rejected(self):
        campaign = self.campaign()
        with open(os.path.join(campaign.campaign, "setup", "sizes", "A",
                               "n10000-run1", "index", "segments", "seg-0001"),
                  "r+b") as handle:
            data = bytearray(handle.read())
            data[8 + 12] = 2
            handle.seek(0)
            handle.write(data)
        self.assertRejected("CV_FORMAT",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv34_changed_segment_digest_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("sizes.json", lambda value: value["A"]["10000"][0].update(
            {"segment_digest": "0" * 64}))
        self.assertRejected("CV_FORMAT",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv35_changed_sentinel_is_rejected(self):
        campaign = self.campaign()
        # Retune both the module expectation and the sealed protocol copy so the
        # protocol comparison still passes and the *layout* sentinel check fires.
        self.patch("A_100K_TOTAL", SYNTH_TOTAL + 1)
        protocol_path = os.path.join(self._tmp, "benchmarks", "pr15i_c",
                                     "causal_protocol_v1.json")
        protocol = verify.read_json(protocol_path)
        protocol["historical_100k_committed_bytes"] = SYNTH_TOTAL + 1
        with open(protocol_path, "w", encoding="utf-8") as handle:
            json.dump(protocol, handle)

        def mutate(value):
            value["protocol_sha256"] = verify.sha256_file(protocol_path)

        campaign.mutate_json("manifest.json", mutate)
        self.assertRejected("CV_FORMAT",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv36_missing_rebuild_is_rejected(self):
        campaign = self.campaign()
        shutil.rmtree(os.path.join(campaign.campaign, "setup", "sizes", "A",
                                   "n10000-run2"))
        self.assertRejected("CV_FORMAT",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    # CV-37..40 ---------------------------------------------------------
    def test_cv37_contended_slot_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("slots/slot-05.json",
                             lambda value: value.update(
                                 {"contention_after": {"state": "busy"}}))
        self.assertRejected("CV_CONTENTION",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv38_forged_reported_ratio_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_json("measurements.json",
                             lambda value: value["ratios"][verify.LANE_IDS[0]].update(
                                 {"campaign_medians": {"B/A": 9.9, "C/A": 1.0,
                                                       "B/C": 9.9}}))
        self.assertRejected("CV_RATIO",
                            lambda: verify.verify(self._tmp, campaign.campaign, True, False))

    def test_cv39_forged_classification_cannot_override_raw(self):
        ratios = {}
        for lane in verify.LOW_MATCH_LANES:
            ratios[lane] = {"campaign_medians": {"B/A": 1.7, "C/A": 1.0, "B/C": 1.7},
                            "B/A": [1.7] * 4, "C/A": [1.0] * 4, "B/C": [1.7] * 4,
                            "A/A_drift_median": 1.0}
        result = verify.independently_classify({"c1": ratios, "c2": ratios}, "unbatched")
        self.assertEqual(result["classification"], "CAUSAL_OPERATOR_DOMINANT")
        unstable = {lane: {**value, "A/A_drift_median": 1.40}
                    for lane, value in ratios.items()}
        self.assertEqual(
            verify.independently_classify({"c1": unstable, "c2": unstable},
                                          "unbatched")["classification"],
            "CAUSAL_UNBATCHED_UNSTABLE")

    def test_cv40_receipt_overwrite_is_refused(self):
        campaign = self.campaign()
        verify.verify(self._tmp, campaign.campaign, False, True)
        self.assertRejected("CV_RECEIPT",
                            lambda: verify.verify(self._tmp, campaign.campaign, False, True))


def seal_campaign(campaign):
    files = {}
    for relative in REQUIRED_RAW_FOR_SEAL:
        path = os.path.join(campaign, "raw", relative)
        files[relative] = verify.sha256_file(path)
    path = os.path.join(campaign, "raw", "seal.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schema": verify.SEAL_SCHEMA, "files": files}, handle)


REQUIRED_RAW_FOR_SEAL = verify.REQUIRED_RAW


if __name__ == "__main__":
    unittest.main()

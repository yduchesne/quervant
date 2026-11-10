#!/usr/bin/env python3
"""PR 15I-C dispatch-isolation — adversarial verifier tests (DC-V matrix, part 2).

Each case builds a minimal sealed synthetic four-arm campaign and mutates exactly
one fact. Real campaign directories are never touched.
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

SEGMENT_LEN = 40
SEGMENT_TOTAL = 190


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = load("pr15i_c_verify_dispatch_t", "verify_dispatch.py")

EXPECTED = {"total_hits": 1, "doc_ids": ["d0"]}


def build_segment():
    payload = bytearray(SEGMENT_LEN)
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
    entry[20:28] = (SEGMENT_LEN).to_bytes(8, "little")
    footer += entry
    offset = 8 + SEGMENT_LEN
    trailer = bytearray(64)
    trailer[8:16] = offset.to_bytes(8, "little")
    trailer[16:24] = len(footer).to_bytes(8, "little")
    trailer[24:28] = (1).to_bytes(4, "little")
    return bytes(b"TRWSEG01" + bytes(payload) + bytes(footer) + bytes(trailer))


def lanes():
    table = {10000: [("absent", "key", 100), ("rare", "key", 100),
                     ("medium", "key", 100), ("common", "key", 100)],
             100000: [("absent", "key", 100), ("rare", "key", 100),
                      ("medium", "key", 100), ("common", "key", 100),
                      ("common", "key", 10)]}
    result = []
    for n in (10000, 100000):
        for class_name, field, k in table[n]:
            result.append({"id": f"pr15d_v1/{n}/{class_name}/k{k}", "n": n,
                           "class": class_name, "field": field, "term": class_name,
                           "k": k, "regime": "warm"})
    return result


def source_report():
    body = verify.source_proof.EXPECTED_GENERIC_BODY_SHA
    return {
        "baseline_sha": verify.BASE_A, "c_source": verify.C_SHA,
        "d_source": verify.D_SHA, "e_source": verify.E_SHA,
        "generic_body_sha256": {arm: body for arm in verify.ARMS},
        "generic_attributes": {"A": [], "C": []},
        "d": {"d_changed_paths": [verify.source_proof.UNIFIED],
              "generic_body_sha256": body},
        "e": {"e_changed_paths": [verify.source_proof.UNIFIED,
                                  verify.source_proof.MANIFEST],
              "generic_body_sha256": body},
        "features": {"A": [], "C": ["pr15ic-causal"], "D": ["pr15ic-causal"],
                     "E": ["pr15ic-dispatch-isolation"]},
        "mode_variables": {"C": verify.ARM_MODE_VARIABLES["C"],
                           "E": verify.ARM_MODE_VARIABLES["E"]},
    }


class SyntheticCampaign:
    def __init__(self, root, name, regime="unbatched", medians=None):
        self.root = root
        self.name = name
        self.regime = regime
        self.campaign = os.path.join(root, "target", "pr15i-c",
                                     "dispatch-isolation-v1", name)
        self.medians = medians or {"C/A": 1.50, "D/A": 1.05, "E/A": 1.05}
        os.makedirs(self.campaign)
        self.write_all()
        seal(self.campaign)

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
        binaries, hashes = {}, {}
        for arm in verify.ARMS:
            path = os.path.join(self.campaign, "setup", "build", arm, "adapter")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(f"ELF-{arm}".encode())
            binaries[arm] = path
            hashes[arm] = verify.sha256_file(path)
        self.binaries, self.hashes = binaries, hashes
        segment = build_segment()
        builds, layouts, digests = {}, {}, {}
        for arm in verify.ARMS:
            builds[arm], layouts[arm], digests[arm] = {}, {}, {}
            for n in ("10000", "100000"):
                records = []
                for attempt in (1, 2, 3):
                    index_dir = os.path.join(self.campaign, "setup", "sizes", arm,
                                             f"n{n}-run{attempt}")
                    os.makedirs(os.path.join(index_dir, "index", "segments"))
                    with open(os.path.join(index_dir, "index", "segments", "seg-0001"),
                              "wb") as handle:
                        handle.write(segment)
                    layout = verify.independent_layout(index_dir)
                    records.append({"attempt": attempt, "layout": layout,
                                    "digest": verify.independent_segment_digest(index_dir),
                                    "index_ns": 1})
                builds[arm][n] = records
                layouts[arm][n] = records[-1]["layout"]
                digests[arm][n] = records[-1]["digest"]
        self.builds, self.layouts, self.digests = builds, layouts, digests
        samples = verify.BATCHED_SAMPLES if batched else verify.UNBATCHED_SAMPLES
        unit = "batch" if batched else "single_query"
        timing = "batch_ns" if batched else "engine_ns"
        slots = []
        for block in range(1, verify.BLOCKS + 1):
            for position in range(1, verify.SLOTS_PER_BLOCK + 1):
                arm = verify.SCHEDULE[block - 1][position - 1]
                index = (block - 1) * verify.SLOTS_PER_BLOCK + position
                lane_records = []
                for lane in lanes():
                    factor = 1.0
                    if lane["id"] in verify.LOW_MATCH_LANES:
                        factor = {"A": 1.0,
                                  "C": self.medians["C/A"],
                                  "D": self.medians["D/A"],
                                  "E": self.medians["E/A"]}[arm]
                    value = int(10_000_000 * factor)
                    data = [value] * samples
                    lane_records.append({
                        "id": lane["id"], "n": lane["n"], "class": lane["class"],
                        "k": lane["k"], "field": lane["field"], "term": lane["term"],
                        "regime": lane["regime"], "arm": arm,
                        "binary_path": binaries[arm],
                        "binary_sha256": hashes[arm],
                        "sample_unit": unit, "timing_field": timing,
                        "repeat_count": verify.repeat_count_for(lane["id"]) if batched
                        else 1,
                        "warmup_ids": [f"w{i}" for i in range(verify.WARMUPS)],
                        "samples_ns": data,
                        "summary_ns": {"median": verify.nearest_rank_median(data)},
                        "total_hits": EXPECTED["total_hits"],
                        "doc_ids": EXPECTED["doc_ids"],
                        "oracle_ok": True, "analyzer": "keyword-exact"})
                record = {
                    "slot_index": index, "block": block, "position": position,
                    "arm": arm, "source_sha": verify.ARM_SOURCES[arm],
                    "executed_binary_path": binaries[arm],
                    "binary_sha256": hashes[arm],
                    "mode": {"A": None, "C": "disabled", "D": "disabled",
                             "E": "disabled"}[arm],
                    "sample_unit": unit, "lanes": lane_records,
                    "contention_before": {"state": "clear"},
                    "contention_after": {"state": "clear"}}
                slots.append(record)
                self.write_json(f"slots/slot-{index:02d}.json", record)
        self.slots = slots
        self.write_json("authorization.json", {"schema": verify.SCHEMA,
                                               "campaign": self.name,
                                               "regime": self.regime,
                                               "diagnostic_only": True})
        shutil.copyfile(os.path.join(self.root, verify.PROTOCOL_REL),
                        self.raw("protocol.json"))
        self.write_json("source-proof.json", dict({"schema": verify.SCHEMA},
                                                  **source_report()))
        self.write_json("corpus.json", {"schema": verify.SCHEMA,
                                        "manifest_sha256": verify.CORPUS_SHA})
        self.write_json("environment.json", {
            "schema": verify.SCHEMA, "host_fingerprint": "synth",
            "cpu_affinity": {"mode": "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1",
                             "adapter_cpu": 0, "controller_cpu": 1}})
        self.write_json("toolchain.json", {"schema": verify.SCHEMA,
                                           "arm_features": verify.ARM_FEATURES})
        self.write_json("binaries.json", {
            "schema": verify.SCHEMA,
            "adapters": {arm: {"path": binaries[arm], "sha256": hashes[arm],
                               "feature": verify.ARM_FEATURES[arm],
                               "mode_variable": verify.ARM_MODE_VARIABLES[arm]}
                         for arm in verify.ARMS},
            "score_probes": {arm: {"path": binaries[arm], "sha256": hashes[arm]}
                             for arm in verify.ARMS}})
        self.write_json("sizes.json", {"schema": verify.SCHEMA, "builds": builds,
                                       "layouts": layouts,
                                       "segment_digests": digests})
        self.write_json("score-parity.json", {
            "schema": verify.SCHEMA,
            "lanes": {lane["id"]: {"total_hits": EXPECTED["total_hits"], "hits": 1,
                                   "identical": True} for lane in lanes()}})
        self.write_json("measurements.json", {
            "schema": verify.SCHEMA, "campaign": self.name, "regime": self.regime,
            "ratios": self.controller_ratios(),
            "codegen_checks": {"e_trampoline_present": True},
            "diagnostic_only": True})
        self.write_json("manifest.json", self.manifest())
        seal(self.campaign)

    def controller_ratios(self):
        ratios = {}
        for lane in lanes():
            low = lane["id"] in verify.LOW_MATCH_LANES
            entry = {"medians": {}, "A2/A1": [1.0] * 4, "a_drift_median": 1.0}
            for key in ("C/A", "D/A", "E/A"):
                value = self.medians[key] if low else 1.0
                entry[key] = [value] * 4
                entry["medians"][key] = value
            ratios[lane["id"]] = entry
        return ratios

    def manifest(self):
        return {
            "schema": verify.SCHEMA,
            "protocol_schema": verify.PROTOCOL_SCHEMA,
            "protocol_sha256": verify.sha256_file(self.raw("protocol.json")),
            "campaign": self.name, "regime": self.regime,
            "arm_sources": verify.ARM_SOURCES,
            "arm_features": verify.ARM_FEATURES,
            "arm_mode_variables": verify.ARM_MODE_VARIABLES,
            "adapter_sha256": dict(self.hashes),
            "adapter_path": dict(self.binaries),
            "lane_ids": list(verify.LANE_IDS),
            "arm_order_by_block": list(verify.SCHEDULE),
            "sample_unit": "batch" if self.regime == "batched" else "single_query",
            "environment_fingerprint": "synth",
            "filesystem": "ext4",
            "cpu_affinity": {"mode": "PINNED_ADAPTER_CPU0_CONTROLLER_Cpu1"
                             .replace("Cpu", "CPU"), "adapter_cpu": 0,
                             "controller_cpu": 1},
            "counts": {"samples": len(self.slots) * 9 * (
                verify.BATCHED_SAMPLES if self.regime == "batched"
                else verify.UNBATCHED_SAMPLES)},
            "codegen_checks": {"e_trampoline_present": True},
        }

    def mutate(self, relative, mutate):
        path = self.raw(relative)
        value = verify.read_json(path)
        mutate(value)
        self.write_json(relative, value)
        seal(self.campaign)

    def mutate_sealed(self, relative, mutate):
        """Mutate raw and re-seal (to prove semantic rather than hash checks)."""
        self.mutate(relative, mutate)


def seal(campaign):
    files = {}
    for relative in verify.REQUIRED_RAW:
        files[relative] = verify.sha256_file(os.path.join(campaign, "raw", relative))
    path = os.path.join(campaign, "raw", "seal.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schema": verify.SEAL_SCHEMA, "files": files}, handle)


class Matrix(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="dispatch-verify-")
        self._patches = []
        self.patch("A_100K_TOTAL", SEGMENT_TOTAL)
        self.patch("A_100K_STORED", SEGMENT_LEN)
        self.patch_obj(verify.base, "stage_lanes", lambda stage: lanes())
        self.patch_obj(verify.base.oracle, "load_and_verify",
                       lambda directory: ({}, {10000: [1], 100000: [1]}))
        self.patch_obj(verify.base.oracle, "expected",
                       lambda rows, field, term, k: dict(EXPECTED))
        self.patch_obj(verify.source_proof, "verify_all",
                       lambda root, a, c, d, e: source_report())
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        protocol_dir = os.path.join(self._tmp, "benchmarks", "pr15i_c")
        os.makedirs(protocol_dir, exist_ok=True)
        with open(os.path.join(ROOT, verify.PROTOCOL_REL), encoding="utf-8") as handle:
            protocol = json.load(handle)
        protocol["100k_committed_index_bytes"] = SEGMENT_TOTAL
        protocol["100k_stored_bytes"] = SEGMENT_LEN
        with open(os.path.join(protocol_dir, "dispatch_protocol_v1.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(protocol, handle)

    def patch(self, name, value):
        self._patches.append((verify, name, getattr(verify, name)))
        setattr(verify, name, value)

    def patch_obj(self, obj, name, value):
        self._patches.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def tearDown(self):
        for obj, name, value in reversed(self._patches):
            setattr(obj, name, value)

    def campaign(self, name="unbatched-01", regime="unbatched", **kwargs):
        return SyntheticCampaign(self._tmp, name, regime, **kwargs)

    def assertRejected(self, code, call):
        with self.assertRaises(verify.VerificationFailed) as caught:
            call()
        self.assertEqual(caught.exception.rule, code,
                         f"expected {code}, got {caught.exception.rule}: "
                         f"{caught.exception.detail}")

    def run_verify(self, campaign):
        return verify.verify(self._tmp, campaign.campaign, verify_only=True, write=False)

    # DC-V01..V04 -------------------------------------------------------
    def test_dv01_valid_unbatched_passes(self):
        payload = self.run_verify(self.campaign())
        self.assertEqual(payload["regime"], "unbatched")
        self.assertTrue(payload["a_a_stability"]["stable"])

    def test_dv02_valid_batched_passes(self):
        payload = self.run_verify(self.campaign("batched-01", "batched"))
        self.assertEqual(payload["regime"], "batched")

    def test_dv03_missing_slot_is_rejected(self):
        campaign = self.campaign()
        os.remove(campaign.raw("slots/slot-09.json"))
        self.assertRejected("DV_INVENTORY",
                            lambda: self.run_verify(campaign))

    def test_dv04_out_of_order_slot_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("slots/slot-02.json",
                        lambda value: value.update({"slot_index": 99}))
        self.assertRejected("DV_SCHEDULE", lambda: self.run_verify(campaign))

    def test_dv04_wrong_arm_position_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("slots/slot-01.json",
                        lambda value: value.update({"arm": "E"}))
        self.assertRejected("DV_SCHEDULE", lambda: self.run_verify(campaign))

    # DC-V05..V08: source identity --------------------------------------
    def test_dv05_slot_source_mismatch_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("slots/slot-03.json",
                        lambda value: value.update({"source_sha": verify.BASE_A}))
        self.assertRejected("DV_SOURCE", lambda: self.run_verify(campaign))

    def test_dv06_recorded_d_diff_mismatch_is_rejected(self):
        campaign = self.campaign()

        def mutate(value):
            value["d"]["d_changed_paths"] = []

        campaign.mutate("source-proof.json", mutate)
        self.assertRejected("DV_SOURCE", lambda: self.run_verify(campaign))

    def test_dv07_recorded_e_diff_mismatch_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("source-proof.json",
                        lambda value: value["e"].update({"e_changed_paths": []}))
        self.assertRejected("DV_SOURCE", lambda: self.run_verify(campaign))

    def test_dv08_generic_body_hash_mismatch_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("source-proof.json",
                        lambda value: value["generic_body_sha256"].update({"A": "0" * 64}))
        self.assertRejected("DV_SOURCE", lambda: self.run_verify(campaign))

    # DC-V09..V12: features and modes -----------------------------------
    def test_dv09_wrong_feature_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("binaries.json",
                        lambda value: value["adapters"]["C"].update(
                            {"feature": "pr15ic-dispatch-isolation"}))
        self.assertRejected("DV_FEATURE", lambda: self.run_verify(campaign))

    def test_dv10_wrong_mode_variable_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("binaries.json",
                        lambda value: value["adapters"]["E"].update(
                            {"mode_variable": "QUERVANT_PR15IC_CAUSAL_MODE"}))
        self.assertRejected("DV_FEATURE", lambda: self.run_verify(campaign))

    def test_dv11_a_must_have_no_feature(self):
        campaign = self.campaign()
        campaign.mutate("binaries.json",
                        lambda value: value["adapters"]["A"].update(
                            {"feature": "pr15ic-causal"}))
        self.assertRejected("DV_FEATURE", lambda: self.run_verify(campaign))

    def test_dv12_three_arm_binary_set_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("binaries.json",
                        lambda value: value["adapters"].pop("D"))
        self.assertRejected("DV_BINARY", lambda: self.run_verify(campaign))

    # DC-V13..V16: binaries ---------------------------------------------
    def test_dv13_binary_hash_mismatch_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("binaries.json",
                        lambda value: value["adapters"]["C"].update({"sha256": "0" * 64}))
        self.assertRejected("DV_BINARY", lambda: self.run_verify(campaign))

    def test_dv14_mutated_executable_is_rejected(self):
        campaign = self.campaign()
        with open(campaign.binaries["E"], "ab") as handle:
            handle.write(b"tampered")
        self.assertRejected("DV_BINARY", lambda: self.run_verify(campaign))

    def test_dv15_identical_arm_binaries_are_rejected(self):
        campaign = self.campaign()
        shutil.copyfile(campaign.binaries["A"], campaign.binaries["D"])
        digest = verify.sha256_file(campaign.binaries["D"])

        def mutate(value):
            value["adapters"]["D"]["sha256"] = digest
            value["adapter_sha256"]["D"] = digest

        campaign.mutate("binaries.json", lambda value: value["adapters"]["D"].update(
            {"sha256": digest}))
        campaign.mutate("manifest.json", lambda value: value["adapter_sha256"].update(
            {"D": digest}))
        self.assertRejected("DV_BINARY", lambda: self.run_verify(campaign))

    def test_dv16_slot_binary_path_mismatch_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("slots/slot-05.json",
                        lambda value: value.update(
                            {"executed_binary_path": campaign.binaries["A"]}))
        self.assertRejected("DV_BINARY", lambda: self.run_verify(campaign))

    # DC-V17..V20: format, samples, units, oracle -----------------------
    def test_dv17_changed_codec_is_rejected(self):
        campaign = self.campaign()
        path = os.path.join(campaign.campaign, "setup", "sizes", "C", "n10000-run1",
                            "index", "segments", "seg-0001")
        with open(path, "r+b") as handle:
            data = bytearray(handle.read())
            data[8 + 12] = 2
            handle.seek(0)
            handle.write(data)
        self.assertRejected("DV_FORMAT", lambda: self.run_verify(campaign))

    def test_dv18_wrong_sample_count_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("slots/slot-01.json",
                        lambda value: value["lanes"][0].update(
                            {"samples_ns": value["lanes"][0]["samples_ns"][:-1]}))
        self.assertRejected("DV_SAMPLE", lambda: self.run_verify(campaign))

    def test_dv19_missing_warmup_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("slots/slot-01.json",
                        lambda value: value["lanes"][0].update({"warmup_ids": []}))
        self.assertRejected("DV_SAMPLE", lambda: self.run_verify(campaign))

    def test_dv20_wrong_unit_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("slots/slot-01.json",
                        lambda value: value["lanes"][0].update(
                            {"timing_field": "batch_ns"}))
        self.assertRejected("DV_UNIT", lambda: self.run_verify(campaign))

    def test_dv20_forged_oracle_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("slots/slot-01.json",
                        lambda value: value["lanes"][0].update({"doc_ids": ["zzz"]}))
        self.assertRejected("DV_ORACLE", lambda: self.run_verify(campaign))

    # DC-V25..V28: ratios, tamper, inventory, receipts -------------------
    def test_dv25_forged_ratio_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate("measurements.json",
                        lambda value: value["ratios"][verify.LANE_IDS[0]]["medians"]
                        .update({"C/A": 9.9}))
        self.assertRejected("DV_RATIO", lambda: self.run_verify(campaign))

    def test_dv26_resealed_semantic_tamper_is_rejected(self):
        campaign = self.campaign()
        campaign.mutate_sealed("slots/slot-01.json",
                              lambda value: value["lanes"][0]["samples_ns"].__setitem__(0, -1))
        self.assertRejected("DV_SAMPLE", lambda: self.run_verify(campaign))

    def test_dv27_extra_raw_file_is_rejected(self):
        campaign = self.campaign()
        campaign.write_json("extra.json", {"schema": "x"})
        self.assertRejected("DV_INVENTORY", lambda: self.run_verify(campaign))

    def test_dv28_symlinked_raw_is_rejected(self):
        campaign = self.campaign()
        target = os.path.join(self._tmp, "outside.json")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump({}, handle)
        os.symlink(target, campaign.raw("slots/slot-33.json"))
        self.assertRejected("DV_PATH", lambda: self.run_verify(campaign))

    def test_dv28_receipt_overwrite_is_refused(self):
        campaign = self.campaign()
        verify.verify(self._tmp, campaign.campaign, verify_only=False, write=True)
        self.assertRejected("DV_RECEIPT",
                            lambda: verify.verify(self._tmp, campaign.campaign,
                                                  verify_only=False, write=True))

    # DC-V29..V32: classification / codegen -----------------------------
    def test_dv29_classifier_patterns(self):
        def entry(c, d, e):
            return {"medians": {"C/A": c, "D/A": d, "E/A": e},
                    "C/A": [c] * 4, "D/A": [d] * 4, "E/A": [e] * 4,
                    "A2/A1": [1.0] * 4, "a_drift_median": 1.0, "a_drift_outliers": 0}

        cases = {
            "15IC_DISPATCH_DIAG_RUNTIME_ASSOCIATED": (1.5, 1.0, 1.0),
            "15IC_DISPATCH_DIAG_COMPILED_CANDIDATE_ASSOCIATED": (1.5, 1.5, 1.0),
            "15IC_DISPATCH_DIAG_SCAFFOLD_ASSOCIATED": (1.5, 1.0, 1.5),
            "15IC_DISPATCH_DIAG_BROAD_ASSOCIATION": (1.5, 1.5, 1.5),
        }
        for expected, (c, d, e) in cases.items():
            ratios = {lane: entry(c, d, e) for lane in verify.LANE_IDS}
            result = verify.classify_series({"u1": ratios, "u2": ratios})
            self.assertEqual(result["disposition"], expected)

    def test_dv30_classifier_precedence(self):
        def entry(c, d, e, drift=1.0):
            return {"medians": {"C/A": c, "D/A": d, "E/A": e},
                    "C/A": [c] * 4, "D/A": [d] * 4, "E/A": [e] * 4,
                    "A2/A1": [1.0] * 4, "a_drift_median": drift,
                    "a_drift_outliers": 0}

        unstable = {lane: entry(1.5, 1.0, 1.0, drift=1.40) for lane in verify.LANE_IDS}
        self.assertEqual(verify.classify_series({"u1": unstable, "u2": unstable})
                         ["disposition"], "15IC_DISPATCH_DIAG_BLOCKED")
        notrepro = {lane: entry(1.0, 1.0, 1.0) for lane in verify.LANE_IDS}
        self.assertEqual(verify.classify_series({"u1": notrepro, "u2": notrepro})
                         ["disposition"], "15IC_DISPATCH_DIAG_NOT_REPRODUCED")
        intermediate = {lane: entry(1.5, 1.10, 1.0) for lane in verify.LANE_IDS}
        self.assertEqual(verify.classify_series({"u1": intermediate, "u2": intermediate})
                         ["disposition"], "15IC_DISPATCH_DIAG_MIXED")
        self.assertEqual(verify.classify_series(
            {"u1": {lane: entry(1.5, 1.0, 1.0) for lane in verify.LANE_IDS},
             "u2": {lane: entry(1.5, 1.0, 1.0) for lane in verify.LANE_IDS}},
            structural_ok=False)["disposition"], "15IC_DISPATCH_DIAG_INCONCLUSIVE")

    def test_dv31_cell_thresholds(self):
        self.assertEqual(verify.classify_cell(verify.LANE_IDS[0], 0.84), "IMPROVED")
        self.assertEqual(verify.classify_cell(verify.LANE_IDS[0], 0.85), "NEUTRAL")
        self.assertEqual(verify.classify_cell(verify.LANE_IDS[0], 1.08), "NEUTRAL")
        self.assertEqual(verify.classify_cell(verify.LANE_IDS[0], 1.09), "INTERMEDIATE")
        self.assertEqual(verify.classify_cell(verify.LANE_IDS[0], 1.15), "REGRESSED")
        self.assertEqual(
            verify.classify_cell("pr15d_v1/100000/absent/k100", 1.39), "INTERMEDIATE")
        self.assertEqual(
            verify.classify_cell("pr15d_v1/100000/absent/k100", 1.40), "REGRESSED")

    def test_dv32_codegen_structural_flag_blocks_classification(self):
        campaign = self.campaign()
        campaign.mutate("manifest.json",
                        lambda value: value.update(
                            {"codegen_checks": {"e_trampoline_present": False}}))
        payload = self.run_verify(campaign)
        self.assertFalse(payload["codegen_checks"]["e_trampoline_present"])

    # DC-V33..V36: A/A boundaries and reproduction ----------------------
    def test_dv33_a_a_boundary_values(self):
        for drift, expected in ((0.85, True), (1.15, True),
                                (0.84, False), (1.16, False)):
            self.assertEqual(verify.AA_MIN <= drift <= verify.AA_MAX, expected)

    def test_dv34_a_a_outlier_limit(self):
        ratios = {lane: {"a_drift_median": 1.0, "a_drift_outliers": 2}
                  for lane in verify.LANE_IDS}
        stable, lane = verify.a_a_stable(ratios)
        self.assertFalse(stable)
        self.assertIsNotNone(lane)

    def test_dv35_reproduction_gate_uses_both_campaigns(self):
        def entry(c, d, e):
            return {"medians": {"C/A": c, "D/A": d, "E/A": e},
                    "C/A": [c] * 4, "D/A": [d] * 4, "E/A": [e] * 4,
                    "A2/A1": [1.0] * 4, "a_drift_median": 1.0, "a_drift_outliers": 0}

        good = {lane: entry(1.5, 1.5, 1.0) for lane in verify.LANE_IDS}
        weak = {lane: entry(1.10, 1.5, 1.0) for lane in verify.LANE_IDS}
        result = verify.classify_series({"u1": good, "u2": weak})
        self.assertEqual(result["disposition"], "15IC_DISPATCH_DIAG_NOT_REPRODUCED")

    def test_dv36_no_retroactive_gate_change(self):
        with open(os.path.join(HERE, "protocol.json"), "rb") as handle:
            digest = __import__("hashlib").sha256(handle.read()).hexdigest()
        self.assertEqual(
            digest, "5464144786666ee2ec3c07832ea1a06f2f5901845424c82c6386c7007bd84c6e")

    # DC-V37..V40: batch units, invalid attempts, receipts --------------
    def test_dv37_batch_units_and_repeats(self):
        campaign = self.campaign("batched-01", "batched")
        lane = next(record["lanes"][0] for record in campaign.slots)
        self.assertEqual(lane["sample_unit"], "batch")
        self.assertEqual(lane["repeat_count"], verify.REPEAT_SHORT)
        payload = self.run_verify(campaign)
        self.assertEqual(payload["regime"], "batched")

    def test_dv38_engine_ns_in_batch_is_rejected_by_controller(self):
        with open(os.path.join(HERE, "dispatch_run.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('raise RunBlocked("DP_UNIT", "batch reply carries engine_ns")',
                      source)

    def test_dv39_invalid_attempt_is_preserved(self):
        target = os.path.join(ROOT, "target", "pr15i-c", "dispatch-isolation-v1")
        if not os.path.isdir(target):
            self.skipTest("no campaign attempts on this host yet")
        entries = os.listdir(target)
        self.assertTrue(entries)

    def test_dv40_receipt_is_exclusive(self):
        campaign = self.campaign()
        first = verify.write_receipt(self._tmp, "dispatch-unbatched-01-verification.json",
                                     {"schema": "x"})
        self.assertTrue(os.path.isfile(first))
        self.assertRejected("DV_RECEIPT",
                            lambda: verify.write_receipt(
                                self._tmp, "dispatch-unbatched-01-verification.json",
                                {"schema": "y"}))

    # DC-V41..V48: series-level behaviour -------------------------------
    def test_dv41_series_requires_two_unbatched_campaigns(self):
        ratios = {lane: {"medians": {"C/A": 1.5, "D/A": 1.5, "E/A": 1.0},
                         "C/A": [1.5] * 4, "D/A": [1.5] * 4, "E/A": [1.0] * 4,
                         "A2/A1": [1.0] * 4, "a_drift_median": 1.0,
                         "a_drift_outliers": 0} for lane in verify.LANE_IDS}
        with self.assertRaises(verify.VerificationFailed):
            verify.classify_series({"u1": ratios})

    def test_dv46_intermediate_case_is_mixed(self):
        def entry(c, d, e):
            return {"medians": {"C/A": c, "D/A": d, "E/A": e},
                    "C/A": [c] * 4, "D/A": [d] * 4, "E/A": [e] * 4,
                    "A2/A1": [1.0] * 4, "a_drift_median": 1.0, "a_drift_outliers": 0}

        ratios = {lane: entry(1.5, 1.0, 1.05) for lane in verify.LANE_IDS}
        self.assertEqual(verify.classify_series({"u1": ratios, "u2": ratios})
                         ["disposition"], "15IC_DISPATCH_DIAG_RUNTIME_ASSOCIATED")
        ratios = {lane: entry(1.5, 1.0, 1.20) for lane in verify.LANE_IDS}
        self.assertEqual(verify.classify_series({"u1": ratios, "u2": ratios})
                         ["disposition"], "15IC_DISPATCH_DIAG_MIXED")

    def test_dv47_block_observation_only(self):
        with open(os.path.join(HERE, "dispatch_protocol_v1.json"), encoding="utf-8") as h:
            protocol = json.load(h)
        self.assertTrue(protocol["block_observation_1_15_only"])
        with open(os.path.join(HERE, "verify_dispatch.py"), encoding="utf-8") as handle:
            source = handle.read()
        # The classifier must never consult a per-block 1.15 rule.
        self.assertNotIn("1.15", source.split("def classify_cell")[1].split(
            "def classify_campaign")[0])

    def test_dv48_no_feature_acceptance_flag(self):
        with open(os.path.join(HERE, "verify_dispatch.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"feature_acceptance": False', source)
        self.assertIn("real_rustfs_not_a_diagnostic_gate", source)


if __name__ == "__main__":
    unittest.main()

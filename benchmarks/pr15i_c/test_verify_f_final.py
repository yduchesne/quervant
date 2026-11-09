#!/usr/bin/env python3
"""Adversarial tests for the PR 15I-C-F independent verifier."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import verify_f_final as vf  # noqa: E402
import f_final_source_proof as proof_module  # noqa: E402

SCHEMA = vf.SCHEMA


class Fixture:
    """Build a self-consistent campaign tree under a temporary checkout root."""

    def __init__(self, root, name="unbatched-01", lane_scale=None):
        self.root = os.path.realpath(root)
        self.name = name
        self.regime = vf.REGIME[name]
        self.lane_scale = dict(lane_scale or {})
        self.path = os.path.join(self.root, vf.ALLOWED, name)
        self.raw = os.path.join(self.path, "raw")
        os.makedirs(os.path.join(self.raw, "slots"))
        self.data = {}
        self.binaries = {}
        self.samples = {}
        self.build()

    # ---- helpers ---------------------------------------------------------
    def write(self, relative, payload):
        path = os.path.join(self.raw, relative)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        self.data[relative] = payload

    def binary(self, tag, payload):
        directory = os.path.join(self.root, "bin")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"adapter-{tag}")
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def lane_ratio(self, lane_id):
        return self.lane_scale.get(lane_id)

    def lane_ratio_for(self, lane_id, arm):
        if lane_id in vf.LOW_MATCH_10K:
            ratios = {"A": 1.0, "C": 1.5, "G": 1.0, "P": 0.95}
        elif lane_id in vf.LOW_MATCH_100K:
            ratios = {"A": 1.0, "C": 1.6, "G": 1.0, "P": 0.97}
        else:
            ratios = {"A": 1.0, "C": 1.02, "G": 1.0, "P": 0.96}
        override = self.lane_ratio(lane_id)
        if override is not None:
            if isinstance(override, dict):
                ratios.update(override)
            else:
                ratios[arm] = override
        value = ratios[arm]
        return value(ratios) if callable(value) else value

    def lane_median(self, lane_id, arm, block, position):
        ratio = self.lane_ratio_for(lane_id, arm)
        base = int(100_000 * ratio) + (block - 1)
        if arm == "A" and position == 2:
            base = int(base * (1.0 + 0.002 * block))
        return max(1, base)

    def samples_for(self, median):
        count = vf.BATCHED if self.regime == "batched" else vf.UNBATCHED
        values = [median - 2, median - 1] + [median] * (count - 2)
        assert vf.nearest_rank_median(values) == median
        return values[:count]

    # ---- construction ----------------------------------------------------
    def build(self):
        adapters = {"A": self.binary("A", b"arm-a"),
                    "C": self.binary("C", b"arm-c"),
                    "F": self.binary("F", b"arm-f")}
        self.binaries = adapters
        probes = {arm: self.binary(f"probe-{arm}", f"probe-{arm}".encode())
                  for arm in vf.ARMS}
        with open(os.path.join(self.root, "Cargo.lock"), "w", encoding="utf-8") as handle:
            handle.write("# lock\n")
        os.makedirs(os.path.dirname(os.path.join(self.root, vf.PROTOCOL_REL)),
                    exist_ok=True)
        with open(os.path.join(self.root, vf.PROTOCOL_REL), "w", encoding="utf-8") as handle:
            with open(os.path.join(os.path.dirname(HERE), "pr15i_c",
                                   "f_final_protocol_v1.json"), encoding="utf-8") as src:
                handle.write(src.read())
        shutil.copyfile(os.path.join(self.root, vf.PROTOCOL_REL),
                        os.path.join(self.raw, "protocol.json"))
        self.data["protocol.json"] = json.load(open(
            os.path.join(self.raw, "protocol.json"), encoding="utf-8"))
        self.write("authorization.json", {
            "schema": SCHEMA, "campaign": self.name, "regime": self.regime,
            "diagnostic_only": True, "idle_authorized_by_user": True,
            "native_filesystem": "ext4",
            "cpu_affinity": {"mode": "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1",
                             "adapter_cpu": 0, "controller_cpu": 1},
            "arm_sources": {"A": vf.BASE_A, "C": vf.CAUSAL, "F": vf.F_DIAG},
            "arm_features": {"A": None, "C": vf.F_FEATURE, "F": vf.F_FEATURE},
            "arm_modes": {"A": None, "C": "disabled", "G": "disabled",
                          "P": "enabled"},
        })
        self.write("source-proof.json", {
            "schema": SCHEMA, "candidate_sha": vf.F_DIAG,
            "generic_body_sha256":
                "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994",
            "physical_body_sha256": "522f6600f0efa24f",
        })
        self.write("corpus.json", {"schema": SCHEMA,
                                   "manifest_sha256": vf.CORPUS_SHA,
                                   "corpora": [{"sha256": vf.CORPUS_SHA}]})
        self.write("environment.json", {
            "schema": SCHEMA, "host_fingerprint": {"cpu": "test-cpu"},
            "filesystem": "ext4",
            "cpu_affinity": {"mode": "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1"},
            "environment": {}})
        self.write("toolchain.json", {
            "schema": SCHEMA, "rustc": "rustc 1.98.1 (test)", "cargo": "cargo 1.98.1",
            "cargo_lock_sha256": vf.sha256_file(os.path.join(self.root, "Cargo.lock")),
            "arm_features": {"A": None, "C": vf.F_FEATURE, "F": vf.F_FEATURE},
            "build_commands": {"A": ["cargo"], "C": ["cargo"], "F": ["cargo"]},
            "adapter_sha256_before": self.arm_shas(),
            "adapter_sha256_after": self.arm_shas()})
        self.write("binaries.json", {
            "schema": SCHEMA,
            "adapters": {
                arm: {"path": adapters["F" if arm in ("G", "P") else arm],
                      "sha256": vf.sha256_file(
                          adapters["F" if arm in ("G", "P") else arm]),
                      "source_sha": {"A": vf.BASE_A, "C": vf.CAUSAL}.get(
                          arm, vf.F_DIAG),
                      "feature": None if arm == "A" else vf.F_FEATURE,
                      "mode": {"A": None, "C": "disabled", "G": "disabled",
                               "P": "enabled"}[arm]}
                for arm in vf.ARMS},
            "score_probes": {arm: {"path": probes[arm],
                                   "sha256": vf.sha256_file(probes[arm])}
                             for arm in vf.ARMS}})
        layout = {"stored_version": 2, "codec_id": 1,
                  "required_features": [[13, 1]],
                  "committed_index_bytes": vf.A_100K_TOTAL,
                  "stored_bytes": vf.A_100K_STORED}
        layouts = {key: {"10000": dict(layout, committed_index_bytes=1_500_000,
                                      stored_bytes=150_000),
                         "100000": dict(layout)} for key in ("A", "C", "F")}
        self.write("sizes.json", {
            "schema": SCHEMA,
            "builds": {key: {n: [{"attempt": attempt,
                                  "layout": layouts[key][n],
                                  "digest": f"digest-{n}"} for attempt in (1, 2, 3)]
                            for n in ("10000", "100000")}
                       for key in ("A", "C", "F")},
            "layouts": layouts,
            "segment_digests": {key: {"10000": "digest-10000",
                                      "100000": "digest-100000"}
                                for key in ("A", "C", "F")}})
        self.write("score-parity.json", {
            "schema": SCHEMA,
            "lanes": {lane: {"total_hits": 100, "hits": 100, "identical": True}
                      for lane in vf.LANE_IDS}})
        self.write("mode-proof.json", {
            "schema": SCHEMA, "binary_path": adapters["F"],
            "binary_sha256": vf.sha256_file(adapters["F"]),
            "probes": [{"label": label,
                        "environment_mode": mode,
                        "expected": "ok" if label in ("A", "C", "G", "P")
                        else "error",
                        "observed_status": "ok" if label in ("A", "C", "G", "P")
                        else "error"}
                       for label, mode in (("A", None), ("C", "disabled"),
                                           ("G", "disabled"), ("P", "enabled"),
                                           ("INVALID", "bogus"),
                                           ("MISSING", "absent"))]})
        self.write("codegen.json", {
            "schema": SCHEMA,
            **{key: {"symbols": {"execute_unified": {"instructions": 3993,
                                                     "drop_glue": False}}}
               for key in ("A", "C", "D", "E")}})
        self.write_slots()
        ratios = self.reference_ratios()
        self.write("measurements.json", {
            "schema": SCHEMA, "campaign": self.name, "regime": self.regime,
            "ratios": ratios,
            "counts": {"samples": vf.SLOTS * len(vf.LANE_IDS) * (
                vf.BATCHED if self.regime == "batched" else vf.UNBATCHED),
                "warmups": vf.SLOTS * len(vf.LANE_IDS) * vf.WARMUPS,
                "slots": vf.SLOTS,
                "lane_slot_records": vf.SLOTS * len(vf.LANE_IDS)},
            "codegen_checks": {"C_physical_present": True,
                               "D_physical_absent": True,
                               "A_generic_inlined": True,
                               "C_generic_inlined": True,
                               "E_generic_out_of_line": True,
                               "E_dispatch_probe": True},
            "diagnostic_only": True})
        self.write("manifest.json", self.manifest())
        self.seal()

    def arm_shas(self):
        return {"A": vf.sha256_file(self.binaries["A"]),
                "C": vf.sha256_file(self.binaries["C"]),
                "G": vf.sha256_file(self.binaries["F"]),
                "P": vf.sha256_file(self.binaries["F"])}

    def write_slots(self):
        expected = [(block, position, arm)
                    for block, order in enumerate(vf.SCHEDULE, start=1)
                    for position, arm in enumerate(order, start=1)]
        for index, (block, position, arm) in enumerate(expected, start=1):
            binary = self.binaries["F" if arm in ("G", "P") else arm]
            lanes = []
            for lane_id in vf.LANE_IDS:
                n = 10_000 if "/10000/" in lane_id else 100_000
                median = self.lane_median(lane_id, arm, block, position)
                samples = self.samples_for(median)
                self.samples[(index, lane_id)] = median
                repeat = (vf.REPEAT_SHORT if lane_id in (
                    vf.LOW_MATCH_10K + vf.LOW_MATCH_100K) else vf.REPEAT_OTHER)
                lanes.append({
                    "id": lane_id, "n": n, "class": lane_id.split("/")[2],
                    "field": "text", "term": "t", "k": int(lane_id.rsplit("k", 1)[1]),
                    "regime": "bm25", "arm": arm,
                    "mode": {"A": None, "C": "disabled", "G": "disabled",
                             "P": "enabled"}[arm],
                    "binary_path": binary,
                    "binary_sha256": vf.sha256_file(binary),
                    "sample_unit": "batch" if self.regime == "batched"
                    else "single_query",
                    "timing_field": "batch_ns" if self.regime == "batched"
                    else "engine_ns",
                    "repeat_count": repeat if self.regime == "batched" else 1,
                    "warmup_ids": [f"warm-{i}" for i in range(vf.WARMUPS)],
                    "samples_ns": samples,
                    "summary_ns": {"median": vf.nearest_rank_median(samples)},
                    "total_hits": 100, "doc_ids": ["d1"], "oracle_ok": True,
                    "analyzer": {"tokenizer": "unicode_word"},
                })
            probe = os.path.join(self.path, "setup", f"contention-{index}.json")
            os.makedirs(os.path.dirname(probe), exist_ok=True)
            with open(probe, "w", encoding="utf-8") as handle:
                json.dump({"clear": True}, handle)
            self.write(f"slots/slot-{index:02d}.json", {
                "slot_index": index, "block": block, "position": position,
                "arm": arm, "source_sha": {"A": vf.BASE_A, "C": vf.CAUSAL}.get(
                    arm, vf.F_DIAG),
                "binary_path": binary, "binary_sha256": vf.sha256_file(binary),
                "feature": None if arm == "A" else vf.F_FEATURE,
                "mode": {"A": None, "C": "disabled", "G": "disabled",
                         "P": "enabled"}[arm],
                "lanes": lanes,
                "contention_before": {"clear": True, "path": probe},
                "contention_after": {"clear": True, "path": probe}})

    def reference_ratios(self):
        times = self.samples
        ratios = {}
        for lane_id in vf.LANE_IDS:
            entry = {"C/A": [], "G/A": [], "P/A": [], "P/G": [], "A2/A1": []}
            for block in range(1, vf.BLOCKS + 1):
                indexes = [(block - 1) * vf.SLOTS_PER_BLOCK + offset
                           for offset in range(1, vf.SLOTS_PER_BLOCK + 1)]
                order = vf.SCHEDULE[block - 1]
                means = {}
                for arm in vf.ARMS:
                    slots = [indexes[position] for position, name in enumerate(order)
                             if name == arm]
                    means[arm] = sum(times[(index, lane_id)]
                                     for index in slots) / len(slots)
                a_slots = sorted(indexes[position]
                                 for position, name in enumerate(order) if name == "A")
                entry["A2/A1"].append(times[(a_slots[1], lane_id)]
                                      / times[(a_slots[0], lane_id)])
                for key, numerator, denominator in (
                        ("C/A", "C", "A"), ("G/A", "G", "A"),
                        ("P/A", "P", "A"), ("P/G", "P", "G")):
                    entry[key].append(means[numerator] / means[denominator])
            entry["medians"] = {key: vf.block_median_of_four(entry[key])
                                for key in ("C/A", "G/A", "P/A", "P/G")}
            entry["a_drift_median"] = vf.block_median_of_four(entry["A2/A1"])
            entry["a_drift_outliers"] = sum(
                1 for value in entry["A2/A1"]
                if value < vf.AA_BLOCK_MIN or value > vf.AA_BLOCK_MAX)
            ratios[lane_id] = entry
        return ratios

    def manifest(self):
        return {
            "schema": SCHEMA, "protocol_schema": vf.PROTOCOL_SCHEMA,
            "protocol_sha256": vf.PROTOCOL_SHA, "campaign": self.name,
            "regime": self.regime,
            "arm_sources": {"A": vf.BASE_A, "C": vf.CAUSAL, "F": vf.F_DIAG},
            "arm_features": {"A": None, "C": vf.F_FEATURE, "F": vf.F_FEATURE},
            "arm_modes": {"A": None, "C": "disabled", "G": "disabled",
                          "P": "enabled"},
            "adapter_sha256": self.arm_shas(),
            "adapter_path": {arm: self.binaries["F" if arm in ("G", "P")
                                              else arm] for arm in vf.ARMS},
            "lane_ids": list(vf.LANE_IDS),
            "arm_order_by_block": list(vf.SCHEDULE),
            "sample_unit": "batch" if self.regime == "batched" else "single_query",
            "environment_fingerprint": {"cpu": "test-cpu"},
            "filesystem": "ext4",
            "cpu_affinity": {"mode": "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1"},
            "counts": self.data["measurements.json"]["counts"],
            "codegen_checks": self.data["measurements.json"]["codegen_checks"],
            "generic_body_sha256":
                "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994",
            "slots_sha256": {
                f"slots/slot-{index:02d}.json": vf.sha256_file(
                    os.path.join(self.raw, "slots", f"slot-{index:02d}.json"))
                for index in range(1, vf.SLOTS + 1)},
        }

    def set_slot_median(self, index, lane_id, median):
        relative = f"slots/slot-{index:02d}.json"
        payload = self.data[relative]
        lane = next(lane for lane in payload["lanes"] if lane["id"] == lane_id)
        lane["samples_ns"] = self.samples_for(median)
        lane["summary_ns"] = {"median": median}
        self.samples[(index, lane_id)] = median

    def refresh_ratios(self):
        self.data["measurements.json"]["ratios"] = self.reference_ratios()
        self.write("measurements.json", self.data["measurements.json"])
        for index in range(1, vf.SLOTS + 1):
            relative = f"slots/slot-{index:02d}.json"
            self.write(relative, self.data[relative])
        self.data["manifest.json"] = self.manifest()
        self.write("manifest.json", self.data["manifest.json"])
        self.reseal()

    def reseal(self):
        files = {relative: vf.sha256_file(os.path.join(self.raw, relative))
                 for relative in vf.REQUIRED_RAW}
        with open(os.path.join(self.raw, "seal.json"), "w", encoding="utf-8") as handle:
            json.dump({"schema": vf.SEAL_SCHEMA, "files": files}, handle,
                      indent=2, sort_keys=True)
            handle.write("\n")

    def seal(self):
        self.reseal()


class VerifierTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ffinal-test-")
        self.root = os.path.realpath(self.tmp)
        self._original = vf.Campaign.check_source
        vf.Campaign.check_source = lambda campaign: {
            "generic_body_sha256":
                "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994",
            "physical_body_sha256": "522f6600f0efa24f",
            "changed_paths": ["crates/quervant-core/src/search/unified.rs"],
        }

    def tearDown(self):
        vf.Campaign.check_source = self._original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fixture(self, name="unbatched-01", lane_scale=None):
        return Fixture(self.root, name, lane_scale)

    def verify(self, fixture, write=False):
        return vf.verify_campaign(self.root, fixture.path, write_receipt=write)

    def assertRule(self, fixture, rule):
        with self.assertRaises(vf.VerifyError) as caught:
            self.verify(fixture)
        self.assertEqual(caught.exception.rule, rule, str(caught.exception))
        return caught.exception

    def rewrite(self, fixture, relative, mutate):
        payload = json.load(open(os.path.join(fixture.raw, relative),
                                 encoding="utf-8"))
        mutate(payload)
        with open(os.path.join(fixture.raw, relative), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        fixture.reseal()

    def mutate_slots(self, fixture, index, mutate):
        relative = f"slots/slot-{index:02d}.json"
        self.rewrite(fixture, relative, mutate)
        fixture.data["manifest.json"]["slots_sha256"][relative] = vf.sha256_file(
            os.path.join(fixture.raw, relative))
        with open(os.path.join(fixture.raw, "manifest.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(fixture.data["manifest.json"], handle, indent=2, sort_keys=True)
            handle.write("\n")
        fixture.reseal()


class ValidCampaignTests(VerifierTestCase):
    def test_valid_unbatched_campaign_passes(self):
        receipt = self.verify(self.fixture())
        self.assertEqual(receipt["status"], vf.STATUS_NEUTRAL)
        self.assertEqual(receipt["reasons"], [])

    def test_valid_batched_campaign_is_observation_only(self):
        receipt = self.verify(self.fixture("batched-01"))
        self.assertEqual(receipt["status"], "F_BATCHED_OBSERVATION_ONLY")

    def test_receipt_is_written_once(self):
        fixture = self.fixture()
        receipt = self.verify(fixture, write=True)
        path = os.path.join(self.root, vf.REVIEWS_ROOT,
                            "f-final-unbatched-01.json")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(json.load(open(path, encoding="utf-8"))["status"],
                         receipt["status"])
        with self.assertRaises(vf.VerifyError) as caught:
            self.verify(fixture, write=True)
        self.assertEqual(caught.exception.rule, "RECEIPT")


class InventoryTests(VerifierTestCase):
    def test_missing_manifest_is_rejected(self):
        fixture = self.fixture()
        os.remove(os.path.join(fixture.raw, "manifest.json"))
        self.assertRule(fixture, "INVENTORY")

    def test_unknown_raw_file_is_rejected(self):
        fixture = self.fixture()
        with open(os.path.join(fixture.raw, "extra.json"), "w", encoding="utf-8") as h:
            h.write("{}")
        self.assertRule(fixture, "INVENTORY")

    def test_symlinked_raw_file_is_rejected(self):
        fixture = self.fixture()
        target = os.path.join(self.root, "elsewhere.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("{}")
        os.remove(os.path.join(fixture.raw, "corpus.json"))
        os.symlink(target, os.path.join(fixture.raw, "corpus.json"))
        self.assertRule(fixture, "SYMLINK")

    def test_symlinked_campaign_directory_is_rejected(self):
        fixture = self.fixture()
        link = os.path.join(self.root, vf.ALLOWED, "link-01")
        os.symlink(fixture.path, link)
        with self.assertRaises(vf.VerifyError) as caught:
            vf.verify_campaign(self.root, link, write_receipt=False)
        self.assertIn(caught.exception.rule, {"PATH", "SCHEDULE"})

    def test_path_escape_is_rejected(self):
        fixture = self.fixture()
        with self.assertRaises(vf.VerifyError) as caught:
            vf.verify_campaign(self.root, os.path.join(self.root, "..", "else"),
                               write_receipt=False)
        self.assertEqual(caught.exception.rule, "PATH")


class SealTests(VerifierTestCase):
    def test_missing_seal_is_rejected(self):
        fixture = self.fixture()
        os.remove(os.path.join(fixture.raw, "seal.json"))
        self.assertRule(fixture, "SEAL")

    def test_malformed_seal_is_rejected(self):
        fixture = self.fixture()
        with open(os.path.join(fixture.raw, "seal.json"), "w", encoding="utf-8") as h:
            h.write("{not json")
        self.assertRule(fixture, "SEAL")

    def test_raw_change_without_reseal_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "corpus.json",
                     lambda payload: payload.update(manifest_sha256="0" * 64))
        with open(os.path.join(fixture.raw, "seal.json"), "w", encoding="utf-8") as h:
            h.write(json.dumps({"schema": vf.SEAL_SCHEMA, "files": {}}))
        self.assertRule(fixture, "SEAL")

    def test_forged_pass_with_regenerated_seal_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "corpus.json",
                     lambda payload: payload.update(manifest_sha256="0" * 64))
        self.assertRule(fixture, "CORPUS")


class ScheduleTests(VerifierTestCase):
    def test_missing_slot_is_rejected(self):
        fixture = self.fixture()
        os.remove(os.path.join(fixture.raw, "slots", "slot-07.json"))
        self.assertRule(fixture, "INVENTORY")

    def test_duplicate_slot_index_is_rejected(self):
        fixture = self.fixture()
        self.mutate_slots(fixture, 2, lambda payload: payload.update(slot_index=1))
        self.assertRule(fixture, "SCHEDULE")

    def test_balanced_but_changed_arm_order_is_rejected(self):
        fixture = self.fixture()

        def swap(payload):
            payload["arm"] = "C"

        self.mutate_slots(fixture, 1, swap)
        self.assertRule(fixture, "SCHEDULE")

    def test_imbalanced_block_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "protocol.json",
                     lambda payload: payload.update(
                         arm_order_by_block=["ACGPPGCA", "PGCAACGP",
                                             "GCPAPACG", "CPAGGACX"]))
        self.assertRule(fixture, "PROTOCOL")


class LaneTests(VerifierTestCase):
    def test_lane_order_change_is_rejected(self):
        fixture = self.fixture()
        self.mutate_slots(fixture, 3,
                          lambda payload: payload["lanes"].reverse())
        self.assertRule(fixture, "LANE")

    def test_lane_removal_is_rejected(self):
        fixture = self.fixture()
        self.mutate_slots(fixture, 4, lambda payload: payload["lanes"].pop())
        self.assertRule(fixture, "LANE")


class SampleTests(VerifierTestCase):
    def test_warmup_count_is_enforced(self):
        fixture = self.fixture()

        def shrink(payload):
            payload["lanes"][0]["warmup_ids"].pop()

        self.mutate_slots(fixture, 5, shrink)
        self.assertRule(fixture, "SAMPLE")

    def test_unbatched_count_is_enforced(self):
        fixture = self.fixture()

        def shrink(payload):
            payload["lanes"][0]["samples_ns"].pop()
            payload["lanes"][0]["summary_ns"]["median"] = vf.nearest_rank_median(
                payload["lanes"][0]["samples_ns"])

        self.mutate_slots(fixture, 6, shrink)
        self.assertRule(fixture, "SAMPLE")

    def test_batched_count_is_enforced(self):
        fixture = self.fixture("batched-01")

        def shrink(payload):
            payload["lanes"][0]["samples_ns"].pop()
            payload["lanes"][0]["summary_ns"]["median"] = vf.nearest_rank_median(
                payload["lanes"][0]["samples_ns"])

        self.mutate_slots(fixture, 2, shrink)
        self.assertRule(fixture, "SAMPLE")

    def test_batch_repeat_is_enforced(self):
        fixture = self.fixture("batched-01")
        self.mutate_slots(fixture, 2,
                          lambda payload: payload["lanes"][0].update(repeat_count=99))
        self.assertRule(fixture, "UNITS")

    def test_batched_unit_drift_is_rejected(self):
        fixture = self.fixture("batched-01")
        self.mutate_slots(fixture, 2, lambda payload: payload["lanes"][0].update(
            timing_field="engine_ns"))
        self.assertRule(fixture, "SAMPLE")

    def test_unbatched_unit_drift_is_rejected(self):
        fixture = self.fixture()
        self.mutate_slots(fixture, 2, lambda payload: payload["lanes"][0].update(
            timing_field="batch_ns", sample_unit="batch"))
        self.assertRule(fixture, "SAMPLE")

    def test_zero_sample_is_rejected(self):
        fixture = self.fixture()

        def zero(payload):
            payload["lanes"][0]["samples_ns"][0] = 0
            payload["lanes"][0]["summary_ns"]["median"] = 1

        self.mutate_slots(fixture, 7, zero)
        self.assertRule(fixture, "SAMPLE")

    def test_float_sample_is_rejected(self):
        fixture = self.fixture()

        def floaty(payload):
            payload["lanes"][0]["samples_ns"][0] = 1.5
            payload["lanes"][0]["summary_ns"]["median"] = 1

        self.mutate_slots(fixture, 8, floaty)
        self.assertRule(fixture, "SAMPLE")


class RatioTests(VerifierTestCase):
    def test_wrong_recorded_median_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "measurements.json",
                     lambda payload: payload["ratios"][vf.LANE_IDS[0]][
                         "medians"].update({"G/A": 0.99}))
        self.assertRule(fixture, "RATIO")

    def test_wrong_per_block_ratio_is_rejected(self):
        fixture = self.fixture()

        def tamper(payload):
            payload["ratios"][vf.LANE_IDS[0]]["G/A"][0] *= 1.01

        self.rewrite(fixture, "measurements.json", tamper)
        self.assertRule(fixture, "RATIO")

    def test_wrong_slot_median_is_rejected(self):
        fixture = self.fixture()

        def tamper(payload):
            payload["lanes"][0]["summary_ns"]["median"] += 1

        self.mutate_slots(fixture, 9, tamper)
        self.assertRule(fixture, "RATIO")

    def test_zero_denominator_is_rejected(self):
        with self.assertRaises(vf.VerifyError) as caught:
            vf.nearest_rank_median([])
        self.assertEqual(caught.exception.rule, "RATIO")

    def test_non_finite_ratio_is_rejected(self):
        with self.assertRaises(vf.VerifyError) as caught:
            vf.require_ratio(float("nan"), "x")
        self.assertEqual(caught.exception.rule, "RATIO")
        with self.assertRaises(vf.VerifyError):
            vf.require_ratio(True, "x")


class SourceTests(VerifierTestCase):
    def setUp(self):
        super().setUp()
        vf.Campaign.check_source = self._original
        self.saved = {name: getattr(proof_module, name) for name in
                      ("is_commit", "is_ancestor", "verify_f_diag")}
        proof_module.is_commit = lambda root, revision: True
        proof_module.is_ancestor = lambda root, a, b: True

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(proof_module, name, value)
        super().tearDown()

    def patch_source(self, error_rule):
        def boom(root, f_diag=None):
            raise proof_module.FSourceError(error_rule, "synthetic")

        proof_module.verify_f_diag = boom

    def test_missing_source_commit_is_rejected(self):
        fixture = self.fixture()
        self.patch_source("FS_SOURCE")
        self.assertRule(fixture, "SOURCE")

    def test_extra_code_edit_is_rejected(self):
        fixture = self.fixture()
        self.patch_source("FS_DIFF")
        self.assertRule(fixture, "SOURCE")

    def test_body_drift_is_rejected(self):
        fixture = self.fixture()
        self.patch_source("FS_BODY")
        self.assertRule(fixture, "BODY")

    def test_physical_body_drift_is_rejected(self):
        fixture = self.fixture()
        self.patch_source("FS_PHYSICAL")
        self.assertRule(fixture, "BODY")

    def test_duplicate_attribute_is_rejected(self):
        fixture = self.fixture()
        self.patch_source("FS_ATTRIBUTE")
        self.assertRule(fixture, "SOURCE")

    def test_release_gate_leak_is_rejected(self):
        fixture = self.fixture()
        self.patch_source("FS_RELEASE")
        self.assertRule(fixture, "RELEASE")

    def test_recorded_body_hash_mismatch_is_rejected(self):
        fixture = self.fixture()
        proof_module.verify_f_diag = lambda root, f_diag=None: {
            "generic_body_sha256": "1" * 64,
            "physical_body_sha256": "522f6600f0efa24f",
            "changed_paths": ["crates/quervant-core/src/search/unified.rs"]}
        self.assertRule(fixture, "BODY")


class BinaryTests(VerifierTestCase):
    def test_distinct_gp_paths_are_rejected(self):
        fixture = self.fixture()
        copy = os.path.join(self.root, "bin", "adapter-F-copy")
        shutil.copyfile(fixture.binaries["F"], copy)
        self.rewrite(fixture, "binaries.json", lambda payload: payload[
            "adapters"]["P"].update(path=copy))
        self.assertRule(fixture, "BINARY")

    def test_gp_sha_mismatch_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "binaries.json", lambda payload: payload[
            "adapters"]["P"].update(sha256="0" * 64))
        self.assertRule(fixture, "BINARY")

    def test_binary_change_after_slot_is_rejected(self):
        fixture = self.fixture()
        with open(fixture.binaries["A"], "ab") as handle:
            handle.write(b"tamper")
        self.assertRule(fixture, "BINARY")

    def test_toolchain_drift_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "toolchain.json", lambda payload: payload.update(
            arm_features={"A": "extra", "C": vf.F_FEATURE, "F": vf.F_FEATURE}))
        self.assertRule(fixture, "TOOLCHAIN")


class CorpusFormatTests(VerifierTestCase):
    def test_corpus_digest_is_enforced(self):
        fixture = self.fixture()
        self.rewrite(fixture, "corpus.json",
                     lambda payload: payload.update(manifest_sha256="0" * 64))
        self.assertRule(fixture, "CORPUS")

    def test_layout_drift_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "sizes.json", lambda payload: payload[
            "layouts"]["C"]["100000"].update(codec_id=2))
        self.assertRule(fixture, "FORMAT")

    def test_sentinel_drift_is_rejected(self):
        fixture = self.fixture()
        def mutate(payload):
            for key in ("A", "C", "F"):
                payload["layouts"][key]["100000"]["committed_index_bytes"] = (
                    vf.A_100K_TOTAL + 1)
                for record in payload["builds"][key]["100000"]:
                    record["layout"]["committed_index_bytes"] = vf.A_100K_TOTAL + 1

        self.rewrite(fixture, "sizes.json", mutate)
        self.assertRule(fixture, "SENTINEL")

    def test_codec_feature_pair_is_enforced(self):
        fixture = self.fixture()
        self.rewrite(fixture, "sizes.json",
                     lambda payload: payload["layouts"]["A"]["10000"].update(
                         required_features=[]))
        self.assertRule(fixture, "FORMAT")


class OracleScoreTests(VerifierTestCase):
    def test_forged_hit_count_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "score-parity.json", lambda payload: payload[
            "lanes"][vf.LANE_IDS[0]].update(total_hits=99))
        self.assertRule(fixture, "SCORE")

    def test_score_bit_divergence_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "score-parity.json", lambda payload: payload[
            "lanes"][vf.LANE_IDS[1]].update(identical=False))
        self.assertRule(fixture, "SCORE")


class ModeTests(VerifierTestCase):
    def test_missing_mode_probe_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "mode-proof.json", lambda payload: payload[
            "probes"].pop())
        self.assertRule(fixture, "MODE")

    def test_generic_arm_with_physical_mode_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "mode-proof.json", lambda payload: next(
            probe for probe in payload["probes"] if probe["label"] == "G"
        ).update(environment_mode="enabled"))
        self.assertRule(fixture, "MODE")

    def test_slot_mode_drift_is_rejected(self):
        fixture = self.fixture()
        self.mutate_slots(fixture, 3, lambda payload: payload.update(mode=None))
        self.assertRule(fixture, "LANE")


class ContentionTests(VerifierTestCase):
    def test_missing_probe_is_rejected(self):
        fixture = self.fixture()
        self.mutate_slots(fixture, 10,
                          lambda payload: payload.pop("contention_after"))
        self.assertRule(fixture, "CONTENTION")

    def test_non_clear_probe_is_rejected(self):
        fixture = self.fixture()
        self.mutate_slots(fixture, 10, lambda payload: payload[
            "contention_before"].update(clear=False))
        self.assertRule(fixture, "CONTENTION")


class CodegenTests(VerifierTestCase):
    def test_empty_symbol_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "codegen.json", lambda payload: payload[
            "A"]["symbols"]["execute_unified"].update(instructions=0))
        self.assertRule(fixture, "CODEGEN")

    def test_drop_glue_symbol_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "codegen.json", lambda payload: payload[
            "C"]["symbols"]["execute_unified"].update(drop_glue=True))
        self.assertRule(fixture, "CODEGEN")

    def test_structural_check_failure_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "measurements.json", lambda payload: payload[
            "codegen_checks"].update(D_physical_absent=False))
        self.assertRule(fixture, "CODEGEN")


class DecisionTests(VerifierTestCase):
    def test_unstable_aa_is_diagnostic_unstable(self):
        fixture = self.fixture()
        for block in (1, 2):
            order = vf.SCHEDULE[block - 1]
            a_indexes = [(block - 1) * vf.SLOTS_PER_BLOCK + position + 1
                         for position, arm in enumerate(order) if arm == "A"]
            median = fixture.samples[(a_indexes[1], vf.LANE_IDS[0])]
            fixture.set_slot_median(a_indexes[1], vf.LANE_IDS[0],
                                    int(median * 1.4))
        fixture.refresh_ratios()
        receipt = self.verify(fixture)
        self.assertEqual(receipt["status"], vf.STATUS_UNSTABLE)

    def test_c_reproduction_missing_is_reported(self):
        fixture = self.fixture(lane_scale={vf.LOW_MATCH_10K[0]: {"C": 1.0}})
        receipt = self.verify(fixture)
        self.assertEqual(receipt["status"], vf.STATUS_NO_REPRO)

    def test_generic_campaign_regression_is_rejected(self):
        fixture = self.fixture(lane_scale={vf.LANE_IDS[3]: {"G": 1.11}})
        receipt = self.verify(fixture)
        self.assertEqual(receipt["status"], vf.STATUS_REJECTED)

    def test_block_observation_does_not_fail_diagnostic(self):
        fixture = self.fixture(lane_scale={vf.LANE_IDS[3]: {"G": 1.001}})
        receipt = self.verify(fixture)
        self.assertEqual(receipt["status"], vf.STATUS_NEUTRAL)
        self.assertIsInstance(receipt["observations"], list)

    def test_batched_observation_ignores_generic_regression(self):
        fixture = self.fixture("batched-01",
                               lane_scale={vf.LANE_IDS[3]: {"G": 2.0}})
        receipt = self.verify(fixture)
        self.assertEqual(receipt["status"], "F_BATCHED_OBSERVATION_ONLY")


class AggregateTests(VerifierTestCase):
    def series(self):
        series = os.path.join(self.root, vf.ALLOWED)
        for name in vf.CAMPAIGNS:
            Fixture(self.root, name).seal()
        return series

    def test_complete_series_passes(self):
        series = self.series()
        summary = vf.aggregate(self.root, series, verify_only=True)
        self.assertEqual(summary["status"], vf.STATUS_NEUTRAL)
        self.assertEqual(set(summary["campaigns"]), set(vf.CAMPAIGNS))

    def test_missing_campaign_is_rejected(self):
        series = self.series()
        shutil.rmtree(os.path.join(series, "batched-02"))
        with self.assertRaises(vf.VerifyError) as caught:
            vf.aggregate(self.root, series, verify_only=True)
        self.assertEqual(caught.exception.rule, "SERIES")

    def test_extra_directory_is_rejected(self):
        series = self.series()
        os.makedirs(os.path.join(series, "unbatched-01-copy"))
        with self.assertRaises(vf.VerifyError) as caught:
            vf.aggregate(self.root, series, verify_only=True)
        self.assertEqual(caught.exception.rule, "SERIES")

    def test_cross_campaign_host_mismatch_is_rejected(self):
        series = self.series()
        path = os.path.join(series, "batched-02", "raw", "environment.json")
        payload = json.load(open(path, encoding="utf-8"))
        payload["host_fingerprint"] = {"cpu": "other"}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        with self.assertRaises(vf.VerifyError) as caught:
            vf.aggregate(self.root, series, verify_only=True)
        self.assertEqual(caught.exception.rule, "SEAL")

    def test_aggregate_generic_regression_is_rejected(self):
        series = self.series()
        for name in ("unbatched-01", "unbatched-02"):
            shutil.rmtree(os.path.join(series, name))
            Fixture(self.root, name,
                    lane_scale={vf.LANE_IDS[5]: {"G": 1.10}}).seal()
        summary = vf.aggregate(self.root, series, verify_only=True)
        self.assertEqual(summary["status"], vf.STATUS_REJECTED)


class ProtocolTests(VerifierTestCase):
    def test_threshold_change_is_rejected(self):
        fixture = self.fixture()
        self.rewrite(fixture, "protocol.json",
                     lambda payload: payload.update(F_generic_aggregate_max=1.2))
        self.assertRule(fixture, "PROTOCOL")

    def test_protocol_copy_must_match_frozen_file(self):
        fixture = self.fixture()
        path = os.path.join(self.root, vf.PROTOCOL_REL)
        payload = json.load(open(path, encoding="utf-8"))
        payload["diagnostic_only"] = True
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        self.assertRule(fixture, "PROTOCOL")


if __name__ == "__main__":
    unittest.main()

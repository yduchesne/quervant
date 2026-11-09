#!/usr/bin/env python3
"""PR 15I-C-F — independent verifier for the four-arm diagnostic campaign.

Recomputes every statistic from sealed raw data with its own nearest-rank
median, ratio and classifier implementations. Never imports the controller's
derivation, never mutates raw evidence, and writes only receipts under
`target/pr15i-c/reviews/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "f_final_protocol_v1.json")
PROTOCOL_SHA = "5ca968c2e8f6cbfbca88357651d66a1cacace3b45def3ad25fefc1d0228a7dba"
PROTOCOL_SCHEMA = "pr15i-c-f-final-diag-v1"
SCHEMA = "pr15i-c-f-final-campaign-v1"
SEAL_SCHEMA = "pr15i-c-f-final-seal-v1"
BASE_A = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
CAUSAL = "658a2dde0e15c17e2b0c92278b5c922f5260fe60"
F_DIAG = "5f74bb691420673bde1181603d0a19a8a4114ec8"
DEFAULT_F_DIAG = F_DIAG
MODE_VARIABLE = "QUERVANT_PR15IC_CAUSAL_MODE"
F_FEATURE = "pr15ic-causal"
ARMS = ("A", "C", "G", "P")
SCHEDULE = ("ACGPPGCA", "PGCAACGP", "GCPAPACG", "CPAGGACP")
BLOCKS = 4
SLOTS_PER_BLOCK = 8
SLOTS = 32
WARMUPS = 5
UNBATCHED = 20
BATCHED = 10
REPEAT_SHORT = 100
REPEAT_OTHER = 1
LANE_IDS = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/medium/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
)
LOW_MATCH_10K = ("pr15d_v1/10000/absent/k100", "pr15d_v1/10000/rare/k100")
LOW_MATCH_100K = ("pr15d_v1/100000/absent/k100", "pr15d_v1/100000/rare/k100")
PRIMARY = (
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
)
CAMPAIGNS = ("unbatched-01", "batched-01", "unbatched-02", "batched-02")
REGIME = {"unbatched-01": "unbatched", "batched-01": "batched",
          "unbatched-02": "unbatched", "batched-02": "batched"}
CORPUS_SHA = "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151"
A_100K_TOTAL = 15_747_551
A_100K_STORED = 1_661_455
SENTINEL_N = 100_000
RAW_METADATA = (
    "authorization.json", "protocol.json", "source-proof.json", "corpus.json",
    "environment.json", "toolchain.json", "binaries.json", "sizes.json",
    "score-parity.json", "mode-proof.json", "codegen.json", "measurements.json",
    "manifest.json",
)
SLOT_FILES = tuple(f"slots/slot-{index:02d}.json" for index in range(1, SLOTS + 1))
REQUIRED_RAW = (*RAW_METADATA, *SLOT_FILES)
REVIEWS_ROOT = os.path.join("target", "pr15i-c", "reviews")
ALLOWED = os.path.join("target", "pr15i-c", "f-final-diagnostic-v1")

AA_MIN, AA_MAX = 0.85, 1.15
AA_BLOCK_MIN, AA_BLOCK_MAX = 0.80, 1.25
AA_BLOCK_OUTLIERS = 1
C_MIN_10K, C_MIN_100K = 1.15, 1.40
G_CAMPAIGN_MAX, G_AGGREGATE_MAX = 1.10, 1.05
G_BLOCK_OBSERVE = 1.15

STATUS_NEUTRAL = "F_GENERIC_NEUTRAL_DIAGNOSTIC"
STATUS_UNSTABLE = "F_DIAGNOSTIC_UNSTABLE"
STATUS_NO_REPRO = "F_C_REPRODUCTION_MISSING"
STATUS_REJECTED = "F_GENERIC_BOUNDARY_REJECTED"


class VerifyError(Exception):
    def __init__(self, rule, detail):
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


def fail(rule, detail):
    raise VerifyError(rule, detail)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def nearest_rank_median(values):
    """Nearest-rank median (ceil(p*n) order statistic), p = 0.5."""
    if not values:
        fail("RATIO", "empty sample set")
    ordered = sorted(values)
    for value in ordered:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            fail("SAMPLE", "timed sample is not a positive integer")
    return ordered[(len(ordered) - 1) // 2]


def block_median_of_four(values):
    """Median of the four per-block ratios (mean of the two middle values)."""
    ordered = sorted(values)
    return (ordered[1] + ordered[2]) / 2


def require_ratio(value, label):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        fail("RATIO", f"{label} is not numeric")
    if not math.isfinite(value):
        fail("RATIO", f"{label} is not finite")
    return float(value)


def is_within(path, root):
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(root)
    return os.path.commonpath([real_path, real_root]) == real_root


class Campaign:
    def __init__(self, root, path):
        self.root = os.path.realpath(root)
        if not is_within(path, self.root):
            fail("PATH", "campaign path escapes the checkout root")
        self.path = os.path.realpath(path)
        if os.path.islink(path):
            fail("PATH", "campaign directory is a symlink")
        if not is_within(self.path, os.path.join(self.root, ALLOWED)):
            fail("PATH", "campaign must live under target/pr15i-c/f-final-diagnostic-v1")
        if not os.path.isdir(self.path):
            fail("PATH", "campaign directory does not exist")
        self.name = os.path.basename(self.path)
        if self.name not in CAMPAIGNS:
            fail("SCHEDULE", f"unknown campaign {self.name!r}")
        self.raw = os.path.join(self.path, "raw")
        self.regime = REGIME[self.name]
        self.data = {}

    # ---- inventory / seal -------------------------------------------------
    def load(self):
        if os.path.islink(self.raw):
            fail("SYMLINK", "raw/ is a symlink")
        if not os.path.isdir(self.raw):
            fail("INVENTORY", "raw/ is missing")
        present = set()
        for entry in os.listdir(self.raw):
            full = os.path.join(self.raw, entry)
            if os.path.islink(full):
                fail("SYMLINK", f"raw/{entry} is a symlink")
            if entry == "seal.json":
                present.add(entry)
                continue
            if os.path.isdir(full):
                if entry != "slots":
                    fail("INVENTORY", f"unexpected raw directory {entry!r}")
                for nested in os.listdir(full):
                    nested_path = os.path.join(full, nested)
                    if os.path.islink(nested_path):
                        fail("SYMLINK", f"raw/slots/{nested} is a symlink")
                    if not os.path.isfile(nested_path):
                        fail("INVENTORY", f"unexpected entry raw/slots/{nested!r}")
                    present.add(f"slots/{nested}")
                continue
            if not os.path.isfile(full):
                fail("INVENTORY", f"unexpected entry {entry!r}")
            present.add(entry)
        missing = sorted(set(REQUIRED_RAW) - present)
        if missing:
            fail("INVENTORY", f"missing raw files: {missing}")
        unknown = sorted(present - set(REQUIRED_RAW) - {"seal.json"})
        if unknown:
            fail("INVENTORY", f"unknown raw files: {unknown}")
        seal_path = os.path.join(self.raw, "seal.json")
        try:
            seal = load_json(seal_path)
        except (OSError, json.JSONDecodeError) as error:
            fail("SEAL", f"unreadable seal: {error}")
        if seal.get("schema") != SEAL_SCHEMA:
            fail("SEAL", "seal schema mismatch")
        files = seal.get("files")
        if not isinstance(files, dict) or set(files) != set(REQUIRED_RAW):
            fail("SEAL", "seal file inventory drifted")
        for relative in REQUIRED_RAW:
            digest = sha256_file(os.path.join(self.raw, relative))
            if files[relative] != digest:
                fail("SEAL", f"{relative} does not match its sealed digest")
        self.seal = seal
        for relative in REQUIRED_RAW:
            try:
                self.data[relative] = load_json(os.path.join(self.raw, relative))
            except json.JSONDecodeError as error:
                fail("INVENTORY", f"{relative} is not valid JSON: {error}")

    # ---- protocol ---------------------------------------------------------
    def check_protocol(self):
        protocol = self.data["protocol.json"]
        if sha256_file(os.path.join(self.root, PROTOCOL_REL)) != PROTOCOL_SHA:
            fail("PROTOCOL", "frozen protocol file digest drifted")
        if sha256_file(os.path.join(self.raw, "protocol.json")) != PROTOCOL_SHA:
            fail("PROTOCOL", "campaign protocol copy is not the frozen protocol")
        if protocol.get("schema") != PROTOCOL_SCHEMA:
            fail("PROTOCOL", "protocol schema mismatch")
        expected = {
            "diagnostic_only": True,
            "baseline_source": BASE_A,
            "historical_c_source": CAUSAL,
            "f_diagnostic_source": DEFAULT_F_DIAG,
            "blocks_per_campaign": BLOCKS,
            "slots_per_block": SLOTS_PER_BLOCK,
            "slots_per_campaign": SLOTS,
            "warmups_per_lane_slot": WARMUPS,
            "unbatched_samples_per_lane_slot": UNBATCHED,
            "batched_samples_per_lane_slot": BATCHED,
            "batch_repeats_absent_rare": REPEAT_SHORT,
            "batch_repeats_other": REPEAT_OTHER,
            "fresh_builds_per_binary_per_n": 3,
            "required_filesystem": "ext4",
            "required_affinity": "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1",
            "AA_control_min": AA_MIN,
            "AA_control_max": AA_MAX,
            "AA_max_blocks_outside_0_80_1_25_per_lane": AA_BLOCK_OUTLIERS,
            "C_repro_min_10k": C_MIN_10K,
            "C_repro_min_100k": C_MIN_100K,
            "F_generic_aggregate_max": G_AGGREGATE_MAX,
            "F_generic_each_campaign_max": G_CAMPAIGN_MAX,
            "F_generic_each_block_1_15_observation_only": True,
            "two_unbatched_campaigns_required": True,
            "batched_classification_allowed": False,
            "frozen_feature_acceptance_unchanged": True,
            "campaigns": list(CAMPAIGNS),
            "arm_order_by_block": list(SCHEDULE),
            "batch_rejects_absent_rare": REPEAT_SHORT,
        }
        for key, value in expected.items():
            if key not in protocol:
                continue
            if protocol[key] != value:
                fail("PROTOCOL", f"protocol field {key} drifted")
        for key in ("diagnostic_only", "frozen_feature_acceptance_unchanged"):
            if protocol.get(key) is not True:
                fail("PROTOCOL", f"{key} must be true")

    # ---- source -----------------------------------------------------------
    def check_source(self):
        sys.path.insert(0, HERE)
        import f_final_source_proof as proof
        f_source = self.data["authorization.json"]["arm_sources"]["F"]
        if not proof.is_commit(self.root, f_source):
            fail("SOURCE", "F source commit is missing")
        if f_source != DEFAULT_F_DIAG:
            fail("SOURCE", "F source is not the frozen diagnostic commit")
        if not proof.is_commit(self.root, CAUSAL):
            fail("SOURCE", "historical C source commit is missing")
        if not proof.is_commit(self.root, BASE_A):
            fail("SOURCE", "baseline commit is missing")
        if not proof.is_ancestor(self.root, CAUSAL, f_source):
            fail("SOURCE", "C is not an ancestor of F")
        if not proof.is_ancestor(self.root, BASE_A, f_source):
            fail("SOURCE", "BASE_A is not an ancestor of F")
        try:
            report = proof.verify_f_diag(self.root, f_source)
        except proof.FSourceError as error:
            rule = {"FS_SCOPE": "SOURCE", "FS_DIFF": "SOURCE",
                    "FS_BODY": "BODY", "FS_BOUNDARY": "BOUNDARY",
                    "FS_PHYSICAL": "BODY", "FS_RELEASE": "RELEASE",
                    "FS_FEATURE": "SOURCE"}.get(error.rule, "SOURCE")
            fail(rule, error.detail)
        if report["generic_body_sha256"] != "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994":
            fail("BODY", "generic collector body hash drifted")
        if report["changed_paths"] != [
                "crates/quervant-core/src/search/unified.rs"]:
            fail("SOURCE", f"F changes production paths: {report['changed_paths']}")
        recorded = self.data["source-proof.json"]
        if recorded.get("generic_body_sha256") != report["generic_body_sha256"]:
            fail("BODY", "recorded generic body hash disagrees with source")
        if recorded.get("physical_body_sha256") != report["physical_body_sha256"]:
            fail("BODY", "recorded physical body hash disagrees with source")
        if recorded.get("candidate_sha") != f_source:
            fail("SOURCE", "recorded F SHA disagrees with authorization")
        return report

    # ---- schedule / lanes ------------------------------------------------
    def check_schedule(self):
        authorization = self.data["authorization.json"]
        if authorization.get("schema") != SCHEMA:
            fail("PROTOCOL", "authorization schema mismatch")
        if authorization.get("campaign") != self.name:
            fail("PROTOCOL", "authorization campaign mismatch")
        if authorization.get("regime") != self.regime:
            fail("SCHEDULE", "authorization regime mismatch")
        if authorization.get("diagnostic_only") is not True:
            fail("PROTOCOL", "authorization is not diagnostic-only")
        if authorization.get("idle_authorized_by_user") is not True:
            fail("AUTHORIZATION", "idle authorization missing")
        if authorization.get("native_filesystem") != "ext4":
            fail("FILESYSTEM", "campaign did not run on ext4")
        affinity = authorization.get("cpu_affinity") or {}
        if affinity.get("mode") != "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1":
            fail("AFFINITY", "affinity mode drifted")
        if (affinity.get("adapter_cpu"), affinity.get("controller_cpu")) != (0, 1):
            fail("AFFINITY", "affinity CPUs drifted")
        if authorization.get("arm_sources") != {"A": BASE_A, "C": CAUSAL,
                                                "F": DEFAULT_F_DIAG}:
            fail("SOURCE", "authorization arm sources drifted")
        if authorization.get("arm_features") != {"A": None, "C": F_FEATURE,
                                                 "F": F_FEATURE}:
            fail("SOURCE", "authorization arm features drifted")
        if authorization.get("arm_modes") != {"A": None, "C": "disabled",
                                              "G": "disabled", "P": "enabled"}:
            fail("MODE", "authorization arm modes drifted")

        expected = [(block, position, arm)
                    for block, order in enumerate(SCHEDULE, start=1)
                    for position, arm in enumerate(order, start=1)]
        self.slots = {}
        for index in range(1, SLOTS + 1):
            record = self.data[f"slots/slot-{index:02d}.json"]
            if record.get("slot_index") != index:
                fail("SCHEDULE", f"slot file {index} carries index "
                                 f"{record.get('slot_index')!r}")
            if self.data["manifest.json"]["slots_sha256"].get(
                    f"slots/slot-{index:02d}.json") != sha256_file(
                        os.path.join(self.raw, "slots", f"slot-{index:02d}.json")):
                fail("SCHEDULE", f"slot {index} digest disagrees with manifest")
            self.slots[index] = record
        for index, (block, position, arm) in enumerate(expected, start=1):
            record = self.slots[index]
            if (record.get("block"), record.get("position"), record.get("arm")) != (
                    block, position, arm):
                fail("SCHEDULE", f"slot {index} does not match the frozen schedule")
        for block, order in enumerate(SCHEDULE, start=1):
            arms = [self.slots[index]["arm"] for index in range(
                (block - 1) * SLOTS_PER_BLOCK + 1, block * SLOTS_PER_BLOCK + 1)]
            if arms != list(order):
                fail("SCHEDULE", f"block {block} arm order drifted")
        for arm in ARMS:
            count = sum(1 for record in self.slots.values() if record["arm"] == arm)
            if count != SLOTS // len(ARMS):
                fail("SCHEDULE", f"arm {arm} appears {count} times")

    def check_lanes(self):
        for index, record in self.slots.items():
            lanes = record.get("lanes")
            if not isinstance(lanes, list):
                fail("LANE", f"slot {index} has no lane list")
            if [lane.get("id") for lane in lanes] != list(LANE_IDS):
                fail("LANE", f"slot {index} lane order/identity drifted")
            for lane in lanes:
                if lane.get("arm") != record["arm"]:
                    fail("LANE", f"slot {index} lane arm mismatch")
                if lane.get("mode") != record["mode"]:
                    fail("LANE", f"slot {index} lane mode mismatch")
                if lane.get("binary_path") != record["binary_path"]:
                    fail("BINARY", f"slot {index} lane binary path mismatch")
                if lane.get("binary_sha256") != record["binary_sha256"]:
                    fail("BINARY", f"slot {index} lane binary digest mismatch")
                if lane.get("analyzer") is None:
                    fail("LANE", f"slot {index} lane analyzer metadata missing")

    # ---- samples ---------------------------------------------------------
    def check_samples(self):
        expected_samples = BATCHED if self.regime == "batched" else UNBATCHED
        unit = "batch" if self.regime == "batched" else "single_query"
        field = "batch_ns" if self.regime == "batched" else "engine_ns"
        for index, record in self.slots.items():
            for lane in record["lanes"]:
                if len(lane.get("warmup_ids", ())) != WARMUPS:
                    fail("SAMPLE", f"slot {index} {lane['id']} warmup count")
                samples = lane.get("samples_ns")
                if not isinstance(samples, list) or len(samples) != expected_samples:
                    fail("SAMPLE", f"slot {index} {lane['id']} timed count")
                if lane.get("sample_unit") != unit or lane.get("timing_field") != field:
                    fail("SAMPLE", f"slot {index} {lane['id']} unit drifted")
                for value in samples:
                    if isinstance(value, bool) or not isinstance(value, int):
                        fail("SAMPLE", f"slot {index} {lane['id']} non-integer sample")
                    if value <= 0:
                        fail("SAMPLE", f"slot {index} {lane['id']} non-positive sample")
                repeat = lane.get("repeat_count")
                expected_repeat = (REPEAT_SHORT if lane["id"].startswith(
                    ("pr15d_v1/10000/absent", "pr15d_v1/10000/rare",
                     "pr15d_v1/100000/absent", "pr15d_v1/100000/rare"))
                    else REPEAT_OTHER) if self.regime == "batched" else 1
                if repeat != expected_repeat:
                    fail("UNITS", f"slot {index} {lane['id']} repeat_count {repeat}")
                summary = lane.get("summary_ns") or {}
                if summary.get("median") != nearest_rank_median(samples):
                    fail("RATIO", f"slot {index} {lane['id']} median disagrees")
                if lane.get("oracle_ok") is not True:
                    fail("ORACLE", f"slot {index} {lane['id']} oracle not confirmed")
                if not lane.get("total_hits"):
                    fail("ORACLE", f"slot {index} {lane['id']} hit count missing")

    # ---- contention / binaries -------------------------------------------
    def check_contention(self):
        for index, record in self.slots.items():
            for key in ("contention_before", "contention_after"):
                probe = record.get(key)
                if not isinstance(probe, dict):
                    fail("CONTENTION", f"slot {index} missing {key}")
                if probe.get("clear") is not True:
                    fail("CONTENTION", f"slot {index} {key} is not clear")
                if probe.get("path") and not os.path.isfile(probe["path"]):
                    fail("CONTENTION", f"slot {index} {key} probe file missing")

    def check_binaries(self):
        binaries = self.data["binaries.json"]
        adapters = binaries.get("adapters")
        if not isinstance(adapters, dict) or set(adapters) != set(ARMS):
            fail("BINARY", "adapter inventory drifted")
        shas = {}
        for arm in ARMS:
            record = adapters[arm]
            path = record.get("path")
            if not path or not os.path.isfile(path):
                fail("BINARY", f"arm {arm} adapter is missing")
            digest = sha256_file(path)
            if digest != record.get("sha256"):
                fail("BINARY", f"arm {arm} binary changed after the campaign")
            shas[arm] = digest
            expected = {"A": (BASE_A, None, None),
                        "C": (CAUSAL, F_FEATURE, "disabled"),
                        "G": (DEFAULT_F_DIAG, F_FEATURE, "disabled"),
                        "P": (DEFAULT_F_DIAG, F_FEATURE, "enabled")}[arm]
            if (record.get("source_sha"), record.get("feature"),
                    record.get("mode")) != expected:
                fail("SOURCE", f"arm {arm} provenance drifted")
            if arm in ("G", "P") and record["path"] != adapters["G"]["path"]:
                fail("BINARY", "G and P must share one binary path")
        if shas["G"] != shas["P"]:
            fail("BINARY", "G and P binaries differ")
        if len({shas["A"], shas["C"], shas["G"]}) != 3:
            fail("BINARY", "A, C and F binaries are not distinct")
        for index, record in self.slots.items():
            if record["binary_sha256"] != shas[record["arm"]]:
                fail("BINARY", f"slot {index} used a different binary")
            if record["binary_path"] != adapters[record["arm"]]["path"]:
                fail("BINARY", f"slot {index} binary path drifted")
            if record["source_sha"] != adapters[record["arm"]]["source_sha"]:
                fail("SOURCE", f"slot {index} source drifted")
        before = self.data["toolchain.json"].get("adapter_sha256_before")
        after = self.data["toolchain.json"].get("adapter_sha256_after")
        if before != after:
            fail("BINARY", "an adapter changed during the campaign")
        if before != shas:
            fail("BINARY", "toolchain record disagrees with binary record")
        probes = binaries.get("score_probes")
        if not isinstance(probes, dict) or set(probes) != set(ARMS):
            fail("BINARY", "score probe inventory drifted")
        for arm in ARMS:
            path = probes[arm].get("path")
            if not path or sha256_file(path) != probes[arm].get("sha256"):
                fail("BINARY", f"score probe {arm} changed")

    def check_toolchain(self):
        toolchain = self.data["toolchain.json"]
        if toolchain.get("schema") != SCHEMA:
            fail("TOOLCHAIN", "toolchain schema mismatch")
        rustc = toolchain.get("rustc") or ""
        if "rustc " not in rustc:
            fail("TOOLCHAIN", "rustc version missing")
        if toolchain.get("arm_features") != {"A": None, "C": F_FEATURE,
                                            "F": F_FEATURE}:
            fail("TOOLCHAIN", "arm feature set drifted")
        if toolchain.get("cargo_lock_sha256") != sha256_file(
                os.path.join(self.root, "Cargo.lock")):
            fail("TOOLCHAIN", "Cargo.lock changed during the campaign")
        for key in ("A", "C", "F"):
            if not toolchain.get("build_commands", {}).get(key):
                fail("TOOLCHAIN", f"build command for {key} is missing")

    # ---- corpus / format / sentinel --------------------------------------
    def check_corpus(self):
        corpus = self.data["corpus.json"]
        if corpus.get("manifest_sha256") != CORPUS_SHA:
            fail("CORPUS", "corpus manifest digest drifted")
        digests = {entry.get("sha256") for entry in corpus.get("corpora") or ()}
        if digests != {CORPUS_SHA}:
            fail("CORPUS", "canonical corpus digest drifted")

    def check_format(self):
        sizes = self.data["sizes.json"]
        layouts = sizes.get("layouts") or {}
        digests = sizes.get("segment_digests") or {}
        if set(layouts) != {"A", "C", "F"}:
            fail("FORMAT", "layout inventory drifted")
        for key in ("A", "C", "F"):
            builds = sizes.get("builds", {}).get(key)
            if not isinstance(builds, dict) or set(builds) != {"10000", "100000"}:
                fail("FORMAT", f"{key} size build inventory drifted")
            for n in ("10000", "100000"):
                records = builds[n]
                if len(records) != 3:
                    fail("FORMAT", f"{key} n{n} does not have three fresh builds")
                if len({json.dumps(entry["layout"], sort_keys=True)
                        for entry in records}) != 1:
                    fail("FORMAT", f"{key} n{n} layout drifted across builds")
                if len({entry["digest"] for entry in records}) != 1:
                    fail("FORMAT", f"{key} n{n} segment digest drifted")
                layout = layouts[key].get(n)
                if layout is None or layout != records[-1]["layout"]:
                    fail("FORMAT", f"{key} n{n} recorded layout drifted")
                if layout.get("stored_version") != 2:
                    fail("FORMAT", f"{key} n{n} stored version is not 2")
                if layout.get("codec_id") != 1:
                    fail("FORMAT", f"{key} n{n} codec id is not 1")
                if [13, 1] not in (layout.get("required_features") or []):
                    fail("FORMAT", f"{key} n{n} lacks feature [13, 1]")
        canonical = {n: json.dumps(layouts["A"][n], sort_keys=True)
                     for n in ("10000", "100000")}
        for key in ("C", "F"):
            for n in ("10000", "100000"):
                if json.dumps(layouts[key].get(n), sort_keys=True) != canonical[n]:
                    fail("FORMAT", f"{key} n{n} layout differs from A")
                if digests.get(key, {}).get(n) != digests.get("A", {}).get(n):
                    fail("FORMAT", f"{key} n{n} segment digest differs from A")
        layout = layouts["A"]["100000"]
        if layout.get("committed_index_bytes") != A_100K_TOTAL:
            fail("SENTINEL", "committed byte sentinel drifted")
        if layout.get("stored_bytes") != A_100K_STORED:
            fail("SENTINEL", "stored byte sentinel drifted")

    # ---- oracle / score / mode / codegen ---------------------------------
    def check_oracle(self):
        parity = self.data["score-parity.json"].get("lanes") or {}
        if set(parity) != set(LANE_IDS):
            fail("ORACLE", "score parity lane inventory drifted")
        for lane_id, record in parity.items():
            if record.get("identical") is not True:
                fail("SCORE", f"{lane_id} score bits differ across arms")
            if record.get("hits") != record.get("total_hits"):
                fail("SCORE", f"{lane_id} hits/total_hits disagree")

    def check_mode(self):
        modes = self.data["mode-proof.json"]
        if modes.get("schema") != SCHEMA:
            fail("MODE", "mode proof schema mismatch")
        probes = modes.get("probes")
        if not isinstance(probes, list):
            fail("MODE", "mode probe list missing")
        seen = {}
        for probe in probes:
            seen[probe.get("label")] = probe
        if set(seen) != {"A", "C", "G", "P", "INVALID", "MISSING"}:
            fail("MODE", "mode truth table is incomplete")
        for label in ("A", "C", "G", "P"):
            if seen[label].get("observed_status") != "ok":
                fail("MODE", f"{label} probe did not succeed")
        if seen["G"].get("environment_mode") != "disabled":
            fail("MODE", "G is not the generic (disabled) mode")
        if seen["P"].get("environment_mode") != "enabled":
            fail("MODE", "P is not the physical (enabled) mode")
        if seen["C"].get("environment_mode") != "disabled":
            fail("MODE", "C must run with the gate disabled")
        if seen["A"].get("environment_mode") is not None:
            fail("MODE", "A must not set the diagnostic mode")
        for label in ("INVALID", "MISSING"):
            if seen[label].get("observed_status") != "error":
                fail("MODE", f"{label} must be a typed error")
        for arm, mode in (("A", None), ("C", "disabled"), ("G", "disabled"),
                          ("P", "enabled")):
            for record in self.slots.values():
                if record["arm"] == arm and record["mode"] != mode:
                    fail("MODE", f"slot {record['slot_index']} mode drifted")

    def check_codegen(self):
        codegen = self.data["codegen.json"]
        if codegen.get("schema") != SCHEMA:
            fail("CODEGEN", "codegen schema mismatch")
        for key in ("A", "C", "D", "E"):
            if key not in codegen:
                fail("CODEGEN", f"codegen arm {key} missing")
        checks = self.data["measurements.json"].get("codegen_checks")
        if not isinstance(checks, dict):
            fail("CODEGEN", "structural codegen checks missing")
        for key in ("C_physical_present", "D_physical_absent",
                    "A_generic_inlined", "C_generic_inlined",
                    "E_generic_out_of_line", "E_dispatch_probe"):
            if checks.get(key) is not True:
                fail("CODEGEN", f"structural codegen check {key} failed")
        for arm in ("A", "C", "D", "E"):
            symbols = codegen[arm].get("symbols") or {}
            for name, record in symbols.items():
                if record.get("instructions", 0) <= 0:
                    fail("CODEGEN", f"{arm} symbol {name} is empty")
                if record.get("drop_glue"):
                    fail("CODEGEN", f"{arm} symbol {name} is drop glue")

    # ---- independent derivation ------------------------------------------
    def derive(self):
        times = {}
        for index, record in self.slots.items():
            for lane in record["lanes"]:
                times[(index, lane["id"])] = nearest_rank_median(lane["samples_ns"])
        ratios = {}
        for lane_id in LANE_IDS:
            entry = {"C/A": [], "G/A": [], "P/A": [], "P/G": [], "A2/A1": []}
            for block in range(1, BLOCKS + 1):
                indexes = [index for index, record in self.slots.items()
                           if record["block"] == block]
                means = {}
                for arm in ARMS:
                    slots = [index for index in indexes
                             if self.slots[index]["arm"] == arm]
                    values = [times[(index, lane_id)] for index in slots]
                    means[arm] = sum(values) / len(values)
                    require_ratio(means[arm], f"{lane_id} block {block} {arm}")
                    if means[arm] <= 0:
                        fail("RATIO", f"{lane_id} block {block} {arm} is zero")
                a_slots = sorted(index for index in indexes
                                 if self.slots[index]["arm"] == "A")
                first = times[(a_slots[0], lane_id)]
                second = times[(a_slots[1], lane_id)]
                if first <= 0:
                    fail("RATIO", f"{lane_id} block {block} zero A denominator")
                entry["A2/A1"].append(second / first)
                entry["C/A"].append(means["C"] / means["A"])
                entry["G/A"].append(means["G"] / means["A"])
                entry["P/A"].append(means["P"] / means["A"])
                if means["G"] <= 0:
                    fail("RATIO", f"{lane_id} block {block} P/G zero denominator")
                entry["P/G"].append(means["P"] / means["G"])
            entry["medians"] = {key: block_median_of_four(entry[key])
                                for key in ("C/A", "G/A", "P/A", "P/G")}
            entry["a_drift_median"] = block_median_of_four(entry["A2/A1"])
            entry["a_drift_outliers"] = sum(
                1 for value in entry["A2/A1"]
                if value < AA_BLOCK_MIN or value > AA_BLOCK_MAX)
            ratios[lane_id] = entry
        return ratios

    def cross_check(self, ratios):
        recorded = self.data["measurements.json"].get("ratios")
        if not isinstance(recorded, dict):
            fail("RATIO", "controller ratios are missing")
        for lane_id in LANE_IDS:
            entry, claimed = ratios[lane_id], recorded.get(lane_id) or {}
            for key in ("C/A", "G/A", "P/A", "P/G"):
                mine = [round(value, 12) for value in entry[key]]
                theirs = [round(value, 12) for value in claimed.get(key) or []]
                if mine != theirs:
                    fail("RATIO", f"{lane_id} per-block {key} disagrees")
                if abs(entry["medians"][key]
                       - require_ratio(claimed["medians"][key], "claimed median")) > 1e-9:
                    fail("RATIO", f"{lane_id} median {key} disagrees")
            drift = [round(value, 12) for value in entry["A2/A1"]]
            if drift != [round(value, 12) for value in claimed.get("A2/A1") or []]:
                fail("RATIO", f"{lane_id} A/A block ratios disagree")
            if abs(entry["a_drift_median"]
                   - require_ratio(claimed["a_drift_median"], "claimed drift")) > 1e-9:
                fail("RATIO", f"{lane_id} A/A drift median disagrees")
            if entry["a_drift_outliers"] != claimed.get("a_drift_outliers"):
                fail("RATIO", f"{lane_id} A/A outlier count disagrees")
        counts = self.data["measurements.json"].get("counts") or {}
        expected_samples = (BATCHED if self.regime == "batched" else UNBATCHED)
        if counts.get("samples") != SLOTS * len(LANE_IDS) * expected_samples:
            fail("SAMPLE", "recorded sample count drifted")
        if counts.get("warmups") != SLOTS * len(LANE_IDS) * WARMUPS:
            fail("SAMPLE", "recorded warmup count drifted")
        if counts.get("slots") != SLOTS:
            fail("SCHEDULE", "recorded slot count drifted")

    # ---- classification --------------------------------------------------
    def classify(self, ratios):
        unstable = []
        for lane_id in LANE_IDS:
            entry = ratios[lane_id]
            if not AA_MIN <= entry["a_drift_median"] <= AA_MAX:
                unstable.append(f"{lane_id} A/A median {entry['a_drift_median']:.4f}")
            elif entry["a_drift_outliers"] > AA_BLOCK_OUTLIERS:
                unstable.append(f"{lane_id} A/A outliers {entry['a_drift_outliers']}")
        if self.regime == "unbatched" and unstable:
            return {"status": STATUS_UNSTABLE, "reasons": unstable}
        if self.regime == "batched":
            return {"status": "F_BATCHED_OBSERVATION_ONLY",
                    "reasons": ["batched A/A is recorded but cannot classify"]}
        for lane_id in LOW_MATCH_10K:
            value = ratios[lane_id]["medians"]["C/A"]
            if value < C_MIN_10K:
                return {"status": STATUS_NO_REPRO,
                        "reasons": [f"{lane_id} C/A {value:.4f} < {C_MIN_10K}"]}
        for lane_id in LOW_MATCH_100K:
            value = ratios[lane_id]["medians"]["C/A"]
            if value < C_MIN_100K:
                return {"status": STATUS_NO_REPRO,
                        "reasons": [f"{lane_id} C/A {value:.4f} < {C_MIN_100K}"]}
        rejected = [f"{lane_id} G/A {ratios[lane_id]['medians']['G/A']:.4f} > "
                    f"{G_CAMPAIGN_MAX}" for lane_id in LANE_IDS
                    if ratios[lane_id]["medians"]["G/A"] > G_CAMPAIGN_MAX]
        if rejected:
            return {"status": STATUS_REJECTED, "reasons": rejected}
        observations = [f"{lane_id} block G/A {value:.4f}"
                        for lane_id in LANE_IDS
                        for value in ratios[lane_id]["G/A"] if value > G_BLOCK_OBSERVE]
        return {"status": STATUS_NEUTRAL, "reasons": [], "observations": observations}

    def receipt(self, ratios, verdict):
        return {
            "schema": "pr15i-c-f-final-verification-v1",
            "campaign": self.name, "regime": self.regime,
            "diagnostic_only": True, "protocol_sha256": PROTOCOL_SHA,
            "status": verdict["status"], "reasons": verdict["reasons"],
            "observations": verdict.get("observations", []),
            "ratios": ratios,
            "primary_lanes": {lane: {"P/A": ratios[lane]["medians"]["P/A"],
                                     "P/G": ratios[lane]["medians"]["P/G"]}
                              for lane in PRIMARY},
            "generic_aggregate_max": G_AGGREGATE_MAX,
        }


def verify_campaign(root, path, write_receipt=True):
    campaign = Campaign(root, path)
    campaign.load()
    campaign.check_protocol()
    source = campaign.check_source()
    campaign.check_schedule()
    campaign.check_lanes()
    campaign.check_samples()
    campaign.check_contention()
    campaign.check_binaries()
    campaign.check_toolchain()
    campaign.check_corpus()
    campaign.check_format()
    campaign.check_oracle()
    campaign.check_mode()
    campaign.check_codegen()
    ratios = campaign.derive()
    campaign.cross_check(ratios)
    verdict = campaign.classify(ratios)
    receipt = campaign.receipt(ratios, verdict)
    receipt["generic_body_sha256"] = source["generic_body_sha256"]
    if write_receipt:
        os.makedirs(os.path.join(root, REVIEWS_ROOT), exist_ok=True)
        target = os.path.join(root, REVIEWS_ROOT,
                              f"f-final-{campaign.name}.json")
        if os.path.exists(target):
            fail("RECEIPT", f"receipt {target} already exists; refusing to overwrite")
        with open(target, "x", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return receipt


def aggregate(root, series_root, verify_only=False):
    series_root = os.path.realpath(series_root)
    if not is_within(series_root, os.path.join(root, ALLOWED)):
        fail("PATH", "series root escapes the allowed diagnostic root")
    present = sorted(entry for entry in os.listdir(series_root)
                     if os.path.isdir(os.path.join(series_root, entry)))
    if present != sorted(CAMPAIGNS):
        fail("SERIES", f"campaign set is {present}")
    receipts = {}
    for name in CAMPAIGNS:
        receipts[name] = verify_campaign(root, os.path.join(series_root, name),
                                        write_receipt=not verify_only)
    unbatched = [name for name in CAMPAIGNS if REGIME[name] == "unbatched"]
    if len(unbatched) != 2:
        fail("SERIES", "exactly two unbatched campaigns are required")
    references = {}
    for name in CAMPAIGNS:
        environment = load_json(os.path.join(series_root, name, "raw",
                                             "environment.json"))
        toolchain = load_json(os.path.join(series_root, name, "raw",
                                           "toolchain.json"))
        references[name] = (environment["host_fingerprint"], environment["filesystem"],
                            environment["cpu_affinity"]["mode"],
                            toolchain["rustc"], toolchain["cargo_lock_sha256"])
    first = references[CAMPAIGNS[0]]
    for name in CAMPAIGNS[1:]:
        if references[name] != first:
            fail("SERIES", f"{name} host/toolchain/affinity differs")

    def lane_values(lane_id, key):
        return [receipts[name]["ratios"][lane_id]["medians"][key]
                for name in unbatched]

    unstable = []
    for lane_id in LANE_IDS:
        for name in unbatched:
            entry = receipts[name]["ratios"][lane_id]
            if not AA_MIN <= entry["a_drift_median"] <= AA_MAX:
                unstable.append(f"{name} {lane_id} A/A {entry['a_drift_median']:.4f}")
            elif entry["a_drift_outliers"] > AA_BLOCK_OUTLIERS:
                unstable.append(f"{name} {lane_id} A/A outliers")
    if unstable:
        return _finish(root, {"status": STATUS_UNSTABLE, "reasons": unstable,
                              "campaigns": receipts}, write=not verify_only)
    for lane_id in LOW_MATCH_10K + LOW_MATCH_100K:
        for name in unbatched:
            value = receipts[name]["ratios"][lane_id]["medians"]["C/A"]
            floor = C_MIN_10K if lane_id in LOW_MATCH_10K else C_MIN_100K
            if value < floor:
                return _finish(root, {"status": STATUS_NO_REPRO,
                                      "reasons": [f"{name} {lane_id} C/A "
                                                  f"{value:.4f} < {floor}"],
                                      "campaigns": receipts},
                               write=not verify_only)
    rejected, observations = [], []
    for lane_id in LANE_IDS:
        for name in unbatched:
            value = receipts[name]["ratios"][lane_id]["medians"]["G/A"]
            if value > G_CAMPAIGN_MAX:
                rejected.append(f"{name} {lane_id} G/A {value:.4f} > {G_CAMPAIGN_MAX}")
        values = lane_values(lane_id, "G/A")
        aggregate_value = sum(values) / len(values)
        if aggregate_value > G_AGGREGATE_MAX:
            rejected.append(f"{lane_id} aggregate G/A {aggregate_value:.4f} > "
                            f"{G_AGGREGATE_MAX}")
        for name in unbatched:
            for block_value in receipts[name]["ratios"][lane_id]["G/A"]:
                if block_value > G_BLOCK_OBSERVE:
                    observations.append(f"{name} {lane_id} block G/A "
                                        f"{block_value:.4f}")
    if rejected:
        return _finish(root, {"status": STATUS_REJECTED, "reasons": rejected,
                              "observations": observations, "campaigns": receipts},
                       write=not verify_only)
    return _finish(root, {"status": STATUS_NEUTRAL, "reasons": [],
                          "observations": observations, "campaigns": receipts},
                   write=not verify_only)


def _finish(root, verdict, write=True):
    summary = {
        "schema": "pr15i-c-f-final-series-v1",
        "status": verdict["status"], "reasons": verdict["reasons"],
        "observations": verdict.get("observations", []),
        "diagnostic_only": True, "protocol_sha256": PROTOCOL_SHA,
        "campaigns": {name: verdict["campaigns"][name]["status"]
                      for name in verdict["campaigns"]},
        "aggregates": {},
    }
    unbatched = [name for name in CAMPAIGNS if REGIME[name] == "unbatched"]
    for lane_id in LANE_IDS:
        values = {key: [verdict["campaigns"][name]["ratios"][lane_id]["medians"][key]
                        for name in unbatched]
                  for key in ("C/A", "G/A", "P/A", "P/G")}
        summary["aggregates"][lane_id] = {
            key: sum(series) / len(series) for key, series in values.items()}
    summary["aggregates"]["primary"] = {
        lane: summary["aggregates"][lane] for lane in PRIMARY}
    if write:
        os.makedirs(os.path.join(root, REVIEWS_ROOT), exist_ok=True)
        path = os.path.join(root, REVIEWS_ROOT, "f-final-series.json")
        if os.path.exists(path):
            fail("RECEIPT", "series receipt already exists")
        with open(path, "x", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return summary


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C-F independent verifier")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--campaign")
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--series-root")
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.aggregate:
            if not args.series_root:
                fail("USAGE", "--aggregate requires --series-root")
            summary = aggregate(os.path.realpath(args.checkout_root),
                                args.series_root, verify_only=args.verify_only)
            print(f"status={summary['status']}")
            for lane_id, values in summary["aggregates"].items():
                if lane_id == "primary":
                    continue
                print(f"  {lane_id}: G/A={values['G/A']:.4f} "
                      f"C/A={values['C/A']:.4f} P/G={values['P/G']:.4f}")
            for reason in summary["reasons"]:
                print(f"  reason: {reason}")
            return 0
        if not args.campaign:
            fail("USAGE", "--campaign or --aggregate is required")
        receipt = verify_campaign(os.path.realpath(args.checkout_root),
                                  args.campaign,
                                  write_receipt=not args.verify_only)
        print(f"status={receipt['status']}")
        for reason in receipt["reasons"]:
            print(f"  reason: {reason}")
        return 0
    except VerifyError as error:
        print(f"VERIFY_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""PR 15I-C dispatch-isolation — independent verifier.

Recomputes every slot median (frozen PR15D nearest-rank), block mean, ratio,
campaign median, A/A drift and classification from sealed raw. It imports no
controller statistics or classification code; it may use the frozen PR15D oracle
and the mechanical Git-blob source proof.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source_proof = _load("pr15i_c_dispatch_source_proof_verify",
                     os.path.join(HERE, "dispatch_source_proof.py"))
base = _load("pr15i_c_dispatch_base",
             os.path.join(ROOT, "benchmarks", "pr15e_b1", "run_targeted.py"))

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "dispatch_protocol_v1.json")
PROTOCOL_SCHEMA = "pr15i-c-dispatch-isolation-v1"
SCHEMA = "pr15i-c-dispatch-campaign-v1"
SEAL_SCHEMA = "pr15i-c-dispatch-seal-v1"
RECEIPT_SCHEMA = "pr15i-c-dispatch-verification-v1"
AGGREGATE_SCHEMA = "pr15i-c-dispatch-series-v1"
BASE_A = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
C_SHA = "658a2dde0e15c17e2b0c92278b5c922f5260fe60"
D_SHA = "9c710e5432aa17cdcd717ce40ad6f9a8167914f1"
E_SHA = "d97889d2debc14f1e4ea3c821089cd453ba1daab"
ARM_SOURCES = {"A": BASE_A, "C": C_SHA, "D": D_SHA, "E": E_SHA}
ARM_FEATURES = {"A": None, "C": "pr15ic-causal", "D": "pr15ic-causal",
                "E": "pr15ic-dispatch-isolation"}
ARM_MODE_VARIABLES = {"A": None, "C": "QUERVANT_PR15IC_CAUSAL_MODE",
                      "D": "QUERVANT_PR15IC_CAUSAL_MODE",
                      "E": "QUERVANT_PR15IC_DISPATCH_MODE"}
ARMS = ("A", "C", "D", "E")
SCHEDULE = ("ACDEEDCA", "EDCAACDE", "DCAEACED", "CEADDAEC")
BLOCKS = 4
SLOTS_PER_BLOCK = 8
SLOTS = 32
WARMUPS = 5
UNBATCHED_SAMPLES = 20
BATCHED_SAMPLES = 10
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
LOW_MATCH_LANES = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
)
CORPUS_SHA = "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151"
A_100K_TOTAL = 15_747_551
A_100K_STORED = 1_661_455
AA_MIN = 0.85
AA_MAX = 1.15
AA_OUTLIER_LIMIT = 1
NEUTRAL_MIN = 0.85
NEUTRAL_MAX = 1.08
REGRESSED_10K = 1.15
REGRESSED_100K = 1.40
TOLERANCE = 1e-12
CAMPAIGNS = (("unbatched-01", "unbatched"), ("batched-01", "batched"),
             ("unbatched-02", "unbatched"), ("batched-02", "batched"))
SERIES_ORDER = [name for name, _ in CAMPAIGNS]
RAW_METADATA = (
    "authorization.json", "protocol.json", "source-proof.json", "corpus.json",
    "environment.json", "toolchain.json", "binaries.json", "sizes.json",
    "score-parity.json", "measurements.json", "manifest.json",
)
REQUIRED_RAW = (
    *RAW_METADATA,
    *(f"slots/slot-{index:02d}.json" for index in range(1, SLOTS + 1)),
)


class VerificationFailed(Exception):
    def __init__(self, rule, detail):
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


def require(condition, code, detail):
    if not condition:
        raise VerificationFailed(code, detail)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def nearest_rank_median(values):
    require(values, "DV_SAMPLE", "empty sample list")
    for value in values:
        require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
                "DV_SAMPLE", f"invalid sample {value!r}")
    ordered = sorted(values)
    return ordered[(50 * len(ordered) + 99) // 100 - 1]


def repeat_count_for(lane_id):
    return REPEAT_SHORT if lane_id in LOW_MATCH_LANES else REPEAT_OTHER


def verify_protocol(root, manifest):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    require(protocol.get("schema") == PROTOCOL_SCHEMA, "DV_PROTOCOL", "bad schema")
    require(protocol.get("baseline_source") == BASE_A, "DV_PROTOCOL", "baseline drift")
    require(protocol.get("c_source") == C_SHA, "DV_PROTOCOL", "C drift")
    require(protocol.get("d_source") == D_SHA, "DV_PROTOCOL", "D drift")
    require(protocol.get("e_source") == E_SHA, "DV_PROTOCOL", "E drift")
    require(tuple(protocol.get("arm_order_by_block", ())) == SCHEDULE, "DV_PROTOCOL",
            "schedule drift")
    for order in protocol["arm_order_by_block"]:
        require(len(order) == SLOTS_PER_BLOCK
                and all(order.count(arm) == 2 for arm in ARMS), "DV_SCHEDULE",
                f"unbalanced block {order!r}")
    require(tuple(protocol.get("low_match_lanes", ())) == LOW_MATCH_LANES,
            "DV_PROTOCOL", "low-match lanes drift")
    require(protocol.get("unbatched_samples_per_lane_slot") == UNBATCHED_SAMPLES,
            "DV_PROTOCOL", "unbatched sample count drift")
    require(protocol.get("batched_samples_per_lane_slot") == BATCHED_SAMPLES,
            "DV_PROTOCOL", "batched sample count drift")
    require(protocol.get("warmups_per_lane_slot") == WARMUPS, "DV_PROTOCOL",
            "warmup count drift")
    require(protocol.get("batched_repeat_count_absent_rare") == REPEAT_SHORT,
            "DV_PROTOCOL", "short repeat drift")
    require(protocol.get("batched_repeat_count_medium_common") == REPEAT_OTHER,
            "DV_PROTOCOL", "control repeat drift")
    require(protocol.get("100k_committed_index_bytes") == A_100K_TOTAL, "DV_PROTOCOL",
            "committed sentinel drift")
    require(protocol.get("100k_stored_bytes") == A_100K_STORED, "DV_PROTOCOL",
            "stored sentinel drift")
    require(protocol.get("frozen_feature_acceptance_protocol_unchanged") is True,
            "DV_PROTOCOL", "the frozen acceptance contract must stay unchanged")
    digest = sha256_file(os.path.join(root, PROTOCOL_REL))
    require(digest == manifest.get("protocol_sha256"), "DV_PROTOCOL",
            "protocol hash mismatch")
    require(digest == sha256_file(os.path.join(manifest["campaign_dir"], "raw",
                                               "protocol.json"))
            if "campaign_dir" in manifest else True, "DV_PROTOCOL",
            "sealed protocol copy mismatch")
    return digest


def canonical_campaign(root, campaign):
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c",
                                            "dispatch-isolation-v1"))
    candidate = os.path.realpath(campaign)
    require(os.path.commonpath([candidate, allowed]) == allowed and candidate != allowed,
            "DV_PATH", "campaign must be under target/pr15i-c/dispatch-isolation-v1")
    return candidate


def _no_symlinks(campaign, relative):
    current = campaign
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        require(not stat.S_ISLNK(os.lstat(current).st_mode), "DV_PATH",
                f"symlinked path component {current}")


def verify_inventory_and_seal(campaign):
    raw = os.path.join(campaign, "raw")
    require(os.path.isdir(raw), "DV_INVENTORY", "missing raw directory")
    _no_symlinks(campaign, "raw")
    found = []
    for root_dir, directories, files in os.walk(raw):
        for directory in directories:
            require(not os.path.islink(os.path.join(root_dir, directory)), "DV_PATH",
                    f"symlinked directory {directory}")
        for name in files:
            full = os.path.join(root_dir, name)
            require(not os.path.islink(full), "DV_PATH", f"symlinked file {full}")
            found.append(os.path.relpath(full, raw).replace(os.sep, "/"))
    expected = set(REQUIRED_RAW) | {"seal.json"}
    require(not (set(found) - expected), "DV_INVENTORY",
            f"unexpected raw files: {sorted(set(found) - expected)}")
    require(not (expected - set(found)), "DV_INVENTORY",
            f"missing raw files: {sorted(expected - set(found))}")
    seal_path = os.path.join(raw, "seal.json")
    require(os.path.isfile(seal_path), "DV_SEAL", "missing seal")
    seal = read_json(seal_path)
    require(seal.get("schema") == SEAL_SCHEMA, "DV_SEAL", "bad seal schema")
    files = seal.get("files")
    require(isinstance(files, dict) and set(files) == set(REQUIRED_RAW), "DV_SEAL",
            "seal inventory mismatch")
    before = {}
    for relative in REQUIRED_RAW:
        digest = sha256_file(os.path.join(raw, relative))
        require(digest == files[relative], "DV_SEAL", f"seal mismatch {relative}")
        before[relative] = digest
    return before


def verify_source_and_binaries(root, campaign, manifest):
    proof = source_proof.verify_all(root, BASE_A, C_SHA, D_SHA, E_SHA)
    recorded = read_json(os.path.join(campaign, "raw", "source-proof.json"))
    require(recorded.get("generic_body_sha256") == proof["generic_body_sha256"],
            "DV_SOURCE", "recorded generic body hashes differ from Git")
    require(recorded.get("d", {}).get("d_changed_paths") == proof["d"]["d_changed_paths"],
            "DV_SOURCE", "recorded D diff differs from Git")
    require(recorded.get("e", {}).get("e_changed_paths") == proof["e"]["e_changed_paths"],
            "DV_SOURCE", "recorded E diff differs from Git")
    binaries = read_json(os.path.join(campaign, "raw", "binaries.json"))
    adapters = binaries.get("adapters", {})
    require(set(adapters) == set(ARMS), "DV_BINARY", "binary inventory must name A/C/D/E")
    hashes = {}
    for arm in ARMS:
        entry = adapters[arm]
        require(entry.get("feature") == ARM_FEATURES[arm], "DV_FEATURE",
                f"arm {arm} feature mismatch")
        require(entry.get("mode_variable") == ARM_MODE_VARIABLES[arm], "DV_FEATURE",
                f"arm {arm} mode variable mismatch")
        path = entry.get("path")
        require(isinstance(path, str) and os.path.isabs(path) and os.path.isfile(path),
                "DV_BINARY", f"arm {arm} executable missing")
        require(not os.path.islink(path), "DV_BINARY", f"arm {arm} executable symlink")
        digest = sha256_file(path)
        require(digest == entry.get("sha256"), "DV_BINARY", f"arm {arm} hash mismatch")
        require(manifest.get("adapter_sha256", {}).get(arm) == digest, "DV_BINARY",
                f"arm {arm} manifest hash mismatch")
        hashes[arm] = digest
    require(len(set(hashes.values())) == 4, "DV_BINARY",
            "the four arm executables must be distinct")
    return {"proof": proof, "hashes": hashes}


def verify_indexes(campaign):
    sizes = read_json(os.path.join(campaign, "raw", "sizes.json"))
    layouts, digests = {}, {}
    rebuilt = 0
    for arm in ARMS:
        records = sizes.get("builds", {}).get(arm)
        require(isinstance(records, dict), "DV_FORMAT", f"missing {arm} builds")
        layouts[arm], digests[arm] = {}, {}
        for n in ("10000", "100000"):
            builds = records.get(n)
            require(isinstance(builds, list) and len(builds) == 3, "DV_FORMAT",
                    f"{arm} n{n} must have three rebuilds")
            require([entry.get("attempt") for entry in builds] == [1, 2, 3],
                    "DV_FORMAT", f"{arm} n{n} attempt order")
            seen_layouts, seen_digests = set(), set()
            for entry in builds:
                index_dir = os.path.join(campaign, "setup", "sizes", arm,
                                         f"n{n}-run{entry['attempt']}")
                require(os.path.isdir(index_dir), "DV_FORMAT",
                        f"missing rebuild {index_dir}")
                _no_symlinks(campaign, os.path.relpath(index_dir, campaign))
                layout = independent_layout(index_dir)
                digest = independent_segment_digest(index_dir)
                require(json.dumps(layout, sort_keys=True)
                        == json.dumps(entry["layout"], sort_keys=True), "DV_FORMAT",
                        f"{arm} n{n} run{entry['attempt']} layout drift")
                require(digest == entry.get("digest"), "DV_FORMAT",
                        f"{arm} n{n} run{entry['attempt']} digest drift")
                seen_layouts.add(json.dumps(layout, sort_keys=True))
                seen_digests.add(digest)
                rebuilt += 1
            require(len(seen_layouts) == 1 and len(seen_digests) == 1, "DV_FORMAT",
                    f"{arm} n{n} non-deterministic rebuilds")
            layouts[arm][n] = json.loads(next(iter(seen_layouts)))
            digests[arm][n] = next(iter(seen_digests))
    require(rebuilt == 24, "DV_FORMAT", f"expected 24 rebuilds, found {rebuilt}")
    for n in ("10000", "100000"):
        baseline = json.dumps(layouts["A"][n], sort_keys=True)
        for arm in ("C", "D", "E"):
            require(json.dumps(layouts[arm][n], sort_keys=True) == baseline,
                    "DV_FORMAT", f"n{n} {arm} layout differs from A")
            require(digests[arm][n] == digests["A"][n], "DV_FORMAT",
                    f"n{n} {arm} digest differs from A")
    require(layouts["A"]["100000"]["committed_index_bytes"] == A_100K_TOTAL,
            "DV_FORMAT", "committed sentinel mismatch")
    require(layouts["A"]["100000"]["stored_bytes"] == A_100K_STORED, "DV_FORMAT",
            "STORED sentinel mismatch")
    return layouts, digests


def independent_layout(index_dir):
    stored = segments = sidecar = 0
    stored_version = codec = features = None
    for root_dir, _dirs, files in os.walk(index_dir):
        for name in sorted(files):
            path = os.path.join(root_dir, name)
            relative = os.path.relpath(path, index_dir).replace(os.sep, "/")
            if relative.startswith("index/state/"):
                sidecar += os.path.getsize(path)
                continue
            if not relative.startswith("index/segments/"):
                continue
            with open(path, "rb") as handle:
                data = handle.read()
            segments += len(data)
            require(data[:8] == b"TRWSEG01", "DV_FORMAT", f"not a segment {path}")
            trailer = len(data) - 64
            footer_offset = int.from_bytes(data[trailer + 8:trailer + 16], "little")
            footer_len = int.from_bytes(data[trailer + 16:trailer + 24], "little")
            section_count = int.from_bytes(data[trailer + 24:trailer + 28], "little")
            cursor = footer_offset
            require(int.from_bytes(data[cursor:cursor + 2], "little") == 1,
                    "DV_FORMAT", "bad footer")
            cursor += 6
            required = int.from_bytes(data[cursor:cursor + 4], "little")
            cursor += 4
            features = []
            for _ in range(required):
                features.append([int.from_bytes(data[cursor:cursor + 2], "little"),
                                 int.from_bytes(data[cursor + 2:cursor + 4], "little")])
                cursor += 4
            optional = int.from_bytes(data[cursor:cursor + 4], "little")
            cursor += 4 + optional * 4
            for _ in range(section_count):
                kind = int.from_bytes(data[cursor:cursor + 2], "little")
                offset = int.from_bytes(data[cursor + 12:cursor + 20], "little")
                length = int.from_bytes(data[cursor + 20:cursor + 28], "little")
                cursor += 60
                if kind == 0x0007:
                    stored = length
                    stored_version = int.from_bytes(data[offset:offset + 2], "little")
                    codec = data[offset + 12] if stored_version == 2 else None
            require(cursor == footer_offset + footer_len, "DV_FORMAT",
                    "footer length mismatch")
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(index_dir) for f in fs)
    return {"stored_bytes": stored, "segment_bytes": segments,
            "sidecar_bytes": sidecar, "committed_index_bytes": total,
            "stored_version": stored_version, "codec_id": codec,
            "required_features": sorted(features or [])}


def independent_segment_digest(index_dir):
    digest = hashlib.sha256()
    segments = os.path.join(index_dir, "index", "segments")
    require(os.path.isdir(segments), "DV_FORMAT", f"missing segments {segments}")
    for name in sorted(os.listdir(segments)):
        path = os.path.join(segments, name)
        if not os.path.isfile(path):
            continue
        digest.update(name.encode() + b"\0")
        digest.update(str(os.path.getsize(path)).encode() + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def verify_slots(campaign, regime, manifest):
    slots = [read_json(os.path.join(campaign, "raw", "slots", f"slot-{index:02d}.json"))
             for index in range(1, SLOTS + 1)]
    batched = regime == "batched"
    samples_expected = BATCHED_SAMPLES if batched else UNBATCHED_SAMPLES
    unit = "batch" if batched else "single_query"
    timing = "batch_ns" if batched else "engine_ns"
    require(len(slots) == SLOTS, "DV_SCHEDULE", f"expected {SLOTS} slots")
    seen = set()
    total_samples = total_warmups = 0
    for index, record in enumerate(slots, start=1):
        require(record.get("slot_index") == index, "DV_SCHEDULE", f"slot {index} order")
        require(index not in seen, "DV_SCHEDULE", f"duplicate slot {index}")
        seen.add(index)
        block, position = record.get("block"), record.get("position")
        arm = record.get("arm")
        require(block in (1, 2, 3, 4), "DV_SCHEDULE", f"slot {index} bad block")
        require(position in tuple(range(1, SLOTS_PER_BLOCK + 1)), "DV_SCHEDULE",
                f"slot {index} bad position")
        require(arm in ARMS, "DV_SCHEDULE", f"slot {index} bad arm")
        require(arm == SCHEDULE[block - 1][position - 1], "DV_SCHEDULE",
                f"slot {index} violates the frozen schedule")
        require(record.get("source_sha") == ARM_SOURCES[arm], "DV_SOURCE",
                f"slot {index} arm source mismatch")
        require(record.get("executed_binary_path")
                == manifest["adapter_path"][arm], "DV_BINARY",
                f"slot {index} executed a different {arm} binary path")
        require(record.get("binary_sha256") == manifest["adapter_sha256"][arm],
                "DV_BINARY", f"slot {index} {arm} binary hash drift")
        lanes = record.get("lanes")
        require(isinstance(lanes, list) and [lane["id"] for lane in lanes] == list(LANE_IDS),
                "DV_SCHEDULE", f"slot {index} lane set drift")
        for lane in lanes:
            require(lane.get("timing_field") == timing, "DV_UNIT",
                    f"slot {index} {lane['id']} timing field drift")
            require(lane.get("sample_unit") == unit, "DV_UNIT",
                    f"slot {index} {lane['id']} sample unit drift")
            warmups = lane.get("warmup_ids")
            require(isinstance(warmups, list) and len(warmups) == WARMUPS, "DV_SAMPLE",
                    f"slot {index} {lane['id']} warmup count drift")
            values = lane.get("samples_ns")
            require(isinstance(values, list) and len(values) == samples_expected,
                    "DV_SAMPLE", f"slot {index} {lane['id']} sample count")
            median = nearest_rank_median(values)
            require(lane.get("summary_ns", {}).get("median") == median, "DV_SAMPLE",
                    f"slot {index} {lane['id']} median is not nearest-rank")
            if batched:
                require(lane.get("repeat_count") == repeat_count_for(lane["id"]),
                        "DV_UNIT", f"slot {index} {lane['id']} repeat drift")
            total_samples += len(values)
            total_warmups += len(warmups)
        for phase in ("contention_before", "contention_after"):
            require(record.get(phase, {}).get("state") == "clear", "DV_CONTENTION",
                    f"slot {index} {phase} not clear")
    require(total_samples == SLOTS * len(LANE_IDS) * samples_expected, "DV_SAMPLE",
            f"total samples {total_samples}")
    require(total_warmups == SLOTS * len(LANE_IDS) * WARMUPS, "DV_SAMPLE",
            f"total warmups {total_warmups}")
    for block in range(1, BLOCKS + 1):
        arms = [record["arm"] for record in slots if record["block"] == block]
        require(all(arms.count(arm) == 2 for arm in ARMS), "DV_SCHEDULE",
                f"block {block} is not balanced")
    return slots


def verify_oracle(campaign, slots):
    corpus_dir = os.path.join(campaign, "setup", "corpus")
    require(os.path.isdir(corpus_dir), "DV_ORACLE", "missing corpus directory")
    _manifest, rows = base.oracle.load_and_verify(corpus_dir)
    recorded = read_json(os.path.join(campaign, "raw", "corpus.json"))
    require(recorded.get("manifest_sha256") == CORPUS_SHA, "DV_ORACLE",
            "corpus digest drift")
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    require([lane["id"] for lane in lanes] == list(LANE_IDS), "DV_ORACLE",
            "lane order drift")
    expected = {lane["id"]: base.oracle.expected(
        rows=rows[lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
        for lane in lanes}
    for record in slots:
        for lane in record["lanes"]:
            lane_id = lane["id"]
            require(lane.get("oracle_ok") is True, "DV_ORACLE",
                    f"slot {record['slot_index']} {lane_id} oracle not ok")
            require(lane.get("total_hits") == expected[lane_id]["total_hits"],
                    "DV_ORACLE", f"slot {record['slot_index']} {lane_id} total_hits")
            require(lane.get("doc_ids") == expected[lane_id]["doc_ids"], "DV_ORACLE",
                    f"slot {record['slot_index']} {lane_id} key order")
    parity = read_json(os.path.join(campaign, "raw", "score-parity.json"))
    recorded_lanes = parity.get("lanes", {})
    require(set(recorded_lanes) == set(LANE_IDS), "DV_SCORE",
            "score parity lane set drift")
    for lane_id, entry in recorded_lanes.items():
        require(entry.get("identical") is True, "DV_SCORE", f"{lane_id} not identical")
    return expected


def independently_derive(slots):
    means = {}
    for lane_id in LANE_IDS:
        for block in range(1, BLOCKS + 1):
            for arm in ARMS:
                medians = [nearest_rank_median(lane["samples_ns"])
                           for record in slots
                           if record["block"] == block and record["arm"] == arm
                           for lane in record["lanes"] if lane["id"] == lane_id]
                require(len(medians) == 2, "DV_RATIO",
                        f"{lane_id} block {block} {arm} slot drift")
                means[(arm, lane_id, block)] = sum(medians) / 2
    ratios = {}
    for lane_id in LANE_IDS:
        entry = {"C/A": [], "D/A": [], "E/A": [], "A2/A1": []}
        for block in range(1, BLOCKS + 1):
            a = means[("A", lane_id, block)]
            require(a > 0, "DV_RATIO", f"{lane_id} block {block} zero denominator")
            for arm in "CDE":
                entry[f"{arm}/A"].append(means[(arm, lane_id, block)] / a)
            ordered_slots = sorted(
                (record for record in slots
                 if record["block"] == block and record["arm"] == "A"),
                key=lambda record: record["slot_index"])
            first = next(lane["summary_ns"]["median"] for lane in ordered_slots[0]["lanes"]
                         if lane["id"] == lane_id)
            second = next(lane["summary_ns"]["median"] for lane in ordered_slots[1]["lanes"]
                          if lane["id"] == lane_id)
            require(first > 0, "DV_RATIO", f"{lane_id} block {block} zero A median")
            entry["A2/A1"].append(second / first)
        ordered = sorted(entry["A2/A1"])
        entry["a_drift_median"] = (ordered[1] + ordered[2]) / 2
        entry["a_drift_outliers"] = sum(1 for value in entry["A2/A1"]
                                        if value > 1.25 or value < 1 / 1.25)
        entry["medians"] = {}
        for key in ("C/A", "D/A", "E/A"):
            values = sorted(entry[key])
            entry["medians"][key] = (values[1] + values[2]) / 2
        ratios[lane_id] = entry
    return ratios


def compare_with_controller(ratios, measurements):
    reported = measurements.get("ratios", {})
    require(set(reported) == set(LANE_IDS), "DV_RATIO", "controller lane set drift")
    for lane_id in LANE_IDS:
        for key in ("C/A", "D/A", "E/A"):
            for expected, actual in zip(ratios[lane_id][key],
                                        reported[lane_id].get(key, [])):
                require(abs(expected - actual) <= TOLERANCE, "DV_RATIO",
                        f"{lane_id} {key} block ratio drift")
            require(abs(ratios[lane_id]["medians"][key]
                        - reported[lane_id].get("medians", {}).get(key, -1)) <= TOLERANCE,
                    "DV_RATIO", f"{lane_id} {key} median drift")
        require(abs(ratios[lane_id]["a_drift_median"]
                    - reported[lane_id].get("a_drift_median", -1)) <= TOLERANCE,
                "DV_RATIO", f"{lane_id} A/A drift drift")


def a_a_stable(ratios):
    for lane_id in LANE_IDS:
        entry = ratios[lane_id]
        if not (AA_MIN <= entry["a_drift_median"] <= AA_MAX):
            return False, lane_id
        if entry["a_drift_outliers"] > AA_OUTLIER_LIMIT:
            return False, lane_id
    return True, None


def classify_cell(lane_id, value):
    if value < NEUTRAL_MIN:
        return "IMPROVED"
    if value <= NEUTRAL_MAX:
        return "NEUTRAL"
    floor = REGRESSED_100K if lane_id.startswith("pr15d_v1/100000/") else REGRESSED_10K
    if value >= floor:
        return "REGRESSED"
    return "INTERMEDIATE"


def classify_campaign(ratios):
    return {lane_id: {arm: classify_cell(lane_id, ratios[lane_id]["medians"][f"{arm}/A"])
                      for arm in ("C", "D", "E")}
            for lane_id in LOW_MATCH_LANES}


def classify_series(unbatched, structural_ok=True):
    """Apply the §8 precedence exactly."""
    if not structural_ok:
        return {"disposition": "15IC_DISPATCH_DIAG_INCONCLUSIVE",
                "reason": "structural/source control failed"}
    stability = {campaign: a_a_stable(ratios) for campaign, ratios in unbatched.items()}
    if not all(ok for ok, _lane in stability.values()):
        return {"disposition": "15IC_DISPATCH_DIAG_BLOCKED",
                "reason": "A/A within-campaign stability failed",
                "a_a": {campaign: {"stable": ok, "lane": lane}
                        for campaign, (ok, lane) in stability.items()}}
    require(len(unbatched) == 2, "DV_SERIES",
            f"classification requires exactly two unbatched campaigns, got {len(unbatched)}")
    cells = {campaign: classify_campaign(ratios)
             for campaign, ratios in unbatched.items()}
    for campaign in cells:
        for lane_id in LOW_MATCH_LANES:
            if cells[campaign][lane_id]["C"] != "REGRESSED":
                return {"disposition": "15IC_DISPATCH_DIAG_NOT_REPRODUCED",
                        "reason": f"C/A not regressed on {lane_id} in {campaign}",
                        "cells": cells}
    classes = {arm: set() for arm in ("C", "D", "E")}
    for campaign in cells:
        for lane_id in LOW_MATCH_LANES:
            for arm in ("C", "D", "E"):
                classes[arm].add(cells[campaign][lane_id][arm])
    if any(len(classes[arm]) != 1 for arm in ("D", "E")):
        return {"disposition": "15IC_DISPATCH_DIAG_MIXED",
                "reason": "D/E classes differ across lanes or campaigns",
                "arm_classes": {arm: sorted(values) for arm, values in classes.items()},
                "cells": cells}
    if classes["C"] != {"REGRESSED"}:
        return {"disposition": "15IC_DISPATCH_DIAG_MIXED",
                "reason": "C/A classes are not uniformly REGRESSED",
                "cells": cells}
    d_class = next(iter(classes["D"]))
    e_class = next(iter(classes["E"]))
    table = {
        ("NEUTRAL", "NEUTRAL"): "15IC_DISPATCH_DIAG_RUNTIME_ASSOCIATED",
        ("REGRESSED", "NEUTRAL"): "15IC_DISPATCH_DIAG_COMPILED_CANDIDATE_ASSOCIATED",
        ("NEUTRAL", "REGRESSED"): "15IC_DISPATCH_DIAG_SCAFFOLD_ASSOCIATED",
        ("REGRESSED", "REGRESSED"): "15IC_DISPATCH_DIAG_BROAD_ASSOCIATION",
    }
    disposition = table.get((d_class, e_class), "15IC_DISPATCH_DIAG_MIXED")
    return {"disposition": disposition, "d_class": d_class, "e_class": e_class,
            "arm_classes": {arm: sorted(values) for arm, values in classes.items()},
            "cells": cells}


def independent_codegen(campaign, manifest):
    """Re-capture the four sealed arm binaries with the dispatch symbol set.

    The verifier does not trust the controller-era `codegen_checks` flag: it
    re-runs the source-neutral capture itself on the immutable binaries.
    """
    capture = _load("pr15i_c_dispatch_codegen_verify",
                    os.path.join(HERE, "dispatch_codegen_capture.py"))
    out = os.path.join(os.path.dirname(campaign), "..", "..", "..",
                       "target", "pr15i-c", "dispatch-codegen-v1",
                       f"verify-{os.path.basename(campaign)}")
    out = os.path.realpath(out)
    if os.path.exists(os.path.join(out, "dispatch-codegen.json")):
        return capture.structural_checks(read_json(
            os.path.join(out, "dispatch-codegen.json")))
    payload = capture.capture({arm: manifest["adapter_path"][arm] for arm in ARMS},
                              out)
    return capture.structural_checks(payload)


def write_receipt(root, name, payload):
    reviews = os.path.join(root, "target", "pr15i-c", "reviews")
    os.makedirs(reviews, exist_ok=True)
    path = os.path.join(reviews, name)
    if os.path.exists(path):
        raise VerificationFailed("DV_RECEIPT", f"refusing to replace {path}")
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def verify(root, campaign, verify_only=False, write=True):
    campaign = canonical_campaign(root, campaign)
    before = verify_inventory_and_seal(campaign)
    manifest = read_json(os.path.join(campaign, "raw", "manifest.json"))
    measurements = read_json(os.path.join(campaign, "raw", "measurements.json"))
    require(manifest.get("schema") == SCHEMA, "DV_MANIFEST", "bad manifest schema")
    require(measurements.get("schema") == SCHEMA, "DV_MANIFEST", "bad measurement schema")
    regime = manifest.get("regime")
    require(regime in ("unbatched", "batched"), "DV_MANIFEST", "bad regime")
    require(regime == measurements.get("regime"), "DV_MANIFEST", "regime mismatch")
    protocol = verify_protocol(root, dict(manifest, campaign_dir=campaign))
    source = verify_source_and_binaries(root, campaign, manifest)
    layouts, digests = verify_indexes(campaign)
    slots = verify_slots(campaign, regime, manifest)
    verify_oracle(campaign, slots)
    ratios = independently_derive(slots)
    compare_with_controller(ratios, measurements)
    after = {relative: sha256_file(os.path.join(campaign, "raw", relative))
             for relative in REQUIRED_RAW}
    require(before == after, "DV_TAMPER", "raw changed during verification")
    environment = read_json(os.path.join(campaign, "raw", "environment.json"))
    payload = {
        "schema": RECEIPT_SCHEMA, "campaign": os.path.basename(campaign),
        "regime": regime, "protocol_sha256": protocol,
        "arm_sources": ARM_SOURCES, "adapter_sha256": source["hashes"],
        "cpu_affinity": manifest.get("cpu_affinity"),
        "host_fingerprint": environment.get("host_fingerprint"),
        "filesystem": manifest.get("filesystem"),
        "layouts": layouts, "segment_digests": digests,
        "lane_ratios": ratios,
        "a_a_stability": dict(zip(("stable", "lane"), a_a_stable(ratios))),
        "codegen_checks": independent_codegen(campaign, manifest),
        "controller_codegen_checks": manifest.get("codegen_checks"),
        "diagnostic_only": True, "feature_acceptance": False,
        "real_rustfs_not_a_diagnostic_gate": True,
        "raw_inventory": len(before),
        "seal_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode())
        .hexdigest(),
        "verify_only": verify_only,
    }
    if write:
        payload["receipt_path"] = write_receipt(
            root, f"dispatch-{os.path.basename(campaign)}-verification.json", payload)
    return payload


def aggregate(root, series_root, verify_only=False, write=True):
    series_root = os.path.realpath(series_root)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c",
                                            "dispatch-isolation-v1"))
    require(series_root == allowed, "DV_SERIES", "wrong series root")
    results = {}
    for campaign, regime in CAMPAIGNS:
        path = os.path.join(series_root, campaign)
        require(os.path.isdir(path), "DV_SERIES", f"missing campaign {campaign}")
        payload = verify(root, path, verify_only, write=False)
        require(payload["regime"] == regime, "DV_SERIES", f"{campaign} regime mismatch")
        results[campaign] = payload
    require(len({results[c]["protocol_sha256"] for c in results}) == 1, "DV_SERIES",
            "protocol identity differs across campaigns")
    require(len({results[c]["host_fingerprint"] for c in results}) == 1, "DV_SERIES",
            "host fingerprint differs across campaigns")
    require(len({json.dumps(results[c]["cpu_affinity"], sort_keys=True)
                 for c in results}) == 1, "DV_SERIES",
            "CPU affinity differs across campaigns")
    unbatched = {c: results[c]["lane_ratios"] for c in results
                 if results[c]["regime"] == "unbatched"}
    require(len(unbatched) == 2, "DV_SERIES", "expected two unbatched campaigns")
    structural_ok = all(
        results[c]["codegen_checks"].get("e_trampoline_present") for c in results)
    decision = classify_series(unbatched, structural_ok=structural_ok)
    batched = {c: results[c]["lane_ratios"] for c in results
               if results[c]["regime"] == "batched"}
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "protocol_sha256": results[SERIES_ORDER[0]]["protocol_sha256"],
        "series_order": SERIES_ORDER,
        "campaigns": {c: {"regime": results[c]["regime"],
                          "seal_sha256": results[c]["seal_sha256"],
                          "a_a": results[c]["a_a_stability"]} for c in results},
        "unbatched_decision": decision,
        "batched_observational": {
            campaign: {lane: {arm: ratios[lane]["medians"][f"{arm}/A"]
                              for arm in ("C", "D", "E")}
                       for lane in LOW_MATCH_LANES}
            for campaign, ratios in batched.items()},
        "codegen_checks": {c: results[c]["codegen_checks"] for c in results},
        "diagnostic_only": True,
        "feature_acceptance": False,
        "real_rustfs_not_a_diagnostic_gate": True,
        "verify_only": verify_only,
    }
    if write:
        name = "dispatch-series-aggregate-verification.json"
        path = os.path.join(root, "target", "pr15i-c", "reviews", name)
        suffix = 2
        while os.path.exists(path):
            name = f"dispatch-series-aggregate-verification-{suffix:02d}.json"
            path = os.path.join(root, "target", "pr15i-c", "reviews", name)
            suffix += 1
        payload["receipt_path"] = write_receipt(root, name, payload)
    return payload


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C dispatch-isolation verifier")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--campaign")
    mode.add_argument("--aggregate", action="store_true")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--series-root")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--no-receipt", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = os.path.realpath(args.checkout_root)
    try:
        if args.aggregate:
            series_root = args.series_root or os.path.join(
                root, "target", "pr15i-c", "dispatch-isolation-v1")
            payload = aggregate(root, series_root, args.verify_only,
                                write=not args.no_receipt)
            print(f"PR15I_C dispatch series: "
                  f"{payload['unbatched_decision']['disposition']}")
            print(json.dumps(payload["unbatched_decision"].get("arm_classes", {}),
                             sort_keys=True))
            return 0
        payload = verify(root, args.campaign, args.verify_only,
                         write=not args.no_receipt)
    except (VerificationFailed, source_proof.DispatchSourceError) as error:
        rule = getattr(error, "rule", "DV_SOURCE")
        detail = getattr(error, "detail", str(error))
        print(f"DV_BLOCKED: {rule}: {detail}", file=sys.stderr)
        return 3
    print(f"PR15I_C dispatch verify campaign={payload['campaign']} "
          f"regime={payload['regime']} A/A={payload['a_a_stability']['stable']}")
    for lane_id in LANE_IDS:
        entry = payload["lane_ratios"][lane_id]
        print(f"  {lane_id}: C/A={entry['medians']['C/A']:.4f} "
              f"D/A={entry['medians']['D/A']:.4f} "
              f"E/A={entry['medians']['E/A']:.4f} "
              f"drift={entry['a_drift_median']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

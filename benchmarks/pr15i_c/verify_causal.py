#!/usr/bin/env python3
"""PR 15I-C causal experiment — independent verifier.

Recomputes every diagnostic number from sealed raw evidence with its own
nearest-rank median, ratio arithmetic and §9 classification. It never imports the
controller's derivation, statistics or classification code; it may use the frozen
PR15D oracle/lane descriptors and the mechanical Git-blob source proof.
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


source_proof = _load("pr15i_c_causal_source_proof_verify",
                     os.path.join(HERE, "causal_source_proof.py"))
# Frozen PR15D/PR15E-B1 harness modules: lane descriptors, corpus oracle and the
# adapter metadata reader only. No controller statistics are imported.
base = _load("pr15i_c_causal_base",
             os.path.join(ROOT, "benchmarks", "pr15e_b1", "run_targeted.py"))

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "causal_protocol_v1.json")
PROTOCOL_SCHEMA = "pr15i-c-causal-v1"
SCHEMA = "pr15i-c-causal-campaign-v1"
SEAL_SCHEMA = "pr15i-c-causal-seal-v1"
RECEIPT_SCHEMA = "pr15i-c-causal-verification-v1"
AGGREGATE_SCHEMA = "pr15i-c-causal-series-v1"
BASELINE_SHA = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
HISTORICAL_CANDIDATE_SHA = "92a741876f6f6823d9d1792fc391dbb1bbecceb0"
MODE_VARIABLE = "QUERVANT_PR15IC_CAUSAL_MODE"
SOURCE_FEATURE = "pr15ic-causal"
ARM_ORDER_BY_BLOCK = ("ABCCBA", "BCAACB", "CABBAC", "ACBBCA")
BLOCKS = 4
SLOTS_PER_BLOCK = 6
SLOTS = 24
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
PRIMARY_LANES = (
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
)
SHORT_LANE_IDS = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
)
LOW_MATCH_LANES = SHORT_LANE_IDS
CORPUS_SHA = "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151"
A_100K_TOTAL = 15_747_551
A_100K_STORED = 1_661_455
LOW_RATIO_FLOOR = 1.20
REPRO_BLOCK_FLOOR = 1.10
NEUTRAL_CEILING = 1.05
NEUTRAL_BLOCK_CEILING = 1.15
MIXED_RATIO_FLOOR = 1.10
MIXED_BLOCK_FLOOR = 1.05
DRIFT_MIN = 0.85
DRIFT_MAX = 1.15
TOLERANCE = 1e-12
METADATA_RAW = (
    "authorization.json",
    "corpus.json",
    "environment.json",
    "toolchain.json",
    "source_proof.json",
    "mode_proof.json",
    "sizes.json",
    "score_parity.json",
    "measurements.json",
    "manifest.json",
)
REQUIRED_RAW = (
    *METADATA_RAW,
    *(f"slots/slot-{index:02d}.json" for index in range(1, SLOTS + 1)),
)
SERIES = (
    ("causal-unbatched-01", "unbatched"),
    ("causal-batched-01", "batched"),
    ("causal-unbatched-02", "unbatched"),
    ("causal-batched-02", "batched"),
)
SERIES_ORDER = [campaign for campaign, _ in SERIES]

StatusError = source_proof.SourceProofError


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
    """Frozen PR15D nearest-rank median: element (50*n+99)//100 - 1 of the sorted list."""
    require(values, "CV_SAMPLE", "empty sample list")
    count = len(values)
    for value in values:
        require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
                "CV_SAMPLE", f"invalid sample value {value!r}")
    ordered = sorted(values)
    return ordered[(50 * count + 99) // 100 - 1]


def repeat_count_for(lane_id):
    return REPEAT_SHORT if lane_id in SHORT_LANE_IDS else REPEAT_OTHER


def verify_protocol(root, manifest):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    require(protocol.get("schema") == PROTOCOL_SCHEMA, "CV_PROTOCOL", "bad schema")
    expected = {
        "baseline_source": BASELINE_SHA,
        "historical_candidate": HISTORICAL_CANDIDATE_SHA,
        "candidate_modes": {"B": "enabled", "C": "disabled"},
        "mode_variable": MODE_VARIABLE,
        "source_feature": SOURCE_FEATURE,
        "blocks_per_campaign": BLOCKS,
        "slots_per_block": SLOTS_PER_BLOCK,
        "slots_per_campaign": SLOTS,
        "warmups_per_lane_slot": WARMUPS,
        "unbatched_samples_per_lane_slot": UNBATCHED_SAMPLES,
        "batched_batches_per_lane_slot": BATCHED_SAMPLES,
        "short_lane_repeat_count": REPEAT_SHORT,
        "other_lane_repeat_count": REPEAT_OTHER,
        "frozen_corpus_sha256": CORPUS_SHA,
        "historical_100k_committed_bytes": A_100K_TOTAL,
        "historical_100k_stored_bytes": A_100K_STORED,
        "micro_attribution_low_ratio_floor": LOW_RATIO_FLOOR,
        "micro_attribution_neutral_ratio_ceiling": NEUTRAL_CEILING,
        "micro_attribution_neutral_per_block_ceiling": NEUTRAL_BLOCK_CEILING,
    }
    for key, value in expected.items():
        require(protocol.get(key) == value, "CV_PROTOCOL", f"{key} drifted")
    require(tuple(protocol.get("arm_order_by_block", ())) == ARM_ORDER_BY_BLOCK,
            "CV_PROTOCOL", "arm order drifted")
    for order in protocol["arm_order_by_block"]:
        require(len(order) == SLOTS_PER_BLOCK and sorted(order) == sorted("AABBCC"),
                "CV_SCHEDULE", f"malformed block order {order!r}")
    require(tuple(protocol.get("lane_ids", ())) == LANE_IDS, "CV_PROTOCOL",
            "lane set drifted")
    require(tuple(protocol.get("primary_lanes", ())) == PRIMARY_LANES, "CV_PROTOCOL",
            "primary lanes drifted")
    for flag in ("classification_uses_unbatched_only", "batched_is_observational_only",
                 "diagnostic_only"):
        require(protocol.get(flag) is True, "CV_PROTOCOL", f"{flag} must be true")
    require(protocol.get("final_pr15ic_acceptance_changed") is False, "CV_PROTOCOL",
            "the frozen acceptance contract must remain unchanged")
    digest = sha256_file(os.path.join(root, PROTOCOL_REL))
    require(digest == manifest.get("protocol_sha256"), "CV_PROTOCOL",
            "protocol hash mismatch")
    return digest


def canonical_campaign(root, campaign):
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c",
                                            "causal-campaigns-v1"))
    candidate = os.path.realpath(campaign)
    require(os.path.commonpath([candidate, allowed]) == allowed and candidate != allowed,
            "CV_PATH", "campaign must be under target/pr15i-c/causal-campaigns-v1")
    return candidate


def _no_symlinks(campaign, relative):
    current = campaign
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        info = os.lstat(current)
        require(not stat.S_ISLNK(info.st_mode), "CV_PATH",
                f"symlinked path component {current}")


def verify_inventory_and_seal(campaign):
    raw = os.path.join(campaign, "raw")
    require(os.path.isdir(raw), "CV_INVENTORY", "missing raw directory")
    _no_symlinks(campaign, "raw")
    # The seal is checked first so a missing/tampered seal reports CV_SEAL rather
    # than a generic inventory mismatch.
    seal_path = os.path.join(raw, "seal.json")
    require(os.path.isfile(seal_path), "CV_SEAL", "missing seal")
    found = []
    for root_dir, directories, files in os.walk(raw):
        for directory in directories:
            full = os.path.join(root_dir, directory)
            require(not os.path.islink(full), "CV_PATH", f"symlinked directory {full}")
        for name in files:
            full = os.path.join(root_dir, name)
            require(not os.path.islink(full), "CV_PATH", f"symlinked file {full}")
            found.append(os.path.relpath(full, raw).replace(os.sep, "/"))
    expected = set(REQUIRED_RAW) | {"seal.json"}
    extra = sorted(set(found) - expected)
    missing = sorted(expected - set(found))
    require(not extra, "CV_INVENTORY", f"unexpected raw files: {extra}")
    require(not missing, "CV_INVENTORY", f"missing raw files: {missing}")
    seal = read_json(seal_path)
    require(seal.get("schema") == SEAL_SCHEMA, "CV_SEAL", "bad seal schema")
    files = seal.get("files")
    require(isinstance(files, dict), "CV_SEAL", "seal files must be a mapping")
    require(set(files) == set(REQUIRED_RAW), "CV_SEAL", "seal file set mismatch")
    before = {}
    for relative in REQUIRED_RAW:
        digest = sha256_file(os.path.join(raw, relative))
        require(digest == files[relative], "CV_SEAL", f"seal mismatch for {relative}")
        before[relative] = digest
    return before


def independent_layout(index_dir):
    """Independent on-disk STORED/segment/sidecar scanner (no controller code)."""
    stored = 0
    segments = 0
    stored_version = None
    codec = None
    features = None
    for root_dir, _dirs, files in os.walk(index_dir):
        for name in sorted(files):
            path = os.path.join(root_dir, name)
            relative = os.path.relpath(path, index_dir).replace(os.sep, "/")
            if not relative.startswith("index/segments/"):
                continue
            with open(path, "rb") as handle:
                data = handle.read()
            segments += len(data)
            require(data[:8] == b"TRWSEG01", "CV_FORMAT", f"not a segment: {path}")
            trailer = len(data) - 64
            footer_offset = int.from_bytes(data[trailer + 8:trailer + 16], "little")
            footer_len = int.from_bytes(data[trailer + 16:trailer + 24], "little")
            section_count = int.from_bytes(data[trailer + 24:trailer + 28], "little")
            cursor = footer_offset
            require(int.from_bytes(data[cursor:cursor + 2], "little") == 1,
                    "CV_FORMAT", "bad footer")
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
            require(cursor == footer_offset + footer_len, "CV_FORMAT",
                    "footer length mismatch")
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(index_dir) for f in fs)
    return {"stored_bytes": stored, "segment_bytes": segments,
            "committed_index_bytes": total, "stored_version": stored_version,
            "codec_id": codec, "required_features": sorted(features or [])}


def independent_segment_digest(index_dir):
    digest = hashlib.sha256()
    segments = os.path.join(index_dir, "index", "segments")
    require(os.path.isdir(segments), "CV_FORMAT", f"missing segments dir {segments}")
    for name in sorted(os.listdir(segments)):
        path = os.path.join(segments, name)
        if not os.path.isfile(path):
            continue
        digest.update(name.encode() + b"\0")
        digest.update(str(os.path.getsize(path)).encode() + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def verify_source_and_binary(root, campaign, manifest):
    report = source_proof.verify_causal_source(
        root, manifest["candidate_sha"], manifest["baseline_sha"])
    executed = manifest.get("adapter_sha256")
    paths = manifest.get("adapter_path")
    require(isinstance(executed, dict) and set(executed) == {"A", "BC"}, "CV_BINARY",
            "manifest adapter hashes must name A and BC")
    require(isinstance(paths, dict) and set(paths) == {"A", "BC"}, "CV_BINARY",
            "manifest adapter paths must name A and BC")
    for arm in ("A", "BC"):
        path = paths[arm]
        require(os.path.isabs(path) and os.path.isfile(path), "CV_BINARY",
                f"arm {arm} binary is missing")
        require(not os.path.islink(path), "CV_BINARY", f"arm {arm} binary is a symlink")
        require(sha256_file(path) == executed[arm], "CV_BINARY",
                f"arm {arm} binary hash mismatch")
    require(executed["A"] != executed["BC"], "CV_BINARY",
            "A and BC binaries must differ")
    toolchain = read_json(os.path.join(campaign, "raw", "toolchain.json"))
    require(toolchain.get("feature") == SOURCE_FEATURE, "CV_MODE",
            "toolchain does not record the experimental feature")
    require(toolchain.get("adapter_sha256") == executed, "CV_BINARY",
            "toolchain adapter hashes disagree with the manifest")
    proof = read_json(os.path.join(campaign, "raw", "source_proof.json"))
    require(proof.get("generic_body_sha256") == report["generic_body_sha256"],
            "CV_SOURCE", "recorded generic body hash mismatch")
    require(proof.get("feature") == SOURCE_FEATURE, "CV_SOURCE", "feature mismatch")
    mode_proof = read_json(os.path.join(campaign, "raw", "mode_proof.json"))
    probes = {probe["arm"]: probe for probe in mode_proof.get("probes", [])}
    require(set(probes) == {"A", "B", "C", "INVALID", "MISSING"}, "CV_MODE",
            "mode truth-table probes incomplete")
    require(probes["B"]["environment_mode"] == "enabled", "CV_MODE",
            "B probe did not use enabled")
    require(probes["C"]["environment_mode"] == "disabled", "CV_MODE",
            "C probe did not use disabled")
    require(probes["A"]["environment_mode"] is None, "CV_MODE",
            "A probe must not set the mode variable")
    require(probes["INVALID"]["observed_status"] == "error"
            and probes["MISSING"]["observed_status"] == "error", "CV_MODE",
            "invalid/missing mode must be a typed error")
    return {"report": report, "executed": executed, "paths": paths}


def verify_index_layouts(campaign):
    sizes = read_json(os.path.join(campaign, "raw", "sizes.json"))
    layouts = {"A": {}, "BC": {}}
    digests = {"A": {}, "BC": {}}
    rebuilt = 0
    for arm in ("A", "BC"):
        records = sizes.get(arm)
        require(isinstance(records, dict), "CV_FORMAT", f"missing {arm} builds")
        for n in ("10000", "100000"):
            builds = records.get(n)
            require(isinstance(builds, list) and len(builds) == 3, "CV_FORMAT",
                    f"{arm} n{n} must have three rebuilds")
            require([entry.get("attempt") for entry in builds] == [1, 2, 3],
                    "CV_FORMAT", f"{arm} n{n} attempt order drift")
            current = set()
            current_digests = set()
            for entry in builds:
                index_dir = os.path.join(campaign, "setup", "sizes", arm,
                                         f"n{n}-run{entry['attempt']}")
                require(os.path.isdir(index_dir), "CV_FORMAT",
                        f"missing rebuild {index_dir}")
                _no_symlinks(campaign, os.path.relpath(index_dir, campaign))
                layout = independent_layout(index_dir)
                digest = independent_segment_digest(index_dir)
                require(json.dumps(layout, sort_keys=True)
                        == json.dumps(entry["layout"], sort_keys=True), "CV_FORMAT",
                        f"{arm} n{n} run{entry['attempt']} layout drift")
                require(digest == entry.get("segment_digest"), "CV_FORMAT",
                        f"{arm} n{n} run{entry['attempt']} digest drift")
                current.add(json.dumps(layout, sort_keys=True))
                current_digests.add(digest)
                rebuilt += 1
            require(len(current) == 1 and len(current_digests) == 1, "CV_FORMAT",
                    f"{arm} n{n} non-deterministic rebuilds")
            layouts[arm][n] = json.loads(next(iter(current)))
            digests[arm][n] = next(iter(current_digests))
    require(rebuilt == 12, "CV_FORMAT", f"expected 12 rebuilds, found {rebuilt}")
    for n in ("10000", "100000"):
        require(json.dumps(layouts["A"][n], sort_keys=True)
                == json.dumps(layouts["BC"][n], sort_keys=True), "CV_FORMAT",
                f"n{n} arm layouts differ")
        require(digests["A"][n] == digests["BC"][n], "CV_FORMAT",
                f"n{n} segment digests differ")
        for arm in ("A", "BC"):
            require(layouts[arm][n]["stored_version"] == 2, "CV_FORMAT",
                    f"{arm} n{n} not STORED v2")
            require(layouts[arm][n]["codec_id"] == 1, "CV_FORMAT",
                    f"{arm} n{n} not LZ4")
            require([13, 1] in layouts[arm][n]["required_features"], "CV_FORMAT",
                    f"{arm} n{n} lacks required feature 0x000D v1")
    require(layouts["A"]["100000"]["committed_index_bytes"] == A_100K_TOTAL,
            "CV_FORMAT", "100K committed-byte sentinel mismatch")
    require(layouts["A"]["100000"]["stored_bytes"] == A_100K_STORED, "CV_FORMAT",
            "100K STORED-byte sentinel mismatch")
    return layouts, digests


def verify_slots(campaign, regime, manifest):
    paths = manifest.get("adapter_path", {})
    hashes = manifest.get("adapter_sha256", {})
    require(isinstance(paths, dict) and set(paths) == {"A", "BC"}, "CV_BINARY",
            "manifest adapter paths must name A and BC")
    require(paths["A"] != paths["BC"], "CV_BINARY",
            "A and BC must be different executables")
    slots = [read_json(os.path.join(campaign, "raw", "slots",
                                    f"slot-{index:02d}.json"))
             for index in range(1, SLOTS + 1)]
    batched = regime == "batched"
    samples_expected = BATCHED_SAMPLES if batched else UNBATCHED_SAMPLES
    unit = "batch" if batched else "single_query"
    timing_field = "batch_ns" if batched else "engine_ns"
    require(len(slots) == SLOTS, "CV_SCHEDULE", f"expected {SLOTS} slots")
    seen = set()
    total_samples = 0
    total_warmups = 0
    for index, record in enumerate(slots, start=1):
        require(record.get("slot_index") == index, "CV_SCHEDULE", f"slot {index} order")
        require(index not in seen, "CV_SCHEDULE", f"duplicate slot {index}")
        seen.add(index)
        block = record.get("block")
        position = record.get("position")
        arm = record.get("arm")
        require(block in (1, 2, 3, 4), "CV_SCHEDULE", f"slot {index} bad block")
        require(position in (1, 2, 3, 4, 5, 6), "CV_SCHEDULE", f"slot {index} bad position")
        require(arm in ("A", "B", "C"), "CV_SCHEDULE", f"slot {index} bad arm")
        require(arm == ARM_ORDER_BY_BLOCK[block - 1][position - 1], "CV_SCHEDULE",
                f"slot {index} violates the frozen schedule")
        require(record.get("sample_unit") == unit, "CV_UNIT",
                f"slot {index} sample unit is not {unit}")
        require(record.get("mode") == {"A": None, "B": "enabled",
                                       "C": "disabled"}[arm], "CV_MODE",
                f"slot {index} mode mismatch")
        lanes = record.get("lanes")
        require(isinstance(lanes, list) and [lane["id"] for lane in lanes] == list(LANE_IDS),
                "CV_SCHEDULE", f"slot {index} lane set drift")
        expected_binary = paths["A"] if arm == "A" else paths["BC"]
        expected_hash = hashes["A"] if arm == "A" else hashes["BC"]
        require(record.get("executed_binary_path") == expected_binary, "CV_BINARY",
                f"slot {index} executed a different {arm} executable path")
        require(record.get("binary_sha256") == expected_hash, "CV_BINARY",
                f"slot {index} {arm} binary hash drift")
        for lane in lanes:
            require(lane.get("binary_path") == expected_binary, "CV_BINARY",
                    f"slot {index} {lane['id']} lane process path drift")
            require(lane.get("binary_sha256") == expected_hash, "CV_BINARY",
                    f"slot {index} {lane['id']} lane process hash drift")
            require(lane.get("timing_field") == timing_field, "CV_UNIT",
                    f"slot {index} {lane['id']} timing field drift")
            require(lane.get("sample_unit") == unit, "CV_UNIT",
                    f"slot {index} {lane['id']} lane sample unit drift")
            warmups = lane.get("warmup_ids")
            require(isinstance(warmups, list) and len(warmups) == WARMUPS, "CV_SAMPLE",
                    f"slot {index} {lane['id']} warmup count drift")
            values = lane.get("samples_ns")
            require(isinstance(values, list) and len(values) == samples_expected,
                    "CV_SAMPLE", f"slot {index} {lane['id']} sample count "
                    f"{len(values) if values else None}")
            median = nearest_rank_median(values)
            require(lane.get("summary_ns", {}).get("median") == median, "CV_SAMPLE",
                    f"slot {index} {lane['id']} reported median is not nearest-rank")
            if batched:
                require(lane.get("repeat_count") == repeat_count_for(lane["id"]),
                        "CV_UNIT", f"slot {index} {lane['id']} repeat count drift")
            total_samples += len(values)
            total_warmups += len(warmups)
        for phase in ("contention_before", "contention_after"):
            require(record.get(phase, {}).get("state") == "clear", "CV_CONTENTION",
                    f"slot {index} {phase} not clear")
    require(total_samples == SLOTS * len(LANE_IDS) * samples_expected, "CV_SAMPLE",
            f"total sample count {total_samples}")
    require(total_warmups == SLOTS * len(LANE_IDS) * WARMUPS, "CV_SAMPLE",
            f"total warmup count {total_warmups}")
    for block in range(1, BLOCKS + 1):
        arms = [record["arm"] for record in slots if record["block"] == block]
        require(arms.count("A") == 2 and arms.count("B") == 2 and arms.count("C") == 2,
                "CV_SCHEDULE", f"block {block} is not AABBCC-balanced")
    bc_paths = {record["executed_binary_path"] for record in slots
                if record["arm"] in ("B", "C")}
    require(len(bc_paths) == 1, "CV_BINARY",
            "B and C must execute one identical executable path")
    return slots


def verify_oracle_and_scores(campaign, root, slots):
    corpus_dir = os.path.join(campaign, "setup", "corpus")
    require(os.path.isdir(corpus_dir), "CV_ORACLE", "missing corpus directory")
    _manifest, rows = base.oracle.load_and_verify(corpus_dir)
    corpus_record = read_json(os.path.join(campaign, "raw", "corpus.json"))
    require(corpus_record.get("manifest_sha256") == CORPUS_SHA, "CV_ORACLE",
            "corpus manifest digest drifted")
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    require([lane["id"] for lane in lanes] == list(LANE_IDS), "CV_ORACLE",
            "lane order drift")
    expected = {lane["id"]: base.oracle.expected(
        rows=rows[lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
        for lane in lanes}
    for record in slots:
        for lane in record["lanes"]:
            lane_id = lane["id"]
            require(lane.get("oracle_ok") is True, "CV_ORACLE",
                    f"slot {record['slot_index']} {lane_id} oracle not ok")
            require(lane.get("total_hits") == expected[lane_id]["total_hits"],
                    "CV_ORACLE", f"slot {record['slot_index']} {lane_id} total_hits")
            require(lane.get("doc_ids") == expected[lane_id]["doc_ids"], "CV_ORACLE",
                    f"slot {record['slot_index']} {lane_id} key order")
    parity = read_json(os.path.join(campaign, "raw", "score_parity.json"))
    recorded = parity.get("lanes", {})
    require(set(recorded) == set(LANE_IDS), "CV_SCORE", "score parity lane set drift")
    for lane_id, entry in recorded.items():
        require(entry.get("identical") is True, "CV_SCORE", f"{lane_id} not identical")
        require(entry.get("total_hits") == expected[lane_id]["total_hits"], "CV_SCORE",
                f"{lane_id} recorded total_hits drift")
    return expected


def independently_recompute_ratios(slots, lane_ids):
    ratios = {}
    for lane_id in lane_ids:
        per_arm = {}
        for arm in ("A", "B", "C"):
            for block in range(1, BLOCKS + 1):
                medians = []
                for record in slots:
                    if record["block"] != block or record["arm"] != arm:
                        continue
                    for lane in record["lanes"]:
                        if lane["id"] == lane_id:
                            medians.append(nearest_rank_median(lane["samples_ns"]))
                require(len(medians) == 2, "CV_RATIO",
                        f"{lane_id} block {block} arm {arm} slot drift")
                per_arm[(arm, block)] = sum(medians) / 2
        entry = {"B/A": [], "C/A": [], "B/C": [], "A/A_drift": []}
        for block in range(1, BLOCKS + 1):
            a = per_arm[("A", block)]
            b = per_arm[("B", block)]
            c = per_arm[("C", block)]
            require(a > 0 and c > 0, "CV_RATIO", f"{lane_id} block {block} zero denominator")
            entry["B/A"].append(b / a)
            entry["C/A"].append(c / a)
            entry["B/C"].append(b / c)
        entry["campaign_medians"] = {}
        for key in ("B/A", "C/A", "B/C"):
            ordered = sorted(entry[key])
            entry["campaign_medians"][key] = (ordered[1] + ordered[2]) / 2
        drift = []
        for block in range(1, BLOCKS + 1):
            medians = []
            for record in slots:
                if record["block"] != block or record["arm"] != "A":
                    continue
                for lane in record["lanes"]:
                    if lane["id"] == lane_id:
                        medians.append(nearest_rank_median(lane["samples_ns"]))
            require(len(medians) == 2, "CV_RATIO",
                    f"{lane_id} block {block} A drift slot count")
            require(medians[0] > 0, "CV_RATIO", f"{lane_id} block {block} zero A median")
            drift.append(medians[1] / medians[0])
        ordered = sorted(drift)
        entry["A/A_drift"] = drift
        entry["A/A_drift_median"] = (ordered[1] + ordered[2]) / 2
        ratios[lane_id] = entry
    return ratios


def compare_with_controller(ratios, measurements):
    reported = measurements.get("ratios", {})
    require(set(reported) == set(LANE_IDS), "CV_RATIO", "controller lane set drift")
    for lane_id in LANE_IDS:
        for key in ("B/A", "C/A", "B/C"):
            for expected, actual in zip(ratios[lane_id][key],
                                        reported[lane_id].get(key, [])):
                require(abs(expected - actual) <= TOLERANCE, "CV_RATIO",
                        f"{lane_id} {key} block ratio drift")
            require(abs(ratios[lane_id]["campaign_medians"][key]
                        - reported[lane_id].get("campaign_medians", {}).get(key, -1))
                    <= TOLERANCE, "CV_RATIO", f"{lane_id} {key} median drift")
    drift = measurements.get("a_drift", {})
    for lane_id in LANE_IDS:
        require(abs(drift.get(lane_id, {}).get("campaign_median", -1)
                    - ratios[lane_id]["A/A_drift_median"]) <= TOLERANCE, "CV_RATIO",
                f"{lane_id} A/A drift median drift")


def independently_classify(ratios_by_campaign, regime):
    """Apply the frozen §9 decision table (unbatched only)."""
    if regime != "unbatched":
        return {"classification": "BATCH_OBSERVATION_ONLY",
                "reason": "batched measurements are observational by protocol"}
    per_lane = {}
    for lane_id in LOW_MATCH_LANES:
        per_lane[lane_id] = []
        for campaign in sorted(ratios_by_campaign):
            entry = ratios_by_campaign[campaign][lane_id]
            per_lane[lane_id].append(entry)
    def aggregate(values):
        ordered = sorted(values)
        return (ordered[0] + ordered[1]) / 2 if len(values) == 2 else ordered[len(ordered) // 2]

    lane_classes = {}
    detail = {}
    for lane_id, entries in per_lane.items():
        ba_med = aggregate([e["campaign_medians"]["B/A"] for e in entries])
        ca_med = aggregate([e["campaign_medians"]["C/A"] for e in entries])
        bc_med = aggregate([e["campaign_medians"]["B/C"] for e in entries])
        ba_blocks = [value for e in entries for value in e["B/A"]]
        ca_blocks = [value for e in entries for value in e["C/A"]]
        bc_blocks = [value for e in entries for value in e["B/C"]]
        drift_med = aggregate([e["A/A_drift_median"] for e in entries])
        detail[lane_id] = {
            "B/A_median": ba_med, "C/A_median": ca_med, "B/C_median": bc_med,
            "B/A_blocks": ba_blocks, "C/A_blocks": ca_blocks, "B/C_blocks": bc_blocks,
            "A/A_drift_median": drift_med,
        }
        if not (DRIFT_MIN <= drift_med <= DRIFT_MAX):
            lane_classes[lane_id] = "CAUSAL_UNBATCHED_UNSTABLE"
        elif not (ba_med >= LOW_RATIO_FLOOR
                  and all(value >= REPRO_BLOCK_FLOOR for value in ba_blocks)):
            lane_classes[lane_id] = "CAUSAL_HISTORICAL_PATTERN_NOT_REPRODUCED"
        elif (ca_med <= NEUTRAL_CEILING
              and all(value <= NEUTRAL_BLOCK_CEILING for value in ca_blocks)
              and bc_med >= LOW_RATIO_FLOOR
              and all(value >= REPRO_BLOCK_FLOOR for value in bc_blocks)):
            lane_classes[lane_id] = "CAUSAL_OPERATOR_DOMINANT"
        elif (ca_med >= LOW_RATIO_FLOOR
              and all(value >= REPRO_BLOCK_FLOOR for value in ca_blocks)
              and bc_med <= NEUTRAL_CEILING
              and all(value <= NEUTRAL_BLOCK_CEILING for value in bc_blocks)):
            lane_classes[lane_id] = "CAUSAL_NON_OPERATOR_DOMINANT"
        elif (ca_med >= MIXED_RATIO_FLOOR and bc_med >= MIXED_RATIO_FLOOR
              and all(value >= MIXED_BLOCK_FLOOR for value in ca_blocks + bc_blocks)):
            lane_classes[lane_id] = "CAUSAL_MIXED_CONTRIBUTIONS"
        else:
            lane_classes[lane_id] = "CAUSAL_INCONCLUSIVE"
    unique = set(lane_classes.values())
    if len(unique) == 1:
        classification = unique.pop()
    else:
        classification = "CAUSAL_INCONCLUSIVE"
        detail["lane_disagreement"] = lane_classes
    return {"classification": classification, "lanes": lane_classes, "detail": detail}


def write_receipt(root, campaign, payload):
    reviews = os.path.join(root, "target", "pr15i-c", "reviews")
    os.makedirs(reviews, exist_ok=True)
    path = os.path.join(reviews, f"{os.path.basename(campaign)}-verification.json")
    if os.path.exists(path):
        raise VerificationFailed("CV_RECEIPT", f"refusing to replace {path}")
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
    require(manifest.get("schema") == SCHEMA, "CV_MANIFEST", "bad manifest schema")
    require(measurements.get("schema") == SCHEMA, "CV_MANIFEST", "bad measurement schema")
    regime = manifest.get("regime")
    require(regime in ("unbatched", "batched"), "CV_MANIFEST", "bad regime")
    require(regime == measurements.get("regime"), "CV_MANIFEST", "regime mismatch")
    require(manifest.get("campaign") == os.path.basename(campaign), "CV_MANIFEST",
            "campaign id mismatch")
    require(manifest.get("baseline_sha") == BASELINE_SHA, "CV_SOURCE",
            "baseline is not merged PR 15I-B")
    protocol = verify_protocol(root, manifest)
    source = verify_source_and_binary(root, campaign, manifest)
    layouts, digests = verify_index_layouts(campaign)
    slots = verify_slots(campaign, regime, manifest)
    expected = verify_oracle_and_scores(campaign, root, slots)
    ratios = independently_recompute_ratios(slots, LANE_IDS)
    compare_with_controller(ratios, measurements)
    classification = independently_classify({os.path.basename(campaign): ratios}, regime)
    after = {relative: sha256_file(os.path.join(campaign, "raw", relative))
             for relative in REQUIRED_RAW}
    require(before == after, "CV_TAMPER", "raw evidence changed during verification")
    environment = read_json(os.path.join(campaign, "raw", "environment.json"))
    payload = {
        "schema": RECEIPT_SCHEMA,
        "campaign": os.path.basename(campaign),
        "regime": regime,
        "protocol_sha256": protocol,
        "baseline_sha": manifest["baseline_sha"],
        "candidate_sha": manifest["candidate_sha"],
        "source_proof": source["report"],
        "adapter_sha256": source["executed"],
        "adapter_path": source["paths"],
        "cpu_affinity": manifest.get("cpu_affinity"),
        "host_fingerprint": environment.get("host_fingerprint"),
        "layouts": layouts,
        "segment_digests": digests,
        "lane_ratios": ratios,
        "classification": classification,
        "diagnostic_only": True,
        "final_feature_acceptance": False,
        "raw_inventory": len(before),
        "seal_sha256": hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()).hexdigest(),
        "verify_only": verify_only,
    }
    if write:
        payload["receipt_path"] = write_receipt(root, campaign, payload)
    return payload


def aggregate(root, series_root, verify_only=False, write=True):
    series_root = os.path.realpath(series_root)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c",
                                            "causal-campaigns-v1"))
    require(series_root == allowed, "CV_SERIES", "series root must be causal-campaigns-v1")
    results = {}
    for campaign, regime in SERIES:
        path = os.path.join(series_root, campaign)
        require(os.path.isdir(path), "CV_SERIES", f"missing campaign {campaign}")
        payload = verify(root, path, verify_only, write=False)
        require(payload["regime"] == regime, "CV_SERIES",
                f"{campaign} has regime {payload['regime']}")
        results[campaign] = payload
    fingerprints = {results[c]["host_fingerprint"] for c in results}
    require(len(fingerprints) == 1, "CV_SERIES", "host fingerprints differ across runs")
    af = {json.dumps(results[c]["cpu_affinity"], sort_keys=True) for c in results}
    require(len(af) == 1, "CV_SERIES", "CPU affinity mode differs across runs")
    unbatched = {c: results[c]["lane_ratios"] for c in results
                 if results[c]["regime"] == "unbatched"}
    batched = {c: results[c]["lane_ratios"] for c in results
               if results[c]["regime"] == "batched"}
    classification = independently_classify(unbatched, "unbatched")
    batched_view = independently_classify(batched, "batched")
    if classification["classification"].startswith("CAUSAL_"):
        status = ("15IC_CAUSAL_DIAGNOSTIC_COMPLETE"
                  if classification["classification"] in (
                      "CAUSAL_OPERATOR_DOMINANT", "CAUSAL_NON_OPERATOR_DOMINANT",
                      "CAUSAL_MIXED_CONTRIBUTIONS")
                  else "15IC_CAUSAL_DIAGNOSTIC_INCONCLUSIVE")
    else:  # pragma: no cover - defensive
        status = "15IC_CAUSAL_DIAGNOSTIC_INCONCLUSIVE"
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "protocol_sha256": results[SERIES_ORDER[0]]["protocol_sha256"],
        "campaigns": {campaign: {"regime": results[campaign]["regime"],
                                "seal_sha256": results[campaign]["seal_sha256"],
                                "classification": results[campaign]["classification"]}
                      for campaign in results},
        "series_order": SERIES_ORDER,
        "unbatched_classification": classification,
        "batched_classification": batched_view,
        "status": status,
        "diagnostic_only": True,
        "final_feature_acceptance": False,
        "frozen_acceptance_changed": False,
        "verify_only": verify_only,
    }
    if write:
        name = "causal-series-aggregate.json"
        path = os.path.join(root, "target", "pr15i-c", "reviews", name)
        suffix = 2
        while os.path.exists(path):
            name = f"causal-series-aggregate-{suffix:02d}.json"
            path = os.path.join(root, "target", "pr15i-c", "reviews", name)
            suffix += 1
        payload["receipt_path"] = write_receipt(root, name, payload)
    return payload


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C causal verifier")
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
                root, "target", "pr15i-c", "causal-campaigns-v1")
            payload = aggregate(root, series_root, args.verify_only,
                                write=not args.no_receipt)
            print(f"PR15I_C causal series: {payload['status']}")
            print(f"  unbatched: {payload['unbatched_classification']['classification']}")
            print(f"  batched (observational): "
                  f"{payload['batched_classification']['classification']}")
            for lane_id, value in payload["unbatched_classification"]["lanes"].items():
                print(f"  {lane_id}: {value}")
            return 0
        payload = verify(root, args.campaign, args.verify_only,
                         write=not args.no_receipt)
    except (VerificationFailed, source_proof.SourceProofError) as error:
        rule = getattr(error, "rule", "CV_SOURCE")
        detail = getattr(error, "detail", str(error))
        print(f"CV_BLOCKED: {rule}: {detail}", file=sys.stderr)
        return 3
    print(f"PR15I_C causal verify campaign={payload['campaign']} "
          f"regime={payload['regime']}")
    for lane_id in LANE_IDS:
        entry = payload["lane_ratios"][lane_id]
        print(f"  {lane_id}: B/A={entry['campaign_medians']['B/A']:.4f} "
              f"C/A={entry['campaign_medians']['C/A']:.4f} "
              f"B/C={entry['campaign_medians']['B/C']:.4f} "
              f"drift={entry['A/A_drift_median']:.4f}")
    print(f"  classification: {payload['classification']['classification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

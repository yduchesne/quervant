#!/usr/bin/env python3
"""PR 15I-C follow-up — independent verifier for the A/A and A/G noise study.

Two modes:

* single campaign: ``--campaign <dir> [--verify-only]`` re-derives every diagnostic
  number from sealed raw evidence and writes a read-only receipt.
* series aggregate: ``--aggregate --series-root <dir>`` verifies exactly the eight
  prescribed campaigns from raw, derives the predeclared A/A and A/G criteria and
  writes one aggregate receipt referencing all component seals.

It never imports the controller's derivation and never trusts a reported verdict.
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


run = _load("pr15i_c_run_noise_verify", os.path.join(HERE, "run.py"))
layout = _load("pr15i_c_layout_noise_verify", os.path.join(HERE, "layout_diag.py"))
source_proof = _load("pr15i_c_source_proof_noise_verify",
                     os.path.join(HERE, "source_proof.py"))
base = run.base

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "noise_protocol_v2.json")
PROTOCOL_SCHEMA = "pr15i-c-noise-v2"
SCHEMA = "pr15i-c-noise-campaign-v2"
SEAL_SCHEMA = "pr15i-c-noise-seal-v2"
RECEIPT_SCHEMA = "pr15i-c-noise-verification-v1"
AGGREGATE_SCHEMA = "pr15i-c-noise-series-v1"
BASELINE_SHA = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
GENERIC_CONTROL_SHA = "50b56e9fe7b22bb266ca7b0d9e209500dfc785ff"
LANE_IDS = layout.LANE_IDS
BLOCK_ORDERS = layout.BLOCK_ORDERS
BLOCKS = layout.BLOCKS
WARMUPS = layout.WARMUPS
MEASURED = layout.MEASURED
SLOTS = layout.SLOTS
GENERIC_METHOD = layout.GENERIC_METHOD
UNIFIED_REL = layout.UNIFIED_REL
EXPECTED_GENERIC_BODY_SHA = "00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994"
AA_CAMPAIGN_MEDIAN_MIN = 0.90
AA_CAMPAIGN_MEDIAN_MAX = 1.10
AA_AGGREGATE_MIN = 0.95
AA_AGGREGATE_MAX = 1.05
AG_AGGREGATE_MAX = 1.05
AG_CAMPAIGN_MEDIAN_MAX = 1.10
AG_RUNS_AT_OR_BELOW_MIN = 3
PER_BLOCK_OBSERVATION = 1.15
RATIO_TOLERANCE = 1e-12
A_100K_TOTAL = 15_747_551
A_100K_STORED = 1_661_455
FROZEN_CORPUS_SHA = "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151"
SERIES = (
    ("aa-01", "aa"), ("ag-01", "ag"),
    ("aa-02", "aa"), ("ag-02", "ag"),
    ("aa-03", "aa"), ("ag-03", "ag"),
    ("aa-04", "aa"), ("ag-04", "ag"),
)
REQUIRED_RAW = (
    "authorization.json",
    "corpus.json",
    "environment.json",
    "manifest.json",
    "measurements.json",
    "sizes.json",
    "toolchain.json",
    *(f"slots/slot-{index:02d}.json" for index in range(1, SLOTS + 1)),
)

VerificationFailed = run.RunBlocked


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


def protocol_sha(root):
    return sha256_file(os.path.join(root, PROTOCOL_REL))


def verify_protocol(root, manifest):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    require(protocol.get("schema") == PROTOCOL_SCHEMA, "NV_PROTOCOL", "bad protocol schema")
    require(tuple(protocol.get("lane_ids", [])) == LANE_IDS, "NV_PROTOCOL", "lane set drifted")
    require(tuple(protocol.get("block_orders", ()))
            == tuple("".join(order) for order in BLOCK_ORDERS), "NV_PROTOCOL",
            "block order drifted")
    require(protocol.get("warmups") == WARMUPS, "NV_PROTOCOL", "warmups drifted")
    require(protocol.get("measured_per_lane_slot") == MEASURED, "NV_PROTOCOL",
            "measured count drifted")
    require(protocol.get("slots_per_campaign") == SLOTS, "NV_PROTOCOL", "slot count drifted")
    require(protocol.get("AA_aggregate_median_min") == AA_AGGREGATE_MIN, "NV_PROTOCOL", "AA min")
    require(protocol.get("AA_aggregate_median_max") == AA_AGGREGATE_MAX, "NV_PROTOCOL", "AA max")
    require(protocol.get("AG_aggregate_median_max") == AG_AGGREGATE_MAX, "NV_PROTOCOL", "AG max")
    require(protocol.get("AG_runs_per_lane_at_or_below_1_05_min")
            == AG_RUNS_AT_OR_BELOW_MIN, "NV_PROTOCOL", "AG run floor")
    digest = protocol_sha(root)
    require(digest == manifest.get("protocol_sha256"), "NV_PROTOCOL", "protocol hash mismatch")
    return digest


def canonical_campaign(root, campaign):
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "noise-diagnostics-v2"))
    candidate = os.path.realpath(campaign)
    require(os.path.commonpath([candidate, allowed]) == allowed and candidate != allowed,
            "NV_PATH", "campaign must be under target/pr15i-c/noise-diagnostics")
    return candidate


def check_no_symlinks(campaign, relative):
    current = campaign
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        info = os.lstat(current)
        require(not stat.S_ISLNK(info.st_mode), "NV_SYMLINK",
                f"symlinked path component {current}")


def inventory(campaign):
    raw = os.path.join(campaign, "raw")
    require(os.path.isdir(raw), "NV_INVENTORY", "missing raw directory")
    check_no_symlinks(campaign, "raw")
    found = []
    for root_dir, directories, files in os.walk(raw):
        for directory in directories:
            full = os.path.join(root_dir, directory)
            require(not os.path.islink(full), "NV_SYMLINK", f"symlinked directory {full}")
        for name in files:
            full = os.path.join(root_dir, name)
            require(not os.path.islink(full), "NV_SYMLINK", f"symlinked file {full}")
            found.append(os.path.relpath(full, raw).replace(os.sep, "/"))
    expected = set(REQUIRED_RAW) | {"seal.json"}
    extra = sorted(set(found) - expected)
    missing = sorted(expected - set(found))
    require(not extra, "NV_INVENTORY", f"unexpected raw files: {extra}")
    require(not missing, "NV_INVENTORY", f"missing raw files: {missing}")
    return sorted(found)


def verify_seal(campaign):
    seal_path = os.path.join(campaign, "raw", "seal.json")
    require(os.path.isfile(seal_path), "NV_SEAL", "missing raw/seal.json")
    seal = read_json(seal_path)
    require(seal.get("schema") == SEAL_SCHEMA, "NV_SEAL", "bad seal schema")
    files = seal.get("files")
    require(isinstance(files, dict), "NV_SEAL", "seal files must be a mapping")
    require(set(files) == set(REQUIRED_RAW), "NV_SEAL", "seal file set mismatch")
    before = {}
    for relative in REQUIRED_RAW:
        path = os.path.join(campaign, "raw", relative)
        digest = sha256_file(path)
        require(digest == files[relative], "NV_SEAL", f"seal hash mismatch for {relative}")
        before[relative] = digest
    return before


def _git(tree, *args):
    result = subprocess.run(["git", "-C", tree, *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def verify_source(root, manifest, mode):
    a_sha = manifest.get("A_sha")
    b_sha = manifest.get("B_sha")
    require(isinstance(a_sha, str) and len(a_sha) == 40, "NV_SOURCE", "bad A sha")
    require(isinstance(b_sha, str) and len(b_sha) == 40, "NV_SOURCE", "bad B sha")
    require(a_sha == BASELINE_SHA, "NV_SOURCE", "baseline is not the merged PR 15I-B commit")
    for sha in (a_sha, b_sha):
        code, out, _err = _git(root, "cat-file", "-t", sha)
        require(code == 0 and out == "commit", "NV_SOURCE", f"{sha} is not a real commit")
    if mode == "aa":
        require(b_sha == a_sha, "NV_SOURCE", "A/A arms must reference the same source")
    else:
        require(b_sha == GENERIC_CONTROL_SHA, "NV_SOURCE", "A/G control is not the pinned G")
        code, _out, _err = _git(root, "merge-base", "--is-ancestor", a_sha, b_sha)
        require(code == 0, "NV_SOURCE", "G does not descend from A")
        code, out, _err = _git(root, "diff", "--name-only", f"{a_sha}..{b_sha}")
        require(code == 0, "NV_SOURCE", "git diff failed")
        changed = [
            path for path in out.splitlines()
            if path.startswith("crates/")
            and not path.startswith("crates/quervant-core/tests/")
            and not path.startswith("crates/quervant-core/benches/")
        ]
        require(changed == [UNIFIED_REL], "NV_SCOPE",
                f"G production diff is not exactly one file: {changed}")
        control_source = source_proof.read_at_revision(root, b_sha, UNIFIED_REL)
        attributes = source_proof.attribute_block(control_source, GENERIC_METHOD)
        require("#[inline(never)]" in attributes, "NV_BOUNDARY",
                "G lacks #[inline(never)]")
        require(sum(1 for item in attributes if item.startswith("#[inline(")) == 1,
                "NV_BOUNDARY", "G must carry exactly one inline attribute")
        require(source_proof.body_sha(control_source, GENERIC_METHOD)
                == EXPECTED_GENERIC_BODY_SHA, "NV_BODY", "G generic body drifted")
    baseline_source = source_proof.read_at_revision(root, a_sha, UNIFIED_REL)
    body = source_proof.body_sha(baseline_source, GENERIC_METHOD)
    require(body == EXPECTED_GENERIC_BODY_SHA, "NV_BODY",
            "baseline generic body hash drifted")
    require(manifest.get("generic_body_sha256") == body, "NV_BODY",
            "recorded generic body hash mismatch")
    return body


def verify_executables(campaign, manifest, mode):
    executed = manifest.get("executed_binary")
    require(isinstance(executed, dict), "NV_BINARY", "missing executed binary record")
    require(set(executed) == {"A", "B"}, "NV_BINARY", "executed binary arms must be A and B")
    toolchain = read_json(os.path.join(campaign, "raw", "toolchain.json"))
    for arm in ("A", "B"):
        path = executed[arm].get("path")
        digest = executed[arm].get("sha256")
        require(isinstance(path, str) and os.path.isabs(path), "NV_BINARY",
                f"arm {arm} executable path must be absolute")
        require(os.path.isfile(path), "NV_BINARY", f"arm {arm} executable is missing")
        require(not os.path.islink(path), "NV_BINARY", f"arm {arm} executable is a symlink")
        actual = sha256_file(path)
        require(actual == digest, "NV_BINARY", f"arm {arm} executable hash mismatch")
        require(toolchain.get("executed_binary_sha256", {}).get(arm, {}).get("sha256")
                == actual, "NV_BINARY", f"arm {arm} toolchain hash mismatch")
    if mode == "aa":
        require(executed["A"]["path"] == executed["B"]["path"], "NV_AA_BINARY",
                "A/A arms must execute the same file path")
        require(executed["A"]["sha256"] == executed["B"]["sha256"], "NV_AA_BINARY",
                "A/A arms must execute identical bytes")
        require(manifest.get("identical_executable") is True, "NV_AA_BINARY",
                "manifest must declare identical executables for A/A")
    else:
        require(manifest.get("identical_executable") is False, "NV_AG_BINARY",
                "manifest must declare distinct executables for A/G")
        require(executed["A"]["sha256"] != executed["B"]["sha256"], "NV_AG_BINARY",
                "A/G arms must be different executables")
    return executed


def verify_sizes(campaign):
    sizes = read_json(os.path.join(campaign, "raw", "sizes.json"))
    layouts = {"A": {}, "B": {}}
    digests = {"A": {}, "B": {}}
    rebuilt = 0
    for arm in ("A", "B"):
        records = sizes.get(arm)
        require(isinstance(records, dict), "NV_SIZES", f"missing {arm} build records")
        for n in ("10000", "100000"):
            builds = records.get(n)
            require(isinstance(builds, list) and len(builds) == 3, "NV_SIZES",
                    f"{arm} n{n} must have three rebuild records")
            require([entry.get("attempt") for entry in builds] == [1, 2, 3], "NV_SIZES",
                    f"{arm} n{n} attempt order drift")
            seen_layouts = set()
            seen_digests = set()
            for entry in builds:
                index_dir = os.path.join(campaign, "setup", "sizes", arm,
                                         f"n{n}-run{entry['attempt']}")
                require(os.path.isdir(index_dir), "NV_SIZES", f"missing rebuild {index_dir}")
                check_no_symlinks(campaign, os.path.relpath(index_dir, campaign))
                current = run.measure_layout(index_dir)
                digest = run.segment_digest(index_dir)
                require(json.dumps(current, sort_keys=True)
                        == json.dumps(entry["layout"], sort_keys=True), "NV_SIZES",
                        f"{arm} n{n} run{entry['attempt']} layout drift")
                require(digest == entry.get("segment_digest"), "NV_SIZES",
                        f"{arm} n{n} run{entry['attempt']} digest drift")
                seen_layouts.add(json.dumps(current, sort_keys=True))
                seen_digests.add(digest)
                rebuilt += 1
            require(len(seen_layouts) == 1 and len(seen_digests) == 1, "NV_SIZES",
                    f"{arm} n{n} non-deterministic rebuilds")
            layouts[arm][n] = json.loads(next(iter(seen_layouts)))
            digests[arm][n] = next(iter(seen_digests))
    require(rebuilt == 12, "NV_SIZES", f"expected 12 remeasured rebuilds, found {rebuilt}")
    for n in ("10000", "100000"):
        require(json.dumps(layouts["A"][n], sort_keys=True)
                == json.dumps(layouts["B"][n], sort_keys=True), "NV_FORMAT",
                f"n{n} arm layouts differ")
        require(digests["A"][n] == digests["B"][n], "NV_FORMAT",
                f"n{n} arm segment digests differ")
        for arm in ("A", "B"):
            require(layouts[arm][n]["stored_version"] == 2, "NV_FORMAT",
                    f"{arm} n{n} not STORED v2")
            require(layouts[arm][n]["codec_id"] == 1, "NV_FORMAT", f"{arm} n{n} not LZ4")
            require([13, 1] in layouts[arm][n]["required_features"], "NV_FORMAT",
                    f"{arm} n{n} lacks required feature 0x000D v1")
    require(layouts["A"]["100000"]["committed_index_bytes"] == A_100K_TOTAL, "NV_SENTINEL",
            "100K committed-byte sentinel mismatch")
    require(layouts["A"]["100000"]["stored_bytes"] == A_100K_STORED, "NV_SENTINEL",
            "100K STORED-byte sentinel mismatch")
    return layouts, digests


def expected_arm(block, position):
    return BLOCK_ORDERS[block - 1][position - 1]


def validate_slot_matrix(slots, lane_ids=LANE_IDS):
    require(len(slots) == SLOTS, "NV_SLOT", f"expected {SLOTS} slots, found {len(slots)}")
    seen = set()
    measured = 0
    warmed = 0
    for position_expected, record in enumerate(slots, start=1):
        index = record.get("slot_index")
        require(index == position_expected, "NV_SLOT", f"slot {index} out of order")
        require(index not in seen, "NV_SLOT", f"duplicated slot {index}")
        seen.add(index)
        arm = record.get("arm")
        block = record.get("block")
        position = record.get("position")
        require(arm in ("A", "B"), "NV_SLOT", f"slot {index} bad arm")
        require(block in tuple(range(1, BLOCKS + 1)), "NV_SLOT", f"slot {index} bad block")
        require(position in (1, 2, 3, 4), "NV_SLOT", f"slot {index} bad position")
        require(arm == expected_arm(block, position), "NV_SLOT",
                f"slot {index} violates the prescribed ABBA/BAAB schedule")
        trial = record.get("trial")
        require(isinstance(trial, dict), "NV_SLOT", f"slot {index} missing trial")
        lanes_seen = [lane["id"] for lane in trial.get("lanes", [])]
        require(lanes_seen == list(lane_ids), "NV_SLOT", f"slot {index} lane set drift")
        for lane in trial["lanes"]:
            samples = lane.get("samples_ns")
            require(isinstance(samples, list) and len(samples) == MEASURED, "NV_SLOT",
                    f"slot {index} {lane['id']} sample count "
                    f"{len(samples) if samples else None}")
            require(lane.get("warmups") == WARMUPS, "NV_SLOT",
                    f"slot {index} {lane['id']} warmup count drift")
            require(len(lane.get("warmup_ids", [])) == WARMUPS, "NV_SLOT",
                    f"slot {index} {lane['id']} warmup id drift")
            for value in samples:
                require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
                        "NV_SLOT", f"slot {index} {lane['id']} invalid sample")
            require(lane.get("summary_ns") == base.pr15d_run.summarize(samples), "NV_SLOT",
                    f"slot {index} {lane['id']} summary mismatch")
            measured += len(samples)
            warmed += WARMUPS
        require(trial.get("contention_before", {}).get("state") == "clear", "NV_CONTENTION",
                f"slot {index} contention before not clear")
        require(trial.get("contention_after", {}).get("state") == "clear", "NV_CONTENTION",
                f"slot {index} contention after not clear")
    require(measured == 2240, "NV_SLOT", f"expected 2240 measured samples, found {measured}")
    require(warmed == 1120, "NV_SLOT", f"expected 1120 warmups, found {warmed}")
    for block in range(1, BLOCKS + 1):
        arms = [record["arm"] for record in slots if record["block"] == block]
        require(arms.count("A") == 2 and arms.count("B") == 2, "NV_SLOT",
                f"block {block} is not balanced")
    return measured, warmed


def verify_corpus(campaign):
    record = read_json(os.path.join(campaign, "raw", "corpus.json"))
    corpus_dir = os.path.join(campaign, "setup", "corpus")
    require(os.path.isdir(corpus_dir), "NV_CORPUS", "missing corpus directory")
    _manifest, rows = base.oracle.load_and_verify(corpus_dir)
    require(record.get("manifest_sha256") == FROZEN_CORPUS_SHA, "NV_CORPUS",
            "corpus manifest digest differs from the frozen value")
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    require([lane["id"] for lane in lanes] == list(LANE_IDS), "NV_CORPUS", "lane order drift")
    return rows, lanes


def verify_slots(campaign, rows, lanes, executed, mode):
    slots = [read_json(os.path.join(campaign, "raw", "slots", f"slot-{index:02d}.json"))
             for index in range(1, SLOTS + 1)]
    measured, warmed = validate_slot_matrix(slots)
    expected = {
        lane["id"]: base.oracle.expected(
            rows=rows[lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
        for lane in lanes
    }
    for record in slots:
        arm = record["arm"]
        require(record.get("executed_binary_path") == executed[arm]["path"], "NV_BINARY",
                f"slot {record['slot_index']} arm {arm} executable path drift")
        require(record.get("binary_sha256") == executed[arm]["sha256"], "NV_BINARY",
                f"slot {record['slot_index']} arm {arm} executable hash drift")
        for lane in record["trial"]["lanes"]:
            lane_id = lane["id"]
            require(lane.get("oracle_ok") is True, "NV_SLOT",
                    f"slot {record['slot_index']} {lane_id} oracle not ok")
            require(lane.get("total_hits") == expected[lane_id]["total_hits"], "NV_SLOT",
                    f"slot {record['slot_index']} {lane_id} total_hits drift")
            require(lane.get("doc_ids") == expected[lane_id]["doc_ids"], "NV_SLOT",
                    f"slot {record['slot_index']} {lane_id} key order drift")
    if mode == "aa":
        paths = {record["executed_binary_path"] for record in slots}
        digests = {record["binary_sha256"] for record in slots}
        require(len(paths) == 1 and len(digests) == 1, "NV_AA_BINARY",
                "A/A slots did not all execute one identical binary")
    return slots, measured, warmed


def median_abs_difference(a_values, b_values):
    count = min(len(a_values), len(b_values))
    if count == 0:
        return 0
    differences = sorted(abs(a_values[index] - b_values[index]) for index in range(count))
    return differences[count // 2]


def recompute_ratios(slots):
    ratios = {}
    for lane_id in LANE_IDS:
        per_block = []
        a_slot_medians = []
        b_slot_medians = []
        for block in range(1, BLOCKS + 1):
            a_values = []
            b_values = []
            for record in slots:
                if record["block"] != block:
                    continue
                for lane in record["trial"]["lanes"]:
                    if lane["id"] != lane_id:
                        continue
                    if record["arm"] == "A":
                        a_values.append(lane["summary_ns"]["median"])
                        a_slot_medians.append(lane["summary_ns"]["median"])
                    else:
                        b_values.append(lane["summary_ns"]["median"])
                        b_slot_medians.append(lane["summary_ns"]["median"])
            require(len(a_values) == 2 and len(b_values) == 2, "NV_RATIO",
                    f"{lane_id} block {block} sample drift")
            a_mean = sum(a_values) / 2
            b_mean = sum(b_values) / 2
            require(a_mean > 0, "NV_RATIO", f"{lane_id} block {block} zero denominator")
            per_block.append(b_mean / a_mean)
        ordered = sorted(per_block)
        ratios[lane_id] = {
            "block_ratios": per_block,
            "campaign_median": (ordered[3] + ordered[4]) / 2,
            "outliers_above_1_15": sum(1 for v in per_block if v > PER_BLOCK_OBSERVATION),
            "outliers_below_inverse_1_15": sum(
                1 for v in per_block if v < 1.0 / PER_BLOCK_OBSERVATION),
            "absolute_median_difference_ns": median_abs_difference(
                a_slot_medians, b_slot_medians),
        }
    return ratios


def compare_with_controller(ratios, measurements):
    reported = measurements.get("ratios", {})
    for lane_id in LANE_IDS:
        require(lane_id in reported, "NV_RATIO", f"{lane_id} missing from controller output")
        for expected, actual in zip(ratios[lane_id]["block_ratios"],
                                    reported[lane_id].get("block_ratios", [])):
            require(abs(expected - actual) <= RATIO_TOLERANCE, "NV_RATIO",
                    f"{lane_id} block ratio drift")
        require(abs(ratios[lane_id]["campaign_median"]
                    - reported[lane_id].get("campaign_median", -1)) <= RATIO_TOLERANCE,
                "NV_RATIO", f"{lane_id} median drift")
        require(ratios[lane_id]["outliers_above_1_15"]
                == reported[lane_id].get("outliers_above_1_15"), "NV_RATIO",
                f"{lane_id} outlier count drift")
    require(measurements.get("campaign_medians")
            == {lane: ratios[lane]["campaign_median"] for lane in LANE_IDS}, "NV_RATIO",
            "controller campaign medians disagree with independent recomputation")
    return reported


def write_receipt(root, name, payload):
    reviews = os.path.join(root, "target", "pr15i-c", "reviews")
    os.makedirs(reviews, exist_ok=True)
    path = os.path.join(reviews, name)
    if os.path.exists(path):
        raise VerificationFailed("NV_RECEIPT", f"refusing to replace {path}")
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def verify_campaign(root, campaign, verify_only, write=True):
    campaign = canonical_campaign(root, campaign)
    check_no_symlinks(campaign, "raw")
    found = inventory(campaign)
    before = verify_seal(campaign)
    manifest = read_json(os.path.join(campaign, "raw", "manifest.json"))
    measurements = read_json(os.path.join(campaign, "raw", "measurements.json"))
    authorization = read_json(os.path.join(campaign, "raw", "authorization.json"))
    require(manifest.get("schema") == SCHEMA, "NV_MANIFEST", "bad manifest schema")
    require(measurements.get("schema") == SCHEMA, "NV_MANIFEST", "bad measurement schema")
    require(authorization.get("diagnostic_only") is True, "NV_MANIFEST",
            "noise campaign must be diagnostic-only")
    mode = manifest.get("mode")
    require(mode in ("aa", "ag"), "NV_MANIFEST", "bad study mode")
    require(authorization.get("mode") == mode, "NV_MANIFEST", "mode mismatch")
    require(tuple(manifest.get("lane_ids", ())) == LANE_IDS, "NV_MANIFEST", "lane list drifted")
    require(manifest.get("warmups") == WARMUPS and manifest.get("measured") == MEASURED,
            "NV_MANIFEST", "sample counts drifted")
    require(manifest.get("slots") == SLOTS, "NV_MANIFEST", "slot count drifted")
    protocol = verify_protocol(root, manifest)
    body = verify_source(root, manifest, mode)
    executed = verify_executables(campaign, manifest, mode)
    layouts, digests = verify_sizes(campaign)
    rows, lanes = verify_corpus(campaign)
    slots, measured_samples, warmups = verify_slots(campaign, rows, lanes, executed, mode)
    ratios = recompute_ratios(slots)
    reported = compare_with_controller(ratios, measurements)

    after = {relative: sha256_file(os.path.join(campaign, "raw", relative))
             for relative in REQUIRED_RAW}
    require(before == after, "NV_TAMPER", "raw evidence changed during verification")

    campaign_medians = {lane: ratios[lane]["campaign_median"] for lane in LANE_IDS}
    if mode == "aa":
        qualified = all(AA_CAMPAIGN_MEDIAN_MIN <= value <= AA_CAMPAIGN_MEDIAN_MAX
                        for value in campaign_medians.values())
        decision = "AA_CAMPAIGN_QUALIFIED" if qualified else "AA_CAMPAIGN_UNSTABLE"
    else:
        qualified = all(value <= AG_CAMPAIGN_MEDIAN_MAX
                        for value in campaign_medians.values())
        decision = "AG_CAMPAIGN_OBSERVED" if qualified else "AG_CAMPAIGN_DRIFT"
    require(measurements.get("decision") == decision, "NV_GATE",
            "controller decision disagrees with independent derivation")

    payload = {
        "schema": RECEIPT_SCHEMA,
        "campaign": os.path.basename(campaign),
        "mode": mode,
        "A_sha": manifest.get("A_sha"),
        "B_sha": manifest.get("B_sha"),
        "protocol_sha256": protocol,
        "generic_body_sha256": body,
        "identical_executable": manifest.get("identical_executable"),
        "executed_binary": executed,
        "corpus_manifest_sha256": manifest.get("corpus_manifest_sha256"),
        "layouts": layouts,
        "segment_digests": digests,
        "rebuilds_remeasured": 12,
        "slots": SLOTS,
        "lane_records": SLOTS * len(LANE_IDS),
        "warmups": warmups,
        "measured_samples": measured_samples,
        "lane_ratios": ratios,
        "campaign_medians": campaign_medians,
        "controller_ratios": reported,
        "decision": decision,
        "diagnostic_only": True,
        "final_feature_acceptance": False,
        "raw_inventory": len(found),
        "seal_sha256": hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()).hexdigest(),
        "verify_only": verify_only,
    }
    if write:
        payload["receipt_path"] = write_receipt(
            root, f"noise-v2-{os.path.basename(campaign)}.json", payload)
    return payload


def evaluate_series(aa_campaign_medians, ag_campaign_medians):
    """Derive the predeclared A/A and A/G criteria from campaign medians.

    ``aa_campaign_medians`` / ``ag_campaign_medians`` map campaign id to
    ``{lane_id: campaign_median}``. Returns ``(aa_aggregate, ag_aggregate,
    aa_pass, ag_pass, decision)``.
    """
    require(len(aa_campaign_medians) == 4, "NV_SERIES", "A/A series must have four runs")
    require(len(ag_campaign_medians) == 4, "NV_SERIES", "A/G series must have four runs")
    aa_aggregate = {}
    ag_aggregate = {}
    for lane_id in LANE_IDS:
        aa_medians = [aa_campaign_medians[campaign][lane_id]
                      for campaign in sorted(aa_campaign_medians)]
        ordered = sorted(aa_medians)
        aa_aggregate[lane_id] = {
            "campaign_medians": aa_medians,
            "aggregate_median": (ordered[1] + ordered[2]) / 2,
            "campaign_medians_in_range": all(
                AA_CAMPAIGN_MEDIAN_MIN <= value <= AA_CAMPAIGN_MEDIAN_MAX
                for value in aa_medians),
        }
        ag_medians = [ag_campaign_medians[campaign][lane_id]
                      for campaign in sorted(ag_campaign_medians)]
        ordered = sorted(ag_medians)
        ag_aggregate[lane_id] = {
            "campaign_medians": ag_medians,
            "aggregate_median": (ordered[1] + ordered[2]) / 2,
            "runs_at_or_below_1_05": sum(1 for value in ag_medians if value <= 1.05),
            "max_campaign_median": max(ag_medians),
        }
    aa_pass = all(
        AA_AGGREGATE_MIN <= value["aggregate_median"] <= AA_AGGREGATE_MAX
        and value["campaign_medians_in_range"]
        for value in aa_aggregate.values())
    ag_pass = all(
        value["aggregate_median"] <= AG_AGGREGATE_MAX
        and value["max_campaign_median"] <= AG_CAMPAIGN_MEDIAN_MAX
        and value["runs_at_or_below_1_05"] >= AG_RUNS_AT_OR_BELOW_MIN
        for value in ag_aggregate.values())
    # A/A must hold on the same host/toolchain that produced the A/G series.
    ag_pass = ag_pass and aa_pass
    if not aa_pass:
        decision = "15IC_NOISE_DIAGNOSTIC_BLOCKED"
    elif not ag_pass:
        decision = "15IC_LAYOUT_DIAGNOSTIC_REJECTED_NO_NEW_IMPLEMENTATION"
    else:
        decision = "15IC_LAYOUT_COMPATIBLE_DIAGNOSTIC"
    return aa_aggregate, ag_aggregate, aa_pass, ag_pass, decision


def aggregate_series(root, series_root, verify_only, write=True):
    series_root = os.path.realpath(series_root)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "noise-diagnostics-v2"))
    require(series_root == allowed, "NV_SERIES", "series root must be the noise-diagnostics dir")
    results = {}
    for campaign_id, expected_mode in SERIES:
        path = os.path.join(series_root, campaign_id)
        require(os.path.isdir(path), "NV_SERIES", f"missing campaign {campaign_id}")
        payload = verify_campaign(root, path, verify_only, write=False)
        require(payload["mode"] == expected_mode, "NV_SERIES",
                f"{campaign_id} has mode {payload['mode']}, expected {expected_mode}")
        results[campaign_id] = payload

    aa = {campaign_id: payload for campaign_id, payload in results.items()
          if payload["mode"] == "aa"}
    ag = {campaign_id: payload for campaign_id, payload in results.items()
          if payload["mode"] == "ag"}
    require(len(aa) == 4 and len(ag) == 4, "NV_SERIES",
            "series must contain four A/A and four A/G runs")

    host_fingerprints = {
        read_json(os.path.join(series_root, campaign_id, "raw", "environment.json"))
        .get("host_fingerprint") for campaign_id in results}
    require(len(host_fingerprints) == 1, "NV_SERIES",
            "all eight campaigns must share one host fingerprint")
    toolchains = {
        read_json(os.path.join(series_root, campaign_id, "raw", "toolchain.json")).get("rustc")
        for campaign_id in results}
    require(len(toolchains) == 1, "NV_SERIES", "all eight campaigns must share one rustc")

    aa_aggregate, ag_aggregate, aa_pass, ag_pass, decision = evaluate_series(
        {campaign_id: payload["campaign_medians"] for campaign_id, payload in aa.items()},
        {campaign_id: payload["campaign_medians"] for campaign_id, payload in ag.items()},
    )

    payload = {
        "schema": AGGREGATE_SCHEMA,
        "protocol_sha256": protocol_sha(root),
        "campaigns": {
            campaign_id: {
                "mode": results[campaign_id]["mode"],
                "decision": results[campaign_id]["decision"],
                "seal_sha256": results[campaign_id]["seal_sha256"],
                "campaign_medians": results[campaign_id]["campaign_medians"],
            } for campaign_id in results
        },
        "aa_aggregate": aa_aggregate,
        "ag_aggregate": ag_aggregate,
        "aa_criteria": {
            "aggregate_median_min": AA_AGGREGATE_MIN,
            "aggregate_median_max": AA_AGGREGATE_MAX,
            "campaign_median_min": AA_CAMPAIGN_MEDIAN_MIN,
            "campaign_median_max": AA_CAMPAIGN_MEDIAN_MAX,
            "pass": aa_pass,
        },
        "ag_criteria": {
            "aggregate_median_max": AG_AGGREGATE_MAX,
            "campaign_median_max": AG_CAMPAIGN_MEDIAN_MAX,
            "runs_at_or_below_1_05_min": AG_RUNS_AT_OR_BELOW_MIN,
            "pass": ag_pass,
        },
        "per_block_1_15_status": "OBSERVATION_ONLY",
        "decision": decision,
        "diagnostic_only": True,
        "final_feature_acceptance": False,
        "verify_only": verify_only,
    }
    if write:
        name = "noise-v2-series-aggregate.json"
        path = os.path.join(root, "target", "pr15i-c", "reviews", name)
        suffix = 2
        while os.path.exists(path):
            name = f"noise-v2-series-aggregate-{suffix:02d}.json"
            path = os.path.join(root, "target", "pr15i-c", "reviews", name)
            suffix += 1
        payload["receipt_path"] = write_receipt(root, name, payload)
    return payload


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C noise-study independent verifier")
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
                root, "target", "pr15i-c", "noise-diagnostics-v2")
            payload = aggregate_series(root, series_root, args.verify_only,
                                       write=not args.no_receipt)
            print(f"PR15I_C noise series: {payload['decision']}")
            print(f"  A/A criteria pass: {payload['aa_criteria']['pass']}")
            print(f"  A/G criteria pass: {payload['ag_criteria']['pass']}")
            for lane_id in LANE_IDS:
                print(f"  {lane_id}: AA_AGG={payload['aa_aggregate'][lane_id]['aggregate_median']:.4f} "
                      f"AG_AGG={payload['ag_aggregate'][lane_id]['aggregate_median']:.4f} "
                      f"AG_runs<=1.05={payload['ag_aggregate'][lane_id]['runs_at_or_below_1_05']}")
            return 0
        payload = verify_campaign(root, args.campaign, args.verify_only,
                                  write=not args.no_receipt)
    except VerificationFailed as error:
        print(f"NV_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3
    print(f"PR15I_C noise verify mode={payload['mode']} decision={payload['decision']}")
    for lane_id in LANE_IDS:
        value = payload["lane_ratios"][lane_id]
        print(f"  {lane_id}: median={value['campaign_median']:.6f} "
              f"outliers>1.15={value['outliers_above_1_15']} "
              f"blocks={[round(item, 6) for item in value['block_ratios']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

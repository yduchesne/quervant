#!/usr/bin/env python3
"""PR 15I-C — independent verifier for the batched noise study.

Recomputes every diagnostic number from sealed raw evidence. It never imports a
controller statistic function and never trusts a reported verdict.

Modes:
  --campaign <dir> [--verify-only]      one campaign; writes an exclusive receipt
  --aggregate --series-root <dir>       all eight fixed campaigns + aggregate receipt
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


run = _load("pr15i_c_run_batched_verify", os.path.join(HERE, "run.py"))
patcher = _load("pr15i_c_patch_batched_verify",
                os.path.join(HERE, "batched_adapter_patch.py"))
base = run.base

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "batched_protocol_v1.json")
PROTOCOL_SCHEMA = "pr15i-c-batched-noise-v1"
SCHEMA = "pr15i-c-batched-campaign-v1"
SEAL_SCHEMA = "pr15i-c-batched-seal-v1"
RECEIPT_SCHEMA = "pr15i-c-batched-verification-v1"
AGGREGATE_SCHEMA = "pr15i-c-batched-series-v1"
BASELINE_SHA = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
GENERIC_CONTROL_SHA = "50b56e9fe7b22bb266ca7b0d9e209500dfc785ff"
FROZEN_MAIN_SHA = "42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63"
LANE_IDS = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
)
SHORT_LANE_IDS = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
)
BLOCK_ORDERS = (
    ("A", "B", "B", "A"),
    ("B", "A", "A", "B"),
    ("B", "A", "A", "B"),
    ("A", "B", "B", "A"),
    ("B", "A", "A", "B"),
    ("A", "B", "B", "A"),
    ("A", "B", "B", "A"),
    ("B", "A", "A", "B"),
)
BLOCKS = 8
SLOTS = 32
WARMUPS = 5
MEASURED_BATCHES = 10
REPEAT_SHORT = 100
REPEAT_CONTROL = 1
SHORT_LANE_FLOOR_NS = 1_000_000
MEASURED_BATCHES_PER_CAMPAIGN = SLOTS * len(LANE_IDS) * MEASURED_BATCHES
WARMUPS_PER_CAMPAIGN = SLOTS * len(LANE_IDS) * WARMUPS
SEARCH_CALLS_PER_CAMPAIGN = (
    SLOTS * MEASURED_BATCHES * (len(SHORT_LANE_IDS) * REPEAT_SHORT
                                + (len(LANE_IDS) - len(SHORT_LANE_IDS)) * REPEAT_CONTROL)
    + WARMUPS_PER_CAMPAIGN
)
AA_AGG_MIN = 0.97
AA_AGG_MAX = 1.03
AA_CAMPAIGN_MIN = 0.94
AA_CAMPAIGN_MAX = 1.06
AA_HARD_MIN = 0.85
AA_HARD_MAX = 1.15
AA_CAMPAIGNS_IN_BAND_MIN = 3
AG_AGG_MAX = 1.05
AG_CAMPAIGN_MAX = 1.10
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
SERIES_ORDER = [campaign for campaign, _ in SERIES]
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


def repeat_count_for(lane_id):
    return REPEAT_SHORT if lane_id in SHORT_LANE_IDS else REPEAT_CONTROL


def verify_affinity(manifest, authorization, environment):
    """Predeclared CPU-affinity mode must be valid and identical across records."""
    affinity = manifest.get("cpu_affinity")
    require(isinstance(affinity, dict), "BV_AFFINITY", "missing CPU affinity record")
    mode = affinity.get("mode")
    require(mode in ("PINNED", "NO_AFFINITY"), "BV_AFFINITY",
            f"invalid CPU affinity mode {mode!r}")
    if mode == "PINNED":
        require(isinstance(affinity.get("adapter_cpu"), int), "BV_AFFINITY",
                "pinned mode requires an adapter CPU")
        require(isinstance(affinity.get("controller_cpu"), int), "BV_AFFINITY",
                "pinned mode requires a controller CPU")
        require(affinity["adapter_cpu"] != affinity["controller_cpu"], "BV_AFFINITY",
                "adapter and controller CPUs must differ")
    require(authorization.get("cpu_affinity") == affinity, "BV_AFFINITY",
            "authorization/manifest affinity disagree")
    require(environment.get("cpu_affinity") == affinity, "BV_AFFINITY",
            "environment affinity disagrees")
    frequency_before = authorization.get("frequency_before")
    require(isinstance(frequency_before, dict), "BV_AFFINITY",
            "missing frequency observation")
    return affinity, frequency_before


def verify_protocol(root, manifest):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    require(protocol.get("schema") == PROTOCOL_SCHEMA, "BV_PROTOCOL", "bad protocol schema")
    require(tuple(protocol.get("lane_ids", [])) == LANE_IDS, "BV_PROTOCOL", "lane set drifted")
    require(tuple(protocol.get("short_lane_ids", [])) == SHORT_LANE_IDS, "BV_PROTOCOL",
            "short lane set drifted")
    require(protocol.get("repeat_count_short") == REPEAT_SHORT, "BV_PROTOCOL",
            "short repeat count drifted")
    require(protocol.get("repeat_count_control") == REPEAT_CONTROL, "BV_PROTOCOL",
            "control repeat count drifted")
    require(protocol.get("warmups") == WARMUPS, "BV_PROTOCOL", "warmups drifted")
    require(protocol.get("measured_batches_per_lane_slot") == MEASURED_BATCHES,
            "BV_PROTOCOL", "batch count drifted")
    require(protocol.get("slots_per_campaign") == SLOTS, "BV_PROTOCOL", "slot count drifted")
    require(protocol.get("frozen_adapter_main_rs_sha256") == FROZEN_MAIN_SHA, "BV_PROTOCOL",
            "frozen adapter blob pin drifted")
    require(tuple(protocol.get("series_order", [])) == tuple(SERIES_ORDER), "BV_PROTOCOL",
            "series order drifted")
    require(protocol.get("short_lane_slot_median_floor_ns") == SHORT_LANE_FLOOR_NS,
            "BV_PROTOCOL", "duration floor drifted")
    require(protocol.get("AA_aggregate_median_min") == AA_AGG_MIN, "BV_PROTOCOL", "AA min")
    require(protocol.get("AA_aggregate_median_max") == AA_AGG_MAX, "BV_PROTOCOL", "AA max")
    require(protocol.get("AA_campaign_median_min") == AA_CAMPAIGN_MIN, "BV_PROTOCOL",
            "AA campaign min")
    require(protocol.get("AA_campaign_median_max") == AA_CAMPAIGN_MAX, "BV_PROTOCOL",
            "AA campaign max")
    require(protocol.get("AA_campaign_median_hard_min") == AA_HARD_MIN, "BV_PROTOCOL",
            "AA hard min")
    require(protocol.get("AA_campaign_median_hard_max") == AA_HARD_MAX, "BV_PROTOCOL",
            "AA hard max")
    require(protocol.get("AA_campaigns_in_band_min") == AA_CAMPAIGNS_IN_BAND_MIN,
            "BV_PROTOCOL", "AA band count")
    require(protocol.get("AG_aggregate_median_max") == AG_AGG_MAX, "BV_PROTOCOL", "AG max")
    require(protocol.get("AG_campaign_median_max") == AG_CAMPAIGN_MAX, "BV_PROTOCOL",
            "AG campaign max")
    require(protocol.get("AG_runs_at_or_below_1_05_min") == AG_RUNS_AT_OR_BELOW_MIN,
            "BV_PROTOCOL", "AG run floor")
    require(protocol.get("sample_unit") == "batch", "BV_PROTOCOL", "sample unit drifted")
    require(protocol.get("timing_basis") == "outer_Rust_Instant_full_batch", "BV_PROTOCOL",
            "timing basis drifted")
    require(protocol.get("final_pr15ic_gate_unchanged") is True, "BV_PROTOCOL",
            "final gate must remain frozen")
    digest = sha256_file(os.path.join(root, PROTOCOL_REL))
    require(digest == manifest.get("protocol_sha256"), "BV_PROTOCOL", "protocol hash mismatch")
    return digest


def canonical_campaign(root, campaign):
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "batched-noise-v1"))
    candidate = os.path.realpath(campaign)
    require(os.path.commonpath([candidate, allowed]) == allowed and candidate != allowed,
            "BV_PATH", "campaign must be under target/pr15i-c/batched-noise-v1")
    return candidate


def check_no_symlinks(campaign, relative):
    current = campaign
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        info = os.lstat(current)
        require(not stat.S_ISLNK(info.st_mode), "BV_SYMLINK",
                f"symlinked path component {current}")


def inventory(campaign):
    raw = os.path.join(campaign, "raw")
    require(os.path.isdir(raw), "BV_INVENTORY", "missing raw directory")
    check_no_symlinks(campaign, "raw")
    found = []
    for root_dir, directories, files in os.walk(raw):
        for directory in directories:
            full = os.path.join(root_dir, directory)
            require(not os.path.islink(full), "BV_SYMLINK", f"symlinked directory {full}")
        for name in files:
            full = os.path.join(root_dir, name)
            require(not os.path.islink(full), "BV_SYMLINK", f"symlinked file {full}")
            found.append(os.path.relpath(full, raw).replace(os.sep, "/"))
    expected = set(REQUIRED_RAW) | {"seal.json"}
    extra = sorted(set(found) - expected)
    missing = sorted(expected - set(found))
    require(not extra, "BV_INVENTORY", f"unexpected raw files: {extra}")
    require(not missing, "BV_INVENTORY", f"missing raw files: {missing}")
    return sorted(found)


def verify_seal(campaign):
    seal_path = os.path.join(campaign, "raw", "seal.json")
    require(os.path.isfile(seal_path), "BV_SEAL", "missing raw/seal.json")
    seal = read_json(seal_path)
    require(seal.get("schema") == SEAL_SCHEMA, "BV_SEAL", "bad seal schema")
    files = seal.get("files")
    require(isinstance(files, dict), "BV_SEAL", "seal files must be a mapping")
    require(set(files) == set(REQUIRED_RAW), "BV_SEAL", "seal file set mismatch")
    before = {}
    for relative in REQUIRED_RAW:
        path = os.path.join(campaign, "raw", relative)
        digest = sha256_file(path)
        require(digest == files[relative], "BV_SEAL", f"seal hash mismatch for {relative}")
        before[relative] = digest
    return before


def _git(tree, *args):
    result = subprocess.run(["git", "-C", tree, *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def verify_source(root, manifest, mode):
    a_sha = manifest.get("A_sha")
    b_sha = manifest.get("B_sha")
    require(isinstance(a_sha, str) and len(a_sha) == 40, "BV_SOURCE", "bad A sha")
    require(isinstance(b_sha, str) and len(b_sha) == 40, "BV_SOURCE", "bad B sha")
    require(a_sha == BASELINE_SHA, "BV_SOURCE", "baseline is not merged PR 15I-B")
    for sha in (a_sha, b_sha):
        code, out, _err = _git(root, "cat-file", "-t", sha)
        require(code == 0 and out == "commit", "BV_SOURCE", f"{sha} is not a real commit")
    if mode == "aa":
        require(b_sha == a_sha, "BV_SOURCE", "A/A arms must reference the same source")
    else:
        require(b_sha == GENERIC_CONTROL_SHA, "BV_SOURCE", "A/G control is not the pinned G")
        code, _out, _err = _git(root, "merge-base", "--is-ancestor", a_sha, b_sha)
        require(code == 0, "BV_SOURCE", "G does not descend from A")
        code, out, _err = _git(root, "diff", "--name-only", f"{a_sha}..{b_sha}")
        require(code == 0, "BV_SOURCE", "git diff failed")
        changed = [
            path for path in out.splitlines()
            if path.startswith("crates/")
            and not path.startswith("crates/quervant-core/tests/")
            and not path.startswith("crates/quervant-core/benches/")
        ]
        require(changed == ["crates/quervant-core/src/search/unified.rs"], "BV_SCOPE",
                f"G production diff is not one file: {changed}")
    frozen = patcher.frozen_source(root)
    require(patcher.sha256_bytes(frozen.encode("utf-8")) == FROZEN_MAIN_SHA, "BV_ADAPTER",
            "frozen adapter blob drifted at the pinned commit")
    return FROZEN_MAIN_SHA


def verify_adapter_patch(campaign, manifest, executed, mode):
    patch = manifest.get("adapter_patch")
    require(isinstance(patch, dict), "BV_PATCH", "missing adapter patch record")
    require(patch.get("frozen_main_sha256") == FROZEN_MAIN_SHA, "BV_PATCH",
            "frozen adapter hash mismatch")
    for arm in ("A", "B"):
        record = patch.get(arm)
        require(isinstance(record, dict), "BV_PATCH", f"missing patch record for arm {arm}")
        derived = record.get("derived_main_sha256")
        require(isinstance(derived, str) and len(derived) == 64, "BV_PATCH",
                f"arm {arm} derived source hash malformed")
        require(isinstance(record.get("frozen_function_sha256"), dict), "BV_PATCH",
                f"arm {arm} frozen function hashes missing")
    if mode == "aa":
        require(patch["A"]["derived_main_sha256"] == patch["B"]["derived_main_sha256"],
                "BV_PATCH", "A/A arms must use one derived adapter source")


def verify_executables(campaign, manifest, mode):
    executed = manifest.get("executed_binary")
    require(isinstance(executed, dict), "BV_BINARY", "missing executed binary record")
    require(set(executed) == {"A", "B"}, "BV_BINARY", "executed binary arms must be A and B")
    toolchain = read_json(os.path.join(campaign, "raw", "toolchain.json"))
    for arm in ("A", "B"):
        path = executed[arm].get("path")
        digest = executed[arm].get("sha256")
        require(isinstance(path, str) and os.path.isabs(path), "BV_BINARY",
                f"arm {arm} executable path must be absolute")
        require(os.path.isfile(path), "BV_BINARY", f"arm {arm} executable is missing")
        require(not os.path.islink(path), "BV_BINARY", f"arm {arm} executable is a symlink")
        actual = sha256_file(path)
        require(actual == digest, "BV_BINARY", f"arm {arm} executable hash mismatch")
        require(toolchain.get("executed_binary_sha256", {}).get(arm, {}).get("sha256") == actual,
                "BV_BINARY", f"arm {arm} toolchain hash mismatch")
    if mode == "aa":
        require(executed["A"]["path"] == executed["B"]["path"], "BV_AA_BINARY",
                "A/A arms must execute the same file path")
        require(executed["A"]["sha256"] == executed["B"]["sha256"], "BV_AA_BINARY",
                "A/A arms must execute identical bytes")
        require(manifest.get("identical_executable") is True, "BV_AA_BINARY",
                "manifest must declare identical executables for A/A")
    else:
        require(manifest.get("identical_executable") is False, "BV_AG_BINARY",
                "manifest must declare distinct executables for A/G")
        require(executed["A"]["sha256"] != executed["B"]["sha256"], "BV_AG_BINARY",
                "A/G arms must be different executables")
    return executed


def verify_sizes(campaign):
    sizes = read_json(os.path.join(campaign, "raw", "sizes.json"))
    layouts = {"A": {}, "B": {}}
    digests = {"A": {}, "B": {}}
    seen_dirs = set()
    rebuilt = 0
    for arm in ("A", "B"):
        records = sizes.get(arm)
        require(isinstance(records, dict), "BV_SIZES", f"missing {arm} build records")
        for n in ("10000", "100000"):
            builds = records.get(n)
            require(isinstance(builds, list) and len(builds) == 3, "BV_SIZES",
                    f"{arm} n{n} must have three rebuild records")
            require([entry.get("attempt") for entry in builds] == [1, 2, 3], "BV_SIZES",
                    f"{arm} n{n} attempt order drift")
            current_layouts = set()
            current_digests = set()
            for entry in builds:
                index_dir = os.path.join(campaign, "setup", "sizes", arm,
                                         f"n{n}-run{entry['attempt']}")
                require(os.path.isdir(index_dir), "BV_SIZES", f"missing rebuild {index_dir}")
                check_no_symlinks(campaign, os.path.relpath(index_dir, campaign))
                real = os.path.realpath(index_dir)
                require(real not in seen_dirs, "BV_SIZES", f"reused index directory {real}")
                seen_dirs.add(real)
                current = run.measure_layout(index_dir)
                digest = run.segment_digest(index_dir)
                require(json.dumps(current, sort_keys=True)
                        == json.dumps(entry["layout"], sort_keys=True), "BV_SIZES",
                        f"{arm} n{n} run{entry['attempt']} layout drift")
                require(digest == entry.get("segment_digest"), "BV_SIZES",
                        f"{arm} n{n} run{entry['attempt']} digest drift")
                current_layouts.add(json.dumps(current, sort_keys=True))
                current_digests.add(digest)
                rebuilt += 1
            require(len(current_layouts) == 1 and len(current_digests) == 1, "BV_SIZES",
                    f"{arm} n{n} non-deterministic rebuilds")
            layouts[arm][n] = json.loads(next(iter(current_layouts)))
            digests[arm][n] = next(iter(current_digests))
    require(rebuilt == 12, "BV_SIZES", f"expected 12 remeasured rebuilds, found {rebuilt}")
    for n in ("10000", "100000"):
        require(json.dumps(layouts["A"][n], sort_keys=True)
                == json.dumps(layouts["B"][n], sort_keys=True), "BV_FORMAT",
                f"n{n} arm layouts differ")
        require(digests["A"][n] == digests["B"][n], "BV_FORMAT",
                f"n{n} arm segment digests differ")
        for arm in ("A", "B"):
            require(layouts[arm][n]["stored_version"] == 2, "BV_FORMAT",
                    f"{arm} n{n} not STORED v2")
            require(layouts[arm][n]["codec_id"] == 1, "BV_FORMAT", f"{arm} n{n} not LZ4")
            require([13, 1] in layouts[arm][n]["required_features"], "BV_FORMAT",
                    f"{arm} n{n} lacks required feature 0x000D v1")
    require(layouts["A"]["100000"]["committed_index_bytes"] == A_100K_TOTAL, "BV_SENTINEL",
            "100K committed-byte sentinel mismatch")
    require(layouts["A"]["100000"]["stored_bytes"] == A_100K_STORED, "BV_SENTINEL",
            "100K STORED-byte sentinel mismatch")
    return layouts, digests


def expected_arm(block, position):
    return BLOCK_ORDERS[block - 1][position - 1]


def validate_slot_matrix(slots, mode):
    require(len(slots) == SLOTS, "BV_SLOT", f"expected {SLOTS} slots, found {len(slots)}")
    seen = set()
    batches = 0
    warmups = 0
    searches = 0
    for position_expected, record in enumerate(slots, start=1):
        index = record.get("slot_index")
        require(index == position_expected, "BV_SLOT", f"slot {index} out of order")
        require(index not in seen, "BV_SLOT", f"duplicated slot {index}")
        seen.add(index)
        arm = record.get("arm")
        block = record.get("block")
        position = record.get("position")
        require(arm in ("A", "B"), "BV_SLOT", f"slot {index} bad arm")
        require(block in tuple(range(1, BLOCKS + 1)), "BV_SLOT", f"slot {index} bad block")
        require(position in (1, 2, 3, 4), "BV_SLOT", f"slot {index} bad position")
        require(arm == expected_arm(block, position), "BV_SLOT",
                f"slot {index} violates the prescribed ABBA/BAAB schedule")
        trial = record.get("trial")
        require(isinstance(trial, dict), "BV_SLOT", f"slot {index} missing trial")
        lanes_seen = [lane["id"] for lane in trial.get("lanes", [])]
        require(lanes_seen == list(LANE_IDS), "BV_SLOT", f"slot {index} lane set drift")
        for lane in trial["lanes"]:
            lane_id = lane["id"]
            expected_repeat = repeat_count_for(lane_id)
            require(lane.get("sample_unit") == "batch", "BV_UNITS",
                    f"slot {index} {lane_id} sample unit is not batch")
            require(lane.get("timing_basis") == "outer_Rust_Instant_full_batch", "BV_UNITS",
                    f"slot {index} {lane_id} timing basis drift")
            require(lane.get("repeat_count") == expected_repeat, "BV_UNITS",
                    f"slot {index} {lane_id} repeat count drift")
            samples = lane.get("raw_batch_ns")
            require(isinstance(samples, list) and len(samples) == MEASURED_BATCHES,
                    "BV_SLOT",
                    f"slot {index} {lane_id} batch count "
                    f"{len(samples) if samples else None}")
            for value in samples:
                require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
                        "BV_SLOT", f"slot {index} {lane_id} invalid batch_ns")
            require(lane.get("batch_count") == MEASURED_BATCHES, "BV_SLOT",
                    f"slot {index} {lane_id} batch_count drift")
            require(lane.get("warmup_count") == WARMUPS, "BV_SLOT",
                    f"slot {index} {lane_id} warmup count drift")
            require(len(lane.get("warmup_ids", [])) == WARMUPS, "BV_SLOT",
                    f"slot {index} {lane_id} warmup id drift")
            require(lane.get("search_count") == MEASURED_BATCHES * expected_repeat + WARMUPS,
                    "BV_SLOT", f"slot {index} {lane_id} search count drift")
            require(lane.get("summary_ns") == base.pr15d_run.summarize(samples), "BV_SLOT",
                    f"slot {index} {lane_id} batch summary mismatch")
            expected_mean = base.pr15d_run.summarize(samples)["median"] / expected_repeat
            require(abs(lane.get("mean_per_query_ns", -1) - expected_mean)
                    <= max(1e-9, abs(expected_mean) * 1e-12), "BV_UNITS",
                    f"slot {index} {lane_id} derived per-query value mismatch")
            batches += len(samples)
            warmups += WARMUPS
            searches += lane["search_count"]
        require(trial.get("contention_before", {}).get("state") == "clear", "BV_CONTENTION",
                f"slot {index} contention before not clear")
        require(trial.get("contention_after", {}).get("state") == "clear", "BV_CONTENTION",
                f"slot {index} contention after not clear")
    require(batches == MEASURED_BATCHES_PER_CAMPAIGN, "BV_COUNT",
            f"expected {MEASURED_BATCHES_PER_CAMPAIGN} batches, found {batches}")
    require(warmups == WARMUPS_PER_CAMPAIGN, "BV_COUNT",
            f"expected {WARMUPS_PER_CAMPAIGN} warmups, found {warmups}")
    require(searches == SEARCH_CALLS_PER_CAMPAIGN, "BV_COUNT",
            f"expected {SEARCH_CALLS_PER_CAMPAIGN} searches, found {searches}")
    for block in range(1, BLOCKS + 1):
        arms = [record["arm"] for record in slots if record["block"] == block]
        require(arms.count("A") == 2 and arms.count("B") == 2, "BV_SLOT",
                f"block {block} is not balanced")
    if mode == "aa":
        paths = {record["executed_binary_path"] for record in slots}
        digests = {record["binary_sha256"] for record in slots}
        require(len(paths) == 1 and len(digests) == 1, "BV_AA_BINARY",
                "A/A slots did not all execute one identical binary")
    return batches, warmups, searches


def verify_corpus(campaign):
    record = read_json(os.path.join(campaign, "raw", "corpus.json"))
    corpus_dir = os.path.join(campaign, "setup", "corpus")
    require(os.path.isdir(corpus_dir), "BV_CORPUS", "missing corpus directory")
    _manifest, rows = base.oracle.load_and_verify(corpus_dir)
    require(record.get("manifest_sha256") == FROZEN_CORPUS_SHA, "BV_CORPUS",
            "corpus manifest digest differs from the frozen value")
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    require([lane["id"] for lane in lanes] == list(LANE_IDS), "BV_CORPUS", "lane order drift")
    return rows, lanes


def verify_slots(campaign, rows, lanes, executed, mode):
    slots = [read_json(os.path.join(campaign, "raw", "slots", f"slot-{index:02d}.json"))
             for index in range(1, SLOTS + 1)]
    batches, warmups, searches = validate_slot_matrix(slots, mode)
    expected = {
        lane["id"]: base.oracle.expected(
            rows=rows[lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
        for lane in lanes
    }
    for record in slots:
        arm = record["arm"]
        require(record.get("executed_binary_path") == executed[arm]["path"], "BV_BINARY",
                f"slot {record['slot_index']} arm {arm} executable path drift")
        require(record.get("binary_sha256") == executed[arm]["sha256"], "BV_BINARY",
                f"slot {record['slot_index']} arm {arm} executable hash drift")
        for lane in record["trial"]["lanes"]:
            lane_id = lane["id"]
            require(lane.get("oracle_ok") is True, "BV_SLOT",
                    f"slot {record['slot_index']} {lane_id} oracle not ok")
            require(lane.get("total_hits") == expected[lane_id]["total_hits"], "BV_SLOT",
                    f"slot {record['slot_index']} {lane_id} total_hits drift")
            require(lane.get("doc_ids") == expected[lane_id]["doc_ids"], "BV_SLOT",
                    f"slot {record['slot_index']} {lane_id} key order drift")
    return slots, batches, warmups, searches


def recompute_ratios(slots):
    ratios = {}
    for lane_id in LANE_IDS:
        per_block = []
        a_medians = []
        b_medians = []
        for block in range(1, BLOCKS + 1):
            a_values = []
            b_values = []
            for record in slots:
                if record["block"] != block:
                    continue
                for lane in record["trial"]["lanes"]:
                    if lane["id"] != lane_id:
                        continue
                    median = base.pr15d_run.summarize(lane["raw_batch_ns"])["median"]
                    if record["arm"] == "A":
                        a_values.append(median)
                        a_medians.append(median)
                    else:
                        b_values.append(median)
                        b_medians.append(median)
            require(len(a_values) == 2 and len(b_values) == 2, "BV_RATIO",
                    f"{lane_id} block {block} sample drift")
            a_mean = sum(a_values) / 2
            b_mean = sum(b_values) / 2
            require(a_mean > 0, "BV_RATIO", f"{lane_id} block {block} zero denominator")
            per_block.append(b_mean / a_mean)
        ordered = sorted(per_block)
        floor_ok = True
        if lane_id in SHORT_LANE_IDS:
            floor_ok = (min(a_medians) >= SHORT_LANE_FLOOR_NS
                        and min(b_medians) >= SHORT_LANE_FLOOR_NS)
        ratios[lane_id] = {
            "block_ratios": per_block,
            "campaign_median": (ordered[3] + ordered[4]) / 2,
            "outliers_above_1_15": sum(1 for v in per_block if v > PER_BLOCK_OBSERVATION),
            "outliers_below_inverse_1_15": sum(
                1 for v in per_block if v < 1.0 / PER_BLOCK_OBSERVATION),
            "min_slot_median_batch_ns": min(a_medians + b_medians),
            "short_lane_duration_ok": floor_ok,
            "repeat_count": repeat_count_for(lane_id),
        }
    return ratios


def compare_with_controller(ratios, measurements):
    reported = measurements.get("ratios", {})
    for lane_id in LANE_IDS:
        require(lane_id in reported, "BV_RATIO", f"{lane_id} missing from controller output")
        for expected, actual in zip(ratios[lane_id]["block_ratios"],
                                    reported[lane_id].get("block_ratios", [])):
            require(abs(expected - actual) <= RATIO_TOLERANCE, "BV_RATIO",
                    f"{lane_id} block ratio drift")
        require(abs(ratios[lane_id]["campaign_median"]
                    - reported[lane_id].get("campaign_median", -1)) <= RATIO_TOLERANCE,
                "BV_RATIO", f"{lane_id} median drift")
        require(ratios[lane_id]["outliers_above_1_15"]
                == reported[lane_id].get("outliers_above_1_15"), "BV_RATIO",
                f"{lane_id} outlier count drift")
    require(measurements.get("campaign_medians")
            == {lane: ratios[lane]["campaign_median"] for lane in LANE_IDS}, "BV_RATIO",
            "controller campaign medians disagree with independent recomputation")
    return reported


def write_receipt(root, name, payload):
    reviews = os.path.join(root, "target", "pr15i-c", "reviews")
    os.makedirs(reviews, exist_ok=True)
    path = os.path.join(reviews, name)
    if os.path.exists(path):
        raise VerificationFailed("BV_RECEIPT", f"refusing to replace {path}")
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def verify_campaign(root, campaign, verify_only, write=True, receipt_name=None):
    campaign = canonical_campaign(root, campaign)
    check_no_symlinks(campaign, "raw")
    found = inventory(campaign)
    before = verify_seal(campaign)
    manifest = read_json(os.path.join(campaign, "raw", "manifest.json"))
    measurements = read_json(os.path.join(campaign, "raw", "measurements.json"))
    authorization = read_json(os.path.join(campaign, "raw", "authorization.json"))
    require(manifest.get("schema") == SCHEMA, "BV_MANIFEST", "bad manifest schema")
    require(measurements.get("schema") == SCHEMA, "BV_MANIFEST", "bad measurement schema")
    require(authorization.get("diagnostic_only") is True, "BV_MANIFEST",
            "batched campaign must be diagnostic-only")
    mode = manifest.get("mode")
    require(mode in ("aa", "ag"), "BV_MANIFEST", "bad study mode")
    require(authorization.get("mode") == mode, "BV_MANIFEST", "mode mismatch")
    require(tuple(manifest.get("lane_ids", ())) == LANE_IDS, "BV_MANIFEST", "lane list drifted")
    require(tuple(manifest.get("short_lane_ids", ())) == SHORT_LANE_IDS, "BV_MANIFEST",
            "short lane list drifted")
    require(manifest.get("warmups") == WARMUPS, "BV_MANIFEST", "warmup count drifted")
    require(manifest.get("measured_batches") == MEASURED_BATCHES, "BV_MANIFEST",
            "batch count drifted")
    require(manifest.get("repeat_count_short") == REPEAT_SHORT, "BV_MANIFEST",
            "short repeat count drifted")
    require(manifest.get("repeat_count_control") == REPEAT_CONTROL, "BV_MANIFEST",
            "control repeat count drifted")
    require(manifest.get("sample_unit") == "batch", "BV_UNITS", "sample unit drifted")
    require(manifest.get("timing_basis") == "outer_Rust_Instant_full_batch", "BV_UNITS",
            "timing basis drifted")
    protocol = verify_protocol(root, manifest)
    verify_source(root, manifest, mode)
    executed = verify_executables(campaign, manifest, mode)
    verify_adapter_patch(campaign, manifest, executed, mode)
    layouts, digests = verify_sizes(campaign)
    rows, lanes = verify_corpus(campaign)
    slots, batches, warmups, searches = verify_slots(campaign, rows, lanes, executed, mode)
    ratios = recompute_ratios(slots)
    reported = compare_with_controller(ratios, measurements)

    environment_record = read_json(os.path.join(campaign, "raw", "environment.json"))
    affinity, frequency_before = verify_affinity(
        manifest, authorization, environment_record)

    after = {relative: sha256_file(os.path.join(campaign, "raw", relative))
             for relative in REQUIRED_RAW}
    require(before == after, "BV_TAMPER", "raw evidence changed during verification")

    medians = {lane: ratios[lane]["campaign_median"] for lane in LANE_IDS}
    duration_ok = all(value["short_lane_duration_ok"] for value in ratios.values())
    if not duration_ok:
        decision = "BATCH_DURATION_BLOCKED"
    elif mode == "aa":
        qualified = all(AA_AGG_MIN <= value <= AA_AGG_MAX for value in medians.values())
        decision = "AA_CAMPAIGN_QUALIFIED" if qualified else "AA_CAMPAIGN_UNSTABLE"
    else:
        qualified = all(value <= AG_CAMPAIGN_MAX for value in medians.values())
        decision = "AG_CAMPAIGN_OBSERVED" if qualified else "AG_CAMPAIGN_DRIFT"
    require(measurements.get("decision") == decision, "BV_GATE",
            "controller decision disagrees with independent derivation")
    require(read_json(os.path.join(campaign, "raw", "manifest.json"))
            .get("counts", {}).get("search_calls") == searches, "BV_COUNT",
            "manifest search count mismatch")

    payload = {
        "schema": RECEIPT_SCHEMA,
        "campaign": os.path.basename(campaign),
        "mode": mode,
        "sequence_index": SERIES_ORDER.index(os.path.basename(campaign))
        if os.path.basename(campaign) in SERIES_ORDER else None,
        "A_sha": manifest.get("A_sha"),
        "B_sha": manifest.get("B_sha"),
        "protocol_sha256": protocol,
        "frozen_main_sha256": FROZEN_MAIN_SHA,
        "adapter_patch": manifest.get("adapter_patch"),
        "identical_executable": manifest.get("identical_executable"),
        "executed_binary": executed,
        "corpus_manifest_sha256": manifest.get("corpus_manifest_sha256"),
        "cpu_affinity": affinity,
        "frequency_before": frequency_before,
        "layouts": layouts,
        "segment_digests": digests,
        "rebuilds_remeasured": 12,
        "slots": SLOTS,
        "lane_records": SLOTS * len(LANE_IDS),
        "warmups": warmups,
        "measured_batches": batches,
        "search_calls": searches,
        "lane_ratios": ratios,
        "campaign_medians": medians,
        "short_lane_duration_ok": duration_ok,
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
            root, receipt_name or f"batched-v1-{os.path.basename(campaign)}.json", payload)
    return payload


def evaluate_series(aa_medians, ag_medians):
    """Predeclared A/A and A/G criteria from campaign medians."""
    require(sorted(aa_medians) == ["aa-01", "aa-02", "aa-03", "aa-04"], "BV_SERIES",
            f"A/A series ids are not the four fixed campaigns: {sorted(aa_medians)}")
    require(sorted(ag_medians) == ["ag-01", "ag-02", "ag-03", "ag-04"], "BV_SERIES",
            f"A/G series ids are not the four fixed campaigns: {sorted(ag_medians)}")
    aa = {}
    ag = {}
    for lane_id in LANE_IDS:
        values = [aa_medians[campaign][lane_id] for campaign in sorted(aa_medians)]
        ordered = sorted(values)
        in_band = sum(1 for value in values
                      if AA_CAMPAIGN_MIN <= value <= AA_CAMPAIGN_MAX)
        aa[lane_id] = {
            "campaign_medians": values,
            "aggregate_median": (ordered[1] + ordered[2]) / 2,
            "campaigns_in_band": in_band,
            "all_within_hard_bounds": all(
                AA_HARD_MIN <= value <= AA_HARD_MAX for value in values),
        }
        values = [ag_medians[campaign][lane_id] for campaign in sorted(ag_medians)]
        ordered = sorted(values)
        ag[lane_id] = {
            "campaign_medians": values,
            "aggregate_median": (ordered[1] + ordered[2]) / 2,
            "runs_at_or_below_1_05": sum(1 for value in values if value <= 1.05),
            "max_campaign_median": max(values),
        }
    aa_pass = all(
        AA_AGG_MIN <= value["aggregate_median"] <= AA_AGG_MAX
        and value["campaigns_in_band"] >= AA_CAMPAIGNS_IN_BAND_MIN
        and value["all_within_hard_bounds"]
        for value in aa.values())
    ag_pass = all(
        value["aggregate_median"] <= AG_AGG_MAX
        and value["runs_at_or_below_1_05"] >= AG_RUNS_AT_OR_BELOW_MIN
        and value["max_campaign_median"] <= AG_CAMPAIGN_MAX
        for value in ag.values())
    if not aa_pass:
        decision = "15IC_BATCHED_NOISE_BLOCKED"
    elif ag_pass:
        decision = "15IC_AG_DIAGNOSTIC_NEUTRAL"
    else:
        decision = "15IC_AG_DIAGNOSTIC_DRIFT"
    return aa, ag, aa_pass, ag_pass, decision


def aggregate_series(root, series_root, verify_only, write=True):
    series_root = os.path.realpath(series_root)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "batched-noise-v1"))
    require(series_root == allowed, "BV_SERIES", "series root must be the batched-noise-v1 dir")
    results = {}
    for campaign_id, expected_mode in SERIES:
        path = os.path.join(series_root, campaign_id)
        require(os.path.isdir(path), "BV_SERIES", f"missing campaign {campaign_id}")
        payload = verify_campaign(root, path, verify_only, write=False)
        require(payload["mode"] == expected_mode, "BV_SERIES",
                f"{campaign_id} has mode {payload['mode']}, expected {expected_mode}")
        require(payload["short_lane_duration_ok"], "BV_DURATION",
                f"{campaign_id} short-lane batch duration below the floor")
        results[campaign_id] = payload

    aa = {campaign_id: payload for campaign_id, payload in results.items()
          if payload["mode"] == "aa"}
    ag = {campaign_id: payload for campaign_id, payload in results.items()
          if payload["mode"] == "ag"}
    require(len(aa) == 4 and len(ag) == 4, "BV_SERIES",
            "series must contain four A/A and four A/G runs")

    fingerprints = {read_json(os.path.join(series_root, campaign_id, "raw",
                                           "environment.json")).get("host_fingerprint")
                    for campaign_id in results}
    require(len(fingerprints) == 1, "BV_SERIES",
            "all eight campaigns must share one host fingerprint")
    toolchains = {read_json(os.path.join(series_root, campaign_id, "raw", "toolchain.json"))
                  .get("rustc") for campaign_id in results}
    require(len(toolchains) == 1, "BV_SERIES", "all eight campaigns must share one rustc")
    protocols = {results[campaign_id]["protocol_sha256"] for campaign_id in results}
    require(len(protocols) == 1, "BV_SERIES", "all eight campaigns must share one protocol")
    affinities = {json.dumps(results[campaign_id]["cpu_affinity"], sort_keys=True)
                  for campaign_id in results}
    require(len(affinities) == 1, "BV_SERIES",
            "all eight campaigns must share one CPU affinity mode")

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
                "cpu_affinity": results[campaign_id]["cpu_affinity"],
                "measured_batches": results[campaign_id]["measured_batches"],
                "search_calls": results[campaign_id]["search_calls"],
            } for campaign_id in results
        },
        "series_order": SERIES_ORDER,
        "aa_aggregate": aa_aggregate,
        "ag_aggregate": ag_aggregate,
        "aa_criteria": {
            "aggregate_median_min": AA_AGG_MIN,
            "aggregate_median_max": AA_AGG_MAX,
            "campaign_median_min": AA_CAMPAIGN_MIN,
            "campaign_median_max": AA_CAMPAIGN_MAX,
            "campaign_median_hard_min": AA_HARD_MIN,
            "campaign_median_hard_max": AA_HARD_MAX,
            "campaigns_in_band_min": AA_CAMPAIGNS_IN_BAND_MIN,
            "short_lane_slot_median_floor_ns": SHORT_LANE_FLOOR_NS,
            "pass": aa_pass,
        },
        "ag_criteria": {
            "aggregate_median_max": AG_AGG_MAX,
            "campaign_median_max": AG_CAMPAIGN_MAX,
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
        name = "batched-v1-series-aggregate.json"
        path = os.path.join(root, "target", "pr15i-c", "reviews", name)
        suffix = 2
        while os.path.exists(path):
            name = f"batched-v1-series-aggregate-{suffix:02d}.json"
            path = os.path.join(root, "target", "pr15i-c", "reviews", name)
            suffix += 1
        payload["receipt_path"] = write_receipt(root, name, payload)
    return payload


def protocol_sha(root):
    return sha256_file(os.path.join(root, PROTOCOL_REL))


def build_parser():
    parser = argparse.ArgumentParser(
        description="PR 15I-C batched-noise independent verifier")
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
                root, "target", "pr15i-c", "batched-noise-v1")
            payload = aggregate_series(root, series_root, args.verify_only,
                                       write=not args.no_receipt)
            print(f"PR15I_C batched series: {payload['decision']}")
            print(f"  A/A pass: {payload['aa_criteria']['pass']}  "
                  f"A/G pass: {payload['ag_criteria']['pass']}")
            for lane_id in LANE_IDS:
                print(f"  {lane_id}: AA_AGG={payload['aa_aggregate'][lane_id]['aggregate_median']:.4f} "
                      f"AG_AGG={payload['ag_aggregate'][lane_id]['aggregate_median']:.4f}")
            return 0
        payload = verify_campaign(root, args.campaign, args.verify_only,
                                  write=not args.no_receipt)
    except (VerificationFailed, patcher.PatchError) as error:
        rule = getattr(error, "rule", "BV_ADAPTER")
        detail = getattr(error, "detail", str(error))
        print(f"BV_BLOCKED: {rule}: {detail}", file=sys.stderr)
        return 3
    print(f"PR15I_C batched verify mode={payload['mode']} decision={payload['decision']}")
    print(f"  batches={payload['measured_batches']} warmups={payload['warmups']} "
          f"searches={payload['search_calls']} duration_ok={payload['short_lane_duration_ok']}")
    for lane_id in LANE_IDS:
        value = payload["lane_ratios"][lane_id]
        print(f"  {lane_id}: median={value['campaign_median']:.6f} "
              f"floor_ok={value['short_lane_duration_ok']} "
              f"outliers>1.15={value['outliers_above_1_15']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

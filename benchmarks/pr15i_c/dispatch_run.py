#!/usr/bin/env python3
"""PR 15I-C dispatch-isolation study — four-arm (A/C/D/E) controller.

Diagnostic only. Every measured observation is one single request (`engine_ns`)
or one whole batch (`batch_ns`). The four arms differ only by the audited source
and feature/process-mode configuration described in `dispatch_protocol_v1.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load("pr15i_c_run", os.path.join(HERE, "run.py"))
patcher = _load("pr15i_c_batched_adapter_patch",
                os.path.join(HERE, "batched_adapter_patch.py"))
source_proof = _load("pr15i_c_dispatch_source_proof",
                     os.path.join(HERE, "dispatch_source_proof.py"))
codegen = _load("pr15i_c_dispatch_codegen_capture",
                os.path.join(HERE, "dispatch_codegen_capture.py"))
base = run.base

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "dispatch_protocol_v1.json")
PROTOCOL_SCHEMA = "pr15i-c-dispatch-isolation-v1"
SCHEMA = "pr15i-c-dispatch-campaign-v1"
SEAL_SCHEMA = "pr15i-c-dispatch-seal-v1"
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
SLOTS = BLOCKS * SLOTS_PER_BLOCK
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
CAMPAIGNS = (
    ("unbatched-01", "unbatched"),
    ("batched-01", "batched"),
    ("unbatched-02", "unbatched"),
    ("batched-02", "batched"),
)
RAW_METADATA = (
    "authorization.json",
    "protocol.json",
    "source-proof.json",
    "corpus.json",
    "environment.json",
    "toolchain.json",
    "binaries.json",
    "sizes.json",
    "score-parity.json",
    "measurements.json",
    "manifest.json",
)
REQUIRED_RAW = (
    *RAW_METADATA,
    *(f"slots/slot-{index:02d}.json" for index in range(1, SLOTS + 1)),
)

RunBlocked = run.RunBlocked
write_exclusive_json = run.write_exclusive_json
read_json = run.read_json
sha256_file = run.sha256_file


def protocol_digest(root):
    return sha256_file(os.path.join(root, PROTOCOL_REL))


def load_protocol(root):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise RunBlocked("DP_PROTOCOL", "bad dispatch protocol schema")
    expected = {
        "study_type": "FOUR_ARM_GENERIC_PATH_ISOLATION",
        "diagnostic_only": True,
        "baseline_source": BASE_A,
        "c_source": C_SHA,
        "d_source": D_SHA,
        "e_source": E_SHA,
        "blocks_per_campaign": BLOCKS,
        "slots_per_block": SLOTS_PER_BLOCK,
        "slots_per_campaign": SLOTS,
        "warmups_per_lane_slot": WARMUPS,
        "unbatched_samples_per_lane_slot": UNBATCHED_SAMPLES,
        "batched_samples_per_lane_slot": BATCHED_SAMPLES,
        "batched_repeat_count_absent_rare": REPEAT_SHORT,
        "batched_repeat_count_medium_common": REPEAT_OTHER,
        "index_rebuilds_per_arm_per_n": 3,
        "required_native_filesystem": "ext4",
        "required_affinity_mode": "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1",
        "100k_committed_index_bytes": A_100K_TOTAL,
        "100k_stored_bytes": A_100K_STORED,
        "frozen_feature_acceptance_protocol_unchanged": True,
        "source_control_required": True,
        "machine_code_capture_required_when_nm_objdump_available": True,
        "A_A_within_campaign_lane_median_min": 0.85,
        "A_A_within_campaign_lane_median_max": 1.15,
        "A_A_max_outlying_blocks_over_1_25_per_lane": 1,
        "candidate_neutral_median_ceiling": 1.08,
        "candidate_regressed_median_floor_10k": 1.15,
        "candidate_regressed_median_floor_100k": 1.4,
        "block_observation_1_15_only": True,
    }
    for key, value in expected.items():
        if protocol.get(key) != value:
            raise RunBlocked("DP_PROTOCOL", f"{key} drifted")
    if tuple(protocol.get("campaigns", ())) != tuple(name for name, _ in CAMPAIGNS):
        raise RunBlocked("DP_PROTOCOL", "campaign list drifted")
    if tuple(protocol.get("arm_order_by_block", ())) != SCHEDULE:
        raise RunBlocked("DP_PROTOCOL", "arm schedule drifted")
    for order in protocol["arm_order_by_block"]:
        if len(order) != SLOTS_PER_BLOCK or any(order.count(arm) != 2 for arm in ARMS):
            raise RunBlocked("DP_PROTOCOL", f"unbalanced block order {order!r}")
    if tuple(protocol.get("low_match_lanes", ())) != LOW_MATCH_LANES:
        raise RunBlocked("DP_PROTOCOL", "low-match lane set drifted")
    for arm in ("d_source", "e_source"):
        value = protocol.get(arm, "")
        if len(value) != 40 or value.startswith("FROM_"):
            raise RunBlocked("DP_PROTOCOL", f"{arm} is not a pinned 40-char SHA")
    return protocol


def validate_output(root, out):
    if not os.path.isabs(out):
        raise RunBlocked("DP_PATH", "--out must be absolute")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c",
                                            "dispatch-isolation-v1"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("DP_PATH",
                         "output must be under target/pr15i-c/dispatch-isolation-v1")
    if os.path.exists(candidate):
        raise RunBlocked("DP_EXISTS", "campaign exists; choose the next unused ID")
    return candidate


def resolve_affinity():
    allowed = sorted(os.sched_getaffinity(0))
    if 0 not in allowed or 1 not in allowed or shutil.which("taskset") is None:
        raise RunBlocked("DP_AFFINITY",
                         "adapter CPU 0 and controller CPU 1 must be pinnable")
    for cpu in (0, 1):
        probe = subprocess.run(["taskset", "-c", str(cpu), "true"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               check=False)
        if probe.returncode != 0:
            raise RunBlocked("DP_AFFINITY", f"taskset pinning to CPU {cpu} fails")
    return {"mode": "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1",
            "adapter_cpu": 0, "controller_cpu": 1}


def arm_environment(arm):
    env = dict(os.environ)
    for variable in ARM_MODE_VARIABLES.values():
        if variable:
            env.pop(variable, None)
    for key in ("RUSTFLAGS", "RUSTDOCFLAGS", "RUST_LOG", "LLVM_PROFILE_FILE",
                "CARGO_INCREMENTAL", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"):
        env.pop(key, None)
    variable = ARM_MODE_VARIABLES[arm]
    if variable:
        env[variable] = "disabled"
    return env


class DispatchAdapterProcess:
    """Frozen PR15D adapter transport with an explicit per-arm environment."""

    def __init__(self, engine, command, env=None):
        self.engine = engine
        self.command = command
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, env=env)

    def request(self, payload):
        if self.process.stdin is None or self.process.stdout is None:
            raise RunBlocked("DP_PROCESS", "adapter pipes unavailable")
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        reply = self.process.stdout.readline()
        if not reply:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RunBlocked("DP_PROCESS", f"adapter died: {stderr.strip()}")
        response = json.loads(reply)
        if response.get("schema") != "pr15d-adapter-v1":
            raise RunBlocked("DP_PROCESS", "adapter schema mismatch")
        if response.get("engine") != self.engine:
            raise RunBlocked("DP_PROCESS", "adapter engine mismatch")
        if response.get("status") != "ok":
            raise RunBlocked("DP_PROCESS",
                             json.dumps(response.get("error"), sort_keys=True))
        return response

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            self.process.kill()
            self.process.wait(timeout=10)


def worktree_name(root, campaign, arm):
    for index in range(1, 100):
        name = f"dispatch-{campaign}-{arm}-{index:02d}"
        path = os.path.join(root, "target", "pr15i-c", "worktrees", name)
        if not os.path.exists(path):
            return name
    raise RunBlocked("DP_WORKTREE", "no free worktree name")


def build_adapter(root, campaign, arm, source_sha, batched):
    tree = run._worktree(root, worktree_name(root, campaign, arm), source_sha)
    source = base.resolve_source_tree(tree)
    campaign_root = os.path.join(root, "target", "pr15i-c",
                                 "dispatch-isolation-v1", campaign)
    arm_dir = os.path.join(campaign_root, "setup", "build", arm)
    os.makedirs(arm_dir, exist_ok=True)
    feature = ARM_FEATURES[arm]
    if batched:
        destination = os.path.join(arm_dir, "batched_adapter")
        if os.path.exists(destination):
            shutil.rmtree(destination)
        record = patcher.materialize(
            root, destination, os.path.join(source["tree"], "crates", "quervant-core"))
        if feature:
            manifest_path = os.path.join(destination, "Cargo.toml")
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = handle.read()
            marker = (f'quervant-core = {{ path = "{source["tree"]}/crates/'
                      f'quervant-core" }}')
            if marker not in manifest:
                raise RunBlocked("DP_BUILD", "unexpected derived manifest")
            manifest = manifest.replace(
                marker, marker[:-2] + f', features = ["{feature}"] }}', 1)
            with open(manifest_path, "w", encoding="utf-8") as handle:
                handle.write(manifest)
        target_dir = os.path.join(arm_dir, "batched_build")
        binary = patcher.build(destination, target_dir)
        command = ["cargo", "build", "--release", "--offline", "--manifest-path",
                   os.path.join(destination, "Cargo.toml"), "--target-dir", target_dir]
    else:
        manifest = os.path.join(source["tree"], "benchmarks", "pr15d", "adapters",
                                "quervant", "Cargo.toml")
        target_dir = os.path.join(arm_dir, "build")
        command = ["cargo", "build", "--release", "--offline", "--manifest-path",
                   manifest, "--target-dir", target_dir]
        if feature:
            command += ["--features", f"quervant-core/{feature}"]
        env = arm_environment(arm)
        env.pop(ARM_MODE_VARIABLES[arm], None)  # builds never consult the mode
        result = subprocess.run(command, cwd=os.path.dirname(manifest),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, check=False, env=env)
        with open(os.path.join(arm_dir, "build.log"), "w", encoding="utf-8") as handle:
            handle.write(result.stdout)
        if result.returncode != 0:
            raise RunBlocked("DP_BUILD", f"{arm} adapter build failed: "
                                         f"{result.stdout[-1500:]}")
        binary = os.path.join(target_dir, "release", "pr15d-quervant-adapter")
    if not os.path.isfile(binary):
        raise RunBlocked("DP_BUILD", f"{arm} adapter binary missing: {binary}")
    return {"arm": arm, "source_sha": source["sha"], "feature": feature,
            "mode_variable": ARM_MODE_VARIABLES[arm], "binary": binary,
            "binary_sha256": sha256_file(binary), "command": command,
            "manifest_package": source["tree"]}


def build_score_probe(root, campaign, arm):
    source_tree = base.resolve_source_tree(
        run._worktree(root, worktree_name(root, campaign, f"probe-{arm}"),
                      ARM_SOURCES[arm]))["tree"]
    campaign_root = os.path.join(root, "target", "pr15i-c",
                                 "dispatch-isolation-v1", campaign)
    source = os.path.join(source_tree, "benchmarks", "pr15i_c", "score_probe")
    destination = os.path.join(campaign_root, "setup", "build", arm, "score_probe")
    os.makedirs(destination, exist_ok=True)
    os.makedirs(os.path.join(destination, "src"), exist_ok=True)
    with open(os.path.join(source, "Cargo.toml"), "r", encoding="utf-8") as handle:
        manifest = handle.read()
    feature = ARM_FEATURES[arm]
    replacement = (f'quervant-core = {{ path = "{source_tree}/crates/quervant-core"'
                   + (f', features = ["{feature}"]' if feature else "") + " }")
    manifest = manifest.replace(
        'quervant-core = { path = "../../../crates/quervant-core" }', replacement, 1)
    with open(os.path.join(destination, "Cargo.toml"), "w", encoding="utf-8") as handle:
        handle.write(manifest)
    shutil.copyfile(os.path.join(source, "src", "main.rs"),
                    os.path.join(destination, "src", "main.rs"))
    shutil.copyfile(os.path.join(source, "Cargo.lock"),
                    os.path.join(destination, "Cargo.lock"))
    target_dir = os.path.join(campaign_root, "setup", "build", arm, "score_probe_target")
    result = subprocess.run(
        ["cargo", "build", "--release", "--offline", "--manifest-path",
         os.path.join(destination, "Cargo.toml"), "--target-dir", target_dir],
        cwd=destination, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False)
    if result.returncode != 0:
        raise RunBlocked("DP_BUILD", f"{arm} score probe build failed: "
                                     f"{result.stdout[-1500:]}")
    binary = os.path.join(target_dir, "release", "pr15i-c-score-probe")
    if not os.path.isfile(binary):
        raise RunBlocked("DP_BUILD", f"{arm} score probe binary missing")
    return {"arm": arm, "binary": binary, "binary_sha256": sha256_file(binary),
            "manifest_sha256": sha256_file(os.path.join(destination, "Cargo.toml")),
            "feature": feature}


def build_index(adapter, corpus_path, index_dir, expected_rows, arm):
    if os.path.exists(index_dir):
        shutil.rmtree(index_dir)
    os.makedirs(index_dir, exist_ok=True)
    process = DispatchAdapterProcess("quervant", [adapter], env=arm_environment(arm))
    try:
        response = process.request({"request_id": "build", "op": "build",
                                    "corpus_path": corpus_path,
                                    "index_dir": index_dir})
    finally:
        process.close()
    for field in ("documents_indexed", "documents_verified"):
        if response.get(field) != expected_rows:
            raise RunBlocked("DP_BUILD", f"{arm} {field} mismatch")
    measured = base.pr15d_run.directory_bytes(index_dir)
    if response.get("index_bytes") != measured:
        raise RunBlocked("DP_BUILD", f"{arm} index_bytes disagree with disk")
    return {"index_ns": response["index_ns"], "commit_ns": response["commit_ns"],
            "index_bytes": measured}


def size_builds(arm_data, corpus, lanes, out):
    arm = arm_data["arm"]
    canonical, records, digests = {}, {}, {}
    for n in (10_000, 100_000):
        lane = next(lane for lane in lanes if lane["n"] == n and lane["class"] == "common")
        expected = base.oracle.expected(rows=corpus["rows"][n], field=lane["field"],
                                        term=lane["term"], k=lane["k"])
        builds = []
        for attempt in (1, 2, 3):
            target = os.path.join(out, "setup", "sizes", arm, f"n{n}-run{attempt}")
            record = build_index(arm_data["adapter"]["binary"],
                                 os.path.join(corpus["dir"],
                                              base.oracle.corpus_filename(n)),
                                 target, n, arm)
            process = DispatchAdapterProcess(
                "quervant", [arm_data["adapter"]["binary"], "--index-dir", target],
                env=arm_environment(arm))
            try:
                response = process.request({
                    "request_id": "oracle", "op": "query", "field": lane["field"],
                    "term": lane["term"], "k": lane["k"], "mode": lane["regime"]})
            finally:
                process.close()
            base.pr15d_run.validate_query_response(response, lane, expected)
            layout = run.measure_layout(target)
            digest = run.segment_digest(target)
            builds.append({"attempt": attempt, "layout": layout, "digest": digest,
                           "index_ns": record["index_ns"]})
        if len({json.dumps(b["layout"], sort_keys=True) for b in builds}) != 1:
            raise RunBlocked("DP_FORMAT", f"{arm} n{n} layout drift")
        if len({b["digest"] for b in builds}) != 1:
            raise RunBlocked("DP_FORMAT", f"{arm} n{n} digest drift")
        canonical[str(n)] = builds[-1]["layout"]
        digests[str(n)] = builds[-1]["digest"]
        records[str(n)] = builds
    for n in ("10000", "100000"):
        layout = canonical[n]
        if layout["stored_version"] != 2 or layout["codec_id"] != 1:
            raise RunBlocked("DP_FORMAT", f"{arm} n{n} not LZ4 STORED v2")
        if [13, 1] not in layout["required_features"]:
            raise RunBlocked("DP_FORMAT", f"{arm} n{n} lacks feature 0x000D v1")
    if (canonical["100000"]["committed_index_bytes"] != A_100K_TOTAL
            or canonical["100000"]["stored_bytes"] != A_100K_STORED):
        raise RunBlocked("DP_SENTINEL", f"{arm} 100K sentinel mismatch")
    return {"layouts": canonical, "digests": digests, "builds": records,
            "indices": {n: {"dir": os.path.join(out, "setup", "sizes", arm,
                                                f"n{n}-run3")}
                        for n in (10_000, 100_000)}}


def repeat_count_for(lane_id):
    return REPEAT_SHORT if lane_id in LOW_MATCH_LANES else REPEAT_OTHER


def measure_lane(arm, binary, index_dir, lane, expected, metadata, batched, affinity):
    command = [binary, "--index-dir", index_dir]
    command = ["taskset", "-c", str(affinity["adapter_cpu"]), *command]
    process = DispatchAdapterProcess("quervant", command, env=arm_environment(arm))
    samples, warmup_ids = [], []
    try:
        for warmup in range(WARMUPS):
            request_id = f"{arm}:{lane['id']}:warmup:{warmup}"
            response = process.request({
                "request_id": request_id, "op": "query", "field": lane["field"],
                "term": lane["term"], "k": lane["k"], "mode": lane["regime"]})
            base.pr15d_run.validate_query_response(response, lane, expected)
            warmup_ids.append(request_id)
        if batched:
            repeat = repeat_count_for(lane["id"])
            for sample in range(BATCHED_SAMPLES):
                request_id = f"{arm}:{lane['id']}:batch:{sample}"
                response = process.request({
                    "request_id": request_id, "op": "query_batch",
                    "field": lane["field"], "term": lane["term"],
                    "k": lane["k"], "repeat_count": repeat})
                if "engine_ns" in response:
                    raise RunBlocked("DP_UNIT", "batch reply carries engine_ns")
                if response.get("repeat_count") != repeat:
                    raise RunBlocked("DP_UNIT", f"{request_id} repeat count drift")
                value = response.get("batch_ns")
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise RunBlocked("DP_UNIT", f"{request_id} invalid batch_ns")
                if (response.get("total_hits") != expected["total_hits"]
                        or response.get("doc_ids") != expected["doc_ids"]):
                    raise RunBlocked("DP_ORACLE", f"{request_id} oracle mismatch")
                samples.append(value)
        else:
            for sample in range(UNBATCHED_SAMPLES):
                request_id = f"{arm}:{lane['id']}:sample:{sample}"
                response = process.request({
                    "request_id": request_id, "op": "query",
                    "field": lane["field"], "term": lane["term"],
                    "k": lane["k"], "mode": lane["regime"]})
                if "batch_ns" in response:
                    raise RunBlocked("DP_UNIT", "unbatched reply carries batch_ns")
                base.pr15d_run.validate_query_response(response, lane, expected)
                samples.append(response["engine_ns"])
    finally:
        process.close()
    expected_count = BATCHED_SAMPLES if batched else UNBATCHED_SAMPLES
    if len(samples) != expected_count:
        raise RunBlocked("DP_SAMPLE", f"{lane['id']} collected {len(samples)} samples")
    return {
        "id": lane["id"], "n": lane["n"], "class": lane["class"],
        "field": lane["field"], "term": lane["term"], "k": lane["k"],
        "regime": lane["regime"], "arm": arm,
        "mode": arm_environment(arm).get(ARM_MODE_VARIABLES[arm] or "_absent_"),
        "binary_path": binary, "binary_sha256": sha256_file(binary),
        "sample_unit": "batch" if batched else "single_query",
        "timing_field": "batch_ns" if batched else "engine_ns",
        "repeat_count": repeat_count_for(lane["id"]) if batched else 1,
        "warmup_ids": warmup_ids, "samples_ns": samples,
        "summary_ns": base.pr15d_run.summarize(samples),
        "total_hits": expected["total_hits"], "doc_ids": expected["doc_ids"],
        "oracle_ok": True, "analyzer": metadata["analyzer"],
    }


def measure_slot(slot, block, position, arm, context, lanes, expected, out, batched):
    trial_dir = os.path.join(out, "setup", "slots")
    before = base.contention_for(
        os.path.join(trial_dir, f"slot-{slot:02d}-before.json"))
    base._require_clear(before, f"slot {slot} before")
    lanes_records = [measure_lane(arm, context["binary"],
                                  context["index_dirs"][lane["n"]]["dir"], lane,
                                  expected[lane["id"]], context["metadata"], batched,
                                  context["affinity"]) for lane in lanes]
    after = base.contention_for(
        os.path.join(trial_dir, f"slot-{slot:02d}-after.json"))
    base._require_clear(after, f"slot {slot} after")
    return {"slot_index": slot, "block": block, "position": position, "arm": arm,
            "source_sha": ARM_SOURCES[arm], "executed_binary_path": context["binary"],
            "binary_sha256": sha256_file(context["binary"]),
            "mode": context["mode"], "started_utc": base.utc_now(),
            "lanes": lanes_records, "contention_before": before,
            "contention_after": after}


def arm_block_means(slots):
    means = {}
    for lane_id in LANE_IDS:
        for block in range(1, BLOCKS + 1):
            for arm in ARMS:
                values = [lane["summary_ns"]["median"] for record in slots
                          if record["block"] == block and record["arm"] == arm
                          for lane in record["lanes"] if lane["id"] == lane_id]
                if len(values) != 2:
                    raise RunBlocked("DP_GATE",
                                     f"{lane_id} block {block} arm {arm} slot drift")
                means[(arm, lane_id, block)] = sum(values) / 2
    return means


def derive(slots):
    means = arm_block_means(slots)
    ratios = {}
    for lane_id in LANE_IDS:
        entry = {arm: [] for arm in ("C/A", "D/A", "E/A")}
        a_first, a_second = [], []
        for block in range(1, BLOCKS + 1):
            a = means[("A", lane_id, block)]
            if a <= 0:
                raise RunBlocked("DP_GATE", f"{lane_id} block {block} zero denominator")
            for arm in "CDE":
                entry[f"{arm}/A"].append(means[(arm, lane_id, block)] / a)
            anchor = sorted(record["slot_index"] for record in slots
                            if record["block"] == block and record["arm"] == "A")
            first = next(record for record in slots if record["slot_index"] == anchor[0])
            second = next(record for record in slots if record["slot_index"] == anchor[1])
            first_median = next(lane["summary_ns"]["median"] for lane in first["lanes"]
                                if lane["id"] == lane_id)
            second_median = next(lane["summary_ns"]["median"] for lane in second["lanes"]
                                 if lane["id"] == lane_id)
            if first_median <= 0:
                raise RunBlocked("DP_GATE", f"{lane_id} block {block} zero A median")
            a_first.append(first_median)
            a_second.append(second_median)
            entry.setdefault("A2/A1", []).append(second_median / first_median)
        ordered = sorted(entry["A2/A1"])
        entry["a_drift_median"] = (ordered[1] + ordered[2]) / 2
        entry["medians"] = {}
        for key in ("C/A", "D/A", "E/A"):
            values = sorted(entry[key])
            entry["medians"][key] = (values[1] + values[2]) / 2
        entry["outliers_over_1_25"] = sum(1 for value in entry["A2/A1"]
                                          if value > 1.25 or value < 1 / 1.25)
        ratios[lane_id] = entry
    return ratios


def score_parity(probes, out, corpus_rows, lanes):
    records = {}
    for lane in lanes:
        expected = base.oracle.expected(rows=corpus_rows[lane["n"]],
                                        field=lane["field"], term=lane["term"],
                                        k=lane["k"])
        per_arm = {}
        for arm in ARMS:
            index_dir = os.path.join(out, "setup", "sizes", arm, f"n{lane['n']}-run3")
            result = subprocess.run(
                [probes[arm], "--index-dir", index_dir, "--field", lane["field"],
                 "--term", lane["term"], "--k", str(lane["k"])],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=arm_environment(arm), check=False)
            if result.returncode != 0:
                raise RunBlocked("DP_SCORE", f"{lane['id']} {arm}: "
                                             f"{result.stderr.strip()[:200]}")
            record = json.loads(result.stdout)
            if record.get("schema") != "pr15i-c-score-parity-v1":
                raise RunBlocked("DP_SCORE", f"{lane['id']} {arm} bad schema")
            keys = [hit["key"] for hit in record["hits"]]
            if keys != expected["doc_ids"]:
                raise RunBlocked("DP_SCORE", f"{lane['id']} {arm} key drift")
            if record["total_hits"] != expected["total_hits"]:
                raise RunBlocked("DP_SCORE", f"{lane['id']} {arm} total_hits drift")
            per_arm[arm] = [(hit["key"], hit["score_bits"]) for hit in record["hits"]]
        if not all(per_arm[arm] == per_arm["A"] for arm in ("C", "D", "E")):
            raise RunBlocked("DP_SCORE", f"{lane['id']} score bits differ across arms")
        records[lane["id"]] = {"total_hits": expected["total_hits"],
                               "hits": len(per_arm["A"]), "identical": True}
    return records


def execute(args):
    if not args.idle_confirmed:
        print("DP_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    if args.regime not in ("unbatched", "batched"):
        raise RunBlocked("DP_REGIME", "regime must be unbatched or batched")
    root = os.path.realpath(args.checkout_root)
    out = validate_output(root, args.out)
    campaign = os.path.basename(out)
    if (campaign, args.regime) not in CAMPAIGNS:
        raise RunBlocked("DP_NAME", f"unknown campaign {campaign}")
    protocol = load_protocol(root)
    if (args.baseline_sha, args.c_sha, args.d_sha, args.e_sha) != (
            BASE_A, C_SHA, D_SHA, E_SHA):
        raise RunBlocked("DP_SOURCE", "arm SHAs do not match the frozen protocol")
    affinity = resolve_affinity()
    batched = args.regime == "batched"
    original = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {affinity["controller_cpu"]})
    try:
        return _run(root, out, campaign, protocol, affinity, batched)
    finally:
        try:
            os.sched_setaffinity(0, original)
        except OSError:  # pragma: no cover
            pass


def _run(root, out, campaign, protocol, affinity, batched):
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("DP_LANES", "lane order drift")
    base.verify_frozen_files(root)
    proof = source_proof.verify_all(root, BASE_A, C_SHA, D_SHA, E_SHA)
    os.makedirs(out)
    os.makedirs(os.path.join(out, "raw"))
    environment = base.pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    filesystem = base.require_native_filesystem(out)
    if filesystem != "ext4":
        raise RunBlocked("DP_FS", f"native filesystem is {filesystem}, expected ext4")
    corpus = base.prepare_corpus(os.path.join(out, "setup"))
    if corpus["manifest_sha256"] != CORPUS_SHA:
        raise RunBlocked("DP_CORPUS", "corpus digest drifted")
    expected = {lane["id"]: base.oracle.expected(
        rows=corpus["rows"][lane["n"]], field=lane["field"], term=lane["term"],
        k=lane["k"]) for lane in lanes}

    arms = {}
    probes = {}
    for arm in ARMS:
        adapter = build_adapter(root, campaign, arm, ARM_SOURCES[arm], batched)
        arms[arm] = {"arm": arm, "source_sha": ARM_SOURCES[arm],
                     "adapter": adapter,
                     "metadata": base.pr15d_run.read_adapter_metadata(
                         "quervant", adapter["binary"])}
        probes[arm] = build_score_probe(root, campaign, arm)["binary"]

    if len({arms[arm]["adapter"]["binary_sha256"] for arm in ARMS}) != 4:
        raise RunBlocked("DP_BINARY", "the four arm binaries must be distinct")

    layouts, digests = {}, {}
    for arm in ARMS:
        arms[arm]["sizes"] = size_builds(arms[arm], corpus, lanes, out)
        layouts[arm] = arms[arm]["sizes"]["layouts"]
        digests[arm] = arms[arm]["sizes"]["digests"]
    for n in ("10000", "100000"):
        baseline = json.dumps(layouts["A"][n], sort_keys=True)
        for arm in ("C", "D", "E"):
            if json.dumps(layouts[arm][n], sort_keys=True) != baseline:
                raise RunBlocked("DP_FORMAT", f"n{n} {arm} layout differs from A")
            if digests[arm][n] != digests["A"][n]:
                raise RunBlocked("DP_FORMAT", f"n{n} {arm} digest differs from A")

    binary_before = {arm: sha256_file(arms[arm]["adapter"]["binary"]) for arm in ARMS}
    slots = []
    slot_index = 0
    for block, order in enumerate(SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            slot_index += 1
            context = {
                "binary": arms[arm]["adapter"]["binary"],
                "index_dirs": arms[arm]["sizes"]["indices"],
                "metadata": arms[arm]["metadata"],
                "mode": arm_environment(arm).get(ARM_MODE_VARIABLES[arm] or "_absent_"),
                "affinity": affinity,
            }
            record = measure_slot(slot_index, block, position, arm, context, lanes,
                                  expected, out, batched)
            write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{slot_index:02d}.json"),
                record)
            slots.append(record)
    binary_after = {arm: sha256_file(arms[arm]["adapter"]["binary"]) for arm in ARMS}
    if binary_before != binary_after:
        raise RunBlocked("DP_BINARY", "an adapter binary changed during the campaign")

    ratios = derive(slots)
    parity = score_parity(probes, out, corpus["rows"], lanes)
    observed_samples = sum(len(lane["samples_ns"]) for record in slots
                           for lane in record["lanes"])
    observed_warmups = sum(len(lane["warmup_ids"]) for record in slots
                           for lane in record["lanes"])
    expected_samples = SLOTS * len(LANE_IDS) * (BATCHED_SAMPLES if batched
                                                else UNBATCHED_SAMPLES)
    if observed_samples != expected_samples:
        raise RunBlocked("DP_COUNT", f"sample count {observed_samples}")
    if observed_warmups != SLOTS * len(LANE_IDS) * WARMUPS:
        raise RunBlocked("DP_COUNT", f"warmup count {observed_warmups}")

    codegen_out = os.path.join(root, "target", "pr15i-c", "dispatch-codegen-v1",
                               campaign)
    codegen_payload = codegen.capture(
        {arm: arms[arm]["adapter"]["binary"] for arm in ARMS}, codegen_out)
    codegen_checks = codegen.structural_checks(codegen_payload)

    protocol_sha = protocol_digest(root)
    measurements = {
        "schema": SCHEMA, "campaign": campaign,
        "regime": "batched" if batched else "unbatched",
        "ratios": ratios,
        "counts": {"samples": observed_samples, "warmups": observed_warmups,
                   "slots": SLOTS, "lane_slot_records": SLOTS * len(LANE_IDS)},
        "codegen_checks": codegen_checks,
        "diagnostic_only": True,
    }
    write_exclusive_json(os.path.join(out, "raw", "authorization.json"), {
        "schema": SCHEMA, "campaign": campaign, "regime": measurements["regime"],
        "diagnostic_only": True, "idle_authorized_by_user": True,
        "recorded_utc": base.utc_now(), "native_filesystem": filesystem,
        "cpu_affinity": affinity, "arm_sources": ARM_SOURCES,
        "arm_features": ARM_FEATURES, "arm_mode_variables": ARM_MODE_VARIABLES,
        "mode_policy": {arm: arm_environment(arm).get(
            ARM_MODE_VARIABLES[arm] or "_absent_") for arm in ARMS},
    })
    shutil.copyfile(os.path.join(root, PROTOCOL_REL),
                    os.path.join(out, "raw", "protocol.json"))
    write_exclusive_json(os.path.join(out, "raw", "source-proof.json"), {
        "schema": SCHEMA, **proof})
    write_exclusive_json(os.path.join(out, "raw", "corpus.json"), {
        "schema": SCHEMA, "manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"]})
    write_exclusive_json(os.path.join(out, "raw", "environment.json"), {
        "schema": SCHEMA, "host_fingerprint": fingerprint,
        "filesystem": filesystem, "environment": environment,
        "cpu_affinity": affinity})
    write_exclusive_json(os.path.join(out, "raw", "toolchain.json"), {
        "schema": SCHEMA,
        "rustc": subprocess.run(["rustc", "-Vv"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo": subprocess.run(["cargo", "-V"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo_lock_sha256": sha256_file(os.path.join(root, "Cargo.lock")),
        "arm_features": ARM_FEATURES, "arm_mode_variables": ARM_MODE_VARIABLES,
        "adapter_commands": {arm: arms[arm]["adapter"]["command"] for arm in ARMS}})
    write_exclusive_json(os.path.join(out, "raw", "binaries.json"), {
        "schema": SCHEMA,
        "adapters": {arm: {"path": arms[arm]["adapter"]["binary"],
                           "sha256": binary_after[arm],
                           "feature": ARM_FEATURES[arm],
                           "mode_variable": ARM_MODE_VARIABLES[arm]} for arm in ARMS},
        "score_probes": {arm: {"path": probes[arm],
                               "sha256": sha256_file(probes[arm])} for arm in ARMS},
        "codegen_capture": os.path.join(codegen_out, "dispatch-codegen.json")})
    write_exclusive_json(os.path.join(out, "raw", "sizes.json"), {
        "schema": SCHEMA,
        "builds": {arm: arms[arm]["sizes"]["builds"] for arm in ARMS},
        "layouts": layouts, "segment_digests": digests})
    write_exclusive_json(os.path.join(out, "raw", "score-parity.json"), {
        "schema": SCHEMA, "lanes": parity})
    write_exclusive_json(os.path.join(out, "raw", "measurements.json"), measurements)
    write_exclusive_json(os.path.join(out, "raw", "manifest.json"), {
        "schema": SCHEMA, "protocol_schema": protocol["schema"],
        "protocol_sha256": protocol_sha, "campaign": campaign,
        "regime": measurements["regime"], "arm_sources": ARM_SOURCES,
        "arm_features": ARM_FEATURES, "arm_mode_variables": ARM_MODE_VARIABLES,
        "adapter_sha256": {arm: binary_after[arm] for arm in ARMS},
        "adapter_path": {arm: arms[arm]["adapter"]["binary"] for arm in ARMS},
        "lane_ids": list(LANE_IDS), "arm_order_by_block": list(SCHEDULE),
        "sample_unit": "batch" if batched else "single_query",
        "environment_fingerprint": fingerprint, "filesystem": filesystem,
        "cpu_affinity": affinity, "counts": measurements["counts"],
        "codegen_checks": codegen_checks,
        "slots_sha256": {f"slots/slot-{index:02d}.json": sha256_file(
            os.path.join(out, "raw", "slots", f"slot-{index:02d}.json"))
            for index in range(1, SLOTS + 1)},
    })
    seal_campaign(out)
    print(f"PR15I_C dispatch campaign={campaign} regime={measurements['regime']} "
          f"samples={observed_samples} warmups={observed_warmups}")
    for lane_id in LANE_IDS:
        entry = ratios[lane_id]
        print(f"  {lane_id}: C/A={entry['medians']['C/A']:.4f} "
              f"D/A={entry['medians']['D/A']:.4f} "
              f"E/A={entry['medians']['E/A']:.4f} "
              f"drift={entry['a_drift_median']:.4f}")
    return 0


def seal_campaign(out):
    files = {}
    for relative in REQUIRED_RAW:
        path = os.path.join(out, "raw", relative)
        if not os.path.isfile(path):
            raise RunBlocked("DP_SEAL", f"missing raw file {relative}")
        files[relative] = sha256_file(path)
    write_exclusive_json(os.path.join(out, "raw", "seal.json"), {
        "schema": SEAL_SCHEMA, "files": files})


def build_parser():
    parser = argparse.ArgumentParser(
        description="PR 15I-C four-arm dispatch-isolation controller")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--c-sha", required=True)
    parser.add_argument("--d-sha", required=True)
    parser.add_argument("--e-sha", required=True)
    parser.add_argument("--regime", required=True, choices=("unbatched", "batched"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return execute(args)
    except (RunBlocked, source_proof.DispatchSourceError) as error:
        rule = getattr(error, "rule", "DP_SOURCE")
        detail = getattr(error, "detail", str(error))
        print(f"DP_BLOCKED: {rule}: {detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

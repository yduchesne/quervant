#!/usr/bin/env python3
"""PR 15I-C-F — four-arm diagnostic controller (A / C / G / P).

Arms: A = merged baseline; C = historical causal candidate (feature build, mode
disabled, generic inlined); G = F_DIAG feature build with mode disabled (generic
**out of line**); P = the *same* F_DIAG binary with mode enabled (physical
collector). G and P differ only by the child-process environment value.

Diagnostic only: this never replaces the frozen nine-lane acceptance campaign.
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
proof = _load("pr15i_c_f_final_source_proof",
              os.path.join(HERE, "f_final_source_proof.py"))
codegen = _load("pr15i_c_dispatch_codegen_capture",
                os.path.join(HERE, "dispatch_codegen_capture.py"))
base = run.base

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "f_final_protocol_v1.json")
PROTOCOL_SCHEMA = "pr15i-c-f-final-diag-v1"
SCHEMA = "pr15i-c-f-final-campaign-v1"
SEAL_SCHEMA = "pr15i-c-f-final-seal-v1"
BASE_A = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
CAUSAL = "658a2dde0e15c17e2b0c92278b5c922f5260fe60"
F_DIAG = "5f74bb691420673bde1181603d0a19a8a4114ec8"
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
PRIMARY_LANES = (
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
)
LOW_MATCH = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
)
CORPUS_SHA = "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151"
A_100K_TOTAL = 15_747_551
A_100K_STORED = 1_661_455
CAMPAIGNS = (("unbatched-01", "unbatched"), ("batched-01", "batched"),
             ("unbatched-02", "unbatched"), ("batched-02", "batched"))
RAW_METADATA = (
    "authorization.json", "protocol.json", "source-proof.json", "corpus.json",
    "environment.json", "toolchain.json", "binaries.json", "sizes.json",
    "score-parity.json", "mode-proof.json", "codegen.json", "measurements.json",
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


def load_f_final_protocol(root):
    path = os.path.join(root, PROTOCOL_REL)
    if not os.path.isfile(path):
        raise RunBlocked("FF_PROTOCOL", f"frozen protocol missing at {path}")
    protocol = read_json(path)
    expected = {
        "schema": PROTOCOL_SCHEMA,
        "study_type": "FINAL_GENERIC_BOUNDARY_WITH_PHYSICAL_OPERATOR",
        "diagnostic_only": True,
        "baseline_source": BASE_A,
        "historical_c_source": CAUSAL,
        "f_diagnostic_source": F_DIAG,
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
        "AA_control_min": 0.85,
        "AA_control_max": 1.15,
        "AA_max_blocks_outside_0_80_1_25_per_lane": 1,
        "C_repro_min_10k": 1.15,
        "C_repro_min_100k": 1.4,
        "F_generic_aggregate_max": 1.05,
        "F_generic_each_campaign_max": 1.1,
        "F_generic_each_block_1_15_observation_only": True,
        "two_unbatched_campaigns_required": True,
        "batched_classification_allowed": False,
        "frozen_feature_acceptance_unchanged": True,
    }
    for key, value in expected.items():
        if protocol.get(key) != value:
            raise RunBlocked("FF_PROTOCOL", f"{key} drifted")
    if tuple(protocol.get("campaigns", ())) != tuple(name for name, _ in CAMPAIGNS):
        raise RunBlocked("FF_PROTOCOL", "campaign list drifted")
    if tuple(protocol.get("arm_order_by_block", ())) != SCHEDULE:
        raise RunBlocked("FF_PROTOCOL", "schedule drifted")
    for block in SCHEDULE:
        if len(block) != SLOTS_PER_BLOCK or any(block.count(arm) != 2 for arm in ARMS):
            raise RunBlocked("FF_PROTOCOL", f"unbalanced block {block!r}")
    require_sha(protocol.get("f_diagnostic_source", ""), "F_DIAG")
    return protocol


def require_sha(value, label):
    if not isinstance(value, str) or len(value) != 40 or value.startswith("COMMITTED_"):
        raise RunBlocked("FF_PROTOCOL", f"{label} is not a pinned 40-char SHA")


def validate_output(root, out):
    if not os.path.isabs(out):
        raise RunBlocked("FF_PATH", "--out must be absolute")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c",
                                            "f-final-diagnostic-v1"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("FF_PATH",
                         "output must be under target/pr15i-c/f-final-diagnostic-v1")
    if os.path.exists(candidate):
        raise RunBlocked("FF_EXISTS", "campaign exists; choose the next unused ID")
    return candidate


def resolve_affinity():
    allowed = sorted(os.sched_getaffinity(0))
    if 0 not in allowed or 1 not in allowed or shutil.which("taskset") is None:
        raise RunBlocked("FF_AFFINITY", "CPUs 0/1 must be pinnable with taskset")
    for cpu in (0, 1):
        probe = subprocess.run(["taskset", "-c", str(cpu), "true"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               check=False)
        if probe.returncode != 0:
            raise RunBlocked("FF_AFFINITY", f"taskset CPU {cpu} fails")
    return {"mode": "PINNED_ADAPTER_CPU0_CONTROLLER_CPU1",
            "adapter_cpu": 0, "controller_cpu": 1}


def arm_mode(arm):
    return {"A": None, "C": "disabled", "G": "disabled", "P": "enabled"}[arm]


def arm_source(arm):
    """Diagnostic source commit for an arm (G and P share F_DIAG)."""
    return {"A": BASE_A, "C": CAUSAL, "G": F_DIAG, "P": F_DIAG}[arm]


def arm_environment(arm):
    env = dict(os.environ)
    env.pop(MODE_VARIABLE, None)
    for key in ("RUSTFLAGS", "RUSTDOCFLAGS", "RUST_LOG", "LLVM_PROFILE_FILE",
                "CARGO_INCREMENTAL", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"):
        env.pop(key, None)
    mode = arm_mode(arm)
    if mode is not None:
        env[MODE_VARIABLE] = mode
    return env


class FAdapterProcess:
    def __init__(self, engine, command, env=None):
        self.engine = engine
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, env=env)

    def request(self, payload):
        if self.process.stdin is None or self.process.stdout is None:
            raise RunBlocked("FF_PROCESS", "adapter pipes unavailable")
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        reply = self.process.stdout.readline()
        if not reply:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RunBlocked("FF_PROCESS", f"adapter died: {stderr.strip()}")
        response = json.loads(reply)
        if response.get("schema") != "pr15d-adapter-v1":
            raise RunBlocked("FF_PROCESS", "adapter schema mismatch")
        if response.get("status") != "ok":
            raise RunBlocked("FF_PROCESS",
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


def worktree_name(root, campaign, tag):
    for index in range(1, 100):
        name = f"ffinal-{campaign}-{tag}-{index:02d}"
        path = os.path.join(root, "target", "pr15i-c", "worktrees", name)
        if not os.path.exists(path):
            return name
    raise RunBlocked("FF_WORKTREE", "no free worktree name")


def build_adapter(root, campaign, tag, source_sha, feature, batched):
    tree = run._worktree(root, worktree_name(root, campaign, tag), source_sha)
    campaign_root = os.path.join(root, "target", "pr15i-c",
                                 "f-final-diagnostic-v1", campaign)
    arm_dir = os.path.join(campaign_root, "setup", "build", tag)
    os.makedirs(arm_dir, exist_ok=True)
    if batched:
        destination = os.path.join(arm_dir, "batched_adapter")
        if os.path.exists(destination):
            shutil.rmtree(destination)
        record = patcher.materialize(
            root, destination, os.path.join(tree, "crates", "quervant-core"))
        if feature:
            manifest_path = os.path.join(destination, "Cargo.toml")
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = handle.read()
            marker = f'quervant-core = {{ path = "{tree}/crates/quervant-core" }}'
            if marker not in manifest:
                raise RunBlocked("FF_BUILD", "unexpected derived manifest")
            manifest = manifest.replace(
                marker, marker[:-2] + f', features = ["{feature}"] }}', 1)
            with open(manifest_path, "w", encoding="utf-8") as handle:
                handle.write(manifest)
        target_dir = os.path.join(arm_dir, "batched_build")
        binary = patcher.build(destination, target_dir)
        command = ["cargo", "build", "--release", "--offline", "--manifest-path",
                   os.path.join(destination, "Cargo.toml"), "--target-dir", target_dir]
    else:
        manifest = os.path.join(tree, "benchmarks", "pr15d", "adapters", "quervant",
                                "Cargo.toml")
        target_dir = os.path.join(arm_dir, "build")
        command = ["cargo", "build", "--release", "--offline", "--manifest-path",
                   manifest, "--target-dir", target_dir]
        if feature:
            command += ["--features", f"quervant-core/{feature}"]
        env = dict(os.environ)
        env.pop(MODE_VARIABLE, None)
        result = subprocess.run(command, cwd=os.path.dirname(manifest),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=env, check=False)
        with open(os.path.join(arm_dir, "build.log"), "w", encoding="utf-8") as handle:
            handle.write(result.stdout)
        if result.returncode != 0:
            raise RunBlocked("FF_BUILD", f"{tag} build failed: {result.stdout[-1500:]}")
        binary = os.path.join(target_dir, "release", "pr15d-quervant-adapter")
    if not os.path.isfile(binary):
        raise RunBlocked("FF_BUILD", f"{tag} adapter binary missing")
    return {"binary": binary, "binary_sha256": sha256_file(binary),
            "source_sha": source_sha, "feature": feature, "command": command}


def build_score_probe(root, campaign, tag, source_sha, feature):
    campaign_root = os.path.join(root, "target", "pr15i-c",
                                 "f-final-diagnostic-v1", campaign)
    tree = base.resolve_source_tree(
        run._worktree(root, worktree_name(root, campaign, f"{tag}-probe"), source_sha))["tree"]
    source = os.path.join(ROOT, "benchmarks", "pr15i_c", "score_probe")
    destination = os.path.join(campaign_root, "setup", "build", tag, "score_probe")
    os.makedirs(os.path.join(destination, "src"), exist_ok=True)
    with open(os.path.join(source, "Cargo.toml"), "r", encoding="utf-8") as handle:
        manifest = handle.read()
    replacement = (f'quervant-core = {{ path = "{tree}/crates/quervant-core"'
                   + (f', features = ["{feature}"]' if feature else "") + " }")
    manifest = manifest.replace(
        'quervant-core = { path = "../../../crates/quervant-core" }', replacement, 1)
    with open(os.path.join(destination, "Cargo.toml"), "w", encoding="utf-8") as handle:
        handle.write(manifest)
    shutil.copyfile(os.path.join(source, "src", "main.rs"),
                    os.path.join(destination, "src", "main.rs"))
    shutil.copyfile(os.path.join(source, "Cargo.lock"),
                    os.path.join(destination, "Cargo.lock"))
    target_dir = os.path.join(campaign_root, "setup", "build", tag, "score_probe_target")
    result = subprocess.run(
        ["cargo", "build", "--release", "--offline", "--manifest-path",
         os.path.join(destination, "Cargo.toml"), "--target-dir", target_dir],
        cwd=destination, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False)
    if result.returncode != 0:
        raise RunBlocked("FF_BUILD", f"{tag} score probe failed: {result.stdout[-1200:]}")
    binary = os.path.join(target_dir, "release", "pr15i-c-score-probe")
    if not os.path.isfile(binary):
        raise RunBlocked("FF_BUILD", f"{tag} score probe binary missing")
    return {"binary": binary, "binary_sha256": sha256_file(binary),
            "feature": feature, "source_sha": source_sha}


def build_index(adapter, corpus_path, index_dir, expected_rows, arm):
    if os.path.exists(index_dir):
        shutil.rmtree(index_dir)
    os.makedirs(index_dir, exist_ok=True)
    process = FAdapterProcess("quervant", [adapter], env=arm_environment(arm))
    try:
        response = process.request({"request_id": "build", "op": "build",
                                    "corpus_path": corpus_path,
                                    "index_dir": index_dir})
    finally:
        process.close()
    for field in ("documents_indexed", "documents_verified"):
        if response.get(field) != expected_rows:
            raise RunBlocked("FF_BUILD", f"{arm} {field} mismatch")
    measured = base.pr15d_run.directory_bytes(index_dir)
    if response.get("index_bytes") != measured:
        raise RunBlocked("FF_BUILD", f"{arm} index_bytes disagree with disk")
    return {"index_ns": response["index_ns"], "commit_ns": response["commit_ns"]}


def size_builds(arm_data, corpus, lanes, out, label=None):
    arm = arm_data["arm"]
    label = label or arm
    canonical, records, digests = {}, {}, {}
    for n in (10_000, 100_000):
        lane = next(lane for lane in lanes if lane["n"] == n and lane["class"] == "common")
        expected = base.oracle.expected(rows=corpus["rows"][n], field=lane["field"],
                                        term=lane["term"], k=lane["k"])
        builds = []
        for attempt in (1, 2, 3):
            target = os.path.join(out, "setup", "sizes", label, f"n{n}-run{attempt}")
            record = build_index(arm_data["adapter"]["binary"],
                                 os.path.join(corpus["dir"],
                                              base.oracle.corpus_filename(n)),
                                 target, n, arm)
            process = FAdapterProcess(
                "quervant", [arm_data["adapter"]["binary"], "--index-dir", target],
                env=arm_environment(arm))
            try:
                response = process.request({
                    "request_id": "oracle", "op": "query", "field": lane["field"],
                    "term": lane["term"], "k": lane["k"], "mode": lane["regime"]})
            finally:
                process.close()
            base.pr15d_run.validate_query_response(response, lane, expected)
            builds.append({"attempt": attempt, "layout": run.measure_layout(target),
                           "digest": run.segment_digest(target),
                           "index_ns": record["index_ns"]})
        if len({json.dumps(b["layout"], sort_keys=True) for b in builds}) != 1:
            raise RunBlocked("FF_FORMAT", f"{arm} n{n} layout drift")
        if len({b["digest"] for b in builds}) != 1:
            raise RunBlocked("FF_FORMAT", f"{arm} n{n} digest drift")
        canonical[str(n)] = builds[-1]["layout"]
        digests[str(n)] = builds[-1]["digest"]
        records[str(n)] = builds
    for n in ("10000", "100000"):
        layout = canonical[n]
        if layout["stored_version"] != 2 or layout["codec_id"] != 1:
            raise RunBlocked("FF_FORMAT", f"{arm} n{n} not LZ4 STORED v2")
        if [13, 1] not in layout["required_features"]:
            raise RunBlocked("FF_FORMAT", f"{arm} n{n} lacks 0x000D v1")
    if (canonical["100000"]["committed_index_bytes"] != A_100K_TOTAL
            or canonical["100000"]["stored_bytes"] != A_100K_STORED):
        raise RunBlocked("FF_SENTINEL", f"{arm} sentinel mismatch")
    return {"layouts": canonical, "digests": digests, "builds": records,
            "indices": {n: {"dir": os.path.join(out, "setup", "sizes", label,
                                                f"n{n}-run3")}
                        for n in (10_000, 100_000)}}


def repeat_count_for(lane_id):
    return REPEAT_SHORT if lane_id in LOW_MATCH else REPEAT_OTHER


def measure_f_lane(arm, context, lane, expected, batched):
    command = ["taskset", "-c", str(context["affinity"]["adapter_cpu"]),
               context["binary"], "--index-dir", context["index_dirs"][lane["n"]]["dir"]]
    process = FAdapterProcess("quervant", command, env=arm_environment(arm))
    samples, warmups = [], []
    try:
        for warmup in range(WARMUPS):
            request_id = f"{arm}:{lane['id']}:warmup:{warmup}"
            response = process.request({
                "request_id": request_id, "op": "query", "field": lane["field"],
                "term": lane["term"], "k": lane["k"], "mode": lane["regime"]})
            base.pr15d_run.validate_query_response(response, lane, expected)
            warmups.append(request_id)
        if batched:
            repeat = repeat_count_for(lane["id"])
            for sample in range(BATCHED):
                request_id = f"{arm}:{lane['id']}:batch:{sample}"
                response = process.request({
                    "request_id": request_id, "op": "query_batch",
                    "field": lane["field"], "term": lane["term"],
                    "k": lane["k"], "repeat_count": repeat})
                if "engine_ns" in response:
                    raise RunBlocked("FF_UNITS", "batch reply carries engine_ns")
                if response.get("repeat_count") != repeat:
                    raise RunBlocked("FF_UNITS", f"{request_id} repeat drift")
                value = response.get("batch_ns")
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise RunBlocked("FF_UNITS", f"{request_id} invalid batch_ns")
                if (response.get("total_hits") != expected["total_hits"]
                        or response.get("doc_ids") != expected["doc_ids"]):
                    raise RunBlocked("FF_ORACLE", f"{request_id} oracle mismatch")
                samples.append(value)
        else:
            for sample in range(UNBATCHED):
                request_id = f"{arm}:{lane['id']}:sample:{sample}"
                response = process.request({
                    "request_id": request_id, "op": "query",
                    "field": lane["field"], "term": lane["term"],
                    "k": lane["k"], "mode": lane["regime"]})
                if "batch_ns" in response:
                    raise RunBlocked("FF_UNITS", "unbatched reply carries batch_ns")
                base.pr15d_run.validate_query_response(response, lane, expected)
                samples.append(response["engine_ns"])
    finally:
        process.close()
    expected_count = BATCHED if batched else UNBATCHED
    if len(samples) != expected_count:
        raise RunBlocked("FF_SAMPLE", f"{lane['id']} collected {len(samples)}")
    return {
        "id": lane["id"], "n": lane["n"], "class": lane["class"],
        "field": lane["field"], "term": lane["term"], "k": lane["k"],
        "regime": lane["regime"], "arm": arm, "mode": arm_mode(arm),
        "binary_path": context["binary"],
        "binary_sha256": sha256_file(context["binary"]),
        "sample_unit": "batch" if batched else "single_query",
        "timing_field": "batch_ns" if batched else "engine_ns",
        "repeat_count": repeat_count_for(lane["id"]) if batched else 1,
        "warmup_ids": warmups, "samples_ns": samples,
        "summary_ns": base.pr15d_run.summarize(samples),
        "total_hits": expected["total_hits"], "doc_ids": expected["doc_ids"],
        "oracle_ok": True, "analyzer": context["metadata"]["analyzer"],
    }


def measure_f_slot(slot_index, arm, context, lanes, expected, output, batched):
    trial_dir = os.path.join(output, "setup", "slots")
    before_path = os.path.join(trial_dir, f"slot-{slot_index:02d}-before.json")
    before = dict(base.contention_for(before_path), probe_path=before_path)
    base._require_clear(before, f"slot {slot_index} before")
    records = [measure_f_lane(arm, context, lane, expected[lane["id"]], batched)
               for lane in lanes]
    after_path = os.path.join(trial_dir, f"slot-{slot_index:02d}-after.json")
    after = dict(base.contention_for(after_path), probe_path=after_path)
    base._require_clear(after, f"slot {slot_index} after")
    return {"slot_index": slot_index, "arm": arm, "source_sha": context["source_sha"],
            "binary_path": context["binary"],
            "binary_sha256": sha256_file(context["binary"]),
            "feature": context["feature"], "mode": arm_mode(arm),
            "started_utc": base.utc_now(), "lanes": records,
            "contention_before": before, "contention_after": after}


def derive_f_block_ratios(slots, lane_ids=LANE_IDS):
    means = {}
    for lane_id in lane_ids:
        for block in range(1, BLOCKS + 1):
            for arm in ARMS:
                medians = [lane["summary_ns"]["median"] for record in slots
                           if record["block"] == block and record["arm"] == arm
                           for lane in record["lanes"] if lane["id"] == lane_id]
                if len(medians) != 2:
                    raise RunBlocked("FF_GATE",
                                     f"{lane_id} block {block} {arm} slot drift")
                means[(arm, lane_id, block)] = sum(medians) / 2
    ratios = {}
    for lane_id in lane_ids:
        entry = {"C/A": [], "G/A": [], "P/A": [], "P/G": [], "A2/A1": []}
        for block in range(1, BLOCKS + 1):
            a = means[("A", lane_id, block)]
            c = means[("C", lane_id, block)]
            g = means[("G", lane_id, block)]
            p = means[("P", lane_id, block)]
            if a <= 0 or g <= 0:
                raise RunBlocked("FF_GATE", f"{lane_id} block {block} zero denominator")
            entry["C/A"].append(c / a)
            entry["G/A"].append(g / a)
            entry["P/A"].append(p / a)
            entry["P/G"].append(p / g)
            a_slots = sorted((record for record in slots
                              if record["block"] == block and record["arm"] == "A"),
                             key=lambda record: record["slot_index"])
            first = next(lane["summary_ns"]["median"] for lane in a_slots[0]["lanes"]
                         if lane["id"] == lane_id)
            second = next(lane["summary_ns"]["median"] for lane in a_slots[1]["lanes"]
                          if lane["id"] == lane_id)
            if first <= 0:
                raise RunBlocked("FF_GATE", f"{lane_id} block {block} zero A median")
            entry["A2/A1"].append(second / first)
        ordered = sorted(entry["A2/A1"])
        entry["a_drift_median"] = (ordered[1] + ordered[2]) / 2
        entry["a_drift_outliers"] = sum(1 for value in entry["A2/A1"]
                                        if value > 1.25 or value < 1 / 1.25)
        entry["medians"] = {}
        for key in ("C/A", "G/A", "P/A", "P/G"):
            values = sorted(entry[key])
            entry["medians"][key] = (values[1] + values[2]) / 2
        ratios[lane_id] = entry
    return ratios


def score_parity(probes, output, corpus_rows, lanes):
    records = {}
    for lane in lanes:
        expected = base.oracle.expected(rows=corpus_rows[lane["n"]],
                                        field=lane["field"], term=lane["term"],
                                        k=lane["k"])
        per_arm = {}
        for arm in ARMS:
            index_dir = os.path.join(output, "setup", "sizes",
                                     "F" if arm in ("G", "P") else arm,
                                     f"n{lane['n']}-run3")
            result = subprocess.run(
                [probes[arm], "--index-dir", index_dir, "--field", lane["field"],
                 "--term", lane["term"], "--k", str(lane["k"])],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=arm_environment(arm), check=False)
            if result.returncode != 0:
                raise RunBlocked("FF_SCORE", f"{lane['id']} {arm}: "
                                             f"{result.stderr.strip()[:200]}")
            record = json.loads(result.stdout)
            keys = [hit["key"] for hit in record["hits"]]
            if keys != expected["doc_ids"]:
                raise RunBlocked("FF_SCORE", f"{lane['id']} {arm} key drift")
            if record["total_hits"] != expected["total_hits"]:
                raise RunBlocked("FF_SCORE", f"{lane['id']} {arm} total_hits drift")
            per_arm[arm] = [(hit["key"], hit["score_bits"]) for hit in record["hits"]]
        if not all(per_arm[arm] == per_arm["A"] for arm in ("C", "G", "P")):
            raise RunBlocked("FF_SCORE", f"{lane['id']} score bits differ across arms")
        records[lane["id"]] = {"total_hits": expected["total_hits"],
                               "hits": len(per_arm["A"]), "identical": True}
    return records


def mode_proof(arm_data, lanes, expected):
    """Truth table for the diagnostic gate (separate processes per arm)."""
    probes = []
    request = {"request_id": "mode", "op": "query", "field": lanes[0]["field"],
               "term": lanes[0]["term"], "k": lanes[0]["k"],
               "mode": lanes[0]["regime"]}
    plans = (("A", None, "ok"), ("C", "disabled", "ok"),
             ("G", "disabled", "ok"), ("P", "enabled", "ok"),
             ("INVALID", "bogus", "error"), ("MISSING", "absent", "error"))
    for label, mode, expected_state in plans:
        binary = arm_data["A" if label == "A" else ("C" if label == "C" else "G")][
            "adapter"]["binary"]
        index_dir = arm_data["A" if label == "A" else (
            "C" if label == "C" else "G")]["sizes"]["indices"][10_000]["dir"]
        env = dict(os.environ)
        env.pop(MODE_VARIABLE, None)
        if mode is not None:
            env[MODE_VARIABLE] = mode
        result = subprocess.run([binary, "--index-dir", index_dir],
                                input=json.dumps(request) + "\n",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, check=False)
        reply = json.loads(result.stdout.strip().splitlines()[-1])
        if expected_state == "ok":
            if reply.get("status") != "ok":
                raise RunBlocked("FF_MODE", f"{label} failed: {reply}")
            if reply.get("total_hits") != expected[lanes[0]["id"]]["total_hits"]:
                raise RunBlocked("FF_MODE", f"{label} hit count drift")
        else:
            if reply.get("status") != "error":
                raise RunBlocked("FF_MODE", f"{label} must be a typed error")
            if "invalid PR15IC causal experiment mode" not in json.dumps(reply["error"]):
                raise RunBlocked("FF_MODE", f"{label} wrong error")
        probes.append({"label": label, "environment_mode": mode,
                       "expected": expected_state,
                       "observed_status": reply.get("status"),
                       "binary_path": binary,
                       "binary_sha256": sha256_file(binary)})
    return {"binary_path": arm_data["G"]["adapter"]["binary"],
            "binary_sha256": sha256_file(arm_data["G"]["adapter"]["binary"]),
            "probes": probes}


def f_codegen_checks(payload):
    """Structural codegen facts for the F diagnostic (presence only)."""
    presence = payload.get("method_presence") or {}
    return {
        "f_physical_present": presence.get("D", {}).get(
            "collect_exact_term_physical") == "PRESENT",
        "f_generic_out_of_line": presence.get("D", {}).get("collect_mixed")
        == "PRESENT",
        "f_execute_present": presence.get("D", {}).get("execute_unified") == "PRESENT",
        "a_execute_present": presence.get("A", {}).get("execute_unified") == "PRESENT",
        "c_execute_present": presence.get("C", {}).get("execute_unified") == "PRESENT",
        "e_execute_present": presence.get("E", {}).get("execute_unified") == "PRESENT",
    }


def seal_f_campaign(output):
    files = {}
    for relative in REQUIRED_RAW:
        path = os.path.join(output, "raw", relative)
        if not os.path.isfile(path):
            raise RunBlocked("FF_SEAL", f"missing raw file {relative}")
        files[relative] = sha256_file(path)
    write_exclusive_json(os.path.join(output, "raw", "seal.json"), {
        "schema": SEAL_SCHEMA, "files": files})


def execute_f_campaign(args):
    if not args.idle_confirmed:
        print("FF_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    if args.regime not in ("unbatched", "batched"):
        raise RunBlocked("FF_REGIME", "regime must be unbatched or batched")
    root = os.path.realpath(args.checkout_root)
    output = validate_output(root, args.out)
    campaign = os.path.basename(output)
    if (campaign, args.regime) not in CAMPAIGNS:
        raise RunBlocked("FF_NAME", f"unknown campaign {campaign}")
    protocol = load_f_final_protocol(root)
    if (args.baseline_sha, args.c_sha, args.f_diag_sha) != (BASE_A, CAUSAL, F_DIAG):
        raise RunBlocked("FF_SOURCE", "arm SHAs do not match the frozen protocol")
    batched = args.regime == "batched"
    affinity = resolve_affinity()
    os.makedirs(output)
    os.makedirs(os.path.join(output, "raw"))
    source_report = proof.verify_f_diag(root, F_DIAG)
    base.verify_frozen_files(root)
    environment = base.pr15d_run.collect_environment(os.path.join(output, "setup"))
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    filesystem = base.require_native_filesystem(output)
    if filesystem != "ext4":
        raise RunBlocked("FF_FS", f"filesystem {filesystem} is not ext4")
    corpus = base.prepare_corpus(os.path.join(output, "setup"))
    if corpus["manifest_sha256"] != CORPUS_SHA:
        raise RunBlocked("FF_CORPUS", "corpus digest drift")
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("FF_LANES", "lane order drift")
    expected = {lane["id"]: base.oracle.expected(
        rows=corpus["rows"][lane["n"]], field=lane["field"], term=lane["term"],
        k=lane["k"]) for lane in lanes}

    built = {
        "A": build_adapter(root, campaign, "A", BASE_A, None, batched),
        "C": build_adapter(root, campaign, "C", CAUSAL, F_FEATURE, batched),
        "F": build_adapter(root, campaign, "F", F_DIAG, F_FEATURE, batched),
    }
    for arm in built:
        require_sha(built[arm]["source_sha"], f"arm {arm}")
    if len({built[arm]["binary_sha256"] for arm in built}) != 3:
        raise RunBlocked("FF_BINARY", "A, C and F binaries must be distinct")
    probes = {arm: build_score_probe(root, campaign, arm,
                                    {"A": BASE_A, "C": CAUSAL}.get(arm, F_DIAG),
                                    F_FEATURE if arm != "A" else None)["binary"]
              for arm in ARMS}

    arm_data = {
        "A": {"arm": "A", "adapter": built["A"], "feature": None,
              "source_sha": BASE_A, "mode": None},
        "C": {"arm": "C", "adapter": built["C"], "feature": F_FEATURE,
              "source_sha": CAUSAL, "mode": "disabled"},
        "G": {"arm": "G", "adapter": built["F"], "feature": F_FEATURE,
              "source_sha": F_DIAG, "mode": "disabled"},
        "P": {"arm": "P", "adapter": built["F"], "feature": F_FEATURE,
              "source_sha": F_DIAG, "mode": "enabled"},
    }
    layouts, digests, size_data = {}, {}, {}
    for key in ("A", "C", "G", "P"):
        arm_data[key]["metadata"] = base.pr15d_run.read_adapter_metadata(
            "quervant", arm_data[key]["adapter"]["binary"])
    for label, key in (("A", "A"), ("C", "C"), ("F", "G")):
        size_data[label] = size_builds(arm_data[key], corpus, lanes, output,
                                       label=label)
        layouts[label] = size_data[label]["layouts"]
        digests[label] = size_data[label]["digests"]
    for n in ("10000", "100000"):
        baseline = json.dumps(layouts["A"][n], sort_keys=True)
        for key in ("C", "F"):
            if json.dumps(layouts[key][n], sort_keys=True) != baseline:
                raise RunBlocked("FF_FORMAT", f"n{n} {key} layout differs from A")
            if digests[key][n] != digests["A"][n]:
                raise RunBlocked("FF_FORMAT", f"n{n} {key} digest differs from A")
    arm_data["A"]["sizes"] = size_data["A"]
    arm_data["C"]["sizes"] = size_data["C"]
    arm_data["G"]["sizes"] = size_data["F"]
    arm_data["P"]["sizes"] = size_data["F"]

    binary_before = {arm: sha256_file(arm_data[arm]["adapter"]["binary"])
                     for arm in ARMS}
    slots = []
    index = 0
    for block, order in enumerate(SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            index += 1
            context = {
                "binary": arm_data[arm]["adapter"]["binary"],
                "index_dirs": arm_data[arm]["sizes"]["indices"],
                "metadata": arm_data[arm]["metadata"],
                "source_sha": arm_data[arm]["source_sha"],
                "feature": arm_data[arm]["feature"],
                "affinity": affinity,
            }
            record = measure_f_slot(index, arm, context, lanes, expected, output, batched)
            record.update({"block": block, "position": position})
            write_exclusive_json(
                os.path.join(output, "raw", "slots", f"slot-{index:02d}.json"), record)
            slots.append(record)
    binary_after = {arm: sha256_file(arm_data[arm]["adapter"]["binary"])
                    for arm in ARMS}
    if binary_before != binary_after:
        raise RunBlocked("FF_BINARY", "an adapter binary changed during the campaign")
    if binary_after["G"] != binary_after["P"]:
        raise RunBlocked("FF_BINARY", "G and P must share one binary")
    if len({binary_after[arm] for arm in ("A", "C", "G")}) != 3:
        raise RunBlocked("FF_BINARY", "A/C/F binaries must be distinct")

    ratios = derive_f_block_ratios(slots)
    parity = score_parity(probes, output, corpus["rows"], lanes)
    modes = mode_proof(arm_data, lanes, expected)
    symbols = codegen.capture(
        {"A": arm_data["A"]["adapter"]["binary"],
         "C": arm_data["C"]["adapter"]["binary"],
         "D": arm_data["G"]["adapter"]["binary"],
         "E": arm_data["G"]["adapter"]["binary"]},
        os.path.join(ROOT, "target", "pr15i-c", "f-final-codegen",
                     f"diagnostic-{campaign}"))
    checks = f_codegen_checks(symbols)
    observed_samples = sum(len(lane["samples_ns"]) for record in slots
                          for lane in record["lanes"])
    observed_warmups = sum(len(lane["warmup_ids"]) for record in slots
                           for lane in record["lanes"])
    expected_samples = SLOTS * len(LANE_IDS) * (BATCHED if batched else UNBATCHED)
    if observed_samples != expected_samples:
        raise RunBlocked("FF_COUNT", f"sample count {observed_samples}")
    if observed_warmups != SLOTS * len(LANE_IDS) * WARMUPS:
        raise RunBlocked("FF_COUNT", f"warmup count {observed_warmups}")

    protocol_sha = protocol_digest(root)
    measurements = {
        "schema": SCHEMA, "campaign": campaign,
        "regime": "batched" if batched else "unbatched", "ratios": ratios,
        "counts": {"samples": observed_samples, "warmups": observed_warmups,
                   "slots": SLOTS, "lane_slot_records": SLOTS * len(LANE_IDS)},
        "codegen_checks": checks, "diagnostic_only": True,
    }
    write_exclusive_json(os.path.join(output, "raw", "authorization.json"), {
        "schema": SCHEMA, "campaign": campaign, "regime": measurements["regime"],
        "diagnostic_only": True, "idle_authorized_by_user": True,
        "recorded_utc": base.utc_now(), "native_filesystem": filesystem,
        "cpu_affinity": affinity, "arm_sources": {
            "A": BASE_A, "C": CAUSAL, "F": F_DIAG},
        "arm_features": {"A": None, "C": F_FEATURE, "F": F_FEATURE},
        "arm_modes": {arm: arm_mode(arm) for arm in ARMS},
    })
    shutil.copyfile(os.path.join(root, PROTOCOL_REL),
                    os.path.join(output, "raw", "protocol.json"))
    write_exclusive_json(os.path.join(output, "raw", "source-proof.json"), {
        "schema": SCHEMA, **source_report})
    write_exclusive_json(os.path.join(output, "raw", "corpus.json"), {
        "schema": SCHEMA, "manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"]})
    write_exclusive_json(os.path.join(output, "raw", "environment.json"), {
        "schema": SCHEMA, "host_fingerprint": fingerprint,
        "filesystem": filesystem, "environment": environment,
        "cpu_affinity": affinity})
    write_exclusive_json(os.path.join(output, "raw", "toolchain.json"), {
        "schema": SCHEMA,
        "rustc": subprocess.run(["rustc", "-Vv"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo": subprocess.run(["cargo", "-V"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo_lock_sha256": sha256_file(os.path.join(root, "Cargo.lock")),
        "arm_features": {"A": None, "C": F_FEATURE, "F": F_FEATURE},
        "build_commands": {key: built[key]["command"] for key in built},
        "adapter_sha256_before": binary_before,
        "adapter_sha256_after": binary_after,
    })
    write_exclusive_json(os.path.join(output, "raw", "binaries.json"), {
        "schema": SCHEMA,
        "adapters": {arm: {"path": arm_data[arm]["adapter"]["binary"],
                           "sha256": binary_after[arm],
                           "source_sha": arm_data[arm]["source_sha"],
                           "feature": arm_data[arm]["feature"],
                           "mode": arm_mode(arm)} for arm in ARMS},
        "score_probes": {arm: {"path": probes[arm],
                               "sha256": sha256_file(probes[arm])} for arm in ARMS},
    })
    write_exclusive_json(os.path.join(output, "raw", "sizes.json"), {
        "schema": SCHEMA,
        "builds": {key: size_data[key]["builds"] for key in ("A", "C", "F")},
        "layouts": layouts, "segment_digests": digests})
    write_exclusive_json(os.path.join(output, "raw", "score-parity.json"), {
        "schema": SCHEMA, "lanes": parity})
    write_exclusive_json(os.path.join(output, "raw", "mode-proof.json"), {
        "schema": SCHEMA, **modes})
    write_exclusive_json(os.path.join(output, "raw", "codegen.json"), {
        **symbols, "schema": SCHEMA, "payload_schema": symbols.get("schema")})
    write_exclusive_json(os.path.join(output, "raw", "measurements.json"), measurements)
    write_exclusive_json(os.path.join(output, "raw", "manifest.json"), {
        "schema": SCHEMA, "protocol_schema": protocol["schema"],
        "protocol_sha256": protocol_sha, "campaign": campaign,
        "regime": measurements["regime"], "arm_sources": {
            "A": BASE_A, "C": CAUSAL, "F": F_DIAG},
        "arm_features": {"A": None, "C": F_FEATURE, "F": F_FEATURE},
        "arm_modes": {arm: arm_mode(arm) for arm in ARMS},
        "adapter_sha256": binary_after,
        "adapter_path": {arm: arm_data[arm]["adapter"]["binary"] for arm in ARMS},
        "lane_ids": list(LANE_IDS), "arm_order_by_block": list(SCHEDULE),
        "sample_unit": "batch" if batched else "single_query",
        "environment_fingerprint": fingerprint, "filesystem": filesystem,
        "cpu_affinity": affinity, "counts": measurements["counts"],
        "codegen_checks": checks,
        "generic_body_sha256": source_report["generic_body_sha256"],
        "slots_sha256": {f"slots/slot-{index:02d}.json": sha256_file(
            os.path.join(output, "raw", "slots", f"slot-{index:02d}.json"))
            for index in range(1, SLOTS + 1)},
    })
    seal_f_campaign(output)
    print(f"PR15I_C_F campaign={campaign} regime={measurements['regime']} "
          f"samples={observed_samples} warmups={observed_warmups}")
    for lane_id in LANE_IDS:
        entry = ratios[lane_id]
        print(f"  {lane_id}: C/A={entry['medians']['C/A']:.4f} "
              f"G/A={entry['medians']['G/A']:.4f} "
              f"P/A={entry['medians']['P/A']:.4f} "
              f"drift={entry['a_drift_median']:.4f}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C-F diagnostic controller")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--c-sha", required=True)
    parser.add_argument("--f-diag-sha", required=True)
    parser.add_argument("--regime", required=True, choices=("unbatched", "batched"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return execute_f_campaign(args)
    except (RunBlocked, proof.FSourceError) as error:
        rule = getattr(error, "rule", "FF_SOURCE")
        detail = getattr(error, "detail", str(error))
        print(f"FF_BLOCKED: {rule}: {detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

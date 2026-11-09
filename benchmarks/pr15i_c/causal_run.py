#!/usr/bin/env python3
"""PR 15I-C causal experiment — three-arm (A/B/C) measurement controller.

Diagnostic only. Compares the accepted merged PR 15I-B binary (A) with one
candidate binary executed twice through a runtime gate: B = specialized path
enabled, C = the same bytes with the specialized path disabled. B and C must be
the *same* executable path and bytes; they differ only by the allowlisted child
environment variable.

This controller never touches the frozen PR15I-C acceptance protocol or its
two-arm campaign tooling.
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
source_proof = _load("pr15i_c_causal_source_proof",
                     os.path.join(HERE, "causal_source_proof.py"))
base = run.base

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "causal_protocol_v1.json")
PROTOCOL_SCHEMA = "pr15i-c-causal-v1"
SCHEMA = "pr15i-c-causal-campaign-v1"
SEAL_SCHEMA = "pr15i-c-causal-seal-v1"
BASELINE_SHA = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
HISTORICAL_CANDIDATE_SHA = "92a741876f6f6823d9d1792fc391dbb1bbecceb0"
MODE_VARIABLE = "QUERVANT_PR15IC_CAUSAL_MODE"
SOURCE_FEATURE = "pr15ic-causal"
ARM_ORDER_BY_BLOCK = ("ABCCBA", "BCAACB", "CABBAC", "ACBBCA")
BLOCKS = 4
SLOTS_PER_BLOCK = 6
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
NEUTRAL_CEILING = 1.05
NEUTRAL_BLOCK_CEILING = 1.15
CAMPAIGN_IDS = (
    ("causal-unbatched-01", "unbatched"),
    ("causal-batched-01", "batched"),
    ("causal-unbatched-02", "unbatched"),
    ("causal-batched-02", "batched"),
)
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

RunBlocked = run.RunBlocked
write_exclusive_json = run.write_exclusive_json
read_json = run.read_json
sha256_file = run.sha256_file


def protocol_digest(root):
    return sha256_file(os.path.join(root, PROTOCOL_REL))


def load_protocol(root):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise RunBlocked("CA_PROTOCOL", "bad causal protocol schema")
    expected = {
        "baseline_source": BASELINE_SHA,
        "historical_candidate": HISTORICAL_CANDIDATE_SHA,
        "candidate_modes": {"B": "enabled", "C": "disabled"},
        "mode_variable": MODE_VARIABLE,
        "source_feature": SOURCE_FEATURE,
        "unbatched_campaigns": 2,
        "batched_campaigns": 2,
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
        if protocol.get(key) != value:
            raise RunBlocked("CA_PROTOCOL", f"{key} drifted")
    if tuple(protocol.get("arm_order_by_block", ())) != ARM_ORDER_BY_BLOCK:
        raise RunBlocked("CA_PROTOCOL", "arm order drifted")
    for order in protocol["arm_order_by_block"]:
        if len(order) != SLOTS_PER_BLOCK or sorted(order) != sorted("AABBCC"):
            raise RunBlocked("CA_PROTOCOL", f"malformed block order {order!r}")
    if tuple(protocol.get("lane_ids", ())) != LANE_IDS:
        raise RunBlocked("CA_PROTOCOL", "lane set drifted")
    if tuple(protocol.get("primary_lanes", ())) != PRIMARY_LANES:
        raise RunBlocked("CA_PROTOCOL", "primary lanes drifted")
    for flag, value in (("classification_uses_unbatched_only", True),
                        ("batched_is_observational_only", True),
                        ("final_pr15ic_acceptance_changed", False),
                        ("diagnostic_only", True)):
        if protocol.get(flag) is not value:
            raise RunBlocked("CA_PROTOCOL", f"{flag} drifted")
    return protocol


def validate_output(root, out):
    if not os.path.isabs(out):
        raise RunBlocked("CA_PATH", "--out must be absolute")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c",
                                            "causal-campaigns-v1"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("CA_PATH",
                         "output must be under target/pr15i-c/causal-campaigns-v1")
    if os.path.exists(candidate):
        raise RunBlocked("CA_EXISTS", "campaign exists; choose the next unused ID")
    return candidate


def resolve_affinity():
    try:
        allowed = sorted(os.sched_getaffinity(0))
    except AttributeError:  # pragma: no cover - non-Linux
        return {"mode": "UNPINNED", "reason": "platform has no sched_getaffinity"}
    if len(allowed) < 2 or shutil.which("taskset") is None:
        return {"mode": "UNPINNED", "allowed_cpus": allowed}
    probe = subprocess.run(["taskset", "-c", str(allowed[0]), "true"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if probe.returncode != 0:
        raise RunBlocked("CA_AFFINITY", "taskset present but pinning fails")
    return {"mode": "PINNED", "allowed_cpus": allowed,
            "adapter_cpu": allowed[0], "controller_cpu": allowed[1]}


def adapter_command(binary, index_dir, affinity):
    command = [binary, "--index-dir", index_dir]
    if affinity["mode"] == "PINNED":
        return ["taskset", "-c", str(affinity["adapter_cpu"]), *command]
    return command


def child_environment(arm):
    """Child environment for one arm: exactly one allowlisted variable."""
    env = dict(os.environ)
    env.pop(MODE_VARIABLE, None)
    # Deny inherited measurement/RUSTFLAGS interference.
    for key in ("RUSTFLAGS", "RUSTDOCFLAGS", "RUST_LOG", "LLVM_PROFILE_FILE",
                "CARGO_INCREMENTAL", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                "LLVM_COV", "LLVM_PROFILE_DATA"):
        env.pop(key, None)
    if arm == "B":
        env[MODE_VARIABLE] = "enabled"
    elif arm == "C":
        env[MODE_VARIABLE] = "disabled"
    return env


class CausalAdapterProcess:
    """Frozen PR15D adapter transport with an explicit child environment.

    Reproduces `benchmarks/pr15d/harness/run.py::AdapterProcess` exactly, adding
    only the `env=` argument, so the three arms can be selected per process.
    """

    def __init__(self, engine, command, env=None):
        self.engine = engine
        self.command = command
        self.env = env
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )

    def request(self, payload):
        if self.process.stdin is None or self.process.stdout is None:
            raise RunBlocked("CA_PROCESS", "adapter pipes are unavailable")
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        reply = self.process.stdout.readline()
        if not reply:
            stderr = ""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read()
            raise RunBlocked("CA_PROCESS", f"adapter died: {stderr.strip()}")
        try:
            response = json.loads(reply)
        except json.JSONDecodeError as error:
            raise RunBlocked("CA_PROCESS", f"malformed adapter reply: {error}") from error
        if response.get("schema") != "pr15d-adapter-v1":
            raise RunBlocked("CA_PROCESS", "adapter schema mismatch")
        if response.get("engine") != self.engine:
            raise RunBlocked("CA_PROCESS", "adapter engine mismatch")
        if response.get("status") != "ok":
            raise RunBlocked("CA_PROCESS",
                             json.dumps(response.get("error"), sort_keys=True))
        return response

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            self.process.kill()
            self.process.wait(timeout=10)


def build_causal_adapter(source_root, arm_dir):
    """Build the frozen adapter with the experimental causal feature enabled."""
    manifest = os.path.join(source_root, "benchmarks", "pr15d", "adapters",
                            "quervant", "Cargo.toml")
    target_dir = os.path.join(arm_dir, "build")
    os.makedirs(target_dir, exist_ok=True)
    command = [
        "cargo", "build", "--release", "--offline", "--manifest-path", manifest,
        "--features", f"quervant-core/{SOURCE_FEATURE}", "--target-dir", target_dir,
    ]
    result = subprocess.run(command, cwd=os.path.dirname(manifest),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, check=False)
    with open(os.path.join(arm_dir, "build.log"), "w", encoding="utf-8") as handle:
        handle.write(result.stdout)
    if result.returncode != 0:
        raise RunBlocked("CA_BUILD", f"causal adapter build failed: {result.stdout[-2000:]}")
    binary = os.path.join(target_dir, "release", "pr15d-quervant-adapter")
    if not os.path.isfile(binary):
        raise RunBlocked("CA_BUILD", f"causal adapter binary missing: {binary}")
    return {"binary": binary, "binary_sha256": sha256_file(binary),
            "command": command, "source_sha": None}


def build_causal_score_probe(source_root, arm_dir):
    """Build the score probe with the experimental feature (non-timed)."""
    source = os.path.join(source_root, "benchmarks", "pr15i_c", "score_probe")
    destination = os.path.join(arm_dir, "score_probe")
    if os.path.exists(destination):
        shutil.rmtree(destination)
    os.makedirs(destination, exist_ok=True)
    with open(os.path.join(source, "Cargo.toml"), "r", encoding="utf-8") as handle:
        manifest = handle.read()
    manifest = manifest.replace(
        'quervant-core = { path = "../../../crates/quervant-core" }',
        'quervant-core = { path = "%s/crates/quervant-core", features = ["%s"] }'
        % (source_root, SOURCE_FEATURE), 1)
    with open(os.path.join(destination, "Cargo.toml"), "w", encoding="utf-8") as handle:
        handle.write(manifest)
    os.makedirs(os.path.join(destination, "src"), exist_ok=True)
    shutil.copyfile(os.path.join(source, "src", "main.rs"),
                    os.path.join(destination, "src", "main.rs"))
    shutil.copyfile(os.path.join(source, "Cargo.lock"),
                    os.path.join(destination, "Cargo.lock"))
    target_dir = os.path.join(arm_dir, "score_probe_target")
    result = subprocess.run(
        ["cargo", "build", "--release", "--offline", "--manifest-path",
         os.path.join(destination, "Cargo.toml"), "--target-dir", target_dir],
        cwd=destination, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False)
    if result.returncode != 0:
        raise RunBlocked("CA_BUILD", f"score probe build failed: {result.stdout[-2000:]}")
    binary = os.path.join(target_dir, "release", "pr15i-c-score-probe")
    if not os.path.isfile(binary):
        raise RunBlocked("CA_BUILD", f"score probe binary missing: {binary}")
    return {"binary": binary, "binary_sha256": sha256_file(binary),
            "manifest_sha256": sha256_file(os.path.join(destination, "Cargo.toml"))}


def prepare_sources(root, baseline_sha, candidate_sha, campaign):
    for sha in (baseline_sha, candidate_sha):
        if not source_proof.is_commit(root, sha):
            raise RunBlocked("CA_SOURCE", f"{sha} is not a Git commit")
    if not source_proof.is_ancestor(root, baseline_sha, candidate_sha):
        raise RunBlocked("CA_SOURCE", "candidate does not descend from the baseline")
    proof = source_proof.verify_causal_source(root, candidate_sha, baseline_sha)
    a_tree = run._worktree(root, f"causal-{campaign}-A", baseline_sha)
    bc_tree = run._worktree(root, f"causal-{campaign}-BC", candidate_sha)
    a_source = base.resolve_source_tree(a_tree)
    bc_source = base.resolve_source_tree(bc_tree)
    a = run.prepare_arm(root, "A", a_source, os.path.join(
        root, "target", "pr15i-c", "causal-campaigns-v1", campaign))
    bc_adapter = build_causal_adapter(bc_source["tree"],
                                      os.path.join(root, "target", "pr15i-c",
                                                   "causal-campaigns-v1", campaign,
                                                   "setup", "build", "BC"))
    bc_adapter["source_sha"] = bc_source["sha"]
    bc = {
        "arm": "BC",
        "source_sha": bc_source["sha"],
        "adapter": bc_adapter,
        "metadata": base.pr15d_run.read_adapter_metadata("quervant", bc_adapter["binary"]),
    }
    if a["adapter"]["binary_sha256"] == bc["adapter"]["binary_sha256"]:
        raise RunBlocked("CA_BINARY", "A and BC binaries are unexpectedly identical")
    return {"A": a, "BC": bc, "proof": proof,
            "score_probe": build_causal_score_probe(
                bc_source["tree"],
                os.path.join(root, "target", "pr15i-c", "causal-campaigns-v1",
                             campaign, "setup", "build", "BC"))}


def repeat_count_for(lane_id):
    return REPEAT_SHORT if lane_id in SHORT_LANE_IDS else REPEAT_OTHER


def measure_lane_causal(arm, binary, index_dir, lane, expected, metadata, mode,
                        batched, affinity):
    """Measure one lane for one arm with a freshly launched adapter process."""
    env = child_environment(arm)
    command = adapter_command(binary, index_dir, affinity)
    samples = []
    warmup_ids = []
    process = CausalAdapterProcess("quervant", command, env=env)
    try:
        for warmup in range(WARMUPS):
            request_id = f"{arm}:{lane['id']}:warmup:{warmup}"
            response = process.request({
                "request_id": request_id,
                "op": "query",
                "field": lane["field"],
                "term": lane["term"],
                "k": lane["k"],
                "mode": lane["regime"],
            })
            base.pr15d_run.validate_query_response(response, lane, expected)
            warmup_ids.append(request_id)
        if batched:
            repeat = repeat_count_for(lane["id"])
            for sample in range(BATCHED_SAMPLES):
                request_id = f"{arm}:{lane['id']}:batch:{sample}"
                response = process.request({
                    "request_id": request_id,
                    "op": "query_batch",
                    "field": lane["field"],
                    "term": lane["term"],
                    "k": lane["k"],
                    "repeat_count": repeat,
                })
                if request_id != response.get("request_id"):
                    raise RunBlocked("CA_SAMPLE", f"{request_id} id mismatch")
                if "engine_ns" in response:
                    raise RunBlocked("CA_SAMPLE", "batch reply must not carry engine_ns")
                if response.get("repeat_count") != repeat:
                    raise RunBlocked("CA_SAMPLE", f"{request_id} repeat mismatch")
                batch_ns = response.get("batch_ns")
                if isinstance(batch_ns, bool) or not isinstance(batch_ns, int) or batch_ns <= 0:
                    raise RunBlocked("CA_SAMPLE", f"{request_id} invalid batch_ns")
                if response.get("total_hits") != expected["total_hits"]:
                    raise RunBlocked("CA_SAMPLE", f"{request_id} total_hits mismatch")
                if response.get("doc_ids") != expected["doc_ids"]:
                    raise RunBlocked("CA_SAMPLE", f"{request_id} doc_ids mismatch")
                samples.append(batch_ns)
        else:
            for sample in range(UNBATCHED_SAMPLES):
                request_id = f"{arm}:{lane['id']}:sample:{sample}"
                response = process.request({
                    "request_id": request_id,
                    "op": "query",
                    "field": lane["field"],
                    "term": lane["term"],
                    "k": lane["k"],
                    "mode": lane["regime"],
                })
                if request_id != response.get("request_id"):
                    raise RunBlocked("CA_SAMPLE", f"{request_id} id mismatch")
                base.pr15d_run.validate_query_response(response, lane, expected)
                if "batch_ns" in response:
                    raise RunBlocked("CA_SAMPLE", "unbatched reply must not carry batch_ns")
                samples.append(response["engine_ns"])
    finally:
        process.close()
    expected_count = BATCHED_SAMPLES if batched else UNBATCHED_SAMPLES
    if len(samples) != expected_count:
        raise RunBlocked("CA_SAMPLE", f"{lane['id']} collected {len(samples)} samples")
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "k": lane["k"],
        "field": lane["field"],
        "term": lane["term"],
        "regime": lane["regime"],
        "arm": arm,
        "mode": mode,
        "binary_path": binary,
        "binary_sha256": sha256_file(binary),
        "sample_unit": "batch" if batched else "single_query",
        "timing_field": "batch_ns" if batched else "engine_ns",
        "repeat_count": repeat_count_for(lane["id"]) if batched else 1,
        "warmup_ids": warmup_ids,
        "samples_ns": samples,
        "summary_ns": base.pr15d_run.summarize(samples),
        "total_hits": expected["total_hits"],
        "doc_ids": expected["doc_ids"],
        "oracle_ok": True,
        "analyzer": metadata["analyzer"],
    }


def measure_slot_causal(slot, arm, context, lanes, expected, campaign_dir, batched):
    trial_dir = os.path.join(campaign_dir, "setup", "slots")
    before = base.contention_for(
        os.path.join(trial_dir, f"slot-{slot:02d}-{arm}-before.json"))
    base._require_clear(before, f"slot {slot} {arm} before")
    records = []
    for lane in lanes:
        records.append(measure_lane_causal(
            arm, context["binary"], context["index_dirs"][lane["n"]]["dir"], lane,
            expected[lane["id"]], context["metadata"],
            context["mode"], batched, context["affinity"]))
    after = base.contention_for(
        os.path.join(trial_dir, f"slot-{slot:02d}-{arm}-after.json"))
    base._require_clear(after, f"slot {slot} {arm} after")
    return {"slot_index": slot, "arm": arm,
            "started_utc": base.utc_now(), "lanes": records,
            "contention_before": before, "contention_after": after}


def arm_block_means(slots, lane_ids):
    """mean of the two same-arm slot medians per (arm, lane, block)."""
    means = {}
    for lane_id in lane_ids:
        for block in range(1, BLOCKS + 1):
            for arm in ("A", "B", "C"):
                values = [lane["summary_ns"]["median"] for record in slots
                          if record["block"] == block and record["arm"] == arm
                          for lane in record["lanes"] if lane["id"] == lane_id]
                if len(values) != 2:
                    raise RunBlocked("CA_GATE",
                                     f"{lane_id} block {block} arm {arm} slot drift")
                means[(arm, lane_id, block)] = sum(values) / 2
    return means


def derive_causal_ratios(slots, lane_ids):
    means = arm_block_means(slots, lane_ids)
    ratios = {}
    for lane_id in lane_ids:
        entry = {"B/A": [], "C/A": [], "B/C": [], "A/A_drift": []}
        for block in range(1, BLOCKS + 1):
            a = means[("A", lane_id, block)]
            b = means[("B", lane_id, block)]
            c = means[("C", lane_id, block)]
            if a <= 0 or c <= 0:
                raise RunBlocked("CA_GATE", f"{lane_id} block {block} zero denominator")
            entry["B/A"].append(b / a)
            entry["C/A"].append(c / a)
            entry["B/C"].append(b / c)
        entry["campaign_medians"] = {}
        for key in ("B/A", "C/A", "B/C"):
            ordered = sorted(entry[key])
            entry["campaign_medians"][key] = (ordered[1] + ordered[2]) / 2
        ratios[lane_id] = entry
    return ratios


def a_drift_sentinel(slots, lane_ids):
    """Within-block second/first A slot median ratio per lane."""
    drift = {}
    for lane_id in lane_ids:
        values = []
        for block in range(1, BLOCKS + 1):
            a_slots = [record for record in slots
                       if record["block"] == block and record["arm"] == "A"]
            if len(a_slots) != 2:
                raise RunBlocked("CA_GATE", f"{lane_id} block {block} A slot drift")
            medians = []
            for record in a_slots:
                lane = next(item for item in record["lanes"] if item["id"] == lane_id)
                medians.append(lane["summary_ns"]["median"])
            if medians[0] <= 0:
                raise RunBlocked("CA_GATE", f"{lane_id} block {block} zero A median")
            values.append(medians[1] / medians[0])
        ordered = sorted(values)
        drift[lane_id] = {"block_ratios": values,
                          "campaign_median": (ordered[1] + ordered[2]) / 2}
    return drift


def score_parity(score_probe, campaign_dir, corpus_rows, lanes):
    """Exact A/B/C keys, counts and f64 score bits outside the timed window."""
    records = {}
    for lane in lanes:
        expected = base.oracle.expected(rows=corpus_rows[lane["n"]],
                                        field=lane["field"], term=lane["term"],
                                        k=lane["k"])
        per_arm = {}
        for arm in ("A", "B", "C"):
            env = child_environment(arm)
            result = subprocess.run(
                [score_probe, "--index-dir",
                 os.path.join(campaign_dir, "setup", "sizes",
                              "A" if arm == "A" else "BC", f"n{lane['n']}-run3"),
                 "--field", lane["field"], "--term", lane["term"],
                 "--k", str(lane["k"])],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=env, check=False)
            if result.returncode != 0:
                raise RunBlocked("CA_SCORE", f"{lane['id']} {arm}: {result.stderr.strip()}")
            record = json.loads(result.stdout)
            if record.get("schema") != "pr15i-c-score-parity-v1":
                raise RunBlocked("CA_SCORE", f"{lane['id']} {arm} bad schema")
            keys = [hit["key"] for hit in record["hits"]]
            if keys != expected["doc_ids"]:
                raise RunBlocked("CA_SCORE", f"{lane['id']} {arm} key drift")
            if record["total_hits"] != expected["total_hits"]:
                raise RunBlocked("CA_SCORE", f"{lane['id']} {arm} total_hits drift")
            per_arm[arm] = [(hit["key"], hit["score_bits"]) for hit in record["hits"]]
        if not (per_arm["A"] == per_arm["B"] == per_arm["C"]):
            raise RunBlocked("CA_SCORE", f"{lane['id']} score bits differ across arms")
        records[lane["id"]] = {"total_hits": expected["total_hits"],
                               "hits": len(per_arm["A"]),
                               "identical": True}
    return records


def mode_proof(adapter_binary, campaign_dir, lanes, expected):
    """Truth-table probe: mode routing and typed error for invalid modes."""
    proof = {"binary_path": adapter_binary,
             "binary_sha256": sha256_file(adapter_binary),
             "probes": []}
    index_dir = os.path.join(campaign_dir, "setup", "sizes", "BC", "n10000-run3")
    lane = lanes[0]
    request = {"request_id": "mode-probe", "op": "query", "field": lane["field"],
               "term": lane["term"], "k": lane["k"], "mode": lane["regime"]}
    for arm, expected_state in (("A", "ok"), ("B", "ok"), ("C", "ok"),
                                ("INVALID", "error"), ("MISSING", "error")):
        env = child_environment(arm if arm in ("A", "B", "C") else "A")
        if arm == "INVALID":
            env[MODE_VARIABLE] = "invalid-mode"
        elif arm == "MISSING":
            env.pop(MODE_VARIABLE, None)
        process = subprocess.run(
            [adapter_binary, "--index-dir", index_dir],
            input=json.dumps(request) + "\n", stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env, check=False)
        reply = json.loads(process.stdout.strip().splitlines()[-1])
        if expected_state == "ok":
            if reply.get("status") != "ok":
                raise RunBlocked("CA_MODE", f"arm {arm} did not succeed: {reply}")
            if reply.get("total_hits") != expected[lane["id"]]["total_hits"]:
                raise RunBlocked("CA_MODE", f"arm {arm} hit count drift")
        else:
            if reply.get("status") != "error":
                raise RunBlocked("CA_MODE", f"mode {arm} must be a typed error")
            message = json.dumps(reply.get("error", {}))
            if "invalid PR15IC causal experiment mode" not in message:
                raise RunBlocked("CA_MODE", f"mode {arm} wrong error: {message}")
        proof["probes"].append({
            "arm": arm,
            "environment_mode": env.get(MODE_VARIABLE),
            "expected": expected_state,
            "observed_status": reply.get("status"),
        })
    return proof


def build_index_causal(binary, corpus_path, index_dir, expected_rows, env):
    """`pr15d_run.build_index` with an explicit child environment.

    The frozen helper launches the adapter without `env`, which the experimental
    gate rejects (by design). This reproduces its protocol and validations exactly,
    only forwarding the arm environment.
    """
    if os.path.exists(index_dir):
        shutil.rmtree(index_dir)
    os.makedirs(index_dir, exist_ok=True)
    process = CausalAdapterProcess("quervant", [binary], env=env)
    try:
        response = process.request({
            "request_id": f"build:{os.path.basename(index_dir)}",
            "op": "build",
            "corpus_path": corpus_path,
            "index_dir": index_dir,
        })
    finally:
        process.close()
    if response.get("documents_indexed") != expected_rows:
        raise RunBlocked("CA_BUILD", "indexed document count mismatch")
    if response.get("documents_verified") != expected_rows:
        raise RunBlocked("CA_BUILD", "reopened reader verified count mismatch")
    for field in ("index_ns", "commit_ns", "reopen_ns"):
        value = response.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RunBlocked("CA_BUILD", f"invalid {field}")
    measured_bytes = base.pr15d_run.directory_bytes(index_dir)
    if response.get("index_bytes") != measured_bytes:
        raise RunBlocked("CA_BUILD", "adapter index_bytes disagree with disk")
    return {
        "documents_indexed": response["documents_indexed"],
        "documents_verified": response["documents_verified"],
        "index_ns": response["index_ns"],
        "commit_ns": response["commit_ns"],
        "reopen_ns": response["reopen_ns"],
        "index_bytes": measured_bytes,
        "segment_count": response.get("segment_count"),
    }


def oracle_check_causal(binary, index_dir, lane, expected, env):
    process = CausalAdapterProcess("quervant", [binary, "--index-dir", index_dir],
                                   env=env)
    try:
        response = process.request({
            "request_id": f"{lane['id']}:oracle-check",
            "op": "query",
            "field": lane["field"],
            "term": lane["term"],
            "k": lane["k"],
            "mode": lane["regime"],
        })
    finally:
        process.close()
    base.pr15d_run.validate_query_response(response, lane, expected)


def size_builds_causal(arm_data, corpus, lanes, out):
    """Three fresh rebuilds per N with layout/digest determinism and format proof."""
    env = child_environment(arm_data["arm"] if arm_data["arm"] in ("A", "B", "C") else "B")
    canonical = {}
    records = {}
    digests = {}
    for n in (10_000, 100_000):
        lane = next(lane for lane in lanes if lane["n"] == n and lane["class"] == "common")
        expected = base.oracle.expected(rows=corpus["rows"][n], field=lane["field"],
                                        term=lane["term"], k=lane["k"])
        builds = []
        for attempt in (1, 2, 3):
            target = os.path.join(out, "setup", "sizes", arm_data["arm"],
                                  f"n{n}-run{attempt}")
            record = build_index_causal(
                arm_data["adapter"]["binary"],
                os.path.join(corpus["dir"], base.oracle.corpus_filename(n)),
                target, n, env)
            oracle_check_causal(arm_data["adapter"]["binary"], target, lane, expected, env)
            layout = run.measure_layout(target)
            digest = run.segment_digest(target)
            builds.append({"attempt": attempt, "index_ns": record["index_ns"],
                           "commit_ns": record["commit_ns"], "layout": layout,
                           "segment_digest": digest})
        if len({json.dumps(b["layout"], sort_keys=True) for b in builds}) != 1:
            raise RunBlocked("CA_FORMAT", f"{arm_data['arm']} n{n} layout drift")
        if len({b["segment_digest"] for b in builds}) != 1:
            raise RunBlocked("CA_FORMAT", f"{arm_data['arm']} n{n} digest drift")
        canonical[str(n)] = builds[-1]["layout"]
        digests[str(n)] = builds[-1]["segment_digest"]
        records[str(n)] = builds
    for n in ("10000", "100000"):
        layout = canonical[n]
        if layout["stored_version"] != 2 or layout["codec_id"] != 1:
            raise RunBlocked("CA_FORMAT", f"{arm_data['arm']} n{n} is not LZ4 STORED v2")
        if [13, 1] not in layout["required_features"]:
            raise RunBlocked("CA_FORMAT", f"{arm_data['arm']} n{n} lacks feature 0x000D v1")
    return {"layouts": canonical, "digests": digests, "builds": records,
            "indices": {n: {"dir": os.path.join(out, "setup", "sizes",
                                                arm_data["arm"], f"n{n}-run3")}
                        for n in (10_000, 100_000)}}


def execute(args):
    if not args.idle_confirmed:
        print("CA_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    if args.regime not in ("unbatched", "batched"):
        raise RunBlocked("CA_REGIME", "regime must be unbatched or batched")
    root = os.path.realpath(args.checkout_root)
    out = validate_output(root, args.out)
    campaign = os.path.basename(out)
    if (campaign, args.regime) not in CAMPAIGN_IDS:
        raise RunBlocked("CA_NAME", f"unknown campaign id {campaign} for {args.regime}")
    protocol = load_protocol(root)
    batched = args.regime == "batched"
    affinity = resolve_affinity()
    original = None
    if affinity["mode"] == "PINNED":
        try:
            original = os.sched_getaffinity(0)
            os.sched_setaffinity(0, {affinity["controller_cpu"]})
        except OSError as error:
            raise RunBlocked("CA_AFFINITY", f"controller pinning failed: {error}")
    try:
        return _run(root, out, campaign, protocol, affinity, batched, args)
    finally:
        if original is not None:
            try:
                os.sched_setaffinity(0, original)
            except OSError:  # pragma: no cover - best effort
                pass


def _run(root, out, campaign, protocol, affinity, batched, args):
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("CA_LANES", "lane order drift")
    base.verify_frozen_files(root)
    os.makedirs(out)
    os.makedirs(os.path.join(out, "raw"))
    environment = base.pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    filesystem = base.require_native_filesystem(out)
    corpus = base.prepare_corpus(os.path.join(out, "setup"))
    if corpus["manifest_sha256"] != CORPUS_SHA:
        raise RunBlocked("CA_CORPUS", "corpus manifest digest drifted")
    expected = {lane["id"]: base.oracle.expected(
        rows=corpus["rows"][lane["n"]], field=lane["field"],
        term=lane["term"], k=lane["k"]) for lane in lanes}
    prepared = prepare_sources(root, args.baseline_sha, args.candidate_sha, campaign)
    a, bc, proof, probe = prepared["A"], prepared["BC"], prepared["proof"], prepared["score_probe"]

    # The frozen `run.size_builds` launches the adapter without an environment,
    # which the experimental gate rejects by design; use the env-aware equivalent.
    a["sizes"] = size_builds_causal(a, corpus, lanes, out)
    bc["sizes"] = size_builds_causal(bc, corpus, lanes, out)
    for n in ("10000", "100000"):
        if json.dumps(a["sizes"]["layouts"][n], sort_keys=True) != json.dumps(
                bc["sizes"]["layouts"][n], sort_keys=True):
            raise RunBlocked("CA_FORMAT", f"n{n} arm layouts differ")
        if a["sizes"]["digests"][n] != bc["sizes"]["digests"][n]:
            raise RunBlocked("CA_FORMAT", f"n{n} segment digests differ")
    sentinel = a["sizes"]["layouts"]["100000"]
    if (sentinel["committed_index_bytes"] != A_100K_TOTAL
            or sentinel["stored_bytes"] != A_100K_STORED):
        raise RunBlocked("CA_SENTINEL", "100K LZ4 sentinel mismatch")

    a_sha_before = sha256_file(a["adapter"]["binary"])
    bc_sha_before = sha256_file(bc["adapter"]["binary"])
    contexts = {
        "A": {"binary": a["adapter"]["binary"], "index_dirs": a["sizes"]["indices"],
              "metadata": a["metadata"], "mode": None, "affinity": affinity},
        "B": {"binary": bc["adapter"]["binary"], "index_dirs": bc["sizes"]["indices"],
              "metadata": bc["metadata"], "mode": "enabled", "affinity": affinity},
        "C": {"binary": bc["adapter"]["binary"], "index_dirs": bc["sizes"]["indices"],
              "metadata": bc["metadata"], "mode": "disabled", "affinity": affinity},
    }

    slots = []
    slot_index = 0
    for block, order in enumerate(ARM_ORDER_BY_BLOCK, start=1):
        for position, arm in enumerate(order, start=1):
            slot_index += 1
            trial = measure_slot_causal(slot_index, arm, contexts[arm], lanes,
                                        expected, out, batched)
            record = {
                "slot_index": slot_index,
                "block": block,
                "position": position,
                "arm": arm,
                "source_sha": a["source_sha"] if arm == "A" else bc["source_sha"],
                "executed_binary_path": contexts[arm]["binary"],
                "binary_sha256": contexts[arm]["binary_sha256"]
                if "binary_sha256" in contexts[arm]
                else sha256_file(contexts[arm]["binary"]),
                "mode": contexts[arm]["mode"],
                "sample_unit": "batch" if batched else "single_query",
                **trial,
            }
            write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{slot_index:02d}.json"),
                record)
            slots.append(record)

    a_sha_after = sha256_file(a["adapter"]["binary"])
    bc_sha_after = sha256_file(bc["adapter"]["binary"])
    if (a_sha_before != a_sha_after) or (bc_sha_before != bc_sha_after):
        raise RunBlocked("CA_BINARY", "adapter binary changed during the campaign")

    ratios = derive_causal_ratios(slots, LANE_IDS)
    drift = a_drift_sentinel(slots, LANE_IDS)
    parity = score_parity(probe["binary"], out, corpus["rows"], lanes)
    modes = mode_proof(bc["adapter"]["binary"], out, lanes, expected)
    observed_samples = sum(len(lane["samples_ns"]) for record in slots
                           for lane in record["lanes"])
    observed_warmups = sum(len(lane["warmup_ids"]) for record in slots
                           for lane in record["lanes"])
    expected_samples = SLOTS * len(LANE_IDS) * (BATCHED_SAMPLES if batched
                                                else UNBATCHED_SAMPLES)
    if observed_samples != expected_samples:
        raise RunBlocked("CA_COUNT", f"sample count {observed_samples}")
    if observed_warmups != SLOTS * len(LANE_IDS) * WARMUPS:
        raise RunBlocked("CA_COUNT", f"warmup count {observed_warmups}")

    protocol_sha = protocol_digest(root)
    write_exclusive_json(os.path.join(out, "raw", "authorization.json"), {
        "schema": SCHEMA,
        "protocol_schema": protocol["schema"],
        "protocol_sha256": protocol_sha,
        "campaign": campaign,
        "regime": "batched" if batched else "unbatched",
        "diagnostic_only": True,
        "idle_authorized_by_user": True,
        "recorded_utc": base.utc_now(),
        "native_filesystem": filesystem,
        "cpu_affinity": affinity,
        "mode_policy": {"A": None, "B": "enabled", "C": "disabled"},
    })
    write_exclusive_json(os.path.join(out, "raw", "corpus.json"), {
        "schema": SCHEMA, "manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"]})
    write_exclusive_json(os.path.join(out, "raw", "environment.json"), {
        "schema": SCHEMA, "host_fingerprint": fingerprint, "filesystem": filesystem,
        "environment": environment, "cpu_affinity": affinity})
    write_exclusive_json(os.path.join(out, "raw", "toolchain.json"), {
        "schema": SCHEMA,
        "rustc": subprocess.run(["rustc", "--version"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo": subprocess.run(["cargo", "--version"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo_lock_sha256": sha256_file(os.path.join(root, "Cargo.lock")),
        "causal_adapter_command": bc["adapter"]["command"],
        "feature": SOURCE_FEATURE,
        "adapter_sha256": {"A": a_sha_after, "BC": bc_sha_after},
        "adapter_path": {"A": a["adapter"]["binary"], "BC": bc["adapter"]["binary"]},
        "score_probe_sha256": probe["binary_sha256"],
        "score_probe_path": probe["binary"],
    })
    write_exclusive_json(os.path.join(out, "raw", "source_proof.json"), {
        "schema": SCHEMA, **proof, "restored_b_sha": HISTORICAL_CANDIDATE_SHA})
    write_exclusive_json(os.path.join(out, "raw", "mode_proof.json"), {
        "schema": SCHEMA, **modes})
    write_exclusive_json(os.path.join(out, "raw", "sizes.json"), {
        "schema": SCHEMA, "A": a["sizes"]["builds"], "BC": bc["sizes"]["builds"],
        "layouts": {"A": a["sizes"]["layouts"], "BC": bc["sizes"]["layouts"]},
        "segment_digests": {"A": a["sizes"]["digests"], "BC": bc["sizes"]["digests"]}})
    write_exclusive_json(os.path.join(out, "raw", "score_parity.json"), {
        "schema": SCHEMA, "lanes": parity})
    measurements = {
        "schema": SCHEMA,
        "campaign": campaign,
        "regime": "batched" if batched else "unbatched",
        "ratios": ratios,
        "a_drift": drift,
        "counts": {"samples": observed_samples, "warmups": observed_warmups,
                   "slots": SLOTS, "lane_slot_records": SLOTS * len(LANE_IDS)},
        "diagnostic_only": True,
        "classification_uses_unbatched_only": True,
    }
    write_exclusive_json(os.path.join(out, "raw", "measurements.json"), measurements)
    write_exclusive_json(os.path.join(out, "raw", "manifest.json"), {
        "schema": SCHEMA,
        "protocol_schema": protocol["schema"],
        "protocol_sha256": protocol_sha,
        "campaign": campaign,
        "regime": "batched" if batched else "unbatched",
        "baseline_sha": args.baseline_sha,
        "candidate_sha": args.candidate_sha,
        "lane_ids": list(LANE_IDS),
        "arm_order_by_block": list(ARM_ORDER_BY_BLOCK),
        "sample_unit": "batch" if batched else "single_query",
        "adapter_sha256": {"A": a_sha_after, "BC": bc_sha_after},
        "adapter_path": {"A": a["adapter"]["binary"], "BC": bc["adapter"]["binary"]},
        "mode_variable": MODE_VARIABLE,
        "feature": SOURCE_FEATURE,
        "environment_fingerprint": fingerprint,
        "filesystem": filesystem,
        "cpu_affinity": affinity,
        "counts": measurements["counts"],
        "slots_sha256": {
            f"slots/slot-{index:02d}.json": sha256_file(
                os.path.join(out, "raw", "slots", f"slot-{index:02d}.json"))
            for index in range(1, SLOTS + 1)},
    })
    seal_campaign(out, list(REQUIRED_RAW))
    print(f"PR15I_C causal campaign={campaign} regime={measurements['regime']} "
          f"affinity={affinity['mode']} samples={observed_samples} "
          f"warmups={observed_warmups}")
    for lane_id in LANE_IDS:
        entry = ratios[lane_id]
        print(f"  {lane_id}: B/A={entry['campaign_medians']['B/A']:.4f} "
              f"C/A={entry['campaign_medians']['C/A']:.4f} "
              f"B/C={entry['campaign_medians']['B/C']:.4f}")
    return 0


def seal_campaign(out, raw_files):
    files = {}
    for relative in raw_files:
        path = os.path.join(out, "raw", relative)
        if not os.path.isfile(path):
            raise RunBlocked("CA_SEAL", f"missing raw file {relative}")
        files[relative] = sha256_file(path)
    write_exclusive_json(os.path.join(out, "raw", "seal.json"), {
        "schema": SEAL_SCHEMA, "files": files})


def build_parser():
    parser = argparse.ArgumentParser(
        description="PR 15I-C three-arm causal attribution controller")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--regime", required=True, choices=("unbatched", "batched"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return execute(args)
    except (RunBlocked, source_proof.SourceProofError) as error:
        rule = getattr(error, "rule", "CA_SOURCE")
        detail = getattr(error, "detail", str(error))
        print(f"CA_BLOCKED: {rule}: {detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

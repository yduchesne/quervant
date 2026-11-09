#!/usr/bin/env python3
"""PR 15I-C — batched short-query noise controller (diagnostic only).

Protocol `pr15i-c-batched-noise-v1`. Compares two labelled arms on seven frozen
PR15D warm lanes over eight paired blocks. Every measured observation is one
*complete timed batch*: an outer Rust `Instant` interval enclosing `repeat_count`
(100 for absent/rare lanes, 1 for common control lanes) sequential real Quervant
searches on the session's single snapshot.

This is a diagnostic study. It never replaces the frozen unbatched PR15I-C
acceptance contract in `benchmarks/pr15i_c/protocol.json`.
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
layout = _load("pr15i_c_layout_diag", os.path.join(HERE, "layout_diag.py"))
patcher = _load("pr15i_c_batched_adapter_patch",
                os.path.join(HERE, "batched_adapter_patch.py"))
base = run.base

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "batched_protocol_v1.json")
PROTOCOL_SCHEMA = "pr15i-c-batched-noise-v1"
SCHEMA = "pr15i-c-batched-campaign-v1"
SEAL_SCHEMA = "pr15i-c-batched-seal-v1"
BASELINE_SHA = "6f6463cb26bcf28340cc9d4afd4dfeb040281898"
GENERIC_CONTROL_SHA = "50b56e9fe7b22bb266ca7b0d9e209500dfc785ff"
FROZEN_MAIN_SHA = "42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63"
LANE_IDS = layout.LANE_IDS
SHORT_LANE_IDS = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
)
BLOCK_ORDERS = layout.BLOCK_ORDERS
BLOCKS = layout.BLOCKS
SLOTS = layout.SLOTS
WARMUPS = 5
MEASURED_BATCHES = 10
REPEAT_SHORT = 100
REPEAT_CONTROL = 1
SHORT_LANE_FLOOR_NS = 1_000_000
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
MEASURED_BATCHES_PER_CAMPAIGN = SLOTS * len(LANE_IDS) * MEASURED_BATCHES
WARMUPS_PER_CAMPAIGN = SLOTS * len(LANE_IDS) * WARMUPS
SEARCH_CALLS_PER_CAMPAIGN = (
    SLOTS * MEASURED_BATCHES * (len(SHORT_LANE_IDS) * REPEAT_SHORT
                                + (len(LANE_IDS) - len(SHORT_LANE_IDS)) * REPEAT_CONTROL)
    + WARMUPS_PER_CAMPAIGN
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

RunBlocked = run.RunBlocked
write_exclusive_json = run.write_exclusive_json
read_json = run.read_json
sha256_file = run.sha256_file


def protocol_digest(root):
    return sha256_file(os.path.join(root, PROTOCOL_REL))


def load_protocol(root):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise RunBlocked("B_PROTOCOL", "bad batched protocol schema")
    checks = {
        "baseline_source": BASELINE_SHA,
        "generic_control_source": GENERIC_CONTROL_SHA,
        "frozen_adapter_main_rs_sha256": FROZEN_MAIN_SHA,
        "valid_campaigns_per_type": 4,
        "repeat_count_short": REPEAT_SHORT,
        "repeat_count_control": REPEAT_CONTROL,
        "warmups": WARMUPS,
        "measured_batches_per_lane_slot": MEASURED_BATCHES,
        "block_count": BLOCKS,
        "slots_per_campaign": SLOTS,
        "measured_batches_per_campaign": MEASURED_BATCHES_PER_CAMPAIGN,
        "warmups_per_campaign": WARMUPS_PER_CAMPAIGN,
        "search_calls_per_campaign": SEARCH_CALLS_PER_CAMPAIGN,
        "fresh_builds_per_arm_per_n": 3,
        "short_lane_slot_median_floor_ns": SHORT_LANE_FLOOR_NS,
        "AA_aggregate_median_min": AA_AGG_MIN,
        "AA_aggregate_median_max": AA_AGG_MAX,
        "AA_campaign_median_min": AA_CAMPAIGN_MIN,
        "AA_campaign_median_max": AA_CAMPAIGN_MAX,
        "AA_campaign_median_hard_min": AA_HARD_MIN,
        "AA_campaign_median_hard_max": AA_HARD_MAX,
        "AA_campaigns_in_band_min": AA_CAMPAIGNS_IN_BAND_MIN,
        "AG_aggregate_median_max": AG_AGG_MAX,
        "AG_campaign_median_max": AG_CAMPAIGN_MAX,
        "AG_runs_at_or_below_1_05_min": AG_RUNS_AT_OR_BELOW_MIN,
        "timing_basis": "outer_Rust_Instant_full_batch",
        "sample_unit": "batch",
    }
    for key, expected in checks.items():
        if protocol.get(key) != expected:
            raise RunBlocked("B_PROTOCOL", f"{key} drifted")
    if tuple(protocol.get("lane_ids", [])) != LANE_IDS:
        raise RunBlocked("B_PROTOCOL", "lane set drifted")
    if tuple(protocol.get("short_lane_ids", [])) != SHORT_LANE_IDS:
        raise RunBlocked("B_PROTOCOL", "short lane set drifted")
    if tuple(protocol.get("block_orders", [])) != tuple("".join(o) for o in BLOCK_ORDERS):
        raise RunBlocked("B_PROTOCOL", "block order drifted")
    if tuple(protocol.get("series_order", [])) != (
            "aa-01", "ag-01", "aa-02", "ag-02",
            "aa-03", "ag-03", "aa-04", "ag-04"):
        raise RunBlocked("B_PROTOCOL", "series order drifted")
    for flag in ("release_profile", "same_compiler_and_flags",
                 "AA_required_identical_executable_bytes",
                 "diagnostic_per_block_1_15_is_observation_only",
                 "final_pr15ic_gate_unchanged"):
        if protocol.get(flag) is not True:
            raise RunBlocked("B_PROTOCOL", f"{flag} must be true")
    return protocol


def validate_out(root, out):
    if not os.path.isabs(out):
        raise RunBlocked("B_PATH", "--out must be absolute")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "batched-noise-v1"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("B_PATH", "output must be under target/pr15i-c/batched-noise-v1")
    if os.path.exists(candidate):
        raise RunBlocked("B_EXISTS", "campaign output exists; choose the next unused ID")
    return candidate


def verify_sources(root, mode, baseline_sha, control_sha):
    for sha in (baseline_sha, control_sha):
        if run._git(root, "cat-file", "-t", sha) != "commit":
            raise RunBlocked("B_SOURCE", f"{sha} is not a commit")
    if mode == "aa":
        if baseline_sha != control_sha or baseline_sha != BASELINE_SHA:
            raise RunBlocked("B_SOURCE", "A/A requires one identical merged baseline source")
    else:
        if baseline_sha != BASELINE_SHA or control_sha != GENERIC_CONTROL_SHA:
            raise RunBlocked("B_SOURCE", "A/G must use merged A and the historical G")
        code = subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor",
                               baseline_sha, control_sha], check=False).returncode
        if code != 0:
            raise RunBlocked("B_SOURCE", "G does not descend from A")
        changed = [
            path for path in run.scope_paths(root, baseline_sha, control_sha)
            if path.startswith("crates/")
            and not path.startswith("crates/quervant-core/tests/")
            and not path.startswith("crates/quervant-core/benches/")
        ]
        if changed != ["crates/quervant-core/src/search/unified.rs"]:
            raise RunBlocked("B_SOURCE", f"G production diff is not one file: {changed}")
    frozen = patcher.frozen_source(root)
    if patcher.sha256_bytes(frozen.encode("utf-8")) != FROZEN_MAIN_SHA:
        raise RunBlocked("B_ADAPTER", "frozen adapter source hash drifted")
    return {"frozen_main_sha256": FROZEN_MAIN_SHA}


def resolve_affinity():
    """Predeclare the CPU affinity mode once for the whole series."""
    try:
        allowed = sorted(os.sched_getaffinity(0))
    except AttributeError:  # pragma: no cover - non-Linux
        return {"mode": "NO_AFFINITY", "reason": "platform has no sched_getaffinity"}
    if len(allowed) < 2 or shutil.which("taskset") is None:
        return {"mode": "NO_AFFINITY", "allowed_cpus": allowed,
                "reason": "fewer than two allowed CPUs or taskset missing"}
    adapter_cpu = allowed[0]
    controller_cpu = allowed[1]
    probe = subprocess.run(["taskset", "-c", str(adapter_cpu), "true"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if probe.returncode != 0:
        raise RunBlocked("B_AFFINITY", "taskset present but pinning fails")
    return {
        "mode": "PINNED",
        "allowed_cpus": allowed,
        "adapter_cpu": adapter_cpu,
        "controller_cpu": controller_cpu,
    }


def frequency_observation():
    """Read CPU scaling/frequency facts as observations only (never modified)."""
    observation = {"governor": None, "scaling_cur_freq_khz": None}
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor",
                  "r", encoding="utf-8") as handle:
            observation["governor"] = handle.read().strip()
    except OSError:
        observation["governor"] = "UNAVAILABLE"
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
                  "r", encoding="utf-8") as handle:
            observation["scaling_cur_freq_khz"] = int(handle.read().strip())
    except (OSError, ValueError):
        observation["scaling_cur_freq_khz"] = "UNAVAILABLE"
    return observation


def repeat_count_for(lane_id):
    return REPEAT_SHORT if lane_id in SHORT_LANE_IDS else REPEAT_CONTROL


def adapter_command(binary, index_dir, affinity):
    command = [binary, "--index-dir", index_dir]
    if affinity["mode"] == "PINNED":
        return ["taskset", "-c", str(affinity["adapter_cpu"]), *command]
    return command


def validate_batch_response(response, lane, expected, repeat_count, request_id):
    if response.get("request_id") != request_id:
        raise RunBlocked("B_SAMPLE", f"{request_id} request id mismatch")
    if "engine_ns" in response:
        raise RunBlocked("B_SAMPLE", f"{request_id} batch reply must not contain engine_ns")
    if response.get("repeat_count") != repeat_count:
        raise RunBlocked("B_SAMPLE", f"{request_id} repeat_count mismatch")
    batch_ns = response.get("batch_ns")
    if isinstance(batch_ns, bool) or not isinstance(batch_ns, int) or batch_ns <= 0:
        raise RunBlocked("B_SAMPLE", f"{request_id} batch_ns must be a positive integer")
    if response.get("total_hits") != expected["total_hits"]:
        raise RunBlocked("B_SAMPLE", f"{request_id} total_hits mismatch")
    if response.get("doc_ids") != expected["doc_ids"]:
        raise RunBlocked("B_SAMPLE", f"{request_id} doc_ids mismatch")
    return batch_ns


def measure_lane_batch(binary, index_dir, lane, expected, metadata, contention, affinity):
    repeat_count = repeat_count_for(lane["id"])
    command = adapter_command(binary, index_dir, affinity)
    batches = []
    warmup_ids = []
    process = base.pr15d_run.AdapterProcess("quervant", command)
    try:
        for warmup in range(WARMUPS):
            request_id = f"{lane['id']}:warmup:{warmup}"
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
        for sample in range(MEASURED_BATCHES):
            request_id = f"{lane['id']}:batch:{sample}"
            response = process.request({
                "request_id": request_id,
                "op": "query_batch",
                "field": lane["field"],
                "term": lane["term"],
                "k": lane["k"],
                "repeat_count": repeat_count,
            })
            batches.append(validate_batch_response(
                response, lane, expected, repeat_count, request_id))
    finally:
        process.close()
    if len(batches) != MEASURED_BATCHES:
        raise RunBlocked("B_SAMPLE", f"{lane['id']} collected {len(batches)} batches")
    summary = base.pr15d_run.summarize(batches)
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "k": lane["k"],
        "field": lane["field"],
        "term": lane["term"],
        "regime": lane["regime"],
        "sample_unit": "batch",
        "timing_basis": "outer_Rust_Instant_full_batch",
        "repeat_count": repeat_count,
        "batch_count": MEASURED_BATCHES,
        "warmup_count": WARMUPS,
        "search_count": MEASURED_BATCHES * repeat_count + WARMUPS,
        "warmup_ids": warmup_ids,
        "raw_batch_ns": batches,
        "summary_ns": summary,
        "mean_per_query_ns": summary["median"] / repeat_count,
        "total_hits": expected["total_hits"],
        "doc_ids": expected["doc_ids"],
        "oracle_ok": True,
        "analyzer": metadata["analyzer"],
        "contention": contention,
    }


def measure_slot_batch(slot_index, binary, lanes, index_dirs, expected, metadata, out,
                       affinity):
    trial_dir = os.path.join(out, "setup", "slots")
    before = base.contention_for(os.path.join(trial_dir, f"slot-{slot_index:02d}-before.json"))
    base._require_clear(before, f"slot {slot_index} before")
    records = []
    for lane in lanes:
        records.append(measure_lane_batch(
            binary, index_dirs[lane["n"]]["dir"], lane, expected[lane["id"]],
            metadata, before, affinity))
    after = base.contention_for(os.path.join(trial_dir, f"slot-{slot_index:02d}-after.json"))
    base._require_clear(after, f"slot {slot_index} after")
    return {
        "slot_index": slot_index,
        "started_utc": base.utc_now(),
        "lanes": records,
        "contention_before": before,
        "contention_after": after,
    }


def build_arms(root, mode, baseline_sha, control_sha, out):
    tag = os.path.basename(out)
    a_source = base.resolve_source_tree(
        run._worktree(root, f"batched-v1-{tag}-a", baseline_sha))
    a_adapter = patcher.prepare_derived_adapter(
        root, out, "A", os.path.join(a_source["tree"], "crates", "quervant-core"))
    a = {
        "arm": "A",
        "source_sha": a_source["sha"],
        "adapter": a_adapter,
        "metadata": base.pr15d_run.read_adapter_metadata("quervant", a_adapter["binary"]),
    }
    if mode == "aa":
        b = {
            "arm": "B",
            "source_sha": a["source_sha"],
            "adapter": dict(a_adapter),
            "metadata": a["metadata"],
            "shared_executable": True,
        }
    else:
        g_source = base.resolve_source_tree(
            run._worktree(root, f"batched-v1-{tag}-g", control_sha))
        g_adapter = patcher.prepare_derived_adapter(
            root, out, "B", os.path.join(g_source["tree"], "crates", "quervant-core"))
        b = {
            "arm": "B",
            "source_sha": g_source["sha"],
            "adapter": g_adapter,
            "metadata": base.pr15d_run.read_adapter_metadata("quervant", g_adapter["binary"]),
        }
    return a, b


def campaign_ratios(slots):
    """Per-lane eight block ratios, raw batch descriptors and the duration floor."""
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
            if len(a_values) != 2 or len(b_values) != 2:
                raise RunBlocked("B_GATE", f"{lane_id} block {block} sample drift")
            a_mean = sum(a_values) / 2
            b_mean = sum(b_values) / 2
            if a_mean <= 0:
                raise RunBlocked("B_GATE", f"{lane_id} block {block} zero denominator")
            per_block.append(b_mean / a_mean)
        ordered = sorted(per_block)
        floor_ok = True
        if lane_id in SHORT_LANE_IDS:
            floor_ok = (min(a_slot_medians) >= SHORT_LANE_FLOOR_NS
                        and min(b_slot_medians) >= SHORT_LANE_FLOOR_NS)
        ratios[lane_id] = {
            "block_ratios": per_block,
            "campaign_median": (ordered[3] + ordered[4]) / 2,
            "outliers_above_1_15": sum(1 for v in per_block if v > PER_BLOCK_OBSERVATION),
            "outliers_below_inverse_1_15": sum(
                1 for v in per_block if v < 1.0 / PER_BLOCK_OBSERVATION),
            "a_slot_median_batch_ns": a_slot_medians,
            "b_slot_median_batch_ns": b_slot_medians,
            "min_slot_median_batch_ns": min(a_slot_medians + b_slot_medians),
            "short_lane_duration_ok": floor_ok,
            "repeat_count": repeat_count_for(lane_id),
        }
    return ratios


def derive(ratios, mode, proof):
    medians = {lane: value["campaign_median"] for lane, value in ratios.items()}
    duration_ok = all(value["short_lane_duration_ok"] for value in ratios.values())
    if not duration_ok:
        decision = "BATCH_DURATION_BLOCKED"
    elif mode == "aa":
        ok = all(AA_AGG_MIN <= value <= AA_AGG_MAX for value in medians.values())
        decision = "AA_CAMPAIGN_QUALIFIED" if ok else "AA_CAMPAIGN_UNSTABLE"
    else:
        ok = all(value <= AG_CAMPAIGN_MAX for value in medians.values())
        decision = "AG_CAMPAIGN_OBSERVED" if ok else "AG_CAMPAIGN_DRIFT"
    return {
        "schema": SCHEMA,
        "mode": mode,
        "campaign_medians": medians,
        "ratios": ratios,
        "decision": decision,
        "short_lane_duration_ok": duration_ok,
        "per_block_observation_only": PER_BLOCK_OBSERVATION,
        "frozen_main_sha256": proof["frozen_main_sha256"],
    }


def execute(args):
    if not args.idle_confirmed:
        print("B_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    if args.mode not in ("aa", "ag"):
        raise RunBlocked("B_MODE", "mode must be aa or ag")
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    protocol = load_protocol(root)
    proof = verify_sources(root, args.mode, args.baseline_sha, args.control_sha)
    base.verify_frozen_files(root)
    affinity = resolve_affinity()
    original_affinity = None
    if affinity["mode"] == "PINNED":
        try:
            original_affinity = os.sched_getaffinity(0)
            os.sched_setaffinity(0, {affinity["controller_cpu"]})
        except OSError as error:
            raise RunBlocked("B_AFFINITY", f"controller pinning failed: {error}")
    try:
        return _run(root, out, protocol, proof, affinity, args)
    finally:
        if original_affinity is not None:
            try:
                os.sched_setaffinity(0, original_affinity)
            except OSError:  # pragma: no cover - best effort restore
                pass


def _run(root, out, protocol, proof, affinity, args):
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("B_LANES", "lane order drift")

    os.makedirs(out)
    os.makedirs(os.path.join(out, "raw"))
    environment = base.pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    filesystem = base.require_native_filesystem(out)
    corpus = base.prepare_corpus(os.path.join(out, "setup"))
    expected = {
        lane["id"]: base.oracle.expected(
            rows=corpus["rows"][lane["n"]], field=lane["field"],
            term=lane["term"], k=lane["k"])
        for lane in lanes
    }
    protocol_sha = protocol_digest(root)
    frequency_before = frequency_observation()
    write_exclusive_json(os.path.join(out, "raw", "authorization.json"), {
        "schema": SCHEMA,
        "protocol_schema": protocol["schema"],
        "protocol_sha256": protocol_sha,
        "mode": args.mode,
        "diagnostic_only": True,
        "idle_authorized_by_user": True,
        "recorded_utc": base.utc_now(),
        "native_filesystem": filesystem,
        "lane_ids": list(LANE_IDS),
        "short_lane_ids": list(SHORT_LANE_IDS),
        "repeat_count_short": REPEAT_SHORT,
        "repeat_count_control": REPEAT_CONTROL,
        "warmups_per_lane_slot": WARMUPS,
        "measured_batches_per_lane_slot": MEASURED_BATCHES,
        "slots": SLOTS,
        "timing_basis": "outer_Rust_Instant_full_batch",
        "sample_unit": "batch",
        "cpu_affinity": affinity,
        "frequency_before": frequency_before,
    })
    write_exclusive_json(os.path.join(out, "raw", "corpus.json"), {
        "schema": SCHEMA,
        "manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
    })

    a, b = build_arms(root, args.mode, args.baseline_sha, args.control_sha, out)
    a["sizes"] = run.size_builds(a, corpus, lanes, out)
    b["sizes"] = run.size_builds(b, corpus, lanes, out)
    if args.mode == "aa":
        if a["adapter"]["binary"] != b["adapter"]["binary"]:
            raise RunBlocked("B_AA_BINARY", "A/A arms must execute the same file")
        if a["adapter"]["binary_sha256"] != b["adapter"]["binary_sha256"]:
            raise RunBlocked("B_AA_BINARY", "A/A arms must execute identical bytes")
    for n in ("10000", "100000"):
        if json.dumps(a["sizes"]["layouts"][n], sort_keys=True) != json.dumps(
                b["sizes"]["layouts"][n], sort_keys=True):
            raise RunBlocked("B_FORMAT", f"n{n} arm layouts differ")
        if a["sizes"]["digests"][n] != b["sizes"]["digests"][n]:
            raise RunBlocked("B_FORMAT", f"n{n} arm segment digests differ")
    sentinel = a["sizes"]["layouts"]["100000"]
    if (sentinel["committed_index_bytes"] != run.A_100K_TOTAL
            or sentinel["stored_bytes"] != run.A_100K_STORED):
        raise RunBlocked("B_SENTINEL", "100K LZ4 sentinel mismatch")

    slots = []
    slot_index = 0
    for block, order in enumerate(BLOCK_ORDERS, start=1):
        for position, letter in enumerate(order, start=1):
            slot_index += 1
            data = a if letter == "A" else b
            trial = measure_slot_batch(
                slot_index, data["adapter"]["binary"], lanes,
                data["sizes"]["indices"], expected, data["metadata"], out, affinity)
            record = {
                "slot_index": slot_index,
                "block": block,
                "position": position,
                "arm": letter,
                "source_sha": data["source_sha"],
                "executed_binary_path": data["adapter"]["binary"],
                "binary_sha256": data["adapter"]["binary_sha256"],
                "derived_main_sha256": data["adapter"]["derived_main_sha256"],
                "trial": trial,
            }
            write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{slot_index:02d}.json"), record)
            slots.append(record)

    for arm_data in (a, b):
        current = sha256_file(arm_data["adapter"]["binary"])
        if current != arm_data["adapter"]["binary_sha256"]:
            raise RunBlocked("B_AA_BINARY", "derived adapter binary changed during the campaign")

    ratios = campaign_ratios(slots)
    report = derive(ratios, args.mode, proof)
    observed_batches = sum(len(lane["raw_batch_ns"]) for record in slots
                           for lane in record["trial"]["lanes"])
    observed_warmups = sum(lane["warmup_count"] for record in slots
                           for lane in record["trial"]["lanes"])
    observed_searches = sum(lane["search_count"] for record in slots
                            for lane in record["trial"]["lanes"])
    if observed_batches != MEASURED_BATCHES_PER_CAMPAIGN:
        raise RunBlocked("B_COUNT", f"batch count {observed_batches}")
    if observed_warmups != WARMUPS_PER_CAMPAIGN:
        raise RunBlocked("B_COUNT", f"warmup count {observed_warmups}")
    if observed_searches != SEARCH_CALLS_PER_CAMPAIGN:
        raise RunBlocked("B_COUNT", f"search count {observed_searches}")
    report["sources"] = {"A": a["source_sha"], "B": b["source_sha"]}
    report["executed_binary"] = {
        "A": {"path": a["adapter"]["binary"], "sha256": a["adapter"]["binary_sha256"]},
        "B": {"path": b["adapter"]["binary"], "sha256": b["adapter"]["binary_sha256"]},
    }
    report["identical_executable"] = args.mode == "aa"
    report["adapter_patch"] = {
        "frozen_main_sha256": FROZEN_MAIN_SHA,
        "A": {key: a["adapter"][key] for key in
              ("derived_main_sha256", "frozen_function_sha256",
               "derived_manifest_sha256")},
        "B": {key: b["adapter"][key] for key in
              ("derived_main_sha256", "frozen_function_sha256",
               "derived_manifest_sha256")},
    }
    report["cpu_affinity"] = affinity
    report["frequency_after"] = frequency_observation()
    report["environment_fingerprint"] = fingerprint
    report["protocol_sha256"] = protocol_sha
    report["corpus_manifest_sha256"] = corpus["manifest_sha256"]
    report["counts"] = {
        "measured_batches": observed_batches,
        "warmups": observed_warmups,
        "search_calls": observed_searches,
    }
    report["layouts"] = {"A": a["sizes"]["layouts"], "B": b["sizes"]["layouts"]}
    report["segment_digests"] = {"A": a["sizes"]["digests"], "B": b["sizes"]["digests"]}
    write_exclusive_json(os.path.join(out, "raw", "sizes.json"), {
        "schema": SCHEMA,
        "A": a["sizes"]["builds"],
        "B": b["sizes"]["builds"],
        "layouts": report["layouts"],
        "segment_digests": report["segment_digests"],
    })
    write_exclusive_json(os.path.join(out, "raw", "measurements.json"), report)
    write_exclusive_json(os.path.join(out, "raw", "toolchain.json"), {
        "schema": SCHEMA,
        "rustc": subprocess.run(["rustc", "--version"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo": subprocess.run(["cargo", "--version"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo_lock_sha256": sha256_file(os.path.join(root, "Cargo.lock")),
        "frozen_main_sha256": FROZEN_MAIN_SHA,
        "executed_binary_sha256": report["executed_binary"],
        "cpu_affinity": affinity,
    })
    write_exclusive_json(os.path.join(out, "raw", "environment.json"), {
        "schema": SCHEMA,
        "host_fingerprint": fingerprint,
        "filesystem": filesystem,
        "environment": environment,
        "cpu_affinity": affinity,
    })
    write_exclusive_json(os.path.join(out, "raw", "manifest.json"), {
        "schema": SCHEMA,
        "protocol_schema": protocol["schema"],
        "protocol_sha256": protocol_sha,
        "mode": args.mode,
        "A_sha": args.baseline_sha,
        "B_sha": args.control_sha,
        "identical_executable": args.mode == "aa",
        "executed_binary": report["executed_binary"],
        "adapter_patch": report["adapter_patch"],
        "frozen_main_sha256": FROZEN_MAIN_SHA,
        "lane_ids": list(LANE_IDS),
        "short_lane_ids": list(SHORT_LANE_IDS),
        "block_orders": ["".join(order) for order in BLOCK_ORDERS],
        "warmups": WARMUPS,
        "measured_batches": MEASURED_BATCHES,
        "repeat_count_short": REPEAT_SHORT,
        "repeat_count_control": REPEAT_CONTROL,
        "slots": SLOTS,
        "sample_unit": "batch",
        "timing_basis": "outer_Rust_Instant_full_batch",
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "environment_fingerprint": fingerprint,
        "filesystem": filesystem,
        "cpu_affinity": affinity,
        "counts": report["counts"],
        "slots_sha256": {
            f"slots/slot-{index:02d}.json": sha256_file(
                os.path.join(out, "raw", "slots", f"slot-{index:02d}.json"))
            for index in range(1, SLOTS + 1)
        },
    })
    seal = {
        "schema": SEAL_SCHEMA,
        "files": {
            relative: sha256_file(os.path.join(out, "raw", relative))
            for relative in REQUIRED_RAW
        },
    }
    write_exclusive_json(os.path.join(out, "raw", "seal.json"), seal)
    print(f"PR15I_C batched noise mode={args.mode} decision={report['decision']}")
    print(f"  affinity={affinity['mode']} counts={report['counts']}")
    for lane_id in LANE_IDS:
        value = ratios[lane_id]
        print(f"  {lane_id}: median={value['campaign_median']:.6f} "
              f"repeat={value['repeat_count']} "
              f"outliers>1.15={value['outliers_above_1_15']} "
              f"floor_ok={value['short_lane_duration_ok']}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C batched noise diagnostic")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--mode", required=True, choices=("aa", "ag"))
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--control-sha", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return execute(args)
    except (RunBlocked, patcher.PatchError) as error:
        rule = getattr(error, "rule", "B_ADAPTER")
        detail = getattr(error, "detail", str(error))
        print(f"B_BLOCKED: {rule}: {detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

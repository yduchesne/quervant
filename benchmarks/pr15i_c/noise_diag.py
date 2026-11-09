#!/usr/bin/env python3
"""PR 15I-C follow-up — prospective A/A and A/G measurement-noise controller.

This is a **diagnostic-only** protocol (`pr15i-c-noise-v1`). It never changes,
replaces or waives the frozen PR15I-C acceptance contract in
`benchmarks/pr15i_c/protocol.json`.

Two study types share one fixed schedule (7 frozen PR15D warm lanes, 8 paired
blocks, 5 warmups plus 10 measured samples per lane per slot, 32 slots):

* `aa` — both logical arms execute the **same** release adapter executable bytes
  (source-neutral A/A). Any measured difference is schedule/OS variance.
* `ag` — arm A is merged PR 15I-B and arm B is the historical F0 generic-boundary
  control `50b56e9…` (only a `#[inline(never)]` on `collect_mixed`).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
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
source_proof = _load("pr15i_c_source_proof", os.path.join(HERE, "source_proof.py"))
base = run.base

PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "noise_protocol_v2.json")
PROTOCOL_SCHEMA = "pr15i-c-noise-v2"
SCHEMA = "pr15i-c-noise-campaign-v2"
SEAL_SCHEMA = "pr15i-c-noise-seal-v2"
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
CAMPAIGN_IDS = ("aa-01", "ag-01", "aa-02", "ag-02", "aa-03", "ag-03", "aa-04", "ag-04")
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
        raise RunBlocked("N_PROTOCOL", "bad noise protocol schema")
    if protocol.get("baseline_source") != BASELINE_SHA:
        raise RunBlocked("N_PROTOCOL", "baseline source drifted")
    if protocol.get("generic_control_source") != GENERIC_CONTROL_SHA:
        raise RunBlocked("N_PROTOCOL", "generic control source drifted")
    if tuple(protocol.get("lane_ids", [])) != LANE_IDS:
        raise RunBlocked("N_PROTOCOL", "lane set drifted")
    if tuple(protocol.get("block_orders", [])) != tuple("".join(o) for o in BLOCK_ORDERS):
        raise RunBlocked("N_PROTOCOL", "block order drifted")
    for key, expected in (
        ("valid_campaigns_per_type", 4),
        ("warmups", WARMUPS),
        ("measured_per_lane_slot", MEASURED),
        ("block_count", BLOCKS),
        ("slots_per_campaign", SLOTS),
        ("AA_noise_median_per_campaign_min", AA_CAMPAIGN_MEDIAN_MIN),
        ("AA_noise_median_per_campaign_max", AA_CAMPAIGN_MEDIAN_MAX),
        ("AA_aggregate_median_min", AA_AGGREGATE_MIN),
        ("AA_aggregate_median_max", AA_AGGREGATE_MAX),
        ("AG_aggregate_median_max", AG_AGGREGATE_MAX),
        ("AG_each_campaign_median_max", AG_CAMPAIGN_MEDIAN_MAX),
        ("AG_runs_per_lane_at_or_below_1_05_min", AG_RUNS_AT_OR_BELOW_MIN),
    ):
        if protocol.get(key) != expected:
            raise RunBlocked("N_PROTOCOL", f"{key} drifted")
    for flag in ("release_profile", "same_compiler_and_flags",
                 "AA_required_identical_executable_bytes",
                 "diagnostic_per_block_1_15_is_observation_only",
                 "final_pr15ic_gate_unchanged"):
        if protocol.get(flag) is not True:
            raise RunBlocked("N_PROTOCOL", f"{flag} must be true")
    return protocol


def validate_out(root, out):
    if not os.path.isabs(out):
        raise RunBlocked("N_PATH", "--out must be absolute")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "noise-diagnostics-v2"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("N_PATH", "output must be under target/pr15i-c/noise-diagnostics-v2")
    if os.path.exists(candidate):
        raise RunBlocked("N_EXISTS", "noise campaign exists; choose the next unused ID")
    return candidate


def verify_sources(root, mode, baseline_sha, control_sha):
    """Validate the study's source identities and the immutable generic body."""
    if run._git(root, "cat-file", "-t", baseline_sha) != "commit":
        raise RunBlocked("N_SOURCE", "baseline is not a commit")
    if run._git(root, "cat-file", "-t", control_sha) != "commit":
        raise RunBlocked("N_SOURCE", "control is not a commit")
    if mode == "aa":
        if baseline_sha != control_sha:
            raise RunBlocked("N_SOURCE", "A/A requires identical source for both arms")
        if baseline_sha != BASELINE_SHA:
            raise RunBlocked("N_SOURCE", "A/A study source must be the merged baseline")
    else:
        if baseline_sha != BASELINE_SHA or control_sha != GENERIC_CONTROL_SHA:
            raise RunBlocked("N_SOURCE", "A/G study must use merged A and the historical G")
        if subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor",
                           baseline_sha, control_sha], check=False).returncode != 0:
            raise RunBlocked("N_SOURCE", "G does not descend from A")
        changed = [
            path for path in run.scope_paths(root, baseline_sha, control_sha)
            if path.startswith("crates/")
            and not path.startswith("crates/quervant-core/tests/")
            and not path.startswith("crates/quervant-core/benches/")
        ]
        if changed != [UNIFIED_REL]:
            raise RunBlocked("N_SOURCE", f"G production diff is not exactly one file: {changed}")
        baseline_source = source_proof.read_at_revision(root, baseline_sha, UNIFIED_REL)
        control_source = source_proof.read_at_revision(root, control_sha, UNIFIED_REL)
        baseline_body = source_proof.body_sha(baseline_source, GENERIC_METHOD)
        control_body = source_proof.body_sha(control_source, GENERIC_METHOD)
        if baseline_body != EXPECTED_GENERIC_BODY_SHA or control_body != EXPECTED_GENERIC_BODY_SHA:
            raise RunBlocked("N_SOURCE", "generic collect_mixed body hash drifted")
        attributes = source_proof.attribute_block(control_source, GENERIC_METHOD)
        if sum(1 for item in attributes if item.startswith("#[inline(")) != 1:
            raise RunBlocked("N_SOURCE", "G must carry exactly one inline attribute")
        if "#[inline(never)]" not in attributes:
            raise RunBlocked("N_SOURCE", "G must carry #[inline(never)]")
    baseline_source = source_proof.read_at_revision(root, baseline_sha, UNIFIED_REL)
    body = source_proof.body_sha(baseline_source, GENERIC_METHOD)
    if body != EXPECTED_GENERIC_BODY_SHA:
        raise RunBlocked("N_SOURCE", "baseline generic body hash drifted")
    return {"baseline_body_sha256": body}


def prepare_arms(root, mode, baseline_sha, control_sha, out):
    tag = os.path.basename(out)
    a_source = base.resolve_source_tree(
        run._worktree(root, f"noise-{tag}-a", baseline_sha))
    a = run.prepare_arm(root, "A", a_source, out)
    if mode == "aa":
        # One canonical executable, executed by both logical arms. Never build a
        # second binary: two independently linked executables can differ in layout.
        b = {
            "arm": "B",
            "source_sha": a["source_sha"],
            "adapter": dict(a["adapter"]),
            "metadata": a["metadata"],
            "shared_executable": True,
        }
    else:
        g_source = base.resolve_source_tree(
            run._worktree(root, f"noise-{tag}-g", control_sha))
        b = run.prepare_arm(root, "B", g_source, out)
    return a, b


def campaign_ratios(slots):
    """Per-lane eight block ratios plus descriptors, from sealed slot records."""
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
                raise RunBlocked("N_GATE", f"{lane_id} block {block} sample drift")
            a_mean = sum(a_values) / len(a_values)
            b_mean = sum(b_values) / len(b_values)
            if a_mean <= 0:
                raise RunBlocked("N_GATE", f"{lane_id} block {block} zero denominator")
            per_block.append(b_mean / a_mean)
        ordered = sorted(per_block)
        median = (ordered[3] + ordered[4]) / 2
        p50 = sorted(a_slot_medians + b_slot_medians)
        ratios[lane_id] = {
            "block_ratios": per_block,
            "campaign_median": median,
            "outliers_above_1_15": sum(1 for value in per_block if value > PER_BLOCK_OBSERVATION),
            "outliers_below_inverse_1_15": sum(
                1 for value in per_block if value < 1.0 / PER_BLOCK_OBSERVATION),
            "a_slot_medians_ns": a_slot_medians,
            "b_slot_medians_ns": b_slot_medians,
            "absolute_median_difference_ns": median_abs_difference(
                a_slot_medians, b_slot_medians),
            "combined_slot_p50_ns": p50[len(p50) // 2],
            "combined_slot_p95_ns": p50[(95 * len(p50) + 99) // 100 - 1],
            "combined_slot_p99_ns": p50[(99 * len(p50) + 99) // 100 - 1],
        }
    return ratios


def median_abs_difference(a_values, b_values):
    count = min(len(a_values), len(b_values))
    if count == 0:
        return 0
    differences = sorted(abs(a_values[index] - b_values[index]) for index in range(count))
    return differences[count // 2]


def derive(ratios, mode, source_proof_record):
    campaign_medians = {lane: value["campaign_median"] for lane, value in ratios.items()}
    if mode == "aa":
        ok = all(
            AA_CAMPAIGN_MEDIAN_MIN <= median <= AA_CAMPAIGN_MEDIAN_MAX
            for median in campaign_medians.values())
        decision = "AA_CAMPAIGN_QUALIFIED" if ok else "AA_CAMPAIGN_UNSTABLE"
    else:
        ok = all(median <= AG_CAMPAIGN_MEDIAN_MAX for median in campaign_medians.values())
        decision = "AG_CAMPAIGN_OBSERVED" if ok else "AG_CAMPAIGN_DRIFT"
    return {
        "schema": SCHEMA,
        "mode": mode,
        "campaign_medians": campaign_medians,
        "ratios": ratios,
        "per_block_observation_only": PER_BLOCK_OBSERVATION,
        "decision": decision,
        "campaign_median_gate": {
            "aa_min": AA_CAMPAIGN_MEDIAN_MIN,
            "aa_max": AA_CAMPAIGN_MEDIAN_MAX,
            "ag_max": AG_CAMPAIGN_MEDIAN_MAX,
        },
        "generic_body_sha256": source_proof_record["baseline_body_sha256"],
    }


def execute(args):
    if not args.idle_confirmed:
        print("N_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    if args.mode not in ("aa", "ag"):
        raise RunBlocked("N_MODE", "mode must be aa or ag")
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    protocol = load_protocol(root)
    proof = verify_sources(root, args.mode, args.baseline_sha, args.control_sha)
    base.verify_frozen_files(root)

    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("N_LANES", "lane order drift")

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
        "block_orders": ["".join(order) for order in BLOCK_ORDERS],
        "warmups_per_lane_slot": WARMUPS,
        "measured_per_lane_slot": MEASURED,
        "slots": SLOTS,
    })
    write_exclusive_json(os.path.join(out, "raw", "corpus.json"), {
        "schema": SCHEMA,
        "manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
    })

    a, b = prepare_arms(root, args.mode, args.baseline_sha, args.control_sha, out)
    a["sizes"] = run.size_builds(a, corpus, lanes, out)
    b["sizes"] = run.size_builds(b, corpus, lanes, out)
    if args.mode == "aa":
        if a["adapter"]["binary"] != b["adapter"]["binary"]:
            raise RunBlocked("N_AA_BINARY", "A/A arms must execute the same file")
        if a["adapter"]["binary_sha256"] != b["adapter"]["binary_sha256"]:
            raise RunBlocked("N_AA_BINARY", "A/A arms must execute identical bytes")
    for n in ("10000", "100000"):
        if json.dumps(a["sizes"]["layouts"][n], sort_keys=True) != json.dumps(
                b["sizes"]["layouts"][n], sort_keys=True):
            raise RunBlocked("N_FORMAT", f"n{n} arm layouts differ")
        if a["sizes"]["digests"][n] != b["sizes"]["digests"][n]:
            raise RunBlocked("N_FORMAT", f"n{n} arm segment digests differ")
    sentinel = a["sizes"]["layouts"]["100000"]
    if (sentinel["committed_index_bytes"] != run.A_100K_TOTAL
            or sentinel["stored_bytes"] != run.A_100K_STORED):
        raise RunBlocked("N_SENTINEL", "100K LZ4 sentinel mismatch")

    slots = []
    slot_index = 0
    for block, order in enumerate(BLOCK_ORDERS, start=1):
        for position, letter in enumerate(order, start=1):
            slot_index += 1
            data = a if letter == "A" else b
            trial = layout.measure_slot(
                slot_index, data["adapter"]["binary"], lanes,
                data["sizes"]["indices"], expected, data["metadata"], out)
            record = {
                "slot_index": slot_index,
                "block": block,
                "position": position,
                "arm": letter,
                "source_sha": data["source_sha"],
                "executed_binary_path": data["adapter"]["binary"],
                "binary_sha256": data["adapter"]["binary_sha256"],
                "trial": trial,
            }
            write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{slot_index:02d}.json"), record)
            slots.append(record)

    for arm_data in (a, b):
        current = sha256_file(arm_data["adapter"]["binary"])
        if current != arm_data["adapter"]["binary_sha256"]:
            raise RunBlocked("N_AA_BINARY", "adapter binary changed during the campaign")

    ratios = campaign_ratios(slots)
    report = derive(ratios, args.mode, proof)
    report["sources"] = {"A": a["source_sha"], "B": b["source_sha"]}
    report["executed_binary"] = {
        "A": {"path": a["adapter"]["binary"], "sha256": a["adapter"]["binary_sha256"]},
        "B": {"path": b["adapter"]["binary"], "sha256": b["adapter"]["binary_sha256"]},
    }
    report["identical_executable"] = args.mode == "aa"
    report["environment_fingerprint"] = fingerprint
    report["protocol_sha256"] = protocol_sha
    report["corpus_manifest_sha256"] = corpus["manifest_sha256"]
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
        "generic_body_sha256": proof["baseline_body_sha256"],
        "executed_binary_sha256": report["executed_binary"],
    })
    write_exclusive_json(os.path.join(out, "raw", "environment.json"), {
        "schema": SCHEMA,
        "host_fingerprint": fingerprint,
        "filesystem": filesystem,
        "environment": environment,
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
        "generic_body_sha256": proof["baseline_body_sha256"],
        "lane_ids": list(LANE_IDS),
        "block_orders": ["".join(order) for order in BLOCK_ORDERS],
        "warmups": WARMUPS,
        "measured": MEASURED,
        "slots": SLOTS,
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "environment_fingerprint": fingerprint,
        "filesystem": filesystem,
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
    print(f"PR15I_C noise campaign mode={args.mode} decision={report['decision']}")
    for lane_id in LANE_IDS:
        value = ratios[lane_id]
        print(f"  {lane_id}: median={value['campaign_median']:.6f} "
              f"outliers>1.15={value['outliers_above_1_15']} "
              f"blocks={[round(item, 6) for item in value['block_ratios']]}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C A/A and A/G noise diagnostic")
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
    except RunBlocked as error:
        print(f"N_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

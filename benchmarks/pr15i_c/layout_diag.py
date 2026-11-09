#!/usr/bin/env python3
"""PR 15I-C fixup — generic-boundary (G control) diagnostic controller.

Separate diagnostic protocol from the frozen `protocol.json`. It compares the real
merged PR 15I-B source (arm A) with a candidate that adds exactly one
`#[inline(never)]` annotation to the generic executor (arm G) on seven frozen
PR15D warm lanes, eight paired blocks, five warmups and ten measured samples per
lane per slot.

A PASS proves only that the out-of-line generic boundary is performance-neutral.
It is never final feature acceptance.
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
source_proof = _load("pr15i_c_source_proof", os.path.join(HERE, "source_proof.py"))
base = run.base

SCHEMA = "pr15i-c-layout-diagnostic-v1"
SEAL_SCHEMA = "pr15i-c-layout-seal-v1"
PROTOCOL_SCHEMA = "pr15i-c-layout-diag-v1"
LANE_IDS = (
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
)
BLOCKS = 8
WARMUPS = 5
MEASURED = 10
BLOCK_SAMPLES = 2
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
SLOTS = BLOCKS * 4
RATIO_MEDIAN_MAX = 1.05
RATIO_BLOCK_MAX = 1.15
A_100K_TOTAL = 15_747_551
A_100K_STORED = 1_661_455
GENERIC_METHOD = "collect_mixed"
UNIFIED_REL = "crates/quervant-core/src/search/unified.rs"
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


def validate_out(root, out):
    if not os.path.isabs(out):
        raise RunBlocked("L_PATH", "--out must be absolute")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "layout-diagnostics"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("L_PATH", "output must be under target/pr15i-c/layout-diagnostics")
    if os.path.exists(candidate):
        raise RunBlocked("L_EXISTS", "diagnostic output exists; choose the next unused ID")
    return candidate


def verify_control_source(root, baseline_sha, candidate_sha):
    """FX-D18/FX-D19: exactly one attribute, generic body byte-identical."""
    baseline = source_proof.read_at_revision(root, baseline_sha, UNIFIED_REL)
    candidate = source_proof.read_at_revision(root, candidate_sha, UNIFIED_REL)
    baseline_body = source_proof.body_sha(baseline, GENERIC_METHOD)
    candidate_body = source_proof.body_sha(candidate, GENERIC_METHOD)
    if baseline_body != candidate_body:
        raise RunBlocked("L_SOURCE", "generic collect_mixed body changed")
    attributes = source_proof.attribute_block(candidate, GENERIC_METHOD)
    if "#[inline(never)]" not in attributes:
        raise RunBlocked("L_SOURCE", "control is missing #[inline(never)]")
    if sum(1 for item in attributes if item.startswith("#[inline(")) != 1:
        raise RunBlocked("L_SOURCE", "control must add exactly one inline attribute")
    changed = run.scope_paths(root, baseline_sha, candidate_sha)
    production = [
        path for path in changed
        if path.startswith("crates/") and not path.startswith("crates/quervant-core/tests/")
        and not path.startswith("crates/quervant-core/benches/")
    ]
    if production != [UNIFIED_REL]:
        raise RunBlocked("L_SOURCE", f"control changed unexpected production paths: {production}")
    return {
        "baseline_body_sha256": baseline_body,
        "candidate_body_sha256": candidate_body,
        "attributes": attributes,
        "changed_paths": changed,
    }


def measure_lane_diagnostic(binary, index_dir, lane, expected, metadata, contention):
    """5 warmups + 10 measured samples on one reused adapter process."""
    samples = []
    warmup_ids = []
    process = base.pr15d_run.AdapterProcess(
        "quervant", base.pr15d_run._adapter_command("quervant", binary, index_dir))
    try:
        for warmup in range(WARMUPS):
            response = process.request({
                "request_id": f"{lane['id']}:warmup:{warmup}",
                "op": "query",
                "field": lane["field"],
                "term": lane["term"],
                "k": lane["k"],
                "mode": lane["regime"],
            })
            warmup_ids.append(response["request_id"])
        for sample in range(MEASURED):
            response = process.request({
                "request_id": f"{lane['id']}:sample:{sample}",
                "op": "query",
                "field": lane["field"],
                "term": lane["term"],
                "k": lane["k"],
                "mode": lane["regime"],
            })
            base.pr15d_run.validate_query_response(response, lane, expected)
            samples.append(response["engine_ns"])
    finally:
        process.close()
    if len(samples) != MEASURED:
        raise RunBlocked("L_SAMPLE", f"{lane['id']} collected {len(samples)} samples")
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "k": lane["k"],
        "field": lane["field"],
        "term": lane["term"],
        "regime": lane["regime"],
        "warmups": WARMUPS,
        "warmup_ids": warmup_ids,
        "samples_ns": samples,
        "summary_ns": base.pr15d_run.summarize(samples),
        "total_hits": expected["total_hits"],
        "doc_ids": expected["doc_ids"],
        "oracle_ok": True,
        "analyzer": metadata["analyzer"],
        "contention": contention,
    }


def measure_slot(slot_index, binary, lanes, index_dirs, expected, metadata, out):
    trial_dir = os.path.join(out, "setup", "slots")
    before = base.contention_for(os.path.join(trial_dir, f"slot-{slot_index:02d}-before.json"))
    base._require_clear(before, f"slot {slot_index} before")
    records = []
    for lane in lanes:
        records.append(measure_lane_diagnostic(
            binary, index_dirs[lane["n"]]["dir"], lane, expected[lane["id"]], metadata, before))
    after = base.contention_for(os.path.join(trial_dir, f"slot-{slot_index:02d}-after.json"))
    base._require_clear(after, f"slot {slot_index} after")
    return {
        "slot_index": slot_index,
        "started_utc": base.utc_now(),
        "lanes": records,
        "contention_before": before,
        "contention_after": after,
    }


def block_ratios(slots, lane_id):
    values = []
    for block in range(1, BLOCKS + 1):
        a_values = [record["summary_ns"]["median"] for slot in slots
                    if slot["block"] == block and slot["arm"] == "A"
                    for record in slot["trial"]["lanes"] if record["id"] == lane_id]
        b_values = [record["summary_ns"]["median"] for slot in slots
                    if slot["block"] == block and slot["arm"] == "B"
                    for record in slot["trial"]["lanes"] if record["id"] == lane_id]
        if len(a_values) != BLOCK_SAMPLES or len(b_values) != BLOCK_SAMPLES:
            raise RunBlocked("L_GATE", f"{lane_id} block {block} sample drift")
        a_mean = sum(a_values) / len(a_values)
        b_mean = sum(b_values) / len(b_values)
        if a_mean <= 0:
            raise RunBlocked("L_GATE", f"{lane_id} block {block} zero denominator")
        values.append(b_mean / a_mean)
    return values


def derive(slots, control):
    ratios = {}
    gates = {}
    medians = {}
    for lane_id in LANE_IDS:
        values = block_ratios(slots, lane_id)
        ordered = sorted(values)
        median = (ordered[3] + ordered[4]) / 2
        ratios[lane_id] = values
        medians[lane_id] = median
        ok = median <= RATIO_MEDIAN_MAX and all(
            value <= RATIO_BLOCK_MAX for value in values)
        gates[lane_id] = "PASS" if ok else "FAIL"
    qualified = all(value == "PASS" for value in gates.values())
    return {
        "schema": SCHEMA,
        "decision": "GENERIC_BOUNDARY_CONTROL_PASS" if qualified
        else "GENERIC_BOUNDARY_CONTROL_FAIL",
        "qualified": qualified,
        "ratios": ratios,
        "medians": medians,
        "gates": gates,
        "thresholds": {
            "median_max": RATIO_MEDIAN_MAX,
            "each_block_max": RATIO_BLOCK_MAX,
        },
        "generic_body_sha256": control["candidate_body_sha256"],
        "baseline_body_sha256": control["baseline_body_sha256"],
    }


def execute(args):
    if not args.idle_confirmed:
        print("L_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    if args.candidate_sha == args.baseline_sha:
        raise RunBlocked("L_SOURCE", "candidate equals baseline")
    if run._git(root, "cat-file", "-t", args.baseline_sha) != "commit":
        raise RunBlocked("L_SOURCE", "baseline is not a commit")
    if run._git(root, "cat-file", "-t", args.candidate_sha) != "commit":
        raise RunBlocked("L_SOURCE", "candidate is not a commit")
    if subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor",
                       args.baseline_sha, args.candidate_sha], check=False).returncode != 0:
        raise RunBlocked("L_SOURCE", "candidate does not descend from the baseline")
    control = verify_control_source(root, args.baseline_sha, args.candidate_sha)
    base.verify_frozen_files(root)

    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("L_LANES", "lane order drift")

    os.makedirs(out)
    os.makedirs(os.path.join(out, "raw"))
    environment = base.pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    filesystem = base.require_native_filesystem(out)
    corpus = base.prepare_corpus(os.path.join(out, "setup"))
    expected = {
        lane["id"]: base.oracle.expected(
            rows=corpus["rows"][lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
        for lane in lanes
    }
    write_exclusive_json(os.path.join(out, "raw", "authorization.json"), {
        "schema": SCHEMA,
        "protocol_schema": PROTOCOL_SCHEMA,
        "idle_authorized_by_user": True,
        "recorded_utc": base.utc_now(),
        "native_filesystem": filesystem,
        "diagnostic_only": True,
        "workload_lane_ids": list(LANE_IDS),
        "block_orders": ["".join(order) for order in BLOCK_ORDERS],
        "warmups_per_lane_slot": WARMUPS,
        "measured_per_lane_slot": MEASURED,
    })
    write_exclusive_json(os.path.join(out, "raw", "corpus.json"), {
        "schema": SCHEMA,
        "manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
    })

    a_source = base.resolve_source_tree(run._worktree(root, "diag-arm-a", args.baseline_sha))
    g_source = base.resolve_source_tree(run._worktree(root, "diag-arm-g", args.candidate_sha))
    a = run.prepare_arm(root, "A", a_source, out)
    g = run.prepare_arm(root, "B", g_source, out)
    a["sizes"] = run.size_builds(a, corpus, lanes, out)
    g["sizes"] = run.size_builds(g, corpus, lanes, out)
    for n in ("10000", "100000"):
        if json.dumps(a["sizes"]["layouts"][n], sort_keys=True) != json.dumps(
                g["sizes"]["layouts"][n], sort_keys=True):
            raise RunBlocked("L_FORMAT", f"n{n} A/G layout differs")
        if a["sizes"]["digests"][n] != g["sizes"]["digests"][n]:
            raise RunBlocked("L_FORMAT", f"n{n} A/G segment digest differs")
    sentinel = a["sizes"]["layouts"]["100000"]
    if (sentinel["committed_index_bytes"] != A_100K_TOTAL
            or sentinel["stored_bytes"] != A_100K_STORED):
        raise RunBlocked("L_SENTINEL", "100K LZ4 sentinel mismatch")

    slots = []
    slot_index = 0
    for block, order in enumerate(BLOCK_ORDERS, start=1):
        for position, arm in enumerate(order, start=1):
            slot_index += 1
            data = a if arm == "A" else g
            trial = measure_slot(slot_index, data["adapter"]["binary"], lanes,
                                 data["sizes"]["indices"], expected, data["metadata"], out)
            record = {
                "slot_index": slot_index,
                "block": block,
                "position": position,
                "arm": arm,
                "source_sha": data["source_sha"],
                "binary_sha256": data["adapter"]["binary_sha256"],
                "trial": trial,
            }
            write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{slot_index:02d}.json"), record)
            slots.append(record)

    report = derive(slots, control)
    report["sources"] = {"A": a["source_sha"], "G": g["source_sha"]}
    report["environment_fingerprint"] = fingerprint
    report["corpus_manifest_sha256"] = corpus["manifest_sha256"]
    report["binary_sha256"] = {
        "A": a["adapter"]["binary_sha256"],
        "G": g["adapter"]["binary_sha256"],
    }
    report["layouts"] = {"A": a["sizes"]["layouts"], "G": g["sizes"]["layouts"]}
    report["segment_digests"] = {"A": a["sizes"]["digests"], "G": g["sizes"]["digests"]}
    report["attributes"] = control["attributes"]
    write_exclusive_json(os.path.join(out, "raw", "sizes.json"), {
        "schema": SCHEMA,
        "A": a["sizes"]["builds"],
        "G": g["sizes"]["builds"],
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
        "binary_sha256": report["binary_sha256"],
        "generic_body_sha256": report["generic_body_sha256"],
    })
    write_exclusive_json(os.path.join(out, "raw", "environment.json"), {
        "schema": SCHEMA,
        "host_fingerprint": fingerprint,
        "filesystem": filesystem,
        "environment": environment,
        "contention": "recorded per slot in setup/slots",
    })
    write_exclusive_json(os.path.join(out, "raw", "manifest.json"), {
        "schema": SCHEMA,
        "A_sha": args.baseline_sha,
        "G_sha": args.candidate_sha,
        "workload_lane_ids": list(LANE_IDS),
        "warmups": WARMUPS,
        "measured": MEASURED,
        "blocks": BLOCKS,
        "slot_schedule": ["".join(order) for order in BLOCK_ORDERS],
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "environment_fingerprint": fingerprint,
        "filesystem": filesystem,
        "binary_sha256": report["binary_sha256"],
        "generic_body_sha256": report["generic_body_sha256"],
        "baseline_body_sha256": report["baseline_body_sha256"],
        "attributes": report["attributes"],
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
    print(f"PR15I_C layout diagnostic decision={report['decision']}")
    for lane_id in LANE_IDS:
        print(f"  {lane_id}: median={report['medians'][lane_id]:.6f} "
              f"blocks={[round(value, 6) for value in report['ratios'][lane_id]]}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C generic-boundary diagnostic")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return execute(args)
    except RunBlocked as error:
        print(f"L_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

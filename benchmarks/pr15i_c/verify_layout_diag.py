#!/usr/bin/env python3
"""PR 15I-C fixup — independent verifier for the generic-boundary diagnostic.

Rebuilds every diagnostic predicate from sealed raw evidence. It does not import
the controller's derivation and never trusts a reported PASS bit.
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


run = _load("pr15i_c_run_for_layout_verify", os.path.join(HERE, "run.py"))
source_proof = _load("pr15i_c_source_proof_for_verify", os.path.join(HERE, "source_proof.py"))
base = run.base

SCHEMA = "pr15i-c-layout-diagnostic-v1"
SEAL_SCHEMA = "pr15i-c-layout-seal-v1"
PROTOCOL_SCHEMA = "pr15i-c-layout-diag-v1"
RECEIPT_SCHEMA = "pr15i-c-layout-verification-v1"
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
RATIO_TOLERANCE = 1e-12
A_100K_TOTAL = 15_747_551
A_100K_STORED = 1_661_455
FROZEN_CORPUS_SHA = "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151"
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


def canonical_campaign(root, campaign):
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "layout-diagnostics"))
    candidate = os.path.realpath(campaign)
    require(os.path.commonpath([candidate, allowed]) == allowed and candidate != allowed,
            "LV_PATH", "campaign must be under target/pr15i-c/layout-diagnostics")
    return candidate


def check_no_symlinks(campaign, relative):
    current = campaign
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        info = os.lstat(current)
        require(not stat.S_ISLNK(info.st_mode), "LV_SYMLINK",
                f"symlinked path component {current}")


def inventory(campaign):
    raw = os.path.join(campaign, "raw")
    require(os.path.isdir(raw), "LV_INVENTORY", "missing raw directory")
    check_no_symlinks(campaign, "raw")
    found = []
    for root_dir, directories, files in os.walk(raw):
        for directory in directories:
            full = os.path.join(root_dir, directory)
            require(not os.path.islink(full), "LV_SYMLINK", f"symlinked directory {full}")
        for name in files:
            full = os.path.join(root_dir, name)
            require(not os.path.islink(full), "LV_SYMLINK", f"symlinked file {full}")
            found.append(os.path.relpath(full, raw).replace(os.sep, "/"))
    expected = set(REQUIRED_RAW) | {"seal.json"}
    extra = sorted(set(found) - expected)
    missing = sorted(expected - set(found))
    require(not extra, "LV_INVENTORY", f"unexpected raw files: {extra}")
    require(not missing, "LV_INVENTORY", f"missing raw files: {missing}")
    return sorted(found)


def verify_seal(campaign):
    seal_path = os.path.join(campaign, "raw", "seal.json")
    require(os.path.isfile(seal_path), "LV_SEAL", "missing raw/seal.json")
    seal = read_json(seal_path)
    require(seal.get("schema") == SEAL_SCHEMA, "LV_SEAL", "bad seal schema")
    files = seal.get("files")
    require(isinstance(files, dict), "LV_SEAL", "seal files must be a mapping")
    require(set(files) == set(REQUIRED_RAW), "LV_SEAL", "seal file set mismatch")
    before = {}
    for relative in REQUIRED_RAW:
        path = os.path.join(campaign, "raw", relative)
        digest = sha256_file(path)
        require(digest == files[relative], "LV_SEAL", f"seal hash mismatch for {relative}")
        before[relative] = digest
    return before


def _git(tree, *args):
    result = subprocess.run(["git", "-C", tree, *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def verify_source(root, manifest):
    a_sha = manifest.get("A_sha")
    g_sha = manifest.get("G_sha")
    require(isinstance(a_sha, str) and len(a_sha) == 40, "LV_SOURCE", "bad A sha")
    require(isinstance(g_sha, str) and len(g_sha) == 40, "LV_SOURCE", "bad G sha")
    for sha in (a_sha, g_sha):
        code, out, _err = _git(root, "cat-file", "-t", sha)
        require(code == 0 and out == "commit", "LV_SOURCE", f"{sha} is not a real commit")
    code, _out, _err = _git(root, "merge-base", "--is-ancestor", a_sha, g_sha)
    require(code == 0, "LV_SOURCE", "G does not descend from A")
    code, out, _err = _git(root, "diff", "--name-only", f"{a_sha}..{g_sha}")
    require(code == 0, "LV_SOURCE", "git diff failed")
    changed = [path for path in out.splitlines() if path]
    production = [
        path for path in changed
        if path.startswith("crates/") and not path.startswith("crates/quervant-core/tests/")
        and not path.startswith("crates/quervant-core/benches/")
    ]
    require(production in ([UNIFIED_REL], []), "LV_SCOPE",
            f"control changed unexpected production paths: {production}")
    baseline = source_proof.read_at_revision(root, a_sha, UNIFIED_REL)
    control = source_proof.read_at_revision(root, g_sha, UNIFIED_REL)
    baseline_body = source_proof.body_sha(baseline, GENERIC_METHOD)
    control_body = source_proof.body_sha(control, GENERIC_METHOD)
    require(baseline_body == control_body, "LV_BODY",
            "generic collect_mixed body differs between A and G")
    require(baseline_body == manifest.get("baseline_body_sha256"), "LV_BODY",
            "recorded baseline body hash mismatch")
    require(control_body == manifest.get("generic_body_sha256"), "LV_BODY",
            "recorded control body hash mismatch")
    if production:
        attributes = source_proof.attribute_block(control, GENERIC_METHOD)
        require("#[inline(never)]" in attributes, "LV_BOUNDARY",
                "control lacks #[inline(never)]")
        require(sum(1 for item in attributes if item.startswith("#[inline(")) == 1,
                "LV_BOUNDARY", "control must add exactly one inline attribute")
    return changed, baseline_body


def verify_binaries(campaign, manifest):
    toolchain = read_json(os.path.join(campaign, "raw", "toolchain.json"))
    declared = manifest.get("binary_sha256")
    require(isinstance(declared, dict), "LV_BINARY", "manifest binary hashes missing")
    for arm in ("A", "G"):
        path = os.path.join(campaign, "setup", "build", arm, "build", "release",
                            "pr15d-quervant-adapter")
        require(os.path.isfile(path), "LV_BINARY", f"missing executable for arm {arm}")
        require(not os.path.islink(path), "LV_BINARY", f"symlinked executable for arm {arm}")
        digest = sha256_file(path)
        require(digest == declared.get(arm), "LV_BINARY", f"{arm} adapter hash mismatch")
        require(toolchain.get("binary_sha256", {}).get(arm) == digest, "LV_BINARY",
                f"{arm} toolchain hash mismatch")
    expected_lock = os.path.join(campaign, "..", "..", "..", "Cargo.lock")
    if os.path.isfile(expected_lock):
        require(toolchain.get("cargo_lock_sha256") == sha256_file(expected_lock),
                "LV_BINARY", "cargo lock hash mismatch")
    return declared


def verify_sizes(campaign, manifest):
    sizes = read_json(os.path.join(campaign, "raw", "sizes.json"))
    layouts = {"A": {}, "G": {}}
    digests = {"A": {}, "G": {}}
    rebuilt = 0
    for arm in ("A", "G"):
        records = sizes.get(arm)
        require(isinstance(records, dict), "LV_SIZES", f"missing {arm} build records")
        for n in ("10000", "100000"):
            builds = records.get(n)
            require(isinstance(builds, list) and len(builds) == 3, "LV_SIZES",
                    f"{arm} n{n} must have three rebuild records")
            require([entry.get("attempt") for entry in builds] == [1, 2, 3], "LV_SIZES",
                    f"{arm} n{n} attempt order drift")
            seen_layouts = set()
            seen_digests = set()
            for entry in builds:
                index_dir = os.path.join(campaign, "setup", "sizes", arm,
                                         f"n{n}-run{entry['attempt']}")
                require(os.path.isdir(index_dir), "LV_SIZES", f"missing rebuild {index_dir}")
                check_no_symlinks(campaign, os.path.relpath(index_dir, campaign))
                layout = run.measure_layout(index_dir)
                digest = run.segment_digest(index_dir)
                require(json.dumps(layout, sort_keys=True)
                        == json.dumps(entry["layout"], sort_keys=True),
                        "LV_SIZES", f"{arm} n{n} run{entry['attempt']} layout drift")
                require(digest == entry.get("segment_digest"), "LV_SIZES",
                        f"{arm} n{n} run{entry['attempt']} digest drift")
                seen_layouts.add(json.dumps(layout, sort_keys=True))
                seen_digests.add(digest)
                rebuilt += 1
            require(len(seen_layouts) == 1 and len(seen_digests) == 1, "LV_SIZES",
                    f"{arm} n{n} non-deterministic rebuilds")
            layouts[arm][n] = json.loads(next(iter(seen_layouts)))
            digests[arm][n] = next(iter(seen_digests))
    require(rebuilt == 12, "LV_SIZES", f"expected 12 remeasured rebuilds, found {rebuilt}")
    for n in ("10000", "100000"):
        require(json.dumps(layouts["A"][n], sort_keys=True)
                == json.dumps(layouts["G"][n], sort_keys=True), "LV_FORMAT",
                f"n{n} A/G layout differs")
        require(digests["A"][n] == digests["G"][n], "LV_FORMAT", f"n{n} A/G digest differs")
        for arm in ("A", "G"):
            require(layouts[arm][n]["stored_version"] == 2, "LV_FORMAT",
                    f"{arm} n{n} not STORED v2")
            require(layouts[arm][n]["codec_id"] == 1, "LV_FORMAT", f"{arm} n{n} not LZ4")
            require([13, 1] in layouts[arm][n]["required_features"], "LV_FORMAT",
                    f"{arm} n{n} lacks required feature 0x000D v1")
    require(layouts["A"]["100000"]["committed_index_bytes"] == A_100K_TOTAL, "LV_SENTINEL",
            "100K committed-byte sentinel mismatch")
    require(layouts["A"]["100000"]["stored_bytes"] == A_100K_STORED, "LV_SENTINEL",
            "100K STORED-byte sentinel mismatch")
    return layouts, digests


def expected_arm(block, position):
    return BLOCK_ORDERS[block - 1][position - 1]


def validate_slot_matrix(slots, lane_ids=LANE_IDS):
    require(len(slots) == SLOTS, "LV_SLOT", f"expected {SLOTS} slots, found {len(slots)}")
    seen = set()
    measured = 0
    warmed = 0
    for position_expected, record in enumerate(slots, start=1):
        index = record.get("slot_index")
        require(index == position_expected, "LV_SLOT", f"slot {index} out of order")
        require(index not in seen, "LV_SLOT", f"duplicated slot {index}")
        seen.add(index)
        arm = record.get("arm")
        block = record.get("block")
        position = record.get("position")
        require(arm in ("A", "B"), "LV_SLOT", f"slot {index} bad arm")
        require(block in tuple(range(1, BLOCKS + 1)), "LV_SLOT", f"slot {index} bad block")
        require(position in (1, 2, 3, 4), "LV_SLOT", f"slot {index} bad position")
        require(arm == expected_arm(block, position), "LV_SLOT",
                f"slot {index} violates the prescribed ABBA/BAAB schedule")
        trial = record.get("trial")
        require(isinstance(trial, dict), "LV_SLOT", f"slot {index} missing trial")
        lanes_seen = [lane["id"] for lane in trial.get("lanes", [])]
        require(lanes_seen == list(lane_ids), "LV_SLOT", f"slot {index} lane set drift")
        for lane in trial["lanes"]:
            samples = lane.get("samples_ns")
            require(isinstance(samples, list) and len(samples) == MEASURED, "LV_SLOT",
                    f"slot {index} {lane['id']} sample count "
                    f"{len(samples) if samples else None}")
            require(lane.get("warmups") == WARMUPS, "LV_SLOT",
                    f"slot {index} {lane['id']} warmup count drift")
            require(len(lane.get("warmup_ids", [])) == WARMUPS, "LV_SLOT",
                    f"slot {index} {lane['id']} warmup id drift")
            for value in samples:
                require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
                        "LV_SLOT", f"slot {index} {lane['id']} invalid sample")
            require(lane.get("summary_ns") == base.pr15d_run.summarize(samples), "LV_SLOT",
                    f"slot {index} {lane['id']} summary mismatch")
            measured += len(samples)
            warmed += WARMUPS
        require(trial.get("contention_before", {}).get("state") == "clear", "LV_CONTENTION",
                f"slot {index} contention before not clear")
        require(trial.get("contention_after", {}).get("state") == "clear", "LV_CONTENTION",
                f"slot {index} contention after not clear")
    require(measured == 2240, "LV_SLOT", f"expected 2240 measured samples, found {measured}")
    require(warmed == 1120, "LV_SLOT", f"expected 1120 warmups, found {warmed}")
    for block in range(1, BLOCKS + 1):
        arms = [record["arm"] for record in slots if record["block"] == block]
        require(arms.count("A") == 2 and arms.count("B") == 2, "LV_SLOT",
                f"block {block} is not balanced")
    return measured, warmed


def verify_corpus(campaign):
    record = read_json(os.path.join(campaign, "raw", "corpus.json"))
    corpus_dir = os.path.join(campaign, "setup", "corpus")
    require(os.path.isdir(corpus_dir), "LV_CORPUS", "missing corpus directory")
    _manifest, rows = base.oracle.load_and_verify(corpus_dir)
    require(record.get("manifest_sha256") == FROZEN_CORPUS_SHA, "LV_CORPUS",
            "corpus manifest digest differs from the frozen value")
    corpora = record.get("corpora", {})
    for n in ("10000", "100000"):
        entry = corpora.get(str(n))
        require(isinstance(entry, dict), "LV_CORPUS", f"missing corpus record for n={n}")
        path = os.path.join(corpus_dir, base.oracle.corpus_filename(n))
        require(os.path.isfile(path), "LV_CORPUS", f"missing corpus file for n={n}")
        require(sha256_file(path) == entry.get("sha256"), "LV_CORPUS",
                f"corpus digest drift for n={n}")
    lanes = [lane for lane in base.stage_lanes("final") if lane["id"] in LANE_IDS]
    require([lane["id"] for lane in lanes] == list(LANE_IDS), "LV_CORPUS", "lane order drift")
    return rows, lanes


def verify_slots(campaign, rows, lanes):
    slots = [read_json(os.path.join(campaign, "raw", "slots", f"slot-{index:02d}.json"))
             for index in range(1, SLOTS + 1)]
    measured, warmed = validate_slot_matrix(slots)
    expected = {
        lane["id"]: base.oracle.expected(
            rows=rows[lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
        for lane in lanes
    }
    for record in slots:
        for lane in record["trial"]["lanes"]:
            lane_id = lane["id"]
            require(lane.get("oracle_ok") is True, "LV_SLOT",
                    f"slot {record['slot_index']} {lane_id} oracle not ok")
            require(lane.get("total_hits") == expected[lane_id]["total_hits"], "LV_SLOT",
                    f"slot {record['slot_index']} {lane_id} total_hits drift")
            require(lane.get("doc_ids") == expected[lane_id]["doc_ids"], "LV_SLOT",
                    f"slot {record['slot_index']} {lane_id} key order drift")
    return slots, measured, warmed


def recompute_ratios(slots):
    ratios = {}
    for lane_id in LANE_IDS:
        per_block = []
        for block in range(1, BLOCKS + 1):
            a_values = [lane["summary_ns"]["median"] for record in slots
                        if record["block"] == block and record["arm"] == "A"
                        for lane in record["trial"]["lanes"] if lane["id"] == lane_id]
            b_values = [lane["summary_ns"]["median"] for record in slots
                        if record["block"] == block and record["arm"] == "B"
                        for lane in record["trial"]["lanes"] if lane["id"] == lane_id]
            require(len(a_values) == BLOCK_SAMPLES and len(b_values) == BLOCK_SAMPLES,
                    "LV_RATIO", f"{lane_id} block {block} sample drift")
            a_mean = sum(a_values) / 2
            b_mean = sum(b_values) / 2
            require(a_mean > 0, "LV_RATIO", f"{lane_id} block {block} zero denominator")
            per_block.append(b_mean / a_mean)
        ordered = sorted(per_block)
        ratios[lane_id] = {
            "block_ratios": per_block,
            "median": (ordered[3] + ordered[4]) / 2,
        }
    return ratios


def recompute_gates(ratios):
    gates = {}
    for lane_id in LANE_IDS:
        median_ok = ratios[lane_id]["median"] <= RATIO_MEDIAN_MAX
        block_ok = all(value <= RATIO_BLOCK_MAX
                       for value in ratios[lane_id]["block_ratios"])
        gates[lane_id] = "PASS" if median_ok and block_ok else "FAIL"
    gates["CONTROL"] = "PASS" if all(value == "PASS" for value in gates.values()) else "FAIL"
    return gates


def compare_with_controller(ratios, gates, measurements):
    reported = measurements.get("ratios", {})
    for lane_id in LANE_IDS:
        values = reported.get(lane_id)
        require(isinstance(values, list) and len(values) == BLOCKS, "LV_RATIO",
                f"{lane_id} reported block ratios missing")
        for expected, actual in zip(ratios[lane_id]["block_ratios"], values):
            require(abs(expected - actual) <= RATIO_TOLERANCE, "LV_RATIO",
                    f"{lane_id} block ratio serialization drift")
        require(abs(ratios[lane_id]["median"] - measurements["medians"][lane_id])
                <= RATIO_TOLERANCE, "LV_RATIO", f"{lane_id} median drift")
    reported_gates = measurements.get("gates", {})
    for lane_id in LANE_IDS:
        require(reported_gates.get(lane_id) == gates[lane_id], "LV_GATE",
                f"{lane_id} controller disagreement")
    require(measurements.get("qualified") is (gates["CONTROL"] == "PASS"), "LV_GATE",
            "controller qualified flag disagrees with the independently derived gates")
    return reported_gates


def write_receipt(root, campaign, payload):
    reviews = os.path.join(root, "target", "pr15i-c", "reviews")
    os.makedirs(reviews, exist_ok=True)
    name = os.path.basename(campaign)
    path = os.path.join(reviews, f"layout-{name}.json")
    if os.path.exists(path):
        raise VerificationFailed("LV_RECEIPT", f"refusing to replace {path}")
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def verify(root, campaign, verify_only, write=True):
    campaign = canonical_campaign(root, campaign)
    check_no_symlinks(campaign, "raw")
    found = inventory(campaign)
    before = verify_seal(campaign)
    manifest = read_json(os.path.join(campaign, "raw", "manifest.json"))
    measurements = read_json(os.path.join(campaign, "raw", "measurements.json"))
    authorization = read_json(os.path.join(campaign, "raw", "authorization.json"))
    require(manifest.get("schema") == SCHEMA, "LV_MANIFEST", "bad manifest schema")
    require(measurements.get("schema") == SCHEMA, "LV_MANIFEST", "bad measurement schema")
    require(authorization.get("schema") == SCHEMA, "LV_MANIFEST", "bad authorization schema")
    require(authorization.get("protocol_schema") == PROTOCOL_SCHEMA, "LV_MANIFEST",
            "bad diagnostic protocol schema")
    require(authorization.get("diagnostic_only") is True, "LV_MANIFEST",
            "diagnostic controller must mark itself diagnostic-only")
    require(tuple(manifest.get("workload_lane_ids", ())) == LANE_IDS, "LV_MANIFEST",
            "workload lane list drifted")
    require(tuple(manifest.get("slot_schedule", ()))
            == tuple("".join(order) for order in BLOCK_ORDERS), "LV_MANIFEST",
            "slot schedule drifted")
    require(manifest.get("warmups") == WARMUPS and manifest.get("measured") == MEASURED,
            "LV_MANIFEST", "sample counts drifted")

    changed, body_sha = verify_source(root, manifest)
    binaries = verify_binaries(campaign, manifest)
    layouts, digests = verify_sizes(campaign, manifest)
    rows, lanes = verify_corpus(campaign)
    slots, measured, warmed = verify_slots(campaign, rows, lanes)
    ratios = recompute_ratios(slots)
    gates = recompute_gates(ratios)
    reported_gates = compare_with_controller(ratios, gates, measurements)

    after = {relative: sha256_file(os.path.join(campaign, "raw", relative))
             for relative in REQUIRED_RAW}
    require(before == after, "LV_TAMPER", "raw evidence changed during verification")

    qualified = gates["CONTROL"] == "PASS"
    payload = {
        "schema": RECEIPT_SCHEMA,
        "campaign": os.path.basename(campaign),
        "A_sha": manifest.get("A_sha"),
        "G_sha": manifest.get("G_sha"),
        "changed_paths": changed,
        "generic_body_sha256": body_sha,
        "attributes": manifest.get("attributes"),
        "corpus_manifest_sha256": manifest.get("corpus_manifest_sha256"),
        "binary_sha256": binaries,
        "layouts": layouts,
        "segment_digests": digests,
        "rebuilds_remeasured": 12,
        "slots": SLOTS,
        "lane_records": SLOTS * len(LANE_IDS),
        "warmups": warmed,
        "measured_samples": measured,
        "lane_ratios": ratios,
        "controller_gates": reported_gates,
        "independent_gates": gates,
        "decision": "GENERIC_BOUNDARY_CONTROL_PASS" if qualified
        else "GENERIC_BOUNDARY_CONTROL_FAIL",
        "diagnostic_only": True,
        "final_feature_acceptance": False,
        "verify_only": verify_only,
        "raw_inventory": len(found),
        "seal_sha256": hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()).hexdigest(),
    }
    if write:
        payload["receipt_path"] = write_receipt(root, campaign, payload)
    return payload


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C generic-boundary verifier")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--no-receipt", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = os.path.realpath(args.checkout_root)
    try:
        payload = verify(root, args.campaign, args.verify_only,
                         write=not args.no_receipt)
    except VerificationFailed as error:
        print(f"LV_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3
    print(f"PR15I_C layout verify decision={payload['decision']}")
    for lane_id in LANE_IDS:
        value = payload["lane_ratios"][lane_id]
        print(f"  {lane_id}: median={value['median']:.6f} "
              f"blocks={[round(item, 6) for item in value['block_ratios']]}"
              f" gate={payload['independent_gates'][lane_id]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

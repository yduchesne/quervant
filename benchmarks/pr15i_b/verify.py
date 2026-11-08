#!/usr/bin/env python3
"""PR 15I-B read-only independent verifier for a sealed STORED v2 campaign."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location("pr15i_b_controller", os.path.join(HERE, "run.py"))
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)
base = run.base

SCHEMA = "pr15i-b-verification-v1"


class VerifyError(Exception):
    def __init__(self, code, detail, exit_code=2):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.exit_code = exit_code


def reject(code, detail):
    raise VerifyError(code, detail)


def blocked(code, detail):
    raise VerifyError(code, detail, 3)


def load(path, code="B_INPUT"):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise VerifyError(code, f"cannot read {os.path.basename(path)}: {error}") from error


def sha(path):
    return run.sha256_file(path)


def _safe(relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or relative.startswith("/"):
        reject("B_SEAL", f"unsafe path {relative!r}")
    if any(part in ("", ".", "..") for part in relative.split("/")):
        reject("B_SEAL", f"non-canonical path {relative!r}")
    if "\x00" in relative:
        reject("B_SEAL", "NUL in path")


def seal_and_inventory(campaign):
    raw = os.path.join(campaign, "raw")
    seal_path = os.path.join(raw, "seal.json")
    if not os.path.isfile(seal_path) or os.path.islink(seal_path):
        blocked("B_SEAL", "missing seal")
    seal = load(seal_path, "B_SEAL")
    if seal.get("schema") != run.SEAL_SCHEMA:
        reject("B_SEAL", "bad seal schema")
    files = seal.get("files")
    if not isinstance(files, dict) or set(files) != set(run.REQUIRED_RAW):
        reject("B_SEAL", "seal inventory is not the exact 26-file set")
    for relative, digest in files.items():
        _safe(relative)
        if not isinstance(digest, str) or len(digest) != 64 or digest.lower() != digest:
            reject("B_SEAL", f"bad digest {relative}")
        path = os.path.join(raw, relative)
        if os.path.islink(path) or not os.path.isfile(path):
            reject("B_SEAL", f"nonregular sealed file {relative}")
        if sha(path) != digest:
            reject("B_SEAL", f"seal mismatch {relative}")
    actual = set()
    for root, dirs, names in os.walk(raw, followlinks=False):
        for name in dirs:
            relative = os.path.relpath(os.path.join(root, name), raw).replace(os.sep, "/")
            if relative != "slots":
                reject("B_SEAL", f"unexpected raw directory {relative}")
        for name in names:
            full = os.path.join(root, name)
            relative = os.path.relpath(full, raw).replace(os.sep, "/")
            if os.path.islink(full) or not os.path.isfile(full):
                reject("B_SEAL", f"nonregular raw file {relative}")
            actual.add(relative)
    expected = set(run.REQUIRED_RAW) | {"seal.json"}
    if actual != expected:
        reject("B_SEAL", f"raw inventory differs: {sorted(actual ^ expected)}")
    return seal, {relative: sha(os.path.join(raw, relative)) for relative in run.REQUIRED_RAW}


def validate_authorization(auth, manifest, measurements):
    if auth.get("schema") != run.SCHEMA:
        reject("B_PROVENANCE", "authorization schema")
    if auth.get("idle_authorized_by_user") is not True:
        reject("B_PROVENANCE", "idle authorization is not true")
    if auth.get("native_filesystem") != manifest.get("filesystem"):
        reject("B_PROVENANCE", "filesystem mismatch")
    if auth.get("native_filesystem") not in base.pr15d_run.NATIVE_FILESYSTEMS:
        reject("B_PROVENANCE", "nonnative filesystem")
    if manifest.get("environment_fingerprint") != measurements.get("environment_fingerprint"):
        reject("B_PROVENANCE", "environment fingerprint mismatch")


def validate_source(root, manifest, measurements, scope):
    if manifest["A_sha"] != run.P0_SHA:
        reject("B_SOURCE", "A is not the P0 baseline")
    if scope.get("p0_sha") != run.P0_SHA or scope.get("A") != manifest["A_sha"] or scope.get("B") != manifest["B_sha"]:
        reject("B_SOURCE", "scope identity mismatch")
    if measurements.get("sources") != {"A": manifest["A_sha"], "B": manifest["B_sha"]}:
        reject("B_SOURCE", "measurement sources mismatch")
    protocol_path = os.path.join(root, "benchmarks", "pr15i_b", "protocol.json")
    if not os.path.isfile(protocol_path):
        reject("B_PROVENANCE", "protocol missing")
    if manifest.get("protocol_sha256") != sha(protocol_path):
        reject("B_PROVENANCE", "protocol hash drift")
    if scope.get("changed_paths") != run.scope_paths(root, manifest["A_sha"], manifest["B_sha"]):
        reject("B_SOURCE", "scope diff mismatch")
    for path in scope["changed_paths"]:
        if path in run.ALLOWED_EXACT or any(path.startswith(p) for p in run.ALLOWED_PREFIXES):
            continue
        reject("B_SOURCE", f"unallowed path {path}")


def validate_sizes(sizes, measurements, codec):
    for arm in ("A", "B"):
        if set(sizes[arm]) != {"10000", "100000"}:
            reject("B_FORMAT", "size map shape")
        for n in ("10000", "100000"):
            builds = sorted(sizes[arm][n], key=lambda record: record["attempt"])
            if len(builds) != run.SIZE_REBUILDS:
                reject("B_FORMAT", f"{arm} n{n} rebuild count")
            layouts = [record["layout"] for record in builds]
            if len({json.dumps(layout, sort_keys=True) for layout in layouts}) != 1:
                reject("B_FORMAT", f"{arm} n{n} layouts differ")
            layout = layouts[0]
            if layout["stored_version"] != (1 if arm == "A" else 2):
                reject("B_FORMAT", f"{arm} n{n} stored version")
            if arm == "B":
                if layout["codec_id"] != run.CODEC_IDS[codec]:
                    reject("B_FORMAT", "codec id mismatch")
                if [13, 1] not in layout["required_features"]:
                    reject("B_FORMAT", "required STORED_BLOCKS missing")
    a, b = sizes["A"]["100000"][-1]["layout"], sizes["B"]["100000"][-1]["layout"]
    if a["committed_index_bytes"] != run.A_100K_TOTAL or a["sidecar_bytes"] != run.A_100K_SIDECAR or a["stored_bytes"] != run.A_100K_STORED:
        reject("B_FORMAT", "A 100K sentinels differ")
    ratios = {
        "stored_100k": b["stored_bytes"] / a["stored_bytes"],
        "committed_100k": b["committed_index_bytes"] / a["committed_index_bytes"],
        "stored_10k": sizes["B"]["10000"][-1]["layout"]["stored_bytes"] / sizes["A"]["10000"][-1]["layout"]["stored_bytes"],
        "committed_10k": sizes["B"]["10000"][-1]["layout"]["committed_index_bytes"] / sizes["A"]["10000"][-1]["layout"]["committed_index_bytes"],
    }
    if measurements.get("size_ratios") != ratios:
        reject("B_INPUT_MISMATCH", "size ratios differ")


def _block_ratios(a_entries, b_entries, metric):
    values = []
    for block in range(1, run.BLOCKS + 1):
        av = [metric(s) for e in a_entries if e["block"] == block for s in e["samples"]]
        bv = [metric(s) for e in b_entries if e["block"] == block for s in e["samples"]]
        if len(av) != run.BLOCK_SAMPLES or len(bv) != run.BLOCK_SAMPLES:
            reject("B_MATRIX", f"block {block} sample count")
        values.append((sum(bv) / len(bv)) / (sum(av) / len(av)))
    return values


def _gate(values, median_max, block_max):
    ordered = sorted(values)
    median = (ordered[1] + ordered[2]) / 2
    return median <= median_max and all(value <= block_max for value in values)


def validate_blocks(blocks):
    if blocks.get("schema") != run.SCHEMA or blocks.get("block_arm_order") != [list(x) for x in run.BLOCK_ARM_ORDER]:
        reject("B_MATRIX", "block schedule")
    for arm in ("A", "B"):
        for kind in ("reopen", "build_commit", "remote"):
            entries = blocks[arm][kind]
            if len(entries) != run.BLOCKS:
                reject("B_MATRIX", f"{arm}/{kind} block count")
            for entry in entries:
                if entry.get("contention_before", {}).get("state") != "clear":
                    reject("B_PROVENANCE", f"{arm}/{kind} before contention")
                if entry.get("contention_after", {}).get("state") != "clear":
                    reject("B_PROVENANCE", f"{arm}/{kind} after contention")
                if len(entry["samples"]) != run.BLOCK_SAMPLES:
                    reject("B_MATRIX", f"{arm}/{kind} samples")
                for sample in entry["samples"]:
                    for field in ("open_ns", "index_ns", "commit_ns", "maxrss_bytes"):
                        if field in sample and (not isinstance(sample[field], int) or sample[field] <= 0 or isinstance(sample[field], bool)):
                            reject("B_MATRIX", f"{arm}/{kind} {field}")
                    if kind == "build_commit" and (sample.get("documents_indexed") != 100_000 or sample.get("documents_verified") != 100_000 or sample.get("index_bytes") != sample.get("measured_index_bytes")):
                        reject("B_MATRIX", "build commit sample")
                    if kind == "remote" and sample.get("documents") != 100_000:
                        reject("B_MATRIX", "remote count")


def validate_slots(slots, sources, binaries, corpus_rows):
    expected = []
    for block, order in enumerate(run.SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            expected.append((block, position, arm))
    keyed = {}
    for slot in slots:
        index = slot.get("slot_index")
        if not isinstance(index, int) or index in keyed:
            reject("B_MATRIX", "slot index")
        keyed[index] = slot
    if set(keyed) != set(range(1, 17)):
        reject("B_MATRIX", "slot set")
    descriptors = {lane["id"]: lane for lane in base.stage_lanes("final")}
    for index in range(1, 17):
        slot = keyed[index]
        if (slot["block"], slot["position"], slot["arm"]) != expected[index - 1]:
            reject("B_MATRIX", f"slot {index} schedule")
        if slot["source_sha"] != sources[slot["arm"]]:
            reject("B_SOURCE", f"slot {index} source")
        if slot["binary_sha256"] != binaries[slot["arm"]]["adapter"]:
            reject("B_PROVENANCE", f"slot {index} binary")
        trial = slot["trial"]
        if trial.get("index") != index or trial.get("contention_before", {}).get("state") != "clear" or trial.get("contention_after", {}).get("state") != "clear":
            reject("B_PROVENANCE", f"slot {index} trial/contention")
        lanes = trial.get("lanes", [])
        if [lane.get("id") for lane in lanes] != list(run.LANE_IDS):
            reject("B_MATRIX", f"slot {index} lane order")
        for lane in lanes:
            descriptor = descriptors[lane["id"]]
            for field in ("n", "class", "field", "term", "k", "regime"):
                if lane.get(field) != descriptor[field]:
                    reject("B_MATRIX", f"{lane['id']} {field}")
            if lane.get("warmups") != run.WARMUPS or lane.get("warmup_ids") != [f"{lane['id']}:warmup:{i}" for i in range(run.WARMUPS)]:
                reject("B_MATRIX", f"{lane['id']} warmups")
            samples = lane.get("samples_ns", [])
            if len(samples) != run.MEASURED or any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in samples):
                reject("B_MATRIX", f"{lane['id']} samples")
            summary = base.pr15d_run.summarize(samples)
            if lane.get("summary_ns") != summary:
                reject("B_MATRIX", f"{lane['id']} summary")
            oracle = base.oracle.expected(rows=corpus_rows[lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
            if lane.get("oracle_ok") is not True or lane.get("total_hits") != oracle["total_hits"] or lane.get("expected_total_hits") != oracle["total_hits"] or lane.get("doc_ids") != oracle["doc_ids"] or lane.get("expected_doc_ids") != oracle["doc_ids"]:
                reject("B_ORACLE", f"{lane['id']} oracle")
            if lane.get("contention", {}).get("state") != "clear":
                reject("B_PROVENANCE", f"{lane['id']} contention")


def verify_campaign(root, campaign):
    root = os.path.realpath(root)
    campaign = os.path.realpath(campaign)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-b", "campaigns"))
    if os.path.commonpath([campaign, allowed]) != allowed or campaign == allowed:
        blocked("B_PATH", "campaign outside target/pr15i-b/campaigns")
    protocol = run.load_protocol(root)
    seal, hashes = seal_and_inventory(campaign)
    raw = os.path.join(campaign, "raw")
    manifest = load(os.path.join(raw, "manifest.json"))
    measurements = load(os.path.join(raw, "measurements.json"))
    authorization = load(os.path.join(raw, "authorization.json"))
    blocks = load(os.path.join(raw, "blocks.json"))
    sizes = load(os.path.join(raw, "sizes.json"))
    selected = load(os.path.join(raw, "selected.json"))
    scope = load(os.path.join(raw, "scope.json"))
    corpus = load(os.path.join(raw, "corpus.json"))
    environment = load(os.path.join(raw, "environment.json"))
    if manifest.get("schema") != run.SCHEMA or measurements.get("schema") != run.SCHEMA:
        reject("B_INPUT", "schema")
    validate_authorization(authorization, manifest, measurements)
    validate_source(root, manifest, measurements, scope)
    auxiliary = environment.get("auxiliary_probe_hashes")
    if not isinstance(auxiliary, dict) or not auxiliary:
        reject("B_PROVENANCE", "auxiliary probe inventory")
    for relative, digest in auxiliary.items():
        _safe(relative)
        path = os.path.join(campaign, relative)
        if not os.path.isfile(path) or sha(path) != digest:
            reject("B_PROVENANCE", f"auxiliary probe mismatch {relative}")
    if manifest.get("corpus_manifest_sha256") != corpus.get("manifest_sha256") or measurements.get("corpus_manifest_sha256") != corpus.get("manifest_sha256"):
        reject("B_PROVENANCE", "corpus hash")
    if corpus.get("manifest_sha256") != verify_expected_corpus(campaign):
        reject("B_PROVENANCE", "corpus unverifiable")
    codec = manifest.get("codec")
    if codec not in run.CODEC_IDS:
        reject("B_FORMAT", "codec name")
    validate_sizes(sizes, measurements, codec)
    binaries = measurements["binary_sha256"]
    for arm in ("A", "B"):
        for name, digest in binaries[arm].items():
            if not isinstance(digest, str) or len(digest) != 64:
                reject("B_PROVENANCE", f"{arm} {name} binary digest")
    validate_blocks(blocks)
    corpus_rows = load_corpus_rows(campaign)
    slots = [load(os.path.join(raw, "slots", f"slot-{i:02d}.json")) for i in range(1, 17)]
    validate_slots(slots, {"A": manifest["A_sha"], "B": manifest["B_sha"]}, binaries, corpus_rows)
    # Independent gate matrix.
    a_sizes = {n: sizes["A"][n][-1]["layout"] for n in ("10000", "100000")}
    b_sizes = {n: sizes["B"][n][-1]["layout"] for n in ("10000", "100000")}
    ratios = measurements["size_ratios"]
    gates = {}
    gates["B-P03"] = "PASS" if ratios["stored_100k"] <= run.LIMITS["B-P03"]["stored_100k_ratio_max"] else "FAIL"
    gates["B-P04"] = "PASS" if ratios["committed_100k"] <= run.LIMITS["B-P04"]["committed_100k_ratio_max"] else "FAIL"
    gates["B-P05"] = "PASS" if ratios["stored_10k"] <= run.LIMITS["B-P05"]["stored_10k_ratio_max"] and ratios["committed_10k"] <= run.LIMITS["B-P05"]["committed_10k_ratio_max"] else "FAIL"
    warm = {}
    for lane in run.LANE_IDS:
        values = []
        for block in range(1, run.BLOCKS + 1):
            av = [r["summary_ns"]["median"] for s in slots if s["block"] == block and s["arm"] == "A" for r in s["trial"]["lanes"] if r["id"] == lane]
            bv = [r["summary_ns"]["median"] for s in slots if s["block"] == block and s["arm"] == "B" for r in s["trial"]["lanes"] if r["id"] == lane]
            values.append((sum(bv) / 2) / (sum(av) / 2))
        warm[lane] = values
    rare_ok = all(_gate(values, run.LIMITS["B-P06"]["rare_medium_median_max"], run.LIMITS["B-P06"]["each_block_max"]) for lane, values in warm.items() if lane in run.RARE_MEDIUM)
    other_ok = all(_gate(values, run.LIMITS["B-P07"]["other_warm_median_max"], run.LIMITS["B-P07"]["each_block_max"]) for lane, values in warm.items() if lane not in run.RARE_MEDIUM)
    gates["B-P06"] = "PASS" if rare_ok else "FAIL"
    gates["B-P07"] = "PASS" if other_ok else "FAIL"
    reopen = _block_ratios(blocks["A"]["reopen"], blocks["B"]["reopen"], lambda s: s["open_ns"])
    gates["B-P08"] = "PASS" if _gate(reopen, run.LIMITS["B-P08"]["reopen_median_max"], run.LIMITS["B-P08"]["each_block_max"]) else "FAIL"
    remote = _block_ratios(blocks["A"]["remote"], blocks["B"]["remote"], lambda s: s["open_ns"])
    gates["B-P09"] = "PASS" if _gate(remote, run.LIMITS["B-P09"]["rustfs_median_max"], run.LIMITS["B-P09"]["each_block_max"]) else "FAIL"
    build = _block_ratios(blocks["A"]["build_commit"], blocks["B"]["build_commit"], lambda s: s["index_ns"] + s["commit_ns"])
    gates["B-P10"] = "PASS" if _gate(build, run.LIMITS["B-P10"]["build_commit_median_max"], run.LIMITS["B-P10"]["each_block_max"]) else "FAIL"
    rss_ok = True
    for kind in ("reopen", "build_commit"):
        values = _block_ratios(blocks["A"][kind], blocks["B"][kind], lambda s: s["maxrss_bytes"])
        rss_ok &= _gate(values, run.LIMITS["B-P11"]["rss_median_max"], run.LIMITS["B-P11"]["each_block_max"])
    gates["B-P11"] = "PASS" if rss_ok else "FAIL"
    selected_ratios = {}
    selected_ok = True
    for k in run.SELECTED_K:
        values = _block_ratios(selected["A"], selected["B"], lambda s, k=k: s[str(k)]["selected_ns"])
        selected_ratios[str(k)] = values
        selected_ok &= _gate(values, run.LIMITS["B-P12"]["selected_median_max"], run.LIMITS["B-P12"]["each_block_max"])
        for entry in selected["A"] + selected["B"]:
            for sample in entry["samples"]:
                if sample[str(k)]["selected_ns"] <= 0:
                    reject("B_MATRIX", "selected latency")
    gates["B-P12"] = "PASS" if selected_ok else "FAIL"
    gates["B-P13"] = "PASS"
    ordered = sorted(selected_ratios["100"])
    combined = ratios["stored_100k"] * ((ordered[1] + ordered[2]) / 2)
    expected_report = {
        "size_ratios": ratios, "warm_ratios": warm, "reopen_ratios": reopen,
        "remote_ratios": remote, "build_commit_ratios": build,
        "selected_ratios": selected_ratios, "combined_cost": combined, "gates": gates,
    }
    for key, value in expected_report.items():
        if measurements.get(key) != value:
            reject("B_INPUT_MISMATCH", f"recomputed {key} differs")
    eligible = all(status == "PASS" for status in gates.values()) and combined < 1.0
    decision = "B_CANDIDATE_QUALIFIED" if eligible else "B_CANDIDATE_INELIGIBLE"
    if measurements.get("decision") != decision:
        reject("B_INPUT_MISMATCH", "decision differs")
    published = os.path.join(root, "benchmarks", "reports", "pr15i-b", "results.json")
    if os.path.isfile(published):
        if load(published) != measurements:
            reject("B_INPUT_MISMATCH", "published results differ")
    return {
        "schema": SCHEMA, "decision": decision, "codec": codec,
        "combined_cost": combined, "gates": gates,
        "sources": {"A": manifest["A_sha"], "B": manifest["B_sha"]},
        "raw_files_verified": len(run.REQUIRED_RAW),
        "seal_sha256": sha(os.path.join(raw, "seal.json")),
        "size_ratios": ratios, "selected_100k_ratio": (ordered[1] + ordered[2]) / 2,
    }


def verify_expected_corpus(campaign):
    directory = os.path.join(campaign, "setup", "corpus")
    try:
        manifest, _rows = base.oracle.load_and_verify(directory)
    except Exception as error:
        raise VerifyError("B_PROVENANCE", f"corpus unverifiable: {error}", 3) from error
    return hashlib.sha256(base.oracle.canonical_json_bytes(manifest)).hexdigest()


def load_corpus_rows(campaign):
    directory = os.path.join(campaign, "setup", "corpus")
    try:
        _manifest, rows = base.oracle.load_and_verify(directory)
    except Exception as error:
        raise VerifyError("B_PROVENANCE", f"corpus unreadable: {error}", 3) from error
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="PR 15I-B verifier")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = verify_campaign(args.checkout_root, args.campaign)
    except VerifyError as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr)
        return error.exit_code
    print(f"PR15I_B_VERIFY codec={receipt['codec']} decision={receipt['decision']} "
          f"combined={receipt['combined_cost']:.6f} raw={receipt['raw_files_verified']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

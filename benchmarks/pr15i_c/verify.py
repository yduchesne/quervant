#!/usr/bin/env python3
"""PR 15I-C independent campaign verifier.

Rebuilds every acceptance predicate from raw evidence. It never imports the
controller's derivation and never trusts a controller-reported PASS bit.
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
SPEC = os.path.join(ROOT, "benchmarks", "pr15e_b1", "run_targeted.py")
_spec = importlib.util.spec_from_file_location("pr15i_c_verify_base", SPEC)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

SCHEMA = "pr15i-c-campaign-v1"
SEAL_SCHEMA = "pr15i-c-seal-v1"
PROTOCOL_SCHEMA = "pr15i-c-physical-v1"
RECEIPT_SCHEMA = "pr15i-c-verification-v1"
PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "protocol.json")
BASE_15IB = "f70cde62e709383d82693ad548a8c69c7f772bef"
P0_15IA = "0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb"

WARMUPS = 5
MEASURED = 20
BLOCKS = 4
BLOCK_SAMPLES = 2
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
SCHEDULE = (("A", "B", "B", "A"), ("B", "A", "A", "B"), ("B", "A", "A", "B"), ("A", "B", "B", "A"))
PRIMARY_MEDIAN_MAX = 0.90
PRIMARY_BLOCK_MAX = 1.15
NONPRIMARY_MEDIAN_MAX = 1.05
NONPRIMARY_BLOCK_MAX = 1.15
RATIO_TOLERANCE = 1e-12
REQUIRED_RAW = (
    "authorization.json",
    "corpus.json",
    "environment.json",
    "manifest.json",
    "measurements.json",
    "scope.json",
    "score_parity.json",
    "sizes.json",
    "toolchain.json",
    *(f"slots/slot-{index:02d}.json" for index in range(1, 17)),
)
ALLOWED_EXACT = {
    "crates/quervant-core/Cargo.toml",
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/diagnostics.rs",
    "crates/quervant-core/src/search/mod.rs",
    "crates/quervant-core/tests/pr15i_c_physical.rs",
    "crates/quervant-core/tests/pr15i_c_rustfs.rs",
    "docs/ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/BENCHMARKING.md",
    "docs/TESTING.md",
    "docs/ROADMAP_V01.md",
    ".github/workflows/ci.yml",
}
ALLOWED_PREFIXES = ("benchmarks/pr15i_c/", "docs/pr-artifacts/pr-15i-c/")
FORBIDDEN_PREFIXES = (
    "crates/quervant-core/src/segment/",
    "crates/quervant-core/src/index/",
    "crates/quervant-core/src/storage/",
    "crates/quervant-core/src/contract/",
    "benchmarks/pr15d/",
    "benchmarks/pr15i_0/",
    "benchmarks/pr15i_a/",
    "benchmarks/pr15i_b/",
    "benchmarks/pr15e_b1/",
    "docs/pr-artifacts/pr-15i-0/",
)

VerificationFailed = base.pr15d_run.RunBlocked


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def require(condition, code, detail):
    if not condition:
        raise VerificationFailed(code, detail)


def canonical_campaign(root, campaign):
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "campaigns"))
    candidate = os.path.realpath(campaign)
    require(
        os.path.commonpath([candidate, allowed]) == allowed and candidate != allowed,
        "V_PATH",
        "campaign must be a real directory under target/pr15i-c/campaigns",
    )
    return candidate


def check_no_symlinks(campaign, relative):
    current = campaign
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        info = os.lstat(current)
        require(not stat.S_ISLNK(info.st_mode), "V_SYMLINK", f"symlinked path component {current}")


def inventory(campaign):
    raw = os.path.join(campaign, "raw")
    require(os.path.isdir(raw), "V_INVENTORY", "missing raw directory")
    check_no_symlinks(campaign, "raw")
    found = []
    for root_dir, directories, files in os.walk(raw):
        for directory in directories:
            full = os.path.join(root_dir, directory)
            require(not os.path.islink(full), "V_SYMLINK", f"symlinked directory {full}")
        for name in files:
            full = os.path.join(root_dir, name)
            require(not os.path.islink(full), "V_SYMLINK", f"symlinked file {full}")
            found.append(os.path.relpath(full, raw).replace(os.sep, "/"))
    expected = set(REQUIRED_RAW) | {"seal.json"}
    extra = sorted(set(found) - expected)
    missing = sorted(expected - set(found))
    require(not extra, "V_INVENTORY", f"unexpected raw files: {extra}")
    require(not missing, "V_INVENTORY", f"missing raw files: {missing}")
    return sorted(found)


def verify_seal(campaign):
    seal = read_json(os.path.join(campaign, "raw", "seal.json"))
    require(seal.get("schema") == SEAL_SCHEMA, "V_SEAL", "bad seal schema")
    files = seal.get("files")
    require(isinstance(files, dict), "V_SEAL", "seal files must be a mapping")
    require(set(files) == set(REQUIRED_RAW), "V_SEAL", "seal file set mismatch")
    before = {}
    for relative in REQUIRED_RAW:
        path = os.path.join(campaign, "raw", relative)
        digest = sha256_file(path)
        require(digest == files[relative], "V_SEAL", f"seal hash mismatch for {relative}")
        before[relative] = digest
    return before


def _git(tree, *args):
    result = subprocess.run(["git", "-C", tree, *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def verify_source(root, manifest):
    a_sha = manifest.get("A_sha")
    b_sha = manifest.get("B_sha")
    require(isinstance(a_sha, str) and len(a_sha) == 40, "V_SOURCE", "bad A sha")
    require(isinstance(b_sha, str) and len(b_sha) == 40, "V_SOURCE", "bad B sha")
    require(a_sha == BASE_15IB or a_sha != P0_15IA, "V_SOURCE", "A must not be PR 15I-A")
    for sha in (a_sha, b_sha):
        code, out, _err = _git(root, "cat-file", "-t", sha)
        require(code == 0 and out == "commit", "V_SOURCE", f"{sha} is not a real commit")
    code, _out, _err = _git(root, "diff", "--quiet", BASE_15IB, a_sha, "--",
                            "crates/quervant-core/src", "crates/quervant-core/Cargo.toml",
                            "Cargo.lock", "benchmarks/pr15d", "benchmarks/pr15i_b")
    require(code == 0, "V_SOURCE", "A content is not the merged PR 15I-B tree")
    code, _out, _err = _git(root, "merge-base", "--is-ancestor", a_sha, b_sha)
    require(code == 0, "V_SOURCE", "B does not descend from A")
    code, out, err = _git(root, "diff", "--name-only", f"{a_sha}..{b_sha}")
    require(code == 0, "V_SOURCE", f"git diff failed: {err}")
    changed = [path for path in out.splitlines() if path]
    for path in changed:
        for prefix in FORBIDDEN_PREFIXES:
            require(not path.startswith(prefix), "V_SCOPE", f"protected path changed: {path}")
        if path in ALLOWED_EXACT:
            continue
        require(any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES),
                "V_SCOPE", f"path outside allowlist: {path}")
    code, out, _err = _git(root, "show", f"{a_sha}:Cargo.lock")
    require(code == 0, "V_SOURCE", "cannot read A Cargo.lock")
    a_lock = out
    code, out, _err = _git(root, "show", f"{b_sha}:Cargo.lock")
    require(code == 0, "V_SOURCE", "cannot read B Cargo.lock")
    require(a_lock == out, "V_SOURCE", "Cargo.lock changed between A and B")
    return changed


def verify_protocol(root, manifest):
    protocol_path = os.path.join(root, PROTOCOL_REL)
    require(os.path.isfile(protocol_path), "V_PROTOCOL", "missing protocol.json")
    digest = sha256_file(protocol_path)
    require(digest == manifest.get("protocol_sha256"), "V_PROTOCOL", "protocol hash mismatch")
    protocol = read_json(protocol_path)
    require(protocol.get("schema") == PROTOCOL_SCHEMA, "V_PROTOCOL", "bad protocol schema")
    require(tuple(protocol.get("lane_ids", [])) == LANE_IDS, "V_PROTOCOL", "lane set drifted")
    require(tuple(protocol.get("primary_lanes", [])) == PRIMARY_LANES, "V_PROTOCOL",
            "primary lanes drifted")
    require(protocol.get("warmups") == WARMUPS, "V_PROTOCOL", "warmup count drifted")
    require(protocol.get("samples_per_lane_slot") == MEASURED, "V_PROTOCOL",
            "sample count drifted")
    require(protocol.get("primary_median_ratio_max") == PRIMARY_MEDIAN_MAX, "V_PROTOCOL",
            "primary median gate drifted")
    require(protocol.get("primary_each_block_ratio_max") == PRIMARY_BLOCK_MAX, "V_PROTOCOL",
            "primary block gate drifted")
    require(protocol.get("nonprimary_median_ratio_max") == NONPRIMARY_MEDIAN_MAX, "V_PROTOCOL",
            "non-primary median gate drifted")
    require(protocol.get("nonprimary_each_block_ratio_max") == NONPRIMARY_BLOCK_MAX,
            "V_PROTOCOL", "non-primary block gate drifted")
    require(tuple("".join(order) for order in SCHEDULE) == tuple(protocol.get("slot_schedule", [])),
            "V_PROTOCOL", "schedule drifted")
    return digest


def measure_layout(index_dir):
    stored = 0
    segments = 0
    sidecar = 0
    stored_version = None
    codec = None
    features = None
    seg_magic = b"TRWSEG01"
    for root, _dirs, files in os.walk(index_dir):
        for name in sorted(files):
            path = os.path.join(root, name)
            relative = os.path.relpath(path, index_dir).replace(os.sep, "/")
            size = os.path.getsize(path)
            if relative.startswith("index/segments/"):
                segments += size
                with open(path, "rb") as handle:
                    data = handle.read()
                if data[:8] != seg_magic:
                    raise VerificationFailed("V_FORMAT", f"not a segment: {path}")
                trailer = len(data) - 64
                footer_offset = int.from_bytes(data[trailer + 8:trailer + 16], "little")
                footer_len = int.from_bytes(data[trailer + 16:trailer + 24], "little")
                section_count = int.from_bytes(data[trailer + 24:trailer + 28], "little")
                cursor = footer_offset
                if int.from_bytes(data[cursor:cursor + 2], "little") != 1:
                    raise VerificationFailed("V_FORMAT", "bad footer")
                cursor += 6
                required = int.from_bytes(data[cursor:cursor + 4], "little")
                cursor += 4
                features = []
                for _ in range(required):
                    features.append([int.from_bytes(data[cursor:cursor + 2], "little"),
                                     int.from_bytes(data[cursor + 2:cursor + 4], "little")])
                    cursor += 4
                optional = int.from_bytes(data[cursor:cursor + 4], "little")
                cursor += 4 + optional * 4
                for _ in range(section_count):
                    kind = int.from_bytes(data[cursor:cursor + 2], "little")
                    offset = int.from_bytes(data[cursor + 12:cursor + 20], "little")
                    length = int.from_bytes(data[cursor + 20:cursor + 28], "little")
                    cursor += 60
                    if kind == 0x0007:
                        stored = length
                        stored_version = int.from_bytes(data[offset:offset + 2], "little")
                        codec = data[offset + 12] if stored_version == 2 else None
                if cursor != footer_offset + footer_len:
                    raise VerificationFailed("V_FORMAT", "footer length mismatch")
            elif relative.startswith("index/state/"):
                sidecar += size
    total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(index_dir) for f in fs)
    return {
        "stored_bytes": stored,
        "segment_bytes": segments,
        "sidecar_bytes": sidecar,
        "committed_index_bytes": total,
        "stored_version": stored_version,
        "codec_id": codec,
        "required_features": sorted(features or []),
    }


def segment_digest(index_dir):
    digest = hashlib.sha256()
    segments = os.path.join(index_dir, "index", "segments")
    if not os.path.isdir(segments):
        return digest.hexdigest()
    for name in sorted(os.listdir(segments)):
        path = os.path.join(segments, name)
        if not os.path.isfile(path):
            continue
        digest.update(name.encode() + b"\0")
        digest.update(str(os.path.getsize(path)).encode() + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def verify_sizes(campaign, manifest):
    sizes = read_json(os.path.join(campaign, "raw", "sizes.json"))
    layouts = {"A": {}, "B": {}}
    digests = {"A": {}, "B": {}}
    rebuilt = 0
    for arm in ("A", "B"):
        builds = sizes.get(arm)
        require(isinstance(builds, dict), "V_SIZES", f"missing {arm} builds")
        for n in ("10000", "100000"):
            records = builds.get(n)
            require(isinstance(records, list) and len(records) == 3, "V_SIZES",
                    f"{arm} n{n} must have exactly 3 rebuild records")
            attempts = [record.get("attempt") for record in records]
            require(attempts == [1, 2, 3], "V_SIZES", f"{arm} n{n} attempt order drift")
            remeasured = []
            remeasured_digests = []
            for record in records:
                index_dir = os.path.join(campaign, "setup", "sizes", arm, f"n{n}-run{record['attempt']}")
                require(os.path.isdir(index_dir), "V_SIZES", f"missing rebuild {index_dir}")
                check_no_symlinks(campaign, os.path.relpath(index_dir, campaign))
                layout = measure_layout(index_dir)
                digest = segment_digest(index_dir)
                require(json.dumps(layout, sort_keys=True) == json.dumps(record["layout"], sort_keys=True),
                        "V_SIZES", f"{arm} n{n} run{record['attempt']} layout drift")
                require(digest == record.get("segment_digest"), "V_SIZES",
                        f"{arm} n{n} run{record['attempt']} segment digest drift")
                remeasured.append(layout)
                remeasured_digests.append(digest)
                rebuilt += 1
            require(len({json.dumps(value, sort_keys=True) for value in remeasured}) == 1,
                    "V_SIZES", f"{arm} n{n} non-deterministic rebuilds")
            layouts[arm][n] = remeasured[-1]
            digests[arm][n] = remeasured_digests[-1]
    require(rebuilt == 12, "V_SIZES", f"expected 12 remeasured rebuilds, found {rebuilt}")
    for n in ("10000", "100000"):
        require(json.dumps(layouts["A"][n], sort_keys=True)
                == json.dumps(layouts["B"][n], sort_keys=True),
                "V_FORMAT", f"n{n} A/B layout differs")
        require(digests["A"][n] == digests["B"][n], "V_FORMAT", f"n{n} A/B segment digest differs")
        for arm in ("A", "B"):
            require(layouts[arm][n]["stored_version"] == 2, "V_FORMAT",
                    f"{arm} n{n} not STORED v2")
            require(layouts[arm][n]["codec_id"] == 1, "V_FORMAT", f"{arm} n{n} not LZ4")
            require([13, 1] in layouts[arm][n]["required_features"], "V_FORMAT",
                    f"{arm} n{n} lacks feature 0x000D v1")
    return layouts, digests


def verify_binaries(campaign, manifest):
    raw = os.path.join(campaign, "raw")
    toolchain = read_json(os.path.join(raw, "toolchain.json"))
    manifest_binaries = manifest.get("binary_sha256", {})
    for arm in ("A", "B"):
        for tool in ("adapter", "score"):
            if tool == "adapter":
                path = os.path.join(campaign, "setup", "build", arm, "build", "release",
                                    "pr15d-quervant-adapter")
            else:
                path = os.path.join(campaign, "setup", "build", arm, "score_probe", "release",
                                    "pr15i-c-score-probe")
            require(os.path.isfile(path), "V_BINARY", f"missing {arm} {tool} executable {path}")
            require(not os.path.islink(path), "V_BINARY", f"symlinked {arm} {tool} executable")
            digest = sha256_file(path)
            require(isinstance(digest, str) and len(digest) == 64, "V_BINARY", "bad digest")
            declared = manifest_binaries.get(arm, {}).get(tool)
            require(digest == declared, "V_BINARY", f"{arm} {tool} hash mismatch")
            require(toolchain.get("binary_sha256", {}).get(arm, {}).get(tool) == digest,
                    "V_BINARY", f"{arm} {tool} toolchain hash mismatch")
    lock_digest = sha256_file(os.path.join(campaign, "..", "..", "..", "Cargo.lock")) \
        if os.path.isfile(os.path.join(campaign, "..", "..", "..", "Cargo.lock")) else None
    require(lock_digest is None or toolchain.get("cargo_lock_sha256") == lock_digest,
            "V_BINARY", "cargo lock hash mismatch")
    return manifest_binaries


def verify_score_parity(campaign):
    record = read_json(os.path.join(campaign, "raw", "score_parity.json"))
    a_hits = record.get("A", {})
    b_hits = record.get("B", {})
    require(set(a_hits) == set(LANE_IDS), "V_SCORE", "score parity lane set drift")
    require(set(b_hits) == set(LANE_IDS), "V_SCORE", "score parity lane set drift")
    for lane_id in LANE_IDS:
        left = a_hits[lane_id]
        right = b_hits[lane_id]
        require(left == right, "V_SCORE", f"{lane_id} A/B score records differ")
        for hit in left:
            bits = hit.get("score_bits")
            require(isinstance(bits, str) and len(bits) == 16
                    and all(character in "0123456789abcdef" for character in bits),
                    "V_SCORE", f"{lane_id} score bits are not 16 lowercase hex digits")
            require(isinstance(hit.get("key"), str) and hit["key"], "V_SCORE",
                    f"{lane_id} empty key")
    return record


def expected_arm(block, position):
    return SCHEDULE[block - 1][position - 1]


def validate_slot_matrix(slots, lane_ids=LANE_IDS):
    """Validate the exact 16-slot / 9-lane / 5-warmup / 20-sample matrix."""
    require(len(slots) == 16, "V_SLOT", f"expected 16 slots, found {len(slots)}")
    seen = set()
    measured = 0
    warmed = 0
    for position_expected, record in enumerate(slots, start=1):
        index = record.get("slot_index")
        require(index == position_expected, "V_SLOT", f"slot {index} out of order")
        require(index not in seen, "V_SLOT", f"duplicated slot {index}")
        seen.add(index)
        arm = record.get("arm")
        block = record.get("block")
        position = record.get("position")
        require(arm in ("A", "B"), "V_SLOT", f"slot {index} bad arm")
        require(block in (1, 2, 3, 4), "V_SLOT", f"slot {index} bad block")
        require(position in (1, 2, 3, 4), "V_SLOT", f"slot {index} bad position")
        require(arm == expected_arm(block, position), "V_SLOT",
                f"slot {index} violates the ABBA/BAAB schedule")
        trial = record.get("trial")
        require(isinstance(trial, dict), "V_SLOT", f"slot {index} missing trial")
        lanes_seen = [lane["id"] for lane in trial.get("lanes", [])]
        require(lanes_seen == list(lane_ids), "V_SLOT", f"slot {index} lane set drift")
        for lane_record in trial["lanes"]:
            lane_id = lane_record["id"]
            samples = lane_record.get("samples_ns")
            require(isinstance(samples, list) and len(samples) == MEASURED, "V_SLOT",
                    f"slot {index} {lane_id} sample count "
                    f"{len(samples) if samples else None}")
            require(lane_record.get("warmups") == WARMUPS, "V_SLOT",
                    f"slot {index} {lane_id} warmup count drift")
            require(len(lane_record.get("warmup_ids", [])) == WARMUPS, "V_SLOT",
                    f"slot {index} {lane_id} warmup id drift")
            for value in samples:
                require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
                        "V_SLOT",
                        f"slot {index} {lane_id} non-integer or non-positive sample")
            summary = lane_record.get("summary_ns")
            require(isinstance(summary, dict), "V_SLOT",
                    f"slot {index} {lane_id} summary missing")
            require(summary == base.pr15d_run.summarize(samples), "V_SLOT",
                    f"slot {index} {lane_id} summary mismatch")
            measured += len(samples)
            warmed += WARMUPS
        before = trial.get("contention_before", {}).get("state")
        after = trial.get("contention_after", {}).get("state")
        require(before == "clear" and after == "clear", "V_CONTENTION",
                f"slot {index} contention not clear ({before}/{after})")
    require(measured == 2880, "V_SLOT",
            f"expected 2880 measured samples, found {measured}")
    require(warmed == 720, "V_SLOT", f"expected 720 warmups, found {warmed}")
    return measured, warmed


def verify_corpus_and_slots(campaign, root):
    corpus_record = read_json(os.path.join(campaign, "raw", "corpus.json"))
    corpus_dir = os.path.join(campaign, "setup", "corpus")
    require(os.path.isdir(corpus_dir), "V_CORPUS", "missing corpus directory")
    _manifest, rows = base.oracle.load_and_verify(corpus_dir)
    corpora = corpus_record.get("corpora", {})
    for n in ("10000", "100000"):
        entry = corpora.get(str(n))
        require(isinstance(entry, dict), "V_CORPUS", f"missing corpus record for n={n}")
        path = os.path.join(corpus_dir, base.oracle.corpus_filename(n))
        require(os.path.isfile(path), "V_CORPUS", f"missing corpus file for n={n}")
        require(sha256_file(path) == entry.get("sha256"), "V_CORPUS",
                f"corpus digest drift for n={n}")
        require(os.path.getsize(path) == entry.get("bytes"), "V_CORPUS",
                f"corpus size drift for n={n}")
        require(len(rows[int(n)]) == entry.get("rows"), "V_CORPUS",
                f"corpus row count drift for n={n}")
    lanes = base.stage_lanes("final")
    require([lane["id"] for lane in lanes] == list(LANE_IDS), "V_CORPUS", "lane order drift")
    expected = {
        lane["id"]: base.oracle.expected(
            rows=rows[lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
        for lane in lanes
    }
    slots = []
    for index in range(1, 17):
        slots.append(read_json(os.path.join(campaign, "raw", "slots", f"slot-{index:02d}.json")))
    measured, warmed = validate_slot_matrix(slots)
    for record in slots:
        for lane_record in record["trial"]["lanes"]:
            lane_id = lane_record["id"]
            require(lane_record.get("oracle_ok") is True, "V_SLOT",
                    f"slot {record['slot_index']} {lane_id} oracle not ok")
            require(lane_record.get("total_hits") == expected[lane_id]["total_hits"], "V_SLOT",
                    f"slot {record['slot_index']} {lane_id} total_hits drift")
            require(lane_record.get("doc_keys") == expected[lane_id]["doc_keys"], "V_SLOT",
                    f"slot {record['slot_index']} {lane_id} key order drift")
    require(measured == 2880 and warmed == 720, "V_SLOT", "sample matrix drift")
    return slots, expected


def recompute_ratios(slots):
    ratios = {}
    for lane_id in LANE_IDS:
        per_block = []
        for block in range(1, BLOCKS + 1):
            a_values = []
            b_values = []
            for record in slots:
                if record["block"] != block:
                    continue
                for lane_record in record["trial"]["lanes"]:
                    if lane_record["id"] != lane_id:
                        continue
                    (a_values if record["arm"] == "A" else b_values).append(
                        lane_record["summary_ns"]["median"])
            require(len(a_values) == BLOCK_SAMPLES and len(b_values) == BLOCK_SAMPLES,
                    "V_RATIO", f"{lane_id} block {block} sample drift")
            a_mean = sum(a_values) / 2
            b_mean = sum(b_values) / 2
            require(a_mean > 0, "V_RATIO", f"{lane_id} block {block} zero denominator")
            per_block.append(b_mean / a_mean)
        ordered = sorted(per_block)
        ratios[lane_id] = {
            "block_ratios": per_block,
            "median": (ordered[1] + ordered[2]) / 2,
        }
    return ratios


def recompute_gates(ratios):
    gates = {}
    for lane_id in LANE_IDS:
        block_max = PRIMARY_BLOCK_MAX if lane_id in PRIMARY_LANES else NONPRIMARY_BLOCK_MAX
        median_max = PRIMARY_MEDIAN_MAX if lane_id in PRIMARY_LANES else NONPRIMARY_MEDIAN_MAX
        median_ok = ratios[lane_id]["median"] <= median_max
        block_ok = all(value <= block_max for value in ratios[lane_id]["block_ratios"])
        gates[lane_id] = "PASS" if median_ok and block_ok else "FAIL"
    gates["C-P06"] = gates[PRIMARY_LANES[0]]
    gates["C-P07"] = gates[PRIMARY_LANES[1]]
    gates["C-P08"] = gates[PRIMARY_LANES[2]]
    gates["C-P09"] = "PASS" if all(
        gates[lane_id] == "PASS" for lane_id in LANE_IDS if lane_id not in PRIMARY_LANES
    ) else "FAIL"
    return gates


def compare_with_controller(ratios, gates, measurements):
    reported = measurements.get("warm_ratios", {})
    for lane_id in LANE_IDS:
        values = reported.get(lane_id)
        require(isinstance(values, list) and len(values) == BLOCKS, "V_RATIO",
                f"{lane_id} reported block ratios missing")
        for expected, actual in zip(ratios[lane_id]["block_ratios"], values):
            require(abs(expected - actual) <= RATIO_TOLERANCE, "V_RATIO",
                    f"{lane_id} block ratio serialization drift")
    reported_gates = measurements.get("gates", {})
    for key, value in gates.items():
        require(reported_gates.get(key) == value, "V_GATE", f"{key} controller disagreement")
    return reported_gates


def write_receipt(root, campaign, payload):
    reviews = os.path.join(root, "target", "pr15i-c", "reviews")
    os.makedirs(reviews, exist_ok=True)
    name = os.path.basename(campaign)
    path = os.path.join(reviews, f"{name}-verification.json")
    if os.path.exists(path):
        raise VerificationFailed("V_RECEIPT", f"refusing to replace {path}")
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
    require(manifest.get("schema") == SCHEMA, "V_MANIFEST", "bad campaign schema")
    measurements = read_json(os.path.join(campaign, "raw", "measurements.json"))
    require(measurements.get("schema") == SCHEMA, "V_MANIFEST", "bad measurement schema")
    protocol_digest = verify_protocol(root, manifest)
    changed = verify_source(root, manifest)
    layouts, digests = verify_sizes(campaign, manifest)
    binaries = verify_binaries(campaign, manifest)
    score = verify_score_parity(campaign)
    slots, expected = verify_corpus_and_slots(campaign, root)
    ratios = recompute_ratios(slots)
    gates = recompute_gates(ratios)
    reported_gates = compare_with_controller(ratios, gates, measurements)

    after = {}
    for relative in REQUIRED_RAW:
        after[relative] = sha256_file(os.path.join(campaign, "raw", relative))
    require(before == after, "V_TAMPER", "raw evidence changed during verification")

    performance_ok = all(
        gates[key] == "PASS" for key in ("C-P06", "C-P07", "C-P08", "C-P09"))
    decision = ("C_PERFORMANCE_QUALIFIED" if performance_ok
                else "C_PERFORMANCE_REJECTED")
    payload = {
        "schema": RECEIPT_SCHEMA,
        "campaign": os.path.basename(campaign),
        "A_sha": manifest.get("A_sha"),
        "B_sha": manifest.get("B_sha"),
        "protocol_sha256": protocol_digest,
        "corpus_manifest_sha256": manifest.get("corpus_manifest_sha256"),
        "source_scope_diff": changed,
        "format_identities": {
            "layouts": layouts,
            "segment_digests": digests,
            "historical_100k_sentinel_match": read_json(
                os.path.join(campaign, "raw", "sizes.json")).get(
                    "historical_100k_sentinel_match"),
        },
        "binary_sha256": binaries,
        "rebuilds_remeasured": 12,
        "slots": len(slots),
        "lane_records": len(slots) * len(LANE_IDS),
        "warmups": 720,
        "measured_samples": 2880,
        "lane_ratios": ratios,
        "controller_gates": reported_gates,
        "independent_gates": gates,
        "score_parity": {
            "lanes": len(score.get("A", {})),
            "score_bits_required": True,
            "score_bits_equal": True,
        },
        "raw_inventory": len(found),
        "seal_before_sha256": hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()).hexdigest(),
        "seal_after_sha256": hashlib.sha256(
            json.dumps(after, sort_keys=True).encode()).hexdigest(),
        "decision": decision,
        "verify_only": verify_only,
        "real_rustfs_status": "PENDING",
        "hosted_ci_status": "PENDING",
        "independent_review_status": "PENDING",
    }
    if write:
        payload["receipt_path"] = write_receipt(root, campaign, payload)
    return payload


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C independent verifier")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--no-receipt", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = os.path.realpath(args.checkout_root)
    try:
        payload = verify(root, args.campaign, args.verify_only, write=not args.no_receipt)
    except VerificationFailed as error:
        print(f"C_VERIFY_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3
    print(f"PR15I_C verify decision={payload['decision']}")
    for key in ("C-P06", "C-P07", "C-P08", "C-P09"):
        print(f"  {key}: {payload['independent_gates'][key]}")
    for lane_id, value in payload["lane_ratios"].items():
        print(f"  {lane_id}: median={value['median']:.6f} "
              f"blocks={[round(item, 6) for item in value['block_ratios']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

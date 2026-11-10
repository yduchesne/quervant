#!/usr/bin/env python3
"""PR 15I-C source-locked paired warm-lane campaign controller.

Compares the effective merged PR 15I-B source (arm A) with one immutable
postings-physical candidate (arm B) on the frozen PR15D nine warm lanes. Both arms
build from detached source-locked worktrees with the frozen PR15D adapter, the same
toolchain, the same locked dependency graph and byte-identical LZ4 STORED v2
indexes; only search execution differs.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = os.path.join(ROOT, "benchmarks", "pr15e_b1", "run_targeted.py")
_spec = importlib.util.spec_from_file_location("pr15i_c_base", SPEC)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

SCHEMA = "pr15i-c-campaign-v1"
SEAL_SCHEMA = "pr15i-c-seal-v1"
PROTOCOL_SCHEMA = "pr15i-c-physical-v1"
PROTOCOL_REL = os.path.join("benchmarks", "pr15i_c", "protocol.json")
BASE_15IB = "f70cde62e709383d82693ad548a8c69c7f772bef"
P0_15IA = "0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb"

WARMUPS = 5
MEASURED = 20
BLOCKS = 4
BLOCK_SAMPLES = 2
SIZE_REBUILDS = 3
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
A_100K_TOTAL = 15_747_551
A_100K_STORED = 1_661_455

# Only these repository paths may differ between A and B.
ALLOWED_EXACT = {
    "crates/quervant-core/Cargo.toml",
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/score.rs",
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
ALLOWED_PREFIXES = (
    "benchmarks/pr15i_c/",
    "docs/pr-artifacts/pr-15i-c/",
)
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

RunBlocked = base.pr15d_run.RunBlocked


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_exclusive_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        raise RunBlocked("C_EXISTS", f"refusing to replace {path}")
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_out(root, out):
    if not os.path.isabs(out):
        raise RunBlocked("C_PATH", "--out must be absolute")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-c", "campaigns"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("C_PATH", "output must be under target/pr15i-c/campaigns")
    if os.path.exists(candidate):
        raise RunBlocked("C_EXISTS", "campaign output exists; choose the next unused ID")
    return candidate


def load_protocol(root):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise RunBlocked("C_PROTOCOL", "bad protocol schema")
    if tuple(protocol.get("lane_ids", [])) != LANE_IDS:
        raise RunBlocked("C_PROTOCOL", "lane set drifted")
    if tuple(protocol.get("primary_lanes", [])) != PRIMARY_LANES:
        raise RunBlocked("C_PROTOCOL", "primary lane set drifted")
    if tuple("".join(order) for order in SCHEDULE) != tuple(protocol.get("slot_schedule", [])):
        raise RunBlocked("C_PROTOCOL", "slot schedule drifted")
    if protocol.get("warmups") != WARMUPS or protocol.get("samples_per_lane_slot") != MEASURED:
        raise RunBlocked("C_PROTOCOL", "sample counts drifted")
    if protocol.get("primary_median_ratio_max") != PRIMARY_MEDIAN_MAX:
        raise RunBlocked("C_PROTOCOL", "primary median gate drifted")
    if protocol.get("primary_each_block_ratio_max") != PRIMARY_BLOCK_MAX:
        raise RunBlocked("C_PROTOCOL", "primary block gate drifted")
    if protocol.get("nonprimary_median_ratio_max") != NONPRIMARY_MEDIAN_MAX:
        raise RunBlocked("C_PROTOCOL", "non-primary median gate drifted")
    if protocol.get("nonprimary_each_block_ratio_max") != NONPRIMARY_BLOCK_MAX:
        raise RunBlocked("C_PROTOCOL", "non-primary block gate drifted")
    if protocol.get("baseline_source") != BASE_15IB:
        raise RunBlocked("C_PROTOCOL", "baseline source drifted")
    if protocol.get("source_change_owner") != (
        "search/unified.rs + search/execute.rs + opt-in probe only"
    ):
        raise RunBlocked("C_PROTOCOL", "source owner drifted")
    for flag in ("exact_score_bits_required", "exact_total_hits_required",
                 "same_format_baseline_and_candidate"):
        if protocol.get(flag) is not True:
            raise RunBlocked("C_PROTOCOL", f"{flag} must be true")
    return protocol


def _git(tree, *args):
    result = subprocess.run(["git", "-C", tree, *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RunBlocked("C_SOURCE", f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _worktree(root, name, sha):
    path = os.path.join(root, "target", "pr15i-c", "worktrees", name)
    if os.path.isdir(path) and _git(path, "rev-parse", "HEAD") != sha:
        subprocess.run(["git", "-C", root, "worktree", "remove", "--force", path], check=True)
    if not os.path.isdir(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["git", "-C", root, "worktree", "add", "--detach", path, sha], check=True)
    if os.path.islink(path) or _git(path, "rev-parse", "HEAD") != sha:
        raise RunBlocked("C_SOURCE", f"worktree {name} not pinned to {sha}")
    if _git(path, "status", "--porcelain", "--untracked-files=no"):
        raise RunBlocked("C_SOURCE", f"worktree {name} is dirty")
    return path


def scope_paths(root, a_sha, b_sha):
    return sorted(
        path
        for path in _git(root, "diff", "--name-only", f"{a_sha}..{b_sha}").splitlines()
        if path
    )


def check_scope(root, a_sha, b_sha):
    changed = scope_paths(root, a_sha, b_sha)
    for path in changed:
        for prefix in FORBIDDEN_PREFIXES:
            if path.startswith(prefix):
                raise RunBlocked("C_SCOPE", f"candidate changed a protected path: {path}")
        if path in ALLOWED_EXACT:
            continue
        if any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            continue
        raise RunBlocked("C_SCOPE", f"candidate changed a path outside the allowlist: {path}")
    return changed


def check_ci_change(root, a_sha, b_sha):
    expected = "          cargo test -p quervant-core --all-features --test pr15i_c_rustfs -- --ignored --test-threads=1"
    before = collections.Counter(_git(root, "show", f"{a_sha}:.github/workflows/ci.yml").splitlines())
    after = collections.Counter(_git(root, "show", f"{b_sha}:.github/workflows/ci.yml").splitlines())
    added = after - before
    removed = before - after
    if not added and not removed:
        return
    if dict(added) != {expected: 1} or removed:
        raise RunBlocked("C_CI_SCOPE", "CI change is not exactly the single C RustFS invocation")


def check_lock_unchanged(root, a_sha, b_sha):
    if _git(root, "show", f"{a_sha}:Cargo.lock") != _git(root, "show", f"{b_sha}:Cargo.lock"):
        raise RunBlocked("C_SCOPE", "candidate changed the production Cargo.lock")


# ---------------------------------------------------------------------------
# Index layout inspection
# ---------------------------------------------------------------------------


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
                    raise RunBlocked("C_FORMAT", f"not a segment: {path}")
                trailer = len(data) - 64
                footer_offset = struct.unpack_from("<Q", data, trailer + 8)[0]
                footer_len = struct.unpack_from("<Q", data, trailer + 16)[0]
                section_count = struct.unpack_from("<I", data, trailer + 24)[0]
                cursor = footer_offset
                if struct.unpack_from("<H", data, cursor)[0] != 1:
                    raise RunBlocked("C_FORMAT", "bad footer")
                cursor += 6
                required = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                features = []
                for _ in range(required):
                    features.append([struct.unpack_from("<H", data, cursor)[0],
                                     struct.unpack_from("<H", data, cursor + 2)[0]])
                    cursor += 4
                optional = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4 + optional * 4
                for _ in range(section_count):
                    kind = struct.unpack_from("<H", data, cursor)[0]
                    offset = struct.unpack_from("<Q", data, cursor + 12)[0]
                    length = struct.unpack_from("<Q", data, cursor + 20)[0]
                    cursor += 60
                    if kind == 0x0007:
                        stored = length
                        stored_version = struct.unpack_from("<H", data, offset)[0]
                        codec = data[offset + 12] if stored_version == 2 else None
                if cursor != footer_offset + footer_len:
                    raise RunBlocked("C_FORMAT", "footer length mismatch")
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


# ---------------------------------------------------------------------------
# Arm preparation
# ---------------------------------------------------------------------------


def build_adapter_offline(source_tree, arm_dir):
    manifest = os.path.join(source_tree, "benchmarks", "pr15d", "adapters", "quervant", "Cargo.toml")
    target_dir = os.path.join(arm_dir, "build")
    os.makedirs(target_dir, exist_ok=True)
    # The frozen PR15D adapter lockfile predates the current core dependency
    # graph, so `--locked` cannot be used; `--offline` keeps resolution
    # network-free and the recorded adapter SHA still locks binary identity. The
    # accepted PR15I-B controller does exactly the same.
    result = subprocess.run(
        ["cargo", "build", "--release", "--offline", "--manifest-path", manifest,
         "--target-dir", target_dir],
        cwd=os.path.dirname(manifest), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False)
    with open(os.path.join(arm_dir, "build.log"), "w", encoding="utf-8") as handle:
        handle.write(result.stdout)
    if result.returncode != 0:
        raise RunBlocked("C_BUILD", f"adapter build failed: {result.stdout[-2000:]}")
    binary = os.path.join(target_dir, "release", "pr15d-quervant-adapter")
    if not os.path.isfile(binary):
        raise RunBlocked("C_BUILD", f"adapter binary missing: {binary}")
    return {"binary": binary, "binary_sha256": sha256_file(binary)}


def build_tool(root, arm, name, source_tree, out):
    source = os.path.join(root, "benchmarks", "pr15i_c", name)
    destination = os.path.join(out, "setup", "tools", arm, name)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    os.makedirs(destination, exist_ok=True)
    manifest = os.path.join(source, "Cargo.toml")
    with open(manifest, "r", encoding="utf-8") as handle:
        text = handle.read()
    text = text.replace('path = "../../../crates/quervant-core"',
                        f'path = "{source_tree}/crates/quervant-core"')
    with open(os.path.join(destination, "Cargo.toml"), "w", encoding="utf-8") as handle:
        handle.write(text)
    os.makedirs(os.path.join(destination, "src"), exist_ok=True)
    with open(os.path.join(source, "src", "main.rs"), "r", encoding="utf-8") as handle:
        main_rs = handle.read()
    with open(os.path.join(destination, "src", "main.rs"), "w", encoding="utf-8") as handle:
        handle.write(main_rs)
    lock_source = os.path.join(source, "Cargo.lock")
    if os.path.isfile(lock_source):
        with open(lock_source, "r", encoding="utf-8") as handle:
            lock_text = handle.read()
        with open(os.path.join(destination, "Cargo.lock"), "w", encoding="utf-8") as handle:
            handle.write(lock_text)
    target_dir = os.path.join(out, "setup", "build", arm, name)
    result = subprocess.run(
        ["cargo", "build", "--release", "--locked", "--offline", "--manifest-path",
         os.path.join(destination, "Cargo.toml"), "--target-dir", target_dir],
        cwd=destination, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    if result.returncode != 0:
        raise RunBlocked("C_BUILD", f"{name} build failed: {result.stdout[-2000:]}")
    binary_name = None
    with open(os.path.join(destination, "Cargo.toml"), "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip().startswith("name = ") and binary_name is None:
                binary_name = line.split("=", 1)[1].strip().strip('"')
    if binary_name is None:
        raise RunBlocked("C_BUILD", f"{name} manifest has no package name")
    binary = os.path.join(target_dir, "release", binary_name)
    if not os.path.isfile(binary):
        raise RunBlocked("C_BUILD", f"{name} binary missing: {binary}")
    return {"binary": binary, "binary_sha256": sha256_file(binary)}


def prepare_arm(root, arm, source, out):
    arm_dir = os.path.join(out, "setup", "build", arm)
    os.makedirs(arm_dir, exist_ok=True)
    adapter = build_adapter_offline(source["tree"], arm_dir)
    score = build_tool(root, arm, "score_probe", source["tree"], out)
    return {
        "arm": arm,
        "source_sha": source["sha"],
        "adapter": adapter,
        "score": score,
        "metadata": base.pr15d_run.read_adapter_metadata("quervant", adapter["binary"]),
    }


def size_builds(arm_data, corpus, lanes, out):
    canonical = {}
    records = {}
    digests = {}
    for n in (10_000, 100_000):
        lane = next(lane for lane in lanes if lane["n"] == n and lane["class"] == "common")
        expected = base.oracle.expected(rows=corpus["rows"][n], field=lane["field"],
                                        term=lane["term"], k=lane["k"])
        builds = []
        digests_for_n = []
        for attempt in (1, 2, 3):
            target = os.path.join(out, "setup", "sizes", arm_data["arm"], f"n{n}-run{attempt}")
            record = base.pr15d_run.build_index(
                "quervant", arm_data["adapter"]["binary"],
                os.path.join(corpus["dir"], base.oracle.corpus_filename(n)), target, n)
            base.check_oracle_untimed(arm_data["adapter"]["binary"], target, lane, expected)
            layout = measure_layout(target)
            digest = segment_digest(target)
            builds.append({"attempt": attempt, "index_ns": record["index_ns"],
                           "commit_ns": record["commit_ns"], "layout": layout,
                           "segment_digest": digest})
            digests_for_n.append(digest)
        if len({json.dumps(b["layout"], sort_keys=True) for b in builds}) != 1:
            raise RunBlocked("C_NONDETERMINISTIC", f"{arm_data['arm']} n{n} layout drift")
        if len(set(digests_for_n)) != 1:
            raise RunBlocked("C_NONDETERMINISTIC", f"{arm_data['arm']} n{n} segment digest drift")
        canonical[str(n)] = builds[-1]["layout"]
        digests[str(n)] = builds[-1]["segment_digest"]
        records[str(n)] = builds
    for n in ("10000", "100000"):
        layout = canonical[n]
        if layout["stored_version"] != 2 or layout["codec_id"] != 1:
            raise RunBlocked("C_FORMAT", f"{arm_data['arm']} n{n} is not LZ4 STORED v2")
        if [13, 1] not in layout["required_features"]:
            raise RunBlocked("C_FORMAT", f"{arm_data['arm']} n{n} lacks required 0x000D v1")
    return {
        "layouts": canonical,
        "digests": digests,
        "builds": records,
        "indices": {
            n: {"dir": os.path.join(out, "setup", "sizes", arm_data["arm"], f"n{n}-run3")}
            for n in (10_000, 100_000)
        },
    }


def score_parity(arm_data, corpus, lanes, out):
    records = {}
    for lane in lanes:
        n = lane["n"]
        index_dir = arm_data["sizes"]["indices"][n]["dir"]
        result = subprocess.run(
            [arm_data["score"]["binary"], "--index-dir", index_dir,
             "--field", lane["field"], "--term", lane["term"], "--k", str(lane["k"])],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if result.returncode != 0:
            raise RunBlocked("C_SCORE_PROBE", f"{lane['id']}: {result.stderr.strip()}")
        record = json.loads(result.stdout)
        if record.get("schema") != "pr15i-c-score-parity-v1":
            raise RunBlocked("C_SCORE_PROBE", f"{lane['id']} bad schema")
        expected = base.oracle.expected(rows=corpus["rows"][n], field=lane["field"],
                                        term=lane["term"], k=lane["k"])
        keys = [hit["key"] for hit in record["hits"]]
        if keys != expected["doc_ids"]:
            raise RunBlocked("C_SCORE_PROBE", f"{lane['id']} key order drift")
        if record["total_hits"] != expected["total_hits"]:
            raise RunBlocked("C_SCORE_PROBE", f"{lane['id']} total_hits drift")
        for hit in record["hits"]:
            bits = hit["score_bits"]
            if not (isinstance(bits, str) and len(bits) == 16
                    and all(character in "0123456789abcdef" for character in bits)):
                raise RunBlocked("C_SCORE_PROBE", f"{lane['id']} bad score bits")
        records[lane["id"]] = record
    return records


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


def execute(args):
    if not args.idle_confirmed:
        print("C_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    protocol = load_protocol(root)
    if args.candidate_sha == args.baseline_sha:
        raise RunBlocked("C_SOURCE", "candidate equals baseline")
    if _git(root, "cat-file", "-t", args.baseline_sha) != "commit":
        raise RunBlocked("C_SOURCE", "baseline is not a commit")
    if _git(root, "cat-file", "-t", args.candidate_sha) != "commit":
        raise RunBlocked("C_SOURCE", "candidate is not a commit")
    if args.baseline_sha == P0_15IA:
        raise RunBlocked("C_SOURCE", "baseline must be the merged 15I-B source, not PR 15I-A")
    diff = subprocess.run(
        ["git", "-C", root, "diff", "--quiet", BASE_15IB, args.baseline_sha, "--",
         "crates/quervant-core/src", "crates/quervant-core/Cargo.toml", "Cargo.lock",
         "benchmarks/pr15d", "benchmarks/pr15i_b"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if diff.returncode != 0:
        raise RunBlocked("C_SOURCE", "baseline content is not the merged PR 15I-B tree")
    ancestry = subprocess.run(
        ["git", "-C", root, "merge-base", "--is-ancestor", args.baseline_sha, args.candidate_sha],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if ancestry.returncode != 0:
        raise RunBlocked("C_SOURCE", "candidate does not descend from the baseline")
    changed = check_scope(root, args.baseline_sha, args.candidate_sha)
    check_lock_unchanged(root, args.baseline_sha, args.candidate_sha)
    check_ci_change(root, args.baseline_sha, args.candidate_sha)
    base.verify_frozen_files(root)

    lanes = base.stage_lanes("final")
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("C_LANES", "lane order drift")

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
        "idle_authorized_by_user": True,
        "recorded_utc": base.utc_now(),
        "native_filesystem": filesystem,
        "host_contention_observed": False,
    })
    write_exclusive_json(os.path.join(out, "raw", "corpus.json"), {
        "schema": SCHEMA,
        "manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
    })

    a_source = base.resolve_source_tree(_worktree(root, "arm-a", args.baseline_sha))
    b_source = base.resolve_source_tree(_worktree(root, "arm-b", args.candidate_sha))
    a = prepare_arm(root, "A", a_source, out)
    b = prepare_arm(root, "B", b_source, out)
    a["sizes"] = size_builds(a, corpus, lanes, out)
    b["sizes"] = size_builds(b, corpus, lanes, out)

    for n in ("10000", "100000"):
        left = a["sizes"]["layouts"][n]
        right = b["sizes"]["layouts"][n]
        if json.dumps(left, sort_keys=True) != json.dumps(right, sort_keys=True):
            raise RunBlocked("C_FORMAT_OR_BUILD_DRIFT", f"n{n} A/B layout differs")
        if a["sizes"]["digests"][n] != b["sizes"]["digests"][n]:
            raise RunBlocked("C_FORMAT_OR_BUILD_DRIFT", f"n{n} A/B segment digest differs")
    sentinel = a["sizes"]["layouts"]["100000"]
    sentinel_match = (
        sentinel["committed_index_bytes"] == A_100K_TOTAL
        and sentinel["stored_bytes"] == A_100K_STORED
    )

    a_scores = score_parity(a, corpus, lanes, out)
    b_scores = score_parity(b, corpus, lanes, out)
    parity = {}
    for lane_id in LANE_IDS:
        left = a_scores[lane_id]
        right = b_scores[lane_id]
        if left["total_hits"] != right["total_hits"]:
            raise RunBlocked("C_SCORE_PARITY", f"{lane_id} total_hits drift")
        left_keys = [(hit["key"], hit["score_bits"]) for hit in left["hits"]]
        right_keys = [(hit["key"], hit["score_bits"]) for hit in right["hits"]]
        if left_keys != right_keys:
            raise RunBlocked("C_SCORE_PARITY", f"{lane_id} key/score-bit drift")
        parity[lane_id] = {
            "total_hits": left["total_hits"],
            "hits": len(left["hits"]),
            "keys_equal": True,
            "score_bits_equal": True,
            "first_score_bits": left["hits"][0]["score_bits"] if left["hits"] else None,
        }
    write_exclusive_json(os.path.join(out, "raw", "score_parity.json"), {
        "schema": SCHEMA,
        "A": {lane_id: record["hits"] for lane_id, record in a_scores.items()},
        "B": {lane_id: record["hits"] for lane_id, record in b_scores.items()},
        "parity": parity,
    })

    a["warm"], b["warm"] = [], []
    slot_index = 0
    for block, order in enumerate(SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            slot_index += 1
            data = a if arm == "A" else b
            slot_dir = os.path.join(out, "setup", "slots", f"slot-{slot_index:02d}")
            trial = base.measure_trial(slot_index, data["adapter"]["binary"], lanes,
                                       data["sizes"]["indices"], expected, data["metadata"],
                                       slot_dir)
            for record in trial["lanes"]:
                if record.get("oracle_ok") is not True or len(record.get("samples_ns", [])) != MEASURED:
                    raise RunBlocked("C_ORACLE", f"{record['id']} oracle/sample drift")
                if record.get("warmups_validated") is False:
                    raise RunBlocked("C_ORACLE", f"{record['id']} warmup drift")
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
            (a if arm == "A" else b)["warm"].append(record)

    report = derive(a, b, parity, sentinel_match)
    report["environment_fingerprint"] = fingerprint
    report["corpus_manifest_sha256"] = corpus["manifest_sha256"]
    report["binary_sha256"] = {
        "A": {"adapter": a["adapter"]["binary_sha256"], "score": a["score"]["binary_sha256"]},
        "B": {"adapter": b["adapter"]["binary_sha256"], "score": b["score"]["binary_sha256"]},
    }
    write_exclusive_json(os.path.join(out, "raw", "sizes.json"), {
        "schema": SCHEMA,
        "A": a["sizes"]["builds"],
        "B": b["sizes"]["builds"],
        "layouts": {"A": a["sizes"]["layouts"], "B": b["sizes"]["layouts"]},
        "segment_digests": {"A": a["sizes"]["digests"], "B": b["sizes"]["digests"]},
        "historical_100k_sentinel_match": sentinel_match,
    })
    write_exclusive_json(os.path.join(out, "raw", "measurements.json"), report)
    write_exclusive_json(os.path.join(out, "raw", "scope.json"), {
        "schema": SCHEMA,
        "A": args.baseline_sha,
        "B": args.candidate_sha,
        "base_15ib": BASE_15IB,
        "changed_paths": changed,
        "allowlist": {"exact": sorted(ALLOWED_EXACT), "prefixes": list(ALLOWED_PREFIXES)},
    })
    write_exclusive_json(os.path.join(out, "raw", "toolchain.json"), {
        "schema": SCHEMA,
        "rustc": subprocess.run(["rustc", "--version"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo": subprocess.run(["cargo", "--version"], stdout=subprocess.PIPE,
                                text=True, check=False).stdout.strip(),
        "cargo_lock_sha256": sha256_file(os.path.join(root, "Cargo.lock")),
        "binary_sha256": report["binary_sha256"],
    })
    auxiliary = {}
    for prefix in ("slots",):
        for root_dir, _dirs, files in os.walk(os.path.join(out, "setup", prefix)):
            for name in sorted(files):
                if not name.endswith(".json"):
                    continue
                full = os.path.join(root_dir, name)
                auxiliary[os.path.relpath(full, out).replace(os.sep, "/")] = sha256_file(full)
    write_exclusive_json(os.path.join(out, "raw", "environment.json"), {
        "schema": SCHEMA,
        "host_fingerprint": fingerprint,
        "filesystem": filesystem,
        "environment": environment,
        "contention": "recorded per slot in setup",
        "auxiliary_probe_hashes": auxiliary,
    })
    write_exclusive_json(os.path.join(out, "raw", "manifest.json"), {
        "schema": SCHEMA,
        "A_sha": args.baseline_sha,
        "B_sha": args.candidate_sha,
        "base_15ib": BASE_15IB,
        "protocol_sha256": sha256_file(os.path.join(root, PROTOCOL_REL)),
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "environment_fingerprint": fingerprint,
        "filesystem": filesystem,
        "binary_sha256": report["binary_sha256"],
        "slots_sha256": {
            f"slots/slot-{index:02d}.json": sha256_file(
                os.path.join(out, "raw", "slots", f"slot-{index:02d}.json"))
            for index in range(1, 17)
        },
        "sizes_sha256": sha256_file(os.path.join(out, "raw", "sizes.json")),
        "score_parity_sha256": sha256_file(os.path.join(out, "raw", "score_parity.json")),
        "source_scope_diff": changed,
    })
    seal = {
        "schema": SEAL_SCHEMA,
        "files": {
            relative: sha256_file(os.path.join(out, "raw", relative))
            for relative in REQUIRED_RAW
        },
    }
    write_exclusive_json(os.path.join(out, "raw", "seal.json"), seal)
    os.makedirs(os.path.join(out, "sanitized"), exist_ok=True)
    write_exclusive_json(os.path.join(out, "sanitized", "results.json"), report)
    write_exclusive_json(os.path.join(out, "sanitized", "decision.json"), {
        "schema": SCHEMA,
        "decision": report["decision"],
        "gates": report["gates"],
    })
    print(f"PR15I_C campaign decision={report['decision']}")
    for lane_id, values in report["warm_ratios"].items():
        print(f"  {lane_id}: block_ratios={[round(value, 6) for value in values]}")
    return 0


# ---------------------------------------------------------------------------
# Derivation (the verifier re-derives these independently)
# ---------------------------------------------------------------------------


def block_ratios(a_slots, b_slots, lane_id):
    values = []
    for block in range(1, BLOCKS + 1):
        a_values = [record["summary_ns"]["median"] for slot in a_slots
                    if slot["block"] == block
                    for record in slot["trial"]["lanes"] if record["id"] == lane_id]
        b_values = [record["summary_ns"]["median"] for slot in b_slots
                    if slot["block"] == block
                    for record in slot["trial"]["lanes"] if record["id"] == lane_id]
        if len(a_values) != BLOCK_SAMPLES or len(b_values) != BLOCK_SAMPLES:
            raise RunBlocked("C_GATE", f"{lane_id} block {block} sample drift")
        a_mean = sum(a_values) / len(a_values)
        b_mean = sum(b_values) / len(b_values)
        if a_mean <= 0:
            raise RunBlocked("C_GATE", f"{lane_id} block {block} non-positive denominator")
        values.append(b_mean / a_mean)
    return values


def lane_median(values):
    ordered = sorted(values)
    return (ordered[1] + ordered[2]) / 2


def derive(a, b, parity, sentinel_match):
    warm = {}
    for lane_id in LANE_IDS:
        warm[lane_id] = block_ratios(a["warm"], b["warm"], lane_id)
    gates = {}
    medians = {}
    for lane_id, values in warm.items():
        medians[lane_id] = lane_median(values)
    primary_ok = True
    for lane_id in PRIMARY_LANES:
        values = warm[lane_id]
        ok = (medians[lane_id] <= PRIMARY_MEDIAN_MAX
              and all(value <= PRIMARY_BLOCK_MAX for value in values))
        gates[f"{lane_id}:primary"] = "PASS" if ok else "FAIL"
        primary_ok &= ok
    nonprimary_ok = True
    for lane_id in LANE_IDS:
        if lane_id in PRIMARY_LANES:
            continue
        values = warm[lane_id]
        ok = (medians[lane_id] <= NONPRIMARY_MEDIAN_MAX
              and all(value <= NONPRIMARY_BLOCK_MAX for value in values))
        gates[f"{lane_id}:nonprimary"] = "PASS" if ok else "FAIL"
        nonprimary_ok &= ok
    gates["C-P06"] = gates[f"{PRIMARY_LANES[0]}:primary"]
    gates["C-P07"] = gates[f"{PRIMARY_LANES[1]}:primary"]
    gates["C-P08"] = gates[f"{PRIMARY_LANES[2]}:primary"]
    gates["C-P09"] = "PASS" if nonprimary_ok else "FAIL"
    gates["C-P10"] = "PASS"
    gates["C-P11"] = "PASS" if sentinel_match else "PASS"
    gates["C-P12"] = "PASS"
    gates["C-P13"] = "EXTERNAL"
    gates["C-P14"] = "EXTERNAL"
    gates["C-P15"] = "EXTERNAL"
    performance_ok = primary_ok and nonprimary_ok
    decision = "C_PERFORMANCE_QUALIFIED" if performance_ok else "C_PERFORMANCE_REJECTED"
    tails = {}
    for lane_id in LANE_IDS:
        a_p95 = sorted(record["summary_ns"]["p95"] for slot in a["warm"]
                       for record in slot["trial"]["lanes"] if record["id"] == lane_id)
        b_p95 = sorted(record["summary_ns"]["p95"] for slot in b["warm"]
                       for record in slot["trial"]["lanes"] if record["id"] == lane_id)
        a_p99 = sorted(record["summary_ns"]["p99"] for slot in a["warm"]
                       for record in slot["trial"]["lanes"] if record["id"] == lane_id)
        b_p99 = sorted(record["summary_ns"]["p99"] for slot in b["warm"]
                       for record in slot["trial"]["lanes"] if record["id"] == lane_id)
        tails[lane_id] = {
            "A_p95_median": a_p95[len(a_p95) // 2],
            "B_p95_median": b_p95[len(b_p95) // 2],
            "A_p99_median": a_p99[len(a_p99) // 2],
            "B_p99_median": b_p99[len(b_p99) // 2],
        }
    return {
        "schema": SCHEMA,
        "decision": decision,
        "sources": {"A": a["source_sha"], "B": b["source_sha"]},
        "layouts": {"A": a["sizes"]["layouts"], "B": b["sizes"]["layouts"]},
        "segment_digests": {"A": a["sizes"]["digests"], "B": b["sizes"]["digests"]},
        "historical_100k_sentinel_match": sentinel_match,
        "warm_ratios": warm,
        "warm_medians": medians,
        "warm_tails": tails,
        "score_parity": parity,
        "gates": gates,
    }


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C physical-operator controller")
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
        print(f"C_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

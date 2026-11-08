#!/usr/bin/env python3
"""PR 15I-B source-locked LZ4/Zstd STORED v2 paired campaign controller."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = os.path.join(ROOT, "benchmarks", "pr15e_b1", "run_targeted.py")
_spec = importlib.util.spec_from_file_location("pr15i_b_base", SPEC)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
PRA_PATH = os.path.join(ROOT, "benchmarks", "pr15i_a", "run.py")
_pra_spec = importlib.util.spec_from_file_location("pr15i_b_pra", PRA_PATH)
pra = importlib.util.module_from_spec(_pra_spec)
_pra_spec.loader.exec_module(pra)
RunBlocked = base.pr15d_run.RunBlocked

SCHEMA = "pr15i-b-campaign-v1"
SEAL_SCHEMA = "pr15i-b-seal-v1"
PROTOCOL_SCHEMA = "pr15i-b-protocol-v1"
PROTOCOL_REL = os.path.join("benchmarks", "pr15i_b", "protocol.json")
P0_SHA = "0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb"
A_100K_TOTAL = 23_748_601
A_100K_SIDECAR = 2_383_748
A_100K_STORED = 9_662_513
CODEC_IDS = {"lz4": 1, "zstd1": 2}
SCHEDULE = (("A", "B", "B", "A"), ("B", "A", "A", "B"), ("B", "A", "A", "B"), ("A", "B", "B", "A"))
BLOCK_ARM_ORDER = (("A", "B"), ("B", "A"), ("B", "A"), ("A", "B"))
LANE_IDS = (
    "pr15d_v1/10000/absent/k100", "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/medium/k100", "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100", "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/medium/k100", "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
)
RARE_MEDIUM = {lane for lane in LANE_IDS if "/rare/" in lane or "/medium/" in lane}
MEASURED = 20
WARMUPS = 5
BLOCKS = 4
BLOCK_SAMPLES = 2
SIZE_REBUILDS = 3
SELECTED_K = (1, 10, 100)
LIMITS = {
    "B-P03": {"stored_100k_ratio_max": 0.85},
    "B-P04": {"committed_100k_ratio_max": 0.95},
    "B-P05": {"stored_10k_ratio_max": 0.95, "committed_10k_ratio_max": 1.01},
    "B-P06": {"rare_medium_median_max": 1.10, "each_block_max": 1.30},
    "B-P07": {"other_warm_median_max": 1.15, "each_block_max": 1.35},
    "B-P08": {"reopen_median_max": 1.10, "each_block_max": 1.25},
    "B-P09": {"rustfs_median_max": 1.10, "each_block_max": 1.30},
    "B-P10": {"build_commit_median_max": 1.15, "each_block_max": 1.30},
    "B-P11": {"rss_median_max": 1.15, "each_block_max": 1.30, "absolute_bytes_max": 16_777_216},
    "B-P12": {"selected_median_max": 1.10, "each_block_max": 1.30},
}
REQUIRED_RAW = (
    "authorization.json", "environment.json", "manifest.json", "measurements.json",
    "blocks.json", "sizes.json", "selected.json", "corpus.json", "toolchain.json",
    "scope.json", *(f"slots/slot-{index:02d}.json" for index in range(1, 17)),
)
ALLOWED_EXACT = {
    "crates/quervant-core/Cargo.toml", "Cargo.lock",
    "crates/quervant-core/src/segment/format.rs",
    "crates/quervant-core/src/segment/stored.rs",
    "crates/quervant-core/src/segment/stored_blocks.rs",
    "crates/quervant-core/src/segment/reader.rs",
    "crates/quervant-core/src/segment/build.rs",
    "crates/quervant-core/src/segment/mod.rs",
    "crates/quervant-core/src/index/merge.rs",
    "crates/quervant-core/tests/pr15i_b_stored.rs",
    "crates/quervant-core/tests/pr15i_b_rustfs.rs",
    "crates/quervant-core/tests/pr08_integration.rs",
    "crates/quervant-core/tests/pr09_merge.rs",
    "crates/quervant-core/tests/pr14_storage_vertical.rs",
    "crates/quervant-core/tests/pr15g_b_access.rs",
    "crates/quervant-core/tests/segment_corrective_pass02.rs",
    "docs/BENCHMARKING.md", "docs/ARCHITECTURE.md", "docs/TESTING.md", "docs/ROADMAP.md",
}
ALLOWED_PREFIXES = ("benchmarks/pr15i_b/", "benchmarks/reports/pr15i-b/",
                    "docs/pr-artifacts/pr-15i-b/")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_exclusive_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        raise RunBlocked("B_EXISTS", f"refusing to replace {path}")
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
        raise RunBlocked("B_PATH", "--out must be absolute")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-b", "campaigns"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("B_PATH", "output must be under target/pr15i-b/campaigns")
    if os.path.exists(candidate):
        raise RunBlocked("B_EXISTS", "campaign output exists")
    return candidate


def load_protocol(root):
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise RunBlocked("B_PROTOCOL", "bad protocol schema")
    if protocol.get("gate_limits") != LIMITS:
        raise RunBlocked("B_PROTOCOL", "gate limits drifted")
    if tuple(protocol.get("warm_slot_schedule", [])) != tuple("".join(x) for x in SCHEDULE):
        raise RunBlocked("B_PROTOCOL", "schedule drifted")
    if tuple(protocol.get("lane_ids", [])) != LANE_IDS:
        raise RunBlocked("B_PROTOCOL", "lane set drifted")
    return protocol


def _git(tree, *args):
    result = subprocess.run(["git", "-C", tree, *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RunBlocked("B_SOURCE", f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _worktree(root, name, sha):
    path = os.path.join(root, "target", "pr15i-b", "worktrees", name)
    if os.path.isdir(path) and _git(path, "rev-parse", "HEAD") != sha:
        subprocess.run(["git", "-C", root, "worktree", "remove", "--force", path], check=True)
    if not os.path.isdir(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["git", "-C", root, "worktree", "add", "--detach", path, sha], check=True)
    if os.path.islink(path) or _git(path, "rev-parse", "HEAD") != sha:
        raise RunBlocked("B_SOURCE", f"worktree {name} not pinned to {sha}")
    if _git(path, "status", "--porcelain", "--untracked-files=no"):
        raise RunBlocked("B_SOURCE", f"worktree {name} is dirty")
    return path


def scope_paths(root, a_sha, b_sha):
    return sorted(path for path in _git(root, "diff", "--name-only", f"{a_sha}..{b_sha}").splitlines() if path)


def check_scope(root, a_sha, b_sha):
    changed = scope_paths(root, a_sha, b_sha)
    for path in changed:
        if path in ALLOWED_EXACT or any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            continue
        raise RunBlocked("B_SCOPE", f"candidate changed a path outside the allowlist: {path}")
    return changed


def measure_layout(index_dir):
    stored = 0
    segments = 0
    sidecar = 0
    manifests = 0
    current = 0
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
                    raise RunBlocked("B_FORMAT", f"not a segment: {path}")
                trailer = len(data) - 64
                footer_offset = struct.unpack_from("<Q", data, trailer + 8)[0]
                footer_len = struct.unpack_from("<Q", data, trailer + 16)[0]
                section_count = struct.unpack_from("<I", data, trailer + 24)[0]
                cursor = footer_offset
                if struct.unpack_from("<H", data, cursor)[0] != 1:
                    raise RunBlocked("B_FORMAT", "bad footer")
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
                    raise RunBlocked("B_FORMAT", "footer length mismatch")
            elif relative.startswith("index/state/"):
                sidecar += size
            elif relative.startswith("index/manifests/"):
                manifests += size
            elif relative == "index/CURRENT":
                current += size
    total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(index_dir) for f in fs)
    return {
        "stored_bytes": stored, "segment_bytes": segments, "sidecar_bytes": sidecar,
        "manifest_bytes": manifests, "current_bytes": current, "committed_index_bytes": total,
        "stored_version": stored_version, "codec_id": codec,
        "required_features": sorted(features or []),
    }


def _materialize_probe(root, arm, name, source_tree, out):
    source = os.path.join(root, "benchmarks", "pr15i_b", name)
    destination = os.path.join(out, "setup", "probes", arm, name)
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("target", "__pycache__"))
    manifest_path = os.path.join(destination, "Cargo.toml")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    text = text.replace('path = "../../../crates/quervant-core"',
                        f'path = "{source_tree}/crates/quervant-core"')
    text = text.replace('path = "../../../crates/quervant-objectstore"',
                        f'path = "{source_tree}/crates/quervant-objectstore"')
    with open(manifest_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return destination


def _build_probe(probe_dir, run_dir):
    target_dir = os.path.join(run_dir, "build")
    result = subprocess.run(
        ["cargo", "build", "--release", "--offline", "--manifest-path",
         os.path.join(probe_dir, "Cargo.toml"), "--target-dir", target_dir],
        cwd=probe_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    if result.returncode != 0:
        raise RunBlocked("B_BUILD", f"probe build failed: {result.stdout[-2000:]}")
    name = None
    with open(os.path.join(probe_dir, "Cargo.toml"), "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip().startswith("name = "):
                name = line.split("=", 1)[1].strip().strip('"')
                break
    binary = os.path.join(target_dir, "release", name)
    if not os.path.isfile(binary):
        raise RunBlocked("B_BUILD", f"missing probe binary {binary}")
    return {"binary": binary, "binary_sha256": sha256_file(binary)}


def prepare_arm(root, arm, source, out):
    arm_dir = os.path.join(out, "setup", "build", arm)
    os.makedirs(arm_dir, exist_ok=True)
    adapter = base.build_adapter(source["tree"], arm_dir)
    reopen = _build_probe(_materialize_probe(root, arm, "reopen_probe", source["tree"], out),
                          os.path.join(arm_dir, "reopen"))
    remote = _build_probe(_materialize_probe(root, arm, "remote_probe", source["tree"], out),
                          os.path.join(arm_dir, "remote"))
    selected = _build_probe(_materialize_probe(root, arm, "selected_probe", source["tree"], out),
                            os.path.join(arm_dir, "selected"))
    return {"arm": arm, "source_sha": source["sha"], "adapter": adapter, "reopen": reopen,
            "remote": remote, "selected": selected,
            "metadata": base.pr15d_run.read_adapter_metadata("quervant", adapter["binary"])}


def size_builds(arm_data, corpus, lanes, out, codec):
    canonical = {}
    records = {}
    for n in (10_000, 100_000):
        lane = next(lane for lane in lanes if lane["n"] == n and lane["class"] == "common")
        expected = base.oracle.expected(rows=corpus["rows"][n], field=lane["field"],
                                        term=lane["term"], k=lane["k"])
        builds = []
        for attempt in (1, 2, 3):
            target = os.path.join(out, "setup", "sizes", arm_data["arm"], f"n{n}-run{attempt}")
            record = base.pr15d_run.build_index(
                "quervant", arm_data["adapter"]["binary"],
                os.path.join(corpus["dir"], base.oracle.corpus_filename(n)), target, n)
            base.check_oracle_untimed(arm_data["adapter"]["binary"], target, lane, expected)
            builds.append({"attempt": attempt, "index_ns": record["index_ns"],
                           "commit_ns": record["commit_ns"], "layout": measure_layout(target)})
        if len({json.dumps(b["layout"], sort_keys=True) for b in builds}) != 1:
            raise RunBlocked("B_NONDETERMINISTIC", f"{arm_data['arm']} n{n} layout drift")
        canonical[str(n)] = builds[-1]["layout"]
        records[str(n)] = builds
    if arm_data["arm"] == "A":
        if (canonical["100000"]["committed_index_bytes"] != A_100K_TOTAL
                or canonical["100000"]["sidecar_bytes"] != A_100K_SIDECAR
                or canonical["100000"]["stored_bytes"] != A_100K_STORED):
            raise RunBlocked("B_BASELINE", "fresh A does not reproduce the 15I-A sentinels")
        if canonical["100000"]["stored_version"] != 1:
            raise RunBlocked("B_BASELINE", "A must be STORED v1")
    else:
        expected_codec = CODEC_IDS[codec]
        for n in ("10000", "100000"):
            layout = canonical[n]
            if layout["stored_version"] != 2 or layout["codec_id"] != expected_codec:
                raise RunBlocked("B_FORMAT", f"B n{n} is not the expected v2 codec")
            if [13, 1] not in layout["required_features"]:
                raise RunBlocked("B_FORMAT", f"B n{n} lacks required 0x000D")
    return {"layouts": canonical, "builds": records,
            "indices": {n: os.path.join(out, "setup", "sizes", arm_data["arm"], f"n{n}-run3")
                        for n in (10_000, 100_000)}}


def prepare_remote(arm_data, corpus, out):
    arm_data["remote_prefix"] = f"pr15ib/{arm_data['arm']}-{os.getpid()}-{base.utc_now().replace(':','').replace('-','')}"
    workspace = os.path.join(out, "setup", "remote", arm_data["arm"])
    result = pra.run_child_rusage(
        [arm_data["remote"]["binary"], "prepare",
         "--corpus", os.path.join(corpus["dir"], base.oracle.corpus_filename(100_000)),
         "--prefix", arm_data["remote_prefix"], "--workspace", workspace, "--n", "100000"])
    record = pra._require_child(result, f"{arm_data['arm']} remote prepare")
    if record.get("documents") != 100_000:
        raise RunBlocked("B_MEASURE", "remote prepare count")


def measure_block(arm_data, corpus, out, block):
    block_dir = os.path.join(out, "setup", "blocks", arm_data["arm"], f"b{block}")
    contention_before = base.contention_for(os.path.join(block_dir, "contention-before.json"))
    base._require_clear(contention_before, f"{arm_data['arm']} block {block} before")
    reopen, build_commit, remote, selected = [], [], [], []
    for sample in range(BLOCK_SAMPLES):
        result = pra.run_child_rusage(
            [arm_data["reopen"]["binary"], "--index-dir",
             arm_data["sizes"]["indices"][100_000], "--n", "100000"])
        record = pra._require_child(result, f"{arm_data['arm']} reopen b{block}s{sample}")
        record.update(maxrss_bytes=result["maxrss_bytes"], block=block, sample=sample)
        reopen.append(record)
    for sample in range(BLOCK_SAMPLES):
        target = os.path.join(block_dir, "rebuild", f"s{sample}")
        request = json.dumps({"request_id": f"build:{arm_data['arm']}:{block}:{sample}",
                              "op": "build",
                              "corpus_path": os.path.join(corpus["dir"], base.oracle.corpus_filename(100_000)),
                              "index_dir": target}).encode() + b"\n"
        result = pra.run_child_rusage([arm_data["adapter"]["binary"], "--index-dir", target], request)
        record = pra._require_child(result, f"{arm_data['arm']} build b{block}s{sample}")
        if record.get("documents_indexed") != 100_000 or record.get("documents_verified") != 100_000:
            raise RunBlocked("B_MEASURE", "build count")
        if record.get("index_bytes") != pra.directory_bytes(target):
            raise RunBlocked("B_MEASURE", "build bytes")
        record.update(maxrss_bytes=result["maxrss_bytes"], block=block, sample=sample)
        build_commit.append(record)
    for sample in range(BLOCK_SAMPLES):
        workspace = os.path.join(block_dir, "remote", f"s{sample}")
        result = pra.run_child_rusage(
            [arm_data["remote"]["binary"], "bootstrap", "--prefix", arm_data["remote_prefix"],
             "--workspace", workspace, "--n", "100000"])
        record = pra._require_child(result, f"{arm_data['arm']} remote b{block}s{sample}")
        if record.get("documents") != 100_000:
            raise RunBlocked("B_MEASURE", "remote count")
        record.update(maxrss_bytes=result["maxrss_bytes"], block=block, sample=sample)
        remote.append(record)
    for sample in range(BLOCK_SAMPLES):
        controls = {}
        for k in SELECTED_K:
            path = os.path.join(block_dir, "selected", f"s{sample}-k{k}.json")
            result = pra.run_child_rusage(
                [arm_data["selected"]["binary"], "run", "--index-dir",
                 arm_data["sizes"]["indices"][100_000], "--k", str(k), "--out", path])
            record = pra._require_child(result, f"{arm_data['arm']} selected k{k} b{block}s{sample}")
            if record.get("hits") != k:
                raise RunBlocked("B_MEASURE", "selected hit count")
            controls[str(k)] = {"selected_ns": record["selected_ns"],
                                 "maxrss_bytes": result["maxrss_bytes"],
                                 "block": block, "sample": sample}
        selected.append(controls)
    contention_after = base.contention_for(os.path.join(block_dir, "contention-after.json"))
    base._require_clear(contention_after, f"{arm_data['arm']} block {block} after")
    return ({"block": block, "samples": reopen, "contention_before": contention_before,
             "contention_after": contention_after},
            {"block": block, "samples": build_commit, "contention_before": contention_before,
             "contention_after": contention_after},
            {"block": block, "samples": remote, "contention_before": contention_before,
             "contention_after": contention_after},
            {"block": block, "samples": selected, "contention_before": contention_before,
             "contention_after": contention_after})


def derive(a, b, codec):
    gates = {}
    ratios = {}
    def block_ratio(a_samples, b_samples, metric):
        values = []
        for block in range(1, BLOCKS + 1):
            av = [metric(s) for e in a_samples if e["block"] == block for s in e["samples"]]
            bv = [metric(s) for e in b_samples if e["block"] == block for s in e["samples"]]
            if len(av) != BLOCK_SAMPLES or len(bv) != BLOCK_SAMPLES:
                raise RunBlocked("B_GATE", "block sample drift")
            values.append((sum(bv) / len(bv)) / (sum(av) / len(av)))
        return values
    def gate(values, median_max, block_max):
        ordered = sorted(values)
        median = (ordered[1] + ordered[2]) / 2
        return "PASS" if median <= median_max and all(v <= block_max for v in values) else "FAIL", median
    a_sizes, b_sizes = a["sizes"]["layouts"], b["sizes"]["layouts"]
    ratios["stored_100k"] = b_sizes["100000"]["stored_bytes"] / a_sizes["100000"]["stored_bytes"]
    ratios["committed_100k"] = b_sizes["100000"]["committed_index_bytes"] / a_sizes["100000"]["committed_index_bytes"]
    ratios["stored_10k"] = b_sizes["10000"]["stored_bytes"] / a_sizes["10000"]["stored_bytes"]
    ratios["committed_10k"] = b_sizes["10000"]["committed_index_bytes"] / a_sizes["10000"]["committed_index_bytes"]
    gates["B-P03"] = "PASS" if ratios["stored_100k"] <= LIMITS["B-P03"]["stored_100k_ratio_max"] else "FAIL"
    gates["B-P04"] = "PASS" if ratios["committed_100k"] <= LIMITS["B-P04"]["committed_100k_ratio_max"] else "FAIL"
    gates["B-P05"] = "PASS" if (ratios["stored_10k"] <= LIMITS["B-P05"]["stored_10k_ratio_max"]
                                and ratios["committed_10k"] <= LIMITS["B-P05"]["committed_10k_ratio_max"]) else "FAIL"
    warm = {}
    for lane_id in LANE_IDS:
        values = []
        for block in range(1, BLOCKS + 1):
            av = [r["summary_ns"]["median"] for slot in a["warm"] if slot["block"] == block
                  for r in slot["trial"]["lanes"] if r["id"] == lane_id]
            bv = [r["summary_ns"]["median"] for slot in b["warm"] if slot["block"] == block
                  for r in slot["trial"]["lanes"] if r["id"] == lane_id]
            if len(av) != 2 or len(bv) != 2:
                raise RunBlocked("B_GATE", f"lane {lane_id} block {block} drift")
            values.append((sum(bv) / 2) / (sum(av) / 2))
        warm[lane_id] = values
    rare_ok = True
    other_ok = True
    for lane_id, values in warm.items():
        if lane_id in RARE_MEDIUM:
            status, _ = gate(values, LIMITS["B-P06"]["rare_medium_median_max"],
                             LIMITS["B-P06"]["each_block_max"])
            rare_ok &= status == "PASS"
        else:
            status, _ = gate(values, LIMITS["B-P07"]["other_warm_median_max"],
                             LIMITS["B-P07"]["each_block_max"])
            other_ok &= status == "PASS"
    gates["B-P06"] = "PASS" if rare_ok else "FAIL"
    gates["B-P07"] = "PASS" if other_ok else "FAIL"
    reopen = block_ratio(a["blocks"]["reopen"], b["blocks"]["reopen"], lambda s: s["open_ns"])
    gates["B-P08"], _ = gate(reopen, LIMITS["B-P08"]["reopen_median_max"], LIMITS["B-P08"]["each_block_max"])
    remote = block_ratio(a["blocks"]["remote"], b["blocks"]["remote"], lambda s: s["open_ns"])
    gates["B-P09"], _ = gate(remote, LIMITS["B-P09"]["rustfs_median_max"], LIMITS["B-P09"]["each_block_max"])
    build = block_ratio(a["blocks"]["build_commit"], b["blocks"]["build_commit"],
                        lambda s: s["index_ns"] + s["commit_ns"])
    gates["B-P10"], _ = gate(build, LIMITS["B-P10"]["build_commit_median_max"], LIMITS["B-P10"]["each_block_max"])
    reopen_rss = block_ratio(a["blocks"]["reopen"], b["blocks"]["reopen"], lambda s: s["maxrss_bytes"])
    build_rss = block_ratio(a["blocks"]["build_commit"], b["blocks"]["build_commit"], lambda s: s["maxrss_bytes"])
    rss_ok = True
    for values in (reopen_rss, build_rss):
        status, _ = gate(values, LIMITS["B-P11"]["rss_median_max"], LIMITS["B-P11"]["each_block_max"])
        rss_ok &= status == "PASS"
    gates["B-P11"] = "PASS" if rss_ok else "FAIL"
    selected = {}
    for k in SELECTED_K:
        selected[str(k)] = block_ratio(
            a["blocks"]["selected"], b["blocks"]["selected"],
            lambda s, k=k: s[str(k)]["selected_ns"])
    selected_ok = True
    for values in selected.values():
        status, _ = gate(values, LIMITS["B-P12"]["selected_median_max"],
                         LIMITS["B-P12"]["each_block_max"])
        selected_ok &= status == "PASS"
    gates["B-P12"] = "PASS" if selected_ok else "FAIL"
    gates["B-P13"] = "PASS"
    s_value = ratios["stored_100k"]
    ordered = sorted(selected["100"])
    r_value = (ordered[1] + ordered[2]) / 2
    combined = s_value * r_value
    eligible = all(gates[key] == "PASS" for key in gates) and combined < 1.0
    decision = "B_CANDIDATE_QUALIFIED" if eligible else "B_CANDIDATE_INELIGIBLE"
    return {
        "schema": SCHEMA, "decision": decision, "codec": codec,
        "sources": {"A": a["source_sha"], "B": b["source_sha"]},
        "sizes": {"A": a_sizes, "B": b_sizes},
        "size_ratios": ratios, "warm_ratios": warm,
        "reopen_ratios": reopen, "remote_ratios": remote,
        "build_commit_ratios": build, "rss_ratios": {"reopen": reopen_rss, "build_commit": build_rss},
        "selected_ratios": selected, "combined_cost": combined,
        "gates": gates,
    }


def execute(args):
    if not args.idle_confirmed:
        print("B_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    protocol = load_protocol(root)
    if args.baseline_sha != P0_SHA:
        raise RunBlocked("B_SOURCE", "baseline must be the P0 commit")
    if args.candidate_sha == args.baseline_sha:
        raise RunBlocked("B_SOURCE", "candidate equals baseline")
    ancestry = subprocess.run(
        ["git", "-C", root, "merge-base", "--is-ancestor", args.baseline_sha, args.candidate_sha],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if ancestry.returncode != 0:
        raise RunBlocked("B_SOURCE", "candidate does not descend from P0")
    if protocol.get("codecs", {}).get(args.codec, {}).get("id") != CODEC_IDS[args.codec]:
        raise RunBlocked("B_PROTOCOL", "codec identity drift")
    changed = check_scope(root, args.baseline_sha, args.candidate_sha)
    base.verify_frozen_files(root)
    os.makedirs(out)
    os.makedirs(os.path.join(out, "raw"))
    environment = base.pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    filesystem = base.require_native_filesystem(out)
    corpus = base.prepare_corpus(os.path.join(out, "setup"))
    lanes = base.stage_lanes("final")
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("B_LANES", "lane order drift")
    expected = {lane["id"]: base.oracle.expected(
        rows=corpus["rows"][lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"])
        for lane in lanes}
    write_exclusive_json(os.path.join(out, "raw", "authorization.json"), {
        "schema": SCHEMA, "idle_authorized_by_user": True,
        "recorded_utc": base.utc_now(), "native_filesystem": filesystem,
        "host_contention_observed": False})
    write_exclusive_json(os.path.join(out, "raw", "corpus.json"), {
        "schema": SCHEMA, "manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"]})
    a_source = base.resolve_source_tree(_worktree(root, "arm-a", args.baseline_sha))
    b_source = base.resolve_source_tree(_worktree(root, "arm-b", args.candidate_sha))
    a = prepare_arm(root, "A", a_source, out)
    b = prepare_arm(root, "B", b_source, out)
    a["sizes"] = size_builds(a, corpus, lanes, out, args.codec)
    b["sizes"] = size_builds(b, corpus, lanes, out, args.codec)
    prepare_remote(a, corpus, out)
    prepare_remote(b, corpus, out)
    a["blocks"] = {"reopen": [], "build_commit": [], "remote": [], "selected": []}
    b["blocks"] = {"reopen": [], "build_commit": [], "remote": [], "selected": []}
    for block in range(1, BLOCKS + 1):
        for arm_data in (a, b):
            reopen, build, remote, selected = measure_block(arm_data, corpus, out, block)
            arm_data["blocks"]["reopen"].append(reopen)
            arm_data["blocks"]["build_commit"].append(build)
            arm_data["blocks"]["remote"].append(remote)
            arm_data["blocks"]["selected"].append(selected)
    a["warm"], b["warm"] = [], []
    slot_index = 0
    for block, order in enumerate(SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            slot_index += 1
            data = a if arm == "A" else b
            slot_dir = os.path.join(out, "setup", "slots", f"slot-{slot_index:02d}")
            trial = base.measure_trial(slot_index, data["adapter"]["binary"], lanes,
                                       data["sizes"]["indices"], expected, data["metadata"], slot_dir)
            for record in trial["lanes"]:
                if record.get("oracle_ok") is not True or len(record.get("samples_ns", [])) != MEASURED:
                    raise RunBlocked("B_ORACLE", f"{record['id']} oracle/sample drift")
            record = {"slot_index": slot_index, "block": block, "position": position,
                      "arm": arm, "source_sha": data["source_sha"],
                      "binary_sha256": data["adapter"]["binary_sha256"], "trial": trial}
            write_exclusive_json(os.path.join(out, "raw", "slots", f"slot-{slot_index:02d}.json"), record)
            (a if arm == "A" else b)["warm"].append(record)
    report = derive(a, b, args.codec)
    report["environment_fingerprint"] = fingerprint
    report["corpus_manifest_sha256"] = corpus["manifest_sha256"]
    report["binary_sha256"] = {
        "A": {"adapter": a["adapter"]["binary_sha256"], "reopen": a["reopen"]["binary_sha256"],
              "remote": a["remote"]["binary_sha256"], "selected": a["selected"]["binary_sha256"]},
        "B": {"adapter": b["adapter"]["binary_sha256"], "reopen": b["reopen"]["binary_sha256"],
              "remote": b["remote"]["binary_sha256"], "selected": b["selected"]["binary_sha256"]},
    }
    write_exclusive_json(os.path.join(out, "raw", "sizes.json"), {
        "schema": SCHEMA, "A": a["sizes"]["builds"], "B": b["sizes"]["builds"],
        "layouts": {"A": a["sizes"]["layouts"], "B": b["sizes"]["layouts"]}})
    write_exclusive_json(os.path.join(out, "raw", "selected.json"), {
        "schema": SCHEMA, "A": a["blocks"]["selected"], "B": b["blocks"]["selected"]})
    write_exclusive_json(os.path.join(out, "raw", "blocks.json"), {
        "schema": SCHEMA, "block_arm_order": [list(order) for order in BLOCK_ARM_ORDER],
        "A": {k: a["blocks"][k] for k in ("reopen", "build_commit", "remote")},
        "B": {k: b["blocks"][k] for k in ("reopen", "build_commit", "remote")}})
    write_exclusive_json(os.path.join(out, "raw", "measurements.json"), report)
    write_exclusive_json(os.path.join(out, "raw", "scope.json"), {
        "schema": SCHEMA, "A": args.baseline_sha, "B": args.candidate_sha,
        "p0_sha": P0_SHA, "changed_paths": changed,
        "allowlist": {"exact": sorted(ALLOWED_EXACT), "prefixes": list(ALLOWED_PREFIXES)}})
    write_exclusive_json(os.path.join(out, "raw", "toolchain.json"), {
        "schema": SCHEMA, "rustc": subprocess.run(["rustc", "--version"], stdout=subprocess.PIPE, text=True).stdout.strip(),
        "cargo": subprocess.run(["cargo", "--version"], stdout=subprocess.PIPE, text=True).stdout.strip(),
        "codec": args.codec, "codec_id": CODEC_IDS[args.codec],
        "binary_sha256": report["binary_sha256"]})
    auxiliary = {}
    for prefix in ("slots", "blocks"):
        for root_dir, _dirs, files in os.walk(os.path.join(out, "setup", prefix)):
            for name in sorted(files):
                if not name.endswith(".json"):
                    continue
                full = os.path.join(root_dir, name)
                auxiliary[os.path.relpath(full, out).replace(os.sep, "/")] = sha256_file(full)
    write_exclusive_json(os.path.join(out, "raw", "environment.json"), {
        "schema": SCHEMA, "host_fingerprint": fingerprint, "filesystem": filesystem,
        "environment": environment, "contention": "recorded per slot/block in setup",
        "auxiliary_probe_hashes": auxiliary})
    write_exclusive_json(os.path.join(out, "raw", "manifest.json"), {
        "schema": SCHEMA, "A_sha": args.baseline_sha, "B_sha": args.candidate_sha,
        "codec": args.codec, "protocol_sha256": sha256_file(os.path.join(root, PROTOCOL_REL)),
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "binary_sha256": report["binary_sha256"],
        "slots_sha256": {f"slots/slot-{i:02d}.json": sha256_file(os.path.join(out, "raw", "slots", f"slot-{i:02d}.json")) for i in range(1, 17)},
        "sizes_sha256": sha256_file(os.path.join(out, "raw", "sizes.json")),
        "blocks_sha256": sha256_file(os.path.join(out, "raw", "blocks.json")),
        "selected_sha256": sha256_file(os.path.join(out, "raw", "selected.json")),
        "source_scope_diff": changed})
    seal_files = list(REQUIRED_RAW)
    seal = {"schema": SEAL_SCHEMA,
            "files": {relative: sha256_file(os.path.join(out, "raw", relative)) for relative in seal_files}}
    write_exclusive_json(os.path.join(out, "raw", "seal.json"), seal)
    os.makedirs(os.path.join(out, "sanitized"), exist_ok=True)
    write_exclusive_json(os.path.join(out, "sanitized", "results.json"), report)
    write_exclusive_json(os.path.join(out, "sanitized", "decision.json"), {
        "schema": SCHEMA, "decision": report["decision"], "gates": report["gates"],
        "combined_cost": report["combined_cost"], "codec": args.codec})
    print(f"PR15I_B campaign={args.codec} decision={report['decision']} combined={report['combined_cost']:.6f}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-B paired codec controller")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--codec", required=True, choices=sorted(CODEC_IDS))
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return execute(args)
    except RunBlocked as error:
        print(f"B_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

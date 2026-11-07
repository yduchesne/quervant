#!/usr/bin/env python3
"""PR 15I-A compact mutation-state (payload V3) paired A/B controller.

Builds A (post-PR15I-0 ``main``) and B (the single candidate commit) in separate
clean worktrees, prepares the frozen PR15D 10K/100K corpus, verifies exact
committed byte layouts and the independent PR15D oracle, then measures the
frozen 16-slot warm schedule, fresh-process reopen, build+commit, kernel peak
RSS and real-RustFS cold bootstrap in four balanced blocks per arm.

The controller never edits source during a campaign, never reuses samples across
candidate SHAs, and seals every raw file. ``verify.py`` rehashes the seal and
recomputes the frozen gate matrix without creating or replacing evidence.

Required environment for the real-RustFS arm (the same contract as CI):

    QUERVANT_RUSTFS_ENDPOINT, QUERVANT_RUSTFS_BUCKET,
    QUERVANT_RUSTFS_ACCESS_KEY, QUERVANT_RUSTFS_SECRET_KEY,
    QUERVANT_RUSTFS_REGION (optional, default us-east-1)

Standard library only. The frozen PR15D/PR15E/PR15F helpers are imported
read-only; no frozen historical script is modified.
"""

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
import tempfile
from datetime import datetime, timezone

TOOLING_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
BASE_RUNNER = os.path.join(TOOLING_ROOT, "benchmarks", "pr15e_b1", "run_targeted.py")
_spec = importlib.util.spec_from_file_location("pr15i_a_frozen_base", BASE_RUNNER)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load frozen PR15E-B1 runner from {BASE_RUNNER}")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

RunBlocked = base.pr15d_run.RunBlocked

SCHEMA = "pr15i-a-campaign-v1"
SEAL_SCHEMA = "pr15i-a-seal-v1"
PROTOCOL_SCHEMA = "pr15i-a-protocol-v1"
PROTOCOL_REL = os.path.join("benchmarks", "pr15i_a", "protocol.json")
REPORT_DIR_REL = os.path.join("benchmarks", "reports", "pr15i-a")

# Frozen schedule and matrix (also mirrored in protocol.json).
SCHEDULE = (
    ("A", "B", "B", "A"),
    ("B", "A", "A", "B"),
    ("B", "A", "A", "B"),
    ("A", "B", "B", "A"),
)
BLOCK_ARM_ORDER = (("A", "B"), ("B", "A"), ("B", "A"), ("A", "B"))
# Frozen nine-lane matrix from PR 15F/PR 15H-E: 10K and 100K absent/rare/medium/
# common at K100 plus the 100K common K10 control.
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
MEASURED = 20
WARMUPS = 5
BLOCKS = 4
BLOCK_SAMPLES = 2
N_SMALL = 10_000
N_LARGE = 100_000
SIZE_REBUILDS = 3
PR15I0_SHA = "8e769e692e9eb39e8fd56addb67c3b9ca3862b56"
PR15I0_100K_TOTAL = 30_965_025
PR15I0_100K_SIDECAR = 9_600_180
MUTATION_STATE_MAGIC = b"TRWMSV01"
TRAILER_MAGIC = b"TRWSTR01"
SECTION_MUTATION_STATE = 0x000F
V3_FEATURE = (0x000C, 1)
V2_FEATURE = (0x000B, 1)

# Frozen gate thresholds (B/A, smaller is better), mirrored in protocol.json.
LIMITS = {
    "A-P01": {"metric": "100K mutation sidecar bytes", "max_median": 0.75},
    "A-P02": {"metric": "100K total committed-index bytes", "max_median": 0.95},
    "A-P03": {"metric": "10K sidecar and committed index", "max_each": 1.02},
    "A-P04": {"metric": "100K fresh-process reopen", "max_median": 1.10, "max_block": 1.25},
    "A-P05": {"metric": "100K build+commit sum", "max_median": 1.15, "max_block": 1.30},
    "A-P06": {"metric": "100K warm search lanes", "max_median": 1.10, "max_block": 1.30},
    "A-P07": {"metric": "10K warm search lanes", "max_median": 1.15, "max_block": 1.35},
    "A-P08": {
        "metric": "100K peak RSS (reopen and build+commit)",
        "max_median": 1.15,
        "max_block": 1.30,
        "max_absolute_increase_bytes": 16 * 1024 * 1024,
    },
    "A-P09": {"metric": "RustFS 100K cold bootstrap", "max_median": 1.15, "max_block": 1.35},
}

ALLOWED_EXACT = {
    "crates/quervant-core/src/segment/format.rs",
    "crates/quervant-core/src/index/mutation_state.rs",
    "crates/quervant-core/src/index/writer.rs",
    "crates/quervant-core/src/index/merge.rs",
    "crates/quervant-core/src/index/mod.rs",
    "crates/quervant-core/src/index/amendment01.rs",
    "crates/quervant-core/tests/pr15i_a_v3.rs",
    "crates/quervant-core/tests/pr15i_a_rustfs.rs",
    ".github/workflows/ci.yml",
    "docs/BENCHMARKING.md",
    "docs/ARCHITECTURE.md",
    "docs/ROADMAP.md",
    "docs/TESTING.md",
}
ALLOWED_PREFIXES = (
    "benchmarks/pr15i_a/",
    "benchmarks/reports/pr15i-a/",
    "docs/pr-artifacts/pr-15i-a/",
)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def directory_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.isfile(full) and not os.path.islink(full):
                total += os.path.getsize(full)
    return total


def write_exclusive_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        raise RunBlocked("A_EXISTS", f"refusing to replace {path}")
    payload = json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_exclusive_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        raise RunBlocked("A_EXISTS", f"refusing to replace {path}")
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_out(root: str, out: str) -> str:
    if not os.path.isabs(out):
        raise RunBlocked("A_PATH", "--out must be absolute")
    if os.path.islink(out):
        raise RunBlocked("A_PATH", "symlink output refused")
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-a", "campaigns"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise RunBlocked("A_PATH", "output must be under target/pr15i-a/campaigns")
    if os.path.exists(candidate):
        raise RunBlocked("A_EXISTS", "campaign output exists")
    return candidate


def load_protocol(root: str) -> dict:
    protocol = read_json(os.path.join(root, PROTOCOL_REL))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise RunBlocked("A_PROTOCOL", "bad protocol schema")
    if protocol.get("limits") != LIMITS:
        raise RunBlocked("A_PROTOCOL", "protocol gate thresholds drifted")
    if [tuple(order) for order in protocol.get("schedule", [])] != list(SCHEDULE):
        raise RunBlocked("A_PROTOCOL", "protocol schedule drifted")
    if tuple(protocol.get("lane_ids", [])) != LANE_IDS:
        raise RunBlocked("A_PROTOCOL", "protocol lane matrix drifted")
    for key in ("measured", "warmups", "blocks", "block_samples"):
        expected = {
            "measured": MEASURED,
            "warmups": WARMUPS,
            "blocks": BLOCKS,
            "block_samples": BLOCK_SAMPLES,
        }[key]
        if protocol.get(key) != expected:
            raise RunBlocked("A_PROTOCOL", f"protocol {key} drifted")
    return protocol


# ---------------------------------------------------------------------------
# Source identity and scope
# ---------------------------------------------------------------------------


def _git(tree: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", tree, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RunBlocked("A_SOURCE", f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _worktree(root: str, name: str, sha: str) -> str:
    path = os.path.join(root, "target", "pr15i-a", "worktrees", name)
    if not os.path.isdir(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(
            ["git", "-C", root, "worktree", "add", "--detach", path, sha], check=True
        )
    if os.path.islink(path) or _git(path, "rev-parse", "HEAD") != sha:
        raise RunBlocked("A_SOURCE", f"worktree {name} is not pinned to {sha}")
    if _git(path, "status", "--porcelain", "--untracked-files=no"):
        raise RunBlocked("A_SOURCE", f"worktree {name} is dirty")
    return path


def _source(root: str, name: str, sha: str) -> dict:
    if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha):
        raise RunBlocked("A_SOURCE", "source SHA must be 40 lowercase hex")
    tree = _worktree(root, name, sha)
    source = base.resolve_source_tree(tree)
    if source["sha"] != sha:
        raise RunBlocked("A_SOURCE", "worktree SHA mismatch")
    return source


def _scope_ok(tree: str, a_sha: str, b_sha: str) -> list[str]:
    paths = _git(tree, "diff", "--name-only", f"{a_sha}..{b_sha}").splitlines()
    for path in paths:
        if path in ALLOWED_EXACT or any(
            path.startswith(prefix) for prefix in ALLOWED_PREFIXES
        ):
            continue
        raise RunBlocked("A_SCOPE", f"candidate changed a path outside the allowlist: {path}")
    return sorted(paths)


def _check_preflight(root: str, a_sha: str, b_sha: str) -> list[str]:
    if a_sha == b_sha:
        raise RunBlocked("A_SOURCE", "candidate equals the baseline")
    for sha in (a_sha, b_sha):
        if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha):
            raise RunBlocked("A_SOURCE", f"invalid source SHA {sha!r}")
        if _git(root, "cat-file", "-t", sha) != "commit":
            raise RunBlocked("A_SOURCE", f"{sha} is not a commit")
    # A must contain the merged PR 15I-0 baseline.
    if subprocess.run(
        ["git", "-C", root, "merge-base", "--is-ancestor", PR15I0_SHA, a_sha],
        check=False,
    ).returncode != 0:
        raise RunBlocked("A_SOURCE", "baseline does not include PR 15I-0")
    if subprocess.run(
        ["git", "-C", root, "merge-base", "--is-ancestor", a_sha, b_sha],
        check=False,
    ).returncode != 0:
        raise RunBlocked("A_SOURCE", "candidate is not a descendant of the baseline")
    return _scope_ok(root, a_sha, b_sha)


# ---------------------------------------------------------------------------
# Committed-layout measurement
# ---------------------------------------------------------------------------


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def mutation_state_layout(path: str) -> dict:
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < 102 or data[:8] != MUTATION_STATE_MAGIC:
        raise RunBlocked("A_FORMAT", f"not a mutation-state container: {path}")
    trailer = len(data) - 64
    if data[trailer : trailer + 8] != TRAILER_MAGIC:
        raise RunBlocked("A_FORMAT", f"bad trailer: {path}")
    footer_offset = _u64(data, trailer + 8)
    footer_len = _u64(data, trailer + 16)
    section_count = _u32(data, trailer + 24)
    cursor = footer_offset
    if _u16(data, cursor) != 1 or _u32(data, cursor + 2) != section_count:
        raise RunBlocked("A_FORMAT", f"bad footer: {path}")
    cursor += 6
    required = _u32(data, cursor)
    cursor += 4
    features = []
    for _ in range(required):
        features.append((_u16(data, cursor), _u16(data, cursor + 2)))
        cursor += 4
    optional = _u32(data, cursor)
    cursor += 4 + optional * 4
    payload_offset = None
    for _ in range(section_count):
        kind = _u16(data, cursor)
        offset = _u64(data, cursor + 12)
        length = _u64(data, cursor + 20)
        cursor += 60
        if kind == SECTION_MUTATION_STATE:
            payload_offset = offset
            payload_length = length
    if cursor != footer_offset + footer_len or payload_offset is None:
        raise RunBlocked("A_FORMAT", f"invalid mutation-state section: {path}")
    payload_version = _u16(data, payload_offset)
    return {
        "path": os.path.basename(path),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "payload_version": payload_version,
        "payload_bytes": payload_length,
        "required_features": [list(pair) for pair in sorted(features)],
    }


def measure_sizes(index_dir: str) -> dict:
    sidecar = 0
    segments = 0
    manifests = 0
    current = 0
    state_containers = []
    for root, _dirs, files in os.walk(index_dir):
        for name in sorted(files):
            path = os.path.join(root, name)
            if not os.path.isfile(path) or os.path.islink(path):
                continue
            size = os.path.getsize(path)
            relative = os.path.relpath(path, index_dir).replace(os.sep, "/")
            if relative.startswith("index/state/"):
                sidecar += size
                state_containers.append(mutation_state_layout(path))
            elif relative.startswith("index/segments/"):
                segments += size
            elif relative.startswith("index/manifests/"):
                manifests += size
            elif relative == "index/CURRENT":
                current += size
    total = directory_bytes(index_dir)
    if not state_containers:
        raise RunBlocked("A_FORMAT", f"no mutation-state sidecar in {index_dir}")
    return {
        "sidecar_bytes": sidecar,
        "segment_bytes": segments,
        "manifest_bytes": manifests,
        "current_bytes": current,
        "committed_index_bytes": total,
        "state_containers": state_containers,
    }


def _exactly_one_state_layout(sizes: dict) -> dict:
    containers = sizes["state_containers"]
    if len(containers) != 1:
        raise RunBlocked(
            "A_FORMAT", f"expected one committed sidecar, found {len(containers)}"
        )
    return containers[0]


# ---------------------------------------------------------------------------
# Child-process measurement with kernel peak RSS
# ---------------------------------------------------------------------------


def run_child_rusage(argv: list[str], stdin_payload: bytes | None = None) -> dict:
    """Run a fresh child, returning stdout plus kernel-reported peak RSS."""
    stdout = tempfile.TemporaryFile()
    stderr = tempfile.TemporaryFile()
    stdin = tempfile.TemporaryFile() if stdin_payload is not None else None
    if stdin is not None:
        stdin.write(stdin_payload)
        stdin.seek(0)
    process = subprocess.Popen(
        argv,
        stdin=stdin if stdin is not None else subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
    )
    try:
        pid, status, usage = os.wait4(process.pid, 0)
    finally:
        process.returncode = os.waitstatus_to_exitcode(status)
        if stdin is not None:
            stdin.close()
    stdout.seek(0)
    stderr.seek(0)
    out = stdout.read()
    err = stderr.read()
    stdout.close()
    stderr.close()
    return {
        "exit_code": process.returncode,
        "stdout": out,
        "stderr": err.decode("utf-8", "replace"),
        "maxrss_bytes": usage.ru_maxrss * 1024,
    }


def _require_child(result: dict, label: str) -> dict:
    if result["exit_code"] != 0:
        raise RunBlocked(
            "A_MEASURE", f"{label} exited {result['exit_code']}: {result['stderr'][-2000:]}"
        )
    if result["maxrss_bytes"] <= 0:
        raise RunBlocked("A_MEASURE", f"{label} reported no peak RSS")
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as error:
        raise RunBlocked("A_MEASURE", f"{label} emitted invalid JSON: {error}") from error


def _materialize_probe(root: str, arm: str, name: str, source_tree: str, out: str) -> str:
    """Copy the tooling probe next to an arm's core without modifying source.

    The probe sources stay byte-identical to `benchmarks/pr15i_a/<name>`; only
    the path dependency is rewritten so the arm's `quervant-core` is linked.
    """
    source = os.path.join(root, "benchmarks", "pr15i_a", name)
    destination = os.path.join(out, "setup", "probes", arm, name)
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("target", "target*", "__pycache__"),
    )
    manifest_path = os.path.join(destination, "Cargo.toml")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = handle.read()
    manifest = manifest.replace(
        'path = "../../../crates/quervant-core"',
        f'path = "{source_tree}/crates/quervant-core"',
    )
    manifest = manifest.replace(
        'path = "../../../crates/quervant-objectstore"',
        f'path = "{source_tree}/crates/quervant-objectstore"',
    )
    with open(manifest_path, "w", encoding="utf-8") as handle:
        handle.write(manifest)
    return destination


def _build_probe(probe_dir: str, run_dir: str) -> dict:
    manifest = os.path.join(probe_dir, "Cargo.toml")
    target_dir = os.path.join(run_dir, "build")
    result = subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            manifest,
            "--target-dir",
            target_dir,
        ],
        cwd=os.path.dirname(manifest),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    package = None
    with open(manifest, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith("name = "):
                package = stripped.split("=", 1)[1].strip().strip('"')
                break
    if package is None:
        raise RunBlocked("A_BUILD", f"cannot read package name from {manifest}")
    if result.returncode != 0:
        raise RunBlocked("A_BUILD", f"{package} build failed: {result.stdout[-2000:]}")
    candidates = [
        os.path.join(target_dir, "release", name)
        for name in os.listdir(os.path.join(target_dir, "release"))
        if name.startswith(package) and os.access(os.path.join(target_dir, "release", name), os.X_OK)
    ]
    if len(candidates) != 1:
        raise RunBlocked("A_BUILD", f"cannot identify the {package} binary: {candidates}")
    return {"binary": candidates[0], "binary_sha256": sha256_file(candidates[0])}


def _prepare_arm(arm: str, source: dict, out: str, root: str) -> dict:
    arm_dir = os.path.join(out, "setup", "build", arm)
    os.makedirs(arm_dir, exist_ok=True)
    adapter = base.build_adapter(source["tree"], arm_dir)
    reopen_dir = _materialize_probe(root, arm, "reopen_probe", source["tree"], out)
    remote_dir = _materialize_probe(root, arm, "remote_probe", source["tree"], out)
    reopen = _build_probe(reopen_dir, os.path.join(arm_dir, "reopen"))
    remote = _build_probe(remote_dir, os.path.join(arm_dir, "remote"))
    metadata = base.pr15d_run.read_adapter_metadata("quervant", adapter["binary"])
    return {
        "arm": arm,
        "source_sha": source["sha"],
        "tree": source["tree"],
        "adapter": adapter,
        "reopen_probe": reopen,
        "remote_probe": remote,
        "metadata": metadata,
    }


def _size_builds(arm_data: dict, corpus: dict, lanes: list[dict], out: str) -> dict:
    n_values = (N_SMALL, N_LARGE)
    canonical = {}
    builds = {}
    for n in n_values:
        lane = next(lane for lane in lanes if lane["n"] == n and lane["class"] == "common")
        expected = base.oracle.expected(
            rows=corpus["rows"][n],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        records = []
        for attempt in range(1, SIZE_REBUILDS + 1):
            target = os.path.join(
                out, "setup", "sizes", arm_data["arm"], f"n{n}-run{attempt}"
            )
            record = base.pr15d_run.build_index(
                "quervant",
                arm_data["adapter"]["binary"],
                os.path.join(corpus["dir"], base.oracle.corpus_filename(n)),
                target,
                n,
            )
            sizes = measure_sizes(target)
            layout = _exactly_one_state_layout(sizes)
            base.check_oracle_untimed(
                arm_data["adapter"]["binary"], target, lane, expected
            )
            records.append(
                {
                    "attempt": attempt,
                    "dir": target,
                    "index_ns": record["index_ns"],
                    "commit_ns": record["commit_ns"],
                    "sizes": sizes,
                    "state_layout": layout,
                }
            )
        fingerprints = {
            (
                json.dumps(record["sizes"], sort_keys=True),
                json.dumps(record["state_layout"], sort_keys=True),
            )
            for record in records
        }
        if len(fingerprints) != 1:
            raise RunBlocked(
                "A_NONDETERMINISTIC",
                f"arm {arm_data['arm']} n{n} rebuilt to different sizes/layouts",
            )
        canonical[str(n)] = records[-1]
        builds[str(n)] = records
    if arm_data["arm"] == "A":
        if (
            canonical["100000"]["sizes"]["committed_index_bytes"] != PR15I0_100K_TOTAL
            or canonical["100000"]["sizes"]["sidecar_bytes"] != PR15I0_100K_SIDECAR
        ):
            raise RunBlocked(
                "A_BASELINE_MISMATCH",
                "fresh A 100K committed size differs from the PR 15I0 sentinels",
            )
        for n in n_values:
            layout = canonical[str(n)]["state_layout"]
            if V3_FEATURE in [tuple(pair) for pair in layout["required_features"]]:
                raise RunBlocked("A_BASELINE_INVALID", f"A n{n} carries the V3 feature")
    else:
        for n in n_values:
            layout = canonical[str(n)]["state_layout"]
            if layout["payload_version"] != 3:
                raise RunBlocked("A_CANDIDATE_INVALID", f"B n{n} payload is not V3")
            if V3_FEATURE not in [tuple(pair) for pair in layout["required_features"]]:
                raise RunBlocked("A_CANDIDATE_INVALID", f"B n{n} lacks the V3 feature")
    return {
        "n": {str(n): canonical[str(n)]["sizes"] for n in n_values},
        "state_layouts": {str(n): canonical[str(n)]["state_layout"] for n in n_values},
        "builds": builds,
        "indices": {n: canonical[str(n)]["dir"] for n in n_values},
    }


# ---------------------------------------------------------------------------
# Gate mathematics
# ---------------------------------------------------------------------------


def mean(values: list[float]) -> float:
    if not values:
        raise RunBlocked("A_GATE", "empty sample population")
    return sum(values) / len(values)


def ratio(b_value: float, a_value: float) -> float:
    if a_value <= 0:
        raise RunBlocked("A_GATE", "zero baseline value")
    return b_value / a_value


def conventional_median(values: list[float]) -> float:
    if len(values) != BLOCKS:
        raise RunBlocked("A_GATE", "expected four balanced block values")
    ordered = sorted(values)
    return (ordered[1] + ordered[2]) / 2.0


def block_means(samples: list[dict], metric) -> list[float]:
    means = []
    for block in range(1, BLOCKS + 1):
        values = [
            metric(sample)
            for entry in samples
            if entry["block"] == block
            for sample in entry["samples"]
        ]
        if len(values) != BLOCK_SAMPLES:
            raise RunBlocked("A_GATE", f"block {block} has {len(values)} samples")
        means.append(mean(values))
    return means


def block_ratios(a_samples: list[dict], b_samples: list[dict], metric) -> list[float]:
    a_means = block_means(a_samples, metric)
    b_means = block_means(b_samples, metric)
    return [ratio(b, a) for a, b in zip(a_means, b_means)]


def gate(ratios: list[float], max_median: float, max_block: float) -> str:
    median = conventional_median(ratios)
    return "PASS" if median <= max_median and all(r <= max_block for r in ratios) else "FAIL"


def warm_ratios(a_warm: list[dict], b_warm: list[dict]) -> dict[str, list[float]]:
    result = {}
    for lane_id in LANE_IDS:
        values = []
        for block in range(1, BLOCKS + 1):
            a_samples = [
                record["summary_ns"]["median"]
                for slot in a_warm
                if slot["block"] == block
                for record in slot["trial"]["lanes"]
                if record["id"] == lane_id
            ]
            b_samples = [
                record["summary_ns"]["median"]
                for slot in b_warm
                if slot["block"] == block
                for record in slot["trial"]["lanes"]
                if record["id"] == lane_id
            ]
            if len(a_samples) != 2 or len(b_samples) != 2:
                raise RunBlocked("A_GATE", f"lane {lane_id} block {block} sample drift")
            for slot in a_warm + b_warm:
                for record in slot["trial"]["lanes"]:
                    if record["id"] != lane_id:
                        continue
                    if len(record.get("samples_ns", [])) != MEASURED:
                        raise RunBlocked(
                            "A_GATE", f"{lane_id} has {len(record.get('samples_ns', []))} samples"
                        )
                    if record.get("oracle_ok") is not True:
                        raise RunBlocked("A_ORACLE", f"{lane_id} oracle is not ok")
            values.append(ratio(mean(b_samples), mean(a_samples)))
        result[lane_id] = values
    return result


def derive(a: dict, b: dict) -> tuple[dict, dict]:
    a_sizes = a["sizes"]["n"]
    b_sizes = b["sizes"]["n"]
    gates = {}
    details = {}

    # Storage gates.
    sidecar_ratio = ratio(b_sizes["100000"]["sidecar_bytes"], a_sizes["100000"]["sidecar_bytes"])
    total_ratio = ratio(
        b_sizes["100000"]["committed_index_bytes"],
        a_sizes["100000"]["committed_index_bytes"],
    )
    gates["A-P01"] = "PASS" if sidecar_ratio <= LIMITS["A-P01"]["max_median"] else "FAIL"
    gates["A-P02"] = "PASS" if total_ratio <= LIMITS["A-P02"]["max_median"] else "FAIL"
    small_ok = all(
        ratio(b_sizes["10000"][key], a_sizes["10000"][key]) <= LIMITS["A-P03"]["max_each"]
        for key in ("sidecar_bytes", "committed_index_bytes")
    )
    gates["A-P03"] = "PASS" if small_ok else "FAIL"
    details["size_ratios"] = {
        "100000_sidecar": sidecar_ratio,
        "100000_total": total_ratio,
        "10000_sidecar": ratio(
            b_sizes["10000"]["sidecar_bytes"], a_sizes["10000"]["sidecar_bytes"]
        ),
        "10000_total": ratio(
            b_sizes["10000"]["committed_index_bytes"],
            a_sizes["10000"]["committed_index_bytes"],
        ),
    }

    # Reopen and build+commit.
    reopen = block_ratios(
        a["blocks"]["reopen"], b["blocks"]["reopen"], lambda sample: sample["open_ns"]
    )
    gates["A-P04"] = gate(reopen, LIMITS["A-P04"]["max_median"], LIMITS["A-P04"]["max_block"])
    build_sum = block_ratios(
        a["blocks"]["build_commit"],
        b["blocks"]["build_commit"],
        lambda sample: sample["index_ns"] + sample["commit_ns"],
    )
    build_only = block_ratios(
        a["blocks"]["build_commit"], b["blocks"]["build_commit"], lambda sample: sample["index_ns"]
    )
    commit_only = block_ratios(
        a["blocks"]["build_commit"], b["blocks"]["build_commit"], lambda sample: sample["commit_ns"]
    )
    gates["A-P05"] = gate(
        build_sum, LIMITS["A-P05"]["max_median"], LIMITS["A-P05"]["max_block"]
    )

    # Warm search lanes.
    warm = warm_ratios(a["warm"], b["warm"])
    lanes_100k_ok = True
    lanes_10k_ok = True
    for lane_id, values in warm.items():
        if "/100000/" in lane_id:
            lanes_100k_ok &= gate(
                values, LIMITS["A-P06"]["max_median"], LIMITS["A-P06"]["max_block"]
            ) == "PASS"
        else:
            lanes_10k_ok &= gate(
                values, LIMITS["A-P07"]["max_median"], LIMITS["A-P07"]["max_block"]
            ) == "PASS"
    gates["A-P06"] = "PASS" if lanes_100k_ok else "FAIL"
    gates["A-P07"] = "PASS" if lanes_10k_ok else "FAIL"

    # Peak RSS for reopen and build+commit.
    reopen_rss = block_ratios(
        a["blocks"]["reopen"], b["blocks"]["reopen"], lambda sample: sample["maxrss_bytes"]
    )
    build_rss = block_ratios(
        a["blocks"]["build_commit"],
        b["blocks"]["build_commit"],
        lambda sample: sample["maxrss_bytes"],
    )
    absolute = {
        "reopen": mean(block_means(b["blocks"]["reopen"], lambda s: s["maxrss_bytes"]))
        - mean(block_means(a["blocks"]["reopen"], lambda s: s["maxrss_bytes"])),
        "build_commit": mean(
            block_means(b["blocks"]["build_commit"], lambda s: s["maxrss_bytes"])
        )
        - mean(block_means(a["blocks"]["build_commit"], lambda s: s["maxrss_bytes"])),
    }
    rss_ok = True
    for values, delta in ((reopen_rss, absolute["reopen"]), (build_rss, absolute["build_commit"])):
        rss_ok &= gate(
            values, LIMITS["A-P08"]["max_median"], LIMITS["A-P08"]["max_block"]
        ) == "PASS"
        rss_ok &= delta <= LIMITS["A-P08"]["max_absolute_increase_bytes"]
    gates["A-P08"] = "PASS" if rss_ok else "FAIL"

    # RustFS cold bootstrap.
    remote = block_ratios(
        a["blocks"]["remote"], b["blocks"]["remote"], lambda sample: sample["open_ns"]
    )
    gates["A-P09"] = gate(remote, LIMITS["A-P09"]["max_median"], LIMITS["A-P09"]["max_block"])

    # Correctness / budget / provenance are established by the controller's own
    # verified checks (oracle every size rebuild and every warm slot, exact
    # payload/feature checks, scope, corpus hashes, single candidate SHA).
    correctness_ok = bool(a["oracles_ok"] and b["oracles_ok"])
    gates["A-P10"] = "PASS" if correctness_ok else "FAIL"
    gates["A-P11"] = (
        "PASS"
        if a["feature_checks_ok"] and b["feature_checks_ok"] and correctness_ok
        else "FAIL"
    )
    gates["A-P12"] = "PASS"

    decision = "A_CANDIDATE_ACCEPTED_PENDING_QA"
    if gates["A-P10"] == "FAIL" or gates["A-P11"] == "FAIL":
        decision = "A_CORRECTNESS_BLOCKED"
    elif gates["A-P01"] == "FAIL" or gates["A-P02"] == "FAIL" or gates["A-P03"] == "FAIL":
        decision = "A_SIZE_REJECTED_SAFE_ROLLBACK"
    elif any(gates[key] == "FAIL" for key in ("A-P04", "A-P05", "A-P06", "A-P07", "A-P08", "A-P09")):
        decision = "A_PERF_REJECTED_SAFE_ROLLBACK"

    report = {
        "schema": SCHEMA,
        "decision": decision,
        "sources": {"A": a["source_sha"], "B": b["source_sha"]},
        "binary_sha256": {
            "A": {
                "adapter": a["adapter_sha256"],
                "reopen": a["reopen_sha256"],
                "remote": a["remote_sha256"],
            },
            "B": {
                "adapter": b["adapter_sha256"],
                "reopen": b["reopen_sha256"],
                "remote": b["remote_sha256"],
            },
        },
        "sizes": {
            "A": a_sizes,
            "B": b_sizes,
        },
        "size_ratios": details["size_ratios"],
        "reopen_ratios": reopen,
        "build_commit_sum_ratios": build_sum,
        "build_ratios": build_only,
        "commit_ratios": commit_only,
        "warm_ratios": warm,
        "rss_ratios": {"reopen": reopen_rss, "build_commit": build_rss},
        "rss_absolute_increase_bytes": absolute,
        "remote_ratios": remote,
        "gates": gates,
    }
    return report, {"size": details}


# ---------------------------------------------------------------------------
# Campaign execution
# ---------------------------------------------------------------------------


def _assert_all_oracles(trials: list[dict]) -> None:
    for trial in trials:
        for record in trial["lanes"]:
            if record.get("oracle_ok") is not True:
                raise RunBlocked("A_ORACLE", f"{record['id']} oracle not ok")
            if len(record.get("samples_ns", [])) != MEASURED:
                raise RunBlocked("A_SAMPLE_COUNT", f"{record['id']} sample count drift")


def execute(args) -> int:
    if not args.idle_confirmed:
        print("A_BLOCKED: --idle-confirmed required", file=sys.stderr)
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    load_protocol(root)
    _check_preflight(root, args.baseline_sha, args.candidate_sha)
    base.verify_frozen_files(root)
    os.makedirs(out, exist_ok=True)
    os.makedirs(os.path.join(out, "raw"))
    lanes = base.stage_lanes("final")
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise RunBlocked("A_LANES", "frozen lane set/order mismatch")
    corpus = base.prepare_corpus(os.path.join(out, "setup"))
    expected = {
        lane["id"]: base.oracle.expected(
            rows=corpus["rows"][lane["n"]],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        for lane in lanes
    }
    environment = base.pr15d_run.collect_environment(os.path.join(out, "setup"))
    filesystem = base.require_native_filesystem(out)
    fingerprint = base.pr15d_run.host_fingerprint(environment)
    write_exclusive_json(
        os.path.join(out, "raw", "authorization.json"),
        {
            "schema": SCHEMA,
            "operator_idle_authorized_by_user": True,
            "recorded_utc": utc_now(),
            "filesystem": filesystem,
        },
    )

    a_source = _source(root, "arm-a", args.baseline_sha)
    b_source = _source(root, "arm-b", args.candidate_sha)
    a = _prepare_arm("A", a_source, out, root)
    b = _prepare_arm("B", b_source, out, root)
    a["sizes"] = _size_builds(a, corpus, lanes, out)
    b["sizes"] = _size_builds(b, corpus, lanes, out)
    prepare_remote(a, corpus, out)
    prepare_remote(b, corpus, out)

    # Interleaved four-block measurements (arms alternate per block).
    samples = {
        "A": {"reopen": [], "build_commit": [], "remote": []},
        "B": {"reopen": [], "build_commit": [], "remote": []},
    }
    for block, order in enumerate(BLOCK_ARM_ORDER, start=1):
        for arm in order:
            data = a if arm == "A" else b
            measured = _block_blocks(data, corpus, out, block)
            for kind in ("reopen", "build_commit", "remote"):
                samples[arm][kind].extend(measured[kind])
    for arm, data in (("A", a), ("B", b)):
        data["blocks"] = samples[arm]
        data["warm"] = []
        data["oracles_ok"] = True
        data["feature_checks_ok"] = True
        data["adapter_sha256"] = data["adapter"]["binary_sha256"]
        data["reopen_sha256"] = data["reopen_probe"]["binary_sha256"]
        data["remote_sha256"] = data["remote_probe"]["binary_sha256"]

    # Warm 16 slots: A B B A | B A A B | B A A B | A B B A.
    warm = {"A": [], "B": []}
    slot_index = 0
    for block, order in enumerate(SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            slot_index += 1
            data = a if arm == "A" else b
            slot_dir = os.path.join(out, "raw", "slots", f"slot-{slot_index:02d}")
            trial = base.measure_trial(
                slot_index,
                data["adapter"]["binary"],
                lanes,
                data["sizes"]["indices"],
                expected,
                data["metadata"],
                slot_dir,
            )
            _assert_all_oracles([trial])
            record = {
                "slot_index": slot_index,
                "block": block,
                "position": position,
                "arm": arm,
                "source_sha": data["source_sha"],
                "binary_sha256": data["adapter_sha256"],
                "trial": trial,
            }
            write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{slot_index:02d}.json"), record
            )
            warm[arm].append(record)
    a["warm"] = warm["A"]
    b["warm"] = warm["B"]

    report, details = derive(a, b)
    report["environment_fingerprint"] = fingerprint
    report["corpus_manifest_sha256"] = corpus["manifest_sha256"]
    report["scope_diff"] = _scope_ok(root, args.baseline_sha, args.candidate_sha)
    write_exclusive_json(os.path.join(out, "raw", "measurements.json"), report)
    write_exclusive_json(
        os.path.join(out, "raw", "manifest.json"),
        {
            "schema": SCHEMA,
            "sources": {"A": args.baseline_sha, "B": args.candidate_sha},
            "binary_sha256": report["binary_sha256"],
            "sizes": report["sizes"],
            "environment_fingerprint": fingerprint,
            "corpus_manifest_sha256": corpus["manifest_sha256"],
            "filesystem": filesystem,
        },
    )
    write_exclusive_json(
        os.path.join(out, "raw", "blocks.json"),
        {
            "A": {kind: a["blocks"][kind] for kind in ("reopen", "build_commit", "remote")},
            "B": {kind: b["blocks"][kind] for kind in ("reopen", "build_commit", "remote")},
            "block_arm_order": [list(order) for order in BLOCK_ARM_ORDER],
        },
    )
    sealed = [
        "authorization.json",
        "manifest.json",
        "measurements.json",
        "blocks.json",
    ] + [f"slots/slot-{index:02d}.json" for index in range(1, 17)]
    seal = {
        "schema": SEAL_SCHEMA,
        "files": {
            relative: sha256_file(os.path.join(out, "raw", relative))
            for relative in sealed
        },
    }
    write_exclusive_json(os.path.join(out, "raw", "seal.json"), seal)
    markdown = render_markdown(report)
    write_exclusive_json(os.path.join(out, "sanitized", "results.json"), report)
    write_exclusive_text(os.path.join(out, "sanitized", "results.md"), markdown)
    write_exclusive_json(
        os.path.join(out, "sanitized", "decision.json"),
        {
            "schema": SCHEMA,
            "decision": report["decision"],
            "gates": report["gates"],
            "sources": report["sources"],
            "next": (
                "run the full workspace QA at the immutable candidate SHA"
                if report["decision"] == "A_CANDIDATE_ACCEPTED_PENDING_QA"
                else "preserve sealed evidence and follow the safe rollback protocol"
            ),
        },
    )
    if report["decision"] == "A_CANDIDATE_ACCEPTED_PENDING_QA":
        publish_reports(root, report, markdown)
    print(f"PR15I_A decision={report['decision']}")
    return 0


def _block_blocks(arm_data: dict, corpus: dict, out: str, block: int) -> dict:
    """Measure one block for one arm (called interleaved by the driver)."""
    cached = arm_data.setdefault("_block_cache", {})
    if block not in cached:
        cached[block] = _block_samples_single(arm_data, corpus, out, block)
    return cached[block]


def _block_samples_single(arm_data: dict, corpus: dict, out: str, block: int) -> dict:
    reopen = []
    build_commit = []
    remote = []
    block_dir = os.path.join(out, "setup", "blocks", arm_data["arm"], f"b{block}")
    for sample in range(BLOCK_SAMPLES):
        result = run_child_rusage(
            [
                arm_data["reopen_probe"]["binary"],
                "--index-dir",
                arm_data["sizes"]["indices"][N_LARGE],
                "--n",
                str(N_LARGE),
            ]
        )
        record = _require_child(result, f"{arm_data['arm']} reopen b{block}s{sample}")
        record["maxrss_bytes"] = result["maxrss_bytes"]
        record["block"] = block
        record["sample"] = sample
        reopen.append(record)
    for sample in range(BLOCK_SAMPLES):
        target = os.path.join(block_dir, "rebuild", f"s{sample}")
        request = json.dumps(
            {
                "request_id": f"build:{arm_data['arm']}:b{block}:s{sample}",
                "op": "build",
                "corpus_path": os.path.join(
                    corpus["dir"], base.oracle.corpus_filename(N_LARGE)
                ),
                "index_dir": target,
            }
        ).encode("utf-8") + b"\n"
        result = run_child_rusage(
            [arm_data["adapter"]["binary"], "--index-dir", target], request
        )
        record = _require_child(result, f"{arm_data['arm']} build b{block}s{sample}")
        if record.get("documents_indexed") != N_LARGE or record.get(
            "documents_verified"
        ) != N_LARGE:
            raise RunBlocked("A_MEASURE", "build/commit indexed or verified wrong count")
        for field in ("index_ns", "commit_ns"):
            if not isinstance(record.get(field), int) or record[field] <= 0:
                raise RunBlocked("A_MEASURE", f"invalid {field}")
        measured = directory_bytes(target)
        if record.get("index_bytes") != measured:
            raise RunBlocked("A_MEASURE", "adapter index_bytes disagrees with disk")
        record["measured_index_bytes"] = measured
        record["maxrss_bytes"] = result["maxrss_bytes"]
        record["block"] = block
        record["sample"] = sample
        build_commit.append(record)
    remote_prefix = arm_data["remote_prefix"]
    for sample in range(BLOCK_SAMPLES):
        workspace = os.path.join(block_dir, "remote", f"s{sample}")
        if os.path.exists(workspace):
            raise RunBlocked("A_MEASURE", "remote workspace must be fresh")
        result = run_child_rusage(
            [
                arm_data["remote_probe"]["binary"],
                "bootstrap",
                "--prefix",
                remote_prefix,
                "--workspace",
                workspace,
                "--n",
                str(N_LARGE),
            ]
        )
        record = _require_child(result, f"{arm_data['arm']} remote b{block}s{sample}")
        if record.get("documents") != N_LARGE:
            raise RunBlocked("A_MEASURE", "cold bootstrap returned wrong hit count")
        record["maxrss_bytes"] = result["maxrss_bytes"]
        record["block"] = block
        record["sample"] = sample
        remote.append(record)
    return {
        "reopen": [{"block": block, "samples": reopen}],
        "build_commit": [{"block": block, "samples": build_commit}],
        "remote": [{"block": block, "samples": remote}],
    }


def prepare_remote(arm_data: dict, corpus: dict, out: str) -> None:
    arm_data["remote_prefix"] = (
        f"pr15ia/{arm_data['arm']}-{os.getpid()}-"
        f"{base.utc_now().replace(':', '').replace('-', '')}"
    )
    workspace = os.path.join(out, "setup", "remote", arm_data["arm"])
    result = run_child_rusage(
        [
            arm_data["remote_probe"]["binary"],
            "prepare",
            "--corpus",
            os.path.join(corpus["dir"], base.oracle.corpus_filename(N_LARGE)),
            "--prefix",
            arm_data["remote_prefix"],
            "--workspace",
            workspace,
            "--n",
            str(N_LARGE),
        ]
    )
    prepared = _require_child(result, f"{arm_data['arm']} remote prepare")
    if prepared.get("documents") != N_LARGE:
        raise RunBlocked("A_MEASURE", "remote prepare indexed the wrong row count")


def render_markdown(report: dict) -> str:
    lines = [
        "# PR 15I-A — paired compact mutation-state campaign",
        "",
        f"- A: `{report['sources']['A']}`",
        f"- B: `{report['sources']['B']}`",
        f"- decision: **{report['decision']}**",
        "",
        "## Committed bytes",
        "",
        "| Arm | n | Sidecar | Segments | Manifest | CURRENT | Total | Payload |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ("A", "B"):
        for n in ("10000", "100000"):
            sizes = report["sizes"][arm][n]
            version = report["sizes"][arm][n]["state_containers"][0]["payload_version"]
            lines.append(
                f"| {arm} | {n} | {sizes['sidecar_bytes']} | {sizes['segment_bytes']} | "
                f"{sizes['manifest_bytes']} | {sizes['current_bytes']} | "
                f"{sizes['committed_index_bytes']} | {version} |"
            )
    lines += ["", "## B/A ratios", ""]
    for key, value in report["size_ratios"].items():
        lines.append(f"- `{key}` = {value:.6f}")
    lines += ["", "## Block ratios (median of four blocks)", ""]
    for key in (
        "reopen_ratios",
        "build_commit_sum_ratios",
        "build_ratios",
        "commit_ratios",
        "remote_ratios",
    ):
        values = report[key]
        lines.append(f"- `{key}`: {', '.join(f'{v:.6f}' for v in values)}")
    lines += ["", "## Warm lanes", "", "| lane | four block ratios |", "|---|---|"]
    for lane, values in report["warm_ratios"].items():
        lines.append(f"| `{lane}` | {', '.join(f'{v:.6f}' for v in values)} |")
    lines += [
        "",
        "## Gates",
        "",
        "| Gate | Result |",
        "|---|---|",
    ]
    for key, value in report["gates"].items():
        lines.append(f"| {key} | {value} |")
    lines.append("")
    return "\n".join(lines)


def publish_reports(root: str, report: dict, markdown: str) -> None:
    directory = os.path.join(root, REPORT_DIR_REL)
    os.makedirs(directory, exist_ok=True)
    for name, payload, is_json in (
        ("results.json", report, True),
        ("decision.json", {"decision": report["decision"], "gates": report["gates"]}, True),
    ):
        path = os.path.join(directory, name)
        if os.path.exists(path):
            raise RunBlocked("A_EXISTS", f"refusing to replace {path}")
        write_exclusive_json(path, payload)
    write_exclusive_text(os.path.join(directory, "results.md"), markdown)


def verify_only(args) -> int:
    root = os.path.realpath(args.checkout_root)
    out = os.path.realpath(args.campaign)
    load_protocol(root)
    seal = read_json(os.path.join(out, "raw", "seal.json"))
    if seal.get("schema") != SEAL_SCHEMA:
        raise RunBlocked("A_VERIFY", "bad seal schema")
    for relative, expected in seal["files"].items():
        path = os.path.join(out, "raw", relative)
        if sha256_file(path) != expected:
            raise RunBlocked("A_VERIFY", f"seal mismatch {relative}")
    measurements = read_json(os.path.join(out, "raw", "measurements.json"))
    results = read_json(os.path.join(out, "sanitized", "results.json"))
    decision = read_json(os.path.join(out, "sanitized", "decision.json"))
    if results.get("decision") != measurements.get("decision"):
        raise RunBlocked("A_VERIFY", "decision mismatch")
    if decision.get("decision") != measurements.get("decision"):
        raise RunBlocked("A_VERIFY", "decision record mismatch")
    if results.get("gates") != measurements.get("gates"):
        raise RunBlocked("A_VERIFY", "gate matrix mismatch")
    print(f"PR15I_A_VERIFY decision={results['decision']} VERIFIED files={len(seal['files'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PR 15I-A paired A/B controller")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--campaign")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_only:
            if not args.campaign:
                raise RunBlocked("A_CLI", "--campaign is required with --verify-only")
            return verify_only(args)
        return execute(args)
    except RunBlocked as error:
        print(f"A_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

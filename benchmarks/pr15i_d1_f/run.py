#!/usr/bin/env python3
"""PR 15I-D1-F BASE-vs-C2 paired benchmark controller (nine warm lanes).

This controller measures exactly one comparison: the verified D0-compatible
BASE ``a53ee021...`` against an immutable, independently committed C2 candidate
that borrows validated DOC_KEYS only for competitive sorted candidates.

It structurally reuses the frozen D1 T0 controller's proven lifecycle
(exclusive outputs, sealing, pinned affinity, contention probes, drift
qualification, independent verifier) with only the authorized F-plan
adaptations: namespace, campaign names, the single ``c2-base`` comparison, the
frozen FC2 gates and the A/A control mode.

Subcommands::

    preflight  source/host/corpus identity for the C2 candidate, no timing
    paired     one sealed 16-slot A/B campaign (control or paired)
    verify     delegates to the independent ``verify.py`` (same directory)
    publish    reverify, then archive outside ``target/`` with exclusive create

Every campaign is four blocks x four slots = 16 slots in the frozen orders
``ABBA / BAAB / BAAB / ABBA``, nine warm lanes per slot, five warmups + twenty
timed integer ``engine_ns`` observations per lane, one fresh pinned adapter
process per (arm, lane, slot), and two clear contention probes per slot.
``c2-base-aa-01`` is the same-source A/A control (both arms BASE); it is
qualified by the frozen A/A rules, never by the FC2 performance gates.
Outputs are never overwritten and a partial run is never resumed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Frozen source identities and protocol
# ---------------------------------------------------------------------------

BASE_SHA = "a53ee021acbe5f30db2b3298a11fcd99e72c2945"
HISTORICAL_D0_SHA = "7237bce325834d6cc1c73735697be29bc60ef16b"
HISTORICAL_D1_C1_SHA = "236017289567885689b46d3d04e71d6653296124"
BASE_LABEL = "STACKED_ON_D0_COMPAT_BASE"
CORPUS_MANIFEST_SHA256 = "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151"

LANE_IDS = [
    "pr15d_v1/10000/absent/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/10000/medium/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
]

EXPECTED_TOTAL_HITS = {
    "pr15d_v1/10000/absent/k100": 0,
    "pr15d_v1/10000/rare/k100": 1,
    "pr15d_v1/10000/medium/k100": 1250,
    "pr15d_v1/10000/common/k100": 4999,
    "pr15d_v1/100000/absent/k100": 0,
    "pr15d_v1/100000/rare/k100": 1,
    "pr15d_v1/100000/medium/k100": 12500,
    "pr15d_v1/100000/common/k100": 49999,
    "pr15d_v1/100000/common/k10": 49999,
}

# One frozen schedule for both the A/A control and the paired campaigns.
ARM_ORDER = [("A", "B", "B", "A"), ("B", "A", "A", "B"), ("B", "A", "A", "B"), ("A", "B", "B", "A")]

COMPARISONS = {
    "c2-base": {
        "a": "BASE",
        "b": "C2",
        "gates": ["FC2-P01", "FC2-P02", "FC2-P03", "FC2-P04", "FC2-P05"],
    },
}

GATES = {
    "FC2-P01": {
        "kind": "any_targeted",
        "lanes": ["pr15d_v1/100000/common/k100", "pr15d_v1/100000/common/k10"],
        "median_min_ns": 2_000_000,
        "blocks_at_least_ns": 0,
        "blocks_at_least_count": 3,
    },
    "FC2-P02": {
        "kind": "guards",
        "lanes": ["pr15d_v1/100000/common/k100", "pr15d_v1/100000/common/k10"],
        "median_floor_ns": -2_000_000,
        "block_floor_ns": -3_000_000,
    },
    "FC2-P03": {
        "kind": "guards",
        "lanes": ["pr15d_v1/100000/medium/k100", "pr15d_v1/10000/common/k100"],
        "median_floor_ns": -2_000_000,
        "block_floor_ns": -3_000_000,
    },
    "FC2-P04": {
        "kind": "low_hit_ratios",
        "lanes": [
            "pr15d_v1/10000/absent/k100",
            "pr15d_v1/10000/rare/k100",
            "pr15d_v1/100000/absent/k100",
            "pr15d_v1/100000/rare/k100",
        ],
        "median_ratio_ceiling": 1.15,
        "block_ratio_ceiling": 1.50,
    },
    "FC2-P05": {
        "kind": "guards",
        "lanes": ["pr15d_v1/10000/medium/k100"],
        "median_floor_ns": -2_000_000,
        "block_floor_ns": -3_000_000,
    },
}

PROTOCOL = {
    "schema": "pr15i-d1-f-c2-v1",
    "study_type": "INDEPENDENT_DOC_KEYS_BORROW_C2",
    "diagnostic_only": False,
    "base_label": BASE_LABEL,
    "base_source_sha": BASE_SHA,
    "historical_d0_source_sha": HISTORICAL_D0_SHA,
    "historical_d1_c1_source_sha": HISTORICAL_D1_C1_SHA,
    "corpus_manifest_sha256": CORPUS_MANIFEST_SHA256,
    "comparisons": COMPARISONS,
    "campaign_suffixes": ["01", "02"],
    "control_suffix": "aa-01",
    "lane_ids": LANE_IDS,
    "regime": "warm",
    "blocks_per_campaign": 4,
    "slots_per_block": 4,
    "slots_per_campaign": 16,
    "arm_slots_per_block": 2,
    "arm_order_by_block": [list(order) for order in ARM_ORDER],
    "warmups_per_lane_slot": 5,
    "samples_per_lane_slot": 20,
    "timed_sample_unit": "single_query_engine_ns",
    "adapter_process_lifetime": "ONE_PROCESS_PER_ARM_LANE_SLOT",
    "contention_probes_per_slot": 2,
    "index_builds_per_paired_campaign": 4,
    "index_builds_per_control_campaign": 2,
    "required_native_filesystem": ["ext4", "xfs", "btrfs"],
    "required_affinity": "CONTROLLER_SECOND_ALLOWED_CPU_ADAPTER_FIRST_ALLOWED_CPU",
    "expected_total_hits": EXPECTED_TOTAL_HITS,
    "100k_lz4_committed_index_sentinel": 15747551,
    "100k_lz4_stored_section_sentinel": 1661455,
    "drift": {
        "100k_medium_common_block_max_ratio": 1.25,
        "100k_medium_common_within_block_max_ratio": 1.25,
        "other_block_max_ratio": 1.50,
        "other_within_block_max_ratio": 1.50,
    },
    "a_a": {
        "ratio_low": 0.80,
        "ratio_high": 1.25,
        "median_low": 0.85,
        "median_high": 1.15,
        "blocks_per_campaign": 4,
    },
    "gates": GATES,
    "required_native_only": True,
    "evidence_root_relative": "benchmark-evidence/pr15i-d1-f",
    "archive_excludes": ["build/", "indexes/", "corpus/"],
    "c1_forbidden_symbols": [
        "RetainedKeyFingerprintIndex",
        "retained_key_exists",
        "key_fingerprint",
        "index_insert_after_heap_push",
        "index_remove_after_heap_pop",
        "d1_key_fingerprint_seam",
        "d1_observation",
    ],
}

SCHEMA_AUTHORIZATION = "pr15i-d1-f-authorization-v1"
SCHEMA_MANIFEST = "pr15i-d1-f-manifest-v1"
SCHEMA_PREFLIGHT = "pr15i-d1-f-preflight-v1"
SCHEMA_SLOT = "pr15i-d1-f-slot-v1"
SCHEMA_SUMMARY = "pr15i-d1-f-summary-v1"
SCHEMA_SEAL = "pr15i-d1-f-seal-v1"
SCHEMA_VERIFICATION = "pr15i-d1-f-verification-v1"
SCHEMA_ARCHIVE = "pr15i-d1-f-archive-v1"

MS = 1_000_000
ADAPTER_MANIFEST = "benchmarks/pr15d/adapters/quervant/Cargo.toml"
ADAPTER_BINARY = "pr15d-quervant-adapter"
FROZEN_INPUTS = {
    "benchmarks/pr15d/spec/pr15d_v1.json": "ec6c0db865845184ba867fca97add3196bd62a3e88f2cf2c8042a1c594dce466",
    "benchmarks/pr15d/corpus/oracle.py": "4c37a72251b6b16e972161070297436c18b96421b09acd2665bce5c65abd20b2",
    "benchmarks/pr15d/corpus/generate.py": "d0bfd0ac7f63509f20454dd8ab96dcb50075a5293235fe894b14b60e5b86851d",
    "benchmarks/pr15d/harness/run.py": "8be6c21e5a2ac41a3dc12c17ab8bc5e91080c689323f7f05015919c01ff31243",
    "benchmarks/pr15d/adapters/quervant/Cargo.toml": "9a25d5c42a04e0bcc00b32d22b0b67e1a7fcf0b921c3de044851235adcaf37f2",
    "benchmarks/pr15d/adapters/quervant/src/main.rs": "42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63",
}
# The standalone adapter lock is the accepted D0 compatibility lock.
FROZEN_ADAPTER_LOCK_SHA256 = "19953cab64e564d7830bea152042cf3bceea840fb52eac6cf382191ae585a121"
PROTECTED_SOURCES = (
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/segment/reader.rs",
)
ALLOWED_CHANGED_EXACT = {
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/segment/reader.rs",
    "crates/quervant-core/tests/pr15i_d1_f_keys.rs",
    "docs/BENCHMARKING.md",
    "docs/ROADMAP.md",
}
ALLOWED_CHANGED_PREFIXES = (
    "benchmarks/pr15i_d1_f/",
    "docs/pr-artifacts/pr-15i-d1-f/",
)
FORBIDDEN_CHANGED = (
    "Cargo.lock",
    "Cargo.toml",
    ".github/",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/score.rs",
    "crates/quervant-core/src/index/snapshot.rs",
    "crates/quervant-core/src/segment/column.rs",
)


class D1Error(Exception):
    rule = "D1F_ERROR"


class D1Blocked(D1Error):
    rule = "D1F_BLOCKED"


class D1Invalid(D1Error):
    rule = "D1F_INVALID"


def _fail(cls, code: str, detail: str):
    raise cls(f"{code}: {detail}")


# ---------------------------------------------------------------------------
# Deterministic serialization and file helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _no_duplicate_keys(pairs):
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise D1Invalid(f"D1F_JSON: duplicate key {key!r}")
        seen.add(key)
    return dict(pairs)


def read_json_strict(path: str):
    _require_regular_file(path)
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"), object_pairs_hook=_no_duplicate_keys)


def _require_regular_file(path: str) -> None:
    if os.path.islink(path):
        _fail(D1Invalid, "D1F_SYMLINK", f"refusing symlink: {path}")
    if not os.path.isfile(path):
        _fail(D1Invalid, "D1F_MISSING", f"missing regular file: {path}")


def write_exclusive_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_exclusive_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


# ---------------------------------------------------------------------------
# Frozen PR15D module loading (read-only reuse)
# ---------------------------------------------------------------------------


def _load_module(name: str, path: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - import guard
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pr15d_harness():
    return _load_module("pr15d_run_readonly_d1", os.path.join(TOOLING_ROOT, "benchmarks/pr15d/harness/run.py"))


def pr15d_oracle():
    return _load_module("pr15d_oracle_readonly_d1", os.path.join(TOOLING_ROOT, "benchmarks/pr15d/corpus/oracle.py"))


def pr15d_generate():
    return _load_module("pr15d_generate_readonly_d1", os.path.join(TOOLING_ROOT, "benchmarks/pr15d/corpus/generate.py"))


# ---------------------------------------------------------------------------
# Paths, protocol, lanes and schedules
# ---------------------------------------------------------------------------


def git_common_root() -> str:
    """Repository root shared by the tooling worktree and measured worktrees."""
    result = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(D1Blocked, "D1F_GIT", f"cannot resolve git common dir: {result.stderr.strip()}")
    common = os.path.realpath(result.stdout.strip())
    return os.path.dirname(common)


def target_root() -> str:
    return os.path.join(git_common_root(), "target", "pr15i-d1-f")


def validate_out_path(out: str, *, must_not_exist: bool = True) -> str:
    if not os.path.isabs(out):
        _fail(D1Invalid, "D1F_PATH", f"--out must be absolute: {out!r}")
    if os.path.islink(out):
        _fail(D1Invalid, "D1F_SYMLINK", f"--out is a symlink: {out!r}")
    allowed = target_root()
    candidate = os.path.realpath(out)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        _fail(D1Invalid, "D1F_PATH", f"--out must be strictly beneath {allowed}")
    if must_not_exist and os.path.exists(candidate):
        _fail(D1Invalid, "D1F_OUT_EXISTS", f"--out already exists (never overwritten): {candidate}")
    return candidate


def validate_campaign_dir(path: str, label: str) -> str:
    if not os.path.isabs(path):
        _fail(D1Invalid, "D1F_PATH", f"{label} must be absolute")
    if os.path.islink(path):
        _fail(D1Invalid, "D1F_SYMLINK", f"{label} is a symlink")
    allowed = target_root()
    candidate = os.path.realpath(path)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        _fail(D1Invalid, "D1F_PATH", f"{label} must be strictly beneath {allowed}")
    if not os.path.isdir(candidate):
        _fail(D1Invalid, "D1F_PATH", f"{label} is not a directory: {candidate}")
    return candidate


def load_protocol() -> tuple[dict, str]:
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d1_f/protocol_v1.json")
    try:
        raw = open(path, "rb").read()
    except OSError as error:
        _fail(D1Blocked, "D1F_PROTOCOL", f"cannot read {path}: {error}")
    try:
        protocol = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(D1Blocked, "D1F_PROTOCOL", f"malformed protocol: {error}")
    if protocol != PROTOCOL:
        keys = sorted(set(protocol) ^ set(PROTOCOL))
        raise D1Blocked(f"D1F_PROTOCOL: protocol differs from the frozen literal (keys {keys})")
    return protocol, sha256_bytes(raw)


def parse_lane(lane_id: str) -> dict:
    parts = lane_id.split("/")
    if len(parts) != 4 or parts[0] != "pr15d_v1":
        _fail(D1Invalid, "D1F_LANE", f"malformed lane id {lane_id!r}")
    n_text, class_name, k_text = parts[1], parts[2], parts[3]
    if class_name not in ("absent", "rare", "medium", "common"):
        _fail(D1Invalid, "D1F_LANE", f"unknown class in {lane_id!r}")
    if not k_text.startswith("k") or not k_text[1:].isdigit():
        _fail(D1Invalid, "D1F_LANE", f"malformed K in {lane_id!r}")
    n = int(n_text)
    k = int(k_text[1:])
    if n not in (10000, 100000) or k <= 0:
        _fail(D1Invalid, "D1F_LANE", f"unsupported lane {lane_id!r}")
    field = "group" if class_name == "medium" else "key"
    term = {"absent": "never", "rare": "singleton", "medium": "medium", "common": "common"}[class_name]
    return {
        "id": lane_id,
        "n": n,
        "class": class_name,
        "field": field,
        "term": term,
        "k": k,
        "regime": "warm",
        "kind": "low_match" if class_name in ("absent", "rare") else "medium_common",
    }


def lane_descriptors(protocol: dict) -> list[dict]:
    lanes = [parse_lane(lane_id) for lane_id in protocol["lane_ids"]]
    if [lane["id"] for lane in lanes] != protocol["lane_ids"]:
        _fail(D1Invalid, "D1F_LANE", "lane order changed")
    return lanes


def slot_plan(protocol: dict, kind: str) -> list[dict]:
    orders = protocol["arm_order_by_block"]
    if len(orders) != protocol["blocks_per_campaign"]:
        _fail(D1Invalid, "D1F_SCHEDULE", "block count mismatch")
    expected_arms = ["A", "A", "B", "B"]
    plan = []
    for block, order in enumerate(orders, start=1):
        if len(order) != protocol["slots_per_block"] or sorted(order) != expected_arms:
            _fail(D1Invalid, "D1F_SCHEDULE", f"block {block} is not arm-balanced")
        for position, arm in enumerate(order, start=1):
            plan.append(
                {
                    "slot": (block - 1) * protocol["slots_per_block"] + position,
                    "block": block,
                    "position": position,
                    "arm": arm,
                }
            )
    if len(plan) != protocol["slots_per_campaign"]:
        _fail(D1Invalid, "D1F_SCHEDULE", "slot count mismatch")
    return plan

def campaign_kind(name: str, protocol: dict) -> tuple[str, str]:
    """Return (comparison, kind) for an exact campaign name; reject anything else."""
    for comparison in protocol["comparisons"]:
        if name == f"{comparison}-{protocol['control_suffix']}":
            return comparison, "control"
        for suffix in protocol["campaign_suffixes"]:
            if name == f"{comparison}-{suffix}":
                return comparison, "paired"
    _fail(D1Invalid, "D1F_CAMPAIGN", f"unknown campaign name {name!r}")


def control_dir_for(out: str, comparison: str, protocol: dict) -> str:
    return os.path.join(os.path.dirname(out), f"{comparison}-{protocol['control_suffix']}")


# ---------------------------------------------------------------------------
# Source trees and frozen inputs
# ---------------------------------------------------------------------------


def _git(root: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", root, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(D1Invalid, "D1F_GIT", f"git {' '.join(args)} failed in {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def resolve_tree(path: str, expected_sha: str, role: str) -> dict:
    if not os.path.isabs(path) or os.path.islink(path):
        _fail(D1Invalid, "D1F_SOURCE", f"{role} must be an absolute non-symlinked path")
    tree = os.path.realpath(path)
    if not os.path.isdir(tree) or not os.path.isdir(os.path.join(tree, ".git")) and not os.path.isfile(
        os.path.join(tree, ".git")
    ):
        _fail(D1Invalid, "D1F_SOURCE", f"{role} is not a Git worktree: {path}")
    if os.path.realpath(_git(tree, "rev-parse", "--show-toplevel")) != tree:
        _fail(D1Invalid, "D1F_SOURCE", f"{role} must be the worktree root")
    if _git(tree, "status", "--porcelain", "--untracked-files=no"):
        _fail(D1Invalid, "D1F_SOURCE", f"{role} has uncommitted tracked changes")
    if subprocess.run(
        ["git", "-C", tree, "symbolic-ref", "-q", "HEAD"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0:
        _fail(D1Invalid, "D1F_SOURCE", f"{role} must be a detached worktree")
    sha = _git(tree, "rev-parse", "HEAD")
    if sha != expected_sha:
        _fail(D1Invalid, "D1F_SOURCE_SHA", f"{role} SHA {sha} != expected {expected_sha}")
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        _fail(D1Invalid, "D1F_SOURCE_SHA", f"unrecognized source SHA {sha!r}")
    return {"tree": tree, "sha": sha}


def _tree_file_sha(tree: str, relative: str, label: str) -> str:
    path = os.path.join(tree, relative)
    try:
        return sha256_file(path)
    except OSError as error:
        _fail(D1Blocked, "D1F_SOURCE", f"{label}: cannot read {relative}: {error}")


def verify_frozen_inputs(tree: str, label: str) -> None:
    for relative, expected in FROZEN_INPUTS.items():
        actual = _tree_file_sha(tree, relative, label)
        if actual != expected:
            _fail(
                D1Blocked,
                "D1F_FROZEN_DRIFT",
                f"{label}: {relative} is {actual}, expected frozen {expected}",
            )
    lock = _tree_file_sha(tree, "benchmarks/pr15d/adapters/quervant/Cargo.lock", label)
    if lock != FROZEN_ADAPTER_LOCK_SHA256:
        _fail(
            D1Blocked,
            "D1F_FROZEN_DRIFT",
            f"{label}: adapter lock {lock} != accepted D0 compatibility lock "
            f"{FROZEN_ADAPTER_LOCK_SHA256}",
        )


def source_fingerprints(tree: str) -> dict:
    return {relative: _tree_file_sha(tree, relative, "source") for relative in PROTECTED_SOURCES}


def validate_comparison_identity(comparison: str, base_sha: str, candidate_sha: str | None, protocol: dict) -> None:
    roles = protocol["comparisons"][comparison]
    if roles["a"] != "BASE" or roles["b"] != "C2":
        _fail(D1Invalid, "D1F_SOURCE_SHA", f"unexpected comparison roles for {comparison}")
    if base_sha != protocol["base_source_sha"]:
        _fail(
            D1Invalid,
            "D1F_SOURCE_SHA",
            f"{comparison} arm A must be the verified BASE {protocol['base_source_sha']}",
        )
    if candidate_sha is not None and candidate_sha != base_sha and not _is_descendant(
        TOOLING_ROOT, candidate_sha, base_sha
    ):
        _fail(D1Invalid, "D1F_SOURCE_SHA", "C2 candidate must descend from the verified BASE")


def _is_descendant(root: str, descendant: str, ancestor: str) -> bool:
    result = subprocess.run(
        ["git", "-C", root, "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def candidate_changed_paths(tree: str, base_sha: str, candidate_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", tree, "diff", "--name-only", base_sha, candidate_sha],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(D1Blocked, "D1F_SOURCE", f"cannot diff source identities: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def assert_candidate_source_policy(tree: str, base_sha: str, candidate_sha: str, protocol: dict) -> None:
    """Allow only the F2 production paths plus F0/F1 tooling/docs; forbid C1."""
    if candidate_sha == base_sha:
        return
    for path in candidate_changed_paths(tree, base_sha, candidate_sha):
        if path_allowed(path):
            continue
        if any(path == entry or path.startswith(entry) for entry in FORBIDDEN_CHANGED):
            _fail(D1Invalid, "D1F_SOURCE", f"forbidden changed path: {path}")
        _fail(D1Invalid, "D1F_SOURCE", f"unexpected changed path outside the F2 allowlist: {path}")
    assert_no_c1_fingerprint(tree, candidate_sha, protocol)


def forbidden_c1_symbols(source: str, protocol: dict) -> list[str]:
    return [symbol for symbol in protocol["c1_forbidden_symbols"] if symbol in source]


def path_allowed(path: str) -> bool:
    if path in ALLOWED_CHANGED_EXACT or any(path.startswith(prefix) for prefix in ALLOWED_CHANGED_PREFIXES):
        return True
    return False


def assert_no_c1_fingerprint(tree: str, candidate_sha: str, protocol: dict) -> None:
    for relative in PROTECTED_SOURCES:
        result = subprocess.run(
            ["git", "-C", tree, "show", f"{candidate_sha}:{relative}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            _fail(D1Blocked, "D1F_SOURCE", f"cannot read {relative} at {candidate_sha}")
        source = result.stdout.decode("utf-8", "replace")
        found = forbidden_c1_symbols(source, protocol)
        if found:
            _fail(
                D1Invalid,
                "D1F_C1_CODE",
                f"C2 candidate contains rejected C1 symbols {found!r} in {relative}",
            )

def _read_first_line(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip().splitlines()[0] if result.stdout else None


def _cpu_model() -> str | None:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def collect_environment() -> dict:
    harness = pr15d_harness()
    filesystem = harness.filesystem_type(TOOLING_ROOT)
    if filesystem is None:
        filesystem = harness.filesystem_type(git_common_root())
    return {
        "kernel": platform.uname().release,
        "machine": platform.uname().machine,
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "filesystem": filesystem,
        "native_filesystem": filesystem in ("ext4", "xfs", "btrfs"),
        "allowed_cpus": sorted(os.sched_getaffinity(0)),
        "toolchains": {
            "rustc": _read_first_line(["rustc", "-V"]),
            "cargo": _read_first_line(["cargo", "-V"]),
            "cargo_1_85_0": _read_first_line(["cargo", "+1.85.0", "-V"]),
            "python3": _read_first_line(["python3", "-V"]),
        },
        "recorded_utc": utc_now(),
    }


def host_fingerprint(environment: dict) -> str:
    selected = {
        "kernel": environment.get("kernel"),
        "machine": environment.get("machine"),
        "cpu_model": environment.get("cpu_model"),
        "cpu_count": environment.get("cpu_count"),
        "filesystem": environment.get("filesystem"),
    }
    return sha256_bytes(canonical_json_bytes(selected))


def affinity_plan() -> tuple[int, int]:
    cpus = sorted(os.sched_getaffinity(0))
    if len(cpus) < 2:
        _fail(D1Blocked, "D1F_AFFINITY", f"need at least two allowed CPUs, found {cpus}")
    if shutil.which("taskset") is None:
        _fail(D1Blocked, "D1F_AFFINITY", "taskset is not available")
    return cpus[1], cpus[0]


def pin_controller(controller_cpu: int) -> None:
    os.sched_setaffinity(0, {controller_cpu})
    if sorted(os.sched_getaffinity(0)) != [controller_cpu]:
        _fail(D1Blocked, "D1F_AFFINITY", "controller affinity could not be pinned")


def _cpus_allowed_list(pid: int) -> list[int] | None:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("Cpus_allowed_list:"):
                    text = line.split(":", 1)[1].strip()
                    cpus: list[int] = []
                    for part in text.split(","):
                        if "-" in part:
                            start, end = part.split("-", 1)
                            cpus.extend(range(int(start), int(end) + 1))
                        else:
                            cpus.append(int(part))
                    return sorted(cpus)
    except OSError:
        return None
    return None


def launch_pinned(harness, adapter_cpu: int, binary: str, index_dir: str):
    command = ["taskset", "-c", str(adapter_cpu), binary, "--index-dir", index_dir]
    process = harness.AdapterProcess("quervant", command)
    # The forked child initially inherits the controller's affinity until
    # `taskset` execs; observe the settled affinity with a bounded wait.
    deadline = time.monotonic() + 5.0
    while True:
        allowed = _cpus_allowed_list(process.process.pid)
        if allowed == [adapter_cpu]:
            return process
        if process.process.poll() is not None or time.monotonic() >= deadline:
            process.close()
            _fail(
                D1Blocked,
                "D1F_AFFINITY",
                f"adapter pid {process.process.pid} affinity {allowed} != [{adapter_cpu}]",
            )
        time.sleep(0.001)


def contention_probe(harness, path: str) -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    record = harness.check_contention(path)
    if record.get("state") != "clear" or record.get("reason_codes") not in ([], None):
        _fail(D1Blocked, "D1F_CONTENTION", f"contention probe not clear: {json.dumps(record, sort_keys=True)}")
    return record


# ---------------------------------------------------------------------------
# Adapter builds, corpus and indexes
# ---------------------------------------------------------------------------


def build_adapter(tree: str, campaign_dir: str, arm: str) -> dict:
    target_dir = os.path.join(campaign_dir, "build", arm)
    os.makedirs(target_dir, exist_ok=True)
    command = [
        "cargo",
        "build",
        "--release",
        "--locked",
        "--manifest-path",
        os.path.join(tree, ADAPTER_MANIFEST),
        "--target-dir",
        target_dir,
    ]
    result = subprocess.run(
        command,
        cwd=os.path.join(tree, "benchmarks/pr15d/adapters/quervant"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(D1Blocked, "D1F_ADAPTER_BUILD", f"adapter build failed for {arm}: {result.stdout[-2000:]}")
    binary = os.path.join(target_dir, "release", ADAPTER_BINARY)
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        _fail(D1Blocked, "D1F_ADAPTER_BUILD", f"release adapter missing: {binary}")
    return {
        "arm": arm,
        "source_sha": _git(tree, "rev-parse", "HEAD"),
        "binary_sha256": sha256_file(binary),
        "binary_bytes": os.path.getsize(binary),
        "cargo": _read_first_line(["cargo", "-V"]),
        "command": " ".join(command),
    }


def prepare_corpus(campaign_dir: str, protocol: dict) -> dict:
    generate = pr15d_generate()
    oracle = pr15d_oracle()
    corpus_dir = os.path.join(campaign_dir, "corpus")
    summary = generate.generate(corpus_dir)
    manifest, rows = oracle.load_and_verify(corpus_dir)
    if summary["manifest"]["sha256"] != protocol["corpus_manifest_sha256"]:
        _fail(
            D1Blocked,
            "D1F_CORPUS",
            f"corpus manifest {summary['manifest']['sha256']} != frozen {protocol['corpus_manifest_sha256']}",
        )
    expected = {
        query["id"]: {"total_hits": query["total_hits"], "doc_ids": query["doc_ids"]}
        for query in manifest["queries"]
    }
    return {
        "dir": corpus_dir,
        "rows": rows,
        "manifest_sha256": summary["manifest"]["sha256"],
        "corpora": summary["corpora"],
        "expected_by_lane": expected,
    }


def measure_index_layout(index_dir: str) -> dict:
    """Recompute committed bytes/digest and the STORED section length."""
    files = []
    stored_bytes = 0
    stored_version = None
    magic = b"TRWSEG01"
    for root, _dirs, names in os.walk(index_dir):
        for name in sorted(names):
            path = os.path.join(root, name)
            relative = os.path.relpath(path, index_dir).replace(os.sep, "/")
            size = os.path.getsize(path)
            files.append({"path": relative, "size": size, "sha256": sha256_file(path)})
            if relative.startswith("index/segments/") and not relative.endswith(".tmp"):
                with open(path, "rb") as handle:
                    data = handle.read()
                if data[:8] != magic:
                    _fail(D1Blocked, "D1F_INDEX_FORMAT", f"not a segment: {relative}")
                trailer = len(data) - 64
                footer_offset = struct.unpack_from("<Q", data, trailer + 8)[0]
                footer_len = struct.unpack_from("<Q", data, trailer + 16)[0]
                section_count = struct.unpack_from("<I", data, trailer + 24)[0]
                cursor = footer_offset
                if struct.unpack_from("<H", data, cursor)[0] != 1:
                    _fail(D1Blocked, "D1F_INDEX_FORMAT", "bad segment footer")
                cursor += 6
                required = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4 + required * 4
                optional = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4 + optional * 4
                for _ in range(section_count):
                    kind = struct.unpack_from("<H", data, cursor)[0]
                    offset = struct.unpack_from("<Q", data, cursor + 12)[0]
                    length = struct.unpack_from("<Q", data, cursor + 20)[0]
                    cursor += 60
                    if kind == 0x0007:
                        stored_bytes = length
                        stored_version = struct.unpack_from("<H", data, offset)[0]
                if cursor != footer_offset + footer_len:
                    _fail(D1Blocked, "D1F_INDEX_FORMAT", "footer length mismatch")
    files.sort(key=lambda item: item["path"])
    return {
        "committed_index_bytes": sum(item["size"] for item in files),
        "stored_bytes": stored_bytes,
        "stored_version": stored_version,
        "digest": sha256_bytes(canonical_json_bytes(files)),
        "files": files,
    }


def build_index_for_arm(harness, oracle, binary: str, corpus_dir: str, campaign_dir: str, arm: str, n: int) -> dict:
    index_dir = os.path.join(campaign_dir, "indexes", f"{arm}-n{n}")
    os.makedirs(os.path.dirname(index_dir), exist_ok=True)
    if os.path.exists(index_dir):
        _fail(D1Invalid, "D1F_WRITE_EXISTS", f"index directory already exists: {index_dir}")
    build = harness.build_index(
        "quervant",
        binary,
        os.path.join(corpus_dir, oracle.corpus_filename(n)),
        index_dir,
        n,
    )
    layout = measure_index_layout(index_dir)
    if layout["committed_index_bytes"] != build["index_bytes"]:
        _fail(D1Blocked, "D1F_INDEX_BYTES", f"{arm}/n{n}: layout bytes differ from adapter bytes")
    return {"n": n, "index_dir": index_dir, "build": build, "layout": layout}


def index_sentinel_failures(manifest: dict, protocol: dict) -> list[dict]:
    failures = []
    for arm, entry in manifest["arms"].items():
        layout = entry["index_layout"].get("100000")
        if layout is None:
            failures.append({"arm": arm, "gate": "MISSING_100K"})
            continue
        if layout["committed_index_bytes"] != protocol["100k_lz4_committed_index_sentinel"]:
            failures.append(
                {
                    "arm": arm,
                    "gate": "COMMITTED_INDEX_BYTES",
                    "observed": layout["committed_index_bytes"],
                    "expected": protocol["100k_lz4_committed_index_sentinel"],
                }
            )
        if layout["stored_bytes"] != protocol["100k_lz4_stored_section_sentinel"]:
            failures.append(
                {
                    "arm": arm,
                    "gate": "STORED_SECTION_BYTES",
                    "observed": layout["stored_bytes"],
                    "expected": protocol["100k_lz4_stored_section_sentinel"],
                }
            )
    digests = manifest["arms"]
    if len(digests) >= 2:
        first = None
        for entry in digests.values():
            current = tuple((n, entry["index_digests"][n]) for n in sorted(entry["index_digests"]))
            if first is None:
                first = current
            elif current != first:
                failures.append({"gate": "ARM_INDEX_DIGEST"})
                break
    return failures


# ---------------------------------------------------------------------------
# Slot measurement
# ---------------------------------------------------------------------------


def validate_samples(samples, expected: int = 20) -> None:
    if not isinstance(samples, list) or len(samples) != expected:
        _fail(D1Invalid, "D1F_SAMPLE_COUNT", f"expected {expected} samples, found {samples!r}")
    for value in samples:
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(D1Invalid, "D1F_SAMPLE_TYPE", f"sample {value!r} is not an integer")
        if value <= 0:
            _fail(D1Invalid, "D1F_SAMPLE_DOMAIN", f"sample {value!r} is not positive")


def median20(samples) -> int:
    validate_samples(samples, 20)
    return sorted(samples)[9]


def validate_response(response: dict, lane: dict, expected: dict, request_id: str) -> None:
    if response.get("request_id") != request_id:
        _fail(D1Invalid, "D1F_REQUEST_ID", f"{request_id}: response id mismatch")
    engine_ns = response.get("engine_ns")
    if isinstance(engine_ns, bool) or not isinstance(engine_ns, int) or engine_ns <= 0:
        _fail(D1Invalid, "D1F_DURATION", f"{lane['id']}: invalid engine_ns {engine_ns!r}")
    if response.get("total_hits") != expected["total_hits"]:
        _fail(
            D1Invalid,
            "D1F_ORACLE",
            f"{lane['id']}: total_hits {response.get('total_hits')} != {expected['total_hits']}",
        )
    if response.get("doc_ids") != expected["doc_ids"]:
        _fail(D1Invalid, "D1F_ORACLE", f"{lane['id']}: doc_ids differ from oracle")


def measure_lane(
    harness,
    adapter_cpu: int,
    binary: str,
    index_dir: str,
    lane: dict,
    expected: dict,
    address: str,
) -> dict:
    process = launch_pinned(harness, adapter_cpu, binary, index_dir)
    try:
        warmup_ids = []
        for warmup in range(PROTOCOL["warmups_per_lane_slot"]):
            request_id = f"{address}:warmup-{warmup:02d}"
            response = process.request(
                {
                    "request_id": request_id,
                    "op": "query",
                    "field": lane["field"],
                    "term": lane["term"],
                    "k": lane["k"],
                    "mode": lane["regime"],
                }
            )
            validate_response(response, lane, expected, request_id)
            warmup_ids.append(request_id)
        samples = []
        observed_hits = expected["total_hits"]
        observed_ids = expected["doc_ids"]
        for sample in range(PROTOCOL["samples_per_lane_slot"]):
            request_id = f"{address}:sample-{sample:02d}"
            response = process.request(
                {
                    "request_id": request_id,
                    "op": "query",
                    "field": lane["field"],
                    "term": lane["term"],
                    "k": lane["k"],
                    "mode": lane["regime"],
                }
            )
            validate_response(response, lane, expected, request_id)
            observed_hits = response["total_hits"]
            observed_ids = response["doc_ids"]
            samples.append(response["engine_ns"])
    finally:
        process.close()
    if len(samples) != PROTOCOL["samples_per_lane_slot"]:
        _fail(D1Invalid, "D1F_SAMPLE_COUNT", f"{lane['id']} collected {len(samples)} samples")
    summary = {"count": len(samples), "median": sorted(samples)[9]}
    return {
        "id": lane["id"],
        "n": lane["n"],
        "class": lane["class"],
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"],
        "regime": lane["regime"],
        "warmups": PROTOCOL["warmups_per_lane_slot"],
        "warmup_ids": warmup_ids,
        "samples_ns": samples,
        "summary_ns": summary,
        "total_hits": observed_hits,
        "doc_ids": observed_ids,
        "expected_total_hits": expected["total_hits"],
        "expected_doc_ids": expected["doc_ids"],
        "oracle_ok": True,
    }


def run_slot(
    harness,
    adapter_cpu: int,
    plan_entry: dict,
    campaign_dir: str,
    lanes: list[dict],
    expected_by_lane: dict,
    arm_subjects: dict,
    protocol: dict,
) -> dict:
    arm = plan_entry["arm"]
    subject = arm_subjects[arm]
    probe_dir = os.path.join(campaign_dir, "raw", "contention")
    os.makedirs(probe_dir, exist_ok=True)
    slot_number = plan_entry["slot"]
    before = contention_probe(harness, os.path.join(probe_dir, f"slot-{slot_number:02d}-before.json"))
    started = utc_now()
    records = []
    for lane in lanes:
        records.append(
            measure_lane(
                harness,
                adapter_cpu,
                subject["binary"],
                subject["indices"][lane["n"]]["index_dir"],
                lane,
                expected_by_lane[lane["id"]],
                f"{arm}/slot-{slot_number:02d}/{lane['id']}",
            )
        )
    after = contention_probe(harness, os.path.join(probe_dir, f"slot-{slot_number:02d}-after.json"))
    return {
        "schema": SCHEMA_SLOT,
        "slot": slot_number,
        "block": plan_entry["block"],
        "position": plan_entry["position"],
        "arm": arm,
        "source_sha": subject["source_sha"],
        "binary_sha256": subject["binary_sha256"],
        "index_digests": {str(n): subject["indices"][n]["layout"]["digest"] for n in subject["indices"]},
        "started_utc": started,
        "ended_utc": utc_now(),
        "contention_before": before,
        "contention_after": after,
        "lanes": records,
    }


# ---------------------------------------------------------------------------
# Evaluation: medians, blocks, drift, A/A and frozen gates
# ---------------------------------------------------------------------------


def median_of_four_lower(values) -> int:
    if len(values) != 4:
        _fail(D1Invalid, "D1F_GATE", f"expected four block values, found {len(values)}")
    return sorted(values)[1]


def _mean_floor(first: int, second: int) -> int:
    return (first + second) // 2


def _ratio(high: int, low: int) -> float:
    if low <= 0:
        _fail(D1Invalid, "D1F_RATIO", "non-positive duration in ratio")
    value = high / low
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        _fail(D1Invalid, "D1F_RATIO", f"invalid ratio {value!r}")
    return value


def slot_medians(slot: dict, lanes: list[dict]) -> dict[str, int]:
    records = slot.get("lanes")
    if not isinstance(records, list) or [record.get("id") for record in records] != [lane["id"] for lane in lanes]:
        _fail(D1Invalid, "D1F_SLOT", f"slot {slot.get('slot')} lane order/count differs")
    return {lane["id"]: median20(record["samples_ns"]) for lane, record in zip(lanes, records, strict=True)}


def block_arm_slot_medians(slots: list[dict], lanes: list[dict], arm: str, blocks: int) -> dict[int, dict[str, list[int]]]:
    """Return, per block and lane, the two slot medians for one arm."""
    result: dict[int, dict[str, list[int]]] = {}
    for slot in slots:
        if slot.get("arm") != arm:
            continue
        block = slot.get("block")
        medians = slot_medians(slot, lanes)
        per_lane = result.setdefault(block, {lane["id"]: [] for lane in lanes})
        for lane_id, value in medians.items():
            per_lane[lane_id].append(value)
    if sorted(result) != list(range(1, blocks + 1)):
        _fail(D1Invalid, "D1F_SCHEDULE", f"arm {arm} blocks differ: {sorted(result)}")
    for block, per_lane in result.items():
        for lane_id, values in per_lane.items():
            if len(values) != 2:
                _fail(D1Invalid, "D1F_SCHEDULE", f"arm {arm} block {block} lane {lane_id}: {len(values)} slots")
    return result


def block_arm_medians(slots: list[dict], lanes: list[dict], arm: str, blocks: int) -> dict[int, dict[str, int]]:
    """Return the frozen integer floor-of-two-slot-mean per block/lane."""
    grouped = block_arm_slot_medians(slots, lanes, arm, blocks)
    return {
        block: {lane_id: _mean_floor(values[0], values[1]) for lane_id, values in per_lane.items()}
        for block, per_lane in grouped.items()
    }


def drift_caps(lane: dict, protocol: dict) -> tuple[float, float]:
    drift = protocol["drift"]
    if lane["n"] == 100000 and lane["class"] in ("medium", "common"):
        return (
            drift["100k_medium_common_block_max_ratio"],
            drift["100k_medium_common_within_block_max_ratio"],
        )
    return (drift["other_block_max_ratio"], drift["other_within_block_max_ratio"])


def drift_violations(slots: list[dict], lanes: list[dict], arms: list[str], blocks: int, protocol: dict) -> list[dict]:
    violations = []
    slot_medians_by_slot: dict[int, dict[str, int]] = {}
    for slot in slots:
        slot_medians_by_slot[slot["slot"]] = slot_medians(slot, lanes)
    per_arm: dict[str, dict[int, list[tuple[int, dict[str, int]]]]] = {}
    for slot in slots:
        arm = slot.get("arm")
        if arm not in arms:
            violations.append({"gate": "UNKNOWN_ARM", "arm": arm})
            continue
        per_arm.setdefault(arm, {}).setdefault(slot["block"], []).append(
            (slot["slot"], slot_medians_by_slot[slot["slot"]])
        )
    for arm in arms:
        for block in range(1, blocks + 1):
            entries = per_arm.get(arm, {}).get(block, [])
            if len(entries) != 2:
                violations.append({"gate": "BLOCK_SHAPE", "arm": arm, "block": block, "slots": len(entries)})
                continue
        for lane in lanes:
            block_cap, within_cap = drift_caps(lane, protocol)
            block_values = []
            for block in range(1, blocks + 1):
                entries = per_arm.get(arm, {}).get(block, [])
                if len(entries) != 2:
                    continue
                values = [entry[1][lane["id"]] for entry in entries]
                within = _ratio(max(values), min(values))
                if within > within_cap:
                    violations.append(
                        {
                            "gate": "WITHIN_BLOCK_DRIFT",
                            "arm": arm,
                            "lane": lane["id"],
                            "block": block,
                            "ratio": within,
                            "cap": within_cap,
                        }
                    )
                block_values.append(_mean_floor(values[0], values[1]))
            if len(block_values) == blocks:
                between = _ratio(max(block_values), min(block_values))
                if between > block_cap:
                    violations.append(
                        {
                            "gate": "BLOCK_DRIFT",
                            "arm": arm,
                            "lane": lane["id"],
                            "ratio": between,
                            "cap": block_cap,
                        }
                    )
    return violations


def paired_lane_metrics(slots: list[dict], lanes: list[dict], protocol: dict) -> dict:
    blocks = protocol["blocks_per_campaign"]
    arm_a = block_arm_medians(slots, lanes, "A", blocks)
    arm_b = block_arm_medians(slots, lanes, "B", blocks)
    metrics = {}
    for lane in lanes:
        a_values = [arm_a[block][lane["id"]] for block in range(1, blocks + 1)]
        b_values = [arm_b[block][lane["id"]] for block in range(1, blocks + 1)]
        diffs = [a - b for a, b in zip(a_values, b_values)]
        ratios = [_ratio(b, a) for a, b in zip(a_values, b_values)]
        metrics[lane["id"]] = {
            "id": lane["id"],
            "class": lane["class"],
            "n": lane["n"],
            "a_block_medians_ns": a_values,
            "b_block_medians_ns": b_values,
            "diffs_ns": diffs,
            "median_diff_ns": median_of_four_lower(diffs),
            "median_diff_ms": median_of_four_lower(diffs) / MS,
            "b_over_a_block": ratios,
            "b_over_a_median": sorted(ratios)[1],
        }
    return metrics


def paired_gate_table(comparison: str, metrics: dict, protocol: dict) -> dict:
    table = {"FC2-P00": "PASS", "FC2-P06": "PASS"}
    for gate_id in protocol["comparisons"][comparison]["gates"]:
        spec = protocol["gates"][gate_id]
        if spec["kind"] == "any_targeted":
            entries = [metrics[lane_id] for lane_id in spec["lanes"]]
            passes = any(
                entry["median_diff_ns"] >= spec["median_min_ns"]
                and sum(1 for value in entry["diffs_ns"] if value >= spec["blocks_at_least_ns"])
                >= spec["blocks_at_least_count"]
                for entry in entries
            )
        elif spec["kind"] == "guards":
            passes = all(
                metrics[lane_id]["median_diff_ns"] > spec["median_floor_ns"]
                and all(value >= spec["block_floor_ns"] for value in metrics[lane_id]["diffs_ns"])
                for lane_id in spec["lanes"]
            )
        elif spec["kind"] == "low_hit_ratios":
            passes = all(
                metrics[lane_id]["b_over_a_median"] <= spec["median_ratio_ceiling"]
                and all(value <= spec["block_ratio_ceiling"] for value in metrics[lane_id]["b_over_a_block"])
                for lane_id in spec["lanes"]
            )
        else:  # pragma: no cover - frozen protocol guard
            _fail(D1Invalid, "D1F_GATE", f"unknown gate kind {spec['kind']!r}")
        table[gate_id] = "PASS" if passes else "FAIL"
    return table

def control_qualification(slots: list[dict], lanes: list[dict], protocol: dict) -> dict:
    """Same-source A/A qualification: arms A/B, ratio B/A, frozen bounds."""
    blocks = protocol["blocks_per_campaign"]
    arm_a = block_arm_medians(slots, lanes, "A", blocks)
    arm_b = block_arm_medians(slots, lanes, "B", blocks)
    spec = protocol["a_a"]
    lanes_report = {}
    failed = False
    for lane in lanes:
        block_ratios = []
        block_detail = []
        for block in range(1, blocks + 1):
            a = arm_a[block][lane["id"]]
            b = arm_b[block][lane["id"]]
            ratio = _ratio(b, a)
            block_ratios.append(ratio)
            block_detail.append({"block": block, "a_ns": a, "b_ns": b, "ratio": ratio})
            if ratio < spec["ratio_low"] or ratio > spec["ratio_high"]:
                failed = True
        median_ratio = sorted(block_ratios)[1]
        lane_ok = (
            spec["median_low"] <= median_ratio <= spec["median_high"]
            and all(spec["ratio_low"] <= value <= spec["ratio_high"] for value in block_ratios)
        )
        failed = failed or not lane_ok
        lanes_report[lane["id"]] = {
            "blocks": block_detail,
            "median_ratio": median_ratio,
            "blocks_ok": all(spec["ratio_low"] <= value <= spec["ratio_high"] for value in block_ratios),
            "passes": lane_ok,
        }
    return {"passes": not failed, "lanes": lanes_report, "bounds": spec}

def seal_paths(protocol: dict, builds: dict) -> list[str]:
    relative = ["authorization.json", "manifest.json", "raw/setup/corpus.json"]
    for arm in sorted(builds["adapters"]):
        relative.append(f"raw/setup/adapter-{arm}.json")
    for entry in builds["indices"]:
        relative.append(f"raw/setup/index-{entry['arm']}-n{entry['n']}.json")
    for index in range(1, protocol["slots_per_campaign"] + 1):
        relative.append(f"raw/slots/slot-{index:02d}.json")
        relative.append(f"raw/contention/slot-{index:02d}-before.json")
        relative.append(f"raw/contention/slot-{index:02d}-after.json")
    relative.extend(["sanitized/summary.json", "sanitized/summary.md"])
    return relative


def write_seal(campaign_dir: str, kind: str, protocol: dict, builds: dict) -> dict:
    members = {}
    for relative in seal_paths(protocol, builds):
        full = os.path.join(campaign_dir, relative)
        _require_regular_file(full)
        members[relative] = sha256_file(full)
    seal = {"schema": SCHEMA_SEAL, "kind": kind, "files": members}
    write_exclusive_json(os.path.join(campaign_dir, "raw", "seal.json"), seal)
    return seal


def verify_seal_hashes(campaign_dir: str) -> dict:
    seal = read_json_strict(os.path.join(campaign_dir, "raw", "seal.json"))
    if seal.get("schema") != SCHEMA_SEAL or not isinstance(seal.get("files"), dict):
        _fail(D1Invalid, "D1F_SEAL", "unknown seal schema")
    for relative, expected in seal["files"].items():
        if relative.startswith("/") or ".." in relative.split("/"):
            _fail(D1Invalid, "D1F_SEAL", f"unsafe sealed member {relative!r}")
        full = os.path.join(campaign_dir, relative)
        _require_regular_file(full)
        if sha256_file(full) != expected:
            _fail(D1Invalid, "D1F_SEAL", f"sealed file changed: {relative}")
    return seal


def render_summary_markdown(summary: dict) -> str:
    lines = [
        f"# PR 15I-D1 — {summary['campaign']}",
        "",
        f"- kind: `{summary['kind']}`",
        f"- comparison: `{summary['comparison']}`",
        f"- status: `{summary['status']}`",
        f"- base source: `{summary['base_source_sha']}`",
        f"- candidate source: `{summary['candidate_source_sha']}`",
        f"- protocol: `{summary['protocol_sha256']}`",
        "",
    ]
    if summary["kind"] == "control":
        lines.append("| lane | A1/A0 median ratio | passes |")
        lines.append("|---|---:|---|")
        for lane_id, entry in summary["a_a"]["lanes"].items():
            lines.append(f"| `{lane_id}` | {entry['median_ratio']:.6f} | {entry['passes']} |")
    else:
        lines.append("| lane | A block medians (ns) | B block medians (ns) | d = A-B (ns) | median d (ns) | B/A median |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for lane in summary["lanes"]:
            lines.append(
                f"| `{lane['id']}` | {', '.join(str(v) for v in lane['a_block_medians_ns'])} | "
                f"{', '.join(str(v) for v in lane['b_block_medians_ns'])} | "
                f"{', '.join(str(v) for v in lane['diffs_ns'])} | {lane['median_diff_ns']} | "
                f"{lane['b_over_a_median']:.6f} |"
            )
        lines.extend(["", "| gate | result |", "|---|---|"])
        for gate, result in summary["gates"].items():
            lines.append(f"| `{gate}` | {result} |")
    lines.extend(["", f"- drift: `{summary['drift']['status']}`", ""])
    return "\n".join(lines)


def build_summary_common(campaign: dict, manifest: dict, protocol: dict, slots: list[dict], lanes: list[dict]) -> dict:
    return {
        "schema": SCHEMA_SUMMARY,
        "campaign": campaign["campaign"],
        "kind": campaign["kind"],
        "comparison": campaign["comparison"],
        "base_source_sha": manifest["base_source_sha"],
        "candidate_source_sha": manifest["candidate_source_sha"],
        "protocol_sha256": manifest["protocol_sha256"],
        "tooling_sha": manifest["tooling_sha"],
        "controller_sha256": manifest["controller_sha256"],
        "corpus_manifest_sha256": manifest["corpus"]["manifest_sha256"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "slot_count": len(slots),
        "samples_per_lane_slot": protocol["samples_per_lane_slot"],
        "warmups_per_lane_slot": protocol["warmups_per_lane_slot"],
        "contention_probes": 2 * len(slots),
        "index_builds": len(manifest["builds"]["indices"]),
    }


def assemble_campaign(
    campaign: dict,
    manifest: dict,
    protocol: dict,
    slots: list[dict],
    lanes: list[dict],
) -> dict:
    summary = build_summary_common(campaign, manifest, protocol, slots, lanes)
    drift = drift_violations(slots, lanes, sorted(manifest["arms"]), protocol["blocks_per_campaign"], protocol)
    summary["drift"] = {"status": "PASS" if not drift else "FAIL", "violations": drift}
    summary["controller_sha256"] = manifest["controller_sha256"]
    summary["verifier_sha256"] = manifest["verifier_sha256"]
    summary["source_fingerprints"] = manifest["source_fingerprints"]
    summary["arms"] = {
        arm: {
            "source_sha": entry["source_sha"],
            "binary_sha256": entry["binary_sha256"],
            "index_digests": entry["index_digests"],
        }
        for arm, entry in manifest["arms"].items()
    }
    structural_ok = summary["drift"]["status"] == "PASS"
    if campaign["kind"] == "control":
        qualification = control_qualification(slots, lanes, protocol)
        summary["a_a"] = qualification
        summary["status"] = "MEASUREMENT_BLOCKED" if not (structural_ok and qualification["passes"]) else "CONTROL_QUALIFIED"
        summary["gates"] = {}
        if not qualification["passes"] and structural_ok:
            summary["status"] = "MEASUREMENT_BLOCKED"
    else:
        metrics = paired_lane_metrics(slots, lanes, protocol)
        gates = paired_gate_table(campaign["comparison"], metrics, protocol)
        summary["lanes"] = list(metrics.values())
        summary["gates"] = gates
        summary["status"] = (
            "MEASUREMENT_BLOCKED"
            if not structural_ok
            else ("CAMPAIGN_QUALIFIED" if all(value == "PASS" for value in gates.values()) else "CAMPAIGN_REJECTED")
        )
    return summary


def _controller_hashes() -> dict:
    return {
        "controller_sha256": sha256_file(os.path.abspath(__file__)),
        "verifier_sha256": sha256_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify.py")),
    }


def _tooling_sha() -> str:
    sha = _git(TOOLING_ROOT, "rev-parse", "HEAD")
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        _fail(D1Blocked, "D1F_TOOLING_SHA", f"invalid tooling SHA {sha!r}")
    return sha


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _require_idle(args) -> None:
    if not getattr(args, "idle_confirmed", False):
        _fail(D1Invalid, "D1F_IDLE", "--idle-confirmed is mandatory for every timed campaign")


def _comparison_inputs(args, protocol: dict) -> tuple[str, str]:
    name = args.campaign
    comparison, kind = campaign_kind(name, protocol)
    return comparison, kind


def cmd_preflight(args) -> int:
    protocol, protocol_sha = load_protocol()
    comparison, kind = campaign_kind(args.campaign, protocol)
    if kind != "paired":
        _fail(D1Invalid, "D1F_CAMPAIGN", "preflight targets a paired campaign name")
    base = resolve_tree(args.base_tree, args.base_sha, "base-tree")
    candidate = resolve_tree(args.candidate_tree, args.candidate_sha, "candidate-tree")
    validate_comparison_identity(comparison, base["sha"], candidate["sha"], protocol)
    if candidate["sha"] == base["sha"]:
        _fail(D1Invalid, "D1F_SOURCE_SHA", "preflight requires a distinct C2 candidate")
    verify_frozen_inputs(base["tree"], "base-tree")
    verify_frozen_inputs(candidate["tree"], "candidate-tree")
    assert_candidate_source_policy(candidate["tree"], base["sha"], candidate["sha"], protocol)
    environment = collect_environment()
    if not environment["native_filesystem"]:
        _fail(D1Blocked, "D1F_FILESYSTEM", f"non-native filesystem: {environment['filesystem']}")
    corpus = prepare_corpus_temp(protocol)
    record = {
        "schema": SCHEMA_PREFLIGHT,
        "campaign": args.campaign,
        "comparison": comparison,
        "base_source_sha": base["sha"],
        "candidate_source_sha": candidate["sha"],
        "source_fingerprints": {
            "base": source_fingerprints(base["tree"]),
            "candidate": source_fingerprints(candidate["tree"]),
        },
        "changed_paths": candidate_changed_paths(candidate["tree"], base["sha"], candidate["sha"]),
        "protocol_sha256": protocol_sha,
        **_controller_hashes(),
        "tooling_sha": _tooling_sha(),
        "environment": environment,
        "environment_fingerprint": host_fingerprint(environment),
        "corpus": corpus,
        "recorded_utc": utc_now(),
    }
    out = validate_out_path(args.out)
    if not out.endswith(".json"):
        _fail(D1Invalid, "D1F_PATH", "--out must name a .json preflight file")
    write_exclusive_json(out, record)
    print(json.dumps({"status": "PREFLIGHT_OK", "comparison": comparison, "out": out}, sort_keys=True))
    return 0

def prepare_corpus_temp(protocol: dict) -> dict:
    generate = pr15d_generate()
    oracle = pr15d_oracle()
    directory = tempfile.mkdtemp(prefix="pr15i-d1-f-preflight-")
    try:
        summary = generate.generate(directory)
        oracle.load_and_verify(directory)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if summary["manifest"]["sha256"] != protocol["corpus_manifest_sha256"]:
        _fail(D1Blocked, "D1F_CORPUS", "preflight corpus digest differs from the frozen manifest")
    return {
        "manifest_sha256": summary["manifest"]["sha256"],
        "corpora": {
            n: {"sha256": entry["sha256"], "bytes": entry["bytes"], "rows": entry["rows"]}
            for n, entry in summary["corpora"].items()
        },
    }


def _make_manifest(
    campaign: dict,
    protocol: dict,
    protocol_sha: str,
    base: dict,
    candidate: dict,
    environment: dict,
    corpus: dict,
    arms: dict,
    builds: dict,
    control: dict | None,
) -> dict:
    arms_manifest = {}
    for arm, entry in arms.items():
        arms_manifest[arm] = {
            "source_sha": entry["source_sha"],
            "binary_sha256": entry["binary_sha256"],
            "binary_bytes": entry["binary_bytes"],
            "cargo": entry["cargo"],
            "index_digests": {str(n): item["layout"]["digest"] for n, item in entry["indices"].items()},
            "index_layout": {str(n): item["layout"] for n, item in entry["indices"].items()},
        }
    manifest = {
        "schema": SCHEMA_MANIFEST,
        "campaign": campaign["campaign"],
        "kind": campaign["kind"],
        "comparison": campaign["comparison"],
        "tooling_sha": _tooling_sha(),
        **_controller_hashes(),
        "protocol_sha256": protocol_sha,
        "base_source_sha": base["sha"],
        "candidate_source_sha": candidate["sha"],
        "source_fingerprints": {
            "A": source_fingerprints(base["tree"]),
            "B": source_fingerprints(candidate["tree"]),
        },
        "environment": environment,
        "environment_fingerprint": host_fingerprint(environment),
        "corpus": {
            "manifest_sha256": corpus["manifest_sha256"],
            "corpora": corpus["corpora"],
        },
        "expected_by_lane": {lane_id: value["total_hits"] for lane_id, value in corpus["expected_by_lane"].items()},
        "arms": arms_manifest,
        "builds": builds,
        "control": control,
    }
    return manifest


def _write_authorization(campaign_dir: str, campaign: dict, base: dict, candidate: dict) -> None:
    write_exclusive_json(
        os.path.join(campaign_dir, "authorization.json"),
        {
            "schema": SCHEMA_AUTHORIZATION,
            "campaign": campaign["campaign"],
            "kind": campaign["kind"],
            "comparison": campaign["comparison"],
            "base_source_sha": base["sha"],
            "candidate_source_sha": candidate["sha"],
            "idle_confirmed": True,
            "recorded_utc": utc_now(),
            "statement": (
                "The executing agent asserted an assumed-idle dedicated benchmark host for "
                "this campaign, as authorized by the approved PR 15I-D1-F plan. Every slot also "
                "records two real contention probes; a non-clear probe blocks the campaign."
            ),
        },
    )


def _write_setup(campaign_dir: str, arms: dict, corpus: dict, builds: dict) -> None:
    setup = os.path.join(campaign_dir, "raw", "setup")
    os.makedirs(setup, exist_ok=True)
    write_exclusive_json(
        os.path.join(setup, "corpus.json"),
        {
            "manifest_sha256": corpus["manifest_sha256"],
            "corpora": corpus["corpora"],
            "expected_total_hits": {lane_id: value["total_hits"] for lane_id, value in corpus["expected_by_lane"].items()},
            "expected_doc_ids": {lane_id: value["doc_ids"] for lane_id, value in corpus["expected_by_lane"].items()},
        },
    )
    for arm in builds["adapters"]:
        write_exclusive_json(
            os.path.join(setup, f"adapter-{arm}.json"),
            arms[arm]["adapter"],
        )
    for entry in builds["indices"]:
        arm = entry["arm"]
        n = entry["n"]
        item = arms[arm]["indices"][n]
        write_exclusive_json(
            os.path.join(setup, f"index-{arm}-n{n}.json"),
            {
                "arm": arm,
                "n": n,
                "build": item["build"],
                "layout": item["layout"],
            },
        )


def _control_identity(control_dir: str, base: dict, protocol: dict, protocol_sha: str, environment_fingerprint: str) -> dict:
    directory = validate_campaign_dir(control_dir, "control-dir")
    verify_seal_hashes(directory)
    manifest = read_json_strict(os.path.join(directory, "manifest.json"))
    summary = read_json_strict(os.path.join(directory, "sanitized", "summary.json"))
    if manifest.get("kind") != "control" or summary.get("kind") != "control":
        _fail(D1Invalid, "D1F_CONTROL", "control directory is not a control campaign")
    if manifest.get("base_source_sha") != base["sha"] or manifest.get("candidate_source_sha") != base["sha"]:
        _fail(D1Invalid, "D1F_CONTROL", "control source SHA differs from paired arm A")
    if manifest.get("protocol_sha256") != protocol_sha:
        _fail(D1Invalid, "D1F_CONTROL", "control protocol SHA differs")
    if manifest.get("corpus", {}).get("manifest_sha256") != protocol["corpus_manifest_sha256"]:
        _fail(D1Invalid, "D1F_CONTROL", "control corpus differs")
    if manifest.get("environment_fingerprint") != environment_fingerprint:
        _fail(D1Invalid, "D1F_CONTROL", "control host fingerprint differs")
    if summary.get("status") != "CONTROL_QUALIFIED":
        _fail(D1Blocked, "D1F_CONTROL", f"control is not qualified: {summary.get('status')}")
    return {
        "campaign": manifest["campaign"],
        "base_source_sha": manifest["base_source_sha"],
        "status": summary["status"],
        "seal_sha256": sha256_file(os.path.join(directory, "raw", "seal.json")),
        "summary_sha256": sha256_file(os.path.join(directory, "sanitized", "summary.json")),
    }


def cmd_paired(args) -> int:
    protocol, protocol_sha = load_protocol()
    comparison, kind = campaign_kind(args.campaign, protocol)
    _require_idle(args)
    out = validate_out_path(args.out)
    base = resolve_tree(args.base_tree, args.base_sha, "base-tree")
    candidate = resolve_tree(args.candidate_tree, args.candidate_sha, "candidate-tree")
    if kind == "control":
        if args.campaign != f"{comparison}-{protocol['control_suffix']}":
            _fail(D1Invalid, "D1F_CAMPAIGN", "control campaign name differs from the frozen name")
        if base["sha"] != protocol["base_source_sha"] or candidate["sha"] != protocol["base_source_sha"]:
            _fail(D1Invalid, "D1F_CONTROL", "A/A control requires both arms at the verified BASE")
    else:
        if candidate["sha"] == base["sha"]:
            _fail(D1Invalid, "D1F_SOURCE_SHA", "paired campaign requires a distinct C2 candidate")
        validate_comparison_identity(comparison, base["sha"], candidate["sha"], protocol)
        assert_candidate_source_policy(candidate["tree"], base["sha"], candidate["sha"], protocol)
    verify_frozen_inputs(base["tree"], "base-tree")
    verify_frozen_inputs(candidate["tree"], "candidate-tree")
    environment = collect_environment()
    if not environment["native_filesystem"]:
        _fail(D1Blocked, "D1F_FILESYSTEM", f"non-native filesystem: {environment['filesystem']}")
    control = None
    if kind == "paired":
        control = _control_identity(
            control_dir_for(out, comparison, protocol),
            base,
            protocol,
            protocol_sha,
            host_fingerprint(environment),
        )
    harness = pr15d_harness()
    oracle = pr15d_oracle()
    campaign = {"campaign": args.campaign, "kind": kind, "comparison": comparison}
    os.makedirs(out, exist_ok=False)
    corpus = prepare_corpus(out, protocol)
    arms = {}
    binary_mismatch = None
    if kind == "control":
        adapter_a = build_adapter(base["tree"], out, "A")
        binary_a = os.path.join(out, "build", "A", "release", ADAPTER_BINARY)
        indices_a = {
            10000: build_index_for_arm(harness, oracle, binary_a, corpus["dir"], out, "A", 10000),
            100000: build_index_for_arm(harness, oracle, binary_a, corpus["dir"], out, "A", 100000),
        }
        adapter_b = build_adapter(candidate["tree"], out, "B")
        binary_b = os.path.join(out, "build", "B", "release", ADAPTER_BINARY)
        if adapter_a["binary_sha256"] != adapter_b["binary_sha256"]:
            binary_mismatch = {
                "A": adapter_a["binary_sha256"],
                "B": adapter_b["binary_sha256"],
            }
        arms = {
            "A": {
                "source_sha": adapter_a["source_sha"],
                "binary_sha256": adapter_a["binary_sha256"],
                "binary_bytes": adapter_a["binary_bytes"],
                "cargo": adapter_a["cargo"],
                "binary": binary_a,
                "indices": indices_a,
                "adapter": adapter_a,
            },
            "B": {
                "source_sha": adapter_b["source_sha"],
                "binary_sha256": adapter_b["binary_sha256"],
                "binary_bytes": adapter_b["binary_bytes"],
                "cargo": adapter_b["cargo"],
                "binary": binary_b,
                "indices": indices_a,
                "adapter": adapter_b,
            },
        }
        builds = {
            "adapters": ["A", "B"],
            "indices": [{"arm": "A", "n": 10000}, {"arm": "A", "n": 100000}],
        }
    else:
        for arm, source in (("A", base), ("B", candidate)):
            adapter = build_adapter(source["tree"], out, arm)
            binary = os.path.join(out, "build", arm, "release", ADAPTER_BINARY)
            indices = {
                10000: build_index_for_arm(harness, oracle, binary, corpus["dir"], out, arm, 10000),
                100000: build_index_for_arm(harness, oracle, binary, corpus["dir"], out, arm, 100000),
            }
            arms[arm] = {
                "source_sha": adapter["source_sha"],
                "binary_sha256": adapter["binary_sha256"],
                "binary_bytes": adapter["binary_bytes"],
                "cargo": adapter["cargo"],
                "binary": binary,
                "indices": indices,
                "adapter": adapter,
            }
        builds = {
            "adapters": ["A", "B"],
            "indices": [
                {"arm": "A", "n": 10000},
                {"arm": "A", "n": 100000},
                {"arm": "B", "n": 10000},
                {"arm": "B", "n": 100000},
            ],
        }
        if arms["A"]["source_sha"] == arms["B"]["source_sha"]:
            _fail(D1Blocked, "D1F_SOURCE", "paired arms have identical source SHAs")
        if arms["A"]["binary_sha256"] == arms["B"]["binary_sha256"]:
            _fail(D1Blocked, "D1F_SOURCE", "paired arms produced identical adapter binaries")
    _write_authorization(out, campaign, base, candidate)
    manifest = _make_manifest(
        campaign,
        protocol,
        protocol_sha,
        base,
        candidate,
        environment,
        corpus,
        arms,
        builds,
        control=control,
    )
    if binary_mismatch is not None:
        manifest["control_binary_mismatch"] = binary_mismatch
    sentinels = index_sentinel_failures(manifest, protocol)
    if sentinels:
        _fail(D1Blocked, "D1F_INDEX_SENTINEL", json.dumps(sentinels, sort_keys=True))
    _write_setup(out, arms, corpus, builds)
    lanes = lane_descriptors(protocol)
    plan = slot_plan(protocol, kind)
    controller_cpu, adapter_cpu = affinity_plan()
    pin_controller(controller_cpu)
    slots = []
    for entry in plan:
        slot = run_slot(harness, adapter_cpu, entry, out, lanes, corpus["expected_by_lane"], arms, protocol)
        write_exclusive_json(os.path.join(out, "raw", "slots", f"slot-{entry['slot']:02d}.json"), slot)
        slots.append(slot)
    write_exclusive_json(os.path.join(out, "manifest.json"), manifest)
    summary = assemble_campaign(campaign, manifest, protocol, slots, lanes)
    write_exclusive_json(os.path.join(out, "sanitized", "summary.json"), summary)
    write_exclusive_text(os.path.join(out, "sanitized", "summary.md"), render_summary_markdown(summary))
    seal = write_seal(out, kind, protocol, builds)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "campaign": summary["campaign"],
                "gates": summary.get("gates", {}),
                "seal_members": len(seal["files"]),
            },
            sort_keys=True,
        )
    )
    qualified = summary["status"] in ("CONTROL_QUALIFIED", "CAMPAIGN_QUALIFIED")
    return 0 if qualified else 3

def cmd_verify(args) -> int:
    verify_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify.py")
    result = subprocess.run(
        [sys.executable, verify_script, "--campaign-dir", args.campaign_dir],
        check=False,
    )
    return result.returncode


def _archive_members(campaign_dir: str, protocol: dict) -> list[str]:
    excludes = tuple(protocol["archive_excludes"])
    members = []
    for root, dirs, names in os.walk(campaign_dir):
        relative_root = os.path.relpath(root, campaign_dir).replace(os.sep, "/")
        if relative_root == ".":
            relative_root = ""
        kept = []
        for directory in sorted(dirs):
            relative_dir = f"{relative_root}/{directory}".lstrip("/")
            if any(relative_dir == prefix.rstrip("/") or (relative_dir + "/").startswith(prefix) for prefix in excludes):
                continue
            kept.append(directory)
        dirs[:] = kept
        for name in sorted(names):
            relative = f"{relative_root}/{name}".lstrip("/")
            if any(relative == prefix.rstrip("/") or relative.startswith(prefix) for prefix in excludes):
                continue
            members.append(relative)
    return sorted(members)


def verify_archive(archive_path: str, expected_inventory: dict) -> dict:
    """Safely extract an archive and re-hash every expected member."""
    import tarfile

    scratch = tempfile.mkdtemp(prefix="pr15i-d1-f-archive-")
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            names = archive.getnames()
            if sorted(names) != sorted(expected_inventory):
                _fail(D1Blocked, "D1F_ARCHIVE", "archive member inventory differs")
            for name in names:
                if name.startswith("/") or name.startswith("\\") or ".." in name.split("/"):
                    _fail(D1Blocked, "D1F_ARCHIVE", f"unsafe archive member {name!r}")
            archive.extractall(scratch, filter="data")
        for relative, expected in expected_inventory.items():
            if sha256_file(os.path.join(scratch, relative)) != expected:
                _fail(D1Blocked, "D1F_ARCHIVE", f"archive round-trip hash differs: {relative}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"members": dict(expected_inventory)}


def write_archive(campaign_dir: str, archive_path: str, members: list[str]) -> dict:
    """Create an exclusive archive and prove it by extraction and re-hashing."""
    if os.path.exists(archive_path):
        _fail(D1Invalid, "D1F_ARCHIVE_EXISTS", f"archive already exists (never overwritten): {archive_path}")
    import tarfile

    descriptor = os.open(archive_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.close(descriptor)
    inventory = {}
    try:
        with tarfile.open(archive_path, "w:gz") as archive:
            for relative in members:
                full = os.path.join(campaign_dir, relative)
                _require_regular_file(full)
                info = archive.gettarinfo(full, arcname=relative)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with open(full, "rb") as handle:
                    archive.addfile(info, handle)
                inventory[relative] = sha256_file(full)
        verify_archive(archive_path, inventory)
    except BaseException:
        # A failed archive stays in place; it is never truncated or resumed.
        raise
    return inventory


def cmd_publish(args) -> int:
    protocol, _protocol_sha = load_protocol()
    campaign_dir = validate_campaign_dir(args.campaign_dir, "campaign-dir")
    evidence_root = os.path.abspath(args.evidence_root)
    if os.path.islink(evidence_root):
        _fail(D1Invalid, "D1F_SYMLINK", "evidence-root is a symlink")
    os.makedirs(evidence_root, exist_ok=True)
    campaign = read_json_strict(os.path.join(campaign_dir, "manifest.json"))["campaign"]
    archive_path = os.path.join(evidence_root, f"{campaign}.tar.gz")
    sidecar_path = archive_path + ".sha256"
    if os.path.exists(archive_path) or os.path.exists(sidecar_path):
        _fail(D1Invalid, "D1F_ARCHIVE_EXISTS", f"archive already exists (never overwritten): {archive_path}")
    verify_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify.py")
    result = subprocess.run(
        [sys.executable, verify_script, "--campaign-dir", campaign_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(D1Blocked, "D1F_VERIFY", f"independent verification failed:\n{result.stdout}\n{result.stderr}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        _fail(D1Blocked, "D1F_VERIFY", f"verifier output is not JSON: {error}")
    if report.get("verification") != "PASS":
        _fail(D1Blocked, "D1F_VERIFY", "verifier did not return PASS")
    write_exclusive_json(
        os.path.join(campaign_dir, "verification.json"),
        {
            "schema": SCHEMA_VERIFICATION,
            "campaign": campaign,
            "verifier": "verify.py",
            "verification": report["verification"],
            "campaign_status": report["campaign_status"],
            "reasons": report.get("reasons", []),
            "member_count": report.get("member_count"),
            "recorded_utc": utc_now(),
        },
    )
    members = _archive_members(campaign_dir, protocol)
    inventory = write_archive(campaign_dir, archive_path, members)
    archive_sha = sha256_file(archive_path)
    write_exclusive_json(
        sidecar_path,
        {
            "schema": SCHEMA_ARCHIVE,
            "campaign": campaign,
            "archive": os.path.basename(archive_path),
            "archive_sha256": archive_sha,
            "member_count": len(inventory),
            "members": inventory,
            "recorded_utc": utc_now(),
        },
    )
    print(
        json.dumps(
            {
                "status": "PUBLISHED",
                "campaign": campaign,
                "archive_sha256": archive_sha,
                "member_count": len(inventory),
            },
            sort_keys=True,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr15i-d1-f-controller", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(sub, campaign=True):
        if campaign:
            sub.add_argument("--campaign", required=True)
        sub.add_argument("--out", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--base-tree", required=True)
    preflight.add_argument("--base-sha", required=True)
    preflight.add_argument("--candidate-tree", required=True)
    preflight.add_argument("--candidate-sha", required=True)
    preflight.add_argument("--campaign", default="c2-base-01")
    preflight.add_argument("--out", required=True)
    preflight.set_defaults(handler=cmd_preflight)

    paired = subparsers.add_parser("paired")
    paired.add_argument("--base-tree", required=True)
    paired.add_argument("--base-sha", required=True)
    paired.add_argument("--candidate-tree", required=True)
    paired.add_argument("--candidate-sha", required=True)
    paired.add_argument("--idle-confirmed", action="store_true")
    common(paired)
    paired.set_defaults(handler=cmd_paired)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--campaign-dir", required=True)
    verify.set_defaults(handler=cmd_verify)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--campaign-dir", required=True)
    publish.add_argument("--evidence-root", required=True)
    publish.set_defaults(handler=cmd_publish)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except D1Blocked as error:
        print(f"BLOCKED {error}", file=sys.stderr)
        return 3
    except D1Invalid as error:
        print(f"REJECTED {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"BLOCKED D1F_IO: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

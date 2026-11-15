#!/usr/bin/env python3
"""Independent verifier for PR 15I-D3-B sealed campaigns.

This module deliberately duplicates the controller's frozen protocol literals,
schedule parsing, statistics and gate arithmetic. It never imports ``run.py``
and never calls a controller verdict function: every median, block mean, drift
ratio, A/A ratio and gate result is recomputed from the sealed raw samples.

Usage::

    python3 benchmarks/pr15i_d3_b/verify.py --campaign-dir <sealed campaign>
    python3 benchmarks/pr15i_d3_b/verify.py --series-root <dir> --comparison d3b-base

Exit codes: 0 = verification PASS (a performance rejection is still a valid
campaign), 3 = verification FAIL (tampered/missing/ambiguous evidence or an
independently recomputed summary mismatch), 2 = bad arguments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_SHA = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
BASE_LABEL = "MAIN_PR97_BASE"
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
    "d3bf12-base": {
        "a": "BASE",
        "b": "D3B",
        "gates": [
            "D3B-P01",
            "D3B-P02",
            "D3B-P03",
            "D3B-P04",
            "D3B-P05",
            "D3B-P06",
        ],
    },
}

GATES = {
    "D3B-P01": {
        "kind": "targeted",
        "lane": "pr15d_v1/100000/common/k100",
        "median_min_ns": 2_000_000,
        "blocks_at_least_ns": 0,
        "blocks_at_least_count": 3,
    },
    "D3B-P02": {
        "kind": "targeted",
        "lane": "pr15d_v1/100000/medium/k100",
        "median_min_ns": 1_000_000,
        "blocks_at_least_ns": 0,
        "blocks_at_least_count": 3,
    },
    "D3B-P03": {
        "kind": "k10_guard",
        "lane": "pr15d_v1/100000/common/k10",
        "median_floor_ns": -500_000,
        "block_floor_ns": -1_500_000,
        "median_ratio_ceiling": 1.05,
    },
    "D3B-P04": {
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
    "D3B-P05": {
        "kind": "guards",
        "lanes": [
            "pr15d_v1/10000/common/k100",
            "pr15d_v1/10000/medium/k100",
        ],
        "median_floor_ns": -2_000_000,
        "block_floor_ns": -3_000_000,
    },
    "D3B-P06": {
        "kind": "guards",
        "lanes": [
            "pr15d_v1/100000/medium/k100",
            "pr15d_v1/100000/common/k100",
        ],
        "median_floor_ns": -500_000,
        "block_floor_ns": -1_500_000,
    },
}

PROTOCOL = {
    "schema": "pr15i-d3b-f1-2-canonical-build-v1",
    "study_type": "RETAINED_KEY_PREFILTER_K100_STABLE_HOST_REQUALIFICATION_F1_2",
    "diagnostic_only": False,
    "base_label": BASE_LABEL,
    "base_source_sha": BASE_SHA,
    "corpus_manifest_sha256": CORPUS_MANIFEST_SHA256,
    "comparisons": COMPARISONS,
    "campaign_suffixes": ["01", "02", "03"],
    "control_suffix": "aa-01",
    "control_suffixes": ["aa-01", "aa-02"],
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
        "exempt_lanes": [
            "pr15d_v1/10000/absent/k100",
            "pr15d_v1/10000/rare/k100",
        ],
        "exempt_max_soft_outliers_per_lane": 1,
        "exempt_hard_low": 0.67,
        "exempt_hard_high": 1.50,
        "median_exception": False,
    },
    "gates": GATES,
    "host_readiness": {
        "schema": "pr15i-d3bf12-host-readiness-v1",
        "settle_ms": 5000,
        "intervals": 6,
        "interval_ms": 1000,
        "minimum_actual_interval_ms": 800,
        "maximum_actual_interval_ms": 1500,
        "max_busy_permille": 250,
        "max_median_busy_permille": 100,
        "max_steal_permille": 20,
        "cpu_roles": ["adapter", "controller"],
        "optional_frequency_observation": True,
        "queries_during_readiness": 0,
        "readiness_retries": 0,
        "missing_required_counter": "BLOCK",
    },
    "paired_structural_replacement": {
        "max_drift_only_invalid_attempts": 1,
        "maximum_paired_attempts": 3,
        "required_independent_qualified_passes": 2,
        "replacement_only_for": "VERIFIED_DRIFT_ONLY",
        "performance_rejection_retries": 0,
    },
    "canonical_build": {
        "mode": "ONE_PATH_SEQUENTIAL_CHECKOUT",
        "subdir": "compile-source",
        "target_subdirs": ["build/A", "build/B"],
        "control_two_real_builds": True,
        "require_aa_identical": True,
        "require_ab_distinct": True,
        "forbid_remap_flags": True,
    },
    "provenance_schema": "pr15i-d3bf1-build-and-host-v1",
    "tooling_directory": "benchmarks/pr15i_d3_b_f1_2",
    "target_subroot": "target/pr15i-d3-b/fixup-f1-2",
    "control_retry_requires_numerical_failure": True,
    "required_native_only": True,
    "evidence_root_relative": "benchmark-evidence/pr15i-d3-b-f1-2",
    "archive_excludes": ["build/", "indexes/", "corpus/"],
    "source_policy": {
        "production_changed": ["crates/quervant-core/src/search/unified.rs"],
        "required_unified_symbols": [
            "RetainedKeyPrefilter",
            "D3B_FILTER_BITS",
            "D3B_FILTER_WORDS",
            "D3B_MAX_ADMISSIONS",
            "request.top_k.limit == 100",
            "duplicate live document key across segments",
        ],
        "rejected_design_symbols": [
            "RetainedKeyFingerprintIndex",
            "retained_key_exists",
            "key_fingerprint",
            "index_insert_after_heap_push",
            "index_remove_after_heap_pop",
            "doc_key_view",
        ],
    },
}

SCHEMA_AUTHORIZATION = "pr15i-d3bf12-authorization-v1"
SCHEMA_MANIFEST = "pr15i-d3bf12-manifest-v1"
SCHEMA_PREFLIGHT = "pr15i-d3bf12-preflight-v1"
SCHEMA_SLOT = "pr15i-d3bf12-slot-v1"
SCHEMA_SUMMARY = "pr15i-d3bf12-summary-v1"
SCHEMA_SEAL = "pr15i-d3bf12-seal-v1"
SCHEMA_VERIFICATION = "pr15i-d3bf12-verification-v1"
SCHEMA_ARCHIVE = "pr15i-d3bf12-archive-v1"
SCHEMA_TOOLING = "pr15i-d3bf12-tooling-manifest-v1"
SCHEMA_BUILD_PROVENANCE = "pr15i-d3bf12-build-provenance-v1"
SCHEMA_HOST_READINESS = "pr15i-d3bf12-host-readiness-v1"
SCHEMA_ATTEMPT_SUCCESSION = "pr15i-d3bf12-attempt-succession-v1"
SCHEMA_HOST_ATTESTATION = "pr15i-d3bf12-host-attestation-v1"

MS = 1_000_000
TOOLING_DIR = "benchmarks/pr15i_d3_b_f1_2"
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
PROTECTED_SOURCES = ("crates/quervant-core/src/search/unified.rs",)
ALLOWED_CHANGED_EXACT = {
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/tests/pr15i_d3_b.rs",
    "docs/BENCHMARKING.md",
    "docs/ROADMAP.md",
}
ALLOWED_CHANGED_PREFIXES = (
    "benchmarks/pr15i_d3_b/",
    "benchmarks/pr15i_d3_b_f1_2/",
    "docs/pr-artifacts/pr-15i-d3-b/",
    "docs/pr-artifacts/pr-15i-d3-b-f1/",
)
FORBIDDEN_CHANGED = (
    "Cargo.lock",
    "Cargo.toml",
    ".github/",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/score.rs",
    "crates/quervant-core/src/index/snapshot.rs",
    "crates/quervant-core/src/segment/column.rs",
    "crates/quervant-core/src/segment/reader.rs",
)


class VerifyError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def reject(code: str, detail: str):
    raise VerifyError(code, detail)


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
            reject("V_JSON", f"duplicate JSON key {key!r}")
        seen.add(key)
    return dict(pairs)


def read_json(path: str):
    if os.path.islink(path):
        reject("V_SYMLINK", f"refusing symlink: {path}")
    if not os.path.isfile(path):
        reject("V_MISSING", f"missing regular file: {path}")
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"), object_pairs_hook=_no_duplicate_keys)


def git_common_root() -> str:
    result = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        reject("V_GIT", f"cannot resolve git common dir: {result.stderr.strip()}")
    return os.path.dirname(os.path.realpath(result.stdout.strip()))


def target_root() -> str:
    return os.path.join(git_common_root(), "target", "pr15i-d3-b", "fixup-f1-2")


def tooling_dir() -> str:
    return os.path.join(TOOLING_ROOT, TOOLING_DIR)


def expected_tooling_members() -> list[str]:
    members = []
    for name in sorted(os.listdir(tooling_dir())):
        if name in ("tooling_manifest.json", "__pycache__"):
            continue
        full = os.path.join(tooling_dir(), name)
        if os.path.islink(full):
            reject("V_TOOLING", f"tooling member is a symlink: {name}")
        if not os.path.isfile(full):
            reject("V_TOOLING", f"tooling member is not a regular file: {name}")
        members.append(name)
    return members


def verify_tooling_manifest() -> dict:
    """Independently validate the frozen tooling inventory and every digest."""
    path = os.path.join(tooling_dir(), "tooling_manifest.json")
    manifest = read_json(path)
    if manifest.get("schema") != SCHEMA_TOOLING:
        reject("V_TOOLING", "unknown tooling manifest schema")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        reject("V_TOOLING", "tooling manifest has no members")
    expected = expected_tooling_members()
    if sorted(files) != expected:
        reject("V_TOOLING", f"tooling file set differs: manifest {sorted(files)} != actual {expected}")
    for name, digest in files.items():
        if not isinstance(digest, str) or len(digest) != 64:
            reject("V_TOOLING", f"invalid tooling digest for {name}")
        if sha256_file(os.path.join(tooling_dir(), name)) != digest:
            reject("V_TOOLING", f"tooling member changed after freeze: {name}")
    return manifest


def load_protocol() -> tuple[dict, str]:
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_2/protocol_v1.json")
    try:
        raw = open(path, "rb").read()
    except OSError as error:
        reject("V_PROTOCOL", f"cannot read {path}: {error}")
    try:
        protocol = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        reject("V_PROTOCOL", f"malformed protocol: {error}")
    if protocol != PROTOCOL:
        reject("V_PROTOCOL", "protocol differs from the verifier's frozen literal")
    verify_tooling_manifest()
    return protocol, sha256_bytes(raw)


def confined_campaign(path: str) -> str:
    if not os.path.isabs(path):
        reject("V_PATH", "--campaign-dir must be absolute")
    if os.path.islink(path):
        reject("V_SYMLINK", "campaign directory is a symlink")
    allowed = target_root()
    candidate = os.path.realpath(path)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        reject("V_PATH", f"campaign must be strictly beneath {allowed}")
    if not os.path.isdir(candidate):
        reject("V_PATH", f"campaign directory missing: {candidate}")
    return candidate


def parse_lane(lane_id: str) -> dict:
    parts = lane_id.split("/")
    if len(parts) != 4 or parts[0] != "pr15d_v1":
        reject("V_LANE", f"malformed lane id {lane_id!r}")
    class_name = parts[2]
    k_text = parts[3]
    if class_name not in ("absent", "rare", "medium", "common"):
        reject("V_LANE", f"unknown class in {lane_id!r}")
    if not k_text.startswith("k") or not k_text[1:].isdigit():
        reject("V_LANE", f"malformed K in {lane_id!r}")
    n = int(parts[1])
    k = int(k_text[1:])
    if n not in (10000, 100000) or k <= 0:
        reject("V_LANE", f"unsupported lane {lane_id!r}")
    return {
        "id": lane_id,
        "n": n,
        "class": class_name,
        "field": "group" if class_name == "medium" else "key",
        "term": {"absent": "never", "rare": "singleton", "medium": "medium", "common": "common"}[class_name],
        "k": k,
        "regime": "warm",
    }


def lane_descriptors(protocol: dict) -> list[dict]:
    lanes = [parse_lane(lane_id) for lane_id in protocol["lane_ids"]]
    if [lane["id"] for lane in lanes] != protocol["lane_ids"]:
        reject("V_LANE", "lane order changed")
    return lanes


def slot_plan(protocol: dict, kind: str) -> list[dict]:
    orders = protocol["arm_order_by_block"]
    expected_arms = ["A", "A", "B", "B"]
    plan = []
    for block, order in enumerate(orders, start=1):
        if len(order) != protocol["slots_per_block"] or sorted(order) != expected_arms:
            reject("V_SCHEDULE", f"block {block} is not arm-balanced")
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
        reject("V_SCHEDULE", "slot count mismatch")
    return plan

def campaign_kind(name: str, protocol: dict) -> tuple[str, str]:
    for comparison in protocol["comparisons"]:
        for suffix in protocol["control_suffixes"]:
            if name == f"{comparison}-{suffix}":
                return comparison, "control"
        for suffix in protocol["campaign_suffixes"]:
            if name == f"{comparison}-{suffix}":
                return comparison, "paired"
    reject("V_CAMPAIGN", f"unknown campaign name {name!r}")


# ---------------------------------------------------------------------------
# Independent statistics
# ---------------------------------------------------------------------------


def validate_samples(samples, label: str) -> None:
    if not isinstance(samples, list) or len(samples) != PROTOCOL["samples_per_lane_slot"]:
        reject("V_SAMPLE_COUNT", f"{label}: expected 20 samples")
    for value in samples:
        if isinstance(value, bool) or not isinstance(value, int):
            reject("V_SAMPLE_TYPE", f"{label}: sample {value!r} is not an integer")
        if value <= 0:
            reject("V_SAMPLE_DOMAIN", f"{label}: sample {value!r} is not positive")


def median20(samples, label: str) -> int:
    validate_samples(samples, label)
    return sorted(samples)[9]


def mean_floor(first: int, second: int) -> int:
    return (first + second) // 2


def ratio(high: int, low: int) -> float:
    if low <= 0:
        reject("V_RATIO", "non-positive duration")
    value = high / low
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        reject("V_RATIO", f"invalid ratio {value!r}")
    return value


def lower_median_of_four(values, label: str):
    if len(values) != 4:
        reject("V_GATE", f"{label}: expected four values")
    return sorted(values)[1]


def slot_medians(slot: dict, lanes: list[dict]) -> dict[str, int]:
    records = slot.get("lanes")
    if not isinstance(records, list) or [record.get("id") for record in records] != [lane["id"] for lane in lanes]:
        reject("V_SLOT", f"slot {slot.get('slot')}: lane order/count differs")
    for lane, record in zip(lanes, records, strict=True):
        if record.get("field") != lane["field"] or record.get("term") != lane["term"] or record.get("k") != lane["k"]:
            reject("V_SLOT", f"slot {slot.get('slot')}: {lane['id']} descriptor differs")
        if record.get("n") != lane["n"] or record.get("class") != lane["class"]:
            reject("V_SLOT", f"slot {slot.get('slot')}: {lane['id']} class differs")
        if record.get("warmups") != PROTOCOL["warmups_per_lane_slot"]:
            reject("V_SLOT", f"slot {slot.get('slot')}: {lane['id']} warmup count differs")
        warmup_ids = record.get("warmup_ids")
        if not isinstance(warmup_ids, list) or len(warmup_ids) != PROTOCOL["warmups_per_lane_slot"]:
            reject("V_SLOT", f"slot {slot.get('slot')}: {lane['id']} warmup ids differ")
        summary = record.get("summary_ns") or {}
        if summary.get("count") != 20 or summary.get("median") != sorted(record["samples_ns"])[9]:
            reject("V_SLOT", f"slot {slot.get('slot')}: {lane['id']} summary differs")
    return {lane["id"]: median20(record["samples_ns"], f"slot {slot.get('slot')}:{lane['id']}") for lane, record in zip(lanes, records, strict=True)}


def block_arm_medians(slots: list[dict], lanes: list[dict], arm: str, blocks: int) -> dict[int, dict[str, int]]:
    grouped: dict[int, dict[str, list[int]]] = {}
    for slot in slots:
        if slot.get("arm") != arm:
            continue
        block = slot.get("block")
        medians = slot_medians(slot, lanes)
        per_lane = grouped.setdefault(block, {lane["id"]: [] for lane in lanes})
        for lane_id, value in medians.items():
            per_lane[lane_id].append(value)
    if sorted(grouped) != list(range(1, blocks + 1)):
        reject("V_SCHEDULE", f"arm {arm} blocks differ")
    result = {}
    for block, per_lane in grouped.items():
        result[block] = {}
        for lane_id, values in per_lane.items():
            if len(values) != 2:
                reject("V_SCHEDULE", f"arm {arm} block {block} lane {lane_id}: {len(values)} slots")
            result[block][lane_id] = mean_floor(values[0], values[1])
    return result


def drift_caps(lane: dict) -> tuple[float, float]:
    drift = PROTOCOL["drift"]
    if lane["n"] == 100000 and lane["class"] in ("medium", "common"):
        return (drift["100k_medium_common_block_max_ratio"], drift["100k_medium_common_within_block_max_ratio"])
    return (drift["other_block_max_ratio"], drift["other_within_block_max_ratio"])


def drift_violations(slots: list[dict], lanes: list[dict], blocks: int) -> list[dict]:
    violations = []
    medians_by_slot = {slot["slot"]: slot_medians(slot, lanes) for slot in slots}
    grouped: dict[str, dict[int, list[tuple[int, dict[str, int]]]]] = {}
    for slot in slots:
        grouped.setdefault(slot["arm"], {}).setdefault(slot["block"], []).append(
            (slot["slot"], medians_by_slot[slot["slot"]])
        )
    for arm, per_block in grouped.items():
        for lane in lanes:
            block_cap, within_cap = drift_caps(lane)
            block_values = []
            for block in range(1, blocks + 1):
                entries = per_block.get(block, [])
                if len(entries) != 2:
                    violations.append({"gate": "BLOCK_SHAPE", "arm": arm, "block": block})
                    continue
                values = [entry[1][lane["id"]] for entry in entries]
                within = ratio(max(values), min(values))
                if within > within_cap:
                    violations.append(
                        {"gate": "WITHIN_BLOCK_DRIFT", "arm": arm, "lane": lane["id"], "block": block, "ratio": within, "cap": within_cap}
                    )
                block_values.append(mean_floor(values[0], values[1]))
            if len(block_values) == blocks:
                between = ratio(max(block_values), min(block_values))
                if between > block_cap:
                    violations.append(
                        {"gate": "BLOCK_DRIFT", "arm": arm, "lane": lane["id"], "ratio": between, "cap": block_cap}
                    )
    return violations


def compute_paired_metrics(slots: list[dict], lanes: list[dict]) -> dict:
    blocks = PROTOCOL["blocks_per_campaign"]
    arm_a = block_arm_medians(slots, lanes, "A", blocks)
    arm_b = block_arm_medians(slots, lanes, "B", blocks)
    metrics = {}
    for lane in lanes:
        a_values = [arm_a[block][lane["id"]] for block in range(1, blocks + 1)]
        b_values = [arm_b[block][lane["id"]] for block in range(1, blocks + 1)]
        diffs = [a - b for a, b in zip(a_values, b_values)]
        ratios = [ratio(b, a) for a, b in zip(a_values, b_values)]
        metrics[lane["id"]] = {
            "id": lane["id"],
            "class": lane["class"],
            "n": lane["n"],
            "a_block_medians_ns": a_values,
            "b_block_medians_ns": b_values,
            "diffs_ns": diffs,
            "median_diff_ns": lower_median_of_four(diffs, lane["id"]),
            "median_diff_ms": lower_median_of_four(diffs, lane["id"]) / 1_000_000,
            "b_over_a_block": ratios,
            "b_over_a_median": sorted(ratios)[1],
        }
    return metrics


def compute_gates(comparison: str, metrics: dict) -> dict:
    table = {"D3B-P00": "PASS", "D3B-P07": "PASS"}
    for gate_id in COMPARISONS[comparison]["gates"]:
        spec = GATES[gate_id]
        if spec["kind"] == "targeted":
            entry = metrics[spec["lane"]]
            passes = entry["median_diff_ns"] >= spec["median_min_ns"] and (
                sum(1 for value in entry["diffs_ns"] if value >= spec["blocks_at_least_ns"])
                >= spec["blocks_at_least_count"]
            )
        elif spec["kind"] == "guards":
            passes = all(
                metrics[lane_id]["median_diff_ns"] > spec["median_floor_ns"]
                and all(value >= spec["block_floor_ns"] for value in metrics[lane_id]["diffs_ns"])
                for lane_id in spec["lanes"]
            )
        elif spec["kind"] == "k10_guard":
            entry = metrics[spec["lane"]]
            passes = (
                entry["median_diff_ns"] >= spec["median_floor_ns"]
                and all(value >= spec["block_floor_ns"] for value in entry["diffs_ns"])
                and entry["b_over_a_median"] <= spec["median_ratio_ceiling"]
            )
        elif spec["kind"] == "low_hit_ratios":
            passes = all(
                metrics[lane_id]["b_over_a_median"] <= spec["median_ratio_ceiling"]
                and all(value <= spec["block_ratio_ceiling"] for value in metrics[lane_id]["b_over_a_block"])
                for lane_id in spec["lanes"]
            )
        else:
            reject("V_GATE", f"unknown gate kind {spec['kind']!r}")
        table[gate_id] = "PASS" if passes else "FAIL"
    return table


def compute_control(slots: list[dict], lanes: list[dict]) -> dict:
    """Independent prospective A/A qualification recomputation."""
    blocks = PROTOCOL["blocks_per_campaign"]
    arm_a = block_arm_medians(slots, lanes, "A", blocks)
    arm_b = block_arm_medians(slots, lanes, "B", blocks)
    spec = PROTOCOL["a_a"]
    exempt = set(spec["exempt_lanes"])
    lanes_report = {}
    failed = False
    for lane in lanes:
        block_ratios = []
        detail = []
        for block in range(1, blocks + 1):
            a = arm_a[block][lane["id"]]
            b = arm_b[block][lane["id"]]
            value = ratio(b, a)
            block_ratios.append(value)
            detail.append({"block": block, "a_ns": a, "b_ns": b, "ratio": value})
        median_ratio = sorted(block_ratios)[1]
        soft_outliers = [
            index
            for index, value in enumerate(block_ratios)
            if value < spec["ratio_low"] or value > spec["ratio_high"]
        ]
        hard_ok = all(
            spec["ratio_low"] <= value <= spec["ratio_high"]
            or spec["exempt_hard_low"] <= value <= spec["exempt_hard_high"]
            for value in block_ratios
        )
        lane_ok = spec["median_low"] <= median_ratio <= spec["median_high"]
        if lane["id"] in exempt:
            lane_ok = (
                lane_ok
                and len(soft_outliers) <= spec["exempt_max_soft_outliers_per_lane"]
                and hard_ok
            )
        else:
            lane_ok = lane_ok and not soft_outliers and hard_ok
        failed = failed or not lane_ok
        lanes_report[lane["id"]] = {
            "blocks": detail,
            "median_ratio": median_ratio,
            "soft_outliers": [value + 1 for value in soft_outliers],
            "blocks_ok": not soft_outliers,
            "hard_bounds_ok": hard_ok,
            "passes": lane_ok,
        }
    return {"passes": not failed, "lanes": lanes_report, "bounds": spec}


def verify_seal(campaign_dir: str) -> dict:
    seal = read_json(os.path.join(campaign_dir, "raw", "seal.json"))
    if seal.get("schema") != SCHEMA_SEAL or seal.get("kind") not in ("paired", "control"):
        reject("V_SEAL", "unknown seal schema/kind")
    files = seal.get("files")
    if not isinstance(files, dict) or not files:
        reject("V_SEAL", "seal has no members")
    for relative, expected in files.items():
        if relative.startswith("/") or relative.startswith("\\") or ".." in relative.replace("\\", "/").split("/"):
            reject("V_SEAL", f"unsafe sealed member {relative!r}")
        if not isinstance(expected, str) or len(expected) != 64:
            reject("V_SEAL", f"invalid digest for {relative!r}")
        full = os.path.join(campaign_dir, relative)
        if os.path.islink(full):
            reject("V_SYMLINK", f"sealed member is a symlink: {relative}")
        if not os.path.isfile(full):
            reject("V_MISSING", f"sealed member missing: {relative}")
        if sha256_file(full) != expected:
            reject("V_SEAL", f"sealed member changed: {relative}")
    return seal


ROOT_EXCLUDED_DIRS = frozenset({"build", "indexes", "corpus", "compile-source"})


def verify_inventory(campaign_dir: str, seal: dict) -> dict:
    """Every evidence file must be sealed; only the receipt is extra.

    F1.1/F11-R1: the mandated campaign-local ``compile-source`` worktree is the
    only newly exempted directory, and only at the campaign root. It is never a
    sealed member and never accepted as a source-identity substitute. The same
    name nested below any subdirectory is still reported as unlisted.
    """
    sealed = set(seal["files"])
    compile_source = os.path.join(campaign_dir, "compile-source")
    if os.path.islink(compile_source):
        reject("V_SYMLINK", "compile-source is a symlink")
    if os.path.lexists(compile_source) and not os.path.isdir(compile_source):
        reject("V_INVENTORY", "compile-source is not a directory")
    if any(
        path == "compile-source" or path.startswith("compile-source/")
        for path in seal["files"]
    ):
        reject("V_SEAL", "compile-source must not be sealed")
    for root, dirs, names in os.walk(campaign_dir, topdown=True, followlinks=False):
        relative_root = os.path.relpath(root, campaign_dir).replace(os.sep, "/")
        if relative_root == ".":
            relative_root = ""
        retained = []
        for name in sorted(dirs):
            rel = f"{relative_root}/{name}".lstrip("/")
            if relative_root == "" and name in ROOT_EXCLUDED_DIRS:
                continue
            if os.path.islink(os.path.join(root, name)):
                reject("V_SYMLINK", f"symlinked evidence directory: {rel}")
            retained.append(name)
        dirs[:] = retained
        for name in sorted(names):
            relative = f"{relative_root}/{name}".lstrip("/")
            if relative in ("raw/seal.json", "verification.json"):
                continue
            if relative not in sealed:
                reject("V_INVENTORY", f"unlisted campaign member: {relative}")
    return {"member_count": len(sealed)}


def verify_sources(manifest: dict, protocol_sha: str) -> None:
    if manifest.get("protocol_sha256") != protocol_sha:
        reject("V_PROTOCOL", "manifest protocol digest differs from the frozen file")
    for field in ("tooling_sha", "base_source_sha", "candidate_source_sha"):
        value = manifest.get(field)
        if not isinstance(value, str) or len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            reject("V_SOURCE", f"invalid {field} {value!r}")
    tooling = manifest["tooling_sha"]
    for relative, field in (
        ("benchmarks/pr15i_d3_b_f1_2/run.py", "controller_sha256"),
        ("benchmarks/pr15i_d3_b_f1_2/verify.py", "verifier_sha256"),
    ):
        result = subprocess.run(
            ["git", "-C", TOOLING_ROOT, "show", f"{tooling}:{relative}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            reject("V_TOOLING_SHA", f"cannot resolve {relative} at tooling SHA {tooling}")
        if sha256_bytes(result.stdout) != manifest.get(field):
            reject("V_TOOLING_SHA", f"{field} does not match the frozen tooling commit")
    comparison, kind = campaign_kind(manifest["campaign"], PROTOCOL)
    if comparison != manifest.get("comparison") or kind != manifest.get("kind"):
        reject("V_IDENTITY", "campaign name/comparison/kind differ")
    if manifest["base_source_sha"] != PROTOCOL["base_source_sha"]:
        reject("V_SOURCE", "arm A is not the verified BASE")
    if kind == "control":
        if manifest["candidate_source_sha"] != manifest["base_source_sha"]:
            reject("V_SOURCE", "A/A control arms must share the verified BASE")
        if sorted(manifest["arms"]) != ["A", "B"]:
            reject("V_SOURCE", "A/A control must declare A/B arms")
    else:
        if manifest["candidate_source_sha"] == manifest["base_source_sha"]:
            reject("V_SOURCE", "paired arms share one source SHA")
        if sorted(manifest["arms"]) != ["A", "B"]:
            reject("V_SOURCE", "paired campaign must declare A/B arms")
        descendant = subprocess.run(
            ["git", "-C", TOOLING_ROOT, "merge-base", "--is-ancestor", manifest["base_source_sha"], manifest["candidate_source_sha"]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if descendant.returncode != 0:
            reject("V_SOURCE", "D3-B candidate does not descend from BASE")
    for role, expected_sha in (("A", manifest["base_source_sha"]), ("B", manifest["candidate_source_sha"])):
        fingerprints = manifest.get("source_fingerprints", {}).get(role)
        if not isinstance(fingerprints, dict) or not fingerprints:
            reject("V_SOURCE", f"missing source fingerprints for {role}")
        for relative, expected in fingerprints.items():
            if relative not in PROTECTED_SOURCES:
                reject("V_SOURCE", f"unexpected fingerprinted path {relative}")
            result = subprocess.run(
                ["git", "-C", TOOLING_ROOT, "show", f"{expected_sha}:{relative}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode != 0:
                reject("V_SOURCE", f"cannot resolve {relative} at {expected_sha}")
            if sha256_bytes(result.stdout) != expected:
                reject("V_SOURCE", f"{relative} fingerprint differs at {expected_sha}")
    for arm in ("A", "B"):
        if manifest["arms"][arm]["source_sha"] != manifest[f"{'base' if arm == 'A' else 'candidate'}_source_sha"]:
            reject("V_SOURCE", f"arm {arm} build SHA differs from its declared source")
    changed = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "diff", "--name-only", manifest["base_source_sha"], manifest["candidate_source_sha"]],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if changed.returncode != 0:
        reject("V_SOURCE", f"cannot diff source identities: {changed.stderr.strip()}")
    for path in changed.stdout.splitlines():
        normalized = path.strip()
        if not normalized:
            continue
        if normalized in ALLOWED_CHANGED_EXACT or any(normalized.startswith(prefix) for prefix in ALLOWED_CHANGED_PREFIXES):
            continue
        if any(normalized == entry or normalized.startswith(entry) for entry in FORBIDDEN_CHANGED):
            reject("V_SOURCE", f"forbidden changed path outside the D3-B allowlist: {normalized}")
        reject("V_SOURCE", f"unexpected changed path outside the D3-B allowlist: {normalized}")
    if manifest.get("tooling_manifest_sha256") != sha256_file(
        os.path.join(tooling_dir(), "tooling_manifest.json")
    ):
        reject("V_TOOLING", "manifest tooling inventory digest differs")
    verify_frozen_inputs_for_revision(manifest["base_source_sha"])
    verify_frozen_inputs_for_revision(manifest["candidate_source_sha"])
    if kind == "paired":
        verify_d3b_source_proof(manifest["candidate_source_sha"])


def verify_d3b_source_proof(candidate_sha: str) -> None:
    """Independent source proof for the only changed production file."""
    relative = "crates/quervant-core/src/search/unified.rs"
    result = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "show", f"{candidate_sha}:{relative}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        reject("V_SOURCE", f"cannot read {relative} at candidate SHA")
    source = result.stdout.decode("utf-8", "replace")
    policy = PROTOCOL["source_policy"]
    missing = [symbol for symbol in policy["required_unified_symbols"] if symbol not in source]
    if missing:
        reject("V_SOURCE", f"candidate {relative} lacks required D3-B symbols {missing!r}")
    found = [symbol for symbol in policy["rejected_design_symbols"] if symbol in source]
    if found:
        reject("V_SOURCE", f"candidate {relative} contains rejected design symbols {found!r}")
    if policy["production_changed"] != [relative]:
        reject("V_PROTOCOL", "unexpected production_changed policy")

FROZEN_ADAPTER_LOCK_RELATIVE = "benchmarks/pr15d/adapters/quervant/Cargo.lock"


def _default_blob_reader(sha: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "show", f"{sha}:{relative}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        reject("V_FROZEN_INPUT", f"cannot read {relative} at {sha}")
    return result.stdout


def verify_frozen_inputs_for_revision(sha: str, blob_reader=None) -> dict:
    """V01: independently hash the immutable Git blobs for one revision."""
    if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        reject("V_SOURCE", f"invalid revision {sha!r}")
    reader = blob_reader or _default_blob_reader
    expected = dict(FROZEN_INPUTS)
    expected[FROZEN_ADAPTER_LOCK_RELATIVE] = FROZEN_ADAPTER_LOCK_SHA256
    for relative, digest in sorted(expected.items()):
        payload = reader(sha, relative)
        if sha256_bytes(payload) != digest:
            reject("V_FROZEN_INPUT", f"{relative} differs at {sha}")
    return {"revision": sha, "files": sorted(expected)}


def _bool_int(value) -> bool:
    return isinstance(value, bool) or not isinstance(value, int)


def build_provenance_failures(record: dict, manifest: dict, protocol_sha: str) -> list[dict]:
    """V02: independent structural validation of the sealed build provenance."""
    failures: list[dict] = []

    def fail(code: str, detail: str) -> None:
        failures.append({"code": code, "detail": detail})

    if not isinstance(record, dict):
        fail("V_BUILD_PROVENANCE", "provenance is not an object")
        return failures
    if record.get("schema") != SCHEMA_BUILD_PROVENANCE:
        fail("V_BUILD_PROVENANCE", "wrong provenance schema")
    if record.get("protocol_sha256") != protocol_sha:
        fail("V_PROTOCOL", "provenance protocol digest differs")
    if record.get("canonical_build_mode") != PROTOCOL["canonical_build"]["mode"]:
        fail("V_BUILD_PROVENANCE", "unexpected canonical build mode")
    canonical = record.get("canonical_source_path")
    if not isinstance(canonical, str) or not os.path.isabs(canonical):
        fail("V_BUILD_PROVENANCE", "canonical source path is not absolute")
        canonical = ""
    else:
        if os.path.basename(canonical) != PROTOCOL["canonical_build"]["subdir"]:
            fail("V_BUILD_PROVENANCE", "canonical source path has the wrong basename")
        campaign_dirname = os.path.basename(os.path.dirname(canonical))
        if campaign_dirname != record.get("campaign"):
            fail("V_BUILD_PROVENANCE", "canonical source path is not inside the campaign directory")
    events = record.get("events")
    if not isinstance(events, list) or len(events) != 2:
        fail("V_BUILD_PROVENANCE", "provenance must contain exactly two build events")
        return failures
    arms = [event.get("arm") for event in events if isinstance(event, dict)]
    if arms != ["A", "B"]:
        fail("V_BUILD_PROVENANCE", f"build event arms are {arms!r}")
        return failures
    expected = {
        "A": manifest["base_source_sha"],
        "B": manifest["candidate_source_sha"] if manifest["kind"] == "paired" else manifest["base_source_sha"],
    }
    if record.get("expected_source_sha") != expected:
        fail("V_BUILD_PROVENANCE", "record expected source SHAs differ")
    build_ids = set()
    fingerprints = set()
    for event in events:
        arm = event["arm"]
        build_ids.add(event.get("build_id"))
        fingerprints.add(event.get("environment_fingerprint"))
        if event.get("expected_source_sha") != expected[arm]:
            fail("V_BUILD_PROVENANCE", f"arm {arm} expected source SHA differs")
        if event.get("pre_checkout_sha") != expected[arm] or event.get("post_checkout_sha") != expected[arm]:
            fail("V_BUILD_PROVENANCE", f"arm {arm} checkout SHA differs")
        if event.get("pre_source_sha256") != event.get("post_source_sha256"):
            fail("V_BUILD_PROVENANCE", f"arm {arm} source changed during its build")
        if event.get("source_tree_clean") is not True:
            fail("V_BUILD_PROVENANCE", f"arm {arm} source tree was not clean")
        if event.get("exit_status") != 0:
            fail("V_BUILD_PROVENANCE", f"arm {arm} build exit status is not zero")
        if event.get("canonical_source") != canonical:
            fail("V_BUILD_PROVENANCE", f"arm {arm} used a different canonical path")
        manifest_path = event.get("manifest_path")
        if manifest_path != os.path.join(canonical, "benchmarks/pr15d/adapters/quervant/Cargo.toml"):
            fail("V_BUILD_PROVENANCE", f"arm {arm} manifest path differs")
        cwd = event.get("cwd")
        if cwd != os.path.join(canonical, "benchmarks/pr15d/adapters/quervant"):
            fail("V_BUILD_PROVENANCE", f"arm {arm} build cwd differs")
        target_dir = event.get("target_dir")
        expected_target = os.path.join(os.path.dirname(canonical), "build", arm)
        if target_dir != expected_target:
            fail("V_BUILD_PROVENANCE", f"arm {arm} target directory differs")
        argv = event.get("command_argv")
        expected_argv = [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            manifest_path,
            "--target-dir",
            target_dir,
        ]
        if argv != expected_argv:
            fail("V_BUILD_PROVENANCE", f"arm {arm} command argv differs or has extra flags")
        if event.get("binary_path") != os.path.join(expected_target, "release", ADAPTER_BINARY):
            fail("V_BUILD_PROVENANCE", f"arm {arm} binary path differs")
        if event.get("binary_sha256") != manifest["arms"][arm]["binary_sha256"]:
            fail("V_BINARY", f"arm {arm} provenance digest differs from the manifest")
        if event.get("binary_bytes") != manifest["arms"][arm]["binary_bytes"]:
            fail("V_BINARY", f"arm {arm} provenance size differs from the manifest")
        codegen = event.get("codegen_flags") or {}
        if codegen.get("forbidden_present") not in ([], None):
            fail("V_BUILD_PROVENANCE", f"arm {arm} reports forbidden codegen flags")
        if codegen.get("locked") is not True or codegen.get("profile") != "release":
            fail("V_BUILD_PROVENANCE", f"arm {arm} build profile/lock differs")
        toolchain = event.get("toolchain") or {}
        if not toolchain.get("rustc") or not toolchain.get("cargo"):
            fail("V_BUILD_PROVENANCE", f"arm {arm} toolchain is incomplete")
        if not isinstance(event.get("started_utc"), str) or not isinstance(event.get("ended_utc"), str):
            fail("V_BUILD_PROVENANCE", f"arm {arm} timestamps missing")
    if len(build_ids) != 2 or None in build_ids:
        fail("V_BUILD_PROVENANCE", "build event identifiers are not distinct")
    if len(fingerprints) != 1 or None in fingerprints:
        fail("V_BUILD_PROVENANCE", "arm build environments differ")
    if events[1].get("started_utc") < events[0].get("ended_utc"):
        fail("V_BUILD_PROVENANCE", "the second build started before the first finished")
    if record.get("target_dirs") != {
        "A": events[0].get("target_dir"),
        "B": events[1].get("target_dir"),
    }:
        fail("V_BUILD_PROVENANCE", "target directory summary differs")
    if record.get("binary_sha256") != {
        "A": manifest["arms"]["A"]["binary_sha256"],
        "B": manifest["arms"]["B"]["binary_sha256"],
    }:
        fail("V_BUILD_PROVENANCE", "binary digest summary differs")
    if record.get("binary_bytes") != {
        "A": manifest["arms"]["A"]["binary_bytes"],
        "B": manifest["arms"]["B"]["binary_bytes"],
    }:
        fail("V_BUILD_PROVENANCE", "binary size summary differs")
    snapshot = record.get("pre_timing_snapshot")
    post = record.get("post_timing_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(post, dict):
        fail("V_BUILD_PROVENANCE", "binary snapshots are missing")
    elif snapshot != post:
        fail("V_BUILD_PROVENANCE", "a binary changed during timed acquisition")
    if manifest["kind"] == "control":
        if events[0]["binary_sha256"] != events[1]["binary_sha256"]:
            fail("V_AA_BINARY", "A/A binary digests differ")
        if events[0]["binary_bytes"] != events[1]["binary_bytes"]:
            fail("V_AA_BINARY", "A/A binary sizes differ")
        if record.get("aa_identical") is not True:
            fail("V_AA_BINARY", "aa_identical is not true")
        if manifest.get("control_binary_mismatch") is not None:
            fail("V_AA_BINARY", "control binary mismatch escape hatch is forbidden")
    else:
        if events[0]["binary_sha256"] == events[1]["binary_sha256"]:
            fail("V_AB_BINARY", "A/B binary digests are identical")
        if record.get("ab_distinct") is not True:
            fail("V_AB_BINARY", "ab_distinct is not true")
        transition = record.get("source_transition")
        if not isinstance(transition, dict):
            fail("V_BUILD_PROVENANCE", "paired source transition is missing")
        else:
            if transition.get("from_sha") != expected["A"] or transition.get("to_sha") != expected["B"]:
                fail("V_BUILD_PROVENANCE", "source transition revisions differ")
            if transition.get("argv") != ["git", "-C", canonical, "switch", "--detach", expected["B"]]:
                fail("V_BUILD_PROVENANCE", "source transition command differs")
    return failures


READINESS_FIELDS = 8
MAX_TICK = 2**64 - 1


def _is_tick(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_TICK


def parse_readiness_ticks(values, label: str) -> tuple[int, ...]:
    if not isinstance(values, list) or len(values) != READINESS_FIELDS:
        reject("V_READINESS", f"{label}: expected eight tick fields")
    if any(not _is_tick(value) for value in values):
        reject("V_READINESS", f"{label}: malformed tick counter")
    return tuple(values)


def host_readiness_failures(record: dict, manifest: dict, host: dict, protocol_sha: str) -> list[dict]:
    """Independently rederive every readiness metric from the raw tick arrays."""
    failures: list[dict] = []

    def fail(code: str, detail: str) -> None:
        failures.append({"code": code, "detail": detail})

    spec = PROTOCOL["host_readiness"]
    if not isinstance(record, dict):
        fail("V_READINESS", "readiness record is not an object")
        return failures
    if record.get("schema") != SCHEMA_HOST_READINESS:
        fail("V_READINESS", "wrong readiness schema")
    if record.get("protocol_sha256") != protocol_sha:
        fail("V_PROTOCOL", "readiness protocol digest differs")
    if record.get("campaign") != manifest.get("campaign"):
        fail("V_READINESS", "readiness campaign differs")
    role_cpus = record.get("role_cpus")
    if not isinstance(role_cpus, dict) or set(role_cpus) != {"adapter", "controller"}:
        fail("V_READINESS", "role_cpus shape differs")
        return failures
    adapter_cpu = role_cpus["adapter"]
    controller_cpu = role_cpus["controller"]
    if _bool_int(adapter_cpu) or _bool_int(controller_cpu) or adapter_cpu == controller_cpu:
        fail("V_READINESS", "invalid pinned CPU pair")
    if adapter_cpu != host.get("adapter_cpu") or controller_cpu != host.get("controller_cpu"):
        fail("V_READINESS", "readiness CPU pair differs from host attestation")
    if record.get("host_fingerprint") != host.get("host_fingerprint"):
        fail("V_READINESS", "readiness host fingerprint differs")
    observations = record.get("observations")
    if not isinstance(observations, list) or len(observations) != spec["intervals"] + 1:
        fail("V_READINESS", "readiness must contain seven observations")
        return failures
    monotonic = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            fail("V_READINESS", f"observation {index} is not an object")
            return failures
        ns = observation.get("monotonic_ns")
        if _bool_int(ns) or ns < 0:
            fail("V_READINESS", f"observation {index} has invalid monotonic time")
        monotonic.append(ns)
        cpus = observation.get("cpus")
        if not isinstance(cpus, dict) or set(cpus) != {str(adapter_cpu), str(controller_cpu)}:
            fail("V_READINESS", f"observation {index} CPU keys differ")
            return failures
        for cpu in (adapter_cpu, controller_cpu):
            try:
                parse_readiness_ticks(cpus[str(cpu)], f"observation {index} cpu{cpu}")
            except VerifyError as error:
                fail(error.code, error.detail)
    if any(later <= earlier for earlier, later in zip(monotonic, monotonic[1:])):
        fail("V_READINESS", "observation monotonic timestamps are not strictly increasing")
    start = record.get("settle_monotonic_start_ns")
    end = record.get("settle_monotonic_end_ns")
    if _bool_int(start) or _bool_int(end):
        fail("V_READINESS", "settle timestamps are invalid")
    elif not (4_500_000_000 <= end - start <= 7_500_000_000):
        fail("V_READINESS", "settle duration is outside the frozen window")
    stored_metrics = record.get("interval_metrics")
    stored_medians = record.get("lower_median_busy_permille")
    recomputed: dict[str, list[dict]] = {"adapter": [], "controller": []}
    medians: dict[str, int] = {}
    codes = set()
    for role, cpu in (("adapter", adapter_cpu), ("controller", controller_cpu)):
        busy_values = []
        for index in range(spec["intervals"]):
            first = observations[index]
            second = observations[index + 1]
            elapsed_ms = (second["monotonic_ns"] - first["monotonic_ns"]) / 1_000_000
            if not (
                spec["minimum_actual_interval_ms"]
                <= elapsed_ms
                <= spec["maximum_actual_interval_ms"]
            ):
                codes.add("INTERVAL_DURATION")
            a = first["cpus"][str(cpu)]
            b = second["cpus"][str(cpu)]
            deltas = [later - earlier for earlier, later in zip(a, b)]
            if any(delta < 0 for delta in deltas):
                codes.add("COUNTER_DECREASE")
                continue
            total = sum(deltas)
            if total <= 0:
                codes.add("ZERO_DELTA")
                continue
            idle = deltas[3]
            steal = deltas[7]
            busy = (1000 * (total - idle)) // total
            steal_permille = (1000 * steal) // total
            if busy > spec["max_busy_permille"]:
                codes.add("BUSY_EXCEEDED")
            if steal_permille > spec["max_steal_permille"]:
                codes.add("STEAL_EXCEEDED")
            busy_values.append(busy)
            recomputed[role].append(
                {
                    "interval": index + 1,
                    "actual_ms": elapsed_ms,
                    "busy_permille": busy,
                    "steal_permille": steal_permille,
                }
            )
        if len(busy_values) == spec["intervals"]:
            median = sorted(busy_values)[spec["intervals"] // 2 - 1]
            medians[role] = median
            if median > spec["max_median_busy_permille"]:
                codes.add("MEDIAN_BUSY_EXCEEDED")
        else:
            codes.add("INCOMPLETE_OBSERVATIONS")
    if stored_metrics != recomputed:
        fail("V_READINESS", "stored interval metrics differ from the recomputation")
    if stored_medians != medians:
        fail("V_READINESS", "stored lower medians differ from the recomputation")
    if record.get("readiness_status") != "READY":
        fail("V_READINESS", "readiness status is not READY")
    if record.get("failure_codes") != []:
        fail("V_READINESS", "readiness failure codes are not empty")
    if record.get("queries_executed") != 0:
        fail("V_READINESS", "readiness executed queries")
    frequency = record.get("optional_cpu_frequency_khz")
    if not isinstance(frequency, dict) or set(frequency) != {"adapter", "controller"}:
        fail("V_READINESS", "optional frequency shape differs")
    else:
        for value in frequency.values():
            if value is not None and (_bool_int(value) or value < 0):
                fail("V_READINESS", "optional frequency is invalid")
    if codes:
        fail("V_READINESS", f"recomputed readiness codes are nonempty: {sorted(codes)}")
    return failures


def verify_host_readiness(campaign_dir: str, manifest: dict, host: dict, protocol_sha: str) -> dict:
    full = os.path.join(campaign_dir, "raw", "host-readiness.json")
    record = read_json(full)
    if manifest.get("host_readiness_sha256") != sha256_file(full):
        reject("V_SEAL", "readiness digest differs from the manifest")
    failures = host_readiness_failures(record, manifest, host, protocol_sha)
    if failures:
        reject("V_READINESS", json.dumps(failures, sort_keys=True))
    return {"status": "PASS", "record": record}


def verify_build_provenance(campaign_dir: str, manifest: dict, protocol_sha: str) -> dict:
    full = os.path.join(campaign_dir, "raw", "build-provenance.json")
    record = read_json(full)
    if manifest.get("build_provenance_sha256") != sha256_file(full):
        reject("V_BUILD_PROVENANCE", "provenance digest differs from the manifest")
    failures = build_provenance_failures(record, manifest, protocol_sha)
    hard = [
        failure
        for failure in failures
        if failure["code"] in ("V_BUILD_PROVENANCE", "V_BINARY", "V_PROTOCOL")
    ]
    if hard:
        reject("V_BUILD_PROVENANCE", json.dumps(hard, sort_keys=True))
    identity = [
        failure for failure in failures if failure["code"] in ("V_AA_BINARY", "V_AB_BINARY")
    ]
    status = "MEASUREMENT_BLOCKED" if identity else "PASS"
    adapter_records = {}
    for arm in ("A", "B"):
        adapter = read_json(os.path.join(campaign_dir, "raw", "setup", f"adapter-{arm}.json"))
        if adapter.get("binary_sha256") != manifest["arms"][arm]["binary_sha256"]:
            reject("V_BINARY", f"adapter-{arm} digest differs")
        if adapter.get("binary_bytes") != manifest["arms"][arm]["binary_bytes"]:
            reject("V_BINARY", f"adapter-{arm} size differs")
        adapter_records[arm] = adapter
    live = {}
    for arm in ("A", "B"):
        binary = os.path.join(campaign_dir, "build", arm, "release", ADAPTER_BINARY)
        if os.path.isfile(binary) and not os.path.islink(binary):
            live[arm] = {
                "binary_sha256": sha256_file(binary),
                "binary_bytes": os.path.getsize(binary),
            }
            if live[arm]["binary_sha256"] != manifest["arms"][arm]["binary_sha256"]:
                reject("V_BINARY", f"live arm {arm} binary digest differs")
            if live[arm]["binary_bytes"] != manifest["arms"][arm]["binary_bytes"]:
                reject("V_BINARY", f"live arm {arm} binary size differs")
    return {
        "status": status,
        "identity_failures": identity,
        "live_binary_rehash": "PASS" if live else "UNAVAILABLE_ARCHIVE",
        "events": len(record.get("events", [])),
    }


def host_attestation_failures(record: dict, manifest: dict, protocol_sha: str) -> list[dict]:
    failures: list[dict] = []

    def fail(code: str, detail: str) -> None:
        failures.append({"code": code, "detail": detail})

    if not isinstance(record, dict):
        fail("V_HOST", "host attestation is not an object")
        return failures
    if record.get("schema") != SCHEMA_HOST_ATTESTATION:
        fail("V_HOST", "wrong host attestation schema")
    if record.get("protocol_sha256") != protocol_sha:
        fail("V_PROTOCOL", "host attestation protocol digest differs")
    for name in ("kernel", "machine", "cpu_model"):
        if not isinstance(record.get(name), str) or not record.get(name):
            fail("V_HOST", f"missing {name}")
    if _bool_int(record.get("cpu_count")) or record.get("cpu_count") <= 0:
        fail("V_HOST", "invalid cpu_count")
    shape_ok = True
    allowed = record.get("allowed_cpus_before_pin")
    controller = record.get("controller_cpu")
    adapter = record.get("adapter_cpu")
    if not isinstance(allowed, list) or len(allowed) < 2:
        fail("V_HOST", "allowed CPU set is invalid")
        shape_ok = False
    else:
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in allowed):
            fail("V_HOST", "allowed CPU set contains a non-integer, boolean or negative value")
            shape_ok = False
        elif list(allowed) != sorted(set(allowed)):
            fail("V_HOST", "allowed CPU set is not sorted and unique")
            shape_ok = False
    if _bool_int(controller) or _bool_int(adapter):
        fail("V_AFFINITY", "pinned CPUs are not integers")
        shape_ok = False
    elif controller == adapter:
        fail("V_AFFINITY", "controller and adapter CPUs are equal")
    elif isinstance(allowed, list) and (controller not in allowed or adapter not in allowed):
        fail("V_AFFINITY", "pinned CPUs are outside the allowed set")
    if record.get("controller_affinity_after_pin") != [controller]:
        fail("V_AFFINITY", "observed controller affinity does not match the requested CPU")
    filesystems = record.get("filesystems")
    required_roles = {
        "repository",
        "campaign_output",
        "compile_source",
        "target_A",
        "target_B",
        "corpus",
        "indexes",
    }
    roles = []
    if not isinstance(filesystems, list):
        fail("V_HOST", "filesystem evidence is not a list")
        shape_ok = False
    else:
        for item in filesystems:
            if not isinstance(item, dict) or not isinstance(item.get("role"), str):
                fail("V_HOST", "filesystem evidence record is malformed")
                shape_ok = False
                continue
            roles.append(item["role"])
        if len(roles) != len(set(roles)):
            fail("V_HOST", "filesystem evidence contains duplicate roles")
            shape_ok = False
        if set(roles) != required_roles:
            fail("V_HOST", "filesystem evidence roles differ")
            shape_ok = False
        for item in filesystems:
            if not isinstance(item, dict):
                continue
            if item.get("harness_fstype") != item.get("findmnt_fstype"):
                fail("V_HOST", f"{item.get('role')}: harness and findmnt disagree")
            if item.get("findmnt_fstype") not in ("ext4", "xfs", "btrfs"):
                fail("V_HOST", f"{item.get('role')}: non-native filesystem")
    if record.get("native_filesystem") is not True:
        fail("V_HOST", "native_filesystem is not true")
    if shape_ok:
        expected_fingerprint = host_fingerprint(record)
        if record.get("host_fingerprint") != expected_fingerprint:
            fail("V_HOST", "host fingerprint does not recompute")
    if manifest.get("environment_fingerprint") != record.get("host_fingerprint"):
        fail("V_HOST", "manifest environment fingerprint differs")
    if manifest.get("host_attestation_sha256") is None:
        fail("V_HOST", "manifest has no host attestation digest")
    return failures


def host_fingerprint(record: dict) -> str:
    filesystems = {
        item["role"]: item["findmnt_fstype"]
        for item in record.get("filesystems", [])
        if isinstance(item, dict) and "role" in item
    }
    selected = {
        "kernel": record.get("kernel"),
        "machine": record.get("machine"),
        "cpu_model": record.get("cpu_model"),
        "cpu_count": record.get("cpu_count"),
        "allowed_cpus": sorted(record.get("allowed_cpus_before_pin") or []),
        "controller_cpu": record.get("controller_cpu"),
        "adapter_cpu": record.get("adapter_cpu"),
        "filesystems": filesystems,
    }
    return sha256_bytes(canonical_json_bytes(selected))


def verify_host_attestation(campaign_dir: str, manifest: dict, protocol_sha: str) -> dict:
    full = os.path.join(campaign_dir, "raw", "host-attestation.json")
    record = read_json(full)
    if manifest.get("host_attestation_sha256") != sha256_file(full):
        reject("V_HOST", "host attestation digest differs from the manifest")
    failures = host_attestation_failures(record, manifest, protocol_sha)
    if failures:
        reject("V_HOST", json.dumps(failures, sort_keys=True))
    return {
        "status": "PASS",
        "controller_cpu": record["controller_cpu"],
        "adapter_cpu": record["adapter_cpu"],
        "record": record,
    }


def affinity_failures(slots: list[dict], controller_cpu: int, adapter_cpu: int) -> list[dict]:
    failures: list[dict] = []
    for slot in slots:
        number = slot.get("slot")
        if slot.get("controller_affinity_before") != [controller_cpu]:
            failures.append({"code": "V_AFFINITY", "detail": f"slot {number}: controller before differs"})
        if slot.get("controller_affinity_after") != [controller_cpu]:
            failures.append({"code": "V_AFFINITY", "detail": f"slot {number}: controller after differs"})
        for record in slot.get("lanes", []):
            label = f"slot {number}:{record.get('id')}"
            if _bool_int(record.get("adapter_pid")) or record.get("adapter_pid") <= 0:
                failures.append({"code": "V_AFFINITY", "detail": f"{label}: missing adapter pid"})
            if record.get("adapter_affinity_before") != [adapter_cpu]:
                failures.append({"code": "V_AFFINITY", "detail": f"{label}: pre-warmup affinity differs"})
            if record.get("adapter_affinity_after") != [adapter_cpu]:
                failures.append({"code": "V_AFFINITY", "detail": f"{label}: post-timed affinity differs"})
            if record.get("affinity_capture_stages") != ["pre_warmup", "post_timed_sample_20"]:
                failures.append({"code": "V_AFFINITY", "detail": f"{label}: capture stages differ"})
    return failures


def verify_binaries(manifest: dict) -> None:
    seen = set()
    for arm, entry in manifest["arms"].items():
        binary = entry.get("binary_sha256")
        if not isinstance(binary, str) or len(binary) != 64:
            reject("V_BINARY", f"arm {arm} has an invalid binary SHA")
        if isinstance(entry.get("binary_bytes"), bool) or not isinstance(entry.get("binary_bytes"), int) or entry["binary_bytes"] <= 0:
            reject("V_BINARY", f"arm {arm} has an invalid binary size")
        seen.add(binary)
    if manifest["kind"] == "control":
        if len(seen) not in (1, 2):
            reject("V_BINARY", "A/A control must have one or two recorded BASE builds")
    elif len(seen) != 2:
        reject("V_BINARY", f"paired campaign requires 2 distinct adapter binaries, found {len(seen)}")

def verify_indexes(campaign_dir: str, manifest: dict) -> None:
    builds = manifest.get("builds")
    if not isinstance(builds, dict):
        reject("V_INDEX", "manifest has no builds")
    expected_indices = 2 if manifest["kind"] == "control" else 4
    if len(builds.get("indices", [])) != expected_indices:
        reject("V_INDEX", f"expected {expected_indices} index builds")
    for entry in builds["indices"]:
        arm = entry["arm"]
        n = entry["n"]
        record = read_json(os.path.join(campaign_dir, "raw", "setup", f"index-{arm}-n{n}.json"))
        layout = record.get("layout") or {}
        files = layout.get("files")
        if not isinstance(files, list) or not files:
            reject("V_INDEX", f"{arm}/n{n}: layout has no files")
        ordered = sorted(files, key=lambda item: item["path"])
        committed = sum(item["size"] for item in ordered)
        if committed != layout.get("committed_index_bytes"):
            reject("V_INDEX", f"{arm}/n{n}: committed bytes differ")
        if sha256_bytes(canonical_json_bytes(ordered)) != layout.get("digest"):
            reject("V_INDEX", f"{arm}/n{n}: layout digest does not recompute")
        actual_dir = os.path.join(campaign_dir, "indexes", f"{arm}-n{n}")
        if os.path.isdir(actual_dir):
            for item in ordered:
                full = os.path.join(actual_dir, item["path"])
                if sha256_file(full) != item["sha256"]:
                    reject("V_INDEX", f"{arm}/n{n}: index file hash differs: {item['path']}")
        if n == 100000:
            if layout.get("committed_index_bytes") != PROTOCOL["100k_lz4_committed_index_sentinel"]:
                reject("V_INDEX", f"{arm}/n{n}: committed-byte sentinel differs")
            if layout.get("stored_bytes") != PROTOCOL["100k_lz4_stored_section_sentinel"]:
                reject("V_INDEX", f"{arm}/n{n}: STORED-section sentinel differs")
        arm_manifest = manifest["arms"][arm]
        if arm_manifest["index_digests"].get(str(n)) != layout.get("digest"):
            reject("V_INDEX", f"{arm}/n{n}: manifest index digest differs")
    digests = {tuple(sorted(entry["index_digests"].items())) for entry in manifest["arms"].values()}
    if len(digests) != 1:
        reject("V_INDEX", "arm index digests differ across arms")


def verify_corpus(campaign_dir: str, manifest: dict) -> dict:
    generate = _load_module("pr15d_generate_verify_d1", os.path.join(TOOLING_ROOT, "benchmarks/pr15d/corpus/generate.py"))
    oracle = _load_module("pr15d_oracle_verify_d1", os.path.join(TOOLING_ROOT, "benchmarks/pr15d/corpus/oracle.py"))
    directory = tempfile.mkdtemp(prefix="pr15i-d3-b-verify-")
    try:
        summary = generate.generate(directory)
        manifest_oracle, rows = oracle.load_and_verify(directory)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    if summary["manifest"]["sha256"] != CORPUS_MANIFEST_SHA256:
        reject("V_CORPUS", "regenerated corpus manifest differs from the frozen digest")
    if manifest["corpus"]["manifest_sha256"] != CORPUS_MANIFEST_SHA256:
        reject("V_CORPUS", "campaign corpus manifest differs from the frozen digest")
    expected = {}
    for query in manifest_oracle["queries"]:
        if query["id"] in LANE_IDS:
            expected[query["id"]] = {
                "total_hits": query["total_hits"],
                "doc_ids": query["doc_ids"],
                "n": query["n"],
                "class": query["class"],
                "field": query["field"],
                "term": query["term"],
                "k": query["k"],
            }
    if sorted(expected) != sorted(LANE_IDS):
        reject("V_CORPUS", "oracle does not cover exactly the nine frozen lanes")
    setup = read_json(os.path.join(campaign_dir, "raw", "setup", "corpus.json"))
    if setup.get("manifest_sha256") != CORPUS_MANIFEST_SHA256:
        reject("V_CORPUS", "setup corpus digest differs")
    for lane_id, value in expected.items():
        if setup.get("expected_total_hits", {}).get(lane_id) != value["total_hits"]:
            reject("V_CORPUS", f"{lane_id}: setup total_hits differs from oracle")
        if setup.get("expected_doc_ids", {}).get(lane_id) != value["doc_ids"]:
            reject("V_CORPUS", f"{lane_id}: setup doc ids differ from oracle")
        if manifest["expected_by_lane"].get(lane_id) != value["total_hits"]:
            reject("V_CORPUS", f"{lane_id}: manifest total_hits differs from oracle")
    return expected


def _load_module(name: str, path: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        reject("V_IMPORT", f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_slots(campaign_dir: str, manifest: dict, expected: dict) -> list[dict]:
    kind = manifest["kind"]
    plan = slot_plan(PROTOCOL, kind)
    slots = []
    for entry in plan:
        slot = read_json(os.path.join(campaign_dir, "raw", "slots", f"slot-{entry['slot']:02d}.json"))
        if slot.get("schema") != SCHEMA_SLOT:
            reject("V_SLOT", f"slot {entry['slot']}: wrong schema")
        if (slot.get("slot"), slot.get("block"), slot.get("position"), slot.get("arm")) != (
            entry["slot"],
            entry["block"],
            entry["position"],
            entry["arm"],
        ):
            reject("V_SLOT", f"slot {entry['slot']}: schedule address differs")
        if slot.get("contention_before", {}).get("state") != "clear" or slot.get("contention_before", {}).get("reason_codes") not in ([], None):
            reject("V_CONTENTION", f"slot {entry['slot']}: before probe is not clear")
        if slot.get("contention_after", {}).get("state") != "clear" or slot.get("contention_after", {}).get("reason_codes") not in ([], None):
            reject("V_CONTENTION", f"slot {entry['slot']}: after probe is not clear")
        arm = manifest["arms"][slot["arm"]]
        if slot.get("source_sha") != arm["source_sha"] or slot.get("binary_sha256") != arm["binary_sha256"]:
            reject("V_SLOT", f"slot {entry['slot']}: source/binary identity differs")
        if slot.get("index_digests") != {str(n): digest for n, digest in arm["index_digests"].items()}:
            reject("V_SLOT", f"slot {entry['slot']}: index identity differs")
        records = slot.get("lanes")
        if not isinstance(records, list) or len(records) != len(LANE_IDS):
            reject("V_SLOT", f"slot {entry['slot']}: lane count differs")
        for lane, record in zip(lane_descriptors(PROTOCOL), records, strict=True):
            oracle_entry = expected[lane["id"]]
            if record.get("id") != lane["id"]:
                reject("V_SLOT", f"slot {entry['slot']}: lane order differs")
            if record.get("total_hits") != oracle_entry["total_hits"]:
                reject("V_ORACLE", f"slot {entry['slot']}:{lane['id']}: total_hits differs")
            if record.get("doc_ids") != oracle_entry["doc_ids"]:
                reject("V_ORACLE", f"slot {entry['slot']}:{lane['id']}: doc ids differ")
            if record.get("expected_total_hits") != oracle_entry["total_hits"] or record.get("expected_doc_ids") != oracle_entry["doc_ids"]:
                reject("V_ORACLE", f"slot {entry['slot']}:{lane['id']}: expected fields differ")
            if record.get("oracle_ok") is not True:
                reject("V_ORACLE", f"slot {entry['slot']}:{lane['id']}: oracle_ok is not true")
            if record.get("regime") != "warm":
                reject("V_SLOT", f"slot {entry['slot']}:{lane['id']}: regime differs")
        slots.append(slot)
    if len(slots) != PROTOCOL["slots_per_campaign"]:
        reject("V_SLOT", "slot count differs")
    return slots


def recompute_summary(
    manifest: dict,
    slots: list[dict],
    lanes: list[dict],
    protocol_sha: str,
    structural: dict,
) -> dict:
    summary = {
        "schema": SCHEMA_SUMMARY,
        "campaign": manifest["campaign"],
        "kind": manifest["kind"],
        "comparison": manifest["comparison"],
        "base_source_sha": manifest["base_source_sha"],
        "candidate_source_sha": manifest["candidate_source_sha"],
        "protocol_sha256": protocol_sha,
        "tooling_sha": manifest["tooling_sha"],
        "tooling_manifest_sha256": manifest["tooling_manifest_sha256"],
        "controller_sha256": manifest["controller_sha256"],
        "verifier_sha256": manifest["verifier_sha256"],
        "corpus_manifest_sha256": manifest["corpus"]["manifest_sha256"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "slot_count": len(slots),
        "samples_per_lane_slot": PROTOCOL["samples_per_lane_slot"],
        "warmups_per_lane_slot": PROTOCOL["warmups_per_lane_slot"],
        "contention_probes": 2 * len(slots),
        "index_builds": len(manifest["builds"]["indices"]),
        "source_fingerprints": manifest["source_fingerprints"],
        "arms": {
            arm: {
                "source_sha": entry["source_sha"],
                "binary_sha256": entry["binary_sha256"],
                "index_digests": entry["index_digests"],
            }
            for arm, entry in manifest["arms"].items()
        },
    }
    drift = drift_violations(slots, lanes, PROTOCOL["blocks_per_campaign"])
    summary["drift"] = {"status": "PASS" if not drift else "FAIL", "violations": drift}
    summary["structural"] = dict(structural)
    structural_ok = not drift and all(
        structural.get(name) == "PASS"
        for name in ("build_provenance", "host_attestation", "affinity_observations", "host_readiness")
    )
    if manifest["kind"] == "control":
        qualification = compute_control(slots, lanes)
        summary["a_a"] = qualification
        summary["gates"] = {}
        if not structural_ok:
            summary["status"] = "MEASUREMENT_BLOCKED"
        elif qualification["passes"]:
            summary["status"] = "CONTROL_QUALIFIED"
        else:
            summary["status"] = "CONTROL_NUMERICAL_BLOCKED"
    else:
        metrics = compute_paired_metrics(slots, lanes)
        gates = compute_gates(manifest["comparison"], metrics)
        summary["lanes"] = list(metrics.values())
        summary["gates"] = gates
        summary["status"] = (
            "MEASUREMENT_BLOCKED"
            if not structural_ok
            else ("CAMPAIGN_QUALIFIED" if all(value == "PASS" for value in gates.values()) else "CAMPAIGN_REJECTED")
        )
    return summary


def verify_setup_protocol(manifest: dict, campaign_dir: str, protocol_sha: str) -> None:
    """Every source/setup record must carry the same frozen protocol digest."""
    records = [os.path.join(campaign_dir, "raw", "setup", "corpus.json")]
    for arm in manifest["builds"]["adapters"]:
        records.append(os.path.join(campaign_dir, "raw", "setup", f"adapter-{arm}.json"))
    for entry in manifest["builds"]["indices"]:
        records.append(
            os.path.join(campaign_dir, "raw", "setup", f"index-{entry['arm']}-n{entry['n']}.json")
        )
    for path in records:
        record = read_json(path)
        if record.get("protocol_sha256") != protocol_sha:
            reject("V_PROTOCOL", f"{os.path.basename(path)} protocol digest differs")


def verify_protocol_records(campaign_dir: str, manifest: dict, protocol_sha: str) -> None:
    """V04: the frozen protocol digest must appear in every identity record."""
    records = [
        "authorization.json",
        "manifest.json",
        "raw/build-provenance.json",
        "raw/host-attestation.json",
    ]
    for relative in records:
        record = read_json(os.path.join(campaign_dir, relative))
        if record.get("protocol_sha256") != protocol_sha:
            reject("V_PROTOCOL", f"{relative} protocol digest differs")
    if manifest.get("protocol_sha256") != protocol_sha:
        reject("V_PROTOCOL", "manifest protocol digest differs")


def eligible_control_name(protocol: dict, comparison: str, statuses: dict[str, str]) -> str:
    """FDX-42..47 succession rule over completed control attempts."""
    first = statuses.get("aa-01")
    retry = statuses.get("aa-02")
    if retry is not None:
        if first == "CONTROL_QUALIFIED":
            reject("V_CONTROL_HISTORY", "qualified control 01 together with control 02")
        if first != "CONTROL_NUMERICAL_BLOCKED":
            reject("V_CONTROL_HISTORY", f"control 02 is not authorized after {first}")
        if retry != "CONTROL_QUALIFIED":
            reject("V_CONTROL_HISTORY", f"control 02 is not qualified: {retry}")
        return f"{comparison}-aa-02"
    if first != "CONTROL_QUALIFIED":
        reject("V_CONTROL_HISTORY", f"control 01 is not qualified: {first}")
    return f"{comparison}-aa-01"


def verify_control_reference(manifest: dict, protocol_sha: str) -> None:
    comparison, kind = campaign_kind(manifest["campaign"], PROTOCOL)
    control = manifest.get("control")
    if not isinstance(control, dict):
        reject("V_CONTROL_HISTORY", "paired manifest has no control reference")
    name = control.get("campaign")
    allowed = {f"{comparison}-{suffix}" for suffix in PROTOCOL["control_suffixes"]}
    if name not in allowed:
        reject("V_CONTROL_HISTORY", f"unauthorized control campaign {name!r}")
    if control.get("status") != "CONTROL_QUALIFIED":
        reject("V_CONTROL_HISTORY", "referenced control is not qualified")
    if control.get("base_source_sha") != manifest["base_source_sha"]:
        reject("V_CONTROL_HISTORY", "referenced control source differs")
    predecessor = control.get("predecessor_status")
    if name.endswith("aa-02"):
        if predecessor != "CONTROL_NUMERICAL_BLOCKED":
            reject("V_CONTROL_HISTORY", "control 02 predecessor status is not a numerical failure")
    elif predecessor != "NONE":
        reject("V_CONTROL_HISTORY", "control 01 predecessor status is not NONE")
    for field in ("seal_sha256", "summary_sha256", "build_provenance_sha256", "host_attestation_sha256"):
        value = control.get(field)
        if not isinstance(value, str) or len(value) != 64:
            reject("V_CONTROL_HISTORY", f"control {field} is invalid")


ATTEMPT_QUALIFIED_PASSED = "QUALIFIED_PASSED"
ATTEMPT_QUALIFIED_REJECTED = "QUALIFIED_REJECTED"
ATTEMPT_DRIFT_ONLY_INVALID = "DRIFT_ONLY_INVALID"
ATTEMPT_INVALID_EVIDENCE = "INVALID_EVIDENCE"
ATTEMPT_STRUCTURAL_KEYS = (
    "build_provenance",
    "host_attestation",
    "affinity_observations",
    "host_readiness",
)
PERFORMANCE_GATES = ("D3B-P01", "D3B-P02", "D3B-P03", "D3B-P04", "D3B-P05", "D3B-P06")


def classify_attempt(report: dict, summary: dict) -> str:
    """Independent F1.2 classification of one completed paired campaign."""
    if not isinstance(report, dict) or report.get("verification") != "PASS":
        return ATTEMPT_INVALID_EVIDENCE
    if report.get("summary_match") is not True:
        return ATTEMPT_INVALID_EVIDENCE
    structural = summary.get("structural") or {}
    structural_ok = all(structural.get(name) == "PASS" for name in ATTEMPT_STRUCTURAL_KEYS)
    drift = summary.get("drift") or {}
    gates = summary.get("gates") or {}
    status = report.get("campaign_status")
    if status == "CAMPAIGN_QUALIFIED":
        if structural_ok and drift.get("status") == "PASS" and all(
            gates.get(gate) == "PASS" for gate in ("D3B-P00", "D3B-P07") + PERFORMANCE_GATES
        ):
            return ATTEMPT_QUALIFIED_PASSED
        return ATTEMPT_INVALID_EVIDENCE
    if status == "CAMPAIGN_REJECTED":
        if (
            structural_ok
            and drift.get("status") == "PASS"
            and gates.get("D3B-P00") == "PASS"
            and gates.get("D3B-P07") == "PASS"
            and any(gates.get(gate) == "FAIL" for gate in PERFORMANCE_GATES)
        ):
            return ATTEMPT_QUALIFIED_REJECTED
        return ATTEMPT_INVALID_EVIDENCE
    if status == "MEASUREMENT_BLOCKED":
        violations = drift.get("violations") or []
        if (
            structural_ok
            and drift.get("status") == "FAIL"
            and violations
            and all(
                isinstance(violation, dict)
                and violation.get("gate") in ("WITHIN_BLOCK_DRIFT", "BLOCK_DRIFT")
                for violation in violations
            )
        ):
            return ATTEMPT_DRIFT_ONLY_INVALID
    return ATTEMPT_INVALID_EVIDENCE


def succession_next(history: list[str]) -> dict:
    """Independent three-attempt state machine (mirrors the frozen table)."""
    def result(next_suffix, terminal, replacement):
        return {"next": next_suffix, "terminal": terminal, "replacement_used": replacement}

    if any(
        item not in (ATTEMPT_QUALIFIED_PASSED, ATTEMPT_QUALIFIED_REJECTED, ATTEMPT_DRIFT_ONLY_INVALID)
        for item in history
    ):
        return result(None, "BLOCKED", False)
    if len(history) > 3:
        return result(None, "BLOCKED", False)
    drift_count = history.count(ATTEMPT_DRIFT_ONLY_INVALID)
    pass_count = history.count(ATTEMPT_QUALIFIED_PASSED)
    if drift_count > 1:
        return result(None, "BLOCKED", True)
    if ATTEMPT_QUALIFIED_REJECTED in history:
        return result(None, "REJECTED", False)
    table = {
        (): result("01", None, False),
        (ATTEMPT_QUALIFIED_PASSED,): result("02", None, False),
        (ATTEMPT_DRIFT_ONLY_INVALID,): result("02", None, True),
        (ATTEMPT_QUALIFIED_PASSED, ATTEMPT_QUALIFIED_PASSED): result(None, "ACCEPTED", False),
        (ATTEMPT_QUALIFIED_PASSED, ATTEMPT_DRIFT_ONLY_INVALID): result("03", None, True),
        (ATTEMPT_DRIFT_ONLY_INVALID, ATTEMPT_QUALIFIED_PASSED): result("03", None, True),
        (ATTEMPT_DRIFT_ONLY_INVALID, ATTEMPT_DRIFT_ONLY_INVALID): result(None, "BLOCKED", True),
        (ATTEMPT_QUALIFIED_PASSED, ATTEMPT_DRIFT_ONLY_INVALID, ATTEMPT_QUALIFIED_PASSED): result(None, "ACCEPTED", True),
        (ATTEMPT_DRIFT_ONLY_INVALID, ATTEMPT_QUALIFIED_PASSED, ATTEMPT_QUALIFIED_PASSED): result(None, "ACCEPTED", True),
        (ATTEMPT_QUALIFIED_PASSED, ATTEMPT_DRIFT_ONLY_INVALID, ATTEMPT_DRIFT_ONLY_INVALID): result(None, "BLOCKED", True),
        (ATTEMPT_DRIFT_ONLY_INVALID, ATTEMPT_QUALIFIED_PASSED, ATTEMPT_DRIFT_ONLY_INVALID): result(None, "BLOCKED", True),
    }
    decision = table.get(tuple(history))
    if decision is None:
        return result(None, "BLOCKED", drift_count == 1)
    if decision["terminal"] == "ACCEPTED" and (pass_count != 2 or drift_count > 1):
        return result(None, "BLOCKED", drift_count == 1)
    return decision


def verify_succession(campaign_dir: str, manifest: dict, control: dict, protocol_sha: str) -> dict:
    """Validate the embedded predecessor chain; full history is checked by series."""
    full = os.path.join(campaign_dir, "raw", "attempt-succession.json")
    record = read_json(full)
    if manifest.get("attempt_succession_sha256") != sha256_file(full):
        reject("V_SUCCESSION", "succession digest differs from the manifest")
    if record.get("schema") != SCHEMA_ATTEMPT_SUCCESSION:
        reject("V_SUCCESSION", "wrong succession schema")
    if record.get("protocol_sha256") != protocol_sha:
        reject("V_PROTOCOL", "succession protocol digest differs")
    if record.get("campaign") != manifest.get("campaign"):
        reject("V_SUCCESSION", "succession campaign differs")
    comparison, kind = campaign_kind(manifest["campaign"], PROTOCOL)
    if kind != "paired":
        reject("V_SUCCESSION", "succession is only valid for paired campaigns")
    if record.get("comparison") != comparison:
        reject("V_SUCCESSION", "succession comparison differs")
    suffix = manifest["campaign"].rsplit("-", 1)[-1]
    index = PROTOCOL["campaign_suffixes"].index(suffix) + 1 if suffix in PROTOCOL["campaign_suffixes"] else 0
    if index == 0:
        reject("V_SUCCESSION", "unknown attempt suffix")
    if record.get("attempt_number") != index or manifest.get("attempt_number") != index:
        reject("V_SUCCESSION", "attempt number differs")
    if record.get("eligible_control") != (manifest.get("control") or {}).get("campaign"):
        reject("V_SUCCESSION", "succession control differs from the manifest control")
    if record.get("control_seal_sha256") != (manifest.get("control") or {}).get("seal_sha256"):
        reject("V_SUCCESSION", "succession control seal differs")
    if record.get("host_fingerprint") != manifest.get("environment_fingerprint"):
        reject("V_SUCCESSION", "succession host fingerprint differs")
    predecessors = record.get("predecessors")
    if not isinstance(predecessors, list) or len(predecessors) != index - 1:
        reject("V_SUCCESSION", "predecessor count differs")
    names = [entry.get("campaign") for entry in predecessors if isinstance(entry, dict)]
    expected_names = [f"{comparison}-{s}" for s in PROTOCOL["campaign_suffixes"][: index - 1]]
    if names != expected_names:
        reject("V_SUCCESSION", "predecessor names/order differ")
    classes = []
    for entry in predecessors:
        if not isinstance(entry, dict):
            reject("V_SUCCESSION", "predecessor record is malformed")
        if entry.get("attempt_class") not in (ATTEMPT_QUALIFIED_PASSED, ATTEMPT_DRIFT_ONLY_INVALID):
            reject("V_SUCCESSION", "predecessor class does not permit a successor")
        if entry.get("verification") != "PASS":
            reject("V_SUCCESSION", "predecessor verification is not PASS")
        if entry.get("source_sha_a") != manifest["base_source_sha"] or entry.get("source_sha_b") != manifest["candidate_source_sha"]:
            reject("V_SUCCESSION", "predecessor source identities differ")
        for field in ("seal_sha256", "summary_sha256", "readiness_sha256", "independent_verifier_sha256"):
            value = entry.get(field)
            if not isinstance(value, str) or len(value) != 64:
                reject("V_SUCCESSION", f"predecessor {field} is invalid")
        classes.append(entry["attempt_class"])
    decision = succession_next(classes)
    if decision["terminal"] is not None or decision["next"] != suffix:
        reject("V_SUCCESSION", "embedded succession does not authorize this attempt")
    return {
        "predecessors": predecessors,
        "attempt_class_history": classes,
        "validation_scope": "EMBEDDED_ONLY",
    }


def verify_campaign_dir(path: str) -> dict:
    protocol, protocol_sha = load_protocol()
    campaign_dir = confined_campaign(path)
    manifest = read_json(os.path.join(campaign_dir, "manifest.json"))
    if manifest.get("schema") != SCHEMA_MANIFEST:
        reject("V_MANIFEST", "unknown manifest schema")
    authorization = read_json(os.path.join(campaign_dir, "authorization.json"))
    if authorization.get("schema") != SCHEMA_AUTHORIZATION or authorization.get("idle_confirmed") is not True:
        reject("V_AUTH", "authorization is missing or not idle-confirmed")
    campaign = manifest.get("campaign")
    comparison, kind = campaign_kind(campaign, protocol)
    for field, expected in (
        ("campaign", campaign),
        ("kind", kind),
        ("comparison", comparison),
        ("base_source_sha", manifest["base_source_sha"]),
        ("candidate_source_sha", manifest["candidate_source_sha"]),
    ):
        if authorization.get(field) != expected:
            reject("V_AUTH", f"authorization {field} differs")
    seal = verify_seal(campaign_dir)
    if seal.get("kind") != kind:
        reject("V_SEAL", "seal kind differs from campaign kind")
    inventory = verify_inventory(campaign_dir, seal)
    verify_sources(manifest, protocol_sha)
    verify_setup_protocol(manifest, campaign_dir, protocol_sha)
    verify_protocol_records(campaign_dir, manifest, protocol_sha)
    verify_binaries(manifest)
    build_report = verify_build_provenance(campaign_dir, manifest, protocol_sha)
    host_report = verify_host_attestation(campaign_dir, manifest, protocol_sha)
    readiness_report = verify_host_readiness(campaign_dir, manifest, host_report["record"], protocol_sha)
    succession_report = None
    if kind == "paired":
        verify_control_reference(manifest, protocol_sha)
    verify_indexes(campaign_dir, manifest)
    expected = verify_corpus(campaign_dir, manifest)
    lanes = lane_descriptors(protocol)
    slots = verify_slots(campaign_dir, manifest, expected)
    affinity = affinity_failures(slots, host_report["controller_cpu"], host_report["adapter_cpu"])
    if affinity:
        reject("V_AFFINITY", json.dumps(affinity, sort_keys=True))
    structural = {
        "build_provenance": build_report["status"],
        "host_attestation": host_report["status"],
        "affinity_observations": "PASS",
        "host_readiness": readiness_report["status"],
    }
    expected_setup = {f"raw/setup/index-{entry['arm']}-n{entry['n']}.json" for entry in manifest["builds"]["indices"]}
    expected_adapters = {f"raw/setup/adapter-{arm}.json" for arm in manifest["builds"]["adapters"]}
    for relative in sorted(expected_setup | expected_adapters | {"raw/setup/corpus.json"}):
        if relative not in seal["files"]:
            reject("V_SEAL", f"missing setup member {relative}")
    for index in range(1, PROTOCOL["slots_per_campaign"] + 1):
        for relative in (
            f"raw/slots/slot-{index:02d}.json",
            f"raw/contention/slot-{index:02d}-before.json",
            f"raw/contention/slot-{index:02d}-after.json",
        ):
            if relative not in seal["files"]:
                reject("V_SEAL", f"missing required member {relative}")
    recomputed = recompute_summary(manifest, slots, lanes, protocol_sha, structural)
    attempt_class = None
    if kind == "paired":
        succession_report = verify_succession(
            campaign_dir, manifest, manifest.get("control") or {}, protocol_sha
        )
        attempt_class = classify_attempt(
            {"verification": "PASS", "summary_match": True, "campaign_status": recomputed["status"]},
            recomputed,
        )
        if attempt_class == ATTEMPT_INVALID_EVIDENCE:
            reject("V_SUCCESSION", "campaign does not classify as a valid F1.2 attempt")
    raw = open(os.path.join(campaign_dir, "sanitized", "summary.json"), "rb").read()
    try:
        controller_summary = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        reject("V_SUMMARY", f"cannot parse controller summary: {error}")
    if canonical_json_bytes(controller_summary) != canonical_json_bytes(recomputed):
        reject("V_SUMMARY", "controller summary does not match the independent recomputation")
    return {
        "schema": SCHEMA_VERIFICATION,
        "campaign": campaign,
        "kind": kind,
        "comparison": comparison,
        "verification": "PASS",
        "reasons": [],
        "campaign_status": recomputed["status"],
        "member_count": inventory["member_count"],
        "summary_match": True,
        "gates": recomputed.get("gates", {}),
        "a_a_passes": recomputed.get("a_a", {}).get("passes"),
        "slots": len(slots),
        "structural": structural,
        "live_binary_rehash": build_report["live_binary_rehash"],
        "attempt_class": attempt_class,
        "succession_validation_scope": succession_report["validation_scope"] if succession_report else None,
    }


def aggregate_statuses(statuses: list[str]) -> str:
    """D3B-P08: both campaigns must qualify independently; never pool."""
    if any(status == "MEASUREMENT_BLOCKED" for status in statuses):
        return "MEASUREMENT_BLOCKED"
    if all(status == "CAMPAIGN_QUALIFIED" for status in statuses):
        return "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY"
    return "COMPARISON_PERFORMANCE_REJECTED"


def aggregate_series(series_root: str, comparison: str) -> dict:
    """Full-series F1.2 verification of the frozen three-attempt state machine."""
    protocol, protocol_sha = load_protocol()
    if comparison not in protocol["comparisons"]:
        reject("V_COMPARISON", f"unknown comparison {comparison!r}")
    if not os.path.isabs(series_root) or os.path.islink(series_root):
        reject("V_PATH", "--series-root must be an absolute non-symlinked path")
    root = os.path.realpath(series_root)
    if not os.path.isdir(root):
        reject("V_PATH", f"--series-root is not a directory: {series_root}")

    control_statuses = {}
    for suffix in protocol["control_suffixes"]:
        directory = os.path.join(root, f"{comparison}-{suffix}")
        if os.path.isdir(directory):
            control_statuses[suffix] = verify_campaign_dir(directory)["campaign_status"]
    eligible_control = eligible_control_name(protocol, comparison, control_statuses)

    attempts = []
    for suffix in protocol["campaign_suffixes"]:
        directory = os.path.join(root, f"{comparison}-{suffix}")
        if not os.path.isdir(directory):
            continue
        if len(attempts) != protocol["campaign_suffixes"].index(suffix):
            reject("V_SERIES", "attempt sequence contains a gap")
        attempts.append((suffix, directory))
    if not attempts:
        reject("V_SERIES", f"required campaign is missing: {comparison}-01")
    if len(attempts) > protocol["paired_structural_replacement"]["maximum_paired_attempts"]:
        reject("V_SERIES", "too many paired attempts")

    reports = [verify_campaign_dir(directory) for _suffix, directory in attempts]
    summaries = [
        read_json(os.path.join(directory, "sanitized", "summary.json"))
        for _suffix, directory in attempts
    ]
    classes = [classify_attempt(report, summary) for report, summary in zip(reports, summaries, strict=True)]
    for index, attempt_class in enumerate(classes):
        if attempt_class == ATTEMPT_INVALID_EVIDENCE:
            reject("V_SERIES", f"attempt {attempts[index][0]} is invalid evidence")
        decision = succession_next(classes[:index])
        if decision["terminal"] is not None or decision["next"] != attempts[index][0]:
            reject("V_SERIES", f"attempt {attempts[index][0]} is out of chronological order")
    for report, attempt_class in zip(reports, classes, strict=True):
        if report.get("attempt_class") != attempt_class:
            reject("V_SUCCESSION", "campaign attempt class differs from the series recomputation")
        manifest = read_json(os.path.join(root, report["campaign"], "manifest.json"))
        if manifest.get("control", {}).get("campaign") != eligible_control:
            reject("V_CONTROL_HISTORY", "paired campaign does not reference the eligible control")

    # Reopen and crosscheck every embedded predecessor chain against actual bytes.
    for index in range(1, len(attempts)):
        _suffix, directory = attempts[index]
        record = read_json(os.path.join(directory, "raw", "attempt-succession.json"))
        predecessors = record.get("predecessors") or []
        if len(predecessors) != index:
            reject("V_SUCCESSION", "predecessor chain length differs")
        for prior_index, entry in enumerate(predecessors):
            prior_directory = attempts[prior_index][1]
            prior_report = reports[prior_index]
            prior_summary = summaries[prior_index]
            if entry.get("campaign") != prior_report["campaign"]:
                reject("V_SUCCESSION", "predecessor campaign name differs")
            if entry.get("attempt_class") != classes[prior_index]:
                reject("V_SUCCESSION", "predecessor attempt class differs")
            if entry.get("verification") != "PASS":
                reject("V_SUCCESSION", "predecessor verification is not PASS")
            if entry.get("source_sha_a") != prior_summary["base_source_sha"] or entry.get("source_sha_b") != prior_summary["candidate_source_sha"]:
                reject("V_SUCCESSION", "predecessor source identities differ")
            expected = {
                "seal_sha256": sha256_file(os.path.join(prior_directory, "raw", "seal.json")),
                "summary_sha256": sha256_file(os.path.join(prior_directory, "sanitized", "summary.json")),
                "readiness_sha256": sha256_file(os.path.join(prior_directory, "raw", "host-readiness.json")),
                "independent_verifier_sha256": sha256_bytes(canonical_json_bytes(prior_report)),
            }
            for field, value in expected.items():
                if entry.get(field) != value:
                    reject("V_SUCCESSION", f"predecessor {field} differs from actual evidence")
            if entry.get("host_fingerprint") not in (None, prior_summary.get("environment_fingerprint")):
                reject("V_SUCCESSION", "predecessor host fingerprint differs")

    # Every completed attempt must have an exclusive archive and matching sidecar.
    evidence_root = os.path.join(
        os.path.expanduser("~"), ".local", "share", "quervant", protocol["evidence_root_relative"]
    )
    archives = {}
    for report in reports:
        campaign = report["campaign"]
        archive = os.path.join(evidence_root, f"{campaign}.tar.gz")
        sidecar = archive + ".sha256"
        if not os.path.exists(archive) and not os.path.exists(sidecar):
            archives[campaign] = None
            continue
        if not os.path.isfile(archive) or not os.path.isfile(sidecar):
            reject("V_ARCHIVE", f"incomplete archive or sidecar for {campaign}")
        side = read_json(sidecar)
        digest = sha256_file(archive)
        if side.get("archive_sha256") != digest:
            reject("V_ARCHIVE", f"archive sidecar mismatch for {campaign}")
        archives[campaign] = digest

    decision = succession_next(classes)
    if decision["terminal"] == "ACCEPTED":
        verdict = "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY"
    elif decision["terminal"] == "REJECTED":
        verdict = "COMPARISON_PERFORMANCE_REJECTED"
    elif decision["terminal"] == "BLOCKED":
        verdict = "MEASUREMENT_BLOCKED"
    else:
        verdict = "COMPARISON_INCOMPLETE"
    qualified = [report["campaign"] for report, cls in zip(reports, classes, strict=True) if cls == ATTEMPT_QUALIFIED_PASSED]
    excluded = [report["campaign"] for report, cls in zip(reports, classes, strict=True) if cls == ATTEMPT_DRIFT_ONLY_INVALID]
    gates = {}
    for report in reports:
        for gate, result in report.get("gates", {}).items():
            gates.setdefault(gate, []).append(result)
    return {
        "schema": "pr15i-d3bf12-comparison-v1",
        "comparison": comparison,
        "eligible_control": eligible_control,
        "control_statuses": control_statuses,
        "campaigns": [report["campaign"] for report in reports],
        "campaign_statuses": [report["campaign_status"] for report in reports],
        "attempt_classes": classes,
        "qualified_campaigns": qualified,
        "excluded_attempts": excluded,
        "structural_replacements_used": len(excluded),
        "verification": "PASS",
        "gates": gates,
        "verdict": verdict,
        "d3b_p08": "PASS" if verdict == "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY" else "FAIL",
        "succession_validation_scope": "FULL_SERIES",
        "archives": archives,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir")
    parser.add_argument("--series-root")
    parser.add_argument("--comparison")
    args = parser.parse_args(argv)
    try:
        if args.campaign_dir and args.series_root is None:
            report = verify_campaign_dir(args.campaign_dir)
        elif args.series_root and args.comparison and args.campaign_dir is None:
            report = aggregate_series(args.series_root, args.comparison)
        else:
            parser.error("provide exactly --campaign-dir or --series-root with --comparison")
        print(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0
    except VerifyError as error:
        print(
            json.dumps(
                {
                    "schema": SCHEMA_VERIFICATION,
                    "verification": "FAIL",
                    "reasons": [{"code": error.code, "detail": error.detail}],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

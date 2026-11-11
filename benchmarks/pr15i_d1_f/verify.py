#!/usr/bin/env python3
"""Independent verifier for PR 15I-D1-F sealed campaigns.

This module deliberately duplicates the controller's frozen protocol literals,
schedule parsing, statistics and gate arithmetic. It never imports ``run.py``
and never calls a controller verdict function: every median, block mean, drift
ratio, A/A ratio and gate result is recomputed from the sealed raw samples.

Usage::

    python3 benchmarks/pr15i_d1_f/verify.py --campaign-dir <sealed campaign>
    python3 benchmarks/pr15i_d1_f/verify.py --series-root <dir> --comparison c1-base

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
    return os.path.join(git_common_root(), "target", "pr15i-d1-f")


def load_protocol() -> tuple[dict, str]:
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d1_f/protocol_v1.json")
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
        if name == f"{comparison}-{protocol['control_suffix']}":
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
    table = {"FC2-P00": "PASS", "FC2-P06": "PASS"}
    for gate_id in COMPARISONS[comparison]["gates"]:
        spec = GATES[gate_id]
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
        else:
            reject("V_GATE", f"unknown gate kind {spec['kind']!r}")
        table[gate_id] = "PASS" if passes else "FAIL"
    return table

def compute_control(slots: list[dict], lanes: list[dict]) -> dict:
    blocks = PROTOCOL["blocks_per_campaign"]
    arm_a = block_arm_medians(slots, lanes, "A", blocks)
    arm_b = block_arm_medians(slots, lanes, "B", blocks)
    spec = PROTOCOL["a_a"]
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
        blocks_ok = all(spec["ratio_low"] <= value <= spec["ratio_high"] for value in block_ratios)
        lane_ok = blocks_ok and spec["median_low"] <= median_ratio <= spec["median_high"]
        failed = failed or not lane_ok
        lanes_report[lane["id"]] = {
            "blocks": detail,
            "median_ratio": median_ratio,
            "blocks_ok": blocks_ok,
            "passes": lane_ok,
        }
    return {"passes": not failed, "lanes": lanes_report, "bounds": spec}

def verify_seal(campaign_dir: str) -> dict:
    seal = read_json(os.path.join(campaign_dir, "raw", "seal.json"))
    if seal.get("schema") != "pr15i-d1-f-seal-v1" or seal.get("kind") not in ("paired", "control"):
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


def verify_inventory(campaign_dir: str, seal: dict) -> dict:
    """Every evidence file must be sealed; only the verification receipt is extra."""
    sealed = set(seal["files"])
    for root, dirs, names in os.walk(campaign_dir):
        relative_root = os.path.relpath(root, campaign_dir).replace(os.sep, "/")
        if relative_root == ".":
            relative_root = ""
        dirs[:] = [name for name in sorted(dirs) if f"{relative_root}/{name}".lstrip("/") not in ("build", "indexes", "corpus")]
        for name in sorted(names):
            relative = f"{relative_root}/{name}".lstrip("/")
            if relative == "raw/seal.json" or relative == "verification.json":
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
        ("benchmarks/pr15i_d1_f/run.py", "controller_sha256"),
        ("benchmarks/pr15i_d1_f/verify.py", "verifier_sha256"),
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
            reject("V_SOURCE", "C2 candidate does not descend from BASE")
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
            reject("V_SOURCE", f"forbidden changed path outside the F2 allowlist: {normalized}")
        reject("V_SOURCE", f"unexpected changed path outside the F2 allowlist: {normalized}")
    if kind == "paired":
        for relative in PROTECTED_SOURCES:
            source = subprocess.run(
                ["git", "-C", TOOLING_ROOT, "show", f"{manifest['candidate_source_sha']}:{relative}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if source.returncode != 0:
                reject("V_SOURCE", f"cannot read {relative} at candidate SHA")
            text_source = source.stdout.decode("utf-8", "replace")
            for symbol in PROTOCOL["c1_forbidden_symbols"]:
                if symbol in text_source:
                    reject("V_SOURCE", f"rejected C1 symbol {symbol!r} present in {relative}")

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
        mismatch = manifest.get("control_binary_mismatch")
        if len(seen) == 2 and not isinstance(mismatch, dict):
            reject("V_BINARY", "A/A binary discrepancy is not disclosed")
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
    directory = tempfile.mkdtemp(prefix="pr15i-d1-f-verify-")
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
        if slot.get("schema") != "pr15i-d1-f-slot-v1":
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
) -> dict:
    summary = {
        "schema": "pr15i-d1-f-summary-v1",
        "campaign": manifest["campaign"],
        "kind": manifest["kind"],
        "comparison": manifest["comparison"],
        "base_source_sha": manifest["base_source_sha"],
        "candidate_source_sha": manifest["candidate_source_sha"],
        "protocol_sha256": protocol_sha,
        "tooling_sha": manifest["tooling_sha"],
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
    structural_ok = not drift
    if manifest["kind"] == "control":
        qualification = compute_control(slots, lanes)
        summary["a_a"] = qualification
        summary["gates"] = {}
        summary["status"] = "CONTROL_QUALIFIED" if structural_ok and qualification["passes"] else "MEASUREMENT_BLOCKED"
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


def verify_campaign_dir(path: str) -> dict:
    protocol, protocol_sha = load_protocol()
    campaign_dir = confined_campaign(path)
    manifest = read_json(os.path.join(campaign_dir, "manifest.json"))
    if manifest.get("schema") != "pr15i-d1-f-manifest-v1":
        reject("V_MANIFEST", "unknown manifest schema")
    authorization = read_json(os.path.join(campaign_dir, "authorization.json"))
    if authorization.get("schema") != "pr15i-d1-f-authorization-v1" or authorization.get("idle_confirmed") is not True:
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
    verify_binaries(manifest)
    verify_indexes(campaign_dir, manifest)
    expected = verify_corpus(campaign_dir, manifest)
    lanes = lane_descriptors(protocol)
    slots = verify_slots(campaign_dir, manifest, expected)
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
    recomputed = recompute_summary(manifest, slots, lanes, protocol_sha)
    raw = open(os.path.join(campaign_dir, "sanitized", "summary.json"), "rb").read()
    try:
        controller_summary = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        reject("V_SUMMARY", f"cannot parse controller summary: {error}")
    if canonical_json_bytes(controller_summary) != canonical_json_bytes(recomputed):
        reject("V_SUMMARY", "controller summary does not match the independent recomputation")
    return {
        "schema": "pr15i-d1-f-verification-v1",
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
    }


def aggregate_statuses(statuses: list[str]) -> str:
    """FC2-P07: both campaigns must qualify; never pool across campaigns."""
    if any(status == "MEASUREMENT_BLOCKED" for status in statuses):
        return "MEASUREMENT_BLOCKED"
    if all(status == "CAMPAIGN_QUALIFIED" for status in statuses):
        return "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY"
    return "COMPARISON_PERFORMANCE_REJECTED"


def aggregate_series(series_root: str, comparison: str) -> dict:
    protocol, _protocol_sha = load_protocol()
    if comparison not in protocol["comparisons"]:
        reject("V_COMPARISON", f"unknown comparison {comparison!r}")
    root = os.path.abspath(series_root)
    reports = []
    for suffix in protocol["campaign_suffixes"]:
        directory = os.path.join(root, f"{comparison}-{suffix}")
        reports.append(verify_campaign_dir(directory))
    statuses = [report["campaign_status"] for report in reports]
    gates = {}
    for report in reports:
        for gate, result in report.get("gates", {}).items():
            gates.setdefault(gate, []).append(result)
    verdict = aggregate_statuses(statuses)
    return {
        "schema": "pr15i-d1-f-comparison-v1",
        "comparison": comparison,
        "campaigns": [report["campaign"] for report in reports],
        "campaign_statuses": statuses,
        "verification": "PASS",
        "gates": gates,
        "verdict": verdict,
        "fc2_p07": "PASS" if verdict == "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY" else "FAIL",
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
                    "schema": "pr15i-d1-f-verification-v1",
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

#!/usr/bin/env python3
"""PR 15I-D2-A source-locked A/Q/P attribution controller.

Measurement/diagnostics tooling only.  It never changes production source.  The
accepted source is a pristine `BASE` checkout; the diagnostic derivative is a
disposable scratch worktree produced by `patch_source.py` and proven
by `source_proof.py`.

Arms:

* ``A`` -- original uninstrumented adapter (``op=query``).
* ``Q`` -- the *same executable as P*, recorder inactive (``op=query``).
* ``P`` -- recorder active (``op=query_probe``); stage data collected outside
  ``engine_ns``.

The controller is responsible for input validation, index construction, the
frozen 24-slot schedule, exclusive evidence writes and sealing.  It derives
ratios for its own ``timing.json`` but the independent verifier recomputes them.
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
import time

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET_ROOT = os.path.join(TOOLING_ROOT, "target", "pr15i-d3a")

BASE_SHA = "409fb0fdf370bb4d4dade5ea507c6fa4518b5220"
FEATURE = "pr15id3a-probe"
PROTOCOL_SCHEMA = "pr15i-d3a-scoring-attribution-v1"

UNIFIED = "crates/quervant-core/src/search/unified.rs"
EXECUTE = "crates/quervant-core/src/search/execute.rs"
SEARCH_MOD = "crates/quervant-core/src/search/mod.rs"
D3A_PROBE = "crates/quervant-core/src/search/d3a_probe.rs"
CORE_CARGO = "crates/quervant-core/Cargo.toml"
ADAPTER = "benchmarks/pr15d/adapters/quervant/src/main.rs"
DERIVATIVE_FILES = (UNIFIED, EXECUTE, SEARCH_MOD, D3A_PROBE, CORE_CARGO, ADAPTER)
EXISTING_FILES = (UNIFIED, EXECUTE, SEARCH_MOD, CORE_CARGO, ADAPTER)

ADAPTER_MANIFEST = "benchmarks/pr15d/adapters/quervant/Cargo.toml"
ADAPTER_BINARY_NAME = "pr15d-quervant-adapter"

CLASS_TERMS = {
    "absent": ("key", "never"),
    "rare": ("key", "singleton"),
    "medium": ("group", "medium"),
    "common": ("key", "common"),
}

STAGE_LABELS = [
    "plan_ns",
    "reader_live_ns",
    "expand_ns",
    "stats_ns",
    "evaluate_ns",
    "candidate_ns",
    "projection_ns",
    "leaf_decode_ns",
    "membership_ns",
    "score_vector_ns",
    "score_map_ns",
    "score_owner_ns",
    "score_accumulate_ns",
    "matched_reserve_ns",
    "scored_vec_build_ns",
    "temp_release_ns",
    "match_insert_sample_ns",
    "candidate_sample_ns",
    "candidate_key_ns",
    "candidate_sort_view_ns",
    "candidate_sort_charge_ns",
    "candidate_duplicate_ns",
    "candidate_compare_ns",
    "candidate_materialize_ns",
    "candidate_heap_ns",
]
COUNTER_LABELS = [
    "matched_docs",
    "scored_docs",
    "candidate_docs",
    "bm25_calls",
    "scoring_map_entries",
    "positive_term_owners",
    "candidate_samples_first",
    "candidate_samples_steady",
    "candidate_samples_fast",
    "candidate_samples_fallback",
    "candidate_samples_insert",
    "candidate_samples_replace",
    "candidate_samples_reject",
    "match_insert_samples",
    "candidate_samples_key",
]

EXPECTED_PROTOCOL = {
    "schema": "pr15i-d3a-candidate-attribution-v1",
    "study_type": "CANDIDATE_INTERMEDIATE_ATTRIBUTION",
    "diagnostic_only": True,
    "base_sha": BASE_SHA,
    "corpus_manifest_sha256": "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151",
    "source_derivation": "DIAGNOSTIC_INSERTION_ONLY_FROM_BASE",
    "arms": ["A", "Q", "P"],
    "arm_operations": {"A": "query", "Q": "query", "P": "query_probe"},
    "q_and_p_exact_same_binary": True,
    "campaigns": ["d3a-unbatched-01", "d3a-unbatched-02"],
    "control_campaign": "d3a-base-aa-01",
    "arm_order_by_block": ["AQPPQA", "PQAAQP", "QAPPAQ", "PAQQAP"],
    "control_arm_order_by_block": [
        "A1A2A2A1", "A2A1A1A2", "A1A2A2A1", "A2A1A1A2",
    ],
    "blocks_per_campaign": 4,
    "slots_per_block": 6,
    "slots_per_campaign": 24,
    "control_blocks": 4,
    "control_slots_per_block": 4,
    "control_slots_per_campaign": 16,
    "arm_slots_per_block": 2,
    "control_arm_slots_per_block": 2,
    "warmups_per_lane_slot": 5,
    "samples_per_lane_slot": 20,
    "timed_sample_unit": "single_query_engine_ns",
    "adapter_process_lifetime": "ONE_PROCESS_PER_ARM_LANE_SLOT",
    "required_native_filesystem": ["ext4", "xfs", "btrfs"],
    "required_affinity": "CONTROLLER_SECOND_ALLOWED_CPU_ADAPTER_FIRST_ALLOWED_CPU",
    "contention_probes_per_slot": 2,
    "index_builds_per_control_campaign": 2,
    "index_builds_per_paired_campaign": 4,
    "100k_lz4_committed_index_sentinel": 15747551,
    "100k_lz4_stored_section_sentinel": 1661455,
    "lane_ids": [
        "pr15d_v1/10000/absent/k100",
        "pr15d_v1/10000/rare/k100",
        "pr15d_v1/10000/medium/k100",
        "pr15d_v1/10000/common/k100",
        "pr15d_v1/100000/absent/k100",
        "pr15d_v1/100000/rare/k100",
        "pr15d_v1/100000/medium/k100",
        "pr15d_v1/100000/common/k100",
        "pr15d_v1/100000/common/k10",
    ],
    "stages": [
        "plan_ns",
        "reader_live_ns",
        "expand_ns",
        "stats_ns",
        "evaluate_ns",
        "candidate_ns",
        "projection_ns",
        "leaf_decode_ns",
        "membership_ns",
        "score_vector_ns",
        "score_map_ns",
        "score_owner_ns",
        "score_accumulate_ns",
        "matched_reserve_ns",
        "scored_vec_build_ns",
        "temp_release_ns",
        "match_insert_sample_ns",
        "candidate_sample_ns",
        "candidate_key_ns",
        "candidate_sort_view_ns",
        "candidate_sort_charge_ns",
        "candidate_duplicate_ns",
        "candidate_compare_ns",
        "candidate_materialize_ns",
        "candidate_heap_ns",
    ],
    "counters": [
        "matched_docs",
        "scored_docs",
        "candidate_docs",
        "bm25_calls",
        "scoring_map_entries",
        "positive_term_owners",
        "candidate_samples_first",
        "candidate_samples_steady",
        "candidate_samples_fast",
        "candidate_samples_fallback",
        "candidate_samples_insert",
        "candidate_samples_replace",
        "candidate_samples_reject",
        "match_insert_samples",
        "candidate_samples_key",
    ],
    "candidate_sample_min_n": 512,
    "candidate_first_samples": 128,
    "candidate_steady_stride": 64,
    "match_insert_min_n": 128,
    "match_insert_stride": 64,
    "max_segment_descriptors": 32,
    "sample_strata_count": 2,
    "sample_strata_children": 8,
    "candidate_sample_children": 7,
    "candidate_priority": {
        "lanes": [
            "pr15d_v1/100000/medium/k100",
            "pr15d_v1/100000/common/k100",
            "pr15d_v1/100000/common/k10",
        ],
        "required_qualifying_lanes_per_campaign": 2,
        "required_campaigns": 2,
        "candidate_min_ns": 3000000,
        "candidate_min_share": 0.12,
        "dominant_min_steady_share": 0.25,
        "dominant_runner_up_ratio": 1.25,
        "dominant_max_residual_share": 0.30,
    },
    "intermediate_priority": {
        "lanes": [
            "pr15d_v1/100000/medium/k100",
            "pr15d_v1/100000/common/k100",
            "pr15d_v1/100000/common/k10",
        ],
        "min_disjoint_ns": 3000000,
        "min_disjoint_share": 0.10,
        "required_qualifying_lanes_per_campaign": 2,
        "required_campaigns": 2,
    },
    "a_a_drift_median_min": 0.85,
    "a_a_drift_median_max": 1.15,
    "a_a_outlier_block_low": 0.80,
    "a_a_outlier_block_high": 1.25,
    "a_a_max_outlier_blocks_per_lane": 1,
    "a_a_outlier_hard_low": 0.67,
    "a_a_outlier_hard_high": 1.50,
    "q_a_ratio_ceiling_low_match": 1.15,
    "q_a_ratio_ceiling_medium_common": 1.10,
    "p_q_ratio_ceiling_low_match": 1.25,
    "p_q_ratio_ceiling_medium_common": 1.15,
    "single_block_guard_ceiling": 1.50,
    "stage_partition_overhead_abs_ns": 10000,
    "stage_partition_overhead_share": 0.02,
    "candidate_sample_partition_overhead_share": 0.05,
    "stage_partition_max_violation_fraction": 0.01,
    "archive_root_relative": "benchmark-evidence/pr15i-d3a",
    "archive_excludes": ["build/", "indexes/", "corpus/", "sources/"],
}

SOURCE_ARTIFACTS = [
    "Cargo.lock",
    "Cargo.toml",
    "crates/quervant-core/Cargo.toml",
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/score.rs",
    "crates/quervant-core/src/search/mod.rs",
    "crates/quervant-core/src/segment/reader.rs",
    "benchmarks/pr15d/adapters/quervant/Cargo.toml",
    "benchmarks/pr15d/adapters/quervant/Cargo.lock",
    "benchmarks/pr15d/adapters/tantivy/Cargo.toml",
    "benchmarks/pr15d/adapters/tantivy/Cargo.lock",
    "benchmarks/pr15d/adapters/lucene/build.gradle",
    "benchmarks/pr15d/adapters/lucene/A1-CHECKSUMS.sha256",
    "benchmarks/pr15d/spec/pr15d_v1.json",
    "benchmarks/pr15d/corpus/generate.py",
    "benchmarks/pr15d/corpus/oracle.py",
    "benchmarks/pr15d/harness/run.py",
    "benchmarks/pr15d/harness/validate.py",
    "benchmarks/pr15d/harness/aggregate.py",
    "benchmarks/pr15i_d3a/protocol_v1.json",
    "benchmarks/pr15i_d3a/patch_source.py",
    "benchmarks/pr15i_d3a/source_proof.py",
    "benchmarks/pr15i_d3a/run.py",
    "benchmarks/pr15i_d3a/verify.py",
]


class D3AError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class D3ABlocked(D3AError):
    pass


class D3AInvalid(D3AError):
    pass


# ---------------------------------------------------------------------------
# Deterministic JSON, hashing and confinement
# ---------------------------------------------------------------------------


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: str):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def write_json_exclusive(path: str, value) -> None:
    """Exclusive-create semantics: never replace existing evidence."""
    destination = os.path.abspath(path)
    if os.path.exists(destination):
        raise D3AError("D3A_WRITE_EXISTS", f"refusing to overwrite {destination}")
    directory = os.path.dirname(destination)
    os.makedirs(directory, exist_ok=True)
    temporary = destination + ".tmp"
    if os.path.exists(temporary):
        raise D3AError("D3A_WRITE_EXISTS", f"temporary path already exists: {temporary}")
    with open(temporary, "xb") as handle:
        handle.write(canonical_json_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    if os.path.exists(destination):
        os.unlink(temporary)
        raise D3AError("D3A_WRITE_EXISTS", f"refusing to overwrite {destination}")
    os.replace(temporary, destination)


def confined(root: str, path: str, label: str) -> str:
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.abspath(path))
    if candidate == root_real:
        raise D3AError("D3A_PATH", f"{label} must be a strict subdirectory of {root_real}")
    if not candidate.startswith(root_real + os.sep):
        raise D3AError("D3A_PATH", f"{label} escapes {root_real}: {candidate}")
    return candidate


# ---------------------------------------------------------------------------
# Protocol and lane validation
# ---------------------------------------------------------------------------


def protocol_path() -> str:
    return os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3a/protocol_v1.json")


def validate_protocol(protocol) -> dict:
    if protocol != EXPECTED_PROTOCOL:
        unknown = sorted(set(protocol) ^ set(EXPECTED_PROTOCOL))
        raise D3AError(
            "D3A_PROTOCOL",
            f"protocol differs from the frozen literal (keys differing: {unknown})",
        )
    return protocol


def load_protocol() -> tuple[dict, str]:
    path = protocol_path()
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise D3AError("D3A_PROTOCOL", f"cannot read {path}: {error}") from error
    try:
        protocol = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise D3AError("D3A_PROTOCOL", f"malformed protocol: {error}") from error
    validate_protocol(protocol)
    return protocol, sha256_bytes(raw)


def parse_lane(lane_id: str) -> dict:
    parts = lane_id.split("/")
    if len(parts) != 4 or parts[0] != "pr15d_v1":
        raise D3AInvalid("D3A_LANE", f"malformed lane id {lane_id!r}")
    n_text, class_name, k_text = parts[1], parts[2], parts[3]
    if class_name not in CLASS_TERMS:
        raise D3AInvalid("D3A_LANE", f"unknown class in {lane_id!r}")
    if not k_text.startswith("k") or not k_text[1:].isdigit():
        raise D3AInvalid("D3A_LANE", f"malformed K in {lane_id!r}")
    n = int(n_text)
    k = int(k_text[1:])
    if n not in (10000, 100000) or k <= 0:
        raise D3AInvalid("D3A_LANE", f"unsupported lane {lane_id!r}")
    field, term = CLASS_TERMS[class_name]
    return {
        "id": lane_id,
        "n": n,
        "class": class_name,
        "field": field,
        "term": term,
        "k": k,
        "kind": "low_match" if class_name in ("absent", "rare") else "medium_common",
    }


def lane_descriptors(protocol: dict) -> list[dict]:
    lanes = [parse_lane(lane_id) for lane_id in protocol["lane_ids"]]
    if [lane["id"] for lane in lanes] != protocol["lane_ids"]:
        raise D3AInvalid("D3A_LANE", "lane order changed")
    return lanes


def slot_plan(protocol: dict) -> list[dict]:
    orders = protocol["arm_order_by_block"]
    if len(orders) != protocol["blocks_per_campaign"]:
        raise D3AInvalid("D3A_SCHEDULE", "block count mismatch")
    plan = []
    for block, order in enumerate(orders, start=1):
        if len(order) != protocol["slots_per_block"]:
            raise D3AInvalid("D3A_SCHEDULE", f"block {block} has wrong slot count")
        if sorted(order) != ["A", "A", "P", "P", "Q", "Q"]:
            raise D3AInvalid("D3A_SCHEDULE", f"block {block} is not arm-balanced")
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
        raise D3AInvalid("D3A_SCHEDULE", "slot count mismatch")
    return plan


def campaign_kind(name: str, protocol: dict) -> str:
    if name == protocol["control_campaign"]:
        return "control"
    if name in protocol["campaigns"]:
        return "paired"
    raise D3AInvalid("D3A_CAMPAIGN", f"unknown campaign {name!r}")


def control_plan(protocol: dict) -> list[dict]:
    orders = protocol["control_arm_order_by_block"]
    if len(orders) != protocol["control_blocks"]:
        raise D3AInvalid("D3A_SCHEDULE", "control block count mismatch")
    plan = []
    for block, order in enumerate(orders, start=1):
        if len(order) % 2 != 0:
            raise D3AInvalid("D3A_SCHEDULE", f"control block {block} has malformed arms")
        arms = [order[index : index + 2] for index in range(0, len(order), 2)]
        if len(arms) != protocol["control_slots_per_block"]:
            raise D3AInvalid("D3A_SCHEDULE", f"control block {block} has wrong slot count")
        if sorted(arms) != ["A1", "A1", "A2", "A2"]:
            raise D3AInvalid("D3A_SCHEDULE", f"control block {block} is not arm-balanced")
        for position, arm in enumerate(arms, start=1):
            plan.append(
                {
                    "slot": (block - 1) * protocol["control_slots_per_block"] + position,
                    "block": block,
                    "position": position,
                    "arm": arm,
                }
            )
    if len(plan) != protocol["control_slots_per_campaign"]:
        raise D3AInvalid("D3A_SCHEDULE", "control slot count mismatch")
    return plan


def compute_control_timing(slot_records: dict, protocol: dict) -> dict:
    plan = control_plan(protocol)
    lanes = {}
    for lane in lane_descriptors(protocol):
        lane_id = lane["id"]
        values = block_arm_values(slot_records, plan, lane_id)
        blocks = []
        ratios = []
        for block in range(1, protocol["control_blocks"] + 1):
            for arm in ("A1", "A2"):
                slots = values.get((arm, block), [])
                if len(slots) != protocol["control_arm_slots_per_block"]:
                    raise D3AInvalid(
                        "D3A_SLOT",
                        f"{lane_id} arm {arm} block {block}: {len(slots)} slots",
                    )
            a1_slots = values[("A1", block)]
            a2_slots = values[("A2", block)]
            a1_mean = _mean2(a1_slots[0][1], a1_slots[1][1])
            a2_mean = _mean2(a2_slots[0][1], a2_slots[1][1])
            if a1_mean <= 0 or a2_mean <= 0:
                raise D3AInvalid("D3A_RATIO", f"{lane_id} block {block}: non-positive median")
            ratio = a1_mean / a2_mean
            ratios.append(ratio)
            blocks.append(
                {
                    "block": block,
                    "a1_slots": [slot for slot, _ in a1_slots],
                    "a2_slots": [slot for slot, _ in a2_slots],
                    "a1_a2": ratio,
                }
            )
        lanes[lane_id] = {
            "class": lane["class"],
            "kind": lane["kind"],
            "blocks": blocks,
            "campaign": {"a1_a2": median_of_four(ratios)},
        }
    return {"schema": "pr15i-d3a-control-timing-v1", "lanes": lanes}


def control_failures(timing: dict, protocol: dict) -> list[dict]:
    failures = []
    low = protocol["a_a_outlier_block_low"]
    high = protocol["a_a_outlier_block_high"]
    median_low = protocol["a_a_drift_median_min"]
    median_high = protocol["a_a_drift_median_max"]
    hard_low = protocol["a_a_outlier_hard_low"]
    hard_high = protocol["a_a_outlier_hard_high"]
    for lane_id, lane in timing["lanes"].items():
        for block in lane["blocks"]:
            ratio = block["a1_a2"]
            if not (low <= ratio <= high):
                failures.append(
                    {
                        "lane": lane_id,
                        "gate": "CONTROL_BLOCK_RATIO",
                        "block": block["block"],
                        "observed": ratio,
                        "expected": [low, high],
                    }
                )
            if ratio < hard_low or ratio > hard_high:
                failures.append(
                    {
                        "lane": lane_id,
                        "gate": "CONTROL_HARD_OUTLIER",
                        "block": block["block"],
                        "observed": ratio,
                        "expected": [hard_low, hard_high],
                    }
                )
        aggregate = lane["campaign"]["a1_a2"]
        if not (median_low <= aggregate <= median_high):
            failures.append(
                {
                    "lane": lane_id,
                    "gate": "CONTROL_LOWER_MEDIAN",
                    "observed": aggregate,
                    "expected": [median_low, median_high],
                }
            )
    return failures


# ---------------------------------------------------------------------------
# Sample validation and deterministic statistics
# ---------------------------------------------------------------------------


def validate_samples(samples, expected: int = 20) -> None:
    if not isinstance(samples, list) or len(samples) != expected:
        raise D3AInvalid(
            "D3A_SAMPLE_COUNT", f"expected {expected} samples, found {type(samples).__name__}"
        )
    for value in samples:
        if isinstance(value, bool) or not isinstance(value, int):
            raise D3AInvalid("D3A_SAMPLE_TYPE", f"sample {value!r} is not an integer")
        if value <= 0:
            raise D3AInvalid("D3A_SAMPLE_DOMAIN", f"sample {value!r} is not positive")


def nearest_rank_median_20(samples) -> int:
    validate_samples(samples, 20)
    return sorted(samples)[9]


def median_of_four(values) -> float:
    if len(values) != 4:
        raise D3AInvalid("D3A_RATIO", f"expected four block values, found {len(values)}")
    ordered = sorted(values)
    return (ordered[1] + ordered[2]) / 2


def _mean2(first: int, second: int) -> float:
    return (first + second) / 2


def block_arm_values(slot_records: dict, plan: list[dict], lane_id: str) -> dict:
    values = {}
    for entry in plan:
        record = slot_records[entry["slot"]]
        lane = None
        for item in record["lanes"]:
            if item["id"] == lane_id:
                lane = item
                break
        if lane is None:
            raise D3AInvalid("D3A_SLOT", f"slot {entry['slot']} is missing lane {lane_id}")
        median = nearest_rank_median_20(lane["samples_ns"])
        values.setdefault((entry["arm"], entry["block"]), []).append(
            (entry["slot"], median)
        )
    return values


def compute_timing(slot_records: dict, protocol: dict) -> dict:
    plan = slot_plan(protocol)
    lanes = {}
    for lane in lane_descriptors(protocol):
        lane_id = lane["id"]
        values = block_arm_values(slot_records, plan, lane_id)
        blocks = []
        drift_values = []
        qa_values = []
        pq_values = []
        pa_values = []
        for block in range(1, protocol["blocks_per_campaign"] + 1):
            for arm in ("A", "Q", "P"):
                slots = values.get((arm, block), [])
                if len(slots) != protocol["arm_slots_per_block"]:
                    raise D3AInvalid(
                        "D3A_SLOT",
                        f"{lane_id} arm {arm} block {block}: {len(slots)} slots",
                    )
            a_slots = values[("A", block)]
            q_slots = values[("Q", block)]
            p_slots = values[("P", block)]
            a_mean = _mean2(a_slots[0][1], a_slots[1][1])
            q_mean = _mean2(q_slots[0][1], q_slots[1][1])
            p_mean = _mean2(p_slots[0][1], p_slots[1][1])
            if a_slots[0][1] <= 0 or q_mean <= 0 or p_mean <= 0:
                raise D3AInvalid("D3A_RATIO", f"{lane_id} block {block}: non-positive median")
            drift = a_slots[1][1] / a_slots[0][1]
            qa = q_mean / a_mean
            pq = p_mean / q_mean
            pa = p_mean / a_mean
            drift_values.append(drift)
            qa_values.append(qa)
            pq_values.append(pq)
            pa_values.append(pa)
            blocks.append(
                {
                    "block": block,
                    "a_slots": [slot for slot, _ in a_slots],
                    "q_slots": [slot for slot, _ in q_slots],
                    "p_slots": [slot for slot, _ in p_slots],
                    "q_a": qa,
                    "p_q": pq,
                    "p_a": pa,
                    "a_a_drift": drift,
                }
            )
        lanes[lane_id] = {
            "class": lane["class"],
            "kind": lane["kind"],
            "blocks": blocks,
            "campaign": {
                "q_a": median_of_four(qa_values),
                "p_q": median_of_four(pq_values),
                "p_a": median_of_four(pa_values),
                "a_a_drift": median_of_four(drift_values),
            },
        }
    return {"schema": "pr15i-d3a-timing-v1", "lanes": lanes}


def _ceiling(kind: str, prefix: str, protocol: dict) -> float:
    if kind == "low_match":
        return protocol[f"{prefix}_ratio_ceiling_low_match"]
    return protocol[f"{prefix}_ratio_ceiling_medium_common"]


def stability_failures(timing: dict, protocol: dict) -> list[dict]:
    failures = []
    low = protocol["a_a_drift_median_min"]
    high = protocol["a_a_drift_median_max"]
    block_low = protocol["a_a_outlier_block_low"]
    block_high = protocol["a_a_outlier_block_high"]
    maximum = protocol["a_a_max_outlier_blocks_per_lane"]
    for lane_id, lane in timing["lanes"].items():
        drift = lane["campaign"]["a_a_drift"]
        if not (low <= drift <= high):
            failures.append(
                {
                    "lane": lane_id,
                    "gate": "A_A_MEDIAN",
                    "observed": drift,
                    "expected": [low, high],
                }
            )
        outliers = sum(
            1
            for block in lane["blocks"]
            if not (block_low <= block["a_a_drift"] <= block_high)
        )
        if outliers > maximum:
            failures.append(
                {
                    "lane": lane_id,
                    "gate": "A_A_OUTLIER_BLOCKS",
                    "observed": outliers,
                    "maximum": maximum,
                }
            )
    return failures


def intrusion_failures(timing: dict, protocol: dict) -> list[dict]:
    failures = []
    guard = protocol["single_block_guard_ceiling"]
    for lane_id, lane in timing["lanes"].items():
        kind = lane["kind"]
        for prefix, key in (("q_a", "q_a"), ("p_q", "p_q")):
            ceiling = _ceiling(kind, prefix, protocol)
            median = lane["campaign"][key]
            if median > ceiling:
                failures.append(
                    {
                        "lane": lane_id,
                        "gate": f"{key.upper()}_MEDIAN",
                        "observed": median,
                        "ceiling": ceiling,
                    }
                )
            for block in lane["blocks"]:
                ratio = block[key]
                if ratio <= 0 or ratio > guard:
                    failures.append(
                        {
                            "lane": lane_id,
                            "gate": f"{key.upper()}_BLOCK",
                            "block": block["block"],
                            "observed": ratio,
                            "guard": guard,
                        }
                    )
    return failures


def classify_timing(timing: dict, protocol: dict) -> tuple[str, list[dict]]:
    stability = stability_failures(timing, protocol)
    if stability:
        return "D3A_UNSTABLE", stability
    intrusion = intrusion_failures(timing, protocol)
    if intrusion:
        return "D3A_DIAGNOSTIC_PERTURBED", intrusion
    return "D3A_ATTRIBUTION_LOW_INTRUSION", []


def series_status(campaign_statuses: dict) -> str:
    statuses = list(campaign_statuses.values())
    if any(status == "INVALID" for status in statuses):
        return "D3A_INVALID"
    if any(status == "BLOCKED" for status in statuses):
        return "D3A_BLOCKED"
    if any(status == "D3A_UNSTABLE" for status in statuses):
        return "D3A_UNSTABLE"
    if all(status == "D3A_ATTRIBUTION_LOW_INTRUSION" for status in statuses):
        return "D3A_ATTRIBUTION_LOW_INTRUSION"
    return "D3A_DIAGNOSTIC_PERTURBED"


# ---------------------------------------------------------------------------
# Stage partition and closed hypothesis vocabulary
# ---------------------------------------------------------------------------

HYPOTHESES = [
    ("H-CANDIDATE", "candidate_ns"),
    ("H-LEAF", "leaf_decode_ns"),
    ("H-MEMBERSHIP", "membership_ns"),
    ("H-SCORE", "score_vector_ns"),
    ("H-LIVE", "reader_live_ns"),
    ("H-STATS", "stats_ns"),
    ("H-PLAN", "plan_ns"),
    ("H-PROJECTION", "projection_ns"),
    ("H-OTHER", "other_ns"),
]

EXCLUSIVE_CATEGORIES = [
    "plan_ns",
    "reader_live_ns",
    "expand_ns",
    "stats_ns",
    "leaf_decode_ns",
    "membership_ns",
    "score_vector_ns",
    "eval_residual_ns",
    "candidate_ns",
    "projection_ns",
    "other_ns",
]


def _strict_non_negative_array(value, length: int, label: str) -> list[int]:
    if not isinstance(value, list) or len(value) != length:
        raise D3AInvalid("D3A_STAGES", f"{label} must be a {length}-element array")
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise D3AInvalid("D3A_STAGES", f"{label} contains a non-integer {item!r}")
        if item < 0:
            raise D3AInvalid("D3A_STAGES", f"{label} contains a negative {item!r}")
        out.append(item)
    return out


def load_pr15d(checkout_root: str):
    path = os.path.join(checkout_root, "benchmarks/pr15d/harness/run.py")
    if not os.path.isfile(path):
        raise D3AError("D3A_PR15D", f"missing PR15D harness at {path}")
    spec = importlib.util.spec_from_file_location("pr15d_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_sibling(name: str):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"pr15i_d3a_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_corpus(pr15d_module, corpus_dir: str, protocol: dict) -> dict:
    oracle = pr15d_module.oracle
    os.makedirs(corpus_dir, exist_ok=True)
    manifest_path = os.path.join(corpus_dir, oracle.manifest_filename())
    if not os.path.exists(manifest_path):
        for n in oracle.N_VALUES:
            path = os.path.join(corpus_dir, oracle.corpus_filename(n))
            temporary = path + ".tmp"
            with open(temporary, "wb") as handle:
                handle.write(oracle.build_tsv_text(n).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        manifest = oracle.build_manifest(corpus_dir)
        temporary = manifest_path + ".tmp"
        with open(temporary, "wb") as handle:
            handle.write(oracle.canonical_json_bytes(manifest))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, manifest_path)
    manifest, rows_by_n = oracle.load_and_verify(corpus_dir)
    digest = oracle.sha256_bytes(oracle.canonical_json_bytes(manifest))
    if digest != protocol["corpus_manifest_sha256"]:
        raise D3AInvalid(
            "D3A_CORPUS",
            f"corpus manifest {digest} != frozen {protocol['corpus_manifest_sha256']}",
        )
    return {"manifest": manifest, "rows_by_n": rows_by_n, "digest": digest}


def collect_environment() -> dict:
    import platform

    toolchains = {}
    for name, command in (
        ("rustc", ["rustc", "-Vv"]),
        ("cargo", ["cargo", "-V"]),
        ("java", ["java", "-version"]),
        ("python3", ["python3", "-V"]),
        ("rustfmt", ["rustfmt", "--version"]),
        ("git", ["git", "--version"]),
    ):
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=60
            )
            toolchains[name] = {
                "present": result.returncode == 0,
                "version": (result.stdout or result.stderr).strip().splitlines()[:1],
            }
        except (OSError, subprocess.TimeoutExpired):
            toolchains[name] = {"present": False, "version": None}
    filesystem = None
    try:
        result = subprocess.run(
            ["findmnt", "-n", "-o", "FSTYPE", "-T", TOOLING_ROOT],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            filesystem = result.stdout.splitlines()[0].strip()
    except OSError:
        filesystem = None
    return {
        "kernel": platform.uname().release,
        "machine": platform.uname().machine,
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "filesystem": filesystem,
        "native_filesystem": filesystem in ("ext4", "xfs", "btrfs"),
        "wsl": "microsoft" in (open("/proc/version").read().lower() if os.path.exists("/proc/version") else ""),
        "toolchains": toolchains,
        "allowed_cpus": sorted(os.sched_getaffinity(0)),
    }


def _cpu_model() -> str | None:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def host_fingerprint(environment: dict) -> str:
    selected = {
        "kernel": environment.get("kernel"),
        "machine": environment.get("machine"),
        "cpu_model": environment.get("cpu_model"),
        "cpu_count": environment.get("cpu_count"),
        "filesystem": environment.get("filesystem"),
        "wsl": environment.get("wsl"),
    }
    return sha256_bytes(canonical_json_bytes(selected))


# ---------------------------------------------------------------------------
# Index layout
# ---------------------------------------------------------------------------


def measure_index_layout(index_dir: str) -> dict:
    files = []
    stored_bytes = 0
    stored_version = None
    codec_id = None
    required_features = []
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
                    raise D3AInvalid("D3A_INDEX_FORMAT", f"not a segment: {relative}")
                trailer = len(data) - 64
                footer_offset = struct.unpack_from("<Q", data, trailer + 8)[0]
                footer_len = struct.unpack_from("<Q", data, trailer + 16)[0]
                section_count = struct.unpack_from("<I", data, trailer + 24)[0]
                cursor = footer_offset
                if struct.unpack_from("<H", data, cursor)[0] != 1:
                    raise D3AInvalid("D3A_INDEX_FORMAT", "bad segment footer")
                cursor += 6
                required = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                features = []
                for _ in range(required):
                    features.append(
                        [
                            struct.unpack_from("<H", data, cursor)[0],
                            struct.unpack_from("<H", data, cursor + 2)[0],
                        ]
                    )
                    cursor += 4
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
                        codec_id = data[offset + 12] if stored_version == 2 else None
                if cursor != footer_offset + footer_len:
                    raise D3AInvalid("D3A_INDEX_FORMAT", "footer length mismatch")
                required_features = sorted(features)
    files.sort(key=lambda item: item["path"])
    committed = sum(item["size"] for item in files)
    digest = sha256_bytes(canonical_json_bytes(files))
    return {
        "index_dir": os.path.abspath(index_dir),
        "committed_index_bytes": committed,
        "stored_bytes": stored_bytes,
        "stored_version": stored_version,
        "codec_id": codec_id,
        "required_features": required_features,
        "digest": digest,
        "files": files,
    }


def build_one_index(pr15d_module, binary: str, corpus_path: str, index_dir: str, rows: int) -> dict:
    if os.path.exists(index_dir):
        raise D3AError("D3A_WRITE_EXISTS", f"index directory already exists: {index_dir}")
    os.makedirs(index_dir, exist_ok=True)
    process = pr15d_module.AdapterProcess("quervant", [binary])
    try:
        response = process.request(
            {
                "request_id": f"build:{os.path.basename(index_dir)}",
                "op": "build",
                "corpus_path": corpus_path,
                "index_dir": index_dir,
            }
        )
    finally:
        process.close()
    if response.get("documents_indexed") != rows or response.get("documents_verified") != rows:
        raise D3AInvalid("D3A_INDEX_BUILD", f"document count verification failed for {index_dir}")
    return response


def index_sentinel_failures(layout: dict, protocol: dict) -> list[dict]:
    """Compare the recorded 100K layout to the frozen LZ4 sentinels."""
    failures = []
    for arm, builds in layout["builds"].items():
        entry = builds.get("100000")
        if entry is None:
            failures.append({"arm": arm, "gate": "MISSING_100K"})
            continue
        if entry["committed_index_bytes"] != protocol["100k_lz4_committed_index_sentinel"]:
            failures.append(
                {
                    "arm": arm,
                    "gate": "COMMITTED_INDEX_BYTES",
                    "observed": entry["committed_index_bytes"],
                    "expected": protocol["100k_lz4_committed_index_sentinel"],
                }
            )
        if entry["stored_bytes"] != protocol["100k_lz4_stored_section_sentinel"]:
            failures.append(
                {
                    "arm": arm,
                    "gate": "STORED_SECTION_BYTES",
                    "observed": entry["stored_bytes"],
                    "expected": protocol["100k_lz4_stored_section_sentinel"],
                }
            )
    if "A" in layout["builds"] and "QP" in layout["builds"]:
        for n in ("10000", "100000"):
            left = layout["builds"]["A"].get(n, {}).get("digest")
            right = layout["builds"]["QP"].get(n, {}).get("digest")
            if left is None or left != right:
                failures.append({"n": n, "gate": "A_QP_INDEX_DIGEST"})
    return failures


# ---------------------------------------------------------------------------
# Affinity, processes and contention
# ---------------------------------------------------------------------------


def affinity_plan() -> tuple[int, int]:
    cpus = sorted(os.sched_getaffinity(0))
    if len(cpus) < 2:
        raise D3ABlocked("D3A_AFFINITY", f"need at least two allowed CPUs, found {cpus}")
    if shutil.which("taskset") is None:
        raise D3ABlocked("D3A_AFFINITY", "taskset is not available")
    return cpus[1], cpus[0]


def pin_controller(controller_cpu: int) -> None:
    os.sched_setaffinity(0, {controller_cpu})
    if sorted(os.sched_getaffinity(0)) != [controller_cpu]:
        raise D3ABlocked("D3A_AFFINITY", "controller affinity could not be pinned")


def _cpus_allowed_list(pid: int) -> list[int] | None:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("Cpus_allowed_list:"):
                    text = line.split(":", 1)[1].strip()
                    cpus = []
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


def launch_pinned(pr15d_module, adapter_cpu: int, binary: str, index_dir: str):
    command = [
        "taskset",
        "-c",
        str(adapter_cpu),
        binary,
        "--index-dir",
        index_dir,
    ]
    process = pr15d_module.AdapterProcess("quervant", command)
    # The forked child inherits the controller affinity until `taskset` execs;
    # observe the settled affinity with a bounded wait.
    deadline = time.monotonic() + 5.0
    while True:
        allowed = _cpus_allowed_list(process.process.pid)
        if allowed == [adapter_cpu]:
            return process
        if process.process.poll() is not None or time.monotonic() >= deadline:
            process.close()
            raise D3ABlocked(
                "D3A_AFFINITY",
                f"adapter pid {process.process.pid} affinity {allowed} != [{adapter_cpu}]",
            )
        time.sleep(0.001)


def contention_probe(pr15d_module, path: str) -> dict:
    record = pr15d_module.check_contention(path)
    if record.get("state") != "clear" or record.get("reason_codes") not in ([], None):
        raise D3ABlocked(
            "D3A_CONTENTION", f"contention probe not clear: {json.dumps(record, sort_keys=True)}"
        )
    return record


# ---------------------------------------------------------------------------
# Build subcommand
# ---------------------------------------------------------------------------


def _build_binary_path(root: str, arm: str) -> str:
    return os.path.join(
        root, "target", "pr15i-d3a", "build", arm, "release", ADAPTER_BINARY_NAME
    )


def _build_meta_path(root: str, arm: str) -> str:
    return os.path.join(root, "target", "pr15i-d3a", "build", arm, "build.json")


def cargo_build(root: str, arm: str, features: list[str] | None) -> dict:
    target_dir = os.path.join(root, "target", "pr15i-d3a", "build", arm)
    os.makedirs(target_dir, exist_ok=True)
    command = [
        "cargo",
        "build",
        "--release",
        "--locked",
        "--manifest-path",
        os.path.join(root, ADAPTER_MANIFEST),
        "--target-dir",
        target_dir,
    ]
    if features:
        command.extend(["--features", *features])
    environment = dict(os.environ)
    sanitized = {}
    for name in ("RUSTFLAGS", "CARGO_INCREMENTAL", "RUSTC_WRAPPER", "LLVM_PROFILE_FILE"):
        sanitized[name] = environment.pop(name, None)
    result = subprocess.run(
        command,
        cwd=os.path.dirname(os.path.join(root, ADAPTER_MANIFEST)),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    log_path = os.path.join(target_dir, "build.log")
    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write(" ".join(command) + "\n")
        handle.write(result.stdout)
        handle.flush()
        os.fsync(handle.fileno())
    if result.returncode != 0:
        raise D3ABlocked(
            "D3A_BUILD",
            f"{arm} adapter build failed ({result.returncode}): {result.stdout[-4000:]}",
        )
    binary = _build_binary_path(root, arm)
    if not os.path.isfile(binary):
        raise D3ABlocked("D3A_BUILD", f"{arm} binary missing at {binary}")
    metadata = {
        "schema": "pr15i-d3a-build-v1",
        "arm": arm,
        "root": os.path.abspath(root),
        "binary": binary,
        "binary_sha256": sha256_file(binary),
        "features": features or [],
        "command": command,
        "sanitized_environment": sanitized,
        "log": log_path,
        "rustc": subprocess.run(
            ["rustc", "-Vv"], capture_output=True, text=True, check=False
        ).stdout.strip(),
        "protocol_sha256": load_protocol()[1],
        "base_sha": BASE_SHA,
    }
    write_json_exclusive(_build_meta_path(root, arm), metadata)
    return metadata


def run_build(args) -> int:
    checkout_root = confined_root(args.base_root, "base-root")
    instrumented_root = confined_root(args.scratch_root, "scratch-root")
    out = confined(TARGET_ROOT, args.out, "--out")
    protocol, protocol_sha = load_protocol()
    if _git(checkout_root, "rev-parse", "HEAD") != BASE_SHA:
        raise D3AInvalid("D3A_SOURCE", "checkout-root is not at BASE")
    if _git(checkout_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise D3AInvalid("D3A_SOURCE", "checkout-root is not clean")

    patcher = load_sibling("patch_source")
    proof_module = load_sibling("source_proof")
    # A derives from pristine BASE; QP derives from the materialized scratch tree.
    os.makedirs(out, exist_ok=True)
    derivation_path = os.path.join(
        instrumented_root, "target", "pr15i-d3a", "build", "QP", "source-derivation.json"
    )
    derivation = patcher.materialize(instrumented_root, derivation_path)
    proof = proof_module.prove(checkout_root, instrumented_root)
    if proof["derivative_fingerprint_sha256"] != derivation["derivative_fingerprint_sha256"]:
        raise D3AInvalid("D3A_SOURCE", "materializer and independent proof disagree")

    a_build = cargo_build(checkout_root, "A", None)
    qp_build = cargo_build(instrumented_root, "QP", [f"quervant-core/{FEATURE}"])
    if a_build["binary_sha256"] == qp_build["binary_sha256"]:
        raise D3AInvalid("D3A_BUILD", "A and Q/P binaries are identical")

    record = {
        "schema": "pr15i-d3a-series-build-v1",
        "base_sha": BASE_SHA,
        "protocol_sha256": protocol_sha,
        "source_derivation_sha256": sha256_bytes(canonical_json_bytes(derivation)),
        "derivative_fingerprint_sha256": derivation["derivative_fingerprint_sha256"],
        "source_proof": proof,
        "A": a_build,
        "QP": qp_build,
        "status": "BUILT",
    }
    write_json_exclusive(os.path.join(out, "series-build.json"), record)
    print(canonical_json_bytes(record).decode("utf-8"))
    return 0


# ---------------------------------------------------------------------------
# Campaign subcommand
# ---------------------------------------------------------------------------


def confined_root(path: str, label: str) -> str:
    candidate = os.path.realpath(os.path.abspath(path))
    if not os.path.isdir(candidate):
        raise D3AError("D3A_PATH", f"{label} is not a directory: {candidate}")
    return candidate


def _git(root: str, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise D3AInvalid("D3A_GIT", f"git {' '.join(args)}: {result.stdout.strip()}")
    return result.stdout.rstrip("\n")


def _lane_query(lane: dict, k: int | None = None) -> dict:
    return {
        "field": lane["field"],
        "term": lane["term"],
        "k": lane["k"] if k is None else k,
        "mode": "warm",
    }


def _validate_response(response: dict, lane: dict, expected: dict, request_id: str) -> None:
    if response.get("request_id") != request_id:
        raise D3AInvalid("D3A_REQUEST_ID", f"{request_id}: response id mismatch")
    engine_ns = response.get("engine_ns")
    if isinstance(engine_ns, bool) or not isinstance(engine_ns, int) or engine_ns <= 0:
        raise D3AInvalid("D3A_DURATION", f"{lane['id']}: invalid engine_ns {engine_ns!r}")
    if response.get("total_hits") != expected["total_hits"]:
        raise D3AInvalid("D3A_ORACLE", f"{lane['id']}: total_hits mismatch")
    if response.get("doc_ids") != expected["doc_ids"]:
        raise D3AInvalid("D3A_ORACLE", f"{lane['id']}: doc_ids differ from oracle")


def _stage_pairs_to_arrays(pairs):
    if not isinstance(pairs, list) or len(pairs) != len(STAGE_LABELS):
        raise D3AInvalid("D3A_STAGES", "stage_ns is not a ten-pair array")
    names = [pair[0] for pair in pairs]
    if names != STAGE_LABELS:
        raise D3AInvalid("D3A_STAGES", "stage labels are missing, reordered or duplicated")
    values = []
    for name, value in pairs:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise D3AInvalid("D3A_STAGES", f"stage {name} has invalid value {value!r}")
        values.append(value)
    return values


def _counter_pairs_to_arrays(pairs):
    if not isinstance(pairs, list) or len(pairs) != len(COUNTER_LABELS):
        raise D3AInvalid("D3A_COUNTERS", "counts is not a three-pair array")
    names = [pair[0] for pair in pairs]
    if names != COUNTER_LABELS:
        raise D3AInvalid("D3A_COUNTERS", "counter labels are missing, reordered or duplicated")
    values = []
    for name, value in pairs:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise D3AInvalid("D3A_COUNTERS", f"counter {name} has invalid value {value!r}")
        values.append(value)
    return values


def _segment_descriptors(value):
    if not isinstance(value, list) or len(value) > 32:
        raise D3AInvalid("D3A_SEGMENTS", "segments is not a bounded list")
    descriptors = []
    for descriptor in value:
        if not isinstance(descriptor, list) or len(descriptor) != 4:
            raise D3AInvalid("D3A_SEGMENTS", "segment descriptor is not a four-item list")
        values = []
        for item in descriptor:
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise D3AInvalid("D3A_SEGMENTS", f"invalid descriptor value {item!r}")
            values.append(item)
        descriptors.append(values)
    return descriptors


def _strata_ns(value):
    if not isinstance(value, list) or len(value) != 2:
        raise D3AInvalid("D3A_STRATA", "sample_strata_ns is not two rows")
    rows = []
    for row in value:
        if not isinstance(row, list) or len(row) != 8:
            raise D3AInvalid("D3A_STRATA", "sample_strata_ns row is not eight values")
        values = []
        for item in row:
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise D3AInvalid("D3A_STRATA", f"invalid strata value {item!r}")
            values.append(item)
        rows.append(values)
    return rows


def _strata_count(value):
    if not isinstance(value, list) or len(value) != 2:
        raise D3AInvalid("D3A_STRATA", "sample_strata_count is not two values")
    values = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise D3AInvalid("D3A_STRATA", f"invalid strata count {item!r}")
        values.append(item)
    return values


PROBE_FIELDS = (
    "stage_ns",
    "counts",
    "segments",
    "sample_strata_ns",
    "sample_strata_count",
    "segments_unsupported",
)


def _query_lane(
    pr15d_module,
    pmap: dict,
    binary: str,
    index_dir: str,
    lane: dict,
    expected: dict,
    address: str,
    arm: str,
    adapter_cpu: int,
    operation: str,
    expect_probe: bool,
):
    process = launch_pinned(pr15d_module, adapter_cpu, binary, index_dir)
    try:
        for warmup in range(pmap["warmups_per_lane_slot"]):
            request_id = f"{address}:warmup-{warmup:02d}"
            payload = {
                "request_id": request_id,
                "op": operation,
                **_lane_query(lane),
            }
            response = process.request(payload)
            _validate_response(response, lane, expected, request_id)
        samples = []
        stage_samples = []
        counter_samples = []
        segment_samples = []
        strata_ns_samples = []
        strata_count_samples = []
        unsupported_samples = []
        observed_hits = expected["total_hits"]
        observed_ids = expected["doc_ids"]
        for sample in range(pmap["samples_per_lane_slot"]):
            request_id = f"{address}:sample-{sample:02d}"
            payload = {
                "request_id": request_id,
                "op": operation,
                **_lane_query(lane),
            }
            response = process.request(payload)
            _validate_response(response, lane, expected, request_id)
            observed_hits = response["total_hits"]
            observed_ids = response["doc_ids"]
            samples.append(response["engine_ns"])
            if expect_probe:
                missing = [name for name in PROBE_FIELDS if name not in response]
                if missing:
                    raise D3AInvalid(
                        "D3A_STAGES", f"{request_id}: P is missing {missing}"
                    )
                stage_samples.append(_stage_pairs_to_arrays(response["stage_ns"]))
                counter_samples.append(_counter_pairs_to_arrays(response["counts"]))
                segment_samples.append(_segment_descriptors(response["segments"]))
                strata_ns_samples.append(_strata_ns(response["sample_strata_ns"]))
                strata_count_samples.append(_strata_count(response["sample_strata_count"]))
                if not isinstance(response["segments_unsupported"], bool):
                    raise D3AInvalid(
                        "D3A_SEGMENTS",
                        f"{request_id}: segments_unsupported is not a boolean",
                    )
                unsupported_samples.append(response["segments_unsupported"])
            else:
                present = [name for name in PROBE_FIELDS if name in response]
                if present:
                    raise D3AInvalid(
                        "D3A_MODE", f"{request_id}: {arm} carries probe-only fields {present}"
                    )
    finally:
        process.close()
    return {
        "id": lane["id"],
        "warmups": pmap["warmups_per_lane_slot"],
        "samples_ns": samples,
        "expected_total_hits": expected["total_hits"],
        "observed_total_hits": observed_hits,
        "doc_ids": observed_ids,
        "stage_samples": stage_samples if expect_probe else None,
        "counter_samples": counter_samples if expect_probe else None,
        "segment_samples": segment_samples if expect_probe else None,
        "strata_ns_samples": strata_ns_samples if expect_probe else None,
        "strata_count_samples": strata_count_samples if expect_probe else None,
        "segments_unsupported_samples": unsupported_samples if expect_probe else None,
    }


def run_campaign(args) -> int:
    base_root = confined_root(args.base_root, "base-root")
    scratch_root = confined_root(args.scratch_root, "scratch-root")
    out = confined(TARGET_ROOT, args.out, "--out")
    protocol, protocol_sha = load_protocol()
    kind = campaign_kind(args.campaign, protocol)
    if not args.idle_confirmed:
        raise D3ABlocked("D3A_IDLE", "--idle-confirmed is required")
    if os.path.exists(out):
        raise D3AError("D3A_WRITE_EXISTS", f"campaign directory already exists: {out}")
    os.makedirs(out)
    raw = os.path.join(out, "raw")
    slots_dir = os.path.join(raw, "slots")
    setup = os.path.join(out, "setup")
    contention_dir = os.path.join(setup, "contention")
    for directory in (raw, slots_dir, contention_dir):
        os.makedirs(directory, exist_ok=True)

    if _git(base_root, "rev-parse", "HEAD") != BASE_SHA:
        raise D3AInvalid("D3A_SOURCE", "base-root is not at BASE")
    if _git(base_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise D3AInvalid("D3A_SOURCE", "base-root is not clean")

    pr15d = load_pr15d(base_root)
    oracle = pr15d.oracle

    if kind == "control":
        a1_meta = cargo_build(base_root, "A1", None)
        a2_meta = cargo_build(base_root, "A2", None)
        for label, meta in (("A1", a1_meta), ("A2", a2_meta)):
            if sha256_file(meta["binary"]) != meta["binary_sha256"]:
                raise D3AInvalid("D3A_BUILD", f"binary hash changed: {label}")
        if a1_meta["binary_sha256"] != a2_meta["binary_sha256"]:
            raise D3ABlocked(
                "D3A_BUILD",
                "A1 and A2 independently built binaries differ; control is invalid",
            )
        arms = {"A1": a1_meta, "A2": a2_meta}
        operation_for = {"A1": "query", "A2": "query"}
        probe_for = {"A1": False, "A2": False}
        plan = control_plan(protocol)
        slot_count = protocol["control_slots_per_campaign"]
        index_arms = ("A1",)
        index_builds = 2
        expected_timed = slot_count * len(protocol["lane_ids"]) * protocol["samples_per_lane_slot"]
        expected_warmups = slot_count * len(protocol["lane_ids"]) * protocol["warmups_per_lane_slot"]
    else:
        if _git(scratch_root, "rev-parse", "HEAD") != BASE_SHA:
            raise D3AInvalid("D3A_SOURCE", "scratch-root HEAD is not BASE")
        a_meta = read_json(_build_meta_path(base_root, "A"))
        qp_meta = read_json(_build_meta_path(scratch_root, "QP"))
        if a_meta["binary_sha256"] == qp_meta["binary_sha256"]:
            raise D3AInvalid("D3A_BUILD", "A and Q/P binary digests are identical")
        for label, meta in (("A", a_meta), ("QP", qp_meta)):
            if sha256_file(meta["binary"]) != meta["binary_sha256"]:
                raise D3AInvalid("D3A_BUILD", f"binary hash changed: {label}")
        derivation = read_json(
            os.path.join(scratch_root, "target", "pr15i-d3a", "build", "QP", "source-derivation.json")
        )
        proof = load_sibling("source_proof").prove(base_root, scratch_root)
        if proof["derivative_fingerprint_sha256"] != derivation["derivative_fingerprint_sha256"]:
            raise D3AInvalid("D3A_SOURCE", "independent source proof disagrees with derivation")
        arms = {"A": a_meta, "QP": qp_meta}
        operation_for = {
            "A": protocol["arm_operations"]["A"],
            "Q": protocol["arm_operations"]["Q"],
            "P": protocol["arm_operations"]["P"],
        }
        probe_for = {"A": False, "Q": False, "P": True}
        plan = slot_plan(protocol)
        slot_count = protocol["slots_per_campaign"]
        index_arms = ("A", "QP")
        index_builds = 4
        expected_timed = slot_count * len(protocol["lane_ids"]) * protocol["samples_per_lane_slot"]
        expected_warmups = slot_count * len(protocol["lane_ids"]) * protocol["warmups_per_lane_slot"]

    controller_cpu, adapter_cpu = affinity_plan()
    pin_controller(controller_cpu)

    corpus_dir = confined(TARGET_ROOT, os.path.join(TARGET_ROOT, "corpus-src"), "corpus")
    corpus = ensure_corpus(pr15d, corpus_dir, protocol)
    lanes = lane_descriptors(protocol)

    environment = collect_environment()
    if not environment["native_filesystem"]:
        raise D3ABlocked(
            "D3A_FILESYSTEM",
            f"non-native filesystem {environment['filesystem']!r}",
        )

    # Index builds: paired A/10K, A/100K, QP/10K, QP/100K; control two shared
    # indexes built once from A1 and used by both independently built binaries.
    build_meta = {"A": arms.get("A")} if kind == "paired" else {}
    if kind == "paired":
        build_meta["QP"] = arms["QP"]
    else:
        build_meta["A1"] = arms["A1"]
    builds = {arm: {} for arm in build_meta}
    for arm in index_arms:
        for n in (10000, 100000):
            corpus_path = os.path.join(corpus_dir, oracle.corpus_filename(n))
            index_dir = os.path.join(setup, "indexes", arm, str(n))
            build_one_index(pr15d, build_meta[arm]["binary"], corpus_path, index_dir, n)
            builds[arm][str(n)] = measure_index_layout(index_dir)
    layout = {"schema": "pr15i-d3a-index-layout-v1", "builds": builds}
    layout_failures = index_sentinel_failures(layout, protocol)
    if layout_failures:
        raise D3AInvalid(
            "D3A_INDEX_FORMAT", json.dumps(layout_failures, sort_keys=True)
        )

    binary_record = {
        "schema": "pr15i-d3a-binaries-v1",
        "q_and_p_exact_same_binary": kind == "paired",
        "arms": {
            label: {"path": meta["binary"], "sha256": meta["binary_sha256"]}
            for label, meta in arms.items()
        },
    }
    authorization = {
        "schema": "pr15i-d3a-authorization-v1",
        "campaign": args.campaign,
        "campaign_kind": kind,
        "base_sha": BASE_SHA,
        "protocol_sha256": protocol_sha,
        "base_head": _git(base_root, "rev-parse", "HEAD"),
        "base_branch": _git(base_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "scratch_head": _git(scratch_root, "rev-parse", "HEAD") if kind == "paired" else None,
        "idle_confirmed": True,
        "controller_cpu": controller_cpu,
        "adapter_cpu": adapter_cpu,
        "slot_count": slot_count,
        "index_builds": index_builds,
    }
    tooling_files = (
        "benchmarks/pr15i_d3a/patch_source.py",
        "benchmarks/pr15i_d3a/source_proof.py",
        "benchmarks/pr15i_d3a/run.py",
        "benchmarks/pr15i_d3a/verify.py",
        "benchmarks/pr15i_d3a/protocol_v1.json",
    )
    sources = {
        "schema": "pr15i-d3a-sources-v1",
        "base_sha": BASE_SHA,
        "protocol_sha256": protocol_sha,
        "tooling": {
            relative: sha256_file(os.path.join(TOOLING_ROOT, relative))
            for relative in tooling_files
        },
        "permitted_diff_paths": list(DERIVATIVE_FILES) if kind == "paired" else [],
    }
    if kind == "paired":
        source_inventory = {}
        for relative in DERIVATIVE_FILES:
            base_path = os.path.join(base_root, relative)
            source_inventory[relative] = {
                "base_sha256": sha256_file(base_path) if os.path.isfile(base_path) else None,
                "derivative_sha256": sha256_file(os.path.join(scratch_root, relative)),
            }
        diagnostic_fingerprint = sha256_bytes(
            canonical_json_bytes(
                {
                    relative: source_inventory[relative]["derivative_sha256"]
                    for relative in DERIVATIVE_FILES
                }
            )
        )
        sources["source_inventory"] = source_inventory
        sources["diagnostic_derivative_sha256"] = diagnostic_fingerprint
        sources["source_proof"] = proof
        sources["source_derivation_sha256"] = sha256_bytes(canonical_json_bytes(derivation))
    else:
        diagnostic_fingerprint = None
        sources["source_inventory"] = {
            relative: {"base_sha256": sha256_file(os.path.join(base_root, relative))}
            for relative in EXISTING_FILES
        }
    corpus_record = {
        "schema": "pr15i-d3a-corpus-v1",
        "manifest_sha256": corpus["digest"],
        "files": corpus["manifest"]["corpora"],
        "queries": corpus["manifest"]["queries"],
    }
    oracle_record = {"schema": "pr15i-d3a-oracle-v1", "lanes": {}}
    for lane in lanes:
        expected = oracle.expected(
            corpus["rows_by_n"][lane["n"]], lane["field"], lane["term"], lane["k"]
        )
        oracle_record["lanes"][lane["id"]] = expected

    for name, value in (
        ("authorization.json", authorization),
        ("environment.json", environment | {"host_fingerprint": host_fingerprint(environment)}),
        ("toolchains.json", environment["toolchains"]),
        ("corpus.json", corpus_record),
        ("sources.json", sources),
        ("binaries.json", binary_record),
        ("index-layout.json", layout),
        ("oracle.json", oracle_record),
    ):
        write_json_exclusive(os.path.join(raw, name), value)

    slot_records = {}
    for entry in plan:
        slot = entry["slot"]
        arm = entry["arm"]
        if kind == "control":
            meta = arms[arm]
            index_arm = "A1"
            operation = operation_for[arm]
            expect_probe = probe_for[arm]
        else:
            meta = arms["A"] if arm == "A" else arms["QP"]
            index_arm = "A" if arm == "A" else "QP"
            operation = operation_for[arm]
            expect_probe = probe_for[arm]
        before_path = os.path.join(contention_dir, f"slot-{slot:02d}-before.json")
        after_path = os.path.join(contention_dir, f"slot-{slot:02d}-after.json")
        contention_probe(pr15d, before_path)
        lanes_out = []
        for lane in lanes:
            index_dir = os.path.join(setup, "indexes", index_arm, str(lane["n"]))
            expected = oracle_record["lanes"][lane["id"]]
            address = f"slot-{slot:02d}:{arm}:{lane['id']}"
            lanes_out.append(
                _query_lane(
                    pr15d,
                    protocol,
                    meta["binary"],
                    index_dir,
                    lane,
                    expected,
                    address,
                    arm,
                    adapter_cpu,
                    operation,
                    expect_probe,
                )
            )
        contention_probe(pr15d, after_path)
        record = {
            "schema": "pr15i-d3a-slot-v1",
            "slot": slot,
            "block": entry["block"],
            "position": entry["position"],
            "arm": arm,
            "base_sha": BASE_SHA,
            "diagnostic_derivative_sha256": (
                None
                if kind == "control" or arm == "A"
                else diagnostic_fingerprint
            ),
            "binary_sha256": sha256_file(meta["binary"]),
            "index_sha256": sha256_bytes(
                canonical_json_bytes(
                    {n: builds[index_arm][n]["digest"] for n in ("10000", "100000")}
                )
            ),
            "lane_ids": protocol["lane_ids"],
            "lanes": lanes_out,
            "contention_before": "clear",
            "contention_after": "clear",
        }
        slot_records[slot] = record
        write_json_exclusive(os.path.join(slots_dir, f"slot-{slot:02d}.json"), record)

    if kind == "control":
        timing = compute_control_timing(slot_records, protocol)
        failures = control_failures(timing, protocol)
        status = "D3A_CONTROL_QUALIFIED" if not failures else "D3A_CONTROL_NOT_QUALIFIED"
        timing["status"] = status
        timing["failures"] = failures
        mode_proof = {
            "schema": "pr15i-d3a-control-mode-proof-v1",
            "a1_a2_same_source": True,
            "control_arms": ["A1", "A2"],
            "probe_fields_absent": True,
        }
    else:
        timing = compute_timing(slot_records, protocol)
        stability = stability_failures(timing, protocol)
        intrusion = [] if stability else intrusion_failures(timing, protocol)
        failures = stability + intrusion
        if stability:
            status = "D3A_UNSTABLE"
        elif intrusion:
            status = "D3A_DIAGNOSTIC_PERTURBED"
        else:
            status = "D3A_ATTRIBUTION_LOW_INTRUSION"
        timing["status"] = status
        timing["failures"] = failures
        mode_proof = {
            "schema": "pr15i-d3a-mode-proof-v1",
            "q_and_p_same_binary": True,
            "q_slots": [entry["slot"] for entry in plan if entry["arm"] == "Q"],
            "p_slots": [entry["slot"] for entry in plan if entry["arm"] == "P"],
            "q_lacks_probe_fields": True,
            "p_carries_probe_fields": True,
        }
    write_json_exclusive(os.path.join(raw, "mode-proof.json"), mode_proof)
    write_json_exclusive(os.path.join(raw, "timing.json"), timing)
    seal_campaign(out, kind=kind, slot_count=slot_count,
                  expected_timed=expected_timed, expected_warmups=expected_warmups,
                  index_builds=index_builds)
    print(canonical_json_bytes({"campaign": args.campaign, "status": status}).decode("utf-8"))
    return 0

# ---------------------------------------------------------------------------
# Seal
# ---------------------------------------------------------------------------

RAW_MEMBERS = [
    "raw/authorization.json",
    "raw/environment.json",
    "raw/toolchains.json",
    "raw/corpus.json",
    "raw/sources.json",
    "raw/binaries.json",
    "raw/index-layout.json",
    "raw/oracle.json",
    "raw/mode-proof.json",
    "raw/timing.json",
]


def required_members(slot_count: int) -> list[str]:
    members = list(RAW_MEMBERS)
    members.extend(f"raw/slots/slot-{slot:02d}.json" for slot in range(1, slot_count + 1))
    for slot in range(1, slot_count + 1):
        members.append(f"setup/contention/slot-{slot:02d}-before.json")
        members.append(f"setup/contention/slot-{slot:02d}-after.json")
    return members


def seal_campaign(
    campaign_dir: str,
    *,
    kind: str | None = None,
    slot_count: int | None = None,
    expected_timed: int | None = None,
    expected_warmups: int | None = None,
    index_builds: int | None = None,
) -> dict:
    campaign_dir = confined(TARGET_ROOT, campaign_dir, "campaign-dir")
    seal_path = os.path.join(campaign_dir, "raw", "seal.json")
    manifest_path = os.path.join(campaign_dir, "raw", "manifest.json")
    if os.path.exists(seal_path):
        raise D3AError("D3A_SEALED", f"campaign is already sealed: {campaign_dir}")
    if slot_count is None:
        campaign_name = os.path.basename(campaign_dir)
        protocol, _ = load_protocol()
        slot_count = (
            protocol["control_slots_per_campaign"]
            if campaign_name == protocol["control_campaign"]
            else protocol["slots_per_campaign"]
        )
        kind = campaign_kind(campaign_name, protocol)
    members = required_members(slot_count)
    missing = [path for path in members if not os.path.isfile(os.path.join(campaign_dir, path))]
    if missing:
        raise D3ABlocked("D3A_SEAL", f"missing required members: {missing}")
    entries = []
    for relative in members:
        path = os.path.join(campaign_dir, relative)
        entries.append(
            {
                "path": relative,
                "size": os.path.getsize(path),
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schema": "pr15i-d3a-manifest-v1",
        "campaign": os.path.basename(campaign_dir),
        "base_sha": BASE_SHA,
        "expected": {
            "campaign_kind": kind,
            "slots": slot_count,
            "blocks": 4,
            "slots_per_block": 6 if kind == "paired" else 4,
            "lanes_per_slot": 9,
            "samples_per_lane_slot": 20,
            "warmups_per_lane_slot": 5,
            "timed_observations": expected_timed,
            "warmups": expected_warmups,
            "contention_probes": slot_count * 2,
            "index_builds": index_builds,
            "p_stage_samples": None if kind == "control" else 8 * 9 * 20,
            "stage_labels": STAGE_LABELS,
            "counter_labels": COUNTER_LABELS,
        },
        "members": entries,
    }
    write_json_exclusive(manifest_path, manifest)
    sealed = entries + [
        {
            "path": "raw/manifest.json",
            "size": os.path.getsize(manifest_path),
            "sha256": sha256_file(manifest_path),
        }
    ]
    seal = {
        "schema": "pr15i-d3a-seal-v1",
        "campaign": os.path.basename(campaign_dir),
        "members": {entry["path"]: entry["sha256"] for entry in sealed},
    }
    write_json_exclusive(seal_path, seal)
    return seal


# ---------------------------------------------------------------------------
# Preflight / source proof CLI
# ---------------------------------------------------------------------------


def preflight(args) -> int:
    checkout_root = confined_root(args.base_root, "base-root")
    scratch_root = confined_root(args.scratch_root, "scratch-root")
    out = confined(TARGET_ROOT, args.out, "--out")
    protocol, protocol_sha = load_protocol()
    blockers = []
    head = _git(checkout_root, "rev-parse", "HEAD")
    clean = _git(checkout_root, "status", "--porcelain", "--untracked-files=all") == ""
    if head != BASE_SHA:
        raise D3AInvalid("D3A_SOURCE", f"checkout HEAD {head} != {BASE_SHA}")
    if not clean:
        raise D3AInvalid("D3A_SOURCE", "base tree is not clean")
    if _git(scratch_root, "rev-parse", "HEAD") != BASE_SHA:
        raise D3AInvalid("D3A_SOURCE", "scratch-root is not at BASE")
    if _git(scratch_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise D3AInvalid("D3A_SOURCE", "scratch-root is not clean")
    environment = collect_environment()
    if not environment["native_filesystem"]:
        blockers.append("NON_NATIVE_FILESYSTEM")
    pr15d = load_pr15d(checkout_root)
    corpus_dir = confined(TARGET_ROOT, os.path.join(TARGET_ROOT, "corpus-src"), "corpus")
    corpus = ensure_corpus(pr15d, corpus_dir, protocol)
    artifacts = {}
    for relative in SOURCE_ARTIFACTS:
        if relative.startswith("benchmarks/pr15i_d3a/"):
            path = os.path.join(TOOLING_ROOT, relative)
        else:
            path = os.path.join(checkout_root, relative)
        if not os.path.isfile(path):
            artifacts[relative] = None
            blockers.append(f"MISSING_SOURCE:{relative}")
        else:
            artifacts[relative] = sha256_file(path)
    record = {
        "schema": "pr15i-d3a-preflight-v1",
        "base_sha": BASE_SHA,
        "base_head": head,
        "scratch_head": _git(scratch_root, "rev-parse", "HEAD"),
        "worktree_clean": clean,
        "origin_main_sha": _git(checkout_root, "rev-parse", "origin/main")
        if _has_origin(checkout_root)
        else None,
        "protocol_sha256": protocol_sha,
        "corpus_manifest_sha256": corpus["digest"],
        "corpus_manifest_matches_frozen": corpus["digest"] == protocol["corpus_manifest_sha256"],
        "source_artifacts": artifacts,
        "environment": environment,
        "host_fingerprint": host_fingerprint(environment),
        "blockers": blockers,
        "status": "PASS" if not blockers else "BLOCKED",
    }
    write_json_exclusive(out, record)
    print(canonical_json_bytes(record).decode("utf-8"))
    return 0 if not blockers else 3


def _has_origin(root: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/main"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def source_proof_cli(args) -> int:
    checkout_root = confined_root(args.base_root, "base-root")
    instrumented_root = confined_root(args.scratch_root, "scratch-root")
    out = confined(TARGET_ROOT, args.out, "--out")
    proof = load_sibling("source_proof").prove(checkout_root, instrumented_root)
    write_json_exclusive(out, proof)
    print(canonical_json_bytes(proof).decode("utf-8"))
    return 0


def seal_cli(args) -> int:
    seal = seal_campaign(args.campaign_dir)
    print(canonical_json_bytes(seal).decode("utf-8"))
    return 0


def run_aa(args) -> int:
    protocol, _ = load_protocol()
    args.campaign = protocol["control_campaign"]
    return run_campaign(args)


# ---------------------------------------------------------------------------
# Evidence archive (outside target/, exclusive create)
# ---------------------------------------------------------------------------


def _archive_members(campaign_dir: str, protocol: dict) -> list[str]:
    excludes = tuple(prefix.rstrip("/") for prefix in protocol["archive_excludes"])

    def excluded(relative: str) -> bool:
        padded = f"/{relative}/"
        return any(f"/{prefix}/" in padded for prefix in excludes)

    members = []
    for root, dirs, names in os.walk(campaign_dir):
        relative_root = os.path.relpath(root, campaign_dir).replace(os.sep, "/")
        if relative_root == ".":
            relative_root = ""
        kept = []
        for directory in sorted(dirs):
            relative_dir = f"{relative_root}/{directory}".lstrip("/")
            if excluded(relative_dir):
                continue
            kept.append(directory)
        dirs[:] = kept
        for name in sorted(names):
            relative = f"{relative_root}/{name}".lstrip("/")
            if excluded(relative):
                continue
            full = os.path.join(campaign_dir, relative)
            if os.path.islink(full) or not os.path.isfile(full):
                raise D3ABlocked("D3A_ARCHIVE", f"non-regular archive member: {relative}")
            members.append(relative)
    return sorted(members)


def _verify_archive(archive_path: str, expected_inventory: dict) -> dict:
    import tarfile

    scratch = tempfile.mkdtemp(prefix="pr15i-d3a-archive-")
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            names = archive.getnames()
            if sorted(names) != sorted(expected_inventory):
                raise D3ABlocked("D3A_ARCHIVE", "archive member inventory differs")
            for name in names:
                if (
                    name.startswith("/")
                    or name.startswith("\\")
                    or ".." in name.split("/")
                ):
                    raise D3ABlocked("D3A_ARCHIVE", f"unsafe archive member {name!r}")
            archive.extractall(scratch, filter="data")
        for relative, expected in expected_inventory.items():
            if sha256_file(os.path.join(scratch, relative)) != expected:
                raise D3ABlocked(
                    "D3A_ARCHIVE", f"archive round-trip hash differs: {relative}"
                )
    finally:
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)
    return {"members": dict(expected_inventory)}


def _write_archive(campaign_dir: str, archive_path: str, members: list[str]) -> dict:
    import tarfile

    if os.path.exists(archive_path):
        raise D3AError(
            "D3A_ARCHIVE_EXISTS",
            f"archive already exists (never overwritten): {archive_path}",
        )
    descriptor = os.open(archive_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    os.close(descriptor)
    inventory = {}
    with tarfile.open(archive_path, "w:gz") as archive:
        for relative in members:
            full = os.path.join(campaign_dir, relative)
            if os.path.islink(full) or not os.path.isfile(full):
                raise D3ABlocked("D3A_ARCHIVE", f"non-regular archive member: {relative}")
            info = archive.gettarinfo(full, arcname=relative)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            with open(full, "rb") as handle:
                archive.addfile(info, handle)
            inventory[relative] = sha256_file(full)
    _verify_archive(archive_path, inventory)
    return inventory


def verify_archive_bundle(
    archive_path: str, sidecar_path: str, expected_inventory: dict
) -> dict:
    """Verify an archive against its immutable SHA-256 sidecar."""
    try:
        with open(sidecar_path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError as error:
        raise D3ABlocked("D3A_ARCHIVE", f"cannot read archive sidecar: {error}") from error
    parts = text.split()
    if len(parts) != 2 or len(parts[0]) != 64:
        raise D3ABlocked("D3A_ARCHIVE", "malformed archive sidecar")
    digest, name = parts
    if name != os.path.basename(archive_path):
        raise D3ABlocked("D3A_ARCHIVE", "archive sidecar names a different file")
    if digest != sha256_file(archive_path):
        raise D3ABlocked("D3A_ARCHIVE", "archive sidecar digest mismatch")
    return _verify_archive(archive_path, expected_inventory)


def cmd_archive(args) -> int:
    protocol, _ = load_protocol()
    campaign_dir = confined(TARGET_ROOT, args.campaign_dir, "campaign-dir")
    evidence_root = os.path.realpath(os.path.abspath(args.evidence_root))
    tooling_root = os.path.realpath(TOOLING_ROOT)
    if evidence_root == tooling_root or evidence_root.startswith(tooling_root + os.sep):
        raise D3AError("D3A_ARCHIVE", "evidence-root must be outside the repository")
    if os.path.islink(args.evidence_root):
        raise D3AError("D3A_ARCHIVE", "evidence-root is a symlink")
    for required in ("sanitized/summary.json", "verification.json"):
        if not os.path.isfile(os.path.join(campaign_dir, required)):
            raise D3ABlocked(
                "D3A_ARCHIVE",
                f"independent verification output is missing: {required}",
            )
    campaign_name = os.path.basename(campaign_dir)
    os.makedirs(evidence_root, exist_ok=True)
    archive_path = os.path.join(evidence_root, f"{campaign_name}.tar.gz")
    sidecar_path = archive_path + ".sha256"
    if os.path.exists(archive_path) or os.path.exists(sidecar_path):
        raise D3AError(
            "D3A_ARCHIVE_EXISTS",
            f"archive or sidecar already exists (never overwritten): {archive_path}",
        )
    members = _archive_members(campaign_dir, protocol)
    inventory = _write_archive(campaign_dir, archive_path, members)
    archive_sha = sha256_file(archive_path)
    sidecar = f"{archive_sha}  {os.path.basename(archive_path)}\n"
    descriptor = os.open(sidecar_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(descriptor, sidecar.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    verify_archive_bundle(archive_path, sidecar_path, inventory)
    record = {
        "schema": "pr15i-d3a-archive-v1",
        "campaign": campaign_name,
        "archive": os.path.basename(archive_path),
        "archive_sha256": archive_sha,
        "member_count": len(inventory),
        "members": inventory,
        "storage_class": "SAME_DISK_ONLY",
    }
    write_json_exclusive(
        os.path.join(campaign_dir, "archive-record.json"), record
    )
    print(canonical_json_bytes(record).decode("utf-8"))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PR 15I-D2-A attribution controller.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_preflight = subparsers.add_parser("preflight")
    p_preflight.add_argument("--base-root", required=True)
    p_preflight.add_argument("--scratch-root", required=True)
    p_preflight.add_argument("--out", required=True)
    p_preflight.set_defaults(handler=preflight)

    p_source = subparsers.add_parser("source-proof")
    p_source.add_argument("--base-root", required=True)
    p_source.add_argument("--scratch-root", required=True)
    p_source.add_argument("--out", required=True)
    p_source.set_defaults(handler=source_proof_cli)

    p_build = subparsers.add_parser("build")
    p_build.add_argument("--base-root", required=True)
    p_build.add_argument("--scratch-root", required=True)
    p_build.add_argument("--out", required=True)
    p_build.set_defaults(handler=run_build)

    p_aa = subparsers.add_parser("aa")
    p_aa.add_argument("--base-root", required=True)
    p_aa.add_argument("--scratch-root", required=True)
    p_aa.add_argument("--out", required=True)
    p_aa.add_argument("--idle-confirmed", action="store_true")
    p_aa.set_defaults(handler=run_aa)

    p_campaign = subparsers.add_parser("campaign")
    p_campaign.add_argument("--base-root", required=True)
    p_campaign.add_argument("--scratch-root", required=True)
    p_campaign.add_argument(
        "--campaign",
        required=True,
        choices=["d3a-unbatched-01", "d3a-unbatched-02"],
    )
    p_campaign.add_argument("--out", required=True)
    p_campaign.add_argument("--idle-confirmed", action="store_true")
    p_campaign.set_defaults(handler=run_campaign)

    p_archive = subparsers.add_parser("archive")
    p_archive.add_argument("--campaign-dir", required=True)
    p_archive.add_argument("--evidence-root", required=True)
    p_archive.set_defaults(handler=cmd_archive)

    p_seal = subparsers.add_parser("seal")
    p_seal.add_argument("--campaign-dir", required=True)
    p_seal.set_defaults(handler=seal_cli)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except D3ABlocked as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 3
    except D3AInvalid as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 2
    except D3AError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""PR 15I-D0 source-locked A/Q/P attribution controller.

Measurement/diagnostics tooling only.  It never changes production source.  The
accepted source is a pristine `BASE` checkout; the diagnostic derivative is a
disposable scratch worktree produced by `patch_instrumented_source.py` and proven
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
import time

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET_ROOT = os.path.join(TOOLING_ROOT, "target", "pr15i-d0")

BASE_SHA = "7237bce325834d6cc1c73735697be29bc60ef16b"
FEATURE = "pr15id0-probe"
PROTOCOL_SCHEMA = "pr15i-d0-attribution-v1"

UNIFIED = "crates/quervant-core/src/search/unified.rs"
EXECUTE = "crates/quervant-core/src/search/execute.rs"
SEARCH_MOD = "crates/quervant-core/src/search/mod.rs"
D0_PROBE = "crates/quervant-core/src/search/d0_probe.rs"
CORE_CARGO = "crates/quervant-core/Cargo.toml"
ADAPTER = "benchmarks/pr15d/adapters/quervant/src/main.rs"
DERIVATIVE_FILES = (UNIFIED, EXECUTE, SEARCH_MOD, D0_PROBE, CORE_CARGO, ADAPTER)

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
]
COUNTER_LABELS = ["matched_docs", "scored_docs", "candidate_docs"]

EXPECTED_PROTOCOL = {
    "schema": "pr15i-d0-attribution-v1",
    "study_type": "THREE_ARM_UNINSTRUMENTED_CODEGEN_ACTIVE_PROBE",
    "diagnostic_only": True,
    "base_sha": BASE_SHA,
    "corpus_manifest_sha256": "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151",
    "source_derivation": "DIAGNOSTIC_INSERTION_ONLY_FROM_BASE",
    "arms": ["A", "Q", "P"],
    "arm_operations": {"A": "query", "Q": "query", "P": "query_probe"},
    "q_and_p_exact_same_binary": True,
    "campaigns": ["unbatched-01", "unbatched-02"],
    "arm_order_by_block": ["AQPPQA", "PQAAQP", "QAPPAQ", "PAQQAP"],
    "blocks_per_campaign": 4,
    "slots_per_block": 6,
    "slots_per_campaign": 24,
    "arm_slots_per_block": 2,
    "warmups_per_lane_slot": 5,
    "samples_per_lane_slot": 20,
    "timed_sample_unit": "single_query_engine_ns",
    "adapter_process_lifetime": "ONE_PROCESS_PER_ARM_LANE_SLOT",
    "required_native_filesystem": ["ext4", "xfs", "btrfs"],
    "required_affinity": "CONTROLLER_SECOND_ALLOWED_CPU_ADAPTER_FIRST_ALLOWED_CPU",
    "contention_probes_per_slot": 2,
    "index_builds_per_campaign": 4,
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
    "stages": STAGE_LABELS,
    "counters": COUNTER_LABELS,
    "a_a_drift_median_min": 0.85,
    "a_a_drift_median_max": 1.15,
    "a_a_outlier_block_low": 0.80,
    "a_a_outlier_block_high": 1.25,
    "a_a_max_outlier_blocks_per_lane": 1,
    "q_a_ratio_ceiling_low_match": 1.15,
    "q_a_ratio_ceiling_medium_common": 1.10,
    "p_q_ratio_ceiling_low_match": 1.25,
    "p_q_ratio_ceiling_medium_common": 1.15,
    "single_block_guard_ceiling": 1.50,
    "quantitative_stage_rank_requires_both_campaigns": True,
    "canonical_pr15d_trails_separate": True,
    "original_15ic_acceptance_gates_unchanged": True,
}

SOURCE_ARTIFACTS = [
    "Cargo.lock",
    "Cargo.toml",
    "crates/quervant-core/Cargo.toml",
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
    "benchmarks/pr15i_d0/protocol_v1.json",
    "benchmarks/pr15i_d0/patch_instrumented_source.py",
    "benchmarks/pr15i_d0/source_proof.py",
    "benchmarks/pr15i_d0/run.py",
    "benchmarks/pr15i_d0/verify.py",
]


class D0Error(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class D0Blocked(D0Error):
    pass


class D0Invalid(D0Error):
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
        raise D0Error("D0_WRITE_EXISTS", f"refusing to overwrite {destination}")
    directory = os.path.dirname(destination)
    os.makedirs(directory, exist_ok=True)
    temporary = destination + ".tmp"
    if os.path.exists(temporary):
        raise D0Error("D0_WRITE_EXISTS", f"temporary path already exists: {temporary}")
    with open(temporary, "xb") as handle:
        handle.write(canonical_json_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    if os.path.exists(destination):
        os.unlink(temporary)
        raise D0Error("D0_WRITE_EXISTS", f"refusing to overwrite {destination}")
    os.replace(temporary, destination)


def confined(root: str, path: str, label: str) -> str:
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.abspath(path))
    if candidate == root_real:
        raise D0Error("D0_PATH", f"{label} must be a strict subdirectory of {root_real}")
    if not candidate.startswith(root_real + os.sep):
        raise D0Error("D0_PATH", f"{label} escapes {root_real}: {candidate}")
    return candidate


# ---------------------------------------------------------------------------
# Protocol and lane validation
# ---------------------------------------------------------------------------


def protocol_path() -> str:
    return os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d0/protocol_v1.json")


def validate_protocol(protocol) -> dict:
    if protocol != EXPECTED_PROTOCOL:
        unknown = sorted(set(protocol) ^ set(EXPECTED_PROTOCOL))
        raise D0Error(
            "D0_PROTOCOL",
            f"protocol differs from the frozen literal (keys differing: {unknown})",
        )
    return protocol


def load_protocol() -> tuple[dict, str]:
    path = protocol_path()
    try:
        raw = open(path, "rb").read()
    except OSError as error:
        raise D0Error("D0_PROTOCOL", f"cannot read {path}: {error}") from error
    try:
        protocol = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise D0Error("D0_PROTOCOL", f"malformed protocol: {error}") from error
    validate_protocol(protocol)
    return protocol, sha256_bytes(raw)


def parse_lane(lane_id: str) -> dict:
    parts = lane_id.split("/")
    if len(parts) != 4 or parts[0] != "pr15d_v1":
        raise D0Invalid("D0_LANE", f"malformed lane id {lane_id!r}")
    n_text, class_name, k_text = parts[1], parts[2], parts[3]
    if class_name not in CLASS_TERMS:
        raise D0Invalid("D0_LANE", f"unknown class in {lane_id!r}")
    if not k_text.startswith("k") or not k_text[1:].isdigit():
        raise D0Invalid("D0_LANE", f"malformed K in {lane_id!r}")
    n = int(n_text)
    k = int(k_text[1:])
    if n not in (10000, 100000) or k <= 0:
        raise D0Invalid("D0_LANE", f"unsupported lane {lane_id!r}")
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
        raise D0Invalid("D0_LANE", "lane order changed")
    return lanes


def slot_plan(protocol: dict) -> list[dict]:
    orders = protocol["arm_order_by_block"]
    if len(orders) != protocol["blocks_per_campaign"]:
        raise D0Invalid("D0_SCHEDULE", "block count mismatch")
    plan = []
    for block, order in enumerate(orders, start=1):
        if len(order) != protocol["slots_per_block"]:
            raise D0Invalid("D0_SCHEDULE", f"block {block} has wrong slot count")
        if sorted(order) != ["A", "A", "P", "P", "Q", "Q"]:
            raise D0Invalid("D0_SCHEDULE", f"block {block} is not arm-balanced")
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
        raise D0Invalid("D0_SCHEDULE", "slot count mismatch")
    return plan


# ---------------------------------------------------------------------------
# Sample validation and deterministic statistics
# ---------------------------------------------------------------------------


def validate_samples(samples, expected: int = 20) -> None:
    if not isinstance(samples, list) or len(samples) != expected:
        raise D0Invalid(
            "D0_SAMPLE_COUNT", f"expected {expected} samples, found {type(samples).__name__}"
        )
    for value in samples:
        if isinstance(value, bool) or not isinstance(value, int):
            raise D0Invalid("D0_SAMPLE_TYPE", f"sample {value!r} is not an integer")
        if value <= 0:
            raise D0Invalid("D0_SAMPLE_DOMAIN", f"sample {value!r} is not positive")


def nearest_rank_median_20(samples) -> int:
    validate_samples(samples, 20)
    return sorted(samples)[9]


def median_of_four(values) -> float:
    if len(values) != 4:
        raise D0Invalid("D0_RATIO", f"expected four block values, found {len(values)}")
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
            raise D0Invalid("D0_SLOT", f"slot {entry['slot']} is missing lane {lane_id}")
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
                    raise D0Invalid(
                        "D0_SLOT",
                        f"{lane_id} arm {arm} block {block}: {len(slots)} slots",
                    )
            a_slots = values[("A", block)]
            q_slots = values[("Q", block)]
            p_slots = values[("P", block)]
            a_mean = _mean2(a_slots[0][1], a_slots[1][1])
            q_mean = _mean2(q_slots[0][1], q_slots[1][1])
            p_mean = _mean2(p_slots[0][1], p_slots[1][1])
            if a_slots[0][1] <= 0 or q_mean <= 0 or p_mean <= 0:
                raise D0Invalid("D0_RATIO", f"{lane_id} block {block}: non-positive median")
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
    return {"schema": "pr15i-d0-timing-v1", "lanes": lanes}


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
        return "D0_UNSTABLE", stability
    intrusion = intrusion_failures(timing, protocol)
    if intrusion:
        return "D0_DIAGNOSTIC_PERTURBED", intrusion
    return "D0_ATTRIBUTION_LOW_INTRUSION", []


def series_status(campaign_statuses: dict) -> str:
    statuses = list(campaign_statuses.values())
    if any(status == "INVALID" for status in statuses):
        return "D0_INVALID"
    if any(status == "BLOCKED" for status in statuses):
        return "D0_BLOCKED"
    if any(status == "D0_UNSTABLE" for status in statuses):
        return "D0_UNSTABLE"
    if all(status == "D0_ATTRIBUTION_LOW_INTRUSION" for status in statuses):
        return "D0_ATTRIBUTION_LOW_INTRUSION"
    return "D0_DIAGNOSTIC_PERTURBED"


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
        raise D0Invalid("D0_STAGES", f"{label} must be a {length}-element array")
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise D0Invalid("D0_STAGES", f"{label} contains a non-integer {item!r}")
        if item < 0:
            raise D0Invalid("D0_STAGES", f"{label} contains a negative {item!r}")
        out.append(item)
    return out


def decompose_sample(engine_ns: int, stages, counts, total_hits: int) -> dict:
    if isinstance(engine_ns, bool) or not isinstance(engine_ns, int) or engine_ns <= 0:
        raise D0Invalid("D0_STAGES", f"engine_ns {engine_ns!r} is not positive")
    stage = _strict_non_negative_array(stages, 10, "stage_ns")
    counter = _strict_non_negative_array(counts, 3, "counts")
    (
        plan,
        reader,
        expand,
        stats,
        evaluate,
        candidate,
        projection,
        leaf,
        membership,
        score,
    ) = stage
    eval_residual = evaluate - leaf - membership - score
    other = engine_ns - (plan + reader + expand + stats + evaluate + candidate + projection)
    if eval_residual < 0:
        raise D0Invalid(
            "D0_STAGE_PARTITION_INVALID",
            f"evaluate {evaluate} < leaf+membership+score {leaf + membership + score}",
        )
    if other < 0:
        raise D0Invalid(
            "D0_STAGE_PARTITION_INVALID",
            "top-level stages exceed engine_ns",
        )
    category = {
        "plan_ns": plan,
        "reader_live_ns": reader,
        "expand_ns": expand,
        "stats_ns": stats,
        "leaf_decode_ns": leaf,
        "membership_ns": membership,
        "score_vector_ns": score,
        "eval_residual_ns": eval_residual,
        "candidate_ns": candidate,
        "projection_ns": projection,
        "other_ns": other,
    }
    if sum(category.values()) != engine_ns:
        raise D0Invalid("D0_STAGE_PARTITION_INVALID", "exclusive partition does not sum")
    matched, scored, candidates = counter
    if not (matched == scored == candidates == total_hits):
        raise D0Invalid(
            "D0_STAGE_COUNTER",
            f"counters {counter} disagree with total_hits {total_hits}",
        )
    return category


def summarize_stages(slot_records: dict, plan: list[dict]) -> dict:
    """Collect every P sample per lane and compute exclusive medians."""
    lanes = {}
    lane_ids = sorted({item["id"] for record in slot_records.values() for item in record["lanes"]})
    for lane_id in lane_ids:
        samples = []
        for entry in plan:
            if entry["arm"] != "P":
                continue
            record = slot_records[entry["slot"]]
            lane = next(item for item in record["lanes"] if item["id"] == lane_id)
            for engine_ns, stages, counts in zip(
                lane["samples_ns"], lane["stage_samples"], lane["counter_samples"]
            ):
                samples.append(
                    decompose_sample(
                        engine_ns, stages, counts, lane["observed_total_hits"]
                    )
                )
        if not samples:
            raise D0Invalid("D0_STAGES", f"no P samples for {lane_id}")
        summary = {}
        for category in EXCLUSIVE_CATEGORIES:
            values = sorted(sample[category] for sample in samples)
            shares = sorted(
                (sample[category] / sample_engine)
                for sample, sample_engine in zip(samples, [
                    sum(sample.values()) for sample in samples
                ])
            )
            summary[category] = {
                "median_ns": values[(len(values) * 50 + 99) // 100 - 1],
                "median_share": shares[(len(shares) * 50 + 99) // 100 - 1],
                "p95_ns": values[(len(values) * 95 + 99) // 100 - 1],
            }
        lanes[lane_id] = summary
    return lanes


def rank_hypotheses(stage_lanes: dict, protocol: dict) -> dict:
    lane_medium = "pr15d_v1/100000/medium/k100"
    lane_common = "pr15d_v1/100000/common/k100"
    lane_common_k10 = "pr15d_v1/100000/common/k10"
    lane_absent = "pr15d_v1/100000/absent/k100"
    lane_rare = "pr15d_v1/100000/rare/k100"

    def hypothesis_value(lane_id: str, category: str) -> int:
        if category == "other_ns":
            return (
                stage_lanes[lane_id]["other_ns"]["median_ns"]
                + stage_lanes[lane_id]["eval_residual_ns"]["median_ns"]
            )
        return stage_lanes[lane_id][category]["median_ns"]

    def hypothesis_share(lane_id: str, category: str) -> float:
        if category == "other_ns":
            return (
                stage_lanes[lane_id]["other_ns"]["median_share"]
                + stage_lanes[lane_id]["eval_residual_ns"]["median_share"]
            )
        return stage_lanes[lane_id][category]["median_share"]

    register = []
    for index, (hypothesis_id, category) in enumerate(HYPOTHESES):
        register.append(
            {
                "id": hypothesis_id,
                "category": category,
                "order": index,
                "medium_k100_ns": hypothesis_value(lane_medium, category),
                "common_k100_ns": hypothesis_value(lane_common, category),
                "common_k10_ns": hypothesis_value(lane_common_k10, category),
                "absent_k100_ns": hypothesis_value(lane_absent, category),
                "rare_k100_ns": hypothesis_value(lane_rare, category),
                "possible_scope": any(
                    hypothesis_share(lane, category) >= 0.20
                    for lane in (lane_medium, lane_common, lane_common_k10, lane_absent, lane_rare)
                ),
            }
        )
    # H-OTHER combines other + eval_residual; its category is a marker only.
    primary = sorted(register, key=lambda item: (-item["common_k100_ns"], item["order"]))
    absent = sorted(register, key=lambda item: (-item["absent_k100_ns"], item["order"]))
    rare = sorted(register, key=lambda item: (-item["rare_k100_ns"], item["order"]))
    return {
        "primary": [item["id"] for item in primary],
        "absent": [item["id"] for item in absent],
        "rare": [item["id"] for item in rare],
        "register": register,
        "other_tops": primary[0]["id"] == "H-OTHER",
    }


# ---------------------------------------------------------------------------
# PR15D helper loading, corpora and environment
# ---------------------------------------------------------------------------


def load_pr15d(checkout_root: str):
    path = os.path.join(checkout_root, "benchmarks/pr15d/harness/run.py")
    if not os.path.isfile(path):
        raise D0Error("D0_PR15D", f"missing PR15D harness at {path}")
    spec = importlib.util.spec_from_file_location("pr15d_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_sibling(name: str):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"pr15i_d0_{name}", path)
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
        raise D0Invalid(
            "D0_CORPUS",
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
                data = open(path, "rb").read()
                if data[:8] != magic:
                    raise D0Invalid("D0_INDEX_FORMAT", f"not a segment: {relative}")
                trailer = len(data) - 64
                footer_offset = struct.unpack_from("<Q", data, trailer + 8)[0]
                footer_len = struct.unpack_from("<Q", data, trailer + 16)[0]
                section_count = struct.unpack_from("<I", data, trailer + 24)[0]
                cursor = footer_offset
                if struct.unpack_from("<H", data, cursor)[0] != 1:
                    raise D0Invalid("D0_INDEX_FORMAT", "bad segment footer")
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
                    raise D0Invalid("D0_INDEX_FORMAT", "footer length mismatch")
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
        raise D0Error("D0_WRITE_EXISTS", f"index directory already exists: {index_dir}")
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
        raise D0Invalid("D0_INDEX_BUILD", f"document count verification failed for {index_dir}")
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
    for arm in ("A", "QP"):
        if arm not in layout["builds"]:
            failures.append({"arm": arm, "gate": "MISSING_ARM"})
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
        raise D0Blocked("D0_AFFINITY", f"need at least two allowed CPUs, found {cpus}")
    if shutil.which("taskset") is None:
        raise D0Blocked("D0_AFFINITY", "taskset is not available")
    return cpus[1], cpus[0]


def pin_controller(controller_cpu: int) -> None:
    os.sched_setaffinity(0, {controller_cpu})
    if sorted(os.sched_getaffinity(0)) != [controller_cpu]:
        raise D0Blocked("D0_AFFINITY", "controller affinity could not be pinned")


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
    allowed = _cpus_allowed_list(process.process.pid)
    if allowed != [adapter_cpu]:
        process.close()
        raise D0Blocked(
            "D0_AFFINITY",
            f"adapter pid {process.process.pid} affinity {allowed} != [{adapter_cpu}]",
        )
    return process


def contention_probe(pr15d_module, path: str) -> dict:
    record = pr15d_module.check_contention(path)
    if record.get("state") != "clear" or record.get("reason_codes") not in ([], None):
        raise D0Blocked(
            "D0_CONTENTION", f"contention probe not clear: {json.dumps(record, sort_keys=True)}"
        )
    return record


# ---------------------------------------------------------------------------
# Build subcommand
# ---------------------------------------------------------------------------


def _build_binary_path(root: str, arm: str) -> str:
    return os.path.join(
        root, "target", "pr15i-d0", "build", arm, "release", ADAPTER_BINARY_NAME
    )


def _build_meta_path(root: str, arm: str) -> str:
    return os.path.join(root, "target", "pr15i-d0", "build", arm, "build.json")


def cargo_build(root: str, arm: str, features: list[str] | None) -> dict:
    target_dir = os.path.join(root, "target", "pr15i-d0", "build", arm)
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
        raise D0Blocked(
            "D0_BUILD",
            f"{arm} adapter build failed ({result.returncode}): {result.stdout[-4000:]}",
        )
    binary = _build_binary_path(root, arm)
    if not os.path.isfile(binary):
        raise D0Blocked("D0_BUILD", f"{arm} binary missing at {binary}")
    metadata = {
        "schema": "pr15i-d0-build-v1",
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
    checkout_root = confined_root(args.checkout_root, "checkout-root")
    instrumented_root = confined_root(args.instrumented_root, "instrumented-root")
    out = confined(TARGET_ROOT, args.out, "--out")
    protocol, protocol_sha = load_protocol()
    if _git(checkout_root, "rev-parse", "HEAD") != BASE_SHA:
        raise D0Invalid("D0_SOURCE", "checkout-root is not at BASE")
    if _git(checkout_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise D0Invalid("D0_SOURCE", "checkout-root is not clean")

    patcher = load_sibling("patch_instrumented_source")
    proof_module = load_sibling("source_proof")
    # A derives from pristine BASE; QP derives from the materialized scratch tree.
    os.makedirs(out, exist_ok=True)
    derivation_path = os.path.join(
        instrumented_root, "target", "pr15i-d0", "build", "QP", "source-derivation.json"
    )
    derivation = patcher.materialize(instrumented_root, derivation_path)
    proof = proof_module.prove(checkout_root, instrumented_root)
    if proof["derivative_fingerprint_sha256"] != derivation["derivative_fingerprint_sha256"]:
        raise D0Invalid("D0_SOURCE", "materializer and independent proof disagree")

    a_build = cargo_build(checkout_root, "A", None)
    qp_build = cargo_build(instrumented_root, "QP", [f"quervant-core/{FEATURE}"])
    if a_build["binary_sha256"] == qp_build["binary_sha256"]:
        raise D0Invalid("D0_BUILD", "A and Q/P binaries are identical")

    record = {
        "schema": "pr15i-d0-series-build-v1",
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
        raise D0Error("D0_PATH", f"{label} is not a directory: {candidate}")
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
        raise D0Invalid("D0_GIT", f"git {' '.join(args)}: {result.stdout.strip()}")
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
        raise D0Invalid("D0_REQUEST_ID", f"{request_id}: response id mismatch")
    engine_ns = response.get("engine_ns")
    if isinstance(engine_ns, bool) or not isinstance(engine_ns, int) or engine_ns <= 0:
        raise D0Invalid("D0_DURATION", f"{lane['id']}: invalid engine_ns {engine_ns!r}")
    if response.get("total_hits") != expected["total_hits"]:
        raise D0Invalid("D0_ORACLE", f"{lane['id']}: total_hits mismatch")
    if response.get("doc_ids") != expected["doc_ids"]:
        raise D0Invalid("D0_ORACLE", f"{lane['id']}: doc_ids differ from oracle")


def _stage_pairs_to_arrays(pairs):
    if not isinstance(pairs, list) or len(pairs) != len(STAGE_LABELS):
        raise D0Invalid("D0_STAGES", "stage_ns is not a ten-pair array")
    names = [pair[0] for pair in pairs]
    if names != STAGE_LABELS:
        raise D0Invalid("D0_STAGES", "stage labels are missing, reordered or duplicated")
    values = []
    for name, value in pairs:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise D0Invalid("D0_STAGES", f"stage {name} has invalid value {value!r}")
        values.append(value)
    return values


def _counter_pairs_to_arrays(pairs):
    if not isinstance(pairs, list) or len(pairs) != len(COUNTER_LABELS):
        raise D0Invalid("D0_COUNTERS", "counts is not a three-pair array")
    names = [pair[0] for pair in pairs]
    if names != COUNTER_LABELS:
        raise D0Invalid("D0_COUNTERS", "counter labels are missing, reordered or duplicated")
    values = []
    for name, value in pairs:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise D0Invalid("D0_COUNTERS", f"counter {name} has invalid value {value!r}")
        values.append(value)
    return values


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
):
    process = launch_pinned(pr15d_module, adapter_cpu, binary, index_dir)
    try:
        for warmup in range(pmap["warmups_per_lane_slot"]):
            request_id = f"{address}:warmup-{warmup:02d}"
            payload = {
                "request_id": request_id,
                "op": pmap["arm_operations"][arm],
                **_lane_query(lane),
            }
            response = process.request(payload)
            _validate_response(response, lane, expected, request_id)
        samples = []
        stage_samples = []
        counter_samples = []
        observed_hits = expected["total_hits"]
        observed_ids = expected["doc_ids"]
        for sample in range(pmap["samples_per_lane_slot"]):
            request_id = f"{address}:sample-{sample:02d}"
            payload = {
                "request_id": request_id,
                "op": pmap["arm_operations"][arm],
                **_lane_query(lane),
            }
            response = process.request(payload)
            _validate_response(response, lane, expected, request_id)
            observed_hits = response["total_hits"]
            observed_ids = response["doc_ids"]
            samples.append(response["engine_ns"])
            if arm == "P":
                if "stage_ns" not in response or "counts" not in response:
                    raise D0Invalid("D0_STAGES", f"{request_id}: P is missing stage_ns/counts")
                stage_samples.append(_stage_pairs_to_arrays(response["stage_ns"]))
                counter_samples.append(_counter_pairs_to_arrays(response["counts"]))
            else:
                if "stage_ns" in response or "counts" in response:
                    raise D0Invalid("D0_MODE", f"{request_id}: {arm} carries probe-only fields")
    finally:
        process.close()
    return {
        "id": lane["id"],
        "warmups": pmap["warmups_per_lane_slot"],
        "samples_ns": samples,
        "expected_total_hits": expected["total_hits"],
        "observed_total_hits": observed_hits,
        "doc_ids": observed_ids,
        "stage_samples": stage_samples if arm == "P" else None,
        "counter_samples": counter_samples if arm == "P" else None,
    }


def run_campaign(args) -> int:
    checkout_root = confined_root(args.checkout_root, "checkout-root")
    instrumented_root = confined_root(args.instrumented_root, "instrumented-root")
    out = confined(TARGET_ROOT, args.out, "--out")
    protocol, protocol_sha = load_protocol()
    if args.campaign not in protocol["campaigns"]:
        raise D0Invalid("D0_CAMPAIGN", f"unknown campaign {args.campaign}")
    if not args.idle_confirmed:
        raise D0Blocked("D0_IDLE", "--idle-confirmed is required")
    if os.path.exists(out):
        raise D0Error("D0_WRITE_EXISTS", f"campaign directory already exists: {out}")
    os.makedirs(out)
    raw = os.path.join(out, "raw")
    slots_dir = os.path.join(raw, "slots")
    setup = os.path.join(out, "setup")
    contention_dir = os.path.join(setup, "contention")
    for directory in (raw, slots_dir, contention_dir):
        os.makedirs(directory, exist_ok=True)

    if _git(checkout_root, "rev-parse", "HEAD") != BASE_SHA:
        raise D0Invalid("D0_SOURCE", "checkout-root is not at BASE")
    if _git(checkout_root, "status", "--porcelain", "--untracked-files=all"):
        raise D0Invalid("D0_SOURCE", "checkout-root is not clean")

    pr15d = load_pr15d(checkout_root)
    oracle = pr15d.oracle
    a_meta = read_json(_build_meta_path(checkout_root, "A"))
    qp_meta = read_json(_build_meta_path(instrumented_root, "QP"))
    if a_meta["binary_sha256"] == qp_meta["binary_sha256"]:
        raise D0Invalid("D0_BUILD", "A and Q/P binary digests are identical")
    for meta in (a_meta, qp_meta):
        if sha256_file(meta["binary"]) != meta["binary_sha256"]:
            raise D0Invalid("D0_BUILD", f"binary hash changed: {meta['binary']}")
    derivation = read_json(
        os.path.join(instrumented_root, "target", "pr15i-d0", "build", "QP", "source-derivation.json")
    )
    proof = load_sibling("source_proof").prove(checkout_root, instrumented_root)
    if proof["derivative_fingerprint_sha256"] != derivation["derivative_fingerprint_sha256"]:
        raise D0Invalid("D0_SOURCE", "independent source proof disagrees with derivation")

    controller_cpu, adapter_cpu = affinity_plan()
    pin_controller(controller_cpu)

    corpus_dir = confined(TARGET_ROOT, os.path.join(TARGET_ROOT, "corpus-src"), "corpus")
    corpus = ensure_corpus(pr15d, corpus_dir, protocol)
    lanes = lane_descriptors(protocol)
    plan = slot_plan(protocol)

    environment = collect_environment()
    if not environment["native_filesystem"]:
        raise D0Blocked(
            "D0_FILESYSTEM",
            f"non-native filesystem {environment['filesystem']!r}",
        )

    # Index builds: A/10K, A/100K, QP/10K, QP/100K.
    builds = {"A": {}, "QP": {}}
    for arm, meta in (("A", a_meta), ("QP", qp_meta)):
        for n in (10000, 100000):
            corpus_path = os.path.join(corpus_dir, oracle.corpus_filename(n))
            index_dir = os.path.join(setup, "indexes", arm, str(n))
            build_one_index(pr15d, meta["binary"], corpus_path, index_dir, n)
            builds[arm][str(n)] = measure_index_layout(index_dir)
    layout = {"schema": "pr15i-d0-index-layout-v1", "builds": builds}
    layout_failures = index_sentinel_failures(layout, protocol)
    if layout_failures:
        raise D0Invalid(
            "D0_INDEX_FORMAT", json.dumps(layout_failures, sort_keys=True)
        )

    source_inventory = {
        relative: {
            "base_sha256": sha256_file(os.path.join(checkout_root, relative)),
            "derivative_sha256": sha256_file(os.path.join(instrumented_root, relative)),
        }
        for relative in DERIVATIVE_FILES
    }
    diagnostic_fingerprint = sha256_bytes(
        canonical_json_bytes(
            {
                relative: source_inventory[relative]["derivative_sha256"]
                for relative in DERIVATIVE_FILES
            }
        )
    )
    binary_record = {
        "schema": "pr15i-d0-binaries-v1",
        "A": {"path": a_meta["binary"], "sha256": a_meta["binary_sha256"]},
        "QP": {"path": qp_meta["binary"], "sha256": qp_meta["binary_sha256"]},
        "q_and_p_exact_same_binary": True,
    }
    authorization = {
        "schema": "pr15i-d0-authorization-v1",
        "campaign": args.campaign,
        "base_sha": BASE_SHA,
        "protocol_sha256": protocol_sha,
        "checkout_head": _git(checkout_root, "rev-parse", "HEAD"),
        "checkout_branch": _git(checkout_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "instrumented_head": _git(instrumented_root, "rev-parse", "HEAD"),
        "idle_confirmed": True,
        "controller_cpu": controller_cpu,
        "adapter_cpu": adapter_cpu,
    }
    toolchains = environment["toolchains"]
    sources = {
        "schema": "pr15i-d0-sources-v1",
        "base_sha": BASE_SHA,
        "protocol_sha256": protocol_sha,
        "tooling": {
            relative: sha256_file(os.path.join(TOOLING_ROOT, relative))
            for relative in (
                "benchmarks/pr15i_d0/patch_instrumented_source.py",
                "benchmarks/pr15i_d0/source_proof.py",
                "benchmarks/pr15i_d0/run.py",
                "benchmarks/pr15i_d0/verify.py",
                "benchmarks/pr15i_d0/protocol_v1.json",
            )
        },
        "source_inventory": source_inventory,
        "diagnostic_derivative_sha256": diagnostic_fingerprint,
        "source_proof": proof,
        "permitted_diff_paths": list(DERIVATIVE_FILES),
        "source_derivation_sha256": sha256_bytes(canonical_json_bytes(derivation)),
    }
    corpus_record = {
        "schema": "pr15i-d0-corpus-v1",
        "manifest_sha256": corpus["digest"],
        "files": corpus["manifest"]["corpora"],
        "queries": corpus["manifest"]["queries"],
    }
    oracle_record = {
        "schema": "pr15i-d0-oracle-v1",
        "lanes": {},
    }
    for lane in lanes:
        expected = oracle.expected(
            corpus["rows_by_n"][lane["n"]], lane["field"], lane["term"], lane["k"]
        )
        oracle_record["lanes"][lane["id"]] = expected

    for name, value in (
        ("authorization.json", authorization),
        ("environment.json", environment | {"host_fingerprint": host_fingerprint(environment)}),
        ("toolchains.json", toolchains),
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
        meta = a_meta if arm == "A" else qp_meta
        before_path = os.path.join(contention_dir, f"slot-{slot:02d}-before.json")
        after_path = os.path.join(contention_dir, f"slot-{slot:02d}-after.json")
        contention_probe(pr15d, before_path)
        lanes_out = []
        for lane in lanes:
            index_dir = os.path.join(setup, "indexes", arm, str(lane["n"]))
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
                )
            )
        contention_probe(pr15d, after_path)
        record = {
            "schema": "pr15i-d0-slot-v1",
            "slot": slot,
            "block": entry["block"],
            "position": entry["position"],
            "arm": arm,
            "base_sha": BASE_SHA,
            "diagnostic_derivative_sha256": (
                None if arm == "A" else diagnostic_fingerprint
            ),
            "binary_sha256": sha256_file(meta["binary"]),
            "index_sha256": sha256_bytes(
                canonical_json_bytes(
                    {
                        n: builds[arm][n]["digest"] for n in ("10000", "100000")
                    }
                )
            ),
            "lane_ids": protocol["lane_ids"],
            "lanes": lanes_out,
            "contention_before": "clear",
            "contention_after": "clear",
        }
        slot_records[slot] = record
        write_json_exclusive(os.path.join(slots_dir, f"slot-{slot:02d}.json"), record)

    timing = compute_timing(slot_records, protocol)
    status, failures = classify_timing(timing, protocol)
    timing["status"] = status
    timing["failures"] = failures
    mode_proof = {
        "schema": "pr15i-d0-mode-proof-v1",
        "q_and_p_same_binary": True,
        "q_slots": [
            entry["slot"] for entry in plan if entry["arm"] == "Q"
        ],
        "p_slots": [
            entry["slot"] for entry in plan if entry["arm"] == "P"
        ],
        "q_lacks_probe_fields": True,
        "p_carries_probe_fields": True,
    }
    write_json_exclusive(os.path.join(raw, "mode-proof.json"), mode_proof)
    write_json_exclusive(os.path.join(raw, "timing.json"), timing)
    seal_campaign(out)
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


def required_members() -> list[str]:
    members = list(RAW_MEMBERS)
    members.extend(f"raw/slots/slot-{slot:02d}.json" for slot in range(1, 25))
    for slot in range(1, 25):
        members.append(f"setup/contention/slot-{slot:02d}-before.json")
        members.append(f"setup/contention/slot-{slot:02d}-after.json")
    return members


def seal_campaign(campaign_dir: str) -> dict:
    campaign_dir = confined(TARGET_ROOT, campaign_dir, "campaign-dir")
    seal_path = os.path.join(campaign_dir, "raw", "seal.json")
    manifest_path = os.path.join(campaign_dir, "raw", "manifest.json")
    if os.path.exists(seal_path):
        raise D0Error("D0_SEALED", f"campaign is already sealed: {campaign_dir}")
    members = required_members()
    missing = [path for path in members if not os.path.isfile(os.path.join(campaign_dir, path))]
    if missing:
        raise D0Blocked("D0_SEAL", f"missing required members: {missing}")
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
        "schema": "pr15i-d0-manifest-v1",
        "campaign": os.path.basename(campaign_dir),
        "base_sha": BASE_SHA,
        "expected": {
            "slots": 24,
            "blocks": 4,
            "slots_per_block": 6,
            "lanes_per_slot": 9,
            "samples_per_lane_slot": 20,
            "warmups_per_lane_slot": 5,
            "timed_observations": 4320,
            "warmups": 1080,
            "contention_probes": 48,
            "index_builds": 4,
            "p_stage_samples": 1440,
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
        "schema": "pr15i-d0-seal-v1",
        "campaign": os.path.basename(campaign_dir),
        "members": {entry["path"]: entry["sha256"] for entry in sealed},
    }
    write_json_exclusive(seal_path, seal)
    return seal


# ---------------------------------------------------------------------------
# Preflight / source proof CLI
# ---------------------------------------------------------------------------


def preflight(args) -> int:
    checkout_root = confined_root(args.checkout_root, "checkout-root")
    out = confined(TARGET_ROOT, args.out, "--out")
    protocol, protocol_sha = load_protocol()
    blockers = []
    head = _git(checkout_root, "rev-parse", "HEAD")
    clean = _git(checkout_root, "status", "--porcelain", "--untracked-files=all") == ""
    if head != BASE_SHA:
        raise D0Invalid("D0_SOURCE", f"checkout HEAD {head} != {BASE_SHA}")
    if not clean:
        raise D0Invalid("D0_SOURCE", "checkout tree is not clean")
    environment = collect_environment()
    if not environment["native_filesystem"]:
        blockers.append("NON_NATIVE_FILESYSTEM")
    pr15d = load_pr15d(checkout_root)
    corpus_dir = confined(TARGET_ROOT, os.path.join(TARGET_ROOT, "corpus-src"), "corpus")
    corpus = ensure_corpus(pr15d, corpus_dir, protocol)
    artifacts = {}
    for relative in SOURCE_ARTIFACTS:
        if relative.startswith("benchmarks/pr15i_d0/"):
            path = os.path.join(TOOLING_ROOT, relative)
        else:
            path = os.path.join(checkout_root, relative)
        if not os.path.isfile(path):
            artifacts[relative] = None
            blockers.append(f"MISSING_SOURCE:{relative}")
        else:
            artifacts[relative] = sha256_file(path)
    record = {
        "schema": "pr15i-d0-preflight-v1",
        "base_sha": BASE_SHA,
        "checkout_head": head,
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
    checkout_root = confined_root(args.checkout_root, "checkout-root")
    instrumented_root = confined_root(args.instrumented_root, "instrumented-root")
    out = confined(TARGET_ROOT, args.out, "--out")
    proof = load_sibling("source_proof").prove(checkout_root, instrumented_root)
    write_json_exclusive(out, proof)
    print(canonical_json_bytes(proof).decode("utf-8"))
    return 0


def seal_cli(args) -> int:
    seal = seal_campaign(args.campaign_dir)
    print(canonical_json_bytes(seal).decode("utf-8"))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PR 15I-D0 attribution controller.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_preflight = subparsers.add_parser("preflight")
    p_preflight.add_argument("--checkout-root", required=True)
    p_preflight.add_argument("--out", required=True)
    p_preflight.set_defaults(handler=preflight)

    p_source = subparsers.add_parser("source-proof")
    p_source.add_argument("--checkout-root", required=True)
    p_source.add_argument("--instrumented-root", required=True)
    p_source.add_argument("--out", required=True)
    p_source.set_defaults(handler=source_proof_cli)

    p_build = subparsers.add_parser("build")
    p_build.add_argument("--checkout-root", required=True)
    p_build.add_argument("--instrumented-root", required=True)
    p_build.add_argument("--out", required=True)
    p_build.set_defaults(handler=run_build)

    p_campaign = subparsers.add_parser("campaign")
    p_campaign.add_argument("--checkout-root", required=True)
    p_campaign.add_argument("--instrumented-root", required=True)
    p_campaign.add_argument("--campaign", required=True, choices=["unbatched-01", "unbatched-02"])
    p_campaign.add_argument("--out", required=True)
    p_campaign.add_argument("--idle-confirmed", action="store_true")
    p_campaign.set_defaults(handler=run_campaign)

    p_seal = subparsers.add_parser("seal")
    p_seal.add_argument("--campaign-dir", required=True)
    p_seal.set_defaults(handler=seal_cli)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except D0Blocked as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 3
    except D0Invalid as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 2
    except D0Error as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Independent verifier for PR 15I-D3-A candidate/intermediate attribution evidence.

The verifier recomputes every derived value from sealed raw samples and the
frozen protocol.  It does not import the controller's ratio, stability,
classification or stage-summary functions and it does not trust
``raw/timing.json``, ``raw/oracle.json``, ``raw/sources.json`` or
``raw/mode-proof.json`` as evidence.  Only the independent PR15D corpus oracle
and the immutable protocol are common reference inputs.

Exit codes: ``0`` VERIFIED, ``2`` INVALID, ``3`` BLOCKED/INCOMPLETE.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from fractions import Fraction

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET_ROOT = os.path.join(TOOLING_ROOT, "target", "pr15i-d3a")

BASE_SHA = "409fb0fdf370bb4d4dade5ea507c6fa4518b5220"
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
CLASS_TERMS = {
    "absent": ("key", "never"),
    "rare": ("key", "singleton"),
    "medium": ("group", "medium"),
    "common": ("key", "common"),
}
EXCLUSIVE = [
    "plan_ns",
    "reader_live_ns",
    "expand_ns",
    "stats_ns",
    "leaf_decode_ns",
    "membership_ns",
    "score_vector_ns",
    "matched_reserve_ns",
    "temp_release_ns",
    "eval_residual_ns",
    "candidate_ns",
    "projection_ns",
    "other_ns",
]
RAW_MEMBERS = [
    "raw/authorization.json",
    "raw/host-quiescence.json",
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
DERIVATIVE_FILES = (
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/mod.rs",
    "crates/quervant-core/src/search/d3a_probe.rs",
    "crates/quervant-core/Cargo.toml",
    "benchmarks/pr15d/adapters/quervant/src/main.rs",
)
EXISTING_FILES = (
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/mod.rs",
    "crates/quervant-core/Cargo.toml",
    "benchmarks/pr15d/adapters/quervant/src/main.rs",
)

EXPECTED_PROTOCOL = {'100k_lz4_committed_index_sentinel': 15747551,
 '100k_lz4_stored_section_sentinel': 1661455,
 'a_a_drift_median_max': 1.15,
 'a_a_drift_median_min': 0.85,
 'a_a_max_outlier_blocks_per_lane': 1,
 'a_a_outlier_block_high': 1.25,
 'a_a_outlier_block_low': 0.8,
 'a_a_outlier_hard_high': 1.5,
 'a_a_outlier_hard_low': 0.67,
 'adapter_process_lifetime': 'ONE_PROCESS_PER_ARM_LANE_SLOT',
 'archive_excludes': ['build/', 'indexes/', 'corpus/', 'sources/'],
 'archive_root_relative': 'benchmark-evidence/pr15i-d3a',
 'arm_operations': {'A': 'query', 'P': 'query_probe', 'Q': 'query'},
 'arm_order_by_block': ['AQPPQA', 'PQAAQP', 'QAPPAQ', 'PAQQAP'],
 'arm_slots_per_block': 2,
 'arms': ['A', 'Q', 'P'],
 'base_sha': '409fb0fdf370bb4d4dade5ea507c6fa4518b5220',
 'blocks_per_campaign': 4,
 'campaigns': ['d3af2-unbatched-01',
               'd3af2-unbatched-02',
               'd3af2-unbatched-03',
               'd3af2-unbatched-04',
               'd3af2-unbatched-05'],
 'candidate_first_samples': 128,
 'candidate_priority': {'candidate_min_ns': 3000000,
                        'candidate_min_share': 0.12,
                        'dominant_max_residual_share': 0.3,
                        'dominant_min_steady_share': 0.25,
                        'dominant_runner_up_ratio': 1.25,
                        'lanes': ['pr15d_v1/100000/medium/k100',
                                  'pr15d_v1/100000/common/k100',
                                  'pr15d_v1/100000/common/k10'],
                        'required_campaigns': 5,
                        'required_qualifying_lanes_per_campaign': 2},
 'candidate_sample_children': 7,
 'candidate_sample_min_n': 512,
 'candidate_sample_partition_overhead_share': 0.05,
 'candidate_steady_stride': 64,
 'contention_probes_per_slot': 2,
 'control_arm_order_by_block': ['A1A2A2A1', 'A2A1A1A2', 'A1A2A2A1', 'A2A1A1A2'],
 'control_arm_slots_per_block': 2,
 'control_blocks': 4,
 'control_campaign': 'd3af2-base-aa-01',
 'control_retry_campaign': 'd3af2-base-aa-02',
 'control_slots_per_block': 4,
 'control_slots_per_campaign': 16,
 'control_soft_outlier_lane_ids': ['pr15d_v1/10000/absent/k100', 'pr15d_v1/10000/rare/k100'],
 'control_soft_outlier_max_per_lane': 1,
 'corpus_manifest_sha256': '69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151',
 'counters': ['matched_docs',
              'scored_docs',
              'candidate_docs',
              'bm25_calls',
              'scoring_map_entries',
              'positive_term_owners',
              'candidate_samples_first',
              'candidate_samples_steady',
              'candidate_samples_fast',
              'candidate_samples_fallback',
              'candidate_samples_insert',
              'candidate_samples_replace',
              'candidate_samples_reject',
              'match_insert_samples',
              'candidate_samples_key'],
 'diagnostic_only': True,
 'index_builds_per_control_campaign': 2,
 'index_builds_per_paired_campaign': 4,
 'intermediate_priority': {'lanes': ['pr15d_v1/100000/medium/k100',
                                     'pr15d_v1/100000/common/k100',
                                     'pr15d_v1/100000/common/k10'],
                           'min_disjoint_ns': 3000000,
                           'min_disjoint_share': 0.1,
                           'required_campaigns': 5,
                           'required_qualifying_lanes_per_campaign': 2},
 'lane_ids': ['pr15d_v1/10000/absent/k100',
              'pr15d_v1/10000/rare/k100',
              'pr15d_v1/10000/medium/k100',
              'pr15d_v1/10000/common/k100',
              'pr15d_v1/100000/absent/k100',
              'pr15d_v1/100000/rare/k100',
              'pr15d_v1/100000/medium/k100',
              'pr15d_v1/100000/common/k100',
              'pr15d_v1/100000/common/k10'],
 'match_insert_min_n': 128,
 'match_insert_stride': 64,
 'max_completed_control_attempts': 2,
 'max_segment_descriptors': 32,
 'measurement_family': 'D3AF2_FIVE_PAIRED_LANE_SCOPED',
 'p_q_ratio_ceiling_low_match': 1.25,
 'p_q_ratio_ceiling_medium_common': 1.15,
 'q_a_ratio_ceiling_low_match': 1.15,
 'q_a_ratio_ceiling_medium_common': 1.1,
 'q_and_p_exact_same_binary': True,
 'required_affinity': 'CONTROLLER_SECOND_ALLOWED_CPU_ADAPTER_FIRST_ALLOWED_CPU',
 'required_native_filesystem': ['ext4', 'xfs', 'btrfs'],
 'run_mad_warning_relative': 0.25,
 'run_reported_areas': ['document_key',
                        'duplicate_detection',
                        'sort_extraction',
                        'heap_compare_update',
                        'candidate_materialization',
                        'match_set_construction',
                        'scored_map_vector'],
 'sample_strata_children': 8,
 'sample_strata_count': 2,
 'samples_per_lane_slot': 20,
 'schema': 'pr15i-d3a-candidate-attribution-lane-scoped-v3',
 'series_min_consistent_runs': 4,
 'single_block_guard_ceiling': 1.5,
 'slots_per_block': 6,
 'slots_per_campaign': 24,
 'source_derivation': 'DIAGNOSTIC_INSERTION_ONLY_FROM_BASE',
 'stage_partition_max_violation_fraction': 0.01,
 'stage_partition_overhead_abs_ns': 10000,
 'stage_partition_overhead_share': 0.02,
 'stages': ['plan_ns',
            'reader_live_ns',
            'expand_ns',
            'stats_ns',
            'evaluate_ns',
            'candidate_ns',
            'projection_ns',
            'leaf_decode_ns',
            'membership_ns',
            'score_vector_ns',
            'score_map_ns',
            'score_owner_ns',
            'score_accumulate_ns',
            'matched_reserve_ns',
            'scored_vec_build_ns',
            'temp_release_ns',
            'match_insert_sample_ns',
            'candidate_sample_ns',
            'candidate_key_ns',
            'candidate_sort_view_ns',
            'candidate_sort_charge_ns',
            'candidate_duplicate_ns',
            'candidate_compare_ns',
            'candidate_materialize_ns',
            'candidate_heap_ns'],
 'study_type': 'CANDIDATE_INTERMEDIATE_ATTRIBUTION',
 'timed_sample_unit': 'single_query_engine_ns',
 'warmups_per_lane_slot': 5,
 'lane_scoped_paired_qualification': True,
 'lane_scoped_min_eligible_runs': 4,
 'lane_scoped_primary_min_lanes': 2,
 'lane_scoped_joint_min_runs': 4,
 'lane_scoped_excluded_run_policy': 'WHOLE_LANE_RUN_EXCLUDED',
 'lane_scoped_global_integrity_policy': 'ANY_NON_TIMING_INVARIANT_FAILURE_BLOCKS_CAMPAIGN',
 'lane_scoped_statistic_policy': 'MEDIAN_LOWER_AND_MAD_LOWER_ON_ELIGIBLE_RUNS',
 'lane_scoped_report_all_nine_lanes': True}

class VerifyError(Exception):
    def __init__(self, status: str, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail


def invalid(code: str, detail: str) -> VerifyError:
    return VerifyError("INVALID", code, detail)


def blocked(code: str, detail: str) -> VerifyError:
    return VerifyError("BLOCKED", code, detail)


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


def load_tooling_manifest() -> dict:
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3a/tooling_manifest_v3.json")
    try:
        manifest = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_TOOLING", f"cannot read v2 tooling manifest: {error}") from error
    if manifest.get("schema") != "pr15i-d3a-tooling-manifest-v3":
        raise invalid("V_TOOLING", "unexpected v2 tooling manifest schema")
    if manifest.get("base_sha") != BASE_SHA:
        raise invalid("V_TOOLING", "v2 tooling manifest BASE differs")
    if manifest.get("protocol_schema") != "pr15i-d3a-candidate-attribution-lane-scoped-v3":
        raise invalid("V_TOOLING", "v2 tooling manifest protocol schema differs")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise invalid("V_TOOLING", "v2 tooling manifest has no files")
    directory = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3a")
    excluded = {"tooling_manifest.json", "tooling_manifest_v2.json", "tooling_manifest_v3.json"}
    actual = set()
    for name in os.listdir(directory):
        full = os.path.join(directory, name)
        if os.path.islink(full):
            raise invalid("V_TOOLING", f"v2 tooling directory contains a symlink: {name}")
        if os.path.isfile(full) and name not in excluded and not name.startswith("__pycache__"):
            actual.add(name)
    if set(files) != actual:
        raise invalid(
            "V_TOOLING",
            f"v2 tooling manifest file set differs: {sorted(set(files) ^ actual)}",
        )
    for relative, digest in files.items():
        safe_member(relative)
        full = os.path.join(directory, relative)
        if not os.path.isfile(full) or os.path.islink(full):
            raise invalid("V_TOOLING", f"v2 tooling member is unavailable: {relative}")
        if sha256_file(full) != digest:
            raise invalid("V_TOOLING", f"v2 tooling manifest hash mismatch: {relative}")
    return manifest


def load_protocol() -> dict:
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3a/protocol_v3.json")
    try:
        protocol = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_PROTOCOL", f"cannot read protocol: {error}") from error
    if protocol != EXPECTED_PROTOCOL:
        raise invalid("V_PROTOCOL", "protocol differs from the frozen literal")
    return protocol


def confined(path: str, root: str = TARGET_ROOT, label: str = "path") -> str:
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.abspath(path))
    if candidate == root_real or not candidate.startswith(root_real + os.sep):
        raise invalid("V_PATH", f"{label} escapes {root_real}: {candidate}")
    return candidate


# ---------------------------------------------------------------------------
# Protocol, lanes and schedule
# ---------------------------------------------------------------------------


def parse_lane(lane_id: str) -> dict:
    parts = lane_id.split("/")
    if len(parts) != 4 or parts[0] != "pr15d_v1":
        raise invalid("V_LANE", f"malformed lane id {lane_id!r}")
    class_name = parts[2]
    if class_name not in CLASS_TERMS:
        raise invalid("V_LANE", f"unknown class {class_name!r}")
    if not parts[3].startswith("k") or not parts[3][1:].isdigit():
        raise invalid("V_LANE", f"malformed K in {lane_id!r}")
    n = int(parts[1])
    k = int(parts[3][1:])
    if n not in (10000, 100000) or k <= 0:
        raise invalid("V_LANE", f"unsupported lane {lane_id!r}")
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
        raise invalid("V_LANE", "lane order differs from the protocol")
    return lanes


def slot_schedule(protocol: dict) -> list[dict]:
    plan = []
    orders = protocol["arm_order_by_block"]
    if len(orders) != protocol["blocks_per_campaign"]:
        raise invalid("V_SCHEDULE", "block count mismatch")
    for block, order in enumerate(orders, start=1):
        if len(order) != protocol["slots_per_block"]:
            raise invalid("V_SCHEDULE", f"block {block} slot count mismatch")
        if sorted(order) != ["A", "A", "P", "P", "Q", "Q"]:
            raise invalid("V_SCHEDULE", f"block {block} is not arm-balanced")
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
        raise invalid("V_SCHEDULE", "slot count mismatch")
    return plan


def control_schedule(protocol: dict) -> list[dict]:
    plan = []
    orders = protocol["control_arm_order_by_block"]
    if len(orders) != protocol["control_blocks"]:
        raise invalid("V_SCHEDULE", "control block count mismatch")
    for block, order in enumerate(orders, start=1):
        if len(order) % 2 != 0:
            raise invalid("V_SCHEDULE", f"control block {block} has malformed arms")
        arms = [order[index : index + 2] for index in range(0, len(order), 2)]
        if len(arms) != protocol["control_slots_per_block"]:
            raise invalid("V_SCHEDULE", f"control block {block} slot count mismatch")
        if sorted(arms) != ["A1", "A1", "A2", "A2"]:
            raise invalid("V_SCHEDULE", f"control block {block} is not arm-balanced")
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
        raise invalid("V_SCHEDULE", "control slot count mismatch")
    return plan


def campaign_kind(name: str, protocol: dict) -> str:
    controls = {protocol["control_campaign"], protocol["control_retry_campaign"]}
    if name in controls:
        return "control"
    if name in protocol["campaigns"]:
        return "paired"
    raise invalid("V_CAMPAIGN", f"unknown campaign {name!r}")


# ---------------------------------------------------------------------------
# Oracle (independent of the controller and of PR15D's harness)
# ---------------------------------------------------------------------------


def load_oracle(checkout_root: str):
    path = os.path.join(checkout_root, "benchmarks/pr15d/corpus/oracle.py")
    if not os.path.isfile(path):
        raise blocked("V_ORACLE", f"missing independent corpus oracle: {path}")
    spec = importlib.util.spec_from_file_location("pr15d_oracle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recompute_oracle(oracle, protocol: dict) -> dict:
    temporary = tempfile.mkdtemp(prefix="pr15i-d3a-verify-")
    try:
        for n in oracle.N_VALUES:
            path = os.path.join(temporary, oracle.corpus_filename(n))
            with open(path, "wb") as handle:
                handle.write(oracle.build_tsv_text(n).encode("utf-8"))
        manifest = oracle.build_manifest(temporary)
        digest = oracle.sha256_bytes(oracle.canonical_json_bytes(manifest))
        if digest != protocol["corpus_manifest_sha256"]:
            raise invalid(
                "V_CORPUS",
                f"re-derived corpus manifest {digest} != {protocol['corpus_manifest_sha256']}",
            )
        rows_by_n = {n: oracle.load_tsv(os.path.join(temporary, oracle.corpus_filename(n)), expected_n=n)
                     for n in oracle.N_VALUES}
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    lanes = {}
    for lane in lane_descriptors(protocol):
        lanes[lane["id"]] = oracle.expected(
            rows_by_n[lane["n"]], lane["field"], lane["term"], lane["k"]
        )
    return {"manifest_sha256": digest, "lanes": lanes}


# ---------------------------------------------------------------------------
# Seal and inventory
# ---------------------------------------------------------------------------


def required_members(slot_count: int) -> list[str]:
    members = list(RAW_MEMBERS)
    members.extend(f"raw/slots/slot-{slot:02d}.json" for slot in range(1, slot_count + 1))
    for slot in range(1, slot_count + 1):
        members.append(f"setup/contention/slot-{slot:02d}-before.json")
        members.append(f"setup/contention/slot-{slot:02d}-after.json")
    members.append("setup/host-quiescence-precheck.json")
    return members


def safe_member(relative: str) -> str:
    normalized = relative.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        raise invalid("V_SEAL", f"unsafe seal member path {relative!r}")
    if normalized != os.path.normpath(normalized).replace(os.sep, "/"):
        raise invalid("V_SEAL", f"non-canonical seal member path {relative!r}")
    return normalized


def verify_seal(campaign_dir: str, protocol: dict) -> dict:
    campaign_name = os.path.basename(campaign_dir)
    kind = campaign_kind(campaign_name, protocol)
    if kind == "control":
        slot_count = protocol["control_slots_per_campaign"]
        expected_manifest = {
            "slots": slot_count,
            "timed_observations": slot_count * len(protocol["lane_ids"]) * protocol["samples_per_lane_slot"],
            "warmups": slot_count * len(protocol["lane_ids"]) * protocol["warmups_per_lane_slot"],
            "contention_probes": slot_count * 2,
            "index_builds": protocol["index_builds_per_control_campaign"],
            "p_stage_samples": None,
        }
    else:
        slot_count = protocol["slots_per_campaign"]
        expected_manifest = {
            "slots": slot_count,
            "timed_observations": slot_count * len(protocol["lane_ids"]) * protocol["samples_per_lane_slot"],
            "warmups": slot_count * len(protocol["lane_ids"]) * protocol["warmups_per_lane_slot"],
            "contention_probes": slot_count * 2,
            "index_builds": protocol["index_builds_per_paired_campaign"],
            "p_stage_samples": 8 * len(protocol["lane_ids"]) * protocol["samples_per_lane_slot"],
        }
    seal_path = os.path.join(campaign_dir, "raw", "seal.json")
    if not os.path.isfile(seal_path):
        raise blocked("V_SEAL", "raw/seal.json is missing")
    try:
        seal = read_json(seal_path)
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_SEAL", f"malformed seal: {error}") from error
    if seal.get("schema") != "pr15i-d3a-seal-v1":
        raise invalid("V_SEAL", "unexpected seal schema")
    if seal.get("campaign") != os.path.basename(campaign_dir):
        raise invalid("V_SEAL", "seal campaign name mismatch")
    members = seal.get("members")
    if not isinstance(members, dict):
        raise invalid("V_SEAL", "seal members are not a map")
    if "raw/seal.json" in members:
        raise invalid("V_SEAL", "seal includes itself")
    expected = set(required_members(slot_count)) | {"raw/manifest.json"}
    normalized = {}
    for relative, digest in members.items():
        key = safe_member(relative)
        if not isinstance(digest, str) or len(digest) != 64:
            raise invalid("V_SEAL", f"malformed digest for {relative!r}")
        normalized[key] = digest
    if set(normalized) != expected:
        raise invalid(
            "V_SEAL",
            f"seal member set differs: missing {sorted(expected - set(normalized))}, "
            f"extra {sorted(set(normalized) - expected)}",
        )
    for relative, digest in normalized.items():
        path = os.path.join(campaign_dir, relative)
        if not os.path.isfile(path):
            raise invalid("V_SEAL", f"sealed member is missing: {relative}")
        if sha256_file(path) != digest:
            raise invalid("V_SEAL", f"seal digest mismatch for {relative}")

    listed = set(normalized)
    actual = set()
    for base in ("raw", "setup/contention"):
        root = os.path.join(campaign_dir, base)
        if not os.path.isdir(root):
            continue
        for walk_root, _dirs, files in os.walk(root):
            for name in files:
                relative = os.path.relpath(os.path.join(walk_root, name), campaign_dir)
                actual.add(relative.replace(os.sep, "/"))
    extra = actual - listed - {"raw/seal.json"}
    if extra:
        raise invalid("V_SEAL", f"unlisted raw/contention files: {sorted(extra)}")

    manifest_path = os.path.join(campaign_dir, "raw", "manifest.json")
    try:
        manifest = read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_SEAL", f"malformed manifest: {error}") from error
    if manifest.get("schema") != "pr15i-d3a-manifest-v1":
        raise invalid("V_SEAL", "unexpected manifest schema")
    if manifest.get("base_sha") != BASE_SHA:
        raise invalid("V_SEAL", "manifest BASE differs")
    entries = manifest.get("members")
    if not isinstance(entries, list):
        raise invalid("V_SEAL", "manifest members are not a list")
    manifest_paths = set()
    for entry in entries:
        relative = safe_member(entry.get("path", ""))
        manifest_paths.add(relative)
        path = os.path.join(campaign_dir, relative)
        if not os.path.isfile(path):
            raise invalid("V_SEAL", f"manifest member is missing: {relative}")
        if sha256_file(path) != entry.get("sha256"):
            raise invalid("V_SEAL", f"manifest digest mismatch for {relative}")
        if os.path.getsize(path) != entry.get("size"):
            raise invalid("V_SEAL", f"manifest size mismatch for {relative}")
    if manifest_paths != expected - {"raw/manifest.json"}:
        raise invalid("V_SEAL", "manifest member inventory differs from required set")
    expected_counts = manifest.get("expected", {})
    if (
        expected_counts.get("campaign_kind") != kind
        or expected_counts.get("slots") != expected_manifest["slots"]
        or expected_counts.get("timed_observations") != expected_manifest["timed_observations"]
        or expected_counts.get("warmups") != expected_manifest["warmups"]
        or expected_counts.get("contention_probes") != expected_manifest["contention_probes"]
        or expected_counts.get("index_builds") != expected_manifest["index_builds"]
        or expected_counts.get("p_stage_samples") != expected_manifest["p_stage_samples"]
        or expected_counts.get("stage_labels") != STAGE_LABELS
        or expected_counts.get("counter_labels") != COUNTER_LABELS
    ):
        raise invalid("V_SEAL", "manifest expected counts differ from the protocol")
    return {"seal": seal, "manifest": manifest, "kind": kind, "slot_count": slot_count}


# ---------------------------------------------------------------------------
# Slot validation
# ---------------------------------------------------------------------------


def strict_int(value, label: str, minimum: int | None = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("V_SAMPLE_TYPE", f"{label} is not an integer: {value!r}")
    if minimum is not None and value < minimum:
        raise invalid("V_SAMPLE_DOMAIN", f"{label} is below {minimum}: {value!r}")
    return value


def validate_samples(samples, label: str) -> None:
    if not isinstance(samples, list) or len(samples) != 20:
        raise invalid("V_SAMPLE_COUNT", f"{label} does not contain exactly 20 samples")
    for value in samples:
        strict_int(value, label, 1)


def strict_array(value, length: int, label: str) -> list[int]:
    if not isinstance(value, list) or len(value) != length:
        raise invalid("V_STAGES", f"{label} is not a {length}-element array")
    return [strict_int(item, label, 0) for item in value]


def load_slots(campaign_dir: str, protocol: dict, oracle_lanes: dict) -> dict:
    kind = campaign_kind(os.path.basename(campaign_dir), protocol)
    plan = control_schedule(protocol) if kind == "control" else slot_schedule(protocol)
    records = {}
    for entry in plan:
        path = os.path.join(campaign_dir, "raw", "slots", f"slot-{entry['slot']:02d}.json")
        if not os.path.isfile(path):
            raise blocked("V_SLOT", f"missing slot file {path}")
        try:
            record = read_json(path)
        except (OSError, json.JSONDecodeError) as error:
            raise invalid("V_SLOT", f"malformed slot {entry['slot']}: {error}") from error
        if record.get("schema") != "pr15i-d3a-slot-v1":
            raise invalid("V_SLOT", f"slot {entry['slot']} schema mismatch")
        for field, expected in (
            ("slot", entry["slot"]),
            ("block", entry["block"]),
            ("position", entry["position"]),
            ("arm", entry["arm"]),
        ):
            if record.get(field) != expected:
                raise invalid(
                    "V_SLOT", f"slot {entry['slot']} {field} {record.get(field)!r} != {expected!r}"
                )
        if record.get("base_sha") != BASE_SHA:
            raise invalid("V_SLOT", f"slot {entry['slot']} BASE differs")
        if record.get("lane_ids") != protocol["lane_ids"]:
            raise invalid("V_SLOT", f"slot {entry['slot']} lane set/order differs")
        arm = entry["arm"]
        derivative = record.get("diagnostic_derivative_sha256")
        if kind == "control":
            if arm not in ("A1", "A2"):
                raise invalid("V_SLOT", f"control slot {entry['slot']} has arm {arm!r}")
            if derivative is not None:
                raise invalid("V_SLOT", f"control slot {entry['slot']} carries a fingerprint")
        else:
            if arm == "A":
                if derivative is not None:
                    raise invalid("V_SLOT", f"A slot {entry['slot']} carries a derivative fingerprint")
            elif not isinstance(derivative, str) or len(derivative) != 64:
                raise invalid("V_SLOT", f"{arm} slot {entry['slot']} lacks a derivative fingerprint")
        if record.get("contention_before") != "clear" or record.get("contention_after") != "clear":
            raise invalid("V_CONTENTION", f"slot {entry['slot']} is not contention-clear")
        lanes = record.get("lanes")
        if not isinstance(lanes, list) or len(lanes) != 9:
            raise invalid("V_SLOT", f"slot {entry['slot']} does not contain nine lanes")
        if [lane.get("id") for lane in lanes] != protocol["lane_ids"]:
            raise invalid("V_SLOT", f"slot {entry['slot']} lanes are missing/reordered")
        probe = arm == "P"
        for lane in lanes:
            expected = oracle_lanes[lane["id"]]
            validate_samples(lane.get("samples_ns"), f"slot {entry['slot']} {lane['id']}")
            if lane.get("warmups") != protocol["warmups_per_lane_slot"]:
                raise invalid("V_WARMUP", f"slot {entry['slot']} {lane['id']} warmup count")
            if lane.get("expected_total_hits") != expected["total_hits"]:
                raise invalid("V_ORACLE", f"slot {entry['slot']} {lane['id']} expected count")
            if lane.get("observed_total_hits") != expected["total_hits"]:
                raise invalid("V_ORACLE", f"slot {entry['slot']} {lane['id']} observed count")
            if lane.get("doc_ids") != expected["doc_ids"]:
                raise invalid("V_ORACLE", f"slot {entry['slot']} {lane['id']} doc ids")
            stages = lane.get("stage_samples")
            counters = lane.get("counter_samples")
            segment_samples = lane.get("segment_samples")
            strata_ns_samples = lane.get("strata_ns_samples")
            strata_count_samples = lane.get("strata_count_samples")
            unsupported_samples = lane.get("segments_unsupported_samples")
            if probe:
                if not isinstance(stages, list) or len(stages) != 20:
                    raise invalid("V_STAGES", f"slot {entry['slot']} {lane['id']} stage samples")
                if not isinstance(counters, list) or len(counters) != 20:
                    raise invalid("V_COUNTERS", f"slot {entry['slot']} {lane['id']} counter samples")
                if not isinstance(segment_samples, list) or len(segment_samples) != 20:
                    raise invalid("V_SEGMENTS", f"slot {entry['slot']} {lane['id']} segment samples")
                if not isinstance(strata_ns_samples, list) or len(strata_ns_samples) != 20:
                    raise invalid("V_STRATA", f"slot {entry['slot']} {lane['id']} strata samples")
                if not isinstance(strata_count_samples, list) or len(strata_count_samples) != 20:
                    raise invalid("V_STRATA", f"slot {entry['slot']} {lane['id']} strata counts")
                if not isinstance(unsupported_samples, list) or len(unsupported_samples) != 20:
                    raise invalid("V_SEGMENTS", f"slot {entry['slot']} {lane['id']} unsupported flags")
                for stage in stages:
                    strict_array(stage, 25, f"slot {entry['slot']} {lane['id']} stage")
                for counter in counters:
                    strict_array(counter, 15, f"slot {entry['slot']} {lane['id']} counter")
                for segments in segment_samples:
                    if not isinstance(segments, list) or len(segments) > protocol["max_segment_descriptors"]:
                        raise invalid("V_SEGMENTS", f"slot {entry['slot']} {lane['id']} segment shape")
                    for descriptor in segments:
                        strict_array(descriptor, 4, f"slot {entry['slot']} {lane['id']} descriptor")
                for strata in strata_ns_samples:
                    if not isinstance(strata, list) or len(strata) != 2:
                        raise invalid("V_STRATA", f"slot {entry['slot']} {lane['id']} strata shape")
                    for row in strata:
                        strict_array(row, 8, f"slot {entry['slot']} {lane['id']} strata row")
                for counts in strata_count_samples:
                    strict_array(counts, 2, f"slot {entry['slot']} {lane['id']} strata count")
                for flag in unsupported_samples:
                    if not isinstance(flag, bool):
                        raise invalid("V_SEGMENTS", f"slot {entry['slot']} {lane['id']} unsupported flag")
            else:
                if any(value is not None for value in (
                    stages, counters, segment_samples, strata_ns_samples,
                    strata_count_samples, unsupported_samples,
                )):
                    raise invalid(
                        "V_MODE", f"{arm} slot {entry['slot']} {lane['id']} carries probe fields"
                    )
        records[entry["slot"]] = record
        records[entry["slot"]] = record
    return records


# ---------------------------------------------------------------------------
# Independent statistics and classification
# ---------------------------------------------------------------------------


def median20(samples) -> int:
    validate_samples(samples, "samples")
    ordered = sorted(samples)
    return ordered[9]


def median_of_four(values) -> float:
    if len(values) != 4:
        raise invalid("V_RATIO", "expected four block values")
    ordered = sorted(values)
    return (ordered[1] + ordered[2]) / 2


def _mean2(first: int, second: int) -> float:
    return (first + second) / 2


def _block_values(records: dict, plan: list[dict], lane_id: str) -> dict:
    values = {}
    for entry in plan:
        record = records[entry["slot"]]
        item = next((lane for lane in record["lanes"] if lane["id"] == lane_id), None)
        if item is None:
            raise invalid("V_SLOT", f"slot {entry['slot']} is missing lane {lane_id}")
        values.setdefault((entry["arm"], entry["block"]), []).append(
            (entry["slot"], median20(item["samples_ns"]))
        )
    return values


def recompute_timing(records: dict, protocol: dict, kind: str) -> dict:
    if kind == "control":
        plan = control_schedule(protocol)
        blocks_per_campaign = protocol["control_blocks"]
        arms = ("A1", "A2")
        slots_per_arm = protocol["control_arm_slots_per_block"]
    else:
        plan = slot_schedule(protocol)
        blocks_per_campaign = protocol["blocks_per_campaign"]
        arms = ("A", "Q", "P")
        slots_per_arm = protocol["arm_slots_per_block"]
    timed = 0
    for record in records.values():
        for lane in record["lanes"]:
            timed += len(lane["samples_ns"])
    expected_timed = len(records) * len(protocol["lane_ids"]) * protocol["samples_per_lane_slot"]
    if timed != expected_timed:
        raise invalid("V_COUNT", f"expected {expected_timed} timed observations, found {timed}")
    timing = {}
    for lane in lane_descriptors(protocol):
        lane_id = lane["id"]
        values = _block_values(records, plan, lane_id)
        blocks = []
        campaign_values = {}
        if kind == "control":
            ratios = []
            for block in range(1, blocks_per_campaign + 1):
                for arm in arms:
                    slots = values.get((arm, block), [])
                    if len(slots) != slots_per_arm:
                        raise invalid("V_COUNT", f"{lane_id} arm {arm} block {block} slot count")
                a1_mean = _mean2(*[value for _, value in values[("A1", block)]])
                a2_mean = _mean2(*[value for _, value in values[("A2", block)]])
                if a1_mean <= 0 or a2_mean <= 0:
                    raise invalid("V_RATIO", f"{lane_id} block {block} non-positive median")
                ratio = a1_mean / a2_mean
                ratios.append(ratio)
                blocks.append(
                    {
                        "block": block,
                        "a1_slots": [slot for slot, _ in values[("A1", block)]],
                        "a2_slots": [slot for slot, _ in values[("A2", block)]],
                        "a1_a2": ratio,
                    }
                )
            campaign_values = {"a1_a2": median_of_four(ratios)}
        else:
            drift, qa, pq, pa = [], [], [], []
            for block in range(1, blocks_per_campaign + 1):
                for arm in arms:
                    slots = values.get((arm, block), [])
                    if len(slots) != slots_per_arm:
                        raise invalid("V_COUNT", f"{lane_id} arm {arm} block {block} slot count")
                a_slots = values[("A", block)]
                q_slots = values[("Q", block)]
                p_slots = values[("P", block)]
                a_mean = _mean2(*[value for _, value in a_slots])
                q_mean = _mean2(*[value for _, value in q_slots])
                p_mean = _mean2(*[value for _, value in p_slots])
                if a_mean <= 0 or q_mean <= 0 or p_mean <= 0:
                    raise invalid("V_RATIO", f"{lane_id} block {block} non-positive median")
                drift.append(a_slots[1][1] / a_slots[0][1])
                qa.append(q_mean / a_mean)
                pq.append(p_mean / q_mean)
                pa.append(p_mean / a_mean)
                blocks.append(
                    {
                        "block": block,
                        "a_slots": [slot for slot, _ in a_slots],
                        "q_slots": [slot for slot, _ in q_slots],
                        "p_slots": [slot for slot, _ in p_slots],
                        "q_a": qa[-1],
                        "p_q": pq[-1],
                        "p_a": pa[-1],
                        "a_a_drift": drift[-1],
                    }
                )
            campaign_values = {
                "q_a": median_of_four(qa),
                "p_q": median_of_four(pq),
                "p_a": median_of_four(pa),
                "a_a_drift": median_of_four(drift),
            }
        timing[lane_id] = {
            "class": lane["class"],
            "kind": lane["kind"],
            "blocks": blocks,
            "campaign": campaign_values,
        }
    return timing


def _validate_ratio(value, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise invalid("V_TIMING", f"invalid ratio for {label}: {value!r}")
    return float(value)


def _stability_failures(timing: dict, protocol: dict) -> list[dict]:
    failures = []
    low = protocol["a_a_drift_median_min"]
    high = protocol["a_a_drift_median_max"]
    block_low = protocol["a_a_outlier_block_low"]
    block_high = protocol["a_a_outlier_block_high"]
    maximum = protocol["a_a_max_outlier_blocks_per_lane"]
    for lane_id, lane in timing.items():
        drift = _validate_ratio(lane["campaign"]["a_a_drift"], f"{lane_id}/a_a_drift")
        if not (low <= drift <= high):
            failures.append(
                {"lane": lane_id, "gate": "A_A_MEDIAN", "observed": drift, "expected": [low, high]}
            )
        outliers = 0
        for block in lane["blocks"]:
            ratio = _validate_ratio(block["a_a_drift"], f"{lane_id}/block-a_a_drift")
            if not (block_low <= ratio <= block_high):
                outliers += 1
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


def _intrusion_failures(timing: dict, protocol: dict) -> list[dict]:
    failures = []
    guard = protocol["single_block_guard_ceiling"]
    for lane_id, lane in timing.items():
        kind = lane["kind"]
        for key, prefix in (("q_a", "q_a"), ("p_q", "p_q")):
            ceiling = (
                protocol[f"{prefix}_ratio_ceiling_low_match"]
                if kind == "low_match"
                else protocol[f"{prefix}_ratio_ceiling_medium_common"]
            )
            median = _validate_ratio(lane["campaign"][key], f"{lane_id}/{key}")
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
                value = _validate_ratio(block[key], f"{lane_id}/block-{key}")
                if value > guard:
                    failures.append(
                        {
                            "lane": lane_id,
                            "gate": f"{key.upper()}_BLOCK",
                            "block": block["block"],
                            "observed": value,
                            "guard": guard,
                        }
                    )
    return failures


def lane_qualification(timing: dict, protocol: dict) -> dict:
    result = {}
    for lane_id, lane in timing.items():
        stability = _stability_failures({lane_id: lane}, protocol)
        intrusion = _intrusion_failures({lane_id: lane}, protocol)
        if stability:
            status = "UNSTABLE"
        elif intrusion:
            status = "DIAGNOSTIC_PERTURBED"
        else:
            status = "QUALIFIED"
        result[lane_id] = {
            "status": status,
            "stability_failures": stability,
            "intrusion_failures": intrusion,
        }
    return result


def recompute_classification(timing: dict, protocol: dict, kind: str) -> dict:
    failures = []
    if kind == "control":
        low = protocol["a_a_outlier_block_low"]
        high = protocol["a_a_outlier_block_high"]
        median_low = protocol["a_a_drift_median_min"]
        median_high = protocol["a_a_drift_median_max"]
        hard_low = protocol["a_a_outlier_hard_low"]
        hard_high = protocol["a_a_outlier_hard_high"]
        exempt = set(protocol["control_soft_outlier_lane_ids"])
        maximum = protocol["control_soft_outlier_max_per_lane"]
        tolerated = []
        for lane_id, lane in timing.items():
            soft = []
            for block in lane["blocks"]:
                ratio = _validate_ratio(block["a1_a2"], f"{lane_id}/control-block")
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
                if not (low <= ratio <= high):
                    soft.append(
                        {
                            "lane": lane_id,
                            "gate": "CONTROL_SOFT_OUTLIER",
                            "block": block["block"],
                            "observed": ratio,
                            "expected": [low, high],
                        }
                    )
            if lane_id in exempt:
                if len(soft) > maximum:
                    failures.extend({**item, "gate": "CONTROL_BLOCK_RATIO"} for item in soft)
                else:
                    tolerated.extend(soft)
            else:
                failures.extend({**item, "gate": "CONTROL_BLOCK_RATIO"} for item in soft)
            aggregate = _validate_ratio(lane["campaign"]["a1_a2"], f"{lane_id}/control-median")
            if not (median_low <= aggregate <= median_high):
                failures.append(
                    {
                        "lane": lane_id,
                        "gate": "CONTROL_LOWER_MEDIAN",
                        "observed": aggregate,
                        "expected": [median_low, median_high],
                    }
                )
        status = "D3A_CONTROL_QUALIFIED" if not failures else "D3A_CONTROL_NOT_QUALIFIED"
        return {"status": status, "failures": failures, "tolerated": tolerated}

    qualification = lane_qualification(timing, protocol)
    for item in qualification.values():
        failures.extend(item["stability_failures"])
        failures.extend(item["intrusion_failures"])
    all_eligible = all(item["status"] == "QUALIFIED" for item in qualification.values())
    status = (
        "D3A_ATTRIBUTION_LOW_INTRUSION"
        if all_eligible
        else "D3A_ATTRIBUTION_LANE_SCOPED"
    )
    return {
        "status": status,
        "failures": failures,
        "lane_qualification": qualification,
    }


# ---------------------------------------------------------------------------
# Stage partition and ranking
# ---------------------------------------------------------------------------


def expected_sample_counts(n: int, protocol: dict) -> tuple[int, int]:
    if n < protocol["candidate_sample_min_n"]:
        return (0, 0)
    first = min(n, protocol["candidate_first_samples"])
    steady = 0
    if n > first:
        steady = (n - first - 1) // protocol["candidate_steady_stride"] + 1
    return (first, steady)


def _exclusive(stage: list[int]) -> dict:
    (
        plan, reader, expand, stats, evaluate, candidate, projection,
        leaf, membership, score_vector, score_map, score_owner, score_accumulate,
        matched_reserve, scored_vec_build, temp_release, match_insert_sample,
        candidate_sample, key, sort_view, sort_charge, duplicate, compare,
        materialize, heap,
    ) = stage
    return {
        "plan": plan, "reader": reader, "expand": expand, "stats": stats,
        "evaluate": evaluate, "candidate": candidate, "projection": projection,
        "leaf": leaf, "membership": membership, "score_vector": score_vector,
        "score_map": score_map, "score_owner": score_owner,
        "score_accumulate": score_accumulate, "matched_reserve": matched_reserve,
        "scored_vec_build": scored_vec_build, "temp_release": temp_release,
        "match_insert_sample": match_insert_sample,
        "candidate_sample": candidate_sample, "key": key,
        "sort_view": sort_view, "sort_charge": sort_charge,
        "duplicate": duplicate, "compare": compare,
        "materialize": materialize, "heap": heap,
    }


def decompose(
    engine_ns: int,
    stages,
    counters,
    segments,
    strata_ns,
    strata_count,
    segments_unsupported: bool,
    expected_hits: int,
    top_k: int,
    protocol: dict,
) -> dict:
    stage = strict_array(stages, 25, "stage")
    counter = strict_array(counters, 15, "counter")
    if engine_ns <= 0:
        raise invalid("V_STAGES", "engine_ns is not positive")
    values = _exclusive(stage)
    absolute = protocol["stage_partition_overhead_abs_ns"]
    share = protocol["stage_partition_overhead_share"]
    candidate_share = protocol["candidate_sample_partition_overhead_share"]

    top_named = (
        values["plan"] + values["reader"] + values["expand"] + values["stats"]
        + values["evaluate"] + values["candidate"] + values["projection"]
    )
    top_tolerance = max(absolute, int(engine_ns * share))
    other_raw = engine_ns - top_named
    top_violation = other_raw < -top_tolerance
    other = max(0, other_raw)

    evaluate_children = (
        values["leaf"] + values["membership"] + values["matched_reserve"]
        + values["score_vector"] + values["temp_release"]
    )
    evaluate_tolerance = max(absolute, int(values["evaluate"] * share))
    evaluate_violation = evaluate_children > values["evaluate"] + evaluate_tolerance
    evaluate_residual = max(0, values["evaluate"] - evaluate_children)

    score_children = (
        values["score_map"] + values["score_owner"]
        + values["score_accumulate"] + values["scored_vec_build"]
    )
    score_tolerance = max(absolute, int(values["score_vector"] * share))
    score_violation = score_children > values["score_vector"] + score_tolerance

    candidate_children = (
        values["key"] + values["sort_view"] + values["sort_charge"]
        + values["duplicate"] + values["compare"] + values["materialize"]
        + values["heap"]
    )
    candidate_tolerance = max(absolute, int(values["candidate_sample"] * candidate_share))
    candidate_violation = candidate_children > values["candidate_sample"] + candidate_tolerance
    candidate_residual = max(0, values["candidate_sample"] - candidate_children)
    candidate_over_parent = (
        values["candidate_sample"]
        > values["candidate"] + max(absolute, int(values["candidate"] * share))
    )

    (
        matched, scored, candidate_docs, bm25_calls, map_entries, owners,
        first_samples, steady_samples, fast_samples, fallback_samples,
        insert_samples, replace_samples, reject_samples, match_insert_samples,
        key_samples,
    ) = counter
    if not (matched == scored == candidate_docs == bm25_calls == expected_hits):
        raise invalid("V_COUNTER", "matched/scored/candidate/bm25 counters disagree with hits")
    if map_entries != expected_hits:
        raise invalid("V_COUNTER", "scoring_map_entries disagrees with hits")
    expected_owners = 0 if expected_hits == 0 else 1
    if owners != expected_owners:
        raise invalid("V_COUNTER", "positive_term_owners is not the single-term expectation")

    evaluated_first = 0
    evaluated_steady = 0
    descriptor_match = 0
    descriptor_total = 0
    sampling_violation = False
    for descriptor in segments:
        n, first, steady, match = descriptor
        expected_first, expected_steady = expected_sample_counts(n, protocol)
        if first != expected_first or steady != expected_steady:
            sampling_violation = True
        if n < protocol["candidate_sample_min_n"] and (first or steady):
            sampling_violation = True
        evaluated_first += expected_first
        evaluated_steady += expected_steady
        descriptor_match += match
        descriptor_total += n
    if descriptor_total != candidate_docs:
        raise invalid("V_SEGMENTS", "segment scored lengths do not sum to candidate_docs")
    if match_insert_samples != descriptor_match:
        raise invalid("V_COUNTER", "match-insert samples disagree with descriptors")
    if first_samples != evaluated_first or steady_samples != evaluated_steady:
        raise invalid("V_COUNTER", "candidate sample counters disagree with segments")
    if fast_samples + fallback_samples != first_samples + steady_samples:
        sampling_violation = True
    if insert_samples + replace_samples + reject_samples != first_samples + steady_samples:
        sampling_violation = True
    if key_samples != first_samples + steady_samples:
        sampling_violation = True
    if values["candidate_sample"] == 0 and (
        first_samples or steady_samples or candidate_children
    ):
        sampling_violation = True
    if values["candidate_sample"] > 0 and first_samples + steady_samples == 0:
        sampling_violation = True
    if first_samples + steady_samples == 0 and candidate_children:
        sampling_violation = True

    strata = []
    if not isinstance(strata_ns, list) or len(strata_ns) != 2:
        raise invalid("V_STRATA", "strata_ns is not a two-row array")
    for row in strata_ns:
        strata.append(strict_array(row, 8, "strata_ns"))
    for child_index in range(8):
        total = strata[0][child_index] + strata[1][child_index]
        if total != stage[17 + child_index]:
            raise invalid("V_STRATA", "strata child totals disagree with stage accumulators")
    counts = strict_array(strata_count, 2, "strata_count")
    if counts[0] != first_samples or counts[1] != steady_samples:
        raise invalid("V_STRATA", "strata counts disagree with candidate sample counters")

    if segments_unsupported:
        sampling_violation = True

    categories = {
        "plan_ns": values["plan"],
        "reader_live_ns": values["reader"],
        "expand_ns": values["expand"],
        "stats_ns": values["stats"],
        "leaf_decode_ns": values["leaf"],
        "membership_ns": values["membership"],
        "score_vector_ns": values["score_vector"],
        "matched_reserve_ns": values["matched_reserve"],
        "temp_release_ns": values["temp_release"],
        "eval_residual_ns": evaluate_residual,
        "candidate_ns": values["candidate"],
        "projection_ns": values["projection"],
        "other_ns": other,
    }
    reconstructed = sum(categories.values())
    partition_ok = not (
        top_violation or evaluate_violation or score_violation
        or candidate_violation or candidate_over_parent or sampling_violation
    )
    return {
        "engine_ns": engine_ns,
        "stage": values,
        "categories": categories,
        "reconstructed_ns": reconstructed,
        "partition_ok": partition_ok,
        "top_violation": top_violation,
        "evaluate_violation": evaluate_violation,
        "score_violation": score_violation,
        "candidate_violation": candidate_violation,
        "candidate_over_parent": candidate_over_parent,
        "sampling_violation": sampling_violation,
        "evaluate_residual_ns": evaluate_residual,
        "candidate_residual_ns": candidate_residual,
        "candidate_children_ns": candidate_children,
        "intermediate_disjoint_ns": (
            values["score_map"] + values["scored_vec_build"]
            + values["matched_reserve"] + values["temp_release"]
        ),
        "strata_ns": strata,
        "strata_count": counts,
        "segments": segments,
        "segments_unsupported": segments_unsupported,
        "counters": {
            "matched_docs": matched,
            "scored_docs": scored,
            "candidate_docs": candidate_docs,
            "bm25_calls": bm25_calls,
            "scoring_map_entries": map_entries,
            "positive_term_owners": owners,
            "candidate_samples_first": first_samples,
            "candidate_samples_steady": steady_samples,
            "candidate_samples_fast": fast_samples,
            "candidate_samples_fallback": fallback_samples,
            "candidate_samples_insert": insert_samples,
            "candidate_samples_replace": replace_samples,
            "candidate_samples_reject": reject_samples,
            "match_insert_samples": match_insert_samples,
            "candidate_samples_key": key_samples,
        },
        "expected_hits": expected_hits,
        "returned_hits": min(expected_hits, top_k),
    }


def _nearest_rank(values: list[int], numerator: int) -> int:
    if not values:
        raise invalid("V_STAGE_COUNT", "cannot take a percentile of no samples")
    ordered = sorted(values)
    index = (len(ordered) * numerator + 99) // 100 - 1
    return ordered[max(index, 0)]


def _median_fraction(values: list[Fraction]) -> Fraction:
    if not values:
        raise invalid("V_STAGE_COUNT", "cannot take a median of no ratios")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _fraction_pair(value: Fraction | None):
    if value is None:
        return None
    return [value.numerator, value.denominator]


def _area_metrics(samples: list[dict]) -> dict:
    strata = [
        [sum(sample["strata_ns"][row][child] for sample in samples) for child in range(8)]
        for row in range(2)
    ]

    def child(index: int) -> dict:
        result = {}
        for row, name in ((0, "first"), (1, "steady")):
            parent = strata[row][0]
            value = strata[row][index]
            result[name] = {
                "parent_ns": parent,
                "ns": value,
                "share": _fraction_pair(Fraction(value, parent) if parent > 0 else None),
            }
        return result

    def pair(index_a: int, index_b: int) -> dict:
        result = {}
        for row, name in ((0, "first"), (1, "steady")):
            parent = strata[row][0]
            value = strata[row][index_a] + strata[row][index_b]
            result[name] = {
                "parent_ns": parent,
                "ns": value,
                "share": _fraction_pair(Fraction(value, parent) if parent > 0 else None),
            }
        return result

    match_ns = [sample["stage"]["match_insert_sample"] for sample in samples]
    match_count = sum(sample["counters"]["match_insert_samples"] for sample in samples)
    map_build = [
        sample["stage"]["score_map"] + sample["stage"]["scored_vec_build"]
        for sample in samples
    ]
    map_build_ratios = [
        Fraction(value, sample["engine_ns"])
        for value, sample in zip(map_build, samples)
        if sample["engine_ns"] > 0
    ]
    return {
        "document_key": child(1),
        "duplicate_detection": child(4),
        "sort_extraction": child(2),
        "sort_charge": child(3),
        "heap_compare_update": pair(5, 7),
        "candidate_materialization": child(6),
        "match_set_construction": {
            "sampled_ns": _nearest_rank(match_ns, 50),
            "samples": match_count,
            "estimable": match_count > 0,
        },
        "scored_map_vector": {
            "ns": _nearest_rank(map_build, 50),
            "share": _fraction_pair(_median_fraction(map_build_ratios) if map_build_ratios else None),
            "score_map_ns": _nearest_rank([sample["stage"]["score_map"] for sample in samples], 50),
            "scored_vec_build_ns": _nearest_rank(
                [sample["stage"]["scored_vec_build"] for sample in samples], 50
            ),
        },
    }


def _lane_metrics(samples: list[dict], lane: dict, protocol: dict) -> dict:
    engine = [sample["engine_ns"] for sample in samples]
    candidates = [sample["stage"]["candidate"] for sample in samples]
    candidate_ratios = [
        Fraction(sample["stage"]["candidate"], sample["engine_ns"]) for sample in samples
    ]
    evaluate = [sample["stage"]["evaluate"] for sample in samples]
    intermediate = [sample["intermediate_disjoint_ns"] for sample in samples]
    intermediate_ratios = [
        Fraction(sample["intermediate_disjoint_ns"], sample["engine_ns"]) for sample in samples
    ]
    stage_medians = {}
    for name in (
        "score_map", "score_owner", "score_accumulate", "score_vector",
        "scored_vec_build", "matched_reserve", "temp_release",
        "leaf", "membership", "candidate_sample", "key", "sort_view",
        "sort_charge", "duplicate", "compare", "materialize", "heap",
        "match_insert_sample",
    ):
        stage_medians[name] = _nearest_rank(
            [sample["stage"][name] for sample in samples], 50
        )
    strata = [[sum(sample["strata_ns"][s][c] for sample in samples) for c in range(8)] for s in range(2)]
    first_total = strata[0][0]
    steady_total = strata[1][0]
    steady_children = sum(strata[1][1:])
    steady_residual = max(0, steady_total - steady_children)
    child_names = [
        "candidate_key", "candidate_sort_view", "candidate_sort_charge",
        "candidate_duplicate", "candidate_compare", "candidate_materialize",
        "candidate_heap",
    ]
    steady_shares = {
        name: Fraction(strata[1][index + 1], steady_children) if steady_children else Fraction(0)
        for index, name in enumerate(child_names)
    }
    ranked = sorted(steady_shares.items(), key=lambda item: (item[1], item[0]), reverse=True)
    dominant = None
    dominant_share = Fraction(0)
    runner_up_share = Fraction(0)
    if ranked and steady_children:
        top_name, top_share = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else Fraction(0)
        residual_ok = steady_residual * 10 <= steady_total * 3
        dominance_ok = (
            top_share >= Fraction(25, 100)
            and top_share >= Fraction(125, 100) * runner
            and residual_ok
        )
        if dominance_ok:
            dominant = top_name
            dominant_share = top_share
            runner_up_share = runner
    candidate_material = (
        _nearest_rank(candidates, 50) >= protocol["candidate_priority"]["candidate_min_ns"]
        and _median_fraction(candidate_ratios)
        >= Fraction(protocol["candidate_priority"]["candidate_min_share"]).limit_denominator(1000)
    )
    intermediate_material = (
        _nearest_rank(intermediate, 50)
        >= protocol["intermediate_priority"]["min_disjoint_ns"]
        and _median_fraction(intermediate_ratios)
        >= Fraction(protocol["intermediate_priority"]["min_disjoint_share"]).limit_denominator(1000)
    )
    intermediate_largest = None
    if intermediate_material:
        component_medians = {
            name: stage_medians[name]
            for name in ("score_map", "scored_vec_build", "matched_reserve", "temp_release")
        }
        ordered = sorted(component_medians.items(), key=lambda item: (item[1], item[0]), reverse=True)
        if len(ordered) == 1 or ordered[0][1] > ordered[1][1]:
            intermediate_largest = ordered[0][0]
    fallback_samples = sum(
        sample["counters"]["candidate_samples_fallback"] for sample in samples
    )
    sampled = sum(
        sample["counters"]["candidate_samples_first"]
        + sample["counters"]["candidate_samples_steady"]
        for sample in samples
    )
    return {
        "engine_ns": _nearest_rank(engine, 50),
        "candidate_ns": _nearest_rank(candidates, 50),
        "candidate_share": float(_median_fraction(candidate_ratios)),
        "candidate_share_exact": _fraction_pair(_median_fraction(candidate_ratios)),
        "evaluate_ns": _nearest_rank(evaluate, 50),
        "membership_ns": stage_medians["membership"],
        "temp_release_ns": stage_medians["temp_release"],
        "evaluate_share": float(
            _median_fraction([Fraction(sample["stage"]["evaluate"], sample["engine_ns"]) for sample in samples])
        ),
        "intermediate_disjoint_ns": _nearest_rank(intermediate, 50),
        "intermediate_share": float(_median_fraction(intermediate_ratios)),
        "intermediate_share_exact": _fraction_pair(_median_fraction(intermediate_ratios)),
        "stage_medians": stage_medians,
        "first_samples": sum(sample["counters"]["candidate_samples_first"] for sample in samples),
        "steady_samples": sum(sample["counters"]["candidate_samples_steady"] for sample in samples),
        "sampled_candidates": sampled,
        "fallback_samples": fallback_samples,
        "candidate_sample_ns": _nearest_rank(
            [sample["stage"]["candidate_sample"] for sample in samples], 50
        ),
        "candidate_residual_ns": _nearest_rank(
            [sample["candidate_residual_ns"] for sample in samples], 50
        ),
        "strata_ns": strata,
        "steady_child_ns": steady_children,
        "steady_residual_ns": steady_residual,
        "steady_child_shares": {name: float(share) for name, share in steady_shares.items()},
        "candidate_material": candidate_material,
        "dominant_component": dominant,
        "dominant_share": float(dominant_share),
        "runner_up_share": float(runner_up_share),
        "intermediate_material": intermediate_material,
        "intermediate_largest_component": intermediate_largest,
        "areas": _area_metrics(samples),
        "samples": len(samples),
    }


def recompute_stages(records: dict, protocol: dict, oracle_lanes: dict, kind: str) -> dict:
    if kind == "control":
        return {
            "schema": "pr15i-d3a-stage-summary-v1",
            "status": "NOT_APPLICABLE",
            "lanes": {},
            "partition": {"violations": 0, "samples": 0, "invalid": False},
        }
    plan = slot_schedule(protocol)
    lanes = {}
    violation_counts = {
        "top": 0, "evaluate": 0, "score": 0, "candidate": 0, "sampling": 0,
    }
    lane_violation_counts = {}
    samples_seen = 0
    for lane in lane_descriptors(protocol):
        lane_id = lane["id"]
        lane_counts = {"top": 0, "evaluate": 0, "score": 0, "candidate": 0, "sampling": 0}
        lane_violation_counts[lane_id] = lane_counts
        samples = []
        for entry in plan:
            if entry["arm"] != "P":
                continue
            record = records[entry["slot"]]
            item = next(lane for lane in record["lanes"] if lane["id"] == lane_id)
            expected = oracle_lanes[lane_id]
            for engine_ns, stages, counters, segments, strata_ns, strata_count, unsupported in zip(
                item["samples_ns"],
                item["stage_samples"],
                item["counter_samples"],
                item["segment_samples"],
                item["strata_ns_samples"],
                item["strata_count_samples"],
                item["segments_unsupported_samples"],
            ):
                sample = decompose(
                    engine_ns, stages, counters, segments, strata_ns, strata_count,
                    unsupported, expected["total_hits"], lane["k"], protocol,
                )
                samples.append(sample)
                samples_seen += 1
                if sample["top_violation"]:
                    violation_counts["top"] += 1
                    lane_counts["top"] += 1
                if sample["evaluate_violation"]:
                    violation_counts["evaluate"] += 1
                    lane_counts["evaluate"] += 1
                if sample["score_violation"]:
                    violation_counts["score"] += 1
                    lane_counts["score"] += 1
                if sample["candidate_violation"] or sample["candidate_over_parent"]:
                    violation_counts["candidate"] += 1
                    lane_counts["candidate"] += 1
                if sample["sampling_violation"]:
                    violation_counts["sampling"] += 1
                    lane_counts["sampling"] += 1
        expected_p_samples = 8 * protocol["samples_per_lane_slot"]
        if len(samples) != expected_p_samples:
            raise invalid(
                "V_STAGE_COUNT", f"{lane_id} does not contain {expected_p_samples} P samples"
            )
        metrics = _lane_metrics(samples, lane, protocol)
        limit = protocol["stage_partition_max_violation_fraction"]
        lane_invalid = {
            name: (count / len(samples)) > limit for name, count in lane_counts.items()
        }
        metrics["partition"] = {
            "violations": lane_counts,
            "samples": len(samples),
            "invalid": any(lane_invalid.values()),
            "per_category_invalid": lane_invalid,
        }
        lanes[lane_id] = metrics
    expected_total = 8 * len(protocol["lane_ids"]) * protocol["samples_per_lane_slot"]
    if samples_seen != expected_total:
        raise invalid("V_STAGE_COUNT", f"unexpected P stage sample count {samples_seen}")
    limit = protocol["stage_partition_max_violation_fraction"]
    invalid_partitions = {
        name: (count / samples_seen) > limit for name, count in violation_counts.items()
    }
    partition_invalid = any(invalid_partitions.values())
    return {
        "schema": "pr15i-d3a-stage-summary-v1",
        "status": "STAGE_PARTITION_INVALID" if partition_invalid else "QUALIFIED",
        "lanes": lanes,
        "partition": {
            "violations": violation_counts,
            "samples": samples_seen,
            "invalid": partition_invalid,
            "per_category_invalid": invalid_partitions,
        },
    }


def campaign_decision(stage_summary: dict, protocol: dict) -> dict:
    gate = protocol["candidate_priority"]
    lanes = stage_summary["lanes"]
    material = {
        lane_id: lanes[lane_id]["candidate_material"] for lane_id in gate["lanes"]
    }
    dominant = {
        lane_id: lanes[lane_id]["dominant_component"] for lane_id in gate["lanes"]
    }
    intermediate = {
        lane_id: lanes[lane_id]["intermediate_material"] for lane_id in gate["lanes"]
    }
    intermediate_largest = {
        lane_id: lanes[lane_id]["intermediate_largest_component"]
        for lane_id in gate["lanes"]
    }
    material_lanes = [lane_id for lane_id, ok in material.items() if ok]
    intermediate_lanes = [lane_id for lane_id, ok in intermediate.items() if ok]
    return {
        "candidate_material": material,
        "dominant_component": dominant,
        "intermediate_material": intermediate,
        "intermediate_largest_component": intermediate_largest,
        "material_lanes": material_lanes,
        "intermediate_lanes": intermediate_lanes,
        "material_count": len(material_lanes),
        "intermediate_count": len(intermediate_lanes),
    }


def _same_component_across(first: dict, second: dict, lanes: list[str]) -> str | None:
    shared = []
    for lane_id in lanes:
        one = first["dominant_component"].get(lane_id)
        two = second["dominant_component"].get(lane_id)
        if one is not None and one == two:
            shared.append((lane_id, one))
    if len(shared) < 2:
        return None
    names = [name for _, name in shared]
    for name in names:
        if names.count(name) >= 2:
            return name
    return None


def _same_intermediate_across(first: dict, second: dict, lanes: list[str]) -> str | None:
    shared = []
    for lane_id in lanes:
        one = first["intermediate_largest_component"]
        two = second["intermediate_largest_component"]
        if one is not None and one == two:
            shared.append((lane_id, one))
    if len(shared) < 2:
        return None
    names = [name for _, name in shared]
    for name in names:
        if names.count(name) >= 2:
            return name
    return None


def _median5(values):
    if len(values) != 5:
        raise invalid("V_STAT", "five-run statistics require exactly five values")
    return sorted(values)[2]


def _mad5(values):
    median = _median5(values)
    return sorted(abs(value - median) for value in values)[2]


def median_lower(values):
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def mad_lower(values):
    median = median_lower(values)
    return sorted(abs(value - median) for value in values)[(len(values) - 1) // 2]


def _stat(values, *, fraction: bool) -> dict:
    if any(value is None for value in values):
        raise invalid("V_STAT", "statistics must not receive null eligible values")
    median = median_lower(values)
    mad = mad_lower(values)
    if fraction:
        if any(not isinstance(value, Fraction) for value in values):
            raise invalid("V_STAT", "fraction statistic received a non-fraction")
        return {
            "estimable": True,
            "n": len(values),
            "median": float(median),
            "median_exact": _fraction_pair(median),
            "mad": float(mad),
            "mad_exact": _fraction_pair(mad),
            "min": float(min(values)),
            "min_exact": _fraction_pair(min(values)),
            "max": float(max(values)),
            "max_exact": _fraction_pair(max(values)),
        }
    return {
        "estimable": True,
        "n": len(values),
        "median": int(median),
        "mad": int(mad),
        "min": int(min(values)),
        "max": int(max(values)),
    }


def _fraction_from_pair(pair):
    if pair is None:
        return None
    if not isinstance(pair, list) or len(pair) != 2:
        raise invalid("V_STAT", f"malformed exact fraction {pair!r}")
    numerator, denominator = pair
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int)
        or not isinstance(denominator, int)
        or denominator <= 0
    ):
        raise invalid("V_STAT", f"malformed exact fraction {pair!r}")
    return Fraction(numerator, denominator)


def _run_scalar(run: dict, lane_id: str, key: str):
    lane = run["stage_summary"]["lanes"][lane_id]
    if key in {
        "candidate_ns", "candidate_sample_ns", "candidate_residual_ns",
        "evaluate_ns", "membership_ns", "intermediate_disjoint_ns",
        "temp_release_ns",
    }:
        return lane[key]
    if key == "candidate_share":
        return _fraction_from_pair(lane["candidate_share_exact"])
    if key == "intermediate_share":
        return _fraction_from_pair(lane["intermediate_share_exact"])
    if key == "area:match_set_construction:sampled_ns":
        return lane["areas"]["match_set_construction"]["sampled_ns"]
    if key == "area:match_set_construction:samples":
        return lane["areas"]["match_set_construction"]["samples"]
    if key == "area:scored_map_vector:ns":
        return lane["areas"]["scored_map_vector"]["ns"]
    if key == "area:scored_map_vector:share":
        return _fraction_from_pair(lane["areas"]["scored_map_vector"]["share"])
    if key.startswith("area:"):
        _, area, stratum, field = key.split(":")
        value = lane["areas"][area][stratum][field]
        if field == "share":
            return _fraction_from_pair(value)
        return value
    if key == "matched_reserve_ns":
        return lane["stage_medians"]["matched_reserve"]
    if key == "score_accumulate_ns":
        return lane["stage_medians"]["score_accumulate"]
    if key == "score_vector_ns":
        return lane["stage_medians"]["score_vector"]
    if key == "sort_charge_ns":
        return lane["stage_medians"]["sort_charge"]
    raise invalid("V_STAT", f"unknown statistic key {key!r}")


SCALAR_KEYS = [
    ("candidate_ns", "int"),
    ("candidate_share", "fraction"),
    ("candidate_sample_ns", "int"),
    ("candidate_residual_ns", "int"),
    ("evaluate_ns", "int"),
    ("membership_ns", "int"),
    ("intermediate_disjoint_ns", "int"),
    ("intermediate_share", "fraction"),
    ("temp_release_ns", "int"),
    ("matched_reserve_ns", "int"),
    ("score_accumulate_ns", "int"),
    ("score_vector_ns", "int"),
    ("sort_charge_ns", "int"),
    ("area:document_key:first:ns", "int"),
    ("area:document_key:first:share", "fraction"),
    ("area:document_key:steady:ns", "int"),
    ("area:document_key:steady:share", "fraction"),
    ("area:duplicate_detection:first:ns", "int"),
    ("area:duplicate_detection:first:share", "fraction"),
    ("area:duplicate_detection:steady:ns", "int"),
    ("area:duplicate_detection:steady:share", "fraction"),
    ("area:sort_extraction:first:ns", "int"),
    ("area:sort_extraction:first:share", "fraction"),
    ("area:sort_extraction:steady:ns", "int"),
    ("area:sort_extraction:steady:share", "fraction"),
    ("area:heap_compare_update:first:ns", "int"),
    ("area:heap_compare_update:first:share", "fraction"),
    ("area:heap_compare_update:steady:ns", "int"),
    ("area:heap_compare_update:steady:share", "fraction"),
    ("area:candidate_materialization:first:ns", "int"),
    ("area:candidate_materialization:first:share", "fraction"),
    ("area:candidate_materialization:steady:ns", "int"),
    ("area:candidate_materialization:steady:share", "fraction"),
    ("area:match_set_construction:sampled_ns", "int"),
    ("area:match_set_construction:samples", "int"),
    ("area:scored_map_vector:ns", "int"),
    ("area:scored_map_vector:share", "fraction"),
]


def lane_scoped_five_run_stats(runs: list[dict], protocol: dict) -> dict:
    if len(runs) != 5:
        raise invalid("V_STAT", "lane-scoped statistics require exactly five runs")
    lanes = {}
    for lane in lane_descriptors(protocol):
        lane_id = lane["id"]
        eligible_indices = [
            index for index, run in enumerate(runs)
            if run["lane_qualification"][lane_id]["eligible"]
        ]
        n = len(eligible_indices)
        excluded = [
            {"run": run["campaign"], "reasons": run["lane_qualification"][lane_id]}
            for index, run in enumerate(runs)
            if index not in eligible_indices
        ]
        entry = {
            "n": n,
            "run_ids_used": [runs[index]["campaign"] for index in eligible_indices],
            "run_ids_excluded": excluded,
            "insufficient": n < protocol["lane_scoped_min_eligible_runs"],
        }
        if n >= 4:
            scalars = {}
            for key, kind in SCALAR_KEYS:
                all_values = [
                    _run_scalar(run, lane_id, key)
                    for index, run in enumerate(runs)
                    if index in eligible_indices
                ]
                if any(value is None for value in all_values):
                    if all(value is None for value in all_values):
                        scalars[key] = {"estimable": False, "n": len(all_values)}
                        continue
                    raise invalid(
                        "V_STAT",
                        f"{lane_id}/{key}: metric is missing for only some eligible runs",
                    )
                scalars[key] = _stat(all_values, fraction=(kind == "fraction"))
            entry["scalars"] = scalars
            entry["run_values"] = {}
            for key, _kind in SCALAR_KEYS:
                values = []
                for index, run in enumerate(runs):
                    if index not in eligible_indices:
                        values.append(None)
                        continue
                    value = _run_scalar(run, lane_id, key)
                    values.append(_fraction_pair(value) if isinstance(value, Fraction) else value)
                entry["run_values"][key] = values
            entry["candidate_material_runs"] = sum(
                1 for index in eligible_indices
                if runs[index]["stage_summary"]["lanes"][lane_id]["candidate_material"]
            )
            entry["intermediate_material_runs"] = sum(
                1 for index in eligible_indices
                if runs[index]["stage_summary"]["lanes"][lane_id]["intermediate_material"]
            )
        lanes[lane_id] = entry
    return {
        "schema": "pr15i-d3af2-lane-scoped-five-run-stats-v3",
        "runs": [run["campaign"] for run in runs],
        "lanes": lanes,
    }


def lane_scoped_five_run_decision(runs: list[dict], stats: dict, protocol: dict) -> dict:
    primary = protocol["candidate_priority"]["lanes"]
    min_runs = protocol["lane_scoped_min_eligible_runs"]
    joint_runs = protocol["lane_scoped_joint_min_runs"]
    sufficient = [lane for lane in primary if stats["lanes"][lane]["n"] >= min_runs]
    if len(sufficient) < protocol["lane_scoped_primary_min_lanes"]:
        return {
            "verdict": "D3A_MEASUREMENT_BLOCKED",
            "reason": "INSUFFICIENT_PRIMARY_LANE_EVIDENCE",
            "primary_lanes_sufficient": sufficient,
        }

    run_ids = [run["campaign"] for run in runs]

    def shared_candidate_runs(left: str, right: str, child: str) -> list[str]:
        shared = []
        for index, run in enumerate(runs):
            left_lane = run["stage_summary"]["lanes"][left]
            right_lane = run["stage_summary"]["lanes"][right]
            if not (
                run["lane_qualification"][left]["eligible"]
                and run["lane_qualification"][right]["eligible"]
            ):
                continue
            if not (left_lane["candidate_material"] and right_lane["candidate_material"]):
                continue
            if (
                left_lane["dominant_component"] == child
                and right_lane["dominant_component"] == child
            ):
                shared.append(run["campaign"])
        return shared

    def shared_intermediate_runs(left: str, right: str, child: str) -> list[str]:
        shared = []
        for index, run in enumerate(runs):
            left_lane = run["stage_summary"]["lanes"][left]
            right_lane = run["stage_summary"]["lanes"][right]
            if not (
                run["lane_qualification"][left]["eligible"]
                and run["lane_qualification"][right]["eligible"]
            ):
                continue
            if not (left_lane["intermediate_material"] and right_lane["intermediate_material"]):
                continue
            if (
                left_lane["intermediate_largest_component"] == child
                and right_lane["intermediate_largest_component"] == child
            ):
                shared.append(run["campaign"])
        return shared

    child_names = [
        "candidate_key", "candidate_sort_view", "candidate_sort_charge",
        "candidate_duplicate", "candidate_compare", "candidate_materialize",
        "candidate_heap",
    ]
    candidate_candidates = []
    for i, left in enumerate(sufficient):
        for right in sufficient[i + 1:]:
            for child in child_names:
                shared = shared_candidate_runs(left, right, child)
                if len(shared) >= joint_runs:
                    candidate_candidates.append(
                        {"child": child, "lanes": [left, right], "runs": shared}
                    )
    distinct_candidates = {item["child"] for item in candidate_candidates}
    if len(distinct_candidates) > 1:
        return {
            "verdict": "D3A_CANDIDATE_STAGE_UNRESOLVED",
            "reason": "MULTIPLE_CANDIDATE_COMPONENTS",
            "contenders": candidate_candidates,
        }
    if len(distinct_candidates) == 1:
        winner = candidate_candidates[0]
        return {
            "verdict": "D3A_CANDIDATE_HOTSPOT_LOCALIZED",
            "component": winner["child"],
            "lanes": winner["lanes"],
            "runs": winner["runs"],
        }

    intermediate_names = ["score_map", "scored_vec_build", "matched_reserve", "temp_release"]
    intermediate_candidates = []
    for i, left in enumerate(sufficient):
        for right in sufficient[i + 1:]:
            for child in intermediate_names:
                shared = shared_intermediate_runs(left, right, child)
                if len(shared) >= joint_runs:
                    intermediate_candidates.append(
                        {"child": child, "lanes": [left, right], "runs": shared}
                    )
    distinct_intermediate = {item["child"] for item in intermediate_candidates}
    if len(distinct_intermediate) > 1:
        return {
            "verdict": "D3A_CANDIDATE_STAGE_UNRESOLVED",
            "reason": "MULTIPLE_INTERMEDIATE_COMPONENTS",
            "contenders": intermediate_candidates,
        }
    if len(distinct_intermediate) == 1:
        winner = intermediate_candidates[0]
        return {
            "verdict": "D3A_INTERMEDIATE_MATERIALIZATION_PRIORITY",
            "component": winner["child"],
            "lanes": winner["lanes"],
            "runs": winner["runs"],
        }

    if any(
        stats["lanes"][lane].get("candidate_material_runs", 0) >= min_runs
        for lane in sufficient
    ) and sum(
        1 for lane in sufficient
        if stats["lanes"][lane].get("candidate_material_runs", 0) >= min_runs
    ) >= 2:
        return {
            "verdict": "D3A_CANDIDATE_STAGE_UNRESOLVED",
            "reason": "NO_NAMED_DOMINANT_COMPONENT",
        }
    return {
        "verdict": "D3A_NO_ACTIONABLE_HOTSPOT",
        "reason": "NO_COMPONENT_OR_MATERIALITY_MEETS_FROZEN_GATE",
    }


def verify_binaries(campaign_dir: str, protocol: dict, kind: str) -> dict:
    try:
        record = read_json(os.path.join(campaign_dir, "raw", "binaries.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_BINARY", f"malformed binaries.json: {error}") from error
    arms = record.get("arms")
    if not isinstance(arms, dict):
        raise invalid("V_BINARY", "binaries.json has no arms map")
    required = ("A", "QP") if kind == "paired" else ("A1", "A2")
    if set(arms) != set(required):
        raise invalid("V_BINARY", f"binary arms differ: {sorted(arms)}")
    entries = {}
    for arm in required:
        entry = arms.get(arm)
        if not isinstance(entry, dict):
            raise invalid("V_BINARY", f"missing {arm} binary record")
        path = entry.get("path")
        if not isinstance(path, str) or not os.path.isfile(path):
            raise blocked("V_BINARY", f"{arm} binary is unavailable")
        digest = sha256_file(path)
        if digest != entry.get("sha256"):
            raise invalid("V_BINARY", f"{arm} binary digest changed")
        entries[arm] = {"path": path, "sha256": digest}
    if kind == "paired":
        if entries["A"]["sha256"] == entries["QP"]["sha256"]:
            raise invalid("V_BINARY", "A and Q/P binary digests are identical")
        if record.get("q_and_p_exact_same_binary") is not True:
            raise invalid("V_BINARY", "Q/P same-binary claim was not asserted")
    else:
        if record.get("q_and_p_exact_same_binary") is not False:
            raise invalid("V_BINARY", "control must not claim a Q/P same-binary arm")
        if entries["A1"]["sha256"] != entries["A2"]["sha256"]:
            raise invalid("V_BINARY", "control A1/A2 binary digests differ")
    return entries


def verify_slot_binaries(records: dict, entries: dict, protocol: dict, kind: str) -> None:
    for slot, record in records.items():
        arm = record["arm"]
        if kind == "control":
            expected = entries[arm]["sha256"]
        else:
            expected = entries["QP" if arm in ("Q", "P") else "A"]["sha256"]
        if record.get("binary_sha256") != expected:
            raise invalid("V_BINARY", f"slot {slot} binary digest differs for arm {arm}")
        if kind == "paired" and arm in ("Q", "P") and record.get("diagnostic_derivative_sha256") is None:
            raise invalid("V_BINARY", f"slot {slot} lacks the derivative fingerprint")


def recompute_layout_files(entry: dict) -> str:
    files = entry.get("files")
    if not isinstance(files, list):
        raise invalid("V_INDEX", "index file inventory is not a list")
    normalized = []
    for item in files:
        relative = safe_member(item.get("path", ""))
        size = strict_int(item.get("size"), "index size", 0)
        digest = item.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise invalid("V_INDEX", f"malformed index digest for {relative}")
        normalized.append({"path": relative, "size": size, "sha256": digest})
    normalized.sort(key=lambda item: item["path"])
    return sha256_bytes(canonical_json_bytes(normalized))


def verify_index_layout(
    campaign_dir: str, protocol: dict, kind: str, check_files: bool = True
) -> dict:
    try:
        layout = read_json(os.path.join(campaign_dir, "raw", "index-layout.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_INDEX", f"malformed index-layout.json: {error}") from error
    builds = layout.get("builds")
    arms = ("A", "QP") if kind == "paired" else ("A1",)
    if not isinstance(builds, dict) or set(builds) != set(arms):
        raise invalid("V_INDEX", f"index layout must describe {arms}")
    digests = {}
    for arm in arms:
        digests[arm] = {}
        arm_builds = builds[arm]
        if set(arm_builds) != {"10000", "100000"}:
            raise invalid("V_INDEX", f"{arm} build set differs")
        for n in ("10000", "100000"):
            entry = arm_builds[n]
            recomputed = recompute_layout_files(entry)
            if entry.get("digest") != recomputed:
                raise invalid("V_INDEX", f"{arm}/{n} index digest mismatch")
            digests[arm][n] = recomputed
            if check_files:
                index_dir = entry.get("index_dir")
                if not isinstance(index_dir, str) or not os.path.isdir(index_dir):
                    raise blocked("V_INDEX", f"{arm}/{n} index directory is unavailable")
                for item in entry["files"]:
                    path = os.path.join(index_dir, item["path"])
                    if not os.path.isfile(path):
                        raise invalid("V_INDEX", f"{arm}/{n} missing file {item['path']}")
                    if os.path.getsize(path) != item["size"] or sha256_file(path) != item["sha256"]:
                        raise invalid("V_INDEX", f"{arm}/{n} file digest changed")
    if kind == "paired":
        for n in ("10000", "100000"):
            if digests["A"][n] != digests["QP"][n]:
                raise invalid("V_INDEX", f"A/QP index digests differ for N={n}")
    sentinel = builds[arms[0]].get("100000", {})
    if sentinel.get("committed_index_bytes") != protocol["100k_lz4_committed_index_sentinel"]:
        raise invalid("V_INDEX_FORMAT", "100K committed index sentinel differs")
    if sentinel.get("stored_bytes") != protocol["100k_lz4_stored_section_sentinel"]:
        raise invalid("V_INDEX_FORMAT", "100K stored section sentinel differs")
    return {"digests": digests, "layout": layout}


def verify_sources(campaign_dir: str, kind: str) -> dict:
    try:
        sources = read_json(os.path.join(campaign_dir, "raw", "sources.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_SOURCES", f"malformed sources.json: {error}") from error
    inventory = sources.get("source_inventory")
    expected_paths = EXISTING_FILES if kind == "control" else DERIVATIVE_FILES
    if not isinstance(inventory, dict) or set(inventory) != set(expected_paths):
        raise invalid("V_SOURCES", "source inventory does not cover the expected paths")
    tooling = sources.get("tooling")
    if not isinstance(tooling, dict) or not tooling:
        raise invalid("V_SOURCES", "tooling hashes are missing")
    for relative, digest in tooling.items():
        path = os.path.join(TOOLING_ROOT, relative)
        if not os.path.isfile(path):
            raise blocked("V_SOURCES", f"tooling file is unavailable: {relative}")
        if sha256_file(path) != digest:
            raise invalid("V_SOURCES", f"tooling hash mismatch for {relative}")
    if kind == "control":
        for relative, entry in inventory.items():
            if set(entry) != {"base_sha256"}:
                raise invalid("V_SOURCES", "control source inventory carries a derivative")
            path = os.path.join(TOOLING_ROOT, relative)
            # Control records the BASE worktree hashes supplied at run time; they
            # are compared for presence, not against the tooling tree.
        return {"fingerprint": None, "sources": sources}
    for relative in DERIVATIVE_FILES:
        entry = inventory[relative]
        if not isinstance(entry, dict):
            raise invalid("V_SOURCES", f"malformed source inventory for {relative}")
        if entry.get("derivative_sha256") is None or not isinstance(
            entry.get("derivative_sha256"), str
        ):
            raise invalid("V_SOURCES", f"missing derivative hash for {relative}")
        if relative == "crates/quervant-core/src/search/d3a_probe.rs":
            if entry.get("base_sha256") is not None:
                raise invalid("V_SOURCES", "the new probe module has a BASE hash")
        elif not isinstance(entry.get("base_sha256"), str):
            raise invalid("V_SOURCES", f"missing BASE hash for {relative}")
    fingerprint = sha256_bytes(
        canonical_json_bytes(
            {
                relative: inventory[relative]["derivative_sha256"]
                for relative in DERIVATIVE_FILES
            }
        )
    )
    if sources.get("diagnostic_derivative_sha256") != fingerprint:
        raise invalid("V_SOURCES", "diagnostic derivative fingerprint mismatch")
    proof = sources.get("source_proof")
    if not isinstance(proof, dict) or proof.get("status") != "VERIFIED":
        raise invalid("V_SOURCES", "independent source proof is not VERIFIED")
    if proof.get("derivative_fingerprint_sha256") != fingerprint:
        raise invalid("V_SOURCES", "source proof fingerprint mismatch")
    return {"fingerprint": fingerprint, "sources": sources}


# ---------------------------------------------------------------------------
# Campaign verification
# ---------------------------------------------------------------------------


def _write_or_check(path: str, payload: bytes) -> str:
    if os.path.exists(path):
        with open(path, "rb") as handle:
            if handle.read() != payload:
                raise invalid("V_SUMMARY", f"existing sanitized output differs: {path}")
        return "UNCHANGED"
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return "CREATED"


def render_markdown(summary: dict) -> str:
    lines = [
        f"# PR 15I-D3-A evidence — {summary['campaign']}",
        "",
        f"- Campaign kind: `{summary['campaign_kind']}`",
        f"- Verification: `{summary['verification']}`",
        f"- Campaign status: `{summary['campaign_status']}`",
        f"- BASE: `{summary['base_sha']}`",
        f"- Protocol SHA-256: `{summary['protocol_sha256']}`",
        f"- Corpus manifest SHA-256: `{summary['oracle_manifest_sha256']}`",
        "",
        "## Lane timing",
        "",
        "| Lane | Block q/a | Block p/q | Campaign q/a | Campaign p/q |",
        "|---|---|---|---|---|",
    ]
    for lane_id, lane in summary["timing"].items():
        if summary["campaign_kind"] == "control":
            continue
        campaign = lane["campaign"]
        blocks = ", ".join(
            f"{block['block']}:{block['q_a']:.6f}/{block['p_q']:.6f}"
            for block in lane["blocks"]
        )
        lines.append(
            f"| `{lane_id}` | {blocks} | | {campaign['q_a']:.6f} | "
            f"{campaign['p_q']:.6f} |"
        )
    if summary["campaign_kind"] == "paired":
        stage = summary["stage_summary"]
        lines.extend(
            [
                "",
                "## Candidate and intermediate attribution",
                "",
                f"- Stage partition status: `{stage['status']}`",
                f"- Partition violations: {stage['partition']['violations']} / "
                f"{stage['partition']['samples']}",
                "",
                "| Lane | candidate median ns | candidate share | sampled (F/S) | "
                "fallback | intermediate ns | intermediate share | dominant child |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for lane_id, lane in stage["lanes"].items():
            lines.append(
                f"| `{lane_id}` | {lane['candidate_ns']} | {lane['candidate_share']:.6f} | "
                f"{lane['first_samples']}/{lane['steady_samples']} | "
                f"{lane['fallback_samples']} | {lane['intermediate_disjoint_ns']} | "
                f"{lane['intermediate_share']:.6f} | "
                f"{lane['dominant_component'] or '-'} |"
            )
        decision = summary.get("decision") or {}
        lines.extend(
            [
                "",
                "## Closed priority decision",
                "",
                f"- Campaign decision: `{decision.get('verdict', 'NOT_APPLICABLE')}`",
                f"- Candidate material lanes: `{decision.get('both_material_lanes', [])}`",
                f"- Localized component: `{decision.get('localized_component')}`",
                f"- Intermediate component: `{decision.get('intermediate_component')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "This summary is sanitized measurement evidence. Stage values are",
            "instrumentation-inclusive diagnostics, not accepted-build latency or",
            "a claimed removable share. Deterministic FIRST/STEADY samples are not",
            "random profiling. No production optimization is delivered.",
            "",
        ]
    )
    return "\n".join(lines)


def verify_host_quiescence(campaign_dir: str, protocol: dict) -> dict:
    raw = os.path.join(campaign_dir, "raw")
    try:
        record = read_json(os.path.join(raw, "host-quiescence.json"))
        environment = read_json(os.path.join(raw, "environment.json"))
        toolchains = read_json(os.path.join(raw, "toolchains.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_QUIESCENCE", f"malformed host-quiescence evidence: {error}") from error
    if record.get("schema") != "pr15i-d3af-host-quiescence-v1":
        raise invalid("V_QUIESCENCE", "unexpected host-quiescence schema")
    if record.get("base_sha") != BASE_SHA:
        raise invalid("V_QUIESCENCE", "host-quiescence BASE differs")
    expected_protocol = sha256_file(
        os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3a/protocol_v3.json")
    )
    if record.get("protocol_sha256") != expected_protocol:
        raise invalid("V_QUIESCENCE", "host-quiescence protocol hash differs")
    if record.get("host_fingerprint") != environment.get("host_fingerprint"):
        raise invalid("V_QUIESCENCE", "host fingerprint differs from environment evidence")
    if record.get("toolchains") != toolchains:
        raise invalid("V_QUIESCENCE", "host-quiescence toolchains differ")
    if record.get("native_filesystem") is not True:
        raise invalid("V_QUIESCENCE", "host-quiescence filesystem is not native")
    if record.get("precheck_state") != "clear" or record.get("precheck_reason_codes") not in ([], None):
        raise invalid("V_QUIESCENCE", "host-quiescence precheck is not clear")
    precheck = record.get("precheck_path")
    if not isinstance(precheck, str):
        raise invalid("V_QUIESCENCE", "host-quiescence precheck path is missing")
    safe_member(precheck)
    precheck_path = os.path.join(campaign_dir, precheck)
    try:
        precheck_record = read_json(precheck_path)
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_QUIESCENCE", f"malformed host precheck: {error}") from error
    if precheck_record.get("state") != "clear" or precheck_record.get("reason_codes") not in ([], None):
        raise invalid("V_QUIESCENCE", "host precheck record is not clear")
    for key in ("controller_cpu", "adapter_cpu"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("V_QUIESCENCE", f"host-quiescence {key} is not an integer")
    if record["controller_cpu"] == record["adapter_cpu"]:
        raise invalid("V_QUIESCENCE", "controller and adapter CPUs must differ")
    return record


def verify_campaign(
    campaign_dir: str, base_root: str, check_external: bool = True
) -> dict:
    campaign_dir = confined(campaign_dir, TARGET_ROOT, "campaign-dir")
    protocol = load_protocol()
    load_tooling_manifest()
    kind = campaign_kind(os.path.basename(campaign_dir), protocol)
    oracle = load_oracle(base_root)
    oracle_lanes = recompute_oracle(oracle, protocol)
    sealed = verify_seal(campaign_dir, protocol)
    quiescence = verify_host_quiescence(campaign_dir, protocol)
    records = load_slots(campaign_dir, protocol, oracle_lanes["lanes"])
    timing = recompute_timing(records, protocol, kind)

    try:
        stored_timing = read_json(os.path.join(campaign_dir, "raw", "timing.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_TIMING", f"malformed timing.json: {error}") from error
    for lane_id, lane in timing.items():
        stored = stored_timing.get("lanes", {}).get(lane_id)
        if not isinstance(stored, dict):
            raise invalid("V_TIMING", f"timing.json is missing {lane_id}")
        if kind == "control":
            value = stored.get("campaign", {}).get("a1_a2")
            if not isinstance(value, float) or abs(value - lane["campaign"]["a1_a2"]) > 1e-9:
                raise invalid("V_TIMING", f"timing.json {lane_id}/a1_a2 differs")
            for expected, actual in zip(lane["blocks"], stored.get("blocks", [])):
                if not isinstance(actual.get("a1_a2"), float) or abs(
                    actual["a1_a2"] - expected["a1_a2"]
                ) > 1e-9:
                    raise invalid("V_TIMING", f"timing.json {lane_id} block a1_a2 differs")
            if len(stored.get("blocks", [])) != 4:
                raise invalid("V_TIMING", f"timing.json {lane_id} block count")
        else:
            for key in ("q_a", "p_q", "p_a", "a_a_drift"):
                value = stored.get("campaign", {}).get(key)
                if not isinstance(value, float) or abs(value - lane["campaign"][key]) > 1e-9:
                    raise invalid("V_TIMING", f"timing.json {lane_id}/{key} differs")
            if len(stored.get("blocks", [])) != 4:
                raise invalid("V_TIMING", f"timing.json {lane_id} block count")
            for expected, actual in zip(lane["blocks"], stored["blocks"]):
                for key in ("q_a", "p_q", "p_a", "a_a_drift"):
                    if not isinstance(actual.get(key), float) or abs(
                        actual[key] - expected[key]
                    ) > 1e-9:
                        raise invalid("V_TIMING", f"timing.json {lane_id} block {key} differs")

    classification = recompute_classification(timing, protocol, kind)
    if kind == "control":
        if stored_timing.get("tolerated_control_soft_outliers") != classification.get("tolerated"):
            raise invalid("V_TIMING", "tolerated control soft-outlier metadata differs")
    if kind == "paired":
        raw_map = stored_timing.get("timing_lane_qualification")
        if not isinstance(raw_map, dict):
            raise invalid("V_TIMING", "timing_lane_qualification is missing")
        if raw_map != classification.get("lane_qualification"):
            raise invalid("V_TIMING", "timing_lane_qualification differs from recomputation")
    stage_summary = recompute_stages(records, protocol, oracle_lanes["lanes"], kind)
    sources = verify_sources(campaign_dir, kind) if check_external else {"fingerprint": None}
    fingerprint = sources["fingerprint"]
    if kind == "paired" and fingerprint is not None:
        for slot, record in records.items():
            if record["arm"] in ("Q", "P"):
                if record.get("diagnostic_derivative_sha256") != fingerprint:
                    raise invalid("V_SOURCES", f"slot {slot} derivative fingerprint differs")
    if check_external:
        entries = verify_binaries(campaign_dir, protocol, kind)
        verify_slot_binaries(records, entries, protocol, kind)
        layout = verify_index_layout(campaign_dir, protocol, kind, check_files=True)
        for slot, record in records.items():
            if kind == "control":
                expected_digest = sha256_bytes(
                    canonical_json_bytes(
                        {
                            n: layout["digests"]["A1"][n]
                            for n in ("10000", "100000")
                        }
                    )
                )
            else:
                index_arm = "A" if record["arm"] == "A" else "QP"
                expected_digest = sha256_bytes(
                    canonical_json_bytes(
                        {
                            n: layout["digests"][index_arm][n]
                            for n in ("10000", "100000")
                        }
                    )
                )
            if record.get("index_sha256") != expected_digest:
                raise invalid("V_INDEX", f"slot {slot} index digest differs")

    final_qualification = {}
    if kind == "paired":
        for lane_id, item in classification["lane_qualification"].items():
            partition = stage_summary["lanes"][lane_id]["partition"]
            status = item["status"]
            if partition["invalid"] and status == "QUALIFIED":
                status = "DIAGNOSTIC_PERTURBED"
            final_qualification[lane_id] = {
                **item,
                "status": status,
                "eligible": status == "QUALIFIED" and not partition["invalid"],
                "partition_failure_count": sum(partition["violations"].values()),
                "partition_invalid": partition["invalid"],
            }
        if stage_summary["partition"]["invalid"]:
            campaign_status = "D3A_STAGE_PARTITION_INVALID"
            for item in final_qualification.values():
                item["eligible"] = False
        elif all(item["eligible"] for item in final_qualification.values()):
            campaign_status = "D3A_ATTRIBUTION_LOW_INTRUSION"
        else:
            campaign_status = "D3A_ATTRIBUTION_LANE_SCOPED"
    else:
        campaign_status = classification["status"]

    protocol_sha = sha256_file(
        os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3a/protocol_v3.json")
    )
    summary = {
        "schema": "pr15i-d3a-sanitized-summary-v1",
        "campaign": os.path.basename(campaign_dir),
        "campaign_kind": kind,
        "verification": "PASS",
        "campaign_status": campaign_status,
        "reasons": classification["failures"],
        "tolerated_control_soft_outliers": classification.get("tolerated", []),
        "host_quiescence_verified": True,
        "base_sha": BASE_SHA,
        "protocol_sha256": protocol_sha,
        "oracle_manifest_sha256": oracle_lanes["manifest_sha256"],
        "timing": timing,
        "stage_summary": stage_summary,
        "lane_qualification": final_qualification if kind == "paired" else {},
        "decision": (
            campaign_decision(stage_summary, protocol) if kind == "paired" else None
        ),
        "sealed_member_count": len(sealed["seal"]["members"]),
    }
    sanitized_json = canonical_json_bytes(summary) + b"\n"
    sanitized_text = render_markdown(summary).encode("utf-8")
    summary_path = os.path.join(campaign_dir, "sanitized", "summary.json")
    markdown_path = os.path.join(campaign_dir, "sanitized", "summary.md")
    _write_or_check(summary_path, sanitized_json)
    _write_or_check(markdown_path, sanitized_text)
    verification = {
        "schema": "pr15i-d3a-verification-v1",
        "campaign": os.path.basename(campaign_dir),
        "campaign_kind": kind,
        "verifier": "verify.py",
        "verification": "PASS",
        "campaign_status": campaign_status,
        "reasons": classification["failures"],
        "tolerated_control_soft_outliers": classification.get("tolerated", []),
        "member_count": len(sealed["seal"]["members"]),
        "oracle_manifest_sha256": oracle_lanes["manifest_sha256"],
        "stage_partition_status": stage_summary["status"],
        "lane_qualification": final_qualification if kind == "paired" else {},
        "campaign_decision": (summary.get("decision") or {}).get("verdict"),
    }
    _write_or_check(
        os.path.join(campaign_dir, "verification.json"),
        canonical_json_bytes(verification) + b"\n",
    )
    return summary


def verify_control_qualified(control: dict | None) -> bool:
    return control is not None and control["campaign_status"] == "D3A_CONTROL_QUALIFIED"


def _series_control(protocol: dict, control_dir: str | None, base_root: str) -> tuple[dict | None, bool, str | None, str | None]:
    if control_dir is None:
        return None, False, None, None
    name = os.path.basename(os.path.abspath(control_dir))
    parent = os.path.dirname(os.path.abspath(control_dir))
    if name == protocol["control_campaign"]:
        control = verify_campaign(control_dir, base_root, check_external=True)
        retry = os.path.join(parent, protocol["control_retry_campaign"])
        if os.path.isdir(retry):
            raise invalid("V_SERIES", "control 02 exists even though control 01 qualified")
        if control["campaign_status"] != "D3A_CONTROL_QUALIFIED":
            return control, False, None, "control 01 is not qualified"
        return control, True, name, None
    if name == protocol["control_retry_campaign"]:
        first_dir = os.path.join(parent, protocol["control_campaign"])
        if not os.path.isdir(first_dir):
            raise invalid("V_SERIES", "control 02 exists without control 01")
        first = verify_campaign(first_dir, base_root, check_external=True)
        if first["campaign_status"] != "D3A_CONTROL_NOT_QUALIFIED":
            raise invalid("V_SERIES", "control 02 is present but control 01 was not rejected")
        archive = os.path.expanduser(
            "~/.local/share/quervant/benchmark-evidence/pr15i-d3a/fixup-f2/"
            + protocol["control_campaign"] + ".tar.gz"
        )
        sidecar = archive + ".sha256"
        if not (os.path.isfile(archive) and os.path.isfile(sidecar)):
            raise blocked("V_SERIES", "control 01 archive/sidecar is missing")
        with open(sidecar, encoding="utf-8") as handle:
            fields = handle.read().split()
        if len(fields) < 1 or fields[0] != sha256_file(archive):
            raise invalid("V_SERIES", "control 01 archive sidecar mismatch")
        control = verify_campaign(control_dir, base_root, check_external=True)
        if control["campaign_status"] != "D3A_CONTROL_QUALIFIED":
            return control, False, None, "control 02 is not qualified"
        return control, True, name, None
    raise invalid("V_SERIES", f"not a v3 control directory: {name!r}")


def render_aggregate_v3(aggregate: dict) -> str:
    lines = [
        "# PR 15I-D3-A-F2 lane-scoped five-run aggregate",
        "",
        f"- Completion state: `{aggregate.get('completion_state')}`",
        f"- Priority verdict: `{aggregate['verdict']}`",
        f"- Control: `{aggregate.get('control_choice')}`",
        f"- BASE: `{aggregate['base_sha']}`",
        "",
        "| Lane | n eligible | eligible runs | candidate stable | intermediate stable |",
        "|---|---|---|---|---|",
    ]
    stats = aggregate.get("five_run_stats") or {}
    for lane_id, lane in stats.get("lanes", {}).items():
        lines.append(
            f"| `{lane_id}` | {lane['n']} | {lane['run_ids_used']} | "
            f"{lane.get('candidate_material_runs', '-')} | "
            f"{lane.get('intermediate_material_runs', '-')} |"
        )
    lines.extend(
        [
            "",
            "Five run-level observations per lane, not pooled queries. Sampled",
            "candidate children are diagnostic proxies; no optimization is authorized.",
            "",
        ]
    )
    return "\n".join(lines)


def aggregate_series(
    series_root: str, base_root: str, control_dir: str | None = None
) -> dict:
    series_root = confined(series_root, TARGET_ROOT, "series-root")
    protocol = load_protocol()
    load_tooling_manifest()
    names = protocol["campaigns"]
    present = {
        name
        for name in os.listdir(series_root)
        if os.path.isdir(os.path.join(series_root, name))
    }
    if present != set(names):
        missing = sorted(set(names) - present)
        extra = sorted(present - set(names))
        raise blocked("V_SERIES", f"series inventory mismatch; missing={missing} extra={extra}")
    results = []
    for campaign in names:
        directory = os.path.join(series_root, campaign)
        results.append(verify_campaign(directory, base_root, check_external=True))
    ordered = [results[names.index(name)] for name in names]

    control, control_ok, control_choice, control_reason = _series_control(
        protocol, control_dir, base_root
    )
    global_ok = all(
        result["campaign_status"]
        in {"D3A_ATTRIBUTION_LOW_INTRUSION", "D3A_ATTRIBUTION_LANE_SCOPED"}
        and not result["stage_summary"]["partition"]["invalid"]
        for result in ordered
    )
    if not control_ok or not global_ok:
        verdict = "D3A_MEASUREMENT_BLOCKED"
        completion = "D3A_MEASUREMENT_BLOCKED"
        stats = None
        decision = {
            "verdict": verdict,
            "control_qualified": control_ok,
            "control_reason": control_reason,
            "global_integrity": global_ok,
        }
    else:
        stats = lane_scoped_five_run_stats(ordered, protocol)
        decision = lane_scoped_five_run_decision(ordered, stats, protocol)
        verdict = decision["verdict"]
        insufficient = [
            lane for lane in protocol["candidate_priority"]["lanes"]
            if stats["lanes"][lane]["n"] < protocol["lane_scoped_min_eligible_runs"]
        ]
        completion = (
            "D3AF2_MEASUREMENT_PARTIAL"
            if verdict == "D3A_MEASUREMENT_BLOCKED"
            else "D3AF2_ATTRIBUTION_QUALIFIED"
        )
    aggregate = {
        "schema": "pr15i-d3af2-independent-aggregate-v3",
        "completion_state": completion,
        "verdict": verdict,
        "control_qualified": control_ok,
        "control_choice": control_choice,
        "control_reason": control_reason,
        "base_sha": BASE_SHA,
        "runs": names,
        "campaigns": {
            result["campaign"]: {
                "campaign_status": result["campaign_status"],
                "stage_partition_status": result["stage_summary"]["status"],
                "host_quiescence_verified": result.get("host_quiescence_verified", False),
            }
            for result in ordered
        },
        "decision": decision,
        "five_run_stats": stats,
        "protocol_sha256": sha256_file(
            os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3a/protocol_v3.json")
        ),
    }
    _write_or_check(
        os.path.join(series_root, "independent-aggregate-v3.json"),
        canonical_json_bytes(aggregate) + b"\n",
    )
    _write_or_check(
        os.path.join(series_root, "independent-aggregate-v3.md"),
        render_aggregate_v3(aggregate).encode("utf-8"),
    )
    _write_or_check(
        os.path.join(series_root, "five-run-areas-v3.json"),
        canonical_json_bytes({
            "schema": "pr15i-d3af2-five-run-areas-v3",
            "completion_state": completion,
            "verdict": verdict,
            "runs": names,
            "lanes": (stats or {}).get("lanes", {}),
        }) + b"\n",
    )
    _write_or_check(
        os.path.join(series_root, "lane-qualification-v3.json"),
        canonical_json_bytes({
            "schema": "pr15i-d3af2-lane-qualification-v3",
            "runs": {
                result["campaign"]: result.get("lane_qualification", {})
                for result in ordered
            },
        }) + b"\n",
    )
    return aggregate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify PR 15I-D3-A-F five-run evidence.")
    parser.add_argument("--base-root", default=os.path.join(TARGET_ROOT, "sources", "base"))
    parser.add_argument("--campaign-dir")
    parser.add_argument("--series-root")
    parser.add_argument("--control-dir")
    parser.add_argument("--aggregate", action="store_true")
    args = parser.parse_args(argv)
    base_root = os.path.realpath(os.path.abspath(args.base_root))
    try:
        if args.aggregate:
            if not args.series_root:
                raise VerifyError("INVALID", "V_CLI", "--aggregate requires --series-root")
            result = aggregate_series(args.series_root, base_root, args.control_dir)
        else:
            if not args.campaign_dir:
                raise VerifyError("INVALID", "V_CLI", "--campaign-dir is required")
            result = verify_campaign(args.campaign_dir, base_root, check_external=True)
    except VerifyError as error:
        print(f"{error.status}: {error}", file=sys.stderr)
        return 2 if error.status == "INVALID" else 3
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

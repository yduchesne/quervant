#!/usr/bin/env python3
"""Independent verifier for PR 15I-D2-A paired attribution evidence.

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
import os
import shutil
import sys
import tempfile

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET_ROOT = os.path.join(TOOLING_ROOT, "target", "pr15i-d2a")

BASE_SHA = "9429dce99827f25766a92c1fbded8f78a0b168f1"
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
]
COUNTER_LABELS = [
    "matched_docs",
    "scored_docs",
    "candidate_docs",
    "bm25_calls",
    "scoring_map_entries",
    "positive_term_owners",
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
    "eval_residual_ns",
    "candidate_ns",
    "projection_ns",
    "other_ns",
]
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
DERIVATIVE_FILES = (
    "crates/quervant-core/src/search/unified.rs",
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/mod.rs",
    "crates/quervant-core/src/search/d2a_probe.rs",
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

EXPECTED_PROTOCOL = {
    "schema": "pr15i-d2a-scoring-attribution-v1",
    "study_type": "THREE_ARM_SCORE_COST_QUALIFICATION",
    "diagnostic_only": True,
    "base_sha": BASE_SHA,
    "corpus_manifest_sha256": "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151",
    "source_derivation": "DIAGNOSTIC_INSERTION_ONLY_FROM_BASE",
    "arms": ["A", "Q", "P"],
    "arm_operations": {"A": "query", "Q": "query", "P": "query_probe"},
    "q_and_p_exact_same_binary": True,
    "campaigns": ["d2a-unbatched-01", "d2a-unbatched-02"],
    "control_campaign": "d2a-base-aa-01",
    "arm_order_by_block": ["AQPPQA", "PQAAQP", "QAPPAQ", "PAQQAP"],
    "control_arm_order_by_block": [
        "A1A2A2A1",
        "A2A1A1A2",
        "A1A2A2A1",
        "A2A1A1A2",
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
    "stages": STAGE_LABELS,
    "counters": COUNTER_LABELS,
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
    "stage_partition_max_violation_fraction": 0.01,
    "priority_gate": {
        "lanes": [
            "pr15d_v1/100000/medium/k100",
            "pr15d_v1/100000/common/k100",
            "pr15d_v1/100000/common/k10",
        ],
        "min_median_accumulate_ns": 2000000,
        "min_median_accumulate_share": 0.08,
        "min_bm25_calls_per_returned_hit": 10,
        "required_qualifying_lanes_per_campaign": 2,
        "required_campaigns": 2,
    },
    "archive_root_relative": "benchmark-evidence/pr15i-d2a",
    "archive_excludes": ["build/", "indexes/", "corpus/", "sources/"],
}


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
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d2a/tooling_manifest.json")
    try:
        manifest = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_TOOLING", f"cannot read tooling manifest: {error}") from error
    if manifest.get("schema") != "pr15i-d2a-tooling-manifest-v1":
        raise invalid("V_TOOLING", "unexpected tooling manifest schema")
    if manifest.get("base_sha") != BASE_SHA:
        raise invalid("V_TOOLING", "tooling manifest BASE differs")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise invalid("V_TOOLING", "tooling manifest has no files")
    directory = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d2a")
    actual = {
        name
        for name in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, name))
        and name not in ("tooling_manifest.json",)
        and not name.startswith("__pycache__")
    }
    if set(files) != actual:
        raise invalid(
            "V_TOOLING",
            f"tooling manifest file set differs: {sorted(set(files) ^ actual)}",
        )
    for relative, digest in files.items():
        path = os.path.join(directory, relative)
        if sha256_file(path) != digest:
            raise invalid("V_TOOLING", f"tooling manifest hash mismatch: {relative}")
    return manifest


def load_protocol() -> dict:
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d2a/protocol_v1.json")
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
    if name == protocol["control_campaign"]:
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
    temporary = tempfile.mkdtemp(prefix="pr15i-d2a-verify-")
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
    if seal.get("schema") != "pr15i-d2a-seal-v1":
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
    if manifest.get("schema") != "pr15i-d2a-manifest-v1":
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
        if record.get("schema") != "pr15i-d2a-slot-v1":
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
            if probe:
                if not isinstance(stages, list) or len(stages) != 20:
                    raise invalid("V_STAGES", f"slot {entry['slot']} {lane['id']} stage samples")
                if not isinstance(counters, list) or len(counters) != 20:
                    raise invalid("V_COUNTERS", f"slot {entry['slot']} {lane['id']} counter samples")
                for stage in stages:
                    strict_array(stage, 13, f"slot {entry['slot']} {lane['id']} stage")
                for counter in counters:
                    strict_array(counter, 6, f"slot {entry['slot']} {lane['id']} counter")
            else:
                if stages is not None or counters is not None:
                    raise invalid(
                        "V_MODE", f"{arm} slot {entry['slot']} {lane['id']} carries probe fields"
                    )
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


def recompute_classification(timing: dict, protocol: dict, kind: str) -> dict:
    failures = []
    if kind == "control":
        low = protocol["a_a_outlier_block_low"]
        high = protocol["a_a_outlier_block_high"]
        median_low = protocol["a_a_drift_median_min"]
        median_high = protocol["a_a_drift_median_max"]
        hard_low = protocol["a_a_outlier_hard_low"]
        hard_high = protocol["a_a_outlier_hard_high"]
        for lane_id, lane in timing.items():
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
        status = "D2A_CONTROL_QUALIFIED" if not failures else "D2A_CONTROL_NOT_QUALIFIED"
        return {"status": status, "failures": failures}

    low = protocol["a_a_drift_median_min"]
    high = protocol["a_a_drift_median_max"]
    block_low = protocol["a_a_outlier_block_low"]
    block_high = protocol["a_a_outlier_block_high"]
    maximum = protocol["a_a_max_outlier_blocks_per_lane"]
    for lane_id, lane in timing.items():
        drift = lane["campaign"]["a_a_drift"]
        if not (low <= drift <= high):
            failures.append(
                {"lane": lane_id, "gate": "A_A_MEDIAN", "observed": drift, "expected": [low, high]}
            )
        outliers = sum(
            1 for block in lane["blocks"] if not (block_low <= block["a_a_drift"] <= block_high)
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
    if failures:
        return {"status": "D2A_UNSTABLE", "failures": failures}
    guard = protocol["single_block_guard_ceiling"]
    for lane_id, lane in timing.items():
        kind_name = lane["kind"]
        for key, prefix in (("q_a", "q_a"), ("p_q", "p_q")):
            ceiling = (
                protocol[f"{prefix}_ratio_ceiling_low_match"]
                if kind_name == "low_match"
                else protocol[f"{prefix}_ratio_ceiling_medium_common"]
            )
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
                value = block[key]
                if value <= 0 or value > guard:
                    failures.append(
                        {
                            "lane": lane_id,
                            "gate": f"{key.upper()}_BLOCK",
                            "block": block["block"],
                            "observed": value,
                            "guard": guard,
                        }
                    )
    if failures:
        return {"status": "D2A_DIAGNOSTIC_PERTURBED", "failures": failures}
    return {"status": "D2A_ATTRIBUTION_LOW_INTRUSION", "failures": []}


# ---------------------------------------------------------------------------
# Stage partition and ranking
# ---------------------------------------------------------------------------


def decompose(engine_ns: int, stages, counters, expected_hits: int, top_k: int) -> dict:
    stage = strict_array(stages, 13, "stage")
    counter = strict_array(counters, 6, "counter")
    if engine_ns <= 0:
        raise invalid("V_STAGES", "engine_ns is not positive")
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
        score_map,
        score_owner,
        score_accumulate,
    ) = stage
    residual = evaluate - leaf - membership - score
    other = engine_ns - (plan + reader + expand + stats + evaluate + candidate + projection)
    if residual < 0:
        raise invalid("V_STAGE_PARTITION", "evaluate is smaller than its nested children")
    if other < 0:
        raise invalid("V_STAGE_PARTITION", "top-level stages exceed engine_ns")
    categories = {
        "plan_ns": plan,
        "reader_live_ns": reader,
        "expand_ns": expand,
        "stats_ns": stats,
        "leaf_decode_ns": leaf,
        "membership_ns": membership,
        "score_vector_ns": score,
        "eval_residual_ns": residual,
        "candidate_ns": candidate,
        "projection_ns": projection,
        "other_ns": other,
    }
    if sum(categories.values()) != engine_ns:
        raise invalid("V_STAGE_PARTITION", "exclusive partition does not sum to engine_ns")

    matched, scored, candidate_docs, bm25_calls, map_entries, owners = counter
    if not (matched == scored == candidate_docs == bm25_calls == expected_hits):
        raise invalid("V_COUNTER", "matched/scored/candidate/bm25 counters disagree with hits")
    if map_entries != expected_hits:
        raise invalid("V_COUNTER", "scoring_map_entries disagrees with hits")
    expected_owners = 0 if expected_hits == 0 else 1
    if owners != expected_owners:
        raise invalid("V_COUNTER", "positive_term_owners is not the single-term expectation")
    score_sum = score_map + score_owner + score_accumulate
    tolerance = max(
        10_000,
        int(score * 0.02),
    )
    partition_ok = score_sum <= score + tolerance
    returned_hits = min(expected_hits, top_k)
    return {
        "categories": categories,
        "engine_ns": engine_ns,
        "score_map_ns": score_map,
        "score_owner_ns": score_owner,
        "score_accumulate_ns": score_accumulate,
        "score_vector_ns": score,
        "score_partition_sum_ns": score_sum,
        "score_partition_tolerance_ns": tolerance,
        "score_partition_ok": partition_ok,
        "bm25_calls": bm25_calls,
        "returned_hits": returned_hits,
        "expected_hits": expected_hits,
    }


def _nearest_rank(values: list[int], numerator: int) -> int:
    if not values:
        raise invalid("V_STAGE_COUNT", "cannot take a percentile of no samples")
    ordered = sorted(values)
    index = (len(ordered) * numerator + 99) // 100 - 1
    return ordered[max(index, 0)]


def recompute_stages(records: dict, protocol: dict, oracle_lanes: dict, kind: str) -> dict:
    if kind == "control":
        return {
            "schema": "pr15i-d2a-stage-summary-v1",
            "status": "NOT_APPLICABLE",
            "lanes": {},
            "partition": {"violations": 0, "samples": 0, "invalid": False},
            "priority": {
                "quantitative_gate_pass": False,
                "qualifying_lanes": 0,
                "lanes": {},
            },
        }
    plan = slot_schedule(protocol)
    lanes = {}
    samples_seen = 0
    violations = 0
    for lane in lane_descriptors(protocol):
        lane_id = lane["id"]
        samples = []
        sample_blocks = []
        for entry in plan:
            if entry["arm"] != "P":
                continue
            record = records[entry["slot"]]
            item = next(lane for lane in record["lanes"] if lane["id"] == lane_id)
            for engine_ns, stages, counters in zip(
                item["samples_ns"], item["stage_samples"], item["counter_samples"]
            ):
                expected = oracle_lanes[lane_id]
                sample = decompose(
                    engine_ns,
                    stages,
                    counters,
                    expected["total_hits"],
                    lane["k"],
                )
                samples.append(sample)
                sample_blocks.append(entry["block"])
                samples_seen += 1
                if not sample["score_partition_ok"]:
                    violations += 1
        expected_p_samples = 8 * protocol["samples_per_lane_slot"]
        if len(samples) != expected_p_samples:
            raise invalid(
                "V_STAGE_COUNT", f"{lane_id} does not contain {expected_p_samples} P samples"
            )
        summary = {}
        for category in EXCLUSIVE:
            values = [sample["categories"][category] for sample in samples]
            shares = [
                sample["categories"][category] / sample["engine_ns"] for sample in samples
            ]
            summary[category] = {
                "median_ns": _nearest_rank(values, 50),
                "median_share": _nearest_rank([int(share * 1_000_000_000) for share in shares], 50)
                / 1_000_000_000,
                "p95_ns": _nearest_rank(values, 95),
            }
        for name in ("score_map_ns", "score_owner_ns", "score_accumulate_ns"):
            values = [sample[name] for sample in samples]
            shares = [sample[name] / sample["engine_ns"] for sample in samples]
            block_ranges = []
            for block in range(1, protocol["blocks_per_campaign"] + 1):
                block_values = [
                    sample[name]
                    for sample, sample_block in zip(samples, sample_blocks)
                    if sample_block == block
                ]
                block_ranges.append(
                    {
                        "block": block,
                        "min_ns": min(block_values),
                        "max_ns": max(block_values),
                    }
                )
            summary[name] = {
                "median_ns": _nearest_rank(values, 50),
                "median_share": _nearest_rank(
                    [int(share * 1_000_000_000) for share in shares], 50
                )
                / 1_000_000_000,
                "p95_ns": _nearest_rank(values, 95),
                "p99_ns": _nearest_rank(values, 99),
                "blocks": block_ranges,
            }
        summary["bm25_calls"] = samples[0]["bm25_calls"]
        summary["returned_hits"] = samples[0]["returned_hits"]
        summary["expected_hits"] = samples[0]["expected_hits"]
        lanes[lane_id] = summary
    if samples_seen != 8 * len(protocol["lane_ids"]) * protocol["samples_per_lane_slot"]:
        raise invalid("V_STAGE_COUNT", f"unexpected P stage sample count {samples_seen}")
    partition_invalid = (
        violations / samples_seen
    ) > protocol["stage_partition_max_violation_fraction"]
    return {
        "schema": "pr15i-d2a-stage-summary-v1",
        "status": "STAGE_PARTITION_INVALID" if partition_invalid else "QUALIFIED",
        "lanes": lanes,
        "partition": {
            "violations": violations,
            "samples": samples_seen,
            "invalid": partition_invalid,
        },
        "priority": recompute_priority(lanes, protocol),
    }


def recompute_priority(stage_lanes: dict, protocol: dict) -> dict:
    gate = protocol["priority_gate"]
    metrics = {}
    qualifying = []
    for lane_id in gate["lanes"]:
        lane = stage_lanes[lane_id]
        accumulate = lane["score_accumulate_ns"]
        bm25_ratio = None
        summary = stage_lanes[lane_id]
        # Sample-level counts are identical within a lane; recover them from the
        # stored stage summary denominator-free fields.
        returned = summary.get("returned_hits")
        calls = summary.get("bm25_calls")
        if returned and calls is not None:
            bm25_ratio = calls / returned
        passed = (
            accumulate["median_ns"] >= gate["min_median_accumulate_ns"]
            and accumulate["median_share"] >= gate["min_median_accumulate_share"]
            and bm25_ratio is not None
            and bm25_ratio >= gate["min_bm25_calls_per_returned_hit"]
        )
        if passed:
            qualifying.append(lane_id)
        metrics[lane_id] = {
            "median_accumulate_ns": accumulate["median_ns"],
            "median_accumulate_share": accumulate["median_share"],
            "bm25_calls_per_returned_hit": bm25_ratio,
            "passed": passed,
        }
    return {
        "quantitative_gate_pass": len(qualifying)
        >= gate["required_qualifying_lanes_per_campaign"],
        "qualifying_lanes": len(qualifying),
        "lanes": metrics,
    }


# ---------------------------------------------------------------------------
# External evidence (binaries, indexes, tooling)
# ---------------------------------------------------------------------------


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
        if relative == "crates/quervant-core/src/search/d2a_probe.rs":
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
        f"# PR 15I-D2-A evidence — {summary['campaign']}",
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
        "| Lane | Block values | Campaign value |",
        "|---|---|---|",
    ]
    for lane_id, lane in summary["timing"].items():
        campaign = lane["campaign"]
        key = "a1_a2" if summary["campaign_kind"] == "control" else "q_a/p_q/p_a"
        blocks = ", ".join(
            f"{block['block']}:{block.get('a1_a2', block.get('q_a')):.6f}"
            for block in lane["blocks"]
        )
        if summary["campaign_kind"] == "control":
            value = f"{campaign['a1_a2']:.6f}"
        else:
            value = (
                f"q/a={campaign['q_a']:.6f}, p/q={campaign['p_q']:.6f}, "
                f"p/a={campaign['p_a']:.6f}"
            )
        lines.append(f"| `{lane_id}` | {blocks} | {value} |")
    if summary["campaign_kind"] == "paired":
        lines.extend(
            [
                "",
                "## Score-stage partition (instrumented P samples)",
                "",
                f"- Partition status: `{summary['stage_summary']['status']}`",
                f"- Violations: {summary['stage_summary']['partition']['violations']} / "
                f"{summary['stage_summary']['partition']['samples']}",
                f"- Quantitative priority gate: "
                f"`{summary['priority']['quantitative_gate_pass']}`",
                "",
                "| Lane | score_accumulate median ns | share | bm25/returned | passed |",
                "|---|---|---|---|---|",
            ]
        )
        for lane_id, metrics in summary["priority"]["lanes"].items():
            lines.append(
                f"| `{lane_id}` | {metrics['median_accumulate_ns']} | "
                f"{metrics['median_accumulate_share']:.6f} | "
                f"{metrics['bm25_calls_per_returned_hit']:.6f} | "
                f"{metrics['passed']} |"
            )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "This summary is sanitized measurement evidence. Stage values are",
            "instrumentation-inclusive diagnostics, not accepted-build latency or",
            "a claimed removable share. No production optimization is delivered.",
            "",
        ]
    )
    return "\n".join(lines)


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

    if kind == "paired":
        if stage_summary["partition"]["invalid"]:
            campaign_status = "D2A_STAGE_PARTITION_INVALID"
        elif classification["status"] != "D2A_ATTRIBUTION_LOW_INTRUSION":
            campaign_status = classification["status"]
        else:
            campaign_status = classification["status"]
    else:
        campaign_status = classification["status"]

    protocol_sha = sha256_file(
        os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d2a/protocol_v1.json")
    )
    summary = {
        "schema": "pr15i-d2a-sanitized-summary-v1",
        "campaign": os.path.basename(campaign_dir),
        "campaign_kind": kind,
        "verification": "PASS",
        "campaign_status": campaign_status,
        "reasons": classification["failures"],
        "base_sha": BASE_SHA,
        "protocol_sha256": protocol_sha,
        "oracle_manifest_sha256": oracle_lanes["manifest_sha256"],
        "timing": timing,
        "stage_summary": stage_summary,
        "priority": (
            stage_summary["priority"] if kind == "paired" else
            {"quantitative_gate_pass": False, "qualifying_lanes": 0, "lanes": {}}
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
        "schema": "pr15i-d2a-verification-v1",
        "campaign": os.path.basename(campaign_dir),
        "campaign_kind": kind,
        "verifier": "verify.py",
        "verification": "PASS",
        "campaign_status": campaign_status,
        "reasons": classification["failures"],
        "member_count": len(sealed["seal"]["members"]),
        "oracle_manifest_sha256": oracle_lanes["manifest_sha256"],
        "stage_partition_status": stage_summary["status"],
        "priority_gate": summary["priority"]["quantitative_gate_pass"],
    }
    _write_or_check(
        os.path.join(campaign_dir, "verification.json"),
        canonical_json_bytes(verification) + b"\n",
    )
    return summary


def series_verdict(
    control_ok: bool | None, qualified: list[bool], gate_passes: list[bool]
) -> str:
    if control_ok is False or not all(qualified):
        return "D2A_ATTRIBUTION_NOT_QUALIFIED"
    if all(gate_passes):
        return "D2A_SCORE_COST_WORTH_DESIGNING"
    if any(gate_passes):
        return "D2A_SCORE_COST_INCONCLUSIVE"
    return "D2A_SCORE_COST_LOW_PRIORITY"


def aggregate_series(
    series_root: str, base_root: str, control_dir: str | None = None
) -> dict:
    series_root = confined(series_root, TARGET_ROOT, "series-root")
    protocol = load_protocol()
    results = {}
    for campaign in protocol["campaigns"]:
        directory = os.path.join(series_root, campaign)
        if not os.path.isdir(directory):
            raise blocked("V_SERIES", f"missing campaign directory {directory}")
        results[campaign] = verify_campaign(directory, base_root, check_external=True)
    expected = set(protocol["campaigns"])
    present = {
        name
        for name in os.listdir(series_root)
        if os.path.isdir(os.path.join(series_root, name))
    }
    if present != expected:
        raise invalid("V_SERIES", f"unexpected campaign directories: {sorted(present ^ expected)}")

    control = None
    if control_dir is not None:
        control = verify_campaign(control_dir, base_root, check_external=True)

    qualified = [
        result["campaign_status"] == "D2A_ATTRIBUTION_LOW_INTRUSION"
        and not result["stage_summary"]["partition"]["invalid"]
        for result in results.values()
    ]
    control_ok = control is not None and control["campaign_status"] == "D2A_CONTROL_QUALIFIED"
    gate_passes = [
        result["priority"]["quantitative_gate_pass"] for result in results.values()
    ]
    verdict = series_verdict(
        control_ok if control is not None else None, qualified, gate_passes
    )
    aggregate = {
        "schema": "pr15i-d2a-independent-aggregate-v1",
        "verdict": verdict,
        "control_qualified": control_ok if control is not None else None,
        "campaigns": {
            name: {
                "campaign_status": result["campaign_status"],
                "stage_partition_status": result["stage_summary"]["status"],
                "priority_gate": result["priority"]["quantitative_gate_pass"],
                "qualifying_lanes": result["priority"]["qualifying_lanes"],
            }
            for name, result in results.items()
        },
        "protocol_sha256": sha256_file(
            os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d2a/protocol_v1.json")
        ),
    }
    destination = os.path.join(series_root, "independent-aggregate.json")
    _write_or_check(
        destination, canonical_json_bytes(aggregate) + b"\n"
    )
    return aggregate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify PR 15I-D2-A evidence.")
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

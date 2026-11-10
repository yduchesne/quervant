#!/usr/bin/env python3
"""Independent verifier for PR 15I-D0 paired attribution evidence.

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
TARGET_ROOT = os.path.join(TOOLING_ROOT, "target", "pr15i-d0")

BASE_SHA = "7237bce325834d6cc1c73735697be29bc60ef16b"
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
CLASS_TERMS = {
    "absent": ("key", "never"),
    "rare": ("key", "singleton"),
    "medium": ("group", "medium"),
    "common": ("key", "common"),
}
HYPOTHESIS_ORDER = [
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
    "crates/quervant-core/src/search/d0_probe.rs",
    "crates/quervant-core/Cargo.toml",
    "benchmarks/pr15d/adapters/quervant/src/main.rs",
)

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


def load_protocol() -> dict:
    path = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d0/protocol_v1.json")
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
    temporary = tempfile.mkdtemp(prefix="pr15i-d0-verify-")
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


def required_members() -> list[str]:
    members = list(RAW_MEMBERS)
    members.extend(f"raw/slots/slot-{slot:02d}.json" for slot in range(1, 25))
    for slot in range(1, 25):
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


def verify_seal(campaign_dir: str) -> dict:
    seal_path = os.path.join(campaign_dir, "raw", "seal.json")
    if not os.path.isfile(seal_path):
        raise blocked("V_SEAL", "raw/seal.json is missing")
    try:
        seal = read_json(seal_path)
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_SEAL", f"malformed seal: {error}") from error
    if seal.get("schema") != "pr15i-d0-seal-v1":
        raise invalid("V_SEAL", "unexpected seal schema")
    if seal.get("campaign") != os.path.basename(campaign_dir):
        raise invalid("V_SEAL", "seal campaign name mismatch")
    members = seal.get("members")
    if not isinstance(members, dict):
        raise invalid("V_SEAL", "seal members are not a map")
    if "raw/seal.json" in members:
        raise invalid("V_SEAL", "seal includes itself")
    expected = set(required_members()) | {"raw/manifest.json"}
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
    if manifest.get("schema") != "pr15i-d0-manifest-v1":
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
        expected_counts.get("slots") != 24
        or expected_counts.get("timed_observations") != 4320
        or expected_counts.get("warmups") != 1080
        or expected_counts.get("contention_probes") != 48
        or expected_counts.get("index_builds") != 4
        or expected_counts.get("p_stage_samples") != 1440
        or expected_counts.get("stage_labels") != STAGE_LABELS
        or expected_counts.get("counter_labels") != COUNTER_LABELS
    ):
        raise invalid("V_SEAL", "manifest expected counts differ from the protocol")
    return {"seal": seal, "manifest": manifest}


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
    plan = slot_schedule(protocol)
    records = {}
    for entry in plan:
        path = os.path.join(campaign_dir, "raw", "slots", f"slot-{entry['slot']:02d}.json")
        if not os.path.isfile(path):
            raise blocked("V_SLOT", f"missing slot file {path}")
        try:
            record = read_json(path)
        except (OSError, json.JSONDecodeError) as error:
            raise invalid("V_SLOT", f"malformed slot {entry['slot']}: {error}") from error
        if record.get("schema") != "pr15i-d0-slot-v1":
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
            if arm == "P":
                if not isinstance(stages, list) or len(stages) != 20:
                    raise invalid("V_STAGES", f"slot {entry['slot']} {lane['id']} stage samples")
                if not isinstance(counters, list) or len(counters) != 20:
                    raise invalid("V_COUNTERS", f"slot {entry['slot']} {lane['id']} counter samples")
                for stage in stages:
                    strict_array(stage, 10, f"slot {entry['slot']} {lane['id']} stage")
                for counter in counters:
                    strict_array(counter, 3, f"slot {entry['slot']} {lane['id']} counter")
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


def recompute_timing(records: dict, protocol: dict) -> dict:
    plan = slot_schedule(protocol)
    timed = 0
    for record in records.values():
        for lane in record["lanes"]:
            timed += len(lane["samples_ns"])
    if timed != 24 * 9 * 20:
        raise invalid("V_COUNT", f"expected 4320 timed observations, found {timed}")
    timing = {}
    for lane in lane_descriptors(protocol):
        lane_id = lane["id"]
        values = {}
        for entry in plan:
            record = records[entry["slot"]]
            item = next(lane for lane in record["lanes"] if lane["id"] == lane_id)
            values.setdefault((entry["arm"], entry["block"]), []).append(
                median20(item["samples_ns"])
            )
        blocks = []
        drift, qa, pq, pa = [], [], [], []
        for block in range(1, 5):
            a = values[("A", block)]
            q = values[("Q", block)]
            p = values[("P", block)]
            if len(a) != 2 or len(q) != 2 or len(p) != 2:
                raise invalid("V_COUNT", f"{lane_id} block {block} slot count")
            a_mean = (a[0] + a[1]) / 2
            q_mean = (q[0] + q[1]) / 2
            p_mean = (p[0] + p[1]) / 2
            if a_mean <= 0 or q_mean <= 0 or p_mean <= 0:
                raise invalid("V_RATIO", f"{lane_id} block {block} non-positive median")
            drift.append(a[1] / a[0])
            qa.append(q_mean / a_mean)
            pq.append(p_mean / q_mean)
            pa.append(p_mean / a_mean)
            blocks.append(
                {
                    "block": block,
                    "q_a": qa[-1],
                    "p_q": pq[-1],
                    "p_a": pa[-1],
                    "a_a_drift": drift[-1],
                }
            )
        timing[lane_id] = {
            "class": lane["class"],
            "kind": lane["kind"],
            "blocks": blocks,
            "q_a": median_of_four(qa),
            "p_q": median_of_four(pq),
            "p_a": median_of_four(pa),
            "a_a_drift": median_of_four(drift),
        }
    return timing


def recompute_classification(timing: dict, protocol: dict) -> dict:
    failures = []
    for lane_id, lane in timing.items():
        drift = lane["a_a_drift"]
        if not (protocol["a_a_drift_median_min"] <= drift <= protocol["a_a_drift_median_max"]):
            failures.append(
                {"lane": lane_id, "gate": "A_A_MEDIAN", "observed": drift}
            )
        outliers = sum(
            1
            for block in lane["blocks"]
            if not (
                protocol["a_a_outlier_block_low"]
                <= block["a_a_drift"]
                <= protocol["a_a_outlier_block_high"]
            )
        )
        if outliers > protocol["a_a_max_outlier_blocks_per_lane"]:
            failures.append(
                {"lane": lane_id, "gate": "A_A_OUTLIER_BLOCKS", "observed": outliers}
            )
    if failures:
        return {"status": "D0_UNSTABLE", "failures": failures}
    for lane_id, lane in timing.items():
        if lane["kind"] == "low_match":
            qa_ceiling = protocol["q_a_ratio_ceiling_low_match"]
            pq_ceiling = protocol["p_q_ratio_ceiling_low_match"]
        else:
            qa_ceiling = protocol["q_a_ratio_ceiling_medium_common"]
            pq_ceiling = protocol["p_q_ratio_ceiling_medium_common"]
        guard = protocol["single_block_guard_ceiling"]
        if lane["q_a"] > qa_ceiling:
            failures.append(
                {"lane": lane_id, "gate": "Q_A_MEDIAN", "observed": lane["q_a"], "ceiling": qa_ceiling}
            )
        if lane["p_q"] > pq_ceiling:
            failures.append(
                {"lane": lane_id, "gate": "P_Q_MEDIAN", "observed": lane["p_q"], "ceiling": pq_ceiling}
            )
        for block in lane["blocks"]:
            for key in ("q_a", "p_q"):
                if block[key] <= 0 or block[key] > guard:
                    failures.append(
                        {
                            "lane": lane_id,
                            "gate": f"{key.upper()}_BLOCK",
                            "block": block["block"],
                            "observed": block[key],
                            "guard": guard,
                        }
                    )
    if failures:
        return {"status": "D0_DIAGNOSTIC_PERTURBED", "failures": failures}
    return {"status": "D0_ATTRIBUTION_LOW_INTRUSION", "failures": []}


# ---------------------------------------------------------------------------
# Stage partition and ranking
# ---------------------------------------------------------------------------


def decompose(engine_ns: int, stages, counters, total_hits: int) -> dict:
    stage = strict_array(stages, 10, "stage")
    counter = strict_array(counters, 3, "counter")
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
    if not (counter[0] == counter[1] == counter[2] == total_hits):
        raise invalid("V_COUNTER", "matched/scored/candidate counters disagree with hits")
    return categories


def recompute_stages(records: dict, protocol: dict, oracle_lanes: dict) -> dict:
    plan = slot_schedule(protocol)
    lanes = {}
    samples_seen = 0
    for lane in lane_descriptors(protocol):
        lane_id = lane["id"]
        samples = []
        for entry in plan:
            if entry["arm"] != "P":
                continue
            record = records[entry["slot"]]
            item = next(lane for lane in record["lanes"] if lane["id"] == lane_id)
            for engine_ns, stages, counters in zip(
                item["samples_ns"], item["stage_samples"], item["counter_samples"]
            ):
                expected = oracle_lanes[lane_id]
                samples.append(
                    (
                        decompose(
                            engine_ns, stages, counters, expected["total_hits"]
                        ),
                        engine_ns,
                    )
                )
                samples_seen += 1
        if len(samples) != 160:
            raise invalid("V_STAGE_COUNT", f"{lane_id} does not contain 160 P samples")
        summary = {}
        for category in EXCLUSIVE:
            values = sorted(sample[category] for sample, _ in samples)
            shares = sorted(sample[category] / engine for sample, engine in samples)
            summary[category] = {
                "median_ns": values[(len(values) * 50 + 99) // 100 - 1],
                "median_share": shares[(len(shares) * 50 + 99) // 100 - 1],
                "p95_ns": values[(len(values) * 95 + 99) // 100 - 1],
            }
        lanes[lane_id] = summary
    if samples_seen != 8 * 9 * 20:
        raise invalid("V_STAGE_COUNT", f"expected 1440 P stage samples, found {samples_seen}")
    return lanes


def recompute_ranking(stage_lanes: dict) -> dict:
    medium = "pr15d_v1/100000/medium/k100"
    common = "pr15d_v1/100000/common/k100"
    common10 = "pr15d_v1/100000/common/k10"
    absent = "pr15d_v1/100000/absent/k100"
    rare = "pr15d_v1/100000/rare/k100"

    def value(lane_id: str, category: str) -> int:
        if category == "other_ns":
            return (
                stage_lanes[lane_id]["other_ns"]["median_ns"]
                + stage_lanes[lane_id]["eval_residual_ns"]["median_ns"]
            )
        return stage_lanes[lane_id][category]["median_ns"]

    def share(lane_id: str, category: str) -> float:
        if category == "other_ns":
            return (
                stage_lanes[lane_id]["other_ns"]["median_share"]
                + stage_lanes[lane_id]["eval_residual_ns"]["median_share"]
            )
        return stage_lanes[lane_id][category]["median_share"]

    register = []
    for order, (hypothesis, category) in enumerate(HYPOTHESIS_ORDER):
        register.append(
            {
                "id": hypothesis,
                "category": category,
                "order": order,
                "medium_k100_ns": value(medium, category),
                "common_k100_ns": value(common, category),
                "common_k10_ns": value(common10, category),
                "absent_k100_ns": value(absent, category),
                "rare_k100_ns": value(rare, category),
                "possible_scope": any(
                    share(lane, category) >= 0.20
                    for lane in (medium, common, common10, absent, rare)
                ),
            }
        )
    primary = sorted(register, key=lambda item: (-item["common_k100_ns"], item["order"]))
    return {
        "primary": [item["id"] for item in primary],
        "absent": [item["id"] for item in sorted(register, key=lambda item: (-item["absent_k100_ns"], item["order"]))],
        "rare": [item["id"] for item in sorted(register, key=lambda item: (-item["rare_k100_ns"], item["order"]))],
        "register": register,
        "other_tops": primary[0]["id"] == "H-OTHER",
    }


# ---------------------------------------------------------------------------
# External evidence (binaries, indexes, tooling)
# ---------------------------------------------------------------------------


def verify_binaries(campaign_dir: str) -> dict:
    try:
        record = read_json(os.path.join(campaign_dir, "raw", "binaries.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_BINARY", f"malformed binaries.json: {error}") from error
    entries = {}
    for arm in ("A", "QP"):
        entry = record.get(arm)
        if not isinstance(entry, dict):
            raise invalid("V_BINARY", f"missing {arm} binary record")
        path = entry.get("path")
        if not isinstance(path, str) or not os.path.isfile(path):
            raise blocked("V_BINARY", f"{arm} binary is unavailable")
        digest = sha256_file(path)
        if digest != entry.get("sha256"):
            raise invalid("V_BINARY", f"{arm} binary digest changed")
        entries[arm] = {"path": path, "sha256": digest}
    if entries["A"]["sha256"] == entries["QP"]["sha256"]:
        raise invalid("V_BINARY", "A and Q/P binary digests are identical")
    if record.get("q_and_p_exact_same_binary") is not True:
        raise invalid("V_BINARY", "Q/P same-binary claim was not asserted")
    return entries


def verify_slot_binaries(records: dict, entries: dict, protocol: dict) -> None:
    for slot, record in records.items():
        arm = record["arm"]
        expected = entries["QP" if arm in ("Q", "P") else "A"]["sha256"]
        if record.get("binary_sha256") != expected:
            raise invalid("V_BINARY", f"slot {slot} binary digest differs for arm {arm}")
        if arm in ("Q", "P") and record.get("diagnostic_derivative_sha256") is None:
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


def verify_index_layout(campaign_dir: str, protocol: dict, check_files: bool = True) -> dict:
    try:
        layout = read_json(os.path.join(campaign_dir, "raw", "index-layout.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_INDEX", f"malformed index-layout.json: {error}") from error
    builds = layout.get("builds")
    if not isinstance(builds, dict) or set(builds) != {"A", "QP"}:
        raise invalid("V_INDEX", "index layout must describe A and QP")
    digests = {}
    for arm in ("A", "QP"):
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
    for n in ("10000", "100000"):
        if digests["A"][n] != digests["QP"][n]:
            raise invalid("V_INDEX", f"A/QP index digests differ for N={n}")
    sentinel = builds["A"].get("100000", {})
    if sentinel.get("committed_index_bytes") != protocol["100k_lz4_committed_index_sentinel"]:
        raise invalid("V_INDEX_FORMAT", "100K committed index sentinel differs")
    if sentinel.get("stored_bytes") != protocol["100k_lz4_stored_section_sentinel"]:
        raise invalid("V_INDEX_FORMAT", "100K stored section sentinel differs")
    return {"digests": digests, "layout": layout}


def verify_sources(campaign_dir: str) -> dict:
    try:
        sources = read_json(os.path.join(campaign_dir, "raw", "sources.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_SOURCES", f"malformed sources.json: {error}") from error
    inventory = sources.get("source_inventory")
    if not isinstance(inventory, dict) or set(inventory) != set(DERIVATIVE_FILES):
        raise invalid("V_SOURCES", "source inventory does not cover the six derivative paths")
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
    tooling = sources.get("tooling")
    if not isinstance(tooling, dict) or not tooling:
        raise invalid("V_SOURCES", "tooling hashes are missing")
    for relative, digest in tooling.items():
        path = os.path.join(TOOLING_ROOT, relative)
        if not os.path.isfile(path):
            raise blocked("V_SOURCES", f"tooling file is unavailable: {relative}")
        if sha256_file(path) != digest:
            raise invalid("V_SOURCES", f"tooling hash mismatch for {relative}")
    proof = sources.get("source_proof")
    if not isinstance(proof, dict) or proof.get("status") != "VERIFIED":
        raise invalid("V_SOURCES", "independent source proof is not VERIFIED")
    if proof.get("derivative_fingerprint_sha256") != fingerprint:
        raise invalid("V_SOURCES", "source proof fingerprint mismatch")
    return {"fingerprint": fingerprint, "sources": sources}


# ---------------------------------------------------------------------------
# Campaign verification
# ---------------------------------------------------------------------------


def verify_campaign(
    campaign_dir: str, checkout_root: str, check_external: bool = True
) -> dict:
    campaign_dir = confined(campaign_dir, TARGET_ROOT, "campaign-dir")
    protocol = load_protocol()
    oracle = load_oracle(checkout_root)
    oracle_lanes = recompute_oracle(oracle, protocol)
    sealed = verify_seal(campaign_dir)
    records = load_slots(campaign_dir, protocol, oracle_lanes["lanes"])
    timing = recompute_timing(records, protocol)

    try:
        stored_timing = read_json(os.path.join(campaign_dir, "raw", "timing.json"))
    except (OSError, json.JSONDecodeError) as error:
        raise invalid("V_TIMING", f"malformed timing.json: {error}") from error
    for lane_id, lane in timing.items():
        stored = stored_timing.get("lanes", {}).get(lane_id)
        if not isinstance(stored, dict):
            raise invalid("V_TIMING", f"timing.json is missing {lane_id}")
        for key in ("q_a", "p_q", "p_a", "a_a_drift"):
            value = stored.get("campaign", {}).get(key)
            if not isinstance(value, float) or abs(value - lane[key]) > 1e-9:
                raise invalid("V_TIMING", f"timing.json {lane_id}/{key} differs")
        if len(stored.get("blocks", [])) != 4:
            raise invalid("V_TIMING", f"timing.json {lane_id} block count")
        for expected, actual in zip(lane["blocks"], stored["blocks"]):
            for key in ("q_a", "p_q", "p_a", "a_a_drift"):
                if not isinstance(actual.get(key), float) or abs(actual[key] - expected[key]) > 1e-9:
                    raise invalid("V_TIMING", f"timing.json {lane_id} block {key} differs")

    classification = recompute_classification(timing, protocol)
    stage_lanes = recompute_stages(records, protocol, oracle_lanes["lanes"])
    ranking = None
    ranking_status = "D0_RANKING_NOT_QUALIFIED"
    if classification["status"] == "D0_ATTRIBUTION_LOW_INTRUSION":
        ranking = recompute_ranking(stage_lanes)
        ranking_status = "QUALIFIED_NONCAUSAL_REGISTER"
    sources = verify_sources(campaign_dir) if check_external else {"fingerprint": None}
    fingerprint = sources["fingerprint"]
    for slot, record in records.items():
        if record["arm"] in ("Q", "P") and fingerprint is not None:
            if record.get("diagnostic_derivative_sha256") != fingerprint:
                raise invalid("V_SOURCES", f"slot {slot} derivative fingerprint differs")
    if check_external:
        entries = verify_binaries(campaign_dir)
        verify_slot_binaries(records, entries, protocol)
        verify_index_layout(campaign_dir, protocol, check_files=True)

    return {
        "schema": "pr15i-d0-verification-v1",
        "campaign": os.path.basename(campaign_dir),
        "status": "VERIFIED",
        "classification": classification["status"],
        "failures": classification["failures"],
        "timing": timing,
        "stage_lanes": stage_lanes,
        "ranking_status": ranking_status,
        "ranking": ranking,
        "oracle_manifest_sha256": oracle_lanes["manifest_sha256"],
        "sealed_member_count": len(sealed["seal"]["members"]),
    }


def aggregate_series(series_root: str, checkout_root: str) -> dict:
    series_root = confined(series_root, TARGET_ROOT, "series-root")
    protocol = load_protocol()
    results = {}
    for campaign in protocol["campaigns"]:
        directory = os.path.join(series_root, campaign)
        if not os.path.isdir(directory):
            raise blocked("V_SERIES", f"missing campaign directory {directory}")
        results[campaign] = verify_campaign(directory, checkout_root, check_external=True)
    expected = set(protocol["campaigns"])
    present = {
        name
        for name in os.listdir(series_root)
        if os.path.isdir(os.path.join(series_root, name))
    }
    if present != expected:
        raise invalid("V_SERIES", f"unexpected campaign directories: {sorted(present ^ expected)}")
    status = series_status({name: result["classification"] for name, result in results.items()})
    aggregate = {
        "schema": "pr15i-d0-independent-aggregate-v1",
        "status": status,
        "campaigns": {
            name: {
                "classification": result["classification"],
                "failures": result["failures"],
                "ranking_status": result["ranking_status"],
            }
            for name, result in results.items()
        },
        "ranking_qualified": status == "D0_ATTRIBUTION_LOW_INTRUSION",
    }
    destination = os.path.join(series_root, "independent-aggregate.json")
    if os.path.exists(destination):
        raise VerifyError("INVALID", "V_SERIES", "independent-aggregate.json already exists")
    temporary = destination + ".tmp"
    with open(temporary, "xb") as handle:
        handle.write(canonical_json_bytes(aggregate) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    return aggregate


def series_status(statuses: dict) -> str:
    values = list(statuses.values())
    if any(value == "D0_UNSTABLE" for value in values):
        return "D0_UNSTABLE"
    if all(value == "D0_ATTRIBUTION_LOW_INTRUSION" for value in values):
        return "D0_ATTRIBUTION_LOW_INTRUSION"
    return "D0_DIAGNOSTIC_PERTURBED"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify PR 15I-D0 evidence.")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--campaign-dir")
    parser.add_argument("--series-root")
    parser.add_argument("--aggregate", action="store_true")
    args = parser.parse_args(argv)
    checkout_root = os.path.realpath(os.path.abspath(args.checkout_root))
    try:
        if args.aggregate:
            if not args.series_root:
                raise VerifyError("INVALID", "V_CLI", "--aggregate requires --series-root")
            result = aggregate_series(args.series_root, checkout_root)
        else:
            if not args.campaign_dir:
                raise VerifyError("INVALID", "V_CLI", "--campaign-dir is required")
            result = verify_campaign(args.campaign_dir, checkout_root, check_external=True)
    except VerifyError as error:
        print(f"{error.status}: {error}", file=sys.stderr)
        return 2 if error.status == "INVALID" else 3
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

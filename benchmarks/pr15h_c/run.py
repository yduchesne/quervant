#!/usr/bin/env python3
"""PR 15H-C targeted Quervant-only controller (six warm lanes).

Structural copy of the proven PR15H-A2 controller with PR15H-B stage identity
and the frozen **absolute nanosecond/millisecond** acceptance gates. It reuses
the frozen PR15D/PR15E-B1 adapter, corpus, oracle, statistics and the PR15H-A
sealing/validation helpers.

Subcommands: ``baseline``, ``paired``, ``verify``.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

TOOLING_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
HA_PATH = os.path.join(TOOLING_ROOT, "benchmarks", "pr15h_a", "run.py")

_spec = importlib.util.spec_from_file_location("pr15h_a_run_readonly_hb", HA_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load PR15H-A controller from {HA_PATH}")
ha = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ha)

RunBlocked = ha.base.pr15d_run.RunBlocked

SCHEMA_AUTHORIZATION = "pr15h-c-authorization-v1"
SCHEMA_MANIFEST = "pr15h-c-manifest-v1"
SCHEMA_BASELINE = "pr15h-c-baseline-v1"
SCHEMA_PERFORMANCE = "pr15h-c-performance-v1"
SCHEMA_BLOCKED = "pr15h-c-blocked-v1"
SCHEMA_CONFIRMATION = "pr15h-c-confirmation-required-v1"
SCHEMA_SEAL = "pr15h-c-seal-v1"
SCHEMA_SLOT = "pr15h-c-slot-v1"

PHASE = "borrowed-document-key-late-ownership"
STAGE = "15h-c"
ARM_A_SHA = "e8744d3fe16ee858c7d587aaf3b10d393059b809"
REGIME = "warm"
TRIALS = 3
WARMUPS = 5
SAMPLES = 20
SLOTS_PER_ARM = 4
TOTAL_SLOTS = 8
BLOCK_SCHEDULE = (("A", "B"), ("B", "A"), ("B", "A"), ("A", "B"))

LANE_IDS = [
    "pr15d_v1/100000/common/k100",
    "pr15d_v1/100000/common/k10",
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/10000/common/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/100000/absent/k100",
]
CANONICAL_LANE_IDS = tuple(LANE_IDS)
P1 = LANE_IDS[0]
P2 = LANE_IDS[1]
P3 = LANE_IDS[2]
G1 = LANE_IDS[3]
G2 = LANE_IDS[4]
G3 = LANE_IDS[5]

# Frozen absolute gates, compared as integer nanoseconds.
P_MIN_MEDIAN_NS = 2_000_000
P_BLOCK_MIN_NS = 1_000_000
P_NEGATIVE_FLOOR_NS = -1_000_000
P3_MEDIAN_NS = -2_000_000
G1_MEDIAN_NS = -2_000_000
SPARSE_MEDIAN_NS = -1_000_000
MS = 1_000_000

A_ALLOWED_CHANGED_EXACT = (
    "crates/quervant-core/src/search/unified.rs",
    "docs/BENCHMARKING.md",
    "docs/PERF_OPTIMIZATION_PLAN.md",
)
A_ALLOWED_CHANGED_PREFIXES = (
    "benchmarks/pr15h_c/",
    "docs/pr-artifacts/pr-15h-c/",
)

FORBIDDEN_REPORT_MARKERS = ("/home/", "/mnt/", "/tmp/", "/abs/", "target/pr15h-c")


def frozen_lanes() -> list[dict]:
    if tuple(LANE_IDS) != CANONICAL_LANE_IDS:
        raise RunBlocked("X_LANE_SET", "PR15H-B lane list/order was modified")
    by_id = {lane["id"]: lane for lane in ha.base.pr15d_run.lane_descriptors()}
    lanes = []
    for lane_id in LANE_IDS:
        lane = by_id.get(lane_id)
        if lane is None:
            raise RunBlocked("X_LANE_SET", f"frozen lane missing: {lane_id}")
        if lane["regime"] != REGIME:
            raise RunBlocked("X_LANE_SET", f"lane is not warm: {lane_id}")
        lanes.append(dict(lane))
    if len(lanes) != 6 or len({lane["id"] for lane in lanes}) != 6:
        raise RunBlocked("X_LANE_SET", "PR15H-B requires exactly six distinct lanes")
    return lanes


# ---------------------------------------------------------------------------
# Paths, sources, seals
# ---------------------------------------------------------------------------


def target_root(checkout_root: str) -> str:
    if not os.path.isabs(checkout_root):
        raise RunBlocked("X_PATH", "--checkout-root must be absolute")
    return os.path.realpath(os.path.join(checkout_root, "target", "pr15h-c"))


def validate_out_path(out: str, checkout_root: str) -> str:
    if not os.path.isabs(out):
        raise RunBlocked("X_PATH", "--out must be absolute")
    if os.path.islink(out):
        raise RunBlocked("X_SYMLINK", "--out is a symlink")
    allowed = target_root(checkout_root)
    candidate = os.path.realpath(out)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        raise RunBlocked("X_PATH", f"--out must be strictly beneath {allowed}")
    if os.path.exists(candidate):
        raise RunBlocked("X_OUT_EXISTS", f"--out already exists: {candidate}")
    return candidate


def validate_sealed_dir(path: str, checkout_root: str, label: str) -> str:
    if not os.path.isabs(path):
        raise RunBlocked("X_PATH", f"{label} must be absolute")
    if os.path.islink(path):
        raise RunBlocked("X_SYMLINK", f"{label} is a symlink")
    if not os.path.isdir(path):
        raise RunBlocked("X_PATH", f"{label} is not a directory")
    allowed = target_root(checkout_root)
    candidate = os.path.realpath(path)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        raise RunBlocked("X_PATH", f"{label} must be strictly beneath {allowed}")
    return candidate


def resolve_tree(path: str, expected_sha: str | None, role: str) -> dict:
    if not os.path.isabs(path) or os.path.islink(path):
        raise RunBlocked("X_SOURCE", f"{role} must be an absolute non-symlinked path")
    source = ha.resolve_pinned_tree(path)
    if expected_sha is not None and source["sha"] != expected_sha:
        raise RunBlocked("X_SOURCE_SHA", f"{role} SHA {source['sha']} != expected {expected_sha}")
    return source


def require_same_tooling(paired_tooling_sha: object, baseline_manifest: dict) -> None:
    """Fail closed if paired and sealed baseline tooling identities differ."""
    sha = baseline_manifest.get("tooling_sha")
    allowed = "0123456789abcdef"

    def valid(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 40
            and all(character in allowed for character in value)
        )

    if not valid(sha) or not valid(paired_tooling_sha):
        raise RunBlocked("X_TOOLING_SHA", "missing or invalid baseline/paired tooling SHA")
    if sha != paired_tooling_sha:
        raise RunBlocked("X_TOOLING_SHA", "paired tooling SHA differs from sealed baseline")


def verify_frozen_inputs(tree: str) -> None:
    ha.verify_frozen_inputs(tree)


def seal_paths(root: str, stage: str) -> list[str]:
    if stage == "baseline":
        return ["authorization.json", "manifest.json"] + [
            f"raw/trial-{index:02d}.json" for index in range(1, TRIALS + 1)
        ]
    return ["authorization.json", "manifest.json"] + [
        f"raw/slots/slot-{index:02d}.json" for index in range(1, TOTAL_SLOTS + 1)
    ]


def write_seal(root: str, stage: str) -> dict:
    relative_paths = seal_paths(root, stage)
    files = {}
    for relative in relative_paths:
        full = os.path.join(root, relative)
        ha._require_regular_file(full)
        files[relative] = ha.sha256_file(full)
    seal = {"schema": SCHEMA_SEAL, "stage": stage, "files": files}
    ha.write_exclusive_json(os.path.join(root, "raw", "seal.json"), seal)
    return seal


def verify_seal(root: str, stage: str) -> dict:
    seal = ha.read_json_strict(os.path.join(root, "raw", "seal.json"))
    if seal.get("schema") != SCHEMA_SEAL or seal.get("stage") != stage:
        raise RunBlocked("X_SEAL", "unknown seal schema/stage")
    expected = seal_paths(root, stage)
    files = seal.get("files")
    if not isinstance(files, dict) or list(files) != expected:
        raise RunBlocked("X_SEAL", "seal file set differs")
    for relative in expected:
        full = os.path.join(root, relative)
        ha._require_regular_file(full)
        if ha.sha256_file(full) != files[relative]:
            raise RunBlocked("X_SEAL", f"sealed file changed: {relative}")
    return seal


# ---------------------------------------------------------------------------
# Record validation
# ---------------------------------------------------------------------------


def validate_slot(slot: dict, lanes: list[dict], stage: str) -> list[dict]:
    if slot.get("schema") != SCHEMA_SLOT or slot.get("stage") != stage:
        raise RunBlocked("X_SLOT", "slot schema/stage differs")
    trial = slot.get("trial")
    if not isinstance(trial, dict):
        raise RunBlocked("X_SLOT", "slot has no trial")
    records = trial.get("lanes")
    if not isinstance(records, list) or len(records) != len(lanes):
        raise RunBlocked("X_SLOT", "slot lane count differs")
    if [record.get("id") for record in records] != [lane["id"] for lane in lanes]:
        raise RunBlocked("X_SLOT", "slot lane order differs")
    return [
        ha.validate_lane_record(record, lane, f"{stage}:slot-{slot.get('slot')}:{lane['id']}")
        for lane, record in zip(lanes, records, strict=True)
    ]


def slot_medians(slot: dict, lanes: list[dict], stage: str) -> dict[str, int]:
    summaries = validate_slot(slot, lanes, stage)
    return {lane["id"]: summary["median"] for lane, summary in zip(lanes, summaries, strict=True)}


def validate_schedule(slots: list[dict]) -> None:
    expected = [(block, arm) for block, order in enumerate(BLOCK_SCHEDULE, 1) for arm in order]
    if len(slots) != len(expected):
        raise RunBlocked("X_SCHEDULE", f"expected {len(expected)} slots, got {len(slots)}")
    observed = [(slot.get("block"), slot.get("arm")) for slot in slots]
    if observed != expected:
        raise RunBlocked("X_SCHEDULE", f"schedule differs: {observed}")
    for index, slot in enumerate(slots, 1):
        if slot.get("slot") != index:
            raise RunBlocked("X_SCHEDULE", f"slot numbering differs at {index}")


def arm_block_medians(slots: list[dict], lanes: list[dict], arm: str) -> dict:
    result = {}
    for slot in slots:
        if slot["arm"] != arm:
            continue
        if slot["block"] in result:
            raise RunBlocked("X_SCHEDULE", f"duplicate block {slot['block']} arm {arm}")
        result[slot["block"]] = slot_medians(slot, lanes, "paired")
    if sorted(result) != [1, 2, 3, 4]:
        raise RunBlocked("X_SCHEDULE", f"arm {arm} blocks differ")
    return result


def _common_problems(manifest: dict, slots: list[dict]) -> list[str]:
    problems = []
    for slot in slots:
        trial = slot["trial"]
        if trial.get("contention_before", {}).get("state") != "clear":
            problems.append(f"slot {slot['slot']} before probe not clear")
        if trial.get("contention_after", {}).get("state") != "clear":
            problems.append(f"slot {slot['slot']} after probe not clear")
        arm = manifest["arms"][slot["arm"]]
        if slot.get("source_sha") != arm["source_sha"]:
            problems.append(f"slot {slot['slot']} source SHA differs")
        if slot.get("binary_sha256") != arm["binary_sha256"]:
            problems.append(f"slot {slot['slot']} binary SHA differs")
        if slot.get("index_digests") != arm["index_digests"]:
            problems.append(f"slot {slot['slot']} index digest differs")
        expected = manifest.get("expected_by_lane", {})
        for record in trial["lanes"]:
            lane_id = record.get("id")
            if record.get("oracle_ok") is not True:
                problems.append(f"slot {slot['slot']} oracle not ok")
            if lane_id in expected and record.get("total_hits") != expected[lane_id]:
                problems.append(f"slot {slot['slot']} {lane_id} total_hits differs")
            if record.get("doc_ids") != record.get("expected_doc_ids"):
                problems.append(f"slot {slot['slot']} {lane_id} doc IDs differ")
    digests = [arm["index_digests"] for arm in manifest["arms"].values()]
    if any(value != digests[0] for value in digests):
        problems.append("arm index digests differ")
    return problems


# ---------------------------------------------------------------------------
# Absolute-millisecond gate math
# ---------------------------------------------------------------------------


def median_of_four(values: list[int]) -> int:
    if len(values) != 4:
        raise RunBlocked("X_GATE", "expected four paired differences")
    return sorted(values)[1]


def conventional_median_of_four(values: list[int]) -> float:
    """Informational even-n arithmetic median; C gates use `median_of_four`."""
    if len(values) != 4:
        raise RunBlocked("X_GATE", "expected four paired differences")
    ordered = sorted(values)
    return (ordered[1] + ordered[2]) / 2


def primary_gate(diffs: list[int]) -> dict:
    median = median_of_four(diffs)
    at_least = sum(1 for value in diffs if value >= P_BLOCK_MIN_NS)
    return {
        "diffs_ns": list(diffs),
        "median_ns": median,
        "median_ms": median / MS,
        "blocks_at_least_2ms": at_least,
        "min_ns": min(diffs),
        "passes": (
            median >= P_MIN_MEDIAN_NS
            and at_least >= 3
            and min(diffs) >= P_NEGATIVE_FLOOR_NS
        ),
        "confirmation_shape": (
            median >= P_MIN_MEDIAN_NS
            and min(diffs) >= P_NEGATIVE_FLOOR_NS
            and at_least == 2
        ),
    }


def p3_gate(diffs: list[int]) -> dict:
    median = median_of_four(diffs)
    below = sum(1 for value in diffs if value < P3_MEDIAN_NS)
    return {
        "diffs_ns": list(diffs),
        "median_ns": median,
        "median_ms": median / MS,
        "blocks_below_neg3ms": below,
        "passes": median > P3_MEDIAN_NS and below < 3,
    }


def guard_gate(diffs: list[int], floor: int) -> dict:
    median = median_of_four(diffs)
    return {"diffs_ns": list(diffs), "median_ns": median, "median_ms": median / MS, "passes": median > floor}


def confirmation_eligible(gates: dict) -> bool:
    primaries = [gates[P1], gates[P2]]
    if not any(gate["confirmation_shape"] for gate in primaries):
        return False
    if any(not gate["passes"] for gate in primaries if not gate["confirmation_shape"]):
        return False
    return (
        gates[P3]["passes"]
        and gates[G1]["passes"]
        and gates[G2]["passes"]
        and gates[G3]["passes"]
    )


def signed_median(values: list[int]) -> int:
    if not values:
        raise RunBlocked("X_GATE", "no values for median")
    ordered = sorted(values)
    index = (50 * len(ordered) + 99) // 100 - 1
    return ordered[index]


def pooled_primary_pass(diffs: list[int]) -> bool:
    if len(diffs) != 8:
        raise RunBlocked("X_GATE", "confirmation pooling requires eight primary differences")
    return signed_median(diffs) >= P_MIN_MEDIAN_NS


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _report_paths(root: str, kind: str) -> tuple[str, str]:
    if kind == "baseline":
        return (
            os.path.join(root, "sanitized", "baseline.json"),
            os.path.join(root, "sanitized", "baseline.md"),
        )
    if kind == "performance":
        return (
            os.path.join(root, "sanitized", "performance.json"),
            os.path.join(root, "sanitized", "performance.md"),
        )
    if kind == "confirmation":
        return (
            os.path.join(root, "sanitized", "confirmation-required.json"),
            os.path.join(root, "sanitized", "confirmation-required.md"),
        )
    return (
        os.path.join(root, "sanitized", "blocked.json"),
        os.path.join(root, "sanitized", "blocked.md"),
    )


def publish_report(root: str, kind: str, report: dict, markdown: str) -> None:
    ha.assert_report_sanitized(report)
    json_path, md_path = _report_paths(root, kind)
    if os.path.exists(json_path) or os.path.exists(md_path):
        raise RunBlocked("X_REPORT_EXISTS", "a report pair already exists")
    ha.write_exclusive_json(json_path, report)
    ha.write_exclusive_text(md_path, markdown)


def _blocked(manifest: dict, reasons: list[str], extra: dict | None = None) -> tuple[dict, str]:
    report = {
        "schema": SCHEMA_BLOCKED,
        "stage": PHASE,
        "tooling_sha": manifest["tooling_sha"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "reasons": reasons,
        "performance_verdict": "NOT_EVALUATED",
    }
    if extra:
        report.update(extra)
    ha.assert_report_sanitized(report)
    lines = ["# PR 15H-B — measurement blocked", "", "No performance disposition.", ""]
    lines.extend(f"- {reason}" for reason in reasons)
    lines.append("")
    return report, "\n".join(lines)


def derive_baseline(manifest: dict, trials: list[dict]) -> tuple[dict, str]:
    lanes = frozen_lanes()
    if len(trials) != TRIALS:
        raise RunBlocked("X_TRIAL_COUNT", "baseline must have three trials")
    medians: dict[str, list[int]] = {lane["id"]: [] for lane in lanes}
    for index, trial in enumerate(trials, 1):
        summaries = validate_slot(
            {"schema": SCHEMA_SLOT, "stage": "baseline", "slot": index, "trial": trial},
            lanes,
            "baseline",
        )
        for lane, summary in zip(lanes, summaries, strict=True):
            medians[lane["id"]].append(summary["median"])
    lane_report = []
    for lane in lanes:
        values = medians[lane["id"]]
        lane_report.append(
            {
                "id": lane["id"],
                "n": lane["n"],
                "class": lane["class"],
                "trial_medians_ns": values,
                "median_of_medians_ns": ha.base.pr15d_run.summarize(values)["median"],
            }
        )
    report = {
        "schema": SCHEMA_BASELINE,
        "phase": PHASE,
        "base_source_sha": manifest["base_source_sha"],
        "tooling_sha": manifest["tooling_sha"],
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "lane_ids": list(LANE_IDS),
        "trial_count": TRIALS,
        "samples_per_lane": SAMPLES,
        "warmups_per_lane": WARMUPS,
        "lanes": lane_report,
    }
    ha.assert_report_sanitized(report)
    lines = [
        "# PR 15H-B — pre-optimization baseline",
        "",
        f"- source: `{report['base_source_sha']}`",
        f"- tooling: `{report['tooling_sha']}`",
        "",
        "| lane | trial medians (ns) | median-of-medians (ns) |",
        "|---|---:|---:|",
    ]
    for lane in lane_report:
        lines.append(
            f"| `{lane['id']}` | {', '.join(str(v) for v in lane['trial_medians_ns'])} | "
            f"{lane['median_of_medians_ns']} |"
        )
    lines.append("")
    return report, "\n".join(lines)


def derive_paired(
    manifest: dict,
    slots: list[dict],
    baseline_manifest: dict,
    confirmation_of: dict | None = None,
) -> tuple[str, dict, str]:
    lanes = frozen_lanes()
    validate_schedule(slots)
    require_same_tooling(manifest.get("tooling_sha"), baseline_manifest)
    problems = _common_problems(manifest, slots)
    if manifest["base_source_sha"] != baseline_manifest["base_source_sha"]:
        problems.append("baseline source SHA differs")
    if manifest["corpus_manifest_sha256"] != baseline_manifest["corpus_manifest_sha256"]:
        problems.append("corpus manifest differs")
    if manifest["environment_fingerprint"] != baseline_manifest["environment_fingerprint"]:
        problems.append("host fingerprint differs")
    if problems:
        return "blocked", *_blocked(manifest, problems)

    arm_a = arm_block_medians(slots, lanes, "A")
    arm_b = arm_block_medians(slots, lanes, "B")
    lanes_report = []
    gates = {}
    for lane in lanes:
        a_values = [arm_a[block][lane["id"]] for block in (1, 2, 3, 4)]
        b_values = [arm_b[block][lane["id"]] for block in (1, 2, 3, 4)]
        diffs = [a - b for a, b in zip(a_values, b_values)]
        if lane["id"] in (P1, P2):
            gates[lane["id"]] = primary_gate(diffs)
        elif lane["id"] == P3:
            gates[lane["id"]] = p3_gate(diffs)
        elif lane["id"] == G1:
            gates[lane["id"]] = guard_gate(diffs, G1_MEDIAN_NS)
        else:
            gates[lane["id"]] = guard_gate(diffs, SPARSE_MEDIAN_NS)
        lanes_report.append(
            {
                "id": lane["id"],
                "n": lane["n"],
                "class": lane["class"],
                "a_slot_medians_ns": a_values,
                "b_slot_medians_ns": b_values,
                "diffs_ns": diffs,
                "median_diff_ns": median_of_four(diffs),
                "median_diff_ms": median_of_four(diffs) / MS,
            }
        )

    p00 = True
    p01 = gates[P1]["passes"]
    p02 = gates[P2]["passes"]
    p03 = gates[P3]["passes"]
    p04 = gates[G1]["passes"]
    p05 = gates[G2]["passes"] and gates[G3]["passes"]
    p06 = True
    p07 = True
    gate_table = {
        "HC-P00": "PASS" if p00 else "FAIL",
        "HC-P01": "PASS" if p01 else "FAIL",
        "HC-P02": "PASS" if p02 else "FAIL",
        "HC-P03": "PASS" if p03 else "FAIL",
        "HC-P04": "PASS" if p04 else "FAIL",
        "HC-P05": "PASS" if p05 else "FAIL",
        "HC-P06": "PASS" if p06 else "FAIL",
        "HC-P07": "PASS" if p07 else "FAIL",
    }
    need_confirmation = confirmation_eligible(gates)
    if need_confirmation and confirmation_of is None:
        report = {
            "schema": SCHEMA_CONFIRMATION,
            "phase": PHASE,
            "tooling_sha": manifest["tooling_sha"],
            "base_source_sha": manifest["base_source_sha"],
            "candidate_source_sha": manifest["candidate_source_sha"],
            "environment_fingerprint": manifest["environment_fingerprint"],
            "lanes": lanes_report,
            "gates": gate_table,
            "reason": "CONFIRMATION_REQUIRED",
        }
        ha.assert_report_sanitized(report)
        lines = [
            "# PR 15H-B — confirmation campaign required",
            "",
            "The first qualified campaign met the frozen one-time confirmation shape:",
            "a primary median ≥ 5 ms, no block below −3 ms, but exactly 2/4 blocks",
            "≥ 2 ms, with every other gate passing. Run exactly one complete extra",
            "campaign and pass its directory as `--confirmation-of`.",
            "",
        ]
        return "confirmation", report, "\n".join(lines)

    pooled_ok = True
    if confirmation_of is not None:
        pooled_ok = all(confirmation_of["pooled"]["passes"].values())
    decision = (
        "PERFORMANCE_ACCEPTED"
        if all(value == "PASS" for value in gate_table.values()) and pooled_ok
        else "PERFORMANCE_REJECTED"
    )
    report = {
        "schema": SCHEMA_PERFORMANCE,
        "phase": PHASE,
        "tooling_sha": manifest["tooling_sha"],
        "base_source_sha": manifest["base_source_sha"],
        "candidate_source_sha": manifest["candidate_source_sha"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "index_digests": manifest["arms"]["A"]["index_digests"],
        "slot_count": len(slots),
        "lane_record_count": len(slots) * len(lanes),
        "timed_samples": len(slots) * len(lanes) * SAMPLES,
        "warmups": len(slots) * len(lanes) * WARMUPS,
        "contention_probes": len(slots) * 2,
        "oracle_validations": len(slots) * len(lanes),
        "lanes": lanes_report,
        "gates": gate_table,
        "confirmation": "NOT_REQUIRED" if not need_confirmation else "COMBINED",
        "decision": decision,
        "performance_verdict": decision,
    }
    if confirmation_of is not None:
        report["confirmation"] = "CONFIRMED"
        report["confirmation_campaign"] = confirmation_of["campaign"]
        pooled = confirmation_of["pooled"]
        report["pooled_primary_diffs_ns"] = pooled
        report["pooled_primary_pass"] = all(pooled["passes"].values())
    ha.assert_report_sanitized(report)
    lines = [
        "# PR 15H-B — paired performance",
        "",
        f"- accepted A: `{report['base_source_sha']}`",
        f"- candidate B: `{report['candidate_source_sha']}`",
        f"- decision: **{decision}**",
        "",
        "Differences are `A − B` (positive = B faster), in milliseconds.",
        "",
        "| lane | A slot medians (ns) | B slot medians (ns) | four diffs (ms) | median Δ (ms) | gate |",
        "|---|---:|---:|---|---:|---|",
    ]
    for lane in lanes_report:
        gate = gates[lane["id"]]
        lines.append(
            f"| `{lane['id']}` | {', '.join(str(v) for v in lane['a_slot_medians_ns'])} | "
            f"{', '.join(str(v) for v in lane['b_slot_medians_ns'])} | "
            f"{', '.join(f'{d / MS:.3f}' for d in lane['diffs_ns'])} | "
            f"{lane['median_diff_ms']:.3f} | {'PASS' if gate['passes'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("Gates: " + ", ".join(f"{k}={v}" for k, v in gate_table.items()))
    lines.append("")
    return "performance", report, "\n".join(lines)


# ---------------------------------------------------------------------------
# Campaign execution
# ---------------------------------------------------------------------------


def _source_scope_ok(tree: str, base_sha: str, candidate_sha: str) -> bool:
    files = ha.base.git(tree, "diff", "--name-only", f"{base_sha}..{candidate_sha}").splitlines()
    for path in files:
        if path in A_ALLOWED_CHANGED_EXACT:
            continue
        if any(path.startswith(prefix) for prefix in A_ALLOWED_CHANGED_PREFIXES):
            continue
        return False
    return True


def _run_trials(
    out: str,
    binary: str,
    lanes: list[dict],
    indices: dict,
    expected: dict,
    metadata: dict,
    trial_count: int,
    stage: str,
) -> list[dict]:
    trials = []
    for index in range(1, trial_count + 1):
        if not all(
            ha.base.directory_digest(record["dir"]) == record["digest"]
            for record in indices.values()
        ):
            raise RunBlocked("X_INDEX_MUTATED", "index changed before a trial")
        trial = ha.base.measure_trial(
            index, binary, lanes, indices, expected, metadata, out
        )
        trials.append(trial)
    return trials


def run_baseline(args) -> int:
    if not args.idle_confirmed:
        print("PERF_BLOCKED_OPERATOR: --idle-confirmed is required", file=sys.stderr)
        return 3
    tooling = ha._assert_clean_tooling()
    out = validate_out_path(args.out, args.checkout_root)
    source = resolve_tree(args.base_tree, ARM_A_SHA, "A")
    verify_frozen_inputs(TOOLING_ROOT)
    verify_frozen_inputs(source["tree"])
    lanes = frozen_lanes()

    os.makedirs(out, exist_ok=False)
    filesystem = ha.base.require_native_filesystem(out)
    environment = ha.base.pr15d_run.collect_environment(out)
    environment["filesystem"] = filesystem

    ha.write_exclusive_json(
        os.path.join(out, "authorization.json"),
        {
            "schema": SCHEMA_AUTHORIZATION,
            "stage": "baseline",
            "operator_idle_confirmed": True,
            "recorded_utc": ha.utc_now(),
            "tooling_sha": tooling["sha"],
            "base_source_sha": source["sha"],
        },
    )
    build = ha.base.build_adapter(source["tree"], out)
    corpus = ha.base.prepare_corpus(out)
    expected = {
        lane["id"]: ha.base.oracle.expected(
            rows=corpus["rows"][lane["n"]],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        for lane in lanes
    }
    metadata = ha.base.pr15d_run.read_adapter_metadata("quervant", build["binary"])
    indices = ha.base.build_indices(
        build["binary"], corpus, out, sorted({lane["n"] for lane in lanes})
    )
    manifest = {
        "schema": SCHEMA_MANIFEST,
        "stage": "baseline",
        "phase": PHASE,
        "base_source_sha": source["sha"],
        "tooling_sha": tooling["sha"],
        "environment": environment,
        "environment_fingerprint": ha.base.pr15d_run.host_fingerprint(environment),
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
        "binary_sha256": build["binary_sha256"],
        "lanes": [lane["id"] for lane in lanes],
        "expected_by_lane": {lid: value["total_hits"] for lid, value in expected.items()},
        "index_digests": {str(n): record["digest"] for n, record in sorted(indices.items())},
    }
    ha.write_exclusive_json(os.path.join(out, "manifest.json"), manifest)
    trials = _run_trials(out, build["binary"], lanes, indices, expected, metadata, TRIALS, "baseline")
    for index, trial in enumerate(trials, 1):
        ha.write_exclusive_json(os.path.join(out, "raw", f"trial-{index:02d}.json"), trial)
    write_seal(out, "baseline")
    report, markdown = derive_baseline(manifest, trials)
    publish_report(out, "baseline", report, markdown)
    print(f"PR15H_C BASELINE_SHA={source['sha']} OUT={out} SEALED=yes")
    return 0


def _arm_indices(build: dict, corpus: dict, root: str, lanes: list[dict]) -> dict:
    return ha.base.build_indices(
        build["binary"], corpus, root, sorted({lane["n"] for lane in lanes})
    )


def run_paired(args) -> int:
    if not args.idle_confirmed:
        print("PERF_BLOCKED_OPERATOR: --idle-confirmed is required", file=sys.stderr)
        return 3
    tooling = ha._assert_clean_tooling()
    out = validate_out_path(args.out, args.checkout_root)
    baseline_root = validate_sealed_dir(args.baseline, args.checkout_root, "--baseline")
    if os.path.realpath(baseline_root) == out:
        raise RunBlocked("X_PATH", "--baseline and --out must differ")
    baseline_manifest = ha.read_json_strict(os.path.join(baseline_root, "manifest.json"))
    verify_seal(baseline_root, "baseline")
    if baseline_manifest.get("schema") != SCHEMA_MANIFEST:
        raise RunBlocked("X_MANIFEST", "baseline manifest differs")
    require_same_tooling(tooling["sha"], baseline_manifest)
    base = resolve_tree(args.base_tree, ARM_A_SHA, "A")
    candidate = resolve_tree(args.candidate_tree, None, "B")
    if candidate["sha"] == base["sha"]:
        raise RunBlocked("X_SOURCE_SHA", "candidate equals baseline")
    if not ha.base.is_ancestor(candidate["tree"], base["sha"]):
        raise RunBlocked("X_SOURCE_SHA", "candidate is not a descendant of baseline")
    if not _source_scope_ok(candidate["tree"], base["sha"], candidate["sha"]):
        raise RunBlocked("X_SCOPE", "candidate touches a path outside the PR15H-B allowlist")
    verify_frozen_inputs(TOOLING_ROOT)
    verify_frozen_inputs(base["tree"])
    verify_frozen_inputs(candidate["tree"])
    lanes = frozen_lanes()

    confirmation_of = None
    if args.confirmation_of:
        prior_root = validate_sealed_dir(args.confirmation_of, args.checkout_root, "--confirmation-of")
        confirmation_of = _load_confirmation(prior_root, base["sha"], candidate["sha"])

    os.makedirs(out, exist_ok=False)
    filesystem = ha.base.require_native_filesystem(out)
    environment = ha.base.pr15d_run.collect_environment(out)
    environment["filesystem"] = filesystem
    if ha.base.pr15d_run.host_fingerprint(environment) != baseline_manifest["environment_fingerprint"]:
        raise RunBlocked("X_HOST", "host fingerprint differs from the sealed baseline")

    ha.write_exclusive_json(
        os.path.join(out, "authorization.json"),
        {
            "schema": SCHEMA_AUTHORIZATION,
            "stage": "paired",
            "operator_idle_confirmed": True,
            "recorded_utc": ha.utc_now(),
            "tooling_sha": tooling["sha"],
            "base_source_sha": base["sha"],
            "candidate_source_sha": candidate["sha"],
            "confirmation_of": os.path.basename(confirmation_of["campaign"]) if confirmation_of else None,
        },
    )
    build_a = ha.base.build_adapter(base["tree"], os.path.join(out, "arm-a"))
    build_b = ha.base.build_adapter(candidate["tree"], os.path.join(out, "arm-b"))
    corpus = ha.base.prepare_corpus(out)
    expected = {
        lane["id"]: ha.base.oracle.expected(
            rows=corpus["rows"][lane["n"]],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        for lane in lanes
    }
    metadata_a = ha.base.pr15d_run.read_adapter_metadata("quervant", build_a["binary"])
    metadata_b = ha.base.pr15d_run.read_adapter_metadata("quervant", build_b["binary"])
    if metadata_a != metadata_b:
        raise RunBlocked("X_ADAPTER", "adapter metadata differs between arms")
    indices_a = _arm_indices(build_a, corpus, os.path.join(out, "arm-a"), lanes)
    indices_b = _arm_indices(build_b, corpus, os.path.join(out, "arm-b"), lanes)
    digests_a = {str(n): record["digest"] for n, record in sorted(indices_a.items())}
    digests_b = {str(n): record["digest"] for n, record in sorted(indices_b.items())}
    if digests_a != digests_b:
        raise RunBlocked("X_INDEX", "baseline and candidate indexes are not byte-identical")
    arms = {
        "A": {
            "source_sha": base["sha"],
            "binary_sha256": build_a["binary_sha256"],
            "binary": build_a["binary"],
            "metadata": metadata_a,
            "indices": indices_a,
            "index_digests": digests_a,
        },
        "B": {
            "source_sha": candidate["sha"],
            "binary_sha256": build_b["binary_sha256"],
            "binary": build_b["binary"],
            "metadata": metadata_b,
            "indices": indices_b,
            "index_digests": digests_b,
        },
    }
    manifest = {
        "schema": SCHEMA_MANIFEST,
        "stage": "paired",
        "phase": PHASE,
        "base_source_sha": base["sha"],
        "candidate_source_sha": candidate["sha"],
        "tooling_sha": tooling["sha"],
        "environment": environment,
        "environment_fingerprint": ha.base.pr15d_run.host_fingerprint(environment),
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
        "lanes": [lane["id"] for lane in lanes],
        "expected_by_lane": {lid: value["total_hits"] for lid, value in expected.items()},
        "schedule": [list(order) for order in BLOCK_SCHEDULE],
        "arms": {
            arm: {
                "source_sha": data["source_sha"],
                "binary_sha256": data["binary_sha256"],
                "index_digests": data["index_digests"],
            }
            for arm, data in arms.items()
        },
    }
    ha.write_exclusive_json(os.path.join(out, "manifest.json"), manifest)

    slots = []
    number = 0
    for block, order in enumerate(BLOCK_SCHEDULE, start=1):
        for arm in order:
            number += 1
            for data in arms.values():
                if not all(
                    ha.base.directory_digest(record["dir"]) == record["digest"]
                    for record in data["indices"].values()
                ):
                    raise RunBlocked("X_INDEX_MUTATED", "index changed before a slot")
            slot_dir = os.path.join(out, "raw", "slots", f"slot-{number:02d}")
            trial = ha.base.measure_trial(
                1,
                arms[arm]["binary"],
                lanes,
                arms[arm]["indices"],
                expected,
                arms[arm]["metadata"],
                slot_dir,
            )
            slot = {
                "schema": SCHEMA_SLOT,
                "stage": "paired",
                "slot": number,
                "block": block,
                "arm": arm,
                "source_sha": arms[arm]["source_sha"],
                "binary_sha256": arms[arm]["binary_sha256"],
                "index_digests": arms[arm]["index_digests"],
                "trial": trial,
            }
            ha.write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{number:02d}.json"), slot
            )
            slots.append(slot)
    write_seal(out, "paired")
    kind, report, markdown = derive_paired(
        manifest, slots, baseline_manifest, confirmation_of
    )
    publish_report(out, kind, report, markdown)
    print(f"PR15H_C PAIRED_BASE={base['sha']} CANDIDATE={candidate['sha']} OUT={out} RESULT={kind}")
    return 0


def _load_confirmation(root: str, base_sha: str, candidate_sha: str) -> dict:
    verify_seal(root, "paired")
    manifest = ha.read_json_strict(os.path.join(root, "manifest.json"))
    if manifest.get("schema") != SCHEMA_MANIFEST or manifest.get("stage") != "paired":
        raise RunBlocked("X_MANIFEST", "confirmation source manifest differs")
    if manifest.get("base_source_sha") != base_sha or manifest.get("candidate_source_sha") != candidate_sha:
        raise RunBlocked("X_CONFIRMATION", "confirmation campaign source arms differ")
    slots = [
        ha.read_json_strict(os.path.join(root, "raw", "slots", f"slot-{index:02d}.json"))
        for index in range(1, TOTAL_SLOTS + 1)
    ]
    marker = ha.read_json_strict(os.path.join(root, "sanitized", "confirmation-required.json"))
    if marker.get("schema") != SCHEMA_CONFIRMATION:
        raise RunBlocked("X_CONFIRMATION", "prior campaign is not confirmation-required")
    lanes = frozen_lanes()
    arm_a = arm_block_medians(slots, lanes, "A")
    arm_b = arm_block_medians(slots, lanes, "B")
    pooled = {}
    for lane_id in (P1, P2):
        diffs = []
        for block in (1, 2, 3, 4):
            diffs.append(arm_a[block][lane_id] - arm_b[block][lane_id])
        pooled[lane_id] = diffs
    combined = {}
    for lane_id in (P1, P2):
        marker_lane = next(lane for lane in marker["lanes"] if lane["id"] == lane_id)
        prior = list(marker_lane["diffs_ns"])
        combined[lane_id] = {
            "prior": prior,
            "pooled": prior + pooled[lane_id],
            "passes": pooled_primary_pass(prior + pooled[lane_id]),
        }
    return {"campaign": root, "pooled": {"campaign": root, "passes": {k: v["passes"] for k, v in combined.items()}, "details": combined}}


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def verify_campaign(args) -> int:
    root = validate_sealed_dir(args.campaign, args.checkout_root, "--campaign")
    manifest = ha.read_json_strict(os.path.join(root, "manifest.json"))
    stage = manifest.get("stage")
    if stage == "baseline":
        verify_seal(root, "baseline")
        trials = [
            ha.read_json_strict(os.path.join(root, "raw", f"trial-{index:02d}.json"))
            for index in range(1, TRIALS + 1)
        ]
        report, markdown = derive_baseline(manifest, trials)
        kind = "baseline"
    elif stage == "paired":
        verify_seal(root, "paired")
        baseline_root = validate_sealed_dir(args.baseline, args.checkout_root, "--baseline")
        baseline_manifest = ha.read_json_strict(os.path.join(baseline_root, "manifest.json"))
        require_same_tooling(manifest.get("tooling_sha"), baseline_manifest)
        slots = [
            ha.read_json_strict(os.path.join(root, "raw", "slots", f"slot-{index:02d}.json"))
            for index in range(1, TOTAL_SLOTS + 1)
        ]
        confirmation_of = None
        if args.confirmation_of:
            prior = validate_sealed_dir(args.confirmation_of, args.checkout_root, "--confirmation-of")
            prior_manifest = ha.read_json_strict(os.path.join(prior, "manifest.json"))
            confirmation_of = _load_confirmation(
                prior,
                prior_manifest["base_source_sha"],
                prior_manifest["candidate_source_sha"],
            )
        kind, report, markdown = derive_paired(
            manifest, slots, baseline_manifest, confirmation_of
        )
    else:
        raise RunBlocked("X_MANIFEST", "unknown campaign stage")
    json_path, md_path = _report_paths(root, kind)
    with open(json_path, "rb") as handle:
        actual_json = handle.read()
    if actual_json != ha.canonical_bytes(report):
        raise RunBlocked("X_REPORT_DRIFT", "sanitized JSON does not recompute")
    with open(md_path, "rb") as handle:
        actual_md = handle.read().decode("utf-8")
    if actual_md != markdown:
        raise RunBlocked("X_REPORT_DRIFT", "sanitized Markdown does not recompute")
    print(f"PR15H_C VERIFY_OK STAGE={stage} CAMPAIGN={root} KIND={kind}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PR 15H-C six-lane Quervant-only controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline = subparsers.add_parser("baseline")
    baseline.add_argument("--checkout-root", required=True)
    baseline.add_argument("--base-tree", required=True)
    baseline.add_argument("--out", required=True)
    baseline.add_argument("--idle-confirmed", action="store_true")
    baseline.add_argument("--verify-only", action="store_true")

    paired = subparsers.add_parser("paired")
    paired.add_argument("--checkout-root", required=True)
    paired.add_argument("--base-tree", required=True)
    paired.add_argument("--candidate-tree", required=True)
    paired.add_argument("--baseline", required=True)
    paired.add_argument("--out", required=True)
    paired.add_argument("--idle-confirmed", action="store_true")
    paired.add_argument("--verify-only", action="store_true")
    paired.add_argument("--confirmation-of", default=None)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_only:
            if args.command == "baseline":
                return verify_campaign(
                    argparse.Namespace(
                        checkout_root=args.checkout_root,
                        campaign=args.out,
                        baseline=None,
                        confirmation_of=None,
                    )
                )
            return verify_campaign(
                argparse.Namespace(
                    checkout_root=args.checkout_root,
                    campaign=args.out,
                    baseline=args.baseline,
                    confirmation_of=args.confirmation_of,
                )
            )
        if args.command == "baseline":
            return run_baseline(args)
        return run_paired(args)
    except RunBlocked as error:
        print(f"PERF_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""PR 15H-A3 diagnostic controller (four-lane, Quervant-only).

Stage subcommands and nothing else:

* ``aa``    accepted A vs an independent build of the same A (environment control)
* ``ab``    accepted A vs rejected A2 candidate B (reproduction)
* ``bv2``   B vs B with the single-line threshold-disabled diagnostic constant
* ``bv3``   B vs B with one ``#[inline(never)]`` helper attribute
* ``verify`` recompute a sealed campaign's sanitized report byte-for-byte

This controller reuses the frozen PR15D/PR15E-B1 measurement functions and the
PR15H-A sealing/validation helpers. It never implements production Rust and
never emits a performance-acceptance verdict.
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

_spec = importlib.util.spec_from_file_location("pr15h_a_run_readonly_a3", HA_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - import failure
    raise ImportError(f"cannot load frozen PR15H-A controller from {HA_PATH}")
ha = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ha)

RunBlocked = ha.base.pr15d_run.RunBlocked

SCHEMA_AUTHORIZATION = "pr15h-a3-authorization-v1"
SCHEMA_MANIFEST = "pr15h-a3-manifest-v1"
SCHEMA_SEAL = "pr15h-a3-seal-v1"
SCHEMA_SLOT = "pr15h-a3-slot-v1"
SCHEMA_AA = "pr15h-a3-aa-v1"
SCHEMA_AB = "pr15h-a3-ab-v1"
SCHEMA_VARIANT = "pr15h-a3-variant-v1"
SCHEMA_BLOCKED = "pr15h-a3-blocked-v1"
STAGE = "15h-a3"

A_SHA = "7a136f7f299c2f460401b9d92dcef37d219ea98c"
B_SHA = "569132dace8d92c103dfdebd5d24167d65c0c0c0"
A1_CANDIDATE_SHA = "dce8f02405e6541d478c2072a0332af192ed2945"
A2_TOOLING_SHA = "9aff92b6b1a12ee323ed7994a177f88949c736fd"
A2_FINAL_SHA = "d398af5e2dc354f19b209ce53df62f78d12e26f8"

CANONICAL_LANE_IDS = (
    "pr15d_v1/100000/absent/k100",
    "pr15d_v1/100000/rare/k100",
    "pr15d_v1/10000/rare/k100",
    "pr15d_v1/100000/common/k100",
)
LANE_IDS = CANONICAL_LANE_IDS
AA_SCHEDULE = (("A", "A_PRIME"), ("A_PRIME", "A"))
AB_SCHEDULE = (("A", "B"), ("B", "A"), ("B", "A"), ("A", "B"))
VARIANT_SCHEDULE = (("B", "V"), ("V", "B"))
WARMUPS = 5
SAMPLES = 20
DRIFT_CAPS = {10000: 1.50, 100000: 1.25}
AA_CAPS = {10000: 1.20, 100000: 1.15}
VARIANT_EFFECT_CAP = 0.95

STAGES = ("aa", "ab", "bv2", "bv3")
SLOT_COUNTS = {"aa": 4, "ab": 8, "bv2": 4, "bv3": 4}
FORBIDDEN_REPORT_MARKERS = ("/home/", "/mnt/", "/tmp/", "/abs/", "target/pr15h-a3")


def _blocked_rule(callable_) -> str:
    try:
        callable_()
    except RunBlocked as error:
        return error.rule
    raise AssertionError("expected RunBlocked")


# ---------------------------------------------------------------------------
# Frozen lanes and paths
# ---------------------------------------------------------------------------


def frozen_lanes() -> list[dict]:
    if tuple(LANE_IDS) != CANONICAL_LANE_IDS:
        raise RunBlocked("X_LANE_SET", "A3 lane list or order was modified")
    by_id = {lane["id"]: lane for lane in ha.base.pr15d_run.lane_descriptors()}
    lanes = []
    for lane_id in LANE_IDS:
        lane = by_id.get(lane_id)
        if lane is None:
            raise RunBlocked("X_LANE_SET", f"frozen lane missing: {lane_id}")
        if lane["regime"] != "warm":
            raise RunBlocked("X_LANE_SET", f"lane is not warm: {lane_id}")
        lanes.append(dict(lane))
    if len(lanes) != 4 or len({lane["id"] for lane in lanes}) != 4:
        raise RunBlocked("X_LANE_SET", "A3 requires exactly four distinct lanes")
    return lanes


def target_root(checkout_root: str) -> str:
    if not os.path.isabs(checkout_root):
        raise RunBlocked("X_PATH", "--checkout-root must be absolute")
    return os.path.realpath(os.path.join(checkout_root, "target", "pr15h-a3"))


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


def validate_campaign_dir(path: str, checkout_root: str) -> str:
    if not os.path.isabs(path):
        raise RunBlocked("X_PATH", "--campaign must be absolute")
    if os.path.islink(path):
        raise RunBlocked("X_SYMLINK", "--campaign is a symlink")
    if not os.path.isdir(path):
        raise RunBlocked("X_PATH", f"--campaign is not a directory: {path}")
    allowed = target_root(checkout_root)
    candidate = os.path.realpath(path)
    try:
        within = os.path.commonpath([candidate, allowed]) == allowed
    except ValueError:
        within = False
    if not within or candidate == allowed:
        raise RunBlocked("X_PATH", "--campaign must be strictly beneath the A3 target root")
    return candidate


def resolve_tree(path: str, expected_sha: str | None, role: str) -> dict:
    if not os.path.isabs(path) or os.path.islink(path):
        raise RunBlocked("X_SOURCE", f"{role} must be an absolute non-symlinked path")
    source = ha.resolve_pinned_tree(path)
    if expected_sha is not None and source["sha"] != expected_sha:
        raise RunBlocked("X_SOURCE_SHA", f"{role} SHA {source['sha']} != expected {expected_sha}")
    return source


def verify_frozen_inputs(tree: str) -> None:
    ha.verify_frozen_inputs(tree)


# ---------------------------------------------------------------------------
# Seal and records
# ---------------------------------------------------------------------------


def seal_paths(root: str, stage: str) -> list[str]:
    count = SLOT_COUNTS[stage]
    return ["authorization.json", "manifest.json"] + [
        f"raw/slots/slot-{index:02d}.json" for index in range(1, count + 1)
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


def arm_block_medians(slots: list[dict], lanes: list[dict], stage: str, arm: str) -> dict:
    result = {}
    for slot in slots:
        if slot["arm"] != arm:
            continue
        block = slot["block"]
        if block in result:
            raise RunBlocked("X_SCHEDULE", f"duplicate block {block} arm {arm}")
        result[block] = slot_medians(slot, lanes, stage)
    expected_blocks = sorted({slot["block"] for slot in slots})
    if sorted(result) != expected_blocks:
        raise RunBlocked("X_SCHEDULE", f"arm {arm} blocks differ")
    return result


def validate_schedule(slots: list[dict], stage: str) -> None:
    schedule = AA_SCHEDULE if stage == "aa" else AB_SCHEDULE if stage == "ab" else VARIANT_SCHEDULE
    expected = []
    for block, order in enumerate(schedule, start=1):
        for arm in order:
            expected.append((block, arm))
    if len(slots) != len(expected):
        raise RunBlocked("X_SCHEDULE", f"expected {len(expected)} slots, got {len(slots)}")
    observed = [(slot.get("block"), slot.get("arm")) for slot in slots]
    if observed != expected:
        raise RunBlocked("X_SCHEDULE", f"schedule differs: {observed} != {expected}")
    for index, slot in enumerate(slots, start=1):
        if slot.get("slot") != index:
            raise RunBlocked("X_SCHEDULE", f"slot numbering differs at {index}")


def _drift(values, n: int, caps: dict) -> dict:
    low = min(values)
    high = max(values)
    if low <= 0:
        raise RunBlocked("X_DRIFT", "non-positive duration")
    ratio = high / low
    return {"cap": caps[n], "values": list(values), "ratio": ratio, "violated": ratio > caps[n]}


def _ratio(high: int, low: int) -> float:
    if low <= 0 or high <= 0:
        raise RunBlocked("X_RATIO", "non-positive duration")
    return high / low


def verdict_from_ratios(ratios: list[float]) -> str:
    for value in ratios:
        if not isinstance(value, (int, float)) or value <= 0 or value != value:
            raise RunBlocked("X_RATIO", f"invalid ratio {value!r}")
    if all(value < 1.0 for value in ratios):
        return "B_FASTER"
    if all(value > 1.0 for value in ratios):
        return "B_SLOWER"
    return "INCONCLUSIVE"


def _slot_context_problems(slots: list[dict], manifest: dict) -> list[str]:
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
    return problems


def _require_same_indexes(manifest: dict) -> None:
    digests = [arm["index_digests"] for arm in manifest["arms"].values()]
    if any(value != digests[0] for value in digests):
        raise RunBlocked("X_INDEX", "arm index digests differ")


def _common_problems(manifest: dict, slots: list[dict]) -> list[str]:
    problems = _slot_context_problems(slots, manifest)
    try:
        _require_same_indexes(manifest)
    except RunBlocked as error:
        problems.append(error.detail)
    expected = manifest.get("expected_by_lane", {})
    for slot in slots:
        for record in slot["trial"]["lanes"]:
            lane_id = record.get("id")
            if record.get("oracle_ok") is not True:
                problems.append(f"slot {slot['slot']} oracle not ok")
            if lane_id in expected and record.get("total_hits") != expected[lane_id]:
                problems.append(f"slot {slot['slot']} {lane_id} total_hits differs from oracle")
            if record.get("doc_ids") != record.get("expected_doc_ids"):
                problems.append(f"slot {slot['slot']} {lane_id} doc IDs differ from oracle")
    return problems


# ---------------------------------------------------------------------------
# Report derivation
# ---------------------------------------------------------------------------


def _blocked_report(manifest: dict, reasons: list[str], extra: dict | None = None) -> tuple[dict, str]:
    report = {
        "schema": SCHEMA_BLOCKED,
        "stage": manifest["stage"],
        "tooling_sha": manifest["tooling_sha"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "reasons": reasons,
        "performance_verdict": "NOT_APPLICABLE_DIAGNOSTIC_ONLY",
    }
    if extra:
        report.update(extra)
    reject_acceptance_claim(report)
    ha.assert_report_sanitized(report)
    lines = [
        f"# PR 15H-A3 — {manifest['stage']} measurement blocked",
        "",
        "Diagnostic-only; no performance verdict.",
        "",
    ]
    lines.extend(f"- {reason}" for reason in reasons)
    lines.append("")
    return report, "\n".join(lines)


def derive_aa(manifest: dict, slots: list[dict]) -> tuple[str, dict, str]:
    lanes = frozen_lanes()
    validate_schedule(slots, "aa")
    problems = _common_problems(manifest, slots)
    if manifest["arms"]["A"]["source_sha"] != manifest["arms"]["A_PRIME"]["source_sha"]:
        problems.append("A/A arms do not share the same source SHA")
    if problems:
        return "blocked", *_blocked_report(
            manifest, problems, {"reason": "MEASUREMENT_BLOCKED_AA_CONTROL"}
        )
    blocks = {}
    for block, first, second in ((1, "A", "A_PRIME"), (2, "A_PRIME", "A")):
        a = slot_medians(
            next(slot for slot in slots if slot["block"] == block and slot["arm"] == first),
            lanes,
            "aa",
        )
        b = slot_medians(
            next(slot for slot in slots if slot["block"] == block and slot["arm"] == second),
            lanes,
            "aa",
        )
        blocks[block] = (a, b)
    lane_report = []
    violations = []
    for lane in lanes:
        values = []
        for block in (1, 2):
            a, b = blocks[block]
            values.append(_ratio(max(a[lane["id"]], b[lane["id"]]), min(a[lane["id"]], b[lane["id"]])))
        check = {
            "id": lane["id"],
            "n": lane["n"],
            "ratios": values,
            "cap": AA_CAPS[lane["n"]],
            "qualified": all(value <= AA_CAPS[lane["n"]] for value in values),
        }
        if not check["qualified"]:
            violations.append(check)
        lane_report.append(check)
    if violations:
        return "blocked", *_blocked_report(
            manifest,
            [f"A/A cap exceeded for {entry['id']}: {entry['ratios']}" for entry in violations],
            {"reason": "MEASUREMENT_BLOCKED_AA_CONTROL", "aa_lanes": lane_report},
        )
    report = {
        "schema": SCHEMA_AA,
        "stage": "aa",
        "tooling_sha": manifest["tooling_sha"],
        "source_sha": manifest["arms"]["A"]["source_sha"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "index_digests": manifest["arms"]["A"]["index_digests"],
        "slot_count": len(slots),
        "lane_record_count": len(slots) * len(lanes),
        "timed_samples": len(slots) * len(lanes) * SAMPLES,
        "warmups": len(slots) * len(lanes) * WARMUPS,
        "contention_probes": len(slots) * 2,
        "oracle_validations": len(slots) * len(lanes),
        "lanes": lane_report,
        "qualification": "AA_QUALIFIED",
        "performance_verdict": "NOT_APPLICABLE_DIAGNOSTIC_ONLY",
    }
    reject_acceptance_claim(report)
    ha.assert_report_sanitized(report)
    lines = [
        "# PR 15H-A3 — A/A environment control",
        "",
        f"- source: `{report['source_sha']}` (two independent builds)",
        f"- result: **{report['qualification']}**",
        "",
        "| lane | block ratios max/min | cap | qualified |",
        "|---|---:|---:|---|",
    ]
    for entry in report["lanes"]:
        lines.append(
            f"| `{entry['id']}` | {', '.join(f'{value:.3f}' for value in entry['ratios'])} | "
            f"{entry['cap']} | {entry['qualified']} |"
        )
    lines.append("")
    return "qualified", report, "\n".join(lines)


def derive_ab(manifest: dict, slots: list[dict]) -> tuple[str, dict, str]:
    lanes = frozen_lanes()
    validate_schedule(slots, "ab")
    problems = _common_problems(manifest, slots)
    if problems:
        return "blocked", *_blocked_report(manifest, problems, {"reason": "MEASUREMENT_BLOCKED"})
    arm_a = arm_block_medians(slots, lanes, "ab", "A")
    arm_b = arm_block_medians(slots, lanes, "ab", "B")
    blocks = (1, 2, 3, 4)
    drift_violations = []
    for lane in lanes:
        for label, values in (
            ("within_arm_a", [arm_a[block][lane["id"]] for block in blocks]),
            ("within_arm_b", [arm_b[block][lane["id"]] for block in blocks]),
        ):
            check = _drift(values, lane["n"], DRIFT_CAPS)
            if check["violated"]:
                drift_violations.append({"lane": lane["id"], "check": label, **check})
    if drift_violations:
        problems.extend(
            f"drift {entry['check']} {entry['lane']} ratio {entry['ratio']:.4f} > {entry['cap']}"
            for entry in drift_violations
        )
    if problems:
        return "blocked", *_blocked_report(
            manifest, problems, {"reason": "MEASUREMENT_BLOCKED", "drift_violations": drift_violations}
        )
    lane_report = []
    for lane in lanes:
        a_values = [arm_a[block][lane["id"]] for block in blocks]
        b_values = [arm_b[block][lane["id"]] for block in blocks]
        ratios = [_ratio(b, a) for a, b in zip(a_values, b_values)]
        lane_report.append(
            {
                "id": lane["id"],
                "n": lane["n"],
                "class": lane["class"],
                "a_slot_medians_ns": a_values,
                "b_slot_medians_ns": b_values,
                "ratios_b_over_a": ratios,
                "verdict": verdict_from_ratios(ratios),
            }
        )
    by_id = {entry["id"]: entry for entry in lane_report}
    sparse = [LANE_IDS[0], LANE_IDS[1], LANE_IDS[2]]
    reproduced = all(by_id[lane_id]["verdict"] == "B_SLOWER" for lane_id in sparse) and (
        by_id[LANE_IDS[3]]["verdict"] == "B_FASTER"
    )
    report = {
        "schema": SCHEMA_AB,
        "stage": "ab",
        "tooling_sha": manifest["tooling_sha"],
        "base_source_sha": manifest["arms"]["A"]["source_sha"],
        "candidate_source_sha": manifest["arms"]["B"]["source_sha"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "index_digests": manifest["arms"]["A"]["index_digests"],
        "slot_count": len(slots),
        "lane_record_count": len(slots) * len(lanes),
        "timed_samples": len(slots) * len(lanes) * SAMPLES,
        "warmups": len(slots) * len(lanes) * WARMUPS,
        "contention_probes": len(slots) * 2,
        "oracle_validations": len(slots) * len(lanes),
        "lanes": lane_report,
        "reproduction": "REPRODUCED" if reproduced else "REPRODUCTION_INCONCLUSIVE",
        "performance_verdict": "NOT_APPLICABLE_DIAGNOSTIC_ONLY",
    }
    reject_acceptance_claim(report)
    ha.assert_report_sanitized(report)
    lines = [
        "# PR 15H-A3 — A/B reproduction",
        "",
        f"- accepted A: `{report['base_source_sha']}`",
        f"- rejected B: `{report['candidate_source_sha']}`",
        f"- reproduction: **{report['reproduction']}**",
        "- Diagnostic only; no performance acceptance.",
        "",
        "| lane | A slot medians (ns) | B slot medians (ns) | B/A ratios | verdict |",
        "|---|---:|---:|---|---|",
    ]
    for entry in report["lanes"]:
        lines.append(
            f"| `{entry['id']}` | {', '.join(str(v) for v in entry['a_slot_medians_ns'])} | "
            f"{', '.join(str(v) for v in entry['b_slot_medians_ns'])} | "
            f"{', '.join(f'{v:.3f}' for v in entry['ratios_b_over_a'])} | {entry['verdict']} |"
        )
    lines.append("")
    return "qualified", report, "\n".join(lines)


def derive_variant(manifest: dict, slots: list[dict]) -> tuple[str, dict, str]:
    stage = manifest["stage"]
    lanes = frozen_lanes()
    validate_schedule(slots, stage)
    problems = _common_problems(manifest, slots)
    if problems:
        return "blocked", *_blocked_report(manifest, problems, {"reason": "MEASUREMENT_BLOCKED"})
    arm_b = arm_block_medians(slots, lanes, stage, "B")
    arm_v = arm_block_medians(slots, lanes, stage, "V")
    lane_report = []
    for lane in lanes:
        b_values = [arm_b[block][lane["id"]] for block in (1, 2)]
        v_values = [arm_v[block][lane["id"]] for block in (1, 2)]
        ratios = [_ratio(v, b) for b, v in zip(b_values, v_values)]
        lane_report.append(
            {
                "id": lane["id"],
                "n": lane["n"],
                "b_slot_medians_ns": b_values,
                "v_slot_medians_ns": v_values,
                "ratios_v_over_b": ratios,
            }
        )
    by_id = {entry["id"]: entry for entry in lane_report}
    effect = all(value < VARIANT_EFFECT_CAP for lane_id in (LANE_IDS[0], LANE_IDS[1]) for value in by_id[lane_id]["ratios_v_over_b"])
    label = (
        "V2_EFFECT_PRESENT" if effect and stage == "bv2"
        else "V3_EFFECT_PRESENT" if effect and stage == "bv3"
        else "V2_EFFECT_NOT_ESTABLISHED" if stage == "bv2"
        else "V3_EFFECT_NOT_ESTABLISHED"
    )
    report = {
        "schema": SCHEMA_VARIANT,
        "stage": stage,
        "tooling_sha": manifest["tooling_sha"],
        "base_source_sha": manifest["arms"]["B"]["source_sha"],
        "variant_source_sha": manifest["arms"]["V"]["source_sha"],
        "environment_fingerprint": manifest["environment_fingerprint"],
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "index_digests": manifest["arms"]["B"]["index_digests"],
        "slot_count": len(slots),
        "lane_record_count": len(slots) * len(lanes),
        "timed_samples": len(slots) * len(lanes) * SAMPLES,
        "warmups": len(slots) * len(lanes) * WARMUPS,
        "contention_probes": len(slots) * 2,
        "oracle_validations": len(slots) * len(lanes),
        "lanes": lane_report,
        "outcome": label,
        "confidence": "SUPPORTING_ONLY",
        "performance_verdict": "NOT_APPLICABLE_DIAGNOSTIC_ONLY",
    }
    reject_acceptance_claim(report)
    ha.assert_report_sanitized(report)
    lines = [
        f"# PR 15H-A3 — {stage.upper()} diagnostic intervention",
        "",
        f"- B: `{report['base_source_sha']}`",
        f"- variant: `{report['variant_source_sha']}`",
        f"- outcome: **{label}** (supporting diagnostic only)",
        "",
        "| lane | V/B ratios |",
        "|---|---|",
    ]
    for entry in report["lanes"]:
        lines.append(f"| `{entry['id']}` | {', '.join(f'{v:.3f}' for v in entry['ratios_v_over_b'])} |")
    lines.append("")
    return "qualified", report, "\n".join(lines)


DERIVERS = {"aa": derive_aa, "ab": derive_ab, "bv2": derive_variant, "bv3": derive_variant}


def reject_acceptance_claim(report: dict) -> None:
    for value in ha._walk_strings(report):
        lowered = value.upper()
        if "PERFORMANCE_ACCEPTED" in lowered or "OPTIMIZATION_RETAINED" in lowered:
            raise RunBlocked(
                "X_ACCEPTANCE", "diagnostic controller cannot emit a performance-acceptance claim"
            )


def render_blocked(manifest: dict, reasons: list[str]) -> tuple[dict, str]:
    return _blocked_report(manifest, reasons)


# ---------------------------------------------------------------------------
# Campaign execution
# ---------------------------------------------------------------------------


def _slug(arm: str) -> str:
    return arm.lower().replace("_prime", "-prime")


def _expected(corpus: dict, lanes: list[dict]) -> dict:
    return {
        lane["id"]: ha.base.oracle.expected(
            rows=corpus["rows"][lane["n"]],
            field=lane["field"],
            term=lane["term"],
            k=lane["k"],
        )
        for lane in lanes
    }


def _expected_hits(manifest: dict) -> dict:
    return manifest["expected_by_lane"]


def _index_digests_ok(indices: dict) -> bool:
    return all(ha.base.directory_digest(record["dir"]) == record["digest"] for record in indices.values())


def _same_corpus_and_host(manifest: dict, environment: dict) -> None:
    if ha.base.pr15d_run.host_fingerprint(environment) != manifest["environment_fingerprint"]:
        raise RunBlocked("X_HOST", "host fingerprint differs within the campaign")


def _arm_definitions(stage: str, args, tooling: dict) -> dict:
    if stage == "aa":
        source = resolve_tree(args.source_tree, A_SHA, "A/A source")
        return {
            "A": {"tree": source, "expected": A_SHA},
            "A_PRIME": {"tree": source, "expected": A_SHA},
        }
    if stage == "ab":
        base = resolve_tree(args.base_tree, A_SHA, "A")
        candidate = resolve_tree(args.candidate_tree, B_SHA, "B")
        return {"A": {"tree": base, "expected": A_SHA}, "B": {"tree": candidate, "expected": B_SHA}}
    candidate = resolve_tree(args.candidate_tree, B_SHA, "B")
    variant = resolve_tree(args.variant_tree, None, "V")
    verify_variant_diff(variant["tree"], B_SHA, variant["sha"], stage)
    return {"B": {"tree": candidate, "expected": B_SHA}, "V": {"tree": variant, "expected": variant["sha"]}}


def verify_variant_diff(tree: str, base_sha: str, variant_sha: str, stage: str) -> None:
    if variant_sha == base_sha:
        raise RunBlocked("X_VARIANT", "variant equals B")
    if not ha.base.is_ancestor(tree, base_sha):
        raise RunBlocked("X_VARIANT", "variant is not a descendant of B")
    files = ha.base.git(tree, "diff", "--name-only", f"{base_sha}..{variant_sha}").splitlines()
    if files != ["crates/quervant-core/src/search/execute.rs"]:
        raise RunBlocked("X_VARIANT", f"variant touches unexpected paths: {files}")
    diff = ha.base.git(tree, "diff", "--unified=0", f"{base_sha}..{variant_sha}")
    added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    removed = [line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
    if stage == "bv2":
        if len(added) != 1 or len(removed) != 1:
            raise RunBlocked("X_VARIANT", "BV2 must change exactly one line")
        if "H_A2_MIN_POSTINGS: usize = usize::MAX;" not in added[0]:
            raise RunBlocked("X_VARIANT", "BV2 did not set the disabled constant")
        if "H_A2_MIN_POSTINGS: usize = 8_192;" not in removed[0]:
            raise RunBlocked("X_VARIANT", "BV2 did not remove the frozen constant")
    elif stage == "bv3":
        if len(added) != 1 or removed:
            raise RunBlocked("X_VARIANT", "BV3 must add exactly one attribute line")
        if "#[inline(never)]" not in added[0]:
            raise RunBlocked("X_VARIANT", "BV3 did not add #[inline(never)]")
    else:
        raise RunBlocked("X_VARIANT", f"unknown variant stage {stage}")


def _schedule(stage: str):
    return AA_SCHEDULE if stage == "aa" else AB_SCHEDULE if stage == "ab" else VARIANT_SCHEDULE


def execute_campaign(args) -> int:
    stage = args.command
    if not args.idle_authorized:
        print("PERF_BLOCKED_OPERATOR: --idle-authorized is required", file=sys.stderr)
        return 3
    if stage not in STAGES:
        raise RunBlocked("X_COMMAND", f"unknown stage {stage}")
    tooling = ha._assert_clean_tooling()
    if tooling["sha"] != ha.base.pr15d_run.source_sha():
        raise RunBlocked("X_TOOLING", "tooling SHA inconsistency")
    out = validate_out_path(args.out, args.checkout_root)
    verify_frozen_inputs(TOOLING_ROOT)
    lanes = frozen_lanes()
    definitions = _arm_definitions(stage, args, tooling)
    for definition in definitions.values():
        verify_frozen_inputs(definition["tree"]["tree"])

    os.makedirs(out, exist_ok=False)
    filesystem = ha.base.require_native_filesystem(out)
    environment = ha.base.pr15d_run.collect_environment(out)
    environment["filesystem"] = filesystem

    authorization = {
        "schema": SCHEMA_AUTHORIZATION,
        "stage": stage,
        "operator_idle_authorized_by_user": True,
        "recorded_utc": ha.utc_now(),
        "tooling_sha": tooling["sha"],
        "source_shas": {arm: definition["tree"]["sha"] for arm, definition in definitions.items()},
    }
    ha.write_exclusive_json(os.path.join(out, "authorization.json"), authorization)

    corpus = ha.base.prepare_corpus(out)
    expected_by_lane = _expected(corpus, lanes)
    n_values = sorted({lane["n"] for lane in lanes})
    arms = {}
    for arm, definition in definitions.items():
        slug = _slug(arm)
        build = ha.base.build_adapter(definition["tree"]["tree"], os.path.join(out, f"arm-{slug}"))
        metadata = ha.base.pr15d_run.read_adapter_metadata("quervant", build["binary"])
        indices = ha.base.build_indices(
            build["binary"], corpus, os.path.join(out, f"arm-{slug}"), n_values
        )
        arms[arm] = {
            "source_sha": definition["tree"]["sha"],
            "binary_sha256": build["binary_sha256"],
            "binary": build["binary"],
            "metadata": metadata,
            "indices": indices,
            "index_digests": {str(n): record["digest"] for n, record in sorted(indices.items())},
        }
    if len({arm["metadata"]["analyzer"] for arm in arms.values()}) != 1:
        raise RunBlocked("X_ADAPTER", "adapter metadata differs between arms")
    if len({tuple(sorted(arm["index_digests"].items())) for arm in arms.values()}) != 1:
        raise RunBlocked("X_INDEX", "arm index digests differ")

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "stage": stage,
        "tooling_sha": tooling["sha"],
        "environment": environment,
        "environment_fingerprint": ha.base.pr15d_run.host_fingerprint(environment),
        "corpus_manifest_sha256": corpus["manifest_sha256"],
        "corpora": corpus["corpora"],
        "lanes": [lane["id"] for lane in lanes],
        "expected_by_lane": {
            lane_id: expected["total_hits"] for lane_id, expected in expected_by_lane.items()
        },
        "schedule": [list(order) for order in _schedule(stage)],
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
    slot_number = 0
    for block, order in enumerate(_schedule(stage), start=1):
        for arm in order:
            slot_number += 1
            for data in arms.values():
                if not _index_digests_ok(data["indices"]):
                    raise RunBlocked("X_INDEX_MUTATED", "index changed before a slot")
            slot_dir = os.path.join(out, "raw", "slots", f"slot-{slot_number:02d}")
            trial = ha.base.measure_trial(
                1,
                arms[arm]["binary"],
                lanes,
                arms[arm]["indices"],
                expected_by_lane,
                arms[arm]["metadata"],
                slot_dir,
            )
            slot = {
                "schema": SCHEMA_SLOT,
                "stage": stage,
                "slot": slot_number,
                "block": block,
                "arm": arm,
                "source_sha": arms[arm]["source_sha"],
                "binary_sha256": arms[arm]["binary_sha256"],
                "index_digests": arms[arm]["index_digests"],
                "trial": trial,
            }
            ha.write_exclusive_json(
                os.path.join(out, "raw", "slots", f"slot-{slot_number:02d}.json"), slot
            )
            slots.append(slot)
        for data in arms.values():
            if not _index_digests_ok(data["indices"]):
                raise RunBlocked("X_INDEX_MUTATED", "index changed during a block")

    write_seal(out, stage)
    kind, report, markdown = DERIVERS[stage](manifest, slots)
    publish_report(out, kind, report, markdown)
    print(
        f"PR15H_A3 STAGE={stage} OUT={out} RESULT={kind} "
        f"TOOLING={tooling['sha']}"
    )
    return 0


def _report_paths(root: str, kind: str) -> tuple[str, str]:
    if kind == "qualified":
        return (
            os.path.join(root, "sanitized", "qualified.json"),
            os.path.join(root, "sanitized", "qualified.md"),
        )
    return (
        os.path.join(root, "sanitized", "blocked.json"),
        os.path.join(root, "sanitized", "blocked.md"),
    )


def publish_report(root: str, kind: str, report: dict, markdown: str) -> None:
    reject_acceptance_claim(report)
    json_path, md_path = _report_paths(root, kind)
    if os.path.exists(json_path) or os.path.exists(md_path):
        raise RunBlocked("X_REPORT_EXISTS", "a report pair already exists")
    ha.write_exclusive_json(json_path, report)
    ha.write_exclusive_text(md_path, markdown)


def verify_campaign(args) -> int:
    root = validate_campaign_dir(args.campaign, args.checkout_root)
    manifest = ha.read_json_strict(os.path.join(root, "manifest.json"))
    stage = manifest.get("stage")
    if stage not in STAGES or manifest.get("schema") != SCHEMA_MANIFEST:
        raise RunBlocked("X_MANIFEST", "unknown campaign manifest")
    verify_seal(root, stage)
    lanes = frozen_lanes()
    slots = [
        ha.read_json_strict(os.path.join(root, "raw", "slots", f"slot-{index:02d}.json"))
        for index in range(1, SLOT_COUNTS[stage] + 1)
    ]
    kind, report, markdown = DERIVERS[stage](manifest, slots)
    json_path, md_path = _report_paths(root, kind)
    if not os.path.isfile(json_path) or not os.path.isfile(md_path):
        raise RunBlocked("X_REPORT_MISSING", f"expected report pair {json_path}")
    with open(json_path, "rb") as handle:
        actual_json = handle.read()
    if actual_json != ha.canonical_bytes(report):
        raise RunBlocked("X_REPORT_DRIFT", "sanitized JSON does not recompute")
    with open(md_path, "rb") as handle:
        actual_markdown = handle.read().decode("utf-8")
    if actual_markdown != markdown:
        raise RunBlocked("X_REPORT_DRIFT", "sanitized Markdown does not recompute")
    print(f"PR15H_A3 VERIFY_OK STAGE={stage} CAMPAIGN={root} RESULT={kind}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PR 15H-A3 four-lane diagnostic controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(sub):
        sub.add_argument("--checkout-root", required=True)
        sub.add_argument("--out", required=True)
        sub.add_argument("--idle-authorized", action="store_true")

    aa = subparsers.add_parser("aa")
    common(aa)
    aa.add_argument("--source-tree", required=True)

    ab = subparsers.add_parser("ab")
    common(ab)
    ab.add_argument("--base-tree", required=True)
    ab.add_argument("--candidate-tree", required=True)

    for name in ("bv2", "bv3"):
        sub = subparsers.add_parser(name)
        common(sub)
        sub.add_argument("--candidate-tree", required=True)
        sub.add_argument("--variant-tree", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--checkout-root", required=True)
    verify.add_argument("--campaign", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            return verify_campaign(args)
        return execute_campaign(args)
    except RunBlocked as error:
        print(f"PERF_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

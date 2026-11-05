#!/usr/bin/env python3
"""PR 15G-D isolated D2 (without D1) A/X confirmation controller.

Measurement-only. The frozen PR15D/PR15E-B1 helpers are imported read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_spec = importlib.util.spec_from_file_location(
    "pr15g_d_run_for_isolate_d2", os.path.join(HERE, "run.py")
)
d_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(d_run)

BASE = d_run.base
ARM_A = "ca065a212987284144d8901aa5c54de093d6dbfc"
HISTORICAL_D1 = "1d2a6b0f08bf68994699e1f3e37f163347492cd1"
HISTORICAL_D2 = "dae598758a433ecdc0d9af37e15194e948bbc788"
START_HEAD = "317d60d73ccbdc6b9df8843aa91eca36a2f6b318"
SCHEMA = "pr15g-d-d2-only-isolation-v2"
SEAL_SCHEMA = "pr15g-d-d2-only-seal-v2"
SCHEDULE = (
    ("A", "X", "X", "A"),
    ("X", "A", "A", "X"),
    ("X", "A", "A", "X"),
    ("A", "X", "X", "A"),
)
BLOCKS = 4
SLOTS = 16
ARM_SLOTS = 8
SAMPLES = 20
WARMUPS = 5
DRIFT_100K = 1.25
DRIFT_10K = 1.50
LANE_IDS = tuple(d_run.LANE_IDS)
SEARCH_FILES = (
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/unified.rs",
)
AUTH_BASIS = "operator_approved_assumed_idle_for_pr15g_d_d2_only_isolation"


class SealError(Exception):
    pass


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes_exclusive(path: str, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def write_json_exclusive(path: str, value) -> None:
    write_bytes_exclusive(path, json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")


def flat_schedule() -> list[str]:
    return [arm for block in SCHEDULE for arm in block]


def validate_out(checkout_root: str, out: str) -> str:
    root = os.path.realpath(checkout_root)
    allowed = os.path.realpath(
        os.path.join(root, "target", "pr15g-d-d2-isolation", "campaigns")
    )
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise BASE.pr15d_run.RunBlocked(
            "CFX_PATH", "--out must be strictly below target/pr15g-d-d2-isolation/campaigns"
        )
    if os.path.lexists(candidate) and os.path.islink(candidate):
        raise BASE.pr15d_run.RunBlocked("CFX_PATH", "symlink output roots are refused")
    if os.path.exists(candidate):
        raise BASE.pr15d_run.RunBlocked("CFX_EXISTS", "campaign output already exists")
    return candidate


def lane_class(lane_id: str) -> str:
    return lane_id.split("/")[1]


def drift_limit(lane_id: str) -> float:
    return DRIFT_100K if lane_class(lane_id) == "100000" else DRIFT_10K


def _positive_finite(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BASE.pr15d_run.RunBlocked("CFX_DRIFT_DATA", f"{label} is not numeric")
    number = float(value)
    if number <= 0 or number != number or number in (float("inf"), float("-inf")):
        raise BASE.pr15d_run.RunBlocked("CFX_DRIFT_DATA", f"{label} is not positive finite")
    return number


def slot_medians(slots: list[dict], arm: str, lane_id: str) -> list[tuple[int, float]]:
    found = []
    for slot in slots:
        if slot["arm"] != arm:
            continue
        for lane in slot["trial"]["lanes"]:
            if lane["id"] == lane_id:
                median = _positive_finite(lane["summary_ns"]["median"], f"{arm}/{lane_id} median")
                found.append((slot["slot_index"], median))
                break
        else:
            raise BASE.pr15d_run.RunBlocked(
                "CFX_LANE", f"missing lane {lane_id} in slot {slot['slot_index']}"
            )
    if len(found) != ARM_SLOTS:
        raise BASE.pr15d_run.RunBlocked(
            "CFX_OBS", f"{arm}/{lane_id} has {len(found)} observations, expected {ARM_SLOTS}"
        )
    return found


def _by_block(slots: list[dict], arm: str, lane_id: str) -> dict[int, list[float]]:
    grouped = {block: [] for block in range(1, BLOCKS + 1)}
    for slot_index, median in slot_medians(slots, arm, lane_id):
        grouped[1 + (slot_index - 1) // 4].append(median)
    for block, values in grouped.items():
        if len(values) != 2:
            raise BASE.pr15d_run.RunBlocked(
                "CFX_BLOCK", f"block {block} {arm}/{lane_id} has {len(values)} slots"
            )
    return grouped


def block_medians(slots: list[dict], arm: str, lane_id: str) -> list[float]:
    grouped = _by_block(slots, arm, lane_id)
    return [(grouped[block][0] + grouped[block][1]) / 2.0 for block in range(1, BLOCKS + 1)]


def pair_ratios(slots: list[dict], lane_id: str) -> list[float]:
    x = block_medians(slots, "X", lane_id)
    a = block_medians(slots, "A", lane_id)
    ratios = []
    for xv, av in zip(x, a, strict=True):
        ratios.append(_positive_finite(xv, "X block median") / _positive_finite(av, "A block median"))
    return ratios


def lane_verdict(ratios: list[float]) -> str:
    if len(ratios) != BLOCKS or any(
        not isinstance(r, float) or r != r or r in (float("inf"), float("-inf"))
        for r in ratios
    ):
        raise BASE.pr15d_run.RunBlocked("CFX_RATIO", "need four finite ratios")
    if all(r < 1.0 for r in ratios):
        return "X_FASTER"
    if all(r > 1.0 for r in ratios):
        return "A_FASTER"
    return "INCONCLUSIVE"


def compute_drift_diagnostics(slots: list[dict]) -> tuple[dict, list[dict]]:
    drift = {}
    violations = []
    for arm in ("A", "X"):
        drift[arm] = {}
        for lane_id in LANE_IDS:
            grouped = _by_block(slots, arm, lane_id)
            within = [
                _positive_finite(max(values) / min(values), f"{arm}/{lane_id} within-block")
                for values in grouped.values()
            ]
            baseline = block_medians(slots, arm, lane_id)
            cross = _positive_finite(max(baseline) / min(baseline), f"{arm}/{lane_id} cross-block")
            limit = drift_limit(lane_id)
            drift[arm][lane_id] = {
                "within_block": within,
                "baseline_cross_block": cross,
                "within_ok": all(value <= limit for value in within),
                "cross_ok": cross <= limit,
                "limit": limit,
            }
            for block, ratio in enumerate(within, start=1):
                if ratio > limit:
                    violations.append({
                        "arm": arm,
                        "lane": lane_id,
                        "dimension": "within_block",
                        "block": block,
                        "observed_ratio": ratio,
                        "limit": limit,
                    })
            if cross > limit:
                violations.append({
                    "arm": arm,
                    "lane": lane_id,
                    "dimension": "cross_block",
                    "block": None,
                    "observed_ratio": cross,
                    "limit": limit,
                })
    return drift, violations


def drift_report(slots: list[dict]) -> dict:
    drift, failures = compute_drift_diagnostics(slots)
    if failures:
        first = failures[0]
        raise BASE.pr15d_run.RunBlocked(
            "CFX_DRIFT",
            f"drift blocked for {first['arm']}/{first['lane']} {first['dimension']} "
            f"{first['observed_ratio']:.6g} > {first['limit']}",
        )
    return drift


def lane_results(slots: list[dict]) -> list[dict]:
    rows = []
    for lane_id in LANE_IDS:
        ratios = pair_ratios(slots, lane_id)
        rows.append({
            "id": lane_id,
            "a_block_medians_ns": block_medians(slots, "A", lane_id),
            "x_block_medians_ns": block_medians(slots, "X", lane_id),
            "a_slot_medians_ns": [value for _, value in slot_medians(slots, "A", lane_id)],
            "x_slot_medians_ns": [value for _, value in slot_medians(slots, "X", lane_id)],
            "ratios": ratios,
            "verdict": lane_verdict(ratios),
        })
    return rows


def gate_verdicts(lanes: list[dict]) -> dict:
    by_id = {row["id"]: row["verdict"] for row in lanes}
    common = ("pr15d_v1/100000/common/k100", "pr15d_v1/100000/common/k10")
    p01 = all(by_id.get(lane) == "X_FASTER" for lane in common)
    p02 = all(by_id.get(lane) != "A_FASTER" for lane in LANE_IDS)
    gates = {"DX-P01": "PASS" if p01 else "FAIL", "DX-P02": "PASS" if p02 else "FAIL"}
    gates["status"] = "ACCEPT_D2_ONLY" if p01 and p02 else "D2_ONLY_PERFORMANCE_REJECTED"
    return gates


def _expected_lanes() -> dict[str, dict]:
    return {lane["id"]: lane for lane in d_run.stage_lanes()}


def validate_raw(manifest: dict, slots: list[dict]) -> None:
    if len(slots) != SLOTS:
        raise BASE.pr15d_run.RunBlocked("CFX_PARTIAL", f"expected {SLOTS} slots, got {len(slots)}")
    expected_order = flat_schedule()
    expected_lanes = _expected_lanes()
    if set(manifest.get("binary_sha256", {})) != {"A", "X"}:
        raise BASE.pr15d_run.RunBlocked("CFX_MANIFEST", "binary identities missing")
    for index, slot in enumerate(sorted(slots, key=lambda item: item["slot_index"]), start=1):
        arm = expected_order[index - 1]
        if slot.get("slot_index") != index or slot.get("arm") != arm:
            raise BASE.pr15d_run.RunBlocked("CFX_SCHEDULE", f"slot {index} schedule mismatch")
        if slot.get("block") != 1 + (index - 1) // 4 or slot.get("position") != 1 + (index - 1) % 4:
            raise BASE.pr15d_run.RunBlocked("CFX_MANIFEST", f"slot {index} block/position mismatch")
        if slot.get("source_sha") != manifest["sources"][arm]["sha"]:
            raise BASE.pr15d_run.RunBlocked("CFX_MANIFEST", f"slot {index} source mismatch")
        if slot.get("binary_sha256") != manifest["binary_sha256"][arm]:
            raise BASE.pr15d_run.RunBlocked("CFX_MANIFEST", f"slot {index} binary mismatch")
        if slot.get("corpus_manifest_sha256") != manifest["corpus_manifest_sha256"]:
            raise BASE.pr15d_run.RunBlocked("CFX_MANIFEST", f"slot {index} corpus mismatch")
        if slot.get("index_digests") != manifest["index_digests"][arm]:
            raise BASE.pr15d_run.RunBlocked("CFX_MANIFEST", f"slot {index} index mismatch")
        if slot.get("environment_fingerprint") != manifest["environment_fingerprint"]:
            raise BASE.pr15d_run.RunBlocked("CFX_MANIFEST", f"slot {index} host mismatch")
        trial = slot.get("trial", {})
        if trial.get("index") != index:
            raise BASE.pr15d_run.RunBlocked("CFX_SCHEDULE", f"trial index mismatch at {index}")
        lanes = trial.get("lanes", [])
        if [lane.get("id") for lane in lanes] != list(LANE_IDS):
            raise BASE.pr15d_run.RunBlocked("CFX_LANES", f"lane order/set mismatch at slot {index}")
        for lane in lanes:
            lane_id = lane["id"]
            reference = expected_lanes[lane_id]
            for field in ("n", "class", "field", "term", "k", "regime"):
                if lane.get(field) != reference[field]:
                    raise BASE.pr15d_run.RunBlocked("CFX_LANES", f"descriptor mismatch {index}/{lane_id}/{field}")
            if lane.get("regime") != "warm":
                raise BASE.pr15d_run.RunBlocked("CFX_LANES", f"non-warm lane at {index}/{lane_id}")
            if lane.get("warmups") != WARMUPS:
                raise BASE.pr15d_run.RunBlocked("CFX_WARMUP", f"warmup count at {index}/{lane_id}")
            warmup_ids = lane.get("warmup_ids")
            if not isinstance(warmup_ids, list) or len(warmup_ids) != WARMUPS or len(set(warmup_ids)) != WARMUPS:
                raise BASE.pr15d_run.RunBlocked("CFX_WARMUP", f"warmup ids at {index}/{lane_id}")
            if lane.get("oracle_ok") is not True:
                raise BASE.pr15d_run.RunBlocked("CFX_ORACLE", f"oracle failed at {index}/{lane_id}")
            if lane.get("total_hits") != lane.get("expected_total_hits"):
                raise BASE.pr15d_run.RunBlocked("CFX_ORACLE", f"hit count at {index}/{lane_id}")
            if lane.get("doc_ids") != lane.get("expected_doc_ids"):
                raise BASE.pr15d_run.RunBlocked("CFX_ORACLE", f"doc ids at {index}/{lane_id}")
            samples = lane.get("samples_ns")
            if not isinstance(samples, list) or len(samples) != SAMPLES:
                raise BASE.pr15d_run.RunBlocked("CFX_SAMPLE", f"sample count at {index}/{lane_id}")
            if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in samples):
                raise BASE.pr15d_run.RunBlocked("CFX_SAMPLE", f"invalid sample at {index}/{lane_id}")
            try:
                expected_summary = BASE.pr15d_run.summarize(samples)
            except ValueError as error:
                raise BASE.pr15d_run.RunBlocked(
                    "CFX_SAMPLE", "frozen PR15D summary rejected samples"
                ) from error
            if lane.get("summary_ns") != expected_summary:
                raise BASE.pr15d_run.RunBlocked("CFX_SUMMARY", f"summary mismatch at {index}/{lane_id}")
        if trial.get("contention_before", {}).get("state") != "clear":
            raise BASE.pr15d_run.RunBlocked("CFX_CONTENTION", f"before probe at slot {index}")
        if trial.get("contention_after", {}).get("state") != "clear":
            raise BASE.pr15d_run.RunBlocked("CFX_CONTENTION", f"after probe at slot {index}")
    for block in range(1, BLOCKS + 1):
        for arm in ("A", "X"):
            count = sum(1 for slot in slots if slot["block"] == block and slot["arm"] == arm)
            if count != 2:
                raise BASE.pr15d_run.RunBlocked("CFX_BLOCK", f"block {block}/{arm} has {count} slots")


def _clean(value):
    forbidden = ("/home/", "/mnt/", "/tmp/", "\\", "hostname", "username", "pid", "command", "trial-", "slot-", "raw/")
    if isinstance(value, str):
        lowered = value.lower()
        for marker in forbidden:
            if marker in lowered:
                raise BASE.pr15d_run.RunBlocked("CFX_REPORT", "prohibited report marker")
        if value.startswith("/"):
            raise BASE.pr15d_run.RunBlocked("CFX_REPORT", "absolute path in report")
    elif isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    elif isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def sanitize(raw_result: dict) -> dict:
    report = {
        "schema": SCHEMA,
        "source_shas": {"A": raw_result["a_sha"], "X": raw_result["x_sha"]},
        "lanes": [{"id": row["id"], "verdict": row["verdict"]} for row in raw_result["lanes"]],
        "comparisons": {
            row["id"]: {
                "a_block_medians_ns": row["a_block_medians_ns"],
                "x_block_medians_ns": row["x_block_medians_ns"],
                "ratios": row["ratios"],
                "verdict": row["verdict"],
            }
            for row in raw_result["lanes"]
        },
        "drift": {
            arm: {
                lane_id: {
                    "within_block": values["within_block"],
                    "baseline_cross_block": values["baseline_cross_block"],
                    "limit": values["limit"],
                }
                for lane_id, values in lanes.items()
            }
            for arm, lanes in raw_result["drift"].items()
        },
        "gates": raw_result["gates"],
    }
    return _clean(report)


def sanitize_blocked(manifest: dict, drift: dict, violations: list[dict]) -> dict:
    report = {
        "schema": SCHEMA,
        "status": "MEASUREMENT_BLOCKED",
        "reason": "CFX_DRIFT",
        "source_shas": {
            "A": manifest["sources"]["A"]["sha"],
            "X": manifest["sources"]["X"]["sha"],
        },
        "acquisition": {
            "slots": SLOTS,
            "lane_records": SLOTS * len(LANE_IDS),
            "samples": SLOTS * len(LANE_IDS) * SAMPLES,
            "contention_probes": SLOTS * 2,
        },
        "violations": violations,
        "drift": {
            arm: {
                lane_id: {
                    "within_block": values["within_block"],
                    "baseline_cross_block": values["baseline_cross_block"],
                    "limit": values["limit"],
                }
                for lane_id, values in lanes.items()
            }
            for arm, lanes in drift.items()
        },
        "performance_verdict": "NOT_EVALUATED",
    }
    return _clean(report)


def render_json(report: dict) -> bytes:
    return json.dumps(report, sort_keys=True, indent=2).encode() + b"\n"


def render_markdown(report: dict) -> bytes:
    gates = report["gates"]
    lines = ["# PR 15G-D D2-only isolation performance", ""]
    lines.append(f"- A: `{report['source_shas']['A']}`")
    lines.append(f"- X (D2 only): `{report['source_shas']['X']}`")
    lines.append(f"- status: `{gates['status']}`")
    lines.append("")
    lines.append("| lane | A block medians (ns) | X block medians (ns) | X/A ratios | verdict |")
    lines.append("|---|---|---|---|---|")
    for lane_id in LANE_IDS:
        row = report["comparisons"][lane_id]
        a = ", ".join(f"{value:.6g}" for value in row["a_block_medians_ns"])
        x = ", ".join(f"{value:.6g}" for value in row["x_block_medians_ns"])
        ratios = ", ".join(f"{value:.6g}" for value in row["ratios"])
        lines.append(f"| `{lane_id}` | {a} | {x} | {ratios} | {row['verdict']} |")
    lines.append("")
    lines.append("Gates: " + ", ".join(f"{key}={value}" for key, value in gates.items()))
    lines.append("")
    return ("\n".join(lines) + "\n").encode()


def render_blocked_markdown(report: dict) -> bytes:
    lines = ["# PR 15G-D D2-only isolation — measurement blocked", ""]
    lines.append(f"- A: `{report['source_shas']['A']}`")
    lines.append(f"- X (D2 only): `{report['source_shas']['X']}`")
    lines.append(f"- status: `{report['status']}`")
    lines.append(f"- reason: `{report['reason']}`")
    lines.append("- performance verdict: `NOT_EVALUATED`")
    lines.append("")
    lines.append("## Acquisition")
    lines.append("")
    lines.append(f"- slots: {report['acquisition']['slots']}")
    lines.append(f"- lane records: {report['acquisition']['lane_records']}")
    lines.append(f"- samples: {report['acquisition']['samples']}")
    lines.append(f"- contention probes: {report['acquisition']['contention_probes']}")
    lines.append("")
    lines.append("## Drift violations")
    lines.append("")
    lines.append("| arm | lane | dimension | block | observed ratio | limit |")
    lines.append("|---|---|---|---|---|---|")
    for violation in report["violations"]:
        block = "" if violation["block"] is None else str(violation["block"])
        lines.append(
            f"| {violation['arm']} | `{violation['lane']}` | {violation['dimension']} | "
            f"{block} | {violation['observed_ratio']:.12g} | {violation['limit']} |"
        )
    lines.append("")
    lines.append("NO PERFORMANCE VERDICT — DRIFT GATE FAILED")
    lines.append("")
    return ("\n".join(lines) + "\n").encode()


def _git_bytes(root: str, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", root, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if result.returncode != 0:
        raise BASE.pr15d_run.RunBlocked(
            "CFX_SOURCE", f"git {' '.join(args)} failed: {result.stderr[:300]!r}"
        )
    return result.stdout


def _git(root: str, *args: str) -> str:
    return _git_bytes(root, *args).decode("utf-8").strip()


def _diff_edits(root: str, old: str, new: str, path: str) -> tuple[tuple[bytes, ...], tuple[bytes, ...]]:
    patch = _git_bytes(root, "diff", "--no-ext-diff", "--no-renames", "--unified=0", old, new, "--", path)
    added, removed = [], []
    state = "before"
    headers = 0
    hunks = 0
    seen_minus = seen_plus = False
    path_bytes = path.encode()
    for line in patch.splitlines(keepends=True):
        if line.startswith(b"@@ "):
            hunks += 1
            state = "hunk"
            continue
        if state == "before":
            if line.startswith(b"diff --git "):
                headers += 1
                if headers != 1:
                    raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"multiple diff headers for {path}")
                continue
            if line.startswith(b"index "):
                continue
            if line.startswith(b"--- "):
                if line != b"--- a/" + path_bytes + b"\n":
                    raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"unexpected removed-file header for {path}")
                seen_minus = True
                continue
            if line.startswith(b"+++ "):
                if line != b"+++ b/" + path_bytes + b"\n":
                    raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"unexpected added-file header for {path}")
                seen_plus = True
                continue
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"unexpected diff metadata for {path}: {line[:120]!r}")
        if line.startswith(b"+"):
            added.append(line[1:])
        elif line.startswith(b"-"):
            removed.append(line[1:])
        elif line.startswith(b"\\"):
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"newline marker is not allowed for {path}")
        else:
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"unexpected hunk line for {path}: {line[:120]!r}")
    if headers != 1 or not seen_minus or not seen_plus or hunks == 0:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"incomplete diff shape for {path}")
    return tuple(added), tuple(removed)


def _assert_exact_d2_edits(root: str, a: str, x: str) -> None:
    counts = {
        SEARCH_FILES[0]: (15, 0),
        SEARCH_FILES[1]: (43, 1),
    }
    total_added = total_removed = 0
    for path in SEARCH_FILES:
        a_plus, a_minus = _diff_edits(root, a, x, path)
        h_plus, h_minus = _diff_edits(root, HISTORICAL_D1, HISTORICAL_D2, path)
        if a_plus != h_plus or a_minus != h_minus:
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"exact D2 edit mismatch in {path}")
        expected_add, expected_remove = counts[path]
        if (len(a_plus), len(a_minus)) != (expected_add, expected_remove):
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"wrong edit counts in {path}")
        total_added += len(a_plus)
        total_removed += len(a_minus)
    if (total_added, total_removed) != (58, 1):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "wrong total D2 edit counts")
    unified_added = b"".join(_diff_edits(root, a, x, SEARCH_FILES[1])[0])
    if b"fn gd_u20_u21_u22_d2_removes_only_membership_binary_search" not in unified_added:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "original D2 test missing from added stream")


def _worktree(root: str, name: str, sha: str) -> str:
    path = os.path.join(root, "target", "pr15g-d-d2-isolation", "worktrees", name)
    if not os.path.isdir(path):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"missing detached worktree {name}")
    if os.path.islink(path):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"symlink worktree {name}")
    if _git(path, "rev-parse", "HEAD") != sha:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"worktree {name} not pinned to {sha}")
    if _git(path, "status", "--porcelain", "--untracked-files=no"):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"worktree {name} dirty")
    return path


def validate_source_identity(manifest: dict) -> None:
    root = manifest["checkout_root"]
    a = manifest["sources"]["A"]
    x = manifest["sources"]["X"]
    if a["sha"] != ARM_A:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "A is not the pinned baseline")
    if _git(root, "rev-list", "--parents", "-n", "1", x["sha"]).split() != [x["sha"], a["sha"]]:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "X is not a direct child of A")
    changed = _git(root, "diff", "--name-only", a["sha"], x["sha"]).splitlines()
    if len(changed) != 2 or set(changed) != set(SEARCH_FILES):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "X changed files are not exactly the two search files")
    _assert_exact_d2_edits(root, a["sha"], x["sha"])
    for path in SEARCH_FILES:
        data = _git_bytes(root, "show", f"{x['sha']}:{path}")
        if any(symbol in data for symbol in (
            b"charge_absent_exact_term_segment", b"absent_term_candidate", b"gd_test_observation"
        )):
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "D1 symbol present in X")
    unified = _git_bytes(root, "show", f"{x['sha']}:{SEARCH_FILES[1]}")
    execute = _git_bytes(root, "show", f"{x['sha']}:{SEARCH_FILES[0]}")
    if b"let matched = if postings_candidate_eligible {" not in unified:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "D2 membership branch absent")
    if b"fn term_membership_searches()" not in execute or b"record_term_membership_search" not in execute:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "D2 counter absent")
    if b"#[cfg(test)]" not in execute:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "D2 counter is not test-gated")


def _prepare_changed_allowlist(root: str) -> None:
    changed = set(_git(root, "diff", "--name-only", START_HEAD, "HEAD").splitlines())
    fixed = {
        "benchmarks/pr15g_d/isolate_d2.py",
        "benchmarks/pr15g_d/test_isolate_d2.py",
        "benchmarks/pr15g_d/README.md",
        "docs/BENCHMARKING.md",
        "docs/PERF_OPTIMIZATION_PLAN.md",
    }
    for path in changed:
        if path in fixed:
            continue
        if path.startswith("docs/pr-artifacts/pr-15g-d/d2-isolation/fixup-") and path.endswith(".md"):
            continue
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"unauthorized post-start change: {path}")
    status = subprocess.run(
        ["git", "-C", root, "status", "--porcelain"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if status.returncode != 0 or status.stdout.strip():
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "checkout is not clean")
    protected = subprocess.run(
        ["git", "-C", root, "diff", "--quiet", START_HEAD, "HEAD", "--", "crates/"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False,
    )
    if protected.returncode == 1:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "shared production source changed")
    if protected.returncode != 0:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "production diff inspection failed")


def prepare(checkout_root: str, out: str, candidate_sha: str) -> dict:
    root = os.path.realpath(checkout_root)
    if len(candidate_sha) != 40 or any(c not in "0123456789abcdef" for c in candidate_sha):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "candidate SHA must be 40 lowercase hex")
    if candidate_sha == ARM_A:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "candidate cannot equal A")
    _prepare_changed_allowlist(root)
    d_run.verify_frozen_inputs(root)
    a_tree = _worktree(root, "arm-a", ARM_A)
    x_tree = _worktree(root, "arm-x", candidate_sha)
    a_source = BASE.resolve_source_tree(a_tree)
    x_source = BASE.resolve_source_tree(x_tree)
    validate_source_identity({"checkout_root": root, "sources": {"A": a_source, "X": x_source}})
    lanes = d_run.stage_lanes()
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise BASE.pr15d_run.RunBlocked("CFX_LANES", "lane matrix drift")
    BASE.require_native_filesystem(os.path.dirname(out))
    corpus = BASE.prepare_corpus(os.path.join(out, "setup"))
    corpus_digest = BASE.directory_digest(corpus["dir"])
    expected = {
        lane["id"]: BASE.oracle.expected(
            rows=corpus["rows"][lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"]
        )
        for lane in lanes
    }
    builds, indices, metadata = {}, {}, {}
    for arm, source in (("A", a_source), ("X", x_source)):
        arm_dir = os.path.join(out, "setup", "build", arm)
        os.makedirs(arm_dir, exist_ok=True)
        build = BASE.build_adapter(source["tree"], arm_dir)
        builds[arm] = build
        metadata[arm] = BASE.pr15d_run.read_adapter_metadata("quervant", build["binary"])
        idx_dir = os.path.join(out, "setup", "indexes", arm)
        os.makedirs(idx_dir, exist_ok=True)
        indices[arm] = BASE.build_indices(build["binary"], corpus, idx_dir, [10000, 100000])
    for n in (10000, 100000):
        digests = {arm: indices[arm][n]["digest"] for arm in ("A", "X")}
        if len(set(digests.values())) != 1:
            raise BASE.pr15d_run.RunBlocked("CFX_INDEX", f"index digest differs across arms at {n}")
    environment = BASE.pr15d_run.collect_environment(os.path.join(out, "setup"))
    fingerprint = BASE.pr15d_run.host_fingerprint(environment)
    return {
        "root": root,
        "sources": {"A": a_source, "X": x_source},
        "lanes": lanes,
        "corpus": corpus,
        "corpus_digest": corpus_digest,
        "expected": expected,
        "builds": builds,
        "indices": indices,
        "metadata": metadata,
        "environment": environment,
        "fingerprint": fingerprint,
    }


def immutable_checks(prep: dict, out: str) -> None:
    for arm, source in prep["sources"].items():
        if BASE.resolve_source_tree(source["tree"])["sha"] != source["sha"]:
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"source changed for arm {arm}")
        if _git(source["tree"], "status", "--porcelain"):
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"untracked/dirty source for arm {arm}")
        if sha256_file(prep["builds"][arm]["binary"]) != prep["builds"][arm]["binary_sha256"]:
            raise BASE.pr15d_run.RunBlocked("CFX_BINARY", f"binary changed for arm {arm}")
    for arm, indices in prep["indices"].items():
        for n, record in indices.items():
            if BASE.directory_digest(record["dir"]) != record["digest"]:
                raise BASE.pr15d_run.RunBlocked("CFX_INDEX", f"index changed for arm {arm} n{n}")
    if BASE.directory_digest(prep["corpus"]["dir"]) != prep["corpus_digest"]:
        raise BASE.pr15d_run.RunBlocked("CFX_CORPUS", "corpus changed")
    environment = BASE.pr15d_run.collect_environment(os.path.join(out, "setup"))
    if BASE.pr15d_run.host_fingerprint(environment) != prep["fingerprint"]:
        raise BASE.pr15d_run.RunBlocked("CFX_HOST", "host fingerprint changed")


def _manifest(prep: dict) -> dict:
    return {
        "schema": SCHEMA,
        "sources": {
            arm: {"sha": prep["sources"][arm]["sha"], "tree": prep["sources"][arm]["tree"]}
            for arm in ("A", "X")
        },
        "checkout_root": prep["root"],
        "schedule": SCHEDULE,
        "lanes": list(LANE_IDS),
        "corpus_manifest_sha256": prep["corpus"]["manifest_sha256"],
        "corpus_digest": prep["corpus_digest"],
        "index_digests": {
            arm: {str(n): rec["digest"] for n, rec in prep["indices"][arm].items()} for arm in ("A", "X")
        },
        "binary_sha256": {arm: prep["builds"][arm]["binary_sha256"] for arm in ("A", "X")},
        "environment_fingerprint": prep["fingerprint"],
    }


def seal_complete_acquisition(out: str) -> dict:
    raw = os.path.join(out, "raw")
    files = {"authorization.json": sha256_file(os.path.join(raw, "authorization.json")),
             "manifest.json": sha256_file(os.path.join(raw, "manifest.json"))}
    for index in range(1, SLOTS + 1):
        name = f"slots/slot-{index:02d}.json"
        files[name] = sha256_file(os.path.join(raw, name))
    if len(files) != 18:
        raise BASE.pr15d_run.RunBlocked("CFX_SEAL", "seal must contain exactly 18 files")
    payload = {"schema": SEAL_SCHEMA, "files": files}
    try:
        write_json_exclusive(os.path.join(raw, "slot-sha256.json"), payload)
    except FileExistsError as error:
        raise BASE.pr15d_run.RunBlocked("CFX_SEAL", "seal already exists") from error
    return payload


def _load_json_strict(path: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SealError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=pairs)
    except (OSError, ValueError) as error:
        raise SealError(str(error)) from error


def _validate_seal(out: str) -> dict:
    raw = os.path.join(out, "raw")
    seal_path = os.path.join(raw, "slot-sha256.json")
    if not os.path.isfile(seal_path):
        raise BASE.pr15d_run.RunBlocked("LEGACY_UNSEALED", "campaign has no v2 seal")
    try:
        seal = _load_json_strict(seal_path)
    except SealError as error:
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", str(error)) from error
    if not isinstance(seal, dict) or seal.get("schema") != SEAL_SCHEMA or not isinstance(seal.get("files"), dict):
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "invalid seal schema")
    expected = {"authorization.json", "manifest.json"} | {
        f"slots/slot-{index:02d}.json" for index in range(1, SLOTS + 1)
    }
    if set(seal["files"]) != expected:
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "seal file set mismatch")
    for relative, digest in seal["files"].items():
        if os.path.isabs(relative) or ".." in relative.split("/") or not isinstance(digest, str):
            raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "invalid seal entry")
        path = os.path.join(raw, relative)
        if os.path.islink(path) or not os.path.isfile(path):
            raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", f"missing sealed file {relative}")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", f"invalid digest for {relative}")
        if sha256_file(path) != digest:
            raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", f"hash mismatch for {relative}")
    return seal


def _load_campaign(out: str) -> tuple[dict, list[dict]]:
    _validate_seal(out)
    raw = os.path.join(out, "raw")
    try:
        manifest = _load_json_strict(os.path.join(raw, "manifest.json"))
        slots = []
        for index in range(1, SLOTS + 1):
            slots.append(_load_json_strict(os.path.join(raw, "slots", f"slot-{index:02d}.json")))
    except SealError as error:
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", str(error)) from error
    return manifest, slots


def execute(args) -> int:
    if not args.idle_confirmed:
        print("CFX_BLOCKED: --idle-confirmed is required", file=sys.stderr)
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    os.mkdir(out)
    raw = os.path.join(out, "raw")
    os.makedirs(raw)
    write_json_exclusive(os.path.join(raw, "authorization.json"), {
        "basis": AUTH_BASIS,
        "flag": "--idle-confirmed",
        "observed_idle": None,
        "probe_policy": "real clear probes required for every timed slot",
    })
    prep = prepare(root, out, args.candidate_sha)
    manifest = _manifest(prep)
    write_json_exclusive(os.path.join(raw, "manifest.json"), manifest)
    slots = []
    for index, arm in enumerate(flat_schedule(), start=1):
        immutable_checks(prep, out)
        slot_dir = os.path.join(raw, "slots", f"slot-{index:02d}")
        os.makedirs(os.path.join(slot_dir, "contention"), exist_ok=True)
        trial = BASE.measure_trial(
            index,
            prep["builds"][arm]["binary"],
            prep["lanes"],
            prep["indices"][arm],
            prep["expected"],
            prep["metadata"][arm],
            slot_dir,
        )
        record = {
            "slot_index": index,
            "block": 1 + (index - 1) // 4,
            "position": 1 + (index - 1) % 4,
            "arm": arm,
            "source_sha": prep["sources"][arm]["sha"],
            "binary_sha256": prep["builds"][arm]["binary_sha256"],
            "corpus_manifest_sha256": prep["corpus"]["manifest_sha256"],
            "index_digests": {str(n): rec["digest"] for n, rec in prep["indices"][arm].items()},
            "environment_fingerprint": prep["fingerprint"],
            "trial": trial,
        }
        write_json_exclusive(os.path.join(raw, "slots", f"slot-{index:02d}.json"), record)
        slots.append(record)
    immutable_checks(prep, out)
    validate_source_identity(manifest)
    validate_raw(manifest, slots)
    seal_complete_acquisition(out)
    drift, violations = compute_drift_diagnostics(slots)
    sanitized = os.path.join(out, "sanitized")
    os.makedirs(sanitized)
    if violations:
        blocked = sanitize_blocked(manifest, drift, violations)
        write_bytes_exclusive(os.path.join(sanitized, "blocked.json"), render_json(blocked))
        write_bytes_exclusive(os.path.join(sanitized, "blocked.md"), render_blocked_markdown(blocked))
        print("PR15G_D_D2_ONLY status=MEASUREMENT_BLOCKED reason=CFX_DRIFT")
        return 3
    lanes = lane_results(slots)
    gates = gate_verdicts(lanes)
    gates["DX-P03"] = "PASS"
    report = sanitize({
        "a_sha": ARM_A,
        "x_sha": args.candidate_sha,
        "lanes": lanes,
        "drift": drift,
        "gates": gates,
    })
    write_bytes_exclusive(os.path.join(sanitized, "confirmation.json"), render_json(report))
    write_bytes_exclusive(os.path.join(sanitized, "performance.md"), render_markdown(report))
    print(f"PR15G_D_D2_ONLY status={gates['status']}")
    return 0


def verify_only(args) -> int:
    out = os.path.realpath(args.out)
    manifest, slots = _load_campaign(out)
    validate_raw(manifest, slots)
    drift, violations = compute_drift_diagnostics(slots)
    sanitized = os.path.join(out, "sanitized")
    blocked_json = os.path.join(sanitized, "blocked.json")
    blocked_md = os.path.join(sanitized, "blocked.md")
    qualified_json = os.path.join(sanitized, "confirmation.json")
    qualified_md = os.path.join(sanitized, "performance.md")
    if violations:
        if os.path.exists(qualified_json) or os.path.exists(qualified_md):
            raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "qualified report present for blocked campaign")
        blocked = sanitize_blocked(manifest, drift, violations)
        if read_bytes(blocked_json) != render_json(blocked):
            raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "blocked JSON bytes differ")
        if read_bytes(blocked_md) != render_blocked_markdown(blocked):
            raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "blocked Markdown bytes differ")
        print("PR15G_D_D2_ONLY_VERIFY status=MEASUREMENT_BLOCKED VERIFIED")
        return 0
    if os.path.exists(blocked_json) or os.path.exists(blocked_md):
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "blocked report present for qualified campaign")
    lanes = lane_results(slots)
    gates = gate_verdicts(lanes)
    gates["DX-P03"] = "PASS"
    report = sanitize({
        "a_sha": manifest["sources"]["A"]["sha"],
        "x_sha": manifest["sources"]["X"]["sha"],
        "lanes": lanes,
        "drift": drift,
        "gates": gates,
    })
    if read_bytes(qualified_json) != render_json(report):
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "JSON report bytes differ")
    if read_bytes(qualified_md) != render_markdown(report):
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "Markdown report bytes differ")
    print(f"PR15G_D_D2_ONLY_VERIFY status={gates['status']} VERIFIED")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify_only:
            if args.idle_confirmed:
                raise BASE.pr15d_run.RunBlocked("CFX_CLI", "--verify-only and --idle-confirmed are exclusive")
            return verify_only(args)
        if not args.candidate_sha:
            raise BASE.pr15d_run.RunBlocked("CFX_CLI", "--candidate-sha is required for a run")
        if args.idle_confirmed is False:
            raise BASE.pr15d_run.RunBlocked("CFX_CLI", "--idle-confirmed is required for a run")
        return execute(args)
    except BASE.pr15d_run.RunBlocked as error:
        print(f"CFX_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

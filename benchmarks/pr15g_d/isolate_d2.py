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
import statistics
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
SCHEMA = "pr15g-d-d2-only-isolation-v1"
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


def slot_medians(slots: list[dict], arm: str, lane_id: str) -> list[tuple[int, float]]:
    found = []
    for slot in slots:
        if slot["arm"] != arm:
            continue
        for lane in slot["trial"]["lanes"]:
            if lane["id"] == lane_id:
                median = lane["summary_ns"]["median"]
                if not isinstance(median, (int, float)) or not median > 0 or median == float("inf"):
                    raise BASE.pr15d_run.RunBlocked(
                        "CFX_SAMPLE", f"nonpositive/nonfinite median for {arm}/{lane_id}"
                    )
                found.append((slot["slot_index"], float(median)))
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
        if not xv > 0 or not av > 0:
            raise BASE.pr15d_run.RunBlocked("CFX_RATIO", "nonpositive numerator/denominator")
        ratios.append(xv / av)
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


def drift_report(slots: list[dict]) -> dict:
    report = {}
    for arm in ("A", "X"):
        report[arm] = {}
        for lane_id in LANE_IDS:
            grouped = _by_block(slots, arm, lane_id)
            within = [max(values) / min(values) for values in grouped.values()]
            baseline = block_medians(slots, arm, lane_id)
            cross = max(baseline) / min(baseline)
            limit = drift_limit(lane_id)
            report[arm][lane_id] = {
                "within_block": within,
                "baseline_cross_block": cross,
                "within_ok": all(value <= limit for value in within),
                "cross_ok": cross <= limit,
                "limit": limit,
            }
            if not all(value <= limit for value in within) or cross > limit:
                raise BASE.pr15d_run.RunBlocked(
                    "CFX_DRIFT", f"drift blocked for {arm}/{lane_id}"
                )
    return report


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
    gates = {
        "DX-P01": "PASS" if p01 else "FAIL",
        "DX-P02": "PASS" if p02 else "FAIL",
    }
    gates["status"] = (
        "ACCEPT_D2_ONLY"
        if p01 and p02
        else "D2_ONLY_PERFORMANCE_REJECTED"
    )
    return gates


def validate_raw(manifest: dict, slots: list[dict]) -> None:
    if len(slots) != SLOTS:
        raise BASE.pr15d_run.RunBlocked("CFX_PARTIAL", f"expected {SLOTS} slots, got {len(slots)}")
    expected = flat_schedule()
    for index, slot in enumerate(sorted(slots, key=lambda item: item["slot_index"]), start=1):
        if slot.get("slot_index") != index or slot.get("arm") != expected[index - 1]:
            raise BASE.pr15d_run.RunBlocked("CFX_SCHEDULE", f"slot {index} schedule mismatch")
        trial = slot.get("trial", {})
        if trial.get("index") != index:
            raise BASE.pr15d_run.RunBlocked("CFX_SCHEDULE", f"trial index mismatch at {index}")
        lanes = trial.get("lanes", [])
        if [lane.get("id") for lane in lanes] != list(LANE_IDS):
            raise BASE.pr15d_run.RunBlocked("CFX_LANES", f"lane order/set mismatch at slot {index}")
        for lane in lanes:
            if lane.get("oracle_ok") is not True:
                raise BASE.pr15d_run.RunBlocked("CFX_ORACLE", f"oracle failed at {index}/{lane['id']}")
            samples = lane.get("samples_ns")
            if not isinstance(samples, list) or len(samples) != SAMPLES:
                raise BASE.pr15d_run.RunBlocked("CFX_SAMPLE", f"sample count at {index}/{lane['id']}")
            if any(not isinstance(value, int) or value <= 0 for value in samples):
                raise BASE.pr15d_run.RunBlocked("CFX_SAMPLE", f"invalid sample at {index}/{lane['id']}")
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


def _git(tree: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", tree, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode != 0:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


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
    a = manifest["sources"]["A"]
    x = manifest["sources"]["X"]
    if a["sha"] != ARM_A:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "A is not the pinned baseline")
    if _git(manifest["checkout_root"], "rev-list", "--parents", "-n", "1", x["sha"]).split() != [
        x["sha"],
        a["sha"],
    ]:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "X is not a direct child of A")
    changed = _git(manifest["checkout_root"], "diff", "--name-only", a["sha"], x["sha"]).splitlines()
    if sorted(changed) != sorted(SEARCH_FILES):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "X changed files are not exactly the two search files")
    for path in SEARCH_FILES:
        data = _git(manifest["checkout_root"], "show", f"{x['sha']}:{path}")
        if any(symbol in data for symbol in ("charge_absent_exact_term_segment", "absent_term_candidate", "gd_test_observation")):
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "D1 symbol present in X")


def prepare(checkout_root: str, out: str, candidate_sha: str) -> dict:
    root = os.path.realpath(checkout_root)
    if len(candidate_sha) != 40 or any(c not in "0123456789abcdef" for c in candidate_sha):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "candidate SHA must be 40 lowercase hex")
    if candidate_sha == ARM_A:
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "candidate cannot equal A")
    if _git(root, "diff", "--name-only", "99686909f0b428c2627403abf66bf71100fe906e", "HEAD") not in ([], ["benchmarks/pr15g_d/isolate_d2.py", "benchmarks/pr15g_d/test_isolate_d2.py"]):
        changed = _git(root, "diff", "--name-only", "99686909f0b428c2627403abf66bf71100fe906e", "HEAD")
        # The controller may be committed; allow only the two new harness files.
        if sorted(changed.splitlines()) != sorted(["benchmarks/pr15g_d/isolate_d2.py", "benchmarks/pr15g_d/test_isolate_d2.py"]):
            raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "shared branch changed beyond authorized harness/docs")
    if _git(root, "diff", "--quiet", "99686909f0b428c2627403abf66bf71100fe906e", "HEAD", "--", "crates/"):
        raise BASE.pr15d_run.RunBlocked("CFX_SOURCE", "shared production source changed")
    d_run.verify_frozen_inputs(root)
    a_tree = _worktree(root, "arm-a", ARM_A)
    x_tree = _worktree(root, "arm-x", candidate_sha)
    a_source = BASE.resolve_source_tree(a_tree)
    x_source = BASE.resolve_source_tree(x_tree)
    validate_source_identity({
        "checkout_root": root,
        "sources": {"A": a_source, "X": x_source},
    })
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
    validate_raw(manifest, slots)
    drift = drift_report(slots)
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
    sanitized = os.path.join(out, "sanitized")
    os.makedirs(sanitized)
    json_bytes = render_json(report)
    markdown_bytes = render_markdown(report)
    write_bytes_exclusive(os.path.join(sanitized, "confirmation.json"), json_bytes)
    write_bytes_exclusive(os.path.join(sanitized, "performance.md"), markdown_bytes)
    slot_hashes = {
        f"slot-{index:02d}.json": sha256_file(os.path.join(raw, "slots", f"slot-{index:02d}.json"))
        for index in range(1, SLOTS + 1)
    }
    write_json_exclusive(os.path.join(raw, "slot-sha256.json"), slot_hashes)
    gates["DX-P04"] = "PASS"
    print(f"PR15G_D_D2_ONLY status={gates['status']} out={out}")
    return 0


def _load_campaign(out: str) -> tuple[dict, list[dict]]:
    raw = os.path.join(out, "raw")
    manifest = json.load(open(os.path.join(raw, "manifest.json"), encoding="utf-8"))
    hashes = json.load(open(os.path.join(raw, "slot-sha256.json"), encoding="utf-8"))
    slots = []
    for index in range(1, SLOTS + 1):
        name = f"slot-{index:02d}.json"
        path = os.path.join(raw, "slots", name)
        if hashes.get(name) != sha256_file(path):
            raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", f"slot hash mismatch for {name}")
        slots.append(json.load(open(path, encoding="utf-8")))
    return manifest, slots


def verify_only(args) -> int:
    out = os.path.realpath(args.out)
    manifest, slots = _load_campaign(out)
    validate_raw(manifest, slots)
    drift = drift_report(slots)
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
    gates["DX-P04"] = "PASS"
    expected_json = render_json(report)
    expected_md = render_markdown(report)
    if open(os.path.join(out, "sanitized", "confirmation.json"), "rb").read() != expected_json:
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "JSON report bytes differ")
    if open(os.path.join(out, "sanitized", "performance.md"), "rb").read() != expected_md:
        raise BASE.pr15d_run.RunBlocked("CFX_VERIFY", "Markdown report bytes differ")
    print(f"PR15G_D_D2_ONLY_VERIFY status={gates['status']}")
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

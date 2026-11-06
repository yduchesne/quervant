#!/usr/bin/env python3
"""PR 15G-D three-revision, interleaved confirmation controller.

Measurement-only. It imports the frozen two-arm D runner helpers read-only and
executes exactly 18 slots in the predeclared mirrored A/B/C schedule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "pr15g_d_run_for_confirm", os.path.join(HERE, "run.py")
)
d_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(d_run)

BASE = d_run.base
ARM_A = "ca065a212987284144d8901aa5c54de093d6dbfc"
ARM_B = "1d2a6b0f08bf68994699e1f3e37f163347492cd1"
ARM_C = "dae598758a433ecdc0d9af37e15194e948bbc788"
SCHEMA = "pr15g-d-confirm-v1"
AUTH_BASIS = "operator_approved_assumed_idle_for_pr15g_d_confirmation"
SCHEDULE = (
    ("A", "B", "C", "C", "B", "A"),
    ("B", "C", "A", "A", "C", "B"),
    ("C", "A", "B", "B", "A", "C"),
)
LANE_IDS = tuple(d_run.LANE_IDS)
DRIFT_100K = 1.25
DRIFT_10K = 1.50


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_exclusive(path: str, value) -> None:
    data = json.dumps(value, indent=2, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def flat_schedule() -> list[str]:
    return [arm for block in SCHEDULE for arm in block]


def arm_counts() -> dict:
    return {arm: flat_schedule().count(arm) for arm in ("A", "B", "C")}


def validate_out(checkout_root: str, out: str) -> str:
    root = os.path.realpath(checkout_root)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15g-d-confirm"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise BASE.pr15d_run.RunBlocked("CF_PATH", "--out must be strictly under target/pr15g-d-confirm")
    if os.path.lexists(candidate) and os.path.islink(candidate):
        raise BASE.pr15d_run.RunBlocked("CF_PATH", "symlink output roots are refused")
    return candidate


def lane_class(lane_id: str) -> str:
    parts = lane_id.split("/")
    return parts[1]


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
                    raise BASE.pr15d_run.RunBlocked("CF_SAMPLE", f"nonpositive/nonfinite median for {arm}/{lane_id}")
                found.append((slot["slot_index"], float(median)))
                break
        else:
            raise BASE.pr15d_run.RunBlocked("CF_LANE", f"missing lane {lane_id} in slot {slot['slot_index']}")
    if len(found) != 6:
        raise BASE.pr15d_run.RunBlocked("CF_OBS", f"{arm}/{lane_id} has {len(found)} observations, expected 6")
    return found


def block_medians(slots: list[dict], arm: str, lane_id: str) -> list[float]:
    values = slot_medians(slots, arm, lane_id)
    by_block = {1: [], 2: [], 3: []}
    for slot_index, median in values:
        by_block[1 + (slot_index - 1) // 6].append(median)
    for block, medians in by_block.items():
        if len(medians) != 2:
            raise BASE.pr15d_run.RunBlocked("CF_BLOCK", f"block {block} {arm}/{lane_id} has {len(medians)} slots")
    return [statistics.median(sorted(by_block[b])) for b in (1, 2, 3)]


def pairwise_ratios(x: list[float], y: list[float]) -> list[float]:
    if len(x) != 3 or len(y) != 3:
        raise BASE.pr15d_run.RunBlocked("CF_RATIO", "expected three block medians per arm")
    ratios = []
    for a, b in zip(x, y, strict=True):
        if not a > 0 or not b > 0:
            raise BASE.pr15d_run.RunBlocked("CF_RATIO", "nonpositive denominator/numerator")
        ratios.append(a / b)
    return ratios


def pairwise_verdict(ratios: list[float]) -> str:
    if any(not isinstance(r, float) or r != r or r in (float("inf"), float("-inf")) for r in ratios):
        raise BASE.pr15d_run.RunBlocked("CF_RATIO", "nonfinite ratio")
    if all(r < 1.0 for r in ratios):
        return "B_FASTER"
    if all(r > 1.0 for r in ratios):
        return "A_FASTER"
    return "INCONCLUSIVE"


def drift_metrics(slots: list[dict], arm: str, lane_id: str) -> dict:
    values = slot_medians(slots, arm, lane_id)
    by_block = {1: [], 2: [], 3: []}
    for slot_index, median in values:
        by_block[1 + (slot_index - 1) // 6].append(median)
    within = []
    for medians in by_block.values():
        within.append(max(medians) / min(medians))
    baseline = block_medians(slots, arm, lane_id)
    cross = max(baseline) / min(baseline)
    limit = drift_limit(lane_id)
    return {
        "within_block": within,
        "baseline_cross_block": cross,
        "within_ok": all(r <= limit for r in within),
        "cross_ok": cross <= limit,
        "limit": limit,
    }


def comparison_table(slots: list[dict]) -> dict:
    out = {}
    for name, x, y in (("B/A", "B", "A"), ("C/B", "C", "B"), ("C/A", "C", "A")):
        rows = []
        for lane_id in LANE_IDS:
            bx = block_medians(slots, x, lane_id)
            by = block_medians(slots, y, lane_id)
            ratios = pairwise_ratios(bx, by)
            rows.append({
                "id": lane_id,
                "x_block_medians_ns": bx,
                "y_block_medians_ns": by,
                "ratios": ratios,
                "verdict": pairwise_verdict(ratios),
            })
        out[name] = rows
    return out


def gate_verdicts(comparisons: dict) -> dict:
    def verdict(pair: str, lane: str) -> str:
        return next(row["verdict"] for row in comparisons[pair] if row["id"] == lane)

    def no_a(pair: str, exclude: set[str] = frozenset()) -> bool:
        return all(row["verdict"] != "A_FASTER" for row in comparisons[pair] if row["id"] not in exclude)

    d1 = verdict("B/A", "pr15d_v1/100000/absent/k100") == "B_FASTER"
    d1_guard = no_a("B/A", {"pr15d_v1/100000/absent/k100"})
    d2 = any(
        verdict("C/B", lane) == "B_FASTER"
        for lane in ("pr15d_v1/100000/medium/k100", "pr15d_v1/100000/common/k100")
    )
    d2_guard = no_a("C/B")
    cumulative = any(
        verdict("C/A", lane) == "B_FASTER"
        for lane in ("pr15d_v1/100000/medium/k100", "pr15d_v1/100000/common/k100")
    )
    cumulative_guard = no_a("C/A")
    gates = {
        "CF-P01": "PASS" if d1 else "FAIL",
        "CF-P02": "PASS" if d1_guard else "FAIL",
        "CF-P03": "PASS" if d2 else "FAIL",
        "CF-P04": "PASS" if d2_guard else "FAIL",
        "CF-P05": "PASS" if cumulative else "FAIL",
        "CF-P06": "PASS" if cumulative_guard else "FAIL",
    }
    if all(gates[f"CF-P0{i}"] == "PASS" for i in range(1, 7)):
        status = "FULLY_RECONFIRMED"
    elif gates["CF-P01"] == "PASS" and gates["CF-P02"] == "PASS":
        status = "D1_ONLY_RECONFIRMED"
    elif gates["CF-P03"] == "PASS" and gates["CF-P04"] == "PASS":
        status = "D2_INCREMENTAL_ONLY"
    elif gates["CF-P05"] == "PASS" and gates["CF-P06"] == "PASS":
        status = "CUMULATIVE_ONLY"
    else:
        status = "NOT_RECONFIRMED"
    gates["status"] = status
    return gates


def validate_raw(manifest: dict, slots: list[dict]) -> None:
    if len(slots) != 18:
        raise BASE.pr15d_run.RunBlocked("CF_PARTIAL", f"expected 18 slots, got {len(slots)}")
    expected = flat_schedule()
    for index, slot in enumerate(sorted(slots, key=lambda s: s["slot_index"]), start=1):
        if slot.get("slot_index") != index or slot.get("arm") != expected[index - 1]:
            raise BASE.pr15d_run.RunBlocked("CF_SCHEDULE", f"slot {index} schedule mismatch")
        trial = slot.get("trial", {})
        if trial.get("index") != index:
            raise BASE.pr15d_run.RunBlocked("CF_SCHEDULE", f"trial index mismatch at {index}")
        lanes = trial.get("lanes", [])
        if [lane.get("id") for lane in lanes] != list(LANE_IDS):
            raise BASE.pr15d_run.RunBlocked("CF_LANES", f"lane order/set mismatch at slot {index}")
        for lane in lanes:
            if lane.get("oracle_ok") is not True:
                raise BASE.pr15d_run.RunBlocked("CF_ORACLE", f"oracle failed at slot {index}/{lane['id']}")
            samples = lane.get("samples_ns")
            if not isinstance(samples, list) or len(samples) != BASE.pr15d_run.MEASURED:
                raise BASE.pr15d_run.RunBlocked("CF_SAMPLE", f"sample count at slot {index}/{lane['id']}")
            if any(not isinstance(v, int) or v <= 0 for v in samples):
                raise BASE.pr15d_run.RunBlocked("CF_SAMPLE", f"invalid sample at slot {index}/{lane['id']}")
        if trial.get("contention_before", {}).get("state") != "clear":
            raise BASE.pr15d_run.RunBlocked("CF_CONTENTION", f"before probe at slot {index}")
        if trial.get("contention_after", {}).get("state") != "clear":
            raise BASE.pr15d_run.RunBlocked("CF_CONTENTION", f"after probe at slot {index}")


def drift_report(slots: list[dict]) -> dict:
    report = {}
    for arm in ("A", "B", "C"):
        report[arm] = {}
        for lane_id in LANE_IDS:
            metrics = drift_metrics(slots, arm, lane_id)
            report[arm][lane_id] = metrics
            if not metrics["within_ok"] or not metrics["cross_ok"]:
                raise BASE.pr15d_run.RunBlocked("CF_DRIFT", f"drift blocked for {arm}/{lane_id}")
    return report


FORBIDDEN = ("/home/", "/mnt/", "/tmp/", "\\", "hostname", "username", "pid", "command", "trial-", "slot-")


def sanitize(comparisons: dict, gates: dict, drift: dict) -> dict:
    def clean(value):
        if isinstance(value, str):
            lowered = value.lower()
            for marker in FORBIDDEN:
                if marker.lower() in lowered:
                    raise BASE.pr15d_run.RunBlocked("CF_REPORT", "prohibited report marker")
            if value.startswith("/"):
                raise BASE.pr15d_run.RunBlocked("CF_REPORT", "absolute path in report")
        elif isinstance(value, dict):
            return {str(k): clean(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [clean(v) for v in value]
        return value

    report = {
        "schema": SCHEMA,
        "source_shas": {"A": ARM_A, "B": ARM_B, "C": ARM_C},
        "lanes": list(LANE_IDS),
        "comparisons": comparisons,
        "drift": drift,
        "gates": gates,
    }
    return clean(report)


def render_markdown(report: dict) -> str:
    lines = ["# PR 15G-D targeted performance confirmation", ""]
    lines.append(f"- A: `{ARM_A}`")
    lines.append(f"- B (D1): `{ARM_B}`")
    lines.append(f"- C (D1+D2): `{ARM_C}`")
    lines.append(f"- status: `{report['gates']['status']}`")
    lines.append("")
    for pair in ("B/A", "C/B", "C/A"):
        lines.append(f"## {pair}")
        lines.append("| lane | block ratios | verdict |")
        lines.append("|---|---|---|")
        for row in report["comparisons"][pair]:
            ratios = ", ".join(f"{r:.6g}" for r in row["ratios"])
            lines.append(f"| `{row['id']}` | {ratios} | {row['verdict']} |")
        lines.append("")
    lines.append("Gates: " + ", ".join(f"{k}={v}" for k, v in report["gates"].items()))
    lines.append("")
    return "\n".join(lines)


def git(tree: str, *args: str) -> str:
    return subprocess.run(["git", "-C", tree, *args], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()


def ensure_worktree(root: str, name: str, sha: str) -> str:
    path = os.path.join(root, "target", "pr15g-d-confirm", "worktrees", name)
    if os.path.isdir(path):
        if git(path, "rev-parse", "HEAD") != sha or git(path, "status", "--porcelain"):
            raise BASE.pr15d_run.RunBlocked("CF_SOURCE", f"existing worktree {name} is not clean/pinned")
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["git", "-C", root, "worktree", "add", "--detach", path, sha], check=True)
    return path


def prepare(root: str, raw: str) -> dict:
    d_run.verify_frozen_inputs(root)
    trees = {arm: ensure_worktree(root, f"arm-{arm.lower()}", sha) for arm, sha in (("A", ARM_A), ("B", ARM_B), ("C", ARM_C))}
    sources = {arm: BASE.resolve_source_tree(tree) for arm, tree in trees.items()}
    for arm, source in sources.items():
        if source["sha"] != {"A": ARM_A, "B": ARM_B, "C": ARM_C}[arm]:
            raise BASE.pr15d_run.RunBlocked("CF_SOURCE", f"arm {arm} SHA mismatch")
        d_run.verify_frozen_inputs(source["tree"])
    lanes = d_run.stage_lanes()
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise BASE.pr15d_run.RunBlocked("CF_LANES", "lane matrix drift")
    corpus = BASE.prepare_corpus(os.path.join(raw, "setup"))
    expected = {
        lane["id"]: BASE.oracle.expected(
            rows=corpus["rows"][lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"]
        )
        for lane in lanes
    }
    builds, indices, adapter_metadata = {}, {}, {}
    for arm in ("A", "B", "C"):
        arm_dir = os.path.join(raw, "build", arm)
        os.makedirs(arm_dir, exist_ok=True)
        build = BASE.build_adapter(sources[arm]["tree"], arm_dir)
        builds[arm] = build
        adapter_metadata[arm] = BASE.pr15d_run.read_adapter_metadata("quervant", build["binary"])
        idx_dir = os.path.join(raw, "indexes", arm)
        os.makedirs(idx_dir, exist_ok=True)
        indices[arm] = BASE.build_indices(build["binary"], corpus, idx_dir, [10000, 100000])
    for n in (10000, 100000):
        digests = {arm: indices[arm][n]["digest"] for arm in ("A", "B", "C")}
        if len(set(digests.values())) != 1:
            raise BASE.pr15d_run.RunBlocked("CF_INDEX", f"index digest differs across arms at {n}")
    environment = BASE.pr15d_run.collect_environment(os.path.join(raw, "setup"))
    fingerprint = BASE.pr15d_run.host_fingerprint(environment)
    return {
        "sources": sources,
        "lanes": lanes,
        "corpus": corpus,
        "expected": expected,
        "builds": builds,
        "indices": indices,
        "adapter_metadata": adapter_metadata,
        "environment": environment,
        "fingerprint": fingerprint,
    }


def immutable_checks(prep: dict, raw: str) -> None:
    for arm, source in prep["sources"].items():
        if BASE.resolve_source_tree(source["tree"])["sha"] != source["sha"]:
            raise BASE.pr15d_run.RunBlocked("CF_SOURCE", f"source changed for arm {arm}")
        if sha256_file(prep["builds"][arm]["binary"]) != prep["builds"][arm]["binary_sha256"]:
            raise BASE.pr15d_run.RunBlocked("CF_BINARY", f"binary changed for arm {arm}")
    for arm, indices in prep["indices"].items():
        for n, record in indices.items():
            if BASE.directory_digest(record["dir"]) != record["digest"]:
                raise BASE.pr15d_run.RunBlocked("CF_INDEX", f"index changed for arm {arm} n{n}")
    env = BASE.pr15d_run.collect_environment(os.path.join(raw, "setup"))
    if BASE.pr15d_run.host_fingerprint(env) != prep["fingerprint"]:
        raise BASE.pr15d_run.RunBlocked("CF_HOST", "host fingerprint changed")


def execute(args) -> int:
    if not args.idle_confirmed:
        print("CF_BLOCKED: --idle-confirmed is required", file=sys.stderr)
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    if os.path.exists(out):
        raise BASE.pr15d_run.RunBlocked("CF_EXISTS", f"output root already exists: {args.out}")
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
    prep = prepare(root, raw)
    write_json_exclusive(os.path.join(raw, "manifest.json"), {
        "schema": SCHEMA,
        "sources": {arm: {"sha": prep["sources"][arm]["sha"], "tree": prep["sources"][arm]["tree"]} for arm in ("A", "B", "C")},
        "schedule": SCHEDULE,
        "lanes": list(LANE_IDS),
        "corpus_manifest_sha256": prep["corpus"]["manifest_sha256"],
        "index_digests": {arm: {str(n): rec["digest"] for n, rec in prep["indices"][arm].items()} for arm in ("A", "B", "C")},
        "binary_sha256": {arm: prep["builds"][arm]["binary_sha256"] for arm in ("A", "B", "C")},
        "environment_fingerprint": prep["fingerprint"],
    })
    slots = []
    for index, arm in enumerate(flat_schedule(), start=1):
        immutable_checks(prep, raw)
        slot_dir = os.path.join(raw, "slots", f"slot-{index:02d}")
        os.makedirs(os.path.join(slot_dir, "contention"), exist_ok=True)
        trial = BASE.measure_trial(
            index,
            prep["builds"][arm]["binary"],
            prep["lanes"],
            prep["indices"][arm],
            prep["expected"],
            prep["adapter_metadata"][arm],
            slot_dir,
        )
        record = {
            "slot_index": index,
            "block": 1 + (index - 1) // 6,
            "position": 1 + (index - 1) % 6,
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
    immutable_checks(prep, raw)
    validate_raw(json.load(open(os.path.join(raw, "manifest.json"))), slots)
    drift = drift_report(slots)
    comparisons = comparison_table(slots)
    gates = gate_verdicts(comparisons)
    gates["CF-P07"] = "PASS"
    gates["CF-P08"] = "PASS"
    report = sanitize(comparisons, gates, drift)
    sanitized = os.path.join(out, "sanitized")
    os.makedirs(sanitized)
    write_json_exclusive(os.path.join(sanitized, "confirmation.json"), report)
    with open(os.path.join(sanitized, "confirmation.md"), "x", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
    print(f"PR15G_D_CONFIRM status={gates['status']} out={out}")
    return 0


def verify_only(args) -> int:
    out = os.path.realpath(args.out)
    raw = os.path.join(out, "raw")
    manifest = json.load(open(os.path.join(raw, "manifest.json")))
    slots = [json.load(open(os.path.join(raw, "slots", f"slot-{i:02d}.json"))) for i in range(1, 19)]
    validate_raw(manifest, slots)
    drift = drift_report(slots)
    comparisons = comparison_table(slots)
    gates = gate_verdicts(comparisons)
    gates["CF-P07"] = "PASS"
    gates["CF-P08"] = "PASS"
    report = sanitize(comparisons, gates, drift)
    existing = json.load(open(os.path.join(out, "sanitized", "confirmation.json")))
    if existing != report:
        print("CF_VERIFY_MISMATCH", file=sys.stderr)
        return 3
    print(f"PR15G_D_CONFIRM_VERIFY status={gates['status']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        return verify_only(args) if args.verify_only else execute(args)
    except BASE.pr15d_run.RunBlocked as error:
        print(f"CF_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

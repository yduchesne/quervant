#!/usr/bin/env python3
"""PR 15G-E format-aware A/E confirmation runner."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
D_HERE = os.path.join(os.path.dirname(HERE), "pr15g_d")
sys.path.insert(0, D_HERE)
_spec = importlib.util.spec_from_file_location(
    "pr15g_d_run_for_pr15g_e", os.path.join(D_HERE, "run.py")
)
d_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(d_run)
BASE = d_run.base
ARM_A = "ca065a212987284144d8901aa5c54de093d6dbfc"
SCHEMA = "pr15g-e-format-aware-v1"
SEAL_SCHEMA = "pr15g-e-seal-v1"
SCHEDULE = (("A", "E", "E", "A"), ("E", "A", "A", "E"), ("E", "A", "A", "E"), ("A", "E", "E", "A"))
LANE_IDS = tuple(d_run.LANE_IDS)
SLOTS, SAMPLES, WARMUPS = 16, 20, 5
DRIFT_100K, DRIFT_10K = 1.25, 1.50
SEARCH_FILES = (
    "crates/quervant-core/src/search/execute.rs",
    "crates/quervant-core/src/search/unified.rs",
)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes_exclusive(path, data):
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


def write_json_exclusive(path, value):
    write_bytes_exclusive(path, json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")


def flat_schedule():
    return [arm for block in SCHEDULE for arm in block]


def validate_out(root, out):
    allowed = os.path.realpath(os.path.join(root, "target", "pr15g-e", "campaigns"))
    candidate = os.path.realpath(out)
    if os.path.commonpath([candidate, allowed]) != allowed or candidate == allowed:
        raise BASE.pr15d_run.RunBlocked("GE_PATH", "output must be under target/pr15g-e/campaigns")
    if os.path.lexists(candidate) and os.path.islink(candidate):
        raise BASE.pr15d_run.RunBlocked("GE_PATH", "symlink output refused")
    if os.path.exists(candidate):
        raise BASE.pr15d_run.RunBlocked("GE_EXISTS", "campaign output exists")
    return candidate


def _git(tree, *args):
    result = subprocess.run(["git", "-C", tree, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise BASE.pr15d_run.RunBlocked("GE_SOURCE", f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _worktree(root, name, sha):
    path = os.path.join(root, "target", "pr15g-e", "worktrees", name)
    if not os.path.isdir(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["git", "-C", root, "worktree", "add", "--detach", path, sha], check=True)
    if os.path.islink(path) or _git(path, "rev-parse", "HEAD") != sha:
        raise BASE.pr15d_run.RunBlocked("GE_SOURCE", f"worktree {name} not pinned")
    if _git(path, "status", "--porcelain", "--untracked-files=no"):
        raise BASE.pr15d_run.RunBlocked("GE_SOURCE", f"worktree {name} dirty")
    return path


def _segment_minors(index_dir):
    minors = set()
    for root, _, files in os.walk(index_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as handle:
                    head = handle.read(12)
            except OSError:
                continue
            if head[:8] == b"TRWSEG01":
                minors.add(int.from_bytes(head[10:12], "little"))
    return sorted(minors)


def prepare(root, out, candidate_sha):
    if len(candidate_sha) != 40 or any(c not in "0123456789abcdef" for c in candidate_sha):
        raise BASE.pr15d_run.RunBlocked("GE_SOURCE", "candidate must be 40 lowercase hex")
    if candidate_sha == ARM_A:
        raise BASE.pr15d_run.RunBlocked("GE_SOURCE", "candidate equals A")
    d_run.verify_frozen_inputs(root)
    a_tree = _worktree(root, "arm-a", ARM_A)
    e_tree = _worktree(root, "arm-e", candidate_sha)
    a_source = BASE.resolve_source_tree(a_tree)
    e_source = BASE.resolve_source_tree(e_tree)
    if _git(root, "diff", "--quiet", ARM_A, candidate_sha, "--", *SEARCH_FILES) != "":
        raise BASE.pr15d_run.RunBlocked("GE_SOURCE", "candidate changed accepted search files")
    e_support = _git(e_tree, "show", "crates/quervant-core/src/index/support.rs")
    if "with_persistent_offsets(true)" not in e_support:
        raise BASE.pr15d_run.RunBlocked("GE_SOURCE", "candidate does not enable production E emission")
    lanes = d_run.stage_lanes()
    if [lane["id"] for lane in lanes] != list(LANE_IDS):
        raise BASE.pr15d_run.RunBlocked("GE_LANES", "lane drift")
    BASE.require_native_filesystem(os.path.dirname(out))
    corpus = BASE.prepare_corpus(os.path.join(out, "setup"))
    expected = {
        lane["id"]: BASE.oracle.expected(
            rows=corpus["rows"][lane["n"]], field=lane["field"], term=lane["term"], k=lane["k"]
        )
        for lane in lanes
    }
    builds, indices, metadata = {}, {}, {}
    for arm, source in (("A", a_source), ("E", e_source)):
        arm_dir = os.path.join(out, "setup", "build", arm)
        os.makedirs(arm_dir, exist_ok=True)
        build = BASE.build_adapter(source["tree"], arm_dir)
        builds[arm] = build
        metadata[arm] = BASE.pr15d_run.read_adapter_metadata("quervant", build["binary"])
        idx_dir = os.path.join(out, "setup", "indexes", arm)
        os.makedirs(idx_dir, exist_ok=True)
        indices[arm] = BASE.build_indices(build["binary"], corpus, idx_dir, [10000, 100000])
    if _segment_minors(indices["A"][10000]["dir"]) != [0]:
        raise BASE.pr15d_run.RunBlocked("GE_FORMAT", "arm A did not emit v1.0")
    if _segment_minors(indices["E"][10000]["dir"]) != [1]:
        raise BASE.pr15d_run.RunBlocked("GE_FORMAT", "arm E did not emit v1.1")
    env = BASE.pr15d_run.collect_environment(os.path.join(out, "setup"))
    return {
        "root": root,
        "sources": {"A": a_source, "E": e_source},
        "lanes": lanes,
        "corpus": corpus,
        "expected": expected,
        "builds": builds,
        "indices": indices,
        "metadata": metadata,
        "fingerprint": BASE.pr15d_run.host_fingerprint(env),
        "corpus_digest": BASE.directory_digest(corpus["dir"]),
    }


def immutable(prep, out):
    for arm, source in prep["sources"].items():
        if BASE.resolve_source_tree(source["tree"])["sha"] != source["sha"]:
            raise BASE.pr15d_run.RunBlocked("GE_SOURCE", f"{arm} source changed")
        if sha256_file(prep["builds"][arm]["binary"]) != prep["builds"][arm]["binary_sha256"]:
            raise BASE.pr15d_run.RunBlocked("GE_BINARY", f"{arm} binary changed")
    for arm, indices in prep["indices"].items():
        for n, record in indices.items():
            if BASE.directory_digest(record["dir"]) != record["digest"]:
                raise BASE.pr15d_run.RunBlocked("GE_INDEX", f"{arm}/n{n} changed")
    env = BASE.pr15d_run.collect_environment(os.path.join(out, "setup"))
    if BASE.pr15d_run.host_fingerprint(env) != prep["fingerprint"]:
        raise BASE.pr15d_run.RunBlocked("GE_HOST", "host fingerprint changed")


def _manifest(prep):
    return {
        "schema": SCHEMA,
        "sources": {arm: {"sha": prep["sources"][arm]["sha"], "tree": prep["sources"][arm]["tree"]} for arm in ("A", "E")},
        "schedule": SCHEDULE,
        "lanes": list(LANE_IDS),
        "binary_sha256": {arm: prep["builds"][arm]["binary_sha256"] for arm in ("A", "E")},
        "index_digests": {arm: {str(n): r["digest"] for n, r in prep["indices"][arm].items()} for arm in ("A", "E")},
        "index_bytes": {arm: {str(n): sum(os.path.getsize(os.path.join(r["dir"], f)) for f in os.listdir(r["dir"])) for n, r in prep["indices"][arm].items()} for arm in ("A", "E")},
        "corpus_manifest_sha256": prep["corpus"]["manifest_sha256"],
        "corpus_digest": prep["corpus_digest"],
        "environment_fingerprint": prep["fingerprint"],
    }


def validate_raw(manifest, slots):
    if len(slots) != SLOTS:
        raise BASE.pr15d_run.RunBlocked("GE_PARTIAL", "expected 16 slots")
    expected = flat_schedule()
    for index, slot in enumerate(sorted(slots, key=lambda s: s["slot_index"]), 1):
        arm = expected[index - 1]
        if slot.get("slot_index") != index or slot.get("arm") != arm:
            raise BASE.pr15d_run.RunBlocked("GE_SCHEDULE", f"slot {index}")
        if slot.get("block") != 1 + (index - 1) // 4 or slot.get("position") != 1 + (index - 1) % 4:
            raise BASE.pr15d_run.RunBlocked("GE_MANIFEST", f"slot {index} block")
        for field in ("source_sha", "binary_sha256", "corpus_manifest_sha256", "environment_fingerprint"):
            expected_value = (
                manifest["sources"][arm]["sha"] if field == "source_sha"
                else manifest["binary_sha256"][arm] if field == "binary_sha256"
                else manifest["corpus_manifest_sha256"] if field == "corpus_manifest_sha256"
                else manifest["environment_fingerprint"]
            )
            if slot.get(field) != expected_value:
                raise BASE.pr15d_run.RunBlocked("GE_MANIFEST", f"slot {index} {field}")
        if slot.get("index_digests") != manifest["index_digests"][arm]:
            raise BASE.pr15d_run.RunBlocked("GE_MANIFEST", f"slot {index} index")
        trial = slot.get("trial", {})
        if trial.get("index") != index:
            raise BASE.pr15d_run.RunBlocked("GE_SCHEDULE", "trial index")
        lanes = trial.get("lanes", [])
        if [lane.get("id") for lane in lanes] != list(LANE_IDS):
            raise BASE.pr15d_run.RunBlocked("GE_LANES", "lane order")
        for lane in lanes:
            if lane.get("oracle_ok") is not True:
                raise BASE.pr15d_run.RunBlocked("GE_ORACLE", lane["id"])
            samples = lane.get("samples_ns")
            if not isinstance(samples, list) or len(samples) != SAMPLES:
                raise BASE.pr15d_run.RunBlocked("GE_SAMPLE", lane["id"])
            if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in samples):
                raise BASE.pr15d_run.RunBlocked("GE_SAMPLE", lane["id"])
            if lane.get("summary_ns") != BASE.pr15d_run.summarize(samples):
                raise BASE.pr15d_run.RunBlocked("GE_SUMMARY", lane["id"])
        if trial.get("contention_before", {}).get("state") != "clear" or trial.get("contention_after", {}).get("state") != "clear":
            raise BASE.pr15d_run.RunBlocked("GE_CONTENTION", f"slot {index}")
    for block in range(1, 5):
        for arm in ("A", "E"):
            if sum(1 for s in slots if s["block"] == block and s["arm"] == arm) != 2:
                raise BASE.pr15d_run.RunBlocked("GE_BLOCK", f"{block}/{arm}")


def _medians(slots, arm, lane):
    vals = {1: [], 2: [], 3: [], 4: []}
    for slot in slots:
        if slot["arm"] != arm:
            continue
        for record in slot["trial"]["lanes"]:
            if record["id"] == lane:
                vals[slot["block"]].append(record["summary_ns"]["median"])
                break
    result = []
    for block in range(1, 5):
        if len(vals[block]) != 2:
            raise BASE.pr15d_run.RunBlocked("GE_BLOCK", f"{arm}/{lane}/{block}")
        result.append((vals[block][0] + vals[block][1]) / 2.0)
    return result


def _drift(slots):
    drift, violations = {}, []
    for arm in ("A", "E"):
        drift[arm] = {}
        for lane in LANE_IDS:
            vals = {b: [] for b in range(1, 5)}
            for slot in slots:
                if slot["arm"] != arm:
                    continue
                med = next(r["summary_ns"]["median"] for r in slot["trial"]["lanes"] if r["id"] == lane)
                vals[slot["block"]].append(med)
            within = [max(v) / min(v) for v in vals.values()]
            bm = _medians(slots, arm, lane)
            cross = max(bm) / min(bm)
            limit = DRIFT_100K if "/100000/" in lane else DRIFT_10K
            drift[arm][lane] = {"within_block": within, "baseline_cross_block": cross, "limit": limit}
            if any(v > limit for v in within) or cross > limit:
                violations.append({"arm": arm, "lane": lane, "within": within, "cross": cross, "limit": limit})
    return drift, violations


def _results(slots):
    rows = []
    for lane in LANE_IDS:
        a, e = _medians(slots, "A", lane), _medians(slots, "E", lane)
        ratios = [ev / av for ev, av in zip(e, a, strict=True)]
        verdict = "E_FASTER" if all(r < 1 for r in ratios) else "A_FASTER" if all(r > 1 for r in ratios) else "INCONCLUSIVE"
        rows.append({"id": lane, "a_block_medians_ns": a, "e_block_medians_ns": e, "ratios": ratios, "verdict": verdict})
    return rows


def _gates(rows, drift_ok=True):
    by = {r["id"]: r["verdict"] for r in rows}
    p03 = any(by.get(l) == "E_FASTER" for l in ("pr15d_v1/100000/rare/k100", "pr15d_v1/10000/rare/k100"))
    p04 = all(v != "A_FASTER" for v in by.values())
    gates = {"E-P03": "PASS" if p03 else "FAIL", "E-P04": "PASS" if p04 else "FAIL"}
    gates["status"] = "RETAIN_E" if p03 and p04 else "REJECT_E_ROLLED_BACK"
    return gates


def _clean(value):
    if isinstance(value, str):
        for marker in ("/home/", "/mnt/", "/tmp/", "\\", "hostname", "username", "pid", "command", "raw/", "trial-", "slot-"):
            if marker in value.lower():
                raise BASE.pr15d_run.RunBlocked("GE_REPORT", "unsafe marker")
        if value.startswith("/"):
            raise BASE.pr15d_run.RunBlocked("GE_REPORT", "absolute path")
    elif isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _json(report):
    return json.dumps(report, sort_keys=True, indent=2).encode() + b"\n"


def _md(report):
    lines = ["# PR 15G-E format-aware comparison", "", f"- A: `{report['source_shas']['A']}`", f"- E: `{report['source_shas']['E']}`", f"- status: `{report['gates']['status']}`", "", "| lane | E/A ratios | verdict |", "|---|---|---|"]
    for row in report["results"]:
        lines.append(f"| `{row['id']}` | {', '.join(f'{r:.6g}' for r in row['ratios'])} | {row['verdict']} |")
    lines.append("")
    lines.append("Gates: " + ", ".join(f"{k}={v}" for k, v in report["gates"].items()))
    lines.append("")
    return ("\n".join(lines) + "\n").encode()


def seal(out):
    raw = os.path.join(out, "raw")
    files = {"authorization.json": sha256_file(os.path.join(raw, "authorization.json")), "manifest.json": sha256_file(os.path.join(raw, "manifest.json"))}
    for i in range(1, 17):
        files[f"slots/slot-{i:02d}.json"] = sha256_file(os.path.join(raw, "slots", f"slot-{i:02d}.json"))
    write_json_exclusive(os.path.join(raw, "slot-sha256.json"), {"schema": SEAL_SCHEMA, "files": files})


def execute(args):
    if not args.idle_confirmed:
        return 3
    root = os.path.realpath(args.checkout_root)
    out = validate_out(root, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    os.mkdir(out)
    raw = os.path.join(out, "raw")
    os.makedirs(raw)
    write_json_exclusive(os.path.join(raw, "authorization.json"), {"basis": "operator_approved_assumed_idle", "observed_idle": None})
    prep = prepare(root, out, args.candidate_sha)
    manifest = _manifest(prep)
    write_json_exclusive(os.path.join(raw, "manifest.json"), manifest)
    slots = []
    for index, arm in enumerate(flat_schedule(), 1):
        immutable(prep, out)
        slot_dir = os.path.join(raw, "slots", f"slot-{index:02d}")
        os.makedirs(os.path.join(slot_dir, "contention"), exist_ok=True)
        trial = BASE.measure_trial(index, prep["builds"][arm]["binary"], prep["lanes"], prep["indices"][arm], prep["expected"], prep["metadata"][arm], slot_dir)
        record = {"slot_index": index, "block": 1 + (index - 1) // 4, "position": 1 + (index - 1) % 4, "arm": arm, "source_sha": prep["sources"][arm]["sha"], "binary_sha256": prep["builds"][arm]["binary_sha256"], "corpus_manifest_sha256": prep["corpus"]["manifest_sha256"], "index_digests": {str(n): r["digest"] for n, r in prep["indices"][arm].items()}, "environment_fingerprint": prep["fingerprint"], "trial": trial}
        write_json_exclusive(os.path.join(raw, "slots", f"slot-{index:02d}.json"), record)
        slots.append(record)
    immutable(prep, out)
    validate_raw(manifest, slots)
    seal(out)
    drift, violations = _drift(slots)
    if violations:
        print("PR15G_E status=MEASUREMENT_BLOCKED")
        return 3
    rows = _results(slots)
    gates = _gates(rows)
    gates["E-P01"] = "PASS"
    gates["E-P02"] = "PASS"
    report = _clean({"schema": SCHEMA, "source_shas": {"A": ARM_A, "E": args.candidate_sha}, "results": rows, "drift": drift, "gates": gates, "index_bytes": manifest["index_bytes"]})
    os.makedirs(os.path.join(out, "sanitized"))
    write_bytes_exclusive(os.path.join(out, "sanitized", "confirmation.json"), _json(report))
    write_bytes_exclusive(os.path.join(out, "sanitized", "performance.md"), _md(report))
    print(f"PR15G_E status={gates['status']}")
    return 0


def verify_only(args):
    out = os.path.realpath(args.out)
    raw = os.path.join(out, "raw")
    seal_data = json.load(open(os.path.join(raw, "slot-sha256.json")))
    if seal_data.get("schema") != SEAL_SCHEMA or len(seal_data.get("files", {})) != 18:
        raise BASE.pr15d_run.RunBlocked("GE_VERIFY", "bad seal")
    for rel, digest in seal_data["files"].items():
        if sha256_file(os.path.join(raw, rel)) != digest:
            raise BASE.pr15d_run.RunBlocked("GE_VERIFY", f"hash {rel}")
    manifest = json.load(open(os.path.join(raw, "manifest.json")))
    slots = [json.load(open(os.path.join(raw, "slots", f"slot-{i:02d}.json"))) for i in range(1, 17)]
    validate_raw(manifest, slots)
    drift, violations = _drift(slots)
    if violations:
        print("PR15G_E_VERIFY status=MEASUREMENT_BLOCKED")
        return 0
    rows = _results(slots)
    gates = _gates(rows)
    gates["E-P01"] = "PASS"
    gates["E-P02"] = "PASS"
    report = _clean({"schema": SCHEMA, "source_shas": {"A": manifest["sources"]["A"]["sha"], "E": manifest["sources"]["E"]["sha"]}, "results": rows, "drift": drift, "gates": gates, "index_bytes": manifest["index_bytes"]})
    if open(os.path.join(out, "sanitized", "confirmation.json"), "rb").read() != _json(report):
        raise BASE.pr15d_run.RunBlocked("GE_VERIFY", "JSON mismatch")
    if open(os.path.join(out, "sanitized", "performance.md"), "rb").read() != _md(report):
        raise BASE.pr15d_run.RunBlocked("GE_VERIFY", "Markdown mismatch")
    print(f"PR15G_E_VERIFY status={gates['status']} VERIFIED")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--candidate-sha")
    parser.add_argument("--out", required=True)
    parser.add_argument("--idle-confirmed", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify_only:
            return verify_only(args)
        if not args.candidate_sha:
            raise BASE.pr15d_run.RunBlocked("GE_CLI", "candidate required")
        return execute(args)
    except BASE.pr15d_run.RunBlocked as error:
        print(f"GE_BLOCKED: {error.rule}: {error.detail}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

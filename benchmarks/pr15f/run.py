#!/usr/bin/env python3
"""PR 15F P0 campaign runner: fixed prepare, query, reopen and inventory order.

Subcommands (exactly):

    prepare        --prepared-run <target/pr15e/...> --out <target/pr15f/run-XX>
    query-perf     --prepared-run <...> --out <...> --idle-confirmed
    reopen-single  --prepared-run <...> --out <...> --idle-confirmed
    reopen-perf    --prepared-run <...> --out <...> --idle-confirmed
    inventory      --prepared-run <...> --out <...>
    allocation     --prepared-run <...> --out <...> --idle-confirmed

The runner never re-implements query evaluation, never edits a frozen fixture,
never writes inside a prepared index and never publishes raw evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _THIS_DIR not in sys.path:  # make sibling modules importable for tests
    sys.path.insert(0, _THIS_DIR)

import profile_queries as pq  # noqa: E402  (after sys.path adjustment)

SCHEMA_PREPARE = "pr15f-prepare-v1"
SCHEMA_QUERY_CAMPAIGN = "pr15f-query-campaign-v1"
SCHEMA_REOPEN_SINGLE = "pr15f-reopen-single-v1"
SCHEMA_REOPEN_PERF = "pr15f-reopen-perf-v1"
SCHEMA_INVENTORY = "pr15f-inventory-campaign-v1"
SCHEMA_ALLOCATION = "pr15f-allocation-campaign-v1"

PROBE_REL_MANIFEST = os.path.join("benchmarks", "pr15f", "reopen_probe", "Cargo.toml")
PROBE_REL_LOCK = os.path.join("benchmarks", "pr15f", "reopen_probe", "Cargo.lock")
PROBE_MANIFEST = os.path.join(REPO_ROOT, PROBE_REL_MANIFEST)
PROBE_LOCK = os.path.join(REPO_ROOT, PROBE_REL_LOCK)
PROBE_BINARY_NAME = "pr15f-reopen-probe"

REOPEN_BLOCK_LAUNCHES = 21
REOPEN_PERF_ITERATIONS = {10000: 128, 100000: 64}
HOSTORICAL_100K_INDEX_BYTES = 30_965_025
HISTORICAL_100K_REOPEN_NS = 423_193_000

PROTECTED_PREFIXES = (
    "crates/",
    "benchmarks/pr15d/",
    "benchmarks/pr15e/",
    "benchmarks/pr15e_b1/",
    "benchmarks/reports/pr15d/",
    "benchmarks/reports/pr15e-b1/",
    "docs/pr-artifacts/pr-15e-b1/",
)


class CampaignError(pq.Pr15fError):
    pass


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def _git(*args) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _tool_version(argv: list[str]) -> str | None:
    result = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0] if text else None


def protected_tree_hash(rev: str = "HEAD") -> dict:
    output = _git("ls-tree", "-r", rev, "--", *PROTECTED_PREFIXES)
    if output is None:
        raise CampaignError("HARD_STOP", "X01_GIT", "cannot read the protected tree")
    entries = {}
    for line in output.splitlines():
        metadata, path = line.split("\t", 1)
        _mode, kind, blob = metadata.split()
        entries[path] = {"kind": kind, "blob": blob}
    return {
        "rev": _git("rev-parse", rev),
        "tree_sha256": pq.sha256_bytes(pq.canonical_json_bytes(entries)),
        "file_count": len(entries),
    }


def tree_is_clean() -> bool:
    status = _git("status", "--porcelain=v1")
    return status is not None and status == ""


def environment_snapshot() -> dict:
    """Host facts for the private preflight; never published verbatim."""
    return {
        "kernel": eprofile_environment("kernel"),
        "filesystem": eprofile_environment("filesystem"),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "rustc_stable": _tool_version(["rustc", "--version"]),
        "cargo_stable": _tool_version(["cargo", "--version"]),
        "rustc_msrv": _tool_version(["cargo", "+1.85.0", "rustc", "--version"]),
        "java": _tool_version(["java", "-version"]),
    }


def eprofile_environment(key: str):
    try:
        environment = pq.eprofile.host_environment()
    except Exception:  # pragma: no cover - environment dependent
        return None
    return environment.get(key)


def choose_run_dir(raw: str) -> tuple[str, str | None]:
    """Resolve an exclusive run directory, applying the 02..05 suffix ladder."""
    resolved = pq.resolve_run_dir(raw, must_exist=False)
    candidates = [resolved]
    if resolved.endswith("-01"):
        prefix = resolved[:-3]
        candidates.extend(f"{prefix}-{suffix:02d}" for suffix in range(2, 6))
    else:
        prefix = None
    for candidate in candidates:
        if not os.path.exists(candidate):
            if candidate != resolved:
                os.makedirs(candidate, exist_ok=False)
            return candidate, (candidate if candidate != resolved else None)
        if not os.path.isdir(candidate):
            raise CampaignError(
                "UNSAFE", "X28_UNSAFE_PATH", f"run path is not a directory: {candidate}"
            )
        if not os.listdir(candidate):
            return candidate, (candidate if candidate != resolved else None)
    raise CampaignError(
        "HARD_STOP",
        "X28_DESTINATION_EXISTS",
        f"all run suffixes are occupied for {prefix or resolved}; preserving every attempt",
    )


def require_run_dir(raw: str) -> str:
    resolved = pq.resolve_run_dir(raw, must_exist=True)
    if pq.eprofile.iter_symlinks(resolved):
        raise CampaignError("UNSAFE", "X29_SYMLINK", "run directory contains symlinks")
    return resolved


def load_json(path: str) -> dict:
    try:
        return pq.read_json(path)
    except (OSError, ValueError) as error:
        raise CampaignError("BLOCKED", "X33_PREPARE_INVALID", f"unreadable {path}: {error}")


def verify_preflight_identity(out_dir: str) -> dict:
    preflight = load_json(os.path.join(out_dir, "preflight.json"))
    binary = os.path.join(out_dir, preflight["probe"]["binary_rel"])
    if not os.path.isfile(binary):
        raise CampaignError("HARD_STOP", "X24_BINARY_CHANGED", "probe binary is missing")
    if pq.sha256_file(binary) != preflight["probe"]["binary_sha256"]:
        raise CampaignError("HARD_STOP", "X24_BINARY_CHANGED", "probe binary digest changed")
    if pq.sha256_file(PROBE_MANIFEST) != preflight["probe"]["manifest_sha256"]:
        raise CampaignError("HARD_STOP", "X24_SOURCE_CHANGED", "probe manifest changed")
    if pq.sha256_file(PROBE_LOCK) != preflight["probe"]["lock_sha256"]:
        raise CampaignError("HARD_STOP", "X24_SOURCE_CHANGED", "probe lock changed")
    pq.source_lock()
    return preflight


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def read_published_anchors() -> dict:
    report_path = os.path.join(
        REPO_ROOT, "benchmarks/reports/pr15e-b1/optimized-three-engine-pr15d.json"
    )
    report = pq.read_json(report_path)
    if report.get("status") != "QUALIFIED":
        raise CampaignError("HARD_STOP", "X01_ANCHOR", "three-engine report is not QUALIFIED")
    if report.get("source_sha") != "40ca10bae46f2d7df7804a0a129a99a4daf35ef0":
        raise CampaignError("HARD_STOP", "X01_ANCHOR", "three-engine source_sha changed")
    lanes = {}
    for entry in report.get("latency", []):
        if entry.get("regime") != pq.REGIME or entry.get("n") != 100000:
            continue
        if entry.get("k") != 100:
            continue
        engine = entry.get("engines", {}).get("quervant", {})
        lanes[entry["class"]] = {
            "lane_id": entry.get("id"),
            "median_ns": engine.get("median_ns"),
            "trial_medians_ns": engine.get("trial_medians_ns"),
        }
    expected_classes = set(pq.eprofile.CLASS_NAMES)
    if set(lanes) != expected_classes:
        raise CampaignError("HARD_STOP", "X01_ANCHOR", "100K warm lane set changed")
    if any(value["median_ns"] is None for value in lanes.values()):
        raise CampaignError("HARD_STOP", "X01_ANCHOR", "an anchor lane has no median")
    indexing = report.get("indexing", {}).get("quervant", {}).get("100000", {})
    index_bytes = indexing.get("index_bytes", {}).get("median")
    reopen_ns = indexing.get("reopen_ns", {}).get("median")
    if index_bytes is None or reopen_ns is None:
        raise CampaignError("HARD_STOP", "X01_ANCHOR", "index byte/reopen anchor missing")
    return {
        "three_engine_report_sha256": pq.sha256_file(report_path),
        "three_engine_source_sha": report["source_sha"],
        "warm_100k_quervant_k100": lanes,
        "index_bytes_100k": index_bytes,
        "build_phase_reopen_ns_100k": reopen_ns,
    }


def build_probe(out_dir: str) -> dict:
    target_dir = os.path.join(out_dir, "build", "reopen")
    argv = [
        "cargo",
        "build",
        "--release",
        "--locked",
        "--manifest-path",
        PROBE_MANIFEST,
        "--target-dir",
        target_dir,
    ]
    result = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    log_path = os.path.join(out_dir, "build", "probe-build.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write(" ".join(argv) + "\n\n")
        handle.write(result.stdout or "")
        handle.write(result.stderr or "")
    if result.returncode != 0:
        raise CampaignError(
            "FAILED", "X29_BUILD_FAILED", "reopen probe release build failed"
        )
    binary = os.path.join(target_dir, "release", PROBE_BINARY_NAME)
    if not os.path.isfile(binary):
        raise CampaignError("FAILED", "X29_BUILD_OUTPUT", "probe binary is missing")
    return {
        "command": argv,
        "binary_rel": pq.rel_path(binary, out_dir),
        "binary_bytes": os.path.getsize(binary),
        "binary_sha256": pq.sha256_file(binary),
        "manifest_sha256": pq.sha256_file(PROBE_MANIFEST),
        "lock_sha256": pq.sha256_file(PROBE_LOCK),
        "source_sha256": pq.sha256_file(os.path.join(_THIS_DIR, "reopen_probe", "src", "main.rs")),
        "rustc": _tool_version(["rustc", "--version"]),
        "cargo": _tool_version(["cargo", "--version"]),
        "release_profile": True,
    }


def prepare(args) -> int:
    prepared_run = pq.resolve_prepared_run(args.prepared_run)
    if not tree_is_clean():
        raise CampaignError(
            "FAILED", "X08_DIRTY_TREE", "prepare requires a clean tracked tree"
        )
    head = _git("rev-parse", "HEAD")
    if not head:
        raise CampaignError("BLOCKED", "X01_GIT", "cannot resolve HEAD")
    if not os.path.isfile(os.path.join(prepared_run, "prepare.json")):
        raise CampaignError("BLOCKED", "X24_PREPARE_MISSING", "prepared prepare.json is absent")
    prepared = pq.eprofile.read_json(os.path.join(prepared_run, "prepare.json"))
    if prepared.get("source", {}).get("head_sha") != head:
        raise CampaignError(
            "HARD_STOP",
            "X24_SOURCE_CHANGED",
            "prepared run was not built from the current committed HEAD",
        )
    pq.verify_prepared_state(prepared_run)

    out_dir, relocated = choose_run_dir(args.out)
    os.makedirs(out_dir, exist_ok=True)
    anchors = read_published_anchors()
    probe = build_probe(out_dir)
    environment = environment_snapshot()
    preflight = {
        "schema": SCHEMA_PREPARE,
        "status": "PREPARED",
        "source_sha": head,
        "origin_main_sha": _git("rev-parse", "origin/main"),
        "protected_tree": protected_tree_hash("HEAD"),
        "prepared_run": pq.rel_path(prepared_run, REPO_ROOT),
        "prepared_digest": prepared.get("prepared_digest"),
        "prepared_sha256": pq.sha256_file(os.path.join(prepared_run, "prepare.json")),
        "corpus_manifest_sha256": prepared["corpus"]["manifest_sha256"],
        "index_inventory_sha256": {
            key: value["inventory"]["sha256"]
            for key, value in prepared["indexes"].items()
        },
        "adapter_binary_sha256": prepared["build"]["binary_sha256"],
        "source_lock": pq.source_lock(),
        "tool_module_lock": pq.tool_module_lock(),
        "anchors": anchors,
        "probe": probe,
        "environment": environment,
        "run_dir_relocated_from": (
            pq.rel_path(args.out, REPO_ROOT) if relocated else None
        ),
        "authorization_basis": pq.AUTHORIZATION_BASIS,
    }
    preflight["preflight_digest"] = pq.sha256_bytes(pq.canonical_json_bytes(preflight))
    pq.write_json(os.path.join(out_dir, "preflight.json"), preflight)
    print(
        pq.canonical_json_bytes(
            {
                "status": "PREPARED",
                "run": pq.rel_path(out_dir, REPO_ROOT),
                "source_sha": head,
                "probe_sha256": probe["binary_sha256"],
                "preflight_sha256": pq.sha256_file(
                    os.path.join(out_dir, "preflight.json")
                ),
            }
        ).decode("utf-8")
    )
    return pq.EXIT_OK


# ---------------------------------------------------------------------------
# query-perf
# ---------------------------------------------------------------------------


def _capture_call(prepared_run: str, capture_dir: str, descriptor: dict, idle: bool) -> int:
    namespace = argparse.Namespace(
        prepared_run=prepared_run,
        out=capture_dir,
        n=descriptor["n"],
        class_name=descriptor["class"],
        k=descriptor["k"],
        tool=descriptor["tool"],
        seconds=descriptor["seconds"],
        idle_confirmed=idle,
    )
    return pq.capture(namespace)


def _deferrable(error: pq.Pr15fError) -> bool:
    return error.status == "BLOCKED"


def query_perf(args) -> int:
    if not args.idle_confirmed:
        raise CampaignError(
            "BLOCKED", "BLOCKED_AUTHORIZATION", "--idle-confirmed is required"
        )
    prepared_run = pq.resolve_prepared_run(args.prepared_run)
    out_dir = require_run_dir(args.out)
    verify_preflight_identity(out_dir)
    records = []
    hard_stopped = None
    for descriptor in pq.perf_lane_descriptors():
        capture_dir = os.path.join(out_dir, descriptor["rel_dir"].replace("/", os.sep))
        entry = {
            "capture_id": descriptor["capture_id"],
            "lane_id": descriptor["pr15f_lane_id"],
            "n": descriptor["n"],
            "class": descriptor["class"],
            "k": descriptor["k"],
            "tool": descriptor["tool"],
            "seconds": descriptor["seconds"],
        }
        try:
            _capture_call(prepared_run, capture_dir, descriptor, True)
            entry["status"] = "CAPTURED"
        except pq.Pr15fError as error:
            entry.update({"status": error.status, "code": error.code, "detail": error.detail})
            if not _deferrable(error) and error.status in ("HARD_STOP", "UNSAFE"):
                hard_stopped = entry.copy()
                records.append(entry)
                break
        records.append(entry)
    campaign = {
        "schema": SCHEMA_QUERY_CAMPAIGN,
        "status": (
            "HARD_STOP"
            if hard_stopped
            else "QUALIFIED"
            if all(record["status"] == "CAPTURED" for record in records)
            and len(records) == len(pq.PERF_LANES)
            else "PARTIAL"
        ),
        "captured": sum(1 for record in records if record["status"] == "CAPTURED"),
        "required": len(pq.PERF_LANES),
        "lanes": records,
        "hard_stop": hard_stopped,
    }
    pq.write_json(os.path.join(out_dir, "query-campaign.json"), campaign)
    print(pq.canonical_json_bytes(campaign).decode("utf-8"))
    if campaign["status"] == "HARD_STOP":
        return pq.EXIT_HARD_STOP
    return pq.EXIT_OK if campaign["status"] == "QUALIFIED" else pq.EXIT_BLOCKED


# ---------------------------------------------------------------------------
# reopen-single
# ---------------------------------------------------------------------------


def _probe_command(binary: str, mode: str, index_dir: str, n: int, iterations=None):
    argv = [binary, "--mode", mode, "--index-dir", index_dir, "--n", str(n)]
    if iterations is not None:
        argv.extend(["--iterations", str(iterations)])
    return argv


def _parse_probe_stdout(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise CampaignError(
            "HARD_STOP",
            "X22_PROBE_PROTOCOL",
            f"probe emitted {len(lines)} non-empty stdout lines",
        )
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "probe stdout is not JSON")
    if not isinstance(payload, dict):
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "probe payload is not an object")
    return payload


def validate_stage(stage: dict) -> None:
    if not isinstance(stage, dict):
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "stage is not an object")
    for field in (
        "fs_directory_open_ns",
        "index_open_ns",
        "snapshot_acquire_ns",
        "reopen_core_ns",
        "reopen_total_ns",
    ):
        value = stage.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise CampaignError(
                "HARD_STOP", "X22_PROBE_PROTOCOL", f"{field} is not strictly positive"
            )
    if stage["reopen_core_ns"] != stage["index_open_ns"] + stage["snapshot_acquire_ns"]:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "reopen_core_ns disagrees")
    if stage["reopen_total_ns"] != stage["fs_directory_open_ns"] + stage["reopen_core_ns"]:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "reopen_total_ns disagrees")


def validate_probe_payload(payload: dict, mode: str, n: int, iterations: int) -> list[dict]:
    if payload.get("schema") != pq.PROBE_SCHEMA:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "probe schema mismatch")
    if payload.get("mode") != mode:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "probe mode mismatch")
    if payload.get("n") != n:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "probe N mismatch")
    samples = payload.get("iterations")
    if not isinstance(samples, list) or len(samples) != iterations:
        raise CampaignError(
            "HARD_STOP",
            "X22_PROBE_PROTOCOL",
            f"expected {iterations} stage observations",
        )
    if payload.get("iteration_count") != iterations:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "iteration_count mismatch")
    if payload.get("documents_verified") != n:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "document count mismatch")
    if not isinstance(payload.get("segments_verified"), int) or payload["segments_verified"] < 1:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "segment count is not positive")
    if not isinstance(payload.get("generation"), int) or payload["generation"] < 1:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "generation is not positive")
    totals = payload.get("stage_totals_ns")
    if not isinstance(totals, dict) or totals.get("sample_count") != iterations:
        raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "stage totals are invalid")
    for stage in samples:
        validate_stage(stage)
        if stage.get("documents") != n:
            raise CampaignError("HARD_STOP", "X22_PROBE_PROTOCOL", "stage documents mismatch")
    return samples


def summarize_reopen(samples: list[dict]) -> dict:
    stages = (
        "fs_directory_open_ns",
        "index_open_ns",
        "snapshot_acquire_ns",
        "reopen_core_ns",
        "reopen_total_ns",
    )
    summary = {}
    for stage in stages:
        values = sorted(sample[stage] for sample in samples)
        baseline = pr15d_summarize(values)
        median = baseline["median"]
        deviations = sorted(abs(value - median) for value in values)
        summary[stage] = {
            **baseline,
            "median_absolute_deviation": pr15d_median(deviations),
        }
    return summary


def pr15d_summarize(values: list[int]) -> dict:
    return pq.eprofile.run.summarize(values)


def pr15d_median(values: list[int]) -> int:
    count = len(values)
    ordered = sorted(values)
    return ordered[(count - 1) // 2] if count % 2 == 1 else ordered[count // 2]


def reopen_launch_sequence() -> list[dict]:
    """The fixed 42-launch rotation, in execution order."""
    sequence = []
    for block_index, label in enumerate(("block1", "block2")):
        even_is_10k = block_index == 0
        for position in range(REOPEN_BLOCK_LAUNCHES):
            n = 10000 if (position % 2 == 0) == even_is_10k else 100000
            sequence.append({"block": label, "position": position, "n": n})
    return sequence


def reopen_single(args) -> int:
    if not args.idle_confirmed:
        raise CampaignError(
            "BLOCKED", "BLOCKED_AUTHORIZATION", "--idle-confirmed is required"
        )
    prepared_run = pq.resolve_prepared_run(args.prepared_run)
    out_dir = require_run_dir(args.out)
    preflight = verify_preflight_identity(out_dir)
    pq.verify_prepared_state(prepared_run)
    binary = os.path.join(out_dir, preflight["probe"]["binary_rel"])
    index_dirs = {
        n: os.path.join(prepared_run, "indexes", f"n{n}") for n in pq.eprofile.N_VALUES
    }
    root = os.path.join(out_dir, "reopen", "single")
    os.makedirs(root, exist_ok=True)

    def contention(label: str) -> str:
        path = os.path.join(root, f"contention-{label}.json")
        record = pq.eprofile.run.check_contention(path)
        return record.get("state")

    probes = {}
    launches = {"block1": [], "block2": []}
    per_n = {str(n): [] for n in pq.eprofile.N_VALUES}
    failures = []
    for launch in reopen_launch_sequence():
        label = launch["block"]
        position = launch["position"]
        n = launch["n"]
        if position == 0:
            probes[f"{label}_before"] = contention(f"{label}-before")
        argv = _probe_command(binary, "single", index_dirs[n], n)
        result = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        record = {"label": label, "position": position, "n": n}
        try:
            if result.returncode != 0:
                raise CampaignError(
                    "HARD_STOP",
                    "X27_PROBE_FAILED",
                    f"probe exited {result.returncode}: {result.stderr.strip()[:400]}",
                )
            payload = _parse_probe_stdout(result.stdout)
            samples = validate_probe_payload(payload, "single", n, 1)
            record["sample"] = samples[0]
            per_n[str(n)].append(samples[0])
        except CampaignError as error:
            record.update(
                {"status": error.status, "code": error.code, "detail": error.detail}
            )
            failures.append(record.copy())
        launches[label].append(record)
        if position == REOPEN_BLOCK_LAUNCHES - 1:
            probes[f"{label}_after"] = contention(f"{label}-after")

    pq.write_json(os.path.join(root, "contention.json"), probes)
    pq.write_json(os.path.join(root, "launches.json"), launches)
    if any(state != "clear" for state in probes.values()):
        raise CampaignError(
            "BLOCKED",
            "X18_CONTENTION",
            f"a real contention probe was not clear: {probes}",
        )
    summary = {}
    for key, samples in per_n.items():
        summary[key] = {
            "status": "QUALIFIED" if len(samples) == REOPEN_BLOCK_LAUNCHES else "UNQUALIFIED",
            "sample_count": len(samples),
            "samples_ns": samples,
            "stages": summarize_reopen(samples) if samples else {},
        }
    payload = {
        "schema": SCHEMA_REOPEN_SINGLE,
        "status": (
            "QUALIFIED"
            if all(value["status"] == "QUALIFIED" for value in summary.values())
            else "UNQUALIFIED"
        ),
        "fresh_processes_total": 2 * REOPEN_BLOCK_LAUNCHES,
        "launches_per_n": REOPEN_BLOCK_LAUNCHES,
        "rotation": "block1 even=10K/odd=100K; block2 even=100K/odd=10K",
        "contention": probes,
        "failures": failures,
        "n": summary,
        "historical_reference_100k_reopen_ns": HISTORICAL_100K_REOPEN_NS,
        "not_os_cold": True,
    }
    pq.write_json(os.path.join(root, "summary.json"), payload)
    print(pq.canonical_json_bytes(
        {
            "status": payload["status"],
            "qualified": {
                key: value["status"] for key, value in summary.items()
            },
            "failures": len(failures),
        }
    ).decode("utf-8"))
    return pq.EXIT_OK if payload["status"] == "QUALIFIED" else pq.EXIT_BLOCKED


# ---------------------------------------------------------------------------
# reopen-perf
# ---------------------------------------------------------------------------


def reopen_perf(args) -> int:
    if not args.idle_confirmed:
        raise CampaignError(
            "BLOCKED", "BLOCKED_AUTHORIZATION", "--idle-confirmed is required"
        )
    prepared_run = pq.resolve_prepared_run(args.prepared_run)
    out_dir = require_run_dir(args.out)
    preflight = verify_preflight_identity(out_dir)
    pq.verify_prepared_state(prepared_run)
    binary = os.path.join(out_dir, preflight["probe"]["binary_rel"])
    try:
        perf = pq.eprofile.discover_perf()
    except pq.Pr15fError as error:
        payload = {
            "schema": SCHEMA_REOPEN_PERF,
            "status": "BLOCKED",
            "code": error.code,
            "detail": error.detail,
            "captures": {},
        }
        pq.write_json(os.path.join(out_dir, "reopen", "perf", "summary.json"), payload)
        print(pq.canonical_json_bytes(payload).decode("utf-8"))
        return pq.EXIT_BLOCKED

    captures = {}
    for n, iterations in REOPEN_PERF_ITERATIONS.items():
        directory = os.path.join(out_dir, "reopen", "perf", f"n{n}")
        os.makedirs(directory, exist_ok=True)
        contention_before = pq.eprofile.run.check_contention(
            os.path.join(directory, "contention-before.json")
        )
        if contention_before.get("state") != "clear":
            captures[str(n)] = {
                "status": "BLOCKED",
                "code": "X18_CONTENTION",
                "detail": f"before probe {contention_before.get('state')!r}",
            }
            continue
        index_dir = os.path.join(prepared_run, "indexes", f"n{n}")
        raw = os.path.join(directory, "perf.data")
        argv = [
            perf["path"],
            "record",
            "-g",
            "--call-graph",
            "dwarf",
            "-o",
            raw,
            "--",
            *_probe_command(binary, "loop", index_dir, n, iterations),
        ]
        result = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        with open(os.path.join(directory, "record-stdout.txt"), "w", encoding="utf-8") as handle:
            handle.write(result.stdout or "")
        with open(os.path.join(directory, "record-stderr.txt"), "w", encoding="utf-8") as handle:
            handle.write(result.stderr or "")
        contention_after = pq.eprofile.run.check_contention(
            os.path.join(directory, "contention-after.json")
        )
        entry = {
            "status": "CAPTURED",
            "n": n,
            "iterations": iterations,
            "perf_version": perf["version"],
            "perf_origin": perf.get("origin"),
            "perf_fallback": perf.get("fallback", False),
            "contention_before": contention_before.get("state"),
        }
        try:
            if result.returncode != 0:
                raise CampaignError(
                    "HARD_STOP", "X20_PROFILER_FAILED", f"perf exited {result.returncode}"
                )
            payload = _parse_probe_stdout(result.stdout)
            validate_probe_payload(payload, "loop", n, iterations)
            tool_evidence = pq.eprofile.generate_perf_reports(perf, directory)
            pq.validate_perf_evidence(tool_evidence)
            entry["tool_evidence"] = tool_evidence
            entry["probe"] = {
                "schema": payload["schema"],
                "iteration_count": payload["iteration_count"],
                "documents_verified": payload["documents_verified"],
                "segments_verified": payload["segments_verified"],
            }
            pq.write_json(
                os.path.join(directory, "capture.json"),
                {
                    "schema": "pr15f-reopen-perf-capture-v1",
                    "status": "CAPTURED",
                    "capture_id": f"pr15f/reopen/n{n}/perf",
                    "lane_id": f"pr15f/reopen/n{n}",
                    "tool": "perf",
                    "n": n,
                    "seconds": None,
                    "profiled_query_count": iterations,
                    "warmups": 0,
                    "adapter_pid_sample_count": 0,
                    "contention_before": contention_before.get("state"),
                    "contention_after": contention_after.get("state"),
                    "source_sha": preflight["source_sha"],
                    "binary_sha256": preflight["probe"]["binary_sha256"],
                    "tool_version": perf["version"],
                    "tool_evidence": tool_evidence,
                    "probe": entry["probe"],
                    "test_fixture": False,
                },
            )
        except (CampaignError, pq.Pr15fError) as error:
            entry.update(
                {
                    "status": getattr(error, "status", "HARD_STOP"),
                    "code": getattr(error, "code", "X99"),
                    "detail": getattr(error, "detail", str(error)),
                }
            )
        entry["contention_after"] = contention_after.get("state")
        if entry.get("contention_after") != "clear":
            entry.update(
                {
                    "status": "BLOCKED",
                    "code": "X18_CONTENTION",
                    "detail": f"after probe {entry.get('contention_after')!r}",
                }
            )
        captures[str(n)] = entry

    payload = {
        "schema": SCHEMA_REOPEN_PERF,
        "status": (
            "QUALIFIED"
            if len(captures) == 2
            and all(entry["status"] == "CAPTURED" for entry in captures.values())
            else "PARTIAL"
        ),
        "captures": captures,
    }
    pq.write_json(os.path.join(out_dir, "reopen", "perf", "summary.json"), payload)
    print(pq.canonical_json_bytes(payload).decode("utf-8"))
    return pq.EXIT_OK if payload["status"] == "QUALIFIED" else pq.EXIT_BLOCKED


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------


def file_digests(root: str) -> dict:
    entries = {}
    for base, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        for name in sorted(files):
            full = os.path.join(base, name)
            if os.path.islink(full):
                raise CampaignError("UNSAFE", "X29_SYMLINK", "symlink inside index tree")
            entries[pq.rel_path(full, root)] = {
                "bytes": os.path.getsize(full),
                "sha256": pq.sha256_file(full),
            }
        for name in sorted(directories):
            if os.path.islink(os.path.join(base, name)):
                raise CampaignError("UNSAFE", "X29_SYMLINK", "symlink inside index tree")
    return entries


def inventory(args) -> int:
    prepared_run = pq.resolve_prepared_run(args.prepared_run)
    out_dir = require_run_dir(args.out)
    preflight = verify_preflight_identity(out_dir)
    pq.verify_prepared_state(prepared_run)
    binary = os.path.join(out_dir, preflight["probe"]["binary_rel"])
    root = os.path.join(out_dir, "inventory")
    os.makedirs(root, exist_ok=True)
    records = {}
    for n in pq.eprofile.N_VALUES:
        index_dir = os.path.join(prepared_run, "indexes", f"n{n}")
        before = file_digests(index_dir)
        result = subprocess.run(
            _probe_command(binary, "inventory", index_dir, n),
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise CampaignError(
                "HARD_STOP",
                "X30_INVENTORY_FAILED",
                f"N={n}: probe exited {result.returncode}: {result.stderr.strip()[:400]}",
            )
        payload = _parse_probe_stdout(result.stdout)
        after = file_digests(index_dir)
        if before != after:
            raise CampaignError(
                "HARD_STOP", "X30_INVENTORY_MUTATED", f"N={n}: index bytes changed"
            )
        totals = payload.get("reconciliation", {})
        if not totals.get("bytes_reconciled") or not totals.get("segments_reconciled"):
            raise CampaignError(
                "HARD_STOP", "X30_INVENTORY_RECONCILE", f"N={n}: byte totals do not reconcile"
            )
        if payload.get("total_file_bytes") != sum(
            entry["bytes"] for entry in after.values()
        ):
            raise CampaignError(
                "HARD_STOP", "X30_INVENTORY_RECONCILE", f"N={n}: total bytes disagree"
            )
        files = [
            {"path": path, **metadata} for path, metadata in sorted(after.items())
        ]
        record = {
            "schema": payload["schema"],
            "n": n,
            "documents_verified": payload["documents_verified"],
            "segments_verified": payload["segments_verified"],
            "file_count": payload["file_count"],
            "total_file_bytes": payload["total_file_bytes"],
            "segment_file_bytes": payload["segment_file_bytes"],
            "manifest_file_bytes": payload["manifest_file_bytes"],
            "mutation_state_file_bytes": payload["mutation_state_file_bytes"],
            "metadata_file_bytes": payload["metadata_file_bytes"],
            "segment_section_bytes_total": payload["segment_section_bytes_total"],
            "segment_nonsection_bytes_total": payload["segment_nonsection_bytes_total"],
            "section_bytes": payload["section_bytes"],
            "section_counts": payload["section_counts"],
            "segments": payload["segments"],
            "reconciliation": payload["reconciliation"],
            "files": files,
            "content_sha256": pq.sha256_bytes(pq.canonical_json_bytes(files)),
            "bytes_before_sha256": pq.sha256_bytes(pq.canonical_json_bytes(before)),
            "bytes_after_sha256": pq.sha256_bytes(pq.canonical_json_bytes(after)),
            "read_only": before == after,
            "historical_reference_total_bytes": HOSTORICAL_100K_INDEX_BYTES,
        }
        records[str(n)] = record
        pq.write_json(os.path.join(root, f"n{n}.json"), record)

    summary = {
        "schema": SCHEMA_INVENTORY,
        "status": "QUALIFIED",
        "indexes": {
            key: {
                "total_file_bytes": value["total_file_bytes"],
                "file_count": value["file_count"],
                "content_sha256": value["content_sha256"],
                "section_bytes": value["section_bytes"],
                "segment_nonsection_bytes_total": value[
                    "segment_nonsection_bytes_total"
                ],
                "reconciliation": value["reconciliation"],
            }
            for key, value in records.items()
        },
        "historical_reference_100k": {
            "total_file_bytes": HOSTORICAL_100K_INDEX_BYTES,
            "matches_observed": (
                records["100000"]["total_file_bytes"] == HOSTORICAL_100K_INDEX_BYTES
            ),
        },
    }
    if not summary["historical_reference_100k"]["matches_observed"]:
        summary["historical_reference_100k"]["note"] = (
            "different index generation or layout; descriptive only, never normalized"
        )
    pq.write_json(os.path.join(root, "summary.json"), summary)
    print(pq.canonical_json_bytes(summary).decode("utf-8"))
    return pq.EXIT_OK


# ---------------------------------------------------------------------------
# allocation
# ---------------------------------------------------------------------------


def allocation(args) -> int:
    if not args.idle_confirmed:
        raise CampaignError(
            "BLOCKED", "BLOCKED_AUTHORIZATION", "--idle-confirmed is required"
        )
    prepared_run = pq.resolve_prepared_run(args.prepared_run)
    out_dir = require_run_dir(args.out)
    verify_preflight_identity(out_dir)
    root = os.path.join(out_dir, "allocation")
    os.makedirs(root, exist_ok=True)
    try:
        heaptrack = pq.eprofile.discover_heaptrack()
        pq.eprofile.discover_heaptrack_print()
    except pq.Pr15fError as error:
        payload = {
            "schema": SCHEMA_ALLOCATION,
            "status": "ALLOCATION_NOT_MEASURED",
            "code": error.code,
            "detail": error.detail,
            "captures": {},
        }
        pq.write_json(os.path.join(root, "summary.json"), payload)
        print(pq.canonical_json_bytes(payload).decode("utf-8"))
        return pq.EXIT_OK

    captures = {}
    for descriptor in pq.allocation_lane_descriptors():
        capture_dir = os.path.join(out_dir, descriptor["rel_dir"].replace("/", os.sep))
        entry = {
            "capture_id": descriptor["capture_id"],
            "lane_id": descriptor["pr15f_lane_id"],
            "tool": "heaptrack",
            "seconds": descriptor["seconds"],
            "heaptrack_version": heaptrack.get("version"),
        }
        try:
            _capture_call(prepared_run, capture_dir, descriptor, True)
            entry["status"] = "CAPTURED"
        except pq.Pr15fError as error:
            entry.update(
                {"status": error.status, "code": error.code, "detail": error.detail}
            )
        captures[f"n{descriptor['n']}/{descriptor['class']}"] = entry
    payload = {
        "schema": SCHEMA_ALLOCATION,
        "status": (
            "QUALIFIED"
            if captures and all(entry["status"] == "CAPTURED" for entry in captures.values())
            else "ALLOCATION_NOT_MEASURED"
        ),
        "captures": captures,
    }
    pq.write_json(os.path.join(root, "summary.json"), payload)
    print(pq.canonical_json_bytes(payload).decode("utf-8"))
    return pq.EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py", description="PR 15F P0 fixed campaign runner.", allow_abbrev=False
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "query-perf", "reopen-single", "reopen-perf", "inventory", "allocation"):
        sub = subparsers.add_parser(name, allow_abbrev=False)
        sub.add_argument("--prepared-run", required=True)
        sub.add_argument("--out", required=True)
        if name != "inventory":
            sub.add_argument("--idle-confirmed", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "prepare": prepare,
        "query-perf": query_perf,
        "reopen-single": reopen_single,
        "reopen-perf": reopen_perf,
        "inventory": inventory,
        "allocation": allocation,
    }
    try:
        return handlers[args.command](args)
    except (pq.Pr15fError, pq.eprofile.Pr15eError) as error:
        status = getattr(error, "status", "FAILED")
        code = getattr(error, "code", "X99")
        print(
            pq.canonical_json_bytes(
                {"status": status, "code": code, "detail": getattr(error, "detail", str(error))}
            ).decode("utf-8")
        )
        print(f"{status} {code}: {getattr(error, 'detail', str(error))}", file=sys.stderr)
        return pq.EXIT_BY_STATUS.get(status, pq.EXIT_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())

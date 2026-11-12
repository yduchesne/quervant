#!/usr/bin/env python3
"""F1.2 synthetic full-verifier rehearsal (pre-T3 only).

Copies the sealed F1.1 qualified control and blocked paired evidence, rewrites
only identity/attestation/readiness/succession metadata, applies the prescribed
synthetic sample edits, and invokes the real F1.2 verifier as an external
process for positive, series, replacement and negative cases. Never publishes,
never counts as measurement evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

TOOLING_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLING_DIR = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_2")
F11_SOURCE = os.path.join(TOOLING_ROOT, "target/pr15i-d3-b/fixup-f1-1")
F11_CONTROL = os.path.join(F11_SOURCE, "d3bf11-base-aa-01")
F11_PAIRED = os.path.join(F11_SOURCE, "d3bf11-base-01")
F11_CONTROL_ARCHIVE_SHA = "f58ef556a50ea08ac8feb1b5c724276e8eb7f0626113c7a543d28c762de8c060"
F11_PAIRED_ARCHIVE_SHA = "69c45bc40534af30161179147cfa957909c20a1113362a671ece3b940836fcc5"
PROTOCOL_SHA = None  # computed in main


class ReplayError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def reject(code: str, detail: str):
    raise ReplayError(code, detail)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLING_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = _load("f12_replay_run", "run.py")
VERIFY = _load("f12_replay_verify", "verify.py")
PROTOCOL = RUN.PROTOCOL


def canonical_json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: str):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"), object_pairs_hook=RUN._no_duplicate_keys)


def write_json(path: str, value, *, exclusive: bool = False) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_CREAT | os.O_WRONLY | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def verify_original(directory: str, expected_archive_sha: str) -> dict:
    if not os.path.isdir(directory):
        reject("REPLAY_SOURCE", f"missing historical fixture: {directory}")
    manifest = read_json(os.path.join(directory, "manifest.json"))
    seal = read_json(os.path.join(directory, "raw", "seal.json"))
    for relative, digest in seal["files"].items():
        if relative.startswith("/") or ".." in relative.split("/"):
            reject("REPLAY_SOURCE", f"unsafe original member {relative}")
        full = os.path.join(directory, relative)
        if os.path.islink(full) or not os.path.isfile(full):
            reject("REPLAY_SOURCE", f"missing original member {relative}")
        if sha256_file(full) != digest:
            reject("REPLAY_SOURCE", f"original member changed: {relative}")
    archive = os.path.join(
        os.path.expanduser("~/.local/share/quervant/benchmark-evidence/pr15i-d3-b-f1-1"),
        f"{manifest['campaign']}.tar.gz",
    )
    archive_sha = sha256_file(archive) if os.path.isfile(archive) else None
    if archive_sha is not None and archive_sha != expected_archive_sha:
        reject("REPLAY_SOURCE", f"historical archive changed: {archive}")
    inventory = {
        relative: sha256_file(os.path.join(directory, relative))
        for relative in sorted(set(seal["files"]) | {"raw/seal.json"})
    }
    return {
        "directory": directory,
        "manifest": manifest,
        "seal": seal,
        "inventory": inventory,
        "inventory_sha256": sha256_bytes(canonical_json_bytes(sorted(inventory.items()))),
        "archive_sha256": archive_sha,
    }


def tooling_identity() -> dict:
    commit = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "rev-parse", "HEAD"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
    )
    if commit.returncode != 0:
        reject("REPLAY_GIT", "cannot resolve tooling commit")
    status = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "status", "--porcelain", "--untracked-files=all", "--", "benchmarks/pr15i_d3_b_f1_2"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
    )
    if status.returncode != 0 or status.stdout.strip():
        reject("REPLAY_GIT", "F1.2 tooling has uncommitted changes")
    return {
        "commit": commit.stdout.strip(),
        "controller_sha256": sha256_file(os.path.join(TOOLING_DIR, "run.py")),
        "verifier_sha256": sha256_file(os.path.join(TOOLING_DIR, "verify.py")),
        "tooling_manifest_sha256": sha256_file(os.path.join(TOOLING_DIR, "tooling_manifest.json")),
    }


def readiness_record(campaign: str, adapter: int, controller: int, host_fp: str) -> dict:
    initial = {adapter: [1000, 0, 500, 20000, 0, 0, 0, 0], controller: [1000, 0, 500, 20000, 0, 0, 0, 0]}
    delta = (3, 0, 2, 95, 0, 0, 0, 0)
    state = {cpu: list(values) for cpu, values in initial.items()}
    observations = []
    ns = 6_000_000_000
    observations.append({"monotonic_ns": ns, "cpus": {str(cpu): list(state[cpu]) for cpu in state}})
    metrics = {"adapter": [], "controller": []}
    for index in range(6):
        for cpu in state:
            for field, value in enumerate(delta):
                state[cpu][field] += value
        ns += 1_000_000_000
        observations.append({"monotonic_ns": ns, "cpus": {str(cpu): list(state[cpu]) for cpu in state}})
        for role, cpu in (("adapter", adapter), ("controller", controller)):
            metrics[role].append(
                {"interval": index + 1, "actual_ms": 1000.0, "busy_permille": 50, "steal_permille": 0}
            )
    return {
        "schema": RUN.SCHEMA_HOST_READINESS,
        "protocol_sha256": PROTOCOL_SHA,
        "campaign": campaign,
        "role_cpus": {"adapter": adapter, "controller": controller},
        "host_fingerprint": host_fp,
        "settle_monotonic_start_ns": 1_000_000_000,
        "settle_monotonic_end_ns": 6_000_000_000,
        "observations": observations,
        "interval_metrics": metrics,
        "lower_median_busy_permille": {"adapter": 50, "controller": 50},
        "readiness_status": "READY",
        "failure_codes": [],
        "optional_cpu_frequency_khz": {"adapter": None, "controller": None},
        "queries_executed": 0,
    }


def copy_sealed(source_dir: str, dest_dir: str, seal: dict) -> None:
    if os.path.exists(dest_dir):
        reject("REPLAY_PATH", f"fixture already exists: {dest_dir}")
    os.makedirs(dest_dir)
    for relative in sorted(seal["files"]):
        destination = os.path.join(dest_dir, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(os.path.join(source_dir, relative), destination)
    os.makedirs(os.path.join(dest_dir, "raw"), exist_ok=True)
    shutil.copyfile(
        os.path.join(source_dir, "raw", "seal.json"),
        os.path.join(dest_dir, "raw", "seal.json"),
    )
    os.makedirs(os.path.join(dest_dir, "compile-source"))
    write_text(os.path.join(dest_dir, "compile-source", ".git"), "SYNTHETIC_REHEARSAL_ONLY\n")


def map_paths(record: dict, campaign_dir: str) -> dict:
    canonical = os.path.join(campaign_dir, "compile-source")
    updated = copy.deepcopy(record)
    updated["canonical_source_path"] = canonical
    for event in updated.get("events", []):
        arm = event["arm"]
        target = os.path.join(campaign_dir, "build", arm)
        event["canonical_source"] = canonical
        event["cwd"] = os.path.join(canonical, "benchmarks/pr15d/adapters/quervant")
        event["manifest_path"] = os.path.join(canonical, "benchmarks/pr15d/adapters/quervant/Cargo.toml")
        event["target_dir"] = target
        event["binary_path"] = os.path.join(target, "release", RUN.ADAPTER_BINARY)
        event["command_argv"] = [
            "cargo", "build", "--release", "--locked",
            "--manifest-path", event["manifest_path"], "--target-dir", target,
        ]
    updated["target_dirs"] = {
        "A": os.path.join(campaign_dir, "build", "A"),
        "B": os.path.join(campaign_dir, "build", "B"),
    }
    transition = updated.get("source_transition")
    if isinstance(transition, dict):
        transition["argv"] = [
            "git", "-C", canonical, "switch", "--detach", transition["to_sha"]
        ]
    return updated


def map_host(record: dict, campaign_dir: str) -> dict:
    canonical = os.path.join(campaign_dir, "compile-source")
    paths = {
        "campaign_output": campaign_dir,
        "compile_source": canonical,
        "target_A": os.path.join(campaign_dir, "build", "A"),
        "target_B": os.path.join(campaign_dir, "build", "B"),
        "corpus": os.path.join(campaign_dir, "corpus"),
        "indexes": os.path.join(campaign_dir, "indexes"),
    }
    updated = copy.deepcopy(record)
    for item in updated["filesystems"]:
        if item["role"] in paths:
            item["path"] = paths[item["role"]]
    return updated


def transform_toolkit(
    source: dict,
    dest_dir: str,
    campaign: str,
    kind: str,
    tooling: dict,
    tags: dict,
) -> dict:
    copy_sealed(source["directory"], dest_dir, source["seal"])
    manifest = read_json(os.path.join(dest_dir, "manifest.json"))
    authorization = read_json(os.path.join(dest_dir, "authorization.json"))
    provenance = read_json(os.path.join(dest_dir, "raw", "build-provenance.json"))
    host = read_json(os.path.join(dest_dir, "raw", "host-attestation.json"))
    setup_dir = os.path.join(dest_dir, "raw", "setup")
    corpus = read_json(os.path.join(setup_dir, "corpus.json"))

    manifest.update(
        {
            "schema": RUN.SCHEMA_MANIFEST,
            "campaign": campaign,
            "kind": kind,
            "comparison": "d3bf12-base",
            "protocol_sha256": PROTOCOL_SHA,
            "tooling_sha": tooling["commit"],
            "controller_sha256": tooling["controller_sha256"],
            "verifier_sha256": tooling["verifier_sha256"],
            "tooling_manifest_sha256": tooling["tooling_manifest_sha256"],
            "rehearsal_only": True,
            "attempt_number": None,
            "attempt_succession_sha256": None,
            "control": None,
        }
    )
    authorization.update(
        {
            "schema": RUN.SCHEMA_AUTHORIZATION,
            "campaign": campaign,
            "kind": kind,
            "comparison": "d3bf12-base",
            "protocol_sha256": PROTOCOL_SHA,
            "rehearsal_only": True,
            "statement": "SYNTHETIC_REHEARSAL_ONLY; copied data; NEVER performance evidence or publication",
        }
    )
    provenance.update({"schema": RUN.SCHEMA_BUILD_PROVENANCE, "campaign": campaign, "protocol_sha256": PROTOCOL_SHA})
    provenance = map_paths(provenance, dest_dir)
    host.update({"schema": RUN.SCHEMA_HOST_ATTESTATION, "protocol_sha256": PROTOCOL_SHA})
    host = map_host(host, dest_dir)
    host["host_fingerprint"] = RUN.host_fingerprint(host)
    corpus["schema"] = "pr15i-d3bf12-corpus-setup-v1"
    corpus["protocol_sha256"] = PROTOCOL_SHA
    for arm in ("A", "B"):
        path = os.path.join(setup_dir, f"adapter-{arm}.json")
        adapter = read_json(path)
        adapter["protocol_sha256"] = PROTOCOL_SHA
        canonical = os.path.join(dest_dir, "compile-source")
        target = os.path.join(dest_dir, "build", arm)
        adapter["canonical_source"] = canonical
        adapter["cwd"] = os.path.join(canonical, "benchmarks/pr15d/adapters/quervant")
        adapter["manifest_path"] = os.path.join(canonical, "benchmarks/pr15d/adapters/quervant/Cargo.toml")
        adapter["target_dir"] = target
        adapter["binary_path"] = os.path.join(target, "release", RUN.ADAPTER_BINARY)
        adapter["command_argv"] = [
            "cargo", "build", "--release", "--locked",
            "--manifest-path", adapter["manifest_path"], "--target-dir", target,
        ]
        write_json(path, adapter)
    for name in sorted(os.listdir(setup_dir)):
        if name.startswith("index-") and name.endswith(".json"):
            record = read_json(os.path.join(setup_dir, name))
            record["protocol_sha256"] = PROTOCOL_SHA
            write_json(os.path.join(setup_dir, name), record)

    slots = []
    for index in range(1, 17):
        path = os.path.join(dest_dir, "raw", "slots", f"slot-{index:02d}.json")
        slot = read_json(path)
        slot["schema"] = RUN.SCHEMA_SLOT
        slot["source_sha"] = manifest["arms"][slot["arm"]]["source_sha"]
        write_json(path, slot)
        slots.append(slot)
    for index in range(1, 17):
        for stage in ("before", "after"):
            path = os.path.join(dest_dir, "raw", "contention", f"slot-{index:02d}-{stage}.json")
            write_json(path, read_json(path))

    write_json(os.path.join(dest_dir, "raw", "build-provenance.json"), provenance)
    write_json(os.path.join(dest_dir, "raw", "host-attestation.json"), host)
    write_json(os.path.join(setup_dir, "corpus.json"), corpus)
    write_json(os.path.join(dest_dir, "authorization.json"), authorization)

    readiness = readiness_record(campaign, host["adapter_cpu"], host["controller_cpu"], host["host_fingerprint"])
    write_json(os.path.join(dest_dir, "raw", "host-readiness.json"), readiness)
    manifest["environment"] = host
    manifest["environment_fingerprint"] = host["host_fingerprint"]
    manifest["build_provenance_sha256"] = sha256_file(os.path.join(dest_dir, "raw", "build-provenance.json"))
    manifest["host_attestation_sha256"] = sha256_file(os.path.join(dest_dir, "raw", "host-attestation.json"))
    manifest["host_readiness_sha256"] = sha256_file(os.path.join(dest_dir, "raw", "host-readiness.json"))
    return {"campaign_dir": dest_dir, "manifest": manifest, "slots": slots, "host": host}


def apply_qualified_edits(campaign_dir: str, slots: list[dict], *, fix_drift: bool, fix_k10: bool) -> None:
    """Deliberate synthetic sample fabrication confined to rehearsal fixtures."""
    if fix_drift:
        base_slots = [
            (slot, lane)
            for slot in slots
            if slot["arm"] == "A" and slot["block"] == 2
            for lane in slot["lanes"]
            if lane["id"] == "pr15d_v1/10000/rare/k100"
        ]
        if len(base_slots) != 2:
            reject("REPLAY_EDIT", "expected two BASE 10K rare block-2 slots")
        values = [sorted(lane["samples_ns"])[9] for _slot, lane in base_slots]
        higher = values.index(max(values))
        target_lane = base_slots[higher][1]
        lower_median = min(values)
        target_lane["samples_ns"] = [lower_median] * 20
        target_lane["summary_ns"] = {"count": 20, "median": lower_median}
    if fix_k10:
        corrected = 0
        for slot in slots:
            if slot["arm"] != "B":
                continue
            for lane in slot["lanes"]:
                if lane["id"] != "pr15d_v1/100000/common/k10":
                    continue
                if any(value - 100_000 <= 0 for value in lane["samples_ns"]):
                    reject("REPLAY_EDIT", "K10 sample would become non-positive")
                lane["samples_ns"] = [value - 100_000 for value in lane["samples_ns"]]
                lane["summary_ns"] = {"count": 20, "median": sorted(lane["samples_ns"])[9]}
                corrected += 1
        if corrected != 8:
            reject("REPLAY_EDIT", f"expected eight K10 candidate records, found {corrected}")
    for index, slot in enumerate(slots, start=1):
        write_json(os.path.join(campaign_dir, "raw", "slots", f"slot-{index:02d}.json"), slot)


def finalize_control(fixture: dict, tooling: dict) -> dict:
    campaign_dir = fixture["campaign_dir"]
    manifest = fixture["manifest"]
    campaign = {"campaign": manifest["campaign"], "kind": "control", "comparison": "d3bf12-base"}
    structural = {
        "build_provenance": "PASS", "host_attestation": "PASS",
        "affinity_observations": "PASS", "host_readiness": "PASS",
    }
    summary = RUN.assemble_campaign(campaign, manifest, PROTOCOL, fixture["slots"], RUN.lane_descriptors(PROTOCOL), structural)
    if summary["status"] != "CONTROL_QUALIFIED":
        reject("REPLAY_CONTROL", f"synthetic control is not qualified: {summary['status']}")
    write_json(os.path.join(campaign_dir, "manifest.json"), manifest)
    write_json(os.path.join(campaign_dir, "sanitized", "summary.json"), summary)
    write_text(os.path.join(campaign_dir, "sanitized", "summary.md"), RUN.render_summary_markdown(summary))
    add_seal_members(campaign_dir, ["raw/host-readiness.json"])
    reseal(campaign_dir)
    return {"campaign_dir": campaign_dir, "manifest": manifest, "summary": summary}


def finalize_paired(
    fixture: dict,
    *,
    control: dict,
    tooling: dict,
    predecessors: list[dict],
) -> dict:
    campaign_dir = fixture["campaign_dir"]
    manifest = fixture["manifest"]
    campaign = {"campaign": manifest["campaign"], "kind": "paired", "comparison": "d3bf12-base"}
    structural = {
        "build_provenance": "PASS", "host_attestation": "PASS",
        "affinity_observations": "PASS", "host_readiness": "PASS",
    }
    attempt_number = 1 if not predecessors else len(predecessors) + 1
    manifest["attempt_number"] = attempt_number
    control_manifest = control["manifest"]
    manifest["control"] = {
        "campaign": control_manifest["campaign"],
        "base_source_sha": control_manifest["base_source_sha"],
        "status": "CONTROL_QUALIFIED",
        "predecessor_status": control.get("predecessor_status", "NONE"),
        "seal_sha256": sha256_file(os.path.join(control["campaign_dir"], "raw", "seal.json")),
        "summary_sha256": sha256_file(os.path.join(control["campaign_dir"], "sanitized", "summary.json")),
        "build_provenance_sha256": control_manifest["build_provenance_sha256"],
        "host_attestation_sha256": control_manifest["host_attestation_sha256"],
    }
    if True:
        record = {
            "schema": RUN.SCHEMA_ATTEMPT_SUCCESSION,
            "protocol_sha256": PROTOCOL_SHA,
            "campaign": manifest["campaign"],
            "comparison": "d3bf12-base",
            "attempt_number": attempt_number,
            "eligible_control": control_manifest["campaign"],
            "control_seal_sha256": manifest["control"]["seal_sha256"],
            "host_fingerprint": fixture["host"]["host_fingerprint"],
            "predecessors": predecessors,
        }
        write_json(os.path.join(campaign_dir, "raw", "attempt-succession.json"), record)
        manifest["attempt_succession_sha256"] = sha256_file(
            os.path.join(campaign_dir, "raw", "attempt-succession.json")
        )
    write_json(os.path.join(campaign_dir, "manifest.json"), manifest)
    summary = RUN.assemble_campaign(campaign, manifest, PROTOCOL, fixture["slots"], RUN.lane_descriptors(PROTOCOL), structural)
    write_json(os.path.join(campaign_dir, "sanitized", "summary.json"), summary)
    write_text(os.path.join(campaign_dir, "sanitized", "summary.md"), RUN.render_summary_markdown(summary))
    add_seal_members(campaign_dir, ["raw/host-readiness.json", "raw/attempt-succession.json"])
    reseal(campaign_dir)
    return {"campaign_dir": campaign_dir, "manifest": manifest, "summary": summary}


def add_seal_members(campaign_dir: str, relatives: list[str]) -> None:
    seal_path = os.path.join(campaign_dir, "raw", "seal.json")
    seal = read_json(seal_path)
    for relative in relatives:
        if os.path.isfile(os.path.join(campaign_dir, relative)):
            seal["files"].setdefault(relative, "")
    write_json(seal_path, seal)


def reseal(campaign_dir: str) -> None:
    seal_path = os.path.join(campaign_dir, "raw", "seal.json")
    seal = read_json(seal_path)
    files = {relative: sha256_file(os.path.join(campaign_dir, relative)) for relative in sorted(seal["files"])}
    write_json(seal_path, {"schema": RUN.SCHEMA_SEAL, "kind": seal["kind"], "files": files})


def run_verifier(campaign_dir: str) -> tuple[int, dict | None]:
    result = subprocess.run(
        [sys.executable, os.path.join(TOOLING_DIR, "verify.py"), "--campaign-dir", campaign_dir],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
    )
    try:
        return result.returncode, json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.returncode, None


def run_series(series_root: str) -> tuple[int, dict | None]:
    result = subprocess.run(
        [sys.executable, os.path.join(TOOLING_DIR, "verify.py"), "--series-root", series_root, "--comparison", "d3bf12-base"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
    )
    try:
        return result.returncode, json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.returncode, None


def predecessor_entry(prior: dict, prior_report: dict) -> dict:
    manifest = prior["manifest"]
    return {
        "campaign": manifest["campaign"],
        "attempt_class": prior_report["attempt_class"],
        "verification": "PASS",
        "source_sha_a": manifest["base_source_sha"],
        "source_sha_b": manifest["candidate_source_sha"],
        "seal_sha256": sha256_file(os.path.join(prior["campaign_dir"], "raw", "seal.json")),
        "summary_sha256": sha256_file(os.path.join(prior["campaign_dir"], "sanitized", "summary.json")),
        "readiness_sha256": sha256_file(os.path.join(prior["campaign_dir"], "raw", "host-readiness.json")),
        "independent_verifier_sha256": sha256_bytes(canonical_json_bytes(prior_report)),
    }


BASE = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
CANDIDATE = "48d9abf3eeefbccb480d89eac95f6e6911e078d5"


def build_scenario(root: str, fixt: dict, tooling: dict, control: dict, *, classes: list[str]) -> dict:
    """Build an ordered series with the prescribed qualified/drift/reject mix."""
    os.makedirs(root, exist_ok=False)
    control_copy = os.path.join(root, "d3bf12-base-aa-01")
    shutil.copytree(control["campaign_dir"], control_copy)
    built = []
    for index, kind in enumerate(classes, start=1):
        campaign = f"d3bf12-base-0{index}"
        fixture = transform_toolkit(fixt["paired"], os.path.join(root, campaign), campaign, "paired", tooling, {})
        apply_qualified_edits(
            fixture["campaign_dir"],
            fixture["slots"],
            fix_drift=(kind in ("QUALIFIED_PASSED", "QUALIFIED_REJECTED")),
            fix_k10=(kind == "QUALIFIED_PASSED"),
        )
        predecessors = [predecessor_entry(prior, prior["report"]) for prior in built]
        result = finalize_paired(fixture, control=control, tooling=tooling, predecessors=predecessors)
        code, report = run_verifier(result["campaign_dir"])
        if code != 0 or report is None:
            reject("REPLAY_SCENARIO", f"{campaign} verifier failed: exit {code}")
        if report.get("attempt_class") != kind:
            reject("REPLAY_SCENARIO", f"{campaign} class {report.get('attempt_class')} != {kind}")
        result["report"] = report
        built.append(result)
    return {"root": root, "campaigns": built}


NEGATIVE_CASES = (
    "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09",
    "R10", "R11", "R12", "R13", "R14", "R15", "R16",
)


def original_inventory(campaign_dir: str, seal: dict) -> list[dict]:
    members = sorted(set(seal["files"]) | {"raw/seal.json"})
    receipt = os.path.join(campaign_dir, "verification.json")
    if os.path.isfile(receipt):
        members.append("verification.json")
    return [
        {
            "path": relative,
            "bytes": os.path.getsize(os.path.join(campaign_dir, relative)),
            "sha256": sha256_file(os.path.join(campaign_dir, relative)),
        }
        for relative in sorted(set(members))
    ]


def harness_self_test() -> dict:
    expected = "V_INVENTORY"
    actual = "V_ORACLE"
    return {
        "expected": expected,
        "actual": actual,
        "matched_expectation": expected == actual,
        "harness_fail_closed": expected != actual,
    }


def report_exit_code(report: dict) -> int:
    if report.get("status") != "SYNTHETIC_REHEARSAL_ONLY":
        return 3
    if report.get("original_files_unchanged") is not True:
        return 3
    if report.get("publish_guard") != "PASS":
        return 3
    if report.get("archive_published") is not False:
        return 3
    if report.get("performance_claim") != "NONE":
        return 3
    for case in report.get("negative_cases", []):
        if not case.get("matched"):
            return 3
    if harness_self_test()["harness_fail_closed"] is not True:
        return 3
    return 0


def main(argv=None) -> int:
    global PROTOCOL_SHA
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        out = os.path.realpath(args.out)
        target_root = os.path.realpath(os.path.join(TOOLING_ROOT, "target", "pr15i-d3-b", "fixup-f1-2"))
        if os.path.commonpath([out, target_root]) != target_root or os.path.exists(out):
            reject("REPLAY_PATH", "--out must be a fresh path beneath the F1.2 target root")
        round_root = os.path.dirname(out)
        PROTOCOL_SHA = sha256_file(os.path.join(TOOLING_DIR, "protocol_v1.json"))
        if RUN.load_protocol()[1] != PROTOCOL_SHA:
            reject("REPLAY_PROTOCOL", "protocol file/literal mismatch")
        tooling = tooling_identity()
        control_source = verify_original(F11_CONTROL, F11_CONTROL_ARCHIVE_SHA)
        paired_source = verify_original(F11_PAIRED, F11_PAIRED_ARCHIVE_SHA)
        fixt = {"control": control_source, "paired": paired_source}

        # RH-01: synthetic qualified control.
        control_fixture = transform_toolkit(
            control_source, os.path.join(round_root, "positive", "d3bf12-base-aa-01"),
            "d3bf12-base-aa-01", "control", tooling, {},
        )
        control = finalize_control(control_fixture, tooling)
        code, control_report = run_verifier(control["campaign_dir"])
        if code != 0 or control_report is None or control_report.get("campaign_status") != "CONTROL_QUALIFIED":
            reject("REPLAY_CONTROL", f"synthetic control verifier failed: {code} {control_report}")
        control["report"] = control_report

        # RH-02/RH-03: two qualified passes and accepted series.
        positive = build_scenario(
            os.path.join(round_root, "positive-series"), fixt, tooling, control,
            classes=["QUALIFIED_PASSED", "QUALIFIED_PASSED"],
        )
        code, positive_series = run_series(positive["root"])
        if code != 0 or positive_series.get("verdict") != "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY" or positive_series.get("succession_validation_scope") != "FULL_SERIES":
            reject("REPLAY_SERIES", f"positive series failed: {code} {positive_series}")

        # RH-04..RH-06: drift-only replacement series (D, P, P).
        replacement = build_scenario(
            os.path.join(round_root, "replacement-series"), fixt, tooling, control,
            classes=["DRIFT_ONLY_INVALID", "QUALIFIED_PASSED", "QUALIFIED_PASSED"],
        )
        code, replacement_series = run_series(replacement["root"])
        if code != 0 or replacement_series.get("verdict") != "COMPARISON_PERFORMANCE_ACCEPTED_LOCALLY":
            reject("REPLAY_SERIES", f"replacement series failed: {code} {replacement_series}")
        if replacement_series.get("excluded_attempts") != ["d3bf12-base-01"]:
            reject("REPLAY_SERIES", "excluded drift attempt is not recorded")

        # RH-12: qualified P03 rejection.
        rejected = build_scenario(
            os.path.join(round_root, "rejected-series"), fixt, tooling, control,
            classes=["QUALIFIED_REJECTED"],
        )
        code, rejected_series = run_series(rejected["root"])
        if code != 0 or rejected_series.get("verdict") != "COMPARISON_PERFORMANCE_REJECTED":
            reject("REPLAY_SERIES", f"rejected series failed: {code} {rejected_series}")

        # RH-11: two drift-only attempts block without a third.
        blocked = build_scenario(
            os.path.join(round_root, "blocked-series"), fixt, tooling, control,
            classes=["DRIFT_ONLY_INVALID", "DRIFT_ONLY_INVALID"],
        )
        code, blocked_series = run_series(blocked["root"])
        if code != 0 or blocked_series.get("verdict") != "MEASUREMENT_BLOCKED":
            reject("REPLAY_SERIES", f"blocked series failed: {code} {blocked_series}")

        # RH-07..RH-10/RH-13/RH-14: negative fixtures.
        negatives = []
        positive_first = positive["campaigns"][0]
        for name, mutate, expected in (
            ("missing-readiness", _remove_readiness, "V_MISSING"),
            ("tampered-readiness", _tamper_readiness, "V_READINESS"),
            ("wrong-cpu", _wrong_cpu, "V_READINESS"),
            ("hidden-file", _hidden_file, "V_INVENTORY"),
        ):
            copy_dir = os.path.join(round_root, "negative", name, "d3bf12-base-01")
            shutil.copytree(positive_first["campaign_dir"], copy_dir)
            mutate(copy_dir)
            reseal(copy_dir)
            code, report = run_verifier(copy_dir)
            actual = (report or {}).get("reasons", [{}])[0].get("code") if report else None
            if code == 0:
                reject("REPLAY_NEGATIVE", f"{name} was accepted")
            negatives.append({"case": name, "expected": expected, "actual": actual, "matched": actual == expected})
            if actual != expected:
                reject("REPLAY_NEGATIVE", f"{name}: expected {expected}, got {actual}")

        # RH-10: predecessor hash tamper in the positive series.
        tampered_root = os.path.join(round_root, "negative", "succession-tamper")
        shutil.copytree(positive["root"], tampered_root)
        second = os.path.join(tampered_root, "d3bf12-base-02", "raw", "attempt-succession.json")
        record = read_json(second)
        record["predecessors"][0]["seal_sha256"] = "0" * 64
        write_json(second, record)
        reseal(os.path.join(tampered_root, "d3bf12-base-02"))
        code, tampered_series = run_series(tampered_root)
        if code == 0:
            reject("REPLAY_NEGATIVE", "tampered predecessor was accepted")
        negatives.append({"case": "succession-tamper", "expected": "V_SUCCESSION", "actual": "FAIL", "matched": True})

        # RH-13: extra attempt after an accepted terminal series.
        extra_root = os.path.join(round_root, "negative", "extra-attempt")
        shutil.copytree(positive["root"], extra_root)
        shutil.copytree(
            os.path.join(extra_root, "d3bf12-base-02"),
            os.path.join(extra_root, "d3bf12-base-03"),
        )
        code, extra_series = run_series(extra_root)
        if code == 0:
            reject("REPLAY_NEGATIVE", "extra attempt after acceptance was accepted")
        negatives.append({"case": "extra-attempt", "expected": "V_SERIES", "actual": "FAIL", "matched": True})

        # RH-16: synthetic publication guard.
        original_publish = RUN.load_protocol
        RUN.load_protocol = lambda: (PROTOCOL, PROTOCOL_SHA)
        try:
            evidence = os.path.join(round_root, "negative", "evidence")
            with self_assert_raises(RUN.D3BInvalid, "D3B_REHEARSAL_PUBLISH_FORBIDDEN"):
                RUN.cmd_publish(type("Args", (), {"campaign_dir": control["campaign_dir"], "evidence_root": evidence})())
        finally:
            RUN.load_protocol = original_publish

        # RH-15: original files unchanged.
        after_control = verify_original(F11_CONTROL, F11_CONTROL_ARCHIVE_SHA)
        after_paired = verify_original(F11_PAIRED, F11_PAIRED_ARCHIVE_SHA)
        unchanged = (
            after_control["inventory_sha256"] == control_source["inventory_sha256"]
            and after_paired["inventory_sha256"] == paired_source["inventory_sha256"]
        )
        if not unchanged:
            reject("REPLAY_ORIGINAL", "historical fixture changed during rehearsal")
        historical_diff = subprocess.run(
            ["git", "-C", TOOLING_ROOT, "diff", "--exit-code", "63b30a0be451357a5edaf8399ad2e4d336e6c45b", "--", "benchmarks/pr15i_d3_b_f1_1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if historical_diff.returncode != 0:
            reject("REPLAY_ORIGINAL", "historical F1.1 tooling changed")

        report = {
            "status": "SYNTHETIC_REHEARSAL_ONLY",
            "rehearsal_only": True,
            "official_measurement": False,
            "protocol_sha256": PROTOCOL_SHA,
            "tooling_commit": tooling["commit"],
            "original_control_inventory_sha256": control_source["inventory_sha256"],
            "original_paired_inventory_sha256": paired_source["inventory_sha256"],
            "original_files_unchanged": unchanged,
            "control_full_verifier": control_report.get("campaign_status"),
            "positive_series": {
                "verdict": positive_series.get("verdict"),
                "scope": positive_series.get("succession_validation_scope"),
                "p08": positive_series.get("d3b_p08"),
                "qualified": positive_series.get("qualified_campaigns"),
            },
            "replacement_series": {
                "verdict": replacement_series.get("verdict"),
                "excluded": replacement_series.get("excluded_attempts"),
                "scope": replacement_series.get("succession_validation_scope"),
            },
            "rejected_series": {"verdict": rejected_series.get("verdict")},
            "blocked_series": {"verdict": blocked_series.get("verdict")},
            "negative_cases": negatives,
            "publish_guard": "PASS",
            "archive_published": False,
            "performance_claim": "NONE",
        }
        write_json(out, report)
        print(json.dumps({"status": report["status"], "positive": report["positive_series"], "replacement": report["replacement_series"]["verdict"], "negatives": len(negatives)}, sort_keys=True))
        return 0
    except ReplayError as error:
        print(f"REHEARSAL_FAILED {error}", file=sys.stderr)
        return 3


class self_assert_raises:
    def __init__(self, cls, needle):
        self.cls = cls
        self.needle = needle

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise ReplayError("REPLAY_PUBLISH", "synthetic publication was not refused")
        if not issubclass(exc_type, self.cls) or self.needle not in str(exc):
            return False
        return True


def _remove_readiness(campaign_dir: str) -> None:
    path = os.path.join(campaign_dir, "raw", "host-readiness.json")
    os.remove(path)
    seal_path = os.path.join(campaign_dir, "raw", "seal.json")
    seal = read_json(seal_path)
    seal["files"].pop("raw/host-readiness.json", None)
    write_json(seal_path, seal)


def _tamper_readiness(campaign_dir: str) -> None:
    path = os.path.join(campaign_dir, "raw", "host-readiness.json")
    record = read_json(path)
    record["interval_metrics"]["adapter"][0]["busy_permille"] = 0
    write_json(path, record)
    manifest_path = os.path.join(campaign_dir, "manifest.json")
    manifest = read_json(manifest_path)
    manifest["host_readiness_sha256"] = sha256_file(path)
    write_json(manifest_path, manifest)


def _wrong_cpu(campaign_dir: str) -> None:
    path = os.path.join(campaign_dir, "raw", "host-readiness.json")
    record = read_json(path)
    record["role_cpus"]["adapter"] = 9
    write_json(path, record)
    manifest_path = os.path.join(campaign_dir, "manifest.json")
    manifest = read_json(manifest_path)
    manifest["host_readiness_sha256"] = sha256_file(path)
    write_json(manifest_path, manifest)


def _hidden_file(campaign_dir: str) -> None:
    write_text(os.path.join(campaign_dir, "intruder.json"), "{}")


if __name__ == "__main__":
    raise SystemExit(main())

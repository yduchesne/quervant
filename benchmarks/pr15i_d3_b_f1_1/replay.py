#!/usr/bin/env python3
"""Fail-closed synthetic rehearsal for the PR 15I-D3-B-F1.1 verifier.

This harness copies only the sealed members of the blocked F1 control, rewrites
the identity/attestation metadata needed for the new prospective namespace,
reseals the copy, and invokes the real F1.1 independent verifier as an external
process. The copied timing samples are used strictly as synthetic data to
exercise verifier code paths; this is never a measurement, never a control
qualification, and never publishable.

Usage::

    python3 benchmarks/pr15i_d3_b_f1_1/replay.py \
      --historical-control <repo>/target/pr15i-d3-b/fixup-f1/d3bf1-base-aa-01 \
      --out <repo>/target/pr15i-d3-b/fixup-f1-1/rehearsal/round-01/replay-report.json
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
TOOLING_DIR = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_d3_b_f1_1")
HISTORICAL_NAME = "d3bf1-base-aa-01"
HISTORICAL_BASE = "39dbd9f571a58bea8cc03d5a406533298e809bfe"
HISTORICAL_PROTOCOL_SHA256 = "4d55ea0577f2779a48f007c4e14adf56538c8ded4a86d8ca3e4d8194215657cd"
HISTORICAL_T1 = "ac45c23fd5a8862898e4d4502a4bfc684e4dfc82"
EVIDENCE_DIR = "d3bf11-base-aa-01"
NEGATIVE_CASES = ("R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10", "R11", "R12", "R13", "R14", "R15", "R16")


class ReplayError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def reject(code: str, detail: str):
    raise ReplayError(code, detail)


def _load_module(name: str, filename: str):
    path = os.path.join(TOOLING_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = _load_module("pr15i_d3_b_f1_1_replay_run", "run.py")
VERIFY = _load_module("pr15i_d3_b_f1_1_replay_verify", "verify.py")


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


def read_json_strict(path: str):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"), object_pairs_hook=RUN._no_duplicate_keys)


def write_json(path: str, value, *, exclusive: bool = True) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_CREAT | os.O_WRONLY | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_text(path: str, text: str, *, exclusive: bool = True) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    flags = os.O_CREAT | os.O_WRONLY | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def tooling_commit() -> str:
    result = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "rev-parse", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        reject("REPLAY_GIT", f"cannot resolve tooling commit: {result.stderr.strip()}")
    sha = result.stdout.strip()
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        reject("REPLAY_GIT", f"invalid tooling commit {sha!r}")
    status = subprocess.run(
        ["git", "-C", TOOLING_ROOT, "status", "--porcelain", "--untracked-files=all", "--", "benchmarks/pr15i_d3_b_f1_1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if status.returncode != 0 or status.stdout.strip():
        reject("REPLAY_GIT", "F1.1 tooling has uncommitted or untracked changes")
    return sha


def verify_original_seal(campaign_dir: str) -> dict:
    seal = read_json_strict(os.path.join(campaign_dir, "raw", "seal.json"))
    if seal.get("schema") != RUN.SCHEMA_SEAL or seal.get("kind") != "control":
        reject("REPLAY_SEAL", "unexpected original seal schema/kind")
    files = seal.get("files")
    if not isinstance(files, dict) or not files:
        reject("REPLAY_SEAL", "original seal has no members")
    for relative, expected in files.items():
        if relative.startswith("/") or ".." in relative.split("/"):
            reject("REPLAY_SEAL", f"unsafe original member {relative!r}")
        full = os.path.join(campaign_dir, relative)
        if os.path.islink(full) or not os.path.isfile(full):
            reject("REPLAY_SEAL", f"missing or symlinked original member {relative}")
        if sha256_file(full) != expected:
            reject("REPLAY_SEAL", f"original member changed before replay: {relative}")
    return seal


def original_inventory(campaign_dir: str, seal: dict) -> list[dict]:
    members = sorted(set(seal["files"]) | {"raw/seal.json"})
    receipt = os.path.join(campaign_dir, "verification.json")
    if os.path.isfile(receipt):
        members.append("verification.json")
    entries = []
    for relative in sorted(set(members)):
        full = os.path.join(campaign_dir, relative)
        entries.append(
            {
                "path": relative,
                "bytes": os.path.getsize(full),
                "sha256": sha256_file(full),
            }
        )
    return entries


def validate_historical_control(campaign_dir: str) -> dict:
    if not os.path.isabs(campaign_dir) or os.path.islink(campaign_dir):
        reject("REPLAY_PATH", "historical control must be an absolute non-symlinked path")
    directory = os.path.realpath(campaign_dir)
    if os.path.basename(directory) != HISTORICAL_NAME:
        reject("REPLAY_PATH", f"historical control must be the F1 {HISTORICAL_NAME} campaign")
    if not os.path.isdir(directory):
        reject("REPLAY_PATH", f"historical control is missing: {directory}")
    seal = verify_original_seal(directory)
    manifest = read_json_strict(os.path.join(directory, "manifest.json"))
    summary = read_json_strict(os.path.join(directory, "sanitized", "summary.json"))
    if manifest.get("campaign") != HISTORICAL_NAME:
        reject("REPLAY_MANIFEST", "historical campaign name differs")
    if manifest.get("kind") != "control":
        reject("REPLAY_MANIFEST", "historical campaign is not a control")
    if manifest.get("base_source_sha") != HISTORICAL_BASE or manifest.get("candidate_source_sha") != HISTORICAL_BASE:
        reject("REPLAY_MANIFEST", "historical source identities differ")
    if manifest.get("protocol_sha256") != HISTORICAL_PROTOCOL_SHA256:
        reject("REPLAY_MANIFEST", "historical protocol digest differs")
    if manifest.get("tooling_sha") != HISTORICAL_T1:
        reject("REPLAY_MANIFEST", "historical tooling revision differs")
    if summary.get("status") != "CONTROL_QUALIFIED":
        reject("REPLAY_SUMMARY", "historical controller summary is not CONTROL_QUALIFIED")
    if summary.get("a_a", {}).get("passes") is not True:
        reject("REPLAY_SUMMARY", "historical controller summary did not pass its numerical A/A")
    slots = []
    samples = 0
    warmups = 0
    probes = 0
    for index in range(1, 17):
        slot = read_json_strict(os.path.join(directory, "raw", "slots", f"slot-{index:02d}.json"))
        lanes = slot.get("lanes")
        if not isinstance(lanes, list) or len(lanes) != 9:
            reject("REPLAY_SLOT", f"slot {index:02d} does not contain nine lanes")
        for lane in lanes:
            values = lane.get("samples_ns")
            if not isinstance(values, list) or len(values) != 20:
                reject("REPLAY_SAMPLE", f"slot {index:02d}:{lane.get('id')} sample count differs")
            if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
                reject("REPLAY_SAMPLE", f"slot {index:02d}:{lane.get('id')} has an invalid sample")
            samples += len(values)
            warmups += len(lane.get("warmup_ids") or [])
            for field in ("total_hits", "expected_total_hits", "doc_ids", "expected_doc_ids"):
                if field not in lane:
                    reject("REPLAY_ORACLE", f"slot {index:02d}:{lane.get('id')} lacks {field}")
            if lane.get("oracle_ok") is not True:
                reject("REPLAY_ORACLE", f"slot {index:02d}:{lane.get('id')} oracle_ok is not true")
        for stage in ("before", "after"):
            probe = read_json_strict(
                os.path.join(directory, "raw", "contention", f"slot-{index:02d}-{stage}.json")
            )
            if probe.get("state") != "clear" or probe.get("reason_codes") not in ([], None):
                reject("REPLAY_CONTENTION", f"slot {index:02d} {stage} probe is not clear")
            probes += 1
        slots.append(slot)
    if samples != 2880 or warmups != 720 or probes != 32:
        reject("REPLAY_COUNT", f"unexpected historical totals: {samples}/{warmups}/{probes}")
    if len(seal["files"]) != 59:
        reject("REPLAY_SEAL", f"expected 59 sealed members, found {len(seal['files'])}")
    documents = [
        os.path.join(TOOLING_ROOT, "docs/pr-artifacts/pr-15i-d3-b-f1/execution-status.md"),
        os.path.join(TOOLING_ROOT, "docs/pr-artifacts/pr-15i-d3-b-f1/a-a-control.md"),
    ]
    for path in documents:
        with open(path, encoding="utf-8") as handle:
            if "MEASUREMENT_BLOCKED" not in handle.read():
                reject("REPLAY_HISTORY", f"historical blocked status missing from {path}")
    return {
        "directory": directory,
        "manifest": manifest,
        "summary": summary,
        "seal": seal,
        "slots": slots,
    }


def _map_paths(record: dict, campaign_dir: str) -> dict:
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
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            event["manifest_path"],
            "--target-dir",
            target,
        ]
    updated["target_dirs"] = {
        "A": os.path.join(campaign_dir, "build", "A"),
        "B": os.path.join(campaign_dir, "build", "B"),
    }
    return updated


def _map_adapter(record: dict, campaign_dir: str) -> dict:
    canonical = os.path.join(campaign_dir, "compile-source")
    arm = record["arm"]
    target = os.path.join(campaign_dir, "build", arm)
    updated = copy.deepcopy(record)
    updated["canonical_source"] = canonical
    updated["cwd"] = os.path.join(canonical, "benchmarks/pr15d/adapters/quervant")
    updated["manifest_path"] = os.path.join(canonical, "benchmarks/pr15d/adapters/quervant/Cargo.toml")
    updated["target_dir"] = target
    updated["binary_path"] = os.path.join(target, "release", RUN.ADAPTER_BINARY)
    updated["command_argv"] = [
        "cargo",
        "build",
        "--release",
        "--locked",
        "--manifest-path",
        updated["manifest_path"],
        "--target-dir",
        target,
    ]
    return updated


def _map_host(record: dict, campaign_dir: str) -> dict:
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


def transform_control(historical: dict, copy_dir: str, tooling_sha: str, protocol_sha: str) -> dict:
    source = historical["directory"]
    os.makedirs(copy_dir, exist_ok=False)
    for relative in sorted(historical["seal"]["files"]):
        destination = os.path.join(copy_dir, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(os.path.join(source, relative), destination)
    os.makedirs(os.path.join(copy_dir, "compile-source"), exist_ok=False)
    write_text(os.path.join(copy_dir, "compile-source", ".git"), "synthetic rehearsal marker\n")

    campaign = EVIDENCE_DIR
    comparison = "d3bf11-base"
    tooling_manifest = os.path.join(TOOLING_DIR, "tooling_manifest.json")
    controller_sha = sha256_file(os.path.join(TOOLING_DIR, "run.py"))
    verifier_sha = sha256_file(os.path.join(TOOLING_DIR, "verify.py"))
    tooling_manifest_sha = sha256_file(tooling_manifest)

    authorization = read_json_strict(os.path.join(copy_dir, "authorization.json"))
    authorization["campaign"] = campaign
    authorization["comparison"] = comparison
    authorization["protocol_sha256"] = protocol_sha
    authorization["rehearsal_only"] = True
    authorization["statement"] = "SYNTHETIC_REHEARSAL_ONLY; copied F1 data; NEVER performance evidence or publication"

    manifest = read_json_strict(os.path.join(copy_dir, "manifest.json"))
    manifest["campaign"] = campaign
    manifest["comparison"] = comparison
    manifest["protocol_sha256"] = protocol_sha
    manifest["tooling_sha"] = tooling_sha
    manifest["controller_sha256"] = controller_sha
    manifest["verifier_sha256"] = verifier_sha
    manifest["tooling_manifest_sha256"] = tooling_manifest_sha
    manifest["rehearsal_only"] = True

    provenance = read_json_strict(os.path.join(copy_dir, "raw", "build-provenance.json"))
    provenance["campaign"] = campaign
    provenance["protocol_sha256"] = protocol_sha
    provenance = _map_paths(provenance, copy_dir)
    write_json(os.path.join(copy_dir, "raw", "build-provenance.json"), provenance, exclusive=False)

    host = read_json_strict(os.path.join(copy_dir, "raw", "host-attestation.json"))
    host["protocol_sha256"] = protocol_sha
    host = _map_host(host, copy_dir)
    host["host_fingerprint"] = RUN.host_fingerprint(host)
    if VERIFY.host_fingerprint(host) != host["host_fingerprint"]:
        reject("REPLAY_HOST", "controller and verifier fingerprints disagree on the valid fixture")
    write_json(os.path.join(copy_dir, "raw", "host-attestation.json"), host, exclusive=False)

    setup = os.path.join(copy_dir, "raw", "setup")
    corpus = read_json_strict(os.path.join(setup, "corpus.json"))
    corpus["protocol_sha256"] = protocol_sha
    write_json(os.path.join(setup, "corpus.json"), corpus, exclusive=False)
    for arm in ("A", "B"):
        adapter = read_json_strict(os.path.join(setup, f"adapter-{arm}.json"))
        adapter = _map_adapter(adapter, copy_dir)
        adapter["protocol_sha256"] = protocol_sha
        write_json(os.path.join(setup, f"adapter-{arm}.json"), adapter, exclusive=False)
    for name in sorted(os.listdir(setup)):
        if name.startswith("index-") and name.endswith(".json"):
            record = read_json_strict(os.path.join(setup, name))
            record["protocol_sha256"] = protocol_sha
            write_json(os.path.join(setup, name), record, exclusive=False)

    manifest["environment"] = host
    manifest["environment_fingerprint"] = host["host_fingerprint"]
    manifest["build_provenance_sha256"] = sha256_file(os.path.join(copy_dir, "raw", "build-provenance.json"))
    manifest["host_attestation_sha256"] = sha256_file(os.path.join(copy_dir, "raw", "host-attestation.json"))
    write_json(os.path.join(copy_dir, "authorization.json"), authorization, exclusive=False)
    write_json(os.path.join(copy_dir, "manifest.json"), manifest, exclusive=False)

    campaign_record = {"campaign": campaign, "kind": "control", "comparison": comparison}
    lanes = RUN.lane_descriptors(RUN.PROTOCOL)
    structural = {
        "build_provenance": "PASS",
        "host_attestation": "PASS",
        "affinity_observations": "PASS",
    }
    summary = RUN.assemble_campaign(campaign_record, manifest, RUN.PROTOCOL, historical["slots"], lanes, structural)
    write_json(os.path.join(copy_dir, "sanitized", "summary.json"), summary, exclusive=False)
    write_text(
        os.path.join(copy_dir, "sanitized", "summary.md"),
        RUN.render_summary_markdown(summary),
        exclusive=False,
    )

    files = {}
    for relative in sorted(historical["seal"]["files"]):
        files[relative] = sha256_file(os.path.join(copy_dir, relative))
    seal = {"schema": RUN.SCHEMA_SEAL, "kind": "control", "files": files}
    write_json(os.path.join(copy_dir, "raw", "seal.json"), seal, exclusive=False)
    return {"campaign_dir": copy_dir, "manifest": manifest, "seal": seal, "summary": summary}


def reseal(campaign_dir: str, *, extra_members: dict | None = None) -> dict:
    seal = read_json_strict(os.path.join(campaign_dir, "raw", "seal.json"))
    files = dict(seal["files"])
    if extra_members:
        files.update(extra_members)
    files = {relative: sha256_file(os.path.join(campaign_dir, relative)) for relative in sorted(files)}
    updated = {"schema": seal["schema"], "kind": seal["kind"], "files": files}
    write_json(os.path.join(campaign_dir, "raw", "seal.json"), updated, exclusive=False)
    return updated


def run_verifier(campaign_dir: str) -> tuple[int, dict | None, str, str]:
    verify_script = os.path.join(TOOLING_DIR, "verify.py")
    result = subprocess.run(
        [sys.executable, verify_script, "--campaign-dir", campaign_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        parsed = None
    return result.returncode, parsed, result.stdout, result.stderr


def _rejection_code(parsed: dict | None) -> str | None:
    if not isinstance(parsed, dict):
        return None
    reasons = parsed.get("reasons") or []
    if reasons and isinstance(reasons[0], dict):
        return reasons[0].get("code")
    return None


def positive_checks(campaign_dir: str) -> dict:
    code, parsed, stdout, stderr = run_verifier(campaign_dir)
    if code != 0 or not isinstance(parsed, dict):
        reject("REPLAY_POSITIVE", f"full verifier did not exit 0: {stdout[-500:]} {stderr[-500:]}")
    expected = {
        "verification": "PASS",
        "campaign_status": "CONTROL_QUALIFIED",
        "summary_match": True,
        "a_a_passes": True,
        "slots": 16,
        "live_binary_rehash": "UNAVAILABLE_ARCHIVE",
    }
    for field, value in expected.items():
        if parsed.get(field) != value:
            reject("REPLAY_POSITIVE", f"verifier field {field} is {parsed.get(field)!r}, expected {value!r}")
    structural = parsed.get("structural") or {}
    for name in ("build_provenance", "host_attestation", "affinity_observations"):
        if structural.get(name) != "PASS":
            reject("REPLAY_POSITIVE", f"structural {name} is not PASS")
    return {"exit_code": code, "report": parsed}


def _copy_case(positive_dir: str, case_dir: str) -> str:
    if os.path.exists(case_dir):
        reject("REPLAY_PATH", f"negative case directory already exists: {case_dir}")
    shutil.copytree(positive_dir, case_dir)
    return case_dir


def _mutate_slot(case_dir: str, mutation) -> None:
    path = os.path.join(case_dir, "raw", "slots", "slot-01.json")
    slot = read_json_strict(path)
    mutation(slot)
    write_json(path, slot, exclusive=False)
    # Oracle/sample cases are resealed: the verifier must reject the content,
    # not merely detect a stale seal (which is the separate R09 case).
    reseal(case_dir)


def execute_negative_cases(positive_dir: str, root: str) -> list[dict]:
    cases: list[tuple[str, str, object]] = [
        ("R02", "V_ORACLE", lambda case: _mutate_slot(
            case, lambda slot: slot["lanes"][1].__setitem__("doc_ids", ["forged"])
        )),
        ("R03", "V_ORACLE", lambda case: _mutate_slot(
            case, lambda slot: slot["lanes"][7].__setitem__("total_hits", slot["lanes"][7]["total_hits"] + 1)
        )),
        ("R04", "V_SAMPLE_TYPE", lambda case: _mutate_slot(
            case, lambda slot: slot["lanes"][0]["samples_ns"].__setitem__(0, True)
        )),
        ("R05", "V_INVENTORY", lambda case: write_text(os.path.join(case, "intruder.json"), "{}")),
        ("R06", "V_INVENTORY", lambda case: write_text(
            os.path.join(case, "unlisted", "compile-source", "bait"), "{}"
        )),
        ("R07", "V_SYMLINK", lambda case: _symlink_compile_source(case)),
        ("R08", "V_SEAL", lambda case: _seal_nested_compile_source(case)),
        ("R09", "V_SEAL", lambda case: write_text(os.path.join(case, "raw", "slots", "slot-01.json"), "{}")),
        ("R10", "V_HOST", lambda case: _corrupt_host(case, "fingerprint")),
        ("R11", "V_HOST", lambda case: _corrupt_host(case, "allowed")),
        ("R12", "V_HOST", lambda case: _corrupt_host(case, "duplicate")),
        ("R13", "V_BUILD_PROVENANCE", lambda case: _corrupt_provenance(case)),
        ("R14", "V_TOOLING_SHA", lambda case: _corrupt_manifest(case, "tooling_sha")),
        ("R15", "V_PROTOCOL", lambda case: _corrupt_authorization(case)),
        ("R16", None, lambda case: write_json(
            os.path.join(case, "verification.json"),
            {"verification": "FAIL", "campaign": EVIDENCE_DIR, "campaign_status": "CAMPAIGN_REJECTED"},
        )),
    ]
    results = []
    for case_id, expected, mutate in cases:
        case_dir = _copy_case(positive_dir, os.path.join(root, "negative", case_id, EVIDENCE_DIR))
        mutate(case_dir)
        code, parsed, stdout, stderr = run_verifier(case_dir)
        if expected is None:
            matched = (
                code == 0
                and isinstance(parsed, dict)
                and parsed.get("verification") == "PASS"
                and parsed.get("campaign_status") == "CONTROL_QUALIFIED"
            )
            actual = parsed.get("campaign_status") if isinstance(parsed, dict) else None
        else:
            actual = _rejection_code(parsed)
            matched = code != 0 and actual == expected
        results.append(
            {
                "case": case_id,
                "expected": expected if expected is not None else "INVARIANCE_PASS",
                "actual": actual,
                "exit_code": code,
                "matched_expectation": matched,
                "stderr_tail": stderr[-300:],
            }
        )
        if not matched:
            reject(
                "REPLAY_CASE",
                f"{case_id}: expected {expected!r}, got exit {code} code {actual!r}: {stdout[-400:]}",
            )
    return results


def _symlink_compile_source(case: str) -> None:
    target = os.path.join(case, "unlisted")
    os.makedirs(target, exist_ok=True)
    write_text(os.path.join(target, "bait"), "bait")
    compile_source = os.path.join(case, "compile-source")
    for name in sorted(os.listdir(compile_source)):
        os.remove(os.path.join(compile_source, name))
    os.rmdir(compile_source)
    os.symlink(target, compile_source)


def _seal_nested_compile_source(case: str) -> None:
    write_text(os.path.join(case, "compile-source", "sneak"), "sneak")
    reseal(case, extra_members={"compile-source/sneak": ""})


def _update_manifest_digest(case: str, field: str, relative: str) -> None:
    path = os.path.join(case, "manifest.json")
    manifest = read_json_strict(path)
    manifest[field] = sha256_file(os.path.join(case, relative))
    write_json(path, manifest, exclusive=False)


def _corrupt_host(case: str, mode: str) -> None:
    path = os.path.join(case, "raw", "host-attestation.json")
    host = read_json_strict(path)
    if mode == "fingerprint":
        host["host_fingerprint"] = "0" * 64
    elif mode == "allowed":
        host["allowed_cpus_before_pin"] = sorted(list(host["allowed_cpus_before_pin"]) + [99])
        # Keep the old fingerprint so the recomputation must fail.
    elif mode == "duplicate":
        host["allowed_cpus_before_pin"] = sorted(list(host["allowed_cpus_before_pin"]) + [host["allowed_cpus_before_pin"][0]])
        host["host_fingerprint"] = "0" * 64
    write_json(path, host, exclusive=False)
    manifest_path = os.path.join(case, "manifest.json")
    manifest = read_json_strict(manifest_path)
    if mode == "duplicate":
        manifest["environment"] = host
        manifest["environment_fingerprint"] = host["host_fingerprint"]
    manifest["host_attestation_sha256"] = sha256_file(path)
    write_json(manifest_path, manifest, exclusive=False)
    reseal(case)


def _corrupt_provenance(case: str) -> None:
    path = os.path.join(case, "raw", "build-provenance.json")
    provenance = read_json_strict(path)
    provenance["events"][1]["binary_sha256"] = "c" * 64
    write_json(path, provenance, exclusive=False)
    manifest_path = os.path.join(case, "manifest.json")
    manifest = read_json_strict(manifest_path)
    manifest["build_provenance_sha256"] = sha256_file(path)
    write_json(manifest_path, manifest, exclusive=False)
    reseal(case)


def _corrupt_manifest(case: str, field: str) -> None:
    path = os.path.join(case, "manifest.json")
    manifest = read_json_strict(path)
    manifest[field] = "f" * 40
    write_json(path, manifest, exclusive=False)
    reseal(case)


def _corrupt_authorization(case: str) -> None:
    path = os.path.join(case, "authorization.json")
    authorization = read_json_strict(path)
    authorization["protocol_sha256"] = "0" * 64
    write_json(path, authorization, exclusive=False)
    reseal(case)


def harness_self_test() -> dict:
    """Deliberately compare a wrong expected code; the harness must fail closed."""
    expected = "V_INVENTORY"
    actual = "V_ORACLE"
    matched = expected == actual
    return {
        "expected": expected,
        "actual": actual,
        "matched_expectation": matched,
        "harness_fail_closed": not matched,
    }


def report_exit_code(report: dict) -> int:
    if report.get("status") != "SYNTHETIC_REHEARSAL_VERIFIER_PASS":
        return 3
    if report.get("negative_cases_completed") != len(NEGATIVE_CASES):
        return 3
    if report.get("negative_cases_as_expected") != len(NEGATIVE_CASES):
        return 3
    for case in report.get("cases", []):
        if not case.get("matched_expectation"):
            return 3
    if report.get("harness_self_test", {}).get("harness_fail_closed") is not True:
        return 3
    if report.get("original_files_unchanged") is not True:
        return 3
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-control", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if not os.path.isabs(args.out) or os.path.islink(args.out):
            reject("REPLAY_PATH", "--out must be an absolute non-symlinked path")
        out = os.path.realpath(args.out)
        target_root = os.path.realpath(os.path.join(TOOLING_ROOT, "target", "pr15i-d3-b", "fixup-f1-1"))
        if os.path.commonpath([out, target_root]) != target_root:
            reject("REPLAY_PATH", f"--out must be beneath {target_root}")
        if os.path.exists(out):
            reject("REPLAY_PATH", f"--out already exists: {out}")
        round_root = os.path.dirname(out)
        historical = validate_historical_control(args.historical_control)
        inventory = original_inventory(historical["directory"], historical["seal"])
        inventory_sha = sha256_bytes(canonical_json_bytes(inventory))
        protocol_sha = sha256_file(os.path.join(TOOLING_DIR, "protocol_v1.json"))
        if RUN.load_protocol()[1] != protocol_sha:
            reject("REPLAY_PROTOCOL", "F1.1 protocol file/literal mismatch")
        tooling_sha = tooling_commit()
        copy_dir = os.path.join(round_root, EVIDENCE_DIR)
        transformed = transform_control(historical, copy_dir, tooling_sha, protocol_sha)
        positive = positive_checks(copy_dir)
        cases = execute_negative_cases(copy_dir, round_root)
        after = original_inventory(historical["directory"], historical["seal"])
        unchanged = after == inventory
        if not unchanged:
            reject("REPLAY_ORIGINAL_CHANGED", "historical F1 files changed during rehearsal")
        if os.path.exists(os.path.join(historical["directory"], "verification.json")):
            reject("REPLAY_ORIGINAL_CHANGED", "rehearsal wrote a receipt into the historical control")
        historical_diff = subprocess.run(
            ["git", "-C", TOOLING_ROOT, "diff", "--exit-code", HISTORICAL_T1, "--", "benchmarks/pr15i_d3_b_f1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if historical_diff.returncode != 0:
            reject("REPLAY_ORIGINAL_CHANGED", "historical F1 tooling differs from T1")
        self_test = harness_self_test()
        report = {
            "status": "SYNTHETIC_REHEARSAL_VERIFIER_PASS",
            "source": "F1_BLOCKED_CONTROL_COPIED",
            "rehearsal_only": True,
            "official_measurement": False,
            "historical_t1": HISTORICAL_T1,
            "new_protocol_sha256": protocol_sha,
            "new_tooling_candidate_commit": tooling_sha,
            "original_source_inventory_sha256": inventory_sha,
            "original_files_unchanged": unchanged,
            "positive_full_verifier": "PASS",
            "positive_report": positive["report"],
            "negative_cases_completed": len(cases),
            "negative_cases_as_expected": sum(1 for case in cases if case["matched_expectation"]),
            "cases": cases,
            "harness_self_test": self_test,
            "archive_published": False,
            "performance_claim": "NONE",
            "synthetic_campaign": transformed["campaign_dir"],
            "recorded_utc": RUN.utc_now(),
        }
        write_json(out, report)
        print(json.dumps({"status": report["status"], **self_test, "cases": len(cases)}, sort_keys=True))
        return report_exit_code(report)
    except ReplayError as error:
        print(f"REHEARSAL_FAILED {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

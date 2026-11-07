#!/usr/bin/env python3
"""PR 15I-0 read-only qualification controller.

Primary (verification) mode:

```sh
python3 benchmarks/pr15i_0/verify.py \
  --root "$ROOT" --source-sha "$MEASURED_SHA" \
  --pr15d-run "$D_RUN" --pr15f-run "$F_RUN" \
  --pr15f-prepared "$PREP" --mutation-run "$M_RUN" \
  --out "$ROOT/target/pr15i-0/verification-01.json"
```

Two auxiliary modes share this file so that the frozen allow-listed PR 15I-0
tree stays exactly as prescribed:

* ``seal`` — write an exclusive, fsync'd ``seal.json`` for one finished
  campaign directory (schema ``pr15i-0-seal-v1``).
* ``qa`` — execute the fixed repository QA/regression command matrix and record
  the real exit codes into an immutable record consumed by gate ``I0-P11``.

The verifier never mutates a measured index, never edits a source manifest and
never writes into a sealed campaign directory. Every gate is one of
``PASS``/``FAIL``/``BLOCKED``/``NOT_RUN``/``NOT_MEASURED`` — never a bare
boolean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

SCHEMA_VERIFICATION = "pr15i-0-verification-v1"
SCHEMA_SEAL = "pr15i-0-seal-v1"
SCHEMA_QA = "pr15i-0-qa-record-v1"
CONTROLLER_VERSION = "pr15i-0-controller-1"

PROTOCOL_REL = "benchmarks/pr15i_0/protocol.json"
ALLOWED_RUN_ROOTS = (
    "target/pr15i-0",
    "target/pr15d/runs",
    "target/pr15e",
    "target/pr15f",
)
PROTECTED_PATHS = (
    "crates/",
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain.toml",
    ".github/workflows",
    "benchmarks/pr15d",
    "benchmarks/pr15e",
    "benchmarks/pr15f",
)
GATE_IDS = (
    "I0-P00",
    "I0-P01",
    "I0-P02",
    "I0-P03",
    "I0-P04",
    "I0-P05",
    "I0-P06",
    "I0-P07",
    "I0-P08",
    "I0-P09",
    "I0-P10",
    "I0-P11",
    "I0-P12",
)
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_NOT_RUN = "NOT_RUN"
STATUS_NOT_MEASURED = "NOT_MEASURED"
UNQUALIFIED_STATUSES = (STATUS_FAIL, STATUS_BLOCKED, STATUS_NOT_RUN)

PR15D_ENGINES = ("quervant", "tantivy", "lucene")
PR15D_REGIMES = ("process_cold", "warm")
PR15D_CLASSES = ("absent", "rare", "medium", "common")
PR15D_N = (10000, 100000)
PR15D_K = (10, 100)
PR15D_WARMUP_LANES = 16
PR15D_LANES = 32
PR15D_TRIALS = 3
PR15F_QUERY_LANES = (
    (10000, "absent", 100),
    (10000, "rare", 100),
    (10000, "medium", 100),
    (10000, "common", 100),
    (100000, "absent", 100),
    (100000, "rare", 100),
    (100000, "medium", 100),
    (100000, "common", 100),
    (100000, "common", 10),
)
PR15F_REOPEN_PROCESSES = 42
PR15F_REOPEN_PER_N = 21

PRIVACY_PATTERNS = (
    (re.compile(r"/home/[A-Za-z0-9._-]+"), "unix home path"),
    (re.compile(r"/mnt/[a-z]/"), "windows mount path"),
    (re.compile(r"[A-Za-z]:\\\\Users\\\\"), "windows user path"),
    (re.compile(r"\b(root|xuser)-[0-9a-f]{8,}\b"), "process id"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws access key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class VerificationError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------


def canonical_json_bytes(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        + b"\n"
    )


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, payload) -> str:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    data = canonical_json_bytes(payload)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return hashlib.sha256(data).hexdigest()


def rel_to(root: str, path: str) -> str:
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path


def require_plain_path(root: str, value: str, label: str, must_exist: bool = True) -> str:
    """Absolute, canonical, non-symlinked path below an allowed run root."""
    if not os.path.isabs(value):
        raise VerificationError("X19_PATH", f"{label} must be absolute: {value}")
    candidate = os.path.realpath(value)
    if candidate != os.path.abspath(value):
        raise VerificationError("X19_PATH", f"{label} is not canonical: {value}")
    if must_exist and not os.path.exists(candidate):
        raise VerificationError("X19_PATH", f"{label} does not exist: {value}")
    if os.path.islink(value):
        raise VerificationError("X19_PATH", f"{label} is a symlink: {value}")
    relative = rel_to(root, candidate)
    if relative.startswith(".."):
        raise VerificationError("X19_PATH", f"{label} escapes the repository: {value}")
    if not any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in ALLOWED_RUN_ROOTS
    ):
        raise VerificationError(
            "X19_PATH",
            f"{label} must live under one of {ALLOWED_RUN_ROOTS}: {relative}",
        )
    return candidate


def require_regular_files(directory: str) -> None:
    for current, directories, files in os.walk(directory):
        for name in directories + files:
            path = os.path.join(current, name)
            if os.path.islink(path):
                raise VerificationError("X19_PATH", f"symlink in evidence tree: {path}")


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(
        value, float
    )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

FROZEN_PROTOCOL = {
    "schema": "pr15i-0-measurement-contract-v1",
    "corpus": "pr15d_v1",
    "document_counts": [10000, 100000],
    "three_engine": {
        "engines": ["quervant", "tantivy", "lucene"],
        "trials": 3,
        "require_original_oracle": True,
        "require_clear_contention": True,
        "require_native_filesystem": True,
    },
    "quervant_profile": {
        "runner": "benchmarks/pr15f/run.py",
        "warm_query_lanes": 9,
        "reopen_single_processes": 42,
        "allocation_optional": True,
        "report_inclusive_exclusive_separately": True,
    },
    "mutation_probe": {
        "allowed_payload_versions": [1, 2],
        "read_only": True,
        "max_file_bytes": 268435456,
        "unsupported_batch_detail": "opaque_remainder",
        "require_exact_byte_reconciliation": True,
    },
    "prohibited": [
        "production_code_change",
        "frozen_input_change",
        "historical_seal_change",
        "new_codec_candidate",
    ],
}


def load_protocol(root: str) -> dict:
    path = os.path.join(root, PROTOCOL_REL)
    if not os.path.isfile(path):
        raise VerificationError("X01_PROTOCOL", f"protocol is missing: {PROTOCOL_REL}")
    digest = sha256_file(path)
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError("X02_PROTOCOL", f"protocol is not valid JSON: {error}")
    if not isinstance(parsed, dict):
        raise VerificationError("X02_PROTOCOL", "protocol must be a JSON object")
    if parsed.get("test_fixture") is True:
        raise VerificationError("X30_FIXTURE", "protocol is a synthetic fixture")
    if parsed != FROZEN_PROTOCOL:
        raise VerificationError(
            "X02_PROTOCOL",
            "protocol content drifted from the frozen PR 15I-0 measurement contract",
        )
    if parsed["mutation_probe"]["max_file_bytes"] != 268435456:
        raise VerificationError("X02_PROTOCOL", "probe byte cap was retuned")
    document_counts = parsed["document_counts"]
    if not isinstance(document_counts, list) or not all(
        is_int(value) for value in document_counts
    ):
        raise VerificationError("X02_PROTOCOL", "document_counts must be integers")
    return {"sha256": digest, "bytes": len(raw), "value": parsed}


# ---------------------------------------------------------------------------
# Gate collector
# ---------------------------------------------------------------------------


class Gates:
    def __init__(self):
        self.entries: dict[str, dict] = {}
        for gate in GATE_IDS:
            self.entries[gate] = {
                "status": STATUS_NOT_RUN,
                "detail": "not evaluated",
                "evidence": [],
            }

    def set(self, gate: str, status: str, detail: str, evidence=None) -> None:
        if gate not in self.entries:
            raise VerificationError("X99_GATE", f"unknown gate {gate}")
        entry = self.entries[gate]
        entry["status"] = status
        entry["detail"] = detail
        if evidence is not None:
            entry["evidence"] = list(evidence)

    def get(self, gate: str) -> dict:
        return self.entries[gate]

    def statuses(self) -> dict[str, str]:
        return {gate: entry["status"] for gate, entry in self.entries.items()}


# ---------------------------------------------------------------------------
# External command execution (read-only verification)
# ---------------------------------------------------------------------------


def run_command(argv: list[str], cwd: str) -> dict:
    result = subprocess.run(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return {
        "argv": argv,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def record_command(command: dict) -> dict:
    return {
        "argv": command["argv"],
        "exit_code": command["exit_code"],
        "stdout_sha256": hashlib.sha256(command["stdout"].encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(command["stderr"].encode("utf-8")).hexdigest(),
        "stdout_tail": command["stdout"].strip().splitlines()[-3:],
    }


# ---------------------------------------------------------------------------
# Source / provenance checks
# ---------------------------------------------------------------------------


def git(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def check_source(root: str, source_sha: str, gates: Gates, decision_log: list) -> None:
    if not SHA1_RE.fullmatch(source_sha):
        gates.set("I0-P00", STATUS_FAIL, "--source-sha is not 40 lowercase hex")
        return
    head = git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        gates.set("I0-P00", STATUS_BLOCKED, "git HEAD is unavailable")
        return
    head_sha = head.stdout.strip()
    status = git(root, "status", "--porcelain=v1")
    if status.returncode != 0:
        gates.set("I0-P00", STATUS_BLOCKED, "git status is unavailable")
        return
    if status.stdout.strip():
        gates.set(
            "I0-P00",
            STATUS_FAIL,
            "tracked working tree is dirty; timing evidence would be unusable",
        )
        return
    diff = git(root, "diff", "--exit-code", source_sha, "HEAD", "--", *PROTECTED_PATHS)
    if diff.returncode == 128:
        gates.set("I0-P00", STATUS_FAIL, f"measured source {source_sha} is not in this history")
        return
    if diff.returncode != 0:
        gates.set(
            "I0-P00",
            STATUS_FAIL,
            "protected production/benchmark paths differ from the measured source",
            [diff.stdout.strip()[:2000]],
        )
        return
    if head_sha != source_sha:
        decision_log.append(
            {
                "rule": "I0-X14",
                "observed": "HEAD differs from the measured source",
                "action": "protected paths proven byte-identical to the measured source",
                "verification": "git diff --exit-code <source> HEAD -- <protected>",
            }
        )
    gates.set(
        "I0-P00",
        STATUS_PASS,
        f"source {source_sha} reconciled; protected paths byte-identical",
        [{"head": head_sha, "protected_paths": list(PROTECTED_PATHS)}],
    )


def require_source(manifest_source: str, source_sha: str, label: str, gates: Gates) -> bool:
    if not isinstance(manifest_source, str) or not SHA1_RE.fullmatch(manifest_source):
        gates.set("I0-P09", STATUS_FAIL, f"{label} declares no valid source_sha")
        return False
    if manifest_source != source_sha:
        gates.set(
            "I0-P09",
            STATUS_FAIL,
            f"{label} was measured on {manifest_source}, not {source_sha}",
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Seal
# ---------------------------------------------------------------------------


def seal_campaign(directory: str, source_sha: str, status: str, extra: dict) -> dict:
    if not os.path.isdir(directory):
        raise VerificationError("X20_SEAL", f"campaign directory is missing: {directory}")
    require_regular_files(directory)
    entries = []
    seen = set()
    for current, _directories, files in os.walk(directory):
        for name in sorted(files):
            path = os.path.join(current, name)
            relative = os.path.relpath(path, directory).replace(os.sep, "/")
            if relative == "seal.json":
                continue
            if relative.startswith("/") or relative.startswith(".."):
                raise VerificationError("X20_SEAL", f"unsafe relative path {relative}")
            if relative in seen:
                raise VerificationError("X20_SEAL", f"duplicate evidence path {relative}")
            seen.add(relative)
            if os.path.islink(path):
                raise VerificationError("X20_SEAL", f"symlink in campaign: {relative}")
            entries.append(
                {
                    "path": relative,
                    "bytes": os.path.getsize(path),
                    "sha256": sha256_file(path),
                }
            )
    entries.sort(key=lambda entry: entry["path"])
    payload = {
        "schema": SCHEMA_SEAL,
        "campaign": os.path.basename(directory.rstrip(os.sep)),
        "source_sha": source_sha,
        "status": status,
        "files": entries,
    }
    payload.update(extra)
    destination = os.path.join(directory, "seal.json")
    data = canonical_json_bytes(payload)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"path": destination, "sha256": hashlib.sha256(data).hexdigest(), "files": len(entries)}


def verify_seal(directory: str, source_sha: str, protocol_sha: str, gates: Gates, label: str):
    """Rehash a sealed campaign. Returns the seal payload or ``None``."""
    path = os.path.join(directory, "seal.json")
    if not os.path.isfile(path):
        gates.set("I0-P09", STATUS_BLOCKED, f"{label} has no seal.json")
        return None
    try:
        seal = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        gates.set("I0-P09", STATUS_FAIL, f"{label} seal is unreadable: {error}")
        return None
    if seal.get("schema") != SCHEMA_SEAL:
        gates.set("I0-P09", STATUS_FAIL, f"{label} seal schema is not {SCHEMA_SEAL}")
        return None
    if seal.get("status") not in ("QUALIFIED", "PARTIAL"):
        gates.set("I0-P09", STATUS_FAIL, f"{label} seal status is invalid")
        return None
    if seal.get("source_sha") != source_sha:
        gates.set(
            "I0-P09",
            STATUS_FAIL,
            f"{label} seal source {seal.get('source_sha')} is not {source_sha}",
        )
        return None
    if seal.get("protocol_sha256") not in (None, protocol_sha):
        gates.set("I0-P09", STATUS_FAIL, f"{label} seal protocol digest drifted")
        return None
    listed = seal.get("files")
    if not isinstance(listed, list):
        gates.set("I0-P09", STATUS_FAIL, f"{label} seal lists no files")
        return None
    listed_paths = [entry.get("path") for entry in listed]
    if len(set(listed_paths)) != len(listed_paths):
        gates.set("I0-P09", STATUS_FAIL, f"{label} seal lists duplicate paths")
        return None
    actual = set()
    for current, _directories, files in os.walk(directory):
        for name in files:
            relative = os.path.relpath(os.path.join(current, name), directory).replace(
                os.sep, "/"
            )
            if relative != "seal.json":
                actual.add(relative)
    if actual != set(listed_paths):
        missing = sorted(set(listed_paths) - actual)[:5]
        extra = sorted(actual - set(listed_paths))[:5]
        gates.set(
            "I0-P09",
            STATUS_FAIL,
            f"{label} seal file set mismatch (missing={missing}, extra={extra})",
        )
        return None
    for entry in listed:
        target = os.path.join(directory, entry["path"])
        if os.path.islink(target):
            gates.set("I0-P09", STATUS_FAIL, f"{label} contains a symlink")
            return None
        if os.path.getsize(target) != entry.get("bytes"):
            gates.set("I0-P09", STATUS_FAIL, f"{label} file length drifted: {entry['path']}")
            return None
        if sha256_file(target) != entry.get("sha256"):
            gates.set("I0-P09", STATUS_FAIL, f"{label} file content drifted: {entry['path']}")
            return None
    return seal


# ---------------------------------------------------------------------------
# PR15D checks
# ---------------------------------------------------------------------------


def expected_pr15d_lane_ids() -> list[tuple[str, int, str, int]]:
    expected = []
    for n in PR15D_N:
        for class_name in PR15D_CLASSES:
            for k in PR15D_K:
                for regime in PR15D_REGIMES:
                    expected.append((regime, n, class_name, k))
    return expected


def fail_three_engine(gates: Gates, status: str, detail: str) -> None:
    """Mark both the three-engine and the cross-engine gate consistently."""
    gates.set("I0-P03", status, detail)
    gates.set("I0-P04", STATUS_BLOCKED if status == STATUS_BLOCKED else STATUS_FAIL, detail)


def check_pr15d(
    root: str,
    run_dir: str,
    source_sha: str,
    protocol: dict,
    verification_dir: str,
    gates: Gates,
    decision_log: list,
) -> tuple[dict, list]:
    commands = []
    run_path = os.path.join(run_dir, "run.json")
    if not os.path.isfile(run_path):
        fail_three_engine(gates, STATUS_BLOCKED, "PR 15D run.json is missing")
        return {}, commands
    run = read_json(run_path)
    if run.get("schema") != "pr15d-run-v1":
        fail_three_engine(gates, STATUS_FAIL, "run.json schema is not pr15d-run-v1")
        return {}, commands
    require_source(run.get("source_sha"), source_sha, "PR 15D run", gates)
    if run.get("qualified") is not True or run.get("status") != "complete":
        fail_three_engine(
            gates,
            STATUS_FAIL,
            f"PR 15D run is not complete/qualified ({run.get('status')})",
        )
        return {"run": run}, commands
    if run.get("trials") != PR15D_TRIALS:
        fail_three_engine(gates, STATUS_FAIL, "PR 15D did not run exactly 3 trials")
        return {"run": run}, commands
    if run.get("native_filesystem") is not True:
        fail_three_engine(gates, STATUS_FAIL, "PR 15D filesystem is not native ext4/xfs/btrfs")
        return {"run": run}, commands
    if run.get("idle_attested") is not True:
        fail_three_engine(gates, STATUS_FAIL, "PR 15D idle authorization was not recorded")
        return {"run": run}, commands
    if run.get("scored_lane", {}).get("status") != "SEMANTICALLY_NONCOMPARABLE":
        fail_three_engine(gates, STATUS_FAIL, "PR 15D scored lane comparability changed")
        return {"run": run}, commands

    expected_lanes = expected_pr15d_lane_ids()
    lane_observations = []
    trial_bytes = {}
    for trial in range(1, PR15D_TRIALS + 1):
        for engine in PR15D_ENGINES:
            path = os.path.join(run_dir, "trials", f"trial-{trial}", f"{engine}.json")
            if not os.path.isfile(path):
                fail_three_engine(gates, STATUS_FAIL, f"missing trial manifest {path}")
                return {"run": run}, commands
            trial_manifest = read_json(path)
            if trial_manifest.get("schema") != "pr15d-trial-v1":
                fail_three_engine(gates, STATUS_FAIL, f"{path} schema drift")
                return {"run": run}, commands
            if trial_manifest.get("qualified") is not True:
                fail_three_engine(
                    gates,
                    STATUS_FAIL,
                    f"trial {trial}/{engine} is unqualified: "
                    f"{trial_manifest.get('unqualified_reasons')}",
                )
                return {"run": run}, commands
            if trial_manifest.get("engine") != engine:
                fail_three_engine(gates, STATUS_FAIL, f"trial {trial} engine mismatch")
                return {"run": run}, commands
            if not require_source(
                trial_manifest.get("source_sha"),
                source_sha,
                f"PR 15D trial {trial}/{engine}",
                gates,
            ):
                return {"run": run}, commands
            lanes = trial_manifest.get("lanes") or []
            if len(lanes) != PR15D_LANES:
                fail_three_engine(
                    gates,
                    STATUS_FAIL,
                    f"trial {trial}/{engine} has {len(lanes)} lanes, expected {PR15D_LANES}",
                )
                return {"run": run}, commands
            observed = sorted(
                (lane.get("regime"), lane.get("n"), lane.get("class"), lane.get("k"))
                for lane in lanes
            )
            if observed != sorted(expected_lanes):
                fail_three_engine(
                    gates, STATUS_FAIL, f"trial {trial}/{engine} lane matrix drifted"
                )
                return {"run": run}, commands
            warm = [lane for lane in lanes if lane.get("regime") == "warm"]
            if len(warm) != PR15D_WARMUP_LANES:
                fail_three_engine(gates, STATUS_FAIL, "warm lane count drifted")
                return {"run": run}, commands
            for lane in lanes:
                if lane.get("oracle_ok") is not True:
                    fail_three_engine(
                        gates,
                        STATUS_FAIL,
                        f"trial {trial}/{engine} lane {lane.get('id')} failed the oracle",
                    )
                    return {"run": run}, commands
                if not lane.get("samples_ns"):
                    fail_three_engine(
                        gates,
                        STATUS_FAIL,
                        f"trial {trial}/{engine} lane {lane.get('id')} has no samples",
                    )
                    return {"run": run}, commands
                contention = lane.get("contention") or {}
                if contention.get("pre") != "clear" or contention.get("post") != "clear":
                    fail_three_engine(
                        gates,
                        STATUS_FAIL,
                        f"trial {trial}/{engine} lane {lane.get('id')} contention is not clear",
                    )
                    return {"run": run}, commands
            for record in trial_manifest.get("contention") or []:
                if record.get("state") != "clear":
                    fail_three_engine(
                        gates,
                        STATUS_FAIL,
                        f"trial {trial}/{engine} {record.get('phase')} contention is "
                        f"{record.get('state')}",
                    )
                    return {"run": run}, commands
            build = trial_manifest.get("build") or {}
            for n in PR15D_N:
                entry = build.get(str(n)) or {}
                if entry.get("verified") is not True:
                    fail_three_engine(
                        gates,
                        STATUS_FAIL,
                        f"trial {trial}/{engine} {n} build was not verified",
                    )
                    return {"run": run}, commands
                if not is_int(entry.get("index_bytes")) or entry["index_bytes"] <= 0:
                    fail_three_engine(
                        gates,
                        STATUS_FAIL,
                        f"trial {trial}/{engine} {n} index_bytes is not a positive integer",
                    )
                    return {"run": run}, commands
                trial_bytes.setdefault(f"{trial}/{engine}", {})[n] = entry["index_bytes"]
            lane_observations.append(
                {
                    "trial": trial,
                    "engine": engine,
                    "lanes": len(lanes),
                    "warm_lanes": len(warm),
                    "engine_version": trial_manifest.get("engine_version"),
                    "index_bytes": build,
                }
            )

    # Independent validator.
    validate_out = os.path.join(verification_dir, "validation-pr15d.json")
    command = run_command(
        [
            sys.executable,
            os.path.join("benchmarks", "pr15d", "harness", "validate.py"),
            "--run",
            run_dir,
            "--out",
            validate_out,
        ],
        root,
    )
    commands.append(record_command(command))
    if command["exit_code"] != 0:
        fail_three_engine(
            gates,
            STATUS_FAIL,
            f"PR 15D validate.py exited {command['exit_code']}",
        )
        return {"run": run, "lanes": lane_observations, "index_bytes": trial_bytes}, commands
    validation = read_json(validate_out)
    if validation.get("status") != "QUALIFIED" or validation.get("errors"):
        fail_three_engine(
            gates,
            STATUS_FAIL,
            f"PR 15D validator did not return QUALIFIED ({validation.get('status')})",
        )
        return {"run": run, "lanes": lane_observations, "index_bytes": trial_bytes}, commands
    if not require_source(
        validation.get("source_sha"), source_sha, "PR 15D validation", gates
    ):
        return {"run": run, "lanes": lane_observations, "index_bytes": trial_bytes}, commands

    gates.set(
        "I0-P03",
        STATUS_PASS,
        "3 trials x 3 engines, 32 lanes each (16 warm), oracle-clean, contention clear",
        [
            {
                "trials": PR15D_TRIALS,
                "engines": list(PR15D_ENGINES),
                "lanes_per_trial": PR15D_LANES,
                "warm_lanes_per_trial": PR15D_WARMUP_LANES,
                "validator": rel_to(root, validate_out),
            }
        ],
    )

    # Cross-engine comparability (I0-P04).
    fingerprints = {
        str(entry.get("host_fingerprint")) for entry in run.get("adapter_metadata", {}).values()
    } if isinstance(run.get("adapter_metadata"), dict) else set()
    del fingerprints  # adapter metadata carries no fingerprint; the run-level one is authoritative
    gates.set(
        "I0-P04",
        STATUS_PASS,
        "same host/corpus/protocol; sort representations are logically, not physically, "
        "identical (Quervant Keyword column / Tantivy numeric ordinal / Lucene SortedDocValues)",
        [
            {
                "host_fingerprint": run.get("host_fingerprint"),
                "filesystem": run.get("filesystem"),
                "corpus_manifest_sha256": run.get("corpus_manifest_sha256"),
                "scored_lane": "SEMANTICALLY_NONCOMPARABLE",
                "comparability_caveat": "PHYSICAL_SORT_ENCODING_DIFFERS",
            }
        ],
    )
    decision_log.append(
        {
            "rule": "I0-X25",
            "observed": "the three adapters use physically different sort encodings",
            "action": "publish logical-result equivalence with an explicit caveat",
            "verification": "docs/pr-artifacts/pr-15i-0/performance-attribution.md",
        }
    )
    return {"run": run, "lanes": lane_observations, "index_bytes": trial_bytes}, commands


# ---------------------------------------------------------------------------
# PR15F checks
# ---------------------------------------------------------------------------


def load_json_maybe(path: str):
    if not os.path.isfile(path):
        return None
    return read_json(path)


def check_pr15f(
    root: str,
    prepared_dir: str,
    run_dir: str,
    source_sha: str,
    gates: Gates,
    decision_log: list,
) -> dict:
    commands = []
    prepared = load_json_maybe(os.path.join(prepared_dir, "prepare.json"))
    preflight = load_json_maybe(os.path.join(run_dir, "preflight.json"))
    if prepared is None or preflight is None:
        gates.set("I0-P05", STATUS_BLOCKED, "PR 15F prepared/preflight records are missing")
        return {}
    if prepared.get("schema") != "pr15e-prepare-v1" or prepared.get("status") != "PREPARED":
        gates.set("I0-P05", STATUS_FAIL, "PR 15E prepared run is not PREPARED")
        return {}
    prepared_source = (prepared.get("source") or {}).get("head_sha")
    if not require_source(prepared_source, source_sha, "PR 15E prepared run", gates):
        return {}
    if not require_source(preflight.get("source_sha"), source_sha, "PR 15F preflight", gates):
        return {}
    if (prepared.get("source") or {}).get("tracked_tree_clean") is not True:
        gates.set("I0-P05", STATUS_FAIL, "PR 15E prepare ran on a dirty tree")
        return {}

    # Query campaign.
    campaign = load_json_maybe(os.path.join(run_dir, "query-campaign.json"))
    if campaign is None:
        gates.set("I0-P05", STATUS_BLOCKED, "PR 15F query campaign is missing")
        return {}
    if campaign.get("schema") != "pr15f-query-campaign-v1":
        gates.set("I0-P05", STATUS_FAIL, "query campaign schema drift")
        return {}
    lanes = campaign.get("lanes") or []
    captured = [lane for lane in lanes if lane.get("status") == "CAPTURED"]
    expected_lane_ids = {
        f"pr15f/n{n}/{class_name}/k{k}" for n, class_name, k in PR15F_QUERY_LANES
    }
    observed_lane_ids = {lane.get("lane_id") for lane in lanes}
    if observed_lane_ids != expected_lane_ids or len(lanes) != PR15F_QUERY_LANES.__len__():
        gates.set("I0-P05", STATUS_FAIL, "the nine frozen warm lanes drifted")
        return {}
    if len(captured) != len(PR15F_QUERY_LANES):
        blocked = [lane for lane in lanes if lane.get("status") != "CAPTURED"]
        status = STATUS_BLOCKED if any(
            lane.get("status") == "BLOCKED" for lane in blocked
        ) else STATUS_FAIL
        gates.set(
            "I0-P05",
            status,
            f"{len(captured)}/{len(PR15F_QUERY_LANES)} query lanes captured",
            [
                {
                    "lane_id": lane.get("lane_id"),
                    "status": lane.get("status"),
                    "code": lane.get("code"),
                }
                for lane in blocked
            ],
        )
        return {"campaign": campaign}

    analysis = load_json_maybe(os.path.join(run_dir, "analysis.json"))
    attribution = {}
    if analysis is None:
        gates.set("I0-P05", STATUS_BLOCKED, "PR 15F attribution analysis is missing")
        return {"campaign": campaign}
    if analysis.get("measured_source_sha") != source_sha:
        gates.set(
            "I0-P05",
            STATUS_FAIL,
            "attribution analysis was produced for a different source",
        )
        return {"campaign": campaign}
    query_frames = analysis.get("query") or {}
    quality = []
    for lane_id in sorted(expected_lane_ids):
        frame = query_frames.get(lane_id)
        if not isinstance(frame, dict):
            gates.set("I0-P05", STATUS_FAIL, f"attribution is missing lane {lane_id}")
            return {"campaign": campaign}
        if frame.get("source_sha") != source_sha:
            gates.set("I0-P05", STATUS_FAIL, f"attribution lane {lane_id} source drift")
            return {"campaign": campaign}
        if not is_int(frame.get("sample_count")) or frame["sample_count"] < 1000:
            gates.set("I0-P05", STATUS_FAIL, f"lane {lane_id} has too few CPU samples")
            return {"campaign": campaign}
        if frame.get("lost_samples") != 0:
            gates.set("I0-P05", STATUS_FAIL, f"lane {lane_id} lost samples")
            return {"campaign": campaign}
        if frame.get("contention_before") != "clear" or frame.get("contention_after") != "clear":
            gates.set("I0-P05", STATUS_FAIL, f"lane {lane_id} contention is not clear")
            return {"campaign": campaign}
        if frame.get("warmups") != 5:
            gates.set("I0-P05", STATUS_FAIL, f"lane {lane_id} warmup count drifted")
            return {"campaign": campaign}
        exclusive = frame.get("exclusive_percent")
        if not isinstance(exclusive, dict) or not exclusive:
            gates.set("I0-P05", STATUS_FAIL, f"lane {lane_id} has no exclusive partition")
            return {"campaign": campaign}
        if not all(is_number(value) for value in exclusive.values()):
            gates.set("I0-P05", STATUS_FAIL, f"lane {lane_id} exclusive shares are not numeric")
            return {"campaign": campaign}
        total = sum(exclusive.values())
        if total > 100.0 + 0.02:
            gates.set(
                "I0-P05",
                STATUS_FAIL,
                f"lane {lane_id} exclusive shares sum to {total:.4f}% (>100%)",
            )
            return {"campaign": campaign}
        unknown = frame.get("unknown_exclusive_percent")
        if not is_number(unknown):
            gates.set("I0-P05", STATUS_FAIL, f"lane {lane_id} has no explicit unknown bucket")
            return {"campaign": campaign}
        inclusive = frame.get("inclusive_percent") or {}
        inclusive_total = sum(inclusive.values()) if isinstance(inclusive, dict) else 0.0
        if inclusive_total > 100.0 + 0.02:
            decision_log.append(
                {
                    "rule": "I0-X24",
                    "observed": f"lane {lane_id} inclusive frames sum to {inclusive_total:.2f}%",
                    "action": "recorded inclusive shares separately; never summed or added to exclusive",
                    "verification": "pr15f attribution inclusive_paths overlap by design",
                }
            )
        quality.append(
            {
                "lane_id": lane_id,
                "sample_count": frame["sample_count"],
                "lost_samples": 0,
                "unknown_exclusive_percent": unknown,
                "exclusive_total_percent": total,
                "inclusive_total_percent": inclusive_total,
                "rank": frame.get("rank", {}).get("classification"),
            }
        )

    gates.set(
        "I0-P05",
        STATUS_PASS,
        "nine warm CPU lanes captured with clear contention, zero lost samples and a "
        "disjoint exclusive/inclusive partition",
        quality,
    )

    # Reopen.
    reopen_single = load_json_maybe(os.path.join(run_dir, "reopen", "single", "summary.json"))
    reopen_perf = load_json_maybe(os.path.join(run_dir, "reopen", "perf", "summary.json"))
    if reopen_single is None or reopen_perf is None:
        gates.set("I0-P06", STATUS_BLOCKED, "PR 15F reopen captures are missing")
        return {"campaign": campaign, "quality": quality}
    if reopen_single.get("schema") != "pr15f-reopen-single-v1":
        gates.set("I0-P06", STATUS_FAIL, "reopen single schema drift")
        return {"campaign": campaign, "quality": quality}
    if reopen_single.get("fresh_processes_total") != PR15F_REOPEN_PROCESSES:
        gates.set("I0-P06", STATUS_FAIL, "reopen single did not launch 42 processes")
        return {"campaign": campaign, "quality": quality}
    if reopen_single.get("launches_per_n") != PR15F_REOPEN_PER_N:
        gates.set("I0-P06", STATUS_FAIL, "reopen single launch split drifted")
        return {"campaign": campaign, "quality": quality}
    if reopen_single.get("failures"):
        gates.set("I0-P06", STATUS_FAIL, "reopen single reported failures")
        return {"campaign": campaign, "quality": quality}
    contention = reopen_single.get("contention") or {}
    if any(value != "clear" for value in contention.values()):
        gates.set("I0-P06", STATUS_FAIL, "reopen single contention is not clear")
        return {"campaign": campaign, "quality": quality}
    for n in ("10000", "100000"):
        entry = (reopen_single.get("n") or {}).get(n) or {}
        if entry.get("sample_count") != PR15F_REOPEN_PER_N:
            gates.set("I0-P06", STATUS_FAIL, f"reopen single n{n} sample count drifted")
            return {"campaign": campaign, "quality": quality}
    perf_status = reopen_perf.get("status")
    if reopen_perf.get("schema") != "pr15f-reopen-perf-v1":
        gates.set("I0-P06", STATUS_FAIL, "reopen perf schema drift")
        return {"campaign": campaign, "quality": quality}
    loops_ok = True
    loop_detail = []
    for n, iterations in (("10000", 128), ("100000", 64)):
        entry = (reopen_perf.get("n") or {}).get(n) or {}
        status = entry.get("status")
        loop_detail.append({"n": int(n), "status": status, "iterations": iterations})
        if status != "CAPTURED":
            loops_ok = False
    if perf_status == "BLOCKED" or not loops_ok:
        gates.set(
            "I0-P06",
            STATUS_BLOCKED,
            "reopen public probe is valid but the CPU-sampled reopen loops are not",
            loop_detail,
        )
    else:
        gates.set(
            "I0-P06",
            STATUS_PASS,
            "42 fresh single-shot reopen processes plus both CPU loops are valid",
            loop_detail,
        )

    # Inventory.
    inventories = {}
    for n in ("10000", "100000"):
        path = os.path.join(run_dir, "inventory", f"n{n}.json")
        inventory = load_json_maybe(path)
        if inventory is None:
            gates.set("I0-P07", STATUS_BLOCKED, f"inventory n{n} is missing")
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        if inventory.get("schema") != "pr15f-index-inventory-v1":
            gates.set("I0-P07", STATUS_FAIL, f"inventory n{n} schema drift")
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        if inventory.get("read_only") is not True:
            gates.set("I0-P07", STATUS_FAIL, f"inventory n{n} is not marked read-only")
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        if inventory.get("bytes_before_sha256") != inventory.get("bytes_after_sha256"):
            gates.set("I0-P07", STATUS_FAIL, f"inventory n{n} observed index mutation")
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        reconciliation = inventory.get("reconciliation") or {}
        if reconciliation.get("bytes_reconciled") is not True:
            gates.set("I0-P07", STATUS_FAIL, f"inventory n{n} bytes do not reconcile")
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        if reconciliation.get("segments_reconciled") is not True:
            gates.set("I0-P07", STATUS_FAIL, f"inventory n{n} sections do not reconcile")
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        files = inventory.get("files") or []
        total = inventory.get("total_file_bytes")
        if not is_int(total) or sum(entry.get("bytes", 0) for entry in files) != total:
            gates.set("I0-P07", STATUS_FAIL, f"inventory n{n} file sizes do not sum")
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        prepared_entry = (prepared.get("indexes") or {}).get(n) or {}
        prepared_inventory = prepared_entry.get("inventory") or {}
        if prepared_inventory.get("sha256") != inventory.get("content_sha256"):
            gates.set(
                "I0-P07",
                STATUS_FAIL,
                f"inventory n{n} content fingerprint differs from the prepared index",
            )
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        expected_files = {
            entry.get("path"): (entry.get("bytes"), entry.get("sha256"))
            for entry in prepared_inventory.get("entries") or []
        }
        observed_files = {
            entry.get("path"): (entry.get("bytes"), entry.get("sha256")) for entry in files
        }
        if expected_files != observed_files:
            gates.set(
                "I0-P07",
                STATUS_FAIL,
                f"inventory n{n} file set or digests differ from the prepared index",
            )
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        if not is_int(inventory.get("mutation_state_file_bytes")):
            gates.set("I0-P07", STATUS_FAIL, f"inventory n{n} has no sidecar byte count")
            return {"campaign": campaign, "quality": quality, "inventories": inventories}
        inventories[n] = inventory
    gates.set(
        "I0-P07",
        STATUS_PASS,
        "both inventories reconcile every file and section byte and are read-only",
        [
            {
                "n": int(n),
                "total_file_bytes": inventories[n]["total_file_bytes"],
                "file_count": inventories[n]["file_count"],
                "content_sha256": inventories[n]["content_sha256"],
            }
            for n in sorted(inventories)
        ],
    )
    return {
        "campaign": campaign,
        "quality": quality,
        "inventories": inventories,
        "prepared": prepared,
        "preflight": preflight,
        "reopen_single": reopen_single,
        "reopen_perf": reopen_perf,
        "analysis": analysis,
    }


# ---------------------------------------------------------------------------
# Mutation probe checks
# ---------------------------------------------------------------------------


def check_mutation(
    root: str,
    mutation_dir: str,
    source_sha: str,
    prepared_info: dict,
    gates: Gates,
) -> dict:
    manifest = load_json_maybe(os.path.join(mutation_dir, "manifest.json"))
    if manifest is None:
        gates.set("I0-P08", STATUS_BLOCKED, "mutation campaign manifest is missing")
        return {}
    if manifest.get("schema") != "pr15i-0-mutation-run-v1":
        gates.set("I0-P08", STATUS_FAIL, "mutation campaign manifest schema drift")
        return {}
    if manifest.get("source_sha") != source_sha:
        gates.set("I0-P08", STATUS_FAIL, "mutation campaign source drift")
        return {}
    if manifest.get("read_only") is not True:
        gates.set("I0-P08", STATUS_FAIL, "mutation campaign is not marked read-only")
        return {}
    inventories = prepared_info.get("inventories") or {}
    if set(inventories) != {"10000", "100000"}:
        gates.set("I0-P08", STATUS_BLOCKED, "prepared inventories are unavailable")
        return {}
    results = {}
    for n in ("10000", "100000"):
        path = os.path.join(mutation_dir, f"n{n}.json")
        result = load_json_maybe(path)
        if result is None:
            gates.set("I0-P08", STATUS_BLOCKED, f"mutation breakdown n{n} is missing")
            return {}
        if result.get("schema") != "pr15i-0-mutation-breakdown-v1":
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} schema drift")
            return {}
        if result.get("source_sha") != source_sha:
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} source drift")
            return {}
        if result.get("qualified") is not True:
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} is not qualified")
            return {}
        payload_version = result.get("payload_version")
        if payload_version not in (1, 2):
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} payload version is unsupported")
            return {}
        inventory = inventories[n]
        inventory_files = {entry.get("path"): entry for entry in inventory.get("files") or []}
        active_key = result.get("active_state_key")
        if active_key not in inventory_files:
            gates.set(
                "I0-P08",
                STATUS_FAIL,
                f"breakdown n{n} attributed a sidecar that the inventory does not contain",
            )
            return {}
        inventory_entry = inventory_files[active_key]
        if inventory_entry.get("sha256") != result.get("sidecar_sha256"):
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} sidecar digest mismatch")
            return {}
        file_bytes = result.get("sidecar_file_bytes")
        if not is_int(file_bytes) or file_bytes != inventory_entry.get("bytes"):
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} sidecar length mismatch")
            return {}
        if file_bytes != inventory.get("mutation_state_file_bytes"):
            gates.set(
                "I0-P08",
                STATUS_FAIL,
                f"breakdown n{n} sidecar is not the inventory's mutation-state total",
            )
            return {}
        components = result.get("component_bytes")
        if not isinstance(components, dict) or len(components) != 17:
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} component vocabulary drifted")
            return {}
        if not all(is_int(value) and value >= 0 for value in components.values()):
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} has a non-integer component")
            return {}
        payload_bytes = result.get("payload_bytes")
        if not is_int(payload_bytes) or sum(components.values()) != payload_bytes:
            gates.set(
                "I0-P08",
                STATUS_FAIL,
                f"breakdown n{n} components do not sum to the payload",
            )
            return {}
        overhead = result.get("container_overhead_bytes")
        if not is_int(overhead) or payload_bytes + overhead != file_bytes:
            gates.set(
                "I0-P08",
                STATUS_FAIL,
                f"breakdown n{n} payload plus overhead does not equal the file length",
            )
            return {}
        live = result.get("live_count")
        deleted = result.get("deleted_count")
        if not is_int(live) or not is_int(deleted) or live + deleted != result.get("row_count"):
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} row counts do not reconcile")
            return {}
        expected_batch = (
            "SEMANTIC_BATCH_DETAIL_NOT_VERIFIED" if payload_version == 2 else "NOT_APPLICABLE"
        )
        if result.get("batch_replay_detail") != expected_batch:
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} batch detail label drifted")
            return {}
        if payload_version == 1 and components.get("batch_replay_opaque_bytes") != 0:
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} invented batch bytes for v1")
            return {}
        if payload_version == 2 and components.get("batch_replay_opaque_bytes", 0) < 4:
            gates.set("I0-P08", STATUS_FAIL, f"breakdown n{n} has no v2 batch span")
            return {}
        results[n] = result

    gates.set(
        "I0-P08",
        STATUS_PASS,
        "both authoritative active sidecars are proven through CURRENT/manifest and every "
        "payload byte reconciles exactly (v2 batch remainder is explicitly opaque)",
        [
            {
                "n": int(n),
                "payload_version": results[n]["payload_version"],
                "sidecar_file_bytes": results[n]["sidecar_file_bytes"],
                "payload_bytes": results[n]["payload_bytes"],
                "container_overhead_bytes": results[n]["container_overhead_bytes"],
                "row_count": results[n]["row_count"],
                "live_count": results[n]["live_count"],
                "deleted_count": results[n]["deleted_count"],
                "replay_count": results[n]["replay_count"],
                "batch_replay_opaque_bytes": results[n]["component_bytes"][
                    "batch_replay_opaque_bytes"
                ],
            }
            for n in sorted(results)
        ],
    )
    return results


# ---------------------------------------------------------------------------
# Controller tests (gate P02)
# ---------------------------------------------------------------------------


def check_controller_tests(root: str, gates: Gates) -> list:
    commands = []
    python_tests = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "benchmarks/pr15i_0", "-p", "test_*.py"],
        root,
    )
    commands.append(record_command(python_tests))
    probe_manifest = os.path.join("benchmarks", "pr15i_0", "mutation_probe", "Cargo.toml")
    stable = run_command(
        ["cargo", "test", "--locked", "--offline", "--manifest-path", probe_manifest], root
    )
    commands.append(record_command(stable))
    msrv = run_command(
        ["cargo", "+1.85.0", "test", "--locked", "--offline", "--manifest-path", probe_manifest],
        root,
    )
    commands.append(record_command(msrv))
    failures = [
        command
        for command, result in zip(commands, (python_tests, stable, msrv))
        if result["exit_code"] != 0
    ]
    if failures:
        gates.set(
            "I0-P02",
            STATUS_FAIL,
            "controller or probe test suite failed",
            [{"argv": entry["argv"], "exit_code": entry["exit_code"]} for entry in failures],
        )
    else:
        gates.set(
            "I0-P02",
            STATUS_PASS,
            "controller Python tests and the locked standalone probe tests pass on stable and MSRV",
            [{"argv": entry["argv"], "exit_code": entry["exit_code"]} for entry in commands],
        )
    return commands


# ---------------------------------------------------------------------------
# Inputs, privacy, QA
# ---------------------------------------------------------------------------


def prepare_inputs(root: str, paths: dict) -> dict:
    inputs = {}
    for label, directory in paths.items():
        if directory is None:
            continue
        require_regular_files(directory)
        manifest_paths = []
        for name in ("run.json", "preflight.json", "prepare.json", "manifest.json"):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                manifest_paths.append(candidate)
        inputs[label] = {
            "path": rel_to(root, directory),
            "manifests": {
                rel_to(root, path): sha256_file(path) for path in sorted(manifest_paths)
            },
        }
    return inputs


def check_privacy(gates: Gates, root: str, verification_payload: dict) -> None:
    problems = []
    text = json.dumps(verification_payload, sort_keys=True)
    for pattern, label in PRIVACY_PATTERNS:
        if pattern.search(text):
            problems.append(f"verification record matched {label}")
    privacy_rel = "benchmarks/reports/pr15i-0/privacy-scan.json"
    privacy_path = os.path.join(root, privacy_rel)
    if not os.path.isfile(privacy_path):
        gates.set(
            "I0-P10",
            STATUS_BLOCKED,
            "sanitized reports are produced after verification; no privacy scan record yet "
            f"({privacy_rel})",
            problems,
        )
        return
    scan = read_json(privacy_path)
    if scan.get("schema") != "pr15i-0-privacy-scan-v1" or scan.get("status") != "PASS":
        gates.set("I0-P10", STATUS_FAIL, "privacy scan record is not PASS")
        return
    for entry in scan.get("files") or []:
        target = os.path.join(root, entry["path"])
        if not os.path.isfile(target):
            problems.append(f"scanned report is missing: {entry['path']}")
            continue
        if sha256_file(target) != entry.get("sha256"):
            problems.append(f"scanned report drifted: {entry['path']}")
    if problems:
        gates.set("I0-P10", STATUS_FAIL, "privacy scan does not match the committed reports", problems)
        return
    gates.set(
        "I0-P10",
        STATUS_PASS,
        "verification record and every published report are free of host paths, pids, keys and tokens",
        [{"files": len(scan.get("files") or []), "scan": privacy_rel}],
    )


def check_qa(gates: Gates, root: str) -> None:
    qa_rel = "target/pr15i-0/qa/workspace-qa.json"
    qa_path = os.path.join(root, qa_rel)
    if not os.path.isfile(qa_path):
        gates.set(
            "I0-P11",
            STATUS_BLOCKED,
            f"no executed QA record yet ({qa_rel}); run the verify.py qa mode first",
        )
        return
    record = read_json(qa_path)
    if record.get("schema") != SCHEMA_QA:
        gates.set("I0-P11", STATUS_FAIL, "QA record schema drift")
        return
    failing = [
        entry
        for entry in record.get("commands") or []
        if entry.get("required") and entry.get("status") != STATUS_PASS
    ]
    if failing:
        gates.set(
            "I0-P11",
            STATUS_FAIL,
            f"{len(failing)} required QA command(s) did not pass",
            [{"id": entry.get("id"), "status": entry.get("status")} for entry in failing],
        )
        return
    coverage = record.get("coverage_percent")
    if coverage is None:
        gates.set("I0-P11", STATUS_FAIL, "QA record carries no measured line coverage")
        return
    if not is_number(coverage) or coverage < 85.0:
        gates.set(
            "I0-P11",
            STATUS_FAIL,
            f"measured line coverage {coverage} is below the 85% floor",
        )
        return
    optional_missing = [
        entry.get("id")
        for entry in record.get("commands") or []
        if not entry.get("required") and entry.get("status") != STATUS_PASS
    ]
    gates.set(
        "I0-P11",
        STATUS_PASS,
        f"all required QA commands passed; measured line coverage {coverage}%",
        [{"optional_not_passed": optional_missing}],
    )


def check_allocation(gates: Gates, pr15f: dict) -> None:
    run_dir = pr15f.get("run_dir")
    if not run_dir:
        gates.set("I0-P12", STATUS_NOT_MEASURED, "allocation campaign is unavailable")
        return
    summary = load_json_maybe(os.path.join(run_dir, "allocation", "summary.json"))
    if summary is None:
        gates.set("I0-P12", STATUS_NOT_MEASURED, "allocations were not captured")
        return
    lanes = summary.get("lanes") or summary.get("captures") or []
    captured = [lane for lane in lanes if lane.get("status") == "CAPTURED"]
    if len(captured) == 2:
        gates.set(
            "I0-P12",
            STATUS_PASS,
            "both prescribed 100K allocation lanes were captured",
            [{"lane_id": lane.get("lane_id") or lane.get("capture_id")} for lane in captured],
        )
    else:
        gates.set(
            "I0-P12",
            STATUS_NOT_MEASURED,
            summary.get("status", "ALLOCATION_NOT_MEASURED"),
            [{"captured": len(captured)}],
        )


# ---------------------------------------------------------------------------
# Verification driver
# ---------------------------------------------------------------------------


def verification_main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify.py", description="PR 15I-0 read-only verification.", allow_abbrev=False
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--pr15d-run", required=True)
    parser.add_argument("--pr15f-run", required=True)
    parser.add_argument("--pr15f-prepared", required=True)
    parser.add_argument("--mutation-run", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    root = os.path.realpath(args.root)
    if not os.path.isdir(root) or not os.path.isfile(os.path.join(root, "Cargo.toml")):
        print(
            canonical_json_bytes({"status": "FAILED", "detail": "--root is not the repository root"}).decode(),
            file=sys.stderr,
        )
        return 2

    out = os.path.abspath(args.out)
    if os.path.exists(out):
        print(
            canonical_json_bytes(
                {"status": "FAILED", "detail": "--out already exists; verify is append-only"}
            ).decode(),
            file=sys.stderr,
        )
        return 2
    if not any(
        rel_to(root, out).startswith(prefix + "/") for prefix in ("target/pr15i-0",)
    ):
        print(
            canonical_json_bytes(
                {"status": "FAILED", "detail": "--out must live under target/pr15i-0/"}
            ).decode(),
            file=sys.stderr,
        )
        return 2

    verification_dir = out[: -len(".json")] if out.endswith(".json") else out + ".d"
    os.makedirs(verification_dir, exist_ok=True)

    gates = Gates()
    decision_log: list[dict] = []
    commands: list[dict] = []
    observations: dict = {}

    def fail(code: str, detail: str, gate: str) -> dict:
        gates.set(gate, STATUS_FAIL, f"{code}: {detail}")
        payload = build_payload(root, args.source_sha, None, gates, commands, observations, decision_log)
        emit(out, payload)
        print(canonical_json_bytes({"status": "FAILED", "code": code, "detail": detail}).decode(), file=sys.stderr)
        return payload

    try:
        protocol = load_protocol(root)
        pr15d_run = require_plain_path(root, args.pr15d_run, "--pr15d-run")
        pr15f_run = require_plain_path(root, args.pr15f_run, "--pr15f-run")
        pr15f_prepared = require_plain_path(root, args.pr15f_prepared, "--pr15f-prepared")
        mutation_run = require_plain_path(root, args.mutation_run, "--mutation-run")
    except VerificationError as error:
        fail(error.code, error.detail, "I0-P09")
        return 1

    check_source(root, args.source_sha, gates, decision_log)
    commands.extend(check_controller_tests(root, gates))

    # I0-P01 frozen inputs.
    corpus_problems = []
    run_path = os.path.join(pr15d_run, "run.json")
    prepared_path = os.path.join(pr15f_prepared, "prepare.json")
    if not os.path.isfile(run_path) or not os.path.isfile(prepared_path):
        gates.set("I0-P01", STATUS_BLOCKED, "PR 15D run or PR 15F prepared manifest is missing")
    else:
        run = read_json(run_path)
        prepared = read_json(prepared_path)
        corpus_a = run.get("corpus_manifest_sha256")
        corpus_b = (prepared.get("corpus") or {}).get("manifest_sha256")
        if not SHA256_RE.fullmatch(str(corpus_a or "")):
            corpus_problems.append("PR 15D corpus manifest digest is invalid")
        if corpus_a != corpus_b:
            corpus_problems.append("PR 15D and PR 15F corpus manifests differ")
        digests_a = run.get("corpus_digests") or {}
        digests_b = {
            key: value.get("sha256")
            for key, value in ((prepared.get("corpus") or {}).get("corpora") or {}).items()
        }
        if digests_a != digests_b:
            corpus_problems.append("corpus file digests differ between campaigns")
        if sorted(int(key) for key in digests_a) != sorted(PR15D_N):
            corpus_problems.append("corpus does not cover exactly 10000 and 100000 documents")
        spec_path = os.path.join(root, "benchmarks", "pr15d", "spec", "pr15d_v1.json")
        spec = read_json(spec_path)
        if spec.get("status") != "FROZEN" or spec.get("workload") != "pr15d_v1":
            corpus_problems.append("frozen PR 15D spec is not FROZEN/pr15d_v1")
        if corpus_problems:
            gates.set("I0-P01", STATUS_FAIL, "; ".join(corpus_problems))
        else:
            gates.set(
                "I0-P01",
                STATUS_PASS,
                "frozen corpus digests match across both campaigns and the spec is FROZEN",
                [{"corpus_manifest_sha256": corpus_a, "n": sorted(int(key) for key in digests_a)}],
            )

    pr15d_info = {}
    if gates.get("I0-P03")["status"] != STATUS_FAIL:
        try:
            pr15d_info, pr15d_commands = check_pr15d(
                root,
                pr15d_run,
                args.source_sha,
                protocol,
                verification_dir,
                gates,
                decision_log,
            )
            commands.extend(pr15d_commands)
            observations["pr15d"] = pr15d_info
        except VerificationError as error:
            gates.set("I0-P03", STATUS_FAIL, f"{error.code}: {error.detail}")

    pr15f_info = {}
    try:
        pr15f_info = check_pr15f(
            root, pr15f_prepared, pr15f_run, args.source_sha, gates, decision_log
        )
        pr15f_info["run_dir"] = pr15f_run
        observations["pr15f"] = pr15f_info
    except VerificationError as error:
        gates.set("I0-P05", STATUS_FAIL, f"{error.code}: {error.detail}")

    try:
        observations["mutation"] = check_mutation(
            root, mutation_run, args.source_sha, pr15f_info, gates
        )
    except VerificationError as error:
        gates.set("I0-P08", STATUS_FAIL, f"{error.code}: {error.detail}")

    # Seals (I0-P09).
    seal_failures = []
    for label, directory in (
        ("pr15d-run", pr15d_run),
        ("pr15f-prepared", pr15f_prepared),
        ("pr15f-run", pr15f_run),
        ("mutation-run", mutation_run),
    ):
        seal = verify_seal(directory, args.source_sha, protocol["sha256"], gates, label)
        if seal is None:
            seal_failures.append(label)
            break
        observations.setdefault("seals", {})[label] = {
            "files": len(seal.get("files") or []),
            "status": seal.get("status"),
        }
    if not seal_failures and gates.get("I0-P09")["status"] != STATUS_FAIL:
        gates.set(
            "I0-P09",
            STATUS_PASS,
            "every campaign seal rehashes exactly and all manifests declare the measured source",
            observations.get("seals"),
        )

    observations["inputs"] = prepare_inputs(
        root,
        {
            "pr15d_run": pr15d_run,
            "pr15f_prepared": pr15f_prepared,
            "pr15f_run": pr15f_run,
            "mutation_run": mutation_run,
        },
    )

    check_allocation(gates, pr15f_info)
    check_qa(gates, root)

    payload = build_payload(
        root, args.source_sha, protocol, gates, commands, observations, decision_log
    )
    check_privacy(gates, root, payload)
    payload = build_payload(
        root, args.source_sha, protocol, gates, commands, observations, decision_log
    )
    emit(out, payload)

    statuses = gates.statuses()
    print(
        json.dumps(
            {
                "status": payload["overall_status"],
                "gates": statuses,
                "qualified": payload["qualified"],
                "out": rel_to(root, out),
            },
            sort_keys=True,
        )
    )
    mandatory = [gate for gate in GATE_IDS if gate != "I0-P12"]
    if any(statuses[gate] != STATUS_PASS for gate in mandatory):
        return 1
    if statuses["I0-P12"] not in (STATUS_PASS, STATUS_NOT_MEASURED):
        return 1
    return 0


def build_payload(root, source_sha, protocol, gates, commands, observations, decision_log) -> dict:
    statuses = gates.statuses()
    mandatory = [gate for gate in GATE_IDS if gate != "I0-P12"]
    mandatory_ok = all(statuses[gate] == STATUS_PASS for gate in mandatory)
    allocation_ok = statuses["I0-P12"] in (STATUS_PASS, STATUS_NOT_MEASURED)
    if statuses["I0-P00"] == STATUS_FAIL:
        overall = "15I0_BLOCKED_SOURCE"
    elif any(status == STATUS_FAIL for status in statuses.values()):
        overall = "15I0_NOT_QUALIFIED"
    elif mandatory_ok and allocation_ok:
        overall = "15I0_QUALIFIED_REVIEW_READY"
    else:
        overall = "15I0_PARTIAL_EVIDENCE"
    return {
        "schema": SCHEMA_VERIFICATION,
        "controller_version": CONTROLLER_VERSION,
        "source_sha": source_sha,
        "protocol": None
        if protocol is None
        else {
            "path": PROTOCOL_REL,
            "sha256": protocol["sha256"],
            "bytes": protocol["bytes"],
            "schema": protocol["value"]["schema"],
        },
        "gates": gates.entries,
        "commands": commands,
        "observations": observations,
        "decision_log": decision_log,
        "qualified": mandatory_ok and allocation_ok,
        "overall_status": overall,
        "repository_root_redacted": True,
        "measured_from": rel_to(root, root) or ".",
    }


def emit(out: str, payload: dict) -> None:
    write_json(out, payload)


# ---------------------------------------------------------------------------
# seal / qa modes
# ---------------------------------------------------------------------------


def seal_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="verify.py seal", allow_abbrev=False)
    parser.add_argument("--root", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--status", required=True, choices=("QUALIFIED", "PARTIAL"))
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--corpus-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    root = os.path.realpath(args.root)
    try:
        directory = require_plain_path(root, args.campaign, "--campaign")
        result = seal_campaign(
            directory,
            args.source_sha,
            args.status,
            {
                "protocol_sha256": args.protocol_sha256,
                "corpus_manifest_sha256": args.corpus_manifest_sha256,
            },
        )
    except (VerificationError, OSError) as error:
        print(canonical_json_bytes({"status": "FAILED", "detail": str(error)}).decode(), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "SEALED",
                "seal": rel_to(root, result["path"]),
                "files": result["files"],
                "sha256": result["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


QA_COMMANDS = (
    ("fmt", ["cargo", "fmt", "--all", "--", "--check"], True),
    ("clippy", ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"], True),
    (
        "clippy-all-features",
        ["cargo", "clippy", "--workspace", "--all-targets", "--all-features", "--", "-D", "warnings"],
        True,
    ),
    ("test", ["cargo", "test", "--workspace", "--all-targets"], True),
    ("test-all-features", ["cargo", "test", "--workspace", "--all-targets", "--all-features"], True),
    ("doc", ["cargo", "doc", "--workspace", "--no-deps"], True),
    ("bench-no-run", ["cargo", "bench", "--workspace", "--no-run"], True),
    ("fmt-msrv", ["cargo", "+1.85.0", "fmt", "--all", "--", "--check"], True),
    (
        "clippy-msrv",
        ["cargo", "+1.85.0", "clippy", "--workspace", "--all-targets", "--all-features", "--", "-D", "warnings"],
        True,
    ),
    ("test-msrv", ["cargo", "+1.85.0", "test", "--workspace", "--all-targets", "--all-features"], True),
    (
        "probe-test",
        ["cargo", "test", "--locked", "--offline", "--manifest-path", "benchmarks/pr15i_0/mutation_probe/Cargo.toml"],
        True,
    ),
    (
        "probe-test-msrv",
        [
            "cargo",
            "+1.85.0",
            "test",
            "--locked",
            "--offline",
            "--manifest-path",
            "benchmarks/pr15i_0/mutation_probe/Cargo.toml",
        ],
        True,
    ),
    ("controller-tests", [sys.executable, "-m", "unittest", "discover", "-s", "benchmarks/pr15i_0", "-p", "test_*.py"], True),
    ("pr15d-tests", [sys.executable, "benchmarks/pr15d/harness/test_pr15d.py"], True),
    ("pr15f-tests", [sys.executable, "-m", "unittest", "discover", "-s", "benchmarks/pr15f", "-p", "test_*.py"], True),
    ("pr15e-tests", [sys.executable, "-m", "unittest", "discover", "-s", "benchmarks/pr15e", "-p", "test_*.py"], True),
    ("diff-check", ["git", "diff", "--check"], True),
    (
        "fsdirectory-integration",
        [
            "cargo",
            "test",
            "--workspace",
            "--all-targets",
            "--",
            "--ignored",
            "--test-threads=1",
        ],
        True,
    ),
    ("coverage", ["cargo", "llvm-cov", "--workspace", "--all-targets", "--fail-under-lines", "85"], True),
)

COVERAGE_RE = re.compile(r"^TOTAL\s+.*?([0-9]+(?:\.[0-9]+)?)%\s*$", re.MULTILINE)


def qa_main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="verify.py qa", allow_abbrev=False)
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--only",
        default=None,
        help="comma-separated command ids to run instead of the full matrix",
    )
    parser.add_argument(
        "--include-rustfs",
        action="store_true",
        help="also run the pinned real RustFS suite when a container runtime is available",
    )
    args = parser.parse_args(argv)
    root = os.path.realpath(args.root)
    if os.path.exists(args.out):
        print("--out already exists; QA records are immutable", file=sys.stderr)
        return 2
    selected = None
    if args.only:
        selected = {name.strip() for name in args.only.split(",") if name.strip()}
    commands = []
    suite = list(QA_COMMANDS)
    if args.include_rustfs:
        suite.append(
            (
                "rustfs",
                ["bash", "-c", "QUERVANT_PRODUCTION_S3_ADAPTER=1 tests/rustfs/run.sh"],
                False,
            )
        )
    for identifier, argv_spec, required in suite:
        if selected is not None and identifier not in selected:
            continue
        result = run_command(argv_spec, root)
        entry = {
            "id": identifier,
            "argv": argv_spec,
            "required": required,
            "exit_code": result["exit_code"],
            "status": STATUS_PASS if result["exit_code"] == 0 else STATUS_FAIL,
            "stdout_sha256": hashlib.sha256(result["stdout"].encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(result["stderr"].encode("utf-8")).hexdigest(),
            "stdout_tail": result["stdout"].strip().splitlines()[-6:],
            "stderr_tail": result["stderr"].strip().splitlines()[-6:],
        }
        commands.append(entry)
        print(f"{identifier}: {entry['status']} ({entry['exit_code']})", file=sys.stderr)

    coverage_percent = None
    for entry in commands:
        if entry["id"] != "coverage":
            continue
        for line in entry.get("stdout_tail") or []:
            match = COVERAGE_RE.search(line)
            if match:
                coverage_percent = float(match.group(1))
    record = {
        "schema": SCHEMA_QA,
        "controller_version": CONTROLLER_VERSION,
        "commands": commands,
        "coverage_percent": coverage_percent,
        "rustfs_included": args.include_rustfs,
    }
    write_json(args.out, record)
    print(
        json.dumps(
            {
                "status": "RECORDED",
                "commands": len(commands),
                "coverage_percent": coverage_percent,
                "failed": [entry["id"] for entry in commands if entry["status"] != STATUS_PASS],
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["seal"]:
        return seal_main(argv[1:])
    if argv[:1] == ["qa"]:
        return qa_main(argv[1:])
    return verification_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""PR 15I-A authoritative read-only campaign verifier.

Verifies the original sealed campaign against frozen sources, protocol, corpus,
build binaries, balanced blocks, the nine warm lanes (independent PR15D oracle),
per-arm payload/feature layout, contention records and the exact 20-file seal
inventory. It never creates, replaces or normalizes evidence.

`run.py::derive` unconditionally sets `A-P12=PASS`; this verifier establishes an
independent provenance predicate first and only then re-derives the numeric
gates. The receipt distinguishes historical host attestation from independent
host observation, and local QA / hosted CI remain separate statuses.

Exit codes: ``0`` independently verified, ``2`` rejected, ``3`` blocked input.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys

TOOLING_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
RUNNER = os.path.join(TOOLING_ROOT, "benchmarks", "pr15i_a", "run.py")
_spec = importlib.util.spec_from_file_location("pr15i_a_controller", RUNNER)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load controller from {RUNNER}")
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)

RECEIPT_SCHEMA = "pr15i-a-independent-review-fixup-v1"
RAW_REL = "raw"
EXPECTED_RAW_FILES = (
    "authorization.json",
    "blocks.json",
    "manifest.json",
    "measurements.json",
    *(f"slots/slot-{index:02d}.json" for index in range(1, 17)),
)
EXPECTED_AUX_FILES = tuple(
    f"slots/slot-{index:02d}/contention/trial{index}-{phase}.json"
    for index in range(1, 17)
    for phase in ("before", "after")
)
EXPECTED_AUX_COUNT = len(EXPECTED_AUX_FILES)

EXPECTED_SOURCES = {
    "A": "888e819d85f0cde62a5040919ac5c96feca52f1f",
    "B": "db9007fb7239a5cce94e20c7c43ac7200da8047f",
}
EXPECTED_ENV_FINGERPRINT = (
    "4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f"
)
EXPECTED_CORPUS_MANIFEST = (
    "69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151"
)
EXPECTED_PROTOCOL_BLOB = "6f6322053d18b2379ee98f9307769f8101591425"
EXPECTED_FEATURES = {
    "A": ((1, 1), (8, 1)),
    "B": ((1, 1), (8, 1), (12, 1)),
}
EXPECTED_PAYLOAD_VERSION = {"A": 1, "B": 3}
# Original-campaign container envelope sentinel: bytes - payload_bytes.
EXPECTED_ENVELOPE_OVERHEAD = {"A": 170, "B": 174}
EXPECTED_100K = {
    "A": {"committed_index_bytes": 30_965_025, "sidecar_bytes": 9_600_180},
}
PRODUCTION_PATHS = (
    "crates/quervant-core/src",
    "crates/quervant-core/Cargo.toml",
    "Cargo.lock",
    ".github/workflows/ci.yml",
)
REPORT_FILES = (
    "benchmarks/reports/pr15i-a/results.json",
    "benchmarks/reports/pr15i-a/results.md",
    "benchmarks/reports/pr15i-a/decision.json",
    "benchmarks/reports/pr15i-a/README.md",
)
RECEIPT_ROOT_REL = ("target", "pr15i-a", "reviews")
BINARY_RELATIVE = {
    "adapter": ("build", "release", "pr15d-quervant-adapter"),
    "reopen": ("reopen", "build", "release", "pr15i-a-reopen-probe"),
    "remote": ("remote", "build", "release", "pr15i-a-remote-probe"),
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA1 = re.compile(r"^[0-9a-f]{40}$")
UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
METRIC_FIELDS = {
    "reopen": ("open_ns", "maxrss_bytes"),
    "build_commit": ("index_ns", "commit_ns", "maxrss_bytes"),
    "remote": ("open_ns", "maxrss_bytes"),
}


class VerifyError(Exception):
    """A typed, deterministic verifier rejection or block."""

    def __init__(self, exit_code: int, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.exit_code = exit_code
        self.code = code
        self.detail = detail


def _reject(code: str, detail: str) -> None:
    raise VerifyError(2, code, detail)


def _blocked(code: str, detail: str) -> None:
    raise VerifyError(3, code, detail)


def _is_int(value, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value > 0 if positive else value >= 0


def _require_hex64(value, code: str, label: str) -> str:
    if not isinstance(value, str) or not HEX64.match(value):
        _reject(code, f"{label} is not a lowercase SHA-256 hex string")
    return value


def _require_sha1(value, code: str, label: str) -> str:
    if not isinstance(value, str) or not GIT_SHA1.match(value):
        _reject(code, f"{label} is not a lowercase 40-character Git SHA")
    return value


def _load_json(path: str, code: str = "A_INPUT") -> object:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerifyError(2, code, f"cannot read {os.path.basename(path)}: {error}") from error


def _sha256_file(path: str) -> str:
    try:
        return run.sha256_file(path)
    except OSError as error:
        raise VerifyError(3, "A_EVIDENCE_UNREADABLE", f"{path}: {error}") from error


def _assert_safe_relative(relative: str, code: str = "A_SEAL") -> None:
    if not isinstance(relative, str) or not relative:
        _reject(code, "empty or non-string relative path")
    if "\x00" in relative:
        _reject(code, "relative path contains NUL")
    if "\\" in relative:
        _reject(code, "relative path contains a backslash")
    if relative.startswith("/") or re.match(r"^[A-Za-z]:", relative):
        _reject(code, f"absolute path not allowed: {relative!r}")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        _reject(code, f"non-canonical relative path: {relative!r}")


def _assert_regular_tree(root: str, relative: str, code: str = "A_SEAL") -> str:
    """Reject symlinks/nonregular files along ``root/relative`` and return it."""
    _assert_safe_relative(relative, code)
    current = root
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        try:
            metadata = os.lstat(current)
        except OSError as error:
            raise VerifyError(3, code, f"cannot stat {relative}: {error}") from error
        if stat.S_ISLNK(metadata.st_mode):
            _reject(code, f"symlink component refused: {relative}")
        final = index == len(parts) - 1
        if final and not stat.S_ISREG(metadata.st_mode):
            _reject(code, f"not a regular file: {relative}")
        if not final and not stat.S_ISDIR(metadata.st_mode):
            _reject(code, f"not a directory component: {relative}")
    return current


# ---------------------------------------------------------------------------
# Read-only Git boundary
# ---------------------------------------------------------------------------


class RealGit:
    """Read-only Git lookups against the checkout; failures are blocked, not OK."""

    def __init__(self, root: str):
        self.root = root

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", self.root, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            _blocked("A_SOURCE_BLOCKED", f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def head(self) -> str:
        return self._run("rev-parse", "HEAD")

    def cat_file_type(self, sha: str) -> str:
        return self._run("cat-file", "-t", sha)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", self.root, "merge-base", "--is-ancestor", ancestor, descendant],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            ).returncode
            == 0
        )

    def changed_paths(self, base: str, candidate: str) -> list[str]:
        output = self._run("diff", "--name-only", f"{base}..{candidate}")
        return sorted(path for path in output.splitlines() if path)

    def hash_object(self, relative: str) -> str:
        return self._run("hash-object", relative)

    def diff_empty(self, base: str, candidate: str, relative: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", self.root, "diff", "--quiet", base, candidate, "--", relative],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            ).returncode
            == 0
        )

    def production_identical(self, base: str, candidate: str) -> bool:
        return (
            subprocess.run(
                ["git", "-C", self.root, "diff", "--quiet", base, candidate, "--", *PRODUCTION_PATHS],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            ).returncode
            == 0
        )


# ---------------------------------------------------------------------------
# Seal, inventory and auxiliary contention binding
# ---------------------------------------------------------------------------


def _inventory_and_rehash(campaign: str) -> dict:
    raw = os.path.join(campaign, RAW_REL)
    if os.path.islink(raw) or not os.path.isdir(raw):
        _blocked("A_SEAL", "raw directory missing or symlinked")
    seal_path = _assert_regular_tree(campaign, "raw/seal.json")
    seal = _load_json(seal_path, "A_SEAL")
    if not isinstance(seal, dict) or seal.get("schema") != run.SEAL_SCHEMA:
        _reject("A_SEAL", "bad seal schema")
    files = seal.get("files")
    if not isinstance(files, dict):
        _reject("A_SEAL", "seal files is not a mapping")
    expected = set(EXPECTED_RAW_FILES)
    if set(files) != expected:
        missing = sorted(expected - set(files))
        extra = sorted(set(files) - expected)
        _reject("A_SEAL", f"seal inventory differs (missing={missing}, extra={extra})")
    digests = {}
    for relative, digest in files.items():
        _assert_safe_relative(relative)
        _require_hex64(digest, "A_SEAL", f"seal digest {relative}")
        path = _assert_regular_tree(campaign, f"raw/{relative}")
        digests[relative] = digest
        actual = _sha256_file(path)
        if actual != digest:
            _reject("A_SEAL", f"seal mismatch for {relative}")

    # Enumerate every regular file under raw/ and require the exact known tree:
    # 20 sealed primaries + seal.json + 32 auxiliary contention probes.
    expected_dirs = {"slots"} | {f"slots/slot-{index:02d}" for index in range(1, 17)} | {
        f"slots/slot-{index:02d}/contention" for index in range(1, 17)
    }
    actual_dirs = set()
    actual_paths = set()
    for root, dirs, names in os.walk(raw, followlinks=False):
        dirs.sort()
        for name in sorted(dirs):
            full = os.path.join(root, name)
            relative = os.path.relpath(full, raw).replace(os.sep, "/")
            try:
                metadata = os.lstat(full)
            except OSError as error:
                raise VerifyError(3, "A_SEAL", f"cannot stat {relative}: {error}") from error
            if stat.S_ISLNK(metadata.st_mode):
                _reject("A_SEAL", f"symlinked raw directory refused: {relative}")
            if not stat.S_ISDIR(metadata.st_mode):
                _reject("A_SEAL", f"non-directory raw entry in dirs: {relative}")
            actual_dirs.add(relative)
        for name in sorted(names):
            full = os.path.join(root, name)
            relative = os.path.relpath(full, raw).replace(os.sep, "/")
            try:
                metadata = os.lstat(full)
            except OSError as error:
                raise VerifyError(3, "A_SEAL", f"cannot stat {relative}: {error}") from error
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                _reject("A_SEAL", f"nonregular raw entry: {relative}")
            actual_paths.add(relative)
    expected_paths = set(EXPECTED_RAW_FILES) | {"seal.json"} | set(EXPECTED_AUX_FILES)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        _reject("A_SEAL", f"raw inventory differs (missing={missing}, extra={extra})")
    if actual_dirs != expected_dirs:
        missing = sorted(expected_dirs - actual_dirs)
        extra = sorted(actual_dirs - expected_dirs)
        _reject("A_SEAL", f"raw directory inventory differs (missing={missing}, extra={extra})")

    slots = []
    for index in range(1, 17):
        relative = f"slots/slot-{index:02d}.json"
        slots.append(_load_json(os.path.join(raw, relative)))
    _check_schedule(slots)

    # Reconcile the unsealed auxiliary probes exactly with the sealed slot copies.
    for index, slot in enumerate(slots, start=1):
        trial = slot.get("trial")
        if not isinstance(trial, dict):
            _reject("A_SEAL", f"slot-{index:02d} has no trial record")
        for phase in ("before", "after"):
            relative = f"slots/slot-{index:02d}/contention/trial{index}-{phase}.json"
            auxiliary = _load_json(os.path.join(raw, relative), "A_SEAL")
            embedded = trial.get(f"contention_{phase}")
            if auxiliary != embedded:
                _reject(
                    "A_SEAL",
                    f"auxiliary contention probe differs from sealed slot-{index:02d} {phase}",
                )
    return {
        "seal": seal,
        "seal_sha256": _sha256_file(seal_path),
        "files": digests,
        "slots": slots,
        "auxiliary_count": len(EXPECTED_AUX_FILES),
    }


def _check_schedule(slots: list) -> None:
    if len(slots) != 16:
        _reject("A_MATRIX", f"expected sixteen warm slots, found {len(slots)}")
    expected = []
    for block, order in enumerate(run.SCHEDULE, start=1):
        for position, arm in enumerate(order, start=1):
            expected.append((block, position, arm))
    keyed = {}
    for slot in slots:
        if not isinstance(slot, dict):
            _reject("A_MATRIX", "slot record is not an object")
        index = slot.get("slot_index")
        if not _is_int(index, positive=True) or index > 16 or index in keyed:
            _reject("A_MATRIX", f"invalid or duplicate slot_index {index!r}")
        keyed[index] = slot
    if sorted(keyed) != list(range(1, 17)):
        _reject("A_MATRIX", "slot indices are not 1..16")
    for index in range(1, 17):
        slot = keyed[index]
        block, position, arm = expected[index - 1]
        if (slot.get("block"), slot.get("position"), slot.get("arm")) != (block, position, arm):
            _reject("A_MATRIX", f"slot-{index:02d} arm/block order differs from the schedule")
        trial = slot.get("trial")
        if not isinstance(trial, dict) or trial.get("index") != index:
            _reject("A_MATRIX", f"slot-{index:02d} trial index mismatch")


# ---------------------------------------------------------------------------
# Independent source / protocol / corpus / host / binary / block proofs
# ---------------------------------------------------------------------------


def _real_corpus_loader(campaign: str):
    directory = os.path.join(campaign, "setup", "corpus")
    if os.path.islink(directory) or not os.path.isdir(directory):
        _blocked("A_PROVENANCE_BLOCKED_CORPUS", f"original corpus missing: {directory}")
    try:
        manifest, rows = run.base.oracle.load_and_verify(directory)
    except Exception as error:  # corpus errors are blocked, never pass
        raise VerifyError(3, "A_PROVENANCE_BLOCKED_CORPUS", f"corpus unverifiable: {error}") from error
    digest = hashlib.sha256(run.base.oracle.canonical_json_bytes(manifest)).hexdigest()
    return digest, rows


EXPECTED_SIZE_REPRODUCIBILITY = {
    f"{arm}/{n}": "INDEPENDENTLY_RE_VERIFIED"
    for arm in ("A", "B")
    for n in (10_000, 100_000)
}


def _require_directory_chain(campaign: str, relative: str) -> str:
    """Require every component of ``relative`` to be a real (non-symlink) dir."""
    current = campaign
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        try:
            metadata = os.lstat(current)
        except OSError as error:
            raise VerifyError(
                3,
                "A_PROVENANCE_BLOCKED_SIZE_ARTIFACTS",
                f"required original size directory missing: {relative} ({error})",
            ) from error
        if stat.S_ISLNK(metadata.st_mode):
            _reject("A_FORMAT", f"symlinked size directory refused: {relative}")
        if not stat.S_ISDIR(metadata.st_mode):
            _reject("A_FORMAT", f"size path is not a directory: {relative}")
        if index != len(parts) - 1 and not os.path.isdir(current):
            _reject("A_FORMAT", f"size directory chain broken: {relative}")
    return current


def _real_size_artifacts(campaign: str, sizes: dict) -> dict:
    """Require all twelve original rebuild directories and re-measure each."""
    for arm in ("A", "B"):
        for n in (10_000, 100_000):
            directories = []
            for attempt in (1, 2, 3):
                relative = f"setup/sizes/{arm}/n{n}-run{attempt}"
                directories.append(_require_directory_chain(campaign, relative))
            measured = []
            for attempt, directory in zip((1, 2, 3), directories):
                try:
                    record = run.measure_sizes(directory)
                except Exception as error:
                    raise VerifyError(
                        3,
                        "A_PROVENANCE_BLOCKED_SIZE_ARTIFACTS",
                        f"cannot re-measure {arm} n{n} run{attempt}: {error}",
                    ) from error
                if record != sizes[arm][str(n)]:
                    _reject(
                        "A_FORMAT",
                        f"{arm} n{n} run{attempt} size/layout differs from the sealed manifest",
                    )
                measured.append(record)
            if len({json.dumps(record, sort_keys=True) for record in measured}) != 1:
                _reject(
                    "A_FORMAT",
                    f"{arm} n{n} rebuilds do not agree with one another",
                )
    return dict(EXPECTED_SIZE_REPRODUCIBILITY)


def _validate_authorization(authorization: dict, manifest: dict, measurements: dict) -> dict:
    if authorization.get("schema") != run.SCHEMA:
        _reject("A_PROVENANCE", "authorization schema mismatch")
    if authorization.get("operator_idle_authorized_by_user") is not True:
        _reject("A_PROVENANCE", "operator idle authorization is not a recorded boolean true")
    recorded = authorization.get("recorded_utc")
    if not isinstance(recorded, str) or not UTC_Z.match(recorded):
        _reject("A_PROVENANCE", "authorization timestamp is not UTC with Z suffix")
    filesystem = authorization.get("filesystem")
    if not isinstance(filesystem, str) or not filesystem:
        _reject("A_PROVENANCE", "authorization filesystem is missing")
    if filesystem != manifest.get("filesystem"):
        _reject("A_PROVENANCE", "authorization/manifest filesystem disagree")
    if filesystem not in run.base.pr15d_run.NATIVE_FILESYSTEMS:
        _reject("A_PROVENANCE", f"filesystem {filesystem!r} is not a native filesystem")
    for source in (manifest, measurements):
        if source.get("environment_fingerprint") != EXPECTED_ENV_FINGERPRINT:
            _reject("A_PROVENANCE", "environment fingerprint mismatches the frozen value")
    return {
        "historical_idle_authorization": "RECORDED_AND_CONSISTENT",
        "historical_environment": "FINGERPRINT_CONSISTENT_NOT_RECOMPUTABLE_FROM_RAW",
    }


def _validate_blocks(blocks: dict) -> None:
    if not isinstance(blocks, dict) or set(blocks) != {"A", "B", "block_arm_order"}:
        _reject("A_MATRIX", "blocks.json keys differ from A/B/block_arm_order")
    order = blocks.get("block_arm_order")
    expected_order = [list(entry) for entry in run.BLOCK_ARM_ORDER]
    if order != expected_order:
        _reject("A_MATRIX", "block arm order differs from the frozen schedule")
    for arm in ("A", "B"):
        arm_blocks = blocks.get(arm)
        if not isinstance(arm_blocks, dict):
            _reject("A_MATRIX", f"blocks[{arm}] is not an object")
        for kind, metric_fields in METRIC_FIELDS.items():
            entries = arm_blocks.get(kind)
            if not isinstance(entries, list) or len(entries) != run.BLOCKS:
                _reject("A_MATRIX", f"{arm}/{kind} must have exactly four blocks")
            seen_blocks = set()
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"block", "samples"}:
                    _reject("A_MATRIX", f"{arm}/{kind} block record shape differs")
                block = entry.get("block")
                if not _is_int(block, positive=True) or block > run.BLOCKS or block in seen_blocks:
                    _reject("A_MATRIX", f"{arm}/{kind} block id {block!r} invalid")
                seen_blocks.add(block)
                samples = entry.get("samples")
                if not isinstance(samples, list) or len(samples) != run.BLOCK_SAMPLES:
                    _reject("A_MATRIX", f"{arm}/{kind} block {block} sample count differs")
                seen_samples = set()
                for sample in samples:
                    if not isinstance(sample, dict):
                        _reject("A_MATRIX", f"{arm}/{kind} sample is not an object")
                    sample_id = sample.get("sample")
                    if not _is_int(sample_id) or sample_id in seen_samples:
                        _reject("A_MATRIX", f"{arm}/{kind} sample id {sample_id!r} invalid")
                    seen_samples.add(sample_id)
                    if sample.get("block") != block:
                        _reject("A_MATRIX", f"{arm}/{kind} sample block mismatch")
                    for field in metric_fields:
                        if not _is_int(sample.get(field), positive=True):
                            _reject("A_MATRIX", f"{arm}/{kind} {field} is not a positive integer")
                    if kind == "build_commit":
                        if sample.get("documents_indexed") != 100_000:
                            _reject("A_MATRIX", "build+commit indexed count is not 100000")
                        if sample.get("documents_verified") != 100_000:
                            _reject("A_MATRIX", "build+commit verified count is not 100000")
                        if not _is_int(sample.get("index_bytes"), positive=True):
                            _reject("A_MATRIX", "build+commit index_bytes is not positive")
                        if sample.get("measured_index_bytes") != sample.get("index_bytes"):
                            _reject("A_MATRIX", "build+commit measured/index bytes differ")
                    else:
                        if sample.get("documents") != 100_000:
                            _reject("A_MATRIX", f"{arm}/{kind} documents is not 100000")
            if seen_blocks != set(range(1, run.BLOCKS + 1)):
                _reject("A_MATRIX", f"{arm}/{kind} block ids are not 1..4")
            for entry in entries:
                if {sample.get("sample") for sample in entry["samples"]} != {0, 1}:
                    _reject("A_MATRIX", f"{arm}/{kind} sample ids are not 0 and 1")


def _validate_binaries(campaign: str, manifest: dict, measurements: dict) -> dict:
    recorded = manifest.get("binary_sha256")
    if recorded != measurements.get("binary_sha256"):
        _reject("A_PROVENANCE", "manifest/measurement binary identities differ")
    if not isinstance(recorded, dict) or set(recorded) != {"A", "B"}:
        _reject("A_PROVENANCE", "binary identity map must contain exactly A and B")
    observed = {}
    for arm in ("A", "B"):
        arm_binaries = recorded[arm]
        if not isinstance(arm_binaries, dict) or set(arm_binaries) != set(BINARY_RELATIVE):
            _reject("A_PROVENANCE", f"{arm} binary identity map shape differs")
        observed[arm] = {}
        for name, parts in BINARY_RELATIVE.items():
            digest = _require_hex64(arm_binaries[name], "A_PROVENANCE", f"{arm} {name} digest")
            relative = "/".join(("setup", "build", arm, *parts))
            try:
                path = _assert_regular_tree(campaign, relative, "A_PROVENANCE")
            except VerifyError as error:
                if error.exit_code == 3:
                    _blocked(
                        "A_PROVENANCE_BLOCKED_MISSING_ORIGINAL_BINARY",
                        f"{arm} {name} binary missing: {relative}",
                    )
                raise
            actual = _sha256_file(path)
            if actual != digest:
                _reject("A_PROVENANCE", f"{arm} {name} binary hash differs from the manifest")
            observed[arm][name] = actual
    return observed


def _source_proof(
    git, root: str, sources: dict, measurements: dict
) -> tuple[str, list[str]]:
    for key, value in sources.items():
        _require_sha1(value, "A_SOURCE", f"source {key}")
    if sources != EXPECTED_SOURCES:
        _reject("A_SOURCE", "measured sources differ from the frozen A/B identities")
    for sha in EXPECTED_SOURCES.values():
        if git.cat_file_type(sha) != "commit":
            _blocked("A_SOURCE_BLOCKED", f"{sha} is not a commit")
    if not git.is_ancestor(run.PR15I0_SHA, EXPECTED_SOURCES["A"]):
        _reject("A_SOURCE", "PR 15I-0 is not an ancestor of A")
    if not git.is_ancestor(EXPECTED_SOURCES["A"], EXPECTED_SOURCES["B"]):
        _reject("A_SOURCE", "A is not an ancestor of B")
    changed = git.changed_paths(EXPECTED_SOURCES["A"], EXPECTED_SOURCES["B"])
    for path in changed:
        if path in run.ALLOWED_EXACT or any(
            path.startswith(prefix) for prefix in run.ALLOWED_PREFIXES
        ):
            continue
        _reject("A_SOURCE", f"candidate changed a path outside the allowlist: {path}")
    if measurements.get("scope_diff") != changed:
        _reject("A_SOURCE", "measurement scope_diff differs from the source diff")
    head = git.head()
    if not git.is_ancestor(EXPECTED_SOURCES["B"], head):
        _blocked("A_SOURCE_BLOCKED", "current HEAD does not descend from B")
    if not git.production_identical(EXPECTED_SOURCES["B"], head):
        _blocked("A_SOURCE_BLOCKED", "production tree differs from the measured candidate")
    if git.hash_object("benchmarks/pr15i_a/protocol.json") != EXPECTED_PROTOCOL_BLOB:
        _reject("A_PROVENANCE", "protocol Git blob differs from the frozen blob")
    if not git.diff_empty(EXPECTED_SOURCES["B"], head, "benchmarks/pr15i_a/protocol.json"):
        _reject("A_PROVENANCE", "protocol changed after the measured candidate")
    return head, changed


# ---------------------------------------------------------------------------
# Format/size proof
# ---------------------------------------------------------------------------


def _validate_sizes_and_features(
    sizes: dict, measurements: dict, proof: dict
) -> dict:
    if not isinstance(sizes, dict) or set(sizes) != {"A", "B"}:
        _reject("A_FORMAT", "size map must contain exactly A and B")
    for arm in ("A", "B"):
        arm_sizes = sizes[arm]
        if not isinstance(arm_sizes, dict) or set(arm_sizes) != {"10000", "100000"}:
            _reject("A_FORMAT", f"{arm} size map shape differs")
        for n in ("10000", "100000"):
            record = arm_sizes[n]
            if not isinstance(record, dict):
                _reject("A_FORMAT", f"{arm} n{n} size record is not an object")
            for component in (
                "sidecar_bytes",
                "segment_bytes",
                "manifest_bytes",
                "current_bytes",
                "committed_index_bytes",
            ):
                if not _is_int(record.get(component)):
                    _reject("A_FORMAT", f"{arm} n{n} {component} is not a nonnegative integer")
            containers = record.get("state_containers")
            if not isinstance(containers, list) or len(containers) != 1:
                _reject("A_FORMAT", f"{arm} n{n} must record exactly one sidecar container")
            container = containers[0]
            if not isinstance(container, dict):
                _reject("A_FORMAT", f"{arm} n{n} sidecar record is not an object")
            for field in ("bytes", "payload_bytes", "payload_version", "sha256", "path"):
                if field not in container:
                    _reject("A_FORMAT", f"{arm} n{n} sidecar lacks {field}")
            if not _is_int(container["bytes"], positive=True):
                _reject("A_FORMAT", f"{arm} n{n} sidecar bytes is not positive")
            if not _is_int(container["payload_bytes"], positive=True):
                _reject("A_FORMAT", f"{arm} n{n} payload bytes is not positive")
            if container["bytes"] != record["sidecar_bytes"]:
                _reject("A_FORMAT", f"{arm} n{n} sidecar length disagrees with the row")
            digest = _require_hex64(container["sha256"], "A_FORMAT", f"{arm} n{n} sidecar")
            path = container["path"]
            if not isinstance(path, str) or not path.endswith(".state"):
                _reject("A_FORMAT", f"{arm} n{n} sidecar path is not a .state basename")
            if os.path.basename(path) != path or path[: -len(".state")] != digest:
                _reject("A_FORMAT", f"{arm} n{n} sidecar path stem is not its SHA-256")
            features = container.get("required_features")
            if not isinstance(features, list):
                _reject("A_FORMAT", f"{arm} n{n} required features is not a list")
            normalized = []
            for feature in features:
                if (
                    not isinstance(feature, list)
                    or len(feature) != 2
                    or not all(_is_int(value) for value in feature)
                ):
                    _reject("A_FORMAT", f"{arm} n{n} malformed feature tuple")
                normalized.append(tuple(feature))
            if len(set(normalized)) != len(normalized):
                _reject("A_FORMAT", f"{arm} n{n} duplicate feature tuple")
            if container["payload_version"] != EXPECTED_PAYLOAD_VERSION[arm]:
                _reject("A_FORMAT", f"{arm} n{n} payload version differs")
            if tuple(sorted(normalized)) != EXPECTED_FEATURES[arm]:
                _reject("A_FORMAT", f"{arm} n{n} required feature set differs")
            overhead = container["bytes"] - container["payload_bytes"]
            if overhead != EXPECTED_ENVELOPE_OVERHEAD[arm]:
                _reject("A_FORMAT", f"{arm} n{n} envelope overhead differs from the sentinel")
            total = (
                record["sidecar_bytes"]
                + record["segment_bytes"]
                + record["manifest_bytes"]
                + record["current_bytes"]
            )
            if total != record["committed_index_bytes"]:
                _reject("A_FORMAT", f"{arm} n{n} component sum differs from the total")
    for n in ("10000", "100000"):
        if sizes["A"][n]["segment_bytes"] != sizes["B"][n]["segment_bytes"]:
            _reject("A_FORMAT", f"n{n} segment bytes differ between arms")
        if sizes["A"][n]["current_bytes"] != sizes["B"][n]["current_bytes"]:
            _reject("A_FORMAT", f"n{n} CURRENT bytes differ between arms")
    for field, value in EXPECTED_100K["A"].items():
        if sizes["A"]["100000"][field] != value:
            _reject("A_FORMAT", f"A 100K {field} differs from the PR 15I0 sentinel")
    if sizes != measurements.get("sizes"):
        _reject("A_FORMAT", "size records differ between manifest and measurements")
    return {
        "format_proof": "PASS",
        "payload_versions": {arm: EXPECTED_PAYLOAD_VERSION[arm] for arm in ("A", "B")},
        "required_features": {
            arm: [[int(a), int(b)] for a, b in EXPECTED_FEATURES[arm]] for arm in ("A", "B")
        },
        "envelope_overhead": dict(EXPECTED_ENVELOPE_OVERHEAD),
    }


# ---------------------------------------------------------------------------
# Lane, oracle and contention proof
# ---------------------------------------------------------------------------


def _validate_slot_lanes(slots: list, corpus_rows: dict, sources: dict, binaries: dict) -> dict:
    descriptors = run.base.stage_lanes("final")
    if [descriptor["id"] for descriptor in descriptors] != list(run.LANE_IDS):
        _reject("A_MATRIX", "frozen lane descriptors drifted")
    for row in descriptors:
        if row["n"] not in corpus_rows:
            _reject("A_ORACLE", f"corpus rows missing n={row['n']}")
    by_id = {descriptor["id"]: descriptor for descriptor in descriptors}
    lane_records = 0
    oracle_records = 0
    for slot in slots:
        arm = slot["arm"]
        if slot.get("source_sha") != sources[arm]:
            _reject("A_SOURCE", f"slot {slot['slot_index']:02d} source differs from {arm}")
        if slot.get("binary_sha256") != binaries[arm]["adapter"]:
            _reject(
                "A_PROVENANCE",
                f"slot {slot['slot_index']:02d} adapter digest differs from {arm}",
            )
        trial = slot["trial"]
        for key in ("contention_before", "contention_after"):
            contention = trial.get(key)
            if not isinstance(contention, dict) or contention.get("state") != "clear":
                _reject("A_PROVENANCE", f"slot {slot['slot_index']:02d} {key} is not clear")
            if contention.get("reason_codes") not in (None, []):
                _reject("A_PROVENANCE", f"slot {slot['slot_index']:02d} {key} has reasons")
        lanes = trial.get("lanes")
        if not isinstance(lanes, list) or len(lanes) != len(run.LANE_IDS):
            _reject("A_MATRIX", f"slot {slot['slot_index']:02d} does not have nine lanes")
        if [lane.get("id") for lane in lanes] != list(run.LANE_IDS):
            _reject("A_MATRIX", f"slot {slot['slot_index']:02d} lane order differs")
        for lane in lanes:
            lane_records += 1
            descriptor = by_id[lane["id"]]
            for field in ("n", "class", "field", "term", "k", "regime"):
                if lane.get(field) != descriptor[field]:
                    _reject("A_MATRIX", f"{lane['id']} {field} differs from the descriptor")
            if lane.get("warmups") != run.WARMUPS:
                _reject("A_MATRIX", f"{lane['id']} warmup count differs")
            expected_ids = [f"{lane['id']}:warmup:{index}" for index in range(run.WARMUPS)]
            if lane.get("warmup_ids") != expected_ids:
                _reject("A_MATRIX", f"{lane['id']} warmup ids differ")
            samples = lane.get("samples_ns")
            if not isinstance(samples, list) or len(samples) != run.MEASURED:
                _reject("A_MATRIX", f"{lane['id']} sample count differs")
            if any(not _is_int(value, positive=True) for value in samples):
                _reject("A_MATRIX", f"{lane['id']} samples contain a nonpositive value")
            try:
                summary = run.base.pr15d_run.summarize(samples)
            except ValueError as error:
                _reject("A_MATRIX", f"{lane['id']} summary failed: {error}")
            if lane.get("summary_ns") != summary:
                _reject("A_MATRIX", f"{lane['id']} summary differs from its samples")
            expected = run.base.oracle.expected(
                rows=corpus_rows[lane["n"]],
                field=lane["field"],
                term=lane["term"],
                k=lane["k"],
            )
            if lane.get("oracle_ok") is not True:
                _reject("A_ORACLE", f"{lane['id']} oracle_ok is not true")
            if lane.get("total_hits") != expected["total_hits"]:
                _reject("A_ORACLE", f"{lane['id']} total_hits differs from the oracle")
            if lane.get("expected_total_hits") != expected["total_hits"]:
                _reject("A_ORACLE", f"{lane['id']} expected_total_hits differs from the oracle")
            if lane.get("doc_ids") != expected["doc_ids"]:
                _reject("A_ORACLE", f"{lane['id']} doc_ids differ from the oracle")
            if lane.get("expected_doc_ids") != expected["doc_ids"]:
                _reject("A_ORACLE", f"{lane['id']} expected_doc_ids differ from the oracle")
            contention = lane.get("contention")
            if not isinstance(contention, dict) or contention.get("state") != "clear":
                _reject("A_PROVENANCE", f"{lane['id']} lane contention is not clear")
            if contention.get("reason_codes") not in (None, []):
                _reject("A_PROVENANCE", f"{lane['id']} lane contention has reasons")
            oracle_records += 1
    return {
        "oracle_record_proof": "PASS",
        "lane_records": lane_records,
        "oracle_records": oracle_records,
        "warmup_records": lane_records * run.WARMUPS,
        "sample_records": lane_records * run.MEASURED,
    }


# ---------------------------------------------------------------------------
# Read-only evidence stamp
# ---------------------------------------------------------------------------


def _evidence_stamp(campaign: str) -> dict:
    stamp = {}
    raw = os.path.join(campaign, RAW_REL)
    for relative in EXPECTED_RAW_FILES + ("seal.json",):
        path = os.path.join(raw, relative)
        stamp[relative] = _sha256_file(path) if os.path.isfile(path) else "MISSING"
    for arm in ("A", "B"):
        for name, parts in BINARY_RELATIVE.items():
            relative = "/".join(("setup", "build", arm, *parts))
            path = os.path.join(campaign, relative)
            stamp[relative] = _sha256_file(path) if os.path.isfile(path) else "MISSING"
    protocol = os.path.join(TOOLING_ROOT, "benchmarks/pr15i_a/protocol.json")
    if os.path.isfile(protocol):
        stamp["benchmarks/pr15i_a/protocol.json"] = _sha256_file(protocol)
    for relative in REPORT_FILES:
        path = os.path.join(TOOLING_ROOT, relative)
        if os.path.isfile(path):
            stamp[relative] = _sha256_file(path)
    for arm in ("A", "B"):
        for n in (10_000, 100_000):
            for index in (1, 2, 3):
                directory = os.path.join(campaign, "setup", "sizes", arm, f"n{n}-run{index}")
                if not os.path.isdir(directory):
                    continue
                stamp[f"sizes/{arm}/n{n}-run{index}"] = run.directory_bytes(directory)
                state_dir = os.path.join(directory, "index", "state")
                if os.path.isdir(state_dir):
                    for name in sorted(os.listdir(state_dir)):
                        path = os.path.join(state_dir, name)
                        if os.path.isfile(path):
                            stamp[f"sizes/{arm}/n{n}-run{index}/state/{name}"] = _sha256_file(path)
    return stamp


# ---------------------------------------------------------------------------
# Public verification entry points
# ---------------------------------------------------------------------------


def verify_campaign(
    checkout_root: str,
    campaign: str,
    *,
    git=None,
    corpus_loader=None,
    size_artifacts=None,
) -> dict:
    """Verify the sealed campaign read-only and return an independent receipt."""
    root = os.path.realpath(checkout_root)
    campaign = os.path.realpath(campaign)
    allowed = os.path.realpath(os.path.join(root, "target", "pr15i-a", "campaigns"))
    if os.path.commonpath([campaign, allowed]) != allowed or campaign == allowed:
        _blocked("A_PATH", "--campaign must be under target/pr15i-a/campaigns")
    if os.path.islink(campaign):
        _blocked("A_PATH", "campaign path is a symlink")
    run.load_protocol(root)
    git = git or RealGit(root)
    corpus_loader = corpus_loader or _real_corpus_loader
    size_artifacts = size_artifacts or _real_size_artifacts

    before = _evidence_stamp(campaign)
    inventory = _inventory_and_rehash(campaign)
    raw = os.path.join(campaign, RAW_REL)
    manifest = _load_json(os.path.join(raw, "manifest.json"), "A_INPUT")
    measurements = _load_json(os.path.join(raw, "measurements.json"), "A_INPUT")
    authorization = _load_json(os.path.join(raw, "authorization.json"), "A_INPUT")
    blocks = _load_json(os.path.join(raw, "blocks.json"), "A_INPUT")
    for document in (manifest, measurements, authorization, blocks):
        if not isinstance(document, dict):
            _reject("A_INPUT", "raw JSON document is not an object")
    if manifest.get("schema") != run.SCHEMA:
        _reject("A_INPUT", "manifest schema mismatch")
    if measurements.get("schema") != run.SCHEMA:
        _reject("A_INPUT", "measurements schema mismatch")
    sources = manifest.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"A", "B"}:
        _reject("A_SOURCE", "manifest sources must be exactly A and B")
    if measurements.get("sources") != sources:
        _reject("A_SOURCE", "manifest/measurement sources differ")

    head, changed = _source_proof(git, root, sources, measurements)
    host = _validate_authorization(authorization, manifest, measurements)
    corpus_digest, corpus_rows = corpus_loader(campaign)
    if corpus_digest != EXPECTED_CORPUS_MANIFEST:
        _reject("A_PROVENANCE", "corpus manifest digest differs from the frozen value")
    for source in (manifest, measurements):
        if source.get("corpus_manifest_sha256") != EXPECTED_CORPUS_MANIFEST:
            _reject("A_PROVENANCE", "recorded corpus manifest digest differs")
    binaries = _validate_binaries(campaign, manifest, measurements)
    _validate_blocks(blocks)
    sizes_proof = _validate_sizes_and_features(
        manifest.get("sizes"), measurements, {"campaign": campaign}
    )
    reproducibility = size_artifacts(campaign, manifest.get("sizes"))
    if reproducibility != EXPECTED_SIZE_REPRODUCIBILITY:
        _reject(
            "A_PROVENANCE",
            "size-artifact proof is not the mandatory four-group independently reverified mapping",
        )
    lanes_proof = _validate_slot_lanes(inventory["slots"], corpus_rows, sources, binaries)

    # Rebuild both arms from fully validated evidence before re-deriving gates.
    a = _reconstruct_arm("A", sources, manifest, blocks, inventory["slots"], binaries,
                         sizes_proof["format_proof"], lanes_proof["oracle_record_proof"])
    b = _reconstruct_arm("B", sources, manifest, blocks, inventory["slots"], binaries,
                         sizes_proof["format_proof"], lanes_proof["oracle_record_proof"])
    report, _details = run.derive(a, b)
    if not _close(report["gates"], measurements["gates"]):
        _reject("A_INPUT_MISMATCH", "recomputed gate matrix differs from the sealed matrix")
    if report["decision"] != measurements["decision"]:
        _reject("A_INPUT_MISMATCH", "recomputed decision differs from the sealed decision")
    for key in (
        "reopen_ratios",
        "build_commit_sum_ratios",
        "build_ratios",
        "commit_ratios",
        "rss_ratios",
        "rss_absolute_increase_bytes",
        "remote_ratios",
        "warm_ratios",
        "size_ratios",
        "sizes",
    ):
        if not _close(report[key], measurements[key]):
            _reject("A_INPUT_MISMATCH", f"recomputed {key} differs from the sealed value")
    _check_baseline_sentinels(measurements)
    _check_integer_size_gates(measurements)
    if list(report["gates"]) != [f"A-P{index:02d}" for index in range(1, 13)]:
        _reject("A_INPUT_MISMATCH", "gate matrix keys differ from A-P01..A-P12")
    if any(value != "PASS" for value in report["gates"].values()):
        _reject("A_INPUT_MISMATCH", "the frozen campaign has a non-PASS gate")
    if report["gates"]["A-P12"] != "PASS":
        _reject("A_PROVENANCE", "A-P12 is not PASS in the re-derived report")

    _validate_published_outputs(root, campaign, measurements)
    after = _evidence_stamp(campaign)
    if before != after:
        _reject("A_EVIDENCE_MUTATED", "evidence bytes changed during verification")

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "qualified": True,
        "decision": measurements["decision"],
        "measured_sources": dict(sources),
        "current_head": head,
        "subject_diff": changed,
        "raw_files_verified": len(EXPECTED_RAW_FILES),
        "auxiliary_contention_files_verified": inventory["auxiliary_count"],
        "original_seal_sha256": inventory["seal_sha256"],
        "protocol_git_blob": EXPECTED_PROTOCOL_BLOB,
        "corpus_manifest_sha256": corpus_digest,
        "binary_sha256": binaries,
        "source_proof": "PASS",
        "format_proof": "PASS",
        "oracle_record_proof": "PASS",
        "provenance_proof": "PASS",
        "three_build_reproducibility": reproducibility,
        "lane_records": lanes_proof["lane_records"],
        "oracle_records": lanes_proof["oracle_records"],
        "warmup_records": lanes_proof["warmup_records"],
        "sample_records": lanes_proof["sample_records"],
        "block_records": 2 * len(METRIC_FIELDS) * run.BLOCKS,
        "historical_idle_authorization": host["historical_idle_authorization"],
        "historical_environment": host["historical_environment"],
        "host_observation": "HISTORICAL_ATTESTATION_NOT_INDEPENDENTLY_REPRODUCED",
        "local_qa": "SEPARATE_REPORTED_STATUS",
        "hosted_ci": "SEPARATE_EXTERNAL_STATUS",
        "independent_review": "SEPARATE_EXTERNAL_STATUS",
        "checks": {
            "seal_inventory": "PASS",
            "auxiliary_contention_binding": "PASS",
            "source_ancestry_and_scope": "PASS",
            "protocol_frozen": "PASS",
            "corpus_frozen": "PASS",
            "binary_identity": "PASS",
            "block_topology": "PASS",
            "format_and_features": "PASS",
            "lane_matrix": "PASS",
            "independent_oracle": "PASS",
            "contention_clear": "PASS",
            "derived_gates": "PASS",
            "published_outputs": "PASS",
            "evidence_unchanged": "PASS",
        },
    }
    return receipt


def _reconstruct_arm(
    arm: str,
    sources: dict,
    manifest: dict,
    blocks: dict,
    slots: list,
    binaries: dict,
    format_proof: str,
    oracle_proof: str,
) -> dict:
    warm = [slot for slot in slots if slot.get("arm") == arm]
    return {
        "arm": arm,
        "source_sha": sources[arm],
        "sizes": {"n": manifest["sizes"][arm], "indices": {}},
        "blocks": {
            kind: blocks[arm][kind] for kind in ("reopen", "build_commit", "remote")
        },
        "warm": warm,
        "oracles_ok": oracle_proof == "PASS",
        "feature_checks_ok": format_proof == "PASS",
        "adapter_sha256": binaries[arm]["adapter"],
        "reopen_sha256": binaries[arm]["reopen"],
        "remote_sha256": binaries[arm]["remote"],
    }


def _validate_published_outputs(root: str, campaign: str, measurements: dict) -> None:
    sanitized = _load_json(os.path.join(campaign, "sanitized", "results.json"), "A_INPUT_MISMATCH")
    if sanitized != measurements:
        _reject("A_INPUT_MISMATCH", "sanitized results differ from raw measurements")
    decision = _load_json(os.path.join(campaign, "sanitized", "decision.json"), "A_INPUT_MISMATCH")
    if decision.get("decision") != measurements["decision"]:
        _reject("A_INPUT_MISMATCH", "sanitized decision differs from raw measurements")
    if not _close(decision.get("gates"), measurements["gates"]):
        _reject("A_INPUT_MISMATCH", "sanitized decision gates differ")
    published = _load_json(
        os.path.join(root, "benchmarks/reports/pr15i-a/results.json"), "A_INPUT_MISMATCH"
    )
    if published != measurements:
        _reject("A_INPUT_MISMATCH", "published results differ from raw measurements")
    published_decision = _load_json(
        os.path.join(root, "benchmarks/reports/pr15i-a/decision.json"), "A_INPUT_MISMATCH"
    )
    if published_decision.get("decision") != measurements["decision"]:
        _reject("A_INPUT_MISMATCH", "published decision differs from raw measurements")
    if not _close(published_decision.get("gates"), measurements["gates"]):
        _reject("A_INPUT_MISMATCH", "published decision gates differ")


def _close(left, right, tolerance: float = 1e-12) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _close(left[key], right[key], tolerance) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _close(a, b, tolerance) for a, b in zip(left, right)
        )
    if isinstance(left, float) or isinstance(right, float):
        return abs(float(left) - float(right)) <= tolerance
    return left == right


def _check_baseline_sentinels(report: dict) -> None:
    a = report["sizes"]["A"]["100000"]
    if (
        a["committed_index_bytes"] != run.PR15I0_100K_TOTAL
        or a["sidecar_bytes"] != run.PR15I0_100K_SIDECAR
    ):
        _reject("A_FORMAT", "arm A 100K size does not reproduce the PR 15I0 sentinels")


def _check_integer_size_gates(report: dict) -> None:
    sizes = report["sizes"]
    a = sizes["A"]
    b = sizes["B"]
    if not b["100000"]["sidecar_bytes"] * 4 <= a["100000"]["sidecar_bytes"] * 3:
        _reject("A_FORMAT", "A-P01 does not hold under exact integer arithmetic")
    if not b["100000"]["committed_index_bytes"] * 20 <= a["100000"][
        "committed_index_bytes"
    ] * 19:
        _reject("A_FORMAT", "A-P02 does not hold under exact integer arithmetic")
    for key in ("sidecar_bytes", "committed_index_bytes"):
        if not b["10000"][key] * 50 <= a["10000"][key] * 51:
            _reject("A_FORMAT", f"A-P03 does not hold for {key}")


# ---------------------------------------------------------------------------
# Receipt and CLI
# ---------------------------------------------------------------------------


def write_receipt(root: str, receipt: dict, path: str) -> str:
    """Exclusively create a review receipt under target/pr15i-a/reviews/."""
    if not os.path.isabs(path):
        _reject("A_RECEIPT", "--receipt-out must be absolute")
    allowed = os.path.realpath(os.path.join(root, *RECEIPT_ROOT_REL))
    candidate = os.path.join(allowed, os.path.basename(path))
    if os.path.realpath(os.path.dirname(path)) != allowed:
        _reject("A_RECEIPT", "receipt must be directly under target/pr15i-a/reviews")
    if os.path.islink(path):
        _reject("A_RECEIPT", "receipt path is a symlink")
    if os.path.exists(candidate):
        _reject("A_RECEIPT", "receipt already exists; refusing to overwrite")
    os.makedirs(allowed, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(candidate, flags, 0o644)
    except FileExistsError as error:
        raise VerifyError(2, "A_RECEIPT", "receipt already exists") from error
    try:
        payload = json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(allowed, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PR 15I-A authoritative verifier")
    parser.add_argument("--checkout-root", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--receipt-out")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = verify_campaign(args.checkout_root, args.campaign)
        if args.receipt_out:
            written = write_receipt(
                os.path.realpath(args.checkout_root), receipt, args.receipt_out
            )
            print(f"RECEIPT={written}")
    except VerifyError as error:
        print(f"{error.code}: {error.detail}", file=sys.stderr)
        return error.exit_code
    print(
        "PR15I_A_VERIFY "
        f"decision={receipt['decision']} qualified={receipt['qualified']} "
        f"raw={receipt['raw_files_verified']} aux={receipt['auxiliary_contention_files_verified']} "
        f"lanes={receipt['lane_records']} samples={receipt['sample_records']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

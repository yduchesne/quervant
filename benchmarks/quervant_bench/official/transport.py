"""Immutable, bounded current-baseline preservation and independent offline replay.

A preserved baseline is ordinary Git data.  Its capability proves the original
bytes and the independent replay calculation; it is never an original G0 or
admission capability.  Working-copy path projections are closed, data-only and
shared with historical reanalysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import uuid

from ..config.codec import canonical_document_bytes, canonical_payload_bytes, content_digest
from ..config.errors import (BM_EVIDENCE_UNAVAILABLE, BM_FILE_MISSING, BM_IDENTITY_INVALID,
    BM_PUBLICATION_CONFLICT, BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError)
from ..config.identity import validate_digest, validate_uuid4
from ..evidence.paths import open_regular_beneath, require_safe_root, validate_relative_member
from ..evidence.provenance import repository_root
from .operation_store import create_directory, write_record
from .protocols import STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY, D3C_CONTROL_NAME, D3C_CAMPAIGN_NAMES

PROFILE = "current-baseline-v2"
KIND = "official-baseline-evidence"
STUDIES = (STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY)
MAX_TOTAL_BYTES = 32 * 1024**3
MAX_MEMBERS = 50_000
MAX_DOCUMENT_BYTES = 64 * 1024**2
MAX_ARCHIVE_BYTES = 4 * 1024**3
MAX_RECORD_BYTES = 1_048_576
ROLES = frozenset({"raw", "control", "readiness", "provenance", "authorization", "qa",
    "policy-input", "analysis", "verification", "history", "report", "qualification", "checkpoint"})
MANIFEST_KEYS = frozenset({"kind", "schema_version", "baseline_id", "profile", "source_commit",
    "source_file_set_digest", "design_digests", "study_runs", "members", "checkpoints", "corpus",
    "relocations", "status"})
MEMBER_KEYS = frozenset({"path", "size_bytes", "sha256", "role"})
RELOCATION_KEYS = frozenset({"path", "json_pointer", "old_value", "new_value", "original_sha256", "working_sha256"})
_EVIDENCE_SENTINEL = object()


def _error(code: str, message: str, field: str) -> BenchError:
    return BenchError(code, message, field_path=field)


def _identity(message: str, field: str) -> BenchError:
    return _error(BM_IDENTITY_INVALID, message, field)


def _git(root: Path, *arguments: str, allowed: tuple[int, ...] = (0,)) -> str:
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True,
            check=False, shell=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise _error(BM_EVIDENCE_UNAVAILABLE, "the required Git identity is unavailable", "git") from error
    if result.returncode not in allowed:
        raise _error(BM_EVIDENCE_UNAVAILABLE, "the required Git identity could not be verified", "git")
    return result.stdout.decode("utf-8", errors="strict").strip()


def _observe(root: Path, relative: str, limit: int, *, capture: bool = False):
    from .history import _observe_file
    return _observe_file(root, relative, max_bytes=limit, capture=capture)


def _recheck(observation: Any) -> None:
    from .history import _require_same_observation
    _require_same_observation(observation)


def _json(root: Path, relative: str, *, limit: int = MAX_RECORD_BYTES) -> dict[str, Any]:
    from .history import _parse
    observation, payload = _observe(root, relative, limit, capture=True)
    assert payload is not None
    node_limit = MAX_MEMBERS * 6 + 10_000 if relative == "baseline-manifest.json" else 100_000
    document = _parse(payload, relative, decimals=False, _node_limit=node_limit)
    if not isinstance(document, Mapping):
        raise _error(BM_SCHEMA_INVALID, "an evidence document must be an object", relative)
    _recheck(observation)
    return dict(document)


def _member_limit(relative: str, role: str) -> int:
    if relative.endswith((".tar.gz", ".zip")):
        return MAX_ARCHIVE_BYTES
    if role in ("authorization", "qualification", "checkpoint", "analysis", "verification"):
        return MAX_RECORD_BYTES
    if role == "provenance":
        if relative.endswith(".tar.gz.sha256"):
            return 4 * 1_048_576
        return 8 * 1_048_576 if relative.endswith(".log") else MAX_RECORD_BYTES
    if role == "policy-input":
        return 4 * 1_048_576
    if role == "qa":
        return 8 * 1_048_576 if relative.endswith(".log") else 65_536
    if relative.startswith("history/inventories/"):
        return MAX_RECORD_BYTES
    if role in ("history", "report") or relative.endswith(".tar.gz.sha256"):
        return 4 * 1_048_576
    return MAX_DOCUMENT_BYTES


def _walk(root: Path, *, exclude: Sequence[str] = ()) -> list[str]:
    root = require_safe_root(root)
    excluded = set(exclude)
    members: list[str] = []
    folded: set[str] = set()
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        dirnames[:] = sorted(name for name in dirnames if name not in excluded)
        for name in dirnames:
            require_safe_root(current / name)
        for name in sorted(filenames):
            relative = validate_relative_member((current / name).relative_to(root).as_posix())
            if relative.casefold() in folded:
                raise _error(BM_UNSAFE_INPUT, "evidence has duplicate or case-colliding paths", "members")
            folded.add(relative.casefold())
            members.append(relative)
            if len(members) > MAX_MEMBERS:
                raise _error(BM_UNSAFE_INPUT, "evidence exceeds the member budget", "members")
    return sorted(members)


def _copy_observed(observation: Any, destination_root: Path, relative: str) -> None:
    """Stream one previously observed member into an exclusive durable file."""
    relative = validate_relative_member(relative)
    destination = destination_root / relative
    create_directory(destination.parent)
    if os.path.lexists(destination):
        other, _ = _observe(destination_root, relative, observation.max_bytes)
        if (other.digest, other.byte_length) != (observation.digest, observation.byte_length):
            raise _error(BM_PUBLICATION_CONFLICT, "preserved evidence is immutable", relative)
        _recheck(observation)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        fd = os.open(destination, flags, 0o600)
        created = True
        with os.fdopen(fd, "wb") as output:
            digest = hashlib.sha256()
            total = 0
            with open_regular_beneath(observation.root, observation.relative) as source:
                while True:
                    chunk = source.read(min(1_048_576, observation.max_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > observation.max_bytes:
                        raise _error(BM_UNSAFE_INPUT, "the preserved member exceeds its budget", relative)
                    digest.update(chunk)
                    output.write(chunk)
            if ("sha256:" + digest.hexdigest(), total) != (observation.digest, observation.byte_length):
                raise _identity("the source changed during preservation", relative)
            output.flush()
            os.fsync(output.fileno())
        _recheck(observation)
        directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def _write_payload(root: Path, relative: str, payload: bytes) -> None:
    """Exclusive fixed bytes with exact reuse; no replacement of original evidence."""
    relative = validate_relative_member(relative)
    target = root / relative
    create_directory(target.parent)
    if os.path.lexists(target):
        before, present = _observe(root, relative, MAX_DOCUMENT_BYTES, capture=True)
        if present != payload:
            raise _error(BM_PUBLICATION_CONFLICT, "preserved evidence is immutable", relative)
        _recheck(before)
        return
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _payload_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _logical_inventory(root: Path, members: Sequence[str]) -> tuple[list[dict[str, Any]], list[Any]]:
    records, observations = [], []
    total = 0
    for path in members:
        observation, _ = _observe(root, path, MAX_DOCUMENT_BYTES)
        total += observation.byte_length
        if total > 512 * 1024**2 or len(records) >= 8192:
            raise _error(BM_UNSAFE_INPUT, "raw inventory exceeds the family bound", "members")
        observations.append(observation)
        records.append({"path": path, "size_bytes": observation.byte_length, "sha256": observation.digest})
    return records, observations


def _confined_working_root(root: Path, replay_checkout: Path) -> Path:
    checkout = require_safe_root(replay_checkout)
    if checkout != repository_root():
        raise _identity("replay must use the executing checkout's package and verifier", "replay_checkout")
    root = Path(root)
    permitted = checkout / "target" / "pr15i-d3-c"
    if not root.is_absolute() or permitted not in root.parents or ".." in root.parts:
        raise _error(BM_UNSAFE_INPUT, "the replay working root is not confined", "working_root")
    if os.path.lexists(root):
        raise _error(BM_PUBLICATION_CONFLICT, "a replay working root must be fresh", "working_root")
    create_directory(root, exclusive=True)
    return root


@dataclass(frozen=True)
class WorkingCopyProjection:
    """Data-only identity of one closed path projection."""
    original_inventory_digest: str
    working_inventory_digest: str
    relocations: tuple[Mapping[str, Any], ...]


def project_retained_working_copy(*, original_campaign_root: Path,
    working_campaign_root: Path, replay_checkout: Path) -> WorkingCopyProjection:
    from .admission import _verify_seal, walk_raw_members

    original = require_safe_root(original_campaign_root)
    if original.name not in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
        raise _identity("a retained working copy needs a registered campaign", "campaign")
    if working_campaign_root.name != original.name:
        raise _identity("the projected campaign basename changed", "campaign")
    members = walk_raw_members(original, exclude_any_dir=("build", "indexes", "corpus", "compile-source"))
    records, observations = _logical_inventory(original, members)
    seal = _json(original, "raw/seal.json", limit=MAX_DOCUMENT_BYTES)
    _verify_seal(original, seal)
    provenance = _json(original, "raw/build-provenance.json", limit=MAX_DOCUMENT_BYTES)
    manifest = _json(original, "manifest.json", limit=MAX_DOCUMENT_BYTES)
    if "canonical_source_path" not in provenance or not isinstance(provenance.get("events"), list):
        raise _error(BM_SCHEMA_INVALID, "build provenance lacks the closed relocation fields", "provenance")
    new_source = str(working_campaign_root / "compile-source")
    changes: dict[str, list[tuple[str, Any, Any]]] = {"raw/build-provenance.json": []}
    provenance = dict(provenance)
    changes["raw/build-provenance.json"].append(("/canonical_source_path", provenance["canonical_source_path"], new_source))
    provenance["canonical_source_path"] = new_source
    events = []
    for index, event in enumerate(provenance["events"]):
        if not isinstance(event, Mapping) or "canonical_source" not in event:
            raise _error(BM_SCHEMA_INVALID, "a provenance event lacks its canonical source", "events")
        changes["raw/build-provenance.json"].append((f"/events/{index}/canonical_source", event["canonical_source"], new_source))
        events.append({**event, "canonical_source": new_source})
    provenance["events"] = events
    projected: dict[str, bytes] = {"raw/build-provenance.json": canonical_document_bytes(provenance)}
    new_provenance = _payload_digest(projected["raw/build-provenance.json"]).removeprefix("sha256:")
    if "build_provenance_sha256" not in manifest:
        raise _error(BM_SCHEMA_INVALID, "manifest lacks its provenance digest", "manifest")
    changes["manifest.json"] = [("/build_provenance_sha256", manifest["build_provenance_sha256"], new_provenance)]
    manifest["build_provenance_sha256"] = new_provenance
    projected["manifest.json"] = canonical_document_bytes(manifest)
    files = seal.get("files")
    if not isinstance(files, Mapping) or not {"raw/build-provenance.json", "manifest.json"} <= set(files):
        raise _error(BM_SCHEMA_INVALID, "seal lacks the projected member identities", "seal")
    files = dict(files)
    changes["raw/seal.json"] = []
    for path, pointer in (("raw/build-provenance.json", "/files/raw~1build-provenance.json"), ("manifest.json", "/files/manifest.json")):
        value = _payload_digest(projected[path]).removeprefix("sha256:")
        changes["raw/seal.json"].append((pointer, files[path], value))
        files[path] = value
    projected["raw/seal.json"] = canonical_document_bytes({**seal, "files": files})
    working = _confined_working_root(working_campaign_root, replay_checkout)
    try:
        for observation in observations:
            if observation.relative not in projected:
                _copy_observed(observation, working, observation.relative)
        for path, payload in projected.items():
            _write_payload(working, path, payload)
        _verify_seal(working, _json(working, "raw/seal.json", limit=MAX_DOCUMENT_BYTES))
        after_records, _ = _logical_inventory(working, members)
        originals = {row["path"]: row["sha256"] for row in records}
        relocated = []
        for path in sorted(changes):
            for pointer, old, new in changes[path]:
                relocated.append({"path": path, "json_pointer": pointer, "old_value": old, "new_value": new,
                    "original_sha256": originals[path], "working_sha256": _payload_digest(projected[path])})
        for observation in observations:
            _recheck(observation)
        return WorkingCopyProjection(content_digest(records), content_digest(after_records), tuple(relocated))
    except BaseException:
        shutil.rmtree(working)
        raise


def project_cross_engine_working_copy(*, original_run_root: Path,
    working_run_root: Path, replay_checkout: Path, corpus_dir: Path) -> WorkingCopyProjection:
    """The sole cross-engine projection changes run.json's corpus_dir only."""
    from .admission import walk_raw_members
    if working_run_root.name != original_run_root.name:
        raise _identity("the projected cross-engine basename changed", "run")
    original = require_safe_root(original_run_root)
    members = walk_raw_members(original, exclude_any_dir=("build", "indexes"))
    records, observations = _logical_inventory(original, members)
    run = _json(original, "run.json", limit=MAX_DOCUMENT_BYTES)
    if type(run.get("corpus_dir")) is not str:
        raise _error(BM_SCHEMA_INVALID, "the original run needs its corpus path", "corpus_dir")
    old = run["corpus_dir"]
    run["corpus_dir"] = str(require_safe_root(corpus_dir))
    payload = canonical_document_bytes(run)
    working = _confined_working_root(working_run_root, replay_checkout)
    try:
        for observation in observations:
            if observation.relative != "run.json":
                _copy_observed(observation, working, observation.relative)
        _write_payload(working, "run.json", payload)
        after, _ = _logical_inventory(working, members)
        for observation in observations:
            _recheck(observation)
        original_digest = next(row["sha256"] for row in records if row["path"] == "run.json")
        return WorkingCopyProjection(content_digest(records), content_digest(after), ({
            "path": "run.json", "json_pointer": "/corpus_dir", "old_value": old,
            "new_value": str(corpus_dir), "original_sha256": original_digest, "working_sha256": _payload_digest(payload)},))
    except BaseException:
        shutil.rmtree(working)
        raise


def _materialize_archive(*, provider_root: Path, relative: str, destination: Path) -> tuple[dict[str, Any], ...]:
    """Inspect then copy regular data members only; archive members are never executed."""
    import tarfile
    import zipfile
    from ..evidence.archives import ArchiveLimits, inspect_tar_gz, inspect_zip
    limits = ArchiveLimits()
    before, _ = _observe(provider_root, relative, limits.max_archive_bytes)
    if relative.endswith(".tar.gz"):
        inspected = inspect_tar_gz(provider_root, relative, limits)
        is_tar = True
    elif relative.endswith(".zip"):
        inspected = inspect_zip(provider_root, relative, limits)
        is_tar = False
    else:
        raise _error(BM_UNSAFE_INPUT, "only registered TAR.GZ or ZIP data are supported", "archive")
    expected = {member.name: member for member in inspected}
    if len({name.casefold() for name in expected}) != len(expected):
        raise _error(BM_UNSAFE_INPUT, "archive member names case-collide", "members")
    if os.path.lexists(destination):
        raise _error(BM_PUBLICATION_CONFLICT, "archive materialization needs a fresh directory", "working_root")
    create_directory(destination, exclusive=True)
    copied = set()
    try:
        with open_regular_beneath(provider_root, relative) as source:
            archive = tarfile.open(fileobj=source, mode="r:gz") if is_tar else zipfile.ZipFile(source)
            with archive:
                for info in (archive if is_tar else archive.infolist()):
                    if (info.isdir() if is_tar else info.is_dir()):
                        continue
                    name = validate_relative_member(info.name if is_tar else info.filename)
                    if name not in expected or name in copied:
                        raise _identity("the archive member set changed during materialization", "archive")
                    if is_tar and not info.isfile():
                        raise _error(BM_UNSAFE_INPUT, "archive links and special files are prohibited", "archive")
                    copied.add(name)
                    item = expected[name]
                    target = destination / name
                    create_directory(target.parent)
                    payload = archive.extractfile(info) if is_tar else archive.open(info)
                    if payload is None:
                        raise _error(BM_UNSAFE_INPUT, "archive member has no ordinary data stream", "archive")
                    digest = hashlib.sha256()
                    length = 0
                    with payload, open(target, "xb") as output:
                        while True:
                            chunk = payload.read(min(1_048_576, item.byte_length - length + 1))
                            if not chunk:
                                break
                            length += len(chunk)
                            if length > item.byte_length:
                                raise _identity("an archive member changed size", name)
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if length != item.byte_length or "sha256:" + digest.hexdigest() != item.digest:
                        raise _identity("a materialized member differs from the inspected archive", name)
        if copied != set(expected):
            raise _identity("the archive lost members during materialization", "archive")
        _recheck(before)
        return tuple({"path": item.name, "size_bytes": item.byte_length, "sha256": item.digest}
            for item in inspected)
    except BaseException:
        shutil.rmtree(destination)
        raise


def _regenerate_corpus(*, replay_checkout: Path, destination: Path,
    expected_digest: str, expected_manifest: Mapping[str, Any] | None = None) -> Path:
    """Untimed frozen Python corpus generation, with exact pinned content checking."""
    from .cross_engine_backend import _module
    from .admission import load_pr15d_oracle
    if replay_checkout != repository_root():
        raise _identity("corpus replay must use the executing checkout", "replay_checkout")
    if os.path.lexists(destination):
        raise _error(BM_PUBLICATION_CONFLICT, "corpus replay requires a fresh owned root", "corpus")
    create_directory(destination, exclusive=True)
    try:
        _module(replay_checkout, "benchmarks/pr15d/corpus/generate.py").generate(str(destination))
        oracle = load_pr15d_oracle()
        manifest, _rows = oracle.load_and_verify(str(destination))
        digest = "sha256:" + oracle.sha256_bytes(oracle.canonical_json_bytes(manifest))
        if digest != expected_digest:
            raise _identity("regenerated corpus differs from the original corpus", "corpus_manifest_digest")
        if expected_manifest is not None and canonical_payload_bytes(manifest) != canonical_payload_bytes(expected_manifest):
            raise _identity("regenerated corpus manifest differs from original bytes", "corpus")
        return destination
    except BaseException:
        shutil.rmtree(destination)
        raise


def validate_recorded_relocations(records: object, *, study_id: str) -> None:
    if not isinstance(records, (list, tuple)):
        raise _error(BM_SCHEMA_INVALID, "relocations must be an ordered sequence", "relocations")
    seen = set()
    for row in records:
        if not isinstance(row, Mapping) or set(row) != RELOCATION_KEYS:
            raise _error(BM_SCHEMA_INVALID, "a relocation has an unexpected shape", "relocations")
        path = validate_relative_member(row["path"])
        pointer = row["json_pointer"]
        if type(pointer) is not str or (path, pointer) in seen:
            raise _error(BM_SCHEMA_INVALID, "a relocation is repeated or mistyped", "relocations")
        seen.add((path, pointer))
        for key in ("original_sha256", "working_sha256"):
            validate_digest(row[key], key)
        if type(row["old_value"]) is not str or type(row["new_value"]) is not str:
            raise _error(BM_SCHEMA_INVALID, "relocation values must be strings", "relocations")
        if study_id == STUDY_CROSS_ENGINE:
            if path not in ("run.json", "backend/run.json") or pointer != "/corpus_dir":
                raise _error(BM_UNSAFE_INPUT, "unapproved cross-engine relocation", "relocations")
        elif study_id == STUDY_RETAINED_KEY:
            relative = path
            for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
                if relative.startswith(campaign + "/"):
                    relative = relative[len(campaign) + 1:]
                    break
            permitted = (relative == "manifest.json" and pointer == "/build_provenance_sha256") or (
                relative == "raw/seal.json" and pointer in ("/files/raw~1build-provenance.json", "/files/manifest.json"))
            if relative == "raw/build-provenance.json":
                parts = pointer.split("/")
                permitted = pointer == "/canonical_source_path" or (len(parts) == 4 and parts[1] == "events"
                    and parts[2].isascii() and parts[2].isdigit() and str(int(parts[2])) == parts[2] and parts[3] == "canonical_source")
            if not permitted:
                raise _error(BM_UNSAFE_INPUT, "unapproved retained-key relocation", "relocations")
        else:
            raise _identity("unknown relocation family", "study_id")


def validate_baseline_evidence_root(*, evidence_root: Path, baseline_id: str, source_root: Path) -> Path:
    """Check the ordinary Git destination before any preparation or acquisition."""
    from .operation_config import absolute_path
    baseline = validate_uuid4(baseline_id, "baseline_id")
    target = absolute_path(str(evidence_root), "evidence_root")
    if target.parts[-3:] != ("benchmark-results", "baselines", baseline):
        raise _error(BM_UNSAFE_INPUT, "baseline evidence has the wrong namespace", "evidence_root")
    checkout = require_safe_root(target.parents[2])
    source = require_safe_root(source_root)
    if checkout == source or checkout in source.parents or source in checkout.parents:
        raise _error(BM_UNSAFE_INPUT, "the evidence checkout must be separate from the executing source checkout", "evidence_root")
    if Path(_git(checkout, "rev-parse", "--show-toplevel")) != checkout:
        raise _error(BM_UNSAFE_INPUT, "the evidence destination is not its checkout root", "evidence_root")
    branch = _git(checkout, "symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1))
    if not branch:
        raise _error(BM_UNSAFE_INPUT, "baseline evidence requires an ordinary branch checkout", "evidence_root")
    relative = target.relative_to(checkout).as_posix()
    ignored = _git(checkout, "check-ignore", "--no-index", "--", relative, relative + "/baseline-manifest.json", allowed=(0, 1))
    if ignored:
        raise _error(BM_UNSAFE_INPUT, "the baseline evidence path is ignored and cannot be committed", "evidence_root")
    source_commit = _git(source, "rev-parse", "--verify", "HEAD")
    _git(checkout, "merge-base", "--is-ancestor", source_commit, "HEAD")
    changed = _git(checkout, "diff", "--name-only", source_commit, "--").splitlines()
    if any(not (path.startswith("docs/") or path.startswith("benchmark-results/")) for path in changed):
        raise _identity("the evidence checkout changes measured source code", "source_commit")
    return checkout


@dataclass(frozen=True)
class _ExportMember:
    observation: Any
    path: str
    role: str

    def record(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.observation.byte_length,
            "sha256": self.observation.digest, "role": self.role}


def _add_export(records: dict[str, _ExportMember], root: Path, relative: str, destination: str,
    role: str, *, optional: bool = False) -> None:
    relative = validate_relative_member(relative)
    destination = validate_relative_member(destination)
    try:
        observation, _ = _observe(root, relative, _member_limit(destination, role))
    except BenchError as error:
        if optional and error.code == BM_FILE_MISSING:
            return
        raise
    member = _ExportMember(observation, destination, role)
    if destination in records:
        previous = records[destination]
        if member.record() != previous.record():
            raise _identity("two inputs conflict at one preserved location", destination)
        return
    if any(path.casefold() == destination.casefold() for path in records):
        raise _error(BM_UNSAFE_INPUT, "export member names case-collide", "members")
    records[destination] = member


def _history_basename(role: str, identity: str) -> str:
    from .history import record_for, PR15D_RUN
    if record_for(role, identity) is None:
        raise _identity("portable history must select a fixed catalog identity", "history")
    names = {"retained-f1-receipt": "f1-freeze.json", "retained-t6-receipt": "t6-freeze.json",
        "retained-micro": "micro.json", "pr15d-archive": PR15D_RUN + ".zip", "pr15d-aggregate": "pr15d-qualified.json",
        "retained-analysis": "analysis.json", "retained-policy": "policy.json"}
    return identity + ".tar.gz" if role == "retained-archive" else names[role]


def _export_history(records: dict[str, _ExportMember], *, config: Any, operation_root: Path, study: str) -> None:
    from . import history
    inventory_path = Path(config.document["baseline"]["history_inventory"])
    inventory = history.validate_inventory(_json(inventory_path.parent, inventory_path.name))
    report = history.validate_report(_json(operation_root, "history-report.json", limit=MAX_DOCUMENT_BYTES))
    selected_inventory = history._family_inventory(inventory, study)
    candidates = {(item["input_role"], item["source_identity"]): item for item in selected_inventory["candidates"]}
    if set(candidates) != {(item["input_role"], item["source_identity"]) for item in report["entries"]}:
        raise _identity("the history report differs from its original inventory", "history")
    _add_export(records, inventory_path.parent, inventory_path.name, f"history/inventories/{study}.json", "history")
    for entry in report["entries"]:
        if entry["status"] != history.STATUS_FOUND:
            if entry["normalized_rows"]:
                raise _identity("an excluded original history observation has numeric rows", "history")
            continue
        role, identity = entry["input_role"], entry["source_identity"]
        candidate = candidates[(role, identity)]
        destination = f"history/inputs/{role}/{identity}/{_history_basename(role, identity)}"
        _add_export(records, inventory_path.parent, candidate["path"], destination, "history")
        if role == "retained-archive":
            _add_export(records, inventory_path.parent, candidate["path"] + ".sha256", destination + ".sha256", "history")
        fresh = history.classify_candidate(inventory_path.parent, candidate, source_root=config.path("source_root"))
        if fresh["status"] != history.STATUS_FOUND or fresh["input_digest"] != entry["input_digest"]:
            raise _identity("a consumed historical input changed before preservation", "history")
        _recheck(records[destination].observation)
        if records[destination].observation.digest != entry["input_digest"]:
            raise _identity("historical export bytes differ from the consumed input", "history")
        if role == "retained-archive":
            _recheck(records[destination + ".sha256"].observation)
    for source, destination in (("history-derivation.json", "derivation.json"), ("history-original-verifier.json", "original-verifier.json")):
        _add_export(records, operation_root, source, f"history/derivations/{study}/{destination}", "history", optional=True)


def preserve_baseline_checkpoint(*, config_path: Path, operation_root: Path, unit: str,
    status: str = "COMPLETE", baseline_context: Any | None = None) -> dict[str, Any]:
    """Preserve finite original bytes, then publish one immutable unit checkpoint."""
    from .operation_config import load_operation_config
    from .protocols import validate_authorization, template_path, verify_g0_authorization, read_canonical_json
    from .authorization import approval_record_path, read_approval_record
    from .admission import load_pr15d_oracle, walk_raw_members
    config = load_operation_config(Path(config_path))
    if config.profile_version != 2:
        raise _error(BM_UNSAFE_INPUT, "baseline preservation requires version two", "schema_version")
    if status not in ("COMPLETE", "STOPPED"):
        raise _error(BM_SCHEMA_INVALID, "unsupported checkpoint status", "status")
    baseline = config.document["baseline"]
    target = Path(baseline["evidence_root"])
    validate_baseline_evidence_root(evidence_root=target, baseline_id=baseline["baseline_id"], source_root=config.path("source_root"))
    terminal_exists = (target / "baseline-manifest.json").exists()
    authorization = validate_authorization(read_canonical_json(config.path("authorization_path")))
    study, run = authorization["study_id"], authorization["run_id"]
    if Path(operation_root) != config.path("workspace") / run:
        raise _identity("the operation root differs from its approved run", "operation_root")
    if authorization.get("baseline_id") != baseline["baseline_id"]:
        raise _identity("the configured baseline differs from G0", "baseline_id")
    units = ("control", "treatment") if study == STUDY_CROSS_ENGINE else (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES)
    if unit not in (*units, "qualification"):
        raise _error(BM_SCHEMA_INVALID, "the checkpoint unit is not registered", "unit")
    context = None
    if unit == "qualification":
        from .history import reverify_baseline_disclosures
        context = reverify_baseline_disclosures(baseline_context)
        if (context.study_id, context.run_id, context.baseline_id) != (study, run, baseline["baseline_id"]):
            raise _identity("qualification context belongs to another baseline run", "baseline_context")
    elif baseline_context is not None:
        raise _error(BM_UNSAFE_INPUT, "raw checkpoints cannot consume publication authority", "baseline_context")
    prefix = f"studies/{study}/{run}"
    exports: dict[str, _ExportMember] = {}
    raw = Path(operation_root) / "raw"
    if unit == "qualification":
        selected = walk_raw_members(raw, exclude_any_dir=("build", "indexes", "corpus", "compile-source"))
    else:
        subtree = ("control" if unit == "control" else "backend") if study == STUDY_CROSS_ENGINE else unit
        selected = []
        if (raw / subtree).is_dir():
            selected = [subtree + "/" + name for name in walk_raw_members(raw / subtree,
                exclude_any_dir=("build", "indexes", "corpus", "compile-source"))]
        elif status == "COMPLETE":
            raise _error(BM_EVIDENCE_UNAVAILABLE, "the completed raw unit is absent", "raw")
    for name in selected:
        role = "readiness" if "readiness" in name else "control" if name.startswith("control/") or name.startswith(D3C_CONTROL_NAME + "/") else "raw"
        _add_export(exports, raw, name, prefix + "/raw/" + name, role)
    source = config.path("source_root")
    design = template_path(study, source, version=2)
    fixed = ((config.path("authorization_path"), "authorization/g0.json", "authorization"),
        (approval_record_path(config.path("approval_source_root"), config.document["approval_source_identity"]), "authorization/approval.json", "authorization"),
        (design, "authorization/design.json", "authorization"),
        (Path(config_path), "provenance/operation-config.json", "provenance"),
        (config.path("prepared_manifest"), "provenance/prepared.json", "provenance"))
    for path, destination, role in fixed:
        _add_export(exports, path.parent, path.name, prefix + "/" + destination, role)
    for name in ("operation.json", "observed-identities.json", "host-preflight.json", "host-readiness.json", "sealed.json", "stopped.json", "preservation-failure.json", f"preflight-{run}.json"):
        _add_export(exports, Path(operation_root), name, prefix + "/provenance/" + name, "provenance",
            optional=name in ("host-readiness.json", "sealed.json", "stopped.json", "preservation-failure.json", f"preflight-{run}.json"))
    for directory_name in ("backend-records", "events"):
        directory = Path(operation_root) / directory_name
        if directory.is_dir():
            for name in _walk(directory):
                _add_export(exports, directory, name, prefix + "/provenance/" + directory_name + "/" + name, "provenance")
    if study == STUDY_RETAINED_KEY:
        from .acquisition import D3C_EVIDENCE_RELATIVE
        from .historical import audit_retained_key_archive
        archives = Path(operation_root) / "home" / ".local" / "share" / "quervant" / D3C_EVIDENCE_RELATIVE
        for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
            archive_name = campaign + ".tar.gz"
            if os.path.lexists(archives / archive_name):
                audit_retained_key_archive(archives, campaign)
                _add_export(exports, archives, archive_name, prefix + "/provenance/published-archives/" + archive_name, "provenance")
                _add_export(exports, archives, archive_name + ".sha256", prefix + "/provenance/published-archives/" + archive_name + ".sha256", "provenance")
            elif unit == "qualification" and status == "COMPLETE":
                raise _error(BM_EVIDENCE_UNAVAILABLE, "a backend-published current archive is missing", "published-archives")
    preparation = config.path("prepared_manifest").parent
    for name in ("preparation-inputs.json", "authorization-inputs.json", "build-receipts.json", "smoke-receipt.json", "smoke.stdout.log", "smoke.stderr.log", "preparation-state.json"):
        _add_export(exports, preparation, name, prefix + "/provenance/" + name, "provenance", optional=True)
    preparation_records = preparation.with_name(preparation.name + ".preparation-records")
    for name in ("started.json", "result.json", "stdout.log", "stderr.log"):
        _add_export(exports, preparation_records, name, prefix + "/provenance/preparation-records/" + name, "provenance", optional=True)
    runtime_path = baseline["runtime_freeze_path"]
    if runtime_path is not None:
        runtime = Path(runtime_path)
        _add_export(exports, runtime.parent, runtime.name, prefix + "/provenance/runtime-freeze.json", "provenance")
        from .runtime_freeze import BACKEND_RECEIPT
        _add_export(exports, source, BACKEND_RECEIPT, prefix + "/provenance/runtime-backend-receipt.json", "provenance")
    oracle = load_pr15d_oracle()
    corpus_manifest, _rows = oracle.load_and_verify(str(config.path("corpus_dir")))
    _add_export(exports, config.path("corpus_dir"), oracle.manifest_filename(), prefix + "/provenance/corpus-manifest.json", "provenance")
    generator = "benchmarks/pr15d/corpus/generate.py"
    generator_digest = _observe(source, generator, 4 * 1_048_576)[0].digest
    corpus_record = {"generator": generator, "generator_digest": generator_digest,
        "manifest_path": prefix + "/provenance/corpus-manifest.json",
        "manifest_digest": "sha256:" + oracle.sha256_bytes(oracle.canonical_json_bytes(corpus_manifest)),
        "files": [{"path": row["path"], "size_bytes": row["bytes"], "sha256": "sha256:" + row["sha256"]}
            for row in corpus_manifest["corpora"]]}
    if corpus_record["manifest_digest"] != authorization["corpus_manifest_digest"]:
        raise _identity("preserved corpus differs from G0", "corpus")
    if unit == "qualification":
        from .contracts import MEMBER_NAMES, FRAMEWORK_QA_ROSTER, SOURCE_QA_ROSTER
        from .qa_evidence import check_record_relative, check_log_relative
        for name in ("admission-index.json", "analysis.json", "policy.json"):
            role = "analysis" if name != "admission-index.json" else "provenance"
            destination = "analysis/" + name if role == "analysis" else "provenance/" + name
            _add_export(exports, Path(operation_root), name, prefix + "/" + destination, role)
        _add_export(exports, Path(operation_root), "verification-assessment.json", prefix + "/verification/assessment.json", "verification")
        for name in ("history-report.json", "relative-effects.json"):
            _add_export(exports, Path(operation_root), name, f"reports/{study}/{name}", "report")
        qualification = config.path("output_base") / study / run
        if _walk(qualification) != sorted(MEMBER_NAMES):
            raise _identity("the original qualification member set is incomplete", "qualification")
        for name in MEMBER_NAMES:
            _add_export(exports, qualification, name, prefix + "/qualification/" + name, "qualification")
        for source_name, name in (("framework_qa", "framework-qa-evidence.json"), ("source_qa", "source-qa-evidence.json")):
            path = config.path(source_name)
            _add_export(exports, path.parent, path.name, prefix + "/qa/summaries/" + name, "qa")
        for gate, roster in (("framework-qa", FRAMEWORK_QA_ROSTER), ("source-qa", SOURCE_QA_ROSTER)):
            for check in roster:
                for name in (check_record_relative(gate, check), check_log_relative(gate, check)):
                    _add_export(exports, config.path("qa_evidence_root"), name, prefix + "/qa/records/" + name, "qa")
        if config.document["policy_inputs"] is not None:
            for field, name in (("micro_json", "micro.json"), ("f1_receipt", "f1-freeze.json")):
                path = Path(config.document["policy_inputs"][field])
                _add_export(exports, path.parent, path.name, prefix + "/policy-inputs/" + name, "policy-input")
        _export_history(exports, config=config, operation_root=Path(operation_root), study=study)
    total = sum(member.observation.byte_length for member in exports.values())
    if total > MAX_TOTAL_BYTES or len(exports) > MAX_MEMBERS:
        raise _error(BM_UNSAFE_INPUT, "the baseline export exceeds its fixed budget", "members")
    raw_members = [member for member in exports.values() if member.role in ("raw", "control", "readiness") and not member.path.endswith((".tar.gz", ".zip"))]
    if len(raw_members) > 8192 or sum(member.observation.byte_length for member in raw_members) > 512 * 1024**2:
        raise _error(BM_UNSAFE_INPUT, "the raw export exceeds its owning family budget", "raw")
    qa_total = sum(member.observation.byte_length for member in exports.values() if member.role == "qa")
    if qa_total > 384 * 1024**2:
        raise _error(BM_UNSAFE_INPUT, "the QA export exceeds its owning budget", "qa")
    existing = [] if not target.exists() else _walk(target)
    existing_total = sum(_observe(target, name, MAX_ARCHIVE_BYTES if name.endswith((".tar.gz", ".zip")) else MAX_DOCUMENT_BYTES)[0].byte_length for name in existing)
    new_total = sum(member.observation.byte_length for path, member in exports.items() if path not in existing)
    if existing_total + new_total > MAX_TOTAL_BYTES or len(set(existing) | set(exports)) + 1 > MAX_MEMBERS:
        raise _error(BM_UNSAFE_INPUT, "cumulative baseline preservation exceeds its budget", "members")
    if shutil.disk_usage(target.parents[2]).free < 2 * total:
        raise _error(BM_EVIDENCE_UNAVAILABLE, "preservation and replay copies exceed available disk", "disk")
    checkpoint = {"kind": "official-baseline-checkpoint", "schema_version": 1,
        "baseline_id": baseline["baseline_id"], "profile": PROFILE, "study_id": study, "run_id": run,
        "source_commit": authorization["source_commit"], "source_file_set_digest": authorization["source_file_set_digest"],
        "design_digest": authorization["design_digest"], "unit": unit, "status": status,
        "qualification_manifest_digest": context and content_digest(_json(config.path("output_base") / study / run, "manifest.json")),
        "members": [exports[path].record() for path in sorted(exports)], "corpus": corpus_record}
    checkpoint_bytes = canonical_document_bytes(checkpoint)
    if len(checkpoint_bytes) > MAX_RECORD_BYTES:
        raise _error(BM_UNSAFE_INPUT, "the checkpoint exceeds the official record bound", "checkpoint")
    if existing_total + new_total + len(checkpoint_bytes) > MAX_TOTAL_BYTES:
        raise _error(BM_UNSAFE_INPUT, "the checkpoint would exceed the total preservation bound", "checkpoint")
    if terminal_exists:
        terminal = _validate_manifest(_json(target, "baseline-manifest.json", limit=MAX_DOCUMENT_BYTES))
        terminal_observations = _authenticate_members(target, terminal)
        checkpoint_path = prefix + "/checkpoints/" + f"{unit}-{status.lower()}.json"
        preserved = _json(target, checkpoint_path)
        if canonical_payload_bytes(preserved) != canonical_payload_bytes(checkpoint):
            raise _error(BM_PUBLICATION_CONFLICT, "the terminal checkpoint differs from current immutable inputs", checkpoint_path)
        declared = {row["path"]: row for row in terminal["members"]}
        for path, member in exports.items():
            if declared.get(path) != member.record():
                raise _error(BM_PUBLICATION_CONFLICT, "terminal evidence cannot acquire changed or new members", path)
            _recheck(member.observation)
        for observed in terminal_observations:
            _recheck(observed)
        return preserved
    for member in exports.values():
        _require_public_safe_member(member.observation)
    create_directory(target)
    for path in sorted(exports):
        member = exports[path]
        _copy_observed(member.observation, target, path)
    checkpoint_dir = target / prefix / "checkpoints"
    create_directory(checkpoint_dir)
    write_record(checkpoint_dir, f"{unit}-{status.lower()}.json", checkpoint, reuse=True)
    return checkpoint


def _checkpoint_documents(baseline_root: Path) -> list[tuple[str, dict[str, Any]]]:
    documents = []
    if not Path(baseline_root).exists():
        return documents
    for path in _walk(baseline_root):
        parts = Path(path).parts
        if len(parts) == 5 and parts[0] == "studies" and parts[3] == "checkpoints":
            document = _json(baseline_root, path)
            keys = {"kind", "schema_version", "baseline_id", "profile", "study_id", "run_id", "source_commit",
                "source_file_set_digest", "design_digest", "unit", "status", "qualification_manifest_digest", "members", "corpus"}
            if set(document) != keys or document["kind"] != "official-baseline-checkpoint" or type(document["schema_version"]) is not int or document["schema_version"] != 1:
                raise _error(BM_SCHEMA_INVALID, "a checkpoint has an unexpected shape", path)
            study, run = parts[1], parts[2]
            if study not in STUDIES or (document["study_id"], document["run_id"], document["baseline_id"], document["profile"]) != (study, run, baseline_root.name, PROFILE):
                raise _identity("checkpoint identities differ from its namespace", path)
            validate_uuid4(run, "run_id")
            from .protocols import validate_source_commit
            validate_source_commit(document["source_commit"], "source_commit")
            validate_digest(document["source_file_set_digest"], "source_file_set_digest")
            validate_digest(document["design_digest"], "design_digest")
            units = ("control", "treatment") if study == STUDY_CROSS_ENGINE else (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES)
            if document["unit"] not in (*units, "qualification") or document["status"] not in ("COMPLETE", "STOPPED"):
                raise _error(BM_SCHEMA_INVALID, "checkpoint unit/status is not registered", path)
            if parts[4] != f"{document['unit']}-{document['status'].lower()}.json":
                raise _identity("checkpoint basename disagrees with its state", path)
            if document["unit"] == "qualification" and document["status"] == "COMPLETE":
                validate_digest(document["qualification_manifest_digest"], "qualification_manifest_digest")
            elif document["qualification_manifest_digest"] is not None:
                raise _error(BM_SCHEMA_INVALID, "an incomplete unit cannot claim a qualification manifest", "qualification_manifest_digest")
            documents.append((path, document))
    return sorted(documents)


def baseline_ready_for_finalization(*, baseline_root: Path) -> bool:
    documents = _checkpoint_documents(Path(baseline_root))
    for study in STUDIES:
        units = ("control", "treatment") if study == STUDY_CROSS_ENGINE else (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES)
        rows = [record for _path, record in documents if record["study_id"] == study]
        if len({record["run_id"] for record in rows}) > 1:
            raise _identity("a baseline contains multiple current runs for one study", "study_runs")
        if not all(any(record["unit"] == unit and record["status"] == "COMPLETE" for record in rows) for unit in (*units, "qualification")):
            return False
    return True


def _validate_member_records(records: object) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) > MAX_MEMBERS:
        raise _error(BM_SCHEMA_INVALID, "member inventory must be a bounded list", "members")
    paths, folded, total = [], set(), 0
    for row in records:
        if not isinstance(row, Mapping) or set(row) != MEMBER_KEYS:
            raise _error(BM_SCHEMA_INVALID, "an inventory member has an unexpected shape", "members")
        path = validate_relative_member(row["path"])
        if path.casefold() in folded:
            raise _error(BM_UNSAFE_INPUT, "inventory paths duplicate or case-collide", "members")
        folded.add(path.casefold())
        paths.append(path)
        if type(row["role"]) is not str or row["role"] not in ROLES:
            raise _error(BM_SCHEMA_INVALID, "unknown preservation role", "role")
        if type(row["size_bytes"]) is not int or not 0 <= row["size_bytes"] <= _member_limit(path, row["role"]):
            raise _error(BM_UNSAFE_INPUT, "a preserved member exceeds its owning bound", path)
        validate_digest(row["sha256"], "sha256")
        total += row["size_bytes"]
    if total > MAX_TOTAL_BYTES or paths != sorted(paths):
        raise _error(BM_UNSAFE_INPUT, "the member inventory is unsorted or exceeds its budget", "members")
    return [dict(row) for row in records]


def finalize_baseline_evidence(*, baseline_root: Path, status: str = "COMPLETE") -> VerifiedBaselineEvidence:
    root = require_safe_root(baseline_root)
    if status not in ("COMPLETE", "STOPPED"):
        raise _error(BM_SCHEMA_INVALID, "unknown terminal baseline status", "status")
    checkpoints = _checkpoint_documents(root)
    if status == "COMPLETE" and not baseline_ready_for_finalization(baseline_root=root):
        raise _error(BM_EVIDENCE_UNAVAILABLE, "both family qualifications and raw unit checkpoints are required", "study_runs")
    if not checkpoints:
        raise _error(BM_EVIDENCE_UNAVAILABLE, "no original checkpoints are available", "study_runs")
    members: dict[str, dict[str, Any]] = {}
    sources = set()
    designs, studies, corpus = {}, {}, {}
    checkpoint_paths = []
    for path, checkpoint in checkpoints:
        sources.add((checkpoint["source_commit"], checkpoint["source_file_set_digest"]))
        study = checkpoint["study_id"]
        if study in designs and designs[study] != checkpoint["design_digest"]:
            raise _identity("one study has conflicting approved designs", "design_digests")
        designs[study] = checkpoint["design_digest"]
        if study in corpus and canonical_payload_bytes(corpus[study]) != canonical_payload_bytes(checkpoint["corpus"]):
            raise _identity("one study has conflicting original corpus identities", "corpus")
        corpus[study] = checkpoint["corpus"]
        existing = studies.get(study)
        if existing and existing["run_id"] != checkpoint["run_id"]:
            raise _identity("one baseline contains multiple current runs for one study", "study_runs")
        if existing is None:
            studies[study] = {"run_id": checkpoint["run_id"], "status": "STOPPED", "qualification_manifest_digest": None}
        if checkpoint["unit"] == "qualification" and checkpoint["status"] == "COMPLETE":
            studies[study] = {"run_id": checkpoint["run_id"], "status": "COMPLETE", "qualification_manifest_digest": checkpoint["qualification_manifest_digest"]}
        for row in _validate_member_records(checkpoint["members"]):
            if row["path"] in members and members[row["path"]] != row:
                raise _identity("immutable checkpoints disagree about preserved bytes", row["path"])
            members[row["path"]] = row
        observed, _ = _observe(root, path, MAX_RECORD_BYTES)
        members[path] = {"path": path, "size_bytes": observed.byte_length, "sha256": observed.digest, "role": "checkpoint"}
        checkpoint_paths.append(path)
    if len(sources) != 1:
        raise _identity("the baseline mixes measured source identities", "source_commit")
    if status == "COMPLETE" and (set(studies) != set(STUDIES) or any(row["status"] != "COMPLETE" for row in studies.values())):
        raise _error(BM_EVIDENCE_UNAVAILABLE, "both current benchmark families must be complete", "study_runs")
    source_commit, source_digest = next(iter(sources))
    manifest = {"kind": KIND, "schema_version": 1, "baseline_id": root.name, "profile": PROFILE,
        "source_commit": source_commit, "source_file_set_digest": source_digest,
        "design_digests": designs, "study_runs": studies, "members": [members[path] for path in sorted(members)],
        "checkpoints": checkpoint_paths, "corpus": corpus, "relocations": [], "status": status}
    _validate_manifest(manifest)
    if len(canonical_document_bytes(manifest)) > MAX_DOCUMENT_BYTES:
        raise _error(BM_UNSAFE_INPUT, "the terminal manifest exceeds its byte bound", "manifest")
    _authenticate_members(root, manifest, manifest_present=(root / "baseline-manifest.json").exists())
    _require_checkpoint_graph(root, manifest)
    write_record(root, "baseline-manifest.json", manifest, reuse=True)
    # A terminal manifest is now immutable. The live writer does not claim replay;
    # its data capability is explicitly PRESERVED, independently reopened below.
    return _preserved_capability(root, manifest)


def _validate_manifest(document: object) -> dict[str, Any]:
    if not isinstance(document, Mapping) or set(document) != MANIFEST_KEYS:
        raise _error(BM_SCHEMA_INVALID, "the baseline manifest has an unexpected shape", "manifest")
    if document["kind"] != KIND or type(document["schema_version"]) is not int or document["schema_version"] != 1 or document["profile"] != PROFILE:
        raise _error(BM_SCHEMA_INVALID, "unsupported baseline manifest kind/version/profile", "manifest")
    validate_uuid4(document["baseline_id"], "baseline_id")
    from .protocols import validate_source_commit
    validate_source_commit(document["source_commit"], "source_commit")
    validate_digest(document["source_file_set_digest"], "source_file_set_digest")
    if document["relocations"] != [] or document["status"] not in ("COMPLETE", "STOPPED"):
        raise _error(BM_SCHEMA_INVALID, "original baseline bytes cannot carry relocations or an unknown status", "manifest")
    studies = document["study_runs"]
    if not isinstance(studies, Mapping) or not studies or not set(studies) <= set(STUDIES):
        raise _error(BM_SCHEMA_INVALID, "baseline studies must be the two registered families", "study_runs")
    if document["status"] == "COMPLETE" and set(studies) != set(STUDIES):
        raise _identity("a complete baseline requires both current families", "study_runs")
    for study, run in studies.items():
        if not isinstance(run, Mapping) or set(run) != {"run_id", "status", "qualification_manifest_digest"}:
            raise _error(BM_SCHEMA_INVALID, "a study run has an unexpected shape", "study_runs")
        validate_uuid4(run["run_id"], "run_id")
        if run["status"] not in ("COMPLETE", "STOPPED"):
            raise _error(BM_SCHEMA_INVALID, "unknown study status", "study_runs")
        if run["status"] == "COMPLETE":
            validate_digest(run["qualification_manifest_digest"], "qualification_manifest_digest")
        elif run["qualification_manifest_digest"] is not None:
            raise _error(BM_SCHEMA_INVALID, "an incomplete study cannot claim qualification", "study_runs")
        if document["status"] == "COMPLETE" and run["status"] != "COMPLETE":
            raise _identity("a complete baseline contains an incomplete study", "study_runs")
    if not isinstance(document["design_digests"], Mapping) or set(document["design_digests"]) != set(studies):
        raise _error(BM_SCHEMA_INVALID, "the design map differs from the registered study set", "design_digests")
    for digest in document["design_digests"].values():
        validate_digest(digest, "design_digests")
    if not isinstance(document["corpus"], Mapping) or set(document["corpus"]) != set(studies):
        raise _error(BM_SCHEMA_INVALID, "the corpus map differs from the registered study set", "corpus")
    for study, record in document["corpus"].items():
        if not isinstance(record, Mapping) or set(record) != {"generator", "generator_digest", "manifest_path", "manifest_digest", "files"}:
            raise _error(BM_SCHEMA_INVALID, "a corpus recipe has an unexpected shape", "corpus")
        if record["generator"] != "benchmarks/pr15d/corpus/generate.py":
            raise _identity("the corpus generator is not the frozen Python generator", "corpus")
        for name in ("generator_digest", "manifest_digest"):
            validate_digest(record[name], name)
        expected = f"studies/{study}/{studies[study]['run_id']}/provenance/corpus-manifest.json"
        if record["manifest_path"] != expected:
            raise _identity("the corpus manifest is outside its original run", "corpus")
        if not isinstance(record["files"], list) or len(record["files"]) != 2:
            raise _error(BM_SCHEMA_INVALID, "the corpus recipe needs its two frozen corpora", "corpus")
        for item in record["files"]:
            if not isinstance(item, Mapping) or set(item) != {"path", "size_bytes", "sha256"}:
                raise _error(BM_SCHEMA_INVALID, "a corpus identity has an unexpected shape", "corpus")
            validate_relative_member(item["path"])
            validate_digest(item["sha256"], "sha256")
            if type(item["size_bytes"]) is not int or item["size_bytes"] <= 0:
                raise _error(BM_SCHEMA_INVALID, "a corpus size must be a positive integer", "corpus")
    members = _validate_member_records(document["members"])
    checkpoints = document["checkpoints"]
    if not isinstance(checkpoints, list) or any(type(path) is not str for path in checkpoints):
        raise _error(BM_SCHEMA_INVALID, "checkpoint paths must be strings in a list", "checkpoints")
    if checkpoints != sorted(set(checkpoints)):
        raise _error(BM_SCHEMA_INVALID, "checkpoint paths must be unique and sorted", "checkpoints")
    expected = sorted(row["path"] for row in members if row["role"] == "checkpoint")
    if checkpoints != expected:
        raise _identity("the terminal checkpoint set differs from its inventory", "checkpoints")
    return {**dict(document), "members": members}


def _authenticate_members(root: Path, manifest: Mapping[str, Any], *, manifest_present: bool = True) -> list[Any]:
    paths = _walk(root)
    expected = [row["path"] for row in manifest["members"]]
    if sorted(paths) != sorted(expected + (["baseline-manifest.json"] if manifest_present else [])):
        raise _identity("preserved baseline has missing or undeclared members", "members")
    observations = []
    for row in manifest["members"]:
        observed, _ = _observe(root, row["path"], _member_limit(row["path"], row["role"]))
        if (observed.digest, observed.byte_length) != (row["sha256"], row["size_bytes"]):
            raise _identity("a preserved member differs from the terminal inventory", row["path"])
        observations.append(observed)
    return observations


def _require_checkpoint_graph(root: Path, manifest: Mapping[str, Any]) -> None:
    """Reconstruct the terminal inventory from its immutable unit checkpoints."""
    checkpoints = _checkpoint_documents(root)
    if [path for path, _document in checkpoints] != manifest["checkpoints"]:
        raise _identity("terminal checkpoint paths differ from preserved checkpoints", "checkpoints")
    members: dict[str, dict[str, Any]] = {}
    designs, studies, corpora = {}, {}, {}
    for path, checkpoint in checkpoints:
        if (checkpoint["source_commit"], checkpoint["source_file_set_digest"]) != (
            manifest["source_commit"], manifest["source_file_set_digest"]):
            raise _identity("a checkpoint differs from the measured source identity", path)
        study = checkpoint["study_id"]
        for target, value, field in ((designs, checkpoint["design_digest"], "design_digests"),
                                    (corpora, checkpoint["corpus"], "corpus")):
            if study in target and canonical_payload_bytes(target[study]) != canonical_payload_bytes(value):
                raise _identity("immutable checkpoints disagree about original identities", field)
            target[study] = value
        if study in studies and studies[study]["run_id"] != checkpoint["run_id"]:
            raise _identity("one study contains multiple checkpoint runs", "study_runs")
        studies.setdefault(study, {"run_id": checkpoint["run_id"], "status": "STOPPED", "qualification_manifest_digest": None})
        if checkpoint["unit"] == "qualification" and checkpoint["status"] == "COMPLETE":
            studies[study] = {"run_id": checkpoint["run_id"], "status": "COMPLETE",
                "qualification_manifest_digest": checkpoint["qualification_manifest_digest"]}
        for member in _validate_member_records(checkpoint["members"]):
            if member["path"] in members and members[member["path"]] != member:
                raise _identity("immutable checkpoints disagree about original bytes", member["path"])
            members[member["path"]] = member
        observed, _ = _observe(root, path, MAX_RECORD_BYTES)
        if path in members:
            raise _identity("a checkpoint may not inventory another checkpoint", path)
        members[path] = {"path": path, "size_bytes": observed.byte_length, "sha256": observed.digest, "role": "checkpoint"}
    expected = {"members": [members[path] for path in sorted(members)],
        "design_digests": designs, "study_runs": studies, "corpus": corpora}
    for field, value in expected.items():
        if canonical_payload_bytes(manifest[field]) != canonical_payload_bytes(value):
            raise _identity("the terminal manifest differs from its complete checkpoint graph", field)


@dataclass(frozen=True)
class VerifiedBaselineEvidence:
    """Verified preserved data, distinct from all live production capabilities."""
    baseline_id: str
    source_commit: str
    source_file_set_digest: str
    manifest_digest: str
    evidence_commit: str | None
    replay_checkout_identity: str | None
    status: str
    _root: Path = field(repr=False)
    _sentinel: object = field(repr=False, compare=False)
    _replay_results: bytes = field(default=b"[]", repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._sentinel is not _EVIDENCE_SENTINEL or self.status not in ("PRESERVED", "REPLAY_VERIFIED"):
            raise _error(BM_UNSAFE_INPUT, "baseline evidence requires its owning verifier", "baseline_evidence")
        validate_uuid4(self.baseline_id, "baseline_id")
        validate_digest(self.manifest_digest, "manifest_digest")
        validate_digest(self.source_file_set_digest, "source_file_set_digest")

    @property
    def document(self) -> Mapping[str, Any]:
        manifest = _validate_manifest(_json(self._root, "baseline-manifest.json", limit=MAX_DOCUMENT_BYTES))
        if content_digest(manifest) != self.manifest_digest:
            raise _identity("the preserved baseline capability is stale", "manifest_digest")
        return manifest


def _preserved_capability(root: Path, manifest: Mapping[str, Any]) -> VerifiedBaselineEvidence:
    return VerifiedBaselineEvidence(baseline_id=manifest["baseline_id"], source_commit=manifest["source_commit"],
        source_file_set_digest=manifest["source_file_set_digest"], manifest_digest=content_digest(dict(manifest)),
        evidence_commit=None, replay_checkout_identity=None, status="PRESERVED", _root=root, _sentinel=_EVIDENCE_SENTINEL)


def _verify_source_link(root: Path, manifest: Mapping[str, Any], checkout: Path) -> tuple[str, str]:
    from ..qualification.identity import source_roster, verify_source_identity
    from .historical import FROZEN_LEGACY_PATHS
    from .protocols import template_path
    checkout = require_safe_root(checkout)
    if checkout != repository_root():
        raise _identity("offline replay must import the package from its replay checkout", "replay_checkout")
    if root != checkout / "benchmark-results" / "baselines" / manifest["baseline_id"]:
        raise _error(BM_UNSAFE_INPUT, "replay requires the baseline's ordinary Git location", "baseline_root")
    evidence_commit = _git(checkout, "rev-parse", "--verify", "HEAD")
    source = manifest["source_commit"]
    _git(checkout, "cat-file", "-e", source + "^{commit}")
    _git(checkout, "merge-base", "--is-ancestor", source, evidence_commit)
    changes = _git(checkout, "diff", "--name-only", source, evidence_commit, "--").splitlines()
    if any(not (name.startswith("docs/") or name.startswith("benchmark-results/")) for name in changes):
        raise _identity("the evidence commit changes measured source", "source_commit")
    status = _git(checkout, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise _error(BM_UNSAFE_INPUT, "offline acceptance requires a clean replay checkout", "replay_checkout")
    relative_root = root.relative_to(checkout).as_posix()
    for path in [row["path"] for row in manifest["members"]] + ["baseline-manifest.json"]:
        relative = relative_root + "/" + path
        tracked = _git(checkout, "rev-parse", "--verify", evidence_commit + ":" + relative)
        current = _git(checkout, "hash-object", "--", relative)
        if tracked != current:
            raise _identity("a preserved member differs from its Git commit", path)
    paths = set(source_roster(checkout)) | set(FROZEN_LEGACY_PATHS)
    paths.update(template_path(study, checkout, version=2).relative_to(checkout).as_posix() for study in STUDIES)
    paths.add("benchmarks/pr15d/corpus/generate.py")
    for path in sorted(paths):
        original = _git(checkout, "rev-parse", "--verify", source + ":" + path)
        current = _git(checkout, "hash-object", "--", path)
        if original != current:
            raise _identity("the replay source differs from the measured source", path)
    verify_source_identity(checkout, manifest["source_file_set_digest"])
    identity = content_digest({"kind": "official-replay-checkout", "schema_version": 1,
        "commit": evidence_commit, "source_file_set_digest": manifest["source_file_set_digest"], "path": str(checkout)})
    return evidence_commit, identity


def _restore_qa(*, baseline_root: Path, prefix: str, freeze: Any, output_root: Path, raw_root: Path) -> None:
    from . import coordinator, qa_evidence
    from .contracts import FRAMEWORK_QA_ROSTER, SOURCE_QA_ROSTER
    summaries = {gate: _json(baseline_root, prefix + "/qa/summaries/" + gate + "-evidence.json")
        for gate in ("framework-qa", "source-qa")}
    for gate, summary in summaries.items():
        coordinator._require_qa(summary, gate=gate, freeze=freeze, roster_digest=coordinator.qa_roster_digest())
    temporary_parent = Path(tempfile.gettempdir()).absolute()
    checkout = repository_root()
    if temporary_parent == checkout or checkout in temporary_parent.parents or temporary_parent == output_root or output_root in temporary_parent.parents or temporary_parent == raw_root or raw_root in temporary_parent.parents:
        raise _error(BM_UNSAFE_INPUT, "QA restoration needs an outside temporary parent", "qa_evidence_root")
    temporary = Path(tempfile.mkdtemp(prefix="quervant-offline-qa-", dir=temporary_parent))
    observations = []
    expected = {}
    try:
        os.chmod(temporary, 0o700)
        for gate, roster in (("framework-qa", FRAMEWORK_QA_ROSTER), ("source-qa", SOURCE_QA_ROSTER)):
            for check in roster:
                for relative, limit in ((qa_evidence.check_record_relative(gate, check), qa_evidence.MAX_CHECK_RECORD_BYTES),
                    (qa_evidence.check_log_relative(gate, check), qa_evidence.MAX_LOG_BYTES)):
                    observed, _ = _observe(baseline_root, prefix + "/qa/records/" + relative, limit)
                    observations.append(observed)
                    expected[relative] = observed.digest
                    _copy_observed(observed, temporary, relative)
        actual = qa_evidence.verify_executed_qa_evidence(qa_evidence_root=temporary,
            framework_summary=summaries["framework-qa"], source_summary=summaries["source-qa"], freeze=freeze,
            output_root=output_root, raw_root=raw_root)
        # QA's snapshot is deliberately the raw SHA-256 map, never summary PASS.
        normalized = {name: value if value.startswith("sha256:") else "sha256:" + value for name, value in actual.items()}
        if normalized != expected or len(expected) != 66:
            raise _identity("restored QA does not equal the preserved 66-member snapshot", "qa")
        for observed in observations:
            _recheck(observed)
    finally:
        shutil.rmtree(temporary)


def _plain_original_freeze(*, root: Path, prefix: str, manifest: Mapping[str, Any], checkout: Path):
    from . import authorization, protocols, analysis, admission
    from ..qualification.identity import compute_source_set_digest, source_roster
    from ..config.identity import validate_semantic_id
    from ..qualification.contracts import require_closed
    approval = require_closed(_json(root, prefix + "/authorization/approval.json"), "approval-record", authorization._APPROVAL_RECORD_KEYS)
    if approval["kind"] != authorization.APPROVAL_RECORD_KIND or type(approval["schema_version"]) is not int or approval["schema_version"] != 1:
        raise _error(BM_SCHEMA_INVALID, "the preserved approval has an unregistered kind/version", "approval")
    validate_semantic_id(approval["independent_review_id"], "independent_review_id")
    if not authorization._is_utc_timestamp(approval["approved_at_utc"]):
        raise _error(BM_SCHEMA_INVALID, "the preserved approval lacks its UTC timestamp", "approval")
    template = protocols.validate_template(_json(root, prefix + "/authorization/design.json"))
    study = template["study_id"]
    if template["schema_version"] != 2 or content_digest(template) != manifest["design_digests"][study]:
        raise _identity("the preserved design differs from the baseline manifest", "design_digest")
    registered = protocols.read_canonical_json(protocols.template_path(study, checkout, version=2))
    if canonical_payload_bytes(template) != canonical_payload_bytes(registered):
        raise _identity("the preserved design differs from the executing approved design", "design_digest")
    original_config = _json(root, prefix + "/provenance/operation-config.json")
    _validate_original_config_data(original_config, study=study)
    baseline = original_config["baseline"]
    if not isinstance(baseline, Mapping) or set(baseline) != {"baseline_id", "evidence_root", "history_inventory", "runtime_freeze_path"}:
        raise _error(BM_SCHEMA_INVALID, "the original baseline locations are malformed", "operation-config")
    if baseline["baseline_id"] != manifest["baseline_id"] or original_config["acceptance_profile"] != PROFILE:
        raise _identity("the preserved configuration belongs to another baseline", "baseline_id")
    prepared_before, _ = _observe(root, prefix + "/provenance/prepared.json", MAX_DOCUMENT_BYTES)
    prepared = _json(root, prefix + "/provenance/prepared.json", limit=MAX_DOCUMENT_BYTES)
    _validate_original_prepared_data(prepared, study=study)
    host = _json(root, prefix + "/provenance/host-preflight.json")
    if prepared.get("source_root") != original_config["source_root"] or prepared.get("corpus_dir") != original_config["corpus_dir"]:
        raise _identity("prepared input locations differ from their original configuration", "prepared")
    if study == STUDY_CROSS_ENGINE:
        from .cross_engine_backend import _PREPARED_KEYS, PREPARED_SCHEMA, _binary_digest
        if set(prepared) != _PREPARED_KEYS or prepared["schema"] != PREPARED_SCHEMA or prepared["source_sha"] != manifest["source_commit"]:
            raise _identity("the preserved preparation has another source or schema", "prepared")
        without_digest = {key: value for key, value in prepared.items() if key != "manifest_digest"}
        if prepared["manifest_digest"] != content_digest(without_digest):
            raise _identity("the preserved prepared manifest digest differs", "prepared")
        binary_digest = _binary_digest(prepared["binaries"])
    else:
        from .retained_backend import KIND as RETAINED_PREPARED_KIND
        if set(prepared) != {"schema", "source_root", "corpus_dir", "protocol_digest", "corpus_digest", "binaries"} or prepared["schema"] != RETAINED_PREPARED_KIND:
            raise _error(BM_SCHEMA_INVALID, "retained preparation has an unexpected shape", "prepared")
        binary_digest = content_digest({"kind": "official-retained-key-binaries", "schema_version": 1, "binaries": prepared["binaries"]})
    corpus = _json(root, manifest["corpus"][study]["manifest_path"])
    oracle = admission.load_pr15d_oracle()
    corpus_digest = "sha256:" + oracle.sha256_bytes(oracle.canonical_json_bytes(corpus))
    if corpus_digest != manifest["corpus"][study]["manifest_digest"]:
        raise _identity("the preserved corpus recipe differs from its original manifest", "corpus")
    corpus_items = corpus.get("corpora")
    if not isinstance(corpus_items, list) or len(corpus_items) != 2 or any(
        not isinstance(row, Mapping) or set(row) != {"n", "rows", "path", "sha256", "bytes"}
        or type(row["bytes"]) is not int or row["bytes"] <= 0 or type(row["sha256"]) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in corpus_items):
        raise _error(BM_SCHEMA_INVALID, "the original corpus file identities are malformed", "corpus")
    expected_corpus_files = [{"path": validate_relative_member(row["path"]), "size_bytes": row["bytes"],
        "sha256": "sha256:" + row["sha256"]} for row in corpus_items]
    if canonical_payload_bytes(manifest["corpus"][study]["files"]) != canonical_payload_bytes(expected_corpus_files):
        raise _identity("the preserved corpus recipe file identities differ from its original manifest", "corpus")
    generator_digest = _observe(checkout, manifest["corpus"][study]["generator"], 4 * 1_048_576)[0].digest
    if generator_digest != manifest["corpus"][study]["generator_digest"]:
        raise _identity("the preserved corpus recipe differs from the executing generator", "corpus")
    if study == STUDY_CROSS_ENGINE:
        corpus_before, _ = _observe(root, manifest["corpus"][study]["manifest_path"], MAX_RECORD_BYTES)
        prepared_files = sorted([*expected_corpus_files, {"path": oracle.manifest_filename(),
            "size_bytes": corpus_before.byte_length, "sha256": corpus_before.digest}], key=lambda row: row["path"])
        if canonical_payload_bytes(prepared["corpus_files"]) != canonical_payload_bytes(prepared_files):
            raise _identity("prepared corpus files differ from the actual preserved originals", "corpus_files")
    prepared_corpus = prepared["corpus_manifest_digest"] if study == STUDY_CROSS_ENGINE else prepared["corpus_digest"]
    if prepared_corpus != corpus_digest:
        raise _identity("the original preparation differs from its preserved corpus", "corpus_manifest_digest")
    if study == STUDY_RETAINED_KEY and prepared["protocol_digest"] != template["backend_protocol_identity"]["raw_sha256"]:
        raise _identity("the original preparation differs from its frozen protocol", "protocol_digest")
    framework = _json(root, prefix + "/qa/summaries/framework-qa-evidence.json")
    source_qa = _json(root, prefix + "/qa/summaries/source-qa-evidence.json")
    schedule = template["schedule"]
    backend = protocols.verify_backend_protocol(template, checkout)
    tree = _git(checkout, "rev-parse", "--verify", manifest["source_commit"] + "^{tree}")
    verifier_path = "benchmarks/pr15d/harness/validate.py" if study == STUDY_CROSS_ENGINE else "benchmarks/pr15i_d3_c/verify.py"
    observations = {
        "design_digest": content_digest(template), "backend_protocol_digest": backend["raw_digest"],
        "source_commit": manifest["source_commit"], "source_file_set_digest": compute_source_set_digest(checkout),
        "source_tree_sha": content_digest({"kind": "official-git-tree", "schema_version": 1, "git_tree": tree}),
        "adapter_source_manifest_digest": admission._adapter_source_digest(checkout),
        "binary_manifest_digest": binary_digest, "corpus_manifest_digest": corpus_digest,
        "original_reference_verifier_digest": _observe(checkout, verifier_path, 8 * 1_048_576)[0].digest,
        "host_preflight_digest": content_digest(host),
        "control_schedule_digest": content_digest({key: value for key, value in schedule.items() if key.startswith("control_")}),
        "treatment_schedule_digest": content_digest({key: value for key, value in schedule.items() if not key.startswith("control_")}),
        "qa_source_digest": content_digest(source_qa), "qa_framework_digest": content_digest(framework),
        "policy_digest": analysis.policy_profile_digest(study, template["policy"]["policy_chain"]),
        "output_root_identity": original_config["output_base"], "acceptance_profile": PROFILE,
        "baseline_id": manifest["baseline_id"], "preservation_root_identity": baseline["evidence_root"], "runtime_freeze_digest": None,
    }
    if study == STUDY_CROSS_ENGINE and prepared["adapter_source_digest"] != observations["adapter_source_manifest_digest"]:
        raise _identity("the original preparation differs from its preserved adapter source", "adapter_source_digest")
    if study == STUDY_RETAINED_KEY:
        from .runtime_freeze import validate_runtime_freeze_document, RECEIPT_KEYS, EXTRA_PROTECTED
        runtime_before, _ = _observe(root, prefix + "/provenance/runtime-freeze.json", MAX_RECORD_BYTES)
        runtime = validate_runtime_freeze_document(_json(root, prefix + "/provenance/runtime-freeze.json"), template=template)
        receipt_before, _ = _observe(root, prefix + "/provenance/runtime-backend-receipt.json", MAX_RECORD_BYTES)
        receipt = _json(root, prefix + "/provenance/runtime-backend-receipt.json")
        protected = {name: _observe(checkout, name, 256 * 1_048_576)[0].digest.removeprefix("sha256:")
            for name in sorted(set(source_roster(checkout)) | set(EXTRA_PROTECTED))}
        tooling = _observe(checkout, "benchmarks/pr15i_d3_c/tooling_manifest.json", MAX_RECORD_BYTES)[0].digest.removeprefix("sha256:")
        expected_receipt = {"schema": "pr15i-d3c-freeze-v1", "protocol_sha256": protocols.D3C_PROTOCOL_RAW_SHA256.removeprefix("sha256:"),
            "control_name": D3C_CONTROL_NAME, "campaign_names": list(D3C_CAMPAIGN_NAMES), "t6_commit": manifest["source_commit"],
            "tooling_manifest_sha256": tooling, "protected_files": protected, "receipt_origin": PROFILE}
        if set(receipt) != RECEIPT_KEYS or canonical_payload_bytes(receipt) != canonical_payload_bytes(expected_receipt):
            raise _identity("the preserved current runtime receipt differs from its original sources", "runtime_freeze")
        expected_runtime = {key: value for key, value in observations.items() if key in runtime}
        expected_runtime.update({"prepared_manifest_digest": prepared_before.digest, "backend_receipt_digest": receipt_before.digest,
            "approved_output_root_identity": original_config["output_base"], "adapter_cpu": original_config["adapter_cpu"],
            "controller_cpu": original_config["controller_cpu"]})
        for key, value in expected_runtime.items():
            if canonical_payload_bytes(runtime[key]) != canonical_payload_bytes(value):
                raise _identity("the preserved runtime envelope differs from authenticated originals", key)
        observations["runtime_freeze_digest"] = runtime_before.digest
    recorded = _json(root, prefix + "/provenance/observed-identities.json")
    if canonical_payload_bytes(recorded) != canonical_payload_bytes(observations):
        raise _identity("the preserved observations differ from independently reconstructed identities", "observed-identities")
    freeze = protocols.verify_g0_authorization(root / prefix / "authorization/g0.json", approval["approved_authorization_digest"], observations)
    if freeze.study_id != study or approval["study_id"] != study or freeze.run_id != manifest["study_runs"][study]["run_id"]:
        raise _identity("preserved approval, design and run identities differ", "authorization")
    if freeze.source_file_set_digest != manifest["source_file_set_digest"]:
        raise _identity("the manifest and original G0 disagree about measured source", "source_file_set_digest")
    admission.verify_authorized_source(checkout, freeze)
    return freeze, template, original_config, host, corpus


def _pure_qualification(*, root: Path, prefix: str, freeze: Any, template: Mapping[str, Any]):
    from . import publication, coordinator, contracts
    directory = root / prefix / "qualification"
    if _walk(directory) != sorted(contracts.MEMBER_NAMES):
        raise _identity("the original qualification bundle is incomplete", "qualification")
    documents = {name: publication.validate_official_member(name, _json(directory, name)) for name in contracts.MEMBER_NAMES}
    index = documents["admission-index.json"]
    history = _json(root, f"reports/{freeze.study_id}/history-report.json", limit=MAX_DOCUMENT_BYTES)
    effects = _json(root, f"reports/{freeze.study_id}/relative-effects.json", limit=MAX_DOCUMENT_BYTES)
    anchors = publication.OfficialBaselineAnchors(subject=index["subject"], approved_design_digest=freeze.design_digest,
        authorization_digest=freeze.authorization_digest, backend_protocol_digest=freeze.backend_protocol_digest,
        source_set_digest=freeze.source_file_set_digest, binary_manifest_digest=freeze.binary_manifest_digest,
        corpus_manifest_digest=freeze.corpus_manifest_digest, host_preflight_digest=freeze.host_preflight_digest,
        original_verifier_digest=freeze.original_reference_verifier_digest, policy_digest=freeze.policy_digest,
        qa_roster_digest=coordinator.qa_roster_digest(), control_assessment_digest=documents["analysis.json"]["control_result_digest"],
        acceptance_profile=PROFILE, baseline_id=freeze.baseline_id, history_report_digest=content_digest(history),
        relative_effects_digest=content_digest(effects))
    publication._check_anchors_against_freeze(anchors, freeze, study_id=freeze.study_id, run_id=freeze.run_id)
    publication._validate_bundle_semantics(study_id=freeze.study_id, run_id=freeze.run_id,
        members=[(name, documents[name]) for name in contracts.MEMBER_NAMES if name != "manifest.json"],
        manifest=documents["manifest.json"], anchors=anchors, profile_version=2, require_verified_parity=False)
    return documents, history, effects


def _verify_original_raw(root: Path, study: str, index: Mapping[str, Any]) -> str:
    from . import admission
    paths = admission.cross_engine_member_paths(root) if study == STUDY_CROSS_ENGINE else admission.retained_key_member_paths(root)
    records, _ = admission.hash_raw_members(root, paths)
    if canonical_payload_bytes(records) != canonical_payload_bytes(index["members"]):
        raise _identity("preserved original raw differs from the original admission member inventory", "raw")
    digest = admission.inventory_digest(records)
    if digest != index["raw_series_root_digest"]:
        raise _identity("preserved original raw differs from original admission", "raw_series_root_digest")
    if study == STUDY_RETAINED_KEY:
        for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
            admission._verify_seal(root / campaign, _json(root / campaign, "raw/seal.json", limit=MAX_DOCUMENT_BYTES))
    return digest


def _working_raw(*, original: Path, working: Path, checkout: Path, study: str, corpus: Path):
    from . import admission
    create_directory(working, exclusive=True)
    relocations = []
    if study == STUDY_RETAINED_KEY:
        for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
            projection = project_retained_working_copy(original_campaign_root=original / campaign,
                working_campaign_root=working / campaign, replay_checkout=checkout)
            relocations.extend({**row, "path": campaign + "/" + row["path"]} for row in projection.relocations)
    else:
        projection = project_cross_engine_working_copy(original_run_root=original / "backend",
            working_run_root=working / "backend", replay_checkout=checkout, corpus_dir=corpus)
        relocations.extend({**row, "path": "backend/" + row["path"]} for row in projection.relocations)
        for path in admission.cross_engine_member_paths(original):
            if not path.startswith("backend/"):
                observation, _ = _observe(original, path, MAX_DOCUMENT_BYTES)
                _copy_observed(observation, working, path)
    validate_recorded_relocations(relocations, study_id=study)
    return relocations


def _verify_current_retained_archives(root: Path, prefix: str) -> None:
    """Bind each actually published current archive to the preserved raw tree."""
    from . import admission
    from .historical import audit_retained_key_archive
    from ..evidence.archives import inspect_tar_gz
    archives = root / prefix / "provenance/published-archives"
    expected_paths = sorted(name for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES)
        for name in (campaign + ".tar.gz", campaign + ".tar.gz.sha256"))
    if _walk(archives) != expected_paths:
        raise _identity("the published current archive set is incomplete", "published-archives")
    for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
        archive_name = campaign + ".tar.gz"
        archive_before, _ = _observe(archives, archive_name, MAX_ARCHIVE_BYTES)
        sidecar_before, _ = _observe(archives, archive_name + ".sha256", 4 * 1_048_576)
        audit_retained_key_archive(archives, campaign)
        members = inspect_tar_gz(archives, archive_name)
        raw = root / prefix / "raw" / campaign
        names = admission.walk_raw_members(raw, exclude_any_dir=("build", "indexes", "corpus", "compile-source"))
        records, _ = admission.hash_raw_members(raw, names)
        expected = {row["path"]: (row["digest"], row["byte_length"]) for row in records}
        actual = {member.name: (member.digest, member.byte_length) for member in members}
        if actual != expected:
            raise _identity("published current archive bytes differ from the original raw campaign", "published-archives")
        _recheck(archive_before)
        _recheck(sidecar_before)


def _independent_statistics(*, root: Path, prefix: str, working: Path, checkout: Path,
    freeze: Any, template: Mapping[str, Any], corpus: Path, original_raw_digest: str,
    documents: Mapping[str, Mapping[str, Any]], original_config: Mapping[str, Any]):
    from . import admission, analysis, verification, contracts, policy_reference, retained_policy
    study = freeze.study_id
    original_analysis = documents["analysis.json"]
    original_policy = documents["policy.json"]
    if study == STUDY_CROSS_ENGINE:
        from .cross_engine_backend import _verify_persisted_cross_engine_control
        control = _verify_persisted_cross_engine_control(raw_root=working, corpus_dir=corpus, root=checkout, template=template)
        record = admission._admit_cross_engine_core(raw_root=working, freeze=freeze, template=template,
            corpus_dir=corpus, control_document=control, source_root=checkout,
            original_verifier=admission.OriginalVerifier(), for_production=True)
        reference = verification._ref_cross_engine_statistics(record)
        verification._compare_cross_engine(original_analysis, reference)
        if not verification._ref_cross_engine_control(record.control):
            raise _identity("the independent cross-engine control failed", "control")
        claims = verification.CLAIM_CROSS_ENGINE
    else:
        record = admission._admit_retained_key_core(raw_root=working, freeze=freeze, template=template,
            source_root=checkout, original_verifier=admission.OriginalVerifier(), for_production=True)
        reference = verification._ref_retained_key_statistics(record, template)
        verification._compare_retained_key(original_analysis, reference)
        if not verification._ref_retained_key_control(record):
            raise _identity("the independent retained control failed", "control")
        paired, _ = policy_reference.reference_slot_statistics(record)
        expected = {"method_id": "retained-key-paired-slot-effects-v1", "lanes": paired}
        if canonical_payload_bytes(expected) != canonical_payload_bytes(original_analysis["retained_slot_statistics"]):
            raise _identity("the independent retained paired statistics differ", "retained_slot_statistics")
        claims = verification.CLAIM_RETAINED_KEY
    if record.admission_index["subject"] != documents["admission-index.json"]["subject"]:
        raise _identity("working replay changed the original path-free subject", "subject")
    derived_analysis, descriptive_policy = analysis.analyze_official_study(admitted=record, template=template, policy_inputs=None)
    comparison = {**derived_analysis, "raw_series_root_digest": original_raw_digest}
    if canonical_payload_bytes(comparison) != canonical_payload_bytes(original_analysis):
        raise _identity("the complete raw-derived analysis differs from original analysis", "analysis")
    optional = original_config["policy_inputs"]
    unevaluated = study == STUDY_RETAINED_KEY and optional is None
    if optional is None:
        comparison_policy = {**descriptive_policy, "analysis_digest": content_digest(dict(original_analysis))}
        if canonical_payload_bytes(comparison_policy) != canonical_payload_bytes(original_policy):
            raise _identity("the complete descriptive policy differs from original policy", "policy")
        verification._require_descriptive_policy(original_policy, study)
    else:
        if study != STUDY_RETAINED_KEY:
            raise _identity("cross-engine replay cannot consume retained policy inputs", "policy_inputs")
        if not isinstance(optional, Mapping) or set(optional) != {"micro_json", "expected_micro_sha256", "f1_receipt"}:
            raise _error(BM_SCHEMA_INVALID, "the original policy input declaration is malformed", "policy_inputs")
        from .policy_inputs import _read_input, validate_micro_table, _f1_identity, _binding
        micro_path = root / prefix / "policy-inputs/micro.json"
        f1_path = root / prefix / "policy-inputs/f1-freeze.json"
        micro, micro_digest = _read_input(micro_path)
        if micro_digest != optional["expected_micro_sha256"]:
            raise _identity("preserved micro input differs from the consumed original", "micro_digest")
        f1_digest, sources = _f1_identity(f1_path, checkout)
        binding = _binding(original_raw_digest, micro_digest, f1_digest, sources)
        memory = validate_micro_table(micro)
        primary = retained_policy.derive_retained_policy(record, memory, binding)
        reference_policy = policy_reference.reference_retained_policy(record, memory, binding)
        if canonical_payload_bytes(primary) != canonical_payload_bytes(reference_policy):
            raise _identity("independent retained policy derivations disagree", "retained_key_policy")
        original_view = {**reference_policy, "raw_series_root_digest": original_raw_digest}
        if canonical_payload_bytes(original_view) != canonical_payload_bytes(original_policy["retained_key_policy"]):
            raise _identity("preserved retained policy differs from the independent nine-K derivation", "retained_key_policy")
        for key, value in contracts.retained_policy_decisions(reference_policy).items():
            if canonical_payload_bytes(original_policy[key]) != canonical_payload_bytes(value):
                raise _identity("a preserved policy decision differs from independent replay", key)
        if original_policy["analysis_digest"] != content_digest(dict(original_analysis)):
            raise _identity("policy does not bind the original analysis", "analysis_digest")
    check_ids = [check for check in contracts.VERIFIER_CHECK_IDS if not (unevaluated and check == "RV-08-POLICY")]
    expected_claims = sorted((set(verification.CLAIM_CONFIG) | set(claims)) - ({"policy-decision"} if unevaluated else set()))
    assessment = {"kind": "official-verification-assessment", "schema_version": 2, "evidence_origin": "real",
        "qualification_scope": "official", "subject": documents["admission-index.json"]["subject"],
        "status": "VERIFIED_CURRENT_BASELINE", "study_id": study, "raw_series_root_digest": original_raw_digest,
        "analysis_digest": content_digest(dict(original_analysis)), "policy_digest": content_digest(dict(original_policy)),
        "reference_id": verification.REFERENCE_ID, "check_ids": check_ids, "verified_claims": expected_claims,
        "verification_scope": PROFILE, "policy_verification_status": "NOT_EVALUATED" if unevaluated else "PASS",
        "not_evaluated_checks": ["RV-08-POLICY"] if unevaluated else []}
    if canonical_payload_bytes(assessment) != canonical_payload_bytes(documents["verification-assessment.json"]):
        raise _identity("original independent assessment differs from replay calculations", "verification-assessment")
    return record


def _verify_recorded_projection(root: Path, original_receipt: Mapping[str, Any], checkout: Path) -> None:
    """Rebuild old projection hashes in memory; never open an old absolute path."""
    from .history import record_for
    study = original_receipt["study_id"]
    changes = original_receipt["relocations"]
    validate_recorded_relocations(changes, study_id=study)
    parent = checkout / "target" / "pr15i-d3-c"
    create_directory(parent)
    scratch = Path(tempfile.mkdtemp(prefix="historical-proof-", dir=parent))
    original_rows, expected_rows = [], []
    try:
        for item in original_receipt["original_inputs"]:
            role, identity = item["input_role"], item["source_identity"]
            record = record_for(role, identity)
            if record is None or record.digest != item["sha256"]:
                raise _identity("a historical derivation input is not independently anchored", "history")
            fixed = f"history/inputs/{role}/{identity}/{_history_basename(role, identity)}"
            observed, _ = _observe(root, fixed, MAX_ARCHIVE_BYTES)
            if (observed.digest, observed.byte_length) != (item["sha256"], item["size_bytes"]):
                raise _identity("historical derivation input differs from preserved bytes", "history")
            if role == "retained-archive":
                sidecar, _ = _observe(root, fixed + ".sha256", 4 * 1_048_576)
                if (sidecar.digest, sidecar.byte_length) != (item["sidecar_sha256"], item["sidecar_size_bytes"]):
                    raise _identity("historical sidecar differs from its derivation identity", "history")
            elif item["sidecar_sha256"] is not None or item["sidecar_size_bytes"] is not None:
                raise _error(BM_SCHEMA_INVALID, "ZIP derivation cannot cite a retained sidecar", "history")
            original = scratch / identity
            members = list(_materialize_archive(provider_root=root, relative=fixed, destination=original))
            prefix = identity + "/" if study == STUDY_RETAINED_KEY else ""
            originals = {row["path"]: dict(row) for row in members}
            selected = [row for row in changes if (row["path"].startswith(prefix) if prefix else True)]
            by_file: dict[str, list[Mapping[str, Any]]] = {}
            for change in selected:
                path = change["path"][len(prefix):]
                if path not in originals or change["original_sha256"] != originals[path]["sha256"]:
                    raise _identity("recorded projection cites another original member", "relocations")
                by_file.setdefault(path, []).append(change)
            projected = dict(originals)
            if study == STUDY_CROSS_ENGINE:
                if set(by_file) != {"run.json"} or len(selected) != 1:
                    raise _identity("PR15D projection must change only its corpus path", "relocations")
                document = _json(original, "run.json")
                row = selected[0]
                if document["corpus_dir"] != row["old_value"]:
                    raise _identity("the recorded original corpus path differs", "relocations")
                document["corpus_dir"] = row["new_value"]
                payloads = {"run.json": canonical_document_bytes(document)}
            else:
                if set(by_file) != {"raw/build-provenance.json", "manifest.json", "raw/seal.json"}:
                    raise _identity("retained projection must cover its exact three documents", "relocations")
                provenance = _json(original, "raw/build-provenance.json", limit=MAX_DOCUMENT_BYTES)
                expected_pointers = {"/canonical_source_path"} | {f"/events/{index}/canonical_source" for index in range(len(provenance["events"]))}
                if {row["json_pointer"] for row in by_file["raw/build-provenance.json"]} != expected_pointers:
                    raise _identity("recorded provenance projection is incomplete", "relocations")
                new_sources = {row["new_value"] for row in by_file["raw/build-provenance.json"]}
                if len(new_sources) != 1 or not next(iter(new_sources)).endswith("/" + identity + "/compile-source"):
                    raise _identity("recorded canonical sources disagree", "relocations")
                for row in by_file["raw/build-provenance.json"]:
                    pointer = row["json_pointer"]
                    if pointer == "/canonical_source_path":
                        old = provenance["canonical_source_path"]
                        provenance["canonical_source_path"] = row["new_value"]
                    else:
                        index = int(pointer.split("/")[2])
                        old = provenance["events"][index]["canonical_source"]
                        provenance["events"][index]["canonical_source"] = row["new_value"]
                    if old != row["old_value"]:
                        raise _identity("recorded old provenance value differs", "relocations")
                payloads = {"raw/build-provenance.json": canonical_document_bytes(provenance)}
                document = _json(original, "manifest.json", limit=MAX_DOCUMENT_BYTES)
                row = by_file["manifest.json"][0]
                derived = _payload_digest(payloads["raw/build-provenance.json"]).removeprefix("sha256:")
                if len(by_file["manifest.json"]) != 1 or document["build_provenance_sha256"] != row["old_value"] or row["new_value"] != derived:
                    raise _identity("recorded manifest projection has another provenance digest", "relocations")
                document["build_provenance_sha256"] = derived
                payloads["manifest.json"] = canonical_document_bytes(document)
                seal = _json(original, "raw/seal.json", limit=MAX_DOCUMENT_BYTES)
                if len(by_file["raw/seal.json"]) != 2:
                    raise _identity("recorded seal projection must update exactly two members", "relocations")
                for row in by_file["raw/seal.json"]:
                    member = "raw/build-provenance.json" if row["json_pointer"] == "/files/raw~1build-provenance.json" else "manifest.json"
                    derived = _payload_digest(payloads[member]).removeprefix("sha256:")
                    if seal["files"][member] != row["old_value"] or derived != row["new_value"]:
                        raise _identity("recorded seal projection differs from the derived hashes", "relocations")
                    seal["files"][member] = derived
                payloads["raw/seal.json"] = canonical_document_bytes(seal)
            for path, payload in payloads.items():
                digest = _payload_digest(payload)
                if any(row["working_sha256"] != digest for row in by_file[path]):
                    raise _identity("recorded projected bytes do not match their exact transform", "relocations")
                projected[path] = {"path": path, "size_bytes": len(payload), "sha256": digest}
            original_rows.extend({**row, "path": prefix + row["path"]} for row in members)
            expected_rows.extend({**row, "path": prefix + row["path"]} for row in projected.values())
        if content_digest(sorted(original_rows, key=lambda row: row["path"])) != original_receipt["original_member_inventory_digest"] or content_digest(sorted(expected_rows, key=lambda row: row["path"])) != original_receipt["working_member_inventory_digest"]:
            raise _identity("recorded historical inventories differ from original and projected bytes", "derivation")
    finally:
        shutil.rmtree(scratch)


def _portable_history(*, root: Path, study: str, original_report: Mapping[str, Any], checkout: Path):
    from . import history
    inventory = history.validate_inventory(_json(root, f"history/inventories/{study}.json"))
    report = history.validate_report(original_report)
    selected_inventory = history._family_inventory(inventory, study)
    candidates = {(item["input_role"], item["source_identity"]): item for item in selected_inventory["candidates"]}
    entries = {(item["input_role"], item["source_identity"]): item for item in report["entries"]}
    if set(candidates) != set(entries):
        raise _identity("original history inventory/report identities differ", "history")
    ephemeral = []
    for key, entry in entries.items():
        if entry["status"] != history.STATUS_FOUND:
            if entry["normalized_rows"]:
                raise _identity("excluded original history observations cannot supply effects", "history")
            continue
        role, identity = key
        candidate = candidates[key]
        fixed = f"history/inputs/{role}/{identity}/{_history_basename(role, identity)}"
        observation, _ = _observe(root, fixed, _member_limit(fixed, "history"))
        if observation.digest != entry["input_digest"]:
            raise _identity("a consumed preserved history input differs from the original disclosure", "history")
        ephemeral.append({**candidate, "path": fixed})
    location_view = {"kind": history.INVENTORY_KIND, "schema_version": 1, "candidates": ephemeral}
    reopened, derivation = history.derive_history_entries(root, location_view, source_root=checkout)
    positive = {(item["input_role"], item["source_identity"]): item for item in reopened}
    output = [positive.get((entry["input_role"], entry["source_identity"]), entry) for entry in report["entries"]]
    if canonical_payload_bytes(output) != canonical_payload_bytes(report["entries"]):
        raise _identity("portable history differs from authenticated original disclosures", "history")
    if derivation is not None:
        original_receipt = _json(root, f"history/derivations/{study}/derivation.json", limit=MAX_DOCUMENT_BYTES)
        original_verifier = _json(root, f"history/derivations/{study}/original-verifier.json", limit=MAX_DOCUMENT_BYTES)
        history.require_derivation_equivalence(original_receipt, derivation["receipt"])
        _verify_recorded_projection(root, original_receipt, checkout)
        if canonical_payload_bytes(original_verifier) != canonical_payload_bytes(derivation["verifier"]):
            raise _identity("historical original-verifier output changed during replay", "history")
    return output


def _replay_study(*, root: Path, manifest: Mapping[str, Any], study: str, checkout: Path, scratch: Path) -> dict[str, Any]:
    from . import admission, history, relative_effects
    run = manifest["study_runs"][study]["run_id"]
    prefix = f"studies/{study}/{run}"
    freeze, template, original_config, host, corpus_manifest = _plain_original_freeze(root=root,
        prefix=prefix, manifest=manifest, checkout=checkout)
    documents, history_report, effects = _pure_qualification(root=root, prefix=prefix, freeze=freeze, template=template)
    if content_digest(documents["manifest.json"]) != manifest["study_runs"][study]["qualification_manifest_digest"]:
        raise _identity("the original qualification manifest differs from its terminal binding", "qualification_manifest_digest")
    original_raw = root / prefix / "raw"
    original_digest = _verify_original_raw(original_raw, study, documents["admission-index.json"])
    if study == STUDY_RETAINED_KEY:
        _verify_current_retained_archives(root, prefix)
    _restore_qa(baseline_root=root, prefix=prefix, freeze=freeze,
        output_root=root / prefix / "qualification", raw_root=original_raw)
    corpus = _regenerate_corpus(replay_checkout=checkout, destination=scratch / study / "corpus",
        expected_digest=freeze.corpus_manifest_digest, expected_manifest=corpus_manifest)
    working = scratch / study / "raw"
    relocations = _working_raw(original=original_raw, working=working, checkout=checkout, study=study, corpus=corpus)
    record = _independent_statistics(root=root, prefix=prefix, working=working, checkout=checkout,
        freeze=freeze, template=template, corpus=corpus, original_raw_digest=original_digest,
        documents=documents, original_config=original_config)
    rows = history.current_effect_rows(analysis=documents["analysis.json"], freeze=freeze, host_preflight=host)
    entries = _portable_history(root=root, study=study, original_report=history_report, checkout=checkout)
    header = {"baseline_id": freeze.baseline_id, "study_id": study, "source_commit": freeze.source_commit,
        "current_raw_digest": original_digest}
    expected_history = history.report_payload(entries=entries, **header)
    expected_effects = relative_effects.disclosure_payload(rows=rows,
        comparisons=relative_effects.compare_effect_rows(historical_rows=[row for entry in entries for row in entry["normalized_rows"]], current_rows=rows), **header)
    if canonical_payload_bytes(expected_history) != canonical_payload_bytes(history_report) or canonical_payload_bytes(expected_effects) != canonical_payload_bytes(effects):
        raise _identity("original disclosures differ from complete independently replayed effects", "disclosures")
    relative_effects.validate_disclosure(effects)
    if _verify_original_raw(original_raw, study, documents["admission-index.json"]) != original_digest:
        raise _identity("original raw changed during replay", "raw")
    if admission.admitted_inventory_digest(record) != record.raw_series_root_digest:
        raise _identity("projected raw changed during replay", "raw")
    return {"study_id": study, "run_id": run, "original_raw_digest": original_digest,
        "working_raw_digest": record.raw_series_root_digest, "relocations": relocations,
        "history_report_digest": content_digest(history_report), "relative_effects_digest": content_digest(effects)}


def open_verified_baseline_evidence(*, baseline_root: Path, replay_checkout: Path | None = None) -> VerifiedBaselineEvidence:
    """Authenticate Git-bound originals and run only the independent offline chain."""
    root = require_safe_root(baseline_root)
    checkout = require_safe_root(replay_checkout if replay_checkout is not None else repository_root())
    observation, _ = _observe(root, "baseline-manifest.json", MAX_DOCUMENT_BYTES)
    manifest = _validate_manifest(_json(root, "baseline-manifest.json", limit=MAX_DOCUMENT_BYTES))
    if manifest["baseline_id"] != root.name:
        raise _identity("baseline UUID differs from its exact namespace", "baseline_id")
    originals = _authenticate_members(root, manifest)
    _require_checkpoint_graph(root, manifest)
    if manifest["status"] != "COMPLETE" or not baseline_ready_for_finalization(baseline_root=root):
        raise _error(BM_EVIDENCE_UNAVAILABLE, "a stopped or incomplete baseline cannot pass replay acceptance", "study_runs")
    evidence_commit, checkout_identity = _verify_source_link(root, manifest, checkout)
    parent = checkout / "target" / "pr15i-d3-c"
    create_directory(parent)
    scratch = Path(tempfile.mkdtemp(prefix="baseline-replay-", dir=parent))
    try:
        replayed = [_replay_study(root=root, manifest=manifest, study=study, checkout=checkout, scratch=scratch)
            for study in STUDIES]
        _recheck(observation)
        for original in originals:
            _recheck(original)
        if _git(checkout, "rev-parse", "--verify", "HEAD") != evidence_commit:
            raise _identity("replay checkout changed during validation", "replay_checkout")
        if _verify_source_link(root, manifest, checkout) != (evidence_commit, checkout_identity):
            raise _identity("replay checkout identity changed during validation", "replay_checkout")
        return VerifiedBaselineEvidence(baseline_id=manifest["baseline_id"], source_commit=manifest["source_commit"],
            source_file_set_digest=manifest["source_file_set_digest"], manifest_digest=content_digest(manifest),
            evidence_commit=evidence_commit, replay_checkout_identity=checkout_identity, status="REPLAY_VERIFIED",
            _root=root, _sentinel=_EVIDENCE_SENTINEL, _replay_results=canonical_payload_bytes(replayed))
    finally:
        shutil.rmtree(scratch)


def replay_baseline_evidence(*, baseline_root: Path, replay_checkout: Path | None = None) -> dict[str, Any]:
    """Publish a separate replay receipt after complete independent verification."""
    capability = open_verified_baseline_evidence(baseline_root=baseline_root, replay_checkout=replay_checkout)
    replay_id = str(uuid.uuid4())
    from ..config.codec import loads_json, decode_text
    receipt = {"kind": "official-baseline-replay", "schema_version": 1, "baseline_id": capability.baseline_id,
        "replay_id": replay_id, "status": "REPLAY_VERIFIED", "baseline_manifest_digest": capability.manifest_digest,
        "measured_source_commit": capability.source_commit, "source_file_set_digest": capability.source_file_set_digest,
        "evidence_commit": capability.evidence_commit, "replay_checkout_identity": capability.replay_checkout_identity,
        "studies": loads_json(decode_text(capability._replay_results))}
    checkout = repository_root() if replay_checkout is None else replay_checkout
    destination = Path(checkout) / "benchmark-results" / "replays" / capability.baseline_id
    create_directory(destination)
    write_record(destination, replay_id + ".json", receipt)
    return receipt


__all__ = ["WorkingCopyProjection", "VerifiedBaselineEvidence", "validate_baseline_evidence_root",
    "preserve_baseline_checkpoint", "baseline_ready_for_finalization", "finalize_baseline_evidence",
    "open_verified_baseline_evidence", "replay_baseline_evidence", "project_retained_working_copy"]


_CREDENTIAL_FIELDS = frozenset({
    "aws_access_key_id", "aws_secret_access_key", "aws_session_token", "access_key", "secret_key",
    "quervant_rustfs_access_key", "quervant_rustfs_secret_key", "rustfs_access_key", "rustfs_secret_key",
    "github_token", "gh_token", "api_key", "access_token", "refresh_token", "secret_token", "password",
})
_REDACTED_VALUES = frozenset({"", "[redacted]", "<redacted>", "***", "null", "none"})
_CREDENTIAL_PATTERN = re.compile(
    rb"(?i)(?<![a-z0-9_])(" + b"|".join(name.encode("ascii") for name in sorted(_CREDENTIAL_FIELDS))
    + rb")[\"']?\s*[:=]\s*[\"']?([^\s\"',;{}]+)"
)
_AUTHORIZATION_PATTERN = re.compile(rb"(?i)authorization[\"']?\s*[:=]\s*[\"']?(?:bearer|basic)\s+([^\s\"',;{}]+)")


def _check_public_chunk(payload: bytes, relative: str) -> None:
    for match in _CREDENTIAL_PATTERN.finditer(payload):
        value = match.group(2).decode("utf-8", errors="replace").casefold()
        if value not in _REDACTED_VALUES:
            raise BenchError(BM_UNSAFE_INPUT, "sealed evidence contains an unredacted credential field",
                field_path=match.group(1).decode("ascii").lower(), reference=relative)
    for match in _AUTHORIZATION_PATTERN.finditer(payload):
        if match.group(1).decode("utf-8", errors="replace").casefold() not in _REDACTED_VALUES:
            raise BenchError(BM_UNSAFE_INPUT, "sealed evidence contains an unredacted authorization header",
                field_path="authorization", reference=relative)


def _scan_public_stream(stream: Any, relative: str, limit: int) -> None:
    from .history import _parse
    captured = bytearray() if relative.endswith(".json") else None
    total = 0
    tail = b""
    while True:
        chunk = stream.read(min(1_048_576, limit - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise _error(BM_UNSAFE_INPUT, "public evidence exceeds its owning byte bound", relative)
        _check_public_chunk(tail + chunk, relative)
        tail = chunk[-4096:]
        if captured is not None:
            captured.extend(chunk)
    if captured is not None:
        # Owner contracts still validate their exact schema separately. This pass
        # checks named credential fields even if their value is a nested object.
        document = _parse(bytes(captured), relative, decimals=False)
        stack = [document]
        while stack:
            item = stack.pop()
            if isinstance(item, Mapping):
                for key, value in item.items():
                    if key.casefold().replace("-", "_") in _CREDENTIAL_FIELDS:
                        if value is not None and not (type(value) is str and value.casefold() in _REDACTED_VALUES):
                            raise BenchError(BM_UNSAFE_INPUT, "sealed evidence contains an unredacted credential field",
                                field_path=key, reference=relative)
                    stack.append(value)
            elif isinstance(item, list):
                stack.extend(item)


def _require_public_safe_member(observation: Any) -> None:
    """Reject fixed unredacted fields before export; sealed originals stay intact."""
    import tarfile
    import zipfile
    from ..evidence.archives import inspect_tar_gz, inspect_zip
    name = observation.relative
    if name.endswith((".tar.gz", ".zip")):
        inspected = inspect_tar_gz(observation.root, name) if name.endswith(".tar.gz") else inspect_zip(observation.root, name)
        expected = {member.name: member for member in inspected}
        with open_regular_beneath(observation.root, name) as handle:
            archive = tarfile.open(fileobj=handle, mode="r:gz") if name.endswith(".tar.gz") else zipfile.ZipFile(handle)
            with archive:
                for info in (archive if name.endswith(".tar.gz") else archive.infolist()):
                    is_directory = info.isdir() if name.endswith(".tar.gz") else info.is_dir()
                    if is_directory:
                        continue
                    member_name = info.name if name.endswith(".tar.gz") else info.filename
                    member = expected[member_name]
                    if member_name.endswith((".exe", ".jar", ".dll", ".so", ".a")):
                        raise _error(BM_UNSAFE_INPUT, "runtime binaries are not committable benchmark evidence", member_name)
                    data = archive.extractfile(info) if name.endswith(".tar.gz") else archive.open(info)
                    if data is None:
                        raise _error(BM_UNSAFE_INPUT, "a preserved archive member has no regular stream", member_name)
                    with data:
                        _scan_public_stream(data, member_name, min(MAX_DOCUMENT_BYTES, member.byte_length))
    else:
        with open_regular_beneath(observation.root, name) as handle:
            _scan_public_stream(handle, name, observation.max_bytes)
    _recheck(observation)


def _lexical_original_path(value: object, field: str) -> Path:
    """Validate original location syntax only; offline never probes producer paths."""
    if type(value) is not str or not value or "\x00" in value:
        raise _error(BM_SCHEMA_INVALID, "an original location must be a string", field)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or str(path) != value:
        raise _error(BM_UNSAFE_INPUT, "an original location must be normalized and absolute", field)
    return path


def _validate_original_config_data(document: Mapping[str, Any], *, study: str) -> None:
    from .operation_config import CONFIG_KEYS_V2, CONFIG_KIND, _PATHS
    from ..config.identity import validate_semantic_id
    if not isinstance(document, Mapping) or set(document) != CONFIG_KEYS_V2:
        raise _error(BM_SCHEMA_INVALID, "the original config has an unexpected shape", "operation-config")
    if document["kind"] != CONFIG_KIND or type(document["schema_version"]) is not int or document["schema_version"] != 2 or document["acceptance_profile"] != PROFILE:
        raise _error(BM_SCHEMA_INVALID, "the original config is not current baseline version two", "operation-config")
    paths = {name: _lexical_original_path(document[name], name) for name in _PATHS}
    validate_semantic_id(document["approval_source_identity"], "approval_source_identity")
    for field in ("adapter_cpu", "controller_cpu"):
        if type(document[field]) is not int or document[field] < 0:
            raise _error(BM_SCHEMA_INVALID, "original CPU identities must be nonnegative integers", field)
    if document["adapter_cpu"] == document["controller_cpu"]:
        raise _error(BM_UNSAFE_INPUT, "the original operation used one CPU for both roles", "cpu_pair")
    if paths["workspace"] == paths["output_base"] or paths["workspace"] in paths["output_base"].parents or paths["output_base"] in paths["workspace"].parents:
        raise _error(BM_UNSAFE_INPUT, "original raw and qualified output locations overlap", "workspace")
    for name in ("workspace", "output_base"):
        path, source = paths[name], paths["source_root"]
        if path == source or path in source.parents:
            raise _error(BM_UNSAFE_INPUT, "an original output contains its source checkout", name)
        allowed = [source / "benchmark-results"]
        if name == "workspace":
            allowed.append(source / "target" / "pr15i-d3-c")
        if source in path.parents and not any(root == path or root in path.parents for root in allowed):
            raise _error(BM_UNSAFE_INPUT, "an original output lies outside its approved namespace", name)
    baseline = document["baseline"]
    if not isinstance(baseline, Mapping) or set(baseline) != {"baseline_id", "evidence_root", "history_inventory", "runtime_freeze_path"}:
        raise _error(BM_SCHEMA_INVALID, "the original baseline locations are malformed", "baseline")
    identifier = validate_uuid4(baseline["baseline_id"], "baseline_id")
    evidence = _lexical_original_path(baseline["evidence_root"], "evidence_root")
    if evidence.parts[-3:] != ("benchmark-results", "baselines", identifier):
        raise _error(BM_UNSAFE_INPUT, "the original baseline location has another namespace", "evidence_root")
    _lexical_original_path(baseline["history_inventory"], "history_inventory")
    if baseline["runtime_freeze_path"] is not None:
        _lexical_original_path(baseline["runtime_freeze_path"], "runtime_freeze_path")
    if study == STUDY_RETAINED_KEY and baseline["runtime_freeze_path"] is None:
        raise _error(BM_SCHEMA_INVALID, "retained baseline requires its current runtime freeze", "runtime_freeze_path")
    optional = document["policy_inputs"]
    if study == STUDY_CROSS_ENGINE and (baseline["runtime_freeze_path"] is not None or optional is not None):
        raise _error(BM_UNSAFE_INPUT, "cross-engine cannot consume retained-only inputs", "policy_inputs")
    if optional is not None:
        if not isinstance(optional, Mapping) or set(optional) != {"micro_json", "expected_micro_sha256", "f1_receipt"}:
            raise _error(BM_SCHEMA_INVALID, "the original policy inputs are malformed", "policy_inputs")
        for name in ("micro_json", "f1_receipt"):
            _lexical_original_path(optional[name], "policy_inputs." + name)
        validate_digest(optional["expected_micro_sha256"], "expected_micro_sha256")


def _validate_original_prepared_data(document: object, *, study: str) -> None:
    """Validate recorded preparation without opening any producer executable."""
    from .cross_engine_backend import _PREPARED_KEYS, PREPARED_SCHEMA, ENGINES, MAX_FILES, MAX_FILE_BYTES
    from .retained_backend import KIND as RETAINED_PREPARED_KIND
    from .protocols import D3C_BASE_COMMIT, D3C_EXPERIMENT_COMMIT, validate_source_commit
    keys = _PREPARED_KEYS if study == STUDY_CROSS_ENGINE else {"schema", "source_root", "corpus_dir", "protocol_digest", "corpus_digest", "binaries"}
    if not isinstance(document, Mapping) or set(document) != keys:
        raise _error(BM_SCHEMA_INVALID, "the original preparation has an unexpected shape", "prepared")
    expected_schema = PREPARED_SCHEMA if study == STUDY_CROSS_ENGINE else RETAINED_PREPARED_KIND
    if document["schema"] != expected_schema:
        raise _error(BM_SCHEMA_INVALID, "the original preparation has an unregistered schema", "prepared")
    for name in ("source_root", "corpus_dir"):
        _lexical_original_path(document[name], name)
    binaries = document["binaries"]
    expected = set(ENGINES) if study == STUDY_CROSS_ENGINE else {"A", "B"}
    if not isinstance(binaries, Mapping) or set(binaries) != expected:
        raise _error(BM_SCHEMA_INVALID, "prepared binaries must cover the exact arm set", "binaries")
    if study == STUDY_CROSS_ENGINE:
        _lexical_original_path(document["build_root"], "build_root")
        validate_source_commit(document["source_sha"], "source_sha")
        for name in ("adapter_source_digest", "corpus_manifest_digest", "manifest_digest"):
            validate_digest(document[name], name)
        metadata = document["adapter_metadata"]
        if not isinstance(metadata, Mapping) or set(metadata) != set(ENGINES) or any(not isinstance(item, Mapping) for item in metadata.values()):
            raise _error(BM_SCHEMA_INVALID, "prepared metadata must cover the exact engine set", "adapter_metadata")

        def files(rows, field):
            if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
                raise _error(BM_SCHEMA_INVALID, "prepared files must be a bounded nonempty list", field)
            paths = []
            for row in rows:
                if not isinstance(row, Mapping) or set(row) != {"path", "size_bytes", "sha256"}:
                    raise _error(BM_SCHEMA_INVALID, "a prepared file has an unexpected shape", field)
                paths.append(validate_relative_member(row["path"]))
                if type(row["size_bytes"]) is not int or not 0 <= row["size_bytes"] <= MAX_FILE_BYTES:
                    raise _error(BM_SCHEMA_INVALID, "a prepared file size is outside its bound", field)
                validate_digest(row["sha256"], field)
            if paths != sorted(set(paths)) or len({path.casefold() for path in paths}) != len(paths):
                raise _error(BM_UNSAFE_INPUT, "prepared file paths duplicate, collide or are unsorted", field)
            return paths

        for engine, item in binaries.items():
            if not isinstance(item, Mapping) or set(item) != {"entrypoint", "files"}:
                raise _error(BM_SCHEMA_INVALID, "a prepared engine has an unexpected shape", "binaries")
            entrypoint = validate_relative_member(item["entrypoint"])
            if entrypoint not in files(item["files"], "binaries." + engine):
                raise _identity("a prepared entrypoint is absent from its runtime inventory", "binaries")
        files(document["corpus_files"], "corpus_files")
    else:
        for name in ("protocol_digest", "corpus_digest"):
            validate_digest(document[name], name)
        for arm, source in (("A", D3C_BASE_COMMIT), ("B", D3C_EXPERIMENT_COMMIT)):
            item = binaries[arm]
            if not isinstance(item, Mapping) or set(item) != {"binary", "sha256", "bytes", "argv", "feature", "source_sha"}:
                raise _error(BM_SCHEMA_INVALID, "a prepared retained arm has an unexpected shape", "binaries")
            _lexical_original_path(item["binary"], "binary")
            if type(item["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise _error(BM_SCHEMA_INVALID, "a retained binary digest must be lowercase raw hex", "binaries")
            if type(item["bytes"]) is not int or not 0 <= item["bytes"] <= 536_870_912:
                raise _error(BM_SCHEMA_INVALID, "a retained binary size is outside its bound", "binaries")
            if not isinstance(item["argv"], list) or not item["argv"] or any(type(value) is not str or not value or "\x00" in value for value in item["argv"]):
                raise _error(BM_SCHEMA_INVALID, "a retained command must be a nonempty string vector", "binaries")
            if item["source_sha"] != source or item["feature"] is not (arm == "B"):
                raise _identity("a retained arm differs from the frozen source/feature", "binaries")
        if binaries["A"]["sha256"] == binaries["B"]["sha256"]:
            raise _identity("retained BASE and experiment binaries must differ", "binaries")

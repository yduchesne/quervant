"""Current-source retained execution freeze, independent of historical T6.

Preparation can produce this candidate before QA or G0 exist.  It grants no
acquisition authority: production callers must also hold a refreshed independent
G0 capability binding the raw envelope digest.  Every reopen observes the actual
Git blobs, prepared executables/corpus, host, schedule and approved output root.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..config.codec import canonical_document_bytes, canonical_payload_bytes, content_digest, decode_text, loads_json
from ..config.errors import BM_EVIDENCE_UNAVAILABLE, BM_IDENTITY_INVALID, BM_PUBLICATION_CONFLICT, BM_UNSAFE_INPUT, BenchError
from ..config.identity import validate_digest, validate_uuid4, validate_source_commit
from ..evidence.paths import open_regular_beneath
from ..evidence.provenance import repository_root
from ..qualification.identity import compute_source_set_digest, source_roster
from .operation_config import OperationConfig, absolute_path
from .operation_store import create_directory, write_record
from .protocols import (
    CURRENT_BASELINE_PROFILE, D3C_CAMPAIGN_NAMES, D3C_CONTROL_NAME, STUDY_RETAINED_KEY,
    read_approved_template, template_path, validate_template, validate_root_identity, verify_backend_protocol,
)
from .retained_backend import PreparedRetainedKey, legacy_runner, load_prepared_retained_key

BACKEND_RECEIPT = "target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json"
PROTOCOL_SHA256 = "c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c"
EXTRA_PROTECTED = (
    "benchmarks/pr15i_d3_c/run.py", "benchmarks/pr15i_d3_c/verify.py",
    "benchmarks/pr15i_d3_c/protocol_v3r3.json", "benchmarks/pr15i_d3_c/host_topology.py",
    "benchmarks/pr15i_d3_c/tooling_manifest.json", "benchmarks/pr15d/harness/run.py",
    "benchmarks/pr15d/corpus/generate.py", "benchmarks/pr15d/corpus/oracle.py",
    "benchmarks/scripts/check-pr07-contention.py", "benchmarks/official-protocols/retained-key-topk-v2.json",
)
ENVELOPE_KEYS = frozenset((
    "kind", "schema_version", "origin", "baseline_id", "study_id", "source_commit",
    "source_tree_sha", "source_file_set_digest", "design_digest", "backend_protocol_digest",
    "backend_receipt_digest", "prepared_manifest_digest", "binary_manifest_digest",
    "corpus_manifest_digest", "host_preflight_digest", "adapter_cpu", "controller_cpu",
    "control_schedule_digest", "treatment_schedule_digest", "approved_output_root_identity",
))
RECEIPT_KEYS = frozenset((
    "schema", "protocol_sha256", "control_name", "campaign_names", "t6_commit",
    "tooling_manifest_sha256", "protected_files", "receipt_origin",
))
_ISSUER = object()


def _fail(message: str, field_path: str = "runtime_freeze", code: str = BM_IDENTITY_INVALID) -> BenchError:
    return BenchError(code, message, field_path=field_path)


def _raw_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _read(path: Path, *, limit: int = 1_048_576) -> bytes:
    """Read twice through descriptors anchored at /, including inode identity."""
    candidate = absolute_path(str(path), "runtime_freeze_path")
    observations = []
    for _ in range(2):
        try:
            handle = open_regular_beneath(Path(candidate.anchor), candidate.relative_to(candidate.anchor).as_posix())
        except OSError as error:
            raise _fail("runtime input could not be opened", code=BM_UNSAFE_INPUT) from error
        close_error: OSError | None = None
        try:
            before = os.fstat(handle.fileno())
            if before.st_nlink != 1 or before.st_size > limit:
                raise _fail("runtime inputs must be bounded single-link regular files", code=BM_UNSAFE_INPUT)
            payload = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
            if len(payload) > limit or len(payload) != before.st_size or _snapshot(before) != _snapshot(after):
                raise _fail("runtime input changed during observation", code=BM_UNSAFE_INPUT)
        except OSError as error:
            raise _fail("runtime input could not be read", code=BM_UNSAFE_INPUT) from error
        finally:
            try:
                handle.close()
            except OSError as error:
                close_error = error
        # A pending primary failure propagates through finally. Report close
        # failure only after an otherwise successful observation.
        if close_error is not None:
            raise _fail("runtime input could not be closed", code=BM_UNSAFE_INPUT) from close_error
        observations.append((_snapshot(after), payload))
    if observations[0] != observations[1]:
        raise _fail("runtime input was replaced during observation", code=BM_UNSAFE_INPUT)
    return observations[0][1]


def _document(payload: bytes, keys: frozenset[str]) -> dict[str, Any]:
    value = loads_json(decode_text(payload))
    if type(value) is not dict or set(value) != keys or canonical_document_bytes(value) != payload:
        raise _fail("runtime document has an unregistered shape or encoding")
    return value


def validate_runtime_freeze_document(document: object, *, template: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only data; offline callers independently verify all original pins.

    This function performs no file, host, prepared-binary or capability lookup.
    Live factories additionally reconstruct the whole document from observations.
    """
    approved = validate_template(template)
    if (type(document) is not dict or set(document) != ENVELOPE_KEYS
            or type(document.get("schema_version")) is not int or document["schema_version"] != 2
            or document.get("kind") != "official-current-runtime-freeze"
            or document.get("origin") != "current" or document.get("study_id") != STUDY_RETAINED_KEY
            or approved["schema_version"] != 2 or approved["study_id"] != STUDY_RETAINED_KEY):
        raise _fail("runtime envelope does not have the closed retained v2 contract")
    validate_uuid4(document["baseline_id"], "baseline_id")
    validate_source_commit(document["source_commit"])
    validate_root_identity(document["approved_output_root_identity"], "approved_output_root_identity")
    for name in ("source_tree_sha", "source_file_set_digest", "design_digest", "backend_protocol_digest",
                 "backend_receipt_digest", "prepared_manifest_digest", "binary_manifest_digest",
                 "corpus_manifest_digest", "host_preflight_digest", "control_schedule_digest", "treatment_schedule_digest"):
        validate_digest(document[name], name)
    if (any(type(document[name]) is not int or document[name] < 0 for name in ("adapter_cpu", "controller_cpu"))
            or document["adapter_cpu"] == document["controller_cpu"]):
        raise _fail("runtime CPU identities must be distinct nonnegative integers", "cpu_pair", BM_UNSAFE_INPUT)
    schedule = approved["schedule"]
    expected = {
        "design_digest": content_digest(approved), "backend_protocol_digest": "sha256:" + PROTOCOL_SHA256,
        "control_schedule_digest": content_digest({k: v for k, v in schedule.items() if k.startswith("control_")}),
        "treatment_schedule_digest": content_digest({k: v for k, v in schedule.items() if not k.startswith("control_")}),
    }
    for name, value in expected.items():
        if document[name] != value:
            raise _fail("runtime profile/schedule identity differs from its design", name)
    return dict(document)


@dataclass(frozen=True)
class VerifiedCurrentRuntimeFreeze:
    """Factory-issued, read-only observation; never a substitute for G0."""

    digest: str
    document: Mapping[str, Any]
    _root: Path = field(repr=False)
    _envelope_path: Path = field(repr=False)
    _prepared_manifest: Path = field(repr=False)
    _identity: bytes = field(repr=False)
    _issuer: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class _CpuSelection:
    adapter_cpu: int
    controller_cpu: int


def _source(root: Path) -> tuple[str, str, str, dict[str, str]]:
    from .operation_identity import git_identity

    if root.resolve() != repository_root().resolve():
        raise _fail("runtime source must be the executing checkout", "source_root")
    commit, tree = git_identity(root)
    detached = subprocess.run(["git", "-C", str(root), "symbolic-ref", "-q", "HEAD"],
                              capture_output=True, check=False, timeout=30)
    if detached.returncode != 1:
        raise _fail("current runtime requires an owned detached execution checkout", "source_root")
    protected = {}
    for relative in sorted(set(source_roster(root)).union(EXTRA_PROTECTED)):
        size = subprocess.run(["git", "-C", str(root), "cat-file", "-s", f"{commit}:{relative}"],
                              capture_output=True, check=False, timeout=30)
        if size.returncode or not size.stdout.strip().isdigit() or int(size.stdout) > 268_435_456:
            raise _fail("a protected Git blob is missing or exceeds the fixed source budget", "protected_files", BM_UNSAFE_INPUT)
        blob = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{relative}"],
                              capture_output=True, check=False, timeout=30)
        if blob.returncode:
            raise _fail("a required protected Git blob is missing", "protected_files")
        actual = _read(root / relative, limit=268_435_456)
        if actual != blob.stdout:
            raise _fail("a protected working file differs from its Git blob", "protected_files")
        protected[relative] = hashlib.sha256(actual).hexdigest()
    return commit, tree, compute_source_set_digest(root), protected


def _observe(*, root: Path, envelope_path: Path, prepared_manifest: Path,
             template: Mapping[str, Any], baseline_id: str, output_root: str,
             adapter_cpu: int, controller_cpu: int) -> tuple[dict[str, Any], dict[str, Any], PreparedRetainedKey]:
    """QA-independent observations: do not call observe_identities here."""
    from .operation_identity import observe_host

    template = validate_template(template)
    if template["schema_version"] != 2 or template["study_id"] != STUDY_RETAINED_KEY:
        raise _fail("current runtime needs the registered retained v2 profile", "schema_version")
    validate_uuid4(baseline_id, "baseline_id")
    output = absolute_path(output_root, "approved_output_root_identity")
    expected_template, _ = read_approved_template(template_path(STUDY_RETAINED_KEY, root, version=2), content_digest(dict(template)))
    if canonical_payload_bytes(template) != canonical_payload_bytes(expected_template):
        raise _fail("runtime template differs from the registered design", "design_digest")
    commit, tree, source_digest, protected = _source(root)
    prepared = load_prepared_retained_key(prepared_manifest, root=root)
    if prepared.source_root != root:
        raise _fail("prepared inputs belong to another checkout", "source_root")
    backend = verify_backend_protocol(template, root)
    if backend["raw_digest"] != "sha256:" + PROTOCOL_SHA256:
        raise _fail("the retained backend protocol differs", "backend_protocol_digest")
    # The original controller chooses this pair itself. Check the same selection
    # before recording a candidate rather than promising an unusable CPU pair.
    runner = legacy_runner()
    if tuple(runner.cpus()) != (adapter_cpu, controller_cpu):
        raise _fail("runtime CPU pair differs from the frozen controller", "cpu_pair")
    host = observe_host(_CpuSelection(adapter_cpu, controller_cpu), template)
    tooling = _read(root / "benchmarks/pr15i_d3_c/tooling_manifest.json")
    receipt = {
        "schema": "pr15i-d3c-freeze-v1", "protocol_sha256": PROTOCOL_SHA256,
        "control_name": D3C_CONTROL_NAME, "campaign_names": list(D3C_CAMPAIGN_NAMES),
        "t6_commit": commit, "tooling_manifest_sha256": hashlib.sha256(tooling).hexdigest(),
        "protected_files": protected, "receipt_origin": CURRENT_BASELINE_PROFILE,
    }
    schedule = template["schedule"]
    envelope = {
        "kind": "official-current-runtime-freeze", "schema_version": 2, "origin": "current",
        "baseline_id": baseline_id, "study_id": STUDY_RETAINED_KEY, "source_commit": commit,
        "source_tree_sha": tree, "source_file_set_digest": source_digest,
        "design_digest": content_digest(dict(template)), "backend_protocol_digest": backend["raw_digest"],
        "backend_receipt_digest": _raw_digest(canonical_document_bytes(receipt)),
        "prepared_manifest_digest": _raw_digest(_read(prepared_manifest)),
        "binary_manifest_digest": prepared.binary_digest, "corpus_manifest_digest": prepared.manifest["corpus_digest"],
        "host_preflight_digest": content_digest(host), "adapter_cpu": adapter_cpu, "controller_cpu": controller_cpu,
        "control_schedule_digest": content_digest({k: v for k, v in schedule.items() if k.startswith("control_")}),
        "treatment_schedule_digest": content_digest({k: v for k, v in schedule.items() if not k.startswith("control_")}),
        "approved_output_root_identity": str(output),
    }
    return receipt, envelope, prepared


def _config_inputs(config: OperationConfig, template: Mapping[str, Any], prepared: PreparedRetainedKey | None) -> dict[str, Any]:
    if type(config) is not OperationConfig or config.profile_version != 2:
        raise _fail("current runtime requires a v2 operation config", "schema_version")
    baseline = config.document["baseline"]
    if config.document["acceptance_profile"] != CURRENT_BASELINE_PROFILE or baseline["runtime_freeze_path"] is None:
        raise _fail("retained v2 runtime path/profile is missing", "baseline.runtime_freeze_path")
    root = config.path("source_root")
    manifest = config.path("prepared_manifest")
    if prepared is not None and (type(prepared) is not PreparedRetainedKey or prepared.manifest_path != manifest):
        raise _fail("supplied preparation belongs to another operation", "prepared_manifest")
    return {
        "root": root, "envelope_path": absolute_path(baseline["runtime_freeze_path"], "baseline.runtime_freeze_path"),
        "prepared_manifest": manifest, "template": template, "baseline_id": baseline["baseline_id"],
        "output_root": str(config.path("output_base")), "adapter_cpu": config.adapter_cpu,
        "controller_cpu": config.controller_cpu,
    }


def _open_observed(inputs: Mapping[str, Any], *, expected_digest: str | None = None) -> VerifiedCurrentRuntimeFreeze:
    envelope_path = inputs["envelope_path"]
    receipt_path = inputs["root"] / BACKEND_RECEIPT
    raw_envelope, raw_receipt = _read(envelope_path), _read(receipt_path)
    document = validate_runtime_freeze_document(_document(raw_envelope, ENVELOPE_KEYS), template=inputs["template"])
    receipt = _document(raw_receipt, RECEIPT_KEYS)
    digest = _raw_digest(raw_envelope)
    if expected_digest is not None and digest != validate_digest(expected_digest, "runtime_freeze_digest"):
        raise _fail("runtime envelope differs from the independently approved bytes", "runtime_freeze_digest")
    expected_receipt, expected, _prepared = _observe(**inputs)
    if (canonical_payload_bytes(document) != canonical_payload_bytes(expected)
            or canonical_payload_bytes(receipt) != canonical_payload_bytes(expected_receipt)
            or document["backend_receipt_digest"] != _raw_digest(raw_receipt)):
        raise _fail("current runtime identities or complete protected roster changed")
    # Retain every original backend check after the stronger closed-roster check.
    runner = legacy_runner()
    for campaign in (D3C_CONTROL_NAME, *D3C_CAMPAIGN_NAMES):
        runner.require_freeze(campaign)
    if _read(envelope_path) != raw_envelope or _read(receipt_path) != raw_receipt:
        raise _fail("runtime documents changed during revalidation")
    from .operation_identity import git_identity
    if (git_identity(inputs["root"]) != (document["source_commit"], document["source_tree_sha"])
            or compute_source_set_digest(inputs["root"]) != document["source_file_set_digest"]):
        raise _fail("runtime source changed during revalidation", "source_commit")
    if _raw_digest(_read(inputs["prepared_manifest"])) != document["prepared_manifest_digest"]:
        raise _fail("runtime preparation changed during revalidation", "prepared_manifest_digest")
    return VerifiedCurrentRuntimeFreeze(digest, MappingProxyType(document), inputs["root"], envelope_path,
                                       inputs["prepared_manifest"], canonical_payload_bytes(document), _ISSUER)


def prepare_current_runtime_freeze(*, config: OperationConfig, template: Mapping[str, Any],
                                   prepared: PreparedRetainedKey) -> VerifiedCurrentRuntimeFreeze:
    """Exclusively create both candidates, or reopen an identical complete pair."""
    inputs = _config_inputs(config, template, prepared)
    receipt_path = inputs["root"] / BACKEND_RECEIPT
    envelope_path = inputs["envelope_path"]
    present = (os.path.lexists(receipt_path), os.path.lexists(envelope_path))
    if any(present):
        if not all(present):
            raise _fail("partial runtime creation is preserved; use a new owned execution checkout",
                        code=BM_PUBLICATION_CONFLICT)
        return _open_observed(inputs)
    receipt, envelope, _fresh = _observe(**inputs)
    if envelope_path == receipt_path:
        raise _fail("runtime envelope and compatibility receipt paths collide", code=BM_UNSAFE_INPUT)
    create_directory(receipt_path.parent)
    create_directory(envelope_path.parent)
    write_record(receipt_path.parent, receipt_path.name, receipt)
    write_record(envelope_path.parent, envelope_path.name, envelope)
    return _open_observed(inputs)


def open_current_runtime_freeze(*, config: OperationConfig, template: Mapping[str, Any],
                               prepared: PreparedRetainedKey | None = None) -> VerifiedCurrentRuntimeFreeze:
    return _open_observed(_config_inputs(config, template, prepared))


def open_worker_runtime_freeze(*, root: Path, envelope_path: Path, prepared_manifest: Path,
                              expected_digest: str, profile_version: int) -> VerifiedCurrentRuntimeFreeze:
    """Reopen from the outer G0's digest, never a fork-inherited capability."""
    if type(profile_version) is not int or profile_version != 2:
        raise _fail("worker runtime profile must be v2", "schema_version")
    raw = _read(envelope_path)
    if _raw_digest(raw) != validate_digest(expected_digest, "runtime_freeze_digest"):
        raise _fail("worker runtime bytes changed after outer authorization", "runtime_freeze_digest")
    document = _document(raw, ENVELOPE_KEYS)
    template, _ = read_approved_template(template_path(STUDY_RETAINED_KEY, root, version=2), document["design_digest"])
    document = validate_runtime_freeze_document(document, template=template)
    inputs = {
        "root": root, "envelope_path": envelope_path, "prepared_manifest": prepared_manifest,
        "template": template, "baseline_id": document["baseline_id"],
        "output_root": document["approved_output_root_identity"],
        "adapter_cpu": document["adapter_cpu"], "controller_cpu": document["controller_cpu"],
    }
    return _open_observed(inputs, expected_digest=expected_digest)


def reverify_current_runtime_freeze(capability: VerifiedCurrentRuntimeFreeze) -> VerifiedCurrentRuntimeFreeze:
    if type(capability) is not VerifiedCurrentRuntimeFreeze or capability._issuer is not _ISSUER:
        raise _fail("a factory-issued current runtime capability is required")
    if canonical_payload_bytes(dict(capability.document)) != capability._identity:
        raise _fail("runtime capability content was modified")
    refreshed = open_worker_runtime_freeze(root=capability._root, envelope_path=capability._envelope_path,
        prepared_manifest=capability._prepared_manifest, expected_digest=capability.digest, profile_version=2)
    if canonical_payload_bytes(dict(refreshed.document)) != capability._identity:
        raise _fail("runtime capability differs from the fresh full observation")
    return refreshed


def require_runtime_for_freeze(capability: VerifiedCurrentRuntimeFreeze, freeze: Any, *, root: Path) -> VerifiedCurrentRuntimeFreeze:
    """Bind the current capability to the caller's already refreshed G0 freeze."""
    refreshed = reverify_current_runtime_freeze(capability)
    if (getattr(freeze, "profile_version", None) != 2 or refreshed._root != root
            or freeze.runtime_freeze_digest != refreshed.digest or freeze.baseline_id != refreshed.document["baseline_id"]):
        raise _fail("runtime capability differs from this authorization", "runtime_freeze_digest")
    for name in ("source_commit", "source_tree_sha", "source_file_set_digest", "design_digest",
                 "backend_protocol_digest", "binary_manifest_digest", "corpus_manifest_digest",
                 "host_preflight_digest", "control_schedule_digest", "treatment_schedule_digest",
                 "approved_output_root_identity"):
        if getattr(freeze, name) != refreshed.document[name]:
            raise _fail("runtime identity differs from this authorization", name)
    return refreshed


def reject_current_receipt_for_v1(root: Path) -> None:
    """Fresh compatibility data must never satisfy historical v1 preconditions."""
    receipt_path = Path(root) / BACKEND_RECEIPT
    if not os.path.lexists(receipt_path):
        return
    value = loads_json(decode_text(_read(receipt_path)))
    if type(value) is dict and value.get("receipt_origin") == CURRENT_BASELINE_PROFILE:
        raise _fail("a current execution receipt cannot be used as historical T6", "t6_freeze_receipt")

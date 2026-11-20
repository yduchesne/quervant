"""Closed offline readers for synthetic qualifications and preserved baselines.

The unchanged synthetic route never creates a sealed run, derives statistics,
recomputes independent verification or publishes anything. It resolves
one operator-provisioned local workspace, loads an independently supplied trust
anchor, asks the existing BM-06 loader to fully re-verify the committed bundle,
re-reads the committed bytes, and renders exactly one bounded stage document.

Exactly two synthetic families are registered through a frozen literal map: the
BM-07 retained-key reference and the BM-08 cross-engine reference. There is no glob
discovery, plugin registry or user-controlled resolver, and a foreign family is
typed ``BM_NOT_IMPLEMENTED``.

The explicit current-baseline-v2 route opens Git-preserved original bytes, makes
owned data/corpus working copies and independently rederives both families. It
never acquires samples or opens original producer locations. Successful verify
writes a separate replay receipt; it does not rewrite the original baseline.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
)
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BM_USAGE,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id, validate_uuid4
from ..evidence.paths import (
    list_directory_beneath,
    open_regular_beneath,
    require_publication_base,
    require_safe_root,
)
from ..evidence.provenance import repository_root
from ..qualification.contracts import (
    bound_payload,
    subject_document,
    validate_subject,
)
from ..qualification.coordinator import QualificationResult, load_qualified_synthetic_run
from ..qualification.profiles import default_profile_path
from ..qualification.publication import CommittedBundle, load_bundle
from .cross_engine import (
    EXPECTED_PROTOCOL_CONTENT_DIGEST,
    REFERENCE_EXPERIMENT_ID as CROSS_ENGINE_EXPERIMENT_ID,
    reference_catalog_root as cross_engine_catalog_root,
    validate_cross_engine_reference,
)
from .retained_key import (
    REFERENCE_EXPERIMENT_ID as RETAINED_KEY_EXPERIMENT_ID,
    load_reference_bundle,
    reference_catalog_root,
)

#: Frozen literal allowlist of the two registered synthetic families. There is
#: no glob discovery, no plugin registry and no user-controlled resolver.
FAMILY_LOADERS = {
    RETAINED_KEY_EXPERIMENT_ID: load_reference_bundle,
    CROSS_ENGINE_EXPERIMENT_ID: validate_cross_engine_reference,
}

OFFLINE_WORKSPACE_ENV = "QUERVANT_BENCH_OFFLINE_WORKSPACE"
DEFAULT_WORKSPACE_DIRECTORY = "benchmark-results"
ANCHOR_NAME = "qualification-anchors.v1.json"
ANCHOR_KIND = "simulated-qualification-trust-anchors"
ANCHOR_SCHEMA_VERSION = 1
MAX_ANCHOR_BYTES = 65_536
MAX_EXPERIMENT_CANDIDATES = 128

ANALYSIS_VIEW_KIND = "simulated-offline-analysis-view"
REPORT_VIEW_KIND = "simulated-offline-report"
VIEW_SCHEMA_VERSION = 1

_ANCHOR_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "profile_digest",
        "framework_qa_digest",
        "source_qa_digest",
        "source_set_digest",
    }
)
_ANALYSIS_VIEW_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "manifest_digest",
        "analysis",
        "policy",
    }
)
_REPORT_VIEW_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "evidence_origin",
        "qualification_scope",
        "subject",
        "manifest_digest",
        "attestation_receipt_id",
        "policy",
    }
)
_DIGEST_FIELDS = (
    "profile_digest",
    "framework_qa_digest",
    "source_qa_digest",
    "source_set_digest",
)


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _schema(message: str, field: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field)


def _workspace_root() -> Path:
    """Resolve the explicit/default local workspace without creating it."""

    raw = os.environ.get(OFFLINE_WORKSPACE_ENV)
    if raw is None:
        candidate = repository_root() / DEFAULT_WORKSPACE_DIRECTORY
        if not candidate.exists():
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                f"the default offline workspace {DEFAULT_WORKSPACE_DIRECTORY!r} "
                "does not exist",
                reference=DEFAULT_WORKSPACE_DIRECTORY,
            )
    else:
        if not raw:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"{OFFLINE_WORKSPACE_ENV} must be a non-empty absolute directory",
                field_path=OFFLINE_WORKSPACE_ENV,
            )
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"{OFFLINE_WORKSPACE_ENV} must be an absolute directory path",
                field_path=OFFLINE_WORKSPACE_ENV,
            )
        if not candidate.exists():
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "the offline workspace does not exist",
                field_path=OFFLINE_WORKSPACE_ENV,
            )
    try:
        workspace = require_safe_root(candidate)
    except BenchError as error:
        if error.code == BM_FILE_MISSING:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE, "the offline workspace does not exist"
            ) from error
        raise
    resolved = workspace.resolve()
    repository = repository_root().resolve()
    inside_repository = resolved == repository or repository in resolved.parents
    if inside_repository:
        permitted = repository / DEFAULT_WORKSPACE_DIRECTORY
        if resolved != permitted and permitted not in resolved.parents:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "an in-repository offline workspace is restricted to benchmark-results",
                field_path=OFFLINE_WORKSPACE_ENV,
            )
    elif resolved in repository.parents:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the offline workspace must not contain the repository",
            field_path=OFFLINE_WORKSPACE_ENV,
        )
    return workspace


def _list_beneath(root: Path, relative: str) -> tuple[str, ...]:
    try:
        return list_directory_beneath(root, relative)
    except BenchError as error:
        if error.code == BM_FILE_MISSING:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "a required offline workspace directory is missing",
                reference=relative,
            ) from error
        raise


def _require_directory(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            f"{label} does not exist",
            reference=label,
        ) from exc
    except OSError as exc:
        raise BenchError(
            BM_UNSAFE_INPUT, f"{label} cannot be inspected", reference=label
        ) from exc
    if stat.S_ISLNK(info.st_mode):
        raise BenchError(
            BM_UNSAFE_INPUT, f"{label} must not be a symbolic link", reference=label
        )
    if not stat.S_ISDIR(info.st_mode):
        raise BenchError(
            BM_UNSAFE_INPUT, f"{label} must be a directory", reference=label
        )


def _read_bounded_regular(root: Path, name: str, maximum: int) -> bytes:
    try:
        handle = open_regular_beneath(root, name)
    except BenchError as error:
        if error.code == BM_FILE_MISSING:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "the independent qualification anchor is missing",
                reference=name,
            ) from error
        raise
    with handle:
        payload = handle.read(maximum + 1)
    if len(payload) > maximum:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the independent qualification anchor exceeds its size budget",
            reference=name,
        )
    return payload


def read_anchor_document(workspace: Path) -> dict[str, Any]:
    """Read the operator-provisioned trust root; never derive or repair it."""

    if not isinstance(workspace, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, "workspace must be a Path", field_path="workspace"
        )
    payload = _read_bounded_regular(workspace, ANCHOR_NAME, MAX_ANCHOR_BYTES)
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the qualification anchor must be stored in canonical byte form",
            reference=ANCHOR_NAME,
        )
    if not isinstance(document, Mapping) or set(document) != _ANCHOR_KEYS:
        raise _schema(
            "the qualification anchor must use the exact closed field set",
            "qualification-anchors",
        )
    if document["kind"] != ANCHOR_KIND:
        raise _schema("the qualification anchor kind is invalid", "kind")
    if document["schema_version"] != ANCHOR_SCHEMA_VERSION:
        raise _schema(
            "the qualification anchor schema_version is unsupported",
            "schema_version",
        )
    for field in _DIGEST_FIELDS:
        validate_digest(document[field], field)
    return dict(document)


def resolve_qualified_run(workspace: Path, run_id: str) -> tuple[str, Path]:
    """Resolve one committed run UUID across bounded immediate experiment dirs."""

    if not isinstance(workspace, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, "workspace must be a Path", field_path="workspace"
        )
    canonical_run = validate_uuid4(run_id)
    names = _list_beneath(workspace, "qualified")
    if len(names) > MAX_EXPERIMENT_CANDIDATES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"the qualified workspace exceeds {MAX_EXPERIMENT_CANDIDATES} experiment directories",
            reference="qualified",
        )
    experiment_names: list[str] = []
    for name in names:
        try:
            validate_semantic_id(name, "qualified experiment directory")
        except BenchError as error:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "a qualified experiment directory name is not a semantic identifier",
                reference="qualified",
            ) from error
        _require_directory(workspace / "qualified" / name, f"qualified/{name}")
        experiment_names.append(name)

    matches: list[tuple[str, Path]] = []
    for name in experiment_names:
        children = _list_beneath(workspace, f"qualified/{name}")
        if canonical_run not in children:
            continue
        candidate = workspace / "qualified" / name / canonical_run
        _require_directory(candidate, f"qualified/{name}/{canonical_run}")
        matches.append((name, candidate))
    if not matches:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "no committed qualification matches the requested run",
            field_path="run_id",
        )
    if len(matches) > 1:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the requested run UUID is ambiguous across experiment directories",
            field_path="run_id",
        )
    return matches[0]


def _offline_paths(workspace: Path, experiment_id: str, run_id: str) -> dict[str, Path]:
    return {
        "run_dir": workspace / "runs" / experiment_id / run_id,
        "scenario_root": workspace / "scenarios" / experiment_id / run_id,
        "qa_evidence_root": workspace / "qa",
        "output_base": workspace / "qualified",
    }


def _same_verified_identity(
    committed: CommittedBundle, result: QualificationResult
) -> bool:
    return (
        committed.manifest_digest == result.manifest_digest
        and committed.documents["attestation.json"]["receipt_id"]
        == result.attestation_receipt_id
        and committed.output_directory == result.output_directory
    )


def _trusted_subject(bundle: Any, run_id: str) -> dict[str, str]:
    return validate_subject(subject_document(bundle, run_id), "subject")


def open_verified_artifacts(
    workspace: Path, run_id: str
) -> tuple[Any, dict[str, Any], QualificationResult, CommittedBundle]:
    """Fully re-verify one committed bundle and re-read its immutable bytes."""

    experiment_id, _directory = resolve_qualified_run(workspace, run_id)
    if experiment_id not in FAMILY_LOADERS:
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "the selected experiment is outside the registered offline families",
            field_path="experiment_id",
        )
    anchors = read_anchor_document(workspace)
    companions = None
    if experiment_id == RETAINED_KEY_EXPERIMENT_ID:
        catalog_root = reference_catalog_root()
        bundle = load_reference_bundle(catalog_root)
    elif experiment_id == CROSS_ENGINE_EXPERIMENT_ID:
        catalog_root = cross_engine_catalog_root()
        bundle, companions = validate_cross_engine_reference(
            catalog_root, repository_root()
        )
    else:  # pragma: no cover - the frozen allowlist is exhaustive
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "the selected experiment is outside the registered offline families",
            field_path="experiment_id",
        )
    experiment_root = catalog_root / experiment_id
    paths = _offline_paths(workspace, experiment_id, run_id)
    require_publication_base(paths["output_base"], repository_root())
    result = load_qualified_synthetic_run(
        bundle=bundle,
        run_dir=paths["run_dir"],
        scenario_root=paths["scenario_root"],
        profiles_root=experiment_root,
        resources_root=experiment_root,
        qualification_profile_path=default_profile_path(),
        qa_evidence_root=paths["qa_evidence_root"],
        expected_profile_digest=anchors["profile_digest"],
        expected_framework_qa_digest=anchors["framework_qa_digest"],
        expected_source_qa_digest=anchors["source_qa_digest"],
        source_root=repository_root(),
        expected_source_set_digest=anchors["source_set_digest"],
        output_base=paths["output_base"],
    )
    committed = load_bundle(
        output_base=paths["output_base"],
        experiment_id=experiment_id,
        run_id=run_id,
    )
    if not _same_verified_identity(committed, result):
        raise _fail(
            "the committed bundle changed after BM-06 re-verification", "qualified"
        )
    if experiment_id == CROSS_ENGINE_EXPERIMENT_ID:
        _revalidated_bundle, revalidated = validate_cross_engine_reference(
            catalog_root, repository_root()
        )
        if companions is None or revalidated != companions:
            raise _fail(
                "the cross-engine ledger or source bindings changed after the read",
                "semantic-comparability",
            )
        if _revalidated_bundle.protocol_digest != bundle.protocol_digest:
            raise _fail(
                "the cross-engine protocol changed after the read", "protocol"
            )
        if (
            content_digest(dict(bundle.protocol_document))
            != EXPECTED_PROTOCOL_CONTENT_DIGEST
        ):
            raise _fail(
                "the cross-engine protocol is not the approved reviewed v1",
                "protocol",
            )
    return bundle, anchors, result, committed


def _validate_common_view(view: Mapping[str, Any]) -> None:
    if view.get("evidence_origin") != "synthetic":
        raise _fail("an offline view must remain synthetic", "evidence_origin")
    if view.get("qualification_scope") != "simulated":
        raise _fail("an offline view must remain simulated", "qualification_scope")
    validate_subject(view.get("subject"), "subject")
    validate_digest(view.get("manifest_digest"), "manifest_digest")


def _build_analysis_view(
    bundle: Any, committed: CommittedBundle, run_id: str
) -> dict[str, Any]:
    view = {
        "kind": ANALYSIS_VIEW_KIND,
        "schema_version": VIEW_SCHEMA_VERSION,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "subject": _trusted_subject(bundle, run_id),
        "manifest_digest": committed.manifest_digest,
        "analysis": dict(committed.documents["analysis.json"]),
        "policy": dict(committed.documents["policy.json"]),
    }
    if set(view) != _ANALYSIS_VIEW_KEYS:
        raise _schema("the offline analysis view is not closed", "view")
    _validate_common_view(view)
    bound_payload(view, "offline-analysis-view")
    return view


def _build_report_view(
    bundle: Any, committed: CommittedBundle, run_id: str
) -> dict[str, Any]:
    receipt_id = committed.documents["attestation.json"]["receipt_id"]
    validate_digest(receipt_id, "attestation_receipt_id")
    view = {
        "kind": REPORT_VIEW_KIND,
        "schema_version": VIEW_SCHEMA_VERSION,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "subject": _trusted_subject(bundle, run_id),
        "manifest_digest": committed.manifest_digest,
        "attestation_receipt_id": receipt_id,
        "policy": dict(committed.documents["policy.json"]),
    }
    if set(view) != _REPORT_VIEW_KEYS:
        raise _schema("the offline report view is not closed", "view")
    _validate_common_view(view)
    bound_payload(view, "offline-report-view")
    return view


_STAGE_DOCUMENTS = {
    "validate": "admission-index.json",
    "verify": "verification-assessment.json",
    "accept": "acceptance-summary.json",
}


def render_offline_stage_view(verb: str, run_id: str) -> dict[str, Any]:
    """Render one closed, source-bound stage view after full re-verification."""

    if verb not in ("validate", "analyze", "verify", "accept", "report"):
        raise BenchError(BM_USAGE, f"unsupported offline verb: {verb!r}")
    workspace = _workspace_root()
    baseline = _resolve_baseline_namespace(workspace, run_id)
    if baseline is not None:
        return _baseline_stage(verb, baseline)
    bundle, _anchors, _result, committed = open_verified_artifacts(workspace, run_id)
    if verb == "analyze":
        return _build_analysis_view(bundle, committed, run_id)
    if verb == "report":
        return _build_report_view(bundle, committed, run_id)
    document = committed.documents[_STAGE_DOCUMENTS[verb]]
    return dict(document)



def _resolve_baseline_namespace(workspace: Path, run_id: str) -> Path | None:
    """Check both literal namespaces before selecting a baseline or synthetic run."""
    run = validate_uuid4(run_id, "run_id")
    baseline = workspace / "baselines" / run
    baseline_present = os.path.lexists(baseline)
    synthetic_present = False
    if os.path.lexists(workspace / "qualified"):
        try:
            resolve_qualified_run(workspace, run)
            synthetic_present = True
        except BenchError as error:
            if error.code != BM_EVIDENCE_UNAVAILABLE or error.field_path != "run_id":
                raise
    if baseline_present:
        require_safe_root(baseline)
        if synthetic_present:
            raise BenchError(BM_IDENTITY_INVALID,
                "the requested UUID is ambiguous between synthetic qualification and baseline evidence", field_path="run_id")
        return baseline
    return None


def _baseline_stage(verb: str, baseline_root: Path) -> dict[str, Any]:
    from ..official import transport
    if verb not in ("verify", "report"):
        raise BenchError(BM_USAGE, "current baseline offline evidence supports only verify and report", field_path="verb")
    if verb == "verify":
        return transport.replay_baseline_evidence(baseline_root=baseline_root)
    capability = transport.open_verified_baseline_evidence(baseline_root=baseline_root)
    manifest = capability.document
    members = {row["path"]: row for row in manifest["members"]}
    studies = {}
    observations = []
    for study in transport.STUDIES:
        documents = {}
        for label, name in (("history", "history-report.json"), ("relative_effects", "relative-effects.json")):
            relative = f"reports/{study}/{name}"
            observed, _ = transport._observe(baseline_root, relative, transport._member_limit(relative, "report"))
            declared = members.get(relative)
            if declared is None or (observed.digest, observed.byte_length) != (declared["sha256"], declared["size_bytes"]):
                raise _fail("a report changed after independent baseline replay", relative)
            observations.append(observed)
            documents[label] = transport._json(baseline_root, relative, limit=transport._member_limit(relative, "report"))
        studies[study] = documents
    for observed in observations:
        transport._recheck(observed)
    if capability.document != manifest:
        raise _fail("the baseline manifest changed while its report was rendered", "manifest")
    return {"kind": "official-baseline-offline-report", "schema_version": 1,
        "baseline_id": capability.baseline_id, "status": capability.status,
        "baseline_manifest_digest": capability.manifest_digest, "source_commit": capability.source_commit,
        "evidence_commit": capability.evidence_commit, "studies": studies,
        "historical_availability_provenance": "original-recorded-availability-and-exclusion-observations"}


def dispatch_stage(verb: str, run_id: str) -> dict[str, Any]:
    """Entry point used by the CLI for an explicitly offline reserved verb."""

    return render_offline_stage_view(verb, run_id)


__all__ = [
    "ANALYSIS_VIEW_KIND",
    "ANCHOR_KIND",
    "ANCHOR_NAME",
    "FAMILY_LOADERS",
    "MAX_EXPERIMENT_CANDIDATES",
    "OFFLINE_WORKSPACE_ENV",
    "REPORT_VIEW_KIND",
    "dispatch_stage",
    "open_verified_artifacts",
    "read_anchor_document",
    "render_offline_stage_view",
    "resolve_qualified_run",
]

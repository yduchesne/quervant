"""Gate A: sealed BM-03 structural admission and canonical file index.

Admission is read-only. It re-runs the BM-03 structural replayer, reopens the
canonical ``seal.json`` without following links, binds the raw seal digest, the
declared file inventory, the freeze/scenario/protocol identities, the frozen
qualification profile and the source-set identity, and rehashes every declared
sealed file. A self-reported seal digest is never sufficient.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
    sha256_prefix,
)
from ..config.contracts import ExperimentBundle
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest
from ..evidence.hashing import sha256_regular_file
from ..evidence.paths import open_regular_beneath, require_safe_root
from ..execution.replay import VERIFIED_STATUS, replay_sealed_synthetic
from ..execution.recorder import validate_seal_document
from ..execution.store import SEAL_NAME
from .contracts import (
    ADMISSION_INDEX_KIND,
    SCHEMA_VERSION,
    bound_payload,
    require_bundle_scope,
    require_synthetic_scope,
    subject_document,
    validate_admission_index,
)
from .receipts import build_stage_receipt, validator_identity, verify_stage_receipt

MAX_SEAL_BYTES = 1_048_576
MAX_SEALED_MEMBER_BYTES = 1_048_576


def _fail(message: str, field: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field)


def _require_paths(run_dir: Path, scenario_root: Path) -> None:
    for value, field in ((run_dir, "run_dir"), (scenario_root, "scenario_root")):
        if not isinstance(value, Path):
            raise BenchError(
                BM_UNSAFE_INPUT, f"{field} must be a Path", field_path=field
            )
    require_safe_root(run_dir)
    require_safe_root(scenario_root)
    resolved_run = run_dir.resolve()
    resolved_scenario = scenario_root.resolve()
    if resolved_run == resolved_scenario or resolved_scenario in resolved_run.parents or resolved_run in resolved_scenario.parents:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the sealed run and scenario roots must be disjoint",
            field_path="scenario_root",
        )


def read_seal(run_dir: Path) -> tuple[dict[str, Any], str]:
    """Read ``seal.json`` through the bounded no-follow reader."""

    handle = open_regular_beneath(run_dir, SEAL_NAME)
    with handle:
        payload = handle.read(MAX_SEAL_BYTES + 1)
    if len(payload) > MAX_SEAL_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT, "seal.json exceeds the record budget", reference=SEAL_NAME
        )
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise _fail("seal.json is not stored in canonical byte form", "seal")
    return dict(document), sha256_prefix(payload)


def rehash_sealed_files(
    run_dir: Path, files: tuple[tuple[str, str, int], ...]
) -> None:
    """Rehash every declared sealed file and compare digest and length."""

    for path, digest, length in files:
        actual_digest, actual_length = sha256_regular_file(
            run_dir, path, max_bytes=MAX_SEALED_MEMBER_BYTES
        )
        if actual_digest != digest or actual_length != length:
            raise _fail(
                "the stored bytes of a sealed record do not match the seal", path
            )


def build_admission_index(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
    profile_digest: str,
    source_set_digest: str,
) -> dict[str, Any]:
    """Replay one sealed synthetic run and build its canonical admission index."""

    require_bundle_scope(bundle)
    _require_paths(run_dir, scenario_root)
    validate_digest(profile_digest, "profile_digest")
    validate_digest(source_set_digest, "source_set_digest")

    replay = replay_sealed_synthetic(
        run_dir, bundle=bundle, scenario_root=scenario_root
    )
    if replay.status != VERIFIED_STATUS:
        raise BenchError(
            BM_EVIDENCE_UNAVAILABLE,
            "the sealed run did not pass structural replay",
            field_path="evidence",
        )
    seal_document, seal_raw_digest = read_seal(run_dir)
    seal = validate_seal_document(seal_document)
    if seal.run_id != run_dir.name or seal.run_id != replay.run_id:
        raise _fail("the seal run identity does not match its directory", "seal.run_id")
    if seal.experiment_id != bundle.experiment.experiment_id:
        raise _fail("the seal experiment identity does not match the bundle", "seal.experiment_id")
    if content_digest(seal_document) != replay.seal_digest:
        raise _fail("the seal document identity does not match replay", "seal")
    rehash_sealed_files(run_dir, seal.files)

    subject = subject_document(bundle, replay.run_id)
    index = {
        "kind": ADMISSION_INDEX_KIND,
        "schema_version": SCHEMA_VERSION,
        "subject": subject,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "seal_raw_digest": seal_raw_digest,
        "freeze_digest": seal.freeze_digest,
        "scenario_digest": seal.scenario_digest,
        "protocol_digest": subject["protocol_digest"],
        "profile_digest": profile_digest,
        "source_set_digest": source_set_digest,
        "counts": {
            "controls_completed": replay.controls_completed,
            "treatments_completed": replay.treatments_completed,
            "slots_completed": replay.slots_completed,
            "lane_envelopes": replay.lane_envelopes,
            "synthetic_samples": replay.synthetic_samples,
        },
        "files": [
            {"path": path, "byte_length": length, "raw_digest": digest}
            for path, digest, length in seal.files
        ],
    }
    validate_admission_index(index)
    bound_payload(index, "admission-index")
    return index


def admission_input_bindings(
    index: Mapping[str, Any], *, profile_digest: str, source_set_digest: str
) -> dict[str, str]:
    return {
        "seal": index["seal_raw_digest"],
        "protocol": index["protocol_digest"],
        "workload": index["subject"]["workload_digest"],
        "qualification-profile": profile_digest,
        "scenario": index["scenario_digest"],
        "source-set": source_set_digest,
    }


def build_admission(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
    profile_digest: str,
    source_set_digest: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and verify the Gate A index and receipt documents."""

    index = build_admission_index(
        bundle=bundle,
        run_dir=run_dir,
        scenario_root=scenario_root,
        profile_digest=profile_digest,
        source_set_digest=source_set_digest,
    )
    receipt = build_stage_receipt(
        gate="admission",
        subject=index["subject"],
        validator=validator_identity("admission", source_set_digest),
        inputs=admission_input_bindings(
            index, profile_digest=profile_digest, source_set_digest=source_set_digest
        ),
        dependencies=(),
        outputs={"admission-index": content_digest(index)},
    )
    return index, receipt


def verify_admission(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
    index_document: Mapping[str, Any],
    receipt_document: Mapping[str, Any],
    profile_digest: str,
    source_set_digest: str,
) -> dict[str, Any]:
    """Re-validate one committed (or in-memory) admission against fresh evidence.

    Loader reuse and re-publication both perform a new structural replay and a new
    byte rehash; there is no cached-admission shortcut.
    """

    index = validate_admission_index(index_document)
    require_synthetic_scope(index)
    expected = build_admission_index(
        bundle=bundle,
        run_dir=run_dir,
        scenario_root=scenario_root,
        profile_digest=profile_digest,
        source_set_digest=source_set_digest,
    )
    if index != expected:
        raise _fail(
            "the admission index does not match fresh sealed-run evidence",
            "admission-index",
        )
    verify_stage_receipt(
        receipt_document,
        gate="admission",
        source_set_digest=source_set_digest,
        expected_subject=index["subject"],
        inputs=admission_input_bindings(
            index, profile_digest=profile_digest, source_set_digest=source_set_digest
        ),
        outputs={"admission-index": content_digest(index)},
        dependencies=(),
    )
    return index


def verify_sealed_bytes(
    run_dir: Path, index_document: Mapping[str, Any]
) -> dict[str, Any]:
    """Rehash the declared sealed inventory and re-read the seal immediately."""

    index = validate_admission_index(index_document)
    seal_document, seal_raw_digest = read_seal(run_dir)
    seal = validate_seal_document(seal_document)
    if seal_raw_digest != index["seal_raw_digest"]:
        raise _fail("seal.json changed after admission", "seal")
    if seal.freeze_digest != index["freeze_digest"]:
        raise _fail("the seal freeze digest changed after admission", "freeze_digest")
    if seal.scenario_digest != index["scenario_digest"]:
        raise _fail("the seal scenario digest changed after admission", "scenario_digest")
    expected_files = [
        {"path": path, "byte_length": length, "raw_digest": digest}
        for path, digest, length in seal.files
    ]
    if index["files"] != expected_files:
        raise _fail("the admission file inventory changed", "files")
    rehash_sealed_files(run_dir, seal.files)
    return index


__all__ = [
    "admission_input_bindings",
    "build_admission",
    "build_admission_index",
    "read_seal",
    "rehash_sealed_files",
    "verify_admission",
    "verify_sealed_bytes",
]

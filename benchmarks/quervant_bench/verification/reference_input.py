"""Independent, read-only traversal of one sealed BM-03 synthetic run.

This module re-enumerates the declared treatment campaigns, compiled schedule
slots and workload lanes from the immutable BM-01 bundle instead of calling the
BM-04 reconstruction helper. It reuses only the frozen BM-03 path derivation,
envelope/seal validators and BM-02 no-follow reader.

It never writes a file, repairs evidence, ingests A/A control samples into the
treatment set or trusts an unsealed path. The returned evidence object records
the exact raw byte ledger so a later integrity pass can prove nothing changed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.codec import canonical_document_bytes, decode_text, loads_json
from ..config.contracts import ExperimentBundle, derive_origin_scope
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..evidence.paths import open_regular_beneath, require_safe_root
from ..execution.contracts import (
    MAX_CANONICAL_RECORD_BYTES,
    SIMULATED_SCOPE,
    SYNTHETIC_DIRECTION,
    SYNTHETIC_METRIC_UNIT,
    SYNTHETIC_ORIGIN,
)
from ..execution.recorder import (
    lane_relative_path,
    validate_lane_envelope_document,
    validate_seal_document,
)
from ..execution.scenario import load_synthetic_scenario
from ..protocol.controls import read_protocol_campaigns
from ..protocol.schedule import CompiledSchedule, ScheduleSlot, compile_schedule
from .contracts import DIRECTION_LOWER_IS_BETTER

TREATMENT_KIND = "treatment"
MAX_SEAL_BYTES = 1_048_576
TREATMENT_SLOT_PREFIX = f"slots/{TREATMENT_KIND}-"


def _identity(message: str, field_path: str = "evidence") -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _unsafe(message: str, field_path: str = "evidence") -> BenchError:
    return BenchError(BM_UNSAFE_INPUT, message, field_path=field_path)


@dataclass(frozen=True)
class ReferenceEvidence:
    """Immutable view of the sealed treatment evidence and its byte ledger."""

    run_id: str
    seal_digest: str
    seal_bytes: bytes
    freeze_digest: str
    scenario_digest: str
    campaign_indices: tuple[int, ...]
    lane_ids: tuple[str, ...]
    slots: tuple[ScheduleSlot, ...]
    schedule: CompiledSchedule
    arms: tuple[str, ...]
    samples: Mapping[tuple[int, str, int, str, int], tuple[int, ...]]
    consumed: tuple[tuple[str, str, int], ...]


# ---------------------------------------------------------------------------
# Pre-open checks
# ---------------------------------------------------------------------------


def _within(candidate: Path, container: Path) -> bool:
    return candidate == container or container in candidate.parents


def require_disjoint_roots(
    *,
    run_dir: Path,
    scenario_root: Path,
    profiles_root: Path,
    resources_root: Path,
) -> None:
    """Validate and safety-check every root without opening any evidence file."""

    roots = (
        (run_dir, "run_dir"),
        (scenario_root, "scenario_root"),
        (profiles_root, "profiles_root"),
        (resources_root, "resources_root"),
    )
    for path, label in roots:
        if not isinstance(path, Path):
            raise BenchError(
                BM_UNSAFE_INPUT, f"{label} must be a Path", field_path=label
            )
        require_safe_root(path)
    for other, label in roots[1:]:
        if _within(other, run_dir) or _within(run_dir, other):
            raise _unsafe(
                f"{label} must be disjoint from the sealed run directory", label
            )


def require_synthetic_evidence_scope(bundle: ExperimentBundle) -> None:
    """Reject any non-synthetic origin/scope declaration before evidence reads."""

    if not isinstance(bundle, ExperimentBundle):
        raise _identity("a validated ExperimentBundle is required", "bundle")
    derived = derive_origin_scope(bundle)
    if derived != (SYNTHETIC_ORIGIN, SIMULATED_SCOPE):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "BM-05 verifies synthetic/simulated evidence only",
            field_path="adapter.build_identity.kind",
        )
    document = bundle.adapter_document
    labels = (
        document.get("evidence_origin", SYNTHETIC_ORIGIN),
        document.get("qualification_scope", SIMULATED_SCOPE),
    )
    if labels != (SYNTHETIC_ORIGIN, SIMULATED_SCOPE):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "BM-05 accepts synthetic/simulated declarations only",
            field_path="adapter.qualification_scope",
        )


def require_lower_is_better_nanoseconds(bundle: ExperimentBundle) -> None:
    """Reject an envelope BM-04 cannot derive before any comparison."""

    envelope = bundle.adapter.measurement_envelope
    if envelope.unit != SYNTHETIC_METRIC_UNIT or (
        envelope.direction != DIRECTION_LOWER_IS_BETTER
    ):
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "BM-05 verifies the synthetic lower-is-better nanosecond envelope only",
            field_path="adapter.measurement_envelope",
        )


# ---------------------------------------------------------------------------
# Bounded reads and digests
# ---------------------------------------------------------------------------


def _read_bounded(root: Path, relative: str, limit: int) -> bytes:
    handle = open_regular_beneath(root, relative)
    with handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise _unsafe("a stored record exceeds the canonical record budget", relative)
    return payload


def raw_digest(payload: bytes) -> str:
    """Return ``sha256:<hex>`` over raw stored bytes."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _decode_canonical(payload: bytes, relative: str) -> Mapping[str, Any]:
    document = loads_json(decode_text(payload))
    if not isinstance(document, Mapping):
        raise BenchError(
            BM_SCHEMA_INVALID, f"{relative} must be a JSON object", reference=relative
        )
    if canonical_document_bytes(document) != payload:
        raise _unsafe(f"{relative} is not in canonical byte form", relative)
    return document


# ---------------------------------------------------------------------------
# Evidence collection
# ---------------------------------------------------------------------------


def _expected_treatment_paths(
    campaign_count: int, schedule: CompiledSchedule, lane_ids: tuple[str, ...]
) -> tuple[str, ...]:
    paths: list[str] = []
    for campaign_index in range(campaign_count):
        for slot in schedule.slots:
            for lane_id in lane_ids:
                paths.append(
                    lane_relative_path(
                        TREATMENT_KIND,
                        campaign_index,
                        slot.block,
                        slot.position,
                        lane_id,
                    )
                )
    return tuple(paths)


def _read_seal(run_dir: Path, bundle: ExperimentBundle, scenario_digest: str):
    payload = _read_bounded(run_dir, "seal.json", MAX_SEAL_BYTES)
    document = _decode_canonical(payload, "seal.json")
    seal = validate_seal_document(document)
    if seal.experiment_id != bundle.experiment.experiment_id:
        raise _identity(
            "the seal experiment identity does not match the declared bundle",
            "seal.experiment_id",
        )
    if seal.scenario_digest != scenario_digest:
        raise _identity(
            "the seal scenario digest does not match the declared scenario",
            "seal.scenario_digest",
        )
    return payload, document, seal


def collect_reference_evidence(
    *,
    bundle: ExperimentBundle,
    run_dir: Path,
    scenario_root: Path,
) -> ReferenceEvidence:
    """Re-enumerate and re-read every declared treatment lane exactly once."""

    scenario = load_synthetic_scenario(scenario_root, bundle=bundle)
    scenario_digest = scenario.scenario_digest
    seal_payload, _seal_document, seal = _read_seal(
        run_dir, bundle, scenario_digest
    )
    seal_digest = raw_digest(seal_payload)

    schedule = compile_schedule(bundle)
    if schedule.protocol_digest != bundle.protocol_digest:
        raise _identity(
            "the compiled schedule does not bind the declared protocol",
            "schedule.protocol_digest",
        )
    declarations = read_protocol_campaigns(bundle)
    campaign_count = declarations.required_treatments
    lane_ids = tuple(lane.lane_id for lane in bundle.workload.lanes)
    arms = tuple(arm.arm_id for arm in bundle.experiment.arms)

    expected_paths = _expected_treatment_paths(campaign_count, schedule, lane_ids)
    if len(set(expected_paths)) != len(expected_paths):
        raise _identity("the expected treatment path inventory is not unique", "schedule")

    manifest: dict[str, tuple[str, int]] = {}
    for path, digest, length in seal.files:
        if path in manifest:
            raise _identity("the seal declares a duplicate path", "seal.files")
        manifest[path] = (digest, length)
    declared_treatment = {
        path
        for path in manifest
        if path.startswith(TREATMENT_SLOT_PREFIX)
        and not path.endswith("/complete.json")
    }
    expected_set = set(expected_paths)
    if declared_treatment != expected_set:
        missing = sorted(expected_set - declared_treatment)
        extra = sorted(declared_treatment - expected_set)
        detail = missing[0] if missing else extra[0]
        raise _identity(
            "the seal treatment inventory does not match the compiled schedule: "
            f"{detail}",
            "seal.files",
        )

    warmups = bundle.protocol.warmups_per_lane_slot
    samples_per_slot = bundle.protocol.samples_per_lane_slot
    oracle_id = bundle.protocol.oracle_id
    oracle_version = bundle.protocol.oracle_version

    samples: dict[tuple[int, str, int, str, int], tuple[int, ...]] = {}
    consumed: list[tuple[str, str, int]] = []
    observed: set[str] = set()
    for campaign_index in range(campaign_count):
        for slot in schedule.slots:
            for lane_id in lane_ids:
                relative = lane_relative_path(
                    TREATMENT_KIND,
                    campaign_index,
                    slot.block,
                    slot.position,
                    lane_id,
                )
                payload = _read_bounded(
                    run_dir, relative, MAX_CANONICAL_RECORD_BYTES
                )
                digest = raw_digest(payload)
                expected = manifest.get(relative)
                if expected is None:
                    raise _identity(
                        f"the seal does not list the treatment record {relative!r}",
                        "seal.files",
                    )
                if expected != (digest, len(payload)):
                    raise _identity(
                        f"the stored bytes of {relative!r} do not match the seal",
                        "seal.files",
                    )
                envelope = validate_lane_envelope_document(
                    _decode_canonical(payload, relative)
                )
                if envelope.campaign_kind != TREATMENT_KIND:
                    raise _identity(
                        "a treatment lane record names the wrong campaign kind", relative
                    )
                if envelope.campaign_index != campaign_index:
                    raise _identity(
                        "a treatment lane record names the wrong campaign", relative
                    )
                if (envelope.block, envelope.position, envelope.ordinal) != (
                    slot.block,
                    slot.position,
                    slot.ordinal,
                ):
                    raise _identity(
                        "a treatment lane record names the wrong slot identity", relative
                    )
                if envelope.lane_id != lane_id:
                    raise _identity(
                        "a treatment lane record names the wrong lane", relative
                    )
                if (
                    envelope.arm_id != slot.arm_id
                    or envelope.declared_arm_id != slot.arm_id
                ):
                    raise _identity(
                        "a treatment lane record names an arm outside the schedule",
                        relative,
                    )
                if envelope.run_id != run_dir.name:
                    raise _identity(
                        "a treatment lane record names the wrong run", relative
                    )
                if envelope.warmup_calls != warmups:
                    raise _identity(
                        "a treatment lane record records the wrong warmup count",
                        relative,
                    )
                if len(envelope.samples) != samples_per_slot:
                    raise _identity(
                        "a treatment lane record records the wrong sample count",
                        relative,
                    )
                if (envelope.metric_unit, envelope.direction) != (
                    SYNTHETIC_METRIC_UNIT,
                    SYNTHETIC_DIRECTION,
                ):
                    raise _identity(
                        "a treatment lane record does not carry the frozen envelope",
                        relative,
                    )
                if (
                    envelope.oracle_id != oracle_id
                    or envelope.oracle_version != oracle_version
                ):
                    raise _identity(
                        "a treatment lane record names the wrong correctness oracle",
                        relative,
                    )
                key = (campaign_index, lane_id, slot.block, slot.arm_id, slot.position)
                if key in samples:
                    raise _identity(
                        "a treatment sample slot is recorded twice", relative
                    )
                samples[key] = envelope.samples
                consumed.append((relative, digest, len(payload)))
                observed.add(relative)

    if observed != expected_set:
        missing = sorted(expected_set - observed)
        raise _identity(
            f"the treatment traversal did not consume {missing[0]}", "seal.files"
        )
    return ReferenceEvidence(
        run_id=seal.run_id,
        seal_digest=seal_digest,
        seal_bytes=seal_payload,
        freeze_digest=seal.freeze_digest,
        scenario_digest=scenario_digest,
        campaign_indices=tuple(range(campaign_count)),
        lane_ids=lane_ids,
        slots=schedule.slots,
        schedule=schedule,
        arms=arms,
        samples=dict(samples),
        consumed=tuple(consumed),
    )


def verify_consumed_files(
    run_dir: Path, consumed: tuple[tuple[str, str, int], ...]
) -> None:
    """Re-read every consumed treatment byte and reject any change."""

    for relative, digest, length in consumed:
        payload = _read_bounded(run_dir, relative, MAX_CANONICAL_RECORD_BYTES)
        if raw_digest(payload) != digest or len(payload) != length:
            raise _identity(
                "a sealed treatment record changed during verification", "seal.files"
            )


def verify_seal_unchanged(run_dir: Path, expected: bytes) -> None:
    """Re-read ``seal.json`` and reject any byte change."""

    payload = _read_bounded(run_dir, "seal.json", MAX_SEAL_BYTES)
    if payload != expected:
        raise _identity("seal.json changed during verification", "seal.json")


def scenario_digest(scenario_root: Path, bundle: ExperimentBundle) -> str:
    """Return the canonical digest of the declared synthetic scenario."""

    return load_synthetic_scenario(scenario_root, bundle=bundle).scenario_digest


__all__ = [
    "MAX_SEAL_BYTES",
    "ReferenceEvidence",
    "collect_reference_evidence",
    "raw_digest",
    "require_disjoint_roots",
    "require_lower_is_better_nanoseconds",
    "require_synthetic_evidence_scope",
    "scenario_digest",
    "verify_consumed_files",
    "verify_seal_unchanged",
]

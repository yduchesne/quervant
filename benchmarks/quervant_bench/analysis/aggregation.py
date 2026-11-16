"""Read-only reconstruction of BM-03 treatment samples.

This module is the only place BM-04 touches sealed lane evidence. It never writes,
never repairs, never imports the A/A control campaign and never re-implements the
BM-03 structural replayer: it re-reads exactly the declared treatment lane
envelopes through the BM-02 no-follow reader, re-validates each with the BM-03
envelope validator and re-checks the original seal's digest and byte length for
every consumed file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.codec import canonical_document_bytes, content_digest, decode_text, loads_json
from ..config.contracts import ExperimentBundle
from ..config.errors import (
    BM_IDENTITY_INVALID,
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
from ..execution.recorder import lane_relative_path, validate_lane_envelope_document
from ..protocol.controls import read_protocol_campaigns
from ..protocol.schedule import compile_schedule
from .contracts import require_int

TREATMENT_KIND = "treatment"


def _fail(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class TreatmentLaneRecord:
    """One validated treatment lane envelope reduced to what analysis needs."""

    campaign_index: int
    block: int
    position: int
    ordinal: int
    arm_id: str
    lane_id: str
    samples: tuple[int, ...]


@dataclass(frozen=True)
class TreatmentSamples:
    """Every validated treatment lane record plus the consumed byte manifest."""

    campaign_indices: tuple[int, ...]
    lane_ids: tuple[str, ...]
    records: tuple[TreatmentLaneRecord, ...]
    consumed: tuple[tuple[str, str, int], ...]

    def block_slot_samples(
        self,
    ) -> dict[int, dict[str, dict[int, dict[str, list[tuple[int, ...]]]]]]:
        """Return ``campaign -> lane -> block -> arm -> [slot sample vectors]``."""

        board: dict[int, dict[str, dict[int, dict[str, list[tuple[int, ...]]]]]] = {}
        for campaign_index in self.campaign_indices:
            lanes: dict[str, dict[int, dict[str, list[tuple[int, ...]]]]] = {
                lane_id: {} for lane_id in self.lane_ids
            }
            for record in self.records:
                if record.campaign_index != campaign_index:
                    continue
                per_lane = lanes[record.lane_id]
                per_lane.setdefault(record.block, {}).setdefault(
                    record.arm_id, []
                ).append(record.samples)
            board[campaign_index] = lanes
        return board


def _read_bytes(run_dir: Path, relative: str) -> bytes:
    handle = open_regular_beneath(run_dir, relative)
    with handle:
        payload = handle.read(MAX_CANONICAL_RECORD_BYTES + 1)
    if len(payload) > MAX_CANONICAL_RECORD_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "a stored lane record exceeds the canonical record budget",
            reference=relative,
        )
    return payload


def _raw_digest(payload: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def read_treatment_samples(
    *,
    run_dir: Path,
    bundle: ExperimentBundle,
    seal_document: Mapping[str, Any],
) -> TreatmentSamples:
    """Reconstruct every scheduled treatment slot/lane exactly once, read-only."""

    if not isinstance(bundle, ExperimentBundle):
        raise _fail("a validated ExperimentBundle is required", "bundle")
    if not isinstance(run_dir, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, "run_dir must be a Path", field_path="run_dir"
        )
    require_safe_root(run_dir)
    if not isinstance(seal_document, Mapping):
        raise BenchError(
            BM_SCHEMA_INVALID, "a validated seal document is required", field_path="seal"
        )

    sealed_files = seal_document.get("files")
    if not isinstance(sealed_files, list):
        raise _fail("the seal must list its file inventory", "seal.files")
    manifest: dict[str, tuple[str, int]] = {}
    for entry in sealed_files:
        manifest[entry["path"]] = (entry["digest"], entry["byte_length"])

    schedule = compile_schedule(bundle)
    campaigns = read_protocol_campaigns(bundle)
    lane_ids = tuple(lane.lane_id for lane in bundle.workload.lanes)
    warmups = bundle.protocol.warmups_per_lane_slot
    samples_per_lane_slot = bundle.protocol.samples_per_lane_slot
    oracle_id = bundle.protocol.oracle_id
    oracle_version = bundle.protocol.oracle_version

    records: list[TreatmentLaneRecord] = []
    consumed: list[tuple[str, str, int]] = []
    consumed_paths: set[str] = set()
    for campaign_index in range(
        require_int(campaigns.required_treatments, "campaigns.required_treatments", minimum=1)
    ):
        for slot in schedule.slots:
            for lane_id in lane_ids:
                relative = lane_relative_path(
                    TREATMENT_KIND,
                    campaign_index,
                    slot.block,
                    slot.position,
                    lane_id,
                )
                payload = _read_bytes(run_dir, relative)
                digest = _raw_digest(payload)
                expected = manifest.get(relative)
                if expected is None:
                    raise _fail(
                        f"the seal does not list the treatment lane record {relative!r}",
                        "seal.files",
                    )
                if expected != (digest, len(payload)):
                    raise _fail(
                        f"the stored bytes of {relative!r} do not match the seal",
                        "seal.files",
                    )
                document = loads_json(decode_text(payload))
                if canonical_document_bytes(document) != payload:
                    raise BenchError(
                        BM_UNSAFE_INPUT,
                        f"stored record {relative!r} is not in canonical byte form",
                        reference=relative,
                    )
                envelope = validate_lane_envelope_document(document)
                if envelope.campaign_kind != TREATMENT_KIND:
                    raise _fail(
                        "a treatment lane record names the wrong campaign kind",
                        relative,
                    )
                if envelope.campaign_index != campaign_index:
                    raise _fail(
                        "a treatment lane record names the wrong campaign index", relative
                    )
                if (envelope.block, envelope.position, envelope.ordinal) != (
                    slot.block,
                    slot.position,
                    slot.ordinal,
                ):
                    raise _fail(
                        "a treatment lane record names the wrong slot identity", relative
                    )
                if envelope.lane_id != lane_id:
                    raise _fail(
                        "a treatment lane record names the wrong lane", relative
                    )
                if envelope.arm_id != slot.arm_id or envelope.declared_arm_id != slot.arm_id:
                    raise _fail(
                        "a treatment lane record names an arm outside the compiled schedule",
                        relative,
                    )
                if envelope.run_id != run_dir.name:
                    raise _fail("a treatment lane record names the wrong run", relative)
                if envelope.warmup_calls != warmups:
                    raise _fail(
                        "a treatment lane record records the wrong warmup count", relative
                    )
                if len(envelope.samples) != samples_per_lane_slot:
                    raise _fail(
                        "a treatment lane record records the wrong sample count", relative
                    )
                if (
                    envelope.metric_unit != SYNTHETIC_METRIC_UNIT
                    or envelope.direction != SYNTHETIC_DIRECTION
                ):
                    raise _fail(
                        "a treatment lane record does not carry the frozen envelope", relative
                    )
                if (
                    envelope.oracle_id != oracle_id
                    or envelope.oracle_version != oracle_version
                ):
                    raise _fail(
                        "a treatment lane record names the wrong correctness oracle", relative
                    )
                records.append(
                    TreatmentLaneRecord(
                        campaign_index=campaign_index,
                        block=slot.block,
                        position=slot.position,
                        ordinal=slot.ordinal,
                        arm_id=slot.arm_id,
                        lane_id=lane_id,
                        samples=envelope.samples,
                    )
                )
                consumed.append((relative, digest, len(payload)))
                consumed_paths.add(relative)

    expected_treatment_paths = {
        lane_relative_path(
            TREATMENT_KIND, campaign_index, slot.block, slot.position, lane_id
        )
        for campaign_index in range(campaigns.required_treatments)
        for slot in schedule.slots
        for lane_id in lane_ids
    }
    if expected_treatment_paths != consumed_paths:
        missing = sorted(expected_treatment_paths ^ consumed_paths)
        raise _fail(
            "the sealed treatment lane inventory does not match the compiled schedule: "
            f"{missing[0]}",
            "seal.files",
        )

    return TreatmentSamples(
        campaign_indices=tuple(range(campaigns.required_treatments)),
        lane_ids=lane_ids,
        records=tuple(records),
        consumed=tuple(consumed),
    )


def verify_consumed_files(
    run_dir: Path, consumed: tuple[tuple[str, str, int], ...]
) -> str:
    """Re-read every consumed record and return a combined deterministic digest."""

    import hashlib

    rebuilt: list[tuple[str, str, int]] = []
    for relative, digest, length in consumed:
        payload = _read_bytes(run_dir, relative)
        rebuilt.append((relative, _raw_digest(payload), len(payload)))
    if tuple(rebuilt) != tuple(consumed):
        raise _fail(
            "a sealed treatment record changed during derivation", "seal.files"
        )
    combined = hashlib.sha256()
    for relative, digest, length in rebuilt:
        combined.update(relative.encode("utf-8"))
        combined.update(digest.encode("utf-8"))
        combined.update(str(length).encode("utf-8"))
    return "sha256:" + combined.hexdigest()


def require_synthetic_scope(bundle: ExperimentBundle) -> None:
    """Reject any non-synthetic bundle **before** any evidence file is opened."""

    from ..config.contracts import derive_origin_scope

    if not isinstance(bundle, ExperimentBundle):
        raise _fail("a validated ExperimentBundle is required", "bundle")
    # ``derive_origin_scope`` raises BM_SCOPE_MISMATCH for any non-synthetic build
    # identity, which is the frozen rejection for a real/official declaration.
    derive_origin_scope(bundle)
    document = bundle.adapter_document
    origin = document.get("evidence_origin", SYNTHETIC_ORIGIN)
    scope = document.get("qualification_scope", SIMULATED_SCOPE)
    if (origin, scope) != (SYNTHETIC_ORIGIN, SIMULATED_SCOPE):
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "BM-04 accepts synthetic/simulated declarations only",
            field_path="adapter.qualification_scope",
        )


def scenario_digest_of(scenario_root: Path, bundle: ExperimentBundle) -> str:
    """Return the canonical content digest of the declared scenario fixture."""

    from ..execution.scenario import load_synthetic_scenario

    scenario = load_synthetic_scenario(scenario_root, bundle=bundle)
    return content_digest(dict(scenario.document))


__all__ = [
    "TREATMENT_KIND",
    "TreatmentLaneRecord",
    "TreatmentSamples",
    "read_treatment_samples",
    "require_synthetic_scope",
    "scenario_digest_of",
    "verify_consumed_files",
]

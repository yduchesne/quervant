"""Closed synthetic evidence records, their builders and their validators.

Every stored JSON document is canonical BM-01 serialized bytes with exactly one
trailing newline. Each record shape below is closed: no extra key is accepted on
write and no extra key is accepted on read. None of these records is a public
BM-01 schema, a receipt, a Gate A-E artefact or an official authorisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..config.codec import canonical_document_bytes, content_digest
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_digest, validate_semantic_id, validate_uuid4
from ..host.readiness import ReadinessDiagnostic, ReadinessLimits, ReadinessObservation
from .contracts import (
    CAMPAIGN_KINDS,
    EVENT_REASONS,
    INTERNAL_SCHEMA_VERSION,
    MAX_CANONICAL_RECORD_BYTES,
    MAX_LOGICAL_NS,
    MAX_SYNTHETIC_SAMPLE_NS,
    SIMULATED_SCOPE,
    SYNTHETIC_DIRECTION,
    SYNTHETIC_METRIC_UNIT,
    SYNTHETIC_ORIGIN,
    RunState,
    check_transition,
)

EVENT_KIND = "synthetic-state-event"
READINESS_KIND = "synthetic-readiness"
LANE_ENVELOPE_KIND = "synthetic-lane-envelope"
SLOT_COMPLETE_KIND = "synthetic-slot-complete"
CONTROL_CHECK_KIND = "synthetic-control-check"
SEAL_KIND = "synthetic-execution-seal"
SEAL_STATUS = "sealed-structural"

_EVENT_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "sequence",
        "from_state",
        "to_state",
        "reason",
        "logical_ns",
        "evidence_origin",
        "qualification_scope",
    }
)
_LIMIT_KEYS = (
    "min_interval_ms",
    "max_interval_ms",
    "max_busy_permille",
    "max_median_busy_permille",
    "max_steal_permille",
    "min_intervals",
)
_READINESS_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "campaign_kind",
        "campaign_index",
        "limits",
        "observations",
        "diagnostic",
        "evidence_origin",
        "qualification_scope",
    }
)
_OBSERVATION_KEYS = frozenset({"elapsed_ms", "busy_permille", "steal_permille"})
_DIAGNOSTIC_KEYS = frozenset({"status", "reasons"})
_LANE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "run_id",
        "campaign_kind",
        "campaign_index",
        "block",
        "position",
        "ordinal",
        "arm_id",
        "declared_arm_id",
        "lane_id",
        "oracle_id",
        "oracle_version",
        "fixture_digest",
        "warmup_calls",
        "metric_unit",
        "direction",
        "samples",
        "logical_start_ns",
        "logical_end_ns",
        "evidence_origin",
        "qualification_scope",
    }
)
_SLOT_COMPLETE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "run_id",
        "campaign_kind",
        "campaign_index",
        "block",
        "position",
        "ordinal",
        "arm_id",
        "declared_arm_id",
        "lanes",
        "evidence_origin",
        "qualification_scope",
    }
)
_SLOT_LANE_KEYS = frozenset({"lane_id", "digest"})
_CONTROL_CHECK_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "campaign_index",
        "control_contract_id",
        "source_arm_id",
        "status",
        "checked_pairs",
        "lane_ids",
        "evidence_origin",
        "qualification_scope",
    }
)
_SEAL_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "run_id",
        "experiment_id",
        "evidence_origin",
        "qualification_scope",
        "freeze_digest",
        "schedule_digest",
        "scenario_digest",
        "status",
        "controls_completed",
        "treatments_completed",
        "slots_completed",
        "lane_envelopes",
        "synthetic_samples",
        "last_logical_ns",
        "files",
    }
)
_SEAL_FILE_KEYS = frozenset({"path", "digest", "byte_length"})


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _require_mapping(document: object, expected: frozenset[str], field: str) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise _fail(f"{field} must be an object", field)
    if set(document) != expected:
        raise _fail(f"{field} must use the exact closed field set", field)
    return document


def _require_int(value: object, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{field} must be an integer", field)
    if value < minimum:
        raise _fail(f"{field} must be >= {minimum}", field)
    if maximum is not None and value > maximum:
        raise _fail(f"{field} must be <= {maximum}", field)
    return value


def _require_origin_scope(document: Mapping[str, Any], field: str) -> None:
    if (
        document.get("evidence_origin") != SYNTHETIC_ORIGIN
        or document.get("qualification_scope") != SIMULATED_SCOPE
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"{field} must keep the synthetic/simulated origin and scope",
            field_path=f"{field}.qualification_scope",
        )


def _require_campaign(document: Mapping[str, Any], field: str) -> tuple[str, int]:
    kind = document.get("campaign_kind")
    if kind not in CAMPAIGN_KINDS:
        raise _fail(f"{field}.campaign_kind must be control or treatment", field)
    index = _require_int(document.get("campaign_index"), f"{field}.campaign_index")
    return kind, index


def _require_slot_position(document: Mapping[str, Any], field: str) -> tuple[int, int, int]:
    block = _require_int(document.get("block"), f"{field}.block", minimum=1)
    position = _require_int(document.get("position"), f"{field}.position", minimum=1)
    ordinal = _require_int(document.get("ordinal"), f"{field}.ordinal", minimum=1)
    return block, position, ordinal


def record_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize one record to canonical bytes and enforce the size budget."""

    payload = canonical_document_bytes(dict(document))
    if len(payload) > MAX_CANONICAL_RECORD_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"record exceeds the {MAX_CANONICAL_RECORD_BYTES}-byte budget",
        )
    return payload


def record_digest(document: Mapping[str, Any]) -> str:
    """Return the canonical content digest of one record."""

    return content_digest(dict(document))


# ---------------------------------------------------------------------------
# State events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateEvent:
    """One validated persisted state transition."""

    sequence: int
    from_state: str
    to_state: str
    reason: str
    logical_ns: int


def build_event_document(
    *,
    sequence: int,
    from_state: RunState | str,
    to_state: RunState | str,
    reason: str,
    logical_ns: int,
) -> dict[str, Any]:
    """Build one closed ``synthetic-state-event`` record."""

    source = from_state.value if isinstance(from_state, RunState) else str(from_state)
    target = to_state.value if isinstance(to_state, RunState) else str(to_state)
    return {
        "kind": EVENT_KIND,
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "sequence": sequence,
        "from_state": source,
        "to_state": target,
        "reason": reason,
        "logical_ns": logical_ns,
        "evidence_origin": SYNTHETIC_ORIGIN,
        "qualification_scope": SIMULATED_SCOPE,
    }


def validate_event_document(document: object) -> StateEvent:
    """Validate one stored state event and its transition legality."""

    field = "event"
    doc = _require_mapping(document, _EVENT_KEYS, field)
    if doc["kind"] != EVENT_KIND or doc["schema_version"] != INTERNAL_SCHEMA_VERSION:
        raise _fail("event kind/version is invalid", field)
    sequence = _require_int(doc["sequence"], "event.sequence", minimum=1)
    from_state = doc["from_state"]
    to_state = doc["to_state"]
    reason = doc["reason"]
    if not isinstance(reason, str) or reason not in EVENT_REASONS:
        raise _fail("event reason is outside the closed set", "event.reason")
    logical_ns = _require_int(doc["logical_ns"], "event.logical_ns", maximum=MAX_LOGICAL_NS)
    _require_origin_scope(doc, field)
    if sequence == 1:
        if from_state != "none" or to_state != RunState.PLANNED.value:
            raise _fail("the first event must open the run as planned", "event")
        if reason != "new-run":
            raise _fail("the first event reason must be 'new-run'", "event.reason")
        return StateEvent(sequence, str(from_state), str(to_state), reason, logical_ns)
    try:
        source_state = RunState(str(from_state))
        target_state = RunState(str(to_state))
    except ValueError as exc:
        raise _fail("event state is not a recognised run state", "event") from exc
    check_transition(source_state, target_state, reason)
    return StateEvent(sequence, source_state.value, target_state.value, reason, logical_ns)


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadinessRecord:
    """One validated persisted simulated readiness diagnostic."""

    campaign_kind: str
    campaign_index: int
    limits: ReadinessLimits
    observations: tuple[ReadinessObservation, ...]
    diagnostic: ReadinessDiagnostic


def limits_document(limits: ReadinessLimits) -> dict[str, int]:
    """Serialize injected readiness limits canonically."""

    return {key: int(getattr(limits, key)) for key in _LIMIT_KEYS}


def observations_document(
    observations: tuple[ReadinessObservation, ...],
) -> list[dict[str, int]]:
    """Serialize simulated observations canonically."""

    return [
        {
            "elapsed_ms": item.elapsed_ms,
            "busy_permille": item.busy_permille,
            "steal_permille": item.steal_permille,
        }
        for item in observations
    ]


def build_readiness_document(
    *,
    campaign_kind: str,
    campaign_index: int,
    limits: ReadinessLimits,
    observations: tuple[ReadinessObservation, ...],
    diagnostic: ReadinessDiagnostic,
) -> dict[str, Any]:
    """Build one closed ``synthetic-readiness`` record."""

    return {
        "kind": READINESS_KIND,
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "campaign_kind": campaign_kind,
        "campaign_index": campaign_index,
        "limits": limits_document(limits),
        "observations": observations_document(observations),
        "diagnostic": {
            "status": diagnostic.status,
            "reasons": list(diagnostic.reasons),
        },
        "evidence_origin": SYNTHETIC_ORIGIN,
        "qualification_scope": SIMULATED_SCOPE,
    }


def validate_readiness_document(document: object) -> ReadinessRecord:
    """Validate a stored readiness record without re-deciding freshness."""

    field = "readiness"
    doc = _require_mapping(document, _READINESS_KEYS, field)
    if doc["kind"] != READINESS_KIND or doc["schema_version"] != INTERNAL_SCHEMA_VERSION:
        raise _fail("readiness kind/version is invalid", field)
    kind, index = _require_campaign(doc, field)
    _require_origin_scope(doc, field)
    raw_limits = doc["limits"]
    if not isinstance(raw_limits, Mapping) or set(raw_limits) != set(_LIMIT_KEYS):
        raise _fail("readiness.limits must use the exact closed field set", "readiness.limits")
    limits = ReadinessLimits(
        **{key: _require_int(raw_limits[key], f"readiness.limits.{key}") for key in _LIMIT_KEYS}
    )
    raw_observations = doc["observations"]
    if not isinstance(raw_observations, list):
        raise _fail("readiness.observations must be an array", "readiness.observations")
    observations: list[ReadinessObservation] = []
    for position, raw in enumerate(raw_observations):
        if not isinstance(raw, Mapping) or set(raw) != _OBSERVATION_KEYS:
            raise _fail(
                "readiness observations must use the exact closed field set",
                f"readiness.observations[{position}]",
            )
        observations.append(
            ReadinessObservation(
                elapsed_ms=_require_int(raw["elapsed_ms"], "readiness.observations[].elapsed_ms"),
                busy_permille=_require_int(raw["busy_permille"], "readiness.observations[].busy_permille"),
                steal_permille=_require_int(raw["steal_permille"], "readiness.observations[].steal_permille"),
            )
        )
    raw_diagnostic = doc["diagnostic"]
    if not isinstance(raw_diagnostic, Mapping) or set(raw_diagnostic) != _DIAGNOSTIC_KEYS:
        raise _fail("readiness.diagnostic must use the exact closed field set", "readiness.diagnostic")
    status = raw_diagnostic["status"]
    if status not in ("clear", "blocked"):
        raise _fail("readiness diagnostic status is not recognised", "readiness.diagnostic.status")
    raw_reasons = raw_diagnostic["reasons"]
    if not isinstance(raw_reasons, list) or not all(isinstance(item, str) for item in raw_reasons):
        raise _fail("readiness diagnostic reasons must be strings", "readiness.diagnostic.reasons")
    if list(raw_reasons) != sorted(set(raw_reasons)):
        raise _fail(
            "readiness diagnostic reasons must be sorted and unique",
            "readiness.diagnostic.reasons",
        )
    return ReadinessRecord(
        campaign_kind=kind,
        campaign_index=index,
        limits=limits,
        observations=tuple(observations),
        diagnostic=ReadinessDiagnostic(status=status, reasons=tuple(raw_reasons)),
    )


# ---------------------------------------------------------------------------
# Lane envelope and slot completion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LaneEnvelope:
    """One validated persisted lane measurement envelope."""

    run_id: str
    campaign_kind: str
    campaign_index: int
    block: int
    position: int
    ordinal: int
    arm_id: str
    declared_arm_id: str
    lane_id: str
    oracle_id: str
    oracle_version: int
    fixture_digest: str
    warmup_calls: int
    metric_unit: str
    direction: str
    samples: tuple[int, ...]
    logical_start_ns: int
    logical_end_ns: int


def build_lane_envelope_document(
    *,
    run_id: str,
    campaign_kind: str,
    campaign_index: int,
    block: int,
    position: int,
    ordinal: int,
    arm_id: str,
    declared_arm_id: str,
    lane_id: str,
    oracle_id: str,
    oracle_version: int,
    fixture_digest: str,
    warmup_calls: int,
    samples: tuple[int, ...],
    logical_start_ns: int,
    logical_end_ns: int,
) -> dict[str, Any]:
    """Build one closed ``synthetic-lane-envelope`` record."""

    return {
        "kind": LANE_ENVELOPE_KIND,
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "run_id": run_id,
        "campaign_kind": campaign_kind,
        "campaign_index": campaign_index,
        "block": block,
        "position": position,
        "ordinal": ordinal,
        "arm_id": arm_id,
        "declared_arm_id": declared_arm_id,
        "lane_id": lane_id,
        "oracle_id": oracle_id,
        "oracle_version": oracle_version,
        "fixture_digest": fixture_digest,
        "warmup_calls": warmup_calls,
        "metric_unit": SYNTHETIC_METRIC_UNIT,
        "direction": SYNTHETIC_DIRECTION,
        "samples": list(samples),
        "logical_start_ns": logical_start_ns,
        "logical_end_ns": logical_end_ns,
        "evidence_origin": SYNTHETIC_ORIGIN,
        "qualification_scope": SIMULATED_SCOPE,
    }


def validate_lane_envelope_document(document: object) -> LaneEnvelope:
    """Validate one stored lane envelope, including its logical arithmetic."""

    field = "lane-envelope"
    doc = _require_mapping(document, _LANE_KEYS, field)
    if doc["kind"] != LANE_ENVELOPE_KIND or doc["schema_version"] != INTERNAL_SCHEMA_VERSION:
        raise _fail("lane envelope kind/version is invalid", field)
    _require_origin_scope(doc, field)
    run_id = validate_uuid4(doc["run_id"], "lane-envelope.run_id")
    kind, index = _require_campaign(doc, field)
    block, position, ordinal = _require_slot_position(doc, field)
    arm_id = validate_semantic_id(doc["arm_id"], "lane-envelope.arm_id")
    declared_arm_id = validate_semantic_id(
        doc["declared_arm_id"], "lane-envelope.declared_arm_id"
    )
    lane_id = validate_semantic_id(doc["lane_id"], "lane-envelope.lane_id")
    oracle_id = validate_semantic_id(doc["oracle_id"], "lane-envelope.oracle_id")
    oracle_version = _require_int(
        doc["oracle_version"], "lane-envelope.oracle_version", minimum=1
    )
    fixture_digest = validate_digest(doc["fixture_digest"], "lane-envelope.fixture_digest")
    warmup_calls = _require_int(doc["warmup_calls"], "lane-envelope.warmup_calls")
    if doc["metric_unit"] != SYNTHETIC_METRIC_UNIT:
        raise _fail("lane envelope metric unit must be nanoseconds", field)
    if doc["direction"] != SYNTHETIC_DIRECTION:
        raise _fail("lane envelope direction must be lower-is-better", field)
    raw_samples = doc["samples"]
    if not isinstance(raw_samples, list) or not raw_samples:
        raise _fail("lane envelope samples must be a non-empty array", "lane-envelope.samples")
    samples = tuple(
        _require_int(
            value,
            "lane-envelope.samples[]",
            minimum=1,
            maximum=MAX_SYNTHETIC_SAMPLE_NS,
        )
        for value in raw_samples
    )
    start = _require_int(doc["logical_start_ns"], "lane-envelope.logical_start_ns", maximum=MAX_LOGICAL_NS)
    end = _require_int(doc["logical_end_ns"], "lane-envelope.logical_end_ns", maximum=MAX_LOGICAL_NS)
    expected_end = start + warmup_calls + sum(samples)
    if end != expected_end:
        raise _fail(
            "lane envelope logical ticks must equal warmups plus the sample sum",
            "lane-envelope.logical_end_ns",
        )
    return LaneEnvelope(
        run_id=run_id,
        campaign_kind=kind,
        campaign_index=index,
        block=block,
        position=position,
        ordinal=ordinal,
        arm_id=arm_id,
        declared_arm_id=declared_arm_id,
        lane_id=lane_id,
        oracle_id=oracle_id,
        oracle_version=oracle_version,
        fixture_digest=fixture_digest,
        warmup_calls=warmup_calls,
        metric_unit=SYNTHETIC_METRIC_UNIT,
        direction=SYNTHETIC_DIRECTION,
        samples=samples,
        logical_start_ns=start,
        logical_end_ns=end,
    )


@dataclass(frozen=True)
class SlotComplete:
    """One validated slot completion record."""

    run_id: str
    campaign_kind: str
    campaign_index: int
    block: int
    position: int
    ordinal: int
    arm_id: str
    declared_arm_id: str
    lanes: tuple[tuple[str, str], ...]


def build_slot_complete_document(
    *,
    run_id: str,
    campaign_kind: str,
    campaign_index: int,
    block: int,
    position: int,
    ordinal: int,
    arm_id: str,
    declared_arm_id: str,
    lanes: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    """Build one closed ``synthetic-slot-complete`` record."""

    return {
        "kind": SLOT_COMPLETE_KIND,
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "run_id": run_id,
        "campaign_kind": campaign_kind,
        "campaign_index": campaign_index,
        "block": block,
        "position": position,
        "ordinal": ordinal,
        "arm_id": arm_id,
        "declared_arm_id": declared_arm_id,
        "lanes": [{"lane_id": lane_id, "digest": digest} for lane_id, digest in lanes],
        "evidence_origin": SYNTHETIC_ORIGIN,
        "qualification_scope": SIMULATED_SCOPE,
    }


def validate_slot_complete_document(document: object) -> SlotComplete:
    """Validate one stored slot completion record."""

    field = "slot-complete"
    doc = _require_mapping(document, _SLOT_COMPLETE_KEYS, field)
    if doc["kind"] != SLOT_COMPLETE_KIND or doc["schema_version"] != INTERNAL_SCHEMA_VERSION:
        raise _fail("slot completion kind/version is invalid", field)
    _require_origin_scope(doc, field)
    run_id = validate_uuid4(doc["run_id"], "slot-complete.run_id")
    kind, index = _require_campaign(doc, field)
    block, position, ordinal = _require_slot_position(doc, field)
    arm_id = validate_semantic_id(doc["arm_id"], "slot-complete.arm_id")
    declared_arm_id = validate_semantic_id(
        doc["declared_arm_id"], "slot-complete.declared_arm_id"
    )
    raw_lanes = doc["lanes"]
    if not isinstance(raw_lanes, list) or not raw_lanes:
        raise _fail("slot completion lanes must be a non-empty array", "slot-complete.lanes")
    lanes: list[tuple[str, str]] = []
    for position_index, raw in enumerate(raw_lanes):
        if not isinstance(raw, Mapping) or set(raw) != _SLOT_LANE_KEYS:
            raise _fail(
                "slot completion lanes must use the exact closed field set",
                f"slot-complete.lanes[{position_index}]",
            )
        lanes.append(
            (
                validate_semantic_id(raw["lane_id"], "slot-complete.lanes[].lane_id"),
                validate_digest(raw["digest"], "slot-complete.lanes[].digest"),
            )
        )
    if len({lane_id for lane_id, _ in lanes}) != len(lanes):
        raise _fail("slot completion lanes must be unique", "slot-complete.lanes")
    return SlotComplete(
        run_id=run_id,
        campaign_kind=kind,
        campaign_index=index,
        block=block,
        position=position,
        ordinal=ordinal,
        arm_id=arm_id,
        declared_arm_id=declared_arm_id,
        lanes=tuple(lanes),
    )


# ---------------------------------------------------------------------------
# Control check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlReport:
    """One validated persisted synthetic A/A equality report."""

    campaign_index: int
    control_contract_id: str
    source_arm_id: str
    checked_pairs: int
    lane_ids: tuple[str, ...]


def build_control_report_document(
    *,
    campaign_index: int,
    control_contract_id: str,
    source_arm_id: str,
    checked_pairs: int,
    lane_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Build one closed ``synthetic-control-check`` PASS record."""

    return {
        "kind": CONTROL_CHECK_KIND,
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "campaign_index": campaign_index,
        "control_contract_id": control_contract_id,
        "source_arm_id": source_arm_id,
        "status": "pass",
        "checked_pairs": checked_pairs,
        "lane_ids": list(lane_ids),
        "evidence_origin": SYNTHETIC_ORIGIN,
        "qualification_scope": SIMULATED_SCOPE,
    }


def validate_control_report_document(document: object) -> ControlReport:
    """Validate one stored control equality report."""

    field = "control-check"
    doc = _require_mapping(document, _CONTROL_CHECK_KEYS, field)
    if doc["kind"] != CONTROL_CHECK_KIND or doc["schema_version"] != INTERNAL_SCHEMA_VERSION:
        raise _fail("control report kind/version is invalid", field)
    _require_origin_scope(doc, field)
    index = _require_int(doc["campaign_index"], "control-check.campaign_index")
    contract_id = validate_semantic_id(
        doc["control_contract_id"], "control-check.control_contract_id"
    )
    source_arm_id = validate_semantic_id(
        doc["source_arm_id"], "control-check.source_arm_id"
    )
    if doc["status"] != "pass":
        raise _fail("a persisted control report can only record equality", field)
    checked_pairs = _require_int(doc["checked_pairs"], "control-check.checked_pairs", minimum=1)
    raw_lanes = doc["lane_ids"]
    if not isinstance(raw_lanes, list) or not raw_lanes:
        raise _fail("control-check.lane_ids must be a non-empty array", "control-check.lane_ids")
    lane_ids = tuple(
        validate_semantic_id(lane_id, "control-check.lane_ids[]") for lane_id in raw_lanes
    )
    if len(set(lane_ids)) != len(lane_ids):
        raise _fail("control-check.lane_ids must be unique", "control-check.lane_ids")
    return ControlReport(
        campaign_index=index,
        control_contract_id=contract_id,
        source_arm_id=source_arm_id,
        checked_pairs=checked_pairs,
        lane_ids=lane_ids,
    )


# ---------------------------------------------------------------------------
# Seal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SealRecord:
    """One validated structural completion seal."""

    run_id: str
    experiment_id: str
    freeze_digest: str
    schedule_digest: str
    scenario_digest: str
    controls_completed: int
    treatments_completed: int
    slots_completed: int
    lane_envelopes: int
    synthetic_samples: int
    last_logical_ns: int
    files: tuple[tuple[str, str, int], ...]


def build_seal_document(
    *,
    run_id: str,
    experiment_id: str,
    freeze_digest: str,
    schedule_digest: str,
    scenario_digest: str,
    controls_completed: int,
    treatments_completed: int,
    slots_completed: int,
    lane_envelopes: int,
    synthetic_samples: int,
    last_logical_ns: int,
    files: tuple[tuple[str, str, int], ...],
) -> dict[str, Any]:
    """Build one closed ``synthetic-execution-seal`` record."""

    return {
        "kind": SEAL_KIND,
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "run_id": run_id,
        "experiment_id": experiment_id,
        "evidence_origin": SYNTHETIC_ORIGIN,
        "qualification_scope": SIMULATED_SCOPE,
        "freeze_digest": freeze_digest,
        "schedule_digest": schedule_digest,
        "scenario_digest": scenario_digest,
        "status": SEAL_STATUS,
        "controls_completed": controls_completed,
        "treatments_completed": treatments_completed,
        "slots_completed": slots_completed,
        "lane_envelopes": lane_envelopes,
        "synthetic_samples": synthetic_samples,
        "last_logical_ns": last_logical_ns,
        "files": [
            {"path": path, "digest": digest, "byte_length": length}
            for path, digest, length in files
        ],
    }


def validate_seal_document(document: object) -> SealRecord:
    """Validate one stored structural seal record."""

    field = "seal"
    doc = _require_mapping(document, _SEAL_KEYS, field)
    if doc["kind"] != SEAL_KIND or doc["schema_version"] != INTERNAL_SCHEMA_VERSION:
        raise _fail("seal kind/version is invalid", field)
    _require_origin_scope(doc, field)
    if doc["status"] != SEAL_STATUS:
        raise _fail("seal status must be sealed-structural", "seal.status")
    run_id = validate_uuid4(doc["run_id"], "seal.run_id")
    experiment_id = validate_semantic_id(doc["experiment_id"], "seal.experiment_id")
    freeze_digest = validate_digest(doc["freeze_digest"], "seal.freeze_digest")
    schedule_digest = validate_digest(doc["schedule_digest"], "seal.schedule_digest")
    scenario_digest = validate_digest(doc["scenario_digest"], "seal.scenario_digest")
    counts = {}
    for name in (
        "controls_completed",
        "treatments_completed",
        "slots_completed",
        "lane_envelopes",
        "synthetic_samples",
        "last_logical_ns",
    ):
        counts[name] = _require_int(doc[name], f"seal.{name}", maximum=MAX_LOGICAL_NS)
    raw_files = doc["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise _fail("seal.files must be a non-empty array", "seal.files")
    files: list[tuple[str, str, int]] = []
    for index, raw in enumerate(raw_files):
        if not isinstance(raw, Mapping) or set(raw) != _SEAL_FILE_KEYS:
            raise _fail(
                "seal.files entries must use the exact closed field set",
                f"seal.files[{index}]",
            )
        path = raw["path"]
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/"):
            raise _fail("seal.files paths must be safe relative paths", f"seal.files[{index}]")
        files.append(
            (
                path,
                validate_digest(raw["digest"], f"seal.files[{index}].digest"),
                _require_int(raw["byte_length"], f"seal.files[{index}].byte_length", minimum=0),
            )
        )
    paths = [path for path, _, _ in files]
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise _fail("seal.files must be sorted and unique", "seal.files")
    if "seal.json" in paths:
        raise _fail("a seal must not list itself", "seal.files")
    return SealRecord(
        run_id=run_id,
        experiment_id=experiment_id,
        freeze_digest=freeze_digest,
        schedule_digest=schedule_digest,
        scenario_digest=scenario_digest,
        controls_completed=counts["controls_completed"],
        treatments_completed=counts["treatments_completed"],
        slots_completed=counts["slots_completed"],
        lane_envelopes=counts["lane_envelopes"],
        synthetic_samples=counts["synthetic_samples"],
        last_logical_ns=counts["last_logical_ns"],
        files=tuple(files),
    )


# ---------------------------------------------------------------------------
# Recorder: path derivation and exclusive writes
# ---------------------------------------------------------------------------


def event_relative_path(sequence: int) -> str:
    """Return the exact journal path for one sequence number."""

    return f"events/{sequence:08d}.json"


def readiness_relative_path(campaign_kind: str, campaign_index: int) -> str:
    """Return the exact readiness path for one campaign."""

    return f"readiness/{campaign_kind}-{campaign_index:04d}.json"


def slot_relative_dir(campaign_kind: str, campaign_index: int, block: int, position: int) -> str:
    """Return the exact slot directory for one campaign block position."""

    return (
        f"slots/{campaign_kind}-{campaign_index:04d}"
        f"/block-{block:04d}/slot-{position:04d}"
    )


def lane_relative_path(
    campaign_kind: str, campaign_index: int, block: int, position: int, lane_id: str
) -> str:
    """Return the exact lane envelope path for one slot and lane."""

    return f"{slot_relative_dir(campaign_kind, campaign_index, block, position)}/{lane_id}.json"


def slot_complete_relative_path(
    campaign_kind: str, campaign_index: int, block: int, position: int
) -> str:
    """Return the exact slot completion path."""

    return f"{slot_relative_dir(campaign_kind, campaign_index, block, position)}/complete.json"


def control_relative_path(campaign_index: int) -> str:
    """Return the exact control report path for one control campaign."""

    return f"controls/control-{campaign_index:04d}.json"


class Recorder:
    """Append-only writer for the closed synthetic evidence journal."""

    def __init__(self, store: Any, run_id: str) -> None:
        self._store = store
        self._run_id = validate_uuid4(run_id, "run_id")
        self._sequence = 0

    @property
    def sequence(self) -> int:
        """Return the last written event sequence number."""

        return self._sequence

    def write_event(
        self,
        *,
        from_state: RunState | str,
        to_state: RunState | str,
        reason: str,
        logical_ns: int,
    ) -> tuple[str, str]:
        """Write the next state event and return ``(relative_path, raw_digest)``."""

        sequence = self._sequence + 1
        document = build_event_document(
            sequence=sequence,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            logical_ns=logical_ns,
        )
        validate_event_document(document)
        relative = event_relative_path(sequence)
        digest = self._store.write_new(relative, document)
        self._sequence = sequence
        return relative, digest

    def write_readiness(self, document: Mapping[str, Any]) -> str:
        """Validate and write one readiness record."""

        record = validate_readiness_document(document)
        return self._store.write_new(
            readiness_relative_path(record.campaign_kind, record.campaign_index),
            document,
        )

    def write_lane_envelope(self, document: Mapping[str, Any]) -> str:
        """Validate and write one lane envelope."""

        envelope = validate_lane_envelope_document(document)
        return self._store.write_new(
            lane_relative_path(
                envelope.campaign_kind,
                envelope.campaign_index,
                envelope.block,
                envelope.position,
                envelope.lane_id,
            ),
            document,
        )

    def write_slot_complete(self, document: Mapping[str, Any]) -> str:
        """Validate and write one slot completion record."""

        record = validate_slot_complete_document(document)
        return self._store.write_new(
            slot_complete_relative_path(
                record.campaign_kind,
                record.campaign_index,
                record.block,
                record.position,
            ),
            document,
        )

    def write_control_report(self, document: Mapping[str, Any]) -> str:
        """Validate and write one control equality report."""

        report = validate_control_report_document(document)
        return self._store.write_new(control_relative_path(report.campaign_index), document)

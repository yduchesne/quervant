"""Synthetic control (A/A) scheduling and the frozen control contract.

The v1 protocol declares only a ``control_contract_id``. It does **not** declare
real A/A arm identities, thresholds or selection policy, so BM-03 must not invent
one. The only executable policy here is the simulation-only
``synthetic-exact-equality`` contract: both control replicas map to one declared
source arm and their raw sample tuples must be strictly equal.

This is a synthetic mechanical oracle. It is not an official stability
qualification and never becomes a Gate A-E receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.contracts import ArmMultiplicity, ExperimentBundle
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BM_SCHEMA_INVALID,
    BenchError,
)
from ..config.identity import (
    validate_nonnegative_int,
    validate_positive_int,
    validate_semantic_id,
)
from ..execution.contracts import (
    CONTROL_CONTRACT_ID,
    CONTROL_LEFT_ARM_ID,
    CONTROL_RIGHT_ARM_ID,
    CONTROL_STATUS_NOT_REQUIRED,
    CONTROL_STATUS_SCHEDULED,
    INTERNAL_SCHEMA_VERSION,
    MAX_CONTROL_CAMPAIGNS,
    MAX_TREATMENT_CAMPAIGNS,
    SIMULATED_SCOPE,
    SYNTHETIC_ORIGIN,
)
from .schedule import (
    SEEDED_MODE,
    CompiledSchedule,
    ScheduleSpec,
    _compile_spec,
    schedule_document,
    validate_schedule_document,
)

CONTROL_SCHEDULE_KIND = "synthetic-control-schedule"

_SCHEDULE_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "schema_version",
        "algorithm_id",
        "schedule_id",
        "protocol_digest",
        "seed",
        "blocks",
        "slots_per_block",
        "slots",
    }
)
_CONTROL_KEYS: frozenset[str] = frozenset(
    {"control_contract_id", "source_arm_id", "campaign_count", "status"}
)
_ORIGIN_KEYS: frozenset[str] = frozenset(
    {"evidence_origin", "qualification_scope"}
)
_NOT_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "schema_version",
        "control_contract_id",
        "source_arm_id",
        "campaign_count",
        "status",
        "slots",
    }
)


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class ProtocolCampaigns:
    """Campaign declarations the typed ``Protocol`` record does not retain."""

    required_controls: int
    required_treatments: int
    control_contract_id: str
    clock_contract_id: str


@dataclass(frozen=True)
class ControlSchedule:
    """One frozen control schedule (or the closed ``not-required`` record)."""

    status: str
    control_contract_id: str
    source_arm_id: str
    campaign_count: int
    compiled: CompiledSchedule | None
    document: Mapping[str, Any]
    digest: str


def read_protocol_campaigns(bundle: ExperimentBundle) -> ProtocolCampaigns:
    """Read the campaign/clock declarations out of the validated protocol."""

    document = bundle.protocol_document
    campaigns = document.get("campaigns")
    measurement = document.get("measurement")
    if not isinstance(campaigns, Mapping) or not isinstance(measurement, Mapping):
        raise BenchError(
            BM_SCHEMA_INVALID,
            "protocol must declare campaigns and measurement",
            field_path="protocol",
        )
    required_controls = validate_nonnegative_int(
        campaigns.get("required_controls"), "campaigns.required_controls"
    )
    required_treatments = validate_positive_int(
        campaigns.get("required_treatments"), "campaigns.required_treatments"
    )
    control_contract_id = validate_semantic_id(
        campaigns.get("control_contract_id"), "campaigns.control_contract_id"
    )
    clock_contract_id = validate_semantic_id(
        measurement.get("clock_contract_id"), "measurement.clock_contract_id"
    )
    if required_controls > MAX_CONTROL_CAMPAIGNS:
        raise _fail(
            f"required_controls exceeds the {MAX_CONTROL_CAMPAIGNS} budget",
            "campaigns.required_controls",
        )
    if required_treatments > MAX_TREATMENT_CAMPAIGNS:
        raise _fail(
            f"required_treatments exceeds the {MAX_TREATMENT_CAMPAIGNS} budget",
            "campaigns.required_treatments",
        )
    return ProtocolCampaigns(
        required_controls=required_controls,
        required_treatments=required_treatments,
        control_contract_id=control_contract_id,
        clock_contract_id=clock_contract_id,
    )


def _require_control_source(bundle: ExperimentBundle, source_arm_id: str) -> str:
    declared = {arm.arm_id for arm in bundle.experiment.arms}
    if not isinstance(source_arm_id, str) or source_arm_id not in declared:
        raise _fail(
            "the control source arm must be a declared experiment arm",
            "scenario.control_source_arm_id",
        )
    return source_arm_id


def build_control_schedule(
    bundle: ExperimentBundle, *, control_source_arm_id: str
) -> ControlSchedule:
    """Build the frozen control schedule for one validated bundle."""

    campaigns = read_protocol_campaigns(bundle)
    source_arm_id = _require_control_source(bundle, control_source_arm_id)

    if campaigns.required_controls == 0:
        document: dict[str, Any] = {
            "kind": CONTROL_SCHEDULE_KIND,
            "schema_version": INTERNAL_SCHEMA_VERSION,
            "control_contract_id": campaigns.control_contract_id,
            "source_arm_id": source_arm_id,
            "campaign_count": 0,
            "status": CONTROL_STATUS_NOT_REQUIRED,
            "slots": [],
            "evidence_origin": SYNTHETIC_ORIGIN,
            "qualification_scope": SIMULATED_SCOPE,
        }
        return ControlSchedule(
            status=CONTROL_STATUS_NOT_REQUIRED,
            control_contract_id=campaigns.control_contract_id,
            source_arm_id=source_arm_id,
            campaign_count=0,
            compiled=None,
            document=document,
            digest=content_digest(document),
        )

    if campaigns.control_contract_id != CONTROL_CONTRACT_ID:
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "only the synthetic-exact-equality control contract is executable",
            field_path="campaigns.control_contract_id",
        )
    blocks = bundle.protocol.schedule.blocks
    if blocks % 2 != 0:
        raise _fail(
            "a required synthetic control needs an even schedule.blocks",
            "schedule.blocks",
        )
    spec = ScheduleSpec(
        schedule_id=bundle.protocol.schedule.schedule_id,
        mode=SEEDED_MODE,
        blocks=blocks,
        slots_per_block=2,
        seed=bundle.protocol.schedule.seed,
        multiplicities=(
            ArmMultiplicity(arm_id=CONTROL_LEFT_ARM_ID, slots_per_block=1),
            ArmMultiplicity(arm_id=CONTROL_RIGHT_ARM_ID, slots_per_block=1),
        ),
        explicit_orders=None,
        protocol_digest=bundle.protocol_digest,
    )
    compiled = _compile_spec(spec)
    document = dict(schedule_document(compiled))
    document.update(
        {
            "kind": CONTROL_SCHEDULE_KIND,
            "control_contract_id": campaigns.control_contract_id,
            "source_arm_id": source_arm_id,
            "campaign_count": campaigns.required_controls,
            "status": CONTROL_STATUS_SCHEDULED,
            "evidence_origin": SYNTHETIC_ORIGIN,
            "qualification_scope": SIMULATED_SCOPE,
        }
    )
    return ControlSchedule(
        status=CONTROL_STATUS_SCHEDULED,
        control_contract_id=campaigns.control_contract_id,
        source_arm_id=source_arm_id,
        campaign_count=campaigns.required_controls,
        compiled=compiled,
        document=document,
        digest=content_digest(document),
    )


def validate_control_schedule_document(document: object) -> ControlSchedule:
    """Re-validate stored ``synthetic-control-schedule`` bytes."""

    if not isinstance(document, Mapping):
        raise _fail("a control schedule document must be an object", "control-schedule")
    doc = document
    if doc.get("kind") != CONTROL_SCHEDULE_KIND:
        raise _fail("control schedule kind is invalid", "control-schedule.kind")
    if doc.get("schema_version") != INTERNAL_SCHEMA_VERSION:
        raise _fail("control schedule version is invalid", "control-schedule.schema_version")
    if set(doc) not in (
        _SCHEDULE_KEYS | _CONTROL_KEYS | _ORIGIN_KEYS,
        _NOT_REQUIRED_KEYS | _ORIGIN_KEYS,
    ):
        raise _fail(
            "control schedule must use an exact closed field set",
            "control-schedule",
        )
    if doc["evidence_origin"] != SYNTHETIC_ORIGIN or doc["qualification_scope"] != SIMULATED_SCOPE:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "control schedule origin/scope must remain synthetic/simulated",
            field_path="control-schedule.qualification_scope",
        )
    contract_id = validate_semantic_id(
        doc["control_contract_id"], "control-schedule.control_contract_id"
    )
    source_arm_id = validate_semantic_id(
        doc["source_arm_id"], "control-schedule.source_arm_id"
    )
    campaign_count = validate_nonnegative_int(
        doc["campaign_count"], "control-schedule.campaign_count"
    )
    status = doc["status"]
    slots = doc["slots"]
    if not isinstance(slots, list):
        raise _fail("control-schedule.slots must be an array", "control-schedule.slots")

    if status == CONTROL_STATUS_NOT_REQUIRED:
        if campaign_count != 0 or slots:
            raise _fail(
                "a not-required control schedule must declare no campaign or slot",
                "control-schedule.status",
            )
        return ControlSchedule(
            status=status,
            control_contract_id=contract_id,
            source_arm_id=source_arm_id,
            campaign_count=0,
            compiled=None,
            document=doc,
            digest=content_digest(doc),
        )
    if status != CONTROL_STATUS_SCHEDULED:
        raise _fail("control schedule status is not recognised", "control-schedule.status")
    if campaign_count < 1:
        raise _fail(
            "a scheduled control must declare at least one campaign",
            "control-schedule.campaign_count",
        )
    schedule_payload = {key: doc[key] for key in _SCHEDULE_KEYS}
    compiled = validate_schedule_document(schedule_payload)
    if compiled.slots_per_block != 2:
        raise _fail(
            "a synthetic control schedule must have exactly two slots per block",
            "control-schedule.slots_per_block",
        )
    declared_arms = {slot.arm_id for slot in compiled.slots}
    if declared_arms != {CONTROL_LEFT_ARM_ID, CONTROL_RIGHT_ARM_ID}:
        raise _fail(
            "a synthetic control schedule must use the two frozen control aliases",
            "control-schedule.slots",
        )
    return ControlSchedule(
        status=status,
        control_contract_id=contract_id,
        source_arm_id=source_arm_id,
        campaign_count=campaign_count,
        compiled=compiled,
        document=doc,
        digest=content_digest(doc),
    )

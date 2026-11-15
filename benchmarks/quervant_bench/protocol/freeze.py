"""Freeze-before-acquisition binding for synthetic execution.

The freeze record binds the exact experiment, workload, protocol, adapter,
compiled schedule, control schedule, synthetic scenario, declared policy and
analysis identities **before** the first adapter instance, readiness provider call
or logical-clock advance. Its source/build entries are explicitly synthetic
markers: they are never Git proofs, build attestations or official
authorisations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..config.codec import content_digest
from ..config.contracts import ExperimentBundle
from ..config.errors import BM_IDENTITY_INVALID, BenchError
from ..config.identity import (
    validate_digest,
    validate_nonnegative_int,
    validate_positive_int,
    validate_semantic_id,
    validate_uuid4,
)
from ..execution.contracts import (
    INTERNAL_SCHEMA_VERSION,
    MAX_CONTROL_CAMPAIGNS,
    MAX_TREATMENT_CAMPAIGNS,
    SIMULATED_SCOPE,
    SYNTHETIC_ORIGIN,
)
from .controls import ControlSchedule, read_protocol_campaigns
from .schedule import CompiledSchedule

FREEZE_KIND = "synthetic-freeze"
SOURCE_BINDING_KIND = "synthetic-source-binding"
BUILD_BINDING_KIND = "synthetic-build-binding"

FREEZE_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "schema_version",
        "run_id",
        "experiment_id",
        "evidence_origin",
        "qualification_scope",
        "experiment_digest",
        "workload_digest",
        "protocol_digest",
        "adapter_digest",
        "schedule_digest",
        "control_schedule_digest",
        "scenario_digest",
        "source_binding_digest",
        "build_binding_digest",
        "policy_digest",
        "analysis_digest",
        "oracle_id",
        "oracle_version",
        "arm_ids",
        "lane_ids",
        "clock_contract_id",
        "required_controls",
        "required_treatments",
    }
)


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class FreezeRecord:
    """One validated internal freeze record."""

    run_id: str
    experiment_id: str
    experiment_digest: str
    workload_digest: str
    protocol_digest: str
    adapter_digest: str
    schedule_digest: str
    control_schedule_digest: str
    scenario_digest: str
    source_binding_digest: str
    build_binding_digest: str
    policy_digest: str
    analysis_digest: str
    oracle_id: str
    oracle_version: int
    arm_ids: tuple[str, ...]
    lane_ids: tuple[str, ...]
    clock_contract_id: str
    required_controls: int
    required_treatments: int
    document: Mapping[str, Any]
    freeze_digest: str


def source_binding_digest(scenario_digest: str) -> str:
    """Return the explicit synthetic source marker binding the scenario."""

    return content_digest(
        {"kind": SOURCE_BINDING_KIND, "scenario_digest": scenario_digest}
    )


def build_binding_digest(adapter_digest: str) -> str:
    """Return the explicit synthetic build marker binding the adapter manifest."""

    return content_digest({"kind": BUILD_BINDING_KIND, "adapter_digest": adapter_digest})


def build_freeze_document(
    *,
    bundle: ExperimentBundle,
    run_id: str,
    schedule: CompiledSchedule,
    control_schedule: ControlSchedule,
    scenario_digest: str,
) -> tuple[dict[str, Any], str]:
    """Build the closed freeze payload and its canonical digest."""

    run = validate_uuid4(run_id, "run_id")
    campaign_declarations = read_protocol_campaigns(bundle)
    adapter_digest = content_digest(dict(bundle.adapter_document))
    document: dict[str, Any] = {
        "kind": FREEZE_KIND,
        "schema_version": INTERNAL_SCHEMA_VERSION,
        "run_id": run,
        "experiment_id": bundle.experiment.experiment_id,
        "evidence_origin": SYNTHETIC_ORIGIN,
        "qualification_scope": SIMULATED_SCOPE,
        "experiment_digest": content_digest(dict(bundle.experiment_document)),
        "workload_digest": content_digest(dict(bundle.workload_document)),
        "protocol_digest": content_digest(dict(bundle.protocol_document)),
        "adapter_digest": adapter_digest,
        "schedule_digest": schedule.schedule_digest,
        "control_schedule_digest": control_schedule.digest,
        "scenario_digest": validate_digest(scenario_digest, "scenario_digest"),
        "source_binding_digest": source_binding_digest(scenario_digest),
        "build_binding_digest": build_binding_digest(adapter_digest),
        "policy_digest": bundle.experiment.policy.policy_digest,
        "analysis_digest": bundle.experiment.analysis.analysis_digest,
        "oracle_id": bundle.workload.oracle_id,
        "oracle_version": bundle.workload.oracle_version,
        "arm_ids": sorted(arm.arm_id for arm in bundle.experiment.arms),
        "lane_ids": sorted(lane.lane_id for lane in bundle.workload.lanes),
        "clock_contract_id": campaign_declarations.clock_contract_id,
        "required_controls": campaign_declarations.required_controls,
        "required_treatments": campaign_declarations.required_treatments,
    }
    return document, content_digest(document)


def validate_freeze_document(document: object) -> FreezeRecord:
    """Validate a stored freeze payload and recompute its synthetic bindings."""

    if not isinstance(document, Mapping):
        raise _fail("a freeze document must be an object", "freeze")
    doc = document
    if set(doc) != FREEZE_KEYS:
        raise _fail("a freeze document must use the exact closed field set", "freeze")
    if doc["kind"] != FREEZE_KIND or doc["schema_version"] != INTERNAL_SCHEMA_VERSION:
        raise _fail("freeze kind/version is invalid", "freeze.kind")
    if (
        doc["evidence_origin"] != SYNTHETIC_ORIGIN
        or doc["qualification_scope"] != SIMULATED_SCOPE
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "a BM-03 freeze must remain synthetic/simulated",
            field_path="freeze.qualification_scope",
        )
    run_id = validate_uuid4(doc["run_id"], "freeze.run_id")
    experiment_id = validate_semantic_id(doc["experiment_id"], "freeze.experiment_id")
    digests = {}
    for name in (
        "experiment_digest",
        "workload_digest",
        "protocol_digest",
        "adapter_digest",
        "schedule_digest",
        "control_schedule_digest",
        "scenario_digest",
        "source_binding_digest",
        "build_binding_digest",
        "policy_digest",
        "analysis_digest",
    ):
        digests[name] = validate_digest(doc[name], f"freeze.{name}")
    if digests["source_binding_digest"] != source_binding_digest(digests["scenario_digest"]):
        raise _fail(
            "freeze.source_binding_digest does not bind the frozen scenario",
            "freeze.source_binding_digest",
        )
    if digests["build_binding_digest"] != build_binding_digest(digests["adapter_digest"]):
        raise _fail(
            "freeze.build_binding_digest does not bind the frozen adapter manifest",
            "freeze.build_binding_digest",
        )
    oracle_id = validate_semantic_id(doc["oracle_id"], "freeze.oracle_id")
    oracle_version = validate_positive_int(doc["oracle_version"], "freeze.oracle_version")
    raw_arms = doc["arm_ids"]
    raw_lanes = doc["lane_ids"]
    if not isinstance(raw_arms, list) or not raw_arms:
        raise _fail("freeze.arm_ids must be a non-empty array", "freeze.arm_ids")
    if not isinstance(raw_lanes, list) or not raw_lanes:
        raise _fail("freeze.lane_ids must be a non-empty array", "freeze.lane_ids")
    arm_ids = tuple(validate_semantic_id(item, "freeze.arm_ids[]") for item in raw_arms)
    lane_ids = tuple(validate_semantic_id(item, "freeze.lane_ids[]") for item in raw_lanes)
    for name, values in (("arm_ids", arm_ids), ("lane_ids", lane_ids)):
        if len(set(values)) != len(values):
            raise _fail(f"freeze.{name} must be unique", f"freeze.{name}")
        if list(values) != sorted(values):
            raise _fail(f"freeze.{name} must be sorted", f"freeze.{name}")
    clock_contract_id = validate_semantic_id(
        doc["clock_contract_id"], "freeze.clock_contract_id"
    )
    required_controls = validate_nonnegative_int(
        doc["required_controls"], "freeze.required_controls"
    )
    required_treatments = validate_positive_int(
        doc["required_treatments"], "freeze.required_treatments"
    )
    if required_controls > MAX_CONTROL_CAMPAIGNS or required_treatments > MAX_TREATMENT_CAMPAIGNS:
        raise _fail("freeze campaign counts exceed the simulator budget", "freeze")
    return FreezeRecord(
        run_id=run_id,
        experiment_id=experiment_id,
        experiment_digest=digests["experiment_digest"],
        workload_digest=digests["workload_digest"],
        protocol_digest=digests["protocol_digest"],
        adapter_digest=digests["adapter_digest"],
        schedule_digest=digests["schedule_digest"],
        control_schedule_digest=digests["control_schedule_digest"],
        scenario_digest=digests["scenario_digest"],
        source_binding_digest=digests["source_binding_digest"],
        build_binding_digest=digests["build_binding_digest"],
        policy_digest=digests["policy_digest"],
        analysis_digest=digests["analysis_digest"],
        oracle_id=oracle_id,
        oracle_version=oracle_version,
        arm_ids=arm_ids,
        lane_ids=lane_ids,
        clock_contract_id=clock_contract_id,
        required_controls=required_controls,
        required_treatments=required_treatments,
        document=doc,
        freeze_digest=content_digest(doc),
    )


def verify_freeze_bindings(
    record: FreezeRecord,
    *,
    bundle: ExperimentBundle,
    schedule: CompiledSchedule,
    control_schedule: ControlSchedule,
    scenario_digest: str,
) -> None:
    """Recompute every binding from current inputs and refuse any difference."""

    expected, _ = build_freeze_document(
        bundle=bundle,
        run_id=record.run_id,
        schedule=schedule,
        control_schedule=control_schedule,
        scenario_digest=scenario_digest,
    )
    for key in sorted(FREEZE_KEYS):
        if record.document.get(key) != expected[key]:
            raise _fail(
                f"frozen binding {key!r} no longer matches the live input",
                f"freeze.{key}",
            )


def require_schedule_binding(
    record: FreezeRecord, schedule: CompiledSchedule, control_schedule: ControlSchedule
) -> None:
    """Refuse a freeze whose recorded schedule digests cannot be reproduced."""

    if record.schedule_digest != schedule.schedule_digest:
        raise _fail("freeze.schedule_digest does not match the compiled schedule", "freeze.schedule_digest")
    if record.control_schedule_digest != control_schedule.digest:
        raise _fail(
            "freeze.control_schedule_digest does not match the control schedule",
            "freeze.control_schedule_digest",
        )

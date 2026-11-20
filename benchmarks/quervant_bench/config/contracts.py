"""Typed records and cross-document semantic validation for the v1 contracts.

JSON Schema validates *shape*. This module validates *semantics*: unique and
PR-agnostic identifiers, arm/lane/slot relationships, protocol/workload/adapter
bindings, origin/scope fences, receipt content identity and CLI outcome coherence.

No acquisition, scheduling, statistics, policy evaluation, gate issuance, timing
or adapter execution lives here. Those belong to later BM milestones.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol as TypingProtocol, runtime_checkable

from . import profiles, schemas
from .codec import content_digest, load_document
from .errors import (
    BLOCKED_CODES,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCOPE_MISMATCH,
    BM_UNSAFE_INPUT,
    BenchError,
    bounded_message,
    error_spec,
)
from .identity import (
    validate_digest,
    validate_nonnegative_int,
    validate_positive_int,
    validate_semantic_id,
    validate_uint64,
    validate_uuid4,
)
from .operator_schema import OPERATOR_PAYLOAD_KINDS, validate_operator_outcome

OPERATIONS: tuple[str, ...] = (
    "search",
    "index",
    "mutation",
    "compaction",
    "storage-read",
    "storage-write",
)
CACHE_REGIMES: tuple[str, ...] = (
    "warm",
    "process-cold",
    "cache-cold",
    "not-applicable",
)
METRIC_UNITS: tuple[str, ...] = (
    "nanoseconds",
    "operations-per-second",
    "bytes",
)
GATES: tuple[str, ...] = (
    "admission",
    "analysis",
    "verification",
    "acceptance",
    "attestation",
    "framework-qa",
    "source-qa",
)
RECEIPT_STATUSES: tuple[str, ...] = ("pass", "fail", "blocked", "not-executed")
EVIDENCE_ORIGINS: tuple[str, ...] = ("synthetic", "real")
QUALIFICATION_SCOPES: tuple[str, ...] = (
    "simulated",
    "official",
    "historical_replay",
)

#: The only recognised origin/scope combinations (see the strict matrix).
ALLOWED_ORIGIN_SCOPES: frozenset[tuple[str, str]] = frozenset(
    {
        ("synthetic", "simulated"),
        ("real", "official"),
        ("real", "historical_replay"),
    }
)

#: Adjacent filenames `inspect` may resolve under one experiment root.
ALLOWED_EXPERIMENT_FILES: frozenset[str] = frozenset(
    {"workloads.yaml", "protocol.yaml", "adapter.yaml"}
)


# ---------------------------------------------------------------------------
# Typed records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    source_commit: str | None = None
    source_pr: str | None = None
    historical_label: str | None = None
    notes: str | None = None

    @classmethod
    def from_doc(cls, doc: Mapping[str, Any] | None) -> Provenance | None:
        if doc is None:
            return None
        return cls(
            source_commit=doc.get("source_commit"),
            source_pr=doc.get("source_pr"),
            historical_label=doc.get("historical_label"),
            notes=doc.get("notes"),
        )


@dataclass(frozen=True)
class PolicyBinding:
    policy_id: str
    policy_version: int
    policy_digest: str


@dataclass(frozen=True)
class AnalysisBinding:
    analysis_id: str
    analysis_version: int
    analysis_digest: str


@dataclass(frozen=True)
class Arm:
    arm_id: str
    adapter_id: str
    variant: str


@dataclass(frozen=True)
class Experiment:
    experiment_id: str
    description: str
    workload_family: str
    workloads_file: str
    protocol_file: str
    adapter_file: str
    profile: str
    policy: PolicyBinding
    analysis: AnalysisBinding
    arms: tuple[Arm, ...]
    provenance: Provenance | None = None


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    digest: str
    fixture_schema: str


@dataclass(frozen=True)
class Lane:
    lane_id: str
    operation: str
    cache_regime: str
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Workload:
    workload_id: str
    dataset: Dataset
    query_semantics_id: str
    oracle_id: str
    oracle_version: int
    lanes: tuple[Lane, ...]
    provenance: Provenance | None = None


@dataclass(frozen=True)
class ArmMultiplicity:
    arm_id: str
    slots_per_block: int


@dataclass(frozen=True)
class Schedule:
    schedule_id: str
    mode: str
    blocks: int
    slots_per_block: int
    seed: int
    explicit_orders: tuple[tuple[str, ...], ...] | None = None


@dataclass(frozen=True)
class Protocol:
    protocol_id: str
    protocol_version: int
    experiment_id: str
    workload_digest: str
    arm_multiplicity: tuple[ArmMultiplicity, ...]
    schedule: Schedule
    policy: PolicyBinding
    oracle_id: str
    oracle_version: int
    metric_unit: str
    warmups_per_lane_slot: int
    samples_per_lane_slot: int
    minimum_retained_blocks: int
    measurement_retries: int
    statistics_seed: int
    provenance: Provenance | None = None


@dataclass(frozen=True)
class BuildIdentity:
    kind: str
    source_digest: str | None = None
    executable_digest: str | None = None


@dataclass(frozen=True)
class MeasurementEnvelope:
    unit: str
    direction: str


@dataclass(frozen=True)
class Adapter:
    adapter_id: str
    adapter_version: int
    engine_id: str
    operations: tuple[str, ...]
    cache_regimes: tuple[str, ...]
    oracle_semantics_id: str
    build_identity: BuildIdentity
    measurement_envelope: MeasurementEnvelope
    timeouts: Mapping[str, int]
    provenance: Provenance | None = None


@dataclass(frozen=True)
class EvidenceEntry:
    name: str
    digest: str


@dataclass(frozen=True)
class DependencyEntry:
    name: str
    digest: str
    gate: str
    receipt_id: str


@dataclass(frozen=True)
class ReceiptSubject:
    experiment_id: str
    run_id: str
    protocol_digest: str
    workload_digest: str


@dataclass(frozen=True)
class ValidatorIdentity:
    validator_id: str
    validator_version: int
    source_digest: str


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    gate: str
    status: str
    evidence_origin: str
    qualification_scope: str
    subject: ReceiptSubject
    validator: ValidatorIdentity
    inputs: tuple[EvidenceEntry, ...]
    dependencies: tuple[DependencyEntry, ...]
    outputs: tuple[EvidenceEntry, ...]
    qa_roster_digest: str | None = None
    policy_digest: str | None = None
    provenance: Provenance | None = None


@dataclass(frozen=True)
class ExperimentBundle:
    experiment: Experiment
    workload: Workload
    protocol: Protocol
    adapter: Adapter
    experiment_document: Mapping[str, Any]
    workload_document: Mapping[str, Any]
    protocol_document: Mapping[str, Any]
    adapter_document: Mapping[str, Any]

    @property
    def workload_digest(self) -> str:
        return content_digest(self.workload_document)

    @property
    def protocol_digest(self) -> str:
        return content_digest(self.protocol_document)


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"{field_name} must be a JSON object",
            field_path=field_name,
        )
    return value


def _dispatch(kind: str, document: object) -> Mapping[str, Any]:
    """Validate ``kind``/``schema_version`` and JSON Schema shape."""

    doc = _mapping(document, kind)
    if doc.get("kind") != kind:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"document kind must be {kind!r}",
            field_path="kind",
        )
    version = doc.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise BenchError(
            BM_SCHEMA_INVALID,
            "schema_version must be an integer",
            field_path="schema_version",
        )
    schemas.validate_schema(kind, version, doc)
    return doc


def _exact_keys_unique(items: list[str], field_name: str) -> None:
    if len(set(items)) != len(items):
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"{field_name} must be unique",
            field_path=field_name,
        )


def _sorted_unique_entries(
    entries: list[Mapping[str, Any]], field_name: str
) -> tuple[str, ...]:
    names = [entry["name"] for entry in entries]
    _exact_keys_unique(names, field_name)
    if names != sorted(names):
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"{field_name} must be serialized in ascending name order",
            field_path=field_name,
        )
    return tuple(names)


def validate_origin_scope(origin: object, scope: object) -> tuple[str, str]:
    """Apply the strict origin/scope matrix; never promote synthetic evidence."""

    if origin not in EVIDENCE_ORIGINS or scope not in QUALIFICATION_SCOPES:
        raise BenchError(
            BM_SCOPE_MISMATCH,
            "evidence_origin and qualification_scope must be recognised values",
            field_path="evidence_origin",
        )
    pair = (origin, scope)
    if pair not in ALLOWED_ORIGIN_SCOPES:
        raise BenchError(
            BM_SCOPE_MISMATCH,
            f"origin/scope combination {pair[0]}+{pair[1]} is not permitted",
            field_path="qualification_scope",
        )
    return pair


def _safe_reference(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field_name} must be a non-empty relative path",
            field_path=field_name,
        )
    if value.startswith("/") or "\\" in value or (len(value) > 1 and value[1] == ":"):
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field_name} must be a relative path",
            field_path=field_name,
        )
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field_name} must not contain empty, '.' or '..' segments",
            field_path=field_name,
        )
    return value


# ---------------------------------------------------------------------------
# Document validators
# ---------------------------------------------------------------------------


def validate_experiment(document: object) -> Experiment:
    doc = _dispatch("experiment", document)
    experiment_id = validate_semantic_id(doc["experiment_id"], "experiment_id")
    workload_family = validate_semantic_id(doc["workload_family"], "workload_family")
    profiles.validate_profile(doc["profile"])

    policy_doc = _mapping(doc["policy"], "policy")
    policy = PolicyBinding(
        policy_id=validate_semantic_id(policy_doc["policy_id"], "policy.policy_id"),
        policy_version=validate_positive_int(
            policy_doc["policy_version"], "policy.policy_version"
        ),
        policy_digest=validate_digest(
            policy_doc["policy_digest"], "policy.policy_digest"
        ),
    )
    analysis_doc = _mapping(doc["analysis"], "analysis")
    analysis = AnalysisBinding(
        analysis_id=validate_semantic_id(
            analysis_doc["analysis_id"], "analysis.analysis_id"
        ),
        analysis_version=validate_positive_int(
            analysis_doc["analysis_version"], "analysis.analysis_version"
        ),
        analysis_digest=validate_digest(
            analysis_doc["analysis_digest"], "analysis.analysis_digest"
        ),
    )

    arms: list[Arm] = []
    for index, raw_arm in enumerate(doc["arms"]):
        arm_doc = _mapping(raw_arm, f"arms[{index}]")
        arms.append(
            Arm(
                arm_id=validate_semantic_id(
                    arm_doc["arm_id"], f"arms[{index}].arm_id"
                ),
                adapter_id=validate_semantic_id(
                    arm_doc["adapter_id"], f"arms[{index}].adapter_id"
                ),
                variant=validate_semantic_id(
                    arm_doc["variant"], f"arms[{index}].variant"
                ),
            )
        )
    _exact_keys_unique([arm.arm_id for arm in arms], "arms[].arm_id")

    referenced = {doc["workloads_file"], doc["protocol_file"], doc["adapter_file"]}
    if len(referenced) != 3:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "workloads_file, protocol_file and adapter_file must be distinct",
            field_path="workloads_file",
        )

    return Experiment(
        experiment_id=experiment_id,
        description=doc["description"],
        workload_family=workload_family,
        workloads_file=doc["workloads_file"],
        protocol_file=doc["protocol_file"],
        adapter_file=doc["adapter_file"],
        profile=doc["profile"],
        policy=policy,
        analysis=analysis,
        arms=tuple(arms),
        provenance=Provenance.from_doc(doc.get("provenance")),
    )


def validate_workload(document: object) -> Workload:
    doc = _dispatch("workload", document)
    workload_id = validate_semantic_id(doc["workload_id"], "workload_id")
    dataset_doc = _mapping(doc["dataset"], "dataset")
    dataset = Dataset(
        dataset_id=validate_semantic_id(dataset_doc["dataset_id"], "dataset.dataset_id"),
        digest=validate_digest(dataset_doc["digest"], "dataset.digest"),
        fixture_schema=validate_semantic_id(
            dataset_doc["fixture_schema"], "dataset.fixture_schema"
        ),
    )
    query_semantics_id = validate_semantic_id(
        doc["query_semantics_id"], "query_semantics_id"
    )
    oracle_id = validate_semantic_id(doc["oracle_id"], "oracle_id")
    oracle_version = validate_positive_int(doc["oracle_version"], "oracle_version")

    lanes: list[Lane] = []
    for index, raw_lane in enumerate(doc["lanes"]):
        lane_doc = _mapping(raw_lane, f"lanes[{index}]")
        lane_id = validate_semantic_id(lane_doc["lane_id"], f"lanes[{index}].lane_id")
        operation = lane_doc["operation"]
        cache_regime = lane_doc["cache_regime"]
        if operation not in OPERATIONS:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"unsupported lane operation: {operation!r}",
                field_path=f"lanes[{index}].operation",
            )
        if cache_regime not in CACHE_REGIMES:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"unsupported cache regime: {cache_regime!r}",
                field_path=f"lanes[{index}].cache_regime",
            )
        params = _mapping(lane_doc["params"], f"lanes[{index}].params")
        for key in ("corpus_size", "top_k", "batch_size", "segment_count"):
            if key in params:
                validate_positive_int(params[key], f"lanes[{index}].params.{key}")
        for key in ("selectivity_class", "query_id"):
            if key in params:
                validate_semantic_id(params[key], f"lanes[{index}].params.{key}")
        lanes.append(
            Lane(
                lane_id=lane_id,
                operation=operation,
                cache_regime=cache_regime,
                params=dict(params),
            )
        )
    _exact_keys_unique([lane.lane_id for lane in lanes], "lanes[].lane_id")

    return Workload(
        workload_id=workload_id,
        dataset=dataset,
        query_semantics_id=query_semantics_id,
        oracle_id=oracle_id,
        oracle_version=oracle_version,
        lanes=tuple(lanes),
        provenance=Provenance.from_doc(doc.get("provenance")),
    )


def _validate_policy_binding(raw: object, field_name: str) -> PolicyBinding:
    binding = _mapping(raw, field_name)
    return PolicyBinding(
        policy_id=validate_semantic_id(
            binding["policy_id"], f"{field_name}.policy_id"
        ),
        policy_version=validate_positive_int(
            binding["policy_version"], f"{field_name}.policy_version"
        ),
        policy_digest=validate_digest(
            binding["policy_digest"], f"{field_name}.policy_digest"
        ),
    )


def validate_protocol(document: object) -> Protocol:
    doc = _dispatch("protocol", document)
    protocol_id = validate_semantic_id(doc["protocol_id"], "protocol_id")
    protocol_version = validate_positive_int(
        doc["protocol_version"], "protocol_version"
    )
    experiment_id = validate_semantic_id(doc["experiment_id"], "experiment_id")
    workload_digest = validate_digest(doc["workload_digest"], "workload_digest")

    multiplicity_docs = doc["arm_multiplicity"]
    multiplicity: list[ArmMultiplicity] = []
    for index, raw_item in enumerate(multiplicity_docs):
        item = _mapping(raw_item, f"arm_multiplicity[{index}]")
        multiplicity.append(
            ArmMultiplicity(
                arm_id=validate_semantic_id(
                    item["arm_id"], f"arm_multiplicity[{index}].arm_id"
                ),
                slots_per_block=validate_positive_int(
                    item["slots_per_block"],
                    f"arm_multiplicity[{index}].slots_per_block",
                ),
            )
        )
    _exact_keys_unique(
        [item.arm_id for item in multiplicity], "arm_multiplicity[].arm_id"
    )

    schedule_doc = _mapping(doc["schedule"], "schedule")
    schedule_id = validate_semantic_id(schedule_doc["schedule_id"], "schedule.schedule_id")
    mode = schedule_doc["mode"]
    blocks = validate_positive_int(schedule_doc["blocks"], "schedule.blocks")
    slots_per_block = validate_positive_int(
        schedule_doc["slots_per_block"], "schedule.slots_per_block"
    )
    schedule_seed = validate_uint64(schedule_doc["seed"], "schedule.seed")

    total_slots = sum(item.slots_per_block for item in multiplicity)
    if total_slots != slots_per_block:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "arm_multiplicity slots must sum to schedule.slots_per_block",
            field_path="schedule.slots_per_block",
        )

    explicit_orders: tuple[tuple[str, ...], ...] | None = None
    if mode == "explicit":
        raw_orders = schedule_doc.get("explicit_orders")
        if not isinstance(raw_orders, list):
            raise BenchError(
                BM_IDENTITY_INVALID,
                "explicit schedule mode requires explicit_orders",
                field_path="schedule.explicit_orders",
            )
        if len(raw_orders) != blocks:
            raise BenchError(
                BM_IDENTITY_INVALID,
                "explicit_orders must declare exactly schedule.blocks blocks",
                field_path="schedule.explicit_orders",
            )
        expected = {item.arm_id: item.slots_per_block for item in multiplicity}
        orders: list[tuple[str, ...]] = []
        for index, raw_block in enumerate(raw_orders):
            if not isinstance(raw_block, list):
                raise BenchError(
                    BM_IDENTITY_INVALID,
                    "each explicit block must be an array of arm IDs",
                    field_path=f"schedule.explicit_orders[{index}]",
                )
            block = tuple(
                validate_semantic_id(
                    arm_id, f"schedule.explicit_orders[{index}][]"
                )
                for arm_id in raw_block
            )
            if len(block) != slots_per_block:
                raise BenchError(
                    BM_IDENTITY_INVALID,
                    "each explicit block must contain schedule.slots_per_block slots",
                    field_path=f"schedule.explicit_orders[{index}]",
                )
            counts = Counter(block)
            if set(counts) - set(expected):
                raise BenchError(
                    BM_IDENTITY_INVALID,
                    "explicit block references an unknown arm",
                    field_path=f"schedule.explicit_orders[{index}]",
                )
            for arm_id, required in expected.items():
                if counts.get(arm_id, 0) != required:
                    raise BenchError(
                        BM_IDENTITY_INVALID,
                        "explicit block arm counts must match arm_multiplicity",
                        field_path=f"schedule.explicit_orders[{index}]",
                    )
            orders.append(block)
        explicit_orders = tuple(orders)
    else:  # seeded-balanced
        if "explicit_orders" in schedule_doc:
            raise BenchError(
                BM_IDENTITY_INVALID,
                "seeded-balanced schedule mode forbids explicit_orders",
                field_path="schedule.explicit_orders",
            )

    measurement = _mapping(doc["measurement"], "measurement")
    warmups = validate_nonnegative_int(
        measurement["warmups_per_lane_slot"], "measurement.warmups_per_lane_slot"
    )
    samples = validate_positive_int(
        measurement["samples_per_lane_slot"], "measurement.samples_per_lane_slot"
    )
    metric_unit = measurement["metric_unit"]
    if metric_unit not in METRIC_UNITS:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"unsupported metric unit: {metric_unit!r}",
            field_path="measurement.metric_unit",
        )
    validate_semantic_id(measurement["clock_contract_id"], "measurement.clock_contract_id")

    campaigns = _mapping(doc["campaigns"], "campaigns")
    validate_nonnegative_int(
        campaigns["required_controls"], "campaigns.required_controls"
    )
    validate_positive_int(
        campaigns["required_treatments"], "campaigns.required_treatments"
    )
    validate_semantic_id(
        campaigns["control_contract_id"], "campaigns.control_contract_id"
    )

    host = _mapping(doc["host"], "host")
    validate_semantic_id(host["capability_policy_id"], "host.capability_policy_id")
    validate_semantic_id(host["readiness_policy_id"], "host.readiness_policy_id")

    correctness = _mapping(doc["correctness"], "correctness")
    oracle_id = validate_semantic_id(correctness["oracle_id"], "correctness.oracle_id")
    oracle_version = validate_positive_int(
        correctness["oracle_version"], "correctness.oracle_version"
    )

    exclusion = _mapping(doc["exclusion"], "exclusion")
    validate_semantic_id(exclusion["ruleset_id"], "exclusion.ruleset_id")
    minimum_retained_blocks = validate_positive_int(
        exclusion["minimum_retained_blocks"], "exclusion.minimum_retained_blocks"
    )
    if minimum_retained_blocks > blocks:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "exclusion.minimum_retained_blocks must not exceed schedule.blocks",
            field_path="exclusion.minimum_retained_blocks",
        )

    statistics = _mapping(doc["statistics"], "statistics")
    validate_semantic_id(statistics["method_id"], "statistics.method_id")
    validate_positive_int(statistics["resamples"], "statistics.resamples")
    statistics_seed = validate_uint64(statistics["seed"], "statistics.seed")
    if statistics["comparison_unit"] != "paired-block":
        raise BenchError(
            BM_SCHEMA_INVALID,
            "statistics.comparison_unit must be 'paired-block'",
            field_path="statistics.comparison_unit",
        )
    validate_semantic_id(statistics["interval_id"], "statistics.interval_id")

    recovery = _mapping(doc["recovery"], "recovery")
    measurement_retries = validate_nonnegative_int(
        recovery["measurement_retries"], "recovery.measurement_retries"
    )
    if recovery["ambiguous_outcome"] != "hard-stop":
        raise BenchError(
            BM_SCHEMA_INVALID,
            "recovery.ambiguous_outcome must be 'hard-stop'",
            field_path="recovery.ambiguous_outcome",
        )

    policy = _validate_policy_binding(doc["policy"], "policy")

    freeze = _mapping(doc["freeze"], "freeze")
    for key, value in freeze.items():
        if value is not True:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"freeze.{key} must be true",
                field_path=f"freeze.{key}",
            )

    return Protocol(
        protocol_id=protocol_id,
        protocol_version=protocol_version,
        experiment_id=experiment_id,
        workload_digest=workload_digest,
        arm_multiplicity=tuple(multiplicity),
        schedule=Schedule(
            schedule_id=schedule_id,
            mode=mode,
            blocks=blocks,
            slots_per_block=slots_per_block,
            seed=schedule_seed,
            explicit_orders=explicit_orders,
        ),
        policy=policy,
        oracle_id=oracle_id,
        oracle_version=oracle_version,
        metric_unit=metric_unit,
        warmups_per_lane_slot=warmups,
        samples_per_lane_slot=samples,
        minimum_retained_blocks=minimum_retained_blocks,
        measurement_retries=measurement_retries,
        statistics_seed=statistics_seed,
        provenance=Provenance.from_doc(doc.get("provenance")),
    )


def validate_adapter(document: object) -> Adapter:
    doc = _dispatch("adapter", document)
    adapter_id = validate_semantic_id(doc["adapter_id"], "adapter_id")
    adapter_version = validate_positive_int(doc["adapter_version"], "adapter_version")
    engine_id = validate_semantic_id(doc["engine_id"], "engine_id")

    operations = tuple(doc["operations"])
    _exact_keys_unique(list(operations), "operations")
    for index, operation in enumerate(operations):
        if operation not in OPERATIONS:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"unsupported adapter operation: {operation!r}",
                field_path=f"operations[{index}]",
            )
    cache_regimes = tuple(doc["cache_regimes"])
    _exact_keys_unique(list(cache_regimes), "cache_regimes")
    for index, regime in enumerate(cache_regimes):
        if regime not in CACHE_REGIMES:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"unsupported adapter cache regime: {regime!r}",
                field_path=f"cache_regimes[{index}]",
            )

    oracle_semantics_id = validate_semantic_id(
        doc["oracle_semantics_id"], "oracle_semantics_id"
    )
    build_doc = _mapping(doc["build_identity"], "build_identity")
    build_kind = build_doc["kind"]
    if build_kind == "synthetic":
        build_identity = BuildIdentity(kind="synthetic")
    elif build_kind == "source-and-binary":
        build_identity = BuildIdentity(
            kind="source-and-binary",
            source_digest=validate_digest(
                build_doc["source_digest"], "build_identity.source_digest"
            ),
            executable_digest=validate_digest(
                build_doc["executable_digest"], "build_identity.executable_digest"
            ),
        )
    else:  # pragma: no cover - schema oneOf guards this
        raise BenchError(
            BM_SCHEMA_INVALID,
            "unsupported build_identity.kind",
            field_path="build_identity.kind",
        )

    envelope = _mapping(doc["measurement_envelope"], "measurement_envelope")
    if envelope["unit"] not in METRIC_UNITS:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"unsupported measurement unit: {envelope['unit']!r}",
            field_path="measurement_envelope.unit",
        )
    if envelope["direction"] not in ("lower-is-better", "higher-is-better"):
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"unsupported measurement direction: {envelope['direction']!r}",
            field_path="measurement_envelope.direction",
        )

    timeouts = _mapping(doc["timeouts"], "timeouts")
    for key in ("setup_ms", "operation_ms", "cleanup_ms"):
        validate_positive_int(timeouts[key], f"timeouts.{key}")

    return Adapter(
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        engine_id=engine_id,
        operations=operations,
        cache_regimes=cache_regimes,
        oracle_semantics_id=oracle_semantics_id,
        build_identity=build_identity,
        measurement_envelope=MeasurementEnvelope(
            unit=envelope["unit"], direction=envelope["direction"]
        ),
        timeouts=dict(timeouts),
        provenance=Provenance.from_doc(doc.get("provenance")),
    )


def validate_receipt(document: object) -> Receipt:
    doc = _dispatch("receipt", document)
    receipt_id = validate_digest(doc["receipt_id"], "receipt_id")
    origin, scope = validate_origin_scope(
        doc["evidence_origin"], doc["qualification_scope"]
    )
    gate = doc["gate"]
    if gate not in GATES:
        raise BenchError(BM_SCHEMA_INVALID, f"unknown gate: {gate!r}", field_path="gate")
    status = doc["status"]
    if status not in RECEIPT_STATUSES:
        raise BenchError(
            BM_SCHEMA_INVALID, f"unknown receipt status: {status!r}", field_path="status"
        )

    subject_doc = _mapping(doc["subject"], "subject")
    subject = ReceiptSubject(
        experiment_id=validate_semantic_id(
            subject_doc["experiment_id"], "subject.experiment_id"
        ),
        run_id=validate_uuid4(subject_doc["run_id"], "subject.run_id"),
        protocol_digest=validate_digest(
            subject_doc["protocol_digest"], "subject.protocol_digest"
        ),
        workload_digest=validate_digest(
            subject_doc["workload_digest"], "subject.workload_digest"
        ),
    )

    validator_doc = _mapping(doc["validator"], "validator")
    validator_identity = ValidatorIdentity(
        validator_id=validate_semantic_id(
            validator_doc["validator_id"], "validator.validator_id"
        ),
        validator_version=validate_positive_int(
            validator_doc["validator_version"], "validator.validator_version"
        ),
        source_digest=validate_digest(
            validator_doc["source_digest"], "validator.source_digest"
        ),
    )

    inputs = _receipt_entries(doc["inputs"], "inputs", require_gate=False)
    outputs = _receipt_entries(doc["outputs"], "outputs", require_gate=False)
    dependencies = _receipt_entries(doc["dependencies"], "dependencies", require_gate=True)

    if doc.get("qa_roster_digest") is not None:
        validate_digest(doc["qa_roster_digest"], "qa_roster_digest")
    if doc.get("policy_digest") is not None:
        validate_digest(doc["policy_digest"], "policy_digest")

    payload = {key: value for key, value in doc.items() if key != "receipt_id"}
    if content_digest(payload) != receipt_id:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "receipt_id does not match the canonical receipt payload",
            field_path="receipt_id",
        )

    return Receipt(
        receipt_id=receipt_id,
        gate=gate,
        status=status,
        evidence_origin=origin,
        qualification_scope=scope,
        subject=subject,
        validator=validator_identity,
        inputs=inputs,
        dependencies=dependencies,
        outputs=outputs,
        qa_roster_digest=doc.get("qa_roster_digest"),
        policy_digest=doc.get("policy_digest"),
        provenance=Provenance.from_doc(doc.get("provenance")),
    )


def _receipt_entries(
    raw_entries: object, field_name: str, *, require_gate: bool
) -> tuple[Any, ...]:
    if not isinstance(raw_entries, list):
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"{field_name} must be an array",
            field_path=field_name,
        )
    _sorted_unique_entries(raw_entries, field_name)
    entries: list[Any] = []
    for index, raw_entry in enumerate(raw_entries):
        entry = _mapping(raw_entry, f"{field_name}[{index}]")
        name = validate_semantic_id(entry["name"], f"{field_name}[{index}].name")
        digest = validate_digest(entry["digest"], f"{field_name}[{index}].digest")
        if require_gate:
            gate = entry["gate"]
            if gate not in GATES:
                raise BenchError(
                    BM_SCHEMA_INVALID,
                    f"unknown dependency gate: {gate!r}",
                    field_path=f"{field_name}[{index}].gate",
                )
            entries.append(
                DependencyEntry(
                    name=name,
                    digest=digest,
                    gate=gate,
                    receipt_id=validate_digest(
                        entry["receipt_id"], f"{field_name}[{index}].receipt_id"
                    ),
                )
            )
        else:
            entries.append(EvidenceEntry(name=name, digest=digest))
    return tuple(entries)


def _validate_operation_outcome(data: Mapping[str, Any]) -> None:
    """Keep configured operation summaries bounded to the stage they completed.

    This validates output coherence only. A CLI summary is never an approval,
    admission capability, QA receipt or substitute for reopening real evidence.
    """

    kind = data["kind"]
    if kind == "official-operation-result":
        version = data["schema_version"]
        if type(version) is not int or version not in (1, 2):
            raise BenchError(BM_SCHEMA_INVALID, "unsupported official result version", field_path="data.schema_version")
        stage = data["stage"]
        statuses = {
            "run": "REAL_EVIDENCE_SEALED",
            "validate": "ADMITTED_REAL",
            "analyze": "ANALYZED_REAL",
            "verify": "VERIFIED_REAL",
            "accept": "REAL_OFFICIAL_QUALIFIED",
            "report": "REAL_OFFICIAL_QUALIFIED",
        }
        if version == 2:
            statuses.update(verify="VERIFIED_CURRENT_BASELINE", accept="CURRENT_BASELINE_QUALIFIED", report="CURRENT_BASELINE_QUALIFIED")
        required_fields = {
            "run": {"raw_series_root_digest"},
            "validate": {"admission_digest"},
            "analyze": {"analysis_digest", "policy_digest", "decision_status"},
            "verify": {"analysis_digest", "policy_digest", "decision_status", "verification_status"},
            "accept": {"manifest_digest", "policy_digest", "decision_status", "verification_status"},
            "report": {"manifest_digest", "policy_digest", "decision_status", "verification_status"},
        }
        observation_fields = {
            "raw_series_root_digest", "admission_digest", "analysis_digest",
            "policy_digest", "decision_status", "verification_status", "manifest_digest",
        }
        present = {field for field in observation_fields if data[field] is not None}
        qualified = stage in ("accept", "report")
        if (
            data["status"] != statuses[stage]
            or present != required_fields[stage]
            or data["accepted"] is not qualified
            or data["attestation_reopened"] is not qualified
        ):
            raise BenchError(
                BM_IDENTITY_INVALID,
                "official result does not match its completed stage",
                field_path="data.stage",
            )
        validate_uuid4(data["run_id"], "data.run_id")
        validate_semantic_id(data["study_id"], "data.study_id")
        if version == 2:
            validate_uuid4(data["baseline_id"], "data.baseline_id")
            evaluated = stage in ("verify", "accept", "report")
            policy_status = data["policy_verification_status"]
            if (evaluated and policy_status not in ("PASS", "NOT_EVALUATED")) or (not evaluated and policy_status is not None):
                raise BenchError(BM_IDENTITY_INVALID, "policy verification status does not match the completed stage", field_path="data.policy_verification_status")
            if data["study_id"] == "cross-engine-keyword-real-v1" and policy_status == "NOT_EVALUATED":
                raise BenchError(BM_IDENTITY_INVALID, "cross-engine policy is not exempted", field_path="data.policy_verification_status")
            if (not qualified and (data["complete_baseline_preserved"] or data["clean_checkout_replay_verified"])) or (
                data["clean_checkout_replay_verified"] and not data["complete_baseline_preserved"]
            ):
                raise BenchError(BM_IDENTITY_INVALID, "preservation/replay flags do not match the completed stage", field_path="data.complete_baseline_preserved")
        return
    if kind == "official-authorization-inputs":
        version = data["schema_version"]
        if type(version) is not int or version not in (1, 2):
            raise BenchError(BM_SCHEMA_INVALID, "unsupported official preparation version", field_path="data.schema_version")
        output = data["observations"]["output_root_identity"]
        if "\x00" in output or ".." in Path(output).parts:
            raise BenchError(BM_UNSAFE_INPUT, "unsafe observed output root", field_path="data.observations.output_root_identity")
        validate_semantic_id(data["study_id"], "data.study_id")
        if version == 2:
            from ..official.protocols import validate_root_identity

            observed = data["observations"]
            validate_uuid4(observed["baseline_id"], "data.observations.baseline_id")
            for field in ("output_root_identity", "preservation_root_identity"):
                validate_root_identity(observed[field], "data.observations." + field)
        return
    if kind == "official-experiment-inspection":
        validate_semantic_id(data["experiment_id"], "data.experiment_id")
        return
    if kind == "synthetic-operation-result":
        output = data["output_directory"]
        if "\x00" in output or ".." in Path(output).parts:
            raise BenchError(BM_UNSAFE_INPUT, "unsafe operation output directory", field_path="data.output_directory")
    elif kind == "synthetic-operation-stage":
        expected_members = {
            "validate": {"admission.json"},
            "analyze": {"analysis.json", "policy.json", "analysis-receipt.json"},
            "verify": {"verification.json", "verification-assessment.json"},
            "accept": {"acceptance.json", "acceptance-summary.json"},
            "report": {"policy.json", "attestation.json"},
        }
        documents = data["documents"]
        if set(documents) != expected_members[data["stage"]]:
            raise BenchError(BM_SCHEMA_INVALID, "synthetic stage members do not match the stage", field_path="data.documents")
        for document in documents.values():
            if validate_origin_scope(document.get("evidence_origin"), document.get("qualification_scope")) != ("synthetic", "simulated"):
                raise BenchError(BM_SCOPE_MISMATCH, "synthetic stage contains non-synthetic evidence", field_path="data.documents")
    else:
        raise BenchError(BM_SCHEMA_INVALID, "unknown successful outcome payload", field_path="data.kind")
    validate_uuid4(data["run_id"], "data.run_id")
    validate_semantic_id(data["experiment_id"], "data.experiment_id")


def validate_outcome(document: object) -> Mapping[str, Any]:
    candidate = _mapping(document, "outcome")
    if type(candidate.get("schema_version")) is int and candidate["schema_version"] == 2:
        validate_operator_outcome(candidate)
        doc = candidate
    else:
        # The frozen registry still owns v1 and unsupported-version rejection.
        doc = _dispatch("outcome", candidate)
    status = doc["status"]
    code = doc["code"]
    data = _mapping(doc["data"], "data")
    message = doc["message"]
    if not isinstance(message, str) or not message:
        raise BenchError(
            BM_SCHEMA_INVALID, "message must be non-empty", field_path="message"
        )
    if len(message.encode("utf-8")) > 1024:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "message exceeds the 1024-byte limit",
            field_path="message",
        )
    if bounded_message(message) != message:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "message exceeds the 1024-byte limit",
            field_path="message",
        )

    if status == "ok":
        if code != "BM_OK":
            raise BenchError(
                BM_IDENTITY_INVALID,
                "a successful outcome must use BM_OK",
                field_path="code",
            )
        if data.get("kind") == "error-detail":
            raise BenchError(
                BM_SCHEMA_INVALID,
                "a successful outcome cannot carry an error-detail",
                field_path="data.kind",
            )
        origin, scope = validate_origin_scope(
            data.get("evidence_origin"), data.get("qualification_scope")
        )
        if data.get("kind") != "inspect-summary":
            _validate_operation_outcome(data)
            return doc
        validate_semantic_id(data.get("experiment_id"), "data.experiment_id")
        profiles.validate_profile(data.get("profile"))
        validate_semantic_id(data.get("workload_id"), "data.workload_id")
        validate_semantic_id(data.get("protocol_id"), "data.protocol_id")
        validate_digest(data.get("protocol_digest"), "data.protocol_digest")
        for index, arm_id in enumerate(data.get("arm_ids") or []):
            validate_semantic_id(arm_id, f"data.arm_ids[{index}]")
        for index, lane_id in enumerate(data.get("lane_ids") or []):
            validate_semantic_id(lane_id, f"data.lane_ids[{index}]")
        if (origin, scope) != (data["evidence_origin"], data["qualification_scope"]):
            raise BenchError(
                BM_SCOPE_MISMATCH, "origin/scope mismatch", field_path="data"
            )
        return doc

    if code == "BM_OK":
        raise BenchError(
            BM_IDENTITY_INVALID,
            "a non-success outcome must not use BM_OK",
            field_path="code",
        )
    if data.get("kind") != "error-detail":
        raise BenchError(
            BM_SCHEMA_INVALID,
            "an error or blocked outcome must carry an error-detail",
            field_path="data.kind",
        )
    expected_status = "blocked" if code in BLOCKED_CODES else "error"
    if status != expected_status:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"{code} must use status {expected_status!r}",
            field_path="status",
        )
    if error_spec(code)[0] != data.get("reason"):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "error-detail.reason must match the code category",
            field_path="data.reason",
        )
    if "field_path" in data:
        field_path = data["field_path"]
        if not isinstance(field_path, str) or len(field_path) > 512:
            raise BenchError(
                BM_UNSAFE_INPUT,
                "error-detail.field_path is not a bounded logical path",
                field_path="data.field_path",
            )
    if "reference" in data:
        _safe_reference(data["reference"], "data.reference")
    return doc


# ---------------------------------------------------------------------------
# Cross-document binding
# ---------------------------------------------------------------------------


def validate_bundle(
    experiment: Experiment,
    workload: Workload,
    protocol: Protocol,
    adapter: Adapter,
    workload_document: Mapping[str, Any],
) -> None:
    """Validate every cross-document reference and identity binding."""

    if protocol.experiment_id != experiment.experiment_id:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "protocol.experiment_id must match the experiment",
            field_path="protocol.experiment_id",
        )

    if protocol.workload_digest != content_digest(workload_document):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "protocol.workload_digest must equal the canonical workload payload digest",
            field_path="protocol.workload_digest",
        )

    arm_ids = {arm.arm_id for arm in experiment.arms}
    for arm in experiment.arms:
        if arm.adapter_id != adapter.adapter_id:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"arm {arm.arm_id!r} references an undeclared adapter",
                field_path="arms[].adapter_id",
            )
    multiplicity_ids = {item.arm_id for item in protocol.arm_multiplicity}
    if multiplicity_ids != arm_ids:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "protocol arm_multiplicity must cover exactly the experiment arms",
            field_path="protocol.arm_multiplicity",
        )

    if (
        protocol.oracle_id != workload.oracle_id
        or protocol.oracle_version != workload.oracle_version
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "protocol correctness oracle must match the workload oracle",
            field_path="protocol.correctness",
        )

    if (
        protocol.policy.policy_id != experiment.policy.policy_id
        or protocol.policy.policy_version != experiment.policy.policy_version
        or protocol.policy.policy_digest != experiment.policy.policy_digest
    ):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "protocol policy binding must match the experiment policy binding",
            field_path="protocol.policy",
        )

    if protocol.metric_unit != adapter.measurement_envelope.unit:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "protocol metric unit must match the adapter measurement envelope",
            field_path="protocol.measurement.metric_unit",
        )

    if adapter.oracle_semantics_id != workload.query_semantics_id:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "adapter oracle semantics must match the workload query semantics",
            field_path="adapter.oracle_semantics_id",
        )

    for lane in workload.lanes:
        if lane.operation not in adapter.operations:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"adapter does not declare lane operation {lane.operation!r}",
                field_path="adapter.operations",
            )
        if lane.cache_regime not in adapter.cache_regimes:
            raise BenchError(
                BM_IDENTITY_INVALID,
                f"adapter does not declare cache regime {lane.cache_regime!r}",
                field_path="adapter.cache_regimes",
            )


def derive_origin_scope(bundle: ExperimentBundle) -> tuple[str, str]:
    """Derive the evidence origin/scope from the declared adapter build identity.

    BM-01 only inspects synthetic declarations. A real source-and-binary adapter
    cannot be classified here because its scope is established by a later
    milestone's frozen official protocol.
    """

    if bundle.adapter.build_identity.kind == "synthetic":
        return ("synthetic", "simulated")
    raise BenchError(
        BM_SCOPE_MISMATCH,
        "BM-01 inspect supports synthetic declarations only; "
        "real-origin evidence scope is established by a later milestone",
        field_path="adapter.build_identity.kind",
    )


def build_inspect_summary(bundle: ExperimentBundle) -> Mapping[str, Any]:
    """Build the typed ``inspect-summary`` payload from validated records."""

    origin, scope = derive_origin_scope(bundle)
    return {
        "kind": "inspect-summary",
        "experiment_id": bundle.experiment.experiment_id,
        "profile": bundle.experiment.profile,
        "workload_id": bundle.workload.workload_id,
        "protocol_id": bundle.protocol.protocol_id,
        "protocol_digest": bundle.protocol_digest,
        "arm_ids": [arm.arm_id for arm in bundle.experiment.arms],
        "lane_ids": [lane.lane_id for lane in bundle.workload.lanes],
        "evidence_origin": origin,
        "qualification_scope": scope,
    }


def build_outcome(status: str, code: str, message: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Use v2 only for the closed operator payload set; preserve ordinary v1."""

    outcome = {
        "kind": "outcome",
        "schema_version": 2 if isinstance(data.get("kind"), str) and data["kind"] in OPERATOR_PAYLOAD_KINDS else 1,
        "status": status,
        "code": code,
        "message": message,
        "data": dict(data),
    }
    validate_outcome(outcome)
    return outcome


# ---------------------------------------------------------------------------
# Bundle loading with path confinement
# ---------------------------------------------------------------------------


def _contained_file(
    directory: Path, name: object, field_name: str
) -> Path:
    if not isinstance(name, str) or not name:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field_name} must be a non-empty adjacent filename",
            field_path=field_name,
        )
    if "/" in name or "\\" in name or name in {".", ".."} or name.startswith("."):
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field_name} must be a plain adjacent filename",
            field_path=field_name,
        )
    path = directory / name
    if path.is_symlink():
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field_name} must not be a symlink",
            field_path=field_name,
            reference=name,
        )
    if path.parent.resolve() != directory.resolve():  # pragma: no cover - defensive
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{field_name} escapes the experiment root",
            field_path=field_name,
        )
    if not path.is_file():
        raise BenchError(
            BM_FILE_MISSING,
            f"{field_name} refers to a missing file",
            field_path=field_name,
            reference=name,
        )
    return path


def load_experiment_bundle(
    experiment_id: object, experiments_root: Path
) -> ExperimentBundle:
    """Load and fully validate one declared experiment and its adjacent files.

    Only ``benchmarks/experiments/<experiment_id>/`` and the three referenced
    adjacent files are ever opened. Symbolic links, traversal, absolute paths,
    globs and environment expansion are rejected.
    """

    identifier = validate_semantic_id(experiment_id, "experiment_id")
    root = Path(experiments_root)
    if not root.is_dir():
        raise BenchError(BM_FILE_MISSING, "experiments directory is missing")

    experiment_dir = root / identifier
    if experiment_dir.is_symlink():
        raise BenchError(
            BM_UNSAFE_INPUT,
            "experiment directory must not be a symlink",
            field_path="experiment_id",
        )
    if not experiment_dir.is_dir():
        raise BenchError(
            BM_FILE_MISSING,
            f"no experiment named {identifier!r} is declared",
            field_path="experiment_id",
            reference=f"{identifier}/experiment.yaml",
        )
    if experiment_dir.resolve().parent != root.resolve():
        raise BenchError(
            BM_UNSAFE_INPUT,
            "experiment directory escapes the catalog root",
            field_path="experiment_id",
        )

    experiment_path = _contained_file(experiment_dir, "experiment.yaml", "experiment.yaml")
    experiment_document = load_document(experiment_path)
    experiment = validate_experiment(experiment_document)
    if experiment.experiment_id != identifier:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "declared experiment_id must match its directory name",
            field_path="experiment_id",
        )

    resolved: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for field_name in ("workloads_file", "protocol_file", "adapter_file"):
        name = experiment_document[field_name]
        if name not in ALLOWED_EXPERIMENT_FILES:
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"{field_name} must be one of {sorted(ALLOWED_EXPERIMENT_FILES)}",
                field_path=field_name,
            )
        path = _contained_file(experiment_dir, name, field_name)
        resolved[field_name] = (path, load_document(path))

    workload_document = resolved["workloads_file"][1]
    protocol_document = resolved["protocol_file"][1]
    adapter_document = resolved["adapter_file"][1]

    workload = validate_workload(workload_document)
    protocol = validate_protocol(protocol_document)
    adapter = validate_adapter(adapter_document)
    validate_bundle(experiment, workload, protocol, adapter, workload_document)

    return ExperimentBundle(
        experiment=experiment,
        workload=workload,
        protocol=protocol,
        adapter=adapter,
        experiment_document=experiment_document,
        workload_document=workload_document,
        protocol_document=protocol_document,
        adapter_document=adapter_document,
    )


# ---------------------------------------------------------------------------
# Future adapter interface (declared, never instantiated or measured in BM-01)
# ---------------------------------------------------------------------------


ADAPTER_STATUSES: tuple[str, ...] = ("prepared", "pass", "fail", "error", "skipped")


@dataclass(frozen=True)
class AdapterContext:
    """Immutable context handed to a future adapter implementation."""

    experiment_id: str
    run_id: str
    lane_ids: tuple[str, ...]
    evidence_origin: str
    qualification_scope: str


@dataclass(frozen=True)
class PreparedFixture:
    fixture_id: str
    digest: str
    status: str
    evidence_origin: str
    qualification_scope: str


@dataclass(frozen=True)
class OracleResult:
    oracle_id: str
    oracle_version: int
    status: str
    evidence_origin: str
    qualification_scope: str


@dataclass(frozen=True)
class WarmupResult:
    lane_id: str
    status: str
    evidence_origin: str
    qualification_scope: str


@dataclass(frozen=True)
class MeasurementResult:
    lane_id: str
    unit: str
    direction: str
    status: str
    samples: tuple[int, ...] | None
    evidence_origin: str
    qualification_scope: str


@runtime_checkable
class BenchmarkAdapter(TypingProtocol):
    """Typed seam for BM-03/BM-07/BM-08 adapter implementations.

    No method here is implemented in BM-01 and none may consult a clock.
    """

    def prepare(self, context: AdapterContext) -> PreparedFixture: ...

    def check_oracle(
        self, context: AdapterContext, prepared: PreparedFixture
    ) -> OracleResult: ...

    def warmup(
        self, context: AdapterContext, prepared: PreparedFixture, lane: Lane
    ) -> WarmupResult: ...

    def measure(
        self, context: AdapterContext, prepared: PreparedFixture, lane: Lane
    ) -> MeasurementResult: ...

    def cleanup(
        self, context: AdapterContext, prepared: PreparedFixture
    ) -> None: ...

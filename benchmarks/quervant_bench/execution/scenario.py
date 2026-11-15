"""Closed synthetic scenario fixture: the only source of simulated samples.

A scenario is an *internal simulator fixture*. It is not a BM-01 schema, not an
official protocol and not a performance result. It supplies the positive integer
nanosecond values the synthetic adapter replays and the simulated readiness
observations the controller consumes once per campaign.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import canonical_document_bytes, content_digest, decode_text, loads_json
from ..config.contracts import ExperimentBundle, validate_origin_scope
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_NOT_IMPLEMENTED,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_semantic_id
from ..evidence.paths import open_regular_beneath
from ..host.readiness import (
    ReadinessLimits,
    ReadinessObservation,
    evaluate_readiness,
)
from ..protocol.controls import read_protocol_campaigns
from .contracts import (
    CAMPAIGN_KINDS,
    MAX_LANES,
    MAX_SAMPLES_PER_LANE_SLOT,
    MAX_SCENARIO_BYTES,
    MAX_WARMUPS_PER_LANE_SLOT,
    SCENARIO_RELATIVE_NAME,
    SCENARIO_SCHEMA_VERSION,
    SIMULATED_SCOPE,
    SYNTHETIC_METRIC_UNIT,
    SYNTHETIC_ORIGIN,
    require_bounded_nanoseconds,
    require_positive_int,
)

SCENARIO_KIND = "synthetic-scenario"

#: Frozen readiness thresholds for this synthetic scenario only.
SYNTHETIC_READINESS_LIMITS = ReadinessLimits(
    min_interval_ms=10,
    max_interval_ms=20,
    max_busy_permille=200,
    max_median_busy_permille=150,
    max_steal_permille=20,
    min_intervals=2,
)

_SCENARIO_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "schema_version",
        "scenario_id",
        "experiment_id",
        "evidence_origin",
        "qualification_scope",
        "control_source_arm_id",
        "metric_unit",
        "clock_contract_id",
        "samples",
        "readiness",
    }
)
_SAMPLE_KEYS: frozenset[str] = frozenset({"arm_id", "lane_id", "values"})
_READINESS_KEYS: frozenset[str] = frozenset(
    {"campaign_kind", "campaign_index", "observations"}
)
_OBSERVATION_KEYS: frozenset[str] = frozenset(
    {"elapsed_ms", "busy_permille", "steal_permille"}
)


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class ScenarioSample:
    """One declared arm/lane sample vector of simulated nanoseconds."""

    arm_id: str
    lane_id: str
    values: tuple[int, ...]


@dataclass(frozen=True)
class ScenarioReadiness:
    """One declared campaign readiness batch of simulated observations."""

    campaign_kind: str
    campaign_index: int
    observations: tuple[ReadinessObservation, ...]


@dataclass(frozen=True)
class SyntheticScenario:
    """Immutable, digest-bound synthetic scenario."""

    scenario_id: str
    experiment_id: str
    evidence_origin: str
    qualification_scope: str
    control_source_arm_id: str
    metric_unit: str
    clock_contract_id: str
    samples: tuple[ScenarioSample, ...]
    readiness: tuple[ScenarioReadiness, ...]
    scenario_digest: str
    document: Mapping[str, Any]

    def values_for(self, arm_id: str, lane_id: str) -> tuple[int, ...]:
        """Return the declared sample vector for one arm/lane pair."""

        for sample in self.samples:
            if sample.arm_id == arm_id and sample.lane_id == lane_id:
                return sample.values
        raise _fail(
            f"no synthetic sample is declared for {arm_id}/{lane_id}",
            "scenario.samples",
        )

    def readiness_for(self, campaign_kind: str, campaign_index: int) -> tuple[ReadinessObservation, ...]:
        """Return the single declared readiness batch for one campaign."""

        for entry in self.readiness:
            if (
                entry.campaign_kind == campaign_kind
                and entry.campaign_index == campaign_index
            ):
                return entry.observations
        raise _fail(
            f"no synthetic readiness is declared for {campaign_kind}-{campaign_index}",
            "scenario.readiness",
        )


def _validate_observation(raw: object, field_path: str) -> ReadinessObservation:
    if not isinstance(raw, Mapping) or set(raw) != _OBSERVATION_KEYS:
        raise _fail(
            "each readiness observation must use the exact closed field set",
            field_path,
        )
    return ReadinessObservation(
        elapsed_ms=raw["elapsed_ms"],
        busy_permille=raw["busy_permille"],
        steal_permille=raw["steal_permille"],
    )


def _scenario_samples(
    raw_samples: object, arms: tuple[str, ...], lanes: tuple[str, ...], samples_per_lane_slot: int
) -> tuple[ScenarioSample, ...]:
    if not isinstance(raw_samples, list):
        raise _fail("scenario.samples must be an array", "scenario.samples")
    expected = len(arms) * len(lanes)
    if len(raw_samples) != expected:
        raise _fail(
            f"scenario.samples must declare exactly arms x lanes = {expected} records",
            "scenario.samples",
        )
    samples: list[ScenarioSample] = []
    keys: list[tuple[str, str]] = []
    for index, raw in enumerate(raw_samples):
        field_path = f"scenario.samples[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _SAMPLE_KEYS:
            raise _fail(
                "each sample record must use the exact closed field set", field_path
            )
        arm_id = raw["arm_id"]
        lane_id = raw["lane_id"]
        if arm_id not in arms or lane_id not in lanes:
            raise _fail("sample record references an undeclared arm or lane", field_path)
        if (arm_id, lane_id) in keys:
            raise _fail("scenario.samples must be unique per arm and lane", field_path)
        keys.append((arm_id, lane_id))
        raw_values = raw["values"]
        if not isinstance(raw_values, list):
            raise _fail("sample values must be an array", f"{field_path}.values")
        if len(raw_values) != samples_per_lane_slot:
            raise _fail(
                "sample vectors must contain exactly samples_per_lane_slot values",
                f"{field_path}.values",
            )
        values = tuple(
            require_bounded_nanoseconds(value, f"{field_path}.values[{position}]")
            for position, value in enumerate(raw_values)
        )
        samples.append(ScenarioSample(arm_id=arm_id, lane_id=lane_id, values=values))
    if keys != sorted(keys):
        raise _fail(
            "scenario.samples must be stored in sorted (arm_id, lane_id) order",
            "scenario.samples",
        )
    return tuple(samples)


def _scenario_readiness(
    raw_readiness: object, required_controls: int, required_treatments: int
) -> tuple[ScenarioReadiness, ...]:
    if not isinstance(raw_readiness, list):
        raise _fail("scenario.readiness must be an array", "scenario.readiness")
    expected: list[tuple[str, int]] = [
        ("control", index) for index in range(required_controls)
    ] + [("treatment", index) for index in range(required_treatments)]
    if len(raw_readiness) != len(expected):
        raise _fail(
            "scenario.readiness must declare exactly one batch per campaign",
            "scenario.readiness",
        )
    entries: list[ScenarioReadiness] = []
    seen: list[tuple[str, int]] = []
    for index, raw in enumerate(raw_readiness):
        field_path = f"scenario.readiness[{index}]"
        if not isinstance(raw, Mapping) or set(raw) != _READINESS_KEYS:
            raise _fail(
                "each readiness record must use the exact closed field set", field_path
            )
        kind = raw["campaign_kind"]
        if kind not in CAMPAIGN_KINDS:
            raise _fail("campaign_kind must be control or treatment", field_path)
        campaign_index = raw["campaign_index"]
        if isinstance(campaign_index, bool) or not isinstance(campaign_index, int) or campaign_index < 0:
            raise _fail("campaign_index must be a non-negative integer", field_path)
        key = (kind, campaign_index)
        if key in seen:
            raise _fail("scenario.readiness keys must be unique", field_path)
        seen.append(key)
        raw_observations = raw["observations"]
        if not isinstance(raw_observations, list):
            raise _fail("observations must be an array", f"{field_path}.observations")
        if not raw_observations:
            raise _fail(
                "observations must contain at least one simulated interval",
                f"{field_path}.observations",
            )
        observations = tuple(
            _validate_observation(item, f"{field_path}.observations[{position}]")
            for position, item in enumerate(raw_observations)
        )
        entries.append(
            ScenarioReadiness(
                campaign_kind=kind,
                campaign_index=campaign_index,
                observations=observations,
            )
        )
    if seen != sorted(seen):
        raise _fail(
            "scenario.readiness must be stored in sorted (kind, index) order",
            "scenario.readiness",
        )
    if sorted(seen) != sorted(expected):
        raise _fail(
            "scenario.readiness must cover exactly the required campaigns",
            "scenario.readiness",
        )
    return tuple(entries)


def validate_scenario_document(
    document: object, *, bundle: ExperimentBundle
) -> SyntheticScenario:
    """Validate closed scenario bytes against one validated BM-01 bundle."""

    if not isinstance(document, Mapping):
        raise _fail("a synthetic scenario must be an object", "scenario")
    doc = document
    if set(doc) != _SCENARIO_KEYS:
        raise _fail(
            "a synthetic scenario must use the exact closed field set", "scenario"
        )
    if doc["kind"] != SCENARIO_KIND:
        raise _fail("scenario kind is invalid", "scenario.kind")
    if doc["schema_version"] != SCENARIO_SCHEMA_VERSION:
        raise _fail("scenario schema_version is invalid", "scenario.schema_version")
    scenario_id = validate_semantic_id(doc["scenario_id"], "scenario.scenario_id")
    experiment_id = validate_semantic_id(doc["experiment_id"], "scenario.experiment_id")
    if experiment_id != bundle.experiment.experiment_id:
        raise _fail(
            "scenario.experiment_id must match the declared experiment",
            "scenario.experiment_id",
        )
    origin, scope = validate_origin_scope(
        doc["evidence_origin"], doc["qualification_scope"]
    )
    if (origin, scope) != (SYNTHETIC_ORIGIN, SIMULATED_SCOPE):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "a BM-03 scenario must remain synthetic/simulated",
            field_path="scenario.qualification_scope",
        )
    control_source_arm_id = validate_semantic_id(
        doc["control_source_arm_id"], "scenario.control_source_arm_id"
    )
    arms = tuple(sorted(arm.arm_id for arm in bundle.experiment.arms))
    if control_source_arm_id not in arms:
        raise _fail(
            "scenario.control_source_arm_id must be a declared arm",
            "scenario.control_source_arm_id",
        )
    metric_unit = doc["metric_unit"]
    if metric_unit != SYNTHETIC_METRIC_UNIT:
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "BM-03 execution supports only the synthetic nanosecond envelope",
            field_path="scenario.metric_unit",
        )
    clock_contract_id = validate_semantic_id(
        doc["clock_contract_id"], "scenario.clock_contract_id"
    )
    campaigns = read_protocol_campaigns(bundle)
    if clock_contract_id != campaigns.clock_contract_id:
        raise _fail(
            "scenario.clock_contract_id must match the declared protocol clock",
            "scenario.clock_contract_id",
        )
    lanes = tuple(lane.lane_id for lane in bundle.workload.lanes)
    if len(lanes) > MAX_LANES:
        raise _fail(
            f"the workload exceeds the {MAX_LANES}-lane simulator budget",
            "scenario.samples",
        )
    warmups = bundle.protocol.warmups_per_lane_slot
    if warmups > MAX_WARMUPS_PER_LANE_SLOT:
        raise _fail(
            f"warmups_per_lane_slot exceeds the {MAX_WARMUPS_PER_LANE_SLOT} budget",
            "scenario.samples",
        )
    samples_per_lane_slot = bundle.protocol.samples_per_lane_slot
    if samples_per_lane_slot > MAX_SAMPLES_PER_LANE_SLOT:
        raise _fail(
            f"samples_per_lane_slot exceeds the {MAX_SAMPLES_PER_LANE_SLOT} budget",
            "scenario.samples",
        )
    samples = _scenario_samples(doc["samples"], arms, lanes, samples_per_lane_slot)
    readiness = _scenario_readiness(
        doc["readiness"], campaigns.required_controls, campaigns.required_treatments
    )
    for entry in readiness:
        evaluate_readiness(SYNTHETIC_READINESS_LIMITS, entry.observations)
    return SyntheticScenario(
        scenario_id=scenario_id,
        experiment_id=experiment_id,
        evidence_origin=origin,
        qualification_scope=scope,
        control_source_arm_id=control_source_arm_id,
        metric_unit=metric_unit,
        clock_contract_id=clock_contract_id,
        samples=samples,
        readiness=readiness,
        scenario_digest=content_digest(doc),
        document=doc,
    )


def read_scenario_bytes(evidence_root: Path, relative: str) -> bytes:
    """Read one bounded scenario file through the BM-02 no-follow helper."""

    handle = open_regular_beneath(evidence_root, relative)
    with handle:
        payload = handle.read(MAX_SCENARIO_BYTES + 1)
    if len(payload) > MAX_SCENARIO_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"scenario exceeds the {MAX_SCENARIO_BYTES}-byte limit",
            reference=relative,
        )
    return payload


def load_synthetic_scenario(
    evidence_root: Path,
    relative: str = SCENARIO_RELATIVE_NAME,
    *,
    bundle: ExperimentBundle,
) -> SyntheticScenario:
    """Load, strictly parse and fully validate one synthetic scenario."""

    payload = read_scenario_bytes(evidence_root, relative)
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the scenario fixture must be stored in canonical byte form",
            reference=relative,
        )
    if not isinstance(document, Mapping):
        raise BenchError(
            BM_SCHEMA_INVALID, "a scenario document must be an object"
        )
    return validate_scenario_document(document, bundle=bundle)


def reopen_scenario_digest(evidence_root: Path, relative: str = SCENARIO_RELATIVE_NAME) -> str:
    """Re-read the scenario bytes and return their canonical content digest."""

    payload = read_scenario_bytes(evidence_root, relative)
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the scenario fixture must be stored in canonical byte form",
            reference=relative,
        )
    return content_digest(document)


def require_fresh_positive_values(values: tuple[int, ...], field_path: str) -> None:
    """Validate an adapter sample vector without converting any value."""

    if not values:
        raise _fail(f"{field_path} must contain at least one sample", field_path)
    for index, value in enumerate(values):
        require_positive_int(value, f"{field_path}[{index}]")

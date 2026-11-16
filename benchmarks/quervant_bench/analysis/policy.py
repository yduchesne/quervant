"""The closed BM-04 policy profile, synthetic resources and frozen selection.

The policy is a **frozen, independently digest-bound document**. It declares the
exact threshold operators, resource limits, ranking lanes, tie rule and fallback.
Nothing here recomputes an estimate: the policy consumes the canonical 12-place
values from the analysis document and applies exact `Decimal` comparisons.

There is no float epsilon, no approximate equality, no operator substitution, no
implicit tie, no baseline auto-selection for merely-inconclusive evidence and no
field that could be read as a Gate B acceptance, real qualification or deployment
permission.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
)
from ..config.contracts import ExperimentBundle
from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_SCHEMA_UNSUPPORTED,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_positive_int, validate_semantic_id
from ..evidence.paths import open_regular_beneath, require_safe_root
from .arithmetic import (
    geometric_mean,
    relative_delta,
    worst_campaign_gm,
)
from .contracts import (
    CANDIDATE_ELIGIBLE,
    CANDIDATE_INCONCLUSIVE,
    CANDIDATE_INELIGIBLE,
    DECISION_BASELINE_ONLY,
    DECISION_INCONCLUSIVE,
    DECISION_SELECTED,
    DECISION_TIE_PREFERENCE,
    DERIVED_STATUS,
    DIRECTIONS,
    LANE_STATUS_ANALYZED,
    LANE_STATUS_INSUFFICIENT,
    SIMULATED_SCOPE,
    SYNTHETIC_ORIGIN,
    parse_decimal_literal,
    require_closed,
    require_enum,
    require_formatted_effect,
    require_int,
    require_list,
    require_mapping,
    require_synthetic_scope,
    validate_digest,
)

POLICY_PROFILE_KIND = "policy-profile"
POLICY_PROFILE_NAME = "policy-profile.v1.json"
POLICY_PROFILE_SCHEMA_VERSION = 1
RESOURCE_OBSERVATIONS_KIND = "synthetic-resource-observations"
RESOURCE_OBSERVATIONS_NAME = "resource-observations.v1.json"
RESOURCE_OBSERVATIONS_SCHEMA_VERSION = 1
MAX_PROFILE_BYTES = 1_048_576
MAX_RESOURCE_BYTES = 1_048_576
MAX_RESOURCE_VALUE = 2**63 - 1

FILTER_SENSITIVE_ACTION_INCONCLUSIVE = "inconclusive"

#: Closed reason-code vocabulary. Every code is produced by exactly one rule.
REASON_RESOURCE_OVER_LIMIT = "RESOURCE_OVER_LIMIT"
REASON_MISSING_RESOURCE = "MISSING_RESOURCE"
REASON_INSUFFICIENT_RETAINED_BLOCKS = "INSUFFICIENT_RETAINED_BLOCKS"
REASON_TARGET_DECISIVE_FAILURE = "TARGET_DECISIVE_FAILURE"
REASON_TARGET_UNPROVEN = "TARGET_UNPROVEN"
REASON_GUARDRAIL_DECISIVE_FAILURE = "GUARDRAIL_DECISIVE_FAILURE"
REASON_GUARDRAIL_UNPROVEN = "GUARDRAIL_UNPROVEN"
REASON_FILTER_SENSITIVE = "FILTER_SENSITIVE"
REASON_MISSING_RANKING_GM = "MISSING_RANKING_GM"

REASON_CODES: frozenset[str] = frozenset(
    {
        REASON_RESOURCE_OVER_LIMIT,
        REASON_MISSING_RESOURCE,
        REASON_INSUFFICIENT_RETAINED_BLOCKS,
        REASON_TARGET_DECISIVE_FAILURE,
        REASON_TARGET_UNPROVEN,
        REASON_GUARDRAIL_DECISIVE_FAILURE,
        REASON_GUARDRAIL_UNPROVEN,
        REASON_FILTER_SENSITIVE,
        REASON_MISSING_RANKING_GM,
    }
)

_POLICY_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "policy_id",
        "policy_version",
        "evidence_origin",
        "qualification_scope",
        "baseline_arm_id",
        "candidate_order",
        "metric_direction",
        "targets",
        "guardrails",
        "resource_rules",
        "selection",
    }
)
_THRESHOLD_KEYS = frozenset({"lane_id", "point_upper", "ci_upper", "ci_operator"})
_RESOURCE_RULE_KEYS = frozenset({"arm_id", "resource_id", "max_bytes"})
_SELECTION_KEYS = frozenset(
    {
        "ranking_lanes",
        "tie_relative_delta",
        "tie_preference",
        "fallback_arm_id",
        "filter_sensitivity_action",
    }
)
_RESOURCE_DOC_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "experiment_id",
        "evidence_origin",
        "qualification_scope",
        "records",
    }
)
_RESOURCE_RECORD_KEYS = frozenset({"arm_id", "resource_id", "value_bytes"})


def _fail(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _schema(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


# ---------------------------------------------------------------------------
# Policy profile records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThresholdRule:
    """One target or guardrail threshold over one lane."""

    lane_id: str
    point_upper: Decimal
    ci_upper: Decimal
    ci_operator: str


@dataclass(frozen=True)
class ResourceRule:
    """One per-arm exact integer resource limit."""

    arm_id: str
    resource_id: str
    max_bytes: int


@dataclass(frozen=True)
class SelectionContract:
    """The frozen ranking, tie and fallback rule."""

    ranking_lanes: tuple[str, ...]
    tie_relative_delta: Decimal
    tie_preference: tuple[str, ...]
    fallback_arm_id: str
    filter_sensitivity_action: str


@dataclass(frozen=True)
class PolicyProfile:
    """One validated, immutable, digest-bound policy profile."""

    policy_id: str
    policy_version: int
    evidence_origin: str
    qualification_scope: str
    baseline_arm_id: str
    candidate_order: tuple[str, ...]
    metric_direction: str
    targets: tuple[ThresholdRule, ...]
    guardrails: tuple[ThresholdRule, ...]
    resource_rules: tuple[ResourceRule, ...]
    selection: SelectionContract
    digest: str
    document: Mapping[str, Any]

    def target_for(self, lane_id: str) -> ThresholdRule | None:
        for rule in self.targets:
            if rule.lane_id == lane_id:
                return rule
        return None

    def guardrail_for(self, lane_id: str) -> ThresholdRule | None:
        for rule in self.guardrails:
            if rule.lane_id == lane_id:
                return rule
        return None

    def rules_for(self, lane_id: str) -> tuple[tuple[str, ThresholdRule], ...]:
        rules: list[tuple[str, ThresholdRule]] = []
        target = self.target_for(lane_id)
        if target is not None:
            rules.append(("target", target))
        guardrail = self.guardrail_for(lane_id)
        if guardrail is not None:
            rules.append(("guardrail", guardrail))
        return tuple(rules)


def _validate_thresholds(
    value: object, field_path: str, declared_lanes: tuple[str, ...]
) -> tuple[ThresholdRule, ...]:
    raw_rules = require_list(value, field_path)
    rules: list[ThresholdRule] = []
    for index, raw_rule in enumerate(raw_rules):
        field = f"{field_path}[{index}]"
        rule_doc = require_closed(raw_rule, field, _THRESHOLD_KEYS)
        lane_id = validate_semantic_id(rule_doc["lane_id"], f"{field}.lane_id")
        if lane_id not in declared_lanes:
            raise _fail(f"{field}.lane_id must be a declared workload lane", field)
        point_upper = parse_decimal_literal(rule_doc["point_upper"], f"{field}.point_upper")
        ci_upper = parse_decimal_literal(rule_doc["ci_upper"], f"{field}.ci_upper")
        operator = require_enum(rule_doc["ci_operator"], f"{field}.ci_operator", ("lt", "le"))
        rules.append(
            ThresholdRule(
                lane_id=lane_id,
                point_upper=point_upper,
                ci_upper=ci_upper,
                ci_operator=operator,
            )
        )
    lanes = [rule.lane_id for rule in rules]
    if len(set(lanes)) != len(lanes):
        raise _fail(f"{field_path} must name each lane at most once", field_path)
    return tuple(rules)


def validate_policy_profile(document: object, bundle: ExperimentBundle) -> PolicyProfile:
    """Validate one closed policy-profile document against a BM-01 bundle."""

    if not isinstance(bundle, ExperimentBundle):
        raise _fail("a validated ExperimentBundle is required", "bundle")
    doc = require_closed(document, "policy-profile", _POLICY_KEYS)
    if doc["kind"] != POLICY_PROFILE_KIND:
        raise _schema("policy profile kind must be 'policy-profile'", "kind")
    if doc["schema_version"] != POLICY_PROFILE_SCHEMA_VERSION:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            "policy profile schema_version is not supported",
            field_path="schema_version",
        )
    require_synthetic_scope(
        doc["evidence_origin"], doc["qualification_scope"], "qualification_scope"
    )
    policy_id = validate_semantic_id(doc["policy_id"], "policy_id")
    policy_version = validate_positive_int(doc["policy_version"], "policy_version")

    declared_arms = tuple(arm.arm_id for arm in bundle.experiment.arms)
    declared_lanes = tuple(lane.lane_id for lane in bundle.workload.lanes)
    baseline_arm_id = validate_semantic_id(doc["baseline_arm_id"], "baseline_arm_id")
    if baseline_arm_id not in declared_arms:
        raise _fail("baseline_arm_id must be a declared arm", "baseline_arm_id")

    raw_candidates = require_list(doc["candidate_order"], "candidate_order")
    if not raw_candidates:
        raise _fail("candidate_order must not be empty", "candidate_order")
    candidate_order = tuple(
        validate_semantic_id(item, f"candidate_order[{index}]")
        for index, item in enumerate(raw_candidates)
    )
    if len(set(candidate_order)) != len(candidate_order):
        raise _fail("candidate_order must be unique", "candidate_order")
    for index, arm_id in enumerate(candidate_order):
        if arm_id not in declared_arms:
            raise _fail(
                f"candidate_order[{index}] must be a declared arm", "candidate_order"
            )
        if arm_id == baseline_arm_id:
            raise _fail(
                "candidate_order must be distinct from baseline_arm_id",
                "candidate_order",
            )
    undeclared = [
        arm_id
        for arm_id in declared_arms
        if arm_id != baseline_arm_id and arm_id not in candidate_order
    ]
    if undeclared:
        raise _fail(
            "candidate_order must declare every non-baseline arm",
            "candidate_order",
        )

    metric_direction = require_enum(
        doc["metric_direction"], "metric_direction", DIRECTIONS
    )
    if metric_direction != bundle.adapter.measurement_envelope.direction:
        raise _fail(
            "metric_direction must equal the adapter measurement envelope direction",
            "metric_direction",
        )

    targets = _validate_thresholds(doc["targets"], "targets", declared_lanes)
    if not targets:
        raise _fail("targets must declare at least one lane", "targets")
    guardrails = _validate_thresholds(doc["guardrails"], "guardrails", declared_lanes)
    target_lanes = {rule.lane_id for rule in targets}
    guardrail_lanes = {rule.lane_id for rule in guardrails}
    if target_lanes & guardrail_lanes:
        raise _fail(
            "targets and guardrails must name disjoint lane sets", "guardrails"
        )

    raw_resources = require_list(doc["resource_rules"], "resource_rules")
    resource_rules: list[ResourceRule] = []
    for index, raw_rule in enumerate(raw_resources):
        field = f"resource_rules[{index}]"
        rule_doc = require_closed(raw_rule, field, _RESOURCE_RULE_KEYS)
        arm_id = validate_semantic_id(rule_doc["arm_id"], f"{field}.arm_id")
        if arm_id not in declared_arms:
            raise _fail(f"{field}.arm_id must be a declared arm", field)
        resource_id = validate_semantic_id(rule_doc["resource_id"], f"{field}.resource_id")
        max_bytes = require_int(rule_doc["max_bytes"], f"{field}.max_bytes", maximum=MAX_RESOURCE_VALUE)
        resource_rules.append(
            ResourceRule(arm_id=arm_id, resource_id=resource_id, max_bytes=max_bytes)
        )
    keys = [(rule.arm_id, rule.resource_id) for rule in resource_rules]
    if keys != sorted(set(keys)):
        raise _fail(
            "resource_rules must be ascending and unique by (arm_id, resource_id)",
            "resource_rules",
        )

    selection_doc = require_closed(doc["selection"], "selection", _SELECTION_KEYS)
    raw_ranking = require_list(selection_doc["ranking_lanes"], "selection.ranking_lanes")
    if not raw_ranking:
        raise _fail("selection.ranking_lanes must not be empty", "selection.ranking_lanes")
    ranking_lanes = tuple(
        validate_semantic_id(item, f"selection.ranking_lanes[{index}]")
        for index, item in enumerate(raw_ranking)
    )
    if ranking_lanes != tuple(sorted(set(ranking_lanes))):
        raise _fail(
            "selection.ranking_lanes must be ascending and unique",
            "selection.ranking_lanes",
        )
    for index, lane_id in enumerate(ranking_lanes):
        if lane_id not in declared_lanes:
            raise _fail(
                f"selection.ranking_lanes[{index}] must be a declared lane",
                "selection.ranking_lanes",
            )
        if lane_id not in target_lanes | guardrail_lanes:
            raise _fail(
                f"selection.ranking_lanes[{index}] must also be a target or guardrail",
                "selection.ranking_lanes",
            )
    tie_delta = parse_decimal_literal(
        selection_doc["tie_relative_delta"], "selection.tie_relative_delta"
    )
    raw_preference = require_list(
        selection_doc["tie_preference"], "selection.tie_preference"
    )
    tie_preference = tuple(
        validate_semantic_id(item, f"selection.tie_preference[{index}]")
        for index, item in enumerate(raw_preference)
    )
    if sorted(tie_preference) != sorted(candidate_order):
        raise _fail(
            "selection.tie_preference must be a permutation of candidate_order",
            "selection.tie_preference",
        )
    fallback_arm_id = validate_semantic_id(
        selection_doc["fallback_arm_id"], "selection.fallback_arm_id"
    )
    if fallback_arm_id != baseline_arm_id:
        raise _fail(
            "selection.fallback_arm_id must be the declared baseline arm",
            "selection.fallback_arm_id",
        )
    filter_action = require_enum(
        selection_doc["filter_sensitivity_action"],
        "selection.filter_sensitivity_action",
        (FILTER_SENSITIVE_ACTION_INCONCLUSIVE,),
    )

    digest = content_digest(dict(doc))
    experiment_binding = bundle.experiment.policy
    protocol_binding = bundle.protocol.policy
    for binding, label in (
        (experiment_binding, "experiment.policy"),
        (protocol_binding, "protocol.policy"),
    ):
        if (
            binding.policy_id != policy_id
            or binding.policy_version != policy_version
            or binding.policy_digest != digest
        ):
            raise _fail(
                f"{label} binding must match the frozen policy profile identity and digest",
                "policy_id",
            )

    return PolicyProfile(
        policy_id=policy_id,
        policy_version=policy_version,
        evidence_origin=doc["evidence_origin"],
        qualification_scope=doc["qualification_scope"],
        baseline_arm_id=baseline_arm_id,
        candidate_order=candidate_order,
        metric_direction=metric_direction,
        targets=targets,
        guardrails=guardrails,
        resource_rules=tuple(resource_rules),
        selection=SelectionContract(
            ranking_lanes=ranking_lanes,
            tie_relative_delta=tie_delta,
            tie_preference=tie_preference,
            fallback_arm_id=fallback_arm_id,
            filter_sensitivity_action=filter_action,
        ),
        digest=digest,
        document=dict(doc),
    )


# ---------------------------------------------------------------------------
# Synthetic resource observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceObservation:
    """One synthetic per-arm resource observation."""

    arm_id: str
    resource_id: str
    value_bytes: int


@dataclass(frozen=True)
class ResourceObservations:
    """One validated, immutable, digest-bound synthetic resource record set."""

    experiment_id: str
    records: tuple[ResourceObservation, ...]
    digest: str
    document: Mapping[str, Any]

    def lookup(self, arm_id: str, resource_id: str) -> int | None:
        for record in self.records:
            if record.arm_id == arm_id and record.resource_id == resource_id:
                return record.value_bytes
        return None


def validate_resource_observations(
    document: object, bundle: ExperimentBundle
) -> ResourceObservations:
    """Validate one closed synthetic resource-observation document."""

    if not isinstance(bundle, ExperimentBundle):
        raise _fail("a validated ExperimentBundle is required", "bundle")
    doc = require_closed(document, "resource-observations", _RESOURCE_DOC_KEYS)
    if doc["kind"] != RESOURCE_OBSERVATIONS_KIND:
        raise _schema(
            "resource observations kind must be 'synthetic-resource-observations'",
            "kind",
        )
    if doc["schema_version"] != RESOURCE_OBSERVATIONS_SCHEMA_VERSION:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            "resource observations schema_version is not supported",
            field_path="schema_version",
        )
    require_synthetic_scope(
        doc["evidence_origin"], doc["qualification_scope"], "qualification_scope"
    )
    experiment_id = validate_semantic_id(doc["experiment_id"], "experiment_id")
    if experiment_id != bundle.experiment.experiment_id:
        raise _fail(
            "resource observations experiment_id must match the declared bundle",
            "experiment_id",
        )
    declared_arms = {arm.arm_id for arm in bundle.experiment.arms}
    raw_records = require_list(doc["records"], "records")
    records: list[ResourceObservation] = []
    for index, raw_record in enumerate(raw_records):
        field = f"records[{index}]"
        record_doc = require_closed(raw_record, field, _RESOURCE_RECORD_KEYS)
        arm_id = validate_semantic_id(record_doc["arm_id"], f"{field}.arm_id")
        if arm_id not in declared_arms:
            raise _fail(f"{field}.arm_id must be a declared arm", field)
        resource_id = validate_semantic_id(record_doc["resource_id"], f"{field}.resource_id")
        value_bytes = require_int(
            record_doc["value_bytes"], f"{field}.value_bytes", maximum=MAX_RESOURCE_VALUE
        )
        records.append(
            ResourceObservation(
                arm_id=arm_id, resource_id=resource_id, value_bytes=value_bytes
            )
        )
    keys = [(record.arm_id, record.resource_id) for record in records]
    if keys != sorted(set(keys)):
        raise _fail(
            "resource records must be ascending and unique by (arm_id, resource_id)",
            "records",
        )
    return ResourceObservations(
        experiment_id=experiment_id,
        records=tuple(records),
        digest=content_digest(dict(doc)),
        document=dict(doc),
    )


def _read_bounded(root: Path, name: str, limit: int) -> Mapping[str, Any]:
    if not isinstance(root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, f"the {name} root must be a Path", field_path="root"
        )
    require_safe_root(root)
    handle = open_regular_beneath(root, name)
    with handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{name} exceeds the {limit}-byte limit",
            reference=name,
        )
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{name} must be stored in canonical byte form",
            reference=name,
        )
    return require_mapping(document, name)


def read_policy_profile(root: Path, bundle: ExperimentBundle) -> PolicyProfile:
    """Read one bounded, canonical, no-follow policy profile from ``root``."""

    return validate_policy_profile(
        _read_bounded(root, POLICY_PROFILE_NAME, MAX_PROFILE_BYTES), bundle
    )


def read_resource_observations(
    root: Path, bundle: ExperimentBundle
) -> ResourceObservations:
    """Read one bounded, canonical, no-follow resource record set from ``root``."""

    return validate_resource_observations(
        _read_bounded(root, RESOURCE_OBSERVATIONS_NAME, MAX_RESOURCE_BYTES), bundle
    )


# ---------------------------------------------------------------------------
# Policy evaluation records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyReason:
    """One closed policy reason record."""

    candidate_arm_id: str
    campaign_index: int | None
    lane_id: str | None
    code: str

    def to_document(self) -> dict[str, Any]:
        return {
            "candidate_arm_id": self.candidate_arm_id,
            "campaign_index": self.campaign_index,
            "lane_id": self.lane_id,
            "code": self.code,
        }

    def sort_key(self) -> tuple[int, str, str]:
        return (
            -1 if self.campaign_index is None else int(self.campaign_index),
            "" if self.lane_id is None else self.lane_id,
            self.code,
        )


@dataclass(frozen=True)
class LanePolicyResult:
    """One target or guardrail evaluation for one lane."""

    lane_id: str
    kind: str
    point_effect: Decimal | None
    ci_low: Decimal | None
    ci_high: Decimal | None
    point_limit: Decimal
    ci_limit: Decimal
    ci_operator: str
    retained_blocks: int
    status: str
    reasons: tuple[str, ...]

    def to_document(self) -> dict[str, Any]:
        def render(value: Decimal | None) -> str | None:
            return None if value is None else format(value, "f")

        return {
            "lane_id": self.lane_id,
            "kind": self.kind,
            "point_effect": render(self.point_effect),
            "ci_low": render(self.ci_low),
            "ci_high": render(self.ci_high),
            "point_limit": format(self.point_limit, "f"),
            "ci_limit": format(self.ci_limit, "f"),
            "ci_operator": self.ci_operator,
            "retained_blocks": self.retained_blocks,
            "status": self.status,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class CampaignCandidateResult:
    """One campaign's evaluation for one candidate."""

    campaign_index: int
    status: str
    lanes: tuple[LanePolicyResult, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "campaign_index": self.campaign_index,
            "status": self.status,
            "lanes": [lane.to_document() for lane in self.lanes],
        }


@dataclass(frozen=True)
class CandidatePolicyResult:
    """One candidate's aggregate policy result."""

    arm_id: str
    status: str
    worst_campaign_gm: Decimal | None
    campaign_results: tuple[CampaignCandidateResult, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "status": self.status,
            "worst_campaign_gm": (
                None
                if self.worst_campaign_gm is None
                else format(self.worst_campaign_gm, "f")
            ),
            "campaign_results": [
                campaign.to_document() for campaign in self.campaign_results
            ],
        }


@dataclass(frozen=True)
class RankedCandidate:
    """One ranked eligible candidate."""

    arm_id: str
    worst_campaign_gm: Decimal

    def to_document(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "worst_campaign_gm": format(self.worst_campaign_gm, "f"),
        }


@dataclass(frozen=True)
class PolicyDecision:
    """The complete in-memory policy outcome (before identity fields are added)."""

    baseline_arm_id: str
    candidate_results: tuple[CandidatePolicyResult, ...]
    selected_arm_id: str | None
    decision_status: str
    reasons: tuple[PolicyReason, ...]
    ranking: tuple[RankedCandidate, ...]

    def to_document(
        self,
        *,
        experiment_id: str,
        run_id: str,
        analysis_digest: str,
        policy_profile: PolicyProfile,
        resource_digest: str,
    ) -> dict[str, Any]:
        return {
            "kind": "synthetic-policy-decision",
            "schema_version": 1,
            "experiment_id": experiment_id,
            "run_id": run_id,
            "evidence_origin": SYNTHETIC_ORIGIN,
            "qualification_scope": SIMULATED_SCOPE,
            "status": DERIVED_STATUS,
            "analysis_digest": analysis_digest,
            "policy_profile_digest": policy_profile.digest,
            "resource_observations_digest": resource_digest,
            "policy_id": policy_profile.policy_id,
            "policy_version": policy_profile.policy_version,
            "baseline_arm_id": self.baseline_arm_id,
            "candidate_results": [
                candidate.to_document() for candidate in self.candidate_results
            ],
            "selected_arm_id": self.selected_arm_id,
            "decision_status": self.decision_status,
            "reasons": [reason.to_document() for reason in self.reasons],
            "ranking": [entry.to_document() for entry in self.ranking],
        }


# ---------------------------------------------------------------------------
# Analysis-record projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LaneView:
    lane_id: str
    retained_blocks: int
    candidates: tuple[Mapping[str, Any], ...]

    def candidate(self, arm_id: str) -> Mapping[str, Any]:
        for entry in self.candidates:
            if entry["candidate_arm_id"] == arm_id:
                return entry
        raise _fail(
            f"analysis record is missing candidate {arm_id!r} for lane {self.lane_id!r}",
            "campaigns[].lanes[].candidates",
        )


@dataclass(frozen=True)
class _CampaignView:
    campaign_index: int
    lanes: tuple[_LaneView, ...]

    def lane(self, lane_id: str) -> _LaneView:
        for entry in self.lanes:
            if entry.lane_id == lane_id:
                return entry
        raise _fail(
            f"analysis record is missing lane {lane_id!r} in campaign "
            f"{self.campaign_index}",
            "campaigns[].lanes",
        )


def _project_analysis(analysis_record: object) -> tuple[_CampaignView, ...]:
    doc = require_mapping(analysis_record, "analysis")
    campaigns = require_list(doc.get("campaigns"), "analysis.campaigns")
    views: list[_CampaignView] = []
    for position, raw_campaign in enumerate(campaigns):
        campaign = require_mapping(raw_campaign, f"campaigns[{position}]")
        index = require_int(campaign.get("campaign_index"), "campaign_index")
        lanes: list[_LaneView] = []
        for lane_position, raw_lane in enumerate(
            require_list(campaign.get("lanes"), "campaigns[].lanes")
        ):
            field = f"campaigns[{position}].lanes[{lane_position}]"
            lane = require_mapping(raw_lane, field)
            lane_id = validate_semantic_id(lane.get("lane_id"), f"{field}.lane_id")
            retained = require_list(lane.get("retained_blocks"), f"{field}.retained_blocks")
            raw_candidates = require_list(lane.get("candidates"), f"{field}.candidates")
            candidates: list[Mapping[str, Any]] = []
            for candidate_position, raw_candidate in enumerate(raw_candidates):
                candidate_field = f"{field}.candidates[{candidate_position}]"
                candidates.append(require_mapping(raw_candidate, candidate_field))
            lanes.append(
                _LaneView(
                    lane_id=lane_id,
                    retained_blocks=len(retained),
                    candidates=tuple(candidates),
                )
            )
        views.append(_CampaignView(campaign_index=index, lanes=tuple(lanes)))
    return tuple(views)


def _option_effect(value: object, field_path: str) -> Decimal | None:
    if value is None:
        return None
    return require_formatted_effect(value, field_path)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _evaluate_threshold(
    rule: ThresholdRule,
    *,
    kind: str,
    lane: _LaneView,
    arm_id: str,
    minimum_retained: int,
) -> tuple[LanePolicyResult, str]:
    entry = lane.candidate(arm_id)
    point = _option_effect(entry.get("raw_point_effect"), "raw_point_effect")
    retained_point = _option_effect(
        entry.get("retained_point_effect"), "retained_point_effect"
    )
    ci_low = _option_effect(entry.get("ci_low"), "ci_low")
    ci_high = _option_effect(entry.get("ci_high"), "ci_high")
    status = entry.get("status")
    prefix = "TARGET" if kind == "target" else "GUARDRAIL"

    if status != LANE_STATUS_ANALYZED or retained_point is None or ci_low is None or ci_high is None:
        return (
            LanePolicyResult(
                lane_id=rule.lane_id,
                kind=kind,
                point_effect=point,
                ci_low=ci_low,
                ci_high=ci_high,
                point_limit=rule.point_upper,
                ci_limit=rule.ci_upper,
                ci_operator=rule.ci_operator,
                retained_blocks=lane.retained_blocks,
                status="insufficient",
                reasons=(REASON_INSUFFICIENT_RETAINED_BLOCKS,),
            ),
            CANDIDATE_INCONCLUSIVE,
        )
    if lane.retained_blocks < minimum_retained:
        return (
            LanePolicyResult(
                lane_id=rule.lane_id,
                kind=kind,
                point_effect=point,
                ci_low=ci_low,
                ci_high=ci_high,
                point_limit=rule.point_upper,
                ci_limit=rule.ci_upper,
                ci_operator=rule.ci_operator,
                retained_blocks=lane.retained_blocks,
                status="insufficient",
                reasons=(REASON_INSUFFICIENT_RETAINED_BLOCKS,),
            ),
            CANDIDATE_INCONCLUSIVE,
        )

    point_ok = retained_point <= rule.point_upper
    ci_ok = (
        ci_high < rule.ci_upper
        if rule.ci_operator == "lt"
        else ci_high <= rule.ci_upper
    )
    if point_ok and ci_ok:
        return (
            LanePolicyResult(
                lane_id=rule.lane_id,
                kind=kind,
                point_effect=retained_point,
                ci_low=ci_low,
                ci_high=ci_high,
                point_limit=rule.point_upper,
                ci_limit=rule.ci_upper,
                ci_operator=rule.ci_operator,
                retained_blocks=lane.retained_blocks,
                status="pass",
                reasons=(),
            ),
            CANDIDATE_ELIGIBLE,
        )
    if ci_low > rule.ci_upper and retained_point > rule.point_upper:
        return (
            LanePolicyResult(
                lane_id=rule.lane_id,
                kind=kind,
                point_effect=retained_point,
                ci_low=ci_low,
                ci_high=ci_high,
                point_limit=rule.point_upper,
                ci_limit=rule.ci_upper,
                ci_operator=rule.ci_operator,
                retained_blocks=lane.retained_blocks,
                status="decisive-failure",
                reasons=(f"{prefix}_DECISIVE_FAILURE",),
            ),
            CANDIDATE_INELIGIBLE,
        )
    return (
        LanePolicyResult(
            lane_id=rule.lane_id,
            kind=kind,
            point_effect=retained_point,
            ci_low=ci_low,
            ci_high=ci_high,
            point_limit=rule.point_upper,
            ci_limit=rule.ci_upper,
            ci_operator=rule.ci_operator,
            retained_blocks=lane.retained_blocks,
            status="unproven",
            reasons=(f"{prefix}_UNPROVEN",),
        ),
        CANDIDATE_INCONCLUSIVE,
    )


def _combine(statuses: Sequence[str]) -> str:
    if any(status == CANDIDATE_INELIGIBLE for status in statuses):
        return CANDIDATE_INELIGIBLE
    if any(status == CANDIDATE_INCONCLUSIVE for status in statuses):
        return CANDIDATE_INCONCLUSIVE
    return CANDIDATE_ELIGIBLE


def _sign(value: Decimal) -> int:
    if value > 1:
        return 1
    if value < 1:
        return -1
    return 0


def _filter_sensitive_lanes(
    campaigns: tuple[_CampaignView, ...],
    policy_profile: PolicyProfile,
) -> set[tuple[int, str, str]]:
    """Return the ``(campaign_index, lane_id, arm_id)`` rows that flipped sign/order."""

    affected: set[tuple[int, str, str]] = set()
    candidates = policy_profile.candidate_order
    for campaign in campaigns:
        for lane in campaign.lanes:
            for arm_id in candidates:
                entry = lane.candidate(arm_id)
                raw = _option_effect(entry.get("raw_point_effect"), "raw_point_effect")
                retained = _option_effect(
                    entry.get("retained_point_effect"), "retained_point_effect"
                )
                if raw is None or retained is None:
                    continue
                if _sign(raw) != _sign(retained):
                    affected.add((campaign.campaign_index, lane.lane_id, arm_id))
            if len(candidates) < 2:
                continue
            raw_effects = [
                _option_effect(
                    lane.candidate(arm_id).get("raw_point_effect"), "raw_point_effect"
                )
                for arm_id in candidates
            ]
            retained_effects = [
                _option_effect(
                    lane.candidate(arm_id).get("retained_point_effect"),
                    "retained_point_effect",
                )
                for arm_id in candidates
            ]
            order_changed = False
            for first in range(len(candidates)):
                for second in range(first + 1, len(candidates)):
                    a_raw, b_raw = raw_effects[first], raw_effects[second]
                    a_ret, b_ret = retained_effects[first], retained_effects[second]
                    if None in (a_raw, b_raw, a_ret, b_ret):
                        continue
                    if _sign(a_raw - b_raw) != _sign(a_ret - b_ret):
                        order_changed = True
            if order_changed:
                for arm_id in candidates:
                    affected.add((campaign.campaign_index, lane.lane_id, arm_id))
    return affected


def evaluate_policy(
    analysis_record: object,
    profile: PolicyProfile,
    resource_record: ResourceObservations,
    *,
    minimum_retained_blocks: int = 2,
) -> PolicyDecision:
    """Evaluate the frozen policy over one validated analysis document.

    Precedence per §8.1: resource, statistical sufficiency, target, guardrail,
    filter sensitivity; then per-campaign and cross-campaign precedence; then the
    frozen global selection. Every applicable reason is preserved in sorted order;
    no early return conceals another failure.
    """

    if not isinstance(profile, PolicyProfile):
        raise _fail("a validated PolicyProfile is required", "profile")
    if not isinstance(resource_record, ResourceObservations):
        raise _fail("validated resource observations are required", "resource_record")
    minimum_retained = max(
        require_int(minimum_retained_blocks, "minimum_retained_blocks", minimum=1), 2
    )
    campaigns = _project_analysis(analysis_record)
    declared_campaigns = tuple(
        campaign.campaign_index for campaign in campaigns
    )
    if declared_campaigns != tuple(range(len(campaigns))):
        raise _fail(
            "analysis campaigns must be ordered by campaign_index from zero",
            "campaigns",
        )
    affected = _filter_sensitive_lanes(campaigns, profile)

    reasons: list[PolicyReason] = []
    candidate_results: list[CandidatePolicyResult] = []
    for arm_id in profile.candidate_order:
        campaign_results: list[CampaignCandidateResult] = []
        for campaign in campaigns:
            lane_results: list[LanePolicyResult] = []
            campaign_reasons: list[PolicyReason] = []
            statuses: list[str] = []

            # 2. resource eligibility (global per candidate, recorded per campaign)
            for rule in profile.resource_rules:
                if rule.arm_id != arm_id:
                    continue
                observed = resource_record.lookup(rule.arm_id, rule.resource_id)
                if observed is None:
                    statuses.append(CANDIDATE_INCONCLUSIVE)
                    campaign_reasons.append(
                        PolicyReason(
                            candidate_arm_id=arm_id,
                            campaign_index=campaign.campaign_index,
                            lane_id=None,
                            code=REASON_MISSING_RESOURCE,
                        )
                    )
                elif observed > rule.max_bytes:
                    statuses.append(CANDIDATE_INELIGIBLE)
                    campaign_reasons.append(
                        PolicyReason(
                            candidate_arm_id=arm_id,
                            campaign_index=campaign.campaign_index,
                            lane_id=None,
                            code=REASON_RESOURCE_OVER_LIMIT,
                        )
                    )

            # 3-5. target and guardrail rules in the profile's declared order
            for lane_id in tuple(
                rule.lane_id for rule in profile.targets
            ) + tuple(rule.lane_id for rule in profile.guardrails):
                lane = campaign.lane(lane_id)
                for kind, rule in profile.rules_for(lane_id):
                    result, status = _evaluate_threshold(
                        rule,
                        kind=kind,
                        lane=lane,
                        arm_id=arm_id,
                        minimum_retained=minimum_retained,
                    )
                    lane_results.append(result)
                    statuses.append(status)
                    for code in result.reasons:
                        campaign_reasons.append(
                            PolicyReason(
                                candidate_arm_id=arm_id,
                                campaign_index=campaign.campaign_index,
                                lane_id=lane_id,
                                code=code,
                            )
                        )

            # 6. filter sensitivity (descriptive, never an exclusion trigger)
            for lane in campaign.lanes:
                if (campaign.campaign_index, lane.lane_id, arm_id) in affected:
                    statuses.append(CANDIDATE_INCONCLUSIVE)
                    campaign_reasons.append(
                        PolicyReason(
                            candidate_arm_id=arm_id,
                            campaign_index=campaign.campaign_index,
                            lane_id=lane.lane_id,
                            code=REASON_FILTER_SENSITIVE,
                        )
                    )

            campaign_status = _combine(statuses)
            reasons.extend(campaign_reasons)
            campaign_results.append(
                CampaignCandidateResult(
                    campaign_index=campaign.campaign_index,
                    status=campaign_status,
                    lanes=tuple(lane_results),
                )
            )

        aggregate = _combine([result.status for result in campaign_results])
        worst_gm: Decimal | None = None
        if aggregate == CANDIDATE_ELIGIBLE:
            campaign_gms: list[Decimal] = []
            missing = False
            for campaign in campaigns:
                effects: list[Decimal] = []
                for lane_id in profile.selection.ranking_lanes:
                    lane = campaign.lane(lane_id)
                    entry = lane.candidate(arm_id)
                    retained = _option_effect(
                        entry.get("retained_point_effect"), "retained_point_effect"
                    )
                    if retained is None:
                        missing = True
                        break
                    effects.append(retained)
                if missing:
                    break
                campaign_gms.append(geometric_mean(effects))
            if missing:
                aggregate = CANDIDATE_INCONCLUSIVE
                reasons.append(
                    PolicyReason(
                        candidate_arm_id=arm_id,
                        campaign_index=None,
                        lane_id=None,
                        code=REASON_MISSING_RANKING_GM,
                    )
                )
            else:
                worst_gm = quantize_policy_gm(worst_campaign_gm(campaign_gms))
        candidate_results.append(
            CandidatePolicyResult(
                arm_id=arm_id,
                status=aggregate,
                worst_campaign_gm=worst_gm,
                campaign_results=tuple(campaign_results),
            )
        )

    return _select(
        profile,
        tuple(candidate_results),
        tuple(_dedupe_reasons(reasons)),
    )


def quantize_policy_gm(value: Decimal) -> Decimal:
    """Quantise a geometric mean to the canonical 12-place form."""

    from .contracts import quantize_effect

    return quantize_effect(value)


def _dedupe_reasons(reasons: tuple[PolicyReason, ...]) -> tuple[PolicyReason, ...]:
    unique: dict[tuple[Any, ...], PolicyReason] = {}
    for reason in reasons:
        key = (
            reason.candidate_arm_id,
            reason.campaign_index,
            reason.lane_id,
            reason.code,
        )
        unique.setdefault(key, reason)
    return tuple(sorted(unique.values(), key=lambda item: item.sort_key()))


def _select(
    profile: PolicyProfile,
    candidate_results: tuple[CandidatePolicyResult, ...],
    reasons: tuple[PolicyReason, ...],
) -> PolicyDecision:
    eligible = [item for item in candidate_results if item.status == CANDIDATE_ELIGIBLE]
    inconclusive = [
        item for item in candidate_results if item.status == CANDIDATE_INCONCLUSIVE
    ]
    ordered = sorted(
        eligible,
        key=lambda item: (
            item.worst_campaign_gm
            if item.worst_campaign_gm is not None
            else Decimal("Infinity")
        ),
    )
    ranking = tuple(
        RankedCandidate(arm_id=item.arm_id, worst_campaign_gm=item.worst_campaign_gm)
        for item in ordered
        if item.worst_campaign_gm is not None
    )

    if not eligible:
        if inconclusive:
            return PolicyDecision(
                baseline_arm_id=profile.baseline_arm_id,
                candidate_results=candidate_results,
                selected_arm_id=None,
                decision_status=DECISION_INCONCLUSIVE,
                reasons=reasons,
                ranking=(),
            )
        return PolicyDecision(
            baseline_arm_id=profile.baseline_arm_id,
            candidate_results=candidate_results,
            selected_arm_id=profile.baseline_arm_id,
            decision_status=DECISION_BASELINE_ONLY,
            reasons=reasons,
            ranking=(),
        )
    if len(eligible) == 1:
        return PolicyDecision(
            baseline_arm_id=profile.baseline_arm_id,
            candidate_results=candidate_results,
            selected_arm_id=eligible[0].arm_id,
            decision_status=DECISION_SELECTED,
            reasons=reasons,
            ranking=ranking,
        )

    best, second = ordered[0], ordered[1]
    best_gm = best.worst_campaign_gm
    second_gm = second.worst_campaign_gm
    if best_gm is None or second_gm is None:  # pragma: no cover - eligible carries a GM
        raise _fail("an eligible candidate must carry a worst campaign GM", "ranking")
    tied = best_gm == second_gm
    if not tied:
        tied = relative_delta(best_gm, second_gm) < profile.selection.tie_relative_delta
    if not tied:
        return PolicyDecision(
            baseline_arm_id=profile.baseline_arm_id,
            candidate_results=candidate_results,
            selected_arm_id=best.arm_id,
            decision_status=DECISION_SELECTED,
            reasons=reasons,
            ranking=ranking,
        )
    pair = {best.arm_id, second.arm_id}
    for arm_id in profile.selection.tie_preference:
        if arm_id in pair:
            chosen = arm_id
            break
    else:  # pragma: no cover - tie_preference is a permutation of candidate_order
        chosen = best.arm_id
    return PolicyDecision(
        baseline_arm_id=profile.baseline_arm_id,
        candidate_results=candidate_results,
        selected_arm_id=chosen,
        decision_status=DECISION_TIE_PREFERENCE,
        reasons=reasons,
        ranking=ranking,
    )


__all__ = [
    "POLICY_PROFILE_NAME",
    "RESOURCE_OBSERVATIONS_NAME",
    "CandidatePolicyResult",
    "PolicyDecision",
    "PolicyProfile",
    "PolicyReason",
    "RankedCandidate",
    "ResourceObservation",
    "ResourceObservations",
    "ThresholdRule",
    "evaluate_policy",
    "read_policy_profile",
    "read_resource_observations",
    "validate_policy_profile",
    "validate_resource_observations",
]

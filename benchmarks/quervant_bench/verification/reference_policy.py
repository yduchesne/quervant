"""Independent frozen-policy evaluator for BM-05.

This module re-derives the complete ``synthetic-policy-decision`` document from
(a) the **independently reconstructed** analysis document, (b) the frozen policy
profile and (c) the frozen synthetic resource observations. It never calls
``analysis.policy.evaluate_policy``, ``analysis.policy._select`` or any primary
numeric helper, and it never treats a supplied policy outcome as an input.

The truth table is the frozen BM-04 contract: exact decimal comparisons, no
epsilon, strict ``lt`` versus inclusive ``le``, resource equality allowed,
descriptive filter sensitivity, INELIGIBLE-dominant precedence, ascending
worst-campaign geometric-mean ranking with declaration-order tie breaks, and a
selection rule restricted to the best two candidates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..config.errors import BM_IDENTITY_INVALID, BM_SCHEMA_INVALID, BenchError
from .contracts import (
    CANDIDATE_ELIGIBLE,
    CANDIDATE_INCONCLUSIVE,
    CANDIDATE_INELIGIBLE,
    DECISION_BASELINE_ONLY,
    DECISION_INCONCLUSIVE,
    DECISION_SELECTED,
    DECISION_TIE_PREFERENCE,
    DERIVED_STATUS,
    EVIDENCE_ORIGIN,
    FILTER_SENSITIVITY_ACTION,
    LANE_STATUS_ANALYZED,
    OUTPUT_DECIMAL_PLACES,
    OUTPUT_SCHEMA_VERSION,
    POLICY_KIND,
    QUALIFICATION_SCOPE,
    REASON_FILTER_SENSITIVE,
    REASON_GUARDRAIL_DECISIVE_FAILURE,
    REASON_GUARDRAIL_UNPROVEN,
    REASON_INSUFFICIENT_RETAINED_BLOCKS,
    REASON_MISSING_RANKING_GM,
    REASON_MISSING_RESOURCE,
    REASON_RESOURCE_OVER_LIMIT,
    REASON_TARGET_DECISIVE_FAILURE,
    REASON_TARGET_UNPROVEN,
)
from .reference_math import (
    format_12,
    geometric_mean,
    parse_effect_literal,
    quantize_12,
    relative_delta,
    sign_of,
    worst_campaign_gm,
)

def _schema(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def _identity(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def _formatted_effect(value: object, field_path: str) -> Decimal:
    parsed = parse_effect_literal(value, field_path)
    if parsed.as_tuple().exponent != -OUTPUT_DECIMAL_PLACES:
        raise _schema(
            f"{field_path} must carry exactly {OUTPUT_DECIMAL_PLACES} fractional digits",
            field_path,
        )
    return parsed


def _optional_effect(value: object, field_path: str) -> Decimal | None:
    if value is None:
        return None
    return _formatted_effect(value, field_path)


def _mapping(value: object, field_path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _schema(f"{field_path} must be a JSON object", field_path)
    return value


def _array(value: object, field_path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _schema(f"{field_path} must be an array", field_path)
    return value


@dataclass(frozen=True)
class _LaneView:
    lane_id: str
    retained_blocks: int
    candidates: tuple[Mapping[str, Any], ...]

    def candidate(self, arm_id: str) -> Mapping[str, Any]:
        for entry in self.candidates:
            if entry.get("candidate_arm_id") == arm_id:
                return entry
        raise _identity(
            f"the analysis document omits candidate {arm_id!r} for lane "
            f"{self.lane_id!r}",
            "campaigns[].lanes[].candidates",
        )


@dataclass(frozen=True)
class _CampaignView:
    campaign_index: int
    lanes: tuple[_LaneView, ...]

    def lane(self, lane_id: str) -> _LaneView:
        for lane in self.lanes:
            if lane.lane_id == lane_id:
                return lane
        raise _identity(
            f"the analysis document omits lane {lane_id!r} from campaign "
            f"{self.campaign_index}",
            "campaigns[].lanes",
        )


def _project_analysis(analysis_document: Mapping[str, Any]) -> tuple[_CampaignView, ...]:
    raw_campaigns = _array(analysis_document.get("campaigns"), "analysis.campaigns")
    campaigns: list[_CampaignView] = []
    for campaign_position, raw_campaign in enumerate(raw_campaigns):
        campaign_field = f"campaigns[{campaign_position}]"
        campaign = _mapping(raw_campaign, campaign_field)
        index = campaign.get("campaign_index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise _schema(
                f"{campaign_field}.campaign_index must be a non-negative integer",
                f"{campaign_field}.campaign_index",
            )
        lanes: list[_LaneView] = []
        raw_lanes = _array(campaign.get("lanes"), f"{campaign_field}.lanes")
        for lane_position, raw_lane in enumerate(raw_lanes):
            lane_field = f"{campaign_field}.lanes[{lane_position}]"
            lane = _mapping(raw_lane, lane_field)
            lane_id = lane.get("lane_id")
            if not isinstance(lane_id, str) or not lane_id:
                raise _schema(
                    f"{lane_field}.lane_id must be a non-empty string",
                    f"{lane_field}.lane_id",
                )
            retained = _array(
                lane.get("retained_blocks"), f"{lane_field}.retained_blocks"
            )
            candidates = tuple(
                _mapping(item, f"{lane_field}.candidates[{position}]")
                for position, item in enumerate(
                    _array(lane.get("candidates"), f"{lane_field}.candidates")
                )
            )
            lanes.append(
                _LaneView(
                    lane_id=lane_id,
                    retained_blocks=len(retained),
                    candidates=candidates,
                )
            )
        campaigns.append(_CampaignView(campaign_index=index, lanes=tuple(lanes)))
    return tuple(campaigns)


# ---------------------------------------------------------------------------
# Individual rule evaluation
# ---------------------------------------------------------------------------


def _lane_result(
    *,
    lane_id: str,
    kind: str,
    point: Decimal | None,
    ci_low: Decimal | None,
    ci_high: Decimal | None,
    point_limit: Decimal,
    ci_limit: Decimal,
    ci_operator: str,
    retained_blocks: int,
    status: str,
    reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "kind": kind,
        "point_effect": None if point is None else format_12(point),
        "ci_low": None if ci_low is None else format_12(ci_low),
        "ci_high": None if ci_high is None else format_12(ci_high),
        "point_limit": format_12(point_limit),
        "ci_limit": format_12(ci_limit),
        "ci_operator": ci_operator,
        "retained_blocks": retained_blocks,
        "status": status,
        "reasons": list(reasons),
    }


def _evaluate_threshold(
    rule: Any,
    *,
    kind: str,
    lane: _LaneView,
    arm_id: str,
    minimum_retained: int,
) -> tuple[dict[str, Any], str]:
    entry = lane.candidate(arm_id)
    raw_point = _formatted_effect(
        entry.get("raw_point_effect"), "raw_point_effect"
    )
    retained_point = _optional_effect(
        entry.get("retained_point_effect"), "retained_point_effect"
    )
    ci_low = _optional_effect(entry.get("ci_low"), "ci_low")
    ci_high = _optional_effect(entry.get("ci_high"), "ci_high")
    status = entry.get("status")
    prefix = "TARGET" if kind == "target" else "GUARDRAIL"

    if (
        status != LANE_STATUS_ANALYZED
        or retained_point is None
        or ci_low is None
        or ci_high is None
        or lane.retained_blocks < minimum_retained
    ):
        return (
            _lane_result(
                lane_id=rule.lane_id,
                kind=kind,
                point=raw_point,
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
    if rule.ci_operator == "lt":
        ci_ok = ci_high < rule.ci_upper
    elif rule.ci_operator == "le":
        ci_ok = ci_high <= rule.ci_upper
    else:  # pragma: no cover - the frozen profile validator rejects this
        raise _schema("ci_operator must be 'lt' or 'le'", "ci_operator")

    if point_ok and ci_ok:
        return (
            _lane_result(
                lane_id=rule.lane_id,
                kind=kind,
                point=retained_point,
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
        reason = (
            REASON_TARGET_DECISIVE_FAILURE
            if prefix == "TARGET"
            else REASON_GUARDRAIL_DECISIVE_FAILURE
        )
        return (
            _lane_result(
                lane_id=rule.lane_id,
                kind=kind,
                point=retained_point,
                ci_low=ci_low,
                ci_high=ci_high,
                point_limit=rule.point_upper,
                ci_limit=rule.ci_upper,
                ci_operator=rule.ci_operator,
                retained_blocks=lane.retained_blocks,
                status="decisive-failure",
                reasons=(reason,),
            ),
            CANDIDATE_INELIGIBLE,
        )
    reason = (
        REASON_TARGET_UNPROVEN
        if prefix == "TARGET"
        else REASON_GUARDRAIL_UNPROVEN
    )
    return (
        _lane_result(
            lane_id=rule.lane_id,
            kind=kind,
            point=retained_point,
            ci_low=ci_low,
            ci_high=ci_high,
            point_limit=rule.point_upper,
            ci_limit=rule.ci_upper,
            ci_operator=rule.ci_operator,
            retained_blocks=lane.retained_blocks,
            status="unproven",
            reasons=(reason,),
        ),
        CANDIDATE_INCONCLUSIVE,
    )


def _combine(statuses: Sequence[str]) -> str:
    if any(status == CANDIDATE_INELIGIBLE for status in statuses):
        return CANDIDATE_INELIGIBLE
    if any(status == CANDIDATE_INCONCLUSIVE for status in statuses):
        return CANDIDATE_INCONCLUSIVE
    return CANDIDATE_ELIGIBLE


def _reason(
    candidate_arm_id: str,
    campaign_index: int | None,
    lane_id: str | None,
    code: str,
) -> dict[str, Any]:
    return {
        "candidate_arm_id": candidate_arm_id,
        "campaign_index": campaign_index,
        "lane_id": lane_id,
        "code": code,
    }


def _filter_sensitive(
    campaigns: Sequence[_CampaignView], candidate_order: Sequence[str]
) -> set[tuple[int, str, str]]:
    affected: set[tuple[int, str, str]] = set()
    for campaign in campaigns:
        for lane in campaign.lanes:
            for arm_id in candidate_order:
                entry = lane.candidate(arm_id)
                raw = _optional_effect(
                    entry.get("raw_point_effect"), "raw_point_effect"
                )
                retained = _optional_effect(
                    entry.get("retained_point_effect"), "retained_point_effect"
                )
                if raw is None or retained is None:
                    continue
                if sign_of(raw) != sign_of(retained):
                    affected.add((campaign.campaign_index, lane.lane_id, arm_id))
            if len(candidate_order) < 2:
                continue
            raw_effects = [
                _optional_effect(
                    lane.candidate(arm_id).get("raw_point_effect"),
                    "raw_point_effect",
                )
                for arm_id in candidate_order
            ]
            retained_effects = [
                _optional_effect(
                    lane.candidate(arm_id).get("retained_point_effect"),
                    "retained_point_effect",
                )
                for arm_id in candidate_order
            ]
            order_changed = False
            for first in range(len(candidate_order)):
                for second in range(first + 1, len(candidate_order)):
                    first_raw = raw_effects[first]
                    second_raw = raw_effects[second]
                    first_retained = retained_effects[first]
                    second_retained = retained_effects[second]
                    if None in (
                        first_raw,
                        second_raw,
                        first_retained,
                        second_retained,
                    ):
                        continue
                    if sign_of(first_raw - second_raw) != sign_of(
                        first_retained - second_retained
                    ):
                        order_changed = True
            if order_changed:
                for arm_id in candidate_order:
                    affected.add((campaign.campaign_index, lane.lane_id, arm_id))
    return affected


# ---------------------------------------------------------------------------
# Full policy evaluation
# ---------------------------------------------------------------------------


def _dedupe_and_sort(reasons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for reason in reasons:
        key = (
            reason["candidate_arm_id"],
            reason["campaign_index"],
            reason["lane_id"],
            reason["code"],
        )
        unique.setdefault(key, dict(reason))

    def sort_key(item: Mapping[str, Any]) -> tuple[int, str, str]:
        campaign = item["campaign_index"]
        lane = item["lane_id"]
        return (
            -1 if campaign is None else int(campaign),
            "" if lane is None else str(lane),
            str(item["code"]),
        )

    return sorted(unique.values(), key=sort_key)


def _ranked(
    eligible: Sequence[dict[str, Any]], candidate_order: Sequence[str]
) -> list[dict[str, Any]]:
    order = {arm_id: position for position, arm_id in enumerate(candidate_order)}
    ordered = sorted(
        eligible,
        key=lambda item: (item["_worst_gm"], order[item["arm_id"]]),
    )
    return [
        {
            "arm_id": item["arm_id"],
            "worst_campaign_gm": format_12(item["_worst_gm"]),
        }
        for item in ordered
        if item["_worst_gm"] is not None
    ]


def evaluate_reference_policy(
    *,
    analysis_document: Mapping[str, Any],
    policy_profile: Any,
    observations: Any,
    minimum_retained: int,
    experiment_id: str,
    run_id: str,
    analysis_digest: str,
) -> dict[str, Any]:
    """Build the complete expected ``synthetic-policy-decision`` document."""

    if isinstance(minimum_retained, bool) or not isinstance(minimum_retained, int):
        raise _schema("minimum_retained must be an integer", "minimum_retained")
    if minimum_retained < 1:
        raise _schema("minimum_retained must be positive", "minimum_retained")
    minimum_retained = max(minimum_retained, 2)
    if policy_profile.selection.filter_sensitivity_action != FILTER_SENSITIVITY_ACTION:
        raise _schema(
            "the frozen policy must declare filter_sensitivity_action=inconclusive",
            "selection.filter_sensitivity_action",
        )
    candidate_order = tuple(policy_profile.candidate_order)
    campaigns = _project_analysis(analysis_document)
    if tuple(campaign.campaign_index for campaign in campaigns) != tuple(
        range(len(campaigns))
    ):
        raise _identity(
            "analysis campaigns must be ordered by campaign_index from zero",
            "campaigns",
        )
    affected = _filter_sensitive(campaigns, candidate_order)

    reasons: list[dict[str, Any]] = []
    candidate_results: list[dict[str, Any]] = []
    for arm_id in candidate_order:
        campaign_results: list[dict[str, Any]] = []
        for campaign in campaigns:
            lane_results: list[dict[str, Any]] = []
            campaign_reasons: list[dict[str, Any]] = []
            statuses: list[str] = []

            for rule in policy_profile.resource_rules:
                if rule.arm_id != arm_id:
                    continue
                observed = observations.lookup(rule.arm_id, rule.resource_id)
                if observed is None:
                    statuses.append(CANDIDATE_INCONCLUSIVE)
                    campaign_reasons.append(
                        _reason(
                            arm_id,
                            campaign.campaign_index,
                            None,
                            REASON_MISSING_RESOURCE,
                        )
                    )
                elif observed > rule.max_bytes:
                    statuses.append(CANDIDATE_INELIGIBLE)
                    campaign_reasons.append(
                        _reason(
                            arm_id,
                            campaign.campaign_index,
                            None,
                            REASON_RESOURCE_OVER_LIMIT,
                        )
                    )

            target_lane_ids = tuple(rule.lane_id for rule in policy_profile.targets)
            guardrail_lane_ids = tuple(
                rule.lane_id for rule in policy_profile.guardrails
            )
            for lane_id in target_lane_ids + guardrail_lane_ids:
                if lane_id in target_lane_ids:
                    kind = "target"
                    rule = next(
                        item
                        for item in policy_profile.targets
                        if item.lane_id == lane_id
                    )
                else:
                    kind = "guardrail"
                    rule = next(
                        item
                        for item in policy_profile.guardrails
                        if item.lane_id == lane_id
                    )
                result, status = _evaluate_threshold(
                    rule,
                    kind=kind,
                    lane=campaign.lane(lane_id),
                    arm_id=arm_id,
                    minimum_retained=minimum_retained,
                )
                lane_results.append(result)
                statuses.append(status)
                for code in result["reasons"]:
                    campaign_reasons.append(
                        _reason(
                            arm_id, campaign.campaign_index, lane_id, code
                        )
                    )

            for lane in campaign.lanes:
                if (campaign.campaign_index, lane.lane_id, arm_id) in affected:
                    statuses.append(CANDIDATE_INCONCLUSIVE)
                    campaign_reasons.append(
                        _reason(
                            arm_id,
                            campaign.campaign_index,
                            lane.lane_id,
                            REASON_FILTER_SENSITIVE,
                        )
                    )

            campaign_status = _combine(statuses)
            reasons.extend(campaign_reasons)
            campaign_results.append(
                {
                    "campaign_index": campaign.campaign_index,
                    "status": campaign_status,
                    "lanes": lane_results,
                }
            )

        aggregate = _combine([item["status"] for item in campaign_results])
        worst_gm: Decimal | None = None
        if aggregate == CANDIDATE_ELIGIBLE:
            campaign_gms: list[Decimal] = []
            missing = False
            for campaign in campaigns:
                effects: list[Decimal] = []
                for lane_id in policy_profile.selection.ranking_lanes:
                    lane = campaign.lane(lane_id)
                    entry = lane.candidate(arm_id)
                    retained = _optional_effect(
                        entry.get("retained_point_effect"),
                        "retained_point_effect",
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
                    _reason(arm_id, None, None, REASON_MISSING_RANKING_GM)
                )
            else:
                worst_gm = quantize_12(
                    worst_campaign_gm(campaign_gms), "worst_campaign_gm"
                )
        candidate_results.append(
            {
                "arm_id": arm_id,
                "status": aggregate,
                "worst_campaign_gm": worst_gm,
                "_worst_gm": worst_gm,
                "campaign_results": campaign_results,
            }
        )

    deduped = _dedupe_and_sort(reasons)
    eligible = [
        item for item in candidate_results if item["status"] == CANDIDATE_ELIGIBLE
    ]
    inconclusive = [
        item
        for item in candidate_results
        if item["status"] == CANDIDATE_INCONCLUSIVE
    ]
    ranking = _ranked(eligible, candidate_order)

    if not eligible:
        if inconclusive:
            selected: str | None = None
            decision_status = DECISION_INCONCLUSIVE
        else:
            selected = policy_profile.baseline_arm_id
            decision_status = DECISION_BASELINE_ONLY
    elif len(eligible) == 1:
        selected = eligible[0]["arm_id"]
        decision_status = DECISION_SELECTED
    else:
        order = {arm_id: position for position, arm_id in enumerate(candidate_order)}
        ordered = sorted(
            eligible, key=lambda item: (item["_worst_gm"], order[item["arm_id"]])
        )
        best, second = ordered[0], ordered[1]
        best_gm = best["_worst_gm"]
        second_gm = second["_worst_gm"]
        if best_gm is None or second_gm is None:  # pragma: no cover - eligible carries a GM
            raise _identity(
                "an eligible candidate must carry a worst campaign GM", "ranking"
            )
        tied = best_gm == second_gm or (
            relative_delta(best_gm, second_gm)
            < policy_profile.selection.tie_relative_delta
        )
        if not tied:
            selected = best["arm_id"]
            decision_status = DECISION_SELECTED
        else:
            pair = {best["arm_id"], second["arm_id"]}
            selected = next(
                (
                    arm_id
                    for arm_id in policy_profile.selection.tie_preference
                    if arm_id in pair
                ),
                best["arm_id"],
            )
            decision_status = DECISION_TIE_PREFERENCE

    for item in candidate_results:
        item.pop("_worst_gm", None)
    for item in eligible:
        item.pop("_worst_gm", None)

    return {
        "kind": POLICY_KIND,
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "evidence_origin": EVIDENCE_ORIGIN,
        "qualification_scope": QUALIFICATION_SCOPE,
        "status": DERIVED_STATUS,
        "analysis_digest": analysis_digest,
        "policy_profile_digest": policy_profile.digest,
        "resource_observations_digest": observations.digest,
        "policy_id": policy_profile.policy_id,
        "policy_version": policy_profile.policy_version,
        "baseline_arm_id": policy_profile.baseline_arm_id,
        "candidate_results": [
            {
                "arm_id": item["arm_id"],
                "status": item["status"],
                "worst_campaign_gm": (
                    None
                    if item["worst_campaign_gm"] is None
                    else format_12(item["worst_campaign_gm"])
                ),
                "campaign_results": item["campaign_results"],
            }
            for item in candidate_results
        ],
        "selected_arm_id": selected,
        "decision_status": decision_status,
        "reasons": deduped,
        "ranking": ranking,
    }


__all__ = ["evaluate_reference_policy"]

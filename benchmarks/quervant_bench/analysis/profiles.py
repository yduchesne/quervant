"""The closed, versioned BM-04 analysis profile and its bounded reader.

A profile is an **internal BM-04 v1 contract**, not a seventh BM-01 public schema.
It is independently frozen: its canonical bytes are digest-bound into the BM-01
experiment document, and every statistical identity it declares must agree with
the declared protocol. There is no implicit default, no alias profile and no
mutable fallback.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from ..config.identity import (
    validate_positive_int,
    validate_semantic_id,
    validate_uint64,
)
from ..evidence.paths import open_regular_beneath, require_safe_root
from ..protocol.controls import read_protocol_campaigns
from .contracts import (
    CONFIDENCE_BASIS_POINTS,
    ESTIMATORS,
    MAX_TOTAL_DRAWS,
    OUTPUT_DECIMAL_PLACES,
    parse_decimal_literal,
    require_bool,
    require_closed,
    require_enum,
    require_int,
    require_list,
    require_mapping,
    require_synthetic_scope,
    validate_digest,
)

ANALYSIS_PROFILE_KIND = "analysis-profile"
ANALYSIS_PROFILE_NAME = "analysis-profile.v1.json"
ANALYSIS_PROFILE_SCHEMA_VERSION = 1
MAX_PROFILE_BYTES = 1_048_576

SLOT_AGGREGATOR = "median-v1"
BLOCK_AGGREGATOR = "mean-of-slot-medians-v1"
BOOTSTRAP_ALGORITHM = "sha256-rejection-paired-block-v1"
EXCLUSION_RULESET = "within-arm-spread-v1"

MIN_RESAMPLES = 100
MAX_RESAMPLES = 20_000
MAX_CANDIDATE_ARMS = 8
MAX_LANES = 64
MAX_TREATMENT_CAMPAIGNS = 8
MAX_BLOCKS = 256

MIN_WITHIN_ARM_CAP = Decimal("1.000000000000")
MAX_WITHIN_ARM_CAP = Decimal("100.000000000000")

_PROFILE_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "analysis_id",
        "analysis_version",
        "evidence_origin",
        "qualification_scope",
        "slot_aggregator",
        "block_aggregator",
        "estimator_id",
        "bootstrap",
        "exclusion",
        "output_precision_decimal_places",
    }
)
_BOOTSTRAP_KEYS = frozenset(
    {
        "algorithm_id",
        "interval_id",
        "confidence_basis_points",
        "resamples",
        "seed",
    }
)
_EXCLUSION_KEYS = frozenset(
    {
        "ruleset_id",
        "symmetric_by_lane_and_block",
        "minimum_retained_blocks",
        "per_lane_caps",
    }
)
_CAP_KEYS = frozenset({"lane_id", "max_within_arm_ratio"})


def _fail(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class LaneCap:
    """One lane's frozen within-arm spread cap."""

    lane_id: str
    max_within_arm_ratio: Decimal


@dataclass(frozen=True)
class BootstrapContract:
    """The frozen bootstrap identity for one analysis profile."""

    algorithm_id: str
    interval_id: str
    confidence_basis_points: int
    resamples: int
    seed: int


@dataclass(frozen=True)
class ExclusionContract:
    """The frozen symmetric exclusion ruleset."""

    ruleset_id: str
    symmetric_by_lane_and_block: bool
    minimum_retained_blocks: int
    per_lane_caps: tuple[LaneCap, ...]

    def cap_for(self, lane_id: str) -> Decimal:
        for cap in self.per_lane_caps:
            if cap.lane_id == lane_id:
                return cap.max_within_arm_ratio
        raise _fail(
            f"no within-arm spread cap is declared for lane {lane_id!r}",
            "exclusion.per_lane_caps",
        )


@dataclass(frozen=True)
class AnalysisProfile:
    """One validated, immutable, digest-bound analysis profile."""

    analysis_id: str
    analysis_version: int
    evidence_origin: str
    qualification_scope: str
    slot_aggregator: str
    block_aggregator: str
    estimator_id: str
    bootstrap: BootstrapContract
    exclusion: ExclusionContract
    output_precision_decimal_places: int
    digest: str
    document: Mapping[str, Any]


def validate_analysis_profile(
    document: object, bundle: ExperimentBundle
) -> AnalysisProfile:
    """Validate one closed analysis-profile document against a BM-01 bundle."""

    if not isinstance(bundle, ExperimentBundle):
        raise _fail("a validated ExperimentBundle is required", "bundle")
    doc = require_closed(document, "analysis-profile", _PROFILE_KEYS)
    if doc["kind"] != ANALYSIS_PROFILE_KIND:
        raise BenchError(
            BM_SCHEMA_INVALID, "profile kind must be 'analysis-profile'", field_path="kind"
        )
    if doc["schema_version"] != ANALYSIS_PROFILE_SCHEMA_VERSION:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            "analysis profile schema_version is not supported",
            field_path="schema_version",
        )
    require_synthetic_scope(
        doc["evidence_origin"], doc["qualification_scope"], "qualification_scope"
    )
    analysis_id = validate_semantic_id(doc["analysis_id"], "analysis_id")
    analysis_version = validate_positive_int(doc["analysis_version"], "analysis_version")
    if doc["slot_aggregator"] != SLOT_AGGREGATOR:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            f"slot_aggregator must be {SLOT_AGGREGATOR!r}",
            field_path="slot_aggregator",
        )
    if doc["block_aggregator"] != BLOCK_AGGREGATOR:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            f"block_aggregator must be {BLOCK_AGGREGATOR!r}",
            field_path="block_aggregator",
        )
    estimator_id = require_enum(doc["estimator_id"], "estimator_id", ESTIMATORS)

    bootstrap_doc = require_closed(doc["bootstrap"], "bootstrap", _BOOTSTRAP_KEYS)
    if bootstrap_doc["algorithm_id"] != BOOTSTRAP_ALGORITHM:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            f"bootstrap.algorithm_id must be {BOOTSTRAP_ALGORITHM!r}",
            field_path="bootstrap.algorithm_id",
        )
    interval_id = validate_semantic_id(
        bootstrap_doc["interval_id"], "bootstrap.interval_id"
    )
    confidence = require_int(
        bootstrap_doc["confidence_basis_points"],
        "bootstrap.confidence_basis_points",
    )
    if confidence != CONFIDENCE_BASIS_POINTS:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            f"bootstrap.confidence_basis_points must be {CONFIDENCE_BASIS_POINTS}",
            field_path="bootstrap.confidence_basis_points",
        )
    resamples = require_int(
        bootstrap_doc["resamples"], "bootstrap.resamples", maximum=MAX_RESAMPLES
    )
    if resamples < MIN_RESAMPLES:
        raise _fail(
            f"bootstrap.resamples must be at least {MIN_RESAMPLES}",
            "bootstrap.resamples",
        )
    seed = validate_uint64(bootstrap_doc["seed"], "bootstrap.seed")

    exclusion_doc = require_closed(doc["exclusion"], "exclusion", _EXCLUSION_KEYS)
    ruleset_id = require_enum(
        exclusion_doc["ruleset_id"], "exclusion.ruleset_id", (EXCLUSION_RULESET,)
    )
    symmetric = require_bool(
        exclusion_doc["symmetric_by_lane_and_block"],
        "exclusion.symmetric_by_lane_and_block",
    )
    if symmetric is not True:
        raise _fail(
            "exclusion.symmetric_by_lane_and_block must be true",
            "exclusion.symmetric_by_lane_and_block",
        )
    minimum_retained = require_int(
        exclusion_doc["minimum_retained_blocks"],
        "exclusion.minimum_retained_blocks",
        minimum=1,
    )

    workload_lanes = tuple(lane.lane_id for lane in bundle.workload.lanes)
    if len(workload_lanes) > MAX_LANES:
        raise _fail(f"the workload exceeds the {MAX_LANES}-lane budget", "lane_ids")
    raw_caps = require_list(exclusion_doc["per_lane_caps"], "exclusion.per_lane_caps")
    caps: list[LaneCap] = []
    for index, raw_cap in enumerate(raw_caps):
        field = f"exclusion.per_lane_caps[{index}]"
        cap_doc = require_closed(raw_cap, field, _CAP_KEYS)
        lane_id = validate_semantic_id(cap_doc["lane_id"], f"{field}.lane_id")
        cap = parse_decimal_literal(
            cap_doc["max_within_arm_ratio"], f"{field}.max_within_arm_ratio"
        )
        if cap < MIN_WITHIN_ARM_CAP:
            raise _fail(
                f"{field}.max_within_arm_ratio must be >= 1.000000000000", field
            )
        if cap > MAX_WITHIN_ARM_CAP:
            raise _fail(
                f"{field}.max_within_arm_ratio must not exceed 100.000000000000", field
            )
        caps.append(LaneCap(lane_id=lane_id, max_within_arm_ratio=cap))
    cap_lanes = [cap.lane_id for cap in caps]
    if cap_lanes != sorted(set(cap_lanes)):
        raise _fail(
            "per_lane_caps must be ascending and unique by lane_id",
            "exclusion.per_lane_caps",
        )
    if tuple(sorted(cap_lanes)) != tuple(sorted(workload_lanes)):
        raise _fail(
            "per_lane_caps must cover every declared workload lane exactly once",
            "exclusion.per_lane_caps",
        )
    if minimum_retained > bundle.protocol.schedule.blocks:
        raise _fail(
            "exclusion.minimum_retained_blocks must not exceed schedule.blocks",
            "exclusion.minimum_retained_blocks",
        )

    precision = require_int(
        doc["output_precision_decimal_places"], "output_precision_decimal_places"
    )
    if precision != OUTPUT_DECIMAL_PLACES:
        raise BenchError(
            BM_SCHEMA_UNSUPPORTED,
            f"output_precision_decimal_places must be {OUTPUT_DECIMAL_PLACES}",
            field_path="output_precision_decimal_places",
        )

    # --- protocol binding -------------------------------------------------
    statistics = require_mapping(
        bundle.protocol_document.get("statistics"), "protocol.statistics"
    )
    protocol_exclusion = require_mapping(
        bundle.protocol_document.get("exclusion"), "protocol.exclusion"
    )
    if estimator_id != statistics.get("method_id"):
        raise _fail(
            "analysis-profile estimator_id must match protocol.statistics.method_id",
            "estimator_id",
        )
    if interval_id != statistics.get("interval_id"):
        raise _fail(
            "analysis-profile bootstrap.interval_id must match protocol.statistics.interval_id",
            "bootstrap.interval_id",
        )
    if resamples != statistics.get("resamples"):
        raise _fail(
            "analysis-profile bootstrap.resamples must match protocol.statistics.resamples",
            "bootstrap.resamples",
        )
    if seed != statistics.get("seed"):
        raise _fail(
            "analysis-profile bootstrap.seed must match protocol.statistics.seed",
            "bootstrap.seed",
        )
    if ruleset_id != protocol_exclusion.get("ruleset_id"):
        raise _fail(
            "analysis-profile exclusion.ruleset_id must match protocol.exclusion.ruleset_id",
            "exclusion.ruleset_id",
        )
    if minimum_retained != protocol_exclusion.get("minimum_retained_blocks"):
        raise _fail(
            "analysis-profile exclusion.minimum_retained_blocks must match the protocol",
            "exclusion.minimum_retained_blocks",
        )

    # --- experiment binding ----------------------------------------------
    digest = content_digest(dict(doc))
    binding = bundle.experiment.analysis
    if binding.analysis_id != analysis_id or binding.analysis_version != analysis_version:
        raise _fail(
            "experiment.analysis identity must match the analysis profile",
            "analysis_id",
        )
    if binding.analysis_digest != digest:
        raise _fail(
            "experiment.analysis.analysis_digest must equal the profile content digest",
            "analysis_digest",
        )

    profile = AnalysisProfile(
        analysis_id=analysis_id,
        analysis_version=analysis_version,
        evidence_origin=doc["evidence_origin"],
        qualification_scope=doc["qualification_scope"],
        slot_aggregator=doc["slot_aggregator"],
        block_aggregator=doc["block_aggregator"],
        estimator_id=estimator_id,
        bootstrap=BootstrapContract(
            algorithm_id=bootstrap_doc["algorithm_id"],
            interval_id=interval_id,
            confidence_basis_points=confidence,
            resamples=resamples,
            seed=seed,
        ),
        exclusion=ExclusionContract(
            ruleset_id=ruleset_id,
            symmetric_by_lane_and_block=symmetric,
            minimum_retained_blocks=minimum_retained,
            per_lane_caps=tuple(caps),
        ),
        output_precision_decimal_places=precision,
        digest=digest,
        document=dict(doc),
    )
    require_draw_budget(profile, bundle)
    return profile


def bootstrap_comparison_count(profile: AnalysisProfile, bundle: ExperimentBundle) -> int:
    """Return the candidate x lane x treatment-campaign comparison count."""

    campaigns = read_protocol_campaigns(bundle)
    candidates = max(len(bundle.experiment.arms) - 1, 0)
    lanes = len(bundle.workload.lanes)
    return candidates * lanes * campaigns.required_treatments


def require_draw_budget(profile: AnalysisProfile, bundle: ExperimentBundle) -> int:
    """Reject an over-budget derivation **before** any resampling happens."""

    if len(bundle.experiment.arms) > MAX_CANDIDATE_ARMS + 1:
        raise _fail(
            f"the experiment exceeds the {MAX_CANDIDATE_ARMS}-candidate-arm budget",
            "arms",
        )
    if len(bundle.workload.lanes) > MAX_LANES:
        raise _fail(f"the workload exceeds the {MAX_LANES}-lane budget", "lane_ids")
    campaigns = read_protocol_campaigns(bundle)
    if campaigns.required_treatments > MAX_TREATMENT_CAMPAIGNS:
        raise _fail(
            f"the protocol exceeds the {MAX_TREATMENT_CAMPAIGNS}-treatment-campaign budget",
            "campaigns.required_treatments",
        )
    blocks = bundle.protocol.schedule.blocks
    if blocks > MAX_BLOCKS:
        raise _fail(f"schedule.blocks exceeds the {MAX_BLOCKS} budget", "schedule.blocks")
    draws = (
        profile.bootstrap.resamples
        * blocks
        * bootstrap_comparison_count(profile, bundle)
    )
    if draws > MAX_TOTAL_DRAWS:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"the derivation would need {draws} bootstrap draws, above the "
            f"{MAX_TOTAL_DRAWS} budget",
            field_path="bootstrap.resamples",
        )
    return draws


def require_minimum_retained(
    profile: AnalysisProfile, bundle: ExperimentBundle
) -> int:
    """Return the retained-block count needed to issue any interval."""

    del bundle  # the call signature mirrors the other budget helpers
    return max(profile.exclusion.minimum_retained_blocks, 2)


def read_analysis_profile(root: Path, bundle: ExperimentBundle) -> AnalysisProfile:
    """Read one bounded, canonical, no-follow analysis profile from ``root``."""

    if not isinstance(root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the analysis profile root must be a Path",
            field_path="profiles_root",
        )
    require_safe_root(root)
    handle = open_regular_beneath(root, ANALYSIS_PROFILE_NAME)
    with handle:
        payload = handle.read(MAX_PROFILE_BYTES + 1)
    if len(payload) > MAX_PROFILE_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{ANALYSIS_PROFILE_NAME} exceeds the {MAX_PROFILE_BYTES}-byte limit",
            reference=ANALYSIS_PROFILE_NAME,
        )
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"{ANALYSIS_PROFILE_NAME} must be stored in canonical byte form",
            reference=ANALYSIS_PROFILE_NAME,
        )
    return validate_analysis_profile(document, bundle)


__all__ = [
    "ANALYSIS_PROFILE_KIND",
    "ANALYSIS_PROFILE_NAME",
    "AnalysisProfile",
    "BootstrapContract",
    "ExclusionContract",
    "LaneCap",
    "bootstrap_comparison_count",
    "read_analysis_profile",
    "require_draw_budget",
    "require_minimum_retained",
    "validate_analysis_profile",
]

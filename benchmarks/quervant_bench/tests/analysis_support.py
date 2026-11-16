"""Shared, non-discovered support code for the BM-04 analysis test modules.

Nothing here asserts anything. It builds real BM-03 sealed synthetic runs through
the actual controller, adapter, store and replayer, and it constructs hand-authored
records for pure policy/arithmetic unit tests so that a failing boundary assertion
cannot be produced by bootstrap variability.
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from quervant_bench.analysis.contracts import (
    DIRECTIONS,
    parse_decimal_literal,
)
from quervant_bench.analysis.policy import (
    PolicyProfile,
    ResourceObservation,
    ResourceObservations,
    ResourceRule,
    SelectionContract,
    ThresholdRule,
)
from quervant_bench.config.codec import (
    canonical_document_bytes,
    content_digest,
    load_document,
)
from quervant_bench.config.contracts import ExperimentBundle, load_experiment_bundle
from quervant_bench.execution import (
    LogicalClock,
    ScenarioReadinessProvider,
    SimulatedCapabilityProvider,
    execute_synthetic,
    load_synthetic_scenario,
    replay_sealed_synthetic,
    synthetic_adapter_factory,
)

EXPERIMENT_ID = "synthetic-analysis-smoke"
BM03_EXPERIMENT_ID = "synthetic-execution-smoke"
EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"
ANALYSIS_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "analysis"
EXECUTION_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "execution"
SCENARIO_NAME = "synthetic-scenario.v1.json"
ZERO_DIGEST = "sha256:" + "0" * 64


def experiment_root() -> Path:
    """Return the new BM-04 experiment directory."""

    return EXPERIMENTS / EXPERIMENT_ID


def load_bundle(experiment_id: str = EXPERIMENT_ID) -> ExperimentBundle:
    """Load one declared experiment bundle from the real catalog."""

    return load_experiment_bundle(experiment_id, EXPERIMENTS)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_canonical(path: Path, document: dict[str, Any]) -> None:
    path.write_bytes(canonical_document_bytes(document))


def analysis_profile_document() -> dict[str, Any]:
    return read_json(experiment_root() / "analysis-profile.v1.json")


def policy_profile_document() -> dict[str, Any]:
    return read_json(experiment_root() / "policy-profile.v1.json")


def resource_document() -> dict[str, Any]:
    return read_json(experiment_root() / "resource-observations.v1.json")


class SealedRun:
    """A real BM-03 sealed synthetic run in an external temporary root."""

    def __init__(
        self,
        scenario_source: Path | None = None,
        *,
        bundle: ExperimentBundle | None = None,
        source_root: Path | None = None,
    ) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        source = scenario_source or ((source_root or experiment_root()) / SCENARIO_NAME)
        shutil.copy(source, self.evidence / SCENARIO_NAME)
        self.output = self.root / "out"
        self.output.mkdir()
        self.bundle = bundle if bundle is not None else load_bundle()
        self.scenario = load_synthetic_scenario(self.evidence, bundle=self.bundle)
        self.result = execute_synthetic(
            bundle=self.bundle,
            scenario=self.scenario,
            run_id=str(uuid.uuid4()),
            evidence_root=self.evidence,
            output_base=self.output,
            adapter_factory=synthetic_adapter_factory(self.bundle),
            capability_provider=SimulatedCapabilityProvider(),
            readiness_provider=ScenarioReadinessProvider(self.scenario),
            clock=LogicalClock(),
        )
        if self.result.status != "sealed":  # pragma: no cover - fixture guard
            raise AssertionError(f"the synthetic fixture did not seal: {self.result.reason}")
        self.run_dir = self.result.run_dir

    def replay(self):
        return replay_sealed_synthetic(
            self.run_dir, bundle=self.bundle, scenario_root=self.evidence
        )

    def close(self) -> None:
        self._temporary.cleanup()


# ---------------------------------------------------------------------------
# Hand-authored analysis records (pure policy unit tests)
# ---------------------------------------------------------------------------


def effect(value: str | int | Decimal) -> Decimal:
    """Parse a test literal into a Decimal (floats are never accepted)."""

    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return parse_decimal_literal(value, "effect")


def render(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000000000001")), "f")


def candidate_row(
    *,
    arm_id: str = "candidate",
    raw: Any = "0.800000000000",
    retained: Any = "0.800000000000",
    low: Any = "0.800000000000",
    high: Any = "0.800000000000",
    status: str = "analyzed",
    direction: str = "lower-is-better",
) -> dict[str, Any]:
    """Build one hand-authored candidate lane row for policy tests."""

    def opt(value: Any) -> str | None:
        return None if value is None else render(effect(value))

    return {
        "candidate_arm_id": arm_id,
        "comparison_direction": direction,
        "raw_point_effect": render(effect(raw)),
        "retained_point_effect": opt(retained),
        "ci_low": opt(low),
        "ci_high": opt(high),
        "bootstrap_stream_digest": None if status != "analyzed" else ZERO_DIGEST,
        "status": status,
        "raw_block_effects": [],
        "retained_block_effects": [],
    }


def lane_row(
    lane_id: str, candidates: list[dict[str, Any]], *, retained_blocks: int = 4
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "blocks_total": 4,
        "retained_blocks": list(range(1, retained_blocks + 1)),
        "excluded_blocks": list(range(retained_blocks + 1, 5)),
        "exclusion_ledger": [],
        "candidates": candidates,
    }


def analysis_document(campaigns: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Wrap hand-authored lane rows into the shape ``evaluate_policy`` reads."""

    return {
        "kind": "synthetic-analysis-result",
        "schema_version": 1,
        "campaigns": [
            {"campaign_index": index, "lanes": lanes}
            for index, lanes in enumerate(campaigns)
        ],
    }


def default_campaigns(
    *,
    rare: tuple[Any, Any, Any, Any, str] = (
        "0.800000000000",
        "0.800000000000",
        "0.800000000000",
        "0.800000000000",
        "analyzed",
    ),
    common: tuple[Any, Any, Any, Any, str] = (
        "0.833333333333",
        "0.833333333333",
        "0.833333333333",
        "0.833333333333",
        "analyzed",
    ),
    campaigns: int = 2,
    arms: tuple[str, ...] = ("candidate",),
) -> list[list[dict[str, Any]]]:
    """Build a passing two-campaign, two-lane hand-authored analysis document."""

    return [_two_lanes(rare, common, arms) for _ in range(campaigns)]


def _two_lanes(
    rare: tuple[Any, Any, Any, Any, str],
    common: tuple[Any, Any, Any, Any, str],
    arms: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane_id, values in (("rare-query", rare), ("common-query", common)):
        raw, retained, low, high, status = values
        rows.append(
            lane_row(
                lane_id,
                [
                    candidate_row(
                        arm_id=arm_id,
                        raw=raw,
                        retained=retained,
                        low=low,
                        high=high,
                        status=status,
                    )
                    for arm_id in arms
                ],
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Hand-authored policy profiles and resources
# ---------------------------------------------------------------------------


def make_threshold(
    lane_id: str,
    point_upper: str,
    ci_upper: str,
    ci_operator: str = "le",
) -> ThresholdRule:
    return ThresholdRule(
        lane_id=lane_id,
        point_upper=effect(point_upper),
        ci_upper=effect(ci_upper),
        ci_operator=ci_operator,
    )


def make_policy_profile(
    *,
    baseline_arm_id: str = "baseline",
    candidate_order: tuple[str, ...] = ("candidate",),
    metric_direction: str = "lower-is-better",
    targets: tuple[ThresholdRule, ...] | None = None,
    guardrails: tuple[ThresholdRule, ...] | None = None,
    resource_rules: tuple[ResourceRule, ...] | None = None,
    ranking_lanes: tuple[str, ...] = ("common-query", "rare-query"),
    tie_relative_delta: str = "0.030000000000",
    tie_preference: tuple[str, ...] | None = None,
    filter_sensitivity_action: str = "inconclusive",
    digest: str = ZERO_DIGEST,
) -> PolicyProfile:
    """Build an in-memory profile for pure policy-boundary tests."""

    if metric_direction not in DIRECTIONS:  # pragma: no cover - test guard
        raise AssertionError("unsupported direction")
    return PolicyProfile(
        policy_id="synthetic-analysis-policy",
        policy_version=1,
        evidence_origin="synthetic",
        qualification_scope="simulated",
        baseline_arm_id=baseline_arm_id,
        candidate_order=candidate_order,
        metric_direction=metric_direction,
        targets=targets
        if targets is not None
        else (make_threshold("rare-query", "0.950000000000", "1.000000000000", "lt"),),
        guardrails=guardrails
        if guardrails is not None
        else (make_threshold("common-query", "1.100000000000", "1.100000000000", "le"),),
        resource_rules=resource_rules
        if resource_rules is not None
        else (ResourceRule("candidate", "aux-memory-bytes", 2097152),),
        selection=SelectionContract(
            ranking_lanes=ranking_lanes,
            tie_relative_delta=effect(tie_relative_delta),
            tie_preference=tie_preference
            if tie_preference is not None
            else candidate_order,
            fallback_arm_id=baseline_arm_id,
            filter_sensitivity_action=filter_sensitivity_action,
        ),
        digest=digest,
        document={},
    )


def make_resources(
    *records: tuple[str, str, int],
) -> ResourceObservations:
    """Build a validated-shaped synthetic resource record set for unit tests."""

    if not records:
        records = (("candidate", "aux-memory-bytes", 1048576),)
    ordered = sorted(records)
    document = {
        "kind": "synthetic-resource-observations",
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "records": [
            {"arm_id": arm_id, "resource_id": resource_id, "value_bytes": value}
            for arm_id, resource_id, value in ordered
        ],
    }
    return ResourceObservations(
        experiment_id=EXPERIMENT_ID,
        records=tuple(
            ResourceObservation(arm_id=arm_id, resource_id=resource_id, value_bytes=value)
            for arm_id, resource_id, value in ordered
        ),
        digest=content_digest(document),
        document=document,
    )


def load_analysis_profile():
    """Load the real frozen analysis profile for the new experiment."""

    from quervant_bench.analysis.profiles import read_analysis_profile

    return read_analysis_profile(experiment_root(), load_bundle())


def load_policy_profile():
    """Load the real frozen policy profile for the new experiment."""

    from quervant_bench.analysis.policy import read_policy_profile

    return read_policy_profile(experiment_root(), load_bundle())


def load_resource_observations():
    """Load the real frozen synthetic resource observations."""

    from quervant_bench.analysis.policy import read_resource_observations

    return read_resource_observations(experiment_root(), load_bundle())


def make_analysis_profile(
    *,
    resamples: int | None = None,
    seed: int = 1592524801,
    estimator_id: str = "median-paired-ratios-v1",
    minimum_retained_blocks: int = 3,
    digest: str = ZERO_DIGEST,
):
    """Build an in-memory analysis profile for pure bootstrap-budget tests."""

    from quervant_bench.analysis.profiles import (
        AnalysisProfile,
        BootstrapContract,
        ExclusionContract,
        LaneCap,
    )

    lanes = ("common-query", "rare-query")
    return AnalysisProfile(
        analysis_id="paired-block-analysis",
        analysis_version=1,
        evidence_origin="synthetic",
        qualification_scope="simulated",
        slot_aggregator="median-v1",
        block_aggregator="mean-of-slot-medians-v1",
        estimator_id=estimator_id,
        bootstrap=BootstrapContract(
            algorithm_id="sha256-rejection-paired-block-v1",
            interval_id="nearest-rank-percentile-v1",
            confidence_basis_points=9500,
            resamples=1000 if resamples is None else resamples,
            seed=seed,
        ),
        exclusion=ExclusionContract(
            ruleset_id="within-arm-spread-v1",
            symmetric_by_lane_and_block=True,
            minimum_retained_blocks=minimum_retained_blocks,
            per_lane_caps=tuple(
                LaneCap(lane_id=lane, max_within_arm_ratio=Decimal("1.5"))
                for lane in lanes
            ),
        ),
        output_precision_decimal_places=12,
        digest=digest,
        document={},
    )


def campaigns_for(
    values_by_arm: dict[str, tuple[Any, Any, Any, Any, str]],
    *,
    campaigns: int = 2,
    lanes: tuple[str, ...] = ("rare-query", "common-query"),
    direction: str = "lower-is-better",
) -> list[list[dict[str, Any]]]:
    """Build per-campaign lane rows with explicit per-arm effect values."""

    built: list[list[dict[str, Any]]] = []
    for _ in range(campaigns):
        rows: list[dict[str, Any]] = []
        for lane_id in lanes:
            rows.append(
                lane_row(
                    lane_id,
                    [
                        candidate_row(
                            arm_id=arm_id,
                            raw=values[0],
                            retained=values[1],
                            low=values[2],
                            high=values[3],
                            status=values[4],
                            direction=direction,
                        )
                        for arm_id, values in values_by_arm.items()
                    ],
                )
            )
        built.append(rows)
    return built


_CACHE: dict[str, Any] = {}


def cached_sealed_run() -> SealedRun:
    """Return one process-wide sealed synthetic run (built at most once)."""

    if "run" not in _CACHE:
        import atexit

        run = SealedRun()
        _CACHE["run"] = run
        atexit.register(run.close)
    return _CACHE["run"]


def cached_derivation() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return one process-wide ``(analysis, policy)`` derivation pair."""

    if "derivation" not in _CACHE:
        from quervant_bench.analysis.derive import analyze_synthetic_run

        run = cached_sealed_run()
        _CACHE["derivation"] = analyze_synthetic_run(
            bundle=run.bundle,
            run_dir=run.run_dir,
            scenario_root=run.evidence,
            profiles_root=experiment_root(),
            resources_root=experiment_root(),
        )
    return _CACHE["derivation"]


# ---------------------------------------------------------------------------
# Isolated, fully bound synthetic catalogs (independent-review fixup fixtures)
# ---------------------------------------------------------------------------

ISOLATED_SCENARIO_NAME = "synthetic-scenario.v1.json"


def _write_yaml_document(path: Path, document: dict[str, Any]) -> None:
    """Write a loader-compatible YAML document (JSON is a YAML 1.2 subset)."""

    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_isolated_catalog(
    root: Path,
    *,
    experiment_id: str,
    arms: tuple[str, ...],
    baseline_arm_id: str,
    candidate_order: tuple[str, ...],
    targets: tuple[tuple[str, str, str, str], ...] | None = None,
    guardrails: tuple[tuple[str, str, str, str], ...] | None = None,
    ranking_lanes: tuple[str, ...] = ("common-query", "rare-query"),
    tie_preference: tuple[str, ...] | None = None,
    tie_relative_delta: str = "0.030000000000",
    resource_rules: tuple[tuple[str, str, int], ...] | None = None,
    resource_records: tuple[tuple[str, str, int], ...] | None = None,
    scenario_values: dict[tuple[str, str], tuple[int, ...]] | None = None,
    blocks: int = 4,
    required_controls: int = 1,
    required_treatments: int = 2,
    policy_limit_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one fully bound, self-consistent synthetic experiment catalog.

    Everything is derived from the checked-in `synthetic-analysis-smoke` fixture so
    the only differences are the arm set, the frozen policy document and the
    simulated sample values. All profile digests are recomputed from the actual
    canonical bytes and rebound in **both** the experiment and protocol documents.
    """

    source = experiment_root()
    catalog = Path(root)
    target = catalog / experiment_id
    target.mkdir(parents=True, exist_ok=True)

    experiment = load_document(source / "experiment.yaml")
    protocol = load_document(source / "protocol.yaml")
    workload = load_document(source / "workloads.yaml")
    adapter = load_document(source / "adapter.yaml")
    analysis_profile = load_document(source / "analysis-profile.v1.json")
    policy_profile = load_document(source / "policy-profile.v1.json")
    scenario = load_document(source / ISOLATED_SCENARIO_NAME)

    # --- frozen policy profile -------------------------------------------
    policy_profile["baseline_arm_id"] = baseline_arm_id
    policy_profile["candidate_order"] = list(candidate_order)
    if targets is not None:
        policy_profile["targets"] = [
            {
                "lane_id": lane_id,
                "point_upper": point_upper,
                "ci_upper": ci_upper,
                "ci_operator": operator,
            }
            for lane_id, point_upper, ci_upper, operator in targets
        ]
    if guardrails is not None:
        policy_profile["guardrails"] = [
            {
                "lane_id": lane_id,
                "point_upper": point_upper,
                "ci_upper": ci_upper,
                "ci_operator": operator,
            }
            for lane_id, point_upper, ci_upper, operator in guardrails
        ]
    if policy_limit_overrides:
        policy_profile.update(copy.deepcopy(policy_limit_overrides))
    rules = (
        resource_rules
        if resource_rules is not None
        else tuple(
            (arm_id, "aux-memory-bytes", 2097152) for arm_id in candidate_order
        )
    )
    policy_profile["resource_rules"] = [
        {"arm_id": arm_id, "resource_id": resource_id, "max_bytes": max_bytes}
        for arm_id, resource_id, max_bytes in sorted(rules)
    ]
    policy_profile["selection"]["ranking_lanes"] = list(ranking_lanes)
    policy_profile["selection"]["tie_preference"] = list(
        candidate_order if tie_preference is None else tie_preference
    )
    policy_profile["selection"]["tie_relative_delta"] = tie_relative_delta
    policy_profile["selection"]["fallback_arm_id"] = baseline_arm_id

    policy_digest = content_digest(policy_profile)
    analysis_digest = content_digest(analysis_profile)

    # --- experiment / protocol bindings ----------------------------------
    experiment["experiment_id"] = experiment_id
    experiment["arms"] = [
        {
            "arm_id": arm_id,
            "adapter_id": adapter["adapter_id"],
            "variant": arm_id,
        }
        for arm_id in arms
    ]
    experiment["policy"] = {
        "policy_id": policy_profile["policy_id"],
        "policy_version": policy_profile["policy_version"],
        "policy_digest": policy_digest,
    }
    experiment["analysis"] = {
        "analysis_id": analysis_profile["analysis_id"],
        "analysis_version": analysis_profile["analysis_version"],
        "analysis_digest": analysis_digest,
    }

    protocol["experiment_id"] = experiment_id
    protocol["workload_digest"] = content_digest(workload)
    protocol["arm_multiplicity"] = [
        {"arm_id": arm_id, "slots_per_block": 1} for arm_id in arms
    ]
    protocol["schedule"]["blocks"] = blocks
    protocol["schedule"]["slots_per_block"] = len(arms)
    protocol["campaigns"]["required_controls"] = required_controls
    protocol["campaigns"]["required_treatments"] = required_treatments
    protocol["policy"] = {
        "policy_id": policy_profile["policy_id"],
        "policy_version": policy_profile["policy_version"],
        "policy_digest": policy_digest,
    }
    protocol["exclusion"]["minimum_retained_blocks"] = min(
        3, blocks
    )

    # --- scenario ---------------------------------------------------------
    scenario["experiment_id"] = experiment_id
    scenario["scenario_id"] = experiment_id
    scenario["control_source_arm_id"] = baseline_arm_id
    if scenario_values is None:
        scenario_values = {
            (sample["arm_id"], sample["lane_id"]): tuple(sample["values"])
            for sample in scenario["samples"]
        }
    scenario["samples"] = [
        {"arm_id": arm_id, "lane_id": lane_id, "values": list(values)}
        for (arm_id, lane_id), values in sorted(scenario_values.items())
    ]
    scenario["readiness"] = [
        {
            "campaign_kind": "control",
            "campaign_index": index,
            "observations": copy.deepcopy(
                scenario["readiness"][0]["observations"]
            ),
        }
        for index in range(required_controls)
    ] + [
        {
            "campaign_kind": "treatment",
            "campaign_index": index,
            "observations": copy.deepcopy(
                scenario["readiness"][0]["observations"]
            ),
        }
        for index in range(required_treatments)
    ]

    records = (
        resource_records
        if resource_records is not None
        else tuple((arm_id, resource_id, 1048576) for arm_id, resource_id, _cap in rules)
    )
    resource_document = {
        "kind": "synthetic-resource-observations",
        "schema_version": 1,
        "experiment_id": experiment_id,
        "evidence_origin": "synthetic",
        "qualification_scope": "simulated",
        "records": [
            {"arm_id": arm_id, "resource_id": resource_id, "value_bytes": value}
            for arm_id, resource_id, value in sorted(records)
        ],
    }

    write_canonical(target / "analysis-profile.v1.json", analysis_profile)
    write_canonical(target / "policy-profile.v1.json", policy_profile)
    write_canonical(target / "resource-observations.v1.json", resource_document)
    write_canonical(target / ISOLATED_SCENARIO_NAME, scenario)
    _write_yaml_document(target / "experiment.yaml", experiment)
    _write_yaml_document(target / "protocol.yaml", protocol)
    _write_yaml_document(target / "workloads.yaml", workload)
    _write_yaml_document(target / "adapter.yaml", adapter)

    bundle = load_experiment_bundle(experiment_id, catalog)
    return {
        "catalog_root": catalog,
        "experiment_root": target,
        "bundle": bundle,
        "policy_digest": policy_digest,
        "analysis_digest": analysis_digest,
    }

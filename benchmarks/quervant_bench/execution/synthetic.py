"""The one synthetic adapter implementation for BM-03.

``SyntheticAdapter`` implements the frozen BM-01 :class:`BenchmarkAdapter`
protocol exactly: ``prepare``, ``check_oracle``, ``warmup``, ``measure`` and
``cleanup``. It returns frozen BM-01 result dataclasses and replays declared
scenario values. It never times, sleeps, samples a host or measures Quervant.

A real ``source-and-binary`` adapter manifest is refused before any acquisition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..config.contracts import (
    AdapterContext,
    BenchmarkAdapter,
    ExperimentBundle,
    Lane,
    MeasurementResult,
    OracleResult,
    PreparedFixture,
    WarmupResult,
)
from ..config.errors import (
    BM_ACQUISITION_PROHIBITED,
    BM_IDENTITY_INVALID,
    BenchError,
)
from ..config.identity import validate_semantic_id, validate_uuid4
from .contracts import (
    SIMULATED_SCOPE,
    SYNTHETIC_ADAPTER_ID,
    SYNTHETIC_ADAPTER_VERSION,
    SYNTHETIC_DIRECTION,
    SYNTHETIC_METRIC_UNIT,
    SYNTHETIC_ORIGIN,
    ArmAssignment,
    SlotKey,
)
from .scenario import SyntheticScenario

FIXTURE_ID = "synthetic-fixture"
FIXTURE_STATUS = "prepared"
PASS_STATUS = "pass"

SyntheticAdapterFactory = Callable[
    [ArmAssignment, SlotKey, SyntheticScenario], BenchmarkAdapter
]


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class _Identity:
    """Immutable adapter identity captured at construction."""

    experiment_id: str
    declared_arm_id: str
    display_arm_id: str
    variant: str
    campaign_kind: str
    oracle_id: str
    oracle_version: int
    fixture_digest: str
    lane_ids: tuple[str, ...]
    slot: SlotKey


def require_synthetic_bundle(bundle: ExperimentBundle) -> ExperimentBundle:
    """Refuse any bundle whose declared adapter is not the BM-03 simulator."""

    if not isinstance(bundle, ExperimentBundle):
        raise _fail("a validated ExperimentBundle is required", "bundle")
    identity = bundle.adapter.build_identity
    if identity.kind != "synthetic":
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            "BM-03 may only execute the synthetic build identity",
            field_path="adapter.build_identity.kind",
        )
    if bundle.adapter.adapter_id != SYNTHETIC_ADAPTER_ID:
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            f"BM-03 only executes the {SYNTHETIC_ADAPTER_ID!r} adapter manifest",
            field_path="adapter.adapter_id",
        )
    if bundle.adapter.adapter_version != SYNTHETIC_ADAPTER_VERSION:
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            f"BM-03 only executes adapter version {SYNTHETIC_ADAPTER_VERSION}",
            field_path="adapter.adapter_version",
        )
    if bundle.adapter.measurement_envelope.unit != SYNTHETIC_METRIC_UNIT:
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            "BM-03 only executes the synthetic nanosecond envelope",
            field_path="adapter.measurement_envelope.unit",
        )
    return bundle


class SyntheticAdapter:
    """Deterministic replay adapter satisfying ``BenchmarkAdapter``."""

    def __init__(
        self,
        bundle: ExperimentBundle,
        assignment: ArmAssignment,
        slot: SlotKey,
        scenario: SyntheticScenario,
    ) -> None:
        require_synthetic_bundle(bundle)
        if not isinstance(assignment, ArmAssignment):
            raise _fail("a validated ArmAssignment is required", "assignment")
        if not isinstance(slot, SlotKey):
            raise _fail("a validated SlotKey is required", "slot")
        if not isinstance(scenario, SyntheticScenario):
            raise _fail("a validated SyntheticScenario is required", "scenario")
        if scenario.experiment_id != bundle.experiment.experiment_id:
            raise _fail(
                "scenario and bundle experiment identities must match",
                "scenario.experiment_id",
            )
        if assignment.campaign_kind != slot.campaign_kind:
            raise _fail(
                "assignment and slot campaign kinds must match", "assignment.campaign_kind"
            )
        declared = {arm.arm_id: arm for arm in bundle.experiment.arms}
        arm = declared.get(assignment.declared_arm_id)
        if arm is None:
            raise _fail(
                "assignment declares an unknown arm", "assignment.declared_arm_id"
            )
        if arm.variant != assignment.variant:
            raise _fail("assignment variant must match the declared arm", "assignment.variant")
        self._identity = _Identity(
            experiment_id=bundle.experiment.experiment_id,
            declared_arm_id=arm.arm_id,
            display_arm_id=validate_semantic_id(
                assignment.display_arm_id, "assignment.display_arm_id"
            ),
            variant=arm.variant,
            campaign_kind=assignment.campaign_kind,
            oracle_id=bundle.workload.oracle_id,
            oracle_version=bundle.workload.oracle_version,
            fixture_digest=scenario.scenario_digest,
            lane_ids=tuple(lane.lane_id for lane in bundle.workload.lanes),
            slot=slot,
        )
        self._scenario = scenario
        self._lanes = {lane.lane_id: lane for lane in bundle.workload.lanes}

    # -- identity ---------------------------------------------------------

    @property
    def identity_fields(self) -> _Identity:
        """Return the immutable identity captured for this slot instance."""

        return self._identity

    def _require_context(self, context: AdapterContext) -> None:
        if not isinstance(context, AdapterContext):
            raise _fail("adapter calls require an AdapterContext", "context")
        if context.experiment_id != self._identity.experiment_id:
            raise _fail("adapter context experiment mismatch", "context.experiment_id")
        validate_uuid4(context.run_id, "context.run_id")
        if (
            context.evidence_origin != SYNTHETIC_ORIGIN
            or context.qualification_scope != SIMULATED_SCOPE
        ):
            raise BenchError(
                BM_ACQUISITION_PROHIBITED,
                "the synthetic adapter refuses non-synthetic evidence scope",
                field_path="context.qualification_scope",
            )
        if tuple(context.lane_ids) != self._identity.lane_ids:
            raise _fail(
                "adapter context lane order must match the declared workload",
                "context.lane_ids",
            )

    def _require_lane(self, lane: Lane) -> None:
        if not isinstance(lane, Lane) or lane.lane_id not in self._lanes:
            raise _fail("adapter lane is not declared by the workload", "lane.lane_id")

    # -- BenchmarkAdapter -------------------------------------------------

    def prepare(self, context: AdapterContext) -> PreparedFixture:
        self._require_context(context)
        return PreparedFixture(
            fixture_id=FIXTURE_ID,
            digest=self._identity.fixture_digest,
            status=FIXTURE_STATUS,
            evidence_origin=SYNTHETIC_ORIGIN,
            qualification_scope=SIMULATED_SCOPE,
        )

    def check_oracle(
        self, context: AdapterContext, prepared: PreparedFixture
    ) -> OracleResult:
        self._require_context(context)
        return OracleResult(
            oracle_id=self._identity.oracle_id,
            oracle_version=self._identity.oracle_version,
            status=PASS_STATUS,
            evidence_origin=SYNTHETIC_ORIGIN,
            qualification_scope=SIMULATED_SCOPE,
        )

    def warmup(
        self, context: AdapterContext, prepared: PreparedFixture, lane: Lane
    ) -> WarmupResult:
        self._require_context(context)
        self._require_lane(lane)
        return WarmupResult(
            lane_id=lane.lane_id,
            status=PASS_STATUS,
            evidence_origin=SYNTHETIC_ORIGIN,
            qualification_scope=SIMULATED_SCOPE,
        )

    def measure(
        self, context: AdapterContext, prepared: PreparedFixture, lane: Lane
    ) -> MeasurementResult:
        self._require_context(context)
        self._require_lane(lane)
        return MeasurementResult(
            lane_id=lane.lane_id,
            unit=SYNTHETIC_METRIC_UNIT,
            direction=SYNTHETIC_DIRECTION,
            status=PASS_STATUS,
            samples=self._scenario.values_for(
                self._identity.declared_arm_id, lane.lane_id
            ),
            evidence_origin=SYNTHETIC_ORIGIN,
            qualification_scope=SIMULATED_SCOPE,
        )

    def cleanup(self, context: AdapterContext, prepared: PreparedFixture) -> None:
        self._require_context(context)
        return None


def synthetic_adapter_factory(bundle: ExperimentBundle) -> SyntheticAdapterFactory:
    """Return the default injected factory bound to one validated bundle."""

    validated = require_synthetic_bundle(bundle)

    def factory(
        assignment: ArmAssignment, slot: SlotKey, scenario: SyntheticScenario
    ) -> BenchmarkAdapter:
        return SyntheticAdapter(validated, assignment, slot, scenario)

    return factory

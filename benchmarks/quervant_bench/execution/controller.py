"""The single synthetic execution controller.

One controller path executes *both* the synthetic A/A control and every treatment
campaign: same adapter factory, same recorder, same slot executor, same state
machine. Nothing here times, sleeps, samples a host or spawns a process.

Order of operations is binding:

``PLANNED`` -> durable schedule/control/freeze publication -> ``FROZEN`` ->
fresh injected capability snapshot -> per-campaign fresh readiness -> ``READY`` ->
first slot -> ``ACQUIRING`` -> slots -> ``COMPLETED`` -> last-file seal.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from ..config.codec import (
    canonical_document_bytes,
    content_digest,
    decode_text,
    loads_json,
    sha256_prefix,
)
from ..config.contracts import (
    ADAPTER_STATUSES,
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
    BM_NOT_IMPLEMENTED,
    BM_UNSAFE_INPUT,
    BenchError,
    internal_error,
)
from ..config.identity import validate_uuid4
from ..evidence.provenance import repository_root
from ..host.capabilities import (
    CapabilityProvider,
    collect_host_capabilities,
    validate_host_capabilities,
)
from ..host.readiness import ReadinessObservation, evaluate_readiness
from ..protocol.controls import (
    CONTROL_LEFT_ARM_ID,
    CONTROL_RIGHT_ARM_ID,
    ControlSchedule,
    build_control_schedule,
    read_protocol_campaigns,
)
from ..protocol.freeze import (
    build_freeze_document,
    validate_freeze_document,
    verify_freeze_bindings,
)
from ..protocol.schedule import (
    CompiledSchedule,
    ScheduleSlot,
    compile_schedule,
    schedule_document as make_schedule_document,
    validate_schedule_document,
)
from .clock import LogicalClock
from .contracts import (
    CONTROL_CONTRACT_ID,
    MAX_SYNTHETIC_SAMPLE_NS,
    SIMULATED_SCOPE,
    SYNTHETIC_METRIC_UNIT,
    SYNTHETIC_ORIGIN,
    ArmAssignment,
    ExecutionResult,
    FaultPlan,
    FaultPoint,
    RunState,
    SlotKey,
    StopReason,
    check_transition,
    total_journal_records,
    total_lane_slots,
)
from .recorder import (
    Recorder,
    build_control_report_document,
    build_lane_envelope_document,
    build_readiness_document,
    build_seal_document,
    build_slot_complete_document,
    control_relative_path,
    event_relative_path,
    lane_relative_path,
    readiness_relative_path,
    slot_complete_relative_path,
    validate_lane_envelope_document,
)
from .scenario import (
    SYNTHETIC_READINESS_LIMITS,
    SyntheticScenario,
    reopen_scenario_digest,
    validate_scenario_document,
)
from .store import SEAL_NAME, ExecutionStore
from .synthetic import (
    FIXTURE_ID,
    FIXTURE_STATUS,
    PASS_STATUS,
    SyntheticAdapter,
    SyntheticAdapterFactory,
    require_synthetic_bundle,
)

LOWER_IS_BETTER = "lower-is-better"


@runtime_checkable
class SyntheticReadinessProvider(Protocol):
    """Injected single-use source of simulated readiness observations."""

    def next_observations(
        self, campaign_kind: str, campaign_index: int
    ) -> tuple[ReadinessObservation, ...]: ...


class ScenarioReadinessProvider:
    """Default provider that serves each declared batch exactly once."""

    def __init__(self, scenario: SyntheticScenario) -> None:
        self._scenario = scenario
        self._consumed: set[tuple[str, int]] = set()
        self.calls: list[tuple[str, int]] = []

    def next_observations(
        self, campaign_kind: str, campaign_index: int
    ) -> tuple[ReadinessObservation, ...]:
        key = (campaign_kind, campaign_index)
        if key in self._consumed:
            raise BenchError(
                BM_IDENTITY_INVALID,
                "a simulated readiness batch may only be consumed once",
                field_path="readiness",
            )
        self._consumed.add(key)
        self.calls.append(key)
        return self._scenario.readiness_for(campaign_kind, campaign_index)


_SIMULATED_TOPOLOGY: dict[int, dict[str, str]] = {
    cpu: {
        "physical_package_id": "0",
        "core_id": str(cpu),
        "thread_siblings_list": str(cpu),
    }
    for cpu in (0, 1)
}


class SimulatedCapabilityProvider:
    """Frozen, static, entirely simulated host capability source.

    It returns the same closed record every time and never reads ``/proc``,
    ``/sys``, real platform metadata, CPU affinity or a clock.
    """

    def __init__(
        self,
        *,
        system: str = "Linux",
        machine: str = "x86_64",
        kernel_release: str = "6.0.0-simulated",
        cpus: tuple[int, ...] = (0, 1),
        include_topology: bool = True,
        proc_version: str | None = "Linux version 6.0.0-simulated",
    ) -> None:
        self._system = system
        self._machine = machine
        self._kernel = kernel_release
        self._cpus = cpus
        self._include_topology = include_topology
        self._proc_version = proc_version

    def read_text(self, relative_system_path: str) -> str | None:
        if relative_system_path == "/proc/version":
            return self._proc_version
        parts = relative_system_path.split("/")
        if (
            self._include_topology
            and len(parts) == 8
            and parts[1:5] == ["sys", "devices", "system", "cpu"]
            and parts[6] == "topology"
        ):
            name = parts[5]
            if not name.startswith("cpu") or not name[3:].isdigit():
                return None
            topology = _SIMULATED_TOPOLOGY.get(int(name[3:]))
            if topology is None:
                return None
            return topology.get(parts[7])
        return None

    def allowed_cpu_ids(self) -> tuple[int, ...]:
        return tuple(self._cpus)

    def platform_record(self) -> tuple[str, str, str]:
        return (self._system, self._machine, self._kernel)


class _Halted(Exception):
    """Internal classified stop; never leaves the controller as an exception."""

    def __init__(self, reason: StopReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class _Campaign:
    """One control or treatment campaign bound to a compiled schedule."""

    kind: str
    index: int
    schedule: CompiledSchedule


def _require_sample(value: object, field_path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"{field_path} must be a positive integer",
            field_path=field_path,
        )
    if value > MAX_SYNTHETIC_SAMPLE_NS:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"{field_path} exceeds the simulated nanosecond bound",
            field_path=field_path,
        )
    return value


def _require_synthetic_scope(origin: object, scope: object, field_path: str) -> None:
    if origin != SYNTHETIC_ORIGIN or scope != SIMULATED_SCOPE:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"{field_path} must remain synthetic/simulated",
            field_path=field_path,
        )


def validate_prepared_fixture(prepared: object, *, scenario_digest: str) -> PreparedFixture:
    """Independently validate one adapter preparation result."""

    if not isinstance(prepared, PreparedFixture):
        raise BenchError(
            BM_IDENTITY_INVALID, "prepare must return a PreparedFixture", field_path="prepare"
        )
    if prepared.fixture_id != FIXTURE_ID:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "unexpected synthetic fixture identity",
            field_path="prepare.fixture_id",
        )
    if prepared.digest != scenario_digest:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the prepared fixture must bind the frozen scenario digest",
            field_path="prepare.digest",
        )
    if prepared.status != FIXTURE_STATUS:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "prepare must report the prepared status",
            field_path="prepare.status",
        )
    _require_synthetic_scope(prepared.evidence_origin, prepared.qualification_scope, "prepare")
    return prepared


def validate_oracle_result(
    result: object, *, oracle_id: str, oracle_version: int
) -> OracleResult:
    """Independently validate one correctness oracle result."""

    if not isinstance(result, OracleResult):
        raise BenchError(
            BM_IDENTITY_INVALID, "check_oracle must return an OracleResult", field_path="oracle"
        )
    if result.oracle_id != oracle_id or result.oracle_version != oracle_version:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the oracle result must match the declared workload oracle",
            field_path="oracle",
        )
    if result.status not in ADAPTER_STATUSES:
        raise BenchError(
            BM_IDENTITY_INVALID, "oracle status is not declared", field_path="oracle.status"
        )
    _require_synthetic_scope(result.evidence_origin, result.qualification_scope, "oracle")
    return result


def validate_warmup_result(result: object, *, lane_id: str) -> WarmupResult:
    """Independently validate one warmup result for one declared lane."""

    if not isinstance(result, WarmupResult):
        raise BenchError(
            BM_IDENTITY_INVALID, "warmup must return a WarmupResult", field_path="warmup"
        )
    if result.lane_id != lane_id:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the warmup result must name the requested lane",
            field_path="warmup.lane_id",
        )
    if result.status != PASS_STATUS:
        raise BenchError(
            BM_IDENTITY_INVALID, "a warmup must report the pass status", field_path="warmup.status"
        )
    _require_synthetic_scope(result.evidence_origin, result.qualification_scope, "warmup")
    return result


def validate_measurement_result(
    result: object,
    *,
    lane_id: str,
    samples_per_lane_slot: int,
) -> MeasurementResult:
    """Independently validate one measurement envelope and its sample vector."""

    if not isinstance(result, MeasurementResult):
        raise BenchError(
            BM_IDENTITY_INVALID, "measure must return a MeasurementResult", field_path="measure"
        )
    if result.lane_id != lane_id:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the measurement envelope must name the requested lane",
            field_path="measure.lane_id",
        )
    if result.status != PASS_STATUS:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "a measurement must report the pass status",
            field_path="measure.status",
        )
    if result.unit != SYNTHETIC_METRIC_UNIT:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the measurement unit must be the synthetic nanosecond envelope",
            field_path="measure.unit",
        )
    if result.direction != LOWER_IS_BETTER:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the measurement direction must be lower-is-better",
            field_path="measure.direction",
        )
    _require_synthetic_scope(result.evidence_origin, result.qualification_scope, "measure")
    samples = result.samples
    if not isinstance(samples, tuple):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "measurement samples must be an immutable tuple",
            field_path="measure.samples",
        )
    if len(samples) != samples_per_lane_slot:
        raise BenchError(
            BM_IDENTITY_INVALID,
            f"measurement must return exactly {samples_per_lane_slot} samples",
            field_path="measure.samples",
        )
    for index, value in enumerate(samples):
        _require_sample(value, f"measure.samples[{index}]")
    return result


class _Run:
    """One in-memory execution attempt over one exclusive run directory."""

    def __init__(
        self,
        *,
        bundle: ExperimentBundle,
        scenario: SyntheticScenario,
        run_id: str,
        evidence_root: Path,
        output_base: Path,
        adapter_factory: SyntheticAdapterFactory,
        capability_provider: CapabilityProvider,
        readiness_provider: SyntheticReadinessProvider,
        clock: LogicalClock,
        faults: FaultPlan,
    ) -> None:
        self.bundle = bundle
        self.scenario = scenario
        self.run_id = run_id
        self.evidence_root = evidence_root
        self.adapter_factory = adapter_factory
        self.capability_provider = capability_provider
        self.readiness_provider = readiness_provider
        self.clock = clock
        self.faults = faults
        self.fault_consumed = False

        self.schedule = compile_schedule(bundle)
        self.control: ControlSchedule = build_control_schedule(
            bundle, control_source_arm_id=scenario.control_source_arm_id
        )
        self.campaigns_decl = read_protocol_campaigns(bundle)
        self.campaigns = self._build_campaigns()
        self.lane_ids = tuple(lane.lane_id for lane in bundle.workload.lanes)
        self.samples_per_lane_slot = bundle.protocol.samples_per_lane_slot
        self.warmups_per_lane_slot = bundle.protocol.warmups_per_lane_slot
        self._validate_budgets()
        self._validate_fault_targets()

        self.store = ExecutionStore.create(
            output_base,
            bundle.experiment.experiment_id,
            run_id,
            evidence_root=evidence_root,
            repo_root=repository_root(),
        )
        self.recorder = Recorder(self.store, run_id)
        self.state = RunState.PLANNED
        self._consumed_readiness: set[tuple[str, int]] = set()
        self._adapter_context = AdapterContext(
            experiment_id=bundle.experiment.experiment_id,
            run_id=run_id,
            lane_ids=self.lane_ids,
            evidence_origin=SYNTHETIC_ORIGIN,
            qualification_scope=SIMULATED_SCOPE,
        )
        self._freeze_document: Mapping[str, Any] | None = None
        self._freeze_digest = ""
        self._started = False
        self._slots_completed = 0
        self._lane_envelopes = 0
        self._synthetic_samples = 0

    # -- construction helpers ---------------------------------------------

    def _build_campaigns(self) -> tuple[_Campaign, ...]:
        campaigns: list[_Campaign] = []
        if self.control.status == "scheduled" and self.control.compiled is not None:
            for index in range(self.control.campaign_count):
                campaigns.append(
                    _Campaign(kind="control", index=index, schedule=self.control.compiled)
                )
        for index in range(self.campaigns_decl.required_treatments):
            campaigns.append(
                _Campaign(kind="treatment", index=index, schedule=self.schedule)
            )
        return tuple(campaigns)

    def _validate_budgets(self) -> None:
        control_campaigns = (
            self.control.campaign_count if self.control.status == "scheduled" else 0
        )
        control_compiled = self.control.compiled
        lanes = len(self.lane_ids)
        lane_slots = total_lane_slots(
            control_campaigns=control_campaigns,
            control_blocks=control_compiled.blocks if control_compiled else 0,
            control_slots_per_block=control_compiled.slots_per_block
            if control_compiled
            else 0,
            treatment_campaigns=self.campaigns_decl.required_treatments,
            blocks=self.schedule.blocks,
            slots_per_block=self.schedule.slots_per_block,
            lanes=lanes,
        )
        total_journal_records(
            state_events=2 + 2 * len(self.campaigns) + 1,
            readiness_records=len(self.campaigns),
            lane_envelopes=lane_slots,
            slot_completes=lane_slots // lanes if lanes else 0,
            control_reports=control_campaigns,
            warmup_calls=lane_slots * self.warmups_per_lane_slot,
        )

    def _validate_fault_targets(self) -> None:
        plan = self.faults
        if plan.point is None:
            return
        control_blocks = self.control.compiled.blocks if self.control.compiled else 0
        control_positions = (
            self.control.compiled.slots_per_block if self.control.compiled else 0
        )
        if plan.campaign_index is not None:
            if plan.campaign_kind == "control":
                limit = self.control.campaign_count
            elif plan.campaign_kind == "treatment":
                limit = self.campaigns_decl.required_treatments
            else:
                limit = max(
                    self.control.campaign_count,
                    self.campaigns_decl.required_treatments,
                )
            if plan.campaign_index >= limit:
                raise BenchError(
                    BM_IDENTITY_INVALID,
                    "the fault campaign target is outside the frozen schedule",
                    field_path="faults.campaign_index",
                )
        if plan.block is not None:
            if plan.block < 1 or plan.block > max(self.schedule.blocks, control_blocks):
                raise BenchError(
                    BM_IDENTITY_INVALID,
                    "the fault block target is outside the frozen schedule",
                    field_path="faults.block",
                )
        if plan.position is not None:
            limit = max(self.schedule.slots_per_block, control_positions)
            if plan.position < 1 or plan.position > limit:
                raise BenchError(
                    BM_IDENTITY_INVALID,
                    "the fault position target is outside the frozen schedule",
                    field_path="faults.position",
                )
        if plan.lane_id is not None and plan.lane_id not in self.lane_ids:
            raise BenchError(
                BM_IDENTITY_INVALID,
                "the fault lane target is not a declared lane",
                field_path="faults.lane_id",
            )

    # -- journal ----------------------------------------------------------

    def _transition(self, target: RunState, reason: str) -> None:
        check_transition(self.state, target, reason)
        self.recorder.write_event(
            from_state=self.state,
            to_state=target,
            reason=reason,
            logical_ns=self.clock.now_ns(),
        )
        self.state = target

    def _halt(self, reason: StopReason, message: str) -> None:
        raise _Halted(reason, message)

    def _take_fault(
        self,
        point: FaultPoint,
        *,
        campaign_kind: str | None = None,
        campaign_index: int | None = None,
        block: int | None = None,
        position: int | None = None,
        lane_id: str | None = None,
    ) -> bool:
        plan = self.faults
        if self.fault_consumed or plan.point is not point:
            return False
        if plan.campaign_kind is not None and plan.campaign_kind != campaign_kind:
            return False
        if plan.campaign_index is not None and plan.campaign_index != campaign_index:
            return False
        if plan.block is not None and plan.block != block:
            return False
        if plan.position is not None and plan.position != position:
            return False
        if plan.lane_id is not None and plan.lane_id != lane_id:
            return False
        self.fault_consumed = True
        return True

    # -- publication ------------------------------------------------------

    def _publish_plan(self) -> None:
        self.recorder.write_event(
            from_state="none",
            to_state=RunState.PLANNED,
            reason="new-run",
            logical_ns=self.clock.now_ns(),
        )
        self._started = True
        if self._take_fault(FaultPoint.BEFORE_FREEZE_PUBLISH):
            self._halt(StopReason.FREEZE_MISSING, "freeze publication failed")
        self.store.write_new("schedule.json", make_schedule_document(self.schedule))
        self.store.write_new("control-schedule.json", dict(self.control.document))
        document, digest = build_freeze_document(
            bundle=self.bundle,
            run_id=self.run_id,
            schedule=self.schedule,
            control_schedule=self.control,
            scenario_digest=self.scenario.scenario_digest,
        )
        self.store.write_new("freeze.json", document)
        record = validate_freeze_document(self._read_document("freeze.json"))
        if record.freeze_digest != digest:
            self._halt(StopReason.FREEZE_MISMATCH, "the published freeze digest is wrong")
        self._freeze_document = document
        self._freeze_digest = digest
        self._transition(RunState.FROZEN, "freeze-published")

    def _read_document(self, relative: str) -> Mapping[str, Any]:
        payload = self.store.read_raw(relative)
        document = loads_json(decode_text(payload))
        if canonical_document_bytes(document) != payload:
            self._halt(
                StopReason.UNSAFE_ARTIFACT,
                f"stored record {relative!r} is not in canonical byte form",
            )
        if not isinstance(document, Mapping):
            self._halt(
                StopReason.UNSAFE_ARTIFACT, f"stored record {relative!r} is not an object"
            )
        return document

    # -- host capability --------------------------------------------------

    def _require_capabilities(self) -> None:
        if not isinstance(self.capability_provider, CapabilityProvider):
            self._halt(
                StopReason.HOST_NOT_READY, "the injected capability provider is not usable"
            )
        record = collect_host_capabilities(self.capability_provider)
        validate_host_capabilities(record)
        if (
            record["environment"] == "unsupported"
            or record["missing_fields"]
            or not record["allowed_cpus"]
        ):
            self._halt(
                StopReason.HOST_NOT_READY,
                "the simulated host capability snapshot is not ready",
            )

    # -- readiness --------------------------------------------------------

    def _require_readiness(self, campaign: _Campaign) -> None:
        key = (campaign.kind, campaign.index)
        if key in self._consumed_readiness:
            self._halt(
                StopReason.HOST_NOT_READY, "a simulated readiness batch was requested twice"
            )
        if self._take_fault(
            FaultPoint.BEFORE_READINESS,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
        ):
            self._halt(StopReason.HOST_NOT_READY, "readiness observation failed")
        if not callable(getattr(self.readiness_provider, "next_observations", None)):
            self._halt(
                StopReason.HOST_NOT_READY, "the injected readiness provider is not usable"
            )
        try:
            observations = tuple(
                self.readiness_provider.next_observations(campaign.kind, campaign.index)
            )
        except BenchError:
            self._halt(
                StopReason.HOST_NOT_READY,
                "the injected readiness provider refused this campaign",
            )
        self._consumed_readiness.add(key)
        expected = self.scenario.readiness_for(campaign.kind, campaign.index)
        if self._take_fault(
            FaultPoint.READINESS_BLOCKED,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
        ):
            observations = (ReadinessObservation(5, 900, 500),)
        elif observations != tuple(expected):
            self._halt(
                StopReason.HOST_NOT_READY,
                "the readiness provider did not return the declared campaign batch",
            )
        diagnostic = evaluate_readiness(SYNTHETIC_READINESS_LIMITS, observations)
        self.recorder.write_readiness(
            build_readiness_document(
                campaign_kind=campaign.kind,
                campaign_index=campaign.index,
                limits=SYNTHETIC_READINESS_LIMITS,
                observations=observations,
                diagnostic=diagnostic,
            )
        )
        if diagnostic.status != "clear":
            self._halt(
                StopReason.HOST_NOT_READY,
                "the simulated host was not ready for this campaign",
            )

    # -- slot execution ---------------------------------------------------

    def _assignment(self, campaign: _Campaign, slot: ScheduleSlot) -> ArmAssignment:
        variants = {arm.arm_id: arm.variant for arm in self.bundle.experiment.arms}
        if campaign.kind == "control":
            source = self.control.source_arm_id
            return ArmAssignment(
                display_arm_id=slot.arm_id,
                declared_arm_id=source,
                variant=variants[source],
                campaign_kind="control",
            )
        return ArmAssignment(
            display_arm_id=slot.arm_id,
            declared_arm_id=slot.arm_id,
            variant=variants[slot.arm_id],
            campaign_kind="treatment",
        )

    def _slot_key(self, campaign: _Campaign, slot: ScheduleSlot) -> SlotKey:
        return SlotKey(
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
            ordinal=slot.ordinal,
        )

    def _cleanup(self, adapter: BenchmarkAdapter, prepared: PreparedFixture) -> None:
        try:
            adapter.cleanup(self._adapter_context, prepared)
        except _Halted:
            raise
        except Exception as exc:  # noqa: BLE001 - classified as an adapter failure
            raise _Halted(StopReason.ADAPTER_FAILURE, "adapter cleanup failed") from exc

    def _execute_slot(
        self, campaign: _Campaign, slot: ScheduleSlot, adapter: BenchmarkAdapter
    ) -> tuple[tuple[str, str], ...]:
        assignment = self._assignment(campaign, slot)
        slot_key = self._slot_key(campaign, slot)
        if not isinstance(adapter, SyntheticAdapter):
            raise BenchError(
                BM_ACQUISITION_PROHIBITED,
                "BM-03 only executes the known synthetic adapter implementation",
                field_path="adapter_factory",
            )
        del slot_key  # the factory already received this exact slot identity
        try:
            prepared = adapter.prepare(self._adapter_context)
        except _Halted:
            raise
        except Exception as exc:  # noqa: BLE001 - classified as an adapter failure
            raise _Halted(StopReason.ADAPTER_FAILURE, "adapter preparation failed") from exc
        try:
            validate_prepared_fixture(
                prepared, scenario_digest=self.scenario.scenario_digest
            )
        except BenchError:
            self._halt(StopReason.ADAPTER_FAILURE, "adapter preparation is not usable")

        try:
            self._require_oracle(campaign, slot, adapter, prepared)
            lanes = tuple(
                self._execute_lane(campaign, slot, adapter, prepared, lane)
                for lane in self.bundle.workload.lanes
            )
        except _Halted:
            self._cleanup(adapter, prepared)
            raise
        except BenchError:
            self._cleanup(adapter, prepared)
            raise
        self._cleanup(adapter, prepared)

        if self._take_fault(
            FaultPoint.BEFORE_SLOT_PUBLISH,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
        ):
            self._halt(StopReason.CRASH_INTERRUPTED, "slot completion publication failed")
        self.recorder.write_slot_complete(
            build_slot_complete_document(
                run_id=self.run_id,
                campaign_kind=campaign.kind,
                campaign_index=campaign.index,
                block=slot.block,
                position=slot.position,
                ordinal=slot.ordinal,
                arm_id=assignment.display_arm_id,
                declared_arm_id=assignment.declared_arm_id,
                lanes=lanes,
            )
        )
        self._slots_completed += 1
        if self._take_fault(
            FaultPoint.AFTER_SLOT_PUBLISH,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
        ):
            self._halt(
                StopReason.CRASH_INTERRUPTED, "execution stopped after slot publication"
            )
        return lanes

    def _require_oracle(
        self,
        campaign: _Campaign,
        slot: ScheduleSlot,
        adapter: BenchmarkAdapter,
        prepared: PreparedFixture,
    ) -> None:
        if self._take_fault(
            FaultPoint.BEFORE_ORACLE,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
        ):
            self._halt(StopReason.ADAPTER_FAILURE, "the oracle step was interrupted")
        try:
            oracle = adapter.check_oracle(self._adapter_context, prepared)
        except _Halted:
            raise
        except Exception as exc:  # noqa: BLE001 - classified as an adapter failure
            raise _Halted(StopReason.ADAPTER_FAILURE, "the oracle step failed") from exc
        if self._take_fault(
            FaultPoint.ORACLE_FAIL,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
        ):
            oracle = replace(oracle, status="fail")
        try:
            validated = validate_oracle_result(
                oracle,
                oracle_id=self.bundle.workload.oracle_id,
                oracle_version=self.bundle.workload.oracle_version,
            )
        except BenchError:
            self._halt(StopReason.ADAPTER_FAILURE, "the oracle result is not usable")
        if validated.status != PASS_STATUS:
            self._halt(
                StopReason.ORACLE_FAILED,
                "the correctness oracle did not pass before warmup",
            )

    def _execute_lane(
        self,
        campaign: _Campaign,
        slot: ScheduleSlot,
        adapter: BenchmarkAdapter,
        prepared: PreparedFixture,
        lane: Lane,
    ) -> tuple[str, str]:
        assignment = self._assignment(campaign, slot)
        start = self.clock.now_ns()
        for warmup_index in range(self.warmups_per_lane_slot):
            if self._take_fault(
                FaultPoint.BEFORE_WARMUP,
                campaign_kind=campaign.kind,
                campaign_index=campaign.index,
                block=slot.block,
                position=slot.position,
                lane_id=lane.lane_id,
            ):
                self._halt(StopReason.ADAPTER_FAILURE, "the warmup step was interrupted")
            try:
                warmup = adapter.warmup(self._adapter_context, prepared, lane)
            except _Halted:
                raise
            except Exception as exc:  # noqa: BLE001 - classified as an adapter failure
                raise _Halted(StopReason.ADAPTER_FAILURE, "adapter warmup failed") from exc
            if warmup_index == 0 and self._take_fault(
                FaultPoint.WARMUP_ERROR,
                campaign_kind=campaign.kind,
                campaign_index=campaign.index,
                block=slot.block,
                position=slot.position,
                lane_id=lane.lane_id,
            ):
                warmup = replace(warmup, status="error")
            try:
                validate_warmup_result(warmup, lane_id=lane.lane_id)
            except BenchError:
                self._halt(StopReason.ADAPTER_FAILURE, "adapter warmup is not usable")
            self.clock.advance_ns(1)

        if self._take_fault(
            FaultPoint.BEFORE_MEASURE,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
            lane_id=lane.lane_id,
        ):
            self._halt(StopReason.ADAPTER_FAILURE, "the measurement step was interrupted")
        try:
            measurement = adapter.measure(self._adapter_context, prepared, lane)
        except _Halted:
            raise
        except Exception as exc:  # noqa: BLE001 - classified as an adapter failure
            raise _Halted(StopReason.ADAPTER_FAILURE, "adapter measurement failed") from exc
        measurement = self._inject_measurement_fault(campaign, slot, lane, measurement)
        try:
            validated = validate_measurement_result(
                measurement,
                lane_id=lane.lane_id,
                samples_per_lane_slot=self.samples_per_lane_slot,
            )
        except BenchError:
            self._halt(StopReason.INVALID_MEASUREMENT, "the measurement envelope is invalid")
        samples = tuple(validated.samples or ())
        self.clock.advance_ns(sum(samples))
        end = self.clock.now_ns()

        document = build_lane_envelope_document(
            run_id=self.run_id,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
            ordinal=slot.ordinal,
            arm_id=assignment.display_arm_id,
            declared_arm_id=assignment.declared_arm_id,
            lane_id=lane.lane_id,
            oracle_id=self.bundle.workload.oracle_id,
            oracle_version=self.bundle.workload.oracle_version,
            fixture_digest=self.scenario.scenario_digest,
            warmup_calls=self.warmups_per_lane_slot,
            samples=samples,
            logical_start_ns=start,
            logical_end_ns=end,
        )
        if self._take_fault(
            FaultPoint.BEFORE_LANE_PUBLISH,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
            lane_id=lane.lane_id,
        ):
            self._halt(StopReason.CRASH_INTERRUPTED, "lane publication failed")
        self.recorder.write_lane_envelope(document)
        self._lane_envelopes += 1
        self._synthetic_samples += len(samples)
        if self._take_fault(
            FaultPoint.AFTER_LANE_PUBLISH,
            campaign_kind=campaign.kind,
            campaign_index=campaign.index,
            block=slot.block,
            position=slot.position,
            lane_id=lane.lane_id,
        ):
            self._halt(
                StopReason.CRASH_INTERRUPTED, "execution stopped after lane publication"
            )
        return (lane.lane_id, content_digest(document))

    def _inject_measurement_fault(
        self,
        campaign: _Campaign,
        slot: ScheduleSlot,
        lane: Lane,
        measurement: MeasurementResult,
    ) -> MeasurementResult:
        targets = {
            "campaign_kind": campaign.kind,
            "campaign_index": campaign.index,
            "block": slot.block,
            "position": slot.position,
            "lane_id": lane.lane_id,
        }
        transformations = (
            (FaultPoint.MEASUREMENT_ERROR, lambda m: replace(m, status="error")),
            (
                FaultPoint.MEASUREMENT_WRONG_COUNT,
                lambda m: replace(m, samples=tuple(m.samples or ())[:-1]),
            ),
            (FaultPoint.MEASUREMENT_WRONG_UNIT, lambda m: replace(m, unit="bytes")),
            (
                FaultPoint.MEASUREMENT_WRONG_SCOPE,
                lambda m: replace(m, qualification_scope="official"),
            ),
        )
        for point, transform in transformations:
            if self._take_fault(point, **targets):
                return transform(measurement)
        return measurement

    # -- control verification ---------------------------------------------

    def _verify_control(self, campaign: _Campaign) -> None:
        positions: dict[int, dict[str, int]] = {}
        for slot in campaign.schedule.slots:
            positions.setdefault(slot.block, {})[slot.arm_id] = slot.position
        pairs = 0
        for block in sorted(positions):
            by_arm = positions[block]
            if set(by_arm) != {CONTROL_LEFT_ARM_ID, CONTROL_RIGHT_ARM_ID}:
                self._halt(
                    StopReason.CONTROL_MISMATCH,
                    "the control block does not declare both frozen aliases",
                )
            for lane in self.bundle.workload.lanes:
                left = validate_lane_envelope_document(
                    self._read_document(
                        lane_relative_path(
                            campaign.kind,
                            campaign.index,
                            block,
                            by_arm[CONTROL_LEFT_ARM_ID],
                            lane.lane_id,
                        )
                    )
                )
                right = validate_lane_envelope_document(
                    self._read_document(
                        lane_relative_path(
                            campaign.kind,
                            campaign.index,
                            block,
                            by_arm[CONTROL_RIGHT_ARM_ID],
                            lane.lane_id,
                        )
                    )
                )
                pairs += 1
                if left.samples != right.samples:
                    self._halt(
                        StopReason.CONTROL_MISMATCH,
                        "the synthetic A/A replicas are not identical",
                    )
        self.recorder.write_control_report(
            build_control_report_document(
                campaign_index=campaign.index,
                control_contract_id=CONTROL_CONTRACT_ID,
                source_arm_id=self.control.source_arm_id,
                checked_pairs=pairs,
                lane_ids=self.lane_ids,
            )
        )

    # -- inventory and seal -----------------------------------------------

    def _expected_paths(self) -> tuple[str, ...]:
        paths: list[str] = ["schedule.json", "control-schedule.json", "freeze.json"]
        events = 2 + 2 * len(self.campaigns) + 1
        paths.extend(event_relative_path(sequence) for sequence in range(1, events + 1))
        for campaign in self.campaigns:
            paths.append(readiness_relative_path(campaign.kind, campaign.index))
            for slot in campaign.schedule.slots:
                for lane_id in self.lane_ids:
                    paths.append(
                        lane_relative_path(
                            campaign.kind,
                            campaign.index,
                            slot.block,
                            slot.position,
                            lane_id,
                        )
                    )
                paths.append(
                    slot_complete_relative_path(
                        campaign.kind, campaign.index, slot.block, slot.position
                    )
                )
            if campaign.kind == "control":
                paths.append(control_relative_path(campaign.index))
        return tuple(sorted(paths))

    def _collect_files(self) -> tuple[tuple[str, str, int], ...]:
        existing = self.store.list_existing()
        if SEAL_NAME in existing:  # pragma: no cover - seal is written once
            self._halt(StopReason.OUTPUT_CONFLICT, "the completion seal already exists")
        expected = self._expected_paths()
        if tuple(existing) != expected:
            missing = sorted(set(expected) - set(existing))
            if missing:
                self._halt(
                    StopReason.MISSING_SLOT,
                    f"the run is missing a required record: {missing[0]}",
                )
            extra = sorted(set(existing) - set(expected))
            self._halt(
                StopReason.UNSAFE_ARTIFACT,
                f"the run contains an unexpected record: {extra[0]}",
            )
        files: list[tuple[str, str, int]] = []
        for relative in existing:
            payload = self.store.read_raw(relative)
            files.append((relative, sha256_prefix(payload), len(payload)))
        return tuple(files)

    def _require_inputs_unchanged(self) -> None:
        try:
            scenario_digest = reopen_scenario_digest(self.evidence_root)
        except BenchError:
            self._halt(StopReason.INPUT_MUTATED, "the scenario fixture cannot be reopened")
        if scenario_digest != self.scenario.scenario_digest:
            self._halt(
                StopReason.INPUT_MUTATED, "the scenario fixture changed after freeze"
            )
        try:
            record = validate_freeze_document(self._freeze_document or {})
        except BenchError:
            self._halt(StopReason.FREEZE_MISSING, "the frozen payload is unavailable")
        try:
            verify_freeze_bindings(
                record,
                bundle=self.bundle,
                schedule=self.schedule,
                control_schedule=self.control,
                scenario_digest=scenario_digest,
            )
        except BenchError:
            self._halt(
                StopReason.FREEZE_MISMATCH, "a frozen binding changed after freeze"
            )
        try:
            validate_schedule_document(self._read_document("schedule.json"))
        except BenchError:
            self._halt(StopReason.FREEZE_MISMATCH, "the stored schedule is invalid")

    def _seal(self) -> str:
        if self._take_fault(FaultPoint.BEFORE_SEAL):
            self._halt(StopReason.CRASH_INTERRUPTED, "seal publication was interrupted")
        self._require_inputs_unchanged()
        files = self._collect_files()
        control_campaigns = (
            self.control.campaign_count if self.control.status == "scheduled" else 0
        )
        document = build_seal_document(
            run_id=self.run_id,
            experiment_id=self.bundle.experiment.experiment_id,
            freeze_digest=self._freeze_digest,
            schedule_digest=self.schedule.schedule_digest,
            scenario_digest=self.scenario.scenario_digest,
            controls_completed=control_campaigns,
            treatments_completed=self.campaigns_decl.required_treatments,
            slots_completed=self._slots_completed,
            lane_envelopes=self._lane_envelopes,
            synthetic_samples=self._synthetic_samples,
            last_logical_ns=self.clock.now_ns(),
            files=files,
        )
        return self.store.commit_seal(document)

    # -- main sequence ----------------------------------------------------

    def execute(self) -> ExecutionResult:
        try:
            return self._execute()
        except _Halted as halt:
            return self._terminate(halt.reason, halt.message)
        except BenchError:
            self._mark_failed()
            raise
        except Exception as exc:  # noqa: BLE001 - never claim success on a defect
            self._mark_failed()
            raise internal_error() from exc

    def _terminate(self, reason: StopReason, message: str) -> ExecutionResult:
        del message
        if self._started:
            try:
                check_transition(self.state, RunState.STOPPED, reason.value)
                self.recorder.write_event(
                    from_state=self.state,
                    to_state=RunState.STOPPED,
                    reason=reason.value,
                    logical_ns=self.clock.now_ns(),
                )
                self.state = RunState.STOPPED
            except BenchError:
                self._mark_failed()
                raise
        return ExecutionResult(
            status="stopped",
            run_dir=self.store.run_dir,
            run_id=self.run_id,
            freeze_digest=self._freeze_digest,
            schedule_digest=self.schedule.schedule_digest,
            seal_digest=None,
            reason=reason.value,
        )

    def _mark_failed(self) -> None:
        if not self._started or self.state in (RunState.STOPPED, RunState.FAILED):
            return
        try:
            check_transition(
                self.state, RunState.FAILED, StopReason.UNEXPECTED_FAILURE.value
            )
            self.recorder.write_event(
                from_state=self.state,
                to_state=RunState.FAILED,
                reason=StopReason.UNEXPECTED_FAILURE.value,
                logical_ns=self.clock.now_ns(),
            )
        except Exception:  # noqa: BLE001 - a failed journal must not mask the cause
            pass
        self.state = RunState.FAILED

    def _execute(self) -> ExecutionResult:
        self._publish_plan()
        self._require_capabilities()
        for position, campaign in enumerate(self.campaigns):
            expected_state = RunState.FROZEN if position == 0 else RunState.ACQUIRING
            if self.state is not expected_state:  # pragma: no cover - defensive
                self._halt(
                    StopReason.UNEXPECTED_FAILURE,
                    "the campaign loop lost its expected state",
                )
            self._require_readiness(campaign)
            self._transition(RunState.READY, "readiness-clear")
            acquiring = False
            for slot in campaign.schedule.slots:
                if not acquiring:
                    self._transition(RunState.ACQUIRING, "slot-acquiring")
                    acquiring = True
                adapter = self._create_adapter(campaign, slot)
                self._execute_slot(campaign, slot, adapter)
            if campaign.kind == "control":
                self._verify_control(campaign)
        self._transition(RunState.COMPLETED, "campaigns-complete")
        seal_digest = self._seal()
        self.state = RunState.SEALED
        return ExecutionResult(
            status="sealed",
            run_dir=self.store.run_dir,
            run_id=self.run_id,
            freeze_digest=self._freeze_digest,
            schedule_digest=self.schedule.schedule_digest,
            seal_digest=seal_digest,
            reason=None,
        )

    def _create_adapter(self, campaign: _Campaign, slot: ScheduleSlot) -> BenchmarkAdapter:
        assignment = self._assignment(campaign, slot)
        slot_key = self._slot_key(campaign, slot)
        try:
            return self.adapter_factory(assignment, slot_key, self.scenario)
        except _Halted:
            raise
        except Exception as exc:  # noqa: BLE001 - classified as an adapter failure
            raise _Halted(StopReason.ADAPTER_FAILURE, "the adapter factory failed") from exc


def execute_synthetic(
    *,
    bundle: ExperimentBundle,
    scenario: SyntheticScenario,
    run_id: str,
    evidence_root: Path,
    output_base: Path,
    adapter_factory: SyntheticAdapterFactory,
    capability_provider: CapabilityProvider,
    readiness_provider: SyntheticReadinessProvider,
    clock: LogicalClock,
    faults: FaultPlan = FaultPlan(),
) -> ExecutionResult:
    """Execute one complete synthetic run through the single controller path.

    This is an internal, importable Python entry point. It is not reachable from
    ``quervant-bench run``, HTTP, a subprocess or any public CLI verb.
    """

    if not isinstance(bundle, ExperimentBundle):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "a validated ExperimentBundle is required",
            field_path="bundle",
        )
    require_synthetic_bundle(bundle)
    if not isinstance(scenario, SyntheticScenario):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "a loaded SyntheticScenario is required",
            field_path="scenario",
        )
    validate_uuid4(run_id, "run_id")
    if not isinstance(clock, LogicalClock):
        raise BenchError(
            BM_IDENTITY_INVALID, "an injected LogicalClock is required", field_path="clock"
        )
    if not isinstance(faults, FaultPlan):
        raise BenchError(
            BM_IDENTITY_INVALID, "faults must be a FaultPlan", field_path="faults"
        )
    if not callable(adapter_factory):
        raise BenchError(
            BM_IDENTITY_INVALID,
            "an injected adapter factory is required",
            field_path="adapter_factory",
        )
    if (
        bundle.protocol.metric_unit != SYNTHETIC_METRIC_UNIT
        or bundle.adapter.measurement_envelope.unit != SYNTHETIC_METRIC_UNIT
        or bundle.adapter.measurement_envelope.direction != LOWER_IS_BETTER
        or scenario.metric_unit != SYNTHETIC_METRIC_UNIT
    ):
        raise BenchError(
            BM_NOT_IMPLEMENTED,
            "BM-03 execution supports only the synthetic lower-is-better nanosecond envelope",
            field_path="measurement.metric_unit",
        )
    if scenario.experiment_id != bundle.experiment.experiment_id:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "scenario and bundle experiment identities must match",
            field_path="scenario.experiment_id",
        )
    # Re-validate the closed scenario against the exact bundle before any writing.
    validate_scenario_document(dict(scenario.document), bundle=bundle)
    if (
        scenario.evidence_origin != SYNTHETIC_ORIGIN
        or scenario.qualification_scope != SIMULATED_SCOPE
    ):
        raise BenchError(
            BM_ACQUISITION_PROHIBITED,
            "BM-03 only executes synthetic/simulated scenarios",
            field_path="scenario.qualification_scope",
        )
    if not isinstance(evidence_root, Path) or not isinstance(output_base, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "evidence_root and output_base must be Path instances",
            field_path="paths",
        )
    # Pre-publication identity check: the canonical scenario at the supplied
    # evidence root must be exactly the frozen in-memory scenario, and this must
    # be established before any run directory, provider or adapter call.
    source_digest = reopen_scenario_digest(evidence_root)
    if source_digest != scenario.scenario_digest:
        raise BenchError(
            BM_IDENTITY_INVALID,
            "the evidence-root scenario differs from the supplied frozen scenario",
            field_path="scenario.scenario_digest",
        )
    return _Run(
        bundle=bundle,
        scenario=scenario,
        run_id=run_id,
        evidence_root=evidence_root,
        output_base=output_base,
        adapter_factory=adapter_factory,
        capability_provider=capability_provider,
        readiness_provider=readiness_provider,
        clock=clock,
        faults=faults,
    ).execute()


__all__ = [
    "ScenarioReadinessProvider",
    "SimulatedCapabilityProvider",
    "SyntheticReadinessProvider",
    "execute_synthetic",
    "validate_measurement_result",
    "validate_oracle_result",
    "validate_prepared_fixture",
    "validate_warmup_result",
]

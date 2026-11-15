"""Frozen BM-03 budgets, enums and internal records.

This module owns the **simulator safety budgets** and the internal state/stop
vocabulary shared by the protocol compiler, the synthetic adapter, the evidence
store, the controller and the read-only replayer. None of these values is an
official measurement policy, a Gate A-E threshold or a release parameter: they
only bound a deterministic Python simulation.

The numbers are declared exactly once here and imported everywhere else so that
validation, publication and replay can never disagree about a limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..config.errors import BM_IDENTITY_INVALID, BenchError

# ---------------------------------------------------------------------------
# Resource budgets (synthetic simulator safety limits, not policy)
# ---------------------------------------------------------------------------

MAX_ARMS = 16
MAX_LANES = 64
MAX_BLOCKS = 256
MAX_SLOTS_PER_BLOCK = 16
MAX_CONTROL_CAMPAIGNS = 4
MAX_TREATMENT_CAMPAIGNS = 8
MAX_WARMUPS_PER_LANE_SLOT = 32
MAX_SAMPLES_PER_LANE_SLOT = 256
MAX_TOTAL_LANE_SLOTS = 50_000
MAX_SYNTHETIC_SAMPLE_NS = 9_223_372_036_854_775_807
MAX_CANONICAL_RECORD_BYTES = 1_048_576
MAX_SCENARIO_BYTES = 1_048_576
MAX_EVENT_RECORDS = 150_000
MAX_LOGICAL_NS = 9_223_372_036_854_775_807

# ---------------------------------------------------------------------------
# Frozen internal identifiers
# ---------------------------------------------------------------------------

SYNTHETIC_ORIGIN = "synthetic"
SIMULATED_SCOPE = "simulated"
SYNTHETIC_METRIC_UNIT = "nanoseconds"
SYNTHETIC_DIRECTION = "lower-is-better"
SYNTHETIC_CLOCK_CONTRACT_ID = "synthetic-logical-clock"
SYNTHETIC_ADAPTER_ID = "synthetic-execution"
SYNTHETIC_ADAPTER_VERSION = 1
CONTROL_CONTRACT_ID = "synthetic-exact-equality"
CONTROL_LEFT_ARM_ID = "control-left"
CONTROL_RIGHT_ARM_ID = "control-right"
CONTROL_STATUS_SCHEDULED = "scheduled"
CONTROL_STATUS_NOT_REQUIRED = "not-required"
SCENARIO_RELATIVE_NAME = "synthetic-scenario.v1.json"
SCENARIO_SCHEMA_VERSION = 1
INTERNAL_SCHEMA_VERSION = 1

#: ``control`` is the only A/A kind; ``treatment`` is every declared arm.
CAMPAIGN_KINDS: tuple[str, ...] = ("control", "treatment")


def _fail(message: str, field_path: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


def require_positive_int(value: object, field_path: str) -> int:
    """Validate a strictly positive integer and reject booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{field_path} must be an integer", field_path)
    if value < 1:
        raise _fail(f"{field_path} must be positive", field_path)
    return value


def require_bounded_nanoseconds(value: object, field_path: str) -> int:
    """Validate one positive simulated nanosecond sample."""

    observed = require_positive_int(value, field_path)
    if observed > MAX_SYNTHETIC_SAMPLE_NS:
        raise _fail(
            f"{field_path} exceeds the simulated nanosecond bound", field_path
        )
    return observed


def total_lane_slots(
    *,
    control_campaigns: int,
    control_blocks: int,
    control_slots_per_block: int,
    treatment_campaigns: int,
    blocks: int,
    slots_per_block: int,
    lanes: int,
) -> int:
    """Return the product ``slots * lanes`` after verifying the hard budget."""

    campaigns_slots = (
        control_campaigns * control_blocks * control_slots_per_block
        + treatment_campaigns * blocks * slots_per_block
    )
    total = campaigns_slots * lanes
    if total > MAX_TOTAL_LANE_SLOTS:
        raise _fail(
            f"lane/slot product {total} exceeds the {MAX_TOTAL_LANE_SLOTS} budget",
            "schedule.blocks",
        )
    return total


def total_journal_records(
    *,
    state_events: int,
    readiness_records: int,
    lane_envelopes: int,
    slot_completes: int,
    control_reports: int,
    warmup_calls: int,
    fixed_records: int = 4,
) -> int:
    """Return a conservative journal record count and enforce the event budget."""

    total = (
        state_events
        + readiness_records
        + lane_envelopes
        + slot_completes
        + control_reports
        + warmup_calls
        + fixed_records
    )
    if total > MAX_EVENT_RECORDS:
        raise _fail(
            f"journal record count {total} exceeds the {MAX_EVENT_RECORDS} budget",
            "schedule.blocks",
        )
    return total


# ---------------------------------------------------------------------------
# Run state and stop vocabulary
# ---------------------------------------------------------------------------


class RunState(str, Enum):
    """Mutable persisted run states; ``verified`` is a read-only replay result."""

    PLANNED = "planned"
    FROZEN = "frozen"
    READY = "ready"
    ACQUIRING = "acquiring"
    COMPLETED = "completed"
    SEALED = "sealed"
    STOPPED = "stopped"
    FAILED = "failed"


class StopReason(str, Enum):
    """Internal stop reasons persisted in the journal; not BM-01 error codes."""

    FREEZE_MISSING = "freeze-missing"
    FREEZE_MISMATCH = "freeze-mismatch"
    HOST_NOT_READY = "host-not-ready"
    CONTROL_MISMATCH = "control-mismatch"
    ORACLE_FAILED = "oracle-failed"
    ADAPTER_FAILURE = "adapter-failure"
    INVALID_MEASUREMENT = "invalid-measurement"
    MISSING_SLOT = "missing-slot"
    DUPLICATE_SLOT = "duplicate-slot"
    MISSING_CAMPAIGN = "missing-campaign"
    OUTPUT_CONFLICT = "output-conflict"
    INPUT_MUTATED = "input-mutated"
    UNSAFE_ARTIFACT = "unsafe-artifact"
    CRASH_INTERRUPTED = "crash-interrupted"
    UNEXPECTED_FAILURE = "unexpected-failure"


#: Closed set of transition reasons written by the controller.
TRANSITION_REASONS: frozenset[str] = frozenset(
    {
        "new-run",
        "freeze-published",
        "readiness-clear",
        "slot-acquiring",
        "campaigns-complete",
    }
)

STOP_REASONS: frozenset[str] = frozenset(reason.value for reason in StopReason)

#: Closed, persisted set of event reasons (transitions plus classified stops).
EVENT_REASONS: frozenset[str] = TRANSITION_REASONS | STOP_REASONS

_TERMINAL = frozenset({RunState.SEALED, RunState.STOPPED, RunState.FAILED})

#: The exact frozen transition table (§8.1). ``COMPLETED -> SEALED`` is absent on
#: purpose: the seal marker itself is the only durable sealed transition.
ALLOWED_TRANSITIONS: dict[tuple[RunState, RunState], str] = {
    (RunState.PLANNED, RunState.FROZEN): "freeze-published",
    (RunState.FROZEN, RunState.READY): "readiness-clear",
    (RunState.READY, RunState.ACQUIRING): "slot-acquiring",
    (RunState.ACQUIRING, RunState.READY): "readiness-clear",
    (RunState.ACQUIRING, RunState.COMPLETED): "campaigns-complete",
}


def is_terminal(state: RunState) -> bool:
    """Return whether ``state`` can never leave itself."""

    return state in _TERMINAL


def check_transition(current: RunState, target: RunState, reason: str) -> None:
    """Validate one ``current -> target`` transition, including its reason."""

    if target == RunState.SEALED:
        raise _fail(
            "the sealed state is published only by the store completion marker",
            "state",
        )
    if is_terminal(current):
        raise _fail(
            f"{current.value} is terminal and can never transition again", "state"
        )
    if target in (RunState.STOPPED, RunState.FAILED):
        expected = (
            STOP_REASONS if target == RunState.STOPPED else {StopReason.UNEXPECTED_FAILURE.value}
        )
        if reason not in expected:
            raise _fail(
                f"a {target.value} transition requires a classified reason", "reason"
            )
        return
    allowed_reason = ALLOWED_TRANSITIONS.get((current, target))
    if allowed_reason is None:
        raise _fail(
            f"transition {current.value} -> {target.value} is not permitted", "state"
        )
    if allowed_reason != reason:
        raise _fail(
            f"transition {current.value} -> {target.value} requires reason "
            f"{allowed_reason!r}",
            "reason",
        )


# ---------------------------------------------------------------------------
# Internal records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotKey:
    """One exact schedule slot identity inside one campaign."""

    campaign_kind: str
    campaign_index: int
    block: int
    position: int
    ordinal: int

    def __post_init__(self) -> None:
        if self.campaign_kind not in CAMPAIGN_KINDS:
            raise _fail("campaign_kind must be control or treatment", "campaign_kind")
        for name, value in (
            ("campaign_index", self.campaign_index),
            ("block", self.block),
            ("position", self.position),
            ("ordinal", self.ordinal),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise _fail(f"{name} must be a non-negative integer", name)


@dataclass(frozen=True)
class ArmAssignment:
    """The arm identity handed to the injected adapter factory."""

    display_arm_id: str
    declared_arm_id: str
    variant: str
    campaign_kind: str

    def __post_init__(self) -> None:
        if self.campaign_kind not in CAMPAIGN_KINDS:
            raise _fail("campaign_kind must be control or treatment", "campaign_kind")
        for name in ("display_arm_id", "declared_arm_id", "variant"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise _fail(f"{name} must be a non-empty string", name)


class FaultPoint(str, Enum):
    """Closed set of test-only fault injection points (§6.2)."""

    BEFORE_FREEZE_PUBLISH = "before-freeze-publish"
    BEFORE_READINESS = "before-readiness"
    READINESS_BLOCKED = "readiness-blocked"
    BEFORE_ORACLE = "before-oracle"
    ORACLE_FAIL = "oracle-fail"
    BEFORE_WARMUP = "before-warmup"
    WARMUP_ERROR = "warmup-error"
    BEFORE_MEASURE = "before-measure"
    MEASUREMENT_ERROR = "measurement-error"
    MEASUREMENT_WRONG_COUNT = "measurement-wrong-count"
    MEASUREMENT_WRONG_UNIT = "measurement-wrong-unit"
    MEASUREMENT_WRONG_SCOPE = "measurement-wrong-scope"
    BEFORE_LANE_PUBLISH = "before-lane-publish"
    AFTER_LANE_PUBLISH = "after-lane-publish"
    BEFORE_SLOT_PUBLISH = "before-slot-publish"
    AFTER_SLOT_PUBLISH = "after-slot-publish"
    BEFORE_SEAL = "before-seal"


_FAULT_TARGETS: frozenset[str] = frozenset(
    {"campaign_kind", "campaign_index", "block", "position", "lane_id"}
)


@dataclass(frozen=True)
class FaultPlan:
    """A single, test-constructed one-shot fault; never parsed or executed."""

    point: FaultPoint | None = None
    campaign_kind: str | None = None
    campaign_index: int | None = None
    block: int | None = None
    position: int | None = None
    lane_id: str | None = None

    def __post_init__(self) -> None:
        if self.point is not None and not isinstance(self.point, FaultPoint):
            raise _fail("fault point must be a FaultPoint", "faults.point")
        if self.campaign_kind is not None and self.campaign_kind not in CAMPAIGN_KINDS:
            raise _fail("fault campaign_kind is not recognised", "faults.campaign_kind")
        for name in ("campaign_index", "block", "position"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise _fail(f"fault {name} must be a non-negative integer", f"faults.{name}")
        if self.lane_id is not None and (
            not isinstance(self.lane_id, str) or not self.lane_id
        ):
            raise _fail("fault lane_id must be a non-empty string", "faults.lane_id")

    @property
    def target_keys(self) -> frozenset[str]:
        """Return the set of constrained target fields."""

        return frozenset(
            name for name in _FAULT_TARGETS if getattr(self, name) is not None
        )


@dataclass(frozen=True)
class ExecutionResult:
    """Structural outcome of one synthetic execution attempt.

    ``status == "sealed"`` means exactly one structural seal was published. It
    never means a statistical decision, an accepted policy, a Gate A-E receipt or
    a real performance qualification.
    """

    status: str
    run_dir: Path
    run_id: str
    freeze_digest: str
    schedule_digest: str
    seal_digest: str | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.status not in ("sealed", "stopped"):
            raise _fail("execution status must be sealed or stopped", "status")
        if self.status == "sealed" and self.seal_digest is None:
            raise _fail("a sealed result must carry a seal digest", "seal_digest")
        if self.status == "stopped" and self.reason is None:
            raise _fail("a stopped result must carry a stop reason", "reason")

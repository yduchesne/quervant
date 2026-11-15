"""Read-only structural replay of one sealed synthetic run.

Replay reconstructs the expected inventory, freeze and counts **independently**
from the declared BM-01 bundle and the declared scenario; it never imports the
controller's in-memory state and never calls a controller completeness predicate.
It never writes, repairs, prunes or reclassifies evidence, and it never issues a
Gate A-E receipt or a statistical decision.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config.codec import canonical_document_bytes, content_digest, decode_text, loads_json
from ..config.contracts import ExperimentBundle
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_FILE_MISSING,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..evidence.paths import (
    list_directory_beneath,
    open_regular_beneath,
    require_safe_root,
)
from ..host.readiness import evaluate_readiness
from ..protocol.controls import (
    CONTROL_LEFT_ARM_ID,
    CONTROL_RIGHT_ARM_ID,
    build_control_schedule,
    read_protocol_campaigns,
)
from ..protocol.freeze import validate_freeze_document, verify_freeze_bindings
from ..protocol.schedule import CompiledSchedule, compile_schedule, validate_schedule_document
from .contracts import CONTROL_CONTRACT_ID, SYNTHETIC_METRIC_UNIT, RunState
from .recorder import (
    control_relative_path,
    event_relative_path,
    lane_relative_path,
    readiness_relative_path,
    slot_complete_relative_path,
    validate_control_report_document,
    validate_event_document,
    validate_lane_envelope_document,
    validate_readiness_document,
    validate_seal_document,
    validate_slot_complete_document,
)
from .scenario import SYNTHETIC_READINESS_LIMITS, SyntheticScenario, load_synthetic_scenario
from .store import SEAL_NAME

VERIFIED_STATUS = "verified-synthetic-structure"
_MAX_RECORD_BYTES = 1_048_576


def _fail(message: str, field_path: str = "evidence") -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class StructuralReplayResult:
    """Read-only structural verification outcome."""

    status: str
    run_id: str
    seal_digest: str
    controls_completed: int
    treatments_completed: int
    slots_completed: int
    lane_envelopes: int
    synthetic_samples: int


@dataclass(frozen=True)
class _CampaignReplay:
    kind: str
    index: int
    schedule: CompiledSchedule


def _read_bytes(run_dir: Path, relative: str) -> bytes:
    handle = open_regular_beneath(run_dir, relative)
    with handle:
        payload = handle.read(_MAX_RECORD_BYTES + 1)
    if len(payload) > _MAX_RECORD_BYTES:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "a stored record exceeds the canonical record budget",
            reference=relative,
        )
    return payload


def _read_document(run_dir: Path, relative: str) -> Mapping[str, Any]:
    payload = _read_bytes(run_dir, relative)
    document = loads_json(decode_text(payload))
    if canonical_document_bytes(document) != payload:
        raise BenchError(
            BM_UNSAFE_INPUT,
            f"stored record {relative!r} is not in canonical byte form",
            reference=relative,
        )
    if not isinstance(document, Mapping):
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"stored record {relative!r} is not a JSON object",
            reference=relative,
        )
    return document


def _inventory(run_dir: Path) -> tuple[str, ...]:
    """Return every stored relative path without following any link."""

    require_safe_root(run_dir)
    collected: list[str] = []

    def walk(prefix: str) -> None:
        names = (
            sorted(os.listdir(run_dir))
            if prefix == ""
            else list_directory_beneath(run_dir, prefix)
        )
        for name in names:
            relative = f"{prefix}/{name}" if prefix else name
            info = os.lstat(run_dir / relative)
            if stat.S_ISLNK(info.st_mode):
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    "evidence must not contain symbolic links",
                    reference=relative,
                )
            if stat.S_ISDIR(info.st_mode):
                walk(relative)
            elif stat.S_ISREG(info.st_mode):
                collected.append(relative)
            else:
                raise BenchError(
                    BM_UNSAFE_INPUT,
                    "evidence must contain only regular files and directories",
                    reference=relative,
                )

    walk("")
    return tuple(sorted(collected))


def _raw_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class _Replay:
    def __init__(
        self,
        run_dir: Path,
        *,
        bundle: ExperimentBundle,
        scenario_root: Path,
    ) -> None:
        self.run_dir = run_dir
        self.bundle = bundle
        self.scenario_root = scenario_root
        self.schedule = compile_schedule(bundle)
        self.scenario: SyntheticScenario = load_synthetic_scenario(
            scenario_root, bundle=bundle
        )
        self.control = build_control_schedule(
            bundle, control_source_arm_id=self.scenario.control_source_arm_id
        )
        self.campaigns_decl = read_protocol_campaigns(bundle)
        self.lane_ids = tuple(lane.lane_id for lane in bundle.workload.lanes)
        self.campaigns = self._campaigns()
        self.samples_per_lane_slot = bundle.protocol.samples_per_lane_slot
        self.warmups_per_lane_slot = bundle.protocol.warmups_per_lane_slot

    def _campaigns(self) -> tuple[_CampaignReplay, ...]:
        campaigns: list[_CampaignReplay] = []
        if self.control.status == "scheduled" and self.control.compiled is not None:
            for index in range(self.control.campaign_count):
                campaigns.append(
                    _CampaignReplay(kind="control", index=index, schedule=self.control.compiled)
                )
        for index in range(self.campaigns_decl.required_treatments):
            campaigns.append(
                _CampaignReplay(kind="treatment", index=index, schedule=self.schedule)
            )
        return tuple(campaigns)

    # -- expectations -----------------------------------------------------

    def expected_paths(self) -> tuple[str, ...]:
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

    def expected_events(self) -> tuple[tuple[str, str, str], ...]:
        events: list[tuple[str, str, str]] = [
            ("none", RunState.PLANNED.value, "new-run"),
            (RunState.PLANNED.value, RunState.FROZEN.value, "freeze-published"),
        ]
        for index, _campaign in enumerate(self.campaigns):
            events.append(
                (
                    RunState.FROZEN.value if index == 0 else RunState.ACQUIRING.value,
                    RunState.READY.value,
                    "readiness-clear",
                )
            )
            events.append(
                (RunState.READY.value, RunState.ACQUIRING.value, "slot-acquiring")
            )
        events.append(
            (RunState.ACQUIRING.value, RunState.COMPLETED.value, "campaigns-complete")
        )
        return tuple(events)

    # -- verification -----------------------------------------------------

    def verify(self) -> StructuralReplayResult:
        require_safe_root(self.run_dir)
        try:
            seal_payload = _read_bytes(self.run_dir, SEAL_NAME)
        except BenchError as exc:
            if exc.code == BM_FILE_MISSING:
                raise BenchError(
                    BM_EVIDENCE_UNAVAILABLE,
                    "the run is incomplete (crash-interrupted): seal.json is absent",
                ) from exc
            raise
        seal_document = loads_json(decode_text(seal_payload))
        if canonical_document_bytes(seal_document) != seal_payload:
            raise _fail("seal.json is not stored in canonical byte form")
        seal = validate_seal_document(seal_document)
        if seal.run_id != self.run_dir.name:
            raise _fail("the seal run identity does not match its directory")
        if seal.experiment_id != self.bundle.experiment.experiment_id:
            raise _fail("the seal experiment identity does not match the declared bundle")
        if seal.scenario_digest != self.scenario.scenario_digest:
            raise _fail("the seal scenario digest does not match the declared scenario")
        if seal.schedule_digest != self.schedule.schedule_digest:
            raise _fail("the seal schedule digest does not match the compiled schedule")

        expected = self.expected_paths()
        inventory = _inventory(self.run_dir)
        if tuple(inventory) != tuple(sorted(expected + (SEAL_NAME,))):
            missing = sorted(set(expected) - set(inventory))
            if missing:
                raise _fail(f"the sealed run is missing a required record: {missing[0]}")
            extra = sorted(set(inventory) - set(expected) - {SEAL_NAME})
            raise BenchError(
                BM_UNSAFE_INPUT,
                f"the sealed run contains an unexpected record: {extra[0]}",
                reference=extra[0],
            )

        listed = {path: (digest, length) for path, digest, length in seal.files}
        if tuple(sorted(listed)) != tuple(sorted(expected)):
            raise _fail("the seal file inventory does not match the expected record set")
        for path in expected:
            payload = _read_bytes(self.run_dir, path)
            digest, length = listed[path]
            if digest != _raw_digest(payload) or length != len(payload):
                raise _fail(f"the stored bytes of {path!r} do not match the seal")

        self._verify_schedule()
        self._verify_control_schedule()
        self._verify_freeze()
        self._verify_events()
        self._verify_readiness()
        envelopes = self._verify_lanes()
        self._verify_slots()
        self._verify_controls(envelopes)

        expected_slots = sum(
            len(campaign.schedule.slots) for campaign in self.campaigns
        )
        expected_samples = expected_slots * len(self.lane_ids) * self.samples_per_lane_slot
        control_campaigns = (
            self.control.campaign_count if self.control.status == "scheduled" else 0
        )
        if seal.controls_completed != control_campaigns:
            raise _fail("the seal control count does not match the declared campaigns")
        if seal.treatments_completed != self.campaigns_decl.required_treatments:
            raise _fail("the seal treatment count does not match the declared campaigns")
        if seal.slots_completed != expected_slots:
            raise _fail("the seal slot count does not match the expected schedule")
        if seal.lane_envelopes != expected_slots * len(self.lane_ids):
            raise _fail("the seal lane-envelope count does not match the expected schedule")
        if seal.synthetic_samples != expected_samples:
            raise _fail("the seal sample count does not match the expected schedule")
        last_end = max((entry.logical_end_ns for entry in envelopes.values()), default=0)
        if seal.last_logical_ns != last_end:
            raise _fail("the seal logical clock does not match the last lane envelope")
        return StructuralReplayResult(
            status=VERIFIED_STATUS,
            run_id=seal.run_id,
            seal_digest=content_digest(dict(seal_document)),
            controls_completed=seal.controls_completed,
            treatments_completed=seal.treatments_completed,
            slots_completed=seal.slots_completed,
            lane_envelopes=seal.lane_envelopes,
            synthetic_samples=seal.synthetic_samples,
        )

    def _verify_schedule(self) -> None:
        stored = validate_schedule_document(_read_document(self.run_dir, "schedule.json"))
        if stored.schedule_digest != self.schedule.schedule_digest:
            raise _fail("the stored schedule digest is not the declared compile output")
        if stored.slots != self.schedule.slots:
            raise _fail("the stored schedule rows differ from the declared compile output")
        if (
            stored.algorithm_id != self.schedule.algorithm_id
            or stored.seed != self.schedule.seed
            or stored.protocol_digest != self.bundle.protocol_digest
        ):
            raise _fail("the stored schedule identity does not match the declared protocol")

    def _verify_control_schedule(self) -> None:
        document = _read_document(self.run_dir, "control-schedule.json")
        if content_digest(dict(document)) != self.control.digest:
            raise _fail("the stored control schedule differs from the declared control schedule")
        if document.get("control_contract_id") != self.control.control_contract_id:
            raise _fail("the stored control contract identity is not the frozen one")
        if document.get("campaign_count") != self.control.campaign_count:
            raise _fail("the stored control campaign count is not the frozen one")

    def _verify_freeze(self) -> None:
        record = validate_freeze_document(_read_document(self.run_dir, "freeze.json"))
        if record.run_id != self.run_dir.name:
            raise _fail("the freeze run identity does not match its directory")
        verify_freeze_bindings(
            record,
            bundle=self.bundle,
            schedule=self.schedule,
            control_schedule=self.control,
            scenario_digest=self.scenario.scenario_digest,
        )
        if record.required_controls != self.campaigns_decl.required_controls:
            raise _fail("the freeze control requirement does not match the protocol")
        if record.required_treatments != self.campaigns_decl.required_treatments:
            raise _fail("the freeze treatment requirement does not match the protocol")

    def _verify_events(self) -> None:
        expected = self.expected_events()
        previous_ns = 0
        for sequence, (from_state, to_state, reason) in enumerate(expected, start=1):
            event = validate_event_document(
                _read_document(self.run_dir, event_relative_path(sequence))
            )
            if event.sequence != sequence:
                raise _fail("a persisted state event has the wrong sequence number")
            if (event.from_state, event.to_state, event.reason) != (
                from_state,
                to_state,
                reason,
            ):
                raise _fail(
                    f"state event {sequence} is not the prescribed transition "
                    f"{from_state} -> {to_state}"
                )
            if event.logical_ns < previous_ns:
                raise _fail("the persisted state events are not monotone in logical time")
            previous_ns = event.logical_ns

    def _verify_readiness(self) -> None:
        for campaign in self.campaigns:
            record = validate_readiness_document(
                _read_document(
                    self.run_dir,
                    readiness_relative_path(campaign.kind, campaign.index),
                )
            )
            if (record.campaign_kind, record.campaign_index) != (
                campaign.kind,
                campaign.index,
            ):
                raise _fail("a readiness record names the wrong campaign")
            if record.limits != SYNTHETIC_READINESS_LIMITS:
                raise _fail("a readiness record does not carry the frozen limits")
            expected = self.scenario.readiness_for(campaign.kind, campaign.index)
            if record.observations != tuple(expected):
                raise _fail("a readiness record does not carry the declared observations")
            diagnostic = evaluate_readiness(record.limits, record.observations)
            if diagnostic != record.diagnostic:
                raise _fail("a persisted readiness diagnostic cannot be reproduced")
            if record.diagnostic.status != "clear":
                raise _fail("a sealed run contains a blocked readiness diagnostic")

    def _verify_lanes(self) -> dict[tuple[str, int, int, int, str], Any]:
        envelopes: dict[tuple[str, int, int, int, str], Any] = {}
        previous_end: int | None = None
        for campaign in self.campaigns:
            for slot in campaign.schedule.slots:
                for lane_id in self.lane_ids:
                    relative = lane_relative_path(
                        campaign.kind,
                        campaign.index,
                        slot.block,
                        slot.position,
                        lane_id,
                    )
                    envelope = validate_lane_envelope_document(
                        _read_document(self.run_dir, relative)
                    )
                    key = (
                        campaign.kind,
                        campaign.index,
                        slot.block,
                        slot.position,
                        lane_id,
                    )
                    if key in envelopes:
                        raise _fail("a lane envelope is stored twice")
                    envelopes[key] = envelope
                    expected_arm = slot.arm_id
                    declared_arm = (
                        slot.arm_id
                        if campaign.kind == "treatment"
                        else self.control.source_arm_id
                    )
                    if envelope.arm_id != expected_arm:
                        raise _fail("a lane envelope names the wrong display arm")
                    if envelope.declared_arm_id != declared_arm:
                        raise _fail("a lane envelope names the wrong declared arm")
                    if envelope.ordinal != slot.ordinal:
                        raise _fail("a lane envelope has the wrong campaign ordinal")
                    if envelope.run_id != self.run_dir.name:
                        raise _fail("a lane envelope names the wrong run")
                    if envelope.warmup_calls != self.warmups_per_lane_slot:
                        raise _fail("a lane envelope records the wrong warmup count")
                    if envelope.metric_unit != SYNTHETIC_METRIC_UNIT:
                        raise _fail("a lane envelope does not record nanoseconds")
                    if envelope.fixture_digest != self.scenario.scenario_digest:
                        raise _fail("a lane envelope does not bind the declared scenario")
                    expected_samples = self.scenario.values_for(declared_arm, lane_id)
                    if envelope.samples != expected_samples:
                        raise _fail("a lane envelope does not replay the declared samples")
                    if previous_end is not None and envelope.logical_start_ns != previous_end:
                        raise _fail("lane envelopes are not contiguous in logical time")
                    previous_end = envelope.logical_end_ns
        return envelopes

    def _verify_slots(self) -> None:
        for campaign in self.campaigns:
            for slot in campaign.schedule.slots:
                record = validate_slot_complete_document(
                    _read_document(
                        self.run_dir,
                        slot_complete_relative_path(
                            campaign.kind,
                            campaign.index,
                            slot.block,
                            slot.position,
                        ),
                    )
                )
                if (record.block, record.position, record.ordinal) != (
                    slot.block,
                    slot.position,
                    slot.ordinal,
                ):
                    raise _fail("a slot completion record has the wrong slot identity")
                if record.arm_id != slot.arm_id:
                    raise _fail("a slot completion record names the wrong arm")
                expected_lanes = self.lane_ids
                if tuple(lane_id for lane_id, _ in record.lanes) != expected_lanes:
                    raise _fail(
                        "a slot completion record does not list the declared lane order"
                    )
                for lane_id, digest in record.lanes:
                    raw = _read_bytes(
                        self.run_dir,
                        lane_relative_path(
                            campaign.kind,
                            campaign.index,
                            slot.block,
                            slot.position,
                            lane_id,
                        ),
                    )
                    document = loads_json(decode_text(raw))
                    if digest != content_digest(document):
                        raise _fail("a slot completion lane digest does not bind its envelope")

    def _verify_controls(
        self, envelopes: Mapping[tuple[str, int, int, int, str], Any]
    ) -> None:
        for campaign in self.campaigns:
            if campaign.kind != "control":
                continue
            report = validate_control_report_document(
                _read_document(self.run_dir, control_relative_path(campaign.index))
            )
            if report.campaign_index != campaign.index:
                raise _fail("a control report names the wrong campaign")
            if report.control_contract_id != CONTROL_CONTRACT_ID:
                raise _fail("a control report does not use the frozen control contract")
            if report.source_arm_id != self.control.source_arm_id:
                raise _fail("a control report names the wrong source arm")
            if report.lane_ids != self.lane_ids:
                raise _fail("a control report does not list the declared lanes")
            expected_pairs = campaign.schedule.blocks * len(self.lane_ids)
            if report.checked_pairs != expected_pairs:
                raise _fail("a control report has the wrong checked-pair count")
            for slot in campaign.schedule.slots:
                if slot.arm_id != CONTROL_LEFT_ARM_ID:
                    continue
                right_position = next(
                    candidate.position
                    for candidate in campaign.schedule.slots
                    if candidate.block == slot.block
                    and candidate.arm_id == CONTROL_RIGHT_ARM_ID
                )
                for lane_id in self.lane_ids:
                    left = envelopes[
                        (campaign.kind, campaign.index, slot.block, slot.position, lane_id)
                    ]
                    right = envelopes[
                        (
                            campaign.kind,
                            campaign.index,
                            slot.block,
                            right_position,
                            lane_id,
                        )
                    ]
                    if left.samples != right.samples:
                        raise _fail("the sealed synthetic A/A replicas are not identical")


def replay_sealed_synthetic(
    run_dir: Path, *, bundle: ExperimentBundle, scenario_root: Path
) -> StructuralReplayResult:
    """Verify one sealed synthetic run structurally, read-only, without repair."""

    if not isinstance(bundle, ExperimentBundle):
        raise BenchError(
            BM_SCHEMA_INVALID,
            "a validated ExperimentBundle is required for replay",
            field_path="bundle",
        )
    if not isinstance(run_dir, Path) or not isinstance(scenario_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "run_dir and scenario_root must be Path instances",
            field_path="paths",
        )
    return _Replay(run_dir, bundle=bundle, scenario_root=scenario_root).verify()


__all__ = ["StructuralReplayResult", "VERIFIED_STATUS", "replay_sealed_synthetic"]

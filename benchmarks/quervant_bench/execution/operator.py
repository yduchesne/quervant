"""Shared, bounded operator dispatch and stage execution.

Stage plans are compiled into this module. Configuration cannot name a Python
callable, substitute a command, reorder a plan, or authorize a retry. Domain
backends retain their independently validated scope and evidence contracts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..config.codec import decode_text, loads_json
from ..config.errors import (
    BM_FILE_MISSING,
    BM_INTERNAL_ERROR,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BM_USAGE,
    BenchError,
)
from ..config.identity import validate_semantic_id, validate_uuid4
from ..evidence.paths import open_regular_beneath, require_safe_root

OFFICIAL_CONFIG_KIND = "official-operation-config"
SYNTHETIC_CONFIG_KIND = "synthetic-operation"
OFFICIAL_EXPERIMENTS = (
    "cross-engine-keyword-real-v1",
    "retained-key-topk-real-v1",
)
SYNTHETIC_EXPERIMENTS = (
    "synthetic-cross-engine-reference",
    "synthetic-retained-key-reference",
)
STAGE_VERBS = ("validate", "analyze", "verify", "accept", "report")
MAX_OPERATION_BYTES = 65_536

_PLANS = MappingProxyType(
    {
        "official-acquisition": (
            "authorize", "readiness", "control", "control-verify", "treatment", "admission",
        ),
        "official-validation": ("authorize", "admission"),
        "official-analysis": ("authorize", "admission", "analysis"),
        "official-verification": ("authorize", "admission", "analysis", "verification"),
        "official-acceptance": (
            "authorize", "admission", "analysis", "verification", "acceptance", "attestation",
        ),
        "synthetic-qualification": ("prepare", "acquisition", "qualification"),
    }
)


def execute_stages(
    plan: str,
    backend: Mapping[str, Callable[[], Any]],
    *,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute one closed plan once; preserve the original failure and stop.

    Events are progress records, never admission, authorization or PASS receipts.
    A caller that persists them must complete each write before returning from
    ``on_event``. A failed event write prevents the next callback from running.
    Resource-owning callbacks remain responsible for their own ``finally`` cleanup.
    """

    if not isinstance(plan, str) or plan not in _PLANS:
        raise BenchError(BM_USAGE, "unknown operator stage plan", field_path="plan")
    stages = _PLANS[plan]
    if not isinstance(backend, Mapping) or set(backend) != set(stages):
        raise BenchError(BM_SCHEMA_INVALID, "backend does not match the closed stage plan", field_path="backend")
    callbacks = tuple(backend[name] for name in stages)
    if any(not callable(callback) for callback in callbacks):
        raise BenchError(BM_SCHEMA_INVALID, "every stage requires a callable backend", field_path="backend")
    if on_event is not None and not callable(on_event):
        raise BenchError(BM_SCHEMA_INVALID, "event sink must be callable", field_path="on_event")
    synthetic = plan == "synthetic-qualification"
    sequence = 0

    def emit(stage: str, event: str, code: str | None = None) -> None:
        nonlocal sequence
        sequence += 1
        document = {
            "kind": "benchmark-operator-stage-event",
            "schema_version": 1,
            "plan": plan,
            "sequence": sequence,
            "stage": stage,
            "event": event,
            "evidence_origin": "synthetic" if synthetic else "real",
            "qualification_scope": "simulated" if synthetic else "official",
            "error_code": code,
        }
        if on_event is not None:
            on_event(document)

    results: dict[str, Any] = {}
    for name, callback in zip(stages, callbacks):
        emit(name, "started")
        try:
            result = callback()
        except BaseException as error:
            code = error.code if isinstance(error, BenchError) else BM_INTERNAL_ERROR
            event = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
            try:
                emit(name, event, code)
            except Exception as journal_error:
                raise error from journal_error
            raise
        emit(name, "completed")
        results[name] = result
    return results


def read_operation_document(path: Path) -> dict[str, Any]:
    """Read a bounded local JSON file with no links or executable extensions."""

    candidate = Path(path).absolute()
    parent = require_safe_root(candidate.parent)
    with open_regular_beneath(parent, candidate.name) as stream:
        payload = stream.read(MAX_OPERATION_BYTES + 1)
    if len(payload) > MAX_OPERATION_BYTES:
        raise BenchError(BM_UNSAFE_INPUT, "operation configuration exceeds its byte budget", field_path="config")
    document = loads_json(decode_text(payload))
    if not isinstance(document, Mapping):
        raise BenchError(BM_SCHEMA_INVALID, "operation configuration must be an object", field_path="config")
    if document.get("kind") not in (OFFICIAL_CONFIG_KIND, SYNTHETIC_CONFIG_KIND):
        raise BenchError(BM_SCHEMA_INVALID, "unknown operation configuration kind", field_path="kind")
    versions = (1, 2) if document["kind"] == OFFICIAL_CONFIG_KIND else (1,)
    if type(document.get("schema_version")) is not int or document["schema_version"] not in versions:
        raise BenchError(BM_SCHEMA_INVALID, "unsupported operation configuration version", field_path="schema_version")
    return dict(document)


def _require_family(experiment: str, document: Mapping[str, Any]) -> str:
    validate_semantic_id(experiment, "experiment_id")
    if experiment in OFFICIAL_EXPERIMENTS:
        expected = OFFICIAL_CONFIG_KIND
    elif experiment in SYNTHETIC_EXPERIMENTS:
        expected = SYNTHETIC_CONFIG_KIND
    else:
        raise BenchError(BM_FILE_MISSING, "unknown supported operator experiment", field_path="experiment_id")
    if document.get("kind") != expected:
        raise BenchError(BM_SCHEMA_INVALID, "operation configuration belongs to a different scope", field_path="kind")
    return expected


def dispatch_run(experiment: str, protocol_path: Path, out: Path, config_path: Path) -> dict[str, Any]:
    """Route through one explicit scope registry, never through a config plugin."""

    document = read_operation_document(config_path)
    kind = _require_family(experiment, document)
    if kind == SYNTHETIC_CONFIG_KIND:
        from .synthetic_operator import run_synthetic

        return run_synthetic(experiment, Path(protocol_path), Path(out), Path(config_path))
    from ..official.workflow import run_official

    return run_official(experiment, Path(protocol_path), Path(out), Path(config_path))


def dispatch_prepare(experiment: str, protocol_path: Path, out: Path, config_path: Path) -> dict[str, Any]:
    """Prepare official inputs only; authorization remains externally reviewed."""

    document = read_operation_document(config_path)
    if _require_family(experiment, document) != OFFICIAL_CONFIG_KIND:
        raise BenchError(BM_USAGE, "prepare is an official input-preparation command", field_path="experiment_id")
    from ..official.workflow import prepare_official

    return prepare_official(experiment, Path(protocol_path), Path(out), Path(config_path))


def dispatch_stage(verb: str, run_id: str, config_path: Path) -> dict[str, Any]:
    """Open one existing run through the configuration's validated scope."""

    if verb not in STAGE_VERBS:
        raise BenchError(BM_USAGE, "unsupported operator stage", field_path="verb")
    validate_uuid4(run_id, "run_id")
    document = read_operation_document(config_path)
    if document["kind"] == SYNTHETIC_CONFIG_KIND:
        from .synthetic_operator import dispatch_synthetic_stage

        return dispatch_synthetic_stage(verb, run_id, Path(config_path))
    from ..official.workflow import dispatch_official_stage

    return dispatch_official_stage(verb, run_id, Path(config_path))


__all__ = [
    "OFFICIAL_EXPERIMENTS", "SYNTHETIC_EXPERIMENTS", "STAGE_VERBS",
    "dispatch_prepare", "dispatch_run", "dispatch_stage", "execute_stages",
    "read_operation_document",
]

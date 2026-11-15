"""BM-03 deterministic synthetic execution core.

Everything here is a **simulator**: an injected logical clock, a declared
synthetic scenario, one adapter that replays those values, one controller state
machine, an exclusive append-only evidence store and a read-only structural
replayer. Nothing times a real query, samples a real host or produces a
performance decision. Real acquisition remains prohibited until BM-09.

Names are resolved lazily so that ``protocol`` and ``execution`` submodules can be
imported in any order without a package-initialisation cycle.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "EVENT_REASONS": ".contracts",
    "MAX_ARMS": ".contracts",
    "MAX_BLOCKS": ".contracts",
    "MAX_CANONICAL_RECORD_BYTES": ".contracts",
    "MAX_CONTROL_CAMPAIGNS": ".contracts",
    "MAX_EVENT_RECORDS": ".contracts",
    "MAX_LANES": ".contracts",
    "MAX_LOGICAL_NS": ".contracts",
    "MAX_SAMPLES_PER_LANE_SLOT": ".contracts",
    "MAX_SCENARIO_BYTES": ".contracts",
    "MAX_SLOTS_PER_BLOCK": ".contracts",
    "MAX_SYNTHETIC_SAMPLE_NS": ".contracts",
    "MAX_TOTAL_LANE_SLOTS": ".contracts",
    "MAX_TREATMENT_CAMPAIGNS": ".contracts",
    "MAX_WARMUPS_PER_LANE_SLOT": ".contracts",
    "SYNTHETIC_READINESS_LIMITS": ".scenario",
    "ArmAssignment": ".contracts",
    "ExecutionResult": ".contracts",
    "ExecutionStore": ".store",
    "FaultPlan": ".contracts",
    "FaultPoint": ".contracts",
    "LogicalClock": ".clock",
    "Recorder": ".recorder",
    "RunState": ".contracts",
    "ScenarioReadiness": ".scenario",
    "ScenarioReadinessProvider": ".controller",
    "ScenarioSample": ".scenario",
    "SimulatedCapabilityProvider": ".controller",
    "SlotKey": ".contracts",
    "StopReason": ".contracts",
    "StructuralReplayResult": ".replay",
    "SyntheticAdapter": ".synthetic",
    "SyntheticAdapterFactory": ".synthetic",
    "SyntheticReadinessProvider": ".controller",
    "SyntheticScenario": ".scenario",
    "execute_synthetic": ".controller",
    "load_synthetic_scenario": ".scenario",
    "replay_sealed_synthetic": ".replay",
    "synthetic_adapter_factory": ".synthetic",
    "validate_scenario_document": ".scenario",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)

"""BM-03 declarative protocol compilation.

``balanced-cyclic-v1`` / ``explicit-v1`` schedule compilation, the frozen control
(A/A) schedule and the synthetic freeze payload live here. They are internal BM-03
mechanics: no BM-01 schema, CLI verb or error code is added, and no official
freeze authorisation is issued.

Names are resolved lazily so that ``protocol`` and ``execution`` submodules can be
imported in any order without a package-initialisation cycle.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "ALGORITHM_BALANCED": ".schedule",
    "ALGORITHM_EXPLICIT": ".schedule",
    "BUILD_BINDING_KIND": ".freeze",
    "CONTROL_SCHEDULE_KIND": ".controls",
    "CompiledSchedule": ".schedule",
    "ControlSchedule": ".controls",
    "FREEZE_KIND": ".freeze",
    "FreezeRecord": ".freeze",
    "ProtocolCampaigns": ".controls",
    "SCHEDULE_KIND": ".schedule",
    "SOURCE_BINDING_KIND": ".freeze",
    "ScheduleSlot": ".schedule",
    "ScheduleSpec": ".schedule",
    "build_control_schedule": ".controls",
    "build_freeze_document": ".freeze",
    "compile_schedule": ".schedule",
    "read_protocol_campaigns": ".controls",
    "schedule_document": ".schedule",
    "validate_control_schedule_document": ".controls",
    "validate_freeze_document": ".freeze",
    "validate_schedule_document": ".schedule",
    "verify_freeze_bindings": ".freeze",
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

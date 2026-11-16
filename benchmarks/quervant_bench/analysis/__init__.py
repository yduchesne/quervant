"""BM-04 primary analysis and frozen-policy package.

Everything in this package is pure, deterministic, in-memory computation over
read-only, replay-verified **synthetic** BM-03 evidence. It never writes a file,
starts a process, reads a clock, opens a socket or invokes an adapter, and it
issues no Gate A-E receipt. Real timed acquisition remains prohibited until
BM-09.

Names are resolved lazily so that submodules can be imported in any order.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "ANALYSIS_KIND": ".contracts",
    "ANALYSIS_STATUS": ".contracts",
    "BootstrapInterval": ".contracts",
    "ExclusionLedger": ".contracts",
    "ExclusionLedgerRow": ".contracts",
    "AnalysisProfile": ".profiles",
    "PolicyProfile": ".policy",
    "ResourceObservations": ".policy",
    "PolicyDecision": ".policy",
    "analyze_synthetic_run": ".derive",
    "apply_lane_block_exclusions": ".pruning",
    "bootstrap_interval": ".bootstrap",
    "evaluate_policy": ".policy",
    "read_analysis_profile": ".profiles",
    "read_policy_profile": ".policy",
    "read_resource_observations": ".policy",
    "validate_analysis_profile": ".profiles",
    "validate_analysis_result": ".contracts",
    "validate_policy_decision": ".contracts",
    "validate_policy_profile": ".policy",
    "validate_resource_observations": ".policy",
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

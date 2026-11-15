"""Read-only host capability and pure readiness diagnostics.

Neither module authorizes acquisition. A capability snapshot is diagnostic and a
readiness ``clear`` is a mechanical diagnostic, not an acquisition permit.
"""

from __future__ import annotations

from .capabilities import (
    CapabilityProvider,
    LinuxCapabilityProvider,
    collect_host_capabilities,
    validate_host_capabilities,
)
from .readiness import (
    ReadinessDiagnostic,
    ReadinessLimits,
    ReadinessObservation,
    evaluate_readiness,
)

__all__ = [
    "CapabilityProvider",
    "LinuxCapabilityProvider",
    "ReadinessDiagnostic",
    "ReadinessLimits",
    "ReadinessObservation",
    "collect_host_capabilities",
    "evaluate_readiness",
    "validate_host_capabilities",
]

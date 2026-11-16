"""BM-06 synthetic qualification: A→B→C→D→E gates and immutable attestation.

The package exposes exactly two library entry points and one result record. It
never activates a CLI verb, launches an adapter, reads a clock, acquires a real
timing sample, authenticates CI or publishes an official qualification.
"""

from __future__ import annotations

from .contracts import QualificationResult
from .coordinator import load_qualified_synthetic_run, qualify_synthetic_run

__all__ = [
    "QualificationResult",
    "load_qualified_synthetic_run",
    "qualify_synthetic_run",
]

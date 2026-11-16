"""Independent BM-05 verification of synthetic analysis and policy outputs.

The package exposes exactly one public function and one public result record.
It performs no timing, adapter launch, persistence, receipt issuance or CLI
registration.
"""

from __future__ import annotations

from .contracts import VerificationAssessment
from .verify import verify_synthetic_run

__all__ = ["VerificationAssessment", "verify_synthetic_run"]

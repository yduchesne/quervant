"""Execution profiles: rigor metadata only.

A profile selects *how rigorous* the checks are. It never changes workload
semantics, arm sets, correctness oracles, schedule identities, measurement units
or policy. BM-01 implements validation only; no profile executes anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import BM_SCHEMA_INVALID, BenchError


@dataclass(frozen=True)
class Profile:
    """A named rigor level declared by an experiment."""

    name: str
    description: str
    rigor_rank: int


PROFILES: dict[str, Profile] = {
    "development": Profile(
        name="development",
        description="fast local development checks",
        rigor_rank=1,
    ),
    "regression": Profile(
        name="regression",
        description="broader deterministic regression coverage",
        rigor_rank=2,
    ),
    "qualification": Profile(
        name="qualification",
        description="full protocol-defined rigor and evidence",
        rigor_rank=3,
    ),
}

PROFILE_NAMES: tuple[str, ...] = tuple(PROFILES)


def validate_profile(name: object) -> str:
    """Validate and return a declared profile name."""

    if not isinstance(name, str) or name not in PROFILES:
        raise BenchError(
            BM_SCHEMA_INVALID,
            f"profile must be one of {', '.join(PROFILE_NAMES)}",
            field_path="profile",
        )
    return name


def get_profile(name: str) -> Profile:
    """Return the profile record for a validated name."""

    return PROFILES[validate_profile(name)]

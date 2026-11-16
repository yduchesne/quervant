"""Read-only historical D3-C/T7 compatibility — **never** a new measurement.

BM-04 owns no historical migration and retires no historical path. This module
exists for three narrow purposes only:

* inventory whether an **authentic** external D3-C archive is present, and record
  ``EVIDENCE_UNAVAILABLE`` honestly when it is not (a clean clone never has it);
* expose a separately named ``legacy_t7_compatibility_calculate`` helper that
  reproduces the historical *arithmetic* (exact slot median, integer floor mean of
  slot medians, ``ratio-of-arm-medians-v1`` and the isolated
  ``legacy-python-randrange-v1`` bootstrap);
* compare historical floating-point outputs with an explicit absolute tolerance.

It never runs ``run.py``, ``micro.py``, ``policy.py`` main, Criterion, a profiler
or any measurement entry point, and it never writes into ``target/`` or mutates a
historical artifact. Historical numbers are never a new official performance
result and the primary BM-04 policy is never routed through this module.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config.errors import (
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..config.identity import validate_positive_int
from .arithmetic import median, normalized_effect
from .bootstrap import legacy_bootstrap_interval, legacy_t7_seed

#: Repository-relative location of the untracked external D3-C series.
ARCHIVE_RELATIVE_ROOT = "target/pr15i-d3-c"
#: The original, trusted historical verifier (read-only).
LEGACY_VERIFIER_RELATIVE = "benchmarks/pr15i_d3_c/verify.py"

STATUS_PRESENT = "present"
STATUS_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
PARITY_VERIFIED = "VERIFIED"
PARITY_NOT_EXECUTED = "NOT_EXECUTED"
PARITY_FAILED = "FAILED"
PARITY_NOT_YET_MIGRATED = "NOT_YET_MIGRATED (BM-07)"

#: Absolute tolerance for normalised floating-point historical parity.
LEGACY_ABSOLUTE_TOLERANCE = Decimal("0.000000001")


def _fail(message: str, field_path: str | None = None) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path=field_path)


@dataclass(frozen=True)
class ArchiveEvidenceStatus:
    """Whether an authentic historical archive is available for comparison."""

    archive_root: Path
    status: str
    reason: str
    entry_count: int

    @property
    def available(self) -> bool:
        return self.status == STATUS_PRESENT

    def report_lines(self) -> tuple[str, ...]:
        """Return the exact §15.2 status record lines."""

        if self.available:  # pragma: no cover - absent in a clean checkout
            return (
                "STATUS=EVIDENCE_PRESENT",
                "HISTORICAL_SERIES_VERIFIED=PENDING_ORIGINAL_VERIFIER",
                "NUMERIC_PARITY=NOT_EXECUTED",
                "POLICY_VERDICT_PARITY=NOT_EXECUTED",
                f"REASON={self.reason}",
                "OWNER=BM-07/BM-09",
            )
        return (
            "STATUS=EVIDENCE_UNAVAILABLE",
            "HISTORICAL_SERIES_VERIFIED=NO",
            "NUMERIC_PARITY=NOT_EXECUTED",
            "POLICY_VERDICT_PARITY=NOT_EXECUTED",
            "REASON=required authentic external archive not present",
            "OWNER=BM-07/BM-09; no historical path retired by BM-04",
        )


@dataclass(frozen=True)
class LegacyT7Result:
    """The historical arithmetic surfaces BM-04 is allowed to recompute."""

    retained_blocks: tuple[int, ...]
    excluded_blocks: tuple[int, ...]
    trigger_arms: tuple[tuple[int, tuple[str, ...]], ...]
    arm_block_values: tuple[tuple[int, tuple[tuple[str, int], ...]], ...]
    retained_arm_medians: tuple[tuple[str, Decimal], ...]
    ratio: Decimal
    ci_low: Decimal
    ci_high: Decimal
    seed: int
    resamples: int
    arithmetic_id: str = "legacy-t7-compatibility-v1"

    def to_document(self) -> dict[str, Any]:
        return {
            "arithmetic_id": self.arithmetic_id,
            "retained_blocks": list(self.retained_blocks),
            "excluded_blocks": list(self.excluded_blocks),
            "trigger_arms": [
                {"block": block, "arms": list(arms)}
                for block, arms in self.trigger_arms
            ],
            "arm_block_values": [
                {"block": block, "arms": {arm: value for arm, value in arms}}
                for block, arms in self.arm_block_values
            ],
            "retained_arm_medians": {
                arm: format(value, "f") for arm, value in self.retained_arm_medians
            },
            "ratio": format(self.ratio, "f"),
            "ci_low": format(self.ci_low, "f"),
            "ci_high": format(self.ci_high, "f"),
            "seed": self.seed,
            "resamples": self.resamples,
        }


def inspect_archive(archive_root: Path) -> ArchiveEvidenceStatus:
    """Inventory the external historical archive without following any link."""

    if not isinstance(archive_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT, "archive_root must be a Path", field_path="archive_root"
        )
    try:
        if archive_root.is_symlink():
            raise BenchError(
                BM_UNSAFE_INPUT,
                "the historical archive root must not be a symbolic link",
                field_path="archive_root",
            )
        if not archive_root.is_dir():
            return ArchiveEvidenceStatus(
                archive_root=archive_root,
                status=STATUS_UNAVAILABLE,
                reason="the archive directory does not exist",
                entry_count=0,
            )
        entries = tuple(sorted(archive_root.iterdir()))
    except OSError as exc:  # pragma: no cover - defensive
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the historical archive root cannot be inspected",
            field_path="archive_root",
        ) from exc
    if not entries:
        return ArchiveEvidenceStatus(
            archive_root=archive_root,
            status=STATUS_UNAVAILABLE,
            reason="the archive directory is empty",
            entry_count=0,
        )
    return ArchiveEvidenceStatus(
        archive_root=archive_root,
        status=STATUS_PRESENT,
        reason="an external archive directory is present",
        entry_count=len(entries),
    )


def run_legacy_verifier(
    archive_root: Path, *, repo_root: Path, timeout_seconds: int = 120
) -> dict[str, Any]:
    """Run the original historical verifier read-only and capture its outcome.

    Only the offline verifier is ever invoked; no measurement entry point is
    reachable from here. A missing verifier or archive is reported, never worked
    around.
    """

    if not isinstance(archive_root, Path) or not isinstance(repo_root, Path):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "archive_root and repo_root must be Path instances",
            field_path="archive_root",
        )
    status = inspect_archive(archive_root)
    if not status.available:
        return {
            "status": STATUS_UNAVAILABLE,
            "returncode": None,
            "reason": status.reason,
        }
    verifier = repo_root / LEGACY_VERIFIER_RELATIVE
    if not verifier.is_file():
        return {
            "status": STATUS_UNAVAILABLE,
            "returncode": None,
            "reason": "the original historical verifier is not present",
        }
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, no shell, bounded
            [sys.executable, str(verifier), "--series-root", str(archive_root)],
            capture_output=True,
            text=True,
            timeout=validate_positive_int(timeout_seconds, "timeout_seconds"),
            check=False,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "ERROR",
            "returncode": None,
            "reason": type(exc).__name__,
        }
    return {
        "status": "PASSED" if completed.returncode == 0 else "FAILED",
        "returncode": completed.returncode,
        "stdout_bytes": len(completed.stdout.encode("utf-8")),
        "stderr_bytes": len(completed.stderr.encode("utf-8")),
    }


def legacy_floor_mean_slot_medians(slot_medians: Sequence[int]) -> int:
    """Return the historical integer floor mean of an arm's slot medians."""

    if isinstance(slot_medians, (str, bytes)) or not isinstance(slot_medians, Sequence):
        raise BenchError(
            BM_SCHEMA_INVALID, "slot medians must be a sequence", field_path="slot_medians"
        )
    if not slot_medians:
        raise BenchError(
            BM_SCHEMA_INVALID,
            "an arm must declare at least one slot median",
            field_path="slot_medians",
        )
    total = 0
    for index, value in enumerate(slot_medians):
        if isinstance(value, bool) or not isinstance(value, int):
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"slot_medians[{index}] must be an integer",
                field_path=f"slot_medians[{index}]",
            )
        if value <= 0:
            raise BenchError(
                BM_SCHEMA_INVALID,
                f"slot_medians[{index}] must be positive",
                field_path=f"slot_medians[{index}]",
            )
        total += value
    return total // len(slot_medians)


def legacy_t7_compatibility_calculate(
    block_slot_medians: Mapping[int, Mapping[str, Sequence[int]]],
    *,
    cap: Decimal,
    minimum_retained_blocks: int,
    historical_protocol_sha: str,
    campaign_name: str,
    lane_id: str,
    numerator: str,
    denominator: str,
    direction: str = "lower-is-better",
    resamples: int = 10_000,
) -> LegacyT7Result:
    """Reproduce the historical T7 arithmetic exactly, without any new timing.

    Historical T7 rounds each arm's block value with an integer floor mean, caps
    the within-arm spread per lane, requires at least four retained blocks and
    takes the **ratio of the retained arm medians** with a seeded
    ``random.Random`` percentile interval. None of this is a new BM-04 default.
    """

    if not isinstance(block_slot_medians, Mapping) or not block_slot_medians:
        raise BenchError(
            BM_SCHEMA_INVALID,
            "block_slot_medians must be a non-empty mapping",
            field_path="block_slot_medians",
        )
    if not isinstance(cap, Decimal) or not cap.is_finite() or cap < 1:
        raise BenchError(
            BM_SCHEMA_INVALID, "cap must be a finite Decimal >= 1", field_path="cap"
        )
    blocks = sorted(block_slot_medians)
    if blocks != list(range(1, len(blocks) + 1)):
        raise _fail("blocks must be exactly 1..N", "block_slot_medians")
    arms = tuple(sorted(block_slot_medians[blocks[0]]))
    if numerator not in arms or denominator not in arms:
        raise _fail(
            "numerator and denominator must be declared arms", "block_slot_medians"
        )

    arm_block_values: dict[int, dict[str, int]] = {}
    retained: list[int] = []
    excluded: list[int] = []
    trigger_arms: list[tuple[int, tuple[str, ...]]] = []
    for block in blocks:
        per_arm = block_slot_medians[block]
        if tuple(sorted(per_arm)) != arms:
            raise _fail(
                "every block must declare the same arms", "block_slot_medians"
            )
        values = {
            arm: legacy_floor_mean_slot_medians(per_arm[arm]) for arm in arms
        }
        arm_block_values[block] = values
        offenders = tuple(
            arm
            for arm in arms
            if max(per_arm[arm]) > 0
            and Decimal(max(per_arm[arm])) / Decimal(min(per_arm[arm])) > cap
        )
        if offenders:
            excluded.append(block)
            trigger_arms.append((block, offenders))
        else:
            retained.append(block)

    if len(retained) < max(minimum_retained_blocks, 1):
        raise _fail(
            "the historical lane does not reach its retained-block minimum",
            "minimum_retained_blocks",
        )

    retained_medians = tuple(
        (
            arm,
            median([Decimal(arm_block_values[block][arm]) for block in retained]),
        )
        for arm in arms
    )
    medians = {arm: value for arm, value in retained_medians}
    ratio = normalized_effect(medians[numerator], medians[denominator], direction)
    seed = legacy_t7_seed(
        historical_protocol_sha,
        campaign_name,
        lane_id,
        numerator,
        denominator,
    )
    rows = tuple(
        (
            block,
            Decimal(arm_block_values[block][denominator]),
            Decimal(arm_block_values[block][numerator]),
        )
        for block in retained
    )
    interval = legacy_bootstrap_interval(
        rows,
        seed=seed,
        resamples=resamples,
        direction=direction,
    )
    return LegacyT7Result(
        retained_blocks=tuple(retained),
        excluded_blocks=tuple(excluded),
        trigger_arms=tuple(trigger_arms),
        arm_block_values=tuple(
            (block, tuple(sorted(values.items())))
            for block, values in sorted(arm_block_values.items())
        ),
        retained_arm_medians=retained_medians,
        ratio=ratio,
        ci_low=interval.low,
        ci_high=interval.high,
        seed=seed,
        resamples=resamples,
    )


def decimal_from_historical(value: Any) -> Decimal:
    """Convert a historical float/int/str value to Decimal for comparison."""

    if isinstance(value, bool):
        raise BenchError(
            BM_SCHEMA_INVALID, "a historical value must not be a boolean", field_path="value"
        )
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise BenchError(
                BM_SCHEMA_INVALID, "a historical value must be finite", field_path="value"
            )
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise BenchError(
                BM_SCHEMA_INVALID, "a historical value must be finite", field_path="value"
            )
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except ArithmeticError as exc:
            raise BenchError(
                BM_SCHEMA_INVALID,
                "a historical string is not a decimal",
                field_path="value",
            ) from exc
        if not parsed.is_finite():
            raise BenchError(
                BM_SCHEMA_INVALID, "a historical value must be finite", field_path="value"
            )
        return parsed
    raise BenchError(
        BM_SCHEMA_INVALID,
        "a historical value must be a number, string or Decimal",
        field_path="value",
    )


def legacy_within_tolerance(
    historical: Any, recomputed: Any, tolerance: Decimal = LEGACY_ABSOLUTE_TOLERANCE
) -> bool:
    """Return whether two historical numeric values agree within the tolerance."""

    first = decimal_from_historical(historical)
    second = decimal_from_historical(recomputed)
    return abs(first - second) <= tolerance


def arithmetic_only_ratio(
    candidate_value: Any, baseline_value: Any, direction: str = "lower-is-better"
) -> Decimal:
    """Compare a raw historical candidate/baseline pair without any policy."""

    candidate = decimal_from_historical(candidate_value)
    baseline = decimal_from_historical(baseline_value)
    if candidate <= 0 or baseline <= 0:
        raise BenchError(
            BM_SCHEMA_INVALID, "historical values must be positive", field_path="value"
        )
    return normalized_effect(candidate, baseline, direction)


__all__ = [
    "ARCHIVE_RELATIVE_ROOT",
    "LEGACY_ABSOLUTE_TOLERANCE",
    "PARITY_FAILED",
    "PARITY_NOT_EXECUTED",
    "PARITY_NOT_YET_MIGRATED",
    "PARITY_VERIFIED",
    "STATUS_PRESENT",
    "STATUS_UNAVAILABLE",
    "ArchiveEvidenceStatus",
    "LegacyT7Result",
    "arithmetic_only_ratio",
    "decimal_from_historical",
    "inspect_archive",
    "legacy_floor_mean_slot_medians",
    "legacy_t7_compatibility_calculate",
    "legacy_within_tolerance",
    "run_legacy_verifier",
]

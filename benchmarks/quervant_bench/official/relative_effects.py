"""Pure relative-effect projection over validated official results.

This module is a *projection*, not an estimator. It never recomputes a statistic
of its own: retained-key rows come from the existing paired-slot statistics and
cross-engine rows from the existing descriptive comparison table. Its only
arithmetic is the documented gain/effect-change conversion between a ratio and a
percentage, which is kept exact by using :class:`decimal.Decimal` on the
canonical ratio strings produced by those existing computations.

Absolute measurements stay in the analysis documents; the report leads with
within-run proportions because those are the only quantities that are
comparable across runs that used different hosts or sources.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Iterable, Mapping, Sequence

from ..config.codec import content_digest
from ..config.errors import BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError

ROWS_KIND = "official-baseline-relative-effects"
DISCLOSURE_SCHEMA_VERSION = 1
METHOD_ID = "relative-effects-v1"
RETAINED_METHOD_ID = "retained-key-paired-slot-effects-v1"
CROSS_ENGINE_METHOD_ID = "cross-engine-three-trial-effects-v1"
RETAINED_DECISION = "DESCRIPTIVE_EFFECT_ONLY"
CROSS_ENGINE_DECISION = "INCONCLUSIVE"
EVIDENCE_RECOMPUTED = "RECOMPUTED"
EVIDENCE_AS_REPORTED = "AS_REPORTED"
DIRECTIONS = ("lower", "higher")
COMPARABILITY = ("COMPARABLE", "CONTEXT_CHANGED", "NOT_COMPARABLE")
PRECISION = Decimal("0.000001")

#: ``(numerator, denominator)`` arm pairs of the frozen retained slot statistics,
#: in the declared presentation order. Every one is a latency ratio, so lower is
#: better; the literal field mapping is R_<num>_<den> -> (num, den).
RETAINED_COMPARISONS: tuple[tuple[str, str], ...] = (
    ("L", "A"),
    ("P", "A"),
    ("H", "A"),
    ("P", "L"),
    ("H", "L"),
    ("H", "P"),
)
RETAINED_REGIME = "warm"
CROSS_ENGINE_REGIME = "warm"
ROW_KEYS = (
    "study_id",
    "run_id",
    "campaign_id",
    "lane_id",
    "metric",
    "unit",
    "regime",
    "direction",
    "baseline",
    "treatment",
    "method_id",
    "ratio",
    "gain_percent",
    "uncertainty",
    "decision",
    "evidence_level",
    "source_commit",
    "host_environment",
    "host_identity",
    "input_digest",
)
COMPARISON_KEYS = (
    "historical_row_digest",
    "current_row_digest",
    "comparability",
    "context_changes",
    "effect_change_percentage_points",
)
#: Coordinates that must agree before two rows may be compared numerically.
MATCH_KEYS = (
    "study_id",
    "campaign_id",
    "lane_id",
    "metric",
    "unit",
    "regime",
    "direction",
    "baseline",
    "treatment",
    "method_id",
)


def _unsafe(message: str, field_path: str) -> BenchError:
    return BenchError(BM_UNSAFE_INPUT, message, field_path=field_path)


def _schema(message: str, field_path: str) -> BenchError:
    return BenchError(BM_SCHEMA_INVALID, message, field_path=field_path)


def decimal_value(value: object, field_path: str) -> Decimal:
    """Return ``value`` as an exact decimal, rejecting bools and non-finites."""

    if type(value) is bool:
        raise _unsafe("a ratio may not be a boolean", field_path)
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (int, float, str)):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise _unsafe("the ratio is not a decimal number", field_path) from error
    else:
        raise _unsafe("the ratio must be a decimal number", field_path)
    if not number.is_finite():
        raise _unsafe("the ratio must be finite", field_path)
    if number <= 0:
        raise _unsafe("the ratio must be positive", field_path)
    return number


def canonical_decimal(number: Decimal) -> str:
    """Format a finite decimal with the fixed six-place presentation precision."""

    with localcontext() as context:
        context.prec = 40
        quantized = number.quantize(PRECISION)
    text = format(quantized, "f")
    if text.startswith("-") and Decimal(text) == 0:
        text = text[1:]
    return text


def signed_decimal(value: object, field_path: str) -> Decimal:
    """Return ``value`` as an exact finite decimal that may be negative or zero."""

    if type(value) is bool:
        raise _unsafe("a percentage may not be a boolean", field_path)
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (int, float, str)):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise _unsafe("the percentage is not a decimal number", field_path) from error
    else:
        raise _unsafe("the percentage must be a decimal number", field_path)
    if not number.is_finite():
        raise _unsafe("the percentage must be finite", field_path)
    return number


def count_value(value: object, field_path: str) -> int:
    """Return a non-negative integer counter, rejecting bools."""

    if type(value) is bool or type(value) is not int:
        raise _unsafe("the count must be an integer", field_path)
    if value < 0:
        raise _unsafe("the count must not be negative", field_path)
    return value


def gain_percent(ratio: object, direction: str) -> str:
    """Convert a treatment/baseline ratio into a signed percentage gain.

    Lower-is-better metrics use ``100 * (1 - ratio)``; higher-is-better metrics
    use ``100 * (ratio - 1)``. A latency reduction is therefore not reported as
    a reciprocal speedup.
    """

    if direction not in DIRECTIONS:
        raise _unsafe("the metric direction must be 'lower' or 'higher'", "direction")
    number = decimal_value(ratio, "ratio")
    with localcontext() as context:
        context.prec = 40
        value = (
            Decimal(100) * (Decimal(1) - number)
            if direction == "lower"
            else Decimal(100) * (number - Decimal(1))
        )
    return canonical_decimal(value)


def effect_change_percentage_points(current_gain: object, historical_gain: object) -> str:
    """Return ``current_gain - historical_gain`` in percentage points."""

    current = signed_decimal(current_gain, "current_gain")
    historical = signed_decimal(historical_gain, "historical_gain")
    with localcontext() as context:
        context.prec = 40
        return canonical_decimal(current - historical)


def _uncertainty(interval: Mapping[str, Any] | None, method: str) -> dict[str, Any] | None:
    if interval is None:
        return None
    if not isinstance(interval, Mapping) or set(interval) != {"low", "high", "seed"}:
        raise _schema("an interval needs exactly low, high and seed", "uncertainty")
    low = canonical_decimal(decimal_value(interval["low"], "uncertainty.low"))
    high = canonical_decimal(decimal_value(interval["high"], "uncertainty.high"))
    if Decimal(low) > Decimal(high):
        raise _schema("an interval must not be inverted", "uncertainty")
    return {
        "low": low,
        "high": high,
        "method": method,
        "seed": count_value(interval["seed"], "uncertainty.seed"),
    }


def _stored_uncertainty(value: object) -> dict[str, Any] | None:
    """Validate an already-normalized interval (fixed low/high/method/seed shape)."""

    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"low", "high", "method", "seed"}:
        raise _schema("a stored interval needs exactly low, high, method and seed", "uncertainty")
    low = canonical_decimal(decimal_value(value["low"], "uncertainty.low"))
    high = canonical_decimal(decimal_value(value["high"], "uncertainty.high"))
    if Decimal(low) > Decimal(high):
        raise _schema("an interval must not be inverted", "uncertainty")
    if not isinstance(value["method"], str) or not value["method"]:
        raise _schema("an interval needs its method identity", "uncertainty.method")
    return {
        "low": low,
        "high": high,
        "method": value["method"],
        "seed": count_value(value["seed"], "uncertainty.seed"),
    }


def effect_row(
    *,
    study_id: str,
    run_id: str,
    campaign_id: str,
    lane_id: str,
    metric: str,
    unit: str,
    regime: str,
    direction: str,
    baseline: str,
    treatment: str,
    method_id: str,
    ratio: object,
    uncertainty: Mapping[str, Any] | None,
    decision: str,
    evidence_level: str,
    source_commit: str | None,
    host_environment: str | None,
    host_identity: str | None,
    input_digest: str,
    uncertainty_method: str,
) -> dict[str, Any]:
    """Build one normalized effect row with the closed 20-field shape."""

    if evidence_level not in (EVIDENCE_RECOMPUTED, EVIDENCE_AS_REPORTED):
        raise _schema("unknown evidence level", "evidence_level")
    number = decimal_value(ratio, "ratio")
    return {
        "study_id": study_id,
        "run_id": run_id,
        "campaign_id": campaign_id,
        "lane_id": lane_id,
        "metric": metric,
        "unit": unit,
        "regime": regime,
        "direction": direction,
        "baseline": baseline,
        "treatment": treatment,
        "method_id": method_id,
        "ratio": canonical_decimal(number),
        "gain_percent": gain_percent(number, direction),
        "uncertainty": _uncertainty(uncertainty, uncertainty_method),
        "decision": decision,
        "evidence_level": evidence_level,
        "source_commit": source_commit,
        "host_environment": host_environment,
        "host_identity": host_identity,
        "input_digest": input_digest,
    }


def validate_row(row: object) -> dict[str, Any]:
    """Validate one normalized effect row and return its canonical copy."""

    if not isinstance(row, Mapping):
        raise _schema("a relative-effect row must be an object", "row")
    if set(row) != set(ROW_KEYS):
        raise _schema("a relative-effect row has an unexpected shape", "row")
    direction = row["direction"]
    if direction not in DIRECTIONS:
        raise _unsafe("the metric direction must be 'lower' or 'higher'", "direction")
    number = decimal_value(row["ratio"], "ratio")
    expected_gain = gain_percent(number, direction)
    if row["gain_percent"] != expected_gain:
        raise _schema("the stored gain does not match its ratio", "gain_percent")
    _stored_uncertainty(row["uncertainty"])
    return dict(row)


def row_digest(row: Mapping[str, Any]) -> str:
    """Return the canonical content digest of one validated row."""

    return content_digest(validate_row(row))


def retained_effect_rows(
    *,
    study_id: str,
    run_id: str,
    lanes: Mapping[str, Any],
    input_digest: str,
    source_commit: str | None,
    host_environment: str | None,
    host_identity: str | None,
) -> list[dict[str, Any]]:
    """Project the existing paired-slot statistics into 72x6 effect rows per campaign."""

    rows: list[dict[str, Any]] = []
    for lane_id in sorted(lanes):
        record = lanes[lane_id]
        campaigns = record.get("campaigns")
        if not isinstance(campaigns, Mapping) or not campaigns:
            raise _schema("a retained lane needs its campaign records", "campaigns")
        for campaign_id in sorted(campaigns):
            campaign = campaigns[campaign_id]
            for numerator, denominator in RETAINED_COMPARISONS:
                ratio = campaign[f"R_{numerator}_{denominator}"]
                interval = campaign[f"CI_{numerator}_{denominator}"]
                rows.append(
                    effect_row(
                        study_id=study_id,
                        run_id=run_id,
                        campaign_id=campaign_id,
                        lane_id=lane_id,
                        metric="latency",
                        unit="ns",
                        regime=RETAINED_REGIME,
                        direction="lower",
                        baseline=denominator,
                        treatment=numerator,
                        method_id=RETAINED_METHOD_ID,
                        ratio=ratio,
                        uncertainty=interval,
                        decision=RETAINED_DECISION,
                        evidence_level=EVIDENCE_RECOMPUTED,
                        source_commit=source_commit,
                        host_environment=host_environment,
                        host_identity=host_identity,
                        input_digest=input_digest,
                        uncertainty_method="paired-slot-bootstrap-v1",
                    )
                )
    return rows


def cross_engine_effect_rows(
    *,
    study_id: str,
    run_id: str,
    analysis_lanes: Sequence[Mapping[str, Any]],
    input_digest: str,
    source_commit: str | None,
    host_environment: str | None,
    host_identity: str | None,
) -> list[dict[str, Any]]:
    """Project the existing descriptive comparison table into warm effect rows.

    The frozen comparison ratio is ``comparator / quervant``; the baseline arm is
    therefore ``quervant`` and the treatment arm the comparator, and latency is
    lower-is-better. No interval is invented for this descriptive table.
    """

    rows: list[dict[str, Any]] = []
    for lane in analysis_lanes:
        lane_id = lane["lane_id"]
        for comparison in lane["comparisons"]:
            rows.append(
                effect_row(
                    study_id=study_id,
                    run_id=run_id,
                    campaign_id="three-trial-backend",
                    lane_id=lane_id,
                    metric="latency",
                    unit="ns",
                    regime=CROSS_ENGINE_REGIME,
                    direction="lower",
                    baseline="quervant",
                    treatment=comparison["comparator"],
                    method_id=CROSS_ENGINE_METHOD_ID,
                    ratio=comparison["ratio"],
                    uncertainty=None,
                    decision=CROSS_ENGINE_DECISION,
                    evidence_level=EVIDENCE_RECOMPUTED,
                    source_commit=source_commit,
                    host_environment=host_environment,
                    host_identity=host_identity,
                    input_digest=input_digest,
                    uncertainty_method="none",
                )
            )
    return rows


def effect_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the uniqueness key of one effect row."""

    return tuple(str(row[name]) for name in MATCH_KEYS)


def unique_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate rows and reject duplicate coordinates."""

    seen: set[tuple[str, ...]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        validated = validate_row(row)
        key = effect_key(validated)
        if key in seen:
            raise _schema("duplicate relative-effect coordinates", "rows")
        seen.add(key)
        result.append(validated)
    return result


def compare_effect_rows(
    *,
    historical_rows: Sequence[Mapping[str, Any]],
    current_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bind comparable historical and current rows into proportional comparisons.

    Only matching workload coordinates, metric/unit/direction, arm roles and
    estimator may be compared. Source and environment differences are recorded as
    context, never as causality; anything else is ``NOT_COMPARABLE`` with a null
    effect change.
    """

    current_by_key = {effect_key(row): validate_row(row) for row in current_rows}
    comparisons: list[dict[str, Any]] = []
    for historical in historical_rows:
        validated = validate_row(historical)
        key = effect_key(validated)
        current = current_by_key.get(key)
        if current is None:
            comparisons.append(
                {
                    "historical_row_digest": row_digest(validated),
                    "current_row_digest": None,
                    "comparability": "NOT_COMPARABLE",
                    "context_changes": ["no-current-row"],
                    "effect_change_percentage_points": None,
                }
            )
            continue
        if {name: historical[name] for name in MATCH_KEYS} != {name: current[name] for name in MATCH_KEYS}:
            comparisons.append(
                {
                    "historical_row_digest": row_digest(validated),
                    "current_row_digest": row_digest(current),
                    "comparability": "NOT_COMPARABLE",
                    "context_changes": ["coordinate-mismatch"],
                    "effect_change_percentage_points": None,
                }
            )
            continue
        changes: list[str] = []
        if validated["source_commit"] != current["source_commit"]:
            changes.append("source-commit")
        if validated["host_environment"] != current["host_environment"]:
            changes.append("host-environment")
        if validated["host_identity"] != current["host_identity"]:
            changes.append("host-identity")
        if validated["method_id"] != current["method_id"]:
            changes.append("estimator")
        if validated["evidence_level"] != EVIDENCE_RECOMPUTED or current["evidence_level"] != EVIDENCE_RECOMPUTED:
            changes.append("as-reported")
        comparisons.append(
            {
                "historical_row_digest": row_digest(validated),
                "current_row_digest": row_digest(current),
                "comparability": "CONTEXT_CHANGED" if changes else "COMPARABLE",
                "context_changes": changes,
                "effect_change_percentage_points": effect_change_percentage_points(
                    current["gain_percent"], validated["gain_percent"]
                ),
            }
        )
    return comparisons


def validate_comparison(comparison: object) -> dict[str, Any]:
    """Validate one cross-run comparison record."""

    if not isinstance(comparison, Mapping) or set(comparison) != set(COMPARISON_KEYS):
        raise _schema("a comparison has an unexpected shape", "comparison")
    if comparison["comparability"] not in COMPARABILITY:
        raise _schema("unknown comparability label", "comparability")
    changes = comparison["context_changes"]
    if not isinstance(changes, list) or any(not isinstance(item, str) for item in changes):
        raise _schema("context changes must be a list of labels", "context_changes")
    change = comparison["effect_change_percentage_points"]
    if comparison["comparability"] == "NOT_COMPARABLE":
        if change is not None:
            raise _schema("a non-comparable pair cannot carry an effect change", "effect_change_percentage_points")
    else:
        if comparison["current_row_digest"] is None:
            raise _schema("a comparable pair needs both row digests", "current_row_digest")
        effect_change_percentage_points(change, "0")
    return dict(comparison)


def disclosure_payload(
    *,
    baseline_id: str,
    study_id: str,
    source_commit: str,
    current_raw_digest: str,
    rows: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the closed relative-effects disclosure document."""

    return {
        "kind": ROWS_KIND,
        "schema_version": DISCLOSURE_SCHEMA_VERSION,
        "baseline_id": baseline_id,
        "study_id": study_id,
        "source_commit": source_commit,
        "current_raw_digest": current_raw_digest,
        "rows": [validate_row(row) for row in rows],
        "comparisons": [validate_comparison(item) for item in comparisons],
    }


def validate_disclosure(document: object) -> dict[str, Any]:
    """Validate a relative-effects disclosure document."""

    if not isinstance(document, Mapping):
        raise _schema("the relative-effects document must be an object", "document")
    expected = {
        "kind",
        "schema_version",
        "baseline_id",
        "study_id",
        "source_commit",
        "current_raw_digest",
        "rows",
        "comparisons",
    }
    if set(document) != expected:
        raise _schema("the relative-effects document has an unexpected shape", "document")
    if document["kind"] != ROWS_KIND:
        raise _schema("unexpected relative-effects kind", "kind")
    if type(document["schema_version"]) is not int or document["schema_version"] != DISCLOSURE_SCHEMA_VERSION:
        raise _schema("unsupported relative-effects version", "schema_version")
    unique_rows(document["rows"])
    for comparison in document["comparisons"]:
        validate_comparison(comparison)
    return dict(document)


__all__ = [
    "COMPARABILITY",
    "COMPARISON_KEYS",
    "CROSS_ENGINE_DECISION",
    "CROSS_ENGINE_METHOD_ID",
    "DISCLOSURE_SCHEMA_VERSION",
    "DIRECTIONS",
    "EVIDENCE_AS_REPORTED",
    "EVIDENCE_RECOMPUTED",
    "MATCH_KEYS",
    "METHOD_ID",
    "RETAINED_COMPARISONS",
    "RETAINED_DECISION",
    "RETAINED_METHOD_ID",
    "ROWS_KIND",
    "ROW_KEYS",
    "canonical_decimal",
    "compare_effect_rows",
    "cross_engine_effect_rows",
    "decimal_value",
    "disclosure_payload",
    "effect_change_percentage_points",
    "effect_key",
    "effect_row",
    "gain_percent",
    "retained_effect_rows",
    "row_digest",
    "unique_rows",
    "validate_comparison",
    "validate_disclosure",
    "validate_row",
]

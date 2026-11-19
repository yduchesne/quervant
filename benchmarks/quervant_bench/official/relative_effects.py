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

import math
import re
from decimal import (
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    ROUND_HALF_EVEN,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

from ..config.codec import content_digest
from ..config.errors import BM_SCHEMA_INVALID, BM_UNSAFE_INPUT, BenchError
from ..config.identity import (
    validate_digest,
    validate_semantic_id,
    validate_source_commit,
    validate_uint64,
    validate_uuid4,
)

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

#: Literal ratio/interval field mapping of the frozen retained slot statistics.
#: ``(ratio_field, ci_field, baseline_arm, treatment_arm)``; every entry is a
#: lower-is-better latency ratio of the treatment against the baseline arm.
RETAINED_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ("R_L_A", "CI_L_A", "A", "L"),
    ("R_P_A", "CI_P_A", "A", "P"),
    ("R_H_A", "CI_H_A", "A", "H"),
    ("R_P_L", "CI_P_L", "L", "P"),
    ("R_H_L", "CI_H_L", "L", "H"),
    ("R_H_P", "CI_H_P", "P", "H"),
)
RETAINED_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (baseline, treatment) for _ratio, _ci, baseline, treatment in RETAINED_FIELDS
)
HISTORICAL_CROSS_METHOD_ID = "historical-three-trial-python-round6-v1"
STUDY_CROSS_ENGINE = "cross-engine-keyword-real-v1"
STUDY_RETAINED_KEY = "retained-key-topk-real-v1"
UNIQUE_KEYS = (
    "study_id",
    "run_id",
    "campaign_id",
    "lane_id",
    "metric",
    "unit",
    "regime",
    "baseline",
    "treatment",
    "method_id",
)
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


class Limits(NamedTuple):
    significant_digits: int
    adjusted_min: int
    adjusted_max: int


#: Value bounds apply after removing insignificant coefficient zeros. These are
#: input/resource guards, never scientific performance thresholds.
RATIO_LIMITS = Limits(128, -128, 128)
DERIVED_LIMITS = Limits(512, -256, 131)
MAX_TOKEN_CHARS = 1024
MAX_RAW_COEFFICIENT_DIGITS = 1024
MAX_INTEGER_BITS = 1800
MAX_EXPLICIT_EXPONENT = 1024
_TOKEN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE]([+-]?[0-9]{1,4}))?\Z")
_TRAPS = (
    InvalidOperation,
    DivisionByZero,
    Overflow,
    Underflow,
    Subnormal,
    Inexact,
    Rounded,
    Clamped,
    FloatOperation,
)


def _context(*, presentation: bool = False) -> Context:
    context = Context(
        prec=1024,
        rounding=ROUND_HALF_EVEN,
        Emin=-2048,
        Emax=2048,
        capitals=1,
        clamp=0,
        flags=[],
        traps=list(_TRAPS),
    )
    if presentation:
        context.traps[Inexact] = False
        context.traps[Rounded] = False
    return context


def _parts(value: Decimal, limits: Limits, field: str) -> tuple[int, str, int]:
    """Bound the coefficient before formatting or allocating powers of ten."""

    if not value.is_finite():
        raise _unsafe("number must be finite", field)
    sign, digits, exponent = value.as_tuple()
    if len(digits) > MAX_RAW_COEFFICIENT_DIGITS:
        raise _unsafe("numeric coefficient exceeds its input budget", field)
    if value.is_zero():
        return 0, "0", 0
    while len(digits) > 1 and digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    adjusted = len(digits) + exponent - 1
    if len(digits) > limits.significant_digits or not limits.adjusted_min <= adjusted <= limits.adjusted_max:
        raise _unsafe("number is outside the declared decimal bounds", field)
    return sign, "".join(str(digit) for digit in digits), exponent


def _format(value: Decimal, limits: Limits, field: str) -> str:
    """Canonical finite decimal: no exponent, plus sign, redundant zero or -0."""

    sign, digits, exponent = _parts(value, limits, field)
    if digits == "0":
        return "0"
    if exponent >= 0:
        text = digits + "0" * exponent
    else:
        point = len(digits) + exponent
        text = (
            digits[:point] + "." + digits[point:]
            if point > 0
            else "0." + "0" * (-point) + digits
        )
    return ("-" if sign else "") + text


def _number(value: object, field: str, *, limits: Limits, positive: bool) -> Decimal:
    """Producer input parser; float identity is exactly ``Decimal(str(float))``."""

    if type(value) is Decimal:
        result = value
    else:
        if type(value) is int:
            if value.bit_length() > MAX_INTEGER_BITS:
                raise _unsafe("integer exceeds its input budget", field)
            token = str(value)
        elif type(value) is float:
            if not math.isfinite(value):
                raise _unsafe("number must be finite", field)
            token = str(value)  # Deliberately not Decimal.from_float(value).
        elif type(value) is str:
            token = value
        else:
            raise _unsafe(
                "expected int, float, Decimal or numeric string; bool is forbidden", field
            )
        if len(token) > MAX_TOKEN_CHARS:
            raise _unsafe("numeric token exceeds its input budget", field)
        match = _TOKEN.fullmatch(token)
        if match is None:
            raise _unsafe("number is not a supported decimal literal", field)
        exponent_text = match.group(1)
        if exponent_text is not None and abs(int(exponent_text)) > MAX_EXPLICIT_EXPONENT:
            raise _unsafe("explicit exponent exceeds its input budget", field)
        try:
            result = Decimal(token, context=_context())
        except (DecimalException, ValueError, OverflowError) as error:
            raise _unsafe("invalid decimal input", field) from error
    _parts(result, limits, field)
    if positive and (result.is_zero() or result.is_signed()):
        raise _unsafe("ratio must be strictly positive", field)
    return Decimal(0) if result.is_zero() else result


def decimal_value(value: object, field_path: str) -> Decimal:
    """Bounded, positive producer ratio parsing; no formatting or rounding."""

    return _number(value, field_path, limits=RATIO_LIMITS, positive=True)


def canonical_decimal(number: Decimal) -> str:
    """Exact canonical formatting; never quantizes evidence."""

    if type(number) is not Decimal:
        raise _unsafe("canonical formatter requires a Decimal", "decimal")
    return _format(number, DERIVED_LIMITS, "decimal")


def signed_decimal(value: object, field_path: str) -> Decimal:
    """Bounded, signed producer percentage parsing."""

    return _number(value, field_path, limits=DERIVED_LIMITS, positive=False)


def normalize_ratio(value: object, field: str = "ratio") -> str:
    """Return the canonical producer form of a ratio."""

    return _format(decimal_value(value, field), RATIO_LIMITS, field)


def normalize_derived(value: object, field: str = "gain_percent") -> str:
    """Return the canonical producer form of a signed percentage."""

    return _format(signed_decimal(value, field), DERIVED_LIMITS, field)


def stored_ratio(value: object, field: str = "ratio") -> Decimal:
    """Require an already-canonical persisted ratio string."""

    if type(value) is not str:
        raise _schema("stored ratio must be a canonical decimal string", field)
    canonical = normalize_ratio(value, field)
    if value != canonical:
        raise _schema("stored ratio is not canonical", field)
    return _number(value, field, limits=RATIO_LIMITS, positive=True)


def stored_derived(value: object, field: str = "gain_percent") -> Decimal:
    """Require an already-canonical persisted percentage string."""

    if type(value) is not str:
        raise _schema("stored percentage must be a canonical decimal string", field)
    canonical = normalize_derived(value, field)
    if value != canonical:
        raise _schema("stored percentage is not canonical", field)
    return _number(value, field, limits=DERIVED_LIMITS, positive=False)


def gain_percent(ratio: object, direction: str) -> str:
    """Exact signed gain of a treatment/baseline ratio within one run."""

    if type(direction) is not str or direction not in DIRECTIONS:
        raise _unsafe("unknown metric direction", "direction")
    value = decimal_value(ratio, "ratio")
    try:
        with localcontext(_context()):
            delta = Decimal(1) - value if direction == "lower" else value - Decimal(1)
            gain = Decimal(100) * delta
    except DecimalException as error:
        raise _unsafe("exact gain arithmetic exceeded declared bounds", "ratio") from error
    return canonical_decimal(gain)


def effect_change_percentage_points(current_gain: object, historical_gain: object) -> str:
    """Exact percentage-point difference of two signed gains."""

    current = signed_decimal(current_gain, "current_gain")
    historical = signed_decimal(historical_gain, "historical_gain")
    try:
        with localcontext(_context()):
            difference = current - historical
    except DecimalException as error:
        raise _unsafe(
            "exact difference exceeded declared bounds", "effect_change_percentage_points"
        ) from error
    return canonical_decimal(difference)


def interval_endpoints(low: object, high: object) -> dict[str, str]:
    """Validate the original endpoints in order before any rendering."""

    lower = _number(low, "uncertainty.low", limits=RATIO_LIMITS, positive=True)
    upper = _number(high, "uncertainty.high", limits=RATIO_LIMITS, positive=True)
    if lower > upper:
        raise _schema("interval endpoints are inverted", "uncertainty")
    return {
        "low": _format(lower, RATIO_LIMITS, "uncertainty.low"),
        "high": _format(upper, RATIO_LIMITS, "uncertainty.high"),
    }


def _uncertainty(interval: Mapping[str, object] | None, method: str) -> dict[str, object] | None:
    """Constructor interval handling: preserve the complete ratio CI and seed."""

    if interval is None:
        return None
    if not isinstance(interval, Mapping) or set(interval) != {"low", "high", "seed"}:
        raise _schema("source interval needs exactly low, high and seed", "uncertainty")
    endpoints = interval_endpoints(interval["low"], interval["high"])
    return {
        **endpoints,
        "method": validate_semantic_id(method, "uncertainty.method"),
        "seed": validate_uint64(interval["seed"], "uncertainty.seed"),
    }


def _stored_uncertainty(interval: object) -> dict[str, object] | None:
    """Persisted interval validation: canonical endpoints and the same seed bound."""

    if interval is None:
        return None
    if not isinstance(interval, Mapping) or set(interval) != {"low", "high", "method", "seed"}:
        raise _schema("stored interval needs exactly low, high, method and seed", "uncertainty")
    low = stored_ratio(interval["low"], "uncertainty.low")
    high = stored_ratio(interval["high"], "uncertainty.high")
    endpoints = interval_endpoints(low, high)
    if type(interval["method"]) is not str:
        raise _schema("interval method must be a string", "uncertainty.method")
    return {
        **endpoints,
        "method": validate_semantic_id(interval["method"], "uncertainty.method"),
        "seed": validate_uint64(interval["seed"], "uncertainty.seed"),
    }


def render_six(value: object) -> str:
    """Presentation only; never feed this output to identity or comparison code."""

    number = _number(value, "display", limits=DERIVED_LIMITS, positive=False)
    try:
        with localcontext(_context(presentation=True)):
            rounded = number.quantize(Decimal("0.000001"))
    except DecimalException as error:
        raise _unsafe("presentation arithmetic exceeded declared bounds", "display") from error
    return "0.000000" if rounded.is_zero() else format(rounded, "f")


def checked_key(row: Mapping[str, object], names: Sequence[str]) -> tuple[str, ...]:
    """Extract identity keys without coercing wrong-typed values."""

    values = []
    for name in names:
        value = row.get(name)
        if type(value) is not str or not value:
            raise _schema("comparison identity must be a nonempty string", name)
        values.append(value)
    return tuple(values)


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
    uncertainty_method: str = "paired-slot-bootstrap-v1",
) -> dict[str, Any]:
    """Build one normalized effect row with the closed 20-field shape."""

    if evidence_level not in (EVIDENCE_RECOMPUTED, EVIDENCE_AS_REPORTED):
        raise _schema("unknown evidence level", "evidence_level")
    for name, value in (
        ("study_id", study_id),
        ("run_id", run_id),
        ("campaign_id", campaign_id),
        ("lane_id", lane_id),
        ("metric", metric),
        ("unit", unit),
        ("regime", regime),
        ("direction", direction),
        ("baseline", baseline),
        ("treatment", treatment),
        ("method_id", method_id),
        ("decision", decision),
    ):
        if type(value) is not str or not value:
            raise _schema("a row identity field must be a nonempty string", name)
    ratio_text = normalize_ratio(ratio)
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
        "ratio": ratio_text,
        "gain_percent": gain_percent(ratio_text, direction),
        "uncertainty": _uncertainty(uncertainty, uncertainty_method),
        "decision": decision,
        "evidence_level": evidence_level,
        "source_commit": source_commit,
        "host_environment": host_environment,
        "host_identity": host_identity,
        "input_digest": input_digest,
    }


_HOST_ENVIRONMENTS = ("native-linux", "wsl2")
_HISTORICAL_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_RETAINED_CAMPAIGNS = ("d3c-v3r3-strategies-01", "d3c-v3r3-strategies-02")


def _printable(value: object, limit: int, field_path: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value) > limit:
        raise _schema("host identity fields must be bounded printable strings", field_path)
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        raise _schema("host identity fields must be printable ASCII", field_path)
    return value


def _digest(value: object, field_path: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value.startswith("sha256:") or len(value) != 71:
        raise _schema("a digest must be sha256: plus 64 lowercase hex digits", field_path)
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise _schema("a digest must be lowercase hexadecimal", field_path)
    return value


RET_CI_METHOD = "paired-slot-bootstrap-v1"


def _require_str(value: object, field_path: str) -> str:
    if type(value) is not str or not value:
        raise _schema("expected a nonempty string", field_path)
    return value


def _printable_context(value: object, limit: int, field_path: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value) > limit:
        raise _schema("historical context must be a bounded printable string", field_path)
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        raise _schema("historical context must be printable ASCII", field_path)
    return value


def validate_row(
    row: object, *, current: bool = True, study_id: str | None = None
) -> dict[str, Any]:
    """Structural and numeric validation of one normalized effect row.

    Acceptance establishes shape and internal consistency only; provenance is bound
    by the owning current or historical reader. Authority is never selected from the
    row's own ``evidence_level``.
    """

    if type(current) is not bool:
        raise _schema("current must be an actual boolean", "current")
    if not isinstance(row, Mapping):
        raise _schema("a relative-effect row must be an object", "row")
    if set(row) != set(ROW_KEYS):
        raise _schema("a relative-effect row has an unexpected shape", "row")
    study = _require_str(row["study_id"], "study_id")
    if study_id is not None:
        _require_str(study_id, "study_id")
        if study != study_id:
            raise _schema("the row belongs to another study", "study_id")
    if study not in (STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY):
        raise _schema("unknown study identity", "study_id")
    if _require_str(row["direction"], "direction") not in DIRECTIONS:
        raise _schema("unknown metric direction", "direction")
    if row["direction"] != "lower":
        raise _schema("registered rows are lower-is-better latency", "direction")
    if (row["metric"], row["unit"], row["regime"]) != ("latency", "ns", "warm"):
        raise _schema("only warm latency rows are registered", "metric")
    lane = _require_str(row["lane_id"], "lane_id")
    if lane not in set(lane_ids(study)):
        raise _schema("the lane is not a registered workload coordinate", "lane_id")
    level = row["evidence_level"]
    if level not in (EVIDENCE_RECOMPUTED, EVIDENCE_AS_REPORTED):
        raise _schema("unknown evidence level", "evidence_level")
    if current and level != EVIDENCE_RECOMPUTED:
        raise _schema("current rows are always RECOMPUTED", "evidence_level")
    validate_digest(row["input_digest"], "input_digest")
    if current:
        validate_uuid4(row["run_id"], "run_id")
        validate_source_commit(row["source_commit"], "source_commit")
        validate_digest(row["host_identity"], "host_identity")
        if row["host_environment"] not in _HOST_ENVIRONMENTS:
            raise _schema("current host environment must be a real environment", "host_environment")
    else:
        run_id = _require_str(row["run_id"], "run_id")
        if _HISTORICAL_RUN_ID.fullmatch(run_id) is None:
            raise _schema("historical run identities are catalog tokens", "run_id")
        if row["source_commit"] is not None:
            validate_source_commit(row["source_commit"], "source_commit")
        _printable_context(row["host_identity"], 256, "host_identity")
        _printable_context(row["host_environment"], 64, "host_environment")
    campaign = _require_str(row["campaign_id"], "campaign_id")
    baseline = _require_str(row["baseline"], "baseline")
    treatment = _require_str(row["treatment"], "treatment")
    method = _require_str(row["method_id"], "method_id")
    decision = _require_str(row["decision"], "decision")
    if study == STUDY_RETAINED_KEY:
        if campaign not in _RETAINED_CAMPAIGNS:
            raise _schema("unknown retained campaign", "campaign_id")
        if (baseline, treatment) not in RETAINED_PAIRS:
            raise _schema("unknown retained arm pair", "baseline")
        if method != RETAINED_METHOD_ID:
            raise _schema("unknown retained estimator identity", "method_id")
        if decision != RETAINED_DECISION:
            raise _schema("retained rows are descriptive effects only", "decision")
        interval = _stored_uncertainty(row["uncertainty"])
        if interval is None:
            raise _schema("a retained row needs its original interval", "uncertainty")
        if interval["method"] != RET_CI_METHOD:
            raise _schema("retained intervals use the paired-slot method", "uncertainty")
        if row["uncertainty"] != interval:
            raise _schema("stored interval is not canonical", "uncertainty")
    else:
        if campaign != "three-trial-backend":
            raise _schema("unknown cross-engine campaign", "campaign_id")
        if baseline != "quervant" or treatment not in ("lucene", "tantivy"):
            raise _schema("cross-engine rows compare quervant against one comparator", "treatment")
        allowed = (CROSS_ENGINE_METHOD_ID,) if current else (
            CROSS_ENGINE_METHOD_ID,
            HISTORICAL_CROSS_METHOD_ID,
        )
        if method not in allowed:
            raise _schema("unknown cross-engine estimator identity", "method_id")
        if decision != CROSS_ENGINE_DECISION:
            raise _schema("cross-engine rows are descriptive INCONCLUSIVE", "decision")
        _stored_uncertainty(row["uncertainty"])
        if row["uncertainty"] is not None:
            raise _schema("cross-engine rows carry no interval", "uncertainty")
    ratio = stored_ratio(row["ratio"])
    expected_gain = gain_percent(ratio, row["direction"])
    if row["gain_percent"] != expected_gain:
        raise _schema("the stored gain does not match its ratio", "gain_percent")
    stored_derived(row["gain_percent"])
    validated = dict(row)
    validated["uncertainty"] = _stored_uncertainty(row["uncertainty"])
    return validated


def lane_ids(study_id: str) -> tuple[str, ...]:
    """Return the registered warm lane set of one study."""

    from .admission import d3c_lane_ids, pr15d_warm_lane_ids

    if study_id == STUDY_CROSS_ENGINE:
        return tuple(pr15d_warm_lane_ids())
    if study_id == STUDY_RETAINED_KEY:
        return tuple(d3c_lane_ids())
    raise _schema("unknown study identity", "study_id")


def row_digest(row: Mapping[str, Any]) -> str:
    """Return the canonical content digest of one validated row."""

    return content_digest(validate_row(row, current=False))


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
    """Project the paired-slot statistics into 72x2x6 effect rows via the literal mapping."""

    rows: list[dict[str, Any]] = []
    for lane_id in sorted(lanes):
        record = lanes[lane_id]
        campaigns = record.get("campaigns")
        if not isinstance(campaigns, Mapping) or not campaigns:
            raise _schema("a retained lane needs its campaign records", "campaigns")
        for campaign_id in sorted(campaigns):
            campaign = campaigns[campaign_id]
            for ratio_field, ci_field, baseline, treatment in RETAINED_FIELDS:
                rows.append(
                    effect_row(
                        study_id=study_id,
                        run_id=run_id,
                        campaign_id=campaign_id,
                        lane_id=lane_id,
                        metric="latency",
                        unit="ns",
                        regime="warm",
                        direction="lower",
                        baseline=baseline,
                        treatment=treatment,
                        method_id=RETAINED_METHOD_ID,
                        ratio=campaign[ratio_field],
                        uncertainty=campaign[ci_field],
                        decision=RETAINED_DECISION,
                        evidence_level=EVIDENCE_RECOMPUTED,
                        source_commit=source_commit,
                        host_environment=host_environment,
                        host_identity=host_identity,
                        input_digest=input_digest,
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
    evidence_level: str = EVIDENCE_RECOMPUTED,
    method_id: str = CROSS_ENGINE_METHOD_ID,
) -> list[dict[str, Any]]:
    """Project the descriptive comparison table into warm effect rows."""

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
                    regime="warm",
                    direction="lower",
                    baseline="quervant",
                    treatment=comparison["comparator"],
                    method_id=method_id,
                    ratio=comparison["ratio"],
                    uncertainty=None,
                    decision=CROSS_ENGINE_DECISION,
                    evidence_level=evidence_level,
                    source_commit=source_commit,
                    host_environment=host_environment,
                    host_identity=host_identity,
                    input_digest=input_digest,
                )
            )
    return rows


def unique_rows(rows: Iterable[Mapping[str, Any]], *, current: bool = True) -> list[dict[str, Any]]:
    """Validate rows and reject duplicate identities (including the run identity)."""

    seen: set[tuple[str, ...]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        validated = validate_row(row, current=current)
        key = checked_key(validated, UNIQUE_KEYS)
        if key in seen:
            raise _schema("duplicate relative-effect identity", "rows")
        seen.add(key)
        result.append(validated)
    return result


def current_index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
    """Return the unambiguous current lookup; reject duplicates and mixed runs."""

    result: dict[tuple[str, ...], dict[str, Any]] = {}
    runs_by_study: dict[str, str] = {}
    for row in unique_rows(rows, current=True):
        key = checked_key(row, MATCH_KEYS)
        study = row["study_id"]
        run = row["run_id"]
        if study in runs_by_study and runs_by_study[study] != run:
            raise _schema("multiple current runs for one study", "run_id")
        runs_by_study[study] = run
        if key in result:
            raise _schema("ambiguous current relative-effect coordinate", "rows")
        result[key] = row
    return result


CONTEXT_LABEL_ORDER = ("source-commit", "host-environment", "host-identity", "as-reported")


def compare_effect_rows(
    *,
    historical_rows: Sequence[Mapping[str, Any]],
    current_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bind eligible historical rows to current rows by exact match keys only."""

    current_by_key = current_index(current_rows)
    comparisons: list[dict[str, Any]] = []
    historical = unique_rows(historical_rows, current=False)
    historical.sort(key=lambda row: checked_key(row, UNIQUE_KEYS))
    for row in historical:
        key = checked_key(row, MATCH_KEYS)
        current = current_by_key.get(key)
        if current is None:
            comparisons.append(
                {
                    "historical_row_digest": row_digest(row),
                    "current_row_digest": None,
                    "comparability": "NOT_COMPARABLE",
                    "context_changes": ["no-current-row"],
                    "effect_change_percentage_points": None,
                }
            )
            continue
        changes: list[str] = []
        for label, field, limit in (
            ("source-commit", "source_commit", None),
            ("host-environment", "host_environment", 64),
            ("host-identity", "host_identity", 256),
        ):
            if row[field] is None or row[field] != current[field]:
                changes.append(label)
        if row["evidence_level"] == EVIDENCE_AS_REPORTED:
            changes.append("as-reported")
        comparisons.append(
            {
                "historical_row_digest": row_digest(row),
                "current_row_digest": row_digest(current),
                "comparability": "COMPARABLE" if not changes else "CONTEXT_CHANGED",
                "context_changes": changes,
                "effect_change_percentage_points": effect_change_percentage_points(
                    current["gain_percent"], row["gain_percent"]
                ),
            }
        )
    return comparisons


def validate_comparison(comparison: object) -> dict[str, Any]:
    """Validate one closed cross-run comparison record."""

    if not isinstance(comparison, Mapping) or set(comparison) != set(COMPARISON_KEYS):
        raise _schema("a comparison has an unexpected shape", "comparison")
    comparability = comparison["comparability"]
    if comparability not in COMPARABILITY:
        raise _schema("unknown comparability label", "comparability")
    changes = comparison["context_changes"]
    if not isinstance(changes, list) or any(type(item) is not str for item in changes):
        raise _schema("context changes must be a list of labels", "context_changes")
    if len(set(changes)) != len(changes):
        raise _schema("context change labels must be unique", "context_changes")
    validate_digest(comparison["historical_row_digest"], "historical_row_digest")
    change = comparison["effect_change_percentage_points"]
    if comparability == "NOT_COMPARABLE":
        if changes != ["no-current-row"]:
            raise _schema(
                "a non-comparable pair is recorded only as no-current-row", "context_changes"
            )
        if comparison["current_row_digest"] is not None or change is not None:
            raise _schema(
                "a non-comparable pair carries no current row or change", "comparability"
            )
        return dict(comparison)
    validate_digest(comparison["current_row_digest"], "current_row_digest")
    if change is None:
        raise _schema(
            "a comparable pair needs its change", "effect_change_percentage_points"
        )
    stored_derived(change)
    expected = [label for label in CONTEXT_LABEL_ORDER if label in changes]
    if changes != expected:
        raise _schema("context change labels must keep the fixed order", "context_changes")
    if comparability == "COMPARABLE" and changes:
        raise _schema("a comparable pair has no context changes", "comparability")
    if comparability == "CONTEXT_CHANGED" and not changes:
        raise _schema("a contextual pair names at least one change", "comparability")
    return dict(comparison)


def _header(envelope: Mapping[str, Any], field: str, value: object) -> str:
    """Shared scalar-header check for the builder and the validator."""

    if field == "baseline_id":
        validate_uuid4(value, field)
    elif field == "source_commit":
        validate_source_commit(value, field)
    elif field == "current_raw_digest":
        validate_digest(value, field)
    elif field == "study_id":
        if _require_str(value, field) not in (STUDY_CROSS_ENGINE, STUDY_RETAINED_KEY):
            raise _schema("unknown study identity", field)
    else:  # pragma: no cover - internal misuse guard
        raise _schema("unknown envelope header", field)
    return str(value)


def expected_grid(study_id: str) -> set[tuple[str, str, str, str]]:
    """Return the complete (campaign, lane, baseline, treatment) family grid."""

    grid: set[tuple[str, str, str, str]] = set()
    if study_id == STUDY_CROSS_ENGINE:
        for lane in lane_ids(STUDY_CROSS_ENGINE):
            for comparator in ("lucene", "tantivy"):
                grid.add(("three-trial-backend", lane, "quervant", comparator))
    elif study_id == STUDY_RETAINED_KEY:
        for lane in lane_ids(STUDY_RETAINED_KEY):
            for campaign in _RETAINED_CAMPAIGNS:
                for baseline, treatment in RETAINED_PAIRS:
                    grid.add((campaign, lane, baseline, treatment))
    else:
        raise _schema("unknown study identity", "study_id")
    return grid


def disclosure_payload(
    *,
    baseline_id: str,
    study_id: str,
    source_commit: str,
    current_raw_digest: str,
    rows: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the eight-key relative-effects document (structural only)."""

    document = {
        "kind": ROWS_KIND,
        "schema_version": DISCLOSURE_SCHEMA_VERSION,
        "baseline_id": baseline_id,
        "study_id": study_id,
        "source_commit": source_commit,
        "current_raw_digest": current_raw_digest,
        "rows": list(rows),
        "comparisons": list(comparisons),
    }
    for field in ("baseline_id", "study_id", "source_commit", "current_raw_digest"):
        _header(document, field, document[field])
    return document


def validate_disclosure(document: object) -> dict[str, Any]:
    """Mandatory complete-family boundary for one relative-effects document."""

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
    for field in ("baseline_id", "study_id", "source_commit", "current_raw_digest"):
        _header(document, field, document[field])
    study = document["study_id"]
    rows_value = document["rows"]
    comparisons_value = document["comparisons"]
    if not isinstance(rows_value, list) or not isinstance(comparisons_value, list):
        raise _schema("rows and comparisons must be lists", "rows")
    rows = unique_rows(rows_value, current=True)
    current_index(rows)
    hosts: set[tuple[str, str]] = set()
    coordinates: list[tuple[str, str, str, str]] = []
    for row in rows:
        if row["study_id"] != study:
            raise _schema("a row belongs to another study", "rows")
        if row["source_commit"] != document["source_commit"]:
            raise _schema("a row cites another source commit", "rows")
        if row["input_digest"] != document["current_raw_digest"]:
            raise _schema("a row cites another raw series", "rows")
        hosts.add((row["host_environment"], row["host_identity"]))
        coordinates.append(
            (row["campaign_id"], row["lane_id"], row["baseline"], row["treatment"])
        )
    if len(hosts) != 1:
        raise _schema("one current run cannot cite mixed measured host contexts", "rows")
    grid = expected_grid(study)
    if len(coordinates) != len(set(coordinates)):
        raise _schema("the disclosure repeats a family coordinate", "rows")
    if set(coordinates) != grid:
        raise _schema("the disclosure is not the complete family grid", "rows")
    known = {row_digest(row) for row in rows}
    comparisons = [validate_comparison(item) for item in comparisons_value]
    for comparison in comparisons:
        digest = comparison["current_row_digest"]
        if digest is not None and digest not in known:
            raise _schema("a comparison cites an unknown current row", "comparisons")
    return {**dict(document), "rows": rows, "comparisons": comparisons}


__all__ = [
    "COMPARABILITY",
    "COMPARISON_KEYS",
    "CONTEXT_LABEL_ORDER",
    "CROSS_ENGINE_DECISION",
    "CROSS_ENGINE_METHOD_ID",
    "DISCLOSURE_SCHEMA_VERSION",
    "DIRECTIONS",
    "EVIDENCE_AS_REPORTED",
    "EVIDENCE_RECOMPUTED",
    "HISTORICAL_CROSS_METHOD_ID",
    "MATCH_KEYS",
    "METHOD_ID",
    "RETAINED_DECISION",
    "RETAINED_FIELDS",
    "RETAINED_METHOD_ID",
    "RETAINED_PAIRS",
    "ROWS_KIND",
    "ROW_KEYS",
    "UNIQUE_KEYS",
    "canonical_decimal",
    "checked_key",
    "compare_effect_rows",
    "cross_engine_effect_rows",
    "current_index",
    "decimal_value",
    "disclosure_payload",
    "effect_change_percentage_points",
    "effect_row",
    "expected_grid",
    "gain_percent",
    "interval_endpoints",
    "lane_ids",
    "normalize_derived",
    "normalize_ratio",
    "render_six",
    "retained_effect_rows",
    "row_digest",
    "signed_decimal",
    "stored_derived",
    "stored_ratio",
    "unique_rows",
    "validate_comparison",
    "validate_disclosure",
    "validate_row",
]

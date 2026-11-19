"""Gate C: independent reference verification of real official evidence.

This module never imports :mod:`quervant_bench.official.analysis`. It rebuilds the
certified numbers from the authenticated raw samples with its own implementations
of the frozen medians, nearest-rank percentiles, exact ratios, dispersion, overlap
and control windows, recomputes every query answer independently, and compares the
results field by field with the Gate B record. A forged but coherently rehashed
analysis is therefore rejected.
"""

from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from typing import Any, Mapping, Sequence

from ..config.codec import canonical_payload_bytes, content_digest
from ..config.errors import (
    BM_EVIDENCE_UNAVAILABLE,
    BM_IDENTITY_INVALID,
    BM_SCHEMA_INVALID,
    BM_UNSAFE_INPUT,
    BenchError,
)
from ..qualification.contracts import document_digest
from .admission import (
    D3C_CAMPAIGN_NAMES,
    D3C_CONTROL_NAME,
    AdmittedCrossEngine,
    AdmittedRetainedKey,
    admitted_inventory_digest,
    d3c_lane_ids,
    hash_raw_members,
    load_pr15d_oracle,
    pr15d_lane_field,
    pr15d_lane_id,
    verify_authorized_source,
)
from .contracts import (
    DECISION_INCONCLUSIVE,
    DECISION_POLICY_NOT_DERIVABLE,
    STATISTICS_CROSS_ENGINE,
    STATISTICS_RETAINED_KEY,
    VERIFIER_CHECK_IDS,
    validate_official_analysis,
    validate_official_policy,
    validate_official_verification,
)
from .protocols import (
    D3C_AA_WINDOWS,
    PR15D_ENGINES,
    STUDY_CROSS_ENGINE,
    STUDY_RETAINED_KEY,
    OfficialFreeze,
    require_freeze,
    verify_backend_protocol,
)

REFERENCE_ID = "official-independent-reference-v1"
REFERENCE_VERSION = 1
DISPERSION_LIMIT = Fraction(11, 10)
CONTROL_SOFT_OUTLIERS = 1

#: Retained-key arm letters -> official semantic arm identifiers (duplicated
#: deliberately so Gate C does not import Gate B's mapping).
REF_ARM_LABELS: dict[str, str] = {
    "A": "base",
    "H": "exact-set",
    "L": "linear",
    "P": "prefilter",
}

CLAIM_CONFIG = (
    "pinned-authorization",
    "pinned-template",
    "pinned-source-set",
    "pinned-backend-protocol",
)
CLAIM_CROSS_ENGINE = (
    "control-windows",
    "lane-answers",
    "lane-medians",
    "lane-ratios",
    "policy-decision",
    "raw-inventory",
    "schedule-shape",
    "source-identity",
)
CLAIM_RETAINED_KEY = (
    "control-windows",
    "lane-answers",
    "lane-blocks",
    "lane-medians",
    "policy-decision",
    "raw-inventory",
    "schedule-shape",
    "source-identity",
)


class VerificationFailure(BenchError):
    """A typed Gate C failure (never converted into a pass)."""


def _fail(message: str, field: str) -> VerificationFailure:
    return VerificationFailure(BM_IDENTITY_INVALID, message, field_path=field)


# ---------------------------------------------------------------------------
# Independent primitives (deliberately duplicated from Gate B)
# ---------------------------------------------------------------------------


def ref_lower_median(values: Sequence[int]) -> int:
    ordered = list(sorted(values))
    if not ordered:
        raise _fail("the reference median needs at least one value", "median")
    return ordered[(len(ordered) - 1) // 2]


def ref_percentile(values: Sequence[int], percentile: int) -> int:
    ordered = list(sorted(values))
    if not ordered:
        raise _fail("the reference percentile needs at least one value", "percentile")
    index = -(-(percentile * len(ordered)) // 100) - 1
    return ordered[index]


def ref_ratio(numerator: int, denominator: int) -> Fraction:
    if numerator <= 0 or denominator <= 0:
        raise _fail("the reference ratio needs positive operands", "ratio")
    return Fraction(numerator, denominator)


def ref_decimal(value: Fraction) -> str:
    scaled = value * 1_000_000
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    if remainder * 2 >= scaled.denominator:
        whole += 1
    return f"{whole // 1_000_000}.{whole % 1_000_000:06d}"


def ref_windows(windows: Mapping[str, str]) -> dict[str, Fraction]:
    parsed: dict[str, Fraction] = {}
    for name, raw in windows.items():
        whole, separator, fraction = str(raw).partition(".")
        if not separator or len(fraction) != 6 or not whole.isdigit() or not fraction.isdigit():
            raise _fail("a control window is not a six-digit decimal", name)
        parsed[name] = Fraction(int(whole) * 1_000_000 + int(fraction), 1_000_000)
    return parsed


def ref_control_lane_pass(ratios: Sequence[Fraction], *, exempt: bool) -> bool:
    if not ratios:
        raise _fail("a control lane needs at least one block ratio", "ratios")
    ordered = sorted(ratios)
    count = len(ordered)
    if count % 2:
        median = ordered[count // 2]
    else:
        median = (ordered[count // 2 - 1] + ordered[count // 2]) / 2
    parsed = ref_windows(D3C_AA_WINDOWS)
    outliers = [ratio for ratio in ratios if not parsed["block_min"] <= ratio <= parsed["block_max"]]
    within_median = parsed["median_min"] <= median <= parsed["median_max"]
    if exempt:
        window_ok = len(outliers) <= CONTROL_SOFT_OUTLIERS and all(
            parsed["exempt_hard_min"] <= ratio <= parsed["exempt_hard_max"] for ratio in ratios
        )
    else:
        window_ok = not outliers
    return bool(within_median and window_ok)


# ---------------------------------------------------------------------------
# Independent lane enumeration
# ---------------------------------------------------------------------------


def ref_cross_engine_lanes() -> list[tuple[int, str, int, str]]:
    return [
        (n, class_name, k, regime)
        for n in (10_000, 100_000)
        for class_name in ("absent", "rare", "medium", "common")
        for k in (10, 100)
        for regime in ("process_cold", "warm")
    ]


def ref_retained_key_lanes() -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for n in (10_000, 100_000):
        for class_name in ("absent", "rare", "medium", "common"):
            field, term = pr15d_lane_field(class_name)
            for k in (1, 10, 32, 64, 100, 128, 256, 512, 1024):
                lanes.append(
                    {
                        "lane_id": pr15d_lane_id(n, class_name, k),
                        "n": n,
                        "class": class_name,
                        "field": field,
                        "term": term,
                        "k": k,
                    }
                )
    return lanes


@lru_cache(maxsize=None)
def _ref_identifiers(n: int, class_name: str) -> tuple[str, ...]:
    if class_name == "absent":
        return ()
    if class_name == "rare":
        return ("d00000000",)
    if class_name == "medium":
        return tuple("d%08d" % index for index in range(0, n, 8))
    if class_name == "common":
        return tuple("d%08d" % index for index in range(2, n, 2))
    raise _fail("unknown retained-key class", "class")


def ref_retained_key_answer(n: int, class_name: str, k: int) -> dict[str, Any]:
    identifiers = _ref_identifiers(n, class_name)
    return {"total_hits": len(identifiers), "doc_ids": list(identifiers[:k])}


def ref_cross_engine_answers(n: int) -> dict[tuple[str, str, int], dict[str, Any]]:
    """Rebuild expected answers from the corpus row formula, independently."""

    oracle = load_pr15d_oracle()
    rows = oracle.build_row_formula(n)
    answers: dict[tuple[str, str, int], dict[str, Any]] = {}
    for class_name in ("absent", "rare", "medium", "common"):
        field, term = pr15d_lane_field(class_name)
        position = 1 if field == "key" else 2
        matches: list[str] = []
        for row in rows:
            if row[position] == term:
                matches.append(row[0])
        if matches != sorted(matches):
            raise _fail("the independently rebuilt answer set is not ordered", "doc_ids")
        for k in (10, 100):
            answers[(class_name, field, k)] = {
                "total_hits": len(matches),
                "doc_ids": matches[:k],
            }
    return answers


# ---------------------------------------------------------------------------
# Cross-engine reference recomputation
# ---------------------------------------------------------------------------


def _ref_cross_engine_statistics(
    admitted: AdmittedCrossEngine,
) -> dict[str, Any]:
    lanes: dict[str, Any] = {}
    answers_cache: dict[int, dict[tuple[str, str, int], dict[str, Any]]] = {}
    for key in ref_cross_engine_lanes():
        n, class_name, k, regime = key
        field, term = pr15d_lane_field(class_name)
        lane_id = pr15d_lane_id(n, class_name, k)
        if n not in answers_cache:
            answers_cache[n] = ref_cross_engine_answers(n)
        expected = answers_cache[n][(class_name, field, k)]
        for trial in range(1, 4):
            for engine in PR15D_ENGINES:
                lane = admitted.lane(trial, engine, key)
                samples = lane.get("samples_ns")
                if not isinstance(samples, list) or len(samples) != 20:
                    raise _fail("a raw lane does not hold twenty samples", "samples_ns")
                for sample in samples:
                    if isinstance(sample, bool) or not isinstance(sample, int) or sample <= 0:
                        raise _fail("a raw sample is not a positive integer", "samples_ns")
                if lane.get("total_hits") != expected["total_hits"]:
                    raise _fail(
                        f"lane {lane_id} ({engine} trial {trial}) total_hits differs from the reference oracle",
                        "total_hits",
                    )
                if list(lane.get("doc_ids") or []) != list(expected["doc_ids"]):
                    raise _fail(
                        f"lane {lane_id} ({engine} trial {trial}) doc_ids differ from the reference oracle",
                        "doc_ids",
                    )
                summary = lane.get("summary_ns") or {}
                if summary.get("count") != len(samples):
                    raise _fail("a raw lane summary count differs from the reference", "summary_ns")
                if summary.get("min") != min(samples) or summary.get("max") != max(samples):
                    raise _fail(
                        "a raw lane summary min/max differs from the reference samples",
                        "summary_ns",
                    )
                if summary.get("median") != ref_lower_median(samples):
                    raise _fail("a raw lane median is not the reference median", "summary_ns")
                if summary.get("p95") != ref_percentile(samples, 95):
                    raise _fail("a raw lane p95 is not the reference percentile", "summary_ns")
                if summary.get("p99") != ref_percentile(samples, 99):
                    raise _fail("a raw lane p99 is not the reference percentile", "summary_ns")
        if regime != "warm":
            continue
        per_engine: dict[str, Any] = {}
        for engine in PR15D_ENGINES:
            trial_medians = [
                ref_lower_median(admitted.lane(trial, engine, key)["samples_ns"])
                for trial in range(1, 4)
            ]
            per_engine[engine] = {
                "trial_medians_ns": trial_medians,
                "median_ns": ref_lower_median(trial_medians),
                "min_ns": min(trial_medians),
                "max_ns": max(trial_medians),
                "dispersion": ref_decimal(ref_ratio(max(trial_medians), min(trial_medians))),
            }
        base = per_engine["quervant"]
        comparisons: dict[str, Any] = {}
        for comparator in ("lucene", "tantivy"):
            entry = per_engine[comparator]
            dispersion_ok = (
                ref_ratio(entry["max_ns"], entry["min_ns"]) <= DISPERSION_LIMIT
                and ref_ratio(base["max_ns"], base["min_ns"]) <= DISPERSION_LIMIT
            )
            overlap = not (
                entry["max_ns"] < base["min_ns"] or base["max_ns"] < entry["min_ns"]
            )
            comparisons[comparator] = {
                "ratio": ref_decimal(ref_ratio(entry["median_ns"], base["median_ns"])),
                "dispersion_ok": bool(dispersion_ok),
                "ranges_overlap": bool(overlap),
                "inconclusive": bool((not dispersion_ok) or overlap),
            }
        lanes[lane_id] = {"per_engine": per_engine, "comparisons": comparisons}
    return lanes


def _ref_cross_engine_control(control: Mapping[str, Any]) -> bool:
    lanes = control.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != 16:
        raise _fail("the control assessment does not cover sixteen warm lanes", "lanes")
    recorded = control.get("a_a")
    if not isinstance(recorded, Mapping):
        raise _fail("the control assessment has no A/A section", "a_a")
    if recorded.get("passes") is not True:
        return False
    lane_results = recorded.get("lanes")
    if not isinstance(lane_results, Mapping) or set(lane_results) != set(str(item) for item in lanes):
        raise _fail("the control A/A lane set differs from the declared lanes", "lanes")
    windows = control.get("windows")
    if not isinstance(windows, Mapping) or dict(windows) != dict(D3C_AA_WINDOWS):
        raise _fail("the control assessment does not carry the frozen windows", "windows")
    for lane_id in lanes:
        entry = lane_results[str(lane_id)]
        ratios = [Fraction(item) for item in entry.get("block_ratios", [])]
        if len(ratios) != 12:
            raise _fail("a control lane must hold twelve block ratios", "block_ratios")
        n = int(str(lane_id).split("/")[1])
        class_name = str(lane_id).split("/")[2]
        exempt = n == 10_000 and class_name in ("absent", "rare")
        expected_pass = ref_control_lane_pass(ratios, exempt=exempt)
        if bool(entry.get("passes")) != expected_pass:
            raise _fail("a control lane pass flag differs from the reference rule", "passes")
        median = sorted(ratios)
        count = len(median)
        reference_median = (
            median[count // 2]
            if count % 2
            else (median[count // 2 - 1] + median[count // 2]) / 2
        )
        if str(entry.get("median_ratio")) != ref_decimal(reference_median):
            raise _fail("a control lane median ratio differs from the reference", "median_ratio")
    return True


# ---------------------------------------------------------------------------
# Retained-key reference recomputation
# ---------------------------------------------------------------------------


def _ref_block_medians(
    slots: Sequence[Mapping[str, Any]], *, arm: str, lane_id: str
) -> list[int]:
    per_block: dict[int, list[int]] = {}
    for slot in slots:
        if slot.get("arm") != arm:
            continue
        block = int(slot["block"])
        for lane in slot["lanes"]:
            if lane.get("id") == lane_id:
                per_block.setdefault(block, []).append(int(lane["summary_ns"]["median"]))
                break
        else:  # pragma: no cover - guarded by admission
            raise _fail("a retained-key slot is missing a lane", "lanes")
    medians: list[int] = []
    for block in range(1, 13):
        values = per_block.get(block, [])
        if len(values) != 2:
            raise _fail("each retained-key arm must appear twice per block", "block")
        medians.append((values[0] + values[1]) // 2)
    return medians


def _ref_cap(template: Mapping[str, Any], *, n: int, class_name: str) -> Fraction:
    raw = (
        template["statistics"]["within_arm_exclusion_cap_100k_medium_common"]
        if n == 100_000 and class_name in ("medium", "common")
        else template["statistics"]["within_arm_exclusion_cap_other"]
    )
    whole, _, fraction = str(raw).partition(".")
    return Fraction(int(whole) * 1_000_000 + int(fraction), 1_000_000)


def _ref_retained_key_statistics(
    admitted: AdmittedRetainedKey, template: Mapping[str, Any]
) -> dict[str, Any]:
    minimum_retained = int(template["statistics"]["min_retained_blocks_per_lane"])
    records: dict[tuple[str, str], Any] = {}
    for campaign in D3C_CAMPAIGN_NAMES:
        slots = admitted.slots[campaign]
        for lane in ref_retained_key_lanes():
            expected = ref_retained_key_answer(lane["n"], lane["class"], lane["k"])
            for slot in slots:
                record = next(
                    (item for item in slot["lanes"] if item.get("id") == lane["lane_id"]),
                    None,
                )
                if record is None:
                    raise _fail("a retained-key slot is missing a lane", "lanes")
                if record.get("total_hits") != expected["total_hits"]:
                    raise _fail("a retained-key lane total_hits differs from the reference", "total_hits")
                if list(record.get("doc_ids") or []) != list(expected["doc_ids"]):
                    raise _fail("a retained-key lane doc_ids differ from the reference", "doc_ids")
                samples = record.get("samples_ns")
                if not isinstance(samples, list) or len(samples) != 20:
                    raise _fail("a retained-key lane does not hold twenty samples", "samples_ns")
                summary = record["summary_ns"]
                if summary["median"] != ref_lower_median(samples):
                    raise _fail("a retained-key lane median is not the reference median", "summary_ns")
                if summary["count"] != len(samples) or summary["min"] != min(samples) or summary["max"] != max(samples):
                    raise _fail(
                        "a retained-key lane summary differs from the reference samples",
                        "summary_ns",
                    )
            per_arm: dict[str, Any] = {}
            insufficient = False
            for letter, arm in sorted(REF_ARM_LABELS.items(), key=lambda item: item[1]):
                values = _ref_block_medians(slots, arm=letter, lane_id=lane["lane_id"])
                cap = _ref_cap(template, n=lane["n"], class_name=lane["class"])
                lowest = min(values)
                retained = [
                    index
                    for index, value in enumerate(values, start=1)
                    if Fraction(value, lowest) <= cap
                ]
                excluded = [index for index in range(1, 13) if index not in retained]
                if len(retained) < minimum_retained:
                    insufficient = True
                per_arm[arm] = {
                    "blocks": 12,
                    "block_medians_ns": values,
                    "retained_block_indices": retained,
                    "excluded_block_indices": excluded,
                    "retained_median_ns": ref_lower_median([values[index - 1] for index in retained]),
                }
            records[(campaign, lane["lane_id"])] = {
                "campaign_id": campaign,
                "lane_id": lane["lane_id"],
                "n": lane["n"],
                "class": lane["class"],
                "k": lane["k"],
                "arms": per_arm,
                "status": "inconclusive-insufficient-blocks" if insufficient else "analyzed",
            }
    return records


def _ref_retained_key_control(admitted: AdmittedRetainedKey) -> bool:
    slots = admitted.slots[D3C_CONTROL_NAME]
    lane_ids = d3c_lane_ids()
    if len(slots) != 48:
        raise _fail("the retained-key control does not hold 48 slots", "slots")
    by_arm: dict[str, dict[int, dict[int, dict[str, int]]]] = {}
    for slot in slots:
        arm = str(slot["arm"])
        block = int(slot["block"])
        position = int(slot["position"])
        if [lane.get("id") for lane in slot["lanes"]] != lane_ids:
            raise _fail("a control slot lane order differs from the frozen order", "lanes")
        by_arm.setdefault(arm, {}).setdefault(block, {})[position] = {
            str(lane["id"]): int(lane["summary_ns"]["median"]) for lane in slot["lanes"]
        }
    for lane_id in lane_ids:
        ratios: list[Fraction] = []
        for block in range(1, 13):
            a_positions = sorted(by_arm.get("A", {}).get(block, {}))
            b_positions = sorted(by_arm.get("B", {}).get(block, {}))
            if len(a_positions) != 2 or len(b_positions) != 2:
                raise _fail("each control arm must appear twice per block", "slots")
            a_values = [by_arm["A"][block][position][lane_id] for position in a_positions]
            b_values = [by_arm["B"][block][position][lane_id] for position in b_positions]
            ratios.append(
                ref_ratio(
                    (b_values[0] + b_values[1]) // 2,
                    (a_values[0] + a_values[1]) // 2,
                )
            )
        n = int(lane_id.split("/")[1])
        class_name = lane_id.split("/")[2]
        exempt = n == 10_000 and class_name in ("absent", "rare")
        if not ref_control_lane_pass(ratios, exempt=exempt):
            return False
    return True


# ---------------------------------------------------------------------------
# Field-by-field comparison
# ---------------------------------------------------------------------------


def _compare_cross_engine(
    analysis: Mapping[str, Any], reference: Mapping[str, Any]
) -> None:
    statistics = analysis.get("statistics")
    if not isinstance(statistics, Mapping) or statistics.get("method_id") != STATISTICS_CROSS_ENGINE:
        raise _fail("the analysis does not use the cross-engine method", "statistics_method_id")
    lanes = statistics.get("lanes")
    if not isinstance(lanes, list):
        raise _fail("the analysis statistics have no lane array", "lanes")
    if len(lanes) != len(reference):
        raise _fail("the analysis lane count differs from the reference", "lanes")
    for record in lanes:
        lane_id = record.get("lane_id")
        if lane_id not in reference:
            raise _fail("the analysis holds an unknown lane", "lane_id")
        expected = reference[lane_id]
        per_engine = record.get("per_engine") or {}
        for engine in PR15D_ENGINES:
            observed = per_engine.get(engine) or {}
            want = expected["per_engine"][engine]
            for name in ("trial_medians_ns", "median_ns", "min_ns", "max_ns", "dispersion"):
                if observed.get(name) != want[name]:
                    raise _fail(
                        f"lane {lane_id} {engine} {name} differs from the reference",
                        name,
                    )
        comparisons = {entry.get("comparator"): entry for entry in record.get("comparisons") or []}
        if set(comparisons) != {"lucene", "tantivy"}:
            raise _fail("the analysis comparisons do not cover both comparators", "comparisons")
        for comparator, want in expected["comparisons"].items():
            observed = comparisons[comparator]
            for name in ("ratio", "dispersion_ok", "ranges_overlap", "inconclusive"):
                if observed.get(name) != want[name]:
                    raise _fail(
                        f"lane {lane_id} {comparator} {name} differs from the reference",
                        name,
                    )


def _compare_retained_key(
    analysis: Mapping[str, Any], reference: Mapping[tuple[str, str], Any]
) -> None:
    statistics = analysis.get("statistics")
    if not isinstance(statistics, Mapping) or statistics.get("method_id") != STATISTICS_RETAINED_KEY:
        raise _fail("the analysis does not use the retained-key method", "statistics_method_id")
    lanes = statistics.get("lanes")
    if not isinstance(lanes, list):
        raise _fail("the analysis statistics have no lane array", "lanes")
    observed_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in lanes:
        key = (str(record.get("campaign_id")), str(record.get("lane_id")))
        if key in observed_map:
            raise _fail("the analysis repeats a (campaign, lane) pair", "lanes")
        observed_map[key] = record
    if set(observed_map) != set(reference):
        raise _fail("the analysis lane set differs from the reference", "lanes")
    for key, want in reference.items():
        observed = observed_map[key]
        for name in ("n", "class", "k", "status"):
            if observed.get(name) != want[name]:
                raise _fail(f"{key} {name} differs from the reference", name)
        arms = observed.get("arms") or {}
        if set(arms) != set(REF_ARM_LABELS.values()):
            raise _fail("the analysis arm set differs from the frozen arms", "arms")
        for arm, arm_want in want["arms"].items():
            arm_observed = arms[arm]
            for name in (
                "blocks",
                "block_medians_ns",
                "retained_block_indices",
                "excluded_block_indices",
                "retained_median_ns",
            ):
                if arm_observed.get(name) != arm_want[name]:
                    raise _fail(f"{key} arm {arm} {name} differs from the reference", name)


def _expected_policy_status(study_id: str) -> str:
    return (
        DECISION_INCONCLUSIVE
        if study_id == STUDY_CROSS_ENGINE
        else DECISION_POLICY_NOT_DERIVABLE
    )


# ---------------------------------------------------------------------------
# Public verification
# ---------------------------------------------------------------------------


def _require_exact_admitted_record(
    submitted: AdmittedCrossEngine | AdmittedRetainedKey,
    authoritative: AdmittedCrossEngine | AdmittedRetainedKey,
) -> None:
    """Require the submitted record to equal the freshly authenticated one.

    Exact family and the admitted dataclasses' complete recursive field equality are
    checked first, so no family-specific field is read before the family guard. For
    cross-engine records the canonical JSON content of the control assessment is
    additionally compared, because Python equality is not type-sensitive for nested
    scalars (`12 == 12.0`). A caller-modified in-memory record therefore cannot reach
    RV-04/RV-07 even when the on-disk raw bytes and outer digests are unchanged.
    """

    if type(submitted) is not type(authoritative) or submitted != authoritative:
        raise _fail(
            "the in-memory admission differs from freshly authenticated raw evidence",
            "admission",
        )
    if type(submitted) is AdmittedCrossEngine and (
        canonical_payload_bytes(dict(submitted.control))
        != canonical_payload_bytes(dict(authoritative.control))
    ):
        raise _fail(
            "the submitted control differs from freshly authenticated raw evidence",
            "admission",
        )


def verify_official_study(
    *,
    admitted: AdmittedCrossEngine | AdmittedRetainedKey,
    template: Mapping[str, Any],
    authorization: Any,
    analysis: Mapping[str, Any],
    policy: Mapping[str, Any],
    source_root: Any | None = None,
    observed: Mapping[str, Any] | None = None,
    admission: Any | None = None,
    policy_inputs: Any | None = None,
) -> dict[str, Any]:
    """Run the independent Gate C registry and return the assessment record.

    Production verification derives the freeze from a verified external
    authorization; a parsed freeze is never sufficient.
    """

    from .admission import (
        AdmittedCrossEngine as _AdmittedCrossEngine,
    )
    from .admission import (
        AdmittedRetainedKey as _AdmittedRetainedKey,
    )
    from .admission import (
        VerifiedOfficialAdmission,
        reverify_official_admission,
    )
    from .authorization import (
        VerifiedOfficialAuthorization,
        require_verified_official_authorization,
    )

    study_id = template.get("study_id")
    if type(admitted) not in (_AdmittedCrossEngine, _AdmittedRetainedKey):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "Gate C requires an admitted cross-engine or retained-key record",
            field_path="admission",
        )
    if not isinstance(authorization, VerifiedOfficialAuthorization):
        raise BenchError(
            BM_UNSAFE_INPUT,
            "Gate C requires a verified official authorization capability",
            field_path="authorization",
        )
    # The mode comes from the verified authorization, never from the caller's record.
    fixture_mode = authorization.fixture_only is True
    if bool(getattr(admitted, "fixture_only", False)) != fixture_mode:
        raise BenchError(
            BM_UNSAFE_INPUT,
            "the admitted record mode does not match the verified authorization mode",
            field_path="admission",
        )
    freeze = require_verified_official_authorization(
        authorization,
        study_id=str(study_id),
        for_production=not fixture_mode,
        observed=observed,
    )
    require_freeze(freeze, str(study_id))

    if fixture_mode:
        if admission is not None and not isinstance(admission, VerifiedOfficialAdmission):
            raise BenchError(
                BM_UNSAFE_INPUT,
                "the admission guard must be a verified capability",
                field_path="admission",
            )
    else:
        if not isinstance(admission, VerifiedOfficialAdmission):
            raise BenchError(
                BM_UNSAFE_INPUT,
                "production Gate C requires a VerifiedOfficialAdmission capability",
                field_path="admission",
            )
        if source_root is None:
            raise BenchError(
                BM_EVIDENCE_UNAVAILABLE,
                "production Gate C requires the authorized source root",
                field_path="source_root",
            )
        if (
            admission.raw_series_root_digest != admitted.raw_series_root_digest
            or admission.admission_index_digest
            != document_digest(dict(admitted.admission_index))
            or admission.authorization_digest != freeze.authorization_digest
        ):
            raise _fail(
                "the verified admission capability does not match the record under test",
                "admission",
            )
        # Mandatory fresh re-admission: only bytes re-authenticated here may be used.
        authoritative = reverify_official_admission(
            admission,
            authorization=authorization,
            template=template,
            source_root=source_root,
            observed=observed,
        )
        _require_exact_admitted_record(admitted, authoritative)
        admitted = authoritative
    validated_analysis = validate_official_analysis(dict(analysis))
    validated_policy = validate_official_policy(dict(policy))
    subject = dict(admitted.admission_index["subject"])

    # RV-01-SCOPE
    for document, label in (
        (validated_analysis, "analysis"),
        (validated_policy, "policy"),
    ):
        if (document.get("evidence_origin"), document.get("qualification_scope")) != (
            "real",
            "official",
        ):
            raise _fail(f"{label} is not real/official evidence", "qualification_scope")
        if document.get("subject") != subject:
            raise _fail(f"{label} subject differs from the authorized subject", "subject")
        if document.get("study_id") != study_id:
            raise _fail(f"{label} study differs from the template", "study_id")

    # RV-02-G0
    if freeze.design_digest != document_digest(dict(template)):
        raise _fail("the template digest differs from the authorized design", "design_digest")
    backend = verify_backend_protocol(template)
    if backend["raw_digest"] != template["backend_protocol_identity"]["raw_sha256"]:
        raise _fail("the backend protocol bytes changed", "backend_protocol_digest")
    if freeze.backend_protocol_digest != backend["raw_digest"]:
        raise _fail("the authorized backend protocol digest differs", "backend_protocol_digest")
    if source_root is not None:
        verify_authorized_source(source_root, freeze)

    # RV-03-RAW-INVENTORY + RV-10-POST-READ-INTEGRITY
    records_before, _total = hash_raw_members(
        admitted.raw_root, [member["path"] for member in admitted.inventory]
    )
    if records_before != list(dict(member) for member in admitted.inventory):
        raise _fail("the raw inventory differs from the admitted inventory", "raw-series-root")
    digest_before = admitted_inventory_digest(admitted)
    if digest_before != validated_analysis["raw_series_root_digest"]:
        raise _fail(
            "the analysis raw-series digest does not match the reference inventory",
            "raw_series_root_digest",
        )

    # RV-04-ORACLE + RV-05-SCHEDULE + RV-07-STATISTICS
    if isinstance(admitted, AdmittedCrossEngine):
        if study_id != STUDY_CROSS_ENGINE:
            raise _fail("the admitted family does not match the template", "study_id")
        reference = _ref_cross_engine_statistics(admitted)
        _compare_cross_engine(validated_analysis, reference)
        claims = CLAIM_CROSS_ENGINE
    elif isinstance(admitted, AdmittedRetainedKey):
        if study_id != STUDY_RETAINED_KEY:
            raise _fail("the admitted family does not match the template", "study_id")
        reference = _ref_retained_key_statistics(admitted, template)
        _compare_retained_key(validated_analysis, reference)
        claims = CLAIM_RETAINED_KEY
    else:  # pragma: no cover - defensive
        raise BenchError(BM_UNSAFE_INPUT, "admitted evidence has an unknown family")

    # RV-06-HOST-CONTROLS
    if isinstance(admitted, AdmittedCrossEngine):
        if not _ref_cross_engine_control(admitted.control):
            raise _fail("the reference control rule rejects the A/A assessment", "a_a")
    else:
        if not _ref_retained_key_control(admitted):
            raise _fail("the reference control rule rejects the retained-key A/A", "a_a")
    if content_digest(dict(admitted.control_assessment if isinstance(admitted, AdmittedRetainedKey) else admitted.control)) != validated_analysis["control_result_digest"]:
        raise _fail("the analysis does not bind the admitted control result", "control_result_digest")

    # RV-08-POLICY
    if policy_inputs is not None:
        from .contracts import retained_policy_decisions
        from .policy_inputs import reverify_retained_policy_inputs
        from .policy_reference import reference_retained_policy

        if type(admitted) is not AdmittedRetainedKey or validated_policy["schema_version"] != 2 or getattr(policy_inputs, "scope", None) != "official":
            raise _fail("verified retained inputs require the complete retained policy schema", "policy_inputs")
        fresh_policy_record, memory = reverify_retained_policy_inputs(
            policy_inputs, admitted=admitted, for_production=not fixture_mode
        )
        expected_payload = reference_retained_policy(fresh_policy_record, memory, policy_inputs.inputs_digest)
        if canonical_payload_bytes(validated_policy["retained_key_policy"]) != canonical_payload_bytes(expected_payload):
            raise _fail("retained policy differs from independent raw-slot recomputation", "retained_key_policy")
        expected_decisions = retained_policy_decisions(expected_payload)
        for name, expected_value in expected_decisions.items():
            if validated_policy[name] != expected_value:
                raise _fail("retained policy summary differs from independent decisions", name)
    else:
        expected_status = _expected_policy_status(str(study_id))
        if validated_policy["schema_version"] != 1 or validated_policy["decision_status"] != expected_status:
            raise _fail(
                "the policy decision requires authentic retained policy inputs",
                "decision_status",
            )
        if validated_policy["performance_claim_allowed"] is not False:
            raise _fail("the frozen v1 policy cannot allow a performance claim", "performance_claim_allowed")
    if validated_policy["analysis_digest"] != document_digest(validated_analysis):
        raise _fail("the policy does not bind the analysis digest", "analysis_digest")
    policy_underivable = validated_policy["decision_status"] == DECISION_POLICY_NOT_DERIVABLE

    # RV-09-IDENTITY
    for name in (
        "approved_design_digest",
        "authorization_digest",
        "source_set_digest",
        "host_identity_digest",
        "binary_manifest_digest",
        "corpus_manifest_digest",
        "original_verifier_digest",
    ):
        if admitted.admission_index.get(name) != getattr(freeze, _freeze_field(name)):
            raise _fail(
                f"the admission index {name} differs from the authorized identity",
                name,
            )

    # RV-10-POST-READ-INTEGRITY
    digest_after = admitted_inventory_digest(admitted)
    if digest_after != digest_before:
        raise _fail("raw evidence changed after it was read", "raw-series-root")
    if policy_inputs is not None:
        reverify_retained_policy_inputs(policy_inputs, admitted=admitted, for_production=not fixture_mode)

    check_ids = list(VERIFIER_CHECK_IDS)
    claims = sorted(set(CLAIM_CONFIG) | set(claims))
    if policy_underivable:
        # A required policy that cannot be derived is a typed block, never a
        # partial verification pass (RV-08 is not certified).
        check_ids = [item for item in check_ids if item != "RV-08-POLICY"]
        claims = [item for item in claims if item != "policy-decision"]
    assessment = {
        "kind": "official-verification-assessment",
        "schema_version": 1,
        "evidence_origin": "real",
        "qualification_scope": "official",
        "subject": subject,
        "status": "BLOCKED" if policy_underivable else "VERIFIED_REAL",
        "study_id": study_id,
        "raw_series_root_digest": validated_analysis["raw_series_root_digest"],
        "analysis_digest": document_digest(validated_analysis),
        "policy_digest": document_digest(validated_policy),
        "reference_id": REFERENCE_ID,
        "check_ids": check_ids,
        "verified_claims": claims,
    }
    return validate_official_verification(assessment)


def _freeze_field(name: str) -> str:
    mapping = {
        "approved_design_digest": "design_digest",
        "authorization_digest": "authorization_digest",
        "source_set_digest": "source_file_set_digest",
        "host_identity_digest": "host_preflight_digest",
        "binary_manifest_digest": "binary_manifest_digest",
        "corpus_manifest_digest": "corpus_manifest_digest",
        "original_verifier_digest": "original_reference_verifier_digest",
    }
    if name not in mapping:  # pragma: no cover - guarded by the caller
        raise _fail("unknown identity field", name)
    return mapping[name]


def blocked_assessment(
    *,
    subject: Mapping[str, Any],
    study_id: str,
    raw_series_root_digest: str,
    reason_field: str,
) -> dict[str, Any]:
    """Return a typed blocked assessment (never a partial pass)."""

    raise BenchError(
        BM_EVIDENCE_UNAVAILABLE,
        "Gate C cannot certify this study without the required evidence",
        field_path=reason_field,
    )


__all__ = [
    "CLAIM_CROSS_ENGINE",
    "CLAIM_RETAINED_KEY",
    "REFERENCE_ID",
    "REFERENCE_VERSION",
    "VerificationFailure",
    "blocked_assessment",
    "ref_control_lane_pass",
    "ref_cross_engine_answers",
    "ref_decimal",
    "ref_lower_median",
    "ref_percentile",
    "ref_ratio",
    "ref_retained_key_answer",
    "ref_windows",
    "verify_official_study",
]

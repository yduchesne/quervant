"""Primary migrated T7/F2 policy, derived from authenticated raw slot samples.

This is a distinct statistical method from the official descriptive block table.
It preserves T7's symmetric within-block filtering, ordinary median, paired
10,000-draw bootstrap and F2's decisive-failure precedence and strict tie bound.
"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import math
import random
import statistics
from typing import Any, Mapping, Sequence

from ..config.codec import content_digest
from ..config.errors import BM_IDENTITY_INVALID, BenchError
from .admission import AdmittedRetainedKey
from .policy_inputs import (
    ARMS, BOOTSTRAP_DRAWS, CAMPAIGNS, CI_HIGH_INDEX, CI_LOW_INDEX, CLASSES,
    H_LIMIT_BYTES, KS, NS, POLICY_METHOD, PROTOCOL_SHA256,
)


def required_lanes(k: int) -> tuple[str, ...]:
    return tuple(f"pr15d_v1/{n}/{name}/k{k}" for n in NS for name in CLASSES)


def _bad(message: str) -> BenchError:
    return BenchError(BM_IDENTITY_INVALID, message, field_path="retained_key_policy")


def _seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{PROTOCOL_SHA256}|{label}".encode()).digest()[:8], "big")


def paired_interval(
    blocks: Mapping[str, Mapping[int, int]], retained: Sequence[int],
    numerator: str, denominator: str, campaign: str, lane_id: str,
) -> dict[str, Any]:
    seed = _seed(f"{campaign}|{lane_id}|{numerator}/{denominator}")
    a = [blocks[numerator][index] for index in retained]
    b = [blocks[denominator][index] for index in retained]
    if len(set(a)) == len(set(b)) == 1:
        lo = hi = a[0] / b[0]
    else:
        rng = random.Random(seed)
        values = []
        for _ in range(BOOTSTRAP_DRAWS):
            draw = [rng.randrange(len(retained)) for _ in retained]
            values.append(statistics.median([a[index] for index in draw]) / statistics.median([b[index] for index in draw]))
        values.sort()
        lo, hi = values[CI_LOW_INDEX], values[CI_HIGH_INDEX]
    return {"low": lo, "high": hi, "seed": seed}


def derive_slot_statistics(admitted: AdmittedRetainedKey) -> tuple[dict[str, Any], dict[tuple[str, str], Any]]:
    """Recompute the old T7 inputs from samples, without trusting a supplied analysis."""

    lanes: dict[str, Any] = {}
    authenticated_slots: dict[tuple[str, str], Any] = {}
    all_ids = {lane for k in KS for lane in required_lanes(k)}
    for campaign in CAMPAIGNS:
        slots = admitted.slots.get(campaign, ())
        if len(slots) != 96:
            raise _bad("retained policy requires ninety-six slots per treatment campaign")
        pairs = {lane: {arm: {block: [] for block in range(1, 13)} for arm in ARMS} for lane in all_ids}
        positions = set()
        for slot in slots:
            arm, block, position = slot.get("arm"), slot.get("block"), slot.get("position")
            if arm not in ARMS or type(block) is not int or block not in range(1, 13) or type(position) is not int or position not in range(1, 9) or (block, position) in positions:
                raise _bad("retained policy slot schedule is incomplete or repeated")
            positions.add((block, position))
            by_id = {lane.get("id"): lane for lane in slot.get("lanes", ())}
            if set(by_id) != all_ids or len(slot["lanes"]) != len(all_ids):
                raise _bad("retained policy requires every frozen lane in each slot")
            for lane_id, lane in by_id.items():
                samples = lane.get("samples_ns")
                if not isinstance(samples, list) or len(samples) != 20 or any(type(value) is not int or value <= 0 for value in samples):
                    raise _bad("retained policy requires twenty positive integer samples")
                measured = sorted(samples)[9]
                if type(lane.get("summary_ns", {}).get("median")) is not int or lane["summary_ns"]["median"] != measured:
                    raise _bad("retained policy slot summary differs from its raw samples")
                pairs[lane_id][arm][block].append(measured)
        for lane_id in sorted(all_ids):
            _, n_text, class_name, k_text = lane_id.split("/")
            n, k = int(n_text), int(k_text[1:])
            by = pairs[lane_id]
            if any(len(by[arm][block]) != 2 for arm in ARMS for block in range(1, 13)):
                raise _bad("every arm must occur twice in every retained-policy block")
            cap = 1.25 if n == 100_000 and class_name in ("medium", "common") else 1.50
            retained = [block for block in range(1, 13) if all(max(by[arm][block]) / min(by[arm][block]) <= cap for arm in ARMS)]
            block_values = {arm: {block: sum(by[arm][block]) // 2 for block in range(1, 13)} for arm in ARMS}
            if len(retained) < 4:
                # The old F2 evaluator rejects absent ratio/CI fields in this
                # case. Preserve an explicit missing-input failure, never invent
                # a decision from fewer than the frozen minimum four blocks.
                raise _bad(f"fewer than four symmetric retained blocks for {campaign}/{lane_id}")
            latency = {arm: statistics.median([block_values[arm][block] for block in retained]) for arm in ARMS}
            raw = {arm: statistics.median(list(block_values[arm].values())) for arm in ARMS}
            sign_raw, sign_filtered = raw["P"] - raw["H"], latency["P"] - latency["H"]
            rec: dict[str, Any] = {
                "retained": retained, "retained_count": len(retained), "latency": latency,
                "raw_latency": raw,
                "filter_sensitive": ((sign_raw > 0) != (sign_filtered > 0) or (sign_raw == 0) != (sign_filtered == 0)),
            }
            for num, den in (("L", "A"), ("P", "A"), ("H", "A"), ("P", "L"), ("H", "L"), ("H", "P")):
                rec[f"R_{num}_{den}"] = latency[num] / latency[den]
                rec[f"CI_{num}_{den}"] = paired_interval(block_values, retained, num, den, campaign, lane_id)
            lanes.setdefault(lane_id, {"id": lane_id, "n": n, "class": class_name, "k": k, "campaigns": {}})["campaigns"][campaign] = rec
            authenticated_slots[(campaign, lane_id)] = {"retained": retained, "block": block_values}
    return lanes, authenticated_slots


def _candidate(lanes: Mapping[str, Any], campaign: str, k: int, candidate: str, memory: int) -> dict[str, Any]:
    decisive = ["EXCLUDED_MEMORY"] if candidate == "H" and memory > H_LIMIT_BYTES else []
    uncertain: list[str] = []
    sensitive = False
    for lane_id in required_lanes(k):
        rec = lanes[lane_id]["campaigns"][campaign]
        if rec["filter_sensitive"]:
            sensitive = True
            uncertain.append(f"FILTER_SENSITIVE:{lane_id}")
        ratio = float(rec[f"R_{candidate}_A"])
        lo, hi = rec[f"CI_{candidate}_A"]["low"], rec[f"CI_{candidate}_A"]["high"]
        target = "/100000/medium/" in lane_id or "/100000/common/" in lane_id
        if target:
            if not (ratio <= .97 and hi < 1.0):
                (decisive if ratio > .97 and lo > .97 else uncertain).append(f"{'NO_PRIMARY_GAIN' if ratio > .97 and lo > .97 else 'TARGET_CI'}:{lane_id}")
        elif not (ratio <= 1.10 and hi <= 1.10):
            (decisive if ratio > 1.10 and lo > 1.10 else uncertain).append(f"{'REGRESSION' if ratio > 1.10 and lo > 1.10 else 'GUARD_CI'}:{lane_id}")
    targets = [lanes[f"pr15d_v1/100000/{name}/k{k}"]["campaigns"][campaign] for name in ("medium", "common")]
    ratios = [float(rec[f"R_{candidate}_L"]) for rec in targets]
    intervals = [rec[f"CI_{candidate}_L"] for rec in targets]
    if not (min(ratios) <= .98 and max(ratios) <= 1.0 and any(ci["high"] < 1.0 for ci in intervals)):
        if min(ratios) > .98 and all(ci["low"] > .98 for ci in intervals):
            decisive.append("ATTRIBUTION")
        else:
            uncertain.append("ATTRIBUTION_CI")
    return {"decisive": decisive, "uncertain": uncertain, "filter_sensitive": sensitive}


def _gm_interval(slots: Mapping[tuple[str, str], Any], campaign: str, k: int, num: str, den: str) -> tuple[float, float]:
    rng = random.Random(_seed(f"{campaign}|k{k}|GM|{num}/{den}"))
    rows = [slots[(campaign, lane)] for lane in required_lanes(k)]
    constant = all(len({row["block"][arm][block] for block in row["retained"]}) == 1 for row in rows for arm in (num, den))
    values = []
    for _ in range(1 if constant else BOOTSTRAP_DRAWS):
        ratios = []
        for row in rows:
            ret, by = row["retained"], row["block"]
            draw = ret if constant else [ret[rng.randrange(len(ret))] for _ in ret]
            ratios.append(statistics.median([by[num][b] for b in draw]) / statistics.median([by[den][b] for b in draw]))
        values.append(math.exp(sum(math.log(value) for value in ratios) / 8))
    values.sort()
    return (values[0], values[0]) if constant else (values[CI_LOW_INDEX], values[CI_HIGH_INDEX])


def derive_nine_rows(lanes: Mapping[str, Any], slots: Mapping[tuple[str, str], Any], memory: Mapping[str, int]) -> list[dict[str, Any]]:
    rows = []
    for k in KS:
        statuses, reasons = {}, {}
        sensitive = False
        for candidate in ("P", "H"):
            evidence = [_candidate(lanes, campaign, k, candidate, memory[str(k)]) for campaign in CAMPAIGNS]
            decisive = [reason for item in evidence for reason in item["decisive"]]
            uncertain = [reason for item in evidence for reason in item["uncertain"]]
            statuses[candidate] = "INELIGIBLE" if decisive else "INCONCLUSIVE" if uncertain else "ELIGIBLE"
            reasons[candidate] = decisive + uncertain
            sensitive = sensitive or any(item["filter_sensitive"] for item in evidence)
        p, h = statuses["P"], statuses["H"]
        if sensitive and not (p == h == "INELIGIBLE"):
            selected, status = "INCONCLUSIVE", "K_INCONCLUSIVE_FILTER_SENSITIVE"
        elif p == h == "INELIGIBLE":
            selected, status = "LINEAR_BASE", "LINEAR_BASE"
        elif p == "ELIGIBLE" and h == "INELIGIBLE":
            selected, status = "P", "SELECTED_ELIGIBLE"
        elif h == "ELIGIBLE" and p == "INELIGIBLE":
            selected, status = "H", "SELECTED_ELIGIBLE"
        elif p != "ELIGIBLE" or h != "ELIGIBLE":
            selected, status = "INCONCLUSIVE", "K_INCONCLUSIVE"
        else:
            products = {}
            for candidate in ("P", "H"):
                campaign_products = []
                for campaign in CAMPAIGNS:
                    product = Fraction(1)
                    for lane_id in required_lanes(k):
                        product *= Fraction(str(float(lanes[lane_id]["campaigns"][campaign][f"R_{candidate}_A"])))
                    campaign_products.append(product)
                products[candidate] = max(campaign_products)
            if max(products.values()) / min(products.values()) < Fraction(103, 100) ** 8:
                selected, status = "P", "P_TIEBREAKER_NOT_PROVEN_FASTER"
            else:
                evidence = {candidate: [_gm_interval(slots, campaign, k, *pair) for campaign in CAMPAIGNS] for candidate, pair in (("P", ("H", "P")), ("H", ("P", "H")))}
                if all(ci[0] > 1 for ci in evidence["P"]):
                    selected, status = "P", "SELECTED_GM_CONFIRMED"
                elif all(ci[0] > 1 for ci in evidence["H"]):
                    selected, status = "H", "SELECTED_GM_CONFIRMED"
                else:
                    selected, status = "INCONCLUSIVE", "K_INCONCLUSIVE_P_VS_H"
        rows.append({"k": k, "selected_strategy": selected, "decision_status": status,
                     "P_status": p, "H_status": h, "P_reasons": reasons["P"], "H_reasons": reasons["H"],
                     "filter_sensitive": sensitive, "H_memory": memory[str(k)]})
    return rows


def derive_retained_policy(admitted: AdmittedRetainedKey, memory: Mapping[str, int], inputs_digest: str) -> dict[str, Any]:
    lanes, slots = derive_slot_statistics(admitted)
    return {"method_id": POLICY_METHOD, "inputs_digest": inputs_digest,
            "raw_series_root_digest": admitted.raw_series_root_digest,
            "statistics_digest": content_digest(lanes),
            "rows": derive_nine_rows(lanes, slots, memory)}

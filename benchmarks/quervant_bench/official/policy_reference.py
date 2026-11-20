"""Independent retained-key reference: raw samples and frozen F2 oracle semantics.

No imports from official.analysis or retained_policy are permitted. The decision
oracle below is migrated from the frozen F2 independent reference. The raw-slot
statistics are independently recomputed here, so changing primary arithmetic
cannot silently change Gate C's expected result.
"""
from __future__ import annotations
import hashlib
import math
import random
import statistics
from fractions import Fraction
from typing import Any, Mapping
from ..config.codec import content_digest
from ..config.errors import BM_IDENTITY_INVALID, BenchError
from .admission import AdmittedRetainedKey
from .policy_inputs import (ARMS, BOOTSTRAP_DRAWS, CAMPAIGNS, CI_LOW_INDEX,
    CI_HIGH_INDEX, CLASSES, H_LIMIT_BYTES, KS, NS, POLICY_METHOD, PROTOCOL_SHA256)

class PolicyInputError(ValueError): pass
def required_lanes(k):
 return tuple(f"pr15d_v1/{n}/{c}/k{k}" for n in NS for c in CLASSES)
def exact_decimal(v):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v): raise PolicyInputError("non-finite")
 return Fraction(str(v))
def _num(v):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0: raise PolicyInputError("invalid number")
 return float(v)
def evaluate_campaign_candidate(lanes,campaign,k,candidate,h_memory):
 if candidate not in ("P","H"): raise PolicyInputError("candidate")
 dec=[]; unc=[]; sens=False
 if candidate=="H" and h_memory>H_LIMIT_BYTES: dec.append("EXCLUDED_MEMORY")
 for lid in required_lanes(k):
  r=lanes.get(lid,{}).get("campaigns",{}).get(campaign)
  if not isinstance(r,dict): raise PolicyInputError(f"missing {lid}")
  n=int(lid.split('/')[1]); cls=lid.split('/')[2]
  if isinstance(r.get("retained_count"),bool) or not isinstance(r.get("retained_count"),int) or not 0<=r["retained_count"]<=12: raise PolicyInputError("retained")
  if not isinstance(r.get("filter_sensitive"),bool): raise PolicyInputError("sensitive")
  if r["retained_count"]<4: unc.append(f"INSUFFICIENT_BLOCKS:{lid}")
  if r["filter_sensitive"]: unc.append(f"FILTER_SENSITIVE:{lid}"); sens=True
  R=_num(r.get(f"R_{candidate}_A")); ci=r.get(f"CI_{candidate}_A")
  if not isinstance(ci,dict) or _num(ci.get("low"))>_num(ci.get("high")): raise PolicyInputError("ci")
  lo,hi=_num(ci["low"]),_num(ci["high"])
  if n==100000 and cls in ("medium","common"):
   if not (R<=0.97 and hi<1.0):
    if R>0.97 and lo>0.97: dec.append(f"NO_PRIMARY_GAIN:{lid}")
    else: unc.append(f"TARGET_CI:{lid}")
  else:
   if not (R<=1.10 and hi<=1.10):
    if R>1.10 and lo>1.10: dec.append(f"REGRESSION:{lid}")
    else: unc.append(f"GUARD_CI:{lid}")
 ts=[f"pr15d_v1/100000/{c}/k{k}" for c in ("medium","common")]
 sl=[]; ci=[]
 for lid in ts:
  r=lanes[lid]["campaigns"][campaign]; sl.append(_num(r.get(f"R_{candidate}_L"))); ci.append(r.get(f"CI_{candidate}_L"))
  if not isinstance(ci[-1],dict): raise PolicyInputError("attribution ci")
 if not (min(sl)<=0.98 and max(sl)<=1.00 and any(_num(x["high"])<1.0 for x in ci)):
  if min(sl)>0.98 and all(_num(x["low"])>0.98 for x in ci): dec.append("ATTRIBUTION")
  else: unc.append("ATTRIBUTION_CI")
 return {"status":"INELIGIBLE" if dec else "INCONCLUSIVE" if unc else "ELIGIBLE","decisive":dec,"uncertain":unc,
         "checked_lanes":8,"target_checks":2,"guard_checks":6,"attribution_checked":True,"filter_sensitive":sens}
def combine_campaign_candidate(c01,c02):
 dec=list(c01["decisive"])+list(c02["decisive"]); unc=list(c01["uncertain"])+list(c02["uncertain"]); sens=c01["filter_sensitive"] or c02["filter_sensitive"]
 return {"status":"INELIGIBLE" if dec else "INCONCLUSIVE" if unc else "ELIGIBLE","decisive":dec,"uncertain":unc,"filter_sensitive":sens}
def worst_campaign_gm_product(lanes,candidate,k):
 best=Fraction(0)
 for c in CAMPAIGNS:
  p=Fraction(1)
  for lid in required_lanes(k): p*=exact_decimal(_num(lanes[lid]["campaigns"][c][f"R_{candidate}_A"]))
  best=max(best,p)
 return best
def within_three_percent(wp,wh):
 lo=min(wp,wh); return lo>0 and max(wp,wh)/lo < Fraction(103,100)**8
def gm_bootstrap_ci_from_original_slots(authenticated_slots,campaign,k,numerator,denominator):
 txt=f"{PROTOCOL_SHA256}|{campaign}|k{k}|GM|{numerator}/{denominator}"; seed=int.from_bytes(hashlib.sha256(txt.encode()).digest()[:8],'big'); rng=random.Random(seed); vals=[]
 constant=all(len({authenticated_slots[(campaign,lid)]["block"][arm][b] for b in authenticated_slots[(campaign,lid)]["retained"]})==1 for lid in required_lanes(k) for arm in (numerator,denominator))
 if constant:
  ratio=math.exp(sum(math.log(authenticated_slots[(campaign,lid)]["block"][numerator][authenticated_slots[(campaign,lid)]["retained"][0]]/authenticated_slots[(campaign,lid)]["block"][denominator][authenticated_slots[(campaign,lid)]["retained"][0]]) for lid in required_lanes(k))/8)
  return ratio,ratio,seed
 for _ in range(BOOTSTRAP_DRAWS):
  rs=[]
  for lid in required_lanes(k):
   s=authenticated_slots[(campaign,lid)]; ret=s["retained"]; by=s["block"]
   draw=[ret[rng.randrange(len(ret))] for _ in ret]
   rs.append(statistics.median([by[numerator][b] for b in draw])/statistics.median([by[denominator][b] for b in draw]))
  vals.append(math.exp(sum(math.log(x) for x in rs)/8))
 vals.sort(); return vals[CI_LOW_INDEX],vals[CI_HIGH_INDEX],seed
def select_k(p_status,h_status,any_filter_sensitive,tie,gm_evidence):
 if any_filter_sensitive and not (p_status=="INELIGIBLE" and h_status=="INELIGIBLE"): return "INCONCLUSIVE","K_INCONCLUSIVE_FILTER_SENSITIVE"
 if p_status=="INELIGIBLE" and h_status=="INELIGIBLE": return "LINEAR_BASE","LINEAR_BASE"
 if p_status=="ELIGIBLE" and h_status=="INELIGIBLE": return "P","SELECTED_ELIGIBLE"
 if h_status=="ELIGIBLE" and p_status=="INELIGIBLE": return "H","SELECTED_ELIGIBLE"
 if p_status!="ELIGIBLE" or h_status!="ELIGIBLE": return "INCONCLUSIVE","K_INCONCLUSIVE"
 if tie: return "P","P_TIEBREAKER_NOT_PROVEN_FASTER"
 if gm_evidence and all(gm_evidence["P"][c]["low"]>1 for c in CAMPAIGNS): return "P","SELECTED_GM_CONFIRMED"
 if gm_evidence and all(gm_evidence["H"][c]["low"]>1 for c in CAMPAIGNS): return "H","SELECTED_GM_CONFIRMED"
 return "INCONCLUSIVE","K_INCONCLUSIVE_P_VS_H"
def derive_nine(analysis,memory_by_k,authenticated_slots=None):
 if analysis.get("protocol_sha256")!=PROTOCOL_SHA256: raise PolicyInputError("protocol")
 lanes_in=analysis["lanes"]; rows={r["id"]:r for r in (lanes_in.values() if isinstance(lanes_in,dict) else lanes_in)}; out=[]
 for k in KS:
  st={}; sens=False; reasons={}
  for S in ("P","H"):
   cs=[]; ds=[]; us=[]
   for c in CAMPAIGNS:
    e=evaluate_campaign_candidate(rows,c,k,S,memory_by_k.get(str(k),0)); cs.append(e); ds+=e["decisive"]; us+=e["uncertain"]; sens=sens or e["filter_sensitive"]
   s="INELIGIBLE" if any(x["decisive"] for x in cs) else "INCONCLUSIVE" if any(x["uncertain"] for x in cs) else "ELIGIBLE"
   st[S]=s; reasons[S]=ds+us
  tie=None; gme=None
  if st["P"]=="ELIGIBLE" and st["H"]=="ELIGIBLE":
   tie=within_three_percent(worst_campaign_gm_product(rows,"P",k),worst_campaign_gm_product(rows,"H",k))
   if not tie and authenticated_slots:
    gme={"P":{},"H":{}}
    for c in CAMPAIGNS:
     lo,hi,_=gm_bootstrap_ci_from_original_slots(authenticated_slots,c,k,"H","P"); gme["P"][c]={"low":lo,"high":hi}
     lo,hi,_=gm_bootstrap_ci_from_original_slots(authenticated_slots,c,k,"P","H"); gme["H"][c]={"low":lo,"high":hi}
  sel,code=select_k(st["P"],st["H"],sens,tie,gme)
  out.append({"k":k,"selected_strategy":sel,"decision_status":code,"P_status":st["P"],"H_status":st["H"],"P_reasons":reasons["P"],"H_reasons":reasons["H"],"filter_sensitive":sens,"H_memory":memory_by_k.get(str(k))})
 return out


def reference_slot_statistics(admitted: AdmittedRetainedKey) -> tuple[dict[str, Any], dict[tuple[str, str], Any]]:
    """An independent path from the 20-sample slots to the T7 ratio inputs."""

    rows: dict[str, Any] = {}
    raw_blocks: dict[tuple[str, str], Any] = {}
    expected_ids = {lid for k in KS for lid in required_lanes(k)}
    for campaign in CAMPAIGNS:
        slots = admitted.slots[campaign]
        if len(slots) != 96 or {(slot["block"], slot["position"]) for slot in slots} != {(b, p) for b in range(1, 13) for p in range(1, 9)}:
            raise PolicyInputError("reference slot schedule")
        tables = []
        for slot in slots:
            table = {row["id"]: row for row in slot["lanes"]}
            if set(table) != expected_ids or len(slot["lanes"]) != 72:
                raise PolicyInputError("reference lane coverage")
            tables.append((slot, table))
        for k in KS:
            for lid in required_lanes(k):
                _, n_string, class_name, _ = lid.split("/")
                n = int(n_string)
                medians: dict[tuple[str, int], list[int]] = {}
                for slot, table in tables:
                    record = table[lid]
                    values = record["samples_ns"]
                    if len(values) != 20 or any(type(v) is not int or v < 1 for v in values):
                        raise PolicyInputError("reference raw samples")
                    median = sorted(values)[9]
                    if type(record["summary_ns"]["median"]) is not int or record["summary_ns"]["median"] != median:
                        raise PolicyInputError("reference summary mismatch")
                    medians.setdefault((slot["arm"], slot["block"]), []).append(median)
                if set(medians) != {(a, b) for a in ARMS for b in range(1, 13)} or any(len(pair) != 2 for pair in medians.values()):
                    raise PolicyInputError("reference arm/block coverage")
                limit = 1.25 if n == 100_000 and class_name in ("medium", "common") else 1.50
                excluded = {b for (a, b), pair in medians.items() if max(pair) / min(pair) > limit}
                retained = [b for b in range(1, 13) if b not in excluded]
                if len(retained) < 4:
                    raise PolicyInputError("reference insufficient symmetric blocks")
                blocks = {a: {b: (medians[(a, b)][0] + medians[(a, b)][1]) // 2 for b in range(1, 13)} for a in ARMS}
                filtered = {a: statistics.median([blocks[a][b] for b in retained]) for a in ARMS}
                unfiltered = {a: statistics.median([blocks[a][b] for b in range(1, 13)]) for a in ARMS}
                delta_before = unfiltered["P"] - unfiltered["H"]
                delta_after = filtered["P"] - filtered["H"]
                rec = {"retained": retained, "retained_count": len(retained), "latency": filtered,
                       "raw_latency": unfiltered,
                       "filter_sensitive": ((delta_before > 0) != (delta_after > 0) or (delta_before == 0) != (delta_after == 0))}
                for num, den in (("L", "A"), ("P", "A"), ("H", "A"), ("P", "L"), ("H", "L"), ("H", "P")):
                    rec[f"R_{num}_{den}"] = filtered[num] / filtered[den]
                    seed_text = f"{PROTOCOL_SHA256}|{campaign}|{lid}|{num}/{den}"
                    seed = int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], "big")
                    if all(len({blocks[arm][b] for b in retained}) == 1 for arm in (num, den)):
                        low = high = blocks[num][retained[0]] / blocks[den][retained[0]]
                    else:
                        rng = random.Random(seed)
                        replicates = []
                        for _ in range(BOOTSTRAP_DRAWS):
                            indices = [retained[rng.randrange(len(retained))] for _ in retained]
                            replicates.append(statistics.median([blocks[num][index] for index in indices]) / statistics.median([blocks[den][index] for index in indices]))
                        replicates.sort()
                        low, high = replicates[CI_LOW_INDEX], replicates[CI_HIGH_INDEX]
                    rec[f"CI_{num}_{den}"] = {"low": low, "high": high, "seed": seed}
                rows.setdefault(lid, {"id": lid, "n": n, "class": class_name, "k": k, "campaigns": {}})["campaigns"][campaign] = rec
                raw_blocks[(campaign, lid)] = {"retained": retained, "block": blocks}
    return rows, raw_blocks


def reference_retained_policy(admitted: AdmittedRetainedKey, memory: Mapping[str, int], inputs_digest: str) -> dict[str, Any]:
    try:
        lanes, slots = reference_slot_statistics(admitted)
        rows = derive_nine({"protocol_sha256": PROTOCOL_SHA256, "lanes": lanes}, memory, slots)
    except (PolicyInputError, KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise BenchError(BM_IDENTITY_INVALID, "retained policy reference rejected its raw inputs", field_path="retained_key_policy") from exc
    return {"method_id": POLICY_METHOD, "inputs_digest": inputs_digest,
            "raw_series_root_digest": admitted.raw_series_root_digest,
            "statistics_digest": content_digest(lanes), "rows": rows}

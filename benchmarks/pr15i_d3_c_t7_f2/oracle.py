#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math, os, random, statistics, sys
from fractions import Fraction
try:
 from . import constants as C
except ImportError:
 import constants as C
class PolicyInputError(ValueError): pass
def required_lanes(k):
 return tuple(f"pr15d_v1/{n}/{c}/k{k}" for n in C.NS for c in C.CLASSES)
def exact_decimal(v):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v): raise PolicyInputError("non-finite")
 return Fraction(str(v))
def _num(v):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0: raise PolicyInputError("invalid number")
 return float(v)
def evaluate_campaign_candidate(lanes,campaign,k,candidate,h_memory):
 if candidate not in ("P","H"): raise PolicyInputError("candidate")
 dec=[]; unc=[]; sens=False
 if candidate=="H" and h_memory>C.H_LIMIT_BYTES: dec.append("EXCLUDED_MEMORY")
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
 for c in C.CAMP:
  p=Fraction(1)
  for lid in required_lanes(k): p*=exact_decimal(_num(lanes[lid]["campaigns"][c][f"R_{candidate}_A"]))
  best=max(best,p)
 return best
def within_three_percent(wp,wh):
 lo=min(wp,wh); return lo>0 and max(wp,wh)/lo < Fraction(103,100)**8
def gm_bootstrap_ci_from_original_slots(authenticated_slots,campaign,k,numerator,denominator):
 txt=f"{C.R3_SHA}|{campaign}|k{k}|GM|{numerator}/{denominator}"; seed=int.from_bytes(hashlib.sha256(txt.encode()).digest()[:8],'big'); rng=random.Random(seed); vals=[]
 for _ in range(C.BOOT_DRAWS):
  rs=[]
  for lid in required_lanes(k):
   s=authenticated_slots[(campaign,lid)]; ret=s["retained"]; by=s["block"]
   draw=[ret[rng.randrange(len(ret))] for _ in ret]
   rs.append(statistics.median([by[numerator][b] for b in draw])/statistics.median([by[denominator][b] for b in draw]))
  vals.append(math.exp(sum(math.log(x) for x in rs)/8))
 vals.sort(); return vals[C.CI_LOW_INDEX],vals[C.CI_HIGH_INDEX],seed
def select_k(p_status,h_status,any_filter_sensitive,tie,gm_evidence):
 if any_filter_sensitive and not (p_status=="INELIGIBLE" and h_status=="INELIGIBLE"): return "INCONCLUSIVE","K_INCONCLUSIVE_FILTER_SENSITIVE"
 if p_status=="INELIGIBLE" and h_status=="INELIGIBLE": return "LINEAR_BASE","LINEAR_BASE"
 if p_status=="ELIGIBLE" and h_status=="INELIGIBLE": return "P","SELECTED_ELIGIBLE"
 if h_status=="ELIGIBLE" and p_status=="INELIGIBLE": return "H","SELECTED_ELIGIBLE"
 if p_status!="ELIGIBLE" or h_status!="ELIGIBLE": return "INCONCLUSIVE","K_INCONCLUSIVE"
 if tie: return "P","P_TIEBREAKER_NOT_PROVEN_FASTER"
 if gm_evidence and all(gm_evidence["P"][c]["low"]>1 for c in C.CAMP): return "P","SELECTED_GM_CONFIRMED"
 if gm_evidence and all(gm_evidence["H"][c]["low"]>1 for c in C.CAMP): return "H","SELECTED_GM_CONFIRMED"
 return "INCONCLUSIVE","K_INCONCLUSIVE_P_VS_H"
def derive_nine(analysis,memory_by_k,authenticated_slots=None):
 if analysis.get("protocol_sha256")!=C.R3_SHA: raise PolicyInputError("protocol")
 lanes_in=analysis["lanes"]; rows={r["id"]:r for r in (lanes_in.values() if isinstance(lanes_in,dict) else lanes_in)}; out=[]
 for k in C.KS:
  st={}; sens=False; reasons={}
  for S in ("P","H"):
   cs=[]; ds=[]; us=[]
   for c in C.CAMP:
    e=evaluate_campaign_candidate(rows,c,k,S,memory_by_k.get(str(k),0)); cs.append(e); ds+=e["decisive"]; us+=e["uncertain"]; sens=sens or e["filter_sensitive"]
   s="INELIGIBLE" if any(x["decisive"] for x in cs) else "INCONCLUSIVE" if any(x["uncertain"] for x in cs) else "ELIGIBLE"
   st[S]=s; reasons[S]=ds+us
  tie=None; gme=None
  if st["P"]=="ELIGIBLE" and st["H"]=="ELIGIBLE":
   tie=within_three_percent(worst_campaign_gm_product(rows,"P",k),worst_campaign_gm_product(rows,"H",k))
   if not tie and authenticated_slots:
    gme={"P":{},"H":{}}
    for c in C.CAMP:
     lo,hi,_=gm_bootstrap_ci_from_original_slots(authenticated_slots,c,k,"H","P"); gme["P"][c]={"low":lo,"high":hi}
     lo,hi,_=gm_bootstrap_ci_from_original_slots(authenticated_slots,c,k,"P","H"); gme["H"][c]={"low":lo,"high":hi}
  sel,code=select_k(st["P"],st["H"],sens,tie,gme)
  out.append({"k":k,"selected_strategy":sel,"decision_status":code,"P_status":st["P"],"H_status":st["H"],"P_reasons":reasons["P"],"H_reasons":reasons["H"],"filter_sensitive":sens,"H_memory":memory_by_k.get(str(k))})
 return out
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--analysis",required=True); ap.add_argument("--policy",required=True); ap.add_argument("--micro-json",required=True); ap.add_argument("--out",required=True); a=ap.parse_args(argv)
 data=json.load(open(a.analysis)); m=json.load(open(a.micro_json)); mem={}
 for r in m["records"]:
  if r["variant"]=="exact_set": mem[str(r["k"])]=max(mem.get(str(r["k"]),0),r["set_capacity"]*40+r["key_bytes"])
 rows=derive_nine(data,mem); old={r["k"]:r for r in json.load(open(a.policy))["rows"]}; errs=[]
 for r in rows:
  o=old[r["k"]]
  if (r["selected_strategy"],r["decision_status"],r["P_status"],r["H_status"])!=(o["selected_strategy"],o["decision_status"],o["P_status"],o["H_status"]): errs.append(r["k"])
 out={"schema":"pr15i-d3c-t7f2-policy-v1","protocol_sha256":C.R3_SHA,"status":"T7_POLICY_DERIVED_PENDING_INDEPENDENT_VERIFICATION","rows":rows}
 os.makedirs(os.path.dirname(os.path.abspath(a.out)),exist_ok=True); json.dump(out,open(a.out,"x"),sort_keys=True,indent=2)
 print(json.dumps({"mismatches":errs,"rows":len(rows)})); return 0 if not errs else 3
if __name__=="__main__": raise SystemExit(main())

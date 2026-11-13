#!/usr/bin/env python3
import json,sys
KS=(1,10,32,64,100,128,256,512,1024); NS=(10000,100000); CLASSES=("absent","rare","medium","common"); CAMPS=("d3c-v3r3-strategies-01","d3c-v3r3-strategies-02")
def lanes(k): return [f"pr15d_v1/{n}/{c}/k{k}" for n in NS for c in CLASSES]
def status_for(S,rows,camp,k,mem):
 dec=[]; unc=[]; sens=False
 if S=="H" and mem[str(k)]>2097152: dec.append("EXCLUDED_MEMORY")
 for lid in lanes(k):
  r=rows[lid]["campaigns"][camp]; n=int(lid.split('/')[1]); cls=lid.split('/')[2]
  if r.get("retained_count",0)<4: unc.append(f"INSUFFICIENT:{lid}")
  if r.get("filter_sensitive"): unc.append(f"SENSITIVE:{lid}"); sens=True
  R=r.get(f"R_{S}_A"); ci=r.get(f"CI_{S}_A")
  if R is None or ci is None: unc.append(f"MISSING:{lid}"); continue
  if n==100000 and cls in ("medium","common"):
   if not (R<=0.97 and ci["high"]<1.0):
    if R>0.97 and ci["low"]>0.97: dec.append(f"NO_GAIN:{lid}")
    else: unc.append(f"TARGET_CI:{lid}")
  else:
   if not (R<=1.10 and ci["high"]<=1.10):
    if R>1.10 and ci["low"]>1.10: dec.append(f"REGRESSION:{lid}")
    else: unc.append(f"GUARD_CI:{lid}")
 ts=[f"pr15d_v1/100000/{c}/k{k}" for c in ("medium","common")]
 sl=[rows[l]["campaigns"][camp].get(f"R_{S}_L") for l in ts]; ci=[rows[l]["campaigns"][camp].get(f"CI_{S}_L") for l in ts]
 if any(x is None for x in sl+ci): unc.append("MISSING_ATTRIBUTION")
 else:
  if not (min(sl)<=0.98 and max(sl)<=1.00 and any(c["high"]<1.0 for c in ci)):
   if min(sl)>0.98 and all(c["low"]>0.98 for c in ci): dec.append("ATTRIBUTION")
   else: unc.append("ATTRIBUTION_CI")
 return ("INELIGIBLE" if dec else "INCONCLUSIVE" if unc else "ELIGIBLE"),dec,sens
def gm(rows,camp,S,k):
 import math
 return math.exp(sum(math.log(rows[l]["campaigns"][camp][f"R_{S}_A"]) for l in lanes(k))/8)
def main(argv=None):
 import argparse
 ap=argparse.ArgumentParser(); ap.add_argument("--analysis",required=True); ap.add_argument("--policy",required=True); ap.add_argument("--micro-json",required=True); ap.add_argument("--out",required=True); a=ap.parse_args(argv)
 data=json.load(open(a.analysis)); rows=data["lanes"]; m=json.load(open(a.micro_json)); mem={}
 for r in m["records"]:
  if r["variant"]=="exact_set": mem[str(r["k"])]=max(mem.get(str(r["k"]),0),r["set_capacity"]*40+r["key_bytes"])
 pol={r["k"]:r for r in json.load(open(a.policy))["rows"]}; errors=[]
 for k in KS:
  st={}; sens=False; reasons={}
  for S in ("P","H"):
   ss=[]
   for c in CAMPS:
    s,r,se=status_for(S,rows,c,k,mem); ss.append(s); sens=sens or se; reasons.setdefault(S,[]).extend(r)
   st[S]="ELIGIBLE" if all(x=="ELIGIBLE" for x in ss) else "INELIGIBLE" if any(x=="INELIGIBLE" for x in ss) else "INCONCLUSIVE"
  if sens and not (st["P"]=="INELIGIBLE" and st["H"]=="INELIGIBLE"): sel,code="INCONCLUSIVE","K_INCONCLUSIVE_FILTER_SENSITIVE"
  elif st["P"]=="INELIGIBLE" and st["H"]=="INELIGIBLE": sel,code="LINEAR_BASE","LINEAR_BASE"
  elif st["P"]=="ELIGIBLE" and st["H"]=="INELIGIBLE": sel,code="P","SELECTED_ELIGIBLE"
  elif st["H"]=="ELIGIBLE" and st["P"]=="INELIGIBLE": sel,code="H","SELECTED_ELIGIBLE"
  elif st["P"]=="ELIGIBLE" and st["H"]=="ELIGIBLE":
   wp=max(gm(rows,c,"P",k) for c in CAMPS); wh=max(gm(rows,c,"H",k) for c in CAMPS)
   sel,code=("P","P_TIEBREAKER_NOT_PROVEN_FASTER") if abs(wp-wh)/min(wp,wh)<0.03 else ("INCONCLUSIVE","K_INCONCLUSIVE_P_VS_H")
  else: sel,code="INCONCLUSIVE","K_INCONCLUSIVE"
  old=pol[k]; print(k,sel,code,st["P"],st["H"])
  if (sel,code,st["P"],st["H"])!=(old["selected_strategy"],old["decision_status"],old["P_status"],old["H_status"]): errors.append(k)
 print("MISMATCH",errors)
 import hashlib,os
 os.makedirs(os.path.dirname(os.path.abspath(a.out)),exist_ok=True)
 rep={"schema":"pr15i-d3c-t7f2-verification-v1","verification":"PASS" if not errors else "FAIL","mismatches":errors,
      "rows":len(KS),"analysis_sha256":hashlib.sha256(open(a.analysis,'rb').read()).hexdigest(),
      "policy_sha256":hashlib.sha256(open(a.policy,'rb').read()).hexdigest(),"protocol_sha256":data["protocol_sha256"]}
 json.dump(rep,open(a.out,"x"),sort_keys=True,indent=2)
 return 0 if not errors else 3
if __name__=="__main__": raise SystemExit(main())

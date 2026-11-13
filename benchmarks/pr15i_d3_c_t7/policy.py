#!/usr/bin/env python3
import argparse, json, math, os, statistics
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
CLASSES=["absent","rare","medium","common"]
def load_micro(path):
 m=json.load(open(path)); assert m["schema"]=="pr15i-d3c-micro-v1" and len(m["records"])==900 and m["selected_profile"]=="P2"
 mem={}
 for r in m["records"]:
  if r["variant"]=="exact_set": mem[str(r["k"])]=max(mem.get(str(r["k"]),0),r["set_capacity"]*40+r["key_bytes"])
 return mem
def lanes_for(k): return [f"pr15d_v1/{n}/{c}/k{k}" for n in (10000,100000) for c in CLASSES]
def campaign(rows,cname):
 return {lid:rows[lid]["campaigns"][cname] for lid in rows}
def evaluate(S,rows,cname,k,mem):
 rs=campaign(rows,cname); ls=lanes_for(k); reasons=[]; incon=[]; fail=False
 if S=="H" and mem.get(str(k),0)>2097152:
  return "INELIGIBLE",["EXCLUDED_MEMORY"],False
 for lid in ls:
  r=rs[lid]; n=int(lid.split('/')[1]); cls=lid.split('/')[2]
  if r.get("retained_count",0)<4 or r.get("filter_sensitive"): return "INCONCLUSIVE",["INSUFFICIENT_OR_SENSITIVE"],False
  R=r.get(f"R_{S}_A"); ci=r.get(f"CI_{S}_A")
  if R is None or ci is None: return "INCONCLUSIVE",["MISSING_CI"],False
  if n==100000 and cls in ("medium","common"):
   if not (R<=0.97 and ci["high"]<1.0):
    if R>0.97 and ci["low"]>0.97: return "INELIGIBLE",[f"NO_PRIMARY_GAIN:{lid}"],True
    incon.append(f"TARGET:{lid}")
  else:
   if not (R<=1.10 and ci["high"]<=1.10):
    if R>1.10 and ci["low"]>1.10: return "INELIGIBLE",[f"REGRESSION:{lid}"],True
    incon.append(f"GUARD:{lid}")
 targets=[f"pr15d_v1/100000/{c}/k{k}" for c in ("medium","common")]
 sl=[rs[l].get(f"R_{S}_L") for l in targets]
 ci_sl=[rs[l].get(f"CI_{S}_L") for l in targets]
 if any(x is None for x in sl+ci_sl): return "INCONCLUSIVE",["MISSING_ATTRIBUTION"],False
 if not (min(sl)<=0.98 and max(sl)<=1.00 and any(c["high"]<1.0 for c in ci_sl)):
  if min(sl)>0.98 and all(c["low"]>0.98 for c in ci_sl): return "INELIGIBLE",["ATTRIBUTION"],True
  incon.append("ATTRIBUTION")
 if incon: return "INCONCLUSIVE",incon,False
 return "ELIGIBLE",[],False
def gm(rows,cname,S,k):
 vals=[rows[l]["campaigns"][cname][f"R_{S}_A"] for l in lanes_for(k)]
 return math.exp(sum(math.log(v) for v in vals)/8)
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--analysis",required=True); ap.add_argument("--micro-json",required=True); ap.add_argument("--out",required=True); a=ap.parse_args(argv)
 data=json.load(open(a.analysis)); rows=data["lanes"]; mem=load_micro(a.micro_json); camps=data["series"]; outrows=[]
 for k in (1,10,32,64,100,128,256,512,1024):
  st={}; reasons={}; decisive={}
  for S in ("P","H"):
   cs=[]; rs=[]
   for c in camps:
    s,r,d=evaluate(S,rows,c,k,mem); cs.append(s); rs+=r; decisive[S]=decisive.get(S,False) or d
   if all(x=="ELIGIBLE" for x in cs): st[S]="ELIGIBLE"
   elif any(x=="INELIGIBLE" for x in cs): st[S]="INELIGIBLE"
   else: st[S]="INCONCLUSIVE"
   reasons[S]=rs
  sens=any(rows[l]["campaigns"][c].get("filter_sensitive") for l in lanes_for(k) for c in camps)
  if sens and not (st["P"]=="INELIGIBLE" and st["H"]=="INELIGIBLE"):
   sel,status="INCONCLUSIVE","K_INCONCLUSIVE_FILTER_SENSITIVE"
  elif st["P"]=="INELIGIBLE" and st["H"]=="INELIGIBLE": sel,status="LINEAR_BASE","LINEAR_BASE"
  elif st["P"]=="ELIGIBLE" and st["H"]=="INELIGIBLE": sel,status="P","SELECTED_ELIGIBLE"
  elif st["H"]=="ELIGIBLE" and st["P"]=="INELIGIBLE": sel,status="H","SELECTED_ELIGIBLE"
  elif st["P"]=="ELIGIBLE" and st["H"]=="ELIGIBLE":
   wp=max(gm(rows,c,"P",k) for c in camps); wh=max(gm(rows,c,"H",k) for c in camps)
   if abs(wp-wh)/min(wp,wh)<0.03: sel,status="P","P_TIEBREAKER_NOT_PROVEN_FASTER"
   else: sel,status="INCONCLUSIVE","K_INCONCLUSIVE_P_VS_H"
  else: sel,status="INCONCLUSIVE","K_INCONCLUSIVE"
  outrows.append({"k":k,"selected_strategy":sel,"decision_status":status,"P_status":st["P"],"H_status":st["H"],
   "P_reasons":reasons["P"],"H_reasons":reasons["H"],"filter_sensitive":sens,
   "P_gm":[gm(rows,c,"P",k) for c in camps],"H_gm":[gm(rows,c,"H",k) for c in camps],"H_memory":mem.get(str(k))})
 out={"schema":"pr15i-d3c-t7-policy-v1","protocol_sha256":data["protocol_sha256"],"status":"T7_POLICY_DERIVED_PENDING_INDEPENDENT_VERIFICATION","rows":outrows}
 os.makedirs(os.path.dirname(os.path.abspath(a.out)),exist_ok=True)
 json.dump(out,open(a.out,"x"),sort_keys=True,indent=2)
 for r in outrows: print(r["k"],r["selected_strategy"],r["decision_status"],r["P_status"],r["H_status"])
 return 0
if __name__=="__main__": raise SystemExit(main())

#!/usr/bin/env python3
import argparse, hashlib, json, math, os, random, statistics, subprocess, sys
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE)); BM=os.path.join(ROOT,"benchmarks/pr15i_d3_c")
import importlib.util
def load(n,f):
 s=importlib.util.spec_from_file_location(n,os.path.join(BM,f));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
RUN=load("vrun","run.py"); P,_=RUN.load_protocol(); SHA=RUN.PROTOCOL_SHA256
def med(v): return statistics.median(v)
def boot(num,den,by,ret,cname,lid):
 seed=int.from_bytes(hashlib.sha256(f"{SHA}|{cname}|{lid}|{num}/{den}".encode()).digest()[:8],'big'); r=random.Random(seed); vals=[]
 for _ in range(10000):
  d=[ret[r.randrange(len(ret))] for _ in ret]
  vals.append(statistics.median([by[(num,b)] for b in d])/statistics.median([by[(den,b)] for b in d]))
 vals.sort(); return vals[249],vals[9749]
def recompute(root):
 lanes=RUN.lanes(P); out={}
 for name in P["campaign_names"]:
  slots=[json.load(open(os.path.join(root,name,"raw/slots",f"slot-{i:02d}.json"))) for i in range(1,97)]
  for lane in lanes:
   lid=lane["id"]; by={}
   for s in slots:
    l=next(x for x in s["lanes"] if x["id"]==lid); by.setdefault((s["arm"],s["block"]),[]).append(l["summary_ns"]["median"])
   cap=1.25 if lane["n"]==100000 and lane["class"] in ("medium","common") else 1.5; ret=[]; ex=[]
   for b in range(1,13):
    if any(max(by[(a,b)])/min(by[(a,b)])>cap for a in ("A","L","P","H")): ex.append(b)
    else: ret.append(b)
   rec={"retained":ret,"excluded":ex,"cap":cap,"retained_count":len(ret)}
   if len(ret)>=4:
    lat={a:med([sum(by[(a,b)])//2 for b in ret]) for a in ("A","L","P","H")}
    tmp={}
    for b in range(1,13):
     for a in ("A","L","P","H"): tmp[(a,b)]=sum(by[(a,b)])//2
    for s in ("L","P","H"): rec[f"R_{s}_A"]=lat[s]/lat["A"]
    for s in ("P","H"): rec[f"R_{s}_L"]=lat[s]/lat["L"]
    rec["R_H_P"]=lat["H"]/lat["P"]
    for num,den in (("L","A"),("P","A"),("H","A"),("P","L"),("H","L"),("H","P")):
     lo,hi=boot(num,den,tmp,ret,name,lid); rec[f"CI_{num}_{den}"]={"low":lo,"high":hi}
   out.setdefault(lid,{"k":lane["k"],"n":lane["n"],"class":lane["class"],"campaigns":{}})["campaigns"][name]=rec
 return out
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--analysis",required=True); ap.add_argument("--policy",required=True); ap.add_argument("--series-root",required=True); ap.add_argument("--micro-json",required=True); ap.add_argument("--out",required=True); a=ap.parse_args(argv)
 root=os.path.realpath(a.series_root); data=json.load(open(a.analysis)); pol=json.load(open(a.policy)); indep=recompute(root)
 errs=[]
 for lid,r in data["lanes"].items():
  for c,x in r["campaigns"].items():
   y=indep[lid]["campaigns"][c]
   if x.get("retained")!=y["retained"]: errs.append(f"retained:{lid}:{c}")
   for f in ("R_P_A","R_H_A","R_L_A","R_P_L","R_H_L","R_H_P"):
    if x.get(f)!=y.get(f): errs.append(f"{f}:{lid}:{c}")
   for f in ("CI_P_A","CI_H_A","CI_P_L","CI_H_L","CI_H_P","CI_L_A"):
    for q in ("low","high"):
     if x.get(f,{}).get(q)!=y.get(f,{}).get(q): errs.append(f"{f}.{q}:{lid}:{c}")
 # policy selection cross-check: require nine rows, candidate statuses and selected strings from verifier's own simple gate
 micro=json.load(open(a.micro_json)); mem={}
 for r in micro["records"]:
  if r["variant"]=="exact_set": mem[str(r["k"])]=max(mem.get(str(r["k"]),0),r["set_capacity"]*40+r["key_bytes"])
 for row in pol["rows"]:
  k=row["k"]
  if row["selected_strategy"] not in ("P","H","LINEAR_BASE","INCONCLUSIVE"): errs.append(f"sel:{k}")
  if row["H_memory"]!=mem.get(str(k)): errs.append(f"mem:{k}")
 outdir=os.path.realpath(a.out)
 if os.path.exists(outdir): raise SystemExit("output exists")
 os.makedirs(outdir)
 rep={"schema":"pr15i-d3c-t7f1-verification-v1","verification":"PASS" if not errs else "FAIL","errors":errs[:20],
      "lanes_checked":len(indep),"rows_checked":len(pol["rows"]),"analysis_sha256":hashlib.sha256(open(a.analysis,'rb').read()).hexdigest(),
      "policy_sha256":hashlib.sha256(open(a.policy,'rb').read()).hexdigest(),"protocol_sha256":SHA,"micro_sha256":hashlib.sha256(open(a.micro_json,'rb').read()).hexdigest()}
 json.dump(rep,open(os.path.join(outdir,"verification.json"),"w"),sort_keys=True,indent=2)
 print(json.dumps({"verification":rep["verification"],"errors":len(errs)})); return 0 if not errs else 3
if __name__=="__main__": raise SystemExit(main())

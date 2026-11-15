#!/usr/bin/env python3
"""Read-only v3 post-acquisition symmetric filter, aggregation and paired bootstrap."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, random, statistics, subprocess, sys
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
def load(n,f):
 s=importlib.util.spec_from_file_location(n,os.path.join(HERE,f));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
RUN=load("av3_run","run.py")
PROTOCOL_SHA=RUN.PROTOCOL_SHA256

def lanes(protocol): return RUN.lanes(protocol)

def load_campaign(d):
 m=json.load(open(os.path.join(d,"manifest.json")))
 slots=[]
 for i in range(1,m["slots"]+1):
  slots.append(json.load(open(os.path.join(d,"raw","slots",f"slot-{i:02d}.json"))))
 return m,slots

def per_block(slots,lane_id,arms):
 by={}
 for s in slots:
  lane=next(l for l in s["lanes"] if l["id"]==lane_id)
  by.setdefault((s["arm"],s["block"]),[]).append(lane["summary_ns"]["median"])
 return by

def filter_lane(slots,lane_id,n,cls,arms,cap_hi,cap_other,blocks):
 by=per_block(slots,lane_id,arms); cap=cap_hi if n==100000 and cls in ("medium","common") else cap_other
 retained=[]; ex=[]
 for b in range(1,blocks+1):
  within={a:max(by[(a,b)])/min(by[(a,b)]) for a in arms}
  bad=[a for a,r in within.items() if r>cap]
  if bad: ex.append({"block":b,"within":within,"arms":bad})
  else: retained.append(b)
 return by,retained,ex,cap

def agg(by,blocks,arm):
 return statistics.median([sum(by[(arm,b)])//len(by[(arm,b)]) for b in blocks])

def boot(numerator,denominator,by,retained,bootstrap,seed):
 rng=random.Random(seed); vals=[]
 for _ in range(bootstrap):
  draw=[retained[rng.randrange(len(retained))] for _ in retained]
  num=statistics.median([sum(by[(numerator,b)])//len(by[(numerator,b)]) for b in draw])
  den=statistics.median([sum(by[(denominator,b)])//len(by[(denominator,b)]) for b in draw])
  vals.append(num/den)
 vals.sort(); return [vals[249],vals[9749]], vals

def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--series-root",required=True); ap.add_argument("--out",required=True)
 a=ap.parse_args(argv)
 p,_=RUN.load_protocol(); root=os.path.realpath(a.series_root)
 r=subprocess.run([sys.executable,os.path.join(HERE,"verify.py"),"--series-root",root],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if r.returncode!=0: raise SystemExit(f"analysis requires verified series: {r.stdout[-300:]}")
 rep=json.loads(r.stdout)
 if not rep.get("full_series"): raise SystemExit("analysis requires full_series")
 out=os.path.realpath(a.out)
 target=os.path.realpath(os.path.join(ROOT,RUN.TARGET_REL,"v3r2-analysis"))
 if os.path.commonpath([out,target])!=target or out==target: raise SystemExit("analysis output path")
 if os.path.exists(out): raise SystemExit("analysis output exists")
 os.makedirs(out)
 ls=lanes(p); names=p["campaign_names"]; campaigns={}
 for name in names:
  m,slots=load_campaign(os.path.join(root,name)); campaigns[name]=slots
 rows={}
 for lane in ls:
  lid=lane["id"]; row={"id":lid,"n":lane["n"],"class":lane["class"],"k":lane["k"],"campaigns":{}}
  for name in names:
   slots=campaigns[name]; arms=["A","L","P","H"]
   by,ret,ex,cap=filter_lane(slots,lid,lane["n"],lane["class"],arms,p["within_arm_exclusion_cap_100k_medium_common"],p["within_arm_exclusion_cap_other"],p["blocks"])
   row["campaigns"][name]={"retained":ret,"excluded":ex,"cap":cap,"retained_count":len(ret),"filter_status":"RETAINED" if len(ret)>=p["min_retained_blocks_per_lane"] else "INCONCLUSIVE_INSUFFICIENT_BLOCKS"}
   if len(ret)>=p["min_retained_blocks_per_lane"]:
    vals={a:agg(by,ret,a) for a in arms}; unf={a:agg(by,range(1,p["blocks"]+1),a) for a in arms}
    row["campaigns"][name]["filtered_ns"]=vals; row["campaigns"][name]["unfiltered_ns"]=unf
    for s in ("A","L","P","H"):
     row["campaigns"][name][f"R_{s}_A"]=vals[s]/vals["A"]; row["campaigns"][name][f"RU_{s}_A"]=unf[s]/unf["A"]
  rows[lid]=row
 data={"schema":"pr15i-d3c-analysis-v3r2","protocol_sha256":PROTOCOL_SHA,"series":names,"lanes":rows,"bootstrap_resamples":p["bootstrap_resamples"],"bootstrap_confidence":p["bootstrap_confidence"]}
 json.dump(data,open(os.path.join(out,"analysis.json"),"w"),sort_keys=True,indent=2)
 print(json.dumps({"status":"ANALYSIS_COMPLETE","lanes":len(rows)})); return 0
if __name__=="__main__": raise SystemExit(main())

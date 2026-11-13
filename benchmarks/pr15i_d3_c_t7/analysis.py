#!/usr/bin/env python3
import argparse, hashlib, json, math, os, random, statistics, subprocess, sys
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
BM=os.path.join(ROOT,"benchmarks/pr15i_d3_c")
def load(n,f):
 s=importlib.util.spec_from_file_location(n,os.path.join(BM,f));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
import importlib.util
RUN=load("t7run","run.py"); P,_=RUN.load_protocol()
SHA=RUN.PROTOCOL_SHA256
def boot(num,den,by,ret,cname,lid,bootstrap=10000):
 seed=int.from_bytes(hashlib.sha256(f"{SHA}|{cname}|{lid}|{num}/{den}".encode()).digest()[:8],'big')
 rng=random.Random(seed); vals=[]
 for _ in range(bootstrap):
  draw=[ret[rng.randrange(len(ret))] for _ in ret]
  n=statistics.median([by[(num,b)] for b in draw]); d=statistics.median([by[(den,b)] for b in draw]); vals.append(n/d)
 vals.sort(); return [vals[249],vals[9749]],seed
def med(v): return statistics.median(v)
def analyze(root):
 lanes=RUN.lanes(P); campaigns={}
 for name in P["campaign_names"]:
  d=os.path.join(root,name); slots=[json.load(open(os.path.join(d,"raw/slots",f"slot-{i:02d}.json"))) for i in range(1,97)]
  campaigns[name]=slots
 out={}
 for lane in lanes:
  lid=lane["id"]
  row={"id":lid,"n":lane["n"],"class":lane["class"],"k":lane["k"],"campaigns":{}}
  for cname,slots in campaigns.items():
   by={}
   for s in slots:
    l=next(x for x in s["lanes"] if x["id"]==lid); by.setdefault((s["arm"],s["block"]),[]).append(l["summary_ns"]["median"])
   for a in ("A","L","P","H"): by[(a,)] = [by[(a,b)] for b in range(1,13)]
   cap=1.25 if lane["n"]==100000 and lane["class"] in ("medium","common") else 1.50
   ret=[]; ex=[]
   for b in range(1,13):
    wr={a:max(by[(a,b)])/min(by[(a,b)]) for a in ("A","L","P","H")}
    bad=[a for a,r in wr.items() if r>cap]
    if bad: ex.append({"block":b,"within":wr,"arms":bad})
    else: ret.append(b)
   rec={"retained":ret,"excluded":ex,"cap":cap,"retained_count":len(ret)}
   if len(ret)>=4:
    lat={a:med([sum(by[(a,b)])//2 for b in ret]) for a in ("A","L","P","H")}
    raw={a:med([sum(by[(a,b)])//2 for b in range(1,13)]) for a in ("A","L","P","H")}
    rec["latency"]=lat; rec["raw_latency"]=raw; rec["raw_ratio"]={a:raw[a]/raw["A"] for a in ("L","P","H")}
    for s in ("L","P","H"): rec[f"R_{s}_A"]=lat[s]/lat["A"]
    for s in ("P","H"): rec[f"R_{s}_L"]=lat[s]/lat["L"]
    rec["R_H_P"]=lat["H"]/lat["P"]
    for num,den in (("L","A"),("P","A"),("H","A"),("P","L"),("H","L"),("H","P")):
     tmp={}
     for b in range(1,13):
      for a in (num,den): tmp[(a,b)]=sum(by[(a,b)])//2
     ci,seed=boot(num,den,tmp,ret,cname,lid); rec[f"CI_{num}_{den}"]={"low":ci[0],"high":ci[1],"seed":seed}
    sign_raw=(raw["P"]-raw["H"]); sign_f=(lat["P"]-lat["H"])
    rec["filter_sensitive"]=(sign_raw>0)!=(sign_f>0) or (sign_raw==0)!=(sign_f==0)
   row["campaigns"][cname]=rec
  out[lid]=row
 return {"schema":"pr15i-d3c-t7-analysis-v1","protocol_sha256":SHA,"series":P["campaign_names"],"lanes":out}
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--series-root",required=True); ap.add_argument("--archive-root"); ap.add_argument("--out",required=True); a=ap.parse_args(argv)
 root=os.path.realpath(a.series_root)
 r=subprocess.run([sys.executable,os.path.join(BM,"verify.py"),"--series-root",root],stdout=subprocess.PIPE,text=True)
 if r.returncode!=0: raise SystemExit("series verification failed")
 rep=json.loads(r.stdout)
 if not rep.get("full_series"): raise SystemExit("not full series")
 data=analyze(root)
 out=os.path.realpath(a.out); base=os.path.realpath(os.path.join(ROOT,RUN.TARGET_REL,"t7-derived"))
 if os.path.commonpath([out,base])!=base or os.path.exists(out): raise SystemExit("output path")
 os.makedirs(out); json.dump(data,open(os.path.join(out,"analysis.json"),"w"),sort_keys=True,indent=2)
 print(json.dumps({"status":"ANALYSIS_COMPLETE","lanes":len(data["lanes"])})); return 0
if __name__=="__main__": raise SystemExit(main())

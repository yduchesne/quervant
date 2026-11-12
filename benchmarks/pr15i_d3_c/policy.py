#!/usr/bin/env python3
"""Deterministic PR 15I-D3-C policy arithmetic (experiment-only recommendation)."""
from __future__ import annotations
import argparse, json, math, os, subprocess, sys
TOOLING_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLING_DIR=os.path.join(TOOLING_ROOT,"benchmarks/pr15i_d3_c")
PROTOCOL_SHA256="e5980b009cd34e9c7a483c126a1b3ed56a89853e251c26ba471c94203109c696"
BASE_SHA="39dbd9f571a58bea8cc03d5a406533298e809bfe"
EXPERIMENT_SHA="f2565509f75472cac8a6b380ea29791036a46f0c"

def fail(code,msg): raise SystemExit(f"{code}: {msg}")
def cj(v): return json.dumps(v,sort_keys=True,separators=(",",":"))
def rj(p):
    with open(p,"rb") as f: return json.loads(f.read().decode())
def load_protocol():
    p=os.path.join(TOOLING_DIR,"protocol_v1.json"); raw=open(p,"rb").read()
    import hashlib
    if hashlib.sha256(raw).hexdigest()!=PROTOCOL_SHA256: fail("D3C_POLICY","protocol digest")
    return json.loads(raw)
def lanes(p):
    out=[]
    for n in p["n_values"]:
        for cls in p["classes"]:
            field="group" if cls=="medium" else "key"
            term={"absent":"never","rare":"singleton","medium":"medium","common":"common"}[cls]
            for k in p["k_values"]: out.append({"id":f"pr15d_v1/{n}/{cls}/k{k}","n":n,"class":cls,"field":field,"term":term,"k":k})
    return out
def blocks(d,ls):
    slots=[]
    for i in range(1,33):
        p=os.path.join(d,"raw","slots",f"slot-{i:02d}.json")
        if not os.path.isfile(p): fail("D3C_POLICY",f"missing slot {i}")
        slots.append(rj(p))
    by={}
    for s in slots:
        by.setdefault(s["arm"],{}).setdefault(s["block"],{})[s["position"]]={l["id"]:l["summary_ns"]["median"] for l in s["lanes"]}
    out={}
    for arm,byb in by.items():
        out[arm]={}
        for b in range(1,5):
            pos=sorted(byb[b]); out[arm][b]={l["id"]:(byb[b][pos[0]][l["id"]]+byb[b][pos[1]][l["id"]])//2 for l in ls}
    return out
def med4(v): return sorted(v)[1]
def ratios(bv,ls,arm,ref):
    return {l["id"]:[bv[arm][b][l["id"]]/bv[ref][b][l["id"]] for b in range(1,5)] for l in ls}
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--series-root",required=True); ap.add_argument("--out",required=True); a=ap.parse_args(argv)
    p=load_protocol(); root=os.path.realpath(a.series_root)
    for name in [p["control_name"]]+p["campaign_names"]:
        d=os.path.join(root,name)
        r=subprocess.run([sys.executable,os.path.join(TOOLING_DIR,"verify.py"),"--campaign-dir",d],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if r.returncode!=0: fail("D3C_POLICY",f"{name} unverified: {r.stdout[-300:]}")
        rep=json.loads(r.stdout)
        if rep.get("verification")!="PASS": fail("D3C_POLICY",f"{name} not PASS")
        if name==p["control_name"] and rep["measurement_status"]!="CONTROL_QUALIFIED": fail("D3C_POLICY","control not qualified")
        if name!=p["control_name"] and rep["measurement_status"]!="FOUR_ARM_QUALIFIED": fail("D3C_POLICY",f"{name} not four-arm qualified")
    ls=lanes(p)
    cams=[]
    for name in p["campaign_names"]:
        d=os.path.join(root,name); bv=blocks(d,ls)
        cams.append((name,bv,{arm:ratios(bv,ls,arm,"A") for arm in ("L","P","H")}))
    rows=[]
    for k in p["k_values"]:
        ks=[l for l in ls if l["k"]==k]
        eligible={}
        for S in ("P","H"):
            ok=True; reasons=[]; gm=[]
            if S=="H":
                reasons.append("EXCLUDED_MEMORY: exact-set auxiliary memory was not measured")
                ok=False
            else:
                for name,bv,rs in cams:
                    rid=lambda n,cls:f"pr15d_v1/{n}/{cls}/k{k}"
                    for cls in ("medium","common"):
                        if med4(rs[S][rid(100000,cls)])>0.97: ok=False; reasons.append(f"{name}: 100K {cls} >0.97")
                    for n in p["n_values"]:
                        for cls in p["classes"]:
                            if n==100000 and cls in ("medium","common"): continue
                            if med4(rs[S][rid(n,cls)])>1.10: ok=False; reasons.append(f"{name}: {n} {cls} >1.10")
                    for cls in ("medium","common"):
                        cap=1.25
                        if any(x>cap for x in rs[S][rid(100000,cls)]): ok=False; reasons.append(f"{name}: block cap 100K {cls}")
                    for n in p["n_values"]:
                        for cls in p["classes"]:
                            if n==100000 and cls in ("medium","common"): continue
                            if any(x>1.5 for x in rs[S][rid(n,cls)]): ok=False; reasons.append(f"{name}: block cap {n} {cls}")
                    lrat=[med4(rs["L"][rid(100000,cls)]) for cls in ("medium","common")]
                    srat=[med4(rs[S][rid(100000,cls)]) for cls in ("medium","common")]
                    if min(srat[i]/lrat[i] for i in range(2))>0.98 or max(srat[i]/lrat[i] for i in range(2))>1.00: ok=False; reasons.append(f"{name}: S/L attribution")
                    logs=[]
                    for n in p["n_values"]:
                        for cls in p["classes"]:
                            r=med4(rs[S][rid(n,cls)])
                            if not (math.isfinite(r) and r>0): ok=False; reasons.append("invalid ratio")
                            else: logs.append(math.log(r))
                    gm.append(math.exp(sum(logs)/len(logs)))
            eligible[S]={"eligible":ok,"reasons":reasons,"gm":gm}
        chosen="LINEAR_BASE"; detail=""
        cands=[S for S in ("P","H") if eligible[S]["eligible"]]
        if len(cands)==1: chosen=cands[0]
        elif len(cands)==2:
            sp=max(eligible["P"]["gm"]); sh=max(eligible["H"]["gm"])
            chosen="P" if abs(sp-sh)/min(sp,sh)<0.03 else ("P" if sp<sh else "H")
        rows.append({"k":k,"selected_strategy":chosen,"eligible_P":eligible["P"]["eligible"],"eligible_H":eligible["H"]["eligible"],
                     "P_campaign_gm":eligible["P"]["gm"],"H_campaign_gm":eligible["H"]["gm"],
                     "P_reasons":eligible["P"]["reasons"],"H_reasons":eligible["H"]["reasons"]})
    status="STRATEGY_POLICY_RECOMMENDED_EXPERIMENT_ONLY" if any(r["selected_strategy"]!="LINEAR_BASE" for r in rows) else "NO_SUPPORTED_POLICY"
    out={"schema":"pr15i-d3-c-policy-v1","protocol_sha256":PROTOCOL_SHA256,"source_experiment_sha":EXPERIMENT_SHA,
         "prefilter_profile":p["prefilter_profile"],"status":status,"rows":rows,"calibration":"L is experimental linear vs A BASE"}
    with open(a.out,"x",encoding="utf-8") as f: f.write(cj(out)+"\n")
    print(cj({"status":status,"rows":len(rows)})); return 0
if __name__=="__main__": raise SystemExit(main())

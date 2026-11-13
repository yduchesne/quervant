#!/usr/bin/env python3
"""Deterministic PR 15I-D3-C policy arithmetic (experiment-only recommendation)."""
from __future__ import annotations
import argparse, json, math, os, subprocess, sys
TOOLING_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLING_DIR=os.path.join(TOOLING_ROOT,"benchmarks/pr15i_d3_c")
PROTOCOL_SHA256="55255c687ccfa65f8cffe3169cca6f01880584f30e3c7f29843489bedc42a5c5"
BASE_SHA="39dbd9f571a58bea8cc03d5a406533298e809bfe"
EXPERIMENT_SHA="3ad6c5184fbe9c011abb731415a007e3f19d21de"

def fail(code,msg): raise SystemExit(f"{code}: {msg}")
def cj(v): return json.dumps(v,sort_keys=True,separators=(",",":"))
def rj(p):
    with open(p,"rb") as f: return json.loads(f.read().decode())
def load_protocol():
    p=os.path.join(TOOLING_DIR,"protocol_v2.json"); raw=open(p,"rb").read()
    import hashlib
    if hashlib.sha256(raw).hexdigest()!=PROTOCOL_SHA256: fail("D3C_POLICY","protocol digest")
    return json.loads(raw)
MEMORY_GUARD=2_097_152
MICRO_VARIANTS={"linear","P0","P1","P2","exact_set"}
MICRO_TRACES={"miss_stable","duplicate_retained","churn","evicted_revisit","collision_distinct"}
MICRO_LENGTHS={8,32,128,1024}

def _no_dupes(pairs):
    out={}
    for k,v in pairs:
        if k in out: raise ValueError(f"duplicate JSON key: {k}")
        out[k]=v
    return out

def validate_micro_memory(micro,protocol,expected_source_sha):
    if not isinstance(micro,dict): fail("POLICY_NOT_DERIVABLE","micro is not an object")
    if micro.get("schema")!="pr15i-d3c-micro-v1": fail("POLICY_NOT_DERIVABLE","micro schema")
    if micro.get("selected_profile")!=protocol["prefilter_profile"]: fail("POLICY_NOT_DERIVABLE","micro profile")
    if micro.get("protocol_sha256")!=PROTOCOL_SHA256: fail("POLICY_NOT_DERIVABLE","micro protocol")
    if micro.get("source_experiment_sha")!=expected_source_sha: fail("POLICY_NOT_DERIVABLE","micro source")
    recs=micro.get("records")
    if not isinstance(recs,list): fail("POLICY_NOT_DERIVABLE","micro records")
    ks=[int(k) for k in protocol["k_values"]]
    seen=set(); maxima={k:0 for k in ks}
    for r in recs:
        if not isinstance(r,dict): fail("POLICY_NOT_DERIVABLE","record shape")
        v=r.get("variant"); k=r.get("k"); ln=r.get("key_len"); tr=r.get("trace")
        if v not in MICRO_VARIANTS or k not in ks or ln not in MICRO_LENGTHS or tr not in MICRO_TRACES:
            fail("POLICY_NOT_DERIVABLE","unexpected combination")
        combo=(v,k,ln,tr)
        if combo in seen: fail("POLICY_NOT_DERIVABLE",f"duplicate {combo}")
        seen.add(combo)
        rounds=r.get("rounds")
        if not isinstance(rounds,list) or len(rounds)!=5: fail("POLICY_NOT_DERIVABLE","rounds")
        for x in rounds:
            if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0:
                fail("POLICY_NOT_DERIVABLE","duration")
        for name in ("set_len","set_capacity","key_bytes"):
            x=r.get(name)
            if isinstance(x,bool) or not isinstance(x,int) or x<0:
                fail("POLICY_NOT_DERIVABLE",name)
        if r["set_len"]>r["set_capacity"]: fail("POLICY_NOT_DERIVABLE","set_len>capacity")
        if v=="exact_set":
            if k>0 and r["set_len"]==0: fail("POLICY_NOT_DERIVABLE","empty exact set")
            size=r["set_capacity"]*40+r["key_bytes"]
            maxima[k]=max(maxima[k],size)
    expected=len(MICRO_VARIANTS)*len(ks)*len(MICRO_LENGTHS)*len(MICRO_TRACES)
    if len(seen)!=expected: fail("POLICY_NOT_DERIVABLE",f"incomplete {len(seen)}/{expected}")
    serialized=micro.get("exact_set_aux_bytes_estimate")
    want={str(k):maxima[k] for k in ks}
    if serialized!=want: fail("POLICY_NOT_DERIVABLE","encoded memory map differs")
    return want

def load_micro(path,protocol,expected_source_sha):
    real=os.path.realpath(path)
    if os.path.islink(path) or not os.path.isfile(real): fail("POLICY_NOT_DERIVABLE","micro path")
    root=os.path.realpath(os.path.join(TOOLING_ROOT,"target","pr15i-d3-c"))
    if not real.startswith(root+os.sep): fail("POLICY_NOT_DERIVABLE","micro outside target root")
    if "docs/pr-artifacts" in real or real.endswith("exploratory.md"): fail("POLICY_NOT_DERIVABLE","exploratory input")
    with open(real,"rb") as f: raw=f.read()
    import hashlib
    micro=json.loads(raw.decode(),object_pairs_hook=_no_dupes)
    mem=validate_micro_memory(micro,protocol,expected_source_sha)
    return mem,hashlib.sha256(raw).hexdigest()

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
def evaluate_arm(S, k, cams, p, ls, memory_bytes):
    ok=True; reasons=[]; gm=[]
    if S=="H" and memory_bytes>MEMORY_GUARD:
        reasons.append(f"EXCLUDED_MEMORY: exact-set auxiliary estimate {memory_bytes} > {MEMORY_GUARD}")
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
    return ok, reasons, gm

def choose_candidate(cands, gm):
    if not cands: return "LINEAR_BASE"
    if len(cands)==1: return cands[0]
    sp=max(gm["P"]); sh=max(gm["H"])
    return "P" if abs(sp-sh)/min(sp,sh)<0.03 else ("P" if sp<sh else "H")

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--series-root",required=True); ap.add_argument("--out",required=True); ap.add_argument("--micro-json",required=True); a=ap.parse_args(argv)
    p=load_protocol(); mem_map,micro_sha=load_micro(a.micro_json,p,EXPERIMENT_SHA); root=os.path.realpath(a.series_root)
    r=subprocess.run([sys.executable,os.path.join(TOOLING_DIR,"verify.py"),"--series-root",root],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode!=0: fail("POLICY_NOT_DERIVABLE",f"series unverified: {r.stdout[-500:]}")
    rep=json.loads(r.stdout)
    if rep.get("verification")!="PASS" or not rep.get("full_series") or not rep.get("provenance_consistent"):
        fail("POLICY_NOT_DERIVABLE",f"series not qualified: {r.stdout[-500:]}")
    if rep.get("control")!="CONTROL_QUALIFIED": fail("POLICY_NOT_DERIVABLE","control not qualified")
    if any(s!="FOUR_ARM_QUALIFIED" for s in rep.get("campaigns",[])): fail("POLICY_NOT_DERIVABLE","campaign not qualified")
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
            ok,reasons,gm=evaluate_arm(S,k,cams,p,ls,mem_map[str(k)] if S=="H" else 0)
            eligible[S]={"eligible":ok,"reasons":reasons,"gm":gm}
        cands=[S for S in ("P","H") if eligible[S]["eligible"]]
        chosen=choose_candidate(cands,{"P":eligible["P"]["gm"],"H":eligible["H"]["gm"]})
        rows.append({"k":k,"selected_strategy":chosen,"eligible_P":eligible["P"]["eligible"],"eligible_H":eligible["H"]["eligible"],
                     "P_campaign_gm":eligible["P"]["gm"],"H_campaign_gm":eligible["H"]["gm"],
                     "P_reasons":eligible["P"]["reasons"],"H_reasons":eligible["H"]["reasons"]})
    status="STRATEGY_POLICY_RECOMMENDED_EXPERIMENT_ONLY" if any(r["selected_strategy"]!="LINEAR_BASE" for r in rows) else "NO_SUPPORTED_POLICY"
    out={"schema":"pr15i-d3-c-policy-v1","protocol_sha256":PROTOCOL_SHA256,"source_experiment_sha":EXPERIMENT_SHA,
         "prefilter_profile":p["prefilter_profile"],"status":status,"rows":rows,"calibration":"L is experimental linear vs A BASE",
         "micro_json_sha256":micro_sha,"h_memory_bytes_by_k":{str(k):mem_map[str(k)] for k in [int(x) for x in p["k_values"]]}}
    with open(a.out,"x",encoding="utf-8") as f: f.write(cj(out)+"\n")
    print(cj({"status":status,"rows":len(rows)})); return 0
if __name__=="__main__": raise SystemExit(main())

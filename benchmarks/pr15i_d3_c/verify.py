#!/usr/bin/env python3
"""Independent verifier for PR 15I-D3-C four-arm evidence (no controller import)."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
TOOLING_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLING_DIR=os.path.join(TOOLING_ROOT,"benchmarks/pr15i_d3_c")
PROTOCOL_SHA256="e5980b009cd34e9c7a483c126a1b3ed56a89853e251c26ba471c94203109c696"
BASE_SHA="39dbd9f571a58bea8cc03d5a406533298e809bfe"
EXPERIMENT_SHA="f2565509f75472cac8a6b380ea29791036a46f0c"
TARGET_REL="target/pr15i-d3-c"

def rej(code,msg): raise VerifyError(code,msg)
class VerifyError(Exception):
    def __init__(self,code,msg): super().__init__(f"{code}: {msg}"); self.code=code
def cj(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def sh(v): return hashlib.sha256(v).hexdigest()
def sf(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda:f.read(1<<20),b""): h.update(c)
    return h.hexdigest()
def _nodup(pairs):
    seen=set()
    for k,_ in pairs:
        if k in seen: rej("V_JSON",f"duplicate key {k}")
        seen.add(k)
    return dict(pairs)
def rj(p):
    if os.path.islink(p) or not os.path.isfile(p): rej("V_MISSING",p)
    with open(p,"rb") as f: return json.loads(f.read().decode(),object_pairs_hook=_nodup)
def load_protocol():
    p=os.path.join(TOOLING_DIR,"protocol_v1.json"); raw=open(p,"rb").read()
    if sh(raw)!=PROTOCOL_SHA256: rej("V_PROTOCOL","protocol digest differs")
    return json.loads(raw.decode())
def confined(p):
    root=os.path.realpath(os.path.join(TOOLING_ROOT,TARGET_REL)); rp=os.path.realpath(p)
    if os.path.commonpath([rp,root])!=root or rp==root or not os.path.isdir(rp): rej("V_PATH",p)
    return rp
def lanes(protocol):
    out=[]
    for n in protocol["n_values"]:
        for cls in protocol["classes"]:
            field="group" if cls=="medium" else "key"
            term={"absent":"never","rare":"singleton","medium":"medium","common":"common"}[cls]
            for k in protocol["k_values"]: out.append({"id":f"pr15d_v1/{n}/{cls}/k{k}","n":n,"class":cls,"field":field,"term":term,"k":k})
    return out
def oracle(n,cls,k):
    ids={"absent":[],"rare":["d00000000"],
         "medium":[f"d{i:08}" for i in range(0,n,8)],
         "common":[f"d{i:08}" for i in range(2,n,2)]}[cls]
    return {"total_hits":len(ids),"doc_ids":ids[:k]}
def schedule(protocol,kind):
    order=protocol["arm_order"] if kind=="four_arm" else [["A","B","B","A"],["B","A","A","B"],["B","A","A","B"],["A","B","B","A"]]
    per=8 if kind=="four_arm" else 4; plan=[]
    for b,o in enumerate(order,start=1):
        for pos,arm in enumerate(o,start=1): plan.append({"slot":(b-1)*per+pos,"block":b,"position":pos,"arm":arm})
    return plan
def block_values(slots,ls,blocks):
    out={}
    for s in slots:
        out.setdefault(s["arm"],{}).setdefault(s["block"],{})[s["position"]]={l["id"]:l["summary_ns"]["median"] for l in s["lanes"]}
    res={}
    for arm,byb in out.items():
        res[arm]={}
        for b in range(1,blocks+1):
            pos=sorted(byb.get(b,{}))
            if len(pos)!=2: rej("V_SLOT",f"arm {arm} block {b}: {len(pos)} slots")
            res[arm][b]={l["id"]:(byb[b][pos[0]][l["id"]]+byb[b][pos[1]][l["id"]])//2 for l in ls}
    return res
def median4(v): return sorted(v)[1]
def drift_cap(l):
    return 1.25 if l["n"]==100000 and l["class"] in ("medium","common") else 1.50
def drift_report(slots,ls,blocks,arms):
    violations=[]; by={}
    for s in slots: by.setdefault(s["arm"],{}).setdefault(s["block"],{})[s["position"]]={l["id"]:l["summary_ns"]["median"] for l in s["lanes"]}
    for arm in arms:
        for l in ls:
            cap=drift_cap(l); vals=[]
            for b in range(1,blocks+1):
                pos=sorted(by.get(arm,{}).get(b,{}))
                if len(pos)!=2: violations.append({"gate":"BLOCK_SHAPE","arm":arm,"block":b}); continue
                v=[by[arm][b][x][l["id"]] for x in pos]; r=max(v)/min(v)
                if r>cap: violations.append({"gate":"WITHIN_BLOCK_DRIFT","arm":arm,"lane":l["id"],"block":b,"ratio":r,"cap":cap})
                vals.append((v[0]+v[1])//2)
            if len(vals)==blocks:
                r=max(vals)/min(vals)
                if r>cap: violations.append({"gate":"BLOCK_DRIFT","arm":arm,"lane":l["id"],"ratio":r,"cap":cap})
    return {"status":"PASS" if not violations else "FAIL","violations":violations}
def summary_control(protocol,bv,ls,blocks,slots):
    drift=drift_report(slots,ls,blocks,["A","B"]); lanes_out={}; ok=drift["status"]=="PASS"
    for l in ls:
        rs=[bv["B"][b][l["id"]]/bv["A"][b][l["id"]] for b in range(1,blocks+1)]
        med=median4(rs); exempt=l["n"]==10000 and l["class"] in ("absent","rare")
        soft=[r for r in rs if not (0.80<=r<=1.25)]
        lane_ok=0.85<=med<=1.15
        lane_ok=lane_ok and (len(soft)<=1 and all(0.67<=r<=1.5 for r in rs) if exempt else not soft)
        ok=ok and lane_ok
        lanes_out[l["id"]]={"block_ratios":rs,"median_ratio":med,"passes":lane_ok}
    return {"schema":"pr15i-d3c-summary-v1","campaign":protocol["control_name"],"kind":"control","protocol_sha256":PROTOCOL_SHA256,
            "source_base_sha":BASE_SHA,"drift":drift,"a_a":{"passes":ok,"lanes":lanes_out},"status":"CONTROL_QUALIFIED" if ok else "MEASUREMENT_BLOCKED"}
def summary_campaign(protocol,bv,ls,blocks,campaign,slots,structural_ok):
    drift=drift_report(slots,ls,blocks,["A","L","P","H"]); out=[]
    status="FOUR_ARM_QUALIFIED" if structural_ok and drift["status"]=="PASS" else "MEASUREMENT_BLOCKED"
    for l in ls:
        a=[bv["A"][b][l["id"]] for b in range(1,blocks+1)]
        e={"id":l["id"],"n":l["n"],"class":l["class"],"k":l["k"],"A_blocks_ns":a}
        for arm in ("L","P","H"):
            v=[bv[arm][b][l["id"]] for b in range(1,blocks+1)]; e[f"{arm}_blocks_ns"]=v
            e[f"{arm}_over_A_block"]=[x/y for x,y in zip(v,a)]; e[f"{arm}_over_A_median"]=median4(e[f"{arm}_over_A_block"])
            e[f"{arm}_minus_A_median_ns"]=median4([y-x for x,y in zip(a,v)])
        for x,y in (("P","L"),("H","L"),("H","P")):
            e[f"{x}_over_{y}_median"]=median4([v/w for v,w in zip(e[f"{x}_blocks_ns"],e[f"{y}_blocks_ns"])])
        out.append(e)
    return {"schema":"pr15i-d3c-summary-v1","campaign":campaign,"kind":"four_arm","protocol_sha256":PROTOCOL_SHA256,
            "source_base_sha":BASE_SHA,"source_experiment_sha":EXPERIMENT_SHA,"prefilter_profile":protocol["prefilter_profile"],
            "lanes":out,"drift":drift,"arms":{"A":"BASE","L":"linear","P":"prefilter","H":"exact_set"},"status":status}
def verify_readiness(rec,host,protocol):
    spec=protocol["host_readiness"]
    if rec.get("schema")!="pr15i-d3c-host-readiness-v1" or rec.get("protocol_sha256")!=PROTOCOL_SHA256: rej("V_READINESS","schema/protocol")
    if rec.get("role_cpus")!={"adapter":host["adapter_cpu"],"controller":host["controller_cpu"]}: rej("V_READINESS","cpu pair")
    if rec.get("host_fingerprint")!=host["host_fingerprint"]: rej("V_READINESS","host fingerprint")
    obs=rec.get("observations")
    if not isinstance(obs,list) or len(obs)!=7: rej("V_READINESS","observation count")
    for o in obs:
        if set(o.get("cpus",{}))!={str(host["adapter_cpu"]),str(host["controller_cpu"])}: rej("V_READINESS","cpu keys")
        for v in o["cpus"].values():
            if len(v)!=8 or any((isinstance(x,bool) or not isinstance(x,int) or x<0 or x>2**64-1) for x in v): rej("V_READINESS","ticks")
    if not (4_500_000_000<=rec["settle_monotonic_end_ns"]-rec["settle_monotonic_start_ns"]<=7_500_000_000): rej("V_READINESS","settle")
    for role,cpu in (("adapter",host["adapter_cpu"]),("controller",host["controller_cpu"])):
        busy=[]
        for i in range(6):
            a=obs[i]["cpus"][str(cpu)]; b=obs[i+1]["cpus"][str(cpu)]
            d=[y-x for x,y in zip(a,b)]
            if any(x<0 for x in d) or sum(d)<=0: rej("V_READINESS","counter")
            e=(obs[i+1]["monotonic_ns"]-obs[i]["monotonic_ns"])/1e6
            if not (spec["minimum_actual_interval_ms"]<=e<=spec["maximum_actual_interval_ms"]): rej("V_READINESS","interval")
            bm=(1000*(sum(d)-d[3]))//sum(d); sm=(1000*d[7])//sum(d)
            if bm>spec["max_busy_permille"] or sm>spec["max_steal_permille"]: rej("V_READINESS","threshold")
            busy.append(bm)
        if sorted(busy)[2]>spec["max_median_busy_permille"]: rej("V_READINESS","median")
    if rec.get("readiness_status")!="READY" or rec.get("failure_codes")!=[] or rec.get("queries_executed")!=0: rej("V_READINESS","status")
def inventory(d):
    seal=rj(os.path.join(d,"raw","seal.json")); sealed=set(seal["files"])
    for rel,dig in seal["files"].items():
        if rel.startswith("/") or ".." in rel.split("/"): rej("V_SEAL","unsafe")
        p=os.path.join(d,rel)
        if os.path.islink(p) or not os.path.isfile(p): rej("V_SEAL",f"missing {rel}")
        if sf(p)!=dig: rej("V_SEAL",f"changed {rel}")
    cs=os.path.join(d,"compile-source")
    if os.path.islink(cs): rej("V_SYMLINK","compile-source")
    if os.path.lexists(cs) and not os.path.isdir(cs): rej("V_INVENTORY","compile-source file")
    if any(x=="compile-source" or x.startswith("compile-source/") for x in sealed): rej("V_SEAL","compile-source sealed")
    for root,dirs,names in os.walk(d):
        rel=os.path.relpath(root,d).replace(os.sep,"/")
        if rel==".": rel=""
        dirs[:]=[n for n in sorted(dirs) if not (rel=="" and n in ("build","indexes","corpus","compile-source"))]
        for n in sorted(names):
            r=f"{rel}/{n}".lstrip("/")
            if r in ("raw/seal.json","verification.json"): continue
            if r not in sealed: rej("V_INVENTORY",f"unlisted {r}")
    return seal
def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--campaign-dir"); ap.add_argument("--series-root"); args=ap.parse_args(argv)
    try:
        if args.campaign_dir:
            report=verify_campaign(confined(args.campaign_dir))
            print(json.dumps(report,sort_keys=True,separators=(",",":"))); return 0
        if args.series_root:
            root=os.path.realpath(args.series_root); p=load_protocol(); c=verify_campaign(confined(os.path.join(root,p["control_name"])))
            reps=[]
            for name in p["campaign_names"]:
                d=os.path.join(root,name)
                if not os.path.isdir(d): rej("V_SERIES",f"missing {name}")
                reps.append(verify_campaign(confined(d)))
            statuses=[r["measurement_status"] for r in reps]
            ok=c["measurement_status"]=="CONTROL_QUALIFIED" and all(s=="FOUR_ARM_QUALIFIED" for s in statuses)
            print(json.dumps({"schema":"pr15i-d3c-comparison-v1","verification":"PASS" if all(r["verification"]=="PASS" for r in reps) and c["verification"]=="PASS" else "FAIL",
                "control":c["measurement_status"],"campaigns":statuses,"full_series":ok},sort_keys=True,separators=(",",":"))); return 0 if ok else 3
        ap.error("provide --campaign-dir or --series-root")
    except VerifyError as e:
        print(json.dumps({"schema":"pr15i-d3c-verification-v1","verification":"FAIL","reasons":[{"code":e.code,"detail":str(e)}]},sort_keys=True,separators=(",",":"))); return 3

def verify_campaign(d):
    p=load_protocol(); m=rj(os.path.join(d,"manifest.json")); a=rj(os.path.join(d,"authorization.json"))
    if m.get("schema")!="pr15i-d3c-manifest-v1" or a.get("schema")!="pr15i-d3c-authorization-v1": rej("V_MANIFEST","schema")
    synthetic=bool(a.get("rehearsal_only")) or "rehearsal" in d.split(os.sep)
    if m.get("protocol_sha256")!=PROTOCOL_SHA256 or a.get("protocol_sha256")!=PROTOCOL_SHA256: rej("V_PROTOCOL","digest")
    kind=m["kind"]; campaign=m["campaign"]
    if kind=="control" and campaign!=p["control_name"]: rej("V_CAMPAIGN","control name")
    if kind=="four_arm" and campaign not in p["campaign_names"]: rej("V_CAMPAIGN","campaign name")
    seal=inventory(d)
    host=rj(os.path.join(d,"raw/host-attestation.json")); ready=rj(os.path.join(d,"raw/host-readiness.json"))
    if m.get("host_attestation_sha256")!=sf(os.path.join(d,"raw/host-attestation.json")): rej("V_SEAL","host digest")
    if m.get("host_readiness_sha256")!=sf(os.path.join(d,"raw/host-readiness.json")): rej("V_SEAL","readiness digest")
    if m.get("build_provenance_sha256")!=sf(os.path.join(d,"raw/build-provenance.json")): rej("V_SEAL","provenance digest")
    verify_readiness(ready,host,p)
    if host.get("protocol_sha256")!=PROTOCOL_SHA256: rej("V_PROTOCOL","host")
    if host.get("controller_cpu")==host.get("adapter_cpu"): rej("V_AFFINITY","same cpu")
    roles={x["role"] for x in host.get("filesystems",[])}
    if roles!={"repository","campaign_output","compile_source","build_A","build_B","corpus","indexes"}: rej("V_HOST","roles")
    for x in host["filesystems"]:
        if x["harness_fstype"]!=x["findmnt_fstype"] or x["findmnt_fstype"] not in ("ext4","xfs","btrfs"): rej("V_HOST","fs")
    prov=rj(os.path.join(d,"raw/build-provenance.json"))
    arms=m["arms"]; kinds={"A","B"} if kind=="control" else {"A","L","P","H"}
    if set(arms)!=kinds: rej("V_BUILD","arm set")
    if kind=="control":
        if arms["A"]["binary_sha256"]!=arms["B"]["binary_sha256"] or arms["A"]["binary_bytes"]!=arms["B"]["binary_bytes"]: rej("V_AA","binary mismatch")
    else:
        base=arms["A"]["binary_sha256"]
        for arm in ("L","P","H"):
            if arms[arm]["binary_sha256"]!=arms["L"]["binary_sha256"]: rej("V_BUILD","L/P/H binary differ")
            if arms[arm]["binary_sha256"]==base: rej("V_AB","experiment equals BASE")
        if m.get("source_experiment_sha")!=EXPERIMENT_SHA: rej("V_SOURCE","experiment sha")
    if m.get("source_base_sha")!=BASE_SHA: rej("V_SOURCE","base sha")
    if prov.get("canonical_source_path")!=os.path.join(d,"compile-source"): rej("V_SOURCE","canonical path")
    events=prov.get("events")
    if not isinstance(events,list) or {e["arm"] for e in events}!=kinds: rej("V_BUILD","event arms")
    seen=set()
    for ev in events:
        if ev["source_sha"] not in (BASE_SHA,EXPERIMENT_SHA): rej("V_SOURCE","event source")
        want_feature=kind!="control" and ev["arm"]!="A"
        if ev["feature"]!=want_feature: rej("V_BUILD","feature flag")
        if ev["binary_sha256"]!=arms[ev["arm"]]["binary_sha256"] or ev["binary_bytes"]!=arms[ev["arm"]]["binary_bytes"]: rej("V_BINARY","event digest")
        if ev["source_sha"]!=arms[ev["arm"]]["source_sha"]: rej("V_SOURCE","event arm sha")
        if ev["canonical_source"]!=prov["canonical_source_path"]: rej("V_SOURCE","event path")
        if not any(x in ev["argv"] for x in ("--features",)) and want_feature: rej("V_BUILD","feature argv")
        seen.add(ev["arm"])
    if seen!=kinds: rej("V_BUILD","duplicate/missing events")
    # indexes
    digests={}
    for arm,info in arms.items():
        for n in p["n_values"]:
            lay=info["indexes"][str(n)]
            if n==100000 and lay["bytes"]!=p["index_100k_committed_sentinel"]: rej("V_INDEX","100K sentinel")
            digests.setdefault(n,set()).add(lay["digest"])
            actual=os.path.join(d,"indexes",f"{arm}-n{n}")
            if os.path.isdir(actual):
                files=[]
                for root,dirs,names in os.walk(actual):
                    for name in sorted(names):
                        fp=os.path.join(root,name); files.append({"path":os.path.relpath(fp,actual).replace(os.sep,"/"),"size":os.path.getsize(fp),"sha256":sf(fp)})
                files.sort(key=lambda x:x["path"])
                if sh(cj(files))!=lay["digest"]: rej("V_INDEX",f"{arm}/n{n} layout")
    for n,ds in digests.items():
        if len(ds)!=1: rej("V_INDEX","arm index digests differ")
    # slots
    plan=schedule(p,kind); ls=lanes(p); slots=[]
    for entry in plan:
        s=rj(os.path.join(d,"raw/slots",f"slot-{entry['slot']:02d}.json"))
        if s.get("schema")!="pr15i-d3c-slot-v1" or (s["slot"],s["block"],s["position"],s["arm"])!=(entry["slot"],entry["block"],entry["position"],entry["arm"]): rej("V_SLOT","address")
        arm=arms[s["arm"]]
        if s["source_sha"]!=arm["source_sha"] or s["binary_sha256"]!=arm["binary_sha256"]: rej("V_SLOT","binary")
        if s["index_digests"]!={str(n):arm["indexes"][str(n)]["digest"] for n in p["n_values"]}: rej("V_SLOT","index")
        if s.get("contention_before",{}).get("state")!="clear" or s.get("contention_after",{}).get("state")!="clear": rej("V_CONTENTION","probe")
        if s.get("controller_affinity_before")!=[host["controller_cpu"]] or s.get("controller_affinity_after")!=[host["controller_cpu"]]: rej("V_AFFINITY","controller")
        recs=s["lanes"]
        if [r["id"] for r in recs]!=[l["id"] for l in ls]: rej("V_SLOT","lane order")
        for l,r in zip(ls,recs):
            exp=oracle(l["n"],l["class"],l["k"])
            if r.get("total_hits")!=exp["total_hits"] or r.get("doc_ids")!=exp["doc_ids"]: rej("V_ORACLE",l["id"])
            sm=r.get("samples_ns")
            if not isinstance(sm,list) or len(sm)!=20 or any((isinstance(x,bool) or not isinstance(x,int) or x<=0) for x in sm): rej("V_SAMPLE",l["id"])
            if r["summary_ns"]["median"]!=sorted(sm)[9]: rej("V_SAMPLE",l["id"])
            mode=p["arm_modes"].get(s["arm"],"BASE")
            want=None if mode=="BASE" else f"PR15I_D3C_MODE=v1:{mode}:{p['prefilter_profile'] if mode=='prefilter' else 'none'}"
            if r.get("mode_marker")!=want: rej("V_MODE",l["id"])
            if r.get("affinity_before")!=[host["adapter_cpu"]] or r.get("affinity_after")!=[host["adapter_cpu"]]: rej("V_AFFINITY",l["id"])
            if not isinstance(r.get("adapter_pid"),int) or r["adapter_pid"]<=0: rej("V_AFFINITY",l["id"])
        slots.append(s)
    bv=block_values(slots,ls,4)
    structural_ok=all(len(x)==1 for x in digests.values())
    summary=summary_control(p,bv,ls,4,slots) if kind=="control" else summary_campaign(p,bv,ls,4,campaign,slots,structural_ok)
    actual=rj(os.path.join(d,"sanitized/summary.json"))
    if cj(actual)!=cj(summary): rej("V_SUMMARY","summary mismatch")
    status="SYNTHETIC_REHEARSAL_ONLY" if synthetic else summary["status"]
    return {"schema":"pr15i-d3c-verification-v1","campaign":campaign,"kind":kind,"verification":"PASS",
            "measurement_status":status,"slots":len(slots),"lanes":len(ls)*len(slots),
            "samples":len(ls)*len(slots)*20,"sealed_members":len(seal["files"])}
if __name__=="__main__": raise SystemExit(main())

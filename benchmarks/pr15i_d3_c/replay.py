#!/usr/bin/env python3
"""Deterministic synthetic rehearsal for the PR 15I-D3-C verifier (never evidence)."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, shutil, subprocess, sys
TOOLING_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLING_DIR=os.path.join(TOOLING_ROOT,"benchmarks/pr15i_d3_c")
def load(n,f):
    s=importlib.util.spec_from_file_location(n,os.path.join(TOOLING_DIR,f)); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
RUN=load("d3c_replay_run","run.py"); P=RUN.load_protocol()[0]
BASE=RUN.BASE_SHA; EXP=RUN.EXPERIMENT_SHA
def fail(code,msg): raise SystemExit(f"{code}: {msg}")
def cj(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def sh(v): return hashlib.sha256(v).hexdigest()
def sf(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda:f.read(1<<20),b""): h.update(c)
    return h.hexdigest()
def wj(p,v):
    os.makedirs(os.path.dirname(p),exist_ok=True)
    with open(p,"wb") as f: f.write(cj(v)+b"\n")
def ticks(cpus):
    state={c:[1000,0,500,20000,0,0,0,0] for c in cpus}; out=[]
    out.append({str(c):list(state[c]) for c in cpus})
    for _ in range(6):
        for c in cpus:
            for i,d in enumerate((3,0,2,95,0,0,0,0)): state[c][i]+=d
        out.append({str(c):list(state[c]) for c in cpus})
    return out
def host(campaign):
    fs=[{"role":r,"path":f"/x/{r}","harness_fstype":"ext4","findmnt_fstype":"ext4"} for r in
        ("repository","campaign_output","compile_source","build_A","build_B","corpus","indexes")]
    h={"schema":"pr15i-d3c-host-attestation-v1","protocol_sha256":RUN.PROTOCOL_SHA256,"campaign":campaign,
       "kernel":"rehearsal-kernel","machine":"x86_64","cpu_model":"rehearsal-cpu","cpu_count":12,
       "allowed_cpus_before_pin":list(range(12)),"controller_cpu":1,"adapter_cpu":0,
       "controller_affinity_after_pin":[1],"filesystems":fs,
       "toolchains":{"rustc":"r","cargo":"c","python3":"p"},"recorded_utc":"rehearsal",
       "cpu_topology":{"adapter":{"cpu":0,"package_id":0,"core_id":0,"thread_siblings":"0"},
                       "controller":{"cpu":1,"package_id":0,"core_id":1,"thread_siblings":"1"}}}
    h["host_fingerprint"]=sh(cj({"kernel":h["kernel"],"machine":h["machine"],"cpu_model":h["cpu_model"],"cpu_count":h["cpu_count"],
        "allowed_cpus":h["allowed_cpus_before_pin"],"controller_cpu":1,"adapter_cpu":0,
        "filesystems":{i["role"]:i["findmnt_fstype"] for i in fs}}))
    return h
def ready(campaign,hostrec):
    obs=[]; ns=0
    states=ticks([0,1])
    for i,c in enumerate(states):
        ns=(i+1)*1_000_000_000
        obs.append({"monotonic_ns":ns,"cpus":{k:list(v) for k,v in c.items()}})
    metrics={"adapter":[{"interval":i+1,"actual_ms":1000.0,"busy_permille":50,"steal_permille":0} for i in range(6)],
             "controller":[{"interval":i+1,"actual_ms":1000.0,"busy_permille":50,"steal_permille":0} for i in range(6)]}
    return {"schema":"pr15i-d3c-host-readiness-v1","protocol_sha256":RUN.PROTOCOL_SHA256,"campaign":campaign,
            "role_cpus":{"adapter":0,"controller":1},"host_fingerprint":hostrec["host_fingerprint"],
            "settle_monotonic_start_ns":0,"settle_monotonic_end_ns":5_000_000_000,"observations":obs,
            "interval_metrics":metrics,"lower_median_busy_permille":{"adapter":50,"controller":50},
            "readiness_status":"READY","failure_codes":[],"optional_cpu_frequency_khz":{"adapter":None,"controller":None},
            "queries_executed":0}
def layout(n):
    files=[]; return {"files":files,"bytes":15747551 if n==100000 else 1560111,"digest":sh(cj(files))}
def build_fixture(root,kind,campaign,dp):
    d=os.path.join(root,campaign)
    if os.path.exists(d): shutil.rmtree(d)
    os.makedirs(os.path.join(d,"compile-source")); os.makedirs(os.path.join(d,"raw"))
    os.makedirs(os.path.join(d,"indexes")); os.makedirs(os.path.join(d,"sanitized"))
    hp=host(campaign); wj(os.path.join(d,"raw","host-attestation.json"),hp)
    wj(os.path.join(d,"raw","host-readiness.json"),ready(campaign,hp))
    bs={"A":{"source_sha":BASE,"binary_sha256":dp["base_binary"],"binary_bytes":dp["base_bytes"],"feature":False,"argv":["cargo","build"],"arm":"A"},
        "B":{"source_sha":BASE,"binary_sha256":dp["base_binary"],"binary_bytes":dp["base_bytes"],"feature":False,"argv":["cargo","build"],"arm":"B"}} if kind=="control" else {
        "A":{"source_sha":BASE,"binary_sha256":dp["base_binary"],"binary_bytes":dp["base_bytes"],"feature":False,"argv":["cargo","build"],"arm":"A"},
        "L":{"source_sha":EXP,"binary_sha256":dp["experiment_binary"],"binary_bytes":dp["experiment_bytes"],"feature":True,"argv":["cargo","build","--features","x"],"arm":"L"},
        "P":{"source_sha":EXP,"binary_sha256":dp["experiment_binary"],"binary_bytes":dp["experiment_bytes"],"feature":True,"argv":["cargo","build","--features","x"],"arm":"P"},
        "H":{"source_sha":EXP,"binary_sha256":dp["experiment_binary"],"binary_bytes":dp["experiment_bytes"],"feature":True,"argv":["cargo","build","--features","x"],"arm":"H"}}
    for ev in bs.values(): ev["canonical_source"]=os.path.join(d,"compile-source")
    wj(os.path.join(d,"raw","build-provenance.json"),{"schema":"pr15i-d3c-build-provenance-v1","campaign":campaign,"kind":kind,
        "canonical_source_path":os.path.join(d,"compile-source"),"source_base_sha":BASE,
        "source_experiment_sha":EXP if kind!="control" else None,"events":list(bs.values()),
        "index_digests":{a:{str(n):layout(n)["digest"] for n in P["n_values"]} for a in bs}})
    ls=RUN.lanes(P); plan=RUN.control_schedule(P) if kind=="control" else RUN.schedule(P,campaign)
    slots=[]
    for e in plan:
        arm=e["arm"]; recs=[]
        for j,l in enumerate(ls):
            base=1_000_000+10_000*j+100*e["block"]+7*e["position"]
            if kind=="control": val=base
            elif arm=="A": val=base
            elif arm=="L": val=base+1000
            elif arm=="P": val=base-50000
            else: val=base-60000
            samples=[val+(t%5) for t in range(20)]
            mode=P["arm_modes"].get(arm,"BASE")
            marker=None if mode=="BASE" else f"PR15I_D3C_MODE=v1:{mode}:{P['prefilter_profile'] if mode=='prefilter' else 'none'}"
            exp=RUN.expected_for(P,l["n"])[l["id"]]
            recs.append({"id":l["id"],"n":l["n"],"class":l["class"],"field":l["field"],"term":l["term"],"k":l["k"],
                "samples_ns":samples,"summary_ns":{"count":20,"median":sorted(samples)[9]},
                "total_hits":exp["total_hits"],"doc_ids":exp["doc_ids"],"expected_total_hits":exp["total_hits"],
                "expected_doc_ids":exp["doc_ids"],"oracle_ok":True,"mode_marker":marker,"adapter_pid":1000+j,
                "affinity_before":[0],"affinity_after":[0]})
        slot={"schema":"pr15i-d3c-slot-v1","slot":e["slot"],"block":e["block"],"position":e["position"],"arm":arm,
              "source_sha":bs[arm]["source_sha"],"binary_sha256":bs[arm]["binary_sha256"],
              "index_digests":{str(n):layout(n)["digest"] for n in P["n_values"]},
              "controller_affinity_before":[1],"controller_affinity_after":[1],
              "contention_before":{"state":"clear","reason_codes":[]},"contention_after":{"state":"clear","reason_codes":[]},"lanes":recs}
        wj(os.path.join(d,"raw","slots",f"slot-{e['slot']:02d}.json"),slot); slots.append(slot)
    arms={a:{"source_sha":bs[a]["source_sha"],"binary_sha256":bs[a]["binary_sha256"],"binary_bytes":bs[a]["binary_bytes"],
             "indexes":{str(n):layout(n) for n in P["n_values"]}} for a in bs}
    manifest={"schema":"pr15i-d3c-manifest-v1","campaign":campaign,"kind":kind,"protocol_sha256":RUN.PROTOCOL_SHA256,
        "source_base_sha":BASE,"source_experiment_sha":EXP if kind!="control" else None,"prefilter_profile":P["prefilter_profile"],
        "arms":arms,"build_events":list(bs.values()),"host_fingerprint":hp["host_fingerprint"],
        "host_attestation_sha256":sf(os.path.join(d,"raw","host-attestation.json")),
        "host_readiness_sha256":sf(os.path.join(d,"raw","host-readiness.json")),
        "build_provenance_sha256":sf(os.path.join(d,"raw","build-provenance.json")),
        "slots":len(slots),"lanes_per_slot":len(ls)}
    bv=RUN.block_values(slots,ls,P["blocks"])
    summary=RUN.summary_control(P,slots,ls,P["blocks"]) if kind=="control" else RUN.summary_campaign(P,slots,ls,P["blocks"],campaign,True)
    wj(os.path.join(d,"authorization.json"),{"schema":"pr15i-d3c-authorization-v1","campaign":campaign,"kind":kind,
        "protocol_sha256":RUN.PROTOCOL_SHA256,"idle_confirmed":True,"rehearsal_only":True})
    wj(os.path.join(d,"manifest.json"),manifest)
    wj(os.path.join(d,"sanitized","summary.json"),summary)
    files={r:sf(os.path.join(d,r)) for r in RUN.seal_paths(d)}
    wj(os.path.join(d,"raw","seal.json"),{"schema":"pr15i-d3c-seal-v1","kind":kind,"files":files})
    return d
def verify(d):
    r=subprocess.run([sys.executable,os.path.join(TOOLING_DIR,"verify.py"),"--campaign-dir",d],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    return r.returncode,json.loads(r.stdout) if r.stdout else {"verification":"FAIL"}
def fix_paths(d):
    prov=os.path.join(d,"raw/build-provenance.json"); p=json.load(open(prov))
    p["canonical_source_path"]=os.path.join(d,"compile-source")
    for ev in p["events"]: ev["canonical_source"]=p["canonical_source_path"]
    open(prov,"w").write(json.dumps(p))
    m=os.path.join(d,"manifest.json"); man=json.load(open(m)); man["build_provenance_sha256"]=sf(prov); open(m,"w").write(json.dumps(man))
    reseal(d)

def reseal(d):
    seal=json.load(open(os.path.join(d,"raw/seal.json"))); files={r:sf(os.path.join(d,r)) for r in seal["files"]}
    open(os.path.join(d,"raw/seal.json"),"w").write(json.dumps({"schema":"pr15i-d3c-seal-v1","kind":seal["kind"],"files":files}))

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--out",required=True); ap.add_argument("--dry-proof"); a=ap.parse_args(argv)
    root=os.path.realpath(a.out); base=os.path.dirname(root)
    dp_path=a.dry_proof or os.path.join(TOOLING_ROOT,RUN.TARGET_REL,"dry-proof","dry-proof.json")
    if not os.path.isfile(dp_path): fail("REHEARSAL","run dry-proof first")
    dp=json.load(open(dp_path))
    os.makedirs(root,exist_ok=False)
    cases=[]
    for kind,camp in (("control",P["control_name"]),("four_arm",P["campaign_names"][0]),("four_arm",P["campaign_names"][1])):
        d=build_fixture(root,kind,camp,dp); c,r=verify(d); cases.append({"case":camp,"exit":c,"status":r.get("measurement_status")})
        if c!=0 or r.get("verification")!="PASS" or r.get("measurement_status")!="SYNTHETIC_REHEARSAL_ONLY": fail("REHEARSAL",f"{camp}: {c} {r}")
    # negatives on copies
    neg=[]
    src=os.path.join(root,P["control_name"])
    def mutate(name,fn,expect):
        d=os.path.join(root,"neg-"+name); shutil.copytree(src,d); fix_paths(d); fn(d); c,r=verify(d); code=(r.get("reasons") or [{}])[0].get("code")
        neg.append({"case":name,"expected":expect,"actual":code,"exit":c,"matched":c!=0 and code==expect})
        if not neg[-1]["matched"]: fail("REHEARSAL",f"{name}: {c} {r}")
    def tamper_slot(d):
        p=os.path.join(d,"raw/slots/slot-01.json"); s=json.load(open(p)); s["lanes"][0]["samples_ns"][0]=0; open(p,"w").write(json.dumps(s))
    mutate("tampered-slot",tamper_slot,"V_SEAL")
    def extra(d): open(os.path.join(d,"intruder.json"),"w").write("{}")
    mutate("extra-file",extra,"V_INVENTORY")
    def marker(d):
        p=os.path.join(d,"raw/slots/slot-01.json"); s=json.load(open(p))
        for l in s["lanes"]: l["mode_marker"]="PR15I_D3C_MODE=v1:linear:none"
        open(p,"w").write(json.dumps(s)); reseal(d)
    mutate("wrong-marker",marker,"V_MODE")
    def oracle(d):
        p=os.path.join(d,"raw/slots/slot-01.json"); s=json.load(open(p)); s["lanes"][0]["total_hits"]+=1; open(p,"w").write(json.dumps(s)); reseal(d)
    mutate("oracle",oracle,"V_ORACLE")
    def summary(d):
        p=os.path.join(d,"sanitized/summary.json"); s=json.load(open(p)); s["a_a"]["lanes"][next(iter(s["a_a"]["lanes"]))]["median_ratio"]=0.1; open(p,"w").write(json.dumps(s)); reseal(d)
    mutate("summary",summary,"V_SUMMARY")
    d=os.path.join(root,"neg-source-sha"); shutil.copytree(os.path.join(root,P["campaign_names"][0]),d); fix_paths(d)
    p=os.path.join(d,"manifest.json"); m=json.load(open(p)); m["source_experiment_sha"]="0"*40; open(p,"w").write(json.dumps(m)); reseal(d)
    c,r=verify(d); code=(r.get("reasons") or [{}])[0].get("code")
    neg.append({"case":"source-sha","expected":"V_SOURCE","actual":code,"exit":c,"matched":c!=0 and code=="V_SOURCE"})
    if not neg[-1]["matched"]: fail("REHEARSAL",f"source-sha: {c} {r}")
    def host(d):
        p=os.path.join(d,"raw/host-attestation.json"); h=json.load(open(p)); h["host_fingerprint"]="other"; open(p,"w").write(json.dumps(h))
        m=os.path.join(d,"manifest.json"); man=json.load(open(m)); man["host_attestation_sha256"]=sf(p); man["host_fingerprint"]="other"; open(m,"w").write(json.dumps(man)); reseal(d)
    mutate("host-identity",host,"V_READINESS")
    def binary(d):
        p=os.path.join(d,"raw/build-provenance.json"); b=json.load(open(p)); b["events"][0]["binary_sha256"]="f"*64; open(p,"w").write(json.dumps(b))
        m=os.path.join(d,"manifest.json"); man=json.load(open(m)); man["build_provenance_sha256"]=sf(p); open(m,"w").write(json.dumps(man)); reseal(d)
    mutate("binary-provenance",binary,"V_BINARY")
    def ready_state(d):
        p=os.path.join(d,"raw/host-readiness.json"); r=json.load(open(p)); r["readiness_status"]="HOST_NOT_READY"; open(p,"w").write(json.dumps(r))
        m=os.path.join(d,"manifest.json"); man=json.load(open(m)); man["host_readiness_sha256"]=sf(p); open(m,"w").write(json.dumps(man)); reseal(d)
    mutate("readiness",ready_state,"V_READINESS")
    def affinity(d):
        p=os.path.join(d,"raw/slots/slot-01.json"); x=json.load(open(p)); x["lanes"][0]["affinity_before"]=[9]; open(p,"w").write(json.dumps(x)); reseal(d)
    mutate("affinity",affinity,"V_AFFINITY")
    def sample_count(d):
        p=os.path.join(d,"raw/slots/slot-01.json"); x=json.load(open(p)); x["lanes"][0]["samples_ns"].pop(); open(p,"w").write(json.dumps(x)); reseal(d)
    mutate("sample-count",sample_count,"V_SAMPLE")
    def sample_median(d):
        p=os.path.join(d,"raw/slots/slot-01.json"); x=json.load(open(p)); x["lanes"][0]["summary_ns"]["median"]+=1; open(p,"w").write(json.dumps(x)); reseal(d)
    mutate("sample-median",sample_median,"V_SAMPLE")
    def lane(d):
        p=os.path.join(d,"raw/slots/slot-01.json"); x=json.load(open(p)); x["lanes"].pop(); open(p,"w").write(json.dumps(x)); reseal(d)
    mutate("lane-count",lane,"V_SLOT")
    def index(d):
        p=os.path.join(d,"manifest.json"); m=json.load(open(p)); m["arms"]["A"]["indexes"]["10000"]["digest"]="0"*64; open(p,"w").write(json.dumps(m)); reseal(d)
    mutate("index-digest",index,"V_INDEX")
    def protocol(d):
        p=os.path.join(d,"manifest.json"); m=json.load(open(p)); m["protocol_sha256"]="0"*64; open(p,"w").write(json.dumps(m)); reseal(d)
    mutate("protocol-sha",protocol,"V_PROTOCOL")
    def campaign(d):
        p=os.path.join(d,"manifest.json"); m=json.load(open(p)); m["campaign"]="d3c-strategies-01"; open(p,"w").write(json.dumps(m)); reseal(d)
    mutate("campaign-name",campaign,"V_CAMPAIGN")
    pub=os.path.join(root,"publish-refusal")
    pr=subprocess.run([sys.executable,os.path.join(TOOLING_DIR,"run.py"),"publish",
        "--campaign-dir",os.path.join(root,P["control_name"]),"--evidence-root",pub],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    guard_ok=pr.returncode!=0 and "D3C_REHEARSAL_PUBLISH_FORBIDDEN" in (pr.stdout+pr.stderr)
    if not guard_ok: fail("REHEARSAL",f"publish guard did not refuse: {pr.returncode} {pr.stdout} {pr.stderr}")
    rep={"schema":"pr15i-d3c-rehearsal-v1","status":"SYNTHETIC_REHEARSAL_ONLY","rehearsal_only":True,"official_measurement":False,
         "cases":cases,"negatives":neg,"publish_guard":"PASS","publish_guard_evidence":{"exit":pr.returncode,
         "detail":"D3C_REHEARSAL_PUBLISH_FORBIDDEN"},"performance_claim":"NONE"}
    wj(os.path.join(root,"replay-report.json"),rep)
    print(json.dumps({"status":"REHEARSAL_PASS","cases":len(cases),"negatives":len(neg)},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())

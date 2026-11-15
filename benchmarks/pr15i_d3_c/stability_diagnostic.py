#!/usr/bin/env python3
"""One bounded NONOFFICIAL 13-lane real A/A stability diagnostic."""
from __future__ import annotations
import argparse, importlib.util, json, os, shutil, sys, time

HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
def load(name,file):
    s=importlib.util.spec_from_file_location(name,os.path.join(HERE,file)); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
RUN=load("diag_run","run.py"); HOST=load("diag_host","host_topology.py")

LANE_IDS=[
 "pr15d_v1/10000/absent/k1","pr15d_v1/10000/absent/k100",
 "pr15d_v1/10000/rare/k100","pr15d_v1/10000/rare/k1024",
 "pr15d_v1/10000/medium/k1","pr15d_v1/10000/medium/k256",
 "pr15d_v1/10000/medium/k512","pr15d_v1/10000/medium/k1024",
 "pr15d_v1/100000/absent/k128","pr15d_v1/100000/medium/k256",
 "pr15d_v1/100000/medium/k1024","pr15d_v1/100000/common/k256",
 "pr15d_v1/100000/common/k1024"]

def subset(protocol):
    all_lanes={l["id"]:l for l in RUN.lanes(protocol)}
    if any(LANE_IDS.count(x)!=1 for x in LANE_IDS) or len(LANE_IDS)!=13: raise SystemExit("HS-03: lane list")
    try: return [all_lanes[x] for x in LANE_IDS]
    except KeyError as e: raise SystemExit(f"HS-03: unknown lane {e}")

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--out",required=True); ap.add_argument("--idle-confirmed",action="store_true")
    a=ap.parse_args(argv)
    if not a.idle_confirmed: raise SystemExit("diagnostic requires --idle-confirmed")
    out=os.path.realpath(a.out)
    root=os.path.realpath(os.path.join(ROOT,RUN.TARGET_REL,"stability-diagnostics"))
    if os.path.commonpath([out,root])!=root or out==root: raise SystemExit("HS-13: output path")
    if os.path.isdir(out):
        extra=set(os.listdir(out))-{"host-before.json"}
        if extra: raise SystemExit(f"HS-13: diagnostic path already populated: {sorted(extra)}")
    protocol,psha=RUN.load_protocol()
    lanes=subset(protocol)
    os.makedirs(out,exist_ok=True)
    if not os.path.isfile(os.path.join(out,"host-before.json")):
        json.dump(HOST.audit(),open(os.path.join(out,"host-before.json"),"w"),sort_keys=True,indent=2)
    before=json.load(open(os.path.join(out,"host-before.json")))
    pair=before["selected_pair"]; adapter_cpu=pair["adapter_cpu"]; controller_cpu=pair["controller_cpu"]
    if not pair.get("distinct_cores") or pair["adapter"]["package_id"]!=pair["controller"]["package_id"]:
        raise SystemExit("HS-02: invalid pair")
    corpus=RUN.prepare_corpus(protocol,os.path.join(out,"corpus"))
    canonical=RUN.worktree(out,RUN.BASE_SHA)
    A=RUN.build(canonical,os.path.join(out,"build","A"),False)
    B=RUN.build(canonical,os.path.join(out,"build","B"),False)
    if A["sha256"]!=B["sha256"]: raise SystemExit("HS-03: A/B binary mismatch")
    os.makedirs(os.path.join(out,"indexes"),exist_ok=True)
    h=RUN.harness(); om=RUN.oracle()
    idx={}
    for n in sorted({l["n"] for l in lanes}):
        idx[n]=RUN.build_index(h,A["binary"],os.path.join(corpus,om.corpus_filename(n)),os.path.join(out,"indexes",f"n{n}"),n)
    RUN.pin(controller_cpu)
    host=RUN.host_record(protocol,adapter_cpu,controller_cpu,out,canonical); host["campaign"]="d3c-stability-diag-01"
    json.dump(host,open(os.path.join(out,"raw-host-attestation.json"),"w"),sort_keys=True,indent=2)
    ready=RUN.readiness(protocol,adapter_cpu,controller_cpu,host["host_fingerprint"]); ready["campaign"]="d3c-stability-diag-01"
    json.dump(ready,open(os.path.join(out,"raw-host-readiness.json"),"w"),sort_keys=True,indent=2)
    if ready["readiness_status"]!="READY": raise SystemExit(f"HS-04: readiness {ready['failure_codes']}")
    exp={n:RUN.expected_for(protocol,n) for n in idx}
    plan=RUN.control_schedule(); slots=[]
    os.makedirs(os.path.join(out,"raw","slots"),exist_ok=True); os.makedirs(os.path.join(out,"raw","contention"),exist_ok=True)
    for entry in plan:
        arm=entry["arm"]; binary=A["binary"] if arm=="A" else B["binary"]
        if RUN.allowed(os.getpid())!=[controller_cpu]: raise SystemExit("HS-02: controller affinity")
        bf=RUN.probe(h,os.path.join(out,"raw","contention",f"slot-{entry['slot']:02d}-before.json"))
        recs=[]
        for lane in lanes:
            rec=RUN.measure_lane(protocol,arm,binary,idx[lane["n"]]["dir"],adapter_cpu,lane,exp[lane["n"]][lane["id"]])
            recs.append(rec)
        af=RUN.probe(h,os.path.join(out,"raw","contention",f"slot-{entry['slot']:02d}-after.json"))
        if RUN.allowed(os.getpid())!=[controller_cpu]: raise SystemExit("HS-02: controller affinity after")
        slot={"schema":"pr15i-d3c-slot-v1","slot":entry["slot"],"block":entry["block"],"position":entry["position"],"arm":arm,
              "source_sha":RUN.BASE_SHA,"binary_sha256":A["sha256"],
              "index_digests":{str(n):idx[n]["layout"]["digest"] for n in idx},
              "controller_affinity_before":[controller_cpu],"controller_affinity_after":[controller_cpu],
              "contention_before":bf,"contention_after":af,"lanes":recs}
        json.dump(slot,open(os.path.join(out,"raw","slots",f"slot-{entry['slot']:02d}.json"),"w"),sort_keys=True)
        slots.append(slot)
    summary=RUN.summary_control(protocol,slots,lanes,4)
    os.sched_setaffinity(0,set(before["allowed_cpus"]))
    after=HOST.audit(); json.dump(after,open(os.path.join(out,"host-after.json"),"w"),sort_keys=True,indent=2)
    samples=sum(len(l["samples_ns"]) for s in slots for l in s["lanes"])
    stable=(summary["status"]=="CONTROL_QUALIFIED" and summary["drift"]["status"]=="PASS"
            and samples==4160 and all(all(isinstance(x,int) and not isinstance(x,bool) and x>0 for x in l["samples_ns"]) for s in slots for l in s["lanes"]))
    rec={"schema":"pr15i-d3c-stability-diagnostic-v1","diagnostic_id":"d3c-stability-diag-01",
         "status":"DIAGNOSTIC_STABLE" if stable else "DIAGNOSTIC_UNSTABLE","official":False,
         "protocol_sha256":psha,"source_base_sha":RUN.BASE_SHA,"binary_sha256":A["sha256"],
         "lanes":LANE_IDS,"slots":len(slots),"samples":samples,
         "selected_pair":pair,"host_before":before,"host_after":after,
         "would_original_subset_AA_qualify":summary["status"]=="CONTROL_QUALIFIED",
         "summary":summary}
    json.dump(rec,open(os.path.join(out,"diagnostic.json"),"w"),sort_keys=True,indent=2)
    print(json.dumps({"status":rec["status"],"samples":samples,"would_qualify":rec["would_original_subset_AA_qualify"]},sort_keys=True))
    return 0 if stable else 4
if __name__=="__main__": raise SystemExit(main())

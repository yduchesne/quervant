#!/usr/bin/env python3
"""PR 15I-D3-C four-arm Top-K strategy evaluation controller (experiment only)."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, statistics, select, shutil, subprocess, sys, tempfile, time
TOOLING_ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLING_DIR=os.path.join(TOOLING_ROOT,"benchmarks/pr15i_d3_c")
PROTOCOL_SHA256="1623cd8081d67a911776105c9a4bf1c9b8506903a737a01b7bccf4e3e1fd3715"
BASE_SHA="39dbd9f571a58bea8cc03d5a406533298e809bfe"
EXPERIMENT_SHA="3ad6c5184fbe9c011abb731415a007e3f19d21de"
EVIDENCE_REL="benchmark-evidence/pr15i-d3-c-v3r2"
TARGET_REL="target/pr15i-d3-c"

def fail(code,msg): raise SystemExit(f"{code}: {msg}")
def cj(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def sh(v): return hashlib.sha256(v).hexdigest()
def sf(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda:f.read(1<<20),b""): h.update(c)
    return h.hexdigest()
def rj(p):
    with open(p,"rb") as f: return json.loads(f.read().decode(),object_pairs_hook=_nodup)
def _nodup(pairs):
    seen=set()
    for k,_ in pairs:
        if k in seen: fail("D3C_JSON",f"duplicate key {k}")
        seen.add(k)
    return dict(pairs)
def wj(p,v,exclusive=False):
    os.makedirs(os.path.dirname(p),exist_ok=True)
    flags=os.O_CREAT|os.O_WRONLY|(os.O_EXCL if exclusive else os.O_TRUNC)
    fd=os.open(p,flags,0o644)
    with os.fdopen(fd,"wb") as f:
        f.write(cj(v)+b"\n"); f.flush(); os.fsync(f.fileno())
def wt(p,t):
    os.makedirs(os.path.dirname(p),exist_ok=True)
    with open(p,"w",encoding="utf-8",newline="\n") as f: f.write(t)
def load_protocol():
    p=os.path.join(TOOLING_DIR,"protocol_v3r2.json"); raw=open(p,"rb").read()
    d=json.loads(raw.decode())
    if sh(raw)!=PROTOCOL_SHA256: fail("D3C_PROTOCOL","protocol digest differs from the frozen literal")
    return d,sh(raw)
def target_root(): return os.path.join(TOOLING_ROOT,TARGET_REL)
def validate_out(p,json_file=False):
    p=os.path.realpath(p)
    root=os.path.realpath(target_root())
    if os.path.commonpath([p,root])!=root or p==root: fail("D3C_PATH",f"output must be beneath {root}")
    if os.path.exists(p): fail("D3C_EXISTS",f"output exists: {p}")
    if json_file and not p.endswith(".json"): fail("D3C_PATH","--out must be a .json")
    return p
def validate_dir(p):
    p=os.path.realpath(p); root=os.path.realpath(target_root())
    if os.path.commonpath([p,root])!=root or p==root or not os.path.isdir(p): fail("D3C_PATH",f"not a campaign under {root}: {p}")
    return p
def git(root,*a):
    r=subprocess.run(["git","-C",root,*a],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode: fail("D3C_GIT",f"git {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout.strip()
def harness():
    import importlib.util
    spec=importlib.util.spec_from_file_location("pr15d_harness_d3c",os.path.join(TOOLING_ROOT,"benchmarks/pr15d/harness/run.py"))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def oracle():
    import importlib.util
    spec=importlib.util.spec_from_file_location("pr15d_oracle_d3c",os.path.join(TOOLING_ROOT,"benchmarks/pr15d/corpus/oracle.py"))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def generator():
    import importlib.util
    spec=importlib.util.spec_from_file_location("pr15d_generate_d3c",os.path.join(TOOLING_ROOT,"benchmarks/pr15d/corpus/generate.py"))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def lanes(protocol):
    out=[]
    for n in protocol["n_values"]:
        for cls in protocol["classes"]:
            field="group" if cls=="medium" else "key"
            term={"absent":"never","rare":"singleton","medium":"medium","common":"common"}[cls]
            for k in protocol["k_values"]:
                out.append({"id":f"pr15d_v1/{n}/{cls}/k{k}","n":n,"class":cls,"field":field,"term":term,"k":k})
    if len(out)!=72: fail("D3C_LANES",f"expected 72 lanes, got {len(out)}")
    return out

def expected_for(protocol,n):
    ids={"absent":[],"rare":["d00000000"],
         "medium":[f"d{i:08}" for i in range(0,n,8)],
         "common":[f"d{i:08}" for i in range(2,n,2)]}
    out={}
    for cls in protocol["classes"]:
        for k in protocol["k_values"]:
            out[f"pr15d_v1/{n}/{cls}/k{k}"]={"total_hits":len(ids[cls]),"doc_ids":ids[cls][:k]}
    exp={"absent":0,"rare":1,"medium":n//8,"common":n//2-1}
    for cls in protocol["classes"]:
        if len(ids[cls])!=exp[cls]: fail("D3C_ORACLE",f"n={n} {cls}: {len(ids[cls])}!={exp[cls]}")
    return out

def prepare_corpus(protocol,dir):
    os.makedirs(dir,exist_ok=False)
    summary=generator().generate(dir)
    if summary["manifest"]["sha256"]!=protocol["corpus_manifest_sha256"]: fail("D3C_CORPUS","manifest digest differs")
    oracle().load_and_verify(dir)
    return dir

def schedule(protocol,campaign):
    if campaign==protocol["campaign_names"][0]: rows=protocol["campaign_01_order"]
    elif campaign==protocol["campaign_names"][1]: rows=protocol["campaign_02_order"]
    else: fail("D3C_SCHEDULE","unknown campaign")
    per=len(rows[0]); plan=[]
    for b,row in enumerate(rows,start=1):
        for pos,arm in enumerate(row,start=1): plan.append({"slot":(b-1)*per+pos,"block":b,"position":pos,"arm":arm})
    if len(plan)!=protocol["blocks"]*per: fail("D3C_SCHEDULE","slot count")
    return plan
def control_schedule(protocol):
    rows=protocol["control_order"]; per=len(rows[0]); plan=[]
    for b,row in enumerate(rows,start=1):
        for pos,arm in enumerate(row,start=1): plan.append({"slot":(b-1)*per+pos,"block":b,"position":pos,"arm":arm})
    if len(plan)!=protocol["blocks"]*per: fail("D3C_SCHEDULE","control slot count")
    return plan

def worktree(campaign_dir,sha):
    path=os.path.join(campaign_dir,"compile-source")
    if os.path.lexists(path): fail("D3C_WORKTREE","compile-source exists")
    r=subprocess.run(["git","-C",TOOLING_ROOT,"worktree","add","--detach",path,sha],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    if r.returncode: fail("D3C_WORKTREE",r.stdout[-1500:])
    prove(path,sha)
    return path
def prove(path,sha):
    if os.path.realpath(path)!=path or os.path.islink(path) or not os.path.isdir(path): fail("D3C_SOURCE","bad canonical path")
    if git(path,"rev-parse","HEAD")!=sha: fail("D3C_SOURCE","canonical HEAD differs")
    if subprocess.run(["git","-C",path,"symbolic-ref","-q","HEAD"]).returncode==0: fail("D3C_SOURCE","canonical checkout not detached")
    if git(path,"status","--porcelain","--untracked-files=all"): fail("D3C_SOURCE","canonical checkout dirty")
def switch(path,old,new):
    prove(path,old)
    r=subprocess.run(["git","-C",path,"switch","--detach",new],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    if r.returncode: fail("D3C_WORKTREE",r.stdout[-1500:])
    prove(path,new)

def build(canonical,target,feature):
    if os.path.lexists(target): fail("D3C_BUILD","target dir exists")
    os.makedirs(target)
    argv=["cargo","build","--release","--locked","--manifest-path",os.path.join(canonical,"benchmarks/pr15d/adapters/quervant/Cargo.toml"),"--target-dir",target]
    if feature: argv += ["--features","quervant-core/pr15i-d3c-experiment"]
    env=dict(os.environ)
    for k in ("RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS","RUSTC","RUSTC_WRAPPER","CARGO_INCREMENTAL","SOURCE_DATE_EPOCH"):
        if k in env: fail("D3C_ENV",f"forbidden build env {k}")
    r=subprocess.run(argv,cwd=os.path.join(canonical,"benchmarks/pr15d/adapters/quervant"),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    if r.returncode: fail("D3C_BUILD",r.stdout[-2000:])
    b=os.path.join(target,"release","pr15d-quervant-adapter")
    if not os.path.isfile(b): fail("D3C_BUILD","missing adapter")
    return {"binary":b,"sha256":sf(b),"bytes":os.path.getsize(b),"argv":argv,"feature":feature,"source_sha":git(canonical,"rev-parse","HEAD")}

def index_layout(index_dir):
    files=[]
    for root,dirs,names in os.walk(index_dir):
        for name in sorted(names):
            p=os.path.join(root,name); rel=os.path.relpath(p,index_dir).replace(os.sep,"/")
            files.append({"path":rel,"size":os.path.getsize(p),"sha256":sf(p)})
    files.sort(key=lambda x:x["path"])
    return {"files":files,"bytes":sum(x["size"] for x in files),"digest":sh(cj(files))}

def build_index(h,binary,corpus_path,index_dir,n):
    if os.path.exists(index_dir): fail("D3C_INDEX","index exists")
    os.makedirs(index_dir)
    r=h.build_index("quervant",binary,corpus_path,index_dir,n)
    return {"n":n,"dir":index_dir,"adapter":r,"layout":index_layout(index_dir)}

def fs_roles(campaign_dir,canonical):
    h=harness(); roles={"repository":TOOLING_ROOT,"campaign_output":campaign_dir,"compile_source":canonical,
        "build_A":os.path.join(campaign_dir,"build","A"),"build_B":os.path.join(campaign_dir,"build","B"),
        "corpus":os.path.join(campaign_dir,"corpus"),"indexes":os.path.join(campaign_dir,"indexes")}
    out=[]
    for role,p in roles.items():
        rp=os.path.realpath(p)
        if not os.path.isdir(rp): fail("D3C_HOST",f"missing role {role}: {p}")
        ht=h.filesystem_type(rp)
        r=subprocess.run(["findmnt","--target",rp,"--noheadings","--output","FSTYPE"],stdout=subprocess.PIPE,text=True)
        ft=[x.strip() for x in r.stdout.splitlines() if x.strip()]
        if len(ft)!=1 or ft[0] not in ("ext4","xfs","btrfs") or ht!=ft[0]: fail("D3C_HOST",f"{role}: {ht}/{ft}")
        out.append({"role":role,"path":rp,"harness_fstype":ht,"findmnt_fstype":ft[0]})
    return out

def topology():
    import importlib.util
    spec=importlib.util.spec_from_file_location("d3c_topology",os.path.join(TOOLING_DIR,"host_topology.py"))
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def cpus():
    c=sorted(os.sched_getaffinity(0))
    try:
        pair=topology().select_pair(c)
    except Exception as e:
        fail("HS-02",str(e))
    return pair["adapter_cpu"],pair["controller_cpu"]
def pin(cpu):
    os.sched_setaffinity(0,{cpu})
    if sorted(os.sched_getaffinity(0))!=[cpu]: fail("D3C_AFFINITY","controller pin failed")
def allowed(pid):
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("Cpus_allowed_list:"):
                t=line.split(":")[1].strip(); out=[]
                for part in t.split(","):
                    if "-" in part:
                        a,b=part.split("-"); out+=list(range(int(a),int(b)+1))
                    else: out.append(int(part))
                return sorted(out)
    except OSError: return None
    return None

def read_ticks():
    ns=time.monotonic_ns(); cpusd={}
    for line in open("/proc/stat"):
        p=line.split()
        if len(p)>=9 and p[0].startswith("cpu") and p[0][3:].isdigit():
            i=int(p[0][3:]); cpusd[i]=tuple(int(x) for x in p[1:9])
    return ns,cpusd

def readiness(protocol,adapter_cpu,controller_cpu,host_fp):
    spec=protocol["host_readiness"]; codes=set(); obs=[]; metrics={"adapter":[],"controller":[]}; medians={}
    t0=time.monotonic_ns(); time.sleep(spec["settle_ms"]/1000.0); t1=time.monotonic_ns()
    if not (4500_000_000<=t1-t0<=7500_000_000): codes.add("SETTLE_DURATION")
    for i in range(7):
        if i: time.sleep(spec["interval_ms"]/1000.0)
        ns,c=read_ticks()
        try:
            obs.append({"monotonic_ns":ns,"cpus":{str(adapter_cpu):list(c[adapter_cpu]),str(controller_cpu):list(c[controller_cpu])}})
        except KeyError:
            codes.add("MISSING_CPU"); break
    names={"adapter":adapter_cpu,"controller":controller_cpu}
    for role,cpu in names.items():
        busy=[]
        for i in range(len(obs)-1):
            a=obs[i]["cpus"][str(cpu)]; b=obs[i+1]["cpus"][str(cpu)]
            d=[y-x for x,y in zip(a,b)]; e=(obs[i+1]["monotonic_ns"]-obs[i]["monotonic_ns"])/1e6
            if not (spec["minimum_actual_interval_ms"]<=e<=spec["maximum_actual_interval_ms"]): codes.add("INTERVAL_DURATION")
            if any(x<0 for x in d): codes.add("COUNTER_DECREASE"); continue
            tot=sum(d)
            if tot<=0: codes.add("ZERO_DELTA"); continue
            bm=(1000*(tot-d[3]))//tot; sm=(1000*d[7])//tot
            if bm>spec["max_busy_permille"]: codes.add("BUSY_EXCEEDED")
            if sm>spec["max_steal_permille"]: codes.add("STEAL_EXCEEDED")
            busy.append(bm); metrics[role].append({"interval":i+1,"actual_ms":e,"busy_permille":bm,"steal_permille":sm})
        if len(busy)==6:
            med=sorted(busy)[2]; medians[role]=med
            if med>spec["max_median_busy_permille"]: codes.add("MEDIAN_BUSY_EXCEEDED")
        else: codes.add("INCOMPLETE_OBSERVATIONS")
    rec={"schema":"pr15i-d3c-host-readiness-v1","protocol_sha256":PROTOCOL_SHA256,"campaign":"",
         "role_cpus":{"adapter":adapter_cpu,"controller":controller_cpu},"host_fingerprint":host_fp,
         "settle_monotonic_start_ns":t0,"settle_monotonic_end_ns":t1,"observations":obs,
         "interval_metrics":metrics,"lower_median_busy_permille":medians,
         "readiness_status":"HOST_NOT_READY" if codes else "READY","failure_codes":sorted(codes),
         "optional_cpu_frequency_khz":{"adapter":None,"controller":None},"queries_executed":0}
    return rec

class Adapter:
    def __init__(self,binary,index_dir,env,cpu):
        e=dict(os.environ); e.update(env)
        self.p=subprocess.Popen(["taskset","-c",str(cpu),binary,"--index-dir",index_dir],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=e)
        deadline=time.monotonic()+5
        while allowed(self.p.pid)!=[cpu]:
            if self.p.poll() is not None or time.monotonic()>deadline: self.close(); fail("D3C_AFFINITY","adapter affinity")
            time.sleep(0.001)
        self.marker=None
    def request(self,payload,read_marker=False):
        self.p.stdin.write(json.dumps(payload,sort_keys=True,separators=(",",":"))+"\n"); self.p.stdin.flush()
        line=self.p.stdout.readline()
        if not line: self.close(); fail("D3C_ADAPTER","adapter closed")
        r=json.loads(line)
        if read_marker:
            rd,_,_=select.select([self.p.stderr],[],[],5)
            if not rd: self.close(); fail("D3C_MODE","missing mode marker")
            self.marker=self.p.stderr.readline().strip()
        return r
    def extra_stderr(self):
        rd,_,_=select.select([self.p.stderr],[],[],0)
        return self.p.stderr.readline().strip() if rd else ""
    def close(self):
        try: self.p.stdin.close()
        except Exception: pass
        self.p.terminate()
        try: self.p.wait(timeout=5)
        except Exception: self.p.kill()

def mode_env(protocol,arm):
    m=protocol["arm_modes"].get(arm,"BASE")
    if m=="BASE": return {}
    env={"QUERVANT_PR15I_D3C_STRATEGY":m}
    if m=="prefilter": env["QUERVANT_PR15I_D3C_PREFILTER_PROFILE"]=protocol["prefilter_profile"]
    return env
def expected_marker(protocol,arm):
    m=protocol["arm_modes"].get(arm,"BASE")
    if m=="BASE": return None
    return f"PR15I_D3C_MODE=v1:{m}:{protocol['prefilter_profile'] if m=='prefilter' else 'none'}"

def measure_lane(protocol,arm,binary,index_dir,adapter_cpu,lane,expected):
    env=mode_env(protocol,arm); exp_marker=expected_marker(protocol,arm)
    a=Adapter(binary,index_dir,env,adapter_cpu)
    pid=a.p.pid
    affinity_before=allowed(pid)
    if affinity_before!=[adapter_cpu]: fail("D3C_AFFINITY",f"pre {affinity_before}")
    try:
        first=a.request({"request_id":"w0","op":"query","field":lane["field"],"term":lane["term"],"k":lane["k"],"mode":"warm"},read_marker=(exp_marker is not None))
        if exp_marker is None:
            if a.marker: fail("D3C_MODE",f"BASE emitted marker {a.marker}")
        elif a.marker!=exp_marker: fail("D3C_MODE",f"marker {a.marker!r} != {exp_marker!r}")
        for w in range(1,protocol["warmups_per_lane_slot"]):
            r=a.request({"request_id":f"w{w}","op":"query","field":lane["field"],"term":lane["term"],"k":lane["k"],"mode":"warm"})
            check(r,lane,expected)
        samples=[]
        for s in range(protocol["samples_per_lane_slot"]):
            r=a.request({"request_id":f"s{s}","op":"query","field":lane["field"],"term":lane["term"],"k":lane["k"],"mode":"warm"})
            check(r,lane,expected); samples.append(r["engine_ns"])
        if a.extra_stderr(): fail("D3C_ADAPTER","unexpected stderr")
        affinity_after=allowed(pid)
        if affinity_after!=[adapter_cpu]: fail("D3C_AFFINITY",f"post {affinity_after}")
    finally:
        a.close()
    return {"id":lane["id"],"n":lane["n"],"class":lane["class"],"field":lane["field"],"term":lane["term"],"k":lane["k"],
            "samples_ns":samples,"summary_ns":{"count":20,"median":sorted(samples)[9]},
            "total_hits":expected["total_hits"],"doc_ids":expected["doc_ids"],"expected_total_hits":expected["total_hits"],
            "expected_doc_ids":expected["doc_ids"],"oracle_ok":True,"mode_marker":a.marker,
            "adapter_pid":pid,"affinity_before":affinity_before,"affinity_after":affinity_after}

def check(r,lane,expected):
    if r.get("total_hits")!=expected["total_hits"] or r.get("doc_ids")!=expected["doc_ids"]:
        fail("D3C_ORACLE",f"{lane['id']}: oracle mismatch")
    e=r.get("engine_ns")
    if isinstance(e,bool) or not isinstance(e,int) or e<=0: fail("D3C_SAMPLE",f"{lane['id']}: invalid engine_ns")

def probe(harness_mod,path):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    r=harness_mod.check_contention(path)
    if r.get("state") not in ("clear","busy") or not isinstance(r.get("reason_codes"),list): fail("D3C_CONTENTION",json.dumps(r,sort_keys=True))
    return r

def block_values(slots,lanes_f,blocks):
    grouped={}
    for s in slots:
        grouped.setdefault(s["arm"],{}).setdefault(s["block"],{}).setdefault(s["position"],{})
        for l in s["lanes"]: grouped[s["arm"]][s["block"]][s["position"]][l["id"]]=l["summary_ns"]["median"]
    out={}
    for arm,byb in grouped.items():
        out[arm]={}
        for b in range(1,blocks+1):
            out[arm][b]={}
            pos=sorted(byb.get(b,{}))
            if len(pos)!=2: fail("D3C_SLOT",f"arm {arm} block {b}: expected 2 slots")
            for lane in lanes_f:
                v=[byb[b][p][lane["id"]] for p in pos]
                out[arm][b][lane["id"]]=(v[0]+v[1])//2
    return out

def median4(v): return sorted(v)[1]
def ratio(a,b): return a/b

def drift_cap(lane):
    return 1.25 if lane["n"]==100000 and lane["class"] in ("medium","common") else 1.50

def drift_report(protocol,slots,lanes_f,blocks,arms):
    violations=[]
    by={}
    for s in slots:
        by.setdefault(s["arm"],{}).setdefault(s["block"],{})[s["position"]]={l["id"]:l["summary_ns"]["median"] for l in s["lanes"]}
    for arm in arms:
        for lane in lanes_f:
            cap=drift_cap(lane); block_values=[]
            for b in range(1,blocks+1):
                pos=sorted(by.get(arm,{}).get(b,{}))
                if len(pos)!=2: violations.append({"gate":"BLOCK_SHAPE","arm":arm,"block":b}); continue
                vals=[by[arm][b][p][lane["id"]] for p in pos]
                r=max(vals)/min(vals)
                if r>cap: violations.append({"gate":"WITHIN_BLOCK_DRIFT","arm":arm,"lane":lane["id"],"block":b,"ratio":r,"cap":cap})
                block_values.append((vals[0]+vals[1])//2)
            if len(block_values)==blocks:
                r=max(block_values)/min(block_values)
                if r>cap: violations.append({"gate":"BLOCK_DRIFT","arm":arm,"lane":lane["id"],"ratio":r,"cap":cap})
    return {"status":"PASS" if not violations else "FAIL","violations":violations}

def summary_control(protocol,slots,lanes_f,blocks):
    bv=block_values(slots,lanes_f,blocks); report={}; ok=True
    drift=drift_report(protocol,slots,lanes_f,blocks,["A","B"])
    if drift["status"]!="PASS": ok=False
    for lane in lanes_f:
        rs=[ratio(bv["B"][b][lane["id"]],bv["A"][b][lane["id"]]) for b in range(1,blocks+1)]
        med=statistics.median(rs); exempt=lane["n"]==10000 and lane["class"] in ("absent","rare")
        soft=[r for r in rs if not (0.80<=r<=1.25)]
        lane_ok=0.85<=med<=1.15
        if exempt:
            lane_ok=lane_ok and len(soft)<=1 and all(0.67<=r<=1.5 for r in rs)
        else:
            lane_ok=lane_ok and not soft
        ok=ok and lane_ok
        report[lane["id"]]={"block_ratios":rs,"median_ratio":med,"passes":lane_ok}
    return {"schema":"pr15i-d3c-summary-v1","campaign":protocol["control_name"],"kind":"control",
            "protocol_sha256":PROTOCOL_SHA256,"source_base_sha":BASE_SHA,
            "drift":drift,"a_a":{"passes":ok,"lanes":report},"status":"ACQUIRED_VERIFIED",
            "timing_observation":"nonfatal"}

def summary_campaign(protocol,slots,lanes_f,blocks,campaign,structural_ok=True):
    bv=block_values(slots,lanes_f,blocks); arms=["A","L","P","H"]; lanes_out=[]
    drift=drift_report(protocol,slots,lanes_f,blocks,arms)
    status="ACQUIRED_VERIFIED" if structural_ok else "ACQUISITION_INCOMPLETE"
    for lane in lanes_f:
        a=[bv["A"][b][lane["id"]] for b in range(1,blocks+1)]
        entry={"id":lane["id"],"n":lane["n"],"class":lane["class"],"k":lane["k"],"A_blocks_ns":a}
        for arm in arms[1:]:
            v=[bv[arm][b][lane["id"]] for b in range(1,blocks+1)]
            entry[f"{arm}_blocks_ns"]=v
            entry[f"{arm}_over_A_block"]=[ratio(x,y) for x,y in zip(v,a)]
            entry[f"{arm}_over_A_median"]=median4(entry[f"{arm}_over_A_block"])
            entry[f"{arm}_minus_A_median_ns"]=median4([y-x for x,y in zip(a,v)])
        for x,y in (("P","L"),("H","L"),("H","P")):
            entry[f"{x}_over_{y}_median"]=median4([ratio(v,w) for v,w in zip(entry[f"{x}_blocks_ns"],entry[f"{y}_blocks_ns"])])
        lanes_out.append(entry)
    return {"schema":"pr15i-d3c-summary-v1","campaign":campaign,"kind":"four_arm",
            "protocol_sha256":PROTOCOL_SHA256,"source_base_sha":BASE_SHA,
            "source_experiment_sha":EXPERIMENT_SHA,"prefilter_profile":protocol["prefilter_profile"],
            "lanes":lanes_out,"drift":drift,
            "arms":{"A":"BASE","L":"linear","P":"prefilter","H":"exact_set"},"status":status}

def host_record(protocol,adapter_cpu,controller_cpu,campaign_dir,canonical):
    rec={"schema":"pr15i-d3c-host-attestation-v1","protocol_sha256":PROTOCOL_SHA256,"campaign":os.path.basename(campaign_dir),
         "kernel":platform.uname().release,"machine":platform.uname().machine,"cpu_model":platform.processor() or platform.uname().machine,
         "cpu_count":os.cpu_count(),"allowed_cpus_before_pin":sorted(os.sched_getaffinity(0)),
         "controller_cpu":controller_cpu,"adapter_cpu":adapter_cpu,
         "controller_affinity_after_pin":[controller_cpu],"filesystems":fs_roles(campaign_dir,canonical),
         "toolchains":{"rustc":subprocess.run(["rustc","-V"],stdout=subprocess.PIPE,text=True).stdout.strip(),
                       "cargo":subprocess.run(["cargo","-V"],stdout=subprocess.PIPE,text=True).stdout.strip(),
                       "python3":sys.version.split()[0]},
         "recorded_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
    t=topology()
    rec["cpu_topology"]={"adapter":t.read_cpu("/sys/devices/system/cpu",adapter_cpu),
        "controller":t.read_cpu("/sys/devices/system/cpu",controller_cpu)}
    rec["host_fingerprint"]=sh(cj({"kernel":rec["kernel"],"machine":rec["machine"],"cpu_model":rec["cpu_model"],"cpu_count":rec["cpu_count"],
        "allowed_cpus":rec["allowed_cpus_before_pin"],"controller_cpu":controller_cpu,"adapter_cpu":adapter_cpu,
        "filesystems":{i["role"]:i["findmnt_fstype"] for i in rec["filesystems"]}}))
    return rec

def seal_paths(campaign_dir):
    out=[]
    for root,dirs,names in os.walk(campaign_dir):
        rel=os.path.relpath(root,campaign_dir).replace(os.sep,"/")
        if rel==".": rel=""
        if rel=="" : dirs[:]=[d for d in dirs if d not in ("build","indexes","corpus","compile-source")]
        for n in sorted(names):
            r=f"{rel}/{n}".lstrip("/")
            if r=="raw/seal.json": continue
            out.append(r)
    return sorted(out)

def write_evidence(campaign_dir,manifest,summary,authorization):
    wj(os.path.join(campaign_dir,"authorization.json"),authorization,exclusive=True)
    wj(os.path.join(campaign_dir,"manifest.json"),manifest,exclusive=True)
    wj(os.path.join(campaign_dir,"sanitized/summary.json"),summary,exclusive=True)
    files={r:sf(os.path.join(campaign_dir,r)) for r in seal_paths(campaign_dir)}
    wj(os.path.join(campaign_dir,"raw/seal.json"),{"schema":"pr15i-d3c-seal-v1","kind":manifest["kind"],"files":files},exclusive=True)

def run_measurement(kind,campaign,out):
    protocol,psha=load_protocol()
    adapter_cpu,controller_cpu=cpus()
    os.makedirs(out,exist_ok=False)
    os.makedirs(os.path.join(out,"indexes"))
    corpus=prepare_corpus(protocol,os.path.join(out,"corpus"))
    canonical=worktree(out,BASE_SHA)
    a=build(canonical,os.path.join(out,"build","A"),False)
    if kind=="control":
        switch(canonical,BASE_SHA,BASE_SHA) if False else None
        b=build(canonical,os.path.join(out,"build","B"),False)
    else:
        switch(canonical,BASE_SHA,EXPERIMENT_SHA)
        b=build(canonical,os.path.join(out,"build","B"),True)
    arms={"A":a,"B":b} if kind=="control" else {"A":a,"L":b,"P":b,"H":b}
    if kind=="control":
        if a["sha256"]!=b["sha256"] or a["bytes"]!=b["bytes"]: fail("D3C_AA","control binaries differ")
    else:
        if a["sha256"]==b["sha256"]: fail("D3C_AB","experimental binary equals BASE")
    h=harness(); oracle_mod=oracle()
    exp={n:expected_for(protocol,n) for n in protocol["n_values"]}
    corpus_paths={n:os.path.join(corpus,oracle_mod.corpus_filename(n)) for n in protocol["n_values"]}
    indices={}
    for arm,binfo in arms.items():
        indices[arm]={}
        for n in protocol["n_values"]:
            d=os.path.join(out,"indexes",f"{arm}-n{n}")
            indices[arm][n]=build_index(h,binfo["binary"],corpus_paths[n],d,n)
    layouts={n:indices["A"][n]["layout"]["digest"] for n in protocol["n_values"]}
    for arm in indices:
        for n in protocol["n_values"]:
            if indices[arm][n]["layout"]["digest"]!=layouts[n]: fail("D3C_INDEX","arm index digests differ")
            lay=indices[arm][n]["layout"]
            if n==100000 and (lay["bytes"]!=protocol["index_100k_committed_sentinel"]): fail("D3C_INDEX","100K committed sentinel")
    pin(controller_cpu)
    host=host_record(protocol,adapter_cpu,controller_cpu,out,canonical)
    host["campaign"]=campaign
    wj(os.path.join(out,"raw","host-attestation.json"),host,exclusive=True)
    ready=readiness(protocol,adapter_cpu,controller_cpu,host["host_fingerprint"]); ready["campaign"]=campaign
    wj(os.path.join(out,"raw","host-readiness.json"),ready,exclusive=True)
    if ready["readiness_status"]!="READY": fail("D3C_HOST_NOT_READY",json.dumps(ready["failure_codes"]))
    lanes_f=lanes(protocol)
    plan=control_schedule(protocol) if kind=="control" else schedule(protocol,campaign)
    slots=[]
    for entry in plan:
        arm=entry["arm"]; binfo=arms[arm]
        controller_before=allowed(os.getpid())
        if controller_before!=[controller_cpu]: fail("D3C_AFFINITY","controller before")
        before=probe(h,os.path.join(out,"raw","contention",f"slot-{entry['slot']:02d}-before.json"))
        recs=[]
        for lane in lanes_f:
            recs.append(measure_lane(protocol,arm,binfo["binary"],indices[arm][lane["n"]]["dir"],adapter_cpu,lane,exp[lane["n"]][lane["id"]]))
        after=probe(h,os.path.join(out,"raw","contention",f"slot-{entry['slot']:02d}-after.json"))
        controller_after=allowed(os.getpid())
        if controller_after!=[controller_cpu]: fail("D3C_AFFINITY","controller after")
        slot={"schema":"pr15i-d3c-slot-v1","slot":entry["slot"],"block":entry["block"],"position":entry["position"],"arm":arm,
              "source_sha":binfo["source_sha"],"binary_sha256":binfo["sha256"],
              "index_digests":{str(n):indices[arm][n]["layout"]["digest"] for n in protocol["n_values"]},
              "controller_affinity_before":controller_before,"controller_affinity_after":controller_after,
              "contention_before":before,"contention_after":after,"lanes":recs}
        wj(os.path.join(out,"raw","slots",f"slot-{entry['slot']:02d}.json"),slot,exclusive=True)
        slots.append(slot)
    a2=build_provenance(kind,campaign,canonical,a,b,arms,indices,protocol)
    wj(os.path.join(out,"raw","build-provenance.json"),a2,exclusive=True)
    structural_ok = (
        ready["readiness_status"] == "READY"
        and all(
            indices[arm][n]["layout"]["digest"] == indices["A"][n]["layout"]["digest"]
            for n in protocol["n_values"]
            for arm in arms
        )
    )
    if kind!="control": structural_ok = structural_ok and a["sha256"]!=b["sha256"]
    summary=summary_control(protocol,slots,lanes_f,protocol["blocks"]) if kind=="control" else summary_campaign(protocol,slots,lanes_f,protocol["blocks"],campaign,structural_ok)
    manifest={"schema":"pr15i-d3c-manifest-v1","campaign":campaign,"kind":kind,"protocol_sha256":psha,
              "source_base_sha":BASE_SHA,"source_experiment_sha":EXPERIMENT_SHA if kind!="control" else None,
              "prefilter_profile":protocol["prefilter_profile"],
              "arms":{arm:{"source_sha":arms[arm]["source_sha"],"binary_sha256":arms[arm]["sha256"],"binary_bytes":arms[arm]["bytes"],
                           "indexes":{str(n):indices[arm][n]["layout"] for n in protocol["n_values"]}} for arm in arms},
              "build_events":a2["events"],"host_fingerprint":host["host_fingerprint"],
              "host_attestation_sha256":sf(os.path.join(out,"raw","host-attestation.json")),
              "host_readiness_sha256":sf(os.path.join(out,"raw","host-readiness.json")),
              "build_provenance_sha256":sf(os.path.join(out,"raw","build-provenance.json")),
              "slots":len(slots),"lanes_per_slot":len(lanes_f)}
    auth={"schema":"pr15i-d3c-authorization-v1","campaign":campaign,"kind":kind,"protocol_sha256":psha,
          "idle_confirmed":True,"rehearsal_only":False,"recorded_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
    write_evidence(out,manifest,summary,auth)
    print(json.dumps({"status":summary["status"],"campaign":campaign,"slots":len(slots),"samples":len(slots)*len(lanes_f)*20},sort_keys=True))
    return 0 if summary["status"]=="ACQUIRED_VERIFIED" else 3

def build_provenance(kind,campaign,canonical,a,b,arms,indices,protocol):
    events=[]
    for arm,info in arms.items():
        events.append({"arm":arm,"source_sha":info["source_sha"],"binary_sha256":info["sha256"],"binary_bytes":info["bytes"],
                       "feature":info["feature"],"argv":info["argv"],"canonical_source":canonical,"binary":info["binary"]})
    return {"schema":"pr15i-d3c-build-provenance-v1","campaign":campaign,"kind":kind,
            "canonical_source_path":canonical,"source_base_sha":BASE_SHA,
            "source_experiment_sha":EXPERIMENT_SHA if kind!="control" else None,"events":events,
            "index_digests":{arm:{str(n):indices[arm][n]["layout"]["digest"] for n in protocol["n_values"]} for arm in arms}}

def archive_members(campaign_dir):
    out=[]
    for root,dirs,names in os.walk(campaign_dir):
        rel=os.path.relpath(root,campaign_dir).replace(os.sep,"/")
        if rel==".": rel=""
        if rel=="":
            dirs[:]=[d for d in dirs if d not in ("build","indexes","corpus","compile-source")]
        for n in sorted(names):
            r=f"{rel}/{n}".lstrip("/")
            if r in ("verification.json",): out.append(r)
            elif r in seal_members(campaign_dir): out.append(r)
    return sorted(set(out))
def seal_members(campaign_dir):
    return set(rj(os.path.join(campaign_dir,"raw","seal.json"))["files"]) | {"raw/seal.json","verification.json"}

FREEZE_RECEIPT_REL="target/pr15i-d3-c/v3r1-freeze/freeze-receipt.json"
def require_freeze(campaign):
    rp=os.path.join(TOOLING_ROOT,FREEZE_RECEIPT_REL)
    if os.path.islink(rp) or not os.path.isfile(rp): fail("HS-07","missing T6-R1 receipt")
    rec=rj(rp)
    if rec.get("schema")!="pr15i-d3c-freeze-v1" or rec.get("protocol_sha256")!=PROTOCOL_SHA256: fail("HS-07","freeze protocol")
    if campaign not in [rec.get("control_name")]+rec.get("campaign_names",[]): fail("HS-07","freeze campaign")
    t6=rec.get("t6_commit","")
    r=subprocess.run(["git","-C",TOOLING_ROOT,"merge-base","--is-ancestor",t6,"HEAD"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode: fail("HS-07","T6 not ancestor")
    mp=os.path.join(TOOLING_DIR,"tooling_manifest.json")
    if rec.get("tooling_manifest_sha256")!=sf(mp): fail("HS-07","manifest changed")
    for rel,dig in rec.get("protected_files",{}).items():
        if rel.startswith("/") or ".." in rel.split("/"): fail("HS-07","unsafe freeze path")
        r=subprocess.run(["git","-C",TOOLING_ROOT,"show",f"{t6}:{rel}"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if r.returncode or hashlib.sha256(r.stdout).hexdigest()!=dig: fail("HS-07",f"protected file differs: {rel}")
    if rec.get("control_name")!=load_protocol()[0]["control_name"]: fail("HS-07","freeze control name")
    return rec

def cmd_publish(args):
    protocol,_=load_protocol(); d=validate_dir(args.campaign_dir)
    require_freeze(rj(os.path.join(d,"manifest.json"))["campaign"])
    m=rj(os.path.join(d,"manifest.json"))
    if rj(os.path.join(d,"authorization.json")).get("rehearsal_only") or "rehearsal" in d.split(os.sep): fail("D3C_REHEARSAL_PUBLISH_FORBIDDEN","synthetic")
    ev=os.path.realpath(args.evidence_root); os.makedirs(ev,exist_ok=True)
    arc=os.path.join(ev,m["campaign"]+".tar.gz"); side=arc+".sha256"
    if os.path.exists(arc) or os.path.exists(side): fail("D3C_ARCHIVE_EXISTS",arc)
    r=subprocess.run([sys.executable,os.path.join(TOOLING_DIR,"verify.py"),"--campaign-dir",d],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode!=0: fail("D3C_VERIFY",r.stdout[-800:])
    rep=json.loads(r.stdout)
    if rep.get("verification")!="PASS": fail("D3C_VERIFY","verifier did not PASS")
    want="ACQUIRED_VERIFIED"
    if rep.get("measurement_status")!=want:
        fail("D3C_QUALIFICATION",f"status {rep.get('measurement_status')} != {want}")
    wj(os.path.join(d,"verification.json"),{"schema":"pr15i-d3c-verification-v1","campaign":m["campaign"],"verification":"PASS","measurement_status":rep["measurement_status"]})
    import tarfile
    tmp_arc=arc+".tmp"; tmp_side=side+".tmp"
    if os.path.exists(tmp_arc) or os.path.exists(tmp_side): fail("D3C_ARCHIVE_EXISTS",tmp_arc)
    try:
        members=[x for x in archive_members(d) if os.path.isfile(os.path.join(d,x))]
        with tarfile.open(tmp_arc,"w:gz") as t:
            for rel in members:
                info=t.gettarinfo(os.path.join(d,rel),arcname=rel); info.uid=info.gid=0; info.uname=info.gname=""
                with open(os.path.join(d,rel),"rb") as f: t.addfile(info,f)
        inv={rel:sf(os.path.join(d,rel)) for rel in members}
        wj(tmp_side,{"schema":"pr15i-d3c-archive-v1","campaign":m["campaign"],"archive_sha256":sf(tmp_arc),"member_count":len(inv),"members":inv})
        validate_archive(tmp_arc,tmp_side,m["campaign"],d)
        os.replace(tmp_arc,arc); os.replace(tmp_side,side)
    except BaseException:
        for p in (tmp_arc,tmp_side):
            try: os.remove(p)
            except OSError: pass
        raise
    print(json.dumps({"status":"PUBLISHED","archive_sha256":sf(arc),"members":len(inv)},sort_keys=True)); return 0

def cmd_readiness_only(args):
    protocol,psha=load_protocol(); rec=require_freeze(protocol["control_name"])
    pair=topology().select_pair(sorted(os.sched_getaffinity(0)))
    host={"kernel":platform.uname().release,"machine":platform.uname().machine,
          "cpu_model":platform.processor() or platform.uname().machine,"cpu_count":os.cpu_count(),
          "allowed_cpus_before_pin":sorted(os.sched_getaffinity(0)),"controller_cpu":pair["controller_cpu"],
          "adapter_cpu":pair["adapter_cpu"],"filesystems":{}}
    fp=sh(cj({"kernel":host["kernel"],"machine":host["machine"],"cpu_model":host["cpu_model"],"cpu_count":host["cpu_count"],
        "allowed_cpus":host["allowed_cpus_before_pin"],"controller_cpu":host["controller_cpu"],"adapter_cpu":host["adapter_cpu"],
        "filesystems":{}}))
    ready=readiness(protocol,pair["adapter_cpu"],pair["controller_cpu"],fp)
    out={"schema":"pr15i-d3c-readiness-only-v1","status":ready["readiness_status"],
         "failure_codes":ready["failure_codes"],"host_fingerprint":fp,"protocol_sha256":psha,
         "t6_commit":rec["t6_commit"],"selected_pair":pair,"observed":ready}
    print(json.dumps(out,sort_keys=True))
    return 0 if ready["readiness_status"]=="READY" else 4

def cmd_preflight(args):
    protocol,psha=load_protocol(); out=validate_out(args.out,True)
    if git(TOOLING_ROOT,"rev-parse","HEAD")=="":
        fail("D3C_GIT","no HEAD")
    # validate source commits and feature build in a throwaway worktree
    tmp=tempfile.mkdtemp(prefix="d3c-preflight-",dir=target_root())
    try:
        c=worktree(tmp,BASE_SHA)
        a=build(c,os.path.join(tmp,"build","A"),False)
        switch(c,BASE_SHA,EXPERIMENT_SHA)
        b=build(c,os.path.join(tmp,"build","B"),True)
        rec={"schema":"pr15i-d3c-preflight-v1","protocol_sha256":psha,"source_base_sha":BASE_SHA,
             "source_experiment_sha":EXPERIMENT_SHA,"base_binary":a["sha256"],"experiment_binary":b["sha256"],
             "distinct":a["sha256"]!=b["sha256"],"corpus_manifest_sha256":protocol["corpus_manifest_sha256"],
             "recorded_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
        if not rec["distinct"]: fail("D3C_AB","experiment binary equals BASE")
        wj(out,rec,exclusive=True)
    finally:
        shutil.rmtree(tmp,ignore_errors=True)
    print(json.dumps({"status":"PREFLIGHT_OK","out":out},sort_keys=True)); return 0

def validate_archive(arc,side,campaign,d):
    import tarfile
    if os.path.islink(arc) or not os.path.isfile(arc): fail("D3C_PREDECESSOR",f"{campaign} archive missing")
    if os.path.islink(side) or not os.path.isfile(side): fail("D3C_PREDECESSOR",f"{campaign} sidecar missing")
    rec=rj(side)
    if rec.get("schema")!="pr15i-d3c-archive-v1" or rec.get("campaign")!=campaign: fail("D3C_PREDECESSOR","archive identity")
    if rec.get("archive_sha256")!=sf(arc): fail("D3C_PREDECESSOR","archive digest")
    expected={rel:sf(os.path.join(d,rel)) for rel in archive_members(d) if os.path.isfile(os.path.join(d,rel))}
    members=rec.get("members")
    if not isinstance(members,dict) or members!=expected: fail("D3C_PREDECESSOR","archive member list")
    if rec.get("member_count")!=len(expected): fail("D3C_PREDECESSOR","archive member count")
    try:
        with tarfile.open(arc,"r:gz") as t:
            infos=t.getmembers()
            names=[m.name for m in infos]
            if names!=sorted(names) or len(set(names))!=len(names): fail("D3C_PREDECESSOR","archive order/duplicates")
            if set(names)!=set(expected) or len(names)!=len(expected): fail("D3C_PREDECESSOR","archive names")
            for m in infos:
                if not m.isfile(): fail("D3C_PREDECESSOR","non-regular archive member")
                f=t.extractfile(m)
                h=hashlib.sha256()
                for chunk in iter(lambda:f.read(1<<20),b""): h.update(chunk)
                if h.hexdigest()!=expected[m.name]: fail("D3C_PREDECESSOR","archive member digest")
    except (tarfile.TarError,OSError,AttributeError) as e:
        fail("D3C_PREDECESSOR",f"archive unreadable: {e}")
    return rec

def verified(dir,kind,campaign):
    if not os.path.isdir(dir): fail("D3C_PREDECESSOR",f"missing {campaign}")
    r=subprocess.run([sys.executable,os.path.join(TOOLING_DIR,"verify.py"),"--campaign-dir",dir],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if r.returncode!=0: fail("D3C_PREDECESSOR",f"{campaign} did not verify: {r.stdout[-400:]}")
    rep=json.loads(r.stdout)
    want="ACQUIRED_VERIFIED"
    if rep.get("verification")!="PASS" or rep.get("measurement_status")!=want: fail("D3C_PREDECESSOR",f"{campaign} status {rep.get('measurement_status')}")
    ev=os.path.expanduser(os.path.join("~",".local","share","quervant",EVIDENCE_REL))
    arc=os.path.join(ev,campaign+".tar.gz")
    validate_archive(arc,arc+".sha256",campaign,dir)
    return rep

def cmd_control(args):
    if args.campaign!=load_protocol()[0]["control_name"]: fail("D3C_CAMPAIGN","wrong control name")
    require_freeze(args.campaign)
    return run_measurement("control",args.campaign,validate_out(args.out))
def cmd_campaign(args):
    p,_=load_protocol(); campaign=args.campaign
    require_freeze(campaign)
    if campaign not in p["campaign_names"]: fail("D3C_CAMPAIGN","unknown campaign")
    root=os.path.dirname(validate_out(args.out))
    verified(os.path.join(root,p["control_name"]),"control",p["control_name"])
    if campaign==p["campaign_names"][0]:
        pass
    elif campaign==p["campaign_names"][1]:
        verified(os.path.join(root,p["campaign_names"][0]),"four_arm",p["campaign_names"][0])
    else: fail("D3C_CAMPAIGN","unexpected campaign")
    return run_measurement("four_arm",campaign,os.path.join(root,campaign))

def cmd_micro(args):
    # Run the deterministic Rust micro grid (feature test, release, ignored).
    out=validate_out(args.out)
    os.makedirs(out,exist_ok=False)
    r=subprocess.run(["cargo","test","--release","--locked","-p","quervant-core","--features","pr15i-d3c-experiment",
        "d3c_micro_grid","--","--ignored","--nocapture"],cwd=TOOLING_ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    lines=[l for l in r.stdout.splitlines() if l.startswith("D3CMICRO ")]
    recs=[json.loads(l[len("D3CMICRO "):]) for l in lines]
    if r.returncode!=0 or not recs: fail("D3C_MICRO",r.stdout[-1500:])
    # select smallest profile whose rescan fraction <=0.10 for every target K.
    ks=[100,256,512,1024]; chosen=None
    for prof in ("P0","P1","P2"):
        ok=True
        for k in ks:
            for key_len in (8, 32, 128, 1024):
                m=[x for x in recs if x["variant"]==prof and x["k"]==k and x["key_len"]==key_len and x["trace"]=="miss_stable"]
                if not m or m[0]["rescan_fraction"]>0.10: ok=False
        if ok: chosen=prof; break
    if chosen is None: fail("D3C_MICRO","no prefilter profile met the frozen rule")
    mem={}
    for r in recs:
        if r["variant"]=="exact_set":
            est=r["set_capacity"]*40+r["key_bytes"]
            mem[str(r["k"])]=max(mem.get(str(r["k"]),0),est)
    wj(os.path.join(out,"micro.json"),{"schema":"pr15i-d3c-micro-v1","records":recs,"selected_profile":chosen,
        "exact_set_aux_bytes_estimate":mem,"memory_estimate_note":"capacity*40 + owned key bytes; approximate, not allocator-exact",
        "source_experiment_sha":git(TOOLING_ROOT,"rev-parse","HEAD"),"protocol_sha256":PROTOCOL_SHA256})
    print(json.dumps({"status":"MICRO_OK","selected_profile":chosen,"records":len(recs)},sort_keys=True)); return 0

def cmd_dryproof(args):
    p,_=load_protocol(); out=validate_out(args.out); os.makedirs(out,exist_ok=False)
    c=worktree(out,BASE_SHA); a=build(c,os.path.join(out,"build","A"),False)
    switch(c,BASE_SHA,EXPERIMENT_SHA); b=build(c,os.path.join(out,"build","B"),True)
    if a["sha256"]==b["sha256"]: fail("D3C_AB","A/B identical")
    corpus=prepare_corpus(p,os.path.join(out,"corpus"))
    idx=os.path.join(out,"indexes","A-100000")
    h=harness(); oracle_mod=oracle()
    bi=build_index(h,a["binary"],os.path.join(corpus,oracle_mod.corpus_filename(100000)),idx,100000)
    # mode marker proof at first warmup using a real query
    exp=expected_for(p,100000)["pr15d_v1/100000/common/k100"]
    markers={}
    for arm in ("L","P","H"):
        m=mode_env(p,arm); expm=expected_marker(p,arm)
        ad=Adapter(b["binary"],idx,m,args.cpu or cpus()[0])
        try:
            r=ad.request({"request_id":"w0","op":"query","field":"key","term":"common","k":100,"mode":"warm"},read_marker=True)
            check(r,{"id":"proof","n":100000,"class":"common","field":"key","term":"common","k":100},exp)
            if ad.marker!=expm: fail("D3C_MODE",f"{ad.marker} != {expm}")
            markers[arm]=ad.marker
        finally: ad.close()
    wj(os.path.join(out,"dry-proof.json"),{"schema":"pr15i-d3c-dry-proof-v1","base_binary":a["sha256"],"experiment_binary":b["sha256"],
        "base_bytes":a["bytes"],"experiment_bytes":b["bytes"],
        "index_layout":bi["layout"],"markers":markers,"source_base_sha":BASE_SHA,"source_experiment_sha":EXPERIMENT_SHA,
        "feature_argv":b["argv"]},exclusive=True)
    print(json.dumps({"status":"DRY_PROOF_OK","markers":markers},sort_keys=True)); return 0

def cmd_adapter_compare(args):
    p,_=load_protocol()
    out=validate_out(args.out); os.makedirs(out,exist_ok=False)
    corpus=prepare_corpus(p,os.path.join(out,"corpus"))
    b=build(TOOLING_ROOT,os.path.join(out,"build"),True)
    h=harness(); om=oracle()
    cpu=args.cpu or cpus()[0]
    results={arm:{"mode":p["arm_modes"][arm],"marker":expected_marker(p,arm),"lanes":[]}
             for arm in ("L","P","H")}
    indices={}
    for n in p["n_values"]:
        idx=os.path.join(out,"indexes",f"n{n}")
        indices[str(n)]=build_index(h,b["binary"],os.path.join(corpus,om.corpus_filename(n)),idx,n)
        lanes_f=[l for l in lanes(p) if l["n"]==n]
        exp=expected_for(p,n)
        for arm in ("L","P","H"):
            env=mode_env(p,arm); expm=expected_marker(p,arm)
            a=Adapter(b["binary"],idx,env,cpu)
            try:
                for i,lane in enumerate(lanes_f):
                    r=a.request({"request_id":f"{arm}-{n}-{i}","op":"query","field":lane["field"],
                                 "term":lane["term"],"k":lane["k"],"mode":"warm"},read_marker=(i==0))
                    if i==0 and a.marker!=expm: fail("D3C_MODE",f"{arm}: {a.marker!r} != {expm!r}")
                    check(r,lane,exp[lane["id"]])
                    results[arm]["lanes"].append({"id":lane["id"],"n":n,"engine_ns":r["engine_ns"],
                                                  "total_hits":r["total_hits"],"doc_ids":r["doc_ids"]})
                if a.extra_stderr(): fail("D3C_ADAPTER",f"{arm}: unexpected stderr")
                if n==10000:
                    for mk in (10,100,1024):
                        mr=a.request({"request_id":f"{arm}-u38-{mk}","op":"query","field":"key",
                                      "term":"common","k":mk,"mode":"warm"})
                        check(mr,{"id":f"u38-{mk}","n":n,"class":"common","field":"key",
                                  "term":"common","k":mk},expected_for(p,n)[f"pr15d_v1/{n}/common/k{mk}"])
                    if a.extra_stderr(): fail("D3C_MODE",f"{arm}: second marker")
                    results[arm]["u38"]={"queries":[10,100,1024],"second_marker":False}
            finally: a.close()
    lanes_f=lanes(p)
    ids={arm:{r["id"]:(r["total_hits"],tuple(r["doc_ids"])) for r in v["lanes"]}
         for arm,v in results.items()}
    for lane in lanes_f:
        exp=expected_for(p,lane["n"])[lane["id"]]
        want=(exp["total_hits"],tuple(exp["doc_ids"]))
        if not (ids["L"][lane["id"]]==ids["P"][lane["id"]]==ids["H"][lane["id"]]==want):
            fail("D3C_ORACLE",f"cross-strategy mismatch {lane['id']}")
    rec={"schema":"pr15i-d3c-adapter-compare-v1","status":"THREE_STRATEGY_PARITY_OK",
         "source_sha":git(TOOLING_ROOT,"rev-parse","HEAD"),"adapter_sha256":b["sha256"],
         "adapter_bytes":b["bytes"],"feature_argv":b["argv"],"indices":indices,
         "lanes":len(lanes_f),"arms":results,
         "oracle":"independent pr15d corpus oracle; all 72 lanes exact"}
    wj(os.path.join(out,"adapter-compare.json"),rec,exclusive=True)
    print(json.dumps({"status":rec["status"],"lanes":len(lanes_f),"adapter_sha256":b["sha256"]},sort_keys=True))
    return 0

def cmd_explore(args):
    p,_=load_protocol()
    out=validate_out(args.out); os.makedirs(out,exist_ok=False)
    corpus=prepare_corpus(p,os.path.join(out,"corpus"))
    base_wt=worktree(out,BASE_SHA)
    base=build(base_wt,os.path.join(out,"build","A"),False)
    exp=build(TOOLING_ROOT,os.path.join(out,"build","B"),True)
    h=harness(); om=oracle()
    idx=os.path.join(out,"indexes","n100000")
    bi=build_index(h,base["binary"],os.path.join(corpus,om.corpus_filename(100000)),idx,100000)
    lanes_f=[l for l in lanes(p) if l["n"]==100000 and l["class"] in ("medium","common")
             and l["k"] in (10,100,256,1024)]
    if len(lanes_f)!=8: fail("D3C_EXPLORE",f"expected 8 lanes, got {len(lanes_f)}")
    adapter_cpu,controller_cpu=cpus(); pin(controller_cpu)
    host=host_record(p,adapter_cpu,controller_cpu,out,base_wt); host["campaign"]="exploratory"
    ready=readiness(p,adapter_cpu,controller_cpu,host["host_fingerprint"])
    if ready["readiness_status"]!="READY": fail("D3C_HOST_NOT_READY",json.dumps(ready["failure_codes"]))
    expmap=expected_for(p,100000)
    arms=[("A",base,None),("L",exp,"L"),("P",exp,"P"),("H",exp,"H")]
    rounds=args.rounds
    recs={a:[] for a,_,_ in arms}
    for rnd in range(rounds):
        order=arms[rnd%4:]+arms[:rnd%4]
        for lane in lanes_f:
            for key,binfo,_arm in order:
                rec=measure_lane(p,key,binfo["binary"],idx,adapter_cpu,lane,expmap[lane["id"]])
                rec["round"]=rnd+1
                recs[key].append(rec)
    table=[]
    for lane in lanes_f:
        def med(key):
            v=[r["summary_ns"]["median"] for r in recs[key] if r["id"]==lane["id"]]
            if len(v)!=rounds: fail("D3C_EXPLORE",f"{key} {lane['id']} rounds={len(v)}")
            return sorted(v)[len(v)//2]
        b=med("A"); row={"id":lane["id"],"n":lane["n"],"class":lane["class"],"k":lane["k"],
                         "BASE_ns":b,"rounds":rounds}
        for key,label in (("L","linear"),("P","prefilter_P2"),("H","exact_set")):
            m=med(key); row[f"{label}_ns"]=m; row[f"{label}_delta_ns"]=m-b
            row[f"{label}_pct"]=round((m-b)/b*100.0,3)
        table.append(row)
    rec={"schema":"pr15i-d3c-exploratory-v1","status":"EXPLORATORY_ONLY",
         "note":"Non-official diagnostic; not D3-C acceptance evidence; no policy selection.",
         "source_base_sha":BASE_SHA,"source_experiment_sha":git(TOOLING_ROOT,"rev-parse","HEAD"),
         "base_binary":{k:base[k] for k in ("binary","sha256","bytes","source_sha")},
         "experiment_binary":{k:exp[k] for k in ("binary","sha256","bytes","source_sha")},
         "feature_argv":exp["argv"],"index":bi,"lanes":len(lanes_f),"rounds":rounds,
         "samples_per_lane":p["samples_per_lane_slot"],"warmups":p["warmups_per_lane_slot"],
         "host":host,"readiness":ready,"table":table,
         "raw":{k:v for k,v in recs.items()}}
    wj(os.path.join(out,"exploratory.json"),rec,exclusive=True)
    lines=["| K | class | BASE ns | linear ns | linear % | P2 ns | P2 % | exact_set ns | exact_set % |",
           "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in table:
        lines.append(f"| {r['k']} | {r['class']} | {r['BASE_ns']} | {r['linear_ns']} | {r['linear_pct']:+.2f}% | "
                     f"{r['prefilter_P2_ns']} | {r['prefilter_P2_pct']:+.2f}% | {r['exact_set_ns']} | {r['exact_set_pct']:+.2f}% |")
    open(os.path.join(out,"exploratory.md"),"w").write("\n".join(lines)+"\n")
    print("\n".join(lines))
    print(json.dumps({"status":"EXPLORATORY_ONLY","lanes":len(lanes_f),"rounds":rounds},sort_keys=True))
    return 0

def main(argv=None):
    ap=argparse.ArgumentParser(prog="pr15i-d3-c"); sub=ap.add_subparsers(dest="cmd",required=True)
    ro=sub.add_parser("readiness-only"); ro.add_argument("--freeze-receipt",required=False); ro.set_defaults(fn=cmd_readiness_only)
    p=sub.add_parser("preflight"); p.add_argument("--out",required=True); p.set_defaults(fn=cmd_preflight)
    m=sub.add_parser("micro"); m.add_argument("--out",required=True); m.set_defaults(fn=cmd_micro)
    ac=sub.add_parser("adapter-compare"); ac.add_argument("--out",required=True); ac.add_argument("--cpu",type=int,default=None); ac.set_defaults(fn=cmd_adapter_compare)
    ex=sub.add_parser("explore"); ex.add_argument("--out",required=True); ex.add_argument("--rounds",type=int,default=4); ex.set_defaults(fn=cmd_explore)
    d=sub.add_parser("dry-proof"); d.add_argument("--candidate-sha",required=True); d.add_argument("--out",required=True); d.add_argument("--cpu",type=int,default=None); d.set_defaults(fn=cmd_dryproof)
    c=sub.add_parser("control"); c.add_argument("--campaign",required=True); c.add_argument("--out",required=True); c.add_argument("--idle-confirmed",action="store_true"); c.set_defaults(fn=cmd_control)
    q=sub.add_parser("campaign"); q.add_argument("--campaign",required=True); q.add_argument("--out",required=True); q.add_argument("--idle-confirmed",action="store_true"); q.set_defaults(fn=cmd_campaign)
    pub=sub.add_parser("publish"); pub.add_argument("--campaign-dir",required=True); pub.add_argument("--evidence-root",required=True); pub.set_defaults(fn=cmd_publish)
    a=ap.parse_args(argv)
    if a.cmd in ("control","campaign") and not getattr(a,"idle_confirmed",False): fail("D3C_IDLE","--idle-confirmed required")
    try: return a.fn(a)
    except SystemExit: raise
    except Exception as e: print(f"BLOCKED D3C_ERROR: {e}",file=sys.stderr); return 3
if __name__=="__main__": raise SystemExit(main())

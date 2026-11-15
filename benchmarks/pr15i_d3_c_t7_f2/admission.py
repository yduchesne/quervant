#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, tarfile
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]; BM=ROOT/"benchmarks/pr15i_d3_c"
try:
 from . import constants as C
except ImportError:
 import constants as C

class AdmissionError(Exception): pass
def sh(p): 
 h=hashlib.sha256()
 with open(p,"rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 return h.hexdigest()
def rj(p):
 def hook(pairs):
  d={}
  for k,v in pairs:
   if k in d: raise AdmissionError(f"duplicate JSON key {k}")
   d[k]=v
  return d
 def bad(x): raise AdmissionError(f"invalid JSON constant {x}")
 return json.loads(Path(p).read_bytes().decode(),object_pairs_hook=hook,parse_constant=bad)
def safe_members(tar_path):
 out={}
 with tarfile.open(tar_path,"r:gz") as t:
  if len(t.getmembers())>5000: raise AdmissionError("member limit")
  total=0
  for m in t.getmembers():
   n=m.name
   if not m.isfile(): raise AdmissionError(f"non-regular member {n}")
   if n.startswith("/") or ".." in n.split("/") or "\\" in n: raise AdmissionError(f"unsafe {n}")
   if n in out: raise AdmissionError(f"duplicate {n}")
   if m.size>256*1024*1024: raise AdmissionError(f"member too large {n}")
   total+=m.size
   if total>4*1024**3: raise AdmissionError("archive too large")
   f=t.extractfile(m); h=hashlib.sha256()
   for b in iter(lambda:f.read(1<<20),b""): h.update(b)
   out[n]=h.hexdigest()
 return out
def validate_archive(archive_root,campaign,loose):
 arc=Path(archive_root)/f"{campaign}.tar.gz"; side=Path(archive_root)/f"{campaign}.tar.gz.sha256"
 if arc.is_symlink() or not arc.is_file(): raise AdmissionError("missing archive")
 if side.is_symlink() or not side.is_file(): raise AdmissionError("missing sidecar")
 if sh(arc)!=C.ARCHIVES[campaign]: raise AdmissionError("archive literal digest")
 rec=rj(side)
 if rec.get("schema")!="pr15i-d3c-archive-v1" or rec.get("campaign")!=campaign: raise AdmissionError("sidecar identity")
 if rec.get("archive_sha256")!=sh(arc): raise AdmissionError("sidecar archive digest")
 members=safe_members(arc)
 if rec.get("member_count")!=len(members): raise AdmissionError("member count")
 if rec.get("members")!=members: raise AdmissionError("member list")
 for rel,dig in members.items():
  p=Path(loose)/rel
  if p.is_symlink() or not p.is_file() or sh(p)!=dig: raise AdmissionError(f"loose mismatch {rel}")
 return {"archive_sha256":sh(arc),"sidecar_sha256":sh(side),"members":len(members)}
def validate_f1(receipt):
 rp=Path(receipt)
 if rp.is_symlink() or not rp.is_file(): raise AdmissionError("missing F1 receipt")
 if sh(rp)!=C.T7_F1_RECEIPT_SHA: raise AdmissionError("F1 receipt digest")
 rec=rj(rp)
 if rec.get("t7_commit")!=C.T7_F1_COMMIT or set(rec.get("files",{}))!={"analysis.py","policy.py","verify_derived.py","freeze.py"}: raise AdmissionError("F1 receipt identity")
 for f,d in rec["files"].items():
  r=subprocess.run(["git","-C",str(ROOT),"show",f"{C.T7_F1_COMMIT}:benchmarks/pr15i_d3_c_t7/{f}"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if r.returncode: raise AdmissionError(f"F1 git blob {f}")
  if hashlib.sha256(r.stdout).hexdigest()!=d: raise AdmissionError(f"F1 blob digest {f}")
  if sh(BM.parent/"pr15i_d3_c_t7"/f)!=d: raise AdmissionError(f"F1 worktree {f}")
 r=subprocess.run(["git","-C",str(ROOT),"merge-base","--is-ancestor",C.T7_F1_COMMIT,"HEAD"])
 if r.returncode: raise AdmissionError("F1 not ancestor")
 return rec
def validate_micro(path):
 p=Path(path)
 if p.is_symlink() or not p.is_file(): raise AdmissionError("missing micro")
 m=rj(p)
 if m.get("schema")!="pr15i-d3c-micro-v1" or len(m.get("records",[]))!=900: raise AdmissionError("micro shape")
 if m.get("selected_profile")!="P2" or m.get("source_experiment_sha")!=C.EXPERIMENT_SHA: raise AdmissionError("micro profile/source")
 variants={"linear","P0","P1","P2","exact_set"}; lens={8,32,128,1024}; traces={"miss_stable","duplicate_retained","churn","evicted_revisit","collision_distinct"}; seen=set(); mem={}
 for r in m["records"]:
  key=(r.get("variant"),r.get("k"),r.get("key_len"),r.get("trace"))
  if r.get("variant") not in variants or r.get("k") not in C.KS or r.get("key_len") not in lens or r.get("trace") not in traces or key in seen: raise AdmissionError("micro combination")
  seen.add(key)
  if not isinstance(r.get("rounds"),list) or len(r["rounds"])!=5 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or x<=0 for x in r["rounds"]): raise AdmissionError("micro rounds")
  for f in ("set_len","set_capacity","key_bytes"):
   if isinstance(r.get(f),bool) or not isinstance(r.get(f),int) or r[f]<0: raise AdmissionError(f"micro {f}")
  if r["set_len"]>r["set_capacity"]: raise AdmissionError("micro len")
  if r["variant"]=="exact_set": mem[str(r["k"])]=max(mem.get(str(r["k"]),0),r["set_capacity"]*40+r["key_bytes"])
 if len(seen)!=900 or set(mem)!= {str(k) for k in C.KS}: raise AdmissionError("micro completeness")
 return {"micro_sha256":sh(p),"source_sha256":C.EXPERIMENT_SHA,"selected_profile":"P2","H_memory_by_k":mem}
def audit(series_root,archive_root,micro_path,f1_receipt):
 series=Path(series_root).resolve(); archive=Path(archive_root).resolve()
 proto=BM/"protocol_v3r3.json"
 if sh(proto)!=C.R3_SHA: raise AdmissionError("protocol digest")
 r=subprocess.run([sys.executable,str(BM/"verify.py"),"--series-root",str(series)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if r.returncode: raise AdmissionError(f"series verify failed: {r.stdout[-300:]}")
 rep=json.loads(r.stdout)
 if rep.get("verification")!="PASS" or not rep.get("full_series") or not rep.get("provenance_consistent"): raise AdmissionError("series status")
 if rep.get("control")!="ACQUIRED_VERIFIED" or any(x!="ACQUIRED_VERIFIED" for x in rep.get("campaigns",[])): raise AdmissionError("campaign status")
 f1=validate_f1(f1_receipt); micro=validate_micro(micro_path)
 before={str(p):sh(p) for p in [proto,Path(f1_receipt),Path(micro_path)]}
 archives={}
 for camp in [C.CONTROL,*C.CAMP]: archives[camp]=validate_archive(archive,camp,series/camp)
 after={str(p):sh(p) for p in [proto,Path(f1_receipt),Path(micro_path)]}
 if before!=after: raise AdmissionError("input mutation during audit")
 return {"schema":"pr15i-d3c-t7f2-admission-v1","status":"PASS","protocol_sha256":C.R3_SHA,"t6_commit":C.T6_SHA,
  "f1_commit":f1["t7_commit"],"f1_receipt_sha256":sh(f1_receipt),"series_report":rep,"archives":archives,"micro":micro}
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("command",choices=["check"]); ap.add_argument("--series-root",required=True); ap.add_argument("--archive-root",required=True); ap.add_argument("--micro-json",required=True); ap.add_argument("--f1-receipt",required=True); ap.add_argument("--out",required=True); a=ap.parse_args(argv)
 try: rec=audit(a.series_root,a.archive_root,a.micro_json,a.f1_receipt)
 except Exception as e:
  print(f"T7F2_ADMISSION_FAIL: {e}",file=sys.stderr); return 3
 p=Path(a.out)
 if p.exists(): raise SystemExit("output exists")
 p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(rec,sort_keys=True,indent=2)+"\n")
 print(json.dumps({"status":"PASS","gate":"A"})); return 0
if __name__=="__main__": raise SystemExit(main())

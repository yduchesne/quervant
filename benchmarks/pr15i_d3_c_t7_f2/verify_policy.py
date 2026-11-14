#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
try:
 from . import admission
except ImportError:
 import admission
try:
 from . import constants as C
except ImportError:
 import constants as C
try:
 from . import oracle as O
except ImportError:
 import oracle as O
ROOT=Path(__file__).resolve().parents[2]; BM=ROOT/"benchmarks/pr15i_d3_c"; F1=ROOT/"benchmarks/pr15i_d3_c_t7"
def sh(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def _rj(p):
 def hook(ps):
  d={}
  for k,v in ps:
   if k in d: raise ValueError(f"duplicate {k}")
   d[k]=v
  return d
 return json.loads(Path(p).read_text(),object_pairs_hook=hook)
def compare(analysis,policy,mem):
 rows={r["id"]:r for r in (analysis["lanes"].values() if isinstance(analysis["lanes"],dict) else analysis["lanes"])}
 got=O.derive_nine(analysis,mem)
 old={r["k"]:r for r in policy["rows"]}; errs=[]
 if [r["k"] for r in policy["rows"]]!=list(C.KS): errs.append("T7F2_POLICY_K_ORDER")
 for g in got:
  o=old.get(g["k"])
  if not isinstance(o,dict): errs.append(f"T7F2_POLICY_ROW_MISSING:{g['k']}"); continue
  for f in ("P_status","H_status","selected_strategy","decision_status","filter_sensitive","H_memory"):
   if g[f]!=o.get(f): errs.append(f"T7F2_POLICY_DECISION_MISMATCH:{g['k']}:{f}")
 return got,errs
def verify_all(series_root,archive_root,micro_json,f1_receipt,analysis_json,policy_json):
 before={str(p):sh(p) for p in [analysis_json,policy_json,micro_json,f1_receipt]}
 a=admission.audit(series_root,archive_root,micro_json,f1_receipt)
 an=_rj(analysis_json); pol=_rj(policy_json)
 if an.get("schema")!="pr15i-d3c-t7-analysis-v1" or an.get("protocol_sha256")!=C.R3_SHA: raise SystemExit("T7F2_STAT_INPUT_MISMATCH")
 if pol.get("schema")!="pr15i-d3c-t7-policy-v1" or pol.get("protocol_sha256")!=C.R3_SHA: raise SystemExit("T7F2_POLICY_PROTOCOL")
 if pol.get("status")!="T7_POLICY_DERIVED_PENDING_INDEPENDENT_VERIFICATION": raise SystemExit("T7F2_POLICY_STATUS")
 if len(an.get("lanes",{}))!=72 or [r.get("k") for r in pol.get("rows",[])]!=list(C.KS): raise SystemExit("T7F2_IDENTITY_INVENTORY")
 diag=Path(tempfile.mkdtemp(prefix="t7f2-diag-",dir=str(ROOT/"target/pr15i-d3-c/t7f2")))
 r=subprocess.run([sys.executable,str(F1/"verify_derived.py"),"--analysis",str(analysis_json),"--policy",str(policy_json),
  "--series-root",str(series_root),"--micro-json",str(micro_json),"--out",str(diag)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if r.returncode: raise SystemExit("T7F2_F1_STAT_CHECK_FAIL")
 mem=a["micro"]["H_memory_by_k"]; got,errs=compare(an,pol,mem)
 after={str(p):sh(p) for p in [analysis_json,policy_json,micro_json,f1_receipt]}
 if before!=after: raise SystemExit("T7F2_INPUT_MUTATION")
 return {"schema":"pr15i-d3c-t7f2-decision-verification-v1","verification":"FAIL" if errs else "PASS","decision_verification":"FAIL" if errs else "PASS",
  "comparison_rows":len(got),"statistical_lanes":len(an["lanes"]),"errors":errs,"computed_rows":got,
  "input_hashes":{"analysis":sh(analysis_json),"policy":sh(policy_json),"micro":sh(micro_json),"f1_receipt":sh(f1_receipt)},
  "f1_statistical_check":"PASS","historical_comparison":"MISMATCH" if errs else "MATCH","admission":a["status"]}
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--series-root",required=True); ap.add_argument("--archive-root",required=True); ap.add_argument("--micro-json",required=True); ap.add_argument("--f1-receipt",required=True); ap.add_argument("--analysis",required=True); ap.add_argument("--policy",required=True); ap.add_argument("--out",required=True); a=ap.parse_args(argv)
 try: rec=verify_all(a.series_root,a.archive_root,a.micro_json,a.f1_receipt,a.analysis,a.policy)
 except SystemExit as e: print(str(e),file=sys.stderr); return 4
 out=Path(a.out)
 if out.exists(): print("T7F2_OUTPUT_EXISTS",file=sys.stderr); return 21
 out.mkdir(parents=True); (out/"verification.json").write_text(json.dumps(rec,sort_keys=True,indent=2)+"\n")
 print(json.dumps({"verification":rec["verification"],"rows":rec["comparison_rows"]}))
 return 0 if rec["verification"]=="PASS" else 3
if __name__=="__main__": raise SystemExit(main())

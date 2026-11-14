#!/usr/bin/env python3
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
FILES=["__init__.py","constants.py","admission.py","oracle.py","verify_policy.py","freeze_gate.py","acceptance_gate.py","fixture_factory.py","test_oracle.py","test_mutations.py","test_admission.py","test_freeze_gate.py","test_acceptance_gate.py"]
def sh(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def prepare(out):
 if Path(out).exists(): raise SystemExit("T7F2_FREEZE_EXISTS")
 Path(out).mkdir(parents=True)
 c=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
 rec={"schema":"pr15i-d3c-t7f2-freeze-v1","t7f2_commit":c,"files":{f:sh(HERE/f) for f in FILES}}
 p=Path(out)/"freeze-receipt.json"; p.write_text(json.dumps(rec,sort_keys=True,indent=2)+"\n"); print(sh(p)); return 0
def verify(receipt):
 try:
  r=json.load(open(receipt)); c=r.get("t7f2_commit")
  subprocess.run(["git","-C",str(ROOT),"merge-base","--is-ancestor",c,"HEAD"],check=True)
  if set(r.get("files",{}))!=set(FILES): raise SystemExit("T7F2_FREEZE_INVENTORY")
  for f,d in r["files"].items():
   blob=subprocess.check_output(["git","-C",str(ROOT),"show",f"{c}:benchmarks/pr15i_d3_c_t7_f2/{f}"])
   if hashlib.sha256(blob).hexdigest()!=d or sh(HERE/f)!=d: raise SystemExit(f"T7F2_FREEZE_BYTES:{f}")
 except SystemExit: raise
 except Exception as e: raise SystemExit(f"T7F2_FREEZE_FAIL:{e}")
 print(json.dumps({"status":"T7F2_FREEZE_VERIFIED","commit":c})); return 0
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--prepare",action="store_true"); ap.add_argument("--verify",action="store_true"); ap.add_argument("--out"); ap.add_argument("--receipt"); a=ap.parse_args(argv)
 if a.prepare: return prepare(a.out)
 if a.verify: return verify(a.receipt)
 raise SystemExit(2)
if __name__=="__main__": raise SystemExit(main())

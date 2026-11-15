#!/usr/bin/env python3
import argparse,hashlib,json,os,subprocess,sys
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
FILES=["analysis.py","policy.py","verify_derived.py","freeze.py"]
def sh(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--prepare",action="store_true"); ap.add_argument("--verify",action="store_true"); ap.add_argument("--out"); ap.add_argument("--receipt"); a=ap.parse_args(argv)
 if a.prepare:
  if os.path.isdir(a.out): raise SystemExit("freeze output exists")
  os.makedirs(a.out)
  commit=subprocess.check_output(["git","-C",ROOT,"rev-parse","HEAD"],text=True).strip()
  rec={"schema":"pr15i-d3c-t7f1-freeze-v1","t7_commit":commit,"files":{f:sh(os.path.join(HERE,f)) for f in FILES},
       "protocol_sha256":"c6193830db591cd60983771a0e35d71e4d9a4ccbdd19471e53babaa8f6bd6f1c",
       "t6_commit":"44ccd9e027071cf12777610abae5e6ab5f03177f"}
  p=os.path.join(a.out,"freeze-receipt.json"); json.dump(rec,open(p,"w"),sort_keys=True,indent=2); print(sh(p)); return 0
 if a.verify:
  rec=json.load(open(a.receipt))
  if any(sh(os.path.join(HERE,f))!=d for f,d in rec["files"].items()): raise SystemExit("T7F1_FREEZE_MISMATCH")
  print(json.dumps({"status":"T7_ANALYSIS_FROZEN","commit":rec["t7_commit"]})); return 0
 raise SystemExit("choose --prepare/--verify")
if __name__=="__main__": raise SystemExit(main())

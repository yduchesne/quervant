#!/usr/bin/env python3
import argparse,hashlib,inspect,json,os,subprocess,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
try:
 from . import constants as C
except ImportError:
 import constants as C
def fq(names): return tuple("benchmarks.pr15i_d3_c_t7_f2."+n for n in names)
def load_tests(names):
 return unittest.TestLoader().loadTestsFromNames(fq(names))
def check_result(result,expected=60):
 if result.testsRun!=expected or not result.wasSuccessful() or result.skipped or result.expectedFailures or result.unexpectedSuccesses or result.failures or result.errors: raise SystemExit("T7F2_ACCEPTANCE_TEST_FAIL")
def check_source(files):
 if len(files)!=13: raise SystemExit("T7F2_SOURCE_INVENTORY")
 for f in files:
  p=HERE/f
  if p.is_symlink() or not p.is_file(): raise SystemExit(f"T7F2_SOURCE_MISSING:{f}")
 return {f:hashlib.sha256(p.read_bytes()).hexdigest() for f in files}
def check_qa(cmds):
 out=[]
 for c in cmds:
  r=subprocess.run(c,shell=False,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  out.append({"argv":c,"exit":r.returncode,"sha256":hashlib.sha256(r.stdout).hexdigest()})
  if r.returncode: raise SystemExit(f"T7F2_QA_FAIL:{c[0]}")
 return out
def main(argv=None):
 ap=argparse.ArgumentParser(); ap.add_argument("--out",required=True); ap.add_argument("--run-qa",action="store_true"); a=ap.parse_args(argv)
 if Path(a.out).exists(): raise SystemExit("T7F2_OUTPUT_EXISTS")
 names=C.MANDATORY_TEST_IDS
 if len(names)!=60: raise SystemExit("T7F2_ROSTER_COUNT")
 suite=load_tests(names); res=unittest.TestResult(); suite.run(res); check_result(res)
 files=[p.name for p in HERE.iterdir() if p.is_file() and p.suffix==".py"]
 hashes=check_source(files)
 qa=[]
 if a.run_qa:
  cmds=[["python3","-m","unittest","discover","-s","benchmarks/pr15i_d3_c_t7_f2","-p","test_*.py","-v"],
   ["python3","-m","unittest","discover","-s","benchmarks/pr15i_d3_c","-p","test_*.py","-v"],
   ["cargo","+1.85.0","fmt","--all","--","--check"],["cargo","+1.85.0","clippy","--workspace","--all-targets","--","-D","warnings"],
   ["cargo","+1.85.0","test","--workspace","--all-targets"],["cargo","+1.85.0","doc","--workspace","--no-deps"],
   ["cargo","fmt","--all","--","--check"],["cargo","clippy","--workspace","--all-targets","--","-D","warnings"],
   ["cargo","test","--workspace","--all-targets"],["cargo","llvm-cov","--workspace","--all-targets","--fail-under-lines","85"],
   ["cargo","doc","--workspace","--no-deps"]]
  qa=check_qa(cmds)
 Path(a.out).mkdir(parents=True); rec={"schema":"pr15i-d3c-t7f2-acceptance-v1","status":"PASS","tests":list(names),"tests_run":res.testsRun,"source":hashes,"qa":qa}
 (Path(a.out)/"acceptance.json").write_text(json.dumps(rec,sort_keys=True,indent=2)+"\n"); print(json.dumps({"status":"PASS","tests":res.testsRun})); return 0
if __name__=="__main__": raise SystemExit(main())

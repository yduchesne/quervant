import copy,json,os,shutil,subprocess,sys,unittest
from pathlib import Path
try:
 from . import verify_policy as V
except ImportError:
 import verify_policy as V
try:
 from . import constants as C
except ImportError:
 import constants as C
ROOT=Path(__file__).resolve().parents[2]
A=ROOT/"target/pr15i-d3-c/t7-derived/t7f1-analysis-01/analysis.json"; P=ROOT/"target/pr15i-d3-c/t7-derived/t7f1-policy-01.json"; M=ROOT/"target/pr15i-d3-c/micro-05/micro.json"
S=ROOT/"target/pr15i-d3-c/official-v3r3"; AR=Path.home()/".local/share/quervant/benchmark-evidence/pr15i-d3-c-v3r3"; F1=ROOT/"target/pr15i-d3-c/t7f1-freeze/freeze-receipt.json"
TMP=ROOT/"target/pr15i-d3-c/t7f2-tests/mutations"
class TestMutation(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if TMP.exists(): shutil.rmtree(TMP)
  TMP.mkdir(parents=True)
  cls.an=json.load(open(A)); cls.pol=json.load(open(P)); m=json.load(open(M)); cls.mem={}
  for r in m["records"]:
   if r["variant"]=="exact_set": cls.mem[str(r["k"])]=max(cls.mem.get(str(r["k"]),0),r["set_capacity"]*40+r["key_bytes"])
  _,e=V.compare(cls.an,cls.pol,cls.mem); assert not e, e
 def mut(self,fn):
  a=copy.deepcopy(self.an); p=copy.deepcopy(self.pol); fn(a,p); _,e=V.compare(a,p,self.mem); return e
 def test_m01_change_selected(self):
  e=self.mut(lambda a,p: p["rows"][6].__setitem__("selected_strategy","H")); self.assertTrue(any("DECISION_MISMATCH" in x for x in e))
 def test_m02_change_candidate_status(self):
  e=self.mut(lambda a,p: p["rows"][4].__setitem__("P_status","INELIGIBLE")); self.assertTrue(any("DECISION_MISMATCH" in x for x in e))
 def test_m03_change_decision_code(self):
  e=self.mut(lambda a,p: p["rows"][6].__setitem__("decision_status","SELECTED_ELIGIBLE")); self.assertTrue(any("DECISION_MISMATCH" in x for x in e))
 def test_m04_change_h_memory(self):
  e=self.mut(lambda a,p: p["rows"][0].__setitem__("H_memory",p["rows"][0]["H_memory"]+1)); self.assertTrue(any("DECISION_MISMATCH" in x for x in e))
 def test_m05_change_filter_sensitive(self):
  def f(a,p):
   lid="pr15d_v1/100000/medium/k256"; a["lanes"][lid]["campaigns"][C.CAMP[0]]["filter_sensitive"]=True
  e=self.mut(f); self.assertTrue(any("DECISION_MISMATCH" in x for x in e))
 def test_m06_drop_k_row(self):
  e=self.mut(lambda a,p: p["rows"].pop()); self.assertTrue(e)
 def test_m07_duplicate_k(self):
  e=self.mut(lambda a,p: p["rows"].__setitem__(8,copy.deepcopy(p["rows"][7]))); self.assertTrue(e)
 def test_m08_change_primary_ci(self):
  e=self.mut(lambda a,p: a["lanes"]["pr15d_v1/100000/medium/k256"]["campaigns"][C.CAMP[0]]["CI_P_A"].__setitem__("high",1.1)); self.assertTrue(e)
 def test_m09_change_attribution_ci(self):
  def f(a,p):
   for cls in ("medium","common"):
    x=a["lanes"][f"pr15d_v1/100000/{cls}/k256"]["campaigns"][C.CAMP[0]]; x["R_P_L"]=1.1; x["CI_P_L"]={"low":1.05,"high":1.2}
  e=self.mut(f); self.assertTrue(e)
 def test_m10_uncertain_then_decisive(self):
  a=copy.deepcopy(self.an); a["lanes"]["pr15d_v1/10000/absent/k256"]["campaigns"][C.CAMP[0]]["R_P_A"]=1.05; a["lanes"]["pr15d_v1/10000/absent/k256"]["campaigns"][C.CAMP[0]]["CI_P_A"]={"low":1.01,"high":1.12}; a["lanes"]["pr15d_v1/100000/common/k256"]["campaigns"][C.CAMP[0]]["R_P_A"]=0.99; a["lanes"]["pr15d_v1/100000/common/k256"]["campaigns"][C.CAMP[0]]["CI_P_A"]={"low":0.98,"high":0.999}; got,e=V.compare(a,self.pol,self.mem); self.assertNotEqual(got[6]["P_status"],"INCONCLUSIVE")
 def cli(self,name,which):
  d=TMP/name; d.mkdir(); pol=copy.deepcopy(self.pol); an=copy.deepcopy(self.an)
  if which=="policy": pol["rows"][6]["selected_strategy"]="H"; p=d/"policy.json"; json.dump(pol,open(p,"w")); anp=A
  elif which=="status": pol["rows"][4]["P_status"]="INELIGIBLE"; p=d/"policy.json"; json.dump(pol,open(p,"w")); anp=A
  else: an["lanes"]["pr15d_v1/100000/medium/k256"]["campaigns"][C.CAMP[0]]["CI_P_A"]["high"]=1.2; p=P; anp=d/"analysis.json"; json.dump(an,open(anp,"w"))
  out=d/"out"; r=subprocess.run([sys.executable,"-m","benchmarks.pr15i_d3_c_t7_f2.verify_policy","--series-root",str(S),"--archive-root",str(AR),"--micro-json",str(M),"--f1-receipt",str(F1),"--analysis",str(anp),"--policy",str(p),"--out",str(out)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  self.assertNotEqual(r.returncode,0); self.assertFalse((out/"verification.json").exists())
 def test_m11_cli_rejects_selected_mutation(self): self.cli("m11","policy")
 def test_m12_cli_rejects_status_mutation(self): self.cli("m12","status")
 def test_m13_cli_rejects_ci_mutation(self): self.cli("m13","analysis")

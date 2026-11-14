import unittest
from fractions import Fraction
from . import oracle as O
from . import constants as C
from . import fixture_factory as F
K=256
def rows(**kw): return F.full(K,**kw)
def ev(rows,c="d3c-v3r3-strategies-01",cand="P",mem=0): return O.evaluate_campaign_candidate(rows,c,K,cand,mem)
class TestCandidate(unittest.TestCase):
 def test_b01_default_eligible(self): self.assertEqual(ev(rows())["status"],"ELIGIBLE")
 def test_b02_target_boundary_pass(self):
  r=rows(); x=r[f"pr15d_v1/100000/medium/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; x["R_P_A"]=0.97; x["CI_P_A"]={"low":0.95,"high":0.999}; self.assertEqual(ev(r)["status"],"ELIGIBLE")
 def test_b03_target_ci_upper_equal_one(self):
  r=rows(); x=r[f"pr15d_v1/100000/medium/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; x["R_P_A"]=0.97; x["CI_P_A"]={"low":0.95,"high":1.0}; self.assertEqual(ev(r)["status"],"INCONCLUSIVE")
 def test_b04_target_decisive(self):
  r=rows(); x=r[f"pr15d_v1/100000/medium/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; x["R_P_A"]=0.970001; x["CI_P_A"]={"low":0.970002,"high":0.99}; self.assertEqual(ev(r)["status"],"INELIGIBLE")
 def test_b05_guard_boundary_pass(self):
  r=rows(); x=r[f"pr15d_v1/10000/absent/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; x["R_P_A"]=1.10; x["CI_P_A"]={"low":1.0,"high":1.10}; self.assertEqual(ev(r)["status"],"ELIGIBLE")
 def test_b06_guard_decisive(self):
  r=rows(); x=r[f"pr15d_v1/10000/absent/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; x["R_P_A"]=1.100001; x["CI_P_A"]={"low":1.100002,"high":1.11}; self.assertEqual(ev(r)["status"],"INELIGIBLE")
 def test_b07_attribution_exact_pass(self):
  r=rows(); m=r[f"pr15d_v1/100000/medium/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; c=r[f"pr15d_v1/100000/common/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; m["R_P_L"]=0.98; m["CI_P_L"]={"low":0.95,"high":0.99}; c["R_P_L"]=1.0; c["CI_P_L"]={"low":0.95,"high":1.0}; self.assertEqual(ev(r)["status"],"ELIGIBLE")
 def test_b08_attribution_ci_uncertain(self):
  r=rows(); m=r[f"pr15d_v1/100000/medium/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; c=r[f"pr15d_v1/100000/common/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; m["R_P_L"]=0.98; m["CI_P_L"]={"low":0.97,"high":1.0}; c["R_P_L"]=0.99; c["CI_P_L"]={"low":0.97,"high":1.0}; self.assertEqual(ev(r)["status"],"INCONCLUSIVE")
 def test_b09_attribution_decisive(self):
  r=rows(); 
  for cls in ("medium","common"):
   x=r[f"pr15d_v1/100000/{cls}/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; x["R_P_L"]=0.980001; x["CI_P_L"]={"low":0.980001,"high":0.99}
  self.assertEqual(ev(r)["status"],"INELIGIBLE")
 def test_b10_earlier_uncertain_later_decisive(self):
  r=rows(); a=r[f"pr15d_v1/10000/absent/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; a["R_P_A"]=1.05; a["CI_P_A"]={"low":1.01,"high":1.12}; x=r[f"pr15d_v1/100000/common/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]; x["R_P_A"]=0.99; x["CI_P_A"]={"low":0.98,"high":0.999}; self.assertEqual(ev(r)["status"],"INELIGIBLE")
 def test_b11_h_memory_exact_limit(self): self.assertEqual(ev(rows(),cand="H",mem=C.H_LIMIT_BYTES)["status"],"ELIGIBLE")
 def test_b12_h_memory_one_over(self): self.assertEqual(ev(rows(),cand="H",mem=C.H_LIMIT_BYTES+1)["status"],"INELIGIBLE")
 def test_b13_retention_below_four(self): self.assertEqual(ev(rows(ret=3))["status"],"INCONCLUSIVE")
 def test_b14_malformed_ci_rejected(self):
  r=rows(); r[f"pr15d_v1/100000/medium/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]["CI_P_A"]={"low":2,"high":1}
  with self.assertRaises(O.PolicyInputError): ev(r)
 def test_b15_nan_bool_missing_rejected(self):
  for v in (float("nan"),True,None):
   r=rows(); r[f"pr15d_v1/100000/medium/k{K}"]["campaigns"]["d3c-v3r3-strategies-01"]["R_P_A"]=v
   with self.assertRaises(O.PolicyInputError): ev(r)
 def test_b16_series_decisive_priority(self):
  a=ev(rows(ret=3)); b=ev(rows(rcand=0.99)); self.assertEqual(O.combine_campaign_candidate(a,b)["status"],"INELIGIBLE")
class TestSelection(unittest.TestCase):
 def test_s01_both_ineligible(self): self.assertEqual(O.select_k("INELIGIBLE","INELIGIBLE",False,None,None),("LINEAR_BASE","LINEAR_BASE"))
 def test_s02_both_ineligible_even_sensitive(self): self.assertEqual(O.select_k("INELIGIBLE","INELIGIBLE",True,None,None),("LINEAR_BASE","LINEAR_BASE"))
 def test_s03_sensitive_blocks_selection(self): self.assertEqual(O.select_k("ELIGIBLE","INELIGIBLE",True,None,None)[1],"K_INCONCLUSIVE_FILTER_SENSITIVE")
 def test_s04_eligible_vs_ineligible(self): self.assertEqual(O.select_k("ELIGIBLE","INELIGIBLE",False,None,None),("P","SELECTED_ELIGIBLE"))
 def test_s05_eligible_vs_inconclusive(self): self.assertEqual(O.select_k("ELIGIBLE","INCONCLUSIVE",False,None,None)[0],"INCONCLUSIVE")
 def test_s06_both_eligible_strict_tie(self): self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",False,True,None),("P","P_TIEBREAKER_NOT_PROVEN_FASTER"))
 def test_s07_exact_three_pct_not_tie(self): self.assertFalse(O.within_three_percent(Fraction(100)**8,Fraction(103)**8))
 def test_s08_gm_confirms_p(self):
  g={"P":{c:{"low":1.1} for c in C.CAMP},"H":{c:{"low":0.9} for c in C.CAMP}}; self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",False,False,g),("P","SELECTED_GM_CONFIRMED"))
 def test_s09_gm_confirms_h(self):
  g={"P":{c:{"low":0.9} for c in C.CAMP},"H":{c:{"low":1.1} for c in C.CAMP}}; self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",False,False,g),("H","SELECTED_GM_CONFIRMED"))
 def test_s10_gm_not_proven(self): self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",False,False,None),("INCONCLUSIVE","K_INCONCLUSIVE_P_VS_H"))
 def test_s11_gm_bootstrap_seed_and_pairing(self):
  slots={}
  for lid in O.required_lanes(K):
   for c in C.CAMP: slots[(c,lid)]={"retained":list(range(1,13)),"block":{"P":{b:100 for b in range(1,13)},"H":{b:110 for b in range(1,13)}}}
  a=O.gm_bootstrap_ci_from_original_slots(slots,C.CAMP[0],K,"H","P"); b=O.gm_bootstrap_ci_from_original_slots(slots,C.CAMP[0],K,"H","P"); self.assertEqual(a,b); self.assertEqual(a[2],int.from_bytes(__import__("hashlib").sha256(f"{C.R3_SHA}|{C.CAMP[0]}|k{K}|GM|H/P".encode()).digest()[:8],'big')); self.assertAlmostEqual(a[0],1.1)

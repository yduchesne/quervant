import unittest
from fractions import Fraction
from . import oracle as O
from . import constants as C
from . import fixture_factory as F
class Base(unittest.TestCase):
 k=256
 def rows(self,**kw): return F.full(self.k,**kw)
 def camp(self,rows,c="d3c-v3r3-strategies-01"): return O.evaluate_campaign_candidate(rows,c,self.k,"P",0)
class B(Base):
 def test_b01_required_lanes_count(self): self.assertEqual(len(O.required_lanes(256)),8)
 def test_b02_required_order(self): self.assertTrue(O.required_lanes(1)[0].startswith("pr15d_v1/10000/absent"))
 def test_b03_exact_decimal(self): self.assertEqual(O.exact_decimal(0.1),Fraction(1,10))
 def test_b04_exact_rejects_bool(self):
  with self.assertRaises(O.PolicyInputError): O.exact_decimal(True)
 def test_b05_exact_rejects_nan(self):
  with self.assertRaises(O.PolicyInputError): O.exact_decimal(float("nan"))
 def test_b06_eligible(self): self.assertEqual(self.camp(self.rows())["status"],"ELIGIBLE")
 def test_b07_no_primary_gain(self):
  r=self.rows(rcand=0.99); rec=r["pr15d_v1/100000/medium/k256"]["campaigns"]["d3c-v3r3-strategies-01"]; rec["CI_P_A"]={"low":0.98,"high":0.999}; self.assertEqual(self.camp(r)["status"],"INELIGIBLE")
 def test_b08_target_ci_uncertain(self):
  r=self.rows(); rec=r["pr15d_v1/100000/medium/k256"]["campaigns"]["d3c-v3r3-strategies-01"]; rec["R_P_A"]=0.975; rec["CI_P_A"]={"low":0.96,"high":1.001}; self.assertEqual(self.camp(r)["status"],"INCONCLUSIVE")
 def test_b09_guard_regression(self):
  r=self.rows(); lid="pr15d_v1/10000/absent/k256"; rec=r[lid]["campaigns"]["d3c-v3r3-strategies-01"]; rec["R_P_A"]=1.2; rec["CI_P_A"]={"low":1.15,"high":1.3}
  self.assertEqual(self.camp(r)["status"],"INELIGIBLE")
 def test_b10_guard_ci_uncertain(self):
  r=self.rows(); lid="pr15d_v1/10000/rare/k256"; rec=r[lid]["campaigns"]["d3c-v3r3-strategies-01"]; rec["R_P_A"]=1.05; rec["CI_P_A"]={"low":1.01,"high":1.12}
  self.assertEqual(self.camp(r)["status"],"INCONCLUSIVE")
 def test_b11_attribution_fail(self): self.assertEqual(self.camp(self.rows(sl=1.01))["status"],"INELIGIBLE")
 def test_b12_attribution_ci(self):
  r=self.rows();
  for cls in ("medium","common"):
   rec=r[f"pr15d_v1/100000/{cls}/k256"]["campaigns"]["d3c-v3r3-strategies-01"]; rec["R_P_L"]=0.99; rec["CI_P_L"]={"low":0.97,"high":0.999}
  self.assertEqual(self.camp(r)["status"],"INCONCLUSIVE")
 def test_b13_memory_boundary_equal(self): self.assertEqual(O.evaluate_campaign_candidate(self.rows(),"d3c-v3r3-strategies-01",256,"H",C.H_LIMIT_BYTES)["status"],"ELIGIBLE")
 def test_b14_memory_over(self): self.assertEqual(O.evaluate_campaign_candidate(self.rows(),"d3c-v3r3-strategies-01",256,"H",C.H_LIMIT_BYTES+1)["status"],"INELIGIBLE")
 def test_b15_insufficient_blocks(self): self.assertEqual(self.camp(self.rows(ret=3))["status"],"INCONCLUSIVE")
 def test_b16_filter_sensitive(self): self.assertEqual(self.camp(self.rows(sens=True))["status"],"INCONCLUSIVE")
class S(Base):
 def test_s01_combine_both_eligible(self):
  a=self.camp(self.rows()); self.assertEqual(O.combine_campaign_candidate(a,a)["status"],"ELIGIBLE")
 def test_s02_decisive_overrides_uncertain(self):
  a=self.camp(self.rows()); b=self.camp(self.rows(rcand=0.99)); self.assertEqual(O.combine_campaign_candidate(a,b)["status"],"INELIGIBLE")
 def test_s03_tie_strict(self):
  p=O.worst_campaign_gm_product(self.rows(),"P",256); self.assertTrue(O.within_three_percent(p,p))
 def test_s04_exact_three_percent_not_tie(self):
  p=Fraction(100); h=p*Fraction(103,100)**8; self.assertFalse(O.within_three_percent(p,h))
 def test_s05_select_linear(self): self.assertEqual(O.select_k("INELIGIBLE","INELIGIBLE",False,None,None)[0],"LINEAR_BASE")
 def test_s06_select_p(self): self.assertEqual(O.select_k("ELIGIBLE","INELIGIBLE",False,None,None)[0],"P")
 def test_s07_select_h(self): self.assertEqual(O.select_k("INELIGIBLE","ELIGIBLE",False,None,None)[0],"H")
 def test_s08_tie_prefers_p(self): self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",False,True,None),("P","P_TIEBREAKER_NOT_PROVEN_FASTER"))
 def test_s09_confirmed_p(self):
  g={"P":{c:{"low":1.1} for c in C.CAMP},"H":{c:{"low":0.9} for c in C.CAMP}}; self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",False,False,g)[0],"P")
 def test_s10_confirmed_h(self):
  g={"P":{c:{"low":0.9} for c in C.CAMP},"H":{c:{"low":1.1} for c in C.CAMP}}; self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",False,False,g)[0],"H")
 def test_s11_unproven(self): self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",False,False,None),("INCONCLUSIVE","K_INCONCLUSIVE_P_VS_H"))
 def test_s12_filter_sensitive(self): self.assertEqual(O.select_k("ELIGIBLE","ELIGIBLE",True,True,None)[1],"K_INCONCLUSIVE_FILTER_SENSITIVE")
 def test_s13_bootstrap_deterministic(self):
  slots={}
  for lid in O.required_lanes(256):
   for c in C.CAMP:
    slots[(c,lid)]={"retained":list(range(1,13)),"block":{"P":{b:100 for b in range(1,13)},"H":{b:110 for b in range(1,13)}}}
  a=O.gm_bootstrap_ci_from_original_slots(slots,C.CAMP[0],256,"H","P"); b=O.gm_bootstrap_ci_from_original_slots(slots,C.CAMP[0],256,"H","P")
  self.assertEqual(a,b); self.assertAlmostEqual(a[0],1.1)
 def allrows(self):
  rows=[]
  for k in C.KS: rows.extend(F.full(k).values())
  return rows
 def test_s14_derive_nine_len(self):
  self.assertEqual(len(O.derive_nine({"protocol_sha256":C.R3_SHA,"lanes":self.allrows()},{str(k):0 for k in C.KS})),9)
 def test_s15_derive_bad_protocol(self):
  with self.assertRaises(O.PolicyInputError): O.derive_nine({"protocol_sha256":"x","lanes":[]},{})
 def test_s16_derive_rows_keys(self):
  r=O.derive_nine({"protocol_sha256":C.R3_SHA,"lanes":self.allrows()},{str(k):0 for k in C.KS}); self.assertEqual([x["k"] for x in r],list(C.KS))
if __name__=="__main__": unittest.main()

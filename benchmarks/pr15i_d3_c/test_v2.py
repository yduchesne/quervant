import importlib.util, json, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
def load(n,f):
 s=importlib.util.spec_from_file_location(n,os.path.join(HERE,f));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
RUN=load("v2_run","run.py"); VER=load("v2_ver","verify.py"); POL=load("v2_pol","policy.py")
class V2(unittest.TestCase):
 def test_v201_protocol_diff_only_identity(self):
  v1=json.load(open(os.path.join(HERE,"protocol_v3r2.json"))); v2=json.load(open(os.path.join(HERE,"protocol_v3r3.json")))
  diff=[k for k in v1 if v1[k]!=v2[k]]; self.assertEqual(sorted(diff),["campaign_names","control_name","evidence_root_relative"])
  self.assertEqual(v2["official_measurement_retries"],0)
 def test_v202_v2_sha_bound(self):
  self.assertEqual(VER.PROTOCOL_SHA256,RUN.PROTOCOL_SHA256); self.assertEqual(POL.PROTOCOL_SHA256,RUN.PROTOCOL_SHA256)
  self.assertNotEqual(RUN.PROTOCOL_SHA256,json.load(open(os.path.join(HERE,"protocol_v2.json")))["source_base_sha"])
 def test_v203_old_control_rejected(self):
  with self.assertRaises(SystemExit) as c: RUN.cmd_control(type("A",(),{"campaign":"d3c-base-aa-01","out":"x"})())
  self.assertIn("D3C_CAMPAIGN",str(c.exception))
 def test_v204_new_names(self):
  p,_=RUN.load_protocol(); self.assertEqual(p["control_name"],"d3c-v3r3-base-aa-01"); self.assertEqual(p["campaign_names"],["d3c-v3r3-strategies-01","d3c-v3r3-strategies-02"])
 def test_v205_v2_micro_protocol_rewrap(self):
  src=os.path.join(ROOT,"target/pr15i-d3-c/micro-05/micro.json")
  m=json.load(open(src)); self.assertEqual(m["selected_profile"],"P2"); self.assertEqual(m["source_experiment_sha"],RUN.EXPERIMENT_SHA)
if __name__=="__main__": unittest.main()

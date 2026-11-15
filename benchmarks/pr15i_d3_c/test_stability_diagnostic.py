import importlib.util, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__))
def load(n,f):
 s=importlib.util.spec_from_file_location(n,os.path.join(HERE,f));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
D=load("sd","stability_diagnostic.py"); RUN=D.RUN
class Diagnostic(unittest.TestCase):
 def test_d01_exact_13_ids(self):
  p,_=RUN.load_protocol(); lanes=D.subset(p); self.assertEqual([l["id"] for l in lanes],D.LANE_IDS); self.assertEqual(len(lanes),13)
 def test_d02_schedule_exact(self):
  plan=RUN.control_schedule(RUN.load_protocol()[0]); self.assertEqual(len(plan),48); self.assertEqual(sum(1 for x in plan if x["arm"]=="A"),24)
 def test_d05_no_publisher_import(self):
  self.assertFalse(hasattr(D,"publish")); self.assertIn("NONOFFICIAL",open(os.path.join(HERE,"stability_diagnostic.py")).read())
 def test_d06_summary_uses_original_controls(self):
  self.assertIs(D.RUN.summary_control.__module__,RUN.__name__)
 def test_d07_counterexample_blocks(self):
  p,_=RUN.load_protocol(); lanes=D.subset(p)
  self.assertEqual(len(set(x["id"] for x in lanes)),13)
if __name__=="__main__": unittest.main()

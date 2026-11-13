import importlib.util, json, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
spec=importlib.util.spec_from_file_location("d3c_analysis",os.path.join(HERE,"analyze_control.py")); A=importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
D=os.path.join(ROOT,"target/pr15i-d3-c/official/d3c-base-aa-01")
class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(D): raise unittest.SkipTest("preserved A/A evidence unavailable")
        cls.r=A.analyze(D); cls.s=json.load(open(os.path.join(D,"sanitized/summary.json")))
    def test_a01_inventory_exact(self):
        self.assertEqual(len(self.r["ids"]),72); self.assertEqual(len(self.r["slots"]),16)
        self.assertEqual(len({(s["arm"],s["block"],s["position"]) for s in self.r["slots"]}),16)
    def test_a02_lower_middle(self):
        self.assertEqual(A.median4([1,2,3,4]),2); self.assertEqual(A.gate_ratio([1.0,2.0,3.0,4.0]),2.0)
    def test_a03_gate_vs_aggregate_outliers(self):
        x="pr15d_v1/10000/absent/k100"; y="pr15d_v1/10000/rare/k1024"
        self.assertAlmostEqual(self.r["gate"][x],0.7990430622009569)
        self.assertAlmostEqual(self.r["aggregate"][x],0.9008810572687225)
        self.assertAlmostEqual(self.r["gate"][y],0.8389897395422258)
        self.assertAlmostEqual(self.r["aggregate"][y],0.9432612612612613)
    def test_a04_exemption_only_absent_rare_10k(self):
        self.assertTrue(A.is_exempt(10000,"absent")); self.assertTrue(A.is_exempt(10000,"rare"))
        self.assertFalse(A.is_exempt(10000,"medium")); self.assertFalse(A.is_exempt(100000,"absent"))
    def test_a05_percentiles(self):
        self.assertEqual(A.nearest_rank([1,2,3,4,5],95),5); self.assertLessEqual(A.nearest_rank(list(range(72)),95),72)
    def test_a06_matches_preserved_summary_status(self):
        for lid in self.r["ids"]:
            self.assertAlmostEqual(self.r["gate"][lid],sorted(self.s["a_a"]["lanes"][lid]["block_ratios"])[1])
        self.assertEqual(self.s["status"],"MEASUREMENT_BLOCKED")
if __name__=="__main__": unittest.main()

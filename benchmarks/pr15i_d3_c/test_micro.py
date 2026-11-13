import importlib.util, json, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__))
def load(name,file):
    s=importlib.util.spec_from_file_location(name,os.path.join(HERE,file)); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
POLICY=load("m_policy","policy.py"); TP=load("m_tp","test_policy.py")
class Micro(unittest.TestCase):
    def test_m01_grid_shape_and_profile(self):
        m=TP.micro(); self.assertEqual(len(m["records"]),900); self.assertEqual(m["selected_profile"],"P2")
    def test_m02_memory_map_recomputed(self):
        mem=POLICY.validate_micro_memory(TP.micro(),POLICY.load_protocol(),POLICY.EXPERIMENT_SHA)
        self.assertEqual(mem["1024"],1_120_256)
    def test_m03_missing_combination_rejected(self):
        m=TP.micro(); m["records"].pop()
        with self.assertRaises(SystemExit): POLICY.validate_micro_memory(m,POLICY.load_protocol(),POLICY.EXPERIMENT_SHA)
    def test_m04_wrong_profile_rejected(self):
        m=TP.micro(); m["selected_profile"]="P1"
        with self.assertRaises(SystemExit): POLICY.validate_micro_memory(m,POLICY.load_protocol(),POLICY.EXPERIMENT_SHA)
    def test_m05_round_count_rejected(self):
        m=TP.micro(); m["records"][0]["rounds"]=[1]
        with self.assertRaises(SystemExit): POLICY.validate_micro_memory(m,POLICY.load_protocol(),POLICY.EXPERIMENT_SHA)
    def test_m06_map_mismatch_rejected(self):
        m=TP.micro(); m["exact_set_aux_bytes_estimate"]["1024"]+=1
        with self.assertRaises(SystemExit): POLICY.validate_micro_memory(m,POLICY.load_protocol(),POLICY.EXPERIMENT_SHA)
    def test_m07_set_len_over_capacity_rejected(self):
        m=TP.micro(); r=m["records"][0]; r["set_len"]=r["set_capacity"]+1
        with self.assertRaises(SystemExit): POLICY.validate_micro_memory(m,POLICY.load_protocol(),POLICY.EXPERIMENT_SHA)
    def test_m08_guard_boundary(self):
        m=TP.micro(cap1024=1792,key1024=2_097_152-1792*40)
        mem=POLICY.validate_micro_memory(m,POLICY.load_protocol(),POLICY.EXPERIMENT_SHA)
        self.assertEqual(mem["1024"],2_097_152)
if __name__=="__main__": unittest.main()

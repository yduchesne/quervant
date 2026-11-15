import importlib.util, os, tempfile, unittest
HERE=os.path.dirname(os.path.abspath(__file__))
spec=importlib.util.spec_from_file_location("ht",os.path.join(HERE,"host_topology.py")); H=importlib.util.module_from_spec(spec); spec.loader.exec_module(H)
def fake(spec):
    root=tempfile.mkdtemp()
    for cpu,(pkg,core,sib) in spec.items():
        d=os.path.join(root,f"cpu{cpu}","topology"); os.makedirs(d)
        open(os.path.join(d,"physical_package_id"),"w").write(str(pkg))
        open(os.path.join(d,"core_id"),"w").write(str(core))
        open(os.path.join(d,"thread_siblings_list"),"w").write(sib)
    return root
class Topology(unittest.TestCase):
    def test_h01_same_package_lowest(self):
        r=fake({0:(0,0,"0"),1:(0,1,"1")}); p=H.select_pair([0,1],r); self.assertEqual((p["adapter_cpu"],p["controller_cpu"]),(0,1))
    def test_h02_smt_siblings_excluded(self):
        r=fake({0:(0,0,"0,1"),1:(0,0,"0,1"),2:(0,1,"2")}); p=H.select_pair([0,1,2],r); self.assertEqual(p["adapter"]["core_id"],0); self.assertEqual(p["controller"]["core_id"],1)
    def test_h03_multiple_packages_same_package_first(self):
        r=fake({0:(0,0,"0"),1:(0,1,"1"),2:(1,0,"2"),3:(1,1,"3")}); p=H.select_pair([0,1,2,3],r); self.assertEqual((p["adapter_cpu"],p["controller_cpu"]),(0,1)); self.assertEqual(p["package_id"],0)
    def test_h04_single_core_hard_stop(self):
        r=fake({0:(0,0,"0"),1:(0,0,"0,1")})
        with self.assertRaises(H.TopologyError): H.select_pair([0,1],r)
    def test_h05_missing_topology_hard_stop(self):
        r=fake({0:(0,0,"0")}); os.remove(os.path.join(r,"cpu0","topology","core_id"))
        with self.assertRaises(H.TopologyError): H.select_pair([0],r)
    def test_h06_audit_pair_metadata(self):
        r=fake({0:(0,0,"0"),1:(0,1,"1"),2:(0,2,"2")}); p=H.select_pair([0,1,2],r)
        self.assertTrue(p["distinct_cores"]); self.assertEqual(p["controller"]["thread_siblings"],"1")
if __name__=="__main__": unittest.main()

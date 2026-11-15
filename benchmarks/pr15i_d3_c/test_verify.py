import copy, importlib.util, json, os, shutil, subprocess, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
def load(name,file):
    s=importlib.util.spec_from_file_location(name,os.path.join(HERE,file)); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
RUN=load("v_run","run.py"); REPLAY=load("v_replay","replay.py"); P=RUN.load_protocol()[0]
BASE=os.path.join(ROOT,RUN.TARGET_REL,"test-verify")
def verify(root):
    r=subprocess.run([sys.executable,os.path.join(HERE,"verify.py"),"--series-root",root],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    return r.returncode,json.loads(r.stdout)
def build(root):
    if os.path.exists(root): shutil.rmtree(root)
    dp_path=os.path.join(ROOT,RUN.TARGET_REL,"dry-proof","dry-proof.json")
    if not os.path.isfile(dp_path): raise unittest.SkipTest("dry-proof unavailable")
    dp=json.load(open(dp_path))
    for kind,camp in (("control",P["control_name"]),("four_arm",P["campaign_names"][0]),("four_arm",P["campaign_names"][1])):
        d=REPLAY.build_fixture(root,kind,camp,dp); REPLAY.fix_paths(d)
    return root
class Series(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=build(BASE+"-base")
    def case(self,name):
        d=os.path.join(BASE+"-case-"+name); shutil.rmtree(d,ignore_errors=True); shutil.copytree(self.root,d)
        for camp in [P["control_name"]]+P["campaign_names"]:
            REPLAY.fix_paths(os.path.join(d,camp))
        return d
    def manifest(self,d,name): return json.load(open(os.path.join(d,name,"manifest.json")))
    def save_manifest(self,d,name,m): json.dump(m,open(os.path.join(d,name,"manifest.json"),"w"))
    def test_v01_valid_series_provenance(self):
        code,rep=verify(self.root)
        self.assertEqual(code,3,rep); self.assertEqual(rep["verification"],"PASS"); self.assertTrue(rep["provenance_consistent"]); self.assertFalse(rep["full_series"])
    def test_v02_control_base_only(self):
        d=self.case("control-exp"); m=self.manifest(d,P["control_name"]); m["source_experiment_sha"]=RUN.EXPERIMENT_SHA; self.save_manifest(d,P["control_name"],m); REPLAY.reseal(os.path.join(d,P["control_name"]))
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_SERIES_PROVENANCE")
    def test_v03_four_arm_source_mismatch(self):
        d=self.case("src"); name=P["campaign_names"][0]; m=self.manifest(d,name); m["source_experiment_sha"]="0"*40; self.save_manifest(d,name,m); REPLAY.reseal(os.path.join(d,name))
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_SOURCE")
    def test_v04_host_identity_mismatch(self):
        d=self.case("host"); c=P["control_name"]; h=json.load(open(os.path.join(d,c,"raw/host-attestation.json"))); h["host_fingerprint"]="other"; json.dump(h,open(os.path.join(d,c,"raw/host-attestation.json"),"w"))
        rp=os.path.join(d,c,"raw/host-readiness.json"); r=json.load(open(rp)); r["host_fingerprint"]="other"; json.dump(r,open(rp,"w"))
        m=self.manifest(d,c); m["host_fingerprint"]="other"; m["host_attestation_sha256"]=RUN.sf(os.path.join(d,c,"raw/host-attestation.json")); m["host_readiness_sha256"]=RUN.sf(rp); self.save_manifest(d,c,m); REPLAY.reseal(os.path.join(d,c))
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_SERIES_PROVENANCE")
    def test_v05_binary_provenance(self):
        d=self.case("bin"); name=P["campaign_names"][0]; p=os.path.join(d,name,"raw/build-provenance.json"); b=json.load(open(p)); b["events"][0]["binary_sha256"]="f"*64; json.dump(b,open(p,"w"))
        m=self.manifest(d,name); m["build_provenance_sha256"]=RUN.sf(p); self.save_manifest(d,name,m); REPLAY.reseal(os.path.join(d,name))
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_BINARY")
    def test_v06_readiness_status(self):
        d=self.case("ready"); c=P["control_name"]; p=os.path.join(d,c,"raw/host-readiness.json"); r=json.load(open(p)); r["readiness_status"]="HOST_NOT_READY"; json.dump(r,open(p,"w"))
        m=self.manifest(d,c); m["host_readiness_sha256"]=RUN.sf(p); self.save_manifest(d,c,m); REPLAY.reseal(os.path.join(d,c))
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_READINESS")
    def test_v07_affinity(self):
        d=self.case("aff"); c=P["control_name"]; p=os.path.join(d,c,"raw/slots/slot-01.json"); s=json.load(open(p)); s["lanes"][0]["affinity_before"]=[9]; json.dump(s,open(p,"w")); REPLAY.reseal(os.path.join(d,c))
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_AFFINITY")
        REPLAY.reseal(os.path.join(d,c)); # altered without seal update must fail; now checksum is refreshed below
    def test_v08_sample_count(self):
        d=self.case("sample"); c=P["control_name"]; p=os.path.join(d,c,"raw/slots/slot-01.json"); s=json.load(open(p)); s["lanes"][0]["samples_ns"].pop(); json.dump(s,open(p,"w")); REPLAY.reseal(os.path.join(d,c))
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_SAMPLE")
    def test_v09_oracle(self):
        d=self.case("oracle"); c=P["control_name"]; p=os.path.join(d,c,"raw/slots/slot-01.json"); s=json.load(open(p)); s["lanes"][0]["total_hits"]+=1; json.dump(s,open(p,"w")); REPLAY.reseal(os.path.join(d,c))
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_ORACLE")
    def test_v10_campaign_order(self):
        d=self.case("order"); a=os.path.join(d,P["campaign_names"][0]); b=os.path.join(d,P["campaign_names"][1]); os.rename(a,a+"-x"); os.rename(b,a); os.rename(a+"-x",b)
        code,rep=verify(d); self.assertNotEqual(code,0); self.assertEqual(rep["reasons"][0]["code"],"V_SOURCE")
if __name__=="__main__": unittest.main()

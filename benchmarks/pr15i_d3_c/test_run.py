import hashlib, importlib.util, json, os, shutil, tarfile, unittest
from unittest import mock
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
def load(name,file):
    s=importlib.util.spec_from_file_location(name,os.path.join(HERE,file)); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
RUN=load("r_run","run.py")
BASE=os.path.join(ROOT,RUN.TARGET_REL,"test-run")
def sf(p): return hashlib.sha256(open(p,"rb").read()).hexdigest()
def make(d,campaign="d3c-base-aa-01"):
    shutil.rmtree(d,ignore_errors=True); os.makedirs(os.path.join(d,"raw"))
    files={"manifest.json":json.dumps({"campaign":campaign}),
           "authorization.json":json.dumps({"rehearsal_only":False}),
           "raw/x.json":json.dumps({"x":1}),
           "verification.json":json.dumps({"verification":"PASS"})}
    for rel,text in files.items(): open(os.path.join(d,rel),"w").write(text)
    seal={"schema":"pr15i-d3c-seal-v1","kind":"control","files":{r:sf(os.path.join(d,r)) for r in files if r!="verification.json"}}
    json.dump(seal,open(os.path.join(d,"raw/seal.json"),"w"))
    members=[r for r in RUN.archive_members(d) if os.path.isfile(os.path.join(d,r))]
    arc=os.path.join(d,"archive.tar.gz"); side=arc+".sha256"
    with tarfile.open(arc,"w:gz") as t:
        for rel in members:
            info=t.gettarinfo(os.path.join(d,rel),arcname=rel); info.uid=info.gid=0; info.uname=info.gname=""
            with open(os.path.join(d,rel),"rb") as f: t.addfile(info,f)
    json.dump({"schema":"pr15i-d3c-archive-v1","campaign":campaign,"archive_sha256":sf(arc),
               "member_count":len(members),"members":{r:sf(os.path.join(d,r)) for r in members}},open(side,"w"))
    return d,arc,side
class Archive(unittest.TestCase):
    def setUp(self): self.d,self.arc,self.side=make(os.path.join(BASE,self._testMethodName))
    def test_v40_valid_archive(self):
        rec=RUN.validate_archive(self.arc,self.side,"d3c-base-aa-01",self.d); self.assertEqual(rec["member_count"],5)
    def test_v41_archive_digest(self):
        s=json.load(open(self.side)); s["archive_sha256"]="0"*64; json.dump(s,open(self.side,"w"))
        with self.assertRaises(SystemExit) as c: RUN.validate_archive(self.arc,self.side,"d3c-base-aa-01",self.d)
        self.assertIn("D3C_PREDECESSOR",str(c.exception))
    def test_v42_member_hash(self):
        s=json.load(open(self.side)); s["members"]["manifest.json"]="0"*64; json.dump(s,open(self.side,"w"))
        with self.assertRaises(SystemExit) as c: RUN.validate_archive(self.arc,self.side,"d3c-base-aa-01",self.d)
        self.assertIn("D3C_PREDECESSOR",str(c.exception))
    def test_v43_extra_member(self):
        extra=os.path.join(self.d,"intruder"); open(extra,"w").write("x")
        with tarfile.open(self.arc,"r:gz") as src, tarfile.open(self.arc+".new","w:gz") as dst:
            for m in src.getmembers(): dst.addfile(m,src.extractfile(m))
            dst.add(extra,arcname="intruder")
        os.replace(self.arc+".new",self.arc)
        with self.assertRaises(SystemExit) as c: RUN.validate_archive(self.arc,self.side,"d3c-base-aa-01",self.d)
        self.assertIn("D3C_PREDECESSOR",str(c.exception))
    def test_v44_missing_sidecar(self):
        os.remove(self.side)
        with self.assertRaises(SystemExit) as c: RUN.validate_archive(self.arc,self.side,"d3c-base-aa-01",self.d)
        self.assertIn("D3C_PREDECESSOR",str(c.exception))
    def test_v45_substituted_archive(self):
        other=os.path.join(self.d,"other.tar.gz"); open(other,"wb").write(b"not a tar")
        with self.assertRaises(SystemExit) as c: RUN.validate_archive(other,self.side,"d3c-base-aa-01",self.d)
        self.assertIn("D3C_PREDECESSOR",str(c.exception))
    def test_v46_wrong_campaign(self):
        with self.assertRaises(SystemExit) as c: RUN.validate_archive(self.arc,self.side,"d3c-strategies-01",self.d)
        self.assertIn("D3C_PREDECESSOR",str(c.exception))
if __name__=="__main__": unittest.main()

class PublishGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.replay=load("rg_replay","replay.py")
        cls.root=os.path.join(ROOT,RUN.TARGET_REL,"test-publish")
        shutil.rmtree(cls.root,ignore_errors=True)
        dp_path=os.path.join(ROOT,RUN.TARGET_REL,"dry-proof","dry-proof.json")
        if not os.path.isfile(dp_path): raise unittest.SkipTest("dry-proof unavailable")
        cls.dp=json.load(open(dp_path))
    def fixture(self,name):
        d=os.path.join(self.root,name)
        if os.path.exists(d): shutil.rmtree(d)
        d=self.replay.build_fixture(self.root,"control","d3c-base-aa-01" if False else "d3c-base-aa-01",self.dp) if False else self.replay.build_fixture(os.path.join(self.root,name),"control","d3c-base-aa-01",self.dp)
        self.replay.fix_paths(d)
        ap=os.path.join(d,"authorization.json"); auth=json.load(open(ap)); auth["rehearsal_only"]=False; json.dump(auth,open(ap,"w"))
        self.replay.reseal(d)
        return d
    def publish(self,d,ev):
        return RUN.main(["publish","--campaign-dir",d,"--evidence-root",ev])
    def test_pub01_relabelled_synthetic_is_accepted_today(self):
        # Regression fixture for the open publication-integrity defect: flipping
        # the mutable rehearsal flag makes synthetic replay evidence publish.
        d=self.fixture("relabelled-flag"); ev=os.path.join(self.root,"ev-relabelled-flag")
        self.publish(d,ev)
        self.assertTrue(os.path.isfile(os.path.join(ev,"d3c-base-aa-01.tar.gz")))
        self.assertTrue(os.path.isfile(os.path.join(ev,"d3c-base-aa-01.tar.gz.sha256")))
    def test_pub02_relabelled_host_markers_still_accepted(self):
        d=self.fixture("relabelled-host"); ev=os.path.join(self.root,"ev-relabelled-host")
        hp=os.path.join(d,"raw/host-attestation.json"); h=json.load(open(hp))
        h.update({"kernel":"6.8.0-generic","cpu_model":"relabelled","recorded_utc":"2026-01-01T00:00:00Z"})
        h["toolchains"]={"rustc":"rustc 1.85.0","cargo":"cargo 1.85.0","python3":"3.12"}
        json.dump(h,open(hp,"w"))
        mp=os.path.join(d,"manifest.json"); m=json.load(open(mp)); m["host_attestation_sha256"]=sf(hp); json.dump(m,open(mp,"w"))
        self.replay.reseal(d)
        self.publish(d,ev)
        self.assertTrue(os.path.isfile(os.path.join(ev,"d3c-base-aa-01.tar.gz")))
    def test_pub03_validation_failure_is_failure_atomic(self):
        d=self.fixture("atomic"); ev=os.path.join(self.root,"ev-atomic")
        with mock.patch.object(RUN,"validate_archive",side_effect=SystemExit("boom")):
            with self.assertRaises(SystemExit): self.publish(d,ev)
        for name in ("d3c-base-aa-01.tar.gz","d3c-base-aa-01.tar.gz.sha256",
                     "d3c-base-aa-01.tar.gz.tmp","d3c-base-aa-01.tar.gz.sha256.tmp"):
            self.assertFalse(os.path.exists(os.path.join(ev,name)),name)
    def test_pub04_duplicate_publication_rejected(self):
        d=self.fixture("duplicate"); ev=os.path.join(self.root,"ev-duplicate")
        self.publish(d,ev); arc=os.path.join(ev,"d3c-base-aa-01.tar.gz"); digest=sf(arc)
        with self.assertRaises(SystemExit) as c: self.publish(d,ev)
        self.assertIn("D3C_ARCHIVE_EXISTS",str(c.exception)); self.assertEqual(sf(arc),digest)
    def _reject(self,name,status,code="D3C_QUALIFICATION"):
        d=self.fixture(name); ev=os.path.join(self.root,"ev-"+name)
        rep={"verification":"PASS","measurement_status":status}
        fake=type("R",(),{"returncode":0,"stdout":json.dumps(rep),"stderr":""})()
        with mock.patch.object(RUN.subprocess,"run",return_value=fake):
            with self.assertRaises(SystemExit) as c: self.publish(d,ev)
        self.assertIn(code,str(c.exception))
        self.assertFalse(os.path.exists(os.path.join(ev,"d3c-base-aa-01.tar.gz")))
        self.assertFalse(os.path.exists(os.path.join(ev,"d3c-base-aa-01.tar.gz.sha256")))
    def test_v48_publish_blocked_rejected(self): self._reject("blocked","MEASUREMENT_BLOCKED")
    def test_v49_publish_synthetic_rejected(self): self._reject("synthetic","SYNTHETIC_REHEARSAL_ONLY")
    def test_v50_publish_unknown_rejected(self): self._reject("unknown","WHATEVER")

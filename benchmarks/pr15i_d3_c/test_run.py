import hashlib, importlib.util, json, os, shutil, tarfile, unittest
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

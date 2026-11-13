import importlib.util, json, os, shutil, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(os.path.dirname(HERE))
def load(name,file):
    s=importlib.util.spec_from_file_location(name,os.path.join(HERE,file)); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
RUN=load("p_run","run.py")
BASE=os.path.join(ROOT,RUN.TARGET_REL,"test-replay")
class Publish(unittest.TestCase):
    def test_rh01_synthetic_publish_refused_without_archive(self):
        d=os.path.join(BASE,"rehearsal-control"); shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
        json.dump({"campaign":"d3c-base-aa-01"},open(os.path.join(d,"manifest.json"),"w"))
        json.dump({"rehearsal_only":True},open(os.path.join(d,"authorization.json"),"w"))
        ev=os.path.join(BASE,"evidence")
        with self.assertRaises(SystemExit) as c:
            RUN.main(["publish","--campaign-dir",d,"--evidence-root",ev])
        self.assertIn("D3C_REHEARSAL_PUBLISH_FORBIDDEN",str(c.exception))
        self.assertFalse(os.path.exists(os.path.join(ev,"d3c-base-aa-01.tar.gz")))
        self.assertFalse(os.path.exists(os.path.join(ev,"d3c-base-aa-01.tar.gz.sha256")))
    def test_rh02_synthetic_path_refused(self):
        d=os.path.join(BASE,"rehearsal"); shutil.rmtree(d,ignore_errors=True); os.makedirs(d,exist_ok=True)
        json.dump({"campaign":"d3c-base-aa-01"},open(os.path.join(d,"manifest.json"),"w"))
        json.dump({"rehearsal_only":False},open(os.path.join(d,"authorization.json"),"w"))
        with self.assertRaises(SystemExit) as c:
            RUN.main(["publish","--campaign-dir",d,"--evidence-root",os.path.join(BASE,"evidence2")])
        self.assertIn("D3C_REHEARSAL_PUBLISH_FORBIDDEN",str(c.exception))
if __name__=="__main__": unittest.main()

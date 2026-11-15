import io,json,shutil,tarfile,unittest
from pathlib import Path
try:
 from . import admission as A
except ImportError:
 import admission as A
try:
 from . import constants as C
except ImportError:
 import constants as C
ROOT=Path(__file__).resolve().parents[2]
SERIES=ROOT/"target/pr15i-d3-c/official-v3r3"; ARCH=Path.home()/".local/share/quervant/benchmark-evidence/pr15i-d3-c-v3r3"
MICRO=ROOT/"target/pr15i-d3-c/micro-05/micro.json"; F1=ROOT/"target/pr15i-d3-c/t7f1-freeze/freeze-receipt.json"; TMP=ROOT/"target/pr15i-d3-c/t7f2-tests/admission"
class TestAdmission(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if TMP.exists(): shutil.rmtree(TMP)
  TMP.mkdir(parents=True)
 def test_a01_original_hashes(self):
  r=A.audit(SERIES,ARCH,MICRO,F1); self.assertEqual(r["status"],"PASS"); self.assertEqual(len(r["archives"]),3)
 def test_a02_archive_replacement_rejected(self):
  with self.assertRaises(A.AdmissionError): A.validate_archive(ARCH,"d3c-v3r3-base-aa-01",SERIES/"d3c-v3r3-strategies-01")
 def test_a03_corrupted_sidecar_rejected(self):
  p=TMP/"side.json"; p.write_text("{}")
  with self.assertRaises(A.AdmissionError): A.validate_archive(p.parent,"x",SERIES)
 def test_a04_tar_traversal_rejected(self):
  p=TMP/"trav.tar.gz"
  with tarfile.open(p,"w:gz") as t:
   i=tarfile.TarInfo("../x"); i.size=1; t.addfile(i,io.BytesIO(b"x"))
  with self.assertRaises(A.AdmissionError): A.safe_members(p)
 def test_a05_t6_receipt_tampering_rejected(self):
  p=TMP/"t6.json"; p.write_text("{}")
  with self.assertRaises(A.AdmissionError): A.validate_f1(p)
 def test_a06_f1_commit_mismatch_rejected(self):
  p=TMP/"f1.json"; p.write_text(open(F1).read()+" ")
  with self.assertRaises(A.AdmissionError): A.validate_f1(p)
 def test_a07_micro_duplicate_combo_rejected(self):
  m=json.load(open(MICRO)); m["records"][-1]=dict(m["records"][0]); p=TMP/"dup.json"; p.write_text(json.dumps(m))
  with self.assertRaises(A.AdmissionError): A.validate_micro(p)
 def test_a08_micro_false_p2_rejected(self):
  m=json.load(open(MICRO)); m["selected_profile"]="P1"; p=TMP/"p1.json"; p.write_text(json.dumps(m))
  with self.assertRaises(A.AdmissionError): A.validate_micro(p)

import io, json, os, shutil, tarfile, tempfile, unittest
from pathlib import Path
from . import admission as A
from . import constants as C
ROOT=Path(__file__).resolve().parents[2]
SERIES=ROOT/"target/pr15i-d3-c/official-v3r3"; ARCH=Path.home()/".local/share/quervant/benchmark-evidence/pr15i-d3-c-v3r3"
MICRO=ROOT/"target/pr15i-d3-c/micro-05/micro.json"; F1=ROOT/"target/pr15i-d3-c/t7f1-freeze/freeze-receipt.json"
TMP=ROOT/"target/pr15i-d3-c/t7f2-tests/admission"
class Admission(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if TMP.exists(): shutil.rmtree(TMP)
  TMP.mkdir(parents=True)
 def test_a01_real_admission_pass(self):
  rec=A.audit(SERIES,ARCH,MICRO,F1); self.assertEqual(rec["status"],"PASS"); self.assertEqual(len(rec["archives"]),3); self.assertEqual(rec["micro"]["H_memory_by_k"]["1024"],1120256)
 def test_a02_duplicate_json_rejected(self):
  p=TMP/"dup.json"; p.write_text('{"a":1,"a":2}')
  with self.assertRaises(A.AdmissionError): A.rj(p)
 def test_a03_unsafe_tar_path(self):
  p=TMP/"unsafe.tar.gz"
  with tarfile.open(p,"w:gz") as t:
   info=tarfile.TarInfo("../x"); info.size=1; t.addfile(info,io.BytesIO(b"x"))
  with self.assertRaises(A.AdmissionError): A.safe_members(p)
 def test_a04_symlink_member_rejected(self):
  p=TMP/"sym.tar.gz"
  with tarfile.open(p,"w:gz") as t:
   info=tarfile.TarInfo("link"); info.type=tarfile.SYMTYPE; info.linkname="target"; t.addfile(info)
  with self.assertRaises(A.AdmissionError): A.safe_members(p)
 def test_a05_micro_missing_record(self):
  m=json.load(open(MICRO)); m["records"].pop(); p=TMP/"micro-missing.json"; p.write_text(json.dumps(m))
  with self.assertRaises(A.AdmissionError): A.validate_micro(p)
 def test_a06_micro_duplicate_substitution(self):
  m=json.load(open(MICRO)); m["records"][-1]=dict(m["records"][0]); p=TMP/"micro-dup.json"; p.write_text(json.dumps(m))
  with self.assertRaises(A.AdmissionError): A.validate_micro(p)
 def test_a07_f1_receipt_digest_rejected(self):
  p=TMP/"f1.json"; p.write_text(open(F1).read()+" ")
  with self.assertRaises(A.AdmissionError): A.validate_f1(p)
 def test_a08_wrong_campaign_archive_rejected(self):
  with self.assertRaises(A.AdmissionError): A.validate_archive(ARCH,"d3c-v3r3-base-aa-01",SERIES/"d3c-v3r3-strategies-01")

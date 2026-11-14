import json,shutil,unittest
from pathlib import Path
try:
 from . import freeze_gate as F
except ImportError:
 import freeze_gate as F
ROOT=Path(__file__).resolve().parents[2]; TMP=ROOT/"target/pr15i-d3-c/t7f2-tests/freeze"
class TestFreeze(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if TMP.exists(): shutil.rmtree(TMP)
  TMP.mkdir(parents=True)
 def test_f01_good_prepared_receipt(self):
  out=TMP/"f01"; F.prepare(out); r=json.load(open(out/"freeze-receipt.json")); self.assertEqual(set(r["files"]),set(F.FILES))
 def test_f02_changed_git_blob_rejected(self):
  out=TMP/"f02"; F.prepare(out); r=json.load(open(out/"freeze-receipt.json")); r["files"]["oracle.py"]="0"*64; p=TMP/"f02.json"; p.write_text(json.dumps(r))
  with self.assertRaises(SystemExit): F.verify(p)
 def test_f03_changed_worktree_byte_rejected(self):
  out=TMP/"f03"; F.prepare(out); r=json.load(open(out/"freeze-receipt.json")); r["files"]["analysis.py"]="0"*64; p=TMP/"f03.json"; p.write_text(json.dumps(r))
  with self.assertRaises(SystemExit): F.verify(p)
 def test_f04_altered_receipt_sha_rejected(self):
  p=TMP/"f04.json"; p.write_text('{"t7f2_commit":"deadbeef","files":{}}')
  with self.assertRaises(SystemExit): F.verify(p)
 def test_f05_missing_qa_manifest_rejected(self):
  with self.assertRaises(SystemExit): F.verify(TMP/"nope.json")
 def test_f06_missing_test_file_rejected(self):
  out=TMP/"f06"; F.prepare(out); r=json.load(open(out/"freeze-receipt.json")); r["files"].pop("test_oracle.py"); p=TMP/"f06.json"; p.write_text(json.dumps(r))
  with self.assertRaises(SystemExit): F.verify(p)

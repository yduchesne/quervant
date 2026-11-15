import unittest
try:
 from . import acceptance_gate as A
except ImportError:
 import acceptance_gate as A
try:
 from . import constants as C
except ImportError:
 import constants as C
def res(n=60,ok=True,skip=None,xfail=None,unexpected=None):
 class R: pass
 r=R(); r.testsRun=n; r.wasSuccessful=lambda:ok; r.skipped=skip or []; r.expectedFailures=xfail or []; r.unexpectedSuccesses=unexpected or []; r.failures=[] if ok else [("x","y")]; r.errors=[]; return r
class TestAcceptance(unittest.TestCase):
 def test_g01_missing_named_test_fails(self):
  with self.assertRaises(SystemExit): A.check_result(res(0,False))
 def test_g02_skipped_test_fails(self):
  with self.assertRaises(SystemExit): A.check_result(res(60,True,skip=[("x","y")]))
 def test_g03_zero_tests_fails(self):
  with self.assertRaises(SystemExit): A.check_result(res(0,True))
 def test_g04_xfail_fails(self):
  with self.assertRaises(SystemExit): A.check_result(res(60,True,xfail=[("x","y")]))
 def test_g05_source_digest_change_fails(self):
  with self.assertRaises(SystemExit): A.check_source(["missing.py"])
 def test_g06_missing_qa_command_fails(self):
  with self.assertRaises(SystemExit): A.check_qa([["false"]])

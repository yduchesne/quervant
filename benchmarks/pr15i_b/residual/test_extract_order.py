"""Deterministic tests for the residual order-diagnostic tool."""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


class ExtractOrderTests(unittest.TestCase):
    def test_out_path_must_be_confined(self):
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "extract_order.py"),
             "--checkout-root", ROOT, "--campaign", "/tmp/does-not-exist",
             "--out", "/tmp/escape"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target/pr15i-b/residual/diagnostics", result.stderr)

    def test_existing_output_is_refused(self):
        out = os.path.join(ROOT, "target", "pr15i-b", "residual", "diagnostics", "unit-existing")
        os.makedirs(out, exist_ok=True)
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "extract_order.py"),
             "--checkout-root", ROOT, "--campaign", "/tmp/does-not-exist",
             "--out", out],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exists", result.stderr)


if __name__ == "__main__":
    unittest.main()

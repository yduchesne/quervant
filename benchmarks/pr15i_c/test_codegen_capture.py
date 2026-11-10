#!/usr/bin/env python3
"""PR 15I-C fixup — codegen capture wrapper tests."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    spec = importlib.util.spec_from_file_location(
        "pr15i_c_codegen_capture", os.path.join(HERE, "codegen_capture.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = load()


def fake_binary(directory, name, payload):
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(payload)
    return path


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


class CaptureTests(unittest.TestCase):
    def test_hashes_are_recorded_and_binaries_unmodified(self):
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "out")
            baseline = fake_binary(directory, "a.bin", b"\x7fELF-a")
            control = fake_binary(directory, "g.bin", b"\x7fELF-g")
            candidate = fake_binary(directory, "b.bin", b"\x7fELF-b")
            before = {path: digest(path) for path in (baseline, control, candidate)}
            capture.capture(baseline, control, candidate, out)
            after = {path: digest(path) for path in (baseline, control, candidate)}
            self.assertEqual(before, after)
            record = json.load(open(os.path.join(out, "codegen-capture.json"),
                                    encoding="utf-8"))
            self.assertEqual(record["schema"], capture.SCHEMA)
            self.assertEqual(record["candidate_status"], "COMPLETE")
            for arm in record["arms"]:
                self.assertEqual(arm["state"], "CAPTURED")
                self.assertEqual(len(arm["binary_sha256"]), 64)

    def test_missing_candidate_is_labelled_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "out")
            baseline = fake_binary(directory, "a.bin", b"\x7fELF-a")
            control = fake_binary(directory, "g.bin", b"\x7fELF-g")
            capture.capture(baseline, control, None, out)
            record = json.load(open(os.path.join(out, "codegen-capture.json"),
                                    encoding="utf-8"))
            self.assertEqual(record["candidate_status"], "CANDIDATE_PENDING")
            states = {arm["arm"]: arm["state"] for arm in record["arms"]}
            self.assertEqual(states["B"], "BINARY_MISSING")

    def test_missing_binary_path_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "out")
            baseline = fake_binary(directory, "a.bin", b"\x7fELF-a")
            missing = os.path.join(directory, "nope.bin")
            capture.capture(baseline, missing, None, out)
            record = json.load(open(os.path.join(out, "codegen-capture.json"),
                                    encoding="utf-8"))
            states = {arm["arm"]: arm["state"] for arm in record["arms"]}
            self.assertEqual(states["G"], "BINARY_MISSING")

    def test_tool_unavailable_is_typed(self):
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "out")
            baseline = fake_binary(directory, "a.bin", b"\x7fELF-a")
            with mock.patch.object(capture.shutil, "which", return_value=None):
                capture.capture(baseline, None, None, out)
            record = json.load(open(os.path.join(out, "codegen-capture.json"),
                                    encoding="utf-8"))
            self.assertEqual(record["tools"]["nm"], "TOOL_UNAVAILABLE")
            self.assertEqual(record["perf"]["state"], "PERF_UNAVAILABLE")
            self.assertEqual(record["arms"][0]["symbols"]["nm"]["state"],
                             "TOOL_UNAVAILABLE")

    def test_existing_output_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "out")
            os.makedirs(out)
            with open(os.path.join(out, "codegen-capture.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({}, handle)
            baseline = fake_binary(directory, "a.bin", b"\x7fELF-a")
            with self.assertRaises(SystemExit):
                capture.capture(baseline, None, None, out)

    def test_no_dependency_on_unavailable_tools(self):
        with open(os.path.join(HERE, "codegen_capture.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("TOOL_UNAVAILABLE", source)
        self.assertIn("PERF_UNAVAILABLE", source)
        self.assertNotIn("pip install", source)


if __name__ == "__main__":
    unittest.main()

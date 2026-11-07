#!/usr/bin/env python3
"""Deterministic tests for ``benchmarks/pr15i_0/summarize.py``.

Publication is exercised against a controlled temporary repository that carries
the *same* identity rules as the CLI: a real qualified verification produced by
the real verifier, four campaigns sealed for the frozen measured source, a
complete QA record bound to the controller bytes and all twelve report targets.

Synthetic fixtures never become benchmark evidence; they only prove the
controller and publication contracts.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import summarize  # noqa: E402  (module under test)
import verify  # noqa: E402  (sibling controller used by the contract)


def load_fixtures():
    spec = importlib.util.spec_from_file_location(
        "pr15i0_verify_fixtures", os.path.join(HERE, "test_verify.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIXTURES = load_fixtures()
FROZEN_SOURCE = summarize.FROZEN_MEASURED_SOURCE_SHA


class Args:
    def __init__(self, values):
        self.__dict__.update(values)


def parse(argv):
    values = {}
    index = 0
    while index < len(argv):
        key = argv[index].lstrip("-").replace("-", "_")
        values[key] = argv[index + 1]
        index += 2
    return Args(values)


def build_tree():
    """Create a fixture repository plus a genuinely qualified verification."""
    root, paths = FIXTURES.build_root(source=FROZEN_SOURCE)
    saved_git = verify.git
    saved_run = verify.run_command
    saved_source = FIXTURES.ACTIVE_SOURCE
    verify.git = FIXTURES.FakeGit(head=FROZEN_SOURCE)
    verify.run_command = FIXTURES.fake_run_command
    FIXTURES.ACTIVE_SOURCE = FROZEN_SOURCE
    try:
        for label in ("pr15d", "prepared", "pr15f", "mutation"):
            verify.seal_campaign(
                paths[label],
                FROZEN_SOURCE,
                "QUALIFIED",
                {
                    "protocol_sha256": FIXTURES.sha_of_protocol(root),
                    "corpus_manifest_sha256": FIXTURES.CORPUS_MANIFEST,
                },
            )
        verification_path = os.path.join(root, "target", "pr15i-0", "verification-01.json")
        argv = [
            "--root",
            root,
            "--source-sha",
            FROZEN_SOURCE,
            "--pr15d-run",
            paths["pr15d"],
            "--pr15f-run",
            paths["pr15f"],
            "--pr15f-prepared",
            paths["prepared"],
            "--mutation-run",
            paths["mutation"],
            "--out",
            verification_path,
        ]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = verify.verification_main(argv)
    finally:
        verify.git = saved_git
        verify.run_command = saved_run
        FIXTURES.ACTIVE_SOURCE = saved_source
    if code != 0:
        raise AssertionError(f"fixture verification did not qualify (exit {code})")
    verification = verify.read_json(verification_path)
    return root, paths, verification_path, verification


class TreeTestCase(unittest.TestCase):
    def setUp(self):
        (
            self.root,
            self.paths,
            self.verification_path,
            self.verification,
        ) = build_tree()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # -- helpers -----------------------------------------------------------

    def outputs(self):
        return {
            "out_json": os.path.join(
                self.root, *summarize.OUTPUT_REL_PATHS["out_json"].split("/")
            ),
            "out_md": os.path.join(
                self.root, *summarize.OUTPUT_REL_PATHS["out_md"].split("/")
            ),
        }

    def argv(self, verification=None, **overrides):
        out = self.outputs()
        values = {
            "--root": self.root,
            "--verification": verification or self.verification_path,
            "--pr15d-run": self.paths["pr15d"],
            "--pr15f-run": self.paths["pr15f"],
            "--pr15f-prepared": self.paths["prepared"],
            "--mutation-run": self.paths["mutation"],
            "--out-json": out["out_json"],
            "--out-md": out["out_md"],
        }
        values.update({f"--{key.replace('_', '-')}": value for key, value in overrides.items()})
        argv = []
        for key, value in values.items():
            argv.extend([key, value])
        return argv

    def publish(self, verification=None, **overrides):
        with contextlib.redirect_stdout(io.StringIO()):
            return summarize.run(parse(self.argv(verification, **overrides)))

    def snapshot_outputs(self):
        state = {}
        for relative in (
            summarize.OUTPUT_REL_PATHS["out_json"],
            summarize.OUTPUT_REL_PATHS["out_md"],
            *summarize.IMPLICIT_OUTPUT_REL_PATHS,
        ):
            path = os.path.join(self.root, *relative.split("/"))
            state[relative] = summarize.sha256_file(path) if os.path.isfile(path) else None
        return state

    def rewrite_verification(self, mutate):
        payload = verify.read_json(self.verification_path)
        mutate(payload)
        FIXTURES.write_json(self.verification_path, payload)
        return payload

    def read_summary(self):
        return verify.read_json(
            os.path.join(self.root, *summarize.OUTPUT_REL_PATHS["out_json"].split("/"))
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class HelperTests(unittest.TestCase):
    def test_median_is_lower_middle_for_even_samples(self):
        self.assertEqual(summarize.median_int([3, 1, 2]), 2)
        self.assertEqual(summarize.median_int([4, 1, 3, 2]), 3)

    def test_median_rejects_empty(self):
        with self.assertRaises(summarize.SummaryError):
            summarize.median_int([])

    def test_ratio_returns_none_on_zero_denominator(self):
        self.assertIsNone(summarize.ratio(1, 0))
        self.assertIsNone(summarize.ratio(None, 1))

    def test_rounded_uses_three_places_but_keeps_precision_upstream(self):
        self.assertEqual(summarize.rounded(1.23456), 1.235)
        self.assertEqual(summarize.rounded(2.0 / 3.0), 0.667)
        self.assertIsNone(summarize.rounded(None))

    def test_not_comparable_shape(self):
        self.assertEqual(summarize.not_comparable("reason")["status"], "NOT_COMPARABLE")
        self.assertEqual(summarize.not_comparable("reason")["reason"], "reason")

    def test_canonical_json_is_sorted_and_compact(self):
        data = summarize.canonical_json_bytes({"b": 1, "a": [2, 3]})
        self.assertEqual(data, b'{"a":[2,3],"b":1}\n')

    def test_report_scan_targets_match_the_verifier_frozen_inventory(self):
        self.assertEqual(len(summarize.REPORT_SCAN_TARGETS), 12)
        self.assertEqual(
            list(summarize.REPORT_SCAN_TARGETS), list(verify.FROZEN_PRIVACY_TARGETS)
        )
        self.assertNotIn("benchmarks/reports/pr15i-0/privacy-scan.json", summarize.REPORT_SCAN_TARGETS)
        self.assertEqual(len(verify.FROZEN_PRIVACY_TARGETS), 12)
        self.assertEqual(
            len(set(verify.FROZEN_PRIVACY_TARGETS)), len(verify.FROZEN_PRIVACY_TARGETS)
        )


# ---------------------------------------------------------------------------
# Derived formulas (unchanged arithmetic)
# ---------------------------------------------------------------------------


class DerivationTests(TreeTestCase):
    def setUp(self):
        super().setUp()
        self.derived = summarize.derive(
            self.verification,
            self.paths["pr15d"],
            self.paths["pr15f"],
            self.paths["mutation"],
        )

    def test_index_bytes_are_the_trial_median_not_a_historical_value(self):
        for n in (10000, 100000):
            self.assertEqual(
                self.derived["index_bytes"][str(n)]["bytes"]["quervant"], 1000 * n + 8
            )
            self.assertEqual(
                self.derived["index_bytes"][str(n)]["bytes"]["tantivy"], 1000 * n + 7
            )
        self.assertNotEqual(
            self.derived["index_bytes"]["100000"]["bytes"]["quervant"],
            summarize.HISTORICAL["index_bytes_100000"],
        )

    def test_index_ratio_is_quervant_over_comparison(self):
        ratios = self.derived["index_bytes"]["100000"]["ratio_quervant_over"]
        expected = (100000 * 1000 + 8) / (100000 * 1000 + 7)
        self.assertEqual(ratios["tantivy"], summarize.rounded(expected))
        self.assertEqual(
            self.derived["index_bytes"]["100000"]["caveat"],
            "PHYSICAL_SEGMENT_SCHEMA_DIFFERS",
        )

    def test_process_cold_ratio_is_not_comparable(self):
        cold = [
            lane
            for lane in self.derived["latency"].values()
            if lane["regime"] == "process_cold"
        ]
        self.assertTrue(cold)
        for lane in cold:
            self.assertEqual(
                lane["ratio_quervant_over_tantivy"]["status"], "NOT_COMPARABLE"
            )

    def test_warm_ratio_is_computed(self):
        warm = [
            lane
            for lane in self.derived["latency"].values()
            if lane["regime"] == "warm"
        ]
        self.assertEqual(len(warm), 16)
        self.assertTrue(
            all(isinstance(lane["ratio_quervant_over_tantivy"], float) for lane in warm)
        )

    def test_physical_sort_caveat_is_attached_to_every_lane(self):
        for lane in self.derived["latency"].values():
            self.assertEqual(lane["physical_sort_caveat"], "PHYSICAL_SORT_ENCODING_DIFFERS")

    def test_section_shares_use_the_committed_index_total(self):
        summary = dict(self.derived)
        summarize.attach_sections(summary, self.paths["pr15f"])
        entry = summary["sections"]["100000"]
        total = entry["total_file_bytes"]
        for kind, section in entry["sections"].items():
            self.assertEqual(section["bytes"], {"Stored": 10, "Postings": 5}[kind])
            self.assertAlmostEqual(
                section["share_of_index_percent"],
                round(100.0 * section["bytes"] / total, 4),
            )

    def test_sidecar_shares_use_the_sidecar_file_size(self):
        for n in ("10000", "100000"):
            entry = self.derived["mutation"][n]
            total = entry["sidecar_file_bytes"]
            for name, share in entry["component_share_percent"].items():
                self.assertAlmostEqual(
                    share, round(100.0 * entry["component_bytes"][name] / total, 4)
                )
            self.assertEqual(
                entry["saved_bytes_upper_bound_label"], "PHYSICAL_ZERO_BYTE_CEILING_ONLY"
            )

    def test_batch_detail_label_survives_derivation(self):
        for n in ("10000", "100000"):
            self.assertEqual(
                self.derived["mutation"][n]["batch_replay_detail"], "NOT_APPLICABLE"
            )

    def test_unknown_cpu_bucket_is_preserved(self):
        for lane in self.derived["quervant_profile"]["lanes"].values():
            self.assertEqual(lane["unknown_exclusive_percent"], 60.0)

    def test_missing_allocation_is_not_zero(self):
        allocation = self.derived["quervant_profile"]["allocation"]
        self.assertEqual(allocation["status"], "ALLOCATION_NOT_MEASURED")
        self.assertEqual(allocation["captured"], [])

    def test_reopen_ratio_uses_trial_medians(self):
        self.assertEqual(self.derived["reopen"]["100000"]["reopen_ns"]["quervant"], 30)
        self.assertAlmostEqual(
            self.derived["reopen"]["100000"]["ratio_quervant_over_tantivy"], 1.0
        )


class IncompleteGateTests(TreeTestCase):
    def test_ratios_are_not_comparable_when_three_engine_gate_fails(self):
        verification = json.loads(json.dumps(self.verification))
        verification["gates"]["I0-P03"]["status"] = "FAIL"
        verification["qualified"] = False
        derived = summarize.derive(
            verification,
            self.paths["pr15d"],
            self.paths["pr15f"],
            self.paths["mutation"],
        )
        self.assertEqual(
            derived["index_bytes"]["10000"]["ratio_quervant_over"]["status"],
            "NOT_COMPARABLE",
        )
        for lane in derived["latency"].values():
            self.assertEqual(
                lane["ratio_quervant_over_tantivy"]["status"], "NOT_COMPARABLE"
            )


# ---------------------------------------------------------------------------
# RF-02: publication bound to verified evidence (FT-11 … FT-20)
# ---------------------------------------------------------------------------


class BindingTests(TreeTestCase):
    def assert_rejected(self, expected_code, verification=None, **overrides):
        before = self.snapshot_outputs()
        with self.assertRaises(summarize.SummaryError) as context:
            self.publish(verification, **overrides)
        self.assertIn(expected_code, str(context.exception))
        self.assertEqual(self.snapshot_outputs(), before)

    def test_ft11_exact_inputs_publish(self):
        self.assertEqual(self.publish(), 0)
        summary = self.read_summary()
        self.assertEqual(summary["schema"], summarize.SCHEMA_SUMMARY)
        self.assertEqual(summary["source_sha"], FROZEN_SOURCE)
        binding = summary["binding"]
        self.assertEqual(binding["protocol_sha256"], self.verification["protocol"]["sha256"])
        self.assertEqual(
            binding["corpus_manifest_sha256"], FIXTURES.CORPUS_MANIFEST
        )
        self.assertRegex(binding["qa_record"]["sha256"], r"^[0-9a-f]{64}$")
        for label, _flag, _seal in summarize.INPUT_LABELS:
            self.assertRegex(binding["inputs"][label]["seal_sha256"], r"^[0-9a-f]{64}$")

    def test_ft12_substituted_pr15d_campaign_is_rejected(self):
        other = os.path.join(self.root, "target", "pr15d", "runs", "other-01")
        shutil.copytree(self.paths["pr15d"], other)
        self.assert_rejected("RF02_INPUT_MISMATCH", pr15d_run=other)

    def test_ft13_substituted_mutation_campaign_is_rejected(self):
        other = os.path.join(self.root, "target", "pr15i-0", "mutation-01-copy")
        shutil.copytree(self.paths["mutation"], other)
        self.assert_rejected("RF02_INPUT_MISMATCH", mutation_run=other)

    def test_ft14_manifest_byte_change_is_rejected(self):
        target = os.path.join(self.paths["pr15f"], "preflight.json")
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(" ")
        self.assert_rejected("RF02_MANIFEST_HASH")

    def test_ft15_seal_byte_change_is_rejected(self):
        target = os.path.join(self.paths["pr15d"], "seal.json")
        seal = verify.read_json(target)
        seal["campaign"] = "renamed"
        FIXTURES.write_json(target, seal)
        self.assert_rejected("RF02_SEAL")

    def test_ft16_source_or_protocol_drift_is_rejected(self):
        self.rewrite_verification(
            lambda payload: payload.update({"source_sha": "0" * 40})
        )
        self.assert_rejected("RF02_SOURCE")

        self.rewrite_verification(
            lambda payload: payload.update(
                {
                    "source_sha": FROZEN_SOURCE,
                    "protocol": {"sha256": "b" * 64},
                }
            )
        )
        self.assert_rejected("RF02_PROTOCOL")

    def test_ft17_incomplete_identity_graph_is_rejected(self):
        self.rewrite_verification(
            lambda payload: payload["observations"]["inputs"].pop("pr15f_prepared")
        )
        self.assert_rejected("RF02_IDENTITY")

        self.rewrite_verification(
            lambda payload: payload["observations"]["seals"].pop("mutation-run")
        )
        self.assert_rejected("RF02_IDENTITY")

    def test_ft18_unqualified_or_failed_gate_verification_is_rejected(self):
        self.rewrite_verification(lambda payload: payload.update({"qualified": False}))
        self.assert_rejected("RF02_NOT_QUALIFIED")

        def break_gate(payload):
            payload["qualified"] = True
            payload["gates"]["I0-P03"]["status"] = "FAIL"

        self.rewrite_verification(break_gate)
        self.assert_rejected("RF02_GATES")

    def test_ft19_changed_qa_record_is_rejected(self):
        qa_path = os.path.join(self.root, *verify.QA_RECORD_REL.split("/"))
        record = verify.read_json(qa_path)
        record["qa_source_head_sha"] = "f" * 40
        FIXTURES.write_json(qa_path, record)
        self.assert_rejected("RF02_QA")

    def test_ft20_corrupt_verification_is_rejected(self):
        self.rewrite_verification(lambda payload: payload.update({"schema": "other"}))
        self.assert_rejected("RF02_VERIFICATION")

        self.rewrite_verification(
            lambda payload: payload.update(
                {"schema": verify.SCHEMA_VERIFICATION, "test_fixture": True}
            )
        )
        self.assert_rejected("RF02_VERIFICATION")

        self.rewrite_verification(
            lambda payload: payload.pop("controller_version", None)
        )
        self.assert_rejected("RF02_VERIFICATION")

    def test_ft44_missing_gate_is_rejected(self):
        def drop(payload):
            payload["gates"].pop("I0-P05")

        self.rewrite_verification(drop)
        self.assert_rejected("RF02_GATES")

    def test_ft46_changed_sealed_file_blocks_publication(self):
        target = os.path.join(self.paths["pr15d"], "run.json")
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(" ")
        seal_path = os.path.join(self.paths["pr15d"], "seal.json")
        seal_before = verify.sha256_file(seal_path)
        self.assert_rejected("RF02_MANIFEST_HASH")
        # The sealed evidence and its seal are preserved untouched for diagnosis.
        self.assertEqual(verify.sha256_file(seal_path), seal_before)
        self.assertTrue(os.path.isfile(seal_path))

    def test_collect_and_write_are_not_reached_on_rejection(self):
        calls = {"collect": 0, "write": 0}
        real_derive = summarize.derive
        real_write = summarize.write_bytes

        def counting_derive(*args, **kwargs):
            calls["collect"] += 1
            return real_derive(*args, **kwargs)

        def counting_write(*args, **kwargs):
            calls["write"] += 1
            return real_write(*args, **kwargs)

        summarize.derive = counting_derive
        summarize.write_bytes = counting_write
        try:
            self.rewrite_verification(lambda payload: payload.update({"qualified": False}))
            with self.assertRaises(summarize.SummaryError):
                self.publish()
        finally:
            summarize.derive = real_derive
            summarize.write_bytes = real_write
        self.assertEqual(calls, {"collect": 0, "write": 0})


# ---------------------------------------------------------------------------
# RF-04: output confinement (FT-36 … FT-42)
# ---------------------------------------------------------------------------


class OutputConfinementTests(TreeTestCase):
    def assert_rejected_without_writes(self, expected_code, **overrides):
        before = self.snapshot_outputs()
        with self.assertRaises(summarize.SummaryError) as context:
            self.publish(**overrides)
        self.assertIn(expected_code, str(context.exception))
        self.assertEqual(self.snapshot_outputs(), before)

    def test_ft36_exact_destinations_publish(self):
        self.assertEqual(self.publish(), 0)
        for relative in (
            summarize.OUTPUT_REL_PATHS["out_json"],
            summarize.OUTPUT_REL_PATHS["out_md"],
            *summarize.IMPLICIT_OUTPUT_REL_PATHS,
        ):
            self.assertTrue(os.path.isfile(os.path.join(self.root, *relative.split("/"))))

    def test_ft37_arbitrary_output_path_is_rejected(self):
        self.assert_rejected_without_writes(
            "RF04_OUTPUT_PATH", out_json=os.path.join(tempfile.gettempdir(), "out.json")
        )

    def test_ft38_historical_pr15f_report_is_rejected(self):
        historical = os.path.join(
            self.root, "benchmarks", "reports", "pr15f", "p0-profile-summary.json"
        )
        os.makedirs(os.path.dirname(historical), exist_ok=True)
        with open(historical, "w", encoding="utf-8") as handle:
            handle.write('{"historical": true}\n')
        digest = verify.sha256_file(historical)
        with self.assertRaises(summarize.SummaryError) as context:
            self.publish(out_json=historical)
        self.assertIn("RF04_OUTPUT_PATH", str(context.exception))
        self.assertEqual(verify.sha256_file(historical), digest)

    def test_ft39_noncanonical_alias_is_rejected(self):
        alias = os.path.join(self.root, "docs", "..", "docs", "pr-artifacts", "pr-15i-0", "measurements.md")
        self.assert_rejected_without_writes("RF04_OUTPUT_PATH", out_md=alias)

    def test_ft40_symlinked_output_parent_is_rejected(self):
        real_dir = os.path.join(self.root, "docs", "pr-artifacts", "pr-15i-0")
        moved = os.path.join(self.root, "docs", "pr-artifacts", "pr-15i-0-real")
        shutil.move(real_dir, moved)
        os.symlink(moved, real_dir)
        target = os.path.join(moved, "measurements.md")
        digest = verify.sha256_file(target) if os.path.isfile(target) else None
        with self.assertRaises(summarize.SummaryError) as context:
            self.publish()
        self.assertIn("RF04_OUTPUT_SYMLINK", str(context.exception))
        if digest is not None:
            self.assertEqual(verify.sha256_file(target), digest)

    def test_ft41_symlinked_output_or_temp_file_is_rejected(self):
        out_json = self.outputs()["out_json"]
        other = os.path.join(self.root, "target", "pr15i-0", "elsewhere.json")
        FIXTURES.write_json(other, {"x": 1})
        os.remove(out_json)
        os.symlink(other, out_json)
        digest = verify.sha256_file(other)
        with self.assertRaises(summarize.SummaryError) as context:
            self.publish()
        self.assertIn("RF04_OUTPUT_SYMLINK", str(context.exception))
        self.assertEqual(verify.sha256_file(other), digest)

        os.remove(out_json)
        FIXTURES.write_json(out_json, {"restored": True})
        temporary = out_json + ".tmp"
        os.symlink(other, temporary)
        with self.assertRaises(summarize.SummaryError) as context:
            self.publish()
        self.assertIn("RF04_OUTPUT_SYMLINK", str(context.exception))

    def test_ft42_invalid_second_output_prevents_any_write(self):
        before = self.snapshot_outputs()
        with self.assertRaises(summarize.SummaryError) as context:
            self.publish(out_md=os.path.join(tempfile.gettempdir(), "nope.md"))
        self.assertIn("RF04_OUTPUT_PATH", str(context.exception))
        self.assertEqual(self.snapshot_outputs(), before)

    def test_missing_report_directory_is_a_layout_error(self):
        shutil.rmtree(os.path.join(self.root, "benchmarks", "reports", "pr15i-0"))
        with self.assertRaises(summarize.SummaryError) as context:
            self.publish()
        self.assertIn("RF04_OUTPUT_LAYOUT", str(context.exception))


# ---------------------------------------------------------------------------
# RF-03: privacy completeness (FT-29 … FT-35) and end-to-end (FT-43/FT-45)
# ---------------------------------------------------------------------------


class PrivacyAndEndToEndTests(TreeTestCase):
    def test_ft32_scan_reports_fails_when_a_target_is_missing(self):
        os.remove(os.path.join(self.root, *verify.FROZEN_PRIVACY_TARGETS[0].split("/")))
        scan = summarize.scan_reports(self.root)
        self.assertEqual(scan["status"], "FAIL")
        self.assertEqual(len(scan["files"]), 11)
        self.assertTrue(scan["problems"])

    def test_ft34_scan_reports_detects_private_content(self):
        target = os.path.join(self.root, *verify.FROZEN_PRIVACY_TARGETS[1].split("/"))
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("contact /home/privateuser/secret\n")
        scan = summarize.scan_reports(self.root)
        self.assertEqual(scan["status"], "FAIL")
        self.assertTrue(any("unix home path" in item["match"] for item in scan["problems"]))

    def test_ft35_scan_only_recomputes_and_refuses_incomplete_inventory(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(summarize.run_scan_only(self.root), 0)
        scan_path = os.path.join(self.root, *summarize.SCAN_ONLY_REL.split("/"))
        first = verify.read_json(scan_path)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual([item["path"] for item in first["files"]], list(verify.FROZEN_PRIVACY_TARGETS))

        # Update one report, rescan, and prove the hash followed the content.
        target = os.path.join(self.root, *verify.FROZEN_PRIVACY_TARGETS[2].split("/"))
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("updated\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(summarize.run_scan_only(self.root), 0)
        second = verify.read_json(scan_path)
        changed = {
            item["path"]: item["sha256"] for item in second["files"]
        }[verify.FROZEN_PRIVACY_TARGETS[2]]
        self.assertNotEqual(
            changed,
            {item["path"]: item["sha256"] for item in first["files"]}[
                verify.FROZEN_PRIVACY_TARGETS[2]
            ],
        )

        # A missing mandatory target must fail and must not write a PASS scan.
        digest_before = verify.sha256_file(scan_path)
        os.remove(os.path.join(self.root, *verify.FROZEN_PRIVACY_TARGETS[3].split("/")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(summarize.run_scan_only(self.root), 1)
        self.assertEqual(verify.sha256_file(scan_path), digest_before)

    def test_ft43_publish_scan_and_final_verification(self):
        self.assertEqual(self.publish(), 0)
        scan = summarize.scan_reports(self.root)
        self.assertEqual(scan["status"], "PASS")
        self.assertEqual(len(scan["files"]), 12)
        final_path = os.path.join(self.root, "target", "pr15i-0", "verification-02.json")
        saved_git = verify.git
        saved_run = verify.run_command
        saved_source = FIXTURES.ACTIVE_SOURCE
        verify.git = FIXTURES.FakeGit(head=FROZEN_SOURCE)
        verify.run_command = FIXTURES.fake_run_command
        FIXTURES.ACTIVE_SOURCE = FROZEN_SOURCE
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = verify.verification_main(
                    [
                        "--root",
                        self.root,
                        "--source-sha",
                        FROZEN_SOURCE,
                        "--pr15d-run",
                        self.paths["pr15d"],
                        "--pr15f-run",
                        self.paths["pr15f"],
                        "--pr15f-prepared",
                        self.paths["prepared"],
                        "--mutation-run",
                        self.paths["mutation"],
                        "--out",
                        final_path,
                    ]
                )
        finally:
            verify.git = saved_git
            verify.run_command = saved_run
            FIXTURES.ACTIVE_SOURCE = saved_source
        self.assertEqual(code, 0)
        final = verify.read_json(final_path)
        self.assertTrue(final["qualified"])
        self.assertEqual(final["overall_status"], "15I0_QUALIFIED_REVIEW_READY")

    def test_ft45_publication_is_deterministic(self):
        self.assertEqual(self.publish(), 0)
        first = self.snapshot_outputs()
        self.assertEqual(self.publish(), 0)
        second = self.snapshot_outputs()
        self.assertEqual(first, second)

    def test_privacy_scan_is_written_last_and_covers_the_published_reports(self):
        self.assertEqual(self.publish(), 0)
        scan = verify.read_json(
            os.path.join(self.root, *verify.PRIVACY_SCAN_REL.split("/"))
        )
        self.assertEqual(scan["status"], "PASS")
        listed = {item["path"]: item["sha256"] for item in scan["files"]}
        summary_rel = summarize.OUTPUT_REL_PATHS["out_json"]
        self.assertEqual(
            listed[summary_rel],
            verify.sha256_file(os.path.join(self.root, *summary_rel.split("/"))),
        )


if __name__ == "__main__":
    unittest.main()

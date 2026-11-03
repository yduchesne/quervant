#!/usr/bin/env python3
"""PR 15F attribution and ranking tests (T11, T12)."""

from __future__ import annotations

import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import attribution as a  # noqa: E402

GROUP_KEYS = {"__unknown__": "G08", **a.QUERY_GROUPS}


def shares(exclusive, inclusive, unknown=0.0, paths=None):
    total = sum(exclusive.values()) + unknown
    return {
        "mode": "query",
        "groups": a.QUERY_GROUPS,
        "exclusive_percent": {**{name: 0.0 for name in a.QUERY_GROUPS}, **exclusive},
        "inclusive_percent": {**{name: 0.0 for name in a.QUERY_GROUPS}, **inclusive},
        "allocated_exclusive_percent": {},
        "unknown_exclusive_percent": round(unknown, 4),
        "exclusive_total_percent": round(total, 4),
        "inclusive_paths": paths or {},
    }


class ParsingTests(unittest.TestCase):
    def test_self_report_and_header(self):
        text = (
            "# Samples: 12K of event 'cycles:Pu'\n"
            "# Total Lost Samples: 3\n"
            "#\n"
            "# Overhead  Shared Object  Symbol\n"
            "    23.21%  adapter        [.] quervant_core7segment6stored17decode\n"
            "     3.00%  libc.so.6      [.] memcpy\n"
        )
        rows = a.parse_self_report(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["percent"], 23.21)
        self.assertEqual(rows[0]["symbol"], "quervant_core7segment6stored17decode")
        header = a.parse_header(text)
        self.assertEqual(header, {"sample_count": 12000, "lost_samples": 3})

    def test_calltree_reconstructs_ancestor_paths(self):
        text = (
            "# Samples: 10 of event 'cycles'\n"
            "    99.95%     0.00%  probe  probe  [.] main\n"
            "            |\n"
            "            ---main\n"
            "               |          \n"
            "                --60.00%--quervant_core7search6unified17project_selected_hits\n"
            "                          |          \n"
            "                           --30.00%--quervant_core7segment6stored15decode_stored\n"
        )
        occurrences = a.parse_calltree(text)
        self.assertTrue(
            any(
                occurrence["symbol"].endswith("decode_stored")
                and any("project_selected_hits" in symbol for symbol in occurrence["path"])
                and "main" in occurrence["path"]
                for occurrence in occurrences
            )
        )

    def test_demangler_absence_is_not_fatal(self):
        mapping, meta = a.demangle_symbols(["x"], finder=lambda name: None)
        self.assertEqual(mapping, {"x": "x"})
        self.assertFalse(meta["available"])


class OwnershipTests(unittest.TestCase):
    def test_exclusive_partition_ambiguous_symbols_and_remainder(self):
        rows = [
            {"percent": 60.0, "dso": "probe",
             "symbol": "quervant_core7segment6stored23decode_stored_selected"},
            {"percent": 30.0, "dso": "probe",
             "symbol": "quervant_core7search7execute20evaluate_lexical_with"},
            {"percent": 5.0, "dso": "probe",
             "symbol": "mystery_leaf"},
            {"percent": 3.0, "dso": "probe", "symbol": "another_mystery_leaf"},
        ]
        calltree = [
            {"percent": 60.0,
             "symbol": "quervant_core7segment6stored23decode_stored_selected",
             "path": ["main", "search", "project_selected_hits",
                      "quervant_core7segment6stored23decode_stored_selected"]},
            {"percent": 30.0,
             "symbol": "quervant_core7search7execute20evaluate_lexical_with",
             "path": ["main", "search", "evaluate_lexical_with",
                      "quervant_core7search7execute20evaluate_lexical_with"]},
            {"percent": 5.0, "symbol": "mystery_leaf",
             "path": ["main", "search", "project_selected_hits", "mystery_leaf"]},
            {"percent": 3.0, "symbol": "another_mystery_leaf",
             "path": ["main", "search", "mystery", "another_mystery_leaf"]},
        ]
        result = a.summarise(rows, calltree, mode="query", demangled={})
        exclusive = result["exclusive_percent"]
        self.assertEqual(exclusive["G05"], 60.0)
        self.assertEqual(exclusive["G06A"], 30.0)
        self.assertEqual(exclusive["G08"], 10.0)  # 5 + 3 unclassified + 2 remainder
        self.assertLessEqual(result["exclusive_total_percent"], 100.0)
        self.assertEqual(result["unknown_exclusive_percent"], 10.0)
        self.assertEqual(result["ambiguous_symbols"], {})
        self.assertEqual(result["inclusive_percent"]["G05"], 60.0)
        self.assertEqual(result["inclusive_percent"]["G06A"], 30.0)
        # Allocated view is diagnostic only and must stay separate.
        self.assertNotIn("allocated_exclusive_percent", result["inclusive_percent"])

    def test_inclusive_shares_are_maxima_never_sums(self):
        symbol = "quervant_core7segment6stored23decode_stored_selected"
        rows = [{"percent": 70.0, "dso": "probe", "symbol": symbol}]
        calltree = [
            {"percent": 40.0, "symbol": symbol,
             "path": ["main", "a", "project_selected_hits", symbol]},
            {"percent": 30.0, "symbol": symbol,
             "path": ["main", "b", "project_selected_hits", symbol]},
        ]
        result = a.summarise(rows, calltree, mode="query", demangled={})
        self.assertEqual(result["inclusive_percent"]["G05"], 40.0)

    def test_standard_runtime_frames_become_unknown(self):
        rows = [{"percent": 100.0, "dso": "libc.so.6", "symbol": "memcpy"}]
        calltree = [
            {"percent": 100.0, "symbol": "memcpy",
             "path": ["main", "std", "alloc", "memcpy"]}
        ]
        result = a.summarise(rows, calltree, mode="query", demangled={})
        self.assertEqual(result["exclusive_percent"]["G08"], 100.0)

    def test_reopen_digest_paths_disambiguate_by_object(self):
        rows = [
            {
                "percent": 60.0,
                "dso": "probe",
                "symbol": "quervant_core7segment6format15parse_container",
            },
            {
                "percent": 40.0,
                "dso": "probe",
                "symbol": "quervant_core5index14mutation_state15MutationStateV16decode",
            },
        ]
        calltree = [
            {
                "percent": 60.0,
                "symbol": "quervant_core7segment6format15parse_container",
                "path": [
                    "main",
                    "open_with_limits",
                    "SegmentReader4open",
                    "quervant_core7segment6format15parse_container",
                ],
            },
            {
                "percent": 40.0,
                "symbol": "quervant_core5index14mutation_state15MutationStateV16decode",
                "path": ["main", "open_with_limits", "MutationStateV16decode"],
            },
        ]
        result = a.summarise(rows, calltree, mode="reopen", demangled={})
        self.assertEqual(result["exclusive_percent"]["R04"], 60.0)
        self.assertEqual(result["exclusive_percent"]["R05"], 40.0)
        self.assertEqual(result["exclusive_percent"]["R08"], 0.0)

    def test_ambiguous_read_verified_is_unknown_in_reopen_mode(self):
        rows = [
            {"percent": 40.0, "dso": "probe",
             "symbol": "quervant_core5index7support13read_verified"},
            {"percent": 10.0, "dso": "probe", "symbol": "no_context_symbol"},
            {"percent": 50.0, "dso": "probe",
             "symbol": "quervant_core7segment6reader12decode_metadata"},
        ]
        calltree = [
            {"percent": 40.0,
             "symbol": "quervant_core5index7support13read_verified",
             "path": ["main", "load_committed_at",
                      "quervant_core5index7support13read_verified"]},
            {"percent": 2.0,
             "symbol": "quervant_core5index7support13read_verified",
             "path": ["main", "read_current", "Manifest::decode",
                      "quervant_core5index7support13read_verified"]},
            {"percent": 50.0,
             "symbol": "quervant_core7segment6reader12decode_metadata",
             "path": ["main", "open_with_limits", "SegmentReader4open",
                      "quervant_core7segment6reader12decode_metadata"]},
        ]
        result = a.summarise(rows, calltree, mode="reopen", demangled={})
        self.assertIn(
            "quervant_core5index7support13read_verified",
            result["ambiguous_symbols"],
        )
        # read_verified (40) + no-context symbol (10) are both unresolved.
        self.assertEqual(result["exclusive_percent"]["R08"], 50.0)
        self.assertEqual(result["exclusive_percent"]["R03"], 0.0)
        self.assertEqual(result["exclusive_percent"]["R02"], 0.0)

    def test_stage_key_identifies_segment_and_mutation_subtrees(self):
        self.assertEqual(
            a.stage_key(["main", "SegmentReader::open", "parse_container", "sha2"]),
            "segment_container",
        )
        self.assertEqual(
            a.stage_key(["main", "MutationStateV16decode", "parse_container"]),
            "mutation_state",
        )
        self.assertEqual(a.stage_key(["main", "std"]), "root")


class RankingTests(unittest.TestCase):
    def _query(self, exclusive, inclusive=None, unknown=0.0):
        return a.classify_workload(
            shares(exclusive, inclusive or {}, unknown), GROUP_KEYS
        )

    def test_strong_exclusive_boundaries(self):
        self.assertEqual(
            self._query({"G05": 20.0, "G06A": 15.0})["classification"],
            "STRONG_EXCLUSIVE_CANDIDATE",
        )
        self.assertEqual(
            self._query({"G05": 20.0, "G06A": 15.01})["classification"],
            "UNRESOLVED",
        )
        self.assertEqual(
            self._query({"G05": 19.99, "G06A": 5.0})["classification"],
            "UNRESOLVED",
        )
        self.assertEqual(
            self._query({"G05": 30.0, "G06A": 10.0}, unknown=10.0)["classification"],
            "STRONG_EXCLUSIVE_CANDIDATE",
        )
        self.assertEqual(
            self._query({"G05": 30.0, "G06A": 10.0}, unknown=10.01)["classification"],
            "UNRESOLVED",
        )
        self.assertEqual(
            self._query({"G05": 25.0, "G06A": 25.0}, unknown=0.0)["classification"],
            "UNRESOLVED",
        )

    def test_likely_inclusive_threshold_and_competition(self):
        self.assertEqual(
            self._query({"G05": 5.0}, {"G05": 35.0})["classification"],
            "LIKELY_INCLUSIVE_CANDIDATE",
        )
        self.assertEqual(
            self._query({"G05": 5.0}, {"G05": 34.99})["classification"],
            "UNRESOLVED",
        )
        disjoint = a.classify_workload(
            shares(
                {"G05": 5.0},
                {"G05": 40.0, "G06A": 40.0},
                paths={
                    "G05": ["main", "search", "a", "leaf"],
                    "G06A": ["main", "other", "b", "leaf"],
                },
            ),
            GROUP_KEYS,
        )
        self.assertEqual(disjoint["classification"], "UNRESOLVED")
        overlapping = a.classify_workload(
            shares(
                {"G05": 5.0},
                {"G05": 40.0, "G06A": 40.0},
                paths={
                    "G05": ["main", "SegmentReader", "a", "leaf"],
                    "G06A": ["main", "SegmentReader", "b", "leaf"],
                },
            ),
            GROUP_KEYS,
        )
        self.assertIn(
            overlapping["classification"],
            ("LIKELY_INCLUSIVE_CANDIDATE", "UNRESOLVED"),
        )

    def test_unknown_dominance_blocks_strong_but_not_inclusive(self):
        strong_blocked = self._query(
            {"G05": 20.0, "G06A": 10.0}, {"G05": 50.0}, unknown=30.0
        )
        self.assertEqual(strong_blocked["classification"], "LIKELY_INCLUSIVE_CANDIDATE")
        unresolved = self._query(
            {"G05": 20.0, "G06A": 10.0}, {"G05": 34.99}, unknown=30.0
        )
        self.assertEqual(unresolved["classification"], "UNRESOLVED")
        self.assertEqual(unresolved["rule"], "RULE_UNRESOLVED")

    def test_ancestor_inclusive_path_is_not_a_disjoint_competitor(self):
        result = a.classify_workload(
            shares(
                {"G05": 5.0},
                {"G02": 90.0, "G05": 50.0},
                paths={
                    "G02": ["main", "search_impl"],
                    "G05": ["main", "search_impl", "project_selected_hits", "leaf"],
                },
            ),
            GROUP_KEYS,
        )
        self.assertEqual(result["classification"], "LIKELY_INCLUSIVE_CANDIDATE")
        self.assertEqual(result["group"], "G05")

    def test_rule_ids_are_explicit(self):
        strong = self._query({"G05": 30.0, "G06A": 10.0})
        self.assertEqual(strong["rule"], "RULE_STRONG_EXCLUSIVE_20_5_10")
        inclusive = self._query({"G05": 5.0}, {"G05": 40.0})
        self.assertEqual(inclusive["rule"], "RULE_INCLUSIVE_35")
        self.assertEqual(inclusive["note"], "inclusive-only; not an estimated improvement")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""PR 15F P0 verification and sanitized publication.

Re-derives every published number from the private capture manifests and raw
stage samples, enforces the PR 15F gate matrix, and writes exactly one sanitized
report:

    benchmarks/reports/pr15f/p0-profile-summary.json

Raw evidence stays under ``target/pr15f/``. Publication refuses hostnames,
usernames, absolute paths, PIDs, attestation material and raw profiler output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import attribution as attribution_module  # noqa: E402
import profile_queries as pq  # noqa: E402
import run as campaign  # noqa: E402

SCHEMA_SUMMARY = "pr15f-p0-summary-v1"
PUBLISH_PATH = os.path.join(
    REPO_ROOT, "benchmarks", "reports", "pr15f", "p0-profile-summary.json"
)

PASS = "PASS"
FAILED = "FAILED"
BLOCKED = "BLOCKED"
NOT_MEASURED = "NOT_MEASURED"
NOT_APPLICABLE = "NOT_APPLICABLE"

STATUS_QUALIFIED = "P0_QUALIFIED_REVIEW_READY"
STATUS_QUALIFIED_NO_ALLOC = "P0_QUALIFIED_ALLOCATION_NOT_MEASURED"
STATUS_PARTIAL = "P0_PARTIAL_EVIDENCE"
STATUS_BLOCKED = "P0_BLOCKED_ENVIRONMENT"

FORBIDDEN_PUBLISH_SUBSTRINGS = (
    "pr15e-attestation-v1",
    "operator_statement",
    "perf.data",
    "heaptrack.",
    "adapter_pid",
    "profiler-stderr",
    '"command"',
)

_ABS_PATH_RE = re.compile(
    r"""(?<![\w./-])/(?:home|Users|root|tmp|mnt|media|var|opt|proc|sys)/[^\s"']+"""
)
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\\\?[^\s\"']+")


class VerificationError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _pr15e_verify():
    return pq.eprofile._load_module(
        "pr15f_pr15e_verify", os.path.join(REPO_ROOT, "benchmarks", "pr15e", "verify.py")
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def gate(gates: dict, name: str, ok: bool, detail: str, *, status: str | None = None):
    gates[name] = {
        "status": status or (PASS if ok else FAILED),
        "detail": detail,
    }
    return ok


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _sha(path: str) -> str:
    return pq.sha256_file(path)


def _rel(path: str) -> str:
    return pq.rel_path(path, REPO_ROOT)


def _git(*args) -> str | None:
    return campaign._git(*args)


def _comparable(value) -> str:
    return pq.sha256_bytes(pq.canonical_json_bytes(value))


# ---------------------------------------------------------------------------
# Source and prepared-state checks
# ---------------------------------------------------------------------------


def verify_source(run_dir: str, preflight: dict, gates: dict) -> dict:
    measured = preflight["source_sha"]
    head = _git("rev-parse", "HEAD")
    if not head:
        raise VerificationError("X01_GIT", "cannot resolve HEAD")
    changed = _git("diff", "--name-only", measured, "HEAD")
    if changed is None:
        raise VerificationError("X01_GIT", "cannot diff the measured source against HEAD")
    allowed = (
        "benchmarks/reports/pr15f/",
        "docs/pr-artifacts/pr-15f/",
        "docs/PERF_OPTIMIZATION_PLAN.md",
    )
    violations = [
        path
        for path in changed.splitlines()
        if path and not any(path.startswith(prefix) for prefix in allowed)
    ]
    gate(
        gates,
        "C01",
        not violations and head is not None,
        f"measured source {measured}; HEAD {head}; changed={violations or 'none'}",
    )
    pq.source_lock()
    protected = campaign.protected_tree_hash("HEAD")
    if protected["tree_sha256"] != preflight["protected_tree"]["tree_sha256"]:
        gate(
            gates,
            "C02",
            False,
            "protected crates/frozen benchmark tree changed after prepare",
        )
    else:
        gate(gates, "C02", True, "protected tree hash is unchanged")
    return {"measured_source_sha": measured, "head_sha": head, "changed": violations}


# ---------------------------------------------------------------------------
# Query campaign
# ---------------------------------------------------------------------------


def verify_query(
    prepared_run: str, run_dir: str, preflight: dict, gates: dict, errors: list
) -> dict:
    _, rows_by_n = pq.eprofile.load_corpus(prepared_run)
    prepared = pq.eprofile.read_json(os.path.join(prepared_run, "prepare.json"))
    campaign_path = os.path.join(run_dir, "query-campaign.json")
    campaign_record = (
        campaign.load_json(campaign_path) if os.path.isfile(campaign_path) else {}
    )
    descriptors = pq.perf_lane_descriptors()
    expected_ids = {descriptor["capture_id"] for descriptor in descriptors}
    observed = set()
    lanes = []
    any_captured = False
    for descriptor in descriptors:
        capture_dir = os.path.join(
            run_dir, descriptor["rel_dir"].replace("/", os.sep)
        )
        capture_path = os.path.join(capture_dir, "capture.json")
        failure_path = os.path.join(capture_dir, "failure.json")
        entry = {
            "capture_id": descriptor["capture_id"],
            "lane_id": descriptor["pr15f_lane_id"],
            "n": descriptor["n"],
            "class": descriptor["class"],
            "k": descriptor["k"],
            "tool": descriptor["tool"],
            "seconds": descriptor["seconds"],
        }
        if os.path.isfile(capture_path):
            observed.add(descriptor["capture_id"])
            any_captured = True
            capture = pq.read_json(capture_path)
            problems = []
            if capture.get("schema") != pq.SCHEMA_CAPTURE or capture.get("status") != "CAPTURED":
                problems.append("schema/status")
            if capture.get("capture_id") != descriptor["capture_id"]:
                problems.append("capture_id")
            if capture.get("lane_id") != descriptor["pr15f_lane_id"]:
                problems.append("lane_id")
            if [capture.get("n"), capture.get("class"), capture.get("k")] != [
                descriptor["n"],
                descriptor["class"],
                descriptor["k"],
            ]:
                problems.append("lane")
            if capture.get("seconds") != descriptor["seconds"]:
                problems.append("seconds")
            if capture.get("warmups") != pq.eprofile.WARMUPS:
                problems.append("warmups")
            if capture.get("profiled_query_count", 0) < pq.eprofile.MIN_PROFILED_REQUESTS:
                problems.append("profiled_requests")
            if capture.get("contention_before") != "clear" or capture.get(
                "contention_after"
            ) != "clear":
                problems.append("contention")
            if capture.get("source_sha") != preflight["source_sha"]:
                problems.append("source_sha")
            if capture.get("binary_sha256") != prepared["build"]["binary_sha256"]:
                problems.append("adapter_binary")
            if capture.get("index_inventory_sha256") != prepared["indexes"][
                str(descriptor["n"])
            ]["inventory"]["sha256"]:
                problems.append("index")
            if capture.get("corpus_manifest_sha256") != prepared["corpus"]["manifest_sha256"]:
                problems.append("corpus")
            if capture.get("authorization_basis") != pq.AUTHORIZATION_BASIS:
                problems.append("authorization_basis")
            if capture.get("test_fixture"):
                problems.append("test_fixture")
            expected = pq.eprofile.recompute_expected(rows_by_n, descriptor)
            if capture.get("expected_digest") != pq.eprofile.expected_digest(expected):
                problems.append("oracle_expectation")
            evidence = capture.get("tool_evidence", {})
            samples = evidence.get("sample_count")
            lost = evidence.get("lost_samples")
            if not isinstance(samples, int) or isinstance(samples, bool) or samples < pq.MIN_PERF_SAMPLES:
                problems.append("sample_count")
            if lost != 0:
                problems.append("lost_samples")
            if evidence.get("symbolization", {}).get("quervant_mentions", 0) < 1:
                problems.append("symbolization")
            artifacts = capture.get("files", [])
            recomputed = pq.artifact_manifest(capture_dir)
            if artifacts != recomputed:
                problems.append("artifact_manifest")
            self_text = _read(os.path.join(capture_dir, "perf-self.txt"))
            header = attribution_module.parse_header(self_text)
            if header["sample_count"] != samples:
                problems.append("self_report_samples")
            if header["lost_samples"] != lost:
                problems.append("self_report_lost")
            entry.update(
                {
                    "status": "CAPTURED" if not problems else "FAILED",
                    "problems": problems,
                    "sample_count": samples,
                    "lost_samples": lost,
                    "profiled_query_count": capture.get("profiled_query_count"),
                    "tool_version": capture.get("tool_version"),
                    "tool_origin": capture.get("tool_origin"),
                    "artifact_manifest_sha256": _comparable(artifacts),
                }
            )
            if problems:
                errors.append(f"{descriptor['capture_id']}: {problems}")
        elif os.path.isfile(failure_path):
            failure = pq.read_json(failure_path)
            entry.update(
                {
                    "status": "BLOCKED" if failure.get("status") == "BLOCKED" else "FAILED",
                    "code": failure.get("code"),
                    "detail": failure.get("detail"),
                }
            )
        else:
            entry.update({"status": "MISSING"})
        lanes.append(entry)

    extras = []
    root = os.path.join(run_dir, "queries")
    if os.path.isdir(root):
        for base, _directories, files in os.walk(root):
            if "capture.json" in files or "failure.json" in files:
                relative = pq.rel_path(base, run_dir)
                if not any(
                    relative == descriptor["rel_dir"] for descriptor in descriptors
                ):
                    extras.append(relative)
    qualified = (
        not extras
        and all(lane["status"] == "CAPTURED" for lane in lanes)
        and len(lanes) == 9
    )
    gate(
        gates,
        "C03",
        qualified,
        f"{sum(1 for lane in lanes if lane['status'] == 'CAPTURED')}/9 lanes captured; "
        f"extra={extras or 'none'}",
    )
    gate(
        gates,
        "C04",
        qualified
        and all(
            lane.get("sample_count", 0) >= pq.MIN_PERF_SAMPLES
            and lane.get("lost_samples") == 0
            for lane in lanes
        ),
        "nine perf profiles with >=1000 samples and zero lost samples",
    )
    return {
        "status": "QUALIFIED" if qualified else ("PARTIAL" if any_captured else "BLOCKED"),
        "captured": sum(1 for lane in lanes if lane["status"] == "CAPTURED"),
        "required": len(descriptors),
        "lanes": lanes,
        "campaign_status": campaign_record.get("status"),
        "unexpected_captures": extras,
    }


# ---------------------------------------------------------------------------
# Reopen campaign
# ---------------------------------------------------------------------------


def verify_reopen_single(run_dir: str, gates: dict, errors: list) -> dict:
    root = os.path.join(run_dir, "reopen", "single")
    summary = campaign.load_json(os.path.join(root, "summary.json"))
    launches = campaign.load_json(os.path.join(root, "launches.json"))
    problems = []
    if summary.get("schema") != campaign.SCHEMA_REOPEN_SINGLE:
        problems.append("schema")
    probes = summary.get("contention", {})
    if set(probes) != {"block1_before", "block1_after", "block2_before", "block2_after"}:
        problems.append("contention_probe_set")
    if any(state != "clear" for state in probes.values()):
        problems.append("contention_state")
    rederived = {}
    for n in pq.eprofile.N_VALUES:
        key = str(n)
        samples = [
            record["sample"]
            for block in ("block1", "block2")
            for record in launches.get(block, [])
            if record.get("n") == n and "sample" in record
        ]
        if len(samples) != campaign.REOPEN_BLOCK_LAUNCHES:
            problems.append(f"n{n}_sample_count")
            rederived[key] = {"sample_count": len(samples), "status": "UNQUALIFIED"}
            continue
        for sample in samples:
            try:
                campaign.validate_stage(sample)
            except pq.Pr15fError:
                problems.append(f"n{n}_stage")
        stages = campaign.summarize_reopen(samples)
        recorded = summary.get("n", {}).get(key, {}).get("stages", {})
        if recorded != stages:
            problems.append(f"n{n}_summary_mismatch")
        if summary.get("n", {}).get(key, {}).get("samples_ns") != samples:
            problems.append(f"n{n}_sample_series")
        rederived[key] = {
            "status": summary.get("n", {}).get(key, {}).get("status"),
            "sample_count": len(samples),
            "stages": stages,
            "private_evidence_sha256": _sha(os.path.join(root, "launches.json")),
        }
    rotation = {
        "block1": [
            10000 if index % 2 == 0 else 100000
            for index in range(campaign.REOPEN_BLOCK_LAUNCHES)
        ],
        "block2": [
            100000 if index % 2 == 0 else 10000
            for index in range(campaign.REOPEN_BLOCK_LAUNCHES)
        ],
    }
    for block, expected in rotation.items():
        observed = [record.get("n") for record in launches.get(block, [])]
        if observed != expected:
            problems.append(f"{block}_rotation")
    gate(gates, "C05", not problems, f"21 fresh processes per N; problems={problems or 'none'}")
    if problems:
        errors.extend(f"reopen_single: {problem}" for problem in problems)
    return {
        "status": "QUALIFIED" if not problems else "UNQUALIFIED",
        "fresh_processes_total": sum(
            len(launches.get(block, [])) for block in ("block1", "block2")
        ),
        "launches_per_n": campaign.REOPEN_BLOCK_LAUNCHES,
        "contention": probes,
        "not_os_cold": True,
        "historical_reference_100k_reopen_ns": summary.get(
            "historical_reference_100k_reopen_ns"
        ),
        "n": rederived,
        "private_evidence_sha256": _sha(os.path.join(root, "launches.json")),
    }


def verify_reopen_perf(run_dir: str, gates: dict, errors: list) -> dict:
    summary = campaign.load_json(os.path.join(run_dir, "reopen", "perf", "summary.json"))
    captures = summary.get("captures", {})
    problems = []
    output = {}
    for n, iterations in campaign.REOPEN_PERF_ITERATIONS.items():
        key = str(n)
        entry = captures.get(key, {})
        capture_dir = os.path.join(run_dir, "reopen", "perf", f"n{n}")
        if entry.get("status") != "CAPTURED":
            problems.append(f"n{n}_{entry.get('status')}")
            output[key] = {"status": entry.get("status"), "code": entry.get("code")}
            continue
        if entry.get("contention_before") != "clear" or entry.get(
            "contention_after"
        ) != "clear":
            problems.append(f"n{n}_contention")
        probe = entry.get("probe", {})
        if probe.get("iteration_count") != iterations:
            problems.append(f"n{n}_iterations")
        if probe.get("documents_verified") != n:
            problems.append(f"n{n}_documents")
        evidence = entry.get("tool_evidence", {})
        self_text = _read(os.path.join(capture_dir, "perf-self.txt"))
        header = attribution_module.parse_header(self_text)
        if header["sample_count"] != evidence.get("sample_count"):
            problems.append(f"n{n}_samples")
        if header["lost_samples"] != evidence.get("lost_samples"):
            problems.append(f"n{n}_lost")
        if evidence.get("lost_samples") != 0:
            problems.append(f"n{n}_lost_nonzero")
        if evidence.get("sample_count", 0) < pq.MIN_PERF_SAMPLES:
            problems.append(f"n{n}_sample_floor")
        output[key] = {
            "status": "CAPTURED",
            "iterations": iterations,
            "sample_count": evidence.get("sample_count"),
            "lost_samples": evidence.get("lost_samples"),
            "perf_version": entry.get("perf_version"),
            "perf_origin": entry.get("perf_origin"),
            "perf_fallback": entry.get("perf_fallback"),
            "artifact_manifest_sha256": _comparable(entry.get("tool_evidence", {})),
        }
    gate(gates, "C06", not problems, f"two reopen CPU loops; problems={problems or 'none'}")
    if problems:
        errors.extend(f"reopen_perf: {problem}" for problem in problems)
    return {
        "status": "QUALIFIED" if not problems else "UNQUALIFIED",
        "captures": output,
    }


# ---------------------------------------------------------------------------
# Layout and allocation
# ---------------------------------------------------------------------------


def verify_inventory(prepared_run: str, run_dir: str, gates: dict, errors: list) -> dict:
    summary = campaign.load_json(os.path.join(run_dir, "inventory", "summary.json"))
    problems = []
    indexes = {}
    for n in pq.eprofile.N_VALUES:
        key = str(n)
        record = campaign.load_json(os.path.join(run_dir, "inventory", f"n{n}.json"))
        index_dir = os.path.join(prepared_run, "indexes", f"n{n}")
        digests = campaign.file_digests(index_dir)
        total = sum(entry["bytes"] for entry in digests.values())
        if total != record.get("total_file_bytes"):
            problems.append(f"n{n}_total")
        if record.get("content_sha256") != _comparable(
            [{"path": path, **metadata} for path, metadata in sorted(digests.items())]
        ):
            problems.append(f"n{n}_content_digest")
        if not record.get("read_only"):
            problems.append(f"n{n}_read_only")
        reconciliation = record.get("reconciliation", {})
        if not reconciliation.get("bytes_reconciled") or not reconciliation.get(
            "segments_reconciled"
        ):
            problems.append(f"n{n}_reconcile")
        classified = (
            record["segment_file_bytes"]
            + record["manifest_file_bytes"]
            + record["mutation_state_file_bytes"]
            + record["metadata_file_bytes"]
        )
        if classified != record["total_file_bytes"]:
            problems.append(f"n{n}_categories")
        if (
            record["segment_section_bytes_total"]
            + record["segment_nonsection_bytes_total"]
            != record["segment_file_bytes"]
        ):
            problems.append(f"n{n}_sections")
        if sum(record["section_bytes"].values()) != record[
            "segment_section_bytes_total"
        ]:
            problems.append(f"n{n}_section_sum")
        indexes[key] = {
            "total_file_bytes": record["total_file_bytes"],
            "file_count": record["file_count"],
            "bytes_per_document": round(record["total_file_bytes"] / n, 3),
            "segment_file_bytes": record["segment_file_bytes"],
            "manifest_file_bytes": record["manifest_file_bytes"],
            "mutation_state_file_bytes": record["mutation_state_file_bytes"],
            "metadata_file_bytes": record["metadata_file_bytes"],
            "segment_section_bytes_total": record["segment_section_bytes_total"],
            "segment_nonsection_bytes_total": record["segment_nonsection_bytes_total"],
            "section_bytes": record["section_bytes"],
            "section_counts": record["section_counts"],
            "top_three_sections": [
                {"kind": kind, "bytes": value}
                for kind, value in sorted(
                    record["section_bytes"].items(),
                    key=lambda item: (-item[1], item[0]),
                )[:3]
            ],
            "reconciliation": reconciliation,
            "content_sha256": record["content_sha256"],
            "historical_reference_total_bytes": record.get(
                "historical_reference_total_bytes"
            ),
        }
    gate(gates, "C07", not problems, f"two byte-exact inventories; problems={problems or 'none'}")
    if problems:
        errors.extend(f"inventory: {problem}" for problem in problems)
    return {
        "status": "QUALIFIED" if not problems else "UNQUALIFIED",
        "indexes": indexes,
        "historical_reference_matches": summary.get("historical_reference_100k", {}).get(
            "matches_observed"
        ),
    }


def verify_allocation(run_dir: str, gates: dict) -> dict:
    path = os.path.join(run_dir, "allocation", "summary.json")
    if not os.path.isfile(path):
        gate(
            gates,
            "C13",
            True,
            "allocation campaign not run; recorded as ALLOCATION_NOT_MEASURED",
            status=NOT_MEASURED,
        )
        return {"status": "ALLOCATION_NOT_MEASURED"}
    summary = campaign.load_json(path)
    status = summary.get("status", "ALLOCATION_NOT_MEASURED")
    gate(
        gates,
        "C13",
        status in ("QUALIFIED", "ALLOCATION_NOT_MEASURED"),
        f"allocation status {status}",
        status=NOT_MEASURED if status != "QUALIFIED" else PASS,
    )
    return {
        "status": status,
        "captures": summary.get("captures", {}),
        "code": summary.get("code"),
        "detail": summary.get("detail"),
    }


# ---------------------------------------------------------------------------
# Attribution validation
# ---------------------------------------------------------------------------


def _public_capture_record(record: dict) -> dict:
    """Project a private analysis record onto publishable, host-free fields."""
    keep = (
        "capture_id",
        "lane_id",
        "tool",
        "n",
        "class",
        "k",
        "seconds",
        "sample_count",
        "lost_samples",
        "profiled_query_count",
        "warmups",
        "source_sha",
        "binary_sha256",
        "tool_version",
        "material_occurrence_percent",
        "groups",
        "exclusive_percent",
        "inclusive_percent",
        "allocated_exclusive_percent",
        "unknown_exclusive_percent",
        "exclusive_total_percent",
        "ambiguous_symbols",
        "inclusive_paths",
        "unparsed_remainder_percent",
        "rank",
        "status",
        "self_rows",
        "calltree_occurrences",
    )
    projected = {key: record[key] for key in keep if key in record}
    demangler = record.get("demangler")
    if isinstance(demangler, dict):
        projected["demangler"] = {
            "available": demangler.get("available"),
            "version": demangler.get("version"),
        }
    return projected


def validate_attribution(analysis: dict, preflight: dict, gates: dict, errors: list) -> dict:
    problems = []
    if analysis.get("schema") != attribution_module.SCHEMA_ANALYSIS:
        problems.append("schema")
    if analysis.get("measured_source_sha") != preflight["source_sha"]:
        problems.append("measured_source_sha")
    if not analysis.get("non_additivity_warning"):
        problems.append("non_additivity_warning")
    allowed_rules = {
        "RULE_STRONG_EXCLUSIVE_20_5_10",
        "RULE_INCLUSIVE_35",
        "RULE_UNRESOLVED",
    }
    for lane, record in analysis.get("query", {}).items():
        if record.get("status") == "NOT_CAPTURED":
            continue
        total = record.get("exclusive_total_percent")
        if not isinstance(total, (int, float)) or total > 100.0 + 1e-6:
            problems.append(f"{lane}_exclusive_partition")
        rank = record.get("rank", {})
        if rank.get("rule") not in allowed_rules:
            problems.append(f"{lane}_rule")
        else:
            expected = attribution_module.classify_workload(
                {
                    "mode": "query" if "G01" in record.get("groups", {}) else "reopen",
                    "exclusive_percent": record["exclusive_percent"],
                    "inclusive_percent": record["inclusive_percent"],
                    "unknown_exclusive_percent": record["unknown_exclusive_percent"],
                    "inclusive_paths": record.get("inclusive_paths", {}),
                },
                {"__unknown__": "G08", **record["groups"]},
            )
            if expected["classification"] != rank.get("classification"):
                problems.append(f"{lane}_ranking_not_deterministic")
    for n, record in analysis.get("reopen", {}).items():
        if record.get("status") == "NOT_CAPTURED":
            continue
        rank = record.get("rank", {})
        if rank.get("rule") not in allowed_rules:
            problems.append(f"reopen_{n}_rule")
    for n, record in analysis.get("layout", {}).items():
        if record.get("status") == "NOT_CAPTURED":
            continue
        if record.get("architecture_label") != "ARCHITECTURE_DESIGN_REQUIRED":
            problems.append(f"layout_{n}_label")
    gate(gates, "C08", not problems, f"attribution rules; problems={problems or 'none'}")
    if problems:
        errors.extend(f"attribution: {problem}" for problem in problems)
    return {
        "status": "QUALIFIED" if not problems else "UNQUALIFIED",
        "query": {
            lane: _public_capture_record(record)
            for lane, record in analysis.get("query", {}).items()
        },
        "reopen": {
            n: _public_capture_record(record)
            for n, record in analysis.get("reopen", {}).items()
        },
        "layout": analysis.get("layout", {}),
        "ranking": analysis.get("ranking", {}),
        "methods": analysis.get("methods", {}),
        "ranking_rules": analysis.get("ranking_rules", {}),
        "non_additivity_warning": analysis.get("non_additivity_warning"),
    }


# ---------------------------------------------------------------------------
# Summary composition and sanitization
# ---------------------------------------------------------------------------


def build_summary(
    prepared_run: str,
    run_dir: str,
    preflight: dict,
    source: dict,
    query: dict,
    reopen_single: dict,
    reopen_perf: dict,
    inventory: dict,
    allocation: dict,
    attribution: dict | None,
    gates: dict,
    errors: list,
) -> dict:
    mandatory = ["C01", "C02", "C03", "C04", "C05", "C06", "C07"]
    mandatory_pass = all(gates.get(name, {}).get("status") == PASS for name in mandatory)
    allocation_ok = allocation.get("status") in ("QUALIFIED", "ALLOCATION_NOT_MEASURED")
    attribution_ok = gates.get("C08", {}).get("status") == PASS
    any_evidence = query["captured"] > 0 or reopen_single.get("fresh_processes_total", 0) > 0
    if not any_evidence:
        status = STATUS_BLOCKED
    elif mandatory_pass and attribution_ok and allocation_ok:
        status = (
            STATUS_QUALIFIED
            if allocation.get("status") == "QUALIFIED"
            else STATUS_QUALIFIED_NO_ALLOC
        )
    else:
        status = STATUS_PARTIAL

    observations = []
    if attribution:
        for lane, record in attribution.get("query", {}).items():
            rank = record.get("rank", {})
            if record.get("status") == "NOT_CAPTURED":
                continue
            observations.append(
                {
                    "lane": lane,
                    "classification": rank.get("classification"),
                    "group": rank.get("group"),
                    "rule": rank.get("rule"),
                    "exclusive_percent": record.get("exclusive_percent", {}).get(
                        rank.get("group")
                    ),
                    "inclusive_percent": record.get("inclusive_percent", {}).get(
                        rank.get("group")
                    ),
                    "unknown_exclusive_percent": record.get(
                        "unknown_exclusive_percent"
                    ),
                }
            )
        for n, record in attribution.get("reopen", {}).items():
            if record.get("status") == "NOT_CAPTURED":
                continue
            rank = record.get("rank", {})
            observations.append(
                {
                    "lane": f"reopen/{n}",
                    "classification": rank.get("classification"),
                    "group": rank.get("group"),
                    "rule": rank.get("rule"),
                    "inclusive_percent": record.get("inclusive_percent", {}).get(
                        rank.get("group")
                    ),
                    "unknown_exclusive_percent": record.get(
                        "unknown_exclusive_percent"
                    ),
                }
            )

    prepared = pq.eprofile.read_json(os.path.join(prepared_run, "prepare.json"))
    summary = {
        "schema": SCHEMA_SUMMARY,
        "status": status,
        "measured_source_sha": source["measured_source_sha"],
        "head_sha_at_verification": source["head_sha"],
        "source": {
            "origin_main_sha": preflight.get("origin_main_sha"),
            "protected_tree_sha256": preflight["protected_tree"]["tree_sha256"],
            "frozen_source_lock": preflight.get("source_lock"),
            "tool_module_lock": preflight.get("tool_module_lock"),
            "corpus_manifest_sha256": prepared["corpus"]["manifest_sha256"],
            "adapter_binary_sha256": prepared["build"]["binary_sha256"],
            "probe_binary_sha256": preflight["probe"]["binary_sha256"],
            "probe_source_sha256": preflight["probe"]["source_sha256"],
            "probe_lock_sha256": preflight["probe"]["lock_sha256"],
            "index_inventory_sha256": preflight.get("index_inventory_sha256"),
        },
        "prepared_sha256": preflight.get("prepared_sha256"),
        "workload": prepared.get("workload"),
        "regime": prepared.get("regime"),
        "authorization_basis": preflight.get("authorization_basis"),
        "authorization_is_measured_fact": False,
        "campaigns": {
            "query": query["status"],
            "reopen_timing": reopen_single["status"],
            "reopen_cpu": reopen_perf["status"],
            "layout": inventory["status"],
            "allocation": allocation["status"],
            "attribution": attribution["status"] if attribution else NOT_MEASURED,
        },
        "query": {
            "required": query["required"],
            "captured": query["captured"],
            "lanes": query["lanes"],
            "unexpected_captures": query["unexpected_captures"],
        },
        "reopen": {"single": reopen_single, "cpu": reopen_perf},
        "layout": inventory,
        "allocation": allocation,
        "attribution": attribution or {"status": NOT_MEASURED},
        "observations": observations,
        "gates": gates,
        "errors": errors,
        "non_additivity_warning": (
            "Exclusive percentages partition self samples; inclusive percentages "
            "overlap and are never added to them or to each other."
        ),
        "historical_anchors_not_thresholds": {
            "warm_100k_quervant_k100_ns": preflight["anchors"][
                "warm_100k_quervant_k100"
            ],
            "index_bytes_100k": preflight["anchors"]["index_bytes_100k"],
            "build_phase_reopen_ns_100k": preflight["anchors"][
                "build_phase_reopen_ns_100k"
            ],
            "note": "historical context only; PR 15F did not improve these numbers",
        },
        "privacy": {
            "sanitized": True,
            "raw_evidence": "TARGET_ONLY_NOT_PUBLISHED",
            "host_and_user_omitted": True,
            "pids_omitted": True,
            "attestation_omitted": True,
        },
        "limitations": [
            "Measured source is the benchmark-only commit; report/docs commits are later evidence SHAs.",
            "Assumed-idle is plan-approved authorization, not a measured host fact.",
            "Fresh-process reopen is not an OS-cold page-cache measurement.",
            "Inclusive attribution is never an estimated improvement.",
            "No production code, query semantics or on-disk format was changed.",
            "NO_OPTIMIZATION_IMPLEMENTED; NOT_MERGED.",
        ],
    }
    return summary


def sanitize(summary: dict) -> str:
    text = json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    verify_module = _pr15e_verify()
    import socket

    try:
        user = __import__("getpass").getuser()
    except Exception:  # pragma: no cover - environment dependent
        user = None
    hits = verify_module.sensitive_hits(text, host=socket.gethostname(), user=user)
    hits += [match.group(0) for match in _ABS_PATH_RE.finditer(text)]
    hits += [match.group(0) for match in _WINDOWS_PATH_RE.finditer(text)]
    hits += [
        marker for marker in FORBIDDEN_PUBLISH_SUBSTRINGS if marker in text
    ]
    if hits:
        raise VerificationError(
            "X31_SENSITIVE_CONTENT",
            f"refusing publication; markers found: {sorted(set(hits))[:5]}",
        )
    return text


def publish(text: str, destination: str) -> dict:
    if os.path.exists(destination):
        with open(destination, "rb") as handle:
            existing = handle.read()
        if existing == text.encode("utf-8"):
            return {"written": False, "path": _rel(destination), "sha256": _sha(destination)}
        raise VerificationError(
            "X28_DESTINATION_EXISTS",
            "a different published summary already exists; refusing to overwrite",
        )
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(text)
    return {
        "written": True,
        "path": _rel(destination),
        "sha256": _sha(destination),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def evaluate(prepared_run: str, run_dir: str, analysis_path: str | None) -> dict:
    gates: dict = {}
    errors: list = []
    preflight = campaign.load_json(os.path.join(run_dir, "preflight.json"))
    if preflight.get("preflight_digest") != pq.sha256_bytes(
        pq.canonical_json_bytes(
            {key: value for key, value in preflight.items() if key != "preflight_digest"}
        )
    ):
        raise VerificationError("X33_PREPARE_INVALID", "preflight digest does not re-derive")
    if preflight["probe"]["binary_sha256"] != _sha(
        os.path.join(run_dir, preflight["probe"]["binary_rel"])
    ):
        raise VerificationError("X24_BINARY_CHANGED", "probe binary digest changed")
    source = verify_source(run_dir, preflight, gates)
    query = verify_query(prepared_run, run_dir, preflight, gates, errors)
    reopen_single = verify_reopen_single(run_dir, gates, errors)
    reopen_perf = verify_reopen_perf(run_dir, gates, errors)
    inventory = verify_inventory(prepared_run, run_dir, gates, errors)
    allocation = verify_allocation(run_dir, gates)
    attribution = None
    if analysis_path:
        analysis = campaign.load_json(analysis_path)
        attribution = validate_attribution(analysis, preflight, gates, errors)
    else:
        gate(
            gates,
            "C08",
            False,
            "no attribution analysis supplied",
            status=NOT_MEASURED,
        )
    gate(gates, "C09", True, "raw evidence remains under target; publication is sanitized")
    gate(gates, "C10", True, "benchmark-only unit/adversarial suites run separately")
    gate(
        gates,
        "C11",
        True,
        "workspace Rust QA is recorded in the execution document",
    )
    gate(gates, "C12", False, "hosted exact-head CI status is checked after push", status=BLOCKED)
    gate(gates, "C14", False, "independent reviewer sign-off is pending", status=BLOCKED)
    summary = build_summary(
        prepared_run,
        run_dir,
        preflight,
        source,
        query,
        reopen_single,
        reopen_perf,
        inventory,
        allocation,
        attribution,
        gates,
        errors,
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="PR 15F P0 verification and sanitized publication.",
        allow_abbrev=False,
    )
    parser.add_argument("--prepared-run", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--analysis")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--publish-sanitized", action="store_true")
    group.add_argument("--publish-partial", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        prepared_run = pq.resolve_prepared_run(args.prepared_run)
        run_dir = pq.resolve_run_dir(args.run, must_exist=True)
        summary = evaluate(prepared_run, run_dir, args.analysis)
        if args.publish_sanitized and summary["status"] not in (
            STATUS_QUALIFIED,
            STATUS_QUALIFIED_NO_ALLOC,
        ):
            raise VerificationError(
                "X31_NOT_QUALIFIED",
                f"--publish-sanitized requires a qualified campaign, got {summary['status']}",
            )
        if args.publish_partial and summary["status"] in (
            STATUS_QUALIFIED,
            STATUS_QUALIFIED_NO_ALLOC,
        ):
            summary["status"] = STATUS_PARTIAL
            summary["partial_reason"] = "published with --publish-partial"
        text = sanitize(summary)
        result = None
        if args.publish_sanitized or args.publish_partial:
            result = publish(text, PUBLISH_PATH)
        print(
            json.dumps(
                {
                    "status": summary["status"],
                    "gates": {
                        name: entry["status"] for name, entry in summary["gates"].items()
                    },
                    "errors": len(summary["errors"]),
                    "published": result,
                },
                sort_keys=True,
            )
        )
        if summary["status"] == STATUS_BLOCKED:
            return pq.EXIT_BLOCKED
        return pq.EXIT_OK
    except (
        pq.Pr15fError,
        pq.eprofile.Pr15eError,
        VerificationError,
        attribution_module.AnalysisError,
    ) as error:
        code = getattr(error, "code", "X99")
        print(f"{code}: {error}", file=sys.stderr)
        return pq.EXIT_HARD_STOP


if __name__ == "__main__":
    raise SystemExit(main())

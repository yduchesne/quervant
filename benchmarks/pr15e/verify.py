#!/usr/bin/env python3
"""PR 15E-A fail-closed evidence verification and report basis.

Standard library only. Rehashes every capture artifact against its manifest,
re-derives the fixed 20-capture matrix, validates an optional attribution
``analysis.json``, and can publish a sanitized manifest *only* from complete
evidence. Nothing here runs a profiler or a search engine.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import socket
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
PROFILE_PATH = os.path.join(_THIS_DIR, "profile.py")


def _load_module(module_name: str, path: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


profile = _load_module("pr15e_profile_for_verify", PROFILE_PATH)

PUBLISH_PATH = os.path.join(
    REPO_ROOT, "benchmarks", "reports", "pr15e-a", "profile-manifest.json"
)

PASS = "PASS"
FAILED = "FAILED"
BLOCKED = "BLOCKED"

STATUS_EVIDENCE_COMPLETE = "EVIDENCE_COMPLETE"
STATUS_PARTIAL = "PARTIAL"
STATUS_BLOCKED = "BLOCKED"
STATUS_FAILED = "FAILED"

# Diagnostic stderr streams may legitimately be empty; measurement artifacts may not.
DIAGNOSTIC_ARTIFACTS = frozenset({"profiler-stderr.txt", "heaptrack-print-stderr.txt"})

_ABS_PATH_RE = re.compile(
    r"""(?<![\w./-])/(?:home|Users|root|tmp|mnt|media|var|opt)/[^\s"'\)\]]+"""
)


class VerificationError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Prepare-state validation
# ---------------------------------------------------------------------------


def unexpected_captures(run_dir: str) -> list[str]:
    """Return capture directories that are not part of the fixed 20-capture matrix."""
    expected = {entry["rel_dir"] for entry in profile.required_captures()}
    root = os.path.join(run_dir, "captures")
    found: list[str] = []
    if not os.path.isdir(root):
        return found
    for base, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        if "capture.json" in files or "failure.json" in files:
            relative = profile.rel_path(base, run_dir)
            if relative not in expected:
                found.append(relative)
    return sorted(found)


def _verify_prepare(run_dir: str, deps) -> dict:
    violations: list[str] = []
    prepare_path = os.path.join(run_dir, "prepare.json")
    result = {
        "present": os.path.isfile(prepare_path),
        "sha256": None,
        "prepared": None,
        "rows_by_n": None,
        "violations": violations,
        "head_sha": None,
    }
    try:
        result["head_sha"] = deps.head_sha()
    except profile.Pr15eError:
        result["head_sha"] = None
    if not result["present"]:
        violations.append("prepare_missing: prepare.json is absent")
        return result
    result["sha256"] = profile.sha256_file(prepare_path)
    try:
        prepared = profile.read_json(prepare_path)
    except (OSError, ValueError) as error:
        violations.append(f"prepare_unreadable: {error}")
        return result
    if prepared.get("schema") != profile.SCHEMA_PREPARE or prepared.get("status") != "PREPARED":
        violations.append("prepare_schema: prepare.json is not a PREPARED record")
        return result
    recorded = prepared.get("prepared_digest")
    payload = {key: value for key, value in prepared.items() if key != "prepared_digest"}
    if recorded != profile.sha256_bytes(profile.canonical_json_bytes(payload)):
        violations.append("prepare_digest: prepare.json digest does not re-derive")
    result["prepared"] = prepared

    for name, entry in prepared.get("source_lock", {}).items():
        if name == "canonical_report":
            path = deps.canonical_report
        elif name in profile.FROZEN_FILES:
            path = os.path.join(profile.REPO_ROOT, profile.FROZEN_FILES[name])
        else:
            violations.append(f"source_lock_unknown: {name}")
            continue
        if not os.path.isfile(path):
            violations.append(f"source_lock_missing: {entry.get('path')}")
            continue
        if profile.sha256_file(path) != entry.get("sha256"):
            violations.append(f"source_lock_changed: {entry.get('path')}")

    corpus_dir = os.path.join(run_dir, "corpus")
    try:
        manifest, rows_by_n = profile.oracle.load_and_verify(corpus_dir)
    except profile.oracle.CorpusError as error:
        violations.append(f"corpus_invalid: {error.code}: {error.detail}")
        manifest = None
        rows_by_n = None
    if manifest is not None:
        result["rows_by_n"] = rows_by_n
        digest = profile.sha256_bytes(profile.canonical_json_bytes(manifest))
        if digest != prepared.get("corpus", {}).get("manifest_sha256"):
            violations.append("corpus_changed: corpus manifest digest differs")
        for entry in manifest["corpora"]:
            recorded_corpus = prepared.get("corpus", {}).get("corpora", {}).get(
                str(entry["n"])
            )
            if not recorded_corpus:
                violations.append(f"corpus_missing_record: N={entry['n']}")
                continue
            if entry["sha256"] != recorded_corpus.get("sha256"):
                violations.append(f"corpus_changed: N={entry['n']} digest differs")
            if entry["bytes"] != recorded_corpus.get("bytes"):
                violations.append(f"corpus_changed: N={entry['n']} byte count differs")

    binary = os.path.join(run_dir, prepared.get("build", {}).get("binary_path", ""))
    if not os.path.isfile(binary):
        violations.append("binary_missing: prepared adapter binary is absent")
    elif profile.sha256_file(binary) != prepared.get("build", {}).get("binary_sha256"):
        violations.append("binary_changed: prepared adapter binary digest differs")

    for relative in unexpected_captures(run_dir):
        violations.append(f"unexpected_capture: {relative}")

    for n in profile.N_VALUES:
        recorded = prepared.get("indexes", {}).get(str(n))
        if not recorded:
            violations.append(f"index_missing_record: N={n}")
            continue
        index_dir = os.path.join(run_dir, recorded.get("path", ""))
        if os.path.exists(index_dir) and profile.iter_symlinks(index_dir):
            violations.append(f"index_symlink: N={n}")
            continue
        for violation in profile.compare_index_inventory(
            index_dir, recorded.get("inventory", {})
        ):
            violations.append(f"N={n}: {violation}")
    return result


# ---------------------------------------------------------------------------
# Capture validation
# ---------------------------------------------------------------------------


def _capture_result(entry: dict) -> dict:
    return {
        "capture_id": entry["capture_id"],
        "lane_id": entry["lane_id"],
        "tool": entry["tool"],
        "n": entry["n"],
        "class": entry["class"],
        "k": entry["k"],
        "seconds": entry["seconds"],
        "status": BLOCKED,
        "reasons": [],
        "sample_count": None,
        "attribution": "NOT_MEASURED",
        "test_fixture": False,
        "artifacts": [],
        "profiled_query_count": None,
        "adapter_pid": None,
        "source_sha": None,
        "prepared_digest": None,
        "tool_version": None,
    }


def _verify_capture(run_dir: str, entry: dict, prepared_state: dict) -> dict:
    result = _capture_result(entry)
    capture_dir = os.path.join(run_dir, *entry["rel_dir"].split("/"))
    prepared = prepared_state.get("prepared")
    rows_by_n = prepared_state.get("rows_by_n")
    if not os.path.isdir(capture_dir):
        result["reasons"].append("capture_missing: no capture directory")
        return result
    symlinks = profile.iter_symlinks(capture_dir)
    if symlinks:
        result["status"] = FAILED
        result["reasons"].append(f"unsafe_path: symlinks in capture: {symlinks[:5]}")
        return result

    manifest_path = os.path.join(capture_dir, "capture.json")
    failure_path = os.path.join(capture_dir, "failure.json")
    has_manifest = os.path.isfile(manifest_path)
    has_failure = os.path.isfile(failure_path)
    if has_manifest and has_failure:
        result["status"] = FAILED
        result["reasons"].append("ambiguous_evidence: both capture.json and failure.json")
        return result
    if not has_manifest:
        if has_failure:
            try:
                failure = profile.read_json(failure_path)
            except (OSError, ValueError) as error:
                result["status"] = FAILED
                result["reasons"].append(f"failure_unreadable: {error}")
                return result
            status = failure.get("status")
            result["status"] = FAILED if status in ("FAILED", "HARD_STOP") else BLOCKED
            result["reasons"].append(
                f"{failure.get('code', 'failure')}: {failure.get('detail', '')}"
            )
            if failure.get("capture_id") not in (None, entry["capture_id"]):
                result["status"] = FAILED
                result["reasons"].append("mislabeled_failure: capture_id mismatch")
            return result
        result["reasons"].append("capture_missing: no manifest and no failure record")
        return result

    try:
        manifest = profile.read_json(manifest_path)
    except (OSError, ValueError) as error:
        result["status"] = FAILED
        result["reasons"].append(f"manifest_unreadable: {error}")
        return result
    result["test_fixture"] = bool(manifest.get("test_fixture"))
    result["sample_count"] = (
        manifest.get("tool_evidence", {}).get("sample_count")
        if entry["tool"] == "perf"
        else None
    )
    result["profiled_query_count"] = manifest.get("profiled_query_count")
    result["adapter_pid"] = manifest.get("adapter_pid")
    result["source_sha"] = manifest.get("source_sha")
    result["prepared_digest"] = manifest.get("prepared_digest")
    result["tool_version"] = manifest.get("tool_version")

    def reject(code: str, detail: str) -> None:
        result["status"] = FAILED
        result["reasons"].append(f"{code}: {detail}")

    if manifest.get("schema") != profile.SCHEMA_CAPTURE:
        reject("manifest_schema", "capture.json is not pr15e-capture-v1")
    if manifest.get("status") != "CAPTURED_RAW":
        reject("manifest_status", "capture.json status is not CAPTURED_RAW")
    identity = {
        "capture_id": entry["capture_id"],
        "lane_id": entry["lane_id"],
        "tool": entry["tool"],
        "n": entry["n"],
        "class": entry["class"],
        "field": entry["field"],
        "term": entry["term"],
        "k": entry["k"],
        "regime": profile.REGIME,
        "seconds": entry["seconds"],
    }
    for key, value in identity.items():
        if manifest.get(key) != value:
            reject("mislabeled_capture", f"{key}: {manifest.get(key)!r} != {value!r}")
    if manifest.get("warmups") != profile.WARMUPS:
        reject("warmups", f"warmups {manifest.get('warmups')!r} != {profile.WARMUPS}")
    profiled_count = manifest.get("profiled_query_count")
    if (
        isinstance(profiled_count, bool)
        or not isinstance(profiled_count, int)
        or profiled_count < profile.MIN_PROFILED_REQUESTS
    ):
        reject(
            "profiled_requests",
            f"profiled_query_count {profiled_count!r} < {profile.MIN_PROFILED_REQUESTS}",
        )
    if manifest.get("warmup_in_capture") is not True:
        reject("warmup_in_capture", "warmups were not captured in the profiled process")

    if prepared is None:
        result["status"] = BLOCKED if result["status"] != FAILED else FAILED
        result["reasons"].append("prepare_unavailable: cannot cross-check provenance")
    else:
        if manifest.get("source_sha") != prepared["source"]["head_sha"]:
            reject("source_sha", "capture source SHA differs from prepare.json")
        if manifest.get("prepared_digest") != prepared.get("prepared_digest"):
            reject("prepared_digest", "capture prepared digest differs from prepare.json")
        if manifest.get("binary_sha256") != prepared["build"]["binary_sha256"]:
            reject("binary_sha256", "capture binary digest differs from prepare.json")
        if (
            manifest.get("index_inventory_sha256")
            != prepared["indexes"][str(entry["n"])]["inventory"]["sha256"]
        ):
            reject("index_digest", "capture index digest differs from prepare.json")
        if (
            manifest.get("corpus_manifest_sha256")
            != prepared["corpus"]["manifest_sha256"]
        ):
            reject("corpus_digest", "capture corpus digest differs from prepare.json")

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        reject("files", "capture.json carries no artifact list")
        files = []
    listed = set()
    for record in files:
        relative = record.get("path")
        if not isinstance(relative, str) or not relative or relative.startswith("/"):
            reject("artifact_path", f"invalid artifact path {relative!r}")
            continue
        if ".." in relative.split("/"):
            reject("artifact_path", f"artifact escapes the capture: {relative!r}")
            continue
        full = os.path.join(capture_dir, *relative.split("/"))
        if os.path.islink(full):
            reject("artifact_symlink", relative)
            continue
        if not os.path.isfile(full):
            reject("artifact_missing", relative)
            continue
        if os.path.getsize(full) == 0 and relative not in DIAGNOSTIC_ARTIFACTS:
            reject("artifact_empty", relative)
            continue
        if profile.sha256_file(full) != record.get("sha256"):
            reject("artifact_digest", f"{relative} differs from the manifest")
            continue
        if os.path.getsize(full) != record.get("bytes"):
            reject("artifact_bytes", f"{relative} byte count differs")
            continue
        listed.add(relative)
        result["artifacts"].append(
            {
                "name": f"{entry['rel_dir']}/{relative}",
                "bytes": record.get("bytes"),
                "sha256": record.get("sha256"),
            }
        )

    actual = set()
    for root, directories, names in os.walk(capture_dir, followlinks=False):
        directories.sort()
        for name in sorted(names):
            relative = profile.rel_path(os.path.join(root, name), capture_dir)
            if relative in ("capture.json", "failure.json"):
                continue
            actual.add(relative)
    unlisted = sorted(actual - listed)
    if unlisted:
        reject("artifact_unlisted", f"files not covered by the manifest: {unlisted[:5]}")

    required = ["contention-before.json", "contention-after.json", "profiler-stderr.txt"]
    if entry["tool"] == "perf":
        required += ["perf.data", "perf-self.txt", "perf-calltree.txt"]
    else:
        required += ["heaptrack-report.txt", "heaptrack-print-stderr.txt"]
    for name in required:
        if name not in listed:
            reject("artifact_required", f"missing required artifact {name}")
    if entry["tool"] == "heaptrack":
        gz = sorted(name for name in listed if name.startswith("heaptrack") and name.endswith(".gz"))
        if len(gz) != 1:
            reject("artifact_required", f"expected one heaptrack raw artifact, found {len(gz)}")

    for phase in ("before", "after"):
        name = f"contention-{phase}.json"
        if name not in listed:
            continue
        try:
            record = profile.read_json(os.path.join(capture_dir, name))
        except (OSError, ValueError) as error:
            reject("contention_unreadable", f"{name}: {error}")
            continue
        if record.get("state") != "clear":
            reject("contention", f"{name} state is {record.get('state')!r}")
        if manifest.get(f"contention_{phase}") != "clear":
            reject("contention", f"manifest claims contention_{phase} is not clear")

    if rows_by_n is not None:
        descriptor = {
            "n": entry["n"],
            "class": entry["class"],
            "field": entry["field"],
            "term": entry["term"],
            "k": entry["k"],
            "lane_id": entry["lane_id"],
        }
        expected = profile.recompute_expected(rows_by_n, descriptor)
        if manifest.get("expected_digest") != profile.expected_digest(expected):
            reject("oracle_digest", "recorded expectation does not re-derive")
        if manifest.get("expected_total_hits") != expected["total_hits"]:
            reject("oracle_count", "recorded total_hits differs from the oracle")
        if manifest.get("expected_doc_ids") != expected["doc_ids"]:
            reject("oracle_ids", "recorded doc_ids differ from the oracle")

    if entry["tool"] == "perf":
        if "perf-self.txt" in listed:
            text = profile.read_text(os.path.join(capture_dir, "perf-self.txt"))
            observed = profile.parse_perf_samples(text)
            claimed = manifest.get("tool_evidence", {}).get("sample_count")
            if observed is None:
                reject("perf_samples", "perf-self.txt exposes no sample count")
            elif observed < profile.MIN_PERF_SAMPLES:
                reject(
                    "perf_samples",
                    f"only {observed} samples; {profile.MIN_PERF_SAMPLES} required",
                )
            if isinstance(claimed, bool) or not isinstance(claimed, int):
                reject("perf_samples", "manifest sample_count is not an integer")
            elif claimed != observed:
                reject("perf_samples", f"manifest {claimed} != report {observed}")
            symbols = profile.symbolized_frames(text)
            if symbols["quervant_mentions"] < 1:
                result["attribution"] = "ATTRIBUTION_UNRESOLVED"
                result["reasons"].append(
                    "ATTRIBUTION_UNRESOLVED: no symbolized Quervant frames"
                )
            else:
                result["attribution"] = "MEASURED_EVIDENCE"
            if manifest.get("tool_evidence", {}).get("sampled_with_loss") != (
                profile.parse_perf_lost_samples(text) > 0
            ):
                reject("perf_loss", "manifest loss claim disagrees with the report")
    else:
        if "heaptrack-report.txt" in listed:
            text = profile.read_text(os.path.join(capture_dir, "heaptrack-report.txt"))
            records = profile.parse_heaptrack_records(text)
            claimed = manifest.get("tool_evidence", {}).get("records", {})
            if records["allocation_sites"] < 1:
                reject("heap_records", "heaptrack report has no allocation sites")
            if claimed.get("allocation_sites") != records["allocation_sites"]:
                reject("heap_records", "manifest allocation sites disagree with report")
            if claimed.get("total_allocations") != records["total_allocations"]:
                reject("heap_records", "manifest allocation totals disagree with report")
            result["attribution"] = "MEASURED_EVIDENCE"

    if result["status"] != FAILED:
        result["status"] = PASS
    return result


# ---------------------------------------------------------------------------
# Attribution analysis validation
# ---------------------------------------------------------------------------


def _iter_keys(value, path="#"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield f"{path}/{key}", key
            yield from _iter_keys(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_keys(item, f"{path}[{index}]")


def _is_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def validate_analysis(path: str, run_dir: str, prepared_state: dict, captures: dict) -> dict:
    """Validate the fixed analysis schema and every cited raw line."""
    errors: list[str] = []
    prepared = prepared_state.get("prepared")
    try:
        analysis = profile.read_json(path)
    except (OSError, ValueError) as error:
        return {"present": True, "valid": False, "errors": [f"unreadable: {error}"]}

    for location, key in _iter_keys(analysis):
        if key in profile.FORBIDDEN_EVIDENCE_KEYS:
            errors.append(f"forbidden_key: {location}")

    if analysis.get("schema") != profile.SCHEMA_ATTRIBUTION:
        errors.append("schema: expected pr15e-attribution-v1")
    source_sha = analysis.get("source_sha")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        errors.append("source_sha: must be a full 40-character SHA")
    elif prepared and source_sha != prepared["source"]["head_sha"]:
        errors.append("source_sha: differs from prepare.json")

    entries = analysis.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries: must be a non-empty list")
        entries = []

    allowed_lane_tools = {
        (entry["lane_id"], entry["tool"]) for entry in profile.required_captures()
    }
    measured_lanes = set()
    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: must be an object")
            continue
        lane_id = entry.get("lane_id")
        tool = entry.get("tool")
        if (lane_id, tool) not in allowed_lane_tools:
            errors.append(f"{label}: lane/tool not in the fixed matrix")
            continue
        category = entry.get("category")
        if category not in profile.ATTRIBUTION_CATEGORIES:
            errors.append(f"{label}: unknown category {category!r}")
        kind = entry.get("kind")
        if kind not in profile.ATTRIBUTION_KINDS:
            errors.append(f"{label}: unknown kind {kind!r}")
            continue
        expected_unit = profile.ATTRIBUTION_KINDS[kind]
        if entry.get("unit") != expected_unit:
            errors.append(
                f"{label}: unit {entry.get('unit')!r} != {expected_unit!r} for {kind}"
            )
        value = entry.get("value")
        if kind == "unknown":
            if value is not None:
                errors.append(f"{label}: unknown kind requires a null value")
        else:
            if not _is_number(value) or float(value) < 0:
                errors.append(f"{label}: value must be a finite non-negative number")
            elif expected_unit == "percent" and float(value) > 100:
                errors.append(f"{label}: percent value above 100")
        interpretation = entry.get("interpretation")
        if interpretation not in profile.ATTRIBUTION_INTERPRETATIONS:
            errors.append(f"{label}: unknown interpretation {interpretation!r}")

        raw_path = entry.get("raw_path")
        if not isinstance(raw_path, str) or not raw_path:
            errors.append(f"{label}: raw_path is required")
            continue
        if raw_path.startswith("/") or ".." in raw_path.split("/"):
            errors.append(f"{label}: raw_path must be capture-relative")
            continue
        full = os.path.join(run_dir, *raw_path.split("/"))
        if not os.path.isfile(full) or os.path.islink(full):
            errors.append(f"{label}: raw_path does not exist as a regular file")
            continue
        cited_sha = entry.get("raw_sha256")
        if cited_sha != profile.sha256_file(full):
            errors.append(f"{label}: raw_sha256 does not match the raw artifact")
        capture = None
        for required in profile.required_captures():
            if raw_path.startswith(required["rel_dir"] + "/"):
                capture = captures[required["capture_id"]]
                break
        if capture is None:
            errors.append(f"{label}: raw_path is not inside a required capture")
        else:
            known = {artifact["name"] for artifact in capture["artifacts"]}
            if raw_path not in known:
                errors.append(f"{label}: raw_path is not listed in the capture manifest")
        line = entry.get("verbatim_source_line")
        symbol = entry.get("symbol")
        if not isinstance(line, str) or not line.strip():
            errors.append(f"{label}: verbatim_source_line is required")
            continue
        if not isinstance(symbol, str) or not symbol:
            errors.append(f"{label}: symbol is required")
            continue
        try:
            text = profile.read_text(full)
        except OSError as error:  # pragma: no cover - defensive
            errors.append(f"{label}: unreadable raw text: {error}")
            continue
        if line not in text:
            errors.append(f"{label}: verbatim_source_line is not in the raw artifact")
            continue
        if symbol not in line:
            errors.append(f"{label}: symbol is not present in the cited line")
        if interpretation == "MEASURED_EVIDENCE":
            if kind == "unknown":
                errors.append(f"{label}: MEASURED_EVIDENCE cannot use kind unknown")
            else:
                representation = _original_representation(value)
                if not representation or representation not in line:
                    errors.append(
                        f"{label}: value is not present in its original numeric form"
                    )
                measured_lanes.add((lane_id, tool))

    coverage = {}
    for entry in profile.required_captures():
        if entry["tool"] != "perf":
            continue
        coverage[entry["capture_id"]] = (
            entry["lane_id"],
            entry["tool"],
        ) in measured_lanes
    return {
        "present": True,
        "valid": not errors,
        "errors": errors,
        "entry_count": len(entries),
        "measured_lane_tools": sorted(f"{lane}/{tool}" for lane, tool in measured_lanes),
        "perf_lane_coverage": coverage,
    }


def _original_representation(value) -> str | None:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = repr(value)
        return text
    return None


# ---------------------------------------------------------------------------
# Sanitization and publication
# ---------------------------------------------------------------------------


def sensitive_hits(text: str, *, host: str | None = None, user: str | None = None) -> list[str]:
    hits = []
    for match in _ABS_PATH_RE.finditer(text):
        hits.append(match.group(0))
    if profile.REPO_ROOT and profile.REPO_ROOT in text:
        hits.append(profile.REPO_ROOT)
    if host:
        for match in re.finditer(rf"\b{re.escape(host)}\b", text):
            hits.append(match.group(0))
    if user and len(user) >= 4:
        for match in re.finditer(rf"\b{re.escape(user)}\b", text):
            hits.append(match.group(0))
    return hits


def _current_host() -> str:
    return socket.gethostname()


def _current_user() -> str | None:
    try:
        import getpass

        return getpass.getuser()
    except Exception:  # pragma: no cover - environment dependent
        return None


def build_publish_manifest(run_dir: str, prepared_state: dict, captures: dict, gates: dict) -> dict:
    prepared = prepared_state["prepared"]
    lanes = []
    for entry in profile.required_captures():
        capture = captures[entry["capture_id"]]
        lanes.append(
            {
                "capture_id": entry["capture_id"],
                "lane_id": entry["lane_id"],
                "tool": entry["tool"],
                "n": entry["n"],
                "class": entry["class"],
                "k": entry["k"],
                "status": capture["status"],
                "sample_count": capture["sample_count"],
                "profiled_query_count": capture["profiled_query_count"],
                "attribution": capture["attribution"],
                "artifacts": capture["artifacts"],
            }
        )
    tools = {}
    for tool, payload in prepared.get("tools", {}).items():
        tools[tool] = payload.get("version") or payload.get("status")
    return {
        "schema": profile.SCHEMA_PROFILE_MANIFEST,
        "status": STATUS_EVIDENCE_COMPLETE,
        "workload": profile.WORKLOAD,
        "source_sha": prepared["source"]["head_sha"],
        "prepare_sha256": prepared_state["sha256"],
        "spec_sha256": prepared["source_lock"]["spec"]["sha256"],
        "protocol_sha256": prepared["source_lock"]["protocol"]["sha256"],
        "adapter_binary_sha256": prepared["build"]["binary_sha256"],
        "corpus": {
            key: value["sha256"]
            for key, value in prepared["corpus"]["corpora"].items()
        },
        "tools": tools,
        "host_fingerprint": prepared["host_fingerprint"],
        "environment": {
            "kernel": prepared["environment"]["kernel"],
            "filesystem": prepared["environment"]["filesystem"],
            "wsl": prepared["environment"]["wsl"],
            "python": prepared["environment"]["python"],
        },
        "gates": gates,
        "lanes": lanes,
        "limitations": prepared.get("limitations", []),
        "raw_evidence_access": "PRIVATE_PENDING_REVIEW",
    }


def publish_manifest(run_dir: str, prepared_state: dict, captures: dict, gates: dict,
                     dest: str | None = None) -> dict:
    payload = build_publish_manifest(run_dir, prepared_state, captures, gates)
    if any(capture["test_fixture"] for capture in captures.values()):
        raise VerificationError(
            "X31_TEST_FIXTURE", "refusing to publish a manifest derived from test fixtures"
        )
    text = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    hits = sensitive_hits(text, host=_current_host(), user=_current_user())
    if hits:
        raise VerificationError(
            "X31_SENSITIVE_CONTENT",
            f"refusing publication; sensitive markers found: {sorted(set(hits))[:5]}",
        )
    destination = dest or PUBLISH_PATH
    if os.path.exists(destination):
        existing = open(destination, "rb").read()
        if existing == text.encode("utf-8"):
            return {"written": False, "path": destination, "sha256": profile.sha256_bytes(existing)}
        raise VerificationError(
            "X28_DESTINATION_EXISTS",
            "a different published manifest already exists; refusing to overwrite",
        )
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(text)
    return {
        "written": True,
        "path": destination,
        "sha256": profile.sha256_bytes(text.encode("utf-8")),
    }


# ---------------------------------------------------------------------------
# Verification entry point
# ---------------------------------------------------------------------------


def evaluate(run_dir: str, deps) -> dict:
    prepared_state = _verify_prepare(run_dir, deps)
    captures = {}
    for entry in profile.required_captures():
        captures[entry["capture_id"]] = _verify_capture(run_dir, entry, prepared_state)

    failures = sorted(
        capture["capture_id"] for capture in captures.values() if capture["status"] == FAILED
    )
    blocked = sorted(
        capture["capture_id"] for capture in captures.values() if capture["status"] == BLOCKED
    )
    passed = sorted(
        capture["capture_id"] for capture in captures.values() if capture["status"] == PASS
    )

    gates = {
        "g05_perf": {
            "status": PASS if len([key for key in passed if key.endswith("/perf")]) == 12 else FAILED,
            "passed": len([key for key in passed if key.endswith("/perf")]),
            "required": 12,
        },
        "g06_heaptrack": {
            "status": PASS
            if len([key for key in passed if key.endswith("/heaptrack")]) == 8
            else FAILED,
            "passed": len([key for key in passed if key.endswith("/heaptrack")]),
            "required": 8,
        },
        "g07_capture_semantics": {
            "status": PASS if len(passed) == 20 else FAILED,
            "passed": len(passed),
            "required": 20,
        },
    }
    primary = profile.primary_lane_ids()
    g09_lanes = {}
    for lane in primary:
        perf = captures[f"{lane}/perf"]
        heap = captures[f"{lane}/heaptrack"]
        ok = (
            perf["status"] == PASS
            and heap["status"] == PASS
            and perf["attribution"] == "MEASURED_EVIDENCE"
        )
        g09_lanes[lane] = {
            "complete": ok,
            "perf_status": perf["status"],
            "heaptrack_status": heap["status"],
            "perf_attribution": perf["attribution"],
        }
    gates["g09_attribution"] = {
        "status": PASS if all(item["complete"] for item in g09_lanes.values()) else FAILED,
        "lanes": g09_lanes,
    }

    missing = sorted(
        capture["capture_id"]
        for capture in captures.values()
        if capture["status"] == BLOCKED
        and any(reason.startswith("capture_missing") for reason in capture["reasons"])
    )
    if prepared_state["violations"] or failures:
        status = STATUS_FAILED
    elif len(passed) == 20:
        status = STATUS_EVIDENCE_COMPLETE
    elif blocked and not missing:
        # Every unobserved lane carries a real environment/tool blocker.
        status = STATUS_BLOCKED
    else:
        status = STATUS_PARTIAL
    if status == STATUS_EVIDENCE_COMPLETE:
        gates["g08_evidence"] = {"status": PASS, "captures": 20}
    else:
        gates["g08_evidence"] = {
            "status": FAILED,
            "passed": len(passed),
            "blocked": blocked,
            "missing": missing,
            "failed": failures,
        }
    return {
        "prepared": prepared_state,
        "captures": captures,
        "gates": gates,
        "status": status,
        "failures": failures,
        "blocked": blocked,
        "missing": missing,
        "passed": passed,
    }


def _render_verification(run_dir: str, evaluation: dict, analysis: dict) -> dict:
    prepared_state = evaluation["prepared"]
    prepared = prepared_state.get("prepared") or {}
    captures = []
    for entry in profile.required_captures():
        capture = evaluation["captures"][entry["capture_id"]]
        captures.append(
            {
                "capture_id": entry["capture_id"],
                "tool": entry["tool"],
                "status": capture["status"],
                "reasons": capture["reasons"],
                "sample_count": capture["sample_count"],
                "profiled_query_count": capture["profiled_query_count"],
                "adapter_pid": capture["adapter_pid"],
                "attribution": capture["attribution"],
                "test_fixture": capture["test_fixture"],
                "artifacts": capture["artifacts"],
            }
        )
    payload = {
        "schema": profile.SCHEMA_VERIFICATION,
        "status": evaluation["status"],
        "run_id": os.path.basename(run_dir),
        "workload": profile.WORKLOAD,
        "prepare_sha256": prepared_state.get("sha256"),
        "source_sha": (prepared.get("source") or {}).get("head_sha"),
        "head_sha": prepared_state.get("head_sha"),
        "head_matches_measured": prepared_state.get("head_sha")
        == (prepared.get("source") or {}).get("head_sha"),
        "prepare_violations": prepared_state["violations"],
        "captures": captures,
        "counts": {
            "required": len(captures),
            "passed": len(evaluation["passed"]),
            "blocked": len(evaluation["blocked"]),
            "missing": len(evaluation["missing"]),
            "failed": len(evaluation["failures"]),
        },
        "gates": {
            "g05_perf": evaluation["gates"]["g05_perf"]["status"],
            "g06_heaptrack": evaluation["gates"]["g06_heaptrack"]["status"],
            "g07_capture_semantics": evaluation["gates"]["g07_capture_semantics"]["status"],
            "g08_evidence": evaluation["gates"]["g08_evidence"]["status"],
            "g09_attribution": evaluation["gates"]["g09_attribution"]["status"],
            "g09_lanes": evaluation["gates"]["g09_attribution"]["lanes"],
        },
        "analysis_valid": analysis.get("valid", False) if analysis.get("present") else None,
        "analysis": {
            key: value
            for key, value in analysis.items()
            if key in ("present", "valid", "errors", "entry_count", "measured_lane_tools")
        },
        "test_fixtures_present": any(
            capture["test_fixture"] for capture in evaluation["captures"].values()
        ),
        "limitations": prepared.get("limitations", []),
    }
    return payload


def verify(args, deps=None) -> int:
    deps = deps or profile.Deps()
    run_dir = profile.resolve_run_dir(args.run, must_exist=True)
    evaluation = evaluate(run_dir, deps)
    analysis = {"present": False}
    if args.analysis:
        analysis = validate_analysis(
            args.analysis, run_dir, evaluation["prepared"], evaluation["captures"]
        )
    payload = _render_verification(run_dir, evaluation, analysis)
    verification_path = os.path.join(run_dir, "verification.json")
    profile.write_json(verification_path, payload)

    publication = None
    if args.publish_manifest:
        if evaluation["status"] != STATUS_EVIDENCE_COMPLETE:
            publication = {
                "written": False,
                "code": "X31_EVIDENCE_INCOMPLETE",
                "detail": f"status is {evaluation['status']}; publication refused",
            }
        elif analysis.get("present") and not analysis.get("valid"):
            publication = {
                "written": False,
                "code": "X31_ANALYSIS_INVALID",
                "detail": "attribution analysis is invalid; publication refused",
            }
        else:
            try:
                publication = publish_manifest(
                    run_dir,
                    evaluation["prepared"],
                    evaluation["captures"],
                    {
                        key: value["status"]
                        for key, value in evaluation["gates"].items()
                    },
                )
            except VerificationError as error:
                publication = {
                    "written": False,
                    "code": error.code,
                    "detail": error.detail,
                }

    summary = {
        "status": payload["status"],
        "run_id": payload["run_id"],
        "counts": payload["counts"],
        "gates": payload["gates"],
        "verification_sha256": profile.sha256_file(verification_path),
        "analysis_valid": payload["analysis_valid"],
        "publication": publication,
    }
    print(profile.canonical_json_bytes(summary).decode("utf-8"))
    exit_codes = {
        STATUS_EVIDENCE_COMPLETE: profile.EXIT_OK,
        STATUS_PARTIAL: profile.EXIT_BLOCKED,
        STATUS_BLOCKED: profile.EXIT_BLOCKED,
        STATUS_FAILED: profile.EXIT_FAILED,
    }
    return exit_codes.get(payload["status"], profile.EXIT_FAILED)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="PR 15E-A fail-closed evidence verification.",
    )
    parser.add_argument("--run", required=True)
    parser.add_argument("--analysis", default=None)
    parser.add_argument("--publish-manifest", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return verify(args)
    except profile.Pr15eError as error:
        print(
            profile.canonical_json_bytes(
                {
                    "status": error.status,
                    "code": error.code,
                    "detail": error.detail,
                }
            ).decode("utf-8")
        )
        print(f"{error.status} {error.code}: {error.detail}", file=sys.stderr)
        return profile.EXIT_BY_STATUS.get(error.status, profile.EXIT_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())

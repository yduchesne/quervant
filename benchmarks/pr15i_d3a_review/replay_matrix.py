#!/usr/bin/env python3
"""Fail-closed, read-only adversarial replay matrix for the F2 review.

This harness lives outside the frozen `benchmarks/pr15i_d3a/` tooling directory.
It copies official F2 evidence into review-owned paths, applies controlled
tampering, reseals the copy, invokes the frozen independent verifier, and
validates every result against a declarative expectation table.

Exit codes:
    0  all eleven scenarios match expectations
    1  one or more scenarios have an unexpected outcome
    2  setup, evidence loading, or harness execution failed
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET = os.path.join(ROOT, "target", "pr15i-d3a")
REVIEW = os.path.join(TARGET, "review")
CASES = os.path.join(REVIEW, "cases")
SERIES = os.path.join(TARGET, "fixup-f2", "paired")
CONTROL = os.path.join(TARGET, "fixup-f2", "aa", "d3af2-base-aa-01")
BASE_ROOT = os.path.join(TARGET, "fixup-f2", "sources", "base")
OFFICIAL_AGGREGATE = os.path.join(TARGET, "fixup-f2", "aggregate")
T0D = "2c74e40d87f319c548c1f485d9b0267208311743"
OFFICIAL_HEAD = "40fd6b92fe646f7bebe4e3076adfac9c8877696f"

PAIRED_RUNS = [
    "d3af2-unbatched-01",
    "d3af2-unbatched-02",
    "d3af2-unbatched-03",
    "d3af2-unbatched-04",
    "d3af2-unbatched-05",
]
PRIMARY_LANES = [
    "pr15d_v1/100000/medium/k100",
    "pr15d_v1/100000/common/k100",
]

SCENARIO_IDS = [
    "positive_aggregate",
    "oracle_tamper",
    "malformed_counter",
    "swapped_binary",
    "missing_member",
    "extra_member",
    "altered_tooling",
    "altered_protocol",
    "duplicate_manifest",
    "four_shared",
    "three_shared",
]

EXPECTATIONS = {
    "positive_aggregate": {
        "result": "PASS",
        "completion_state": "D3AF2_ATTRIBUTION_QUALIFIED",
        "verdict": "D3A_CANDIDATE_HOTSPOT_LOCALIZED",
        "campaign_count": 5,
        "control_qualified": True,
        "component": "candidate_duplicate",
        "lanes": PRIMARY_LANES,
        "runs": PAIRED_RUNS,
    },
    "oracle_tamper": {
        "result": "REJECTED", "status": "INVALID", "code": "V_ORACLE",
    },
    "malformed_counter": {
        "result": "REJECTED", "status": "INVALID", "code": "V_SAMPLE_TYPE",
    },
    "swapped_binary": {
        "result": "REJECTED", "status": "INVALID", "code": "V_BINARY",
    },
    "missing_member": {"result": "REJECTED", "code": "V_SEAL"},
    "extra_member": {"result": "REJECTED", "code": "V_SEAL"},
    "altered_tooling": {"result": "REJECTED", "code": "V_SOURCES"},
    "altered_protocol": {"result": "EXPECTED_KNOWN_GAP"},
    "duplicate_manifest": {"result": "EXPECTED_KNOWN_GAP"},
    "four_shared": {
        "result": "PASS",
        "verdict": "D3A_CANDIDATE_HOTSPOT_LOCALIZED",
        "component": "candidate_duplicate",
    },
    "three_shared": {
        "result": "NOT_LOCALIZED",
        "verdict": "D3A_CANDIDATE_STAGE_UNRESOLVED",
    },
}


def load(name: str):
    path = os.path.join(ROOT, "benchmarks", "pr15i_d3a", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"review_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = load("run")
verify = load("verify")


def sha(path: str) -> str:
    return run.sha256_file(path)


def slot_count(name: str, protocol: dict) -> int:
    if name in {protocol["control_campaign"], protocol["control_retry_campaign"]}:
        return protocol["control_slots_per_campaign"]
    return protocol["slots_per_campaign"]


def write_seal(case_dir: str, protocol: dict) -> None:
    name = os.path.basename(case_dir)
    members = run.required_members(slot_count(name, protocol))
    entries = []
    for relative in members:
        path = os.path.join(case_dir, relative)
        entries.append(
            {"path": relative, "size": os.path.getsize(path), "sha256": sha(path)}
        )
    manifest_path = os.path.join(case_dir, "raw", "manifest.json")
    sealed = entries + [
        {
            "path": "raw/manifest.json",
            "size": os.path.getsize(manifest_path),
            "sha256": sha(manifest_path),
        }
    ]
    seal = {
        "schema": "pr15i-d3a-seal-v1",
        "campaign": name,
        "members": {entry["path"]: entry["sha256"] for entry in sealed},
    }
    with open(os.path.join(case_dir, "raw", "seal.json"), "w", encoding="utf-8") as handle:
        json.dump(seal, handle, sort_keys=True, separators=(",", ":"))


def reseal(case_dir: str, protocol: dict) -> None:
    manifest_path = os.path.join(case_dir, "raw", "manifest.json")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    members = run.required_members(slot_count(os.path.basename(case_dir), protocol))
    manifest["members"] = [
        {
            "path": relative,
            "size": os.path.getsize(os.path.join(case_dir, relative)),
            "sha256": sha(os.path.join(case_dir, relative)),
        }
        for relative in members
    ]
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, sort_keys=True, separators=(",", ":"))
    write_seal(case_dir, protocol)


def copy_case(source: str, name: str) -> str:
    parent = os.path.join(CASES, name)
    if os.path.exists(parent):
        shutil.rmtree(parent)
    os.makedirs(parent)
    destination = os.path.join(parent, os.path.basename(source))
    shutil.copytree(source, destination)
    return destination


def positive_paths() -> tuple[str, str]:
    root = os.path.join(CASES, "positive-aggregate")
    return (
        os.path.join(root, "paired"),
        os.path.join(root, "aa", "d3af2-base-aa-01"),
    )


def copy_positive_aggregate() -> tuple[str, str]:
    copied_series, copied_control = positive_paths()
    parent = os.path.dirname(copied_series)
    if os.path.exists(parent):
        shutil.rmtree(parent)
    os.makedirs(copied_series)
    os.makedirs(os.path.dirname(copied_control))
    for name in PAIRED_RUNS:
        shutil.copytree(os.path.join(SERIES, name), os.path.join(copied_series, name))
    shutil.copytree(CONTROL, copied_control)
    return copied_series, copied_control


def snapshot_tree(*roots: str) -> dict:
    paths = {}
    for root in roots:
        for walk_root, _dirs, files in os.walk(root):
            for name in files:
                path = os.path.join(walk_root, name)
                relative = os.path.relpath(path, root)
                paths[f"{root}::{relative}"] = sha(path)
    return paths


def compare_snapshot(before: dict, after: dict) -> dict:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        key for key in set(before) & set(after) if before[key] != after[key]
    )
    return {
        "unchanged": not (added or removed or changed),
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def load_json(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, value) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))


def find_lane_slot(case_dir: str, lane_id: str, arm: str | None = None):
    slots = os.path.join(case_dir, "raw", "slots")
    for name in sorted(os.listdir(slots)):
        path = os.path.join(slots, name)
        record = load_json(path)
        if arm is not None and record.get("arm") != arm:
            continue
        for lane in record.get("lanes", []):
            if lane.get("id") == lane_id:
                return path, record, lane
    raise RuntimeError(f"lane {lane_id!r} not found in {case_dir}")


def rejection_record(scenario: str, case_dir: str) -> dict:
    try:
        verify.verify_campaign(case_dir, BASE_ROOT, check_external=True)
    except verify.VerifyError as error:
        return {
            "scenario": scenario,
            "actual_result": "REJECTED",
            "status": error.status,
            "code": error.code,
            "detail": error.detail,
        }
    except Exception as error:  # never silently treat as rejection
        return {
            "scenario": scenario,
            "actual_result": "ERROR",
            "status": "ERROR",
            "code": type(error).__name__,
            "detail": str(error),
        }
    return {
        "scenario": scenario,
        "actual_result": "ACCEPTED",
        "status": "PASS",
        "code": None,
        "detail": None,
    }


def scenario_positive_aggregate() -> dict:
    copied_series, copied_control = copy_positive_aggregate()
    aggregate = verify.aggregate_series(copied_series, BASE_ROOT, copied_control)
    decision = aggregate.get("decision") or {}
    return {
        "scenario": "positive_aggregate",
        "actual_result": "PASS",
        "completion_state": aggregate.get("completion_state"),
        "verdict": aggregate.get("verdict"),
        "campaign_count": len(aggregate.get("campaigns", {})),
        "control_qualified": aggregate.get("control_qualified"),
        "component": decision.get("component"),
        "lanes": decision.get("lanes"),
        "runs": decision.get("runs"),
    }


def scenario_oracle_tamper(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "oracle-tamper")
    path, record, lane = find_lane_slot(case, "pr15d_v1/10000/rare/k100")
    lane["doc_ids"] = ["tampered"]
    write_json(path, record)
    reseal(case, protocol)
    return rejection_record("oracle_tamper", case)


def scenario_malformed_counter(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "malformed-counter")
    path, record, lane = find_lane_slot(case, "pr15d_v1/10000/rare/k100", arm="P")
    lane["counter_samples"][0][0] = True
    write_json(path, record)
    reseal(case, protocol)
    return rejection_record("malformed_counter", case)


def scenario_swapped_binary(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "swapped-binary")
    binaries_path = os.path.join(case, "raw", "binaries.json")
    binaries = load_json(binaries_path)
    binaries["arms"]["QP"]["sha256"] = binaries["arms"]["A"]["sha256"]
    write_json(binaries_path, binaries)
    reseal(case, protocol)
    return rejection_record("swapped_binary", case)


def scenario_missing_member() -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "missing-member")
    os.remove(os.path.join(case, "raw", "slots", "slot-01.json"))
    return rejection_record("missing_member", case)


def scenario_extra_member(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "extra-member")
    with open(os.path.join(case, "raw", "extra.json"), "w", encoding="utf-8") as handle:
        handle.write("{}\n")
    reseal(case, protocol)
    return rejection_record("extra_member", case)


def scenario_duplicate_manifest(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "duplicate-manifest")
    manifest_path = os.path.join(case, "raw", "manifest.json")
    manifest = load_json(manifest_path)
    manifest["members"].append(dict(manifest["members"][0]))
    write_json(manifest_path, manifest)
    write_seal(case, protocol)
    return rejection_record("duplicate_manifest", case)


def scenario_altered_tooling(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "altered-tooling")
    sources_path = os.path.join(case, "raw", "sources.json")
    sources = load_json(sources_path)
    sources["tooling"]["benchmarks/pr15i_d3a/verify.py"] = "0" * 64
    write_json(sources_path, sources)
    reseal(case, protocol)
    return rejection_record("altered_tooling", case)


def scenario_altered_protocol(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "altered-protocol")
    auth_path = os.path.join(case, "raw", "authorization.json")
    authorization = load_json(auth_path)
    authorization["protocol_sha256"] = "0" * 64
    write_json(auth_path, authorization)
    sources_path = os.path.join(case, "raw", "sources.json")
    sources = load_json(sources_path)
    sources["protocol_sha256"] = "0" * 64
    write_json(sources_path, sources)
    reseal(case, protocol)
    return rejection_record("altered_protocol", case)


def scenario_shared_run_sets() -> list[dict]:
    runs = []
    for name in verify.load_protocol()["campaigns"]:
        with open(os.path.join(SERIES, name, "sanitized", "summary.json"), encoding="utf-8") as handle:
            runs.append(json.load(handle))
    protocol = verify.load_protocol()
    medium = protocol["candidate_priority"]["lanes"][0]

    four = json.loads(json.dumps(runs))
    four[4]["stage_summary"]["lanes"][medium]["dominant_component"] = "candidate_key"
    stats4 = verify.lane_scoped_five_run_stats(four, protocol)
    decision4 = verify.lane_scoped_five_run_decision(four, stats4, protocol)

    three = json.loads(json.dumps(runs))
    three[3]["stage_summary"]["lanes"][medium]["dominant_component"] = "candidate_key"
    three[4]["stage_summary"]["lanes"][medium]["dominant_component"] = "candidate_key"
    stats3 = verify.lane_scoped_five_run_stats(three, protocol)
    decision3 = verify.lane_scoped_five_run_decision(three, stats3, protocol)
    return [
        {
            "scenario": "four_shared",
            "actual_result": "PASS" if decision4["verdict"] == "D3A_CANDIDATE_HOTSPOT_LOCALIZED" else "NOT_LOCALIZED",
            "verdict": decision4["verdict"],
            "component": decision4.get("component"),
        },
        {
            "scenario": "three_shared",
            "actual_result": "PASS" if decision3["verdict"] == "D3A_CANDIDATE_HOTSPOT_LOCALIZED" else "NOT_LOCALIZED",
            "verdict": decision3["verdict"],
        },
    ]


def dispersion_report() -> dict:
    areas = load_json(os.path.join(SERIES, "five-run-areas-v3.json"))
    aggregate = load_json(os.path.join(SERIES, "independent-aggregate-v3.json"))
    threshold = verify.load_protocol()["run_mad_warning_relative"]
    report = {"threshold": threshold, "lanes": {}}
    for lane_id in verify.load_protocol()["candidate_priority"]["lanes"]:
        lane = areas["lanes"][lane_id]
        entry = {}
        for key in ("candidate_ns", "candidate_share", "intermediate_disjoint_ns", "intermediate_share"):
            stat = lane["scalars"][key]
            if not stat.get("estimable"):
                entry[key] = {"estimable": False}
                continue
            median = stat["median"]
            mad = stat["mad"]
            ratio = (mad / median) if median > 0 else None
            entry[key] = {
                "median": median,
                "mad": mad,
                "mad_over_median": ratio,
                "high_dispersion": bool(ratio is not None and ratio > threshold),
                "max_over_min": (stat["max"] / stat["min"]) if stat["min"] > 0 else None,
            }
        report["lanes"][lane_id] = entry
    report["verdict"] = aggregate["verdict"]
    return report


def _matches(record: dict, expectation: dict) -> tuple[bool, str]:
    expected = expectation["result"]
    actual = record.get("actual_result")
    if expected == "EXPECTED_KNOWN_GAP":
        return actual == "ACCEPTED", f"expected known-gap acceptance, actual {actual!r}"
    if actual != expected:
        return False, f"expected {expected!r}, actual {actual!r}"
    for key in ("status", "code", "completion_state", "verdict", "component", "campaign_count", "control_qualified", "lanes", "runs"):
        if key in expectation and record.get(key) != expectation[key]:
            return False, f"{key}: expected {expectation[key]!r}, actual {record.get(key)!r}"
    return True, ""


def validate_results(records: list[dict], expectations: dict | None = None) -> dict:
    expectations = expectations or EXPECTATIONS
    by_id: dict[str, dict] = {}
    duplicate_ids = []
    for record in records:
        scenario = record.get("scenario")
        if scenario in by_id:
            duplicate_ids.append(scenario)
        by_id[scenario] = record
    expected_ids = list(expectations)
    missing = [scenario for scenario in expected_ids if scenario not in by_id]
    extra = [scenario for scenario in by_id if scenario not in expectations]
    details = []
    unexpected = 0
    for scenario, expectation in expectations.items():
        record = by_id.get(scenario)
        if record is None:
            details.append(
                {
                    "scenario": scenario,
                    "expected_result": expectation["result"],
                    "actual_result": "MISSING",
                    "matched_expectation": False,
                    "failure": "scenario was not executed",
                }
            )
            unexpected += 1
            continue
        matched, reason = _matches(record, expectation)
        if not matched:
            unexpected += 1
        details.append(
            {
                "scenario": scenario,
                "expected_result": expectation["result"],
                "actual_result": (
                    "EXPECTED_KNOWN_GAP"
                    if expectation["result"] == "EXPECTED_KNOWN_GAP" and record.get("actual_result") == "ACCEPTED"
                    else record.get("actual_result")
                ),
                "matched_expectation": matched,
                "failure": reason,
                "record": record,
            }
        )
    for scenario in extra:
        unexpected += 1
        details.append(
            {
                "scenario": scenario,
                "expected_result": "UNEXPECTED",
                "actual_result": by_id[scenario].get("actual_result"),
                "matched_expectation": False,
                "failure": "unexpected scenario",
            }
        )
    for scenario in duplicate_ids:
        unexpected += 1
        details.append(
            {
                "scenario": scenario,
                "expected_result": "UNIQUE",
                "actual_result": "DUPLICATE",
                "matched_expectation": False,
                "failure": "duplicate scenario record",
            }
        )
    inventory_ok = not (missing or extra or duplicate_ids)
    overall = "PASS" if unexpected == 0 and inventory_ok else "FAIL"
    return {
        "overall_status": overall,
        "expected_scenario_count": len(expected_ids),
        "executed_scenario_count": len(records),
        "unexpected_outcome_count": unexpected,
        "missing_scenarios": missing,
        "extra_scenarios": extra,
        "duplicate_scenarios": duplicate_ids,
        "details": details,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="F2 fail-closed review replay matrix")
    parser.add_argument("--out", default=os.path.join(REVIEW, "replay-matrix-final.json"))
    args = parser.parse_args(argv)
    try:
        os.makedirs(CASES, exist_ok=True)
        protocol = verify.load_protocol()
        official_before = snapshot_tree(
            os.path.join(TARGET, "fixup-f2", "aa"),
            os.path.join(TARGET, "fixup-f2", "paired"),
            OFFICIAL_AGGREGATE,
        )
        records = [scenario_positive_aggregate()]
        records.append(scenario_oracle_tamper(protocol))
        records.append(scenario_malformed_counter(protocol))
        records.append(scenario_swapped_binary(protocol))
        records.append(scenario_missing_member())
        records.append(scenario_extra_member(protocol))
        records.append(scenario_duplicate_manifest(protocol))
        records.append(scenario_altered_tooling(protocol))
        records.append(scenario_altered_protocol(protocol))
        records.extend(scenario_shared_run_sets())
        official_after = snapshot_tree(
            os.path.join(TARGET, "fixup-f2", "aa"),
            os.path.join(TARGET, "fixup-f2", "paired"),
            OFFICIAL_AGGREGATE,
        )
        evidence = compare_snapshot(official_before, official_after)
        validation = validate_results(records)
        copied_series, copied_control = positive_paths()
        document = {
            "schema": "pr15i-d3af2-review-replay-matrix-v2",
            "t0d": T0D,
            "official_head": OFFICIAL_HEAD,
            "positive_replay": {
                "series_root": copied_series,
                "control_dir": copied_control,
                "isolated": copied_series != SERIES and copied_control != CONTROL,
            },
            "official_evidence": evidence,
            "dispersion": dispersion_report(),
            **validation,
        }
        if not evidence["unchanged"]:
            document["overall_status"] = "FAIL"
            document["unexpected_outcome_count"] += 1
            document["details"].append(
                {
                    "scenario": "official_evidence_unchanged",
                    "expected_result": "UNCHANGED",
                    "actual_result": evidence,
                    "matched_expectation": False,
                    "failure": "official evidence changed during replay",
                }
            )
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(json.dumps(document, indent=2, sort_keys=True))
    except Exception as error:
        print(f"HARNESS SETUP FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    if document["overall_status"] == "PASS":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

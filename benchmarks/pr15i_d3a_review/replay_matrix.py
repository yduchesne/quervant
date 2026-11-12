#!/usr/bin/env python3
"""Read-only adversarial replay matrix for the F2 independent review.

This harness lives outside the frozen `benchmarks/pr15i_d3a/` tooling directory
and never mutates the official evidence. It copies selected F2 campaigns into
`target/pr15i-d3a/review/`, applies controlled tampering, reseals the copy, and
invokes the frozen independent verifier.
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


def expect_invalid(label: str, case_dir: str) -> dict:
    try:
        verify.verify_campaign(case_dir, BASE_ROOT, check_external=True)
    except verify.VerifyError as error:
        return {"case": label, "result": "REJECTED", "status": error.status, "error": str(error)}
    return {"case": label, "result": "ACCEPTED", "status": "PASS", "error": None}


def scenario_positive_aggregate() -> dict:
    aggregate = verify.aggregate_series(SERIES, BASE_ROOT, CONTROL)
    return {
        "case": "positive_five_run_aggregate_with_lane_scoped_run",
        "result": "PASS",
        "completion_state": aggregate["completion_state"],
        "verdict": aggregate["verdict"],
        "control": aggregate["control_choice"],
    }


def scenario_oracle_tamper(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "oracle-tamper")
    path, record, lane = find_lane_slot(case, "pr15d_v1/10000/rare/k100")
    lane["doc_ids"] = ["tampered"]
    write_json(path, record)
    reseal(case, protocol)
    return expect_invalid("wrong_oracle_in_excluded_lane", case)


def scenario_malformed_counter(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "malformed-counter")
    path, record, lane = find_lane_slot(case, "pr15d_v1/10000/rare/k100", arm="P")
    lane["counter_samples"][0][0] = True
    write_json(path, record)
    reseal(case, protocol)
    return expect_invalid("malformed_counter_in_excluded_lane", case)


def scenario_swapped_binary(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "swapped-binary")
    binaries_path = os.path.join(case, "raw", "binaries.json")
    binaries = load_json(binaries_path)
    binaries["arms"]["QP"]["sha256"] = binaries["arms"]["A"]["sha256"]
    write_json(binaries_path, binaries)
    reseal(case, protocol)
    return expect_invalid("swapped_qp_binary_digest", case)


def scenario_missing_member() -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "missing-member")
    os.remove(os.path.join(case, "raw", "slots", "slot-01.json"))
    return expect_invalid("missing_sealed_member", case)


def scenario_extra_member(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "extra-member")
    with open(os.path.join(case, "raw", "extra.json"), "w", encoding="utf-8") as handle:
        handle.write("{}\n")
    reseal(case, protocol)
    return expect_invalid("extra_unlisted_member", case)


def scenario_duplicate_manifest(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "duplicate-manifest")
    manifest_path = os.path.join(case, "raw", "manifest.json")
    manifest = load_json(manifest_path)
    manifest["members"].append(dict(manifest["members"][0]))
    write_json(manifest_path, manifest)
    write_seal(case, protocol)
    return expect_invalid("duplicate_manifest_entry", case)


def scenario_altered_tooling(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "altered-tooling")
    sources_path = os.path.join(case, "raw", "sources.json")
    sources = load_json(sources_path)
    key = "benchmarks/pr15i_d3a/verify.py"
    sources["tooling"][key] = "0" * 64
    write_json(sources_path, sources)
    reseal(case, protocol)
    return expect_invalid("altered_v3_tooling_identity", case)


def scenario_altered_protocol(protocol: dict) -> dict:
    case = copy_case(os.path.join(SERIES, "d3af2-unbatched-03"), "altered-protocol")
    auth_path = os.path.join(case, "raw", "authorization.json")
    auth = load_json(auth_path)
    auth["protocol_sha256"] = "0" * 64
    write_json(auth_path, auth)
    sources_path = os.path.join(case, "raw", "sources.json")
    sources = load_json(sources_path)
    sources["protocol_sha256"] = "0" * 64
    write_json(sources_path, sources)
    reseal(case, protocol)
    return expect_invalid("altered_v3_protocol_identity", case)


def scenario_shared_run_sets() -> list[dict]:
    runs = []
    for name in verify.load_protocol()["campaigns"]:
        with open(os.path.join(SERIES, name, "sanitized", "summary.json"), encoding="utf-8") as handle:
            runs.append(json.load(handle))
    protocol = verify.load_protocol()
    medium = protocol["candidate_priority"]["lanes"][0]
    common = protocol["candidate_priority"]["lanes"][1]

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
        {"case": "four_of_five_shared_duplicate", "verdict": decision4["verdict"], "component": decision4.get("component")},
        {"case": "three_of_five_shared_duplicate", "verdict": decision3["verdict"], "reason": decision3.get("reason")},
    ]


def dispersion_report() -> dict:
    areas_path = os.path.join(SERIES, "five-run-areas-v3.json")
    aggregate_path = os.path.join(SERIES, "independent-aggregate-v3.json")
    areas = load_json(areas_path)
    aggregate = load_json(aggregate_path)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="F2 read-only adversarial replay matrix")
    parser.add_argument("--out", default=os.path.join(REVIEW, "replay-matrix.json"))
    args = parser.parse_args(argv)
    os.makedirs(CASES, exist_ok=True)
    protocol = verify.load_protocol()
    results = [scenario_positive_aggregate()]
    results.append(scenario_oracle_tamper(protocol))
    results.append(scenario_malformed_counter(protocol))
    results.append(scenario_swapped_binary(protocol))
    results.append(scenario_missing_member())
    results.append(scenario_extra_member(protocol))
    results.append(scenario_duplicate_manifest(protocol))
    results.append(scenario_altered_tooling(protocol))
    results.append(scenario_altered_protocol(protocol))
    results.extend(scenario_shared_run_sets())
    dispersion = dispersion_report()
    document = {
        "schema": "pr15i-d3af2-review-replay-matrix-v1",
        "t0d": "2c74e40d87f319c548c1f485d9b0267208311743",
        "official_head": "40fd6b92fe646f7bebe4e3076adfac9c8877696f",
        "results": results,
        "dispersion": dispersion,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

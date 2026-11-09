#!/usr/bin/env python3
"""PR 15I-C dispatch-isolation — source-neutral machine-code capture wrapper.

Wraps `codegen_capture.py` (exact demangled-symbol selection) to record, for the
A/C/D/E release adapters, which of the relevant methods exist as standalone
symbols and their instruction/byte counts. Diagnostic evidence only: no claim
about cycles, caches or branch prediction is made or supported.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

_spec = importlib.util.spec_from_file_location(
    "pr15i_c_codegen_capture", os.path.join(HERE, "codegen_capture.py"))
codegen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(codegen)

SCHEMA = "pr15i-c-dispatch-codegen-v1"
ARMS = ("A", "C", "D", "E")
TARGETS = (
    "execute_unified",
    "collect_mixed",
    "collect_exact_term_physical",
    "collect_mixed_dispatch_probe",
    "pr15ic_causal_enabled",
)
PAIRS = (("A", "C"), ("A", "D"), ("A", "E"), ("C", "D"), ("C", "E"))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tool_state():
    return {"nm": shutil.which("nm") or "TOOL_UNAVAILABLE",
            "objdump": shutil.which("objdump") or "TOOL_UNAVAILABLE",
            "perf": shutil.which("perf") or "PERF_UNAVAILABLE"}


def _target_list():
    """The dispatch targets, injected into the shared capture helper."""
    codegen.TARGET_SYMBOLS = TARGETS
    return TARGETS


def capture_arm(arm, binary, out_dir):
    _target_list()
    if not os.path.isfile(binary):
        return {"arm": arm, "state": "BINARY_MISSING", "path": binary}
    before = sha256_file(binary)
    record = codegen.capture_arm(arm, binary, tool_state(), out_dir)
    after = sha256_file(binary)
    if before != after:
        record["state"] = "BINARY_MUTATED"
    methods = {}
    sections = (record.get("symbols", {}).get("objdump") or {}).get("sections", {})
    for target in TARGETS:
        entry = sections.get(target)
        if entry is None:
            methods[target] = {"state": "NOT_CAPTURED"}
        elif entry.get("state") == "CAPTURED":
            methods[target] = {"state": "PRESENT",
                               "instructions": entry.get("instructions"),
                               "bytes": entry.get("bytes"),
                               "raw_symbol": entry.get("raw_symbol")}
        else:
            methods[target] = {"state": entry.get("state", "ABSENT")}
    record["methods"] = methods
    record["binary_sha256_after"] = after
    return record


def capture(binaries, out):
    os.makedirs(out, exist_ok=True)
    destination = os.path.join(out, "dispatch-codegen.json")
    if os.path.exists(destination):
        raise SystemExit(f"refusing to replace {destination}")
    tools = tool_state()
    arms = []
    for arm in ARMS:
        binary = binaries.get(arm)
        if not binary:
            arms.append({"arm": arm, "state": "BINARY_MISSING", "path": None})
            continue
        arms.append(capture_arm(arm, binary, out))
    by_arm = {record["arm"]: record for record in arms}
    presence = {}
    for arm in ARMS:
        methods = by_arm.get(arm, {}).get("methods", {})
        presence[arm] = {target: methods.get(target, {}).get("state", "UNKNOWN")
                         for target in TARGETS}
    pairs = {}
    for left, right in PAIRS:
        pairs[f"{left}-vs-{right}"] = {
            "left_sha256": by_arm.get(left, {}).get("binary_sha256"),
            "right_sha256": by_arm.get(right, {}).get("binary_sha256"),
            "identical": by_arm.get(left, {}).get("binary_sha256")
            == by_arm.get(right, {}).get("binary_sha256"),
        }
    payload = {
        "schema": SCHEMA,
        "tools": tools,
        "perf_state": "PERF_UNAVAILABLE" if tools["perf"] == "PERF_UNAVAILABLE"
        else "PERF_AVAILABLE_NOT_USED",
        "targets": list(TARGETS),
        "arms": arms,
        "method_presence": presence,
        "binary_pairs": pairs,
        "notes": [
            "Diagnostic only; no cycle/cache/branch-prediction claim is supported.",
            "A missing method symbol means the compiler did not emit one; it does"
            " not by itself identify which transformation removed it.",
        ],
    }
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def structural_checks(payload):
    """Booleans the classifier must consult before naming a codegen cause."""
    presence = payload["method_presence"]
    return {
        "e_trampoline_present": presence.get("E", {}).get(
            "collect_mixed_dispatch_probe") == "PRESENT",
        "c_physical_present": presence.get("C", {}).get(
            "collect_exact_term_physical") == "PRESENT",
        "d_physical_present": presence.get("D", {}).get(
            "collect_exact_term_physical") == "PRESENT",
        "e_physical_absent": presence.get("E", {}).get(
            "collect_exact_term_physical") != "PRESENT",
        "generic_symbol_present": {arm: presence.get(arm, {}).get("collect_mixed")
                                   for arm in ARMS},
    }


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="dispatch-isolation codegen capture")
    for arm in ARMS:
        parser.add_argument(f"--{arm.lower()}-binary", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    payload = capture({arm: getattr(args, f"{arm.lower()}_binary") for arm in ARMS},
                      os.path.abspath(args.out))
    print(json.dumps(structural_checks(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

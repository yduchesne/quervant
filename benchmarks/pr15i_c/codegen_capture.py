#!/usr/bin/env python3
"""PR 15I-C fixup — diagnostic-only compiler/machine-code capture.

Records exact binary hashes and whatever symbol/disassembly/perf evidence the host
actually provides for the A/G/B release adapters. It is never part of timing
acceptance and never mutates a measured binary.

If a tool or a binary is unavailable the result is a typed `TOOL_UNAVAILABLE` /
`BINARY_MISSING` record, never a fabricated measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCHEMA = "pr15i-c-codegen-capture-v1"
TARGET_SYMBOLS = ("execute_unified", "collect_mixed")
TOOLS = ("nm", "objdump", "llvm-objdump", "perf")
PERF_EVENTS = ("instructions", "cycles", "branches", "branch-misses",
               "cache-misses", "task-clock")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tool_availability():
    availability = {}
    for tool in TOOLS:
        availability[tool] = shutil.which(tool) or "TOOL_UNAVAILABLE"
    return availability


def perf_usable():
    """Return an availability record without requiring elevated privileges."""
    if shutil.which("perf") is None:
        return {"state": "PERF_UNAVAILABLE", "detail": "perf not installed"}
    try:
        result = subprocess.run(["perf", "stat", "-e", "task-clock", "true"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"state": "PERF_UNAVAILABLE", "detail": str(error)}
    if result.returncode != 0:
        return {"state": "PERF_UNAVAILABLE",
                "detail": (result.stderr or "").strip()[-400:]}
    return {"state": "PERF_AVAILABLE", "detail": "perf stat task-clock succeeded"}


def _symbol_table(binary, nm):
    """Return sorted `(address, demangled_name)` pairs from `nm -anC`."""
    result = subprocess.run([nm, "-anC", binary], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        return None, result.stderr.strip()[-400:]
    table = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        address, kind, name = parts
        if kind.lower() not in ("t", "w"):
            continue
        try:
            table.append((int(address, 16), name))
        except ValueError:
            continue
    table.sort()
    return table, None


def _disassemble_range(objdump, binary, start, stop):
    result = subprocess.run(
        [objdump, "-drwC", f"--start-address={start}", f"--stop-address={stop}", binary],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        return None, result.stderr.strip()[-400:]
    return result.stdout, None


def capture_symbols(binary, tools, out_dir, arm):
    """Capture nm/objdump evidence for the target symbols when available."""
    records = {"nm": None, "objdump": None}
    nm = tools.get("nm")
    table = None
    if nm and nm != "TOOL_UNAVAILABLE":
        table, error = _symbol_table(binary, nm)
        result = subprocess.run([nm, "-anC", binary], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, check=False)
        if result.returncode == 0:
            path = os.path.join(out_dir, f"{arm}-nm.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(result.stdout)
            found = {
                symbol: any(
                    line.strip().split(None, 2)[-1] == symbol
                    or line.strip().split(None, 2)[-1].endswith(f"::{symbol}")
                    for line in result.stdout.splitlines()
                    if len(line.split(None, 2)) == 3
                )
                for symbol in TARGET_SYMBOLS
            }
            records["nm"] = {"state": "CAPTURED", "file": os.path.basename(path),
                             "symbols_present": found}
        else:
            records["nm"] = {"state": "TOOL_UNAVAILABLE",
                             "detail": result.stderr.strip()[-400:]}
    else:
        records["nm"] = {"state": "TOOL_UNAVAILABLE", "detail": "nm not installed"}

    objdump = tools.get("objdump")
    if objdump and objdump != "TOOL_UNAVAILABLE" and table:
        addresses = [address for address, _name in table]
        sections = {}
        for symbol in TARGET_SYMBOLS:
            # Exact method selector: the demangled symbol must *end* with the
            # method name, so generic-argument mentions (drop glue, iterator
            # adapters) cannot be mistaken for the method itself.
            match = next(
                (entry for entry in table
                 if entry[1] == symbol or entry[1].endswith(f"::{symbol}")),
                None,
            )
            if match is None:
                sections[symbol] = {"state": "SYMBOL_INLINED_OR_NOT_PRESENT"}
                continue
            start, raw_name = match
            later = [address for address in addresses if address > start]
            stop = later[0] if later else start + 0x4000
            text, error = _disassemble_range(objdump, binary, start, stop)
            if text is None or ">:" not in text:
                sections[symbol] = {"state": "SYMBOL_INLINED_OR_NOT_PRESENT",
                                    "detail": error}
                continue
            path = os.path.join(out_dir, f"{arm}-{symbol}.asm")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            instructions = 0
            byte_count = 0
            for line in text.splitlines():
                if ":" not in line or "\t" not in line:
                    continue
                address_text, rest = line.split(":", 1)
                if not address_text.strip() or any(
                        character not in "0123456789abcdef"
                        for character in address_text.strip().lower()):
                    continue
                fields = rest.split("\t")
                if len(fields) < 2:
                    continue
                mnemonic = fields[-1].strip()
                if not mnemonic:
                    continue
                instructions += 1
                try:
                    byte_count += len(bytes.fromhex(
                        "".join(token for token in fields[1].split()
                                if len(token) == 2)))
                except ValueError:
                    continue
            sections[symbol] = {
                "state": "CAPTURED",
                "file": os.path.basename(path),
                "raw_symbol": raw_name,
                "start_address": hex(start),
                "stop_address": hex(stop),
                "instructions": instructions,
                "bytes": byte_count,
            }
        records["objdump"] = {"state": "CAPTURED", "sections": sections}
    else:
        records["objdump"] = {"state": "TOOL_UNAVAILABLE",
                              "detail": "objdump or symbol table not available"}
    return records


def capture_arm(arm, path, tools, out_dir):
    if not path:
        return {"arm": arm, "state": "BINARY_MISSING", "path": None}
    if not os.path.isfile(path):
        return {"arm": arm, "state": "BINARY_MISSING", "path": path}
    before = sha256_file(path)
    record = {
        "arm": arm,
        "state": "CAPTURED",
        "path": path,
        "binary_sha256": before,
        "binary_bytes": os.path.getsize(path),
    }
    record["symbols"] = capture_symbols(path, tools, out_dir, arm)
    after = sha256_file(path)
    if before != after:
        record["state"] = "BINARY_MUTATED"
    return record


def capture(baseline, control, candidate, out):
    os.makedirs(out, exist_ok=True)
    destination = os.path.join(out, "codegen-capture.json")
    if os.path.exists(destination):
        raise SystemExit(f"refusing to replace {destination}")
    tools = tool_availability()
    arms = [
        capture_arm("A", baseline, tools, out),
        capture_arm("G", control, tools, out),
        capture_arm("B", candidate, tools, out),
    ]
    payload = {
        "schema": SCHEMA,
        "tools": tools,
        "perf": perf_usable(),
        "perf_events": list(PERF_EVENTS),
        "target_symbols": list(TARGET_SYMBOLS),
        "arms": arms,
        "notes": [
            "Diagnostic only: never part of timing acceptance.",
            "A missing symbol may have been inlined; it does not mean the code is absent.",
            "No causal claim is made from instruction counts.",
        ],
    }
    pending = [arm["arm"] for arm in arms if arm["state"] == "BINARY_MISSING"]
    payload["candidate_status"] = "CANDIDATE_PENDING" if "B" in pending else "COMPLETE"
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"codegen capture written to {destination} (candidate={payload['candidate_status']})")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="PR 15I-C diagnostic codegen capture")
    parser.add_argument("--baseline-binary", default=None)
    parser.add_argument("--control-binary", default=None)
    parser.add_argument("--candidate-binary", default=None)
    parser.add_argument("--out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return capture(args.baseline_binary, args.control_binary,
                   args.candidate_binary, os.path.abspath(args.out))


if __name__ == "__main__":
    raise SystemExit(main())

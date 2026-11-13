#!/usr/bin/env python3
"""Read-only Linux CPU topology audit and deterministic core-pair selection."""
from __future__ import annotations
import argparse, json, os, platform

class TopologyError(Exception):
    pass

def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None

def read_cpu(root, cpu):
    base = os.path.join(root, f"cpu{cpu}", "topology")
    pkg = _read(os.path.join(base, "physical_package_id"))
    core = _read(os.path.join(base, "core_id"))
    siblings = _read(os.path.join(base, "thread_siblings_list"))
    if pkg is None or core is None:
        raise TopologyError(f"cpu{cpu}: missing package/core topology")
    try:
        pkg_i, core_i = int(pkg), int(core)
    except ValueError as e:
        raise TopologyError(f"cpu{cpu}: malformed topology: {e}") from e
    return {"cpu": cpu, "package_id": pkg_i, "core_id": core_i,
            "thread_siblings": siblings,
            "scaling_governor": _read(os.path.join(root, f"cpu{cpu}", "cpufreq", "scaling_governor")),
            "scaling_cur_freq": _read(os.path.join(root, f"cpu{cpu}", "cpufreq", "scaling_cur_freq"))}

def select_pair(allowed, root="/sys/devices/system/cpu"):
    info = {cpu: read_cpu(root, cpu) for cpu in sorted(allowed)}
    pairs = []
    for a in sorted(allowed):
        for b in sorted(allowed):
            if a == b: continue
            if info[a]["package_id"] == info[b]["package_id"] and info[a]["core_id"] != info[b]["core_id"]:
                pairs.append((a, b))
    if not pairs:
        raise TopologyError("no distinct physical cores on one package")
    a, b = min(pairs)
    return {"adapter_cpu": a, "controller_cpu": b,
            "adapter": info[a], "controller": info[b],
            "package_id": info[a]["package_id"],
            "distinct_cores": info[a]["core_id"] != info[b]["core_id"]}

def audit(root="/sys/devices/system/cpu", proc_root="/proc"):
    allowed = sorted(os.sched_getaffinity(0))
    cpus = [read_cpu(root, c) for c in allowed]
    pair = select_pair(allowed, root)
    def rd(name):
        return _read(os.path.join(proc_root, name))
    return {"schema": "pr15i-d3c-host-topology-v1", "kernel": platform.uname().release,
            "machine": platform.uname().machine, "cpu_count": os.cpu_count(),
            "allowed_cpus": allowed, "cpus": cpus, "selected_pair": pair,
            "loadavg": rd("loadavg"), "uptime": rd("uptime"),
            "cpu_pressure": rd("pressure/cpu"), "cpuinfo_model": _cpu_model(proc_root)}

def _cpu_model(proc_root):
    try:
        for line in open(os.path.join(proc_root, "cpuinfo")):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        rec = audit()
    except TopologyError as e:
        print(json.dumps({"status": "HS-02", "detail": str(e)}))
        return 3
    text = json.dumps(rec, sort_keys=True, indent=2)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "x") as f: f.write(text + "\n")
    print(text)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

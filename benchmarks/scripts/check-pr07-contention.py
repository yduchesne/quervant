#!/usr/bin/env python3
"""Best-effort, non-destructive benchmark contention detector (PR 7 A04 C01).

Samples ``/proc/stat`` and per-process ``/proc/<pid>/stat`` over a fixed window
and reports whether unrelated CPU consumers are present. It never terminates
processes, never escalates privileges and never modifies the kernel.

Sanitization: the emitted JSON contains no PIDs, command lines, executable paths,
usernames or environment variables. Only anonymized process-class counts are
recorded. Missing/unreadable ``/proc`` yields ``unknown`` (never a false
``clear``).

Test-only snapshot replay: ``--snapshot-a FILE --snapshot-b FILE`` assesses two
pre-recorded snapshots instead of live ``/proc``. ``--dump-snapshot FILE`` records
one live snapshot for fixture construction. The production runner always uses
live ``/proc``.
"""
import argparse
import datetime
import json
import os
import sys
import time

DETECTOR_VERSION = "pr07-contention-1"
SUSPECT_CORE_FRACTION = 0.50
SUSPECT_GUEST_BUSY = 0.70


def fail(reason):
    print(f"CONTENTION FAILED: {reason}", file=sys.stderr)
    sys.exit(70)


def classify(comm):
    name = (comm or "").lower()
    if name.startswith("cargo"):
        return "cargo"
    if name.startswith("rustc") or name.startswith("rust"):
        return "rustc"
    if "criterion" in name:
        return "criterion"
    if name.startswith("java"):
        return "java"
    if name.startswith("python"):
        return "python"
    return "other"


def read_cpu_stat(path):
    try:
        with open(path, encoding="utf-8") as handle:
            line = handle.readline()
    except OSError:
        return None
    fields = line.split()
    if len(fields) < 9 or fields[0] != "cpu":
        return None
    try:
        values = [int(value) for value in fields[1:9]]
    except ValueError:
        return None
    total = sum(values)
    busy = total - values[3] - values[4]  # minus idle and iowait
    return {"total": total, "busy": busy}


def read_proc_snapshot(proc_root):
    stat = read_cpu_stat(os.path.join(proc_root, "stat"))
    if stat is None:
        return None
    procs = {}
    malformed = 0
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return None
    for name in entries:
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(os.path.join(proc_root, name, "stat"), encoding="utf-8") as handle:
                data = handle.read()
            close = data.rfind(")")
            after = data[close + 2 :].split()
            ppid = int(after[1])
            utime = int(after[11])
            stime = int(after[12])
            with open(os.path.join(proc_root, name, "comm"), encoding="utf-8") as handle:
                comm = handle.readline().strip()
        except OSError:
            continue  # disappeared between listing and read
        except (ValueError, IndexError):
            malformed += 1
            continue
        procs[pid] = {"ppid": ppid, "utime": utime, "stime": stime, "comm": comm}
    return {"stat": stat, "procs": procs, "malformed": malformed}


def excluded_pids(procs, self_pid):
    excluded = set()
    current = self_pid
    guard = 0
    while current and current not in excluded and guard < 4096:
        excluded.add(current)
        current = procs.get(current, {}).get("ppid")
        guard += 1
    # Exclude the runner's own subtree (the checker's parent and its descendants),
    # which contains the benchmark/cargo/rustc children. Do NOT expand descendants
    # of the whole init-rooted ancestry chain, which would exclude every process.
    roots = set()
    runner = procs.get(self_pid, {}).get("ppid")
    if runner:
        roots.add(runner)
    changed = True
    while changed:
        changed = False
        for pid, info in procs.items():
            if pid not in excluded and info.get("ppid") in roots:
                excluded.add(pid)
                roots.add(pid)
                changed = True
    return excluded


def assess(snapshot_a, snapshot_b, self_pid, sample_seconds, clk_tck=100):
    reasons = []
    if snapshot_a is None or snapshot_b is None:
        return base_record("unknown", ["proc_unavailable"], sample_seconds)
    ticks = snapshot_b["stat"]["total"] - snapshot_a["stat"]["total"]
    if ticks <= 0:
        return base_record("unknown", ["zero_elapsed_ticks"], sample_seconds)
    busy_delta = snapshot_b["stat"]["busy"] - snapshot_a["stat"]["busy"]
    busy_fraction = max(0.0, busy_delta / ticks)

    excluded = excluded_pids(snapshot_a["procs"], self_pid)
    class_counts = {"cargo": 0, "rustc": 0, "criterion": 0, "java": 0, "python": 0, "other": 0}
    competing = 0
    malformed = int(snapshot_a.get("malformed", 0)) + int(snapshot_b.get("malformed", 0))
    for pid, info in snapshot_a["procs"].items():
        if pid in excluded:
            continue
        other = snapshot_b["procs"].get(pid)
        if other is None:
            continue
        delta = (other["utime"] + other["stime"]) - (info["utime"] + info["stime"])
        if delta < 0:
            reasons.append("pid_reuse_suspected")
            continue
        cores = delta / max(1.0, clk_tck * sample_seconds)
        if cores >= SUSPECT_CORE_FRACTION:
            competing += 1
            class_counts[classify(info.get("comm"))] += 1

    state = "clear"
    if competing > 0:
        state = "suspected"
        reasons.append("unrelated_cpu_consumer")
    elif busy_fraction >= SUSPECT_GUEST_BUSY:
        state = "suspected"
        reasons.append("guest_busy_high")
    if malformed > 0:
        reasons.append("malformed_stat_lines")

    record = base_record(state, reasons, sample_seconds)
    record.update(
        {
            "elapsed_ticks": ticks,
            "cpu_busy_fraction": round(busy_fraction, 6),
            "competing_process_count": competing,
            "process_class_counts": class_counts,
            "processes_total": len(snapshot_a["procs"]),
            "excluded_process_count": len(excluded),
        }
    )
    return record


def base_record(state, reason_codes, sample_seconds):
    return {
        "detector_version": DETECTOR_VERSION,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": state,
        "reason_codes": reason_codes,
        "sample_seconds": sample_seconds,
        "cpu_busy_fraction": None,
        "competing_process_count": 0,
        "process_class_counts": {},
        "processes_total": 0,
        "excluded_process_count": 0,
    }


def dump_snapshot(path):
    snapshot = read_proc_snapshot("/proc")
    if snapshot is None:
        fail("cannot read /proc")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle)


def load_snapshot(path):
    try:
        with open(path, encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except Exception as error:  # noqa: BLE001
        fail(f"cannot read snapshot {path}: {error}")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("procs"), dict):
        normalized = {}
        for key, info in snapshot["procs"].items():
            normalized[int(key)] = {
                "ppid": int(info["ppid"]),
                "utime": int(info["utime"]),
                "stime": int(info["stime"]),
                "comm": info.get("comm", ""),
            }
        snapshot["procs"] = normalized
    return snapshot


def main():
    parser = argparse.ArgumentParser(description="Detect benchmark CPU contention.")
    parser.add_argument("--out", help="write the sanitized JSON record here")
    parser.add_argument("--sample-seconds", type=float, default=2.0)
    parser.add_argument("--snapshot-a", help="test-only snapshot A")
    parser.add_argument("--snapshot-b", help="test-only snapshot B")
    parser.add_argument("--dump-snapshot", help="write one live /proc snapshot and exit")
    parser.add_argument("--self-pid", type=int, default=None, help="test-only self pid override")
    args = parser.parse_args()

    if args.dump_snapshot:
        dump_snapshot(args.dump_snapshot)
        return

    if args.snapshot_a and args.snapshot_b:
        snapshot_a = load_snapshot(args.snapshot_a)
        snapshot_b = load_snapshot(args.snapshot_b)
        sample_seconds = args.sample_seconds or 1.0
    else:
        snapshot_a = read_proc_snapshot("/proc")
        time.sleep(max(0.0, args.sample_seconds))
        snapshot_b = read_proc_snapshot("/proc")
        sample_seconds = args.sample_seconds
    record = assess(
        snapshot_a,
        snapshot_b,
        args.self_pid if args.self_pid is not None else os.getpid(),
        sample_seconds,
    )

    text = json.dumps(record, indent=2) + "\n"
    if args.out:
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, args.out)
    sys.stdout.write(text)
    # Nonzero exit for suspected/unknown so callers can fail closed.
    sys.exit(0 if record["state"] == "clear" else 3)


if __name__ == "__main__":
    main()

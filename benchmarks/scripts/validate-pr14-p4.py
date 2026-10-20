#!/usr/bin/env python3
"""Validate a set of `pr14_p4_v1` qualified benchmark trials.

A completed measurement is not a qualified measurement. This validator rejects
incomplete, contaminated, dirty-tree, non-idle, contended or mixed-condition
trials. `--self-test` exercises the negative cases B02/B04.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

REQUIRED_LANES = {
    ("local-cold", "W09"),
    ("local-warm", "W02"),
    ("local-warm", "W03"),
    ("local-warm", "W04"),
    ("local-warm", "W05"),
    ("local-warm", "W06"),
    ("local-warm", "W07"),
    ("remote-cold", "W01"),
    ("remote-warm", "W02"),
    ("remote-warm", "W03"),
    ("remote-warm", "W04"),
    ("remote-warm", "W05"),
    ("remote-warm", "W06"),
    ("remote-warm", "W07"),
}


def validate(trials):
    errors = []
    if len(trials) < 3:
        errors.append("fewer than three independent trials")
    ids = [t.get("trial") for t in trials]
    if len(set(ids)) != len(ids):
        errors.append("duplicate trial id")
    digests = {t.get("corpus_digest") for t in trials}
    if len(digests) != 1:
        errors.append("mismatched corpus digests")
    for trial in trials:
        name = trial.get("trial", "<unknown>")
        if trial.get("workload") != "pr14_p4_v1":
            errors.append(f"{name}: wrong workload id")
        if not re.fullmatch(r"[0-9a-f]{64}", str(trial.get("corpus_digest", ""))):
            errors.append(f"{name}: invalid corpus digest")
        if trial.get("corpus_docs") != 20000:
            errors.append(f"{name}: corpus doc count mismatch")
        if trial.get("qualified") is not True:
            errors.append(f"{name}: not qualified")
        if trial.get("idle_confirmed") is not True:
            errors.append(f"{name}: missing idle confirmation")
        if trial.get("contention") != "clear":
            errors.append(f"{name}: contention not clear")
        if trial.get("dirty") is not False:
            errors.append(f"{name}: dirty tree")
        if not isinstance(trial.get("warmups"), int) or trial["warmups"] < 3:
            errors.append(f"{name}: fewer than three warmups")
        if not isinstance(trial.get("samples"), int) or trial["samples"] < 20:
            errors.append(f"{name}: fewer than twenty samples")
        if not trial.get("summary"):
            errors.append(f"{name}: missing summary")
        raw = trial.get("raw_csv")
        if not raw or not Path(raw).is_file():
            errors.append(f"{name}: missing raw csv")
            continue
        seen = set()
        with open(raw, newline="") as handle:
            for row in csv.DictReader(handle):
                seen.add((row["lane"], row["workload"]))
        if not REQUIRED_LANES.issubset(seen):
            errors.append(f"{name}: missing required measurements")
        # Cold and warm samples must not be pooled under one label.
        for lane in {lane for lane, _ in seen}:
            if lane not in {"local-cold", "local-warm", "remote-cold", "remote-warm"}:
                errors.append(f"{name}: unknown lane {lane}")
        if ("local-cold", "W09") not in seen and ("remote-cold", "W01") not in seen:
            errors.append(f"{name}: no cold lane measured")
    return errors


def self_test():
    base = {
        "workload": "pr14_p4_v1",
        "trial": "t1",
        "sha": "a" * 40,
        "corpus_docs": 20000,
        "corpus_digest": "b" * 64,
        "warmups": 3,
        "samples": 20,
        "qualified": True,
        "idle_confirmed": True,
        "contention": "clear",
        "dirty": False,
        "raw_csv": None,
        "summary": ["ok"],
    }
    # Use a synthetic CSV so self-test does not depend on prior runs.
    import tempfile

    def trial(**overrides):
        item = dict(base)
        item.update(overrides)
        return item

    tmp = Path(tempfile.mkdtemp()) / "raw.csv"
    with open(tmp, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["lane", "workload", "sample", "micros", "hits", "rss_kib"])
        for lane, workload in REQUIRED_LANES:
            writer.writerow([lane, workload, 0, 1.0, 1, 1])
    negative = {
        "wrong expected count": [trial(), trial(trial="t2"), trial(trial="t3", corpus_docs=19999)],
        "wrong digest": [trial(), trial(trial="t2"), trial(trial="t3", corpus_digest="c" * 64)],
        "missing workload": [trial(), trial(trial="t2"), trial(trial="t3", workload="other")],
        "duplicate trial id": [trial(), trial(), trial()],
        "fewer than three": [trial(), trial(trial="t2")],
        "dirty tree": [trial(), trial(trial="t2"), trial(trial="t3", dirty=True)],
        "missing idle": [trial(), trial(trial="t2"), trial(trial="t3", idle_confirmed=False)],
        "contention unknown": [trial(), trial(trial="t2"), trial(trial="t3", contention="unknown")],
        "contention present": [trial(), trial(trial="t2"), trial(trial="t3", contention="present")],
        "missing measurements": [
            trial(),
            trial(trial="t2"),
            trial(trial="t3", raw_csv=str(tmp) + ".missing"),
        ],
        "too few samples": [trial(), trial(trial="t2"), trial(trial="t3", samples=5)],
        "missing warmups": [trial(), trial(trial="t2"), trial(trial="t3", warmups=0)],
    }
    ok = True
    for name, trials in negative.items():
        for item in trials:
            if item["raw_csv"] is None:
                item["raw_csv"] = str(tmp)
        found = validate(trials)
        if not found:
            print(f"FAIL self-test: {name} was accepted")
            ok = False
    good = [trial(trial="t1", raw_csv=str(tmp)), trial(trial="t2", raw_csv=str(tmp)), trial(trial="t3", raw_csv=str(tmp))]
    if validate(good):
        print(f"FAIL self-test: valid set rejected: {validate(good)}")
        ok = False
    print("PASS self-test" if ok else "FAIL self-test")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="*")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.reports:
        print("no trial reports supplied", file=sys.stderr)
        return 1
    trials = [json.loads(Path(path).read_text()) for path in args.reports]
    errors = validate(trials)
    for error in errors:
        print(f"REJECT: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"PASS: {len(trials)} qualified pr14_p4_v1 trials")
    return 0


if __name__ == "__main__":
    sys.exit(main())

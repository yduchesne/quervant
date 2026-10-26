#!/usr/bin/env python3
"""Read-only strict auditor for three fresh `pr14_p4_v1` qualification trials.

`validate-pr14-p4.py` proves presence of the required lanes and the basic
qualification flags. This auditor adds the checks that validator deliberately
does not perform:

* source SHA and fixed corpus digest equality across all three reports,
* 20,000 documents, three or more warmups, twenty or more samples,
* three distinct trial ids and three distinct raw CSV paths,
* a readable CSV with the exact header and exactly ``14 * samples`` rows,
* sample indices exactly ``0..samples-1`` for every required ``(lane, W06/W07)``
  pair with no duplicates, gaps, NaN/infinite/zero/negative durations,
* the hand-derived hit count for every lane/workload pair (W06/W07 use the
  measured batch response length, not the aggregation group count),
* no measured W08 lane (approved waiver), no unknown lane/workload ids,
* a fresh ``state == clear`` contention record per trial.

The script never mutates its inputs, never contacts the network and never reads
credentials. It prints a deterministic ``PASS PR14F audit`` line or exits
nonzero with exact errors.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
HEADER = ["lane", "workload", "sample", "micros", "hits", "rss_kib"]
EXPECTED_DOCS = 20000
MIN_WARMUPS = 3
MIN_SAMPLES = 20

# Expected `hits` column values exactly as emitted by the runner's `record`
# calls. W06/W07 record the measured batch response length (1 and 3), not the
# aggregation group/document counts asserted by the separate oracle.
REQUIRED = {
    ("local-cold", "W09"): 10000,
    ("local-warm", "W02"): 10000,
    ("local-warm", "W03"): 2000,
    ("local-warm", "W04"): 6000,
    ("local-warm", "W05"): 2500,
    ("local-warm", "W06"): 1,
    ("local-warm", "W07"): 3,
    ("remote-cold", "W01"): 10000,
    ("remote-warm", "W02"): 10000,
    ("remote-warm", "W03"): 2000,
    ("remote-warm", "W04"): 6000,
    ("remote-warm", "W05"): 2500,
    ("remote-warm", "W06"): 1,
    ("remote-warm", "W07"): 3,
}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_raw(raw, root):
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path


def audit_csv(path, samples, name):
    errors = []
    try:
        handle = open(path, newline="", encoding="utf-8")
    except OSError as error:
        return [f"{name}: cannot read raw csv {path}: {error}"]

    with handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != HEADER:
            return [f"{name}: raw csv header {reader.fieldnames!r} != {HEADER!r}"]
        seen = {}
        rows = 0
        for line, row in enumerate(reader, start=2):
            rows += 1
            lane = row.get("lane", "")
            workload = row.get("workload", "")
            pair = (lane, workload)
            if workload == "W08":
                errors.append(f"{name}: W08 must not be measured (approved waiver)")
                continue
            if pair not in REQUIRED:
                errors.append(f"{name}: unknown lane/workload pair {lane}/{workload}")
                continue
            try:
                sample = int(row["sample"], 10)
            except (TypeError, ValueError):
                errors.append(f"{name}: line {line}: invalid sample index")
                continue
            try:
                micros = float(row["micros"])
            except (TypeError, ValueError):
                errors.append(f"{name}: line {line}: invalid micros value")
                continue
            if not math.isfinite(micros) or micros <= 0.0:
                errors.append(f"{name}: line {line}: non-finite/non-positive duration {micros}")
            try:
                hits = int(row["hits"], 10)
            except (TypeError, ValueError):
                errors.append(f"{name}: line {line}: invalid hits value")
                continue
            expected_hits = REQUIRED[pair]
            if hits != expected_hits:
                errors.append(
                    f"{name}: line {line}: {lane}/{workload} hits {hits} != {expected_hits}"
                )
            try:
                int(row["rss_kib"], 10)
            except (TypeError, ValueError):
                errors.append(f"{name}: line {line}: invalid rss_kib value")
            indices = seen.setdefault(pair, [])
            if sample in indices:
                errors.append(f"{name}: line {line}: duplicate sample index {sample}")
            indices.append(sample)
            if sample < 0 or sample >= samples:
                errors.append(
                    f"{name}: line {line}: sample {sample} outside 0..{samples - 1}"
                )

    expected_rows = len(REQUIRED) * samples
    if rows != expected_rows:
        errors.append(f"{name}: {rows} CSV rows != {expected_rows} ({len(REQUIRED)} lanes x {samples})")
    for pair in REQUIRED:
        if pair not in seen:
            errors.append(f"{name}: missing lane pair {pair[0]}/{pair[1]}")
        elif sorted(seen[pair]) != list(range(samples)):
            errors.append(
                f"{name}: {pair[0]}/{pair[1]} sample indices are not exactly 0..{samples - 1}"
            )
    return errors


def audit(report_paths, expected_sha, expected_digest, root=Path(".")):
    errors = []
    if len(report_paths) != 3:
        return [f"exactly three trial reports are required (got {len(report_paths)})"]
    if not SHA_RE.fullmatch(str(expected_sha)):
        return [f"--expected-sha is not 40 lowercase hex: {expected_sha!r}"]
    if not DIGEST_RE.fullmatch(str(expected_digest)):
        return [f"--expected-digest is not 64 lowercase hex: {expected_digest!r}"]

    root = Path(root)
    reports = []
    for report_path in report_paths:
        try:
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            errors.append(f"cannot read report {report_path}: {error}")
            continue
        if not isinstance(report, dict):
            errors.append(f"{report_path}: report is not a JSON object")
            continue
        reports.append((str(report_path), report))
    if errors:
        return errors

    trial_ids = []
    csv_paths = []
    for path, report in reports:
        name = report.get("trial", "<unknown>")
        if report.get("workload") != "pr14_p4_v1":
            errors.append(f"{name}: wrong workload id")
        if report.get("qualified") is not True:
            errors.append(f"{name}: not qualified")
        if report.get("idle_confirmed") is not True:
            errors.append(f"{name}: idle confirmation is not true")
        if report.get("contention") != "clear":
            errors.append(f"{name}: contention is not clear")
        if report.get("dirty") is not False:
            errors.append(f"{name}: dirty tree flag is not false")
        if report.get("sha") != expected_sha:
            errors.append(f"{name}: sha {report.get('sha')!r} != expected {expected_sha}")
        if report.get("corpus_docs") != EXPECTED_DOCS:
            errors.append(f"{name}: corpus_docs {report.get('corpus_docs')!r} != {EXPECTED_DOCS}")
        if report.get("corpus_digest") != expected_digest:
            errors.append(
                f"{name}: corpus_digest {report.get('corpus_digest')!r} != expected {expected_digest}"
            )
        warmups = report.get("warmups")
        if not isinstance(warmups, int) or warmups < MIN_WARMUPS:
            errors.append(f"{name}: warmups {warmups!r} < {MIN_WARMUPS}")
        samples = report.get("samples")
        if not isinstance(samples, int) or samples < MIN_SAMPLES:
            errors.append(f"{name}: samples {samples!r} < {MIN_SAMPLES}")
            continue
        trial = report.get("trial")
        if not isinstance(trial, str) or not trial:
            errors.append(f"{path}: missing trial id")
            continue
        trial_ids.append(trial)
        raw = report.get("raw_csv")
        if not isinstance(raw, str) or not raw:
            errors.append(f"{name}: missing raw_csv")
            continue
        raw_path = resolve_raw(raw, root)
        csv_paths.append((name, raw_path))
        errors.extend(audit_csv(raw_path, samples, name))

    if len(set(trial_ids)) != len(trial_ids):
        errors.append("duplicate trial id")
    resolved = {str(path.resolve()) for _, path in csv_paths}
    if len(csv_paths) == 3 and len(resolved) != 3:
        errors.append("reports do not reference three distinct raw CSV files")
    for _, path in csv_paths:
        try:
            sha256_file(path)
        except OSError as error:
            errors.append(f"cannot hash raw CSV {path}: {error}")

    qualification = root / "target" / "pr14-p4" / "qualification" / expected_sha
    for trial in trial_ids:
        contention_path = qualification / f"pr14-p4-contention-{trial}.json"
        try:
            record = json.loads(contention_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            errors.append(f"{trial}: missing/unreadable contention record {contention_path}: {error}")
            continue
        if not isinstance(record, dict) or record.get("state") != "clear":
            state = record.get("state") if isinstance(record, dict) else record
            errors.append(f"{trial}: contention state {state!r} != 'clear'")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Strict read-only PR 14F trial audit.")
    parser.add_argument("reports", nargs=3, help="three sanitized trial JSON reports")
    parser.add_argument("--expected-sha", required=True, help="40-character source SHA")
    parser.add_argument("--expected-digest", required=True, help="fixed 64-character corpus digest")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent.parent
    errors = audit(args.reports, args.expected_sha, args.expected_digest, root)
    for error in errors:
        print(f"REJECT: {error}", file=sys.stderr)
    if errors:
        return 1
    print("PASS PR14F audit")
    return 0


if __name__ == "__main__":
    sys.exit(main())

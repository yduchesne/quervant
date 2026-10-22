#!/usr/bin/env bash
# M1 performance gate — single-key `IndexWriter::apply` baseline vs M1.
#
# Builds and runs the SAME benchmark source
# (`crates/quervant-core/benches/writer_mutation.rs`) against two revisions in
# isolated worktrees and isolated Cargo target directories:
#
#   baseline : the pre-M1 revision
#   current  : the M1 revision under test
#
# Three independent Criterion runs are performed per revision. The script prints
# every run, the per-configuration medians and an explicit regression
# assessment. Differences whose confidence intervals overlap are reported as
# inconclusive, never as a win.
#
# Usage:
#   bash benchmarks/scripts/m1-single-key-apply.sh [baseline-sha] [current-ref] [runs]
#
# Defaults: baseline `cd3b9ac610e35628587faf38780fda778d53cd94`, current `HEAD`,
# 3 runs. Set KEEP_M1_BENCH_ARTIFACTS=1 to retain the temporary directories.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BASELINE_SHA="${1:-cd3b9ac610e35628587faf38780fda778d53cd94}"
CURRENT_REF="${2:-HEAD}"
RUNS="${3:-3}"
BENCH_SRC="crates/quervant-core/benches/writer_mutation.rs"
MANIFEST_REL="crates/quervant-core/Cargo.toml"

[[ -f "$BENCH_SRC" ]] || { echo "missing benchmark source: $BENCH_SRC" >&2; exit 1; }
case "$RUNS" in
    ''|*[!0-9]*) echo "runs must be a positive integer" >&2; exit 1 ;;
esac
[[ "$RUNS" -ge 3 ]] || { echo "at least three runs are required for qualification" >&2; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/quervant-m1-bench.XXXXXX")"
WORKTREES=()
cleanup() {
    if [[ "${KEEP_M1_BENCH_ARTIFACTS:-0}" == "1" ]]; then
        echo "artifacts kept at $TMP"
        return
    fi
    for wt in "${WORKTREES[@]:-}"; do
        [[ -n "$wt" ]] && git worktree remove --force "$wt" >/dev/null 2>&1 || true
    done
    rm -rf "$TMP"
}
trap cleanup EXIT

echo "== M1 single-key apply benchmark =="
echo "repository : $ROOT"
echo "baseline   : $BASELINE_SHA ($(git rev-parse "$BASELINE_SHA"))"
echo "current    : $CURRENT_REF ($(git rev-parse "$CURRENT_REF"))"
echo "runs       : $RUNS per revision"
echo
echo "== environment =="
echo "kernel     : $(uname -sr)"
echo "cpu        : $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //')"
echo "cpus       : $(nproc)"
echo "tmp fs     : $(stat -f -c %T "$TMP")"
echo "rustc      : $(rustc --version)"
echo "cargo      : $(cargo --version)"
echo "loadavg    : $(cut -d' ' -f1-3 /proc/loadavg)"

BASE_WT="$TMP/baseline"
CUR_WT="$TMP/current"
git worktree add --detach "$BASE_WT" "$BASELINE_SHA" >/dev/null
WORKTREES+=("$BASE_WT")
git worktree add --detach "$CUR_WT" "$CURRENT_REF" >/dev/null
WORKTREES+=("$CUR_WT")

# Install the identical benchmark source and target declaration into both trees.
install_bench() {
    local wt="$1"
    mkdir -p "$wt/crates/quervant-core/benches"
    cp "$BENCH_SRC" "$wt/$BENCH_SRC"
    python3 - "$wt/$MANIFEST_REL" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
if 'name = "writer_mutation"' in text:
    sys.exit(0)
entry = '\n[[bench]]\nname = "writer_mutation"\npath = "benches/writer_mutation.rs"\nharness = false\n'
marker = '\n[dependencies]'
if marker not in text:
    sys.exit('cannot locate [dependencies] in ' + path)
text = text.replace(marker, entry + marker, 1)
open(path, 'w').write(text)
PY
}
install_bench "$BASE_WT"
install_bench "$CUR_WT"

run_revision() {
    local label="$1" wt="$2" target="$3"
    local log
    for run in $(seq 1 "$RUNS"); do
        log="$TMP/${label}-run${run}.log"
        echo
        echo "--- $label run $run/$RUNS (loadavg $(cut -d' ' -f1-3 /proc/loadavg)) ---"
        CARGO_TARGET_DIR="$target" \
            cargo bench --quiet -p quervant-core --bench writer_mutation \
            --manifest-path "$wt/Cargo.toml" >"$log" 2>&1 \
            || { echo "benchmark run failed; log:" >&2; tail -40 "$log" >&2; exit 1; }
        grep -E '^(m1_single_key_apply/|[[:space:]]+time:)' "$log" \
            | sed 's/^/    /' || true
        if ! grep -q '^m1_single_key_apply/' "$log"; then
            echo "no measurements captured; log:" >&2; tail -40 "$log" >&2; exit 1
        fi
    done
}

run_revision baseline "$BASE_WT" "$TMP/target-baseline"
run_revision current "$CUR_WT" "$TMP/target-current"

echo
echo "== aggregate =="
python3 - "$TMP" "$RUNS" "$(git rev-parse "$BASELINE_SHA")" "$(git rev-parse "$CURRENT_REF")" <<'PY'
import glob
import re
import statistics
import sys

tmp, runs, baseline_sha, current_sha = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
UNIT_NS = {
    "ns": 1.0,
    "us": 1e3, "µs": 1e3,
    "ms": 1e6,
    "s": 1e9,
}
TIME_RE = re.compile(
    r"time:\s+\[\s*([0-9.]+)\s+(\S+)\s+([0-9.]+)\s+(\S+)\s+([0-9.]+)\s+(\S+)\s*\]"
)

def parse(path):
    """Return {bench_id: (lower_ns, estimate_ns, upper_ns)}."""
    out, pending = {}, None
    for line in open(path):
        stripped = line.strip()
        if stripped.startswith("m1_single_key_apply/"):
            pending = stripped
            continue
        match = TIME_RE.search(line)
        if match and pending:
            lo, lu, est, eu, hi, hu = match.groups()
            out[pending] = (
                float(lo) * UNIT_NS[lu],
                float(est) * UNIT_NS[eu],
                float(hi) * UNIT_NS[hu],
            )
            pending = None
    return out

rows = {}
for label in ("baseline", "current"):
    for run in range(1, runs + 1):
        path = f"{tmp}/{label}-run{run}.log"
        for bench, triple in parse(path).items():
            rows.setdefault(bench, {}).setdefault(label, []).append(triple)

sha = {"baseline": baseline_sha, "current": current_sha}
print(f"{'configuration':42} {'rev':9} {'run':>3}  {'lower':>12} {'estimate':>12} {'upper':>12}  per-op")
for bench in sorted(rows):
    for label in ("baseline", "current"):
        for index, (lo, est, hi) in enumerate(rows[bench].get(label, []), start=1):
            print(
                f"{bench:42} {label:9} {index:>3}  "
                f"{lo/1000:9.3f} µs {est/1000:9.3f} µs {hi/1000:9.3f} µs  "
                f"{est/100.0:.1f} ns/op"
            )

print()
print("== regression assessment ==")
print(
    f"per-op estimate = estimate_ns / 100 mutations; "
    f"baseline {baseline_sha[:12]}, current {current_sha[:12]}"
)
verdicts = []
for bench in sorted(rows):
    base = rows[bench].get("baseline", [])
    cur = rows[bench].get("current", [])
    if len(base) != runs or len(cur) != runs:
        print(f"{bench}: INCOMPLETE (baseline {len(base)}/{runs}, current {len(cur)}/{runs})")
        verdicts.append("INCOMPLETE")
        continue
    base_estimates = [t[1] for t in base]
    cur_estimates = [t[1] for t in cur]
    base_median = statistics.median(base_estimates)
    cur_median = statistics.median(cur_estimates)
    change = ((cur_median / base_median) - 1.0) * 100.0
    # Conservative overlap test on the union of per-run intervals.
    base_lo, base_hi = min(t[0] for t in base), max(t[2] for t in base)
    cur_lo, cur_hi = min(t[0] for t in cur), max(t[2] for t in cur)
    overlap = not (cur_lo > base_hi or base_lo > cur_hi)
    spread = (max(cur_estimates) - min(cur_estimates)) / cur_median * 100.0
    if overlap:
        verdict = "INCONCLUSIVE (confidence intervals overlap)"
    elif change > 5.0:
        verdict = "REGRESSION"
    elif change < -5.0:
        verdict = "IMPROVEMENT"
    else:
        verdict = "NO MATERIAL CHANGE (non-overlapping, |Δ| <= 5%)"
    verdicts.append(verdict)
    print()
    print(f"{bench}")
    print(f"  baseline median : {base_median/1000:9.3f} µs  ({base_median/100.0:6.1f} ns/op)")
    print(f"  current  median : {cur_median/1000:9.3f} µs  ({cur_median/100.0:6.1f} ns/op)")
    print(f"  change          : {change:+.2f} %")
    print(f"  run spread (cur): {spread:.2f} %")
    print(f"  baseline range  : [{base_lo/1000:.3f}, {base_hi/1000:.3f}] µs")
    print(f"  current range   : [{cur_lo/1000:.3f}, {cur_hi/1000:.3f}] µs")
    print(f"  verdict         : {verdict}")

print()
failed = [v for v in verdicts if v in ("REGRESSION", "INCOMPLETE")]
if failed:
    print(f"M1-PERF: {len(failed)} configuration(s) require attention")
    sys.exit(1)
print("M1-PERF: no material regression detected on the single-key apply() path")
PY

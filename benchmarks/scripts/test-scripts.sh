#!/usr/bin/env bash
# Deterministic tests for the Amendment 04 scripts (A4-T10, T11, T14, T15).
# Uses temporary directories and a fake `perf` injected through PATH. Real
# profiling is not required here.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
note() { echo "  $*"; }
ok() { PASS=$((PASS + 1)); }
bad() { FAIL=$((FAIL + 1)); echo "FAIL: $*"; }

run_expect() {
    local desc="$1" expected="$2"
    shift 2
    set +e
    "$@" >/dev/null 2>&1
    local rc=$?
    set -e
    if [[ "$rc" -eq "$expected" ]]; then
        ok
    else
        bad "$desc (exit $rc, expected $expected)"
    fi
}

echo "== A4-T11 invalid profiling arguments =="
run_expect "unknown mode" 64 bash benchmarks/scripts/profile-pr07.sh --mode bogus --workload rare-2k --out "$TMP/a"
run_expect "unknown workload" 64 bash benchmarks/scripts/profile-pr07.sh --mode perf --workload bogus --out "$TMP/a"
run_expect "missing --out" 64 bash benchmarks/scripts/profile-pr07.sh --mode perf --workload rare-2k
run_expect "missing --mode" 64 bash benchmarks/scripts/profile-pr07.sh --workload rare-2k --out "$TMP/a"

echo "== A4-T10 unavailable profilers report UNAVAILABLE =="
for mode in perf heaptrack; do
    if command -v "$mode" >/dev/null 2>&1; then
        note "$mode is installed; skipping UNAVAILABLE assertion"
        continue
    fi
    set +e
    msg="$(bash benchmarks/scripts/profile-pr07.sh --mode "$mode" --workload rare-2k --out "$TMP/$mode" 2>&1)"
    rc=$?
    set -e
    if [[ "$rc" -eq 2 && "$msg" == *UNAVAILABLE* ]]; then
        ok
    else
        bad "$mode should exit 2 with UNAVAILABLE (got $rc: $msg)"
    fi
done

echo "== A4-T10 fake perf tool produces a captured report =="
mkdir -p "$TMP/bin"
cat >"$TMP/bin/perf" <<'FAKE'
#!/usr/bin/env bash
if [[ "${1:-}" == "record" ]]; then
    out=""
    prev=""
    for arg in "$@"; do
        if [[ "$prev" == "-o" ]]; then out="$arg"; fi
        prev="$arg"
    done
    [[ -n "$out" ]] && printf 'fake perf data\n' >"$out"
    exit 0
fi
echo "fake perf report"
FAKE
chmod +x "$TMP/bin/perf"
if PATH="$TMP/bin:$PATH" bash benchmarks/scripts/profile-pr07.sh --mode perf --workload rare-2k --out "$TMP/perfok" >/dev/null 2>&1; then
    if [[ -s "$TMP/perfok/perf-report.txt" ]]; then
        ok
    else
        bad "fake perf run did not produce perf-report.txt"
    fi
else
    bad "fake perf run failed"
fi

echo "== A4-T14 provenance runs are preserved =="
bash benchmarks/scripts/capture-pr07-env.sh --out "$TMP/env1.txt" >/dev/null
sleep 1
bash benchmarks/scripts/capture-pr07-env.sh --out "$TMP/env2.txt" >/dev/null
if [[ -s "$TMP/env1.txt" && -s "$TMP/env2.txt" ]] && grep -q '^git_sha=' "$TMP/env1.txt" && grep -q '^git_sha=' "$TMP/env2.txt"; then
    ok
else
    bad "env captures missing or empty"
fi

echo "== A4-T15 report schema validator =="
MANIFEST="benchmarks/reports/pr07-amendment04-baseline.json"
run_expect "valid manifest" 0 python3 benchmarks/scripts/validate-report.py "$MANIFEST"

python3 - "$MANIFEST" "$TMP" <<'PY'
import json, sys
src, out = sys.argv[1], sys.argv[2]
base = json.load(open(src))
def write(name, mutate):
    doc = json.loads(json.dumps(base))
    mutate(doc)
    json.dump(doc, open(f"{out}/{name}.json", "w"))
def drop_digest(d): del d["dataset_sha256"]
def false_correct(d): d["correctness_passed"] = False
def bad_numeric(d): d["results"][0]["estimate_ns"] = -1
def dirty(d): d["dirty"] = True
write("no-digest", drop_digest)
write("bad-correct", false_correct)
write("bad-numeric", bad_numeric)
write("dirty", dirty)
PY
run_expect "missing digest rejected" 1 python3 benchmarks/scripts/validate-report.py "$TMP/no-digest.json"
run_expect "false correctness rejected" 1 python3 benchmarks/scripts/validate-report.py "$TMP/bad-correct.json"
run_expect "negative latency rejected" 1 python3 benchmarks/scripts/validate-report.py "$TMP/bad-numeric.json"
run_expect "dirty publishable rejected" 1 python3 benchmarks/scripts/validate-report.py "$TMP/dirty.json"

echo
echo "script tests: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]

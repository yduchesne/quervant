#!/usr/bin/env bash
# Deterministic tests for the Amendment 04 Correction 01 scripts.
# Uses temporary directories, synthetic snapshots and synthetic Criterion output;
# real benchmarking and real /proc stress are not required.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); }
bad() { FAIL=$((FAIL + 1)); echo "FAIL: $*"; }

run_expect() {
    local desc="$1" expected="$2"
    shift 2
    set +e
    "$@" >/dev/null 2>&1
    local rc=$?
    set -e
    if [[ "$rc" -eq "$expected" ]]; then ok; else bad "$desc (exit $rc, expected $expected)"; fi
}

echo "== A4-T11 invalid profiling arguments =="
run_expect "unknown mode" 64 bash benchmarks/scripts/profile-pr07.sh --mode bogus --workload rare-2k --out "$TMP/a"
run_expect "unknown workload" 64 bash benchmarks/scripts/profile-pr07.sh --mode perf --workload bogus --out "$TMP/a"
run_expect "missing --out" 64 bash benchmarks/scripts/profile-pr07.sh --mode perf --workload rare-2k
run_expect "missing --mode" 64 bash benchmarks/scripts/profile-pr07.sh --workload rare-2k --out "$TMP/a"

echo "== A4-T10/C-T21 unavailable profilers report UNAVAILABLE =="
for mode in perf heaptrack; do
    if command -v "$mode" >/dev/null 2>&1; then
        echo "  $mode installed; skipping UNAVAILABLE assertion"
        continue
    fi
    set +e
    msg="$(bash benchmarks/scripts/profile-pr07.sh --mode "$mode" --workload rare-2k --out "$TMP/$mode" 2>&1)"
    rc=$?
    set -e
    if [[ "$rc" -eq 2 && "$msg" == *UNAVAILABLE* ]]; then ok; else bad "$mode should exit 2 with UNAVAILABLE (got $rc)"; fi
done

echo "== A4-T10 fake perf tool produces a captured report =="
mkdir -p "$TMP/bin"
cat >"$TMP/bin/perf" <<'FAKE'
#!/usr/bin/env bash
if [[ "${1:-}" == "record" ]]; then
    out=""; prev=""
    for arg in "$@"; do if [[ "$prev" == "-o" ]]; then out="$arg"; fi; prev="$arg"; done
    [[ -n "$out" ]] && printf 'fake perf data\n' >"$out"
    exit 0
fi
echo "fake perf report"
FAKE
chmod +x "$TMP/bin/perf"
if PATH="$TMP/bin:$PATH" bash benchmarks/scripts/profile-pr07.sh --mode perf --workload rare-2k --out "$TMP/perfok" >/dev/null 2>&1 && [[ -s "$TMP/perfok/perf-report.txt" ]]; then ok; else bad "fake perf run did not produce perf-report.txt"; fi

echo "== C-T14 provenance runs are preserved =="
bash benchmarks/scripts/capture-pr07-env.sh --out "$TMP/env1.txt" >/dev/null
sleep 1
bash benchmarks/scripts/capture-pr07-env.sh --out "$TMP/env2.txt" >/dev/null
if [[ -s "$TMP/env1.txt" && -s "$TMP/env2.txt" ]] && grep -q '^git_sha=' "$TMP/env1.txt"; then ok; else bad "env captures missing"; fi

echo "== C-T15 historical report =="
python3 - "$TMP" <<'PY'
import json, sys
out = sys.argv[1]
base = json.load(open("benchmarks/reports/pr07-amendment04-baseline.json"))
base["status"] = "historical_unqualified"
json.dump(base, open(f"{out}/historical-ok.json", "w"))
base2 = json.loads(json.dumps(base))
del base2["status"]
json.dump(base2, open(f"{out}/historical-unmarked.json", "w"))
PY
run_expect "historical accepted" 0 python3 benchmarks/scripts/validate-report.py --historical "$TMP/historical-ok.json"
run_expect "unmarked v1 rejected in historical mode" 1 python3 benchmarks/scripts/validate-report.py --historical "$TMP/historical-unmarked.json"
run_expect "v1 rejected without --historical" 1 python3 benchmarks/scripts/validate-report.py "$TMP/historical-ok.json"

echo "== C-T01/C-T08 fixture metadata counts and dictionary throughput =="
run_expect "fixture metadata emits" 0 bash -c "cargo run --release -p quervant-core --example pr07_report_metadata >$TMP/meta.json 2>/dev/null"
python3 - "$TMP/meta.json" <<'PY'
import json, sys
records = {r["workload_key"]: r for r in json.load(open(sys.argv[1]))["records"]}
checks = {
    "pr07_search_2000_4seg/phrase-present/k10": 8,
    "pr07_search_2000_4seg/phrase-repeated/k10": 16,
    "pr07_search_2000_4seg/phrase-absent/k10": 0,
    "pr07_search_2000_4seg/term-rare/k10": 1,
    "pr07_search_2000_4seg/term-common/k10": 1000,
    "pr07_phrase_10000_4seg/phrase-present/k10": 40,
    "pr07_search_scaling_10000/term-common/k10": 5000,
    "pr07_search_scaling_100000/term-common/k10": 50000,
}
for key, expected in checks.items():
    got = records[key]["actual_hits"]
    assert got == expected, f"{key}: {got} != {expected}"
assert records["pr07_bm25_reference_control/bm25_equation/fixed_inputs"]["actual_hits"] is None
assert records["pr07_dictionary_2000/dictionary_lookup_present/ctoken"]["actual_hits"] is None
print("metadata ok")
PY
if grep -q 'Throughput::Elements(1)' crates/quervant-core/benches/dictionary.rs; then ok; else bad "dictionary throughput is not Elements(1)"; fi

echo "== C-T03..C-T07 v2 builder + validator =="
python3 - "$TMP" <<'PY'
import json, os, sys
tmp = sys.argv[1]
meta = {
  "schema": "quervant-fixture-metadata-v1",
  "fixture_version": "pr07_amendment04_v1",
  "seed": "0xA404202600000001",
  "records": [
    {"workload_key":"pr07_search_2000_4seg/phrase-present/k10","query_id":"phrase-present","operation":"search","doc_count":2000,"segments":4,"top_k":10,"actual_hits":8,"selectivity_ratio":0.004,"hit_count_applicable":True,"dataset_sha256":"a"*64,"fixture_version":"pr07_amendment04_v1"},
    {"workload_key":"pr07_bm25_reference_control/bm25_equation/fixed_inputs","query_id":"bm25-control","operation":"bm25-control","doc_count":0,"segments":0,"top_k":0,"actual_hits":None,"selectivity_ratio":None,"hit_count_applicable":False,"dataset_sha256":"b"*64,"fixture_version":"pr07_amendment04_v1"}
  ]
}
json.dump(meta, open(f"{tmp}/meta.json","w"))
env = "timestamp_utc=2026-10-14T00:00:00Z\ngit_sha=deadbeef\ngit_dirty=false\nrustc=rustc 1.98.1\nuname=Linux test\nwsl2=true\ncpu_model=test cpu\nfilesystem=ext4\ncriterion_version=0.7.0\n"
open(f"{tmp}/env.txt","w").write(env)
def write_bench(root, key, slope, sample):
    path = os.path.join(root, key, "new")
    os.makedirs(path, exist_ok=True)
    d = {
      "slope":{"point_estimate":slope,"confidence_interval":{"lower_bound":slope*0.9,"upper_bound":slope*1.1}},
      "median":{"point_estimate":slope*1.01,"confidence_interval":{"lower_bound":slope*0.9,"upper_bound":slope*1.2}},
    }
    json.dump(d, open(os.path.join(path,"estimates.json"),"w"))
    json.dump({"iters":[1]*sample,"times":[slope]*sample}, open(os.path.join(path,"sample.json"),"w"))
os.makedirs(f"{tmp}/crit", exist_ok=True)
write_bench(f"{tmp}/crit", "pr07_search_2000_4seg/phrase-present/k10", 1000.0, 30)
write_bench(f"{tmp}/crit", "pr07_bm25_reference_control/bm25_equation/fixed_inputs", 50.0, 30)
json.dump({"state":"clear","reason_codes":[],"cpu_busy_fraction":0.01,"competing_process_count":0,"timestamp_utc":"2026-10-14T00:00:00Z"}, open(f"{tmp}/check.json","w"))
PY
BUILD=(python3 benchmarks/scripts/build-pr07-report.py --criterion-dir "$TMP/crit" --fixture-metadata "$TMP/meta.json" --env-file "$TMP/env.txt" --run-id trial-1 --environment-state qualified --profiler-status UNAVAILABLE --correctness-passed --operator-idle-confirmed --check "$TMP/check.json" --out "$TMP/report.json")
run_expect "builder assembles qualified report" 0 "${BUILD[@]}"
run_expect "validator accepts qualified report" 0 python3 benchmarks/scripts/validate-report.py --fixture-metadata "$TMP/meta.json" "$TMP/report.json"

python3 - "$TMP" <<'PY'
import json, sys
tmp=sys.argv[1]
base=json.load(open(f"{tmp}/report.json"))
def write(name, mutate):
    d=json.loads(json.dumps(base)); mutate(d); json.dump(d, open(f"{tmp}/{name}.json","w"))
def false_zero(d): d["results"][0]["actual_hits"]=0
def wrong_corpus(d): d["results"][0]["doc_count"]=9999
def wrong_ratio(d): d["results"][0]["selectivity_ratio"]=0.5
def nonquery_zero(d): d["results"][1]["actual_hits"]=0
def bad_ci(d): d["results"][0]["ci_lower_ns"]=d["results"][0]["estimate_ns"]+1
def zero_samples(d): d["results"][0]["sample_count"]=0
def false_qualified(d): d["environment_qualification"]["operator_idle_confirmed"]=False
def dirty_qualified(d): d["environment_qualification"]["git_dirty"]=True
def duplicate(d): d["results"].append(json.loads(json.dumps(d["results"][0])))
def extra(d): d["results"][0]["workload_key"]="nope"
write("false-zero", false_zero); write("wrong-corpus", wrong_corpus); write("wrong-ratio", wrong_ratio)
write("nonquery-zero", nonquery_zero); write("bad-ci", bad_ci); write("zero-samples", zero_samples)
write("false-qualified", false_qualified); write("dirty-qualified", dirty_qualified)
write("duplicate", duplicate); write("extra", extra)
PY
for case in false-zero wrong-corpus wrong-ratio nonquery-zero bad-ci zero-samples false-qualified dirty-qualified duplicate extra; do
    run_expect "v2 rejects $case" 1 python3 benchmarks/scripts/validate-report.py --fixture-metadata "$TMP/meta.json" "$TMP/$case.json"
done

# Missing / extra / stale Criterion estimates fail the builder.
rm -rf "$TMP/crit/pr07_bm25_reference_control"
run_expect "builder rejects missing estimate" 1 "${BUILD[@]}"

echo "== C-T09..C-T13 contention detector (synthetic snapshots) =="
python3 - "$TMP" <<'PY'
import json, sys
tmp=sys.argv[1]
def snap(total, busy, procs, malformed=0):
    return {"stat":{"total":total,"busy":busy},"procs":procs,"malformed":malformed}
def proc(ppid, utime, stime, comm="other"):
    return {"ppid":ppid,"utime":utime,"stime":stime,"comm":comm}
# clear: unrelated low-CPU process
a=snap(1000,100,{1:proc(0,10,10),100:proc(1,5,5),101:proc(100,1,1),200:proc(1,10,10)})
b=snap(1300,130,{1:proc(0,12,12),100:proc(1,6,6),101:proc(100,2,2),200:proc(1,11,11)})
json.dump(a,open(f"{tmp}/snap-clear-a.json","w")); json.dump(b,open(f"{tmp}/snap-clear-b.json","w"))
# suspected: unrelated pid 200 consumes 1 core (200 ticks over 2s at 100 Hz)
a2=snap(1000,100,{1:proc(0,10,10),100:proc(1,5,5),101:proc(100,1,1),200:proc(1,10,10,"java")})
b2=snap(1300,230,{1:proc(0,12,12),100:proc(1,6,6),101:proc(100,2,2),200:proc(1,110,110)})
json.dump(a2,open(f"{tmp}/snap-susp-a.json","w")); json.dump(b2,open(f"{tmp}/snap-susp-b.json","w"))
# runner subtree must be excluded: pid 102 (cargo) under runner 100 is high-CPU but excluded
a3=snap(1000,100,{1:proc(0,0,0),100:proc(1,0,0),101:proc(100,0,0),102:proc(100,0,0,"cargo")})
b3=snap(1300,120,{1:proc(0,0,0),100:proc(1,0,0),101:proc(100,0,0),102:proc(100,200,200,"cargo")})
json.dump(a3,open(f"{tmp}/snap-excl-a.json","w")); json.dump(b3,open(f"{tmp}/snap-excl-b.json","w"))
# unknown: zero elapsed ticks
json.dump(a,open(f"{tmp}/snap-zero-a.json","w")); json.dump(a,open(f"{tmp}/snap-zero-b.json","w"))
PY
run_expect "detector clear" 0 python3 benchmarks/scripts/check-pr07-contention.py --snapshot-a "$TMP/snap-clear-a.json" --snapshot-b "$TMP/snap-clear-b.json" --out "$TMP/cont-clear.json"
python3 -c "import json;assert json.load(open('$TMP/cont-clear.json'))['state']=='clear'"
run_expect "detector suspected" 3 python3 benchmarks/scripts/check-pr07-contention.py --snapshot-a "$TMP/snap-susp-a.json" --snapshot-b "$TMP/snap-susp-b.json" --out "$TMP/cont-susp.json"
python3 -c "import json;assert json.load(open('$TMP/cont-susp.json'))['state']=='suspected'"
set +e
python3 benchmarks/scripts/check-pr07-contention.py --snapshot-a "$TMP/snap-excl-a.json" --snapshot-b "$TMP/snap-excl-b.json" --self-pid 101 --out "$TMP/cont-excl.json" >/dev/null 2>&1
rc=$?
set -e
if [[ "$rc" -eq 0 ]] && python3 -c "import json;assert json.load(open('$TMP/cont-excl.json'))['state']=='clear'"; then ok; else bad "runner subtree not excluded"; fi
run_expect "detector unknown on zero ticks" 3 python3 benchmarks/scripts/check-pr07-contention.py --snapshot-a "$TMP/snap-zero-a.json" --snapshot-b "$TMP/snap-zero-b.json" --out "$TMP/cont-zero.json"
python3 -c "import json;assert json.load(open('$TMP/cont-zero.json'))['state']=='unknown'"

echo
echo "script tests: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]

# PR 14F — authorized harness qualification corrections

**Status:** Stage B corrections implemented, tested and committed before any
measurement. Executable scope is limited to the benchmark wrapper, the test-only
runner's report destination, and benchmark harness tests. No `src/`, library,
codec, manifest, public API, dependency, CI or feature-flag change.

## 1. Files changed

| File | Before SHA-256 | After SHA-256 | Change |
|---|---|---|---|
| `crates/quervant-core/tests/pr14_bench_remote.rs` | `c6353ec0…210cadec` | `adb1ddc5…2032ce264` | `QUERVANT_P4_REPORT_DIR` opt-in + `create_new` report write (AD-F05/B1) |
| `benchmarks/scripts/run-pr14-p4.sh` | `bbfb8a35…0ffec322` | `ea92481e…2e80851d7` | Deterministic parser, qualified env array, source SHA, per-trial contention, report redirection, W08 exemption (AD-F06–F09/B2) |
| `benchmarks/scripts/audit-pr14f-trials.py` | — (new) | `832fd7d8…e03d99107` | Strict read-only trial auditor (B3) |
| `benchmarks/scripts/test-pr14f-audit.py` | — (new) | `35c9edfa…9dcb2d5` | 25 stdlib unit tests for the auditor (B3) |
| `benchmarks/scripts/test-scripts.sh` | `2e10dcdf…3f1e9c9f` | `3c430a9e…435d3a83` | Append-only PATH-stub wrapper tests (B4) |

Unchanged: `validate-pr14-p4.py`, `check-pr07-contention.py`,
`pr14_p4_v1.md`, the W08 waiver/decision record, and the three historical
trial JSON files.

## 2. B1 — runner report destination

Only the report-directory selection and the report write changed. Queries,
sampling, timing boundaries, CSV content, JSON keys and the default
`benchmarks/reports/` fallback are untouched.

```rust
let reports = match std::env::var_os("QUERVANT_P4_REPORT_DIR") {
    Some(path) if !path.is_empty() => std::path::PathBuf::from(path),
    Some(_) => panic!("QUERVANT_P4_REPORT_DIR must not be empty"),
    None => std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../benchmarks/reports"),
};
std::fs::create_dir_all(&reports).expect("create benchmark report directory");
let json_path = reports.join(format!("pr14-p4-{trial}.json"));
let mut report_file = std::fs::OpenOptions::new()
    .write(true)
    .create_new(true)
    .open(&json_path)
    .expect("create benchmark report without overwriting an existing attempt");
std::io::Write::write_all(&mut report_file, json.as_bytes()).expect("write benchmark report");
```

`create_new(true)` refuses to overwrite an earlier attempt; failed artifacts
remain inspectable. Report writing stays outside every timed region. Raw CSV
still goes to `target/pr14-p4/`.

## 3. B2 — wrapper

Replaced the `for arg in "$@"` loop with a consuming `while`/`case` parser.
`--trials N` and `--trials=N` both accept a decimal integer `1..20`; missing,
non-numeric, out-of-range and unknown arguments exit `2`.

Qualified invocation is built as an array and always starts with
`env -u QUERVANT_P4_DIAGNOSTIC`, so an inherited diagnostic variable cannot
reach the runner:

```bash
run_env=(env -u QUERVANT_P4_DIAGNOSTIC
         "QUERVANT_P4_TRIAL=$trial"
         "QUERVANT_P4_IDLE_CONFIRMED=$idle"
         "QUERVANT_P4_CONTENTION=$contention"
         "QUERVANT_P4_REPORT_DIR=$report_dir")
if (( diagnostic == 1 )); then
  run_env+=("QUERVANT_P4_DIAGNOSTIC=1")
fi
"${run_env[@]}" cargo test -p quervant-core --all-features \
  --test pr14_bench_remote -- --ignored --exact pr14_p4_benchmark --nocapture --test-threads=1
```

Additional wrapper guarantees:

- `source_sha="$(git rev-parse HEAD)"`, required to match `^[0-9a-f]{40}$`.
- Refuses a tracked dirty tree and missing `QUERVANT_RUSTFS_*` variables.
- `report_dir="target/pr14-p4/reports/$source_sha"` and
  `qualification_dir="target/pr14-p4/qualification/$source_sha"` (both ignored).
- Runs a **fresh live** `check-pr07-contention.py --out
  "$qualification_dir/pr14-p4-contention-${trial}.json"` for every qualified
  attempt, requires detector exit `0`, a non-empty record and `state == clear`.
  Any `suspected`, `unknown`, malformed or missing record fails closed.
- Captures each run log at
  `$qualification_dir/pr14-p4-${trial}-run.log` and requires `1 passed`
  (and `qualified=true` for qualified trials) plus a non-empty report file.
- Invokes `validate-pr14-p4.py --w08-exemption
  benchmarks/reports/pr14-p4-w08-exemption.json` with the fresh reports.

The verified test name is `pr14_p4_benchmark`
(`cargo test -p quervant-core --all-features --test pr14_bench_remote --
--list` → `pr14_p4_benchmark: test`, `1 test, 0 benchmarks`), so X04 was not
triggered.

### Qualified trial count

AD-F07 requires the parser to accept `1..20` but the publication gate to
require exactly three distinct qualified reports. The wrapper therefore rejects
`--trials` other than `3` in qualified mode (exit `2`, before any measurement)
and continues to allow `1..20` in diagnostic mode. This prevents a campaign
that could never publish. The normal qualified path is `--trials=3`.

## 4. B3 — strict auditor

`benchmarks/scripts/audit-pr14f-trials.py` is a pure-stdlib, read-only checker
invoked with exactly three report paths, `--expected-sha` and
`--expected-digest`. It verifies:

- workload id, `qualified`, `idle_confirmed`, `contention == "clear"`,
  `dirty is False`, exact source SHA, 20,000 documents, exact corpus digest;
- `warmups >= 3`, `samples >= 20`, three unique trial ids;
- three distinct raw CSV paths, each readable with the exact header
  `lane,workload,sample,micros,hits,rss_kib`;
- exactly `14 * samples` rows, sample indices exactly `0..samples-1` per
  required pair, no duplicates/gaps, finite positive durations, parseable
  integers;
- expected `hits` per pair: W01/W02/W09 `10000`, W03 `2000`, W04 `6000`,
  W05 `2500`, W06 `1`, W07 `3` (batch response length, as recorded by the
  runner — **not** the aggregation group/document counts);
- no measured W08 lane and no unknown lane/workload id;
- a `state == clear` contention record at
  `target/pr14-p4/qualification/<sha>/pr14-p4-contention-<trial>.json`;
- SHA-256 is computed for every CSV (inputs are never mutated).

`test-pr14f-audit.py` provides 25 stdlib tests over a complete synthetic
14-lane fixture and rejects: bad/stale SHA, mismatched/missing digest,
duplicate trial id, unqualified report, non-clear/unknown/missing contention,
duplicate sample, missing lane, wrong hit count, wrong sample index,
NaN/∞/negative/zero duration, W08 present, unknown lane, short CSV, missing
CSV, shared CSV, wrong header and fewer than three reports. These tests never
substitute for live provider qualification.

**Manifest hash clause.** The task text also asks the auditor to "verify file
hash in manifest". The qualification manifest does not exist before trials
finish; it is generated in Stage E from the trial artifacts. The auditor
therefore computes and validates every artifact hash but cannot compare against
a not-yet-created manifest. Stage E records report/CSV/contention hashes in
`qualification-manifest.json`; a later invariant check compares them. This is
recorded as a known sequencing limitation, not a relaxed gate.

## 5. Deferred (not changed by PR 14F)

- Corpus digest prose in `benchmarks/workloads/pr14_p4_v1.md` describes all
  eight fields, while the runner hashes five field blobs (with `ts` equal to
  `n`). The emitted digest still equals the fixed contract `80ef5615…f8768`
  and every historical report, so the X12 digest gate passes. Correcting the
  prose requires separate human approval (AD-F02); no hasher, oracle or
  expected digest was modified.
- `QUERVANT_P4_IDLE_CONFIRMED` is detected by `std::env::var(...).is_ok()`,
  so any set value (including `0`) reads as true. Qualified runs always set
  `1`; diagnostic runs cannot qualify. Measurement code was not changed.
- `docs/TESTING.md` contains pre-existing committed conflict markers; it is not
  an executable input and was left untouched.

## 6. Stage B verification (before source lock)

| Check | Command | Result |
|---|---|---|
| Shell syntax | `bash -n benchmarks/scripts/run-pr14-p4.sh` | PASS |
| Auditor unit tests | `python3 benchmarks/scripts/test-pr14f-audit.py -v` | PASS, 25/25 |
| Validator negative self-test | `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` | `PASS self-test` |
| Existing script suite | `bash benchmarks/scripts/test-scripts.sh` | PASS, 55/55 |
| Formatting | `cargo fmt --all -- --check` | PASS |
| Runner compilation | `cargo test -p quervant-core --all-features --test pr14_bench_remote --no-run` | PASS |
| Test discovery | `… -- --list` | `pr14_p4_benchmark` present |

`python3 -m unittest discover -s benchmarks/scripts -p 'test-pr14f-audit.py'`
discovers zero tests because the hyphenated filename is not an importable
module name; the plan explicitly permits direct invocation, which is used and
recorded.

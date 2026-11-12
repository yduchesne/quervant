# PR 15I-D3-B-F1.2 — design and invariants

F1.2 is a benchmark-tooling continuation. The optimization candidate, corpus,
oracle, index format, metrics, thresholds and schedule are unchanged.

## Implementation

- **Namespace:** `benchmarks/pr15i_d3_b_f1_2/` is an isolated copy of T2 with a
  nine-key protocol delta, new `pr15i-d3bf12-*` record schemas and the names
  `d3bf12-base-{aa-01,aa-02,01,02,03}` under
  `target/pr15i-d3-b/fixup-f1-2/`.
- **Readiness:** `parse_cpu_ticks`, `read_cpu_ticks`, `measure_host_readiness`,
  `write_host_readiness` in `run.py`; an independently written parser and
  rederivation (`host_readiness_failures`, `verify_host_readiness`) in
  `verify.py`. The controller samples `/proc/stat` seven times after one fixed
  5,000 ms settle, sleeps 1,000 ms between reads, computes integer busy/steal
  per interval and the lower median of six, and seals
  `raw/host-readiness.json`. Readiness is collected after both builds, both
  indexes and the pre-timing snapshots and before the first slot; failure raises
  `D3BF12_HOST_NOT_READY` without slots, manifest or seal.
- **Succession:** `classify_attempt`, `decide_next_attempt`,
  `plan_attempt_succession`, `write_attempt_succession` in `run.py`; independent
  `classify_attempt`, `succession_next`, `verify_succession` and a full-series
  `aggregate_series` in `verify.py`. Every paired campaign seals
  `raw/attempt-succession.json`; the controller reverifies every predecessor and
  refuses an unauthorized suffix before allocating its output. The series
  verifier reopens every predecessor's actual bytes.
- **Publication guard:** inherited `rehearsal_only`/`rehearsal` path refusal.

## Invariants → witnesses

| ID | Witness |
|---|---|
| F12-I01 | `git diff --exit-code` for T0/T1/T2/T3 (recorded in `qa.md`) |
| F12-I02 | production/Cargo diffs empty until the qualified rollback |
| F12-I03 | control build provenance: one canonical path, two builds, identical binaries |
| F12-I04 | exact oracle/index/sentinels in control and campaign |
| F12-I05 | `test_f11_t32`–`t35` deep equality of A/A, gates, lanes, schedule |
| F12-I06 | 16 slots × 9 lanes × 20 samples = 2,880 (`host-readiness.md`, control) |
| F12-I07 | F1.1 drift values untouched; fresh F1.2 samples only |
| F12-I08 | readiness reads OS counters only; `queries_executed: 0` |
| F12-I09 | RD-01–RD-11 duration/threshold cases |
| F12-I10 | RD-19–RD-28 raw-tick rederivation and sealed evidence |
| F12-I11 | RD-27 and `D3BF12_HOST_NOT_READY` ordering |
| F12-I12 | SC-03/06/07/30/31 (`decide_next_attempt`) |
| F12-I13 | SC-01–SC-16, SC-23–SC-25 |
| F12-I14 | SC-04/09/10/13/14/22/58–63 (state machine + series) |
| F12-I15 | positive/replacement/rejected/blocked series rehearsal |
| F12-I16 | verifier imports only its own modules; independent arithmetic |
| F12-I17 | seal/inventory/`V_SEAL`/`V_INVENTORY` tests and N-R14 |
| F12-I18 | exclusive paths and rehearsal publish guard |
| F12-I19 | T3 immutability check (`git diff T3`) |
| F12-I20 | readiness failure is fail-closed; `/proc/stat` limitations documented |
| F12-I21 | `qa.md` stable/MSRV/coverage/Python/FS/RustFS |
| F12-I22 | rollback to BASE `bb7a1035…`, post-rollback QA |
| F12-I23 | full-series chronological attempt list incl. excluded drift |
| F12-I24 | control host fingerprint/CPU pair reused by every paired attempt |

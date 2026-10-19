# PR 14 — P4 real RustFS acceptance (partial)

## Topology executed
- Podman rootless, existing pinned container `quervant-rustfs`,
  `rustfs/rustfs:1.0.1@sha256:1803faef…6a3c`, endpoint `http://127.0.0.1:9000`,
  health `{"status":"ok","version":"1.0.1"}`.
- Test-only credentials sourced from the container environment; not committed
  and not logged.
- Remote prefixes are unique per test/case (`pr14-p4/<tag>/<pid>/<nanos>/case`);
  local cache directories are unique and deleted after each case.

## PR 13 real-provider baseline (executed, all PASS)
| Target | Result |
|---|---|
| `quervant-objectstore --features s3 pr13_s3_rustfs` | 8/8 |
| `quervant-core --all-features pr13_remote` (real) | 3/3 |
| `quervant-core --all-features pr13_remote_proxy` | 7/7 |
| `quervant-objectstore --features s3 pr13_proxy_rustfs` | 5/5 |
| `quervant-core --all-features pr13_oracle` (real) | 1/1 |
| `quervant-core --all-features pr13_oracle_geo` (real) | 1/1 |
| `quervant-core --all-features pr13_crash_rustfs k0` | 5/5 |

## P4 vertical `pr14_storage_vertical`
Local `FsDirectory` and real RustFS are queried through the same
`UnifiedSearcher`/`execute_batch` entry points against the deterministic
`pr14-p4-v1` fixture (two immutable segments, six documents, mixed
lexical/typed/JSON/geo/IP, null/multi states, aggregation, batch).

| Case | Executed | Result |
|---|---|---|
| R02/R04/R06 cold compound local-vs-RustFS equivalence + aggregation | yes | PASS |
| R05 upsert/delete; old snapshot unchanged; new generation; cold reopen | yes | PASS |
| R08/R09 ordered batch S/F/S with aggregation, prior success retained | yes | PASS |
| R10/R11 remote exact/one-over `BatchMemoryBytes` and `BatchResponseBytes` | yes | PASS |
| R12 empty-cache cold bootstrap, no writer state | yes | PASS |
| R15 public cursor + aggregation fail-closed (STOP S2) | yes | PASS |
| Local oracle gates (`r02`, `r04`) | yes | PASS |

Command:
```sh
cargo test -p quervant-core --all-features --test pr14_storage_vertical -- --ignored --test-threads=1
```
Result: **5 real tests passed**, 0 failed; 2 local tests passed separately.

## Phase 1 completion (executed after the initial vertical)
Real RustFS command:
```sh
cargo test -p quervant-core --all-features --test pr14_storage_vertical -- --ignored --test-threads=1
```
Result: **9 passed, 0 failed** (plus 3 local tests):
- **R01** separate-process cold bootstrap: child receives only remote config and
  an empty workspace, opens generation 2, matches the mixed oracle and exact
  aggregation groups.
- **R03** wrong-generation isolation: prefix A sees generation 2; a distinct
  prefix B with one generation sees generation 1 and only its own document.
- **R07** local missing/null/empty/multivalue matrix with geo-distance + `n` tie
  ordering; deterministic across repeated runs.
- **R13/R14** warm reopen reuses the cache with equal results; a pinned reader
  remains consistent; a cache capacity that cannot hold pinned bytes fails closed
  (`Storage(LimitExceeded)`) instead of evicting pinned data; reload after
  releasing pins matches the oracle.
- R02/R04/R05/R06/R08/R09/R10/R11/R12/R15 remain green.

Note: automatic eviction/reload with a capacity smaller than two unpinned
segments is not exercised because the current cache admission returns
`LimitExceeded` rather than evicting under that topology; the pinned-safety
behavior is asserted. This is a documented residual, not a pass claim for
forced-eviction reload.

## Not yet executed (P4 not accepted)
- F01–F10 real proxy/crash faults, each 10 independent iterations.
- B01–B04 benchmark oracle gate, negative validator, and three qualified trials.

## Status
**P4: NOT ACCEPTED (PARTIAL).** Vertical storage/compound/batch/aggregation
evidence is real and green; fault-recovery and qualified benchmark gates remain.
**PR 14: NOT READY** (P4 completion + final-SHA CI).

## Handoff — exact remaining work

### Faults (F01–F10) — `crates/quervant-core/tests/pr14_storage_faults.rs`
1. Copy the harness setup from `tests/pr13_remote_proxy.rs`:
   `#[path = "../../quervant-objectstore/tests/support/mod.rs"] mod support;`,
   `use support::{Fault, Proxy, Rule};`, `parse_host_port`, unique prefix/cache.
2. Publish the `pr14-p4-v1` fixture through `RemoteIndexWriter`, then open a
   fresh `RemoteIndex` through the proxy endpoint.
3. F01/F02/F03: `Fault` on the segment GET (fail first, truncate body, corrupt
   body); assert typed error, no readable partial segment, and a healthy reopen
   equals the oracle. F04: fault the manifest/CURRENT GET. F05: old reader +
   new commit. F06: cancel during delayed GET. F07: retry exhaustion bounds.
   F09/F10: fault during `execute_batch` setup and an S→F→S sequence.
4. Run each stateful case 10 independent iterations with unique prefix/cache;
   `--ignored --test-threads=1`.

### Separate-process cold bootstrap (R01) and crash (F08)
Reuse `tests/pr13_crash_rustfs.rs` child-mode pattern; add a PR 14 child mode
that receives only endpoint/bucket/credentials/prefix and runs the mixed query
plus aggregation, then assert oracle equivalence after `kill`.

### Cache warm/evict (R13/R14)
Use the existing `RemoteConfig`/`SegmentCache` capacity and pin/unpin APIs from
PR 13. Warm: open twice, assert zero segment GETs on the second open and equal
results. Evict: lower cache capacity, drop/unpin, force eviction, reload, and
assert equal results plus bounded disk bytes. Do not delete authoritative
objects.

### Benchmarks (B01–B04)
1. Add `benchmarks/workloads/pr14_p4_v1.md` with ≥20,000 deterministic docs,
   three segments, W01–W10 oracles, seed/digest.
2. Add `tests/pr14_bench_remote.rs` (`#[ignore]`, `s3`) reusing the PR 13
   measurement loop: 3 warmups + ≥20 samples per configuration, raw CSV under
   `target/pr14-p4/`, digest-gated oracle before timing, GET/bytes/retries/cache
   metrics from existing `TransferStats`.
3. Add `benchmarks/scripts/run-pr14-p4.sh` with `--diagnostic` (cannot qualify)
   and qualified mode requiring `--idle-confirmed`, clean tree, 3 independent
   trials, `check-pr07-contention.py --out`, and report validation. Add negative
   validator tests B02/B04.
4. Run three qualified trials on native Linux fs; publish
   `benchmarks/reports/pr14-p4-<sha>.json` and `p4-benchmark-report.md`.

### Final gates
Run all §14 commands on the final committed tree (stable + 1.85.0), PR13
real-provider regressions, P2B/P3/PR14 regressions, coverage, docs and script
tests. Do not claim P4/PR14 ready until F, B and final-SHA CI are observed.

## Phase 2 fault recovery (executed)

Target: `crates/quervant-core/tests/pr14_storage_faults.rs` (`s3` feature,
`--ignored --test-threads=1`). Faults are injected by the PR 13 HTTP proxy in
front of real RustFS; each stateful case runs **10 independent iterations** with
unique prefixes and cache workspaces. Every case asserts the proxy observed the
targeted request before accepting the outcome.

| Case | Injection | Executed | Result |
|---|---|---|---|
| F01 | first segment GET `503` | 10× | PASS (bounded retry can recover; healthy reopen oracle) |
| F02 | segment GET truncated after 16 bytes | 10× | PASS (typed failure, no partial read) |
| F03 | ranged `206` rewritten to `200` | 10× | PASS (integrity/range rejection) |
| F04 | `CURRENT` GET `503` | 10× | PASS (bounded failure, healthy reopen) |
| F05 | old reader + new commit | 10× | PASS (old unchanged, new generation visible) |
| F06 | delayed segment GET, 250 ms timeout/drop | 10× | PASS (bounded cancellation, recovery) |
| F07 | every segment GET `503` | 10× | PASS (bounded retry exhaustion, recovery) |
| F09/F10 | faulted open then healthy S→F→S batch with aggregation | 10× | PASS |
| F08 | separate-process crash at block-before-download checkpoint; SIGKILL; healthy reopen | 10× | PASS |

Command result: **9 tests passed, 0 failed**, 10 iterations each; F08 spawns a separate child process and kills it at the proxy checkpoint.

## Phase 3 benchmark qualification
**NOT EXECUTED.** No workload manifest, runner, negative validator, or qualified
trial was created in this pass. No benchmark claim is made.

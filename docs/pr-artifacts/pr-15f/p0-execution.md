# PR 15F — P0 execution record

**Status:** P0 measurement complete; independent review pending. **No optimization
was implemented and nothing was merged.**

- Initial planning baseline (merged PR #83): `d5f3c0563f352123ce4136d6dbd45a6091cc7aeb`.
- Branch: `dev/pr15f-p0-query-reopen-layout-attribution`.
- Measured source commit (benchmark-only tooling): `80a2fd73245b4e981b635f02bf9c7f136711f4e4`.
- Published summary: [`benchmarks/reports/pr15f/p0-profile-summary.json`](../../../benchmarks/reports/pr15f/p0-profile-summary.json)
  (`schema=pr15f-p0-summary-v1`, SHA-256
  `384c02904cdd9fefecc2050472553b392962e6aa11f254adfa3a321a7c381096`).
- Protected production/frozen tree SHA-256 at measurement:
  `43ea723304c61f5f12f912aef76b98d0131c4d6b6c03b97734fed62462dfc4d8`.
- Corpus manifest SHA-256: `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`.
- Adapter binary SHA-256: `bcbf40d480420219e52f10d703203e98f3bd6c5f198b6e927489778aad4404b7`.
- Reopen probe binary SHA-256: `e5e1aff2bd466065ff7d70826cea812e8353d9bdd854489099d9903114f3f920`.

The report/docs commit is intentionally a different evidence SHA from the measured
source. Only `crates/` byte equality, the protected tree hash and the frozen input
hashes bind the measurements to the accepted optimized implementation.

## Environment

| Item | Value |
|---|---|
| Kernel | Linux 6.18 (WSL2 virtualized), native `ext4` for the checkout and `target/` |
| CPU / memory | 12 logical CPUs / 31 GiB |
| Rust stable | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| Rust MSRV | `1.85.0` toolchain installed and used for every MSRV gate |
| Python | 3.12.3 |
| Java | OpenJDK 21.0.12 (context only; not used for PR 15F measurements) |
| `perf` | wrapper refused the WSL2 kernel; existing PR 15E discovery selected the installed versioned fallback `/usr/lib/linux-tools/6.8.0-147-generic/perf`, `perf version 6.8.12` (`tool_origin=versioned`, `profiler_fallback=true`) |
| Heaptrack | `heaptrack 1.5.0`, `heaptrack_print 1.5.0` |
| Demangler | `GNU c++filt (GNU Binutils for Ubuntu) 2.42` |

No tool was installed, no root escalation was used and no toolchain was
substituted.

## Execution order and results

1. **P0 preflight.** Fetched `origin/main`; it equalled the planning baseline
   exactly. Created the PR branch from it with a clean tracked tree. Recorded the
   frozen input hashes and the published three-engine anchors (status `QUALIFIED`,
   `source_sha=40ca10b…`, 32 lane keys, non-null units). Ran the existing PR 15D,
   PR 15E and PR 15E-B1 test suites (PASS).
2. **Benchmark-only tooling.** Added `benchmarks/pr15f/` and the standalone
   `reopen_probe/` crate. No `crates/` file changed.
3. **Preparation.** Reused PR 15E `prepare` unchanged for the exact measured
   source (`target/pr15e/pr15f-prepared-80a2fd73-01`), then compiled the probe with
   `cargo build --release --locked` and recorded its source/lock/binary hashes.
4. **Query CPU.** Nine fixed warm `perf` lanes, five warmups each, oracle-checked
   replies, real before/after contention probes. All nine captured, 9/9
   `QUALIFIED`, every capture `clear/clear`, zero oracle mismatches, zero lost
   samples.
5. **Reopen timing.** 42 independent `single` probe processes (21 per N) in the
   fixed block-1/block-2 rotation, with four real contention probes. All 21
   samples per N are positive, disjoint and internally consistent.
6. **Reopen CPU.** Two `perf record -g --call-graph dwarf` loop captures:
   128 iterations at 10K and 64 at 100K, zero lost samples, clear probes.
7. **Layout.** Read-only inventory of the same prepared indexes with the public
   `segment::parse_container`; all byte categories and section totals reconcile
   exactly, and file hashes are unchanged before/after.
8. **Allocation (optional).** Heaptrack captured `100K/rare/K100` (30 s) and
   `100K/common/K100` (60 s) with the approved heaptrack 1.5.0 preamble.
9. **Verification and publication.** `verify.py` re-derived every published
   number, refused raw paths/PIDs/attestations, and wrote the sanitized summary.
   `attribution.py` produced strict exclusive/inclusive shares and deterministic
   rankings.

### Query capture matrix

| Lane | Samples | Lost | Profiled replies | Contention |
|---|---:|---:|---:|---|
| 10K absent / K100 | 79,000 | 0 | 80,220 | clear/clear |
| 10K rare / K100 | 79,000 | 0 | 6,923 | clear/clear |
| 10K medium / K100 | 79,000 | 0 | 4,273 | clear/clear |
| 10K common / K100 | 79,000 | 0 | 2,548 | clear/clear |
| 100K absent / K100 | 119,000 | 0 | 20,496 | clear/clear |
| 100K rare / K100 | 123,000 | 0 | 1,144 | clear/clear |
| 100K medium / K100 | 124,000 | 0 | 675 | clear/clear |
| 100K common / K100 | 246,000 | 0 | 767 | clear/clear |
| 100K common / K10 | 245,000 | 0 | 916 | clear/clear |

### Reopen (`target/pr15f/run-02/reopen/single/launches.json`, SHA-256
`2272047f0b0dbdaa8d68edb78b32b485f7f66364e99b8897ebfc8c3a3b796f09`)

| Stage | 10K median (ns) | 10K p95 (ns) | 100K median (ns) | 100K p95 (ns) |
|---|---:|---:|---:|---:|
| `fs_directory_open_ns` | 13,800 | 15,891 | 14,200 | 25,500 |
| `index_open_ns` | 42,806,033 | 43,963,977 | 434,622,398 | 445,024,077 |
| `snapshot_acquire_ns` | 2,639 | 2,999 | 20,088 | 21,302 |
| `reopen_core_ns` | 42,808,431 | 43,966,420 | 434,642,198 | 445,041,861 |
| `reopen_total_ns` | 42,824,322 | 43,980,686 | 434,657,998 | 445,055,541 |

21 samples per N; medians, min, max, p95 (nearest-rank) and median absolute
deviation are in the published summary. This is a **fresh-process** measurement,
not an OS-cold page-cache measurement and not a same-session PR 15D comparison.
The historical build-phase `reopen_ns` anchor (~423.193 ms at 100K) is independent
context only.

### Reopen CPU quality

| N | Iterations | Samples | Lost | Contention |
|---|---:|---:|---:|---|
| 10K | 128 | 21,000 | 0 | clear/clear |
| 100K | 64 | 115,000 | 0 | clear/clear |

### Layout

| N | Total bytes | Bytes/doc | Segment | Manifest | Mutation state | Metadata |
|---|---:|---:|---:|---:|---:|---:|
| 10K | 3,090,037 | 309.004 | 2,129,038 | 636 | 960,180 | 183 |
| 100K | 30,965,025 | 309.650 | 21,364,026 | 636 | 9,600,180 | 183 |

The observed 100K total exactly matches the historical PR 15E three-engine report
anchor `30,965,025` bytes, so the measured index is the same layout generation.
That match is descriptive; it is **not** a compression or performance threshold.

### Allocation (supplementary)

| Lane | Profiled replies | Allocations | Sites | Raw artifact |
|---|---:|---:|---:|---:|
| 100K rare / K100 | 1,070 | 1,294,333 | 10 | 117,480 B |
| 100K common / K100 | 140 | 90,139,348 | 10 | 3,624,249 B |

Allocation counts are coarse heaptrack aggregate records from the private raw
artifacts; they are not a substitution for the mandatory CPU captures and were
not used in the ranking rule.

## Evidence and privacy

Raw `perf.data`, perf reports, heaptrack output, probe stdout, contention logs,
adapter PIDs, command lines and absolute paths remain under the ignored
`target/pr15f/run-02/` tree. Only the sanitized summary and these documents are
tracked. The sanitizer checks hostname, username, absolute Unix/Windows paths,
PIDs, `perf.data`, heaptrack artifacts, `pr15e-attestation-v1` and
`operator_statement`; it refuses publication on any hit.

### Tooling-correction disclosure

A short smoke campaign (`target/pr15f/run-01/`) was executed first to validate the
pipeline. It exposed two analysis-only defects: umbrella frames (adapter root,
`UnifiedSearcher::search_impl`) were treated as disjoint inclusive competitors,
and demangled umbrella symbols were not excluded. Both were corrected **before**
the qualified campaign, and the campaign was re-executed from scratch at the
final measured source `80a2fd73…` into `target/pr15f/run-02/`. `run-01` is
preserved privately but is not evidence for this report. No production code,
capture driver, probe, oracle, frozen fixture or prepared index changed between
the two campaigns.

## Mandatory local QA (final tree, before the docs commit)

| Command | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15f -p 'test_*.py' -v` | PASS — 48 tests |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | PASS — 83 tests |
| `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py' -v` | PASS — 64 tests |
| `python3 -m unittest discover -s benchmarks/pr15e_b1 -p 'test_*.py' -v` | PASS — all tests |
| `cargo fmt --all -- --check` / `cargo +1.85.0 fmt --all -- --check` | PASS / PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 2,227 tests |
| `cargo test --workspace --all-targets --all-features` | PASS — 2,231 tests |
| `cargo +1.85.0 test --workspace --all-targets` | PASS — 2,227 tests |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2,231 tests |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — 92.52% line coverage |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 script tests |
| Probe `cargo build --release --locked` (stable and 1.85.0) | PASS / PASS |
| Probe `cargo test --locked` (stable and 1.85.0) | PASS — 11 tests each |
| Probe `cargo fmt -- --check` (stable and 1.85.0) | PASS / PASS |
| `git diff --check` | PASS |
| `python3 -m json.tool benchmarks/reports/pr15f/p0-profile-summary.json` | PASS |

Coverage is measured across all workspace production crates with all features; the
standalone benchmark probe is not counted as production code. The real
`FsDirectory`/public-engine vertical slice is the campaign above
(prepare → nine perf captures → 42 fresh reopen processes → two reopen perf loops →
two inventories → allocation → verify → attribution → publication). No ObjectStore
or RustFS code changed, so a new real RustFS campaign is `NOT_APPLICABLE` for PR
15F; prior PR 15E acceptance evidence remains authoritative.

## Remote status

The branch had not been pushed when this record was written; hosted exact-head
`rust`, `msrv` and `rustfs` jobs are therefore **BLOCKED**, not green. Independent
reviewer sign-off is **pending**. See
[`p0-qualification.md`](p0-qualification.md) for the gate matrix and
[`p0-decision-log.md`](p0-decision-log.md) for every triggered decision rule.

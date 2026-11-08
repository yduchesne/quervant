# PR 15I-C — Correctness execution record

Candidate `C_MEASURED_SHA = 395e05c629c5929f0164764c51c5a1b60b8acd1c`.
The candidate was measured against the effective merged PR 15I-B base
`f70cde62e709383d82693ad548a8c69c7f772bef`.

## 1. In-tree Rust tests (candidate)

| Group | Module / file | Count | Result |
|---|---|---|---|
| `C-U` unit + differential | `search::unified::c15i_tests` | 16 | PASS |
| `C-U` operator-level | `search::execute::c15i_physical_tests` | 6 | PASS |
| `C-I` integration | `tests/pr15i_c_physical.rs` | 12 | PASS |
| Pre-existing PR15E | `search::unified::phase4_tests` | 8 | PASS |
| Pre-existing PR15H-B | `search::unified::b_tests` | 6 | PASS |
| Pre-existing ledger | `search::execute::budget_tests` | 40 | PASS |
| Whole `search::` module | — | 333 | PASS |
| Whole `quervant-core` lib | — | 1024 (1 ignored) | PASS |

Command results:

```
cargo fmt --all -- --check                                    PASS
cargo +1.85.0 check --locked -p quervant-core                 PASS
cargo +1.85.0 clippy -p quervant-core --all-targets -D warnings            PASS
cargo +1.85.0 clippy -p quervant-core --all-targets --all-features -D warnings  PASS
cargo +1.85.0 test -p quervant-core --lib search::unified::c15i_tests     16 passed
cargo +1.85.0 test -p quervant-core --lib search::execute::c15i_physical_tests  6 passed
cargo +1.85.0 test -p quervant-core --test pr15i_c_physical               12 passed
```

## 2. Invariant coverage

All fourteen `C-INV01..C-INV14` invariants from
`invariant-traceability.md` were exercised by executed tests. Highlights:

* `C-INV01/02/03`: exhaustive `M × K` matrix (`C-U05`, `C-U37`), a 64-case
  deterministic generated differential with seed `0x15_1C_EA_07` (`C-U08`), and
  `f64::to_bits` equality on all returned hits (`C-U09`, `C-U34`, `C-I02`).
* `C-INV04`: sort column deliberately unequal to the logical key and reversed
  (`C-U10`, `C-I04`); Missing/Null/Unicode states and a `label` sort (`C-U11`,
  `C-U12`).
* `C-INV05/06/07`: exact/one-below work, scanned-occurrence, candidate-entry and
  candidate-byte parity between the fast and forced-generic paths (`C-U14`,
  `C-U15`, `C-U16`, `C-U17`, `C-I21`), with the virtual matched/scored peaks
  reserved before any key or heap work (`C-U21`, `C-U22`).
* `C-INV08/09`: losing-candidate validation and duplicate-key rejection are the
  unchanged borrowed-Keyword helper (`C-U25`); the pre-existing
  `b_fixup_losing_keyword_payload_invalid_utf8_fails_before_discard` still passes
  and still covers the corrupt-losing-value ordering.
* `C-INV12`: test-only witnesses assert `matched_set_allocations = 0`,
  `scored_map_allocations = 0`, `scalar_scores = M`, `callbacks = M`, and a zeroed
  segment ledger at the first callback (`C-U04`, `C-U29`, `C-U40`).
* `C-INV14`: the full excluded-shape matrix plus `retain = true` and batch absence
  (`C-U03`, `C-U26`), and the two-segment and compaction integration paths
  (`C-I06`, `C-I07`, `C-I08`).

## 3. Python harness tests

```
python3 -m unittest discover -s benchmarks/pr15i_c -p 'test_*.py'   41 tests OK
python3 -m py_compile benchmarks/pr15i_c/run.py benchmarks/pr15i_c/verify.py   OK
```

| Group | Tests | Result |
|---|---|---|
| `C-V` verifier adversarial matrix (synthetic fixtures) | 29 | PASS |
| Controller fail-closed / derivation | 12 | PASS |

## 4. Real-boundary status

| Gate | Status | Reason |
|---|---|---|
| Local `FsDirectory` commit → close → reopen → query | **EXECUTED** (`C-I01…I09`, `C-I17…I24`) | real local filesystem |
| PIT pinning across a new generation | **EXECUTED** (`C-I05`) | real `IndexWriter::pin` |
| Compaction to one segment after retention deletes | **EXECUTED** (`C-I08`) | real `compact()` |
| Two-segment fallback | **EXECUTED** (`C-I06`, `C-I07`) | real two-commit index |
| Pinned RustFS S3-compatible cold bootstrap / fault proxy | **BLOCKED (C-P13)** | no container runtime on the host (`docker` absent), so the `#[ignore]` real-service suites could not be executed |
| Hosted CI | **PENDING** | not run by this agent |

No fake ObjectStore was substituted for a required real-boundary test.

## 5. Declared evidence gaps (not waived)

1. `C-U19` synthetic `InvalidScore`: impossible without a test-only constructor
   inside the protected `search/score.rs` (see `budget-and-error-parity.md` §4).
2. `C-U23`/`C-F07`/`C-F08` corrupt logical-key injection: no production or
   test seam exists inside the allowlist; the pre-existing PR07/PR15 key-failure
   tests cover the generic path, and the score-before-key ordering is covered
   structurally by `C-U19`.
3. `C-U28`/`C-R06` v1-vs-v2 segment interop: the 15I-B suite already owns this
   acceptance; C did not modify segment bytes (12 way byte-identical rebuilds).
4. Baseline-side stage profile: structurally impossible (see
   `diagnostic-stage-profile.md` §4).

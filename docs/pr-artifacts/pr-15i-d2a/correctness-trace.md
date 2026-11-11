# PR 15I-D2-A — correctness trace and semantic feasibility

## Invariant trace

| Invariant | Evidence |
|---|---|
| INV-01 production source identical to BASE | `git diff 9429dce..T0 -- crates/quervant-core/src crates/quervant-core/Cargo.toml` is empty; scratch reverse proof `VERIFIED` |
| INV-02 A has no probe code; Q/P one binary; only JSON op differs | binaries `8d33…` vs `18205…`; Q slots carry no probe fields; P carries them; `raw/mode-proof.json` |
| INV-03 nested score spans are non-overlapping | `score_map_ns`, `score_owner_ns`, `score_accumulate_ns` partition `score_vector_ns` within the frozen tolerance; 0/1440 violations in both campaigns |
| INV-04 probe collection outside `engine_ns` | adapter `query_probe` takes the recorder after `query()` returns; no probe fields in Q |
| INV-05 counted BM25 calls, no per-candidate timer | `bm25_calls` inserted immediately before each real `bm25` call; 0/1/4999/12500/49999 counters verified |
| INV-06 exact results | independent PR15D oracle matches every timed query in all three campaigns |
| INV-07 A/QP committed index bytes identical | A/QP digest equality per N and frozen 100K LZ4 sentinels |
| INV-08 contention/source/oracle/intrusion gates | `verify.py` PASS; all 128 probes clear; A/A qualified |
| INV-09 durable evidence outside `target/` | three exclusive archives plus `.sha256`; round-trip re-verification |
| INV-10 no inferred D2-B design | verdict `D2A_SCORE_COST_LOW_PRIORITY`; semantic risks listed below |
| INV-11 multiple snapshots/merges/no-hit | SC-01/06/07/13/14 and existing regression suites |
| INV-12 stable+MSRV QA and coverage | see `qa.md` |

## Adversarial test trace

| Area | SC | BT |
|---|---|---|
| Scores / bits | SC-02/03/04/06/07/14 | BT-08/BT-15 |
| Error precedence | SC-12/13 | BT-20 |
| Resource admission | SC-13 | BT-09/BT-15 |
| Cancellation | SC-12 | — |
| Multi-segment / PIT | SC-06/07 | BT-02/BT-06 |
| Cursor | SC-08/12 | BT-04 |
| Oracle / counts | SC-04/06 | BT-01/BT-03/BT-06/BT-14 |
| Mutation | SC-07 | — |
| Source / tooling | — | BT-07/BT-22/BT-25 |
| Evidence / archive | — | BT-16/BT-17/BT-21/BT-24 |

Every BT-01…BT-25 condition has an executable Python test (75+ tests; see
`benchmarks/pr15i_d2a/test_*.py`). SC-16 is intentionally covered by the
existing private scorer tests.

## Semantic feasibility report

### 1. Observable score

`ProjectedHit.score` must remain `Some(f64)` for lexical hits and keep identical
`to_bits()` per selected key. SC-02/03/04/06/07 compare explicit-sort,
relevance-sort, page, reopened-snapshot and two-segment forms. The reported
score-stage cost is measured on the **eager** path; it does not establish that a
late scorer can reproduce these bits.

### 2. Exact total hits and sorted winners

`collect_mixed` consumes the complete scored vector to compute exact
`total_hits`; K truncates the heap, not the count. D2-A does not implement a
count path and no measurement in D2-A proves K can stop counting.

### 3. Budgets

The accepted path reserves the per-segment `BTreeSet` (membership), the global
scored-map charge (`SCORED_MAP_BYTES_PER_ENTRY = 64` for **all** matches),
candidate bytes, work units, scanned-postings occurrences and cancellation
polls. A hypothetical late scorer that reserves only for winners changes the
earliest failing operation. `CandidateBudget` behaviour remains a
contract-changing shortcut unless separately proven.

### 4. Corruption and invalid score

`bm25` returns `SearchError::InvalidScore` for `df > n` or a non-finite result.
A non-winning document can trigger that error on the eager path. Scoring only
winners must not convert an error into success. The public error witness is
limited: producing `df > n` through a public query requires a corrupt index or a
unit seam, so this remains `UNPROVEN` without a new API or corruption fixture.

### 5. Multiple segments, deletes, PIT, cursors, aggregation, batch

SC-06/07/08/12 prove accepted eager behaviour under segment split, delete/upsert,
old PIT and cursor pages. Aggregation and batch were not measured and are
excluded from any late-score eligibility sketch. The screened hypothesis in the
plan (standalone `search`, single positive exact term, explicit one-field
Keyword sort, no cursor/aggregation/batch) is **not** authorized by D2-A.

### 6. Candidate storage

`LeafData::Term` owns sorted `(doc_id, tf)` postings in a `Vec`; the owned
`LeafData` is released before the global heap is processed. A late scorer cannot
assume frequencies remain available without proving a new lifetime and memory
charge. `PostingsReader::advance_with` is a linear advance, not a sublinear seek;
D2-A makes no free random-access claim.

### 7. Error witness matrix

| Witness | Feasible through public query? | D2-A treatment |
|---|---|---|
| `ResourceLimit` (candidate entries) | Yes, constrained `SearchLimits` | SC-13 |
| `Cancelled` before search | Yes | SC-12 |
| Invalid sort / stale PIT cursor | Yes | SC-12 |
| Corrupt segment | Yes with a damaged index fixture | existing regression suite; not needed for eligibility |
| `InvalidScore` (`df > n`, non-finite) | No public non-corrupt witness found | existing private scorer tests only; `UNPROVEN` for non-winner parity |

### 8. D0 rank comparison

D0's `score_vector_ns` was a nested instrumented observation on an older frozen
BASE and is not an accepted-build removable share. D2-A adds three nested
subspans inside the same inclusion boundary. The values are
instrumentation-inclusive diagnostics, not a speedup promise.

## Decision

The semantic report identifies contract-changing shortcuts around non-winner
errors, budget admission and cancellation order. They are not addressed by D2-A
and would require explicit human approval in a future plan. This is recorded as
`D2_B_NOT_AUTHORIZED_BY_D2A`; it does not change the quantitative
`LOW_PRIORITY` verdict, which already makes an immediate D2-B implementation
unwarranted.

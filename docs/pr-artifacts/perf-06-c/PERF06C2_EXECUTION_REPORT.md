# PERF-06-C2 — strict-term physical execution: execution report

> **Status:** `PERF06_C2_NOT_IMPLEMENTED` at authoring; this report is append-only.
> Sections are filled in execution order and never rewritten to hide a failure.

## 1. Identity

| Item | Value |
|---|---|
| Repository | `yduchesne/quervant` |
| Accepted C1 main | `bc726420cede2e26681d6e8192b45a5d0169abbf` |
| Task branch | `dev/perf06-c2-physical-executor` |
| START | `bc726420cede2e26681d6e8192b45a5d0169abbf` |
| BASE | `bc726420cede2e26681d6e8192b45a5d0169abbf` |
| TESTED | _pending_ |
| FINAL | _pending_ |
| Remote-verified SHA | _pending_ |

### P0 / G0 source admission

Commands and observed results:

```
$ git fetch origin main
$ git branch --show-current
dev/perf06-c2
$ git rev-parse HEAD origin/main
bc726420cede2e26681d6e8192b45a5d0169abbf
bc726420cede2e26681d6e8192b45a5d0169abbf
$ git status --short
?? docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt
$ git merge-base --is-ancestor bc726420cede2e26681d6e8192b45a5d0169abbf origin/main && echo ANCESTOR_OK
ANCESTOR_OK
```

- **D01 applied:** `origin/main` descends from the merged C1 commit and the C1
  contract path exists unchanged.
- **D05/D06 applied:** the task branch `dev/perf06-c2` already existed at exactly
  the accepted main SHA with no committed C2 work; it was resumed without reset
  or force.
- **D08 applied:** the single foreign untracked file
  `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` belongs to PERF-06-B. It
  was recorded and left untouched (not deleted, staged or committed).
- Toolchains present: stable `1.98.1` (default) and `1.85.0`. The plan's pinned
  `+1.98.1` is the active stable toolchain; MSRV commands use `+1.85.0`.

## 2. Pre-implementation correctness worksheet (P1 / G1)

### 2.1 Design challenge answers (plan §2, mandatory)

**(a) Why is C2's M certificate based on effective-live data rather than the
physical postings count?**

`compute_stats` is the single accepted source of query-term statistics. For a
segment with persisted norms where every physical document is effective-live it
adds the dictionary `doc_freq` (which the immutable postings list guarantees is
one posting per physical document). For a segment with any tombstone, or one with
legacy (unpersisted) norms, it decodes the postings and counts only effective-live
documents. Either way the summed `PreparedTermStat::doc_freq` is exactly the number
of effective-live documents in the snapshot that contain the term — the same value
`build_leaf_data` will later materialize per segment after live filtering — so a
physical postings count (which can include tombstoned documents) could overstate
the number of candidates and admit an ineligible `M <= K+1` request.

**(b) Why does reusing the sole posting buffer eliminate the additional scored-pair
allocation without reducing an existing logical charge?**

`evaluate_lexical_with` retains exactly one `Vec<(u64,u64)>` per segment (charged
`TERM_POSTING_BYTES = 16` per entry) and then allocates a second
`Vec<(u64,f64)>` inside `score_single_term_candidates` (logically charged
`SCORED_MAP_BYTES_PER_ENTRY = 64`). C2 rewrites the frequency word of the *first*
buffer into `f64::to_bits()` and yields `(doc_id, f64::from_bits(bits))` from it, so
the second allocation never exists. Both historical logical charges are still
made, because the accepted limit model must not become stricter (`P + S + T` peak)
or weaker (`T` removed). The physical peak drops; the logical peak does not change.

**(c) Which error wins if candidate 0 has an invalid key and candidate M-1 has an
invalid score?**

`InvalidScore`. Baseline `evaluate_lexical_with` scores every matched document
inside the evaluator, before `collect_mixed` resolves any document key. C2 keeps
that order: the whole per-segment score conversion completes before the first
`on_scored` callback, so a late score failure aborts before any key/rank/duplicate
work. `C2-U07` executes exactly this with a test-only structural injector
(`INJECTED_C2_ONLY`); genuine shared-source faults are compared against the
forced-Legacy reference separately.

**(d) How is no-postings in one segment handled while another has >K+1 matches?**

The request-level selector is decided once from the snapshot-wide M certificate.
Each segment is still processed in ascending segment order: an `m = 0` segment
still enters the ledger, performs its N examination charge and its cancellation
polls, produces no callbacks, and releases to zero. `m = 1` keeps the
`single_hit_segment` selected-key optimization. No segment is skipped and no
global M value is used for a per-segment optimization. `C2-U02`, `C2-I09`.

**(e) Why is ExactSet still allowed but B3 compact hash optional?**

ExactSet is a *duplicate policy*, not a key-access mechanism: when it is resolved,
`d3c::State::supports_compact_key()` is `false`, so C2 takes the unchanged owned
B2 handler `consider_ordinal_keyword_candidate` with `reader.doc_key*` and the
`HashSet<DocumentKey>` policy — identical to accepted behavior. The B3 compact
directory is an *optional* per-segment acceleration; a refused binding downgrades
only that segment to the same owned B2 handler, which is nonfatal (`D37`).

**(f) Where does the last `Arc<ReaderSnapshot>`/ordinal map live?**

`SnapshotKeywordOrdinals` is one request-wide `Arc` created by
`ReaderSnapshot::prepare_keyword_ordinals` during `collect_mixed` preflight. It is
borrowed by `collect_strict_term_ordinal_body` for the whole request and dropped
when `collect_mixed` returns. It is never cloned into a candidate, a callback, a
cursor or the evaluator; `SegmentOrdinalMap` borrows it per segment only.

**(g) How is a low-hit query guaranteed to reach the old generic loop?**

`collect_mixed` computes the route once, before the segment loop, from
(a) the static eligibility conjunction, (b) request-wide B1 `Ready`, and
(c) `stats.field(field_id).doc_freq(term) > top_k.limit + 1`. When any conjunct
fails the single `if` selects `collect_mixed_legacy_body`, which is the mechanically
moved accepted loop with no per-document dispatch. There is no second route
decision and no post-hoc flip.

### 2.2 Invariant ledger (C2-I01..I20)

Every row must eventually cite an executed command and result. At P1 the
"counterexample" and "required test" columns are the acceptance plan.

| ID | Invariant | Wrong-result counterexample | Required tests | Status |
|---|---|---|---|---|
| C2-I01 | Only the standalone strict one-term/one-sort query with ready ordinals and proved `M > K+1` enters C2; segment bindings stay in original order | `And(Term)`, relevance sort, typed predicate, `M = K+1`, or `NotAvailable` incorrectly enters C2 | C2-U01, U02, U17, I01 | _pending_ |
| C2-I02 | All compiled/schema/cursor/per-reader validation precedes processing | Invalid sort error lost to a corrupt segment | C2-U03, I07 | _pending_ |
| C2-I03 | Full `next_with` validation for a segment precedes scoring/admission | A later malformed posting silently skipped after K winners | C2-U04, U12, I06 | _pending_ |
| C2-I04 | Live-examination count stays N; scanned occurrences charge `freq`; cancellation polled | Charge only M, or stop charging after the heap fills | C2-U05, U13 | _pending_ |
| C2-I05 | `total_hits` counts all effective-live matches in all segments | Count truncated at K/K+1 or includes deleted rows | C2-U06, I01, I03 | _pending_ |
| C2-I06 | All M scores are computed before any admission for that segment | Late `InvalidScore` hidden by an earlier corrupt-key decision | C2-U07, U12 | _pending_ |
| C2-I07 | Every returned lexical hit has bit-identical `Some(f64)` from `+0.0` BM25 order | Changed zero sign/float grouping, or `None` score for an explicit sort | C2-U08, I02 | _pending_ |
| C2-I08 | The only O(M) owned buffer is the reused decoded posting allocation | A `Vec<(u64,f64)>` is allocated in the new evaluator | C2-U09, code review | _pending_ |
| C2-I09 | Preflight/peak/one-over errors/release/unwind logically identical to the accepted evaluator | Fewer/extra virtual charges change admission | C2-U10, U11, I08 | _pending_ |
| C2-I10 | Numeric direction, missing/null, MultiOne and exact byte-key ties stay B2-defined | `doc_id` used as global sort order, or hash as tie-break | C2-U14, I02 | _pending_ |
| C2-I11 | Duplicate identity is exact-key based and tested before rejecting a loser | Hash equality treated as identity; duplicate loser ignored | C2-U15, I04 | _pending_ |
| C2-I12 | K+1 sentinel and cursor contents exact; continuation page uses Legacy | Heap capacity K; cursor from numeric rank | C2-U16, I05 | _pending_ |
| C2-I13 | B1 `NotAvailable` selects Legacy before any candidate; corruption/poison/cancel are typed errors | Catch an error and silently replay generic after partial work | C2-U17, I06 | _pending_ |
| C2-I14 | Snapshot/PIT/updates/deletes/compaction/multi-segment obey the same live mask and identity | Reopen invalidates PIT or counts tombstoned hits | C2-U18, I03 | _pending_ |
| C2-I15 | Batch, aggregation, `select_keys`, JSON/geo/Boolean/phrase/typed/multisort never use C2 | Batch response memory accounting bypassed | C2-U19, I07 | _pending_ |
| C2-I16 | Low-hit generic path unchanged; dispatch runs once outside the document loop | Disabled fast operator still calls a per-candidate selector | C2-U20, source/CI review | _pending_ |
| C2-I17 | Errors produce no successful partial response and no leaked segment/snapshot charges | First page returned despite a later-segment error | C2-U11, U12, I08 | _pending_ |
| C2-I18 | No persisted bytes, writer/storage/reader API, feature flags, dependencies or strategy overrides change | New versioned format added for C2 | Protected path inventory | _pending_ |
| C2-I19 | Acceptance evidence is executed at the final tested source; no real timing acquisition | Source changed after the only tests; older-SHA CI cited | G7/G8 identity ledger | _pending_ |
| C2-I20 | C3 winner-only scoring remains absent; full BM25 errors on noncompetitive documents retained | Skip scoring when the numeric rank loses | C2-U07, U08, I02 | _pending_ |

### 2.3 Accounting worksheet (plan §6)

Per-segment `m` = effective-live match count of the single query term in that
segment; `G` = retained global heap bytes on entry; `P = 16m`, `S = 48m`,
`T = 64m`.

| Request K | Request M | Route | `m` | Peak entries/bytes | Required observed behavior | Status |
|---:|---:|---|---:|---|---|---|
| 1 | 0 | Legacy | 0 | Legacy unchanged | exact count 0, no cursor | _pending_ |
| 1 | 1 | Legacy | 1 | Legacy unchanged | exact single hit | _pending_ |
| 1 | 2 = K+1 | Legacy | 2 | Legacy unchanged | lookahead/cursor parity | _pending_ |
| 1 | 3 = K+2 | C2 | 3 | `9 / 384` | first eligible boundary | _pending_ |
| 10 | 10 | Legacy | 10 | Legacy unchanged | 10 hits, no extra page | _pending_ |
| 10 | 11 = K+1 | Legacy | 11 | Legacy unchanged | 10 hits + cursor | _pending_ |
| 10 | 12 = K+2 | C2 | 12 | `36 / 1536` | 10 hits + cursor, all 12 scored | _pending_ |
| 100 | 101 = K+1 | Legacy | 101 | Legacy unchanged | cursor still correct | _pending_ |
| 100 | 102 = K+2 | C2 | 102 | `306 / 13056` | 100 hits + cursor, all 102 scored | _pending_ |
| 10 | 12 (segments 1 + 0 + 11) | C2 | 1/0/11 | `3/128`, `0/0`, `33/1408` | `G` overlaps each peak; `m=1` keeps selected-key path | _pending_ |
| 10 | 12 (segments 0 + 12) | C2 | 0/12 | `0/0`, `36/1536` | empty segment still charges its N examination | _pending_ |

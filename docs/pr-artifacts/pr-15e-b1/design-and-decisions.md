# PR 15E-B1 — design and decisions

**Scope:** two narrowly attributed optimizations of the existing unified executor:
**B1a** — iterate the effective-live bitmap directly instead of materializing a
transient `BTreeSet<u64>`; **B1b** — binary-search decoded sorted term postings
instead of a linear scan.

**Not in scope** (explicitly deferred): B2 postings-driven candidate enumeration,
B3 selective/random-access stored projection, B4 column cache/reader reuse, any
vector work, any format/API/durability change.

## 1. Starting state and authorization

| Item | Value |
|---|---|
| Starting `main` | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` (PR #82 merge) |
| Branch | `dev/pr15e-b1-live-bitmap-postings-membership` |
| B1a commit | `601765fbc253cf9db3a2bfb5d594156eecb35f51` |
| B1b commit | `79218187390487eea0ced5e193147c15cd5a1e2a` |
| Design authority | approved AD-B01–AD-B04 and B1–B4 sequencing |

### G11 status — explicit human waiver, not a PASS

`docs/pr-artifacts/pr-15e-a/fixup-review-handoff.md` still records
`G11 = PENDING_REVIEW` and `PR15E_B_AUTHORIZED = NO`, and that file is unchanged by
this PR. The repository maintainer explicitly **waived G11 as a prerequisite** for
PR 15E-B1 implementation, citing the existing profiling report and audit receipt
(25/25 checks) as sufficient evidence, and directed that no formal G11 PASS be
claimed. That waiver is the authorization for this work; it is recorded here as a
documented human exception (see `decision-log.md`, D02). **This PR does not claim
`G11 = PASS`, and the PR 15E-A dossier and its private evidence are untouched.**

## 2. Measured motivation (PR 15E-A, unchanged)

From `docs/pr-artifacts/pr-15e-a/profiling-report.md` (process samples and
cumulative allocation traffic, not per-stage wall time): nested unified membership
evaluation dominated sampled CPU on the 100K medium/common lanes (83.41% / 92.38%
exclusive in `evaluate_unified`); constructing `BTreeSet<u64>` from live flags
accounted for 34,232,993 of 35,015,933 Heaptrack allocations on the 100K absent
lane; `LeafData::matches` linearly scanned decoded sorted postings per examined
document. The 100K common CPU report disclosed 786 lost samples; the workload is a
synthetic exact-term `FsDirectory` lane and says nothing about BM25-scored,
RustFS-backed or distributed search.

## 3. B1a — direct effective-live bitmap iteration

### Change

In `crates/quervant-core/src/search/execute.rs`:

* `visit_lexical_membership_with`
* `evaluate_lexical_with`

replaced

```rust
let live_count = live.iter().filter(|flag| **flag).count() as u64;
let live_bytes = bytes_for_count(live_count, LIVE_SET_BYTES_PER_ENTRY)?;
ledger.reserve_with_memory(live_count, live_bytes, memory.as_deref_mut())?;
let live_set: BTreeSet<u64> = live.iter().enumerate()
    .filter_map(|(index, flag)| flag.then_some(index as u64)).collect();
for doc_id in &live_set { /* ... */ }
drop(live_set);
ledger.release_with_memory(live_count, live_bytes, memory.as_deref_mut())?;
```

with

```rust
for (index, flag) in live.iter().enumerate() {
    if !*flag { continue; }
    let doc_id = index as u64;
    /* unchanged: check_cancelled, charge_typed/charge_lexical,
       is_match, on_match / matched.insert */
}
```

### Why this is safe

* `live: &[bool]` is the snapshot's effective visibility; index order is the
  physical doc-id order, so enumeration preserves ascending order and visits each
  live document exactly once.
* The removed `BTreeSet` existed only as a traversal vehicle: it was built from the
  same bitmap, iterated in the same order, and never observed by any caller,
  scorer, cursor or aggregation. It therefore had **no independent normative
  budget role** (decision D05, not D06).
* The existing `index as u64` conversion is reused unchanged; no new truncation
  risk is introduced.

### Memory accounting decision (approved B1a rule)

Only the paired `reserve_with_memory`/`release_with_memory` for the removed
transient collection is deleted, plus the now-unused `live_count`/`live_bytes`
locals in those two functions. Every physically retained allocation keeps its
checked accounting and its lifetime: decoded leaf postings/matches, matched set,
scored map, global candidates, projection and batch memory. `LIVE_SET_BYTES_PER_ENTRY`
remains because the pure lexical `execute_segment_inner` still builds and charges
its own `live_set` (I10).

Queries that were previously rejected **solely** because the transient live set was
charged 48 logical bytes per live document may now succeed. That is an intentional
admissibility improvement (D09), not a waiver for real memory: the same query still
fails one byte below the real retained peak, and high-match queries still scale with
retained hits. Both directions are asserted
(`u11_u12_retained_memory_caps_still_reject_but_the_transient_live_set_is_gone`).

### Intentionally unchanged

`execute_segment_inner` (pure lexical path) and its `live_set`/`MatchAll`/`Not` set
algebra; cancellation timing and charge order; work-meter charge sites; callbacks and
early stop; query mutation limit semantics in `select_keys`.

## 4. B1b — binary search over decoded sorted term postings

### Change

Only the `Term` arm of `LeafData::matches`:

```rust
Self::Term { terms, .. } => terms.iter().any(|term| {
    term.postings
        .binary_search_by_key(&doc_id, |(posting_doc_id, _)| *posting_doc_id)
        .is_ok()
}),
```

No index, copy, conversion, `.sort()`, clone or new per-query allocation. The outer
`any` keeps the OR across the expanded terms of one leaf. The `Phrase` arm is
byte-identical to before.

### Ordering proof (verified on the executed HEAD)

1. `segment/postings.rs::PostingsReader::next_with` decodes `doc_id = previous + delta`
   and rejects `delta == 0` with `SegmentError::NonMonotoneDocId`, so the decoded
   stream is **strictly ascending**; out-of-range ids and zero frequencies are also
   rejected.
2. `build_leaf_data` pushes `(posting.doc_id, posting.freq)` in that decoded order
   and only *filters* by `live` (filters preserve order). Both production
   `TermPostings` constructors route through it (`CompiledLeaf::Term` and
   `CompiledLeaf::MultiTerm`).
3. No other production constructor exists; test fixtures must supply ascending ids,
   which is now documented on `TermPostings` and on the `term_leaf` helper.

The invariant is additionally asserted on the read path by a new decoder test
(`segment::tests::decoder_rejects_nonmonotone_doc_id_deltas`), so a malformed block
cannot decode into an unsorted vector that a binary search would mis-read.

## 5. Invariants preserved (I01–I12)

See `test-traceability.md` for the test-per-invariant matrix. Summary:

* traversal order/exactly-once visits, no tombstone visits, no duplicate charges;
* cancellation check before charge, one lexical **or** typed unit per examined live
  document, unchanged charge order, no charge for false slots;
* immediate stop on `VisitControl::Stop` with no partial successful key selection;
* identical Boolean membership, scores, totals, sort/cursor/PIT behaviour,
  projection, aggregation and batch semantics;
* unchanged postings validation and scanned-postings accounting;
* no over-release/underflow/bypass; ledger ends at zero on success and unwinds on
  failure/cancellation;
* no public API, dependency, format, on-disk, ObjectStore, cache or protocol change.

## 6. Lifecycle and durability

Nothing about commit, generation, manifests, readers, cache or ObjectStore changes.
Segments remain immutable; `live: &[bool]` remains the snapshot-effective view; no
ownership promotion, shared mutation or new lifetime is introduced. All produced
candidate sets, heap entries and ledger reservations keep their original lifetimes.

## 7. Performance methodology (change-specific)

Per the plan, only the targeted Quervant lanes are measured
(`benchmarks/pr15e_b1/run_targeted.py`), never the full PR15D three-engine matrix and
never a new `perf`/Heaptrack campaign. All comparisons are 3 independent trials per
commit on one host, `regime=warm`, 5 warmups + 20 measured samples per lane, oracle
checked, contention probed before and after every trial. Results are reported as
paired trial ratios with an explicit `INCONCLUSIVE` outcome; no arbitrary speedup
threshold is asserted. Current status: `PERF_BLOCKED_OPERATOR` (no operator idle
confirmation was available to this agent) — see `qualification.md`.

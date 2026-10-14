# PR 8 Amendment 01 preflight — deterministic FST work and bounded expansion memory

**Branch:** `dev/advanced-lexical`
**Base:** `main` @ `17305caa653751152972ea1677e1bdc93f8d30a6` (unchanged)
**Inspected implementation:** `cbfb5ec` (PR 8 feature); reports through `64edd5f`
**Working tree at preflight:** clean
**Toolchains:** stable Rust 1.98.1; MSRV Rust 1.85.0

Fresh `git fetch`/`origin/main` inspection: no divergence. No subsequent fixes to
the PR 8 files were found, so all three amendment gaps are **NOT-STARTED** (see
classification below).

## Issue classification

| Gap | Status before amendment | Evidence |
|---|---|---|
| FST build work not charged to `SearchWork` | NOT-STARTED | `expand.rs` called `TermFst::estimate_bytes` then `TermFst::build` with no `work.charge`; only `matches` returned work. |
| Retained FST bytes accumulate `Set::as_fst().size()` instead of the conservative preflight reservation | NOT-STARTED | `expand.rs` set `fst_bytes += fst.logical_bytes()`. |
| Expansion retains one owned `Vec<String>` per `(segment, leaf)` and a scratch `BTreeSet` duplicate | NOT-STARTED | `Expansion.per_segment: Vec<Vec<Option<Vec<String>>>>`; `unique_expanded`/`combined` scratch sets. |

## Baseline (clean `dev/advanced-lexical` @ `64edd5f`)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS — 1133 passed, 0 failed, 7 ignored |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | PASS — 91.86% lines |
| `cargo test -p quervant-core --test pr08_unit` | PASS — 21 |
| `cargo test -p quervant-core --test pr08_properties` | PASS — 8 |
| `cargo test -p quervant-core --test pr08_faults` | PASS — 5 |
| `cargo test -p quervant-core --test pr08_integration` | PASS — 8 |
| `cargo test -p quervant-core --test pr08_domain` | PASS — 4 |

## Exact call graph and ownership

```
LexicalSearcher::search                                  search/mod.rs
  -> plan::compile                                       search/plan.rs
  -> execute::execute_search                             search/execute.rs
       -> SearchWork::new(limits.max_total_work_units)   execute.rs
       -> snapshot.open_segment_reader(index)            index/snapshot.rs
       -> expand::expand_query(&readers, compiled, ...)  search/expand.rs
            -> fsts: BTreeMap<(segment, field), TermFst>  (request-owned)
            -> TermFst::estimate_bytes / build            search/term_fst.rs
            -> TermFst::matches -> Vec<String>            term_fst.rs
            -> Expansion { per_segment: Vec<Vec<Option<Vec<String>>>>,
                           positive_terms: QueryTerms }  expand.rs
       -> score::compute_stats(expansion.positive_terms)  search/score.rs
       -> for each segment: execute_segment(...)
            -> build_leaf_data(reader, compiled, expansion, ...)
                 -> for MultiTerm: expansion.terms_for(seg, leaf) -> &[String]
       -> TopKSelector::finish                            search/topk.rs
```

Lifetimes/ownership:
- `TermFst` is created and dropped inside `expand_query`; it owns an
  `fst::Set<Vec<u8>>`.
- `Expansion` is owned by `execute_search` for the whole request and is borrowed
  by `execute_segment`/`build_leaf_data`.
- `SearchWork` is the single request-wide work ledger, threaded `&mut` through
  expansion and evaluation; it is not reset between fields/segments/leaves.

`TermFst::matches` returns an owned `Vec<String>` and a work count; the caller
charges the count. `FstMatcher` never returns `Result` (the `fst::Automaton` trait
does not allow it); it records `cancelled`/`limit_hit` in `Cell`s and returns dead
states, and the caller checks the flags after each `next()` and after the stream.

## Reserved-work / memory decision

- `fst::Set::from_iter` is a **streaming builder**: it consumes keys in one pass
  and retains an output buffer proportional to the encoded FST plus a node stack
  bounded by the longest key. It does **not** materialize a copy of the whole
  input. Peak temporary memory is therefore O(final FST size + max term length),
  bounded by the conservative per-entry reservation. It does **not** expose a
  fallible allocation API, so allocation failure cannot be mapped to
  `ResourceLimit`; this is disclosed as a residual risk, not concealed.
- The reservation model is `sum(term.len() + TERM_OVERHEAD_ESTIMATE)` (16 bytes
  per term) and is checked cumulatively against `max_fst_bytes` **before** build.
  After build, `Set::as_fst().size() > reservation` fails closed with
  `ResourceLimit`.
- Empty dictionaries are never built: a `(segment, field)` with no entries yields
  an empty `TermFst` (no `Set`), which matches nothing and charges no work. This
  avoids a non-zero FST header exceeding a zero reservation.
- `hashbrown`/`HashMap` is not introduced: the new canonical intern table is a
  `BTreeMap<(u32, String), TermId>` (the text is stored once as the key), and the
  final `Vec<String>` is built by moving those keys. No scratch duplicate set.

## New budget model (amendment §3.4)

```
TERM_ENTRY_OVERHEAD        = 32  // new canonical (field, term) once per request
TERM_ID_BYTES              = 4   // each retained occurrence id (capacity charged)
POSITIVE_TERM_COPY_OVERHEAD = 24 // positive scoring term String copy (once/pair)
ID_CHUNK                   = 64  // deterministic vector growth in ids
max_expansion_bytes default 32 MiB, ceiling 512 MiB
```

## Invariant/test mapping (A1)

| ID | Test target |
|---|---|
| A1-I01 | `term_fst::tests::*work*`, `expand::tests::*work*` |
| A1-I02 | `expand::tests::*fst_budget*`, `*reservation*` |
| A1-I03 | `expand::tests::*intern*`, `*canonical*` |
| A1-I04 | `expand::tests::*occurrence*`, `*expansion_bytes*`, `*capacity*` |
| A1-I05 | `expand::tests::*partial*`, `*recovery*`; `tests/pr08_amendment01.rs` |
| A1-I06 | `tests/pr08_amendment01.rs` oracle parity; existing PR 8 suites |
| A1-I07 | `limits::tests`; `tests/pr08_amendment01.rs`; segment golden suites |
| A1-I08 | stable/MSRV/coverage gates |

## STOP check

No STOP condition is triggered. The `fst` builder's temporary memory is bounded by
the output size and longest key; a truthfully conservative retained-memory
reservation plus a bounded, charged input-work preflight is achievable. The
remaining non-fallible temporary allocation is explicitly disclosed as a residual
risk (documented, not hidden). No segment/codec/writer change is required.

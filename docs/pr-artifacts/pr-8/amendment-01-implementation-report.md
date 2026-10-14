# PR 8 Amendment 01 implementation report

**Branch:** `dev/advanced-lexical`
**Base:** `main` @ `17305ca`
**Pre-amendment head:** `64edd5f`
**Scope:** close three resource-accounting gaps in PR 8 without changing search
semantics or on-disk formats.

## What changed

### 1. FST construction work is charged to the request-wide ledger

`TermFst::preflight_build(entries, current_total, max_fst_bytes, work, cancel)`
is a single bounded walk that:

- charges `1 + term.len()` per dictionary entry to the shared `SearchWork`
  **before** `fst::Set::from_iter`;
- polls cancellation at the start, every 256 entries, and after the final entry;
- computes the conservative retained-memory reservation
  `FST_BASE_RESERVATION + sum(term.len() + TERM_OVERHEAD_ESTIMATE)`;
- rejects as soon as `current_total + partial_reservation > max_fst_bytes`.

`expand_query` calls the preflight immediately before `TermFst::build` and never
builds when the preflight fails. The reference model
`TermFst::estimate_build_work` is test-only so production never does an uncharged
second scan. A test-only `build_invocations()` counter proves that an
over-budget request never calls `Set::from_iter`.

### 2. Retained FST bytes use the reservation, not the encoded size

`expand_query` accumulates `fst_reserved_total += reservation` and ignores
`Set::as_fst().size()` for accounting. After build,
`fst.reservation_fits(reservation)` fails closed with `ResourceLimit` if the
encoded size exceeds the reservation (test-only injected case). Empty dictionaries
are handled by an explicit `TermFst::empty()` marker and never build an `fst::Set`.

**Documented correction:** the amendment's per-term reservation model omits the
fixed encoded FST header (measured 39 bytes for an empty `Set`). A private
`FST_BASE_RESERVATION = 64` was added; without it, tiny dictionaries would
under-reserve and fail closed. This is a minimal, private logical constant — not a
published default, query semantic, or format change.

### 3. Expansion interns terms and bounds retention separately

- `Expansion.per_segment` now stores `Vec<TermId>` (`u32`) instead of
  `Vec<String>`. `Expansion::term(id)` resolves canonical text.
- A request-owned intern table `BTreeMap<u32, BTreeMap<String, TermId>>` stores
  each `(field, term)` text once; `finish` moves the keys into an id-indexed
  `Vec<String>`. There is no separate scratch `BTreeSet`.
- Production uses `TermFst::visit_matches`, which streams borrowed `&str` keys to
  a fallible callback; no owned match vector is materialized.
- `max_expansion_bytes` (default 32 MiB, ceiling 512 MiB) bounds simultaneously
  retained canonical texts, occurrence ids (charged by vector capacity in 64-id
  chunks plus allocator overshoot) and positive scoring-term `String` copies.
- `execute.rs` resolves each `TermId` with `Expansion::term` before the existing
  `lookup_entry`/postings/scoring path.

The ordinary positive-term union, negative-only zero scoring, global BM25,
Boolean/PIT/top-K and legacy formats are unchanged.

## Files

| File | Change |
|---|---|
| `search/limits.rs` | additive `max_expansion_bytes` field/getter/setter/ceiling; 10-arg `new` preserved |
| `search/term_fst.rs` | `preflight_build`, reservation/fail-closed validation, `visit_matches`, explicit `TermFst::empty()`, test-only build counter and oversize injection |
| `search/expand.rs` | canonical intern table, `TermId` occurrence vectors, `ExpansionBudget`, streaming callback insertion, capacity charging |
| `search/execute.rs` | resolve `TermId` to canonical text |
| `tests/pr08_amendment01.rs` | public-path A1-T01–T28 integration tests |
| `examples/pr08_bench.rs` | unchanged (diagnostic latency reference) |

No `contract/*`, `segment/*`, `index/*`, `storage/*`, `quervant-objectstore/*`
file changed; no segment section, feature id, manifest or dictionary wire change.

## Behavior preservation

- All original PR 8 suites and all PR 7 suites pass unchanged.
- `a1_t21_operator_membership_matches_oracle` and the existing seeded oracle
  confirm Prefix/Glob/Regex/Fuzzy membership and scoring are unchanged.
- `a1_t24_boolean_and_negative_only_unchanged` confirms Boolean and pure-negative
  behavior.
- `a1_t27_frozen_fixture_bytes_unchanged` confirms the frozen pre-norms fixture
  bytes are identical.

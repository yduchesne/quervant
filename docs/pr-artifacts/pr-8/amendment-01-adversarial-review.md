# PR 8 Amendment 01 adversarial review

Scope: deterministic FST construction work, conservative cumulative FST
retained-memory reservations, and a separately bounded expansion-retention
budget. This review identifies plausible ways each invariant can be defeated and
the test that discharges it. A semantic mismatch is never an accepted risk.

## A1-I01 — every inspected dictionary entry charges work before build

- **Risk:** the cost model is charged only after `Set::from_iter`; a second
  uncharged scan; cancellation missed on a no-match/zero-entry walk.
- **Discharge:** `preflight_build` charges `1 + term.len()` per entry into the
  single `SearchWork` ledger, polls cancellation at the start, every 256 entries,
  and after the final entry, and returns before any build. `estimate_build_work`
  is the test-only reference model (kept out of production precisely to avoid an
  uncharged second scan). Tests: `preflight_charges_work_and_reserves_conservatively`,
  `preflight_work_limit_prevents_build` (build counter == 0),
  `preflight_cancellation_during_walk`,
  `preflight_empty_dictionary_checks_cancellation`,
  `a1_t01_t02_work_limit_is_charged_and_prevents_partial_success`,
  `a1_t03_cumulative_work_across_fields`.

## A1-I02 — FST reservation is cumulative and conservative

- **Risk:** accumulating encoded `Set::as_fst().size()` instead of the
  reservation; accepting an underestimated reservation; the fixed FST header
  exceeding a per-term-only estimate for tiny dictionaries.
- **Discharge:** the caller keeps `fst_reserved_total += reservation` and never
  reads `logical_bytes()` for accounting. `preflight_build` rejects as soon as
  `current_total + partial_reservation > max_fst_bytes`. After build,
  `reservation_fits` fails closed if the encoded size exceeds the reservation.
  A measured 39-byte fixed FST header required adding a private
  `FST_BASE_RESERVATION = 64`; this is the only deviation from the amendment's
  per-term formula and is recorded in the implementation report. Tests:
  `preflight_fst_budget_one_over_prevents_build`,
  `preflight_is_cumulative_across_fields`, `reservation_rejects_encoded_oversize`,
  `a1_t05_t06_fst_budget_exact_and_one_over`,
  `a1_t07_two_fsts_share_the_cumulative_budget`.

## A1-I03 — one canonical text per `(field, term)`

- **Risk:** cloning the term per occurrence; a scratch set duplicating the
  canonical table; ordering by numeric id instead of term order.
- **Discharge:** the intern map (`BTreeMap<u32, BTreeMap<String, TermId>>`) is
  the single canonical store; text is stored once as the map key and moved into
  the id-indexed vector at `finish`. Per-leaf vectors hold `u32` ids only, pushed
  in FST (ascending UTF-8) order. There is no separate `unique_expanded`/
  `combined` `BTreeSet`. Tests: `intern_deduplicates_and_charges_once`,
  `duplicate_term_amplification_is_bounded_by_occurrences_not_strings`,
  `a1_t14_occurrence_amplification_fails_by_bytes`.

## A1-I04 — every retained occurrence and scoring copy is charged

- **Risk:** charging only occupied slots, not allocated capacity; missing the
  positive-scoring `String` copy; an unbounded per-leaf match vector before
  admission.
- **Discharge:** `push_occurrence` charges each `ID_CHUNK` capacity growth and
  any allocator overshoot before pushing; `intern_term` charges the canonical
  entry and the positive copy before insertion; production uses
  `visit_matches`, which streams borrowed keys and never materializes an owned
  match vector. Tests: `occurrence_capacity_is_charged_in_chunks`,
  `occurrence_bytes_one_over_fails_closed`, `positive_copy_is_not_charged_twice`,
  `positive_unique_limit_is_enforced`,
  `occurrence_amplification_fails_even_when_unique_terms_fit`,
  `a1_t12_t13_expansion_bytes_exact_and_one_over`.

## A1-I05 — no partial results or state mutation on failure

- **Risk:** returning a truncated response; leaving an index/PIT mutated.
- **Discharge:** all budget/limit failures return a typed error before any
  response is built; the request-local builder and FST cache drop on error; the
  index and PIT are read-only. Tests:
  `a1_t17_t18_no_partial_results_and_recovery`,
  `a1_t19_cancellation_mid_expansion_then_recovery`,
  `a1_t20_fs_failing_expansion_is_read_only`, and the module budget tests.

## A1-I06 — search membership and BM25 unchanged

- **Risk:** a semantic change hidden inside the representation change.
- **Discharge:** `execute.rs` resolves each `TermId` to canonical text before the
  existing `lookup_entry`/postings/scoring path; Boolean membership, positive
  union, negative-only zero scoring and top-K are untouched. Tests:
  `a1_t21_operator_membership_matches_oracle`,
  `a1_t24_boolean_and_negative_only_unchanged`, plus the unchanged PR 8 oracle
  and legacy/mixed-norm suites.

## A1-I07 — existing limits/API/codec unchanged except the additive limit

- **Risk:** changing `SearchLimits::new`; changing the query AST or segment wire
  format.
- **Discharge:** `new` keeps its ten arguments and initializes the new field to
  the default; only a getter/setter and ceiling were added. No segment/querier
  files changed. Tests: `a1_t25_ten_arg_constructor_preserves_defaults`,
  `a1_t26_expansion_bytes_setter_exact_zero_one_over`,
  `a1_t27_frozen_fixture_bytes_unchanged`,
  `a1_t28_published_schema_and_semantics_unchanged`.

## Residual risks (disclosed, not semantic)

- `fst::Set::from_iter` does not expose a fallible allocation API, so an actual
  allocator OOM during build cannot be mapped to `ResourceLimit`. The builder is
  streaming and its temporary memory is bounded by the output FST size plus the
  longest key; the conservative reservation, not measured RSS, is the bound.
  This is the amendment's permitted "truthful retained accounting + residual
  temporary overhead" position.
- The `Expansion` outer `per_segment` structure (`segments x leaves x
  Option<Vec>`) is bounded structural overhead not separately charged; it is
  O(segments x leaves) pointers, dwarfed by the charged canonical/occurrence
  bytes. It can be charged in a future revision if profiling warrants.
- `execute.rs` clones a canonical term into each `TermPostings` for the segment,
  exactly as PR 7 did for ordinary `Term` leaves; that ownership is covered by the
  existing candidate ledger. The amendment does not increase that clone count
  relative to the pre-amendment PR 8 branch.

## STOP check

No mandatory STOP condition was hit: the `fst` builder is bounded, borrowed-key
streaming works, `TermId` resolution needs no new unbounded clone, no scoring or
codec change was required, and every limit is enforced before significant
allocation. The base-reservation correction is documented and tested.

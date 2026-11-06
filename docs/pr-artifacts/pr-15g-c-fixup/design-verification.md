# PR 15G-C fixup design verification

**Status:** implementation and verification in progress.

## Locked changes

- Preserve `single_term_stream_eligible` and the legacy P4 path.
- Replace four postings scans with exactly two for a nonempty term; no second
  scan for an absent term.
- Pass `Posting.freq: u64` directly to `score::bm25`; pass an exact validated
  `f64` to the shared candidate admission routine.
- Pass 1: full decode/scanned/live work/16/48/64 virtual admission, then release
  all segment reservations and finish the ledger before pass 2.
- Pass 2: score every live posting once; defer the first candidate-admission
  error until all later scores in the same segment are checked; a later
  `InvalidScore` outranks that deferred candidate error.
- No O(M) match/score collection; existing K+1 heap and comparator unchanged.
- Test-only hooks for invalid nonwinner score, deferred candidate-error priority,
  pass-count mismatch, and postings-open counts are `#[cfg(test)]` only.

## Invariant map

| ID | Witness |
|---|---|
| GF-I01 eligibility | unchanged eligibility tests + `gc_u01…` |
| GF-I02 two passes/no O(M) | postings-open counter; `gf_u05_u06_two_pass_counts` |
| GF-I03 exact totals | `gc_u11…`, legacy differential |
| GF-I04 score bits/keys/tuples | C-vs-`And([Term])` differential |
| GF-I05 exact virtual budgets | phase4 budget parity + C entry/byte boundary tests |
| GF-I06 error priority | `gf_u21…`, `gf_u22…`, `gf_u23…` |
| GF-I07 u64 frequency | scorer direct test + visitor code review |
| GF-I08 cancellation/cleanup | existing cancellation + integration/RustFS |
| GF-I09 corrupt postings | existing corrupt/fault tests |
| GF-I10 fallback parity | eligibility/fallback integration |
| GF-I11 PIT/multi-segment | `gc_i07`, convergence tests |
| GF-I12 remote parity | C/A/B RustFS |
| GF-I13 B carryover | `gc_br01*`, `gc_br02*` |
| GF-I14 measurement truth | frozen C runner + new campaign |

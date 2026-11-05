# D2-only source disposition

**Campaign result:** `D2_ONLY_PERFORMANCE_REJECTED`
**Selected source:** exact A baseline `ca065a212987284144d8901aa5c54de093d6dbfc`
**Rollback commit:** `f51b772b653205ddf1c767850961e88a13193096`
**Harness commit:** `74f495cc580a746ada6facda7c44363499273481`

## Why A

- `DX-P01` failed: 100K common/K100 was `X_FASTER`, but 100K common/K10 was
  `INCONCLUSIVE`, so both required common targets did not pass.
- `DX-P02` failed: 10K rare/K100 was `A_FASTER` across all four blocks.

Under the predeclared decision rule, either failure requires restoring A. No
D2-only retention, threshold change or selective retry was applied.

## Byte proof

```sh
git diff --quiet ca065a212987284144d8901aa5c54de093d6dbfc -- \
  crates/quervant-core/src/search/execute.rs \
  crates/quervant-core/src/search/unified.rs
```

Exit status: `0` — both files are byte-identical to A.

Both D1 and D2 are absent from active production source. The remaining P4
`postings_candidate_eligible` references are part of accepted A, not D2.
`TERM_MEMBERSHIP_SEARCHES`, `record_term_membership_search`,
`charge_absent_exact_term_segment` and `absent_term_candidate` are absent.

## Preserved

- Original D1/D2 reports, three-arm confirmation, first blocked campaign and
  its raw evidence remain untouched.
- D/B/C differential integration tests remain in the repository.
- No frozen benchmark, Cargo, CI, segment, storage or API file changed.

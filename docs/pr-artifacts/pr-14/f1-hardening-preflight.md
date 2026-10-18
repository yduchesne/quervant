# PR 14 — F1 hardening preflight

- Repository branch: `dev/pagination`
- `main` SHA: `7ca1b2ec59fec648602e0e4a52e8f903a596f106`
- Branch HEAD at preflight: `83e1dcfecbc81cc12108622c2fe96940b4932d9f` ("PR 14 Phase 2"); hardening edits uncommitted.
- Working tree before edits: clean.
- Toolchains: stable `1.98.1`, MSRV `1.85.0`, `cargo-llvm-cov 0.9.1`.
- Baseline `pr14_unified_mixed` 14 passed, `pr14_batch` 12 passed; workspace green (from the prior pass).

## Source facts revalidated

- `search/execute.rs`: `SearchWork` (own total/scanned counters), `CandidateBudget` (segment + global bytes), `SegmentCandidateLedger`, `evaluate_lexical_with`, `build_leaf_data`, `score_segment`, `LeafData::matches`.
- `search/typed.rs`: `ScanGuard` (own total counter), `evaluate_query`, `build_geo_membership`, `build_geo_sort_distances`, `sort` machinery.
- `search/typed_compare.rs`: `SortValue`, `compare_candidates`, `sort_tuple_for_doc`, `GeoSortDistances`.
- `search/unified.rs`: `SelectedHit`, `collect_mixed`, `project_selected`, `project_selected_hits`, `MixedEntry` top-K.
- `contract/result.rs`: `Sort::validate` (columnar/multi/geo rules), `Projection::validate`.

## I01–I10 → test mapping (see traceability for symbols)

| ID | Tests |
|---|---|
| I01/I02 | W01–W06 — **NOT IMPLEMENTED** (STOP H1) |
| I03/I04 | M01–M06 |
| I05 | P01–P05 |
| I06 | S01–S05 |
| I07 | V01–V05 |
| I08 | G01–G05 |
| I09 | `pr14_unified_mixed::m07`, P02 |
| I10 | R01–R04 (existing suites) |

## Adversarial counterexamples selected

- Mixed parity masquerading as delegated parity → S01–S03 assert bit-exact `f64::to_bits()` against `LexicalSearcher`.
- Obsolete physical version returned by key rescan → P02 upsert with changed stored field.
- Invalid sort surfacing late or as a segment error → V01–V05.
- Mixed geo sort divergence → G01–G03.
- Unbounded retention / lost total → M02.

## STOP H1 finding

`SearchWork` and `ScanGuard` each own independent counters and are both live during a
mixed segment: `evaluate_lexical_with` holds `&mut SearchWork` while invoking the typed
callback that holds `&mut ScanGuard`. Sharing one counter requires routing `build_leaf_data`
→ `build_phrase` → `phrase.rs::match_phrase` and `expand_query`/`compute_stats` through a new
`WorkCharge` seam, plus a mixed `ScanGuard` adapter. That is a cross-module signature change
(execute.rs, expand.rs, score.rs, phrase.rs, typed.rs) and was **not** attempted in this pass.
Reported as STOP H1; no degraded substitute was introduced.

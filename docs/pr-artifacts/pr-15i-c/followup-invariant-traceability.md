# PR 15I-C follow-up — invariant traceability and pre-implementation challenge

Written before any production edit (P0). Each invariant maps to the planned
positive test and the counterexample that must fall back or fail closed.

| ID | Positive proof | Counterexample proof |
|---|---|---|
| I-01 validation order | `N-U01`, `N-I01` | invalid sort/projection/K/cursor returns the pre-existing typed error with zero dispatch |
| I-02 `collect_mixed` identity | `N-U34` source proof (normalized body SHA `00c5a1c8…`, attributes unchanged, no inline attribute); `codegen_capture` | any added attribute or body drift → `NC-D47` STOP |
| I-03 ineligible shapes use generic only | `N-U02..N-U10`, `N-I02..N-I09` | phrase/prefix/regex/glob/fuzzy/Not/two-term, multi-token analysis, cursor, aggregation/typed/JSON/geo, two segments, batch, `retain`, DESC/two-field/numeric/JSON-path/distance/multi sort, relevance |
| I-04 eligible shape | `N-U11..N-U15` | sort field named `label` still eligible; field named `doc_id` but numeric/noncolumnar/multi → generic; column values ≠ keys still canonical |
| I-05 exhaustive exact count | `N-U16..N-U19`, `N-I10` | `M>K` (K=1/10/100, 1000 matches) still scores and counts all `M`; delete/upsert filtered by effective-live |
| I-06 bit-exact results | `N-U20..N-U25`, `N-I11..N-I14`, score probe | 256 fixed-seed cases (`0x15_1C_2026`); missing `FieldStats` → exact `0.0` bits; ties by canonical comparator; `K+1` cursor identical |
| I-07 budgets and first-error parity | `N-U26..N-U33`, `N-F02..N-F09` | exact/one-below scanned/work/entries/bytes/heap; cancellation at every checkpoint; late score error precedes key error |
| I-08 format unchanged | 12 A/B rebuilds + digests, `N-I15` | any layout/digest/sentinel drift → `NC-D73` STOP |
| I-09 no release instrumentation | `N-V`/binary grep (`pr15ic-probe` absent) | probe symbol in default release → `NC-D62` STOP |
| I-10 sealed independent diagnostics | `N-V01..N-V28` | forged controller PASS, missing/extra/symlinked raw, re-sealed tamper |
| I-11 A/A same executable bytes | A/A verifier: same absolute path + same SHA-256 before/after | two different binaries with equal source → `NC-D20` STOP |
| I-12 A/G changes only a boundary | source proof: body SHA equal, exactly one `#[inline(never)]` | body change or extra production path → `NC-D09/D10/D46` STOP |
| I-13 local-only and unchanged remote semantics | `N-I16`..`N-I20`, `N-R01..N-R06` | no S3 in the query loop; missing runtime → `REAL_RUSTFS_BLOCKED` |
| I-14 diagnostics never waive the frozen gate | final `C-P06..09` matrix | diagnostic PASS with final median/block failure → `NC-D66/D68` reject |
| I-15 rollback identity | `git diff --quiet BASE HEAD -- <protected>` | any residual production delta → `NC-D82` STOP |
| I-16 no new remote I/O or generic inline attribute | release source diff + `codegen_capture` | `#[inline(never)]` on `collect_mixed` → `NC-D46` STOP |

## Mandatory challenge: why each tempting shortcut must fall back

1. **Sort column ≠ logical key.** Eligibility never compares the field name to
   `doc_id`; it checks schema `Keyword`/`Single`/`columnar` and direction. Every
   candidate is compared with the unchanged borrowed-Keyword comparator, so a
   column that differs from the key still orders by column value, and ties break
   by logical key. (Source: `consider_borrowed_keyword_candidate`,
   `compare_borrowed_keyword_to_owned`, `heap_admit_candidate`.)
2. **No columnar Keyword.** `exact_term_physical_eligible` requires
   `options.columnar` and `FieldType::Keyword`/`Cardinality::Single`; anything else
   is generic.
3. **Cursor on an eligible-looking query.** `single_term_postings_eligible` (and
   the copied predicate) require `request.after.is_none()`; cursor validation and
   dispatch are separate, so a cursor leaves `c_physical == false` and the original
   `collect_mixed` call runs with the cursor.
4. **Batch/retain.** Dispatch passes `batch.is_none()` as `standalone` and the
   `retain` flag; both must be false. The specialized collector cannot even see the
   batch meter, so a batch slot cannot lose its accounting.
5. **Two segments.** `self.snapshot.segment_count() != 1` → generic. No read-time
   compaction is created.
6. **Unanalyzed/multi-token leaf.** `CompiledLeaf::Term{terms}` must contain exactly
   one analyzed term; a multi-token analysis has `terms.len() > 1` → generic.
7. **Phrase/regex/prefix/glob/fuzzy.** Those compile to `CompiledLeaf::Phrase` or
   `CompiledLeaf::MultiTerm`, so the `CompiledLeaf::Term` match fails → generic.
8. **Corrupt unselected record / semantic certificate.** The fast path only changes
   *which collector* runs; segment open, `schema == plan.codec` check, effective-live
   resolution, `build_leaf_data` and the STORED v2 certificate are the same code, so
   corruption still fails closed through the same typed errors.
9. **One-below limits.** The operator reproduces the legacy admission order exactly
   (16 B/posting leaf reserve, virtual 48 B matched, virtual 64 B scored, then one
   `Vec<f64>`), so a query rejected at a given ceiling stays rejected; removing the
   physical trees cannot admit work the generic path refused.
10. **Cancellation.** The operator polls cancellation at the same checkpoints
    (`effective_live_examination_count` entry, per posting, after the loop) and the
    callback path is unchanged, so `Cancelled` surfaces before any partial response.
11. **`-0.0` vs `+0.0`.** Scores are produced by the unchanged `score::bm25` and
    accumulated as `let mut score = 0.0_f64; score += contribution;` — exactly the
    single-positive-term branch of `score_segment` — so the returned bits match,
    including the `+0.0` result for a zero contribution.
12. **Injected score error late in postings.** The operator completes the whole
    scoring pass before the first callback, so a late `InvalidScore` precedes any
    key decode or sort comparison. The *fixture* for `df > n` remains unavailable
    without a protected `score.rs` seam (`EVIDENCE_BLOCKED`, `NC-D56`), and that
    limitation is declared rather than manufactured.
13. **Missing external RustFS.** Local correctness/performance cannot substitute for
    the real-service gate: `N-R01..N-R06` are reported `REAL_RUSTFS_BLOCKED` if no
    runtime exists, and no fake store is substituted.

No behavior above requires new source outside the authorized files, so no STOP is
triggered at P0.

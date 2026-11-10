# PR 15I-C batched-noise follow-up — invariant traceability

Written before any production edit (P0). Each invariant maps to a planned
positive test and to the counterexample that must fall back or fail closed.

| ID | Positive proof | Counterexample proof |
|---|---|---|
| I-01 | `N-U01`, `N-I01` | invalid query/sort/projection/K/cursor returns the pre-existing typed error with zero dispatch |
| I-02 | `N-U34` source proof: `collect_mixed` normalized body SHA `00c5a1c8…`, attributes unchanged, **no** inline attribute; `codegen_capture` | any added attribute or body drift → `NC-D47` STOP |
| I-03 | `N-U02..N-U10`, `N-I02..N-I09` | phrase/prefix/regex/glob/fuzzy/`Not`/two-term, multi-token analysis, cursor, aggregation/typed/JSON/geo, two segments, batch, `retain`, DESC/two-field/numeric/JSON-path/distance/multi sort, relevance |
| I-04 | `N-U11..N-U15` | sort field named `label` stays eligible (schema-driven); a field named `doc_id` that is numeric/noncolumnar/multi falls back |
| I-05 | `N-U16..N-U19`, `N-I10` | `M>K` (K=1/10/100, 1000 matches) still scores and counts every `M`; deletes/upserts filtered by effective-live |
| I-06 | `N-U20..N-U25`, `N-I11..N-I14`, score probe | 256 fixed-seed cases (`0x15_1C_2026`); missing `FieldStats` → exact `0.0` bits; canonical tie order; identical `K+1` cursor |
| I-07 | `N-U26..N-U33`, `N-F02..N-F09` | exact/one-below scanned/work/entries/bytes/heap; cancellation at every checkpoint; late score error precedes key error |
| I-08 | 12 A/B rebuilds + digests, `N-I15` | any layout/digest/sentinel drift → `NC-D73` STOP |
| I-09 | default release binary has no `pr15ic-probe` symbol | probe symbol in default release → `NC-D62` STOP |
| I-10 | `B-V` matrix (48 executed cases) + seal/inventory checks | forged controller PASS, missing/extra/symlinked raw, re-sealed tamper |
| I-11 | batched A/A verifier: one absolute executable path **and** one SHA-256, re-hashed before/after | two different binaries with equal bytes → `NC-D20` STOP (`B-V06`) |
| I-12 | A/G source proof: identical generic body hash, exactly one `#[inline(never)]` in G only | body change or extra production path → `NC-D09/D10/D46` STOP (`B-V08`) |
| I-13 | `N-I16..N-I20`, `N-R01..N-R06` | no S3 in the query loop; missing runtime → `REAL_RUSTFS_BLOCKED` |
| I-14 | final `C-P06..C-P09` matrix from the frozen unbatched campaign | diagnostic PASS with a final median/block failure → `NC-D68`/`NC-D97` reject |
| I-15 | `git diff --quiet BASE HEAD -- <protected>` after rollback | any residual production delta → `NC-D82` STOP |
| I-16 | release source diff + `codegen_capture` | `#[inline(never)]` on `collect_mixed` → `NC-D46` STOP |

## Batched-diagnostic invariants (new, §3)

| ID | Requirement | Proof |
|---|---|---|
| B-01 | exact repetition count: 100 for the four absent/rare lanes, 1 for the three common lanes | `B-V16`, `test_batched_noise.repeat_count_assignment`, verifier `BV_UNITS` |
| B-02 | one snapshot per lane/slot session reused across every repetition | derived adapter reuses `QuerySession`; `test_batched_adapter_patch` BV-08/BV-14 |
| B-03 | no measurement-unit substitution: a batch is one outer Rust `Instant`, never a sum of `engine_ns` | patcher BV-06/BV-07/BV-08, `B-V21`, `B-V22` |
| B-04 | A/A uses one actual executable file for both labels | `B-V06`, verifier `BV_AA_BINARY`, slots' path/hash equality |
| B-05 | frozen PR15D adapter unmodified; only a deterministic two-hunk patch in a throwaway copy | patcher BV-09/BV-10/BV-11/BV-13, `NC-D87` |
| B-06 | source-bound patch proof (blob SHA, frozen function hashes, derived hash) | patcher BV-01..BV-05, `B-V07`, manifest `adapter_patch` |
| B-07 | short-lane slot median ≥ 1 ms per arm | `B-V37`, controller/verifier floor flags, `NC-D89`/`NC-D90` |
| B-08 | one CPU-affinity mode for all eight campaigns | `B-V23`, verifier `verify_affinity`, aggregate fingerprint check |
| B-09 | exact counts 2 240 batches / 1 120 warmups / 130 080 searches per campaign | `B-V40`, `BV_COUNT` |

## Mandatory challenge: why each tempting shortcut must fall back

1. **Sort column ≠ logical key** — eligibility checks schema (`Keyword`, `Single`,
   `columnar`, `Asc`), never a name; ordering always uses
   `consider_borrowed_keyword_candidate` + `compare_borrowed_keyword_to_owned`.
2. **No columnar Keyword** — the predicate requires `options.columnar`; otherwise
   generic.
3. **Cursor on an otherwise eligible query** — `single_term_postings_eligible`
   requires `request.after.is_none()`; a cursor keeps `c_physical == false`, so the
   original `collect_mixed` call runs with the cursor.
4. **Batch / retain** — dispatch passes `batch.is_none()` and `retain`; both must be
   false, and the specialized collector never sees the batch meter.
5. **Two segments** — `snapshot.segment_count() != 1` → generic; no read-time
   compaction.
6. **Unanalyzed / multi-token leaf** — `CompiledLeaf::Term { terms }` must hold
   exactly one analyzed term.
7. **Phrase / regex / prefix / glob / fuzzy** — they compile to
   `CompiledLeaf::Phrase` / `MultiTerm`, so the `Term` match fails.
8. **Corrupt unselected record** — the fast path only changes *which collector*
   runs; segment open, codec check, effective-live view, `build_leaf_data` and the
   STORED v2 certificate are the same code, so corruption fails closed identically.
9. **One-below limits** — the operator reproduces the legacy admission order
   (16 B/posting leaf, virtual 48 B matched, virtual 64 B scored, then one
   `Vec<f64>`); removing physical trees cannot admit work the generic path refused.
10. **Cancellation** — the operator polls at the same checkpoints
    (`effective_live_examination_count` entry, per posting, after the loop).
11. **`-0.0` vs `+0.0`** — the operator accumulates exactly as the
    single-positive-term branch of `score_segment` (`0.0` then `+=`), so bits match.
12. **Late score error** — the operator completes the whole score pass before the
    first callback. The `df > n` fixture is authorized only through the §5.6
    `#[cfg(test)]` helper; if that cannot compile, HARD STOP (`NC-D56`/`NC-D98`).
13. **Missing external RustFS** — no fake store; `REAL_RUSTFS_BLOCKED` and no
    positive feature acceptance.

No item above requires source outside the authorized files, so P0 triggers no STOP.

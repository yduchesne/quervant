# PR 7 Amendment 05 review — persistent BM25 field norms

**Scope:** eliminate the per-search all-dictionary/all-postings statistics scan by
persisting immutable per-document field norms and retrieving document frequencies
for queried terms only. No BM25 formula, query semantics, candidate-ledger
accounting, top-K ordering, or durability change.
**Branch:** `dev/lexical-postings`; base `main` `4f603ce1`; pre-optimization
commit `a8adf37`.
**Disposition:** implementation complete, correctness-verified, and the
performance objective **VERIFIED** by a qualified three-trial same-environment
pre/post comparison (1.68x–2.06x on scored lexical search, controls unchanged).

## Changed files

Production:

- `segment/format.rs`: `SectionKind::FieldNorms = 0x000E`,
  `FEATURE_FIELD_NORMS = 0x0007` (v1) added to `SUPPORTED_FEATURES` and
  `from_raw`. `FORMAT_MAJOR/MINOR`, magic and existing IDs unchanged.
- `segment/norms.rs` (new): `FieldNorms`, `FieldNormsReader`, `encode_field_norms`,
  `scoring_field_ids`; bounded decode with per-allocation/cumulative budgets,
  canonical varints, strict field ordering, exactly the schema's scoring fields,
  recomputed-vs-declared total/nonzero verification, trailing-byte rejection.
- `segment/build.rs`: norms collected in the existing single analysis pass
  (per physical doc, per scoring field, one per emitted token); section + required
  feature emitted together for every new segment.
- `segment/reader.rs`: section/feature consistency table (neither = legacy, both =
  validated, mismatch = corruption); `field_norms()` accessor; eager validated
  decode at open.
- `segment/mod.rs`: module registration/re-exports.
- `search/score.rs`: `SnapshotStats<'a>`/`FieldStats<'a>` with
  `SegmentLengths::Persisted(&[u64]) | Legacy(HashMap)`. New-format/all-live path
  uses `total_token_count` + binary-search `doc_freq`; tombstone path sums live
  norms and counts live postings for queried terms; legacy path preserves the
  original bounded all-postings reconstruction. `bm25` unchanged.
- `search/execute.rs`: only lifetime parameters on `SnapshotStats` propagation.

Dev/tests/docs: `tests/pr07_amendment05.rs` (new), `tests/segment_golden.rs` (new
`golden_norms.seg` + digest), `segment/norms.rs` unit tests,
`search/score.rs` legacy-fallback unit test, `tests/pr07_amendment01.rs` (`l02`)
and `tests/pr07_faults.rs` (`f08`) updated for superseded legacy-only bounds,
`Cargo.toml` (`sha2` dev-dep), `Cargo.lock`, PR artifacts and docs.

## Golden fixtures

| Fixture | Bytes | SHA-256 | Role |
|---|---:|---|---|
| `tests/fixtures/segment/golden.seg` | 1688 | unchanged | frozen legacy (no norms); opens and searches |
| `tests/fixtures/segment/golden_norms.seg` | 1810 | `49f813a68a4adedf8b69c8a965159a840bc993ca252f81efb1887daa95b5c39b` | new v1 norms-bearing golden, exact bytes pinned |

## Invariant evidence

| Invariant | Evidence |
|---|---|
| A5-I01 section + required feature | `a5_t01`, `p5_g03` |
| A5-I02 norms = emitted tokens (repeats, stopwords, multi-value) | `a5_t02_t04`, `norms::tests::round_trip_and_lookup` |
| A5-I03 physical-order/field ordering | `a5_t06`, `a5_t07` |
| A5-I04 legacy bytes/readability | `a5_t08`, `p5_g02` (unchanged golden) |
| A5-I05 malformed norms fail closed | `norms::tests::{missing_required_field,wrong_total,trailing_bytes,bad_version,declared_size_beyond_budget}`, `a5_t10` |
| A5-I06 exact BM25 stats | `a5_t17` (independent arithmetic oracle), `a5_t05`, `search::score::legacy_segment_field_length_budget_is_enforced` |
| A5-I07 query-proportional new-format stats | `a5_t22`: rare term succeeds with `max_scanned_posting_occurrences=1` and `max_dictionary_terms_examined=40`, fails at probe budget 1 |
| A5-I08 legacy fallback only | `search::score::legacy_segment_field_length_budget_is_enforced` (golden legacy segment) |
| A5-I09 cancellation/budgets | `a5_t25`, existing F-suites |
| A5-I10 lifecycle/norms immutability | `a5_t29` (Memory + Fs commit/reopen) |
| A5-I11 PR 7 output contracts | all `pr07_*` suites + `pr07_amendment04` oracle |
| A5-I12 qualified before/after | **QUALIFIED** — `benchmarks/reports/pr07-amendment05-comparison.md` |

Full acceptance-test traceability for A5-T01–T33, including documented deviations,
is in [amendment-05-test-traceability.md](amendment-05-test-traceability.md).

## Gates (stable 1.98.1 and MSRV 1.85.0)

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` ×2 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` ×2 | PASS |
| `cargo test --workspace --all-targets` ×2 | **1049 passed, 7 ignored, 0 failed** |
| `cargo llvm-cov --workspace --all-features --fail-under-lines 85` | PASS — **92.04% line** |
| `cargo doc --workspace --no-deps` ×2 | PASS |
| `cargo bench -p quervant-core --no-run` ×2 | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS — 33/33 |

## Performance — QUALIFIED

- **Pre-optimization qualified baseline:** PASS. Run from an isolated `git
  worktree` checked out at clean `a8adf37` (`git_dirty=false`), 3/3 trials
  `qualified`, every contention check `clear`: `run_base=
  20261014T035234Z-a8adf37`.
- **Post-optimization qualified baseline:** PASS. Clean `eb28f7e` (optimized
  code plus the test-only runner aggregate fix), 3/3 trials `qualified`, every
  contention check `clear`: `run_base=20261014T041511Z-eb28f7e`.
- Identical guest (`Linux 6.18.33.2-microsoft-standard-WSL2`, i7-10750H), ext4,
  Criterion 0.7.0, fixture metadata SHA-256
  `09bb89876fb2e1233d7ec7a5d65b1fd43a65213787878c3ce84793d0c504b128` and dataset
  digest `930cdb59945008035c22f7899afa95265b971159828989d725555d7e831c0b7b`.
  Each v2 trial was independently validated with `validate-report.py`.
- Artifacts: `benchmarks/reports/pr07-amendment05-{before,after}.json` and
  `benchmarks/reports/pr07-amendment05-comparison.md` (per-workload medians,
  min/max, trial SHA-256, provenance).
- **Result:** scored lexical search **1.68x–2.06x** faster; corpus-size scaling
  ratios at 2K/10K/100K: rare 1.82x/2.03x/2.06x, common 1.74x/1.78x/1.92x.
  `match-all`/`pure-negative` 1.00x/1.02x; postings decode 0.97x–1.00x,
  dictionary present 1.01x–1.05x, absent 1.02x–1.05x, BM25 equation control
  1.01x — no unexplained material regression. `n`/live-norm summation remains
  O(doc_count) per search; no O(1) or zero-allocation claim.
- **Chronological note:** the gate intends the pre-baseline to predate
  production edits; because the first attempts were blocked, the pre-baseline was
  collected from the unmodified pre-optimization commit after the implementation
  commit existed. The measured tree was clean and exactly pre-optimization; the
  order is recorded in the comparison artifact.
- **Runner defect found and fixed:** the three-trial runner passed a single
  `--trial-report` flag followed by three paths; `argparse` (`action="append"`)
  consumed only the first, so aggregation always failed for `--trials > 1`. Fixed
  to emit one flag per trial (`eb28f7e`) with a script regression test.
- Profilers (`perf`/flamegraph/`heaptrack`) remain **UNAVAILABLE**; no
  symbol-level attribution.

## Diagnostic scaling (superseded by the qualified comparison)

This earlier single-run observation was recorded while the gate was blocked. It is
retained as historical evidence; the qualified pre/post comparison above
supersedes it. Single Criterion run of `--bench search -- pr07_search_scaling` on
the optimized commit (`CRITERION_HOME` isolated), correctness-gated oracle passed.

| Workload | optimized (this run) | historical/unqualified baseline | direction |
|---|---:|---:|---|
| 10K term-rare | 14.49 ms | 34.96 ms | ~2.4x faster |
| 10K term-common | 18.37 ms | 49.58 ms | ~2.7x faster |
| 100K term-rare | 134.33 ms | 327.49 ms | ~2.4x faster |
| 100K term-common | 175.46 ms | 393.70 ms | ~2.2x faster |

The pre-baseline is the Amendment 04 historical/unqualified run (contended), so
this is a **directional scaling observation only**, not a qualified same-environment
before/after ratio. It is consistent with eliminating the O(all postings) scan and
confirms that rare/common default-term latency still grows with corpus size (norms
decode is O(doc_count)) rather than with unrelated dictionary/postings work.

## Residual risks

1. The qualified before/after was collected with the pre-baseline after the
   implementation commit existed (from the clean pre-optimization commit); the
   collection order is documented in the comparison artifact.
2. Norms are decoded once per search per segment (`SegmentReader::open` is
   per-search), which is O(doc_count × scoring fields) per search — permitted by
   the plan, but a constant-factor cost for queries that need no scoring fields
   (e.g. `MatchAll`). A snapshot-level shared norms cache would remove it but
   requires an approved `ReaderSnapshot`/`SegmentSnapshot` change.
3. `max_field_length_entries/bytes` now bound only the legacy fallback; new-format
   norms are bounded by segment decode/snapshot limits. Existing Amendment 01
   `l02`/`f08` assertions were updated accordingly (documented, not weakened for
   the legacy path, which has its own unit test).
4. Tombstone/merge behavior is future PR 9; the persisted format retains
   per-document lengths so live totals can be recomputed.
5. `reader.postings` leaf lookup remains a linear dictionary scan (uncharged)
   distinct from the bounded stats probes; not changed by this amendment.

# PR 15G-A acceptance fixup

**Status:** IN PROGRESS — focused implementation and evidence reconciliation.
**Starting branch HEAD (reviewed):** `b120f9f8d63901cd4bdc9bb83fb4462a5b11d6ad`
**PR 15G-A base:** `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc`
**Fixup scope:** tests/evidence only; no production cache, format, query, storage or budget change.

## Preflight observations (before edits)

- Clean tracked tree on `dev/pr15g-a-retained-column-geometry`.
- `origin/main` = `f44d7f4fc0f061bf9b666fd2bd4e902ba7a874bc`; merge-base with the
  branch is the same commit.
- Frozen PR 15F report SHA-256:
  `384c02904cdd9fefecc2050472553b392962e6aa11f254adfa3a321a7c381096`.
- Baseline focused suites all passed (see `target/pr15g-a/fixup/baseline-*.log`).

### Counterexamples to correct

1. **CEX-01 — false fallback claim.** `Index::open_existing` delegates to
   `Index::open_with_limits(..., IndexLimits::default())`, so the previous
   `ga_i05` 64-KiB limit was discarded on reopen and its correctness assertions
   did not prove a metadata-cap fallback.
2. **CEX-02 — undetected cache-path defect.** The previous GA-I06 integration
   proved only standalone `SegmentReader::open` rejection of rebuilt malformed
   COLUMNS bytes; it did not prove the metered `VerifiedSegmentState::build_cached`
   path returns the same typed error and publishes nothing.
3. **CEX-03 — missing executable acceptance.** A documentation note that RustFS
   is blocked is not an executable ignored test for hosted CI.
4. **CEX-04 — wrong remote inference.** The existence of
   `pr13_remote_proxy`/`pr13_crash_rustfs` is not GA-I08 execution evidence for
   this HEAD; every mapped test must be actually run or marked BLOCKED.

## Invariant mapping

| ID | Invariant |
|---|---|
| FX-I01 | Caller-supplied `IndexLimits` survive public reopen |
| FX-I02 | Exact metered allowance retains geometry once; zero/one-under do not |
| FX-I03 | Fallback remains fully validating and value-identical |
| FX-I04 | Digest-valid schema-invalid COLUMNS never yields cached state |
| FX-I05 | Rejected/error candidates release reservations and allow a valid retry |
| FX-I06 | Remote bootstrap uses the real S3 adapter and persisted generation |
| FX-I07 | Typed range/explicit sort keep literal hits, order and values |
| FX-I08 | Warm reread of the same snapshot makes no extra provider requests |
| FX-I09 | Existing H*/K* fault harness evidence is executed, not inferred |
| FX-I10 | No production/format/frozen-report change |
| FX-I11 | No PASS claim without actual execution evidence |

The detailed case dispositions, exact assertions and residual blockers are added
at the end of this document after the fixup runs.

## Fixup results

No production behavior changed. All edits are in test modules, the new ignored
RustFS executable, one additive CI invocation and these evidence documents.

### F15G-A-01 — GA-I05 corrected limit and observable fallback

| Witness | What it proves | Result |
|---|---|---|
| `ga_i05_reduced_limit_survives_public_reopen_and_queries` | The 64-KiB `IndexLimits` value is supplied to `Index::open_with_limits`; term, `n` range and `n ASC` results stay exact | PASS |
| `g5_02_private_zero_exact_and_one_under_observable_fallback` | cap=0 / exact / one-under; four repeated fallback rounds; slot, verification, charge, identity, independent counters, value parity and release | PASS |
| `g5_03_reopened_index_with_exact_resident_cap_uses_fallback` | Real `Index::create_with_limits` → writer commit → `Index::open_with_limits` at exactly `resident_bytes`; four fallback reads with no retained geometry/charge/Ready slot/verification | PASS |

The previous `open_existing`-based GA-I05 is gone. The public integration test no
longer claims to observe an internal cache miss.

Observed g5_03 boundary: candidate allowance is strictly greater than encoded
resident bytes for the minimal committed segment, so the exact reader-copy cap
forces a metadata-candidate rejection while remaining sufficient for active
reader admission.

### F15G-A-02 — GA-I06 digest-valid malformed COLUMNS

`u18_valid_envelope_bad_columns_rejected_by_metered_candidate`:

- Rebuilds the full segment with `ContainerBuilder`, preserving every
  required/optional feature tuple (including the original duplicate baseline
  pair), every section `(kind, flags, aux)` and every non-COLUMNS body.
- Corrupts only COLUMNS byte 10 (first column type tag).
- `parse_container` succeeds on the rebuilt bytes; features, sections and
  non-COLUMNS bodies are asserted equal, and the COLUMNS body is asserted equal
  except at byte 10.
- Standalone `SegmentReader::open` → `FieldTypeMismatch`.
- Metered `VerifiedSegmentState::build_cached` → `Err(FieldTypeMismatch)`, not
  `Ok(None)`/`Ok(Some(_))`; `budget.used()==0` afterwards.
- The same budget handle then admits the pristine bytes, retains geometry with a
  nonzero charge, and releases to zero on drop.

The original real-boundary `ga_i06_corrupt_column_geometry_fails_closed` test
still passes separately.

### F15G-A-03 — GA-I07 real RustFS

New file: `crates/quervant-core/tests/pr15g_a_rustfs.rs`.

`ga_i07_real_rustfs_cold_bootstrap_typed_sort_and_warm_reread` was compiled with
`--all-features --no-run` and then **actually executed** against
`rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
in a disposable local container with the CI-equivalent test credentials:

- generation 1 after one commit;
- disposable local workspace removed before reopen;
- cold remote bootstrap succeeds;
- `MatchAll` + `n ASC` → `["b","c","a"]`, total hits 3;
- `n ∈ [15,30]` + `n ASC` → `["c","a"]`, total hits 2;
- direct column map exactly `{a:30,b:10,c:20}`;
- repeated queries/column reads on the same snapshot leave
  `transfer_stats().requests()` unchanged.

The workflow now invokes the test once in the existing pinned RustFS Core remote
step. Hosted execution at the final PR HEAD remains required.

### GA-I08 — existing real fault/crash harness execution

Executed locally against the same pinned service:

| Test | Result |
|---|---|
| `pr13_remote_proxy` full ignored suite (H06, H07, H09 plus H08/H10/H11/H12) | 7 passed |
| `pr13_crash_rustfs k0` (K01–K05) | 5 passed |
| `pr13_crash_rustfs k05` repeated 10 times | 10/10 passed |

These are actual executions, not source-existence claims. Hosted logs at the
final PR HEAD remain required.

## Local QA

| Command / gate | Result |
|---|---|
| Focused reader / snapshot / integration | 7 / 41 / 6 passed |
| PR 15C / PR 15E / PR 06 integration | 5 / 17 / 13 passed (3 ignored in PR 06) |
| Stable + MSRV fmt/clippy default/all-features | PASS |
| Stable/MSRV workspace tests | 2254 passed, 10 ignored, 119 suites |
| Stable/MSRV all-features workspace tests | 2258 passed, 76 ignored, 119 suites |
| Workspace line coverage (`--all-features`) | 92.65% |
| `segment/column.rs` / `segment/reader.rs` line coverage | 94.37% / 90.26% |
| Doc / bench build / scripts / PR 15D / PR 15F Python | PASS — 108 / 83 / 54 |
| Frozen PR 15F report SHA-256 | unchanged: `384c0290...381096` |
| `git diff --check` | PASS |

Logs: `target/pr15g-a/fixup/` (focused and real-service runs) and
`target/pr15g-a/fixup/qa/` (full QA).

## Remaining blockers and residual risk

- **Performance:** P01–P04 remain `BLOCKED_OPERATOR`; no timed runner invocation
  or speedup claim exists.
- **Hosted CI:** the branch will be pushed, but no PR exists and `gh`
  credentials are invalid. Exact-head `rust`/`msrv`/`rustfs` success is not
  observed and must not be inferred from local runs.
- **Independent review:** FX-A10 remains human-owned and not started.
- Local real-RustFS execution is strong supporting evidence, not a substitute
  for the hosted pinned-service job at the final HEAD.

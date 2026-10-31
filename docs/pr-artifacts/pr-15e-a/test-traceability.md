# PR 15E-A — test traceability

- **Implementation commit:** `19ae3d7a2227be6f7b0c546d7b178366464aca59`
  (X22 amendment; supersedes `fc2c62a936cd09069d1f46ed582c247e7f78cf28`)
- **Measured HEAD / preparation commit:** `0f0091c02b3d7e057f1db10b3a12c06179f1c399`
- **Fixup (PR 15E-A-F1) source head:** see
  [`fixup-review-handoff.md`](fixup-review-handoff.md) — the verifier exit-status
  correction lands on the existing PR #82 branch and does not touch measured code.
- **Evidence status:** `PROFILED_EVIDENCE_COMPLETE` (20/20 captures, `EVIDENCE_COMPLETE`)
- **Base:** `de278e21c38bb60fa84c43951dadc7c0836787fd`
- **Python suites:** `benchmarks/pr15e/test_profile.py`,
  `benchmarks/pr15e/test_verify.py`
- **Status:** T01–T47 pass and all 20 authorized captures were executed and
  verified; `PR_ACCEPTANCE = PENDING_REVIEW` awaits independent review.

## 1. Commands and results (executed locally)

| # | Command | Result |
|---:|---|---|
| 1 | `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py'` (history, pre-F1) | **PASS** — 79 tests, `OK (skipped=1)`; the skip is the opt-in real-adapter integration test |
| 2 | `PR15E_RUN_REAL_INTEGRATION=1 python3 -m unittest test_profile.RealAdapterIntegrationTest -v` | **PASS** — 1 test, 39.6 s: real `cargo build --release --locked` with debuginfo, real `FsDirectory` 10 K + 100 K indexes, real oracle, real adapter session |
| 2b | Real heaptrack 1.5.0 **protocol-only** smoke (real adapter, prepared 10 K index) | **PASS** — 8/8 oracle-verified replies, profiler exit 0, one `heaptrack.gz`, `heaptrack_print` exit 0 with 10 allocation sites / 760 587 allocations, single adapter PID, 211-byte preamble artifact (`973435df…`). Not a qualified capture |
| 3 | `python3 benchmarks/pr15d/harness/test_pr15d.py` | **PASS** — 83 tests |
| 4 | `cargo test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` | **PASS** — 5 tests (includes the one-snapshot `QuerySession` proofs) |
| 5 | `cargo +1.85.0 test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` | **PASS** — 5 tests |
| 6 | `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 108 passed, 0 failed |
| 7 | `python3 benchmarks/pr15d/corpus/generate.py --out target/pr15e/pr15e-preflight-corpus` | **PASS** — `5cdc9341…` / `6ea867fe…`, manifest `69052c66…` |
| 8 | `python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15e/pr15e-preflight-corpus` | **PASS** — 10 000 / 100 000 rows |
| 9 | `python3 benchmarks/pr15e/profile.py prepare --out target/pr15e/20261031T164645Z-0f0091c` | **PASS** — `PREPARED` on the exact final head, 20 lanes, `prepare.json` `d6ac3421…`, `prepared_digest` `78a01c77…` |
| 9b | `python3 benchmarks/pr15e/profile.py capture …` ×20 (fixed order, attested window) | **PASS** — 20/20 `CAPTURED_RAW`, 0 retries, 40/40 contention `clear`, campaign `17:24:45Z … 17:44:53Z` |
| 10 | `python3 benchmarks/pr15e/verify.py --run target/pr15e/20261031T164645Z-0f0091c` | **PASS** — `EVIDENCE_COMPLETE`, 20/20, 0 prepare violations, `verification.json` `52ec0465…` |
| 10b | `python3 benchmarks/pr15e/verify.py --run … --analysis …/analysis.json --publish-manifest` | **PASS** — `analysis_valid: true` (81 entries), manifest `benchmarks/reports/pr15e-a/profile-manifest.json` `adfe7ead…` |
| 11 | (pre-attestation) `capture` without `<run>/attestation.json` | **BLOCKED (expected)** — exit 3, `BLOCKED_ATTESTATION`, no capture directory created |
| 12 | (pre-attestation) `verify.py --publish-manifest` from `PARTIAL` | **BLOCKED (expected)** — exit 3, `X31_EVIDENCE_INCOMPLETE`, no manifest written |
| 13 | `git diff --name-only de278e2...HEAD` + `classify_diff_paths()` (history) | **PASS** — 11 changed paths at the time; the current count is recomputed in §5 |

## 2. Required T01–T47 mapping

Every entry names the executable test that fails if the invariant regresses.
`test_profile.py` fakes only the profiler/adapter *process boundary*; all such
evidence is labelled `TEST_FIXTURE` and can never be published.

| ID | Test | Outcome |
|---|---|---|
| T01 | `ScopeAndOracleTests.test_t01_diff_allowlist_rejects_protected_paths` + row 13 | PASS |
| T02 | `test_t02_absent_lane_has_zero_hits` | PASS |
| T03 | `test_t03_rare_lane_has_single_hit` | PASS |
| T04 | `test_t04_medium_matches_n_over_eight` | PASS |
| T05 | `test_t05_common_matches_n_over_two_minus_one` | PASS |
| T06 | `CaptureTests.test_t06_t08_one_adapter_process_per_capture` | PASS |
| T07 | Row 4/5 adapter tests (`QuerySession` single-snapshot) + `check_15d_prerequisites` source assertions in rows 9/10 | PASS |
| T08 | `CaptureTests.test_t06_t08_one_adapter_process_per_capture` (distinct PIDs per capture) | PASS |
| T09 | Row 2 real integration + `prepare.json` indexes (10 000/100 000 indexed = reopened) | PASS |
| T10 | `CaptureTests.test_t09_real_adapter_evidence_is_required` | PASS |
| T11 | `SourceLockTests.test_t11_changed_corpus_is_refused` | PASS |
| T12 | `test_t12_changed_adapter_binary_is_refused` | PASS |
| T13 | `test_t13_changed_source_sha_is_refused` | PASS |
| T14 | `test_t14_changed_or_missing_index_is_never_rebuilt` | PASS |
| T15 | `ArgumentTests.test_t15_invalid_enum_values_are_typed`, `test_t15_cli_returns_usage_exit_code` | PASS |
| T16 | `test_t16_k10_control_is_100k_only` | PASS |
| T17 | `test_t17_wrong_seconds_are_rejected` | PASS |
| T18 | `test_t18_unknown_cli_option_is_rejected` | PASS |
| T19 | `test_t19_profiler_must_target_the_prepared_adapter` | PASS |
| T20 | `test_t20_perf_empty_data_is_not_captured_raw`, `test_t20b_perf_nonzero_exit_is_failed`, `test_t20c_perf_report_failures_are_blocked` | PASS |
| T21 | `test_t21_heaptrack_raw_artifacts_must_be_unambiguous` | PASS |
| T22 | `test_t22_profiler_banner_is_a_hard_stop_with_preserved_raw` (unexpected banner, retained negative test) | PASS |
| T23 | `test_t23_incomplete_warmups_are_refused` | PASS |
| T24 | `test_t24_insufficient_profiled_requests_are_not_qualified` | PASS |
| T25 | `test_t25_altered_total_hits_aborts` | PASS |
| T26 | `test_t26_altered_doc_ids_aborts` | PASS |
| T27 | `test_t27_child_death_cleans_the_process_group` | PASS |
| T28 | `test_t28_path_traversal_is_rejected_before_writing` | PASS |
| T29 | `test_t29_symlink_inside_run_tree_is_rejected` | PASS |
| T30 | `test_t30_destinations_are_never_overwritten` | PASS |
| T31 | `IntegrityTests.test_t31_truncated_artifact_fails` | PASS |
| T32 | `test_t32_edited_artifact_after_manifest_fails` | PASS |
| T33 | `test_t33_mutated_prepare_fails` | PASS |
| T34 | `test_t34_modified_canonical_report_fails` | PASS |
| T35 | `PublicationTests.test_t35_published_manifest_carries_no_latency_or_inferred_metrics` | PASS |
| T36 | `AttributionTests.test_t36_units_and_inferred_stage_ns_are_rejected` | PASS |
| T37 | `CaptureTests.test_t37_missing_perf_is_blocked` | PASS |
| T38 | `test_t38_missing_heaptrack_print_is_blocked` | PASS |
| T39 | `AttestationTests` — missing, flag-only, expired, short, wrong-host, no-PR-label, contention, window-ended-mid-capture | PASS |
| T40 | `MatrixTests.test_t40_missing_capture_yields_partial` | PASS |
| T41 | `test_t41_wrong_labeled_capture_fails` + `test_unlisted_or_duplicate_capture_is_reported` | PASS |
| T42 | `test_t42_verification_is_byte_identical_on_replay` | PASS |
| T43 | `PublicationTests` — sensitive content, incomplete evidence, test fixtures, explicit mode, no-`PRIVATE_PENDING_REVIEW` omission | PASS |
| T44 | `MatrixTests.test_t44_sample_count_claim_must_match_the_report` | PASS |
| T45 | `AttributionTests.test_t45_unsupported_measurement_is_rejected`, `test_t45_missing_symbolization_marks_attribution_unresolved` | PASS |
| T46 | `test_t46_summed_inclusive_percent_is_rejected` | PASS |
| T47 | `test_t47_missing_common_100k_lane_blocks_attribution` | PASS |

Additional behavioural tests (not tied to a single T ID): fixed-matrix shape
(20 captures, 12 perf / 8 heaptrack), `perf` sample-count abbreviation parsing
(`11K` → 11 000), lost-sample parsing, heaptrack record parsing, adapter error
status handling, `READ`-timeout classification, and the approved X22 exception:

| X22 amendment behaviour | Test | Outcome |
|---|---|---|
| Two-line accepted preamble preserved byte-for-byte + hashed | `CaptureTests.test_heaptrack_preamble_is_preserved_byte_for_byte` | PASS |
| Altered / reversed / duplicated / garbage / wrong-path / escape-path / unexpected banner | `test_x22_heaptrack_preamble_variants_are_rejected` | PASS |
| Missing preamble | `test_x22_heaptrack_missing_preamble_is_rejected` | PASS |
| Banner after the first adapter reply | `test_x22_preamble_after_the_first_response_is_rejected` | PASS |
| `perf` stays strict (heaptrack-style output rejected) | `test_perf_rejects_heaptrack_style_output` | PASS |
| Exception pinned to heaptrack 1.5.0 (1.4.0 rejected) | `test_preamble_exception_is_pinned_to_heaptrack_1_5_0` | PASS |
| Path/line validator unit matrix | `test_preamble_validation_rejects_non_designated_paths` | PASS |
| Verifier requires the preamble for 1.5.0 | `IntegrityTests.test_heaptrack_1_5_0_preamble_is_required` | PASS |
| Verifier rejects tampered preamble bytes | `test_tampered_preamble_content_fails` | PASS |
| Verifier rejects a preamble artifact on `perf` | `test_preamble_artifact_on_a_perf_capture_fails` | PASS |

## 3. Repository QA

Rust sources are unchanged by this PR (Python/docs only); the gates below were
re-run after the X22 amendment and are reported for the amended tree.

| Gate | Command | Result |
|---|---|---|
| Formatting (stable) | `cargo fmt --all -- --check` | PASS |
| Formatting (MSRV) | `cargo +1.85.0 fmt --all -- --check` | PASS |
| Clippy (stable, default) | `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| Clippy (stable, all features) | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Clippy (MSRV, default) | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | PASS |
| Clippy (MSRV, all features) | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Tests (stable, default) | `cargo test --workspace --all-targets` | PASS |
| Tests (stable, all features) | `cargo test --workspace --all-targets --all-features` | PASS — 2173 passed, 0 failed, 75 ignored |
| Tests (MSRV, default) | `cargo +1.85.0 test --workspace --all-targets` | PASS |
| Tests (MSRV, all features) | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| Coverage | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.31 %** lines (51 738 lines, 4 236 missed), 87.90 % functions, 91.81 % regions (re-run after the X22 amendment) |
| Documentation | `cargo doc --workspace --all-features --no-deps` | PASS |
| Bench build | `cargo bench --workspace --no-run` | PASS |
| Script tests | `bash benchmarks/scripts/test-scripts.sh` | PASS — 108/108 |
| Whitespace | `git diff --check` | PASS |
| Exact-head CI | `Rust CI` #278 on `0f0091c` (PR #82) | **PASS** — `rust`, `msrv`, `rustfs` all `success` |
| Real RustFS suite | `rustfs` job in `Rust CI` #278 | **PASS** — real RustFS S3 adapter, core remote, M1/M2/M3/M5, fault proxy/crash, critical race ×10 (not part of the profiling workload) |

## 4. Gates (campaign state)

| Gate | Reason |
|---|---|
| G04 host attestation | **Observed** — `MSI`, `2026-10-31T17:24:40Z … 20:24:40Z` |
| G05 perf captures (12) | **PASS** 12/12 |
| G06 heaptrack captures (8) | **PASS** 8/8 (approved `X22-AMENDMENT` in use) |
| G07 capture semantics (20) | **PASS** 20/20 (5 warmups + ≥ 5 profiled queries, every reply oracle-checked) |
| G08 `EVIDENCE_COMPLETE` | **PASS** |
| G09 attribution | **PASS** — four primary lanes carry `perf` **and** `heaptrack` evidence with cited raw lines |
| G11 independent review | **Open** — human reviewer has not reviewed this dossier |

A present or passing test proves the *code path*, not that a capture executed.
The campaign reported here **did** execute the 20 authorized captures, and their
records are listed above; the **raw profiler evidence is still private and has not
been independently reviewed**, so `G11` stays `PENDING_REVIEW`.

## 5. PR 15E-A-F1 — verifier requested-operation exit-status fixup

Defect: `verify()` selected the process exit code from **capture completeness only**,
so a complete 20-capture matrix plus an explicitly invalid `--analysis`, or a refused
`--publish-manifest`, returned exit `0`. Automation could read a refused operation as
success.

Change (only the final exit selection in `verify.py::verify()`; capture
completeness, `verification.json` schema, summary fields, publication logic and
`profile.EXIT_*` constants are unchanged):

1. capture-completeness exit first — `PARTIAL`/`BLOCKED` → 3, `FAILED` → 4, and it can
   never be upgraded to success;
2. then, if `--analysis` was supplied and is invalid/missing → `EXIT_FAILED` (4),
   retaining `EVIDENCE_COMPLETE` and `analysis_valid: false`;
3. then, if `--publish-manifest` was requested → `EXIT_FAILED` (4) when the outcome
   carries a `code`, is not a mapping, has a non-boolean `written`, or lacks a
   64-character lowercase hex `sha256`; a first write and an identical-bytes no-op
   both stay `EXIT_OK`.

Executed regression evidence (`benchmarks/pr15e/test_verify.py`,
`VerifyExitStatusTests`), all driving the real `VERIFY.verify()` path:

| Case | Scenario | Exit | Status kept | Observed |
|---|---|---:|---|---|
| FX-01 | complete evidence, no requested operation (E01) | 0 | `EVIDENCE_COMPLETE` | PASS |
| FX-02 | complete evidence + valid `--analysis` (E02) | 0 | `EVIDENCE_COMPLETE` | PASS |
| FX-03 | complete evidence + invalid `--analysis` (E03) | 4 | `EVIDENCE_COMPLETE`, `analysis_valid:false` | PASS (failed 0 vs 4 pre-fix) |
| FX-04 | complete evidence + missing `--analysis` file (E03) | 4 | `EVIDENCE_COMPLETE`, `analysis_valid:false` | PASS (failed 0 vs 4 pre-fix) |
| FX-05 | complete evidence + refused publication (`X31_TEST_FIXTURE`) (E06) | 4 | `EVIDENCE_COMPLETE` | PASS (failed 0 vs 4 pre-fix) |
| FX-06 | invalid analysis + `--publish-manifest` (`X31_ANALYSIS_INVALID`) (E07) | 4 | `EVIDENCE_COMPLETE` | PASS (failed 0 vs 4 pre-fix) |
| FX-07 | one capture + `--publish-manifest` (E09) | 3 | `PARTIAL` | PASS |
| FX-08 | publication newly written (`written:true`) (E04) | 0 | `EVIDENCE_COMPLETE` | PASS |
| FX-09 | identical existing manifest (`written:false` + sha256) (E05) | 0 | `EVIDENCE_COMPLETE` | PASS |
| FX-10a | malformed publication result (E08) | 4 | `EVIDENCE_COMPLETE` | PASS (failed 0 vs 4 pre-fix) |
| FX-10b | capture integrity failure, no analysis (E11) | 4 | `FAILED` | PASS |
| FX-11 | published manifest bytes unchanged by the fixup | n/a | n/a | PASS — `adfe7ead…` before and after |

Pre-fix red run: `Ran 11 tests … FAILED (failures=5)` with `0 != 4` for FX-03,
FX-04, FX-05, FX-06 and FX-10a. Post-fix: `Ran 11 tests … OK`.

One existing expectation encoded the defect and was reconciled inside the same file:
`PublicationTests.test_t43_publication_refuses_sensitive_content` asserted exit `0`
for a refused publication; it now asserts exit `4` while still requiring
`EVIDENCE_COMPLETE`, `written: false` and the `X31` code. The assertion was
tightened, never weakened.

Re-executed suites after the change (this fixup, same tree):

| Suite | Result |
|---|---|
| `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py'` | **PASS — 90 tests, 0 failed, 1 skipped** (was 79) |
| `PR15E_RUN_REAL_INTEGRATION=1 … test_profile.RealAdapterIntegrationTest` | **PASS** — real adapter, real `FsDirectory` 10 K/100 K, independent oracle |
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | **PASS** — 83 tests |
| `cargo test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` (stable + 1.85.0) | **PASS** — 5 + 5 |
| `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 108/108 |

No profiling capture was re-run, no attestation was recreated, and no measured file
changed (`profile.py`, `test_profile.py`, `profile-manifest.json` blob/SHA identical).
Changed paths for the whole PR are recomputed from
`git diff --name-only de278e2...HEAD` at the fixup head and recorded in
[`fixup-review-handoff.md`](fixup-review-handoff.md).

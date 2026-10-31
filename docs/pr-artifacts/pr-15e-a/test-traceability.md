# PR 15E-A — test traceability

- **Implementation commit:** `fc2c62a936cd09069d1f46ed582c247e7f78cf28`
- **Base:** `de278e21c38bb60fa84c43951dadc7c0836787fd`
- **Python suites:** `benchmarks/pr15e/test_profile.py`,
  `benchmarks/pr15e/test_verify.py`
- **Status:** `BLOCKED_ATTESTATION`; T01–T47 are implemented and pass, but the
  capture-dependent gates (G05–G09) remain unobserved, so `PR_ACCEPTANCE =
  PENDING_REVIEW`.

## 1. Commands and results (executed locally)

| # | Command | Result |
|---:|---|---|
| 1 | `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py'` | **PASS** — 69 tests, `OK (skipped=1)`; the skip is the opt-in real-adapter integration test |
| 2 | `PR15E_RUN_REAL_INTEGRATION=1 python3 -m unittest test_profile.RealAdapterIntegrationTest -v` | **PASS** — 1 test, 36.9 s: real `cargo build --release --locked` with debuginfo, real `FsDirectory` 10 K + 100 K indexes, real oracle, real adapter session |
| 3 | `python3 benchmarks/pr15d/harness/test_pr15d.py` | **PASS** — 83 tests |
| 4 | `cargo test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` | **PASS** — 5 tests (includes the one-snapshot `QuerySession` proofs) |
| 5 | `cargo +1.85.0 test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` | **PASS** — 5 tests |
| 6 | `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 108 passed, 0 failed |
| 7 | `python3 benchmarks/pr15d/corpus/generate.py --out target/pr15e/pr15e-preflight-corpus` | **PASS** — `5cdc9341…` / `6ea867fe…`, manifest `69052c66…` |
| 8 | `python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15e/pr15e-preflight-corpus` | **PASS** — 10 000 / 100 000 rows |
| 9 | `python3 benchmarks/pr15e/profile.py prepare --out target/pr15e/20261031T122508Z-fc2c62a` | **PASS** — `PREPARED`, 20 lanes, `prepare.json` `b09b9456…` |
| 10 | `python3 benchmarks/pr15e/verify.py --run target/pr15e/20261031T122508Z-fc2c62a` | **PARTIAL (expected)** — exit 3, 20 unobserved, 0 prepare violations, `verification.json` `2c17f92f…` |
| 11 | `python3 benchmarks/pr15e/profile.py capture … --idle-confirmed` (no attestation) | **BLOCKED (expected)** — exit 3, `BLOCKED_ATTESTATION`, no capture directory created |
| 12 | `python3 benchmarks/pr15e/verify.py --run … --publish-manifest` | **BLOCKED (expected)** — exit 3, `X31_EVIDENCE_INCOMPLETE`, no manifest written |
| 13 | `git diff --name-only de278e2...HEAD` + `classify_diff_paths()` | **PASS** — 7 changed paths, 0 allowlist violations |

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
| T22 | `test_t22_profiler_banner_is_a_hard_stop_with_preserved_raw` | PASS |
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
status handling, `READ`-timeout classification.

## 3. Repository QA (final code head `fc2c62a`, Rust source unchanged since)

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
| Coverage | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.31 %** lines (51 738 lines, 4 236 missed), 87.90 % functions, 91.81 % regions |
| Documentation | `cargo doc --workspace --all-features --no-deps` | PASS |
| Bench build | `cargo bench --workspace --no-run` | PASS |
| Script tests | `bash benchmarks/scripts/test-scripts.sh` | PASS — 108/108 |
| Whitespace | `git diff --check` | PASS |
| Exact-head CI | GitHub Actions on `fc2c62a` | **BLOCKED** — `gh` credentials invalid (X38); not claimed |
| Real RustFS suite | repository CI job | **BLOCKED** — same credential blocker; not part of the profiling workload |

## 4. Unrun gates (explicit)

| Gate | Reason |
|---|---|
| G04 host attestation | No PR 15E-A operator statement (X15) |
| G05 perf captures (12) | Requires G04 |
| G06 heaptrack captures (8) | Requires G04 **and** a heaptrack relaying decision (X22) |
| G07 capture semantics (20) | Requires G05/G06 |
| G08 `EVIDENCE_COMPLETE` | Requires G05–G07; current status `PARTIAL` |
| G09 attribution | Requires the four primary `perf` **and** `heaptrack` lanes |
| G11 independent review | Human reviewer has not reviewed this dossier |

A present or passing test proves the *code path*, not that a capture executed;
no capture is claimed in this PR.

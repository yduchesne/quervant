# PR 15G-C fixup safe rollback

**Rule:** GF-D49/GF-D50
**Trigger:** qualified fixup campaign failed GF-P01 and GF-P04.
**Action:** additive rollback of only C production search files to the B carryover
source (`97d7ce1bc82c9903304371ce8b45074c3981adf5`) after preserving all fixup
evidence.

## Source equality

The following files are byte-identical to `97d7ce1` after rollback:

- `crates/quervant-core/src/search/execute.rs`
- `crates/quervant-core/src/search/unified.rs`

`git diff --quiet 97d7ce1 -- <both files>` exits 0.

## Preserved

- B carryover tests in `segment/{reader,stored}.rs` are untouched.
- C integration tests `pr15g_c_stream.rs` and `pr15g_c_rustfs.rs` remain and pass
  against the restored B execution path.
- Failed C and fixup reports, raw benchmark evidence and negative results remain
  immutable.
- The C benchmark runner remains for forensic replay only; it makes no C success
  claim.

## Post-rollback QA

- Stable/MSRV fmt and Clippy default/all-features: PASS.
- Workspace tests: 2301 passed / 10 ignored (default); 2305 passed / 78 ignored
  (all features), stable and MSRV.
- Coverage: 92.72%.
- `execute.rs` / `unified.rs` line coverage: 94.38% / 96.83%.
- C/A/B RustFS, proxy, crash K0 and 10× K05: PASS locally.
- Scripts and Python benchmark suites: PASS.

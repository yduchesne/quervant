# PR 15I-D2-A — QA evidence

## Tested tree

- Code/test/evidence commit: `9e1641dcee77ac0e5876a427de1f8e56c36a5ab0`
- BASE: `9429dce99827f25766a92c1fbded8f78a0b168f1`
- Final tooling freeze T0: `747ceb2464425f2392829c5165decf4c697cf34b`
- Working tree after QA: clean except this documentation-only follow-up.
- Production `src/`, PR15D adapter source, corpus, oracle, lockfile, CI, schema
  and codecs: no change.

## Command results

| # | Command | Result |
|---|---|---|
| 1 | `python3 -m py_compile benchmarks/pr15i_d2a/*.py` | **PASS** |
| 2 | `python3 -m unittest discover -s benchmarks/pr15i_d2a -p 'test_*.py' -v` | **PASS** — 76 tests, 0 failures |
| 3 | `python3 benchmarks/pr15d/harness/test_pr15d.py` | **PASS** — 83 tests, 3 skipped (environment-gated) |
| 4 | `cargo fmt --all -- --check` | **PASS** |
| 5 | `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** |
| 6 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| 7 | `cargo test -p quervant-core --all-features --test pr15i_d2a_scoring_contract` | **PASS** — 15 passed |
| 8 | `cargo test --workspace --all-targets` | **PASS** — 2,454 passed, 0 failed, 13 ignored |
| 9 | `cargo test --workspace --all-targets --all-features` | **PASS** — 2,458 passed, 0 failed, 92 ignored (RustFS-gated) |
| 10 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** — **92.68% line coverage** (89,917 of 97,024 lines covered; 7,107 missed), 87.48% functions |
| 11 | `cargo doc --workspace --no-deps` | **PASS** |
| 12 | `cargo +1.85.0 fmt --all -- --check` | **PASS** |
| 13 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| 14 | `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS** |
| 15 | `cargo +1.85.0 doc --workspace --no-deps` | **PASS** |
| 16 | `git diff --check` | **PASS** |
| 17 | Frozen tooling manifest re-check | **PASS** |
| 18 | Three archive round-trip extractions + independent `verify.py` | **PASS** (all three, byte-identical sanitized/verification output) |

## Coverage note

The exact measured line coverage from `cargo llvm-cov` is **92.68%**, above the
mandatory 85% floor. No crate was omitted and no production module was excluded.
The new Rust test file increased coverage of the public scoring path; the
existing repository tests contribute the remainder.

## Integration topology actually exercised

- **Local real filesystem:** every SC test uses native `FsDirectory` with a real
  writer commit and reopened `ReaderSnapshot`; SC-15 reopens a fresh directory.
- **Production search path:** `UnifiedSearcher::search` for all SC scenarios.
- **PR15D lanes:** real 10K/100K index builds, exact oracle, fixed adapter JSON,
  pinned affinity, contention probes and sealed campaigns.
- **RustFS:** not run locally. The all-features workspace suite reports the
  RustFS container tests as ignored; hosted CI owns those real-container jobs.
  This measurement-only PR changes no storage semantics.

## Failure taxonomy

No failures required a taxonomy disposition. The only rejected attempts were
harness/protocol rejections preserved as superseded evidence (see
`preflight.md` and `decision-register.md`); they are `ENVIRONMENT_OR_HARNESS`
or `FEATURE_IMPLEMENTATION_DEFECT` in the diagnostic tooling, not production
regressions.

## Pending external gates

- Hosted CI for this branch: **not run locally** (pending).
- Independent human review: **pending**.
- PR creation/merge: **not performed**.

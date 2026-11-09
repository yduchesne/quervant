# PR 15I-C fixup — execution status

## Disposition

**`15IC_GENERIC_BOUNDARY_REJECTED_SAFE_ROLLBACK`**

F0 (the mandatory generic-boundary falsification test) produced a **valid,
independently verified failure** on a second complete run, so the prescribed
action was taken: the single `#[inline(never)]` attribute was rolled back and
operator restoration was **HARD STOPPED** (`FX-D33`). Production is byte-identical
to merged PR 15I-B. No PR 15I-C capability is delivered, and none is claimed.

External statuses, reported separately and truthfully:
`REAL_RUSTFS_BLOCKED`, `HOSTED_CI_PENDING`, `REVIEW_PENDING`, `NOT_PUSHED`,
`NOT_MERGED`.

## 1. Phase outcomes

| Phase | Status | Evidence |
|---|---|---|
| F-00 source reconciliation + baseline QA | PASS | `fixup-preflight.md` |
| F-01 generic `#[inline(never)]` control + diagnostic harness | PASS (`G_CONTROL_SHA = 50b56e9…`) | `fixup-control.md` |
| F-02 seven-lane / eight-block generic-neutrality diagnostic | **FAIL (valid)** | `fixup-performance-decision.md`; sealed `generic-boundary-04` + receipt |
| F-03 operator restoration / dispatcher | **NOT EXECUTED** (F0 precondition failed) | — |
| F-04 `FX-U/FX-I/FX-F` correctness suites | **NOT EXECUTED** | `fixup-correctness-and-qa.md` §3 |
| F-05 frozen nine-lane campaign | **NOT EXECUTED** | — |
| F-06 real RustFS + final QA | real RustFS BLOCKED; final QA PASS at the rollback tip | §4 below |
| F-07 additive rollback | PASS, protected diff empty | §2 below |
| F-08 local reporting | this document | — |

## 2. Rollback proof

Only `crates/quervant-core/src/search/unified.rs` was ever changed by this fixup;
it was restored from `6f6463cb…`. No candidate-only file existed to remove
(`diagnostics.rs`, `mod.rs`, `Cargo.toml`, `tests/pr15i_c_physical.rs` were never
restored in this fixup), and CI was never modified.

After the rollback commit:

```
git diff --quiet 6f6463cb26bcf28340cc9d4afd4dfeb040281898 HEAD -- \
  crates/quervant-core/src crates/quervant-core/Cargo.toml Cargo.lock \
  .github/workflows/ci.yml
```

must be empty; the same check over `benchmarks/pr15d`, `benchmarks/pr15i_a`,
`benchmarks/pr15i_b` and `benchmarks/pr15i_c/protocol.json` is also empty. Verified
below.

## 3. Commit identities

| Role | SHA |
|---|---|
| `MERGED_15IB_A_SHA` | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| `PREV_REJECTION_HEAD` (start) | `a3a502cd3aeea3e2d6d1b2d95eb0baf8d19b79ed` |
| `G_CONTROL_SHA` | `50b56e9fe7b22bb266ca7b0d9e209500dfc785ff` |
| Diagnostic tooling SHA | `7fbea7f4a43cd105fdb6939b84e6f5d02f59a863` |
| `FIXUP_FINAL_PROD_SHA` (rollback) | this commit (recorded in the final report) |
| `FIXUP_IMPLEMENTATION_SHA` / `FIXUP_MEASURED_SHA` | not created |

## 4. Final QA on the settled rollback tree

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` | PASS |
| `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo test --workspace --all-targets` | PASS (135 test binaries) |
| `cargo test --workspace --all-targets --all-features` | PASS |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — `TOTAL` lines **92.68%** (regions 87.48%, functions 91.96%) |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| `python3 -m unittest discover -s benchmarks/pr15d/harness` | PASS (139) |
| `python3 -m unittest discover -s benchmarks/pr15i_b` | PASS (10) |
| `python3 -m unittest discover -s benchmarks/pr15i_c` | PASS (90) |
| `python3 -m unittest discover -s benchmarks/pr15i_a` | 87 tests, 1 failure + 3 errors — `DETERMINISTIC_PREEXISTING` / source-bound (`FX-D17`), unchanged from merged main |
| `git diff --check` | CLEAN |

Coverage is measured on the rollback tree, which intentionally does not contain
the (never-created) fast-path tests. The 92.68% line figure is comparable to the
previously reported value only because production source is identical to the
merged base plus nothing.

## 5. Preserved artefacts

| Artefact | Path |
|---|---|
| Historical rejected candidate campaign | `target/pr15i-c/campaigns/paired-01` (+ receipt) — read-only |
| Diagnostic runs | `target/pr15i-c/layout-diagnostics/generic-boundary-01..04` |
| Codegen captures | `target/pr15i-c/layout-diagnostics/codegen-01..03` |
| Diagnostic receipts | `target/pr15i-c/reviews/layout-generic-boundary-03.json`, `layout-generic-boundary-04.json` |
| Tooling | `benchmarks/pr15i_c/{layout_diag,verify_layout_diag,source_proof,codegen_capture}.py` + 49 tests |
| Documentation | this `docs/pr-artifacts/pr-15i-c/fixup-*.md` set |

`generic-boundary-01` is preserved as an invalid attempt (arm-path defect) and
`-02` as a pre-measurement blocked attempt; neither is used as evidence.

## 6. Residual findings and next steps (not authorized by this plan)

1. The merged baseline's generic executor is inlined into `execute_unified`; the
   control attribute really does move 2 644 instructions out of line. The
   historical regression's suspected inlining/layout sensitivity is therefore
   plausible and now symbol-documented — not proven at microarchitectural level
   (`perf` unavailable).
2. The diagnostic's hard `1.15` per-block ceiling is under-powered on the
   sub-millisecond absent/rare lanes: two valid runs disagreed, each failing on a
   single outlying slot out of 64. A future plan should freeze the statistical
   property it wants *before* data, instead of relying on a per-block ceiling that
   effectively demands outlier-free measurement at ~50–250 µs.
3. Real RustFS acceptance remains unexecuted on this host; any future positive
   candidate must execute it before claiming review readiness.

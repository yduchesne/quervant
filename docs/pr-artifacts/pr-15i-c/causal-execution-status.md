# PR 15I-C causal experiment — execution status

## Disposition

**`15IC_CAUSAL_DIAGNOSTIC_INCONCLUSIVE`** with **`SAFE_ROLLBACK_VERIFIED`**.

Four valid, independently verified three-arm campaigns were executed (two
unbatched, two batched). The frozen §9 table awards the decisive
non-operator label for all four low-match lanes in campaign 1, but campaign 2
misses block-level floors/ceilings on two lanes, so the strict "all four lanes in
both campaigns" rule yields `CAUSAL_INCONCLUSIVE`. Production is restored
byte-identically to merged PR 15I-B; nothing is qualified and nothing is merged.

External statuses: `REAL_RUSTFS_BLOCKED`, `HOSTED_CI_PENDING`, `REVIEW_PENDING`,
`NOT_PUSHED`, `NOT_MERGED`.

## 1. Phase outcomes

| Phase | Status | Evidence |
|---|---|---|
| P0 preflight + invariant trace | PASS | `causal-preflight.md`, `causal-invariant-traceability.md` |
| P1 restore measured candidate (`RESTORED_B_SHA`) | PASS | 7/7 blob hashes equal `OLD_B`; candidate suites green |
| P2 feature-only gate (`CAUSAL_BC_SOURCE_SHA`) | PASS | only Cargo.toml + unified.rs delta; mode truth table exact |
| P3 tooling freeze (`CAUSAL_TOOLING_SHA`) + plumbing fixups | PASS | protocol, controller, verifier, 64 tests |
| P4 pre-measurement proof | PASS | source/feature/default-release proof, restored tests, score parity, 40 CV cases |
| P5 four campaigns + independent receipts | COMPLETE | `target/pr15i-c/causal-campaigns-v1/`, `target/pr15i-c/reviews/causal-*` |
| P6 classification | INCONCLUSIVE | `causal-performance.md` §3 |
| P7 rollback + final QA | PASS | §2, §4 |

## 2. Rollback identity

Restored from merged `BASE_A`: `crates/quervant-core/Cargo.toml`,
`search/unified.rs`, `search/execute.rs`, `search/score.rs`, `search/mod.rs`,
`search/diagnostics.rs`; removed `tests/pr15i_c_physical.rs` (absent at base).

```
git diff --quiet 6f6463cb… HEAD -- crates/quervant-core/src crates/quervant-core/Cargo.toml \
  Cargo.lock .github/workflows/ci.yml benchmarks/pr15d benchmarks/pr15i_a benchmarks/pr15i_b
  -> empty
```

The four frozen protocols (`protocol.json`, `noise_protocol_v1/v2`,
`batched_protocol_v1.json`) are byte-identical to `START`; they are new relative
to `BASE_A` because earlier follow-ups added them.

## 3. Commit identities

| Role | SHA |
|---|---|
| `BASE_A` | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| `START` | `8541c8edcf70f84c89cbea6ea6dc4c711446ec84` |
| `RESTORED_B_SHA` | `b32523b9bb182190cb8260b00c3a81645314837f` |
| `CAUSAL_BC_SOURCE_SHA` | `658a2dde0e15c17e2b0c92278b5c922f5260fe60` |
| `CAUSAL_TOOLING_SHA` | `a426c6ae7225987cc09d9056a4d835483822235a` |
| Tooling fixups | `9f667c9`, `cf419dd`, `888b1ae`, `7334a9c`, `d996441`, `58780e4`, `45fe886e` |
| Rollback | this commit |

## 4. Final QA on the settled rollback tree

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` (stable + 1.85.0) | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (stable + MSRV) | PASS |
| `cargo test --workspace --all-targets` | PASS (135 test binaries) |
| `cargo test --workspace --all-targets --all-features` (stable + MSRV) | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — `TOTAL` lines **92.68%** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| Python `pr15d/harness`, `pr15i_b`, `pr15i_c` | PASS (139 / 10 / 309) |
| Python `pr15i_a` | 87 tests, 1F/3E `SOURCE_BOUND_HISTORICAL_ONLY` |
| `git diff --check` | CLEAN |

Real boundary: **`REAL_RUSTFS_BLOCKED`** — `docker` absent, `podman` present but
no verified access to the pinned `rustfs/rustfs@sha256:1803faef…` image, so the
real-service suites were not executed, no fake store was substituted, and no
compiled-but-ignored test is counted.

## 5. Preserved evidence

| Artefact | Location |
|---|---|
| Four valid campaigns (2 unbatched, 2 batched) | `target/pr15i-c/causal-campaigns-v1/causal-{unbatched,batched}-0{1,2}` |
| Per-campaign receipts | `target/pr15i-c/reviews/causal-{unbatched,batched}-0N-verification.json` |
| Aggregate receipt | `target/pr15i-c/reviews/causal-series-aggregate-verification.json` |
| Invalid pre-sampling attempts and stale series | `causal-*-attempt-0N`, `causal-unbatched-01-stale-series1/2` (each with an `INVALID.json`) |
| Tooling + protocol | `benchmarks/pr15i_c/{causal_protocol_v1.json,causal_run.py,verify_causal.py,causal_source_proof.py,test_causal_*,README-causal.md}` |
| All earlier negative evidence | untouched |

## 6. The bounded fact this study establishes

On the four absent/rare lanes, **disabling the specialized operator in the same
candidate binary does not remove the regression**: `C/A ≈ B/A` in all eight
lane × campaign cells (`B/C` medians 0.850–1.026), while on the common lanes the
specialization is exactly what produces the 0.78–0.90 speedup (`C/A ≈ 1.0`).
The regression therefore lives in the candidate build's non-operator path
(gate/dispatch/link layout), not in the operator's per-posting work — stated as a
measured association, not a proven compiler mechanism (`perf` unavailable).

## 7. Precise next experiment (not authorized here)

A future, separately approved plan should decide **one** of two bounded options,
both requiring no new algorithm:

1. Re-run this same three-arm design with a predeclared block-level tolerance that
   is achievable on ~50–250 µs lanes (e.g. more than two campaigns per regime, or
   a within-lane pooled estimator), so the non-operator hypothesis can be labelled
   decisively; or
2. If the non-operator cause is the target, measure the candidate's *generic-only*
   path against the merged baseline with machine-code instrumentation that exists
   in both builds (e.g. identical-flag assembly capture plus an instruction-count
   proxy), which this study could not do because `perf` is unavailable.

Either option must keep the frozen `C-P06..C-P09` gates unchanged; neither
authorizes shipping PR 15I-C.

# PR 15I-C batched-noise follow-up — execution status

## Disposition

**`15IC_PERFORMANCE_REJECTED_SAFE_ROLLBACK`**

Batched A/A stability passed (`15IC_BATCHED_AA_STABLE`) and the historical A/G
control was neutral, so the outside-generic dispatch candidate was implemented,
passed local correctness, and was measured once under the frozen unbatched
PR15I-C contract — which failed `C-P09`. Production was rolled back additively.

External statuses: `REAL_RUSTFS_BLOCKED`, `HOSTED_CI_PENDING`, `REVIEW_PENDING`,
`NOT_PUSHED`, `NOT_MERGED`.

## 1. Phase outcomes

| Phase | Status | Evidence |
|---|---|---|
| P0 preflight + invariant challenge | PASS | `batched-preflight.md`, `batched-invariant-traceability.md` |
| P1-A frozen batched tooling (protocol, patcher, controller, verifier, 92 tests) | PASS (`BATCH_TOOLING_SHA = 0a84c02`) | commits |
| P1-B eight batched campaigns (4 A/A + 4 A/G), fixed order, independently verified | COMPLETE, 8 receipts + aggregate | `target/pr15i-c/batched-noise-v1/`, `reviews/batched-v1-*` |
| P1-C prospective gates | A/A **PASS**; A/G `NEUTRAL` | aggregate receipt |
| P2 outside-generic dispatch implementation (`B_IMPLEMENTATION_SHA = 92a7418`) | PASS (source proofs) | `unified.rs`, `execute.rs`, `score.rs` cfg(test) |
| P3 correctness (40-row N-U matrix, 24 N-I, fault rows, 256-case differential, invalid-score precedence) | PASS | `n_tests` (16), `n_extra_tests` (12), `n_failure_tests` (2), `c15i_physical_tests` (6), `tests/pr15i_c_physical.rs` (12) |
| P4 frozen unbatched campaign `outside-dispatch-batched-01` | **VALID FAIL** (`C-P06/07/08 PASS`, `C-P09 FAIL`) | campaign + receipt |
| P5 additive rollback | PASS, protected diff empty | §2 |
| P6 reporting | this document set | — |

## 2. Rollback identity

Restored from merged `6f6463cb…`: `search/unified.rs`, `search/execute.rs`,
`search/score.rs`, `search/diagnostics.rs`, `search/mod.rs`,
`crates/quervant-core/Cargo.toml`; removed `tests/pr15i_c_physical.rs`.

```
git diff --quiet 6f6463cb… HEAD -- crates/quervant-core/src crates/quervant-core/Cargo.toml \
  Cargo.lock .github/workflows/ci.yml      -> empty
git diff --quiet 6f6463cb… HEAD -- benchmarks/pr15d benchmarks/pr15i_a benchmarks/pr15i_b \
  benchmarks/pr15i_c/protocol.json benchmarks/pr15i_c/noise_protocol_v1.json \
  benchmarks/pr15i_c/noise_protocol_v2.json -> empty
```

Retained as diagnostics: `benchmarks/pr15i_c/{batched_protocol_v1.json,
batched_adapter_patch.py,batched_noise.py,verify_batched_noise.py,test_batched_*}`,
all prior tooling and every sealed negative campaign.

## 3. Commit identities

| Role | SHA |
|---|---|
| `MERGED_15IB_A_SHA` | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| `BRANCH_START` | `60344aba822e93bb64fe16b95805d9478b7b0100` |
| `BATCH_TOOLING_SHA` | `0a84c023178ed43eb917d20317f2ea469fdd12ed` |
| Scope-allowlist tooling fixup | `9381c3eb0052878712eb0cb67758f8f05b5c70d7` |
| `B_IMPLEMENTATION_SHA` = `B_MEASURED_SHA` | `92a741876f6f6823d9d1792fc391dbb1bbecceb0` |
| Rollback / final production | this commit |

## 4. Final QA on the settled rollback tree

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` (stable and 1.85.0) | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (stable and MSRV) | PASS |
| `cargo test --workspace --all-targets` | PASS (135 test binaries) |
| `cargo test --workspace --all-targets --all-features` (stable and MSRV) | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — `TOTAL` lines **92.68%** |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `bash benchmarks/scripts/test-scripts.sh` | PASS (108) |
| Python `pr15d/harness`, `pr15i_b`, `pr15i_c` | PASS (139 / 10 / 245) |
| Python `pr15i_a` | 87 tests, 1F/3E `SOURCE_BOUND_HISTORICAL_ONLY` (reproduced at base) |
| `git diff --check` | CLEAN |

Real boundary: **`REAL_RUSTFS_BLOCKED`** — no `docker`/`podman`, so
`pr15i_c_rustfs` (not added), `pr15i_b_rustfs`, `pr13_remote`,
`pr13_remote_proxy` and the S3/proxy suites could not be executed. No fake store
was substituted and no compiled-but-ignored test is counted as run.

## 5. Preserved evidence

| Artefact | Location |
|---|---|
| 8 batched campaigns + 8 receipts + aggregate | `target/pr15i-c/batched-noise-v1/`, `target/pr15i-c/reviews/batched-v1-*` |
| Frozen final campaign + receipt | `target/pr15i-c/campaigns/outside-dispatch-batched-01`, `target/pr15i-c/reviews/outside-dispatch-batched-01-verification.json` |
| Earlier noise v2 / layout / paired-01 evidence | untouched |
| Batched tooling and tests | `benchmarks/pr15i_c/` |

## 6. Findings for any future plan (not authorization)

1. Per-request measurement of this specialization on ~50–250 µs lanes is
   dominated by a reproducible low-match regression (1.34–1.73×) that survives
   moving the dispatch out of `collect_mixed`. Three measurement regimes and three
   candidate layouts agree on the common-lane gain and the low-match loss.
2. Repeated-query batching removes that measurement variance: with 100-search
   batches the same-binary A/A noise is < 1.5 % and zero block outliers remain,
   but the batched regime cannot speak to per-request tail latency.
3. Any further attempt must therefore either (a) find an execution change that
   does not regress per-request low-match latency, or (b) obtain explicit human
   agreement on a different acceptance contract for the low-match lanes. Neither
   is authorized by this plan.

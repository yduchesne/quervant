# PR 14 — P4 final acceptance

> **Supersession note (2026-10-24, PR 14C):** this P4 acceptance remains
> historical provenance for the tested tree below. PR 14C did not re-run the
> qualified benchmark trials, so the `ab9b2d7` figures must not be cited as
> current-branch measurements. PR 14 remains **BLOCKED / NOT ACCEPTED**; see
> [../pr-14c/benchmark-report.md](../pr-14c/benchmark-report.md) and
> [../pr-14c/final-acceptance.md](../pr-14c/final-acceptance.md).

Tested code tree: `dev/pagination` at `0d005ab1d8a5b09d5cf0113227e1b6025b2a0216`
(clean). This artifact commit is documentation-only.

## Status
- **P4: ACCEPTED** on the tested tree (real RustFS verticals, faults, qualified
  W01–W07/W09 benchmarks, approved W08 v0.1 exception, Phase 4 local gates).
- **PR 14: NOT READY.** Final-SHA CI has not been observed and is a separate
  subsequent gate.

## Traceability
| Invariant | Evidence |
|---|---|
| V01/V02/V03/V06 | R01–R07, local oracle in `pr14_storage_vertical` |
| V04/V05 | R08–R11 remote batch/budget boundaries |
| V07/V08/V10 | F01–F10, 10 independent iterations each |
| V09 | R13/R14 warm/pinned cache; W08 approved exception |
| V11/V12 | B01–B04, three qualified trials, negative validator self-tests |
| V13 | no codec/manifest/format or distributed/vector changes in P4 |
| V14 | R15 cursor+aggregation STOP S2 fail-closed |

| Case set | Executed evidence |
|---|---|
| R01–R15 | `pr14_storage_vertical`: 9 real RustFS tests + 3 local oracle tests, all PASS |
| F01–F10 | `pr14_storage_faults`: 9 tests × 10 iterations, all PASS (F08 separate-process SIGKILL) |
| B01–B04 | `pr14_bench_remote`: 3 qualified trials `t1/t2/t3`; validator self-test and 3-trial PASS |
| W01–W07, W09 | measured, 3 warmups + 20 samples × 3 trials |
| W08 | **NOT APPLICABLE** — approved Option 2 v0.1 snapshot-lifetime pinning exception (`p4-w08-stop.md`, `benchmarks/reports/pr14-p4-w08-exemption.json`) |

## Real RustFS topology
Pinned `rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
rootless Podman, `http://127.0.0.1:9000`, test-only credentials from the
container environment (not committed/logged).

## Executed gates (tested tree `0d005ab`)
| Command | Result |
|---|---|
| `cargo fmt --all -- --check` (stable + 1.85.0) | PASS |
| `cargo clippy --workspace --all-targets --all-features -D warnings` (stable + 1.85.0) | PASS |
| `cargo test --workspace --all-targets --all-features` (stable + 1.85.0) | PASS |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **90.89% lines**, 86.93% functions |
| `cargo doc --workspace --all-features --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `pr14_storage_vertical` real RustFS | 9 PASS |
| `pr14_storage_faults` real RustFS | 9 PASS × 10 iterations |
| `pr13_s3_rustfs` / `pr13_remote` / `pr13_remote_proxy` / `pr13_proxy_rustfs` / `pr13_oracle` / `pr13_oracle_geo` / `pr13_crash_rustfs k0` | 8 / 3 / 7 / 5 / 1 / 1 / 5 PASS |
| `validate-pr14-p4.py --self-test` | PASS |
| `validate-pr14-p4.py --w08-exemption … t1 t2 t3` | PASS: 3 qualified trials |
| `git diff --check` / `git status --short` | clean |

## Benchmark provenance
Trials ran on benchmark source commit `ab9b2d7da066ec80190dcee70a8cebfd81481b80`;
later commits changed only documentation and the validator. Corpus digest
`80ef56151e6b1e4625fb2e5d9f03106a3fa9e292ffea77d4f4630f4a753f8768`;
all three trials `qualified=true`, `idle_confirmed=true`, `contention=clear`,
`dirty=false`. Details: `p4-benchmark-report.md`.

## Residual risks and exclusions
- W08 eviction/reload is not applicable for v0.1; multi-snapshot/cache-owner
  lifecycle support is a prospective enhancement, not a PR 14 requirement.
- No power-loss durability proof; process-crash recovery only.
- RustFS is the reference S3-compatible provider, not proof for all providers.
- p99 values are sample quantiles, not production SLOs; no cross-engine claim.
- Final-SHA CI is unobserved and remains the PR 14 blocker.

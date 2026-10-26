# PR 14E — validation report

**Status: `LOCAL GATES PASS — PR 14E CI PENDING — PR 14 NOT ACCEPTED`.**
PR 14E is documentation/evidence only: no Rust source, test, fixture,
benchmark, workflow, dependency or roadmap change was made.

| Item | Value |
|---|---|
| Tested branch | `docs/pr14e-acceptance-reconciliation` |
| Tested commit / working tree | `dc506f6ee28014e64fbc9070db6925b73063d9ba` plus uncommitted PR 14E documents at the time of each run; docs-only |
| Base (`origin/main`) | `dc506f6ee28014e64fbc9070db6925b73063d9ba` |
| Tree state during runs | clean tracked tree (documents added after the gate run; no tracked file modified before it) |
| Fresh real-RustFS run | **NO** — PR 14D's immutable provider evidence is cited (`REUSE-14D`), not re-executed |
| Fresh benchmark trial | **NO** — owned by PR 14F |

## 1. Environment

| Item | Value |
|---|---|
| Host | WSL2, `Linux 6.18.33.2-microsoft-standard-WSL2`, x86-64, 12 vCPU, 31 GiB RAM |
| Repository filesystem | ext4 (`/dev/sdd` → `/`), not `/mnt/c` |
| Stable toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| MSRV toolchain | `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Container runtime | `podman 4.9.3` (rootless) — **not used** (no provider started) |
| Python | 3.12.3 |
| GitHub CLI | `gh` token invalid; public read API reachable (HTTP 200) and used for check-run records |

## 2. Mandatory workspace gates

All commands run from the workspace root, sequentially, on the tested tree.
Log: `/tmp/pr14e/gates.log` (session-local; commands are reproducible as listed).

| # | Command | Result |
|---:|---|---|
| 1 | `cargo fmt --all -- --check` | **PASS** |
| 2 | `cargo +1.85.0 fmt --all -- --check` | **PASS** |
| 3 | `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** |
| 4 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| 5 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| 6 | `cargo test --workspace --all-targets` | **PASS** — 2044 passed, 0 failed, 10 ignored |
| 7 | `cargo test --workspace --all-targets --all-features` | **PASS** — 2048 passed, 0 failed, 73 ignored |
| 8 | `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS** — 2048 passed, 0 failed, 73 ignored |
| 9 | `cargo doc --workspace --all-features --no-deps` | **PASS** |
| 10 | `cargo bench --workspace --no-run` | **PASS** |
| 11 | `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 33 script tests passed, 0 failed |
| 12 | `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` | **PASS** — `PASS self-test` |
| 13 | `git diff --check` | **PASS** |
| 14 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** — 91.29 % lines |

The plan's optional `cargo clippy …` default-only and MSRV variants are covered by
rows 3–5. `cargo clippy --workspace --all-targets --all-features` on both
toolchains was run because CI runs them; the plan's minimal default-only MSRV
clippy is a subset.

**Ignored tests are not counted as executed.** Default runs ignore provider/child
entrypoints (10); all-features runs ignore the RustFS provider verticals, fault
matrix, benchmark lanes and child entrypoints (73). Those counts are reported
verbatim and no ignored case is claimed as a PR 14E execution.

## 3. Targeted PR 14 and legacy suites (executed individually)

`cargo test -p quervant-core --all-features --test <suite> -- --test-threads=1`

| Suite | Passed | Ignored | Failed |
|---|---:|---:|---:|
| `pr14a_public_cursor` | 26 | 0 | 0 |
| `pr14_json` | 13 | 0 | 0 |
| `pr14_typed_predicates` | 12 | 0 | 0 |
| `pr14_projection` | 10 | 0 | 0 |
| `pr14_unified_mixed` | 14 | 0 | 0 |
| `pr14_unified_cursor` | 11 | 0 | 0 |
| `pr14_batch` | 12 | 0 | 0 |
| `pr14_batch_memory` | 31 | 0 | 0 |
| `pr14_batch_governance` | 7 | 0 | 0 |
| `pr14_aggregation` | 5 | 0 | 0 |
| `pr14_compound_aggregation` | 24 | 0 | 0 |
| `pr14_f1_hardening` | 23 | 0 | 0 |
| `pr14d_json_sort_memory` | 13 | 0 | 0 |
| `pr11_json_corruption` | 8 | 1 | 0 |
| `pr11_json_paths` | 10 | 0 | 0 |
| `pr11_json_mutations` | 7 | 0 | 0 |
| `pr11_json_properties` | 4 | 0 | 0 |
| `pr14_storage_vertical` (local, non-ignored) | 5 | 14 | 0 |
| `pr13_remote` (non-ignored) | 5 | 3 | 0 |
| `pr14b_json_memory --nocapture` | 1 | 1 (child) | 0 |
| `--lib legacy_json_tests` | 2 | 0 | 0 |
| `--lib json_sort_winner_tests` | 3 | 0 | 0 |
| `--lib` (all unit tests) | 759 | 1 | 0 |

All 23 targeted runs passed. Log: `/tmp/pr14e/targeted.log`.

### 3.1 B20/B21 output at this head (verbatim)

```text
B20/B21 occurrences=1 logical_BatchMemoryBytes=387 tracked_peak_exact=33547 tracked_peak_one_under=33547 tracked_peak_cancelled=7397
B20/B21 occurrences=128 logical_BatchMemoryBytes=45726 tracked_peak_exact=110392 tracked_peak_one_under=110392 tracked_peak_cancelled=7397
B20/B21 occurrences=4096 logical_BatchMemoryBytes=1462302 tracked_peak_exact=2518968 tracked_peak_one_under=2518968 tracked_peak_cancelled=7397
```

These match `docs/pr-artifacts/pr-14d/resource-characterization.md` exactly
(`387 / 45,726 / 1,462,302`). They are allocator-window observations, **not** RSS
and **not** a physical memory cap.

## 4. Provider-required cases — explicitly NOT run in PR 14E

The following are `#[ignore]`d real-boundary suites in the all-features run. They
were **not** executed here (no provider started) and are cited from PR 14D:

| Suite | Ignored cases | Evidence used |
|---|---:|---|
| `pr14_storage_vertical` | 14 (incl. `real::{r01…r15, b02, b06_b07, b18, d11, d12}`, `p4_child_bootstrap`) | `REUSE-14D` — 13 real symbols PASS |
| `pr14_storage_faults` | 10 (F01–F09/F10 + child entrypoints) | `REUSE-14D` — 9 cases × 10 iterations |
| `pr14_bench_remote` | 1 | not executed (benchmark lane; PR 14F) |
| `pr13_remote` | 3 | `REUSE-14D` |
| `pr13_oracle` / `pr13_oracle_geo` | 1 / 1 | `REUSE-14D` |
| `pr13_remote_proxy` | 7 | `REUSE-14D` |
| `pr13_crash_rustfs` | 6 | `REUSE-14D` |
| `pr13_bench_remote` | 2 | not executed (benchmark lane) |
| `quervant-objectstore` `pr13_s3_rustfs` / `pr13_proxy_rustfs` | 8 / 5 | `REUSE-14D` |

Applicability bridge (verified, not assumed):
`git diff --stat 3f82284..dc506f6 -- crates/ Cargo.toml Cargo.lock benchmarks/ .github/`
is **empty** — the code tree on which PR 14D ran its provider qualification is
the code tree now on `main`. If a future change touches those paths, this bridge
lapses and the affected rows become `BLOCKED` pending a controlled re-run.

## 5. Coverage

```
TOTAL   76158   6213   91.84% regions | 4068   514   87.36% functions | 48236   4200   91.29% lines
```

Measured over all workspace production code with `--all-targets --all-features`
and the 85 % line floor; the command exited `PASS`. The value equals the PR 14D
figure because no code changed since `3f82284`; it is a fresh measurement, not a
copied one. No exclusion was added.

## 6. CI evidence (immutable records)

| SHA | Role | `rust` | `msrv` | `rustfs` | Run |
|---|---|---|---|---|---|
| `6cb6d47` | PR #61 head | success | success | success | `actions/runs/40122922869` |
| `a61f0b8` | PR #62 (PR 14C) head | success | success | success | `actions/runs/40135692802` |
| `4097a02` | PR #63 head | success | success | success | `actions/runs/40136120377` |
| `9f9371c` | PR #64 pre-fixup head | success | success | success | `actions/runs/40254674936` |
| `635c7f4` | PR #64 final head | success | success | success | `actions/runs/40326618997` |
| `6d18ebe` | PR #64 merge | success | success | success | `actions/runs/40361560578` |
| `dc506f6` | `main` head | success | success | success | `actions/runs/40361657335` |
| `e0e1dcb`, `d0e1bbb`, `ab9b2d7` | never-pushed local SHAs | — | — | — | `total_count: 0` |

**PR 14E head CI is PENDING** — the branch had not been pushed when these records
were read. No PR 14E CI result is claimed (decision X17).

## 7. Failure classification

| Class | Count | Detail |
|---|---:|---|
| Introduced regression | 0 | no production/test code changed |
| Existing deterministic failure | 0 | all executed suites green |
| Flaky / nondeterministic | 0 | none observed; nothing retried to green |
| Harness/environment failure | 0 | no gate was blocked by the environment |
| External dependency | 0 | no provider, network or container dependency in the executed matrix |
| **Not executed by design** | 1 class | real-RustFS provider suites and benchmark lanes (ignored; `REUSE-14D` / PR 14F) |

## 8. Gate-to-evidence map

| Plan §6 stage | Command/test | Where recorded |
|---|---|---|
| Stage D fmt/clippy/tests/docs/bench/scripts | §2 rows 1–13 | this report |
| Stage D targeted `pr14*` suites | §3 | this report, `test-traceability.md` E14E-13 |
| Stage D B20/B21 | §3.1 | `test-traceability.md` E14E-05 |
| Stage D coverage | §5 | `test-traceability.md` E14E-15 |
| Stage D ignored-provider classification | §4 | `test-traceability.md` E14E-19 |
| Stage C1 risk correction | source + CI + B20/B21 + drift check | `resource-risk-reconciliation.md` |
| Stage C2 zero-GET | existing counters/tests inspected, none at the PR 14 boundary | dossiers D-01/D-05/D-08 |
| Stage C3 hit identity | source inspected, no assertion | dossiers D-04/D-07 |
| Stage C4 legacy JSON | legacy/PR 11/14D tests executed | dossiers D-02/D-03 |
| Stage C5 U/G/R/X | repository + git history search | dossier D-16 |
| Stage C6 CI | §6 | dossiers D-06/D-15 |
| Stage C7 benchmarks | none run | `benchmark-dependency.md` |

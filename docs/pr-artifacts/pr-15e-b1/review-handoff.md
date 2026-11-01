# PR 15E-B1 — review handoff

**State: `PERF_BLOCKED` (safe work complete).** Implementation, correctness
evidence and the full mandatory QA matrix are complete on the final B1 commit.
Targeted wall-clock qualification is **not** available because no operator idle
confirmation was furnished, and this repository cannot be pushed / have a PR opened
from the executing environment (invalid GitHub token). No performance claim is made.

```text
B1_ACCEPTANCE = HOLD   (correctness/QA PASS; targeted performance unqualified)
```

## 1. Identity

| Item | Value |
|---|---|
| Base `main` | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` (PR #82 merge) |
| Branch | `dev/pr15e-b1-live-bitmap-postings-membership` |
| B1a commit | `601765fbc253cf9db3a2bfb5d594156eecb35f51` |
| B1b commit | `79218187390487eea0ced5e193147c15cd5a1e2a` |
| Docs/tooling commit | the commit that adds `benchmarks/pr15e_b1/` and `docs/pr-artifacts/pr-15e-b1/` (no Rust change) |
| PR | **not opened** — `gh` token in this environment is invalid; `origin` is `git@github.com:yduchesne/quervant.git` |
| G11 | `PENDING_REVIEW` in the PR 15E-A dossier (unchanged). Implementation proceeded under an **explicit maintainer waiver**, recorded in `decision-log.md` (D01/D02). This PR does **not** claim G11 PASS |

## 2. Files changed against `main`

| Path | Kind |
|---|---|
| `crates/quervant-core/src/search/execute.rs` | production (B1a + B1b) — the only production file |
| `crates/quervant-core/tests/pr15e_b1.rs` | new integration tests (U01–U05, U11–U14) |
| `crates/quervant-core/src/search/unified.rs` | tests only (`U::u06_*`) |
| `crates/quervant-core/src/segment/tests.rs` | tests only (decoder ordering invariant) |
| `benchmarks/pr15e_b1/{run_targeted.py,test_run_targeted.py,README.md}` | new, isolated tooling |
| `docs/pr-artifacts/pr-15e-b1/*.md` | new evidence |

Not touched: `benchmarks/pr15d/**`, `benchmarks/pr15e/**`,
`benchmarks/reports/**`, `docs/pr-artifacts/pr-15e-a/**`, `crates/*/src/search/{unified,work,score,projection,typed_compare}.rs`
(production bodies), `crates/quervant-core/src/segment/**` (production),
`crates/quervant-core/src/index/**`, objectstore, distributed, `Cargo.toml`,
`Cargo.lock`, `.github/**`. Verified: `git diff --name-only <base>..HEAD -- benchmarks/pr15d benchmarks/pr15e docs/pr-artifacts/pr-15e-a benchmarks/reports .github Cargo.toml Cargo.lock` → 0 files.

## 3. Mandatory QA — actual results (final working tree)

Toolchains: stable `cargo 1.98.1`, MSRV `cargo 1.85.0`. Every command's own exit code
was captured (no pipelines masking status except benign `grep` summaries of saved logs).

| # | Command | Result |
|---|---|---|
| 01 | `cargo fmt --all -- --check` | **PASS** (exit 0) |
| 02 | `cargo +1.85.0 fmt --all -- --check` | **PASS** (0) |
| 03 | `git diff --check` | **PASS** (0) |
| 04 | `python3 benchmarks/pr15d/harness/test_pr15d.py` | **PASS** (0) |
| 05 | `python3 -m unittest discover -s benchmarks/pr15e -p 'test_*.py' -v` | **PASS** (0) |
| 06 | `python3 -m unittest discover -s benchmarks/pr15e_b1 -p 'test_*.py' -v` | **PASS** (0) — 42 tests |
| 07 | `cargo clippy --workspace --all-targets -- -D warnings` | **PASS** (0) |
| 08 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** (0) |
| 09 | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | **PASS** (0) |
| 10 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** (0) |
| 11 | `cargo test --workspace --all-targets` | **PASS** (0) — 117 binaries, 2184 passed, 0 failed, 10 ignored |
| 12 | `cargo test --workspace --all-targets --all-features` | **PASS** (0) — 2188 passed, 0 failed, 75 ignored |
| 13 | `cargo +1.85.0 test --workspace --all-targets` | **PASS** (0) — 2184/0/10 |
| 14 | `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS** (0) — 2188/0/75 |
| 15 | `cargo test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --locked` | **PASS** (0) — 5 tests |
| 16 | `cargo +1.85.0 test --manifest-path …/quervant/Cargo.toml --locked` | **PASS** (0) — 5 tests |
| 17 | `cargo bench --workspace --no-run` | **PASS** (0) — compile only, no timing |
| 18 | `cargo doc --workspace --all-features --no-deps` | **PASS** (0) |
| 19 | `bash benchmarks/scripts/test-scripts.sh` | **PASS** (0) — 108/108 |
| 20 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** (0) — **lines 92.34%**, functions 87.95%, regions 91.83% (83354 lines, 6388 missed) |
| 21 | `PR15E_RUN_REAL_INTEGRATION=1 python3 -m unittest test_profile.RealAdapterIntegrationTest` (cwd `benchmarks/pr15e`) | **PASS** (0) — 1 test, recorded `source_sha=7921818…` |
| 22–26 | Real RustFS: `pr13_s3_rustfs`, `pr13_proxy_rustfs`, `pr13_remote`, `pr13_oracle`, `pr13_oracle_geo` (`--ignored --test-threads=1`) | **PASS** — 8 / 5 / 3 / 1 / 1 |
| 27–28 | Real RustFS: `m1_batches`, `m2_patches` | **PASS** — 1 / 1 |
| 29–31 | Real RustFS: `m3_delete_by_query` ×3 | **PASS** — 1 / 1 / 1 |
| 32–34 | Real RustFS: `m5_mutation_qualification` ×3 | **PASS** — 1 / 1 / 1 |
| 35–37 | Real RustFS: `pr13_remote_proxy`, `pr13_crash_rustfs k0`, `pr13_crash_rustfs k05` ×10 | **PASS** — 7, 5, 10×1 |

Logs are retained privately under `target/pr15e-b1-qa/` (gitignored, this checkout only).

Notes on the RustFS gate: Docker is absent in this environment, so the gate ran with
**podman** against the exact CI image digest
`rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
the exact CI env vars and the exact CI commands; the container was removed afterwards.
This is equivalent container content, not a byte-identical runtime. CI must still run
the authoritative `rustfs` job on the exact head.

Local `FsDirectory` integration is covered by `pr07_integration`,
`storage_fs_integration`, `storage_conformance`, `cache_async_integration`,
`pr06_local_integration` inside the workspace runs above.

## 4. Correctness evidence summary

* `U01–U15` and `I01–I08` mapping with named tests: `test-traceability.md`.
* RED proof for B1a on baseline `c3083d8`: `T::u11_u12_…` failed with
  `wide=48016, narrow=496` (i.e. the removed charge was exactly `48 × 1000`).
* B1b ordering invariant proved from `PostingsReader::next_with` plus a new
  decoder-level test that a zero doc-id delta is rejected.
* No assertion was weakened; no test was skipped, quarantined or re-scoped.

## 5. Performance status

`PERF_BLOCKED_OPERATOR`. See `qualification.md` for the pre-registered design, the
untimed dry-run evidence (adapter build, corpus verification, index build, metadata,
per-lane untimed oracle on all 6 `b1a` lanes) and the exact six commands needed to
complete `b1a`, `b1b` and `final`. No ratios, speeds or regressions are claimed.

## 6. Reviewer stop list

1. **G11 is not PASS.** It is waived for implementation by the maintainer; if the
   reviewer does not accept that waiver, this PR must not merge.
2. **Targeted performance is unqualified.** Do not merge claiming a B1 speedup; the
   comparison JSON/Markdown does not exist yet.
3. **Exact-head CI has not run** (no push/PR possible here). `rust`, `msrv` and
   `rustfs` must be green on the final SHA before merge.
4. **RustFS ran under podman locally**, not the CI Docker service.
5. `crates/quervant-core/src/segment/tests.rs` received a **test-only** addition
   outside the originally listed test files (disclosed in `decision-log.md`).
6. Behavioural (not just performance) consequence: some queries previously rejected
   solely by the transient live-set charge are now admitted. This is intentional and
   covered by tests; a reviewer who considers the old rejection semantics normative
   must reject this PR.
7. B2/B3/B4 remain unimplemented; nothing here authorizes postings-driven candidate
   enumeration, projection random access or column-cache reuse.

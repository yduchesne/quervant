# PR 14G — validation report

**Validated code state:** branch `test/pr14g-final-acceptance`, code head
**`d1ee42b`** (`B: test(pr14g): assert exact physical hit projection`) on top of
`e4d7237` (Phase A) and baseline `054ca55d143e89a092cc6519231b820fecfa42dc`.
The only later commits are **documentation-only** (`docs/pr-artifacts/pr-14g/`),
including the maintainer-decision transcription, which do not touch source, tests,
manifests or CI configuration. The decision-recording update therefore requires no
re-execution of the code gates above; only documentation/link/format checks apply
(`git diff --check`, crosswalk count assertion).

**Verdict:** every executable gate in the plan's §5 C2 matrix **PASS**. The two
human decisions are recorded from PR #70 comment `6458408816` (CW-041 = X-B,
CW-127 = bounded PR 14 acceptance). PR #70 now exists, so pushes trigger CI; the
`rust`/`msrv`/`rustfs` conclusions are bound to the exact PR head in §6 and
re-verified after the final evidence push. `CW-087`, independent review and
maintainer acceptance remain open, so PR 14 is **not** accepted.

## 1. Environment

| Item | Value |
|---|---|
| Host | Linux (WSL2), native ext4 repository filesystem (not `/mnt/c`/drvfs) |
| Stable toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| MSRV toolchain | `cargo +1.85.0` → `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Real provider | container `quervant-pr14f-rustfs`, image `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`, image ID `f6b22807f10db2aee80b8a9ed1e36bd12c2fba25ac2d98dc3b0332a23f1a5c4d`, health version `1.0.1`, endpoint `http://127.0.0.1:9000` |
| Real-provider env | `QUERVANT_RUSTFS_ENDPOINT`, `QUERVANT_RUSTFS_BUCKET=quervant-pr14g`, `QUERVANT_RUSTFS_ACCESS_KEY`/`SECRET_KEY` = disposable container harness values (not committed); `QUERVANT_RUSTFS_REGION` unset → `us-east-1` |

## 2. Mandatory command matrix (plan §5 C2)

All commands were executed from the repository root. Exit codes are the observed
process status codes.

| # | Command | Exit | Observed result |
|---:|---|---:|---|
| 1 | `cargo fmt --all -- --check` | 0 | no diff |
| 2 | `cargo +1.85.0 fmt --all -- --check` | 0 | no diff |
| 3 | `cargo clippy --workspace --all-targets -- -D warnings` | 0 | clean |
| 4 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | clean |
| 5 | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | 0 | clean |
| 6 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | clean |
| 7 | `cargo test --workspace --all-targets` | 0 | 110 suites, **2054 passed / 0 failed / 10 ignored** |
| 8 | `cargo test --workspace --all-targets --all-features` | 0 | 110 suites, **2058 passed / 0 failed / 74 ignored** |
| 9 | `cargo +1.85.0 test --workspace --all-targets` | 0 | **2054 passed / 0 failed / 10 ignored** |
| 10 | `cargo +1.85.0 test --workspace --all-targets --all-features` | 0 | **2058 passed / 0 failed / 74 ignored** |
| 11 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | **91.37 % lines** (workspace production code); regions 91.93 %, functions 87.41 % |
| 12 | `cargo doc --workspace --all-features --no-deps` | 0 | clean |
| 13 | `cargo bench --workspace --no-run` | 0 | all benches compile |
| 14 | `bash benchmarks/scripts/test-scripts.sh` | 0 | `script tests: 64 passed, 0 failed` |
| 15 | `git diff --check` | 0 | no whitespace errors |

The test-count deltas versus the PR 14F baseline (2,044 default / 2,048
all-features) are exactly the ten new PR 14G tests (5 integration + 5 in-crate),
which is the expected arithmetic consequence of this PR's diff.

## 3. Phase-specific gates

| # | Command | Exit | Observed result |
|---:|---|---:|---|
| 16 | `cargo test -p quervant-core --test pr14g_remote_zero_get` | 0 | 5 passed, 0 failed, 0 ignored |
| 17 | `cargo test -p quervant-core --all-features --test pr14g_remote_zero_get` | 0 | 5 passed, 0 failed, 1 ignored (real) |
| 18 | `cargo +1.85.0 test -p quervant-core --test pr14g_remote_zero_get` and `--all-features` | 0 / 0 | 5 passed each; 0 / 1 ignored |
| 19 | `QUERVANT_RUSTFS_* cargo test -p quervant-core --all-features --test pr14g_remote_zero_get -- --ignored --nocapture --test-threads=1` | 0 | 1 passed (`real::a02_real_rustfs_zero_get_after_warmup`) |
| 20 | same real command with `cargo +1.85.0` | 0 | 1 passed |
| 21 | `cargo test -p quervant-core --lib search::unified::tests` (stable + MSRV, default + all features) | 0 | 31 passed each time (26 pre-existing + 5 new) |
| 22 | `QUERVANT_RUSTFS_* cargo test -p quervant-core --all-features --test pr14_storage_vertical -- --ignored --test-threads=1` | 0 | 14 passed, 0 failed |
| 23 | `QUERVANT_RUSTFS_* cargo test -p quervant-core --all-features --test pr14_storage_faults -- --ignored --test-threads=1` | 0 | 10 passed, 0 failed |
| 24 | `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` | 0 | `PASS self-test` |
| 25 | PR #70 comment `6458408816` retrieval (`GET /repos/…/issues/70/comments`) | 0 | maintainer decision authorization returned (`author_association: OWNER`); transcribed verbatim into `maintainer-decisions.md` §0 |

Commands 22 and 23 re-exercise the merged PR 14 remote vertical and fault
suites against the **same pinned provider** at the PR 14G code head; they are
supporting regression evidence, not a substitute for the PR 14F qualified
benchmark campaign (which was **not** re-run, X25).

## 4. Counter evidence (see `phase-a-zero-get.md` for the full record)

| Boundary | Positive control | Warmed families |
|---|---|---|
| Fake `FakeObjectStore::get_calls` (all GETs) | `11 → 17` across three publisher commits → cold open + warmup | typed-only, mixed, serial batch, pinned page 1→2 all at `17` |
| Real `TransferStats::requests` (budgeted GETs, GET-only) | cold open `3`; `whole+range == 3` (one per immutable segment) | all four families remain at `3` |

## 5. Scope audit of the diff

| Check | Result |
|---|---|
| New files | `crates/quervant-core/tests/pr14g_remote_zero_get.rs`, `docs/pr-artifacts/pr-14g/*` |
| Modified production file | `crates/quervant-core/src/search/unified.rs` only inside the existing `#[cfg(test)] mod tests` (single hunk at line 2404+, `0` removed lines) |
| `SelectedHit`/`HitRef` visibility | unchanged |
| Persisted formats/codecs/manifests | unchanged |
| `Cargo.toml` / `Cargo.lock` | unchanged |
| `.github` workflows | unchanged |
| Historical 14C/14D/14E/14F artefacts | unchanged (`git diff --stat` shows no modifications) |
| Benchmarks / PR 14F source-lock corpus | unchanged |
| v0.1 release status | unchanged (not a release PR) |

## 6. GitHub CI binding (exact PR head)

| Item | Observed state |
|---|---|
| PR 14G | **PR #70** `test(pr14g): zero-GET and physical hit identity final acceptance`, base `main` `054ca55`, head branch `test/pr14g-final-acceptance`, created `2026-10-28T01:42:29Z` |
| `gh` CLI | `gh auth status` → token invalid (`HTTP 401`), so **writes** are unavailable; public read endpoints work and are the CI evidence source |
| `ci.yml` triggers | `pull_request` (and `push` to `main`); with PR #70 open, every push to the branch starts a run |
| Run at `cb59ab0` (docs head C3) | workflow run **40616645852** (`Rust CI`): `rustfs` `completed/success` id `122580579215`; `msrv` `completed/success` id `122580579059`; `rust` in progress at the time these documents were written |
| Final evidence head | after the decision-recording commit is pushed, `rust`, `msrv` and `rustfs` are re-observed on that **new exact head** and reported in the PR/final report; no earlier head is cited as the current binding |
| Baseline `main` `054ca55` | `rust` `122537968762`, `msrv` `122537968736`, `rustfs` `122537968815`, all `completed/success` |

Per X36/X44, a check that has not completed is reported as pending, never as a
pass. A failure at the exact PR head is a HARD STOP for acceptance, not something
the agent may reinterpret.

## 7. Required integration topology

- Local filesystem: `MemoryDirectory` + `FsDirectory` (workspace tests, PR 6/9/14
  suites) on native ext4.
- Deterministic object store: `FakeObjectStore` (capabilities:
  `IMMUTABLE_BASELINE.with_conditional_replace(true)`).
- Real pinned RustFS via the production S3 adapter (`--features s3`), one unique
  prefix per test, disposable reader/writer workspaces under `$TMPDIR`.

## 8. Unresolved failures

None in executable gates. The following are **not** failures and are not
converted into passes:

1. exact-head GitHub CI — verified only from the check-runs of the exact head;
   a run that is still executing is `PENDING`;
2. independent review — not performed;
3. CW-087 — dependent on 1, 2 and explicit maintainer PR 14/merge authorization.

CW-041 and CW-127 are no longer open: both are recorded from PR #70 comment
`6458408816` and reflected in the 127-row crosswalk (`112 PASS / 12 SUPERSEDED /
2 N/A / 1 BLOCKED`).

## 9. Exceptions

No coverage floor reduction, no test skip, no exclusion and no toolchain waiver
was used. The real-provider test is `#[ignore]`d **by design** and was executed
explicitly with the documented environment; the ignored status is not an
exception to execution.

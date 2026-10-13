# PR 5-R — Correctness matrix (QR-01…QR-12)

Evidence commands were run from the workspace root. Baseline `main` = `c735dac`; final
branch `dev/quervant-rename` (same content as the reviewed working tree). Status is
**PASS**, **BLOCKED** (external/human gate) or **NOT APPLICABLE**.

| QR | Invariant | Acceptance / oracle | Evidence | Status |
|---|---|---|---|---|
| QR-01 | Workspace members resolve under `crates/quervant-*` with exact new names | Q01, Q02 | `cargo +1.85.0 metadata --no-deps --format-version 1` → exactly `quervant-core`, `quervant-objectstore`, `quervant-distributed`; `cargo +1.85.0 check --workspace --all-targets` exit 0 | PASS |
| QR-02 | No active Rust source/test import or package dependency uses `trawler_*`/`trawler-*` | Q02, Q03 | `git grep -E 'trawler_core\|trawler_objectstore\|trawler_distributed\|trawler-(core\|objectstore\|distributed)' -- crates` → none; `Cargo.lock` local entries `quervant-*` only | PASS |
| QR-03 | No active user-facing text presents Trawler as the current name | Q10 | Postscan: active docs/scripts/CI contain no old branding; remaining matches are historical ADRs/PR artifacts, persisted markers, golden fixture comment, gated repo URL (inventory §4) | PASS |
| QR-04 | PR 5 segment/manifest wire bytes unchanged | Q04, Q05 | `sha256sum …/golden.seg` = `ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979` (identical to baseline); `segment_codec`, `segment_golden`, `segment_corrective*` suites pass | PASS |
| QR-05 | Persisted storage identities, commit/recovery rules and cache keys compatible | Q06, Q07 | `.trawler-tmp-` grammar and A5 recovery tests unchanged; `storage_fs_integration`, `storage_conformance`, `cache_async_integration`, `storage_cache_integration` pass; source diff audit shows only import/path edits in codec modules | PASS |
| QR-06 | `quervant-core`/`quervant-objectstore` Apache-2.0, `quervant-distributed` Elastic-2.0 | Q08 | `cargo metadata` licenses; `LICENSING.md` paths updated, SPDX/legal text unchanged; `LICENSES/*` untouched | PASS |
| QR-07 | No new dependency/unsafe/feature/API/architecture change | Q09 | `Cargo.lock` diff = 3 local packages only; no third-party version change; no `unsafe` introduced; public API shapes unchanged | PASS |
| QR-08 | Confirmed active configuration agrees across producer/consumer/docs/tests | Q11, Q12 | `QUERVANT_F02_DIR`, `QUERVANT_PRODUCTION_S3_ADAPTER`, `quervant-rustfs*` consistent in code, tests, `run.sh`, `compose.yaml`, `README.md` | PASS |
| QR-09 | Historical references/provenance not rewritten | Q13 | `docs/decisions/**` and `docs/pr-artifacts/pr-3|pr-4|pr-5/**` untouched; historical URLs in `ROADMAP_V01.md` retained; inventory table documents retention | PASS |
| QR-10 | GitHub repository metadata resolves to new URL after owner rename | Q14 | Owner renamed `yduchesne/trawler` → `yduchesne/quervant`. `git ls-remote https://github.com/yduchesne/quervant.git HEAD` → `3a82ad5…`; SSH `git@github.com:yduchesne/quervant.git` fetch succeeds; `Cargo.toml` `repository` updated to the new URL on `dev/quervant-url-metadata`. | PASS |
| QR-11 | CI and workspace coverage remain green (≥85 % production Rust line coverage) | Q15, Q16 | stable + 1.85 tests `771 passed / 0 failed / 2 ignored`; `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` → **85.25 % lines**, exit 0. Hosted CI on the final head: rename head `c0d4ec4` merged via GitHub PR #20; hosted `rust` check-run on merge `3a82ad5` = `completed/success`. | PASS |
| QR-12 | PR 6 can target `quervant-core` without a parallel old-name crate | Q02, Q17 | No `trawler-*` crate directory, alias, or manifest entry remains; `cargo doc --workspace --no-deps` resolves `quervant_core` docs | PASS |

## Q-gate execution summary

| Q | Check | Result |
|---|---|---|
| Q01 | `cargo +1.85.0 metadata --no-deps` | PASS — 3 renamed packages |
| Q02 | `cargo +1.85.0 check --workspace --all-targets` | PASS |
| Q03 | grep active crate refs in `crates` | PASS — none |
| Q04 | golden `sha256` | PASS — identical |
| Q05 | segment codec/golden/corrective suites | PASS |
| Q06 | memory/filesystem reopen/recovery | PASS |
| Q07 | crash-temp/cache recovery | PASS |
| Q08 | manifest + `LICENSING.md` license inspection | PASS |
| Q09 | rename-aware diff + lockfile audit | PASS — no behavior/dependency change |
| Q10 | postscan vs preflight inventory | PASS (documented retained exceptions) |
| Q11 | active env-var reference search | PASS |
| Q12 | RustFS harness default run | PASS — explicit SKIP, exit 0, no false PASS |
| Q13 | historical URL/text spot-check | PASS |
| Q14 | `git ls-remote` new repo identity | PASS — `quervant` resolves (`3a82ad5…`); SSH fetch works |
| Q15 | full workspace tests (both toolchains) | PASS — 771/0/2 each |
| Q16 | coverage ≥85 % | PASS — 85.25 % lines |
| Q17 | `cargo doc --workspace --no-deps` | PASS |
| Q18 | fmt/clippy (both) + `git diff --check` | PASS |
| Q19 | GitHub Actions on final head | PASS — rename head `c0d4ec4` merged via GitHub PR #20; hosted `rust` check-run on merge `3a82ad5` = `completed/success` |

## Pre-existing issues (not introduced by the rename)

- `docs/TESTING.md` lines 56–59 contain `<<<<<<< HEAD` conflict markers. Per §6.16 these are
  **not** resolved by this PR (would require unrelated semantic edits). Recorded as a baseline
  defect. They do not break any current docs gate because no docs-build/lint gate consumes them.
- The pre-existing `target/` filesystem corruption is an environment issue; a fresh target
  directory was used (see `validation-report.md`).

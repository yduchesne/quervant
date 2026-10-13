# PR 5-R — Validation report

**Baseline:** `main` @ `c735dac7fb9b4a9e496a64512212d22daa92d216` (clean worktree)
**Reviewed state:** branch `dev/quervant-rename`, working tree identical to the committed content
**Toolchains:** stable `rustc 1.99.0 (b940084d7 2026-09-28)`, MSRV `rustc 1.85.0`
**Environment:** Linux; `cargo-llvm-cov` present; filesystem note below.

## 1. Environment incident

The pre-existing `target/` directory was corrupt ("Structure needs cleaning", 95 % disk) and
could not be read or fully removed. This affected only gitignored build artifacts. It was renamed
aside and a fresh build performed; source integrity was confirmed with `git fsck --no-dangling`
(clean). All results below are from the fresh build.

## 2. Command results

| Check | Stable | MSRV 1.85 | Result |
|---|---|---|---|
| `cargo fmt --all -- --check` | exit 0 | exit 0 | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | exit 0 | exit 0 | PASS |
| `cargo test --workspace --all-targets` | 771 passed / 0 failed / 2 ignored | 771 passed / 0 failed / 2 ignored | PASS |
| `cargo doc --workspace --no-deps` | `quervant_core` docs generated | generated | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | — | **85.25 % lines**, exit 0 | PASS |
| `git diff --check` | — | — | PASS |
| `tests/rustfs/run.sh` (no production adapter) | explicit `SKIP`, exit 0 | — | PASS (no false conformance) |

### Baseline test counts

Baseline `main` produced the identical suite result on both toolchains: **771 passed / 0 failed /
2 ignored**. No pre-existing failures were present, so no failure could be misattributed to the
rename.

### Coverage detail (MSRV)

```
TOTAL   line 8157 covered 1203 missed  85.25%
        region 89.56%   function 92.58%
```

Threshold 85 % satisfied with margin. No exclusions were added; coverage spans all production
workspace crates.

## 3. Fixture digests (must be unchanged)

| File | SHA-256 | Note |
|---|---|---|
| `crates/quervant-core/tests/fixtures/segment/golden.seg` | `ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979` | Identical to baseline/plan |
| `crates/quervant-core/tests/fixtures/analysis/golden.tsv` | `8eef6e0c95af3ba60cb8b50b1cf956179a9b650bc72df5baf4c60060acd710af` | Unmodified (comment preserved) |
| `crates/quervant-core/src/analysis/data/public_suffix_list.dat` | `ba7d836c0ea57a8bcf9f1fcb868066a7554bed029b441ecc6204ad8494a32612` | Matches `PROVENANCE.md` |
| `crates/quervant-core/src/analysis/data/english_stopwords.txt` | `06b8b14bbe6f6e0b64c0830813819416d96a71bec1655668d83b3e602a651db6` | Matches `PROVENANCE.md` |

## 4. GitHub CI / provenance verification

Independent verification performed via the GitHub API against `yduchesne/trawler`:

- GitHub PR #16 (analyzer): `merged = true`, merge commit `9bc042d`; check-run `rust` = `completed/success`.
- GitHub PR #19 (segment codecs): `merged = true`, merge commit `c735dac`; check-run `rust` = `completed/success`.

`https://github.com/yduchesne/quervant.git` does **not** resolve yet, so `Cargo.toml` repository
metadata and historical URLs remain on the old name and Q14/QR-10 are **BLOCKED** pending the
owner-performed GitHub rename. Hosted CI for the rename head (Q19) cannot be attached until the
branch is pushed to the renamed repository.

## 5. Failure classification

| Item | Classification |
|---|---|
| Corrupt `target/` directory | Environment/harness (not source); mitigated by fresh target dir |
| `docs/TESTING.md` `<<<<<<< HEAD` markers | Deterministic pre-existing baseline defect; intentionally not fixed (§6.16) |
| Q14/QR-10 repository rename | External human gate; **BLOCKED**, not failed |
| All fmt/clippy/test/doc/coverage gates | Introduced regressions: none — all PASS |

## 6. Integration topology exercised

- Real `MemoryDirectory` and `FsDirectory` production paths (`storage_conformance`,
  `storage_fs_integration`, `storage_cache_integration`, `cache_async_integration`).
- Real segment builder → decoder golden path (`segment_codec`, `segment_golden`,
  `segment_corrective*`).
- Analyzer → contract → golden path (`analysis_contract`, `domain_analysis`, amendments 02–07).
- RustFS harness remains an explicit SKIP (production adapter is roadmap PR 13); no fake
  RustFS conformance was claimed.

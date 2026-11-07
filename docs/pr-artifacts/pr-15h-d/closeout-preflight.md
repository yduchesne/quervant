# PR 15H-D — closeout preflight (verified locally)

**Branch:** `dev/pr15h-a-linear-term-candidates`
**Verified D final HEAD:** `b05216ee83430d4e15373912aeaf0bd18bd27d97`
**`main`:** `ddcbe7789a2f06bfe13c3cac1c5b8eae1fafd078`
**Worktree:** clean at preflight.

## Ancestry verified

`C_CORRECTION d4b10c1` → `D_TOOLING c802f96` → `D_CANDIDATE 0f97779` →
`D_ROLLBACK 2ac85c7` → `D_FINAL b05216e`; all `merge-base --is-ancestor`
checks exit 0. `git diff --quiet c802f96 HEAD -- search/unified.rs
search/unified_plan.rs` exits 0: D production is byte-identical to A.

## Evidence re-verified read-only

| Campaign | Seal SHA-256 | `--verify-only` |
|---|---|---|
| `target/pr15h-d/baseline-01` | `72c8d17d5e0708435b46e3d50cde918da48403698cc15ceed3caf7a669a05eea` | PASS |
| `target/pr15h-d/paired-01` | `902d8432a74225ccaab5a876d5bb51a38a1b7d0cb5b26824f6bd7fac08fbdcc5` | PASS |

The D controller test suite executed **49 tests, all PASS**, from
`target/pr15h-d/tooling` (`c802f96`). D's A/B sources, corpus
`69052c66…`, host `4f971362…`, byte-identical index digests and 960/240/16/48
sample/probe/oracle counts match the sealed manifest.

## D disposition confirmed

`D_P1 +0.306132 ms`, `D_P2 +0.2981015 ms`, `D_P3 +0.8655125 ms` conventional
medians (from unrounded raw ns), all below the +2.000 ms primary gate; guards
pass. D-P01 FAIL. `PERFORMANCE_REJECTED_SAFE_ROLLBACK`.

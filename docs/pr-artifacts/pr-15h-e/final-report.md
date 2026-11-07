# PR 15H-E — final execution report

## Disposition

**`E_SIZE_REJECTED_SAFE_ROLLBACK`.**

The compact dictionary v2 implementation passed correctness and every latency
gate and cut Dictionary bytes by ~54%, but the frozen overall storage gates
failed: 100K segment ratio 0.9119 (E-P03 limit 0.90) and 100K committed-index
ratio 0.9392 (E-P04 limit 0.92). The production change was removed by exact
source rollback. No threshold was retuned.

## Source identity

| Item | Commit |
|---|---|
| D closeout (predecessor) | `7878caaeed8ee7a3b9dfef3191a1f57e0bd3ffcd` |
| E tooling / A baseline | `eb6ed9170308965987a35211d227431535a41ecb` |
| E candidate | `72b18e249f2a83b77fd2faaf05deb6f0d60eaad6` |
| E production rollback | `8d722ad0c0cff6b947fcdc762bb2ccaacdfcff0b` |
| Final code HEAD (retained fixture formatted) | `6fce44b2f393e68ae73090f3843a2c201f7dd3a1` |

`git diff --quiet eb6ed91 6fce44b -- crates/quervant-core/src` exits 0.
The candidate changed only the five authorized production files plus tests;
the rollback restored all production source and touched tests byte-for-byte.

## Correctness

- v2 codec matrix: 5/5 unit tests.
- v2 feature/payload and producer matrix: 3/3 integration tests.
- Frozen v1 golden: 2 passed, 1 ignored; no fixture edited.
- Full workspace stable and MSRV: 2,339 passed / 0 failed / 12 ignored
  (`--all-targets`); 2,343 passed / 0 failed / 81 ignored (`--all-features`).
- Real pinned RustFS on candidate: `pr13_remote` 3, `pr15g_{a,b,c,d}_rustfs`
  1 each, `pr13_crash_rustfs` 6, `pr13_s3_rustfs` 8 — all passed, exercising v2
  cold bootstrap and the production adapter. See `correctness.md` for the
  disclosed v1-object remote gap.
- One test-expectation update: compaction no longer asserts a fixed physical
  doc order because content-addressed segment ids legitimately change with v2;
  surviving keys and stored/column values are asserted instead.

## Storage

| Corpus | Dictionary E/A | Segment E/A | Committed index E/A |
|---|---:|---:|---:|
| 10K | 0.4553 | 0.9104 | 0.9383 |
| 100K | 0.4623 | **0.9119 FAIL** | **0.9392 FAIL** |
| low-vocab | — | 0.9999 | — |

Sealed campaigns: `baseline-01` seal `6b3851b4…`; `paired-01` seal `2ed0ca61…`.
See `storage.md`.

## Latency

All warm lanes passed E-P08/E-P09 (worst block 1.1139; worst median 1.0192).
Cold-open conventional median 0.9500 (E-P10 pass); build+commit conventional
median 0.9862 (E-P11 pass). E-P12 provenance/idle/seal/drift passed. See
`latency.md`.

## QA commands

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` (stable and 1.85.0) | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` (stable and 1.85.0) | PASS |
| `cargo test --workspace --all-targets` (stable and 1.85.0) | PASS — 2,339 |
| `cargo test --workspace --all-targets --all-features` (stable and 1.85.0) | PASS — 2,343 |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **92.75%** lines |
| `cargo doc --workspace --no-deps` | PASS |
| `git diff --check` | PASS |

Logs are under `target/pr15h-e/qa/`.

## Sealed evidence

- `target/pr15h-e/campaigns/baseline-01/` (v1 baseline, sealed).
- `target/pr15h-e/campaigns/paired-01/` (16 warm slots, cold/build, sizes,
  sealed). Neither campaign was edited after sealing.

## Outstanding CI

Hosted CI is **`CI_PENDING / BLOCKED`**. The user waived the D hosted-CI
prerequisite for local E execution; no CI was created, authenticated, pushed or
claimed green. No PR/merge was performed.

## Rollback

Production rollback is `8d722ad`. Tooling (`benchmarks/pr15h_e/`), helper tests,
sealed evidence and these documents are retained. See `rollback.md` /
`decision.md`.

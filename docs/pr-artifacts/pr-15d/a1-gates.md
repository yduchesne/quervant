# PR 15D A1 gates

**Status:** local build/oracle gates pass for Quervant and Tantivy; Lucene
execution is **BLOCKED-ENVIRONMENT** (no JDK 21); the isolated CI job was added
but has not run. No performance qualification was executed.

Source: `main` `28dc6c2cf95ee24d2b48a580a7cb2a7a8f7dcc6e`;
A1 branch `dev/pr15d-comparative-qualification`, starting from
`d0c9a3a4f655d874b2825a502f98eb2d553928b1`.

## 1. Gate results

| # | Command | Result |
|---|---|---|
| 1 | `python3 benchmarks/pr15d/corpus/generate.py --out target/pr15d/a1-corpus` | **PASS** — TSV/manifest digests match frozen values |
| 2 | `python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15d/a1-corpus` | **PASS** — 10K/100K rows verified |
| 3 | `python3 benchmarks/pr15d/harness/test_pr15d.py` (with both adapter binaries) | **PASS** — 31 tests, 0 failures, 0 skips |
| 4 | `cargo build --release --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml` | **PASS** |
| 5 | `cargo build --release --locked --manifest-path benchmarks/pr15d/adapters/tantivy/Cargo.toml` | **PASS** |
| 6 | `cargo +1.85.0 check --locked --manifest-path benchmarks/pr15d/adapters/tantivy/Cargo.toml` | **PASS** |
| 7 | `(cd benchmarks/pr15d/adapters/lucene && ./gradlew --no-daemon classes installDist)` | **BLOCKED-ENVIRONMENT** — exit 1: `JAVA_HOME is not set and no 'java' command could be found in your PATH` |
| 8 | `python3 benchmarks/pr15d/harness/smoke.py … --lucene-command /nonexistent/...` | **PASS (fail-closed)** — exit 2, `command_missing`, no synthetic success |
| 9 | Three-adapter `smoke.py` against real Lucene | **BLOCKED-ENVIRONMENT** — no JDK, no built Lucene distribution |
| 10 | `bash benchmarks/scripts/test-scripts.sh` | **PASS** — 108 passed, 0 failed |
| 11 | `cargo fmt --all -- --check` | **PASS** |
| 12 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| 13 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | **PASS** |
| 14 | `cargo test --workspace --all-targets --all-features` | **PASS** — 2173 passed, 0 failed, 75 ignored |
| 15 | `cargo +1.85.0 test --workspace --all-targets --all-features` | **PASS** — 2173 passed, 0 failed, 75 ignored |
| 16 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **PASS** — 91.81% lines (92.31% regions, 87.90% functions) |
| 17 | `cargo doc --workspace --all-features --no-deps` | **PASS** |
| 18 | `cargo bench --workspace --no-run` | **PASS** |
| 19 | `git diff --check` | **PASS** |
| 20 | Adapter `cargo fmt` / `cargo clippy --locked --all-targets -- -D warnings` (Quervant, Tantivy) | **PASS** |

Ignored tests are the pre-existing real-RustFS suites; they were not simulated.

## 2. Adapter oracle evidence (non-qualified sanity only)

Each adapter parsed the shared TSV, built a **persistent on-disk** index,
committed, reopened and answered all 8 mandatory predicates (4 classes × K=10,
100) exactly. The independent `oracle.py` was the only expectation source.

| Engine | N | Indexed | Reopened | index_bytes | segments | 8 predicates |
|---|---:|---:|---:|---:|---:|---|
| Quervant | 16 | 16 | 16 | 7,193 | 1 | PASS |
| Quervant | 10,000 | 10,000 | 10,000 | 3,090,037 | 1 | PASS |
| Quervant | 100,000 | 100,000 | 100,000 | 30,965,025 | 1 | PASS |
| Tantivy | 16 | 16 | 16 | 8,239 | 4 | PASS |
| Tantivy | 10,000 | 10,000 | 10,000 | 300,469 | 4 | PASS |
| Tantivy | 100,000 | 100,000 | 100,000 | 2,961,148 | 4 | PASS |

The counts are `index_bytes` as summed from regular files on disk; segment counts
are the engines' actual physical counts and are not normalized. The differing
segment topology and index size are reported, not judged.

Exact hit counts validated: `absent=0`, `rare=1`, `medium=N/8`,
`common=N/2 − 1`, with lexically ascending `doc_id` tuples identical to the
oracle for every predicate.

> These are correctness/scale checks. They are **not** 20-sample timing
> distributions, not qualified trials, and carry no performance claim.

### A1 correction required by the 100K lane

The Quervant adapter initially used `Index::create`/`open_existing` defaults,
whose `max_pending_docs = 10_000` rejected document 10,001. The adapter now
passes an explicit **bounded benchmark resource policy**
(`IndexLimits::new().with_max_pending_docs(1_000_000)`, 512 MiB pending/replay
bytes) to `Index::create_with_limits`/`Index::open_with_limits`. No query,
analyzer, ordering or scoring semantics changed; this is operational limit
configuration required by the frozen 100K corpus. It is called out for reviewer
confirmation because A1 otherwise froze Quervant adapter semantics.

## 3. Frozen-source verification

```text
git diff --quiet 28dc6c2… -- crates Cargo.toml Cargo.lock \
  benchmarks/datasets benchmarks/workloads \
  benchmarks/reports/pr15b-v1-e8ca1b0-qualified.json \
  benchmarks/reports/pr15c-b docs/pr-artifacts/pr-15b docs/pr-artifacts/pr-15c
exit = 0
```

`benchmarks/pr15d/spec/` and `benchmarks/pr15d/protocol/schema.json` are
unmodified from the prior committed state. No production source, root Cargo
file, published 15B/15C report or frozen workload changed.

## 4. CI

`.github/workflows/ci.yml` gained exactly one appended job, `pr15d-adapters`:

1. checkout;
2. `sha256sum -c A1-CHECKSUMS.sha256` plus properties pin checks **before any
   Java invocation**;
3. `actions/setup-java@v4` with Temurin 21;
4. `dtolnay/rust-toolchain@master` with 1.98.1;
5. locked Quervant + Tantivy release builds;
6. verified `./gradlew --no-daemon classes installDist`;
7. frozen corpus generation;
8. `harness/smoke.py` three-adapter exact-hit check with no timing, no
   `--idle-confirmed` and no performance output.

The existing `rust`, `msrv` and `rustfs` jobs are byte-identical. The new job
has **not** executed locally (no push/PR credentials, X49). Therefore A1 is
**not** yet “CI green” and PR 15D is not done.

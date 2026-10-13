# PR 5 preflight — versioned immutable segment codecs and typed columnar values

> **Status:** PREFLIGHT COMPLETE — **production codec BLOCKED at the F01–F12 human
> format-decision gate.** This report records verified facts only. It does not
> approve a format, authorize production codec code, or mark PR 5 DONE.

**Execution date:** 2026-10-12 (local development host).
**Inspected by:** coding agent under `TRAWLER_PR05_DETAILED_IMPLEMENTATION_PLAN.md`.
**Repository:** `yduchesne/trawler`.
**Working branch:** `dev/segment-codecs` (clean, byte-identical to `main` at the
recorded SHA; no PR 5 implementation existed before this task).

## 1. Fresh baseline identity

| Fact | Value |
|---|---|
| `main` / `HEAD` SHA | `a23cf25798e52fc181e93ac84505a07412f37463` |
| `HEAD` subject | `Merge pull request #17 from yduchesne/docs/pr-plan-correctness-gates` |
| `HEAD` commit date | 2026-10-12 16:19:55 -0700 |
| Working tree | clean (`git status --porcelain` empty) |
| Branch shape | `dev/segment-codecs == main` (no commits, no diff) |
| `origin/main` SHA | `a23cf25798e52fc181e93ac84505a07412f37463` (matches local) |
| Tags | none |

## 2. PR 4 ancestry reconciliation

The roadmap register still labels PR 4 `PLANNED`, but merged code and ancestry
show it is **merged**:

| Check | Evidence |
|---|---|
| PR 4 merge commit | `9bc042d` — `Merge pull request #16 from yduchesne/dev/analyzer-contract` |
| Ancestor of `HEAD`? | `git merge-base --is-ancestor 9bc042d HEAD` → **yes** |
| Branch contains merge? | `main`, `dev/segment-codecs`, `origin/main` |
| Analyzer implementation present | `crates/trawler-core/src/analysis/` (13 modules, real pinned pipelines, fingerprints) |
| PR 4 decision record | `docs/decisions/PR04_ANALYZER_PARAMETER_DECISIONS.md`, `docs/decisions/PR04_ANALYZER_PARAMETER_APPROVAL_AMENDMENT.md` |
| PR 4 implementation report | `docs/pr-artifacts/pr-4/implementation-report.md` (amendment 07 recorded) |

**Classification:** PR 4 = **DONE + MERGED** on the inspected baseline. The
roadmap register text is stale; this is a documentation-status lag, not missing
implementation. PR 5 dependencies PR 2/3/4 are all present on `main`.

## 3. Existing abstractions PR 5 must reuse (do not duplicate)

| Area | Verified paths / types |
|---|---|
| Typed contract | `contract::{schema,document,value,budget,capability,error}`; `Schema`, `FieldDefinition`, `FieldOptions`, `FieldType`, `Cardinality`, `Document`, `DocumentKey`, `FieldValues`, `FieldValue`, `Timestamp`, `GeoPoint`, `IpNetwork`, `JsonValue`, `Capabilities` |
| Analysis | `analysis::{analyzer,registry,term,limits,token}`; `Token` (UTF-8 term, `value_index`, absolute `position`, `position_increment`, `position_length`, source `start/end_offset`), `AnalyzerFingerprint([u8;32])`, `AnalyzerRegistry::resolve_fingerprint`, `AnalysisLimits` hard ceilings |
| Local storage | `storage::Directory` (`create`, `open_read`, `exists`, `delete`, `atomic_write`, `sync`, `list`, `file_len`), owned `ReadHandle::read_at`, `WriteHandle::write_all/sync_all`, `MemoryDirectory`, `FsDirectory`, `StorageKey` |
| Segment seam | `storage::{SegmentId, SegmentDescriptor, SegmentStore, StaticSegmentStore}` — logical id → one remote object key + `ContentDescriptor` |
| Cache | `storage::SegmentCache` (bounded, verified, pin/LRU, no remote deletion) |
| Explicit non-scope statement | `storage/mod.rs`: "does **not** define a segment codec, manifest, CURRENT pointer, writer, reader, or query executor" |

There is **no** `crates/trawler-core/src/segment/` directory. PR 5 is
**NOT STARTED**.

## 4. Toolchain and dependency evidence

| Fact | Value |
|---|---|
| `rust-toolchain.toml` | `channel = "stable"`, components `rustfmt`, `clippy` |
| Pinned MSRV (workspace) | `rust-version = "1.85"`, edition 2024 |
| `rustc +1.85.0 --version` | `rustc 1.85.0 (4d91de4e4 2025-02-17)` — installed and usable |
| `cargo +1.85.0 --version` | `cargo 1.85.0 (d73d2caf9 2024-12-31)` |
| Default `stable` | `rustc 1.99.0` (present alongside the pinned MSRV) |
| Audited SHA-256 | `sha2 = 0.11.0` (RustCrypto; already a `trawler-core` and `trawler-objectstore` dependency) |
| Other pinned deps | `unicode-normalization 0.1.25`, `icu_casemap =2.0.1`, `rust-stemmers =1.2.0`, `idna 1.1.0`, `publicsuffix 2.3.0`, `unicode-security 0.1.2`, `regex-syntax 0.8.11` |

No new dependency is required by this preflight. Any PR 5 codec dependency must
remain Rust 1.85-compatible and approved.

## 5. Pre-existing baseline defect observed (not introduced here)

`docs/TESTING.md` contains **four literal nested Git conflict markers**
(`<<<<<<< HEAD` at lines 56–59) and no matching `=======`/`>>>>>>>`. The section
that follows is otherwise complete. This is a **pre-existing documentation
defect on `main`**, not a code or test failure. It does not affect compilation,
tests, or coverage. Disposition: reported for a separate docs fix; out of PR 5
scope. (No other conflict markers were found in tracked files.)

## 6. Baseline QA evidence (pre-change, on `a23cf25`)

Environment: local host, `cargo +1.85.0` (MSRV) unless noted; commands run from
the workspace root.

| Gate | Exact command | Result |
|---|---|---|
| Check | `cargo +1.85.0 check --workspace --all-targets` | **PASS** (exit 0) |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | **PASS** — **639 passed, 0 failed, 1 ignored** |
| Format | `cargo +1.85.0 fmt --all -- --check` | **PASS** (exit 0) |
| Clippy | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | **PASS** (exit 0) |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | **PASS** (exit 0) |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | **PASS** — workspace **87.74% line**, 91.19% function, 94.63% region |

The single ignored test is the pre-existing RustFS/S3 harness SKIP in
`crates/trawler-objectstore/tests/objectstore_conformance.rs` or equivalent;
per `docs/TESTING.md`, a SKIP is not a pass, and the real S3 adapter remains
PR 13.

### Coverage per-crate line result (production code)

Lowest-covered production modules on baseline: `storage/fs.rs` 75.79%,
`storage/error.rs` 77.78%, `analysis/registry.rs` 83.78%, `storage/a3_io.rs`
83.24%, `storage/cache.rs` 86.00%. Workspace aggregate clears the 85% floor.

## 7. Scope classification against the plan

| Plan item | Classification on inspected baseline |
|---|---|
| F01–F12 concrete byte-level format | **BLOCKED** — no human-approved concrete decision record exists; only in-principle direction (`PR04_PR05_DESIGN_GATE_APPROVAL.md`) |
| `segment` module + codecs | **NOT STARTED** |
| Manifest codec (no publication) | **NOT STARTED** |
| Real `Directory` write/read/reopen for components | **NOT STARTED** (Directory primitives exist and are verified) |
| Golden fixtures | **NOT STARTED** for segments (analysis golden exists) |
| Workspace coverage floor | **PASS** on baseline |
| PR 6 writer/commit/refresh/PIT | **NOT APPLICABLE** — explicit PR 6 scope |
| RustFS remote acceptance | **NOT APPLICABLE** — PR 13 |
| Vector/hybrid | **NOT APPLICABLE** — post-v0.2 |

## 8. Gate decision (recorded)

Per `TRAWLER_PR05_DETAILED_IMPLEMENTATION_PLAN.md` §2 and §8, and
`PR04_PR05_DESIGN_GATE_APPROVAL.md` ("STOP if a coding agent is asked to decide
any of the unresolved architecture or format choices"):

- The agent has **authored** the concrete F01–F12 proposal in
  `docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md` and the review in
  `docs/pr-artifacts/pr-5/format-decision-review.md`.
- The agent has **not** written production codec code, has chosen no format
  unilaterally, and has not modified any protected contract/storage/analysis
  path.
- **STOP**: implementation is blocked until a human approves the F01–F12
  decisions and records the approved commit SHA.

## 9. Preflight command log

```text
git rev-parse HEAD                       -> a23cf25798e52fc181e93ac84505a07412f37463
git merge-base --is-ancestor 9bc042d HEAD -> yes (PR 4 merged)
git status --porcelain                   -> (empty)
rustc +1.85.0 --version                  -> 1.85.0 (4d91de4e4 2025-02-17)
cargo +1.85.0 check --workspace --all-targets          -> exit 0
cargo +1.85.0 test  --workspace --all-targets          -> exit 0 (639/0/1)
cargo +1.85.0 fmt   --all -- --check                   -> exit 0
cargo +1.85.0 clippy --workspace --all-targets -- -D warnings -> exit 0
cargo +1.85.0 doc   --workspace --no-deps              -> exit 0
cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85 -> exit 0 (87.74% lines)
```

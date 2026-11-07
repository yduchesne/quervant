# PR 15I-0 — final execution report

**Repository:** `yduchesne/quervant`
**Branch:** `dev/pr15i-0-qualified-baseline`
**Document class:** measurement, audit and documentation. **No production code,
format or query executor was changed.**

## Status block

```text
DOCUMENTATION_IMPLEMENTED
MEASUREMENT_QUALIFIED
TESTS_PASSED
HOSTED_CI_PENDING
REVIEW_PENDING
NOT_MERGED
```

These labels are independent. `MEASUREMENT_QUALIFIED` describes the local,
source-locked, sealed campaign verified on this branch. It says nothing about
hosted CI, independent review or merge, none of which happened here.

## 1. Branch, ancestry and commit identity

| Item | Value |
|---|---|
| Accepted base (`BASE`) | `19cc5207009abdc1496473443d850487f7739e92` |
| Tooling source (`15I0_TOOLING_SHA`) | `48e7d3a0771f9ccd1cc0bf1d07eadac4b2b5f39f` |
| Preflight/traceability commit | `4d81ba0` |
| Report + design-contract commit | `c3cac26` |
| Verifier corrections (measurement-only) | `1c58f87`, `2ba76d4`, `00f9501` |
| Reports bound to final verification | `6eec4fb` |
| Working tree at report time | clean |
| Push / PR / merge | **not performed**; no force-push, no merge, no self-approval |

`BASE` is the post-15H-E merge (`19cc520`, PR #87). `git diff --stat eb6ed91 BASE
-- crates/quervant-core/src` is empty, so production `src` is byte-identical to
the pre-E baseline; the only later `crates/` difference is rustfmt on the retained
15H-E control fixture (a test file). The 15H-E disposition remains
`E_SIZE_REJECTED_SAFE_ROLLBACK`; the dictionary-v2 candidate
(`72b18e2`) is **not** the baseline and was not measured.

Later commits on this branch touch only `benchmarks/pr15i_0/**`,
`benchmarks/reports/pr15i-0/**` and `docs/pr-artifacts/pr-15i-0/**`. Gate
`I0-P00` proves the protected paths are still byte-identical to the measured
source.

## 2. Preflight and source reconciliation

- `main` = `origin/main` = `BASE`; no reset, rebase or destructive operation.
- All assumed 15H-E SHAs are reachable ancestors of `BASE`:
  `8d7a17f` (docs closeout), `eb6ed91` (tooling/A), `72b18e2` (candidate,
  reverted), `8d722ad` (rollback), `6fce44b` (final code HEAD).
- Required 15H-E records exist: `final-report.md`, `rollback.md`, `decision.md`,
  `storage.md`, `latency.md`, `correctness.md`.
- Format facts verified in source, not assumed: dictionary payload v1, STORED v1,
  mutation-state payload v1/v2, container features `0x0001`–`0x000B` in use
  (`0x000C` free).
- Full detail: [`preflight.md`](preflight.md),
  [`invariant-traceability.md`](invariant-traceability.md).

## 3. Frozen inputs and identity

| Item | Value |
|---|---|
| Measured source | `48e7d3a0771f9ccd1cc0bf1d07eadac4b2b5f39f` |
| Measurement contract | `pr15i-0-measurement-contract-v1` |
| Contract SHA-256 | `af828096ca3d4581a8cda50b9401b3d23df92311487acaa79966a8a0e2e0e6f8` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Corpus files | `5cdc9341…` (10K), `6ea867fe…` (100K) |
| Host filesystem | `ext4`, native (accepted by PR 15D's own gate) |
| Host kernel class | WSL2 (`*-microsoft-standard-WSL2`) — disclosed, never OS-cache-cold |
| Sealed campaigns | `pr15d-current-01` (2037 files), `pr15i0-prepared-48e7d3a0-01` (645), `pr15i0-run-48e7d3a0-04` (743), `mutation-01` (3) — all `QUALIFIED` |

Seal schema `pr15i-0-seal-v1`; every listed file was rehashed by the verifier and
matched. Raw evidence, `perf.data`, heaptrack output, QA logs and absolute paths
stay under the ignored `target/` tree.

## 4. Three-engine campaign (PR 15D, unmodified harness)

3 trials × 3 engines; 32 lanes per trial (16 warm, 16 process-cold); every lane
matched the independent PR 15D oracle; all 54 contention probes `clear`;
`validate.py` → `QUALIFIED` with 0 errors.

Index bytes (median of three trials):

| Documents | Quervant | Tantivy | Lucene | Q/T | Q/L |
|---:|---:|---:|---:|---:|---:|
| 10,000 | 3,090,037 | 296,787 | 186,052 | 10.412 | 16.608 |
| 100,000 | 30,965,025 | 2,901,172 | 1,858,642 | 10.673 | 16.660 |

Warm medians (ns) — full table incl. process-cold in
[`measurements.md`](measurements.md):

| Lane | Quervant | Tantivy | Lucene | Q/T |
|---|---:|---:|---:|---:|
| 10K absent K100 | 43,400 | 11,100 | 299,105 | 3.910 |
| 10K rare K100 | 48,900 | 13,801 | 675,411 | 3.543 |
| 10K medium K100 | 1,958,830 | 90,802 | 4,482,970 | 21.573 |
| 10K common K100 | 4,545,572 | 133,102 | 3,002,847 | 34.151 |
| 100K absent K100 | 251,305 | 15,500 | 329,405 | 16.213 |
| 100K rare K100 | 254,804 | 18,600 | 665,310 | 13.699 |
| 100K medium K100 | 19,021,490 | 239,504 | 4,891,975 | 79.420 |
| 100K common K100 | 47,918,853 | 662,910 | 3,043,451 | 72.286 |
| 100K common K10 | 35,689,628 | 647,911 | 1,579,425 | 55.084 |

Reopen medians: Quervant 41,745,650 / 418,244,572 ns; Tantivy 423,206 / 466,008 ns;
Lucene 30,503,567 / 26,862,690 ns (10K / 100K).
Reopen ratio Q/T: **98.641×** (10K), **897.505×** (100K).

**Comparability caveat (disclosed next to every ratio):** Quervant sorts on a
`Keyword` column, Tantivy on a numeric ordinal and Lucene on `SortedDocValues`.
The ordering is logically equivalent; the physical representation is not. The
lane is exact match + exact count + explicit ascending `doc_id` sort. **No BM25
score comparability is claimed.**

## 5. Quervant profile (PR 15F, unmodified harness)

Nine warm CPU lanes captured, five warmups each, 76,000–242,000 samples,
**zero lost samples**, `clear` contention before and after. `perf` resolved
through PR 15F's documented `versioned` fallback (`perf version 6.8.12`).

Exclusive (self) share includes the unclassified bucket; inclusive shares overlap
and are never summed.

| Lane | Samples | Unknown (G08) excl. % | G01 | G02 | G03 | G05 | G06A | G06B | G06C | Rank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10K absent K100 | 76,000 | 53.91 | 23.99 | 22.10 | 0 | 0 | 0 | 0 | 0 | `UNRESOLVED` |
| 10K rare K100 | 76,000 | 59.92 | 21.75 | 18.33 | 0 | 0 | 0 | 0 | 0 | `UNRESOLVED` |
| 10K medium K100 | 77,000 | 88.56 | 0.65 | 0.57 | 1.40 | 0 | 5.96 | 2.86 | 0 | `UNRESOLVED` |
| 10K common K100 | 78,000 | 80.16 | 0 | 0.72 | 3.14 | 0 | 10.83 | 5.15 | 0 | `LIKELY_INCLUSIVE` (G06A 37.47) |
| 100K absent K100 | 118,000 | 14.55 | 49.16 | 36.29 | 0 | 0 | 0 | 0 | 0 | `LIKELY_INCLUSIVE` (G01 49.50) |
| 100K rare K100 | 118,000 | 16.91 | 47.94 | 35.15 | 0 | 0 | 0 | 0 | 0 | `LIKELY_INCLUSIVE` (G01 48.26) |
| 100K medium K100 | 121,000 | 88.02 | 0.65 | 0 | 1.83 | 0 | 6.18 | 3.32 | 0 | `UNRESOLVED` |
| 100K common K100 | 242,000 | 79.66 | 0 | 0.67 | 3.16 | 0 | 10.91 | 5.60 | 0 | `LIKELY_INCLUSIVE` (G06A 37.44) |
| 100K common K10 | 241,000 | 79.84 | 0 | 0.81 | 4.18 | 0 | 5.74 | 7.33 | 1.50 | `UNRESOLVED` |

No lane met `STRONG_EXCLUSIVE_CANDIDATE`. Allocation capture: `heaptrack 1.5.0`,
both prescribed 100K lanes (`ALLOCATION` gate `I0-P12` PASS).

Reopen: 42 fresh single-shot processes (21 per size, `clear` contention in every
block) plus both CPU loops (128 iterations at 10K, 64 at 100K, zero lost samples).
Reopen total medians 42,791,382 ns (10K) and 427,513,918 ns (100K). Inclusive
reopen frames: `R03` 40.39 %, `R04` 43.41 %, `R05` 21.03 % (100K) — overlapping;
the **exclusive** partition is 100 % `R08` (unknown), so no stage can be credited
with a removable share. Stage-level latency is `NOT_MEASURED`.

## 6. Storage and sidecar attribution

Committed index at 100K = **30,965,025 B**:

| Part | Bytes | Share |
|---|---:|---:|
| Segment file (sections 21,363,360 + 666 overhead) | 21,364,026 | 69.00 % |
| Mutation-state sidecar | 9,600,180 | 31.00 % |
| Manifest | 636 | 0.002 % |
| `CURRENT` | 183 | 0.0006 % |

100K segment sections: `Stored` 9,662,513 (31.2046 %); `Postings` 3,983,573
(12.8647 %); `Dictionary` 3,500,207 (11.3037 %); `Columns` 2,004,364; `DocKeys`
1,100,010; `VersionRefs` 800,011; `FieldNorms` 300,074; `LiveDocs` 12,511;
`Schema` 97.

Sidecar (payload v1, 100,000 live / 0 deleted / 0 replay rows) = 9,600,010 B
payload + 170 B envelope = 9,600,180 B (**96.0018 B/doc**):

| Component | Bytes | Share of sidecar |
|---|---:|---:|
| `live_pointer_id_bytes` (full segment ID per live row) | 6,600,000 | 68.7487 % |
| `row_key_bytes` | 900,000 | 9.3748 % |
| `row_revision_bytes` | 800,000 | 8.3332 % |
| `live_doc_id_bytes` | 800,000 | 8.3332 % |
| `row_key_prefix_bytes` | 200,000 | 2.0833 % |
| `live_pointer_prefix_bytes` | 200,000 | 2.0833 % |
| `row_status_bytes` | 100,000 | 1.0416 % |
| headers | 10 | 0.0001 % |
| replay / batch components | 0 | 0 % |

Reconciliation equalities verified: `sum(component_bytes) == payload_bytes`,
`payload + overhead == sidecar file`, sidecar digest/length equal to the PR 15F
inventory entry, `live + deleted == row_count`, v2 batch remainder labelled
`SEMANTIC_BATCH_DETAIL_NOT_VERIFIED` (zero invented bytes for v1).

Per-document costs and the isolated historical table are in
[`storage-attribution.md`](storage-attribution.md). `saved_bytes_upper_bound` is
labelled `PHYSICAL_ZERO_BYTE_CEILING_ONLY` and is **not** a benefit forecast.

## 7. Architecture deliverables

| File | Content | Status |
|---|---|---|
| [`architecture-15i-a.md`](architecture-15i-a.md) | Segment-ID interning + compact live pointers, V3 payload, feature rule | `DESIGN_PROPOSAL_ONLY` |
| [`architecture-15i-b.md`](architecture-15i-b.md) | 128-doc compressed STORED blocks, LZ4/Zstd evaluation gate, validation certificate | `DESIGN_PROPOSAL_ONLY` |
| [`architecture-15i-c.md`](architecture-15i-c.md) | Narrow postings-driven exact-count/top-K operator with fallback | `DESIGN_PROPOSAL_ONLY` |
| [`compatibility-matrix.md`](compatibility-matrix.md) | Producer/consumer responsibilities across A/B/C | contract matrix |
| [`decision-register.md`](decision-register.md) | 14 recorded decisions/exceptions | mixed |
| [`measurements.md`](measurements.md) | Generated measured baseline | measured |

Open questions and the exact STOP principles are inside each contract. **No
15I-A/B/C production code exists, and none is authorised by this report.**

## 8. Tests and QA

Executed on the final tree (`verify.py qa` record
`target/pr15i-0/qa/workspace-qa.json`, 20 commands, all `PASS`):

| Command | Result |
|---|---|
| `cargo fmt --all -- --check` (stable and 1.85.0) | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (1.85.0) | PASS |
| `cargo test --workspace --all-targets` | PASS — 130 binaries, **2,339 passed, 0 failed, 12 ignored** |
| `cargo test --workspace --all-targets --all-features` | PASS — 130 binaries, **2,343 passed, 0 failed, 81 ignored** |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 130 binaries, **2,343 passed, 0 failed, 81 ignored** |
| `cargo doc --workspace --no-deps` | PASS |
| `cargo bench --workspace --no-run` | PASS |
| `cargo llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS — **93.23 % line coverage** |
| probe tests, stable and 1.85.0 (`--locked --offline`) | PASS — 45 tests each |
| PR 15I-0 controller tests | PASS — 82 tests |
| PR 15D / PR 15F / PR 15E harness tests | PASS — 83 / 54 / 90 |
| `git diff --check` | PASS |
| real pinned RustFS acceptance (CI command list) | PASS |
| real-boundary `#[ignore]`d integration sweep against pinned RustFS | PASS — **66 tests executed, 0 failed** |

The RustFS topology used the pinned digest
`rustfs/rustfs@sha256:1803faef…b6a3c` in a disposable `podman` container with
disposable credentials, an isolated bucket prefix and an unconditional teardown.
No `SKIP` is counted as a pass.

Two QA invocations are preserved as evidence: the first attempt failed on a
`libtest` limitation (`--ignored` + `--skip`) and is kept as
`target/pr15i-0/qa/workspace-qa-01-failed.json`; the recorded run is the second.

## 9. Exceptions and residual risk

| Rule | Category | Evidence | Smallest next decision |
|---|---|---|---|
| `I0-X15` | verifier defect corrected before publication | `verification-01` (reopen/allocation shape) preserved; `verification-02/03/04/05` re-derived | none |
| `I0-X11`, `I0-X32`, `I0-X39` | three PR 15F CPU campaigns rejected for lost perf chunks | `…-01/-02/-03` under `target/pr15f/`, `X19_PERF_LOST_SAMPLES`; `…-04` is the sealed qualified one | none |
| `I0-X24` | inclusive frames overlap; unknown 14.55–88.56 % | `performance-attribution.md` §2, §5 | none |
| `I0-X25` | physically different sort encodings | `measurements.md`, `performance-attribution.md` §1 | none |
| `I0-X26` | current 100K size equals the historical figure | same value because 15H-E rolled back byte-for-byte; reported, not reworked | none |
| `I0-X30` | hosted CI and review unavailable (`gh` credentials invalid) | `CI_PENDING`, `REVIEW_PENDING` | maintainer dispatches CI and reviews |
| `I0-X34` | future V3 feature id `0x000C` free on the measured base | `preflight.md` §3 | confirm at implementation base |
| `I0-X37` | attribution does not justify a specific rewrite | `UNRESOLVED`/`LIKELY_INCLUSIVE` only | 15I-C must add stage-level measurement first |

Residual risks carried forward (unchanged from
`invariant-traceability.md` §5): the v2 batch block is never decoded by this
probe; the sidecar corpus is single-segment/all-live/zero-replay; cross-engine
ratios are logical, not physical; RustFS conformance covers read paths that exist
on this base, not future formats.

## 10. Disposition

```text
DOCUMENTATION_IMPLEMENTED
MEASUREMENT_QUALIFIED            (I0-P00 … I0-P12 all PASS, verification-05)
TESTS_PASSED                     (stable + MSRV, FsDirectory, real pinned RustFS, 93.23 % lines)
HOSTED_CI_PENDING                (gh credentials invalid locally)
REVIEW_PENDING                   (independent review required)
NOT_MERGED                       (no push, PR or merge performed)
```

Final verifier result: `15I0_QUALIFIED_REVIEW_READY`, 13/13 gates `PASS`,
`qualified: true`, measured source `48e7d3a`, verification artifact
`target/pr15i-0/verification-05.json` (private).

No 15I-A/B/C implementation is claimed. No threshold was retuned, no historical
evidence was rewritten and no sealed campaign was modified.

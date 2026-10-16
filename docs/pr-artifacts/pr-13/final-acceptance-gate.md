# PR 13 — final acceptance gate

**Baseline (corrective):** `ae2036c` on `dev/rust-fs`, parent `main`
`653b412e0e7df8efe18602479b661629427fab57`. This gate precedes the final
acceptance evidence phases and records the executed/partial/deferred ledger.

## Feature status

| Area | Status | Evidence |
|---|---|---|
| File-backed cache staging / cache-first hydration | Implemented + verified | `corrective-preimplementation-gate.md`, M06/M07/M13, transfer unit tests |
| Bounded whole/ranged transfer, retained leases | Implemented + verified | unit peak-retention test, H01–H12 |
| Timed retry / no hidden SDK retries | Implemented + verified | T01–T04 unit, H06–H08 via proxy |
| Cancellation-safe terminal writer | Implemented + verified | H11, K06 (H11), ambiguous tests |
| CAS-last publication | Implemented + verified | C01–C12, H10–H12, K01–K04 |
| Real HTTP fault proxy | Implemented + verified | H01–H12 |
| Separate-process crash recovery | Partially verified | K01–K04 (K05 via H02/H09, K06 via H11) |
| Independent query oracle | Partially verified | O01–O03, O07–O10 (O04–O06 NOT EXECUTED) |
| Remote benchmark lane | Implemented + measured | P01–P04, `benchmark-report.md` |
| V08 query-scoped pruning | DEFERRED — NOT EXECUTED | plan §9; needs maintainer approval |
| GitHub Actions on final SHA | NOT OBSERVED | no push from this environment |

## Fault checkpoints (proxy rules)

| Checkpoint | Rule | Test |
|---|---|---|
| After segment, before state | `BlockBeforeCheckpoint` on `index/state` | K01 |
| After state, before manifest | `BlockBeforeCheckpoint` on `index/manifests` | K02 |
| After manifest, before CAS reaches RustFS | `BlockBeforeCheckpoint` on `index/CURRENT` | K03 |
| After CAS applied, before ack | `ForwardThenCheckpoint` on `index/CURRENT` | K04 |
| CAS applied, response lost (in-process) | `ForwardThenDrop` | H10 |
| CAS never reaches RustFS (in-process timeout) | `DelayUntil` | H11 |

All proxy paths preserve the exact signed request bytes and `Host` header; the
upstream remains the pinned real RustFS container.

## Independent oracle

`crates/quervant-core/tests/pr13_oracle.rs` enumerates expected hit sets by hand
from corpus/query semantics (never from a Quervant run) and checks local
`FsDirectory`, `FakeObjectStore` and real RustFS cold reopen. `TimeRange` was
confirmed half-open `[start, end)` by the oracle; `In`/`Missing` are not
supported by the current searchers and are NOT APPLICABLE to PR 13.

## Environment

Pinned RustFS
`docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`,
`QUERVANT_RUSTFS_*` variables, isolated per-run prefixes, native Linux
filesystem. Corpus digest for the benchmark:
`4e80dd39ca95a18e5859e38c7f7881a9272ce737066cfa570876deab4da9ce52`.

## Residual risks / STOP items

- **V08 deferral lacks maintainer approval** (plan §9). PR 13 must not be marked
  DONE until approved and linked.
- K05 (crash during a partial ranged download) and O04–O06 (JSON/geo oracle) are
  **NOT EXECUTED**; do not treat as PASS.
- CI on the final pushed SHA has **not** been observed.

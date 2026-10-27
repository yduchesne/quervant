# PR 14F — SR-14F-01 fixup

**Status: `SR-14F-01 CAMPAIGN QUALIFIED; NEW DURABLE ARCHIVE UPLOAD REQUIRED`.**
Three fresh trials at source lock `d12a97537a5131953c948c3a90065a73c3d24b40`
passed the full pre-cold remote oracle, emitted the required marker before the
timed cold lane, and passed the validator and strict auditor. A new deterministic
local package verifies; durable archival awaits a **new** operator Google Drive
upload. PR 14 remains **IN PROGRESS / NOT ACCEPTED**; v0.1 is **NOT RELEASED**.

## 1. Finding and baseline

At reviewed head `dad3030…`, the timed `remote-cold` W01 loop preceded the full
remote `correctness()` oracle. The workload contract requires the complete
independent oracle before any timed workload. `correctness()` is unchanged.

`origin/main` advanced from `7b1b84be…` to `18c8fca8…` during this pass. No
PR-branch executable change was introduced by that drift; no rebase/merge was
performed.

## 2. First corrected attempt — failed, preserved

Source lock `8cfd2fce436ea99d57d2699471ab49d2cd1a3446` used
`index.snapshot()`. That snapshot reflects the generation observed at
`create()` time (empty), so t1 failed at `pr14_bench_remote.rs:286` with W01
`0 != 10000`. No CSV/report was written; t2/t3 did not start. The attempt is
preserved as unqualified under
`target/pr14-p4/attempts/8cfd2fce436e-t1-oracle-snapshot-failure/`
(contention `615cf158…`, run log `e0db1d18…`).

## 3. Final source lock and fix

Source lock **`d12a97537a5131953c948c3a90065a73c3d24b40`** uses AD02's approved
fallback: a fresh `RemoteIndex::open_existing` reader of the committed
generation feeds the untimed oracle. Its reader/snapshot and the writer `index`
handle are dropped before the disposable workspace is cleared. The exact marker
`PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS` is printed before the first cold
stopwatch, and the pass flag is asserted before every cold sample.

## 4. Qualified campaign

| Trial | UTC window | Duration | Contention | Marker |
|---|---|---:|---|---|
| t1 | 21:01:28Z–21:11:58Z | 629.79 s | clear (0.006250, 0) | PASS |
| t2 | 21:12:01Z–21:22:20Z | 619.23 s | clear (0.009148, 0) | PASS |
| t3 | 21:22:22Z–21:32:41Z | 619.38 s | clear (0.006667, 0) | PASS |

All trials: `sha=d12a975…`, `qualified=true`, `idle_confirmed=true`,
`contention=clear`, `dirty=false`, corpus `80ef5615…f8768`, 20,000 docs,
14 lanes × 20 samples (280 CSV rows each).

- Validator: `PASS: 3 qualified pr14_p4_v1 trials`
- Strict auditor: `PASS PR14F audit`
- Wrapper marker gate: satisfied by all three run logs
- W08: `NOT APPLICABLE (APPROVED)`, never measured

Published reports:

| Trial | Report | SHA-256 |
|---|---|---|
| t1 | `benchmarks/reports/pr14f-p4-d12a97537a51-t1.json` | `28a8cf2f3a2734a2e5925815b52ca799a915995e8c90db43831bbb9f7049f44e` |
| t2 | `benchmarks/reports/pr14f-p4-d12a97537a51-t2.json` | `95e5931aac9c02c3ca8ea3950e8f48f061577b361e3e4559f6f9945e4be1ca7a` |
| t3 | `benchmarks/reports/pr14f-p4-d12a97537a51-t3.json` | `65d39b8f68cc77de0d3bc6f1dd3867f101897cac1887755c66e94cb0a01a5910` |

New latency tables are in `benchmark-report.md` §10, derived directly from the
new CSVs.

## 5. New local archive

Deterministic package (pending durable upload):

`target/pr14-p4/package/quervant-pr14f-sr14f01-p4-d12a97537a51-raw-evidence.tar.gz`

It contains three raw CSVs, three contention records, three run logs, three
published reports, the fixup manifest/note, and the read-only analysis helper.
`PACKAGE-SHA256SUMS` and `original-archive/SHA256SUMS` verify; a rebuild is
byte-identical. Package SHA-256:
`373d3b756598b1a70f1501530167e7399a47d9172799b0bf05a40ee6ada181e2`
(17,674 bytes). The package embeds the pre-archival manifest snapshot to avoid a
self-referential hash; the repository manifest records the package hash.

**Durable archive: `BLOCKED — NEW GOOGLE DRIVE UPLOAD REQUIRED`.** The prior
Google Drive file belongs to the historical `7df4920` campaign and must not be
reused.

## 6. Gates at `d12a975`

| Gate | Result |
|---|---|
| Stable and MSRV `fmt` | PASS |
| Stable and MSRV Clippy, both feature sets, `-D warnings` | PASS |
| Workspace tests (stable/MSRV, ±all-features) | PASS — 2,044 / 2,048 passed, 0 failed |
| Coverage | PASS — 91.84% lines |
| `cargo doc` / `cargo bench --no-run` | PASS |
| `test-scripts.sh` / oracle-order tests | PASS — 64/64, 6/6 |
| Validator self-test / `--list` / `git diff --check` | PASS |
| Native Linux filesystem | PASS — ext4 |
| Pinned RustFS digest/health | PASS — `1803faef…6a3c`, `1.0.1` |

## 7. Historical separation

The `7df4920…` campaign, its reports and its Google Drive archive remain
historical only. The failed `8cfd2fc` t1 attempt is preserved as unqualified.
Neither is current SR-14F-01 acceptance evidence.

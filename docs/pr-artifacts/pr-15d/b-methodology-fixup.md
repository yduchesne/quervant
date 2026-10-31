# PR 15D-B — Methodology, evidence and resource-qualification fixup

**Status:** IN PROGRESS. This document is the fixup's audit trail. It is not an
acceptance record, and nothing here authorizes merge, release or a `DONE` marker.

Plan authority: `QUERVANT_PR15D_B_METHOD_REPORT_FIXUP_PLAN.md`. Governing
documents: `AGENTS.md`, `docs/BENCHMARKING.md`, `docs/TESTING.md`,
`benchmarks/pr15d/spec/pr15d_v1.{json,md}`, `benchmarks/pr15d/protocol/schema.json`.

## P0 — Starting state, snapshot and protection

### Source lock

| Item | Value |
|---|---|
| Branch | `dev/pr15d-b-comparison-qualification` (PR #81; no new PR created) |
| PR / start HEAD | `850b119b885ad7648904b14afa0adeab2b5bdb32` |
| `origin/main` (PR base) | `8caca7682cc23c7b595fba049608e7fd843cd4dd` |
| Merge base | `8caca7682cc23c7b595fba049608e7fd843cd4dd` |
| Working tree | clean (`git status --porcelain=v1` empty) |
| Classification | **X01 AUTO** — branch + HEAD equal the specified PR SHA, worktree clean |

### `git diff --name-status origin/main...HEAD` (recorded at P0)

```
M   .github/workflows/ci.yml
A   .github/workflows/comparative-adapters.yml
M   benchmarks/pr15d/README.md
M   benchmarks/pr15d/harness/aggregate.py
M   benchmarks/pr15d/harness/smoke.py
M   benchmarks/pr15d/harness/test_pr15d.py
M   benchmarks/pr15d/harness/validate.py
A   benchmarks/reports/pr15d/pr15d-qualified.json
A   docs/pr-artifacts/pr-15d/b-acceptance.md
A   docs/pr-artifacts/pr-15d/b-ci.md
A   docs/pr-artifacts/pr-15d/b-preflight.md
A   docs/pr-artifacts/pr-15d/b-trials.md
M   docs/pr-artifacts/pr-15d/decisions.md
M   docs/pr-artifacts/pr-15d/qualification.md
```

### Frozen / protected hashes at P0 (must not change)

```
ec6c0db865845184ba867fca97add3196bd62a3e88f2cf2c8042a1c594dce466  spec/pr15d_v1.json
a0e72ac93bab4fdc0c2e6b8aaebb20231721415ea7ddaf8963da1263c54d7cb0  spec/pr15d_v1.md
62bb81ad2b96162ea1d3c7eef656fa62b48ff2205c819e8715d6bb2b2f2a9eb8  protocol/schema.json
d0bfd0ac7f63509f20454dd8ab96dcb50075a5293235fe894b14b60e5b86851d  corpus/generate.py
4c37a72251b6b16e972161070297436c18b96421b09acd2665bce5c65abd20b2  corpus/oracle.py
8be6c21e5a2ac41a3dc12c17ab8bc5e91080c689323f7f05015919c01ff31243  harness/run.py
9a25d5c42a04e0bcc00b32d22b0b67e1a7fcf0b921c3de044851235adcaf37f2  adapters/quervant/Cargo.toml
050f9d751f978277e02057a0002d1b87d6f0166d73dcadab93f4e78e26cb817d  adapters/quervant/Cargo.lock
f4d32d74fae1ebbe6d62b604492361476b57bd08b4c1006a6dbc4168dcd3edd3  adapters/tantivy/Cargo.toml
3f3bd6cc1dc9c92ad57405bbe9f4ff26dcfed23a224ff9508ea41d04cc1bcb2a  adapters/tantivy/Cargo.lock
facafbbfe87bc9dc14f94573bf479d2b45006c8d8b827cef7dddcf95cef7db84  adapters/lucene/build.gradle
7c002b53d6b85acd66bcf16887ef8f0383f5ac9b2e49524dae19c3b4d582c3ce  adapters/lucene/A1-CHECKSUMS.sha256
05fcb55a155233ee632da57149d1ba3cd39a001701ae00e0c20782fbaf6c378b  adapters/lucene/gradle/wrapper/gradle-wrapper.properties
```

`harness/validate.py` and `harness/aggregate.py` were already amended in
`ffbd4b3` (index-size policy) and are **frozen for numerical qualification
logic** in this fixup; only the expressly permitted metadata/evidence hooks may
touch them.

### Old campaign inventory (preserved, untouched)

Run directory: `target/pr15d/runs/20261030T220025Z-c9e982fec5b21ca542f76d0d7940ef796a4c7474`
(ignored by Git, 635 MB). Essential files and SHA-256:

| File | Bytes | SHA-256 |
|---|---:|---|
| `run.json` | 3353 | `98c8d4247bfd63a299fd0013ae6cce4079fe60e6443ec3eaf7572695d5bb7c54` |
| `validation-initial.json` (original INVALID) | 405 | `86ecd4fb74cb9da2c3548dba9798443e131ae4074075ec2466184cd93c6d638c` |
| `validation.json` (post-amendment) | 261 | `a51a7badb129acb028873cae4678c3cab801e8fade7ca13b92bf2a05ad0240ba` |
| `trials/trial-1/quervant.json` | 50268 | `97ee3c48700bea71a2b2d0d2488a6e9066e686cbdfbcd3b5af95ffb2835d5769` |
| `trials/trial-2/quervant.json` | 50268 | `dbb2a8be05b21f9ef94c5d49f980af3506716be6aecf753346e3ce9e2c26a448` |
| `trials/trial-3/quervant.json` | 50268 | `f48b5c0619b7982bed488dca9c2e75e01cfd0a5f3432a6ea88858f6f6f9423a6` |
| `trials/trial-1/tantivy.json` | 47634 | `92f7e7b20cfca1e16ef6ca53bece04c5c343dd95ebb92ef344193a1c75916121` |
| `trials/trial-2/tantivy.json` | 47651 | `aa998f0b5698c00cc792f19247725c01454865d7a5e5dd834ca0c06225762025` |
| `trials/trial-3/tantivy.json` | 47634 | `3bc58ff58bd372943e638b280df6bd213d956aa5c19d6af3ba7ce1f3bfef31b2` |
| `trials/trial-1/lucene.json` | 49094 | `58a8333c60e811fa0eb873167b6e59364884f845523aff63d4c4cba9860f2c13` |
| `trials/trial-2/lucene.json` | 49073 | `1040db69f438b5844ef3a1ba9e23873a0a82198be6f06d10ae942f1c6fdee9f1` |
| `trials/trial-3/lucene.json` | 49093 | `1ac5ffbdf7ca27a1e6202a55e3e7f9cfe5d20bf5270ac10c9fd212a3a8ade363` |
| `contention/**` | 54 files | inventoried individually at P0 (per-trial, per-engine, per-N pre/post/final) |

**X06 AUTO** — the old run and all nine raw manifests exist and match the
inventory recorded at the end of the previous campaign. The measurement source
SHA `c9e982fec5b21ca542f76d0d7940ef796a4c7474` is **superseded**; its raw files
are never edited, moved or reused for new samples.

### Byte-identical archive of the superseded reports

```bash
mkdir -p benchmarks/reports/pr15d/diagnostic-v1
cp benchmarks/reports/pr15d/pr15d-qualified.json benchmarks/reports/pr15d/diagnostic-v1/pr15d-qualified.json
cp docs/pr-artifacts/pr-15d/qualification.md docs/pr-artifacts/pr-15d/qualification-v1-superseded.md
cmp ... # both compare equal
```

| Archived artifact | SHA-256 |
|---|---|
| `benchmarks/reports/pr15d/diagnostic-v1/pr15d-qualified.json` | `8b81c09aff407165f253a460160fb9694abbe0d4b12307516b44e28e7d199bc1` |
| `docs/pr-artifacts/pr-15d/qualification-v1-superseded.md` | `9008fe7d76f334941ccf0746db67cfdc5fdfb0621d8668d4cd7f3e425fe2c5e3` |

**X22 AUTO** — both `cmp` comparisons passed, so the archives are byte-identical
to the canonical files they preserve. The archival copies are **never edited**;
the "superseded" statement lives in this document and in
`qualification-v1-superseded.md`'s own header is *not* added (it must remain
byte-identical), so the label is carried by this record instead.

### Baseline deterministic tests at P0 (actual results)

| Command | Result |
|---|---|
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | **PASS** — `Ran 63 tests ... OK` |
| `bash benchmarks/scripts/test-scripts.sh` | **PASS** — `script tests: 108 passed, 0 failed` |
| `cargo fmt --all -- --check` | **PASS** |
| `git diff --check` | **PASS** |

### P0 reconciliation notes

- The old campaign's qualified aggregate remains on the canonical paths **for
  now**, but it is methodologically superseded: its `engine_ns` excluded
  stored-`doc_id` materialization. It must not be quoted as a corrected
  comparison.
- The previous human attestation covered only the **2026-10-30
  22:00:25Z–22:41:08Z** window. It does **not** authorize this fixup's campaign
  or resource probes. See the attestation gate at the end of this document.

## P1 — Exact query timing correction (F1)

`engine_ns` now starts immediately before the engine search/count and stops only
after **every** returned `doc_id` has been materialised into the adapter's owned
result collection. Ordering/count sanity checks, response serialisation, IPC,
process start, reader open and the independent oracle remain outside the timer.
No timing was split, duplicated or subtracted.

| Adapter | File | Change |
|---|---|---|
| Quervant | `adapters/quervant/src/main.rs::search` | `let engine_ns = positive(started.elapsed()…)` moved from immediately after `searcher.search(...)` to immediately after the `for hit in &response.hits { … doc_ids.push(doc_id) }` loop, before `let sorted = …` |
| Tantivy | `adapters/tantivy/src/main.rs::handle_query` | stop-clock moved from after `TopDocs`/`Count` to after the stored-document loop that pushes `doc_id`, before the returned-count check; the stale "stored-field decoding is outside the timed engine operation" comment was replaced |
| Lucene | `adapters/lucene/.../Adapter.java::query` | `long engineNs = System.nanoTime() - started;` moved from after `searcher.search(query, k, sort)` to after the `for (ScoreDoc scoreDoc : top.scoreDocs)` loop, before the count check |

Unchanged by construction: `UnifiedRequest`, `Budgets`, `SearchLimits`, the sort
fields, the projection, the Tantivy `ordinal` fast field, the Lucene string sort
field, the JSON response shape and every error path.

## P2 — Ingestion boundary (F2) and physical-sort disclosure (F3)

**F2.** Tantivy's `handle_build` previously called `make_document(...)` *inside*
the `index_ns` interval. It now builds `let documents: Vec<TantivyDocument>`
before `let insert_started = Instant::now();` and the timer covers only
`writer.add_document(document)`. Quervant (`let documents = parse_tsv(...)` before
the timer) and Lucene (`List<Document> documents = parseCorpus(corpusPath)` before
the timer) already behaved this way, so all three ingestion boundaries now agree.
Writer memory budget, schema, field names, document count/order and `commit` /
reopen / index-byte measurement are untouched.

**F3.** The aggregate publishes `sort_physical_keys`
(`physical_equivalence: "NOT_CLAIMED"`), a Markdown "Physical sort
representation" section, and a "Query API shape and timing boundary" section. The
documented representations are:

| Engine | Physical sort |
|---|---|
| Quervant | Keyword `doc_id` column, ascending |
| Tantivy | `u64 ordinal` fast field derived from the fixed-width `doc_id`, ascending |
| Lucene | `STRING doc_id` `SortedDocValues` sort field, ascending |

Logical order is identical for the frozen fixed-width IDs; the physical sort
workloads are **not** claimed to be equivalent, and a test rejects that phrasing.

**Primary ingestion metric.** `ingest_through_commit_ns = index_ns + commit_ns`
per trial, added to `indexing[engine][N]` with `trial_values`, `median`, `min`,
`max` and `dispersion_max_over_min`, derived only from validated `build` records
with checked integer addition (overflow → `AggregateError`, never wrapping). The
raw `index_ns`, `commit_ns` and `reopen_ns` remain visible and unchanged. The
metric measures adapter insertion plus commit, **not** proven fsync-equivalent
durability, and `reopen_ns` stays separate.

No change was made to `validate.py` (byte-identical to the amendment baseline),
to dispersion/overlap/index-size policy, to `run.py`, or to the workload.

## P3 — Evidence packaging (F4)

`harness/package_evidence.py` (standard library only) produces a deterministic
`ZIP_STORED` archive with a fixed `(1980,1,1,0,0,0)` timestamp, forward-slash
relative names and `ZipInfo`-written entries, so reruns on unchanged inputs are
byte-identical. It requires a `complete`+`qualified` run, a `QUALIFIED`
validation, three trials × three engines, all 54 contention records, consistent
trial source SHAs, no symlinks and no path escaping the run directory. It emits
`SHA256SUMS` over every other member (never the ZIP), a reproduction `README`,
and a `pr15d-evidence-manifest-v1` manifest with per-file SHA-256/byte length,
package digest/size, disposition and reviewer reproduction steps.

Sensitive content is **reported, never rewritten** (`disposition:
BLOCKED_SENSITIVE_CONTENT`), because rewriting a raw file would invalidate its
digest and the reviewer's re-derivation. `--require-resources` fails closed
(exit 3) instead of silently omitting the CPU/RSS gate.

Note: the archived `run.json` records absolute paths from the measuring host, so
the packager reports `absolute_home_path` findings on real evidence and
publication is therefore deferred to a human decision (X28).

## P4 — Supplemental CPU/RSS probe (F5)

`harness/resource_probe.py` collects **separate process-level** diagnostics and
never touches `engine_ns`, the latency ratios or the 20-sample series:

- 18 probes = 3 rounds × 3 engines × {N=10 000 `rare`/K=10, N=100 000
  `medium`/K=10}, round order rotating `q→t→l`, `t→l→q`, `l→q→t`;
- opens an **already built** index (`indexes/trial-<round>/<engine>/n<N>`), never
  rebuilding or mutating one;
- 5 untimed warmups, each reply validated by `run.validate_query_response`
  against `oracle.expected`;
- serial requests until ≥500 ms of process CPU, 60 s wall or 50 000 requests,
  whichever first; `stop_reason` recorded;
- `/proc/<pid>/stat` parsed around its **final `)`** (so a `comm` containing
  spaces/parentheses is safe), `utime`/`stime` summed, `VmHWM` from
  `/proc/<pid>/status` converted kB→bytes, `SC_CLK_TCK` required positive, and
  `cpu_ns = ticks × 1e9 // CLK_TCK`;
- fail-closed PID identity: a shell/wrapper `comm` is rejected, Lucene must be
  `java` whose cmdline names the adapter, and descendants are never summed;
- statuses are `MEASURED`, `BELOW_RESOLUTION`, `DIAGNOSTIC_RESOLUTION_LIMIT` or
  `BLOCKED_ENVIRONMENT` — never a fabricated zero;
- contention is sampled before and after every probe (`X36_CONTENTION` on any
  non-clear state), and the nine trial manifests are hashed before/after to prove
  they were not mutated (`X41_EVIDENCE_MUTATED`).

Allocations remain `NOT_MEASURED` and are never implied by `VmHWM`.

## P5 — Local correctness and method-validation gates (actual results)

Run at the working tree that became the measured-source candidate:

| Command | Result |
|---|---|
| `python3 benchmarks/pr15d/harness/test_pr15d.py` | **PASS** — `Ran 77 tests ... OK` |
| `python3 benchmarks/pr15d/harness/test_resource_probe.py` | **PASS** — `Ran 29 tests ... OK` |
| `python3 benchmarks/pr15d/harness/test_package_evidence.py` | **PASS** — `Ran 18 tests ... OK` |
| `bash benchmarks/scripts/test-scripts.sh` | **PASS** — `108 passed, 0 failed` |
| `cargo fmt --all -- --check` / `cargo +1.85.0 fmt …` | **PASS** |
| adapter crates `cargo fmt -- --check` (quervant, tantivy) | **PASS** |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` (stable + 1.85.0) | **PASS** |
| `cargo test --workspace --all-targets --all-features` (stable) | **PASS** — 116 suites, 2173 passed, 0 failed, 75 ignored |
| `cargo +1.85.0 test …` | **PASS** — 116 suites, 2173 passed, 0 failed |
| `cargo llvm-cov … --fail-under-lines 85` | **PASS** — 92.31 % lines, exit 0 |
| `cargo doc --workspace --all-features --no-deps` | **PASS** |
| `cargo bench --workspace --no-run` | **PASS** |
| `git diff --check` | **PASS** |

Real adapter builds (actual pins, verified wrapper):

```
cargo build --release --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml --target-dir target/pr15d/preflight-build/quervant   # OK
cargo build --release --locked --manifest-path benchmarks/pr15d/adapters/tantivy/Cargo.toml  --target-dir target/pr15d/preflight-build/tantivy    # OK (tantivy 0.22.1)
cd benchmarks/pr15d/adapters/lucene && sha256sum -c A1-CHECKSUMS.sha256 && ./gradlew --no-daemon classes installDist                            # BUILD SUCCESSFUL
```

Real three-engine oracle smoke on the edited adapters,
`smoke.py --sizes 10000,100000` → **exit 0**, 8 queries × 2 sizes × 3 engines
PASS (FIX-T06). A skipped adapter is never counted as a pass.

## Invariant → test crosswalk

| Invariant | Tests |
|---|---|
| I01 timer encloses query + count + sort + `doc_id` materialisation | FIX-T01–T03 (`AdapterTimingContractTests`) |
| I02 setup/open/IPC/serialisation outside `engine_ns` | FIX-T01–T03 timer-vs-serialisation ordering; FIX-T05 |
| I03 errors never become zero hits/success | FIX-T07 (`run.validate_query_response` rejections) |
| I04 frozen lanes/regimes/sizes unchanged | FIX-T08 frozen hashes, FIX-T10 lane matrix |
| I07 ingestion excludes document preparation; derived `index+commit` | FIX-T14, FIX-T15, FIX-T27, FIX-T19 overflow |
| I06 physical-sort disclosure, no equivalence claim | FIX-T12/T13 |
| I10 CPU/RSS never enter latency; anomalies rejected | `test_resource_probe.py` (29 tests) |
| I11 reviewable, reproducible evidence; tamper rejected | `test_package_evidence.py` (18 tests) |
| I13 unchanged dispersion/overlap rules | existing `test_t12`/`test_t16`/`test_t20` still PASS |

## P6 — New campaign status: `BLOCKED-ATTESTATION`

Per the fixup plan (and X38), the 2026-10-30 attestation covers only that old
window. **No new campaign has been run and no `--idle-confirmed` was passed.** No
new `target/pr15d/runs/<new-id>` exists, no new `validation.json`, no new
aggregate, and the canonical reports still hold the superseded diagnostic build.

To proceed, the human operator must supply a fresh, explicit attestation naming
the host and the window, for example:

> "Host *<host>* is idle from *<T0>* to *<T1>* on *<date>*; I authorize the PR
> 15D-B corrected-methodology campaign and the supplemental CPU/RSS probes on
> that window."

After that: commit → run the campaign on that exact clean SHA → validate →
aggregate → `resource_probe.py --idle-confirmed` in its own authorized window →
`package_evidence.py --require-resources` → publish through the aggregator only.

## Snapshot-reuse finding (closed before P6)

**Finding.** `Index::snapshot()` constructs a *new* `ReaderSnapshot` on every call
(`crates/quervant-core/src/index/mod.rs`). The Quervant adapter called it inside
`search()`, i.e. **once per query**, while Tantivy reuses one `IndexReader`
(opened once, cheap `searcher()` per query) and Lucene reuses one
`IndexSearcher`. Every warm query therefore rebuilt a snapshot — and its
metadata-cache slots — as untimed work the other engines never perform.

**Correction (benchmark adapter only).** A `QuerySession` now owns exactly one
`Arc<ReaderSnapshot>` per process and committed generation:

- `QuerySession::open()` opens the index, takes **one** snapshot and records the
  acquisition;
- every `query` op is answered from that same snapshot (`search(&ReaderSnapshot,…)`),
  so the metadata-cache slots survive for the whole session;
- a successful `build` sets `session = None`, so a later query in the same
  process opens the new generation rather than serving a stale snapshot;
- the snapshot is dropped when the session ends (process exit).

`process_cold` semantics are untouched and now proven: `run.measure_lane` starts
**one** `AdapterProcess` per cold sample and **one** for a whole warm lane, so
each cold sample gets an independent process and therefore an independent
snapshot.

**No production Quervant source was modified.** `crates/**` is byte-identical
(verified below); only `benchmarks/pr15d/adapters/quervant/src/main.rs` changed.

### Deterministic evidence (behavioural, not result-only)

In-crate unit tests (`cargo test --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml`),
5 passed:

| Test | What it establishes |
|---|---|
| `query_session_constructs_exactly_one_snapshot_for_the_whole_session` | a thread-local acquisition counter records **exactly 1** `ReaderSnapshot` construction across 10 queries |
| `warm_queries_reuse_one_snapshot_instance_and_its_cache_slots` | `Arc::as_ptr` is unchanged across 5 warm queries and `Arc::strong_count == 1` (same object ⇒ same metadata-cache slots, no per-query duplicate) |
| `separate_sessions_get_independent_snapshots` | two sessions over the same index get non-`ptr_eq` snapshots and the counter advances to 2 (process-cold independence) |
| `snapshot_lifetime_ends_with_the_query_session` | a `Weak` upgrade succeeds while the session lives and fails after it is dropped |
| `reused_snapshot_returns_identical_results` | reuse does not change answers (exact `total_hits`/`doc_ids`) |

Harness-level tests (`test_pr15d.py`, `ProcessLifecycleTests`) replace
`run.AdapterProcess` with a counting fake at the process boundary and prove:
a warm lane creates **1** adapter process (5 warmups + 20 samples), a
`process_cold` lane creates **20** — one per sample.

Plus a source-structure guard (`snapshot_reuse_violations`) that fails if
`.snapshot()` ever returns to `search()`, if the session type disappears, if the
build no longer invalidates the session, or if the acquisition is no longer
recorded.

## P6 — Corrected-methodology campaign (executed in the attested window)

**Operator attestation (verbatim):** "Host MSI is idle from 2026-10-31T00:50Z to
2026-10-31T02:50Z on 2026-10-31. I authorize the PR 15D-B corrected-methodology
campaign and supplemental CPU/RSS probes during that window."

| Item | Value |
|---|---|
| Measured source SHA | `40a9c26a57aa23640904075e77be956ee52718bc` (clean tree at launch) |
| Proposed superseded source | `c9e982fec5b21ca542f76d0d7940ef796a4c7474` — kept, never reused |
| Run id | `20261031T005545Z-40a9c26a57aa23640904075e77be956ee52718bc` |
| Campaign window (UTC) | `2026-10-31T00:55:44Z` → `01:33:18Z` (37 m 34 s) |
| Probe window (UTC) | `2026-10-31T01:38:52Z` → `01:40:32Z` (100 s) |
| Corpus digest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Host fingerprint | `4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f` (WSL2, ext4) |
| Run outcome | `run.py` exit **0**, `status: complete`, `qualified: true`, 3/3 trials per engine |
| Contention | **54/54 `clear`** (pre/post/final), `--allow-contended` never used |

Validator (`validate.py`, frozen semantics): exit **0**,
`status: QUALIFIED`, `errors: []`, `unqualified: []`, `trials: 3`.

Aggregator (`aggregate.py`, the only writer of the canonical reports):

| Artifact | SHA-256 |
|---|---|
| `benchmarks/reports/pr15d/pr15d-qualified.json` | `c9e8ed722aefc4fef43837a5511c2c88575287497b449f68f82f7ea0c251b257` |
| `docs/pr-artifacts/pr-15d/qualification.md` | `fc7ff7b42a117905daef1c22c05d1930d4f11ba500003a31ccaa7f610ceb330f` |

`verify_aggregate()` → `[]`; re-derivation byte-identical; **108 statistics**
matched an independent std-lib recomputation (all 32 lanes × 3 engines trial
medians/median/dispersion, index bytes, and the derived ingestion sums) with
**0 problems**.

### Two execution incidents, both resolved without weakening a gate

1. **Tree-dirty ordering error (mine).** I aggregated before probing, which
   dirtied the tracked report files and the probe correctly refused with
   `X29_SOURCE_DIRTY`. The canonical report was reverted, the probe ran on the
   clean measured tree, and the aggregate was regenerated afterwards **byte
   identically** (both digests above reproduced, proving no data was altered).
2. **Launcher exec race (probe defect).** The Lucene install launcher ends with
   `exec "$JAVACMD" "$@"`; the PID is preserved across the exec but `comm` only
   becomes `java` afterwards, so reading identity immediately after spawn races
   it. Fixed with a bounded 15 s / 10 ms wait (`await_process_identity`) that
   applies the *same* strict rules — a process that never becomes the real
   engine, java without the adapter classpath, or a vanished PID still fails
   closed with `X32_PID_IDENTITY`. No descendant summing was added. The probe
   gate also now compares the measured source with HEAD over the paths that
   actually determine timings, so tooling-only drift is recorded
   (`observation_head_sha`, `measured_path_drift: []`) instead of being waived.

### Resource gate (P4 against the new run)

18/18 probes `MEASURED`, all stopped on `cpu_target`, `SC_CLK_TCK = 100`,
contention `clear` before and after every probe, nine trial manifests unchanged.
Detail in `b-resource-report.md`. Allocations remain `NOT_MEASURED`.

### Evidence package (P3)

```bash
python3 benchmarks/pr15d/harness/package_evidence.py --run <run> \
  --out target/pr15d/evidence/<run>.zip \
  --manifest docs/pr-artifacts/pr-15d/b-evidence-manifest.json --require-resources
```

68 archive members (9 raw manifests, 54 contention records, `run.json`,
`validation.json`, `resource-probe.json`, generated `README.md` + `SHA256SUMS`),
package bytes `502566`, package SHA-256
`426dff2920b55ff63766da284421cf698f9950011da409b88a33be5d6d4e7bab`.
Disposition is **`BLOCKED_SENSITIVE_CONTENT`**: the archived `run.json` contains
absolute `/home/...` paths (18 occurrences) and one other member contains 4. Per
X28 the raw bytes were **not** rewritten — that would invalidate their digests and
the reviewer's re-derivation — so public upload is deferred and the verified
archive stays local for an approved private transfer.

## P7 — Final gates and disposition

Local gates re-run at the reporting HEAD (see the PR report for the table):
`test_pr15d.py` 81 tests, `test_resource_probe.py` 38, `test_package_evidence.py`
18, `test-scripts.sh` 108, adapter unit tests 5, Rust workspace fmt/clippy/test
(stable + 1.85.0), coverage ≥85 %, doc, bench build, `git diff --check`.

**Disposition: `LATENCY-QUALIFIED / ACCEPTANCE-BLOCKED`.**

- Qualified: the corrected-methodology three-engine latency, throughput and
  ingestion comparison, validated and independently re-derived.
- Resource: measured as separate process diagnostics (not part of latency).
- Blocked: exact-head GitHub CI (no working token; nothing pushed) and
  independent human review. Evidence publication blocked by X28 until an approved
  transfer channel exists.
- Not claimed: statistical significance, allocation measurements, OS-cold cache
  behaviour, or any parity/win threshold. Scored BM25 stays
  `SEMANTICALLY_NONCOMPARABLE`.

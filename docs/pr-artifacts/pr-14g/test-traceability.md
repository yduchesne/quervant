# PR 14G — test traceability

**Status: implementation-complete for Phases A and B; final acceptance
`BLOCKED`.** Every executed row below was run from the repository root by the
coding agent; nothing in this table is inferred. Immutable evidence SHAs are the
PR 14G commits plus merged predecessor SHAs.

## 1. Phase A — remote query-time zero-GET (CW-018 / CW-058 / CW-073)

Evidence commit: **`e4d7237`** (`A: test(pr14g): assert remote query zero-GET
boundaries`). File:
`crates/quervant-core/tests/pr14g_remote_zero_get.rs` (new).

| ID | Requirement | Test symbol | Boundary | Status | Evidence SHA |
|---|---|---|---|---|---|
| A01 | Cold remote GET positive control is strictly positive | `pr14g_remote_zero_get::a01_fake_remote_zero_get_after_warmup` (`get_before=11 → get_after=17`), `::a03_positive_control_detects_remote_get`; real: `real::a02_real_rustfs_zero_get_after_warmup` (`requests()==3`, `whole+range==3`) | Fake (`FakeObjectStore::get_calls`), real pinned RustFS (`TransferStats::requests`) | PASS | `e4d7237` |
| A02 | Typed-only and mixed lexical+typed queries add no GET | `a01` families (i)/(ii) after one warmup, each re-executed at `get_calls == 17`; local `Index` oracle parity (keys, totals, fields, scores) | Fake + local `MemoryDirectory`; real provider in `a02` (`mixed`/`typed-only` at `requests == 3`) | PASS | `e4d7237` |
| A03 | Three-slot serial batch (typed, mixed, aggregation) adds no GET | `a01` family (iii); `a05_batch_and_cursor_oracle` independent slot parity | Fake + local; real `a02` (`serial-batch after=3`) | PASS | `e4d7237` |
| A04 | Pinned batch page 1→2 on one frozen generation adds no GET | `a01` family (iv); `a05` page sizes 1/2/3/4; real `a02` (`pinned-page-2 after=3`) | Fake + local `Index::pin`; real `RemoteIndex::pin` | PASS | `e4d7237` |
| A05 | Local-vs-remote keys/hits/projections/aggregations agree | `a01`/`a05`/`a02` (`assert_unified_equal`, `assert_batch_equal`, `PinnedChain` equality) | Fake, local, real | PASS | `e4d7237` |
| A06 | An injected test-only GET is rejected by the invariant checker | `a04_counter_boundary_rejects_query_get` (injected `store.get` → `NotFound`, counter `+1`, `check_no_get` returns `Err`) | Fake only (deliberate negative) | PASS | `e4d7237` |
| A07 | Old/new pinned generations cannot be confused | `a06_wrong_generation_guard` (gen `3` pin vs upserted generation; old pin `delta=0`, new reader `delta=1` with mutated stored `host`) | Fake + local reader workspaces | PASS | `e4d7237` |

Measured counter traces (verbatim from `--nocapture`):

```text
[pr14g][zero-get] family=baseline get_before=11 get_after=17
[pr14g][zero-get] family=typed-only get_before=17 get_after=17
[pr14g][zero-get] family=mixed get_before=17 get_after=17
[pr14g][zero-get] family=serial-batch get_before=17 get_after=17
[pr14g][zero-get] family=pinned-page-2 get_before=17 get_after=17

[pr14g][a02] baseline GETs after hydration+warmup=3 (cold open 3)
[pr14g][a02] typed-only after=3
[pr14g][a02] mixed after=3
[pr14g][a02] serial-batch after=3
[pr14g][a02] pinned-page-2 after=3
```

Known oracle limitation (recorded, not hidden): the real counter
(`TransferStats::requests`) counts only GETs issued through the bounded transfer
budget (segment materialization); direct metadata GETs in `hydrate`/`fetch_verified`
bypass it. The fake counter counts **all** GETs. Query-time metadata re-reads do not
exist because `ReaderSnapshot` holds resident segment bytes.

## 2. Phase B — exact selected physical hit projection (CW-055 / CW-068)

Evidence commit: **`d1ee42b`** (`B: test(pr14g): assert exact physical hit
projection`). Additive tests inside the existing
`crates/quervant-core/src/search/unified.rs` `#[cfg(test)] mod tests`.

| ID | Requirement | Test symbol | Physical witness | Status | Evidence SHA |
|---|---|---|---|---|---|
| B01 | Selected physical tuple projects identical field values in selected order | `search::unified::tests::g_b01_selected_physical_hit_projection_exact` | `[(0,0,k1,h1),(2,0,k3,h3),(0,1,k2,h2)]`; non-key `n`-descending order `k1,k3,k2`; end-user `search()` equal | PASS | `d1ee42b` |
| B02 | Old/new PIT projection differs across the same logical key | `g_b02_old_new_pit_upsert_physical_identity` | `stable` `(1,0)`→`(2,0)`; `host` `before`→`after`; each equals its own snapshot's physical record | PASS | `d1ee42b` |
| B03 | Deleted key omitted; tied sort deterministic; old pin stable | `g_b03_deleted_and_tied_sort_no_leak` | old `["doomed","tie-a","tie-b"]` with `doomed=(0,1)`; new `["tie-a","tie-b"]`; ties `h1`→`h3` | PASS | `d1ee42b` |
| B04 | Deliberate tuple-key mismatch returns `CorruptIndex` | `g_b04_mismatched_selected_hit_is_corrupt_index` | cloned `SelectedHit`, same `(segment_index, doc_id)`, different valid key → `SearchError::CorruptIndex`; honest control still projects | PASS | `d1ee42b` |
| B05 | Key-latest shortcut demonstrably differs from old physical | `g_b05_regression_against_key_only_oracle` | old physical `host="before"` vs new-snapshot key-latest `host="after"`; `assert_ne!` enforced | PASS | `d1ee42b` |

Scope proof: `git diff -U0` for `search/unified.rs` shows **0 removed lines** and a
single hunk starting at line 2404, inside `mod tests` (which begins at line 1323).
No production item was added, removed or re-exported.

## 3. PR 14F transitions carried by immutable evidence (X25)

No benchmark trial was re-run in PR 14G: the diff contains no production query,
remote-cache or workload change. Rows 086, 092, 114, 116, 118, 126 are bound to
merged PR #67.

| CW | Evidence | Executed in PR 14G? |
|---|---|---|
| 086, 092, 114, 116, 118, 126 | source `d12a97537a5131953c948c3a90065a73c3d24b40`, evidence head `cc8153e593bc403d169da291a95a5ad18c6b0293`, merge `054ca55d143e89a092cc6519231b820fecfa42dc`; three qualified trials; validator + auditor PASS; package SHA-256 `373d3b75…81e2`; Drive `18Vqah…` | no — inspected and cited (immutable) |

## 4. Regression evidence at the PR 14G head

| Suite | Command selector | Result | Boundary |
|---|---|---|---|
| Workspace, stable, default | `cargo test --workspace --all-targets` | 110 suites, **2054 passed, 0 failed, 10 ignored** | mixed local/fake |
| Workspace, stable, all features | `cargo test --workspace --all-targets --all-features` | 110 suites, **2058 passed, 0 failed, 74 ignored** | incl. real-gated suites |
| Workspace, MSRV 1.85.0, default / all features | `cargo +1.85.0 test …` | identical counts (2054 / 2058) | mixed |
| PR 14 storage vertical, real RustFS | `cargo test -p quervant-core --all-features --test pr14_storage_vertical -- --ignored --test-threads=1` | **14 passed, 0 failed** | real pinned provider |
| PR 14 storage faults, real RustFS | `… --test pr14_storage_faults -- --ignored --test-threads=1` | **10 passed, 0 failed** | real pinned provider with fault injection |
| PR 14G Phase A, fake | `cargo test -p quervant-core --test pr14g_remote_zero_get` | **5 passed, 0 failed** | fake + local |
| PR 14G Phase A, real | `… --all-features --test pr14g_remote_zero_get -- --ignored --exact --nocapture` | **1 passed** (`real::a02_…`) | real pinned provider |
| PR 14G Phase B | `cargo test -p quervant-core --lib search::unified::tests` | **31 passed, 0 failed** | in-crate, real segment readers |
| Coverage | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | **91.37 % lines**, exit 0 | workspace production code |
| Validator self-test | `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` | `PASS self-test` | benchmark validator |

## 5. Not executed (and why)

| Item | Status | Reason |
|---|---|---|
| Exact-head GitHub CI for PR 14G | **BLOCKED / PENDING** | no check runs exist at the pushed head: `ci.yml` triggers only on `push` to `main` or `pull_request`; PR creation requires a GitHub token and the configured token is invalid (`HTTP 401`). Zero check-runs at `d1ee42b` were verified via the public API. No CI success is claimed |
| Independent review | **PENDING** | agent self-review is not independent review |
| CW-041 / CW-127 decisions | **BLOCKED** | human-only judgments; packet prepared in `maintainer-decisions.md` |
| CW-087 | **BLOCKED** | depends on the two decisions, exact-head CI and independent review |
| PR 14F benchmark re-run | **NOT APPLICABLE (X25)** | immutable qualified evidence remains valid; no measured path changed |
| New per-ID `X01–X13` tests | **NOT DONE (forbidden)** | definitions do not exist; inventing them is prohibited |

## 6. Traceability gaps and residual risk

1. The real-provider zero-GET oracle covers budgeted segment GETs only (see §1);
   the fake covers all GETs. Both are required and both are executed.
2. `R-14A-JSON-MEM` measurements are logical-ledger and child-window observations,
   not RSS/physical bounds; uncharged bounded transients remain (see
   `maintainer-decisions.md` §2.4).
3. `X01–X13` per-ID semantics remain unknown; only family-level evidence exists.
4. Phase B's `Index` fixtures use `MemoryDirectory` (segment bytes are resident);
   the persisted-format and real-filesystem behaviour is covered by the existing
   PR 6/13/14 suites, which pass at this head.

# PR 14G — Phase A: remote query-time zero-GET boundary (CW-018 / CW-058 / CW-073)

**Executed:** `2026-10-28` on branch `test/pr14g-final-acceptance`, baseline
`054ca55d143e89a092cc6519231b820fecfa42dc`.
**Status:** `PASS` for CW-018, CW-058 and CW-073 — both required boundaries
(deterministic `FakeObjectStore`, non-ignored; real pinned RustFS, executed
explicitly) produced the mandated positive control and zero additional GETs.

## 1. New file

`crates/quervant-core/tests/pr14g_remote_zero_get.rs` (new; no production file
touched in this phase).

| Test symbol | §6 ID(s) | Boundary | Ignored? |
|---|---|---|---|
| `a01_fake_remote_zero_get_after_warmup` | A01, A02, A03, A04, A05 | `FakeObjectStore` + exact `get_calls` | no |
| `a02_real_rustfs_zero_get_after_warmup` (`mod real`) | A01, A02, A03, A04, A05 | real pinned RustFS + `TransferStats::requests` | `#[ignore]`, `cfg(feature = "s3")` |
| `a03_positive_control_detects_remote_get` | A01 | `FakeObjectStore` positive control | no |
| `a04_counter_boundary_rejects_query_get` | A06 | `FakeObjectStore` injected-GET negative | no |
| `a05_batch_and_cursor_oracle` | A03, A04, A05 | `FakeObjectStore` + local oracle | no |
| `a06_wrong_generation_guard` | A07 | `FakeObjectStore` old/new generation | no |

`a05` additionally exercises page sizes 1, 2, 3 and 4 through the public
`PitHandle` + `execute_batch_pinned` API on one frozen generation.

## 2. Counter boundary (A-01 / A-02 / A-03)

### 2.1 Fake: exact GET-only counter

`FakeObjectStore::get_calls()` increments inside `ObjectStore::get` before any
fault or `NotFound` handling (`crates/quervant-objectstore/src/fake.rs:321`), and
no PUT/HEAD/DELETE path touches it. Observed trace (`a01`, `--nocapture`):

```text
[pr14g][zero-get] family=baseline get_before=11 get_after=17
[pr14g][zero-get] family=typed-only get_before=17 get_after=17
[pr14g][zero-get] family=mixed get_before=17 get_after=17
[pr14g][zero-get] family=serial-batch get_before=17 get_after=17
[pr14g][zero-get] family=pinned-page-2 get_before=17 get_after=17
```

- `get_before = 11` is the counter after the three publisher commits.
- `get_after = 17` is recorded **after** a cold `RemoteIndex::open_existing` on a
  deleted workspace **and** one full warmup of all four query families. The
  strictly positive delta (`+6`) is the positive control: the instrumented store
  demonstrably counts remote GETs during cold materialization (X08; X09 does not
  trigger). No synthetic GET was added to the counter.
- Counters are **never reset inside** a measured query: the baseline is read once
  after warmup and each family is re-executed one at a time, asserting equality
  immediately afterwards. Every family finished at exactly `17`.

`a03_positive_control_detects_remote_get` isolates the same control: after
removing the disposable workspace, a fresh cold open advances `get_calls` by at
least three, and reads of already-resident committed state add nothing.

`a04_counter_boundary_rejects_query_get` proves the checker is live: between the
baseline and the assertion the test injects a **test-only** `store.get` for a
non-existent physical key (`config.prefix().object_key("pr14g-injected-get")`),
which returns `ObjectStoreError::NotFound` and advances the counter by exactly
one; `check_no_get` then returns `Err("… advanced from … to …")`. Production
search paths are never modified (X11; X12 does not trigger).

### 2.2 Real RustFS: GET-only transfer counter

`TransferStats::requests()` is source-verified as GET-only: it is incremented
exactly once per `ObjectStore::get` attempt in
`remote/transfer.rs::get_with_retry` (line 513) and never by PUT/HEAD/LIST
(line 505 of the same function performs the only `store.get`). Metadata objects
(`CURRENT`, manifest, mutation-state sidecar) are fetched through direct
`store.get` calls in `hydrate`/`fetch_verified` and are therefore outside the
budgeted counter; that limitation is recorded rather than papered over.

Observed trace (pinned RustFS `sha256:1803faef…b6a3c`, version `1.0.1`):

```text
[pr14g][a02] baseline GETs after hydration+warmup=3 (cold open 3)
[pr14g][a02] typed-only after=3
[pr14g][a02] mixed after=3
[pr14g][a02] serial-batch after=3
[pr14g][a02] pinned-page-2 after=3
```

The stats instance is constructed inside `RemoteIndex::open_existing` (zeroed),
so `3` is the cold-hydration GET count for the three committed immutable
segments, and the test asserts `whole_requests() + range_requests() == 3` — one
classified fetch attempt per segment. That is the real-provider positive control.
Every warmed family then left `requests()` at exactly `3`: zero additional
segment (re)materialization GETs.

## 3. Workload families and independent local oracle (A-04 / A-05)

Corpus: the authoritative PR 14 fixture (`pr14_storage_vertical::fixture()`
declaration copied verbatim) with six documents committed as **three** immutable
segments over the PR 14 schema (`pr14_common::schema()`).

| Family | Query | Local-oracle assertions (all executed) |
|---|---|---|
| (i) typed-only | `AND[Range(n) 0..=100, IpInCidr(192.0.2.0/24), GeoBoundingBox(-1,-1,1,1), JsonPathRange($.n) 0..=100]`, explicit `n` descending sort | keys `["d5","d3","d1","d0"]`, `total_hits == 4`, per-hit key/score/fields and aggregation identical remote vs local |
| (ii) mixed lexical+typed | `AND[Term(title,"alpha"), Range(n), AND[JsonPathRange($.n), GeoBoundingBox]]` on relevance order | `total_hits == 4`, key set `{d0,d1,d3,d5}`, per-hit key/score/fields identical remote vs local |
| (iii) three-slot serial batch | slot 0 typed-only (`n` desc, top 2), slot 1 mixed (top 10), slot 2 mixed + aggregation (`host` group, `count`, `sum(n)`) | every slot compared field-by-field against `execute_batch` on the local index; typed slot keys `["d5","d3"]`; aggregation slot has exactly 2 groups (`h1`, `h2`) |
| (iv) pinned batch page 1→2 | mixed query, `n` ascending, page size 2, `host` aggregation | local and remote `PinnedChain` equal: pages `[["d0","d1"],["d3","d5"]]`, `total_hits == 4` on both pages, aggregation identical on both pages, aggregation page-invariant |

`a05_batch_and_cursor_oracle` repeats pinned pagination for page sizes 1, 2, 3
and 4 on the same frozen generation, and for each size asserts: exact page count
(`ceil(4/page_size)`), first-page size, non-overlapping pages, exact union
`{d0,d1,d3,d5}`, identical totals on every page, page-invariant aggregation, and
local/remote chain equality. Cursor-continuation on the immutable pin is
therefore independently verified, not merely "no GET".

`a06_wrong_generation_guard` (A07) commits three segments, opens a cold reader
(`generation == Some(3)`), pins it, then performs a real `upsert` of `d0`
(`title="delta"`, `host="h9"`) plus a commit, and opens a **second** cold reader
on the new committed generation:

- the new generation is strictly newer and a `title=delta` query returns 0 hits
  on the old pin and exactly 1 (`d0`) on the new reader;
- the new reader projects the mutated `host="h9"` stored value;
- the old pinned generation's page chain is byte-for-byte unchanged across the
  mutation, and the new pinned chain differs;
- after warmup, old-pin mixed/pinned queries and new-reader batch/mixed queries
  all leave `get_calls` unchanged.

## 4. Commands and results (Phase A)

| Command | Result |
|---|---|
| `cargo test -p quervant-core --test pr14g_remote_zero_get` | PASS — `5 passed; 0 failed; 0 ignored` |
| `cargo test -p quervant-core --all-features --test pr14g_remote_zero_get` | PASS — `5 passed; 0 failed; 1 ignored` (real test ignored as designed) |
| `cargo +1.85.0 test -p quervant-core --test pr14g_remote_zero_get` | PASS — `5 passed; 0 failed` |
| `cargo +1.85.0 test -p quervant-core --all-features --test pr14g_remote_zero_get` | PASS — `5 passed; 0 failed; 1 ignored` |
| `QUERVANT_RUSTFS_* cargo test -p quervant-core --all-features --test pr14g_remote_zero_get -- --ignored --nocapture --test-threads=1` | PASS — `real::a02_real_rustfs_zero_get_after_warmup` `1 passed`, provider digest `sha256:1803faef…b6a3c`, version `1.0.1` |
| same real command with `cargo +1.85.0` | PASS — `1 passed`, identical counter trace |

Environment for the real commands (disposable harness values, never committed):
`QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000`,
`QUERVANT_RUSTFS_BUCKET=quervant-pr14g`,
`QUERVANT_RUSTFS_REGION` unset → `us-east-1`, credentials from the pinned
container environment.

## 5. Row dispositions

| CW row | Prior generation | Disposition after Phase A | Evidence |
|---|---|---|---|
| 018 | §3 `I13` no query-time remote GET after snapshot open | `PASS` | `a01`, `a03`, `a05`, `a06` (fake, exact GET count) and `a02` (real, GET-only transfer count), stable + MSRV |
| 058 | §5.3 `I12` same boundary for corrective search/batch | `PASS` | `a01`/`a05` three-slot serial batch (typed, mixed, aggregation) with local slot parity, `+0` GETs on both boundaries |
| 073 | §5.4 `I13` same boundary for final-design unified/pinned paths | `PASS` | `a01`/`a05`/`a02` pinned page 1→page 2 chains on one frozen generation, `+0` GETs |

No other historical row changes state in Phase A. CW-055/068 are Phase B;
CW-041/127 remain human decisions; CW-087 remains open until the consolidated
final gates and independent review.

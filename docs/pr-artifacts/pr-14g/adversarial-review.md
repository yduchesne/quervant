# PR 14G — adversarial review (negative proofs, assumptions, residual risk)

**Status:** self-review by the implementing agent. **This is not independent
review** and is not treated as approval. The two human decisions are recorded
from PR #70 comment `6458408816`; `CW-087` remains `BLOCKED`. PR 14 remains
**NOT ACCEPTED**.

The purpose of this document is to record the attacks the implementation was
subjected to, the negative controls that prove a passing test is meaningful, and
the assumptions/limitations a reviewer must re-check.

## 1. Attacks that must fail (and are proven to fail)

| # | Attack | Where proven | Observed |
|---|---|---|---|
| N1 | Instrumentation silently reports zero GETs (a counter stuck at zero would make the whole invariant vacuous) | `a01_fake_remote_zero_get_after_warmup` positive control; `a03_positive_control_detects_remote_get` | Cold open of three committed segments strictly increases `get_calls` (`11 → 17` including warmup; `a03` requires ≥3). A real cold open yields `TransferStats::requests()==3` with `whole+range==3` |
| N2 | A nonzero GET delta is accepted because the checker is broken | `a04_counter_boundary_rejects_query_get` | A test-only injected `store.get` (non-existent key → `NotFound`) advances the counter by exactly 1, and `check_no_get` returns `Err("… advanced from … to …")` |
| N3 | The remote test passes without actually materializing anything (empty snapshot) | `a01`/`a02`/`a05`/`a06` | `generation == Some(3)`, `segment_count() == 3`, exact key totals (`4` matches), aggregation groups and stored projections are asserted |
| N4 | "Zero GET" achieved by doing no work / returning nothing | `a01`, `a05`, `a02` local-oracle parity | Every family is compared against an equivalent local `Index` snapshot: totals, key order, per-hit fields, scores, aggregation and cursor pages must agree |
| N5 | Pinned page 2 silently restarts page 1 or drops rows | `a01` (page size 2: `[d0,d1]` then `[d3,d5]`), `a05` (page sizes 1–4) | Non-overlap, exact union `{d0,d1,d3,d5}`, page counts `ceil(4/page_size)`, identical `total_hits` on every page |
| N6 | Old and new committed generations are confused (stale snapshot reused) | `a06_wrong_generation_guard`; Phase B `g_b02`/`g_b03` | Old pin keeps `title=delta` at 0 hits and unchanged pinned pages; new reader sees the mutation and strictly newer generation |
| N7 | Projection rescans by logical key instead of the selected physical hit | `g_b01`, `g_b05`, `g_b04` | `g_b01` compares each hit with the oracle derived from its own `(segment_index, doc_id)` in selected (non-key) order; `g_b05` proves the key-latest shortcut produces a **different** value after upsert; `g_b04` proves a key/PHYSICAL mismatch raises `CorruptIndex` |
| N8 | A test-only "corruption" hides real data corruption | `g_b04` | Only a cloned in-memory `SelectedHit` is altered; persisted bytes, segments and production selector internals are untouched |
| N9 | Phase B tests pass because the fresh snapshot is never opened (stale `Index` handle) | `g_b02`/`g_b03`/`g_b05` | Each mutation test reloads via `Index::open_existing` and asserts `new_index.generation() > index.generation()`; the stale-handle bug was found and fixed during development (the tests failed before the fix) |
| N10 | The new tests are green because a production behaviour was changed to fit them | diff audit | `search/unified.rs` diff is a single additive hunk inside `mod tests` (`0` removed lines); no production item changed |
| N11 | PR 14F benchmark reuse conceals a changed measured path | diff audit | PR 14G changes no production query/remote-cache/workload code; the 14F qualification remains valid (X25). No fresh trial is claimed |
| N12 | Coverage passes by excluding code or skipping tests | validation report; `ci.yml` command used verbatim | No `#[ignore]` added, no exclusion introduced, 85 % floor unchanged; measured 91.37 % lines |

## 2. Assumptions that a reviewer must re-verify

1. **Counter semantics.** `FakeObjectStore::get_calls` increments per
   `ObjectStore::get` attempt (fake.rs:321) — exact for the fake.
   `TransferStats::requests` increments per budgeted GET attempt
   (transfer.rs:513) and is never touched by PUT/HEAD/LIST; metadata GETs in
   `hydrate`/`fetch_verified` bypass it. The real zero-GET claim is therefore
   scoped to segment (re)materialization; the fake covers all GETs.
2. **Snapshot residency.** `ReaderSnapshot` holds resident segment bytes
   (`SegmentSnapshot.bytes`), which is why warm queries need no provider access.
   A future partial/range-cached segment design would invalidate this proof and
   require a new test.
3. **Fake capabilities.** The fake advertises
   `IMMUTABLE_BASELINE.with_conditional_replace(true)`, matching the publication
   path's CAS requirement. A fake advertising different capabilities would take
   different code paths.
4. **Segment layout.** The Phase A corpus commits three separate segments; the
   real counter ties `whole+range == 3` to that layout. Merging/compaction
   behaviour changes would change the number (the assertion would fail loudly,
   not silently pass).
5. **Local oracle independence.** Phase A compares the remote snapshot with a
   *local* `Index` built from the same document stream — the comparison is only
   as strong as the local engine, which is itself covered by the pre-existing
   PR 7/14 suites.
6. **Phase B fixture backend.** Phase B uses `MemoryDirectory`; segment bytes are
   resident, so the physical-identity proof isolates projection semantics rather
   than filesystem behaviour. Filesystem/restart/persistence behaviour is covered
   by the existing PR 6/13/14 suites, which pass at this head.
7. **Deterministic ties.** Tie ordering relies on the documented
   relevance comparator (score desc, then key asc). The test asserts the actual
   observed order rather than assuming insertion order.
8. **Clock/deadline values.** Pinned tests use fixed `now=1_000`,
   `deadline=10_000` microseconds; cursor expiry semantics are covered by
   negative tests in the pre-existing PR 14A/14D suites, not re-derived here.
9. **Provider identity.** The pinned digest/health were read from the running
   container; the tests fail closed when the environment is absent. No mock
   provider was substituted.
10. **CI binding.** No GitHub check run exists at the PR 14G head because the
    workflow triggers only on `pull_request`/`push: main` and PR creation needs an
    authenticated token that is invalid here. CI is `PENDING`, never `PASS`.

## 3. Residual risks (not closed by this PR)

| Risk | Impact | Mitigation / owner |
|---|---|---|
| Metadata GETs are outside the real counter | A future query path that re-reads `CURRENT`/manifest remotely would not be detected by the real counter (the fake would catch it) | maintain the fake test as the primary oracle; add a metadata counter only via an approved design |
| `R-14A-JSON-MEM` uncharged transients | One decoded `JsonOccurrence` and the legacy walker stack remain uncharged bounded pre-admission transients; the meter is a logical ledger, not RSS | **accepted for PR 14 only** by the maintainer (PR #70 comment `6458408816`); the risk is not eliminated and the acceptance is not a physical-memory guarantee |
| `X01–X13` undefined | Per-ID claims cannot be verified or reproduced | **family-level supersession (X-B)** authorized by the maintainer; no per-ID test exists and none is claimed |
| Mis-transcribed human decision | A wrong transcription would silently widen the acceptance | source is the immutable PR #70 comment `6458408816`; §0 of `maintainer-decisions.md` quotes it verbatim, and the derived counts (`112/12/2/1`) are mechanically asserted |
| No independent review | Self-review cannot substitute for external scrutiny | reviewer/maintainer action |
| No exact-head CI | CI result unknown for the PR head | maintainer with valid credentials must open the PR and observe `rust`/`msrv`/`rustfs` |
| Phase B fixtures are in-memory | Real-filesystem physical identity is inferred from resident bytes | covered by existing fs/remote suites; note as a scope limit |
| Provider environment is local | No AWS S3 (TLS) end-to-end test in this PR | unchanged v0.1 policy; scheduled release CI owns real AWS tests |

## 4. What would falsify the Phase A claim

- Any warmed family advancing the fake `get_calls` (would fail `require_no_get`);
- a cold open that leaves `get_calls` unchanged (`a03` fails);
- an injected GET that is not detected (`a04` fails);
- remote results differing from the local oracle in totals, order, fields,
  scores, aggregation or cursor pages;
- a pinned page 2 that overlaps, drops or repeats rows.

## 5. What would falsify the Phase B claim

- `project_selected_hits` fields differing from the physical-record oracle at
  any position;
- old/new PIT tuples equal after a real upsert (`g_b02`);
- the deleted key appearing in the newer generation (`g_b03`);
- a mismatched key not producing `SearchError::CorruptIndex` (`g_b04`);
- the key-latest shortcut reproducing the retained old physical projection
  (`g_b05`).

## 6. Reviewer checklist

1. Confirm the diff scope (`git diff --stat`, and `git diff -U0
   crates/quervant-core/src/search/unified.rs | grep '^-'` → none).
2. Re-run the fake Phase A suite and the Phase B unit tests.
3. Re-run the real Phase A test against a pinned provider; verify the provider
   digest and that `whole+range == 3` corresponds to three segments.
4. Re-run the workspace matrix and coverage commands from `validation-report.md`
   (the table lists the exact commands and observed exit codes).
5. Re-check the 127-row crosswalk count mechanically (script in
   `acceptance-crosswalk.md` §2).
6. Compare `maintainer-decisions.md` §0 against PR #70 comment `6458408816` word
   by word, confirm the derived row states (`CW-041` = `SUPERSEDED WITH EVIDENCE`,
   `CW-127` = `PASS`, `CW-087` = `BLOCKED`) and confirm that
   `final-acceptance.md` remains `NOT ACCEPTED`.

# PR 14E — blocked-row dossiers

One dossier per historical `BLOCKED` row: 18 rows, matching the PR 14C totals.
Each dossier records the previous state, the gap, the evidence actually examined
in PR 14E, the action taken, the current status and the owner/dependency for
closure. Crosswalk row numbers (`CW-###`) refer to
[acceptance-crosswalk.md](acceptance-crosswalk.md).

Status vocabulary per dossier: **CLOSED (evidence)** — the historical gap is
now directly evidenced; **CARRIED (blocked)** — still not provable without work
outside this documentation PR; **CARRIED (deferred)** — owned by PR 14F.

| Dossier | Historical row | CW | Status | Owner |
|---|---|---|---|---|
| D-01 | §3 `I13` zero query-time remote GET | 018 | CARRIED (blocked) | separate instrumentation/test approval |
| D-02 | §4.2 `J14` old-segment JSON fallback | 024 | **CLOSED (evidence)** | — |
| D-03 | §4.2 `J15` legacy segments | 025 | **CLOSED (evidence)** | — |
| D-04 | §5.3 corrective `I07` exact `HitRef` projection identity | 055 | CARRIED (blocked) | separate test-only approval |
| D-05 | §5.3 corrective `I12` zero-GET instrumentation | 058 | CARRIED (blocked) | separate instrumentation/test approval |
| D-06 | §5.3 corrective `I16` final-SHA CI | 060 | **CLOSED (evidence)** | — |
| D-07 | §5.4 final-design `I8` exact physical hit identity | 068 | CARRIED (blocked) | separate test-only approval |
| D-08 | §5.4 final-design `I13` no query-time remote GET | 073 | CARRIED (blocked) | separate instrumentation/test approval |
| D-09 | §6 phase `14F` real boundary + faults + benchmarks | 086 | CARRIED (deferred) | PR 14F |
| D-10 | §6 phase `14G` final gates, CI, docs | 087 | CARRIED (blocked) | PR 14F + maintainer |
| D-11 | §7.1 `V11, V12` benchmark oracle + three trials | 092 | CARRIED (deferred) | PR 14F |
| D-12 | §7.4 `B01` correctness oracle before timing | 114 | CARRIED (deferred) | PR 14F |
| D-13 | §7.4 `B03` three independently qualified trials | 116 | CARRIED (deferred) | PR 14F |
| D-14 | §7.5 `W01–W07, W09` measured lanes | 118 | CARRIED (deferred) | PR 14F |
| D-15 | §7.6 `Q01–Q06 / Q01–Q09` CI Q-gates | 120 | **CLOSED (evidence)** | — |
| D-16 | §4.6 `X01–X13` per-ID oracle matrix | 041 | CARRIED (blocked) | maintainer decision |
| D-17 | §8 item 6 benchmarks | 126 | CARRIED (deferred) | PR 14F |
| D-18 | §8 item 7 JSON temporary memory (`R-14A-JSON-MEM`) | 127 | CARRIED (blocked) | maintainer risk-closure signoff |

---

## D-01 — original `I13`: zero query-time remote GET

| Field | Value |
|---|---|
| Previous state | PR 14C §3 `I13`: "No dedicated instrumentation exists; 14B notes it as unimplemented" → `BLOCKED` |
| Historical obligation | During query execution, no remote object GET occurs; all remote reads belong to snapshot open, manifest verification or segment materialization/cache warmup |
| Gap claimed in 14C | No instrumentation boundary existed to prove the property |

**Examined in PR 14E**

- `crates/quervant-core/src/remote/transfer.rs:197` `TransferStats`
  (`requests`, `bytes`, `retries`, `range_requests`, `whole_requests`,
  `peak_retained_bytes`) — per-instance atomic counters.
- `crates/quervant-core/src/remote/mod.rs:215,487` `transfer_stats()`.
- `crates/quervant-objectstore/src/fake.rs:162–185` `get_calls()/put_calls()/
  delete_calls()/reset_counters()`.
- Executed zero-GET assertions that already exist:
  - `crates/quervant-core/tests/pr13_remote.rs:162–205`
    `v01_lexical_results_match_local_oracle` — `reset_counters()`, then 4 lexical
    queries, then `assert_eq!(store.get_calls(), 0, "no remote GET during scoring")`.
    **Non-ignored; re-executed in PR 14E.**
  - `crates/quervant-core/tests/pr13_oracle.rs:535–542` O09 inside
    `o07_pit_and_o08_mutations_and_o10_explicit_commit` — real RustFS
    `stats.requests()` frozen across `check_expectations` (`#[ignore]`, historical
    evidence only).
  - `crates/quervant-core/tests/pr13_bench_remote.rs:355–362` — warm scoring
    `stats.requests()` unchanged (`#[ignore]` benchmark lane).
- Source inspection of `search/unified.rs` search path: `open_segment_reader`,
  `doc_key`, `stored_doc` and `plan.project` only; no remote object access. This
  is an inspection, **not** proof of the counter-level property.

**Action taken.** No code and no test added (docs-only PR; EAD-01, decision
X10/X27). The rows stay `BLOCKED`.

**Why it stays blocked.** The historical gate concerns PR 14 query execution
(typed, mixed, batch, pinned cursor). Every existing counter assertion exercises
the lexical `Index::search` path, optionally on a `FakeObjectStore`. No executed
test isolates the PR 14 boundary (open/cache-warm → reset/record → execute →
assert frozen).

**Required follow-up (separate approval).** Add a test-only case (no production
change needed, since the counters already exist):

1. Cold-open a `RemoteIndex` (real provider and/or `FakeObjectStore`), complete
   manifest verification and segment materialization, and run one warm query.
2. Record `stats.requests()` (real) or `reset_counters()` (fake) **after** the
   open/warmup boundary.
3. Execute: a typed-only `UnifiedSearcher::search`, a mixed lexical+JSON/IP/geo
   search, a 3-slot `execute_batch`, and `execute_batch_pinned` including a
   page-2 cursor.
4. Assert the counter delta is exactly `0` for every query, and separately assert
   that the cold open/cache-fill window itself did increment the counter (so a
   broken counter cannot pass vacuously).

Suggested locations: a non-ignored variant in
`crates/quervant-core/tests/pr14_storage_vertical.rs` plus an
`#[ignore]`d real-provider variant; no public API change.

---

## D-02 — `J14`: old-segment JSON fallback

| Field | Value |
|---|---|
| Previous state | PR 14C §4.2 `J14`: "No dedicated PR 14 test; historical PR 11 fallback suites only" → `BLOCKED` |
| Historical obligation | A JSON-path predicate on a segment that predates the JSON-path section must use the bounded stored-source fallback; if the field is not stored, it must fail typed instead of guessing |

**Examined in PR 14E**

- `crates/quervant-core/src/search/typed.rs:1169–1179` documents the contract:
  "For a segment with a JSON-path section it decodes only the requested
  document's occurrences. For a legacy segment without the section it uses a
  bounded, exact stored-source fallback, and fails typed when the field is not
  stored."
- `crates/quervant-core/src/search/typed.rs` `mod legacy_json_tests`:
  - `legacy_json_tests::legacy_source_fallback_and_unstored_error` — builds a
    segment with the `FEATURE_JSON_PATHS` requirement and `SectionKind::JsonPaths`
    section removed using the **production** `SegmentBuilder` + `ContainerBuilder`
    layout, opens it with the production `SegmentReader`, asserts
    `JsonAccess::open(...).paths.is_none()`, asserts a matching stored-source
    fallback (`$.v` → true), a clean negative (`$.nope` → false), and a typed
    `SearchError::UnsupportedOperator` for the indexed-but-not-stored
    `indexed_only` field.
  - `legacy_json_tests::b1_legacy_source_fallback_wide_field` — 2,000-member
    document, bounded exact fallback (`$.w01999` → true, `$.missing` → false).
- Related: `pr11_json_corruption::t14_negotiation_and_corruption_fail_closed`
  proves a legacy container with neither feature nor section still opens cleanly.

**Action taken.** Executed both `legacy_json_tests` cases and the related PR 11
case at current head (see `validation-report.md`, E14E-09); adjudicated `J14` as
**PASS**.

**Scope limitation (recorded, not a blocker).** The legacy container is
synthesised by stripping the section from a current segment rather than being a
checked-in pre-PR-11 artifact, and the assertion drives the production
`JsonAccess` accessor rather than `UnifiedSearcher`. The mandated elements
(old-segment shape, stored-source fallback, typed failure for unstored
unsupported) are all directly asserted. An end-to-end `UnifiedSearcher` legacy
fixture would strengthen this and is *not* claimed.

---

## D-03 — `J15`: legacy segments

| Field | Value |
|---|---|
| Previous state | PR 14C §4.2 `J15`: "No dedicated PR 14 test; covered indirectly by PR 11 legacy suites" → `BLOCKED` |
| Historical obligation | Genuine historical segments must still decode correctly, or fail typed (corruption, unsupported version) — never be reinterpreted |

**Examined in PR 14E**

- `crates/quervant-core/tests/pr14_storage_vertical.rs` `b18_b19_historical_json_segment_compatibility`
  (non-ignored, executed):
  - frozen artifact `tests/fixtures/segment/json_paths_golden.seg` checked in by
    commit `65f7440` (PR 11 Phase 0), SHA-256
    `0528a62cdb02fcd08754d5776f23bd16de787f788597ade93d5dfbc65c30a02f`;
  - the current writer reproduces the artifact **byte-identically**
    (`guard.reader().bytes() == GOLDEN`);
  - decoding yields the expected predicate/projection table (`$.v == 2` → `b`);
  - a flipped payload byte is rejected; format major `1 → 2` yields
    `SegmentError::UnsupportedFormatVersion { major: 2, minor: 0 }`.
- `crates/quervant-core/tests/pr11_json_corruption.rs` `t14_negotiation_and_corruption_fail_closed`
  — legacy (no feature, no section) opens cleanly; feature-without-section and
  section-without-feature fail closed; digest/version/trailing-byte corruption
  rejected.
- `crates/quervant-core/tests/pr14d_json_sort_memory.rs`
  `d07_historical_fixture_digest_and_corruption` — the same frozen fixture digest
  is unchanged and a corrupted byte fails at open with the typed error.
- Related real-provider case `real::b18_real_historical_json_remote` (PR 14D,
  `REUSE-14D`) exercises the frozen artifact through a remote provider.

**Action taken.** Executed the local cases at current head (E14E-09); adjudicated
`J15` as **PASS**.

**Scope limitation (recorded).** JSON wire **v1** only. No cross-version
migration of an older supported wire version is claimed (none exists).

---

## D-04 — corrective `I07`: exact `HitRef` projection identity

| Field | Value |
|---|---|
| Previous state | PR 14C §5.3 corrective `I07`: "Projection tallies states/order; no direct assertion found" → `BLOCKED`; original definition (pr-14 corrective traceability): "exact `HitRef` projection | P03–P06 | NOT IMPLEMENTED (rescan still key-based)" |
| Historical obligation | The projected fields must come from the exact physical hit that was selected (a `HitRef`), not from a key-based rescan |

**Examined in PR 14E**

- `crates/quervant-core/src/search/unified.rs` — `SelectedHit { segment_index,
  doc_id, key, score, … }`; `collect_mixed` produces it; `search` calls
  `project_selected_hits(self.snapshot, projection, ledger, &page, …)`.
- `project_selected_hits` (same file) is documented "Projection using exact
  physical `(segment_index, doc_id)` identities": it groups hits by
  `segment_index`, opens that segment reader, checks
  `reader.doc_key(hit.doc_id) == hit.key` (else `SearchError::CorruptIndex`), then
  `reader.stored_doc(hit.doc_id)` and `plan.project(&record)`.
- `crates/quervant-core/tests/pr14_f1_hardening.rs`
  `p02_projection_uses_current_version` — after upsert + commit, the projected
  `host` must be the new value. Executed; proves *current-version* projection,
  but a key-based rescan against the same snapshot would also satisfy it.
- Repo-wide search for `HitRef`: **no such type exists** in `crates/**`; the
  obligation's named artifact was never implemented as a public type.

**Action taken.** Source inspection only; no test, seam or API added (EAD-01,
decision X11/X27). Row stays `BLOCKED`.

**Why it stays blocked.** EAD-09 requires an observable assertion tying the
selected physical hit to the projected fields. The implementation appears to
satisfy the invariant, but no executed assertion distinguishes physical
projection from a key-based rescan, and no public `HitRef` exists to assert on.

**Required follow-up (separate test-only approval).** Either
(a) add a `#[cfg(test)]`/crate-private accessor or unit test inside
`search/unified.rs` that drives `collect_mixed` + `project_selected_hits` and
asserts, for each hit, `snapshot.open_segment_reader(hit.segment_index)
.reader().doc_key(hit.doc_id) == hit.key` **and** that the projected fields equal
the oracle built from that same `(segment_index, doc_id)`, including an
upsert + PIT-old/new case where the stale physical doc holds a different value;
or (b) obtain maintainer approval to define and publish a `HitRef` contract
(API change — requires its own design review). Under this docs-only PR neither is
permitted.

---

## D-05 — corrective `I12`: zero-GET instrumentation

Identical boundary gap, evidence and proposal to **D-01**; the historical row is
the corrective-generation statement of the same requirement (CW-058). Kept
`BLOCKED` for the same reason: the counters exist, the PR 14 query boundary is
never asserted.

---

## D-06 — corrective `I16`: final-SHA CI

| Field | Value |
|---|---|
| Previous state | PR 14C §5.3 corrective `I16`: "Final-SHA CI | Not observed" → `BLOCKED` due to an invalid `gh` token and no observed run |
| Historical obligation | Green `rust`, `msrv`, `rustfs` checks on the final head of the PR 14 line |

**Examined in PR 14E (immutable records, public GitHub API)**

| SHA | Role | `rust` | `msrv` | `rustfs` | Run / job URLs |
|---|---|---|---|---|---|
| `a61f0b8ed97be48235f9583c9b4dd6d8755c36bc` | PR #62 (PR 14C) head | success | success | success | `actions/runs/40135692802` |
| `635c7f4a89c5e2e9478da23c2a533e8dc1f80e09` | PR #64 (PR 14D) head | success | success | success | `actions/runs/40326618997` |
| `6d18ebed4c2a8c7d73ca9e5078019d50546cb675` | PR #64 merge | success | success | success | `actions/runs/40361560578` |
| `dc506f6ee28014e64fbc9070db6925b73063d9ba` | `main` head | success | success | success | `actions/runs/40361657335` |
| `e0e1dcbff9ab72288945c424c44fbabd008f4416` | local corrective preflight head (never pushed) | — | — | — | `total_count: 0` |
| `d0e1bbbd841feff6615d7824dd3261a2418511f7` | PR 14D implementation commit (pre-fixup, superseded) | — | — | — | `total_count: 0` |

**Action taken.** Adjudicated **PASS** at the level the row states ("final-SHA
CI"), with the explicit scope below.

**Scope (binding).** The claim is: *the final SHA of the PR 14 line, as merged,
has green `rust`/`msrv`/`rustfs` checks.* It is **not** a claim that CI ran on the
never-pushed local corrective commits; those show zero check runs and are
superseded by merged `main`. EAD-14 is respected: nothing here retroactively
assigns the newer checks to `e0e1dcb` or `d0c445a`.

---

## D-07 — final-design `I8`: exact physical hit identity

Same requirement as **D-04**, recorded in the final-design generation (CW-068).
Examined evidence additionally includes
`crates/quervant-core/src/search/unified.rs` line-level documentation
("Every internal match carries `SelectedHit { segment_index, doc_id, key, … }`")
and the same `project_selected_hits` guard. No executed assertion distinguishes
physical selection from a key-based rescan across duplicate stable keys, upsert,
delete or PIT old/new views; `HitRef` does not exist. Status: `BLOCKED`, same
follow-up as D-04. Note that upsert cannot leave two *live* physical documents
with the same key, which is precisely why the assertion must be built on the
selected physical identity rather than on output equality.

---

## D-08 — final-design `I13`: no query-time remote GET

Same requirement and evidence as **D-01/D-05** (CW-073). `BLOCKED`; same
follow-up proposal.

---

## D-09 — phase `14F`: real-boundary RustFS + faults + benchmarks

| Field | Value |
|---|---|
| Previous state | PR 14C §6: `14F` → `BLOCKED` (benchmark component) |
| Historical obligation | Real-boundary provider verticals, fault matrix and the qualified P4 benchmark lanes |

**Examined in PR 14E**

- Real-boundary and fault components already have immutable evidence in merged
  PR 14D: 13 real RustFS verticals, `pr14_storage_faults` F01–F09/F10 × 10
  iterations, PR 13 proxy/crash/objectstore/remote/oracle suites, pinned image
  digest `sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`
  (`rustfs:1.0.1`). **Cited, not re-executed** in PR 14E (no provider started).
- Benchmark component: **0 of 3** qualified trials
  (`benchmarks/workloads/pr14_p4_v1.md`, `validate-pr14-p4.py`, W08 exemption).

**Action taken.** No benchmark run; `BLOCKED` carried.

**Owner / next gate.** PR 14F owns fresh qualified trials (see
[benchmark-dependency.md](benchmark-dependency.md)). Because the row is a phase
gate, it cannot be satisfied by evidence alone: a fresh, correctness-gated,
idle-attested trial is required.

---

## D-10 — phase `14G`: final gates, CI, docs

| Field | Value |
|---|---|
| Previous state | PR 14C §6: `14G` → `BLOCKED` (CI component) |
| Historical obligation | Final gates: local gates, CI on the final head, documentation closure |

**Examined in PR 14E**

- CI component: **closed** by the immutable check runs in D-06/D-15.
- Local gate component: re-executed at current head (`validation-report.md`).
- Documentation component: this PR 14E artifact set.
- Remaining: risk-closure signoff (D-18), fresh benchmarks (D-09), independent
  review and PR 14 acceptance.

**Action taken.** `BLOCKED` carried; the CI sub-component is marked verified in
the rationale rather than converting the phase gate into a pass.

---

## D-11 — `V11, V12`: benchmark oracle + three qualified trials

| Field | Value |
|---|---|
| Previous state | PR 14C §7.1: `BLOCKED` — "Benchmark oracle + three qualified trials not run in 14C; validator self-test PASS" |
| Historical obligation | `B01–B04`-backed benchmark oracle and three independently qualified trials |

**Examined in PR 14E.** Validator self-test re-executed (`PASS`); W08 exemption
manifest present and required; no trial executed. Historical trials at source
`ab9b2d7da066ec80190dcee70a8cebfd81481b80` (138+ commits behind) remain
**provenance only** and were not relabelled.

**Action taken.** `BLOCKED — PR 14F`; ledger in
[benchmark-dependency.md](benchmark-dependency.md).

---

## D-12 — `B01`: correctness oracle passes before timing

`BLOCKED — PR 14F`. The oracle is defined in `pr14_p4_v1` (hand-derived expected
counts per lane) and is asserted before timing by the harness, but no fresh trial
has executed it in the current acceptance line. Decision X18 applies.

---

## D-13 — `B03`: three independently qualified trials

`BLOCKED — PR 14F`. Requires 3 independent trials, each with `--idle-confirmed`
operator attestation, `contention=clear`, clean tree at the recorded SHA, real
RustFS adapter exercised, 3 warmups / 20 samples per lane and the W08 exemption
manifest. Zero completed in this line.

---

## D-14 — `W01–W07, W09`: measured lanes

`BLOCKED — PR 14F`. No lane was re-measured. Historical `ab9b2d7` values are
provenance only. `W08` is separately `NOT APPLICABLE (APPROVED)` and is never
counted as a measured lane.

---

## D-15 — `Q01–Q06 / Q01–Q09`: CI Q-gates

| Field | Value |
|---|---|
| Previous state | PR 14C §7.6: `BLOCKED` — "No PR/CI run exists; `gh` token invalid" |
| Historical obligation | A pushed PR with CI on the exact head |

**Examined in PR 14E.** Exact-head check runs, all `completed/success` for
`rust`, `msrv`, `rustfs`:

| PR | Head SHA | Run |
|---:|---|---|
| #61 | `6cb6d47bc7ab185f1934b94a805ccfaf19541fa3` | `actions/runs/40122922869` |
| #62 | `a61f0b8ed97be48235f9583c9b4dd6d8755c36bc` | `actions/runs/40135692802` |
| #63 | `4097a02a9d8551d9e9be377220b44af012fc63c8` | `actions/runs/40136120377` |
| #64 | `635c7f4a89c5e2e9478da23c2a533e8dc1f80e09` | `actions/runs/40326618997` |
| #65 | `b66f817bdff15fe58d867e611fb84f312ceabcb7` | (merged; see main run) |

Merge/`main` heads `376023b`, `2cb91be`, `6d18ebe`, `dc506f6` are also green.

**Action taken.** Adjudicated **PASS at family level**, exactly as the historical
row was recorded (a family gate, not per-ID).

**Scope (binding).** No per-ID `Q01…Q09` check definitions exist in the
repository (`docs/pr-artifacts/pr-14/remaining-*`, `corrective-*` record only the
family). PR 14E therefore does **not** claim Q01, Q02 … individually; it claims
the family requirement "pushed PR + CI on the exact head" is met by the immutable
records above. If the maintainer requires per-ID Q verification, that needs the
missing definitions (same treatment as D-16).

---

## D-16 — `X01–X13`: independent oracle matrix

| Field | Value |
|---|---|
| Previous state | PR 14C §4.6: `BLOCKED` — "no per-ID definitions recorded; an exact ID mapping cannot be asserted without inventing one" |
| Historical obligation | Independent local / `FakeObjectStore` / real-RustFS oracles, per ID |

**Examined in PR 14E (searched, not hypothesised)**

- `docs/pr-artifacts/pr-14/test-traceability.md:63` — the only description:
  "X01–X13 independent local/FakeObjectStore/real-RustFS oracles: local oracles
  only; FakeObjectStore/RustFS verticals not executed."
- `docs/pr-artifacts/pr-14/corrective-test-traceability.md:17` uses `X01` for
  "mixed Boolean equivalence" (`I01`) and `:24` uses `X01–X10` for "RustFS oracle
  equivalence" (`I14`) — contradictory reuse, no definitions.
- Git history: `git log --all -S"X01" -- docs/` → `fa82db7`, `d0c445a`,
  `e0e1dcb`; no commit contains an `X01…X13` definition table
  (`git ls-tree`/`git show` inspected for `d0c445a`).
- No definition exists anywhere else in `docs/` (grep for `X01` returns only
  these families).

**Action taken.** No mapping invented (EAD-07). `BLOCKED` carried; decision X09
applies.

**Maintainer options (explicit, not preselectable by the agent)**

1. Recover the authoritative `X01–X13` definitions from an external record and
   provide them for a later reconciliation PR.
2. Approve a scoped exception stating that the `X` matrix is superseded at family
   level by the executed local/provider oracle evidence (§7.2, §7.3, PR 14D
   verticals), with the provenance and scope written into an approved decision.
3. Commission a new, explicitly versioned `X` mapping contract in a separately
   approved (possibly test-only) PR.

---

## D-17 — `§8` item 6: benchmarks

Duplicate of D-11/D-13/D-14 at the mapping-table level (CW-126). `BLOCKED — PR
14F`.

---

## D-18 — `§8` item 7: JSON temporary memory (`R-14A-JSON-MEM`)

| Field | Value |
|---|---|
| Previous state | PR 14C §8 item 7: "B20/B21 characterization; human decision `REQUIRE SEPARATE CORRECTION`" → `BLOCKED` (risk not accepted) |
| Historical obligation | Correct the unmetered JSON-sort transient allocation **and** obtain human acceptance of the corrected risk |

**Examined in PR 14E**

- Human decision record: `docs/pr-artifacts/pr-14c/resource-risk-disposition.md`
  §5 — `REQUIRE SEPARATE CORRECTION`, literal instruction "proceed with option 2",
  dated 2026-10-24, bounded scope "PR 14 acceptance (blocked until corrected)",
  "Accepted bounds: NONE".
- Corrective implementation: `search/typed.rs` now reserves occurrence capacity
  before growth (`push_occurrence`), charges owned path/member/node payloads,
  compares borrowed scalar nodes, reserves `JsonSortBuffer::Winner` bytes, and
  materializes the winner exactly once (`materialize_json_sort_winner`).
  Implementation commit `d0e1bbb`; admission-order fixup `3f82284`; reviewed head
  `635c7f4`; merged to `main` as `6d18ebe`.
- Re-characterization: `docs/pr-artifacts/pr-14d/resource-characterization.md` —
  logical thresholds `387 / 45,726 / 1,462,302 B` (previously the constant
  `112 B`), tracked peaks `33,547 / 110,392 / 2,518,968 B`, cancellation
  `7,397 B`. Executed in this run via `pr14b_json_memory`
  (`1 passed, 1 ignored`).
- CI on the corrected head: see D-06.

**Action taken.** No Rust change in PR 14E. Row stays `BLOCKED` with corrected
work-status flags (implemented / merged / CI-verified / **not** human-accepted).

**Why not PASS.** EAD-15 and decision X20/X26: the risk is closed by a *human*
decision. The recorded decision requires the correction to land **and** remaining
PR 14 gates to clear; PR 14E may not convert an agent-observed correction into a
recorded risk acceptance.

**Next gate.** Maintainer records risk closure (with the allocator-window
limitation preserved) in a dated decision, then PR 14 acceptance can resume.

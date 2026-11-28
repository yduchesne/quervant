# PERF-07-A — Arbitrary-K selective physical document-key verification

**Document type:** detailed implementation contract for a coding agent; not an implementation report.
**Repository:** `yduchesne/quervant`
**Branch:** `dev/perf07-a`
**Base engine:** merged PERF-06-C4, `44caa511f6e147836c446b970845f03de45eb515`
**Roadmap predecessor:** PR #134, reviewed head `e7bc4cab3c433f7e6c1894e8128b0bd6e618bf5b`
**Authoring source inspection:** 2026-11-27 (Pacific), repository artifacts use UTC dates.

## 0. Execution authority, admission, and completion boundary

This plan is designed for an agent with limited reasoning capacity. The architecture, branch scope, implementation algorithm, error precedence, test inputs and expected results below are prescribed. Do not replace them with another design. The plan is governed by `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` (including §§3E, 3F and 27), `docs/TESTING.md`, and `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md`.

**Continuous execution authorization:** Once asked to execute this approved plan, proceed from admission through red-first proof, all prescribed implementation, verification, documentation, branch push and draft PR delivery without asking for routine reconfirmation. Successful checks, ordinary compiler/lint repairs expressly allowed by the matrix, and stage completions are not approval checkpoints. Apply the precise decision matrix in §12 before acting. Stop affected work for an applicable hard stop or uncovered condition; continue safe independent work only if its independence is demonstrable. Do not invent an architecture, broaden scope, weaken a check, or obtain a favorable result by changing the fixture. Do not merge or start B.

**Important current-state prerequisite:** PR #134 was OPEN, not merged, when this plan was authored. Its reviewed roadmap is available at its pinned head above. Execution must start after that documentation predecessor has merged. The author does not assume a future merge SHA. The coding agent must verify this automatically, not ask again if already merged:

1. `git fetch origin main` and inspect `gh pr view 134 --repo yduchesne/quervant --json state,mergedAt,mergeCommit,headRefOid,baseRefName`. Fetch the reviewed PR object with `git fetch origin refs/pull/134/head`; require `git rev-parse FETCH_HEAD` equals `e7bc4cab3c433f7e6c1894e8128b0bd6e618bf5b` before the tree comparison. Do not use the prospective merge ref as BASE.
2. Require PR #134 merged into `main`, its reviewed head unchanged, and the merged roadmap content exactly equal to the reviewed `e7bc4cab...` roadmap. Require `44caa511...` an ancestor of `origin/main` and `origin/main`'s **complete tree** equal to `e7bc4cab...^{tree}`. This admits merge, squash or rebase that preserves the reviewed tree; do not require the PR head to be a first-parent commit. Record `BASE=$(git rev-parse origin/main)`, full tree ID, actual merged PR SHA and timestamp. Require the source anchors in §2. If #134 is still open, stop implementation; never merge it on behalf of the maintainer. If main has other changes, stop for re-pinning instead of guessing whether they matter.
3. If the local repo is clean and `dev/perf07-a` does not exist locally/remotely, `git switch -c dev/perf07-a "$BASE"`. If it exists at exactly BASE with no prior PERF-07-A work or PR, reuse it under D03. Any other branch state follows D04. Do not reset, force push, overwrite or discard existing work. Leave disjoint pre-existing untracked files alone and record them; any overlapping or executable shadowing input is a stop.
4. Store the supplied Markdown verbatim in `docs/pr-artifacts/perf-07-a/PERF07A_DETAILED_IMPLEMENTATION_PLAN.md` at documentation closeout; record its SHA-256. Do not modify this plan to cure a contradiction encountered in execution.

This is a **code-bearing correctness-first** PR. The earlier C4 benchmark-specific QA waiver does not apply. The repository's local stable/MSRV checks, real filesystem and applicable RustFS acceptance, and 85% production line-coverage gate apply. **No timed performance acquisition, profiler, Criterion measurement campaign, cross-engine run, new benchmark configuration, or optimization acceptance claim.** Ordinary Cargo `--all-targets` test-mode benchmark smoke checks and `bench --no-run` are compilation/regression checks, not a performance acquisition. PERF-07-I owns the consolidated real warm qualification. The host is assumed usable; no stability campaign is required for these deterministic tests.

## 1. Purpose and required observable outcome

C4 is merged, with C2's strict term collector, B1/B2 numeric sort ordinals, B3 compact candidate identity, and C3 winner-only scoring retained. A fixes the projection path **after selection**. `project_selected_hits` opens a fresh query-local reader for each segment represented in the selected results. In the ordinary multi-hit branch, the first `reader.doc_key(doc_id)` constructs the entire `Vec<DocumentKey>` using `doc_keys()`, even when only 10 or 100 of N physical records will be returned. That full-cache allocation belongs to this newly opened reader and is thrown away after projection.

A must eliminate this repeated full-key reconstruction, without removing the physical-key identity check. The exact new behavior is:

| Path | Full DOC_KEYS decoder calls | Full owned key construction | Full validating scans per selected segment | Direct selected-key reads |
|---|---:|---:|---:|---:|
| Current ordinary projection, K >= 2, fresh wrapper | 1 | N | Full decoder traverses N | K clones from full cache |
| A: already certified offsets | 0 | 0 | 0 | At most K (exactly K on successful parity) |
| A: first-use, admitted offset construction | 0 | 0 | 1 | 0; compare during validation |
| A: no metadata account or directory refused | 0 | 0 | 1 | 0; compare during validation |
| A: pre-existing local full cache (generic reader accessor only) | 0 additional | 0 additional | 0 | K borrowed cache comparisons on success |
| A: zero hits | 0 | 0 | 0 | 0 |

Here N is physical segment document count; K is the number of selected **positions in this segment**, not requested global TopK, and includes repeated positions in private test inputs. On a successful warm offset path the existing direct accessor can construct one selected `DocumentKey` at a time (at most K constructions in total); the borrowed scanning path constructs **zero** new `DocumentKey`s. The retained offset directory still costs N+1 u64 positions when admitted. That is bounded shared immutable metadata, not N owned strings on every query. If the directory is unavailable, scratch is O(K) and the section is scanned once, never K times.

This is a structural work-reduction claim, not a measured millisecond or speedup claim. Candidate collection can still use other key APIs and incur work; do not describe A as eliminating every whole-segment operation from the complete search.

## 2. Current-source evidence and reuse map

Inspected `main@44caa511...` and the proposed roadmap at `e7bc4cab...`. The source paths below must match the pinned blobs at BASE. Execute `git rev-parse "$BASE:$path"` for each, compare to this table, and record the actual hash. Do not use a filename from memory as a substitute for source inspection.

| Repository path | Reviewed blob |
|---|---|
| `crates/quervant-core/src/search/unified.rs` | `cd2072960fa15ffd078335ca56264559d22ad018` |
| `crates/quervant-core/src/segment/reader.rs` | `9951e1c930aef3951cc29ac5493aa32300d02691` |
| `crates/quervant-core/src/index/snapshot.rs` | `65fef3bc9b66467580ee3f2e9c367a1bdaf8543e` |
| `crates/quervant-core/src/segment/metadata.rs` | `4e471b87bc79d7c91f45039775a11ad366a6e7f1` |
| `crates/quervant-core/src/segment/format.rs` | `296b7c5ca7d8211890667745956116ace8f4c6fe` |
| `crates/quervant-core/src/segment/error.rs` | `e44e48d5a2880d1431691c51919bcdc6268060fb` |
| `crates/quervant-core/src/search/batch_meter.rs` | `9019726c42eeead4d4aae689ac5e4e02d832a54a` |
| `crates/quervant-core/src/search/memory.rs` | `001b69b98d94cb806b5993ccc0645d46df43b844` |
| `crates/quervant-core/src/segment/limits.rs` | `bf222b67e0675aadf6137642748d6b7f4c781328` |
| `crates/quervant-core/src/contract/document.rs` | `557b5dfdb061f833a96dfe8c1f50329c612e123a` |
| `crates/quervant-core/src/search/error.rs` | `61ce8cef2033bc8b95e86e8da136b3e01217c152` |
| `crates/quervant-core/src/search/projection.rs` | `d36048ab1a2b6959c8b6593dfed8c0d15e9679a9` |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | `76dc464a519dd5faf34653ab374a3033ffc43a0c` |
| `crates/quervant-core/tests/pr15g_b_rustfs.rs` | `14d6aa9207bc0b8737581e3a9750f7d0251000b7` |
| `.github/workflows/ci.yml` | `e8aeae6a892c76a295c27541397c1a504c77c4e3` |
| `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` | `c871d370dc050fad9457bfa81a8421dbb846fbf2` |
| `docs/TESTING.md` | `91c8643eaa041b0cb475949bcefa7c074ae27fe3` |
| `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md` | `7c399fcde8cd601c034d7dd4bcd399504afa1b93` |
| `Cargo.toml` | `40bd37bd5314009eeb7b81f201f5ae0180be26f7` |

Current facts (line numbers are navigation aids, symbols are authoritative):

- `unified.rs:3705` `project_selected_hits`: `BTreeMap<usize,Vec<usize>>` groups positions by segment; per segment it obtains one `GuardedSegmentReader`, validates all selected physical keys in `indices` order, then builds sorted/deduplicated `selected_ids` for `stored_docs_selected`. It projects and reserves logical output bytes **in original selected-position order within that segment**. It fills `out[index]` to restore global rank order. Keep everything except the key verification block unchanged. The accepted semantics are per-segment parity before that segment's STORED processing, not all-segment parity before any STORED processing anywhere.
- `SelectedHit` (`unified.rs:1739`) already owns `key: DocumentKey`, `segment_index`, `doc_id`, score and sort tuple. Reuse that key as the expected value, but do not assume it proves physical identity. `doc_id` is a physical ID within the exact snapshot segment, not an ordinal/key into the latest generation.
- `reader.rs:1621` `doc_keys` calls `decode_doc_keys` and sets a query-local `RefCell<Option<Rc<Vec<DocumentKey>>>>`. `doc_key` converts ID to usize, calls that full accessor and clones one key. `decode_doc_keys` (`:2425`) validates version, count, entries, count representability, minimum bytes, every UTF-8 key and length, and trailing bytes. Keep these public methods and the full decoder's production behavior intact; other call sites need them.
- `doc_key_selected` (`:1652`) uses the already available full local cache, else shared `key_offsets: OnceLock<Option<ValidatedOffsets>>`, else `decode_doc_key_selected`. A scalar fallback scans the entire section, validates unselected keys, owns only the requested key. Repeating this scalar call K times on a refused directory would produce K scans. **Do not do that.** Existing scalar callers and B3 `bind_key_identity` stay unchanged.
- `ValidatedOffsets::range`, `decode_doc_key_at_validated_offset`, `build_validated_offsets`, `try_build_key_directory`, and `scan_doc_keys` are already implemented in `reader.rs`. The offset vector has N+1 relative offsets, first offset 10, terminal offset body length; admission is `limits.check_alloc::<u64>(N+1)`, `limits.check_entries(N)`, `MetadataMeter::reserve`, `try_reserve_exact`, validation, boundary/monotonicity verification, measured capacity and `finalize`. The returned `MetadataReservation` is RAII-owned by the directory. Reuse this exact builder and cell, not a new directory, fingerprint, or index format. `MetadataMeter::finalize` can refuse **after** validation; that is the subtle case A must handle without rescanning.
- `scan_doc_keys` (`:2560`) validates `DOC_KEYS` v1 with `ByteReader` and optionally captures offsets or materializes a single key. The existing borrowed validation is precisely the `DocumentKey::new` rule: nonempty UTF-8, <= 1024 **bytes**; no normalization. The new parity-only caller uses the same scanner and checks exact borrowed strings against the already owned expected keys.
- `ReaderSnapshot::open_segment_reader` (`snapshot.rs:593`) reserves encoded-reader bytes before opening, and creates a fresh reader wrapper from a snapshot-admitted `Arc<VerifiedSegmentState>` when available. The immutable state owns the exact bytes/limits and the offset cell. Never retain a query-local reader across queries or share `Rc` across threads. Do not change snapshot admission, metadata budgets, segment verification, cache eviction, storage or remote lifecycle.
- `ProjectionLedger::reserve_with_memory` checks local and optional batch charge atomically per projected hit. Leave this implementation, `projected_hit_bytes`, `stored_docs_selected` v1/v2 production implementation, projection field order, all caller finalization and cursor construction unchanged. `SearchError::from(SegmentError)` preserves the typed segment error except cancellation mapping.

The prior 15G-B validated offset work is already delivered; A changes how projection uses it. The prior 15H-C/15I-D1-F rejected candidate-key-borrow experiments are not revived. No change to candidate duplicate detection, logical work, BM25, heap layout, stored codecs, or any other PERF-07 stage.

## 3. Invariant ledger, ownership and error contract

| ID | Required invariant | Proof / acceptance |
|---|---|---|
| A-I01 | All selected positions verify their exact physical key from the same guarded snapshot/segment before any STORED access for that segment; equality is byte-exact, not hash equality. | R01/R07, U03/U04, I01/I02, RF01; same mismatched-key `SearchError::CorruptIndex` detail. |
| A-I02 | A successful prepared offset path performs no full key decode/scan; <= K selected keys read and owned, no full local key cache installed. | R01/R02, U01 red-first and green, U02. |
| A-I03 | Absent/refused directory performs at most one complete validating scan, including a refusal after scanning; no owned full key list, no K repeated scalar scans. Scratch <= K selection rows, no per-unselected owned key. | R02–R05, R09, U02/U04. |
| A-I04 | A fresh uncertified DOC_KEYS body is validated fully in accepted wire order before comparison/range mismatch returns (except the preexisting large-singleton range check and first unrepresentable ID exception). Malformed **unselected** keys are never skipped. | R06/R07, U04/U05. |
| A-I05 | Existing cell and metadata account remain the only retained directory owner. Complete validation before publication, optional refusal stays sticky; capacity pressure, unwind and last-owner release preserve accounting. | R02–R05/R08/R09. |
| A-I06 | Zero hits perform no projection reader acquisition. Output rank, duplicate selected positions in private projection seam, exact field states, score bits, exact total, cursors, PIT/refresh/mutation/compaction remain unchanged. | U01–U06, I01/I02, RF01, retained C2/C3 tests. |
| A-I07 | Reader admission, logical candidate/response budget charges, batch sink operations, errors, and existing cancellation sites remain unchanged. No partial successful response on any refusal. | U03/U05/U06, existing `phase3_*`, `e_projection_*`, `c3_u09_*`, `c3_i03_*`, full suites. |
| A-I08 | No wire format, public API, persistent or global cache, query-demand, postings, live bitmap, adapter, statistical, or timing changes; no unsafe/new deps. | Source freeze, diff review and full regression. |

Ownership and identity: a `SelectedHit` borrows nothing from a cache; it carries the owned expected key and the exact segment ordinal/physical doc ID. The new accessor borrows those keys for the duration of one projection group; it returns only a boolean success/mismatch or a typed codec error. Offset identity is still tied to `Arc<VerifiedSegmentState>`, exact immutable bytes and limits, not logical document key, physical doc ID globally, mutable index, or PIT token alone. Ready directory reads borrow the same immutable bytes. No new network/storage operations or mutable publication transaction. A held old snapshot may retain the old offset owner; a new snapshot must obtain its own correct state. Neither may use a latest-key lookup. Existing `ReaderReservation` is retained even on a cache hit and drops on all exits.

### 3.1 Important error-precedence choices

In the historical ordinary `doc_key` route, **first** `usize::try_from` can fail before body access; otherwise full body decode validates every record including trailing bytes before the first selected lookup returns. Later bad IDs or mismatches are evaluated in the original selected order. In the old large-singleton route (`K==1 && N>=1024`), the scalar selective scan checks range after header/count/limit/minimum-byte checks and **before** reading rows. A must preserve those distinctions for private malformed selection tests (normal selected IDs are valid). For full local cache already present, the selected lookup order governs; no new validation is needed. For a ready shared offset certificate the complete body is already validated, so each selected range and parity check is authoritative in original order.

The prescribed accessor therefore records the earliest failed selection ordinal on a scan but never exposes that mismatch/range failure until full validation succeeds. A selected mismatch is **not** a body-validation error and must not suppress a complete offset certificate. The old first-unrepresentable-ID check remains before body access for ordinary route; a large-singleton invalid ID must retain the scalar early-range behavior, even if offsets exist. Do not reorder segments, fail a later selected ID before an earlier mismatch, sort the response order, or make a mismatched selected key trump corruption later in an uncertified DOC_KEYS body.

New scratch is a fallible O(K) allocation from the bounded, internally selected hits, not an untrusted wire count; no new deterministic search budget or per-hit virtual charge is introduced. As with the eliminated full N allocation, actual process allocator exhaustion can differ because physical allocations changed; report its typed resource failure, not a guarantee of identical OOM timing. Keep all deterministic `SegmentLimits` checks in the scanner and all deterministic search/batch admissions unchanged. No full decoder allocation should be simulated to preserve an allocation that was removed. Keep existing cancellation checks at caller boundaries; **do not add or remove polls** in the projection/key scanner for this PR. It has no cancellation parameter today. Later work may explicitly redesign cancellation, but not here.

### 3.2 Fixed decision table for key validation

| Input/state | Required action/result |
|---|---|
| Empty selection | `Ok(true)` without touching the body/cache/directory. |
| Local full cache | Read expected keys by physical ID in selected order without cloning; first mismatched key -> `Ok(false)`, first invalid ID -> original `Corrupt { context: "doc keys", detail: "doc id out of range" }`. Do not initialize directory. |
| Ordinary selection, first ID not representable as usize | Same range error before accessing DOC_KEYS as old `doc_key`. |
| No local cache, large singleton and ID >= N | Old early-range behavior via shared scanner: header/count/limits/minimum-byte failure first; otherwise range error, zero rows, no directory build. |
| Ready offsets | For each original selection, explicit `id < N`, then existing direct key decoder and equality. First failure wins. No scratch or full scan. |
| Directory empty, metadata account present, all IDs valid | Attempt existing bounded offset build. During its single validating scan also compare selected keys. Retain the private comparison result independently of optional metadata result. |
| Builder refuses before scanner starts (`LimitExceeded`) | One unmetered selected verification scan; publish existing sticky None, no full decode. |
| Builder scanner itself fails | Propagate actual error; do not restart scanner. No ready publication. |
| Builder scan succeeds, post-scan optional capacity refusal | Use the completed parity result; do NOT rescan. Sticky None. |
| Builder succeeds even when expected key mismatches | Publish validated offsets; return `Ok(false)` after validation. This does not validate a wrong expected key. |
| Builder unexpected non-resource failure outside scan | Propagate typed error; no fallback that hides internal invariant failure. |
| Another caller completed init while this call waited | Consume resulting ready directory or perform one fallback scan for sticky None; no new directory attempt. |
| Unmetered / sticky None / cold malformed ordinary selection with invalid IDs | One full scanner pass, selected parity evaluated by original ordinals after validation. No new offset initialization on invalid input. |
| Parity fails for this group | Projector emits same existing mismatch or mapped segment error; no `stored_docs_selected`, output reservation, or successful page for this group. |

## 4. Exact implementation design

**Only two production files may change:** `crates/quervant-core/src/segment/reader.rs` and `crates/quervant-core/src/search/unified.rs`. The permitted changes are described in P0–P4. No new dependency, public API, unsafe, cache state field, persistent feature, config, benchmark adapter, work charge or CI change. Test-only additions are allowed only as specified. The following Rust snippets are normative implementations (format with rustfmt; small compiler-required lifetime/type corrections only under D08). Do not choose a different strategy. Do not add `#[allow(...)]`, `#[inline]`, `unsafe`, `expect`/`unwrap`/panic in new production paths, or change unrelated imports/attributes to get green CI.

### P0. Test-only structural observations (red-first prerequisite)

Add a crate-visible `#[cfg(test)] pub(crate) mod perf07a_observation` in `reader.rs` next to `test_observation`. Use one `thread_local!` `Cell<Counts>` with `const { Cell::new(Counts { ...all fields 0... }) }`. `Counts` derives `Debug, Clone, Copy, Default, PartialEq, Eq`; fields are `pub(crate) usize` named `full_decodes`, `full_owned`, `scans`, `scan_rows`, `offset_reads`, `cache_compares`, `selection_rows`, `stored_calls`. Expose `reset()`, `counts() -> Counts`, and the following recorders, each incrementing its named counter by one: `record_full_decode`, `record_full_owned`, `record_scan`, `record_scan_row`, `record_offset_read`, `record_cache_compare`, `record_selection_row`, `record_stored_call`. Implement e.g. `fn add(f: impl FnOnce(&mut Counts)) { COUNTS.with(|c| { let mut counts=c.get(); f(&mut counts); c.set(counts); }); }`. Call recorders under `#[cfg(test)]` at these actual sites; no production metric/tracing. Counter arithmetic is test-only, never estimate counts from N/K.

| Counter | Exact site |
|---|---|
| `full_decodes` | first statement in `decode_doc_keys` |
| `full_owned` | immediately after each successful `keys.push(key)` in `decode_doc_keys` |
| `scans` | at entry of existing `scan_doc_keys` for RED; after P1 move this site to `scan_doc_keys_with` (only once, not wrapper) |
| `scan_rows` | after successful UTF-8/key-length validation of a physical row, before visitor (on RED before loop closes) |
| `offset_reads` | after `bytes.expect_end("doc keys")?` in `decode_doc_key_at_validated_offset`, next to existing selected-owned witness |
| `cache_compares` | immediately after each successful local full-cache `get` in new verifier, before equality |
| `selection_rows` | one addition per real valid scratch-row push in `scan_selected_key_parity`; not a formula using selected.len() |
| `stored_calls` | first statement of existing `stored_docs_selected`, before local cache branch |

The `cache_compares` and `selection_rows` sites are inserted during P1/P2; until then their recorders may be defined only after RED to avoid unused-code lint (not suppressed). Do not reset global test state or modify existing selected-key observations. For tests that need direct-selected ownership proof, additionally reset and read the existing `test_observation::selected_keys_owned()`. The full-key counter is separate and counts the full decoder's owned keys. The counters may include earlier collection work if not scoped; **reset after fixture setup immediately before calling the actual projection seam**. Do not use whole-search counter totals as projection-only evidence.

Add U01 (§6) at this point, with no production behavior change. Run the exact red command in §9. It must successfully project the expected fields and then fail on `full_owned` (1100 vs 0). If it fails earlier, repair only a prescribed mechanical fixture typo or stop; never accept a compile error or an unrelated assertion failure as RED. Commit this observation-only/test-red revision, record SHA and raw command output; do not publish a separate PR or run a full QA campaign on the intentionally red intermediate commit. Continue directly.

### P1. Reuse the existing scanner; add selection parity without owning keys

#### P1.1 Scanner seam (one decoder)

Do not replace `decode_doc_keys` or duplicate its wire parsing. Keep the existing `scan_doc_keys` signature and callers. Make it a wrapper around a new private function:

```rust
fn scan_doc_keys(
    body: &[u8],
    expected_count: u64,
    limits: &SegmentLimits,
    selected_doc_id: Option<u64>,
    offsets: Option<&mut Vec<u64>>,
) -> SegmentResult<Option<DocumentKey>> {
    scan_doc_keys_with(
        body, expected_count, limits, selected_doc_id, selected_doc_id,
        offsets, |_, _| {},
    )
}

fn scan_doc_keys_with<F>(
    body: &[u8],
    expected_count: u64,
    limits: &SegmentLimits,
    selected_doc_id: Option<u64>,
    early_range: Option<u64>,
    mut offsets: Option<&mut Vec<u64>>,
    mut on_valid_key: F,
) -> SegmentResult<Option<DocumentKey>>
where
    F: FnMut(u64, &str),
{
    // Move the complete ORIGINAL scan_doc_keys body here.
    // The only edits to that body are listed immediately below.
}
```

The comment-only body above is an edit instruction, **not** compilable placeholder. Move the original body byte-for-byte except the following three changes:

1. Move `scans` observation to its entry. Retain the exact `ByteReader` reads, version/count comparisons, `limits.check_entries`, `usize::try_from(count)`, `count_min_bytes`, offset-capture logic and typed errors.
2. Change only the pre-loop range gate `if let Some(selected_doc_id) = selected_doc_id { if selected_doc_id >= count { ... } }` to bind `early_range` as `if let Some(selected_doc_id) = early_range { ... }`. This separates the existing early range check from optional single-key ownership. Do not change the later selected ID branch or final `Option<DocumentKey>` behavior.
3. At the end of each physical-row loop body, **after** the original selected-constructor/unselected-borrowed validation branch, increment `scan_rows` under cfg(test) and execute `on_valid_key(physical_doc_id, key_ref);`. `on_valid_key` must not terminate traversal. Leave terminal offset and `expect_end` ordering intact.

For original scalar selection, both parameters are identical, so the original range/materialization/error behavior remains. For directory-only capture both are None. For new parity-only scans, `selected_doc_id=None`; never call the constructor for any scanned row, including selected ones. `early_range` is supplied only for the historical large singleton. No new full-array decode or raw byte parsing beyond the existing scanner.

#### P1.2 Private parity type and one-scan verifier

Add the following adjacent to the scanner (the existing `SegmentError` import is already present). `KeyParity` is not a public API. An expected-key mismatch is a result of comparing valid bytes, distinct from an actual malformed body. Selected indices can be unsorted or duplicated. The scratch vector uses `(doc_id, original_selection_ordinal, &DocumentKey)`, sorts by physical ID and then original ordinal, and records the earliest failed selection by its original ordinal. Invalid IDs stay in the earliest-failure record, not in the scan rows. There is no `Vec<DocumentKey>` and no cloning expected keys.

```rust
#[derive(Clone, Copy)]
enum KeyParity {
    Match,
    Mismatch,
    OutOfRange,
}

fn selected_key_range_error() -> SegmentError {
    SegmentError::Corrupt {
        context: "doc keys",
        detail: "doc id out of range".to_owned(),
    }
}

impl KeyParity {
    fn into_result(self) -> SegmentResult<bool> {
        match self {
            Self::Match => Ok(true),
            Self::Mismatch => Ok(false),
            Self::OutOfRange => Err(selected_key_range_error()),
        }
    }
}

fn remember_first_key_failure(
    failure: &mut Option<(usize, KeyParity)>,
    ordinal: usize,
    parity: KeyParity,
) {
    if failure.as_ref().is_none_or(|(previous, _)| ordinal < *previous) {
        *failure = Some((ordinal, parity));
    }
}

fn scan_selected_key_parity<'a, I>(
    shared: &VerifiedSegmentState,
    body: &[u8],
    selected: I,
    early_range: Option<u64>,
    offsets: Option<&mut Vec<u64>>,
) -> SegmentResult<KeyParity>
where
    I: ExactSizeIterator<Item = (u64, &'a DocumentKey)>,
{
    let selected_len = selected.len();
    let mut rows: Vec<(u64, usize, &DocumentKey)> = Vec::new();
    rows.try_reserve_exact(selected_len).map_err(|_| SegmentError::LimitExceeded {
        limit: shared.limits.max_single_allocation(),
        requested: u64::try_from(selected_len).unwrap_or(u64::MAX),
    })?;
    let mut failure = None;
    for (ordinal, (doc_id, expected)) in selected.enumerate() {
        if doc_id >= shared.doc_count || usize::try_from(doc_id).is_err() {
            remember_first_key_failure(&mut failure, ordinal, KeyParity::OutOfRange);
        } else {
            rows.push((doc_id, ordinal, expected));
            #[cfg(test)]
            perf07a_observation::record_selection_row();
        }
    }
    rows.sort_unstable_by_key(|row| (row.0, row.1));
    let mut next = 0usize;
    let _ = scan_doc_keys_with(
        body, shared.doc_count, &shared.limits, None, early_range, offsets,
        |physical, actual| {
            while let Some((doc_id, ordinal, expected)) = rows.get(next) {
                if *doc_id != physical {
                    break;
                }
                if actual != expected.as_str() {
                    remember_first_key_failure(&mut failure, *ordinal, KeyParity::Mismatch);
                }
                next += 1;
            }
        },
    )?;
    if next != rows.len() {
        return Err(SegmentError::Corrupt {
            context: "doc keys",
            detail: "selected document key was not decoded".to_owned(),
        });
    }
    Ok(failure.map_or(KeyParity::Match, |(_, parity)| parity))
}
```

No new untrusted counts are allocated from the section header. The scratch reservation is from the exact-size iterator over already bounded selected positions. `rows.push` happens at most K times; no selected strings are allocated. Rust 1.85 supports `Option::is_none_or`, already used in baseline. `unwrap_or` above is a non-panicking saturation on usize conversion; it is not an authorization to unwrap fallible data. `scan_doc_keys_with` validates the full body before its return; the comparison loop records only private facts, never projects STORED and never returns early on parity mismatch. A late malformed row or trailing byte wins. If a valid selected ID was not visited despite full validation, the internal typed invariant error above is required, not a fabricated key.

#### P1.3 Direct offset verifier

Use the existing selected decoder as-is. No second raw-key parser and no fingerprint-directory creation required for projection. Introduce this private function adjacent to `decode_doc_key_at_validated_offset`:

```rust
fn verify_keys_at_offsets<'a, I>(
    body: &[u8],
    offsets: &ValidatedOffsets,
    count: u64,
    selected: I,
) -> SegmentResult<bool>
where
    I: Iterator<Item = (u64, &'a DocumentKey)>,
{
    for (doc_id, expected) in selected {
        if doc_id >= count || usize::try_from(doc_id).is_err() {
            return Err(selected_key_range_error());
        }
        let actual = decode_doc_key_at_validated_offset(body, offsets, doc_id)?;
        if &actual != expected {
            return Ok(false);
        }
    }
    Ok(true)
}
```

This deliberately reuses existing direct decoder's `DocumentKey` construction and validated extent checks rather than pursuing a small additional per-key optimization. At most one of the K new selected keys is alive in this function at any instant. The already-owned expected key remains the result identity; the temporary decoded key is only a verification value.

### P2. Add one crate-private `SegmentReader` parity accessor using the existing offset cell

Insert immediately after `doc_key_selected`, before its test-only local-cache witness. Implement exactly this method, allowing rustfmt layout differences. The argument is an exact-size, cloneable iterator of borrowed expected keys in original selection order. Only its internal projection caller and deterministic tests are authorized; do not expose it in `segment/mod.rs` or add a public selection API.

```rust
pub(crate) fn verify_selected_doc_keys<'a, I>(&self, selected: I) -> SegmentResult<bool>
where
    I: Clone + ExactSizeIterator<Item = (u64, &'a DocumentKey)>,
{
    let Some((first_id, _)) = selected.clone().next() else {
        return Ok(true);
    };
    let shared = &self.shared;
    let large_singleton = selected.len() == 1 && shared.doc_count >= 1024;
    if !large_singleton && usize::try_from(first_id).is_err() {
        return Err(selected_key_range_error());
    }

    // A pre-existing full cache has already validated the body. Borrow, do not
    // clone its keys or populate/replace any other cache.
    if let Some(keys) = self.doc_keys_cache.borrow().as_ref() {
        for (doc_id, expected) in selected {
            let index = usize::try_from(doc_id).map_err(|_| selected_key_range_error())?;
            let actual = keys.get(index).ok_or_else(selected_key_range_error)?;
            #[cfg(test)]
            perf07a_observation::record_cache_compare();
            if actual != expected {
                return Ok(false);
            }
        }
        return Ok(true);
    }

    let body = self.body(SectionKind::DocKeys).ok_or(SegmentError::MissingSection {
        kind: SectionKind::DocKeys as u16,
    })?;
    let early_range = large_singleton.then_some(first_id);

    // Preserve the old scalar early-range error order on invalid large singleton.
    if large_singleton && first_id >= shared.doc_count {
        return scan_selected_key_parity(shared, body, selected, early_range, None)?
            .into_result();
    }

    if let Some(budget) = &shared.access_budget {
        if let Some(directory) = shared.key_offsets.get() {
            if let Some(offsets) = directory {
                return verify_keys_at_offsets(body, offsets, shared.doc_count, selected);
            }
            return scan_selected_key_parity(shared, body, selected, early_range, None)?
                .into_result();
        }

        // Malformed ordinary private selections cannot initialize a new directory;
        // preserve complete body validation and original selection error ordering.
        if selected.clone().all(|(id, _)| {
            id < shared.doc_count && usize::try_from(id).is_ok()
        }) {
            let mut scan_started = false;
            let mut scanned = None;
            let mut build_error = None;
            let directory = shared.key_offsets.get_or_init(|| {
                let built = build_validated_offsets(
                    body, shared.doc_count, &shared.limits, budget,
                    |offsets| {
                        scan_started = true;
                        let parity = scan_selected_key_parity(
                            shared, body, selected.clone(), early_range, Some(offsets),
                        )?;
                        scanned = Some(parity);
                        Ok(())
                    },
                );
                match built {
                    Ok(offsets) => Some(offsets),
                    Err(error) => {
                        build_error = Some(error);
                        None
                    }
                }
            });

            if let Some(error) = build_error {
                match error {
                    SegmentError::LimitExceeded { .. } if !scan_started => {
                        // Optional pre-scan capacity refusal: one scan below.
                    }
                    SegmentError::LimitExceeded { .. } if scanned.is_some() => {
                        // Post-scan capacity refusal: use the completed scan.
                        // Never perform another validation pass.
                    }
                    other => return Err(other),
                }
            }
            if let Some(parity) = scanned {
                return parity.into_result();
            }
            if let Some(offsets) = directory {
                // Another initializer completed, or this is the ready case.
                return verify_keys_at_offsets(body, offsets, shared.doc_count, selected);
            }
        }
    }
    scan_selected_key_parity(shared, body, selected, early_range, None)?.into_result()
}
```

**Subtle but binding choices:** The scanner returns `KeyParity::Mismatch` as a successful validation of the body, so a completed valid directory can still publish. `scanned` is set only after the scanner returns success, including terminal offset and trailing-data check. A `LimitExceeded` from inside a started scan (including failed scratch allocation) with no completed result is authoritative, not a retry. A `LimitExceeded` before scanner start could be the builder's optional count/entry/allocation preflight; the fallback scanner repeats the authoritative semantic checks, not the optional allocation. A post-scan capacity refusal must use the completed result. Other builder errors propagate. The cell retains the established `OnceLock<Option<ValidatedOffsets>>` sticky-None behavior, including on malformed body; no malformed body can publish Some, and subsequent fallback validates the same bytes and fails. No new lock, hash, cache admission scheme, synchronization, reader field or retry policy. The closure-local outcome is never shared or cached; only the validated directory is published. A competing call that did not run the initializer cannot use another request's parity result. Unwind leaves OnceLock empty and RAII releases budget, as before. Test this precisely.

### P3. Route all projection groups through the verifier; preserve the rest of the projector

In `search/unified.rs::project_selected_hits`, replace **only** the comment and key-check region beginning `// Physical identity is authoritative` through the end of the loop before `// Ascending unique physical ids`. New block:

```rust
        // Verify every selected physical key before STORED materialization. The
        // reader reuses validated offsets or performs one borrowed validation scan.
        let selected = indices.iter().map(|index| {
            let hit = &hits[*index];
            (hit.doc_id, &hit.key)
        });
        if !reader.verify_selected_doc_keys(selected)? {
            return Err(SearchError::CorruptIndex {
                detail: "selected hit key does not match its physical document".to_owned(),
            });
        }
```

Change the function doc comment to describe PERF-07-A key verification, retaining existing per-segment parity-before-STORED, output order, and ledger facts. **Do not** move the `selected_ids` reservation, sorting/dedup, `stored_docs_selected`, binary search, `plan.project`, `projected_hit_bytes`, `reserve_with_memory`, `out[index]`, or final error/collection. No new branch based on K, N, sort, score, query type, or benchmark input; all projection groups use this accessor, including Legacy, batch, PIT continuation, C2/C3 and typed paths. The historical 1024 threshold survives only for malformed singleton **error ordering** inside the verifier, not as a performance dispatcher. No skipping identity on empty projection fields.

### P4. Deterministic post-scan fault seam (test-only)

To exercise the otherwise allocator-dependent post-scan measured-capacity refusal, add `#[cfg(test)]` to a narrowly scoped TLS `Cell<DirectoryFault>` in `perf07a_observation`, with enum `DirectoryFault { None, FinalizeRefusal, PanicAfterScan }`, derive Copy/Clone/PartialEq/Eq. An RAII arm saves prior value and restores it in Drop. Expose `arm_directory_fault(fault) -> Guard` and private/test `directory_fault()`. No production flag or environment variable. Only arm around `verify_selected_doc_keys` on a fresh reader; disarm before STORED or any other operation. In `build_validated_offsets`, immediately after the original measured-capacity calculation and before the existing finalize call, shadow the measured value only under cfg(test):

```rust
    #[cfg(test)]
    let measured = match perf07a_observation::directory_fault() {
        perf07a_observation::DirectoryFault::None => measured,
        perf07a_observation::DirectoryFault::FinalizeRefusal => {
            allowance.checked_add(1).ok_or(SegmentError::LimitExceeded {
                limit: allowance,
                requested: u64::MAX,
            })?
        }
        perf07a_observation::DirectoryFault::PanicAfterScan => {
            panic!("injected PERF-07-A post-scan directory unwind")
        }
    };
```

The actual `MetadataMeter::finalize` must reject the simulated over-capacity value; do not inject a fake returned error after success or alter production measured capacity. Label R05 `INJECTED_POST_SCAN_MEASUREMENT`; actual one-under admission is tested independently. R09 catches the injected test panic, checks cell empty and budget restored, and retries normally on the same state. This is a deterministic test of the real finalize/unwind path, not a claim that a real allocator overallocated. The shared builder is also used for STORED, so guard scope matters. Existing stored panic seam and all historical tests remain unchanged.

## 5. Pre-implementation correctness challenge

Before feature code (after inspection; red observation stage is permitted), record a short completed worksheet in the execution report for each of the following. Use the answer specified, not a new design. If the actual source contradicts it, D04/D07 STOP.

| Challenge | Prescribed answer / witness |
|---|---|
| Why not call `doc_key_selected` K times? | Refused directory rescans N K times. One scan with K sorted borrowed rows is required. |
| Why not skip parity because B3 already selected the key? | Projection authoritative physical identity is required, including tampered private SelectedHit and retained PITs. |
| Why not return mismatch as soon as a key differs in the fallback scan? | Late corrupt unselected key/trailing data used to win before selected lookup. Record failure privately, complete validation. |
| Why not sort selected IDs and report first error in sorted order? | Historical selected order decides mismatch vs out-of-range after validation. Keep original ordinals. |
| Can optional directory build scan then refuse? | Yes, measured finalization may fail; preserve scan outcome and return without rescan. |
| Can the new initializer cache the expected-key comparison? | No; it is per request; only immutable offset certificate enters cell. |
| Does `None` mean valid bytes? | No; it means optional unavailable. Scan and validate on every access. |
| Does checksum validation establish all keys valid? | No; retain full UTF-8/length/framing/terminal validation before publishing offsets. |
| Can one snapshot's certificate verify another segment's bytes? | No; existing owner binds to exact bytes/limits; tests use separate Arc states. |
| Can projection reserve fewer output bytes due to optimized physical allocations? | No; unchanged output ledger and optional batch sink. |
| Do we need a new public storage/read abstraction? | No; reuse existing reader/state/offset builder and local/RustFS path. |
| Can the first preparation claim O(K) total memory? | No; optional retained offset directory is N+1 u64; only request scratch/owned keys change. |

## 6. Deterministic unit and adversarial acceptance

No mocks of codec/scanner, offset state, or actual `project_selected_hits`. Test with real `SegmentBuilder`, real verified state, real `MemoryDirectory` + index writer/reader, and checksum-valid copied containers. Keep all prior tests unchanged. Add **nine reader tests (R01–R09) and six projection tests (U01–U06)**; use these exact registered names. Named helper functions may be added in the indicated existing test modules only. Do not rename old tests or duplicate them for evidence. Every matrix row must have a distinct stable row label and assert literal expected results, not merely log an outcome. Add each test's final marker `PERF07-A <ID> rows=<actual completed count>` (the marker is supplemental; count only after assertions complete). Preserve raw outputs of focused runs.

### 6.1 Shared reader fixture and deterministic body mutations

Place R tests in `reader.rs::column_geometry_tests` (reuse `build_with_docs`, `doc`, `rebuild_section`, `key_body`, `lazy_directory_allowance`, `pressure_for`). For new admitted tests, build fresh state with `MetadataBudget::new(256 * 1024 * 1024)` and `VerifiedSegmentState::build_cached(Arc::new(bytes), SegmentLimits::default(), &budget).expect(...).expect(...)`; record state and budget. Use existing `SegmentReader::from_shared(Arc::clone(&state))`. For unmetered path `SegmentReader::open(bytes, limits)` must have no access budget. Assert actual `doc_count`, fixture key order (independent known insertion data; `Layout::Insertion`), and cache initial state before resetting counters. Do not call a full decoder after reset unless explicitly the oracle on a distinct wrapper before/after the measured path.

Make owned expected keys from literal input strings before passing iterator: `rows.iter().map(|(id, key)| (*id, key))`, where `rows: Vec<(u64,DocumentKey)>` is owned by test. A small shared `assert_counts` test helper may compare every field of `Counts` to an explicit expected value, using `Counts::default()` for zeros. Existing `test_observation::selected_keys_owned` must be checked on prepared success and scan success. K in counts is selection positions, not unique keys.

| Test / row | Fixture, trigger, and required result |
|---|---|
| **R01** `perf07a_r01_prepared_reordered_duplicate_utf8` (2 success calls + full-cache control) | Build six keys in exact insertion order: `d10`, `d2`, `é`, `e\u{301}` (Rust decomposed literal), `"x".repeat(1024)`, `z`. Prewarm offsets using old `doc_key_selected(0)`; drop wrapper. Two fresh wrappers on the same state verify rows `[4,1,3,0,4,2]` with correct literal expected strings. Each: scans=0, full_decodes=0, full_owned=0, offset_reads=6, selected_keys_owned=6, selection_rows=0, cache not populated. Same offset pointer and same budget before/after each. Then on a separate fresh state explicitly populate full local cache with `doc_keys` before reset; verify same rows; cache_compares=6, no scan/offset read/new ownership; directory remains empty. |
| **R02** `perf07a_r02_first_use_single_scan_and_warm_reuse` (4 verification calls) | N=4 keys `k0..k3`. Cold state with account, no offsets; select `(3,k3),(0,k0),(3,k3)`. First call: scans=1, scan_rows=4, selection_rows=3, zero full/selected owned keys and direct reads; true; offsets Some(true); budget increases by 40 bytes (5*u64; verify actual capacity matches expected on supported allocator, otherwise D07). Fresh wrapper repeat: direct=3, scans=0, no scratch, same pointer/budget. Separate new state with same IDs but first expected `k1`: false, full scan=1/4, directory still Some(true); correct later call on same state succeeds direct. |
| **R03** `perf07a_r03_unmetered_and_real_optional_refusal` (4 calls) | N=4, same three rows. Two repeated calls on unmetered reader: each one scan/4 rows, scratch3, no owned keys, cell stays None. Separate admitted state reserve pressure leaving **39 bytes** when directory requires 40 using `pressure_for`; verify actual before balance and real refusal. Call succeeds via one scan/4 rows; cell Some(false), no extra retained bytes. Drop pressure, new wrapper on same state, repeat: still sticky None, one scan, no retained delta. Drop owners and assert budget zero. |
| **R04** `perf07a_r04_exact_metadata_and_independent_owners` (3 verification calls, 2 states) | Same N=4 with exactly 40 bytes free under real pressure. First state succeeds, scan=1/4, exact charge +40, offset pointer nonzero; fresh wrapper direct reads, no new charge. Independent state over copied same bytes and independently admitted budget: its own pointer different while both alive, same parity. Drop first state Arc but keep wrapper; directory remains accounted. Drop pressure and last reader/state; first budget zero, second unaffected; drop second => zero. Preserve Send+Sync assertions from existing tests. |
| **R05** `perf07a_r05_post_scan_finalize_refusal_no_rescan` (4 calls: 2 cases, each repeat) | Two separate fresh admitted N=4 states, correct selection and same IDs with wrong first key. Arm `FinalizeRefusal` only around new verifier. Actual finalize rejects after full scan; return true/false respectively, scans=1/4, scratch3, offset_reads=0, full/selected owned=0, cell Some(false), no metadata delta. Disarm; repeat correct selection on fresh wrapper => one scan, true, no further attempted publication. Label `INJECTED_POST_SCAN_MEASUREMENT`; do not label actual allocator refusal. |
| **R06** `perf07a_r06_corrupt_unselected_full_validation_matrix` | Use exact malformed-body table below with both unmetered and fresh admitted wrappers, genuine checksum-valid rebuilt container. Compare typed result to literal variant/detail and separate full-decoder oracle (same immutable bytes, distinct reader) for ordinary selection. No ready directory and no full cache. Repeat an admitted corruption case to ensure sticky None is not trust. |
| **R07** `perf07a_r07_selection_error_order_and_singleton_boundary` | Use selection-order table below on fresh unmetered, admitted-empty and ready states for valid body. Additionally large/small singleton early-range boundary with real corrupt last key at N=1023 and N=1024; wrong valid first selected key plus malformed tail. No successful partial result. |
| **R08** `perf07a_r08_concurrent_initialization_is_request_local` | N=4, shared admitted empty state; two `std::thread::scope` workers, barrier of 2, each creates its own reader from Arc inside worker (never move `Rc`/SegmentReader across threads). Each selects `(3,k3),(0,k0),(3,k3)`; the second request replaces only its first expected `k3` with `k1`. Start both after barrier; true and false regardless of initializer winner; per-thread observations return with outcome/pointer. Sum scans=1, scan_rows=4, full_owned=0; non-initializer may stop at mismatch, so total direct reads are 1 or 3 depending on which request initialized. Assert exact branch-dependent count using which thread's scan count was 1; not a permissive arbitrary interval. Both share same pointer, charge once 40. Drop all state owners => budget zero. No sleeps or process-global counters. |
| **R09** `perf07a_r09_initializer_unwind_and_recovery` | N=4 fresh admitted state; arm `PanicAfterScan`, catch with `std::panic::catch_unwind(AssertUnwindSafe(...))`; expect injected message. First scan one/4, directory cell still None, budget restored, no cache, no full owned. Arm drops; normal same-state verification succeeds, one scan/4, publish Some(true), exact +40. Next wrapper direct reads only. No production panic introduced. |

#### R06 literal corrupt-body table

Construct pristine N=4 via `build_with_docs(vec![doc("k0"), doc("k1"), doc("k2"), doc("k3")])`. Build each replacement using `key_body` (version=1, u64 count, u16 length prefixes) and `rebuild_section` for `SectionKind::DocKeys`. Preserve container features/digests; assert opening the real segment succeeds before key access. A default container parser validates envelope and metadata, not lazy key bodies. If any listed body cannot be admitted because accepted source validates it earlier, D07 STOP with precise error rather than changing the bytes or test expectation. Selection = `(0,k0),(1,k1)`; use additional mismatch selection `(0,k2),(1,k1)` for row C1 to prove tail corruption wins. `count_min_bytes` is the accepted minimum of three bytes per key. Compare exact variant and fields; `SegmentError` is not Eq, so match or compare Debug to independently constructed literal variant. Do not rely on error substring alone. Check scan count once and zero full owned for new accessor; reference full decoder on separate reader outside observation window.

| Row | Mutation from pristine | Expected typed codec error |
|---|---|---|
| C1 | final key bytes `[0xff,0xff]` | `InvalidUtf8 { context: "doc key" }` |
| C2 | final key length zero (`key_body` with `b""`) | `Corrupt { context:"doc key", detail:"invalid document key" }` |
| C3 | final key 1025 ASCII bytes | same invalid-document-key Corrupt |
| C4 | version bytes 9 little endian | `Corrupt { context:"doc keys version", detail:"unsupported 9" }` |
| C5 | count bytes 3 little endian, unchanged four records | `Corrupt { context:"doc keys", detail:"doc key count does not match segment doc_count" }` |
| C6 | truncate body to first 11 bytes (header + one byte) | `Truncated { context:"doc keys", needed:12, available:1 }` |
| C7 | final key length prefix at offset 22 changed to 255u16; body length unchanged, 2 bytes remain | `Truncated { context:"doc key", needed:255, available:2 }` |
| C8 | append one byte `0x00` after valid four records | `Corrupt { context:"doc keys", detail:"1 trailing bytes" }` |

For C7 confirm wire positions `[10,14,18,22]` from fixed two-byte keys and lengths; validate prefix bytes before mutation. For C2 the minimum check remains satisfiable (14 bytes of records >= 12). Additionally call the actual shared scanner `scan_doc_keys_with` on valid `key_body` with `SegmentLimits::default().with_max_decoded_entries(3)`, expected count=4, no ownership, no offsets, callback must never run; expect `LimitExceeded { limit:3, requested:4 }`. This direct bounded-body test isolates count-limit semantics without changing envelope limits. Count C1 mismatch extra case on both paths and one explicit repeat of the admitted C1 on the same sticky-None state. R06 has 20 acceptance calls: 16 primary corrupt-body cases, 2 C1 mismatch cases, 1 sticky-None repeat, 1 direct count-limit case. The separate full-decoder oracle invocations are not counted as new-verifier cases. Report each row identity and count, not an invented full-cache test on malformed data. For cold malformed valid-ID selections builder starts scanner once; error propagated, no second scan; `key_offsets_state()==Some(false)` after attempted initialization. Unmetered state remains None.

#### R07 selected-order table

N=4, valid literal `k0..k3`. For every row including S0 use a fresh unmetered reader, fresh admitted-empty reader, and fresh wrapper on a prepared state. Thus the literal table produces 24 calls; prepared state must have been initialized by the unchanged scalar accessor outside the observation window. Reset counters before each. On success compare exact values and observe direct vs scan route as specified. On mismatch use boolean false; do not create `SearchError` in reader tests.

| Row | Selection in this order | Expected |
|---|---|---|
| S0 | empty | true, no reads/scans/scratch/cache change |
| S1 | `(3,k3),(0,k0),(3,k3)` | true, duplicate positions preserved |
| S2 | `(3,k3),(3,k1)` | false (duplicate physical identity with different expected key) |
| S3 | `(0,k1),(9,k2)` | false, earlier mismatch wins over later invalid ID |
| S4 | `(9,k2),(0,k1)` | range error; earlier invalid wins |
| S5 | `(0,k0),(4,k1)` | range error |
| S6 | `(3,k3),(0,k0),(u64::MAX,k2)` | range error |
| S7 | `(u64::MAX,k0),(0,k0)` | range error on supported 64-bit host; on targets where u64::MAX is not representable as usize, return before body as historical ordinary route |

For two additional large-boundary rows construct N=1023 and N=1024 with keys `k00000..k01023` as applicable, `Layout::Insertion`. Replace last key's first byte with `0xff` without changing lengths. Single selection `(N, "k00000")`: for N=1023 expect final-key `InvalidUtf8`, for N=1024 expect range error before rows (scan_rows=0). For both N, single selection `(0,"k00001")` expects `InvalidUtf8` (late unselected fault before mismatch). Repeat on unmetered and admitted-empty. Invalid ordinary selection must not build new offsets; large singleton invalid must not initialize offsets. Neither route populates full key cache. Include N=0 real empty segment, empty selection true, nonempty `(0,k0)` range error after valid empty section; no full decoder. A separate corrupted-body empty-selection call on a fresh unmetered reader must return true with no reads, not validate unused data. The R07 matrix is 35 calls: 24 table calls, 8 boundary calls (2 sizes × 2 selections × 2 states), 2 unmetered real empty-segment calls, 1 corrupted-body empty-selection call. Use existing `build_with_docs(Vec::new())` fixture.

## 7. Actual projection-path unit acceptance

Add U01–U06 inside `unified.rs::c2_tests` to reuse `Fixture`, `schema`, `document`, `bounded_key`, `CopiedSegment`, `c2_f1_snapshot`, and existing public search helpers. For direct private projection tests construct `SelectedHit { segment_index, doc_id, key: DocumentKey::new(bounded_key(input_index)).unwrap(), score: Some(1.0), sort_tuple: Vec::new() }`. Never fabricate expected physical layout; build one native segment, assert count, then inspect pristine full key list on a separate wrapper **before** observation reset to map each input key to physical ID, checking bijection against the literal input set. Keep selected input indices prescribed below; do not select a key based on returned projection output. For multi-segment test map segment ordinals by actual pristine key membership (segment order is content-addressed, not commit order), assert two disjoint exact input ranges.

A helper `p07a_fields(i)` returns exactly `[ ("doc_id", Single(Keyword(bounded_key(i)))), ("n", Single(I64(i as i64))) ]` in requested order. `ProjectionPlan::compile(&Projection::Fields(vec!["doc_id".into(),"n".into()]), &fixture.schema)`. Compare complete vector of fields in input-selected order. For ledger tests use **empty fields** `Projection::Fields(vec![])`, which validates under accepted projection contract; `projected_hit_bytes` then is literally `24 + key.len()`, so each `doc000000`-style key of length 9 charges **33 bytes**. Assert this formula independently, not an oracle from observed ledger. Empty projection still invokes existing STORED selection and key verification; do not optimize it away.

### U01 — red-first structural proof and warm multi-hit scaling

Registered name `perf07a_u01_projection_prepared_offsets_no_full_keys`.

1. Build `Fixture::new(&[(0..1100).map(document).collect()])`, require one segment exactly N=1100. On separate guard, verify exact set of pristine keys; prime `doc_key_selected` for a valid physical ID (existing scalar path) and assert `key_offsets_state()==Some(true)`. Drop guard; offset pointer retained by snapshot; `reader_copy_used()==0` before projection.
2. Run private `project_selected_hits` with exactly the input indices `[1099,1098,...,1090]`, same physical IDs mapped from pristine. Fresh `ProjectionLedger::new(1<<20)`; reset observations immediately before actual call. Assert full expected fields, exact rank, ledger >0, returned length=10, reader guard released. `stored_calls==1`.
3. Print `PERF07-A RED-WITNESS full_owned=<observed> full_decodes=<observed> expected=0 K=10 N=1100` and **first structural assertion** `assert_eq!(counts.full_owned, 0, "PERF07-A U01 full owned keys");`. Before feature change the same test must fail left=1100 right=0 after all preceding assertions pass; `full_decodes==1`. This is the only acceptable expected red. Do not make the test conditional on code under test or environment. No performance clock.
4. Final GREEN: for same fixture and prepared offset state run K=10 and K=100 (input indices `1099..=1000` descending for latter), twice each; require `full_decodes=0`, `full_owned=0`, `scans=0`, `scan_rows=0`, `offset_reads=K`, `selection_rows=0`, existing selected-owned=K, `stored_calls=1`; no local full cache created by verifier (R cases directly prove wrapper state). For RED use the final four-call test unchanged; first K10 call fails at exact assertion, later rows unreached. Assert 4 completed rows on GREEN. Do not edit U01's behavioral assertions after RED. Print observed actual counts on both runs.

### U02 — cold and refused actual projector

`perf07a_u02_projection_first_use_and_zero_metadata`. Build a one-segment N=1100 fixture and construct test snapshots using `ReaderSnapshot::for_test` and `SegmentSnapshot::new` with pristine bytes + actual feature lists, using the same identity construction as existing `c2_f1_snapshot`. `reader_copy_limit=256 MiB`; `metadata_cap=256 MiB` and `0` respectively. Each snapshot must reference the exact immutable pristine bytes, correct descriptor, count and feature list. Take selected input `[1099,2,0,2]` (four positions, repeated physical ID). On fresh admitted snapshot first call: scan=1, rows=1100, selected scratch=4, full/selected owned=0, direct=0, stored_calls=1; fields and positions correct. Second fresh projection wrapper on same snapshot: direct=4, scan=0, full=0. Zero-cap snapshot repeated twice: each exactly one full borrowed scan/1100, selection_rows=4, no full/selected owned, direct=0, stored_calls=1. Same selected fields. After every call active reader bytes zero. Zero cap metadata remains zero. Include an empty selection on zero-cap snapshot: no scan/reader/stored calls, ledger zero, result empty. Use exact expected counters, not merely `<=`.

### U03 — selection order, duplicate positions, and physical identity guard

`perf07a_u03_projection_selected_order_and_parity`. N=4 native fixture. Use real private projector with warm prepared and fresh unmetered snapshot, input cases: success `[3,0,3,1]`, wrong first expected key (physical for 3 but key `doc000001`), wrong later repeated ID (third position key `doc000002`), earlier mismatch + later invalid ID=N, earlier invalid ID=N + later mismatch. Require success fields literal for all positions. Mismatch error exactly `SearchError::CorruptIndex { detail:"selected hit key does not match its physical document" }`; range error exactly `SearchError::Segment(SegmentError::Corrupt { context:"doc keys", detail:"doc id out of range" })`. On every failed single-segment case ledger.used()==0, `stored_calls==0`, reader bytes zero, no full keys. Repeat correct selection on same snapshot/ledger with generous cap; same fields. Verify cold scanner count one and ready scan count zero on successful rows. For wrong key and invalid ID cases assert first failure order from R07 table; do not derive expected from Legacy run.

### U04 — corruption precedence through the real projector

`perf07a_u04_projection_unselected_corruption_precedes_stored`. Real N=4 fixture with copied-container helper. Use one pristine segment's bytes and independently reconstruct actual record offsets from `DOC_KEYS` v1 header and length prefixes (assert four records, final key's length and bytes). Mutate physical record 3 (the last and unselected record), first key byte to `0xff`. Select physical IDs 0 and 1, whose exact expected keys must be derived from the independently verified pristine mapping of the four literal input keys; never use a returned projection as the oracle. For the mismatch case replace the expected key at physical ID 0 with the valid key known to belong to physical ID 2. Do not mutate STORED: `stored_calls==0` on real key corruption and U03 valid-key mismatch proves ordering without inventing an additional fault or relying on a malformed eagerly validated header. Use separate fresh admitted and zero-metadata snapshots; assert `InvalidUtf8 { context:"doc key" }` mapped exactly via `SearchError::Segment`; `stored_calls==0`, no ledger admission, one validating scan and zero full ownership. A valid pristine copy on the same logical fixture must project successfully on a fresh admitted snapshot (one success control after the four negative cases). This is a real copied-container lazy corruption, not an injected comparison error. Do not mutate shared ready bytes or a committed index.

### U05 — physical grouping and per-segment failure ordering

`perf07a_u05_projection_multisegment_order_and_limits`. Build two committed native segments from input `0..4` and `4..8`. Discover canonical segment ordinals from pristine physical keys. Select four interleaved positions `[7,0,5,2]` plus a duplicate `[7]`; assert expected fields and output rank exactly, each segment verifies its own physical keys, two `stored_calls`, full ownership zero. On a fresh admitted snapshot with both key directories empty, first success must scan exactly twice (8 rows total); fresh subsequent call must direct-read five selected positions and scan zero. For wrong key in first canonical segment (choose its first selected position by actual segment ordinal) assert mismatch, `stored_calls==0`, ledger 0. For wrong key in second canonical segment assert mismatch, `stored_calls==1`, earlier segment's exact charge remains in private ledger as existing semantics; use empty field projection for failure rows so expected charge = 33 * number of selected positions in first canonical group (derive from prescribed input and canonical order before running). No partial successful response. Do not change to all-segment pre-validation or global atomic ledger rollback: this function's ledger is private and previously charged groups remain until caller cleanup. Verify reader guards release on both exits.

### U06 — logical projection ledger and batch sink parity

`perf07a_u06_projection_exact_and_one_under_batch_memory`. N=4 with selected two valid positions `[1,0]`, same fields-empty plan, exact 33 bytes per hit. Standalone ledger 66 -> success, used 66; 65 -> exact `SearchError::ResourceLimit { limit:65, requested:66 }`, private ledger used 33 (first reservation survived, second atomic rejection); same snapshot new ledger 66 -> success. Repeat with real `BatchMemoryMeter`/`SlotMemoryScope` from existing `e_projection_exact_and_one_over` tests: local generous cap, batch 66 -> success, `temporary_bytes()==66`, drop scope => meter.current()==0; batch 65 -> exact `SearchError::Query(QueryError::BudgetExceeded { kind: BudgetKind::BatchMemoryBytes })`, because the inspected `BatchMeterError::to_search_error` maps to that query error, not `ResourceLimit`; local used 33 and temporary_bytes 33 before drop, meter zero after drop; local 65 / batch 66 -> exact local `SearchError::ResourceLimit { limit:65, requested:66 }`, same balances. Use the literal typed pattern for each of the six cases. Do not broaden error matching. Each case opens real projector, keys verified before STORED; no full key cache, and reader guard released. Confirm existing cancellation tests and C3 U09 projection refusal run unchanged. Use no new charge and no change to caller cancellation schedule.

## 8. Real-boundary integration acceptance

Keep the full existing integration inventory and all previous C2/C3 acceptance tests. Append **two local tests** to `crates/quervant-core/tests/perf06_c2_physical.rs` and **one ignored real-RustFS test** to the existing `crates/quervant-core/tests/pr15g_b_rustfs.rs` target so the current hosted job automatically executes it. Do not alter existing integration helpers or test registration except adding private new helper(s) with prefixed names. No new CI trigger/job, new Cargo target manifest or test framework. Unit tests do not replace this integration.

### I01 `perf07a_i01_real_fs_multi_hit_scores_and_projection`

Use `reopen_scoring_corpus("perf07a-i01", 1100, 1000)` (two committed segments: 1000 and 100). Existing helper uses genuine `FsDirectory`, closes writer/index, reopens with the existing scoring schema, registry and limits; assert two segments with counts [100,1000] ignoring native ordinal order. All 1100 documents contain `alpha`; known input field lengths from existing `scoring_dl` formula. Compute total `sum(1+i%4+i%5 for i in 0..1100) = 4950`, df=n=1100; assert literal 4950 before search. `request(text_term("body","alpha"), K, doc_id_sort(direction), scoring_projection())`; K=1,10,100, directions Asc/Desc, each executed twice on same snapshot. Expected index order for first page `0..K` ascending or `(1100-K..1100).rev()` descending, key `scoring_doc_key(i)`, complete ordered projection `(doc_id, body)` from `scoring_doc_key(i)`/`scoring_body(i)`, and **score bits** from existing independent `scoring_oracle(scoring_tf(i), scoring_dl(i),1100,1100,4950)`. Assert `total_hits=1100`, response hit length=K, aggregation None, next_cursor Some for every first page. Assert `assert_eq!(repeat, first)` (the inspected `UnifiedResponse` derives `PartialEq`) plus explicit scalar score-bit checks and literal oracle for each repeated response. Do not drop the cursor assertion. Follow one continuation for each of the K10 and K100 directions from first page, expected next consecutive K input indices, exact fields and score bits and total, next cursor Some. **16 page executions**: 12 first-page calls + 4 continuations. No timing. Both segments can contribute across the selected directions; do not assume physical order. Note that the 1024 threshold is exercised by U01; here two real segment sizes are deliberately different.

### I02 `perf07a_i02_real_fs_pit_upsert_delete_compact_projection`

Use `reopen_scoring_corpus("perf07a-i02", 40, 6)` and hold the original `Arc<ReaderSnapshot>`. Unlike the retained C3 I02 case (where the upsert removes alpha and leaves 39 matches), this test **keeps the updated key matching but changes its stored content and score**. That distinction directly exercises physical identity when both snapshots return the same logical key. Use the existing `request`, `scoring_doc_key`, `scoring_body`, `scoring_tf`, `scoring_dl`, and `scoring_oracle` helpers. Do not change `collect_pages` (it is specifically scoped to old C3 K3 acceptance).

Fixed lifecycle:

1. Old 40 documents `0..40`, df=n=40, total field length 180. Use `text_term("body","alpha")`, K=10, `doc_id_sort(Asc)`, `scoring_projection()`. Traverse the four pages and retain complete old responses including first cursor. The old body at index 6 has tf=3 and dl=4.
2. On the real writer delete `s0002` (dl=5), upsert `scoring_document(6)` with only `body` replaced by literal `"alpha alpha alpha alpha gamma gamma"` (tf=4, dl=6, still a match), insert `scoring_document(40)` (tf=1, dl=1), commit and `writer.refresh()` exactly as in existing C3 I02. New indices `0..=40` excluding only 2, new df=n=40, total length **178** (=180−5−4+6+1). Assert all these facts from the fixed input, not search output. Fresh first page includes s0006 with the new body; old still contains original body. An old cursor against the new snapshot must yield `SearchError::Query(QueryError::InvalidQuery(InvalidQueryReason::CursorPitMismatch))`.
3. Traverse all four fresh pages; then traverse all four original pinned pages again. Assert pinned responses exactly equal the saved old responses (`UnifiedResponse: PartialEq`, plus explicit bitwise score checks). Compare fresh and old sequences to their respective literal input-derived lists; neither may show duplicate keys. Verify updated s0006 exists in both, but with different body and score bits determined by each phase's scalar oracle.
4. Run `let mut writer=index.writer().expect(...); writer.compact().expect(...); writer.commit().expect(...);` in a block, then `Index::open_with_limits(Arc::new(FsDirectory::open(temp.path()).expect(...)), schema.clone(), AnalyzerRegistry::builtin(), large_index_limits())`, exactly as in the existing C3 I02. Assert compacted segment count=1, and obtain new snapshot. Traverse four pages with the fresh oracle from step 2; compare keys, complete fields, score bits, totals and cursor presence/termination with the post-mutation phases. Do not require opaque cursor byte equality across distinct snapshot bindings. Traverse all four original snapshot pages again and assert exact saved old responses.

A private prefixed I02 helper takes `&UnifiedSearcher`, `&ReaderSnapshot`, `&UnifiedRequest`, `updated: bool`. It builds literal expected sequence from `0..40` (old) or `0..=40` excluding 2 (updated). `for page_index in 0..4`: clone request, attach previous cursor, execute, assert total_hits=40 and exactly 10 hits, aggregation None, `response.generation == snapshot.generation()` and `response.view_ordinal == snapshot.view_ordinal()`, and each hit at input index `expected[10*page_index+rank]`. For updated index 6 only use the literal new body/tf/dl; all others use old input helper. Assert exact two-field projection order, score bits `scoring_oracle(tf,dl,40,40,180 or 178)`, key, and cursor Some iff page_index<3. Return four actual complete responses for parity comparisons; no extra query after page 4. All five phases have 4 pages/40 hits, **20 successful page calls / 200 per-hit checks**, plus one rejected cross-snapshot cursor call. This is additional, distinct A-specific physical-key evidence; retain existing C3 I02 unmodified. No timing.

### RF01 `perf07a_rf01_real_rustfs_multi_hit_cold_and_warm_projection`

Append to existing `pr15g_b_rustfs.rs`, under its existing `#![cfg(feature="s3")]`, `#[test] #[ignore = "requires a running pinned RustFS instance"]`. Reuse `schema()`, `registry()`, `document()`, `require_env()`, `run(...)`, `request(...)`, `search(...)`, `keys(...)`, and actual `S3ObjectStore`/`RemoteIndex` create and reopen path. **Do not reuse the existing `remote_config()` prefix**: its process-wide `run_id()` is stable for the original test. New `RemoteConfig::new(RemoteKeyPrefix::parse(format!("perf07-a/rf01-{}-{}", std::process::id(), run_id())).expect(...), std::env::temp_dir().join(format!("quervant-perf07a-rf01-{}-{}", std::process::id(), run_id())))`. Unique namespace and workspace, check workspace is not existing; never delete another task's path. Use existing S3 test environment only with approved test endpoint. Create bucket if absent, real remote index, one writer commit containing 1100 documents with keys `format!("d{i:05}")`, title `"common"`, n=i, tag `t{i}` from existing `document`. Assert generation1. Drop writer and index before removing this test's own disposable local workspace. Reopen from authoritative RustFS using same prefix and new empty workspace. Snapshot one committed segment, actual doc_count=1100. Execute MatchAll `SortField::new("n", Asc)` and Desc, K=10 and K=100, four cases, each twice on same snapshot. For each: total_hits=1100, exact literal ordered keys from input indices (`0..K` or `(1100-K..1100).rev()`), complete `title,n,tag` projection fields of every hit, score None for typed-neutral MatchAll as existing engine behavior, next cursor Some, aggregation None. The inspected unified path determines `scoring = !plan.positive_lexical.is_empty()` and sets selected score `None` when scoring is not included; MatchAll is not a positive lexical leaf. This is the literal score-none oracle. First acquisition after reopen is a real cold local-cache lifecycle, not a process-cold timing experiment. Capture provider transfer request count after first four cases, then run the same four cases again and require no additional provider GET/requests via existing `reopened.transfer_stats().requests()` (match existing GB-R01). Compare all response data and rank; 8 requests, 440 returned-hit checks (2*(10+100)*2). Drop snapshot/reopened, remove only own disposable local workspace; never remove shared bucket, unrelated prefixes or authoritative remote data. Service cleanup only if task-owned per §9. Existing GB-R01 and entire hosted RustFS target remain intact.

## 9. Ordered execution, exact verification and evidence

Use the actual repo-supported tools. `rustc +1.98.1 --version`, `cargo +1.98.1 --version`, `rustc +1.85.0 --version`, `cargo +1.85.0 --version`; require 1.98.1 and 1.85.0 matching current CI/AGENTS. No dependency update or substituting another compiler. Record `cargo llvm-cov --version`, `git --version`, `python3 --version`. Disable inherited `QUERVANT_PR15I_*` experimental overrides and `RUST_TEST_THREADS` override; do not change production features or runtime strategy. Do not dump credential values. Use normal parallel test runner unless the real RustFS target requires serial.

### 9.1 Evidence capture without creating a second framework

Create a task-owned untracked evidence directory under `target/perf07-a-evidence/` before executing commands; if it already exists, D04. Save **stdout and stderr together, losslessly**, separate file for each command, plus a TSV/JSON command index with exact argv, toolchain, commit, tree, start/end UTC, exit code, and log relative path. Shell `set -o pipefail`; do not hide failures through `tee`. No heavy receipt/certification framework, no rerun solely to reconstruct a missing historical attachment. The exact runner shell function below is sufficient; copy into task-owned `target` script, source it in one bash shell. Never store secrets in argv or logs. `git status --porcelain --untracked-files=no` must be clean at final TESTED; before RED intermediate commit use explicit stage of observation-only files and record the actual tree. Use absolute evidence path. `command.tsv` is an audit index, not an approval gate.

```bash
set -u -o pipefail
ROOT=$(git rev-parse --show-toplevel) || exit 1
cd "$ROOT" || exit 1
EV="$ROOT/target/perf07-a-evidence"
mkdir -p "$EV" || exit 1
record() {
  local label="$1"; shift
  local log="$EV/$label.log" start end rc sha tree argv
  if [[ -e "$log" ]]; then printf 'refusing existing log: %s\n' "$log" >&2; return 125; fi
  sha=$(git rev-parse HEAD) || return 125
  tree=$(git rev-parse HEAD^{tree}) || return 125
  start=$(date -u +%FT%TZ) || return 125
  printf -v argv '%q ' "$@"
  "$@" >"$log" 2>&1
  rc=$?
  end=$(date -u +%FT%TZ) || return 125
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$label" "$sha" "$tree" "$start" "$end" "$rc" "$argv" >>"$EV/commands.tsv" || return 125
  tail -n 12 "$log"
  return "$rc"
}
```

Use `record label ... || { ...stop dependent work...; }` or explicit `if` check for **every** required command. Do not run downstream dependent commands after failure. The single expected RED is handled separately. Do not delete/reuse labels. If a prescribed repair leads to a new tested revision, fresh labels prefix `recheck-<revision-short>-`; preserve all previous logs. Record `git diff --check`, all modified paths, SHA-256 of each retained log, and full `git diff BASE..TESTED` in scratch. Do not commit megabytes of repetitive logs unless needed to establish exact failure; retain raw locally and supply exact selected focused logs + concise summaries in repo, as specified below.

### 9.2 G0 baseline and G1 expected RED

On admitted BASE with branch clean, run and capture:

```sh
cargo +1.98.1 test -p quervant-core --lib gbu16_doc_keys_zero_one_and_many_match_legacy -- --nocapture
cargo +1.98.1 test -p quervant-core --lib phase3_projection -- --nocapture
cargo +1.98.1 test -p quervant-core --lib phase5_i07 -- --nocapture
cargo +1.98.1 test -p quervant-core --lib -- --list
cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list
cargo +1.98.1 test -p quervant-core --all-features --test pr15g_b_rustfs -- --list
```

The baseline list commands establish the exact registered-test inventory (parse lines ending `: test`, not benchmarks; compare names rather than substring totals). Assert selected baseline tests actually execute, not zero selected. Baseline test suite is focused because this task changes only projection/key accessor; the full workspace final suite is mandatory. Capture failures and apply classification; do not call a known-passing previous C4 check a current baseline execution.

Add only P0 and U01. Format changed Rust files using supported stable formatter, confirm no unrelated changes, commit `test(perf07a): witness repeated full-key projection`. Run `record red-u01 cargo +1.98.1 test -p quervant-core --lib perf07a_u01_projection_prepared_offsets_no_full_keys -- --nocapture` once. Must exit 101 with exactly one selected test, actual `full_owned=1100`, expected 0, and named assertion. Preserve log and commit SHA. The subsequent P1–P4, remaining tests and final verification are automatically authorized. No baseline reread/run campaign is authorized solely for comparison after success.

### 9.3 G2 implementation and targeted acceptance

Apply P1 → P2 → P3 → P4 exactly. Add R/U/I/RF cases with fixed oracles. Use `cargo +1.98.1 fmt --all` only to format changed Rust files; if it changes unrelated paths, restore **only the agent's own formatting modifications** from the admitted source or stop if ownership uncertain. Never format historical evidence. Run focused new tests with actual logs, first green U01 individually, then reader and projection groups. Do not run real benchmark or profiler. Before final immutable test commit inspect source boundary and every invariant; no unexplained failed test. Commit code and tests only: `feat(perf07a): verify selected projection keys without full decode`. Set `TESTED=$(git rev-parse HEAD)`; clean tracked tree. Record source diff and inventory. All final QA executes on exactly this immutable commit. Mechanical fix after TESTED -> new commit and repeat affected checks including complete final QA; do not relabel old receipts.

Final focused commands (record distinct labels):

```sh
cargo +1.98.1 test -p quervant-core --lib perf07a_u01_projection_prepared_offsets_no_full_keys -- --nocapture
cargo +1.98.1 test -p quervant-core --lib perf07a_r -- --nocapture
cargo +1.98.1 test -p quervant-core --lib perf07a_u -- --nocapture
cargo +1.98.1 test -p quervant-core --lib column_geometry_tests
cargo +1.98.1 test -p quervant-core --lib b3_key_identity_tests
cargo +1.98.1 test -p quervant-core --lib phase3_projection
cargo +1.98.1 test -p quervant-core --lib phase5_i07
cargo +1.98.1 test -p quervant-core --lib g_b0
cargo +1.98.1 test -p quervant-core --lib e_projection
cargo +1.98.1 test -p quervant-core --lib c2_tests
cargo +1.98.1 test -p quervant-core --lib c2_physical_tests
cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --nocapture
cargo +1.98.1 test -p quervant-core --lib -- --list
cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list
cargo +1.98.1 test -p quervant-core --all-features --test pr15g_b_rustfs -- --list
```

Require 9 new R tests, 6 new U tests, and 2 added I tests in existing `perf06_c2_physical` target (12->14 on pinned baseline); RF target 1->2 ignored tests. Check exact test-name sets against baseline + prescribed names, no removals, ignored/scope changes or renames. All tests pass when executed, including old C2 and C3 inventories. `perf07a_r` and `perf07a_u` prefixes are unique to new registrations on BASE; if another existing name matches, report exact list, do not rename it. The new tests live in existing modules; full names include module prefix. A counter value measured in candidate collection is not proof of projection counts. Report rows with actual labels/observations, not just total count.

### 9.4 G3 real RustFS topology

RF01 and GB-R01 must both actually run locally using the existing production S3 adapter (`--all-features`, ignored harness, serial). Use a task-owned isolated service, pinned image exactly as `.github/workflows/ci.yml`, unless a preconfigured local approved **test-only** service is supplied (then do not destroy it). Do not send credentials to an unknown/non-test remote endpoint. If absent, use the following fixed local topology: Podman if installed and usable (`podman info`), otherwise Docker if installed and usable (`docker info`); no daemon/host modifications or privilege escalation. `127.0.0.1:19007` host port, 9000 container port, image `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`. Name `quervant-perf07a-<pid>`; prove name and port unoccupied (port conflict -> D16 STOP, do not kill other service). Use disposable test credentials matching the CI example, distinct bucket `quervant-perf07a-<pid>`, region `us-east-1`. These are task-created credentials only; no real credentials committed. Use exactly this pattern, capture service IDs and health outcome (not secrets):

```bash
# Set RUNTIME to podman or docker by the rule above, only if no approved test service.
NAME="quervant-perf07a-$$"
IMAGE='rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c'
# Verify name and 19007 free before running. Do not reuse an existing name.
"$RUNTIME" run -d --rm --name "$NAME" -p 127.0.0.1:19007:9000 \
  -e RUSTFS_ACCESS_KEY=quervanttest -e RUSTFS_SECRET_KEY=quervantsecret "$IMAGE"
# Require successful run and record actual ID; register cleanup of exactly that container.
export QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:19007
export QUERVANT_RUSTFS_REGION=us-east-1
export QUERVANT_RUSTFS_BUCKET="quervant-perf07a-$$"
export QUERVANT_RUSTFS_ACCESS_KEY=quervanttest
export QUERVANT_RUSTFS_SECRET_KEY=quervantsecret
# Health polling: at most 30 attempts 2 s apart; real service prerequisite,
# not CPU-load stability and not a test retry. Check success before proceeding.
healthy=0
for i in $(seq 1 30); do
  if curl -fsS --max-time 2 "$QUERVANT_RUSTFS_ENDPOINT/health" >/dev/null; then healthy=1; break; fi
  sleep 2
done
[[ "$healthy" = 1 ]] || exit 1
```

Run `record rustfs-gb-rf01 cargo +1.98.1 test -p quervant-core --all-features --test pr15g_b_rustfs -- --ignored --test-threads=1 --nocapture`. Require 2 passed, 0 failed, 0 ignored with actual named bodies, not an environment SKIP. Also run `cargo +1.98.1 test -p quervant-core --all-features --test perf06_b1_rustfs -- --ignored --test-threads=1` as the adjacent immutable ordinal/reader real-service regression; require actual existing bodies execute. No need to launch a separate production full remote benchmark. Normal hosted CI executes its own complete required real-RustFS suite. Clean up **only** the task-owned container and disposable local workspace, even on failure; never run container-system prune or destroy shared volumes/buckets. If no usable real service after bounded setup, D16: local real-service gate BLOCKED, continue independent checks and publish draft evidence, not ready. A fake provider or hosted green result alone cannot substitute for local required execution.

### 9.5 G4 mandatory final quality gates on immutable TESTED

Run all commands below in this order with the recorder, using the supported toolchains; both feature regimes are required for Clippy/tests/coverage/doc. Do not run extra benchmark acquisition. Stable `--all-targets` may execute Criterion harnesses in test mode; report those separately. `cargo bench --workspace --no-run` compiles only. `cargo doc` builds docs, does not establish a doctest run; do not mislabel. No new CI triggers; do not manually dispatch duplicate CI.

```sh
cargo +1.98.1 fmt --all -- --check
cargo +1.85.0 fmt --all -- --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 clippy --workspace --all-targets -- -D warnings
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.98.1 test --workspace --all-targets
cargo +1.98.1 test --workspace --all-targets --all-features
cargo +1.85.0 test --workspace --all-targets
cargo +1.85.0 test --workspace --all-targets --all-features
cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.98.1 doc --workspace --no-deps
cargo +1.98.1 doc --workspace --all-features --no-deps
cargo +1.98.1 bench --workspace --no-run
```

Use the actual installed coverage subcommand for pinned 1.98.1 and the required llvm-tools component. If missing, attempt standard toolchain/component setup; if blocked D15. Report `TOTAL` **Lines / Missed Lines / Cover%** from the named line columns, not Regions. State total, covered (=total−missed), missed, percent for both feature regimes. Require >=85% in each with successful exit. No exclusions or changed thresholds. Inspect uncovered new production branches and the test matrices; add no unplanned test or production logic to game coverage. If a coverage/behavior gap requires a new design or test outside the matrix, stop and report.

Run existing adapter-contract regression `cargo +1.98.1 test --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml` (tests only, no benchmark). Run and record `bash benchmarks/scripts/test-scripts.sh`, the exact existing CI script command. Do not modify it or its expected outputs. Since framework/Python and scripts are frozen and unchanged, no local benchmark-framework unit campaign is necessary; ordinary hosted CI executes it. No changes to benchmarks or CI to accommodate this task. Verify `.github/workflows/ci.yml` unchanged, including default PR and main triggers. Full QA receipts must identify actual TESTED commit/tree and success; inventory/test-count reporting must distinguish top-level libtest result summaries from any nested child process summaries and Criterion smoke runs, disclose ambiguous/interleaved output, and never claim a doctest run that didn't execute.

### 9.6 G5 source freeze, reports, remote verification and CI

Allowed file list:

| Kind | Exact path / allowed regions |
|---|---|
| Production + unit tests | `crates/quervant-core/src/segment/reader.rs`: new verifier and helper functions; scanner wrapper/body transformation; cfg(test) counter and fault seam; cfg(test) R tests in `column_geometry_tests`; existing full/stored/direct functions only cfg(test) observation statements. Existing scalar `doc_key_selected`, `bind_key_identity`, full key cache semantics, `VerifiedSegmentState`, `ValidatedOffsets::range`, `MetadataMeter`, and STORED production body unchanged. |
| Production + unit tests | `crates/quervant-core/src/search/unified.rs`: one prescribed block and doc comment in `project_selected_hits`; new U tests/helpers in existing `c2_tests` module. No other production change. |
| Integration | `crates/quervant-core/tests/perf06_c2_physical.rs`: append I01/I02 and private prefixed helpers only. |
| Integration | `crates/quervant-core/tests/pr15g_b_rustfs.rs`: append RF01 only, optionally helper for its own unique config; no changes to old test. |
| Docs | `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md` (dated A addendum describing shared certificate, local cache, one scan, first-use/refusal, actual verification; preserve earlier text). |
| Docs | `docs/PERF_OPTIMIZATION_ROADMAP.md` (append dated A implementation status with report link, leave historical C4 and A–I register unchanged except clear current status amendment). |
| Docs | `docs/pr-artifacts/perf-07-a/PERF07A_DETAILED_IMPLEMENTATION_PLAN.md` verbatim copy; `PERF07A_EXECUTION_REPORT.md`; `evidence/` containing selected raw focus/RED logs, command index, coverage summaries, source-scope/check records. |

Use these exact dated documentation additions, replacing `<UTC date>`, `<TESTED>` and `<local/hosted status>` with actual factual values. Do not claim verified completion if a gate is blocked.

In `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md`, append:

```markdown
### PERF-07-A — selected physical-key verification in projection (<UTC date>)

Final projection verifies every selected physical key in original selection order before STORED processing for that segment. A ready validated DOC_KEYS offset directory is reused from the exact immutable verified state; no full query-local key cache is built. A pre-existing full local cache is borrowed. Otherwise one shared semantic validation scan compares selected expected keys using bounded O(K) scratch without constructing unselected owned keys. A first-use admitted directory captures offsets during that same scan. If optional metadata admission fails before scanning, perform the one validating fallback; if it fails after a completed scan, reuse the private comparison outcome without rescanning. Invalid or unselected corrupt keys retain the established typed failure ordering. Complete directory publication and RAII metadata accounting remain unchanged. No wire-format, public API, logical-budget, or storage-lifecycle change.

Implementation/tested source: `<TESTED>`; verification: <local/hosted status>. See [PERF-07-A execution report](../pr-artifacts/perf-07-a/PERF07A_EXECUTION_REPORT.md). This is structural correctness evidence, not measured warm-performance qualification; PERF-07-I owns timing.
```

In `docs/PERF_OPTIMIZATION_ROADMAP.md`, append:

```markdown
## PERF-07-A implementation status (<UTC date>)

Selective multi-hit physical document-key verification is implemented on `dev/perf07-a`, tested revision `<TESTED>`; <local/hosted status>. The existing verified DOC_KEYS offsets are reused; the one-scan borrowed fallback preserves complete validation and original selected-key error precedence without reconstructing N owned keys. The existing STORED projection, scores, exact counts, ordering, reader admission and logical budgets are unchanged. Plan: [PERF07A_DETAILED_IMPLEMENTATION_PLAN.md](pr-artifacts/perf-07-a/PERF07A_DETAILED_IMPLEMENTATION_PLAN.md); report: [PERF07A_EXECUTION_REPORT.md](pr-artifacts/perf-07-a/PERF07A_EXECUTION_REPORT.md). Independent acceptance remains pending. No real benchmark or measured speedup claim; B–I are not started.
```

If implementation is blocked before complete, replace the first sentence with actual implemented/blocked status; never say the mechanism is delivered if unimplemented. This is factual reporting, not authority to redesign. Resolve the new relative links against committed paths. Do not update historical status amendments retroactively.

All other paths protected (including Cargo files, scripts, adapters, C4 evidence/results/configs, snapshot/cache/metadata code, other reader accessors, parser/codec, all historical tests/fixtures and docs, CI). No new persistent feature/version, no public type change, no `SegmentStore`/`SegmentCache`/`ObjectStore`/`Directory` change. `git diff --name-only BASE..TESTED` must equal the four executable/test paths; TESTED..DOCS_FINAL only named docs. Inspect full diff and use `git show BASE:<path>` vs `git show TESTED:<path>`; explicitly list old functions whose production bodies are unchanged and verify original tests untouched. Scanner move is the only allowed refactor of existing parser body; review original and new bodies mechanically (strip inserted cfg(test) statements, wrapper/callback and early_range substitution, compare remainder). Check `project_selected_hits` prefix/suffix outside replacement equal. Ensure no production flags/counters, panic, unsafe or lint suppressions added. Use `git diff --check BASE..TESTED`, `git diff --check BASE..HEAD`, `git diff --check TESTED..HEAD`, `git diff --check`, `git diff --cached --check`; record results; unexpected new whitespace STOP or narrow authorized docs correction. Do not rewrite historical whitespace/evidence.

Execution report must include:

- exact BASE, ROADMAP predecessor/merge, RED, TESTED, TESTED tree, final remote HEAD (latter in PR body/terminal to avoid self-referential hash); plan hash and source anchor table; branch/PR identity; prior untracked preserved; source audit and worksheet;
- R/U exact named tests and row outcomes with actual structural counts and typed error checks; RED and GREEN raw logs; I/RF real lifecycle topology, input checks and score/field/cursor/count outcomes; proof of actual remote body execution and cleanup;
- both stable/MSRV and feature regime results, coverage line columns, top-level and child counts separated, all exact commands/exits, failures classified with evidence; no claims of unexecuted suites;
- retained directory charge and direct-vs-scan counts, allocation vs read distinction, post-scan synthetic refusal evidence explicitly labelled, boundary/cancellation/resource limits and residual risks;
- final status `PERF07_A_IMPLEMENTED_CORRECTNESS_VERIFIED_READY_FOR_REVIEW` only when all local correctness/QA and required real service checks PASS and hosted exact-head checks confirmed. If hosted pending, `PERF07_A_LOCAL_ACCEPTANCE_PASS_CI_PENDING`; if any mandatory gate blocked, `PERF07_A_BLOCKED_<specific reason>`. No performance qualification or measured gain. No status `DONE` or baseline promotion before independent maintainer review. No auto merge.

Avoid evidence recursion: commit docs/report/selected logs once after TESTED; `DOCS_FINAL` must change docs only. Stage only the explicit allowed paths. PR body/terminal receipt records DOCS_FINAL, remote verification and eventual hosted job state; do not add another commit solely to store its own CI SHA. Store concise machine-readable manifest of selected committed evidence with SHA-256 and size; use standard `sha256sum`/Python hashlib; not a new admission/authorization system. Focused evidence committed: red-u01.log; final green-u01, R and U group logs; real I target log and RF target log; final command index; actual baseline/final inventories; both raw TOTAL line rows and command exits; source-freeze/diff check summary. Retain full workspace logs under task-owned `target` and deliver actual files if reviewer requests them, not an inaccessible path as a claimed uploaded artifact. No unrelated data or credentials in evidence. This plan requires no external terminal ZIP unless maintainer asks; committed focused logs and PR body/terminal are the handoff.

Push `git push -u origin dev/perf07-a` non-force. If independent source branch moved remotely, stop push, preserve local work. Create one draft PR to main using `gh pr create --draft --base main --head dev/perf07-a --title 'PERF-07-A: selective multi-hit physical key verification' --body-file <task-owned prepared body>`. If the PR creation response is lost, inspect remote under D22: reuse only the newly created draft PR whose exact head, base and body match the prescribed values; otherwise stop rather than create a duplicate. D03 admits no prior partial implementation PR. Read back `gh pr view ... --json headRefOid,baseRefName,isDraft,state,url,body` and `git ls-remote --heads origin dev/perf07-a`; require local HEAD == remote == PR head and base main. No force, no merge, no ready-state change. Ordinary CI auto-starts; inspect existing `pull_request` run bound to final head, all required jobs (`rust`, `msrv`, `rustfs`, `benchmark-adapter-contract`, `python-benchmark-framework`); record run/job URLs and actual conclusions. Poll at most 20 times at 30-second intervals; do not re-dispatch or cancel; if pending after bound, deliver pending status with actual evidence, no further authorization prompt. Inspect real RustFS job log for RF01 and GB-R01 test result lines if available; job success alone does not prove exact bodies without log or equivalent receipt. If CI failure, D19, no retry-to-green. The user requested a detailed implementation plan, not merging.

After completion check disk usage (repository maintenance policy); if >=60%, use repository-approved `disk-cleanup.sh --apply --yes --purge-root-target --allow-podman-repair --allow-podman-reset` **only after preserving the task evidence and confirming cleanup cannot destroy untracked work/evidence or other active tasks**. If safety cannot be established, record deferred cleanup instead of deleting data. No maintenance during measurements (none here).

## 10. Cross-component and residual-risk matrix

| Component/path | Change | Required regression / constraint |
|---|---|---|
| `SegmentReader` full decode/scalar access | production unchanged; shared scanner visitor extracted | existing gbu16–28, existing key identity tests, full suite. |
| Verified state/cache and reader guard | reuse only, no new state or admission policy | R02–05/R08–09, existing metadata/state tests, U05/U06. |
| `UnifiedSearcher` projection (all search variants) | use one verifier; same grouping/projection ledger | U01–06; C2/C3 full integration, batch, typed, PIT. |
| `IndexWriter`, compaction, manifest and mutation | unchanged | I02, existing local lifecycle/real remote tests. |
| `Directory`, `SegmentStore`, `SegmentCache`, `ObjectStore` | unchanged | RF01 real provider and existing real tests; no remote per-key I/O. |
| `DOC_KEYS`, STORED, columns, postings | no encoding/version change | old codec/legacy fixture tests, R06, full suite. |
| Public query/result/scoring/cursor | unchanged | I01/I02 bitwise/field/cursor parity, retained C3 tests. |
| Adapter/benchmark | unchanged | compile/test adapter; no timing. |

Residuals to disclose: (1) actual elapsed savings are unmeasured until I; (2) cold first-use still validates N keys and may allocate an N+1 u64 metadata directory; (3) refusal still scans N once per projection group, so does not promise O(K) latency for unmetered readers; (4) existing STORED certification, live state, and other collector work may still be substantial; (5) initializing offsets in projection can consume part of existing shared optional metadata budget earlier than before, potentially changing which later optional accelerators are admitted, without relaxing semantic limits. Test exact pressure and fallback; report retained metadata and possible operational tradeoff for I. No new cache policy in A. (6) Actual allocator failures have a changed physical allocation footprint; no assertion of identical OOM behavior. (7) Existing cancellation checks are preserved, not redesigned. These are explicit scope limits, not permissions to weaken correctness or future performance gates.

## 11. Acceptance gates and handoff

| Gate | Required evidence |
|---|---|
| G0 | Reviewed roadmap merged, tree/source pins exact, branch admitted, baseline focused tests/inventories. |
| G1 | Counter-only RED commit, one actual U01 failure exactly 1100 vs 0, prior semantic assertions passed. Worksheet complete. |
| G2 | Exact implementation P1–P4; all 15 registered new unit tests including R/U matrices green, exact names retained; no unrelated prod changes. |
| G3 | Both real FsDirectory new tests plus old C2/C3 suite; local real RustFS RF01/GB-R01 and existing PERF06 B1 remote target pass; required lifecycle and resource checks. |
| G4 | All final QA at immutable TESTED, both toolchains/features, >=85% actual lines, exact inventory, adapter test and applicable script checks. |
| G5 | Source scope and whitespace checks, docs-only delivery after TESTED, actual evidence and PR read-back. |
| G6 | Ordinary hosted final-head CI all required jobs pass with actual RF01 body evidence. Pending remains pending. |
| G7 | Independent review and maintainer decision (not set by coding agent). |

The agent must not mark G7 PASS. The entire optimization remains correctness-only until PERF-07-I. No individual percentage threshold is fabricated. A and B are technically independent, but the roadmap orders A first; no B implementation or design is authorized here.

## 12. Preauthorized architectural decisions and exception-handling matrix

**Apply before acting.** Exact triggers only. AUTO = perform the stated action and continue without asking. DEFER = preserve evidence, continue only independent authorized tasks. STOP = halt affected work; never invent a design. If multiple rules apply, use most restrictive. Unlisted or contradictory conditions fall under D26. All failures remain visible; no weakening or retry to green. The affected gates and owner are stated explicitly. On every applied rule record its ID, observed condition, relevant source/command evidence, action and result in execution report.

| ID | Observable trigger / category | Prescribed action | Prohibited action | Evidence; affected gate / owner |
|---|---|---|---|---|
| D01 | Exact reviewed #134 merged, main complete tree and anchors match; AUTO | Pin actual BASE, create clean branch, start baseline. | Ask for confirmation or repin to arbitrary revision. | PR/tree/blob receipts; G0 agent. |
| D02 | #134 remains open/unmerged; STOP | Report predecessor not merged; no implementation branch changes. | Merge #134 or code against unapproved roadmap automatically. | PR state; G0 maintainer. |
| D03 | Local/remote branch exists at exact BASE, no prior task work or PR; AUTO | Reuse clean branch. Disjoint old untracked file outside shadowed paths may be recorded and preserved; exact-path staging only. | Reset/overwrite/force push/delete untracked files. | Branch/PR checks and list; G0 agent. |
| D04 | Main tree/anchor differs, prior partial A work/PR exists, tracked dirty tree or overlapping untracked/shadow input; STOP | Record precise mismatch and preserve all work. If exact same already delivered branch is found, report it for review rather than implement twice. | Rebase/cherry-pick, choose new base, clean/reset or improvise recovery. | SHAs/status/diff; G0 maintainer. |
| D05 | Baseline focused command exits nonzero or selects zero intended tests; STOP dependent implementation | Capture exact command/log; distinguish environment vs observed baseline failure. If purely missing supported tool, D15 setup; no source repair. | Call it flaky, ignore or alter baseline. | G0 baseline log; reviewer. |
| D06 | U01 RED executes exactly one test, semantic assertions pass and fails 1100 vs 0 at named assertion; AUTO | Record expected red, continue P1–P4. | Stop for permission or treat intentional failure as unexpected. | RED SHA/log; G1 agent. |
| D07 | Unexpected fixture layout, typed result, test baseline contradiction, expected counts/offset size or red mismatch; STOP | Record input, actual/expected and source. Preserve valid other evidence. | Change data, expected values, assert broad error type, skip test or tune threshold. | Affected G1–G4; plan author/maintainer. |
| D08 | Purely mechanical Rust compile/lint issue in authorized new region (lifetime elision, type annotation, import path, rustfmt, idiomatic equivalent required by MSRV, no behavior or error order change); AUTO | Make smallest correction and record exact diff/reason; repeat affected checks. If after TESTED, new immutable TESTED and full final QA. | New lint suppression, new public API, new algorithm, broaden files, edit test expectations. | Compiler log/diff; G2/G4 agent. |
| D09 | Already-ready shared offset directory, or full local cache (runtime table); AUTO | Use corresponding exact verifier route. | Build second directory or full-key cache. | R01/R02 counts and ptr; G2 agent. |
| D10 | Optional directory pre-scan capacity refusal/no access account/sticky None (runtime table); AUTO | One borrowed full validation scan and no full ownership. | Loop scalar selected accessor, retry budget, enlarge cap. | R03/R04/U02 counts and balances; G2 agent. |
| D11 | Started scan returns corruption/limit error; AUTO expected negative / STOP unexpected positive case | Propagate exact error; no replay. Test expected corruptions as specified. | Catch and hide corruption, replace with mismatch, run second scan. | R06/U04 exact errors; G2 reviewer if unexpected. |
| D12 | Complete scan followed by post-scan `LimitExceeded`; AUTO | Return saved private parity, sticky None, no rescan. | Revalidate whole body, publish partial certificate, claim injected refusal real allocator observation. | R05 actual finalize path; G2 agent. |
| D13 | Complete valid scan with parity mismatch or invalid ordinary ID; AUTO | First original selection failure after full validation; no STORED for that group. | Early return in scan, reorder error priority, use latest key. | R07/U03/U05; G2 agent. |
| D14 | Unexpected error from production candidate after eligible verified input, or failure of structural/invariant assertion; STOP | Preserve logs and state; diagnose scope only, report precise issue. | Redesign implementation, change semantic oracle, retry until green. | G2/G3; plan author. |
| D15 | Pinned toolchain/llvm-cov/tool not installed; AUTO bounded standard setup, DEFER if unavailable | Use supported rustup/component/tool installer without system mutation; rerun original command once setup resolves. If inaccessible record BLOCKED and continue independent docs/review. | Change MSRV, lower coverage, install unreviewed dependencies, substitute unrelated command. | Tool/setup output; G4 agent then maintainer. |
| D16 | Real RustFS missing/unhealthy or port/name occupied, no approved test endpoint; DEFER AND CONTINUE | Attempt fixed isolated setup once, bounded health polling. If blocked, preserve diagnostics, clean only own resources, continue local independent QA/docs/push draft with G3 blocked. | Kill unrelated service, use production provider, fake pass, silently change port/topology, force service reset. | Health/container/run log; G3 maintainer. |
| D17 | Deterministic expected corruption/resource/cancellation negative test succeeds with exact error and recovery; AUTO | Record the negative as PASS and continue. | Reclassify expected refusal as runtime failure; widen expected error. | Test row outputs; G2/G3 agent. |
| D18 | Required local QA fails or coverage below floor; STOP affected completion, DEFER independent work | Classify using evidence in §13. Only D08 corrections or D15 setup permitted; otherwise preserve failure. | Change thresholds, suppress lints, remove tests, run repeats until pass. | QA log/counts; G4 maintainer. |
| D19 | Hosted CI pending/failure/log unavailable; DEFER | Bounded poll, preserve actual run status and jobs; no success claim for missing bodies. Deliver draft with precise pending/blocked disposition. | Dispatch duplicate CI, rerun failed jobs merely to get green, modify workflows. | run/job refs; G6 maintainer. |
| D20 | Scope audit detects unexpected formatting changes from agent only; AUTO narrowly | Restore only known agent-owned unrelated formatting bytes; verify exact protected paths and rerun affected checks. Unknown changes -> D04/D26. | Restore user work, hide source changes, change historical artifacts. | diff before/after; G2/G5 agent. |
| D21 | New whitespace/report/link typo in authorized docs; AUTO | Correct only that text before docs delivery, rerun doc/diff checks, keep TESTED frozen. | Edit historical measurements or introduce new code/test changes. | G5 doc diff; agent. |
| D22 | PR body/push transient network/credential failure; DEFER | Preserve local commits/logs. One ordinary retry if command had definite non-publication and remote unchanged; otherwise inspect remote, report delivery blocked. | Force push, expose credentials, overwrite another PR, rerun tests for publication. | remote/command evidence; G5 maintainer. |
| D23 | All local mandatory checks pass; AUTO | Commit bounded docs and push/open draft, inspect hosted CI. | Wait for routine permission, merge, mark series performance accepted. | G5/G6 agent. |
| D24 | Real metadata or reader optional account is smaller than intended and genuine documented fallback succeeds with exact counts; AUTO only prescribed cases | Record actual fallback; continue fixed test table, required ready cases still must actually be ready. | Substitute fallback for required ready proof, enlarge fixture allowance after seeing failure except exact planned pressure setup. | R03/U02; G2 reviewer if contradiction. |
| D25 | Later performance work, another codec, snapshot-live caching, scoring-demand, block streaming or optimization scope seems attractive; STOP that scope | Record defer to B–I as applicable; complete only A. | Implement unrelated optimizations, run real performance samples, microbenchmark or modify benchmark policy. | G2/G5 scope; maintainer. |
| D26 | Any condition not covered by exact triggers, conflicting rules, unverified assumption, new architectural decision, or change outside allowlist; HARD STOP affected work | Preserve exact source/logs; identify smallest unresolved decision. Continue safe independent work only if demonstrably isolated. | Improvise, hallucinate a missing API, quietly waive a gate, widen rule or perform destructive actions. | Affected gates BLOCKED; plan author/maintainer. |

## 13. Failure taxonomy, final receipt and PR description

For actual failed mandatory gates distinguish introduced regression, new feature implementation defect, deterministic pre-existing failure (requires baseline reproduction or equivalent actual evidence), demonstrated nondeterminism/flaky failure (requires evidence, not merely a suspicion), or environment/harness failure. A single failing test on TESTED with no same-source nondeterminism evidence is not "flaky". A failing known baseline case is not a waiver. Unexpected RustFS/test infrastructure failure must not be called a feature pass. An exact expected RED or expected negative-case typed refusal is not a failed mandatory final gate.

Suggested PR title: `PERF-07-A: selective multi-hit physical key verification`.

Suggested PR description (fill factual values from actual execution):

```markdown
## Purpose
Remove repeated whole-segment owned DOC_KEYS construction from final selected-hit projection, using the existing validated offset directory and one borrowed validating scan when unavailable.

## Implementation
- Arbitrary-K physical parity verification in original selected order.
- Existing immutable offsets, admission and shared owner reused; first-use scan also verifies expected keys; post-scan refusal reuses that result.
- Exact count/key/scores/projection/duplicate/PIT semantics, error precedence and logical budgets retained; no format/public API/benchmark changes.

## Evidence
BASE / RED / TESTED / TESTED_TREE / FINAL / remote head: <actual>
R01–R09 / U01–U06 / I01–I02 / RF01: <actual results>
RED 1100 owned keys vs expected 0; GREEN actual direct and scan counts: <actual>
Stable/MSRV QA, actual line coverage, real RustFS and hosted CI: <actual>
Residuals and applied matrix rules: <actual>
Plan/report: docs/pr-artifacts/perf-07-a/...

No performance acquisition or speedup claim. PERF-07-I owns qualification. Draft/unmerged; independent review outstanding.
```

Final terminal handoff must give repo, branch, actual PR URL/state/draft/merged, predecessor state, BASE/RED/TESTED/tree/DOCS_FINAL/REMOTE_H, plan SHA256, exact changed paths, tested source freeze, actual R/U/I/RF names and counts (and row distinctions), observed red/green key counts, all gates PASS/FAIL/PENDING/BLOCKED, exact coverage line totals, local RustFS topology/outcome and CI run/job URLs/status, applied matrix IDs, unresolved items, artifact paths and terminal disposition. Include no inaccessible temporary file link presented as an attachment. Do not claim an uploaded package without delivery. Keep independent acceptance G7 open. No permission request after normal completion; provide next action (review and eventual PERF-07-B after acceptance).

## 14. Reviewer checklist

- [ ] #134 merged at reviewed content and BASE source matches; no unrelated changed files.
- [ ] Red is actual old projector full-key ownership, not a contrived helper; same U01 succeeds after feature.
- [ ] Exact shared scanner body reused; original scalar callers and old full decoder semantics preserved.
- [ ] `KeyParity` is request-local; direct path checks original selection order; full cache not populated; zero result work on no hits.
- [ ] Cold admitted directory publishes only after full semantic validation and exact budget; pre/post-scan refusal correctly distinguished, no retry after started scan.
- [ ] Unselected invalid UTF-8/empty/oversized/truncated/trailing bytes fail with typed precedence; ordinary invalid-ID and large singleton special ordering retained.
- [ ] Actual warm projection no N full keys, fallback exactly one scan, scratch scales with K, actual counters and exact tests; no timing/speedup claim.
- [ ] Every per-segment parity check before STORED; output ordering, duplicate positions, ledger and batch release unchanged.
- [ ] Distinct snapshots/old PITs and real local/remote lifecycle proven; actual provider execution and no warm extra requests.
- [ ] All 15 new unit registrations, 2 local and 1 remote registrations, prior tests retained; actual QA stable/MSRV and both line floors >=85%; report coverage correctly.
- [ ] No production API/format, extra cache, unsafe, lint suppression, benchmark policy or CI changes; no unrelated implementation.
- [ ] Immutable TESTED -> docs-only final, ordinary final-head CI, verified branch/PR, honest open gates. No merge/promotion.

## 15. Dependency context and authoring limitations

PERF-07-A is the first narrow implementation in the merged PERF-07 roadmap. B (postings validation lifetime) is technically independent but follows A in priority; C is snapshot effective-live reuse; D/E demand/detail; F bounded execution; G/H conditional count/seek and sort pruning; I integrated qualification. This plan authorizes none of those changes. It intentionally uses existing metadata and scanner logic rather than implementing a new index format or a wider reader cache.

The plan was authored from the actual pinned repository code and the reviewed roadmap PR. The new Rust snippets and tests have not been compiled or executed in the authoring environment. The agent must perform the prescribed red-first, correctness, real-boundary and QA verification; a planning statement is not an executed acceptance result. The predecessor was still open at authoring, so the base commit is discovered only under the exact admission conditions in §0. The design's measurable work bounds are structural; only later warm measurement can establish elapsed benefit.

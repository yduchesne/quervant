# PERF-06-A2 — Validated Document/Frequency-Only Postings Reader

**Authoritative low-reasoning-agent implementation plan — correctness first, no real benchmarking**  
**Repository:** `yduchesne/quervant`  
**Milestone / series:** `v0.1-perf` / PERF-06-A (scoring and postings efficiency)  
**Proposed individual PR:** `PERF-06-A2: Validated document/frequency-only postings decoding`  
**Proposed branch:** `dev/perf06-a2-docfreq-postings` (**new branch from accepted `origin/main`**, never from series PR #119)  
**Planning sources:** `docs/PERF_OPTIMIZATION_ROADMAP.md` (PERF-06-A2), `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`, `docs/TESTING.md`, `AGENTS.md`.  
**Source inspection date:** 2026-11-23. Last verified merged `main` was `2a74017958c8ac61948f931e8745bf8134827025`.  
**Immediate dependency:** **PERF-06-A1 PR #120**; the fixup head `657352563c0fbe23759d64d9c2ac5b3b6f7be0a6` passed CI run #535, but PR #120 was **still open/unmerged when this plan was authored**. Do not start the A2 implementation until its merge is independently verified.  
**Other related PRs:** PERF-05 #117 merged, PERF-06 planning #118 merged, PERF-06-A series charter #119 open/draft. The charter is **not** the implementation base.  
**Plan status:** design approved only when the maintainer explicitly authorizes execution; this document is **not** an assertion of implemented work or of A1 merge completion.

---

## 0. Mandatory agent execution contract

> **Continuous execution authorization:** Once explicitly authorized to execute this plan **and after the A1 merge dependency is satisfied**, execute all prescribed implementation, testing, review-evidence, commit, push and draft-PR creation work without asking for routine reconfirmation. Continue after successful preflights, successful stages, authorized AUTO-RESOLVE conditions and routine checkpoints. Stop the affected work only for an applicable HARD STOP, a genuinely missing human decision or a blocking external dependency. If a blocker can be isolated, record it and continue independent, safe, already authorized work. Never treat a routine checkpoint as a request for more permission.

**Do not interpret user authorization of this plan as authorization to merge, change query semantics, alter persistent formats, run performance acquisitions, start A3, relax tests, or decide an unanticipated architecture.** The rule above does not override the A1 dependency or any HARD STOP below.

- **Your task is implementation, not design.** Follow the exact types, method contracts, call-site substitutions and test fixtures in §§4–10. Do not choose an alternative iterator, introduce a new storage format, build a generic decoding framework, change corruption policy, invent additional caching, or redesign scoring.
- **Preflight:** verify the repository identity, exact A1 merge, correct latest `origin/main`, unchanged relevant source blobs, clean worktree, and absence of an existing A2 branch/PR. A missing A1 merge means **DEFER AND CONTINUE only with genuinely independent source audit/documentation; do not create an A2 code branch or implement against the unmerged A1 head**.
- **Quality:** all mandatory Rust local tests, both applicable toolchains, workspace coverage ≥85%, real local writer→commit→reopen→search integration and relevant hosted CI must be reported accurately. A green compile is not a passed runtime test.
- **No timing:** no `quervant-bench run`, benchmarks, profiling, Criterion, benchmark-timing loops, cross-engine Tantivy/Lucene acquisition, process-cold studies or RustFS service startup. Warm performance qualification is **A4**. `cargo bench --no-run` under a mandatory CI build job is a compile check, **not** performance acquisition.
- **Stop unknowns:** apply §12 matrix *before* making changes. When no row covers an unforeseen condition, HARD STOP dependent work rather than improvising; continue only provably independent prescribed activities.

## 1. Purpose, architectural problem, and exit condition

### Current source-proven waste

`crates/quervant-core/src/segment/postings.rs::PostingsReader::next_with` currently decodes **every positional occurrence** into an owned `Vec<Occurrence>`, constructs a full `Posting`, and clones the complete posting to retain `current` for the existing `advance_with` API. This happens even when the caller only reads `(doc_id, freq)`.

The following **four actual production loops** require no positional occurrence vectors:

| ID | Current A1-head source anchor | Role |
|---|---|---|
| C1 | `search/execute.rs::build_leaf_data`, `CompiledLeaf::Term`, approximately lines 1277–1294 | Strict and generic term postings into `TermPostings` `(doc_id, freq)` |
| C2 | `search/execute.rs::build_leaf_data`, `CompiledLeaf::MultiTerm`, approximately lines 1328–1345 | Expanded prefix/glob/regex/fuzzy term postings |
| C3 | `search/score.rs::compute_stats`, persisted-norms **partially-live** DF scan, approximately lines 466–491 | Read frequencies for scan charges and live-only DF |
| C4 | `search/score.rs::compute_stats`, **legacy no-norms** field-length/DF reconstruction, approximately lines 522–556 | Accumulate frequencies and live-only DF |

**Position-dependent consumer intentionally unchanged:** `search/execute.rs::build_phrase` at approximately lines 1409–1435 must keep the existing `PostingsReader::next_with` with full `Posting.occurrences` vectors. Existing other public full-`Posting` callers (`next`, `next_with`, `advance`, `advance_with`) remain functional and semantically unchanged.

### Exact A2 goal

Add a **consuming, type-separated document/frequency view** over the existing postings cursor, with a **single shared validation/decode routine**. The view returns only `{doc_id, freq}` and does **not** allocate an occurrence vector, retain an owned full posting, or clone one. It nevertheless parses and validates **all** positional bytes for **every** examined posting (including dead/unselected documents), with the same checked offsets, errors, resource preflight, and posting-boundary cancellation as before.

**A2 ends** when C1–C4 use this new API, phrase/full consumers still use the old API, the on-disk representation and full-reader semantics are unchanged, mandatory tests/coverage/CI pass, and the separate A2 PR is ready for independent review. There is **no speedup acceptance gate** in A2.

## 2. Source facts and immutable preflight anchors

### 2.1 Verified code identities

The inspected **A1 fixup head** (not yet `main` when authored) is `657352563c0fbe23759d64d9c2ac5b3b6f7be0a6`. Its relevant Git blobs:

| File | Expected blob at the A1 fixup head | A2 treatment |
|---|---|---|
| `crates/quervant-core/src/segment/postings.rs` | `31e2981e0be42b316668016f46436c36dc0fc143` | Modify, preserve wire decoder behavior |
| `crates/quervant-core/src/segment/tests.rs` | `213ba6e7c640411f34ec10a0988b26e76be5acba` | Add focused unit tests |
| `crates/quervant-core/src/search/score.rs` | `6f8bd0f54896aa201d932125dcf21417fb69d58c` | Modify **only** C3/C4 loops; preserve A1 prepared IDF changes |
| `crates/quervant-core/src/search/execute.rs` | `25516f05bae0631aae28a3d0e038882a3141a4ab` | Modify **only** C1/C2 loops; preserve A1 scorer/phrase logic |
| `crates/quervant-core/src/segment/reader.rs` | `aa69f2bebb9746f44254a702438e91cea9a9b7a5` | Read-only: reuse `postings` / `postings_for_entry` |
| `crates/quervant-core/src/segment/limits.rs` | `bf222b67e0675aadf6137642748d6b7f4c781328` | Read-only: reuse `check_entries` / `check_alloc::<Occurrence>` |
| `crates/quervant-core/src/segment/format.rs` | `6932edd210e3cc480342f11c4e4ca7ae5ec39e77` | Read-only: reuse `ByteReader::varint`, `expect_end` |
| `crates/quervant-core/src/segment/error.rs` | `e44e48d5a2880d1431691c51919bcdc6268060fb` | Read-only: existing typed `SegmentError` |
| `crates/quervant-core/tests/segment_codec.rs` | `7aeb5e0c1d88aa004e4f1e31f8602260c2739e88` | Add real immutable-segment reader test |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | `b418c0e36728d292b35bb5bcc7df9a9d279279de` | Add real `FsDirectory` query integration test |
| `AGENTS.md` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` | Policy read-only |
| `.github/workflows/ci.yml` | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` | CI definition read-only |

All paths and calls above were inspected, not inferred from the roadmap. `main@2a740179…` still contains the pre-A1 versions of `score.rs` and `execute.rs`; therefore **do not accidentally branch A2 from that old main**. Resolve A1 merge first.

### 2.2 Required executable preflight (from repository root)

```bash
set -euo pipefail
REPO='yduchesne/quervant'
A1_FIXUP='657352563c0fbe23759d64d9c2ac5b3b6f7be0a6'
A2_BRANCH='dev/perf06-a2-docfreq-postings'
git remote -v
git fetch origin main
gh pr view 120 --repo "$REPO" --json state,mergedAt,mergeCommit,headRefOid
# STOP: require state=MERGED, a non-null mergedAt and the A1 fixup
# to be the actual accepted PR head (or a separately approved later reviewed head).
git status --porcelain
# STOP: require no tracked or untracked source/doc changes (ignored target/ is OK).
git show-ref --verify --quiet "refs/heads/$A2_BRANCH" && { echo 'STOP: A2 local branch exists'; exit 4; } || true
# The following check MUST pass (no remote ref); otherwise STOP and do not reuse an existing remote.
test -z "$(git ls-remote --heads origin "$A2_BRANCH")" || { echo "STOP: A2 remote branch exists"; exit 4; }
# After A1 is verified merged, inspect the exact A1-head and latest-main
# blobs for *every* row of the preceding table; compare with git rev-parse:
git rev-parse origin/main
git rev-parse "origin/main:crates/quervant-core/src/segment/postings.rs"
git rev-parse "origin/main:crates/quervant-core/src/search/score.rs"
git rev-parse "origin/main:crates/quervant-core/src/search/execute.rs"
```

**Mandatory interpretation:** compare `git rev-parse origin/main:<path>` with the exact table values. For source files that A1 changed, the accepted `main` blob **must equal** its A1 fixup blob regardless of merge strategy (ordinary, squash, or rebase). For other listed files, compare to the inspected source; any unexpected delta requires HARD STOP and a source-reconciled amended plan. `gh`/GitHub API must confirm PR #120 is actually merged: ancestry alone is insufficient after squash, and a passing CI run is not acceptance.

**After all checks pass, and only then:** `git switch -c dev/perf06-a2-docfreq-postings origin/main`; record `BASE_MAIN_SHA` (`git rev-parse HEAD`) and all relevant file blobs. Confirm no existing A2 PR (`gh pr list --repo "$REPO" --state all --search 'PERF-06-A2'`). If an A2 PR/branch already exists, STOP rather than overwriting it. If `main` advances during work and any inspected source anchor changes, STOP before rebasing; never force push.

### 2.3 Scope reconciled with A1 and prior work

- A1 delivered query-local BM25 IDF preparation and updated both scorers. **Preserve it byte-equivalently outside the C3/C4 lines**. No repeated BM25 redesign in A2.
- PERF-05 delivered single-term optimized matching and score-buffer ownership. **Do not rewrite `TermPostings`, B1–B5 dispatch, score storage or evaluator**.
- `PostingsReader::next_with` and `advance_with` are public and support callers needing actual occurrences. **Do not replace them with tuples**.
- `SegmentReader::postings` and `postings_for_entry` already perform dictionary lookup, bounds and header validation. Reuse their existing returned `PostingsReader`, converting to a view **at the four consumers**. **Do not add `SegmentReader` APIs or caches**.
- A3 owns the future *new postings wire layout*. A2 **does not** alter `encode_postings_block`, dictionary, field norms, schema, manifest, feature IDs or persisted bytes.

## 3. Correctness invariants and exact acceptance traceability

| ID | Falsifiable requirement (inherited unless noted) | Code step | Tests/gates |
|---|---|---|---|
| INV-01 | For every valid postings block, full and doc/freq readers emit the **identical ordered `(doc_id,freq)` sequence**, with the same EOF transition and no duplicates. | S1/S2 | U01, U02, U07, I01 |
| INV-02 | Doc/freq decoding **reads and checks every positional field** even when no occurrence is materialized and even for an eventual dead/nonwinner candidate. No malformed posting is accepted by one mode and rejected by the other. | S2 | U03, U04, U05, U08 |
| INV-03 | Doc/freq mode performs **zero occurrence-vector heap reserves and zero `Posting` clones/caches**; full mode continues retaining `current` for `advance` and returns full occurrences. | S1/S2 | U01, U06, U07, observation counters |
| INV-04 | `PostingsReader::next`, `next_with`, `advance`, `advance_with` keep their former return values, exact errors and already-consumed-current behavior; conversion consumes the cursor and never exposes both modes on one live handle. | S1/S2 | U02, U06, U09, existing `segment_codec` |
| INV-05 | Decode budget and work accounting match before A2: `check_entries`, `max_decoded_entries`, **hypothetical `check_alloc::<Occurrence>(freq)` even without physical allocation**, work-unit charge per `freq`, candidate ledgers, and typed limit errors. | S2/S3 | U05, U08, U10, I02, existing `b4_u05` |
| INV-06 | Cancellation remains checked **once at every attempted posting boundary** (before EOF/finished guards), not silently skipped by lean decoding; no new inner-occurrence polling changes error precedence. | S2/S3 | U05, U08, existing `sc12` |
| INV-07 | Phrase/position consumers use full `Posting` with exact positions/offsets and all phrase query semantics, including corrupt positional data handling. No deferred positions, placeholder occurrence arrays or phrase shortcut. | S3 | U06, I02, existing `pr07_properties::p02`, `pr14_unified_mixed::m10` |
| INV-08 | The real `UnifiedSearcher`/`LexicalSearcher` result contract is unchanged: exact hits, total counts, live filtering, BM25 score **bits**, sort/ties, resource/cancel errors, PIT/cursor and typed/Boolean fallback. | S3/S4 | I02, existing SC01–SC15+A1, `pr07_properties`, `pr14_unified_mixed` |
| INV-09 | Same index bytes/format, writer, reader snapshot and storage objects; new API has **query-local cursor ownership only** and no global cache or durable state. | S1–S4 | Source diff audit, I01/I02, CODEC regressions |
| INV-10 | The A2 implementation introduces no benchmark acquisition, index format change, topology assumption, undocumented branch dependency or API behavior change outside prescribed scope. | All | Diff audit, report and CI |

**Pre-implementation correctness gate (mandatory):** Before production code, write a brief table mapping INV-01–INV-10 to the source anchors and planned U/I tests; challenge with: 0/1/2 postings, doc-only, 2 positional occurrences, zero/oversized freq, EOF trailing bytes, repeated doc ID, corrupt unselected later posting, cancellation at 0/1/EOF, phrase/Boolean/typed fallback, ledger exact/one-under, two segments. Apply §12 to each ambiguity. Do not improvise a changed contract to satisfy a test.

## 4. Frozen architecture — types, ownership, APIs and decoding algorithm

### 4.1 Exact new API, in `crates/quervant-core/src/segment/postings.rs`

Add these two public types in **that file** next to `Posting` / `PostingsReader`; no new module, no new trait, no dependency or stored metadata:

```rust
/// An already validated physical posting's identity and frequency.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DocFreqPosting {
    pub doc_id: u64,
    pub freq: u64,
}

/// Owns one existing postings cursor in validated doc/freq-only mode.
#[derive(Debug)]
pub struct DocFreqPostingsReader<'a> {
    inner: PostingsReader<'a>,
}
```

Add **exactly**:

```rust
impl<'a> PostingsReader<'a> {
    /// Consume this cursor and continue from its NEXT unread posting.
    /// Conversion may occur at the beginning or after a previous full read;
    /// the last full cached posting is NOT re-emitted.
    pub fn into_doc_freq(mut self) -> DocFreqPostingsReader<'a> {
        self.current = None; // drop any cached positional clone
        DocFreqPostingsReader { inner: self }
    }
}

impl DocFreqPostingsReader<'_> {
    #[allow(clippy::should_implement_trait)]
    pub fn next(&mut self) -> SegmentResult<Option<DocFreqPosting>> {
        self.next_with(&NeverCancel)
    }

    pub fn next_with(
        &mut self,
        cancel: &dyn Cancellation,
    ) -> SegmentResult<Option<DocFreqPosting>> {
        // EXACT call to the shared validated reader described below, in DocFreq mode;
        // discard the always-empty occurrence Vec. Do not call full next_with().
    }
}
```

The new types are accessible through the **already public** `crate::segment::postings` module. **Do not change** `crates/quervant-core/src/segment/mod.rs` exports; do not add public `advance_doc_freq` in A2 (no observed consumer needs it). `PostingsReader::into_doc_freq` takes ownership; the original `PostingsReader` is no longer usable, so full/lean API mixing cannot occur on a single handle. If a caller already consumed full results before conversion, continue at the **next unread** posting only, and release its cached clone on conversion.

### 4.2 A **single** validated decoder for both modes

Within the existing `impl PostingsReader`, introduce private:

```rust
#[derive(Clone, Copy, PartialEq, Eq)]
enum DecodeDetail { Full, DocFreq }

fn read_one_with(
    &mut self,
    cancel: &dyn Cancellation,
    detail: DecodeDetail,
) -> SegmentResult<Option<(DocFreqPosting, Vec<Occurrence>)>>
```

**Move** the entire existing body of `next_with` into `read_one_with`, keeping the same statement order and exact error variants/strings/contexts. Its only approved differences are:

1. At the **very start**, call existing `cancel_result(cancel)?` before `finished`/count checks. On `finished`, return `None`; on `docs_read == posting_doc_count`, call `reader.expect_end("postings")?`, set `finished = true` and `current = None`, return `None`. Do not move `expect_end` earlier or check for trailing bytes before all declared postings have been read.
2. Run exactly the original `self.limits.check_entries(self.docs_read + 1)?`; parse `doc_id` delta with its same first-doc/strictly-increasing/overflow checks; reject `doc_id >= segment_doc_count`; parse `freq`; reject `freq == 0`, then `freq > max_decoded_entries` (in that order).
3. Initialize `let mut occurrences = Vec::new();`. For **every positional block** (both modes), run **the exact original** `self.limits.check_alloc::<Occurrence>(freq)?` *before parsing any occurrences*. This is an intentionally preserved historical rejection condition even in the lean mode. Reserve `freq as usize` capacity **only if `detail == Full`**. Never call `Vec::reserve`, `Vec::with_capacity`, `Posting::clone`, or `Occurrence::clone` in DocFreq mode.
4. For each of `0..freq`, read and validate (using the exact existing `ByteReader` calls and order): `position_delta` and strict monotonic accumulated position, `position_length != 0`, nondecreasing `value_index`, `start_offset`, `end_offset`, and `start_offset <= end_offset`. Update local `previous_position` and `previous_value_index` exactly as before. **Construct and push `Occurrence` only in Full mode.** Do not skip byte parsing, replace it with a seek, use an unchecked offset, or add cancellation polls inside this loop. Even when a posting is dead or will not rank Top-K, its positional payload must be fully validated before returning the doc/freq header.
5. Only after the complete posting validates, increment `docs_read` and write `previous_doc = Some(doc_id)` exactly as before; return `Some((DocFreqPosting { doc_id, freq }, occurrences))`. On any error, do not commit these two state updates (as in the original). As before, **no resume-after-error guarantee is introduced**.
6. On **successful Full mode** in the old `next_with` public method, construct the existing `Posting {doc_id, freq, occurrences}`, perform its original **one** `self.current = Some(posting.clone())` update, and return the owned `Posting`. `advance_with` remains literally unchanged and continues to read/cache full `Posting` values. The DocFreq view never sets or retains `current`.

**Approved routing pseudocode (not an invitation to choose another algorithm):**

```rust
pub fn next_with(&mut self, cancel: &dyn Cancellation) -> SegmentResult<Option<Posting>> {
    let Some((head, occurrences)) = self.read_one_with(cancel, DecodeDetail::Full)? else {
        return Ok(None);
    };
    let posting = Posting { doc_id: head.doc_id, freq: head.freq, occurrences };
    self.current = Some(posting.clone());
    Ok(Some(posting))
}

// DocFreqPostingsReader::next_with:
let result = self.inner.read_one_with(cancel, DecodeDetail::DocFreq)?;
Ok(result.map(|(head, occurrences)| {
    debug_assert!(occurrences.is_empty());
    head
}))
```

`PostingsReader::next` continues invoking the full `next_with(&NeverCancel)`. The existing full `advance` and `advance_with` bodies are not edited, including their returned cached posting behavior.

**Important nonchange:** The original reader does not verify `freq_total` by a new post-decode sum; do not invent that validation. The only wire-format/version code changes are **none**.

### 4.3 Test-only zero-materialization witness

Add a minimal `#[cfg(test)] pub(crate) mod decode_observation` in `postings.rs` with `thread_local!` `Cell<u64>` counters and `reset()`/`counts()` readers for:

- `positional_vector_reserves`: increment **only** immediately before the original `occurrences.reserve(freq as usize)` in `DecodeDetail::Full` on a positional block.
- `cached_posting_clones`: increment **only** immediately before `self.current = Some(posting.clone())` in full `next_with`.

Use the counters in **unit tests only** to assert **both equal zero** after a multi-posting positional DocFreq read and greater than zero in corresponding full-reader reads. No production static counters, metrics, tracing labels, overhead, allocator hooks or profilers. The tests do not assert actual allocator behavior outside these two explicitly named allocation/clone sites; the source audit additionally proves no other occurrence allocation exists in the lean branch.

## 5. Exact production consumer migration (no other call sites)

The conversion `postings.into_doc_freq()` must be applied **once immediately after obtaining each `PostingsReader`** and before the loop. The existing `while let`, work charge, live bitmap check, ledger, matched tuple push and error propagation remain the same; the value's `doc_id` and `freq` fields are unchanged.

| ID | Exact edit in `main` after A1 merge | Must remain unchanged |
|---|---|---|
| C1 | `build_leaf_data` Term arm: `if let Some(postings) = reader.postings(*field_id, term)? { let mut postings = postings.into_doc_freq(); while let Some(posting) = postings.next_with(cancel)? { ... } }` | Term normalization, scan charge `work.charge_scanned(posting.freq)?`, live filter, `ledger.reserve_with_memory(1, TERM_POSTING_BYTES, ...)`, `charges.add`, `(posting.doc_id, posting.freq)` push |
| C2 | `build_leaf_data` MultiTerm arm: `let mut postings = reader.postings_for_entry(entry)?.into_doc_freq();` then original loop | Expansion `TermId`, dictionary resolution, live checks, ledger/work and returned `TermPostings` |
| C3 | `compute_stats` persisted-norms partially-live DF arm: `let mut postings = postings.into_doc_freq()` after existing `let Some(postings) = reader.postings(...)? else {continue};` | Existing live-length scan, `work.charge_scanned(posting.freq)?`, bitmap bounds, live-only DF checked-add; **A1** `PreparedTermStat.doc_freq` not replaced |
| C4 | `compute_stats` no-norms legacy reconstruction arm: `reader.postings_for_entry(entry)?.into_doc_freq()` | Dictionary iteration, full field lengths, `accumulate_length` limits, live-only DF, A1 query-local IDF preparation *after* stats |
| C5 (protected) | `build_phrase`: **no change**; keep full `.next_with(cancel)` and `posting.occurrences` ownership | Exact phrase positions/offsets/membership/charges, corruption validation |

**Review with diff, not a broad search-and-replace.** The five A1-head `reader.postings` calls in the production portions of `execute.rs` and `score.rs` include C1–C4 plus the protected phrase caller. Test-fixture postings calls in the same files are **not** extra production sites and must not be bulk changed. No `select_keys`, `UnifiedSearcher`, new strategy flag or `ColumnReader` edit is authorized.

## 6. State/ownership/compatibility contract

| Boundary | Before A2 | After A2 |
|---|---|---|
| Immutable wire payload | Positional interleaved `doc_id` delta, freq, five fields per occurrence | **Byte-identical**; same version, encoder and checks |
| Full `PostingsReader` | Owns decoder, `current: Option<Posting>` and cloned full posting for `advance_with` | Identical public behavior, checked by U06 and existing segment tests |
| New DocFreq view | Not present | Consumes `PostingsReader`; unique mutable cursor; emits `Copy` two-`u64` record; `current` cache cleared at conversion |
| Positional validation | All fields parsed with strict checks | Same parser, same checks, before any posting returned; **no skipping** |
| Allocation bound | `check_alloc::<Occurrence>(freq)` before `reserve` | Same check in both modes, physical Vec allocation only in Full mode |
| Memory/work ledger | Consumer charges scanned freq, candidate entries, phrase positions | **No changes** to consumer charging; bypass no charge even if physical Vec removed |
| Cancellation/error | Reader polls at every next attempt; preserves order of typed failures | Same boundary poll; no new early return or extra poll |
| Snapshot/reader | Query-local cursor borrowing segment bytes; immutable generation | Same bytes and lifetime; no mutation, caching or global retained state |
| Retry/idempotence | Repeated query opens new cursor; malformed read is an error | Same; no new publication or transactional behavior |

**Storage identities:** segment content descriptor, index layout, dictionary entry, field norms, `CURRENT`, manifest and any local/RustFS cache keys are unchanged; no new index version or migration. A3 is responsible for any future format change/reindexing. `SegmentReader::open_directory` remains the authentic local storage boundary used by existing integration tests.

## 7. Explicit adverse states and failure-mode matrix

| State/failure | Exact required behavior | Tests |
|---|---|---|
| Zero postings in term/dictionary | `reader.postings(...)` returns `None` or existing header rejects invalid zero-count block; no false emitted results | U02, I01/I02 |
| Single, multiple; positional and doc-only | Ordered exact `(doc_id,freq)` equality, including frequency >1 and duplicate term occurrence | U01/U02/U07/I01 |
| One/last posting and repeated EOF | Last succeeds; `expect_end("postings")` on next attempt; subsequent `None` when not cancelled | U01, U09 |
| Duplicate/non-increasing doc id delta; out-of-range id; delta overflow | Same typed `NonMonotoneDocId` / `Corrupt` as old reader | U03/U04 |
| Zero frequency; frequency > `max_decoded_entries` | Same `ZeroFrequency` / `LimitExceeded`; no partial success | U03/U05 |
| Positional `check_alloc` at exact limit/one below | Same preflight result (`freq * size_of::<Occurrence>()`) **even though lean allocates no Vec** | U05 |
| Truncated/invalid varint in any of five positional fields | Same `Truncated` / `InvalidVarint`, correct context/order | U04 |
| Zero position length, decreasing value index, zero delta for later position, position overflow, start>end | Same `Corrupt` or `NonMonotonePosition` variant and detail | U04 |
| Corruption only in a later, nonwinning/dead posting | Lean reader **still fails** on that record; no silent skip or partial accepted query | U08 |
| Extra/trailing bytes after declared count | Same `Corrupt {context:"postings", detail:"... trailing bytes"}` on EOF request | U09 |
| Cancelled before first, between postings, at EOF | Same `SegmentError::Cancelled` precedence on next attempt | U08, existing SC12 |
| Phrase/multi-term/Boolean sibling paths | Phrase retains positional decoding and exact results; expanded terms use lean decoder; no hit/score/cursor drift | U06, I02, existing integration suites |
| Invalid query / unrelated writer failure | A2 does not affect validation, commit or manifest; existing typed response and snapshots remain | Existing regression suites; no new I/O protocol |
| RustFS unavailable | No A2 remote-boundary changes; no local RustFS startup required. Hosted pre-existing RustFS CI remains applicable baseline evidence, not a new remote acceptance design. | CI/status |
| A1 unavailable/unmerged or not exact source | No A2 source edits; dependency BLOCKED. | P0/matrix |

## 8. Deterministic unit tests — write first, RED then GREEN

All new U tests go in **existing** `crates/quervant-core/src/segment/tests.rs`, adjacent to `postings_round_trip_and_errors` and `decoder_rejects_nonmonotone_doc_id_deltas`. Reuse `encode_postings_block`, `PostingsReader`, `Occurrence`, `Posting`, `SegmentLimits`, `ByteWriter`, `CancellationFlag`. Do not create a new unit test module or third-party test library.

**Reference oracle:** For *valid* blocks, the unchanged full `PostingsReader::next()` results mapped to `(doc_id, freq)` are the behavioral oracle; separately assert the fixed hand-specified tuple list and occurrence counts. For *malformed* blocks, compare the **same exact bytes** driven through full vs lean modes at the same advancement point, comparing concrete typed `SegmentError` variant and its context/detail (use `format!("{error:?}")` only if no `PartialEq`, while also pattern-matching the expected error category). This is a differential test of a shared wire contract, **not** the optimized parser scoring itself.

| Test ID / prescribed name | Exact fixture and assertions |
|---|---|
| **A2-U01 `a2_u01_docfreq_positional_parity_and_zero_materialization`** | Encode 3 positional postings with docs `[1,4,7]`, frequencies `[2,1,3]`, valid strictly increasing positions and nondecreasing value indexes. Full reference yields exact triples/occurrence lengths; DocFreq yields exact `[(1,2),(4,1),(7,3)]`, then two `None`. Reset counters and assert DocFreq reserves=0, clones=0; full reader has both counters >0. |
| **A2-U02 `a2_u02_doc_only_and_empty_lookup`** | Encode a doc-only list docs `[0,2]` with frequencies `[1,2]`, empty occurrences. Full and lean return same doc/freq and EOF; one existing dictionary absent term still returns `None` in `SegmentReader` integration. A zero-entry raw postings header is rejected at `PostingsReader::new`, as before. |
| **A2-U03 `a2_u03_doc_id_and_frequency_errors_match_full`** | Use `ByteWriter` raw blocks with duplicate delta 0, second doc overflow, out-of-range first doc, zero freq, and frequency > max entries. Same exact error category/details in both modes, with the already valid first posting still returned before a malformed second. |
| **A2-U04 `a2_u04_all_positional_corruptions_match_full`** | Begin with valid 1-posting, 2-occurrence raw positional block: header `(kind=1,count=1,freq_total=2)`, `(doc_delta=0,freq=2)`, occurrence1 `(position=1,length=1,value_index=0,start=0,end=1)`, occurrence2 `(position_delta=2,length=1,value_index=0,start=2,end=3)` (each component canonical varint). Build one malformed case each: second position delta 0; first/second `position_length=0`; first value index 1 then second 0; start>end; second position overflow; truncated last field; invalid noncanonical 2-byte varint. Full and lean reject with same typed errors. Do not use an encoder that rejects corruption before it reaches the reader. |
| **A2-U05 `a2_u05_positional_hypothetical_budget`** | Valid positional 1 posting with freq=2: `max_single_allocation` exactly `2 * size_of::<Occurrence>()` passes both readers; `max_single_allocation` one byte below fails both with identical `LimitExceeded{limit,requested}`. Also test `max_decoded_entries=1` rejects freq 2 before the allocation check. |
| **A2-U06 `a2_u06_full_reader_advance_and_phrase_unmodified`** | Drive existing full `next`, `advance`, `advance_with`, repeated same-target cached current, after-EOF and positional equality on encoded block. The newly implemented full path must match the baseline assertions; `build_phrase` must still contain the unchanged full call in diff. |
| **A2-U07 `a2_u07_lean_mixed_conversion_and_no_clones`** | Convert fresh `PostingsReader` to lean and read 3 records: no position reserve/clone. Also call full `next()` once, consume into lean, confirm it drops cached full posting and emits only the **next unread** record; no repetition, no additional full clone after conversion. Verify cursor can be dropped at any point without durable side effects. |
| **A2-U08 `a2_u08_cancel_and_corrupt_unselected`** | For a two-posting block first valid, second corrupt in an occurrence field, lean returns first then the exact full-mode corruption on the second, even when test labels second as “dead/nonwinner.” For a separate valid block cancel before first, after one successful posting and before EOF; both modes yield identical `Cancelled` precedence and no extra inner-occurrence cancellation callbacks. |
| **A2-U09 `a2_u09_trailing_and_repeated_eof`** | Valid block with extra trailing byte: both readers return all declared postings and reject only on next read with matching `Corrupt("postings")`; unmodified valid block returns `None` repeatedly, but cancellation before repeated EOF still returns `Cancelled`. |
| **A2-U10 `a2_u10_frequency_transport_for_work_charges`** | On a fixed positional two-posting block, calculate `sum(freq)` independently from the Full and DocFreq returned records; both must equal the wire header `freq_total` and the fixed expected sum. Include one doc ID designated dead/nonwinner in the fixture and confirm it is still emitted by the decoder for the caller to filter. This unit test verifies the frequency *input* to existing `work.charge_scanned`; the actual work/ledger parity is separately exercised by existing `b4_u05`, `pr07_properties`, and real I02. No new work meter or ledger implementation. |

**Red gate:** add U01/U05/U07 first so their code references `DocFreqPostingsReader` or `.into_doc_freq()` that does not exist at baseline. Run `cargo test -p quervant-core --lib a2_u` and save the **expected missing API compile failure only**. A failure caused by an unrelated crate, baseline defect or environment is not valid RED. Add remaining tests with implementation after this proof. Do not weaken an asserting test to turn it green.

**Adversarial data generation:** the bytes for negative tests are **deliberately hand-built by `ByteWriter`** according to `postings.rs`'s frozen interleaved layout. No randomness is required; optional seeded fuzz/property cases are **not** authorization to add third-party tools or extend scope. Record inputs and expected errors in the execution report.

## 9. Real production-path integration tests and regression suites

| Test ID / file | Required scenario | Acceptance |
|---|---|---|
| **A2-I01** `crates/quervant-core/tests/segment_codec.rs` | Add `a2_i01_real_segment_docfreq_matches_full`: use existing `sample()` real `SegmentBuilder` bytes → `SegmentReader::open`; resolve `body` field and a term with positional postings (`hello`), then independently reopen the postings reader twice, one full and one `.into_doc_freq()`. Compare `(doc_id,freq)` for all results and EOF; assert the full path still supplies nonempty positions. Verify built segment identity/content descriptor as existing `p5_g01` does. | Exact counts/order/freq; no codec version or byte changes; no `Position` fabrication in lean results. |
| **A2-I02** `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | Add `a2_i02_fs_term_prefix_phrase_and_generic_parity` using the **existing** `build`, `batch`, `spec`, `term`, `request`, `ascend`, `search_ok`, `keys`, `bits_by_key` fixtures. Build 12 actual documents using `batch(12, |i| i % 3 + 1)` and real `FsDirectory` writer→commit→reopen. Query: `Term(body="alpha")`; `Prefix {field:"body", prefix:"alp"}`; `And(vec![term()])`; `Phrase {field:"body", terms:["alpha","alpha"]}`; absent `Term(body="never_present_a2")`. | Term/prefix/generic each have `total_hits=12`, identical ordered keys and per-key `score.to_bits()` where one term owner is scored. Phrase has exactly 8 matches (alpha frequency ≥2 for 8 of 12); expected keys derived **independently** from `i % 3 + 1` and checked, not from the production query. Absent count 0. K10/K100: first 10 sorted keys and exact scores equal corresponding subset of K100. Repeat after a fresh `Index::open_existing`; verify same results. All done through public `UnifiedSearcher`, no fake scorer. |
| **Existing mandatory focused suites** | `pr07_properties` seeded independent Boolean/phrase/BM25 oracle; `pr07_integration` real writer/reopen/PIT; `pr14_unified_mixed` typed/phrase/fallback; `pr15i_d2a_scoring_contract` SC01–SC15 plus A1; `segment_codec` old `advance`; `segment_corrective`; `pr15h_b_sort_materialization` borrowed-sort guards. | All execute and PASS on final A2 source; no skipped failures. |

For I02 construct the test without inventing fields or analyzer behavior: existing schema uses `body: Text` with `standard_folded`, `body(alpha,filler)` emits `alpha` repeated then `zeta`. **Do not** change the fixture corpus helpers. For live/dead/PIT/cursor and budget/cancellation, reuse existing real-path tests; A2 does not introduce new write, network or cache behavior.

**RustFS:** No new remote storage contract, byte format, bootstrapping logic or caching is implemented. Therefore do **not** start RustFS locally or execute a full remote qualification campaign for A2; preserve the existing hosted RustFS CI job where already required. A2-I02 is the *real local filesystem* boundary acceptance for the affected query executor. This scoping is consistent with the PERF-06 roadmap's “no unnecessary work” policy but does not waive general workspace QA.

## 10. Implementation order, exact commands and execution evidence

### P0 — Preconditions, inventory and baseline health

1. Complete §2.2; require merged A1 and the expected source blob identities; record `BASE_MAIN_SHA` and the branch/PR absence. Read the merge version of `postings.rs`, `execute.rs`, `score.rs`, `segment/tests.rs` in full. If source changed, apply D03 and STOP. Confirm `gh` identity and branch tracking before push.
2. From the accepted main, run and record the focused **baseline** checks:

```bash
cargo test -p quervant-core --lib postings_round_trip_and_errors
cargo test -p quervant-core --lib decoder_rejects_nonmonotone_doc_id_deltas
cargo test -p quervant-core --test segment_codec
cargo test -p quervant-core --test segment_corrective
cargo test -p quervant-core --test pr15i_d2a_scoring_contract
cargo test -p quervant-core --test pr07_properties
```

3. Do not treat baseline test success as A2 acceptance. If failure, classify using §11 and §12; don't silently change accepted main.

### P1 — RED tests, before production edits

1. In `segment/tests.rs`, add A2-U01/U05/U07 with missing `into_doc_freq` symbols. Run the focused `a2_u` command once; preserve exact expected compile errors. Do not add test-only production shortcuts that bypass the API.
2. Add remaining U02–U10 fixtures, including negative bytes, within this allowlist. Add the I01/I02 production-path tests before or alongside implementation (these may pass on baseline only where they assert pre-existing invariants). Log which tests demonstrate **new API** vs regression.

### P2 — Decoder and view implementation, one file

1. Edit `segment/postings.rs` exactly per §4.1–4.3. **Move** existing decode code into one private `read_one_with`; mode controls **only** occurrence vector reserve/push and full-payload ownership, never byte validation or limits. Keep old public `next_with` / `advance_with` API and errors.
2. Introduce `DocFreqPosting`, consuming `DocFreqPostingsReader`, `next`, `next_with`, and test-only observation counters. No new `SegmentReader` factory, segment version or file.
3. Run `cargo test -p quervant-core --lib a2_u`; require all prescribed U cases GREEN. No inferred success from only a compile.

### P3 — Four and only four consumer conversions

1. Edit exactly C1/C2 in `search/execute.rs` and C3/C4 in `search/score.rs` as §5. Preserve A1 scoring calls/structures. Keep `build_phrase` unchanged byte-for-byte except any no-op formatter normalization imposed by rustfmt (and explain that if it occurs).
2. Run targeted regression suites, and compare `git diff` to the exact allowlist. Any unexpected production consumer or changed score formula is HARD STOP.

### P4 — Production-path QA and adversarial self-review

1. Run both I01 and I02 and all named focused suites; review every INV row against actual evidence, not assertions about what should happen.
2. Challenge: malformed `Occurrence` belonging to a dead/nonwinner posting; `advance_with` after `next`; trailing bytes after last doc; doc delta overflow; phrase corruption; A1 prepared scores; zero/one below resource bounds; cancellation before EOF. Record the actual failing counterexample and stop if any contract diverges.
3. Resolve only narrowly applicable implementation defects within the approved design; do not rewrite the decode/charge/validation architecture.

### P5 — Mandatory full local QA after **final** code/test change

Run from workspace root; record the exact toolchain version, command, exit status, test count and line coverage. The project `AGENTS.md` and `.github/workflows/ci.yml` own these gates:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test --workspace --all-targets --all-features
cargo llvm-cov --workspace --all-targets --fail-under-lines 85
cargo doc --workspace --no-deps
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets -- -D warnings
cargo +1.85.0 test --workspace --all-targets
git diff --check
```

CI separately executes **all-features** coverage with `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`, all-features docs, benchmark build-only and benchmark script tests. If locally available without changing infrastructure, run these parity commands too; otherwise record which CI-owned gates remain pending and inspect the actual GitHub results. Do not claim CI passed merely because a previous run on A1 was green. **Any source or test change after P5 requires rerunning all affected mandatory checks and workspace coverage.** Do not start RustFS locally or execute timed benchmarks.

Coverage is **workspace-wide**; do not reduce the threshold, change exclusions, ignore failing tests or quote a targeted-file percentage as equivalent.

### P6 — Evidence, push and draft implementation PR

1. Copy the **entire approved** `PERF06_A2_DETAILED_PLAN.md` to `docs/pr-artifacts/perf-06-a/PERF06A2_DETAILED_PLAN.md` on **the A2 implementation branch**. Do not alter its architectural requirements retroactively.
2. Author `docs/pr-artifacts/perf-06-a/PERF06A2_EXECUTION_REPORT.md` recording baseline/merge, exact source blobs, RED/GREEN, actual error parity, U/I IDs, coverage, CI, source diff, stop decisions, and any unresolved failures; see §13 schema.
3. Stage only approved files, `git diff --cached --check`, commit with scoped `perf(a2): add validated doc/freq postings view`, push normally (no force). Verify `git rev-parse HEAD` equals `git ls-remote origin refs/heads/dev/perf06-a2-docfreq-postings` SHA. Create **one new draft PR targeting `main`**, title `PERF-06-A2: Validated document/frequency-only postings decoding` and include status and no-timing statement. **Do not use PR #119 as base**, do not merge, do not start A3. If auth blocked, preserve locally committed work and report `PR_CREATION_BLOCKED` without asserting a PR exists.
4. Obtain/inspect hosted CI for **that exact PR head**, report PASS/FAIL/PENDING accurately. If CI pending, PR stays draft and status is `IMPLEMENTED_LOCAL_QA_PASS_HOSTED_CI_PENDING`; independent review is still required.

## 11. Failure classification and exit states

Required classification of each mandatory test/check failure (with evidence): `INTRODUCED_REGRESSION`, `FEATURE_IMPLEMENTATION_DEFECT`, `DETERMINISTIC_PREEXISTING_FAILURE` (only after proving on accepted main), `NONDETERMINISTIC_FLAKY_FAILURE` (only after reproducible nondeterminism), or `ENVIRONMENT_HARNESS_FAILURE` (record environment and exact failed command). “Unrelated” is **not** a classification. No blind retry loop, no replacing tests with stubs, no invoking a different harness to make an equivalent-looking green result.

| Exit disposition | Conditions |
|---|---|
| `PERF06_A2_IMPLEMENTED_READY_FOR_INDEPENDENT_REVIEW` | Source and all required local acceptance pass, PR opened/pushed, hosted CI green on final exact head, scope audit passes; independent reviewer still needed before merge. |
| `PERF06_A2_IMPLEMENTED_CI_PENDING` | All local acceptance and integration pass, head pushed/PR opened, relevant CI still pending. |
| `PERF06_A2_IMPLEMENTATION_BLOCKED` | A mandatory required gate failed, CI failed or required acceptance evidence cannot be obtained. Preserve code/evidence, don't call complete. |
| `PERF06_A2_DEPENDENCY_BLOCKED_A1_UNMERGED` | A1 not actually merged, not exact accepted source; no A2 implementation branch/code changes. |
| `PERF06_A2_HARD_STOP_DESIGN_DECISION_REQUIRED` | New condition outside matrix or impossible-to-preserve invariant; stop affected implementation without choosing an alternative architecture. |

## 12. Preauthorized Architectural Decisions and Exception-Handling Matrix

**Rule:** match exact observable trigger; use most restrictive applicable row. `AUTO-RESOLVE` means execute and continue, documenting evidence. `DEFER AND CONTINUE` means record the blocked dependent gate and work on provably independent tasks only; it never authorizes a workaround. `HARD STOP` stops affected implementation immediately; if isolation cannot be proved, stop the entire PR. All deviations need human maintainer approval. **For any unforeseen condition with no applicable row, HARD STOP** the affected design/execution; do not improvise.

| ID | Observable trigger / source check | Category | Exact preauthorized action | Prohibited response | Evidence / affected gate / owner |
|---|---|---|---|---|---|
| D01 | PR #120 shows OPEN/DRAFT, even with green CI or pushed fixup | **DEFER AND CONTINUE** | Audit/read docs and source only; report A1 dependency blocked; do not create A2 code branch | Building A2 atop unmerged A1, cherry-picking fixup | GitHub PR state, maintainer merge |
| D02 | PR #120 shows MERGED, actual `origin/main` source blobs match A1 fixup and table | **AUTO-RESOLVE** | Record merge SHA and exact main SHA; create clean A2 branch after all P0 checks | Assuming merged without GitHub proof | P0 log / agent |
| D03 | Any inspected A2-relevant source blob differs from §2 expected after A1 merge, or current main has a new incompatible consumer | **HARD STOP** | Provide file, old/new blob and diff; request amended plan | Silent rebase, reconstructing a new design | P0 / maintainer |
| D04 | A2 local or remote branch/PR already exists | **HARD STOP** | Preserve it, report identity to maintainer | Resetting, force pushing, creating a second competing A2 PR | P0 / maintainer |
| D05 | Source has exactly four doc/freq consumer loops and protected phrase loop described in §1 | **AUTO-RESOLVE** | Convert C1–C4 only; keep C5 full | Global replacement of `next_with` | Diff / agent |
| D06 | `SegmentReader::postings` returns existing cursor and `into_doc_freq` may consume it | **AUTO-RESOLVE** | Convert locally at call sites; leave SegmentReader unchanged | New factories, cache, alternate storage API | P3 / agent |
| D07 | Positional `check_alloc::<Occurrence>(freq)` is present before parsing | **AUTO-RESOLVE** | Preserve identical bound in both modes, even with no allocation | Removing it to improve benchmarks | U05 / agent |
| D08 | Full `advance_with` relies on `current: Option<Posting>` clone | **AUTO-RESOLVE** | Retain full clone and unchanged advance methods; only lean omits clone | Changing `advance_with` semantics | U06 / agent |
| D09 | `DocFreq` conversion occurs after some full reads in a test | **AUTO-RESOLVE** | Consume cursor; clear old cached clone; continue next unread record | Emitting last cached again or permitting simultaneous handle use | U07 / agent |
| D10 | Source positional decoder has all six existing checked occurrence components/relationships | **AUTO-RESOLVE** | Parse all in shared helper; branch only on Vec `reserve`/`push` | Skipping payload bytes or seeking unchecked | U04 / agent |
| D11 | `build_phrase` requires `Posting.occurrences` | **AUTO-RESOLVE** | Preserve full cursor and ownership exactly | Lean mode for phrase, lazy positions | I02/U06 / agent |
| D12 | New unknown production postings consumer appears during audit | **HARD STOP** | Inventory symbol/path and request updated migration matrix | Convert based on guessed need | P0/P3 / maintainer |
| D13 | Tests require a malformed positional record | **AUTO-RESOLVE** | Encode explicit raw block using `ByteWriter`; compare typed full/lean errors | Editing production encoder to write corruption | U04 / agent |
| D14 | A new lean branch passes malformed later record without the old error | **HARD STOP** | Record exact bytes and divergence; stop until compliance restored within prescribed parser | Treat dead/nonwinning corruption as ignorable | INV02 / maintainer |
| D15 | Full cursor's `next`, `advance` or EOF error/cancellation differs | **HARD STOP** | Stop and report mismatch; only the prescribed shared-parser correction is permissible after review | Accepting changed API behavior | INV04 / maintainer |
| D16 | Decoder's original budget preflight or error precedence cannot be preserved | **HARD STOP** | Provide counterexample and required design decision | Dropping checks or changing `SegmentError` | INV05/06 / maintainer |
| D17 | `cargo fmt` changes only in-scope style in intended hunks | **AUTO-RESOLVE** | Keep formatting and record diff | Formatting unrelated modules | P5 / agent |
| D18 | `cargo fmt` touches unrelated files | **DEFER AND CONTINUE** | Restore only confirmed out-of-scope formatting, preserve in-scope work, rerun fmt | Reset/clean repository, broad refactor | Diff / agent |
| D19 | New A2 API tests fail RED solely because API missing before implementation | **AUTO-RESOLVE** | Retain exact RED output; implement approved API; continue | Treat unrelated failures as feature RED | P1 / agent |
| D20 | Baseline-focused test fails on accepted `main` | **DEFER AND CONTINUE** | Reproduce/prove on baseline, classify; continue independent source audit only | Label flaky/unrelated by assumption, edit main | P0/QA / maintainer |
| D21 | New implementation test fails due to the intended API implementation defect | **AUTO-RESOLVE** | Make **narrow in-scope** fix following §§4–5; rerun all relevant tests | New algorithm, waiver, test loosening | P2/P4 / agent |
| D22 | An in-scope Clippy/fmt warning appears on new A2 code | **AUTO-RESOLVE** | Make bounded mechanical lint/style fix, retain behavior; rerun required gates | Broad crate/manifest edits or `allow` suppressions without reason | P5 / agent |
| D23 | Workspace coverage <85% due to uncovered new A2 logic | **AUTO-RESOLVE** | Add deterministic adverse tests in allowlist for the uncovered branch; rerun coverage | Lowering gate, exclusions or instrumentation hacks | P5 / agent |
| D24 | Coverage fails for a substantial pre-existing/unrelated reason | **DEFER AND CONTINUE** | Classify with baseline evidence, continue reports, block acceptance | Reporting partial coverage as pass | P5 / maintainer |
| D25 | CI or PR creation unavailable due to auth/network after local QA | **DEFER AND CONTINUE** | Preserve committed local branch/evidence, retry only ordinary non-destructive auth validation, report blocked external gate | Force push, claim PR/CI success | P6 / maintainer |
| D26 | Hosted CI pending on final exact SHA | **DEFER AND CONTINUE** | Report pending precisely; do not claim READY or merge | Poll indefinitely, silently mark green | P6 / maintainer |
| D27 | Hosted CI FAIL on relevant final-head job | **HARD STOP** | Classify/log failure; request narrow fixup if not explained by planned implementation | Ignore job or change CI policy | P6 / maintainer |
| D28 | Requested change is disk format, skip/block index, positional compression, writer, A1 BM25, new planner or A3 | **HARD STOP** | Record scope violation and request later plan | Folding future series into A2 | Scope / maintainer |
| D29 | Real RustFS unavailable locally, but A2 changed no remote/storage contract | **AUTO-RESOLVE** | Do not start service; use required local Fs integration and hosted existing CI | Fake a RustFS success or run unrelated service benchmark | P4/P5 / agent |
| D30 | A1 scoring bits/candidate ledgers change under A2 | **HARD STOP** | Record exact query and expected/actual, stop | Accept “close enough” score or new charge | INV05/08 / maintainer |
| D31 | Same bytes produce different full vs lean error category/context at any boundary | **HARD STOP** | Record raw fixture, first mismatch, and stop until corrected within existing validation contract | Catch-and-map errors to preferred category | INV02 / maintainer |
| D32 | New exception is not covered by D01–D31 | **HARD STOP** | Preserve state and return source evidence plus smallest approval question | Design-by-agent improvisation | Maintainer |

## 13. Required final execution report and acceptance checklist

### Required report headings

`PERF06A2_EXECUTION_REPORT.md` must include: repository/branch/PR/base and final/remote SHAs; merge verification; source blob table; pre-implementation invariant challenge; scope/diff audit; RED evidence; per-U and per-I GREEN evidence; corrupted-byte parity table; proof of zero lean positional reserves/clones; full/lean EOF/advance/cancellation cases; scoring/ledger/phrase regressions; local stable/MSRV/cov and hosted CI command/status table; all applied matrix rows; unresolved failures/residual risks; out-of-scope audit; final typed disposition. Distinguish **test exists**, **test executed** and **test passed**; do not say an unrelated existing suite proves the new API unless the new path was actually exercised.

### Reviewer acceptance criteria (all mandatory)

- [ ] A1 PR #120 is actually merged; accepted `origin/main` contains the A1 fixup code; A2 starts from the exact verified main source with clean tree.
- [ ] `DocFreqPosting`, consuming `DocFreqPostingsReader`, `into_doc_freq`, `next` and `next_with` implemented exactly; no alternative API.
- [ ] A **single** original-code-preserving shared decoder parses and validates **all positional bytes** in both modes.
- [ ] DocFreq mode performs **zero positional Vec capacity reserves and zero full Posting clones/cached payloads**; full mode remains unchanged.
- [ ] Exactly C1–C4 use lean view, `build_phrase` stays full; no production API/storage/format or scoring drift.
- [ ] U01–U10 all pass with exact typed malformed/cancellation/budget/EOF/full-advance behavior.
- [ ] I01/I02 pass through real `SegmentReader`/`FsDirectory` writer→commit→reopen→`UnifiedSearcher`, with independent expected membership and score-bit checks.
- [ ] Existing phrase, Boolean, multi-term, score parity, resource, cancellation, PIT/cursor, mutable/live and writer/reopen regression suites pass.
- [ ] All mandatory stable/MSRV workspace QA passes on final source; coverage ≥85%; hosted relevant CI passes on exact PR head before `READY`.
- [ ] Entire raw diff is limited to the authorized files; no benchmark/profiler acquisition, results, roadmap or format changes.
- [ ] New PR is draft, published without force, not merged; A3 not started; report and approved plan are committed; independent review remains outstanding.

### Proposed PR description for the agent

```markdown
## PERF-06-A2 — Validated document/frequency-only postings decoding

Introduces a consuming doc/frequency postings view while retaining one full positional
validation implementation, the existing wire format, and unchanged full reader/advance semantics.
Four existing term, expanded-term and snapshot-statistics consumers use the lean view.
Phrase queries continue to use full positional postings.

Correctness first: full/lean codec parity and malformed-block tests, allocation/clone
witnesses, real SegmentReader and FsDirectory query integration, plus workspace QA.
No new persistent format, no BM25 change, no profiling, no real performance acquisition.
Warm qualification remains PERF-06-A4. Independent review required before merge.
```

## 14. Dependencies and coding-agent final rules

- **A1 must be merged** and its published source used as this PR's accepted baseline. The A1 pushed fixup and green CI do not suffice. If unmerged, stop the dependent branch/implementation and report `PERF06_A2_DEPENDENCY_BLOCKED_A1_UNMERGED` rather than implementing ahead of acceptance.
- A2 is a single dominant decoder/API concern. **A3** owns future separated streams and skip indexes; **A4** owns consolidated warm qualification, including any comparison against immutable historical results when actually comparable. Neither may be implemented by the A2 agent.
- Follow `AGENTS.md`, `docs/TESTING.md`, and this plan even when an easier implementation would be faster. No undocumented thresholds, new service processes, unplanned benchmark setup, or legacy error downgrade.
- Use all necessary routine execution permissions under the continuous-authorization rule in §0. Do not request permission after every stage; do not bypass actual human approvals for architectural changes or unresolved stops.
- If a source fact, test, or exceptional case is not covered here, **HARD STOP dependent work**. Report precise line/symbol, observed condition, violated invariant, evidence, and the minimum decision needed. No free design choices are delegated.

**Terminal objective:** `PERF06_A2_IMPLEMENTED_READY_FOR_INDEPENDENT_REVIEW` **only** on all required green local and hosted evidence; do not merge this PR or begin A3.

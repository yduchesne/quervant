# PERF-06-C2-F1-A1 — Complete stopped acceptance cases and correct evidence

| Item | Frozen value |
|---|---|
| Repository / existing PR | `yduchesne/quervant` / [PR #131](https://github.com/yduchesne/quervant/pull/131) |
| Branch / delivery state | `dev/perf06-c2`; latest verified state OPEN, ready for review (`draft=false`), unmerged; preserve the observed readiness flag |
| Plan date | November 26, 2026, America/Los_Angeles |
| Reviewed A1 starting head | `2bf9539cd2f53838ad1aca406ca4e67a34229ff6` |
| Fresh main / accepted C1 | `bc726420cede2e26681d6e8192b45a5d0169abbf` |
| Original F1 starting head | `46ccab0a606a56a8b9034ab4db5c9c4df969d098` |
| Historical F1 tested source | `564fd7853d41adc77c84c766f59e29bae113d7b0` |
| Governing original plan | `docs/pr-artifacts/perf-06-c/PERF06C2F1_DETAILED_FIXUP_PLAN.md` |
| Original plan SHA-256 | `b9d11e958af2186e9a5f358153cee489a4cdafc9913ed7ea7bb6b494b091d5e7` |
| This amendment's repository destination | `docs/pr-artifacts/perf-06-c/PERF06C2F1_A1_DETAILED_AMENDMENT.md` |
| Authoring status | SOURCE-REVIEWED DESIGN; amended Rust cases have not been executed by the plan author |
| Outstanding human-owned decision | G7 whitespace failure: no exception is granted by this document |

## 0. Binding execution contract

This is a narrow amendment to the existing F1 plan, not a replacement for it. Read both documents and the repository's `AGENTS.md`, `docs/TESTING.md`, and `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`. The original F1 plan remains binding except for the explicit changes in section 2 below. Preserve verified F1 work and all historical plans and raw evidence.

The plan author made two incorrect fixture assumptions: the six-document commit does not occupy query segment 0, and `grp/common` does not use doc-only postings. The coding agent correctly applied D14 to those contradictions. This amendment fixes the design by using the actual native segment order and actual positional encoding. It also closes independently observed assertion and evidence gaps. It does not authorize a production change.

When this amendment is supplied for execution, complete the prescribed source admission, test changes, verification, reports, ordinary push, and ordinary CI observation. Do not ask for routine reconfirmation. The unresolved G7 exception is scoped: it does not prevent independent implementation, verification, or truthful delivery of partial work.

> **Continuous execution authorization:** Execute the approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

The coding agent implements the exact design in this amendment. It may perform only the bounded conformance repairs in section 13. It must not invent fixtures, derive substitute thresholds at runtime, change error expectations, broaden the allowlist, add alternate implementations, approve exceptions, or improvise when an unforeseen condition appears. Unknown conditions are scoped HARD STOPs.

No benchmark execution, profiler, latency measurement, threshold tuning, C3/C4 implementation, merge, readiness-state toggle in either direction, review approval, reviewer message, or workflow redesign is authorized. `cargo bench --no-run` remains a compile check. G10 remains maintainer-owned and open.

## 1. Reconciled starting state and source evidence

The author inspected fresh PR metadata, main, the pushed source, the two D14 receipts, the F1 report, the original guide/contract, and ordinary CI. The reviewed head remains `2bf9539…`, and main remains `bc726420…`. During final metadata verification, the latest read reports `draft=false` while the PR remains open and unmerged at those same refs. This supersedes the earlier draft-state report. The author made no PR-status change; do not infer who changed the flag or treat readiness as acceptance. A repository comparison from historical TESTED `564fd785…` to reviewed head contains documentation/evidence changes only. The author did not run Rust tests: this review environment has no `cargo` executable. Source review and existing receipts establish the starting facts; they do not establish that the amended cases will pass.

### 1.1 Capability classification

| Capability at A1 start | Classification | Required A1 action |
|---|---|---|
| Existing C2 runtime implementation | DONE + VERIFIED for the prior executed checks; independent acceptance open | Preserve it exactly. |
| Normal-build F1 source isolation | DONE + VERIFIED by independent text comparison | Recheck after A1; do not add observation sites. |
| U17 five actual B3 refusal/control rows | DONE + VERIFIED for their actual assertions | Preserve rows/counters; strengthen complete-response comparison. |
| U17 no-eager-binding failure case | BLOCKED / NOT IMPLEMENTED | Implement the native-order score-fault case in section 6. |
| U21 fixed later-segment table | BLOCKED / NOT IMPLEMENTED | Replace the retained sweep using section 5. |
| U12 registration and six fault rows | PARTIAL | Keep working rows; restore the three posting rows; correct combined-fault probing and complete-response assertions. |
| P05 six resource rows and same-budget recovery | DONE + VERIFIED for existing assertions/receipts | Keep `execute.rs` unchanged; rerun required regression. |
| I08 exact resource/cancellation outcomes | DONE + VERIFIED for those outcomes | Strengthen retry cursor and aggregation parity. |
| Exact test-name inventory | DONE + VERIFIED | Preserve 24 + 5 + 9 functions; distinguish nine U12 rows from one test function. |
| Local F1 QA | Existing receipts report successful executable checks; G7 closure is BLOCKED | Reexecute mandatory QA after final test changes; correct whitespace evidence. |
| Ordinary CI for reviewed head | DONE + VERIFIED as historical regression | Run 45828518258 has five successful jobs; obtain A1 CI after changes. |
| F1 evidence/report accuracy | PARTIAL | Append errata and create the new A1 report. |
| C3/C4 and G10 | NOT STARTED / OPEN | Keep unchanged. |

U21 currently retains its original `saw_failure` sweep. U12 explicitly omits three calls. Passing test registrations therefore do not prove the missing matrix cases. Preserve this distinction in every status statement.

### 1.2 Pinned primary sources

These are source anchors, not permission to modify the referenced implementation:

- [Reviewed unified source](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/crates/quervant-core/src/search/unified.rs): `c2_tests`, U17/U21/U12, observation reset semantics, existing helper APIs.
- [Reviewed public integration tests](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/crates/quervant-core/tests/perf06_c2_physical.rs): I08's resource cases and incomplete `assert_same_response` helper.
- [Segment identity](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/crates/quervant-core/src/index/support.rs), [manifest ordering](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/crates/quervant-core/src/index/writer.rs), and [snapshot load order](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/crates/quervant-core/src/index/mod.rs): content-hash IDs, sorted manifest references, preserved query order.
- [Native postings decoder](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/crates/quervant-core/src/segment/postings.rs): compact-short positional decoding; zero-frequency check precedes that posting's positions.
- [Segment-order D14 receipt](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/docs/pr-artifacts/perf-06-c/evidence/c2-f1-d14-segment-order-stop.txt) and [postings-layout D14 receipt](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/docs/pr-artifacts/perf-06-c/evidence/c2-f1-d14-postings-layout-stop.txt): observed immutable fixture details.
- [F1 report](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/docs/pr-artifacts/perf-06-c/PERF06C2F1_EXECUTION_REPORT.md) and [whitespace receipt](https://github.com/yduchesne/quervant/blob/2bf9539cd2f53838ad1aca406ca4e67a34229ff6/docs/pr-artifacts/perf-06-c/evidence/c2-f1-git-diff-check.txt): preserve, then supersede incorrect claims through append-only errata.
- [Ordinary CI run 45828518258](https://github.com/yduchesne/quervant/actions/runs/45828518258): all five jobs succeeded. RustFS logs show checkout of merge `2af67bc6fc089b686acdcc582b1926ed5808a195`, merging reviewed head into accepted main, and executed test bodies. Record merge-ref identity separately from PR-head identity.
- [Authoring guide](https://github.com/yduchesne/quervant/blob/bc726420cede2e26681d6e8192b45a5d0169abbf/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md) and [AGENTS](https://github.com/yduchesne/quervant/blob/bc726420cede2e26681d6e8192b45a5d0169abbf/AGENTS.md): current-source reconciliation, exact acceptance, continuous execution, mandatory QA, and human-owned exceptions.

## 2. Exact supersession map and change allowlist

### 2.1 Superseded instructions

| Original F1 instruction | A1 replacement |
|---|---|
| U21 assumes segment sizes `(6,34)`, uses caps 12/13/99/100 and completion count 6 | Native sizes `(34,6)`; caps 86/87/99/100; completed first-segment count 34; section 5. |
| U17 structural score arm targets local doc 5 in the six-document first segment | Target local doc 33 in the native 34-document first segment; section 6. |
| U12 `grp/common` is 67-byte doc-only marker 6, final frequency at `+66` | 218-byte positional marker 7, final frequency at `+67`; section 7. |
| Unqualified direct probes may run on a combined column/key/posting corruption | Column-present rows run only the eager column probe on combined bytes; section 7.3. |
| Presence-only cursor comparisons accepted in the implementation | Exact cursor equality and all listed response fields; section 4. |
| F1 report's G7 PASS / all whitespace pre-existing / F1 delta clean | Unsupported; replace through errata with committed-range evidence and BLOCKED unless genuinely resolved or explicitly excepted; section 10. |
| Historical reports are the current identity record | A1 report and final handoff record precise current identities; section 12. |
| Earlier instructions require the PR to remain draft | Latest metadata reports ready for review. Preserve the observed readiness flag, do not toggle it, and apply A31 if that flag is the sole changed admission fact. G10 remains open. |

All other original case semantics, protection rules, resource values, scoring rules, error wrappers, retention of older tests, QA commands, coverage floors, and CI topology remain binding. The original plan file itself stays byte-identical.

### 2.2 Closed A1 allowlist relative to A1 START

| Path | Permitted delta |
|---|---|
| `crates/quervant-core/src/search/unified.rs` | Private helpers and U12/U17/U21 inside existing `#[cfg(test)] mod c2_tests`; two narrowly corrected explanatory comments described below. No other test body changes. |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | I08's existing response-comparison helper and its doc comment only. |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_A1_DETAILED_AMENDMENT.md` | Add this amendment verbatim. |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_A1_EXECUTION_REPORT.md` | New report with actual results. |
| `docs/pr-artifacts/perf-06-c/PERF06C2F1_EXECUTION_REPORT.md` | Append dated A1 errata only; preserve all existing bytes as an exact prefix. |
| `docs/pr-artifacts/perf-06-c/PERF06C2_EXECUTION_REPORT.md` | Append one current-status pointer only; preserve existing bytes as an exact prefix. |
| `docs/pr-artifacts/perf-06-c/evidence/c2-f1-a1-*` | New bounded evidence; numbered attempts; no overwriting. |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | Append A1 status and evidence link. |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | Narrow current C2 note/link reflecting actual gates. |

Make two comment corrections: `linear_config` must say Linear and Prefilter support compact keys, while ExactSet does not. Replace the two-line comment immediately above `record_owned_key_fallback_segment` with exactly these two lines; its code and observer placement remain unchanged:

```rust
    /// PERF-06-C2-F1-A1: record selection of the accepted owned B2 key handler.
    /// Refusal and ExactSet bypass are distinguished by config and B3 counters.
```

`execute.rs` is entirely frozen at A1 START, including P05. The two existing `#[cfg(test)]` observation statements are frozen. All other original protected paths remain protected: scoring, work/memory accounting, cursor, planner, errors, typed/batch APIs, index/segment/storage implementations, B1–B3 fixtures, manifests, dependencies, toolchains, workflows, benchmarks, C1 contract, architecture, guide, AGENTS, TESTING, and all old plans/raw receipts. Do not format old artifacts to conceal the whitespace problem.

## 3. Source admission and correctness preparation

1. Fetch `origin main dev/perf06-c2`. Require main `bc726420…`, PR #131 open/unmerged/base main, and remote head `2bf9539…`. Capture the actual `draft` boolean and preserve it; do not change readiness in either direction. The only permitted source-descendant exception is section 13 A02; a readiness-only metadata change uses A31.
2. Preserve foreign work. The previously reported untracked `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt` is unrelated; if still present, record and leave untouched. Do not use broad staging, resets, stashes, or cleanup.
3. Record unambiguous identities: `MAIN_BASE=bc726420…`, `F1_START=46ccab0…`, `A1_START=<admitted remote>`, and later `A1_TESTED`, `A1_FINAL`, `REMOTE_VERIFIED`. For inherited report fields use `BASE=MAIN_BASE` and `START=A1_START`; explicitly state those meanings rather than reinterpret historical F1 labels.
4. Verify the original F1 plan SHA-256 exactly. Save this amendment at its prescribed path. Capture its SHA-256 separately; never substitute that hash for the original.
5. Capture baseline exact test-name inventories and focused current U17/U21/U12/P05/I08 receipts. U21's old passing sweep and U12's six-row pass are baseline regression only. Record missing acceptance rows rather than declaring them verified.
6. Before edits, complete this worksheet in the new report: why segment 0 has 34 documents; why scanned total is 87+13; why cap 87 fails requesting88; why doc 33 is the last first-segment score; why frequency byte67 precedes unchanged positional bytes; why the combined column error must prevent deeper direct probes; why exact cursor equality is legitimate only on the same snapshot/request; why a worktree-only diff cannot prove a committed range clean.
7. Map the invariants below to exact planned checks. Continue automatically when the worksheet is complete and source admission passes.

### 3.1 Invariants, negative cases and shared impact

| Invariant | Positive case | Counterexample rejected | Proof owner |
|---|---|---|---|
| Native topology is preserved | Fixed two-segment guard | Reordered snapshot or different corpus disguised as the same case | U17/U21 native guard |
| Later failure follows completed first-segment collection | Cap100 success, same-snapshot retry | Cap87/99 silently returns partial success or fails before any prior collection | U21 exact errors and completion tuples |
| First-segment score failure precedes later binding | Unarmed recovery | Eager all-segment binding before score failure | U17 bound-columns1, no callback/collection |
| Complete postings validation precedes candidates | Pristine U12 control | Ignoring the final posting or allowing DOC_KEYS to win over its error | P29 and P29+D0 |
| Eager malformed columns keep priority | Healthy native columns | Combined probe assumes malformed columns can open successfully | C29+P29+D0, exact Index→Segment wrapper |
| Entire intended matrix executes | Nine completed returned row IDs | A green Rust test with only six row calls | U12 exact ordered completion array |
| Retry/Legacy responses are complete matches | Same snapshot/request success | Wrong cursor with unchanged presence, or changed aggregation | Exact response helpers |
| Runtime implementation is unchanged | A1 source freeze | Unapproved production or observer change | Exact path/region comparison |
| Evidence corresponds to committed bytes | Explicit revisions and final receipts | Untracked artifacts omitted from whitespace check; stale link treated as evidence | G7/G9 audit |

Runtime APIs, codecs, writers, snapshot ordering, collectors, resource-accounting semantics, and real FsDirectory/RustFS paths are consumers of these invariants and remain unchanged. Unit tests exercise the native MemoryDirectory writer/reader path; I08 exercises the existing FsDirectory path; ordinary RustFS CI remains regression evidence. No new backend or fake decoder is introduced.

## 4. Complete-response comparisons

Add one private helper inside `c2_tests`:

```rust
fn assert_c2_f1_full_response(
    actual: &UnifiedResponse,
    expected: &UnifiedResponse,
    label: &str,
) {
    assert_eq!(projected(actual), projected(expected), "{label}: projected hits");
    assert_eq!(bits(actual), bits(expected), "{label}: score bits");
    assert_eq!(actual.total_hits, expected.total_hits, "{label}: total hits");
    assert_eq!(actual.generation, expected.generation, "{label}: generation");
    assert_eq!(actual.view_ordinal, expected.view_ordinal, "{label}: view ordinal");
    assert_eq!(actual.next_cursor, expected.next_cursor, "{label}: complete cursor");
    assert_eq!(actual.aggregation, expected.aggregation, "{label}: aggregation");
}
```

Use it in U17's `assert_refusal_response`, U17 structural recovery versus its forced-Legacy reference, all U21 successful/recovery comparisons, U12 pristine versus forced Legacy, and every U12 post-row pristine recovery versus the saved pristine response. Keep literal expected key/total assertions and cursor-present checks separately; two identically wrong routes are not the sole oracle.

`projected()` compares ordered keys, score bits and projected fields. `bits()` supplies the separately required explicit bit witness. `UnifiedCursor` already derives `PartialEq`; do not compare only `.is_some()`, serialize cursors through a new format, strip fields, or rebuild the fixture to make cursors compare.

In I08's existing `assert_same_response`, replace cursor-presence comparison with `assert_eq!(left.next_cursor, right.next_cursor, "{label}: complete cursor")`; add `assert_eq!(left.aggregation, right.aggregation, "{label}: aggregation")`. Retain hit count, total, generation, view, ordered keys/projected fields and score-bit comparisons. Change the helper comment to say complete cursor equality. All resource/cancellation inputs and outcomes remain unchanged.

Before each measured C2 query reset, in order, `reset_witnesses()`, `b2_observation::reset()`, `b3_observation::reset()`, and `reset_b3_counters()` when its counters are used. Capture/assert C2 observations before any reference query. `forced_legacy_with` resets C2/physical observations but not B2/B3; explicitly reset all relevant modules before each recovery. Create `ForceLegacy` or `ScoreFailureArm` only after resets; never call `strict()` while armed.

## 5. U21: exact native-order boundary table

Keep the existing registered function `c2_u21_work_budget_exhaustion_after_prior_segment`. Remove the geometric sweep, `saw_failure`, permissive differential verdict checks and its generic success tail. Replace them with the fixed table below.

### 5.1 Frozen fixture and guard

Use exactly:

```rust
let fixture = Fixture::new(&[
    body_documents(6),
    body_documents(40).into_iter().skip(6).collect(),
]);
let request = request_asc(term_body(), 2);
let config = linear_config();
assert_native_boundary_fixture(&fixture);
```

Do not reverse commits, reconstruct a reordered test snapshot, change keys, change frequencies, or search for a corpus with preferred hashes.

Add this private helper inside `c2_tests`; its temporary reader guards must drop before measured queries:

```rust
fn assert_native_boundary_fixture(fixture: &Fixture) {
    const EXPECTED: [(&str, u64, usize); 2] = [
        (
            "s-920b6e02921926f20ee4e865aecf1a4d0ca69e17e39cdd09fee6bd6ff0f7c097",
            34,
            6,
        ),
        (
            "s-f915efbfc5652be3911bb2cddbacadee03d9466c68dd5fbd9bef28d7957fd495",
            6,
            0,
        ),
    ];
    assert_eq!(fixture.snapshot.segment_count(), EXPECTED.len());
    assert_eq!(fixture.snapshot.document_count(), 40);
    for (segment_index, &(expected_id, expected_docs, global_start)) in
        EXPECTED.iter().enumerate()
    {
        let segment = &fixture.snapshot.segments()[segment_index];
        assert_eq!(segment.meta().segment_id(), expected_id);
        assert_eq!(segment.doc_count(), expected_docs);
        let guard = fixture.snapshot.open_segment_reader(segment_index)
            .expect("native fixture reader");
        let reader = guard.reader();
        assert_eq!(reader.doc_count(), expected_docs);
        let live = fixture.snapshot.effective_live_docs(segment_index, reader)
            .expect("native fixture live mask");
        assert_eq!(live.len(), usize::try_from(expected_docs).expect("small count"));
        assert!(live.iter().all(|flag| *flag), "native fixture must be all live");
        let body_field_id = reader.schema().field_id("body").expect("body field id");
        assert!(reader.field_norms().and_then(|norms| norms.field(body_field_id)).is_some());
        for local_doc in 0..expected_docs {
            let expected_key = bounded_key(
                global_start + usize::try_from(local_doc).expect("small local id")
            );
            let actual_key = reader.doc_key(local_doc).expect("native fixture key");
            assert_eq!(actual_key.as_str(), expected_key.as_str());
        }
    }
}
```

The guard reads keys/live masks/norm metadata; it must not call ordinal preparation or key-identity binding. Reset request observations after it. A mismatch is A08 STOP; do not recalculate table constants from the new fixture.

### 5.2 Fixed calculation and observations

Global document `i` has alpha frequency `1 + i % 4`. Query slot 0 contains global 6..39, total 87; its final local doc 33 has frequency 4. Slot1 contains global 0..5 with frequencies1,2,3,4,1,2, total 13. Persisted norms and the all-live guard keep stats preparation from consuming scanned occurrences. The entire query total is100.

Use default limits except `.with_max_scanned_posting_occurrences(cap)`. Use the same `linear_config()` for C2, forced Legacy and recovery.

| Row | Cap | Required result | Evaluators | Membership | Converted | Completed callbacks | Numeric candidates | Bound columns | Completed segments |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| U21-A86 | 86 | `ResourceLimit { limit:86, requested:87 }` | 1 | 0 | 0 | 0 | 0 | 1 | `[]` |
| U21-A87 | 87 | `ResourceLimit { limit:87, requested:88 }` | 2 | 34 | 34 | 34 | 34 | 2 | `[(0,3,34)]` |
| U21-A99 | 99 | `ResourceLimit { limit:99, requested:100 }` | 2 | 34 | 34 | 34 | 34 | 2 | `[(0,3,34)]` |
| U21-A100 | 100 | Success: total 40 | 2 | 40 | 40 | 40 | 40 | 2 | `[(0,3,34),(1,3,40)]` |

Every row requires strict routes1 and Legacy routes0. Read the exact existing accessors `physical::strict_evaluator_calls`, `strict_membership_observations`, `converted_rows`, `callbacks`; `b2_observation::numeric_candidates`, `bound_columns`; and `c2_observation::collected_segments`. The tuple is `(segment_index, heap_len, cumulative_total_hits)`. K=2 means retained heap K+1=3. Capture observed values before reference/reset calls.

For each failure row, call `expect_err` and structurally match the complete `SearchError::ResourceLimit` payload. Then use `forced_legacy_with` with identical request/snapshot/limits/config and require the identical exact payload. Do not accept success, merely any error, matching debug text, or agreement between two unspecified results.

After each failure, independently query the same snapshot at cap 100. Assert the complete success-row counter vector and tuple vector; total 40; keys exactly `doc 000000`, `doc 000001`; cursor present; generation/view equal the fixture's snapshot. Compare the complete response with a same-request, same-snapshot forced-Legacy cap 100 success using section 4. The explicit cap 100 table row requires these same assertions. A failed call produces no response to expose a partial page or cursor.

Print one bounded line after each row's assertions with stable row ID, exact error or success, observed counters and tuples. Print separate recovery labels for the three retries. Do not introduce a new registered test.

## 6. U17: no eager later-segment binding

Preserve all five existing actual B3 cases and their exact counters, fresh-fixture discipline, RAII probe cleanup and full forced-Legacy parity. Their 20+20 fixture does not need the 34+6 correction. Preserve the existing B1 enum/error mapping assertions.

Replace U17's final ordinary two-binding happy-path check and its stale claim that a multi-segment precedence case is executed elsewhere with this exact structural case:

1. Create a fresh section-5 native fixture and run `assert_native_boundary_fixture`. Query `request_asc(term_body(),2)` with default limits and `linear_config()`.
2. Ensure prior B3 probe guards are out of scope, call `clear_b3_probe`, then perform all section-4 observation/counter resets.
3. Within a local scope bind `physical::ScoreFailureArm::arm(33)`, call `run_with` directly, then leave the scope so the arm drops. Do not use `strict()`.
4. Require exactly `SearchError::InvalidScore { detail }` where `detail == "injected C2 score failure"`.
5. Assert the following exact observations before any recovery or reference call.

| Observation | Required value |
|---|---|
| Strict / Legacy routes | 1 / 0 |
| Bound columns / strict evaluator calls | 1 / 1 |
| Membership observations | 34 |
| Converted rows / completed callbacks / numeric candidates | 0 / 0 / 0 |
| Completed segments / owned-key fallback segments | `[]` / `[]` |
| B3 build attempts | 0 |

6. Reset all relevant observations/counters and run the same snapshot unarmed. Require total 40, literal keys0/1, cursor present, bound columns 2, evaluator 2, membership/converted/callback/numeric 40 and completed tuples `[(0,3,34),(1,3,40)]`. Require complete same-request/snapshot forced-Legacy success parity.
7. Print the label `INJECTED_C2_ONLY — no-eager-binding structural evidence` with the observed vector.

This proves that the next segment's column binding has not occurred when the first segment's final local score fails. It is not genuine column-corruption evidence. `converted_rows==0` means no whole segment completed the score-conversion observation; it does not claim that zero individual score operations occurred. Do not invent an identical Legacy score injection.

## 7. U12: complete the nine-case corruption matrix

Keep the single existing function `c2_u12_corrupt_selected_unselected_and_multi_fault`, its native32-row corpus, K=3, matched docs 0..29 and unmatched docs 30..31, copied-container ownership and exact error matcher. Do not change schemas, analyzers, codecs, builder behavior, source committed bytes, row error wrappers or resource semantics.

### 7.1 Add the missing pristine all-live guard

Inside the existing pristine reader block, immediately after `let reader = guard.reader();`, add:

```rust
assert_eq!(reader.doc_count(), 32, "pristine physical document count");
let live = fixture.snapshot.effective_live_docs(0, reader)
    .expect("pristine effective-live mask");
assert_eq!(live.len(), 32, "pristine effective-live mask length");
assert!(live.iter().all(|flag| *flag), "all32 pristine documents are effective-live");
```

Retain physical key-order, persisted `grp` norms, dictionary doc_freq30 and pristine-byte checks. Perform guards only on the pristine native snapshot. Malformed columns must not be required to pass `SegmentReader::open`.

### 7.2 Replace only the final-posting mutation recipe

The actual layout is fixed below. Offsets are relative to the matching dictionary entry's `postings_offset` in the POSTINGS section.

| Region | Relative bytes | Frozen content |
|---|---|---|
| Header | `[0,8)` | `[7,1,30,30,30,30,0x96,0x01]` |
| Document deltas | `[8,38)` | First0, then 29 bytes of1 |
| Frequencies | `[38,68)` | Thirty bytes of1 before mutation |
| Positions | `[68,218)` | Declared150 bytes; preserve exactly |
| Mutation target | `67` | Final document29 frequency:1→0 |

Replace `u12_corrupt_final_posting` with this implementation, subject only to rustfmt/import/borrow corrections permitted by A06:

```rust
fn u12_corrupt_final_posting(copied: &mut CopiedSegment, offset: u64, length: u64) {
    assert_eq!(length, 218, "grp/common compact-short positional payload length");
    let start = usize::try_from(offset).expect("postings offset");
    let end = start.checked_add(218).expect("bounded postings payload end");
    let body = copied.body_mut(crate::segment::SectionKind::Postings);
    assert!(end <= body.len(), "postings payload inside section");
    {
        let payload = &body[start..end];
        assert_eq!(&payload[0..8], &[7u8,1,30,30,30,30,0x96,0x01]);
        assert_eq!(payload[8], 0, "first document delta");
        assert!(payload[9..38].iter().all(|byte| *byte == 1));
        assert!(payload[38..68].iter().all(|byte| *byte == 1));
        assert_eq!(payload[68..218].len(), 150);
    }
    let original_body = body.clone();
    let target = start.checked_add(67).expect("bounded final frequency offset");
    assert_eq!(body[target], 1);
    body[target] = 0;
    assert_eq!(body.len(), original_body.len());
    assert_eq!(&body[start + 68..end], &original_body[start + 68..end]);
    let changed_offsets: Vec<usize> = body.iter().zip(original_body.iter())
        .enumerate()
        .filter_map(|(index, (after, before))| (after != before).then_some(index))
        .collect();
    assert_eq!(changed_offsets, vec![target], "exactly one POSTINGS byte changed");
    assert_eq!(body[target], 0);
}
```

Keep the existing native container rebuild so section/container integrity is correct. The only semantic mutation is the specified frequency byte; checksum changes caused by rebuilding are expected. Do not set positional length to zero, rewrite any frequency-total header, remove positions, change the encoder, add a parser, or scan for an alternate offset.

In `u12_probe_final_posting`, retain ordered doc IDs0..28 followed by exact `SegmentError::ZeroFrequency { doc_id:29 }`. In each successful `Ok(Some(posting))` arm also require `posting.freq == 1` before recording its doc ID. The decoder checks zero frequency before that row's positions, so the error remains ZeroFrequency even though positions and the original aggregate-frequency header are intact. Any other outcome is STOP after checking transcription against this recipe.

### 7.3 Correct direct-probe precedence on combined bytes

The current runner probes keys before columns. For C29+P29+D0, that incorrectly calls `SegmentReader::open(...).expect(success)` despite eager column validation. Replace only that dispatch with:

```rust
if row.sort_column_record.is_some() {
    u12_probe_sort_column(&rebuilt);
} else {
    if row.final_posting {
        u12_probe_final_posting(&rebuilt);
    }
    if row.doc_key_record.is_some() {
        u12_probe_doc_keys(&rebuilt);
    }
}
```

D0, P29 and C29 individually establish the component mutations; the combined row establishes precedence. Do not weaken its column error or open malformed columns through a substitute reader. The query/Legacy checks still execute on the combined snapshot.

### 7.4 Frozen row table and exact execution accounting

Require all rows in this order. Keep the existing constructors `row`, `posting_row`, `column_row`; declare all three before the call sequence.

| ID | Mutations / injected fault | Exact expected error | Strict/Legacy | Evaluators | Converted | Callbacks | Numeric | Membership |
|---|---|---|---|---:|---:|---:|---:|---:|
| D0 | DOC_KEYS0 | `SearchError::Segment(InvalidUtf8 { context:"doc key" })` | 1/0 | 1 | 30 | 0 | 1 | 30 |
| D29 | DOC_KEYS29 | Same DOC_KEYS error | 1/0 | 1 | 30 | 0 | 1 | 30 |
| D31 | DOC_KEYS31, a nonmatch | Same DOC_KEYS error | 1/0 | 1 | 30 | 0 | 1 | 30 |
| P29 | Final matching frequency 0 | `SearchError::Segment(ZeroFrequency { doc_id:29 })` | 1/0 | 1 | 0 | 0 | 0 | 0 |
| P29+D0 | Posting plus DOC_KEYS0 | Same ZeroFrequency error | 1/0 | 1 | 0 | 0 | 0 | 0 |
| C0 | Sort-column0 invalid UTF-8 | `SearchError::Index(IndexError::Segment(InvalidUtf8 { context:"keyword" }))` | 0/0 | 0 | 0 | 0 | 0 | 0 |
| C29 | Sort-column29 invalid UTF-8 | Same nested column error | 0/0 | 0 | 0 | 0 | 0 | 0 |
| C29+P29+D0 | All three real mutations | Same nested column error | 0/0 | 0 | 0 | 0 | 0 | 0 |
| S29+D0 | Score arm 29 plus DOC_KEYS0 | `SearchError::InvalidScore`, detail `"injected C2 score failure"` | 1/0 | 1 | 0 | 0 | 0 | 30 |

Change `run_row` to return `&'static str`, returning `row.id` only after its existing exact-error, observer, repeat, forced-Legacy, immutable-original and complete pristine-recovery assertions. Keep all of those checks. Retain the C2-only label and unarmed real-fault controls for S29+D0. For real byte faults repeat once on the same corrupted snapshot. Keep the existing zero-match controls for rows without column corruption and in-place preservation assertion where converted 30.

Replace all standalone calls/blocked placeholders with this exact completion array:

```rust
let completed_rows: [&'static str; 9] = [
    run_row(row("D0", Some(0), false, None)),
    run_row(row("D29", Some(29), false, None)),
    run_row(row("D31", Some(31), false, None)),
    run_row(posting_row("P29", true, None)),
    run_row(posting_row("P29+D0", true, Some(0))),
    run_row(column_row("C0", 0, false, None)),
    run_row(column_row("C29", 29, false, None)),
    run_row(column_row("C29+P29+D0", 29, true, Some(0))),
    run_row(U12Row {
        id: "S29+D0",
        doc_key_record: Some(0),
        final_posting: false,
        sort_column_record: None,
        injected_score: Some(29),
        routed: true,
        converted: 0,
        callbacks: 0,
        numeric: 0,
        membership: 30,
    }),
];
assert_eq!(completed_rows, [
    "D0", "D29", "D31", "P29", "P29+D0",
    "C0", "C29", "C29+P29+D0", "S29+D0",
]);
eprintln!("C2-F1-A1 U12 completed=9 ids={completed_rows:?}");
```

Remove `let _ = posting_row` and blocked-row placeholders. Add no test registrations or ignore/skip mechanism. Returning an ID only after recovery prevents the final completion line from claiming a partially executed row succeeded.

## 8. Preserve verified resource work

P05 remains byte-identical, including all six cap combinations, actual meter totals20/38/53/53/40/53, zero ledgers and same-budget retry. I08 retains its exact admitted resource peak69 entries/2944 bytes, failures68→69 and2943→2944, scanned22→23, cap 23 success, cancellation and same-snapshot retries. Only section 4's comparison strengthening is authorized in I08.

No new production memory/work rule, test seam, clock, concurrent state, error type, dependency or schema is needed. Resource arithmetic is a fixed oracle, not a value to adjust until tests pass.

## 9. Implementation order and source freeze

Execute these stages continuously; an isolated stop does not cancel independent stages.

| Stage | Exact work | Exit evidence |
|---|---|---|
| P0 | Section3 admission, baseline inventories/receipts, correctness worksheet | Immutable identities and classified starting state |
| P1 | Complete-response helper and I08 helper changes | Focused U17/U12/I08 receipts; capture any existing failure |
| P2 | Native boundary guard, replacement U21, U17 structural case | Four U21 rows, three recoveries, five retained B3 cases, structural case |
| P3 | U12 all-live guard, corrected posting recipe, precedence-aware probes, nine-row completion | Nine case lines and completed=9 after all recoveries |
| P4 | A1 path/region freeze and exact inventories | Only allowed diffs; 24/5/9 counts |
| P5 | All final focused, serial/parallel, retained regression and mandatory local QA | Command receipts, both coverage results, full whitespace classification |
| P6 | New report, append-only errata, narrow status notes, ordinary commit/push and CI | Accurate gates and current source linkage |
| P7 | Final handoff | Draft/unmerged; G10 open; any blocked G7 explicit |

For A1 source isolation, compare A1 START with final source and require `execute.rs` exactly equal. In `unified.rs`, remove only the existing `#[cfg(test)]\nmod c2_tests {` region through `// C2_TESTS_CLOSE_MARKER` using unique exact markers; require only whitespace after that closing marker. Remove exactly the old two-line `record_owned_key_fallback_segment` explanatory comment from START and exactly its prescribed section 2.2 replacement from the candidate, once each. Compare every remaining byte. The exact old comment is:

```rust
    /// PERF-06-C2-F1: this segment's only key-identity attempt was refused, so the
    /// accepted owned B2 key handler ran for it.
```

The original F1 section 9 comparison against F1 START, with only its precisely authorized test-region/two-site exclusions, is additionally mandatory. This is a second check, not an alternative. Do not broaden exclusions, remove observer statements from the A1 comparison, or normalize whitespace to obtain equality.

For the integration file inspect the exact diff: only I08's local helper/comment may differ. Require all other protected paths unchanged from A1 START and preserve the original F1-to-current normal-build comparison. Save the actual checking script and result as new evidence. This establishes normal-build source equality; it is not a compiled-binary or performance claim.

## 10. Whitespace failure: truthful evidence and scoped human decision

### 10.1 What must be corrected

The original receipt ran `git diff --check` while new plan/evidence files were untracked. That command did not check all committed F1 additions. Its claim that the worktree was “exactly the F1 change set” is false. Independently checking the exact supplied F1 plan as an added file produces 11 whitespace diagnostics: trailing spaces on lines 3–9, 378, 853–854 and a blank line at EOF 1005. Therefore “all 25 errors pre-existed F1” and “final F1 delta clean” are not valid final-range conclusions.

The author reconstructed all 91 changed paths between accepted main and reviewed head from exact Git blobs. Under ordinary Git whitespace rules the result is **55 diagnostics in 40 added documentation/evidence artifacts**: 19 in original C2 artifacts, 11 in the verbatim F1 plan and 25 in F1 raw logs ending with a blank line. The four modified documentation paths and three Rust paths add zero diagnostics. Appendix A freezes the exact affected paths, blob identities and diagnostics. This is a current source reconstruction, not a historical command receipt; the final repository range command remains mandatory. The historical “25 entries” may have counted output lines rather than diagnostic lines, but the unavailable raw output prevents asserting that explanation as fact.

This is partly an authoring conflict: the original plan required verbatim commitment of whitespace-bearing text while also requiring a clean full-PR whitespace gate. Do not blame or silently alter runtime source to resolve it. Preserve the historical file and receipts, correct the claims, and leave the gate blocked absent an explicit applicable human exception.

### 10.2 Required committed-range receipts

After all source, plan, report and evidence additions are committed, record these exact range checks using admitted immutable SHAs, command exit codes and actual stdout/stderr. Re-run the range checks after the last documentation-only commit as well. Never substitute a clean worktree check.

```sh
git diff --check 46ccab0a606a56a8b9034ab4db5c9c4df969d098..HEAD
git diff --check 2bf9539cd2f53838ad1aca406ca4e67a34229ff6..HEAD
git diff --check bc726420cede2e26681d6e8192b45a5d0169abbf...HEAD
git diff --check
git diff --cached --check
```

If A02 admitted a later documentation-only A1 START, additionally check that actual START..HEAD and retain the pinned2bf comparison. Before committing, use explicit staging plus `git diff --cached --check` to include new A1 files; record unrelated untracked paths separately. Prevent new A1 Markdown trailing spaces and trailing blank EOF lines. New raw logs may contain output whitespace; preserve them faithfully and classify that fact instead of deleting or rewriting output.

Baseline reproduction uses the same range and whitespace configuration at the pinned old revision. Record effective `core.whitespace` and applicable attributes without changing either. Do not suppress blank-at-eol/blank-at-eof, introduce attributes, narrow the mandatory full-PR range, or replace failure with a baseline-relative pass.

### 10.3 Exception boundary

The default is **G7 BLOCKED**. The original F1 D29/D30 rules and repository AGENTS require human disposition of a failing mandatory check; this amendment does not grant one. All independent test/evidence work continues.

Appendix A already provides a concrete proposed exception scope for the reviewed head. It is not an approved exception. After final committed-range receipts exist, reconcile every observed diagnostic with that list and prove listed blobs remain identical. The proposed exception may cover only the listed whitespace already present in those frozen plans/raw receipts. It may not cover Rust, build/configuration, CI, new A1 prose, newly introduced whitespace elsewhere, missing tests, or inaccurate reports. Preserve all raw command failures even if approval is later granted. Any extra diagnostic requires correction under A26 if it is owned new prose/source, or a separately explicit human decision if it is immutable evidence; it does not inherit Appendix A's possible exception.

If the user/maintainer explicitly grants that exact exception, record the authorization reference and scope. Report the whitespace command **FAIL — authorized exception**, and G7 **SATISFIED WITH EXPLICIT EXCEPTION**, never “the command passed.” If an exception is absent, ambiguous, broader/narrower than observed diagnostics, or additional unapproved diagnostics exist, keep G7 BLOCKED. General permission to execute this plan is not whitespace-exception approval. Any request instead to rewrite historical artifacts requires a separate precise amendment before modifying them.

## 11. Mandatory verification and case receipts

### 11.1 Focused commands and exact counts

Run all cargo/script child commands with the two experiment overrides removed. Use this prefix literally, without changing the user's persistent environment:

```sh
env -u QUERVANT_PR15I_D3C_STRATEGY -u QUERVANT_PR15I_D3C_PREFILTER_PROFILE
```

The prefix is shown separately for readability; put it immediately before each command below. Do not execute it alone as an environment dump.

| Focus | Command after prefix | Required selection |
|---|---|---:|
| U17 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u17_ordinal_unavailable_and_b3_refusal -- --exact --nocapture --test-threads=1` | 1 |
| U21 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u21_work_budget_exhaustion_after_prior_segment -- --exact --nocapture --test-threads=1` | 1 |
| U12 | `cargo +1.98.1 test -p quervant-core --lib search::unified::c2_tests::c2_u12_corrupt_selected_unselected_and_multi_fault -- --exact --nocapture --test-threads=1` | 1 |
| P05 retained | `cargo +1.98.1 test -p quervant-core --lib search::execute::c2_physical_tests::c2_p05_n_examination_and_scanned_frequency -- --exact --nocapture --test-threads=1` | 1 |
| I08 | `cargo +1.98.1 test -p quervant-core --test perf06_c2_physical c2_i08_resource_cancellation_atomicity -- --exact --nocapture --test-threads=1` | 1 |

After final edits run the original F1 section 10–12 exact inventory, module, all-features, regression and local QA commands. This reference preserves every original command; it is not permission to select a subset. Required registered-name counts remain unified24, physical5, integration9, broad `--lib c2_`39. No names added, removed, renamed or ignored. U12 is one function with nine fault rows; its pristine/retry/control calls are separate case evidence, not additional functions.

Run unified and physical modules with `--test-threads=1` and `--test-threads=8`; preserve all-feature selections from the original plan. Run the nine integration functions. Retain B1/B2/B3 unit filters and `perf06_b1_ordinals`, `perf06_b2_ordinals`, `perf06_b3_keys`, `pr15h_a_candidate_materialization`, `pr15h_a2_dispatch` regressions. Expected historical counts are context, not a substitute for captured final selected-name sets. Zero-test success is failure of the verification command.

### 11.2 Full final local QA

After final source/test edits execute all commands below sequentially against the same final source, each with the experiment-removal prefix:

```sh
cargo +1.98.1 fmt --all -- --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.98.1 test --workspace --all-targets
cargo +1.98.1 test --workspace --all-targets --all-features
cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.98.1 doc --workspace --no-deps
cargo +1.98.1 doc --workspace --all-features --no-deps
cargo +1.98.1 bench --workspace --no-run
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
bash benchmarks/scripts/test-scripts.sh
```

Both workspace coverage results must be at least 85% lines; no exclusions or threshold changes. Record actual covered/missed totals and percentages. Do not copy historical2739/2784 test counts or93.24%/92.82% as new measurements. No concurrent cargo processes against the same target directory. Full workspace runs use normal concurrency; do not serialise them to hide a flake.

For every receipt record command, source/test identity, working directory, toolchain, start/end timestamps, real command exit status, test counts and complete relevant output. Use `set -o pipefail` with `tee`. Number all attempts and retain failed attempts. For new receipts preserve raw output between explicit `BEGIN RAW OUTPUT` and `END RAW OUTPUT` delimiters, then append real exit/source/end-time metadata and a final nonblank `END RECEIPT` line. This retains raw bytes while avoiding a new blank EOF merely from the command's final newline; do not trim or rewrite the raw body. An empty fmt output still needs the actual command and exit metadata. If retained raw-body whitespace triggers a diagnostic, apply A30 rather than sanitizing it. Do not claim `c2-f1-u21-attempt-02.txt` exists: the reviewed tree contains only `c2-f1-u21-attempt-01.txt`. New receipts use `c2-f1-a1-…` names.

The known certificate-counter flake retains the original bounded diagnostic policy: first failure preserved; at most one identical-current-source diagnostic repeat and two isolated baseline diagnostic runs, then stop diagnostics. A later green result does not erase a mandatory failure or approve an exception.

### 11.3 Ordinary CI

After normal push, observe the existing ordinary PR workflow; do not launch duplicate equivalent runs. Require terminal successful `rust`, `msrv`, `python-benchmark-framework`, `benchmark-adapter-contract`, and `rustfs` jobs. Record PR head, merge checkout if used, workflow/run/job IDs and actual required-body execution. Old run 45828518258 is historical baseline only after A1 test changes. If CI is pending/inaccessible, continue independent local/evidence work, mark G8 PENDING/BLOCKED and preserve the observed PR readiness state.

## 12. Reports, identities, errata and gate semantics

Create `PERF06C2F1_A1_EXECUTION_REPORT.md` with the original F1 section 13.1 eleven-section report structure. Include all A1 invariants, matrix rows, exact observed vectors, new receipts, final name sets, source-freeze results, QA/coverage, ordinary CI, decisions and residual limits.

Append a dated A1 erratum to the F1 report covering all of these facts, using observed status:

1. The two D14 stops were correct; the plan's segment-order and posting-layout assumptions were wrong. Cite this amendment and new execution receipts.
2. U21 and U17's structural row were not executed by the prior F1 implementation. Their status changes only when the amended tests execute successfully.
3. Previous U12 evidence executed six of nine rows. The earlier sentence saying a skipped final posting “would now be rejected” was not established by that run. State actual nine-row results only after execution.
4. Previous “complete/identical” response comparisons checked cursor presence, not complete cursor equality; I08 also omitted aggregation equality. Cite the strengthened assertions and new receipts.
5. Correct G7 PASS, “F1 delta clean,” and “all pre-existing” statements. Include actual committed-range failures and any explicit human exception; preserve the old receipt unchanged.
6. Correct the nonexistent `c2-f1-u21-attempt-02.txt` citation; point to the actual historical attempt01 and new A1 receipts without renaming history.
7. Clarify which old revisions/CI runs are historical and provide the new identity record. Do not silently change historical BASE semantics; use section 3's explicit identity definitions.
8. Correct historical coverage labels without changing the raw measurements: default 74,113 total lines, 69,103 covered, 5,010 missed, 93.24%; all features 75,622 total, 70,196 covered, 5,426 missed, 92.82%. The earlier report incorrectly called the default total the covered count. New A1 coverage must use actual newly measured totals.
9. State the old source-freeze receipt's limits: it lacks the exact checking script and tested dirty-diff hash required by the plan, and several old command receipts omit invocation/exit/source metadata. Provide complete new receipts; do not invent missing historical timestamps or exit statuses. Independent current-source equality supports preservation, not reconstruction of unrecorded historical command metadata.

Preserve the old reports as exact byte prefixes, then append. Link the A1 report from the series register and current C2 roadmap note. No DONE/accepted/merged marker while G10 is open.

### 12.1 Revised gate meanings

| Gate | Required A1 closure | Starting assessment / boundary |
|---|---|---|
| G0 | Fresh source admission and explicit identity meanings | Reviewed metadata consistent; rerun at execution |
| G1 | Completed worksheet and invariant/decision ledger | Must reflect corrected fixtures |
| G2 | Allowed paths only; A1 source freeze and original F1 normal-build comparison | Historical source isolation passed |
| G3 | Five actual B3 rows with full parity, U17 structural row, all four U21 rows and three retries | PARTIAL until amended cases pass |
| G4 | All nine U12 rows, exact completed-ID array, pristine/all-live guards, correct direct probes and recovery | PARTIAL until all execute |
| G5 | Existing P05 exact resources/reuse and I08 exact outcomes plus complete retry-response parity | Resource outcomes sound; I08 comparison incomplete at A1 start |
| G6 | Exact24/5/9 inventory; required serial/parallel/feature/regression suites | A green inventory does not close G3/G4 |
| G7 | All mandatory local QA and final committed-range whitespace disposition | BLOCKED absent correction or explicit applicable human exception |
| G8 | Ordinary CI for A1 tested source, with five jobs and actual required bodies | Old CI remains historical only |
| G9 | Accurate new report, append-only errata, existing receipt links, exact source/delivery linkage | Prior overclaims need correction |
| G10 | Independent review and maintainer acceptance | OPEN; coding agent cannot close |

If all G0–G9 are satisfied, with any human exception separately identified, use `PERF06_C2_F1_A1_EXECUTED_PENDING_INDEPENDENT_REVIEW`. If only the whitespace decision remains, use `PERF06_C2_F1_A1_ACCEPTANCE_EXECUTED_G7_BLOCKED_WHITESPACE_DECISION`. If a prescribed semantic/fixture condition fails, use `PERF06_C2_F1_A1_STOPPED_AMENDMENT_REQUIRED` and list affected gates. These are descriptive dispositions, not permission to label an unverified task complete.

### 12.2 Commit and delivery identity procedure

1. Record the tested source/worktree hash; commit only the allowed source/test changes and this verbatim amendment. Prove committed bytes equal the tested bytes, then call that commit `A1_TESTED`.
2. Commit new evidence/reports/status notes separately. Every later `A1_FINAL` must be source-equivalent to `A1_TESTED`: empty diff across `crates/`, manifests/lockfile, toolchain, `.github/`, benchmarks, and unchanged protected contracts.
3. Push normally; never force. Fetch and verify remote equality. Preserve the observed readiness flag without toggling it. Update the existing PR body from a prepared file with accurate gates and links; no comments, reviewer messages, approvals or merge.
4. A later CI-evidence commit supersedes the earlier final delivery SHA. After the last repository commit and normal push, fetch and freeze the observed remote head as literal immutable `H`. The final handoff must name that latest remote-verified head, not an earlier docs commit. The committed report may explicitly identify the previously captured evidence revision; do not create an endless self-referential identity commit.
5. Run every final committed-range check in section 10.2 with the literal value of `H` substituted for `HEAD`, and verify the remote still equals `H` at handoff. Capture the complete commands, outputs, exit codes, source-equivalence result and current identity in a terminal receipt outside the checkout, named `perf06-c2-f1-a1-terminal-<H>.txt` using the actual hash. Deliver that file with the final handoff; if attachment delivery is unavailable, include its complete contents in the final handoff text. Do not commit this terminal receipt: diagnostic output repeats offending whitespace, and committing each final-range receipt would create a new range and possibly new whitespace diagnostics. Do not claim the terminal receipt belongs to commit `H`. If the remote changes, apply source-admission rules before issuing a current-state claim. Source-equivalent docs changes do not require another optional Rust test campaign, but final range/identity checks are mandatory.

## 13. Preauthorized decisions and exception-handling matrix

A = AUTO-RESOLVE, D = DEFER AND CONTINUE, S = scoped HARD STOP. Source/scope/contract stops take priority. Apply a known conformance correction only when its precise trigger is proved, then run the affected focused check once. If it still disagrees, apply the semantic/layout stop; do not iterate expectations until green. Record rule ID, evidence, action, verification, affected gate and owner for every exception.

| ID | Observable condition | Class | Exact authorized action | Prohibited action / owner | Required evidence / affected gate |
|---|---|---|---|---|---|
| A01 | Pinned main/head/PR and clean affected paths match | A | Admit source and execute all remaining stages | Routine reconfirmation; Agent | Fresh refs/PR state/worktree status; G0 |
| A02 | Head is a descendant of 2bf with only append-only C2 report/status additions or new evidence; source/tests/contracts/guide/build/CI, all original plans/raw receipts and every Appendix A blob remain identical | A | Preserve additions, record actual A1 START and full delta, check all protected blobs, and use unchanged design | Admit rewritten historical evidence or executable drift as doc-only; Agent | Ancestry, complete changed-path list, append-only prefix checks and protected blob equality; G0/G9 |
| A03 | Main advanced; PR closed/merged/retargeted; source/test/contract/toolchain drift; conflicting dirty work | S | Preserve state and request precise amendment | Rebase/reset/overwrite/adapt design; Maintainer | Exact ref/PR/diff collision evidence; G0 and dependent gates |
| A04 | Local branch missing or cleanly behind exact admitted remote | A | Create tracking branch or fast-forward only | New PR, merge commit, force; Agent | Before/after local and remote SHAs, clean status; G0 |
| A05 | Foreign untracked/dirty item is outside scope and cannot influence checks | A | Record, leave untouched, stage named paths only | Broad staging or cleanup; Agent | Foreign path list and build-independence explanation; G0/G9 |
| A06 | Introduced test helper has compiler/import/borrow/rustfmt/Clippy conformance error with unchanged prescribed behavior | A | Correct only local syntax/formatting or equivalent assertion expression; retain failure; rerun focused check | Change corpus, constants, APIs, semantics or error expectations; Agent | Compiler/lint diagnostic, bounded diff and focused receipt; G2–G5, then G6/G7 reruns |
| A07 | Exact prescribed call/assertion/reset/probe dispatch was omitted or transcribed incorrectly | A | Restore this document's exact design and rerun focused check once | Invent replacement assertions; Agent | Exact omitted-plan mapping, bounded correction and receipt; affected G2–G5/G6, then G7 reruns |
| A08 | Native IDs/order/keys/live mask/norms,218-byte layout, prefix, unique mutation or direct decoder guards disagree after transcription check | S | Preserve actual bytes/guards and stop affected rows | Reorder, regenerate alternate fixture, search bytes, tune offsets/caps; Maintainer | Fixture identity, actual guard values/bytes and failed receipt; G3/G4 |
| A09 | Any exact error, counter, completion tuple, retry, cursor or aggregation differs after applicable A06/A07 repair | S | Preserve expected/actual result and stop affected acceptance | Accept either result, broaden matcher, drop parity, repair production; Maintainer | Exact expected/actual payload/vector/response and failed receipt; G3–G5 |
| A10 | B3 probe missing solely because earlier unauthorized search warmed fixture | A | Restore specified fresh-fixture order, then rerun once | Remove probe assertion or accept only output parity; Agent | Pre-search ordering proof, corrected fresh fixture and probe count; G3 |
| A11 | B3 counters still disagree on a verified fresh fixture | S | Preserve row/counters; stop that row | New probe/seam or expectation relaxation; Maintainer | Freshness proof plus probe/build/fallback counters; G3 |
| A12 | Combined column row fails at the old key-probe open before the query | A | Apply section 7.3 exactly, then rerun U12 once | Make malformed column open successfully or weaken column error; Agent | Failed open, precedence-aware dispatch diff and U12 receipt; G4 |
| A13 | Synthetic score arm is cleared by a reset or `strict()` | A | Reset before arm and call `run_with` directly, then rerun once | Change injector, scorer or Legacy behavior; Agent | Reset/arm/call order and focused case receipt; G3/G4 |
| A14 | Real fault repeats/recovery mutate original bytes or budget/snapshot no longer reusable | S | Preserve identities/bytes/ledger/outcome | Rebuild pristine snapshot to hide failure or manually zero ledger; Maintainer | Original/current bytes or budget fields, snapshot identity and retry error; G3–G5 |
| A15 | U12 has fewer/different completed IDs or the test-name inventory changes unexpectedly, after any exactly applicable A07 omitted-call repair and its one verification | S | Retain the remaining mismatch and stop affected acceptance | Invent extra tests, ignore rows or count controls as functions; Maintainer | Expected/actual completion IDs and registered-name sets; G4/G6 |
| A16 | Exact command selects zero solely from a typo while intended name exists in recorded inventory | A | Fix command spelling once; require exactly one selected function | Rename tests or accept exit0; Agent | Captured inventory, mistyped/corrected commands and selection counts; G6 |
| A17 | Serial passes but parallel fails after any exactly applicable A06/A07/A13 repair and its one verification | S | Preserve both results and stop affected acceptance | Add global locks, lower required concurrency or ignore test; Maintainer | Serial and parallel commands/results plus bounded repair evidence; G3–G6 |
| A18 | Freeze fails solely due to identified agent-owned accidental drift with known A1 START bytes | A | Restore only that accidental drift, then rerun freeze once | Broad restore, foreign work loss or broader exclusions; Agent | Known START bytes, owned drift/restoration diff and freeze receipt; G2/G9 |
| A19 | Protected behavior/path change is required or unexplained freeze mismatch remains | S | Report minimum needed amendment | Disguise runtime change as test cleanup; Maintainer | Exact protected diff and smallest required change; G2/G9 and dependent acceptance |
| A20 | Final source/test bytes changed after QA | A | Reexecute all affected mandatory checks, including full workspace coverage | Reuse stale acceptance; Agent | Changed-source identity and complete required rerun ledger; G3–G8 |
| A21 | Only permitted docs/evidence changed after TESTED and source equality is proved | A | Reuse source QA, update identities and final range receipts | Claim old revision is current or skip docs/range checks; Agent | Empty executable/protected diff, new FINAL and range receipts; G7/G9 |
| A22 | Required tool/service/access is unavailable | D | Attempt bounded ordinary setup of pinned prerequisites; finish independent work | Substitute versions, new services or gate waiver; Repository owner | Failed setup/invocation and prerequisite details; affected G6/G7/G8 |
| A23 | Mandatory failure is shown pre-existing or flaky | D | Retain actual failures and bounded baseline diagnostics; gate remains blocked | Retry-to-green or self-approved exception; Maintainer | All current/baseline attempts and bounded failure classification; G7/G8 |
| A24 | Whitespace check failed and no explicit applicable human exception exists | D | Complete independent work; prepare exact committed-range exception request; G7 BLOCKED | Rewrite frozen history or mark PASS; Maintainer | Final immutable-range outputs, artifact blobs and proposed scope; G7 |
| A25 | Explicit human whitespace exception identifies the exact frozen diagnostic scope and all non-whitespace G7 mandatory commands pass | A | Preserve raw FAIL; record authorization; G7 SATISFIED WITH EXPLICIT EXCEPTION | Extend scope or call command PASS; Agent applies, Maintainer authorizes | Explicit authorization reference, exact diagnostic/blob match and retained FAIL; G7/G9 |
| A26 | New whitespace occurs in agent-authored A1 prose/source | A | Correct owned new text only, recheck staged/final ranges; preserve failed receipt | Rewrite old plans/raw logs; Agent | Owned new-text correction plus staged/final-range receipts; G7/G9 |
| A27 | Required CI is pending/inaccessible | D | Finish independent evidence; observe existing run and report pending/blocked | Duplicate workflow, changed triggers or invented pass; Repository owner | Run/head/job IDs, observed pending/error state; G8/G9 |
| A28 | Coverage below 85% or required invariant unproven after prescribed tests | S | Preserve measurement/gap and request exact additional design | Lower floor, add exclusions or unplanned filler tests; Maintainer | Measured totals/percentage or named unproven invariant; G3–G7 as applicable |
| A29 | Success checkpoint or authorized local correction completed | A | Continue the next prescribed independent stage automatically | Stop merely to ask whether to continue; Agent | Completed checkpoint receipt and next prescribed stage; relevant next gate |
| A30 | A newly captured raw A1 log contains whitespace diagnostics despite a nonblank metadata footer | D | Preserve raw bytes, list exact new path/blob/diagnostic, finish independent work and leave G7 BLOCKED pending a separate explicit decision | Trim output, extend Appendix A or infer its exception covers new logs; Maintainer | Raw log blob, command, diagnostic and separate decision request; G7/G9 |
| A31 | Only the PR readiness flag differs from an earlier observation; admitted refs remain exact and PR #131 remains open, unmerged and based on main | A | Record the fresh boolean and preserve it; continue prescribed independent work with G10 OPEN | Mark ready, restore draft, infer approval or waive any acceptance gate; Agent | Fresh PR metadata, exact refs and unchanged admission facts; G0/G9, with G10 OPEN |
| A32 | Any unforeseen condition not matched exactly above | S | Stop affected work, preserve evidence, name smallest missing decision; continue safe independent stages | Generalize a rule or improvise architecture/testing; Maintainer | Observed condition, affected invariant/path and smallest missing decision; every directly dependent gate |

The original F1 matrix remains applicable where compatible. A1's more specific rules govern these amended cases; the more restrictive rule governs any unresolved conflict. Neither matrix grants merge authority or a whitespace exception.

## 14. Final adversarial review and residual limits

Before delivery, answer each item with source/receipt evidence:

- Native query order remained 34+6; no fixture reorder, alternate corpus or decoder change.
- U21 has exactly four fixed rows and three same-snapshot successful recoveries; caps 87/99 prove prior completed tuple `(0,3,34)`.
- U17's five actual B3 cases remain; score arm 33 is applied after resets; exactly one column binding occurs before the injected failure.
- U12 final frequency is at relative67; unchanged positions are asserted; each direct successful posting has freq 1; exact final error is doc 29 ZeroFrequency.
- Column-present combined bytes run only the eager column probe; the public/Legacy triple-row error remains the complete nested column error.
- U12 prints completed=9 only after the exact ordered completion array and all row assertions/recoveries succeed.
- Same-snapshot comparisons include actual cursor and aggregation values, with explicit score bits; a presence-only comparison cannot satisfy them.
- P05 and all runtime/source-protected paths remain unchanged; no added seam, test registration or ignored test.
- Local final QA/coverage, case receipts and ordinary CI identify the final tested source; failure classification does not silently turn FAIL into PASS.
- Reports preserve history, correct the missing receipt/overclaims, and distinguish test functions, executed matrix rows, regression CI, source review and new acceptance.
- G7 is either actually satisfied or explicitly excepted by a human; otherwise it is BLOCKED. G10 stays OPEN.

Residual limits are unchanged: score injections are structural C2-only evidence; malformed columns establish the shared pre-route boundary; these exact native fixtures do not prove all formats/corpora; no new end-to-end B1 NotAvailable fixture is added; immutable copied corrupt segments do not mutate durable committed storage; and source isolation/correctness/coverage do not prove performance. C4 owns performance qualification. C3/C4 remain unstarted. A newly exposed production defect requires a separate source-grounded amendment.

## 15. Required final handoff

Use the original F1 section 18 report structure with these A1 additions:

```text
REPO / BRANCH / PR
  yduchesne/quervant / dev/perf06-c2 / #131 OPEN UNMERGED; draft=<fresh observed boolean>

MAIN_BASE / F1_START / A1_START / A1_TESTED / A1_FINAL / REMOTE_VERIFIED
  exact immutable values, with source-equivalence proof and last checked range

PLAN_HASHES
  Original F1 SHA-256 = b9d11e958af2186e9a5f358153cee489a4cdafc9913ed7ea7bb6b494b091d5e7
  A1 amendment SHA-256 = actual value

DISPOSITION / G0..G10
  actual status per gate; G10 OPEN; G7 exception or blocker explicit

ACCEPTANCE
  U17: five B3 rows + native score-fault row + full-response parity
  U21: 86/87/99/100 + three full-response recoveries
  U12: exact nine completed IDs, no blocked/omitted rows
  P05: retained six resource rows and same-budget recovery
  I08: exact errors/cancellation and complete retry-response parity

INVENTORY / LOCAL QA / COVERAGE / ORDINARY CI
  actual final values, commands, source revisions and linked receipts

FAILURES / DECISIONS / EXCEPTIONS
  all retained attempts; exact committed-range whitespace diagnostics;
  explicit human exception reference if any; no inferred waiver

STATE
  protected paths unchanged; PR unmerged, observed readiness recorded and preserved; C3/C4 unstarted;
  no benchmark/performance claim; precise remaining maintainer action
```

Do not ask for approval at routine checkpoints. If the only remaining dependency is the explicitly human-owned whitespace decision, deliver all completed independent work and the concrete diagnostic-scoped request, explaining that AGENTS and original F1 D29 require that human disposition. Do not end with an invitation to redesign tests or keep prescribed cases permanently unexecuted.

## Appendix A. Proposed frozen-artifact whitespace exception scope

**Status: PROPOSED ONLY — explicit human approval is required.** This table is a reviewable boundary for the maintainer decision in section 10. It grants no exception by itself.

Reviewed head: `2bf9539cd2f53838ad1aca406ca4e67a34229ff6`; comparison base: `bc726420cede2e26681d6e8192b45a5d0169abbf`. Each path below is relative to `docs/pr-artifacts/perf-06-c/`. Git blob IDs freeze complete artifact bytes; line numbers refer to those exact blobs. “Trailing” denotes Git's trailing-whitespace diagnostic; “EOF” denotes new blank line at EOF. There are 55 diagnostics across 40 artifacts.

The proposed approval, if the maintainer chooses it, is: accept only these listed whitespace diagnostics for these unchanged historical artifact blobs, preserve their bytes and the raw failed-check results, and continue to reject every unapproved diagnostic elsewhere. A current range check and exact blob equality are prerequisites to applying an approval. This does not waive any source, test, coverage, CI, evidence-accuracy or independent-review requirement.

| Artifact | Cohort | Actual diagnostics | Git blob |
|---|---|---|---|
| `PERF06C2F1_DETAILED_FIXUP_PLAN.md` | F1 | 3 trailing, 4 trailing, 5 trailing, 6 trailing, 7 trailing, 8 trailing, 9 trailing, 378 trailing, 853 trailing, 854 trailing, 1005 EOF | `5852dcf8952b9114f7e078c57b73075f977810e7` |
| `PERF06C2_DETAILED_PLAN.md` | original C2 | 3 trailing, 4 trailing, 5 trailing, 6 trailing | `b6f44a92a441305fa98993657a1688150c3e03e1` |
| `evidence/c2-coverage-all-features.txt` | original C2 | 11 EOF | `7e7bf4fc677874207223b3500ecb18f1a73d8fd6` |
| `evidence/c2-coverage.txt` | original C2 | 11 EOF | `4a0747e95a1cdc3f8e10bddd459f016b3c2ccb0e` |
| `evidence/c2-f1-baseline-integration.txt` | F1 | 16 EOF | `610ad72fadea70b12f66e8e629c052ce62198d92` |
| `evidence/c2-f1-baseline-physical.txt` | F1 | 12 EOF | `eb52df0bd9a644859fac638f9d79c66b49f2804c` |
| `evidence/c2-f1-baseline-unified.txt` | F1 | 30 EOF | `9c77c1e0f987c0ede769028122daeaffa756208f` |
| `evidence/c2-f1-i08-attempt-01.txt` | F1 | 8 EOF | `b27ba3ac34f7fe1fcce4ca581bbf731a262b7493` |
| `evidence/c2-f1-i08-attempt-02.txt` | F1 | 9 EOF | `e5ee7b573cac456f0e08d41f57492cd2e69a3c09` |
| `evidence/c2-f1-integration.txt` | F1 | 16 EOF | `05d3aad261b4affdc979c8cf3de11a0228f826fc` |
| `evidence/c2-f1-p05-attempt-01.txt` | F1 | 42 EOF | `6d985f6e1b8b035c67e80d7a3918f21a3325d257` |
| `evidence/c2-f1-p05-attempt-02.txt` | F1 | 14 EOF | `c68e1a83dc52a72665e038003b066dcce6a8f6b9` |
| `evidence/c2-f1-physical-parallel.txt` | F1 | 12 EOF | `7fe53722b331f4b8cda23353cd08c89f4a6b472e` |
| `evidence/c2-f1-physical-serial.txt` | F1 | 12 EOF | `0cef1307cf7aa829688ac30ab9446bce893c063c` |
| `evidence/c2-f1-regression-15h-a.txt` | F1 | 14 EOF | `39e20d1c28cbcaacdc911ec84b252ac9db10c990` |
| `evidence/c2-f1-regression-15h-a2.txt` | F1 | 16 EOF | `6a200df084e452526e6b5314f3e67bf27ec617d5` |
| `evidence/c2-f1-regression-b1-ordinals.txt` | F1 | 31 EOF | `814ea60dcccb5a0c7c5905f0166b6824b6118560` |
| `evidence/c2-f1-regression-b1-unit.txt` | F1 | 100 EOF | `4adabcfa7854df453d4790f45e93fbe13721b32b` |
| `evidence/c2-f1-regression-b2-ordinals.txt` | F1 | 16 EOF | `245ad7bd91bc73dc01430f360973cb399f7db7f7` |
| `evidence/c2-f1-regression-b2-unit.txt` | F1 | 66 EOF | `79d25512ca224a756f9a5bf6f620265e445fd493` |
| `evidence/c2-f1-regression-b3-keys.txt` | F1 | 16 EOF | `73b789710506ae6ec145a8a219d12bacd0537cdc` |
| `evidence/c2-f1-regression-b3-unit.txt` | F1 | 64 EOF | `626305dbafb0437eba35ef526397881379e8f56a` |
| `evidence/c2-f1-u12-attempt-01.txt` | F1 | 42 EOF | `8a2135f8795d57991aa73efb2606aa7c531884d0` |
| `evidence/c2-f1-u12-attempt-02.txt` | F1 | 14 EOF | `6ae93996129c05c73a880ec49b90ffce5f68897a` |
| `evidence/c2-f1-u17-attempt-01.txt` | F1 | 41 EOF | `05523fbb75edfc1ec6b8aba8ea04ec87ac2007e0` |
| `evidence/c2-f1-u17-attempt-02.txt` | F1 | 14 EOF | `09e2d8c388fc3a25624c188fdd6272c4a10a290e` |
| `evidence/c2-f1-u21-attempt-01.txt` | F1 | 36 EOF | `f0b8a58deeea22e270b96559b3b7038eec54983f` |
| `evidence/c2-f1-unified-parallel.txt` | F1 | 31 EOF | `5b44d04fa057c422bbdc50b04e8b36b6043f1106` |
| `evidence/c2-f1-unified-serial.txt` | F1 | 31 EOF | `376c0d1864f545face6ac4803540ba0b6d377c06` |
| `evidence/c2-integration.txt` | original C2 | 16 EOF | `d4554464f9ee0dc051bb3cded24b491b205d3a73` |
| `evidence/c2-regression-15h-a.txt` | original C2 | 13 EOF | `5eb35d63791af2007e05c3486cf7aff6c58c71bc` |
| `evidence/c2-regression-15h-a2.txt` | original C2 | 15 EOF | `2056815f513429b5cc0efdffa529c6862b18e721` |
| `evidence/c2-regression-b1-ordinals.txt` | original C2 | 7 trailing, 16 trailing, 30 EOF | `72ac7ab7ce3bfcf293697b241124cf08b1f9895f` |
| `evidence/c2-regression-b1-unit.txt` | original C2 | 72 EOF | `2049a5da7ce5b63800723d52e45729472bd5ec15` |
| `evidence/c2-regression-b2-ordinals.txt` | original C2 | 15 EOF | `8c96634b20af4fc2faab7cdb1a9a2293922cdfd0` |
| `evidence/c2-regression-b2-unit.txt` | original C2 | 38 EOF | `d5b08836d2c549ac340c0b6940ab645c5c00ea61` |
| `evidence/c2-regression-b3-keys.txt` | original C2 | 15 EOF | `10f987566e41ccf82bed394ccd029f4f3b6dc691` |
| `evidence/c2-regression-b3-unit.txt` | original C2 | 36 EOF | `6f930e6fdead63ef38a6072ccf3fa7ee521085b9` |
| `evidence/c2-unit-c2-parallel.txt` | original C2 | 45 EOF | `025af9004a402d1e995f70873f7b5e5b0bddaccd` |
| `evidence/c2-unit-c2-serial.txt` | original C2 | 45 EOF | `a756d55e3c62b05e23558c103bbb24752f1ebcd9` |

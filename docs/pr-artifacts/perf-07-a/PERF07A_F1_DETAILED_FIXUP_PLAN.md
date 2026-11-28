# PERF-07-A-F1 — Correctness acceptance and evidence closeout for PR #135

**Document type:** Detailed fixup execution contract; not an execution report.
**Repository:** `yduchesne/quervant`
**Existing PR:** #135, `PERF-07-A: selective multi-hit physical key verification`
**Actual branch:** `dev/perf-07-a` (hyphens are significant)
**Authoring inspection:** 2026-11-27 Pacific / 2026-11-28 UTC.
**Authority:** the reviewed PERF-07-A design, `AGENTS.md`, `docs/TESTING.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` §§3A–3F, 27, 37–38 and the review findings below.

## 0. Execution contract and non-goals

**Continuous execution authorization:** Execute this approved plan from its authorized starting point through all remaining prescribed work without asking for routine reconfirmation. Continue automatically after successful preflight, stage completion, permitted AUTO-RESOLVE decisions, and ordinary verification checkpoints. Stop affected work only for an explicitly applicable HARD STOP, a genuinely missing human decision, or an essential external dependency that prevents that work. When the obstacle is isolated, record its scope and continue every independent, safe, authorized task. Do not reinterpret an informational checkpoint as a request for approval.

The independent review identified no production-code defect. F1 strengthens or corrects five existing test functions and corrects evidence and documentation. **Do not design, refactor, or modify production code.** If a strengthened assertion exposes a production defect, preserve its output, identify the exact failing invariant and stop the affected work; request a separately designed amendment. A green previous CI run does not justify weakening a new assertion.

Work on the existing PR, not a new branch or PR. Preserve its current ready/draft setting (`isDraft=false` at authoring). Do not merge, change branch protection, force-push, dispatch extra CI, or promote a performance baseline. Do not start PERF-07-B or any later stage. No timing acquisition, profiling, new benchmark, cross-engine campaign, or speedup claim. Ordinary Cargo all-targets test-mode harnesses and `bench --no-run` are permitted correctness/build checks only. The host is assumed usable; no performance-readiness or host-stability gate is authorized.

The original plan remains immutable and authoritative except for the narrow acceptance/evidence amendments explicitly stated here. Follow its mandatory local QA, real RustFS and scope rules. Do not create another implementation plan or another evidence framework. F1 is test-bearing and therefore requires final local QA, coverage, and hosted CI on the corrected revision. G7 remains independent reviewer/maintainer-owned.

## 1. Pinned source, admission, and existing accepted work

At authoring, fresh `main` and live PR #135 were read from GitHub. The PR is open, unmerged, mergeable, not draft; no branch movement was observed. These are source identities, not a claim about the state when execution begins.

| Identity | Exact value |
|---|---|
| BASE / current `origin/main` | `c9ca7975ab6f29fc4fe1fac65951cede3799cb8c` |
| BASE tree | `0ead7efb356d66751c801b12a27147e281ae2a5e` |
| Original RED commit | `06898baf9a796cddf5a03033652df4d2a53e150a` |
| RED tree | `9ca4f8ed5cf311dbca24f9e50848c24e69c74a5a` |
| Original TESTED | `29fe4a2d596b3df43cd29f18722983098d664a47` |
| Original TESTED tree | `5828846d3dfcc3a4742848099c873e185fb9a7aa` |
| F1_START / reviewed PR head | `f7437954c87e070ffc5df15bbc4d80c826ace3e7` |
| F1_START tree | `aecc07cc6a1bbd6de7b73a557f2a86b9297feeee` |
| Prior CI run | `46102649763`, all five jobs succeeded, `pull_request` |
| Prior CI tested merge ref | `7b9da4e1387dba22200f009eaff7d632aa28ad92` |
| Prior real RustFS job | `140848349411` (GB-R01 and RF01 actual bodies passed) |

The original plan is `docs/pr-artifacts/perf-07-a/PERF07A_DETAILED_IMPLEMENTATION_PLAN.md`, SHA-256 `5a66c42cb00ed8fde2118ef3e55145603b44a4a3ca13de9a6a1f65b0670ed7b1`, Git blob `bac21b375bb93deb34cccb29423369125cae46e9`. Read the full plan, especially §§3, 6, 7, 8, 9, 11 and 12, before editing. Use the actual branch above, not the original plan's `dev/perf07-a` spelling.

### 1.1 Start commands

From the existing local repository root, before any edit:

```bash
git status --porcelain=v1 --untracked-files=all
git fetch origin main dev/perf-07-a
gh pr view 135 --repo yduchesne/quervant --json state,mergedAt,headRefName,headRefOid,baseRefName,isDraft,url,body
git rev-parse origin/main origin/dev/perf-07-a
git ls-remote --heads origin dev/perf-07-a
```

Require PR #135 OPEN and unmerged, base `main`, head branch `dev/perf-07-a`, remote/PR head F1_START, and `origin/main` exactly BASE. If main or remote head moved, or PR closed/merged, apply F02, not an automatic rebase. Verify local branch is already F1_START or is a clean ancestor of it; `git switch dev/perf-07-a` and `git merge --ff-only origin/dev/perf-07-a` when permitted by F01. If local branch is absent, create tracking branch with `git switch --track origin/dev/perf-07-a`. Never discard local work. If dirty tracked files, local divergence, or overlapping untracked input exists, stop. Leave disjoint pre-existing untracked files intact (the original run reported `docs/pr-artifacts/perf-06-b/evidence/f2-ci-status.txt`). Record all pre-existing untracked paths; do not stage them. In particular preserve `target/perf07-a-evidence/` if present; it contains historical logs.

```bash
BASE=c9ca7975ab6f29fc4fe1fac65951cede3799cb8c
RED=06898baf9a796cddf5a03033652df4d2a53e150a
A_TESTED=29fe4a2d596b3df43cd29f18722983098d664a47
F1_START=f7437954c87e070ffc5df15bbc4d80c826ace3e7
BRANCH=dev/perf-07-a
A_DIR=docs/pr-artifacts/perf-07-a
READER=crates/quervant-core/src/segment/reader.rs
UNIFIED=crates/quervant-core/src/search/unified.rs
FS_TEST=crates/quervant-core/tests/perf06_c2_physical.rs
RF_TEST=crates/quervant-core/tests/pr15g_b_rustfs.rs
```

Require exact trees above, `BASE` ancestor of RED, RED ancestor of A_TESTED, A_TESTED ancestor of F1_START. Verify `git diff --name-only "$BASE..$A_TESTED"` is exactly the four executable paths `$READER`, `$UNIFIED`, `$FS_TEST`, `$RF_TEST`, and `git diff --name-only "$A_TESTED..$F1_START"` is docs-only. Verify the original plan hash and historical selected evidence with `(cd "$A_DIR/evidence" && sha256sum -c SHA256SUMS)` (18 entries). An altered or missing committed artifact is F03, not a license to repair historical evidence.

| F1_START source anchor | Git blob |
|---|---|
| `crates/quervant-core/src/segment/reader.rs` | `a4c16170ebf2402707a1e75598899698f948c140` |
| `crates/quervant-core/src/search/unified.rs` | `4fd2f2aef8aa606db6571a14f3238a02f28a931e` |
| `crates/quervant-core/tests/perf06_c2_physical.rs` | `1b51044349e0457cdd55b68c3f15172c2ea1bada` |
| `crates/quervant-core/tests/pr15g_b_rustfs.rs` | `a364e2a129a8bec3718f2e1fbcf2ed4f77510d72` |
| `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` | `c871d370dc050fad9457bfa81a8421dbb846fbf2` |
| `AGENTS.md` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` |
| `docs/TESTING.md` | `91c8643eaa041b0cb475949bcefa7c074ae27fe3` |

Verify each using `git rev-parse "$F1_START:<path>"`; verify source blobs also equal A_TESTED. Do not edit the guide, AGENTS, original plan, or unrelated existing documentation defects.

### 1.2 Reconciliation and traceability

| Capability / review finding | At F1_START | F1 delta / acceptance |
|---|---|---|
| Arbitrary-K production verifier, shared offset ownership, scanner, error routing, STORED and ledger integration | DONE; independently source-reviewed; prior QA/CI green | Freeze production bytes; F1 only tests the existing implementation. |
| R05 post-scan refusal | PARTIAL proof: repeats mismatching expectation instead of recovering | F1-T1: four calls, corrected expected keys after refusal. A-I03/A-I05. |
| R07 singleton boundary | PARTIAL proof: admitted large invalid ID accepts two errors | F1-T2: exclusive typed error and exact counters/state. A-I04/A-I05. |
| U02 row evidence | DONE behavior; incorrect marker | F1-T3: five counted completed calls. A-I02/A-I03/A-I06. |
| U03 projector errors and recovery | PARTIAL proof: negative cases only zero cap; recovery on another snapshot/new ledger | F1-T4: 19 calls, two routes, eight exact failures plus eight same-ledger recoveries. A-I01/A-I04/A-I06/A-I07. |
| RF01 | DONE actual local + hosted real-service execution; PARTIAL complete response parity proof | F1-T5: four complete cold/warm response pairs plus original 440 per-hit assertions, provider request stability. A-I06/A-I07. |
| Original RED evidence attribution | PARTIAL provenance; actual expected failure observed in precommit worktree | F1-E1: historical erratum, one explicitly new immutable RED replay (not replacement for original receipt). G1. |
| Original local test count, prior readiness and roadmap branch spelling | Reporting discrepancies | F1-E2: historical count recovery/qualification; current count and state separately; branch spelling correction. G5. |
| All other R/U tests, I01/I02 and prior tests, performance/benchmark policies | DONE and previously verified | Preserve exact source; rerun prescribed regression/QA on F1_TESTED. |

### 1.3 Correctness worksheet before modification

Record this fixed challenge-to-oracle mapping in F1 report. Confirm each source premise against the pinned functions; discrepancies follow F03/F04. Do not ask for routine approval.

| Plausible bad implementation | Required detecting evidence |
|---|---|
| Caches comparison false when optional offset directory refuses | R05 mismatch false, corrected request true on same sticky-None owner; exact counts, no new retained charge. |
| Scans malformed final key for invalid large singleton before returning range error | R07 N=1024 invalid ID exclusively range, zero valid scan rows, no offset init; N=1023 still UTF-8 error. |
| Sorts by physical ID before deciding mismatch versus range | U03 both permutations, literal first-failure types on both routes. |
| Deduplicates selected expected keys by physical ID and skips conflicting later occurrence | U03 wrong-later fails after three prepared reads; correct duplicate positions retained in output. |
| Skips physical parity on prepared route, or admits STORED/projection output before parity | U03 ready-state failures, zero STORED calls, zero ledger, guard released. |
| Reuses poisoned request-local state or leaves projection ledger charged after failure | U03 recovery immediately on same snapshot and same ledger instance, full literal fields and route counts. |
| Warm remote result has different cursor/generation/view despite matching key order | RF01 compares complete `UnifiedResponse` for same request on same snapshot, plus individual literal checks and unchanged provider requests. |
| Claims a test count or immutable revision unsupported by raw receipt | Per-row completion increment after assertions, immutable replay and preserved historical timestamps, actual command records. |

There is no new public interface, durable state machine, I/O protocol, memory budget, algorithm, dependency, or wire format. Existing error, concurrency, cancellation, allocation, metadata publication and PIT invariants remain the accepted PERF-07-A contract; all applicable original regression suites run. Real RustFS is required, not an ObjectStore fake. No new property/fuzz dependency or test infrastructure; the known failure permutations are finite and deterministic.

## 2. Exact write scope and protection

Only these existing **function bodies** may change in executable files. Keep attributes, names, enclosing modules, helpers, preexisting test functions, and all production code unchanged.

| Path | Function(s) allowed to change |
|---|---|
| `$READER`, `column_geometry_tests` | `perf07a_r05_post_scan_finalize_refusal_no_rescan`, `perf07a_r07_selection_order_and_singleton_boundary` |
| `$UNIFIED`, `c2_tests` | `perf07a_u02_projection_first_use_and_zero_metadata`, `perf07a_u03_projection_selected_order_and_parity` |
| `$RF_TEST` | `perf07a_rf01_real_rustfs_multi_hit_cold_and_warm_projection` |

There are **five** existing registrations whose bodies may change (R05, R07, U02, U03, RF01); four substantive acceptance/counter fixes plus RF01 parity. No new registrations. No changes to `$FS_TEST`, `perf07a_observation`, `test_observation`, `SegmentReader::verify_selected_doc_keys`, `scan_selected_key_parity`, `project_selected_hits`, `ProjectionLedger`, `build_validated_offsets`, shared metadata/certificate owners, public `UnifiedResponse`, or any non-test implementation. Existing GB-R01 must remain byte-identical. Do not edit compiler flags, test ignore attributes, budgets, fixture input data, `.github/`, Cargo manifests/lockfiles, benchmark harness, configurations/results, or other prior tests. The original red replay runs unchanged historical code only in an isolated detached worktree.

Permitted docs after immutable F1_TESTED: new `$A_DIR/PERF07A_F1_DETAILED_FIXUP_PLAN.md` (verbatim this file), `$A_DIR/PERF07A_F1_EXECUTION_REPORT.md`, new `$A_DIR/evidence/f1/` receipts, append-only erratum to `$A_DIR/PERF07A_EXECUTION_REPORT.md`, exact one-token correction plus dated status addendum in `docs/PERF_OPTIMIZATION_ROADMAP.md`. No other doc edits necessary. The original architecture paragraph is historical and unchanged; F1 does not change architecture. All original `$A_DIR/evidence/` files and their `SHA256SUMS` stay byte-identical. No historical receipt replacement, sanitization, or hash update.

## 3. F1-T1: R05 — prove correct recovery on the same unavailable owner

**Source:** reader.rs at F1_START, R05 near lines 5042–5124. Original plan §6.1 R05. Retain both N=4 states and initial injection exactly. Existing `selection = [(3,k3),(0,k0),(3,k3)]`; `wrong` changes only first expected key to k1. The actual test-only `FinalizeRefusal` makes `MetadataMeter::finalize` refuse measured capacity after one complete scan. No new injection or counter.

1. Keep the original `for (label, rows, expected_parity)` two-case table. Before each injected call assert `state.key_offsets_state()==None`, `state.key_offsets_ptr()==None`, and no populated query-local key cache. Record `before` as existing access-budget balance. Arm once around `verify`; drop guard immediately after call. Assert existing true/false expected parity, complete `Counts` literal with `scans:1, scan_rows:4, selection_rows:3, ..Counts::default()`, `selected_keys_owned()==0`, `Some(false)`, unchanged charge, no cache. Also assert no offset pointer. Increment only after all assertions.
2. Replace the existing retry, which currently uses `rows` and `expected_parity`, with this design (retain existing local `Counts` and helpers):

```rust
let retry = SegmentReader::from_shared(Arc::clone(&state));
assert_eq!(perf07a_observation::directory_fault(), DirectoryFault::None);
assert_eq!(state.key_offsets_state(), Some(false));
assert!(state.key_offsets_ptr().is_none());
reset_perf07a();
let again = verify(&retry, &selection).expect("sticky correct recovery");
assert!(again, "{label}: corrected request must succeed on the same owner");
assert_counts(
    perf07a_observation::counts(),
    Counts { scans: 1, scan_rows: 4, selection_rows: 3, ..Counts::default() },
    &format!("{label} sticky correct recovery"),
);
assert_eq!(test_observation::selected_keys_owned(), 0);
assert_eq!(state.key_offsets_state(), Some(false), "{label}: still none");
assert!(state.key_offsets_ptr().is_none());
assert_eq!(state.access_budget_used(), Some(before));
assert!(!retry.doc_keys_cache_is_populated());
rows_done += 1;
```

3. Preserve existing `drop(reader); drop(retry); drop(state);`; before dropping budget assert `budget.used()==0`. Keep the existing final `rows_done==4` check, and use a truthful per-case log marker after completed assertions:
   `PERF07-A F1 R05 case={label} injected_parity={expected_parity} corrected_parity=true scan_rows=4/4 sticky_none=true rows=2`.
   Preserve the existing `INJECTED_POST_SCAN_MEASUREMENT` marker; do not label this a real allocator-capacity incident.

| Case | Injected call | Correct retry (unarmed) | Both observations |
|---|---|---|---|
| match | true | true | scan1/4, scratch3, all other counters and owned count zero, no pointer, sticky None, no budget delta |
| mismatch | false | true | same |

The retry must use the literal correct selection even in the mismatch case, not a rebuilt state, new budget, or temporarily cleared cell. Total remains four verification calls. R02/R03/R04/R06/R07/R08/R09 remain unchanged except R07 below.

## 4. F1-T2: R07 — exclusive singleton error ordering

**Source:** reader.rs R07 near lines 5360–5585. Original plan §6.1 R07 35 calls. Preserve S0–S7 table (24 calls), native fixture, corrupt-last-key construction, empty segment checks and corrupt empty-selection control. Do not change expected counts on S0–S7 or rename the test.

Replace only the boundary loop body (the loop starting `for size in [1023usize, 1024]` and ending immediately before `// Real empty segment`). Retain existing boundary bytes and exact corruption offset `10 + (size - 1) * 8 + 2`. The size is encoded count, not top-K. Ensure pristine/corrupt container opens, and assert actual `doc_count()==size as u64`. Keep key length/bytes fixed; no alternate malformed fixture.

For each size, execute `invalid-id` selection `[(size as u64, DocumentKey::new("k00000")...)]`, then `late-corrupt` selection `[(0, DocumentKey::new("k00001")...)]`; each on a fresh unmetered and a fresh admitted-empty wrapper, in that order. Use existing `headroom_state` and `SegmentReader::open`. Before reset assert cell None and cache empty. Record admitted budget before. Compute **only** these literal expectations:

| size | selection | required outcome | scans | scan_rows | selection_rows | admitted cell after | unmetered cell after |
|---:|---|---|---:|---:|---:|---|---|
| 1023 | invalid-id | `InvalidUtf8 { context: "doc key" }` | 1 | 1022 | 0 | None | None |
| 1023 | late-corrupt | same UTF-8 error | 1 | 1022 | 1 | Some(false) | None |
| 1024 | invalid-id | `Corrupt { context: "doc keys", detail: "doc id out of range" }` | 1 | 0 | 0 | None | None |
| 1024 | late-corrupt | `InvalidUtf8 { context: "doc key" }` | 1 | 1023 | 1 | Some(false) | None |

All unspecified `Counts` fields zero, `selected_keys_owned()==0`, no populated full cache, no offset pointer; admitted metadata unchanged. For valid expected-key mismatch the cell becomes `Some(false)` because real semantic validation failed during admitted initialization; no valid directory published. The unmetered state does not initialize the cell.

Use a local closure in R07 (not a new helper outside the allowed function) or inline the following common assertion in the two paths. The exclusive branch is mandatory:

```rust
let early = size == 1024 && case == "invalid-id";
if early {
    check_typed(outcome, P07aExpect::Range, "large invalid before body rows");
} else {
    match outcome {
        Err(SegmentError::InvalidUtf8 { context }) => assert_eq!(context, "doc key"),
        other => panic!("N={size} {case}: expected InvalidUtf8, got {other:?}"),
    }
}
let expected = Counts {
    scans: 1,
    scan_rows: if early { 0 } else { size - 1 },
    selection_rows: usize::from(case == "late-corrupt"),
    ..Counts::default()
};
assert_counts(perf07a_observation::counts(), expected, case);
assert_eq!(test_observation::selected_keys_owned(), 0);
```

Use the exact cell expectations in the table for admitted/unmetered respectively. Check `access_budget_used()==Some(before)` on admitted path before dropping owners, and `budget.used()==0` after dropping the wrapper and state. For unmetered require `!has_access_budget()`, and no pointer/cell/cache. Reset observations immediately before each actual verification. Increment `calls` only after every row assertion; emit a stable marker for each of eight calls, including N, case, mode, exact outcome label, scans, scan_rows, selection_rows and cell state. The final `PERF07-A R07 rows=35` remains derived from the counter. Do not allow `InvalidUtf8` for the large invalid-ID case on either route or allow range for the three other combinations. Never turn a mismatch into a permitted alternate error. This is a regression test of the already implemented historical asymmetry; do not alter production precedence.

## 5. F1-T3: U02 — count the actual five projector calls

**Source:** unified.rs U02 lines 18556–18647 approximately. Original plan §7 U02. Keep the exact N=1100 fixture, `[1099,2,0,2]`, admitted and zero cap snapshots, all count/field/guard/metadata assertions. Add `let mut completed = 0usize;` before first call. Increment once after each fully asserted call (first use, warm use, zero-a, zero-b, empty). Add `assert_eq!(completed, 5, "five completed projector calls");` and replace hardcoded `rows=6` with `eprintln!("PERF07-A U02 rows={completed}");`. Log stable completed-row labels, not merely an iteration count. No sixth case, no synthetic invocation. Preserve all previous successful case assertions. This fixes a reporting error rather than missing functionality.

## 6. F1-T4: U03 — exact two-route negative and recovery matrix

**Source:** unified.rs `perf07a_u03_projection_selected_order_and_parity`, currently lines 18649–18761. Original plan §7 U03. Reuse all helpers `Fixture`, `document`, `p07a_pristine_key_map`, `bounded_key`, `p07a_copied`, `p07a_snapshot`, `p07a_plan`, `p07a_hit`, `p07a_reset`, `p07a_counts`, `p07a_owned`, `p07a_check_fields`. Production entry is `super::project_selected_hits`, not reader-only verifier or public collection. `p07a_snapshot` constructs real reader states over checksum-valid bytes with 256 MiB reader-copy cap; metadata cap is 0 or 256 MiB. Do not replace it.

### 6.1 Setup and controls

Retain original fixture setup through `let success_inputs = [3usize, 0, 3, 1];`. Add explicit source/input premises: one fixture segment, `copied.doc_count==4`, key-map key set equal to `(0..4).map(bounded_key).collect::<BTreeSet<String>>()`, distinct physical IDs equal to 0..4. Do not assume native order; existing `id(index)` resolves actual physical ID. Prepare admitted offsets exactly as existing code does via `doc_key_selected(0)` on separate guard before observations. Require Some(true), pointer present, and drop guard. On the zero-cap snapshot, metadata remains zero. Assert both active reader-copy balances zero before the first call. Do not populate a full local key cache in the measured path.

Preserve three positive controls: one unmetered and two prepared calls with the exact success vector `[hit(id(3),3),hit(id(0),0),hit(id(3),3),hit(id(1),1)]`. Each success asserts complete literal two-field projection in selected order, including repeated position. Use a fresh generous `ProjectionLedger::new(1 << 20)` for each independent success control. Define a local success assertion closure, used for both controls and failure recovery, taking the actual snapshot, `&mut ProjectionLedger`, route flag and label. The following is the prescribed implementation of that closure:

```rust
let assert_success = |snapshot: &ReaderSnapshot,
                      ledger: &mut ProjectionLedger,
                      prepared: bool,
                      label: &str| {
    assert_eq!(ledger.used(), 0, "{label}: initially empty ledger");
    assert_eq!(snapshot.reader_copy_used(), 0, "{label}: no active reader");
    p07a_reset();
    let out = super::project_selected_hits(snapshot, &plan, ledger, &success, None)
        .unwrap_or_else(|error| panic!("{label}: {error:?}"));
    let expected = if prepared {
        P07aCounts { offset_reads: 4, stored_calls: 1, ..P07aCounts::default() }
    } else {
        P07aCounts { scans: 1, scan_rows: 4, selection_rows: 4,
                     stored_calls: 1, ..P07aCounts::default() }
    };
    assert_eq!(p07a_counts(), expected, "{label}: exact counts");
    assert_eq!(p07a_owned(), if prepared { 4 } else { 0 }, "{label}: owned");
    p07a_check_fields(&out, &success_inputs, label);
    assert!(ledger.used() > 0, "{label}: successful projection charged");
    assert_eq!(snapshot.reader_copy_used(), 0, "{label}: guard released");
    if !prepared {
        assert_eq!(snapshot.metadata_used(), 0, "{label}: zero metadata");
    }
    eprintln!("PERF07-A F1 U03 label={label} outcome=success counts={:?} owned={} ledger_used={} reader_bytes={}",
              p07a_counts(), p07a_owned(), ledger.used(), snapshot.reader_copy_used());
};
```

The full-field success check plus positive ledger use is the intended recovery witness here; U06's exact 33/65/66-byte ledger boundary contract remains unchanged and is rerun. No need to create a new budget formula or ledger reset API. `assert_success` must not instantiate a ledger or replace the passed reference. Keep it scoped within this test. For control invocations use the labels `unmetered-success`, `prepared-success-a`, `prepared-success-b`, then initialize/advance actual `completed` after each assertion; do not set it to a claimed magic number after a loop.

### 6.2 Negative inputs and exact expected counters

Keep the original four malformed selection vectors, using `id(index)` for genuine physical IDs. Invalid physical ID is literally 4 (`N`), not a logical key or `u64::MAX`. For each vector execute the real projector once on each route, with a new empty ledger for that **failure/recovery pair**. Reuse the two test snapshots; do not reconstruct either after an error. The prepared state has already been prepared and exercised by the controls; `metadata_used` is stable across negative calls. Exactly these rows, in the fixed route-outer order specified below (all four unmetered pairs, then all four prepared pairs):

| Case | Input `(physical-id, logical-key-index)` in order | Error | Unmetered selection_rows | Prepared offset_reads / owned |
|---|---|---|---:|---:|
| wrong-first | `(id(3),1), (id(0),0), (id(3),3)` | mismatch | 3 | 1 |
| wrong-later | `(id(3),3), (id(0),0), (id(3),2)` | mismatch | 3 | 3 |
| mismatch-then-invalid | `(id(0),1), (4,0)` | mismatch | 1 | 1 |
| invalid-then-mismatch | `(4,0), (id(0),1)` | range | 1 | 0 |

For every unmetered failure `scans=1, scan_rows=4, selection_rows` as table; offset_reads, cache_compares, full_decodes, full_owned, stored_calls and owned all zero. For every prepared failure `offset_reads` as table, `owned==offset_reads`, **all other fields zero**. This includes zero STORED calls. A mismatch is exactly `SearchError::CorruptIndex { detail: "selected hit key does not match its physical document" }`. Range is exactly `SearchError::Segment(SegmentError::Corrupt { context: "doc keys", detail: "doc id out of range" })`. Do not substitute substring, generic is_err, or an enum permitting both. Before/after failure reader_copy_used zero, ledger.used zero; zero metadata stays zero, prepared metadata balance unchanged. No full keys or full decode in either path. Never require owned=0 for all prepared failures: direct reads of successfully decoded mismatching keys are real expected temporary ownership.

### 6.3 Prescribed loop and immediate recovery

Replace the old `failed` table, `rows=2`, loop restricted to unmetered, and final separate `recovery` block with the following. The closure above replaces the old success blocks with equivalent assertions; initialize the completed counter before controls and increment after each. Use `type FailedRow = (&'static str, Vec<SelectedHit>, bool, usize, usize);` if needed to avoid `type_complexity` (allowed local-only alias). Keep exact table rows and fixed mode-outer loop below. Reuse existing imports and types; rustfmt may reflow this code only.

```rust
let mut completed = 0usize;
for (label, snapshot, prepared) in [
    ("unmetered-success", &unmetered, false),
    ("prepared-success-a", &admitted, true),
    ("prepared-success-b", &admitted, true),
] {
    let mut ledger = ProjectionLedger::new(1 << 20);
    assert_success(snapshot, &mut ledger, prepared, label);
    completed += 1;
}

type FailedRow = (&'static str, Vec<SelectedHit>, bool, usize, usize);
let failed: Vec<FailedRow> = vec![
    ("wrong-first", vec![hit(id(3), 1), hit(id(0), 0), hit(id(3), 3)], false, 3, 1),
    ("wrong-later", vec![hit(id(3), 3), hit(id(0), 0), hit(id(3), 2)], false, 3, 3),
    ("mismatch-then-invalid", vec![hit(id(0), 1), hit(4, 0)], false, 1, 1),
    ("invalid-then-mismatch", vec![hit(4, 0), hit(id(0), 1)], true, 1, 0),
];
let mut failures = 0usize;
let mut recoveries = 0usize;
for (mode, snapshot, prepared) in [
    ("unmetered", &unmetered, false),
    ("prepared", &admitted, true),
] {
    for (case, hits, range, scratch, reads) in &failed {
        let label = format!("{mode}-{case}");
        let mut ledger = ProjectionLedger::new(1 << 20);
        let before = snapshot.metadata_used();
        assert_eq!(ledger.used(), 0);
        assert_eq!(snapshot.reader_copy_used(), 0);
        if !prepared { assert_eq!(before, 0); }
        p07a_reset();
        let error = super::project_selected_hits(snapshot, &plan, &mut ledger, hits, None)
            .expect_err(&label);
        if *range {
            match &error {
                SearchError::Segment(crate::segment::SegmentError::Corrupt { context, detail }) => {
                    assert_eq!(*context, "doc keys", "{label}: range context");
                    assert_eq!(detail, "doc id out of range", "{label}: range detail");
                }
                other => panic!("{label}: expected range, got {other:?}"),
            }
        } else {
            match &error {
                SearchError::CorruptIndex { detail } => assert_eq!(
                    detail, "selected hit key does not match its physical document", "{label}: mismatch detail"
                ),
                other => panic!("{label}: expected mismatch, got {other:?}"),
            }
        }
        let expected = if prepared {
            P07aCounts { offset_reads: *reads, ..P07aCounts::default() }
        } else {
            P07aCounts { scans: 1, scan_rows: 4, selection_rows: *scratch,
                         ..P07aCounts::default() }
        };
        assert_eq!(p07a_counts(), expected, "{label}: complete failure counts");
        assert_eq!(p07a_owned(), if prepared { *reads } else { 0 }, "{label}: owned");
        assert_eq!(ledger.used(), 0, "{label}: zero admission");
        assert_eq!(snapshot.reader_copy_used(), 0, "{label}: guard released");
        assert_eq!(snapshot.metadata_used(), before, "{label}: unchanged metadata");
        eprintln!("PERF07-A F1 U03 label={label} outcome={error:?} counts={:?} owned={} ledger_used=0 reader_bytes=0",
                  p07a_counts(), p07a_owned());
        failures += 1;
        completed += 1;

        // Same reference, same ledger variable, no reset/reassignment of ledger.
        // assert_success resets only test observation counters.
        assert_success(snapshot, &mut ledger, prepared, &format!("{label}-recovery"));
        assert_eq!(snapshot.metadata_used(), before, "{label}: recovery metadata");
        recoveries += 1;
        completed += 1;
    }
}
assert_eq!(failures, 8);
assert_eq!(recoveries, 8);
assert_eq!(completed, 19, "3 positive controls + 8 failures + 8 recoveries");
eprintln!("PERF07-A U03 rows={completed} failures={failures} recoveries={recoveries}");
```

Do not introduce a second `ProjectionLedger` between failure and recovery, reset `used`, clear caches, reprime offsets, or move recovery to another snapshot. No `catch_unwind` around a real projector failure. Each recovery is a real call with correct inputs and checks the duplicate positions. The `completed` count is 19, not 6, 8, or 20; the old standalone recovery is removed because it proves the wrong thing. The three existing successful controls remain. All four failure rows retain independent literal error oracle. No new registration.

## 7. F1-T5: RF01 — complete remote repeated-response equality

**Source:** `pr15g_b_rustfs.rs`, `perf07a_rf01_real_rustfs_multi_hit_cold_and_warm_projection` at F1_START (last function, near lines 274–390). `UnifiedResponse` is already `Debug, Clone, PartialEq` and contains hits, exact total, generation, view ordinal, full next cursor, and aggregation. RF01 already checks literal key/fields/score and provider counter. Preserve all original statements and topology except the specific additions below. No changes to `gb_r01_real_rustfs_cold_bootstrap_selected_access`, shared helpers, data, sort, K, pass order, or remote lifecycle.

1. Immediately after existing `let mut checks = 0usize; let mut provider_baseline = None;`, add:

```rust
let mut cold_responses: Vec<UnifiedResponse> = Vec::with_capacity(4);
let mut requests = 0usize;
let mut parity_pairs = 0usize;
```

2. In each existing nested pass/direction/K iteration, after constructing the response, assert `response.generation == snapshot.generation()` and `response.view_ordinal == snapshot.view_ordinal()`. Keep all literal assertions (including `score.is_none()`, cursor presence, full `title,n,tag`, no aggregation) in both passes. After the existing per-hit loop, before leaving the innermost loop, add exactly:

```rust
let case_index = match direction {
    SortDirection::Asc => 0usize,
    SortDirection::Desc => 2usize,
} + if k == 10 { 0 } else { 1 };
if pass == 0 {
    assert_eq!(cold_responses.len(), case_index);
    cold_responses.push(response);
} else {
    let cold = &cold_responses[case_index];
    assert_eq!(&response, cold, "{direction:?} K={k}: complete cold/warm response parity");
    parity_pairs += 1;
    eprintln!("PERF07-A F1 RF01 pair={case_index} direction={direction:?} K={k} full_response_equal=true");
}
requests += 1;
```

3. After the outer loops require `cold_responses.len()==4`, `requests==8`, `parity_pairs==4`, and the original `checks==440`. Preserve provider baseline captured after all four first-pass requests and exact unchanged provider request count after second pass. Do not replace full-response equality with a keys-only comparison; `PartialEq` includes the full cursor and snapshot identity. `None` scores are separately verified, so float bit parity is not an issue for RF01. Retaining four small test-only responses is deliberate and not a production memory change. Extend final log to include `requests`, `parity_pairs`, and provider before/after counts (capture numeric counts before dropping reopened). Preserve original prefix `PERF07-A RF01 checks=440 segment-docs=1100`.

The first pass is after real cold-cache reopen, not four separate cold reopens. The second pass uses the same snapshot. No measured performance claim or new provider instrumentation.

## 8. F1-E1/E2 — exact historical evidence corrections

### 8.1 RED attribution and one new immutable replay

Original `evidence/commands.tsv` row 7:

- command `cargo +1.98.1 test -p quervant-core --lib perf07a_u01_projection_prepared_offsets_no_full_keys -- --nocapture`;
- recorded HEAD BASE `c9ca7975...`, recorded tree `0ead7efb...`;
- start `2026-11-28T02:28:33Z`, end `2026-11-28T02:28:50Z`, exit **101**;
- later RED commit `06898baf...` created `2026-11-28T02:28:55Z` (five seconds after completion).

Original raw RED log proves one test failed with named U01 full-owned assertion, actual 1100, expected 0, `full_decodes=1`; it is evidence of a precommit worktree run with the observations and test present, not immutable-RED execution. Preserve it and original manifest. Inspect historical scratch `target/perf07-a-evidence/` if present for a **contemporaneous** staged/dirty-tree receipt (not a later reconstruction). If an actual captured full tested-source tree/patch identity is available and matches RED, record what it proves. Otherwise explicitly state: *the exact precommit tested worktree identity was not recorded/available; equivalence to the later RED commit cannot be established retrospectively.* Do not edit original row, rename log, redate commit, infer staged contents from the later commit, or describe HEAD tree as dirty tree.

**One independent immutable replay is prescribed to close the original G1 evidence requirement** (not to repair or replace the historical receipt). This is the only expected failing command in F1. It runs even if contemporaneous proof is found; purpose is direct verifiable evidence of the unchanged original counter-only RED. Use a separate detached Git worktree at exact RED, never checkout/reset the active branch. Before replay inspect `git diff BASE..RED` and require only reader/unified test observations and U01 helpers/test, no production behavior change (two paths were verified at authoring). If unexpected non-test change, F03 STOP. Allocate a unique task-owned directory under `target/perf07-a-f1-evidence/` and use the normal existing Cargo cache; a detached worktree may use `CARGO_TARGET_DIR="$ROOT/target"` for build reuse. Do not overwrite prior receipts, add flags/features, disable test assertions, or mutate RED. Use exact command above from detached worktree, clean tracked tree, record actual RED HEAD and tree before/after. Assert exit 101, exactly one selected test, exactly one failure (0 pass, 1 fail), named `PERF07-A U01 full owned keys (K10-a)` assertion, left 1100/right 0, witnessed full_decodes=1; prior semantic checks reached. Do not accept a build failure, any alternate assertion failure, extra selected test, or successful result. If any unexpected result, F07 STOP and report. Cleanup only the detached worktree owned by F1 via `git worktree remove <path>` (no force); preserve all logs. Do not make new commits on RED. Then continue on unchanged F1_START. Original historical claim remains qualified regardless of replay result. This is correctness-only red proof, not a benchmark or mutation-testing campaign.

### 8.2 Test-count reconciliation and reporting

Original report table says `1234 passed, 0 failed, 1 ignored` for stable default; original TESTED inventory says 1,234 library registrations including one ignored. The reviewed hosted run reported 1,233 passed, zero failed, one ignored for the library harness. These are not workspace-wide counts. Inspect original raw `target/perf07-a-evidence/qa-test-198.log` if present, with original `commands.tsv` entry `qa-test-198` binding to A_TESTED. Extract verbatim top-level `quervant-core` library harness `running ... tests` and final `test result: ...` plus harness launch identity. Do not use a child-process summary, another crate, inventory count, or CI's output as the historical local result. If the original log is absent/ambiguous, explicitly qualify historical local count as unverified; state the known 1,234 inventory and independently observed hosted 1,233/0/1. No rerun of A_TESTED just to recreate historical local evidence. Preserve any recovered original excerpt in F1 evidence, label it historical with original full log SHA if available. Fresh F1 run counts are separately reported on F1_TESTED; expect unchanged library inventory and one ignored test.

Other original reporting corrections: U02 five calls, not six; original U03 actually eight calls (three successes + four failures + one separate success), not six; F1 replaces that insufficient matrix with 19 completed calls, not an assertion that the historical matrix had 19. Original RF01 had 440 literal hit checks and four second-pass results, but not full-response pair assertions; F1 adds four complete response comparisons. Correct original roadmap status spelling from `dev/perf07-a` to `dev/perf-07-a` in the single A implementation-status paragraph, not a global replace or actual branch rename. The original PR body said draft; the live PR is ready at F1_START; report both as time-specific facts. No status change required or authorized.

## 9. Execution sequence, reproducible command evidence, and verification

### 9.1 Recorder and environment

Use the existing original-plan style recorder, not a new harness. Create a new, task-owned scratch directory `target/perf07-a-f1-evidence/` (absolute path `EV`); if it already exists, F05: select exactly `target/perf07-a-f1-evidence-$$` if nonexistent, else STOP. Do not delete or overwrite prior directories. Preserve original A scratch untouched. Set `ROOT=$(git rev-parse --show-toplevel)`, cd root. `set -u -o pipefail`; do not use an unchecked `tee` pipeline. Use standard supported Rust stable 1.98.1 and MSRV 1.85.0. Record tool versions `rustc +1.98.1 --version`, `cargo +1.98.1 --version`, `rustc +1.85.0 --version`, `cargo +1.85.0 --version`, `cargo +1.98.1 llvm-cov --version`, `git --version`, `python3 --version`. Unset inherited `QUERVANT_PR15I_*` experiment overrides and `RUST_TEST_THREADS` (record names only); do not change normal runner concurrency. No arbitrary host modifications. Use the original plan's safe bounded dependency/toolchain setup if needed; F06 if unavailable.

The following recorder is sufficient. Copy into task-owned scratch or execute in the shell. It intentionally records HEAD/tree only for immutable executions; it refuses a dirty tracked tree. For tool/version or admission commands before code changes use the same recorder after branch admission; for source-formatting commands on a dirty tree keep a separate transcript clearly labeled worktree, not immutable receipts. No `set -x` when credentials are set.

```bash
record() {
  local label="$1"; shift
  local log="$EV/$label.log" start end rc sha tree argv after_sha after_tree
  [[ ! -e "$log" ]] || { printf 'duplicate label %s\n' "$label" >&2; return 125; }
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] || return 125
  sha=$(git rev-parse HEAD) || return 125
  tree=$(git rev-parse HEAD^{tree}) || return 125
  start=$(date -u +%FT%TZ) || return 125
  printf -v argv '%q ' "$@"
  "$@" >"$log" 2>&1
  rc=$?
  end=$(date -u +%FT%TZ) || return 125
  after_sha=$(git rev-parse HEAD) || return 125
  after_tree=$(git rev-parse HEAD^{tree}) || return 125
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$label" "$sha" "$tree" "$start" "$end" "$rc" "$after_sha" "$after_tree" "$log" "$argv" \
    >>"$EV/commands.tsv" || return 125
  tail -n 12 "$log"
  [[ "$after_sha" == "$sha" && "$after_tree" == "$tree" ]] || return 125
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] || return 125
  return "$rc"
}
```

Set `EV` absolute and export `CARGO_TARGET_DIR` only in the RED worktree subshell as prescribed; restore original environment for final tests. Check every command's status explicitly. Exit 125 from recorder is evidence failure, not a Cargo test failure. The RED replay is the sole intentional exit101. No lost stderr, hidden rerun, or overwriting labels. If a required independent check fails, classify according to §11, preserve the exact log, and continue only independent safe checks. Final QA commands must use the identical F1_TESTED SHA/tree. Don't run final tests until test edits and formatting are committed.

### 9.2 Ordered stages

| Stage | Required work and terminal criterion |
|---|---|
| F0 | Admission, review source pins, original evidence checks, pre-implementation worksheet; run one pinned RED replay; recover/qualify historical count. |
| F1 | Apply T1→T5 exactly; format only permitted bodies; source freeze check and commit. No new production code. |
| F2 | On clean F1_TESTED run targeted R/U tests, inventories, C2/C3 and other prescribed regressions. |
| F3 | Real local RustFS RF01/GB-R01 + existing B1 target, actual named bodies. |
| F4 | Full repository local QA on F1_TESTED, both toolchains/feature regimes, coverage >=85%, adapter/scripts. |
| F5 | Verify source freeze, create docs-only commit, preserve prior evidence, push to existing PR, read back exact head/body/state. |
| F6 | Observe ordinary final-head hosted CI and actual RF01 log. Report pending if still running. |
| F7 | Independent review/maintainer decision. Agent never marks PASS or merges. |

All new executable changes are tests. `cargo +1.98.1 fmt --all` may be run before immutable test commit, but changes outside the five permitted functions are unauthorized. Inspect diff; if formatter alone touches other lines, undo only its own unauthorized modifications when baseline bytes are certain (F08). Do not reset unrelated user work. Record exact source diff and approved modifications. Stage exactly three paths; `git diff --cached --name-only` must equal them. Commit `test(perf07a): close selective projection acceptance gaps`. Set `F1_TESTED=$(git rev-parse HEAD)` and tree. Run clean tracked check and freeze script below on F1_START..F1_TESTED. No docs in this commit. If a mechanical test correction is required after F1_TESTED, F08 permits one correction commit confined to the five bodies; freeze a new F1_TESTED and rerun every required final command, preserve preceding evidence under distinct labels prefixed `recheck-<new-F1_TESTED-short>-` (including the original F1 label). If observed failure is semantic, F09 instead; do not treat it as mechanical. Do not amend or force-push.

### 9.3 Source freeze (whole-file exclusion comparison)

Use this small read-only check from repository root. It compares all bytes outside the five allowed functions, not just file-name scope. No checked-in new script. Store stdout and exit status in F1 scratch. Source ranges are anchored by exact unique strings from the reviewed head. The ending anchor itself is preserved. Only the RF01 function extends to EOF. Reject ambiguous anchors or changed surrounding attributes/comments. The code verifies both unchanged prior test sources and all other executable files through the path allowlist. Run `python3 "$EV/check-source-freeze.py" "$F1_START" "$F1_TESTED"` on the immutable test commit. At docs closeout, use the same original arguments again to verify the tested delta, then independently require the F1_TESTED-to-F1_FINAL diff contains only the permitted docs and the executable/build trees are identical (§10.3). Do not pass F1_FINAL as the second argument to this exact-three-path checker. Pass explicit F1_START/F1_TESTED arguments, not floating branch.

```python
# $EV/check-source-freeze.py
import subprocess, sys
start, tested = sys.argv[1:]
reader = 'crates/quervant-core/src/segment/reader.rs'
unified = 'crates/quervant-core/src/search/unified.rs'
rf = 'crates/quervant-core/tests/pr15g_b_rustfs.rs'
ranges = {
    reader: [
        (b'    fn perf07a_r05_post_scan_finalize_refusal_no_rescan() {', b'\n    // R06 \xe2\x80\x94'),
        (b'    fn perf07a_r07_selection_order_and_singleton_boundary() {', b'\n    fn pristine_for_r07()'),
    ],
    unified: [
        (b'    fn perf07a_u02_projection_first_use_and_zero_metadata() {', b'\n    // U03 \xe2\x80\x94'),
        (b'    fn perf07a_u03_projection_selected_order_and_parity() {', b'\n    // U04 \xe2\x80\x94'),
    ],
    rf: [(b'fn perf07a_rf01_real_rustfs_multi_hit_cold_and_warm_projection() {', None)],
}
def git(*args):
    return subprocess.check_output(['git', *args])
def require(ok, msg):
    if not ok:
        raise SystemExit(msg)
def masked(src, spans):
    for begin, end in spans:
        require(src.count(begin) == 1, f'nonunique start {begin!r}')
        p = src.index(begin) + len(begin)
        if end is None:
            q = len(src)
            require(src.rstrip().endswith(b'}'), 'RF01 not last function')
        else:
            require(src.count(end) == 1, f'nonunique end {end!r}')
            q = src.index(end, p)
        require(q > p, 'empty or reversed function region')
        src = src[:p] + b'\n<F1-ALLOWED-FUNCTION-BODY>\n' + src[q:]
    return src
changed = set(git('diff','--name-only','-z',start,tested).decode().strip('\0').split('\0'))
require(changed == set(ranges), f'unexpected tested paths: {changed}')
for path, spans in ranges.items():
    a, b = (git('show', f'{rev}:{path}') for rev in (start,tested))
    require(masked(a, spans) == masked(b, spans), f'change outside allowed functions: {path}')
    print('PASS outside permitted function bodies:', path)
print('PASS exact test-only path scope')
```

This comparison masks function bodies including their closing braces and whitespace before the next anchor. Therefore also manually inspect each diff hunk and confirm it is the literal test changes in §§3–7 (no additional helper/production item inside a masked range). All existing attributes/registrations remain exact. Review full `git diff F1_START..F1_TESTED` and preserve. Do not rely on a mask to authorize arbitrary new items in its region. Require `git diff --check F1_START..F1_TESTED`, and `git diff --check BASE..F1_TESTED -- crates/` (historical executable range). Check worktree and staged whitespace clean. No whitespace exceptions authorized.

### 9.4 Exact targeted commands on F1_TESTED

Run each via `record` with distinct F1 labels. The five repaired functions execute via R/U prefix groups and RustFS harness; don't separately rerun all repaired individual functions after green merely for another receipt. Preserve raw row logs with markers. Original U01 individually retained for structural regression and paired with pinned red replay.

```bash
record f1-u01 cargo +1.98.1 test -p quervant-core --lib perf07a_u01_projection_prepared_offsets_no_full_keys -- --nocapture
record f1-r-group cargo +1.98.1 test -p quervant-core --lib perf07a_r -- --nocapture
record f1-u-group cargo +1.98.1 test -p quervant-core --lib perf07a_u -- --nocapture
record f1-column-geometry cargo +1.98.1 test -p quervant-core --lib column_geometry_tests
record f1-b3 cargo +1.98.1 test -p quervant-core --lib b3_key_identity_tests
record f1-phase3-projection cargo +1.98.1 test -p quervant-core --lib phase3_projection
record f1-phase5-i07 cargo +1.98.1 test -p quervant-core --lib phase5_i07
record f1-g-b0 cargo +1.98.1 test -p quervant-core --lib g_b0
record f1-e-projection cargo +1.98.1 test -p quervant-core --lib e_projection
record f1-c2-tests cargo +1.98.1 test -p quervant-core --lib c2_tests
record f1-c2-physical-tests cargo +1.98.1 test -p quervant-core --lib c2_physical_tests
record f1-perf06-c2 cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --nocapture
record f1-lib-list cargo +1.98.1 test -p quervant-core --lib -- --list
record f1-c2-list cargo +1.98.1 test -p quervant-core --test perf06_c2_physical -- --list
record f1-rustfs-list cargo +1.98.1 test -p quervant-core --all-features --test pr15g_b_rustfs -- --list
```

The block lists exact commands, not an instruction to ignore failures: check the return code individually and apply matrix before continuing. Require U01 1 pass with four completed rows; R group 9 pass; U group 6 pass; C2/C3 integration target 14 pass; exact test registration sets equal to previous A `green-lib-list.log` (1234 library registrations), `green-c2-list.log` (14 integration tests), `green-rustfs-list.log` (2 ignored real-service registrations). Compare sorted actual test-name sets (lines ending `: test`), not cargo compilation chatter. No additions, removals, renames, or ignore changes. The original `--list` harness does not itself prove ignore status; source attrs plus actual ignored harness execution do. All regression filters must select nonzero existing tests and pass; use actual counts, not invented fixed totals. Require R05 four calls with correct recovery and two injected case markers; R07 35 with eight exact boundary markers; U02 five; U03 19 with 8 errors and 8 immediate recoveries; U01 four; R06 20; unchanged I01 16 page executions, I02 20/200, unchanged U06 ledger checks. Verify these from raw logs and assertion-bearing source, not marker alone.

### 9.5 Real local RustFS (F3)

Reuse original plan §9.4 topology. If an already explicitly approved local test-only service is supplied, verify endpoint, health, isolated disposable bucket/prefix and pinned image provenance; do not destroy it. Otherwise prefer usable Podman (`podman info`), then usable Docker (`docker info`), with no privilege escalation, daemon modifications, or global reset. Require loopback port 19007 and task-owned name vacant; use `NAME=quervant-perf07a-f1-$$`, distinct disposable bucket `quervant-perf07a-f1-$$`, region us-east-1. Use exact pinned image from unchanged CI: `rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c`. Set `RUNTIME` to actual usable CLI. With preflight name and port verified, start:

```bash
"$RUNTIME" run -d --rm --name "$NAME" -p 127.0.0.1:19007:9000 \
  -e RUSTFS_ACCESS_KEY=quervanttest -e RUSTFS_SECRET_KEY=quervantsecret \
  rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
export QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:19007
export QUERVANT_RUSTFS_REGION=us-east-1
export QUERVANT_RUSTFS_BUCKET="quervant-perf07a-f1-$$"
export QUERVANT_RUSTFS_ACCESS_KEY=quervanttest
export QUERVANT_RUSTFS_SECRET_KEY=quervantsecret
```

These are disposable test credentials from original topology, not actual user secrets. Capture container ID and image, endpoint, bucket, health status; do not log secrets. Require successful startup. Register cleanup of exactly that ID on exit. Poll `/health` at most 30 times, each `curl -fsS --max-time 2`, sleep 2 seconds after failed attempts; health failure is F10. Never kill existing service or use a different port/image as improvisation. Execute on F1_TESTED with actual service:

```bash
record f1-rustfs-gb-rf01 cargo +1.98.1 test -p quervant-core --all-features --test pr15g_b_rustfs -- --ignored --test-threads=1 --nocapture
record f1-rustfs-b1 cargo +1.98.1 test -p quervant-core --all-features --test perf06_b1_rustfs -- --ignored --test-threads=1 --nocapture
```

Require 2 passed/0 failed/0 ignored, named GB-R01 and RF01, four complete response-equality pairs, 8 requests, 440 hit checks, unchanged provider request count, real cold workspace deletion/reopen. B1 actual existing `b1_r01_cold_shared_ordinals_and_pit` passes (1/0/0). Preserve full raw logs. Cleanup only task-owned container and disposable workspace; never remove shared bucket, authoritative objects or other prefixes. Do not claim host `--ignored` run on a fake store or hosted CI as replacement for local. Restore/clear task-created env overrides as appropriate. If no local service, mark F3 BLOCKED and continue independent QA; no acceptance claim.

### 9.6 Full local QA (F4)

On immutable F1_TESTED run original plan §9.5 commands **in order**, each separately recorded. Check actual return codes. Source/test changes require this full rerun; the previous green run cannot substitute. No further performance qualification, profiler or new benchmark configuration.

```bash
record f1-fmt-198 cargo +1.98.1 fmt --all -- --check
record f1-fmt-185 cargo +1.85.0 fmt --all -- --check
record f1-clippy-198 cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
record f1-clippy-198-af cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
record f1-clippy-185 cargo +1.85.0 clippy --workspace --all-targets -- -D warnings
record f1-clippy-185-af cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
record f1-test-198 cargo +1.98.1 test --workspace --all-targets
record f1-test-198-af cargo +1.98.1 test --workspace --all-targets --all-features
record f1-test-185 cargo +1.85.0 test --workspace --all-targets
record f1-test-185-af cargo +1.85.0 test --workspace --all-targets --all-features
record f1-cov-default cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
record f1-cov-allfeatures cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
record f1-doc cargo +1.98.1 doc --workspace --no-deps
record f1-doc-af cargo +1.98.1 doc --workspace --all-features --no-deps
record f1-bench-norun cargo +1.98.1 bench --workspace --no-run
record f1-adapter-contract cargo +1.98.1 test --locked --manifest-path benchmarks/pr15d/adapters/quervant/Cargo.toml
record f1-scripts bash benchmarks/scripts/test-scripts.sh
```

Coverage command, scope, exclusions and toolchain exactly original. Read named `TOTAL` Lines/Missed Lines/Cover% columns; report covered = total − missed and percent, require successful exit and >=85% in each regime. No new production branches; no selective exclusion or changed threshold. Original report 93.65% default/93.26% all-features are historical only. Report actual suite counts per four workspace runs, including library harness and workspace counts clearly labeled. If aggregating workspace test summaries, distinguish actual top-level harnesses from nested child processes and Criterion smoke output; do not double count or guess interleaved summaries. State any ambiguous aggregate and retain per-target summaries instead. No need for a new count-parser framework. Actual library target default expected 1233 pass, 0 failed, 1 ignored given unchanged inventory, but report observed values. Inventory mismatch or failure triggers F09/F11, not edits to expected numbers. Adapter target expected 6 pass, scripts 108 pass (original receipts); record actual outputs. `cargo doc` is docs build, not doctests. `bench --no-run` compile only; any all-targets test-mode Criterion execution must be labeled smoke, not timing data. The unchanged Python framework is covered by ordinary CI; no additional local framework run needed.

## 10. Evidence delivery, docs-only closeout, and hosted CI

### 10.1 Compact evidence package

All raw final logs remain in task-owned `$EV` with exact command records. Commit the relevant new evidence under `$A_DIR/evidence/f1/`, not into old evidence paths. Required selected raw logs: immutable red replay, f1-u01, f1-r-group, f1-u-group, f1-perf06-c2, f1-rustfs-gb-rf01, f1-rustfs-b1, three inventory outputs, two coverage TOTAL excerpts, per-workspace-run result summaries with exact library launch/result, adapter/scripts summaries, source-freeze output, original-red attribution receipt (original row/time/hash, any contemporaneous proof or explicit absence), historical count excerpt or explicit unavailability, real-service topology/cleanup receipt, and `commands.tsv` containing actual source-bound command outcomes. Include failure logs if any. Record SHA-256 of every retained evidence file and of every raw log retained locally, with log paths and lengths. Use standard `sha256sum`; no new custom receipt format/cryptography. A summary is not a raw execution log; name it accordingly. For full QA, keep raw locally; no need to commit repetitive full logs. If selected raw log contains trailing whitespace causing a new `git diff --check` diagnostic, preserve its raw bytes separately and commit an explicitly named `.log.b64` lossless base64 encoding plus original SHA-256 and decoded byte length, following F12. Verify decoded equality. Do not trim raw evidence. Never fabricate a missing log, claim a skipped command passed, or rerun solely to create a historical receipt. Do not expose credentials or unrelated files.

### 10.2 Required original report erratum

Append one dated section to `PERF07A_EXECUTION_REPORT.md` with title `## PERF-07-A-F1 review erratum and acceptance continuation (<actual UTC date>)`. Preserve all prior content, including historical status. Use these exact substantive facts (fill only observed/recovered facts and new report link):

> The original RED command executed with HEAD `c9ca7975ab6f29fc4fe1fac65951cede3799cb8c` and HEAD tree `0ead7efb356d66751c801b12a27147e281ae2a5e` in a precommit worktree, 2026-11-28T02:28:33Z–02:28:50Z, exit 101. The RED commit `06898baf9a796cddf5a03033652df4d2a53e150a` was created at 02:28:55Z. The historical red failure is real; the original record does not by itself identify the exact dirty tested source tree. [Report actual contemporaneous identity evidence or its unavailability.] The F1 immutable RED replay is separate evidence and does not establish the historical worktree identity retroactively.
>
> The original U02 marker `rows=6` overstated five completed calls. The original U03 marker `rows=6` did not count its eight calls correctly and its failure matrix/recovery were incomplete. F1 corrects these assertions and markers. R05 now proves corrected-selection recovery on the same sticky-unavailable owner; R07 exclusively requires the historical singleton-boundary error; RF01 adds complete response parity. [Report actual F1 outcomes, not expected results as observations.]
>
> The historical library test count `1234 passed, 0 failed, 1 ignored` in the QA table must not be treated as a workspace total. The original library inventory contains 1,234 registrations including one ignored; prior hosted run observed 1,233 passed, zero failed, one ignored. [Insert actual recovered original local summary, or state it is unavailable/unverified.] New F1 test counts are separate and bound to F1_TESTED.
>
> Previous local/hosted statuses and draft wording are execution-time history. Prior CI run 46102649763 completed successfully for F1_START; the PR was ready, not draft, when reviewed. F1 source/test results and current hosted state are reported in [PERF07A_F1_EXECUTION_REPORT.md](PERF07A_F1_EXECUTION_REPORT.md). No timing qualification or baseline promotion.

Do not edit original raw logs or retroactively replace their hashes. If F1 has a blocked test, adjust only forward-looking outcome sentence to state actual result/blocked gate, never claim corrected behavior executed if it did not. Do not push a new source revision containing a known failing semantic assertion under the existing ready PR; deliver the local blocked report and exact evidence for review instead. Independent safe verification may continue. A pure external CI-pending outcome is not a semantic failure and does not prevent the prescribed push.

In roadmap, replace exactly `implemented on \`dev/perf07-a\`,` in existing A status paragraph with `implemented on \`dev/perf-07-a\`,` (backticks are literal Markdown, no backslashes in file); append a dated brief F1 status with F1_TESTED, actual local acceptance, pending hosted/independent gates, link to F1 report. Do not mark DONE or modify A–I order, historical C4 appendices, benchmark policy, or other branches. No architecture doc edit required.

### 10.3 Report format and docs commit

Write `PERF07A_F1_EXECUTION_REPORT.md`, with the following exact sections and actual data:

1. Disposition, repository/branch/PR and starting identities; F1_START, original BASE/RED/A_TESTED, F1_TESTED/tree, plan SHA-256 and original plan SHA-256; clean tracked state and preserved untracked paths. Record the new plan file verbatim.
2. Reconciliation and pre-implementation worksheet (§1.3), changes in each of the five permitted function bodies, no production change. Source freeze actual output and path inventory.
3. Historical corrections and red replay: timestamps, HEAD/tree, original and new logs, explicit provenance limitation, actual outcome; historical local count evidence or absence.
4. Per-row R05/R07/U02/U03/RF01 tables with completed stable labels, literal expected/actual error variants, counters, ownership, state/metadata, ledger/guard, recovery and complete response checks as applicable. Include actual row totals and all unchanged targeted regressions. Distinguish original 8 U03 vs F1 19.
5. Actual RustFS topology, named local test results, four full-response pairs, 8 requests, 440 hit checks and actual provider before/after request count; cleanup ownership.
6. Per-command PASS/FAIL/BLOCKED/N/A with actual test counts, compiler versions, coverage Lines/Covered/Missed/% for both regimes, exact log identities. Full QA on F1_TESTED only. Record test inventories equal (actual sets), adapter/scripts, compilation only.
7. Residual risks, applied decision rules, no performance acquisition, local gates, source freeze, hosted/independent pending at docs time. Include actual unresolved failures. Do not mark independent G7 PASS.
8. Evidence index/manifest with links, original receipt integrity retained. Terminal handoff includes final remote head and CI status after push; report written before push cannot truthfully claim future CI or its own commit SHA. No recursive docs amendment or extra CI solely to replace a pending historical marker.

Commit only docs allowlist using explicit path staging (include new `evidence/f1/`, not existing evidence siblings). Message `docs(perf07a): record F1 correctness acceptance and evidence errata`. Set `F1_FINAL=$(git rev-parse HEAD)`. Verify `git diff --name-only "$F1_TESTED..$F1_FINAL"` is only permitted docs; compare all source/build/CI/benchmark trees byte-identical between F1_TESTED and F1_FINAL, and historical original plan+evidence tree unchanged from F1_START. `git diff --check "$F1_START..$F1_FINAL"`, worktree and staged checks must pass. Check `git diff --check BASE..F1_FINAL`; if diagnostics exist solely in frozen original artifacts, report exact comparison to `BASE..F1_START` and classify F13 (no automatic waiver). New diagnostics always fail; fix own docs formatting or losslessly encode raw new evidence under F12. Verify local relative Markdown links (new plan/report/evidence). `sha256sum -c` for old manifest and new manifest, ensure no extra unknown staged paths. Do not run cargo tests after docs-only change unless code/build inputs changed (forbidden). Do not rewrite history.

### 10.4 Push and CI readback

Before push fetch remote and check head still F1_START, main still BASE, PR still open, same branch/base. No force, rebase, merge, duplicate PR, or branch rename. Push `git push origin dev/perf-07-a` normal fast-forward. Read back:

```bash
git ls-remote --heads origin dev/perf-07-a
gh pr view 135 --repo yduchesne/quervant --json headRefOid,headRefName,baseRefName,state,isDraft,url,body,mergeStateStatus
```

Require remote head == local == PR head == F1_FINAL, base `main`, state OPEN. Preserve the user's actual ready/draft setting observed at admission; no `gh pr ready`/`--undo`. Update **existing PR description** by appending a single F1 section (not rewriting original history) with test-only scope, actual F1_TESTED/F1_FINAL, corrected 5/19 matrix and 4 parity pairs, local status, qualified red provenance, actual coverage, report link, no timing qualification, and current hosted state. Remove no old evidence; if old text says draft, explicitly qualify it as original handoff and note current actual state. Use `gh pr edit 135 --body-file <task-owned prepared body>` only if current body equals captured admission body (if another actor edited it, F14: stop body edit, preserve remote text and report). Read back updated body. If PR body permission unavailable, F14 report rather than changing readiness. No PR comment claiming review approval.

CI: ordinary PR event only, no manual dispatch or duplicate push trigger. Inspect `gh run list --repo yduchesne/quervant --branch dev/perf-07-a --event pull_request --json databaseId,headSha,status,conclusion,url` for exact final head; inspect matching run with `gh run view <id> --repo yduchesne/quervant --json headSha,status,conclusion,jobs,url`. Require all five jobs `rust`, `msrv`, `rustfs`, `benchmark-adapter-contract`, `python-benchmark-framework`; actual conclusion success, not skipped/cancelled. Inspect RustFS job actual log for named RF01 and GB-R01 passing (2/0/0; `--ignored` actual bodies); job success alone is insufficient for this specific witness. Ordinary hosted `--nocapture` may not print parity markers; named test passing plus new source and local row log proves assertions. Record run/merge ref/job IDs and URLs; compare base/head checkout identity. Poll at most 20 times, 30 seconds apart as original plan; if still pending, report pending and finish local handoff without routine reconfirmation. No rerun-to-green, no dispatch, no cancel. If CI fails, retain logs, F15. Do not append another repo commit just to change the historical pending CI status; provide live status in terminal handoff and PR body if authorized.

## 11. Preauthorized decisions and failure classification

These are the only autonomous exception rules for F1. Each rule identifies trigger, scope/action, prohibition, evidence/gate/owner. Apply most restrictive matching rule. If unexpected condition is not explicitly covered, use F18. Independent work may continue only if it cannot invalidate or assume the blocked contract. Never reinterpret a test failure as approval to change production, modify expected values, skip, or increase budgets. No generic "fix anything necessary" authorization.

| ID | Observable trigger | Category / exact authorized response | Prohibited / evidence, gate, owner |
|---|---|---|---|
| F01 | PR open, BASE/head exact, clean local branch absent or clean ancestor | AUTO: create tracking branch or fast-forward only; record refs/status; continue | No reset, force, cherry-pick, duplicate PR; F0 agent |
| F02 | Main or remote head differs from pinned SHA, PR closed/merged, branch diverged, overlapping dirty tracked/untracked work, wrong base | HARD STOP whole dependent execution; preserve all work and report refs/diff | No auto rebase, no overwrite or choosing a new base; F0/F5 maintainer |
| F03 | Anchor/blob/tree/manifest mismatch, unexpected RED production changes, exact test function missing/changed, unexpected baseline structure | HARD STOP affected/all work; show exact observed vs expected path/hash and invariant | No approximate source match, restoring foreign work, editing old evidence; F0 reviewer |
| F04 | Fixture does not open, native mapping not bijective, expected state cannot be prepared, prescribed assertion premise contradicts pinned source | HARD STOP affected test; report source/fixture actual facts | No substitute fixture, change caps, select different ID, weaker predicate; F1/F2 reviewer |
| F05 | Scratch name exists but original and source untouched | AUTO: use exact PID-suffixed alternative once, otherwise STOP | No deleting or mixing old logs; record paths; F0 agent |
| F06 | Required Rust toolchain/llvm tools/dependency unavailable | DEFER AND CONTINUE safe independent checks after standard approved toolchain setup attempt | No alternate toolchain, lockfile changes, disabling features, hidden gate waiver; exact failure, F4 maintainer |
| F07 | Immutable RED replay exit101 with exact named U01 failure, 1100 vs 0 and full_decodes=1 | AUTO: record as expected RED, return to active branch and continue | Any other result (incl green, build failure) HARD STOP G1; no changing RED or repeated run; F0 reviewer |
| F08 | rustfmt or compiler/Clippy mechanical issue confined to literal prescribed tests (line wrap, type annotation, local alias, borrow/reborrow syntax) with same input/oracle/route/count | AUTO: correct syntax only, no semantic alternative; inspect diff; if already F1_TESTED create new test-only commit and rerun complete final QA with fresh labels. One such post-freeze correction cycle allowed; if repeated/unforeseen stop | No lint suppression, altered assertions, altered ownership/projection code, new helpers outside scope; evidence before/after and exact diagnostic; F1–F4 agent |
| F09 | Any strengthened semantic assertion, typed error, counter, cell, ledger, resource, cursor or integration expectation fails | HARD STOP affected implementation/acceptance. Record first exact failure; distinguish test construction error only if F08 mechanical preconditions hold. Continue independent evidence/QA only if safe | No production fix, alternative allowed outcome, fixture changes or retry-to-green; F2/F3/F4 reviewer designs amendment |
| F10 | Approved real service absent, name/port occupied, unavailable pinned image/runtime/health, local credential setup impossible | DEFER AND CONTINUE independent local QA. Mark F3 BLOCKED. Cleanup only owned resources | No killing existing service, alternate port/image, fake provider, destructive global reset; record topology/attempt; maintainer |
| F11 | Workspace test/coverage/adapter/script fails, inventory differs, ambiguous result, or suspected pre-existing/flaky failure | HARD STOP acceptance of affected gate. Preserve logs. A claim of pre-existing/flaky requires actual baseline or nondeterminism evidence; otherwise label unclassified failure and stop | No automatic baseline or retry campaign, no waivers, no threshold or count manipulation; F4 reviewer/maintainer |
| F12 | New selected raw log has whitespace diagnostic, raw bytes otherwise valid and nonsecret | AUTO: commit lossless `.log.b64`, original SHA/bytes and decode verification; keep raw local; run diff check | No trimming, changing raw history, or hiding error; F5 agent |
| F13 | Source-freeze or scope mismatch, new whitespace diagnostic unresolved, or inherited exact historical diff-check diagnostic | HARD STOP affected acceptance; inspect exact path/line/type and compare historical blob; if inherited, report without editing frozen evidence | No broad exception or historical rewrite. Maintainer decides any needed narrowly scoped exception; F5 reviewer |
| F14 | Push response ambiguous, PR metadata/body concurrently changed, or body permission denied | AUTO only read back exact remote head; if equals F1_FINAL reuse that push, else STOP push. For body mismatch/denial DEFER body update, preserve content and report | No retry push over moved head, body overwrite, readiness change, duplicate PR; F5 maintainer |
| F15 | Exact final CI pending or required job/log unavailable | DEFER AND CONTINUE terminal handoff; state actual pending/blocked status. If failed, retain job failure; no rerun | No manual dispatch, treating pending/skipped as pass, or changing workflow; F6 maintainer |
| F16 | Original local QA log missing/ambiguous or contemporaneous dirty-source identity unavailable | AUTO: record explicit historical limitation per §8; fresh immutable replay remains separate; new local final suite counts separate | No reconstruction, relabeling, invented hash or historical count; F1-E1/E2 agent |
| F17 | All required local and hosted gates actually pass, evidence complete | AUTO: report ready for independent review only; preserve actual PR readiness | No merge, marking G7 PASS, baseline promotion, or starting B; F7 maintainer |
| F18 | Any material condition not covered by exact preconditions above, or requires architecture/semantic decision | HARD STOP affected work. If isolation demonstrable, DEFER independent safe work without relying on unresolved decision; otherwise stop all | No improvisation. Report file/symbol, observed facts, invariant, alternatives, dependent gates and smallest required decision; reviewer/maintainer |

Failure taxonomy (authoring guide §3C): introduced regression, feature defect, deterministic verified pre-existing failure, demonstrated nondeterministic failure, environment/harness failure. Only use pre-existing or flaky classification with actual supporting evidence; a suspicion is unclassified. Preserve earlier failed executions; a later green does not erase one. F1 modifies tests, not runtime. If a stronger assertion fails, the agent must not assume the new test is wrong. Classify and stop as above. No extra baseline campaign authorized just to obtain a convenient classification.

## 12. Acceptance and terminal handoff

| Gate | Required final evidence |
|---|---|
| G0 / F0 | Exact current main/head/trees, source anchors, preserved original plan and manifest, admission and worksheet. |
| G1 / F0 | Historical red attribution accurate; actual immutable RED replay exact intended failure, separately identified. |
| G2 / F1–F2 | Production and all other source frozen; five existing functions only; R05 4, R07 35 with exclusive boundary and 8 rows, U02 5, U03 19 with 8 exact failures + 8 same-ledger recoveries; all 15 A unit registrations execute green; all original test inventories preserved. |
| G3 / F3 | Actual local filesystem C2/C3 14 pass, I01/I02 retained oracles; real local RustFS RF01/GB-R01 2/0/0, B1 1/0/0, four full parity pairs, 8 requests/440 hits, provider count unchanged. |
| G4 / F4 | Mandatory local format/Clippy/tests on both toolchains/features, actual >=85% workspace lines in both, docs, adapter/script regression, bench compile. All bound to exact F1_TESTED. |
| G5 / F5 | Historical evidence unmodified, precise docs corrections, source freeze, clean whitespace, exact PR head/readback and evidence delivery. |
| G6 / F6 | Ordinary hosted exact-head CI five jobs all successful, named RF01/GB-R01 actual execution proof. Pending/blocked is not pass. |
| G7 / F7 | Independent review and maintainer approval only. No agent approval or merge. |

Suggested terminal disposition when all local gates and hosted G6 pass: `PERF07_A_F1_ACCEPTANCE_EXECUTED_READY_FOR_INDEPENDENT_REVIEW`. When local gates pass but CI pending: `PERF07_A_F1_LOCAL_ACCEPTANCE_PASS_CI_PENDING`. For any blocked gate: `PERF07_A_F1_BLOCKED_<GATE>` with precise reason, actual completed independent tasks, and required next action. Do not claim completion just because a report exists. Do not claim measurable performance improvement; PERF-07-I is the only consolidated qualification owner.

Return a concise, complete terminal report in the coding-agent handoff (not just a scratch path): PR link and actual readiness, BASE/F1_START/RED replay/F1_TESTED/tree/F1_FINAL/REMOTE_VERIFIED_SHA, source freeze result, historical correction disposition, new row counts and key exact error/counter values, RustFS topology/result, per-command QA and coverage table, test inventories, exact CI run/job links and current status, applied matrix rules, any blockers and retained evidence/report links. Preserve every failed command and actual exit code. State whether production code changed (**must be no**), whether benchmarking was run (**must be no**), and whether PR was merged (**must be no**). Do not initiate another coding-agent round for a reporting detail already fixed by this plan.

## 13. Reviewer checklist and residual risks

- [ ] Fresh main and existing PR admitted, no alternate branch created, original historical artifacts unchanged.
- [ ] All five permitted existing test bodies changed only as prescribed; no production/test-seam/fixture design change; other source and build inputs frozen.
- [ ] R05 initially mismatch false and corrected retry true on same sticky-unavailable owner, exact scan/counter/accounting; R07 large invalid singleton exclusive range and zero scan rows, other boundary rows exact UTF-8.
- [ ] U02 exactly five actual calls; U03 three controls + eight real failures + eight same-snapshot/same-ledger successes, prepared and unmetered exact counters, literal error precedence, zero admission/STORED/reader bytes on failures.
- [ ] RF01 all original per-hit and provider checks, four complete pair comparisons on actual RustFS; GB-R01 untouched; integration fixtures unchanged.
- [ ] Historical RED receipt distinguished from later commit and separate immutable replay; original test count either recovered or honestly qualified; branch/status correction accurate.
- [ ] Full source-bound local QA and >=85% coverage, actual targeted/integration executions and inventory parity; exact final CI five jobs and RustFS body evidence.
- [ ] Evidence hashes and links valid; documentation status reflects actual results; no agent merge, baseline promotion, real benchmark or claimed speedup.

Residual risks remain those already documented for A: cold N-key validation and N+1 offset directory; refused/unmetered one scan per projection group; optional metadata admission order may vary; physical allocation/OOM timing not identical; existing cancellation sites unchanged. F1 does not alter or resolve these accepted design boundaries. Actual warm performance unmeasured until PERF-07-I; no individual speedup threshold is imposed. No new unverified production behavior is introduced. Historical precommit source identity may remain unprovable; this limitation is explicitly preserved while independent replay verifies the immutable RED source. Missing historical local raw log may remain missing; do not equate fresh evidence to a historical receipt. Any actual new correctness failure is not an accepted residual; F09/F18 applies.

## 14. Source references (immutable reviewed revision)

- [PR #135](https://github.com/yduchesne/quervant/pull/135), [prior successful CI](https://github.com/yduchesne/quervant/actions/runs/46102649763), [actual prior RustFS job](https://github.com/yduchesne/quervant/actions/runs/46102649763/job/140848349411).
- [Original detailed plan](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/docs/pr-artifacts/perf-07-a/PERF07A_DETAILED_IMPLEMENTATION_PLAN.md), [original execution report](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/docs/pr-artifacts/perf-07-a/PERF07A_EXECUTION_REPORT.md), [historical commands.tsv](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/docs/pr-artifacts/perf-07-a/evidence/commands.tsv), [RED commit](https://github.com/yduchesne/quervant/commit/06898baf9a796cddf5a03033652df4d2a53e150a).
- [Reader tests and production code](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/crates/quervant-core/src/segment/reader.rs), [unified projector and tests](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/crates/quervant-core/src/search/unified.rs), [RF01 source](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/crates/quervant-core/tests/pr15g_b_rustfs.rs).
- [Authoring guide](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md), [AGENTS](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/AGENTS.md), [TESTING](https://github.com/yduchesne/quervant/blob/f7437954c87e070ffc5df15bbc4d80c826ace3e7/docs/TESTING.md).

**Final instruction:** execute continuously within this finite contract. Do not invent implementation behavior to satisfy a test or invent evidence to close a gate. The next action after a successful F1 handoff belongs to independent review and the maintainer, not another autonomous optimization stage.

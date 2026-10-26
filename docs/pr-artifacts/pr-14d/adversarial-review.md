# PR 14D — adversarial review

**Status:** local evidence and independent review inputs; PR 14 remains
IN PROGRESS. Implementation `d0e1bbb`.

## 1. Falsification attempts executed

| Challenge | How it could falsify the claim | Observed |
|---|---|---|
| Post-hoc-only charging | A budget below the transient should still allocate the full buffer | `d01`/`d09`: `exact/4` fails with typed `BatchMemoryBytes`; `d02` thresholds grow 387 → 45,726 → 1,462,302 |
| Constant logical threshold | Same as the old defect | `d02` asserts strict growth; B20/B21 post-fix shows the same |
| Charge before growth missing | Capacity grows even when the charge is rejected | unit `t08`: rejected push leaves `out.len()==0`, `capacity()==0`, no leaked charge |
| Double release / underflow | Over-release or double `finish` corrupts the ledger | unit `t02`, `t05`; `Drop` fallback `t03` |
| Winner double charge | Winner reservation plus heap charge both live | winner released by `finish()` immediately before heap admission; `t07` verifies concurrent-buffer peak |
| Legacy bypass | Batch sort still calls the bulk extractor unmetered | `extract_field_paths_charged` used with the sink; unit `t09` rejects before retained growth |
| Ordering regression | Single-pass selection changes Min/Max or ties | `d03` (mixed bool/i64/u64/f64/keyword/null/missing asc+desc), `d08`, PR 14A/14B suites |
| Silent partial success on cancel | Cancelled slot returns hits or leaks scratch | `d06`, provider `d12` cancellation, `pr14a::t13` |
| Sibling contamination | A failed middle slot poisons the next budget | `d05`: S/F/S at the same aggregate limit; 100 repeated runs and interleaved failures |
| Provider divergence | Local-only accounting works but remote differs | provider `d11` exact/one-under + hand-authored oracle; `d12` mixed/PIT |
| Format drift | Fixture or codec changed to pass | `d07` frozen SHA-256; corrupt bytes rejected; no format diff |
| Fault-regression | Storage/recovery changed | F01–F09 ×10, PR 13 proxy/crash/objectstore all green |

## 2. Test-harness credibility

- Real provider: pinned digest `sha256:1803faef…6a3c`, health `1.0.1`, unique
  prefixes, disposable credentials never logged.
- Oracles are hand-authored in-test or fixture-model derived; production
  comparators are not used to compute expected values.
- Allocator observations run in a spawned child with an explicit measurement
  window (B20/B21) and are reported as allocator-window peaks, not RSS.
- Child entrypoints (`p4_child_bootstrap`, `p4_fault_child_open`,
  `b20_child_json_memory_probe`) were invoked only by their parents.

## 3. Failed attempts during implementation

| Attempt | Outcome | Classification |
|---|---|---|
| Initial `d04` expectation `[a,c]` | Actual `[a,b]` because all single-occurrence minima are 0 and ties break by key | Test-oracle error; corrected to hand-authored `[a,b]` |
| Initial `d05` at the single-slot threshold | Third slot failed because successful responses remain retained in the cumulative meter | Test-expectation error; corrected with a documented 2× cumulative bound, still far below the huge slot |
| Initial `d12` used `writer.insert` for an existing key | `DuplicateDocument { key: "a" }` | Test-harness error; corrected to `MutationRequest::upsert` |
| Any production fix attempted during test debugging | None | N/A — scoped test/doc corrections only |

No failure was relabelled PASS; no test was ignored or weakened to make the suite
green.

## 4. Known limitations

| Limitation | Impact |
|---|---|
| One decoded occurrence (indexed) and the legacy walker path/stack exist before admission | Bounded per JSON limits; documented in `resource-characterization.md`; not claimed as a hard physical cap |
| Occurrence buffer is materialized (admitted) rather than streamed item-by-item | Decision AD-05 explicitly governs this growth; no second `Vec<FieldValue>` |
| Winner is released immediately before the retained heap charge | No allocation occurs between release and charge; ordering documented in `design-and-ownership.md`; conservative no-double-charge |
| Logical meter ≠ RSS | Always reported as a logical reservation ledger |
| WSL2 host | Not a bare-metal performance environment; no performance claim is made |
| No 14D benchmark | PR 14's qualified P4 trials are unchanged and not re-run; this PR makes no speed claim |
| Final-SHA CI | Not observed at evidence time; see `final-acceptance.md` |

## 5. Reviewer prompts

1. Verify no production path passes `None` to the sort helper when a batch meter
   exists (`collect_mixed` uses the existing scope).
2. Verify `push_occurrence` charges before `try_reserve_exact` and before
   `push`; check capacity reconciliation arithmetic.
3. Verify the legacy sink re-raises `BatchMemoryBytes` rather than a generic
   segment limit.
4. Verify the winner reservation outlives the winner clone and ends before the
   heap charge.
5. Verify the frozen fixture digest and the absence of format/API/CI diffs.
6. Verify the two provider cases and the fault matrix ran on the pinned digest.


## 6. SR-14D-01 addendum

New falsification attempts:

- Rejected winner reservation must not invoke conversion: unit counter F07 stays
  0, then increments exactly once on admission.
- Borrowed comparator must match canonical ordering for every supported scalar
  pair in both directions: F01–F03 parity over 16×16 pairs.
- A large losing string must not be the Min winner: F08 keys and threshold delta
  (≥4,096 B only for Max).
- Pinned page-2 cursor after JSON sort: F13 in `d04`.
- Mid-scan cancellation must release the meter: F11 typed cancellation + retry.

Remaining limitation: F12 legacy-sort integration evidence is unit-level plus
existing PR 11 legacy suites; no dedicated legacy-sort fixture was added.

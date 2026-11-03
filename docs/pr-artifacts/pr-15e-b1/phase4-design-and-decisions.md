# PR 15E Phase 4 — design and decisions (as executed)

**Authorization:** maintainer-approved Phase 4 plan (postings-driven single-term candidate
enumeration), executed on the existing PR #83 branch. One optimization; no Phase 5 work.

## 1. Approved decisions and how they were implemented

| ID | Approved decision | Implementation |
|---|---|---|
| P4-AD-01 | Eligibility is exactly: `root == Lexical(0)`, one `CompiledLeaf::Term` with one analyzed term, no typed leaves, `positive_lexical == {0}`, no aggregation, no `after` cursor; sorting allowed | `search/unified.rs::single_term_postings_eligible`, computed once per query from the compiled plan in `collect_mixed` |
| P4-AD-02 | One evaluator, one ledger/scorer pipeline, private boolean argument, preserved full-live logical work charge, borrowed ascending postings, unchanged scoring/retention | `search/execute.rs::evaluate_lexical_with` new private argument + branch; legacy loop retained verbatim for the fallback |
| P4-AD-02 §4 | Charge one examination per **effective-live** document, never per posting | `effective_live_examination_count` over the same bitmap, ≤4096-position chunks, cancellation polled; single `charge_lexical(live_count)` |
| P4-AD-02 §6 | No early top-K stop; exact `total_hits` | candidate loop feeds the unchanged matched set and `score_segment` |
| P4-AD-02 §7 | No scope/identity/score/sort/projection/cursor change | untouched; only enumeration changed |

## 2. Why the narrow rule

A multi-term/Boolean candidate generator would need a new budgeted union/intersection engine
plus rules for negation, typed predicates, phrase witnesses and failure ordering — not
authorized in this phase. The narrow rule guarantees the candidate sequence is already
decoded, validated, effective-live filtered and strictly ascending, so the optimization adds
no new index structure, iterator framework, merge heap, scorer or cache.

## 3. Recorded variances (disclosed for review)

| Item | Plan ledger | Actual | Why / risk |
|---|---|---|---|
| In-crate Phase 4 unit tests | Listed `execute.rs` (private seam) and existing integration files or a new `tests/pr15e_phase4.rs` | Added to the existing `unified.rs` `#[cfg(test)] mod phase4_tests` | The plan mandates a test-only predicate-call witness, which requires in-crate access; the real index fixtures used by every unified test already live in that module. Test-only module in an allowed production file; no public or benchmark-build surface |
| Integration tests | Allowed `pr15e_b1.rs` etc. | Two tests added to `tests/pr15e_b1.rs` | Within the ledger |
| Docs | Allowed `phase4-design-and-decisions.md`, `phase4-execution.md`, `phase4-qualification.md`, handoff/decision log | This file, `phase4-execution.md`, `phase4-qualification.md`, handoff section, decision-log entry | Within the ledger |

## 4. Non-goals honored

No Boolean/multi-term/phrase/typed/mixed/aggregation/cursor optimization, no `work.rs`
change, no scorer, heap, sort, cursor, projection or segment/format/writer/reader change, no
new dependency, no public API, no second meter, no new benchmark harness, no Phase 5 work.

# PR 15H-A — correctness contract

## Behavioural contract

The candidate changed only the `postings_candidate_eligible == true` arm of
`execute::evaluate_lexical_with`. For that shape it was required to preserve:

| Contract | Requirement |
|---|---|
| Eligibility | Unchanged `single_term_postings_eligible`; no plan/API extension |
| Shape guard | Exactly one single-analyzed-term leaf; no typed examination; `CorruptIndex` otherwise |
| Candidate order | Strictly ascending, unique, effective-live decoded postings |
| Membership | Same `is_match` callbacks, order and count |
| Work | Same per-effective-live-document lexical charge, scanned postings and cancellation polls |
| Budget | 48-byte matched-set then 64-byte scored-map virtual charges, same order and no reduction |
| Scoring | Existing `bm25` per match, ascending doc order, `0.0 + contribution` |
| Output | One ordered `(physical_doc_id, f64)` per match; same score bits and order |
| Errors | Same typed class and precedence, including resource-before-score |
| Fallback | Every noneligible shape byte-identical to baseline |
| Caller | `collect_mixed` key/sort tuple/heap/duplicate-key/cursor/projection unchanged |
| Storage | No codec, segment, manifest, `CURRENT`, `Directory`, cache or remote change |

## Verified against

1. The pinned baseline source at `ddcbe7789…` in a clean detached worktree.
2. An ineligible but logically equivalent `And([Term])` request on the same
   segment (the established PR15G differential pattern), including exact
   `f64::to_bits()` score equality.
3. Real local `FsDirectory`/`MemoryDirectory` write → commit → reopen paths.

## Candidate result

All unit, differential, integration and workspace gates passed at candidate
`dce8f024…`. The optimization was nevertheless rejected on performance; the
production files were then restored to baseline. This contract documents the
behaviour the candidate was required to preserve and that was exercised before
the rollback.

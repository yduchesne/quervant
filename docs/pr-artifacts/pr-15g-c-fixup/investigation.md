# PR 15G-C fixup investigation

**Status:** source-backed investigation complete; no measured causal percentage
is claimed.

## Source witness: four full postings decodes

The failed C implementation in `search/execute.rs::visit_single_term_sorted_stream_with`
opened `reader.postings(field_id, term)` four times for a nonempty term:

1. initial full decode + `charge_scanned` + virtual leaf charge;
2. predicate/test-only visitation over effective-live postings;
3. BM25 validation over effective-live postings;
4. candidate emission into the shared heap path.

It also passed `posting.freq as u32` to the late-score callback and recomputed
BM25 for selected winners. The fixup removes those repeated decodes and the
lossy frequency cast.

## Candidate admission remains expensive

`unified.rs::admit_candidate` still performs per-candidate key resolution, sort
tuple construction, duplicate retained-key scan, candidate charge and heap
comparison/admission. The fixup does not remove that work and does not change the
heap comparator, K+1 cursor or projection path.

## Historical failed-C ratios (preserved, not profile attribution)

The qualified failed-C campaign measured B/A ratios: 100K common K100 `1.154`,
100K common K10 `1.284`, 100K absent `1.625`, 100K rare `1.574`; aggregate
`1.240647`. These are historical wall-clock outcomes, not measured pass
contributions.

## Profiler availability

The fixup did not obtain privileged CPU/allocation profile percentages. The
source-proven repeated-decode mechanism is sufficient to justify the prescribed
two-pass experiment; the new full nine-lane campaign is decisive. No sysctl,
sudo, capability or privileged tracing change was made.

## Expected removal / residual cost

The replacement removes two full immutable postings decodes per nonempty
eligible segment and removes winner rescoring. Residual cost remains: two
postings decodes, per-match BM25 in pass 2, and per-candidate key/sort/heap work.
No speedup percentage is promised.

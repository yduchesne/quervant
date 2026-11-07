# PR 15H-A2 — diagnosis

## Source-level facts (verified before implementation)

1. **The rejected H-A candidate had no cardinality check.** At `dce8f02`,
   `evaluate_lexical_with` contained
   `if postings_candidate_eligible { return evaluate_single_term_linear(...) }`,
   so a 0- or 1-posting eligible term always entered the linear helper.
   Verified with `git show dce8f02:…/execute.rs`.
2. **The dispatch input is already decoded and live-filtered.**
   `build_leaf_data` pushes only effective-live decoded postings into
   `TermPostings::postings`, so `terms[0].postings.len()` is available without a
   dictionary access, an estimate or a second postings pass.
3. **Historical guard evidence** (`docs/pr-artifacts/pr-15h-a/performance.md`):
   100K rare and 100K absent were `A_FASTER` at every paired ratio, as was 10K
   rare, while both 100K common lanes were `B_FASTER`. A2 takes that qualified
   result as the regression to avoid, not as a causal explanation.

## Frozen hypothesis

Below `H_A2_MIN_POSTINGS = 8_192` decoded, live-filtered postings, run the exact
original accepted eligible branch; at or above it, run the historical linear
helper. The gate is fixed before measurement and is not derived from K, corpus
size, selectivity estimates or the request.

## Optional profiler

`DIAGNOSTIC_PROFILE_UNAVAILABLE` (not run). The approved source-level facts were
sufficient for the hypothesis; profiling is explicitly optional and is not an
acceptance substitute.

## Bounded post-campaign diagnostic (not acceptance evidence)

The same sealed arm binaries and indexes were queried directly, alternating A/B
through one long-lived adapter process per arm:

```
absent 100K: A=244904ns B=427806ns ratio=1.747
rare   100K: A=260504ns B=440157ns ratio=1.690
medium 100K: A=21060479ns B=20352368ns ratio=0.966
common 100K: A=52724924ns B=48543158ns ratio=0.921
```

The below-gate sparse lanes still regress even though the dispatch source routes
them to the original eligible branch. **No causal attribution is claimed**
(binary layout/inlining/codegen was not established). The frozen, qualified
campaign remains the binding verdict; this probe merely confirms it is
reproducible on the same artifacts. Raw note:
`target/pr15h-a2/diagnostics/adapter-probe.txt`.

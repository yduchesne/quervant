# Benchmark acceptance and result preservation

## Current decision and implementation status

The maintainer clarified this contract on 19 November 2026: **run the current benchmarks through the new framework and preserve the results as a new baseline. Historical results are useful when available or faithfully recoverable; their absence does not block completion. A legacy-versus-new execution comparison is not a required proof.**

This decision supersedes the earlier fresh legacy-versus-new comparison proposal and the former blanket requirement to recover missing historical T6/micro/PR15D inputs before BM-09 could close. Do not execute replacement legacy runs to satisfy that superseded proposal. Repeating an old program today creates a new observation; it does not reconstruct a lost past measurement.

The Linux/WSL2 host compatibility correction is implemented alongside this document. The explicit current-baseline acceptance profile, fresh retained runtime authorization, proportional-history reporting and complete automatic result preservation described here still require implementation. Their concrete instructions are in [BM09_COMPLETION_PLAN.md](BM09_COMPLETION_PLAN.md). This document does not claim that current benchmark acquisition or BM-09 closeout has run.

## Performance comparisons are proportional

A and B are the baseline and treatment variants or engines **within one run**. Compare B with A using that study's declared estimator, controls and uncertainty. For a lower-is-better metric, B/A = 0.80 means a 20% reduction; B/A = 1.10 means a 10% increase. For a higher-is-better metric, the gain direction reverses. Preserve paired/interleaved schedules and existing estimator definitions.

Across runs, compare those within-run effects. A previous 20% latency reduction and a current 10% reduction means that B's advantage narrowed by 10 percentage points. Never compare previous A with current A, previous B with current B, absolute A-minus-B differences across runs, or absolute legacy-runner/new-runner timings to infer a performance change.

Keep raw absolute measurements so the proportional results can be checked. Human-facing reports lead with baseline, treatment, metric direction, proportional gain/loss, applicable uncertainty and qualification status. Do not invent confidence intervals or significance claims for the descriptive PR15D method.

Environment differences do not automatically invalidate proportional comparisons across runs. Record actual host/platform/configuration and source identities. Relative comparisons reduce environmental dependence but do not eliminate it: a platform can affect A and B differently. Where environment and code both differ, a changed proportional effect is observable, but its cause cannot be attributed solely to code. Matching metric definitions, workload coordinates, arm roles and estimators remains necessary.

Current collection supports native Linux and WSL2. Both retain Linux filesystem, capability, CPU-affinity, distinct-core and readiness requirements. WSL2 is recorded as WSL2; a run cannot switch hosts after approval. Native Windows collection has not been implemented. Authenticated historical Windows-derived proportional results may still be displayed with their platform metadata.

## Primary acceptance: valid current results

Execute a complete current run for each migrated family: retained-key and Quervant/Tantivy/Lucene. Preserve the existing workload, source pins, oracle, measurement boundaries, samples, controls, statistical methods and stop rules. Verify current raw data, provenance and calculations independently. No second acquisition through the legacy runner is required, and old/new analyzer equivalence is not the primary acceptance gate.

Use an explicit versioned `current-baseline-v2` execution/acceptance profile. Keep existing v1 readers, historical archive identities and their stricter acceptance semantics unchanged. V2 retained execution uses a newly observed current runtime freeze and independent G0. Its explicitly marked backend compatibility receipt may use the frozen helper’s required locator in a new owned checkout, as specified by the plan; it must never be described as recovery of the missing historical T6, overwrite an existing receipt, or satisfy the v1 historical prerequisite.

Separate baseline validity from adopting an optimization policy. Complete, independently verified current A/B observations and their proportional results can establish the new baseline even if a historical memory/micro input needed for an optimizer-selection policy is unavailable. In that case the report must say the policy is not derivable, select no arm and make no adoption claim. It must not relabel incomplete policy verification as the existing full `VERIFIED_REAL` result. The implementation plan defines the narrower, explicit baseline-verification scope. Invalid current measurements, failed controls or incorrect calculations remain failures.

## Historical data: use what is supportable

| Available evidence | Required treatment |
| --- | --- |
| Authentic raw observations and required method inputs | Recompute their within-run effects, then compare compatible proportional effects with the current run. |
| Authentic original derived result with an explicit ratio, but raw inputs absent | Show the original effect as `AS_REPORTED`; identify the source and disclose that rederivation is unavailable. |
| Deterministic source receipt or derived result recoverable from authentic source/input bytes | Recover it and verify the pinned identity; do not call this recovery of missing measurements. |
| Missing original samples or required historical input after the bounded search | Record `UNAVAILABLE` and continue with current results as the new baseline. |
| Present malformed, unauthenticated or inconsistent historical candidate | Record `INVALID` or `UNVERIFIED`; exclude it from quantitative history. Resolve any implications for current-source correctness separately. |
| Same metric/arm roles/estimator cannot be established | Mark `NOT_COMPARABLE`; do not invent a conversion or cross-run effect change. |

Historical availability is a disclosure, not a universal PASS prerequisite. Do not fabricate past samples, change archive digests, label fresh data historical, or keep searching indefinitely for absent files. Do not silently discard a verified analysis defect merely because it was found while examining history: a defect affecting current calculations still blocks current acceptance.

## Complete results in a committable path

The canonical repository location is:

```text
benchmark-results/baselines/<baseline-uuid>/
```

This replaces the unimplemented comparison-oriented destination in the superseded proposal. A baseline UUID groups the two family run UUIDs. The measured source revision and the later evidence commit are separate identities.

Preserve an ordinary directory, automatically, with complete raw observations, controls/readiness, frozen protocols, source/build/host identities, G0/QA evidence, original qualification records, analysis, proportional reports, historical availability and every policy input actually used. Preserve missing-input and partial-run states honestly. No executable ZIP, manual artifact transfer, temporary path or expiring CI URL is the delivery contract.

Checkpoint immutable evidence after each acquisition unit, before a later analysis/policy/acceptance failure can lose it. Final publication writes one complete manifest of relative member paths, byte lengths and SHA-256 digests. Existing preserved members cannot be overwritten. Build trees, executables, indexes, caches and deterministically reconstructible corpus payloads stay outside Git; retain the reconstruction recipe and expected corpus hashes. Runtime credentials and entire environment dumps must not be exported.

Original sealed bytes remain unchanged. Portable replay uses a separate transport record and the plan's fixed path mapping; it does not rewrite or reissue the original attestation. A completed baseline must replay from Git in a different checkout without access to the producer's target directory, private HOME or original corpus, and without new timing, adapter builds or services. The existing fifteen-member derived qualification bundle alone does not meet this requirement.

## Completion

BM-09 completion under this amendment requires both complete current family runs, current-run correctness and independent baseline verification, applicable local/hosted QA, genuine current execution approval, complete committable preservation, clean-checkout replay and independent review. Historical absence and a disclosed historical-policy-input limitation do not themselves block a valid new baseline. Keep benchmark validity, optimization-policy adoption and historical availability separate in the report.

No merge, destructive legacy retirement, measured improvement or completed benchmark run is claimed by this documentation or the host compatibility patch.

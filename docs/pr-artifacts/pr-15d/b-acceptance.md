# PR 15D-B — acceptance checklist

**Current disposition: `PENDING REVIEW` / partially `BLOCKED`.**

No item below may be marked complete on the strength of a local test alone.

| # | Checklist item | State | Evidence |
|---|---|---|---|
| 1 | A1 prerequisite (PR #79) verified | **PASS** | `b-preflight.md`; source lock `8caca76…`; run `41124428333` `pr15d-adapters` = success |
| 2 | No production or frozen contract diff | **PASS** | diff limited to `ci.yml`, new workflow, `smoke.py`, `test_pr15d.py`, `benchmarks/pr15d/README.md`, `docs/pr-artifacts/pr-15d/**` |
| 3 | `ci.yml` only had the comparative job removed | **PASS** | deletion-only diff; `git grep pr15d` empty; job set `rust, msrv, rustfs` |
| 4 | Comparative workflow path + manual triggers verified | **PASS (static)** | `ComparativeWorkflowContractTests`; YAML parse of both files |
| 5 | Smoke genuinely 10K | **PASS (static + local execution)** | `comparative-smoke` passes no `--sizes`; default selector is `[10000]`; default invocation prints exactly one `n: 10000` line locally |
| 6 | On-demand full genuinely 10K/100K for all engines | **PASS (static + local execution)** | `--sizes 10000,100000` + all three adapter commands + `corpus/oracle.py` in the full job; executed locally end-to-end for both sizes (see `b-ci.md`) |
| 7 | Wrapper/locks checks preserved | **PASS** | `sha256sum -c A1-CHECKSUMS.sha256` before `./gradlew` in both jobs; T07 asserts ordering |
| 8 | No timed CI | **PASS** | T06: no `run.py`, no idle flag, no qualified artifact in either workflow |
| 9 | Both actual CI modes PASS | **BLOCKED (X43/X42)** | `gh` token invalid; no dispatch or PR observation possible |
| 10 | stable/MSRV/RustFS and ≥85% coverage PASS on this head | **PARTIAL** | local stable+MSRV fmt/clippy/tests/doc/bench PASS and coverage 92.31% lines (`fail-under-lines 85` exit 0); `rustfs` real-service suite and exact-head CI still pending (X40) |
| 11 | Explicit host + operator idle attestation | **PASS** | operator attestation quoted verbatim in `b-trials.md`; window `2026-10-30T22:00:25Z`–`22:41:08Z` |
| 12 | 3/3 per-engine qualified trials | **PASS** | 9/9 original engine-trials retained, 32 lanes × 20 samples each, 54/54 contention records clear |
| 13 | Original validator PASS | **PASS after approved amendment** | pre-amendment run exited 2 (`index_bytes_inconsistent`, Tantivy only, preserved in `validation-initial.json`); post-amendment `validate.py` exit 0 `QUALIFIED`, 0 errors, 0 unqualified |
| 14 | Aggregate reproducible | **PASS** | aggregator-generated `pr15d-qualified.json` + `qualification.md`; byte-identical re-derivation; 108 statistics matched an independent recomputation; `verify_aggregate` → `[]` |
| 15 | No unsupported metrics or scored comparisons | **PASS** | scored lane stays `SEMANTICALLY_NONCOMPARABLE`, no scored ratio; RSS/CPU/allocation `NOT_MEASURED`; index-size variation published descriptively with no parity threshold |
| 16 | Source reviewer ACCEPTED | **PENDING** | no reviewer |
| 17 | Maintainer merge approved | **PENDING** | no merge attempted |

## Reviewer focus (source review)

1. `ci.yml` — confirm the diff is deletion-only and the surviving jobs match
   `main` byte-for-byte above the boundary.
2. `comparative-adapters.yml` — confirm the `paths` list is exactly the two
   authorized entries, the two `if:` guards match the matrix, the checksum step
   precedes Gradle, and permissions stay `contents: read`.
3. `smoke.py` — confirm `parse_sizes` cannot widen beyond `SIZES`, the default is
   still `[10000]`, and per-size summaries keep one line per selected size.
4. `test_pr15d.py` — confirm no existing assertion was weakened; the new guards
   are additions only.

## Honest summary

The CI restructuring and the bounded 10K/100K correctness interface are
implemented and covered by deterministic tests. The three-engine campaign was run
once in an attested window on a clean tree (`c9e982f…`). The original validator
rejected it on a Tantivy-specific `index_bytes` determinism invariant; an
approved methodology amendment (`ffbd4b3…`) reclassified physical index size as a
descriptive measurement, preserving every per-trial validity check, and the
**same untouched measurements** then validated `QUALIFIED` and aggregated into a
reproducible report. Quervant is reported as substantially slower, unaltered.

The PR is **not** complete: exact-head GitHub CI and independent acceptance
review remain outstanding.

## Methodology fixup status (PR #81, P0–P6)

Independent review found two timing/ingestion defects and two evidence gaps. The
fixup plan's implementation work is complete; the acceptance gates it adds are
not.

| Item | State |
|---|---|
| `engine_ns` includes stored-`doc_id` materialisation on all three adapters | **DONE** — `b-methodology-fixup.md` P1, FIX-T01–T05 |
| Tantivy document preparation moved outside the ingestion timer | **DONE** — P2, FIX-T14/T15 |
| Derived `index_ns + commit_ns` primary ingestion metric (checked sum) | **DONE** — FIX-T27/T19 |
| Physical-sort disparity disclosed; no equivalence claim | **DONE** — `sort_physical_keys`, FIX-T12/T13 |
| Old campaign preserved byte-identically and labelled superseded | **DONE** — `diagnostic-v1/` + `qualification-v1-superseded.md`, P0 |
| Deterministic evidence packager | **DONE** — `package_evidence.py`, 18 tests |
| Supplemental CPU/RSS probe | **IMPLEMENTED, NOT EXECUTED** — `resource_probe.py`, 29 tests; `b-resource-report.md` is `BLOCKED-ATTESTATION` |
| New corrected-methodology campaign | **BLOCKED-ATTESTATION (X38)** — no new human attestation for a new window |
| New validator/aggregate on corrected measurements | **BLOCKED** — depends on the campaign |
| Exact-head CI (`rust`, `msrv`, `rustfs`, comparative smoke/full) | **DEFER (X48)** — GitHub token invalid; nothing pushed |
| Independent reviewer acceptance | **PENDING** |

**Important:** the currently published `pr15d-qualified.json` and
`qualification.md` were produced under the superseded timing definition (they omit
stored-`doc_id` materialisation from `engine_ns`). They are retained only as
historical diagnostic evidence and must not be quoted as a corrected comparison.
They will be replaced, by `aggregate.py` only, after a new qualified campaign.

## Corrected-methodology campaign result (P6/P7)

| Item | State |
|---|---|
| Campaign on `40a9c26` in the attested MSI window (00:55:44Z–01:33:18Z) | **DONE** — exit 0, 3/3 trials/engine, 54/54 contention clear |
| `validate.py` | **PASS** — `QUALIFIED`, 0 errors, 0 unqualified |
| `aggregate.py` + `verify_aggregate` + 108 independent checks | **PASS** — byte-identical re-derivation, 0 discrepancies |
| Resource probe (18/18 `MEASURED`, cpu_target, clear contention) | **PASS** — separate process diagnostics only; allocations `NOT_MEASURED` |
| Evidence package | **BUILT, NOT PUBLISHED** — `BLOCKED_SENSITIVE_CONTENT` (X28, absolute paths; raw bytes deliberately not rewritten) |
| Superseded v1 report archived byte-identically | **PASS** — `diagnostic-v1/` + `qualification-v1-superseded.md` |
| Exact-head CI | **DEFER (X48)** — token invalid, nothing pushed |
| Independent reviewer acceptance | **PENDING** |

**Overall: `LATENCY-QUALIFIED / ACCEPTANCE-BLOCKED`.** No merge, no `DONE`
marker, no parity claim, no statistical-significance claim.

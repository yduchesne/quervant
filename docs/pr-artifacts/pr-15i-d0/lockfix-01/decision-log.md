# PR 15I-D0 lockfix-01 — decision log

All entries record the observed trigger, the authorized action, the prohibited
action not taken, the affected gates and the owner of unresolved decisions.

## FX-01 — acknowledged docs-only successor

| Field | Value |
|---|---|
| Trigger | `PARENT_MAIN = 4606f92e32f7d7e2419ad9a52888910747c1a44b`; `HISTORICAL_BASE` is an ancestor; complete diff is the four PR #92 docs paths; protected paths identical |
| Action | continue from `PARENT_MAIN` |
| Not taken | re-basing historical evidence, importing PR #92 into historical reports |
| Evidence | `preflight.md`; `git diff HISTORICAL_BASE..PARENT_MAIN` |

## FX-02 / FX-03 — minimal lock correction

| Field | Value |
|---|---|
| Trigger | `cargo generate-lockfile` produced a broad refresh (unrelated `itoa`, `smallvec`, `syn`, `unicode-*` bumps); offline Cargo resolution produced exactly `lz4_flex 0.11.6` + `twox-hash 2.1.5` and one `quervant-core` edge |
| Action | discard the broad probe; commit only the minimal mechanically validated lock; build `--locked` twice |
| Not taken | hand-edited lock, unrelated upgrades, manifest or feature change, non-locked benchmark acceptance |
| Evidence | `compatibility-lock-diff.md`; local `lock-probe-broad.diff`; `lock-diff-proof.json`; two locked builds with stable lock SHA |
| Rule | `FX-02`, `FX-03` |

## FX-06 — exactly two scratch imports

| Field | Value |
|---|---|
| Trigger | Rust name resolution requires `use super::d0_probe;` in `search/unified.rs` and `search/execute.rs` |
| Action | authorize exactly those two scratch-only insertions; independent byte proof and negative tamper tests |
| Not taken | a third import, moving an import, any non-instrumented source byte change, production instrumentation |
| Evidence | `source-proof.md`; `test_source_proof` tamper tests; real `VERIFIED` proof |
| Rule | `FX-06` |

## FX-08 — new protocol identity

| Field | Value |
|---|---|
| Trigger | the measured baseline changed from `HISTORICAL_BASE` to `COMPAT_BASE`; old/new evidence must not be confusable |
| Action | new schema `pr15i-d0-attribution-lockfix-v1`; `base_sha = COMPAT_BASE`; `historical_base_sha` and `parent_main_sha` provenance fields; strict consumers rebound atomically |
| Not taken | accepting both identities, reusing the old schema, changing lanes/sampling/stages/thresholds |
| Evidence | `protocol_v1.json`; `run.validate_protocol`; `verify.validate_protocol`; old/mixed rejection tests |
| Rule | `FX-08` |

## FX-10 / FX-11 — additive evidence only

| Field | Value |
|---|---|
| Trigger | historical `target/pr15i-d0/` evidence and the old D0 branch exist |
| Action | new branch and worktrees; new `lockfix-01` output directories; preserve every failed/partial attempt |
| Not taken | overwriting a sealed or partial directory, rewriting historical reports, deleting failed raw data |
| Evidence | old D0 HEAD `67467a1…` unchanged; historical hashes in `historical-freeze.json` |

## Scoped failures preserved (FX-12 / FX-14)

| Attempt | Disposition | Cause |
|---|---|---|
| historical canonical `canonical-three-engine-01` | historical BLOCKED/incomplete | stale lock |
| historical paired build `build-01` | historical BLOCKED | stale lock |
| `lockfix-01/paired/unbatched-01` | partial, preserved | tooling defect before any sealed sample |
| `lockfix-01/paired-02/unbatched-01` | partial, preserved | Q/P index-path mapping defect |
| `lockfix-01/vertical-slice-01` | partial, preserved | affinity check raced `taskset` fork/exec |
| `lockfix-01/vertical-slice-02` | partial, preserved | parameter/list shadowing in the slice helper |
| broad lock probe | discarded, preserved | unrelated package refresh |

Each defect was fixed in tooling **before** a sealed measurement existed. The
final measurements use the frozen tooling commits recorded in `preflight.md`.
No threshold, schedule, sample count or kernel was changed to obtain a pass.

## FX-15 — canonical line

| Field | Value |
|---|---|
| Trigger | canonical PR15D run is executed from the clean `COMPAT_BASE` worktree |
| Action | run the unmodified harness, validator and aggregator; publish only a `QUALIFIED` result |
| Not taken | changing the harness, dropping an engine, promoting historical ratios |
| Evidence | `canonical-three-engine.md` |
| Status | recorded after the run |

## FX-16 — external publication

| Field | Value |
|---|---|
| Trigger | local GitHub token is invalid and no push authorization is assumed |
| Action | record a local branch/commit handoff; no PR number or CI pass is claimed |
| Not taken | force-push, permission bypass, fabricated PR |
| Status | `CI_PENDING`, `REVIEW_PENDING`, merge not done |

## FX-18 — completion state

The final completion state, per-gate statuses, QA results and next human decision
are recorded in `execution-status.md`. D0 still does not authorize PR 15I-D1, an
optimization, a merge or a release.

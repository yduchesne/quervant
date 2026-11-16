# BM-06 — Design and closed contracts (pre-implementation correctness gate)

Status: pre-implementation artifact, written **before** any production edit.
Baseline: `main` = `f9125d2c4e95362511f568489de4b06d6236beaf` (BM-05 PR #106 merged),
verified equal to `origin/main` and the merge base on a clean tree.

Authorities: `AGENTS.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`,
`docs/benchmarking/*`, BM-01 receipt schema, BM-02–BM-05 implemented contracts.

## 1. Scope and dominant invariant

BM-06 adds one dependency-bound, independently checkable **A→B→C→D→E** chain for a
BM-03 sealed **synthetic** run, reusable framework/source QA evidence, durable
completion receipts and an immutable logical snapshot.

A published `simulated` qualification refers to exactly one verified set of sealed
source bytes, frozen analysis/policy inputs, verifier/source identities, exact QA
rosters and successfully completed gate dependencies. Any covered byte change
prevents reuse and/or invalidates acceptance. A `pass` string is never sufficient.

Non-goals: real timing, adapter launch, host readiness, A/A, historical verdict
mutation, public schema change, CLI activation, credential work, merge.

## 2. Trust boundary

| Anchor | Supplied by | Verified by |
|---|---|---|
| `expected_source_set_digest` | operator/CI/test fixture | fresh roster enumeration + raw byte hashing |
| `expected_profile_digest` | operator/CI/test fixture | `open_regular_beneath` + canonical read + `content_digest` |
| `expected_framework_qa_digest` | operator/CI/test fixture | canonical read of `<gate>-evidence.json` + `content_digest` |
| `expected_source_qa_digest` | operator/CI/test fixture | same, source gate |

Digests computed from the same untrusted file inside the same invocation are **not**
anchors. BM-06 tests use `tests/fixtures/qualification/trust-anchors.v1.json`
(deliberately outside the source roster). L2 QA records are `SIMULATED_ONLY`.

## 3. Closed record shapes

All persisted documents: strict JSON, closed field set, `schema_version=1`, UTF-8
without BOM, no duplicate keys / NaN / Infinity, canonical payload + exactly one
trailing newline, digest = `content_digest(document)` (no newline). Raw seal bytes
use a raw `sha256:` of the file bytes (`seal_raw_digest`), never a canonical JSON
digest. Every document ≤ 1 048 576 bytes.

### 3.1 `synthetic-qualification-profile.v1.json`

`kind, schema_version, profile_id, profile_version, evidence_origin,
qualification_scope, required_gates, required_verifier_checks,
framework_qa_roster, source_qa_roster, max_document_bytes`.

Normative values: gates `admission, analysis, verification, framework-qa,
source-qa, acceptance, attestation`; verifier checks `VC-01-SCOPE …
VC-09-POST-READ-INTEGRITY`; framework roster `python-contracts, python-mutations,
python-vertical`; source roster `rust-clippy, rust-coverage, rust-format,
rust-msrv, rust-stable, rustfs-service`; `max_document_bytes=1048576`; profile
`profile_id=synthetic-framework`, `profile_version=1`, origin/scope
`synthetic`/`simulated`.

### 3.2 `synthetic-qa-evidence` and `synthetic-qa-check`

Evidence: `kind, schema_version, evidence_origin, qualification_scope, qa_gate,
profile_digest, source_set_digest, toolchain_id, checks[]` where each check is
`check_id, executed, status, failed, mandatory_skipped, evidence_digest`.
Toolchain literals: `python-3-12` (framework), `rust-1-85-and-1-98` (source).

Check record at `<qa_evidence_root>/<gate>/<check_id>.json`:
`kind, schema_version, qa_gate, check_id, evidence_origin, qualification_scope,
source_set_digest, toolchain_id, executed, status, failed, mandatory_skipped`.
Its canonical content digest equals `checks[].evidence_digest`; every scalar equals
the enclosing check. Exact roster only; extra/absent records are rejected.

### 3.3 `synthetic-sealed-admission-index`

`kind, schema_version, subject, evidence_origin, qualification_scope,
seal_raw_digest, freeze_digest, scenario_digest, protocol_digest, profile_digest,
source_set_digest, counts, files`.

`counts` = `controls_completed, treatments_completed, slots_completed,
lane_envelopes, synthetic_samples`. `files` sorted by path, each
`path, byte_length, raw_digest`, exactly the sealed `seal.files` list. No absolute
paths.

### 3.4 `synthetic-verification-assessment`

`kind, schema_version, status, experiment_id, run_id, evidence_origin,
qualification_scope, analysis_digest, policy_digest, source_seal_digest,
reference_id, check_ids` — the frozen BM-05 `VerificationAssessment` plus
kind/version. `check_ids` must equal the profile list.

### 3.5 `synthetic-acceptance-summary`

`kind, schema_version, subject, evidence_origin, qualification_scope,
profile_digest, source_set_digest, gate_receipt_ids,
framework_qa_evidence_digest, source_qa_evidence_digest, policy_decision_status`.
`gate_receipt_ids` exact sorted keys `admission, analysis, verification,
framework-qa, source-qa`.

### 3.6 `simulated-freeze-snapshot` (in memory only)

`kind, schema_version, subject, evidence_origin, qualification_scope,
profile_digest, source_set_digest, members`. `members` = first 13 durable members
sorted by path, each `{path, byte_length, digest}`.

### 3.7 `simulated-qualification-manifest`

`kind, schema_version, subject, evidence_origin, qualification_scope,
profile_digest, source_set_digest, freeze_snapshot, attestation_digest, members`.
`members` = all first 14 members sorted by path, including `attestation.json`.
No self-hash, no `manifest.json` member.

## 4. Durable member inventory (exactly 15)

Creation order: `admission-index.json`, `admission.json`, `analysis.json`,
`policy.json`, `analysis-receipt.json`, `verification-assessment.json`,
`verification.json`, `framework-qa-evidence.json`, `framework-qa.json`,
`source-qa-evidence.json`, `source-qa.json`, `acceptance-summary.json`,
`acceptance.json`, `attestation.json`, `manifest.json` (commit marker last).

Publication: exclusive `mkdir` of `<experiment>` then `<run>`, each file
`O_CREAT|O_EXCL|O_NOFOLLOW` + full write + `fsync`, directory `fsync`, canonical
`manifest.pending` (exclusive) + `fsync`, hardlink pending→`manifest.json`
(no replace), directory `fsync`, unlink pending, directory `fsync`. No repair, no
cleanup, no rename/copy fallback. Unsupported link/fsync/no-follow ⇒
`BM_NOT_IMPLEMENTED`.

## 5. Gate graph and exact upstream dependencies

| Receipt | Deps | Outputs | Bound inputs |
|---|---|---|---|
| `admission` | — | `admission-index` | `seal`, `protocol`, `workload`, `qualification-profile`, `scenario`, `source-set` |
| `analysis` | A | `analysis`, `policy` | `admission-index`, `analysis-profile`, `policy-profile`, `resource-observations`, `source-set` |
| `verification` | A, B | `verification-assessment` | `analysis`, `policy`, `source-seal`, `source-set` |
| `framework-qa` | — | `framework-qa-evidence` | `framework-qa-evidence`(digest), `qualification-profile`, `source-set`, `qa-toolchain` |
| `source-qa` | — | `source-qa-evidence` | `source-qa-evidence`(digest), `qualification-profile`, `source-set`, `qa-toolchain` |
| `acceptance` | A,B,C,F,S | `acceptance-summary` | `admission-index`, `analysis`, `policy`, `verification-assessment`, `framework-qa-evidence`, `source-qa-evidence`, `qualification-profile`, `source-set` |
| `attestation` | A,B,C,F,S,D | `freeze-snapshot` | `freeze-snapshot`, `source-set`, `qualification-profile` |

Dependency entry: `name == gate slug`, `gate == slug`, `receipt_id` = recomputed
receipt ID, `digest` = `content_digest(referenced receipt document)` (includes the
referenced `receipt_id`). All entries sorted by name; no extra/missing/cycles/
self/cross-run edges. Validator IDs `synthetic-<gate>` version 1 with
`source_digest` = pinned source-set digest. `qa_roster_digest` = profile digest on
F, S, D, E; `policy_digest` = policy document digest on B, C, D, E.

## 6. Reuse key (conceptual, represented by receipts)

`(experiment_id, run_id, source_set_digest, profile_digest, protocol_digest,
workload_digest, seal_raw_digest, freeze_digest, scenario_digest,
analysis_profile_digest, policy_profile_digest, resource_observations_digest,
framework_qa_evidence_digest, source_qa_evidence_digest, toolchain_identifiers)`.

`qualify_synthetic_run` checks the destination **before** deriving. A committed
destination delegates to the same loader; `REUSED_VERIFIED` only after fresh
anchor/byte/edge validation and replay. Incomplete destination ⇒
`BM_PUBLICATION_CONFLICT`; changed inputs at a committed destination ⇒
`BM_IDENTITY_INVALID`/`BM_PUBLICATION_CONFLICT`. Loader never calls BM-04 or BM-05.

## 7. Source roster algorithm

Deterministic closed roster, sorted, no symlinks, repository-root confined:

1. Git-tracked `*.py` beneath
   `benchmarks/quervant_bench/{config,evidence,host,execution,protocol,analysis,
   verification,qualification,tests}/`.
2. `.github/workflows/ci.yml`, `benchmarks/pyproject.toml`,
   `benchmarks/scripts/test-scripts.sh`.
3. Every `benchmarks/quervant_bench/config/schemas/*.json`.

Enumerated with `git ls-files -z` (argv, no shell) after verifying
`git rev-parse --show-toplevel` equals the resolved `source_root`. Any **untracked**
`.py` in those directories or untracked schema JSON fails closed
(`BM_UNSAFE_INPUT`). `.pyc`, `.benchmarks`, `target`, archives and output
artifacts are never members. `source_file_set_digest` hashes the exact set.

## 8. Typed failure boundaries

Preflight: wrong origin/scope ⇒ `BM_SCOPE_MISMATCH`; wrong run/experiment UUID,
bad anchors, forged edges/doc identity ⇒ `BM_IDENTITY_INVALID`; malformed/unknown
version ⇒ `BM_SCHEMA_INVALID`/`BM_SCHEMA_UNSUPPORTED`; missing pinned anchor ⇒
`BM_EVIDENCE_UNAVAILABLE`; missing file ⇒ `BM_FILE_MISSING`; unsafe root/symlink/
traversal/oversize/untracked ⇒ `BM_UNSAFE_INPUT`; collision/incomplete destination
or pending marker ⇒ `BM_PUBLICATION_CONFLICT`; unsupported filesystem primitives ⇒
`BM_NOT_IMPLEMENTED`; unexpected I/O defect ⇒ `BM_INTERNAL_ERROR` (never `pass`).
No new error codes, no clock leases, no retries, no auto cleanup.

## 9. Invariant → adversarial counterexample → module/test matrix

| ID | Invariant | Mutation (false-PASS attempt) | Modules | Tests |
|---|---|---|---|---|
| Q01 | synthetic/simulated only | forged `official` scope relabel | coordinator, contracts | SCOPE-01/02, E2E-01 |
| Q02 | A replays + binds seal/inventory | drop/alter/add/foreign sealed record, changed seal | admission | A-01…06, E2E-01 |
| Q03 | B is BM-04's exact output, bound to A | swapped candidate, mismatched digest/protocol | coordinator | B-01…03 |
| Q04 | C is BM-05's exact independent assessment | forged selection/CI, omitted VC id | coordinator | C-01…03 |
| Q05 | receipts legal gate/status/edges/digests | recomputed self-hash with a wrong-edge dependency | receipts | REC-01…09 |
| Q06 | framework/source/acceptance distinct | QA pass doc with `executed=false` / skipped | qa | QA-01…10 |
| Q07 | QA + source independently pinned | counterfeit QA self-digest, source/test/toolchain drift | identity, qa | QA-01, SRC-01…03 |
| Q08 | reuse only after fresh revalidation | mutate one dependency, attempt reuse | coordinator, publication | REUSE-01…10 |
| Q09 | exclusive, crash-aware publication | crash/collision/symlink/concurrent publisher | publication | PUB-01…09, PUBL-01…12 |
| Q10 | acyclic attestation/manifest | attestation claims manifest digest, self-hash | manifest | E-01…06 |
| Q11 | source/QA changes invalidate D/E | source byte mutated, analysis numerically identical | coordinator | REUSE-05…08 |
| Q12 | INCONCLUSIVE/baseline-only co-exist | promote to winner/real qualification | coordinator, contracts | POLICY-01…04 |
| Q13 | raw evidence unchanged; no redundant work | poison BM-04/BM-05 during valid reuse | coordinator | E2E-02, REUSE-01 |
| Q14 | no real acquisition, CLI untouched | invoke `run`/reserved verbs, real scope | cli (unchanged) | BOUND-01/02 |
| Q15 | bounds/closed shapes reject oversize/bool/null/dup | 1 MiB+ doc, duplicate key, `true` as int | contracts | CONTRACT-01…10 |
| Q16 | full production A→E, fault-injected | stage-specific failure at each transition | all | E2E-01/03, E2E-04…12 |

### 9.1 Plausible false-PASS mutations that must fail

- **Q02**: replace `seal.files` entry digest with a recomputed digest and rebuild
  a syntactically valid `seal.json` — replay/A must reject because the file bytes
  and expected inventory/identities no longer match.
- **Q05**: keep a valid `receipt_id` (recomputed over the whole payload) but point a
  dependency at another gate/run — semantic edge validation must reject.
- **Q06**: pin a QA document whose checks say `status=pass` but
  `executed=false`/`mandatory_skipped=1` — F/S/D must reject, not promote.
- **Q08**: re-run qualification against a committed destination after changing one
  source byte (analysis numerically identical) — E-ward invalidation, no reuse.
- **Q09**: crash after the hardlink but before pending removal — a present
  `manifest.pending` must never be reported as `SIMULATED_QUALIFIED`.
- **Q10**: upload a recomputed attestation whose dependency digests point at the
  manifest — the manifest algebra (attestation output = freeze snapshot) must reject.

## 10. Lifecycle / publication transitions

| Situation | Result | Files left |
|---|---|---|
| invalid scope/identity before writes | typed error | none |
| Gate A/B/C/QA failure before publication | typed error | none |
| success | all 15 members, manifest last | complete |
| collision with committed output | reuse only if all current dependencies match | prior output unchanged |
| collision with incomplete output | `BM_PUBLICATION_CONFLICT` | incomplete retained |
| crash at any of 14 writes | typed non-success | incomplete, no marker |
| crash after hardlink, before pending unlink | typed non-success or incomplete | marker+pending, loader rejects |
| two writers | one exclusive winner; loser conflict | loser writes nothing |
| mutated covered input after preflight | `BM_IDENTITY_INVALID` | no new manifest |

## 11. Decision-matrix expectations

D01/D02/D03/D04/D05/D06/D07/D08/D09/D11/D12/D14/D15/D20/D23/D25/D26/D29/D31/
D33/D37/D40/D42/D43/D46: pre-authorised, no human input required. Any trigger for
D13/D17/D19/D21/D22/D24/D27/D28/D30/D32/D34/D36/D44/D47/D48 is a hard stop for the
affected work and is reported, never improvised.

---

# RF06 independent-review fixup — pre-implementation correctness gate

Reviewed start head: `37b0d35ad63179f97be8e17120b8b01e6e8e16b2` (PR #107); review
`5924261766`, disposition `BM06_REVIEW_CHANGES_REQUIRED`; findings RF06-01 (Gate E
subject), RF06-02 (Gate D identities), RF06-03 (publication-window integrity).
Main merge base `f9125d2c4e95362511f568489de4b06d6236beaf`.

The authority is the **admitted BM-03 run plus independently pinned
source/profile/QA anchors**. Content-addressed self-consistency is necessary but
not sufficient. Only `qualification/coordinator.py` may change in production.

## FX06 invariant → function → adversarial test

| ID | Falsifiable statement | Function | Positive | Negative |
|---|---|---|---|---|
| FX06-01 | loaded manifest subject == independently read Gate A `index["subject"]` | `_verify_committed` (E) | `F06-E-01` | `F06-E-02` |
| FX06-02 | embedded snapshot subject == admitted subject (experiment/run/protocol/workload) | `_verify_committed` + `verify_freeze_snapshot` | `F06-E-01` | `F06-E-02`, `F06-E-03` |
| FX06-03 | manifest/snapshot profile+source digests == context anchors | `_verify_committed` + `verify_freeze_snapshot` | `F06-E-01` | `F06-E-04` |
| FX06-04 | attestation bound to authoritative subject + actual reconstructed snapshot, acyclic | `verify_attestation_graph` (unchanged) + `verify_freeze_snapshot` | `F06-E-01` | `F06-E-02` |
| FX06-05 | Gate D summary subject == admitted subject (receipt subject alone insufficient) | `_verify_committed` (D) | `F06-D-01` | `F06-D-02`, `F06-D-03` |
| FX06-06 | Gate D summary profile/source == current anchors | `_verify_committed` (D) | `F06-D-01` | `F06-D-04`, `F06-D-05` |
| FX06-07 | existing Gate D IDs/policy/QA/graph checks retained | `_verify_committed` (D) | `F06-D-01` | existing `REUSE-06…10`, `REC-02…09` |
| FX06-08 | `SIMULATED_QUALIFIED` only after published bundle loaded, fully verified and equal to derived manifest/receipt/path | `qualify_synthetic_run` → `load_bundle` + `_verify_committed` | `F06-P-01` | `F06-P-02`, `F06-P-03` |
| FX06-09 | postpublication drift rejects without deleting output | `qualify_synthetic_run` | `F06-P-01` | `F06-P-02`–`P-04` |
| FX06-10 | valid reuse still `REUSED_VERIFIED` with no BM-04/05 calls | `qualify_synthetic_run` reuse path | `F06-P-05`, `REUSE-01` | poisoned producers |
| FX06-11 | output remains synthetic/simulated; `run` still exit 77 | unchanged surfaces | `F06-P-01`, `SCOPE-01/02` | `BOUND-01` |
| FX06-12 | fixtures re-frozen from final roster; stale anchors fail closed | `identity`, `qa` | `F06-A-01` | `F06-A-02`, `SRC-02` |
| FX06-13 | interrupted publication remains fail-closed, never repaired | publisher (unchanged) | existing `PUBL-01…11` | `F06-P-04` |
| FX06-14 | gate result / local QA / CI / review reported separately | final report | report audit | CI unverified ≠ PASS |

## Expected typed failures

| Condition | Error | Field |
|---|---|---|
| D summary foreign subject | `BM_IDENTITY_INVALID` | `acceptance-summary.subject` |
| D summary stale profile/source | `BM_IDENTITY_INVALID` | `acceptance-summary.profile_digest` / `.source_set_digest` |
| E manifest foreign subject | `BM_IDENTITY_INVALID` | `manifest.subject` |
| E manifest stale profile/source | `BM_IDENTITY_INVALID` | `manifest.profile_digest` / `.source_set_digest` |
| E snapshot reconstruction mismatch | existing `verify_freeze_snapshot` identity rejection | `freeze_snapshot`/`members` |
| postpublication QA byte drift | existing canonical/identity error (`BM_UNSAFE_INPUT`/`BM_IDENTITY_INVALID`) | qa evidence path |
| postpublication sealed byte drift | existing replay/identity error | seal/evidence path |
| postpublication derived/loaded disagreement | `BM_IDENTITY_INVALID` | `manifest`/`attestation`/`output_directory` |

## Red-test construction rules

Forged bundles are produced by mechanically rebinding **all** descendants
(receipt self-IDs, acceptance output digest, attestation dependency/digest, freeze
snapshot members and digest, manifest attestation digest/members) so that
`publication.load_bundle` **succeeds** and only the missing trusted comparisons can
reject. The publication-window tests mutate a real temporary QA/sealed byte inside
`OsPublicationIO.hardlink_no_replace`, i.e. after the pre-publication guard and
before the manifest commit marker. No checked-in fixture is mutated; the global
cached qualified bundle is never rewritten.

Temporary intermediate re-freeze (see `qa-and-reuse-matrix.md` §7) is used only to
let the red tests reach the semantic seam; the final re-freeze occurs after the last
Python edit.

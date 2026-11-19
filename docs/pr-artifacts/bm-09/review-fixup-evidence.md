# BM-09 RF09-F1 — trust-boundary, acquisition-layout and publication fixup

Scope: `dev/bm09-real-qualification` (PR #110), starting head
`28a2952aa63306e3810d99d76aaa7d6067cc91e3`, main merge base
`a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b`.

This fixup is **implementation authorization only**. It is not an independent G0
approval, not a real-measurement authorization and not a parity waiver. No real
timed data was acquired, no engine was launched, no G0/approval record was
created for production, and no historical parity was approved.

## 1. Findings and corrections

| ID | Correction |
| --- | --- |
| RF09-01 | New `official/authorization.py` provides `VerifiedOfficialAuthorization` and the single production factory `open_verified_official_authorization(...)`, which validates an external approval record, re-reads the canonical authorization, re-runs `verify_g0_authorization` against an independently supplied digest and freshly observed identities. `require_verified_official_authorization(...)` revalidates the approval source, the authorization bytes and (for production) fresh observations at every entry point. `acquisition.*_invocations`, `admission.admit_*_real`, `verification.verify_official_study`, `coordinator.qualify_official_study`, `coordinator.reuse_or_conflict` and `publication.publish_official_bundle` now take `authorization=`. A parsed `OfficialFreeze` is rejected by type; `require_freeze` is shape validation only. |
| RF09-02 | `coordinator._require_qa` now compares the canonical QA document digest to `freeze.qa_framework_digest` / `freeze.qa_source_digest` in addition to source-set, roster, toolchain, check-ID, executed/status/failed/skipped checks with strict boolean rules. A coherently rehashed QA document that does not match the G0 pin fails. |
| RF09-03 | `historical.assess_required_historical_parity` is read-only and can no longer return `PASS`; caller rows plus a reviewer label yield at most `COMPARISON_COMPUTED_PENDING_REVIEW`. A new `VerifiedHistoricalParity` capability is created only by `open_verified_historical_parity(...)`, which requires a versioned equivalence mapping approved by an external approval record, authenticates the archive member bytes, checks the frozen original verifier digest, and **independently recomputes** every mapped metric (lower-middle median, nearest-rank p95/p99, total hits, ordered doc IDs) from the archived samples against the approved expected values and tolerances. `require_verified_historical_parity(...)` re-reads, re-audits and re-recomputes before Gate D. |
| RF09-04 | `acquisition.cross_engine_invocations` now writes/validates the backend at `raw_root/backend` (`--out`, `--run`, `validation.json`), reserving `raw_root` for official control artefacts, and refuses an existing or symlinked backend root. `admission.admit_cross_engine_real` consumes exactly that layout; there is no fallback to the flat legacy layout. |
| RF09-05 | `publication.publish_official_bundle` validates the complete `OfficialAnchors` set, the verified authorization, the manifest, the freeze snapshot, the 14-file member set and the seven-gate receipt graph **before** `destination_state` or any write. Missing/wrong anchors leave no destination. `validate_official_bundle_in_memory` is the non-persisting test seam. |
| RF09-06 | `admission.admit_cross_engine_real` / `admit_retained_key_real` no longer accept an `original_verifier`; they instantiate the trusted `OriginalVerifier` internally after verified G0 and check its source digest against `freeze.original_reference_verifier_digest` before invoking it. Test-only injection moved to `tests/official_support.py` private helpers that return `fixture_only=True` records rejected by production. |
| RF09-07 | The six generated `benchmarks/quervant_bench.egg-info/*` files were removed with `git rm --cached`; root `.gitignore` gained `**/*.egg-info/`. |

## 2. Red-before-green evidence

Red gate was executed on the unmodified `28a2952` production code. Selected
observations (full log under untracked `target/bm09-fixup/`):

| Case | Original observation |
| --- | --- |
| G0F-02 (retained-key factory) | accepted a bare `OfficialFreeze` and returned 14 invocations (T6 present) |
| G0F-02b (cross-engine factory) | accepted a bare freeze and returned the flat `raw_root` layout |
| G0F-03 (admission) | rejected only because the real verifier failed the fixture; the failure field was `original-verifier`, not `authorization` |
| LAY-01/02/04/05 | `cross_engine_invocations` returned flat paths; no backend exclusivity; existing/symlinked backend not checked |
| VERF-01/02/03 | an injected `StubVerifier` returned success through the public intake; no fixture-only record existed |
| PUBF-01 | with `anchors=None` the publisher **created the destination directory** and then raised |
| PUBF-03 | anchors copied from the manifest were accepted without any G0 record (no error raised) |
| QAF-02/03 | QA document digests were never compared with `freeze.qa_*_digest` |
| HPF-01 | a caller PASS row plus a reviewer label returned `PASS` |
| PKG-01..03 | six `egg-info` files tracked; no ignore rule |

## 3. Green gate

- Official suite: **259 tests OK** (`test_official_*.py`), including all new
  G0F/LAY/VERF/QAF/HPF/PUBF/PKG cases.
- Full Python suite in the pinned venv: **1,224 tests OK, zero skips**.
- Legacy: `pr15d/harness/test_pr15d.py` 83 tests with the **same pre-existing
  `test_t01` CI-job-list failure** reproduced on the `a5a8303` baseline (no PR15D
  file may change); `pr15i_d3_c/test_verify.py` keeps its pre-existing
  `dry-proof` module skip; contract inventory PASS; script suite **108 passed**.
- Rust: fmt (stable + 1.85), clippy (default, all-features, MSRV all-features),
  tests (all three command forms), `cargo doc`, `cargo bench --no-run` all pass;
  `cargo llvm-cov … --fail-under-lines 85` → **92.03% lines**.

## 4. Controlled synthetic QA re-freeze (one, after the final Python edit)

`benchmarks/quervant_bench/official/authorization.py` is new inside the already
rostered `official` directory (D57), so the BM-06 source roster semantics are
unchanged and only the digest chain was refreshed:

| Anchor | Before | After |
| --- | --- | --- |
| `source_set_digest` | `sha256:c9f07779…c814` | `sha256:606ebcc9…768d` |
| `framework_qa_digest` | `sha256:992eb159…72cd` | `sha256:c2f69f79…d762` |
| `source_qa_digest` | `sha256:910ddfcf…1b56` | `sha256:a41a4139…a902` |
| `profile_digest` | `sha256:9db01390…046c` | unchanged |

Only per-check `source_set_digest`, per-check `evidence_digest`, the two QA
evidence `source_set_digest` fields and the anchors were rewritten (canonical
JSON). Rosters, check IDs, statuses, toolchains and the profile were not touched.
A second `compute_source_set_digest` after the re-freeze equals the anchor, so the
freeze is stable (no second pass required).

## 5. Test-seam discipline

- `tests/official_support.py::fixture_authorization` builds a capability with
  `fixture_only=True`; every production entry point rejects it.
- `fixture_historical_parity` is fixture-only and rejected by production Gate D.
- `production_shaped_authorization` and `historical_parity_sandbox` build a
  **sandboxed external-approval simulation** outside the repository, clearly
  tagged TEST ONLY. They let the real production path (including the real pinned
  original verifier, which now accepts the fixture series) run end-to-end without
  any real authorization, measurement or engine launch.
- `qualify_fixture_graph_in_memory` returns `TEST_ONLY_GRAPH_VERIFIED` only, cannot
  publish and cannot run a backend.

## 6. Remaining blockers (unchanged)

| Gate | Status | Missing evidence |
| --- | --- | --- |
| Independent G0 authorization | **BLOCKED** | No operator/reviewer approval record or approved digest exists |
| Retained-key real L3 | **BLOCKED** | No `target/pr15i-d3-c/v3r3-freeze/freeze-receipt.json` (T6) |
| Cross-engine real L3 | **BLOCKED** | No G0, no `target/pr15d` corpus, no adapter binary set |
| Historical parity | **BLOCKED** | No authentic PR15D archive; D3-C replay and approved mapping absent |
| Official acceptance / closeout | **BLOCKED** | Depends on the above |
| Final-head CI | **UNVERIFIED** | GitHub API credentials invalid from this terminal (`gh` 401) |

No legacy path was retired, `v0.1-bench` is not COMPLETE and no performance claim
exists.

## 7. Disposition

`BM09_RF09_FIXUP_IMPLEMENTED_L1_L2_PASS_REAL_BLOCKED_READY_FOR_REVIEW`

---

# RF09-F2 fixup — verified admission, executed QA artifacts, complete historical parity

Scope: `dev/bm09-real-qualification` (PR #110), starting head
`42d86f082e09d98a7ac3a47f3891da595c84368b`, merge base
`a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b`.

Implementation authorization only. No real timed acquisition, no G0 approval, no
T6 freeze, no authentic historical archive and no merge.

## RF09-08 — verified production admission

| Change | Detail |
| --- | --- |
| Duplicate field | The duplicated `fixture_only` declaration on `AdmittedCrossEngine` was removed (D018). |
| New capability | `admission.VerifiedOfficialAdmission` (creation-sentinel guarded) binds study, authorization, raw-series digest, admission-index digest and pinned original-verifier digest; it refuses a fixture record. |
| Public factories | `admit_cross_engine_real` / `admit_retained_key_real` now return the capability and **require** a safe `source_root` (`BM_EVIDENCE_UNAVAILABLE` otherwise), verify the source set, verify the pinned verifier digest, run the real `OriginalVerifier` internally, then re-hash the inventory before issuing the capability. |
| Re-admission | `admission.reverify_official_admission(...)` rejects any non-capability (including `dataclasses.replace(fixture, fixture_only=False)`), re-runs the public factory over the bound raw roots, and compares all four digests before returning the freshly verified record. |
| Coordinator | `qualify_official_study` accepts `VerifiedOfficialAdmission`, re-admits at Gate A and uses only the fresh record downstream. |
| Gate C | `verify_official_study` refuses a production record without the matching capability, so a raw `Admitted*` plus plausible G0 cannot manufacture `VERIFIED_REAL`. |
| Fixture path | `qualify_fixture_graph_in_memory` is unchanged: fixture capability, in-memory only, `TEST_ONLY_GRAPH_VERIFIED`, never publishes. |

## RF09-09 — executed QA artifacts

New read-only module `official/qa_evidence.py`:

- Literal, immutable `GATE_CHECK_EXECUTORS` map covering exactly the 15 framework
  and 18 source roster IDs (asserted at use).
- Exact inventory: `framework-qa/<id>.json`, `source-qa/<id>.json`,
  `logs/framework-qa/<id>.log`, `logs/source-qa/<id>.log` — 66 members, no extras,
  no symlinks/hardlinks, bounded (64 KiB record, 8 MiB log, 384 MiB total).
- Canonical closed records (`official-executed-qa-check`) binding source commit,
  source set, frozen toolchain, frozen `(executor, job_name)`, exact hosted run URL
  or operator identity, `executed is True`, `status=pass`, integer zero
  failed/skipped/exit, exact log path and raw log SHA-256.
- `content_digest(record) == summary.checks[i].evidence_digest` and
  `document_digest(summary) == freeze.qa_*_digest`, so a coherently rehashed record
  or log still fails the unchanged G0 pin.
- `verify_executed_qa_evidence` returns the 66-member raw snapshot;
  `reverify_executed_qa_evidence` re-reads everything and requires an identical
  snapshot.
- Coordinator integration: `qa_evidence_root` is mandatory for production, the
  first read happens before any QA receipt, the second immediately after Gate C and
  before Gate D, and the third immediately before publication. Watchdog tests prove
  each barrier.

## RF09-10 — complete historical parity

`official/historical.py` now enforces the frozen six-dimensional PR15D contract:

- `expected_cross_engine_parity_coordinates()` returns the exhaustive
  lexicographically ordered 288 cells × 5 metrics = **1,440** coordinates, built
  only from literal constants.
- `_validate_mapping` requires exactly those 1,440 rows in that exact order with
  deterministic row IDs (`engine-t{trial}-n{N}-{class}-k{K}-{regime}-{metric}`),
  rejects duplicates, unknown/out-of-domain locators, extra rows and reordering, and
  validates the exact archived member inventory (`run.json` + 9 trial files).
- `process_cold` is accepted through exact frozen membership (the legacy literal
  contains an underscore, so the generic public-slug rule does not apply to the
  regime field or to derived row IDs).
- `total-hits` must be a nonnegative built-in integer (zero is required for the
  `absent` class); duration metrics must be positive built-in integers; `doc-ids`
  must be ordered, unique `dNNNNNNNN` identifiers (empty allowed).
- `_recompute_row` validates the archived lane id, regime, N, K, `field` and `term`,
  requires twenty positive samples, and recomputes p50/p95/p99 at nearest-rank
  indices 9/18/**19**. Archived `total_hits`/`doc_ids` are cross-checked against the
  independent closed-form corpus oracle before they are trusted.
- The approval record, mapping digest, archive member digests and original-verifier
  digest are rechecked before and after recomputation and again at Gate D.
- Retained-key parity still returns `BM_EVIDENCE_UNAVAILABLE` (no authentic
  T7/F2 policy inputs), and `POLICY_NOT_DERIVABLE` still blocks Gate C/D.

## Red → green

Red was captured on `42d86f0` (logs under untracked `target/bm09-rf09-f2/`):

| Case | F1 observation |
| --- | --- |
| ADMF-03/04 | a `dataclasses.replace(fixture_record, fixture_only=False)` copy entered the production coordinator; no capability type existed |
| ADMF-12 | production admission accepted `source_root=None` |
| QAE-04/09/18 | `official.qa_evidence` did not exist and `qualify_official_study` had no `qa_evidence_root`, so QA receipts rested on summary digests alone |
| HPC-02 | a one-row approved mapping produced `VerifiedHistoricalParity` (PASS) |
| HPC-10/11 | a frozen `process_cold` regime was rejected by the public-slug rule and `total-hits=0` was rejected as a non-positive integer |
| HPC-14 | p99 at index 19 was correct in F1; the surrounding matrix rules were not |

Green: **300 official tests** (was 259) and **1,265 full Python tests**, zero skips.

## Result summary

| Item | Result |
| --- | --- |
| Source set digest | `sha256:57eb22fa7c02e3230ac1cf649331d702f35b06a232853f123137dd2fce2f2b70` |
| Framework QA digest | `sha256:cc7f704ef753e70d2803aa3aff28fd898e245f5a8686088aa70e5e11afd32cdb` |
| Source QA digest | `sha256:7dab23a706976927ce40bfc98772123c6073519f9d7b42292d06ac7caaf1613e` |
| Profile digest | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` (unchanged) |
| Rust | fmt/clippy/tests stable+MSRV, doc, `bench --no-run` PASS; coverage **92.04% lines** |
| Legacy | `test_pr15d.py` 83 tests with the same pre-existing `test_t01` failure (baseline-reproduced); D3-C verifier suite keeps its pre-existing skip |
| Real L3 / historical parity / closeout | **BLOCKED** (no G0, no T6, no authentic archive, no cross-engine corpus) |
| Final-head CI | **UNVERIFIED** (`gh` returns HTTP 401) |

Disposition: `BM09_RF09_F2_IMPLEMENTED_L1_L2_PASS_REAL_BLOCKED_READY_FOR_REVIEW`.

---

# RF09-F3 fixup (2026-11-17) — standalone Gate C provenance and deterministic QA-root tests

Scope: `dev/bm09-real-qualification` (PR #110), starting head
`619562b2b80d884a44c79cf88b88192a33837743`, merge base
`a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b`. Two findings only: RF09-11 and RF09-12.

Implementation authorization only. No timed benchmark, engine launch, G0/T6
approval, historical parity, retirement or closeout.

## RF09-11 — Gate C must consume freshly re-admitted evidence

The public production `verification.verify_official_study` previously checked the
capability digests and the on-disk inventory but then recomputed statistics from the
**caller-provided** `admitted.trials` / `admitted.slots`. A coherently mutated
in-memory record with unchanged raw bytes was accepted as `VERIFIED_REAL`.

Correction (production code: `official/verification.py` only):

1. The admitted object must be exactly `AdmittedCrossEngine` or
   `AdmittedRetainedKey`, and `authorization` must be a
   `VerifiedOfficialAuthorization`.
2. The production/fixture **mode comes from the verified authorization**, not from
   the caller's `fixture_only` flag; a mismatch is `BM_UNSAFE_INPUT`
   (`field_path="admission"`).
3. Production mode additionally requires `VerifiedOfficialAdmission` and a
   `source_root` (`BM_EVIDENCE_UNAVAILABLE`, `field_path="source_root"`), then calls
   the existing `admission.reverify_official_admission(...)`.
4. A new private `_require_exact_admitted_record(submitted, authoritative)` compares
   exact type and the dataclasses' complete recursive field equality (every nested
   trial, slot, campaign, control, inventory and metadata value). Any difference is
   `BM_IDENTITY_INVALID` with `field_path="admission"`, raised before RV-01.
5. RV-01..RV-10 then run against the freshly authenticated record only. Fixture mode
   keeps its existing bounded in-memory behaviour and still cannot publish.

No new capability, digest, cache, schema or bypass was introduced. The coordinator
now performs the pinned original verifier twice (Gate A and Gate C); this is
read-only re-validation, explicitly permitted, and no timing occurs.

## RF09-12 — deterministic QA-root tests (tests only)

`test_qae_20` depended on the workstation venv `target/bm09-venv`, which does not
exist on hosted runners; run #394 returned `BM_FILE_MISSING` where the test expected
`BM_UNSAFE_INPUT`/`BM_EVIDENCE_UNAVAILABLE`. Replaced with three deterministic
cases and no production change:

- `F3-QAE-20`: `REPO_ROOT` (existing, in-repo) → exactly `BM_UNSAFE_INPUT`.
- `F3-QAE-20B`: `REPO_ROOT/benchmarks` (existing, in-repo) → exactly
  `BM_UNSAFE_INPUT`.
- `F3-QAE-20C`: a guaranteed-absent child of the temporary root → exactly
  `BM_FILE_MISSING`.

The existing 66-member valid-root, symlink, log-tamper and reverify cases are
unchanged.

## Red → green

Red on `619562b` (`PYTHONPATH=benchmarks python -m unittest
quervant_bench.tests.test_official_verification.StandaloneGateCProvenanceTests -v`):

| Case | F2 observation |
| --- | --- |
| F3-GC-02 | `AssertionError: BenchError not raised` — a coherent in-memory latency forgery with unchanged raw bytes was **accepted** |
| F3-GC-03 | same acceptance for a non-statistical `run_json` change |
| F3-GC-04 | rejected only at RV-06 (`control_result_digest`), not at admission |
| F3-GC-08 | `dataclasses.replace(record, fixture_only=True)` accepted |
| F3-GC-09 | fixture authorization + production record rejected with the wrong field |
| F3-GC-11 | `source_root=None` accepted |
| F3-GC-06/07 | the equality helper did not exist |

Green: all 11 F3-GC cases pass, including the previously red F3-GC-02, plus the 18
existing O09-VER tests and the coordinator end-to-end fixture graph.

## Source-level adversarial answers

1. No production path reaches RV-04/RV-07 without `reverify_official_admission`: the
   re-admission runs in the production branch before `validate_official_analysis`.
2. Relabelling the record cannot select fixture mode: mode is read from the verified
   authorization and a mismatch is rejected first.
3. Any field change (`trials`, `run_json`, `control`, `campaigns`, `slots`,
   `inventory`, digests) breaks full dataclass equality and is rejected.
4. The new check performs read-only validation; it cannot mutate raw bytes, rewrite
   G0, launch engines, alter receipts or publish.
5. RV math is unchanged and still independent of `official.analysis`
   (`test_o09_ver_03` passes).
6. The coordinator continues to use its own re-admitted record; the extra Gate C
   read is a second validation, not a bypass.

## Digests and gates

| Item | Value |
| --- | --- |
| Source set digest | `sha256:79186989226f1df793f7ca0ece6b809c327bd9386b883797f102afe86aa8cb98` |
| Framework QA digest | `sha256:140158d2518bc4d51e9e9f1cc97cd981079854d162db1165276cdd10fe068ed8` |
| Source QA digest | `sha256:631d9788580b1937409db4ee0af733684e92c108431bb951595e318308c62e6d` |
| Profile digest | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` (unchanged) |
| Official Python | **313 tests OK** |
| Full Python | **1,278 tests OK, 0 skips** |
| Scripts / inventory / compileall / console | PASS (108 script tests) |
| Rust | fmt/clippy/tests stable+MSRV, doc, `bench` **compile only** PASS; coverage **92.04% lines** |
| Hosted final-head CI | **UNVERIFIED** — `gh` returns HTTP 401; run #394 is the previous head |

Disposition: `BM09_RF09_F3_IMPLEMENTED_LOCAL_PASS_CI_UNVERIFIED_REAL_BLOCKED`.

---

# RF09-F4 (2026-11-17) — persisted cross-engine control provenance

Scope: PR #110, starting head `c65c2bcfb2308ac328f73e7e495fb24f5e89026a`, merge
base `a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b`. Findings RF09-13 (fixed here) and
RF09-14 (diagnosed here; repair in the separate Addendum A commit).

## RF09-13 — the persisted control is the only authority

Production cross-engine admission previously copied the caller/capability control
mapping. The inventory hashed `control/control.json`, but the admitted control came
from memory, so a changed in-memory control with unchanged bytes was accepted.

Correction (`official/admission.py`, `official/verification.py` only):

1. New private `_read_bound_cross_engine_control(raw_root, supplied, inventory)`:
   requires a mapping, reads the fixed `control/control.json` through the existing
   strict reader, requires
   `sha256_prefix(canonical_document_bytes(parsed)) == reader_digest`, requires
   exactly one inventory member with that digest and byte length, compares
   `canonical_payload_bytes(supplied)` with the parsed content, and returns the
   **parsed** tree.
2. `_admit_cross_engine_core` computes the raw inventory first, then selects the
   control from disk in production mode (`for_production=True`) and keeps the
   in-memory mapping only for fixture mode; `require_control_pass` and the
   schema/slot/lane checks run on the selected control exactly once.
3. `reverify_official_admission` continues to pass the capability control as a
   **corroborating assertion**; the docstring was corrected accordingly.
4. Gate C adds canonical-payload comparisons for the cross-engine control: first for
   the capability's own record (field `control`), then the existing full-record
   equality (field `admission`), then the submitted record's control (field
   `admission`). This closes the `12` vs `12.0` Python-equality gap without a general
   comparator redesign.

## Red → green (executed)

Red on F3 source (`PYTHONPATH=benchmarks python -m unittest … -v`, log in the task
evidence directory):

| Case | F3 observation |
| --- | --- |
| CP-02 supplied control mismatch | `AssertionError: BenchError not raised` |
| CP-03 numeric alias (`12.0`) | `AssertionError: BenchError not raised` |
| CP-04 input alias ownership | admitted record **shared** the caller's nested `block_ratios` list |
| CP-09 capability control mutation | `AssertionError: BenchError not raised` |
| GC-01 capability control alias | `AssertionError: BenchError not raised` |
| GC-02 submitted numeric alias | `AssertionError: BenchError not raised` |
| CO-01 coordinator capability mutation | `AssertionError: BenchError not raised` |

Green: 15 CP cases, 15 GC cases (including the 4 F4 additions) and 17 coordinator
cases pass; the official suite is 333 tests and the full Python suite 1,298 tests
with zero skips after one controlled re-freeze.

## Controlled re-freeze (sequence 1)

| Anchor | Before | After |
| --- | --- | --- |
| `source_set_digest` | `sha256:79186989…cb98` | `sha256:07af5bf47d3bdb5b3bd6172fdc63be7efa9553e200db7748596bf37050ed3280` |
| `framework_qa_digest` | `sha256:140158d2…068ed8` | `sha256:d62073f92b795cb8ce4db2b7398c72d2add3c1f3e5e0d35023deb41179baebef` |
| `source_qa_digest` | `sha256:631d9788…62e6d` | `sha256:9960a739d92bb4c3fa122fdc83344c934ab6aa0eac5d9dfdc8df257a0ce241df` |
| `profile_digest` | `sha256:9db01390…046c` | unchanged |

## RF09-14 diagnosis (bounded, executed)

Two detached worktrees at the F3 head and at `a5a8303`, identical
`unified.rs` blob `9625b442f385bd264fa6899cd8c42d83828bc7a1`, Rust 1.85.0, 25
sequential `--exact --test-threads=1` attempts each:

| Baseline | Attempted | Passed | Known u43 failures | Other |
| --- | --- | --- | --- | --- |
| F3 `c65c2bc` | 25 | 21 | 4 | 0 |
| main `a5a8303` | 25 | 23 | 2 | 0 |

Both baselines show the exact `CorruptIndex("exact-set capacity grew after
reservation")` failure and passes on the same source/toolchain, so the finding is
`NONDETERMINISM_OBSERVED` and `REPRODUCED_ON_MAIN`. RF09-14 remains open at this
checkpoint; the repair is the separate Addendum A commit.

---

# RF09-F4 Addendum A (2026-11-17) — ExactSet capacity accounting

Continues the F4 work above. Parent scope kept (RF09-13 fixed, committed as
`5a7b8e6533b0aadc885fb13b4d2730646a73df1f`); this addendum repairs RF09-14.
No real timed acquisition, G0/T6 approval, historical parity, retirement or closeout.

## Design implemented

`crates/quervant-core/src/search/unified.rs`:

- `State<S = RandomState>` is generic over the hasher; production keeps
  `RandomState`, and a `#[cfg(test)]` accounted factory accepts a supplied builder.
- Construction reserves the set for `K+2` and the scratch `Vec` for `K+1`
  (`try_reserve`/`try_reserve_exact`) and charges
  `T = set_capacity*40 + scratch_capacity*size_of::<DocumentKey>()` **once** through
  the existing local/batch wrappers. `T` is fixed for the query.
- New fields `exact_scratch`, `exact_retained_limit`, `exact_initial_capacity`, plus
  test-only `force_rebuild_next_admit` / `exact_rebuilds`.
- `reserve_exact_set` is restricted to an empty, uncharged state and keeps the
  `fail_reserve` hook plus a new test-only `fail_scratch_reserve` hook.
- `rebuild_exact_set` drains the set into the preallocated scratch and back, keeping
  both allocations, restoring every key and guaranteeing one insertion slot.
- `admit` replaces the per-admission `try_reserve(1)` capacity-delta accounting with:
  validated retained bound, preflighted peak (`extra + charge`) and evicted
  (`charge + key length`) release, optional rebuild, `h_commit(extra)`, heap
  admission, **insert before evict**, then a single `2 × O` release. Every rejection
  path precedes rebuild/commit/clone/heap mutation; a heap failure releases `extra`
  and propagates the original error.

## Red proof (executed)

Deterministic probe on pinned Rust 1.85.0 (`HashSet` reserve 33, the fixed
dense/sparse sequence) confirmed the predicted effective-capacity sequence
**56 → 55 → 55 → 56**. An instrumented replication of the *shipped F4-checkpoint*
arithmetic (same toolchain) then showed:

| Defect | Observed |
| --- | --- |
| A-U01 ledger conservation | after the first replacement the ledger was **42 bytes short** of the independent sum (the code refunded a 40-byte table "shrink" without deallocating) |
| A-U02 second replacement | `capacity grew after reservation` — the exact hosted `CorruptIndex` failure |

The probe and replication live outside the tracked tree in the task evidence
directory; they replicate the arithmetic rather than executing the shipped binary,
and that limitation is stated here explicitly.

## Green (executed)

- `rf09_14_tests`: **12 tests** (A-U01, A-U02, A-U03, A-U04, A-U05, A-U06, A-U07,
  A-U08, A-U09, A-U10, A-U11, A-U12) pass on Rust 1.85.0 and 1.98.1, default and
  `--all-features`.
- `u43_replacement_witness_all_variants`: **10/10 pass on 1.85.0 and 10/10 on
  1.98.1** (previously 21/25 and 23/25 on the two baselines).
- `pr15i_d3_c` integration target: 22 tests pass on both toolchains and both feature
  sets, including the new `rf09_14_av01_reopened_snapshot_sorting_matches_the_independent_oracle`
  (4096 durable documents, K ∈ {1,31,32,100,1024}, exact descending oracle, forced
  Linear and default parity, byte-identical tree) and
  `rf09_14_av02_pagination_collects_every_key_once` (K=100 cursor walk, 4096 keys in
  42 requests or fewer).
- `u42_exact_set_memory_estimate_k1024_long_keys` now includes the scratch capacity
  and still fits the 2 MiB ceiling; `fx_final_exactset_batch_memory_failure_then_success`
  probe updated to `K+2` set capacity, `K+1` scratch capacity and the prescribed
  structural formula, with its `T + 3000` margin unchanged.
- Workspace: tests pass for both toolchains (default and all features); clippy
  (`-D warnings`) passes for 1.98.1 default/all-features and 1.85.0 all-features;
  fmt clean; `cargo doc` and `cargo bench --no-run` pass; workspace line coverage
  **92.08%**.
- Python regression: the Rust change is outside the frozen source roster, so the F4
  synthetic anchors remain valid (`source_set_digest` unchanged) and the F4 Python
  evidence above still applies.

## Performance diagnostic

Protocol `RF09-14-query-regression-v1` was executed for the default strategy (three
benchmarks, four pairs each): median B/A ratios 0.9969 / 0.9899 / 0.9912, all inside
the 25% guard. The ExactSet phase could not produce valid timings: arm A failed the
correctness gate with the repaired defect and arm B with a pre-existing harness
top-k interaction (`ResourceLimit { limit: 1024, requested: 3750 }`; the harness
validates with K above `MAX_EXACT_SET_K`). ExactSet nonregression is therefore
reported as **UNAVAILABLE** for reviewer disposition; full numbers are in
`verification-report.md`.

---

# RF09-F4 Addendum B (2026-11-17) — Gate C family guard, complete acceptance, diagnostic scope

Scope: PR #110, start `597ea6c08d9861ff47bf0c0983d747c5ce602637`. Findings
RF09-15…RF09-19. This addendum executed the parts recorded below and **stopped
one dependent task** on a scope conflict it could not resolve inside its allowlist.

## RF09-15 — family guard before family-specific access (FIXED, local verified)

Red (executed on `597ea6c`): `test_f4b_gc_01_helper_rejects_cross_engine_numeric_alias`
→ `AssertionError: BenchError not raised`, because
`_require_exact_admitted_record` only used dataclass equality (`12 == 12.0`).

Correction (`official/verification.py` only):

- The helper now guards **exact family** first, then full dataclass equality, then
  the canonical JSON content of the cross-engine control (field `admission`). No
  family-specific field is read before the family guard, so a wrong-family record
  can no longer raise `AttributeError` on `authoritative.control`.
- Both inline canonical-control comparisons were removed from
  `verify_official_study`; its post-re-admission sequence is now exactly
  `reverify_official_admission` → `_require_exact_admitted_record` →
  `admitted = authoritative`. The capability-control mismatch is still reported with
  field `control`, now by production re-admission.
- `official/admission.py`: docstring correction only (unchanged executable code).

Acceptance executed: B-P01 red→green; B-P02/P03 both mixed-family orientations plus
the public wrong-family negative (`dataclasses.replace(fresh, fixture_only=False, …)`
against the genuine production-shaped capability) → `BM_IDENTITY_INVALID/admission`;
B-P04 CP-08 now covers leaf symlink, parent-directory symlink, hardlink (`nlink == 2`)
and FIFO members with byte/inventory restoration; B-P05 GC-04 replaced its tautology
with a real pre/post raw-bytes and inventory comparison; B-P06 CP-10 now requires
`field_path == "admission"`, proves the mutated raw state is preserved, and restores
the original mapping and inventory.

Evidence boundary: the original orientation using an *authentic retained-key
production capability* remains source-traced only (no authentic retained-key archive
exists). Real retained-key L3 remains blocked.

## RF09-18 — bounded diagnostic scope (IMPLEMENTED AND EXECUTED, then reverted)

The bounded branch for `crates/quervant-core/benches/unified_diagnostics.rs` was
implemented exactly as prescribed and all six command-compatibility checks were
executed:

| Case | Scope / strategy | Observed |
| --- | --- | --- |
| H01 | absent / absent | exit 0, no bounded marker, metadata written, 3 benchmarks selected |
| H02 | `""` | exit 101, no metadata, no marker |
| H03 | `unsupported-rf14b` | exit 101, no metadata, no marker |
| H04 | `\xff` (invalid Unicode) | exit 101, no metadata, no marker |
| H05 | `sort-n-bounded-v1` | exit 0, bounded marker, 3 benchmarks |
| H06 | `sort-n-bounded-v1` + `exact_set` | exit 0, bounded marker, 3 benchmarks — the K=3750 failure is gone |

**Scoped HARD STOP (F4-D15 / A-D24 equivalent):** keeping that branch makes the
pre-existing BM-01 regression `test_leg_07_frozen_historical_bytes_are_unchanged`
fail, because it whitelists only `benchmarks/README.md` for change under
`crates/quervant-core/benches/`. The only fix is to edit
`benchmarks/quervant_bench/tests/test_legacy_inventory.py`, which is **outside**
Addendum B's 22-path allowlist. Rather than silently extend the allowlist, the branch
was reverted (`crates/` clean) and the patch retained outside the repository
(sha256 `389559230cdd3cdd6ddcf8e8208d74bd6db1acac244d44fa954e8f1c4aa01b3f`).
Consequence: the v2 performance protocol was **not** executed and RF09-18 remains
open pending an amended allowlist decision.

## RF09-16 / RF09-17 / RF09-19 — NOT EXECUTED

- RF09-16 (actual old-`State::admit` red proof via Appendix A instrumentation): not
  executed in this session. The earlier instrumented arithmetic replication and the
  pinned-1.85 probe remain the only red evidence; the earlier "42-byte" figure is
  **not** corrected by an actual-code run.
- RF09-17 (assertion-level completion of A-U01…A-U12): not executed; the shipped 12
  `rf09_14_tests` remain as delivered by Addendum A.
- RF09-19 (three local real RustFS suites): not executed; no container runtime probe
  was performed in this session. The hosted `rustfs` job remains the only real-service
  evidence.

No claim is made that these passed.

## Gates on the final state of this addendum

| Gate | Result |
| --- | --- |
| Official Python suites (admission/verification/coordinator) | 127 tests PASS |
| Full Python suite | **1,299 tests, 0 skips** |
| Scripts / inventory / compileall / console | PASS (108 script tests) |
| Rust fmt/clippy (1.98.1 default+all-features, 1.85.0 all-features) / tests both toolchains / doc / `bench --no-run` | PASS |
| Workspace line coverage | **92.08%** |
| Controlled synthetic re-freeze (sequence 1 for Addendum B) | source `sha256:7922c1a8…b638`, framework QA `sha256:8b169b5e…981f`, source QA `sha256:e5a96aea…8562`, profile unchanged |
| Hosted CI on the Addendum B head | **UNVERIFIED** (`gh` 401); run #396 is the previous head |

---

# RF09-F4 Addendum B — continuation erratum `RF09-F4-B-E1` (2026-11-17)

Resume point `25b6669b5e518f11e99959829d30947abf424585`. Parent Addendum B verified at
SHA-256 `a91dc30cb1ad80eafa7f8aed7518ca3b86e23832bb8b80f8ea3045527a345fe0`.

## RF09-15 completion (DONE, local verified)

- B-P01: the numeric-alias test now asserts both that ordinary dataclass equality
  permits `12` vs `12.0` **and** that the canonical payload bytes differ, then the
  typed `BM_IDENTITY_INVALID/admission` rejection.
- B-P04/CP-08: the four filesystem cases now run as named subTests
  (`leaf_symlink`, `hardlink`, `fifo`, `parent_symlink`) with the destructive setup
  inside the protected region and explicit `member_removed` / `parent_moved` /
  `parent_linked` flags, so cleanup is owned when creation or an assertion fails.
  Restoration still asserts pristine bytes and the recomputed inventory.

## CI observation correction

Hosted run **#397** (`44250709172`), attempt 1, is **SUCCESS** for head
`25b6669…`, tested merge `47d6e09e040bf25bca1a9aba2c69c149e8fdaaa2`, against main
`a5a8303…`: `python-contracts` 134620414995, `rust` 134620415077, `msrv`
134620414806, `rustfs` 134620415050 — all SUCCESS. The hosted Python run reports
**1,299 tests with one existing missing-authentic-archive skip** (not zero) and
92.08% line coverage. The earlier "UNVERIFIED" entry stands for its own head; #397
cannot certify any later head.

## RF09-18 execution (`detached-worktree-overlay-v1`), DONE

Diagnostic copies were prepared exactly as prescribed: detached worktrees at
`5a7b8e6533b0aadc885fb13b4d2730646a73df1f` (A) and the new implementation checkpoint
`25381607d33552ad68c671de403d6a26da03f194` (B), both clean, harness blob
`8e7dc5271b776636184ec811c87c427ead18d050` / SHA-256
`08b4b7e531a91a23809ad55dae8df46a7d9ab613c497bdd9da7fdbda60524802`, equal
Cargo.lock. The retained patch matched SHA-256
`389559230cdd3cdd6ddcf8e8208d74bd6db1acac244d44fa954e8f1c4aa01b3f`, applied with
`git apply --check` then `git apply`, and produced exactly one modified path with
identical arm diffs (`389559230c…`) and identical patched harness bytes
(`d02dec431b94db6cf6f6de9fb915f3c19778ca490529a8aca955b73eac0240eb`). The committed
harness in the implementation checkout is untouched; the BM-01 guard and whitelist
are unchanged, and LEG-07 passes on the clean checkout.

H01–H06 on the final patched B copy: normal path exit 0 without the bounded marker
and with metadata; empty/unknown/invalid-Unicode scope exit 101 with no metadata and
no marker; bounded scope exit 0 with the oracle marker; bounded + `exact_set` exit 0 —
the K=3750 failure is gone.

Protocol `RF09-14-query-regression-v2` (Rust 1.98.1, bounded scope, N=10,000/S=4,
K={10,100,1000}, 3 s warm-up / 5 s measurement / 20 samples, fixed pair order), all
contention records `clear`:

| Benchmark | Default B/A ratios (4 pairs) | Median | Guard ≤ 1.25 |
| --- | --- | --- | --- |
| `…/k10/sort-n` | 1.0229, 1.0040, 1.0009, 1.0075 | **1.0057** | PASS |
| `…/k100/sort-n` | 1.0383, 1.0271, 1.0125, 1.0166 | **1.0218** | PASS |
| `…/k1000/sort-n` | 1.0026, 1.0138, 1.0083, 0.9978 | **1.0054** | PASS |

ExactSet phase: arm A failed its untimed gate with the known old defect
(`CorruptIndex("exact-set capacity grew after reservation")`), so per §8.5 exactly
four successful B ExactSet runs were executed (B1–B4, three benchmarks each) and no
ExactSet ratios were computed → `BASELINE_EXACTSET_CORRECTNESS_INVALID` /
comparison **UNAVAILABLE**, `PERF_ACCEPTANCE=REVIEW_REQUIRED`.

## RF09-19 — probes executed, suites not executed

Provider probes on the coding host: `docker` and `docker compose` **UNAVAILABLE**;
`podman info` and `podman compose version` **OK** (row 3 of §9.1). The owned service
was **not** started in this session, so the three local real RustFS suites
(`pr13_oracle`, `pr13_oracle_geo`, `m1_batches`) were **not executed** here. The
hosted `rustfs` job in #397 ran all three named suites and remains the only
real-service evidence; it is not local acceptance.

## RF09-16 / RF09-17 — not executed

- RF09-16 (actual old-`State::admit` red proof with Appendix A instrumentation) was
  not executed; the earlier arithmetic replication and the pinned-1.85 probe remain
  the only red evidence, and the earlier "42-byte" figure is not corrected by an
  actual-code run.
- RF09-17 (assertion-level completion of A-U01…A-U12) was not executed; the twelve
  `rf09_14_tests` remain as delivered by Addendum A. No claim is made that the
  completed assertion matrix passed.

## Controlled re-freeze (continuation sequence)

| Anchor | Previous | Now |
| --- | --- | --- |
| `source_set_digest` | `sha256:7922c1a8…b638` | `sha256:81bcdecc4f7019c6805b2db91ea8ae108c45d47d523b4e83077baaad40e9a734` |
| `framework_qa_digest` | `sha256:8b169b5e…981f` | `sha256:e3f178ddc94f91e856dc0bb7b48218ed2be01fe468bdd0dff61cef71583baba9` |
| `source_qa_digest` | `sha256:e5a96aea…8562` | `sha256:15732a6a0cef3a4100a8dbec34eadac4b7bb1b235c3f4173bf89a2d59a88dbd0` |
| `profile_digest` | `sha256:9db01390…046c` | unchanged |

Post-freeze source digest recomputation equals the anchor. Note: the earlier F4 claim
that the `reverify_official_admission` docstring correction was already applied was
premature — it landed with the Addendum B commit `25b6669`.

## Gates on the continuation final state

Full Python **1,299 tests, 0 skips**; scripts 108; inventory/compileall/console PASS;
Rust fmt/clippy/tests on 1.98.1 (default + all features) and 1.85.0 PASS; workspace
line coverage **92.08%**. No real timed acquisition beyond the bounded nonofficial
diagnostic; real G0/T6/L3/historical parity remain **BLOCKED**; not merged.

---

# RF09-F4 Addendum B — E1 continuation round 2 (2026-11-17)

Resume point `9f766e69e5db93e1efa0662836a41adab3078b1e`. RF09-16 and RF09-19 executed;
RF09-17 remains not executed (row-level ledger below).

## RF09-16 — actual old-code red proof (EXECUTED)

Extracted the supplied Appendix A patch and Appendix B verifier with the Appendix C
procedure: patch SHA-256
`8d8c2e219ccdfdf790617cb3784c1b93a640bd03ba8d9d7314d1c5ad0e96975f` (matches),
verifier parses. Detached worktree at `5a7b8e6533b0aadc885fb13b4d2730646a73df1f`
(clean, `unified.rs` blob `9625b442…287a7`), `git apply --check` then `git apply`,
and the body verifier reported byte-identical old bodies:

```
admit BYTE_IDENTICAL sha256:925a27e4e5d0e03d9558d81a4185001f1bfe9fdbbdc094dcd2404d10e9862927
reserve_exact_set BYTE_IDENTICAL sha256:ad3526aca1bcd1d377502e8684980d7bbb4a251d7839223caeb7deda0cafba0f
heap_admit_candidate BYTE_IDENTICAL sha256:ff9a2174f00fbcaecdd64784a8c72acbe99aa44874c576ffb2c661a4d760e62b
BASELINE_BODY_IDENTITY=PASS
```

Red results (Rust 1.85.0, `--exact --test-threads=1`, warm target dir):

| Case | Observed |
| --- | --- |
| B-R01 `b_red01_actual_baseline_local_ledger` | `initial_capacity=56 final_capacity=55 initial_table=2240 before=4824 heap_bytes=2318 key_bytes=270 expected=4828 actual=4788 **deficit=40**`; assertion `left: 4788, right: 4828` FAILED — the ledger is 40 bytes short |
| B-R02 `b_red02_actual_baseline_batch_ledger` | same numbers with a real `SlotMemoryScope`; `scope=Some(4788)` equals the wrong local ledger, exposing both accounting paths |
| B-R03 `b_red03_actual_baseline_second_replacement` | `capacity_before=55 capacity_after=56 result=Err(CorruptIndex { detail: "exact-set capacity grew after reservation" })`; success assertion FAILED |

**Correction of the earlier claim:** the previous arithmetic-replica report's "42-byte
deficit" was an artifact of its simplified charge model. The actual old-code execution
on the pinned toolchain shows the prescribed **40-byte** deficit, expected 4828 vs
actual 4788. The replica and the standalone capacity probe remain historical
supporting evidence only.

## RF09-19 — local real RustFS suites (EXECUTED)

Provider probes: `docker` / `docker compose` unavailable; `podman info` and
`podman compose version` available (row 3). Owned topology
`quervant-rf14b-<token>` with `RF14B_CONTAINER_NAME` override, pinned image
`rustfs/rustfs:1.0.1@sha256:1803faef…6a3c`, loopback ports 9000/9001 verified free,
health on attempt 1.

| Suite | Exit | Named real test executed |
| --- | --- | --- |
| `pr13_oracle` | 0 | `real::o01_o02_o03_o09_o10_real_rustfs` ok |
| `pr13_oracle_geo` | 0 | `real::o04_o05_o06_real_rustfs` ok |
| `m1_batches` | 0 | `real_rustfs::m1_v04_real_rustfs_batch_replay_and_generation_consistency` ok |

Cleanup: service logs captured (secret/access key redacted), `compose down -v` run,
and the owned container, volume and the leftover `…_default` network were removed;
`podman ps -a`/`volume ls`/`network ls` show none of them. No other task's containers,
volumes or networks were touched, and no global prune was used. The first `up` echo
log from the planning step also contained unredacted keys and was redacted in place.

## RF09-17 — A-U01…A-U12 assertion completion: NOT EXECUTED (ledger)

The prescribed constructor seam (`finish_construction`), the charged-state reservation
guard, and every assertion upgrade in Addendum B §6 were **not implemented**. The
twelve `rf09_14_tests` remain exactly as delivered by Addendum A and still pass on
both toolchains, but the following required rows are missing:

| Row | Required, not implemented |
| --- | --- |
| A-U01 | both local and real-batch sinks, model equality and exact peak |
| A-U02 | explicit model membership after the second replacement |
| A-U03 | rebuild under a real scope with ledger/scope/peak assertions |
| A-U04/A-U05 | full K grid incl. invalid K in both constructor modes; zero balances on error; peak T / 0 |
| A-U06 | T+206 / T+205 / T+207 subcases with `cccc`/`ccc` charges 68/67 and same-state reuse |
| A-U07 | K × short/1024-byte key × scope cross product with per-operation model and expected peak |
| A-U08 | equal-score K1 ordering/loser/reappearance chain |
| A-U09 | exact corrupt-state detail matrix incl. checked overflow rows |
| A-U10 | unpublished constructor faults with prior balances 7/11 and the four reserve-guard snapshots |
| A-U11 | `finish_success`/`finish_failure`/Drop cases with prior 7 and independent follow-up query |
| A-U12 | populated 1025 × 1024-byte-key sentinel case with the auxiliary estimate bound |

Consequently the implementation checkpoint stays `2538160…`; the v2 diagnostic already
collected against it (default PASS; ExactSet comparison UNAVAILABLE) remains the
current evidence, and no new checkpoint or re-run was created for this round.

## Gates

Python and Rust source are unchanged since the last green run (this round only added
external diagnostic work and documentation): full Python 1,299 tests / 0 skips,
Rust gates on 1.98.1 and 1.85.0, coverage 92.08%. The three local RustFS suites above
are additional real-service acceptance for this round.

## RF09-17 — EXECUTED: A-U01…A-U12 assertion completion (supersedes the ledger above)

Implementation commit `b94a4d1910ee24929f08f7553dc65816efe8f70c`
(`BM-09 RF09-17: exact-set assertion completion and construction seam`), parent
`15b962f`. The only changed file between `15b962f` and `b94a4d1` is
`crates/quervant-core/src/search/unified.rs`; no Python, protocol, QA or script file
was touched, so the last controlled re-freeze and the Python gates stand unchanged.

### Production changes (Addendum B §6.1)

| Item | Evidence |
| --- | --- |
| One owned constructor seam | `new_with_builder` builds `Self::empty`, installs the builder, then delegates to `finish_construction(state, k, budget, scope)`; the old constructor body (k validation, `reserve_exact_set`, `table = capacity*40`, `scratch = capacity*size_of::<DocumentKey>()`, `h_preflight`/`h_commit`, `exact_table_charged`/`exact_initial_capacity`/`exact_retained_limit`) moved verbatim into the seam |
| Test-only fault factory | `ReserveFault::{Set, Scratch}` plus `for_test_accounted_with_builder_and_fault`, which also routes through `finish_construction` after setting the matching flag |
| Charged-state reservation guard | `reserve_exact_set` now also rejects `exact_table_charged != 0` and `exact_live_key_charged != 0`; detail `"exact-set reservation requires an empty, uncharged state"` |

`BYTE_IDENTICAL` bodies from the RF09-16 proof (`reserve_exact_set`,
`heap_admit_candidate`) keep their logic; the only edits are the guard predicate, its
detail string, and the extraction of the constructor body into the seam.

### Assertion → execution ledger

Each row was executed individually (`cargo +1.98.1 test --locked -p quervant-core
--lib --all-features <name> -- --exact --test-threads=1`); ledger file
`f4b/rf09-17-ledger.json` — **12 rows, 18 tests, 0 failures**.

| Row | Executed test(s) | Asserted in this round |
| --- | --- | --- |
| A-U01 | `a_u01_replacement_conserves_the_structural_ledger`, `a_u01b_batch_replacement_conserves_the_structural_ledger` | model run `None` **and** real `SlotMemoryScope`; set/heap/model membership equality after fill and after the first replacement; fixed T; live key charge = model key bytes; exact local balance probed through `preflight_release_global_bytes`; scope balance equality; meter peak = filled + (new key len + evicted key len + new charge) = **92** in the fixture; `finish_failure` leaves current 0 |
| A-U02 | `a_u02_second_replacement_matches_the_model` | second replacement succeeds; final set = 31 fixture keys minus both zero-score keys plus both new keys; model equality after every step |
| A-U03 | `a_u03_rebuild_moves_the_same_allocations` | rebuild under a real scope: identical key pointers, scratch pointer and capacity, unchanged T/live/balance/scope, `rebuild_count()==1`, heap tuples unchanged, meter peak equals the filled state |
| A-U04 / A-U05 | `a_u04_constructor_local_boundaries_are_exact`, `a_u05_constructor_batch_boundaries_are_exact` | K ∈ {1, 31, 32, 100, 1024}: T exact in both modes, empty set, local balance == T, scope bytes == T; one-under local → `ResourceLimit`, one-under batch → `BudgetExceeded{BatchMemoryBytes}`; zero balances and zero scope bytes on every error; invalid K ∈ {0, 1025} rejected with zero balances |
| A-U06 | `a_u06a…`/`a_u06c` (local), `a_u06d…`/`a_u06f` (batch) | K=1, heap limit 2, `a`=65/`bb`=66/`cccc`=68/`ccc`=67: admitted transient **T+207**, reuse transient **T+205**, one-under **T+206** rejected with the forced-rebuild flag preserved and no rebuild, final balances **T+140** and **T+138**; meter peak asserted against the ledger model (302 filled-state when the rejection commits nothing, 373 for the reuse case) |
| A-U07 | `a_u07_model_churn_preserves_membership_and_ledger` | 20 configurations = K ∈ {1, 31, 32, 100, 1024} × {short, 1024-byte} × {local, batch}; 4·(K+1) replacements each; per-operation model membership, constant T, live charge = model key bytes, per-operation expected peak |
| A-U08 | `a_u08_ordering_duplicates_and_losers_are_preserved` | equal-score K=1 ordering (`aa` evicts `b`), retained duplicate `check` fails without mutation, loser leaves state and pending flag unchanged, `0` consumes the flag with a rebuild, evicted key reappears at a better score |
| A-U09 | `a_u09_corrupt_state_is_rejected_before_mutation` | nine isolated corrupt rows with exact detail strings (count mismatch, missing worst, non-empty scratch, zero/above retained bound, bound exceeded, live underflow, live overflow, overlap overflow); checked overflow maps to `ResourceLimit { limit: u64::MAX, requested: u64::MAX }`; zero rebuilds, flag preserved, full 12-field state snapshot equality |
| A-U10 | `a_u10_constructor_faults_and_reserve_guard` | `ReserveFault::Set` → `ResourceLimit{10,10}`, `ReserveFault::Scratch` → `ResourceLimit{9,9}` at K=8 through the seam, with prior local balance **11**, prior meter balance **7** unchanged and scope 0; four reserve-guard snapshots (charged table, live-only, non-empty set, non-empty scratch) each return the exact `CorruptIndex` detail |
| A-U11 | `a_u11_cleanup_paths_and_follow_up_query` | `finish_success(0)`, `finish_failure` and bare `Drop` cleanup with prior meter 7; peak **7 + T + 207**; an independent follow-up query constructs a fresh state and commits T+66 |
| A-U12 | `a_u12_populated_maximum_includes_scratch_and_sentinel` | K=1024, 1025 retained 1024-byte keys, retained limit 1025, sentinel retained, key bytes **1,049,600**, auxiliary estimate ≤ 2 MiB |

### Interaction with the RF09-18 / RF09-19 evidence

The RF09-17 change is test-facing plus a precondition guard, so the earlier RF09-19
RustFS results and the Python QA anchors are unaffected; `unified.rs` is not part of
either frozen Python tree.

## RF09-18 — final-source diagnostic re-run (v3, EXECUTED)

Re-run after the RF09-17 commit, same design (`detached-worktree-overlay-v1`): arm A
`5a7b8e6533b0aadc885fb13b4d2730646a73df1f` (defective base, red control), arm B
`b94a4d1910ee24929f08f7553dc65816efe8f70c` (implementation head). The harness branch
patch was applied to both worktrees with `git apply --index`; the staged diff is
`sha256:389559230cdd3cdd6ddcf8e8208d74bd6db1acac244d44fa954e8f1c4aa01b3f` in **both**
arms, and the tracked harness was left untouched.

Harness checks (`f4b/v3-harness-A.json`, `f4b/v3-harness-B.json`):

| Case | Scope | Arm A | Arm B |
| --- | --- | --- | --- |
| H01 | default validation | exit 0, metadata written | exit 0, metadata written |
| H02 | empty scope value | exit 101 (rejected) | exit 101 (rejected) |
| H03 | unsupported scope value | exit 101 (rejected) | exit 101 (rejected) |
| H04 | non-Unicode scope value | exit 101 (rejected) | exit 101 (rejected) |
| H05 | `sort-n-bounded-v1` | exit 0, `ORACLE_GATE=PASS` | exit 0, `ORACLE_GATE=PASS` |
| H06 | `sort-n-bounded-v1` + `exact_set` | **exit 101** — `CorruptIndex { detail: "exact-set capacity grew after reservation" }` (`unified_diag_common/mod.rs:472`) | **exit 0**, `ORACLE_GATE=PASS` |

H06 is the red/green control for the repaired defect: the previous head could not even
gate the ExactSet phase; the RF09-17 head can.

Timed runs (`f4b/v3-runs.json`, order A1 B1 B2 A2 B3 A3 A4 B4, all pre/post contention
state `clear`):

| Phase | Runs | Result |
| --- | --- | --- |
| default | 8/8 OK (4 A + 4 B) | median B/A ratios **k10 1.0209**, **k100 1.0237**, **k1000 1.0097** (guard ≤ 1.25 **PASS**) |
| exact_set | A1 `GATE_FAIL`, B1–B4 OK | no A/B pair ⇒ ratio **UNAVAILABLE** |

Absolute medians (ns/iter): arm B `exact_set` k10 **3,349,580**, k100 **3,645,167**,
k1000 **5,877,711** (spread 2.8–3.3 %); default phase A k10 3,244,224 / k100 3,450,419
/ k1000 21,817,232 versus B k10 3,304,997 / k100 3,543,139 / k1000 22,155,378.

`PERF_ACCEPTANCE=REVIEW_REQUIRED` stands for the ExactSet comparison: the defective
baseline arm cannot produce a gated baseline, and RF09-17 deliberately does not change
the scored admission path. The observed default-phase k1000 medians (≈21.8 ms both
arms) versus the gated exact_set medians on arm B (≈5.9 ms) are recorded as an
observation only; they are not a qualified comparison and no strategy change is made
from them.

## Gates on the final source (`b94a4d1`)

| Check | Result |
| --- | --- |
| `cargo +1.98.1 fmt --all -- --check` / `cargo +1.85.0 fmt --all -- --check` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets -- -D warnings` | PASS |
| `cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets` (default and all-features) | PASS |
| `cargo +1.98.1 test --workspace --all-targets` | **2,505 passed, 0 failed**, 13 ignored (138 binaries) |
| `cargo +1.98.1 test --workspace --all-targets --all-features` | **2,549 passed, 0 failed**, 94 ignored |
| `cargo +1.85.0 test --workspace --all-targets` | **2,505 passed, 0 failed**, 13 ignored |
| `rf09_14_tests` | 18/18 on 1.98.1 all-features; 18/18 on three consecutive 1.85.0 runs |
| `cargo +1.98.1 doc --workspace --no-deps` | PASS |
| `cargo +1.98.1 bench --workspace --no-run` | PASS |
| `cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85` | **92.67 % lines** (60,594 lines, 4,440 missed; region 93.21 %, function 87.95 %), floor PASS |
| `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py'` | **1,299 tests, 0 failures**, 511.6 s (Python tree unchanged since the last green run) |

Hosted CI for `b94a4d1` is **UNVERIFIED**: `gh` still returns `HTTP 401: Bad
credentials`, so no run id can be observed; run #397 SUCCESS applies only to
`25b6669`. Real G0 authorization, the D3-C T6 freeze receipt, PR15D corpus/adapter
acceptance and authentic historical parity remain blocked on external owners; no
legacy retirement; `v0.1-bench` is not COMPLETE; `MERGED=NO`.

### RF09-19 re-execution on the final head (`e61e7dc`, EXECUTED)

Because the implementation head changed core code after the previous RustFS round, the
three real-boundary suites were re-executed on the final head with an owned Podman
topology (`quervant-rf14b-5a24b89a4e16`, pinned image
`rustfs/rustfs:1.0.1@sha256:1803faef…6a3c`, health on attempt 1, credentials redacted in
every log):

| Suite | Exit | Named real test executed |
| --- | --- | --- |
| `pr13_oracle` | 0 | `o01_o02_o03_o09_o10_real_rustfs` |
| `pr13_oracle_geo` | 0 | `o04_o05_o06_real_rustfs` |
| `m1_batches` | 0 | `m1_v04_real_rustfs_batch_replay_and_generation_consistency` |

Owned resources after the run: **0 containers**, **0 project volumes**, network
`quervant-rf14b-5a24b89a4e16_default` removed (`podman network rm`). Two unrelated
pre-existing networks from other sessions remain untouched.

## RF09-F4-B-E2 — assertion completion, executed on `4c8817d` (2026-11-18)

RF09-17 **was executed**; this continuation completes the assertion contract it left
partial. The production ExactSet repair, the `finish_construction` seam, the
`ReserveFault` factory and the charged-state reservation guard are **byte-identical**
(`e2_scope_check.py`: prefix `f89379d4…`, suffix `bf906ace…`, unchanged across the
edit). Only the body of `#[cfg(test)] mod rf09_14_tests` changed.

Implementation checkpoint: `4c8817df04248863df00fc20cbabc959e6c0a711`
(parent `013fa41b`). The module now has **19 test functions** (the 18 previous plus the
restored `a_u08_duplicates_ordering_and_losers_are_preserved`).

### Assertions completed in this round

| Was (partial) | Now |
| --- | --- |
| Owned `(String, f64, u64)` model; expected charge could be copied from the implementation | One borrowed `InputRecord` model; the expected charge is `64 + key.len()` computed independently and asserted against `candidate_charge` at every admission |
| `structure_total()` re-read the recorded charge | `initial_structural_charge()` derives T from the physical capacities of the *empty* accounted state and asserts the recorded charge equals it |
| U07 peak derived after admission (double-counting the candidate) | `model_next_peak()` computes the transient from the pre-operation model, the input record and the retained limit only |
| Twelve-field tuple snapshot without set pointers/scratch/bounds/scope | Named `Snapshot` struct with set key pointers, heap `(key, score bits, charge)`, scratch keys/pointer/len/capacity, bounds, flags, rebuild count and both ledgers |
| U03 heap comparison without score bits | Full `(key, score bits, charge)` equality plus pointer, ledger and peak checks |
| U04/U05 without final meter observations | Every grid cell asserts local/scope/meter current and peak after the borrow ends |
| U06 without a complete rejection snapshot or exact error fields | `ResourceLimit{limit:T+206, requested:T+207}` (local) / `BudgetExceeded{BatchMemoryBytes}` (batch), full `Snapshot` equality, then prescribed reuse on the same state |
| U07 first rebuilt count not pinned; U08 R3 case missing | First forced rebuild asserted exactly 1 with the flag consumed; the original R=3 chain restored next to the R=2 tie chain |
| U09 without a real scope; U10 guard rows incomplete | All nine corruption rows run under a real `SlotMemoryScope`; the four guards use a genuine accounted state (T) and three genuinely empty states (0) |
| U11 follow-up asserted scope only; U12 sentinel used the first key | Both balances asserted for the follow-up; the sentinel is `inputs[1024]` |
| Cleanup sometimes released the scope before dropping data | Uniform order: drop heap/State → `finish_*` → end borrow → read meter |

### 12 rows → 19 selectors (executed individually)

| Row | Selectors | Grid / subcases executed |
| --- | --- | --- |
| A-U01 | `a_u01_…`, `a_u01b_…` | local + real batch: fill 32, current **T+2584**, peak **T+2676**, final **T+2588** |
| A-U02 | `a_u02_…` | explicit final membership (minus dense-00/sparse-00, plus both replacements), **T+2588** |
| A-U03 | `a_u03_…` | rebuild pointer/heap-tuple/ledger identity, count 0→1, fill peak T+2584 |
| A-U04 / A-U05 | `a_u04_…`, `a_u05_…` | K ∈ {1,31,32,100,1024} exact and one-under; K ∈ {0,1025} invalid; both modes |
| A-U06 | `a_u06a…f` | 3 cases × 2 sinks: peaks **T+134 / T+205 / T+207**, final T+140/T+138 |
| A-U07 | `a_u07_…` | 20 cells × (R fills + 4R replacements), modelled peak per operation |
| A-U08 | `a_u08_duplicates…`, `a_u08_ordering…` | R=3 original chain and R=2 tie chain with literal best-first sequences |
| A-U09 | `a_u09_…` | 9 fresh corrupt states, exact details, no mutation, scope peak T+134 |
| A-U10 | `a_u10_…` | 2 constructor faults (ResourceLimit 10/10, 9/9; prior 11 and 7 preserved) + 4 reserve guards |
| A-U11 | `a_u11_…` | 3 cleanup modes, peak 7+T+207, independent follow-up **T2+66** |
| A-U12 | `a_u12_…` | 1025 × 1024-byte keys, sentinel `inputs[1024]`, 1,049,600 key bytes, **T+2,164,800**, auxiliary ≤ 2 MiB |

Command receipts: `receipts/commands.jsonl` (`E2F-ind-*` per selector, `E2F-mod-*` for
the four module configurations, `E2F-int-*` for the four `pr15i_d3_c` configurations,
`E2F-u43-*` for the 20 fresh U43 processes). Evidence package:
`/tmp/quervant-rf09-f4.rfhAq8/e2/package/`, inventory
`sha256:bc10c07fd38514b6c6d20c5b3e255a78b451679c2955d669987106a1034bb464`, archive
`bm09-e2-evidence.tar.gz` `sha256:4ef874cebdb68585144601ff129554b14b681cff5e6ca8d34dcc0302c8769f61`.

Source equivalence for the reused historical measurements:
`e2/receipts/source-equivalence.json` — measured B `b94a4d1`, E2 start `013fa41b`,
final `4c8817d`; every tracked path other than the test module and the four
append-only documents is byte-identical; the benchmark library is compiled as a plain
`lib` (no `--test`, no `cfg test`, no coverage instrumentation).

## RF09-F4-B-E2 — corrections to earlier wording (append-only)

1. **Replacement refund arithmetic.** Production *preflights* the evicted entry's
   `charge + key_len` (`h_preflight_release`); that preflight is not a committed
   refund. The committed release of a replacement is the evicted heap charge plus
   **twice** the evicted key length (`heap_commit_release(old_charge)` plus
   `h_release(2*old_len)`). The earlier phrasing "release the evicted `charge+old_len`
   and the `2·old_len` overlap" double-counted the preflight.
2. **Old-code proof.** The actual deficit is **40 bytes** (expected 4828, actual 4788);
   the earlier "42" was an arithmetic replica. The old source blob is full
   `9625b442f385bd264fa6899cd8c42d83828bc7a1`; the proof receipts are packaged under
   `old-code-proof/` (instrumentation patch, red log, body-identity verifier).
3. **A-U01 peak.** 92 bytes is the replacement *overlap above the filled current*, not
   the total meter peak; the prescribed peak is **T+2676**.
4. **A-U02.** There are 32 initial keys; `dense-00` has score 0 and `sparse-00` score 1;
   the final model removes exactly those two and adds the two replacements.
5. **H06 identity.** The failing gated arm is the pre-RF09-14 base `5a7b8e6`; the
   repaired candidate already contained the capacity repair, so its ExactSet gate
   passes. The failure is not attributable to the RF09-17 assertion work.
6. **Guard snapshots.** The earlier round performed four *unsnapshotted* guard checks;
   the four complete `Snapshot`-based guards are new in E2 and are not backdated.
7. **Coverage.** `92.67 %` remains tied to its original command/scope (default
   features). E2's acceptance number is the newly executed
   `--all-targets --all-features` result, **92.21 %**.
8. **Protocol.** The historical acquisition directory is named `v3`, but its actual
   design is the approved **RF09-14-query-regression-v2** protocol (same arms, patch,
   three IDs, 3 s/5 s/20-sample timers, order and calculation). Filenames are retained;
   the reconciliation is recorded, and no protocol was renamed or re-run for the label.
9. **CI.** The correctly mapped baseline run for `013fa41b` is
   [#401](https://github.com/yduchesne/quervant/actions/runs/44376240704), attempt 1,
   tested merge `ec13268043379fcaf123fa1921b9ebc096623216`: `python-contracts`,
   `rust`, `msrv` and `rustfs` all SUCCESS. The final E2 head is observed separately in
   the external completion receipt.

### E2 evidence-package identity correction (append-only, 2026-11-18)

The inventory/archive hashes cited above describe the package snapshot built **before**
the final-head CI observation and the completion receipt were added. The delivered
package is the later snapshot that also contains `ci/` and `completion-receipt.txt`:

- package directory `/tmp/quervant-rf09-f4.rfhAq8/e2/package/`
- inventory `evidence-inventory.json`
  `sha256:73fdeb23beda83e3c772e6b92df20f57e0a298a8fb04d71d28ab52380de39269`
  (468 files, every size/hash re-verified against the staged tree)
- archive `bm09-e2-evidence.tar.gz`
  `sha256:4fda25d10139779b7bdffdc1b6467185905c51b32d36d3532a3414a06fdc4d5d`
  (488 KB; all 468 inventory rows present, no absolute or parent-traversal entries)

The archive hash is recorded beside the archive (`e2/ARCHIVE.sha256`), never inside it.
The final PR-head CI mapping is held in the external completion receipt, not in another
documentation commit.


## BM-09 operator migration after E2 — implementation evidence (2026-11-19)

Continuation baseline: `b7ce3a478af6012c607debea090dfad0b3d2ac17`.
The explicit task boundary is source migration with untimed validation; no
benchmark, timed pilot, actual preparation/smoke workload or real-service
qualification was invoked by this continuation.

The missing public acquisition path, cross-engine A/A producer and retained-key
policy/historical connections are implemented. Both required real families and
their logical synthetic references now enter through the configured common
operator surface. See `docs/BENCHMARK_WORKFLOW.md` for commands, exact input
fields, ownership, continuation and fixed stop conditions.

| Regression/integration area | Untimed verification added |
| --- | --- |
| Stage progression | Exact ordered stage plans; no later stage after a failed approval, readiness or control; no implicit retry |
| Configured CLI | Fixed family routing, closed configuration, v1/v2 envelope separation, no success from backend `SystemExit` |
| Cross-engine | Complete raw A/A schedule/oracle/readiness binding; runtime and binary tamper rejection before treatment |
| Retained acquisition | Original control/treatment build order and all slot/lane calls through deterministic doubles; actual on-disk executable mismatch blocks before index/query |
| Process lifetime | Success, timeout, interruption, partial output preservation, bounded worker error transport and owned descendant cleanup |
| Retained policy | Complete micro input grid, original F1 identities, symmetric filters, independent seeded bootstrap/decision recomputation, raw-input and capability mutation rejection |
| Historical policy | Mapping-owned archived inputs, independent source/digest pins, reopen/tamper behavior; no current-run input substitution |
| Continuation | Missing retained inputs create no immutable placeholder; completed preparation can finalize after genuine QA arrives without rebuilding |
| Legacy compatibility | Actual D3-C readiness builder with clocks/sleep/counters substituted; original summary shape; immutable protocols, scripts and v1 schemas |

Full-suite integration exposed the frozen schema registry dependency. The fix
restores `outcome.v1.schema.json` byte-for-byte and moves new operator results to
a separate closed v2 resource; no historical guard or registry was weakened.
The validator closure now includes the new module and resource (22 entries).
Only the explicitly synthetic golden validator-source pin/spec digest and the
existing 12 synthetic qualification QA fixtures were refreshed to final source.
No raw measurement, real QA record or approval was created by this refresh.

Final controlled fixture identities:

```text
VALIDATOR_SOURCE_DIGEST=sha256:b333a16d3632c8a938230483ff9559482837cf65d49bf7c6c9e15d100f03237e
SYNTHETIC_GOLDEN_SPEC_DIGEST=sha256:ec19ebcf053e244aae42d5ea663b540202a4cd1de2518a376f20c608e6ee86fa
SOURCE_SET_DIGEST=sha256:7d838173bdb05d32136d81c604960cb1be9e905512362365536ebc62f6fdd527
FRAMEWORK_QA_FIXTURE_DIGEST=sha256:1c1ef7f598542d357cb777c0f672651a371f11d0416387998230d7a0bf0f7442
SOURCE_QA_FIXTURE_DIGEST=sha256:a8eeb00f63f8bea2caf4ce6e8b105d16534180677421195a48e171944a980399
PROFILE_DIGEST=sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c (unchanged)
```

The current verification report records final executed counts and environmental
limitations. Earlier E2/RF09 performance and CI evidence remains tied to its own
source checkpoint and is not relabelled as validation of this migration.

## BM09-CONTINUATION-POST-MIGRATION-1 — C-F01/C-F02/C-F03 implementation (2026-11-18)

Started from the fast-forwarded migration head
`bff24340ed3e8f86ea0df87e3192fa0a5cd608f2` (fresh main
`a5a8303e1701aa10f2bf94a6dc6ca9b5a608526b`). Clean tree, migration ancestry verified,
`git pull --ff-only` only.

| Finding | Implementation | Counterexample evidence |
| --- | --- | --- |
| C-F01 first-run QA cycle | `FRAMEWORK_QA_ROSTER` now carries `official-authorization-boundary` and `official-control-boundary` (15 IDs, source roster still 18); both are registered `hosted-ci`/`python-contracts`; the `operator-attested` registration for `official-g0-review`/`official-real-aa` is gone; both official templates change only `required_qa.framework` | Red: `test_c_t01..c_t03`, `CoherentRosterForgeTests` (7 tests, 5 failures + 5 subTest errors on the baseline). Green: 72 targeted tests pass |
| C-F02 authorization scope | `protocols._PERMITTED_CAMPAIGN_ORDERS` fixes `["control","treatment"]` and the retained three-campaign sequence; `validate_authorization` compares the normalized list and raises `BM_IDENTITY_INVALID`/`permitted_campaign_order` | Red: `CampaignOrderTests` 17 subTest failures (baseline accepted `["fixture"]`, reordered, duplicate, subset and other-family lists). Green after the change |
| C-F03 exact-source CI | `on.push.branches` becomes `[main, dev/bm09-real-qualification]`; every job gains `Record tested source identity` immediately after `actions/checkout@v4`, logging event/PR-head/checkout commit+tree and failing when the checkout differs from the event SHA | Red: `BranchPushWorkflowTests` (branch list and missing step). Green: contract + four executed identity-script cases (exact push, wrong push, PR merge distinction, empty SHA) |

Template identities after the correction (both verified against the prescribed
values, including the raw bytes):

```
cross-engine-keyword-v1.json  content sha256:dd6ff8a244664d0c521e8cb8b47e32eac22a20bef860b1d47a71e7df090c75fd
                              raw     b806f508244acabc12fde27e981396ccbae98f7ddf9b14932a6cc79b4fd4808c
retained-key-topk-v1.json     content sha256:6ba22f7c1e0b1cb0a11e645b0ce27a350111bbb8688e97c1bd247fe52677e20f
                              raw     d286acbb34dbdf17b52c88edcdc3356878c8cffa24b24a10d548c75dd6c90474
```

Controlled synthetic re-freeze (one occurrence, after the last code/test edit):
source set `sha256:331f61af6f7c1a076d5d2ee7cfb0546572e3464f67f2eb8845e518d7b38c9479`
(unchanged before/after the fixture edit), framework QA
`sha256:35840d37b46ad88a56cda9269037b10c0a3a7915268fac0fd6ecade3ab9444cf`, source QA
`sha256:c6176d906f10c2298b8e020b9eb640a2ef03f88b7e19caf0793e43a3e5a7a04b`, profile
`sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` unchanged.
Only the nine per-check records and two summaries changed `source_set_digest` /
`evidence_digest`; both chains reopen through `qualification.qa.read_qa_evidence`.

Measured checks on the checkpoint: targeted three modules **72 tests OK**,
`FixupAnchorTests` + `QaTests` **14 tests OK**, full Python discovery **1,426 tests,
0 failures, 0 skips** (the socket test runs unchanged on this host; the earlier
migration host's EPERM was environmental).

## BM09-CONTINUATION-POST-MIGRATION-1 — executed gates and blockers (append-only, 2026-11-18)

Checkpoint C `b2eb2878…` passed: full Python 1,426 tests / 0 failures / 0 skips;
Rust workspace 2,506 passed (default) and 2,550 (all features) on both pinned
toolchains; clippy/fmt/doc/bench clean; coverage 92.21 % lines with
`--all-targets --all-features`; 20/20 U43 fresh processes; the three local real
RustFS suites exit 0 under owned project `quervant-bm09-df9cc1850631` with full
cleanup; hosted runs #405 (push) and #406 (PR) both green in all four jobs with
the identity step reporting the exact checkout for `b2eb2878…` (PR tested merge
`8f839942…`).

Concrete blockers, classified by the plan's matrix:

| Trigger | Rule | Evidence |
| --- | --- | --- |
| Official host observation reports `environment=wsl2` | D11 (host prerequisite) | `quervant-bench prepare` → `BM_EVIDENCE_UNAVAILABLE` field `host`; capability snapshot `kernel_release=6.18.33.2-microsoft-standard-WSL2` |
| Authentic T6 receipt, `micro.json`, T7-F1 receipt, PR15D `20261031T005545Z-…` archive absent | D24/D37 | bounded searches of the executing checkout, `~/.local/share/quervant/benchmark-evidence`, `target/` and the operator host leave no candidate; the three retained archives with expected hashes are present |
| Hosted job logs HTTP 403 unauthenticated | D20 | `429/403` probe against `…/actions/jobs/<id>/logs`; run/job metadata is available and recorded |
| `gh workflow run comparative-adapters.yml` returns 401 | D21 | CLI authentication failure; CI owner must dispatch at C |
| No independent G0 or mapping approval supplied | D26/D39 | no approval records in any authorized approval root |

No measured campaign was attempted, no approval was fabricated, and no historical
evidence was reconstructed. `closeout_status` returns `BLOCKED` with ten unmet
predicates; the disposition stays `BM09_IMPLEMENTATION_L1_L2_PASS_REAL_BLOCKED`.


## 2026-11-19 — Linux/WSL2 compatibility and current-baseline continuation

The maintainer's final direction is current benchmark results as a new baseline, with within-run proportional A/B effects and optional authentic historical relative-effect reporting. The proposed mandatory legacy-versus-new experiment is superseded. Missing history is not a future current-baseline acceptance gate. Native Windows collection is not claimed. The normative contract and executable-agent design are `docs/BENCHMARK_MIGRATION_ACCEPTANCE.md` and `docs/BM09_COMPLETION_PLAN.md`.

Implemented in this change: a reviewed native-Linux/WSL2 union selector; actual environment retained in G0 identity; consistent preparation, live readiness, both acquisition families and persisted cross-engine control checks. Literal-only selectors remain restrictive; mixed environments within one control fail. The retained acquisition caller now loads its own independently pinned retained template and passes it to the shared CPU check. Tests also finish the previously omitted campaign-order singleton negatives, retained opener no-effect assertion and actual QA-validator rejection of the removed operator check IDs. No frozen legacy source, Rust code, historical byte or benchmark sample changed.

Local verification: five affected host/protocol/acquisition/workflow modules PASS, 81 tests. The exact CI discovery command ran 1,441 tests in 403.997 seconds: zero assertion failures, one ERROR from the unchanged AF_UNIX path test (`PermissionError: [Errno 1] Operation not permitted`), and one existing authentic-archive-unavailable skip. This is not a full-suite PASS. An earlier discovery invocation with `-t benchmarks` also produced three flat-import errors; the supported CI command without that option removed those import errors. Compileall, module/installed-console inspection and exact legacy inventory check PASS. Script suite attempted, exit1: cargo/rustc are absent; profile/fixture-metadata tests could not build and the suite stopped before a final count. Rust fmt/clippy/tests/doc/coverage/bench compilation and local real RustFS were not executed here. No benchmark timings were acquired.

One controlled synthetic re-freeze after final source/test edits: source-set `sha256:94d237b9a22aed90b84d903856d2255b87274dc3c7a3e2da7cb4baf0ed2f6dce`; framework QA `sha256:13cee67a064700bf91144d7e210e1d953912e3bcec7e631d999e4b9361decd24`; source QA `sha256:19cae013a73368c58dccacb79d106dd3d25534a738a48b5b7fb693646e32187f`; profile unchanged `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c`. Both fixture chains reopened, source digest stable. These remain synthetic fixtures, not executed real SOURCE_QA.

Current-baseline-v2 acceptance/runtime-freeze/proportional-history/export/replay are DESIGNED, NOT IMPLEMENTED by this host patch. Their detailed continuation has explicit versions, fixed scientific source pins, positive baseline verification without an unsupported optimization-selection claim, automatic committable results and a bounded decision matrix. BM-09 real acceptance remains incomplete pending that work and execution. MERGED=NO. Final hosted CI must be observed for the actual pushed head; no prior-head result is promoted here.

## BM09-CURRENT-BASELINE-1 — implemented slice (append-only, 2026-11-19)

Started from `2ff491fb96dbe4796dd5a8e87e98c84de7db5e81` (fast-forward from
`560a0af`, fresh main `a5a8303e…`, merge base `a5a8303e…`). The downloaded
plan's §3 work — proportional relative effects and the bounded historical
inventory — is implemented as two additive modules with no change to any v1
production path:

| Item | Evidence |
| --- | --- |
| `official/relative_effects.py` | 20-field normalized rows, exact decimal gains, six-pair retained projection, cross-engine projection, `COMPARABLE`/`CONTEXT_CHANGED`/`NOT_COMPARABLE` comparisons, closed 8-key disclosure payload |
| `official/history.py` | closed inventory schema and roles, frozen-digest enforcement for retained archives, `FOUND`/`MISSING`/`INVALID`/`UNVERIFIED`/`NOT_COMPARABLE` statuses, `AS_REPORTED` derived inputs, disclosure reopening bound to baseline/study/source/raw |
| Tests | `test_official_relative_effects.py` (18) and `test_official_history.py` (14) covering T01–T04: reciprocal-speedup vs latency-reduction, −10 percentage-point example, scale invariance, contextual vs non-comparable pairs, duplicate/tampered rows, frozen-digest mismatch, symlink/unsafe paths, unverified inputs, disclosure binding |
| Full Python | **1,473 tests, 0 failures, 0 skips** |
| Qualification anchors | `FixupAnchorTests` + `QaTests` 14 tests OK after one controlled refresh |
| compileall / inventory / scripts | PASS / PASS / 108 passed |

Controlled synthetic refresh (one occurrence, after the last Python edit): source
set `sha256:f0eaf2fe1a66860c745afc54e92889a54f54287195af695133e8ae5c39a0c481`
(unchanged before/after the fixture edit), framework QA
`sha256:71153d92…7511`, source QA `sha256:97f27630…2b11`, profile
`sha256:9db01390…046c` unchanged.

Not implemented here (explicitly not claimed): the `current-baseline-v2` profile
and versioned dispatch, `official/runtime_freeze.py`, `official/transport.py`,
preservation/clean-checkout replay, and the current cross-engine/retained
acquisitions. Those remain `BM09-CURRENT-BASELINE-1` stages 2–10.

## BM09-CURRENT-BASELINE-1-F1 — first-slice corrections (append-only, 2026-11-19)

Applied the addendum's numeric, row and history corrections to the two delivered
modules. No v1 production path changed.

| Finding | Correction | Evidence |
| --- | --- | --- |
| F1-01 | The numeric layer now preserves the estimator's digits: `4/3` stores `1.3333333333333333` and gains `-33.33333333333333`; persisted forms must already be canonical | `normalize_ratio`/`stored_ratio`/`gain_percent`; literal vectors and a `Fraction` oracle in `test_official_relative_effects` |
| F1-02 | `0.0000001` stays nonzero; interval endpoints are validated in the original precision before any rendering, so `1.0000004 > 1.0000003` rejects even though both render `1.000000` | `interval_endpoints`, `render_six` (the only six-place quantizer, presentation-only) |
| F1-03 | A caller-supplied digest can no longer authenticate anything: the fixed `SUPPORTED_SOURCES` catalog is the sole authority, and a conflicting declaration is `INVALID / declared-digest-conflicts-with-independent-anchor` | `history.classify_candidate`; unknown identity stays `UNVERIFIED / unsupported-source-identity` |
| F1-04 | Historical reads use the descriptor-based `open_regular_beneath` path (no link following, bounded), with absence reported before authentication | symlink/parent-escape/FIFO/directory tests, budget guard |
| F1-06 | Closed row validation: exact types, registered lane/campaign/arm/latency literals, canonical stored strings, `UNIQUE_KEYS` include `run_id`, and `current_index` rejects duplicate or multi-run ambiguity instead of silently choosing one | `validate_row`, `unique_rows`, `current_index`; both input orders tested |
| F1-07 | Documentation now states that a treatment/baseline latency ratio of 1.2 is a 20 % latency increase and gain `-20` | `docs/BENCHMARK_WORKFLOW.md` |
| Status vocabulary | Serialized missing inputs are `UNAVAILABLE` (the first slice's `MISSING` was an unpublished spelling) | `history.STATUSES`, tests |

Comparison rules now follow the addendum exactly: `NOT_COMPARABLE` carries only
`['no-current-row']` with null change; matched rows carry the ordered label subset
`source-commit`, `host-environment`, `host-identity`, `as-reported`; the unreachable
`estimator` branch and the `coordinate-mismatch` fallback are gone (method is a match
key, so a mismatch is a schema error).

Gates: targeted 41 tests (24 effects + 17 history, one conditional repository test),
full Python **1,482 tests, 0 failures, 0 skips**, qualification anchors 14/14 after one
controlled refresh, compileall/inventory/scripts PASS.

Not implemented in this fixup (unchanged scope): the summary-to-row history adapters
(`pr15d-aggregate`, `retained-analysis`) and the shared raw-replay projector, which
belong to the v2/transport stages; and the v2 profile, runtime freeze, transport and
current acquisitions themselves.

### F1 continuation — status corrections and adapter completion (append-only, 2026-11-19)

Corrections to statements in the previous F1 section of this file:

- **F1-03/F1-04 were overstated as fully closed.** The catalog and safe-read work was
  real, but the inventory still accepted unhashable/boolean field types, had no
  candidate/depth/node budget, and raised on an absent provider root. Those are now
  fixed: typed schema errors before any membership test, `MAX_CANDIDATES = 32` with
  JSON depth/node budgets, and an unavailable provider location classified as
  `UNAVAILABLE` per candidate instead of aborting the report.
- **F1-05 was reported as deferred.** It is now implemented: fixed
  `pr15d-aggregate` and `retained-analysis` readers project authenticated summary
  documents into `AS_REPORTED` rows (32 and 864 respectively), and the authentic
  committed PR15D aggregate is exercised as a positive with its exact anchors.

New evidence: `history.pr15d_aggregate_rows` maps `engine_over_quervant_ratio` with
`baseline=quervant`, `treatment=<comparator>`, `method_id =
historical-three-trial-python-round6-v1`, `source_commit = 40a9c26a…`, `run_id =
20261031T005545Z-40a9c26a…`, `host_identity = sha256:<host_fingerprint>`, null
environment and no interval. The committed aggregate
(`benchmarks/reports/pr15d/pr15d-qualified.json`) hashes to the catalog anchor
`sha256:c9e8ed72…b257`; its warm `pr15d_v1/10000/absent/k10` rows produce
`tantivy 0.045566 → 95.4434` and `lucene 1.068173 → -6.8173`, exactly the specified
golden values, and the 32-row set covers every warm lane once per comparator.
`history.retained_analysis_rows` projects the authentic retained analysis shape
(72 lanes × 2 campaigns × 6 literal pairs) as `AS_REPORTED` with the experiment
revision and no host fields. Both adapters are covered by negatives: wrong schema,
wrong run/source, unqualified status, truncated or duplicated lanes, missing
comparator ratio, missing interval, missing retained blocks, and any attempt to
relabel a summary row as `RECOMPUTED`.

Gate results for this continuation: full Python **1,487 tests, 0 failures, 0 skips**;
qualification anchors 14/14 after one controlled refresh (source set
`sha256:1546cb74…3959`, framework QA `sha256:df6b5250…5976`, source QA
`sha256:8784e6f9…13dd`, profile `sha256:9db01390…046c` unchanged); compileall,
contract inventory and 108 script tests PASS.

Still outstanding, and not claimed: the v2 execution profile and versioned dispatch,
`official/runtime_freeze.py`, `official/transport.py` preservation/replay, the
baseline disclosure factory/publication wiring, available-raw retained historical
reanalysis, both current acquisitions, committed results and clean-checkout replay.

## BM09-CB1-STEP1 — first-slice implementation corrections (append-only, 2026-11-19)

Scope: `BM09-CB1-STEP1` on head `9b4f4bc6e5999e4ed393bb0b58742ac1def26548`.

| Change | Detail |
| --- | --- |
| Row contract | `validate_row` now type-checks every scalar before membership, requires a real boolean `current`, rejects non-`lower` registered rows, requires `input_digest` in both modes, keeps `host_identity` a digest for current rows but only a bounded printable descriptor for historical rows (so a Windows fingerprint is representable), and pins retained intervals to `paired-slot-bootstrap-v1`. |
| Disclosure boundary | `validate_disclosure` validates the four header identities (UUID4 baseline, commit, digest, registered study), rejects mixed current runs and mixed measured host contexts, and requires **exact set equality** with the family grid (16 lanes × 2 comparators; 72 lanes × 2 campaigns × 6 pairs) instead of an "either 32 or 864" count. |
| Stable reading | One private `_observe`/`_stable_observation` helper opens each component from the filesystem root through the existing no-follow descriptor implementation, requires a single-link regular file, enforces the byte budget, snapshots `(dev, ino, size, mtime, ctime, nlink)`, and re-observes; identical bytes through a new inode are rejected. Strict JSON rejects duplicate keys, BOM, invalid UTF-8, non-finite literals, out-of-range numbers, non-object roots, depth > 64 and node count > 100 000. |
| Catalog | Authority is an immutable tuple of ten `SourceRecord`s (including `retained-micro / micro-05 / digest=None`); `SUPPORTED_SOURCES` is a read-only `MappingProxyType` view, and classification never consults the mutable archive-digest dict. A missing or conflicting declared digest for a pinned identity is `INVALID / declared-digest-conflicts-with-independent-anchor`; unknown identities stay `UNVERIFIED`. |
| Role dispatch | Every role has a literal reader: retained archive (audit + frozen protocol, no extraction), micro (`validate_micro_table`, `UNVERIFIED / no-independent-raw-digest`), F1 receipt (`_f1_identity`), T6 receipt (private adapter mirroring the frozen fields), PR15D ZIP (pinned length, `inspect_zip`, manifest member set/hashes/lengths), PR15D aggregate (32 `AS_REPORTED` rows), retained analysis (864 `AS_REPORTED` rows), retained policy (metadata only). No role falls through to a hash-only `FOUND`. |
| Summary adapters | The PR15D adapter now requires the exact 24 root keys, lane `field`/`term` per class, three-value trial arrays, positive integer medians and boolean comparison flags, and validates cold lanes before emitting warm rows only. The retained adapter requires the exact root/lane/campaign key sets, ascending unique retained blocks with a matching `retained_count`, the complementary excluded-block set with `arms` derived from the ratios, the per-cell cap, positive latency tables and `L/P/H` raw ratios. |
| Report/entry | Entries require a catalog record with a matching digest to be `FOUND`; rows are allowed only for the two summary roles, must be `AS_REPORTED`, must cite the entry digest, and must belong to the entry's family. Reports validate their header identities, bound the entry count, and reject cross-family entries. |
| Documentation | `docs/BENCHMARK_WORKFLOW.md` now states that a treatment/baseline latency ratio of 1.2 is a 20 % latency increase with `gain_percent = -20`, and that cross-run differences are percentage points of gain. |

Executed gates for this step: focused modules **58 tests** (34 relative-effects incl. the
complete-family grid and hostile ambient Decimal context, 24 history incl. the genuine
PR15D 32-row positive, real hardlink/FIFO/parent-symlink/dangling-provider/replace-after-read
faults, strict-parsing budgets, T6/policy/micro adapters and the disclosure reader); full
Python **1,499 tests, 0 failures, 0 skips**; qualification anchors **14/14** after one
controlled refresh (source set `sha256:0efd8a88…48c2`, framework QA `sha256:a6bf3676…c64b`,
source QA `sha256:e92d1f6c…2dbc`, profile `sha256:9db01390…046c` unchanged); compileall,
contract inventory, both `inspect` surfaces and **108** script tests PASS; the unchanged
AF_UNIX socket probe and named socket test PASS on this host; Rust fmt/clippy/tests on
1.98.1 and 1.85.0 (default and all features), doc, bench compile and `llvm-cov` **92.21 %**
lines all PASS.

Not claimed: v2 integration, runtime freeze, transport/replay, service QA, current
acquisition and BM-09 acceptance. Available-raw retained reanalysis and the shared
projection remain the later steps.

## BM09-CB1-STEP1-F1 — reader and validation fixup (append-only, 2026-11-19)

Reviewed start `451b35e361c4a249e2e81533039c323c98770563`; fixup checkpoint
`591c821` (rebased onto the operator's docs-only commit `9bcb28d`; no published
history rewritten, no rebase of published commits).

**Correction to the Step 1 receipt above:** at `451b35e` the focused split was
**28 relative-effects + 30 history** tests (not 34 + 24). The current fixup suite
is 34 relative-effects + 46 history = 80 focused tests.

| Finding group | Change |
| --- | --- |
| 1. Historical context | Removed the duplicate environment allowlist that ran after the current/historical branch, so historical rows accept a bounded printable descriptor (`windows`, `original-host-id`) while current rows keep the exact `native-linux`/`wsl2` allowlist and digest identity. |
| 2. Comparison references | `validate_comparison` now validates `historical_row_digest` with the identity owner first, validates `current_row_digest` only for comparable pairs, and requires the change before `stored_derived`; `_uncertainty` passes the method without `str()` coercion. |
| 3. Strict parsing | Token-length enforcement moved **inside** the `parse_int`/`parse_float` callbacks, with finiteness/overflow checks and an exact `Decimal` view from the original token; the text-after-last-quote check was removed; structural budget violations are `BM_UNSAFE_INPUT`. |
| 4. Stable observations | One `_observe_file` (lexical provider ancestry through the no-follow descriptors, single link, exact budget, snapshot before/after, streaming unless capture is requested) plus `_require_same_observation`; archives are never buffered and inherit `ArchiveLimits().max_archive_bytes`. |
| 5. Observation ordering | The classifier observes the candidate, authenticates the declaration, parses, observes the fixed dependencies, runs the owning reader, then rechecks **every** recorded observation; INVALID outcomes keep their primary error and skip the recheck; a change detected at recheck becomes `INVALID/changed-during-read`. |
| 6. Role readers | Micro no longer short-circuits on a null catalog digest; T6 validates exactly the seven known fields as a subset (no invented `receipt_origin`, no whole-receipt schema); F1 observes its four fixed sources before calling the owner; retained archives use a pure `(parent, basename, sidecar)` helper; PR15D uses the real `MemberDigest` API and the committed manifest's 68-name / 65-record binding including the 502 566-byte package. |
| 7. Summary boundaries | Exact-number guards for both families, exact integer retained block ids/cap, typed PR15D lane scalars, typed excluded-block ids and `arms` derivation, and `validate_entry` binding rows to the fixed summary metadata through `unique_rows`. |
| 8. Archive dispatch | Retained candidates are observed under the archive bound while JSON roles use 4 MiB; sidecar absence is first-read `UNVERIFIED/owning-reader-sidecar-unavailable`, post-observation disappearance is `INVALID`. |

Executed proof: `Step1FixupTests` classes cover T01–T24 (historical context,
mandatory comparison references, method typing, independent 32/864 grids,
identity boundary, arithmetic preservation, token parsing, exact budgets,
absence vs unsafe ancestry, no-follow `raw_digest`, operation-bracketed
observations, typed I/O failure, streaming budgets, disclosure reader faults,
micro owner, T6 fields, both policy schemas, PR15D manifest/API binding,
retained archive routing, exact summary schemas, fixed row binding, classification
transitions and the genuine PR15D vertical slice with `0.045566 → 95.4434` /
`1.068173 → -6.8173`).

Final-source gates: focused **80** tests OK; full Python **1,521 tests, 0 failures,
0 skips**; qualification anchors **14/14**; compileall, contract inventory, both
`inspect` surfaces, **108** script tests, `git diff --check`, AF_UNIX probe and the
named socket test PASS; Rust fmt/clippy/tests on 1.98.1 and 1.85.0 (default and all
features), doc and bench compile PASS; `llvm-cov` **92.21 %** lines (whole
workspace, all targets/all features). Controlled refresh:
source set `sha256:fe36c526…e4ea`, framework QA `sha256:ca1c4293…beaa`, source QA
`sha256:1480e8e7…9638`, profile `sha256:9db01390…046c` unchanged.

Not claimed: authentic retained-archive/F1/T6 metadata positives (their inputs are
absent from this host and are recorded as unavailable), summary-to-row retained
analysis positive (no authentic file), Step 2 audit, v2/runtime/transport/replay,
service QA, acquisition, acceptance or merge.

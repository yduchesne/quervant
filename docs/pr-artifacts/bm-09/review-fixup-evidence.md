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

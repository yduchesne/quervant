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

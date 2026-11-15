# BM-02 verification report

## 1. State

| Item | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Branch | `dev/bm02-evidence-admission` |
| Actual main base | `bc1409ec997d66baa2ff3f403c239a598ffd87d3` |
| BM-01 C1 present | Yes: six v1 schemas, contract package, `inspect` CLI, legacy inventory and 82 passing L1 tests |
| Implementation commit | `9fca642d8253f1bd2a12e275eab154fee4166451` |
| Review-fixup commit | `bec0ce7675166151ae7295104489a25aeefe9ce8` |
| Remote head | `origin/dev/bm02-evidence-admission` (this evidence commit) |
| Working tree during QA | Only BM-02 additions plus the whitelisted `benchmarks/README.md` pointer and roadmap status sentence |
| Historical tracked files modified | 0 |
| BM-01 v1 schemas modified | 0 |
| New public schema IDs | 0 |
| Real timed acquisition | Not run |

Toolchains: Rust stable `1.98.1` and MSRV `1.85.0`; Python `3.12.3`;
`cargo-llvm-cov 0.9.1`.

## 2. Per-command results

| # | Command | Result |
| --- | --- | --- |
| 1 | `cargo +1.85.0 fmt --all -- --check` | PASS |
| 2 | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| 3 | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2529 passed, 0 failed, 94 ignored |
| 4 | `cargo fmt --all -- --check` | PASS |
| 5 | `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| 6 | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| 7 | `cargo test --workspace --all-targets` | PASS — 2485 passed, 0 failed, 13 ignored |
| 8 | `cargo test --workspace --all-targets --all-features` | PASS — 2529 passed, 0 failed, 94 ignored |
| 9 | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.70 % line** |
| 10 | `cargo doc --workspace --all-features --no-deps` | PASS |
| 11 | `cargo bench --workspace --no-run` | PASS — compile only, no timing |
| 12 | `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| 13 | `python -m compileall -q benchmarks/quervant_bench` | PASS |
| 14 | `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py'` | PASS — **230 tests, 0 failed** (82 BM-01 + 148 BM-02) |
| 15 | `PYTHONPATH=benchmarks python -m quervant_bench inspect --experiment synthetic-contract-smoke --format json` | PASS — byte-identical to console entrypoint |
| 16 | `quervant-bench inspect --experiment synthetic-contract-smoke --format json` | PASS |
| 17 | `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef64… --check docs/pr-artifacts/bm-01/legacy-inventory.json` | PASS |
| 18 | `git diff --check` | PASS |

Coverage scope is the full Rust workspace production code. Python coverage is
reported separately as the deterministic L1 matrix above; Rust `llvm-cov` does not
measure Python.

Ignored Rust tests require a live pinned RustFS container and are exercised by the
unchanged `rustfs` CI job. **Local RustFS boundary: not verified locally** (no
container was started); the test suite reports them as ignored rather than passed.

## 2.1 Independent review fixup — RF-01 through RF-04

Fixup implementation SHA: `bec0ce7675166151ae7295104489a25aeefe9ce8`
(reviewed head was `640925e4433e0bec3b5b2a0f8f4e71c43b40b911`). This evidence
commit follows it and does not change validator source bytes.

| Finding | Resolution | Acceptance tests | Result |
| --- | --- | --- | --- |
| **RF-01** Validator closure incomplete | `VALIDATOR_SOURCE_PATHS` is now the exact frozen 20-file package closure (adds `config/profiles.py`, `host/capabilities.py`, `host/readiness.py` and package/subpackage initializers). Synthetic trusted-spec `validator.source_digest` was refreshed once after source freeze; only the independent literal anchor changed in the test. | `test_vs_01_validator_source_list_is_the_frozen_closure`, `test_vs_02_golden_admission_and_reuse`, `test_vs_03_and_04_imported_module_mutation_invalidates_reuse`, `test_vs_05_changed_validator_digest_cannot_bypass_pinned_anchor` | PASS |
| **RF-02** Overlapping/protected roots | New side-effect-free `require_publication_base()` and `require_disjoint_admission_roots()` use component-wise containment and canonical resolution after safe-root checks. Wired into `admit_synthetic()`, `reverify_admission()` and the shared `_require_output_base()` used by direct publication/loading. Only `benchmark-results` inside the repository is permitted. | `test_root_01…05` (admission), `test_root_06_08…`, `test_root_10…`, `test_root_11…`, existing `test_store_06…` | PASS |
| **RF-03** Missing `BM_IDENTITY_INVALID` import | Import restored; three output-identity branches now raise typed errors instead of `NameError`. Tests recompute `receipt_id` so mutations are schema- and self-hash-valid and reach the intended branch. | `test_err_01_to_03_invalid_receipt_outputs_are_typed`, `test_err_04_valid_receipt_still_loads` | PASS |
| **RF-04** Unbounded Git blob buffering | Blob content now uses `git cat-file -s` size preflight (≤ 256 MiB, `BM_UNSAFE_INPUT` before spawn) followed by `git cat-file blob` streamed through `sha256_stream()` in 1 MiB chunks, with deterministic terminate/reap on every failure path. `git show` and whole-output blob capture were removed. | `test_git_01`…`test_git_08`, existing `test_prov_02…`, `test_prov_09…` | PASS |

Committed validator source digest:
`sha256:c5b3661ff96a81e7cf1b92cbd464c9bea5188a2d9c4cf286ec57e696fda5a358`.
Committed trusted-spec anchor:
`sha256:5a8b6a3f8a301c2f096d8f7c7d096085a6d4b4bf59b7c1cc69dd1450d5aad229`.

Post-fixup local QA on the fixup source/test tree:

| Check | Result |
| --- | --- |
| Python full L1 suite | PASS — 230 tests, 0 failed |
| Python compile/inspect/inventory | PASS |
| MSRV fmt/clippy/tests | PASS — 2529 passed, 0 failed, 94 ignored |
| Stable fmt/clippy/tests | PASS — 2485/2529 passed, 0 failed |
| Rust line coverage | PASS — 92.70 % |
| Docs, bench compile-only, script tests | PASS (108 script tests) |

One stable all-features run initially reported a single failure while an MSRV
suite was executing concurrently in the same target directory. Three immediate
sequential reruns passed 2529/0 with no failure. No log identified a product
test; classification is **environment/harness interference**, not a reproducible
regression. Final sequential runs are the recorded evidence.

## 3. Invariant evidence

| Invariant | Evidence |
| --- | --- |
| INV-01 contract immutability | CON-01/02 pass; no `config/`, schema, CLI or error-table diff |
| INV-02 trusted binding | ADM-02/08, SCOPE-10, `verify_rejects_wrong_anchor` |
| INV-03 raw byte integrity | ADM-03/07/09, HASH-01/02, ARC-01/02/06/07 |
| INV-04 path safety | PATH-01…07, ARC-03/04/05 |
| INV-05 bounded archives | ARC-01…11, plus TAR/ZIP parity cases |
| INV-06 source/build identity | PROV-01…09 |
| INV-07 complete binding | ADM-01 (21 sorted inputs), receipt build/verify tests |
| INV-08 safe reuse | REUSE-01…10, vertical slice |
| INV-09 exclusive publication | STORE-01…08 and non-canonical committed bytes |
| INV-10 scope isolation | SCOPE-01…10 |
| INV-11 diagnostic-only host data | HOST-01…09, closed-shape mutation rejection |
| INV-12 historical immutability | LEG-01, LEG-02 |
| INV-13 no time acquisition | CLI-01, SCOPE-06, HOST-05 |
| INV-14 fail closed | ADM-04/05, SCOPE-08, REUSE-08/09, lock/index shape tests |

## 4. Synthetic golden root

`benchmarks/quervant_bench/tests/fixtures/evidence-admission/` with independent
anchor `GOLDEN_SPEC_DIGEST` pinned in
`tests/test_evidence_admission.py`. Fixtures contain no measurements; archives
contain two tiny text/JSON members only.

Mutation evidence covers each category independently: raw evidence byte, archive
bytes, archive member declaration, source lock, adapter/analysis/build/schema
locks, protocol/workload/policy subject bindings, validator source and version,
QA roster, committed receipt fields, committed index fields, deleted evidence and
mid-flight replacement.

## 5. Legacy parity

Twelve deterministic cases are recorded in
[legacy-parity-matrix.md](legacy-parity-matrix.md): 2 `PARITY`, 4 `BOTH_REJECT`,
6 `NEW_STRICTER_REJECT`. No new acceptance where a legacy validator rejected a
security-relevant input (no D25 condition). Real T7/F2 archives are absent and
reported `EVIDENCE_UNAVAILABLE`, not recreated.

## 6. Decision-matrix use

| ID | Trigger | Action | Evidence |
| --- | --- | --- | --- |
| D01 | Fresh main contained BM-01 C1 at `bc1409e` | Branched from verified main; recorded SHA | §1 |
| D02 | BM-01 landed through merge PR #102 (`52a6557` is an ancestor) | Verified contract files and C1 rather than requiring a single-parent history | Preflight |
| D05 | BM-01 codec/identity/schemas available | Reused them; no second parser or custom SHA-256 | Imports and tests |
| D06 | Subpackages discovered by setuptools/unittest | No new CI job; existing discovery finds all tests | 230 tests discovered |
| D10 | Golden trust anchor needed independent literal | Pinned `GOLDEN_SPEC_DIGEST` in test code | ADM-01/08 |
| D14/D24 | Archive dangers and stricter new rejection | Rejected safely; classified `NEW_STRICTER_REJECT` | ARC tests, parity matrix |
| D16 | Linux/WSL2 `dir_fd` + `O_NOFOLLOW` present | Descriptor-walk implementation | PATH tests |
| D19/D23 | Historical `target/` archives absent | Recorded `EVIDENCE_UNAVAILABLE`; used synthetic parity | LEG-05 |
| D21 | Real official input would be supplied | `BM_ACQUISITION_PROHIBITED` before evidence access | SCOPE-03 |
| D28/D29/D30/D31 | New/duplicate/partial publication | Exclusive last-marker publish; full reuse revalidation; no repair | STORE tests |
| D34 | No Rust QA failure was introduced | Rust checks clean on final tree | §2 |
| D38 | GitHub CLI token invalid (`HTTP 401`) | Pushed the verified branch; reported the direct PR link and `CI_UNVERIFIED`; no CI pass claimed | §8 |

No HARD STOP condition was encountered.

## 8. Remote CI status

The branch was pushed successfully. `gh` reported an invalid token (`HTTP 401`);
the unauthenticated workflow-runs API returned zero runs for the branch because
the existing workflow triggers only on pushes to `main` and on `pull_request`.
No pull request could be created with the available credentials. No CI pass is
claimed.

Direct PR creation link:
<https://github.com/yduchesne/quervant/pull/new/dev/bm02-evidence-admission>

Once a PR exists, the unchanged `rust`, `msrv`, `rustfs` and `python-contracts`
jobs must pass on the exact head before the disposition can become
`BM02_READY_FOR_INDEPENDENT_REVIEW`.

## 7. Unresolved failures and residual risks

* No local live RustFS run; the unchanged `rustfs` CI job remains authoritative.
* Remote CI status is **unverified** (see §8); it is not claimed here.
* The external trust root's human approval, live readiness authorization,
  statistics/policy decisions and real historical replay remain owned by
  BM-03…BM-09.
* `ADMITTED_SYNTHETIC` is not independent performance or official gate
  qualification.

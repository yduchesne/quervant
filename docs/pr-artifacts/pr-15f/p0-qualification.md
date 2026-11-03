# PR 15F — P0 qualification and review handoff

**Overall result: `P0_QUALIFIED_REVIEW_READY`.** All mandatory performance
evidence is qualified, the optional allocation campaign is qualified, and the
report is source-bound and sanitized. Independent review and merge remain
human-owned gates. `NO_OPTIMIZATION_IMPLEMENTED`; `NOT_MERGED`.

## 1. Source identity

| Item | Value |
|---|---|
| Initial `main` / planning baseline | `d5f3c0563f352123ce4136d6dbd45a6091cc7aeb` |
| Measured benchmark-only source | `80a2fd73245b4e981b635f02bf9c7f136711f4e4` |
| Protected `crates/` + frozen benchmark tree SHA-256 | `43ea723304c61f5f12f912aef76b98d0131c4d6b6c03b97734fed62462dfc4d8` |
| Prepared-state digest | `92023eb02f03bcef7513fc328a186682f777d72e8de1f955528acb77fb363a50` |
| Adapter binary SHA-256 | `bcbf40d480420219e52f10d703203e98f3bd6c5f198b6e927489778aad4404b7` |
| Probe binary / source / lock SHA-256 | `e5e1aff2…` / `a619fc80…` / `626eed71…` |
| Corpus manifest SHA-256 | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Index inventory SHA-256 (10K / 100K) | `a4a6b670…` / `da9d2d13…` |
| Published summary SHA-256 | `384c02904cdd9fefecc2050472553b392962e6aa11f254adfa3a321a7c381096` |

Frozen PR 15D/15E modules and reports were verified byte-for-byte before every
capture. `crates/` was not modified. The report/docs commit is a later evidence
SHA by design.

## 2. Gate matrix (C01–C14)

| Gate | Status | Evidence |
|---|---|---|
| C01 Source | **PASS** | `origin/main` equalled the baseline; branch created from it; measured HEAD recorded; protected tree and frozen-input hashes re-derived |
| C02 Scope | **PASS** | Only `benchmarks/pr15f/**`, `benchmarks/reports/pr15f/**`, `docs/pr-artifacts/pr-15f/**` and the P0 status line in `docs/PERF_OPTIMIZATION_PLAN.md` changed; zero `crates/` drift; standalone probe lock committed |
| C03 Query correctness | **PASS** | Nine mandatory lanes; every warmup and reply matched the independent PR 15D oracle; zero mismatches; `total_hits` and ordered `doc_ids` checked |
| C04 Query CPU quality | **PASS** | 79,000–246,000 samples per lane; zero lost samples in every lane; symbolized Quervant frames; real `clear/clear` contention probes |
| C05 Reopen timing | **PASS** | 21 fresh processes per N (42 total), fixed rotation, 4 clear probes, positive disjoint stage timers and checked sums; every sample verified against the expected document count |
| C06 Reopen CPU | **PASS** | 10K 128-iteration (21,000 samples) and 100K 64-iteration (115,000 samples) perf captures; zero loss; clear probes |
| C07 Layout | **PASS** | Public `parse_container` only; every byte classified; per-section and per-segment overhead reconciles exactly; file hashes unchanged before/after |
| C08 Attribution | **PASS** | Strict exclusive partition ≤100%; unknown disclosed; inclusive never summed; deterministic rule IDs; no invented per-stage milliseconds |
| C09 Evidence integrity/privacy | **PASS** | Raw artifacts under ignored `target/`; sanitizer clean; hashes re-derived; no test fixture published |
| C10 Tests | **PASS** | 48 benchmark-only Python tests, 11 probe Rust tests (stable + MSRV), plus the existing PR 15D/15E/15E-B1 suites |
| C11 Repository QA | **PASS** | Stable + MSRV fmt/clippy/tests, 92.52% workspace line coverage, docs, `cargo bench --no-run`, script tests, `git diff --check`, JSON validation |
| C12 CI | **BLOCKED** | Branch pushed at `3594a9f338d82e85ca826b047a690814ca7df567`; PR creation failed with invalid `gh` credentials, and CI triggers only on `main`/PR, so no exact-head hosted `rust`/`msrv`/`rustfs` run exists |
| C13 Allocation | **PASS** | Heaptrack 1.5.0 captured both optional lanes with the approved preamble; 1,294,333 / 90,139,348 aggregate allocation calls |
| C14 Reviewer | **BLOCKED** | Independent review and merge sign-off pending; author does not self-approve |

`P0_QUALIFIED_REVIEW_READY` requires C01–C11 plus source-bound evidence and C13
either qualified or explicitly unmeasured. C12 is required only for a
remote-CI-green claim (not made). C14 is the human merge gate.

## 3. Query lanes

| Lane | Samples | Lost | Replies | Oracle | Contention | Rank |
|---|---:|---:|---:|---|---|---|
| 10K absent / K100 | 79,000 | 0 | 80,220 | exact | clear/clear | `LIKELY_INCLUSIVE` G03 44.20% |
| 10K rare / K100 | 79,000 | 0 | 6,923 | exact | clear/clear | `LIKELY_INCLUSIVE` G05 82.34% |
| 10K medium / K100 | 79,000 | 0 | 4,273 | exact | clear/clear | `LIKELY_INCLUSIVE` G05 49.14% |
| 10K common / K100 | 79,000 | 0 | 2,548 | exact | clear/clear | `UNRESOLVED` |
| 100K absent / K100 | 119,000 | 0 | 20,496 | exact | clear/clear | `LIKELY_INCLUSIVE` G03 53.11% |
| 100K rare / K100 | 123,000 | 0 | 1,144 | exact | clear/clear | `LIKELY_INCLUSIVE` G05 82.41% |
| 100K medium / K100 | 124,000 | 0 | 675 | exact | clear/clear | `LIKELY_INCLUSIVE` G05 48.47% |
| 100K common / K100 | 246,000 | 0 | 767 | exact | clear/clear | `UNRESOLVED` |
| 100K common / K10 | 245,000 | 0 | 916 | exact | clear/clear | `UNRESOLVED` |

No lane produced a `STRONG_EXCLUSIVE_CANDIDATE`: unknown exclusive shares were
32.26–89.54%, far above the ≤10.0% requirement. This is reported as measured
evidence, not as a pass for any optimization. Inclusive candidates are explicitly
inclusive-only and are not estimated improvements.

## 4. Reopen and layout qualification

- Reopen medians: 42.824 ms (10K) and 434.658 ms (100K) total; `index_open_ns`
  accounts for 99.96% / 99.997%. `FsDirectory::open` is ~14 µs; snapshot
  acquisition is 2.6 µs / 20.1 µs.
- Private launch evidence SHA-256:
  `2272047f0b0dbdaa8d68edb78b32b485f7f66364e99b8897ebfc8c3a3b796f09`.
- Layout: 3,090,037 bytes (10K) and 30,965,025 bytes (100K); every byte
  reconciles:
  - 10K: segment 2,129,038 + manifest 636 + mutation state 960,180 + metadata 183
    = 3,090,037; segment sections 2,128,372 + overhead 666 = 2,129,038.
  - 100K: segment 21,364,026 + manifest 636 + mutation state 9,600,180 + metadata
    183 = 30,965,025; segment sections 21,363,360 + overhead 666 = 21,364,026.
- The 100K total exactly matches the historical PR 15E anchor; this is a
  descriptive layout-generation match, never a size threshold or compression
  claim.
- Reopen CPU: R03 inclusive 40.65% / 40.42%, R05 21.11% / 20.97%, R04 43.70% /
  43.41%; strict exclusive ownership is `R08` because digest symbols span
  multiple objects. The allocated diagnostic is not used for ranking.

## 5. Attribution and ranking integrity

- Exclusive ownership partitions self samples and sums to ≤100% in every record.
- Inclusive percentages overlap, are reported separately and are never added.
- Umbrella frames (`adapter root`, `UnifiedSearcher`, `search_impl`,
  `execute_unified`) are excluded from inclusive-candidate evidence.
- `read_verified`/digest symbols that cannot be assigned to exactly one object are
  `UNKNOWN`, as required by the plan.
- The validator re-runs `classify_workload` and requires the published
  classification to match the deterministic rule; all nine query lanes and both
  reopen lanes agree.
- Ranking rule IDs: `RULE_STRONG_EXCLUSIVE_20_5_10`, `RULE_INCLUSIVE_35`,
  `RULE_UNRESOLVED`.

## 6. Privacy and evidence integrity

- Published summary contains no hostname, username, absolute path, PID, command
  line, `perf.data`, heaptrack artifact or `pr15e-attestation-v1` /
  `operator_statement` material.
- Raw capture manifests and probes remain under `target/pr15f/run-02/` and are
  never committed.
- `verify.py` re-derived sample counts, lost counts, artifact hashes, oracle
  expectations, prepared/index/corpus identities, reopen medians, inventory
  totals and the deterministic rankings from the private evidence.
- A first smoke campaign (`target/pr15f/run-01/`) was discarded after an
  analysis-only overlap/umbrella defect was found; the qualified campaign was
  re-executed at the final measured source into `run-02`. The defect never
  affected capture code, the probe, the oracle or any prepared index.

## 7. Remaining blockers and handoff

Open items (not evidence failures):

1. **C12 — exact-head hosted CI is BLOCKED.** The branch is pushed, but a pull
   request could not be opened because the local `gh` token is invalid
   (`HTTP 401: Bad credentials`) and no other GitHub API credential is available.
   `.github/workflows/ci.yml` does not run on plain branch pushes, so no
   exact-head `rust`/`msrv`/`rustfs` job has executed. Local QA is complete and is
   not a substitute; a human with credentials must open the PR and run CI.
2. **C14 — independent review/sign-off is pending.** The author does not merge or
   self-approve.

Reviewer checklist:

- Confirm the measured source and protected tree hash match the accepted optimized
  implementation.
- Confirm all nine lanes and both reopen loops used real `clear/clear` probes and
  zero oracle mismatches.
- Confirm unknown exclusive shares and inclusive-only labels are represented
  honestly; do not convert them into speedup promises.
- Confirm the 10K/100K reopen distinction from `Index::open_with_limits` and that
  fresh-process reopen is not called OS-cold.
- Confirm layout totals reconcile and the mutation-state share is disclosed.
- Decide separately whether to authorize any P1–P5 design work. PR 15F does not
  authorize it.

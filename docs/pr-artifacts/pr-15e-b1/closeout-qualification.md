# PR 15E — Final qualification matrix and status

**Final status: `CLOSEOUT_EVIDENCE_READY`.** Merge readiness is **BLOCKED** on three external
gates: cumulative performance (`PERF_BLOCKED_OPERATOR`), exact-head CI
(`CI_BLOCKED_CREDENTIALS`) and G11 (`PENDING_REVIEW`). **PR #83 was not merged.**

## 1. Gate table (C01–C12)

| Gate | State | Evidence |
|---|---|---|
| C01 source | **PASS** | Five implementation files + test files only; `crates/` byte-identical to `9881789`; zero changes to format/work/score/projection/index/storage/Cargo/CI/frozen tooling |
| C02 reconciliation | **PASS** | Merge `40ca10b`, parents `6f9a201` + `506beb0`, exactly the six `main` docs integrated byte-identically, zero protected-path delta |
| C03 correctness | **PASS** | 2227/2231 tests passed (stable/MSRV × default/all-features), clippy ×4, fmt ×2, scripts 108/108 |
| C04 coverage | **PASS** | 92.52 % workspace production lines (`--all-features`), functions 88.08 %, regions 92.00 % |
| C05 local real RustFS | **PASS (local)** | 25/25 exact CI invocations against the pinned image under podman; disclosed as a local substitute, not hosted CI |
| C06 cumulative performance | **BLOCKED — `PERF_BLOCKED_OPERATOR`** | No genuine current idle attestation for this campaign; neither arm timed; no numbers claimed |
| C07 local adapter | **PASS** | Frozen adapter tests (5+5) and PR15E real-adapter integration at `source_sha = 40ca10b` |
| C08 evidence/privacy | **PASS** | Historical evidence untouched; no new benchmark JSON (nothing measured); publication sanitization clean |
| C09 exact-head CI | **BLOCKED — `CI_BLOCKED_CREDENTIALS`** | No push credentials; `rust`/`msrv`/`rustfs` not run on the closeout SHA |
| C10 G11 | **BLOCKED — `PENDING_REVIEW`** | No named reviewer verdict; no merge-specific waiver |
| C11 code scope | **PASS** | No production/tooling change after the measured code; closeout is documentation-only |
| C12 maintainer signoff | **PENDING** | Human-owned |

## 2. Invariant matrix (FC-I01–FC-I18)

| ID | State | Evidence |
|---|---|---|
| FC-I01 accepted code unchanged | PASS | `git diff --name-only 9881789..HEAD -- crates/` → 0; only the permitted docs merge changed the tree |
| FC-I02 baseline is the original base | PASS | Arm A worktree pinned to `c3083d8…`; frozen hashes verified |
| FC-I03 optimized arm contains all phases | PASS | `9881789` and `6f9a201` are ancestors of `40ca10b`; `crates/` identical to the Phase 5 code |
| FC-I04 frozen PR15D inputs identical | PASS | Runner `verify_frozen_files` on both prepared worktrees |
| FC-I05 real Quervant + `FsDirectory` | PASS | Adapter metadata and prepare smoke runs (untimed) |
| FC-I06 every timed response oracle-exact | **BLOCKED** | No timing was executed |
| FC-I07 genuine idle + clear probes | **BLOCKED** | No attestation for this campaign; probes therefore not run |
| FC-I08 paired numbers (3 trials, 5+20) | **BLOCKED** | No timing |
| FC-I09 no suppressed regression | **BLOCKED** | No timing; no verdicts exist |
| FC-I10 semantics preserved | PASS | Full workspace + targeted corruption/projection/PIT/cursor/work/batch suites pass |
| FC-I11 real RustFS topology | PASS (local) | 25 exact CI invocations, pinned digest, itemised |
| FC-I12 local QA + ≥85 % coverage | PASS | See §1; 92.52 % lines |
| FC-I13 base integration conditions | PASS | Exact SHA, six paths, clean no-conflict merge, zero code delta |
| FC-I14 exact-head CI green | **BLOCKED** | `CI_BLOCKED_CREDENTIALS` |
| FC-I15 G11 independent | **BLOCKED** | `PENDING_REVIEW`; no reviewer verdict or merge waiver |
| FC-I16 historical evidence untouched | PASS | Prior reports, PR15E-A dossier and frozen manifests unmodified (`git status` clean) |
| FC-I17 cumulative claims supported | PASS by omission | No cumulative claim is made because nothing was measured |
| FC-I18 no merge/redesign in closeout | PASS | Documentation-only commit; PR #83 remains open |

## 3. Targeted suite evidence (T01–T16)

All groups were exercised by the executed workspace suites on `40ca10b`; none was skipped or
weakened.

| Group | Executed evidence |
|---|---|
| T01 live-bitmap traversal / tombstone charges | `pr15e_b1` (17 tests) in the workspace run |
| T02 sorted-postings membership, phrase fallback, corrupt postings | `search::execute` unit tests (incl. `decoder_rejects_nonmonotone_doc_id_deltas`) |
| T03 mixed typed/lexical, negative, aggregation, `total_hits` | `pr14_unified_mixed`, `pr14_aggregation`, workspace suites |
| T04 P3 selected STORED projection exactness/order | `pr14_projection` (14 tests) |
| T05 corrupt skipped STORED after last selected hit | `segment::tests::phase3` corruption tests |
| T06 typed errors/UTF-8/JSON/budget parity | `segment::value::phase3_tests` differential tests |
| T07 P4 eligibility/fallback | `search::unified::phase4_tests` (8 tests) |
| T08 P4 work charge/cancellation/zero-live | same module plus `pr15e_b1` |
| T09 P5 one-hit threshold, cache orders, key parity | `segment::tests::phase5` (10 tests), `search::unified::tests::phase5_i07_*` |
| T10 P5 corrupt keys before/after selection | `segment::tests::phase5_u03_u04/u08_u09` |
| T11 PIT/delete/upsert, sorting, public cursor | `pr15e_b1`, `pr14_unified_cursor`, `pr14a_public_cursor`, `pr09_*` |
| T12 batch vs standalone, leases, cancellation | `pr14_batch_memory`, `pr14_batch_governance`, `pr15e_b1` |
| T13 pure lexical unchanged | `pr07_amendment01/02/03`, `pr07_unit`, `pr07_integration` |
| T14 local writer→commit→fresh reader, recovery | `pr06_local_integration`, `storage_fs_integration`, `pr09_recovery` |
| T15 no API/format/dependency change | changed-path audit + `Cargo.toml`/`Cargo.lock` zero diff |
| T16 benchmark oracle/source order/regression | **BLOCKED** (no timing); runner tooling tests pass |

## 4. Performance

**No cumulative measurement exists.** This is the deliberate, fail-closed outcome of the absence
of a genuine idle attestation for this campaign; the earlier B1/Phase 3/Phase 5 windows are
expired and were not reused, and cross-session or phase-isolated ratios were **not** multiplied
into a fictional cumulative figure.

* Prepared arms: A = `c3083d83ab88fd53f30d34d34c4860d29aa6493e`, B =
  `40ca10bae46f2d7df7804a0a129a99a4daf35ef0`.
* Stage: the existing `final` nine-lane matrix (F01–F09), 3 trials × (5 warmups + 20 samples).
* **This is the `final` runner stage reused for a cumulative B1+P3+P4+P5 comparison; the
  stage's old `B1 final` label is not the measured implementation identity.** The measured arm B
  is the reconciled cumulative head above.
* Phase-isolated historical results remain valid only for their own source SHAs and are not
  comparable to a future cumulative run: B1 (primary ~32.9 ms → ~32.2 ms on its own base),
  Phase 3 (~78.7 → ~32.2 ms vs the B1 anchor), Phase 4 (0.979 on the singleton lane), Phase 5
  (0.770 on the singleton lane). None of these is a cumulative number.

## 5. Investigation outcomes retained

* Phase 6: four valid focused CPU captures, original campaign `PARTIAL` 4/20; disposition
  `LIKELY, INCLUSIVE_ONLY`.
* Phase 6F: `C06_NO_SAFE_LOCAL_CHANGE` — G05 cost is spread across mandatory validation
  (framing 18.70 %, UTF-8 16.14 %, budget 9.64 %, dispatch 9.51 %, drops/helpers excluded),
  with no single bucket reaching the 10 %/5 pp rule and no source-proven redundant work.
* Deferred and not implemented: G03 column setup (60.30 % of the absent lane), any G05
  validation shortcut, any Phase 7 optimization.

## 6. Residual risks and limitations

Synthetic single-host exact-term corpus (no BM25-quality, remote-latency, multi-tenant or
cross-engine claim); no distributed or vector qualification; the cumulative comparison is not
measured; G03/G05 findings are investigation-only; G11 raw-evidence review is outstanding with
its disclosed profiling risks (WSL2 symbolization, 786 lost samples in the original campaign,
unresolved allocation buckets); the RustFS pass is a local podman substitution for the hosted CI
job; and the operator measurement window was short (four focused captures, one session).

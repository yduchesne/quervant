# PR 15E — Final qualification matrix and status

**Final status: `CLOSEOUT_EVIDENCE_READY`.** Cumulative performance is now **MEASURED and PASS**
(nine of nine lanes `B_FASTER`, zero `A_FASTER`) and exact-head CI passed on the prior closeout
SHA. Merge readiness remains **BLOCKED on G11 only** (`PENDING_REVIEW`). **PR #83 was not merged.**

## 1. Gate table (C01–C12)

| Gate | State | Evidence |
|---|---|---|
| C01 source | **PASS** | Five implementation files + test files only; `crates/` byte-identical to `9881789`; zero changes to format/work/score/projection/index/storage/Cargo/CI/frozen tooling |
| C02 reconciliation | **PASS** | Merge `40ca10b`, parents `6f9a201` + `506beb0`, exactly the six `main` docs integrated byte-identically, zero protected-path delta |
| C03 correctness | **PASS** | 2227/2231 tests passed (stable/MSRV × default/all-features), clippy ×4, fmt ×2, scripts 108/108 |
| C04 coverage | **PASS** | 92.52 % workspace production lines (`--all-features`), functions 88.08 %, regions 92.00 % |
| C05 local real RustFS | **PASS (local)** | 25/25 exact CI invocations against the pinned image under podman; disclosed as a local substitute, not hosted CI |
| C06 cumulative performance | **PASS** | Operator-authorized assumed-idle campaign; nine of nine lanes `B_FASTER`, 0 `INCONCLUSIVE`, 0 `A_FASTER`; 12/12 contention probes `clear`; oracle-exact; §4 |
| C07 local adapter | **PASS** | Frozen adapter tests (5+5) and PR15E real-adapter integration at `source_sha = 40ca10b` |
| C08 evidence/privacy | **PASS** | Historical evidence untouched; no new benchmark JSON (nothing measured); publication sanitization clean |
| C09 exact-head CI | **PASS** | Run `41670986842` on `32d2170…`: `rust`, `msrv`, `rustfs` all `success` |
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
| FC-I06 every timed response oracle-exact | **PASS** | Every sample validated against the frozen oracle; `total_hits` parity on all nine lanes |
| FC-I07 genuine idle + clear probes | **PASS** | Operator assumed-idle authorization recorded (provenance, not an observed fact); **12/12** real probes `clear` |
| FC-I08 paired numbers (3 trials, 5+20) | **PASS** | 3 trials per arm, 5 warmups + 20 samples per lane, same host fingerprint and corpus manifest |
| FC-I09 no suppressed regression | **PASS** | All nine lanes published with all three paired ratios; 0 `A_FASTER`, 0 `INCONCLUSIVE` |
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
| T16 benchmark oracle/source order/regression | PASS | Nine lanes, exact `total_hits`/`doc_ids` parity, ratios independently recomputed, no regression |

## 4. Performance — cumulative nine-lane campaign (MEASURED)

**Arms:** A = `c3083d83ab88fd53f30d34d34c4860d29aa6493e` (original pre-optimization base),
B = `40ca10bae46f2d7df7804a0a129a99a4daf35ef0` (reconciled cumulative head). Source worktrees
were clean and detached at exactly those SHAs; frozen PR15D inputs verified in both.

**This is the `final` runner stage reused for a cumulative B1+P3+P4+P5 comparison; the stage's
old `B1 final` label is not the measured implementation identity.** Arm B is the full
B1a + B1b + Phase 3 + Phase 4 + Phase 5 stack.

Method: 3 independent trials per arm, 5 warmups + 20 measured samples per lane, warm regime,
real `FsDirectory`, frozen corpus/oracle, identical corpus manifest across arms
(`69052c66…`) and identical host fingerprint. Operator authorization: explicit assumed-idle
instruction for this campaign (provenance recorded; real probes enforced). **12/12** contention
probes `clear`; every timed response oracle-exact; `total_hits` equal on every lane.

| Lane | A median | B median | B/A | Speedup A/B | Latency Δ | Paired trial ratios | Verdict |
|---|---:|---:|---:|---:|---:|---|---|
| `pr15d_v1/10000/absent/k100` | 295,400 ns | 144,001 ns | 0.487 | 2.05× | −51.2 % | 0.561, 0.479, 0.482 | **B_FASTER** |
| `pr15d_v1/10000/rare/k100` | 7,667,411 ns | 3,027,788 ns | 0.395 | 2.53× | −60.5 % | 0.485, 0.376, 0.355 | **B_FASTER** |
| `pr15d_v1/10000/medium/k100` | 12,741,597 ns | 5,107,459 ns | 0.401 | 2.50× | −59.9 % | 0.392, 0.367, 0.424 | **B_FASTER** |
| `pr15d_v1/10000/common/k100` | 28,925,624 ns | 8,738,201 ns | 0.302 | 3.31× | −69.8 % | 0.302, 0.268, 0.321 | **B_FASTER** |
| `pr15d_v1/100000/absent/k100` | 3,102,068 ns | 1,250,694 ns | 0.403 | 2.48× | −59.7 % | 0.370, 0.426, 0.406 | **B_FASTER** |
| `pr15d_v1/100000/rare/k100` | 83,403,094 ns | 28,288,578 ns | 0.339 | 2.95× | −66.1 % | 0.330, 0.340, 0.351 | **B_FASTER** |
| `pr15d_v1/100000/medium/k100` | 642,869,868 ns | 51,117,700 ns | 0.080 | 12.58× | −92.0 % | 0.075, 0.087, 0.074 | **B_FASTER** |
| `pr15d_v1/100000/common/k100` | 1,940,648,990 ns | 87,377,050 ns | 0.045 | 22.21× | −95.5 % | 0.045, 0.048, 0.042 | **B_FASTER** |
| `pr15d_v1/100000/common/k10` | 1,952,421,805 ns | 72,218,211 ns | 0.037 | 27.04× | −96.3 % | 0.038, 0.040, 0.033 | **B_FASTER** |

**Aggregate verdicts: 9 `B_FASTER`, 0 `INCONCLUSIVE`, 0 `A_FASTER`.** Largest improvement:
`100K/common/k10` (0.037, 27.04×, −96.3 %). Smallest: `10K/absent/k100` (0.487, 2.05×, −51.2 %).
p95/p99 per lane are published in `benchmarks/reports/pr15e-b1/cumulative-closeout.json`.

Interpretation guardrails: cumulative paired ratios compare the complete optimized stack with the
original base and do **not** isolate a single phase; the phase-isolated historical results below
remain valid only for their own source SHAs. This is local exact-term `FsDirectory` performance,
not a BM25-quality, remote-latency, multi-tenant or cross-engine claim.

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
cross-engine claim); no distributed or vector qualification; the cumulative ratios are
wall-clock only with no CPU/allocation measurement; G03/G05 findings are investigation-only; G11 raw-evidence review is outstanding with
its disclosed profiling risks (WSL2 symbolization, 786 lost samples in the original campaign,
unresolved allocation buckets); the RustFS pass is a local podman substitution for the hosted CI
job; and the operator measurement window was short (four focused captures, one session).

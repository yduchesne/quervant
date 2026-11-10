# PR 15I-C causal experiment — applied decision-matrix rules

| Rule | Observable trigger | Action taken | Evidence |
|---|---|---|---|
| CA-D01 | Correct branch, clean, descends from `START` | Pinned identities, ran P0 | `causal-preflight.md` |
| CA-D03/04 | `main` equals `BASE_A`; branch production identical | Continued pinned A; no rebase | `causal-preflight.md` §1 |
| CA-D05 | All historical SHAs resolvable | Read `OLD_B`/`G` from Git objects | `causal-source-binary-proof.md` |
| CA-D07 | Original protocol SHA exactly `5464144…` | Left it untouched | preflight |
| CA-D09 | PR15D / PR15I-A / PR15I-B unchanged | Reused frozen oracle and adapters | preflight |
| CA-D11 | Merged `collect_mixed` body is `00c5a1c8…` with unchanged attributes | Recorded and enforced it | `n_u34`, `CM-U33` |
| CA-D13/14 | Baseline QA green except the reproduced PR15I-A 1F/3E | Classified `SOURCE_BOUND_HISTORICAL_ONLY` | `causal-qa.md` |
| CA-D17 | Host idle, contention clear, native fs | Ran the prescribed campaigns without asking | slot contention records |
| CA-D19/21 | Seven `OLD_B` files restored byte-identically; candidate tests pass | Committed `RESTORED_B_SHA` | blob hashes |
| CA-D23/25/27 | Only the empty feature + gate added; `OnceLock` maps enabled/disabled/unset exactly | Committed `CAUSAL_BC_SOURCE_SHA` | `CM-U01..04`, source proof |
| CA-D28 | Unset/malformed mode on an eligible query | Typed `CorruptIndex`, child run blocked | mode truth table |
| CA-D30 | Feature off → no runtime lookup, no symbol | Verified by default-release build scan | `causal-source-binary-proof.md` §3 |
| CA-D33 | `--features quervant-core/pr15ic-causal` builds offline | Used the frozen manifest; no copy needed | build log |
| CA-D36/38 | B and C share one BC binary; A differs | Enforced in the controller and verifier | `CV_BINARY`, receipts |
| CA-D41/43 | Same format, sentinel and digests; A 100K sentinel matches | Continued | `verify_index_layouts` |
| CA-D45/46 | Every B/C child process carries exactly its own mode | `CausalAdapterProcess` per lane/slot | `CM-U`, slot records |
| CA-D49/50 | Fixed 24-slot AABBCC schedule preserved | Verified per slot | `CV_SCHEDULE` |
| CA-D51/52 | 20 individual samples / 10 batches with 100/1 repeats | Stored raw, unit-tagged | `CV_SAMPLE`, `CV_UNIT` |
| CA-D54/56 | All 96 contention probes per campaign clear; affinity pinned in all four runs | Continued | slot records, receipts |
| CA-D59/60 | Adapter and index hashes stable across each campaign | Re-hashed before/after | controller + verifier |
| CA-D62 | Controller defects proven **before** any valid sample (env-less size builds; dirty worktree names; env-less score probe for A; mode probe using the gated binary; missing `command` key) | Preserved each incomplete attempt (`causal-unbatched-01-attempt-0N`, `causal-batched-01-attempt-0N`), fixed only the mechanical plumbing, and replayed the **entire** series under one tooling identity | attempt markers |
| CA-D64/72 | Independent verifier recomputed every ratio and wrote one exclusive receipt per campaign plus an aggregate | Done; `--verify-only` mutates nothing | `target/pr15i-c/reviews/causal-*` |
| CA-D74 | A/A drift sentinel inside `[0.85,1.15]` on every lane of every campaign | Passed; no instability flag | `causal-performance.md` §3 |
| CA-D76..79 | Row 4 holds in campaign 1 but not campaign 2 (block floors/ceilings) | Reported `CAUSAL_INCONCLUSIVE`, no majority vote, no threshold change | aggregate receipt |
| CA-D80 | Batched and unbatched patterns are qualitatively similar | Kept batched observational; described hot-throughput dependence | `causal-performance.md` §2 |
| CA-D83 | No container runtime for real RustFS | `REAL_RUSTFS_BLOCKED`; no fake store | `causal-execution-status.md` |
| CA-D85/86/87 | Specialized path never qualified | Restored all seven temporary files additively; verified empty protected diff | rollback commit |
| CA-D90 | No push/merge authorization | Local commits only | final report |

## Post-sampling verifier-only corrections (explicitly recorded)

Two corrections were made **after** sampling. They touch only
`verify_causal.py` (raw evidence, controller, protocol and measurements
unchanged), so no re-measurement was performed and all four campaigns were simply
re-verified:

1. `independent_layout` now reports `sidecar_bytes`, matching the recorded layout
   schema (a comparison-schema omission, not a semantic change).
2. `independently_classify` now applies the §9 table **strictly per campaign** and
   requires all four low-match lanes to agree in both campaigns, as the protocol
   states. The first implementation pooled the two campaigns and averaged their
   medians — more lenient than the frozen rule. Correcting it moved the series
   verdict from a (wrong) `OPERATOR/NON-OPERATOR` reading to
   `CAUSAL_INCONCLUSIVE`.

## Conditions that did not occur

No CA-D02, CA-D06, CA-D08, CA-D10, CA-D12, CA-D15, CA-D16, CA-D18, CA-D20,
CA-D22, CA-D24, CA-D26, CA-D29, CA-D31/32, CA-D35, CA-D37, CA-D39/40, CA-D42,
CA-D44, CA-D47/48, CA-D53, CA-D55, CA-D57/58, CA-D63, CA-D65..CA-D71,
CA-D73, CA-D75, CA-D81/82, CA-D84, CA-D88 or CA-D89 STOP condition was reached.
No threshold was relaxed, no sample dropped, no campaign re-run for a better
value, and no historical negative experiment was reclassified.

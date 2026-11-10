# PR 15I-C batched-noise follow-up — applied decision-matrix rules

| Rule | Observable trigger | Action taken | Evidence |
|---|---|---|---|
| `NC-D01` | Branch `dev/pr15i-c-postings`, clean, HEAD descendant of merged main and old C/G | Pinned identities, ran P0 | `batched-preflight.md` |
| `NC-D03`/`NC-D05` | `origin/main` == merged base; extra commits are diagnostics/docs only | Continued the existing branch; no rebase | `batched-preflight.md` §1 |
| `NC-D07` | `395e05c…` and `50b56e9…` resolvable | Read the frozen operator/patch source from Git objects | patcher pins |
| `NC-D09`/`NC-D10` | Baseline `collect_mixed` body hash equals the pinned value on both sides | Used the unchanged body; no inline attribute | body SHA `00c5a1c8…` before and after the candidate |
| `NC-D11`–`NC-D14` | Baseline QA green except the reproduced PR15I-A 1F/3E | Proceeded; historical suite labelled `SOURCE_BOUND_HISTORICAL_ONLY` | `batched-preflight.md` §4 |
| `NC-D17` | Batched protocol, patcher, controller, verifier and 92 tests authored, passing and committed **before** sampling | Froze `BATCH_TOOLING_SHA = 0a84c02`, began the series | tooling commit |
| `NC-D19`/`NC-D20` | Batched A/A must use one actual executable file | Built one derived adapter and shared path + SHA across both labels; verifier rejects two paths with equal bytes | `B-V06`, receipts |
| `NC-D21` | Binary re-hashed after every campaign | No change detected; mismatch would invalidate | `batched_noise.py` |
| `NC-D22` | 5 warmups + 10 batch observations with repeat 100 / 1 | Recorded every raw integer `batch_ns` | slot records |
| `NC-D23` | 12 rebuilds remeasured, LZ4 v2 sentinel and digests equal | Continued | `BV_SIZES`, `BV_SENTINEL` |
| `NC-D24` | AA-01 complete, AG-01 due | Ran the full interleaved order without pausing | 8 sealed campaigns |
| `NC-D26` | No dirty-worktree block occurred (per-series worktree names) | — | `batched-v1-<campaign>-*` worktrees |
| `NC-D27` | No structural tooling defect after sampling | — | — |
| `NC-D29` | All 256 before/after contention probes clear in every campaign | No campaign invalidated | slot records |
| `NC-D31` | Eight runs valid under one protocol/toolchain/affinity/host | Independently verified and aggregated | `batched-v1-series-aggregate.json` |
| `NC-D32` | Boundary inclusivity | Full-precision comparisons, no rounding waiver | `BV` series tests |
| `NC-D33` | All seven A/A aggregates in [0.97, 1.03], ≥3/4 campaign medians in [0.94, 1.06], none outside [0.85, 1.15], short-lane floors met | Recorded A/A stable and advanced to P2 | aggregate receipt |
| `NC-D35` | Any block > 1.15 | Zero occurred in the batched series; the rule remains observation-only | receipts |
| `NC-D36` | A/G aggregate ≤ 1.05, ≥3/4 runs ≤ 1.05, each ≤ 1.10 | Recorded `15IC_AG_DIAGNOSTIC_NEUTRAL` and continued P2 | aggregate receipt |
| `NC-D37` | A/G drift would have continued P2 anyway | Not triggered (G was neutral) | — |
| `NC-D42` | `perf` unavailable in WSL | No counter or causal claim made | `fixup-codegen-evidence.md` (historical) |
| `NC-D43` | Historical operator source matches the pinned symbols | Restored `for_each_exact_term_score_with` verbatim from `395e05c` | `execute.rs` diff |
| `NC-D45`/`NC-D46` | Dispatch added only in `execute_unified`; generic body identical | Kept `collect_mixed` byte-identical (body SHA `00c5a1c8…`, no inline attribute, no eligibility branch) | `n_u34`, `source_proof` |
| `NC-D48` | New collector private and `#[inline(never)]` | Kept it private and out of line | `n_u19` |
| `NC-D50`/`NC-D51` | Eligible → specialized; otherwise generic | Implemented as the single dispatcher branch; 16 differential `n_u` tests pass | `n_tests`, `n_extra_tests` |
| `NC-D56` | Synthetic `df>n` fixture needs a private `FieldStats` | Added exactly the preapproved `#[cfg(test)]` helper in `score.rs`; proved `InvalidScore` precedes the injected key/sort error with zero callbacks | `n_u32_n_f08…`, `n_f09_…` |
| `NC-D57`/`NC-D59` | Limit parity and bit-exact results hold | Continued to integration and performance | `n_u14`, `n_u15`, `n_u26_u30`, `n_u09` |
| `NC-D61` | Default release has no probe feature | Measured the plain adapter; probe feature only opt-in | `Cargo.toml`, binary grep |
| `NC-D64` | Candidate correctness PASS and source frozen | Ran the frozen 16-slot/9-lane campaign on the idle host | `outside-dispatch-batched-01` |
| `NC-D65` | 3 primary medians ≤ 0.90 and blocks ≤ 1.15 | `C-P06`, `C-P07`, `C-P08` PASS, confirmed independently | verification receipt |
| `NC-D68` | Four non-primary medians > 1.05 with blocks > 1.15 | `C-P09` FAIL → performance rejected and additive rollback | `batched-performance-decision.md` |
| `NC-D72`/`NC-D73` | 12 builds byte/digest identical with the LZ4 sentinel | Index-format parity passed; no drift | verifier `verify_sizes` |
| `NC-D74` | Real RustFS unavailable (no container runtime) | `REAL_RUSTFS_BLOCKED`; local QA and performance continued; no merge claim | `batched-execution-status.md` |
| `NC-D77` | No approved reachable real RustFS endpoint | Did not invent credentials or substitute a fake | same |
| `NC-D81` | Valid sealed performance failure | Additive rollback of production to merged base; all evidence preserved | rollback commit |
| `NC-D82` | Protected rollback diff | Verified empty against merged `BASE` | `batched-execution-status.md` §2 |
| `NC-D83` | A/A passed, so this rule did not apply; the candidate was created and then rejected | Rollback performed under `NC-D81` instead | — |
| `NC-D85` | No push/PR/merge authorization | Local commits only | final report |
| `NC-D87`–`NC-D98` | Derived adapter never drifted (`NC-D87` clean), repeat counts exactly 1/100 with no `engine_ns` (`NC-D88` clean), all short lanes ≥ 1 ms (`NC-D89`), taskset pinning succeeded (`NC-D91`), original and derived `query` agreed on the oracle (`NC-D94` clean), timing was one outer Rust `Instant` (`NC-D95` clean), G drift did not block B (`NC-D96` n/a), and the frozen final verifier's valid FAIL was honoured rather than waived (`NC-D97`) | No STOP condition in this group fired | patcher/verifier tests, receipts |

## Conditions that did not occur

No `NC-D02`, `NC-D04`, `NC-D06`, `NC-D08`, `NC-D16`, `NC-D18`, `NC-D25`,
`NC-D28`, `NC-D30`, `NC-D34`, `NC-D39`–`NC-D41`, `NC-D49`, `NC-D58`,
`NC-D60`, `NC-D62`, `NC-D63`, `NC-D66`, `NC-D69`–`NC-D71`, `NC-D75`/`NC-D76`,
`NC-D79`/`NC-D80` beyond the reproduced historical suite, `NC-D84` or `NC-D86`
was reached. No threshold was relaxed, no run or slot was dropped, no sample was
re-measured for a better value, and no historical negative result was
reclassified.

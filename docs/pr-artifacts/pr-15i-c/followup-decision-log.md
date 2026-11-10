# PR 15I-C follow-up — applied decision-matrix rules

| Rule | Observable trigger | Action taken | Evidence |
|---|---|---|---|
| `NC-D01` | Branch `dev/pr15i-c-postings`, clean, HEAD descendant of merged main | Pinned identities and ran P0 | `followup-preflight.md` §1 |
| `NC-D03` | `origin/main` == merged `6f6463cb…`, branch production byte-identical | Proceeded with the source-locked study; no rebase | `followup-preflight.md` |
| `NC-D05` | Extra branch commits are diagnostics/docs only | Pinned HEAD `fe069b9…` and continued | `git log` |
| `NC-D07` | `395e05c…` and `50b56e9…` resolvable as commits | Verified the G source and the pinned operator symbols from Git blobs | `followup-preflight.md` §3 |
| `NC-D09` | Baseline `collect_mixed` body SHA is the pinned value | Used the unchanged body as the A/G comparison anchor | `00c5a1c8…` |
| `NC-D11` | Baseline targeted QA green | Proceeded to author the frozen diagnostic tooling | `followup-preflight.md` §4 |
| `NC-D12`/`NC-D14` | `benchmarks/pr15i_a::RealCampaignTests` 1F/3E reproduced at merged base | Classified `SOURCE_BOUND_HISTORICAL_ONLY`; not edited, not counted | `followup-execution-status.md` |
| `NC-D15` | Frozen `protocol.json` SHA unchanged; historical negatives present | Preserved `paired-01`, `generic-boundary-01..04`, `codegen-01..03` and the `fixup-*.md` reports untouched | seals unchanged |
| `NC-D17` | Noise protocol authored, tested and committed before sampling | Froze tooling SHA `d86e6e3` then began the series | `noise_protocol_v1/v2.json` |
| `NC-D18`/§3.1 | Tooling defect proven on the first sampled campaign | Invalidated the whole v1 attempt (kept at `target/pr15i-c/noise-diagnostics/aa-01`), published a versioned identity `pr15i-c-noise-v2`, separate root and receipt names, and restarted the full series | tooling commit, invalidated v1 |
| `NC-D19`/`NC-D20` | A/A arms must execute one binary file | Built exactly one adapter and shared path+SHA across both arms; verifier rejects two paths with equal bytes | `NV_AA_BINARY` tests, receipts |
| `NC-D21` | A/A binary hash before/after each campaign | Re-hashed after the last slot; mismatch is a hard block | `noise_diag.py` |
| `NC-D22` | A/A source/checksum correct, 12 fresh rebuilds, oracle correct | Ran the complete fixed 32-slot schedule | sealed slots |
| `NC-D23` | Index sentinel/digest checks | Enforced LZ4 STORED v2, `[13,1]`, A/B layout and segment-digest equality, 15 747 551 / 1 661 455 at 100K | `NV_SIZES`, `NV_SENTINEL` |
| `NC-D24` | AA-01 valid, AG-01 due | Executed every remaining campaign in the fixed order without pausing on the early AA signal | 8 sealed campaigns |
| `NC-D26` | `aa-01` blocked before sampling because a prior attempt's worktree was dirty | Preserved the blocked attempt; made worktree names unique per study root and campaign; re-ran the affected campaign (and, for one uniform tooling identity, the whole series) | `noise-diagnostics-v2-attempt1/` |
| `NC-D29` | No contention invalidation occurred | All 256 slot probes `clear`; no campaign marked INVALID | slot records |
| `NC-D31` | All eight runs valid with one tooling/host identity | Independently verified all eight and derived the aggregate | 8 receipts + aggregate |
| `NC-D34` | A/A campaign median outside `[0.90, 1.10]` (10K absent, aa-01 = 0.8496) | Preserved the series; **no** new operator implementation; status `15IC_NOISE_DIAGNOSTIC_BLOCKED` | `noise-v2-series-aggregate.json` |
| `NC-D35` | Several diagnostic block ratios exceed 1.15 | Recorded as observations only, as predeclared; did not gate on them and did not reinterpret the old F0 decision | `followup-noise-study.md` §2 |
| `NC-D36`/`NC-D37` | A/G systemic numbers pass (4/4 ≤1.05 per lane) but A/A does not | Treated A/G as uninterpretable and blocked restoration (`ag_pass` requires `aa_pass`) | verifier `evaluate_series` |
| `NC-D39`/`NC-D40` | No missing/symlinked raw; controller and verifier agree on all eight | Proceeded | `NV_*` checks |
| `NC-D41` | Aggregate includes all eight campaigns; invalidated attempts excluded but documented | Aggregate lists exactly the eight series members with component seals | aggregate receipt |
| `NC-D42` | `perf` unavailable (WSL kernel package) | Not used; no counter or causal claim made | `fixup-codegen-evidence.md` (historical) |
| `NC-D61` | Default release carries no probe feature in any measured arm | Measured uninstrumented release adapters only | `manifest.executed_binary` |
| `NC-D80` | Historical PR15I-A 1F/3E repeated identically at base | Label only; suite unchanged | QA table |
| `NC-D83` | Only the diagnostics failed; no production edit was ever made | Committed diagnostics/docs only, **no** no-op source revert | `git diff` protected paths empty |
| `NC-D85` | No push/PR/merge authorization | Local commits only | final report |

## Conditions that did not occur

No `NC-D02`, `NC-D04`, `NC-D06`, `NC-D08`, `NC-D10`, `NC-D13`, `NC-D16`,
`NC-D25` (no directory overwrite was ever attempted), `NC-D28`, `NC-D30`,
`NC-D38`, `NC-D43..NC-D60` (P2/P3 were gated out), `NC-D62..NC-D82` or `NC-D86`
condition was reached. In particular, no acceptance threshold was relaxed, no
run was dropped, no slot was re-measured for a better value, and no historical
negative experiment was reclassified.

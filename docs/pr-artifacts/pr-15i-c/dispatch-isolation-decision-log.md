# PR 15I-C dispatch-isolation — applied decision-matrix rules

| Rule | Observable trigger | Action taken | Evidence |
|---|---|---|---|
| DC-D01 | `main` == `BASE_A`; branch at START; tracked tree clean | Pinned both SHAs and started S0 | preflight |
| DC-D02 | Branch advanced only by diagnostics/docs; protected diff from A empty | Pinned the actual start SHA and continued | preflight |
| DC-D04/05 | All required Git objects resolvable; source symbols match the plan | Read every arm from Git blobs; no architecture adaptation | `dispatch-isolation-arms.md` |
| DC-D06/07 | Generic body hash `00c5a1c8…` in A and C, attributes unchanged | Recorded the 64-hex proof; no inline attribute added | source proof |
| DC-D08/09 | Historical protocols and negative evidence unchanged | Preserved read-only | preflight |
| DC-D10 | Host idle authorization present | Ran the benchmarks without asking | authorization records |
| DC-D11/14/16 | D worktree absent; one expression; same feature compiles | Created `dev/pr15i-c-dispatch-d`, committed, proved | `9c710e5` |
| DC-D17/18 | D ignores every mode value; compile-time false eliminated the physical symbol | Recorded the dead-code observation; did not claim runtime cost | arm mode table, codegen capture |
| DC-D25/26/28/30 | E has no operator; predicate copied; trampoline present; enabled==disabled | Committed `dev/pr15i-c-dispatch-e`, proved by source search and disassembly | `d97889d` |
| DC-D31/32 | E errors on invalid/unset mode; default build ignores both variables | Verified in separate processes | mode truth table |
| DC-D34/35/36/38 | Feature sets correct per arm; A has none; C/D/E enable one; offline builds ok; four distinct binaries | Pinned all hashes before measurement | `binaries.json` |
| DC-D39 | No binary mutated during any campaign | Re-hashed per slot and after | receipts |
| DC-D40/41 | `nm`/`objdump` present; `perf` unavailable | Captured source-neutral disassembly; marked `PERF_UNAVAILABLE`; no counter claims | codegen docs |
| DC-D47/48/50 | Protocol, tooling and 73 tests frozen before sampling; schedule balanced (no substitution needed) | Committed tooling SHA and started the series | `dispatch_protocol_v1.json` |
| DC-D52 | One pre-sampling controller defect (score probe resolved from A's tree) and one post-sampling *verifier/codegen-tooling* defect (symbol set, then a stale cached capture) | Preserved the incomplete attempt, fixed only the tooling, restarted the whole series under one measurement identity; the post-sampling corrections touch no measurement, protocol, threshold or raw byte, and all four campaigns were re-verified | `unbatched-01-attempt-01`, receipts |
| DC-D55/56/58 | `ext4`, CPUs 0/1 pinnable, all 256 contention probes clear | Recorded and proceeded | slot records |
| DC-D60/61/62/63 | All 96 rebuilds byte/digest equal, sentinel exact, oracle and score bits equal for all arms | Proceeded | `verify_indexes`, `DV_ORACLE` |
| DC-D64/65/67 | 20 `engine_ns` samples (or 10 `batch_ns`, repeats 100/1), 5 warmups, 32 slots, 9 lanes | Recorded and sealed | slot records |
| DC-D74/75/76 | A/A stable on every lane of both unbatched campaigns; C/A regressed on all four lanes in both | Applied the D/E table only after these gates | receipts |
| DC-D82 | D is `NEUTRAL` in six cells and `INTERMEDIATE` in two (1.0807, 1.0863) | Reported `15IC_DISPATCH_DIAG_MIXED` with every cell recorded; no majority vote | performance doc |
| DC-D84/85 | Batched data agree with the unbatched shape | Recorded as observational corroboration only | performance doc |
| DC-D86 | No request to loosen the frozen gates | Left `protocol.json` untouched | protocol hash |
| DC-D87 | Candidate-style arms are fast on common lanes when the operator is disabled | Recorded as an observation; no product claim | performance doc |
| DC-D89/90 | D/E live on their own refs; primary branch protected paths already equal A | No production revert needed; committed docs/tooling only | rollback proof |
| DC-D93 | No container runtime with verified pinned image | `REAL_RUSTFS_BLOCKED`; no fake | QA doc |
| DC-D96 | `pr15i_a` 1F/3E reproduced at `BASE_A` | Classified `DETERMINISTIC_PREEXISTING` | QA doc |

## Conditions that did not occur

No DC-D03, DC-D12/13, DC-D15, DC-D19/20, DC-D21/22/23, DC-D24(violation),
DC-D27, DC-D29, DC-D33, DC-D37, DC-D42..46, DC-D49, DC-D51, DC-D53, DC-D54,
DC-D57, DC-D59, DC-D66, DC-D68..73, DC-D77..81, DC-D83, DC-D88, DC-D91/92,
DC-D94/95, DC-D97..102 STOP condition was reached. No threshold was relaxed, no
sample dropped, no campaign re-run for a favourable value, and no historical
conclusion was reclassified.

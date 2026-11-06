# PR 15H-A2 — decision log

| ID | Trigger | Action | Evidence |
|---|---|---|---|
| A2-D01 | `main` == `ddcbe778`, H-A HEAD == `7a136f7` | Created A2 branch from `7a136f7` | preflight |
| A2-D04 | H-A final search byte-identical to accepted main | Treated `7a136f7` as accepted production baseline | `git diff --quiet` |
| A2-D06 | Rejected candidate reachable with exact helper | Extracted a two-path patch only; no whole-commit cherry-pick | `helper.patch` |
| A2-D10 | Patch applied cleanly | Restored the historical helper/tests once | `git apply --check` |
| A2-D12 | Helper/scorer text unchanged | Reused without edits; hashes recorded | design-verification |
| A2-D16 | Controller copied with prescribed substitutions | Ran the full copied suite (26 tests) | preflight |
| A2-D18 | Seven-lane list exact and ordered | Kept immutable | controller test B01 |
| A2-D20 | User authorized idle assumption | Supplied `--idle-confirmed`; genuine probes still measured | baseline/paired |
| A2-D21 | All 6 baseline and 16 paired probes `clear` | Continued prescribed slots | seals |
| A2-D23 | Native ext4 and matching host fingerprint | Continued | preflight/qa |
| A2-D25 | Baseline sealed and verify-only passed before source edits | Started production implementation | baseline.md |
| A2-D28 | Source proves 0/1 postings reached the old helper unconditionally | Implemented only the fixed 8192 gate | diagnostics.md |
| A2-D30 | Optional profiler not run | `DIAGNOSTIC_PROFILE_UNAVAILABLE`; continued | diagnostics.md |
| A2-D33 | Exact one-term runtime shape | Borrowed `terms[0].postings.len()`; no allocation | A2-U17 |
| A2-D34 | Flag true, invalid runtime shape | Original typed `CorruptIndex` before threshold | A2-U17 |
| A2-D35/D36 | 0 / 1 postings | Original path | A2-U01/U02 |
| A2-D37 | 8,191 postings | Original path | A2-U05 |
| A2-D38/D39 | 8,192 / 8,193+ postings | Historical linear helper once | A2-U06/U04 |
| A2-D40 | Eligibility false | Original live scan | A2-U15/U16 |
| A2-D41 | Callback rejects some postings | Dispatch on decoded length; order preserved | A2-U19 |
| A2-D46 | Helper budget/allocation failure | Typed error, no fallback retry | A2-U13/U14/U21 |
| A2-D47 | Legacy budget error | Propagated unchanged | A2-U07 |
| A2-D50 | A2 Rust unit suite passed | Continued to integration | qa.md |
| A2-D52 | Local production-path integration passed | Continued to paired measurement | qa.md |
| A2-D54 | Same corpus/index digests and adapter metadata | Proceeded with paired campaign | paired manifest |
| A2-D56 | 8 complete mirrored slots, 20 samples/lane | Sealed and evaluated | performance.md |
| A2-D58 | Same host and within drift caps | Evaluated frozen sign gate | performance.md |
| A2-D62 | Qualified P04 guard failure | `PERFORMANCE_REJECTED`; exact rollback | performance.md |
| A2-D64 | Low-hit guards `A_FASTER` | Rejected despite common-lane improvement | HA2-P04 |
| A2-D66 | Rollback byte-equal to base | Preserved evidence and reran final QA | source-disposition.md |
| A2-D70 | Real RustFS available via local podman | Ran all required suites; PASS | qa.md |
| A2-D71 | Branch not pushed | Recorded `CI_PENDING`; no merge claim | qa.md |

No HARD STOP occurred. The only deferred gate is hosted CI / independent review.

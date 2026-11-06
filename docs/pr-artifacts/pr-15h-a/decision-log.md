# PR 15H-A — decision log

Only rules actually exercised are recorded. Source SHA at each decision is the
branch head named.

| ID | Observable trigger | Action taken | Gate |
|---|---|---|---|
| HA-D01 | `main` was unchanged at `ddcbe7789…` after a fresh fetch | Recorded the new baseline SHA and continued | S0 |
| HA-D04 | Working tree was clean at start and a clean detached baseline worktree was available | No preserve/discard action needed | S0 |
| HA-D07 | Branch `dev/pr15h-a-linear-term-candidates` did not exist | Created it from the exact baseline SHA | S0 |
| HA-D24 | The helper fitted entirely inside `execute.rs` | Implemented the approved branch only | S1 |
| HA-D13 | Decoded candidates were strictly increasing | Appended without sorting or dedup | S1 |
| HA-D14 | A crafted non-increasing candidate was observed in a test | Returned typed `CorruptIndex`; no repair sort | U10 |
| HA-D15 | Field stats were absent | Emitted `0.0`, matching baseline | U09 |
| HA-D16 | Field stats were present | Reused `score::bm25` with the exact supplied arguments | U09/U17 |
| HA-D18 | Zero postings / zero matches | Empty vectors, same zero-charge ledger calls | U01/G4 |
| HA-D19 | Allocation-failure injection | Typed `ResourceLimit`, ledger cleaned | U16 |
| HA-D20 | Matched virtual reservation rejected | Typed `ResourceLimit`, no score reservation | U12 |
| HA-D21 | Scored virtual reservation rejected | Typed `ResourceLimit`, no scoring, no phantom charge | U14 |
| HA-D32 | Physical vectors were smaller than the modeled budget | Retained baseline charges unchanged | U11–U15 |
| HA-D34 | All Rust unit cases passed | Continued to integration and measurement | S1/S2 |
| HA-D40 | User explicitly authorized assuming an idle host | Supplied `--idle-confirmed`; genuine contention probes were still run | S0/S2 |
| HA-D41 | All 6 baseline and all 16 paired contention probes returned `clear` | Continued prescribed slots | HA-P00 |
| HA-D44 | Baseline-only campaign succeeded 3/3 and sealed | Continued to production implementation | S0 |
| HA-D50 | Corpus and index digests were equal across arms | Compared only after oracle and drift checks | HA-P00 |
| HA-D53 | 8-slot mirrored schedule and 56 lane records were exact | Sealed and evaluated | HA-P00 |
| HA-D61 | Qualified campaign had guards G2/G3/G4 `A_FASTER` | Classified `PERFORMANCE_REJECTED`, ran additive source rollback | HA-P04 |
| HA-D63 | Qualified negative result after a measured candidate | Restored exact pre-optimization source and preserved evidence | disposition |
| HA-D65 | Real RustFS topology availability | Recorded execution status in `qa-ci.md`; no fake substitute | HA-I07/I08 |

No HARD STOP condition occurred. The only DEFER-class outcome is any unavailable
real-RustFS/hosted-CI gate, which remains explicitly open rather than claimed.

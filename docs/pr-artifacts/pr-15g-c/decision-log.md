# PR 15G-C decision log

**GC_BASE_SHA:** `018fdd768d0898d6709baeb8661998ee1a82947c`

| Rule | Trigger | Authorized action | Evidence / gate |
|---|---|---|---|
| GC-D01/GC-D02 | Shared tip `018fdd7`, B CI success, main context only | Pinned shared baseline; no main merge/branch | `preflight.md`; GC-A00 |
| GC-D06 | Umbrella PR #86 exists | Reused PR #86; no C-specific PR | PR #86 |
| GC-D08 | Verified P4 eligibility and compiled plan | Added narrower `single_term_stream_eligible` | GC-U01/02/03/05 |
| GC-D14 | Dead postings present in frozen lanes | Count/charge scanned, exclude candidates | existing phase4/serve tests |
| GC-D16 | Constants 16/48/64 verified | Reused exact constants/ledger | phase4 budget tests |
| GC-D25 | Candidate factoring needed for C and legacy | Extracted one shared `admit_candidate`; heap logic/comparator unchanged | unified/phase4 tests |
| GC-D34/GC-D35 | Lazy-directory pressure test could be arranged | Added exact/one-under pressure tests; no cached-state substitute | `gc_br01a–e` |
| GC-D37 | Stored test fixture had fewer than 100 records | Extended test-only generator to 128/1024 and asserted 100 operations | `gc_br02a/b` |
| GC-D39 | Pinned local RustFS image available | Ran C/A/B RustFS and fault/crash suites | `target/pr15g-c/rustfs/` |
| GC-D43 | Assume-idle authorization and actual clear probes | Ran full C campaign with `--idle-confirmed` | performance report |
| GC-D46 | Both mandatory common lanes not `B_FASTER`; guardrail `A_FASTER` | Reported `PERFORMANCE_NOT_ACCEPTED`; no tuning/omission/retiming | `performance-qualification.md` |
| GC-D47 | Closure docs postdate measured `5ec886f` | Verify final diff is docs-only; measured source remains `5ec886f` | final report |
| GC-D48 | No source/test/runner/CI change after C measurement | No replay required; docs-only closure | final diff |

Not triggered: GC-D04/D05 (clean shared tip), D12/D13/D19/D20/D22/D23/D24
(no decoder/score/budget mismatch), D26 (shared admission preserved legacy tests),
D29/D30 (no duplicate-key contract issue), D40 (service available).

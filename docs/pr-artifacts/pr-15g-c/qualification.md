# PR 15G-C qualification

**Status:** `IMPLEMENTATION_CORRECTNESS_PASS_PERFORMANCE_NOT_ACCEPTED`
**GC_BASE_SHA:** `018fdd768d0898d6709baeb8661998ee1a82947c`
**C measured candidate:** `5ec886f3cbd8666d46b7d3c4a9761abd53e30d4e`
**Performance:** **FAIL** (GC-P01/P02/P04 failed; GC-P03 passed/inconclusive)
**Real RustFS:** PASS locally on pinned image
**Hosted CI:** pending at final HEAD (reported separately)
**Independent review:** NOT STARTED
**Merge:** NOT MERGED

## Gate matrix

| Gate | Status | Evidence |
|---|---|---|
| GC-A00 shared-branch preflight | PASS | `018fdd7`, B CI `41790864564` |
| GC-A01 B carryover | PASS | `gc_br01a–e`, `gc_br02a/b`, existing gbu15 |
| GC-A02 C eligibility/fallback | PASS | GC-U01/U02/U03/U05, fallback integration |
| GC-A03 first-stage audit/budgets | PASS | visitor + U11/U13/U22, phase4 budget parity |
| GC-A04 shared heap admission | PASS | existing unified/phase4/batch/PIT/cursor tests |
| GC-A05 bounded/total_hits/score parity | PASS | C-vs-`And([Term])` differential, counters |
| GC-A06 local integration | PASS | `pr15g_c_stream` 7 tests + B/A suites |
| GC-A07 real RustFS/fault | PASS locally | C RustFS 1; B/A RustFS 1+1; proxy 7; K0 5; K05 10/10 |
| GC-A08 C runner tests | PASS | 18 deterministic Python tests |
| GC-A09 local QA | PASS | 2303/2307 tests, 92.69% coverage |
| GC-A10 C performance | **FAIL** | GC-P01/P02/P04 failed; see performance report |
| GC-A11 exact-head CI | pending final HEAD |
| GC-A12 independent review | NOT STARTED |

## Correctness/integration evidence

- `pr15g_c_stream`: memory high-hit, FsDirectory reopen, fallback/cursor, PIT,
  reduced metadata cap, concurrent readers, deterministic index bytes.
- `search::unified`: 304 search tests pass; C path exercised by sorted term
  queries, while legacy `And([Term])` provides a differential reference.
- C stage-one validates all postings, works, virtual 16/48/64 charges and BM25
  for every match before emission; second pass emits every live candidate.
- Existing cancellation, batch, JSON/geo, cursor and duplicate-key behavior
  remains on the shared admission/legacy paths.
- B carryover tests distinguish lazy-directory remaining budget from initial
  verified-state admission and prove K=100 direct operation counts.

## Local QA

Stable/MSRV fmt and Clippy (default/all-features), workspace tests, coverage,
docs, bench build, scripts and Python suites all pass. Full logs:
`target/pr15g-c/qa/final/`.

## Performance failure

The qualified nine-lane campaign at `5ec886f` vs `018fdd7` failed:
100K common/K100 and common/K10 were **A_FASTER**, as were 100K absent, 100K
rare and 10K rare; 100K medium was `INCONCLUSIVE` (GC-P03 pass). No selective
retiming, lane exclusion or implementation tuning was performed. Performance
status is **NOT ACCEPTED** and requires human disposition.

## Remaining blockers

- Performance acceptance failed; code is not phase-accepted.
- Exact-final-HEAD hosted CI must be reported.
- Independent review is pending.
- No merge or self-approval occurred.

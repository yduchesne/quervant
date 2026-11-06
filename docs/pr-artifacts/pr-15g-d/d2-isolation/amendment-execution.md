# D2-only isolation — amendment execution record

**Amendment:** `Quervant_PR15G_D_D2_Isolation_Authorization_Amendment.md`
**Starting docs HEAD:** `99686909f0b428c2627403abf66bf71100fe906e`
**Harness/controller commit:** `e2009d22ffcd22de17b9c9609199fb6957868007`
**A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**X:** `53e41df1fd5e91c7c2a67a3fcfbba4abf62bd4f6`
**Campaign ID:** opaque `d2-only-first-qualified`

## Completed

- Verified the shared HEAD was exactly the authorized docs SHA and its diff from
  `f0039e1` contained only the five prior D2-isolation documentation files.
- Reused the existing clean, pinned A/X worktrees.
- Ran the approved exact-edit identity proof: `DX-SOURCE-ID: PASS`.
- Reconfirmed the original D2 differential test at X: 1 passed.
- Added and committed the isolated D2 A/X controller and deterministic tests
  before any timed slot.
- Ran exactly one complete 16-slot campaign with the literal mirrored schedule,
  nine frozen lanes, 5 warmups + 20 samples, independent oracle and real
  before/after contention probes.
- All 16 slots completed; 2,880 measured samples and 32 clear probes validated.

## Stop condition

The campaign failed the predeclared drift gate:

- Arm A, `pr15d_v1/100000/rare/k100`, cross-block drift `1.2994` > `1.25`.
- Block medians: `265354.5`, `252504.0`, `328104.5`, `301354.5` ns.
- X stayed within the cap on the same lane (`1.1085`).

Per the plan, drift is `MEASUREMENT_BLOCKED`, not a performance pass or fail.
No selective retry, slot exclusion, threshold change or second campaign was
performed.

## Consequence

- No performance verdict exists.
- Shared production search source remains the existing D1+D2 source.
- No D2-only retention or A rollback was performed.
- Historical C/D1/D2/confirmation/blocker reports remain untouched.

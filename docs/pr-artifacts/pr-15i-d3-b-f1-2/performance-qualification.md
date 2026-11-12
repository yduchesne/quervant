# PR 15I-D3-B-F1.2 — performance qualification

## Final disposition: `D3BF12_PERFORMANCE_REJECTED_SAFE_ROLLBACK`

The first F1.2 paired attempt was **fully structurally qualified** (readiness,
host, affinity, provenance, oracle, index, contention and drift all PASS) and
independently verified, but failed the frozen `D3B-P03` K10 median floor. Per the
plan this is a performance rejection: no second campaign was run, the negative
evidence was archived, and the candidate production delta was rolled back.

## Attempt 01 `d3bf12-base-01`

| Item | Value |
|---|---|
| Independent verifier | exit 0, `verification=PASS`, `campaign_status=CAMPAIGN_REJECTED`, `attempt_class=QUALIFIED_REJECTED`, `summary_match=true`, `live_binary_rehash=PASS` |
| Sources | A `39dbd9f5…`, B `48d9abf3…` |
| Binaries | A `9f3d1afebe3f222b97f80e64b030b3e14fe8c7f8a925127e2e6c460dad86f9b0` (4,479,072 B); B `c5cceb191d4ff2d333058862a6f916c77d89cd12a06a51fbdda961dcdff0fe61` (4,490,664 B) |
| Indexes | byte-identical, 15,747,551 / 1,661,455, digest `5734ae60…` |
| Readiness | `READY` (adapter median 19‰, controller 0‰) |
| Drift | `PASS`, no violations |
| Provenance / host / readiness / succession | `0ada8e16…` / `a2c61505…` / `6b425085…` / `abc57a73…` |
| Archive | `d3bf12-base-01.tar.gz`, SHA-256 `9e1e59b6d2e6a09fa1601861e38e59161437d65e128f9518ed5ea63a93f593ba`, 65 members |

### Frozen gate results (single attempt)

| Gate | Result | Evidence |
|---|---|---|
| P00/P07 | PASS | structure, provenance, readiness, oracle, indexes, sealing |
| P01 | PASS | 100K common/K100 median **+9,760,624 ns**, 4/4 blocks ≥ 0 |
| P02 | PASS | 100K medium/K100 median **+2,389,981 ns**, 4/4 blocks ≥ 0 |
| P03 | **FAIL** | 100K common/K10 median **−519,627 ns** (floor −500,000); all blocks ≥ −1,500,000; median B/A 1.014986 (≤1.05) |
| P04 | PASS | all absent/rare medians ≤1.15 and blocks ≤1.50 |
| P05 | PASS | 10K common +960,549; medium +234,476; blocks within floors |
| P06 | PASS | 100K common/medium medians > −500,000; blocks within floors |
| P08 | FAIL | only one attempt; performance rejection is terminal |

### All nine lanes (block medians ns; d = A−B; r = B/A lower median)

| Lane | A blocks | B blocks | d blocks | median d | r |
|---|---|---|---:|---:|---:|
| 10K absent | 50818, 38637, 39220, 45349 | 50490, 41705, 41553, 41457 | 328, −3068, −2333, 3892 | −2333 | 0.993546 |
| 10K rare | 54285, 47911, 56911, 58277 | 58117, 52192, 52862, 54910 | −3832, −4281, 4049, 3367 | −3832 | 0.942224 |
| 10K medium | 1839207, 1861180, 1832418, 1824375 | 1596826, 1591632, 1599361, 1589899 | 242381, 269548, 233057, 234476 | 234476 | 0.868214 |
| 10K common | 4320457, 4263662, 4255020, 4225159 | 3327884, 3303113, 3278226, 3274867 | 992573, 960549, 976794, 950292 | 960549 | 0.770437 |
| 100K absent | 235831, 243197, 244267, 233666 | 233986, 241004, 239835, 247445 | 1845, 2193, 4432, −13779 | 1845 | 0.990983 |
| 100K rare | 258074, 247301, 260113, 250244 | 259033, 258563, 250272, 258485 | −959, −11262, 9841, −8241 | −8241 | 1.003716 |
| 100K medium | 18422509, 18006840, 17928594, 18723027 | 15373613, 15712785, 15538613, 15392668 | 3048896, 2294055, 2389981, 3330359 | 2389981 | 0.834502 |
| 100K common/K100 | 44400937, 43623412, 43884502, 43054793 | 33507043, 33895269, 33120208, 33294169 | 10893894, 9728143, 10764294, 9760624 | 9760624 | 0.754713 |
| 100K common/K10 | 33498909, 33181821, 32882985, 32499115 | 34000934, 34477284, 32930408, 33018742 | −502025, −1295463, −47423, −519627 | −519627 | 1.014986 |

## Series verdict

`verify.py --series-root …/fixup-f1-2 --comparison d3bf12-base` returns
`verification=PASS`, `verdict=COMPARISON_PERFORMANCE_REJECTED`, `d3b_p08=FAIL`,
`attempt_classes=['QUALIFIED_REJECTED']`, `succession_validation_scope=FULL_SERIES`.
Attempts 02 and 03 were not run (`performance_rejection_retries: 0`).

## Rollback

Additive commit `5d3bf1f7b1bb87f374d355fece579e84ad3d0ec2` restored
`crates/quervant-core/src/search/unified.rs` to the exact BASE blob
`bb7a10357ffa215a5a21e77ca63caaa21fd614533d2c64e086e64e6c73f08433`
(`git diff BASE -- file` empty). The D3-B integration test file still passes on
BASE and was retained. Post-rollback QA: 2,468 all-feature tests (stable and
MSRV), 92.68% workspace line coverage, all Python/PR15D suites and RustFS
adapter tests pass.

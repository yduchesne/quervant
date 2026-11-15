# PR 15I-D3-B-F1.1 — performance qualification

## Disposition: `D3BF11_MEASUREMENT_BLOCKED`

Campaign 01 was **not structurally qualified**: the independent verifier found a
within-block drift violation on arm A, block 2, `10K rare` (ratio
`1.503057781526782` > the frozen `1.50` cap). Per plan §6.3/F11-49 a drift
failure is a structural qualification failure, so no performance verdict is
authorized, campaign 02 was **not** run, and no production rollback was
performed.

The same campaign also recorded a `D3B-P03` numerical miss, which is reported
below for transparency but is **not** an authorized performance rejection
because the campaign never achieved structural qualification. No speed-up or
regression is claimed.

## Campaign 01 `d3bf11-base-01`

| Item | Value |
|---|---|
| Status (controller and independent verifier) | `MEASUREMENT_BLOCKED` |
| Independent verifier | exit `0`, `verification=PASS`, `summary_match=true`, 16 slots, `live_binary_rehash=PASS` |
| Source SHAs | A `39dbd9f5…`, B `48d9abf3…` |
| Binaries | A `9519a215b7fa188793d2cddd349a94b37ba4eb5da0cc291c0bf7433fdc6b942f` (4,479,120 B); B `370678645eed410830294ef48d712d2646b79b51751405383adf18ad5ca2c431` (4,490,552 B) — distinct |
| Indexes | byte-identical across arms: 15,747,551 committed / 1,661,455 STORED, digest `5734ae60591f7563…` |
| Provenance / host | `46b90dbd…` / `18ecc9b9…` |
| Samples / warmups / probes | 2,880 / 720 / 32 clear |
| Drift | **FAIL** — `WITHIN_BLOCK_DRIFT` arm A block 2 `10K rare` 1.503058 > 1.50 |

### Nine-lane values (block medians ns, d = A − B, r = B/A)

| Lane | A block medians | B block medians | d blocks | median d | median r |
|---|---|---|---|---:|---:|
| `10000/absent/k100` | 39723, 39166, 38991, 52748 | 40278, 42524, 38359, 39503 | −555, −3358, 632, 13245 | −555 | 0.983791 |
| `10000/rare/k100` | 49592, 59347, 48310, 52445 | 47387, 54325, 48157, 50187 | 2205, 5022, 153, 2258 | 2205 | 0.955537 |
| `10000/medium/k100` | 1809758, 1807103, 1870597, 1866436 | 1579483, 1613598, 1625457, 1660510 | 230275, 193505, 245140, 205926 | 205926 | 0.872759 |
| `10000/common/k100` | 4227822, 4256454, 4248638, 4369784 | 3322382, 3323001, 3324492, 3435109 | 905440, 933453, 924146, 934675 | 924146 | 0.782484 |
| `100000/absent/k100` | 248045, 237124, 238905, 242221 | 243600, 250517, 236707, 262765 | 4445, −13393, 2198, −20544 | −13393 | 0.990800 |
| `100000/rare/k100` | 271307, 263615, 272191, 250266 | 254442, 251677, 246761, 288382 | 16865, 11938, 25430, −38116 | 11938 | 0.937838 |
| `100000/medium/k100` | 18215839, 18763712, 18344533, 18236657 | 15777864, 15526940, 15630860, 15810845 | 2437975, 3236772, 2713673, 2425812 | 2437975 | 0.852072 |
| `100000/common/k100` | 43953115, 44258029, 44275594, 43526544 | 33838537, 33909366, 34104141, 34066296 | 10114578, 10348663, 10171453, 9460248 | 10114578 | 0.769878 |
| `100000/common/k10` | 33746034, 33937091, 33351333, 33152261 | 34286677, 34025008, 33658571, 34199534 | −540643, −87917, −307238, −1047273 | −540643 | 1.009212 |

### Gate observation (recorded, not an acceptance verdict)

| Gate | Result | Note |
|---|---|---|
| D3B-P01 | PASS | 100K common/K100 median +10,114,578 ns, 4/4 blocks ≥ 0 |
| D3B-P02 | PASS | 100K medium/K100 median +2,437,975 ns, 4/4 blocks ≥ 0 |
| D3B-P03 | FAIL | 100K common/K10 median −540,643 ns < −500,000 floor; all blocks ≥ −1,500,000; r 1.009212 ≤ 1.05 |
| D3B-P04 | PASS | absent/rare medians ≤ 1.15, blocks ≤ 1.50 |
| D3B-P05 | PASS | 10K common/medium medians > −2,000,000; blocks ≥ −3,000,000 |
| D3B-P06 | PASS | 100K K100 medians > −500,000; blocks ≥ −1,500,000 |
| D3B-P07 | PASS | distinct sources/binaries, identical indexes, complete evidence |
| D3B-P08 | FAIL | campaign 01 not structurally qualified; campaign 02 not authorized |

**Warning:** these numbers are from a structurally unqualified campaign. They
cannot be promoted into an acceptance or rejection verdict.

## Series verification

`verify.py --series-root …/fixup-f1-1 --comparison d3bf11-base` returns exit `0`
with `verification=PASS`, `verdict=MEASUREMENT_BLOCKED`, `d3b_p08=FAIL`,
eligible control `d3bf11-base-aa-01`, and campaign statuses
`['MEASUREMENT_BLOCKED']`.

## Archive (preserved negative/invalid evidence)

| Item | Value |
|---|---|
| Archive | `d3bf11-base-01.tar.gz` |
| SHA-256 | `69c45bc40534af30161179147cfa957909c20a1113362a671ece3b940836fcc5` |
| Members | 63 |
| Sidecar | matching `.sha256` (exclusive) |

## Not run

- `d3bf11-base-02` — prohibited because campaign 01 was structurally blocked and
  no paired retry is authorized.
- No rollback — a structural measurement block leaves the candidate unmerged and
  intact (F11-56).

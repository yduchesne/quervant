# PR 15I-D3-A measurement

Status: `NOT_RUN`.

No timed campaign has been executed. The tables below are populated only from
sealed raw slot evidence and independently recomputed by `verify.py`.

## Planned evidence

| Campaign | Kind | Slots | Timed samples | Warmups | Clear probes | Index builds |
|---|---|---:|---:|---:|---:|---:|
| `d3a-base-aa-01` | control | 16 | 2,880 | 720 | 32 | 2 |
| `d3a-unbatched-01` | paired | 24 | 4,320 | 1,080 | 48 | 4 |
| `d3a-unbatched-02` | paired | 24 | 4,320 | 1,080 | 48 | 4 |

Expected successful full series: 64 slots, 11,520 timed samples, 2,880
warmups, 128 clear contention probes, 10 index builds, 2,880 P records.

No measurement may be reported as qualified until the independent verifier
returns `PASS` and the archive is sealed and re-extracted.

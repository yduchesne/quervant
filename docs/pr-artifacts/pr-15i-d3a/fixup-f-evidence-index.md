# PR 15I-D3-A-F evidence index

Status: `D3A_MEASUREMENT_BLOCKED`.

All v2 archives are outside `target/` under
`~/.local/share/quervant/benchmark-evidence/pr15i-d3a/fixup-f/`, with exclusive
`.sha256` sidecars and `SAME_DISK_ONLY` status. Historical T0/T0b archives were
not modified.

| Attempt | Status | Archive SHA-256 |
|---|---|---|
| `d3af-base-aa-01` | QUALIFIED | `3ba3c4e3e765eed51987b6c6de7021acb8c4ea50ef96582190ea498a19ce4a2c` |
| `d3af-unbatched-01` | QUALIFIED | `99b2dd16c979b5a803b138b632e0b2f5c644aedb6fa489bf62ebac75b6ac4f33` |
| `d3af-unbatched-02` | QUALIFIED | `4e085945f5d1ef7223d018d5730e6685143a6956bddb1b8fb3db679aae2135a9` |
| `d3af-unbatched-03` | QUALIFIED | `d71e69e0e3334499edf711326fcb476ef3e962acb214cb88bfa6c63eca8662af` |
| `d3af-unbatched-04` | `D3A_UNSTABLE` (blocked) | `f8336da45dfd6a615512c791262495d71fd468181140c05711a0fe46cabd4069` |
| `d3af-unbatched-05` | NOT RUN | n/a |

A pre-T0c dry run under `target/pr15i-d3a/fixup-f/pre/` and the pre-T0c
worktrees is preserved separately and is not official evidence. No aggregate
archive exists because the five-run series is incomplete/unqualified.

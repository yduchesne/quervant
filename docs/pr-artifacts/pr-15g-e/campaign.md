# PR 15G-E format-aware campaign

**Campaign:** opaque `e-first-qualified`
**Status:** `REJECT_E_ROLLED_BACK`
**A:** `ca065a212987284144d8901aa5c54de093d6dbfc` (v1.0)
**E:** `62d35c262fa667673ee6d8701ca9ef75daf17a53` (v1.1)
**Raw seal:** `47a82d884e2e314d68d2ab8304c558ebdc3e7257fd35aa2a1722781d7be9d226`
**Sanitized JSON:** `7e811be1325ffc9e7f65b16bd95cf17aa543f4d54d8447039c5a963a602fb972`
**Sanitized Markdown:** `991aa4a84736e5ddbb0e5c3eb3fdc310347706bc6995109fe54b5a8ecadb2c93`

## Acquisition

| Item | Result |
|---|---|
| Schedule | `A E E A | E A A E | E A A E | A E E A` |
| Slots | 16/16 |
| Arms | 8 A, 8 E |
| Lane records | 144 |
| Samples | 2,880 |
| Warmups | 720 |
| Oracle checks | 144 pass |
| Contention probes | 32/32 clear |
| Drift | PASS both arms, all nine lanes |
| A segment minor | 0 |
| E segment minor | 1 |
| E feature/directories | present exactly once |
| `--verify-only` | PASS, byte-identical |

The arms intentionally have different encoded bytes. Index digests were
immutable within each arm and the logical corpus/oracle matched across arms.

## Result

`E-P03` failed: neither rare lane was `E_FASTER`. `E-P04` failed: both 10K
rare/medium/common and 100K rare/common/K10 were `A_FASTER`. The 100K rare
ratio was approximately 6.4–6.9× slower for E. E was rejected; production
emission and the fast path were rolled back to A+B.

Full table: `performance.md`.

# PR 15G-E decision log

| Rule | Trigger | Action |
|---|---|---|
| E-EX01 | Starting HEAD `7627cd6`, clean | Proceeded |
| E-EX14/16 | Generic builder needed segment-only minor; IDs free | Added private setter and `0x0012/13`, feature `0x000C` |
| E-EX18/19 | Legacy 1.0 fixtures byte-stable; new production format differs | Kept legacy defaults, updated only tests that falsely required new production bytes to equal 1.0 goldens |
| E-EX22/23 | Codec boundaries/overflow | Typed fail-closed tests |
| E-EX29/30 | Structural and semantic corruption | Metadata rejects; certification compares full scan |
| E-EX31/33/34 | Temporary offsets and persisted interior mismatch | No retained vector, no cert on mismatch |
| E-EX35/36 | Invalid selection/full cache | Legacy precedence retained |
| E-EX42 | `support::build_segment` owns production emission | Enabled E only there |
| E-EX51/53 | Frozen oracle shared; arm bytes differ | Required within-arm digests, not cross-arm byte equality |
| E-EX55/56 | All probes clear; drift within caps | Campaign qualified |
| E-EX58/59 | E-P03/P04 failed | Reverted E production code to A+B |
| E-EX66/67 | Hosted CI pending/failure | Recorded honestly; no prior green reused |
| E-EX72 | Human review absent | Review pending, no merge |

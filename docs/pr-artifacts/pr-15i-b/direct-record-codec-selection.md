# PR 15I-B direct-record — codec selection

**Decision: `15IB_DIRECT_RECORD_REJECTED_SAFE_ROLLBACK` — neither codec is eligible.**

| Codec | Campaign | Seal SHA-256 | `C = S × R` | Decision |
|---|---|---|---|---|
| LZ4 | `target/pr15i-b/campaigns/lz4-direct-01` | `4ba9404ccabe89f65692bfc9b77a61b1f08639052f2c8483ce760a6c678a51de` | 0.1295 | `B_CANDIDATE_INELIGIBLE` |
| Zstd1 | `target/pr15i-b/campaigns/zstd-direct-01` | `23a41fb016ff9d067a013333fa61f096aebfd500171319578e1d9dc0c968fe54` | 0.0481 | `B_CANDIDATE_INELIGIBLE` |

Both independent verifiers pass with `B-P13` established from source, 12
remeasured rebuilds, eight binary hashes, the frozen protocol/corpus, auxiliary
contention hashes, the exact selected key/total-hit oracle and the absolute RSS
cap. `B-P06` fails only on the 10K rare median (1.152 / 1.158 > 1.10); all
blocks remain within 1.30.

No tie-break applies. No threshold, block size, codec or format was changed.
Production was restored exactly to P0 in
`7b423fc17d1c888bccf2be97749bb8de73be1556`; both new campaigns and the earlier
rejected campaigns remain sealed as negative evidence.

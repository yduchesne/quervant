# PR 15I-B — codec comparison and decision

**Decision: `15IB_CODEC_REJECTED_SAFE_ROLLBACK` — neither codec is eligible.**

Both candidates used the same STORED v2 framing, certificate, producers and
tests, derived from P1_SHA; only the pinned codec dependency and compile-time
feature differed.

| Item | LZ4 candidate | Zstd level-1 candidate |
|---|---|---|
| Production candidate SHA | `bfdb9b0d95de171c72be1de26e4501fc701df988` (tooling tip `aa00b98`… ancestry) | `b3fbde55596615e44d4aa4b11a0e0bbf4f107e5b` |
| Codec | `lz4_flex =0.11.6` | `zstd =0.13.3`, level 1 |
| Campaign | `target/pr15i-b/campaigns/lz4-05` | `target/pr15i-b/campaigns/zstd-01` |
| Seal SHA-256 | `9adec5f3b51f9ef386eea65abf9401c5179254bf3665a0e3cd9afe9c5ac65a46` | `245fad6e3c968aeda05fda036e6c71136e908dbacd3d480f8843eb098c33a36f` |
| 100K STORED ratio (B-P03) | **0.1719** PASS | **0.0650** PASS |
| 100K total ratio (B-P04) | **0.6631** PASS | **0.6196** PASS |
| 10K STORED / total (B-P05) | 0.1722 / 0.6611 PASS | 0.0652 / 0.6173 PASS |
| 10K rare lane median | **1.664 FAIL** | **1.691 FAIL** |
| 10K medium lane median | 1.089 PASS | **1.126 FAIL** |
| 100K rare lane median | **1.168 FAIL** | **1.165 FAIL** |
| 100K medium lane median | 0.998 PASS | 1.035 PASS |
| Reopen (B-P08) | ~0.71 PASS | ~0.69 PASS |
| Build+commit (B-P10) | ~0.85 PASS | ~0.85 PASS |
| RustFS cold (B-P09) | ~0.71 PASS | ~0.66 PASS |
| Selected K100 (B-P12) | ~0.77 PASS | ~0.74 PASS |
| RSS (B-P11) | ~0.94–0.98 PASS | ~0.93–0.97 PASS |
| `C = S × R` | 0.1327 | 0.0482 |
| Verifier decision | `B_CANDIDATE_INELIGIBLE` | `B_CANDIDATE_INELIGIBLE` |

Both independent verifiers pass with the same rejection decision; the frozen
protocol, corpus and A-sentinels were preserved. `C < 1.00` is necessary but not
sufficient: every gate must pass, and `B-P06` fails for both.

## Conclusion

Storage savings were large (STORED section 83%/94% smaller), but rare/medium
warm queries regress because a certified selected read must parse the touched
128-record block while the legacy v1 lazy offset directory decodes only the
selected records. No adaptive block size, alternate codec, runtime switch or
threshold change is authorized. Production was restored exactly to P0
(PR 15I-A code) in commit `c5180a7012e678d6fa938c747b18990201621d11`; both
candidate campaigns remain sealed as negative evidence.

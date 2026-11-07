# PR 15H-D — sealed baseline

**Campaign:** `target/pr15h-d/baseline-01` (ignored raw evidence)
**A source/tooling:** `c802f965a57d5038e98006bba581c4356654baaf`
**Seal SHA-256:** `72c8d17d5e0708435b46e3d50cde918da48403698cc15ceed3caf7a669a05eea`
**Sanitized baseline SHA-256:** `f95f6a14aa0c9541617dd5f76ee3e042668c9fa831de75a02a744e59dc4ae910`

3 trials × 6 lanes × (5 warmups + 20 samples) = 360 samples, 90 warmups,
6 clear probes, 18 oracle checks. Host fingerprint
`4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f`, corpus
`69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`.
`--verify-only` reproduced the sanitized report byte-for-byte.

| Lane | Trial medians (ns) | Median-of-medians |
|---|---:|---:|
| D-P1 common/100K/K100 | 51974318, 54312320, 53408293 | 53408293 |
| D-P2 common/100K/K10 | 39367419, 48474126, 38852276 | 39367419 |
| D-P3 medium/100K/K100 | 20369719, 26782700, 20274800 | 20369719 |
| D-G1 common/10K/K100 | 5171081, 6001690, 4924773 | 5171081 |
| D-G2 rare/100K/K100 | 260604, 298704, 259004 | 260604 |
| D-G3 absent/100K/K100 | 272104, 291704, 262804 | 272104 |

The sanitized Markdown carries the mechanically copied “PR 15H-B” title; the
recorded SHAs, lanes and seal are D-specific and verified.

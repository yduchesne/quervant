# PR 15H-C — sealed baseline

**Campaign:** `target/pr15h-c/baseline-01` (ignored raw evidence)
**Source A:** `e8744d3fe16ee858c7d587aaf3b10d393059b809`
**Tooling:** `b8064e4ae603162c3485a0ffd990f5061cc9b3e1`
**Seal SHA-256:** `53aceea42a227289d8054929db9f7a9a333d50a0b55410c09801afe18ee492d0`
**Sanitized baseline SHA-256:** `af9c3bb87ea13f8e46cab1c18c3d7cdb4dcdd3a4c7954f6f245f99b9893f9db4`

3 trials × 6 lanes × (5 warmups + 20 samples) = 360 samples, 90 warmups,
6 clear probes, 18 oracle checks. Host fingerprint
`4f971362f029a3301d89ac17aa6e6078fb00f2e56dc594f7ac2b26e18e13598f`, corpus
`69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`.
`--verify-only` reproduced the sanitized report byte-for-byte.

| Lane | Trial medians (ns) | Median-of-medians |
|---|---:|---:|
| P1 common/100K/K100 | 52786835, 50501726, 49782147 | 50501726 |
| P2 common/100K/K10 | 37551590, 37343605, 38561641 | 37551590 |
| P3 medium/100K/K100 | 19915511, 19873867, 19488497 | 19873867 |
| G1 common/10K/K100 | 4755875, 4594662, 4731372 | 4731372 |
| G2 rare/100K/K100 | 267604, 271503, 268704 | 268704 |
| G3 absent/100K/K100 | 245705, 252604, 241004 | 245705 |

The sanitized Markdown title still carries the mechanically copied "PR 15H-B"
label; the recorded source/tooling SHAs, lanes and seal are C-specific.

# PR 15I-B — evidence manifest

All raw campaign data lives under ignored `target/pr15i-b/campaigns/` and is
never rewritten.

| Campaign | Codec | Candidate B | Seal SHA-256 |
|---|---|---|---|
| `lz4-05` | LZ4 | `bfdb9b0d95de171c72be1de26e4501fc701df988` | `9adec5f3b51f9ef386eea65abf9401c5179254bf3665a0e3cd9afe9c5ac65a46` |
| `zstd-01` | Zstd1 | `b3fbde55596615e44d4aa4b11a0e0bbf4f107e5b` | `245fad6e3c968aeda05fda036e6c71136e908dbacd3d480f8843eb098c33a36f` |

Invalid/incomplete attempts preserved: `lz4-00-invalid`, `lz4-01-invalid`,
`lz4-02-invalid`, `lz4-03-invalid`, `lz4-04` (manifest schema incomplete).

Common identity:

- A baseline: `0cf7dec58c3a5412c1ad750b487e9fa00dfc46bb` (P0; production
  byte-identical to merged PR 15I-A `691b699`).
- Frozen corpus manifest:
  `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151`.
- P0 PR 15I-A requalification receipt:
  `target/pr15i-a/reviews/verification-15ib-p0-01.json`.
- Historical diagnosis: `target/pr15i-b/diagnose/run-01/diagnosis.json`
  (H-E3, boundary reads 10,001/100,001).
- Codec lab: `target/pr15i-b/lab/codec-n{10000,100000}/codec_lab.json`.

A adapter SHA-256 (both campaigns): `94d119b29c99c3853182d6f77110074b4c21c44a32bc3cbf240170979417e91d`.
B adapters: LZ4 `2bda9428…c332a`, Zstd `eb328849…3c879`.

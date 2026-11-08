# PR 15I-A — decision register

| Date (UTC) | Decision | Evidence |
|---|---|---|
| 2026-11-07 | Implement payload V3 exactly as frozen: sorted segment-ID table + canonical varint ordinal/doc ID | `format-and-compatibility.md`, U01–U43 |
| 2026-11-07 | Keep `encode()`/`encode_with_mode()` as legacy V1/V2 codecs; production write sites use only `encode_v3` | U26, U27, I04–I06 |
| 2026-11-07 | Reject sidecar/manifest V3 feature mismatch in both directions before visibility masks | U28–U30, U33, I03 |
| 2026-11-07 | Add a V3-only cumulative decode budget charged before every reservation/copy; leave V1/V2 accounting unchanged | U34–U41 |
| 2026-11-07 | Keep `KeyRow` owned string IDs; claim disk savings only, measure peak RSS explicitly | IA-08, A-P08 |
| 2026-11-07 | Update the `#[cfg(test)]` amendment01 publication helper to write V3 (assertions unchanged) | workspace tests |
| 2026-11-07 | Freeze the nine-lane/ABBA schedule and all thresholds before the first complete campaign | `protocol.json`, `verify.py` tests |
| 2026-11-07 | Preserve `paired-01..03` as invalid/incomplete attempts and run the complete matrix in `paired-04` | raw campaign tree |
| 2026-11-07 | Accept the measured candidate: all campaign gates PASS | `raw/measurements.json`, `verify.py` |
| 2026-11-07 | Keep hosted CI and independent review as open external gates; no push/merge | this report |

## Rollback state

Not invoked: no size or guardrail gate failed. If a later gate fails, the
protocol is to preserve the sealed evidence, restore only the five allowed
production files to `888e819` in a new rejection commit, remove candidate-only
production-facing tests/CI wiring, and verify
`git diff --exit-code 888e819 HEAD -- <five production paths>`.

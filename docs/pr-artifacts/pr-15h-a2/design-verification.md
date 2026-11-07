# PR 15H-A2 — design verification

**A2 base:** `7a136f7f299c2f460401b9d92dcef37d219ea98c`
**Candidate:** `569132dace8d92c103dfdebd5d24167d65c0c0c0`
**Final rollback:** `29f2a372fdc1b4b3316409fc7ff218fb761ba5fb`

## Frozen production change

Only `execute.rs::evaluate_lexical_with` gains a dispatch wrapper; the historical
linear helper and `score_single_term_linear` are textually identical to the
rejected candidate (hashes below). `unified.rs` production code is unchanged
(only the historical `#[cfg(test)]` tests were transplanted).

| Helper region | SHA-256 (A2 candidate == `dce8f02`) |
|---|---|
| `evaluate_single_term_linear` | `966554bccc5d5d5a852c53713ec566122981de480a40157e92b7e6be100f1592` |
| `score_single_term_linear` | `9b811a609f4be3d16543b10a811325f1f2c417021d750966d559d5a2a4cf40ac` |

## Dispatch

```
window 1  eligibility false            → original live-bitmap scan
window 2  eligibility true, shape bad  → original CorruptIndex text
window 3  eligible, len < 8192         → original BTreeSet/score_segment path
window 4  eligible, len >= 8192        → historical linear helper
```

The shape guard runs before the threshold read. No extra work charge, cancel
poll, allocation, sorting or estimate is introduced by the dispatch. Failure on
either path propagates its own typed error with no cross-path retry.

## Counterexamples considered

| Counterexample | Resolution |
|---|---|
| 0/1 posting enters the helper | Gate sends it to the original path (A2-U01/U02) |
| Exactly 8,191 / 8,192 | Strict `>=` boundary, no off-by-one (A2-U05/U06) |
| High-cardinality segment followed by low | Per-segment dispatch; one helper call only for the high segment (A2-U10) |
| Deleted docs / stale raw df | Gate reads live-filtered postings (A2-U11) |
| Callback rejects some postings | Dispatch uses decoded length; staging preserves callback order (A2-U19) |
| Linear budget rejection | Typed `ResourceLimit`, no legacy evasion (A2-U13/U14) |
| Score fault after reservations | Historical precedence preserved (A2-U22) |
| Missing field stats | `0.0` score, no panic (A2-U12/historical helper tests) |
| PIT key mismatch | Existing fail-closed path unchanged (A2-I07/phase5) |

## State boundaries

All A2 state is per-query/per-segment. No cardinality estimate, cache, manifest,
snapshot, file or remote object changes. The threshold constant is the only new
production configuration value and is non-configurable.

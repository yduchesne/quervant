# PR 11 — Amendment 01 (finding A1): STOP report — non-finite JSON-path F64 is already rejected

**Status:** BLOCKED ON PLAN PREMISE — production change **not applied** (per plan §0 / Phase 0 STOP gate).
**Prepared:** 2026-10-14
**Branch:** `dev/json-indexing`
**Reviewed implementation SHA (plan):** `65f74401010f7d1f7f7faabf0709dee775f06597`
**Observed HEAD:** `65f74401010f7d1f7f7faabf0709dee775f06597`
**`git status --short` at start:** clean
**`git merge-base origin/main HEAD`:** `81b8a31713f79a0855210f89d8857c2e5cbb3802`
**Remote branch:** `origin/dev/json-indexing` at `65f7440…` (PR #31).

## Finding

The plan's §1 states that `skip_node` and `decode_node` "call `reader.f64(...)?` … without validating
finiteness". That premise is **false for this codebase**: `ByteReader::f64` itself already rejects
non-finite values.

Conflicting source (pre-existing since before PR 11, unchanged at `65f7440`):

```rust
// crates/quervant-core/src/segment/format.rs:350-357
pub fn f64(&mut self, context: &'static str) -> SegmentResult<f64> {
    let bits = self.u64(context)?;
    let value = f64::from_bits(bits);
    if !value.is_finite() {
        return Err(SegmentError::NonFiniteFloat { context });
    }
    Ok(value)
}
```

The two call sites the plan targets therefore already return the exact prescribed error:

- `crates/quervant-core/src/segment/json_paths.rs:869` (`skip_node`, kind 4) →
  `reader.f64("json path f64")?` → `SegmentError::NonFiniteFloat { context: "json path f64" }`.
- `crates/quervant-core/src/segment/json_paths.rs:916` (`decode_node`, kind 4) →
  `reader.f64("json path f64")?` → same error before `normalize_zero` is reached.

`JsonPathsReader::decode_directory` calls `skip_node`; `DocOccurrences::next_occurrence` calls
`decode_node`; both therefore reject NaN/±∞ with the required typed error. The acceptance target is
already met, so the prescribed `read_finite_json_f64` helper and the two branch replacements would be
redundant dead validation, and `write_node`, `normalize_zero`, the wire version and all public
contracts must remain unchanged.

## Concrete counterexample (reproduction attempt)

Prescribed tests were added against the **unmodified** production code and executed:

| Test | Location | Expected by plan (Phase 1) | Actual (HEAD `65f7440` + tests only) |
|---|---|---|---|
| A1-T01 `nonfinite_f64_rejected_by_directory_skip` | `segment/json_paths.rs` unit tests | FAIL (accepts NaN/±∞) | **PASS** — already returns `NonFiniteFloat` |
| A1-T02 `nonfinite_f64_rejected_by_occurrence_decode` | `segment/json_paths.rs` unit tests | FAIL | **PASS** — already returns `NonFiniteFloat` |
| A1-T04 `finite_f64_and_signed_zero_still_decode` | `segment/json_paths.rs` unit tests | PASS | **PASS** |
| A1-T03 `t_nonfinite_json_path_payloads_fail_at_segment_open` | `tests/pr11_json_corruption.rs` | PASS | **PASS** — valid-checksum rebuilt envelope rejected at `SegmentReader::open` with `NonFiniteFloat { context: "json path f64" }`; finite positive control opens |

Commands actually executed:

```
cargo test -p quervant-core --lib nonfinite_f64_rejected_by_directory_skip   # ok
cargo test -p quervant-core --lib nonfinite_f64_rejected_by_occurrence_decode # ok
cargo test -p quervant-core --lib finite_f64_and_signed_zero_still_decode     # ok
cargo test -p quervant-core --test pr11_json_corruption                       # 8 passed; 1 ignored
```

A1-T03 locates the unique `kind == 4` payload by walking the §2.2 wire (never scanning for `1.5`),
patches only those 8 bytes to `NaN`/`+∞`/`−∞`, and rebuilds the container through the existing
`ContainerBuilder` test helper so length/digests/footer are valid. The rejection is therefore
semantic, not checksum-driven, and occurs during `SegmentReader::open`.

## Disposition

- A1-I01…I05 are **already satisfied** by `ByteReader::f64`; A1-I06/I08 are satisfied by the
  unchanged wire/golden fixture.
- The prescribed production edit is **not applied** (would be redundant and conflicts with §1).
- The four prescribed regression tests are **retained** as guards for the already-correct behavior.
- No golden fixture was regenerated; no wire/feature/public API/search semantics changed.

## Requested corrected plan

Choose one:

1. **Close A1 as no-change** (recommended): the generic `ByteReader::f64` finiteness guard is the
   intended enforcement, and A1-T01…T04 are accepted as the regression evidence.
2. **Provide a genuine bypass**: if a concrete code path can read a JSON-path F64 without
   `ByteReader::f64`, supply that path/counterexample; only then is a JSON-path-local helper needed.

Until a corrected plan is provided, this amendment remains **BLOCKED / NOT VERIFIED** and PR #31 stays
open.

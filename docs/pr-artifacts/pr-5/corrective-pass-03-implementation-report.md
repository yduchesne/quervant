# PR 5 corrective pass 03 implementation report

> **Branch:** `dev/segment-codecs`
> **Pre-pass-03 baseline:** `5e441a64fb168688ffb0876f9528aa8fd2b4817c`
> **Status:** manifest preallocation budget enforcement complete; awaiting
> independent review. **No merge.**

## 1. Finding and fix

`Manifest::decode` reserved the cumulative modeled retained-memory budget only
*after* allocating owned ID/key strings, the duplicate-index clone, and feature
vectors. Pass 03 enforces the cumulative modeled charge **before each
corresponding retained allocation**.

### Baseline defect (source-level, exact lines at `4a62cc2`)

| Step | Baseline line | Behavior |
|---|---|---|
| Owned segment ID | `manifest.rs:177` `decode_string(...)` | Allocates `String` before per-entry cumulative charge |
| Duplicate-index clone | `manifest.rs:192` `object_keys.insert(object_key.clone())` | Clones/allocates key before its charge is included |
| Per-segment feature vectors | `manifest.rs:226`, `:228` `decode_features(...)` | Allocate `Vec` before cumulative charge |
| Manifest-level feature vectors | `manifest.rs:247`, `:249` `decode_features(...)` | Allocate `Vec` before cumulative charge |
| Cumulative check | `manifest.rs:244`, `:261` `check_decoded_bytes` | Runs after the allocations above |

A custom `#[global_allocator]` could demonstrate this with an allocation-order
red, but the plan's §10 forbids introducing a custom allocator without a separate
decision, so this is recorded as a candid source-level audit.

### Post-fix allocation-order audit (`manifest.rs`, final tree)

Each charged allocation is immediately preceded by an individual check and a
cumulative `ManifestDecodeBudget::reserve`:

| Charged allocation | Individual check | Cumulative reserve | Allocation |
|---|---|---|---|
| `segments` vector backing | `:151` `check_alloc::<ManifestSegmentRef>` | `:164` `budget.reserve(segment_vector_charge)` | `:167` `try_reserve_exact` |
| owned segment ID | `:193` `check_allocation_bytes(id_len)` | `:194` `budget.reserve(segment_id_charge)` | `:195` `to_owned` |
| owned object key + index clone | `:210`/`:211` `check_allocation_bytes` | `:218` `budget.reserve(object_key_charge)` | `:219` `to_owned`, `:220` `insert(object_key.clone())` |
| per-segment feature vector | `:387` `check_alloc::<(u16,u16)>` | `:388` `budget.reserve(features_charge)` | `:389` `Vec::with_capacity` |
| manifest-level feature vector | same `decode_features_budgeted` path | same | same |

`object_key_charge` = `2 * key.len()` (original + duplicate-index clone) +
`DUPLICATE_INDEX_BYTES` (`size_of::<String>() + 32` estimate). Borrowed
`trawler_objectstore::validate_key(&str)` replaces the previous temporary owned
validation clones.

## 2. Files changed

- `crates/trawler-core/src/segment/manifest.rs`: `ManifestDecodeBudget`,
  `segment_vector_charge` / `segment_id_charge` / `object_key_charge` /
  `features_charge`, `decode_features_budgeted`, borrowed ID/key handling,
  updated `retained_bytes` model documentation.
- new `crates/trawler-core/tests/segment_corrective_pass03.rs` (11 tests).

Untouched: F01–F12 bytes, encoder, `limits.rs`, `format.rs`, `schema.rs`,
`reader.rs`, public storage APIs, golden fixture, Cargo manifests/lockfile.

## 3. Semantic contract preserved

- `max_section_decode_bytes` remains a deterministic **modeled peak-retained
  decode charge**, explicitly not heap/RSS/allocator capacity.
- `max_single_allocation` individual prechecks remain.
- Duplicate-key detection is global (including nonadjacent), IDs strictly
  ascending, features strictly ascending/duplicate-free, required features
  negotiated.
- Decode is all-or-error; no partial `Manifest` is returned.
- `Manifest::retained_bytes()` equals the decoder's final charge on success
  (enforced by a `debug_assert` in tests); it includes the temporary duplicate
  index even though the returned manifest does not retain it.
- `CodecSchema::decode` keeps independent limits; no global budget introduced.

## 4. Residual risks

| Risk | Disposition |
|---|---|
| Logical charge ≠ allocator metadata/RSS | Explicit documented model |
| Fixed `BTreeSet` node overhead estimate | Accepted under modeled contract |
| Schema and manifest budgets independent | Deferred, not pass 03 |
| Custom allocator not allowed, so no allocation-count red | Documented source audit + stage-prefix tests |

## 5. Validation

See `corrective-pass-03-validation-report.md`. All mandatory gates pass on the
final tree; no merge.

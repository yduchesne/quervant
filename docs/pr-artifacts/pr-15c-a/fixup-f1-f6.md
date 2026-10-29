# F1–F6 fallible metadata-allocation fixup — S0 preflight

Written before any production edit (plan §2).

## 1. Baseline

| Item | Value |
|---|---|
| Branch | `dev/pr15c-a-immutable-segment` |
| HEAD | `0c2a121766f1f6cfce695f5ed373dfaa360df714` (matches the plan) |
| `git status --porcelain` | empty |
| Toolchains | `rustc 1.98.1` (stable), `rustc 1.85.0` (MSRV), `cargo-llvm-cov 0.9.1` |
| `cargo +1.85.0 check -p quervant-core` | exit 0 |
| `cargo test -p quervant-core --lib` | exit 0 — 830 passed, 1 ignored |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | exit 0 — 5 passed |
| `cargo test -p quervant-core --test pr15b_diagnostics` | exit 0 — 16 passed |

Decision rows: **X01** (exact baseline, clean tree), **X29** (`docs/TESTING.md`
conflict markers remain baseline-only; untouched).

## 2. Findings to repair (audit §5 of `fixup-c15a02-c15a03.md`)

All six are **capacity-accounting-correct but infallible**: the retained capacity is
precharged (or covered by the parser allowance) before allocation, but the
allocation itself aborts the process on failure instead of returning the typed
`SegmentError::LimitExceeded` that `VerifiedSegmentState::build_cached` classifies
as an optional cache failure.

| ID | Symbol / site (current source) | Current allocation |
|---|---|---|
| F1 | `format.rs::parse_container` section directory (`limits.check_alloc::<SectionEntry>` then `Vec::with_capacity(section_count as usize)`) | `Vec::with_capacity` |
| F1 | `format.rs::read_features` (`check_alloc::<(u16,u16)>` then `Vec::with_capacity(count as usize)`) | `Vec::with_capacity` |
| F2 | `reader.rs::decode_metadata` → `view.sections().to_vec()`, `view.required_features().to_vec()`, `view.optional_features().to_vec()` (after `meter.charge_vec`) | `slice::to_vec` |
| F3 | `reader.rs::decode_geo_bounds` → `Vec::with_capacity(count as usize)` (after `meter.charge_vec::<GeoBounds>`) | `Vec::with_capacity` |
| F4 | `reader.rs::try_build_cached` → `Arc::new(candidate.with_metadata(reservation))`; `reader.rs::decode_metadata` → `Arc::new(JsonPathsReader::decode_directory_metered(..))` | `Arc::new` |
| F5 | `schema.rs` field names (`name_ref.to_owned()`), `FieldBinding::decode_budgeted` `id`/`version` (`to_owned`), `dictionary.rs` term (`term_ref.to_owned()`) | `str::to_owned` |
| F6 | `remap.rs::decode_metered` state `1` → two `Vec::with_capacity(doc_count)` | `Vec::with_capacity` |

Preserved by contract: `DecodeBudget`/`MetadataMeter` charges and their ordering,
candidate-allowance admission, `finalize(measured)` reconciliation, the snapshot
state machine/fallback classification, wire format, public signatures,
`SegmentLimits`/`IndexLimits` and telemetry. `segment/metadata.rs` is not edited.

## 3. F4 hard-stop record (X20)

Probe (`/tmp/arc_probe`, `edition = "2021"`, `let value = Arc::try_new(7u64);`):

```
$ cargo +1.85.0 build   (rustc 1.85.0 (4d91de4e4 2025-02-17))
error[E0658]: use of unstable library feature `allocator_api`
 --> src/main.rs:4:17
  |
4 |     let value = Arc::try_new(7u64);
  |                 ^^^^^^^^^^^^
  |
  = note: see issue #32838 <https://github.com/rust-lang/rust/issues/32838> for more information

$ cargo +1.98.1 build   (rustc 1.98.1 (48a229cea 2026-09-01))
error[E0658]: use of unstable library feature `allocator_api`   (same diagnostic)
```

`Arc::try_new` is **not available on the workspace MSRV (1.85.0) nor on current
stable**. Per X20 the F4 sites are **HARD STOPPED**: no `unsafe`, no custom
allocator, no panic-catching, no alternative representation. F1/F2/F3/F5/F6
proceed independently. Consequence: PR 15C-A acceptance remains blocked on an F4
architecture/feasibility decision by the architecture owner.

Feasibility alternatives for that decision (not chosen here): (a) keep `Arc::new`
with the existing precharge and document the residual abort risk; (b) wait for the
`allocator_api` stabilisation of `Arc::try_new`; (c) an approved representation that
avoids a separately allocated accounted `Arc` payload. Selecting one is an
architecture decision, not an implementation choice in this fixup.

## 4. Counterexample probes (pre-edit, recorded before implementation)

| Boundary | Probe | Expected / observed |
|---|---|---|
| zero count | `Vec::new()` + no `try_reserve` (F1 empty feature list, F3 count 0, F6 `doc_count = 0`) | empty vector, `capacity() == 0`, success |
| singleton / exact count | F1/F2/F3/F6 with 1 element | `capacity() == count`, no growth past capacity |
| large count | F6 `reserve_pair(1024)`; F1 max-sections fixture | `capacity() == count`, no implicit growth |
| overflow | `Vec::<SectionEntry>::with_capacity(usize::MAX)` panics (capacity overflow) vs the new helper → typed `LimitExceeded` | witness T02/T06 mechanism |
| cap one-under | existing `c15a01_t06_absent_remap_falls_back_one_under_allowance` | verified uncached fallback, no READY, no charge |
| malformed input | existing `g3_02`, `g3_03`, `g3_04`, `g3_04b`, `c15a02_t05` | original typed corruption errors |
| allocation failure | `try_reserve_exact(usize::MAX)` (guaranteed `CapacityOverflow`) for vectors; `String::try_reserve_exact(usize::MAX)` for strings | typed error, no panic |
| concurrent acquisitions | existing `g4_01` (2/8/32-thread barrier), `g2_11` | one verification, shared `Arc`, unchanged admission |

## 5. FI → test traceability (tests written in module test blocks)

| FI | Witnesses |
|---|---|
| FI-01 | `f1_t01_parser_feature_and_section_counts`, `f2_t03_slice_copies_are_exact`, `f6_t05_reserve_pair_capacities`, existing `c15a01_t05`, `g2_02` |
| FI-02 | `f1_t01`, `f1_t02`, `f2_t03`, `f3_t04`, `f5_t07`, `f6_t05`, `f6_t06`, plus the T16 F4 record |
| FI-03 | `f1_t02` (typed limit, no partial state), `f6_t06` (typed overflow), `c15a01_t06`, `g2_12`, `g2_04` |
| FI-04 | `f5_t07` (invalid UTF-8 / duplicate term unchanged), `g3_02`, `g3_03`, `g3_04`, `g3_04b` |
| FI-05 | `g1_05` (cached vs uncached parity), `f2_t03`, `f3_t04`, `f6_t05`, `pr15c_a_t01…t05` |
| FI-06 | `g4_01`, `g2_11`, `g4_09`, `g4_11`, `pr15c_a_t02`/`t03` |
| FI-07 | `c15a01_t05`, `g3_01` (one verification), `c15a01_t06`/`g2_12` (fallback) |
| FI-08 | this document §3 (no unsafe, no allocator API, no alternative representation) |

## 6. Intended exact changes

1. `format.rs`: add crate-private `reserve_exact_vec<T>(&mut Vec<T>, count: usize, limits: &SegmentLimits) -> SegmentResult<()>` — no-op for `count == 0`, otherwise `try_reserve_exact(count)` mapped to `LimitExceeded { limit: limits.max_single_allocation(), requested: count * size_of::<T>() }` with checked arithmetic. Use it at the two F1 sites (after the existing `check_alloc`).
2. `reader.rs`: add private `copy_slice_fallible<T: Copy>(source: &[T], limits: &SegmentLimits) -> SegmentResult<Vec<T>>` (`Vec::new`, `reserve_exact_vec`, `extend_from_slice`) and use it for the three F2 copies, keeping the meter charges before it; use `reserve_exact_vec` for F3.
3. `remap.rs`: add private `reserve_pair_with(first, second, limits) -> SegmentResult<(Vec<u64>, Vec<u64>)>` (drops the first vector if the second reservation fails) and `reserve_pair(doc_count)`; use `reserve_pair` in `identity_fallible` and `decode_metered` state `1` (before reading any data).
4. `schema.rs`: add `pub(crate) fn copy_str_fallible(source: &str, limits: &SegmentLimits) -> SegmentResult<String>` (`String::new`, `try_reserve_exact(source.len())`, `push_str`) and use it for field names and binding id/version; `dictionary.rs` imports it for terms. No change to diagnostic/error-message strings.
5. `segment/metadata.rs`, `index/snapshot.rs` production paths, formats, limits, public APIs: unchanged. Test-only additions allowed in the module test blocks.

---

# Results (S1–S6) — executed

| Item | Value |
|---|---|
| Baseline SHA (S0) | `0c2a121766f1f6cfce695f5ed373dfaa360df714` |
| Fix commit | `b3c72b9727becbde06ee10ea1850f08defa7b821` |
| Evidence commit | this document+artifacts commit (HEAD) |
| Diff (fix commit) | `format.rs` +168/−?, `reader.rs` +201, `remap.rs` +151, `schema.rs` +132, `dictionary.rs` +67 (production edits plus colocated tests) |
| Tree | clean |

## 1. Source changes landed

### F1 — `segment/format.rs` (IMPLEMENTED)

* New crate-private `reserve_exact_vec<T>(&mut Vec<T>, count, &SegmentLimits) -> SegmentResult<()>`:
  no-op for `count == 0`, otherwise `try_reserve_exact(count)` mapped to
  `LimitExceeded { limit: limits.max_single_allocation(), requested: checked(count × size_of::<T>()) }`.
* `parse_container` section directory (`Vec::new()` + `reserve_exact_vec`, after the
  existing `check_alloc::<SectionEntry>`) and `read_features` required/optional lists
  (`Vec::new()` + `reserve_exact_vec`, after `check_alloc::<(u16,u16)>`) — reservations
  happen before any `push`; section/feature ordering, validation and digests unchanged.

### F2 — `segment/reader.rs` (IMPLEMENTED)

* New private `copy_slice_fallible<T: Copy>(source, limits, meter) -> SegmentResult<Vec<T>>`:
  meter charge for `source.len()` **before** allocation, `reserve_exact_vec`, then
  `extend_from_slice` (cannot grow past capacity).
* `decode_metadata` now copies `sections`, `required`, `optional` through it. The
  previous separate `meter.charge_vec` block was replaced (not duplicated), so the
  charge amount, order and total are unchanged.

### F3 — `segment/reader.rs` (IMPLEMENTED)

* `decode_geo_bounds` uses `Vec::new()` + `reserve_exact_vec(count)`; the existing
  `check_entries`/`check_alloc`/`count_min_bytes` checks, meter charge, decode order and
  trailing-byte validation are unchanged.

### F5 — `segment/schema.rs`, `segment/dictionary.rs` (IMPLEMENTED)

* New `pub(crate) copy_str_fallible(source: &str, limits) -> SegmentResult<String>`
  (`String::new()`, `try_reserve_exact(source.len())` — bytes, not chars, `push_str`).
* Applied to retained field names, `FieldBinding.id`/`.version` (limits threaded through
  the private `decode_budgeted`/`decode_optional_binding_budgeted` helpers) and dictionary
  terms (`use super::schema::copy_str_fallible`). Error-message/diagnostic strings are
  untouched, and the final `String::capacity()` accounting in `metadata_charge()` remains.

### F6 — `segment/remap.rs` (IMPLEMENTED)

* New private `reserve_pair_with(first, second)` and `reserve_pair(doc_count)` plus
  `reserve_exact_u64`: both arrays are reserved before any value is read or written; the
  first vector is dropped if the second reservation fails.
* `identity_fallible` now uses `reserve_pair` (behaviour and error shape unchanged), and
  `DocRemap::decode_metered` state `1` reserves both arrays fallibly **before** reading the
  permutation payload, reusing the same technique. `DecodeBudget`/meter charges unchanged.

### F4 — `segment/reader.rs` (HARD STOPPED, X20)

Not implemented. `Arc::try_new` is unstable on the workspace MSRV and on current stable
(see §3 of the S0 section above), and the plan forbids unsafe, custom allocators,
`Box::try_new` conversion tricks or panic-catching. The two accounted `Arc::new` sites keep
their precharge and remain the only infallible retained allocations on this path. PR 15C-A
acceptance stays blocked on an architecture/feasibility decision for F4.

## 2. Witness results

| ID | Test | Placement | Result |
|---|---|---|---|
| T01 (F1) | `format::fallible_parser_tests::f1_t01_parser_feature_and_section_counts` | `format.rs` | PASS — empty, singleton and max-legal (17 sections, 1024 required + 1024 optional features) lists parse to exactly the declared content, flags, aux, lengths and digests |
| T02 (F1, FI-03) | `f1_t02_feature_limit_and_malformed_inputs_are_typed` | `format.rs` | PASS — `LimitExceeded { limit: 1024, requested: 1025 }` for one-over required and optional features before allocation; truncation and `with_max_single_allocation(1)` keep typed errors; `reserve_exact_vec(usize::MAX)` returns `LimitExceeded` while `Vec::with_capacity(usize::MAX)` panics |
| T03 (F2, FI-01) | `reader::fallible_metadata_tests::f2_t03_slice_copies_are_exact` | `reader.rs` | PASS — 0/1/9 entries byte-identical and order-preserving, `capacity() == len`, empty source → capacity 0; metered allowance of exactly 9 entries admits, one entry less rejects with `LimitExceeded` and refunds (`budget.used() == 0`); `usize::MAX` request is typed |
| T04 (F3) | `f3_t04_geo_bounds_decode_unchanged` | `reader.rs` | PASS — empty/singleton/12-entry vectors decode to identical values; truncated and trailing-byte input keep `Truncated`/`Corrupt`; over-limit count rejected by the existing allocation check |
| T05 (F6, FI-05) | `remap::tests::f6_t05_reserve_pair_and_explicit_permutation` | `remap.rs` | PASS — `reserve_pair` capacities exactly `0/1/5/1024`; explicit state-1 permutation `[2,0,1]`/`[1,2,0]` round-trips against the hand-authored mapping, re-encodes and re-decodes identically; truncation fails closed |
| T06 (F6, FI-03) | `f6_t06_reserve_pair_failures_are_typed` | `remap.rs` | PASS — `reserve_pair(usize::MAX)` typed; `reserve_pair_with(4, usize::MAX)` (second reservation fails) returns `LimitExceeded` with the first vector dropped; mixed `(4,6)` succeeds; `Vec::<u64>::with_capacity(usize::MAX)` panics while `identity_fallible(usize::MAX)` is typed |
| T07 (F5) | `schema::fallible_string_tests::f5_t07_strings_are_byte_exact`, `dictionary::fallible_term_tests::f5_t07_dictionary_terms_are_byte_exact` | `schema.rs`, `dictionary.rs` | PASS — empty/ASCII/multibyte strings byte-exact with byte-length capacity (`hôst`, `日本語キー`, `emoji-🌍-key`); multibyte binding id/version round-trip; malformed UTF-8 keeps `InvalidUtf8`; duplicate/unsorted terms keep `DuplicateTerm`; metered dictionary equals the unmetered directory |
| T07b (F5) | `f5_t07b_string_reservation_failure_is_typed` | `schema.rs` | PASS — `String::try_reserve_exact(usize::MAX)` is `Err` while `String::with_capacity(usize::MAX)` panics |
| T08 (FI-03) | inherited `c15a01_t05_absent_remap_segment_is_cached_and_reused`, `c15a01_t06_absent_remap_falls_back_one_under_allowance`, `g2_02` | `index/snapshot.rs` | PASS (re-executed) — exact allowance admits, allowance−1 falls back with no READY/charge and released admission |
| T09 (FI-02/03) | `f1_t02` (budget rejection before allocation), `f6_t06` (reservation failure), `f5_t07b` (string mechanism) | as above | PASS — typed failures, no partial state, no leaks. **Not feasible** without a production seam: forcing a real `TryReserveError` at F2/F3/F5 vector/string sizes requires exhausting memory; recorded as such (X24/limitation) |
| T10 (FI-04) | inherited `g3_02`, `g3_03`, `g3_04`, `g3_04b`, `c15a02_t05` | `index/snapshot.rs`, `json_paths.rs` | PASS (re-executed) — original typed corruption, no fallback masking |
| T11 (FI-05) | inherited `g1_05_zero_cap_and_cached_readers_are_equivalent` | `index/snapshot.rs` | PASS — cached vs uncached parity for keys/stored/live/schema/remap/norms/dictionary+postings/spatial/columns |
| T12 | `pr15c_a_segment_state` (5), `pr15b_diagnostics` (16 frozen oracles) | integration | PASS — no fixture or baseline file changed |
| T13 (FI-06) | workspace suites (PIT/generation/mask/mutation: `pr14a*`, `pr15a*`, `pr09_visibility`, `pr14_unified_cursor`, …) | workspace | PASS — 114 targets, 2172 tests |
| T14 (FI-06/07) | inherited `g4_01` (2/8/32 threads), `g2_11`, `g4_09`, `g4_11` | `index/snapshot.rs` | PASS (re-executed) — one verification, shared `Arc`, unchanged admission charges |
| T15 (FI-08) | `pr13_remote --ignored` | integration | **BLOCKED — ENVIRONMENT** (`QUERVANT_RUSTFS_ENDPOINT … NotPresent`, no Docker daemon) |
| T16 (F4) | `/tmp/arc_probe` compile probe | host | **BLOCKED** — `Arc::try_new` is E0658 `allocator_api` (issue #32838) on 1.85.0 **and** stable 1.98.1 |

## 3. Adversarial counterexamples (executed, safe and bounded)

| Class | Old construct | Replacement | Evidence |
|---|---|---|---|
| F1 vector | `Vec::<SectionEntry>::with_capacity(usize::MAX)` → panic (capacity overflow) | `reserve_exact_vec(.., usize::MAX, ..)` → `LimitExceeded` | `f1_t02` |
| F6 vectors | `Vec::<u64>::with_capacity(usize::MAX)` → panic | `reserve_pair(usize::MAX)` → `LimitExceeded`; `reserve_pair_with(4, usize::MAX)` → typed with the first vector dropped | `f6_t06` |
| F5 string | `String::with_capacity(usize::MAX)` → panic | `try_reserve_exact(usize::MAX)` → `Err` | `f5_t07b` |
| F2/F3 vectors | `to_vec()`/`with_capacity(count)` are only reachable with a representable count ≤ `max_single_allocation`, so a real `TryReserveError` cannot be forced without exhausting memory | `copy_slice_fallible`/`reserve_exact_vec` reserve exactly and return the typed error | Code-level + typed-overflow witnesses; documented limitation (no memory-exhaustion probe attempted) |

All probes are bounded (no actual large allocation is attempted; `capacity() > isize::MAX`
short-circuits before any allocator call).

## 4. Accounting preservation (FI-01)

* F2: charge amount/order unchanged — the meter still charges `sections/required/optional`
  lengths before the copy, now inside `copy_slice_fallible` (the previous duplicate block was
  removed, so nothing is double charged).
* F1: parser-side reservations stay inside `parser_allowance()` (bounded by
  `max_sections`/`max_features`); `try_reserve_exact` yields `capacity == count`, so measured
  capacity cannot exceed the allowance, and `finalize(measured)` remains the publication gate.
* F3/F5/F6: charges are issued before the allocation by the existing `meter.charge_vec`/
  `charge_str` calls; `metadata_charge()` still measures actual capacities and `finalize`
  discards a candidate whose measured charge exceeds its allowance (`c15a01_t02`/`g2_02`
  still pass).

## 5. Gate evidence (fix commit `b3c72b9`, clean tree)

| Command | Exit | Result |
|---|---|---|
| `cargo fmt --all -- --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo test -p quervant-core --lib` | 0 | PASS — **839 passed**, 1 ignored (was 830) |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | PASS — 5 passed |
| `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | PASS — 16 passed (frozen oracles) |
| `cargo test --workspace --all-features` | 0 | PASS — 114 targets, **2172 tests**, 0 failed (was 2163) |
| `cargo +1.85.0 test --workspace --all-features` | 0 | PASS — 2172 tests, 0 failed |
| `cargo test -p quervant-core --release --lib` | 0 | PASS — 839 passed |
| `cargo doc --workspace --no-deps` | 0 | PASS — no warnings |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | PASS — **91.81% lines** / 92.31% regions / 87.89% functions (`format.rs` 89.73%, `reader.rs` 87.80%, `remap.rs` 95.28%, `schema.rs` 89.13%, `dictionary.rs` 83.74%) |
| `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored` | 1 | **BLOCKED — ENVIRONMENT** |

Logs: `/tmp/f4_{fmt,clippy,check185,clippy185,lib,pr15c,pr15b,ws,ws185,release,doc,cov}.log`,
F4 probe `/tmp/f4_probe.txt`.

Failure classification: no mandatory gate failed. The only non-passing command is the
pre-existing external RustFS gate (environment, not code). No retries, no suppression, no
limit change.

## 6. Decision-matrix rows exercised

`X01` (exact baseline, clean tree), `X03` (sites located by symbol), `X05` (reused
`check_alloc::<T>` for the typed limit shape), `X07` (zero count reserves nothing: F1 empty
features, F3 count 0, F6 `doc_count = 0`), `X08` (validated counts reserve then fill without
growth), `X09` (checked count × element-size overflow), `X10` (typed `TryReserveError`
mapping), `X11` (measured-capacity reconciliation unchanged via `metadata_charge`/`finalize`),
`X12` (`DecodeBudget` denials propagate unchanged), `X13` (corruption untouched), `X14`
(meter/cap rejection keeps the verified fallback), `X15` (standalone `SegmentReader::open`
signature/behaviour preserved), `X17` (F6 state 0 preserved), `X18` (second-reservation
failure drops the first vector), `X19` (string bytes, not chars), **`X20` (F4 HARD STOP:
`Arc::try_new` unstable on 1.85.0/stable, documented)**, `X23` (test corrections within the
authorized algorithm), `X24` (no production seam invented for T09; limitation documented),
`X27`/`X28` (RustFS/CI deferred, acceptance blocked), `X29` (`docs/TESTING.md` untouched),
`X30`/`X31` (no budget/format/API/dependency change), `X32`/`X33` (no new retained owner; all
remaining scratch allocations were already recorded as temporary), `X34`/`X35` (F4 blocked
independently while F1/F2/F3/F5/F6 completed), `X37`/`X39` (local gates, then rerun on the
final evidence SHA).

No `X99` condition arose beyond the preauthorized F4 stop.

## 7. Status

| Item | Status |
|---|---|
| F1 parser vectors | IMPLEMENTED + VERIFIED LOCAL |
| F2 retained slice copies | IMPLEMENTED + VERIFIED LOCAL |
| F3 geo-bounds vector | IMPLEMENTED + VERIFIED LOCAL |
| F5 retained strings | IMPLEMENTED + VERIFIED LOCAL |
| F6 explicit-remap vectors | IMPLEMENTED + VERIFIED LOCAL |
| F4 accounted `Arc` payloads | **HARD STOP (X20)** — blocked on MSRV/stable availability of `Arc::try_new`; architecture decision required |
| Real RustFS / exact-head CI | **BLOCKED — ENVIRONMENT / NOT RUN** |
| PR 15C-A acceptance | **NOT ACCEPTED** — F4 unresolved and external gates missing |
| Merge / roadmap DONE | NOT PERFORMED |

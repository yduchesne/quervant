# C15A-02 / C15A-03 fixup — pre-implementation gate (S0)

Written **before** any production edit, per plan §4.4.

## 1. Baseline

| Item | Value |
|---|---|
| Branch | `dev/pr15c-a-immutable-segment` |
| HEAD at start | `5695709c1cb2331389afe4380b86831c4dbac91f` (matches the plan's required SHA) |
| `git merge-base main HEAD` | `42b19445dd79a90d8701b4306e305c6e4e44cd57` |
| Working tree | clean (`git status --short` empty) |
| Toolchain | `rustc 1.98.1` stable + `cargo +1.85.0` (MSRV), `cargo-llvm-cov 0.9.1` |

Baseline commands (unmodified branch):

| Command | Exit | Result |
|---|---|---|
| `cargo fmt --all -- --check` | 0 | PASS |
| `cargo test -p quervant-core --lib` | 0 | PASS — 819 passed, 1 ignored |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | PASS — 5 passed |
| `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | PASS — 16 passed |

Decision rows: **X01** (branch + base exact, clean tree), **X04** (line numbers
may shift; functions identified by symbol), **X37** (`docs/TESTING.md` conflict
markers remain baseline-only and untouched).

## 2. Confirmed defect sites (symbol-level)

### C15A-02 — JSON offset vector growth is not pre-charged

`crates/quervant-core/src/segment/json_paths.rs::JsonPathsReader::decode_directory_metered`
(`~1071` `let mut doc_offsets: Vec<JsonDocOffset> = Vec::new();`; emission sites
`~1147-1156` and `~1165-1175`):

```rust
budget.reserve_bytes(doc_offset_charge())?;   // logical record accounting
if let Some(meter) = meter.as_deref_mut() {
    meter.charge_vec::<JsonDocOffset>(1)?;    // charges ONE element
}
doc_offsets.push(JsonDocOffset { .. });       // may reserve 4/8/16/… slots
```

`Vec::push` grows amortized (from empty: 4, then 8, 16, …). The retained capacity
increment is therefore much larger than the one element charged before the
allocation, so uncharged retained capacity is allocated — a VSR-G2-04
violation ("reserve this amount **before** the allocating operation"). The
post-hoc `measured_charge()` reconciliation keeps the *final* account correct but
does not satisfy the normative preallocation contract.

### C15A-03 — identity remap construction is infallible in metered paths

`crates/quervant-core/src/segment/remap.rs::DocRemap::identity` (`~15-23`) uses
`(0..doc_count as u64).collect()` twice — infallible, amortized growth — and is
called from two metered paths after charging:

* `DocRemap::decode_metered` state `0` (`~144-160`), and
* `segment/reader.rs::decode_metadata` absent-`SortedRemap` branch (`~735-767`).

VSR-G2-04 requires `try_reserve_exact`/equivalent bounded allocation after the
precharge; `collect()` gives no capacity control and aborts the process on
allocation failure instead of returning the typed resource error that routes to
the verified uncached fallback.

### Preserved behaviour (must not change)

`segment/reader.rs::decode_allowance` now charges `2*doc_count*size_of::<u64>()`
unconditionally (C15A-01). `segment/metadata.rs` (CAS budget, RAII, charge
accounting) and the `index/snapshot.rs` state machine/fallback are **not** edited.

## 3. Intended changes (exact)

### C15A-02 (`json_paths.rs`)

1. New private `push_doc_offset(doc_offsets: &mut Vec<JsonDocOffset>, value: JsonDocOffset, meter: &mut Option<&mut MetadataMeter>) -> SegmentResult<()>`:
   * `len < capacity` → `push` with **no** charge (no growth);
   * `len == capacity` → `new_cap = len.checked_add(1)` (typed overflow),
     `delta = new_cap - old_cap`, `meter.charge_vec::<JsonDocOffset>(delta)`
     **before** `try_reserve_exact(delta)`;
   * after the fallible reservation, read `capacity()`; if `actual > new_cap`
     charge `actual - new_cap` **before** the append; a failed excess charge
     returns the typed `LimitExceeded` and discards the candidate;
   * never call `reserve`/`with_capacity`/implicit-growth `push` for a growing
     append. Applied in unmetered mode too (fallible reserve always; metering
     conditional) per AD-FX-01.
2. Both emission sites call the helper; `budget.reserve_bytes(doc_offset_charge())`
   stays exactly once per emitted record (unchanged `DecodeBudget` semantics).
3. `#[cfg(test)]`-only growth probe (`json_paths::growth_probe`) records
   `old_capacity`, `requested_capacity`, `charged_before`, `actual_capacity`,
   `charged_extra` for each growth so tests can prove ordering. No release
   interface, no public API.

### C15A-03 (`remap.rs`, `reader.rs`)

4. New private `DocRemap::identity_fallible(doc_count: usize) -> SegmentResult<Self>`:
   `Vec::new()` + `try_reserve_exact(doc_count)` for **both** arrays before any
   fill (first array dropped if the second fails), then `u64::try_from(i)` pushes
   in `for i in 0..doc_count`; no `collect`, no `vec![]`, no `with_capacity`.
   `doc_count == 0` performs no heap reservation.
5. New `pub(crate) DocRemap::identity_metered(doc_count, meter)` centralizes the
   two `charge_vec::<u64>(doc_count)` charges **once**, calls
   `identity_fallible`, and charges any allocator capacity excess
   (`capacity > doc_count`) before returning (AD-FX-04).
6. `DocRemap::decode_metered` state `0` uses `identity_metered` (caller-side
   charges removed, `DecodeBudget` reservations unchanged); `decode_metadata`'s
   absent-section branch uses `identity_metered` in place of the manual charges +
   `DocRemap::identity`.
7. Public `DocRemap::identity(usize) -> Self` is **unchanged** (X20) and remains
   the only constructor for non-cached callers.

## 4. Invariant → test mapping (test-before-code)

| Invariant | Witness | Location |
|---|---|---|
| FX-I01 | `c15a02_t02_each_offset_growth_is_pre_charged` (growth events: `charged_before == requested - old`, `charged_extra == actual - requested`, `actual == requested`) | `json_paths.rs` tests |
| FX-I01 | `c15a02_t01_zero_offsets_charge_nothing` | `json_paths.rs` tests |
| FX-I02 | `c15a02_t04_allocator_excess_is_reconciled_before_append` (charge-excess helper with real over-reserved vector + rejection case) | `json_paths.rs` tests |
| FX-I03 | `c15a02_t03_multi_field_runs_and_budget_boundary` (independent run oracle + exact `doc_offset_charge()` budget boundary) | `json_paths.rs` tests |
| FX-I06 | `c15a02_t05_malformed_section_after_append_fails_closed` | `json_paths.rs` tests |
| FX-I04 | `c15a03_t06_identity_fallible_matches_public_identity` (0/1/5/1024, both directions, exact capacity) | `remap.rs` tests |
| FX-I04 | `c15a03_t07_identity_fallible_overflow_is_typed` (`usize::MAX` → typed `LimitExceeded`, no panic) | `remap.rs` tests |
| FX-I05 | `c15a03_t08_state_zero_and_absent_section_agree` (`decode_metered(&[0])` vs `identity_fallible`, plus reader-level absent vs state-0 container) | `remap.rs` + `index/snapshot.rs` tests |
| FX-I06 | `c15a01_t06_absent_remap_falls_back_one_under_allowance` (inherited, exact fit) | `index/snapshot.rs` tests |
| FX-I06 | `g3_02_envelope_corruption_fails_closed`, `g3_04b_malformed_json_paths_fail_closed`, `c15a01_t09` (inherited) | `index/snapshot.rs` tests |
| FX-I07 | `g2_11_cache_hits_keep_full_admission_charge`, `c15a01_t05_absent_remap_segment_is_cached_and_reused` (inherited, includes `Arc::ptr_eq`, `2*len` admission) | `index/snapshot.rs` tests |
| FX-I07 | `g1_05_zero_cap_and_cached_readers_are_equivalent` (inherited: JSON-path directory + spatial + columns parity) | `index/snapshot.rs` tests |
| FX-I08 | real RustFS harness — **BLOCKED-ENVIRONMENT** on this host | `pr13_remote --ignored` |
| FX-I09 | diff allowlist review + `pr15b_diagnostics` frozen oracles | git / test command |

Boundary table (JSON offset counts): `0` offsets (no allocation, no charge),
`1` offset (single growth event), `≥9` offsets (12) — forces several growth
events under the exact-incremental policy and would leave `capacity != len`
under the pre-fix amortized `push`.

## 5. Regression-killer plan (X21/X22)

* **C15A-02:** assert the final `doc_offsets.capacity() == doc_offsets.len()`
  for a 12-offset directory. Pre-fix `Vec::push` amortization from empty reserves
  4 → 8 → 16 slots, so the pre-fix capacity (16) differs from `len` (12) and the
  assertion fails. Additionally, the growth-probe assertions
  (`charged_before == capacity delta`, `charged_extra == actual - requested`)
  cannot hold pre-fix because no per-growth charge exists.
* **C15A-03:** assert that the metered identity path is the fallible constructor,
  i.e. `identity_fallible(usize::MAX)` returns a typed `LimitExceeded` instead of
  aborting, and that `identity_metered` charges are exactly
  `2*doc_count*size_of::<u64>()` for the tested counts. Pre-fix no such
  constructor exists (compile-level witness) and `identity(usize::MAX)` would
  abort.
* Both witnesses will be executed against the pre-fix code by temporarily
  reverting only the affected hunks (throwaway local patch, restored afterwards),
  and the observed failures recorded verbatim in the evidence document.

## 6. Anticipated audit findings (AD-FX-06, X31)

Preliminary inspection shows additional infallible-allocation sites inside the
metered cached path that are **out of scope** for C15A-02/C15A-03 and will be
recorded (not patched) in the S4 audit table:

* `DocRemap::decode_metered` state `1`: `Vec::with_capacity(doc_count)` for both
  arrays (charged first and exact-capacity, but infallible).
* `reader.rs::decode_metadata`: `view.sections().to_vec()`,
  `view.required_features().to_vec()`, `view.optional_features().to_vec()`.
* `schema.rs` / `dictionary.rs`: `str::to_owned()` for field names, binding ids /
  versions and dictionary terms (charged first, exact capacity, infallible).

These do not affect the correctness of C15A-02/C15A-03; they will be reported for
an independent fixup decision (acceptance stays blocked until reviewed).

---

# Results (S1–S5) — executed

| Item | Value |
|---|---|
| Baseline SHA (S0) | `5695709c1cb2331389afe4380b86831c4dbac91f` |
| Fix commit | `6cdbf93fc464c9ea8961e456aefebd7d124004d8` |
| Evidence commit | this document-only commit (HEAD) |
| Diff (fix commit) | `segment/json_paths.rs` +508/-?, `segment/remap.rs` +243, `segment/reader.rs` 10 lines, `index/snapshot.rs` +67 (test-only) |
| Tree | clean |

## 1. Source changes

### C15A-02 — `crates/quervant-core/src/segment/json_paths.rs`

* Added private `push_doc_offset(&mut Vec<JsonDocOffset>, JsonDocOffset, &mut Option<&mut MetadataMeter>, &SegmentLimits)`:
  * `len < capacity` → insert with no charge (no growth);
  * `len == capacity` → `requested = len.checked_add(1)`, `delta = requested - old_capacity`,
    `meter.charge_vec::<JsonDocOffset>(delta)` **before** `try_reserve_exact(delta)`,
    typed `LimitExceeded` on fallible-reserve failure, then
    `charge_retained_excess(requested, actual_capacity, meter)` **before** the insert.
* Added private `charge_retained_excess(requested_capacity, actual_capacity, meter)` — the only
  permitted post-allocation top-up; returns `LimitExceeded` when the excess cannot be charged.
* Both emission sites (mid-run boundary and end-of-field) call the helper. `budget.reserve_bytes(doc_offset_charge())`
  remains exactly once per emitted record.
* Added `growth_probe` recorder: `#[cfg(test)]` implementation with a thread-local event list
  (`old_capacity`, `requested_capacity`, `charged_before`, `actual_capacity`, `charged_extra`,
  `reconciled`) plus a `#[cfg(not(test))]` no-op module so call sites carry no `cfg` attributes.
  No public or release-visible interface changed.

### C15A-03 — `crates/quervant-core/src/segment/remap.rs`, `segment/reader.rs`

* Added private `DocRemap::identity_fallible(doc_count) -> SegmentResult<DocRemap>`:
  `Vec::new()` + `try_reserve_exact(doc_count)` for both arrays before any fill (the first array is
  dropped if the second reservation fails), then `u64::try_from(i)` pushes. No `collect`, no
  `vec![]`/`with_capacity`, no implicit growth; `doc_count == 0` reserves nothing.
* Added `pub(crate) DocRemap::identity_metered(doc_count, meter)` which charges the two arrays
  **once**, calls `identity_fallible`, then charges any allocator capacity excess
  (`capacity - doc_count`) before returning (AD-FX-04).
* `DocRemap::decode_metered` state `0` now delegates to `identity_metered` (caller-side charges
  removed; `DecodeBudget` reservations unchanged).
* `reader.rs::decode_metadata` absent-`SortedRemap` branch replaced manual charges +
  `DocRemap::identity` with `DocRemap::identity_metered(...)`; the C15A-01 unconditional allowance
  is untouched.
* Public `DocRemap::identity(usize) -> Self` is unchanged (X20).

## 2. Unchanged / preserved

`segment/metadata.rs` has **no** production edit (CAS budget, RAII release, accounting model
identical). `index/snapshot.rs` production paths (state machine, admission, fallback, locks) are
untouched; only test code was added. `decode_allowance`'s C15A-01 term, wire format, codecs,
`SegmentLimits`/`IndexLimits`, public APIs, PIT/mask semantics and telemetry are unchanged.

## 3. Independent pre-fix counterexamples (X21/X22)

**C15A-02** — with only the two emission sites reverted to the pre-fix
`meter.charge_vec::<JsonDocOffset>(1)` + `doc_offsets.push(...)` (helper retained so the tests
compile), `/tmp/prefix_c15a02.txt`:

```
test ... c15a02_t02_each_offset_growth_is_pre_charged ... FAILED
test ... c15a02_t03_multi_field_runs_and_budget_boundary ... FAILED
assertion `left == right` failed: retained offset capacity must equal the number of emitted offsets
  left: 16      <- pre-fix amortized push
  right: 12     <- offsets actually emitted/charged
  left: 8       <- pre-fix capacity for the 5-offset fixture
  right: 5
test result: FAILED. 3 passed; 2 failed
```

Post-fix the same command reports `5 passed`. `c15a02_t04` exercises the new excess-charging seam
directly with a real over-reserved vector; it is a contract witness for AD-FX-02 rather than a
pre-fix discriminator (labelled as such).

**C15A-03** — the pre-fix metered paths used the infallible constructor. Witness
`c15a03_t07b_infallible_constructor_would_panic` records the observable difference:

```
DocRemap::identity(usize::MAX)            -> panic (capacity overflow), no typed error
DocRemap::identity_fallible(usize::MAX)   -> Err(SegmentError::LimitExceeded { requested: u64::MAX, .. })
```

The pre-fix defect cannot be reproduced as an assertion failure without aborting the test process
(`collect()`/`with_capacity` on `usize::MAX` panic instead of returning a value), which is exactly
the defect; the witness therefore asserts the infallible constructor's unsafe behaviour and the
fallible constructor's typed behaviour side by side. Recorded under X22 with the reason above.

## 4. Witness results (executed)

| ID | Test | Result |
|---|---|---|
| FX-T01 | `c15a02_t01_zero_offsets_charge_nothing` | PASS — zero fields and zero-occurrence field: `len == 0`, `capacity == 0` |
| FX-T02 | `c15a02_t02_each_offset_growth_is_pre_charged` | PASS — 12 offsets, `capacity == len == 12`, 12 growth events each `old_capacity=k`, `requested=k+1`, `charged_before=1`, `actual==requested`, `charged_extra=0`, reconciled; metered exact allowance admits, one element less rejects with `LimitExceeded` and refunds the allowance (`budget.used() == 0`) |
| FX-T03 | `c15a02_t03_multi_field_runs_and_budget_boundary` | PASS — 2 JSON fields / 3 docs / 5 runs exactly match the independent constructed-run oracle `[(0,0,2),(0,1,3),(0,2,1),(1,0,1),(1,1,2)]`; `capacity == 5`; `DecodeBudget` boundary exactly `5 × doc_offset_charge()` (48 bytes each) succeeds and one byte less fails; cursor occurrence counts match the oracle |
| FX-T04 | `c15a02_t04_allocator_excess_is_reconciled_before_append` | PASS — real over-reserved vector: excess charged before append; insufficient allowance returns `LimitExceeded` with nothing appended and the allowance refunded; zero excess charges nothing |
| FX-T05 | `c15a02_t05_malformed_section_after_append_fails_closed` | PASS — truncation after the first appended offset returns `Truncated`/`Corrupt` |
| FX-T06 | `c15a03_t06_identity_fallible_matches_public_identity` | PASS — `0/1/5/1024`: equal to `DocRemap::identity`, both directions equal the independent `0..n` oracle, `capacity == doc_count` on both arrays, out-of-range ids still rejected |
| FX-T07 | `c15a03_t07_identity_fallible_overflow_is_typed` | PASS — `usize::MAX` returns typed `LimitExceeded`; metered rejection refunds (`budget.used() == 0`); allowance of exactly `2·5·8` admits and `finalize` charges exactly that |
| FX-T07b | `c15a03_t07b_infallible_constructor_would_panic` | PASS — documents the pre-fix failure mode |
| FX-T08 | `c15a03_t08_state_zero_and_absent_section_agree` | PASS — `decode(&[0])`, `decode_metered(&[0])` and `identity_fallible` agree for `0/1/7`; non-zero state still decodes a real permutation |
| FX-T08b | `c15a03_t08b_state_zero_and_absent_section_agree_through_snapshot` | PASS — reader level: explicit state-0 container and absent-section container both reach READY, verify once, and expose identical identity remaps matching the uncached readers |
| FX-T09 | inherited `c15a01_t06_absent_remap_falls_back_one_under_allowance` (FX-I06) | PASS (re-executed in this run) — allowance−1 → verified uncached reader, slot not READY, `metadata_used == 0`, admission released |
| FX-T10 | inherited `g3_02_envelope_corruption_fails_closed`, `g3_04b_malformed_json_paths_fail_closed`, `c15a01_t09_absent_remap_corruption_still_fails_closed` | PASS (re-executed) — typed digest/corruption errors, no READY, no charge |
| FX-T11 | inherited `g2_11_cache_hits_keep_full_admission_charge`, `c15a01_t05_absent_remap_segment_is_cached_and_reused` | PASS (re-executed) — one verification, `Arc::ptr_eq`, `2*len` admission, release to 0 |
| FX-T12 | inherited `g1_05_zero_cap_and_cached_readers_are_equivalent` (+ JSON-path parity) and `pr15c_a_t01…t05` | PASS (re-executed) |
| FX-T13 | `pr15c_a_segment_state` (5) and `pr15b_diagnostics` (16 frozen oracles) | PASS — no fixture/baseline file changed (`git diff --stat` shows only the four source files) |
| FX-T14 | full workspace + MSRV + coverage | PASS — see §6 |
| FX-T15 | real RustFS | **BLOCKED — ENVIRONMENT** (`QUERVANT_RUSTFS_ENDPOINT … NotPresent`, no Docker daemon) |

## 5. S4 — retained-allocation audit (cached construction path)

Legend — **Charge**: exact precharge before allocation. **Alloc**: allocation API.
**Reconcile**: post-allocation capacity reconciliation. **Verdict**: `PASS` (VSR-G2-04 satisfied) or
`FINDING` (capacity accounting sound but the allocation is infallible; out of scope here).

| Owner / site | Count bound | Charge | Alloc | Reconcile | Verdict |
|---|---|---|---|---|---|
| `format.rs::parse_container` sections (`878`) / features (`972`) | ≤ `max_sections`, ≤ `max_features` per list | `parser_allowance()` reserved before parsing | `Vec::with_capacity` | count-driven exact | **FINDING F1** (infallible `with_capacity`; count-bounded, allowance-covered) |
| `reader.rs::decode_metadata` `sections`/`required`/`optional` copies (`721-723`) | same counts as the view | `meter.charge_vec` at `712-716` | `to_vec()` | n/a (exact count) | **FINDING F2** (infallible `to_vec`) |
| `reader.rs::decode_geo_bounds` (`942`) | encoded count (55 B/entry) | `meter.charge_vec::<GeoBounds>(count)` | `Vec::with_capacity` | exact | **FINDING F3** (infallible `with_capacity`) |
| `reader.rs::build_cached` state `Arc` (`183`) | one | `parser_allowance` (`size_of::<VerifiedSegmentState>()`) | `Arc::new` | n/a | **FINDING F4** (infallible `Arc::new` for the accounted payload) |
| `reader.rs::decode_metadata` JSON directory `Arc` (`821`) | one | `meter.charge_arc::<JsonPathDirectory>()` | `Arc::new` | n/a | **FINDING F4** (same class) |
| `schema.rs` fields vec (`355`) | `field_count` | `meter.charge_vec::<CodecField>` | `try_reserve_exact` | exact | **PASS** |
| `schema.rs` names (`376`) / binding id+version (`57-58`) | section bytes | `meter.charge_str(len)` before each | `str::to_owned` | exact (capacity == len) | **FINDING F5** (infallible `to_owned`) |
| `remap.rs::identity_metered` → `identity_fallible` (`41,49`) | `doc_count` × 2 | `identity_metered` charges twice before | `try_reserve_exact` | excess charged (`identity_metered`) | **PASS** (C15A-03) |
| `remap.rs::decode_metered` state 1 (`257,261`) | `doc_count` × 2 | `meter.charge_vec` before | `Vec::with_capacity` | exact | **FINDING F6** (explicit-remap branch still infallible) |
| `dictionary.rs` outer (`132`) / entries (`181`) | field / term counts | `meter.charge_vec` before | `try_reserve_exact` | exact | **PASS** |
| `dictionary.rs` term strings (`221`) | section bytes | `meter.charge_str(len)` before | `str::to_owned` | exact | **FINDING F5** (same class) |
| `norms.rs` fields (`182`) / lengths (`232`) | field count / `doc_count` | `meter.charge_vec` before | `try_reserve_exact` | exact | **PASS** |
| `norms.rs::scoring_field_ids` (`295`) | ≤ field count | none (temporary) | `collect` | n/a | **PASS** — decoder scratch, not retained in the state |
| `json_paths.rs::push_doc_offset` (new) | one slot per growth | `charge_vec(delta)` before, `charge_retained_excess` after | `try_reserve_exact` | allocator excess charged before append | **PASS** (C15A-02) |
| `json_paths.rs` path/previous-path scratch | ≤ depth limit | `DecodeBudget` (temporary) | `Vec` growth | n/a | **PASS** — temporary, dropped after decode |
| `spatial.rs` fields (`192`) / nodes (`245`) | field / point counts | `meter.charge_vec` before | `try_reserve_exact` | exact | **PASS** |
| `spatial.rs` `recomputed`/`visited`/`stack`/`seen` | node count | none (temporary) | `vec!`/`collect`/`BTreeSet` | n/a | **PASS** — decoder scratch, subject to existing limits |
| `metadata.rs` | — | — | no allocations | — | **PASS** |

### Findings for an independent fixup (X31 scoped HARD STOP for PR acceptance)

All findings are **capacity-accounting-correct but infallible**: the retained capacity is bounded and
charged before allocation, and measured capacity is reconciled, but an allocation failure aborts the
process instead of returning the typed `LimitExceeded` that the snapshot routes to the verified
uncached fallback. They are **not** patched here (plan AD-FX-06: "do not patch unrelated decoders in
this PR"), and they do not affect C15A-02/C15A-03:

| ID | Site | Proposed next fixup |
|---|---|---|
| **F1** | `format.rs:878,972` parser `Vec::with_capacity` | Migrate the parser's retained vectors to `try_reserve_exact` under the existing parser allowance |
| **F2** | `reader.rs:721-723` `to_vec()` copies | Replace with precharged `try_reserve_exact` + `extend_from_slice` |
| **F3** | `reader.rs:942` geo-bounds `with_capacity` | `Vec::new()` + `try_reserve_exact(count)` |
| **F4** | `reader.rs:183,821` accounted `Arc::new` payloads | Precharge (already) plus a fallible allocation strategy (e.g. `Arc::try_new`) with typed failure |
| **F5** | `schema.rs:376,57,58`, `dictionary.rs:221` `to_owned()` strings | Precharge (already) plus `String::try_reserve_exact` + `push_str` |
| **F6** | `remap.rs:257,261` explicit-remap `with_capacity` | Mirror `identity_fallible` with a shared `reserve_pair(doc_count)` helper |

**Consequence:** PR 15C-A acceptance remains blocked pending (a) review of these findings and a
follow-up fixup decision, and (b) the real RustFS / exact-head CI gates. C15A-02 and C15A-03
themselves are complete and independently witnessed.

## 6. Gate evidence (fix commit `6cdbf93`, clean tree)

| Command | Exit | Result |
|---|---|---|
| `cargo fmt --all -- --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo test -p quervant-core --lib` | 0 | PASS — **830 passed**, 1 ignored (was 819) |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | PASS — 5 passed |
| `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | PASS — 16 passed (frozen oracles) |
| `cargo test --workspace --all-features` | 0 | PASS — 114 targets, **2163 tests**, 0 failed (was 2152) |
| `cargo +1.85.0 test --workspace --all-features` | 0 | PASS — 2163 tests, 0 failed |
| `cargo test -p quervant-core --release --lib` | 0 | PASS — 830 passed |
| `cargo doc --workspace --no-deps` | 0 | PASS — no warnings |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | PASS — **91.73% lines** / 92.24% regions / 87.79% functions (`segment/json_paths.rs` 90.50%, `segment/remap.rs` 92.19%, `segment/reader.rs` 85.79%) |
| `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored` | 1 | **BLOCKED — ENVIRONMENT** (no RustFS endpoint/credentials, no Docker daemon) |

Logs: `/tmp/f2_{fmt,clippy,check185,clippy185,lib,pr15c,pr15b,ws,ws185,release,doc,cov}.log`,
pre-fix JSON experiment `/tmp/prefix_c15a02.txt`.

Failure classification: no mandatory gate failed. The only non-passing command is the pre-existing
external RustFS gate (environment, not code). No retries were used to mask failures; no suppression
or limit change was introduced.

## 7. Decision-matrix rows exercised

`X01` (exact base SHA, clean tree), `X04` (line numbers tracked by symbol), `X05`/`X06` (reused the
existing JSON-path encoders/`ContainerBuilder` helpers; no new harness), `X07` (`len < cap` append
without growth charge), `X08` (`len == cap` charge delta → `try_reserve_exact` → reconcile →
append), `X09`/`X10` (typed `LimitExceeded` on checked-math and reserve failure), `X11` (allocator
excess charged before append; rejection discards), `X13` (decoder corruption preserved), `X14`
(zero-offset directory: no allocation, no charge), `X15` (end-of-field emission uses the same
helper), `X16`/`X17`/`X18` (identity remap `0`/positive/typed allocation failure), `X19` (remap
capacity excess charge), `X20` (public `identity` untouched), `X21` (witnesses strengthened until
they discriminate), `X22` (C15A-03 pre-fix counterexample is a panic, recorded with the reason),
`X23` (`#[cfg(test)]` growth probe only), `X24` (`DecodeBudget` unchanged, one reserve per record),
`X25` (formatting confined to the edited files), `X26` (test corrections stayed inside the plan),
`X29`/`X30` (RustFS and CI recorded as blocked/deferred, not claimed), `X31` (audit findings F1–F6
recorded, unrelated production fixes stopped), `X32` (scratch allocations classified separately),
`X37` (`docs/TESTING.md` untouched), `X38`/`X39` (local gates green; exact-head re-run required
after the evidence commit), `X34` (inherited witnesses re-executed rather than duplicated).

No `X99` condition arose.

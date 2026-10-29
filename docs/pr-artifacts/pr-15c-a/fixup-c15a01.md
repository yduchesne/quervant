# C15A-01 fixup — implicit identity remap in the cached-state allowance

**Finding:** C15A-01 (independent source review of PR 15C-A).
**Status:** repaired on `dev/pr15c-a-immutable-segment`; local gates green; real
RustFS gate BLOCKED — ENVIRONMENT; PR acceptance still requires independent review
plus exact-head CI/RustFS.

## 1. Defect

| Item | Value |
|---|---|
| Failing function | `decode_allowance(&ContainerView) -> SegmentResult<u64>` in `crates/quervant-core/src/segment/reader.rs` |
| Original defect site | lines 581–591 at `748d85fab90e9e09c81522a8d936cf45d185579c`: the `2 * doc_count * size_of::<u64>()` term was wrapped in `if view.body(SectionKind::SortedRemap).is_some()` |
| Original (reviewed) commit | `748d85fab90e9e09c81522a8d936cf45d185579c` |
| Fix commit | `aca8ed17ea8fef6a65aa5ceabc978ceb305148b2` |
| Related, unchanged code | `decode_metadata()` retains two `Vec<u64>` in **both** branches: `DocRemap::decode_metered(...)` for an explicit section and `DocRemap::identity(doc_count)` otherwise, charging `meter.charge_vec::<u64>(doc_count)` twice |

Both branches retain a `DocRemap` with two `doc_count`-long `u64` vectors; the
section decides only where the values come from. The candidate allowance therefore
under-reserved `2 * doc_count * 8` bytes for every segment without a `SortedRemap`
section, breaking the VSR-G2-04/VSR-G2-06 invariant that the pre-reserved
allowance covers every retained allocation. Observed effect: a lost optimization
(the candidate is discarded and the verified uncached path is used whenever the
measured charge exceeds the under-reserved allowance), never incorrect results —
but the accounting invariant itself was unsound.

## 2. Authorized correction (production diff)

```diff
-    if view.body(SectionKind::SortedRemap).is_some() {
-        let doubled = view
-            .doc_count()
-            .checked_mul(2)
-            .ok_or(SegmentError::LimitExceeded {
-                limit: u64::MAX,
-                requested: u64::MAX,
-            })?;
-        total = accumulate(total, element_bytes::<u64>(doubled)?)?;
-    }
+    // Both explicit and implicit identity remaps retain two u64 vectors: an
+    // absent `SortedRemap` section is not a zero-cost identity representation,
+    // so this allowance is unconditional.
+    let doubled = view
+        .doc_count()
+        .checked_mul(2)
+        .ok_or(SegmentError::LimitExceeded {
+            limit: u64::MAX,
+            requested: u64::MAX,
+        })?;
+    total = accumulate(total, element_bytes::<u64>(doubled)?)?;
```

`git diff 748d85f..aca8ed1 --stat` → `segment/reader.rs` 21 lines changed
(11 insertions / 10 deletions: guard removal + comment); `index/snapshot.rs` 290
insertions of test-only code. No other production file changed:
`segment/remap.rs`, `segment/metadata.rs`, `index/snapshot.rs` production paths,
`SegmentLimits`, `IndexLimits`, format/wire bytes, admission/fallback logic and
the metering core are untouched (X32 allowlist respected).

Mathematical justification: retained payload
`= 2 * doc_count * size_of::<u64>()` (`= 16 * doc_count` bytes) regardless of
`SortedRemap` presence; at `doc_count = 0` the term is legitimately `0`, and the
shared state still carries its other charges (state `Arc` payload, schema, parser
vectors).

## 3. Fixtures and their proven section presence

Absence/presence is always proved from the parsed container directory
(`parse_container(...).sections()`), never from a fixture name.

| Fixture | Construction | `SortedRemap` | `doc_count` |
|---|---|---|---|
| Controlled implicit | `ContainerBuilder::new(ContainerKind::Segment, N)` + `Schema` section only (`c15a01_minimal_segment(N, None)`) | **absent** (asserted) | 0, 1, 3, 4, 5 |
| Controlled explicit | same + `FEATURE_REMAP` required + `Section(SortedRemap, DocRemap::from_order([..]))`, order asserted non-identity | **present** (asserted) | 3, 4 |
| Production implicit | `fixture_segment()` (`SegmentBuilder`, `Layout::Insertion` ⇒ identity remap ⇒ builder emits no `SortedRemap`), text/keyword/JSON/geo/timestamp/columnar fields, 3 docs | **absent** (asserted) | 3 |

## 4. Independent oracle

The test oracle never calls `decode_allowance`. For the controlled fixtures the
complete allowance is recomputed in the test with checked arithmetic from the
documented formula:

```
parser = max_sections * size_of::<SectionEntry>()
       + 2 * max_features * size_of::<(u16,u16)>()
       + size_of::<VerifiedSegmentState>()
schema = (schema_section_len / 13) * size_of::<CodecField>() + schema_section_len
remap  = doc_count * 2 * size_of::<u64>()
```

with all other sections absent, so `candidate_allowance_for_test` is compared for
**exact equality** (not `>= 0`), which is why the omission cannot hide behind the
conservative slack of other terms.

## 5. Witness matrix

| ID | Test | Executed | Result |
|---|---|---|---|
| FX-I01 / FX-T01 | `c15a01_t01_implicit_identity_remap_allowance_is_exact` | yes | PASS — absent section proved; allowance == oracle incl. `2·N·8` (`N=3` → 48 bytes) |
| FX-T02 | `c15a01_t02_explicit_sorted_remap_allowance_is_exact` | yes | PASS — present section proved; allowance == same oracle |
| FX-T03 | `c15a01_t03_remap_allowance_scales_with_doc_count` | yes | PASS — `N ∈ {0,1,5}` each equal to the oracle; `allowance(5) − allowance(1) == 2·4·8 == 64` exactly (slop-free doc-count differential) |
| FX-I02 / FX-T04 (regression killer) | `c15a01_t04_absent_and_present_remap_allowances_match` | yes | PASS — structurally identical implicit and explicit fixtures have **equal** allowances |
| FX-I03 / FX-I04 / FX-T05 | `c15a01_t05_absent_remap_segment_is_cached_and_reused` | yes | PASS — see §6 |
| FX-I06 / FX-T06 | `c15a01_t06_absent_remap_falls_back_one_under_allowance` | yes | PASS — verified fallback, nothing published, no charge |
| FX-T07 | distinct snapshots never share state | inherited: `g3_06_same_ids_different_bytes_are_never_trusted` (X13) | PASS (existing) |
| FX-I05 / FX-T08 | active-reader admission/release unchanged | inherited: `snapshot::tests::reader_budget_exact_and_one_over`, `reader_budget_overflow_fails_closed`, `decoder_failure_releases_reservation`, `reservation_is_released_on_guard_drop`, plus `g2_11_cache_hits_keep_full_admission_charge`, `g4_11_cache_hit_still_obeys_admission_budget` (X13) | PASS (existing) |
| FX-T09 | `c15a01_t09_absent_remap_corruption_still_fails_closed` | yes | PASS — `DigestMismatch`, no READY, no charge, no admission leak |
| FX-I08 / FX-T10 | `doc_count * 2` overflow remains checked | inherited: `segment::metadata::tests::{element_and_capacity_helpers_are_checked, charge_overflow_is_typed, budget_overflow_fails_closed}` (X13) + code review of `checked_mul` | PASS (existing) — a container with `u64::MAX/2` docs is unreachable: `SegmentLimits::max_docs = u32::MAX` and the encoded container must fit `accepted_segment_bytes`; no huge allocation was attempted |
| FX-I07 | no search-visible change | inherited: PR15A regression/oracle suites, PR15B 16 frozen oracles, `pr15c_a_segment_state` (5) | PASS |
| FX-I09 | no layout/API/storage/telemetry change | diff review (`git diff 748d85f..HEAD --stat`) | PASS — one production function, test-only additions |

## 6. Actual absent-remap admission numbers (production fixture)

`c15a01_t05_absent_remap_segment_is_cached_and_reused`, `fixture_segment()`,
`doc_count = 3`, `SegmentLimits::default()`, independent test reader limit `1 << 22`:

- `SortedRemap` section: **absent** (parsed directory).
- `candidate_allowance_for_test` = metadata cap used (`allowance`);
  `allowance > 2·3·8 = 48`.
- First acquisition: slot **READY**, `verification_count() == 1`,
  `0 < metadata_used() == charged <= allowance`, `doc_count == 3`,
  `reader_copy_used() == encoded_len`.
- Second acquisition while the first guard is held: `Arc::ptr_eq(shared_state)` is
  true, `verification_count()` still `1`, `metadata_used()` still `charged`,
  `reader_copy_used() == 2 * encoded_len`, and an independent
  `SegmentReader::open(same bytes)` reports the same doc keys and schema.
- Both guards dropped: `reader_copy_used() == 0`; a third read stays READY with
  one verification and unchanged charge.

`c15a01_t06…`: cap = `allowance - 1` on the same bytes → `slot READY == false`,
`verification_count() == 0`, `metadata_used() == 0`, reader still succeeds with
the same `doc_count`, and `reader_copy_used()` returns to `0` after drop.

## 7. Pre-fix counterexample (regression-killer evidence)

The three oracle/differential witnesses were executed against the **pre-fix**
condition (`if SortedRemap.is_some()`) by temporarily restoring it locally, then
the fix was restored and the suite re-run:

```
pre-fix  : c15a01_t01 FAILED, c15a01_t03 FAILED, c15a01_t04 FAILED
           c15a01_t02 ok, c15a01_t05 ok, c15a01_t06 ok, c15a01_t09 ok
           test result: FAILED. 4 passed; 3 failed
post-fix : test result: ok. 7 passed; 0 failed
```

This confirms (a) the tests are discriminating, and (b) — exactly as the plan
predicted — the admission/fallback witnesses alone would *not* have caught the
defect, because other conservative terms masked the missing 48 bytes.

## 8. Gate evidence (fixed head `aca8ed1`, tree clean)

| Command | Exit | Result |
|---|---|---|
| `cargo fmt --all -- --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo +1.85.0 check -p quervant-core` | 0 | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | 0 | PASS |
| `cargo test -p quervant-core --lib` | 0 | PASS — 819 passed, 1 ignored (was 812) |
| `cargo test -p quervant-core --test pr15c_a_segment_state` | 0 | PASS — 5 passed |
| `cargo test -p quervant-core --test pr15b_diagnostics` | 0 | PASS — 16 passed |
| `cargo test --workspace --all-features` | 0 | PASS — 114 targets, 2152 tests, 0 failed (was 2145) |
| `cargo +1.85.0 test --workspace --all-features` | 0 | PASS — 2152 tests, 0 failed |
| `cargo test -p quervant-core --release --lib` | 0 | PASS — 819 passed |
| `cargo doc --workspace --no-deps` | 0 | PASS — no warnings |
| `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | 0 | PASS — 91.69% lines / 92.18% regions / 87.85% functions (changed files: `index/snapshot.rs` 97.46%, `segment/reader.rs` 85.87%, `segment/metadata.rs` 98.60%) |
| `cargo test -p quervant-core --all-features --test pr13_remote -- --ignored` | 1 | **BLOCKED — ENVIRONMENT**: `QUERVANT_RUSTFS_ENDPOINT … NotPresent`; no Docker daemon on host |

Logs: `/tmp/fx_{fmt,clippy,check185,clippy185,lib,pr15c,pr15b,ws,ws185,release_lib,doc,cov}.log`.

Failure classification: none of the mandatory gates failed. The only non-passing
command is the pre-existing external RustFS gate (environment, not code): no
introduced regression, no flaky result, no fabricated pass.

## 9. Decision-matrix rows exercised

`X01` (branch at reviewed SHA, clean tree), `X03` (production implicit-remap
fixture proven absent), `X04` (controlled `ContainerBuilder` fixtures added for
exact arithmetic), `X05` (`doc_count = 0` accepted by the codec and tested),
`X06` (explicit-remap comparison witness added without modifying encoded
fixtures), `X07` (private `#[cfg(test)]` checked-arithmetic oracle helpers only),
`X09` (exact allowance used as the metadata cap), `X12` (isolated remap term /
identical-structure comparison, no whole-total comparison across unlike
fixtures), `X13` (FX-T07/T08/T10 inherited from named existing tests),
`X14` (fix compiles, targeted tests run), `X19` (`cargo fmt` touched only the new
test code; verified via `git diff --stat`), `X20` (no lint suppressions added),
`X21` (no exact-head CI run available in this environment — not claimed),
`X22` (RustFS BLOCKED — ENVIRONMENT, local work continued), `X29`
(`docs/TESTING.md` conflict markers remain untouched), `X30` (evidence appended
here and referenced from `decisions.md`/`acceptance.md`), `X31` (fixup committed on
the same branch, no merge).

Unresolved external gates: real RustFS conformance and exact-head GitHub checks.
PR acceptance, roadmap status and performance (PR 15C-B) remain outside this fixup.

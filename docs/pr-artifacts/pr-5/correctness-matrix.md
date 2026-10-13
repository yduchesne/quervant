# PR 5 correctness matrix and pre-implementation gate

> **Status: PLANNED — NOT EXECUTED.**
>
> This document is the pre-implementation correctness gate required by
> `TRAWLER_PR05_DETAILED_IMPLEMENTATION_PLAN.md` §3, §6 and §8. It maps every
> invariant to planned code paths, implementation steps and test IDs, and records
> at least two plausible counterexamples per high-risk invariant. **No test in
> this document has executed because no PR 5 code exists.** Per the plan,
> production codec code is blocked until the F01–F12 format decisions are
> human-approved (`docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md`).

## 1. Status legend

| Status | Meaning |
|---|---|
| PLANNED | check/test specified; implementation and execution pending format approval |
| EXECUTED | command run on the final SHA with recorded result |
| BLOCKED | cannot run (missing approval / infrastructure) |

All rows are currently **PLANNED / BLOCKED on F01–F12 approval**.

## 2. Test ID namespace (from the plan §6)

```text
P5-U01..U06  envelope: magic/version/endian/flags/duplicate/truncated
P5-U07..U12  offsets/counts/overlap/short read/limit/cancellation
P5-U13..U18  schema: duplicate ids/type/cardinality/fingerprint/unknown/columnar
P5-U19..U26  stored values: states/order/JSON/Unicode/floats/signedness/time
P5-U27..U34  IP/CIDR/geo/group-key collision/column state
P5-U35..U43  dictionary/postings: terms/sort/dupes/monotonicity/freq/positions/offsets
P5-U44..U50  remap: identity/reverse/sorted/duplicate/omitted/agreement
P5-U51..U58  bounds: timestamp extremes/negative/absent/sorted/dateline/unknown
P5-U59..U64  manifest: missing/duplicate refs/capabilities/digest/no CURRENT
P5-I01..I05  MemoryDirectory real write/sync/reopen/typed/postings/conflict/corruption
P5-I06..I11  FsDirectory fresh-instance reopen/tamper/truncate/partial/sync-fail/orphan
P5-G01..G05  checked-in goldens: empty/positional/typed-IP/time-geo/remapped
P5-P01..P04  property: seeded round-trip/reordered/oracle/permutation
P5-P05..P07  property: mutate boundaries/random truncation/hostile lengths
```

## 3. Invariant traceability

| INV | Property (abridged) | Affected planned paths | Impl step (plan §5) | Positive tests | Adversarial tests | Evidence |
|---|---|---|---|---|---|---|
| INV01 | Identical logical segment/config ⇒ byte-identical components regardless of insertion order/runtime | `segment::format`, `segment::schema`, `segment::dictionary`, `segment::remap` | A1–A4, B6, C10, D14 | P5-P01, P5-P02, P5-G01..G05 | P5-P02 (reordered inputs), P5-P04 | NOT EXECUTED (blocked) |
| INV02 | `decode(encode(x))` preserves logical identity, null/missing/empty, multivalue order, nested JSON, offsets, positions | `segment::stored`, `segment::column`, `segment::postings` | B7, B8, C11 | P5-U19..U26, P5-U27..U34 | P5-U19..U26 (Unicode/nested/extremes) | NOT EXECUTED (blocked) |
| INV03 | Every field/doc/term/posting/column/manifest reference resolves; no dangling/overlapping/out-of-range | all `segment::*` + `segment::manifest` | A4, B6, C11, D16 | P5-U07..U12, P5-U59..U64 | P5-U07..U12 (overlap/out-of-range), P5-P05 | NOT EXECUTED (blocked) |
| INV04 | Term ordering, posting monotonicity, frequency/position invariants, checked arithmetic | `segment::dictionary`, `segment::postings` | C10, C11 | P5-U35..U43 | P5-U35..U43 (nonmonotone/overflow/zero freq) | NOT EXECUTED (blocked) |
| INV05 | Malformed/truncated/hostile data fails typed; no panic; no read/alloc beyond caps | `segment::error`, `segment::format`, all decoders | A2–A4, F11 | P5-P05..P07 | P5-U07..U12, P5-P06, P5-P07 | NOT EXECUTED (blocked) |
| INV06 | Unsupported versions/unknown required features fail closed; analyzer fingerprint mismatch never silently passes | `segment::format`, `segment::schema`, `segment::manifest` | A4, B6, D16 | P5-U01..U06, P5-U13..U18 | P5-U04 (unknown required), P5-U16 (fingerprint mismatch) | NOT EXECUTED (blocked) |
| INV07 | Files immutable; failed writes never appear valid; PR 5 never publishes CURRENT | `segment::reader`, `segment::manifest`, `storage::Directory` use | E17–E19, D16 | P5-I01..I05, P5-I06..I11, P5-U59..U64 | P5-I06..I11 (partial/tamper/orphan), P5-U64 | NOT EXECUTED (blocked) |
| INV08 | Doc-ID remap bijective and applied consistently everywhere | `segment::remap` + all doc-addressed sections | D14 | P5-U44..U50, P5-P04 | P5-U44..U50 (duplicate/omitted/out-of-range) | NOT EXECUTED (blocked) |
| INV09 | Time/geo bounds conservative; missing/unknown disables pruning | `segment::bounds` | D15 | P5-U51..U58 | P5-U51..U58 (dateline/absent/unknown) | NOT EXECUTED (blocked) |
| INV10 | Typed columns preserve signedness, finite floats, timestamp precision, IP family, CIDR prefix, null states | `segment::column` | B8, B9 | P5-U27..U34 | P5-U27..U34 (family/prefix/collision), P5-P03 | NOT EXECUTED (blocked) |
| INV11 | Real Directory write/sync/reopen tested without claiming PR 6 commit/recovery | tests using `MemoryDirectory`, `FsDirectory` | E17–E19 | P5-I01..I05, P5-I06..I11 | P5-I06..I11 | NOT EXECUTED (blocked) |
| INV12 | All encoder/decoder entry points enforce memory/size/work/cancellation limits incl. error/no-op paths | `segment::error`, `segment::format`, every decoder entry point | A2, A3, F11 | P5-U07..U12, P5-U35..U43 | P5-U12 (cancellation), P5-P07 (hostile lengths) | NOT EXECUTED (blocked) |

## 4. Counterexamples to attempt before implementation

Each row names at least two concrete ways a plausible implementation could
violate the invariant, and the test that must falsify it once implemented.

| INV | Counterexample 1 | Counterexample 2 | Falsifying tests |
|---|---|---|---|
| INV01 | Iterating `BTreeMap` field order by insertion/registration order instead of UTF-8 name sort changes field ids and every reference. | Using a `HashMap` anywhere in encoding makes term/doc order nondeterministic across runs. | P5-P02, P5-P01 |
| INV01 | Floats encoded via `format!`/decimal lose bit determinism; `-0.0` vs `0.0` differ. | Varint emitted in non-minimal form for the same value changes bytes. | P5-G03, P5-P01 |
| INV02 | Collapsing `Empty` multi into `Absent` because both have zero values. | JSON object member order lost by storing into a `BTreeMap`/`HashMap`. | P5-U19, P5-U22 |
| INV02 | Offsets re-derived from normalized term length rather than original source. | `value_index` reset per doc instead of per source value. | P5-U23, P5-U24 |
| INV03 | Section `body_offset + body_length` overflowing `u64` wraps and passes `≤ file_len`. | Overlapping section ranges accepted because only end is checked. | P5-U08, P5-U09 |
| INV03 | Manifest references a segment digest but not its `object_key`, so a reader cannot fetch it. | Postings `postings_offset` points into the wrong section. | P5-U59, P5-U60 |
| INV04 | Posting doc ids equal (not strictly increasing) accepted because delta 0 is legal arithmetic. | `freq = 0` accepted, then zero occurrence records are silently produced. | P5-U38, P5-U39 |
| INV04 | Position delta `u32::MAX + 1` wraps to a small position. | First occurrence stored as a delta from an implicit 0 instead of absolute. | P5-U40, P5-U41 |
| INV05 | A `Vec::with_capacity(declared_count)` runs before validating `count` against remaining bytes → OOM. | `unreachable!()`/slice indexing on a truncated body panics instead of typed error. | P5-P05, P5-P06, P5-U07 |
| INV05 | A 2^60 length passes `checked_add` but is never compared to file length. | Decoder reads `offset` without checking it is inside the declared section. | P5-P07, P5-U07 |
| INV06 | Unknown `format_minor` treated as compatible by ignoring all differences. | Analyzer id/version match but fingerprint differs, resolved via `resolve_compatible` (version-only). | P5-U04, P5-U16 |
| INV06 | Unknown `section_kind` silently skipped even when listed as required. | Unknown `header_flags` bit ignored. | P5-U02, P5-U05 |
| INV07 | `Directory::create` on an existing key silently overwrites (it must conflict). | A failed `sync_all` leaves a file that a later reader treats as valid commit. | P5-I04, P5-I09 |
| INV07 | PR 5 code writes a `CURRENT`-like pointer after writing a component. | Manifest write failure leaves a partially written manifest readable. | P5-U64, P5-I11 |
| INV08 | Applying remap to postings but not stored/columns. | Reverse permutation accepted with a duplicated target id. | P5-U46, P5-U47 |
| INV08 | Identity remap applied when a sorted permutation was requested. | Remap computed but not applied to `LIVE_DOCS` bitmap. | P5-U44, P5-U50 |
| INV09 | Absent timestamp min/max encoded as `0`, causing time-range pruning to drop docs. | Geopoint envelope ignoring antimeridian sets `west <= east` and excludes crossing points. | P5-U52, P5-U56 |
| INV09 | Unknown geo bounds defaulted to the whole globe but the flag is misread as Known-empty. | Block bounds computed over physical instead of original order. | P5-U57, P5-U58 |
| INV10 | IPv4-mapped IPv6 normalized to IPv4 by default, merging distinct identities. | CIDR prefix stored without family; a v4 /24 and v6 /24 collide. | P5-U27, P5-U28 |
| INV10 | `-0.0` canonicalized to `0.0`, losing bit-exact GeoPoint/F64 value. | Negative timestamps `i64` decoded as `u64`. | P5-U31, P5-U33 |
| INV11 | Tests reopen with the *same* `FsDirectory` object, hiding a missing fresh-instance path. | A fake in-memory directory substituted for the real filesystem reopen. | P5-I06 |
| INV11 | Reopen test accepts a short `read_at` as EOF without checking `len`. | Corruption test only mutates the last byte, missing header/footer corruption. | P5-I07, P5-I08 |
| INV12 | Cancellation checked only at entry, never inside a large decode loop. | Error path allocates before checking the relevant cap (violates "error paths too"). | P5-U12, P5-P07 |
| INV12 | No-op/empty section skips cap validation entirely. | `usize` conversion truncates a `u64` length on 32-bit. | P5-P05, P5-U07 |

## 5. Independent oracle strategy

The plan requires an independent oracle, not encoder-intermediate-derived
expectations. For PR 5:

- **Hand-authored golden table**: a checked-in table of expected tuples
  `(document_key, field, term, position, position_increment, start_offset,
  end_offset, typed_value)` authored from the input fixture, independent of the
  encoder. Test P5-P03 compares decoded codec output against the table.
- **Second independent decoder path in tests**: the oracle and production
  decoder must be written separately; a test must not call production encoder
  internals to build expectations (the production encoder is not an oracle).
- **Property tests** use fixed seeds and bounded generators (P5-P01..P04) with
  reproducible shrink artifacts.
- **Differential Lucene/Tantivy comparison** is optional and only for *logical*
  semantics; binary formats are not interchangeable and are not an oracle for
  Trawler bytes.
- **Real-path topology**: `MemoryDirectory` (P5-I01..I05) and a **fresh
  `FsDirectory` instance** for filesystem reopen (P5-I06..I11); fault injection
  wraps real code at boundaries, never a fake codec.

## 6. Pre-implementation correctness gate checklist

Per plan §8. All items must be satisfied before writing production codec code:

- [ ] F01–F12 approved by a human and an approved commit SHA recorded.
- [ ] INV01–INV12 traceability above reviewed and accepted.
- [ ] At least two counterexamples per high-risk invariant documented (§4).
- [ ] Independent oracle feasible without duplicating production code (§5).
- [ ] Resource caps (F11) and cancellation checkpoints agreed.
- [ ] Real `MemoryDirectory`/`FsDirectory` topology and fault-injection approach
      agreed; no fake codec substituted.
- [ ] No STOP condition remains: no protected-contract change, no new
      unapproved dependency, no MSRV violation, no unsafe allocation.
- [ ] No PR 6/13/distributed/vector scope in the PR 5 change set.

**Gate status: OPEN — BLOCKED on F01–F12 human approval.**

## 7. Post-implementation evidence table (to be filled in Phase E)

| Gate | Command | Result |
|---|---|---|
| Format | `cargo +1.85.0 fmt --all -- --check` | _pending_ |
| Lint | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | _pending_ |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | _pending_ |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | _pending_ |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | _pending_ |
| Golden decode | checked-in fixture tests | _pending_ |
| Real reopen | Memory + fresh FsDirectory | _pending_ |
| Corruption | truncation/tamper/fault-injection | _pending_ |

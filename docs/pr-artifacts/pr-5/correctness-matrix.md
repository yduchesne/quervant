# PR 5 correctness matrix and pre-implementation gate

> **Status: PLANNED — NOT EXECUTED. Amendment 01 (R5-01–R5-08) applied.**
>
> This document is the pre-implementation correctness gate required by
> `TRAWLER_PR05_DETAILED_IMPLEMENTATION_PLAN.md` §3, §6 and §8, extended by the
> PR 5 Format Decision Amendment 01. It maps every invariant to planned code
> paths, implementation steps and test IDs, and records at least two plausible
> counterexamples per high-risk invariant. **No test in this document has
> executed because no PR 5 code exists.** Production codec code is blocked until
> the F01–F12 format decisions are human-approved
> (`docs/decisions/PR05_SEGMENT_FORMAT_DECISIONS.md`).

## 1. Status legend

| Status | Meaning |
|---|---|
| PLANNED | check/test specified; implementation and execution pending format approval |
| EXECUTED | command run on the final SHA with recorded result |
| BLOCKED | cannot run (missing approval / infrastructure) |

All rows are currently **PLANNED / BLOCKED on F01–F12 approval**.

## 2. Test ID namespace

Existing plan §6 IDs (unchanged):

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

Amendment 01 additions (planned only):

```text
P5-A01  advance() exact/in-between/EOF/idempotent vs sorted-doc oracle
P5-A02  bounded scan/read budget and cancellation during large advance
P5-A03  PR 4 repeated-position and multivalue gap/value-index compatibility
P5-A04  dictionary/postings doc_freq/offsets/lengths/frequency cross-validation
P5-A05  random-access first/last doc and block-boundary column reads
P5-A06  instrumented bytes read: doc N does not scan preceding blocks
P5-A07  malformed column offset table (descending/overflow/out-of-block)
P5-A08  absent/null/empty multi/single/multi round-trip and group-key distinction
P5-A09  full verification against trusted content descriptor rejects tampering
P5-A10  selective range access is not claimed authenticated without trusted proof/cache
P5-A11  fixed trailer deterministically locates footer despite magic bytes in payload
P5-A12  truncated/overflow/overlapping footer and section offsets fail closed
P5-A13  partial timestamp presence and positive-range pruning never false-negative
P5-A14  missing/null, NOT, OR predicates never incorrectly pruned by positive bounds
P5-A15  partial GeoPoint presence, antimeridian and multivalued geo envelopes
P5-A16  wire max vs operational 256 MiB target; larger compatible file accepted by policy
P5-A17  hostile count, 32-bit conversion and work/alloc budgets
P5-A18  manifest digest scope vs per-segment content digest independently checked
P5-A19  reserved generation/epoch fields cannot imply publication
P5-A20  end-to-end doc-ID remap across postings, columns, source and bounds
```

## 3. Invariant traceability

| INV | Property (abridged) | Affected planned paths | Impl step (plan §5) | Positive tests | Adversarial tests | Evidence |
|---|---|---|---|---|---|---|
| INV01 | Identical logical segment/config ⇒ byte-identical components regardless of insertion order/runtime | `segment::format`, `segment::schema`, `segment::dictionary`, `segment::remap` | A1–A4, B6, C10, D14 | P5-P01, P5-P02, P5-G01..G05 | P5-P02 (reordered), P5-P04 | NOT EXECUTED (blocked) |
| INV02 | `decode(encode(x))` preserves logical identity, null/missing/empty, multivalue order, nested JSON, offsets, positions | `segment::stored`, `segment::column`, `segment::postings` | B7, B8, C11 | P5-U19..U26, P5-U27..U34, P5-A08 | P5-U19..U26, P5-A03, P5-A20 | NOT EXECUTED (blocked) |
| INV03 | Every field/doc/term/posting/column/manifest reference resolves; no dangling/overlapping/out-of-range | all `segment::*` + `segment::manifest` | A4, B6, C11, D16 | P5-U07..U12, P5-U59..U64 | P5-U07..U12, P5-A04, P5-A05, P5-A07, P5-A11, P5-A12, P5-A18 | NOT EXECUTED (blocked) |
| INV04 | Term ordering, posting monotonicity, frequency/position invariants, checked arithmetic | `segment::dictionary`, `segment::postings` | C10, C11 | P5-U35..U43 | P5-U35..U43, P5-A01, P5-A03, P5-A04 | NOT EXECUTED (blocked) |
| INV05 | Malformed/truncated/hostile data fails typed; no panic; no read/alloc beyond caps | `segment::error`, `segment::format`, all decoders | A2–A4, F11 | P5-P05..P07 | P5-U07..U12, P5-P06, P5-P07, P5-A07, P5-A12, P5-A17 | NOT EXECUTED (blocked) |
| INV06 | Unsupported versions/unknown required features fail closed; analyzer fingerprint mismatch never silently passes | `segment::format`, `segment::schema`, `segment::manifest` | A4, B6, D16 | P5-U01..U06, P5-U13..U18 | P5-U04 (unknown required), P5-U16 (fingerprint mismatch) | NOT EXECUTED (blocked) |
| INV07 | Files immutable; failed writes never appear valid; PR 5 never publishes CURRENT | `segment::reader`, `segment::manifest`, `storage::Directory` use | E17–E19, D16 | P5-I01..I05, P5-I06..I11, P5-U59..U64 | P5-I06..I11, P5-U64, P5-A19 | NOT EXECUTED (blocked) |
| INV08 | Doc-ID remap bijective and applied consistently everywhere | `segment::remap` + all doc-addressed sections | D14 | P5-U44..U50, P5-P04 | P5-U44..U50, P5-A20 | NOT EXECUTED (blocked) |
| INV09 | Time/geo bounds conservative; missing/unknown disables pruning | `segment::bounds` | D15 | P5-U51..U58 | P5-U51..U58, P5-A13, P5-A14, P5-A15 | NOT EXECUTED (blocked) |
| INV10 | Typed columns preserve signedness, finite floats, timestamp precision, IP family, CIDR prefix, null states | `segment::column` | B8, B9 | P5-U27..U34 | P5-U27..U34, P5-P03, P5-A08, P5-A15 | NOT EXECUTED (blocked) |
| INV11 | Real Directory write/sync/reopen tested without claiming PR 6 commit/recovery | tests using `MemoryDirectory`, `FsDirectory` | E17–E19 | P5-I01..I05, P5-I06..I11 | P5-I06..I11 | NOT EXECUTED (blocked) |
| INV12 | All entry points enforce memory/size/work/cancellation limits incl. error/no-op paths | `segment::error`, `segment::format`, every decoder | A2, A3, F11 | P5-U07..U12, P5-U35..U43 | P5-U12, P5-P07, P5-A02, P5-A16, P5-A17 | NOT EXECUTED (blocked) |
| INV13 | Bounded selective access: column doc-N and postings `advance` never require an unbounded prefix scan; work is charged and bounded | `segment::column`, `segment::postings`, `segment::dictionary` | C11, B8, A3 | P5-A05, P5-A06, P5-A01 | P5-A02, P5-A06, P5-A07 | NOT EXECUTED (blocked) |
| INV14 | Integrity trust modes are not conflated: full verification uses an independently trusted `ContentDescriptor`; unverified selective ranges are never treated as content-authenticated | `segment::format`, `segment::manifest`, `storage` read path | A3, A4, D16 | P5-A09, P5-A10, P5-A18 | P5-A09, P5-A10, P5-A11 | NOT EXECUTED (blocked) |

## 4. Amendment 01 test-to-invariant mapping (planned)

| Test | INV(s) | Verification |
|---|---|---|
| P5-A01 | INV04, INV13 | `advance()` exact/in-between/EOF/idempotent/monotone vs independent sorted-doc oracle |
| P5-A02 | INV12, INV13 | Bounded read/batch budget and cancellation mid-scan |
| P5-A03 | INV02, INV04 | PR 4 repeated-position and multivalue gap/`value_index` compatibility |
| P5-A04 | INV03, INV04 | `doc_freq`/`doc_count`/`freq_total`/extent cross-validation |
| P5-A05 | INV03, INV13 | First/last/block-boundary typed column doc reads |
| P5-A06 | INV13 | Instrumented byte counts prove doc N does not scan preceding blocks |
| P5-A07 | INV03, INV05, INV12 | Descending/overflow/out-of-block column offsets rejected |
| P5-A08 | INV02, INV10 | Five-state round-trip and group-key missing/null distinction |
| P5-A09 | INV14 | Tampered segment fails trusted-`ContentDescriptor` full verification |
| P5-A10 | INV14 | Selective range not claimed authenticated without trusted proof/cache |
| P5-A11 | INV03, INV05, INV14 | Fixed trailer wins over magic bytes embedded in payload |
| P5-A12 | INV03, INV05 | Truncated/overflow/overlapping footer/section offsets fail closed |
| P5-A13 | INV09 | Partial timestamp presence; positive-range pruning never false-negative |
| P5-A14 | INV09 | Missing/null, NOT and OR predicates never incorrectly pruned |
| P5-A15 | INV09, INV10 | Partial/multivalued geo presence (antimeridian) envelopes conservative |
| P5-A16 | INV12 | Wire max vs operational target; larger compliant file accepted by policy |
| P5-A17 | INV05, INV12 | Hostile counts, `u64`→`usize` conversion, work/alloc budgets |
| P5-A18 | INV03, INV14 | Manifest digest scope vs per-segment content digest checked separately |
| P5-A19 | INV07 | Reserved lifecycle fields cannot imply publication |
| P5-A20 | INV08, INV02 | End-to-end remap across postings, columns, source and bounds |

## 5. Counterexamples to attempt before implementation

Each row names at least two concrete ways a plausible implementation could
violate the invariant; the listed test must falsify it once implemented.

| INV | Counterexample 1 | Counterexample 2 | Falsifying tests |
|---|---|---|---|
| INV01 | Field ids assigned by declaration order instead of UTF-8 name sort. | A `HashMap` in encoding makes term/doc order nondeterministic. | P5-P01, P5-P02 |
| INV01 | Floats encoded via decimal formatting; `-0.0` vs `0.0` differ. | Non-minimal varint encoding yields different bytes for one value. | P5-G03, P5-P01 |
| INV02 | `EMPTY_MULTI` collapsed into `ABSENT`. | JSON object member order lost via `BTreeMap`/`HashMap`. | P5-U19, P5-A08 |
| INV02 | Offsets re-derived from normalized term length. | `value_index` reset per doc instead of per source value. | P5-U23, P5-A03 |
| INV03 | `body_offset + body_length` overflows `u64` and passes `<= file_len`. | Overlapping sections accepted because only the end is checked. | P5-U08, P5-U09, P5-A12 |
| INV03 | Dictionary `postings_offset` points into the wrong section. | Column offset table ends before/after the value area. | P5-A04, P5-A07 |
| INV04 | Posting doc ids equal (delta 0) accepted. | `freq = 0` accepted and zero records emitted. | P5-U38, P5-U39 |
| INV04 | `position` delta `u64::MAX + 1` wraps. | First occurrence stored as a delta from implicit 0. | P5-U40, P5-A01 |
| INV05 | `Vec::with_capacity(declared_count)` before validating count vs remaining bytes. | Slice indexing on a truncated body panics instead of typed error. | P5-P05, P5-P06, P5-A17 |
| INV05 | A 2^60 length passes checked add but is never compared to file length. | Decoder reads `offset` without checking inside the declared section. | P5-P07, P5-A12 |
| INV06 | Unknown `format_minor` treated as compatible by ignoring differences. | Analyzer id/version match but fingerprint differs, resolved version-only. | P5-U04, P5-U16 |
| INV06 | Unknown `section_kind` skipped despite being required. | Unknown `header_flags`/`trailer_flags` bit ignored. | P5-U02, P5-U05 |
| INV07 | `create` silently overwrites an existing key. | Failed `sync_all` leaves a file a later reader treats as valid. | P5-I04, P5-I09 |
| INV07 | PR 5 writes a CURRENT-like pointer after a component. | Nonzero reserved lifecycle field treated as a generation. | P5-U64, P5-A19 |
| INV08 | Remap applied to postings but not stored/columns. | Reverse permutation accepted with a duplicate target id. | P5-U46, P5-U47, P5-A20 |
| INV08 | Identity remap applied when sorted permutation requested. | Remap applied but not to `LIVE_DOCS`. | P5-U44, P5-U50 |
| INV09 | Absent timestamp min/max encoded as 0, dropping docs in range pruning. | Antimeridian envelope stored as `west <= east`. | P5-U52, P5-A15 |
| INV09 | `SOME` presence treated as `ALL` so `IS NULL` is wrongly pruned. | Negated range pruned from present values though missing values match. | P5-A13, P5-A14 |
| INV10 | IPv4-mapped IPv6 normalized to IPv4 by default. | CIDR prefix stored without family, so v4 /24 and v6 /24 collide. | P5-U27, P5-U28 |
| INV10 | `-0.0` canonicalized to `0.0`. | Negative timestamp decoded as `u64`. | P5-U31, P5-A15 |
| INV11 | Reopen uses the same `FsDirectory` object, hiding fresh-instance reopen. | A fake in-memory directory substituted for filesystem reopen. | P5-I06 |
| INV11 | A short `read_at` accepted as EOF without checking `len`. | Corruption test only mutates the last byte. | P5-I07, P5-I08 |
| INV12 | Cancellation checked only at entry, never inside a large decode loop. | Error path allocates before checking a cap. | P5-U12, P5-A02 |
| INV12 | No-op/empty section skips cap validation. | `u64` length truncates on 32-bit `usize`. | P5-P05, P5-A17 |
| INV13 | Column doc N decoded by scanning docs `0..N` because state tags precede values. | `advance` materializes the whole term posting list to find `target`. | P5-A06, P5-A01 |
| INV13 | Block directory not used, so a "block" is only a logical group with no offsets. | Work counters not charged while scanning, hiding unbounded work. | P5-A06, P5-A02 |
| INV14 | Section digest compared to the same untrusted footer and called verified. | Selective range read treated as authenticated purely because it decoded. | P5-A09, P5-A10 |
| INV14 | Manifest repeats its own envelope digest in the payload and treats self-match as trust. | Content descriptor length ignored so a truncated file passes digest. | P5-A18, P5-A09 |
| INV14 | Tampered trailer offset points at a forged footer that is internally consistent. | Cached unverified file reused without full verification. | P5-A11, P5-A10 |

## 6. Cross-decision consistency audit

See `docs/pr-artifacts/pr-5/amendment-01-consistency-matrix.md` for the
end-to-end trace required by Amendment 01 §4. Each cross-cutting row carries two
concrete counterexamples and a disposition.

## 7. Independent oracle strategy

- **Hand-authored golden table**: checked-in tuples
  `(document_key, field, state, term, position, position_length, value_index,
  start_offset, end_offset, typed_value)` authored from the input fixture,
  independent of the encoder (P5-P03).
- **Second independent test decoder path**: the oracle must not call production
  encoder internals to build expectations.
- **Property tests** use fixed seeds and bounded generators (P5-P01..P04) with
  reproducible shrink artifacts.
- **Bounded-access instrumentation**: bytes read and decoded entries are counted
  to prove INV13, not inferred from timing.
- **Integrity tests** use a trusted expected `ContentDescriptor` and sabotage
  bytes to prove INV14; a self-consistent forgery must still fail when the
  trusted digest is enforced.
- **Real-path topology**: `MemoryDirectory` (P5-I01..I05) and a **fresh
  `FsDirectory`** for filesystem reopen (P5-I06..I11); fault injection wraps real
  code, never a fake codec.

## 8. Pre-implementation correctness gate checklist

- [ ] F01–F12 approved by a human and an approved commit SHA recorded.
- [ ] INV01–INV14 traceability reviewed and accepted.
- [ ] At least two counterexamples per high-risk invariant documented (§5).
- [ ] Independent oracle feasible without duplicating production code (§7).
- [ ] Resource caps (F11 classes) and cancellation checkpoints agreed.
- [ ] Real `MemoryDirectory`/`FsDirectory` topology and fault-injection approach agreed.
- [ ] No STOP condition remains: no protected-contract change, no unapproved
      dependency, no MSRV violation, no unsafe allocation.
- [ ] No PR 6/13/distributed/vector scope in the PR 5 change set.

**Gate status: OPEN — BLOCKED on F01–F12 human approval.**

## 9. Post-implementation evidence table (to be filled in Phase E)

| Gate | Command | Result |
|---|---|---|
| Format | `cargo +1.85.0 fmt --all -- --check` | _pending_ |
| Lint | `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` | _pending_ |
| Tests | `cargo +1.85.0 test --workspace --all-targets` | _pending_ |
| Coverage | `cargo +1.85.0 llvm-cov --workspace --all-targets --fail-under-lines 85` | _pending_ |
| Docs | `cargo +1.85.0 doc --workspace --no-deps` | _pending_ |
| Golden decode | checked-in fixture tests | _pending_ |
| Real reopen | Memory + fresh FsDirectory | _pending_ |
| Corruption | truncation/tamper/fault injection | _pending_ |
| Bounded access | instrumented bytes/entries (P5-A06) | _pending_ |
| Integrity trust | trusted-descriptor tamper (P5-A09) | _pending_ |

## Amendment 01 final clarification acceptance (pending implementation)

| Test ID | Required falsifiable case | Status |
|---|---|---|
| P5-A21 | Whole-file PR 3 `ContentDescriptor` digest covers trailer; F02 envelope digest excludes trailer; verify each against its own expected value and reject substitution; never compare the two directly. An untrusted `SegmentStore::describe` response is not an independent trust anchor. | PLANNED |
| P5-A22 | Segment has 10 docs but a term has postings for docs 7 and 9 only: `posting_doc_count = doc_freq = 2`, each posting doc ID `< segment_doc_count = 10`; reject doc ID 10, duplicate IDs, and posting count > segment count. | PLANNED |
| P5-A23 | Encode columns with persisted `block_docs = 3`, reopen with runtime default 1,024; random access to documents 0, 2, 3, and final doc must work without scanning preceding blocks. Reject zero block_docs, wrong block_count, wrong first_doc_id, malformed final-block size and overflow. | PLANNED |

These cases extend INV03, INV05, INV06, INV10, INV11, INV12 and the P5-A01–A20 suite. They are **not executed**; the format approval gate remains open.

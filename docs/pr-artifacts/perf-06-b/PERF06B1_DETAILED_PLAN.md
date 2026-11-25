# PERF-06-B1 — Persistent keyword ordinals and a snapshot-wide numeric value space

**Plan revision:** 1 · **Authoring date:** 2026-11-24  
**Repository:** https://github.com/yduchesne/quervant  
**Frozen source:** 480a77e78c6897e05cb7ceb76b01434974b82ec6 (merged PERF-06-A6 / PR #125)  
**Proposed branch:** dev/perf06-b1  
**Plan copy in the implementation PR:** docs/pr-artifacts/perf-06-b/PERF06B1_DETAILED_PLAN.md  
**Execution report:** docs/pr-artifacts/perf-06-b/PERF06B1_EXECUTION_REPORT.md

## Navigation

- §§1–6: authority, scope, invariants and sequence.
- §7: persistent local format, encoding and all reader consumers.
- §8: snapshot-wide maps, public APIs, state machine, memory and G tests.
- §9: exact errors, wire literal, allocation rules and cancellation details.
- §§10–13: independent corpus, historical fixture, unit/integration and real RustFS acceptance.
- §§14–20: execution order, allowlist, decisions, QA, gates, report and review.
- Appendix S: verified source objects; Appendix L: complete frozen fixture producer.

## 1. Execution contract

This document is the implementation design. The coding agent implements it; the agent does not choose a different representation, global-ID lifetime, caching policy, compatibility policy, benchmark protocol, or query algorithm.

**Dominant invariant:** for each eligible keyword field, immutable segment data provides numeric local values, and an admitted reader-snapshot mapping translates those values into one exact, order-preserving numeric space across all that snapshot's segments. The same UTF-8 value in that field maps to the same shared ordinal. Existing logical values, queries, immutable files, reader admission, and PIT semantics remain correct.

The user approved the design of persistent segment dictionaries plus a shared ordinal view, while keeping B2 responsible for collector integration. “Global” in this plan means **one field in one exact ReaderSnapshot**, including volatile refresh identity. It does not mean a permanent interning service, cross-index IDs, or a distributed dictionary.

**Continuous execution authorization:** after the user hands this plan to the coding agent for execution, execute all prescribed work continuously. Successful preflight, completed phases, and AUTO-RESOLVE decisions do not require renewed permission. Classify obstacles with the decision matrix. Stop the affected work for a HARD STOP or a genuinely missing prerequisite; continue independently safe work only where this plan explicitly permits it. An unlisted condition is a HARD STOP for the affected work. Do not improvise.

### 1.1 Authorized work and boundaries

Authorized on execution: create the isolated implementation branch, implement the prescribed source delta, write and run the prescribed tests, perform final mandatory QA, record evidence, and prepare a draft PR using the repository's normal workflow. Commit and ordinary push are part of delivery; do not merge, force-push, rewrite existing evidence, or modify unrelated branches.

B1 does **not** authorize a performance acquisition, profiling, a cross-engine run, benchmark framework changes, threshold changes, B2 collector work, B3 identity work, or B4 qualification. Host-load observations are advisory and non-blocking. No host-idleness gate is needed to run deterministic correctness tests. A6's unfavorable numerical evidence remains unchanged.

Treat merged main as a healthy starting baseline: no full healthy-baseline suite or baseline coverage run. This removes redundant preflight work. B1 changes executable codec and cache code, so its new tests and the repository's final local and CI requirements still apply. The earlier A6 no-suite exception was explicitly task-scoped to that qualification. This plan consolidates verification after the final source change and forbids repetitive QA after report-only changes.

### 1.2 Completion vocabulary

- **PERF06_B1_IMPLEMENTATION_IN_PROGRESS:** prescribed source work is incomplete.
- **PERF06_B1_IMPLEMENTED_VERIFICATION_BLOCKED:** implementation exists but a mandatory gate is missing or failed.
- **PERF06_B1_READY_FOR_INDEPENDENT_REVIEW:** implementation, correctness, local QA and mandatory CI evidence all pass on the declared source; maintainer review remains.
- **PERF06_B1_HARD_STOP_DESIGN_AMENDMENT_REQUIRED:** an unlisted or prohibited architectural choice is required.

No self-issued ACCEPTED, MERGED, performance-win, or completed-B-series status. No “all tests pass” unless the exact required commands actually ran successfully. Pending CI is pending, not failed and not passed.

## 2. Source and authority

The plan was authored from the frozen main source, not from previous execution summaries alone. The guide, AGENTS.md, current format/column readers and producers, snapshot cache/budgets, tests, CI, roadmap, and relevant rejected experiments were inspected. No production change, Rust suite, benchmark, or CI run was executed while authoring this document.

### 2.1 Existing facts to preserve

| Source fact | Consequence for B1 |
|---|---|
| CodecSchema::from_contract assigns dense u32 IDs in UTF-8 field-name order; compatible index schemas agree across segments. | Reuse those field IDs. Add no global field registry and do not renumber fields. |
| COLUMNS v1 stores variable-length keyword payloads with per-block u64 document offsets; ColumnReader owns or borrows one parsed geometry table. | Add a versioned ordinal layout in the same section and retain the existing shared-reader path. |
| SegmentBuilder and IndexWriter::compact both produce COLUMNS. | Both must emit the new layout from the same encoder. |
| Generic column value, borrowed keyword view, logical allocation-shape access, merge reconstruction and query fallbacks share the column reader. | All must interpret the new layout correctly before B2 changes any collector. |
| Single cardinality allows Multi([one]); it is not identical to the Single value shape. | Preserve the state and old logical allocation charge. |
| The public schema currently admits Multi([]), but v1 value decoding rejects its zero count. | New ordinal encoding explicitly rejects this noncanonical source before publication; do not normalize it or change the public schema. |
| ReaderSnapshot owns immutable segments, visibility masks, verified-reader slots, active-reader admission and retained-metadata accounting. | Extend those owners; introduce no parallel reader, storage, or cache framework. |
| Snapshot identity includes a unique binding_id and volatile refresh state, not just a manifest generation. | Key shared values by exact snapshot identity and field ID. |
| PitHandle pins an Arc<ReaderSnapshot>. | Old PITs retain their maps and segment owners after refresh or compaction. |
| Required features stop older readers from accepting an unknown format. | A new required feature must accompany COLUMNS v2. |
| A6 is merged, with numerical misses retained. | A6 is the implementation baseline; B1 does not relabel A6 measurements. |

### 2.2 Required primary source reading

Read these sources before production edits. Paths are repository-relative and verified at the frozen revision.

- AGENTS.md; docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md; docs/TESTING.md; .github/workflows/ci.yml.
- docs/ARCHITECTURE.md; docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md.
- docs/PERF_OPTIMIZATION_ROADMAP.md; docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md.
- crates/quervant-core/src/segment/{format,column,reader,build,metadata,limits,error,schema,value}.rs.
- crates/quervant-core/src/index/{snapshot,merge,limits,mod,pit,error,reconstruct}.rs.
- crates/quervant-core/src/contract/{schema,document}.rs.
- crates/quervant-core/src/search/{typed,typed_compare,unified}.rs — read-only impact inspection.
- crates/quervant-core/src/search/{batch,projection}.rs, contract/{batch,aggregation,result}.rs and tests/pr14a_public_cursor.rs — existing public acceptance APIs, read-only.
- The specific tests and historical reports named in the acceptance section.

The user's explicit task decisions override repository guidelines where they conflict; otherwise follow the applicable engineering policy. Do not treat an old report's pending status as revoking the user's explicit merge of A6.

### 2.3 Preflight — inspect, do not retest the accepted baseline

1. Inspect git status, the configured origin, current branch and any existing dev/perf06-b1 branch/PR. Fetch origin using the existing authenticated setup; do not alter credentials or remotes.
2. Require a clean worktree or create a separate clean worktree without touching user changes. Never stash/reset/delete another task's changes.
3. Resolve the frozen commit object and current origin/main. If main still equals the pin, continue.
4. A later origin/main may be used only if it descends from the pin and the protected source/authority comparison below is empty. Record both SHAs and inspect the remaining documentation delta. A source, policy, schema, dependency or CI difference requires an amendment; do not silently rebase the design onto it.
5. An existing B1 branch with work requires reconciliation against this exact plan and its report. Do not overwrite, cherry-pick guesses, or create a competing B1 PR.
6. Create dev/perf06-b1 from the admitted main. Copy this downloaded plan verbatim to its prescribed artifact path; record SHA-256 and Git blob identity.
7. Inspect tool versions, available disk and the existing RustFS test setup. Missing real-service prerequisites can block the remote gate while local work continues. No benchmark or “host stability” campaign is authorized.
8. Complete the pre-implementation correctness gate: attach the invariant→step→test traceability, check the concrete counterexamples in this plan, record source assumptions and apply the matrix before editing production code.

Protected comparison:

~~~sh
git diff --exit-code 480a77e78c6897e05cb7ceb76b01434974b82ec6..origin/main -- \
  crates benchmarks Cargo.toml Cargo.lock rust-toolchain.toml .cargo .github/workflows \
  AGENTS.md docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md docs/TESTING.md \
  docs/ARCHITECTURE.md docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md \
  docs/PERF_OPTIMIZATION_ROADMAP.md \
  docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md
~~~

Do not use baseline test execution as a substitute for this source comparison. Reproduce a specific baseline test later only if needed to classify a concrete failure.

## 3. Scope and frozen decisions

### 3.1 In scope

- All **columnar Keyword fields whose declared Cardinality is Single**.
- Persistent lexically ordered distinct raw-value dictionaries and compact document ordinals.
- Existing Single versus Multi([one]) row-shape preservation, explicit null and absence.
- Feature-gated COLUMNS v2, new producer output, legacy reader support and compatibility tests.
- Borrowed, bound local ordinal access with no name/column search in its per-document operation.
- Optional, explicitly prepared, shared snapshot mappings with bounded retained and construction memory.
- Exact cross-segment equality and UTF-8 byte ordering for those prepared numeric values.
- Reader/PIT ownership, cancellation, concurrency, error and resource tests.
- Additive architectural documentation and narrowly scoped CI test registration.

### 3.2 Out of scope

- Query collector switching, heap redesign, segment-result truncation, cross-segment top-K algorithms, deferred scoring or changes to existing logical query charging — B2/C own these.
- Document-key numeric identity or duplicate-key redesign — B3.
- Runtime global dictionaries spanning unrelated fields, indexes or shards.
- IDs stable under arbitrary schema evolution; the current canonical-schema compatibility rule remains.
- Persistent shared value registries, manifest protocols, cross-segment on-disk rewrites, or new publication/GC protocols.
- Multi-valued field ordinal sorting, analyzed Text term ordinals, JSON-path ordinals, locale collation, case folding or a new normalizer.
- Persisting snapshot maps remotely or in manifests.
- Reintroducing the rejected postings-dictionary compact codec.
- Extra crates/dependencies, unsafe code, dynamic plugin frameworks or new telemetry.
- New benchmark configurations/results, performance acquisitions, latency or RSS claims.

### 3.3 Important semantics

1. A field ID identifies a schema field. A local ordinal identifies a raw string in one field's segment dictionary. A shared ordinal is that string's rank in one field across an exact snapshot.
2. Compare raw UTF-8 bytes, exactly as the current keyword comparator. Do not use normalized postings terms as the dictionary's source. Empty string is a real value; no sentinel may collide with it.
3. Shared ranks can change in a new snapshot when values are inserted or removed. Immutable local bytes do not change. Old PITs keep their old map.
4. Local numeric slots remain segment-local on disk. Cross-segment comparability is obtained by numeric translation. This is the agreed implementation of the user's cross-segment requirement.
5. Shared-map availability is an optimization capability, not a new condition for reading an otherwise valid legacy index. Mixed legacy/new snapshots return the specified NotAvailable result; existing string-value query execution remains usable.
6. B1 does not automatically prepare all fields during reader open or on existing queries. The new explicit preparation API owns at-most-once successful preparation per snapshot/field. B2 will invoke that API and consume its result; B1 tests exercise the API directly.
7. Logical sort/candidate resource charges remain based on the reconstructed legacy logical value shape, not the smaller physical ordinal width.
8. New-format dictionary integrity is validated at reader/column open. Legacy v1 retains its existing deferred payload-validation behavior. This is an explicit validation boundary for a new required feature, not an accidental change to old data.

## 4. Observable invariants and traceability

The acceptance section supplies the final test IDs. Preserve this contract if test names receive a mechanical suffix for Rust naming.

| ID | Falsifiable invariant | Required positive / counterexample evidence |
|---|---|---|
| INV01 | Canonical field IDs agree across compatible segments; no per-document field-name lookup in the bound ordinal API. | Reordered schema declaration; field absent from some documents; bound-access structural witness. |
| INV02 | Each eligible new column contains one sorted distinct dictionary and document ordinals, without a duplicate legacy keyword payload. | Literal wire fixture; independent size formula; repeated/high-cardinality values. |
| INV03 | Raw values and state shapes are preserved. | Absent, null, empty string, Single, Multi([one]); explicit rejection of noncanonical Multi([]), Empty and Multi>1. |
| INV04 | Dictionary order/equality is byte exact. | ASCII case, NUL, Unicode, prefixes, duplicate strings, opposite segment insertion order. |
| INV05 | Existing generic value, sort-view and allocation-shape APIs remain logically equivalent. | Differential comparison with retained v1 encoder, with exact errors/charges and state shapes. |
| INV06 | Every producer emits the same supported feature/layout combination. | Builder and compaction, zero/all-missing values, no-keyword schema, genuine legacy append/compact. |
| INV07 | New-format corrupt dictionary/row metadata is rejected before trusted access, including unselected/deleted-only values. | Recomputed-checksum corruption fixtures for every format boundary. |
| INV08 | Shared ordinals have one meaning across all admitted segments of the same snapshot/field. | Literal local→shared tables plus an input-derived independent union/sort oracle. |
| INV09 | Shared maps never cross a field/snapshot binding and do not mutate old PIT state. | Refresh, volatile view, append, delete, compaction, held PIT and wrong-guard cases. |
| INV10 | Shared mapping reads dictionaries, not every document, and copies no string pool. | Construction counters; one segment identity; retained structure accounting; no inverse string table. |
| INV11 | Each field has one builder; waiters cannot observe a partial map or cause duplicate successful construction. | Deterministic barriers, contention, cancellation, unwind and poison tests. |
| INV12 | All new ordinal/map allocations are pre-admitted and released correctly; the explicit ordinary-layout exception is disclosed. | Exact capacity, one-under, failure injection, last-Arc drop, multiple fields and held PITs. |
| INV13 | Optional capability failures never hide corruption or cancellation. | Exact NotAvailable reasons versus typed Err; sticky optional failures; reset on cancellation/unwind. |
| INV14 | Existing query correctness and durable local/remote visibility remain unchanged. | Input-derived real FsDirectory and RustFS vertical slices; full existing query regression gates. |
| INV15 | B1 does not claim B2 execution/performance completion. | Protected scope diff, documentation and report checks; zero benchmark artifact delta. |

## 5. Architecture and data flow

~~~mermaid
flowchart TD
    A["Immutable segment dictionaries"] --> B["Bound local ordinal readers"]
    B --> C["Snapshot field preparation"]
    C --> D["Local-to-shared numeric maps"]
    D --> E["B2 numeric comparisons"]
    B --> F["Retained value materialization"]
~~~

The existing Directory, SegmentStore/SegmentCache, verified segment state, IndexWriter, ReaderSnapshot and PIT ownership remain authoritative. The new format stays inside the existing immutable segment container and its checksums. No additional remote object or commit transaction is introduced.

New shared maps retain numeric buffers and their accounting only. They do not retain Arc<ReaderSnapshot>, preventing a snapshot→cache→snapshot cycle. They do not retain escaped unbudgeted column readers or copied document buffers. Access to actual segment values continues through an admitted GuardedSegmentReader and its bound local column.

Strings are still compared while constructing ordered dictionaries and merging their distinct terms. The later prepared comparison path is numeric. This plan makes no claim that all string processing disappears from indexing or querying.

## 6. Implementation sequence overview

1. G0: source/authority preflight and G1: invariant/counterexample reconciliation.
2. Generate and freeze the genuine pre-B1 fixture under §11 before production edits; then add the new required feature and local ordinal codec with literal/differential unit tests.
3. Integrate the same encoder into normal builds and compaction; integrate all column consumers.
4. Add the borrowed bound local API; prove its data access and logical shape.
5. Add the snapshot shared-map provider, exact cache state machine, accounting and cancellation tests.
6. Execute the local legacy/new/PIT/compaction/reopen vertical slices and the real RustFS slice.
7. Run the consolidated final local gates once on the final source; fix actual defects within the matrix and rerun only affected mandatory gates.
8. Complete the additive docs/report, prepare one draft PR push, observe its ordinary CI and retain source identity. Report missing gates accurately; no extra dispatch or repeated acquisition.
9. Independent reviewer and maintainer own acceptance. B2 starts from the accepted B1 implementation, not an unreviewed branch.

## 7. Persistent keyword ordinal codec and reader integration

### 7.1 Source facts and scope

- `segment/column.rs::encode_columns` currently emits COLUMNS version 1, a 6-byte prefix, 46-byte column headers, and 36-byte block entries. Single Keyword uses layout `0x02`: one state byte per document, `(rows+1)` u64 offsets per block, then repeated length-prefixed strings.
- `ColumnGeometry` retains only `Vec<ColumnMeta>`. The field table is cached under the existing metadata admission path; offset tables and values remain borrowed from immutable segment bytes. Preserve this ownership model and **preserve the size of `ColumnMeta`**.
- `ColumnReader::value`, `keyword_sort_view`, and `encoded_value_shape` share `span_of`. The latter admission seam feeds `search/typed_compare.rs::ColumnAccess::decoded_value_bound`; returning physical ordinal width there would undercharge string materialization.
- Producers are `SegmentBuilder::build` and `index/merge.rs::compact`/`build_merged_segment`. Ordinary building currently calls `ordered_docs(&ordered)` again for columns, cloning documents already cloned separately for stored encoding. The new column call must consume the existing borrowed physical-order references without that column-only clone.
- `Schema::validate_field_values` allows `Cardinality::Single` with `FieldValues::Multi(vec![one])`. Preserve that observable state; it is not interchangeable with `FieldValues::Single` for round trips or budget admission. The schema also accidentally admits `Multi([])`; the existing decoder rejects its zero count. B1 must reject it in the new encoder before publication without modifying public schema validation.
- Existing `encode_columns` is used by many literal/corruption/legacy tests, including tests that deliberately expect UTF-8 rejection on value access. Keep its legacy semantics and bytes.

Eligible fields are exactly `field.is_columnar() && field.field_type == Keyword && field.cardinality == Single`. Multi-cardinality Keyword, Text, JSON strings, and every other column type retain their existing encoding. B1 does not change the query collector or sort eligibility.

### 7.2 Frozen feature and version design

Add `FEATURE_KEYWORD_ORDINALS: u16 = 0x0010` with supported version `1` in `segment/format.rs`. This is a **feature** namespace; the existing section kind `JsonPaths = 0x0010` is unrelated. No new section kind, manifest format, container major/minor version, or postings feature is introduced.

Add `LAYOUT_KEYWORD_ORDINAL_SINGLE: u8 = 0x03` in `segment/column.rs`.

Keep the public `encode_columns(...) -> SegmentResult<Vec<u8>>` as the legacy-v1 entry point, sharing private implementation/helpers where practical. Add the production entry point:

```rust
pub(crate) enum ColumnDocuments<'a> {
    Documents(&'a [SegmentDocument]),
    References(&'a [&'a SegmentDocument]),
}

pub(crate) struct EncodedColumns {
    pub(crate) bytes: Vec<u8>,
    pub(crate) has_keyword_ordinals: bool,
}

pub(crate) fn encode_columns_with_ordinals(
    schema: &CodecSchema,
    docs: ColumnDocuments<'_>,
    block_docs: u32,
    limits: &SegmentLimits,
) -> SegmentResult<EncodedColumns>;
```

`ColumnDocuments` provides private length/index/iteration access, not a copied vector of references. New production encoding emits v2 iff there is at least one eligible field; otherwise it emits v1 with byte-identical legacy layout. In v2 every eligible field uses layout 3. Other fields keep layouts 1/2 and identical individual payloads. No cost-based escape back to legacy Keyword is permitted: every eligible new column must expose ordinals.

The field-header width and block-entry width remain exactly 46 and 36. Their existing fields retain their meanings. The reserved `state_bitmap_len` is zero. The only prefix difference is `columns_version = 2`.

Feature agreement in `reader.rs::decode_metadata`, at the existing column validation stage:

| Body | Required features | Result |
|---|---|---|
| v1 or absent | no ordinal feature | Existing behavior, unchanged |
| v2 | `FEATURE_COLUMNS/1` and `FEATURE_KEYWORD_ORDINALS/1` | Validate v2; must contain at least one eligible ordinal column |
| v2 | ordinal feature missing or only optional | `Corrupt { context: "keyword ordinals", detail: "columns version/feature mismatch" }` |
| v2 | ordinal feature required, but `FEATURE_COLUMNS/1` absent or only optional | Same mismatch error |
| v1 | ordinal feature present | Same mismatch error |
| absent | ordinal feature present | `Corrupt { context: "keyword ordinals", detail: "feature requires columns" }` |
| any | required ordinal feature version unsupported | Existing `UnsupportedFeature`, before payload decoding |

Do not strengthen unrelated v1 feature checks or error precedence. Standalone `ColumnReader::open` accepts both known payload versions; feature enforcement belongs to the containing `SegmentReader`.

### 7.3 Exact layout-3 bytes

All integers below are little-endian. Existing header fields and block directories are unchanged. `data_base = dir_offset + dir_len` remains the origin for block state/value offsets.

Immediately at `data_base`, store:

| Relative offset | Encoding | Meaning |
|---:|---|---|
| 0 | u64 | `U`, number of distinct dictionary strings |
| 8 | u64 | `L`, total raw dictionary UTF-8 bytes |
| 16 | `(U+1)` packed unsigned integers | Offsets into the dictionary byte blob |
| `16 + (U+1)*ow` | `L` bytes | Distinct strings concatenated in strict byte-lexical order |
| after dictionary blob | Existing per-block state bytes and packed ordinal slots | Document rows |

Define one `pub(crate)` helper in `segment::column`, `packed_width(max_value: u64) -> u8`, returning the smallest width in **1..=8** that can hold `max_value`; zero uses width 1. The snapshot map reuses this pure helper with `T.saturating_sub(1)` rather than introducing a second width algorithm. Widths are derived, not stored:

```text
ow = packed_width(L)
dw = packed_width(U.saturating_sub(1))
dictionary_len = 16 + (U + 1) * ow + L
```

Each block stores exactly `rows` state bytes followed by exactly `rows*dw` ordinal bytes. Its first `state_offset` is the dictionary length. Following block extents are contiguous. State/value offsets remain relative to `data_base` and include the dictionary prefix. Blocks retain the persisted `block_docs` arithmetic and touch only the requested row's block during document access.

State grammar:

| State | Meaning | Ordinal slot |
|---|---|---|
| `0x00` ABSENT | Missing | Must be zero |
| `0x01` EXPLICIT_NULL | Null | Must be zero |
| `0x03` SINGLE | One Keyword value | Must be `< U` |
| `0x04` MULTI | Exactly one Keyword value in the allowed single-element Multi state | Must be `< U`; count is implicit 1 in this layout |
| other, including `0x02` EMPTY_MULTI | Invalid for this single-cardinality layout | Reject |

The zero ordinal may legitimately designate the empty string. Missing/null have separate state tags; never consume a value ordinal as their sentinel. Dictionary ordering is exact UTF-8 **byte** order, with no case folding, locale collation, or normalization. Empty string sorts first. Embedded NUL is allowed if already accepted as a Keyword value.

The offset table begins at 0 and ends at L. It is nondecreasing; an empty first term can have equal offsets. Strictly ascending dictionary string order rejects duplicate terms, including multiple empty strings. Each term's byte length is at most `u16::MAX`, retaining the existing Keyword wire ceiling.

### 7.4 Structural size proof and witnesses

For one eligible field, let:

- `N` = document count; `B = ceil(N/block_docs)`;
- `V` = number of value-bearing rows, including Single and Multi-of-one;
- `M` = number of Multi-of-one rows;
- `U` = distinct value count; `R` = repeated string payload bytes across all value rows; `L` = distinct dictionary payload bytes.

The per-column payloads, excluding the unchanged 46-byte field header, have exact lengths:

```text
legacy = 36*B + N + 8*(N+B) + R + 2*V + M
ordinal = 36*B + N + 16 + (U+1)*ow + L + N*dw
```

No query-time representation or stored-source section is counted in this local column formula. For valid single-valued input, `U <= V <= N`, `L <= R`, each term is at most 65535 bytes, and accepted `N <= u32::MAX`. Consequently `dw <= 4`, `ow <= dw+2`, and:

```text
ordinal <= legacy + 17
```

Sketch: for fixed U, excess is maximized by N=V=U and R=L; each extra absent/null/repeated row reduces the excess because `dw <= 4 < 8`. For U=0, maximum excess is 17 at N=0. For U=1 it is at most 3. For U>=2, substitute the width intervals; the largest interval bound is `22-8*B <= 14` for dw=4/ow=6, with smaller intervals below 17. Existing block directory and state bytes cancel. The container adds one 4-byte required-feature pair once, not once per field.

Therefore this design has a concrete tiny-field overhead ceiling without losing ordinal capability. Do not promise a whole-index percentage reduction; STORED, postings, and other sections are unchanged. No old and new Keyword column are stored side by side.

Literal witness: field id 0, Keyword tag 2, block_docs=4, documents `[Absent, Null, Single("b"), Single("")]`.

```text
U=2, L=1, ow=1, dw=1
dictionary offsets: [0,0,1]
dictionary bytes: [0x62]
row states: [0,1,3,3]
row ordinals: [0,0,1,0]
prefix+headers = 6+46 = 52
directory = 36 bytes; data_base=88
directory entry: first_doc=0, rows=4, state_offset=20,
                 values_offset=24, values_length=4
COLUMNS total = 116 bytes; corresponding v1 total = 137 bytes
```

Additional exact witnesses: empty field N=0 has 17 bytes of new dictionary payload; N=1 with one empty value adds 1 byte over v1; N=1 with one 65535-byte value adds 3; all-absent N=1 adds 2. B1-U04 and U15 test width boundaries directly and 256/257 distinct values without allocating enormous boundary corpora.

### 7.5 Encoder algorithm and allocation discipline

Use a private encoding mode to share legacy planning/header/block helpers. Preserve the public v1 entry point's behavior; new validation applies to the new production path.

1. Check `block_docs != 0`, doc count, decoded-entry bound and representability before allocating ordinal scratch.
2. For each eligible field, inspect each document's **borrowed** `FieldValues` once, in physical document order. Record its state byte and, for a value row, a borrowed `(term: &str, physical_doc_id: usize)` record. Do not clone a `FieldValues`, String, SegmentDocument, or BTreeMap.
3. Reject invalid new-encoder input deterministically: wrong scalar type -> `FieldTypeMismatch`; Multi([]) -> `InvalidColumnGeometry { detail: "zero multi count" }`; Multi with >1 values -> `InvalidColumnGeometry { detail: "multiple values in single keyword column" }`; Empty -> `InvalidColumnGeometry { detail: "empty multi in single keyword column" }`. Keyword length >65535 retains the current `LengthMismatch { context: "u16 length prefix", expected: 65535, actual }`. The valid Multi-of-one state remains 4.
4. Maintain R, V and M during that scan with checked arithmetic. Reserve the state buffer exactly N bytes. Grow the borrowed-record vector geometrically and fallibly; check the proposed backing bytes before growth and charge actual capacity. **Never `try_reserve_exact(1)` per record**, reserve N records for a sparse field, or make a separate full pass merely to count the records.
5. Sort the borrowed records once with `sort_unstable_by` on `term.as_bytes()`. Equal terms need no document-id tie comparator because they receive the same ordinal, and writes target unique physical slots.
6. Scan sorted records once to determine U and L and select widths. This pass is necessary to determine final exact extents. No temporary unique-String set, per-document binary search, or String->ordinal hash table is allowed.
7. Compute all column/header/directory/data extents with checked arithmetic. Plan ordinary columns with the existing representation. Allocate the final COLUMNS Vec exactly once and initialize it to its final length with zeros. Local checked slice-writing helpers fill this buffer; do not add broad ByteWriter patch APIs.
8. Write headers and block directory entries, then copy state buffers. Traverse each field's sorted records once to emit dictionary offsets and each distinct term's bytes directly into their final ranges. Assign the increasing local ordinal to every record in that equal-term run by writing the packed number directly into its final document slot. Missing/null ordinal slots remain the canonical zeros from initialization.
9. Release field scratch when its final bytes have been emitted. Do not allocate another N-element u64 ordinal map, an offsets Vec, a distinct-strings Vec, or a second completed column body that will subsequently be copied into COLUMNS.
10. Return `EncodedColumns`; consumers move its Vec into the existing container flow. Do not redesign the container builder or eliminate unrelated existing section copies in B1.

Every newly introduced ordinal vector/output capacity is admitted against `max_single_allocation`; new ordinal scratch plus measured retained ordinary buffers and final output use one `DecodeBudget` under §9.3. That section explicitly preserves the existing ordinary-layout temporary allocation behavior; do not silently redesign it. Pre-admit growth by reserving the capacity delta, then reconcile actual capacity; allocator refusal is `LimitExceeded` with bytes, not element count. Hold the final output allowance alongside all still-live field planning buffers. No further allocation occurs after output emission begins, so releasing scratch during emission requires no budget refund API. An overflow uses requested=`u64::MAX`. Do not increase defaults, switch to infallible large allocations, or fall back to a second representation on resource failure.

The existing column encoder has no Cancellation argument. Preserve the existing merge checks surrounding encoding and the existing publication rollback. Do not make sort comparison order depend on a cancellation flag. The global-map preparation API has its separately prescribed cancellation checks; it is not justification for introducing a new encoder cancellation framework.

### 7.6 Reader validation and allocation model

`ColumnMeta` and `ColumnGeometry::columns` retain their existing shape and actual capacity charging. The new dictionary's fixed geometry is derived from its 16-byte prefix when binding a column. It is copied into a small borrowed handle, not retained as an Option of a large struct on every legacy/numeric column. `column_geometry_allowance` remains valid because field-header size and ColumnMeta size are unchanged.

Extend the authoritative `ColumnReader::parse` rather than creating a second parser. V1 parsing and its value-validation timing remain unchanged. V2 validation, before publishing verified state, checks:

1. Current field/schema/header/count/block geometry rules; v2 reserved header field must be zero; eligible fields have layout3 and other types their existing layouts. In v2 the complete ordered field-ID inventory must equal the canonical schema's columnar-field inventory, including empty/all-missing fields. Compare with a filtered schema iterator; do not allocate a second field-name/ID table. Missing or extra declared columns use `InvalidColumnGeometry { detail: "column inventory does not match schema" }`. V1 retains its previous inventory rules. This prevents a malformed new segment from masquerading as a legacy-absent field during global-map preparation.
2. The 16-byte dictionary prefix exists. U <= N and configured entry limits hold. Derive widths. Checked `(U+1)*ow`, dictionary blob extent, and usize conversions fit the containing bytes before any indexed access.
3. First offset=0; all offsets are nondecreasing and <=L; terminal offset=L; each length <=65535. Each distinct slice is valid UTF-8. Neighboring strings are strictly ascending by bytes. Validate all terms, including terms not returned by a query.
4. U=0 implies L=0 and the single zero offset. It permits only missing/null rows. The reader need not allocate a used-term bitmap or prove dictionary surjectivity: the canonical writer omits unused terms, but harmless unused valid terms do not affect comparison semantics.
5. Dictionary and block extents are contiguous and nonoverlapping. New row states obey the layout3 grammar; each values extent is rows*dw; value ordinals are <U; stateless slots are zero. Inspect every row at open, including unselected rows.
6. For v2, columns are contiguous from the end of the headers and the last column ends exactly at section length. Empty ordinal columns set their end to their dictionary end even when there are no blocks.

Use existing typed errors: malformed geometry/state/order/ordinal/extents -> `InvalidColumnGeometry` with fixed bounded labels; bad UTF-8 -> `InvalidUtf8 { context: "keyword" }`; resource overages -> `LimitExceeded`. No raw term bytes are placed into errors. Missing/truncated primitive prefixes may retain `Truncated` from ByteReader; the test matrix must freeze the exact reached check for each fixture, rather than allowing arbitrary error categories.

No dictionary strings, per-term descriptors, offsets, or document ordinals are copied to heap during reader validation. UTF-8 validation reads immutable bytes and retains no string allocation, so do not charge all dictionary bytes as though owned strings had been allocated. Existing metadata admission charges retained geometry. Logical string/FieldValue decode budgets still apply when materializing a document value.

The new format deliberately has eager dictionary/value-reference validation at open; legacy v1 keeps its established lazy value error timing. This is an explicit new-feature trust boundary, not an unannounced relaxation. Do not alter legacy malformed-byte fixtures to expect the new timing.

### 7.7 Bound ordinal API

Implement these exact public, documented names through the existing public `segment::column` module; §8 consumes them. Public visibility permits real integration tests and external foundation consumers to exercise document -> local ordinal -> global ordinal without test-only production escape hatches. Struct fields remain private:

```rust
pub enum KeywordOrdinalState {
    Single,
    MultiOne,
}

pub enum KeywordOrdinalValue {
    Missing,
    Null,
    Value { ordinal: u64, state: KeywordOrdinalState },
}

pub struct KeywordOrdinalColumn<'a> { /* private fields */ }

impl<'a> ColumnReader<'a> {
    pub fn bind_keyword_ordinals(
        &self,
        field_id: u32,
    ) -> SegmentResult<Option<KeywordOrdinalColumn<'a>>>;
}

impl<'a> KeywordOrdinalColumn<'a> {
    pub fn dictionary_len(&self) -> u64;
    pub fn dictionary_term(&self, local_ord: u64)
        -> SegmentResult<&'a [u8]>;
    pub fn doc_ordinal(&self, doc_id: u64)
        -> SegmentResult<KeywordOrdinalValue>;
}
```

The handle borrows original immutable section bytes for `'a` and copies only ColumnMeta, dictionary extent/width values and SegmentLimits. It must **not** borrow the ColumnReader's owned geometry Vec or the temporary reader object. A caller can bind from a temporary ColumnReader and retain the handle only while its GuardedSegmentReader owner remains alive. It owns no Arc and clones no data. Give the bound handle its own local block-read counter if structural tests need it; never borrow ColumnReader's Cell across its shorter lifetime.

Binding resolves numeric field ID once, confirms new layout, derives fixed dictionary geometry once, and returns None for legacy/unsupported fields. `dictionary_term` performs checked offset access into the validated bytes without a UTF-8 conversion or allocation. `doc_ordinal` performs constant block arithmetic and one packed ordinal read, with state classification, bounds checks, no schema/field lookup, no dictionary lookup and no string processing. Single and allowed Multi-of-one both return a numeric Value while preserving their original state in the returned tag. Returning this already-read tag avoids a later duplicate row read when B2 computes logical admission. `dictionary_term(ord).len()` obtains the logical length through numeric offsets and does not inspect the string bytes. No unrelated generic fallback is built here. Derive `Debug + Clone + Copy + PartialEq + Eq` for the two value/state enums; provide no public handle constructor.

### 7.8 Existing consumers must remain correct

Extend the shared span representation with exactly `ValueSpan::Ordinal { state: u8, start: usize, end: usize }`, where start/end are absolute raw-term byte offsets in the same COLUMNS body. Add private `KeywordOrdinalColumn::dictionary_range(local_ord) -> SegmentResult<(usize, usize)>`; reuse it in public `dictionary_term` and the new `span_of` branch. Keep ranges as offsets, avoiding an added lifetime parameter throughout ValueSpan. Share the existing block-directory/state/row-location read between bound document access and ordinary span access through one private helper; never call `doc_ordinal` after already reading the same row in `span_of`. Both ordinary and bound readers increment their own block-read observation once per valid row lookup. All existing consumer paths must handle the new span:

The ordinary accessors already selected a `ColumnMeta` before `span_of`; the ordinal branch must use that selected metadata directly. Add one private constructor/helper taking the copied `ColumnMeta`, original immutable bytes and limits, shared with the public binder. **Do not call `bind_keyword_ordinals(field_id)` from `span_of`, value or keyword_sort_view**, because that would repeat the schema/geometry search per candidate. Derive the fixed dictionary prefix from the selected metadata without retaining another geometry table. New bound-reader observation counters exist only under `cfg(test)`.

| Existing path | Required new-layout behavior |
|---|---|
| `ColumnReader::value` | Missing/Null unchanged. SINGLE -> owned Keyword string. MULTI -> one-element FieldValues::Multi, preserving its Vec and existing checks. Fallible copy after the original logical DecodeBudget checks. |
| `keyword_sort_view` | SINGLE -> borrowed validated string and original logical string budget; Missing/Null unchanged; MULTI remains `LegacyDecode` so B1 does not silently widen sort eligibility. |
| `encoded_value_shape` | SINGLE -> `(STATE_SINGLE, term_len+2, 1)`; MULTI -> `(STATE_MULTI, term_len+3, 1)`; stateless -> `(state,0,0)`. These are legacy-equivalent logical spans, **not packed ordinal widths**. Update its doc comment to say so. |
| `ColumnAccess::decoded_value_bound` | Existing formula unchanged; it receives the logical spans above. |
| `SegmentReader::column_value` / `open_columns` | Existing public behavior, no alternative raw-only decoder. |
| Merge reconstruction | Reads old/new columns through the once-per-source retained ColumnReader::value described in §7.9; preserves MultiOne state, then emits ordinals in output physical order. |
| Projections, aggregations, generic typed predicates, generic/cursor sorts | Continue through ordinary value access and retain exact values, states, ordering and admission behavior. No query algorithm changes. |

No new per-candidate full validation or dictionary traversal. The bound API supplies the future B2 numeric path. Existing B1 string consumers may still call `from_utf8` when constructing a safe `&str`; do not introduce unsafe code or a retained Vec<&str> merely to remove that conversion before B2.

### 7.9 Producer and lifecycle integration

In `build.rs` pass `ColumnDocuments::References(&ordered)` to the new encoder; consume the returned bytes and its feature boolean. Existing stored encoding remains independent and unchanged. Require FEATURE_KEYWORD_ORDINALS/1 exactly when the returned flag is true, alongside FEATURE_COLUMNS/1.

In `merge.rs` pass `ColumnDocuments::Documents(&out_docs)` to the same encoder. Thread its boolean to `build_merged_segment` rather than independently rediscovering whether the resulting payload is new. Keep no-op compaction behavior unchanged. Newly merged eligible columns always use ordinals even when all input segments are legacy.

Also remove a source-proven repeated parse in this same consumer: the current merge reconstruction loop calls `reader.column_value(...)` for each nonstored column/document. On the unmetered `segment.open_reader` path, that convenience method opens and validates all columns again. After the existing no-op decision and codec-schema equality checks, open each source's columns **once**, retaining a bounded `Vec<Option<ColumnReader<'_>>>` borrowed from the already opened `readers`. Use the source's retained column reader's `value(field.id, old_doc)` in the reconstruction loop; None has the same meaning as the old method returning None. Drop this local vector before encoding output columns. Reserve its backing fallibly against existing limits. Do not eagerly open columns before the no-op boundary or move this before schema mismatch validation. Add an observation assertion that source column parsing does not scale with output document count. `index/reconstruct.rs` already opens columns once and reuses the reader, so it needs no matching production edit.

All segment construction must complete before existing immutable content publication. Encoding/resource/validation failure follows existing failure cleanup and leaves prior CURRENT/generation usable. No in-place modification of old segments, global persistent dictionary, new storage sidecar, network access path, or manifest field is introduced. RustFS caches and cold opens see the same immutable segment bytes and required feature as local storage.

### 7.10 Legacy and test migrations

- Keep public v1 encoder fixtures byte-identical. `borrowed_keyword_tests::b_u14_invalid_utf8_rejected`, current unified corruption fixtures, and A-series legacy column constructions retain their old timing and bytes.
- New-format fixtures explicitly call the new encoder and assert open-time validation, feature agreement, numeric values and ordinary materialization separately.
- `tests/pr08_integration.rs::p8_t42_golden_bytes_features_unchanged` receives the new supported feature pair in its exact allowlist; do not drop old features or rewrite goldens.
- Inspect every copied-container test: tests replacing an ordinal COLUMNS body with v1 must also remove only the new ordinal feature if the test's intent is a genuine v1 reconstruction. Tests retaining v2 keep the feature. Do not broadly relax container feature validation.
- Property/differential acceptance compares decoded FieldValues to input-derived expected values, including Multi-of-one, and compares all ordinary query results to an independent input-derived oracle. A second copy of the new encoder is not an oracle.

### 7.11 Negative evidence and interpretation

PR 15H-E's compact **postings term dictionary** was rolled back despite section compression and latency gates passing because its frozen whole-segment/whole-index size gates failed (`docs/pr-artifacts/pr-15h-e/decision.md`). B1 changes a different representation: repeated Keyword column values and document offset metadata. It does not resurrect that postings dictionary codec or its feature. The per-field cost formula above guards against the same mistake of assuming section-local savings imply a whole-index percentage win.

Existing PR 15G-A cached ColumnGeometry and PR 15G-B validated lazy offsets are already present and remain reused. Do not add another segment cache. No speedup percentage is asserted for B1; B2 uses the numeric reader APIs, and B4 owns the combined warm-performance qualification and writer/open/RSS observations.

## 8. Snapshot-wide numeric value maps

### 8.1 Source facts and architecture boundary

- `segment/schema.rs::CodecSchema::from_contract` assigns dense `u32` field IDs by ascending UTF-8 field-name order. Identical supported schemas therefore already give the same IDs across segments. Preserve these IDs and the exact schema/analyzer equality rules. Do not add a field-ID registry, rename fields, or introduce mixed-schema evolution.
- `index/mod.rs::load_committed` checks the supplied canonical schema against the manifest. `index/merge.rs` checks all input reader schemas for exact equality. `search/unified.rs` already checks lexical reader schemas against the prepared query codec.
- `index/snapshot.rs::ReaderSnapshot` is an immutable view of a committed generation **or a volatile refresh**. Its private `binding_id` is unique to the snapshot instance; committed generation alone is not a sufficient cache key. Its `slots` cache admitted `Arc<VerifiedSegmentState>` values and has an existing empty/building/ready state machine with RAII unwind recovery.
- `ReaderSnapshot::open_segment_reader` charges encoded segment bytes to `ReaderByteBudget` on every acquisition, including cached acquisitions. The resulting `GuardedSegmentReader` owns the admission reservation and deliberately does not expose an owned reader.
- `segment/metadata.rs` already provides `MetadataBudget`, `MetadataMeter`, `MetadataReservation`, `element_bytes`, `capacity_bytes`, and `accumulate`. Reuse this account and the existing cap, which equals the snapshot reader-copy limit. No new configurable budget or unaccounted retained mapping cache is authorized.
- `PitHandle` retains `Arc<ReaderSnapshot>`. A held PIT must retain its old mappings, segment identities, and visibility. A new snapshot constructs a separate mapping; no shared mutable rank table is permitted.
- The current `collect_mixed` path already acquires an ordered guard for every snapshot segment before collecting. The new preparation API accepts that existing guard slice so B2 will not reopen or re-admit readers to construct the mapping.

The map is over the **physical dictionaries** of every segment in the snapshot. It is not constructed from live documents, matching documents, selected segments, or a particular query. Deleted-only terms may retain an ordinal until compaction removes them in a new snapshot. Do not scan documents or visibility masks to prune dictionary terms.

### 8.2 Frozen feature boundary

B1 delivers the persistent segment representation, borrowed local accessors, and snapshot-wide numeric translation foundation. B1 does not change production candidate selection, comparator dispatch, cursor serialization, scoring, duplicate identity, or Top-K behavior. B2 owns adopting this foundation in the query loop; B4 owns the separately approved cumulative performance qualification.

All supported same-schema segments of one snapshot can share one numeric ordering for one eligible field. That ordering is identified by `(snapshot binding_id, field_id)`. It need not retain the same numbers after refresh, append, reopen, or compaction. No ordinal is a durable application identifier or a cross-snapshot cursor value.

The mapping is optional acceleration. A valid but unsupported or resource-constrained snapshot produces a typed `NotAvailable` result. Corruption, schema disagreement, wrong snapshot binding, cancellation, and poisoned state produce typed errors. No caller may treat those errors as optional fallback.

### 8.3 Exact ownership and API additions

#### 8.3.1 Files

1. New `crates/quervant-core/src/index/keyword_ordinals.rs`: only the snapshot ordinal cache, the packed maps, streaming builder, and focused unit tests.
2. `index/snapshot.rs`: add one cache owner to `ReaderSnapshot`; initialize it in the existing common constructor; add the preparation wrapper; add private identity to `GuardedSegmentReader` and set it at acquisition; add focused identity/lifetime tests.
3. `index/mod.rs`: module declaration and explicit public re-exports of the new foundation API types.
4. `segment/metadata.rs`: comments may mention both verified-segment and global-ordinal metadata; reuse the existing implementation without changing its cap or semantics.

No changes to `index/pit.rs`, `index/limits.rs`, or `index/error.rs` are required. Their existing contracts suffice. Section 7 defines the bound local-column API in `segment/column.rs` and its shared-reader wiring.

#### 8.3.2 Public API

Implement these exact public, documented names:

```rust
pub enum KeywordOrdinalUnavailable {
    LegacySegment,
    ResourceBudget,
    Allocation,
    UnsupportedField,
}

pub enum KeywordOrdinalPreparation {
    Ready(Arc<SnapshotKeywordOrdinals>),
    NotAvailable(KeywordOrdinalUnavailable),
}

impl ReaderSnapshot {
    pub fn prepare_keyword_ordinals(
        &self,
        field_id: u32,
        guards: &[GuardedSegmentReader],
        cancellation: &dyn crate::analysis::Cancellation,
    ) -> IndexResult<KeywordOrdinalPreparation>;
}

impl SnapshotKeywordOrdinals {
    pub const fn field_id(&self) -> u32;
    pub const fn term_count(&self) -> u64;
    pub fn bind_segment(
        &self,
        guard: &GuardedSegmentReader,
    ) -> IndexResult<SegmentOrdinalMap<'_>>;
}

impl SegmentOrdinalMap<'_> {
    pub fn translate(&self, local_ordinal: u64) -> SegmentResult<u64>;
}
```

`KeywordOrdinalUnavailable` is `Debug + Clone + Copy + PartialEq + Eq`. All fields of `SnapshotKeywordOrdinals` and `SegmentOrdinalMap` are private. The map binding is retained internally; no persisted or externally serialized identity is introduced. `KeywordOrdinalPreparation` can be `Debug` without requiring map internals to expose content.

`GuardedSegmentReader` gains private `snapshot_binding: u64` and `segment_index: usize`, set by `open_segment_reader` from the acquiring snapshot. A narrowly visible `pub(super)` identity accessor is permitted for the sibling map module. Neither the fields nor a constructor become public. The original reader and RAII admission reservation remain unchanged.

The preparation wrapper first polls cancellation, then verifies that the slice contains exactly one guard per snapshot segment, in canonical segment order, with the same snapshot binding. A mismatched, missing, duplicated, reordered, or foreign guard returns `IndexError::CorruptCommittedState` with fixed detail `"keyword ordinal readers do not match snapshot"`. This happens before consulting a ready cache entry.

`bind_segment` checks the guard binding against the map binding and uses its recorded segment index. A foreign/new/old snapshot guard returns the same typed corruption category with fixed detail `"keyword ordinal map does not match snapshot"`. The check happens once during segment setup, never per document.

Do not add a global-ordinal-to-string table or API. B2 retains the winning document's segment/document identity and can materialize through that document's already bound local column. The snapshot cache retains no string copies, term representatives, `Arc<ReaderSnapshot>`, readers, or active-reader guards.

#### 8.3.3 Borrowed local codec interface required by this layer

Section 7 provides a bound `KeywordOrdinalColumn<'a>` with dictionary count, borrowed dictionary bytes by ordinal, and document ordinal/state access. The binding must borrow the original immutable segment bytes for `'a` while copying only its small validated geometry into the handle. It must not borrow an owned temporary `ColumnReader` geometry vector with the shorter `&self` lifetime.

The local handle and its binding/access methods are public with private fields, so real integration acceptance can inspect the persisted document-to-local-to-global path. Its public result retains source shape as `KeywordOrdinalValue::Value { ordinal, state: KeywordOrdinalState::Single | KeywordOrdinalState::MultiOne }`; Missing and Null remain separate variants. B2 must retain this distinction for the existing logical admission and fallback contracts. The map builder itself does not use document state.

This permits a builder to open a column view once, obtain its bound handle, drop the temporary column view, and keep the handle while the caller's guarded reader remains borrowed. It prevents retaining another full column geometry per segment. No raw pointer, unsafe lifetime extension, self-referential owner, or escaped reader is authorized.

The map builder calls **only** local dictionary access. It must not call the document-ordinal API, `column_value`, `doc_key`, live-document access, or stored-document decoding.

### 8.4 Optional results and retry policy

The following outcomes are frozen:

| Condition | Result | Cache behavior |
|---|---|---|
| No segments, nonexistent field ID, non-keyword field, non-columnar field, or unsupported cardinality | `NotAvailable(UnsupportedField)` | Direct result; nonexistent IDs must not allocate arbitrary cache entries |
| At least one eligible field column uses the genuine legacy layout | `NotAvailable(LegacySegment)` | Sticky for that field and snapshot |
| Proven valid dimensions cannot fit checked integer/usize arithmetic, per-allocation bound, or remaining metadata allowance | `NotAvailable(ResourceBudget)` | Sticky for that field and snapshot |
| A fallible vector/heap reservation fails | `NotAvailable(Allocation)` | Sticky for that field and snapshot |
| Local codec detects malformed data, out-of-range ordinals, invalid UTF-8, invalid ordering, or a required-feature/layout inconsistency | Original typed error, wrapped by `IndexError::Segment` where applicable | Do not cache availability or a partial map |
| Reader schemas disagree | `IndexError::SchemaMismatch`, fixed bounded detail | Do not publish mapping |
| Cancellation | `IndexError::Cancelled` | Reset own in-progress state; wake waiters |
| Panic/unwind during construction | Unwind propagates | RAII resets own in-progress state and wakes waiters |
| Cache mutex poisoning | `IndexError::CorruptCommittedState`, detail `"keyword ordinal cache lock poisoned"` | Fail closed; never serve recovered contents |

The early UnsupportedField path follows cancellation/ordered-guard validation and the first canonical schema eligibility check; it does not allocate or perform full-schema validation for arbitrary invalid IDs. Full schema equality is validated once during registry initialization for eligible requests.

Sticky optional unavailability lasts for the snapshot lifetime, including later calls after memory becomes available. Only a new snapshot may try again. This prevents repeated allocation attempts or repeated dictionary merging on every query. This is an explicit acceleration policy, not a claim that memory pressure is permanent. Report it in the API documentation.

There is no automatic retry within a preparation invocation. A waiter whose separate builder is cancelled may become the next builder after wake-up if the waiter itself is not cancelled; this is its first construction attempt, not a retry of failed work. A builder returning an error must return immediately.

Do not catch every `SegmentError::LimitExceeded` as optional failure: errors originating from the authoritative codec are preserved. Convert only errors from explicitly identified **new optional map allocation/admission** operations into `NotAvailable`.

### 8.5 Snapshot cache and concurrency state machine

Use one new `KeywordOrdinalCache` inline in the snapshot. It owns a `Mutex<RegistryState>` and one `Condvar`. Do not generalize/rewrite the established segment-reader cache.

The registry states are:

```text
Uninitialized -> Initializing -> Ready(Registry)
                            -> NotAvailable(ResourceBudget | Allocation)
                            -> Uninitialized on cancellation/error/unwind
```

`Registry` owns a fallibly allocated vector of entries for the canonical schema's eligible fields, in ascending field-ID order, plus its `MetadataReservation`. An entry contains its numeric field ID and one field state:

```text
Empty -> Building -> Ready(Arc<SnapshotKeywordOrdinals>)
                  -> NotAvailable(reason)
                  -> Empty on cancellation/error/unwind
```

The registry is allocated lazily on the first eligible request. Determine the exact eligible-field count from the validated canonical schema, reserve and charge its vector once, and initialize entries outside the mutex. An initial count pass over schema metadata is permitted so allocation is bounded before it happens; this is not a dictionary or document scan. Store no field-name strings. Find an entry by binary search on its numeric field ID during setup.

Registry initialization first requires every supplied guard's complete `CodecSchema` to equal the first guard's schema. This check occurs once per successful registry construction. Subsequent ready-cache calls already validate the guard binding and need no repeat full-schema comparison.

Only state inspection/transition is inside the mutex. Schema iteration, codec access, cancellation callbacks, budget reservation, vector allocation, dictionary comparison, merge work, and map finalization run outside it. Once an initializer/builder claims its state, an armed RAII guard resets exactly that state and `notify_all()` on every unsuccessful exit/unwind. Successful publication replaces the state with the completed immutable result, disarms the guard, releases the mutex and notifies waiters; no callback can run between publication and disarming. Apply §9.5 for the final cancellation check.

For waiters use `Condvar::wait_timeout` with a fixed 5 ms interval. Recheck the predicate after every wake-up, including spurious wakes. Poll cancellation before waiting and immediately after releasing the returned guard. Never call user cancellation code while holding the cache mutex. A cancelled waiter returns `IndexError::Cancelled` without altering another caller's building state. No spin loop, unbounded untimed wait, global process cache, detached background task, or per-query map construction is permitted.

Readiness is atomic: no partially initialized vector or partially filled map is ever returned. Concurrent successful requests for the same snapshot/field must return `Arc`-identical map owners. Different fields may build concurrently after the registry exists, subject to the same shared metadata budget.

### 8.6 Exact mapping representation and construction

Let `S` be the number of snapshot segments and `Ui` the physical dictionary term count for the field in segment `i`. Compute `T = checked_sum(Ui)`. This is an upper bound on the global distinct term count `U`.

#### 8.6.1 Single-segment and empty cases

For exactly one segment with a new eligible dictionary, bind it on the stack without source/heap/outer-map vectors and publish an identity map with that dictionary's `U0`. It allocates no ordinal array and does not read dictionary terms again: the local codec has already validated strict lexical order and ordinal references. `translate(x)` returns `x` after the ordinary local-range check. The retained map owner itself remains budgeted.

With multiple segments and all `Ui == 0`, publish the zero-term mapped shape with one empty map per segment; there are no heap entries, string reads, or document scans. All value ordinals are out of range; missing/null are handled by the local value-state API and never passed to `translate`.

#### 8.6.2 Shared packed width

For multiple segments use one byte width for every segment:

```text
width = 1                         if T <= 1
width = ceil(bit_length(T-1) / 8) otherwise
```

The width is in `1..=8`. Reuse the codec's crate-visible pure `packed_width(T.saturating_sub(1))` helper. Use the checked upper bound `T`, not an extra pass to discover `U`. This can use a wider entry than an exact-U width when dictionaries overlap, potentially by more than one byte (U=1,T=65537 uses3 instead of1), but avoids a second dictionary merge or rewriting the finished maps. Account the full selected width; do not narrow it after construction.

Retain `Vec<Vec<u8>>`, one inner byte vector per segment. Reserve each inner vector's exact `Ui * width` requested capacity, leave its length zero, and append each rank's low `width` little-endian bytes as that segment's terms emerge from the merge. The local ordinals of each segment emerge in strictly increasing order, so no scatter table or initialization pass is needed.

Do not create a full-width intermediate `Vec<u64>`, a flat second copy, a zero-filled destination then rewrite it, or a document-sized global ordinal array. Do not shrink/repack the vectors after filling. The finished retained payload is approximately `width * T` plus the actual outer vector capacity and map owner.

#### 8.6.3 One streaming k-way merge

1. Bind the eligible field's local column exactly once per segment. Retain only borrowed bound handles for construction. Validate all sources/new-layout availability before producing mapping entries. Genuine legacy input returns the prescribed sticky unavailable result.
2. Read the `Ui` values from validated headers, checked-sum `T`, derive `width`, and preflight all output and scratch capacities before allocating output buffers.
3. Fill one fallibly preallocated vector with reverse-ordered `MergeHead { term: &[u8], segment_index: usize, local_ordinal: u64 }`, containing ordinal zero for each nonempty source. Convert it with `BinaryHeap::from` to heapify in `O(S)` using that same backing allocation. Comparison order is term bytes, segment index, then local ordinal; reverse it so the top is the lexically smallest head. The numeric tie breakers make construction deterministic without influencing equality/rank.
4. Keep `previous_term: Option<&[u8]>`, `next_global: u64`, and a current rank on the stack. Obtain the current head with `peek_mut` and copy its small borrowed descriptor. On the first emitted term or a term differing from `previous_term`, use the next global rank and increment the checked distinct count. Equal byte strings receive the same global rank across every source. Store only the borrowed previous slice, never an owned string.
5. Assert structurally that the destination vector's present entry count equals the emitted local ordinal. Append the rank in the frozen width. If that source has another term, fetch it and replace the current heap head through `peek_mut`, then drop the peek guard for one reheapification. If the source is exhausted, remove that head with `PeekMut::pop`. Do not pop then separately push the next term, perform two heap repairs per entry, rebuild the heap, or scan every segment for the next minimum.
6. Poll cancellation at entry, before each allocation, after every 256 emitted dictionary entries (after dropping any peek guard), and immediately before publication. Source-binding loops also poll at entry and at least every 256 segments. Each individual term is bounded by the codec's maximum keyword length; heap work is bounded by `log S`. No new cancellation poll occurs in `translate`.
7. At EOF, each segment buffer has exactly `Ui * width` bytes; the distinct count is `U <= T`; mapping entries within each segment are strictly increasing. The number of emitted mapping entries is exactly `T`. Finalize the measured retained metadata reservation and publish the complete owner.

This is `O(T log S)` heap comparisons, `O(S)` borrowed construction cursors/heads, and `O(width*T + S)` retained mapping memory. Byte comparison cost also depends on term lengths; do not call it constant time. The builder reads each local dictionary term once for heap admission and does not copy its bytes. Heap comparisons may compare a borrowed term more than once; that is the chosen merge algorithm, not repeated decoding.

`SegmentOrdinalMap::translate` is a single already-bound identity or packed-array operation: check the local ordinal against the segment term count; read its fixed-width entry with checked bounds; expand into a zeroed eight-byte stack array; decode little-endian `u64`. Invalid caller ordinals or impossible map slice bounds use `SegmentError::InvalidColumnGeometry { detail: "global ordinal lookup out of bounds" }`. The positive path must not construct allocated error strings. It performs no schema or column search, UTF-8 validation, heap allocation, string comparison, lock acquisition, or reader reopening.

### 8.7 Memory accounting and lifetime

Reuse the snapshot's existing `MetadataBudget`. No independent unbounded account is permitted. Keep the active-reader `ReaderByteBudget` entirely unchanged: input guards remain admitted for their original lifetime, and mapping preparation does not reserve their encoded bytes a second time.

Account these allocations before requesting them:

| Allocation | Required preflight and retained treatment |
|---|---|
| Registry entries | `E * size_of::<RegistryEntry>()`; retain actual vector capacity in registry reservation |
| Bound-source scratch | `S * size_of::<KeywordOrdinalColumn>()`; reserve during build, release at completion/error |
| Merge heap scratch | At most `S * size_of::<MergeHead>()`; reserve during build, release at completion/error |
| Outer map vector | `S * size_of::<Vec<u8>>()`; retain measured actual capacity |
| Segment map bytes | Each checked `Ui * width`; retain each measured actual capacity |
| Map `Arc` payload | `size_of::<SnapshotKeywordOrdinals>()`, following existing `MetadataMeter::charge_arc` convention |

Every multiplication, addition, width conversion, and `u64`/`usize` conversion is checked. Apply `SegmentLimits::check_allocation_bytes`/`check_alloc` to each backing allocation before reserving it. A bounded valid optional map that cannot fit returns `NotAvailable(ResourceBudget)` rather than changing decoder limits.

Use `MetadataMeter::reserve`, `extend`, `charge_vec`, `charge_arc`, and `finalize`. All vector and heap backing allocations use `try_reserve_exact`. Reserve the small fixed construction allowance first; after validated `Ui` values are known, extend once by the checked total output payload. Scratch allowances remain reserved through construction; finalization retains only the measured finished owner and releases scratch/unused allowance.

Inspect actual capacities after each reservation. If a capacity exceeds the preflight allowance, return `NotAvailable(ResourceBudget)` and drop the candidate; do not silently retain the extra capacity, grow the budget after the unaccounted allocation, or call infallible shrinking to conceal it. A failed `try_reserve_exact` is `Allocation`; configured bounds, arithmetic/capacity limits, and meter admission/finalization failures from this new optional layer are `ResourceBudget`. This origin-based mapping does not intercept authoritative codec errors.

`MetadataReservation` is owned by `SnapshotKeywordOrdinals`, not just the cache entry. An external `Arc` can therefore keep numeric maps alive after snapshot/cache drop without freeing their accounting early. The owner does not retain the snapshot, segment bytes, local readers, dictionaries, or strings. When the final map reference drops, its reservation drops exactly once. Registry accounting drops when the snapshot drops. Use the existing `Arc::new` owner construction convention after budget admission; do not introduce nightly fallible-Arc APIs or a new allocator dependency.

Do not raise limits to make a test pass. Do not add cache eviction, map persistence, sidecar files, background rebuilding, automatic legacy-to-ordinal conversion, or runtime format rewriting in B1.

### 8.8 Acceptance cases for this layer

These are the mandatory B1-G01 through B1-G20 behavior groups. Implement them in the new module's unit tests and the existing snapshot test module; lifecycle acceptance uses the public foundation API.

| ID | Required case and independent expectation |
|---|---|
| B1-G01 | Two dictionaries `["Austin","Seattle"]` and `["Dallas","Seattle"]`; maps must be `[0,2]` and `[1,2]`, global count 3. Verify direct integer comparisons equal independent byte comparisons for every pair. |
| B1-G02 | One dictionary: identity representation, zero map payload, zero builder dictionary-term reads, all translated values identical. Empty dictionary still works. |
| B1-G03 | Multiple empty dictionaries; global count 0, zero heap pushes, missing/null never converted into real value ordinals. |
| B1-G04 | Empty string, ASCII case differences, shared prefixes, embedded NUL if the current keyword contract permits it, composed/decomposed Unicode, non-ASCII values; exact UTF-8 byte equality/order, no locale comparison or normalization introduced. |
| B1-G05 | Deterministic 64-case small dictionary families, up to 5 segments and bounded values; oracle uses test-only `BTreeSet<Vec<u8>>` and rank lookup. It must not call production merge/translation to derive expected ranks. |
| B1-G06 | Many identical dictionaries: all equal values receive equal global ranks, output width still uses T; no duplicated string storage or inverse table. Many disjoint dictionaries: all ranks distinct. |
| B1-G07 | Packed-width boundaries `T=0,1,255,256,257,65536,65537` through builder or bounded helper witnesses as appropriate. Higher widths/arithmetic overflow use pure helper tests without giant allocation. Check little-endian literal bytes. |
| B1-G08 | Physical dictionary contains a deleted-only term; map includes it without document/live-mask access. After compaction a new snapshot may omit it and renumber later terms; held PIT retains exact old mapping. |
| B1-G09 | Two different snapshots with identical committed generation, and two volatile snapshots with `generation=None`, cannot share map identity; mixed/reordered/foreign guard slices are rejected. A map cannot bind a guard from another snapshot. |
| B1-G10 | Eight barrier-synchronized callers prepare the same field; one successful dictionary merge, `Arc::ptr_eq` for every result, no partially ready state. Give the test sufficient active-reader admission for eight independent guard sets. |
| B1-G11 | Different eligible fields build independently; results never cross field identity. Unsupported/nonexistent numeric IDs do not grow the registry. |
| B1-G12 | Cancellation already set on cache miss, hit, single-segment identity, legacy/unavailable, and empty snapshot returns `IndexError::Cancelled` before success/unavailability. Mid-merge cancellation publishes no map and restores empty state. |
| B1-G13 | Deterministically paused builder plus cancelled waiter: waiter returns cancellation while builder remains valid and can publish. Use barriers/channels/test hooks, not a wall-clock performance assertion. Exercise spurious notify and timed-wait recheck. |
| B1-G14 | Injected error and panic during registry initialization and field merge; RAII restores state, releases temporary reservations, wakes waiters. Later independent call may succeed. Injected mutex poisoning fails closed rather than using poisoned contents. |
| B1-G15 | Exact mapping metadata allowance succeeds; one byte below returns sticky `ResourceBudget`; repeat request performs no merge/reservation attempt. After dropping snapshot/map owners, measured accounting returns to the prior level. |
| B1-G16 | Fail each new fallible allocation site through a scoped deterministic test-only fault seam; sticky `Allocation`, no partial maps, all previous reservations released, and a fresh snapshot can attempt again. No production hooks or metrics. |
| B1-G17 | Existing legacy-only and legacy/new mixed snapshots return sticky `LegacySegment`, with zero legacy document scan or on-demand dictionary construction. Ordinary legacy value/search behavior remains covered by the separate codec/lifecycle acceptance. |
| B1-G18 | Corrupt new dictionary, schema disagreement, required-feature/layout mismatch, or invalid local ordinal preserves the original typed error. Never downgrade any into `NotAvailable`. |
| B1-G19 | Keep an external map `Arc`, drop all snapshot/cache owners, and verify its retained metadata charge persists until the final map drop. No ownership cycle remains. Existing reader admission charges release with guards as before. |
| B1-G20 | Structural counters show exactly T map entries appended, at most S heap heads, no output capacity growth after preflight, no document/visibility/stored reads, no second dictionary merge, no owned term bytes, and no map rebuild on ready cache hit. |

Tests that compare performance-related structure must use deterministic counters/capacity observations under `cfg(test)`, not timing thresholds, RSS estimates, or claims of latency gains. In a production library build there are no observation atomics or allocation-failure hooks.

## 9. Additional frozen implementation details

This section closes the details that must not be chosen by the coding agent. It supplements the codec and snapshot designs above.

### 9.1 Validation order and exact errors

Preserve the existing container/checksum/required-feature and earlier metadata error precedence. At the existing COLUMNS validation stage, check new-feature/body agreement before parsing the new body. Read the two-byte version with the existing `ByteReader`; a truncated prefix remains its existing `Truncated` result. A present but unknown COLUMNS version retains `SegmentError::Corrupt { context: "columns version", detail: format!("unsupported {version}") }`. Do not treat an unknown version as legacy. New required-feature version support is checked by the existing feature parser first.

For v2, apply validation in this order: prefix and header inventory; header/schema/layout and directory geometry; dictionary prefix/dimensions/extents; offsets and individual strings; block extents and row references; complete section end. Check arithmetic and bounds before accessing a slice. Within a dictionary, check first offset, each next offset's bounds and monotonicity, that term's length/UTF-8/order, then terminal offset. A negative fixture must violate one intended condition while keeping earlier checks valid. The coding agent must not select whichever error happens to be convenient.

Use `SegmentError::InvalidColumnGeometry { detail }` with these literal static labels for the new checks:

| Condition | `detail` |
|---|---|
| V2 field inventory differs from canonical columnar fields | `column inventory does not match schema` |
| V2 layout does not match eligible/noneligible field rule | `column layout does not match schema` |
| Nonzero v2 reserved header field | `nonzero v2 column reserved field` |
| V2 has no eligible ordinal column | `v2 columns require keyword ordinals` |
| U exceeds the field document count | `keyword dictionary count exceeds document count` |
| U=0 with nonzero L | `empty keyword dictionary has payload` |
| Dictionary extent arithmetic/representability fails | `keyword dictionary extent overflow` |
| Complete dictionary extent exceeds the field/section bytes | `keyword dictionary extent out of range` |
| First dictionary offset is not zero | `keyword dictionary offsets must start at zero` |
| An offset exceeds L | `keyword dictionary offset exceeds payload` |
| A later offset is less than its predecessor | `keyword dictionary offsets descend` |
| Last offset differs from L | `keyword dictionary terminal offset mismatch` |
| Adjacent terms are equal or out of byte order | `keyword dictionary terms are not strictly ascending` |
| V2 column/block ranges have a gap, overlap or wrong origin | `noncanonical v2 column extent` |
| Last v2 extent does not consume the section | `trailing v2 columns bytes` |
| A layout3 block's values length differs from rows×dw | `keyword ordinal slots length mismatch` |
| Illegal layout3 state | `invalid keyword ordinal state` |
| Missing/null row carries a nonzero slot | `stateless keyword ordinal is not zero` |
| Value row carries ordinal >= U | `keyword ordinal out of range` |
| Public dictionary lookup receives ordinal >= U | `keyword dictionary ordinal out of range` |
| Public numeric translation receives out-of-range local ordinal | `global ordinal lookup out of bounds` |

Dictionary prefix reads use contexts `keyword dictionary term count` and `keyword dictionary byte length`. Invalid UTF-8 is `InvalidUtf8 { context: "keyword" }`. A term longer than 65,535 bytes is `LengthMismatch { context: "u16 length prefix", expected: 65535, actual: term_length }`. Configured entry/allocation/decode limits use the existing `LimitExceeded` fields and units. A document ID outside the bound column remains `Corrupt { context: "column", detail: "doc id out of range".to_owned() }`. Do not put raw user strings in errors or construct owned error strings on successful accesses; use lazy factories for owned details.

Shared-map schema disagreement is `IndexError::SchemaMismatch { detail: "keyword ordinal source schemas differ".to_owned() }`. The guard-binding, poison and optional-result errors remain exactly as specified in §8. No new `IndexError` or `SegmentError` variant is authorized; the explicitly prescribed `KeywordOrdinalUnavailable` result enum is part of B1. If the frozen source does not support the prescribed constructor, stop that integration with source evidence.

The standalone COLUMNS parser can accept a v2 payload without a container because it has no feature context. A containing `SegmentReader` must enforce **required** feature membership; listing 0x0010 only as optional is insufficient. V2 with no eligible ordinal column is rejected by the layout/inventory contract, not accepted as an empty format upgrade.

### 9.2 Literal 116-byte wire witness

For B1-U02, use the complete byte string below as an independent literal, not an expected value produced by the encoder. It is the §7 four-row witness, with exactly one column and one block. Whitespace below is presentation only; decode hexadecimal in test setup, or use an equivalent literal byte array.

```text
02 00 01 00 00 00
00 00 00 00 02 03
04 00 00 00 00 00 00 00
01 00 00 00 04 00 00 00
00 00 00 00 00 00 00 00
34 00 00 00 00 00 00 00
24 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00
04 00 00 00
14 00 00 00 00 00 00 00
18 00 00 00 00 00 00 00
04 00 00 00 00 00 00 00
02 00 00 00 00 00 00 00
01 00 00 00 00 00 00 00
00 00 01 62
00 01 03 03
00 00 01 00
```

Absolute ranges: prefix `[0,6)`, field header `[6,52)`, block directory `[52,88)`, U `[88,96)`, L `[96,104)`, offsets `[104,107)`, string bytes `[107,108)`, states `[108,112)`, ordinals `[112,116)`. Assert total length 116. Compare v1's independently calculated total 137, but keep the existing v1 encoder's byte grammar unchanged.

### 9.3 Encoder allocation algorithm

Implement one small **private, column-encoder-local** fallible reservation helper. It accepts the current vector, desired total capacity, the operation's `DecodeBudget`, and `SegmentLimits`. It checks total backing bytes against `max_single_allocation`; reserves only the additional capacity charge against the operation budget; calls `try_reserve_exact(desired_capacity - len)` when desired capacity exceeds present capacity; then reconciles actual capacity. An allocator returning more capacity is charged for the additional actual bytes and rejected if either bound is exceeded. No capacity above a configured bound may be retained or published. Allocation refusal reports `LimitExceeded` in bytes with the relevant allocation limit. On checked overflow report requested `u64::MAX`.

Borrowed occurrence records grow as follows: initial requested capacity `min(8,N)`; thereafter `min(N, max(1, 2*old_capacity))` with checked arithmetic. Grow only when len==capacity. A zero-value field allocates no occurrence backing. Do not reserve N occurrence records merely because N documents exist. States use exactly N requested bytes. New ordinal plan vectors use admitted fallible growth. The public legacy entry point keeps its existing externally observable behavior and bytes; do not silently add new failure timing to that compatibility helper.

Count canonical column fields once to reserve the outer field-plan vector. Retain each field plan's measured geometry needed for final emission; do not allocate a second placement vector if offsets can be stored in those plans. The new encoder's operation budget includes all live new plan/state/occurrence backing, measured retained ordinary block backing, and the one final output. Avoid cloning source field values for ordinary-field encoding as well: pass references to the existing scalar encoder and count writer.

**Frozen ordinary-layout exception:** reuse the baseline layout1/layout2 block-encoding algorithm and its existing scalar `ByteWriter` allocation behavior for noneligible fields. Do not add a second scalar-size/JSON traversal, a budget-aware ByteWriter framework, or a changed scalar wire implementation in B1. At the end of planning each ordinary column, measure and check the actual capacity of its retained block vector plus every retained state/value vector. Charge those live buffers once to the new operation budget before final output admission; do not charge both a moved Vec and its previous owner. Existing temporary legacy offset/value-area construction is not newly pre-admitted by B1. This inherited limitation must be stated in the report; B1 must not claim a comprehensive allocator or peak-memory bound for the old ordinary encoder. It introduces no extra ordinary payload copy beyond that baseline algorithm. If there are no eligible fields, the borrowed-document adapter uses the unchanged legacy encoding path, with no B1 allocation-policy upgrade.

For an ordinary column's retained block vector, measure `capacity * size_of::<BlockPlan>()`; for its state/value vectors measure byte capacity. The outer new field-plan capacity is charged separately once. B1-U09 must build a mixed keyword-single/keyword-multi/I64 case and independently sum these measured retained capacities plus ordinal plans/scratch and final output; the exact sum is admitted and one byte less is rejected before final output allocation. The separate ordinal-only I06 test proves new output pre-admission without any inherited ordinary-buffer ambiguity.

`DecodeBudget` is a conservative capacity model, not an allocator/RSS monitor; internal allocator reallocation bookkeeping and the explicitly retained legacy temporary-buffer behavior are excluded. A released scratch vector is not reused as an excuse to allocate an unbudgeted replacement. No allocation occurs after final output emission starts. Add no generalized arena, allocation framework, dependency, or new public setting.

### 9.4 Logical decode-budget preservation

For a Single ordinal row, locate its raw term once, validate the safe UTF-8 view, then apply the same string allocation/decode checks as the old Keyword scalar path before a fallible owned-string copy. For MultiOne, preserve the old sequence: `check_entries(1)`, `check_alloc::<FieldValue>(1)`, allocate its one-element vector fallibly, then perform the Keyword string's **separate** logical `DecodeBudget` check. The old vector allocation and scalar string allocation are not one combined decode operation. Summing them into a new cumulative limit would change existing acceptance behavior and is prohibited here.

In B1-U13 use an 80-byte ASCII string and limits with section decode budget 80 and single allocation at least `max(80,size_of::<FieldValue>())`; both v1 and v2 MultiOne must succeed. Section budget 79 must fail with requested80. A one-element FieldValue-vector allocation limit one byte below `size_of::<FieldValue>()` must fail before string decoding with that exact requested vector byte count. Construct/validate geometry under ordinary limits first where necessary to isolate **value-access** budget semantics. This is a sibling-API compatibility test, not permission to bypass actual reader admission.

For `keyword_sort_view`, Single retains the existing string budget even though it borrows bytes; MultiOne remains `LegacyDecode`. For `encoded_value_shape`, return legacy-equivalent logical lengths and counts. Do not change `search/typed_compare.rs` to compensate for incorrect codec results.

### 9.5 Single-builder publication and cancellation details

Initialize the registry and claim a field through a short lock transition. Its RAII guard stores only the cache reference plus the numeric entry index/claim kind, never a reference into a Vec across unlock. The registry vector does not move or change length after publication. Cleanup may recover a poisoned guard solely to reset its own Building/Initializing marker and notify waiters; every normal API entry still fails closed on poison and never serves recovered data.

The public preparation wrapper checks cancellation before guard validation, and cancellation must be checked again immediately before returning any Ready or NotAvailable result reached after work/waiting. Release the mutex before invoking the callback. A cancellation observed before publication resets the builder's state; cancellation observed after **any** completed publication, including the caller's own, does not erase that shared successful result. Disarm the build guard immediately after publishing, before the final callback. The cancelling caller returns Cancelled. Builder errors return immediately; they do not loop into another construction attempt.

The one-field map owner includes its snapshot binding, field ID, global term count, per-segment local counts/packed representation and the `MetadataReservation`. Keep per-segment local counts in the chosen representation without allocating an additional redundant count vector: the single identity arm owns its one count, while each packed vector length divided by the common width yields that segment's count. Guards supply the segment index. `SnapshotKeywordOrdinals` owns no string, schema clone, reader, snapshot Arc, storage handle, visibility mask, or global-to-local inverse index.

For a single segment, bind its local column on the stack and avoid allocating the source-handle/heap/outer-map vectors entirely. For multiple segments, preflight exact source and head capacity S, owner and outer-vector payload, then extend the same construction meter by the checked sum of the inner buffers before their allocations. Empty individual buffers allocate no backing. Drop source/heap scratch before finalizing and publishing the retained map reservation. Do not grow a published map.

### 9.6 Existing integration boundaries and cost accounting

The only production COLUMNS writers are `SegmentBuilder::build` and compaction's `build_merged_segment`; both consume the same `EncodedColumns` result. Reuse `ContainerBuilder` checksums/features, `IndexWriter` transaction/rollback, `Directory`, `SegmentStore`/`SegmentCache`, `RemoteIndex`, verified segment cache, and PIT ownership. New maps are disposable in-memory metadata; they have no manifest identity, recovery log, authoritative file or GC action.

Reader open performs new-format dictionary/state/ordinal validation. A cached `open_columns` view borrows its validated geometry. The existing uncached-reader fallback can revalidate when it opens a column view; B1 does not claim to eliminate that existing fallback cost or add another cache. The new map builder binds each source only once per construction, and merge reconstruction opens each source's columns once, so those operations never multiply validation by candidate/document count.

Record these structural costs, not timing claims: encoder occurrence sort `O(V log V)` comparisons plus linear emission; new reader validation `O(U+N)` entries plus dictionary bytes; multi-segment shared construction `O(T log S)` comparisons, each over bounded byte strings; prepared local row lookup and numeric translation constant work; retained shared map payload `width*T` plus measured headers/owner/registry. B1 may reduce COLUMNS bytes substantially for repeated strings, but it does not measure warm-query benefit and does not assert a whole-index percentage.

## 10. Frozen independent corpus and oracle

Use one shared test-only corpus definition in `crates/quervant-core/tests/perf06_b1_common/mod.rs`. It contains the schema and immutable input table below, a document constructor, an input-derived expected-value map, and assertions that consume actual production results. It is not a second codec, searcher, storage backend or global-ordinal implementation. The historical producer in Appendix L deliberately embeds the same literal contract so it can compile without B1 test code.

For each local lifecycle transition, drop the committing writer and open a **fresh** `Index::open_existing` reader from the same Directory/schema/registry before inspecting the new committed snapshot. For a custom-limits fixture use `Index::open_with_limits` with those exact limits; `open_existing` would restore defaults. An Index handle created before later commits is not presumed to refresh its snapshot automatically. Retain old reader/PIT/map owners explicitly for old-view assertions. The helper must verify actual generation and segment counts before any expected rank assertion.

When the test retains a PIT and its map, first call `let pit = reopened.pin()?;` and then `let snapshot = Arc::clone(pit.snapshot());`. Build every guard, local handle, shared map and query for that view from that **same Arc**. Each separate `Index::snapshot()` creates a different ReaderSnapshot binding, and `pin()` obtains its own snapshot; equal generations do not make separately obtained views interchangeable. RemoteIndex exposes the same `pin()`/`PitHandle::snapshot()` pattern. This rule applies to I03, I04, I08 and R01.

### 10.1 Schema, rows and exact ranks

Canonical field IDs are `body=0`, `category=1`, `city=2`, `n=3`, `stored_tag=4`, `tags=5`. Use the precise schema flags and analyzer bindings in §11/Appendix L. Build three real six-document commits. All documents have body `common`; category is `type-a`, `type-b` or `type-c` by batch; n is 0..17; stored_tag is `stored`; tags is Multi([`one`,`two`]).

| Batch | Key | city input state/value | Expected shared ordinal |
|---|---|---|---:|
| A | a0 | Absent | Missing |
| A | a1 | ExplicitNull | Null |
| A | a2 | Single empty string | 0 |
| A | a3 | Single Austin | 2 |
| A | a4 | Single Seattle | 5 |
| A | a5 | Single é, U+00E9 | 10 |
| B | b0 | Single Boston | 3 |
| B | b1 | Single Dallas | 4 |
| B | b2 | Single Seattle | 5 |
| B | b3 | Single e + U+0301 | 9 |
| B | b4 | Single NUL byte | 1 |
| B | b5 | Single 😀, U+1F600 | 11 |
| C | c0 | Single Austin | 2 |
| C | c1 | Single a | 7 |
| C | c2 | Single aa | 8 |
| C | c3 | Single Z | 6 |
| C | c4 | Absent | Missing |
| C | c5 | ExplicitNull | Null |

There are 18 documents, 14 value rows, and 12 distinct raw values. The exact byte order is `["", "\0", "Austin", "Boston", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é", "😀"]`.

| Batch identity | Local dictionary | Exact local→shared vector |
|---|---|---|
| A | `["", "Austin", "Seattle", "é"]` | `[0,2,5,10]` |
| B | `["\0", "Boston", "Dallas", "Seattle", "e\u{301}", "😀"]` | `[1,3,4,5,9,11]` |
| C | `["Austin", "Z", "a", "aa"]` | `[2,6,7,8]` |

Locate each batch/physical document through the actual document keys. Do not assume segment order, generated segment names or physical document positions. Read the source's canonical numeric field IDs once; do not derive them from which fields happen to have values. Reverse the schema declaration list in a paired unit fixture and require the same canonical schema and COLUMNS bytes for the same physical input order.

The keyword normalizer uses NFC for indexed terms, while COLUMNS preserves raw input. Composed/decomposed strings must therefore keep **different value ordinals**, even when their indexed term normalizes identically. Empty string remains a value even though it contributes no keyword posting. This corpus must never be reconstructed from the postings dictionary.

### 10.2 Exact ordinary-query ordering

For city ASC, value-bearing keys are exactly:

```text
[a2,b4,a3,c0,b0,b1,a4,b2,c3,c1,c2,b3,a5,b5]
```

For city DESC, value-bearing keys are exactly:

```text
[b5,a5,b3,c2,c1,c3,a4,b2,b1,b0,a3,c0,b4,a2]
```

Equal values retain logical-key ascending ties in both directions. With missing-first, prepend `[a0,c4,a1,c5]`; with missing-last, append `[a1,c5,a0,c4]`. Missing/null placement does not reverse with direction. Compare complete ordered keys, sort values and total_hits=18 for MatchAll and `Term(body,Text("common"))`; K1 and K10 must equal exact prefixes, and K100 returns all18. Do not compare only sets or per-key score bits.

Use existing query/result types: `SortField::new`, its public `missing` field, `Sort::new`, `TopK::new`, `UnifiedRequest`, `UnifiedSearcher`, `Budgets`, and `CancellationFlag`. For the generic Boolean path use `Query::And([Term(body,common), Range(n, Included(0), Included(17))])`. It must retain the same exact sorted results. Relevance-only ordering is all logical keys ascending for this equal-body corpus; check equality/finite score bits across these identical matches and existing frozen scoring regressions, without inventing a new golden BM25 constant.

Set `request.projection = Projection::Fields(["body","category","city","n","stored_tag","tags"].map(str::to_owned).to_vec())`; compare the returned field list in that requested order. This explicit selected projection includes Absent values; do not substitute the default Source projection, which can omit absent fields. All six fields must match the input `FieldValues` by key, including Absent versus ExplicitNull. Additional predicate membership comes directly from the input table: city Missing→`[a0,c4]`, IsNull→`[a1,c5]`, Exists→all16 keys other than a0/c4, including the two nulls. This is the pinned `typed.rs` behavior (`!values.is_absent()`). For category grouping the three counts are6 each; for n the sum is153 and distinct count18; tags expands to `one` and `two` counts18 each under the existing aggregate API. No new aggregation semantics are introduced.

### 10.3 Deterministic differential generator

Use exactly64 cases numbered0..63, up to5 segments, at most12 rows per segment. The test value alphabet is `["", "\0", "a", "aa", "A", "Austin", "Seattle", "e\u{301}", "é", "😀"]`. For case c choose segment count `1+c%5`; source s has row count `(c+3*s)%13`. Row j selects `(c+7*s+5*j)%13`: 0→Absent,1→Null,2→MultiOne of alphabet[(c+j)%10], otherwise Single of alphabet[(c+s+j)%10]. These constants are frozen; no random crate, time seed or corpus tuning.

The independent oracle gathers the small input strings into test-side `BTreeSet<Vec<u8>>`, collects sorted unique bytes, and binary-searches them for expected ranks. It does not invoke production dictionary ordering/merge/translate to compute expectations. Compare full FieldValues, every local dictionary, every mapped rank and pairwise byte-comparison versus integer-comparison results. Include a separate segment-order permutation of the same inputs. A round trip alone is insufficient.

## 11. Genuine historical compatibility fixture

Generate the complete pre-B1 fixture **before editing production source**, using the exact detached baseline and Appendix L producer. The producer and invocation contract follow this section. They are source-checked, not represented as already executed. B1 must finish this compatibility gate itself; it cannot transfer it silently to B2 or B4.

The frozen fixture package is `crates/quervant-core/tests/fixtures/index/perf06_b1_columns_v1/`. The existing `pr07_pre_norms_v1` fixture remains immutable: its Keyword field is not columnar and cannot substitute for this acceptance. The new package contains exactly the six CURRENT-reachable index objects plus `objects.tsv`, `producer.rs` and provenance `README.md`. No writer lock, stale manifest, target directory or generated binary is committed.

### 11.1 Frozen schema

| Field | ID | Type/cardinality | Indexed / stored / columnar | Binding |
|---|---:|---|---|---|
| body | 0 | Text / Single | true / true / false | standard_folded analyzer |
| category | 1 | Keyword / Single | true / true / true | keyword normalizer |
| city | 2 | Keyword / Single | true / true / true | keyword normalizer |
| n | 3 | I64 / Single | false / true / true | none |
| stored_tag | 4 | Keyword / Single | false / true / false | none |
| tags | 5 | Keyword / Multi | true / true / true | keyword normalizer |

Use `Schema::new(fields,None)` and `AnalyzerRegistry::builtin()`. The current `FieldOptions::indexed_stored()` used for body is not columnar. Do not alter this helper to make a future API easier; historical schema equality depends on these exact options.

### 11.2 One-time baseline producer procedure

Run each command with exit-status checking. Every task path must be absent at first creation; a failed absence check means STOP, not overwrite. If a resumed task already has a verified package with matching source/program/binary/inventory provenance, reuse it after verification and do not regenerate.

```sh
PERF06_B1_REPO_ROOT="$(git rev-parse --show-toplevel)"
PERF06_B1_FIXTURE_TASK="$PERF06_B1_REPO_ROOT/target/perf06-b1-legacy-fixture"
PERF06_B1_BASELINE_TREE="$PERF06_B1_FIXTURE_TASK/baseline-source"
PERF06_B1_BASELINE_TARGET="$PERF06_B1_FIXTURE_TASK/baseline-target"
test ! -e "$PERF06_B1_FIXTURE_TASK"
mkdir -p "$PERF06_B1_FIXTURE_TASK"
git worktree add --detach "$PERF06_B1_BASELINE_TREE" 480a77e78c6897e05cb7ceb76b01434974b82ec6
git -C "$PERF06_B1_BASELINE_TREE" rev-parse HEAD
```

Require the exact pinned SHA. Extract only the single Rust block in Appendix L to `crates/quervant-core/examples/perf06_b1_make_legacy_fixture.rs` in that detached tree. Require SHA-256 `3f04e5eed3679f3d65dd846be9c52259ce2536f7a9776a93cdf4a97f7d44663d`. The baseline tracked worktree remains unchanged; that one supplied example is its only added source. No Cargo/dependency edits.

```sh
CARGO_TARGET_DIR="$PERF06_B1_BASELINE_TARGET" cargo +1.98.1 build --locked --manifest-path "$PERF06_B1_BASELINE_TREE/Cargo.toml" -p quervant-core --example perf06_b1_make_legacy_fixture
rustc +1.98.1 -Vv
sha256sum "$PERF06_B1_BASELINE_TARGET/debug/examples/perf06_b1_make_legacy_fixture"
"$PERF06_B1_BASELINE_TARGET/debug/examples/perf06_b1_make_legacy_fixture" "$PERF06_B1_FIXTURE_TASK/index-work" "$PERF06_B1_FIXTURE_TASK/fixture"
```

Capture the compiler identity, exact command/exit code, stdout/stderr, binary hash before invocation and producer source hash. Exactly one successful fixture-generation invocation is authorized; no regeneration for cosmetic bytes. Require terminal `PERF06_B1_LEGACY_FIXTURE_PASS`, generation3,18docs,3segments and6objects. Both original and packaged index must cold-open and reproduce the complete input-derived city map. The program checks real COLUMNSv1 and absence of feature0x0010.

Copy the generated package to its previously absent tracked destination. Add the verbatim producer and README recording observed baseline/Cargo.lock Git identities, binary/source hashes, toolchain, command and inventory digest. Compare copied objects to `objects.tsv` and original generated bytes once. Every actual digest/path comes from execution; no placeholders in a completed report.

Remove only the task-added example from the detached worktree, verify its tracked/untracked state is clean, then use ordinary `git worktree remove` for that task-owned worktree. No `--force`, global clean, target purge or cleanup of another task. Keeping its build target for diagnostics is permitted. Compile or invariant failure blocks fixture generation and requires an amendment; no hand-edited historical bytes or B1-generated substitute.

### 11.3 Fixture verification and B1-I04 lifecycle

The integration helper locates the package through `env!("CARGO_MANIFEST_DIR")`. Require the exact inventory header `# sha256\tbytes\trelative_path`, six unique object rows, safe relative paths without traversal, matching lengths/digests, and an independently parsed CURRENT/Manifest reachable set equal to the inventory set. Reuse `CurrentPointer::parse` and `Manifest::decode`; never select a latest manifest by directory listing. Copy only `index/` to a fresh test-owned FsDirectory root before writing.

1. Open generation3/18docs/3segments with exact schema. Verify all three columns bodies v1, new feature absent, complete values/search order and `NotAvailable(LegacySegment)`. Retain g3 PIT and five immutable object digests, excluding CURRENT.
2. Append one commit with `d0` city Chicago/category type-d/n18 and `d1` city Seattle/category type-d/n19; other fields follow the common helper. Require generation4/20docs/4segments, three genuine v1 and one v2, feature0x0010/1 on the new segment only. Identify segments by actual features/keys, not position.
3. The mixed snapshot remains `NotAvailable(LegacySegment)`; ordinary reads, queries, projections and aggregates match all20 inputs. Retain g4 PIT and its immutable-object inventory.
4. Run real `IndexWriter::compact()`. Require generation5/20docs/one v2 segment and Ready identity mapping. Exact city dictionary order is `["", "\0", "Austin", "Boston", "Chicago", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é", "😀"]`; category has four independent values type-a..type-d. Check all keys with multiplicity and all state/value/rank mappings.
5. Both held PITs return their full original maps/results. All old immutable g3 and g4 objects remain byte-identical after compaction. CURRENT changes only through actual commits.
6. Drop current writer/index and reopen generation5 in a real child process. The parent passes exact root/mode, asserts process success and a mode-specific terminal marker; the child checks all20 keys/values/ranks and exact query order. A no-environment helper return is not child acceptance evidence.

## 12. Required test matrix and real execution

Stable IDs below are mandatory behavior groups, not optional examples. Name concrete Rust tests with their lower-case ID prefix (`b1_u01_...`, `b1_g01_...`, `b1_i01_...`). A group can have several tests/rows. Do not delete an adversary because another test has the same coverage lines. Tests must use production codecs and lifecycle/query paths; fakes are restricted to the named fault seams and deterministic synchronization.

### 12.1 Codec/access cases

| ID | Cases | Required result |
|---|---|---|
| B1-U01 | N=0, one empty value, all missing, all null, mixed missing/null/empty | Exact distinct count, state and local value; zero dictionary has its one zero offset. |
| B1-U02 | §9.2 literal bytes; all feature/version combinations in §7 | Byte equality and length116; v1 length137; exact containing-reader errors; old required features retained. |
| B1-U03 | Reversed declaration/insertion order; duplicate strings; NUL, Unicode, case and prefixes | Canonical IDs/order and raw-byte distinctness; never normalize column values. |
| B1-U04 | N at block_docs−1/block_docs/block_docs+1 and two-block boundary; U=255/256/257; L=255/256/65535/65536; packed helper through 8-byte maximum | Exact widths, endpoints and document-N single-block access; pure checked-arithmetic tests for enormous dimensions. |
| B1-U05 | Dictionary header truncation, bad U/L, first/descending/terminal/beyond-L offsets, duplicate/out-of-order/invalid UTF-8/overlong term; corrupt unselected term | Exact §9 error at open, no published view; no owned string allocation in validation. |
| B1-U06 | Missing/null nonzero slot; invalid state2/other; ordinal==U/larger; rows×dw mismatch; gaps/overlaps/trailing bytes; malformed zero-doc extent | Exact geometry errors; no sentinel alias. |
| B1-U07 | Wrong source scalar type, zero block_docs, Multi0, Multi2, Empty, 65,536-byte Keyword | Exact validation errors before output publication; same public schema rules remain. |
| B1-U08 | All public ordinary value access plus keyword view and logical encoded shape | Full equality to input-derived FieldValues; numeric/multivalue controls unchanged. |
| B1-U09 | Encoder scratch/output allocation at exact capacity and one-under; all checked overflow branches; allocator refusal | Correct requested-byte units, no duplicate final buffer, no hidden growth, no published partial bytes; mixed-column accounting case required. |
| B1-U10 | §10.3 64-case differential corpus | Every value/state/local dictionary equals independent input oracle; include MultiOne. |
| B1-U11 | Builder/merge parity; no eligible field; all-missing eligible field | Same encoder/flag; no-eligible v1 byte equality; eligible v2 feature even for zero values. |
| B1-U12 | Existing v1 malformed UTF-8 and tight logical-budget fixtures | Legacy value-access timing/assertions unchanged, with explicit v1 input. |
| B1-U13 | Single(x) versus allowed MultiOne(x), including §9.4 limits | Same ordinal, different state; lengths len+2/len+3; MultiOne LegacyDecode; exact old logical budgets. |
| B1-U14 | Real writer accepts noncanonical Multi0 input, then commit reaches the new ordinal encoder | Exact zero-multi rejection before durable publication; never repair into empty/missing or alter Schema. A legacy compaction variant, if present, must reject at source decoding and is not new-encoder coverage. |
| B1-U15 | Structural size witnesses and formula across repeated/high-cardinality/sparse inputs | Exact COLUMNS bytes, per-field `ordinal<=legacy+17`, feature overhead separately4, no whole-index win claim. |
| B1-U16 | Bound-reader and encoder observations | One row/block location per lookup; no field-name/column scan in bound lookup; no cloned input documents/terms; one final output; ordinary merge opens columns once per source. |

Keep direct codec tests in `segment/column.rs`'s new `b1_tests` module and feature/container tests in `segment/reader.rs`/`segment/format.rs` test modules. Integration tests exercise public bound APIs; do not expose private raw readers solely for tests.

For U14's real-writer case use a one-field Keyword/Single schema with `FieldOptions::new(false,false,true)`. Commit one valid document first, record CURRENT/generation/immutable identities, then insert a different key with `FieldValues::Multi(vec![])` and attempt commit. Assert `IndexError::Segment(SegmentError::InvalidColumnGeometry { detail: "zero multi count" })` and that the previous committed state remains readable and unchanged. This columnar-only source ensures indexing/stored decoding cannot mask the intended new-encoder check. Do not inject Multi0 through an allegedly valid committed v2 segment.

### 12.2 Snapshot/global cases

The twenty B1-G groups in §8.8 are mandatory, using exactly the final B1-G01..B1-G20 IDs. Place cache/build tests in `index/keyword_ordinals.rs`; put snapshot-construction/guard-identity fixtures in `index/snapshot.rs` only when private access is necessary. The final execution report maps every group to actual functions/logs.

In addition to those rows, apply the §10 three-batch literal translation table to G01, and the §10.3 generator to G05. G10 uses8 threads with independently acquired ordered guard sets and sufficient **explicit test** reader admission; do not raise production defaults. Synchronize with barriers/channels. Use test-only scoped fault injection for registry allocation, source/heap/outer/inner allocation, error, panic and publication pause; no production fault switches/atomics/telemetry.

G15 distinguishes construction allowance from retained charge: exact **peak modeled allowance** succeeds, one byte below refuses, and final retained accounting excludes released scratch. Independently calculate sizes from the frozen representation and `size_of`/actual capacities; do not call the production accounting helper to create the only expected number. Registry and verified-reader charges are separate pre-existing amounts in the shared account. G19 proves an external map Arc keeps its own reservation alive after snapshot drop; an active reader guard separately retains its original reader charge. No snapshot cycle is permitted.

G20 also starts with a fresh snapshot whose ordinal registry is Uninitialized, runs the existing ordinary query paths, and proves no ordinal registry/build is triggered. Only the explicit preparation call may initialize it. After successful preparation, repeated direct calls on that same snapshot return the identical Arc with zero additional dictionary merge. Protecting the production search diff supplements this behavioral assertion.

### 12.3 Local vertical slices

New target: `crates/quervant-core/tests/perf06_b1_ordinals.rs`. Use real `Index`, `IndexWriter`, `SegmentBuilder`, `ReaderSnapshot`, `UnifiedSearcher`, mutations, compaction and public ordinal API. `MemoryDirectory` is an additional deterministic substrate, not a replacement for the FsDirectory cases.

| ID | Execution | Exact acceptance |
|---|---|---|
| B1-I01 | Build §10 corpus in MemoryDirectory and real FsDirectory | 3commits/18docs/3segments; literal dictionaries/translations; complete values; exact ASC/DESC/missing/K/And/relevance/projection results. |
| B1-I02 | Drop/reopen FsDirectory and actual subprocess | Child executes full18-key/value/ordinal/query checks and terminal marker; no parent's cached index/reader is reused. |
| B1-I03 | Hold original PIT/map; append d0 Chicago; hold new PIT; delete b0 Boston; compact | Append shifts later shared ranks only in new snapshot; pre-compaction physical dictionary still includes deleted-only Boston; after compaction current dictionary omits it, held old PITs unchanged; complete key multiplicities and old immutable digests preserved. |
| B1-I04 | §11 genuine historical fixture lifecycle | g3 v1→g4 mixed→g5 v2; exact optional legacy result before compaction; full20-key/rank/order checks, old PITs and child reopen. |
| B1-I05 | Typed predicates/projection/aggregate and reconstruction | Input-derived exact memberships, group counts and numeric totals; nonstored ordinal values survive compact/upsert; multivalue and numeric layout controls unchanged. |
| B1-I06 | Exact large-dictionary allocation fixture below | Typed final-output failure and unchanged g2; exact-cap success on independent copy; no duplicate dictionary blob. |
| B1-I07 | New malformed COLUMNS wrapped in valid container checksums/digests | Actual SegmentReader rejects inner corruption before any prepared map; include unselected row/term; immutable good generation is untouched. |
| B1-I08 | Public `execute_batch_pinned` pagination with repeated cross-segment values | Concatenated full page sequence equals frozen full sorted list; exact per-slot/envelope PIT/cursor errors and cursor expiry in §12.6; no invented public serializer. |

For I05 use existing aggregation structures from `contract/aggregation.rs` and existing tests, not invented builder methods. Keep all selected projection field states exact. For I03 the deletion changes visibility before compaction; shared mapping must not inspect that visibility. For I08 page size5 across all18 records and both sort directions is fixed: page lengths are5,5,5,3; the final page has `next_cursor=None`. Stop pagination there. Do not send `after=None` as an exhausted follow-up, because that starts a new first page. Verify existing close/drop pin-release behavior separately, without inventing expiration semantics.

The public batch/cursor construction and separate nonstored I05 workload are frozen in §12.6–§12.7; they are required, not optional API choices.

### 12.4 Exact B1-I06 allocation boundary

Use a separate FsDirectory fixture with one field `city`: Keyword, Single, indexed=false, stored=false, columnar=true, no normalizer/analyzer required for a nonindexed field. Documents `p00`..`p15` carry strings `format!("{i:02}") + "x" repeated5998`, exactly6,000 UTF-8 bytes each. Commit p00..p07 then p08..p15 under default limits. Assert generation2,2segments,8docs each, one COLUMNSv2 field and exactly48,138 COLUMNS bytes per source. No postings or stored large values compete with the intended boundary.

After dropping writer/index, retain a full filesystem inventory/digest ledger and make independent test-owned copies for failure and success. Reopen the failure copy with `IndexLimits::default().with_segment_limits(SegmentLimits::default().with_max_single_allocation(65_536))`. Real compaction must return exactly:

```rust
IndexError::Segment(SegmentError::LimitExceeded {
    limit: 65_536,
    requested: 96_187,
})
```

The merged COLUMNS size is `6+46+36+16+17*3+96000+16+16=96187`. A failure requesting96,000 exposes a forbidden duplicate dictionary blob and is a failed test, not an acceptable alternative. Verify CURRENT, generation2, both original segments, manifest/mutation-state identities and complete16 values remain unchanged. Drop the failed writer and acquire a fresh one successfully; do not require an unchanged failed writer object to be reusable if its existing lifecycle contract says otherwise.

Reopen the success copy with max_single_allocation96,187 and the otherwise unchanged default cumulative budget. Compaction must succeed at generation3 with one segment and COLUMNS length96,187. Require complete values and a Ready identity map. This is a source-derived frozen expected boundary; execution must establish it. Any competing unexpected allocation is investigated under the matrix, not accommodated by raising the cap or changing expected requested bytes.

### 12.5 Existing regression preservation

Keep `borrowed_keyword_tests::b_u14_invalid_utf8_rejected` and `b_u18_decode_budget_rejected` on explicit v1 bytes. Keep all existing compatibility fixture objects/digests, A4/A6 results and postings grammars immutable. Add exactly feature0x0010/1 to `pr08_integration.rs::p8_t42_golden_bytes_features_unchanged`'s known-feature allowlist; retain old pairs and versions. First-field COLUMNS **type-tag** corruption remains byte10 because the header width is unchanged; do not mislabel it as field-ID corruption.

For copied-container tests that deliberately install a v1 column body into a newly produced container, remove **only** the new required ordinal feature from that test's reconstructed feature list. Preserve the old intended corruption/assertion and add separate v2 negative coverage. This is allowed only in the paths explicitly listed in §15 after the source pattern is confirmed. No wildcard feature acceptance, broad `.is_err()` replacement or golden rewrite.

The A5 `LimitExceeded { limit:65536, requested:114059 }` assertion is a postings allocation boundary; B1 must not update it for smaller/different COLUMNS. Existing `pr15g_*` column-cache/fallback/PIT tests, `pr15h_b_sort_materialization`, `pr07_compatibility` and `pr15i_d2a_scoring_contract` remain regression gates. A prior experiment's test file does not authorize restoring its rolled-back optimization.


### 12.6 Exact public aggregation and cursor test calls

The following snippets freeze the existing public API path; combine them with the input-derived assertions above. They are source-checked construction instructions, not claims of executed tests.

#### Shared test policy and explicit projection

Use the verified imports from these public paths:

```rust
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::aggregation::{
    Aggregate, Aggregation, AggregationGroupValue, AggregationMetricValue,
    ExactDistinct, GroupBy, GroupKey, NumericAggregate,
};
use quervant_core::contract::batch::{
    BatchBudget, BatchQueryRequest, PerQueryOutcome, QueryRequest,
};
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::capability::CapabilitySet;
use quervant_core::contract::error::{InvalidBatchReason, InvalidQueryReason, QueryError};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::{
    MissingValuePosition, Projection, Sort, SortDirection, SortField, TopK,
};
use quervant_core::contract::value::{FieldValue, Timestamp};
use quervant_core::search::{SearchError, SearchLimits, execute_batch, execute_batch_pinned};

fn b1_batch_policy() -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 16).expect("queries")
            .with(BudgetKind::BatchMemoryBytes, 1 << 30).expect("memory")
            .with(BudgetKind::BatchResponseBytes, 1 << 30).expect("response")
            .with(BudgetKind::BatchAggregate, 1 << 30).expect("work"),
        Budgets::new(), Budgets::new(), Budgets::new(),
    )
}

fn b1_projection() -> Projection {
    Projection::Fields(
        ["body", "category", "city", "n", "stored_tag", "tags"]
            .into_iter().map(str::to_owned).collect(),
    )
}
```

These are explicit test-only budget ceilings, not production default changes. Set `UnifiedRequest.projection` and `QueryRequest.projection` to `b1_projection()` for complete six-field comparisons. Default `Projection::Source` omits absent fields; it does not satisfy the full-field vector assertion.

#### I05 aggregation through the public batch executor

`UnifiedRequest` has no aggregation field. The verified contract path is `QueryRequest.aggregation` plus public `quervant_core::search::execute_batch`. The internal `search::batch` module is private.

Use three requests in one batch over the original 18-row corpus:

```rust
let definitions = [
    Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("category".into())])),
        aggregates: vec![Aggregate::count()],
        ..Aggregation::new()
    },
    Aggregation {
        aggregates: vec![Aggregate::sum("n")],
        exact_distinct: Some(ExactDistinct { field: "n".into() }),
        ..Aggregation::new()
    },
    Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("tags".into())])),
        aggregates: vec![Aggregate::count()],
        ..Aggregation::new()
    },
];
let queries = definitions.into_iter().map(|aggregation| {
    let mut request = QueryRequest::new(Query::MatchAll);
    request.top_k = TopK::new(100).expect("top-k");
    request.projection = b1_projection();
    request.aggregation = Some(aggregation);
    request
}).collect();
let batch = BatchQueryRequest::new(queries, None, BatchBudget::new(16));
let response = execute_batch(
    snapshot.as_ref(), &schema(), &registry(), SearchLimits::default(),
    &batch, &b1_batch_policy(), &CapabilitySet::new(), &CancellationFlag::new(),
).expect("aggregate batch envelope");
```

Here `schema()` and `registry()` are the prescribed B1 common helper, not the old `pr14_common` fixture. For every slot require `response.slot(i)` to match `Some(PerQueryOutcome::Success(slot))`, `slot.total_hits == 18`, and complete hit/projection equality. A successful batch envelope alone is not enough: per-slot errors must fail acceptance.

For slot0 require exactly three groups with components `Value(Keyword("type-a"))`, `Value(Keyword("type-b"))`, `Value(Keyword("type-c"))` and each metrics vector `[Count(6)]`. Compare a test-side map keyed by the literal typed group component; reject missing/extra groups. For slot1 require exactly one global group, empty components, and exact metrics `[Sum(NumericAggregate::Signed(153)), ExactDistinct(18)]`; contract mapping appends the exact-distinct metric after `aggregates`. For slot2 require exactly two groups, components `Value(Keyword("one"))` and `Value(Keyword("two"))`, each metrics `[Count(18)]`. No aggregate names/builders not present in `contract/aggregation.rs` are needed.

Repeat mutated/historical lifecycle expectations from their declared input rows, not the original 18-row constants. The original 19/20-doc variants have different numeric sums and category/tag counts.

#### I08 public PIT-bound cursor path

Use `execute_batch_pinned`, with the same retained `pit` whose snapshot owns the prepared map. For each direction separately choose `MissingValuePosition::Last`, page size5, `Query::MatchAll`, and `b1_projection()`:

```rust
let mut field = SortField::new("city", direction);
field.missing = MissingValuePosition::Last;
let sort = Sort::new(vec![field]);
let mut request = QueryRequest::new(Query::MatchAll);
request.sort = sort.clone();
request.top_k = TopK::new(5).expect("page size");
request.projection = b1_projection();
let batch = BatchQueryRequest::new(
    vec![request.clone()], Some(pit.id().clone()), BatchBudget::new(16),
);
let response = execute_batch_pinned(
    &pit, &schema(), &registry(), SearchLimits::default(), &batch,
    &b1_batch_policy(), &CapabilitySet::new(), &CancellationFlag::new(),
    Timestamp::from_micros(1_000), Timestamp::from_micros(10_000),
).expect("pinned batch envelope");
```

This block is the first-page call; on each next call set `request.cursor` to the preceding successful slot's cloned `next_cursor`, then reconstruct the one-slot batch. Require exactly four pages with lengths `[5,5,5,3]`, `total_hits=18` on every page, first three cursors `Some`, and fourth cursor `None`. Stop at `None`; sending a request with `cursor=None` again starts a new search and cannot be called an exhausted follow-up.

Exact concatenated orders, with missing-last:

- ASC: `[a2,b4,a3,c0,b0,b1,a4,b2,c3,c1,c2,b3,a5,b5,a1,c5,a0,c4]`.
- DESC: `[b5,a5,b3,c2,c1,c3,a4,b2,b1,b0,a3,c0,b4,a2,a1,c5,a0,c4]`.

For each emitted cursor assert `.pit() == pit.id()`, `.last_key()` equals the last key of its page, and `.validate(pit.id(), &sort, Timestamp::from_micros(1_000)) == Ok(())`. Compare all projected values by the input oracle. Do not invent a serializer or access private cursor atoms: `CursorAtom`, `CursorContinuationV1`, `Cursor::continuation_v1`, `Cursor::sort`, and `Cursor::expires_at` are `pub(crate)`. Scope protects `contract/result.rs` and `search/batch_cursor.rs`; their unchanged private Keyword(String)/Missing/Null representation plus existing cursor regression tests establish that B1 adds no numeric cursor representation. No debug-string parsing is allowed.

#### Exact negative cursor outcomes

Retain the first real cursor from `pit_a` at now1000/deadline10000.

1. Open a second index handle on the same generation, call `.pin()` to obtain `pit_b`, and assert same generation/different `binding_id()`. Execute the old cursor using `pit_b` with batch.shared_pit=`Some(pit_b.id().clone())`. The envelope succeeds but slot0 is exactly `PerQueryOutcome::Failure(QueryError::InvalidQuery(InvalidQueryReason::CursorPitMismatch))`.
2. Call `execute_batch_pinned(&pit_b,...)` while batch.shared_pit is `pit_a.id()`. The whole call is exactly `Err(SearchError::Query(QueryError::InvalidBatch(InvalidBatchReason::ConflictingPit)))`.
3. Execute the genuine first cursor against `pit_a` at now10000 with the **new request deadline20000**. The envelope succeeds and slot0 is exactly `PerQueryOutcome::Failure(QueryError::ExpiredCursor)`. The new deadline must exceed now so `InvalidCursorDeadline` does not mask the expired-cursor check. No sleeps or real wall-clock advancement.

PIT handles have no expiry/TTL; only these public cursors have explicit expiry. The existing source witnesses are `tests/pr14a_public_cursor.rs::{t06_wrong_handle_and_snapshot_binding_fail_without_fallback,t08_three_slot_batch_isolates_cursor_failure_in_input_order}` and `search/batch.rs::execute_batch_pinned`.


### 12.7 Nonstored reconstruction and mutation oracle

I05 additionally builds the same18 inputs in a **separate index with a separate schema helper** that changes only `city` to `FieldOptions::new(true,false,true)` and keeps its Keyword/Single/keyword-normalizer contract. All other schema fields remain the §11 definitions; canonical IDs remain unchanged. This separate schema must never open the historical fixture, and the historical helper is not modified.

For this workload project only `["body","category","n","stored_tag","tags"]` in that order. Observe city through the real column-value and local/global ordinal APIs and the city sort; requesting an unstored field in a stored projection is not a new B1 capability. Build three commits, pin the initial snapshot/map, then upsert a3 with a complete replacement document identical to its original except city=`Athens`. Use the existing production upsert operation and commit; the input-derived live key set remains18 and the live value oracle changes only a3's city. Compact normally and reopen. Verify every nonstored city value before and after compaction, exact old PIT city a3=`Austin`, new city a3=`Athens`, full key multiplicity, stored controls and raw dictionaries. No record may silently lose its nonstored column during reconstruction.

The compacted city dictionary is exactly `["", "\0", "Athens", "Austin", "Boston", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é", "😀"]`. The final single segment uses identity mapping. Numeric n values remain0..17 (sum153); category/tags counts remain the base corpus counts. The physical pre-compaction old dictionary can still retain values from shadowed rows; compare its map to the physical source-dictionary oracle, not only the live input set.

Freeze these aggregate/lifecycle totals for the other workloads. Query aggregates are over live matches; global-map rank space is over physical dictionaries until compaction.

| Workload state | Live docs | n sum / distinct | Category counts a,b,c,d | tags one/two counts | City global dictionary |
|---|---:|---|---|---|---|
| Original corpus | 18 | 153 /18 | 6,6,6,0 | 18 each |12 values |
| I03 or R01 after d0 Chicago/n18 | 19 | 171 /19 | 6,6,6,1 | 19 each |13 values |
| I03 after delete b0 Boston/n6, before compact | 18 | 165 /18 | 6,5,6,1 | 18 each |13 physical values, including Boston |
| Same I03 after compact | 18 | 165 /18 | 6,5,6,1 | 18 each |12 values, Boston removed |
| Historical I04 after d0+d1 n18/n19 | 20 | 190 /20 | 6,6,6,2 | 20 each |13 values |

There is no empty type-d group in the original corpus; zero above denotes absent group, not an emitted zero-count result. Independent expected document rows are the authority for each transition. Do not carry the original18-row sum/count constants into the19/20-document cases.

## 13. Real RustFS acceptance topology

### 13.1 Required test and remote assertions

Add `crates/quervant-core/tests/perf06_b1_rustfs.rs`, gated by `#![cfg(feature = "s3")]`, with one ignored test named `b1_r01_cold_shared_ordinals_and_pit`. Follow the existing `pr15g_b_rustfs.rs` runtime, `require_env`, unique-prefix and workspace patterns. Use a real Tokio current-thread runtime on the existing 32MiB test thread pattern; `tests/common::block_on` is not an S3 runtime.

Use real `S3ObjectStore`, `RemoteConfig`, `RemoteKeyPrefix`, `RemoteIndex`, analyzer, writer, immutable objects, reader and query path. This explicitly approved correctness test is the only new RustFS activity in B1; the roadmap's warning against automatic performance/bootstrap campaigns does not prohibit this prescribed real-boundary acceptance.

1. Create a unique prefix `perf06-b1/r01-<pid>-<nanos>` and task-owned workspaces. Build §10's18 documents in three remote commits. Use actual returned commit generations; require1→2→3 and three segments.
2. Capture the remote generation3 CURRENT-reachable immutable keys/digests using the real manifest and existing object-store APIs. Drop the current remote index/writer, and cold-open the same prefix in a **new empty** workspace. Do not remove a workspace still backing an active reader.
3. Verify generation3/18docs/3segments, complete input-derived values, all local/global rank tables, canonical IDs, exact sorted results and projections. Obtain all admitted guards before preparation. Record `transfer_stats().requests()` after materialization, prepare/reuse the map and repeat queries, then require that the request counter is unchanged. Do not add a provider-counting wrapper or a fake store.
4. Hold generation3 snapshot/PIT plus its prepared map. Through the current real remote writer, append d0 Chicago/category type-d/n18 with the common fields and commit generation4. Cold-open generation4 in another empty workspace; require19docs/4segments, new city rank order including Chicago, and original snapshot results/map unchanged. The old snapshot may retain its own local workspace until its owners are dropped.
5. Drop current generation4 readers, cold-open it once more in a third empty workspace and repeat complete19-key/value/rank/order checks. Verify every captured generation3 immutable remote object is byte-identical. This proves actual remote publication/transport/cold decoding, not just local copies.
6. Drop all test-owned owners and remove only their recorded disposable workspaces. For an externally provided service retain the unique remote prefix and record it unless an existing scoped deletion helper can prove it deletes only recorded test-created keys; no new remote cleanup framework. The disposable task-owned container is removed as below, including its anonymous volumes. Never delete another bucket/prefix or authoritative objects still owned by another test.

No remote compaction publication is attempted or qualified. The A6 residual remains explicit. Existing hosted proxy/interruption/corrupt-download/restart suites exercise the unchanged transport/cache code; keep them in ordinary CI. B1-I07 and U05/U06 cover changed inner validation. A fake Directory/store cannot stand in for B1-R01.

### 13.2 Existing service or one task-owned pinned service

If all four `QUERVANT_RUSTFS_ENDPOINT`, `QUERVANT_RUSTFS_BUCKET`, `QUERVANT_RUSTFS_ACCESS_KEY`, `QUERVANT_RUSTFS_SECRET_KEY` are already supplied for this task, use them without logging secrets or managing the service. Region defaults to `us-east-1`. Partial configuration is BLOCKED; do not silently mix existing and default credentials. An endpoint supplied for an unrelated task is not implied authorization to modify that service.

Otherwise use exactly the pinned image:

```text
rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
```

Select `docker` if its local daemon is usable; otherwise `podman` if usable; otherwise mark G6 BLOCKED and continue local work. Do not install a runtime, elevate privileges, change daemon settings or use an unpinned substitute. Verify port127.0.0.1:19010 and name `quervant-perf06-b1-<pid>` are free; a conflict is a blocker, never permission to stop another container. Bind only loopback, with no host mount. Pull only this digest if it is not local and normal network access permits it.

Bind `PERF06_B1_CONTAINER_CLI` to the verified CLI, `PERF06_B1_CONTAINER_NAME` to the unique name and `PERF06_B1_EVIDENCE_DIR` to the task report's evidence directory. The following `run` is the sole authorized service creation:

```sh
PERF06_B1_CONTAINER_ID="$("$PERF06_B1_CONTAINER_CLI" run --detach \
  --name "$PERF06_B1_CONTAINER_NAME" \
  --publish 127.0.0.1:19010:9000 \
  --env RUSTFS_ACCESS_KEY=quervanttest \
  --env RUSTFS_SECRET_KEY=quervantsecret \
  rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c)"
"$PERF06_B1_CONTAINER_CLI" inspect "$PERF06_B1_CONTAINER_ID"
```

Require a successful command and one recorded full container ID before any subsequent management. Capture start/final inspect and logs to task evidence; verify image digest, no host mounts and any image-declared anonymous volume. Health probe `curl -fsS http://127.0.0.1:19010/health` may run at most30 times at2-second intervals; each HTTP attempt has a2-second timeout. Service reachability is required to execute a real test. **Host load, CPU stability and idle-state observations remain advisory and never block this test.** Do not confuse a missing service with performance-host noise.

For this disposable service only, set endpoint `http://127.0.0.1:19010`, region `us-east-1`, bucket `quervant-perf06-b1`, access `quervanttest`, secret `quervantsecret`, then run:

```sh
cargo +1.98.1 test -p quervant-core --all-features --test perf06_b1_rustfs -- --ignored --test-threads=1
```

Capture actual executed test name and `ok`, not just exit0 with zero tests. Whether the test passes or fails, collect diagnostics then stop and remove **only** the recorded task-owned ID, removing its anonymous volumes:

```sh
"$PERF06_B1_CONTAINER_CLI" logs "$PERF06_B1_CONTAINER_ID"
"$PERF06_B1_CONTAINER_CLI" inspect "$PERF06_B1_CONTAINER_ID"
"$PERF06_B1_CONTAINER_CLI" stop "$PERF06_B1_CONTAINER_ID"
"$PERF06_B1_CONTAINER_CLI" rm --volumes "$PERF06_B1_CONTAINER_ID"
```

Use an ID-scoped cleanup trap after successful creation; no wildcard names, `prune`, global volume deletion, image removal, forced kill of unknown processes, or cleanup of user files. Verify that exact container is absent and port released. Cleanup failure is recorded and escalated without widening deletion scope.

### 13.3 Narrow CI registration

Add exactly this one command inside the existing `rustfs` job's `Core remote acceptance (real RustFS)` step in `.github/workflows/ci.yml`:

```sh
cargo test -p quervant-core --all-features --test perf06_b1_rustfs -- --ignored --test-threads=1
```

Keep the existing pinned service, all existing commands/jobs/triggers, health settings and environment unchanged. `tests/rustfs/run.sh` is a scaffold that launches then tears down a service and executes no acceptance tests; it is not the B1 gate.

## 14. Ordered coding procedure

Follow these phases in order. A completed phase is not a permission checkpoint. Start independent prescribed work only under an explicit matrix rule when another gate is blocked.

| Phase | Required actions | Exit evidence |
|---|---|---|
| P0 — source/contract | Perform §2 preflight; freeze plan/source identities, allowed paths and old artifact blobs; attach INV→test table; reconcile source assumptions and matrix. | G0/G1 ledgers; no baseline suite. |
| P1 — historical fixture | Extract verified Appendix L, build baseline example once, generate/verify/package §11 fixture; remove clean detached source worktree. | Program/binary/source/objects provenance and terminal PASS, or exact blocker. |
| P2 — format/local codec | Add feature/version dispatch, derived widths, canonical layout/validation, borrowed-source encoder and bound API; preserve v1 helper. Add U01–U16 cases as each invariant is implemented. | Source review and targeted codec tests. |
| P3 — existing consumers | Integrate build/merge returned feature flag; implement all new ValueSpan consumers and logical budget compatibility; make merge column readers once per source. | Builder/merge/sibling-API exact tests, no search production delta. |
| P4 — snapshot provider | Implement identities, typed preparation outcomes, registry and field state machine, RAII cleanup, identity/packed representations, one heap merge, accounting and public exports. | G01–G20 tests and measured structural observations. |
| P5 — local lifecycle | Execute I01–I08 including genuine fixture, held PITs, exact cap failure, actual child reopen and cursor ordering. | Full input-derived acceptance, exact corruption/error/budget evidence. |
| P6 — real boundary | Implement/run R01 on prescribed real service; register exactly one CI command; perform scoped cleanup. | Actual R01 execution plus remote/cold/PIT/object evidence. |
| P7 — final QA | Complete source/tests/docs, run §17 local ledger once on final executable source, resolve only authorized defects. | Exact source tree, commands/counts/coverage and failure classifications. |
| P8 — delivery | Commit implementation/report; ordinary push and one draft PR; inspect ordinary CI until a terminal result or genuine external blocker. Do not re-dispatch green CI. | Tested/final/remote SHAs, mandatory job results, report ledger. |
| P9 — review | Perform §19 implementation checklist and submit for independent review; maintain draft state. | G9 report complete; G10 maintainer acceptance open. |

Targeted development commands, after the named tests exist:

```sh
cargo +1.98.1 test -p quervant-core --lib b1_
cargo +1.98.1 test -p quervant-core --test perf06_b1_ordinals
```

Run a targeted test when it can resolve a concrete implementation risk. Do not repeatedly run already-green full suites between phases. A targeted test is not a substitute for the final mandatory ledger.

## 15. Allowed files and documentation changes

Existing files below were verified at the pin. Paths explicitly marked NEW are deliberate additions. This is an allowlist, not a suggestion to edit every listed file.

### 15.1 Production source — seven existing files plus one new module

| Path under `crates/quervant-core/src/` | Authorized delta |
|---|---|
| `segment/format.rs` | FEATURE_KEYWORD_ORDINALS0x0010/1 support and exact feature tests; no ByteWriter architecture change. |
| `segment/column.rs` | New wrapper/layout/encoder/parser/bound APIs/shared spans; legacy helper retained; private unit observations/tests. |
| `segment/reader.rs` | New required feature/body dispatch at existing COLUMNS boundary and corresponding private tests. |
| `segment/build.rs` | Use borrowed ordered references/new encoder result/feature; remove columns-only ordered_docs deep clone. |
| `index/merge.rs` | Same encoder/feature, once-per-source column readers after existing guards, focused tests. |
| `index/snapshot.rs` | Inline cache owner/wrapper/guard binding/common-constructor initialization and private tests. |
| `index/mod.rs` | Declare new module and public re-export of the exact prescribed API types. |
| `index/keyword_ordinals.rs` — NEW | Snapshot ordinal cache/maps/builder and G tests only. |

`segment/metadata.rs` may receive documentation-only wording naming both metadata owners, with **no executable delta**. It is a ninth optional documentation path, not permission to change the budget implementation. No `segment/mod.rs` re-export is required: the local APIs are available through existing public `segment::column`.

### 15.2 Tests, fixture and CI

- NEW `crates/quervant-core/tests/perf06_b1_ordinals.rs`, `perf06_b1_rustfs.rs`, `perf06_b1_common/mod.rs`.
- NEW fixture directory `crates/quervant-core/tests/fixtures/index/perf06_b1_columns_v1/` with only the §11 package.
- `crates/quervant-core/tests/pr08_integration.rs`: exact new-feature allowlist pair only.
- `crates/quervant-core/tests/pr15g_a_column_geometry.rs`, `pr15g_b_access.rs`, `pr15h_b_sort_materialization.rs`, `pr15i_d2a_scoring_contract.rs`, `pr07_compatibility.rs`: only necessary, source-proven fixture dispatch/reconstruction changes under D18. No changed semantic expected results, no changed old postings allocation tuple, no test deletion/renaming.
- `crates/quervant-core/src/search/unified.rs`: **test modules only**, and only an explicit v1 container fixture adjustment under D18 if needed. Its production code is protected.
- `.github/workflows/ci.yml`: the single §13.3 command only.

No other existing test or production file is preauthorized. A newly discovered direct v1 reader or required adaptation elsewhere is a matrix HARD STOP for that integration, with the exact source location reported.

### 15.3 Authoritative documentation

| File | Required update |
|---|---|
| `docs/ARCHITECTURE.md` | Required feature and COLUMNSv2 bytes; same-schema field IDs; raw value ordinals; logical budgets; exact snapshot scope and compatibility. |
| `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md` | Optional shared numeric map ownership, existing metadata account, guard identity, concurrency/cancellation/sticky outcomes; no claim about RSS. |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | Add a current B1 amendment: A6 user-accepted/merged baseline; B1 includes snapshot map foundation, B2 collector adoption remains. Preserve historical A6 misses and old status record. |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | Same dependency/current-status reconciliation, gates and review state; B1 not accepted before maintainer review. |
| `docs/ROADMAP.md` | Minimal accurate cross-reference/status for this delivered capability, only after executed gates; no whole PERF-06 DONE. |
| `docs/BENCHMARKING.md` | Brief scope note: B1 correctness/structural sizes only; B4 owns new qualification; host stability advisory for this task; no protocol/threshold change. |
| NEW `docs/pr-artifacts/perf-06-b/PERF06B1_DETAILED_PLAN.md` | Verbatim approved downloaded plan and recorded digest. |
| NEW `docs/pr-artifacts/perf-06-b/PERF06B1_EXECUTION_REPORT.md` and `evidence/` | §18 ledger plus concise relevant raw evidence; no generated target/build/cache payload. |

Current documentation may still say “B1 blocked” in historical A6 text. Add a clearly dated/current-status amendment recognizing the user's merged dependency and this new approved execution plan; do not rewrite the unfavorable evidence. The guide's generic baseline-test recommendation is overridden by this task's no-redundant-baseline rule. Existing unrelated conflict-marker text in `docs/TESTING.md` is not part of B1; do not clean it up here.

### 15.4 Protected scope

Do not change `Cargo.toml`, `Cargo.lock`, toolchains, `.cargo`, AGENTS or authoring-guide policy, schema/public document validation, search production code, storage/remote commit or GC, postings formats, document-key codecs, vector/distributed/service APIs, benchmark framework/config/results, old fixtures, A4/A5/A6 evidence, or any unlisted path. No dependency, unsafe code or new feature flag. Report the actual diff against the admitted source, not merely against the previous local commit.

## 16. Preauthorized Architectural Decisions and Exception-Handling Matrix

Evaluate the exact trigger before acting. AUTO-RESOLVE permits only the listed action. DEFER AND CONTINUE leaves its dependent gate blocked and permits only the independent work named. HARD STOP halts the affected work; unlisted conditions are always HARD STOP under the user's instruction, even if a general guide would allow broader discretion. If several rows apply, use the most restrictive. Ordinary coding fixes within the frozen API/algorithm/semantics are implementation, not redesign.

Each decision-register row records ID, exact observation/source, action, verification, affected gate and escalation owner. “Maintainer” below means the user or their independent reviewer; it never means self-approval by the coding agent.

| ID | Observable trigger/source check | Category | Authorized response | Prohibited response | Evidence / gate / owner |
|---|---|---|---|---|---|
| D01 | Main equals frozen source; worktree clean | AUTO-RESOLVE | Start prescribed branch/plan/fixture without renewed confirmation. | Baseline suite/benchmark for reassurance. | SHAs/status; G0; agent records. |
| D02 | Main advanced by descendant, protected §2 diff empty | AUTO-RESOLVE | Inspect remaining docs, record admitted newer base and unchanged protected blobs. | Ignore policy/source differences. | Full diff/ancestry; G0; agent. |
| D03 | Protected source/authority changed, pin not ancestor, or feature/layout ID occupied | HARD STOP | Preserve work; request smallest source-specific amendment. | Pick another ID, retarget design or silently rebase. | Files/blobs/conflict; G0/G1; maintainer. |
| D04 | Dirty user worktree; clean isolated checkout possible | AUTO-RESOLVE | Create separate clean worktree using normal git workflow. | Stash/reset/delete user work. | Both paths/status; G0; agent. |
| D05 | Existing B1 branch/PR contains work | DEFER AND CONTINUE | Read/reconcile plan/source/evidence; perform independent source review only until ownership is clear. | Overwrite, duplicate PR or discard work. | Existing diff/status map; G0; maintainer. |
| D06 | Exact historical fixture package/provenance exists from this plan | AUTO-RESOLVE | Verify all identities/closure, reuse without generation. | Cosmetic regeneration or overwrite. | Inventory/source/binary/producer hashes; G5; agent. |
| D07 | Fixture destination exists with incomplete/different provenance | HARD STOP | Preserve it; stop fixture/lifecycle gate. Independent new-code unit work may proceed. | Delete, relabel or substitute new-format bytes. | Path/provenance mismatch; G5; maintainer. |
| D08 | Frozen producer hash, compile, or invariant check fails | HARD STOP | Capture exact diagnostic; stop fixture generation. Continue independent P2–P4 only. | Patch supplied producer/output or claim historical compatibility. | Command/hash/diagnostic; G5; maintainer amendment. |
| D09 | Exact baseline object/toolchain/network unavailable | DEFER AND CONTINUE | Use existing authenticated fetch for that object if possible; otherwise block fixture/affected gate. Implementation may continue only if G0 already admitted its actual source; otherwise read-only reconciliation only. | Credentials changes, toolchain substitution, fabricated source. | Tool/object error; G0/G5/G7; maintainer/infrastructure. |
| D10 | Compatible canonical schemas have existing numeric field IDs | AUTO-RESOLVE | Reuse them and bind once. | Global field registry or per-document name lookup in bound access. | Schema tests; G2/G3; agent. |
| D11 | No eligible fields | AUTO-RESOLVE | Exact legacy-v1 path, no new feature. | Unnecessary v2 or empty feature. | Byte differential U11; G2; agent. |
| D12 | Eligible field has no value rows | AUTO-RESOLVE | U=L=0/zero offset/state-only values with zero slots. | Value sentinel or legacy fallback. | U01/U11; G2; agent. |
| D13 | Single schema contains MultiOne | AUTO-RESOLVE | Preserve state4 and old vector/string logical charges. | Normalize to Single or widen sort-view eligibility. | U13/I05; G2/G5; agent. |
| D14 | New ordinal input Multi0/Multi2/Empty/type mismatch | AUTO-RESOLVE | Exact §7/§9 typed rejection before publication. | Schema change or silent repair. | U07/U14 durable state; G2/G5; agent. |
| D15 | Valid new ordinal encoder cannot fit its limits | AUTO-RESOLVE | Exact LimitExceeded/rollback; retain old generation. | Raise limits, alternate codec/retry, unchecked allocation. | U09/I06 exact bytes; G2/G5; agent. |
| D16 | Noneligible ordinary column uses legacy ByteWriter scratch | AUTO-RESOLVE | Apply §9.3 narrow inherited-allocation exception; charge retained buffers before new output; disclose limit. | New scalar sizing/encoding framework or unqualified total-memory claim. | Mixed U09/source diff; G2; agent. |
| D17 | V2 corruption, inventory/layout/feature mismatch, codec limit error | AUTO-RESOLVE | Return authoritative exact typed error; no map publication. | NotAvailable/fallback that hides it. | U05/U06/I07/G18; G2/G3; agent. |
| D18 | Listed old test explicitly installs v1 COLUMNS into new container | AUTO-RESOLVE | Remove only0x0010 from reconstructed required features; keep old intended assertion; add separate v2 case. | Golden edits, loosened error, production search change, remove other features. | Exact before/after helper and legacy body proof; G4/G7; agent. |
| D19 | p8_t42 exact supported-feature allowlist rejects new pair | AUTO-RESOLVE | Add only(0x0010,1). | Unknown-feature wildcard or dropping previous pairs. | Narrow diff; G4/G7; agent. |
| D20 | Unlisted production consumer decodes v1 bytes directly, or prescribed lifetime cannot be implemented safely | HARD STOP | Report exact symbol/borrow conflict; continue independent prescribed tests only. | Unsafe lifetime, duplicated full reader or ad hoc API. | Source/counterexample; G2/G3; maintainer. |
| D21 | Eligible snapshot contains genuine legacy columns | AUTO-RESOLVE | Sticky LegacySegment; ordinary queries continue. | Transient dictionary/doc scan or implicit rewrite. | G17/I04; G3/G5; agent. |
| D22 | New optional map dimension/budget/actual-capacity admission fails | AUTO-RESOLVE | Sticky ResourceBudget, drop candidate/reservations. | New budget, eviction, retry loop or partial map. | G15 and accounting; G3; agent. |
| D23 | New optional map try_reserve_exact fails | AUTO-RESOLVE | Sticky Allocation, drop candidate/reservations. | Downgrade unrelated decoder errors or retry. | G16 fault-site ledger; G3; agent. |
| D24 | Cancel/error/unwind before publication; cancelled waiter | AUTO-RESOLVE | Exact reset/notify/caller error; preserve another builder and already-published maps. | Stuck Building or erase completed map. | G12–G14 barriers; G3; agent. |
| D25 | Wrong snapshot guards, schema mismatch, poisoned cache | AUTO-RESOLVE | Exact typed errors and fail closed. | Remap by names or serve poisoned state. | G09/G18; G3; agent. |
| D26 | Append/delete/refresh/compaction changes shared rank numbers | AUTO-RESOLVE | New snapshot builds separate map; old PIT exact. | Permanent-ID promise or mutate old map. | G08/G09/I03; G3/G5; agent. |
| D27 | Request appears to require durable cross-snapshot/global-index IDs or Multi/Text ordinals | HARD STOP | Report scope expansion for design amendment. | Extend wire/cursors/schema/distributed registry. | Requirement conflict; G1; maintainer. |
| D28 | Performance gain requires switching collectors or benchmarking | DEFER AND CONTINUE | Finish B1 foundation correctness; record B2/B4 dependency. | Production comparator change, acquisition, retune or win claim. | Protected diff/report; G9; maintainer for future plan. |
| D29 | All prescribed RustFS env supplied or task-owned pinned runtime available | AUTO-RESOLVE | Run §13 topology once per final relevant source; ID-scoped cleanup. | Unpinned/external substitute, another task's service management. | R01 logs/digest/ID; G6; agent. |
| D30 | RustFS infrastructure/env/name/port unavailable or health cannot pass | DEFER AND CONTINUE | G6 BLOCKED; continue local code/tests/QA/report. | Mock PASS, stop another service or expand cleanup. | Exact service error; G6; infrastructure/maintainer. |
| D31 | Host stability/load probe noisy, missing or not run | AUTO-RESOLVE | Record advisory observation or NOT OBSERVED and proceed. | Block correctness, alter thresholds or claim host caused results. | Informative report only; no gate; agent. |
| D32 | Mandatory gate fails on changed source within frozen contract | AUTO-RESOLVE | Diagnose and fix implementation defect; rerun affected gates. | Weaken test, add ignore/exclusion or redefine semantics. | Failing input/trace/fix/test; affected gate; agent. |
| D33 | Gate claimed pre-existing/flaky/infra without evidence | HARD STOP acceptance | Classify with §17 taxonomy; one minimal baseline reproduction allowed if needed. Independent prescribed work may continue. | Declare unrelated/pass based on speculation. | Comparative/source/infra evidence; G7/G8; reviewer. |
| D34 | CI pending/service unavailable at handoff | DEFER AND CONTINUE | Finish local report; report verification blocked, exact pending jobs. | Green claim, extra workflow dispatch/cancel/repeated push. | Run/head/job identities; G8; infrastructure. |
| D35 | Source/tests/CI changed after QA | AUTO-RESOLVE | Determine affected required gates from changed paths and rerun them; all-feature/default where applicable. | Transfer old evidence to changed executable source. | Diff/tested/final identities; G7/G8; agent. |
| D36 | Only report/plan prose changed after validated source | AUTO-RESOLVE | Prove protected executable/test/CI diff empty; diff-check and retain prior source QA. | Repeat full local suites solely for prose or claim new CI passed unseen. | Exact source-object comparison; G7/G9; agent. |
| D37 | Need edits outside allowlist, dependencies, storage publication, unsafe code or existing budget semantics | HARD STOP | Preserve working state and request narrow amendment. | Self-authorize expansion. | File/symbol/reason; affected gate; maintainer. |
| D38 | Cleanup of task-owned ID fails | DEFER AND CONTINUE | Record exact remaining ID/resource, preserve diagnostics, continue reporting. | Broad prune/kill or delete authoritative unrelated data. | Cleanup log; G6/G9; infrastructure/maintainer. |
| D39 | Any new condition not covered above | HARD STOP | Halt affected work; describe input, source, invariant, impact and minimum amendment. | Generalize AUTO rule or invent architecture. | Decision register; affected gate; maintainer. |

## 17. Verification commands and failure classification

### 17.1 Final local ledger

Trust merged main as the healthy starting point. Do **not** run this ledger on the unmodified baseline. Run it once after the final B1 source/tests/CI change, with the already pinned toolchains. These commands are the repository's required local evidence; ordinary CI is additional evidence, not a substitute. Do not upgrade tools/dependencies to avoid a failure.

```sh
cargo +1.98.1 fmt --all -- --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.98.1 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.98.1 test --workspace --all-targets
cargo +1.98.1 test --workspace --all-targets --all-features
cargo +1.98.1 llvm-cov --workspace --all-targets --fail-under-lines 85
cargo +1.98.1 llvm-cov --workspace --all-targets --all-features --fail-under-lines 85
cargo +1.98.1 doc --workspace --no-deps
cargo +1.98.1 doc --workspace --all-features --no-deps
cargo +1.98.1 bench --workspace --no-run
bash benchmarks/scripts/test-scripts.sh
cargo +1.85.0 fmt --all -- --check
cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings
cargo +1.85.0 test --workspace --all-targets --all-features
git diff --check
```

This selects the current CI-equivalent MSRV all-features topology rather than inventing additional variants. Default and all-features line coverage must each be at least85%, with actual percentages recorded and no new exclusions. `bench --no-run` is a compilation gate, not a benchmark acquisition. The baseline fixture example is built once separately under §11; it does not rerun baseline suites. Do not create a Python/shell/framework test campaign beyond the existing script ledger and ordinary CI.

Capture command, working/source revision, toolchain, flags, actual exit code, actual counts/coverage and log path. Do not predict counts from A5/A6. A pipeline must preserve the tested command's failure status (`pipefail` if using tee); a successful log writer is not a passing test. Report all skipped/unexecuted gates as NOT RUN or BLOCKED with the actual reason.

Formatting fixes inside authorized Rust paths are routine implementation fixes; a workspace formatter must not leave unrelated files modified. Isolate only allowed changes. For a source correction after a failure, rerun its affected targeted tests and every mandatory source-dependent gate invalidated by the change. Once source QA is sufficient, stop optional repetition. A final report-only commit needs an executable/test/CI-source comparison and diff-check, not another complete local suite.

### 17.2 Ordinary CI

Use the repository's ordinary draft-PR workflow. Current required jobs are `rust`, `msrv`, `rustfs`, `python-benchmark-framework`, and `benchmark-adapter-contract`. Do not disable jobs, change their triggers, manually dispatch, cancel, rerun green jobs, or split implementation into interim pushes merely to get repeated CI.

Finish local source/tests/docs first, then ordinary push and open/update the draft PR. Inspect the exact head/run/jobs. To claim G8 PASS, every required job must actually pass for the declared final executable source, and the RustFS log must show B1-R01 executed successfully. If the final head differs only by report/plan prose, record both source identities and the newly observed CI status without pretending unseen success; maintainer branch policy still governs the actual merge head.

Do not hold completed coding work hostage to an unavailable CI service: finish the report under `PERF06_B1_IMPLEMENTED_VERIFICATION_BLOCKED` with exact pending/blocked jobs. This is an honest incomplete acceptance state, not authority to skip the gate. The agent need not ask permission merely to continue prescribed safe work.

### 17.3 Failure taxonomy

| Classification | Evidence required | Disposition |
|---|---|---|
| B1 implementation defect | Reproducible failure tied to changed source or violated frozen invariant | Fix within scope, retain regression and rerun affected gates. |
| Pre-existing failure | Concrete source evidence and, when necessary, one smallest relevant reproduction at the pinned baseline under the same conditions | Record both outcomes; mandatory gate stays unresolved until maintainer disposition. Do not run a full baseline suite just for classification. |
| Infrastructure/tooling blocker | Exact missing tool/service/network/credential diagnostic; no semantic substitute available | BLOCKED; continue independent prescribed work. |
| Nondeterministic/unclassified | Failure log/input/source retained; cause not established | Treat as unresolved. No label “flaky” without evidence and no repeated reruns until one happens to pass. |
| Plan/API/design contradiction | Exact source/contract mismatch not covered by AUTO rule | HARD STOP affected work and request smallest amendment. |

Host-load data cannot establish the cause of a correctness failure. No threshold tuning, test exclusion, block pruning, benchmark rerun or evidence deletion is authorized.

## 18. Objective acceptance gates and execution report

### 18.1 Gate ledger

| Gate | PASS requires | If incomplete |
|---|---|---|
| G0 — Source/authority | Admitted main/pin/branch/clean scope, required source reads, exact plan identity and preserved artifact blobs | No dependent production work on an unverified source. |
| G1 — Frozen contract | INV01–INV15 traced to implementation steps/tests, format/API/error/resource states reconciled, all applicable decisions recorded | HARD STOP unresolved contract. |
| G2 — Local representation | Exact format/feature/producer/reader APIs, size/shape contracts, no duplicate keyword representation, approved allocation policy | Implementation incomplete. |
| G3 — Shared snapshot values | Exact identity/cache/merge/optional/cancel/budget/lifetime contracts, no query adoption | Implementation incomplete. |
| G4 — Unit/adversarial evidence | U01–U16 and G01–G20 actually executed with exact literals, independent oracles, negative/boundary/concurrency/cleanup evidence | Correctness gate blocked/failed. |
| G5 — Local lifecycle | I01–I08, genuine legacy package provenance, exact compaction cap, held PITs and actually executed child reopen | Cannot defer compatibility to B2/B4. |
| G6 — Real boundary | B1-R01 executed against prescribed real pinned RustFS, actual cold opens/PIT/publication/unchanged objects, scoped cleanup recorded | BLOCKED if infrastructure missing; no fake PASS. |
| G7 — Final local QA | Every applicable §17.1 command passed on declared source, both line coverages >=85%, no exclusions | Verification blocked. |
| G8 — Mandatory CI | Required jobs pass with exact tested source/run identity and real B1-R01 log evidence | Pending/blocked remains unresolved. |
| G9 — Docs/report/review package | Actual allowed delta, accurate current docs, full report/decision register/residuals, reviewer checklist and draft PR | Delivery incomplete. |
| G10 — Independent acceptance | Maintainer/independent reviewer explicitly accepts B1 and manages merge/dependency promotion | Always maintainer-owned; coding agent cannot self-close. |

G0–G9 PASS permits `PERF06_B1_READY_FOR_INDEPENDENT_REVIEW`. G10 remains open. A source implementation with missing mandatory evidence is `PERF06_B1_IMPLEMENTED_VERIFICATION_BLOCKED`. A design contradiction is `PERF06_B1_HARD_STOP_DESIGN_AMENDMENT_REQUIRED`. Do not call B1 a measured performance success.

### 18.2 Report structure

Write `docs/pr-artifacts/perf-06-b/PERF06B1_EXECUTION_REPORT.md` with these sections, populated by observed facts:

1. Current status, draft PR/branch, gate ledger, maintainer-owned acceptance.
2. Authorization/scope: approved plan hash, source pin, admitted main, healthy-baseline assumption, no acquisition/profiling, host policy advisory.
3. Source/provenance: starting, tested and final SHAs; source-tree comparison; upstream/local/remote verification; exact changed-path allowlist and protected objects.
4. Implemented format and source symbols: feature/version/layout, all producers/consumers, existing field IDs, raw value semantics and public APIs.
5. Memory/algorithm audit: borrowed occurrences and one output, measured capacities/formula, inherited ordinary-encoder exception, heap construction and identity fast path, no duplicate strings/doc maps/name lookups, exact retained-metadata accounting.
6. Snapshot state machine: guard binding, registry, concurrency, cancellation, optional-result stickiness, error preservation, PIT/last-Arc lifetime.
7. Historical fixture: source/program/binary/compiler/lockfile identities, one invocation, complete six-object closure and actual hashes, g3→g4→g5 evidence and child execution.
8. Invariant→symbol→test→command/log trace. Every U/G/I/R group appears; coverage percentage does not replace the trace.
9. Local and remote vertical-slice results, full logical counts/order/state assertions, exact I06 error, immutable-object proof, RustFS digest/container/prefix/workspace/cleanup identities and provider request observation.
10. Actual targeted/final local QA commands, flags, toolchains, counts, coverage and exit codes; separate baseline build from B1 tests.
11. CI head/run/job identities and terminal results or exact pending/blocker state; source equivalence for report-only changes.
12. Applied decision rows, unresolved blockers, failure classification, residual correctness/performance risks and owners.
13. Documentation/fixture/evidence integrity and dependency disposition: A6 misses unchanged; B2 query adoption, B3 document identity, B4 measurement; remote compaction publication still not qualified.

Keep useful raw logs/manifests under the new B1 evidence directory; link them from the report. Do not commit target directories, containers, secret env dumps, huge binary logs or unrelated scratch. A changed report must preserve prior unfavorable or failed evidence with an additive correction notice; do not erase it.

### 18.3 Invariant traceability minimum

| Invariant | Implementation sections | Required primary test groups |
|---|---|---|
| INV01 | §7 bound reader, §8 identity | U03/U16, G09/G11, I01 |
| INV02 | §7 layout/encoder, §9 sizes/budget | U02/U09/U15/U16, I06 |
| INV03 | §7 states, §9 logical decode | U01/U07/U13/U14, I05 |
| INV04 | §7 dictionary, §8 merge | U03/U05/U10, G01/G04/G05, I01 |
| INV05 | §7 sibling APIs, §9.4 | U08/U12/U13, I01/I05/I08 |
| INV06 | §7 producer integration | U11, I03/I04/I06 |
| INV07 | §7 parser, §9 errors | U05/U06, G18, I07 |
| INV08 | §8 mapping, §10 oracle | G01/G05/G06, I01/R01 |
| INV09 | §8 identity/lifetime | G08/G09/G19, I03/I04/I08/R01 |
| INV10 | §8 algorithm, §9.5 | G02/G03/G20, U16 |
| INV11 | §8 state machine, §9.5 | G10/G12/G13/G14 |
| INV12 | §8 budgets, §9.3 exception | U09/I06, G15/G16/G19 |
| INV13 | §8 result/error rules | G12/G14/G15/G16/G17/G18 |
| INV14 | §11–§13 real paths | I01–I08, R01, final regression suites |
| INV15 | §1/§3/§15 scope and docs | Protected diff, no acquisition artifacts, G9 review |

### 18.4 Residual risks with fixed disposition

High-cardinality fields can require map payload proportional to the sum of distinct local terms; no string-copy saving makes that free. The existing cap produces sticky optional unavailability. Many held PITs can retain maps and their reservations; G19 verifies release rather than adding eviction. Eager new-format validation adds open-time work proportional to dictionary/rows; B4 measures it separately from query latency. Encoding sorts borrowed occurrences and may consume scratch proportional to value rows; exact limits reject excessive work rather than spilling to a new on-disk algorithm.

Global ranks are intentionally unstable across new snapshots. Legacy/new mixed snapshots remain usable but cannot prepare this shared map until real compaction/rebuild creates all-new eligible columns. Multi-valued fields, Text, JSON strings and permanent shared identifiers remain outside B1. The inherited ordinary-column allocation path is explicitly unchanged apart from borrowing inputs and charging retained buffers before new output admission. No agent may remove these limitations from documentation to imply broader completion.

## 19. Reviewer checklist and next dependency

- [ ] Current source and roadmap were reconciled with the accepted A6 baseline and this user's approval.
- [ ] One required feature and one COLUMNS payload version/layout, with exact bytes and no namespace confusion.
- [ ] Existing canonical field IDs are reused; raw string dictionaries are field-scoped and not normalized postings dictionaries.
- [ ] Public bound APIs borrow admitted immutable bytes safely and perform no hidden per-document name/dictionary scan.
- [ ] All producers and sibling value/shape APIs work; MultiOne and its logical budgets are preserved.
- [ ] Encoder avoids input deep clones, duplicate string pools and doc-sized u64 maps; final output and new scratch are bounded; legacy ordinary exception is accurately documented.
- [ ] Map builder performs one distinct-term heap merge, no document scan or global string copy; one segment uses identity with no vectors.
- [ ] Snapshot/field binding, full ordered guard admission, RAII, cancellation and concurrent once-only publication are proved.
- [ ] New optional allocation outcomes never hide codec corruption/schema mismatch/cancellation; sticky policy is documented.
- [ ] Mapping reservation lives with the last map Arc; no Arc snapshot cycle or double reader charge.
- [ ] Exact independent values/order/ranks, complete key multiplicity, negative checks and exact budget failures actually ran.
- [ ] Genuine old-producer index is read/appended/compacted/reopened in B1; no synthetic legacy substitute or deferred gap.
- [ ] Real filesystem/subprocess and real pinned RustFS/cold/PIT paths executed; provider/object integrity and cleanup evidence exist.
- [ ] Required local QA and CI actually passed or are accurately BLOCKED; no healthy-baseline full rerun or needless prose-triggered local suite.
- [ ] Changed paths stay within allowlist; old fixtures/evidence/benchmarks remain immutable.
- [ ] Docs/report distinguish implemented foundation, unmeasured performance, B2 adoption, B3 identity and B4 qualification.

**B2 handoff:** accepted B1 supplies field IDs, local doc/state/ordinal access, dictionary length-by-ordinal and exact snapshot-wide numeric translations. B2 must design the collector's preparation call, typed NotAvailable fallback, logical admission, comparisons, missing/null/multivalue rules, ties, cursor/PIT behavior and retained value materialization. Do not leak rank numbers into persisted cursors or application identities. B2 is a separate source-specific detailed plan, not automatic work authorized by B1. B3 then owns document-key/duplicate identity, and B4 owns independently reviewed cumulative correctness and a separately approved warm qualification.

B2 must explicitly account for `Index::snapshot()` creating a fresh binding each call. Reuse of one prepared map requires reuse of the same snapshot Arc; repeatedly constructing a new snapshot and map per query cannot be presented as once-per-snapshot reuse across those queries. B1 does not change Index snapshot ownership or introduce a cross-instance/global cache to hide that cost.

## 20. Suggested draft PR description

Use this structure with actual evidence and status; replace every bracketed field before publication. Do not paste invented test results.

```text
Title: PERF-06-B1: persistent keyword ordinals and snapshot-wide value maps

Why
Single-valued keyword columns repeat strings and per-document offsets. Future
numeric collectors also need values from different segments to compare in one
exact snapshot-scoped order.

Changes
- Add required feature 0x0010/1 and COLUMNS v2 sorted raw-value dictionaries with
  compact local document ordinals, preserving missing/null and MultiOne shapes.
- Reuse canonical field IDs, shared column readers and the existing metadata
  budget; expose borrowed local access and one shared numeric map per field and
  snapshot, with identity handling for a single segment.
- Preserve legacy reads and ordinary queries, and verify genuine historical
  append/compact/reopen plus local and real RustFS lifecycle behavior.

Evidence
[tested source / final head / G0–G9 ledger / targeted and final QA / coverage /
 CI run and RustFS execution / historical fixture identities / report link]

Scope and limitations
Collector adoption belongs to B2; document identity to B3; warm qualification to
B4. This PR provides no measured latency or whole-index percentage claim.
Shared ranks are snapshot/field scoped; legacy or bounded-resource cases return
the documented optional capability result. A6 unfavorable evidence is unchanged.

Status
[READY_FOR_INDEPENDENT_REVIEW or precise BLOCKED status]. Draft; maintainer G10
and merge remain open.
```

## Appendix S — Verified source identities and references

The source pin is `480a77e78c6897e05cb7ceb76b01434974b82ec6`; its complete Git tree is `6dca2f1d094704e7e95f94b0a47c6c892aa718a0`.

These are upstream **Git blob IDs**, not SHA-256 hashes of the downloaded plan or local analysis copies. Check them with `git rev-parse <pin>:<path>`. The complete pinned commit is authoritative; this table makes the main design dependencies easy to audit.

| Repository path | Upstream Git blob |
|---|---|
| `AGENTS.md` | `08fcd3dea6e4cd62bde52d597e0a6be7ddf4f39c` |
| `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md` | `c871d370dc050fad9457bfa81a8421dbb846fbf2` |
| `docs/ARCHITECTURE.md` | `8c12444bb6da8454f293a5a35646690e68f40b9d` |
| `docs/architecture/VERIFIED_SEGMENT_READER_REUSE.md` | `e3ee9f181938ffbedd95dde6153b6dd2e441012b` |
| `docs/TESTING.md` | `91c8643eaa041b0cb475949bcefa7c074ae27fe3` |
| `docs/PERF_OPTIMIZATION_ROADMAP.md` | `b5a700605b9d00da77719e923ac1e3ecbda27b23` |
| `docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md` | `11ab74e028a6767294a1ff41c5eb7378757fc901` |
| `docs/BENCHMARKING.md` | `79ab0bf2cbb6074ef791cd8760e9bb444f79d797` |
| `docs/ROADMAP.md` | `dbf0ff977ae06a2541f61f8ef559b1823e50313a` |
| `.github/workflows/ci.yml` | `df63adc43f9f27e1e84e539d00bb2d78361c5c03` |
| `Cargo.toml` | `40bd37bd5314009eeb7b81f201f5ae0180be26f7` |
| `Cargo.lock` | `a230eb28d692c543fd541e7a9eaa0980e678e40e` |
| `rust-toolchain.toml` | `73cb934de4706a914c15e8db2a3c037ce75699d9` |
| `crates/quervant-core/src/segment/format.rs` | `55ca2885def34d6563ab91b9fd81c761f19a3203` |
| `crates/quervant-core/src/segment/column.rs` | `263d40df46f49a546cde88141c01e0e8b6142e17` |
| `crates/quervant-core/src/segment/reader.rs` | `951f08086a8a0225b7fb31195c4db359bd7fda82` |
| `crates/quervant-core/src/segment/build.rs` | `7cf05a09e9453a254febcb7ea10bd957e175b587` |
| `crates/quervant-core/src/segment/metadata.rs` | `4e471b87bc79d7c91f45039775a11ad366a6e7f1` |
| `crates/quervant-core/src/index/merge.rs` | `14754c16254064902fe17753f809565b0c01ec9b` |
| `crates/quervant-core/src/index/snapshot.rs` | `b89230838bfed930d51249a03ca67c6d16be8c90` |
| `crates/quervant-core/src/index/mod.rs` | `e19d522c66a6f3c120d95e87abffbd1b7a931172` |
| `crates/quervant-core/src/contract/schema.rs` | `67478800a1c306f78f168fc1912bb5c2e7eba782` |
| `crates/quervant-core/src/search/typed_compare.rs` | `3ec503103a93d083cd3c3994431e659ce397eaea` |
| `crates/quervant-core/tests/pr08_integration.rs` | `ee4a4f86b8c572749e6a7f499bf64193231fa649` |
| `crates/quervant-core/tests/pr15i_d2a_scoring_contract.rs` | `e5422d8ca8d272ee40f637df7c7a3d1856cd66dd` |

Primary source references:

- [Detailed PR Plan Authoring Guide](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md).
- [Current column codec and readers](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/crates/quervant-core/src/segment/column.rs).
- [Current snapshot cache and admission](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/crates/quervant-core/src/index/snapshot.rs).
- [Metadata accounting implementation](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/crates/quervant-core/src/segment/metadata.rs).
- [Current CI topology](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/.github/workflows/ci.yml).
- [PERF-06 series register](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/docs/pr-artifacts/perf-06/PERF06_SERIES_REGISTER.md).
- [Rejected postings-dictionary size experiment](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/docs/pr-artifacts/pr-15h-e/decision.md). This is not a rejected keyword-column ordinal implementation.
- [Rejected two-pass stream fixup](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/docs/pr-artifacts/pr-15g-c-fixup/performance-qualification.md).
- [Ordinal feasibility source analysis](https://github.com/yduchesne/quervant/blob/480a77e78c6897e05cb7ceb76b01434974b82ec6/docs/pr-artifacts/perf-02-b/PROFILE_REPORT.md). Feasibility is not measured Quervant benefit.
- [Rust 1.85 BinaryHeap implementation/API](https://github.com/rust-lang/rust/blob/1.85.0/library/alloc/src/collections/binary_heap/mod.rs): the prescribed `BinaryHeap::from(Vec)`, `peek_mut`, `PeekMut::pop` and fallible reservation APIs exist at the pinned MSRV; no newer library facility is needed.

## Appendix L — Frozen legacy fixture producer

Extract the following Rust block verbatim, including its final newline, only as prescribed in §11. Source SHA-256: `3f04e5eed3679f3d65dd846be9c52259ce2536f7a9776a93cdf4a97f7d44663d`. The authoring review checked this against pinned public APIs; it was not compiled or executed while writing this plan. The coding agent supplies the actual one-build/one-generation evidence.

```rust
//! Frozen PERF-06-B1 fixture producer: compile only against the pinned pre-B1 source.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{CURRENT_KEY, CurrentPointer, Index, WRITER_LOCK_KEY};
use quervant_core::segment::{Manifest, SectionKind, SegmentLimits, parse_container};
use quervant_core::storage::{Directory, FsDirectory};
use sha2::Digest as _;

const SOURCE_REVISION: &str = "480a77e78c6897e05cb7ceb76b01434974b82ec6";

#[derive(Clone, Copy)]
enum City {
    Missing,
    Null,
    Value(&'static str),
}

const ROWS: [(&str, City); 18] = [
    ("a0", City::Missing),
    ("a1", City::Null),
    ("a2", City::Value("")),
    ("a3", City::Value("Austin")),
    ("a4", City::Value("Seattle")),
    ("a5", City::Value("\u{e9}")),
    ("b0", City::Value("Boston")),
    ("b1", City::Value("Dallas")),
    ("b2", City::Value("Seattle")),
    ("b3", City::Value("e\u{301}")),
    ("b4", City::Value("\0")),
    ("b5", City::Value("\u{1f600}")),
    ("c0", City::Value("Austin")),
    ("c1", City::Value("a")),
    ("c2", City::Value("aa")),
    ("c3", City::Value("Z")),
    ("c4", City::Missing),
    ("c5", City::Null),
];

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "body", FieldType::Text, Cardinality::Single, FieldOptions::indexed_stored(),
            ).with_analyzer("standard_folded"),
            FieldDefinition::new(
                "category", FieldType::Keyword, Cardinality::Single,
                FieldOptions::new(true, true, true),
            ).with_normalizer("keyword"),
            FieldDefinition::new(
                "city", FieldType::Keyword, Cardinality::Single,
                FieldOptions::new(true, true, true),
            ).with_normalizer("keyword"),
            FieldDefinition::new(
                "n", FieldType::I64, Cardinality::Single, FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "stored_tag", FieldType::Keyword, Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
            FieldDefinition::new(
                "tags", FieldType::Keyword, Cardinality::Multi,
                FieldOptions::new(true, true, true),
            ).with_normalizer("keyword"),
        ],
        None,
    ).expect("frozen schema")
}

fn city_values(city: City) -> FieldValues {
    match city {
        City::Missing => FieldValues::Absent,
        City::Null => FieldValues::ExplicitNull,
        City::Value(value) => FieldValues::Single(FieldValue::Keyword(value.to_owned())),
    }
}

fn document(position: usize) -> Document {
    let (key, city) = ROWS[position];
    let mut doc = Document::new(DocumentKey::new(key).expect("key"));
    doc.insert("body", FieldValues::Single(FieldValue::Text("common".to_owned())))
        .expect("body");
    doc.insert("category", FieldValues::Single(FieldValue::Keyword(
        ["type-a", "type-b", "type-c"][position / 6].to_owned(),
    ))).expect("category");
    doc.insert("city", city_values(city)).expect("city");
    doc.insert("n", FieldValues::Single(FieldValue::I64(position as i64)))
        .expect("n");
    doc.insert("stored_tag", FieldValues::Single(FieldValue::Keyword("stored".to_owned())))
        .expect("stored_tag");
    doc.insert("tags", FieldValues::Multi(vec![
        FieldValue::Keyword("one".to_owned()),
        FieldValue::Keyword("two".to_owned()),
    ])).expect("tags");
    doc
}

fn sha256(bytes: &[u8]) -> String {
    let digest = sha2::Sha256::digest(bytes);
    let mut text = String::with_capacity(64);
    for byte in digest.iter() {
        write!(text, "{byte:02x}").expect("write to String");
    }
    text
}

fn verify_fixture(root: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(root)?);
    let index = Index::open_existing(directory, schema(), AnalyzerRegistry::builtin())?;
    assert_eq!(index.generation(), Some(3));
    let snapshot = index.snapshot();
    assert_eq!(snapshot.document_count(), 18);
    assert_eq!(snapshot.segment_count(), 3);
    let expected: BTreeMap<String, FieldValues> = ROWS.iter()
        .map(|(key, city)| ((*key).to_owned(), city_values(*city)))
        .collect();
    let mut actual = BTreeMap::new();
    for segment in 0..snapshot.segment_count() {
        let guard = snapshot.open_segment_reader(segment)?;
        let reader = guard.reader();
        assert_eq!(reader.doc_count(), 6);
        assert_eq!(reader.schema().field_id("city"), Some(2));
        assert!(!reader.required_features().iter().any(|(id, _)| *id == 0x0010));
        let container = parse_container(reader.bytes(), &SegmentLimits::default())?;
        let columns = container.body(SectionKind::Columns).expect("COLUMNS");
        assert_eq!(&columns[..2], &1u16.to_le_bytes(), "genuine baseline COLUMNS v1");
        let keys = reader.doc_keys()?;
        for doc_id in 0..reader.doc_count() {
            let key = keys[doc_id as usize].as_str().to_owned();
            let value = reader.column_value(2, doc_id)?.expect("city column exists");
            assert!(actual.insert(key, value).is_none(), "unique logical key");
        }
    }
    assert_eq!(actual, expected, "complete input-derived city state/value oracle");
    assert!(!root.join(WRITER_LOCK_KEY).exists(), "no active writer lock");
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        return Err("usage: perf06_b1_make_legacy_fixture WORK_ROOT FIXTURE_ROOT (both absent)".into());
    }
    let work_root = PathBuf::from(&args[1]);
    let fixture_root = PathBuf::from(&args[2]);
    if work_root.exists() || fixture_root.exists() {
        return Err("both destination roots must be absent; refusing overwrite".into());
    }
    std::fs::create_dir_all(&work_root)?;
    {
        let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&work_root)?);
        let index = Index::create(directory, schema(), AnalyzerRegistry::builtin())?;
        for batch in 0..3usize {
            let mut writer = index.writer()?;
            for position in batch * 6..(batch + 1) * 6 {
                writer.insert(document(position))?;
            }
            let outcome = writer.commit()?;
            assert_eq!(outcome.generation, (batch + 1) as u64);
            assert_eq!(outcome.segments_added, 1);
        }
    }
    verify_fixture(&work_root)?;

    // Package the complete CURRENT-reachable closure, not stale generations or locks.
    let current_bytes = std::fs::read(work_root.join(CURRENT_KEY))?;
    let current = CurrentPointer::parse(&current_bytes)?;
    assert_eq!(current.generation(), 3);
    let manifest_key = current.manifest_key().as_str().to_owned();
    let manifest_bytes = std::fs::read(work_root.join(&manifest_key))?;
    assert_eq!(manifest_bytes.len() as u64, current.manifest_length());
    assert_eq!(sha256(&manifest_bytes), current.manifest_digest().to_hex());
    let manifest = Manifest::decode(&manifest_bytes, &SegmentLimits::default())?;
    assert_eq!(manifest.segments.len(), 3);
    let mut objects = BTreeSet::from([CURRENT_KEY.to_owned(), manifest_key]);
    for segment in &manifest.segments {
        objects.insert(segment.object_key.clone());
    }
    objects.insert(manifest.mutation_state.as_ref().expect("baseline mutation state").object_key.clone());
    assert_eq!(objects.len(), 6);
    std::fs::create_dir_all(&fixture_root)?;
    let mut inventory = String::from("# sha256\tbytes\trelative_path\n");
    for key in &objects {
        let bytes = std::fs::read(work_root.join(key))?;
        let destination = fixture_root.join(key);
        std::fs::create_dir_all(destination.parent().expect("object parent"))?;
        std::fs::write(&destination, &bytes)?;
        writeln!(inventory, "{}\t{}\t{}", sha256(&bytes), bytes.len(), key)?;
    }
    std::fs::write(fixture_root.join("objects.tsv"), inventory.as_bytes())?;
    verify_fixture(&fixture_root)?;
    println!("SOURCE_REVISION\t{SOURCE_REVISION}");
    println!("FIXTURE_GENERATION\t3");
    println!("FIXTURE_DOCUMENTS\t18");
    println!("FIXTURE_SEGMENTS\t3");
    println!("FIXTURE_OBJECTS\t6");
    println!("INVENTORY_SHA256\t{}", sha256(inventory.as_bytes()));
    print!("{inventory}");
    println!("PERF06_B1_LEGACY_FIXTURE_PASS");
    Ok(())
}
```

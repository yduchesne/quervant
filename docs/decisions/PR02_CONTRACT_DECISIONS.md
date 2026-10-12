# PR 2 — Contract Decision Record (A01–A25)

> **Status: DRAFT — PENDING HUMAN APPROVAL.**
> Every decision below is a **proposal for review**, not approved architecture.
> No public Rust contract may be considered stable, and no segment format may be
> frozen, until each item is marked `APPROVED` with a recorded approval reference.
>
> This record exists because PR 2 stabilizes the typed document/field/query/
> aggregation/batch contracts that PR 5 (codecs) and later PRs depend on.
> Approving it authorizes implementation of the contract-only layer described in
> `TRAWLER_IMPLEMENTATION_PR02_DETAILED_PLAN_V2.md` (PR 2). It does **not**
> authorize any query execution, durable storage, PIT retention, or format freeze.

## How to use this record

1. Review each decision and its proposed choice.
2. Mark each item with one of:
   - `APPROVED` — accept the proposed choice as written;
   - `APPROVED WITH CHANGES` — accept after the noted modification;
   - `REJECTED` — replace with the alternative you select (record it inline).
3. Record the approval reference (issue/PR/comment link, reviewer, date) in the
   table at the end of this section and in the PR description.
4. Until then, the executor must treat PR 2 as `BLOCKED — human contract approval`.

**Approval reference:** _PENDING_ (reviewer / link / date)

## Cross-cutting invariants these decisions must not violate

- `trawler-core` stays standalone: no etcd, RPC, RustFS/S3, vectors, graph or
  cluster imports.
- Logical document keys never equal or depend on segment-local doc IDs.
- Missing, explicit null, and empty multi-value stay distinguishable.
- No implicit type coercion; no silent truncation; no false exact results.
- Budget exhaustion is a typed error, never a partial exact result.
- JSON flattened matches never imply same-element correlation.
- IP/CIDR operations are family-aware binary operations, never text prefixing.
- Contracts describe *shape and validation*; they do not claim execution,
  durability, or PIT retention.

---

## A01 — Stable document key

**Decision:** Canonical representation and validation of the logical document key.

**Proposed choice:** `DocumentKey` wraps a private `String`. It is a nonempty,
opaque, byte-exact UTF-8 sequence, scoped to one logical index. No Unicode
normalization, case folding, trimming, or percent-decoding is applied. Maximum
length 1024 bytes. Identical byte sequences are the same logical document; any
differing byte sequence (including canonically equivalent Unicode) is a distinct
document. External naming (segments, manifests, cache keys) must never derive
logical identity from the key bytes without a collision-free encoding.

**Examples**

```text
ACCEPTED: "user:42", "aGVsbG8=", "Δ", "a\u{0301}"     (as distinct from "á")
REJECTED: ""                        -> InvalidDocument::EmptyKey
REJECTED: 1025-byte value           -> InvalidDocument::KeyTooLong
```

**Alternatives considered:** normalized keys; ASCII-only keys; caller-supplied
`u64` identity; trimming whitespace.

**Rejected because:** normalization/trimming silently merges or splits caller
identity; `u64` identity pushes ID allocation and persistence into the contract
layer and invites collisions across sources.

**Downstream format consequence:** PR 5 must store keys byte-exact and provide a
stable mapping from key bytes to internal doc identity independent of doc IDs.

**Status:** PENDING

---

## A02 — Insert / upsert / delete and revision semantics

**Decision:** Mutation intents, conflict rules, revision assignment, absent-delete,
and retry/idempotency policy.

**Proposed choice:** Three intents: `Insert`, `Upsert`, `Delete`.

- A *writer-assigned* monotonic `u64` revision is returned per applied mutation;
  no caller-supplied revision or sequence number.
- `Insert` on an absent key succeeds; `Insert` on a live key fails with
  `QueryError::Conflict` (duplicate key).
- `Upsert` always succeeds and assigns a new revision.
- `Delete` on a live key succeeds; `Delete` on an absent key is a **successful
  no-op** (idempotent), assigning no revision.
- Retry/idempotency: absent-delete is naturally idempotent. `Upsert` is
  last-writer-wins by writer order. Retried `Insert` of an already-inserted key
  is a `Conflict` and must be resolved by the caller (typically by switching to
  `Upsert`). No client idempotency token is part of v0.1.
- Revision allocation, duplicate suppression, and durability are **writer/PR 6
  responsibilities**; PR 2 defines only the request shapes and response fields.

**Examples**

```text
Insert(key absent)      -> Ok(revision = N)
Insert(key live)        -> Err(Conflict)
Upsert(key any)         -> Ok(revision = N+1)
Delete(key live)        -> Ok(revision = N+1)
Delete(key absent)      -> Ok (no revision)      // idempotent no-op
```

**Alternatives considered:** client-supplied revisions with compare-and-set; a
boolean `create_only` flag instead of `Insert`; absent-delete as an error.

**Rejected because:** client-supplied revisions require a conflict-resolution
contract and CAS semantics the writer does not yet own; absent-delete-as-error
makes retries non-idempotent for event pipelines.

**Downstream format consequence:** PR 6 must define monotonic revision
assignment, delete ordering, and recovery; PR 9 owns tombstone/merge semantics.

**Status:** PENDING

---

## A03 — Field types

**Decision:** The closed set of typed field values supported in v0.1 contracts.

**Proposed choice:**

| Type | Rust value | Notes |
|---|---|---|
| Text | `String` | analyzed at index time (analyzer owned by PR 4) |
| Keyword | `String` | exact normalized term; no stemming |
| Bool | `bool` | |
| I64 | `i64` | signed integer |
| U64 | `u64` | unsigned integer |
| F64 | `f64` | finite only; NaN/±Inf invalid |
| Timestamp | `i64` microseconds UTC | see A13 |
| Json | recursive JSON value | preserves order/null (see A12) |
| GeoPoint | `{ lon: f64, lat: f64 }` | WGS84 (see A14) |
| IpAddress | `std::net::IpAddr` | IPv4/IPv6 (see A07) |
| IpNetwork | `{ addr: IpAddr, prefix: u8 }` | CIDR (see A08) |

Decimal and arbitrary binary/bytes are **deferred**; their absence must not block
the v0.1 format. Extension points are reserved as versioned field types.

**Examples**

```text
ACCEPTED: F64(1.5), F64(-0.0), I64(-9), U64(9), Timestamp(1_700_000_000_000_000)
REJECTED: F64(f64::NAN), F64(f64::INFINITY)  -> InvalidDocument::NonFiniteFloat
```

**Alternatives considered:** arbitrary-precision decimal; fixed "number" with
mixed integer/float; first-class binary blobs.

**Rejected because:** decimals require a codec and rounding contract owned by a
later PR; mixed "number" reintroduces implicit coercion (see A06); binary blobs
are not a v0.1 retrieval target.

**Downstream format consequence:** PR 5 must reserve distinct type tags and an
unknown-required-type failure rule; adding types later must not require rewriting
existing formats.

**Status:** PENDING

---

## A04 — Cardinality and the missing/null/empty distinction

**Decision:** Single vs multi cardinality, and representation of absent, explicit
null, and empty multi-value.

**Proposed choice:** `Cardinality::{Single, Multi}`. Three field states are
distinct and must round-trip:

```text
Absent        : the field is not present on the document
ExplicitNull  : the field is present with the JSON/CBOR-equivalent null
EmptyMulti    : the field is present as a zero-element array (Multi only)
```

`Single` fields accept one scalar or explicit null; a caller array of length >1
is a validation error. `Multi` fields accept zero or more scalars; explicit null
is allowed as the field's value but is not an array element. A null element
inside a multi-value array is rejected (`InvalidDocument::NullArrayElement`).

**Examples**

```text
Single absent         -> Absent
Single explicit null  -> ExplicitNull
Multi absent          -> Absent
Multi []              -> EmptyMulti
Multi [a, b]          -> Present 2 values
Multi [a, null]       -> REJECTED (NullArrayElement)
```

**Alternatives considered:** collapsing null and absent; treating empty array as
absent; allowing null array elements.

**Rejected because:** collapsing loses information required by the EXISTS/
MISSING/IS NULL truth tables (A09); null-in-array creates ambiguous membership.

**Downstream format consequence:** PR 5 must encode presence, explicit-null, and
empty distinctly (for example, a presence/nullable indicator separate from value
count).

**Status:** PENDING

---

## A05 — Field options and invalid combinations

**Decision:** Per-field capability flags and analyzer binding, plus rejected
combinations.

**Proposed choice:** Each field has `indexed`, `stored`, `columnar` booleans,
plus optional `analyzer` (Text only) and optional `normalizer` (Keyword only),
and an index-level optional primary timestamp designation.

Rejected combinations:

```text
all of indexed/stored/columnar false            -> InvalidSchema::UselessField
analyzer bound to non-Text field                -> InvalidSchema::AnalyzerTypeMismatch
normalizer bound to non-Keyword field           -> InvalidSchema::NormalizerTypeMismatch
primary timestamp not Timestamp/Single/indexed  -> InvalidSchema::InvalidPrimaryTimestamp
columnar on Text or Json                        -> InvalidSchema::ColumnarTypeUnsupported
columnar on Multi without an explicit selector  -> deferred check (see A15)
```

Analyzer/normalizer bindings are **opaque identifiers** in PR 2; PR 4 owns their
definitions and compatibility/versioning.

**Examples**

```text
ACCEPTED: Text{indexed:true, stored:true, analyzer:"en_default"}
ACCEPTED: Keyword{indexed:true, columnar:true, normalizer:"lowercase"}
REJECTED: Text{analyzer:"kw"}                    -> AnalyzerTypeMismatch
REJECTED: I64{indexed:false, stored:false, columnar:false} -> UselessField
```

**Alternatives considered:** implicit `stored = indexed`; analyzer identifiers
resolved at query time; a single opaque `options` map.

**Rejected because:** implicit defaults encode policy that callers must see;
late analyzer resolution makes validation non-deterministic; opaque maps defeat
typed validation.

**Downstream format consequence:** PR 5 must serialize the capability flags and
the analyzer/normalizer identifier *and its version* so reindexing implications
are explicit.

**Status:** PENDING

---

## A06 — Numeric equality, ordering, and overflow

**Decision:** Cross-type numeric comparisons and overflow behavior.

**Proposed choice:** No implicit coercion between integer and float, or between
I64 and U64, for equality or membership. A comparison whose field type and RHS
type differ is `QueryError::TypeMismatch`.

- Integer ordering is defined by the mathematical integers: all negative values
  precede all non-negative values; within U64 the natural order applies.
- `F64` comparisons use IEEE-754 ordering restricted to finite values.
- Range bounds must be the same type as the field.
- NaN and ±Inf are invalid as field values and as query bounds.
- Integer arithmetic in aggregations uses checked arithmetic; overflow is
  `QueryError::NumericOverflow` (see A19), never wrapping.

**Examples**

```text
I64 field == I64(-5)          -> ACCEPTED
I64 field == F64(-5.0)        -> REJECTED (TypeMismatch)
U64 field range [0, 10]       -> ACCEPTED
I64 field range [F64(0), ...] -> REJECTED (TypeMismatch)
```

**Alternatives considered:** numeric tower with implicit widening; comparing
I64/U64 via bit reinterpretation; comparing floats and integers by rounding.

**Rejected because:** implicit coercion hides precision loss and makes the
on-disk type contract ambiguous; bit reinterpretation is not a total order.

**Downstream format consequence:** PR 5 stores types immutably and must not need
runtime coercion; numeric DocValues must retain exact integer width.

**Status:** PENDING

---

## A07 — IP normalization and IPv4-mapped IPv6

**Decision:** Address family handling and IPv4-mapped IPv6 policy.

**Proposed choice:** Store native IPv4 (32-bit) and IPv6 (128-bit) separately;
never text-compare. Canonical binary ordering is family-tagged (IPv4 tag `0`,
IPv6 tag `1`), then address bytes. **IPv4-mapped IPv6 (`::ffff:a.b.c.d`) is
preserved as IPv6 by default; it is not silently treated as IPv4.** An explicit
index- or field-level opt-in `normalize_ipv4_mapped` may canonicalize mapped
addresses to IPv4 at ingestion; when disabled (default) families remain distinct.

**Examples**

```text
"A.B.C.D"            -> IPv4 (family separated)
"::ffff:192.0.2.1"   -> IPv6 (default), distinct from "192.0.2.1"
bad literal "1.2.3"  -> InvalidDocument::MalformedIp
```

**Alternatives considered:** always collapsing mapped addresses; always treating
mapped as a separate family with no opt-in.

**Rejected because:** silent collapsing merges distinct identities and violates
the family-awareness invariant; no opt-in prevents legitimate dual-stack
canonicalization.

**Downstream format consequence:** PR 5 requires a family-tagged, byte-comparable
IPv4/IPv6 encoding and a schema flag for mapped normalization; the flag value
must be part of the field/schema version.

**Status:** PENDING

---

## A08 — CIDR semantics

**Decision:** Prefix ranges, host-bit policy, and family mismatches.

**Proposed choice:** IPv4 prefix length `0..=32`; IPv6 `0..=128`. A prefix length
outside range is `QueryError::InvalidCidr` (query) / `InvalidDocument::InvalidCidr`
(field). Host bits set in the network address are **rejected** by the validating
constructor `IpNetwork::new`; callers who want masking use an explicit
`IpNetwork::new_masked`. A membership test between different families is
**`false`**, not an error. Query construction against a field whose type is not
an IP field is `TypeMismatch`.

**Examples**

```text
IPv4 /0    -> matches every IPv4 (not IPv6)
IPv4 /32   -> matches exactly that address
IPv6 /0    -> matches every IPv6 (not IPv4)
IPv6 /128  -> matches exactly that address
192.0.2.1/24 (host bits set) -> REJECTED by IpNetwork::new
192.0.2.1/24 -> 192.0.2.0/24 via IpNetwork::new_masked
v4 field IN v6 network -> false (no error)
```

**Alternatives considered:** silently masking host bits; family mismatch as a
typed error; allowing out-of-range prefixes clamped to family width.

**Rejected because:** silent masking hides caller mistakes; error-on-mismatch
breaks `NOT IN` over mixed data; clamping fabricates a network.

**Downstream format consequence:** PR 5 must store prefix length and canonical
network bytes; prefix comparison must be a byte/bit operation, never textual.

**Status:** PENDING

---

## A09 — EXISTS / MISSING / IS NULL

**Decision:** Definition of the three presence predicates.

**Proposed choice (matches the plan's proposal):**

- `EXISTS` is `true` iff the field is **present** (including explicit null and
  empty multi-value). This makes `EXISTS` the exact complement of `MISSING`.
- `MISSING` is `true` iff the field is **absent**.
- `IS NULL` is `true` iff the field is **explicitly null** (empty multi-value and
  absent are `false`).

| Field state | EXISTS | MISSING | IS NULL |
|---|---:|---:|---:|
| Absent | false | true | false |
| Explicit null | true | false | true |
| Empty array (multi) | true | false | false |
| Value(s) present | true | false | false |

**Examples**

```text
Absent        -> EXISTS false, MISSING true,  IS NULL false
Explicit null -> EXISTS true,  MISSING false, IS NULL true
[]            -> EXISTS true,  MISSING false, IS NULL false
["a"]         -> EXISTS true,  MISSING false, IS NULL false
```

**Alternatives considered:** `EXISTS` = "has a non-null value" (so explicit null
is not EXISTS); `MISSING` = "null or absent"; treating empty array as MISSING.

**Rejected because:** the chosen definitions give callers lossless access to all
three states and make `EXISTS`+`MISSING` a clean partition; the alternatives
conflate states callers must distinguish (A04).

**Downstream format consequence:** PR 5 must persist presence and nullability
independently of value cardinality so all three predicates are answerable.

**Status:** PENDING

---

## A10 — IN / NOT IN and null/missing truth table

**Decision:** Membership semantics and negation over absent/null/empty.

**Proposed choice:** `IN {x}` matches if **any** live value equals a member of
`x` (any-member semantics for multi-value). Explicit-null array elements do not
exist (A04). A type-incompatible RHS is `TypeMismatch`.

`NOT IN {x}` is defined as a **genuine negation only over present, non-null
values**. Absent fields, explicit null, and empty arrays are **not** matched by
`NOT IN` (the membership is "unknown/not applicable"), so they are excluded.

| Field state | IN{x} | NOT IN{x} |
|---|---:|---:|
| Absent | false | **false** |
| Explicit null | false | **false** |
| Empty array | false | **true** |
| Scalar x | true | false |
| Scalar y | false | true |
| Array [x, y] | true | false |
| Array [y, y] | false | true |
| Type-incompatible RHS | typed error | typed error |

**Examples**

```text
absent       IN {"x"} -> false ; NOT IN {"x"} -> false
null         IN {"x"} -> false ; NOT IN {"x"} -> false
[]           IN {"x"} -> false ; NOT IN {"x"} -> true
["y"]        IN {"x"} -> false ; NOT IN {"x"} -> true
["x","y"]    IN {"x"} -> true  ; NOT IN {"x"} -> false
I64 field IN {"x"}              -> TypeMismatch
```

**Alternatives considered:** SQL three-valued logic (absent/null → UNKNOWN, so
`NOT IN` excludes them); total two-valued logic (`NOT IN` = `!IN`, so absent and
null match `NOT IN`); `IN` over null as true.

**Rejected because:** SQL 3VL is a valid alternative but must not be assumed
without approval; total 2VL makes `NOT IN` match missing/null, which the
architecture explicitly warns against. The chosen rule keeps `NOT IN` from
returning missing/null while treating empty arrays as vacuously non-matching.

**Downstream format consequence:** PR 5/execution must be able to distinguish
"present non-null non-matching" from absent/null for negation; the presence
encoding from A09 suffices.

**Status:** PENDING

---

## A11 — JSONPath subset grammar

**Decision:** The exact JSONPath grammar that PR 2 can represent.

**Proposed choice: an RFC 9535-inspired, indexable subset.**

```text
path        := "$" segment*
segment     := "." member
             | "[" quoted-member "]"
             | "[" index "]"
             | "[*]"
member      := ASCII letter/underscore followed by letters/digits/underscore
index       := non-negative decimal integer (no leading '+'/'-')
```

Supported: root, dot/bracket named child, non-negative fixed array index, and a
single-level wildcard `[*]`.

Explicitly **rejected** (typed `QueryError::UnsupportedJsonPath`):

```text
"$..name"          recursive descent ("..")
"$[?(@.x > 1)]"    filter/script selectors
"$[0:2]" "$[::2]"  slices
"$['a','b']"       unions
"$[-1]"            negative indices
"$[(@.length-1)]"  expression selectors
functions/`length()` and similar extensions
```

Wildcard `[*]` is representable but its **correlated** execution is deferred
(A12). PR 2 defines parsing/validation only; no compiler or executor.

**Examples**

```text
ACCEPTED: "$.a.b", "$['a b']", "$.a[0]", "$.a[*]"
REJECTED: "$..a", "$[?(@.x==1)]", "$[1:3]", "$[-1]"
```

**Alternatives considered:** full RFC 9535; a minimal dot-only grammar; storing
raw path strings unvalidated.

**Rejected because:** full RFC 9535 includes recursive/filter features that
cannot be indexed and would imply execution; dot-only cannot express quoted or
array members; unvalidated strings cannot be type-checked.

**Downstream format consequence:** PR 5/11 must persist the parsed segment path
and reserve extension for recursive selectors without changing the meaning of
accepted paths.

**Status:** PENDING

---

## A12 — Nested JSON identity and array ancestry

**Decision:** How structural identity is preserved and what is explicitly not
promised.

**Proposed choice:** The parsed `JsonPath` is the identity of an extracted scalar.
Every extracted value retains its full path ancestry **including array element
indices** (for example `$.events[1].ip`). Multiple values extracted from the same
path are distinct indexed terms. Flattening a document into independent field
postings must **never** be interpreted as proof that values from different paths
belonged to the same array element. Correlated-array predicate execution
(expressing "the same event object has `ip` and `time` matching") is **deferred**;
the contract reserves a structural-identity extension but does not claim it.

**Examples**

```text
{"events":[{"ip":"a","t":1},{"ip":"b","t":2}]}
  $.events[0].ip = "a" and $.events[1].ip = "b"  (ancestry retained)
  A flattened query ip="a" AND t=2 must NOT be treated as satisfied by one element.
```

**Alternatives considered:** discarding array indices; merging same-named nested
paths; implementing correlated extraction now.

**Rejected because:** discarding indices destroys the counterexample; merging
conflates independent arrays; correlated execution is explicitly deferred by the
architecture gate.

**Downstream format consequence:** PR 5 must store array ancestry (or enough to
reconstruct it) and reserve a versioned structural-index capability; PR 11 owns
the source/evaluator path.

**Status:** PENDING

---

## A13 — Timestamps, precision, and time windows

**Decision:** Time representation, precision/rounding, window boundaries, and
invalid ranges.

**Proposed choice:**

- `Timestamp` is a signed 64-bit count of **microseconds since the Unix epoch**,
  always UTC. Offsets in inputs are converted to UTC.
- Sub-microsecond precision is not representable; conversion **floors toward
  negative infinity** so an event can never be rounded *forward* across a
  half-open window boundary.
- Time windows are half-open: `[start, end)`, `start` inclusive, `end` exclusive.
- `start == end` is a valid, empty interval (matches nothing).
- `start > end` is `QueryError::InvalidTimeRange`. Non-representable timestamps
  (outside the i64 microsecond range) are `InvalidDocument`/`InvalidQuery`.

**Examples**

```text
Window [t0, t1): t0 matches, t1 does not
start == end     -> empty (0 matches), no error
start > end      -> InvalidTimeRange
"2024-01-01T00:00:00+02:00" -> UTC-normalized
sub-µs input     -> floored, documented
```

**Alternatives considered:** milliseconds (Lucene-style); nanoseconds; rounding
half-up; inclusive upper bound; rejecting `start == end`.

**Rejected because:** ms loses log precision; ns overflows i64's practical range;
half-up can move events across boundaries; inclusive upper bounds complicate
adjacent windows; rejecting empty intervals needlessly blocks builder code.

**Downstream format consequence:** PR 5 must store microsecond timestamps and
segment min/max bounds; PR 10 owns half-open execution and time buckets.

**Status:** PENDING

---

## A14 — GeoPoint and spatial boundary semantics

**Decision:** Coordinate model, ranges, antimeridian, polygon validation, and
distance units.

**Proposed choice:**

- `GeoPoint` is WGS84 `[longitude, latitude]`; longitude `[-180, 180]`,
  latitude `[-90, 90]`, both finite.
- Bounding boxes: `west <= east` is a normal box; `west > east` denotes a box
  **crossing the antimeridian** (the union of `[west, 180]` and `[-180, east]`).
- Radius: center plus a distance in **meters**; a geodesic metric with documented
  tolerance is used at execution (PR 12); PR 2 validates shape only.
- Polygon: an outer ring of >= 3 distinct vertices plus optional holes; rings may
  be given open or closed (a repeated first/last vertex is normalized); rings
  with < 3 distinct vertices or non-finite coordinates are rejected.
- Boundary inclusion (edge/vertex on a boundary) and self-intersection handling
  are fixed when PR 12 executes; PR 2 records the query shape and validation
  budget only.

**Examples**

```text
ACCEPTED: { lon: -122.4, lat: 37.8 }, bbox west=170 east=-170 (antimeridian)
REJECTED: { lon: 200, lat: 0 }, { lon: 0, lat: 91 }, NaN
REJECTED: polygon with 2 distinct vertices
```

**Alternatives considered:** `[lat, lon]` ordering; degrees for radius;
antimeridian as an error; implicit ring closure with no validation.

**Rejected because:** `[lat, lon]` contradicts GeoJSON/WGS84 convention; degrees
are unit-ambiguous; erroring on antimeridian forbids legitimate queries.

**Downstream format consequence:** PR 5/12 must reserve geo bounds and exact
coordinates; conservative pruning must not produce false negatives at the
antimeridian.

**Status:** PENDING

---

## A15 — Sorting and deterministic ties

**Decision:** Total order, missing/null placement, multi-value selection, and
tie-breaking.

**Proposed choice:**

- Every sorted request is a **total, deterministic order**.
- Missing and explicit-null values are ordered by an explicit
  `MissingValuePosition::{First, Last}`; the default is `Last` for both.
  Missing and explicit null are treated as equal for ordering and are
  disambiguated only by the final tie-break.
- A multi-value sort field **requires an explicit selector**
  `MultiValueSelector::{Min, Max}`; omitting it is `TypeMismatch` (or a dedicated
  `InvalidSort` error). `Min`/`Max` are taken over non-null values; an
  all-null/absent multi-value is treated as missing.
- The final tie-break is always the logical `DocumentKey` in ascending byte
  order, guaranteeing stability across segments and merges.

**Examples**

```text
sort by age asc, default nulls-last, tie on key
sort by tags with Min/Max required
multi-value sort without selector -> InvalidSort
```

**Alternatives considered:** fixed nulls-first; rejecting multi-value sort
entirely; tie-break by segment doc ID (unstable across merges).

**Rejected because:** a configurable but explicit null policy is needed by
callers while remaining deterministic; rejecting multi-value sort is
unnecessarily restrictive; doc-ID tie-breaks break snapshot stability.

**Downstream format consequence:** PR 5 columnar values must select Min/Max over
multi-values and expose missing/null sentinels; cursors (A21) require the full
sort tuple plus the key tie-break.

**Status:** PENDING

---

## A16 — Group-by semantics

**Decision:** Group key typing, multi-value expansion, missing/null groups, and
group ordering.

**Proposed choice:**

- Group-by accepts one or more indexed/columnar scalar keys.
- A multi-value key **expands** the document into one group per distinct value
  (cross-product across multiple multi-value keys), with repeated identical key
  values for one document collapsed first.
- Missing and explicit null form **distinct groups** (using the A04 states);
  they are ordered last.
- Group keys are ordered by a documented canonical typed ordering: type tag,
  then value, with missing before explicit null; ties do not occur because keys
  are distinct.
- A maximum-group budget (A20) is enforced; exceeding it is `BudgetExceeded`,
  never truncation.

**Examples**

```text
doc A tags=[x,y], doc B tags=[y]  -> groups x:{A}, y:{A,B}
absent vs null vs [] on a key     -> absent group, null group, ([] expands to nothing)
group cardinality budget + 1      -> BudgetExceeded
```

**Alternatives considered:** rejecting multi-value group keys; merging null and
missing groups; grouping by frequency order.

**Rejected because:** rejecting multi-value keys removes a required capability;
merging loses state; frequency ordering is non-deterministic under ties.

**Downstream format consequence:** PR 5 must encode typed group keys with
missing/null sentinels; PR 10 owns bounded grouped execution.

**Status:** PENDING

---

## A17 — Exact distinct counts

**Decision:** Distinct scope, per-document duplicates, and null policy.

**Proposed choice:**

- `COUNT(DISTINCT field)` counts distinct values across **live matched documents**
  in the reader/PIT snapshot.
- Per-document duplicate members of a multi-value field count **once** per
  distinct value for that document (per-document membership).
- Explicit null is **excluded** (SQL-like); missing is excluded; empty
  multi-value contributes nothing.
- The distinct set is bounded by the A20 cardinality budget; exceeding it is
  `BudgetExceeded`, never an approximate or truncated count.

**Examples**

```text
doc1 [x,x,y], doc2 [y,z] -> distinct {x,y,z} = 3
explicit null            -> excluded
absent / []              -> contribute nothing
```

**Alternatives considered:** counting occurrences; counting null as a distinct
value; returning approximate counts on overflow.

**Rejected because:** occurrence counting is a different operation and should be
named explicitly if added; including null conflicts with SQL intuition; silent
approximation produces a false "exact" result.

**Downstream format consequence:** PR 5 columnar/set encoding must support
per-document distinct; PR 10 owns execution and the reserved approximate
extension point.

**Status:** PENDING

---

## A18 — Top-K frequent values

**Decision:** Counting unit, tie-breaking, and null policy.

**Proposed choice:**

- Frequency counts **documents containing the value**, once per document per
  distinct value (consistent with A17).
- Results are ordered by count **descending**, then by canonical typed value
  **ascending** as a stable tie-break.
- Explicit null and missing are excluded (consistent with A17).
- The number of distinct keys examined is bounded by the A20 cardinality budget.

**Examples**

```text
values: x in doc1, y in doc1&2, z in doc2 (same count as y) -> y before z
null -> excluded
over budget -> BudgetExceeded
```

**Alternatives considered:** occurrence counting; tie-break by first-seen order;
including null as a group.

**Rejected because:** first-seen order is non-deterministic across segments/merges;
including null is inconsistent with A17; occurrence counting is a distinct
operation.

**Downstream format consequence:** PR 5 requires typed canonical value ordering;
PR 10 owns bounded top-K execution.

**Status:** PENDING

---

## A19 — Aggregates: count/sum/min/max/avg and time buckets

**Decision:** Empty input, overflow, and bucket boundaries.

**Proposed choice:**

- `Count` -> `u64`, empty input -> `0`.
- `Sum` -> integer fields accumulate in `i128` (checked); float fields accumulate
  in `f64` and must remain finite; overflow or non-finite result is
  `QueryError::NumericOverflow`. Empty input -> `Sum(None)`.
- `Min`/`Max` -> same type as the field; empty input -> `None`.
- `Avg` -> `f64`; empty input -> `None`; non-finite result -> `NumericOverflow`.
- Fixed UTC time buckets: bucket width is a positive duration; bucket starts are
  aligned to the Unix epoch by floor division (`floor(us / width) * width`),
  giving half-open `[bucket_start, bucket_start + width)`.
- Aggregation output size is bounded by the A20 budget.

**Examples**

```text
count empty -> 0
sum empty   -> None
avg empty   -> None
sum near i128 overflow -> NumericOverflow
bucket 1m at t = 00:00:30  -> [00:00:00, 00:01:00)
```

**Alternatives considered:** wrapping integer sums; returning `0.0` for empty
avg; timezone-local bucket alignment.

**Rejected because:** wrapping silently corrupts results; `0.0` for empty avg is
ambiguous with a real zero; local alignment is non-deterministic across clients.

**Downstream format consequence:** PR 5 must provide typed columnar values
suitable for checked aggregation; PR 10 owns execution.

**Status:** PENDING

---

## A20 — Resource budgets

**Decision:** Which limits exist, and what happens at zero or exhaustion.

**Proposed choice:** Budgets are explicit, bounded, positive values carried on a
request:

```text
max_json_depth, max_fields, max_array_elements, max_document_bytes,
max_result_window (top-K), max_groups, max_distinct_keys,
max_term_expansion, max_memory_bytes, max_elapsed, max_response_bytes
```

- A budget of `0` is `QueryError::InvalidQuery` at validation time.
- A configured maximum larger than the type can represent is likewise rejected
  at validation; there is no silent "unbounded" sentinel.
- Exceeding any budget during execution is `QueryError::BudgetExceeded { kind }`.
- **No silent truncation.** A budget failure must never be reported as a smaller
  but "exact" result.

**Examples**

```text
max_fields = 0                -> InvalidQuery
max_groups = 10, 11th group   -> BudgetExceeded
top_k = 100 within window     -> Ok
```

**Alternatives considered:** `Option<usize>` with `None` = unbounded; saturating
at `usize::MAX`; returning partial results flagged as truncated.

**Rejected because:** unbounded defaults invite resource exhaustion; a truncation
flag still lets callers treat partial output as complete; explicit positives keep
the contract auditable.

**Downstream format consequence:** none on disk; budgets are request metadata
that PRs 10/14 must enforce.

**Status:** PENDING

---

## A21 — PIT and cursor contracts

**Decision:** Snapshot binding, cursor contents, expiry, and mismatch behavior.

**Proposed choice:** PR 2 defines shapes only; no reader, retention, signing, or
serialization.

- `PitId` is an opaque, caller-visible token identifying a pinned snapshot.
- `Cursor` is opaque bytes that bind: the `PitId`, the complete sort key of the
  last returned document, and the `DocumentKey` tie-break.
- A cursor whose `PitId` is missing/expired is `QueryError::ExpiredCursor`.
- A cursor whose `PitId` mismatches the request's PIT, or whose sort differs from
  the request, is `QueryError::InvalidQuery` (cursor mismatch).
- `PitId` lifetime/expiry is expressed as contract metadata; retention and token
  encoding are later PRs.

**Examples**

```text
cursor(pit A) + request(pit A, same sort)   -> accepted
cursor(pit B) + request(pit A)              -> InvalidQuery (mismatch)
cursor(pit expired)                         -> ExpiredCursor
```

**Alternatives considered:** encoding the full snapshot in the cursor; allowing
cursor reuse across sorts; returning panics on mismatch.

**Rejected because:** embedding the snapshot leaks storage internals and can
grow unbounded; cross-sort reuse produces gaps/duplicates; panics are forbidden.

**Downstream format consequence:** PR 6 owns PIT retention/reopen; PR 14 owns
deterministic search-after. Cursor bytes must remain opaque to clients.

**Status:** PENDING

---

## A22 — Version and capability negotiation

**Decision:** How required/optional capabilities are expressed and rejected.

**Proposed choice:** `Capability` is a stable string identifier with a version.
A request carries `required: Set<Capability>` and `optional: Set<Capability>`. A
server/handshake that does not support a **required** capability returns
`QueryError::UnsupportedCapability { capability }`. Unsupported **optional**
capabilities are ignored (the request proceeds without them). No on-disk format
or cross-version read guarantee is implied.

**Examples**

```text
required: ["regex_query"] unsupported -> UnsupportedCapability
optional: ["hybrid_rrf"] unsupported -> ignored
```

**Alternatives considered:** integer bitfields; silently ignoring all unknown
capabilities; rejecting unknown optional capabilities.

**Rejected because:** bitfields are opaque and unstable; ignoring required
capabilities changes semantics silently; rejecting optional ones defeats their
purpose.

**Downstream format consequence:** PR 5/13 must advertise codec/capability
metadata; unknown *required* segment features must fail explicitly.

**Status:** PENDING

---

## A23 — Projection

**Decision:** What a projection may select and how missing fields behave.

**Proposed choice:** A projection is either `Source` (return the full stored
source document) or `Fields(Vec<String>)` (return named stored fields). It is not
both. No computed expressions, aliases, or restructuring. Requested stored fields
that are absent from a document are **omitted** from that document's result;
fields explicitly stored as null are returned as null. Requesting a field that is
not stored on the schema is `InvalidQuery`.

**Examples**

```text
Source                              -> full stored source
Fields(["a","b"])                   -> only a,b
Fields(["computed"])                -> InvalidQuery if not a stored field
absent stored field                 -> omitted
```

**Alternatives considered:** allowing source + fields together; aliasing;
returning missing as null.

**Rejected because:** mixing source and fields is ambiguous; aliases/expressions
are transformations explicitly deferred; null-for-missing erases the distinction
(A04).

**Downstream format consequence:** PR 5 must distinguish stored fields and
support source retrieval; PR 14 owns projection execution.

**Status:** PENDING

---

## A24 — Error taxonomy

**Decision:** The stable typed error families.

**Proposed choice:** A single public `QueryError` enum (plus a schema/document
validation error type, or one unified enum) with stable variants:

```text
InvalidSchema          field definition invalid (A05)
InvalidDocument        document value invalid (A01/A03/A04/A07/A13)
InvalidQuery           malformed/contradictory query (A13/A15/A21/A23)
InvalidBatch           malformed batch envelope (A25)
TypeMismatch           field/operator/RHS type disagreement (A03/A06/A10)
UnsupportedCapability  required capability unavailable (A22)
BudgetExceeded         resource limit exhausted (A20)
Conflict               duplicate-key insert (A02)
ExpiredCursor          PIT/cursor no longer valid (A21)
NumericOverflow        checked arithmetic overflow (A06/A19)
UnsupportedJsonPath    JSONPath outside the approved subset (A11)
```

Errors are returned, never panicked. Error payloads carry a machine-readable kind
and, where useful, the offending field/capability name.

**Alternatives considered:** standalone per-domain error types; `anyhow`-style
opaque errors; `String` messages.

**Rejected because:** per-domain types fragment the public API; opaque/string
errors prevent callers from matching cases and violate the typed-error invariant.

**Downstream format consequence:** later PRs must add variants without changing
existing variant meanings.

**Status:** PENDING

---

## A25 — Batch-query contract

**Decision:** The first-class ordered batch request/response contract.

**Proposed choice:**

```rust
pub struct QueryRequest { /* typed query, sort, top_k, aggregation,
                            projection, budgets, optional PIT/cursor */ }

pub struct BatchQueryRequest {
    pub queries: Vec<QueryRequest>,
    pub shared_pit: Option<PitId>,        // optional batch-wide snapshot
    pub budget: BatchBudget,              // aggregate work/memory/response limits
}

pub struct BatchQueryResponse {
    pub results: Vec<PerQueryOutcome>,    // exactly one slot per accepted query
}

pub enum PerQueryOutcome {
    Success(SearchResponse),              // the SAME standalone response type
    Failure(QueryError),                  // the SAME standalone error type
}
```

Policies (all proposed for approval):

| Item | Proposed policy |
|---|---|
| Cardinality | `N` accepted queries ⇒ **exactly `N`** slots at indices `0..N-1`; no omission/merge/duplication, even if some fail |
| Ordering | slot `i` corresponds to input query `i`, independent of completion order |
| Empty batch | whole envelope rejected `InvalidBatch`; no empty success |
| Max size | configured positive `max_queries_per_batch`; oversized rejected **before** execution, no truncation |
| Independent options | each query keeps its own filters, sort, top-K, aggregates, projection, per-query budgets, PIT/cursor |
| Per-query failure | valid envelope may return `Failure(QueryError)` per slot; other slots unaffected |
| Envelope failure | malformed envelope, excessive count, invalid shared PIT *specification*, or invalid aggregate budget rejects the **whole batch before execution** |
| Shared PIT | optional. If `shared_pit` is set and any query carries its own PIT, the envelope is rejected `InvalidBatch` (conflicting PIT); no silent override |
| Budgets | per-query limits apply individually; aggregate limits apply to total work/memory/response bytes; aggregate exhaustion is reported as `Failure(BudgetExceeded)` for the affected slots so the **slot count never drops** |
| Concurrency | execution may be parallel but bounded; no ordering/timing guarantee (PR 14 owns scheduling) |
| Cancellation | **per-slot** outcomes: completed slots keep their result; uncompleted slots receive explicit `Failure(Cancelled)`-class errors; no fabricated successes |
| Transport failure | if the response cannot be delivered, no N-slot guarantee is made; this is represented separately from a returned `BatchQueryResponse` |
| Determinism | given the same PIT and semantics, batch and individual execution produce equivalent per-query logical results |
| Observability | optional correlation/diagnostic metadata for tracing; no telemetry/runtime scheduling in core contracts |

**Consistency rule (approved boundary):** the "exactly N" guarantee applies only
to a **successfully accepted batch that returns a `BatchQueryResponse`**. It does
not apply to an envelope rejected before acceptance or to a transport/process
failure. PR 14 owns batch execution, scheduling, and service exposure.

**Examples**

```text
queries = []                     -> InvalidBatch (empty)
queries.len() = max              -> accepted
queries.len() = max + 1          -> InvalidBatch (oversized, before execution)
[ok, err, ok]                    -> results[0]=Success, [1]=Failure, [2]=Success
shared_pit = Some, q[1].pit=Some -> InvalidBatch (conflicting PIT)
aggregate budget exhausted       -> affected slots Failure(BudgetExceeded), slots = N
cancelled slot                   -> Failure(explicit cancellation), slots = N
```

**Alternatives considered:** a reduced batch query language; positional results
as a map keyed by caller query ID; allowing variable-length result vectors;
atomic whole-batch cancellation; treating aggregate budget exhaustion as an
envelope rejection.

**Rejected because:** a second query language forks semantics; caller-keyed maps
lose positional guarantees and complicate duplicates; variable-length results
break the exactly-N invariant; atomic cancellation discards completed work and
is worse for delivery; envelope rejection on aggregate exhaustion would drop
result slots that may already be complete.

**Downstream format consequence:** none on disk. PR 14 consumes these types and
must enforce bounded scheduling, aggregate budgets, per-slot cancellation, and
the transport-failure boundary.

**Status:** PENDING

---

## Consolidated truth tables requiring approval

### Presence predicates (A09)

| Field state | EXISTS | MISSING | IS NULL |
|---|---:|---:|---:|
| Absent | false | true | false |
| Explicit null | true | false | true |
| Empty array | true | false | false |
| Scalar/array values | true | false | false |

### Membership predicates (A10)

| Field state | IN{x} | NOT IN{x} |
|---|---:|---:|
| Absent | false | false |
| Explicit null | false | false |
| Empty array | false | true |
| Scalar x | true | false |
| Scalar y | false | true |
| Array [x,y] | true | false |
| Array [y,y] | false | true |
| Type-incompatible RHS | typed error | typed error |

---

## Approval ledger

| ID | Decision | Proposed | Status | Reviewer / reference |
|---|---|---|---|---|
| A01 | Stable document key | byte-exact opaque UTF-8, index-scoped | PENDING | |
| A02 | Insert/upsert/delete | Insert conflicts; Upsert wins; Delete-absent no-op | PENDING | |
| A03 | Field types | closed typed set; decimal/binary deferred | PENDING | |
| A04 | Cardinality | Single/Multi; absent/null/empty distinct | PENDING | |
| A05 | Field options | indexed/stored/columnar + analyzer; explicit rejects | PENDING | |
| A06 | Numeric semantics | no coercion; finite floats; checked overflow | PENDING | |
| A07 | IP normalization | family-separated; mapped IPv6 preserved by default | PENDING | |
| A08 | CIDR | /0–/32, /0–/128; reject host bits; family mismatch false | PENDING | |
| A09 | EXISTS/MISSING/NULL | EXISTS = present; MISSING = absent; IS NULL = explicit null | PENDING | |
| A10 | IN/NOT IN | any-member; null/missing excluded from NOT IN | PENDING | |
| A11 | JSONPath subset | `$`, `.member`, `['member']`, `[index]`, `[*]` | PENDING | |
| A12 | JSON ancestry | array indices retained; correlation deferred | PENDING | |
| A13 | Timestamps | i64 µs UTC; floor; half-open; start>end error | PENDING | |
| A14 | Geo | WGS84 lon/lat; antimeridian crossing; meters | PENDING | |
| A15 | Sorting | total order; nulls last default; Min/Max selector; key tie-break | PENDING | |
| A16 | Group-by | multi-key; multivalue expands; null/missing distinct | PENDING | |
| A17 | Exact distinct | per-document membership; null excluded | PENDING | |
| A18 | Top-K frequency | per-document; count desc then value asc | PENDING | |
| A19 | Aggregates | checked sum/avg; empty None; epoch-aligned buckets | PENDING | |
| A20 | Budgets | positive explicit limits; no truncation | PENDING | |
| A21 | PIT/cursor | opaque; snapshot+sort+key binding; typed expiry/mismatch | PENDING | |
| A22 | Capabilities | required fails, optional ignored | PENDING | |
| A23 | Projection | Source XOR stored fields; no expressions | PENDING | |
| A24 | Error taxonomy | single stable typed error enum | PENDING | |
| A25 | Batch | ordered exactly-N outcomes; per-slot failures/cancellation | PENDING | |

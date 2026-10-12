# PR 2 — Contract Decision Record (A01–A25)

> **Status: APPROVED (2026-10-11) — contract-only scope.**
> A01–A25 are approved as documented below, per *Human approval in the Trawler
> ChatGPT conversation, 2026-10-11, following the pushed A14 clarification*. This
> authorizes implementation of the contract-only layer described in
> `TRAWLER_IMPLEMENTATION_PR02_DETAILED_PLAN_V2.md` (PR 2). It does **not**
> authorize query execution, durable storage, PIT retention, codecs or format
> freeze. `G-DEDUP-MIN` and `G-CANON` remain **OPEN — PRE-PR 6** and are not
> approved by this record.
>
> This record exists because PR 2 stabilizes the typed document/field/query/
> aggregation/batch contracts that PR 5 (codecs) and later PRs depend on.
> Approving it authorizes implementation of the contract-only layer described in
> `TRAWLER_IMPLEMENTATION_PR02_DETAILED_PLAN_V2.md` (PR 2). It does **not**
> authorize any query execution, durable storage, PIT retention, or format freeze.

> **Amendment 01 (targeted):** amended A02, A11, A12, A14, A16, A20 and A25 and
> added the Human Decision table plus the contract-conformance matrix. See
> [Amendment 01 — targeted changes](#amendment-01--targeted-changes).
>
> **Resolution Round 02 (2026-10-12):** recorded the user-selected resolutions of
> H01–H11 for the ADR proposal. See
> [Resolution Round 02 — H01–H11](#resolution-round-02--h01h11-resolved-for-adr-proposal).
> The A14 clarification (shorter-longitudinal-arc rule) is included in the
> 2026-10-11 approval.

## How to use this record

1. Each decision lists its approved choice, status and recorded approval
   reference.
2. Accepted statuses are:
   - `APPROVED` — accepted as written;
   - `APPROVED WITH CHANGES` — accepted after the noted modification;
   - `REJECTED` — replaced by the selected alternative.
3. A decision may be re-opened only with an explicit recorded human decision.

**Approval reference:** *Human approval in the Trawler ChatGPT conversation,
2026-10-11, following the pushed A14 clarification.* No GitHub approval URL is
implied.

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

**Status:** APPROVED

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
- Retry/idempotency (Amendment 01): absent-delete is naturally idempotent.
  `Upsert` is last-writer-wins by writer order. Retried `Insert` of an
  already-inserted key is a `Conflict` and must be resolved by the caller
  (typically by switching to `Upsert`). In addition, any mutation request may
  carry an optional opaque `idempotency_key` (see A02.1).
- Revision allocation, duplicate suppression, durability and the deduplication
  store are **writer/PR 6 (and PR 9 for mutations) responsibilities**; PR 2
  defines only the request/outcome/error shapes and validation.

### A02.1 — Idempotency keys (Amendment 01, Round 02)

- **Namespace (H01, resolved for ADR proposal):** every mutation request **may**
  carry an opaque `idempotency_key`, scoped to
  **`(logical index, authenticated caller scope)`**. Opaque keys must not collide
  across these namespaces. `trawler-core` must **not** depend on an
  authentication provider or tenant service: the caller scope is **verified
  context supplied at the integration boundary**. Accepting an unverified,
  caller-supplied identity as authoritative is explicitly prohibited.
- **Replay (H03, resolved for ADR proposal):** the server computes the canonical
  mutation identity; JSON object member order does not affect it. Same scoped key
  + **same canonical request** replays the prior committed outcome (including a
  revision or a successful no-op); same scoped key + **different canonical
  request** yields a typed `IdempotencyConflict`.
- Canonicalization must be deterministic, typed, lossless and versioned. It
  covers the operation kind, document key, payload and all semantic options, and
  preserves array order, type distinctions and null/missing values. A concrete
  wire canonicalization algorithm is **not** claimed here; if none is already
  selected, that is the narrowly scoped open gate **G-CANON**, not a made-up
  implementation. Client-provided fingerprints alone are **not** trusted.
- Requests **without** an idempotency key retain the original A02 semantics.
- An idempotency key is **not** a client-selected revision and does not change
  writer ordering or last-writer-wins semantics.
- **Retention (H02, resolved for ADR proposal):** default deduplication retention
  is **24 hours**. It is index-configurable subject to a documented positive
  `minimum_supported_dedup_retention` policy parameter; the default must be
  `>=` that configured minimum. On expiry, a replay may be treated as a **new**
  operation, and the replay guarantee applies only while the deduplication record
  is retained. A no-op delete is **distinct** from a deduplicated replay.
- The numeric value of `minimum_supported_dedup_retention` is **not chosen here**;
  it is a named implementation-policy parameter and the pre-PR 6 open gate
  **G-DEDUP-MIN**. No numeric minimum is asserted in this ADR.
- Durable deduplication and replay outcomes are **PR 6/PR 9 responsibilities**;
  PR 2 defines request/outcome/error types and validation only.

**Examples**

```text
Insert(key absent)      -> Ok(revision = N)
Insert(key live)        -> Err(Conflict)
Upsert(key any)         -> Ok(revision = N+1)
Delete(key live)        -> Ok(revision = N+1)
Delete(key absent)      -> Ok (no revision)      // idempotent no-op
Insert(k, idem=K) ok; retry Insert(k, idem=K)   -> same Ok(revision = N)
Insert(k, idem=K) then Insert(other, idem=K)    -> Err(IdempotencyConflict)
Upsert(k, idem=K); retry with same payload      -> same Ok(revision = N+1)
Delete absent, idem=K; retry same               -> same successful no-op (no new revision)
token K replay after retention expiry           -> may be treated as a new operation (PR 6/9)
canonical identity ignores member order: {"a":1,"b":2} == {"b":2,"a":1}
same key, different scope (index or caller)     -> independent namespaces, no collision
```

**Alternatives considered:** client-supplied revisions with compare-and-set; a
boolean `create_only` flag instead of `Insert`; absent-delete as an error.

**Rejected because:** client-supplied revisions require a conflict-resolution
contract and CAS semantics the writer does not yet own; absent-delete-as-error
makes retries non-idempotent for event pipelines.

**Downstream format consequence:** PR 6 must define monotonic revision
assignment, delete ordering, recovery, and the durable deduplication store;
PR 9 owns tombstone/merge semantics. The 24-hour default retention, the
`minimum_supported_dedup_retention` parameter, the `(index, caller scope)`
namespace and the versioned canonical request identity are policy/format inputs
that must be fixed before the writer format freezes.

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

---

## A11 — JSONPath subset grammar

**Decision:** The exact JSONPath grammar that PR 2 can represent.

**Proposed choice: an RFC 9535-inspired, indexable subset.**

```text
path        := "$" segment*
segment     := "." member
             | "[" json-string "]"
             | "[" index "]"
             | "[*]"
member      := ASCII letter/underscore followed by letters/digits/underscore
json-string := JSON string literal delimited by U+0022 (double quotes)
index       := non-negative decimal integer (no leading '+'/'-')
```

Supported: root, dot/bracket named child, non-negative fixed array index, and a
single-level wildcard `[*]`.

Quoted-member rules (H05, resolved for ADR proposal):

- Bracket-quoted member selectors use **double-quoted JSON string syntax only**,
  for example `$["a b"]`. Single-quoted forms such as `$['a b']` are **not
  accepted**.
- JSON string escape rules apply (`\"`, `\\`, `\/`, `\b`, `\f`, `\n`, `\r`,
  `\t`, `\uXXXX`). Malformed escapes, unpaired/lone surrogate escapes and
  invalid syntax are rejected with `UnsupportedJsonPath`.
- Quoted member names support Unicode and compare as **exact decoded Unicode
  scalar sequences**; **no Unicode normalization** is applied.
- The dot-member ASCII subset remains unchanged.
- `$["a"]` and `$.a` select the same member and canonicalize to the same member
  selector, **without** normalizing member content.

Explicitly **rejected** (typed `QueryError::UnsupportedJsonPath`):

```text
"$..name"          recursive descent ("..")
"$[?(@.x > 1)]"    filter/script selectors
"$[0:2]" "$[::2]"  slices
"$['a','b']"       unions
"$[-1]"            negative indices
"$[(@.length-1)]"  expression selectors
functions/`length()` and similar extensions
"$['a b']"         single-quoted member (use $["a b"])
"$[\"\uD800\"]"   lone surrogate escape
```

The approved subset is a validated query **expression** type (`JsonPathExpr`). It
may contain wildcard segments and identifies a **set of possible matches**, never
a single value occurrence. `JsonPathExpr` is distinct from a resolved
`ConcreteJsonPath` and from a `JsonNodeRef`; see A12. Wildcard `[*]` is
representable but its **correlated** execution is deferred. PR 2 defines
parsing/validation only; no compiler or executor.

**Examples**

```text
ACCEPTED: $.a.b ; $["a b"] ; $.a[0] ; $.a[*] ; $["naïve"] ; $["a\"b"] ; $["a\\b"]
REJECTED: $..a ; $[?(@.x==1)] ; $[1:3] ; $[-1] ; $['a b'] ; $["unterminated ; lone surrogate \uD800
```

**Alternatives considered:** full RFC 9535; a minimal dot-only grammar; storing
raw path strings unvalidated.

**Rejected because:** full RFC 9535 includes recursive/filter features that
cannot be indexed and would imply execution; dot-only cannot express quoted or
array members; unvalidated strings cannot be type-checked.

**Downstream format consequence:** PR 5/11 must persist the parsed segment path
and reserve extension for recursive selectors without changing the meaning of
accepted paths. PR 11 must round-trip double-quoted JSON member selectors,
Unicode member names and escapes exactly, with no normalization.

**Status:** APPROVED

---

## A12 — Nested JSON identity and array ancestry

**Decision:** How structural identity is preserved and what is explicitly not
promised.

**Proposed choice (Amendment 01):** three distinct concepts are separated:

1. **`JsonPathExpr`** — a validated *query expression* following the approved
   A11 subset. It may contain wildcard segments and identifies a **set of
   possible matches**, not one value occurrence.
2. **`ConcreteJsonPath`** — a resolved path to **one node in one document**. It
   contains **no wildcards**; it uses explicit nonnegative array indices and
   exact member names.
3. **`JsonNodeRef`** (or equivalently named contract) — a concrete node identity:
   **`(logical document key, document revision, ConcreteJsonPath)`**. A
   `JsonPathExpr` (possibly wildcard) is **not** a concrete node identity. A node
   reference must **never** be silently re-resolved after a mutation; a lookup
   against a released or unavailable snapshot/revision may fail with a typed
   unavailable/stale result, and no retention of old revisions is promised.

Every extracted value retains its full path ancestry **including array element
indices** (for example `$.events[1].ip`). Two predicates on `$.events[*].ip` and
`$.events[*].time` do **not** imply same-element correlation; such correlation
requires a future explicit ancestor-binding operator, not Boolean AND over
flattened terms. Flattening a document into independent field postings must
**never** be interpreted as proof that values from different paths belonged to
the same array element. Correlated-array predicate execution is **deferred**; the
contract reserves a structural-identity extension but does not claim it.

Quoted member selectors follow A11: **double-quoted JSON strings**, JSON string
escape rules, and comparison as **exact decoded Unicode scalar sequences** with
**no Unicode normalization**; distinct JSON member names are never collapsed.

**Examples**

```text
{"events":[{"ip":"a","t":1},{"ip":"b","t":2}]}
  expression:      $.events[*].ip
  concrete match:  $.events[1].ip
  node identity:   (document_key="doc-7", revision=42, path=$.events[1].ip)
  after upsert:    (doc-7, revision=43, ...) is a DIFFERENT node ref
  $.events[0].ip = "a" and $.events[1].ip = "b"  (ancestry retained)
  A flattened query ip="a" AND t=2 must NOT be treated as satisfied by one element.
  $["naïve"] and $.naïve style members compare as exact decoded scalars (no NFC/NFD fold).
```

**Alternatives considered:** discarding array indices; merging same-named nested
paths; implementing correlated extraction now.

**Rejected because:** discarding indices destroys the counterexample; merging
conflates independent arrays; correlated execution is explicitly deferred by the
architecture gate.

**Downstream format consequence:** PR 5 must store array ancestry (or enough to
reconstruct it) and reserve a versioned structural-index capability; PR 11 owns
the source/evaluator path. If a stable `JsonNodeRef` requires a node encoding not
approved here, that format change is a STOP condition until the node-reference
encoding is approved; revision-scoped references must not silently re-resolve.

**Status:** APPROVED

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

**Status:** APPROVED

---

## A14 — GeoPoint and spatial boundary semantics

**Decision:** Coordinate model, ranges, antimeridian, polygon validation, and
distance units.

**Proposed choice (Amendment 01):**

- `GeoPoint` is WGS84 `[longitude, latitude]`; longitude `[-180, 180]`,
  latitude `[-90, 90]`, both finite.
- Bounding boxes: `west <= east` is a normal box; `west > east` denotes a box
  **crossing the antimeridian** (the union of `[west, 180]` and `[-180, east]`).
- Radius: center plus a distance in **meters**; PR 2 validates units/shape only.
  An explicit execution distance model and tolerance must be approved before
  PR 12 may claim exact matching.
- Polygon: an outer ring of >= 3 distinct vertices plus optional holes; rings may
  be given open or closed (a repeated first/last vertex is normalized); rings
  with < 3 distinct vertices, zero area, non-finite coordinates, degenerate edges
  or malformed closures are rejected with `InvalidGeoShape`.
- **Boundary inclusion (H07, resolved logical rule):** points on an **outer-ring
  boundary are inside**; points strictly inside a hole are **outside**; points on
  a **hole boundary are outside** (hole boundary wins).
- **Self-intersections and malformed rings (H07, resolved):** self-intersecting
  rings, including bow-tie polygons, and malformed/degenerate rings are
  **rejected** with `InvalidGeoShape`; no implicit repair is attempted.
  Ambiguous touching/crossing holes are rejected by default.
- **Antimeridian polygons (H06 + A14 clarification, resolved for v0.1):**
  for the v0.1 polygon contract, consecutive vertex longitudes (and the
  implicit/explicit closing edge) are interpreted using the **shorter
  longitudinal arc**. An edge whose shorter arc crosses the ±180° meridian is
  **unsupported** for v0.1 polygon queries: the entire polygon is rejected with
  the typed `UnsupportedGeoShape` error, and it is never silently unwrapped,
  normalized or repaired.
  - An adjacent pair with an absolute longitude difference **equal to 180°** is
    **ambiguous** (either arc is equally short) and is likewise rejected with
    `UnsupportedGeoShape`, rather than having an arc chosen arbitrarily.
  - **Boundary distinction:** `abs(lon2 - lon1) > 180°` is only an *indicator* of
    a short-arc wrap for longitudes canonicalized to `[-180°, 180°]`; it is **not
    a universally valid geodesic test by itself**. The shorter-arc convention
    above is the normative rule, including how endpoints at `+180°` and `-180°`
    are handled.
  - **Conservative v0.1 validation rule:** reject an edge when
    `abs(lon2 - lon1) >= 180°`, and reject any additional edge that uses a `+180°`
    or `-180°` endpoint where the edge interpretation would be ambiguous. This is
    a conservative contract-validation rule, **not** a complete geodesic
    intersection algorithm.
  - Antimeridian-crossing **bounding boxes remain supported** (`west > east`);
    only polygons are restricted. PR 12 may extend polygon support through a
    versioned capability.
- **Precision (H07, resolved split):** PR 2 defines logical inclusion and shape
  validation only and does **not** claim execution. PR 12 must document the
  numeric tolerance and geodesic distance algorithm before any runtime
  conformance is asserted. The GeoPoint/bbox/polygon **contract** is not marked
  unsupported.

**Examples**

```text
ACCEPTED: { lon: -122.4, lat: 37.8 }, bbox west=170 east=-170 (antimeridian bbox)
ACCEPTED: outer-ring boundary point (inside), hole interior point (outside)
ACCEPTED: polygon with adjacent Δlon < 180° and no ±180° endpoint (if well-formed)
REJECTED: { lon: 200, lat: 0 }, { lon: 0, lat: 91 }, NaN
REJECTED: polygon with 2 distinct vertices, zero-area ring, self-intersecting ring -> InvalidGeoShape
REJECTED: polygon adjacent Δlon > 180° -> UnsupportedGeoShape
REJECTED: polygon adjacent Δlon == 180° (ambiguous arc) -> UnsupportedGeoShape
REJECTED: polygon closing edge crossing the antimeridian -> UnsupportedGeoShape
REJECTED: polygon edge with a +180°/-180° endpoint (ambiguous) -> UnsupportedGeoShape
```

**Alternatives considered:** `[lat, lon]` ordering; degrees for radius;
antimeridian as an error; implicit ring closure with no validation.

**Rejected because:** `[lat, lon]` contradicts GeoJSON/WGS84 convention; degrees
are unit-ambiguous; erroring on antimeridian forbids legitimate queries.

**Downstream format consequence:** PR 5/12 must reserve geo bounds and exact
coordinates; conservative pruning must not produce false negatives at the
antimeridian. The resolved logical boundary and antimeridian-polygon rules affect
query meaning and must be fixed before PR 12 freezes the spatial predicate
contract; PR 12 must document numeric tolerance and the geodesic algorithm before
runtime conformance is claimed.

**Status:** APPROVED

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

**Status:** APPROVED

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
- A global maximum-group budget (A20) is enforced; exceeding it is
  `BudgetExceeded { kind: GroupCardinality }`, never truncation.
- **Per-document expansion bound (Amendment 01):** cross-product expansion is
  bounded separately by `max_group_expansions_per_document` and
  `max_group_key_fields` (both positive bounded integers, A20). The prospective
  Cartesian product is computed with **checked arithmetic before materializing**
  combinations; exceeding the per-document limit or overflowing produces
  `BudgetExceeded { kind: GroupExpansion }`, never truncation.
- **Count semantics (Amendment 01):** each document contributes **at most once**
  to any given canonical group key; repeated multivalue members must not inflate
  counts. A document that expands into many *already existing* groups still
  consumes per-document expansion budget. The per-document and global budgets are
  enforced independently.

**H08 (resolved for ADR proposal):** an empty multivalue group key expands to
**zero groups**. Missing and explicit null remain **distinct** group keys. Each
multivalue key is deduplicated before **checked** Cartesian expansion. No "empty"
group is silently synthesized.

**Examples**

```text
doc A tags=[x,y], doc B tags=[y]  -> groups x:{A}, y:{A,B}
absent vs null vs [] on a key     -> absent group, null group, ([] expands to nothing)
group cardinality budget + 1      -> BudgetExceeded (GroupCardinality)
[a,b] x [1,2,3]                   -> 6 unique group keys
expansion limit + 1               -> BudgetExceeded (GroupExpansion), pre-allocation
```

**Alternatives considered:** rejecting multi-value group keys; merging null and
missing groups; grouping by frequency order.

**Rejected because:** rejecting multi-value keys removes a required capability;
merging loses state; frequency ordering is non-deterministic under ties.

**Downstream format consequence:** PR 5 must encode typed group keys with
missing/null sentinels; PR 10 owns bounded grouped execution and must enforce
both the per-document expansion and global group budgets.

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

---

## A20 — Resource budgets

**Decision:** Which limits exist, and what happens at zero or exhaustion.

**Proposed choice (Amendment 01):** Budgets are explicit, bounded, positive
values. Four classes are distinguished:

| Class | Description |
|---|---|
| Server hard ceiling | non-bypassable operator safety limit |
| Index/tenant policy ceiling | optional, at or below server ceilings |
| Caller-requested limit | optional; cannot increase effective ceilings |
| Default limit | used when the caller omits a field; bounded and published |

For each limit kind:

```text
effective_limit = min(server_hard_limit,
                      applicable_index_or_tenant_limit,
                      caller_requested_limit_or_default)
```

The budget kinds are:

```text
max_json_depth, max_fields, max_array_elements, max_document_bytes,
max_result_window (top-K), max_groups, max_group_key_fields,
max_group_expansions_per_document, max_distinct_keys,
max_term_expansion, max_memory_bytes, max_elapsed, max_response_bytes,
max_queries_per_batch, max_batch_memory_bytes, max_batch_response_bytes
```

- A budget of `0` is `QueryError::InvalidQuery` at validation time.
- A configured maximum larger than the type can represent is likewise rejected
  at validation; there is no silent "unbounded" sentinel.
- **H09 (resolved for ADR proposal):** a caller-requested budget above any
  applicable server hard ceiling or index/tenant policy ceiling is **rejected**
  with a typed `BudgetPolicyViolation`; it is never silently clamped. The
  effective budget is the minimum of the server hard ceiling, the applicable
  index/tenant ceiling, and the requested-or-default limit. Limits are validated
  as positive, bounded values with explicit units. Exhaustion still yields a
  typed `BudgetExceeded` and never a false exact result.
- Exceeding any **effective** budget during execution is
  `QueryError::BudgetExceeded { kind }`.
- Request validation is separate from runtime consumption.
- Every budget kind has a stable unit (bytes, documents, groups, expansions,
  elapsed milliseconds, etc.). CPU "work units" must not be claimed without an
  explicit metering definition and may remain an abstract future limit only.
- Contract structs must not depend on a tenant/multi-tenant implementation; an
  optional index/tenant policy is a policy input, not a service dependency.
- **No silent truncation.** A budget failure must never be reported as a smaller
  but "exact" result.

**Examples**

```text
max_fields = 0                -> InvalidQuery
max_groups = 10, 11th group   -> BudgetExceeded
server=10k, index=5k, caller=20k -> BudgetPolicyViolation (recommended)
caller omitted, default=2k    -> effective_limit = 2k
top_k = 100 within window     -> Ok
```

**Alternatives considered:** `Option<usize>` with `None` = unbounded; saturating
at `usize::MAX`; returning partial results flagged as truncated.

**Rejected because:** unbounded defaults invite resource exhaustion; a truncation
flag still lets callers treat partial output as complete; explicit positives keep
the contract auditable.

**Downstream format consequence:** none on disk; budgets are request metadata
that PRs 10/14 must enforce. The A16 per-document expansion limits and the A25
batch aggregate limits are part of this governance model.

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Status:** APPROVED

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

**Amendment 01 additions:**

```text
IdempotencyConflict    same idempotency key with a different canonical request (A02.1)
InvalidGeoShape        invalid/degenerate/self-intersecting polygon (A14)
UnsupportedGeoShape    antimeridian-crossing polygon rejected by v0.1 policy (A14)
BudgetPolicyViolation  caller-requested limit exceeds an applicable ceiling (A20)
Cancelled              per-slot batch cancellation; carries a reason (A25.1)
```

`InvalidGeoShape` denotes a malformed or degenerate shape; `UnsupportedGeoShape`
denotes a well-formed shape that v0.1 policy declines to execute (antimeridian
crossing). The two must not be conflated.

`BudgetExceeded { kind }` now also covers `GroupCardinality`, `GroupExpansion`
and `BatchAggregate` kinds. `Cancelled` is returned as a per-slot batch outcome
(`PerQueryOutcome::Failure`) while remaining a `QueryError` variant, so batch and
standalone error contracts stay unified.

Errors are returned, never panicked. Error payloads carry a machine-readable kind
and, where useful, the offending field/capability name.

**Alternatives considered:** standalone per-domain error types; `anyhow`-style
opaque errors; `String` messages.

**Rejected because:** per-domain types fragment the public API; opaque/string
errors prevent callers from matching cases and violate the typed-error invariant.

**Downstream format consequence:** later PRs must add variants without changing
existing variant meanings.

**Status:** APPROVED

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
| Budgets | per-query limits apply individually; aggregate limits apply to total work/memory/response bytes; deterministic exhaustion semantics are defined in A25.1 |
| Concurrency | execution may be parallel but bounded; no ordering/timing guarantee (PR 14 owns scheduling) |
| Cancellation | **per-slot** outcomes: completed slots keep their result; uncompleted slots receive explicit `Failure(Cancelled)`-class errors; terminalization precedence is defined in A25.1 |
| Transport failure | if the response cannot be delivered, no N-slot guarantee is made; this is represented separately from a returned `BatchQueryResponse` |
| Determinism | given the same PIT and semantics, batch and individual execution produce equivalent per-query logical results |
| Observability | optional correlation/diagnostic metadata for tracing; no telemetry/runtime scheduling in core contracts |

### A25.1 — Shared-budget exhaustion and deterministic outcomes (Amendment 01, Round 02)

- **Exactly N ordered slots** are retained for every accepted batch that returns a
  `BatchQueryResponse`. Envelope rejection and transport/process failure remain
  outside this guarantee.
- **Two budget phases:**
  1. **Admission:** validate the envelope, query count, shared-PIT conflicts and
     any *statically calculable* aggregate constraints **before** executing.
     Invalid envelopes are rejected whole.
  2. **Runtime:** enforce aggregate budgets through a bounded shared accounting
     mechanism.
- **Completed slots are immutable:** a completed success must never be
  retroactively replaced because another query exhausts the shared budget.
- **Admission/reservation policy (H10, resolved for ADR proposal):** admission and
  aggregate budget reservation occur in deterministic **input-index order**.
  Execution may be concurrent and may finish in any order. Reservation and
  accounting rules must be explicitly bounded and must **not** falsely guarantee
  deterministic runtime success/failure when actual work differs; only
  admission/reservation is deterministic. If reservation units cannot yet be
  concretely metered, PR 2 defines a contract-level scheduling policy and PR 14
  owns the metering; no reservation determinism beyond admission is promised.
- **Terminalization precedence (H11, resolved for ADR proposal):** each unfinished
  slot has a **single terminalization point**, and after terminalization no later
  event overwrites its outcome. When multiple terminal reasons compete, precedence
  is: **explicit client cancellation > aggregate batch budget exhaustion >
  per-query timeout**. Per-query validation/runtime failures not caused by these
  three events retain their own typed error. Already completed success/failure is
  never rewritten.
- At exhaustion, affected in-flight/not-yet-started queries receive
  `Failure(BudgetExceeded { kind: BatchAggregate })` or
  `Failure(Cancelled { reason: BatchBudgetExhausted })` per the precedence above.
- A completed slot keeps its outcome; an unfinished slot gets an explicit typed
  failure. No slot is omitted, duplicated, or synthesized as a successful
  partial result.
- If explicit client cancellation makes response delivery impossible, no
  exactly-N transport guarantee applies.
- Shared PIT is only a **snapshot reference contract**. PIT lifetime, cross-query
  consistency, scheduling and response delivery are PR 14 responsibilities.
- Batch/standalone result equivalence holds only with identical PIT, query
  semantics and sufficient budgets; it is **not** promised when shared budgets or
  cancellation differ.

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
aggregate budget exhausted, q0 done -> results[0]=Success, [1..]=Failure(BudgetExceeded)
client cancel + exhaustion       -> client cancellation wins (H11 precedence)
q0 done, then cancel + budget    -> results[0] unchanged; remaining slots terminalized once
reservation, q2 budget-starved   -> admission in input-index order; runtime order may vary
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
must enforce bounded scheduling, aggregate budgets, the A25.1 admission/runtime
split, input-index-order reservation, the H11 terminalization precedence,
per-slot cancellation and the transport-failure boundary.

**Status:** APPROVED

---

## Amendment 01 — targeted changes

This amendment (targeted) touched only A02, A11, A12, A14, A16, A20
and A25. It preserves every other decision verbatim. The amended items are
`APPROVED` under the 2026-10-11 approval record.

| Item | Amendment summary | Cross-reference |
|---|---|---|
| A02 | Optional `idempotency_key`; same-key/different-request rejected; finite dedup window | A02.1 |
| A11 | Approved subset is a query *expression* (`JsonPathExpr`), not value identity | A11, A12 |
| A12 | Split `JsonPathExpr` / `ConcreteJsonPath` / `JsonNodeRef`; revision-scoped identity | A12 |
| A14 | Boundary inclusion, self-intersection rejection, ring validation, antimeridian decision | A14 |
| A16 | Per-document expansion + key-field budgets; checked product; no count inflation | A16 |
| A20 | Effective-limit precedence (server/index/caller/default); `BudgetPolicyViolation` | A20 |
| A25 | Admission vs. runtime budgets; completed-slot retention; allocation/cancellation decisions | A25.1 |

Error additions: `IdempotencyConflict`, `InvalidGeoShape`, `BudgetPolicyViolation`,
`Cancelled` (A24). New budgets: `max_group_expansions_per_document`,
`max_group_key_fields`, `max_batch_memory_bytes`, `max_batch_response_bytes` (A20).

Human choices H01–H11 are resolved for the ADR proposal in
[Resolution Round 02](#resolution-round-02--h01h11-resolved-for-adr-proposal);
residual implementation-policy gates are in
[Open implementation-policy gates](#open-implementation-policy-gates).
New test IDs are collected in the
[contract-conformance matrix](#contract-conformance-matrix-pr-2-vs-future-runtime).

---

## Resolution Round 02 — H01–H11 (resolved for ADR proposal)

On **2026-10-12**, per the user's instruction in this conversation
(`TRAWLER_PR02_H01_H11_RESOLUTION_INSTRUCTIONS.md`), the following H01–H11 choices
were recorded for the ADR proposal; they are included in the **2026-10-11**
A01–A25 approval. No GitHub approval URL is implied. These resolutions constrain
the A02/A02.1, A11, A12, A14, A16, A20, A24 and A25.1 text above.

| ID | Resolution (as selected) | Qualification / boundary |
|---|---|---|
| H01 | Idempotency namespace is `(logical index, authenticated caller scope)`; opaque keys must not collide across namespaces | Core must not depend on an authentication provider or tenant service; caller scope is verified context supplied at the integration boundary; an unverified caller-supplied identity is never authoritative |
| H02 | Default dedup retention **24 hours**; index-configurable with a documented, positive minimum | `minimum_supported_dedup_retention` is a named unresolved parameter (gate **G-DEDUP-MIN**); no numeric minimum is asserted; on expiry replay may be a new operation; a no-op delete is distinct from a dedup replay; guarantee holds only while the record is retained |
| H03 | Server computes canonical mutation identity; JSON member order is irrelevant; same scoped key + same request replays the prior outcome; same key + different request → `IdempotencyConflict` | Deterministic, typed, lossless, versioned; includes operation kind, document key, payload and semantic options; preserves array order, type distinctions, null/missing; concrete wire algorithm is gate **G-CANON**; client fingerprints alone are not trusted |
| H04 | `JsonNodeRef` = `(logical document key, document revision, ConcreteJsonPath)` | A `JsonPathExpr` (possibly wildcard) is not a concrete node identity; never silently re-resolve after mutation; stale/unavailable snapshot lookup is a typed result; retention is not promised |
| H05 | Bracket-quoted members use **double-quoted JSON strings** with JSON escapes and exact decoded Unicode scalar comparison; **no Unicode normalization** | Single-quoted forms rejected; malformed/lone-surrogate escapes rejected; dot-member ASCII subset unchanged; `$["a"]` and `$.a` canonicalize to the same selector; PR 11 round-trips exactly |
| H06 | v0.1 **rejects** antimeridian-crossing polygons with `UnsupportedGeoShape`; crossing bounding boxes remain supported | Shorter-arc interpretation; conservative detection rejects `abs(Δlon) >= 180°` and ambiguous `+180°`/`-180°` endpoints (A14 clarification, 2026-10-12); never silently reinterpret; PR 12 may extend via a versioned capability |
| H07 | Logical inclusion fixed now: outer boundary inside; hole interior and hole boundary outside; malformed/self-intersecting polygons rejected with `InvalidGeoShape` | Numeric algorithms and tolerances deferred to PR 12; the GeoPoint/bbox/polygon **contract** is not marked unsupported; PR 2 shapes/validation only, execution not claimed |
| H08 | Empty multivalue group key expands to **zero groups** | Missing and explicit null remain distinct group keys; deduplicate each key before checked Cartesian expansion; never synthesize an "empty" group |
| H09 | Caller budget above any applicable hard/index/tenant ceiling is **rejected** with `BudgetPolicyViolation`; never silently clamped | Effective budget = min(server hard, applicable index/tenant, requested-or-default); positive bounded values with explicit units; exhaustion yields typed `BudgetExceeded`, never a false exact result |
| H10 | Deterministic **input-index-order** admission and aggregate budget reservation; execution may be concurrent and finish in any order | No deterministic runtime success/failure guarantee beyond admission/reservation; completed outcomes immutable; if reservation units are unmetered, PR 2 defines a contract-level scheduling policy and PR 14 owns metering |
| H11 | Terminalization precedence: **explicit client cancellation > aggregate batch budget exhaustion > per-query timeout** | Single terminalization point per slot; completed outcomes never overwritten; unrelated per-query failures retain their own typed error; envelope/transport failure is separate; if cancellation prevents delivery, no exactly-N transport guarantee applies |

Residual open implementation-policy gates are recorded in
[Open implementation-policy gates](#open-implementation-policy-gates).

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

### Geo boundary inclusion (A14, resolved logical rule)

| Point location | Inside query polygon |
|---|---|
| Strictly inside outer ring | true |
| On outer-ring boundary | **true** |
| Strictly inside a hole | false |
| On a hole boundary | **false** (hole boundary wins) |
| Outside all rings | false |
| Antimeridian-crossing polygon (shorter arc) | rejected with `UnsupportedGeoShape` (v0.1 policy; `=180°` ambiguous also rejected) |

### Group expansion and budget (A16, resolved)

| Case | Expected |
|---|---|
| Two multivalue keys `[a,b] × [1,2,3]` | 6 unique group keys |
| Duplicate members within one key | collapsed before the product |
| Product exactly at per-document limit | accepted |
| Product one above per-document limit | `BudgetExceeded { kind: GroupExpansion }`, pre-allocation |
| Checked multiplication overflows | `BudgetExceeded { kind: GroupExpansion }` |
| Global group count at/over budget | enforced independently of per-document expansion |
| Empty multivalue key | expands to **zero groups** |

### Batch shared-budget outcome (A25.1, resolved)

| Situation | Expected outcome |
|---|---|
| Completed slot, then aggregate exhaustion | completed slot's original outcome retained |
| Not-yet-started slot at exhaustion | explicit `Failure(BudgetExceeded { kind: BatchAggregate })` or `Failure(Cancelled { .. })` per H11 precedence |
| Invalid envelope / oversized count | whole-batch `InvalidBatch`; no `BatchQueryResponse` |
| Transport/process failure | separate representation; no N-slot guarantee |
| Any accepted batch that returns a response | exactly N ordered slots, no omission/duplication |
| Competing terminal reasons | cancel > aggregate budget exhaustion > per-query timeout |

---

## Human Decision Needed (Amendment 01)

**Status (Resolution Round 02, 2026-10-12):** H01–H11 are resolved **for the ADR
proposal** per the user's instruction. This is **not** final A01–A25 approval; the
status column records proposal-level resolution only and the approval reference
remains blank. Residual implementation-policy questions are listed under
[Open implementation-policy gates](#open-implementation-policy-gates).

| # | Item | Candidate options | Recommendation | Consequence if deferred | Status (Round 02) |
|---|---|---|---|---|---|
| H01 | A02.1 idempotency namespace | `(index, caller scope)` / `(index)` / caller-supplied | `(index, authenticated caller scope)` | Request/outcome types cannot freeze | RESOLVED FOR ADR PROPOSAL |
| H02 | A02.1 dedup retention | minimum window; index-configurable?; post-expiry behavior | bounded, configurable, documented; after expiry treat as a new request | Durable dedup format (PR 6/9) blocked | RESOLVED FOR ADR PROPOSAL |
| H03 | A02.1 canonical request identity | canonical encoding vs. opaque client fingerprint | approved canonicalization, member-order independent | `IdempotencyConflict` detection undefined | RESOLVED FOR ADR PROPOSAL |
| H04 | A12 `JsonNodeRef` revision | revision in ref / snapshot-scoped / not in ref | include document revision; reject silent re-resolution | Structural identity and PR 5/11 format blocked | RESOLVED FOR ADR PROPOSAL |
| H05 | A12 quoted-member grammar | escaping/Unicode/canonical-equivalence rules | double-quoted JSON strings, exact scalar comparison, no normalization | Parser cannot be frozen (STOP) | RESOLVED FOR ADR PROPOSAL |
| H06 | A14 antimeridian polygons | support with normalization / reject explicitly | reject crossing polygons in v0.1 with `UnsupportedGeoShape` | Spatial predicate meaning undefined | RESOLVED FOR ADR PROPOSAL |
| H07 | A14 precision/tolerance | fix tolerance now / mark `UnsupportedCapability` | fix logical inclusion now; defer numeric algorithm/tolerance to PR 12 | Boundary equality unclaimable | RESOLVED FOR ADR PROPOSAL |
| H08 | A16 empty multivalue group key | no groups (current) / special empty group | expand to zero groups | Group semantics ambiguous | RESOLVED FOR ADR PROPOSAL |
| H09 | A20 above-ceiling request | reject `BudgetPolicyViolation` / clamp with disclosure | reject; never silently clamp | Validation semantics undefined | RESOLVED FOR ADR PROPOSAL |
| H10 | A25.1 allocation fairness | deterministic index-order reservation / scheduling-dependent failure | deterministic input-index-order admission/reservation | Which-slot-fails becomes non-deterministic | RESOLVED FOR ADR PROPOSAL |
| H11 | A25.1 error precedence | `BudgetExceeded` vs. `Cancelled`; client cancel vs. exhaustion vs. timeout | cancel > aggregate budget > per-query timeout | Per-slot outcome ambiguous | RESOLVED FOR ADR PROPOSAL |

### Open implementation-policy gates

These narrow questions are **not** decided by H01–H11 or by the 2026-10-11
A01–A25 approval. `G-DEDUP-MIN` and `G-CANON` remain **OPEN — PRE-PR 6** and must
be approved before PR 6 depends on them; they do not block PR 2 contract types.
`G-GEO-CROSS` was confirmed as part of this approval and is retained for
traceability.

| Gate | Question | Boundary already fixed | Required before | Status |
|---|---|---|---|---|
| G-DEDUP-MIN | numeric value of `minimum_supported_dedup_retention` | positive; the 24-hour default must be `>=` the configured minimum | durable dedup (PR 6) | OPEN — PRE-PR 6 |
| G-CANON | exact canonical mutation wire encoding and version | deterministic, typed, lossless, member-order independent; covers operation kind, key, payload, semantic options | canonicalization type freeze / durable replay (PR 6) | OPEN — PRE-PR 6 |
| G-GEO-CROSS | confirm the conservative antimeridian-crossing detection rule | shorter-arc interpretation; reject edges with `abs(Δlon) >= 180°` and ambiguous `+180°`/`-180°` endpoints | PR 12 spatial execution | APPROVED — 2026-10-11 |

---

## Contract-conformance matrix (PR 2 vs. future runtime)

PR 2 owns **contract validation and test-only reference oracles**. Runtime rows are
future-owned and must not be claimed as executed by PR 2. This matrix augments the
plan's D/T/I/P/J/G/S/A/C/X/B IDs without replacing them.

| ID | Case | PR 2 (contract-only) | Future runtime owner |
|---|---|---|---|
| M-ID01 | Same scoped idempotency key + same canonical request yields identical contract identity | outcome/type equality | PR 6/9 |
| M-ID02 | Same scoped idempotency key + different payload rejected | `IdempotencyConflict` validation | PR 6/9 |
| M-ID03 | Absent idempotency key retains original A02 behavior | request validation | PR 6/9 |
| M-ID04 | After 24h default retention expiry, replay may be a new operation | documented only, **not** executable in PR 2 | PR 6/9 |
| M-ID05 | Keys in different `(index, caller scope)` namespaces never collide | namespace validation (test-only) | PR 6/9 |
| M-ID06 | Canonical identity ignores JSON object member order | contract/reference equality once **G-CANON** resolves | PR 6/9 |
| M-ID07 | Default retention metadata is 24h and `>=` the configured minimum | constant/config validation | PR 6/9 |
| J-ID01 | Wildcard expression resolves to distinct concrete paths | test-only fixture | PR 11 |
| J-ID02 | Repeated values at different indices have distinct node refs | test-only fixture | PR 11 |
| J-ID03 | Different document revisions cannot be conflated | test-only reference | PR 11 |
| J-ID04 | Cross-element false-positive counterexample rejected as correlation | negative assertion | PR 11 |
| J-ID05 | Double-quoted JSON member selectors round-trip (escapes, backslashes, Unicode) | parser/round-trip test | PR 11 |
| J-ID06 | `$["a"]` and `$.a` canonicalize to the same member selector | test-only reference | PR 11 |
| J-ID07 | Malformed escapes and lone surrogate escapes rejected | `UnsupportedJsonPath` validation | PR 11 |
| G-EDGE01 | Outer boundary included | test-only semantic example | PR 12 |
| G-EDGE02 | Hole interior excluded | test-only semantic example | PR 12 |
| G-EDGE03 | Hole boundary excluded | test-only semantic example | PR 12 |
| G-EDGE04 | Self-intersecting/degenerate ring rejected | `InvalidGeoShape` validation | PR 12 |
| G-EDGE05 | Antimeridian-crossing bbox accepted | query-shape validation | PR 12 |
| G-EDGE06 | Antimeridian-crossing polygon rejected | `UnsupportedGeoShape` validation | PR 12 |
| G-CROSS01 | Adjacent Δlon < 180° with no ±180° endpoint — not rejected for crossing | test-only reference oracle | PR 12 |
| G-CROSS02 | Adjacent Δlon > 180° — rejected | `UnsupportedGeoShape` validation | PR 12 |
| G-CROSS03 | Adjacent Δlon == 180° — rejected (ambiguous arc) | `UnsupportedGeoShape` validation | PR 12 |
| G-CROSS04 | Closing edge crosses the antimeridian — rejected | `UnsupportedGeoShape` validation | PR 12 |
| G-CROSS05 | Edge with a +180°/-180° endpoint — conservative ambiguity rule | `UnsupportedGeoShape` validation | PR 12 |
| G-CROSS06 | bbox `west=170, east=-170` — legitimate crossing bbox | query-shape validation | PR 12 |
| G-CROSS07 | Ordinary polygon near but not crossing — valid if otherwise well-formed | test-only reference oracle | PR 12 |
| GR01 | Two multivalue keys produce six unique group keys | test-only reference oracle | PR 10 |
| GR02 | Duplicate members collapse | test-only reference oracle | PR 10 |
| GR03 | Product exactly at per-document limit accepted | budget-boundary validation | PR 10 |
| GR04 | Limit + 1 rejected before allocation | `BudgetExceeded` validation | PR 10 |
| GR05 | Checked multiplication overflow rejected | test-only reference oracle | PR 10 |
| GR06 | Empty/missing/null distinction | test-only reference oracle | PR 10 |
| GR07 | Per-document and global caps enforced independently | budget-model validation | PR 10 |
| GR08 | Empty multivalue group key contributes zero groups | test-only reference oracle | PR 10 |
| BG01 | Omitted caller limit uses bounded default | effective-limit validation | PR 10/14 |
| BG02 | Requested limit under ceiling accepted | effective-limit validation | PR 10/14 |
| BG03 | Request above ceiling rejected (if recommended policy approved) | `BudgetPolicyViolation` validation | PR 10/14 |
| BG04 | Zero budget invalid | `InvalidQuery` validation | PR 10/14 |
| BG05 | Conflicting policies use strictest ceiling | effective-limit calculation | PR 10/14 |
| BG06 | Checked overflow rejected | validation | PR 10/14 |
| BG07 | Exhaustion yields a typed error with no false exact result | contract assertion | PR 10/14 |
| BG08 | Effective budget is the minimum of server, index/tenant and requested/default | effective-limit calculation | PR 10/14 |
| BT01 | Three accepted queries yield three indexed slots with mixed outcomes | ordered assembly, test-only | PR 14 |
| BT02 | Out-of-order completion retains input order | ordered assembly, test-only | PR 14 |
| BT03 | Admission failure rejects envelope with no response | envelope validation | PR 14 |
| BT04 | Completed slot retained after aggregate exhaustion | model validation | PR 14 |
| BT05 | Unfinished slots receive explicit typed failures | model validation | PR 14 |
| BT06 | No missing/duplicate slots | counted/ordered assertion | PR 14 |
| BT07 | Shared PIT conflict rejected | envelope validation | PR 14 |
| BT08 | Per-query budget exhaustion isolated | contract assertion | PR 14 |
| BT09 | Terminalization precedence cancel > aggregate budget > timeout | enum/precedence validation | PR 14 |
| BT10 | Input-index-order admission/reservation policy | documented contract policy | PR 14 |
| BT11 | Batch vs. standalone equivalence | documented conditional only | PR 14 |
| BT12 | Completed slot unchanged after later cancellation/exhaustion | model validation | PR 14 |
| BT13 | Single terminalization point per unfinished slot | model validation | PR 14 |

---

## Implementation status (PR 2 contract layer)

Contract-only phases 2–5 were delivered on `dev/query-contracts`:
`trawler_core::contract` now implements validated document/field/value types,
schema checks, the typed query AST (including the conservative A14 polygon
rules), sorting/projection/top-K/PIT/cursor shapes, aggregation contracts,
resource budgets, capability negotiation, typed errors, and first-class ordered
batch request/response contracts, with unit tests and public-API integration
tests (including the G-CROSS01–07 fixtures).

No writer, revision allocator, immutable codec, query executor, PIT reader,
ObjectStore adapter, distributed service, vector or graph functionality is
implemented. The deferred implementation-policy gates `G-DEDUP-MIN` and
`G-CANON` remain **OPEN — PRE-PR 6**.

---

## Approval ledger

**Approval record:** All A01–A25 decisions are **APPROVED** as documented, per
*Human approval in the Trawler ChatGPT conversation, 2026-10-11, following the
pushed A14 clarification.* This approval covers the v0.1 contract-only scope and
includes the A14 shorter-longitudinal-arc clarification. It does **not** resolve
the deferred implementation-policy gates `G-DEDUP-MIN` and `G-CANON`, which remain
`OPEN — PRE-PR 6`.

| ID | Decision | Proposed | Status | Reviewer / reference |
|---|---|---|---|---|
| A01 | Stable document key | byte-exact opaque UTF-8, index-scoped | APPROVED | Human approval 2026-10-11 |
| A02 | Insert/upsert/delete | Insert conflicts; Upsert wins; Delete-absent no-op; `idempotency_key` scoped `(index, caller scope)`, 24h default dedup (A02.1) | APPROVED | Human approval 2026-10-11 |
| A03 | Field types | closed typed set; decimal/binary deferred | APPROVED | Human approval 2026-10-11 |
| A04 | Cardinality | Single/Multi; absent/null/empty distinct | APPROVED | Human approval 2026-10-11 |
| A05 | Field options | indexed/stored/columnar + analyzer; explicit rejects | APPROVED | Human approval 2026-10-11 |
| A06 | Numeric semantics | no coercion; finite floats; checked overflow | APPROVED | Human approval 2026-10-11 |
| A07 | IP normalization | family-separated; mapped IPv6 preserved by default | APPROVED | Human approval 2026-10-11 |
| A08 | CIDR | /0–/32, /0–/128; reject host bits; family mismatch false | APPROVED | Human approval 2026-10-11 |
| A09 | EXISTS/MISSING/NULL | EXISTS = present; MISSING = absent; IS NULL = explicit null | APPROVED | Human approval 2026-10-11 |
| A10 | IN/NOT IN | any-member; null/missing excluded from NOT IN | APPROVED | Human approval 2026-10-11 |
| A11 | JSONPath subset | `$`, `.member`, `["member"]` (double-quoted JSON), `[index]`, `[*]` as `JsonPathExpr` | APPROVED | Human approval 2026-10-11 |
| A12 | JSON ancestry | `JsonPathExpr`/`ConcreteJsonPath`/`JsonNodeRef` = key+revision+concrete path; correlation deferred | APPROVED | Human approval 2026-10-11 |
| A13 | Timestamps | i64 µs UTC; floor; half-open; start>end error | APPROVED | Human approval 2026-10-11 |
| A14 | Geo | WGS84 lon/lat; outer/hole boundary rules; reject self-intersection; reject antimeridian-crossing polygon via shorter-arc (abs(Δlon) >= 180°) (`UnsupportedGeoShape`) | APPROVED | Human approval 2026-10-11 |
| A15 | Sorting | total order; nulls last default; Min/Max selector; key tie-break | APPROVED | Human approval 2026-10-11 |
| A16 | Group-by | multi-key; checked expansion caps; empty multivalue key -> zero groups; null/missing distinct | APPROVED | Human approval 2026-10-11 |
| A17 | Exact distinct | per-document membership; null excluded | APPROVED | Human approval 2026-10-11 |
| A18 | Top-K frequency | per-document; count desc then value asc | APPROVED | Human approval 2026-10-11 |
| A19 | Aggregates | checked sum/avg; empty None; epoch-aligned buckets | APPROVED | Human approval 2026-10-11 |
| A20 | Budgets | effective-limit precedence; above-ceiling rejected (`BudgetPolicyViolation`); no truncation | APPROVED | Human approval 2026-10-11 |
| A21 | PIT/cursor | opaque; snapshot+sort+key binding; typed expiry/mismatch | APPROVED | Human approval 2026-10-11 |
| A22 | Capabilities | required fails, optional ignored | APPROVED | Human approval 2026-10-11 |
| A23 | Projection | Source XOR stored fields; no expressions | APPROVED | Human approval 2026-10-11 |
| A24 | Error taxonomy | single stable typed error enum + Amendment 01/Round 02 additions (`UnsupportedGeoShape`) | APPROVED | Human approval 2026-10-11 |
| A25 | Batch | ordered exactly-N outcomes; input-index-order reservation; cancel > aggregate budget > timeout | APPROVED | Human approval 2026-10-11 |

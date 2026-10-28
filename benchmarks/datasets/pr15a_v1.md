# `pr15a_v1` — frozen PR 15A regression fixture

**Version:** `pr15a_v1` (immutable once merged; any semantic change requires a
new version and invalidates downstream PR 15B/15D/15E baselines).

This document is the human-readable contract for
`benchmarks/datasets/pr15a_v1.json`. Test code implements the same literal
records from a static Rust table; expected query results are independently
enumerated from those records and are **never** derived from a Quervant search
or writer result.

## 1. Freeze record

| Item | Value |
|---|---|
| Canonical file | `benchmarks/datasets/pr15a_v1.json` |
| Canonical SHA-256 | `104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087` |
| Canonical size | 2408 bytes |
| Git blob id | `90828bbd1bc3f4a4b0a0bb59029fe93bb64cd2f9` |
| Seed | none (fully static fixture) |
| Digest tool | external GNU `sha256sum`; tests recompute with the existing RustCrypto `sha2` dependency (no handwritten digest) |

The test-owned constant `PR15A_V1_SHA256` in
`crates/quervant-core/tests/pr15a_common/mod.rs` must equal the SHA-256 above.
A-T00 recomputes the digest twice in one process and asserts determinism.

## 2. Schema and analysis

The fixture uses the existing PR 14 public schema (`pr14_common::schema`), with
these fields populated:

| Field | Type | Options | Analysis |
|---|---|---|---|
| `title` | Text | indexed, stored | `standard_folded` |
| `host` | Keyword | indexed, stored, sortable | default keyword handling |
| `n` | I64 | indexed, stored, sortable | none |
| `ts` | Timestamp (microseconds) | indexed, stored, sortable | none |
| `ip` | IpAddress | indexed, stored, sortable | none |
| `body` | Json | indexed, stored | concrete `$.severity`, `$.tags` paths |

`tags` is the existing multi-value Keyword field from the PR 14 schema but is
not populated in the canonical JSON body; the JSON `body.tags` array is the
JSON witness, not a document field. `loc` (GeoPoint) is not populated by these
eight rows; geo uses the existing `pr12_geo` fixture and its independent
oracle.

Timestamp literals are integer microseconds. The contract expresses the
requested inclusive window `[2000, 5000]`. Quervant's existing `TimeRange`
operator is half-open `[start, end)` (`pr10_time.rs:16`), so the test evaluates
the equivalent `TimeRange { start: 2000, end: 5001 }`. This is an exact
re-expression, not a semantic change.

## 3. Segment membership and insertion order

Segment 0 (first commit, insertion order): `a0, a1, a2, a3`.

Segment 1 (second commit, insertion order): `b0, b1, b2, b3`.

## 4. Records

| Key | Seg | title | host | n | ts | ip | body |
|---|---|---|---|---|---|---|---|
| `a0` | 0 | `alpha beta` | `h1` | 10 | 1000 | `10.0.0.1` | `{"severity":1,"tags":["red","blue"]}` |
| `a1` | 0 | `alpha` | `h2` | 20 | 2000 | `10.0.0.2` | `{"severity":2,"tags":["blue"]}` |
| `a2` | 0 | `beta` | `h1` | 30 | 3000 | `192.0.2.1` | `{"severity":3,"tags":[]}` |
| `a3` | 0 | `gamma` | `h3` | 40 | 4000 | `2001:db8::1` | `{"severity":null}` |
| `b0` | 1 | `alpha gamma` | `h1` | 50 | 5000 | `10.0.1.1` | `{"severity":2,"tags":["red"]}` |
| `b1` | 1 | `beta gamma` | `h2` | 60 | 6000 | `192.0.2.2` | `{"severity":4}` |
| `b2` | 1 | `delta` | `h3` | 70 | 7000 | `2001:db8::2` | `{"severity":0,"tags":[]}` |
| `b3` | 1 | `alpha` | `h2` | 80 | 8000 | `10.0.0.8` | `{"severity":5,"tags":["green"]}` |

State distinctions that must be preserved:

- `a3.body.severity` is explicit JSON `null`; `a3.body` has no `tags` key.
- `b1.body` has no `tags` key.
- `a2.body.tags` and `b2.body.tags` are explicit empty arrays.
- No canonical row has an absent `body` field.

## 5. Independent truth table

Sorted lexicographically unless stated.

| Predicate | Expected keys |
|---|---|
| `title=alpha` | `a0, a1, b0, b3` (4) |
| `n >= 50` | `b0, b1, b2, b3` (4) |
| `title=alpha AND n>=50` | `b0, b3` (2) |
| `host=h2` | `a1, b1, b3` (3) |
| `ip IN 10.0.0.0/24` | `a0, a1, b3` (3) |
| time `[2000,5000]` inclusive | `a1, a2, a3, b0` (4) |
| `title=alpha AND host=h2` | `a1, b3` (2) |
| host group counts | `h1:3, h2:3, h3:2` |
| exact distinct hosts | `3` |

Additional derived facts:

- `title=alpha` must not match `a2` (`beta`), `b1` (`beta gamma`) or `b2`
  (`delta`).
- `ip IN 10.0.0.0/24` must not match `b0` (`10.0.1.1`) nor any IPv6 row.
- `ip IN 2001:db8::/32` matches `a3, b2` (2).
- `body.severity = 2` (integer) matches `a1, b0`; the string `"2"` matches none.
- `body.severity` `null`/absent never matches a scalar equality.
- `NOT title=alpha` matches `a2, a3, b1, b2` (4) because every row has
  `title`; `a3` (`gamma`) does not contain the alpha token.
- IPv4 CIDR `/0` matches every IPv4 row (`a0, a1, a2, b0, b1, b3`) and no IPv6
  row.
- Full `n`-ascending order is `a0,a1,a2,a3,b0,b1,b2,b3`.

## 6. Snapshot mutation sequence (separate from the base fixture)

Start from committed generation 2 (the two segments above), retain a PIT on
that generation, then apply one atomic durable batch:

1. Upsert `a1` retaining `title=alpha`, changing `host` to `h9` and `n` to `25`
   (other fields unchanged).
2. Delete `b1`.
3. Insert `c0`: `title=alpha`, `host=h1`, `n=90`, `ts=9000`,
   `ip=10.0.0.9`, `body={"severity":6,"tags":[]}`.

Commit generation 3, then reopen a **new** reader handle. A subsequent forced
compaction commits generation 4; the retained generation-2 PIT remains
immutable across both commits.

| Expectation | Keys |
|---|---|
| Old PIT live keys (unchanged generation 2) | `a0,a1,a2,a3,b0,b1,b2,b3` |
| New live keys | `a0,a1,a2,a3,b0,b2,b3,c0` |
| New `title=alpha` | `a0,a1,b0,b3,c0` |
| Old `host=h2` | `a1,b1,b3` |
| New `host=h2` | `b3` |
| Old `a1.host` / `a1.n` | `h2` / `20` |
| New `a1.host` / `a1.n` | `h9` / `25` |

Snapshots are never compared as if interchangeable. The mutation batch carries
a fixed idempotency token; durable replay must return the same response without
a second state transition.

## 7. Validation rules

- A-T00 asserts the static truth table, segment membership, uniqueness and
  digest determinism before any index is built.
- An intentional wrong-set negative proves the oracle helper rejects a missing
  key; the negative is asserted with `assert_ne!` so the suite stays green.
- No test may replace a field with an unsupported constructor. If a canonical
  field cannot be represented with an existing supported constructor, that test
  is a HARD STOP (X03) rather than a silent omission.
- Any semantic edit to the JSON file (record, predicate, segment, or mutation)
  requires a version bump and a new SHA-256 freeze record.

# PR 14G — Phase B: exact selected physical hit projection (CW-055 / CW-068)

**Executed:** `2026-10-28` on branch `test/pr14g-final-acceptance`, baseline
`054ca55d143e89a092cc6519231b820fecfa42dc` (Phase A commit `e4d7237`).
**Status:** `PASS` for CW-055 and CW-068 — the physical-tuple proofs *and* the
negative key-latest discriminator executed and passed.

## 1. Scope and seam

All Phase B code is inside the **existing** `#[cfg(test)] mod tests` of
`crates/quervant-core/src/search/unified.rs` (module starts at line 1323). The
diff is purely additive at the end of that module (`git diff -U0` shows
`0` removed lines). Nothing in the compiled library path changed:

- `SelectedHit` fields/visibility unchanged; no `HitRef` or public API added;
- `collect_mixed`, `project_selected_hits` and `ProjectionPlan::project` unchanged;
- the `reader.doc_key(hit.doc_id)? == hit.key` guard was not weakened;
- no persisted bytes, manifest or codec were touched.

Test-only helpers live in the same module:

| Helper | Purpose |
|---|---|
| `g_schema` / `g_doc` / `g_index` | three-field (text + keyword + i64) fixture; `g_index` commits exactly one immutable segment per supplied group and reopens |
| `g_reopen` | reopens the committed generation, because an `Index` handle never tracks later writers; the old pinned snapshot stays alive |
| `g_mixed_request` | mixed `AND[Term(title,"alpha"), Range(n,0..=100)]` request with explicit non-key sort |
| `g_select` | builds the **real** selected-hit stream: `unified_plan::compile` → `unified_cursor::fingerprint` → `UnifiedSearcher::collect_mixed` (normal budgets, `NeverCancel`) → `project_selected_hits`; returns `GSelection { hits, fields, total, projection }` |
| `g_physical_oracle` | derives the expected projection from the exact physical `(segment_index, doc_id)` via `snapshot.open_segment_reader(...)`, asserts `reader.doc_key(doc_id) == hit.key`, then `projection.project(&reader.stored_doc(doc_id))` — no key lookup, no rescan |
| `g_key_latest_projection` | the deliberately naive key-based shortcut under test (scan effective-live physical docs for a key, project it); used only as a discriminator |
| `g_keys` / `g_tuple` / `g_position` / `g_projected` / `g_keyword` | ordering and field helpers |

## 2. Tests, physical tuples and witnesses

### B01 — `g_b01_selected_physical_hit_projection_exact`

Three immutable segments, four documents (`k1` n=30, `k2` n=10, `k3` n=20,
`k4` n=40/gamma), explicit `n` descending sort. Selected hits (observed trace):

```text
[pr14g][b01] selected (segment,doc,key,host) = [(0, 0, "k1", "h1"), (2, 0, "k3", "h3"), (0, 1, "k2", "h2")]
```

Witnesses actually asserted:

- `total_hits == 3`, selected order `["k1","k3","k2"]` — a non-key order
  (`k1,k2,k3` sorted by `n`), so projection order cannot be reproduced by a
  key-ordered rescan;
- every selected `(segment_index, doc_id)` is re-opened and its `doc_key` equals
  the selected `key`, and the oracle projection equals
  `project_selected_hits(...)` at the same position (`h1`, `h3`, `h2`);
- selected physical tuples are pairwise distinct;
- end-user `UnifiedSearcher::search` returns the identical `total_hits`, key
  sequence and projected fields in the **selected-hit sequence**;
- `k4` (`gamma`) is correctly absent from the `alpha` match set.

`(0,0)/(0,1)/(2,0)` also documents that segment index order follows the
content-addressed manifest ordering, not commit order — an additional reason a
key-only oracle is not interchangeable with physical identity.

### B02 — `g_b02_old_new_pit_upsert_physical_identity`

Corpus `stable` (`host="before"`, n=30), `other`, `third`. Old pin acquired
before a real `MutationRequest::upsert` of `stable` (`host="after"`, same title
and `n`) plus commit; a **new** generation handle is opened and pinned afterwards.

```text
[pr14g][b02] stable physical identity old=(1, 0) new=(2, 0)
```

Witnesses actually asserted:

- old tuple `(1,0)` ≠ new tuple `(2,0)`: the two versions of the same logical
  key are physically distinct documents in distinct immutable segments;
- the old projection is `host="before"` and the new projection is
  `host="after"`;
- each projection equals its own snapshot's physical-record projection
  (`g_physical_oracle` on the old snapshot and on the new snapshot);
- re-selecting on the retained old pin after the mutation returns unchanged
  tuples, fields and `host="before"` — the old pin never resolves through the
  current key map;
- old and new physical records differ for the same logical key.

### B03 — `g_b03_deleted_and_tied_sort_no_leak`

Corpus `tie-a` (n=10), `doomed` (n=5), `tie-b` (n=10), ascending `n` sort; old
pin before a real delete of `doomed`, new generation handle afterwards.

```text
[pr14g][b03] old_keys=["doomed", "tie-a", "tie-b"] new_keys=["tie-a", "tie-b"] doomed_tuple=(0, 1)
```

Witnesses actually asserted:

- the new snapshot excludes `doomed` entirely (no projection, no key leak);
- the tied `n=10` pair is ordered deterministically (`tie-a` then `tie-b`) and
  repeated executions on the same snapshot produce the identical order;
- new-snapshot projection order equals the physical oracle order, `h1` then `h3`;
- the old pin still sees `doomed` at its original physical tuple `(0,1)` with
  unchanged fields.

No artificial duplicate **live** key exists in one generation: old and new are
independent committed generations, as required.

### B04 — `g_b04_mismatched_selected_hit_is_corrupt_index`

A genuine selected hit is cloned test-locally and **only its key** is replaced
with another valid selected key while the physical `(segment_index, doc_id)` is
retained. `project_selected_hits` then returns `SearchError::CorruptIndex`
(asserted with `matches!`), which proves the key guard is live. Control: the
honest hits still project exactly the B01 fields. Persisted bytes and selector
internals are untouched.

### B05 — `g_b05_regression_against_key_only_oracle`

After the same upsert as B02:

- the retained old physical projection is `host="before"`;
- the **key-latest** shortcut evaluated against the *new* snapshot resolves the
  same logical key to `host="after"`;
- `assert_ne!(old_physical_projection, key_latest)` — so output-only parity
  cannot satisfy this invariant: an implementation that rescans by logical key
  would produce the current version and fail this discriminator;
- the new snapshot's selected physical projection equals its own key-latest
  value (`"after"`), confirming the discriminator isolates snapshot selection
  rather than the projection code.

## 3. Commands and results (Phase B)

| Command | Result |
|---|---|
| `cargo test -p quervant-core --lib search::unified::tests` | PASS — `31 passed; 0 failed` (26 pre-existing + 5 new) |
| `cargo test -p quervant-core --all-features --lib search::unified::tests` | PASS — `31 passed; 0 failed` |
| `cargo +1.85.0 test -p quervant-core --lib search::unified::tests` | PASS — `31 passed; 0 failed` |
| `cargo +1.85.0 test -p quervant-core --all-features --lib search::unified::tests` | PASS — `31 passed; 0 failed` |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -- -D warnings` (stable, and with `--all-features`) | PASS |
| `cargo +1.85.0 clippy --workspace --all-targets -- -D warnings` (and with `--all-features`) | PASS |
| diff inspection | production-file diff is **additive inside `mod tests` only** (`0` removed lines) |

## 4. Row dispositions

| CW row | Prior generation | Disposition after Phase B | Evidence |
|---|---|---|---|
| 055 | §5.3 `I07` projection uses the selected physical hit, not a key rescan | `PASS` | B01 exact physical tuples + B03 deletion/tie ordering + B04 corrupt-index negative + B05 key-latest discriminator |
| 068 | §5.4 `I8` same identity across duplicate logical key, mutation and PIT | `PASS` | B02 old/new PIT physical identity, B03 old-pin stability, B05 shortcut regression |

CW-041 and CW-127 remain `BLOCKED` pending explicit human decisions (Phase C).
CW-087 remains open until the consolidated final gates and independent review.

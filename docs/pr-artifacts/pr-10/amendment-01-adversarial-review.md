# PR 10 Amendment 01 — Adversarial Review (pre-implementation)

**Date:** 2026-10-14
**Branch:** `dev/temporal-retrieval`
**HEAD at Phase 0:** `05c8d89ac6f364ff4132bb4ac33788cf8fc38042`
**Merge-base against `main`:** `2ecbbe2bb3ca1b9fe0e33827c94d03df0a6874a7`
**Tree:** clean at Phase 0 (PR 10 implementation is committed as `05c8d89`).

## Defect

`crates/quervant-core/src/index/snapshot.rs`:

```rust
static NEXT_SNAPSHOT_BINDING: AtomicU64 = AtomicU64::new(1);
...
binding_id: NEXT_SNAPSHOT_BINDING.fetch_add(1, Ordering::Relaxed),
```

`fetch_add` wraps on overflow. At counter `u64::MAX` it returns `u64::MAX` and
wraps the counter to `0`; the next allocation returns `0` and sets `1`, after
which IDs already issued at the start of the sequence are reissued. That breaks
the uniqueness contract `TypedCursor` relies on for snapshot binding.

### Adversarial counterexample (transition table)

| Initial | Operation | `fetch_add` return | New counter | Consequence |
|---|---|---|---|---|
| `u64::MAX` | allocate | `u64::MAX` | `0` | reserved-ID/wrap |
| `0` | allocate | `0` | `1` | returns `0` |
| `1` | allocate | `1` | `2` | reissues `1` |

The typed cursor validates `snapshot_binding` and would accept a cursor from an
unrelated snapshot if a reused ID matched. Generation/view alone are not unique
across `Index::snapshot()` calls, so the binding is load-bearing.

## Reconciliation of existing PR 10 work

| Item | State before amendment |
|---|---|
| Typed scan, cursor fingerprint, per-segment `ColumnReader`, analytics, limits, pruning | DONE as implementation, previously tested |
| Monotonic allocator exhaustion behavior | **PARTIAL/DEFECTIVE** |
| Amendment-01 boundary tests | NOT STARTED |
| Amendment-01 final-tree evidence | NOT STARTED |

No working PR 10 subsystem is rewritten.

## Invariant → test mapping

| ID | Invariant | Tests |
|---|---|---|
| A1-I01 | unique nonzero strictly increasing IDs `1..u64::MAX` | A1-T01, T02, T04 |
| A1-I02 | `MAX-1` is last success, sets sentinel `MAX` | A1-T03 |
| A1-I03 | at `MAX` panic, sentinel unchanged, never `0`/wrap | A1-T04 |
| A1-I04 | concurrent uniqueness; exhausted contenders cannot change sentinel | A1-T05, T05b |
| A1-I05 | snapshot identity immutable; distinct snapshots differ; Arc clone shares | A1-T06, T07 |
| A1-I06 | cursor valid same snapshot, rejected different snapshot | A1-T08, T09 |
| A1-I07 | snapshot/PIT/refresh/commit/compaction unchanged for non-exhausted state | A1-T10, existing PR 9/10 suites |

## STOP-gate decision

- `ReaderSnapshot::build` is infallible (`-> Self`); `new` and `new_with_masks`
  delegate to it. **Go.**
- `fetch_add` still present exactly once. **Go.**
- Typed cursor is process-local and checked before scanning. **Go.**
- Fix requires only a private allocator function and one call site; no public API,
  wire, CURRENT, format or lexical change. **Go.**

**Decision: GO.**

## Post-implementation outcome

The checked allocator from §4 was implemented in
`crates/quervant-core/src/index/snapshot.rs` and the single `fetch_add` call site
was replaced with `allocate_snapshot_binding(&NEXT_SNAPSHOT_BINDING)`. No other
production file changed.

The table below is the executed behavior (A1-T01–T04, T05, T05b):

| Initial counter | Operation | Return | New counter | Outcome |
|---|---|---|---|---|
| `1` | allocate | `1` | `2` | success |
| `u64::MAX - 2` | allocate | `u64::MAX - 2` | `u64::MAX - 1` | success |
| `u64::MAX - 1` | allocate | `u64::MAX - 1` | `u64::MAX` | last success |
| `u64::MAX` | allocate | none | `u64::MAX` | explicit panic, sentinel unchanged |
| `0` | allocate | none | `0` | explicit panic, never issues reserved `0` |
| `MAX-4`, 8 racing threads | allocate | 4 successes, 4 panics | `u64::MAX` | no duplicate binding |

### Residual risk (accepted)

- Exhaustion is astronomically unlikely; the explicit panic is deliberate
  fail-closed behavior of an infallible internal constructor, not graceful
  degradation.
- `Relaxed` ordering is sufficient for identity uniqueness; it is not a
  synchronization mechanism for snapshot contents (publication remains owned by
  the existing `Arc`/snapshot logic).
- IDs are process-local; a restart reuses numeric IDs by design. `TypedCursor` is
  explicitly nonportable across processes.
- No wire-format, `CURRENT`, merge, lexical or persistent-identity guarantee is
  implied.

No semantic conflict or unapproved deviation was encountered; no STOP condition
was triggered.

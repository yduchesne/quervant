# PR 9 reclamation safety

## Decision: dry-run planning only, no online deletion

PR 9 does **not** implement destructive garbage collection. The verified
constraints from the plan remain true in this tree:

- Independent `Index::open_existing` handles own independent `PinCounter`s.
  Observing one counter cannot prove no other live reader exists.
- There is no cross-process reader-exclusion protocol. `index/WRITER_LOCK`
  excludes writers only, not readers.
- `Directory::list` is bounded (`list(prefix, limit)` fails closed when
  exceeded) and is not proof of a complete inventory.
- No durable generation/object inventory is persisted yet, so exact lineage of
  an unreferenced object cannot be verified.

## What `Index::reclamation_plan` does

`reclamation_plan()` reads the authoritative `CURRENT` generation and scans a
bounded inventory of `index/manifests`, `index/segments`, `index/state` and
`index`. It classifies:

| Class | Meaning |
|---|---|
| `CURRENT_REACHABLE` | The current manifest, its referenced segments and its mutation-state sidecar (`CURRENT` itself included). |
| `HISTORICAL_REACHABLE` | Objects referenced by an older but still-present manifest. |
| `ORPHAN_CANDIDATE` | Never produced in PR 9: no persisted lineage inventory exists, so an unreferenced object cannot be proven orphaned. |
| `UNKNOWN` | Everything not provably reachable. Never deletable. |

`online_deletion_supported` is always `false` and `has_deletable_objects()` is
always `false`. `complete_inventory` reports whether every prefix scan fit
inside `INVENTORY_LIMIT`; an incomplete scan still produces `UNKNOWN`, never a
deletion candidate.

## Observability

The plan intentionally forbids inferring safety from object age, a single PIT
counter or a truncated listing. Because a generation/object inventory is not
persisted, the conservative default is to retain all old manifests, segments
and sidecars. Operators must treat old on-disk generations as retained until a
future offline-maintenance protocol with verified exclusive access exists.

## Tests

- T31: current generation objects are never candidates; `unknown` is empty and
  no deletion is reported.
- T32: an independently opened `Index` handle plus a live PIT still resolve
  their pre-mutation results; historical objects are retained, not candidates.
- T33: an orphan object left by a simulated crash (written before `CURRENT`) is
  classified `UNKNOWN`, never `ORPHAN_CANDIDATE`, and never deletable.

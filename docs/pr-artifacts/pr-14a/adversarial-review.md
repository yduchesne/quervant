# PR 14A — adversarial review

| Risk challenged | Evidence / disposition |
|---|---|
| Key-only resume could accept a different sort tuple | Legacy `Cursor::new` has no continuation and is rejected with `CursorSortMismatch`; only complete V1 tuples resume (T10, T12). |
| Same key with changed query/sort could pass | Fingerprint and public sort are checked before execution; T07 asserts typed `CursorSortMismatch`. |
| Cursor from another snapshot could read current data | The pinned API uses only `pit.snapshot()`; wrong handle/PIT fails typed and never falls back (T06). |
| Expiry could be renewed with a later requested deadline | Returned expiry is `min(incoming expiry, requested deadline)`; T10 resumes only before the original deadline. |
| Cursor bytes bypass response/memory budgets | Response bytes include the cursor formula and T11 exercises exact/one-over response and memory boundaries. |
| Cursor failure erases sibling slots | T08 has exactly three ordered outcomes with only the middle expired slot failing. |
| Cancellation emits a partial cursor | T13 cancels at a later slot boundary; prior success remains, cancelled slot emits no cursor. |
| Pinned mutation view could drift | T09 retains the old PIT across upsert/delete/insert/refresh/commit/compact and compares the full old order; a new PIT sees the new generation. |
| Cursor is secretly a wire format | No serde/base64/wire parsing; continuations are private Rust values and are explicitly process-local. |

Residual risks are recorded in `implementation-evidence.md`. Real-RustFS and
broader fault qualification remain 14B work.

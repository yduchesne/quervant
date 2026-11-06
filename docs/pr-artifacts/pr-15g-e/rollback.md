# PR 15G-E rollback proof

**Rejected implementation commit:** `62d35c262fa667673ee6d8701ca9ef75daf17a53`
**Additive rollback commit:** `e2bdf48cd88f6780e6c833001fec537ba218c3d4`

The rollback reverts the E production format, writer emission and reader fast
path to the accepted A+B implementation. The format-aware benchmark tooling is
retained as non-production evidence. The E-only Rust integration test is removed
with the rejected implementation because it cannot compile without E.

Proof:

```sh
git diff --quiet ca065a212987284144d8901aa5c54de093d6dbfc -- \
  crates/quervant-core/src/segment \
  crates/quervant-core/src/index/support.rs \
  crates/quervant-core/src/search
```

Exit status: `0`.

E codec/wire details and the negative performance result remain in Git history
and sanitized documentation; no historical D/C evidence was rewritten.

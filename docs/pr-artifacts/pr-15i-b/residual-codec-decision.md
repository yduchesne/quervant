# PR 15I-B residual — codec decision

**Selected codec: LZ4** (`B_LZ4_RESIDUAL_SHA`
`5703a3dfd62b67bf0413b8542c420dbd5c986fe9`; measured production bytes preserved
in final code SHA `9da20614f58313259fcceb5ff8fa997e6afc7d7c`).

| Codec | Campaign | Seal | Gates | Decision |
|---|---|---|---|---|
| LZ4 | `lz4-residual-01` | `b5cf7fd4…5bf740` | all B-P03..B-P13 PASS | **eligible** |
| Zstd1 | `zstd-residual-01` | `2a589854…9b4c61` | B-P06 FAIL (10K rare 1.1923) | ineligible |

Only one codec is eligible, so the tie-break rule does not apply. The retained
production tree is exactly the measured LZ4 tree plus a test-only RustFS fix and
the single approved CI invocation; `git diff 5703a3d..9da2061 --
crates/quervant-core/src crates/quervant-core/Cargo.toml Cargo.lock` is empty.

Zstd evidence remains sealed as a negative result and is not shipped.

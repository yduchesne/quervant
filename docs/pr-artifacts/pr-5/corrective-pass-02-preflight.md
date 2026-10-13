# PR 5 corrective pass 02 preflight

> Narrow fixup for R5-I08/R5-I09 on `dev/segment-codecs`. No F01–F12 wire change,
> no golden change, no merge. Baseline report only.

## 1. Baseline reconciliation

| Fact | Value |
|---|---|
| Branch | `dev/segment-codecs` |
| Pre-fix HEAD | `75134b84208df3eb1b08c7a1cf57baa121181bf2` (matches plan) |
| `origin/main` | `a23cf25798e52fc181e93ac84505a07412f37463` |
| `75134b8` ancestor of HEAD | yes |
| `git status --short` | clean before edits |
| `git diff --stat origin/main...HEAD` | PR 5 implementation + artifacts |
| Rust | `rustc 1.85.0 (4d91de4e4 2025-02-17)` |

No divergence, no unrelated working-tree changes. No upstream change to the
targeted contracts.

## 2. Targeted baseline execution

`cargo +1.85.0 test -p trawler-core --test segment_corrective` (pass-01 suite)
and the full workspace suite run clean on the baseline; the defects are not
covered by existing tests.

## 3. Source inspection

- `reader.rs::read_all` passed `&mut bytes[offset..]` to `read_at`, requesting up
  to the entire remaining object in one call and ignoring `max_read_bytes`.
- `manifest.rs::decode` kept a `BTreeSet<String>` of cloned object keys plus a
  cloned `previous_id`, while `retained_bytes` charged only the struct size and
  one string per entry — not the duplicate-key clone payload, feature vector
  backings, or the segments vector backing.

## 4. Failing-before evidence (R5-I08)

Temporary worktree at `75134b8`, baseline-compatible reproducer using default
`max_read_bytes` (1 MiB) and an instrumented `ReadHandle` that rejects requests
>1 MiB, against a valid >1 MiB segment:

`cargo +1.85.0 test -p trawler-core --test p2_baseline_repro`
→ **0 passed / 1 failed**: `Storage(Corrupt …)` because the baseline requested
the whole segment in one call. The fixed chunked reader passes the same
reproducer (`c6_baseline_oversized_read_reproducer`). Worktree removed.

## 5. Failing-before evidence (R5-I09)

The baseline has **no** `max_section_decode_bytes` setter and no retained-charge
accessor, so a deterministic runtime red cannot be produced at practical sizes
without new test-only API. Per the plan, the discrepancy is documented at the
code level (§3) and the corrected charge is proven by a deterministic boundary
test on the fixed tree:

- `Manifest::retained_bytes()` reports the conservative charge.
- `c6_u16_u19_u20_retained_budget_boundaries` shows exact-budget accepted and
  one-below/well-below rejected.
- `c6_i04_public_retained_bytes_is_conservative` shows the charge exceeds the
  naive string-only estimate.

No fabricated red result is claimed.

## 6. Gate outcome

PASS; no STOP condition. Proceeding to Phases B–G. A narrow
`with_max_read_bytes` and `with_max_section_decode_bytes` policy setter were
added (configuration only; no wire/format/public-Directory change).

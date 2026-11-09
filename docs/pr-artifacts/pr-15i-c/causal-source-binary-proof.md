# PR 15I-C causal experiment — source and binary proof

## 1. Commit identities (actual local Git objects)

| Role | SHA |
|---|---|
| `BASE_A` (merged PR 15I-B) | `6f6463cb26bcf28340cc9d4afd4dfeb040281898` |
| `START` | `8541c8edcf70f84c89cbea6ea6dc4c711446ec84` |
| Historical outside-dispatch candidate | `92a741876f6f6823d9d1792fc391dbb1bbecceb0` |
| `RESTORED_B_SHA` | `b32523b9bb182190cb8260b00c3a81645314837f` |
| `CAUSAL_BC_SOURCE_SHA` | `658a2dde0e15c17e2b0c92278b5c922f5260fe60` |
| `CAUSAL_TOOLING_SHA` (first freeze) | `a426c6ae7225987cc09d9056a4d835483822235a` |
| Tooling fixups (pre-sampling, then post-sampling verifier-only) | `9f667c9`, `cf419dd`, `888b1ae`, `7334a9c`, `d996441`, `58780e4`, `45fe886e` |

`RESTORED_B_SHA` restores exactly the seven historical candidate files; every
`git hash-object` equals the `92a7418` blob. `CAUSAL_BC_SOURCE_SHA` adds only:

* `crates/quervant-core/Cargo.toml`: `pr15ic-causal = []` (non-default);
* `crates/quervant-core/src/search/unified.rs`: the shape/mode dispatch binding
  and the `OnceLock` helper.

`git diff --name-only RESTORED_B_SHA..CAUSAL_BC_SOURCE_SHA -- 'crates/**'` is
exactly those two files. `git diff --name-only BASE_A..CAUSAL_BC_SOURCE_SHA --
'crates/**'` is exactly the seven restored paths (no index/segment/storage/
contract/CI/lock change).

## 2. Generic collector identity

| Source | `collect_mixed` normalized body SHA-256 |
|---|---|
| `BASE_A` | `00c5a1c82f5a60bc1b5a4886a137637ac31f64eb7f5260fad9237c2935391994` |
| `CAUSAL_BC_SOURCE_SHA` | identical |
| attributes | `#[allow(clippy::needless_option_as_deref)]`, `#[allow(clippy::too_many_arguments, clippy::type_complexity)]` — **no inline attribute** |

The physical collector keeps its historical `#[inline(never)]`; the generic
collector has none, and the experimental gate is the only runtime branch.

## 3. Feature and gate proof

* `pr15ic-causal = []` exists only in the candidate; `BASE_A` does not contain it.
* It is **not** in `default = [...]`, and `cargo build --release --offline` of the
  frozen adapter with default features contains **zero** occurrences of
  `QUERVANT_PR15IC_CAUSAL_MODE` (string scan) and **no** `pr15ic_causal_enabled`
  symbol; in that build the environment variable is ignored and every mode answers
  identically.
* In the feature build the truth table is exact (verified in separate processes):
  `enabled` → ok (specialized), `disabled` → ok (generic), unset or malformed →
  typed `corrupt index state: invalid PR15IC causal experiment mode`.

## 4. Binary identities per campaign

| Campaign | A adapter SHA-256 (prefix) | BC adapter SHA-256 (prefix) | A ≠ BC |
|---|---|---|---|
| causal-unbatched-01 | `483e6264c838` (derived) / base | `c376075f313e` (derived) / causal | yes |
| causal-batched-01 | derived base adapter | the one causal derived adapter | yes |
| causal-unbatched-02 | base adapter | causal adapter | yes |
| causal-batched-02 | derived base adapter | the one causal derived adapter | yes |

B and C always share one absolute executable path and SHA-256 inside a campaign;
the full hashes are in each campaign's `raw/manifest.json`,
`raw/toolchain.json` and each slot record (both at the slot and per-lane process
level). The verifier re-hashes the actual files and rejects a different BC path
(`CV_BINARY`).

## 5. Format proof

Twelve fresh rebuilds per campaign (3 per arm per N). Both arms produce identical
committed bytes, sidecar bytes, segment bytes and segment SHA-256 digest per N;
all use STORED v2 with codec id 1 and required feature `[13, 1]`; the merged
baseline's 100K sentinel is exactly `15,747,551` committed and `1,661,455` STORED
bytes. Batched campaigns additionally build a derived adapter with the single
deterministic `query_batch` hunk for both arms, with the causal feature enabled
only on the BC copy.

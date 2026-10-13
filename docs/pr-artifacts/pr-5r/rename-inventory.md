# PR 5-R — Rename inventory and occurrence classification

**Plan:** `QUERVANT_PR_5R_DETAILED_RENAMING_PLAN.md`
**Branch:** `dev/quervant-rename`
**Baseline `main` SHA:** `c735dac7fb9b4a9e496a64512212d22daa92d216` (PR 5 merged; clean worktree)
**Toolchains:** stable `rustc 1.99.0 (b940084d7 2026-09-28)`, MSRV `1.85.0`

## 1. Preflight

| Check | Result |
|---|---|
| `git fetch origin --prune` | PASS |
| `git status --porcelain` before edits | clean |
| PR 5 segment codecs + golden fixture present on `main` | PASS (`crates/trawler-core/src/segment/*`, `tests/fixtures/segment/golden.seg`) |
| Branch created from verified `main` | `dev/quervant-rename` @ `c735dac` |
| Tracked files scanned | 183 |
| Case-insensitive occurrences (excluding `Cargo.lock`) | 480 across 107 files |

The reconnaissance confirmed the plan's representative inventory and additionally found the
`dev/repo-rename` local branch, which was **not** used; the rename was re-derived from `main`.

### Environment note (baseline gate failure and recovery)

The pre-existing `target/` directory was corrupt ("Structure needs cleaning") and could not be
read or fully removed; the filesystem was 95 % full. This is a build-artifact/environment
failure, not a source failure. `target/` is gitignored. It was renamed aside
(`target` → `target.corrupt`) and a fresh `target/` was built successfully (7.8 G free
afterwards). Baseline gates were then executed cleanly; see `validation-report.md`.

## 2. Classification policy applied

| Class | Disposition |
|---|---|
| A — current branding | `Trawler` → `Quervant` |
| B — Cargo/package/path | `trawler-*` → `quervant-*` |
| C — Rust imports | `trawler_*` → `quervant_*` |
| D — active test/dev identifiers | renamed (`quervant-a3-…`, `quervant-fs-offload`, `quervant-rustfs`, …) |
| E — active external configuration | `TRAWLER_*` → `QUERVANT_*` |
| F — current repo metadata | **retained** until the human rename gate passes (§8) |
| G — historical provenance | **retained** (`docs/decisions/**`, `docs/pr-artifacts/pr-3,4,5/**`, historical URLs) |
| H — persisted/wire identity | **retained** (`.trawler-tmp-*`, `trawler-analyzer-fingerprint-v1`) |
| I — golden/binary fixtures | **retained** (`golden.seg`, `golden.tsv`) |
| J — legal notices | license texts unchanged; current project labels/paths updated in `LICENSING.md` |
| K — third-party references | unchanged |

## 3. Renamed occurrences (class A/B/C/D/E)

- **Crate directories:** `crates/trawler-core` → `crates/quervant-core`,
  `crates/trawler-objectstore` → `crates/quervant-objectstore`,
  `crates/trawler-distributed` → `crates/quervant-distributed` (via `git mv`, rename detection preserved).
- **Manifests:** `[package].name`, descriptions, dependency keys and paths in root `Cargo.toml`
  and the three crate manifests.
- **Rust imports / paths:** `trawler_core`/`trawler_objectstore`/`trawler_distributed` and
  `trawler-*` references across 38 source/test/doc-in-crate files.
- **`project_name()`** string literals in `quervant-core`, `quervant-objectstore`,
  `quervant-distributed` (branding only; not part of any persisted identity or hash input).
- **Disposable test/dev identifiers:** `quervant-a3-…`, `quervant-a4-…`, `quervant-fs-unit-…`,
  `quervant-fs-offload`, `quervant-pr5-…`, `quervant-test-…`, `quervant-p2-…`.
- **Active configuration:** `TRAWLER_F02_DIR` → `QUERVANT_F02_DIR`;
  `TRAWLER_PRODUCTION_S3_ADAPTER` → `QUERVANT_PRODUCTION_S3_ADAPTER`;
  harness project/container/credentials `trawler-rustfs-pr3`/`trawler-rustfs`/
  `trawler-test-access`/`trawler-test-secret` → `quervant-*`; example prefixes `quervant-<pr>-<random>`.
- **Active documentation:** `README.md`, `AGENTS.md`, `LICENSING.md`,
  `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/ROADMAP_V01.md`, `docs/BENCHMARKING.md`,
  `docs/TESTING.md`, `docs/STREAMING_SEARCH.md`, `docs/DETAILED_PR_PLAN_AUTHORING_GUIDE.md`.

## 4. Retained occurrences (must NOT change)

| Location | Count | Class | Reason |
|---|---|---|---|
| `docs/decisions/**` | 53 | G | Historical ADR decision text and approval records; not rewritten. |
| `docs/pr-artifacts/pr-4/**` | 92 | G | Merged PR report artifacts; historical provenance. |
| `docs/pr-artifacts/pr-5/**` | 55 | G | Merged PR report artifacts; historical provenance. |
| `docs/pr-artifacts/pr-3/**` | 7 | G | Merged PR report artifact; historical provenance. |
| `docs/ROADMAP_V01.md` | 3 | G | Historical GitHub PR/CI URLs (lines 19–21). Branding/crate names in the same file were renamed. |
| `crates/quervant-core/src/analysis/analyzer.rs` | 1 | H | `encoder.tag("trawler-analyzer-fingerprint-v1")` is a SHA-256 input to the analyzer fingerprint embedded in segments. Renaming changes wire bytes. |
| `crates/quervant-core/src/storage/fs.rs` | 2 | H | `.trawler-tmp-<pid>-<counter>` is the durable crash-recovery marker grammar; recovery still recognizes legacy temp files. |
| `crates/quervant-core/src/storage/cache.rs` | 2 | H | Same `.trawler-tmp-` grammar in cache reconciliation. |
| `crates/quervant-core/src/storage/a3_io.rs` | 9 | H | A5 tests asserting `.trawler-tmp-*` recognition and malformed-lookalike rejection. |
| `crates/quervant-core/tests/cache_async_integration.rs` | 1 | H | Asserts `.trawler-tmp-` classification. |
| `crates/quervant-core/tests/storage_fs_integration.rs` | 1 | H | Asserts no `.trawler-tmp-` leftovers. |
| `crates/quervant-core/tests/fixtures/analysis/golden.tsv` | 1 | I | Line 1 comment in a checked-in golden fixture; regeneration is prohibited for a rename. |
| `docs/ARCHITECTURE.md` | 1 | G/H | Documents the persisted `.trawler-tmp-<pid>-<counter>` grammar. |
| `docs/TESTING.md` | 1 | G/H | Documents `.trawler-tmp-*` recovery recognition. |
| `Cargo.toml` | 1 | F | `repository = "https://github.com/yduchesne/trawler"` retained until the owner-performed GitHub rename (§8 gate). **BLOCKED.** |

### Persistence audit (no wire/identity change)

- Segment/manifest encoders, decoders, magic/version fields, field-type tags, `Directory`
  temp grammar, cache keys and object-key constructors were **not** modified. Only crate
  import paths inside those modules changed.
- `golden.seg` SHA-256 is byte-identical: `ebb07800495497c8ef4c2cef1843a8b497b7bd553cf68ac947decdcf66dae979`.
- The analyzer fingerprint tag is unchanged, so analyzer fingerprints and segment bytes are unchanged.
- `Cargo.lock` changed only by the three local package names and their interdependencies; no
  third-party version churn.

## 5. Postscan

After edits, tracked case-insensitive occurrences dropped from 480 to 230. Every remaining
occurrence is accounted for in the retained table above (or is an audit quotation inside this
`docs/pr-artifacts/pr-5r/` directory, which intentionally cites old identifiers). No active
Rust import, package/path, script, CI or external-configuration occurrence of the old name
remains.

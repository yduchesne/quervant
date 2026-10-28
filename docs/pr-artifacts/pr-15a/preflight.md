# PR 15A — P0 preflight and adversarial contract check

**Status of this document:** `PASS (EXECUTED)` for the preflight inventory and
baseline regression run recorded below. It is **not** evidence that any new PR
15A acceptance test has executed. v0.1 remains `NOT RELEASED`.

## 1. Repository baseline

| Item | Value |
|---|---|
| Base branch | `main` |
| Base SHA | `80a38643878681b2ae53f90c281b52f6aa4bd9a1` |
| Base commit | `Merge pull request #71 from yduchesne/docs/pr15-series-roadmap-authoritative` |
| PR #70 (14G) merge predecessor | `2a2bbac5` (`Merge pull request #70 from yduchesne/test/pr14g-final-acceptance`) |
| PR #71 roadmap merge | `80a3864` (this base) |
| Working branch | `test/pr15a-regression-compatibility` (created from `80a3864`) |
| Working tree before changes | clean (`git status --porcelain` empty) |
| Remote | `origin git@github.com:yduchesne/quervant.git` |

`docs/ROADMAP_V01.md` still defines the six-package **15A–15F** series
(lines 169–188) and does not redefine PR 15A semantics. The prerequisite in the
roadmap (PR 14 accepted, PR 14G merged) is satisfied by the merge commits above.
No rebase or force-push of another author's work was performed.

## 2. Toolchain and environment

| Item | Value |
|---|---|
| Stable toolchain | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| MSRV toolchain | `rustc 1.85.0 (4d91de4e4 2025-02-17)`, `cargo 1.85.0` |
| Workspace | Rust 2024, `rust-version = "1.85"`, resolver 3 |
| OS | `Linux MSI 6.18.33.2-microsoft-standard-WSL2 x86_64` |
| Workspace filesystem | native Linux filesystem under WSL2 (`ext2/ext3` reported by `stat -f`; not `/mnt/c`) |
| Temp filesystem used by tests | `/tmp` on the same native Linux filesystem |
| CPU / RAM | 12 logical CPUs / 31 GiB |
| Coverage tool | `cargo-llvm-cov` present at `~/.cargo/bin/cargo-llvm-cov` |
| Container runtime | rootless Podman; Docker CLI absent |
| RustFS image | `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| RustFS local image ID | `f6b22807f10db2aee80b8a9ed1e36bd12c2fba25ac2d98dc3b0332a23f1a5c4d` |
| RustFS container | `quervant-pr14f-rustfs`, started 2026-10-26, loopback `127.0.0.1:9000` |
| RustFS health | `GET http://127.0.0.1:9000/health` → `{"status":"ok",...,"version":"1.0.1"}` |

Credentials were read from the existing container environment into the test
process only. They are not recorded in this document, in any tracked artifact,
or in any committed log.

## 3. Baseline regression execution (unchanged `main` @ `80a3864`)

Command (stable, P0 item 4):

```sh
cargo +stable test -p quervant-core \
  --test pr14_unified_mixed --test pr14a_public_cursor --test m5_mutation_qualification
```

Result: **PASS**, `69 passed; 0 failed; 0 ignored`.

| Target | Result |
|---|---|
| `pr14_unified_mixed` | 29 passed / 0 failed / 0 ignored |
| `pr14a_public_cursor` | 14 passed / 0 failed / 0 ignored |
| `m5_mutation_qualification` | 26 passed / 0 failed / 0 ignored |

Raw output is retained at `target/pr15a/p0-baseline-stable.log` (ephemeral
`target/` evidence; summarized here).

## 4. Source inventory and constructor references

Inspection only; these references were used to copy public constructors
mechanically. No production source was changed by P0.

| Concern | Source / test reference |
|---|---|
| Shared schema (title/host/n/ts/ip/body/loc/tags) | `crates/quervant-core/tests/pr14_common/mod.rs:28` (`schema`), `:106` (`registry`), `:130` (`doc`), `:135` (`set`), `:173` (`committed`) |
| Two-segment local commit + reopen | `crates/quervant-core/tests/pr14_storage_vertical.rs:161` (`build_local_docs`) |
| Unified request/projection | `crates/quervant-core/tests/pr14_storage_vertical.rs:303` (`request`), `:347` (`unified`) |
| Aggregation group/count/sum | `crates/quervant-core/tests/pr14_storage_vertical.rs:293` (`aggregation`), `:320` (`run_aggregation`), `:440` (`group_counts`) |
| Exact distinct + frequency tie contract | `crates/quervant-core/tests/pr14_aggregation.rs:96`–`:112`; `crates/quervant-core/tests/pr14_compound_aggregation.rs:238` |
| JSON path equality/range constructors | `crates/quervant-core/tests/pr14_json.rs:17` (`path`), `:49` (`range`), `:58` (`contains`) |
| IP/CIDR constructors | `crates/quervant-core/tests/pr14_typed_predicates.rs:207`–`:239` |
| `TimeRange` half-open `[start, end)` | `crates/quervant-core/tests/pr10_time.rs:16` + `:118` inverted-window rejection |
| Pinned batch public seam | `crates/quervant-core/tests/pr14a_public_cursor.rs:289` (`batch`), `:293` (`run`), `:400` (`paginate`), `:1121` (cancellation slot) |
| Mutation batch/apply/replay | `crates/quervant-core/tests/m5_mutation_qualification.rs:260` (`setup_with`), `:754` (`t01`), `:959` (`t05`), `:1121` (`t11`), `:1554` (`t19`), `:1598` (`t20`) |
| Retained PIT across mutation/compaction | `crates/quervant-core/tests/pr14a_public_cursor.rs:828` (`t09`) |
| Historical JSON segment fixture/digest | `crates/quervant-core/tests/pr14_storage_vertical.rs:628` (`b18_b19`); `crates/quervant-core/tests/fixtures/segment/json_paths_golden.seg` |
| Golden segment decode table | `crates/quervant-core/tests/segment_golden.rs:13` (`GOLDEN`), `:70` (`golden_segment`) |
| Corruption/unsupported-major rejection | `crates/quervant-core/tests/pr11_json_corruption.rs:90` (`rebuild`), `:218` (`t14`) |
| Fake remote GET-only counter | `crates/quervant-core/tests/pr14g_remote_zero_get.rs:98` (`remote_fake`), `:514` (`check_no_get`), `:542` (`a01`) |
| Real RustFS zero-GET via `TransferStats` | `crates/quervant-core/tests/pr14g_remote_zero_get.rs:1053` (`a02_real_rustfs_zero_get_after_warmup`) |
| Real RustFS env/config contract | `crates/quervant-core/tests/pr14_storage_vertical.rs:771` (`mod real`); `crates/quervant-core/tests/pr14_storage_faults.rs:46` (`env`) |

### Field contract decision (X03/X04)

The frozen `pr15a_v1` schema copies the existing PR 14 public schema verbatim
(`pr14_common::schema()`): `title` Text `standard_folded`, `host` Keyword
indexed/stored/sortable, `n` I64 indexed/stored/sortable, `ts` Timestamp
indexed/stored/sortable, `ip` IpAddress indexed/stored/sortable, `body` Json
indexed/stored with concrete JSON-path queries, plus the existing `tags`/`loc`
fields. No field type or option was invented. Geo is deliberately not attached
to the eight canonical rows; a separate existing `pr12_geo` fixture and its
independent geometric oracle remain the geo witness.

## 5. Adversarial gate: invariant counterexamples and oracle independence

| ID | Counterexample considered | Independent oracle basis | Test witness |
|---|---|---|---|
| A-I01 | Term accidentally matches all docs or AND degrades to MatchAll | static `Row` table in `pr15a_common`, evaluated before indexing | A-T01/A-T03 |
| A-I02 | CIDR/range/time composition changes membership; IPv6 treated as IPv4 | static IP/CIDR and timestamp arithmetic over frozen integer values | A-T04/A-T05/A-T06 |
| A-I03 | Group counts double-count multi-value hosts; frequency ties flip | independent host tally from static rows and documented canonical value tie rule | A-T07/A-T08 |
| A-I04 | Pagination repeats/omits; cursor silently falls back | full ordered static `n` table compared with concatenated pages | A-T09; negatives REUSED from PR 14A `t01/t06/t07` |
| A-I05 | Partial mutation visible; replay re-applies after reopen | independent mutation state table for generation 3 | A-T11; negatives REUSED from M5 `t05/t11/t20` |
| A-I06 | Old PIT observes post-mutation values or new reader hides commit | hardcoded old/new key sets and per-key host values | A-T13/A-T14; C01 |
| A-I07 | Corrupt/unsupported segment is silently repaired | existing frozen digest and typed `SegmentError` | A-T15/A-T16 (REUSED `b18_b19`, `pr11_json_corruption::t14`) |
| A-I08 | Remote result differs from local fixture; warmed query issues GET | same static oracle on local and remote; exact GET counters | A-R01/A-R02/A-R03 (new provider vertical) |
| A-I09 | Fault/cancellation produces partial success | existing typed cancellation/fault outcomes plus local cancellation witness | A-T17; A-R04/A-R05 REUSED from PR 14 fault suites |
| A-I10 | A gate is claimed from history or a skipped/ignored test | every mandatory command logged with SHA/status/counts | `local-validation.md`, `provider-validation.md` |
| A-I11 | PR 15A changes public/format surface | `git diff` forbidden-path audit + CI | `final-acceptance.md`, A-E03/A-E04 |

Fixture expressiveness: eight rows are sufficient for A-T01/A-T04/A-T07/A-T11/
A-T13. The optional 32-row pagination extension is omitted under **X19** because
the required cursor witnesses (full ordered 8-key list plus page sizes 1/2/3/8)
are present. Geo, JSON corruption, and historical format witnesses reuse their
existing dedicated fixtures as prescribed (X08).

## 6. Planned new tests and reuse map

New files:

- `benchmarks/datasets/pr15a_v1.md` + `pr15a_v1.json` — frozen fixture contract.
- `crates/quervant-core/tests/pr15a_common/mod.rs` — test-only fixture/oracle.
- `crates/quervant-core/tests/pr15a_regression.rs` — A-T00…A-T18.
- `crates/quervant-core/tests/pr15a_compatibility.rs` — C01…C03.
- `crates/quervant-core/tests/pr15a_provider.rs` — A-R01…A-R03 (fake + real).

Reused executed suites (not duplicated):

- A-T10 cursor negatives → `pr14a_public_cursor::{t01,t06,t07,t08,t10}`.
- A-T12 mutation negatives → `m5_mutation_qualification::{m5_t05,m5_t11,m5_t20}`.
- A-T15/A-T16 → `pr14_storage_vertical::b18_b19_historical_json_segment_compatibility`,
  `segment_golden`, `pr11_json_corruption::t14_negotiation_and_corruption_fail_closed`.
- A-T18 budget boundaries → `pr14a_public_cursor::{t11,j10}`.
- M5 query-selection/replay → `m5_t07`, `m5_t19`.
- Real provider faults → `pr14_storage_faults` F01–F10.

## 7. X-rule dispositions exercised in P0

| Rule | Trigger | Action |
|---|---|---|
| X02 | Existing PR 14A/M5 tests exactly prove cursor/mutation negatives under the required topology | Reuse them; run in P0 and P5; map in traceability |
| X08 | Historical golden fixtures already have valid frozen digests | Reuse unchanged bytes and digests |
| X14 | Test workspace and `/tmp` are on the native Linux filesystem, not `/mnt/c` | No relocation needed |
| X19 | 32-row pagination extension unnecessary | Omit; document 8-row sufficiency |
| X28 | No benchmark timing in PR 15A | Only `cargo bench --no-run` later |
| X36 | `p4_child_bootstrap` is an internal ignored child entrypoint | Run only through its parent harness |

No HARD STOP condition was observed in P0.

## 8. Coverage and evidence gaps carried into implementation

- New PR 15A modules are not yet written; they cannot contribute coverage yet.
- Real-provider PR 15A vertical is not yet written; existing PR 14 real suites
  are available and the pinned RustFS instance is healthy.
- Historical PR 14/PR 14G evidence is cited as historical reuse only where the
  source path is unchanged; no historical green check is promoted to a PR 15A
  PASS.

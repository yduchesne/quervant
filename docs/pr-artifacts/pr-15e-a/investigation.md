# PR 15E-A — investigation and method

- **PR status:** `BLOCKED_ATTESTATION` (implementation and verification complete;
  no profiling capture has been executed, none is claimed)
- **Acceptance:** `PENDING_REVIEW` — no human reviewer has accepted this dossier
- **PR 15E-B authorization:** `NO` — nothing in this PR authorizes an optimization
- **PR 15D-B dependency:** merged into `main` before branching

## 1. Source lock

| Item | Value |
|---|---|
| `origin/main` at branch time | `de278e21c38bb60fa84c43951dadc7c0836787fd` |
| `git merge-base HEAD origin/main` | `de278e21c38bb60fa84c43951dadc7c0836787fd` |
| PR #81 merge commit (PR 15D-B) | `de278e21c38bb60fa84c43951dadc7c0836787fd` |
| Implementation branch | `dev/pr15e-a-exact-workload-profiling` |
| Implementation (code + tests) commit | `fc2c62a936cd09069d1f46ed582c247e7f78cf28` |
| Documentation commit | the commit that adds this file (documentation only) |
| Working tree at `prepare` | clean (`git status --porcelain=v1` empty) |

The plan was authored against `main` `8caca768…` and PR #81 head `f0556d3e…`.
The actual merge head is `de278e2`, which contains all required PR 15D-B files,
so decision **X02** applied: the merged SHA was recorded and used, no authoring
SHA was pinned as a base. The pre-existing branch `dev/pr15e-profiling` was
clean at `de278e2` with no work on it, so decision **X04** applied: it was
renamed to the prescribed name rather than duplicated.

Frozen PR 15D inputs hashed by `prepare` (SHA-256 / bytes):

| Frozen file | SHA-256 | Bytes |
|---|---|---:|
| `spec/pr15d_v1.json` | `ec6c0db865845184ba867fca97add3196bd62a3e88f2cf2c8042a1c594dce466` | 3456 |
| `corpus/oracle.py` | `4c37a72251b6b16e972161070297436c18b96421b09acd2665bce5c65abd20b2` | 13414 |
| `corpus/generate.py` | `d0bfd0ac7f63509f20454dd8ab96dcb50075a5293235fe894b14b60e5b86851d` | 2649 |
| `protocol/schema.json` | `62bb81ad2b96162ea1d3c7eef656fa62b48ff2205c819e8715d6bb2b2f2a9eb8` | 3807 |
| `harness/run.py` | `8be6c21e5a2ac41a3dc12c17ab8bc5e91080c689323f7f05015919c01ff31243` | 43215 |
| `adapters/quervant/src/main.rs` | `42d2858ec406aa01b2556504a07907e1b2bc9891d596c684b1a9ba99ede78a63` | 25818 |
| `adapters/quervant/Cargo.toml` | `9a25d5c42a04e0bcc00b32d22b0b67e1a7fcf0b921c3de044851235adcaf37f2` | 614 |
| `adapters/quervant/Cargo.lock` | `050f9d751f978277e02057a0002d1b87d6f0166d73dcadab93f4e78e26cb817d` | 17261 |
| `reports/pr15d/pr15d-qualified.json` | `c9e8ed722aefc4fef43837a5511c2c88575287497b449f68f82f7ea0c251b257` | 46061 |

The canonical PR 15D-B report is `QUALIFIED`, `source_sha`
`40a9c26a57aa23640904075e77be956ee52718bc`. It is read-only input and was **not**
re-run, re-aggregated or overwritten. No PR 15D-B number is quoted as an
expectation for this PR.

## 2. Frozen workload reuse (no re-implementation)

`prepare` calls the existing functions instead of copying behaviour:

| Concern | Reused code |
|---|---|
| Corpus generation | `corpus/generate.py :: generate()` |
| Corpus/oracle truth | `corpus/oracle.py :: load_and_verify()`, `expected()` |
| Adapter build | locked `adapters/quervant/Cargo.toml`, `cargo build --release --locked` |
| Index build + reopen verification | `harness/run.py :: build_index()` |
| Adapter metadata / analyzer check | `harness/run.py :: read_adapter_metadata()` |
| Lane smoke validation | `harness/run.py :: AdapterProcess`, `validate_query_response()` |
| Contention probe | `harness/run.py :: check_contention()` |
| Adapter argv | `harness/run.py :: _adapter_command()` |

There is exactly **one** new query-facing code path: a ~90-line bounded JSONL
transport in `benchmarks/pr15e/profile.py` (`ProfiledTransport`). It exists only
because a profiler must wrap the adapter process; it does not score, filter, sort
or materialise results — it forwards the frozen `pr15d-adapter-v1` request and
returns the adapter's reply after schema/engine/status checks.

Measured workload (unchanged from `pr15d_v1`): `Query::Term` on an exact
`Keyword` (`key`/`group`), `doc_id` ascending, K=10/100,
`Projection::Fields(["doc_id"])`, exact `total_hits`, `mode: "warm"`.

Oracle expectations re-derived independently by `prepare` and again by
`verify.py`:

| Lane | `total_hits` | Ordered `doc_ids` digest |
|---|---:|---|
| `n10000/absent/k100` | 0 | `322e81fbc2a0…` |
| `n10000/rare/k100` | 1 | `d43464cab939…` |
| `n10000/medium/k100` | 1250 | `9b81209ec828…` |
| `n10000/common/k100` | 4999 | `72431bf17c1c…` |
| `n100000/absent/k100` | 0 | `322e81fbc2a0…` |
| `n100000/rare/k100` | 1 | `d43464cab939…` |
| `n100000/medium/k100` | 12500 | `742e4b2d6f5c…` |
| `n100000/common/k100` | 49999 | `1a459db0ba04…` |
| `n100000/absent/k10` | 0 | `322e81fbc2a0…` |
| `n100000/rare/k10` | 1 | `d43464cab939…` |
| `n100000/medium/k10` | 12500 | `4f8300a290da…` |
| `n100000/common/k10` | 49999 | `2cb03d582a4d…` |

The same digest for `absent` and `rare` across N is expected: both result sets are
`[]` and `["d00000000"]` respectively, and the digest covers `{total_hits,
doc_ids}`.

## 3. Prepared state (local, gitignored)

Run `target/pr15e/20261031T122508Z-fc2c62a`:

| Artifact | Value |
|---|---|
| `prepare.json` SHA-256 | `b09b94561c1c421b72ec6b001db76facd277ddbec0c7cbef0783f1fe19571f63` |
| `prepared_digest` (self-consistent record) | `37d99cb0c074fdea08d0f6c69320c2c35756b876a749e6c311c7cb66dff81c56` |
| Corpus N=10000 | 10 000 rows, 546 283 B, `5cdc9341d20bdc525af7e11d3b64bcabf66af9a6eaf27c7dfaddc87280be9a8b` |
| Corpus N=100000 | 100 000 rows, 5 462 533 B, `6ea867fe10679d12fa569822b27e58a8898d866938cf524870c84b0d80d5da4a` |
| Corpus manifest | `69052c6627bf980d7d3c5ab509db746419fb93e7cba2d7d019e749b34c681151` |
| Adapter binary (release + debuginfo) | 30 273 608 B, `fd72599a4ef6a3159edf8656a599aec4997391ebab62aaadab481d9f687f464e`, `rustc 1.98.1` |
| Index N=10000 | 4 files, 3 090 037 B, inventory `a4a6b6701699a8adaf3deb11bab96c46c7ecf3bb060853bc3029dda2d1a891d6`, indexed/reopened 10 000/10 000 |
| Index N=100000 | 4 files, 30 965 025 B, inventory `da9d2d13faaea2d8a072d4726810bf2f4a621dc6d53a3e01590e14d08f051360`, indexed/reopened 100 000/100 000 |
| `verification.json` SHA-256 | `2c17f92f335b00367a6c587b686f9852a7383f1173272937a52acf886ccf42d1` |
| `verification.json` status | `PARTIAL` (20/20 captures unobserved, no prepare violation) |

The adapter binary is a real `FsDirectory`-backed release build (not stripped,
`nm` reports 2 087 `quervant_core` symbols) and the adapter declares
`analyzer = keyword-exact` and `index_backend = FsDirectory`.

## 4. Profiling topology

```text
verify.py / profile.py  (Python controller — never profiled)
        │  JSONL over stdin/stdout
        ▼
perf record … -- pr15d-quervant-adapter --index-dir <run>/indexes/n<N>
        │
        └─ one OS adapter process, one QuerySession, one ReaderSnapshot
```

- Five untimed warmups and the bounded profiled loop run in the **same** adapter
  process; the driver records the adapter PID (discovered from the profiler's
  process tree) at warmup start, at loop start and at loop end and requires one
  distinct PID.
- `perf record`/`heaptrack` see adapter startup, JSONL protocol handling and the
  warmups. Captures are therefore labelled *process sample, warmups included*;
  `perf` percentages are never converted to stage milliseconds.
- Index build, commit, reopen, corpus generation and oracle computation all run
  outside the profiled process.
- Every reply is checked against the oracle; one mismatch aborts the capture with
  `X23_ORACLE` and preserves the raw evidence.

## 5. Environment and tool capability (measured, not assumed)

| Item | Observed |
|---|---|
| Host | WSL2, kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64 |
| CPU | Intel Core i7-10750H |
| Filesystem | `ext4` (resolved from `/proc/mounts`) |
| Python | 3.12.3 |
| Host fingerprint digest | `f450d284f418e340128c3ed974e0ad1842aefb4be469997815216f12d90611f7` |
| `perf` | `/usr/bin/perf` wrapper fails: rc 2, `WARNING: perf not found for kernel 6.18.33.2-microsoft` |
| `perf` used | `/usr/lib/linux-tools-6.8.0-147-generic/perf` → realpath `/usr/lib/linux-tools-6.8.0-147/perf`, `perf version 6.8.12` (decision X12) |
| `heaptrack` | `/usr/bin/heaptrack`, `heaptrack 1.5.0` |
| `heaptrack_print` | `/usr/bin/heaptrack_print`, `heaptrack_print 1.5.0` |
| Optional `cargo flamegraph` | installed (`cargo-flamegraph`); intentionally unused (X14) — no SVG is required |

`/proc/sys/kernel/perf_event_paranoid` is `2`. No package was installed, no
`sudo` was used, `perf_event_paranoid` was not modified, and no profiler shim was
created.

**Harmless tool smoke (capability only, NOT attribution).** A single
non-attested `perf record -g --call-graph dwarf` of the prepared adapter against
the prepared 10 K index (5 warmups + 200 `medium`/K=100 requests) produced
`perf.data` = 95 159 688 B, 11 272 samples (`# Samples: 11K` in the mandated
report invocation) and 490 `quervant` symbol mentions in
`perf-self.txt` — above the 100-sample and symbolization thresholds. It is a tool
probe in `target/pr15e/tool-smoke/`, it is not one of the 20 authorized lanes, it
includes warmups and a dev-chosen request count, and **no share, hotspot or
bottleneck conclusion is drawn from it**.

**`heaptrack` cannot relay the protocol.** `heaptrack 1.5.0` writes two
informational lines to **stdout before launching the debuggee**:

```text
heaptrack output will be written to "<prefix>.gz"
starting application, this might take some time...
```

The adapter's JSONL stream is therefore not transparently relayed, which is
decision **X22** (hard stop for the affected capture class), not a line-skipping
opportunity. Consequence: heaptrack lanes (G06) are blocked independent of
attestation. See [`decision-log.md`](decision-log.md).

## 6. Why no production hook or instrumentation was added

- The dominant deliverable is an *external* evidence dossier; a counter in
  `evaluate_lexical_with` would change the measured code and its cost.
- `crates/quervant-core/` is on the protected allowlist (decision X30); the
  unified-search path, budget/work accounting and diagnostics remain untouched.
- `search/diagnostics.rs` is `#[cfg(test)]`-only and must not become release
  telemetry; per-posting/per-document counters are prohibited by `AGENTS.md` and
  would not survive review.
- If CPU/allocation capture still cannot attribute the hot path after the 20
  captures, decision X43 requires a *separately approved* instrumentation PR —
  not an autonomous one.

## 7. Why PR 15B/15C profiles are historical only

`benchmarks/scripts/profile-pr15b.sh`, `crates/quervant-core/examples/pr15b_profile.rs`
and `docs/pr-artifacts/pr-15b/profile-attempts.md` describe a **different
fixture** (PR 15B U01–U13 in-process microbenchmarks, 2 K/10 K/100 K) on the
pre-PR-15C code base, and its `perf`/`heaptrack` attempts were recorded before the
metadata-verification correction. Only their *tool invocation approach* informed
this harness (decision X06); their numbers are not evidence about the corrected
PR 15D adapter or `crates/quervant-core/src/search/execute.rs` today.

## 8. Residual risks (disclosed, not mitigated)

- `perf` sampling and heaptrack instrumentation change timing; captures include
  adapter startup, protocol and warmups.
- `perf` 6.8.12 runs on a 6.18 WSL2 kernel; symbolication is partial and Rust
  symbols appear mangled in the mandated report invocation.
- The uninstrumented PR 15D-B comparison is not comparable to an instrumented
  capture and no such comparison is made.
- The synthetic corpus is not a production distribution; results are
  lane-specific, not general engine performance.
- `doc_id`-ordered exact-term membership is deliberately not BM25 ranking.
- One Quervant lane set says nothing about mixed queries, RustFS-backed indexes
  or distributed fan-out.
- Contention detection is best-effort and cannot observe Windows-host or other
  WSL guest activity.

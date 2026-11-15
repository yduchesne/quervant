# BM-01 — Benchmarking contract foundation

**Status:** implementation evidence for `v0.1-bench` checkpoint **C1 (Contracts
stable)**. This is **not** a benchmark run, a Gate A–E qualification, evidence
admission or production adoption of any optimization.

## 1. Scope and source baseline

| Item | Value |
| --- | --- |
| Repository | `yduchesne/quervant` |
| Branch | `dev/bm01-benchmark-contracts` |
| Pinned reviewed baseline | `ea9bef647cf155bb0176f159a8b304319ed6f7de` (merge of PR #99) |
| Milestone | `v0.1-bench` (interim; **not** v0.2) |
| New runtime dependency set | `PyYAML==6.0.3`, `jsonschema==4.26.0` |
| Python support | `>=3.11`; CI uses 3.12 |

The baseline was re-verified before implementation: `HEAD` and `origin/main` both
equalled the pinned commit and the working tree was clean apart from an unrelated
untracked `.bin/` directory.

## 2. What BM-01 adds

* `benchmarks/quervant_bench/` — a strict, versioned, **contract-only** Python
  package (`codec`, `identity`, `schemas`, `contracts`, `profiles`, `errors`,
  `cli`, read-only `legacy` registry).
* Six closed JSON Schema Draft 2020-12 documents under
  `benchmarks/quervant_bench/config/schemas/`.
* `benchmarks/experiments/synthetic-contract-smoke/` — a non-measuring declarative
  catalog example.
* `benchmarks/quervant_bench/tests/` — 80 deterministic L1 tests plus a synthetic
  receipt fixture and a golden `inspect` record.
* `benchmarks/scripts/bm-contract-inventory.py` — read-only, baseline-derived
  legacy inventory (no working-tree or historical-script execution).
* `docs/pr-artifacts/bm-01/legacy-inventory.json` — the exhaustive pinned-tree
  inventory and format-ID register.
* One separate `python-contracts` CI job. Existing `rust`, `msrv` and `rustfs`
  jobs are untouched.

No Rust production or benchmark source, Cargo manifest/lockfile, historical
controller, protocol, verifier, report or receipt was modified.

## 3. Actual inventory (measured on the pinned baseline)

Derived with:

```sh
python benchmarks/scripts/bm-contract-inventory.py \
    --baseline ea9bef647cf155bb0176f159a8b304319ed6f7de \
    --out docs/pr-artifacts/bm-01/legacy-inventory.json
```

| Metric | Measured value |
| --- | ---: |
| Tracked paths in scope | **414** |
| External/untracked evidence roots classified | **1** (`target/`) |
| Distinct explicit legacy format IDs | **295** |
| `retain_live` | 244 |
| `preserve_archive` | 123 |
| `read_only_adapter_later` | 31 |
| `candidate_migrate_later` | 16 |
| `external_not_present` | 1 |

Scopes: `benchmarks/`, `crates/quervant-core/benches/` and the benchmark CI
entrypoint `.github/workflows/ci.yml`.

Kind counts observed: acceptance 1, adapter 8, admission 4, analysis 6,
attestation 0, corpus_oracle 3, criterion 10, documentation 33, evidence 63,
fixture 19, launcher 15, other_related 28, policy 2, profiling 37, protocol 30,
report_schema 1, runner 35, test 96, verifier 24.

### Historical-count reconciliation

`docs/benchmarking/BENCHMARKING_MIGRATION.md` reported **32 PR 15 directories, 26
`run.py` and 15 `verify.py` files** on an earlier audited development branch. Those
three headline counts are **reproduced exactly** on this pinned baseline. The
inventory additionally records **30 `*_run.py` controllers** and **23
`verify*.py` modules**, which the three headline numbers do not cover; for
example `benchmarks/pr15i_d3_c/` alone has `causal_run.py`, `dispatch_run.py`,
`f_final_run.py`, `verify_causal.py`, `verify_dispatch.py`, `verify_f_final.py` and
seven more verifier siblings. Every discovered path and format ID is therefore
classified in `legacy-inventory.json` rather than inferred from the old counts.

### Legacy format registry

`benchmarks/quervant_bench/legacy/legacy_formats.v1.json` registers every
explicit `schema` / `$id` / `SCHEMA_*` literal that carries a `v<N>` version
segment, verbatim. All entries use `reader_status: original_tool_only`,
`new_equivalence_status: not_verified` and **no** entry claims parity. Historical
identifiers are exempt from the new PR-agnostic rule only inside this registry.

The registry loader rejects any attempt to mark a format `verified`, so BM-01
cannot accidentally claim legacy/new equivalence.

## 4. L1 tests and fixtures

Run:

```sh
python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v
```

| Module | Named cases |
| --- | --- |
| `test_codec.py` | PARSE-01 … PARSE-10 |
| `test_identity.py` | ID-01 … ID-04, CAN-01 … CAN-08 |
| `test_schemas.py` | SCH-01 … SCH-02, PROTO-01 … PROTO-09, BIND-01 … BIND-09, SCOPE-01 … SCOPE-07 |
| `test_cli.py` | CLI-01 … CLI-11 |
| `test_legacy_inventory.py` | LEG-01 … LEG-10 |

Result on the final working tree: **82 tests, 0 failures, 0 errors** (6.3 s,
standard-library `unittest`, no network, no clock assertions, no sleeping).

Fixed seeds used by fixtures and boundary tests: `0`, `1`, `42`,
`0x5EEDB001`, `2**32-1`, `2**64-1`. No randomized schedule is generated.

Golden `inspect` output: `inspect.golden.json` is canonical JSON plus one trailing
newline, **563 bytes**, SHA-256
`ff8d4e91ed3c07956d8120f7dda000e4c1028a271984dd4f4272939b9259cf3c`. The CLI test
compares bytes on two consecutive runs and every run revalidates the emitted
`outcome.v1` document.

Synthetic fixture identities (documented derivation, not real evidence):

| Binding | Derivation |
| --- | --- |
| `dataset.digest` | `content_digest({"dataset_id":"synthetic-contract-dataset","generator":"deterministic-synthetic","documents":8})` |
| `policy_digest` | `content_digest({"policy_id":"synthetic-contract-policy","policy_version":1})` |
| `analysis_digest` | `content_digest({"analysis_id":"synthetic-contract-analysis","analysis_version":1})` |
| receipt `validator.source_digest` | `content_digest({"validator_id":"synthetic-contract-validator","validator_version":1})` |
| `protocol_digest` | `content_digest(<validated protocol document>)` |
| `receipt_id` | `content_digest(<receipt payload without receipt_id>)` |

The receipt fixture is `status: not-executed`, `evidence_origin: synthetic`,
`qualification_scope: simulated`. It is an identity fixture, never a Gate PASS.

## 5. Decisions and prohibitions applied

| Decision | Application |
| --- | --- |
| A01/A02 | New Python package beside historical scripts; Python ≥3.11, CI 3.12 |
| A03 | Pinned PyYAML 6.0.3 + jsonschema 4.26.0; no bespoke YAML grammar |
| A04/A05 | Canonical JSON machine form; closed versioned schemas starting at v1 |
| A06 | Semantic slugs + canonical UUIDv4 + `sha256:` digests via `hashlib` |
| A07 | JSON Schema shape **plus** explicit cross-field semantics |
| A08 | `quervant-bench` with 7 verbs; only `inspect`/`--help`/`--version` operate |
| A09/A10 | Three rigor profiles; origin and qualification scope are separate |
| A11 | Side-by-side layout, tracked registry, exhaustive inventory |
| A12 | Standard-library `unittest`, fixed seeds, no Hypothesis |
| A13 | Output-root pattern documented, never created |
| A14 | Workload-agnostic identifiers only; no PR/phase tokens in new IDs |

Prohibitions verified:

* zero real timed benchmark acquisition (no Criterion timing, profiling, pilot or
  `quervant-bench run`);
* zero edits to frozen historical benchmark files (see §6);
* `run` fails with `BM_ACQUISITION_PROHIBITED` **before** file access, clock
  access, subprocess creation or output-directory creation (spied in CLI-03);
* no synthetic record can be relabelled official (`BM_SCOPE_MISMATCH`).

## 6. Protected-path proof

`git diff --name-only --diff-filter=MDR ea9bef64... -- benchmarks/ crates/quervant-core/benches/`
is empty apart from the single whitelisted `benchmarks/README.md` pointer
(asserted by `test_leg_07`). `.github/workflows/ci.yml` gained one separate job;
no existing job was removed or weakened. Verified independently: every inventory
row's `sha256` still equals the SHA-256 of its bytes at the pinned commit.

## 7. How to reproduce

```sh
# Isolated environment (created outside the working tree so .gitignore is untouched)
python3 -m venv /tmp/quervant-bm-venv
. /tmp/quervant-bm-venv/bin/activate
python -m pip install -e ./benchmarks

python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py
python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v
PYTHONPATH=benchmarks python -m quervant_bench inspect --experiment synthetic-contract-smoke --format json
quervant-bench inspect --experiment synthetic-contract-smoke --format json
PYTHONPATH=benchmarks python -m quervant_bench --help
python benchmarks/scripts/bm-contract-inventory.py \
    --baseline ea9bef647cf155bb0176f159a8b304319ed6f7de \
    --check docs/pr-artifacts/bm-01/legacy-inventory.json
```

## 8. Residual (intentional) gaps

* No real acquisition, timing fidelity or A/A evidence: **BM-09 only**.
* No simulated end-to-end campaign, scheduler or Gate A–E chain: **BM-03/BM-06**.
* No admission receipts, provenance authentication, archive safety or statistics:
  **BM-02/BM-04/BM-05**.
* No legacy/new parity, no legacy adapter and no retirement: **BM-07/BM-08/BM-09**.
* Historical `target/` evidence is untracked and therefore classified
  `external_not_present`; nothing was fabricated to fill the gap.

See [schema-and-cli-contract.md](schema-and-cli-contract.md) for the normative
field/CLI reference.

## 9. Invariant traceability

| Invariant | Observable contract | Tests |
| --- | --- | --- |
| INV-01 | No PR/phase identifiers in new public names | ID-01…ID-04, LEG-06 |
| INV-02 | Strict parsing rejects duplicate/unknown/unsafe structures | PARSE-01…PARSE-10, SCH-01/02 |
| INV-03 | Canonical bytes/digests stable and content-bound | CAN-01…CAN-08 |
| INV-04 | Protocol arms, lanes, slot counts and schedules consistent | PROTO-01…PROTO-09 |
| INV-05 | Experiment/workload/adapter references explicit, unique, typed | BIND-01…BIND-09 |
| INV-06 | Origin/scope cannot be relabelled official | SCOPE-01…SCOPE-07 |
| INV-07 | CLI deterministic, read-only, never acquires | CLI-01…CLI-11 |
| INV-08 | Inventory covers the tracked baseline without mutation | LEG-01…LEG-08 |
| INV-09 | Missing real archives cannot be fabricated | LEG-09, LEG-10 |
| INV-10 | No effect on production or benchmark history | LEG-07, §6 above |

## 10. Verification evidence (final working tree)

| Gate | Command | Result |
| --- | --- | --- |
| Python compile | `python -m compileall -q benchmarks/quervant_bench benchmarks/scripts/bm-contract-inventory.py` | PASS |
| Python L1 | `python -m unittest discover -s benchmarks/quervant_bench/tests -p 'test_*.py' -v` | PASS — 82 tests, 0 failed |
| Inspect (module) | `PYTHONPATH=benchmarks python -m quervant_bench inspect …` | PASS — golden bytes |
| Inspect (console) | `quervant-bench inspect …` | PASS — golden bytes |
| Inventory determinism | `python benchmarks/scripts/bm-contract-inventory.py --baseline ea9bef64… --check …` | PASS |
| Format (MSRV) | `cargo +1.85.0 fmt --all -- --check` | PASS |
| Format (stable) | `cargo fmt --all -- --check` | PASS |
| Clippy (MSRV) | `cargo +1.85.0 clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Clippy (stable) | `cargo clippy --workspace --all-targets -- -D warnings` | PASS |
| Clippy (stable, all features) | `cargo clippy --workspace --all-targets --all-features -- -D warnings` | PASS |
| Tests (MSRV, all features) | `cargo +1.85.0 test --workspace --all-targets --all-features` | PASS — 2529 passed, 0 failed, 94 ignored |
| Tests (stable) | `cargo test --workspace --all-targets` | PASS — 2485 passed, 0 failed, 13 ignored |
| Tests (stable, all features) | `cargo test --workspace --all-targets --all-features` | PASS — 2529 passed, 0 failed, 94 ignored |
| Coverage | `cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85` | PASS — **92.69 % line** |
| Docs | `cargo doc --workspace --all-features --no-deps` | PASS |
| Benchmark compile only | `cargo bench --workspace --no-run` | PASS — no timing |
| Historical script tests | `bash benchmarks/scripts/test-scripts.sh` | PASS — 108 passed, 0 failed |
| Whitespace | `git diff --check` | PASS |

Ignored Rust tests require a live RustFS container; they are exercised by the
unchanged `rustfs` CI job. No Criterion measurement was executed: `cargo bench`
was only ever invoked with `--no-run`.

Environment note: the isolated Python virtual environment was created at
`/tmp/quervant-bm-venv` instead of `.venv-bm` inside the repository so that no
`.gitignore` edit (a non-whitelisted path) was required. The commands are
otherwise identical to the plan.

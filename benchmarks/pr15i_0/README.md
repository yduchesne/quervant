# PR 15I-0 — measurement, audit and design-contract tooling

**Status: benchmark-only.** This tree does not implement, schedule or approve any
15I-A/B/C optimization. Production crates, on-disk formats, mutation and STORED
codecs, postings, query planning/execution, writer/commit/recovery semantics,
resource limits and public APIs are unchanged by PR 15I-0.

The tree exists to (a) re-qualify a source-locked three-engine baseline,
(b) re-run the existing Quervant CPU/reopen/layout attribution, (c) attribute
every mutation-state sidecar byte from *original verified bytes*, and
(d) publish fixed design contracts for the next series.

## Layout

```text
benchmarks/pr15i_0/
  README.md               this file
  protocol.json           frozen measurement contract (schema + SHA-256 recorded in every manifest)
  verify.py               read-only qualification controller (+ `seal` and `qa` modes)
  summarize.py            stable report calculator (ratios, shares, historical separation)
  run_mutation.py         wrapper that drives the benchmark-only sidecar probe
  test_verify.py          controller/seal/QA-gate tests
  test_summarize.py       report-calculation and privacy tests
  test_run_mutation.py    wrapper cross-check tests (fake probe, no index mutation)
  mutation_probe/         standalone, independently locked read-only Rust probe
```

Private raw evidence (indexes, `perf.data`, heaptrack output, seals, QA logs)
lives only under ignored `target/…` directories. Committed reports live under
`benchmarks/reports/pr15i-0/` and `docs/pr-artifacts/pr-15i-0/` and are sanitized.

## Frozen measurement contract

`protocol.json` fixes the three-engine trial count, the corpus, the nine warm
Quervant lanes, the 42 reopen processes, the optional allocation capture, the
sidecar payload versions, the 256 MiB probe bound and the prohibited actions.
`verify.py` deep-compares it against an in-source copy of the same values, so
retuning the contract to obtain a pass is detected as `X02_PROTOCOL`.

The contract is `pr15i-0-measurement-contract-v1`, SHA-256
`af828096ca3d4581a8cda50b9401b3d23df92311487acaa79966a8a0e2e0e6f8`.

## Campaign sequence

```sh
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
SRC="$(git rev-parse HEAD)"; SHORT="$(git rev-parse --short=8 HEAD)"

# 1. Frozen corpus + three-engine campaign (existing PR 15D harness, unmodified).
python3 benchmarks/pr15d/corpus/generate.py --out target/pr15i-0/corpus
python3 benchmarks/pr15d/corpus/oracle.py --corpus target/pr15i-0/corpus
python3 benchmarks/pr15d/harness/run.py --trials 3 --idle-confirmed \
  --corpus target/pr15i-0/corpus --out target/pr15i-0/pr15d-current-01
python3 benchmarks/pr15d/harness/validate.py \
  --run target/pr15i-0/pr15d-current-01 \
  --out target/pr15i-0/pr15d-current-01/validation.json

# 2. Quervant profile + reopen + layout (existing PR 15E/15F harnesses, unmodified).
PREP="$ROOT/target/pr15e/pr15i0-prepared-$SHORT-01"
F_RUN="$ROOT/target/pr15f/pr15i0-run-$SHORT-01"
python3 benchmarks/pr15e/profile.py prepare --out "$PREP"
python3 benchmarks/pr15f/run.py prepare --prepared-run "$PREP" --out "$F_RUN"
python3 benchmarks/pr15f/run.py query-perf --prepared-run "$PREP" --out "$F_RUN" --idle-confirmed
python3 benchmarks/pr15f/run.py reopen-single --prepared-run "$PREP" --out "$F_RUN" --idle-confirmed
python3 benchmarks/pr15f/run.py reopen-perf --prepared-run "$PREP" --out "$F_RUN" --idle-confirmed
python3 benchmarks/pr15f/run.py inventory --prepared-run "$PREP" --out "$F_RUN"
python3 benchmarks/pr15f/run.py allocation --prepared-run "$PREP" --out "$F_RUN" --idle-confirmed
python3 benchmarks/pr15f/attribution.py --run "$F_RUN" --out "$F_RUN/analysis.json"
python3 benchmarks/pr15f/verify.py --prepared-run "$PREP" --run "$F_RUN" --analysis "$F_RUN/analysis.json"

# 3. Sidecar byte attribution (this tree).
python3 benchmarks/pr15i_0/run_mutation.py \
  --prepared-run "$PREP" --pr15f-run "$F_RUN" --source-sha "$SRC" \
  --out "$ROOT/target/pr15i-0/mutation-01"

# 4. Seal every new campaign (exclusive, fsync'd, immutable).
python3 benchmarks/pr15i_0/verify.py seal --root "$ROOT" \
  --campaign target/pr15i-0/pr15d-current-01 --source-sha "$SRC" \
  --status QUALIFIED --protocol-sha256 <protocol sha> --corpus-manifest-sha256 <corpus sha>
# ... repeat for target/pr15e/pr15i0-prepared-*, target/pr15f/pr15i0-run-*,
#     and target/pr15i-0/mutation-01.

# 5. Execute the QA matrix and record the real exit codes.
python3 benchmarks/pr15i_0/verify.py qa --root "$ROOT" \
  --out "$ROOT/target/pr15i-0/qa/workspace-qa.json" [--include-rustfs]

# 6. Verify, then derive the sanitized reports.
python3 benchmarks/pr15i_0/verify.py --root "$ROOT" --source-sha "$SRC" \
  --pr15d-run target/pr15i-0/pr15d-current-01 --pr15f-run "$F_RUN" \
  --pr15f-prepared "$PREP" --mutation-run target/pr15i-0/mutation-01 \
  --out "$ROOT/target/pr15i-0/verification-01.json"
python3 benchmarks/pr15i_0/summarize.py --root "$ROOT" \
  --verification target/pr15i-0/verification-01.json \
  --pr15d-run target/pr15i-0/pr15d-current-01 --pr15f-run "$F_RUN" \
  --pr15f-prepared "$PREP" --mutation-run target/pr15i-0/mutation-01 \
  --out-json benchmarks/reports/pr15i-0/pr15i-0-summary.json \
  --out-md docs/pr-artifacts/pr-15i-0/measurements.md
# 7. Re-verify into a NEW destination so gate I0-P10 can see the privacy scan.
python3 benchmarks/pr15i_0/verify.py ... --out "$ROOT/target/pr15i-0/verification-02.json"
```

`verify.py` never writes into a campaign directory and never overwrites its own
output: an existing destination is an error, and revalidation always uses a fresh
`verification-NN` path.

## Gates

`verify.py` emits `I0-P00`…`I0-P12`, each exactly one of `PASS`, `FAIL`,
`BLOCKED`, `NOT_RUN` or `NOT_MEASURED`. `I0-P12` (optional allocation capture)
may legitimately be `NOT_MEASURED`. Overall dispositions are
`15I0_QUALIFIED_REVIEW_READY`, `15I0_PARTIAL_EVIDENCE`, `15I0_NOT_QUALIFIED` or
`15I0_BLOCKED_SOURCE`.

`I0-P10` (privacy) and `I0-P11` (QA) can only pass once the sanitized reports and
the executed QA record exist, which is why the campaign is verified twice.

### Complete-QA contract (`RF-01`)

`I0-P11` is not a "no failures recorded" check. It requires the **exact**
mandatory matrix, derived at runtime from `QA_COMMANDS` plus the required
`ignored-integration-with-real-rustfs` sweep (20 identifiers):

- one entry per mandatory id — no omissions, no duplicates, no unknown ids;
- the `required` flag equal to the source matrix;
- `status = "PASS"` **and** integer `exit_code = 0`;
- an optional `rustfs` entry only when the record declares `rustfs_included` and
  it passed;
- the coverage entry's recorded `stdout_full` must parse to a real `TOTAL` line
  percentage `>= 85`, matching `coverage_percent` within 0.005;
- `fixup_code_sha256` must equal the fingerprint of the current
  `verify.py`/`summarize.py`/`test_verify.py`/`test_summarize.py` bytes, so a
  record produced by older controller code is rejected (a docs-only commit does
  not invalidate it).

A `qa --only …` record is a diagnostic; it can never satisfy `I0-P11`.

### Seal qualification (`RF-05`)

`verify_seal` requires `status = QUALIFIED`, an exact `protocol_sha256`, an exact
`corpus_manifest_sha256`, a sorted, unique, safe file inventory with valid
digests, and a full rehash with no unlisted file. A `PARTIAL` seal stays valid
*honest evidence* but can never satisfy the final gate.

### Privacy inventory (`RF-03`)

`I0-P10` requires the scan to list **exactly** the twelve frozen report paths in
frozen order with matching hashes and an empty `problems` list, and then
independently re-reads every report and re-runs the privacy patterns against the
current bytes. An incomplete scan cannot pass.

Because `final-report.md` is one of the twelve scanned reports, editing it
requires re-running only the scan:

```sh
python3 benchmarks/pr15i_0/summarize.py --scan-only --root "$ROOT"
```

`--scan-only` writes nothing but `benchmarks/reports/pr15i-0/privacy-scan.json`
and refuses to write a scan when any target is missing or unclean.

## Probe CLI

The benchmark-only probe resolves the authoritative sidecar through public
`quervant-core` APIs and takes the **prepared index root** as its input:

```sh
mutation-probe --index-root <abs prepared index dir> \
               --max-bytes 268435456 --source-sha <40 lowercase hex> \
               --out <abs path under target/>
```

It walks `CURRENT → Manifest → MutationStateRef`, verifies the manifest and
sidecar digests with `quervant_objectstore::ContentDigest`, refuses symlinks,
traversal, non-regular files and oversize inputs, and accounts every payload byte
with checked 64-bit arithmetic. The version-2 batch replay remainder is
deliberately **opaque** (`SEMANTIC_BATCH_DETAIL_NOT_VERIFIED`); it is never
decoded or guessed. An earlier sketch in the executing plan showed a `--file`
flag; the authoritative locator section of the same plan requires the prepared
index root, so that is the implemented input form (recorded as a decision).

### Publication contract (`RF-02`, `RF-04`)

`summarize.py` refuses to publish unless the supplied campaigns are *exactly* the
ones the verification qualified: four exact repo-relative campaign paths, their
current `run.json`/`prepare.json`/`preflight.json`/`manifest.json` digests, their
`seal.json` digests, the verifier's `observations.seals` digests, the QA-record
digest, the frozen protocol digest and the cross-checked corpus digest — all
re-proven before the first derived number is computed. Seal rehash, source
identity and gate status (`I0-P00`…`I0-P11` PASS, `I0-P12` PASS or
`NOT_MEASURED`) are rechecked too.

Outputs are confined to exactly five PR 15I-0 files:

```text
benchmarks/reports/pr15i-0/pr15i-0-summary.json   (--out-json)
docs/pr-artifacts/pr-15i-0/measurements.md        (--out-md)
benchmarks/reports/pr15i-0/pr15i-0-summary.md
benchmarks/reports/pr15i-0/historical-context.json
benchmarks/reports/pr15i-0/privacy-scan.json
```

Every destination is validated (canonical spelling, existing non-symlinked
parent, existing regular file, no nonregular stale `*.tmp`) before any write.
Arbitrary paths, `..` aliases, symlinks and prior-PR reports (for example
`benchmarks/reports/pr15f/p0-profile-summary.json`) are rejected with a typed
`RF04_*` error and leave every existing output byte-identical.

## Tests

```sh
python3 -m unittest discover -s benchmarks/pr15i_0 -p 'test_*.py' -v
python3 -m py_compile benchmarks/pr15i_0/{verify,summarize,test_verify,test_summarize}.py
cargo test --locked --manifest-path benchmarks/pr15i_0/mutation_probe/Cargo.toml
cargo +1.85.0 test --locked --manifest-path benchmarks/pr15i_0/mutation_probe/Cargo.toml
```

The suites cover the adversarial matrices `FT-01`–`FT-47` (complete-QA,
seal qualification, publication binding, output confinement, privacy inventory)
against synthetic fixture repositories. Synthetic fixtures exercise the *same*
identity rules as the CLI; there is no bypass flag.

Synthetic fixtures are marked `test_fixture: true` and are rejected for real
qualification. Fake probes are used only to test the wrapper's cross-checks.

## Evidence statuses

`QUALIFIED`, `PARTIAL`, `ALLOCATION_NOT_MEASURED`, `NOT_MEASURED`. A missing or
blocked lane is never silently dropped and is never replaced by a historical
value. Inclusive CPU shares are reported separately from exclusive ownership and
are never summed into a latency estimate.

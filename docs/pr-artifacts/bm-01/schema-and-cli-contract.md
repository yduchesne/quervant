# BM-01 schema and CLI contract (normative reference)

This document is the field-level reference for the `v0.1-bench` contract
foundation. It is subordinate to `docs/benchmarking/BENCHMARKING_{ARCHITECTURE,
METHODOLOGY,MIGRATION,ROADMAP}.md`; where those documents set a requirement, this
document specifies the concrete BM-01 encoding. It does **not** authorise
acquisition and does not describe an implemented execution engine.

Machine-readable authority: the six checked-in JSON Schemas under
`benchmarks/quervant_bench/config/schemas/` plus the semantic checks in
`benchmarks/quervant_bench/config/contracts.py`.

## 1. Canonical encoding

| Rule | Contract |
| --- | --- |
| Machine form | Canonical JSON: `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`, UTF-8 |
| Persistence | Canonical payload + exactly one trailing `\n`; the newline is **not** hashed |
| Content digest | `sha256:` + `hashlib.sha256(canonical_payload_bytes(obj)).hexdigest()` |
| Array order | Meaningful; never sorted during canonicalisation |
| Unicode | Preserved verbatim; no implicit NFC/NFD normalisation |
| Omitted vs `null` | Distinct; no default insertion before hashing |
| Duplicate keys | Rejected in JSON **and** YAML mappings (`BM_DUPLICATE_KEY`) |
| Non-finite numbers | `NaN`, `Infinity`, `-Infinity`, `.nan`, `.inf` rejected |
| UTF-8 | Strict; invalid sequences and byte-order marks rejected |
| Document size | 1,048,576 bytes maximum (inclusive) |
| Nesting depth | 32 nested containers maximum (33 rejected) |
| Collection nodes | 10,000 dictionaries/arrays maximum |
| Scalar length | 4,096 UTF-8 bytes maximum per string |
| YAML subset | `SafeLoader` only; no anchors, aliases, merge keys, custom/unsafe tags, timestamps, binary, sets, cyclic objects or multiple documents |
| JSON Schema | Draft 2020-12, local allowlist, closed objects, no remote `$ref`, no network resolution |
| Self-reference | A `*_digest`/`receipt_id` is never part of the payload it identifies |

The canonical payload of `{"a": 1, "b": [true, null, "é"]}` hashes to
`sha256:9488dd13ca33d3291f5a91a1833dfa164811755ffba538c2b340780f8c31a0cb`
(independently computed with `printf` + `sha256sum`; asserted by `CAN-04`).

## 2. Identity rules

| Name | Rule |
| --- | --- |
| `experiment_id`, `workload_id`, `arm_id`, `adapter_id`, `protocol_id`, `analysis_id`, `policy_id`, `lane_id`, `query_id`, `schedule_id`, `…` | `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`, 3–64 characters |
| PR/phase exclusion | A new public ID must not contain a `pr<N>…`, `bm<N>`/`bm-<N>` or `t<N>`/`t<N>f<N>` **segment** |
| `protocol_version`, `policy_version`, `adapter_version`, `oracle_version`, `analysis_version`, `validator_version` | Positive integer; booleans rejected |
| `schema_version` | Integer `1` for every v1 document; unsupported versions fail with `BM_SCHEMA_UNSUPPORTED` |
| `run_id` | Exact lower-case canonical UUIDv4; uppercase is normalised only by `normalize_uuid4`, never accepted as stored identity |
| `*_digest`, `receipt_id` | `sha256:` + exactly 64 lower-case hexadecimal digits |
| `source_commit` | Exactly 40 lower-case hexadecimal digits |
| Seeds | Unsigned 64-bit integer, `0 ≤ seed ≤ 2**64-1`; booleans, negatives and floats rejected |
| `provenance` | Optional closed object with only `source_commit`, `source_pr`, `historical_label`, `notes`; may contain PR/phase text; never participates in semantic selection |

Identity relationships that must stay distinct: `experiment_id` is stable across
protocol versions; `protocol_digest` binds exact protocol content; `workload_digest`
binds corpus, lanes, semantics and cache regime; `arm_id` is a label within an
experiment; `run_id` identifies one execution instance, never an experiment;
`receipt_id` binds content and dependencies, not a filename or PASS string.

## 3. Origin / qualification-scope fence

| `evidence_origin` | `qualification_scope` | Result |
| --- | --- | --- |
| `synthetic` | `simulated` | Allowed; never authoritative real evidence |
| `real` | `official` | Shape recognised for a future BM-09 campaign only |
| `real` | `historical_replay` | Shape recognised for read-only historical evidence |
| `synthetic` | `official` | Reject `BM_SCOPE_MISMATCH` |
| `synthetic` | `historical_replay` | Reject `BM_SCOPE_MISMATCH` |
| `real` | `simulated` | Reject `BM_SCOPE_MISMATCH` |
| missing / unrecognised | any | Reject (schema or `BM_SCOPE_MISMATCH`) |

`inspect` derives the summary's origin/scope **from the validated adapter build
identity**: `build_identity.kind == "synthetic"` yields
`("synthetic","simulated")`; a real `source-and-binary` declaration is refused by
BM-01 with `BM_SCOPE_MISMATCH` because its official scope belongs to a later
milestone. BM-01 never issues a real gate PASS.

## 4. Schema documents

All use `$schema: https://json-schema.org/draft/2020-12/schema`,
`$id: urn:quervant-bench:contract:<kind>:v1`, and
`additionalProperties: false` on every closed object.

### 4.1 `experiment` v1

Required: `kind:"experiment"`, `schema_version:1`, `experiment_id`,
`description` (1–1024), `workload_family`, `workloads_file`, `protocol_file`,
`adapter_file`, `profile` (`development|regression|qualification`),
`policy:{policy_id,policy_version,policy_digest}`,
`analysis:{analysis_id,analysis_version,analysis_digest}`,
`arms:[{arm_id,adapter_id,variant}]` (1–16).
Optional: `provenance`.

Cross-field: referenced files must be distinct and resolvable; every `adapter_id`
must equal the validated adapter manifest; `arm_id` values are unique.

### 4.2 `workload` v1

Required: `kind:"workload"`, `schema_version:1`, `workload_id`,
`dataset:{dataset_id,digest,fixture_schema}`, `query_semantics_id`,
`oracle_id`, `oracle_version`,
`lanes:[{lane_id,operation,cache_regime,params}]` (1–4096).
Optional: `provenance`.

`operation ∈ {search,index,mutation,compaction,storage-read,storage-write}`;
`cache_regime ∈ {warm,process-cold,cache-cold,not-applicable}`.
`params` is a closed map of optional typed declarations: `corpus_size`, `top_k`,
`batch_size`, `segment_count` (positive integers); `selectivity_class`, `query_id`
(semantic slugs). A lane is a scenario, never an arm. `lane_id` values are unique.

### 4.3 `adapter` v1

Required: `kind:"adapter"`, `schema_version:1`, `adapter_id`,
`adapter_version`, `engine_id`, `operations`, `cache_regimes`,
`oracle_semantics_id`, `build_identity`, `measurement_envelope`, `timeouts`.
Optional: `provenance`.

`build_identity` is exactly one of:

* `{"kind":"synthetic"}` — literal marker, no fabricated hashes;
* `{"kind":"source-and-binary","source_digest":"sha256:…","executable_digest":"sha256:…"}`.

`measurement_envelope.unit ∈ {nanoseconds,operations-per-second,bytes}`;
`direction ∈ {lower-is-better,higher-is-better}`.
`timeouts:{setup_ms,operation_ms,cleanup_ms}` are positive declarations only.

The future adapter seam is declared as a `typing.Protocol`
(`BenchmarkAdapter.prepare/check_oracle/warmup/measure/cleanup`) with typed
records carrying IDs, origin/scope and status. **No method is implemented and none
may consult a clock in BM-01.**

### 4.4 `protocol` v1

Required: `kind:"protocol"`, `schema_version:1`, `protocol_id`,
`protocol_version`, `experiment_id`, `workload_digest`, `arm_multiplicity`
(`[{arm_id,slots_per_block}]`), `schedule`, `measurement`, `campaigns`, `host`,
`correctness`, `exclusion`, `statistics`, `recovery`, `policy`, `freeze`.
Optional: `provenance`.

* `schedule:{schedule_id, mode:explicit|seeded-balanced, blocks, slots_per_block, seed, explicit_orders?}`
* `measurement:{warmups_per_lane_slot≥0, samples_per_lane_slot≥1, metric_unit, clock_contract_id}`
* `campaigns:{required_controls≥0, required_treatments≥1, control_contract_id}`
* `host:{capability_policy_id, readiness_policy_id}`
* `correctness:{oracle_id, oracle_version, must_pass_before_timing:true}`
* `exclusion:{ruleset_id, symmetric_by_lane_and_block:true, minimum_retained_blocks}`
* `statistics:{method_id, resamples≥1, seed, comparison_unit:"paired-block", interval_id}`
* `recovery:{measurement_retries≥0, ambiguous_outcome:"hard-stop"}`
* `freeze:{require_source_digest:true, require_build_digest:true, require_workload_digest:true, before_first_official_control:true}`

Cross-field: `Σ slots_per_block == schedule.slots_per_block`; arm IDs equal the
experiment arm set; `minimum_retained_blocks ≤ blocks`; `explicit` mode requires
exactly `blocks` arrays of exactly `slots_per_block` arm IDs with counts matching
`arm_multiplicity`; `seeded-balanced` forbids `explicit_orders`.

A syntactically valid protocol is **not** an authorised official protocol. BM-01
does not generate schedules, prove positional balance, freeze, run readiness/A/A
or compute statistics.

### 4.5 `receipt` v1

Required: `kind:"receipt"`, `schema_version:1`, `receipt_id`,
`gate ∈ {admission,analysis,verification,acceptance,attestation,framework-qa,source-qa}`,
`status ∈ {pass,fail,blocked,not-executed}`, `evidence_origin`,
`qualification_scope`, `subject:{experiment_id,run_id,protocol_digest,workload_digest}`,
`validator:{validator_id,validator_version,source_digest}`,
`inputs`, `dependencies`, `outputs`.
Optional: `qa_roster_digest`, `policy_digest`, `provenance`.

`inputs`/`outputs` are arrays of `{name,digest}`; `dependencies` entries also carry
`gate` and `receipt_id`. All three arrays must be serialised in ascending `name`
order with unique names. `receipt_id` must equal
`content_digest(payload_without_receipt_id)`.

The checked-in fixture is `status:"not-executed"`. Presence of a receipt proves
identity, not authenticity, dependency-chain validity or gate issuance.

### 4.6 `outcome` v1

Required: `kind:"outcome"`, `schema_version:1`,
`status ∈ {ok,error,blocked}`, `code`, `message` (≤1024 UTF-8 bytes),
`data`.

* `ok` ⇒ `code:"BM_OK"` and `data.kind:"inspect-summary"` with
  `experiment_id`, `profile`, `workload_id`, `protocol_id`, `protocol_digest`,
  `arm_ids`, `lane_ids`, `evidence_origin`, `qualification_scope`.
* `error`/`blocked` ⇒ non-`BM_OK` code and `data.kind:"error-detail"` with
  `reason` equal to the code's category, optional bounded `field_path`, optional
  safe relative `reference`.

`blocked` is mandatory for `BM_NOT_IMPLEMENTED`, `BM_EVIDENCE_UNAVAILABLE`,
`BM_ACQUISITION_PROHIBITED` and `BM_PUBLICATION_CONFLICT`. No statistics,
performance verdict or acquired `run_id` may appear in an `inspect-summary`.

## 5. CLI contract

```text
quervant-bench inspect  --experiment <semantic-id> [--format json]
quervant-bench validate --run <run-uuid> [--offline]
quervant-bench run      --experiment <semantic-id> --protocol <relative-path> --out <new-path>
quervant-bench analyze  --run <run-uuid> [--offline]
quervant-bench verify   --run <run-uuid> [--offline]
quervant-bench accept   --run <run-uuid> [--offline]
quervant-bench report   --run <run-uuid> [--offline]
quervant-bench --version
quervant-bench --help
```

| Verb | BM-01 behaviour |
| --- | --- |
| `inspect` | Loads `benchmarks/experiments/<id>/experiment.yaml` and the three referenced adjacent files, validates schema + semantics + bindings, prints one canonical `outcome.v1` to stdout, exit 0 |
| `run` | **Always** `BM_ACQUISITION_PROHIBITED` (77) after argument syntax validation; no file read, protocol open, clock read, subprocess, output directory or timing |
| `validate`/`analyze`/`verify`/`accept`/`report` | `BM_NOT_IMPLEMENTED` (69); no substitute execution and no fabricated PASS |
| `--help`, `--version` | Safe; exit 0 |

`inspect` is read-only and deterministic: repeated invocations on unchanged input
produce byte-identical stdout. Invalid input writes one structured error document
to stderr, leaves stdout empty and creates no files. `--offline` is parsed but
enables nothing. There is no `--force`, `--allow-unsafe`, `--dry-run` or implicit
default experiment.

### Exit codes

| Code | Category | Exit |
| --- | --- | ---: |
| `BM_OK` | success | 0 |
| `BM_USAGE` | invalid CLI usage | 64 |
| `BM_SCHEMA_INVALID` | invalid document | 65 |
| `BM_SCHEMA_UNSUPPORTED` | unsupported schema version | 65 |
| `BM_DUPLICATE_KEY` | invalid document | 65 |
| `BM_IDENTITY_INVALID` | invalid identity/binding | 65 |
| `BM_SCOPE_MISMATCH` | invalid provenance scope | 65 |
| `BM_UNSAFE_INPUT` | unsafe config/path/overlimit | 65 |
| `BM_FILE_MISSING` | missing input | 66 |
| `BM_NOT_IMPLEMENTED` | stage unavailable | 69 |
| `BM_EVIDENCE_UNAVAILABLE` | external archive unavailable | 69 |
| `BM_PUBLICATION_CONFLICT` | exclusive output collision (reserved) | 73 |
| `BM_ACQUISITION_PROHIBITED` | forbidden action | 77 |
| `BM_INTERNAL_ERROR` | unexpected internal defect | 70 |

### Example: successful inspect (stdout)

```json
{"code":"BM_OK","data":{"arm_ids":["baseline","candidate"],"evidence_origin":"synthetic","experiment_id":"synthetic-contract-smoke","kind":"inspect-summary","lane_ids":["rare-query","common-query"],"profile":"development","protocol_digest":"sha256:baaf3f6dca88de6cdaa0504e115b04dcc203a05c20dbba98baedbce6457e12df","protocol_id":"synthetic-balanced-pair","qualification_scope":"simulated","workload_id":"synthetic-contract-lanes"},"kind":"outcome","message":"validated synthetic contract declaration for synthetic-contract-smoke","schema_version":1,"status":"ok"}
```

### Example: prohibited `run` (stderr)

```json
{"code":"BM_ACQUISITION_PROHIBITED","data":{"kind":"error-detail","reason":"forbidden-action"},"kind":"outcome","message":"real benchmark acquisition is prohibited in BM-01; BM-09 owns the first real full-scale campaign","schema_version":1,"status":"blocked"}
```

## 6. Output directory contract (documented, never created in BM-01)

```text
benchmark-results/<experiment-id>/<run-id>/
  protocol.json  environment.json  measurements/
  admission.json analysis.json policy.json verification.json
  acceptance.json attestation.json manifest.json
```

Only the owning gate component may publish its own file; missing files are normal
before a gate runs; a publisher must exclusively create a new run root and never
overwrite. BM-01 documents this path pattern and creates no such tree.

## 7. Legacy inventory and compatibility registry

`benchmarks/scripts/bm-contract-inventory.py` is read-only and derives everything
from a pinned commit (`git ls-tree` / `git show`), never from the working tree and
never by executing historical code.

* `--baseline <commit>` (required)
* `--out <new-path>` — refuses to overwrite an existing file
* `--check <existing-file>` — byte-for-byte deterministic comparison

Per-path record: `path`, `kind`, `historical_family`, `schema_ids`,
`producer_consumers`, `source_baseline_sha`, `blob_sha`, `sha256`, `disposition`,
`compatibility`, `notes`.

`kind` vocabulary: runner, verifier, protocol, adapter, corpus_oracle, analysis,
policy, admission, acceptance, attestation, report_schema, evidence, profiling,
criterion, fixture, test, launcher, documentation, other_related.

`disposition` vocabulary: `retain_live`, `read_only_adapter_later`,
`preserve_archive`, `candidate_migrate_later`, `external_not_present`.

Format IDs are extracted only from explicit `schema`/`$id`/`SCHEMA_*` literals
that contain a `v<N>` (optionally `r<N>`) version segment, and are recorded
verbatim. `benchmarks/quervant_bench/legacy/legacy_formats.v1.json` registers each
ID with `reader_status: original_tool_only`, a future disposition and
`new_equivalence_status` restricted to `not_verified` / `evidence_unavailable`.
`verified` is rejected by the registry validator.

External roots (for example `target/`) are recorded with `blob_sha: null`,
`sha256: null` and `disposition: external_not_present`; member files and digests
are never invented.

## 8. Fixture and synthetic-binding conventions

`benchmarks/experiments/synthetic-contract-smoke/` declares 2 arms
(`baseline`, `candidate`), 2 lanes (`rare-query`, `common-query`), 2 blocks with
2 slots each, one appearance per arm per block, a `seeded-balanced` schedule with
seed `42`, and `build_identity.kind: synthetic`. These are contract-validation
values, **not** default experiment parameters.

The `benchmarks/quervant_bench/tests/fixtures/synthetic-contract-smoke/` copies of
the four YAML files are byte-identical to the catalog example (asserted by the
test suite). The additional `receipt.synthetic.json` is a `not-executed`
identity-only fixture and `inspect.golden.json` is the exact expected stdout.

## 9. Deferred ownership

| Capability | Owner |
| --- | --- |
| Provenance authentication, safe archives, admission receipts | BM-02 |
| Protocol compiler, scheduler, controller, synthetic adapter execution | BM-03 |
| Statistics, policy evaluation | BM-04 |
| Independent verification | BM-05 |
| Gate orchestration and attestation | BM-06 |
| Legacy retained-key migration | BM-07 |
| Cross-engine migration | BM-08 |
| First real full-scale qualification | BM-09 |

# BM-06 — QA evidence and reuse/invalidation matrix

## 1. Trust boundary

| Anchor | Supplied by | Verified by |
| --- | --- | --- |
| `expected_source_set_digest` | independently established operator/CI/test literal | fresh closed roster enumeration + raw byte hashing |
| `expected_profile_digest` | independent operator/CI/test literal | no-follow canonical read + `content_digest` |
| `expected_framework_qa_digest` | independent operator/CI/test literal | canonical read of `framework-qa-evidence.json` |
| `expected_source_qa_digest` | independent operator/CI/test literal | canonical read of `source-qa-evidence.json` |

A digest computed from the same untrusted file at verification time is not an
anchor. The test fixtures live in
`benchmarks/quervant_bench/tests/fixtures/qualification/trust-anchors.v1.json`
(deliberately outside the source roster) and are **L2 test trust only**.

## 2. Framework/source QA

Two distinct obligations, both mandatory upstream dependencies of Gate D:

| Gate | Roster (sorted) | Toolchain literal |
| --- | --- | --- |
| `framework-qa` | `python-contracts`, `python-mutations`, `python-vertical` | `python-3-12` |
| `source-qa` | `rust-clippy`, `rust-coverage`, `rust-format`, `rust-msrv`, `rust-stable`, `rustfs-service` | `rust-1-85-and-1-98` |

Each QA evidence document is closed:
`kind, schema_version, evidence_origin, qualification_scope, qa_gate, profile_digest,
source_set_digest, toolchain_id, checks[]`, where each check is
`check_id, executed, status, failed, mandatory_skipped, evidence_digest`.

**Per-check binding is mandatory.** For every `checks[]` entry there must be an
external canonical record at
`<qa_evidence_root>/<qa_gate>/<check_id>.json` with exactly:
`kind='synthetic-qa-check', schema_version, qa_gate, check_id, evidence_origin,
qualification_scope, source_set_digest, toolchain_id, executed, status, failed,
mandatory_skipped`. Its canonical content digest must equal the enclosing check's
`evidence_digest`, and every scalar must match. The directory must contain exactly
the declared records; extra or missing records fail closed. Records are reopened and
re-hashed immediately before publication and during committed-bundle loading.

A QA document is rejected when a mandatory check is missing, duplicated, reordered,
unknown, not executed, failed, blocked, `not-executed`, skipped, or when the
toolchain, source-set digest or profile digest drifts — even if the document has
been rehashed to a fresh self-digest **and** pinned as a new anchor, because the
shape/roster/toolchain checks still fail. The coordinator never executes QA,
approves a log or derives a PASS from an aggregate count.

## 3. Source roster

Deterministic, sorted, repository-root confined:

1. tracked `*.py` beneath `benchmarks/quervant_bench/{config,evidence,host,execution,
   protocol,analysis,verification,qualification,tests}/`;
2. `.github/workflows/ci.yml`, `benchmarks/pyproject.toml`,
   `benchmarks/scripts/test-scripts.sh`;
3. every `benchmarks/quervant_bench/config/schemas/*.json`.

`git ls-files -z` (argv, no shell) enumerates tracked paths after verifying
`git rev-parse --show-toplevel` equals the resolved `source_root`. Any **untracked**
`.py`/schema file in those locations, any symlink, or a missing mandatory file fails
closed (`BM_UNSAFE_INPUT`/`BM_EVIDENCE_UNAVAILABLE`). Generated `.pyc`, `target`,
archives and output artifacts are never members. Every BM-06 module and test is in
the roster; an added but unlisted Python module is an invalid roster.

## 4. Reuse key and lifecycle

Conceptual reuse key (represented by the verified receipts/manifest, never by an
untrusted editable cache entry):

```text
(experiment_id, run_id, source_set_digest, profile_digest, protocol_digest,
 workload_digest, seal_raw_digest, freeze_digest, scenario_digest,
 analysis_profile_digest, policy_profile_digest, resource_observations_digest,
 framework_qa_evidence_digest, source_qa_evidence_digest, toolchain_identifiers)
```

`qualify_synthetic_run` classifies the destination before deriving:

| Destination | Result |
| --- | --- |
| absent | derive A–E, verify in memory, publish the 15-file bundle |
| complete and all current anchors/edges match | `REUSED_VERIFIED` after fresh replay/re-hash; BM-04/BM-05 are **not** called |
| complete but any covered input changed | `BM_IDENTITY_INVALID`/`BM_PUBLICATION_CONFLICT`; never overwrite |
| incomplete (pending marker, missing/extra file) | `BM_PUBLICATION_CONFLICT`; partial evidence retained |

No clock lease, retry counter, background task or automatic cleanup exists.

## 5. Invalidation matrix (executed)

| Case | Mutation | Required observation | Executed test |
| --- | --- | --- | --- |
| REUSE-01 | none | `REUSED_VERIFIED`, same manifest digest, no new files, BM-04/05 poisoned | `test_e2e_02…`, `test_reuse_01…` |
| REUSE-02 | seal member bytes (manifest untouched) | A rejected before reuse | `test_reuse_02…` |
| REUSE-03 | protocol binding | subject/index mismatch | `test_reuse_03…` |
| REUSE-04 | analysis-profile bytes | B input identity mismatch | `test_reuse_04…` |
| REUSE-05 | one source `.py` byte, same measurement | source digest mismatch, D/E invalid | `test_reuse_05…`, `test_src_02…` |
| REUSE-06 | framework QA `executed=true→false`, document rehashed | pinned anchor/shape mismatch, D invalid | `test_reuse_06…` |
| REUSE-07 | source QA `mandatory_skipped=0→1`, document rehashed | pinned anchor/shape mismatch, D invalid | `test_reuse_07…` |
| REUSE-08 | QA roster changed + new profile digest | existing D/E invalid, no automatic acceptance | `test_reuse_08…` |
| REUSE-09 | `toolchain_id` changed with all passes | QA identity mismatch | `test_reuse_09…` |
| REUSE-10 | alternate run receipt with valid self-hash | subject/edge mismatch | `test_reuse_10…`, `test_rec_06…` |
| E-02 | rehashed attestation with stale source, matching manifest | anchored attestation input mismatch | `test_e_02…` |
| E-03 | manifest member digest tampered | raw member hash mismatch | `test_e_03…` |
| E-04 | `freeze_snapshot` modified, manifest rehashed | snapshot reconstruction mismatch | `test_e_04…` |
| E-05 | forged attestation→manifest dependency | wrong graph rejected | `test_e_05…` |
| E-06 | undeclared `.json`/`manifest.pending` inserted | exact inventory fails | `test_e_06…`, `test_pub_05/06…` |

## 6. QA adversarial matrix (executed)

`QA-01…12` cover: exact rosters accepted and receipted; missing/duplicate/reordered/
extra checks; passed-but-not-executed; `failed`/`blocked`/`not-executed`/skipped;
missing/stale/weak anchors; toolchain, source and profile drift; missing/extra/
tampered/cross-identity per-check records; cross-gate and foreign-run receipts;
unsafe roots. `SRC-01…03` cover the real roster anchor, a disposable-repository
one-byte mutation and untracked/symlinked source rejection.

---

# RF06 fixup — additional reuse checks and controlled re-freeze

## 7. Additional invalidation checks (executed)

| Case | Mutation (fully rehashed cascade) | Structural load | Trusted rejection |
| --- | --- | --- | --- |
| F06-E-02 | manifest + snapshot foreign `run_id` | PASS | `manifest.subject` |
| F06-E-03 | manifest + snapshot foreign `experiment_id`, `protocol_digest`, `workload_digest` | PASS | `manifest.subject` |
| F06-E-04 | manifest + snapshot forged `profile_digest` / `source_set_digest` | PASS | `manifest.<field>` |
| F06-D-02 | acceptance summary foreign `run_id` | PASS | `acceptance-summary.subject` |
| F06-D-03 | acceptance summary foreign `experiment_id` / `protocol_digest` | PASS | `acceptance-summary.subject` |
| F06-D-04 | acceptance summary forged `profile_digest` | PASS | `acceptance-summary.profile_digest` |
| F06-D-05 | acceptance summary forged `source_set_digest` | PASS | `acceptance-summary.source_set_digest` |
| F06-P-02 | framework QA check record mutated at the manifest hard-link | PASS (marker committed) | post-publication typed failure, no success |
| F06-P-03 | sealed member mutated at the manifest hard-link | PASS (marker committed) | post-publication typed failure, no success |
| F06-P-04 | failed post-publication call examined twice | n/a | 15 files preserved byte-identically, no repair |

`F06-D-01`, `F06-E-01`, `F06-P-01` and `F06-P-05` are the positive controls.
Existing `E-01…06`, `REC-01…09`, `REUSE-01…10`, `PUB-*`/`PUBL-*` remain unchanged
and pass.

## 8. Controlled source/QA trust re-freeze ledger

Source/test Python bytes changed in this fixup, so the checked-in anchors were
re-frozen exactly once after the final Python edit (intermediate red-phase
re-freezes were separate and are not the accepted ledger):

| Anchor | At reviewed head `37b0d35` | Final (`b1d67b4`) |
| --- | --- | --- |
| `source_set_digest` | `sha256:e9b43f1fdacd9784bf07bd8edfbce28e49a17d05e237526f2d30a9fa708baafb` | `sha256:d8f782f3db1cacbc22deead7717e984027ca1039795bd22b42471c9a94b15da4` |
| `framework_qa_digest` | `sha256:e9430e06f60ed041a100de3f5a4a682e7ccb2639dffd9f2d114a4c5eb7e3465d` | `sha256:de486da134604edf53746375af66d2f1a22efff0c940c4238e4b5deeb8cc646e` |
| `source_qa_digest` | `sha256:431450749b27d5a0a45c2f10b2f57deafd925135d3cc2b0811f639df9fdf78e2` | `sha256:e86ef1a692915a0ce9208f812774d1d8f9ff7fc3251c42a058f44d314806151a` |
| `profile_digest` | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` | **unchanged** |

Only `source_set_digest`, per-check `evidence_digest` values and the two QA document
`source_set_digest` fields were rewritten (canonical JSON, once); toolchains,
rosters, check IDs, statuses and the qualification profile are unchanged. The
`.json` fixtures remain outside the source roster, so there is no circular hash.
`F06-A-01` re-reads the whole chain from disk; `F06-A-02` shows an unchanged anchor
rejecting a mutated source tree and a mutated QA record.

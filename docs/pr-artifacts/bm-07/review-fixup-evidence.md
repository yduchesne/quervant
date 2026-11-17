# BM-07 RF07 independent-review fixup evidence

- Review ID: `5928282125`
- Plan ID: `BM07-RF07-F1`
- Starting head: `5a86da517ede00a499b9986e0acc451da360e64c`
- PR: [#108](https://github.com/yduchesne/quervant/pull/108)
- Scope: historical read-only assessor status classification only.

## 1. Defects and fix

### RF07-01 — false `AUTHENTIC`

The previous assessor returned `historical_archive=AUTHENTIC` when three
campaign directories contained header-compatible `manifest.json` files. It did
not require a seal, raw slots, host/build evidence, or execution of the frozen
historical verifier. A fabricated header-only tree was therefore mislabelled.

**Fix:** the assessor now returns `PRESENT_UNVERIFIED` for header-compatible
metadata. BM-07 has no approved full-archive authentication path and **never
returns `AUTHENTIC`**. `ARCHIVE_AUTHENTIC` remains reserved vocabulary for a
future approved verifier.

### RF07-02 — malformed present evidence mislabelled unavailable

The previous assessor converted malformed/truncated present JSON into
`EVIDENCE_UNAVAILABLE`. Missing evidence and invalid evidence are now distinct:

- genuinely absent archive/campaign/required file → `EVIDENCE_UNAVAILABLE`;
- present malformed/duplicate/array/null/UTF-8-invalid JSON → `FAILED_AUTHENTICATION`;
- unsafe filesystem entry/size/entry-count → typed `BM_UNSAFE_INPUT`.

## 2. Decision table implementation

| Case | Outcome |
|---|---|
| S01 frozen protocol absent | `EVIDENCE_UNAVAILABLE` |
| S02 frozen protocol hash differs | `FAILED_AUTHENTICATION` |
| S03/S04 archive absent/empty | `EVIDENCE_UNAVAILABLE` |
| S05 required campaign/file missing | `EVIDENCE_UNAVAILABLE` |
| S06 present malformed/duplicate/non-object JSON | `FAILED_AUTHENTICATION` |
| S07 manifest identity wrong | `FAILED_AUTHENTICATION` |
| S08/S09/S10 authorization schema/protocol/rehearsal wrong | `FAILED_AUTHENTICATION` |
| S11/S12 header-compatible, no full verifier | `PRESENT_UNVERIFIED` |
| S13/S14 symlink/nonregular/oversize/too many entries | typed `BM_UNSAFE_INPUT` |
| S15 malformed + header-compatible | `FAILED_AUTHENTICATION` |
| S16 missing + header-compatible | `EVIDENCE_UNAVAILABLE` |
| mixed malformed + missing | `FAILED_AUTHENTICATION` (corruption precedence) |

Every non-unsafe outcome keeps:

```text
historical_numeric_parity=NOT_EXECUTED
historical_decision_parity=NOT_EXECUTED
historical_acceptance_gate=BLOCKED
legacy_paths_retired=NO
```

The historical verifier field is `NOT_EXECUTED` except for
`FAILED_AUTHENTICATION`, where it is `FAILED`.

## 3. Red-first evidence

Tests were added before the production edit and executed against starting head
`5a86da5`. The run produced 25 failures across 13 tests. Key reproduced defects:

| Test | Old observed | Required |
|---|---|---|
| HF07-01 | `AUTHENTIC` | `PRESENT_UNVERIFIED` |
| HF07-02 | `AUTHENTIC` for `authorization.json={}` | `FAILED_AUTHENTICATION` |
| HF07-06 | `EVIDENCE_UNAVAILABLE` for malformed present JSON | `FAILED_AUTHENTICATION` |
| HF07-19 | `EVIDENCE_UNAVAILABLE` for malformed+missing | `FAILED_AUTHENTICATION` |
| HF07-20 | `AUTHENTIC` with control `source_experiment_sha` | `FAILED_AUTHENTICATION` |
| HF07-21 | missing `ARCHIVE_PRESENT_UNVERIFIED` export | exported |

The old code also assigned `historical_numeric_parity=NON_EQUIVALENT_CONTRACT`
for a header-only tree; the fixup keeps it `NOT_EXECUTED`.

## 4. Green test traceability

| Test | Property |
|---|---|
| HF07-01 | header-compatible, no seal → `PRESENT_UNVERIFIED` |
| HF07-02/03/04 | authorization header compatibility |
| HF07-05/20 | manifest identity compatibility, control source SHA absent/null |
| HF07-06 | malformed/duplicate/array/null/UTF-8 present JSON → failed |
| HF07-07/10 | raw stub/no seal does not promote |
| HF07-08/09 | absent/empty/missing remains unavailable |
| HF07-11/12 | parity blocked; no `AUTHENTIC`/`QUALIFIED`/`EXACT`/`PASS` token |
| HF07-13 | symlink/nonregular/oversize/entry-count unsafe rejection |
| HF07-14 | no writes to fixture or frozen historical paths |
| HF07-15 | no subprocess/legacy execution |
| HF07-16 | original historical SHA literals unchanged |
| HF07-17 | final source/QA anchor chain exact |
| HF07-18 | stale source digest and altered QA record rejected |
| HF07-19 | malformed+missing prefers failed authentication |
| HF07-21 | public constants/signature/`__all__` preserved + new state exported |

## 5. Controlled synthetic re-freeze

The re-freeze is synthetic QA fixture maintenance only; it is **not** historical
authentication.

| Field | Value |
|---|---|
| Previous source-set digest | `sha256:a8af53867f04bca986f1f64d076ec2e037d36e4160145432fdea305d93deee97` |
| Final source-set digest | `sha256:2b0ee6ab1eb990b4fdc1d574772145e1492497680d53c273e0c753083826fe84` |
| Profile digest (unchanged) | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` |
| Previous framework QA | `sha256:7ce79d12e53e1857fa034f7e1e886cb943f1e7a234c155091ae3a5e06b9c71ea` |
| Final framework QA | `sha256:d38171fd5192328ddf51d5afcccb9b32f060676008e073e6e8c3b2d34ca4f9b3` |
| Previous source QA | `sha256:ba4d7bcb98d1d7d10e661304c09860f30a2a26f2c8dff9f7a89118d207350f39` |
| Final source QA | `sha256:23d0df650038ee0279ad4218618559133fd50eed171326508dd535082c2a0ebc` |

Only source-set fields, per-check evidence digests, two parent QA document
digests and the three anchor digest fields changed. QA rosters, statuses,
toolchains, check IDs and the qualification profile are unchanged.

## 6. Local verification after fixup

| Check | Result |
|---|---|
| Historical module | PASS — 28 tests |
| Retained-key suites | PASS — 67 tests |
| BM-06 qualification suites | PASS — 109 tests |
| BM-05 verification suites | PASS — 111 tests |
| BM-04 analysis suites | PASS — 190 tests |
| Full Python suite | PASS — 839 tests, 1 established skip |
| Inventory check | PASS |
| Script test suite | PASS — 108 passed |
| Stable Rust fmt/clippy/tests | PASS |
| MSRV fmt/clippy/tests | PASS |
| Rust line coverage | PASS — 92.70% |
| Documentation | PASS |
| `cargo bench --no-run` | PASS — compile only |
| Real timed acquisition | NOT RUN |
| Hosted CI — implementation head `9c2bf40` | PASS — run `43970644323`, all four jobs success |

## 6.1 Hosted CI observation

GitHub Actions run
[`43970644323`](https://github.com/yduchesne/quervant/actions/runs/43970644323)
on implementation head `9c2bf409504f41df5af8f45db85a79d116d6ddf6` completed with
all four required jobs successful:

```text
python-contracts  success
rust              success
msrv              success
rustfs            success
```

## 7. Current historical state

```text
HISTORICAL_ARCHIVE=EVIDENCE_UNAVAILABLE
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED
HISTORICAL_DECISION_PARITY=NOT_EXECUTED
HISTORICAL_ACCEPTANCE_GATE=BLOCKED
LEGACY_PATHS_RETIRED=NO
```

`target/pr15i-d3-c` remains an empty stub. Header-compatible metadata, if later
present, is `PRESENT_UNVERIFIED` only. A full historical acceptance claim still
requires a separately approved full-archive authentication/parity milestone.

## 8. Residual risks

1. `PRESENT_UNVERIFIED` proves only that selected header literals match.
2. BM-07 does not verify seals, raw slots, host readiness, build provenance or
   original statistics.
3. The synthetic QA fields remain simulated L2 assertions, not CI proof.
4. Final-head hosted CI and independent review remain mandatory.
5. No historical numeric/decision parity, official qualification or legacy
   retirement is claimed.

## 9. RF07-F2 — intra-campaign classification precedence

- Plan ID: `BM07-RF07-F2`
- Starting head: `f3acd3b76c02f590ba7d0d7f87d13fca72647345`
- Defect: `_audit_campaign` returned `EVIDENCE_UNAVAILABLE` on the first missing
  required file without inspecting a present sibling. A malformed
  `authorization.json` could therefore be hidden by a missing `manifest.json`.

### 9.1 Red-first evidence

Thirteen new tests (`HF07-22…34`) were added before the production edit and run
against the old head. The new class produced **11 failures**. Key red cases:

| Test | Old observed | Required |
|---|---|---|
| HF07-22 (missing manifest + malformed auth) | `EVIDENCE_UNAVAILABLE` | `FAILED_AUTHENTICATION` |
| HF07-23 (missing manifest + `{}` auth) | `EVIDENCE_UNAVAILABLE` | `FAILED_AUTHENTICATION` |
| HF07-33 (missing manifest + `[]`/bad UTF-8 auth) | `EVIDENCE_UNAVAILABLE` | `FAILED_AUTHENTICATION` |
| HF07-34 (malformed manifest + symlink auth) | no `BenchError` | `BM_UNSAFE_INPUT` |
| HF07-27/28 (missing manifest + unsafe/oversize auth) | unavailable | `BM_UNSAFE_INPUT` |

The cross-campaign `HF07-19` remained green; the new defect was strictly
intra-campaign sibling inspection.

### 9.2 Implementation delta

Only `_audit_campaign` changed. It now:

1. inspects both required files even after a missing sibling;
2. records the first missing relative path and defers the absence decision;
3. accumulates malformed/duplicate/non-object/header-invalid present evidence;
4. propagates unsafe/oversize/no-follow errors immediately;
5. returns `FAILED_AUTHENTICATION` if any present member is invalid;
6. raises `BM_EVIDENCE_UNAVAILABLE` only when both members were inspected and
   only absence remains;
7. returns `_HEADER_COMPATIBLE` only when both present documents are valid and
   header-compatible.

The cross-campaign collector, header predicates, public signature, constants and
`ARCHIVE_AUTHENTIC` reservation are unchanged. BM-07 still never returns
`AUTHENTIC`.

### 9.3 Green results

| Check | Result |
|---|---|
| Historical module | PASS — 41 tests (HF07-01…34 plus PAR/LEG) |
| Retained-key suites | PASS — 80 tests |
| BM-06 qualification | PASS — 109 tests |
| BM-05 verification | PASS — 111 tests |
| BM-04 analysis | PASS — 190 tests |
| Full Python suite | PASS — 852 tests, 1 established skip |
| Inventory check | PASS |
| Script suite | PASS — 108 passed |
| Stable Rust fmt/clippy/tests | PASS |
| MSRV fmt/clippy/tests | PASS |
| Rust line coverage | PASS — 92.70% |
| Documentation | PASS |
| `cargo bench --no-run` | PASS — compile only |

### 9.4 Follow-up synthetic re-freeze

| Field | Value |
|---|---|
| Previous source-set digest | `sha256:2b0ee6ab1eb990b4fdc1d574772145e1492497680d53c273e0c753083826fe84` |
| Final source-set digest | `sha256:28170ada72d89f00277543a7e2b73def9367bc6a24dcb82ad0be31ebf560a659` |
| Profile digest (unchanged) | `sha256:9db01390e29834ed3d368489adc72005aa49029563cbc1e015cf07d0ef4a046c` |
| Previous framework QA | `sha256:d38171fd5192328ddf51d5afcccb9b32f060676008e073e6e8c3b2d34ca4f9b3` |
| Final framework QA | `sha256:0e8408ebee8e54fe5465bc79610a07d5fd71b5f57ba584bded09b651637310e3` |
| Previous source QA | `sha256:23d0df650038ee0279ad4218618559133fd50eed171326508dd535082c2a0ebc` |
| Final source QA | `sha256:e1abe182ab046edf3cfc254932927a29346b75616919441fadaf89fe8a94f31a` |

Exactly nine per-check records, two parent QA documents and three anchor digest
fields were updated. QA rosters, statuses, toolchains and the profile digest are
unchanged. `HF07-17/18`, `F06-A-01/02`, `SRC-01…03` and `ANC-03` pass. The
previous source digest is rejected. `QA_FIXTURES=SIMULATED_ONLY`.

### 9.5 Final historical state

```text
HISTORICAL_ARCHIVE=EVIDENCE_UNAVAILABLE (current external root remains an empty stub)
HISTORICAL_NUMERIC_PARITY=NOT_EXECUTED
HISTORICAL_DECISION_PARITY=NOT_EXECUTED
HISTORICAL_ACCEPTANCE_GATE=BLOCKED
LEGACY_PATHS_RETIRED=NO
```

Header-compatible metadata remains `PRESENT_UNVERIFIED`. Full archive
authentication/parity still requires a separately approved milestone.

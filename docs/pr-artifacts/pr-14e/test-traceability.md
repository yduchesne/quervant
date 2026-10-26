# PR 14E — test traceability (`E14E-01` … `E14E-20`)

**Status: `EVIDENCE TRACEABILITY — PR 14 NOT ACCEPTED`.** Each `E14E-*` ID is a
PR 14E verification requirement. These IDs are **new** and do not renumber,
replace or alias any original PR 14 obligation ID. Historical obligations remain
keyed as `PR14C:<section>:<literal>` in
[acceptance-crosswalk.md](acceptance-crosswalk.md).

Base/head for every locally executed row: `dc506f6ee28014e64fbc9070db6925b73063d9ba`
on branch `docs/pr14e-acceptance-reconciliation`. Command output, counts and
failure classification are in [validation-report.md](validation-report.md).

| ID | Input / fixture | Oracle / assertion | Result |
|---|---|---|---|
| E14E-01 | Git `main` + GitHub merge records | PR 14C/14D ancestry and exact base SHA | **PASS** |
| E14E-02 | PR 14C crosswalk | Exactly 127 preserved rows; `96/11/2/18/0` | **PASS** |
| E14E-03 | Reused ID prefixes | Composite keys unique; no generation collision | **PASS** |
| E14E-04 | PR 14D code + CI + fixture | Correction merged; reviewed-head checks verified at immutable links | **PASS** |
| E14E-05 | B20/B21 | Charge increase reported; physical-memory limitation stated | **PASS** |
| E14E-06 | JSON scalar winner | Single materialization after admission; borrowed comparison parity; source-level proof | **PASS** |
| E14E-07 | Zero-GET evidence | Counter at an isolated PR 14 query boundary; no inference from success | **BLOCKED** |
| E14E-08 | Physical hit identity | Assertion ties selected physical hit to projection (incl. PIT/upsert) | **BLOCKED** |
| E14E-09 | JSON `J14`/`J15` | Direct old-segment/fail-closed fixtures + matching tests | **PASS** |
| E14E-10 | `U/G/R/X` historical sources | No fabricated mapping; unrecovered `X` IDs stay `BLOCKED` | **PASS** |
| E14E-11 | P4 `V/B/W` rows | Fresh trials delegated to PR 14F; old numbers provenance only | **PASS** (truthful `BLOCKED`) |
| E14E-12 | `W08` exception | Approved manifest present; `N/A`, never measured | **PASS** |
| E14E-13 | Current regression suites | Actual commands/suites green at current head | **PASS** |
| E14E-14 | Stable/MSRV/tooling | Command matrix correctly qualified | **PASS** |
| E14E-15 | Coverage | Measured `≥ 85 %` at current head (not copied) | **PASS** — 91.29 % lines |
| E14E-16 | CI | PR 14E head checks separately identified from #64 checks | **BLOCKED / PENDING** (PR 14E head not yet pushed) |
| E14E-17 | Status/crosswalk | Transition matrix sums to 127; all 18 previous `BLOCKED` accounted for | **PASS** |
| E14E-18 | Negative audit | No PR 14 DONE, benchmark-qualified, PR 15, release or self-merge claim | **PASS** |
| E14E-19 | Provider boundary | Prior immutable evidence distinguished from fresh execution | **PASS** |
| E14E-20 | Additive history | Historical dated files not rewritten to falsify past state | **PASS** |

---

## E14E-01 — ancestry and base identity

```sh
git fetch origin --prune
git status --porcelain                  # empty
git rev-parse origin/main               # dc506f6ee28014e64fbc9070db6925b73063d9ba
git rev-parse HEAD                      # dc506f6ee28014e64fbc9070db6925b73063d9ba
git merge-base --is-ancestor 6d18ebed4c2a8c7d73ca9e5078019d50546cb675 origin/main  # 0
git merge-base --is-ancestor 635c7f4a89c5e2e9478da23c2a533e8dc1f80e09 origin/main  # 0
git merge-base --is-ancestor 376023b53b557a30367097f29a41328c798188d4 origin/main  # 0
```

GitHub API: PRs #61/#62/#63/#64/#65 all `merged: true` with the merge SHAs
recorded in `baseline-inventory.md` §1. Observed: base equals the plan's expected
`dc506f6`; no X01/X02/X03 trigger.

## E14E-02 — 127-row preservation

Re-extraction of `docs/pr-artifacts/pr-14c/acceptance-reconciliation.md` tables:

```sh
python3 - <<'PY'
import re
from collections import Counter
c=Counter()
for l in open('docs/pr-artifacts/pr-14c/acceptance-reconciliation.md'):
    if not l.strip().startswith('|'): continue
    last=[x.strip() for x in l.strip().strip('|').split('|')][-1].replace('*','')
    if 'SUPERSEDED WITH EVIDENCE' in last: c['SUPERSEDED']+=1
    elif 'NOT APPLICABLE (APPROVED)' in last: c['NA']+=1
    elif last.startswith('BLOCKED'): c['BLOCKED']+=1
    elif last.startswith('PASS'): c['PASS']+=1
print(len(list(c.elements())), c)
PY
```

Observed: `127 Counter({'PASS': 95, 'BLOCKED': 19, 'SUPERSEDED': 11, 'NA': 2})`.
The single delta from the published `96/18` is the `§6` row whose adjudication
cell reads `PASS (legacy fallback J14/J15 remain BLOCKED)` — a naive
suffix-match classifies it `BLOCKED`. Counting that row by its leading token
reproduces the published `PASS=96, BLOCKED=18`. Rule documented in the crosswalk
(§1) and challenged in `adversarial-review.md` §1 row 1. No row was added,
dropped or reclassified to make the totals fit.

## E14E-03 — composite key uniqueness

```sh
python3 - <<'PY'
import re
from collections import Counter
rows=[l for l in open('docs/pr-artifacts/pr-14e/acceptance-crosswalk.md')
      if re.match(r'^\| \d{3} \|', l)]
print(len(rows))
PY
```
Observed: 127 crosswalk rows; the `CW-###` keys are dense and unique
(`1…127`, no gap). Literal IDs are **not** unique across generations by design
(`I07`, `I13`, `I8`, `P01–P05`, `G01–G05`, `R01–R07`, `B01–B04`, `Q01–Q09`,
`V01–V14` recur), so each row is keyed by `PR14C:<section>:<literal>`, never by
literal alone. Repeated literals live in distinct rows: CW-012 vs CW-055/CW-068;
CW-018 vs CW-058/CW-073; CW-039 vs CW-078; CW-040 vs CW-095…104; CW-031 vs
CW-114…117.

## E14E-04 — PR 14D merged correction, code and CI

- `git merge-base --is-ancestor 6d18ebe origin/main` → 0 (merged).
- Source inspection at `dc506f6`: `json_sort_value` compares borrowed
  `&JsonNode`, `push_occurrence` preflights capacity,
  `materialize_json_sort_winner` reserves before the single conversion, and the
  `#[cfg(test)]` `winner_probe` increments only after admission.
- PR #64 `merged: true`; head `635c7f4`; merge `6d18ebe`.
- Check runs (public API):
  `https://api.github.com/repos/yduchesne/quervant/commits/635c7f4…/check-runs`
  → `rust`, `msrv`, `rustfs` all `completed / success`
  (`actions/runs/40326618997`).
- Merge-commit CI `6d18ebe` and `main` `dc506f6` green
  (`actions/runs/40361560578`, `actions/runs/40361657335`).
- Source drift: `git diff --stat 3f82284..dc506f6 -- crates/ Cargo.toml Cargo.lock benchmarks/ .github/`
  → empty.

Result: **PASS** for "correction merged and CI-verified"; PR 14 acceptance is
**not** implied (that requires the human risk signoff, benchmarks and review).

## E14E-05 — B20/B21 wording and values

Executed: `cargo test -p quervant-core --all-features --test pr14b_json_memory -- --nocapture --test-threads=1`
(`1 passed, 1 ignored` child entrypoint). Recorded thresholds
`387 / 45,726 / 1,462,302 B` vs the pre-fix constant `112 B`; tracked peaks
`33,547 / 110,392 / 2,518,968 B`; cancellation `7,397 B`.
Oracle: `resource-characterization.md` must match the test output; the text must
not call the meter RSS, a cap or a bound. Observed: matches; the limits are stated
in `resource-risk-reconciliation.md` §4 and no physical-memory claim exists.

## E14E-06 — JSON scalar winner materialization

Executed: `cargo test -p quervant-core --all-features --lib json_sort_winner_tests`
→ `f01_f03_borrowed_comparator_matches_canonical`,
`f01_non_scalar_nodes_are_not_comparable`,
`f07_winner_conversion_runs_only_after_admission`, `t02/t05/t08/t09` and the other
unit rows pass. Oracle: the `winner_probe` counter must be `0` on a rejected
reservation and exactly `1` after an admitted conversion; comparator parity with
`canonical_scalar_cmp` across all node pairs and both orders. Observed: pass.

## E14E-07 — zero query-time remote GET

Executed zero-GET assertions found in the repository:
`pr13_remote::v01_lexical_results_match_local_oracle` (non-ignored; lexical
queries over a `FakeObjectStore`, `get_calls() == 0` after `reset_counters()`).
`pr13_oracle` (O09) and `pr13_bench_remote` assertions are `#[ignore]` provider /
benchmark lanes and were **not** executed here.

Oracle required by EAD-08: separated cold-open/cache-warm GETs from query-time
GETs, at the PR 14 typed/mixed/batch/pinned entry points, with a positive control
that the cold window *does* increment the counter. Observed: no such test exists,
and none may be added in a docs-only PR. Result: **BLOCKED** — CW-018, CW-058,
CW-073 and dossier D-01/D-05/D-08.

## E14E-08 — exact physical hit identity

Inspected `SelectedHit`, `collect_mixed`, `project_selected_hits` and the
`doc_key(doc_id) != key → CorruptIndex` guard. Executed
`pr14_f1_hardening::p02_projection_uses_current_version` as the closest existing
oracle (PASS). Oracle required by EAD-09: an assertion tying the selected
`(segment_index, doc_id)` to the projected fields, including upsert / delete /
PIT old-new views. Observed: implementation-level identity only; no assertion and
no `HitRef` type. Result: **BLOCKED** — CW-055, CW-068, dossiers D-04/D-07.

## E14E-09 — legacy JSON `J14` / `J15`

| Case | Command | Observed |
|---|---|---|
| `J14` fallback + typed failure | `cargo test -p quervant-core --all-features --lib legacy_json_tests` | 2 passed (`legacy_source_fallback_and_unstored_error`, `b1_legacy_source_fallback_wide_field`) |
| `J15` frozen artifact + corruption | `cargo test -p quervant-core --all-features --test pr14_storage_vertical b18_b19 -- --test-threads=1` | 1 passed (`b18_b19_historical_json_segment_compatibility`) |
| `J15` negotiation variants | `cargo test -p quervant-core --all-features --test pr11_json_corruption t14_negotiation -- --test-threads=1` | 1 passed |
| `J15` digest/corruption (14D) | `cargo test -p quervant-core --all-features --test pr14d_json_sort_memory d07_ -- --test-threads=1` | 1 passed |

Oracles: `paths.is_none()` on the section-stripped segment, stored-source match /
clean negative, `UnsupportedOperator` for indexed-not-stored, frozen SHA-256
`0528a62c…a02f`, byte-identical writer reproduction, corruption and
`UnsupportedFormatVersion { major: 2 }` rejection. All observed.

## E14E-10 — historical `U/G/R/X`

Searched `docs/` and `git log --all -S"X01" -- docs/` (`fa82db7`, `d0c445a`,
`e0e1dcb`). No per-ID `X01…X13` definition exists; the corrective generation reuses
`X01`/`X01–X10` with contradictory meanings. `U`/`G`/`R` families were adjudicated
at family level exactly as PR 14C recorded them, with named replacement suites.
No mapping was invented. Result: **PASS** for the reconciliation behaviour;
CW-041 stays `BLOCKED` (dossier D-16).

## E14E-11 — P4 obligation truthfulness

No trial was run. `benchmark-dependency.md` keeps `V11/V12`, `B01`, `B03`,
`W01–W07/W09`, `§8` item 6, phase `14F` as `BLOCKED — PR 14F`; historical
`ab9b2d7` trials are provenance only (and have **0** check runs through the API,
i.e. they are not CI-qualified either). Result: **PASS** for truthful blocking.

## E14E-12 — W08 approved exception

- `benchmarks/reports/pr14-p4-w08-exemption.json` present:
  `workload: pr14_p4_v1`, `w08.status: not_applicable`, `approved: true`,
  referencing `docs/pr-artifacts/pr-14/p4-w08-stop.md`.
- `validate_w08_exemption()` in `benchmarks/scripts/validate-pr14-p4.py`
  requires exactly those fields.
- `python3 benchmarks/scripts/validate-pr14-p4.py --self-test` → `PASS self-test`
  (the self-test includes the W08 negative cases).
- `W08` is labelled `NOT APPLICABLE (APPROVED)` in CW-119/CW-125 and is never
  reported as measured.

## E14E-13 — current regression suites

| Command | Observed |
|---|---|
| `cargo test --workspace --all-targets` | 2044 passed, 0 failed, 10 ignored |
| `cargo test --workspace --all-targets --all-features` | 2048 passed, 0 failed, 73 ignored |
| `cargo +1.85.0 test --workspace --all-targets --all-features` | 2048 passed, 0 failed, 73 ignored |
| `cargo test -p quervant-core --all-features --test pr14d_json_sort_memory` | 13 passed |
| `cargo test -p quervant-core --all-features --test pr14b_json_memory -- --nocapture --test-threads=1` | 1 passed, 1 ignored (child) |

Per-suite PR 14 counts at this head: `pr14a_public_cursor` 26, `pr14_json` 13,
`pr14_typed_predicates` 12, `pr14_projection` 10, `pr14_unified_mixed` 14,
`pr14_unified_cursor` 11, `pr14_batch` 12, `pr14_batch_memory` 31,
`pr14_batch_governance` 7, `pr14_aggregation` 5, `pr14_compound_aggregation` 24,
`pr14_f1_hardening` 23, `pr14d_json_sort_memory` 13, `pr14_storage_vertical`
local 5 (+14 ignored provider), `pr11_json_corruption` 8 (+1 ignored),
`pr11_json_paths` 10, `pr11_json_mutations` 7, `pr11_json_properties` 4,
`pr13_remote` 5 (+3 ignored). Full matrix in `validation-report.md`.

## E14E-14 — toolchain qualification

`rustc 1.98.1 (48a229cea 2026-09-01)` / `cargo 1.98.1` and `cargo +1.85.0`
(`1.85.0 (d73d2caf9 2024-12-31)`) both ran fmt, clippy (`--all-targets
--all-features -- -D warnings`) and tests; all passed. MSRV and stable are
reported separately, never merged into one result.

## E14E-15 — coverage

`cargo llvm-cov --workspace --all-targets --all-features --fail-under-lines 85`
→ **PASS**. Measured `91.29 %` lines (48,236 lines, 4,200 missed), `91.84 %`
regions, `87.36 %` functions. The value coincides with the PR 14D figure because
no code changed since `3f82284`; it was re-measured, not copied.

## E14E-16 — CI

| Scope | State |
|---|---|
| Historical PR 14 line (`a61f0b8`, `635c7f4`, `6d18ebe`, `dc506f6`) | **VERIFIED** — `rust`/`msrv`/`rustfs` success |
| Never-pushed local SHAs (`e0e1dcb`, `d0c445a`, `ab9b2d7`, `d0e1bbb`) | **NO CHECK RUNS** — not claimed |
| PR 14E head | **PENDING** — checks begin only after the branch is pushed |

PR 14E does not claim its own CI result before it exists (decision X17).

## E14E-17 — transition accounting

Transition matrix in `acceptance-crosswalk.md` §9 sums to 127 with
`BLOCKED→PASS` only for CW-024, CW-025, CW-060, CW-120 (each with named proof)
and `BLOCKED→BLOCKED` for the other 14. No `PASS→BLOCKED/FAIL` transition
occurred. Verified by re-parsing the crosswalk tables: current totals
`PASS 100 / SUPERSEDED 11 / N/A 2 / BLOCKED 14 / FAIL 0 = 127`.

## E14E-18 — negative audit

Searched all new files and the two successor notes: no text claims PR 14 DONE,
accepted, benchmark-qualified, PR 15 unblocked, W08 measured, zero-GET proven,
hit identity proven, or v0.1 released; no self-merge instruction. See
`adversarial-review.md` §2.

## E14E-19 — provider-boundary honesty

Real-provider rows are labelled `REUSE-14D`; no provider was started in PR 14E.
The bridge is the verified absence of code drift between `3f82284` and
`dc506f6`. Fresh provider runs are **not** claimed (EAD/§8 of the plan).

## E14E-20 — additive history

`git diff --stat origin/main` for this branch is confined to
`docs/pr-artifacts/pr-14e/*` plus two dated additive notes in
`docs/pr-artifacts/pr-14c/{acceptance-reconciliation,resource-risk-disposition}.md`.
PR 14D documents and `docs/ROADMAP_V01.md` are untouched; no historical
conclusion was rewritten.

# PR 15E Phase 6 — design and decisions (investigation-only)

**Status: `P6_PROFILE_BLOCKED_OPERATOR`.** Source preparation and non-timed checks are
complete; the four required CPU captures were **not** collected because the PR 15E-A profiler
requires a genuine, current operator-written attestation that the maintainer's Phase 6
authorization explicitly did **not** waive. No measurement, attribution share or optimization
recommendation is claimed.

**Scope:** read-only investigation of current-source CPU cost. No production Rust, schema,
index, manifest, public API, frozen benchmark input, profiler driver or verifier change.

| Item | Value |
|---|---|
| Branch / PR | `dev/pr15e-b1-live-bitmap-postings-membership` / #83 |
| Required measured source | `e448469d6c98d9ef4b4a827ad9567363a888a185` (Phase 5 evidence anchor) |
| Phase 5 production/tooling anchor | `66b266fd8850c90836d4327700f279a2ed2c4b92` |
| Original merged `main` | `c3083d83ab88fd53f30d34d34c4860d29aa6493e` |
| Private run directory (gitignored) | `target/pr15e/phase6-e448469d-01` |

## 1. Purpose and boundary

Determine what dominates CPU time **now** in the accepted Phase 5 search path (notably the
100K rare/K100 lane), using the frozen PR 15D corpus/oracle and the existing PR 15E-A
`perf` capture driver. Output is a sanitized, explicitly **partial-campaign** report plus one
bounded next-phase candidate **or** an unresolved verdict. No implementation.

## 2. Invariant traceability (P6-I01..P6-I15)

| ID | Invariant | How this phase enforces it | State |
|---|---|---|---|
| P6-I01 | Profiled executable is built from the immutable P5-accepted source | `prepare.json.source.head_sha` equals the required SHA; the harness rejects dirty trees and re-checks SHA/digests per capture | Enforced at prepare; capture not run |
| P6-I02 | Real Quervant `FsDirectory` index + real frozen oracle | `adapter_evidence.index_backend == FsDirectory`, real smoke lanes, frozen corpus manifest `69052c66…` | Verified at prepare |
| P6-I03 | Exactly the four N100K/K100/perf captures at the fixed durations | Fixed command matrix in the execution record; driver `validate_capture_args` rejects any other lane/duration | Not run (blocked) |
| P6-I04 | Every profiled reply equals the independent oracle | Driver `_verify_capture` + per-capture manifests | Not run (blocked) |
| P6-I05 | Source/binary/corpus/index digests unchanged across captures | Driver per-capture fingerprint checks | Not run (blocked) |
| P6-I06 | Genuine before/after contention checks | Two real probes per capture, `clear` required | Not run (blocked) |
| P6-I07 | Only sampled CPU is attributed, with frame/hash citations | Report rules in the qualification doc; no simulated numbers | No data yet |
| P6-I08 | Inclusive percentages are never summed as exclusive | Attribution instructions separate `self` and `inclusive` | No data yet |
| P6-I09 | Four valid captures are `FOCUSED_COMPLETE`, never 20/20 `EVIDENCE_COMPLETE` | Focused gate restricted to 4/4; legacy verifier expected `PARTIAL` | Not run (blocked) |
| P6-I10 | Prior B1/P3/P4/P5 and PR 15E-A evidence unmodified | `git diff` audit; only Phase 6 docs added | Verified |
| P6-I11 | No production/schema/API change | Changed-path audit limited to `docs/pr-artifacts/pr-15e-b1/phase6-*.md`, handoff and decision log | Verified |
| P6-I12 | No optimization implemented | No `crates/` change; recommendation withheld | Verified |
| P6-I13 | Attestation is genuine and window-scoped | No attestation was created; the driver refused the capture | **Blocker** |
| P6-I14 | Published evidence is sanitized | Publication sanitization gate (not applicable — nothing measured) | N/A |
| P6-I15 | Failures reported, never converted to success | Status `P6_PROFILE_BLOCKED_OPERATOR`; refusal evidence recorded | Verified |

## 3. Fixed capture matrix (not executed)

| ID | N | Class | K | Tool | Window |
|---|---:|---|---:|---|---:|
| P6-C01 | 100000 | rare | 100 | perf | 30 s |
| P6-C02 | 100000 | absent | 100 | perf | 30 s |
| P6-C03 | 100000 | medium | 100 | perf | 30 s |
| P6-C04 | 100000 | common | 100 | perf | 60 s |

Optional P6-C05 (`100000/rare/k100/heaptrack`, 30 s) remains conditional on the §9 trigger and
is not authorized while the required CPU set is uncollected.

## 4. Attribution groups (fixed vocabulary, unused until data exists)

`P6-G01_STAGING`, `P6-G02_STATS`, `P6-G03_COLUMNS`, `P6-G04_KEYS`,
`P6-G05_STORED_PROJECTION`, `P6-G06_QUERY_SCORING`, `P6-G07_ADAPTER_RUNTIME`,
`P6-G08_UNKNOWN`. Membership is by named frame, never by reinterpretation, and inclusive
chains are reported separately from exclusive shares.

## 5. Disposition algorithm (preapproved, not yet applicable)

* **Strong:** a group's named Quervant **exclusive** share is ≥ 20.0% of samples and leads the
  next named group by ≥ 5.0 percentage points → exactly one mapped next-phase scope.
* **Likely (inclusive only):** one unambiguous inclusive chain ≥ 40.0% with a clear owned
  child and no competing disjoint chain ≥ 35.0% → recommend narrower profiling first.
* **Unresolved:** anything else → `P6_PROFILE_UNRESOLVED`, recommendation
  `NO_PHASE7_OPTIMIZATION_AUTHORIZED`.

The numeric thresholds govern **recommendation confidence only**; they are not speedup or
merge gates, and no microseconds may be inferred from sample percentages.

## 6. Non-goals honored

No optimization, no cache design, no scorer/statistics/format change, no new tracing
instrumentation, no profiler or verifier patch, no expansion of the frozen corpus, no
Lucene/Tantivy rerun, no full 20-capture campaign, no merge, no Phase 7 work.

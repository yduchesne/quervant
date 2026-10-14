# PR 7 Amendment 05 preflight — persistent BM25 field norms

**Branch:** `dev/lexical-postings`
**Inspected branch baseline:** `b397eea` (Amendment 04 Correction 01); current
HEAD `7aac0c8` (adds a dev-only baseline-runner path fix)
**Base `main`:** `4f603ce1c0dafd994918bb5291d4b0584d9f001c` (unchanged)
**Working tree:** clean.

**Disposition: STOP — BLOCKED. No production code was changed.**
Two independent blockers prevent implementation under the approved plan (see §4
and §5). Per the plan's own STOP conditions ("If contention, tooling, or the
baseline runner blocks qualification, STOP before production changes"), the
correct action is to report and request reconciliation, not to improvise.

## 1. Plan integrity — the supplied plan is truncated

`/mnt/c/Users/yduchesne/Downloads/PR07_AMENDMENT_05_DETAILED_IMPLEMENTATION_PLAN.md`
is **45 lines / 5,495 bytes**. It ends mid-sentence inside §3.1, immediately after
the payload field list, with no closing brace and no further content:

```text
repeat field_count times, strictly increasing field_id:
    u32 field_id
    u64 total_token_count
    u64 documents_with_tokens
    repeat doc_count times:
        canonical unsigned LEB128 token_count_for_physical_doc
```

Missing sections that are required before a production segment-format change can
be implemented safely and without independent redesign:

- §3.2+ (reader/`SegmentReader` accessors, `compute_stats` integration, `df`
  derivation without a full scan, live-doc filtering).
- Writer/`build.rs` integration and encode ordering; section/feature wiring.
- Decoder allocation/entry/byte limits and cancellation/error semantics.
- Backward-compatibility/golden-fixture policy and format-version rules.
- Test matrix, invariant IDs, and acceptance criteria.
- Implementation sequence, required gates, and artifacts.

The plan explicitly forbids independent redesign ("implement, do not redesign").
Implementing from a truncated design would require inventing the missing contract,
which is out of scope and risky for a persisted format.

## 2. Verified architecture facts (§2 conformance)

Inspected at `b397eea`/`7aac0c8`:

- `segment::format`: `FORMAT_MAJOR=1`, `FORMAT_MINOR=0`; `SectionKind` ends at
  `SegmentMeta=0x000C`/`Manifest=0x000D`; `SUPPORTED_FEATURES` ends at
  `FEATURE_REMAP=0x0006`. The planned `FieldNorms=0x000E` / `FEATURE_FIELD_NORMS=0x0007`
  are additive and consistent with the existing scheme.
- `segment::build`: a single analysis pass already builds
  `postings_map: BTreeMap<(field_id, term), Vec<Posting>>`, so per-document token
  counts are collectable without a second traversal.
- `search::score::compute_stats` currently iterates every dictionary term and every
  posting for each scoring field/segment — the documented dominant defect.
- Golden segment fixtures and committed indexes exist; backward readability is
  mandatory.
- Amendment 04 Correction 01 tooling is present (Criterion targets, oracle, v2
  validator, contention detector, three-trial aggregator).

## 3. Dev-only baseline-runner defect found and fixed

While attempting the mandatory gate, the Correction 01 runner wrote Criterion
output under a relative `CRITERION_HOME`. Cargo runs bench binaries with cwd = the
package directory, so results landed in
`crates/quervant-core/target/pr07-baseline/.../criterion` and the report builder
(run from the repo root) reported all 34 estimates missing. Fixed in `7aac0c8`
(absolute `OUT_ABS`/`CRITERION_HOME`); no production or format change.

## 4. Mandatory qualified-baseline gate — BLOCKED by contention

The plan requires, before any production change, a clean-tree
`run-pr07-baseline.sh --idle-confirmed --trials 3` whose three trial reports and
qualified state all validate. Attempts:

| Attempt | Commit | Result |
|---|---|---|
| 1 | `b397eea` | Trial 1 benchmarks ran; builder failed on the relative-`CRITERION_HOME` bug (fixed) |
| 2 | `7aac0c8` | Pre-check `suspected`; runner exited **3** before any Criterion work |
| Isolation samples | `7aac0c8` | 4/4 `clear`, then intermittent `suspected` (`other`/`java`, ≥0.5 core) |

Representative blocked pre-check:

```json
{"state":"suspected","reason_codes":["unrelated_cpu_consumer"],
 "process_class_counts":{"other":1},"competing_process_count":1,
 "cpu_busy_fraction":0.104}
```

The detector is non-destructive and sanitized; the runner fails closed (exit 3)
unless `--allow-contended` is passed, which yields only a **diagnostic** run and is
not permitted to satisfy the gate. The competing consumer could not be identified
or stopped by the agent (no termination, no privilege escalation). Contention is
intermittent, so a three-trial all-clear qualification is not reliably obtainable
in this environment.

**No qualified baseline JSON/Markdown was produced. No historical or diagnostic
measurement was substituted.**

## 5. Risk matrix (for when the plan is complete)

| Risk | Mitigation already specified/expected |
|---|---|
| Format compatibility with existing segments | Optional section + optional feature; decoder must tolerate absence |
| Norm payload corruption | Validated decode with checked allocation/entry/byte bounds |
| `df` for query terms still O(all postings) | Derive from query-term postings only; live filtering via bitmaps |
| Divergence between norms and true frequencies | Encode from the same analysis pass; cross-check in tests |
| Live/deleted docs | Use live bitmaps; PR 9 owns tombstones/merges |
| Regression of Amendment 04 v2 evidence | Re-run qualified baseline after implementation; ratios, not absolutes |

## 6. Invariant-to-test map (partial — rest of plan absent)

| Invariant (from available text) | Test (to be defined by the complete plan) |
|---|---|
| Query prep does not enumerate unrelated terms | Postings-scanned counter bound; rare-term query touches only its postings |
| Norms reproduce exact PR 7 BM25 | Differential vs Amendment 04 oracle on golden corpus |
| Existing segments remain readable | Golden fixture without `FieldNorms` decodes and searches |
| New segments self-describe | Feature/section round-trip test |
| Bounded decode | Allocation/entry/byte limit tests, corrupt payloads |
| No regression | Full stable/MSRV suites + qualified post-optimization baseline |

## 7. Pre-implementation adversarial review

- A norms section could silently diverge from postings if built in a different
  pass; the plan's "same analysis pass" must be enforced and tested with derived
  tokens/stemming/multi-values.
- `avgdl` and `df` semantics must remain live-doc-aware; a naive norms-only `n`
  would break once PR 9 adds tombstones.
- Backward compatibility must not be asserted without a golden
  no-norms fixture round-trip.
- The qualified-baseline requirement is a hard gate; an unqualified before/after
  comparison must not be reported as a speedup.

## 8. Requested decisions

1. Provide the **complete** Amendment 05 plan (all sections through
   implementation sequence, tests, and acceptance criteria), or authorize a
   narrower, fully specified change.
2. Provide a **contention-free** WSL2 guest (stop the competing `other`/`java`
   workload) and explicit operator confirmation so the three-trial qualified
   baseline gate can run, or explicitly authorize deferring the qualified baseline
   with a documented risk.

# PR 15B preflight — freshness, feasibility and adversarial scope check

**Result state:** IMPLEMENTED / QUALIFIED / AWAITING INDEPENDENT REVIEW. This
document records preflight evidence; it is not maintainer acceptance.

## Source base

| Item | Value |
|---|---|
| Repository | `yduchesne/quervant` |
| Verified `main` at planning | `e3e989e0bf3736a8a2d6f2493b240209e008b2be` (PR 15A/#72 merged) |
| Working branch | `dev/pr15b-unified-search-diags` at `e3e989e0` |
| Planning-prescribed branch name | `test/pr15b-unified-diagnostics` |
| Tree at preflight | clean (`git status --porcelain` empty) |

**Branch-name deviation (X12-adjacent, no functional effect).** The authorized
starting commit is exact. An existing local branch name that already pointed at
`e3e989e0` was reused instead of creating the illustrative name in the plan.
No `main` commit, force-push or tag was made.

## Environment

| Item | Value |
|---|---|
| OS | Linux `6.18.33.2-microsoft-standard-WSL2` (WSL2) |
| Filesystem for repository | `ext4` (native Linux filesystem) |
| CPUs | 12 logical |
| Memory | 32,774,780 kB |
| Stable toolchain | `rustc 1.98.1` / `cargo 1.98.1` |
| MSRV toolchain installed | `1.85.0` |
| `perf` | UNAVAILABLE |
| `cargo-flamegraph` | UNAVAILABLE |
| `heaptrack` | UNAVAILABLE |
| `python3` | available |
| `cargo-llvm-cov` | available |

## Baseline verification on the starting commit (before implementation)

| Command | Result |
|---|---|
| `cargo +stable test -p quervant-core --test pr15a_regression --test pr15a_compatibility` | PASS: 14 + 3 tests |
| `cargo +stable bench -p quervant-core --no-run` | PASS: all nine pre-existing targets compiled |
| `cargo +stable llvm-cov --workspace --all-targets --fail-under-lines 85` | PASS: 92.17% lines, 92.56% regions, 88.09% functions |

The canonical fixture digest was verified with `sha256sum`:
`104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087`.

## Source-verified interface check

- `UnifiedSearcher::new/search`, `UnifiedRequest`, `UnifiedResponse`,
  `ProjectedHit`, `UnifiedCursor` exist and are public.
- `execute_batch_pinned`, `PitHandle`, `BatchQueryRequest`, `QueryRequest`,
  `PerQueryOutcome` and `SearchResponse` exist and are public.
- `Projection` has exactly the approved `Source` and `Fields(Vec<String>)`
  variants. There is **no** `Projection::None`.
- `Query::TimeRange` is implemented as a **half-open** interval
  `[start, end)`; the approved contract already has regression witnesses for
  this behaviour.
- `Query::Term` is rejected for non-lexical fields with
  `term_on_non_lexical_field`. The plan's typed `n == 0` identity is therefore
  expressed with the existing typed `Query::In { field: "n", values: [0] }`.
- `Aggregation` supports per-group `ExactDistinct` metrics, but the global
  exact-distinct host count is exactly the group cardinality of the grouped
  response. U09 reports both separately: group cardinality and per-group
  count/sum.
- The existing `IndexLimits` object provides documented fixture-only builders
  for pending document/byte, segment-per-commit, manifest and snapshot bounds.

No material API change blocks the plan. The following discrepancies are recorded
and resolved without changing production semantics:

1. `Projection::None` is not representable. U08 runs `Source` and
   `Fields(host,n)`; the `None` variant is `NOT RUN`.
2. U05's prose says "inclusive time range"; the approved production contract is
   half-open. U05 preserves the production contract and the oracle uses
   `[start, end)`.
3. U09's "global exact-distinct host" is validated as the group cardinality
   (`host` has cardinality 3), reported separately from per-group metrics
   (X49).
4. The plan's illustrative branch name differs from the reused branch; the exact
   starting commit is unchanged.

## Adversarial state check before implementation

Every workload was checked for valid, empty, boundary, one-hit, many-hit,
error/typed-rejection and cancellation states:

| Workload | Valid | Empty/boundary | Typed rejection / isolation |
|---|---|---|---|
| U01 absent | empty set, total 0 | no match is success, not error | invalid field still typed error |
| U02 rare | exactly one hit | `n != 0` empty | `Term` on typed field rejected → use `In` |
| U03 medium | `3N/8` exact total | truncated top-K still exact total | invalid term field typed error |
| U04 mixed | `N/4` exact total | empty below `N/2` window | type mismatch typed error |
| U05 CIDR+time | exact ordered set | `/0` differs from `/24`; IPv6 excluded | mixed family not coerced |
| U06 JSON | `N/4` exact | absent/null/empty distinguished | malformed path typed error |
| U07 sort | exact prefix, total `N` | `K > N` prefix is `N` | invalid sort field typed error |
| U08 projection | exact states | empty `Fields` produces zero fields | indexed-not-stored typed error |
| U09 group | exact count/sum | zero-match → no groups | unsupported group field typed error |
| U10 batch | 3 ordered successes | invalid middle slot isolated | siblings preserved |
| U11 segments | identical results | `S=1/4/16` | physical count mismatch aborts |
| U12 pages | concatenation exact | no duplicate/omission | wrong PIT/expired deadline typed |
| U13 geo | exact bbox set | outside bbox empty | real geo query, separate corpus |

## Invariant traceability

| Invariant | Evidence |
|---|---|
| I01 frozen provenance | B-T01, canonical digest in every bench run and validator |
| I02 independent oracle | U01–U13 oracle formulas; no production evaluator used to derive truth |
| I03 physical snapshots | B-T03/B-T10 exact segment/document counts; bench aborts on mismatch |
| I04 no measured setup | fixture/oracle/metadata/cursor work precedes every `b.iter` |
| I05 no default semantic change | no production semantics changed; PR15A suites re-run; B-T12 test-only counters |
| I06 qualified source-identical trials | `run-pr15b.sh` + strict validator + aggregate |
| I07 correct profile/run mode | `cargo bench` release profile + release profiling example |
| I08 no fabricated counters | measured response-level counters; all others `NOT INSTRUMENTED` |
| I09 no fabricated profiler | UNAVAILABLE attempts recorded with exact exit status |
| I10 honest cross-run comparison | dispersion reported, no p99/SLA relabel |
| I11 no unauthorized optimization | diff audit: no search algorithm/budget/format change |

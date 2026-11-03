# PR 15E Phase 6F — G05 narrow attribution: design and decisions

**Status: `P6F_ATTRIBUTED_REVIEW_READY` — candidate `C06_NO_SAFE_LOCAL_CHANGE`.
`implementation_authorized: false`.** Investigation only: no production Rust, benchmark, profiler,
format or API change, no new capture, no Phase 7 work.

## 1. Question

Phase 6 measured 82.39 % **inclusive** process-wide CPU on the rare 100K/K100 lane inside
`execute_unified → project_selected_hits → SegmentReader::stored_docs_selected →
decode_stored_selected → skip_field_values_budgeted → skip_scalar_budgeted`, with a
`LIKELY, INCLUSIVE_ONLY` disposition. P6F had to determine the **exclusive** composition of that
chain and whether any part is safely removable.

## 2. Method (read-only)

Existing Phase 6 raw evidence only: the original `capture.json`, `perf-self.txt`,
`perf-calltree.txt` and the recorded `perf.data`, bound to source
`e448469d6c98d9ef4b4a827ad9567363a888a185` by SHA-256. Two independent readings were used:

1. the hashed **text reports** from Phase 6 (exclusive self table and inclusive call tree);
2. an **offline per-sample call-chain re-reading** of the same `perf.data` with the same
   installed `perf 6.8.12` binary (`script` mode only — no capture, no queries, no profiler
   session), giving each sample an exact leaf symbol and its full caller chain.

The per-sample reading resolves what the text caller tree could not: the text tree's
caller branches overlap (their percentages are not an arithmetic partition), so shared frames
(`from_utf8`, `ByteReader::*`, `DecodeBudget::*`, `drop_glue`) could not be split from the text
alone without inventing numbers. The per-sample chains remove that ambiguity: a sample is
classified by its **leaf** (what work) and its **innermost named subsystem** in the chain
(whose work), with runtime/helper frames treated as transparent.

## 3. Attribution rules applied (preapproved V/U taxonomy)

| Bucket | What it contains | Rankable |
|---|---|---|
| `V01_UTF8_STORED_UNSELECTED` | `from_utf8` / `run_utf8_validation` leaves inside a G05 chain (unselected text/keyword/JSON strings and stored keys) | yes |
| `V02_SKIP_FIELD_SCALAR` | `skip_field_values_budgeted` / `skip_scalar_budgeted` self | yes |
| `V03_FRAMING_BYTE_READER` | `decode_stored_selected` record loop, presence bitmap, field-id order, `ByteReader` take/u16/u32/bytes/len_prefixed_u16 | yes |
| `V04_MODELED_BUDGET` | `DecodeBudget` reserve_bytes/reserve_string/reserve_btree_entry/reserve_vec | yes |
| `V05_SELECTED_MATERIALIZATION` | materialization/projection of the selected record | yes |
| `V06_JSON_VALIDATION` | `skip_json_budgeted` (absent in this corpus) | yes |
| `V07_G05_DROP_GLUE` | generic `drop_glue` while a G05 chain is active | **no** (rule) |
| `V08_OTHER_G05` | inlined G05 helper code without a named category (bounds checks, `Option`/`Result` plumbing, checked/saturating arithmetic) | **no** (rule) |

Frames outside G05 are reported as separate contexts (`G04` keys, `G03` columns, `G01`
staging/verification, `G06` scoring, `G02` statistics, adapter runtime, unsymbolized) and never
counted as G05. Inclusive shares are never summed with exclusive ones, and nested inclusive
chains are never added together.

## 4. Result and decision

Rare lane, exact per-sample population 121,296 cycles samples (the recorded 121,000 is perf's
shortened `121K` display; the two are never mixed in one figure):

| Bucket | Samples | Share |
|---|---:|---:|
| `V03_FRAMING_BYTE_READER` | 22,685 | 18.70 % |
| `V01_UTF8_STORED_UNSELECTED` | 19,579 | 16.14 % |
| `V07_G05_DROP_GLUE` (not rankable) | 20,967 | 17.29 % |
| `V08_OTHER_G05` (not rankable) | 12,853 | 10.60 % |
| `V04_MODELED_BUDGET` | 11,689 | 9.64 % |
| `V02_SKIP_FIELD_SCALAR` | 11,536 | 9.51 % |
| `V05_SELECTED_MATERIALIZATION` | 2 | 0.00 % |
| `V06_JSON_VALIDATION` | 0 | 0.00 % |

Cross-check: per-sample G05 = 81.87 % of samples, consistent with the Phase 6 inclusive chain
maximum of 82.39 %. The independently derived G05 dominance is therefore confirmed; only its
internal composition is new information.

**Ranking (preapproved):** an eligible bucket must reach 10.0 % exclusive **and** lead the next
eligible bucket by 5.0 pp. The leader is framing at 18.70 %; the runner-up is UTF-8 validation at
16.14 % — a lead of **2.56 pp**, below the rule. `V07`/`V08` are excluded by rule.

**Decision: `C06_NO_SAFE_LOCAL_CHANGE`.** The G05 cost is spread across mandatory per-record
validation categories with no dominant, safely-removable component, and no source-proven
redundant work. The selected-record bucket is effectively zero, confirming that Phase 3
selectivity already works; what remains is the cost of validating records that are **not**
materialized — which the accepted contract requires.

## 5. Why no local optimization is proposed

Source audit of each bucket (`phase6f-qualification.md` §3) shows every one is required:

* UTF-8 validation of unselected strings and keys is part of typed-error parity with the
  accepted decoder; skipping it would accept corrupt segments.
* Framing (presence bitmap, field-id order, `ByteReader` bounds) is the corruption-detection
  contract, including `expect_end` after the last selected record.
* Modeled `DecodeBudget` admission must keep its exact per-field order and first-failure
  semantics (retained-budget equivalence), so batching or eliding is not a local change.
* Field-state/scalar dispatch is how the cursor advances correctly through unselected values.
* The inlined helpers are bounds/overflow checks, not overhead that can be removed.

Removing or weakening any of these is explicitly not authorized, and no alternative
identification of redundant work is possible from the evidence.

## 6. Options left to the maintainer (not authorized here)

1. a new **verified immutable validation/offset architecture** (pre-validated sections or a
   persisted validation provenance) — a format/architecture decision requiring its own plan;
2. investigate the **unselected** G03 signal: the absent lane is 60.30 % column setup
   (`ColumnAccess::open` → `ColumnReader::open` → `read_u64_at`), the largest single
   subsystem share observed anywhere in these four lanes;
3. stop optimization work on PR 15E and move to final integration qualification.

The coding agent does not choose among these and implements none of them.

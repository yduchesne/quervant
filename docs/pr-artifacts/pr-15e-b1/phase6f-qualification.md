# PR 15E Phase 6F — G05 narrow attribution: qualification

**Status: `P6F_ATTRIBUTED_REVIEW_READY`** — evidence valid, subpath attribution bounded,
remaining unknowns disclosed. Candidate **`C06_NO_SAFE_LOCAL_CHANGE`**,
`implementation_authorized: false`. This is not `PR15E_MERGE_READY`; CI, G11 and PR-level gates
are unchanged.

## 1. Evidence integrity

| Item | Value |
|---|---|
| Measured source | `e448469d6c98d9ef4b4a827ad9567363a888a185` |
| Evidence head | `395d8d8c06f8569348e00fe3264259203ab080f3` |
| Primary capture | `pr15e/n100000/rare/k100/perf`, warm, oracle-exact, contention `clear`/`clear` |
| Recorded sample count | 121,000 (perf's `121K` display) |
| Parsed cycles population | **121,296** samples (single denominator for every share below) |
| Lost samples | 0 |
| Original verifier | `PARTIAL`, exit 3, 4 passed / 16 absent / 0 failed |
| Artifact digests | `capture.json` `823b4c3b…`, `perf-self.txt` `dccbcef3…`, `perf-calltree.txt` `c46b2fb1…`, plus all six manifest artifacts verified |
| New captures in P6F | **0** |

## 2. G05 composition (exclusive, per sample)

Inclusive context: the Phase 6 G05 chain maximum remains **82.39 %** (reported separately and
never summed with the buckets below). The independent per-sample reading measures G05 at
**81.87 %**, which cross-validates the Phase 6 attribution.

| Bucket | Samples | Share | Rankable |
|---|---:|---:|---|
| `V03_FRAMING_BYTE_READER` | 22,685 | **18.70 %** | yes |
| `V01_UTF8_STORED_UNSELECTED` | 19,579 | **16.14 %** | yes |
| `V07_G05_DROP_GLUE` | 20,967 | 17.29 % | no (rule) |
| `V08_OTHER_G05` | 12,853 | 10.60 % | no (rule) |
| `V04_MODELED_BUDGET` | 11,689 | 9.64 % | yes |
| `V02_SKIP_FIELD_SCALAR` | 11,536 | 9.51 % | yes |
| `V05_SELECTED_MATERIALIZATION` | 2 | 0.00 % | yes |
| `V06_JSON_VALIDATION` | 0 | 0.00 % | yes |

Outside G05 (contexts, excluded from G05): `G04` keys 10.87 %, `G03` columns 3.17 %, `G01`
staging/verification 2.54 %, `G06` scoring 1.05 %, adapter 0.29 %, `G02` 0.19 %, unsymbolized
0.01 %.

**Ranking verdict:** the eligible leader (framing, 18.70 %) leads the runner-up (UTF-8, 16.14 %)
by **2.56 pp**, below the required 5.0 pp, so no bucket qualifies → `C06_NO_SAFE_LOCAL_CHANGE`.

## 3. Source contract per bucket (why it is not removable locally)

| Bucket | Code path | Contract it preserves |
|---|---|---|
| `V01` | `skip_scalar_budgeted` → `str::from_utf8` for Text/Keyword/JSON strings; `decode_stored_selected` key validation | Typed `InvalidUtf8` parity with the accepted decoder; corrupt segments must be rejected |
| `V02` | `skip_field_values_budgeted` / `skip_scalar_budgeted` state and type dispatch | Cursor advances exactly over the encoded value; unknown states rejected |
| `V03` | `decode_stored_selected` record loop, presence bitmap, field-id order; `ByteReader::{take,u16,u32,bytes,varint,len_prefixed_u16}`, `expect_end` | Bounds checking, structural corruption detection, trailing-data rejection after the last selected record |
| `V04` | `DecodeBudget::{reserve_string,reserve_btree_entry,reserve_bytes,reserve_vec}` | Per-field admission order and first-failure semantics; retained-budget equivalence with the full decoder |
| `V05` | selected record insertion / projection | Only one record is materialized (2 samples), so Phase 3 selectivity is already effective |
| `V07` | `core::ptr::drop_glue` in a G05 chain | Runtime destruction, not a Quervant subsystem cost; never rankable |
| `V08` | inlined bounds/overflow helpers, `Option`/`Result` plumbing | `SegmentLimits` checks and checked arithmetic are correctness checks |

No bucket contains source-proven redundant work. Removing or reordering any of them would change
corruption, error-precedence or budget semantics, which is explicitly not authorized.

## 4. Control lanes (same per-sample method)

| Lane | Dominant subsystem shares |
|---|---|
| `absent` | `G03` columns **60.30 %**, `G06` 19.82 %, `G01` 12.93 %, `G02` 3.95 %, adapter 2.95 %, `G05` ≈ 0.02 % |
| `medium` | `G05` 52.56 %, adapter 15.41 %, `G04` legacy full-key decode 14.42 %, `G06` 11.41 % |
| `common` | `G05` 33.95 %, `G06` 25.77 %, adapter 24.94 %, `G04` 8.49 %, `G03` 5.30 % |

The `absent` lane has no stored projection at all and is dominated by per-query column setup —
the largest single subsystem share observed in these four lanes, and the strongest **unselected**
signal for a future investigation.

## 5. Unknowns and limits

* No `U01`/`U02` residual to speak of (7 samples, 0.01 %), so the exclusive attribution is
  complete for this lane; the ambiguity is in *ownership meaning*, not in missing samples.
* Inclusive and exclusive trees are never combined; the 82.39 % is context only.
* Process-wide CPU samples include startup, five warmups and JSONL transport; they are not
  elapsed time and cannot be converted to microseconds or savings.
* One host, one session, synthetic frozen exact-term corpus; `absent`/`medium`/`common` shares are
  descriptive controls, not a new campaign.
* No allocation evidence (no heaptrack), no cross-host, remote-latency or concurrent-writer
  evidence; no Rust test, coverage or RustFS run was executed for P6F (none is applicable to a
  read-only investigation).
* The legacy PR 15E-A campaign remains `PARTIAL` 4/20 and is not re-claimed.

## 6. Acceptance distinction

P6F acceptance means: raw evidence bound and verified, exclusive composition measured with a
sound per-sample method, source contracts checked, sanitized publication, and one bounded
candidate (or unresolved) with `implementation_authorized: false`. It is **not** an optimization
acceptance, not a Phase 7 authorization, and not a merge approval.

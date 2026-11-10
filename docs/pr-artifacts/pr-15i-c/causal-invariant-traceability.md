# PR 15I-C causal experiment — invariant traceability

Written before measurement. Each invariant names its positive proof and the
counterexample that must fail closed.

| ID | Positive proof | Counterexample |
|---|---|---|
| CA-I01 | `BASE_A` production tree untouched (`git diff --quiet`) | any main production drift → `CA-D03` HARD STOP |
| CA-I02 | B/C share one absolute executable path and SHA-256, re-hashed before/after (`CV_BINARY`, `verify_slots` path equality, `CM-U36`) | different path with equal bytes → `CV_BINARY` (CV-17) |
| CA-I03 | `child_environment()` sets exactly one allowlisted variable per arm; every lane/slot launches a fresh process (`CausalAdapterProcess`) | missing/invalid mode → typed error (CM-U03/04) |
| CA-I04 | mode `disabled` → generic path (CM-U02, differential parity) | specialized invocation in disabled mode → `CA-D29` STOP |
| CA-I05 | mode `enabled` → specialized path for the nine frozen lanes (CM-U01, `n_u` differential suite) | eligible query routed generic → BLOCK |
| CA-I06 | gate is `#[cfg(feature = "pr15ic-causal")]`, feature non-default (CM-U34/35) | gate reachable in default release → `CA-D24` STOP |
| CA-I07 | `collect_mixed` body SHA `00c5a1c8…` and attributes identical (`CM-U33`, `causal_source_proof`) | `#[inline(never)]` on generic or body drift → `CA-D12` STOP |
| CA-I08 | 12 rebuilds per campaign, A/BC layout and segment-digest equality (`verify_index_layouts`) | mismatch → `CV_FORMAT` (CV-33/34/36) |
| CA-I09 | STORED v2 + feature `[13,1]` + 100K sentinel 15 747 551 / 1 661 455 | format/sentinel drift → `CV_FORMAT` (CV-35) |
| CA-I10 | frozen PR15D oracle keys/counts on every warmup and sample; A/B/C `f64::to_bits` parity via the score probe | any discrepancy → `CV_ORACLE`/`CV_SCORE` (CV-29/30) |
| CA-I11 | unbatched slots hold 20 individual `engine_ns` observations | batch sample in an unbatched slot → `CV_UNIT` (CV-21) |
| CA-I12 | batched slots hold 10 `batch_ns` observations with 100/1 repeats, never divided into pseudo-samples | `batch_ns/100` mislabeled as a sample → `CV_UNIT` (CV-22) |
| CA-I13 | protocol SHA pinned in every manifest and receipt before sampling | mid-series change → invalidate the attempt (`CA-D18`) |
| CA-I14 | verifier has its own nearest-rank median, ratio arithmetic and §9 classifier (no controller import) | controller/verifier disagreement → `CV_RATIO` (CV-38) |
| CA-I15 | restored candidate suites (16+12+6+2 unit, 12 integration) executed against the gated source | error-precedence change → `CA-D67` STOP |
| CA-I16 | host fingerprint, affinity mode, rustc and filesystem recorded and stable across the four campaigns | contended slot → `CV_CONTENTION` (CV-37) |
| CA-I17 | exact raw inventory + seal rehashed before/after (`verify_inventory_and_seal`) | missing/extra/symlink/tamper → `CV_INVENTORY`/`CV_PATH`/`CV_SEAL`/`CV_TAMPER` (CV-05..12) |
| CA-I18 | temporary production files restored to `BASE_A` before the final commit | residual delta → `CA-D87` STOP |
| CA-I19 | every claimed test executed with recorded exit statuses (no `--no-run` claims) | compiled-only claim → STOP |
| CA-I20 | real RustFS only if actually reachable; otherwise `REAL_RUSTFS_BLOCKED` | fake store / ignored test counted → not accepted |

## Schedule and counting invariants (verified by both controller and verifier)

* Four blocks `ABCCBA / BCAACB / CABBAC / ACBBCA`, each arm twice per block.
* 24 slots × 9 lanes = 216 lane/slot records and 1 080 validated warmups per campaign.
* Unbatched: 4 320 measured `engine_ns` samples; batched: 2 160 `batch_ns`
  observations = 97 200 searches.
* A/A within-block drift sentinel per lane from the two A slots of each block,
  median of four ratios, gate `[0.85, 1.15]`.

## Why the tempting shortcuts are excluded

1. **B/C vs C/A conflation** — B/C isolates the specialized path inside one
   layout; C/A includes gate, dispatch and code-layout effects. They are reported
   separately and never merged into one number.
2. **Batched as acceptance** — batched data is `BATCH_OBSERVATION_ONLY`; it can
   never override the unbatched §9 verdict or the frozen `C-P06..C-P09` gates.
3. **Per-query average as a sample** — `batch_ns / 100` is descriptive only; the
   verifier rejects mixed units and forged derived values.
4. **`statistics.median`** — would average the central pair of a 20-sample list;
   the protocol requires the frozen PR15D nearest-rank element (10th of 20).
5. **Environment mutation** — the controller never touches `os.environ`; each
   child gets its own map, so `OnceLock` cannot leak a mode across arms.
6. **Reused process across arms** — rejected by construction (a fresh process per
   lane/slot) and by the recorded per-lane `binary_path`/mode.
7. **Retro-fitting the classification** — the §9 table and its thresholds are in
   the committed protocol; the aggregate verifier applies them mechanically and
   reports `CAUSAL_INCONCLUSIVE` when lanes disagree.

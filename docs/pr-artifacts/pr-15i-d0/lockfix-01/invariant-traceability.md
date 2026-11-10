# PR 15I-D0 lockfix-01 — invariant traceability

Every row cites executed positive and negative evidence. “Pre-campaign” tooling
was frozen at `526a154`; measurements use that exact tooling.

## 1. Invariants

| ID | Positive evidence | Negative counterexample evidence | Status |
|---|---|---|---|
| F-I01 Lock-only compatibility | `COMPAT_BASE` `a53ee021…` changes exactly `benchmarks/pr15d/adapters/quervant/Cargo.lock`; structured proof adds only `lz4_flex`/`twox-hash` and the one edge; root lock unchanged | broad `generate-lockfile` probe (unrelated bumps) was discarded and preserved; `git diff --name-only` shows one path | PASS |
| F-I02 Locked reproducibility | two `cargo build --release --locked` runs PASS; lock SHA `19953cab…` unchanged after both; `cargo metadata --locked` PASS | omitting the packages fails the historical `--locked` build (preserved historical log) | PASS |
| F-I03 Historical isolation | `historical-freeze.json` pins old run hashes; old D0 branch/report bytes untouched | fixup uses new `lockfix-01` directories and a new branch; old `15ID0_BLOCKED` reports remain in place | PASS |
| F-I04 Unique new source identity | protocol `pr15i-d0-attribution-lockfix-v1`, `base_sha = COMPAT_BASE`, historical and parent fields; all artifacts declare it | `test_run` old-protocol / mixed-base rejection; `test_verify` old/mixed rejection; `test_source_proof` historical-is-provenance | PASS |
| F-I05 Source purity | real materialization `VERIFIED`; reverse deletion restores `COMPAT_BASE` bytes | one-token import tamper, moved import, third import, one-byte non-instrumented change, extra `#[inline]`, changed default feature, seventh path all rejected | PASS |
| F-I06 Import confinement | exactly two `use super::d0_probe;` at offsets 1565/1398; scratch build compiles | missing/duplicated/moved import and any extra change rejected by the byte proof | PASS |
| F-I07 Q/P equivalence | one QP binary `aab694cd…`; A is `db27f3bf…`; slice and campaigns record the same QP digest for Q and P | `test_verify` identical-A/QP, slot-digest mismatch, and probe-field mode tests reject | PASS |
| F-I08 Logical oracle | real slice 12/12 cases and both 24-slot campaigns match the independent PR15D oracle, including absent zero-hit and rare singleton | wrong `doc_ids`, wrong count, reordered lanes and missing probe-field tests reject | PASS |
| F-I09 Sample integrity | 4,320 timed + 1,080 warmups per campaign; 48 probes; 4 builds; 1,440 P samples; all seals rehashed; per-sample exclusive partition exact | 19 samples, bool/zero/string samples, wrong warmups, duplicate/missing slot, missing probe, extra file, torn seal, path traversal all reject | PASS |
| F-I10 Scientific neutrality | lanes, schedule, 5+20 sampling, 10 stage labels, 3 counters, thresholds and ranking logic are the original effective values; only identity fields changed | exact-protocol literal tests and immutable schedule tests fail on any threshold/lane/sample change | PASS |
| F-I11 Canonical comparability | see `canonical-three-engine.md` | validator refuses aggregation on an invalid/incomplete run | see canonical report |
| F-I12 Status from evidence | this report distinguishes implementation, tests, correctness, paired attribution, canonical, CI and review | unit-only tests are not called qualified measurements | PASS |

## 2. New and extended tests

- `test_run`: old-protocol rejection, mixed-base rejection, compatibility
  provenance, slice case set, source-arm mapping, absent recorder inventory.
- `test_verify`: old/mixed protocol rejection, real slice shape, slice wrong
  `doc_ids`, slice missing seal.
- `test_source_proof`: historical base is provenance only; one-token import
  tamper; third import; moved import; one-byte non-instrumented change.
- All previously existing D0 parser, seal, oracle, ratio, stability, intrusion,
  stage-partition, ranking, path and affinity tests remain.

Final D0 test count and repository QA results are recorded in `qa.md`.

## 3. Adversarial self-review (most plausible remaining counterexample)

| Invariant | Most plausible remaining counterexample | Rejecting evidence |
|---|---|---|
| F-I01 | a future lock refresh silently bumps an unrelated crate | the committed lock diff has 16 added lines and zero version/checksum changes; `lock-diff-proof.json` is regenerated from TOML in the verification script |
| F-I02 | a build mutates the lock after acceptance | lock SHA re-checked after each of two `--locked` builds; unchanged |
| F-I03 | a new report overwrites the historical blocked report | new reports live under `lockfix-01/`; historical files are unchanged in Git and their local hashes are frozen |
| F-I04 | old protocol accepted alongside new | strict dict equality in both `run.validate_protocol` and `verify.validate_protocol`; old/mixed tests |
| F-I05 | an edit lands in an inserted line and survives byte comparison | the independent proof rebuilds from BASE; any altered inserted byte fails byte equality; a BASE-byte change becomes a non-insertion diff |
| F-I06 | a third import is added elsewhere in the file | full-file byte equality against the independently rebuilt derivative |
| F-I07 | Q and P built separately | campaign uses one QP path; `verify_slot_binaries` compares every Q/P slot to the recorded QP digest |
| F-I08 | an oracle bug in both controller and verifier | verifier recomputes from the frozen PR15D corpus generator, not from controller output |
| F-I09 | a truncated slot passes because the aggregate is recomputed | seal requires all 24 slots/48 probes; sample count, type and partition are rechecked per sample |
| F-I10 | a threshold was relaxed to pass | the protocol and all gates are strict literals; only identity fields differ from the historical tooling |
| F-I11 | a partial three-engine run is presented as current | validator `INVALID`/blocked classification is reported; no ratio is published without `QUALIFIED` |
| F-I12 | a unit test is presented as measurement evidence | status table separates implementation, tests, paired measurement, canonical, CI and review |

## 4. Residual risks

1. P stage shares are instrumented diagnostic values; `H-CANDIDATE` dominance is
   a hypothesis, not a proven removable percentage.
2. `H-OTHER` is an observed residual; the ranking does not authorize attributing
   it to allocator, compiler or I/O behavior.
3. The two scratch imports are a plan-authorized compile-path addition; reviewers
   must confirm the exact two lines.
4. Canonical comparability remains logically (not physically) equivalent; the
   scoring/sort caveat is repeated next to any ratio.

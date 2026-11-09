# PR 15I-C-F — invariant traceability

Diagnostic only. The F experiment must preserve every v0.1 semantic contract
while changing exactly one code-generation decision (inlining of
`UnifiedSearcher::collect_mixed`). Each row names the invariant, where it lives,
and the test or artifact that proves it still holds at `F_DIAG`.

## 1. Production invariants

| # | Invariant | Where enforced | Proof at F_DIAG |
| --- | --- | --- | --- |
| I1 | Request, cursor and plan validation are unchanged | `execute.rs` (verbatim from `CAUSAL_PARENT`) | `git diff C..Fd -- crates/` = only `unified.rs`; source proof `FS_SCOPE` |
| I2 | Eligible exact-term requests still dispatch to `collect_exact_term_physical` | `unified.rs` eligibility branch | `c15i_observation::eligible_invocations()` = 1 (`n_u39`); physical body hash `522f6600…` in all arms |
| I3 | Generic path semantics are identical to baseline: same documents, same order, same bits | `collect_mixed` body | body SHA-256 `00c5a1c8…` (A = C = F); `n_u34` structural test; differential tests compare `doc_id` and score bits between physical and forced-generic paths |
| I4 | Only one generic definition exists and it carries exactly one out-of-line attribute | `unified.rs` | `n_u34_generic_collector_is_structurally_untouched` asserts one `#[inline(never)]`, one inline attribute, one definition |
| I5 | Scoring, BM25, pagination, sorting, cursors and totals are untouched | `score.rs`, `work.rs` | seven historical files verbatim except the attribute; score probe refuses any score-bit divergence between A/C/G/P |
| I6 | Segment format, codec and features are untouched | `segment/**` (byte-identical to `BASE_A`) | `PROTECTED_IDENTICAL` preflight; three fresh builds per arm per `n` produce identical layout and digest; feature pair `[13, 1]`; 100K sentinel 15 747 551 committed / 1 661 455 stored |
| I7 | The diagnostic gate cannot affect default builds | `Cargo.toml` feature + runtime variable | feature is non-default; wrong/missing mode is a typed adapter error (`mode-proof.json`); release variant removes feature and variable entirely |
| I8 | A commit is recoverable from ObjectStore alone; no partial publication | unchanged storage path | no storage code touched; campaign re-verifies after restart from a cold process |
| I9 | No custom cryptography or new dependency is introduced | dependency set | `Cargo.lock` protected and byte-identical to `BASE_A` |
| I10 | Telemetry remains structural, not per-posting | `tracing` usage unchanged | no new spans/events added by the experiment |

## 2. Measurement invariants

| # | Invariant | Proof |
| --- | --- | --- |
| M1 | One adapter process per slot, pinned adapter CPU 0, controller CPU 1 | `authorization.cpu_affinity`, per-slot contention probes before/after |
| M2 | Five warmups per lane per slot are excluded from samples | verifier requires exactly 5 warmup ids and 20 samples (unbatched) / 10 batches |
| M3 | Unbatched and batched units never mix | unbatched replies must not carry `batch_ns`; batched replies must not carry `engine_ns`; unit fields recorded per lane |
| M4 | Batch repeats are fixed (100 for absent/rare, 1 otherwise) | verifier re-derives the expected repeat per lane |
| M5 | Arms alternate inside a balanced block; no run is dropped or retried | fixed schedule `ACGP PGCA GCPA CPAG` per campaign, 32 slots, checked slot-by-slot |
| M6 | A/A drift bounds the noise floor | per-lane median of four within-block A/A ratios in `[0.85, 1.15]`, at most one block outside `[0.80, 1.25]` |
| M7 | Statistics are recomputed independently | verifier implements its own nearest-rank median, mean-of-two-slot-medians, median-of-four-block-ratios and classifier |
| M8 | Evidence is immutable | exclusive-create raw files, sealed SHA-256 inventory, receipts written only when absent |
| M9 | A, C and F binaries are distinct; G and P share one binary | `binaries.json` + verifier `BINARY` rules |
| M10 | Only the environment value varies between G and P | `mode-proof.json` truth table plus one shared binary path and digest |

## 3. Decision invariants

| # | Invariant | Proof |
| --- | --- | --- |
| D1 | No threshold is relaxed after measurement | frozen `f_final_protocol_v1.json` SHA-256 `5ca968c2…`; verifier rejects changed values |
| D2 | Batched medians can never classify | batched receipts return `F_BATCHED_OBSERVATION_ONLY` |
| D3 | A valid numerical failure is recorded as a failure, never retried | controller exits non-zero only for invalid evidence; verifier returns the failing status and reasons |
| D4 | Any invalid evidence is a hard stop | source/oracle/score/binary/format/mode/codegen/seal failures block before classification |
| D5 | The frozen PR 15I-C acceptance is unchanged and unmet | no receipt in this experiment claims feature acceptance |

# PR 15I-C dispatch-isolation — independent verification

## Tooling

| File | Role |
|---|---|
| `dispatch_protocol_v1.json` | frozen protocol (`pr15i-c-dispatch-isolation-v1`, SHA-256 `4a7889ad66a407b98ee2b1e5e753676393c2267d5026f7540702ad884fa14621`) |
| `dispatch_run.py` | four-arm controller |
| `verify_dispatch.py` | independent verifier + `--aggregate` |
| `dispatch_source_proof.py` | mechanical Git-blob source/feature proof |
| `dispatch_codegen_capture.py` | source-neutral `nm`/`objdump` wrapper |

The verifier imports no controller statistics: it re-implements the frozen
nearest-rank median, the two-slot block mean, the four block ratios, the campaign
medians, the A/A drift sentinel and the §8 classifier with explicit precedence.
It may use the frozen PR15D oracle and the mechanical Git-blob reader.

## What the verifier checks (executed, not asserted)

1. Realpath confinement under `target/pr15i-c/dispatch-isolation-v1`, no
   symlinks, exact raw inventory (11 metadata files + `protocol.json` copy + 32
   slot files + `seal.json`), full SHA-256 seal re-checked before and after.
2. Re-derives the D and E diffs from Git (not from `raw/source-proof.json`), and
   requires the recorded values to agree.
3. Re-hashes the four actual adapter files after the campaign, requires four
   distinct hashes, per-arm features and mode variables, and per-slot path/hash
   identity.
4. Re-derives all 24 index rebuilds from disk: layout, sidecar, segment digest,
   STORED v2, codec 1, feature `[13,1]`, and the 100K sentinel; requires A/C/D/E
   byte and digest equality per corpus size.
5. Validates the 4×8 schedule (two of each arm per block), 5 warmups, 20 samples
   (or 10 batches with the correct 100/1 repeat), positive integer durations,
   correct `engine_ns`/`batch_ns` unit per regime.
6. Requires all 64 contention probes `clear` per campaign, one host fingerprint,
   one toolchain and one affinity mode across the series.
7. Recomputes the frozen PR15D oracle for every warmup and sample, plus the
   nine-lane score-bit parity record.
8. Recomputes every ratio and rejects any mismatch with the controller at
   `1e-12`.
9. Re-captures the four arm binaries itself for the codegen structural controls,
   instead of trusting the controller-era flag.
10. Applies §8 precedence: BLOCKED → INCONCLUSIVE → NOT_REPRODUCED → exact rows →
    MIXED, using only the two unbatched campaigns.

## Receipts

| Receipt | Campaign |
|---|---|
| `target/pr15i-c/reviews/dispatch-unbatched-01-verification.json` | unbatched-01 |
| `target/pr15i-c/reviews/dispatch-batched-01-verification.json` | batched-01 |
| `target/pr15i-c/reviews/dispatch-unbatched-02-verification.json` | unbatched-02 |
| `target/pr15i-c/reviews/dispatch-batched-02-verification.json` | batched-02 |
| `target/pr15i-c/reviews/dispatch-series-aggregate-verification.json` | series |

Each receipt records `feature_acceptance: false` and
`real_rustfs_not_a_diagnostic_gate: true`. `--verify-only` writes nothing and was
run after the receipt-producing pass; re-verification is deterministic.

## Adversarial tests

`test_verify_dispatch.py` implements the DC-V matrix cases with typed `DV_*`
rejections (inventory, path/symlink, seal, source, feature, binary, format,
sample, unit, oracle, ratio, schedule, contention, receipt) including a re-sealed
semantic tamper that a hash-only check would miss. Together with
`test_dispatch_run.py` (real per-arm mode truth tables, source proofs, codegen
wrapper, arithmetic) the dispatch study contributes **73 executed tests**.

## Tampering caveat

The SHA-256 seal detects accidental edits; it is not cryptographic
authentication. The independent re-derivation of source identity, oracle and
constraints from Git and the frozen protocol is what makes a re-sealed forgery
detectable, and the tests exercise exactly that case.

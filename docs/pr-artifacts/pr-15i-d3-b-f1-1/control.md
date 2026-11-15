# PR 15I-D3-B-F1.1 — official A/A control `d3bf11-base-aa-01`

**Result: `CONTROL_QUALIFIED`, independently verified.**

## Identity and execution

| Item | Value |
|---|---|
| Campaign | `d3bf11-base-aa-01` (FIRST FRESH F1.1 control) |
| Kind | same-source A/A control, both arms BASE `39dbd9f5…` |
| T2 tooling | `63b30a0be451357a5edaf8399ad2e4d336e6c45b` |
| Protocol SHA-256 | `ae1b7d8d9ab638e70cddb1e52d0b9dd063ccdffae74826ab67728db42a095b4c` |
| Tooling manifest SHA-256 | `f9134926cbe372b628f6248aa7f846a52455ebaedaa6b2a741f402796295e250` |
| Canonical compile path | `…/fixup-f1-1/d3bf11-base-aa-01/compile-source` |
| Arm A binary | `6469b5fa3952823f5828e59a2946bae4e166cd4c6eed97029c5712a406a2d71d`, 4,479,272 bytes |
| Arm B binary | `6469b5fa3952823f5828e59a2946bae4e166cd4c6eed97029c5712a406a2d71d`, 4,479,272 bytes |
| Build provenance SHA-256 | `3696f404619bee80970adc7741ea5a509c08b56e80597e81c0e345699d924485` |
| Host attestation SHA-256 | `efda5a3f2e21b9e937fda4372bc513509de01fdacfc0f1f2fa6760d31318266d` |
| Host fingerprint | `aa13625261508f3dc3a97ec937106c33ba53dc79c79fc64f8577ec2269d706a9` |
| Slots / lane records | 16 / 144 |
| Timed samples / warmups | 2,880 / 720 |
| Contention probes | 32, all `clear` |
| Drift | `PASS`, zero violations |

Two real, sequential `cargo build --release --locked` executions from **one**
canonical path into independent target directories produced **byte-identical**
BASE binaries. The controller and the independent verifier computed the same
host fingerprint from the sealed `allowed_cpus_before_pin` list — the F1 defect
is fixed.

## A/A numerical result (all lanes pass, no soft exception used)

| Lane | Block B/A ratios | Lower-median | Pass |
|---|---|---|---|
| `pr15d_v1/10000/absent/k100` | 0.982525, 0.944630, 0.963522, 0.877047 | 0.944630 | yes |
| `pr15d_v1/10000/rare/k100` | 0.991604, 1.030844, 0.937299, 1.022562 | 0.991604 | yes |
| `pr15d_v1/10000/medium/k100` | 0.959466, 1.022374, 1.019091, 1.003326 | 1.003326 | yes |
| `pr15d_v1/10000/common/k100` | 0.983168, 1.009234, 1.003451, 0.997715 | 0.997715 | yes |
| `pr15d_v1/100000/absent/k100` | 0.990901, 1.036551, 1.057684, 1.010112 | 1.010112 | yes |
| `pr15d_v1/100000/rare/k100` | 0.921474, 1.035588, 1.033828, 0.967428 | 0.967428 | yes |
| `pr15d_v1/100000/medium/k100` | 0.987306, 1.068978, 1.013658, 0.999478 | 0.999478 | yes |
| `pr15d_v1/100000/common/k100` | 0.978604, 0.999178, 0.994094, 0.988824 | 0.988824 | yes |
| `pr15d_v1/100000/common/k10` | 0.982451, 0.998717, 0.988954, 1.004406 | 0.988954 | yes |

## Index and oracle identity

Both arms produced byte-identical indexes: 10K and 100K layouts with digest
`5734ae60591f7563…` for 100K; **100K committed bytes 15,747,551** and **STORED
1,661,455**, matching the frozen sentinels. The verifier regenerated the frozen
PR15D corpus and confirmed every lane's hit count and document IDs.

## Independent verification

`python3 benchmarks/pr15i_d3_b_f1_1/verify.py --campaign-dir …/d3bf11-base-aa-01`
returns exit `0` with `verification=PASS`, `campaign_status=CONTROL_QUALIFIED`,
`summary_match=true`, `a_a_passes=true`, 16 slots, 59 sealed members,
`live_binary_rehash=PASS`, and build/host/affinity structural statuses `PASS`.
`compile-source/` is present and correctly excluded from the sealed inventory
(the F1 defect is fixed); it is neither sealed nor archived.

## Archive

`run.py publish` produced an exclusive archive after verification:

| Item | Value |
|---|---|
| Archive | `d3bf11-base-aa-01.tar.gz` |
| SHA-256 | `f58ef556a50ea08ac8feb1b5c724276e8eb7f0626113c7a543d28c762de8c060` |
| Members | 61 |
| Sidecar | `d3bf11-base-aa-01.tar.gz.sha256` (exclusive, matching) |

The archive excludes `build/`, `indexes/`, `corpus/` and `compile-source/`, and
its extraction/rehash round-trip was verified by `publish`.

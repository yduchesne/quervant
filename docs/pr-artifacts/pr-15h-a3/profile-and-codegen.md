# PR 15H-A3 — profiles and codegen

## Profiler availability

| Probe | Result |
|---|---|
| `perf --version` | `perf not found for kernel 6.18.33.2-microsoft` |
| `perf stat -e cycles,instructions -- true` | exit 2 (unavailable) |
| `/proc/sys/kernel/perf_event_paranoid` | `2` |
| Packages installed | none (A3-D44) |

**`PROFILE_UNAVAILABLE`.** No cycle/instruction/branch/cache counters and no
`perf record` call stacks were collected. No elapsed-time substitution is
presented as CPU evidence.

## Machine-code inspection

`objdump`/`nm`/`size` (GNU binutils 2.42) resolved function symbols.

| Fact | A | B |
|---|---|---|
| Binary SHA-256 | `3370083e…af14f` | `8682403a…1f867c` |
| `.text` bytes | 3,172,458 | 3,186,842 |
| `evaluate_lexical_with` | `0xdc9`, 693 instr | `0xe69`, 713 instr |
| `evaluate_single_term_linear` | absent | `0xdef`, 716 instr |
| Gate instruction | absent | `24dcb2 cmpq $0x2000,0x28(%r14)` |
| Helper call | absent | `24dd0e call …evaluate_single_term_linear…` |

The B sparse path is source-identical below the gate; the extra machine code is
the gate/shape check plus the (not-taken on sparse) helper branch and the helper
body. Whether the larger function/layout affects sparse latency cannot be
decided here because the A/A control failed. These are observations only
(A3-D49/D50/D68); no instruction-cache or inlining cause is asserted.

Raw artifacts (ignored): `target/pr15h-a3/profiles/objdump/`.

## Source-level answer to Q1/Q2

- **Q1 dynamic work:** the sparse path adds only a shape match, one `.len()` read
  and one comparison. It adds no loop, allocation, decoder/validator, statistics
  pass or callback. This is a source fact, not a measured cost.
- **Q2 compiler layout:** the optimized code differs (function size, gate, helper
  call). The A/A session was too noisy to attribute any latency change to it.

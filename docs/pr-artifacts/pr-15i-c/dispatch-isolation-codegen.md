# PR 15I-C dispatch-isolation — machine-code evidence

Diagnostic only. `nm`/`objdump` are present; `perf` is **unavailable**
(`PERF_UNAVAILABLE`), so no cycle, cache, branch-prediction or I-cache claim is
made anywhere in this study. Symbols are selected by exact demangled-name suffix
(never substring/drop-glue matching), and every reported "present" symbol has a
non-empty in-range disassembly body.

## Method presence (identical in all four campaigns, re-captured by the verifier)

| Target | A | C | D | E |
|---|---|---|---|---|
| `execute_unified` | PRESENT | PRESENT | PRESENT | PRESENT |
| `collect_mixed` | inlined/absent | inlined/absent | inlined/absent | **PRESENT** |
| `collect_exact_term_physical` | absent | **PRESENT** | **absent (eliminated)** | absent (never defined) |
| `collect_mixed_dispatch_probe` | absent | absent | absent | **PRESENT** |
| `pr15ic_causal_enabled` | absent | inlined/absent | inlined/absent | inlined/absent |

Recorded instruction counts from the verifier's capture of the campaign binaries:

Instruction counts (bytes) as captured by the verifier's independent re-capture:

| Arm | `execute_unified` | `collect_mixed` | `collect_exact_term_physical` | `collect_mixed_dispatch_probe` |
|---|---|---|---|---|
| A | 3993 (23952) | absent | absent | absent |
| C | 4173 (25056) | absent | 1063 (6304) | absent |
| D | 4053 (24336) | absent | absent | absent |
| E | 2027 (11168) | 2692 (16016) | absent | 25 (64) |

## What this establishes — and what it does not

* **D really did lose the physical operator**: the symbol is absent in D although
  the source still contains `collect_exact_term_physical` and its call, so the
  literal-false condition let the compiler delete both. D is therefore a genuine
  "candidate without the physical path" arm, not a "physical path still present but
  unreachable" arm.
* **E's trampoline exists and is a real, separate 25-instruction function**, and it
  forces `collect_mixed` out of line (that is why A/C/D show no `collect_mixed`
  symbol while E does). E is therefore structurally a *different* generic call
  shape from A, which is exactly the limitation the plan predeclared.
* `execute_unified` is largest in C (4173 instructions) and D (4053) and smaller in
  A (3993); in E it shrinks to 2027 because the generic collector is no longer
  inlined into it (it lives in its own 2692-instruction symbol). Instruction
  counts are **not** execution-time evidence and are reported only as structural
  facts; the A-vs-C difference of about 4.5% cannot explain a 30-80% latency change.
* No claim is made about *why* C's generic path is slower. With the operator
  eliminated the regression largely disappears (D), and the minimal scaffold alone
  does not produce it (E), but the predeclared per-lane classification is not
  uniform for D (see `dispatch-isolation-performance.md`), so the study reports
  MIXED rather than a single cause.

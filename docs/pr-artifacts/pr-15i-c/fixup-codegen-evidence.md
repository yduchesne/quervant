# PR 15I-C fixup — machine-code and compiler evidence

Diagnostic only (`FX-I12`, `FX-D34..FX-D38`). Nothing here is acceptance
evidence; acceptance for F0 is the eight-block timing diagnostic plus its
independent receipt.

## 1. Environment

| Item | Value |
|---|---|
| rustc / cargo | `1.98.1` / `1.98.1` |
| Cargo profile | release, workspace defaults, unchanged `RUSTFLAGS` |
| Linker / target | host default `x86_64-unknown-linux-gnu` |
| `nm` | `/usr/bin/nm` |
| `objdump` | `/usr/bin/objdump` |
| `llvm-objdump` | `TOOL_UNAVAILABLE` |
| `perf` | **`PERF_UNAVAILABLE`** — WSL kernel `6.18.33.2-microsoft` has no matching perf package |

Capture artefact: `target/pr15i-c/layout-diagnostics/codegen-03/codegen-capture.json`
(plus `A-*.asm`, `G-*.asm`, `A-nm.txt`, `G-nm.txt`). An earlier
`codegen-01`/`codegen-02` capture is retained but superseded: its symbol selector
matched generic-argument mentions (drop glue) rather than the method, and its
`--disassemble=<demangled name>` produced empty bodies. `codegen-03` selects the
exact demangled method symbol by suffix and disassembles the symbol's real address
range.

## 2. Facts

| Fact | Arm A (`6f6463cb`, merged PR 15I-B) | Arm G (`50b56e9`, + `#[inline(never)]`) |
|---|---|---|
| Adapter binary SHA-256 | `805fe4e4c849529b…` | `d89a8745193c4d5e…` |
| Adapter binary bytes | 4,478,840 | 4,476,072 |
| Standalone `UnifiedSearcher::collect_mixed` symbol | **absent → inlined** (`SYMBOL_INLINED_OR_NOT_PRESENT`) | present, 2,644 instructions / 15,584 bytes |
| `UnifiedSearcher::execute_unified` | 3,993 instructions / 23,952 bytes | 1,898 instructions / 10,320 bytes |

Interpretation (stated as fact, not causation): in the accepted merged baseline the
large generic executor is **inlined into** `execute_unified`. The single
`#[inline(never)]` attribute in arm G does force it out of line — that is a real,
symbol-observable machine-code difference, and it shrinks `execute_unified` by
about 57% of its instruction count.

## 3. What this does and does not prove

* It **confirms** the mechanism assumed by the fixup hypothesis: `collect_mixed`
  was previously inlined into a larger caller, so adding a data-dependent
  eligibility branch inside its body could perturb inlining/layout of the generic
  path exactly as the historical candidate did.
* It **does not** prove the original regression was caused by a specific LLVM
  decision: `perf` counters (`instructions`, `cycles`, `branches`,
  `branch-misses`, `cache-misses`, `task-clock`) are unavailable on this host, so
  no branch-miss or I-cache claim is made.
* It does **not** show that taking the generic executor out of line is free: the
  F0 timing diagnostic measures that, and it did not reliably pass (see
  `fixup-performance-decision.md`).

## 4. Supervision of the capture tool

`benchmarks/pr15i_c/codegen_capture.py` records hashes of the actual binaries and
re-hashes them after capture, refusing to report a mutated binary; missing tools
and missing binaries are typed `TOOL_UNAVAILABLE` / `BINARY_MISSING`, never
fabricated. Its unit tests cover hash provenance, unavailable-tool handling,
missing arm handling and refusal to overwrite.

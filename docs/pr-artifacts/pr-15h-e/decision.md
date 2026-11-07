# PR 15H-E — decision

**Disposition: `E_SIZE_REJECTED_SAFE_ROLLBACK`.**

All correctness and latency gates passed, and dictionary compression exceeded
the dictionary-specific gates (E-P01/E-P02). However, the frozen overall storage
gates failed:

- E-P03 100K segment: 19,481,993 / 21,364,026 = 0.9119 > 0.90.
- E-P04 100K committed index: 29,082,996 / 30,965,025 = 0.9392 > 0.92.

A valid campaign miss is a rejection. Thresholds and lanes were frozen before
measurement and were not retuned. The v2 dictionary and its feature/tests were
therefore removed by exact source rollback, with the sealed campaigns, controller,
tooling and this evidence retained. See `rollback.md`.

- Tooling / A: `eb6ed9170308965987a35211d227431535a41ecb`
- Candidate E: `72b18e249f2a83b77fd2faaf05deb6f0d60eaad6`
- Rollback: `8d722ad0c0cff6b947fcdc762bb2ccaacdfcff0b`

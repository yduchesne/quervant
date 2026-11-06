# PR 15G-D confirmation preflight

**Status:** preflight complete.
**Shared HEAD:** `4a4fec50238f1f0f75aed122fe0d8ecea60f0f81`
**A:** `ca065a212987284144d8901aa5c54de093d6dbfc`
**B (D1):** `1d2a6b0f08bf68994699e1f3e37f163347492cd1`
**C (D1+D2):** `dae598758a433ecdc0d9af37e15194e948bbc788`

- Ancestry A -> B -> C -> HEAD verified.
- C->HEAD diff is documentation only for the D production files.
- Original D1/D2 reports and the two-arm runner remain unchanged.
- Frozen PR15D/PR15E-B1 corpus, adapter and oracle remain unchanged.
- Measurement host is native ext4/WSL2; host and frozen-input fingerprints are
  recorded only in ignored raw evidence.
- This is a measurement-only follow-up; no production or CI change is made.

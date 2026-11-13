# PR 15I-D3-C — T5 / protocol v2 tooling freeze

**T5: FROZEN** under the owner-authorized procedural qualification and the
stability-remediation plan.

- Experimental source: `3ad6c5184fbe9c011abb731415a007e3f19d21de`
- Protocol v2 SHA-256: `55255c687ccfa65f8cffe3169cca6f01880584f30e3c7f29843489bedc42a5c5`
- T5 tooling commit: `1bdbef8984461de7ddc6c8fd30a1960e6accf140`
- Tooling manifest SHA-256: `b523772968ea3c2874a0c45882213a9a9707fb5979e9c0391a61066e5942d299`
- Protocol v1 remains byte-unchanged; only `control_name`, `campaign_names`
  and `evidence_root_relative` differ in v2.

Pre-freeze evidence:

- Host topology: allowed CPUs 0–11; selected adapter CPU 0 (package 0, core 0,
  siblings 0–1) and controller CPU 2 (package 0, core 1, siblings 2–3). The
  failed v1 control used logical CPUs 0 and 1, which are SMT siblings.
- One 13-lane diagnostic, 16 slots, 4,160 real samples: `DIAGNOSTIC_STABLE`,
  zero drift violations, original subset A/A gate `CONTROL_QUALIFIED`.
- v2 preflight `PREFLIGHT_OK`; v2 dry-proof `DRY_PROOF_OK`.
- Synthetic rehearsal: 3 positives, 16 negatives, publisher refusal; evidence
  directory deleted.
- Python suite: 83 tests PASS. Rust: fmt/clippy PASS, 2,518 workspace tests PASS.
- T0–T3 historical diffs empty; v1 blocked control and T4 unchanged.

Official v2 acquisition may proceed in order control -> strategies-01 ->
strategies-02, with independent verification and publication after each.

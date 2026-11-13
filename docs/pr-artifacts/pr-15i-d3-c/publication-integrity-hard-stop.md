# PR 15I-D3-C — publication-integrity HARD STOP

Status: **HARD STOP** on distinguishing genuine acquisition from relabeled
synthetic rehearsal evidence using the existing evidence format.

## Demonstrated defect

`test_run.py::PublishGate.test_pub01_relabelled_synthetic_is_accepted_today`
takes a fixture produced by `replay.py`, changes only the mutable
`authorization.rehearsal_only` flag, and the publisher accepts it:
`status=PUBLISHED`, archive and sidecar created.

`test_pub02_relabelled_host_markers_still_accepted` additionally rewrites the
mutable host attestation markers (`kernel`, `cpu_model`, `recorded_utc`,
`toolchains`) and the manifest digest, reseals the mutable copy, and the
publisher still accepts it.

The synthetic slots themselves carry deterministic fabricated values
(`adapter_pid=1000`, synthetic sample progression). These too are mutable raw
payload that can be resealed. The current format has no immutable,
independently authenticated marker proving that samples came from a real
adapter process on this host.

## Consequence

The publisher cannot be made to reject relabeled synthetic evidence using the
existing acquisition evidence without inventing a new attestation/trust
mechanism. `test_pub01`/`test_pub02` are retained as documented failing
regression fixtures; they do not count as positive qualification evidence.

Failure-atomic publication and duplicate-publication rejection were implemented
and tested independently (`test_pub03` and `test_pub04`), but they do not solve
the authenticity gap.

## Required decision

Authorize an evidence-authenticity mechanism (for example a controller-produced
signed/attested acquisition statement verified independently) or explicitly
accept that publication qualification is procedural only. Until then T4 may not
be frozen and no official acquisition may run.

# PR 15I-D3-A evidence index

Status: `NOT_RUN`.

No evidence archive exists yet. When campaigns run, each attempt (including
failed or superseded attempts) is listed here with:

- campaign id and attempt path;
- qualification status (`QUALIFIED`, `BLOCKED`, `SUPERSEDED`);
- T0, BASE and protocol identities;
- archive path, archive SHA-256 and `.sha256` sidecar path;
- independent re-extraction verification result;
- `SAME_DISK_ONLY` disclosure unless an off-host copy is separately verified.

Failed attempts are never deleted or re-sealed with repaired raw files.

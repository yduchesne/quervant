# PR 15I-D3-A evidence index

Status: `D3A_MEASUREMENT_BLOCKED`.

All archives are outside `target/`, have an exclusive `.sha256` sidecar, and
were independently re-extracted and verified by `verify_archive_bundle`.
Storage class: `SAME_DISK_ONLY` (WSL virtual disk; no off-host copy).

| Attempt | Qualification | Archive | SHA-256 | Members |
|---|---|---|---|---:|
| `d3a-base-aa-01.attempt-01-not-qualified` | `NOT_QUALIFIED` (control block ratio) | `~/.local/share/quervant/benchmark-evidence/pr15i-d3a/d3a-base-aa-01.attempt-01-not-qualified.tar.gz` | `f08de815611242809ab796ce42347dd18089864e4091b415dad5b37c1502701c` | 63 + A1/A2 build artifacts |
| `d3a-base-aa-01.attempt-03-not-qualified` | `NOT_QUALIFIED` (single retry; control block ratio) | `~/.local/share/quervant/benchmark-evidence/pr15i-d3a/d3a-base-aa-01.attempt-03-not-qualified.tar.gz` | `5cea38b062c354baa57d8bc787d07c895934c2e77536572fae69f959b0ec2f4f` | 63 |

## Preserved but superseded

- `target/pr15i-d3a/superseded/t0-2576bba/` contains the T0 preflight, T0 A/A
  control (qualified), the T0 `d3a-unbatched-01` raw campaign, the T0 build
  metadata and the first derivation. These predate the verifier stage-key
  repair and are **not** used for any conclusion.
- `target/pr15i-d3a/aa/d3a-base-aa-01.attempt-02-write-exists` is an aborted
  attempt that produced no slot measurements. It is not sealed or archived.

## Disclosure

- Attempt 01's archive includes its preserved `A1`/`A2` release build
  artifacts because they were moved into the attempt directory before archival;
  the archive is therefore much larger than a normal campaign archive. Its
  manifest and sidecar are internally consistent.
- No failed attempt was deleted, edited or re-sealed with repaired raw files.
- No qualified paired-campaign archive exists for this series.

# PR 14F — environment and provider prequalification

**Status:** host and pinned provider verified. Operator idle attestation is
**NOT SUPPLIED**, so no qualified measurement was attempted (X15). Endpoint,
bucket and credential values are deliberately omitted (AD-F11).

## 1. Host and toolchain

| Item | Observed value |
|---|---|
| UTC date | 2026-10-26 |
| Host kernel | `Linux 6.18.33.2-microsoft-standard-WSL2 #1 SMP PREEMPT_DYNAMIC … x86_64` |
| Environment | WSL2 (`microsoft-standard-WSL2` in `/proc/version`) |
| Distribution | Ubuntu 24.04.5 LTS (PR 14B record; unchanged host) |
| CPU | Intel(R) Core(TM) i7-10750H CPU @ 2.60GHz, 12 logical CPUs |
| RAM | 32,774,780 kB total; 31,667,532 kB available at preflight |
| Root filesystem | `/dev/sdd`, `df -T` type `ext4`; `stat -f -c %T` reports `ext2/ext3` (shared ext2/3/4 statfs magic) |
| Free space | 1007G total, 639G available (34% used) |
| Host load at preflight | `0.36 0.20 0.08` (before validation workloads) |
| Host load after validation | `1.02 5.82 4.96` — **not an idle host** |
| Stable Rust | `rustc 1.98.1 (48a229cea 2026-09-01)`, `cargo 1.98.1` |
| MSRV toolchain | `1.85.0-x86_64-unknown-linux-gnu` (`rustc 1.85.0`) |
| Installed toolchains | `stable`, `1.85.0`, `1.98.1` |
| Coverage tool | `cargo-llvm-cov 0.9.1` |
| Container runtime | `podman 4.9.3` (rootless) |
| Python | 3.12.3 |
| Git | 2.43.0 |

Native Linux filesystem requirement: **satisfied**. The repository is not on
`/mnt/c` or `drvfs`. Linux-in-WSL2 on ext4 is permitted by
`docs/BENCHMARKING.md`; `/proc` observations do not include Windows-host
processes or other WSL guests (see adversarial review).

## 2. Pinned real provider

| Item | Value |
|---|---|
| Reference | `docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c` |
| Tag | `rustfs/rustfs:1.0.1` |
| Image ID | `f6b22807f10db2aee80b8a9ed1e36bd12c2fba25ac2d98dc3b0332a23f1a5c4d` |
| Digest verification | `podman pull` of the exact pinned digest succeeded; `podman image inspect` lists the pinned digest in `RepoDigests` (an additional platform-manifest digest `sha256:7465b319…34a56` is also listed for the same image) |
| Container | `quervant-pr14f-rustfs` (rootless podman, `no-new-privileges:true`) |
| Container state | running; started 2026-10-26 14:29:55 PDT |
| Health | `{"status":"ok","service":"rustfs-endpoint","version":"1.0.1"}` |
| Endpoint / bucket / credentials | loopback pinned RustFS with disposable harness values; **values intentionally not recorded** |

The pinned reference and image ID agree with the PR 14B/14D committed evidence
(`f6b22807…1a5c4d`, health `1.0.1`). No substitute tag, fake provider or
reconstructed digest was used.

The provider was exercised end-to-end by all three qualified trials at source
`7df4920…` on 2026-10-26T23:13Z–23:43Z: bucket creation, three immutable segment
commits per trial, cold reader opens and warm queries. All three live contention
checks were `clear`. An earlier campaign at `162cbfea…` aborted after t1 on a
harness report-path defect unrelated to the provider; that attempt is disclosed
in `qualification-attempts.md`.

## 3. Operator gate

The human operator has not stated that competing benchmark workloads are
stopped and the host is sufficiently idle. A `clear` contention detector result
is explicitly **not** that attestation (AD-F10). The agent did not pass
`--idle-confirmed`, did not self-generate an attestation, and did not run a
diagnostic or qualified trial.

The host load after local validation rose to `5.82`, so no idle attestation was
made then. The operator later attested idleness. The corrected campaign started
with the host independently observed idle (load `0.19 0.07 0.21`, 100% idle CPU,
0 runnable processes); all three trial contention records are `clear`.

## 4. Provider environment variables

`QUERVANT_RUSTFS_ENDPOINT`, `QUERVANT_RUSTFS_BUCKET`,
`QUERVANT_RUSTFS_ACCESS_KEY` and `QUERVANT_RUSTFS_SECRET_KEY` were **unset** in
the agent session at preflight (X17). No credential was requested, printed or
committed. A later attested campaign must export the non-secret endpoint,
region and bucket and supply disposable credentials through the local
environment; the wrapper already fails closed when any is missing.

## 5. Reproducible prequalification commands (no secrets)

```sh
uname -a
grep -qi microsoft /proc/version
grep -m1 'model name' /proc/cpuinfo
stat -f -c %T .
df -T .
rustc --version && cargo --version && rustup toolchain list
podman pull docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
podman image inspect docker.io/rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
curl -fsS <loopback-endpoint>/health
```

The container start command is the PR 14B documented pinned-image command with
disposable harness credentials; it is not repeated here to avoid recording
endpoint or credential values.

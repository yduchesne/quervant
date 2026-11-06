# Persistent offset directories v1.1 — rejected research record

**Status:** implemented, performance-rejected and rolled back; not an active
production format.

The experimental segment-only minor 1 format added required feature `0x000C`
and sections `0x0012`/`0x0013` containing canonical
`u16 version + u64 count + u64 source_len + sha256(source) + u64[N+1]`
record boundaries. Directories were bound to the exact STORED/DOC_KEYS body
digests, but were treated only as untrusted hints until an in-process full
semantic scan compared every boundary and published a snapshot-scoped
certificate.

Legacy 1.0 containers, manifests and mutation-state sidecars remained
unchanged. The design added no compression, range reads, durable receipt,
mmap, planner change or query-semantic change.

The format-aware A/E campaign qualified structurally but showed large rare-lane
regressions and several common-lane `A_FASTER` results. E was therefore rejected
and the production source was restored to exact A+B. This document preserves the
wire/trust rationale; it does **not** authorize emitting 1.1 segments.

# PR 15G-B design verification

**Status:** in progress — locked plan design, source comparison and test mapping.
**GB_BASE_SHA:** `3329dd861ffdae0258703e0f6b9e9fe7eb19cb8c`

## Locked decisions

| Decision | Verification intent |
|---|---|
| GB-AD-001 | In-memory offsets over existing v1 bodies; no wire/format change |
| GB-AD-002 | `ValidatedOffsets` holds `Vec<u64>` ends plus `MetadataReservation` |
| GB-AD-003 | Two `OnceLock<Option<ValidatedOffsets>>` cells in admitted state |
| GB-AD-004 | `access_budget` present only on admitted cached state |
| GB-AD-005 | `(doc_count+1)*size_of::<u64>()` reserved before fallible allocation |
| GB-AD-006 | STORED offsets captured through the existing selected scanner |
| GB-AD-007 | DOC_KEYS offsets captured through the existing full key checks |
| GB-AD-008 | Direct STORED read decodes only selected slices, exact consumption |
| GB-AD-009 | Direct key read owns exactly one key from a checked slice |
| GB-AD-010 | Full caches first; malformed request/error precedence preserved |
| GB-AD-011 | B benchmark baseline is shared-branch pre-B tip, not main |
| GB-AD-012 | No writer/format mutation, no shared mutable decoded values |

## Invariant/test mapping

| ID | Implementation witness | Adversarial witness |
|---|---|---|
| GB-I01 | Pre/post segment/index byte comparison | Frozen codec/golden tests |
| GB-I02 | STORED directory only after full scan | `GB-U04/U05/U27` corrupt unselected record |
| GB-I03 | DOC_KEYS full validation before publish | `GB-U17/U27` invalid unselected key |
| GB-I04 | Shared scanner preserves checks/order | `GB-U03/U08/U18` |
| GB-I05 | One full modeled `DecodeBudget` pass | `GB-U05/U06/U10` |
| GB-I06 | Differential selected vs legacy/full values | `GB-U03/U11/U13` |
| GB-I07 | Direct decoder visits only selected slices | `GB-U14/U15/U20` |
| GB-I08 | Zero/budget/fallback paths | `GB-U19/U24/U27` |
| GB-I09 | State-owned directory identity | `GB-U28` PIT/generation |
| GB-I10 | `OnceLock` publication, RAII on panic | `GB-U21/U25/U26` |
| GB-I11 | Full-cache precedence | `GB-U13/U23` |
| GB-I12 | Existing query/PIT/cursor suites | `GB-I01–I08` |
| GB-I13 | Real RustFS cold/warm harness | `GB-R01/R02` |
| GB-I14 | No new hot-path remote I/O/dynamic dispatch | Benchmark + RustFS GET counter |
| GB-I15 | Qualified A/B runner and gates | `GB-B01–B16`, `GB-P01–P05` |

## Boundaries

- `ends` length exactly `count+1`; zero records => `[10]`.
- `ends[0] == 10`, monotonic, terminal `== body.len()`.
- `usize` conversion, `start <= end`, every slice via `.get(..)`.
- `count+1` checked add.
- Existing `SegmentLimits` entry/allocation ceilings unchanged.
- Metadata allowance and actual capacity both checked.
- Existing full-cache branches untouched and first.
- Malformed/out-of-range selection reaches the legacy scanner before directory
  construction.
- Missing sections return the original `MissingSection` errors.
- `OnceLock(None)` means optional acceleration unavailable, never data invalid.
- No directory survives its owning `VerifiedSegmentState`.

## Residual risks

Cold first selective access pays one full validation scan; budget rejection
permanently disables that optional directory for the state; RSS is not bounded by
`MetadataBudget`; persistent/cold-reopen offsets remain out of scope.

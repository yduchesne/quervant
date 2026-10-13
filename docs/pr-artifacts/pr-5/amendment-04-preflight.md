# PR 5 Amendment 04 preflight — decoder budget consistency

> Narrow refactor of dictionary/schema/stored/JSON/remap decoders onto one shared
> modeled retained-byte budget. No wire/format/public-API change, no golden
> change, no merge.

## 1. Branch and baseline

| Fact | Value |
|---|---|
| Branch | `dev/segment-codecs` |
| Pre-amendment HEAD | `dcaffb3b1dccb93f5e655713652cfb394645efe7` |
| `origin/dev/segment-codecs` | `dcaffb3b1dccb93f5e655713652cfb394645efe7` |
| `origin/main` | `68bcf0d828f801f247d7f052082b76397f150fbf` |
| Merge base | `a23cf25798e52fc181e93ac84505a07412f37463` |
| Working tree | clean before edits |
| Rust | `rustc 1.85.0`; CI stable `1.99.0` |

## 2. Allocation inventory (before)

| Decoder | Retained allocations | Pre-charge status |
|---|---|---|
| `dictionary` | outer `Vec<(u32,Vec<DictionaryEntry>)>`, per-field `Vec<DictionaryEntry>`, per-term owned `String`, `previous_term` clone | Count/byte checks existed but were ad hoc; `previous_term` duplicated each term |
| `schema` | `Vec<CodecField>`, per-field name `String`, `FieldBinding` id/version `String` | Names charged after allocation; binding strings not charged |
| `stored` | `Vec<StoredRecord>`, key `String`, `BTreeMap` entries, nested value/JSON | No shared budget; per-field entries uncharged |
| `value` | multi `Vec<FieldValue>`, JSON `Vec<JsonValue>`/`Vec<(String,JsonValue)>`, strings/keys | Per-allocation `check_alloc` only, no cumulative shared budget |
| `remap` | two `Vec<u64>` plus a third inverse `Vec<u64>` from `from_order` | `from_order` built a redundant third vector |

## 3. Charge worksheet (model)

- Vector backing: `count * size_of::<T>()`.
- Owned string: UTF-8 byte length.
- `BTreeMap` entry: `size_of::<(K,V)>() + 3 * size_of::<usize>()`.
- `FieldBinding` is **not** fixed-size inline: it owns `id`/`version` `String`s.
  The plan's premise was inaccurate; those payloads are charged via
  `reserve_string`. This is stricter, needs no public/wire change, and is
  recorded as a resolved deviation (not a STOP).

Budgeted source of truth: `decode_budget::DecodeBudget`, one per logical decode,
passed mutably to nested operations.

## 4. Invariant ↔ test map

A4-01–A4-12 map to tests U01–U27, I01–I04 and G01–G02 (see
`correctness-matrix.md` §14 and the validation report). Counterexamples
challenged: empty/zero, exact/one-below, huge count with short source, many small
dictionary fields, duplicate/nonascending/UTF-8/truncation, shared stored budget,
nested JSON accumulation, remap identity/explicit/bad inverse, arithmetic
overflow.

## 5. Baseline QA

Prior pass-03 tree: 749 passed / 0 failed / 2 ignored; coverage 85.18% (MSRV).
Re-executed as regression evidence on the final tree.

## 6. Gate outcome

PASS; no STOP. The only contract discrepancy (binding strings) is resolved by
charging them, which does not change any public API, wire byte, or limit
interpretation. Proceeding.

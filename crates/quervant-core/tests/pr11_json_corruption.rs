//! PR 11 JSON path section format, corruption and resource-bound tests.

mod pr11_common;

use std::sync::Arc;

use pr11_common::*;
use quervant_core::contract::budget::Budgets;
use quervant_core::index::Index;
use quervant_core::search::{SearchError, SearchLimits};
use quervant_core::segment::format::{ByteReader, FEATURE_JSON_PATHS};
use quervant_core::segment::{
    ContainerBuilder, ContainerKind, SectionKind, SegmentError, SegmentLimits, SegmentReader,
    parse_container,
};
use quervant_core::storage::Directory;

fn body_doc(key: &str, value: i64) -> quervant_core::contract::document::Document {
    let mut document = doc(key, 1);
    set_body(&mut document, obj(&[("v", i64_value(value))]));
    document
}

fn float_body_doc(key: &str) -> quervant_core::contract::document::Document {
    let mut document = doc(key, 1);
    set_body(&mut document, obj(&[("n", f64_value(1.5))]));
    document
}

/// Absolute offset of the unique `kind == 4` payload inside a JSON-path body,
/// found by walking the documented wire rather than scanning for `1.5` bytes.
fn f64_payload_offset(section: &[u8]) -> usize {
    let mut reader = ByteReader::new(section);
    let _version = reader.u16("version").unwrap();
    let _doc_count = reader.u64("doc count").unwrap();
    let field_count = reader.u32("field count").unwrap();
    for _ in 0..field_count {
        let _field_id = reader.u32("field id").unwrap();
        let occurrence_count = reader.u64("occurrence count").unwrap();
        for _ in 0..occurrence_count {
            let _doc_id = reader.u64("doc id").unwrap();
            let segments = reader.varint("segment count").unwrap();
            for _ in 0..segments {
                match reader.u8("segment tag").unwrap() {
                    0 => {
                        let len = reader.varint("member length").unwrap() as usize;
                        reader.bytes(len, "member").unwrap();
                    }
                    1 => {
                        reader.varint("index").unwrap();
                    }
                    tag => panic!("unexpected segment tag {tag}"),
                }
            }
            let kind = reader.u8("node kind").unwrap();
            if kind == 4 {
                return reader.position();
            }
            match kind {
                0 | 6 | 7 => {}
                1 => {
                    reader.u8("bool").unwrap();
                }
                2 => {
                    reader.i64("i64").unwrap();
                }
                3 => {
                    reader.u64("u64").unwrap();
                }
                5 => {
                    let len = reader.varint("string length").unwrap() as usize;
                    reader.bytes(len, "string").unwrap();
                }
                other => panic!("unexpected node kind {other}"),
            }
        }
    }
    panic!("no kind-4 payload found")
}

fn first_segment_bytes(index: &Index) -> Vec<u8> {
    let snapshot = index.snapshot();
    let guard = snapshot.open_segment_reader(0).unwrap();
    guard.reader().bytes().to_vec()
}

/// Rebuild a segment, optionally dropping the JSON feature/section or replacing
/// the JSON body. This exercises the reader's fail-closed negotiation without
/// touching production code.
fn rebuild(
    bytes: &[u8],
    include_feature: bool,
    include_section: bool,
    json_body: Option<Vec<u8>>,
) -> Vec<u8> {
    let limits = SegmentLimits::default();
    let view = parse_container(bytes, &limits).unwrap();
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, view.doc_count());
    for (id, version) in view.required_features() {
        if *id == FEATURE_JSON_PATHS && !include_feature {
            continue;
        }
        builder.require_feature(*id, *version);
    }
    if include_feature && !view.required_features().contains(&(FEATURE_JSON_PATHS, 1)) {
        builder.require_feature(FEATURE_JSON_PATHS, 1);
    }
    for entry in view.sections() {
        if entry.kind == SectionKind::JsonPaths && !include_section {
            continue;
        }
        let body = if entry.kind == SectionKind::JsonPaths {
            json_body
                .clone()
                .unwrap_or_else(|| view.body(SectionKind::JsonPaths).unwrap().to_vec())
        } else {
            view.body(entry.kind).unwrap().to_vec()
        };
        builder.section(entry.kind, entry.flags, entry.aux, body);
    }
    builder.build().unwrap()
}

/// A1-T03 — a valid-checksum segment with a non-finite F64 payload fails at open.
#[test]
fn t_nonfinite_json_path_payloads_fail_at_segment_open() {
    let (_directory, index) = committed(vec![float_body_doc("a")]);
    let bytes = first_segment_bytes(&index);
    let limits = SegmentLimits::default();

    // Positive control: the unmodified finite fixture opens.
    SegmentReader::open(bytes.clone(), limits).unwrap();

    let view = parse_container(&bytes, &limits).unwrap();
    let section = view.body(SectionKind::JsonPaths).unwrap().to_vec();
    let payload = f64_payload_offset(&section);

    for (label, value) in [
        ("nan", f64::NAN),
        ("positive_infinity", f64::INFINITY),
        ("negative_infinity", f64::NEG_INFINITY),
    ] {
        let mut patched = section.clone();
        patched[payload..payload + 8].copy_from_slice(&value.to_bits().to_le_bytes());
        let rebuilt = rebuild(&bytes, true, true, Some(patched));
        // The rebuilt envelope has valid checksums, so rejection is semantic.
        let error = match SegmentReader::open(rebuilt, limits) {
            Ok(_) => panic!("non-finite payload must be rejected"),
            Err(error) => error,
        };
        assert!(
            matches!(
                error,
                SegmentError::NonFiniteFloat {
                    context: "json path f64"
                }
            ),
            "{label}: {error:?}"
        );
    }
}

/// Regenerates the checked-in JSON-path golden fixture.
///
/// Run with `cargo test -p quervant-core --test pr11_json_corruption \
/// generate_json_paths_golden -- --ignored` after a deliberate wire change.
#[test]
#[ignore = "writes tests/fixtures/segment/json_paths_golden.seg"]
fn generate_json_paths_golden() {
    let (_directory, index) = committed(vec![body_doc("a", 1), body_doc("b", 2)]);
    let bytes = first_segment_bytes(&index);
    std::fs::write("tests/fixtures/segment/json_paths_golden.seg", &bytes).unwrap();
}

/// J11-T13 — the checked-in golden segment is byte-frozen and readable.
#[test]
fn t13_json_paths_golden_fixture() {
    let bytes = include_bytes!("fixtures/segment/json_paths_golden.seg");
    let limits = SegmentLimits::default();
    let view = parse_container(bytes, &limits).unwrap();
    assert!(view.required_features().contains(&(FEATURE_JSON_PATHS, 1)));
    assert!(view.entry(SectionKind::JsonPaths).is_some());
    let reader = SegmentReader::open(bytes.to_vec(), limits).unwrap();
    assert_eq!(reader.doc_count(), 2);
    assert!(
        reader
            .sections()
            .iter()
            .any(|section| section.kind == SectionKind::JsonPaths)
    );
    // Byte-frozen: any wire change must regenerate the fixture deliberately.
    let digest = quervant_core::segment::format::sha256(bytes);
    let expected: [u8; 32] = [
        0x05, 0x28, 0xa6, 0x2c, 0xdb, 0x02, 0xfc, 0xd0, 0x87, 0x54, 0xd5, 0x77, 0x6f, 0x23, 0xbd,
        0x16, 0xde, 0x78, 0x7f, 0x78, 0x85, 0x97, 0xad, 0xe9, 0x3d, 0x5d, 0xfb, 0xc6, 0x5c, 0x30,
        0xa0, 0x2f,
    ];
    assert_eq!(digest, expected);
}

/// J11-T13 — the section and required feature are exact and deterministic.
#[test]
fn t13_feature_section_and_determinism() {
    let (_directory, index) = committed(vec![body_doc("a", 1)]);
    let bytes = first_segment_bytes(&index);
    let limits = SegmentLimits::default();
    let view = parse_container(&bytes, &limits).unwrap();
    assert!(view.required_features().contains(&(FEATURE_JSON_PATHS, 1)));
    assert!(view.entry(SectionKind::JsonPaths).is_some());
    // Identical logical input in the same insertion order encodes identically.
    let second = first_segment_bytes(&index);
    assert_eq!(bytes, second);
    SegmentReader::open(bytes, limits).unwrap();
}

/// J11-T14 — feature/section mismatches and corrupt bytes fail closed.
#[test]
fn t14_negotiation_and_corruption_fail_closed() {
    let (_directory, index) = committed(vec![body_doc("a", 1)]);
    let bytes = first_segment_bytes(&index);
    let limits = SegmentLimits::default();

    // Feature declared but section missing.
    let feature_only = rebuild(&bytes, true, false, None);
    assert!(SegmentReader::open(feature_only, limits).is_err());
    // Section present but feature missing.
    let section_only = rebuild(&bytes, false, true, None);
    assert!(SegmentReader::open(section_only, limits).is_err());
    // Legacy: neither, opens cleanly.
    let legacy = rebuild(&bytes, false, false, None);
    let reader = SegmentReader::open(legacy, limits).unwrap();
    assert!(
        reader
            .sections()
            .iter()
            .all(|s| s.kind != SectionKind::JsonPaths)
    );

    // A flipped body byte breaks the section digest.
    let view = parse_container(&bytes, &limits).unwrap();
    let entry = view.entry(SectionKind::JsonPaths).unwrap();
    let mut corrupt = bytes.clone();
    let corrupt_at = entry.offset as usize + 3;
    corrupt[corrupt_at] ^= 0xFF;
    assert!(SegmentReader::open(corrupt, limits).is_err());

    // Version byte bumped inside a structurally rebuilt body.
    let body = view.body(SectionKind::JsonPaths).unwrap().to_vec();
    let mut bad_version = body.clone();
    bad_version[0] = 2;
    assert!(SegmentReader::open(rebuild(&bytes, true, true, Some(bad_version)), limits).is_err());

    // Trailing bytes.
    let mut trailing = body.clone();
    trailing.push(0);
    assert!(SegmentReader::open(rebuild(&bytes, true, true, Some(trailing)), limits).is_err());

    // Non-JSON field id (field id is a u32 at offset 10).
    let mut bad_field = body.clone();
    bad_field[10] = 1;
    assert!(SegmentReader::open(rebuild(&bytes, true, true, Some(bad_field)), limits).is_err());
}

/// J11-T15 — decode allocation bounds fail at one-over without partial results.
#[test]
fn t15_decode_budget_limits() {
    let (_directory, index) = committed(vec![body_doc("a", 1)]);
    let bytes = first_segment_bytes(&index);
    // One-over the whole-segment acceptance ceiling.
    let small = SegmentLimits::default().with_accepted_segment_bytes(bytes.len() as u64 - 1);
    assert!(SegmentReader::open(bytes.clone(), small).is_err());
    // One-over the decoded section budget rejects at open.
    let tiny = SegmentLimits::default().with_max_section_decode_bytes(1);
    assert!(SegmentReader::open(bytes.clone(), tiny).is_err());
    // Exact acceptance succeeds.
    let exact = SegmentLimits::default().with_accepted_segment_bytes(bytes.len() as u64);
    SegmentReader::open(bytes, exact).unwrap();
}

/// J11-T16/T17 — typed work budget exhaustion and cancellation are terminal.
#[test]
fn t16_work_budget_and_cancellation() {
    let (_directory, index) = committed(vec![body_doc("a", 1)]);
    let snapshot = index.snapshot();
    let budgets = Budgets::new();

    let starved = SearchLimits::default()
        .with_max_typed_work_units(1)
        .unwrap();
    let error = try_search(&snapshot, exists("body", "$.v"), starved, &budgets).unwrap_err();
    assert!(matches!(error, SearchError::ResourceLimit { .. }));

    let cancel = quervant_core::analysis::CancellationFlag::new();
    cancel.cancel();
    let error = search_cancel(&snapshot, exists("body", "$.v"), &cancel).unwrap_err();
    assert!(matches!(error, SearchError::Cancelled));
}

/// J11-T15 — query path depth is bounded exactly at the documented ceiling.
#[test]
fn t15_query_path_depth_bound() {
    let (_directory, index) = committed(vec![body_doc("a", 1)]);
    let snapshot = index.snapshot();
    let budgets = Budgets::new();
    let mut deep = String::from("$");
    for _ in 0..128 {
        deep.push_str(".a");
    }
    let at_limit = exists("body", &deep);
    assert!(try_search(&snapshot, at_limit, SearchLimits::default(), &budgets).is_ok());

    let over = format!("{deep}.a");
    let error = try_search(
        &snapshot,
        exists("body", &over),
        SearchLimits::default(),
        &budgets,
    )
    .unwrap_err();
    assert!(matches!(error, SearchError::ResourceLimit { .. }));
}

/// J11-I12 — a non-JSON field query keeps its existing unsupported behavior.
#[test]
fn t23_unrelated_operators_still_unsupported() {
    let (_directory, index) = committed(vec![body_doc("a", 1)]);
    let snapshot = index.snapshot();
    let error = try_search(
        &snapshot,
        quervant_core::contract::query::Query::In {
            field: "body".to_owned(),
            values: vec![quervant_core::contract::value::FieldValue::Json(
                quervant_core::contract::value::JsonValue::Null,
            )],
        },
        SearchLimits::default(),
        &Budgets::new(),
    )
    .unwrap_err();
    assert!(matches!(error, SearchError::UnsupportedOperator { .. }));
}

/// A marker to keep the `Directory` import meaningful for future fault injectors.
#[allow(dead_code)]
fn directory_marker() -> Option<Arc<dyn Directory>> {
    None
}

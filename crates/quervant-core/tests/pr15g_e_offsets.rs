//! PR 15G-E — persistent offset-directory wire format and compatibility.

mod pr11_common;

use quervant_core::segment::format::{FEATURE_PERSISTENT_OFFSETS, SEGMENT_INDEXED_MINOR};
use quervant_core::segment::{SectionKind, SegmentLimits, parse_container};

#[test]
fn production_segments_emit_indexed_directories() {
    let mut a = pr11_common::doc("a", 1);
    pr11_common::set_body(
        &mut a,
        pr11_common::obj(&[("v", pr11_common::i64_value(1))]),
    );
    let mut b = pr11_common::doc("b", 1);
    pr11_common::set_body(
        &mut b,
        pr11_common::obj(&[("v", pr11_common::i64_value(2))]),
    );
    let (_directory, index) = pr11_common::committed(vec![a, b]);
    let snapshot = index.snapshot();
    let guard = snapshot.open_segment_reader(0).expect("reader");
    let bytes = guard.reader().bytes();
    let limits = SegmentLimits::default();
    let view = parse_container(bytes, &limits).expect("container");

    assert_eq!(view.format_minor(), SEGMENT_INDEXED_MINOR);
    assert!(
        view.required_features()
            .contains(&(FEATURE_PERSISTENT_OFFSETS, 1))
    );
    let stored = view.entry(SectionKind::Stored).expect("stored");
    let keys = view.entry(SectionKind::DocKeys).expect("keys");
    let stored_offsets = view
        .entry(SectionKind::StoredOffsets)
        .expect("stored offsets");
    let key_offsets = view.entry(SectionKind::DocKeyOffsets).expect("key offsets");
    assert_eq!(stored_offsets.flags, 0);
    assert_eq!(stored_offsets.aux, 0);
    assert_eq!(key_offsets.flags, 0);
    assert_eq!(key_offsets.aux, 0);
    assert_eq!(stored_offsets.length, 50 + 8 * (view.doc_count() + 1));
    assert_eq!(key_offsets.length, 50 + 8 * (view.doc_count() + 1));
    assert!(stored.length > 10);
    assert!(keys.length > 10);

    assert_eq!(
        pr11_common::search(&snapshot, pr11_common::exists("body", "$.v")),
        ["a", "b"]
    );
}

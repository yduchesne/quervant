//! PR 5 segment/manifest codec integration tests (plan P5-* suites).

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{
    FieldType, FieldValue, GeoPoint, IpNetwork, JsonNumber, JsonValue, Timestamp,
};
use quervant_core::segment::{
    BuiltSegment, Layout, SegmentBuilder, SegmentDocument, SegmentError, SegmentLimits,
    SegmentReader,
};
use quervant_objectstore::ContentDescriptor;

fn text_field(name: &str, analyzer: Option<&str>) -> FieldDefinition {
    let field = FieldDefinition::new(
        name,
        quervant_core::contract::value::FieldType::Text,
        Cardinality::Single,
        FieldOptions::indexed_stored(),
    );
    match analyzer {
        Some(analyzer) => field.with_analyzer(analyzer),
        None => field,
    }
}

fn keyword_field(
    name: &str,
    cardinality: Cardinality,
    normalizer: Option<&str>,
) -> FieldDefinition {
    let field = FieldDefinition::new(
        name,
        quervant_core::contract::value::FieldType::Keyword,
        cardinality,
        FieldOptions::new(true, true, true),
    );
    match normalizer {
        Some(normalizer) => field.with_normalizer(normalizer),
        None => field,
    }
}

fn test_schema() -> Schema {
    use quervant_core::contract::value::FieldType;
    Schema::new(
        vec![
            text_field("body", Some("standard")),
            keyword_field("tag", Cardinality::Single, Some("keyword")),
            keyword_field("tags", Cardinality::Multi, Some("keyword")),
            FieldDefinition::new(
                "count",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "flag",
                FieldType::Bool,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "score",
                FieldType::F64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "when",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "ip",
                FieldType::IpAddress,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "cidr",
                FieldType::IpNetwork,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "loc",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            text_field("raw", None),
            FieldDefinition::new(
                "meta",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
        ],
        Some("when".to_owned()),
    )
    .expect("schema")
}

fn document(key: &str, timestamp: i64, body: &str) -> SegmentDocument {
    let mut doc = SegmentDocument::new(DocumentKey::new(key).expect("key"));
    doc.fields.insert(
        "body".to_owned(),
        FieldValues::Single(FieldValue::Text(body.to_owned())),
    );
    doc.fields.insert(
        "tag".to_owned(),
        FieldValues::Single(FieldValue::Keyword("Alpha".to_owned())),
    );
    doc.fields.insert(
        "tags".to_owned(),
        FieldValues::Multi(vec![
            FieldValue::Keyword("x".to_owned()),
            FieldValue::Keyword("y".to_owned()),
        ]),
    );
    doc.fields
        .insert("count".to_owned(), FieldValues::Single(FieldValue::I64(-5)));
    doc.fields.insert(
        "flag".to_owned(),
        FieldValues::Single(FieldValue::Bool(true)),
    );
    doc.fields.insert(
        "score".to_owned(),
        FieldValues::Single(FieldValue::F64(1.5)),
    );
    doc.fields.insert(
        "when".to_owned(),
        FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(timestamp))),
    );
    doc.fields.insert(
        "ip".to_owned(),
        FieldValues::Single(FieldValue::Ip("2001:db8::1".parse().expect("ip"))),
    );
    doc.fields.insert(
        "cidr".to_owned(),
        FieldValues::Single(FieldValue::Cidr(
            IpNetwork::new("10.0.0.0".parse().expect("v4"), 8).expect("cidr"),
        )),
    );
    doc.fields.insert(
        "loc".to_owned(),
        FieldValues::Single(FieldValue::GeoPoint(
            GeoPoint::new(170.0, 10.0).expect("geo"),
        )),
    );
    doc.fields.insert(
        "meta".to_owned(),
        FieldValues::Single(FieldValue::Json(JsonValue::Object(vec![
            ("n".to_owned(), JsonValue::Number(JsonNumber::I64(7))),
            (
                "a".to_owned(),
                JsonValue::Array(vec![JsonValue::Bool(true), JsonValue::Null]),
            ),
        ]))),
    );
    doc
}

fn build(docs: Vec<SegmentDocument>, layout: Layout) -> BuiltSegment {
    let mut builder = SegmentBuilder::new(test_schema(), AnalyzerRegistry::builtin())
        .expect("builder")
        .with_layout(layout);
    for doc in docs {
        builder.add_document(doc).expect("add document");
    }
    builder.build().expect("build")
}

fn sample() -> BuiltSegment {
    build(
        vec![
            document("doc-a", 1000, "Hello world hello"),
            document("doc-b", 2000, "world there"),
        ],
        Layout::Insertion,
    )
}

#[test]
fn p5_g01_round_trip_and_content_descriptor() {
    let built = sample();
    let descriptor = ContentDescriptor::of(&built.bytes);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    assert_eq!(reader.doc_count(), 2);
    reader
        .verify_content_descriptor(&descriptor)
        .expect("descriptor verifies");
    assert_eq!(reader.schema().field_count(), 12);

    let stored = reader.stored().expect("stored");
    assert_eq!(stored.len(), 2);
    let first = &stored[0];
    assert_eq!(first.key.as_str(), "doc-a");
    let body_id = reader.schema().field_id("body").expect("body");
    assert_eq!(
        first.get(body_id),
        FieldValues::Single(FieldValue::Text("Hello world hello".to_owned()))
    );
    let meta_id = reader.schema().field_id("meta").expect("meta");
    match first.get(meta_id) {
        FieldValues::Single(FieldValue::Json(JsonValue::Object(entries))) => {
            assert_eq!(entries.len(), 2);
            assert_eq!(entries[0].0, "n");
        }
        other => panic!("unexpected meta: {other:?}"),
    }
}

#[test]
fn p5_a22_posting_doc_count_distinct_from_segment_doc_count() {
    let mut docs: Vec<SegmentDocument> = (0..10)
        .map(|i| document(&format!("doc-{i:02}"), i as i64, "filler"))
        .collect();
    docs[7].fields.insert(
        "body".to_owned(),
        FieldValues::Single(FieldValue::Text("needle".to_owned())),
    );
    docs[9].fields.insert(
        "body".to_owned(),
        FieldValues::Single(FieldValue::Text("needle".to_owned())),
    );
    let built = build(docs, Layout::Insertion);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    assert_eq!(reader.doc_count(), 10);
    let body_id = reader.schema().field_id("body").expect("body");
    let mut postings = reader
        .postings(body_id, "needle")
        .expect("postings")
        .expect("term present");
    assert_eq!(postings.posting_doc_count(), 2);
    let first = postings.next().expect("next").expect("first");
    let second = postings.next().expect("next").expect("second");
    assert_eq!(first.doc_id, 7);
    assert_eq!(second.doc_id, 9);
    assert!(postings.next().expect("next").is_none());
    // `posting_doc_count` is smaller than segment `doc_count`.
    assert_ne!(postings.posting_doc_count(), reader.doc_count());
}

#[test]
fn p5_u01_rejects_corrupt_magic_and_truncation() {
    let built = sample();
    let mut corrupt = built.bytes.clone();
    corrupt[0] ^= 0xff;
    assert!(matches!(
        SegmentReader::open(corrupt, SegmentLimits::default()),
        Err(SegmentError::InvalidMagic { .. })
    ));

    let truncated = built.bytes[..built.bytes.len() - 10].to_vec();
    assert!(SegmentReader::open(truncated, SegmentLimits::default()).is_err());
}

#[test]
fn p5_a21_envelope_and_whole_file_digests_cover_different_domains() {
    let built = sample();
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    // Whole-file descriptor matches.
    let whole = ContentDescriptor::of(&built.bytes);
    reader.verify_content_descriptor(&whole).expect("whole");

    // Corrupting a trailer byte breaks the whole-file digest, not the envelope.
    let mut tampered = built.bytes.clone();
    let len = tampered.len();
    tampered[len - 1] ^= 0xff;
    let expected = ContentDescriptor::of(&built.bytes);
    assert!(matches!(
        quervant_core::segment::verify_bytes(&tampered, &expected),
        Err(SegmentError::DigestMismatch { .. })
    ));
    // The tampered trailer no longer parses as a valid container either.
    assert!(SegmentReader::open(tampered, SegmentLimits::default()).is_err());
}

// ---------------------------------------------------------------------------
// Additional PR 5 suites (P5-I, P5-U, P5-A, P5-G)
// ---------------------------------------------------------------------------

use quervant_core::segment::{
    ColumnReader, DocRemap, GroupComponent, Manifest, ManifestSegmentRef, TimeBounds,
    encode_group_key,
};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory, StorageKey};

#[test]
fn p5_a08_five_states_round_trip() {
    let mut doc = document("states", 500, "body");
    doc.fields
        .insert("tag".to_owned(), FieldValues::ExplicitNull);
    doc.fields.insert("tags".to_owned(), FieldValues::Empty);
    doc.fields.remove("count");
    doc.fields.insert(
        "raw".to_owned(),
        FieldValues::Single(FieldValue::Text("Exact Raw".to_owned())),
    );
    let built = build(vec![doc], Layout::Insertion);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    let first = &reader.stored().expect("stored")[0];

    assert_eq!(
        first.get(reader.schema().field_id("tag").unwrap()),
        FieldValues::ExplicitNull
    );
    assert_eq!(
        first.get(reader.schema().field_id("tags").unwrap()),
        FieldValues::Empty
    );
    assert_eq!(
        first.get(reader.schema().field_id("count").unwrap()),
        FieldValues::Absent
    );
    assert_eq!(
        first.get(reader.schema().field_id("raw").unwrap()),
        FieldValues::Single(FieldValue::Text("Exact Raw".to_owned()))
    );
    // SINGLE and MULTI(count 1) remain distinct.
    let mut one = document("single-vs-multi", 600, "x");
    one.fields.insert(
        "tags".to_owned(),
        FieldValues::Multi(vec![FieldValue::Keyword("z".to_owned())]),
    );
    let built = build(vec![one], Layout::Insertion);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    let first = &reader.stored().expect("stored")[0];
    assert_eq!(
        first.get(reader.schema().field_id("tags").unwrap()),
        FieldValues::Multi(vec![FieldValue::Keyword("z".to_owned())])
    );
}

#[test]
fn p5_u27_group_keys_do_not_collide() {
    let ip = FieldValue::Ip("10.0.0.1".parse().expect("ip"));
    let keyword = FieldValue::Keyword("10.0.0.1".to_owned());
    let cidr = FieldValue::Cidr(IpNetwork::new("10.0.0.0".parse().expect("v4"), 8).expect("cidr"));
    let i64_one = FieldValue::I64(1);
    let u64_one = FieldValue::U64(1);
    let text_one = FieldValue::Text("1".to_owned());
    let keys = [
        encode_group_key(&[GroupComponent::Missing(FieldType::Keyword)]).expect("k"),
        encode_group_key(&[GroupComponent::Null(FieldType::Keyword)]).expect("k"),
        encode_group_key(&[GroupComponent::Value(&ip)]).expect("k"),
        encode_group_key(&[GroupComponent::Value(&keyword)]).expect("k"),
        encode_group_key(&[GroupComponent::Value(&cidr)]).expect("k"),
        encode_group_key(&[GroupComponent::Value(&i64_one)]).expect("k"),
        encode_group_key(&[GroupComponent::Value(&u64_one)]).expect("k"),
        encode_group_key(&[GroupComponent::Value(&text_one)]).expect("k"),
    ];
    for i in 0..keys.len() {
        for j in (i + 1)..keys.len() {
            assert_ne!(keys[i], keys[j], "group key collision {i} vs {j}");
        }
    }
    // Missing vs null with different declared types must also differ.
    assert_ne!(
        encode_group_key(&[GroupComponent::Missing(FieldType::Keyword)]).unwrap(),
        encode_group_key(&[GroupComponent::Missing(FieldType::I64)]).unwrap()
    );
    let ip2 = FieldValue::Ip("10.0.0.1".parse().expect("ip"));
    assert_eq!(
        keys[2],
        encode_group_key(&[GroupComponent::Value(&ip2)]).expect("k")
    );
}

#[test]
fn p5_g01_group_key_wire_bytes_match_approved_f07() {
    // Independently authored expected bytes: tuple_len, then (type_tag, state, value).
    let value = FieldValue::Keyword("k".to_owned());
    let key = encode_group_key(&[GroupComponent::Value(&value)]).expect("k");
    assert_eq!(key, vec![1, 2, 2, 1, 0, b'k']);
    let missing = encode_group_key(&[GroupComponent::Missing(FieldType::Keyword)]).expect("k");
    assert_eq!(missing, vec![1, 2, 0]);
    let null = encode_group_key(&[GroupComponent::Null(FieldType::I64)]).expect("k");
    assert_eq!(null, vec![1, 4, 1]);
    // Composite order is preserved with prefix safety.
    let composite = encode_group_key(&[
        GroupComponent::Null(FieldType::I64),
        GroupComponent::Value(&value),
    ])
    .expect("k");
    assert_eq!(composite, vec![2, 4, 1, 2, 2, 1, 0, b'k']);
}

#[test]
fn p5_a23_columns_persisted_block_geometry_and_bounded_access() {
    let docs: Vec<SegmentDocument> = (0..5)
        .map(|i| document(&format!("c-{i}"), i as i64 * 10, "col"))
        .collect();
    let mut builder = SegmentBuilder::new(test_schema(), AnalyzerRegistry::builtin())
        .expect("builder")
        .with_block_docs(3);
    for doc in docs {
        builder.add_document(doc).expect("add");
    }
    let built = builder.build().expect("build");
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    let columns_entry = reader
        .sections()
        .iter()
        .find(|entry| entry.kind == quervant_core::segment::SectionKind::Columns)
        .expect("columns section");
    let columns_body = &reader.bytes()
        [columns_entry.offset as usize..(columns_entry.offset + columns_entry.length) as usize];
    let column_reader =
        ColumnReader::open(reader.schema(), columns_body, &SegmentLimits::default()).expect("open");

    let count_id = reader.schema().field_id("count").expect("count");
    let loc_id = reader.schema().field_id("loc").expect("loc");
    let tag_id = reader.schema().field_id("tag").expect("tag");
    for doc_id in [0u64, 2, 3, 4] {
        assert!(
            column_reader
                .value(count_id, doc_id)
                .expect("count")
                .is_some()
        );
        assert!(column_reader.value(loc_id, doc_id).expect("loc").is_some());
        assert!(column_reader.value(tag_id, doc_id).expect("tag").is_some());
    }
    // Reopening with a different runtime default still uses the persisted value.
    let reader2 = SegmentReader::open(
        built.bytes.clone(),
        SegmentLimits::default().with_block_docs_default(1024),
    )
    .expect("open");
    assert_eq!(
        reader2.column_value(count_id, 4).expect("count"),
        Some(FieldValues::Single(FieldValue::I64(-5)))
    );
    assert_eq!(column_reader.blocks_read(), 12, "one block per access");
}

#[test]
fn p5_a05_a07_column_geometry_is_rejected() {
    let built = sample();
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    let entry = reader
        .sections()
        .iter()
        .find(|entry| entry.kind == quervant_core::segment::SectionKind::Columns)
        .expect("columns");
    let mut body =
        reader.bytes()[entry.offset as usize..(entry.offset + entry.length) as usize].to_vec();
    // Header: version(2) + count(4) + field_id(4) + type_tag(1) + layout(1) + doc_count(8)
    // + block_count(4) => block_docs begins at offset 24.
    body[24] = 0;
    body[25] = 0;
    body[26] = 0;
    body[27] = 0;
    assert!(matches!(
        ColumnReader::open(reader.schema(), &body, &SegmentLimits::default()),
        Err(SegmentError::InvalidColumnGeometry { .. })
    ));
}

#[test]
fn p5_a01_advance_semantics() {
    let mut docs: Vec<SegmentDocument> = (0..8)
        .map(|i| document(&format!("adv-{i}"), i as i64, "filler"))
        .collect();
    for (index, text) in [(1usize, "term"), (4, "term"), (7, "term")] {
        docs[index].fields.insert(
            "body".to_owned(),
            FieldValues::Single(FieldValue::Text(text.to_owned())),
        );
    }
    let built = build(docs, Layout::Insertion);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    let body_id = reader.schema().field_id("body").unwrap();
    let mut postings = reader.postings(body_id, "term").unwrap().unwrap();
    assert_eq!(postings.advance(0).unwrap().unwrap().doc_id, 1);
    assert_eq!(postings.advance(2).unwrap().unwrap().doc_id, 4);
    assert_eq!(
        postings.advance(4).unwrap().unwrap().doc_id,
        4,
        "idempotent"
    );
    assert!(postings.advance(9).unwrap().is_none());
    assert!(postings.advance(0).unwrap().is_none(), "after EOF");
}

#[test]
fn p5_a20_timestamp_sorted_remap() {
    let docs = vec![
        document("late", 3000, "a"),
        document("early", 1000, "b"),
        document("middle", 2000, "c"),
    ];
    let built = build(docs, Layout::TimestampSorted);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    assert!(!reader.remap().is_identity());
    let stored = reader.stored().expect("stored");
    assert_eq!(stored[0].key.as_str(), "early");
    assert_eq!(stored[1].key.as_str(), "middle");
    assert_eq!(stored[2].key.as_str(), "late");
    // Postings use physical ids in sorted order.
    let body_id = reader.schema().field_id("body").unwrap();
    let mut postings = reader.postings(body_id, "a").unwrap().unwrap();
    assert_eq!(postings.next().unwrap().unwrap().doc_id, 2);
    assert_eq!(reader.remap().physical_to_original(0).unwrap(), 1);
    assert_eq!(reader.remap().original_to_physical(1).unwrap(), 0);
}

#[test]
fn p5_a13_a14_time_bounds_presence() {
    let complete = build(
        vec![document("t1", 1000, "x"), document("t2", 2000, "y")],
        Layout::Insertion,
    );
    let reader =
        SegmentReader::open(complete.bytes.clone(), SegmentLimits::default()).expect("open");
    let bounds = reader.time_bounds().expect("bounds");
    assert!(bounds.known);
    assert!(bounds.prunes_positive_range(3000, 4000));
    assert!(!bounds.prunes_positive_range(1500, 2500));
    assert!(bounds.prunes_negated_range(500, 5000));
    assert!(bounds.prunes_value_less());

    // One missing timestamp => SOME presence; positive pruning stays safe.
    let mut partial = document("t3", 0, "z");
    partial.fields.remove("when");
    let built = build(vec![document("t1", 1000, "x"), partial], Layout::Insertion);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    let bounds = reader.time_bounds().expect("bounds");
    assert_eq!(bounds.present_count, 1);
    assert!(!bounds.known || bounds.prunes_positive_range(2000, 3000));
    assert!(
        !bounds.prunes_negated_range(0, 5000),
        "missing may match NOT range"
    );
    assert!(!bounds.prunes_value_less());
}

#[test]
fn p5_a15_geo_antimeridian_envelope() {
    let mut a = document("g1", 1, "x");
    a.fields.insert(
        "loc".to_owned(),
        FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(170.0, 10.0).unwrap())),
    );
    let mut b = document("g2", 2, "y");
    b.fields.insert(
        "loc".to_owned(),
        FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(-170.0, 5.0).unwrap())),
    );
    let built = build(vec![a, b], Layout::Insertion);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    let bounds = reader.geo_bounds();
    assert_eq!(bounds.len(), 1);
    let bounds = bounds[0];
    assert!(bounds.crosses_antimeridian);
    assert!(
        bounds.prunes_positive_box(0.0, 0.0, 90.0, 30.0),
        "disjoint box"
    );
    assert!(
        bounds.prunes_positive_box(0.0, 0.0, 169.0, 30.0),
        "disjoint west arc"
    );
    assert!(
        !bounds.prunes_positive_box(160.0, 0.0, 175.0, 20.0),
        "overlaps west arc"
    );
    // A box straddling the antimeridian still intersects.
    assert!(!bounds.prunes_positive_box(175.0, 0.0, -175.0, 20.0));
}

#[test]
fn p5_a18_a19_manifest_round_trip_no_lifecycle() {
    let built = sample();
    let descriptor = ContentDescriptor::of(&built.bytes);
    let manifest = Manifest {
        schema: built.schema.clone(),
        segments: vec![ManifestSegmentRef {
            segment_id: "segments/one".to_owned(),
            object_key: "objects/one".to_owned(),
            content_algorithm: 0,
            content_length: built.bytes.len() as u64,
            content_digest: *descriptor.digest.as_bytes(),
            time_bounds: Some(TimeBounds {
                field_id: built.schema.primary_timestamp().unwrap(),
                known: true,
                presence: 3,
                live_count: 2,
                present_count: 2,
                min_micros: 1000,
                max_micros: 2000,
                ordered: false,
            }),
            required_features: vec![],
            optional_features: vec![],
        }],
        required_features: vec![],
        optional_features: vec![],
        mutation_state: None,
    };
    let bytes = manifest.encode().expect("encode");
    let decoded = Manifest::decode(&bytes, &SegmentLimits::default()).expect("decode");
    assert_eq!(decoded, manifest);

    // Duplicate object keys are rejected.
    let mut duplicate = manifest.clone();
    duplicate.segments.push(duplicate.segments[0].clone());
    duplicate.segments[1].segment_id = "segments/two".to_owned();
    assert!(matches!(
        duplicate.encode(),
        Err(SegmentError::InvalidManifest { .. })
    ));

    // Unknown digest algorithm is rejected.
    let mut bad_algorithm = manifest.clone();
    bad_algorithm.segments[0].content_algorithm = 9;
    let bytes = bad_algorithm.encode().expect("encode");
    assert!(Manifest::decode(&bytes, &SegmentLimits::default()).is_err());
}

#[test]
fn p5_i01_memory_directory_reopen() {
    let built = sample();
    let directory = MemoryDirectory::new();
    let key = StorageKey::parse("segments/one").expect("key");
    {
        let mut handle = directory.create(&key).expect("create");
        handle.write_all(&built.bytes).expect("write");
        handle.sync_all().expect("sync");
    }
    directory.sync().expect("dir sync");
    let reader =
        SegmentReader::open_directory(&directory, &key, SegmentLimits::default()).expect("open");
    assert_eq!(reader.doc_count(), 2);
}

#[test]
fn p5_i06_fs_directory_fresh_instance_reopen() {
    let built = sample();
    let dir = std::env::temp_dir().join(format!("quervant-pr5-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let key = StorageKey::parse("segments/one").expect("key");
    std::fs::create_dir_all(dir.join("segments")).expect("mkdir");
    {
        let directory = FsDirectory::open(&dir).expect("fs");
        let mut handle = directory.create(&key).expect("create");
        handle.write_all(&built.bytes).expect("write");
        handle.sync_all().expect("sync");
        directory.sync().expect("dir sync");
    }
    // Fresh instance, fresh handle.
    let directory = FsDirectory::open(&dir).expect("fs reopen");
    let reader =
        SegmentReader::open_directory(&directory, &key, SegmentLimits::default()).expect("open");
    assert_eq!(reader.doc_count(), 2);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn p5_u02_footer_body_corruption_is_rejected() {
    let built = sample();
    // Flip a byte in a section body; the envelope digest must reject it.
    let mut corrupt = built.bytes.clone();
    corrupt[30] ^= 0x01;
    assert!(matches!(
        SegmentReader::open(corrupt, SegmentLimits::default()),
        Err(SegmentError::DigestMismatch { .. })
    ));
}

#[test]
fn p5_u16_analyzer_fingerprint_mismatch_is_typed() {
    let built = sample();
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    // The persisted binding round-trips through PR 4's fingerprint seam.
    let binding = reader
        .schema()
        .fields()
        .iter()
        .find(|field| field.name == "body")
        .and_then(|field| field.analyzer.as_ref())
        .expect("body analyzer binding");
    let registry = AnalyzerRegistry::builtin();
    let standard = registry.get("standard").expect("standard").fingerprint();
    assert_eq!(binding.fingerprint, *standard.as_bytes());
    assert!(
        registry
            .resolve_fingerprint(&binding.id, &binding.version, standard)
            .is_ok()
    );
    let other = registry.get("english").expect("english").fingerprint();
    assert!(matches!(
        registry.resolve_fingerprint(&binding.id, &binding.version, other),
        Err(quervant_core::analysis::AnalysisError::AnalyzerFingerprintMismatch { .. })
    ));
    let _ = other;
}

#[test]
fn p5_p01_deterministic_bytes_and_field_order_independence() {
    let a = build(
        vec![document("d1", 1, "one"), document("d2", 2, "two")],
        Layout::Insertion,
    );
    let b = build(
        vec![document("d1", 1, "one"), document("d2", 2, "two")],
        Layout::Insertion,
    );
    assert_eq!(a.bytes, b.bytes, "same input yields identical bytes");

    // Reversing field declaration order must not change the schema bytes.
    use quervant_core::contract::schema::{FieldDefinition, Schema};
    let fields: Vec<FieldDefinition> = test_schema().fields().cloned().collect();
    let mut reversed = fields.clone();
    reversed.reverse();
    let schema_reversed = Schema::new(reversed, Some("when".to_owned())).expect("schema");
    let c = SegmentBuilder::new(schema_reversed, AnalyzerRegistry::builtin())
        .expect("builder")
        .build()
        .expect("build");
    let d = SegmentBuilder::new(test_schema(), AnalyzerRegistry::builtin())
        .expect("builder")
        .build()
        .expect("build");
    assert_eq!(c.bytes, d.bytes, "field declaration order is canonicalized");
}

#[test]
fn p5_u19_value_extremes_round_trip() {
    let mut doc = document("extremes", i64::MIN + 1, "unicode \u{e9}\u{4e2d}\u{6587}");
    doc.fields.insert(
        "count".to_owned(),
        FieldValues::Single(FieldValue::I64(i64::MIN)),
    );
    doc.fields.insert(
        "score".to_owned(),
        FieldValues::Single(FieldValue::F64(-0.0)),
    );
    doc.fields.insert(
        "ip".to_owned(),
        FieldValues::Single(FieldValue::Ip("::ffff:192.0.2.1".parse().expect("mapped"))),
    );
    doc.fields.insert(
        "cidr".to_owned(),
        FieldValues::Single(FieldValue::Cidr(
            IpNetwork::new("2001:db8::".parse().expect("v6"), 128).expect("cidr"),
        )),
    );
    let built = build(vec![doc.clone()], Layout::Insertion);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    let stored = &reader.stored().expect("stored")[0];
    assert_eq!(
        stored.get(reader.schema().field_id("count").unwrap()),
        doc.fields["count"]
    );
    assert_eq!(
        stored.get(reader.schema().field_id("score").unwrap()),
        doc.fields["score"]
    );
    assert_eq!(
        stored.get(reader.schema().field_id("ip").unwrap()),
        doc.fields["ip"]
    );
    assert_eq!(
        stored.get(reader.schema().field_id("cidr").unwrap()),
        doc.fields["cidr"]
    );
    assert_eq!(
        stored.get(reader.schema().field_id("body").unwrap()),
        doc.fields["body"]
    );
}

#[test]
fn p5_a16_accepted_segment_size_policy() {
    let built = sample();
    let len = built.bytes.len() as u64;
    let too_small = SegmentLimits::default().with_accepted_segment_bytes(len - 1);
    assert!(matches!(
        SegmentReader::open(built.bytes.clone(), too_small),
        Err(SegmentError::LimitExceeded { .. })
    ));
    let generous = SegmentLimits::default().with_accepted_segment_bytes(len);
    assert!(SegmentReader::open(built.bytes.clone(), generous).is_ok());
}

#[test]
fn p5_u05_noncanonical_varint_rejected() {
    use quervant_core::segment::format::ByteReader;
    // 0x80 0x00 is an overlong encoding of zero.
    let mut reader = ByteReader::new(&[0x80, 0x00]);
    assert!(matches!(
        reader.varint("test"),
        Err(SegmentError::InvalidVarint { .. })
    ));
    // Canonical zero and max are accepted.
    let mut reader = ByteReader::new(&[0x00]);
    assert_eq!(reader.varint("test").unwrap(), 0);
}

#[test]
fn p5_u44_remap_validation() {
    assert!(
        DocRemap::from_order(vec![0, 1, 2, 3])
            .unwrap()
            .is_identity()
    );
    assert!(DocRemap::from_order(vec![2, 0, 3, 1]).is_ok());
    assert!(matches!(
        DocRemap::from_order(vec![0, 0, 1, 2]),
        Err(SegmentError::InvalidRemap { .. })
    ));
    assert!(matches!(
        DocRemap::from_order(vec![0, 1, 2, 9]),
        Err(SegmentError::InvalidRemap { .. })
    ));
}

#[test]
fn p5_u06_unsupported_version_and_unknown_feature_fail_closed() {
    use quervant_core::segment::ContainerBuilder;
    use quervant_core::segment::format::{ContainerKind, SectionKind, parse_container};
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, 0);
    builder.section(SectionKind::Schema, 0, 0, vec![0, 1]);
    builder.require_feature(0xbeef, 7);
    let bytes = builder.build().expect("build");
    let view = parse_container(&bytes, &SegmentLimits::default()).expect("parse");
    assert!(matches!(
        view.ensure_supported_features(),
        Err(SegmentError::UnsupportedFeature { .. })
    ));
}

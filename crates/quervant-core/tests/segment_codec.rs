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

/// PERF-06-A2 I01: a real built segment's positional postings decode to the same
/// ordered `(doc_id, freq)` sequence through the full and doc/freq-only readers,
/// while the full reader still supplies real positions.
#[test]
fn a2_i01_real_segment_docfreq_matches_full() {
    let built = sample();
    let descriptor = ContentDescriptor::of(&built.bytes);
    let reader = SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
    reader
        .verify_content_descriptor(&descriptor)
        .expect("descriptor verifies");
    let body_id = reader.schema().field_id("body").expect("body");

    // Two independent cursors over the same immutable postings extent. The
    // `standard` analyzer only NFC-normalizes (it does not case-fold), so
    // "Hello world hello" indexes `hello` once and `Hello`/`world` separately.
    let mut full = reader
        .postings(body_id, "hello")
        .expect("postings")
        .expect("term present");
    assert!(full.is_positional());
    assert_eq!(full.posting_doc_count(), 1);
    let mut full_records = Vec::new();
    while let Some(posting) = full.next().expect("decode") {
        assert_eq!(posting.occurrences.len() as u64, posting.freq);
        assert!(
            posting
                .occurrences
                .iter()
                .all(|occurrence| occurrence.position_length >= 1),
            "full reader must supply real positions"
        );
        full_records.push((posting.doc_id, posting.freq));
    }
    assert_eq!(full_records, vec![(0u64, 1u64)]);

    let mut lean = reader
        .postings(body_id, "hello")
        .expect("postings")
        .expect("term present")
        .into_doc_freq();
    let mut lean_records = Vec::new();
    while let Some(posting) = lean.next().expect("decode") {
        lean_records.push((posting.doc_id, posting.freq));
    }
    assert_eq!(lean_records, full_records);

    // A second, independently opened lean cursor yields the same records and EOF.
    let mut reread = reader
        .postings(body_id, "hello")
        .expect("postings")
        .expect("term present")
        .into_doc_freq();
    assert_eq!(
        reread.next().expect("decode").map(|p| (p.doc_id, p.freq)),
        Some((0, 1))
    );
    assert!(reread.next().expect("eof").is_none());

    // A two-posting positional term keeps identical order and frequencies.
    let mut multi_full = reader
        .postings(body_id, "world")
        .expect("postings")
        .expect("term present");
    let mut multi_full_records = Vec::new();
    while let Some(posting) = multi_full.next().expect("decode") {
        assert!(!posting.occurrences.is_empty());
        multi_full_records.push((posting.doc_id, posting.freq));
    }
    let mut multi_lean = reader
        .postings(body_id, "world")
        .expect("postings")
        .expect("term present")
        .into_doc_freq();
    let mut multi_lean_records = Vec::new();
    while let Some(posting) = multi_lean.next().expect("decode") {
        multi_lean_records.push((posting.doc_id, posting.freq));
    }
    assert_eq!(multi_full_records, vec![(0u64, 1u64), (1u64, 1u64)]);
    assert_eq!(multi_lean_records, multi_full_records);

    assert!(
        reader
            .postings(body_id, "absent_a2")
            .expect("lookup")
            .is_none()
    );
}

// ---------------------------------------------------------------------------
// PERF-06-A3: split postings streams through the real builder/reader path.
// ---------------------------------------------------------------------------

const A3_BLOCK_DOCS: usize = 128;
const A3_HEADER_BYTES: usize = 56;

fn a3_u32(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().expect("u32 field"))
}

fn a3_u64(bytes: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(bytes[offset..offset + 8].try_into().expect("u64 field"))
}

fn a3_split_postings_body(bytes: &[u8]) -> Vec<u8> {
    use quervant_core::segment::{SectionKind, parse_container};
    let view = parse_container(bytes, &SegmentLimits::default()).expect("container");
    view.body(SectionKind::Postings)
        .expect("postings section")
        .to_vec()
}

#[test]
fn a3_i01_real_segment_split_postings_extents() {
    use quervant_core::segment::format::FEATURE_SPLIT_POSTINGS;

    for count in [0usize, 127, 128, 129, 257] {
        let docs: Vec<SegmentDocument> = (0..count)
            .map(|index| document(&format!("k{index:05}"), index as i64, "alpha"))
            .collect();
        let built = build(docs, Layout::Insertion);
        let reader =
            SegmentReader::open(built.bytes.clone(), SegmentLimits::default()).expect("open");
        assert_eq!(reader.doc_count(), count as u64);
        let has_split = reader
            .required_features()
            .iter()
            .any(|(id, version)| (*id, *version) == (FEATURE_SPLIT_POSTINGS, 1));
        let body_id = reader.schema().field_id("body").expect("body field");
        if count == 0 {
            assert!(!has_split, "an empty segment declares no split feature");
            assert!(reader.dictionary().is_none());
            assert!(reader.postings(body_id, "alpha").expect("lookup").is_none());
            continue;
        }
        assert!(
            has_split,
            "a non-empty lexical segment requires the split feature"
        );

        let postings_body = a3_split_postings_body(&built.bytes);
        let dictionary = reader.dictionary().expect("dictionary");
        let mut extent_end = 0u64;
        for (field_id, entries) in dictionary.fields() {
            for entry in entries {
                assert_eq!(entry.postings_offset, extent_end, "contiguous extents");
                let start = entry.postings_offset as usize;
                let marker = postings_body[start];
                assert!(
                    marker == 2 || marker == 3,
                    "field {field_id} term {:?} marker {marker}",
                    entry.term
                );
                assert_eq!(a3_u32(&postings_body, start + 4), A3_BLOCK_DOCS as u32);
                assert_eq!(
                    a3_u64(&postings_body, start + 16),
                    entry.doc_freq,
                    "header posting count equals dictionary doc_freq"
                );
                assert!(
                    a3_u64(&postings_body, start + 24) >= entry.doc_freq,
                    "frequency total is at least the posting count"
                );
                let block_count = a3_u32(&postings_body, start + 8) as u64;
                assert_eq!(block_count, entry.doc_freq.div_ceil(A3_BLOCK_DOCS as u64));
                let doc_len = a3_u64(&postings_body, start + 32);
                let freq_len = a3_u64(&postings_body, start + 40);
                let pos_len = a3_u64(&postings_body, start + 48);
                extent_end = entry
                    .postings_offset
                    .checked_add(entry.postings_length)
                    .expect("extent");
                assert_eq!(
                    entry.postings_length,
                    A3_HEADER_BYTES as u64 + doc_len + freq_len + pos_len + block_count * 40,
                    "term extent is exactly the declared payload"
                );
            }
        }
        assert_eq!(extent_end, postings_body.len() as u64, "no trailing bytes");

        // Every document contains "alpha" exactly once.
        let entry = reader
            .dictionary()
            .expect("dictionary")
            .lookup(body_id, "alpha")
            .expect("alpha term");
        assert_eq!(entry.doc_freq, count as u64);

        let mut full = reader.postings_for_entry(entry).expect("full postings");
        let mut full_records = Vec::new();
        while let Some(posting) = full.next().expect("decode") {
            assert_eq!(posting.freq, 1);
            assert_eq!(posting.occurrences.len(), 1);
            assert_eq!(posting.occurrences[0].position, 0);
            full_records.push(posting.doc_id);
        }
        let expected: Vec<u64> = (0..count as u64).collect();
        assert_eq!(full_records, expected);

        let mut lean = reader
            .postings_for_entry(entry)
            .expect("lean postings")
            .into_doc_freq();
        let mut lean_records = Vec::new();
        while let Some(posting) = lean.next().expect("decode") {
            lean_records.push(posting.doc_id);
        }
        assert_eq!(lean_records, expected);
    }

    // A term that is absent from a non-empty segment is simply not found.
    let built = build(vec![document("k0", 0, "alpha")], Layout::Insertion);
    let reader = SegmentReader::open(built.bytes, SegmentLimits::default()).expect("open");
    let body_id = reader.schema().field_id("body").expect("body field");
    assert!(
        reader
            .postings(body_id, "absent_a3")
            .expect("lookup")
            .is_none()
    );
}

/// Rebuild a segment container with recomputed section digests.
fn a3_rebuild_segment(
    original: &[u8],
    replace: &[(quervant_core::segment::SectionKind, Vec<u8>)],
    drop_features: &[(u16, u16)],
) -> Vec<u8> {
    use quervant_core::segment::{ContainerBuilder, parse_container};
    let limits = SegmentLimits::default();
    let view = parse_container(original, &limits).expect("container");
    let mut builder = ContainerBuilder::new(view.kind(), view.doc_count());
    for (feature, version) in view.required_features() {
        if drop_features.contains(&(*feature, *version)) {
            continue;
        }
        builder.require_feature(*feature, *version);
    }
    for (feature, version) in view.optional_features() {
        builder.optional_feature(*feature, *version);
    }
    for section in view.sections() {
        let body = match replace.iter().find(|(kind, _)| *kind == section.kind) {
            Some((_, body)) => body.clone(),
            None => {
                let start = section.offset as usize;
                original[start..start + section.length as usize].to_vec()
            }
        };
        builder.section(section.kind, section.flags, section.aux, body);
    }
    builder.build().expect("rebuilt container")
}

#[test]
fn a3_i03_legacy_split_parity_and_malformed_body() {
    use quervant_core::segment::dictionary::{DictionaryEntry, encode_dictionary};
    use quervant_core::segment::format::FEATURE_SPLIT_POSTINGS;
    use quervant_core::segment::postings::{Posting, encode_postings_block};
    use quervant_core::segment::{SectionKind, parse_container};

    let limits = SegmentLimits::default();
    let built = build(
        vec![
            document("k0", 1000, "alpha beta gamma"),
            document("k1", 2000, "alpha alpha"),
            document("k2", 3000, "beta"),
        ],
        Layout::Insertion,
    );
    let split_reader = SegmentReader::open(built.bytes.clone(), limits).expect("open split");
    let postings_body = a3_split_postings_body(&built.bytes);

    // Re-encode every term with the frozen legacy encoder, keeping the same
    // logical (field, term) order and rebuilding exact dictionary extents.
    let mut legacy_body: Vec<u8> = Vec::new();
    let mut legacy_fields: Vec<(u32, Vec<DictionaryEntry>)> = Vec::new();
    for (field_id, entries) in split_reader.dictionary().expect("dictionary").fields() {
        let mut rebuilt = Vec::with_capacity(entries.len());
        for entry in entries {
            let mut postings: Vec<Posting> = Vec::new();
            let mut cursor = split_reader
                .postings_for_entry(entry)
                .expect("split postings");
            while let Some(posting) = cursor.next().expect("decode") {
                postings.push(posting);
            }
            let offset = legacy_body.len() as u64;
            let block = encode_postings_block(split_reader.doc_count(), &postings, &limits)
                .expect("legacy encode");
            legacy_body.extend_from_slice(&block);
            rebuilt.push(DictionaryEntry {
                term: entry.term.clone(),
                doc_freq: entry.doc_freq,
                postings_offset: offset,
                postings_length: block.len() as u64,
            });
        }
        legacy_fields.push((*field_id, rebuilt));
    }
    let dictionary_body = encode_dictionary(&legacy_fields, &limits).expect("dictionary");

    let legacy_bytes = a3_rebuild_segment(
        &built.bytes,
        &[
            (SectionKind::Postings, legacy_body),
            (SectionKind::Dictionary, dictionary_body),
        ],
        &[(FEATURE_SPLIT_POSTINGS, 1)],
    );
    let legacy_reader = SegmentReader::open(legacy_bytes.clone(), limits).expect("open legacy");
    // Structural size evidence only: same logical corpus, both codecs. No timing.
    println!(
        "PERF-06-A3 complete segment sizes (3 documents): split={} legacy={}",
        built.bytes.len(),
        legacy_bytes.len()
    );
    let view = parse_container(&legacy_bytes, &limits).expect("container");
    assert!(
        !view
            .required_features()
            .iter()
            .any(|(id, version)| (*id, *version) == (FEATURE_SPLIT_POSTINGS, 1))
    );

    // Logical parity for every term in the segment.
    for (field_id, entries) in split_reader.dictionary().expect("dictionary").fields() {
        for entry in entries {
            let mut split_cursor = split_reader
                .postings_for_entry(entry)
                .expect("split postings");
            let mut split_records = Vec::new();
            while let Some(posting) = split_cursor.next().expect("decode") {
                split_records.push(posting);
            }
            let legacy_entry = legacy_reader
                .dictionary()
                .expect("legacy dictionary")
                .lookup(*field_id, &entry.term)
                .expect("legacy term");
            let mut legacy_cursor = legacy_reader
                .postings_for_entry(legacy_entry)
                .expect("legacy postings");
            let mut legacy_records = Vec::new();
            while let Some(posting) = legacy_cursor.next().expect("decode") {
                legacy_records.push(posting);
            }
            assert_eq!(
                split_records, legacy_records,
                "field {field_id} term {:?} logical parity",
                entry.term
            );
        }
    }

    // Malformed split payload inside a fully valid rebuilt container: corrupt the
    // position-length field of one positional term's first occurrence.
    let body_id = split_reader.schema().field_id("body").expect("body field");
    let corrupted = {
        let entry = split_reader
            .dictionary()
            .expect("dictionary")
            .lookup(body_id, "alpha")
            .expect("alpha term");
        let start = entry.postings_offset as usize;
        let mut body = postings_body.clone();
        let doc_len = a3_u64(&body, start + 32) as usize;
        let freq_len = a3_u64(&body, start + 40) as usize;
        let positions_start = start + A3_HEADER_BYTES + doc_len + freq_len;
        // First occurrence: position delta, then position length.
        body[positions_start + 1] = 0;
        body
    };
    let malformed = a3_rebuild_segment(&built.bytes, &[(SectionKind::Postings, corrupted)], &[]);
    let reader = SegmentReader::open(malformed, limits).expect("malformed container opens");
    let entry = reader
        .dictionary()
        .expect("dictionary")
        .lookup(body_id, "alpha")
        .expect("alpha term");
    let mut full = reader.postings_for_entry(entry).expect("reader constructs");
    match full.next() {
        Err(SegmentError::Corrupt { context, detail }) => {
            assert_eq!(context, "postings");
            assert_eq!(detail, "zero position length");
        }
        other => panic!("unexpected full result: {other:?}"),
    }
    let mut lean = reader
        .postings_for_entry(entry)
        .expect("reader constructs")
        .into_doc_freq();
    assert!(matches!(lean.next(), Err(SegmentError::Corrupt { .. })));

    // An unselected, clean term still decodes: corruption is surfaced lazily and
    // only for the record that is actually traversed.
    let beta = reader
        .dictionary()
        .expect("dictionary")
        .lookup(body_id, "beta")
        .expect("beta term");
    let mut beta_cursor = reader.postings_for_entry(beta).expect("beta postings");
    let mut beta_docs = Vec::new();
    while let Some(posting) = beta_cursor.next().expect("beta decode") {
        beta_docs.push(posting.doc_id);
    }
    assert_eq!(beta_docs, vec![0, 2]);
}

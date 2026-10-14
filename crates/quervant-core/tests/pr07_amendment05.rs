//! PR 7 Amendment 05 — persistent BM25 field norms and query-proportional stats.
//!
//! Exercises the real segment builder/reader and search path. Independent oracles
//! compute expected norms/statistics from the fixture input.

mod common;

use std::sync::Arc;

use common::{Pr07Doc, TempDir, pr07_registry, pr07_schema};
use quervant_core::analysis::NeverCancel;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue, Timestamp};
use quervant_core::index::Index;
use quervant_core::search::{LexicalSearcher, SearchError, SearchLimits};
use quervant_core::segment::format::{FEATURE_BASELINE, FEATURE_FIELD_NORMS, FEATURE_STORED};
use quervant_core::segment::{
    ContainerBuilder, ContainerKind, Layout, SegmentBuilder, SegmentDocument, SegmentError,
    SegmentLimits, SegmentReader, scoring_field_ids,
};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};

fn doc(key: &str, title: Option<&str>, body: Option<&str>) -> SegmentDocument {
    let mut document = SegmentDocument::new(DocumentKey::new(key).unwrap());
    if let Some(title) = title {
        document
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text(title.to_owned())),
            )
            .unwrap();
    }
    if let Some(body) = body {
        document
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text(body.to_owned())),
            )
            .unwrap();
    }
    document
}

fn reader_for(docs: Vec<SegmentDocument>) -> SegmentReader {
    reader_for_schema(docs, pr07_schema())
}

fn reader_for_schema(docs: Vec<SegmentDocument>, schema: Schema) -> SegmentReader {
    let mut builder = SegmentBuilder::new(schema, pr07_registry()).unwrap();
    for document in docs {
        builder.add_document(document).unwrap();
    }
    let built = builder.build().unwrap();
    SegmentReader::open(built.bytes, SegmentLimits::default()).unwrap()
}

// A5-T01 — a new segment declares the section and the required feature.
#[test]
fn a5_t01_new_segment_declares_norms() {
    let reader = reader_for(vec![doc("a", Some("hello"), None)]);
    assert!(reader.field_norms().is_some());
    assert!(
        reader
            .required_features()
            .contains(&(FEATURE_FIELD_NORMS, 1))
    );
    let section_count = reader
        .sections()
        .iter()
        .filter(|entry| entry.kind == quervant_core::segment::SectionKind::FieldNorms)
        .count();
    assert_eq!(section_count, 1);
}

// A5-T02/T03/T04 — norms count emitted tokens (repetitions, stopword removal).
#[test]
fn a5_t02_t04_norms_count_emitted_tokens() {
    let reader = reader_for(vec![
        doc("a", Some("alpha alpha beta"), None),
        doc("b", Some("the quick brown"), None),
        doc("c", Some(""), None),
    ]);
    let norms = reader.field_norms().unwrap();
    let title = reader.schema().field_id("title").unwrap();
    let lengths = norms.field(title).unwrap();
    assert_eq!(lengths.length(0).unwrap(), 3, "repeated term counts twice");
    assert_eq!(lengths.length(1).unwrap(), 2, "stopword removed");
    assert_eq!(lengths.length(2).unwrap(), 0, "empty value has zero tokens");
    assert_eq!(lengths.total_token_count(), 5);
    assert_eq!(lengths.documents_with_tokens(), 2);

    // Postings agree for the repeated term: freq 2 in one doc.
    let mut postings = reader.postings(title, "alpha").unwrap().unwrap();
    let posting = postings.next().unwrap().unwrap();
    assert_eq!(posting.freq, 2);
    assert!(postings.next().unwrap().is_none());
}

// A5-T05 — two scoring fields, one absent on some docs.
#[test]
fn a5_t05_two_fields_absent() {
    let reader = reader_for(vec![
        doc("a", Some("alpha beta"), None),
        doc("b", None, Some("gamma delta")),
    ]);
    let norms = reader.field_norms().unwrap();
    let title = reader.schema().field_id("title").unwrap();
    let body = reader.schema().field_id("body").unwrap();
    assert_eq!(norms.field(title).unwrap().length(0).unwrap(), 2);
    assert_eq!(norms.field(title).unwrap().length(1).unwrap(), 0);
    assert_eq!(norms.field(body).unwrap().length(0).unwrap(), 0);
    assert_eq!(norms.field(body).unwrap().length(1).unwrap(), 2);
}

// A5-T06 — timestamp-sorted remap: norms follow physical order.
#[test]
fn a5_t06_timestamp_sorted_remap() {
    let schema = Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("whitespace"),
            FieldDefinition::new(
                "ts",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
        ],
        Some("ts".to_owned()),
    )
    .unwrap();
    let mut first = SegmentDocument::new(DocumentKey::new("a").unwrap());
    first
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("one two three".to_owned())),
        )
        .unwrap();
    first
        .insert(
            "ts",
            FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(2000))),
        )
        .unwrap();
    let mut second = SegmentDocument::new(DocumentKey::new("b").unwrap());
    second
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("one".to_owned())),
        )
        .unwrap();
    second
        .insert(
            "ts",
            FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(1000))),
        )
        .unwrap();
    let mut builder = SegmentBuilder::new(schema, pr07_registry())
        .unwrap()
        .with_layout(Layout::TimestampSorted);
    builder.add_document(first).unwrap();
    builder.add_document(second).unwrap();
    let built = builder.build().unwrap();
    let reader = SegmentReader::open(built.bytes, SegmentLimits::default()).unwrap();
    let title = reader.schema().field_id("title").unwrap();
    let norms = reader.field_norms().unwrap().field(title).unwrap();
    // Physical order is b(1000) then a(2000).
    assert_eq!(norms.length(0).unwrap(), 1);
    assert_eq!(norms.length(1).unwrap(), 3);
}

// A5-T07 — deterministic bytes for identical input.
#[test]
fn a5_t07_deterministic_bytes() {
    let build = || {
        reader_for(vec![
            doc("a", Some("hello world"), Some("body text")),
            doc("b", Some("hello"), None),
        ])
        .bytes()
        .to_vec()
    };
    assert_eq!(build(), build());
}

// A5-T08/I04 — the checked-in legacy golden fixture is unchanged and has no norms.
#[test]
fn a5_t08_legacy_golden_has_no_norms() {
    const GOLDEN: &[u8] = include_bytes!("fixtures/segment/golden.seg");
    let reader = SegmentReader::open(GOLDEN.to_vec(), SegmentLimits::default()).unwrap();
    assert!(reader.field_norms().is_none());
    assert!(
        !reader
            .required_features()
            .iter()
            .any(|(id, _)| *id == FEATURE_FIELD_NORMS)
    );
    assert_eq!(reader.doc_count(), 2);
}

// A5-T10 — section/feature presence mismatch is corruption, never a fallback.
#[test]
fn a5_t10_section_feature_mismatch_is_corrupt() {
    let schema = pr07_schema();
    let registry = pr07_registry();
    let bindings =
        quervant_core::analysis::SchemaAnalyzerBindings::resolve(&schema, &registry).unwrap();
    let codec = quervant_core::segment::CodecSchema::from_contract(&schema, &bindings).unwrap();

    let build = |with_section: bool, with_feature: bool| {
        let mut builder = ContainerBuilder::new(ContainerKind::Segment, 0);
        builder.require_feature(FEATURE_BASELINE, 1);
        builder.require_feature(FEATURE_STORED, 1);
        if with_feature {
            builder.require_feature(FEATURE_FIELD_NORMS, 1);
        }
        builder.section(
            quervant_core::segment::SectionKind::Schema,
            0,
            0,
            codec.encode().unwrap(),
        );
        if with_section {
            builder.section(
                quervant_core::segment::SectionKind::FieldNorms,
                0,
                0,
                vec![],
            );
        }
        builder.build().unwrap()
    };

    // Section without feature.
    assert!(matches!(
        SegmentReader::open(build(true, false), SegmentLimits::default()),
        Err(SegmentError::Corrupt { .. })
    ));
    // Feature without section.
    assert!(matches!(
        SegmentReader::open(build(false, true), SegmentLimits::default()),
        Err(SegmentError::Corrupt { .. })
    ));
}

// A5-T22/T23/I07 — a rare query does not scan unrelated postings or dictionary terms.
#[test]
fn a5_t22_rare_term_is_query_proportional() {
    // A large background vocabulary plus one rare sentinel in a single document.
    let docs: Vec<SegmentDocument> = (0..400)
        .map(|index| {
            let mut text = format!("w{index:04} w{:04} w{:04}", index + 1000, index + 2000);
            if index == 0 {
                text.push_str(" rare_sentinel_zzz");
            }
            doc(&format!("d{index:04}"), Some(&text), None)
        })
        .collect();
    let snapshot = {
        // Build via the real writer so search uses production snapshots.
        let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
        let index = Index::create(Arc::clone(&directory), pr07_schema(), pr07_registry()).unwrap();
        let mut writer = index.writer().unwrap();
        for segment_doc in &docs {
            let mut document =
                quervant_core::contract::document::Document::new(segment_doc.key.clone());
            for (name, values) in &segment_doc.fields {
                document.insert(name.clone(), values.clone()).unwrap();
            }
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
        drop(writer);
        Index::open_existing(directory, pr07_schema(), pr07_registry())
            .unwrap()
            .snapshot()
    };
    let schema = pr07_schema();
    let registry = pr07_registry();
    let search = |limits: SearchLimits| {
        LexicalSearcher::new(&snapshot, &schema, &registry, limits).search(
            &Query::Term {
                field: "title".into(),
                value: FieldValue::Text("rare_sentinel_zzz".into()),
            },
            TopK::new(10).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
    };

    // Only the rare term's single posting may be scanned.
    assert!(
        search(
            SearchLimits::default()
                .with_max_scanned_posting_occurrences(1)
                .unwrap()
        )
        .is_ok()
    );
    assert!(matches!(
        search(
            SearchLimits::default()
                .with_max_scanned_posting_occurrences(1)
                .unwrap()
                .with_max_dictionary_terms_examined(1)
                .unwrap()
        ),
        Err(SearchError::ResourceLimit { .. })
    ));
    // A small dictionary-probe budget suffices (binary search), far below the
    // ~1200-term vocabulary that an all-terms scan would need.
    assert!(
        search(
            SearchLimits::default()
                .with_max_dictionary_terms_examined(40)
                .unwrap()
        )
        .is_ok()
    );
    // Sanity: the rare term matches exactly one document.
    let response = search(SearchLimits::default()).unwrap();
    assert_eq!(response.total_hits, 1);
    assert_eq!(response.hits[0].key.as_str(), "d0000");
}

// A5-I06/T17 — BM25 parity with an independent oracle across two fields.
#[test]
fn a5_t17_bm25_parity_oracle() {
    // title: whitespace-analyzed repeated terms; check score against the formula.
    let corpus = [
        ("a", "alpha alpha beta"),
        ("b", "alpha beta beta"),
        ("c", "gamma"),
    ];
    let reader = reader_for(
        corpus
            .iter()
            .map(|(key, title)| doc(key, Some(title), None))
            .collect(),
    );
    let title = reader.schema().field_id("title").unwrap();
    let norms = reader.field_norms().unwrap().field(title).unwrap();
    assert_eq!(norms.length(0).unwrap(), 3);
    assert_eq!(norms.length(1).unwrap(), 3);
    assert_eq!(norms.length(2).unwrap(), 1);
    assert_eq!(norms.total_token_count(), 7);

    // Independent BM25 for "alpha": n=3, df=2, dl/doc as above, avgdl=7/3.
    let n = 3u64;
    let df = 2u64;
    let avgdl = 7.0f64 / 3.0;
    let reference = |tf: u64, dl: u64| {
        let tf = tf as f64;
        let df_f = df as f64;
        let n_f = n as f64;
        let dl_f = dl as f64;
        let idf = (1.0 + (n_f - df_f + 0.5) / (df_f + 0.5)).ln();
        idf * (tf * (1.0 + 1.2)) / (tf + 1.2 * (1.0 - 0.75 + 0.75 * dl_f / avgdl))
    };
    let expected_a = reference(2, 3);
    let expected_b = reference(1, 3);

    // Search through the production path on a committed snapshot.
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), pr07_schema(), pr07_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    for (key, title) in corpus {
        writer
            .insert(Pr07Doc::new(key).title(title).n(1).build())
            .unwrap();
    }
    writer.commit().unwrap();
    drop(writer);
    let committed = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let snapshot = committed.snapshot();
    let response = LexicalSearcher::new(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        SearchLimits::default(),
    )
    .search(
        &Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        TopK::new(10).unwrap(),
        &Budgets::new(),
        &NeverCancel,
    )
    .unwrap();
    let scores: std::collections::BTreeMap<_, _> = response
        .hits
        .iter()
        .map(|hit| (hit.key.as_str().to_owned(), hit.score))
        .collect();
    assert!((scores["a"] - expected_a).abs() < 1e-10, "{:?}", scores);
    assert!((scores["b"] - expected_b).abs() < 1e-10, "{:?}", scores);
    assert_eq!(response.total_hits, 2);
}

// A5-T25 — cancellation on the stats/leaf path returns typed Cancelled.
#[test]
fn a5_t25_cancellation() {
    use quervant_core::analysis::CancellationFlag;
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(Arc::clone(&directory), pr07_schema(), pr07_registry()).unwrap();
    let mut writer = index.writer().unwrap();
    writer
        .insert(Pr07Doc::new("a").title("alpha beta").n(1).build())
        .unwrap();
    writer.commit().unwrap();
    drop(writer);
    let committed = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
    let snapshot = committed.snapshot();
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let result = LexicalSearcher::new(
        &snapshot,
        &pr07_schema(),
        &pr07_registry(),
        SearchLimits::default(),
    )
    .search(
        &Query::MatchAll,
        TopK::new(10).unwrap(),
        &Budgets::new(),
        &cancel,
    );
    assert!(matches!(result, Err(SearchError::Cancelled)));
}

// A5-T29/T30/I10 — memory and filesystem commit/reopen preserve norms and results.
#[test]
fn a5_t29_memory_and_fs_lifecycle() {
    let batches = || {
        vec![
            vec![
                Pr07Doc::new("a")
                    .title("alpha beta")
                    .body(vec!["rust"])
                    .n(1)
                    .build(),
                Pr07Doc::new("b").title("gamma").n(2).build(),
            ],
            vec![
                Pr07Doc::new("c")
                    .title("alpha")
                    .body(vec!["rust rust"])
                    .n(3)
                    .build(),
            ],
        ]
    };
    let query = Query::Or(vec![
        Query::Term {
            field: "title".into(),
            value: FieldValue::Text("alpha".into()),
        },
        Query::Term {
            field: "body".into(),
            value: FieldValue::Text("rust".into()),
        },
    ]);

    let run = |directory: Arc<dyn Directory>| -> (u64, Vec<String>, Option<u64>) {
        let index = Index::create(Arc::clone(&directory), pr07_schema(), pr07_registry()).unwrap();
        let mut writer = index.writer().unwrap();
        for batch in batches() {
            for document in batch {
                writer.insert(document).unwrap();
            }
            writer.flush().unwrap();
        }
        writer.commit().unwrap();
        drop(writer);
        let reopened = Index::open_existing(directory, pr07_schema(), pr07_registry()).unwrap();
        let snapshot = reopened.snapshot();
        // Norms survive reopen for every segment.
        for index in 0..snapshot.segment_count() {
            let guard = snapshot.open_segment_reader(index).unwrap();
            assert!(guard.reader().field_norms().is_some());
        }
        let response = LexicalSearcher::new(
            &snapshot,
            &pr07_schema(),
            &pr07_registry(),
            SearchLimits::default(),
        )
        .search(
            &query,
            TopK::new(10).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
        .unwrap();
        (
            response.total_hits,
            response
                .hits
                .iter()
                .map(|hit| hit.key.as_str().to_owned())
                .collect(),
            response.generation,
        )
    };

    let memory = run(Arc::new(MemoryDirectory::new()));
    let dir = TempDir::new("pr07-a5-lifecycle");
    let fs = run(Arc::new(FsDirectory::open(dir.path()).unwrap()));
    assert_eq!(memory.0, 2);
    assert_eq!(memory.1, fs.1);
    assert_eq!(memory.0, fs.0);
}

// A5-I02 — scoring field ids are exactly the indexed Text/Keyword fields.
#[test]
fn a5_scoring_field_ids_match_schema() {
    let schema = pr07_schema();
    let registry = pr07_registry();
    let bindings =
        quervant_core::analysis::SchemaAnalyzerBindings::resolve(&schema, &registry).unwrap();
    let codec = quervant_core::segment::CodecSchema::from_contract(&schema, &bindings).unwrap();
    let ids = scoring_field_ids(&codec);
    assert_eq!(ids.len(), 5, "title, body, host, tags, raw");
    assert!(ids.windows(2).all(|pair| pair[0] < pair[1]));
}

//! PR 15G-B — real local access parity for validated STORED/DOC_KEYS offsets.
//!
//! The selective offset directories are crate-private, so this suite exercises
//! the public query/projection/stored/key boundary and compares it with an
//! independently opened unmetered `SegmentReader::open` over the same committed
//! segment bytes. Private admission/fallback witnesses live in crate tests.

mod pr14_common;
mod pr15a_common;

use std::collections::BTreeMap;
use std::sync::Arc;

use pr14_common::{
    Bound, FieldValue, Query, Sort, SortDirection, SortField, TopK, registry, schema,
};
use pr15a_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{DocumentKey, FieldValues, MutationRequest};
use quervant_core::contract::result::Projection;
use quervant_core::index::{Index, IndexLimits, ReaderSnapshot};
use quervant_core::search::{SearchLimits, UnifiedRequest, UnifiedResponse, UnifiedSearcher};
use quervant_core::segment::{SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader};
use quervant_core::storage::Directory;

const PROJ: [&str; 4] = ["title", "n", "host", "tags"];

fn request(query: Query, sort: Sort, top_k: usize, fields: &[&str]) -> UnifiedRequest {
    let mut request = UnifiedRequest::new(query, TopK::new(top_k).expect("top-k"));
    request.sort = sort;
    request.projection =
        Projection::Fields(fields.iter().map(|field| (*field).to_owned()).collect());
    request
}

fn search(snapshot: &ReaderSnapshot, request: &UnifiedRequest) -> UnifiedResponse {
    UnifiedSearcher::new(snapshot, &schema(), &registry(), SearchLimits::default())
        .search(request, &Budgets::new(), &CancellationFlag::new())
        .expect("unified search")
}

fn keys(response: &UnifiedResponse) -> Vec<String> {
    response
        .hits
        .iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

fn sorted_keys(response: &UnifiedResponse) -> Vec<String> {
    let mut keys = keys(response);
    keys.sort_unstable();
    keys
}

fn n_asc() -> Sort {
    Sort::new(vec![SortField::new("n", SortDirection::Asc)])
}

fn alpha_query() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("alpha".into()),
    }
}

fn absent_query() -> Query {
    Query::Term {
        field: "title".into(),
        value: FieldValue::Text("definitely-absent".into()),
    }
}

fn range_query() -> Query {
    Query::Range {
        field: "n".into(),
        lower: Bound::Included(FieldValue::I64(25)),
        upper: Bound::Included(FieldValue::I64(60)),
    }
}

fn range_oracle() -> Vec<String> {
    BASE_ROWS
        .iter()
        .filter(|row| (25..=60).contains(&row.n))
        .map(|row| row.key.to_owned())
        .collect()
}

/// Independent expected projection map from the unmetered scanner.
fn expected_projection(snapshot: &ReaderSnapshot) -> BTreeMap<String, Vec<(String, FieldValues)>> {
    let limits = *snapshot.segment_limits();
    let mut expected = BTreeMap::new();
    for segment in snapshot.segments() {
        let reader = SegmentReader::open(segment.bytes().to_vec(), limits).expect("uncached");
        let keys = reader.doc_keys().expect("keys");
        for doc_id in 0..reader.doc_count() {
            let key = keys[doc_id as usize].as_str().to_owned();
            let record = reader.stored_doc(doc_id).expect("stored");
            let values = PROJ
                .iter()
                .map(|field| {
                    let field_id = reader.schema().field_id(field).expect("field id");
                    ((*field).to_owned(), record.get(field_id))
                })
                .collect();
            expected.insert(key, values);
        }
    }
    expected
}

fn assert_projection_matches(
    response: &UnifiedResponse,
    expected: &BTreeMap<String, Vec<(String, FieldValues)>>,
) {
    for hit in &response.hits {
        let key = hit.key.as_str();
        assert_eq!(
            &hit.fields,
            expected.get(key).expect("expected key"),
            "projected fields for {key}"
        );
    }
}

fn assert_cached_segments_match_uncached(snapshot: &ReaderSnapshot) {
    for index in 0..snapshot.segment_count() {
        let segment = &snapshot.segments()[index];
        let cached = snapshot
            .open_segment_reader(index)
            .expect("snapshot reader");
        let uncached = SegmentReader::open(segment.bytes().to_vec(), *snapshot.segment_limits())
            .expect("uncached reader");
        assert_eq!(cached.reader().doc_count(), uncached.doc_count());
        for doc_id in 0..uncached.doc_count() {
            assert_eq!(
                cached.reader().doc_key(doc_id).expect("cached key"),
                uncached.doc_key(doc_id).expect("uncached key")
            );
            assert_eq!(
                cached.reader().stored_doc(doc_id).expect("cached stored"),
                uncached.stored_doc(doc_id).expect("uncached stored")
            );
        }
    }
}

// GB-I01 — memory index, projection, term/absent/range/sort parity.
#[test]
fn gb_i01_memory_projection_and_query_parity() {
    let index = build_memory();
    let snapshot = index.snapshot();
    let expected = expected_projection(&snapshot);

    let alpha = search(
        &snapshot,
        &request(alpha_query(), Sort::default(), 16, &PROJ),
    );
    assert_eq!(sorted_keys(&alpha), oracle_sorted(Predicate::Alpha));
    assert_projection_matches(&alpha, &expected);

    let absent = search(
        &snapshot,
        &request(absent_query(), Sort::default(), 16, &PROJ),
    );
    assert!(absent.hits.is_empty());
    assert_eq!(absent.total_hits, 0);

    let range = search(
        &snapshot,
        &request(range_query(), Sort::default(), 16, &PROJ),
    );
    assert_eq!(sorted_keys(&range), range_oracle());
    assert_projection_matches(&range, &expected);

    let sorted = search(&snapshot, &request(Query::MatchAll, n_asc(), 8, &PROJ));
    assert_eq!(keys(&sorted), N_ASCENDING_KEYS);
    assert_eq!(sorted.total_hits, 8);
    assert_projection_matches(&sorted, &expected);
    assert_cached_segments_match_uncached(&snapshot);
}

// GB-I02 — real FsDirectory commit, handle drop, cold reopen, projection parity.
#[test]
fn gb_i02_filesystem_reopen_projection_parity() {
    let (path, index) = build_fs("pr15g-b-i02");
    let before = index.snapshot();
    let before_bytes: Vec<Vec<u8>> = before
        .segments()
        .iter()
        .map(|segment| segment.bytes().to_vec())
        .collect();
    let expected = expected_projection(&before);
    let response = search(&before, &request(Query::MatchAll, n_asc(), 8, &PROJ));
    assert_eq!(keys(&response), N_ASCENDING_KEYS);
    assert_projection_matches(&response, &expected);
    drop(index);
    drop(before);

    let reopened = reopen_fs(&path);
    let after = reopened.snapshot();
    let after_bytes: Vec<Vec<u8>> = after
        .segments()
        .iter()
        .map(|segment| segment.bytes().to_vec())
        .collect();
    assert_eq!(before_bytes, after_bytes);
    let expected = expected_projection(&after);
    let response = search(&after, &request(alpha_query(), Sort::default(), 16, &PROJ));
    assert_eq!(sorted_keys(&response), oracle_sorted(Predicate::Alpha));
    assert_projection_matches(&response, &expected);
    assert_cached_segments_match_uncached(&after);
    let _ = std::fs::remove_dir_all(&path);
}

// GB-I03 — old PIT keeps old keys/values; new generation sees mutations.
#[test]
fn gb_i03_old_pit_and_new_generation_are_isolated() {
    let (directory, index) = build_memory_with_dir();
    let old = index.pin().expect("pin old");
    let old_snapshot = old.snapshot();
    let old_expected = expected_projection(old_snapshot);
    let old_alpha = search(
        old_snapshot,
        &request(alpha_query(), Sort::default(), 16, &PROJ),
    );
    assert_eq!(sorted_keys(&old_alpha), oracle_sorted(Predicate::Alpha));
    assert_projection_matches(&old_alpha, &old_expected);

    let b1 = DocumentKey::new("b1").expect("b1");
    let c0 = DocumentKey::new("c0").expect("c0");
    {
        let mut writer = index.writer().expect("writer");
        writer
            .apply(MutationRequest::delete(b1.clone()))
            .expect("delete");
        writer.insert(c0_document()).expect("insert c0");
        writer.commit().expect("commit");
    }
    let reopened = Index::open_existing(Arc::clone(&directory), schema(), registry())
        .expect("reopen after mutation");
    let new_snapshot = reopened.snapshot();
    let new_expected = expected_projection(&new_snapshot);
    let new_alpha = search(
        &new_snapshot,
        &request(alpha_query(), Sort::default(), 16, &PROJ),
    );
    assert_eq!(sorted_keys(&new_alpha), NEW_ALPHA_KEYS.to_vec());
    assert_projection_matches(&new_alpha, &new_expected);

    let old_after = search(
        old_snapshot,
        &request(alpha_query(), Sort::default(), 16, &PROJ),
    );
    assert_eq!(sorted_keys(&old_after), oracle_sorted(Predicate::Alpha));
    assert_projection_matches(&old_after, &old_expected);
    assert!(new_snapshot.contains_key(&c0).expect("new c0"));
    assert!(old_snapshot.contains_key(&b1).expect("old b1"));
    assert_cached_segments_match_uncached(old_snapshot);
    assert_cached_segments_match_uncached(&new_snapshot);
}

// GB-I04 — consecutive cursor pages aggregate to the exact full ordered set.
#[test]
fn gb_i04_cursor_pages_are_complete_and_unique() {
    let index = build_memory();
    let snapshot = index.snapshot();
    let mut after = None;
    let mut seen = Vec::new();
    let mut pages = 0usize;
    loop {
        let mut req = request(Query::MatchAll, n_asc(), 2, &PROJ);
        req.after = after;
        let response = search(&snapshot, &req);
        seen.extend(keys(&response));
        pages += 1;
        after = response.next_cursor;
        if after.is_none() {
            break;
        }
        assert!(pages < 100, "pagination must terminate");
    }
    assert_eq!(seen, N_ASCENDING_KEYS);
    assert_eq!(pages, 4);
    let unique: std::collections::BTreeSet<_> = seen.iter().collect();
    assert_eq!(unique.len(), seen.len());
}

// GB-I05 — reduced public metadata cap falls back and remains correct.
#[test]
fn gb_i05_reduced_metadata_cap_fallback_is_correct() {
    let directory: Arc<dyn Directory> = Arc::new(quervant_core::storage::MemoryDirectory::new());
    let limits = IndexLimits::default().with_max_snapshot_bytes(64 * 1024);
    let index =
        Index::create_with_limits(Arc::clone(&directory), schema(), registry(), limits.clone())
            .expect("create");
    commit_segment(&index, segment0_documents());
    commit_segment(&index, segment1_documents());
    let reopened =
        Index::open_with_limits(directory, schema(), registry(), limits).expect("reopen");
    let snapshot = reopened.snapshot();
    assert!(snapshot.resident_bytes() < 64 * 1024);
    let expected = expected_projection(&snapshot);
    for _ in 0..4 {
        let response = search(
            &snapshot,
            &request(alpha_query(), Sort::default(), 16, &PROJ),
        );
        assert_eq!(sorted_keys(&response), oracle_sorted(Predicate::Alpha));
        assert_projection_matches(&response, &expected);
    }
}

// GB-I06 — concurrent readers over two segments remain exact and independent.
#[test]
fn gb_i06_concurrent_readers_are_exact() {
    let index = build_memory();
    let snapshot = Arc::new(index.snapshot());
    let expected = expected_projection(&snapshot);
    std::thread::scope(|scope| {
        for _ in 0..8 {
            let snapshot = Arc::clone(&snapshot);
            let expected = expected.clone();
            scope.spawn(move || {
                for _ in 0..4 {
                    let response = search(&snapshot, &request(Query::MatchAll, n_asc(), 8, &PROJ));
                    assert_eq!(keys(&response), N_ASCENDING_KEYS);
                    assert_projection_matches(&response, &expected);
                    for index in 0..snapshot.segment_count() {
                        let guard = snapshot.open_segment_reader(index).expect("guarded reader");
                        assert!(guard.reader().doc_count() > 0);
                    }
                }
            });
        }
    });
}

fn rebuild_section(original: &[u8], kind: quervant_core::segment::SectionKind) -> Vec<u8> {
    let limits = SegmentLimits::default();
    let view = quervant_core::segment::parse_container(original, &limits).expect("container");
    let mut body = view.body(kind).expect("section body").to_vec();
    assert!(body.len() > 10);
    if kind == quervant_core::segment::SectionKind::Stored
        && u16::from_le_bytes([body[0], body[1]]) == 2
    {
        // STORED v2: keep the header/directory geometry valid and corrupt the
        // first compressed payload byte so decompression/validation fails at
        // the first STORED access.
        let block_count = u64::from_le_bytes(body[14..22].try_into().expect("count"));
        let directory_end = 22usize + 40usize * block_count as usize;
        assert!(body.len() > directory_end);
        body[directory_end] ^= 0xFF;
    } else {
        body[10] ^= 0xFF;
    }
    let mut builder = quervant_core::segment::ContainerBuilder::new(view.kind(), view.doc_count());
    let mut baseline_skipped = false;
    for (feature, version) in view.required_features() {
        if !baseline_skipped && (*feature, *version) == (1, 1) {
            baseline_skipped = true;
            continue;
        }
        builder.require_feature(*feature, *version);
    }
    for (feature, version) in view.optional_features() {
        builder.optional_feature(*feature, *version);
    }
    for section in view.sections() {
        let replacement = if section.kind == kind {
            body.clone()
        } else {
            let start = section.offset as usize;
            original[start..start + section.length as usize].to_vec()
        };
        builder.section(section.kind, section.flags, section.aux, replacement);
    }
    builder.build().expect("rebuilt valid-digest container")
}

// GB-I07 — corrupt digest-valid STORED and DOC_KEYS sections fail at the
// public segment boundary; private tests prove the admitted directory is not
// published and selective access falls back to the original typed error.
#[test]
fn gb_i07_public_corrupt_stored_and_keys_fail_closed() {
    let index = build_memory();
    let snapshot = index.snapshot();
    let original = snapshot.segments()[0].bytes().to_vec();
    let limits = *snapshot.segment_limits();
    for kind in [
        quervant_core::segment::SectionKind::Stored,
        quervant_core::segment::SectionKind::DocKeys,
    ] {
        let corrupt = rebuild_section(&original, kind);
        let reader = SegmentReader::open(corrupt, limits).expect("valid container digests");
        match kind {
            quervant_core::segment::SectionKind::Stored => {
                assert!(reader.stored().is_err(), "corrupt STORED must fail");
            }
            _ => {
                assert!(reader.doc_keys().is_err(), "corrupt DOC_KEYS must fail");
            }
        }
    }
}

// GB-I08 — empty and singleton segments keep zero/one behavior.
#[test]
fn gb_i08_empty_and_singleton_segments() {
    let limits = SegmentLimits::default();
    let empty = SegmentBuilder::new(schema(), registry())
        .expect("builder")
        .build()
        .expect("empty build");
    let reader = SegmentReader::open(empty.bytes, limits).expect("empty reader");
    assert_eq!(reader.doc_count(), 0);
    assert!(reader.doc_keys().expect("keys").is_empty());
    assert!(reader.stored().expect("stored").is_empty());

    let mut builder = SegmentBuilder::new(schema(), registry()).expect("builder");
    let mut document = SegmentDocument::new(DocumentKey::new("only").expect("key"));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text("alpha".to_owned())),
        )
        .expect("title");
    document
        .insert("n", FieldValues::Single(FieldValue::I64(10)))
        .expect("n");
    builder.add_document(document).expect("add");
    let singleton = builder.build().expect("single build");
    let reader = SegmentReader::open(singleton.bytes, limits).expect("single reader");
    assert_eq!(reader.doc_count(), 1);
    assert_eq!(reader.doc_key(0).expect("key").as_str(), "only");
    assert!(
        !reader
            .stored_doc(0)
            .expect("stored")
            .key
            .as_str()
            .is_empty()
    );
}

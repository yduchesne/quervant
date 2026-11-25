//! Shared PERF-06-B1 corpus, independent oracles and public-API helpers.
//!
//! Everything here is test-only. Expected values, dictionaries and orderings are
//! derived from the frozen input table below — never from the production codec,
//! merge or comparator.
#![allow(dead_code)]

use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, CancellationFlag};
use quervant_core::contract::batch::BatchBudget;
use quervant_core::contract::budget::{BudgetKind, BudgetPolicy, Budgets};
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::result::Projection;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{
    GuardedSegmentReader, KeywordOrdinalPreparation, ReaderSnapshot, SnapshotKeywordOrdinals,
};
use quervant_core::storage::{Directory, FsDirectory};

/// Canonical field ids for the frozen corpus schema.
pub const BODY: u32 = 0;
pub const CATEGORY: u32 = 1;
pub const CITY: u32 = 2;
pub const N: u32 = 3;
pub const STORED_TAG: u32 = 4;
pub const TAGS: u32 = 5;

/// City input state for one corpus row.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum City {
    Missing,
    Null,
    Value(&'static str),
}

impl City {
    /// The exact expected `FieldValues` for this row.
    pub fn values(self) -> FieldValues {
        match self {
            Self::Missing => FieldValues::Absent,
            Self::Null => FieldValues::ExplicitNull,
            Self::Value(value) => FieldValues::Single(FieldValue::Keyword(value.to_owned())),
        }
    }

    /// The expected shared ordinal for this row, if it has a value.
    pub fn expected_ordinal(self) -> Option<u64> {
        match self {
            Self::Missing | Self::Null => None,
            Self::Value(value) => Some(expected_rank(value)),
        }
    }
}

/// Batch letter for one corpus row (`a`, `b` or `c`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Batch {
    A,
    B,
    C,
}

impl Batch {
    pub const fn category(self) -> &'static str {
        match self {
            Self::A => "type-a",
            Self::B => "type-b",
            Self::C => "type-c",
        }
    }

    /// The exact raw local dictionary of this batch, in strict UTF-8 byte order.
    pub const fn dictionary(self) -> &'static [&'static str] {
        match self {
            Self::A => &["", "Austin", "Seattle", "é"],
            Self::B => &["\0", "Boston", "Dallas", "Seattle", "e\u{301}", "😀"],
            Self::C => &["Austin", "Z", "a", "aa"],
        }
    }

    /// The exact local→shared rank vector for this batch.
    pub const fn ranks(self) -> &'static [u64] {
        match self {
            Self::A => &[0, 2, 5, 10],
            Self::B => &[1, 3, 4, 5, 9, 11],
            Self::C => &[2, 6, 7, 8],
        }
    }
}

/// The frozen 18-document corpus: `(key, batch, city)`.
pub const ROWS: [(&str, Batch, City); 18] = [
    ("a0", Batch::A, City::Missing),
    ("a1", Batch::A, City::Null),
    ("a2", Batch::A, City::Value("")),
    ("a3", Batch::A, City::Value("Austin")),
    ("a4", Batch::A, City::Value("Seattle")),
    ("a5", Batch::A, City::Value("\u{e9}")),
    ("b0", Batch::B, City::Value("Boston")),
    ("b1", Batch::B, City::Value("Dallas")),
    ("b2", Batch::B, City::Value("Seattle")),
    ("b3", Batch::B, City::Value("e\u{301}")),
    ("b4", Batch::B, City::Value("\0")),
    ("b5", Batch::B, City::Value("\u{1f600}")),
    ("c0", Batch::C, City::Value("Austin")),
    ("c1", Batch::C, City::Value("a")),
    ("c2", Batch::C, City::Value("aa")),
    ("c3", Batch::C, City::Value("Z")),
    ("c4", Batch::C, City::Missing),
    ("c5", Batch::C, City::Null),
];

/// The exact raw-byte global ordering of the 12 distinct city values.
pub const GLOBAL_CITY_ORDER: [&str; 12] = [
    "", "\0", "Austin", "Boston", "Dallas", "Seattle", "Z", "a", "aa", "e\u{301}", "é", "😀",
];

/// Independent rank lookup over [`GLOBAL_CITY_ORDER`].
pub fn expected_rank(value: &str) -> u64 {
    GLOBAL_CITY_ORDER
        .iter()
        .position(|candidate| candidate.as_bytes() == value.as_bytes())
        .expect("value is part of the frozen corpus") as u64
}

/// Value-bearing keys in ascending city order (ties by logical key).
pub const CITY_ASC: [&str; 14] = [
    "a2", "b4", "a3", "c0", "b0", "b1", "a4", "b2", "c3", "c1", "c2", "b3", "a5", "b5",
];

/// Value-bearing keys in descending city order (ties by logical key).
pub const CITY_DESC: [&str; 14] = [
    "b5", "a5", "b3", "c2", "c1", "c3", "a4", "b2", "b1", "b0", "a3", "c0", "b4", "a2",
];

/// The frozen corpus schema (identical to the historical fixture schema).
pub fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "category",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "city",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "stored_tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
        ],
        None,
    )
    .expect("frozen schema")
}

/// A schema whose only difference is a non-stored columnar `city`.
pub fn schema_nonstored_city() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "category",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "city",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, false, true),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
            FieldDefinition::new(
                "stored_tag",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            ),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("keyword"),
        ],
        None,
    )
    .expect("frozen schema")
}

/// The frozen analyzer registry.
pub fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// One corpus document at `position`, optionally with a replacement city.
pub fn document_at(position: usize, city: City) -> Document {
    let (key, batch, expected_city) = ROWS[position];
    assert_eq!(city, expected_city, "frozen city for {key}");
    document_with(key, batch, city, position as i64)
}

/// One corpus document with explicit overrides.
pub fn document_with(key: &str, batch: Batch, city: City, n: i64) -> Document {
    let mut doc = Document::new(DocumentKey::new(key).expect("key"));
    doc.insert(
        "body",
        FieldValues::Single(FieldValue::Text("common".to_owned())),
    )
    .expect("body");
    doc.insert(
        "category",
        FieldValues::Single(FieldValue::Keyword(batch.category().to_owned())),
    )
    .expect("category");
    doc.insert("city", city.values()).expect("city");
    doc.insert("n", FieldValues::Single(FieldValue::I64(n)))
        .expect("n");
    doc.insert(
        "stored_tag",
        FieldValues::Single(FieldValue::Keyword("stored".to_owned())),
    )
    .expect("stored_tag");
    doc.insert(
        "tags",
        FieldValues::Multi(vec![
            FieldValue::Keyword("one".to_owned()),
            FieldValue::Keyword("two".to_owned()),
        ]),
    )
    .expect("tags");
    doc
}

/// The exact six-field projection, in this order.
pub fn projection() -> Projection {
    Projection::Fields(
        ["body", "category", "city", "n", "stored_tag", "tags"]
            .into_iter()
            .map(str::to_owned)
            .collect(),
    )
}

/// The five-field projection for the non-stored-city workload.
pub fn projection_without_city() -> Projection {
    Projection::Fields(
        ["body", "category", "n", "stored_tag", "tags"]
            .into_iter()
            .map(str::to_owned)
            .collect(),
    )
}

/// An explicit, generous test-only batch policy.
pub fn batch_policy() -> BudgetPolicy {
    BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 16)
            .expect("queries")
            .with(BudgetKind::BatchMemoryBytes, 1 << 30)
            .expect("memory")
            .with(BudgetKind::BatchResponseBytes, 1 << 30)
            .expect("response")
            .with(BudgetKind::BatchAggregate, 1 << 30)
            .expect("work"),
        Budgets::new(),
        Budgets::new(),
        Budgets::new(),
    )
}

/// A one-slot batch budget.
pub fn batch_budget() -> BatchBudget {
    BatchBudget::new(16)
}

/// A never-cancelled flag.
pub fn cancel() -> CancellationFlag {
    CancellationFlag::new()
}

/// A unique temporary directory removed on drop.
pub struct TempDir {
    path: std::path::PathBuf,
}

impl TempDir {
    pub fn new(tag: &str) -> Self {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0);
        let path = std::env::temp_dir().join(format!(
            "quervant-perf06-b1-{tag}-{}-{nanos}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).expect("create temp dir");
        Self { path }
    }

    pub fn path(&self) -> &std::path::Path {
        &self.path
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

/// Open a filesystem directory backend.
pub fn fs_directory(path: &std::path::Path) -> Arc<dyn Directory> {
    Arc::new(FsDirectory::open(path).expect("fs directory"))
}

/// Acquire every guard of one snapshot in canonical segment order.
pub fn guards(snapshot: &ReaderSnapshot) -> Vec<GuardedSegmentReader> {
    (0..snapshot.segment_count())
        .map(|index| snapshot.open_segment_reader(index).expect("guard"))
        .collect()
}

/// Prepare (or reuse) the city ordinal map for one exact snapshot view.
pub fn prepare_city(
    snapshot: &ReaderSnapshot,
    guards: &[GuardedSegmentReader],
) -> KeywordOrdinalPreparation {
    match snapshot.prepare_keyword_ordinals(CITY, guards, &cancel()) {
        Ok(preparation) => preparation,
        Err(error) => panic!("prepare city ordinals failed: {error:?}"),
    }
}

/// Require a ready map.
pub fn ready_map(preparation: &KeywordOrdinalPreparation) -> &Arc<SnapshotKeywordOrdinals> {
    preparation
        .ready()
        .unwrap_or_else(|| panic!("expected a ready map, got {preparation:?}"))
}

/// One segment's local dictionary and its local→shared translation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SegmentOrdinals {
    pub keys: Vec<String>,
    pub terms: Vec<Vec<u8>>,
    pub ranks: Vec<u64>,
}

/// Read every segment's local dictionary and translation through the public
/// bound APIs, ordered by the segment's first logical key.
pub fn segment_ordinals(
    _snapshot: &ReaderSnapshot,
    guards: &[GuardedSegmentReader],
    map: &SnapshotKeywordOrdinals,
) -> Vec<SegmentOrdinals> {
    let mut collected: Vec<(String, SegmentOrdinals)> = Vec::new();
    for guard in guards {
        let keys = guard
            .reader()
            .doc_keys()
            .expect("doc keys")
            .iter()
            .map(|key| key.as_str().to_owned())
            .collect::<Vec<_>>();
        let translation = map.bind_segment(guard).expect("bind segment");
        let columns = guard
            .reader()
            .open_columns()
            .expect("columns")
            .expect("column section");
        let handle = columns
            .bind_keyword_ordinals(CITY)
            .expect("bind local")
            .expect("ordinal column");
        let mut terms = Vec::new();
        let mut ranks = Vec::new();
        for ordinal in 0..handle.dictionary_len() {
            terms.push(handle.dictionary_term(ordinal).expect("term").to_vec());
            ranks.push(translation.translate(ordinal).expect("translate"));
        }
        let first = keys.first().cloned().unwrap_or_default();
        collected.push((first, SegmentOrdinals { keys, terms, ranks }));
    }
    collected.sort_by(|left, right| left.0.cmp(&right.0));
    collected.into_iter().map(|(_, value)| value).collect()
}

/// Read one document's local ordinal/state through the public bound API by key.
pub fn city_ordinal(
    guard: &GuardedSegmentReader,
    key: &str,
) -> Option<quervant_core::segment::column::KeywordOrdinalValue> {
    let reader = guard.reader();
    let keys = reader.doc_keys().expect("keys");
    let doc_id = keys
        .iter()
        .position(|candidate| candidate.as_str() == key)? as u64;
    let columns = reader.open_columns().expect("columns")?;
    let handle = columns.bind_keyword_ordinals(CITY).expect("bind")?;
    Some(handle.doc_ordinal(doc_id).expect("row"))
}

/// Translate the corpus city state of `key` in one snapshot to its shared rank.
pub fn shared_city_rank(
    guards: &[GuardedSegmentReader],
    map: &SnapshotKeywordOrdinals,
    key: &str,
) -> Option<u64> {
    for guard in guards {
        if let Some(value) = city_ordinal(guard, key) {
            return match value {
                quervant_core::segment::column::KeywordOrdinalValue::Value { ordinal, .. } => Some(
                    map.bind_segment(guard)
                        .expect("bind")
                        .translate(ordinal)
                        .expect("translate"),
                ),
                _ => None,
            };
        }
    }
    None
}

/// All document keys of one snapshot, in deterministic sorted order.
pub fn sorted_keys(snapshot: &ReaderSnapshot) -> Vec<String> {
    let mut keys = Vec::new();
    for index in 0..snapshot.segment_count() {
        let guard = snapshot.open_segment_reader(index).expect("guard");
        for key in guard.reader().doc_keys().expect("keys").iter() {
            keys.push(key.as_str().to_owned());
        }
    }
    keys.sort();
    keys
}

/// The literal six-field projection for one logical key.
///
/// This is an input oracle over the frozen table plus the two fixed appended
/// `type-d` exceptions; it never consults a production reader, query result,
/// codec, segment map or ordinal translator.
pub fn expected_projected_fields(key: &str) -> Vec<(String, FieldValues)> {
    // Appended-only rows (never part of the frozen first 18).
    let appended: Option<(&str, i64)> = match key {
        "d0" => Some(("Chicago", 18)),
        "d1" => Some(("Seattle", 19)),
        _ => None,
    };
    let (city, category, n) = match appended {
        Some((city, n)) => (City::Value(city), "type-d", n),
        None => {
            let position = ROWS
                .iter()
                .position(|(row, _, _)| *row == key)
                .unwrap_or_else(|| panic!("unknown corpus key {key}"));
            let (_, batch, city) = ROWS[position];
            (city, batch.category(), position as i64)
        }
    };
    vec![
        (
            "body".to_owned(),
            FieldValues::Single(FieldValue::Text("common".to_owned())),
        ),
        (
            "category".to_owned(),
            FieldValues::Single(FieldValue::Keyword(category.to_owned())),
        ),
        ("city".to_owned(), city.values()),
        ("n".to_owned(), FieldValues::Single(FieldValue::I64(n))),
        (
            "stored_tag".to_owned(),
            FieldValues::Single(FieldValue::Keyword("stored".to_owned())),
        ),
        (
            "tags".to_owned(),
            FieldValues::Multi(vec![
                FieldValue::Keyword("one".to_owned()),
                FieldValue::Keyword("two".to_owned()),
            ]),
        ),
    ]
}

/// The complete expected `city` `FieldValues` map for the frozen corpus.
pub fn expected_city_values() -> std::collections::BTreeMap<String, FieldValues> {
    ROWS.iter()
        .map(|(key, _, city)| ((*key).to_owned(), city.values()))
        .collect()
}

/// Independent membership sets derived from the frozen input table.
pub fn typed_membership() -> (
    std::collections::BTreeSet<String>,
    std::collections::BTreeSet<String>,
    std::collections::BTreeSet<String>,
) {
    let missing = ["a0", "c4"].iter().map(|k| (*k).to_owned()).collect();
    let null = ["a1", "c5"].iter().map(|k| (*k).to_owned()).collect();
    let exists = ROWS
        .iter()
        .map(|(key, _, _)| *key)
        .filter(|key| *key != "a0" && *key != "c4")
        .map(str::to_owned)
        .collect();
    (missing, null, exists)
}

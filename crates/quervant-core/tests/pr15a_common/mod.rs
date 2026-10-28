//! PR 15A frozen `pr15a_v1` fixture and independent test-only oracle.
//!
//! The records below are the literal `benchmarks/datasets/pr15a_v1.json`
//! content. The oracle evaluates simple predicates over those static records
//! **before** any index is built; it never calls `Index`, `Searcher` or the
//! writer to derive an expectation.

#![allow(dead_code)]

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;

use quervant_core::contract::document::{Document, DocumentKey, FieldValues};
use quervant_core::contract::value::{FieldValue, JsonNumber, JsonValue, Timestamp};
use quervant_core::index::{Index, IndexLimits};
use quervant_core::storage::{Directory, FsDirectory, MemoryDirectory};
use sha2::{Digest, Sha256};

use crate::pr14_common::{registry, schema};

/// Frozen fixture version identifier.
pub const FIXTURE_VERSION: &str = "pr15a_v1";

/// Canonical fixture file bytes, compiled into the test binary.
pub const CANONICAL_JSON: &str = include_str!("../../../../benchmarks/datasets/pr15a_v1.json");

/// Frozen SHA-256 of [`CANONICAL_JSON`], recorded with external `sha256sum`.
pub const PR15A_V1_SHA256: &str =
    "104d5ef0392edc43ac68f82d25288bea1394898e2a51dddac178cb7db8ecd087";

/// One frozen logical record.
#[derive(Clone, Copy, Debug)]
pub struct Row {
    pub key: &'static str,
    pub segment: u8,
    pub title: &'static str,
    pub host: &'static str,
    pub n: i64,
    pub ts: i64,
    pub ip: &'static str,
    /// `None` means an explicit JSON `null` severity.
    pub severity: Option<i64>,
    /// `None` means the `tags` key is absent; `Some(&[])` is an empty array.
    pub tags: Option<&'static [&'static str]>,
}

/// The eight canonical records in insertion order.
pub const BASE_ROWS: [Row; 8] = [
    Row {
        key: "a0",
        segment: 0,
        title: "alpha beta",
        host: "h1",
        n: 10,
        ts: 1000,
        ip: "10.0.0.1",
        severity: Some(1),
        tags: Some(&["red", "blue"]),
    },
    Row {
        key: "a1",
        segment: 0,
        title: "alpha",
        host: "h2",
        n: 20,
        ts: 2000,
        ip: "10.0.0.2",
        severity: Some(2),
        tags: Some(&["blue"]),
    },
    Row {
        key: "a2",
        segment: 0,
        title: "beta",
        host: "h1",
        n: 30,
        ts: 3000,
        ip: "192.0.2.1",
        severity: Some(3),
        tags: Some(&[]),
    },
    Row {
        key: "a3",
        segment: 0,
        title: "gamma",
        host: "h3",
        n: 40,
        ts: 4000,
        ip: "2001:db8::1",
        severity: None,
        tags: None,
    },
    Row {
        key: "b0",
        segment: 1,
        title: "alpha gamma",
        host: "h1",
        n: 50,
        ts: 5000,
        ip: "10.0.1.1",
        severity: Some(2),
        tags: Some(&["red"]),
    },
    Row {
        key: "b1",
        segment: 1,
        title: "beta gamma",
        host: "h2",
        n: 60,
        ts: 6000,
        ip: "192.0.2.2",
        severity: Some(4),
        tags: None,
    },
    Row {
        key: "b2",
        segment: 1,
        title: "delta",
        host: "h3",
        n: 70,
        ts: 7000,
        ip: "2001:db8::2",
        severity: Some(0),
        tags: Some(&[]),
    },
    Row {
        key: "b3",
        segment: 1,
        title: "alpha",
        host: "h2",
        n: 80,
        ts: 8000,
        ip: "10.0.0.8",
        severity: Some(5),
        tags: Some(&["green"]),
    },
];

/// Old-generation keys (generation 2).
pub const OLD_KEYS: [&str; 8] = ["a0", "a1", "a2", "a3", "b0", "b1", "b2", "b3"];
/// New live keys after the frozen generation-3 mutation.
pub const NEW_LIVE_KEYS: [&str; 8] = ["a0", "a1", "a2", "a3", "b0", "b2", "b3", "c0"];
/// New `title=alpha` keys after the frozen generation-3 mutation.
pub const NEW_ALPHA_KEYS: [&str; 5] = ["a0", "a1", "b0", "b3", "c0"];
/// Old `host=h2` keys.
pub const OLD_HOST_H2: [&str; 3] = ["a1", "b1", "b3"];
/// New `host=h2` keys.
pub const NEW_HOST_H2: [&str; 1] = ["b3"];
/// Full `n`-ascending key order.
pub const N_ASCENDING_KEYS: [&str; 8] = ["a0", "a1", "a2", "a3", "b0", "b1", "b2", "b3"];

/// Look up one frozen record by key.
#[must_use]
pub fn row(key: &str) -> &'static Row {
    BASE_ROWS
        .iter()
        .find(|row| row.key == key)
        .unwrap_or_else(|| panic!("unknown pr15a_v1 key {key}"))
}

/// Build the canonical document for one frozen record.
#[must_use]
pub fn document(row: &Row) -> Document {
    let mut document = Document::new(DocumentKey::new(row.key).expect("valid fixture key"));
    insert(
        &mut document,
        "title",
        FieldValue::Text(row.title.to_owned()),
    );
    insert(
        &mut document,
        "host",
        FieldValue::Keyword(row.host.to_owned()),
    );
    insert(&mut document, "n", FieldValue::I64(row.n));
    insert(
        &mut document,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(row.ts)),
    );
    insert(
        &mut document,
        "ip",
        FieldValue::Ip(row.ip.parse().expect("fixture ip")),
    );
    insert(&mut document, "body", FieldValue::Json(body(row)));
    document
}

fn insert(document: &mut Document, field: &str, value: FieldValue) {
    document
        .insert(field, FieldValues::Single(value))
        .expect("fixture insert");
}

/// The canonical JSON body, preserving explicit null and empty-array states.
#[must_use]
pub fn body(row: &Row) -> JsonValue {
    let mut entries = vec![(
        "severity".to_owned(),
        match row.severity {
            Some(value) => JsonValue::Number(JsonNumber::I64(value)),
            None => JsonValue::Null,
        },
    )];
    if let Some(tags) = row.tags {
        entries.push((
            "tags".to_owned(),
            JsonValue::Array(
                tags.iter()
                    .map(|tag| JsonValue::String((*tag).to_owned()))
                    .collect(),
            ),
        ));
    }
    JsonValue::Object(entries)
}

/// Canonical documents in insertion order.
#[must_use]
pub fn base_documents() -> Vec<Document> {
    BASE_ROWS.iter().map(document).collect()
}

/// Documents for segment 0 in insertion order.
#[must_use]
pub fn segment0_documents() -> Vec<Document> {
    BASE_ROWS
        .iter()
        .filter(|row| row.segment == 0)
        .map(document)
        .collect()
}

/// Documents for segment 1 in insertion order.
#[must_use]
pub fn segment1_documents() -> Vec<Document> {
    BASE_ROWS
        .iter()
        .filter(|row| row.segment == 1)
        .map(document)
        .collect()
}

/// Rebuild the frozen upserted `a1` document (`host=h9`, `n=25`).
#[must_use]
pub fn mutated_a1() -> Document {
    let mut document = document(row("a1"));
    replace(&mut document, "host", FieldValue::Keyword("h9".to_owned()));
    replace(&mut document, "n", FieldValue::I64(25));
    document
}

/// The frozen generation-3 inserted document `c0`.
#[must_use]
pub fn c0_document() -> Document {
    let mut document = Document::new(DocumentKey::new("c0").expect("c0"));
    insert(&mut document, "title", FieldValue::Text("alpha".to_owned()));
    insert(&mut document, "host", FieldValue::Keyword("h1".to_owned()));
    insert(&mut document, "n", FieldValue::I64(90));
    insert(
        &mut document,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(9000)),
    );
    insert(
        &mut document,
        "ip",
        FieldValue::Ip("10.0.0.9".parse().expect("c0 ip")),
    );
    insert(
        &mut document,
        "body",
        FieldValue::Json(JsonValue::Object(vec![
            ("severity".to_owned(), JsonValue::Number(JsonNumber::I64(6))),
            ("tags".to_owned(), JsonValue::Array(Vec::new())),
        ])),
    );
    document
}

fn replace(document: &mut Document, field: &str, value: FieldValue) {
    let mut rebuilt = Document::new(document.key().clone());
    for (name, values) in document.fields() {
        if name != field {
            rebuilt.insert(name, values.clone()).expect("copy field");
        }
    }
    rebuilt
        .insert(field, FieldValues::Single(value))
        .expect("replace field");
    *document = rebuilt;
}

/// A unique native-Linux temporary directory for `FsDirectory` tests.
#[must_use]
pub fn temp_dir(tag: &str) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "quervant-pr15a-{}-{tag}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|value| value.as_nanos())
            .unwrap_or(0)
    ));
    let _ = std::fs::remove_dir_all(&path);
    path
}

/// Build the frozen two-segment generation in an in-memory directory.
#[must_use]
pub fn build_memory() -> Index {
    build_memory_with_dir().1
}

/// Build the frozen two-segment generation and return the directory handle.
#[must_use]
pub fn build_memory_with_dir() -> (Arc<dyn Directory>, Index) {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = create(Arc::clone(&directory));
    commit_segment(&index, segment0_documents());
    commit_segment(&index, segment1_documents());
    let reopened = Index::open_existing(directory.clone(), schema(), registry()).expect("reopen");
    (directory, reopened)
}

/// Build the frozen two-segment generation in a real `FsDirectory` and reopen.
#[must_use]
pub fn build_fs(tag: &str) -> (PathBuf, Index) {
    let path = temp_dir(tag);
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(&path).expect("fs directory"));
    let index = create(Arc::clone(&directory));
    commit_segment(&index, segment0_documents());
    commit_segment(&index, segment1_documents());
    let reopened = Index::open_existing(directory, schema(), registry()).expect("fs reopen");
    (path, reopened)
}

/// Reopen the frozen generation from an existing real filesystem path.
#[must_use]
pub fn reopen_fs(path: &std::path::Path) -> Index {
    let directory: Arc<dyn Directory> = Arc::new(FsDirectory::open(path).expect("fs directory"));
    Index::open_existing(directory, schema(), registry()).expect("fs reopen")
}

fn create(directory: Arc<dyn Directory>) -> Index {
    Index::create_with_limits(directory, schema(), registry(), IndexLimits::default())
        .expect("create index")
}

/// Commit one explicit immutable segment.
pub fn commit_segment(index: &Index, documents: Vec<Document>) {
    let mut writer = index.writer().expect("writer");
    for document in documents {
        writer.insert(document).expect("insert");
    }
    writer.commit().expect("commit");
}

/// Independent predicate family over the frozen records.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Predicate {
    Alpha,
    NAtLeast50,
    AlphaAndN50,
    HostH2,
    Ipv4Cidr10,
    TimeInclusive2000To5000,
    AlphaAndHostH2,
    NotAlpha,
    Ipv6Cidr2001Db8,
    SeverityTwo,
}

impl Predicate {
    /// Evaluate this predicate directly over static record values.
    #[must_use]
    pub fn matches(self, row: &Row) -> bool {
        match self {
            Self::Alpha => has_alpha(row),
            Self::NAtLeast50 => row.n >= 50,
            Self::AlphaAndN50 => has_alpha(row) && row.n >= 50,
            Self::HostH2 => row.host == "h2",
            Self::Ipv4Cidr10 => {
                let address: std::net::IpAddr = row.ip.parse().expect("fixture ip");
                match address {
                    std::net::IpAddr::V4(address) => {
                        let octets = address.octets();
                        octets[0] == 10 && octets[1] == 0 && octets[2] == 0
                    }
                    std::net::IpAddr::V6(_) => false,
                }
            }
            Self::TimeInclusive2000To5000 => (2000..=5000).contains(&row.ts),
            Self::AlphaAndHostH2 => has_alpha(row) && row.host == "h2",
            Self::NotAlpha => !has_alpha(row),
            Self::Ipv6Cidr2001Db8 => {
                let address: std::net::IpAddr = row.ip.parse().expect("fixture ip");
                match address {
                    std::net::IpAddr::V6(address) => {
                        let segments = address.segments();
                        segments[0] == 0x2001 && segments[1] == 0x0db8
                    }
                    std::net::IpAddr::V4(_) => false,
                }
            }
            Self::SeverityTwo => row.severity == Some(2),
        }
    }
}

fn has_alpha(row: &Row) -> bool {
    row.title.split_whitespace().any(|token| token == "alpha")
}

/// Independent oracle keys in record insertion order.
#[must_use]
pub fn oracle_keys(predicate: Predicate) -> Vec<&'static str> {
    BASE_ROWS
        .iter()
        .filter(|row| predicate.matches(row))
        .map(|row| row.key)
        .collect()
}

/// Independent oracle keys sorted lexicographically.
#[must_use]
pub fn oracle_sorted(predicate: Predicate) -> Vec<&'static str> {
    let mut keys = oracle_keys(predicate);
    keys.sort_unstable();
    keys
}

/// Independent host group counts.
#[must_use]
pub fn oracle_group_counts() -> BTreeMap<&'static str, u64> {
    let mut counts = BTreeMap::new();
    for row in BASE_ROWS {
        *counts.entry(row.host).or_insert(0) += 1;
    }
    counts
}

/// Independent exact distinct host count.
#[must_use]
pub fn oracle_distinct_hosts() -> u64 {
    let hosts: std::collections::BTreeSet<&str> = BASE_ROWS.iter().map(|row| row.host).collect();
    hosts.len() as u64
}

/// SHA-256 of the frozen canonical fixture bytes.
#[must_use]
pub fn canonical_sha256() -> [u8; 32] {
    Sha256::digest(CANONICAL_JSON.as_bytes()).into()
}

/// Assert the compiled fixture digest equals the frozen record.
pub fn assert_frozen_digest() {
    let first = canonical_sha256();
    let second = canonical_sha256();
    assert_eq!(first, second, "fixture digest must be deterministic");
    let expected: [u8; 32] = {
        let mut out = [0u8; 32];
        let text = PR15A_V1_SHA256.as_bytes();
        assert_eq!(text.len(), 64, "frozen digest must be 64 hex characters");
        for (index, byte) in out.iter_mut().enumerate() {
            let high = hex_nibble(text[index * 2]);
            let low = hex_nibble(text[index * 2 + 1]);
            *byte = (high << 4) | low;
        }
        out
    };
    assert_eq!(
        first, expected,
        "benchmarks/datasets/pr15a_v1.json changed; bump the fixture version and freeze record"
    );
}

fn hex_nibble(byte: u8) -> u8 {
    match byte {
        b'0'..=b'9' => byte - b'0',
        b'a'..=b'f' => byte - b'a' + 10,
        other => panic!("invalid frozen digest hex byte {other:#x}"),
    }
}

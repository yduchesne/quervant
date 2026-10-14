//! Shared integration-test helpers (no external test dependencies).
#![allow(dead_code)]

use std::future::Future;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::task::{Context, Poll};

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::Index;
use quervant_core::storage::{Directory, ReadHandle};

/// Minimal `std`-only executor for deterministic tests.
pub fn block_on<F: Future>(future: F) -> F::Output {
    let mut context = Context::from_waker(std::task::Waker::noop());
    let mut future = Box::pin(future);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::yield_now(),
        }
    }
}

static COUNTER: AtomicU64 = AtomicU64::new(0);

/// Poll a boxed future exactly once (used for cancellation tests).
pub fn poll_once<F: Future>(future: &mut Pin<Box<F>>) -> Poll<F::Output> {
    let mut context = Context::from_waker(std::task::Waker::noop());
    future.as_mut().poll(&mut context)
}

/// A unique temporary directory removed on drop.
pub struct TempDir {
    path: PathBuf,
}

impl TempDir {
    pub fn new(tag: &str) -> Self {
        let unique = format!(
            "quervant-test-{tag}-{}-{}",
            std::process::id(),
            COUNTER.fetch_add(1, Ordering::Relaxed)
        );
        let path = std::env::temp_dir().join(unique);
        std::fs::create_dir_all(&path).expect("create temp dir");
        Self { path }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

/// Read the complete contents of a handle using positional reads only.
pub fn read_all(reader: &dyn ReadHandle) -> Vec<u8> {
    let mut buf = vec![0u8; reader.len() as usize];
    let mut filled = 0;
    while filled < buf.len() {
        let read = reader.read_at(filled as u64, &mut buf[filled..]).unwrap();
        if read == 0 {
            break;
        }
        filled += read;
    }
    buf.truncate(filled);
    buf
}

// ---------------------------------------------------------------------------
// PR 7 lexical-search fixture helpers
// ---------------------------------------------------------------------------

/// The shared PR 7 fixture schema.
pub fn pr07_schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("english"),
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_normalizer("keyword"),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "raw",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "n",
                FieldType::I64,
                Cardinality::Single,
                FieldOptions::new(false, true, true),
            ),
        ],
        None,
    )
    .expect("pr07 schema")
}

/// The shared PR 7 analyzer registry (all built-ins).
pub fn pr07_registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// A convenient PR 7 fixture document description.
pub struct Pr07Doc<'a> {
    pub key: &'a str,
    pub title: Option<&'a str>,
    pub body: Vec<&'a str>,
    pub host: Option<&'a str>,
    pub tags: Vec<&'a str>,
    pub raw: Option<&'a str>,
    pub n: i64,
}

impl<'a> Pr07Doc<'a> {
    pub fn new(key: &'a str) -> Self {
        Self {
            key,
            title: None,
            body: Vec::new(),
            host: None,
            tags: Vec::new(),
            raw: None,
            n: 0,
        }
    }

    pub fn title(mut self, title: &'a str) -> Self {
        self.title = Some(title);
        self
    }

    pub fn body(mut self, body: Vec<&'a str>) -> Self {
        self.body = body;
        self
    }

    pub fn host(mut self, host: &'a str) -> Self {
        self.host = Some(host);
        self
    }

    pub fn tags(mut self, tags: Vec<&'a str>) -> Self {
        self.tags = tags;
        self
    }

    pub fn raw(mut self, raw: &'a str) -> Self {
        self.raw = Some(raw);
        self
    }

    pub fn n(mut self, n: i64) -> Self {
        self.n = n;
        self
    }

    pub fn build(self) -> Document {
        let mut document = Document::new(DocumentKey::new(self.key).expect("pr07 key"));
        if let Some(title) = self.title {
            document
                .insert(
                    "title",
                    FieldValues::Single(FieldValue::Text(title.to_owned())),
                )
                .expect("title");
        }
        if !self.body.is_empty() {
            let values = if self.body.len() == 1 {
                FieldValues::Single(FieldValue::Text(self.body[0].to_owned()))
            } else {
                FieldValues::Multi(
                    self.body
                        .iter()
                        .map(|value| FieldValue::Text((*value).to_owned()))
                        .collect(),
                )
            };
            document.insert("body", values).expect("body");
        }
        if let Some(host) = self.host {
            document
                .insert(
                    "host",
                    FieldValues::Single(FieldValue::Keyword(host.to_owned())),
                )
                .expect("host");
        }
        if !self.tags.is_empty() {
            let values = if self.tags.len() == 1 {
                FieldValues::Single(FieldValue::Keyword(self.tags[0].to_owned()))
            } else {
                FieldValues::Multi(
                    self.tags
                        .iter()
                        .map(|value| FieldValue::Keyword((*value).to_owned()))
                        .collect(),
                )
            };
            document.insert("tags", values).expect("tags");
        }
        if let Some(raw) = self.raw {
            document
                .insert("raw", FieldValues::Single(FieldValue::Text(raw.to_owned())))
                .expect("raw");
        }
        document
            .insert("n", FieldValues::Single(FieldValue::I64(self.n)))
            .expect("n");
        document
    }
}

/// Build a committed index from ordered batches, one immutable segment per
/// non-empty batch. Returns the resulting generation.
pub fn pr07_commit_batches(directory: Arc<dyn Directory>, batches: Vec<Vec<Document>>) -> u64 {
    let index = Index::create(directory, pr07_schema(), pr07_registry()).expect("create index");
    let mut writer = index.writer().expect("writer");
    for batch in batches {
        for document in batch {
            writer.insert(document).expect("insert");
        }
        if writer.pending_documents() > 0 {
            writer.flush().expect("flush");
        }
    }
    let outcome = writer.commit().expect("commit");
    outcome.generation
}

// ---------------------------------------------------------------------------
// PR 8 lexical-search fixture helpers
// ---------------------------------------------------------------------------

/// The shared PR 8 fixture schema: the PR 7 fields plus an indexed canonical
/// domain keyword field (`keyword` normalizer).
pub fn pr08_schema() -> Schema {
    let mut fields: Vec<FieldDefinition> = pr07_schema().fields().cloned().collect();
    fields.push(
        FieldDefinition::new(
            "domain_canonical",
            FieldType::Keyword,
            Cardinality::Single,
            FieldOptions::indexed_stored(),
        )
        .with_normalizer("keyword"),
    );
    Schema::new(fields, None).expect("pr08 schema")
}

/// The shared PR 8 analyzer registry (all built-ins).
pub fn pr08_registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

/// Build a committed PR 8 index from ordered batches, one segment per flush.
pub fn pr08_commit_batches(directory: Arc<dyn Directory>, batches: Vec<Vec<Document>>) -> u64 {
    let index = Index::create(directory, pr08_schema(), pr08_registry()).expect("create index");
    let mut writer = index.writer().expect("writer");
    for batch in batches {
        for document in batch {
            writer.insert(document).expect("insert");
        }
        if writer.pending_documents() > 0 {
            writer.flush().expect("flush");
        }
    }
    let outcome = writer.commit().expect("commit");
    outcome.generation
}

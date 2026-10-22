//! M1 regression gate: single-key [`IndexWriter::apply`] admission.
//!
//! This target exists to answer one question only: **did M1 change the cost of
//! the pre-existing single-key mutation admission path?** It is not a batch
//! throughput benchmark and it makes no cross-engine claim.
//!
//! Methodology (see `docs/BENCHMARKING.md`):
//!
//! * Schema, documents, requests and idempotency tokens are built in the
//!   **untimed** setup closure, together with a fresh in-memory index. No index
//!   creation, commit, flush or reader work is inside a timed region.
//! * The timed region is exactly `IndexWriter::apply` called
//!   [`MUTATIONS_PER_ITERATION`] times on successful upserts.
//! * An independent, untimed oracle validates the expected revision sequence and
//!   pending counters before any measurement. A mismatch aborts the run.
//! * Two configurations are measured so the M1 token-namespace check on the
//!   admission path is exercised: untokened requests, and requests carrying a
//!   distinct idempotency token.
//!
//! This source is also compiled against pre-M1 revisions by
//! `benchmarks/scripts/m1-single-key-apply.sh`; it therefore uses only APIs that
//! exist before M1.

use std::fmt::Write as _;
use std::hint::black_box;
use std::sync::Arc;

use criterion::{BatchSize, Criterion, Throughput, criterion_group, criterion_main};

use quervant_core::analysis::AnalyzerRegistry;
use quervant_core::contract::document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey, MutationRequest,
};
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, IndexLimits, IndexWriter};
use quervant_core::storage::{Directory, MemoryDirectory};

/// Successful single-key mutations per timed iteration.
const MUTATIONS_PER_ITERATION: usize = 100;
/// Distinct logical keys. Smaller than the mutation count so each key is
/// upserted more than once and the revision path is exercised.
const KEY_SPACE: usize = 64;
/// Analyzed tokens per `body` value.
const BODY_TOKENS: usize = 8;

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::new(true, false, false),
            )
            .with_analyzer("standard_folded"),
            FieldDefinition::new(
                "tag",
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
        ],
        None,
    )
    .expect("benchmark schema")
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn document(index: usize) -> Document {
    let key = format!("k{:04}", index % KEY_SPACE);
    let mut document = Document::new(DocumentKey::new(key).expect("key"));
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(format!("title{index:04}"))),
        )
        .expect("title");
    let mut body = String::with_capacity(BODY_TOKENS * 8);
    for token in 0..BODY_TOKENS {
        let _ = write!(body, "tok{:02} ", (index + token) % 97);
    }
    document
        .insert("body", FieldValues::Single(FieldValue::Text(body)))
        .expect("body");
    document
        .insert(
            "tag",
            FieldValues::Single(FieldValue::Keyword(format!("tag{:02}", index % 17))),
        )
        .expect("tag");
    document
        .insert("n", FieldValues::Single(FieldValue::I64(index as i64)))
        .expect("n");
    document
}

/// Untimed setup: a fresh in-memory index plus a prebuilt request batch.
fn setup(with_token: &str) -> (IndexWriter, Vec<MutationRequest>) {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create_with_limits(directory, schema(), registry(), IndexLimits::default())
        .expect("index");
    let writer = index.writer().expect("writer");
    let requests = (0..MUTATIONS_PER_ITERATION)
        .map(|i| {
            let request = MutationRequest::upsert(document(i));
            if with_token.is_empty() {
                request
            } else {
                request.with_idempotency_key(
                    IdempotencyKey::new(format!("{with_token}-{i:04}")).expect("token"),
                )
            }
        })
        .collect();
    (writer, requests)
}

/// Independent, untimed correctness oracle. Aborts the run on mismatch.
fn assert_oracle(with_token: &str) {
    let (mut writer, requests) = setup(with_token);
    for (index, request) in requests.iter().enumerate() {
        let expected_revision = (index / KEY_SPACE) as u64 + 1;
        let key = request.key.clone();
        let response = writer.apply(request.clone()).expect("oracle apply");
        assert_eq!(response.key, key, "oracle key at {index}");
        assert_eq!(
            response.revision,
            Some(expected_revision),
            "oracle revision at {index}"
        );
        assert!(!response.replayed, "oracle must not replay at {index}");
    }
    assert_eq!(
        writer.pending_documents(),
        MUTATIONS_PER_ITERATION,
        "oracle pending documents"
    );
    assert_eq!(
        writer.pending_mutations(),
        MUTATIONS_PER_ITERATION,
        "oracle pending mutations"
    );
}

fn bench(c: &mut Criterion) {
    assert_oracle("");
    assert_oracle("oracle");

    let mut group = c.benchmark_group("m1_single_key_apply");
    group.throughput(Throughput::Elements(MUTATIONS_PER_ITERATION as u64));

    group.bench_function("apply/single_key_no_token", |b| {
        b.iter_batched(
            || setup(""),
            |(mut writer, requests)| {
                for request in requests {
                    black_box(writer.apply(request).expect("apply"));
                }
            },
            BatchSize::SmallInput,
        );
    });

    group.bench_function("apply/single_key_with_token", |b| {
        b.iter_batched(
            || setup("bench"),
            |(mut writer, requests)| {
                for request in requests {
                    black_box(writer.apply(request).expect("apply"));
                }
            },
            BatchSize::SmallInput,
        );
    });

    group.finish();
}

criterion_group!(benches, bench);
criterion_main!(benches);

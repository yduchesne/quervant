//! Real RustFS acceptance tests for the production S3 adapter (PR 13).
//!
//! These tests require a running pinned RustFS (or compatible S3) instance and
//! are therefore `#[ignore]`d by default. Run them explicitly:
//!
//! ```sh
//! QUERVANT_RUSTFS_ENDPOINT=http://127.0.0.1:9000 \
//! QUERVANT_RUSTFS_REGION=us-east-1 \
//! QUERVANT_RUSTFS_BUCKET=quervant-pr13 \
//! QUERVANT_RUSTFS_ACCESS_KEY=quervanttest \
//! QUERVANT_RUSTFS_SECRET_KEY=quervantsecret \
//! cargo test -p quervant-objectstore --features s3 --test pr13_s3_rustfs -- --ignored --test-threads=1
//! ```
//!
//! A skipped default run is **not** real RustFS acceptance evidence; the PR
//! validation report records the explicit env and image digest used.

#![cfg(feature = "s3")]

use std::sync::atomic::{AtomicU64, Ordering};

use quervant_objectstore::{
    ByteRange, ContentDescriptor, ContentDigest, ObjectKey, ObjectStore, ObjectStoreError,
    PutOutcome, PutPrecondition, S3Config, S3ObjectStore, TransferLimits,
};

static COUNTER: AtomicU64 = AtomicU64::new(0);

/// A per-process run identifier so repeated runs against a persistent RustFS
/// instance never reuse keys.
fn run_id() -> u128 {
    static RUN: std::sync::OnceLock<u128> = std::sync::OnceLock::new();
    *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0)
    })
}

struct Env {
    endpoint: String,
    region: String,
    bucket: String,
    access_key: String,
    secret_key: String,
}

/// Required real-RustFS acceptance environment. Fails closed when the suite is
/// explicitly invoked without a provider.
fn require_env() -> Env {
    let endpoint = std::env::var("QUERVANT_RUSTFS_ENDPOINT")
        .expect("QUERVANT_RUSTFS_ENDPOINT must be set for real RustFS acceptance");
    let bucket = std::env::var("QUERVANT_RUSTFS_BUCKET")
        .expect("QUERVANT_RUSTFS_BUCKET must be set for real RustFS acceptance");
    let access_key = std::env::var("QUERVANT_RUSTFS_ACCESS_KEY")
        .expect("QUERVANT_RUSTFS_ACCESS_KEY must be set for real RustFS acceptance");
    let secret_key = std::env::var("QUERVANT_RUSTFS_SECRET_KEY")
        .expect("QUERVANT_RUSTFS_SECRET_KEY must be set for real RustFS acceptance");
    let region = std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned());
    assert!(
        !endpoint.trim().is_empty(),
        "QUERVANT_RUSTFS_ENDPOINT must not be empty"
    );
    assert!(
        !bucket.trim().is_empty(),
        "QUERVANT_RUSTFS_BUCKET must not be empty"
    );
    assert!(
        !access_key.trim().is_empty(),
        "QUERVANT_RUSTFS_ACCESS_KEY must not be empty"
    );
    assert!(
        !secret_key.trim().is_empty(),
        "QUERVANT_RUSTFS_SECRET_KEY must not be empty"
    );
    assert!(
        endpoint.starts_with("http://"),
        "real RustFS acceptance requires an http:// endpoint"
    );
    Env {
        endpoint,
        region,
        bucket,
        access_key,
        secret_key,
    }
}

async fn store(prefix: &str) -> S3ObjectStore {
    let env = require_env();
    let store = S3ObjectStore::new(
        S3Config::rustfs(
            env.endpoint,
            env.region,
            env.bucket,
            env.access_key,
            env.secret_key,
        )
        .with_prefix(prefix)
        .with_timeouts(
            std::time::Duration::from_secs(5),
            std::time::Duration::from_secs(30),
        ),
    )
    .expect("valid config");
    store.create_bucket_if_absent().await.expect("bucket");
    store
}

fn unique_key(name: &str) -> ObjectKey {
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    ObjectKey::parse(format!(
        "pr13/run-{}-{}-{name}-{n}",
        std::process::id(),
        run_id()
    ))
    .unwrap()
}

fn limits() -> TransferLimits {
    TransferLimits::new(16 * 1024 * 1024)
}

async fn put(
    store: &S3ObjectStore,
    key: &ObjectKey,
    body: &[u8],
    precondition: PutPrecondition,
) -> Result<PutOutcome, ObjectStoreError> {
    let descriptor = ContentDescriptor::of(body);
    store
        .put(key, &descriptor, body, precondition, &limits())
        .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires a running pinned RustFS instance"]
async fn s01_concurrent_if_absent_single_winner() {
    let store = store("s01").await;
    let key = unique_key("if-absent");
    let left = put(&store, &key, b"left", PutPrecondition::IfAbsent);
    let right = put(&store, &key, b"right", PutPrecondition::IfAbsent);
    let (left, right) = tokio::join!(left, right);
    let created = [&left, &right]
        .iter()
        .filter(|r| matches!(r, Ok(PutOutcome::Created)))
        .count();
    let conflicts = [&left, &right]
        .iter()
        .filter(|r| matches!(r, Err(ObjectStoreError::Conflict { .. })))
        .count();
    assert_eq!(created, 1, "exactly one create-if-absent winner");
    assert_eq!(conflicts, 1, "the loser observes a typed conflict");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires a running pinned RustFS instance"]
async fn s02_concurrent_if_match_single_winner() {
    let store = store("s02").await;
    let key = unique_key("if-match");
    let base = b"base";
    assert_eq!(
        put(&store, &key, base, PutPrecondition::IfAbsent)
            .await
            .unwrap(),
        PutOutcome::Created
    );
    let base_digest = ContentDigest::sha256_v1(base);
    let left = put(
        &store,
        &key,
        b"candidate-left",
        PutPrecondition::IfMatch(base_digest),
    );
    let right = put(
        &store,
        &key,
        b"candidate-right",
        PutPrecondition::IfMatch(base_digest),
    );
    let (left, right) = tokio::join!(left, right);
    let replaced = [&left, &right]
        .iter()
        .filter(|r| matches!(r, Ok(PutOutcome::Created)))
        .count();
    let precondition = [&left, &right]
        .iter()
        .filter(|r| matches!(r, Err(ObjectStoreError::PreconditionFailed { .. })))
        .count();
    assert_eq!(replaced, 1, "exactly one conditional replacer wins");
    assert_eq!(precondition, 1, "the loser sees a precondition failure");
}

#[tokio::test]
#[ignore = "requires a running pinned RustFS instance"]
async fn s03_read_after_write_exact_bytes() {
    let store = store("s03").await;
    let key = unique_key("raw");
    let body = b"read-after-write payload";
    assert_eq!(
        put(&store, &key, body, PutPrecondition::IfAbsent)
            .await
            .unwrap(),
        PutOutcome::Created
    );
    let got = store.get(&key, None, &limits()).await.unwrap();
    assert_eq!(got, body);
    let metadata = store.head(&key).await.unwrap();
    assert_eq!(metadata.length, body.len() as u64);
    assert_eq!(metadata.digest, ContentDigest::sha256_v1(body));
}

#[tokio::test]
#[ignore = "requires a running pinned RustFS instance"]
async fn s04_exact_ranged_read() {
    let store = store("s04").await;
    let key = unique_key("range");
    let body: Vec<u8> = (0u8..=255).collect();
    assert_eq!(
        put(&store, &key, &body, PutPrecondition::IfAbsent)
            .await
            .unwrap(),
        PutOutcome::Created
    );
    let slice = store
        .get(&key, Some(ByteRange::new(10, 20)), &limits())
        .await
        .unwrap();
    assert_eq!(slice, &body[10..30]);
    let tail = store
        .get(&key, Some(ByteRange::new(250, 6)), &limits())
        .await
        .unwrap();
    assert_eq!(tail, &body[250..256]);
}

#[tokio::test]
#[ignore = "requires a running pinned RustFS instance"]
async fn s08_existing_identical_and_different() {
    let store = store("s08").await;
    let key = unique_key("idempotent");
    assert_eq!(
        put(&store, &key, b"same", PutPrecondition::IfAbsent)
            .await
            .unwrap(),
        PutOutcome::Created
    );
    assert_eq!(
        put(&store, &key, b"same", PutPrecondition::IfAbsent)
            .await
            .unwrap(),
        PutOutcome::AlreadyPresent
    );
    let conflict = put(&store, &key, b"different", PutPrecondition::IfAbsent).await;
    assert!(matches!(conflict, Err(ObjectStoreError::Conflict { .. })));
}

#[tokio::test]
#[ignore = "requires a running pinned RustFS instance"]
async fn s09_rejects_oversize_before_network() {
    let store = store("s09").await;
    let key = unique_key("oversize");
    let body = b"0123456789";
    let descriptor = ContentDescriptor::of(body);
    let tiny = TransferLimits::new(3);
    let error = store
        .put(&key, &descriptor, body, PutPrecondition::IfAbsent, &tiny)
        .await
        .unwrap_err();
    assert!(matches!(error, ObjectStoreError::LimitExceeded { .. }));
}

#[tokio::test]
#[ignore = "requires a running pinned RustFS instance"]
async fn s10_unqualified_endpoint_fails_closed() {
    let env = require_env();
    let store = S3ObjectStore::new(S3Config::new(
        env.endpoint,
        env.region,
        env.bucket,
        env.access_key,
        env.secret_key,
    ))
    .expect("valid config");
    let key = unique_key("unqualified");
    let error = put(&store, &key, b"x", PutPrecondition::IfAbsent)
        .await
        .unwrap_err();
    assert!(matches!(
        error,
        ObjectStoreError::UnsupportedCapability {
            capability: "atomic_create_if_absent"
        }
    ));
    let error = put(
        &store,
        &key,
        b"x",
        PutPrecondition::IfMatch(ContentDigest::sha256_v1(b"y")),
    )
    .await
    .unwrap_err();
    assert!(matches!(
        error,
        ObjectStoreError::UnsupportedCapability {
            capability: "conditional_replace"
        }
    ));
}

#[tokio::test]
#[ignore = "requires a running pinned RustFS instance"]
async fn s11_delete_is_idempotent() {
    let store = store("s11").await;
    let key = unique_key("delete");
    put(&store, &key, b"x", PutPrecondition::IfAbsent)
        .await
        .unwrap();
    store.delete(&key).await.unwrap();
    store.delete(&key).await.unwrap();
    assert!(matches!(
        store.head(&key).await.unwrap_err(),
        ObjectStoreError::NotFound { .. }
    ));
}

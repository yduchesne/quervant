//! H01–H04: deterministic HTTP fault proxy in front of real RustFS.
//!
//! These tests exercise the production `S3ObjectStore` through a loopback proxy
//! that tunnels exact signed requests to a pinned RustFS container and injects
//! deterministic transport/protocol faults. They are `#[ignore]`d by default
//! and require the documented `QUERVANT_RUSTFS_*` environment.

#![cfg(feature = "s3")]

mod support;

use std::sync::atomic::{AtomicU64, Ordering};

use quervant_objectstore::{
    ByteRange, ContentDescriptor, ObjectKey, ObjectStore, ObjectStoreError, PutOutcome,
    PutPrecondition, S3Config, S3ObjectStore, TransferLimits,
};
use support::{Fault, Proxy, Rule};

static COUNTER: AtomicU64 = AtomicU64::new(0);

struct Env {
    endpoint: String,
    region: String,
    bucket: String,
    access_key: String,
    secret_key: String,
}

fn env() -> Option<Env> {
    Some(Env {
        endpoint: std::env::var("QUERVANT_RUSTFS_ENDPOINT").ok()?,
        region: std::env::var("QUERVANT_RUSTFS_REGION").unwrap_or_else(|_| "us-east-1".to_owned()),
        bucket: std::env::var("QUERVANT_RUSTFS_BUCKET").ok()?,
        access_key: std::env::var("QUERVANT_RUSTFS_ACCESS_KEY").ok()?,
        secret_key: std::env::var("QUERVANT_RUSTFS_SECRET_KEY").ok()?,
    })
}

fn parse_host_port(endpoint: &str) -> (String, u16) {
    let rest = endpoint
        .strip_prefix("http://")
        .or_else(|| endpoint.strip_prefix("https://"))
        .unwrap_or(endpoint);
    let rest = rest.trim_end_matches('/');
    match rest.rsplit_once(':') {
        Some((host, port)) => (host.to_owned(), port.parse().expect("port")),
        None => (rest.to_owned(), 80),
    }
}

fn unique_key(name: &str) -> ObjectKey {
    static RUN: std::sync::OnceLock<u128> = std::sync::OnceLock::new();
    let run = *RUN.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    });
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    ObjectKey::parse(format!(
        "pr13-proxy/run-{}-{run}-{name}-{n}",
        std::process::id()
    ))
    .unwrap()
}

fn limits() -> TransferLimits {
    TransferLimits::new(16 * 1024 * 1024)
}

fn store_through(env: &Env, endpoint: &str) -> S3ObjectStore {
    S3ObjectStore::new(
        S3Config::rustfs(
            endpoint.to_owned(),
            env.region.clone(),
            env.bucket.clone(),
            env.access_key.clone(),
            env.secret_key.clone(),
        )
        .with_timeouts(
            std::time::Duration::from_secs(5),
            std::time::Duration::from_secs(10),
        ),
    )
    .expect("valid config")
}

async fn put(
    store: &S3ObjectStore,
    key: &ObjectKey,
    body: &[u8],
) -> Result<PutOutcome, ObjectStoreError> {
    let descriptor = ContentDescriptor::of(body);
    store
        .put(key, &descriptor, body, PutPrecondition::IfAbsent, &limits())
        .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires a running pinned RustFS instance"]
async fn h01_transparent_proxy_preserves_signed_cas_and_ranges() {
    let Some(env) = env() else {
        return;
    };
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let store = store_through(&env, &proxy.endpoint);
    store.create_bucket_if_absent().await.expect("bucket");

    let key = unique_key("h01");
    let body: Vec<u8> = (0..=255).collect();
    assert_eq!(put(&store, &key, &body).await.unwrap(), PutOutcome::Created);
    assert_eq!(store.get(&key, None, &limits()).await.unwrap(), body);
    let slice = store
        .get(&key, Some(ByteRange::new(10, 20)), &limits())
        .await
        .unwrap();
    assert_eq!(slice, &body[10..30]);
    let metadata = store.head(&key).await.unwrap();
    assert_eq!(metadata.digest, ContentDescriptor::of(&body).digest);

    assert!(proxy.observed("PUT", "h01") >= 1);
    assert!(proxy.observed("GET", "h01") >= 2);
    proxy.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires a running pinned RustFS instance"]
async fn h02_truncated_ranged_response_is_a_typed_failure() {
    let Some(env) = env() else {
        return;
    };
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let direct = store_through(&env, &env.endpoint);
    direct.create_bucket_if_absent().await.expect("bucket");
    let key = unique_key("h02");
    let body: Vec<u8> = (0..=255).cycle().take(4096).collect();
    assert_eq!(
        put(&direct, &key, &body).await.unwrap(),
        PutOutcome::Created
    );

    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "h02".to_owned(),
        nth: 1,
        fault: Fault::TruncateBodyAfter(8),
    });
    let store = store_through(&env, &proxy.endpoint);
    let error = store
        .get(&key, Some(ByteRange::new(0, 1024)), &limits())
        .await
        .unwrap_err();
    // A truncated transport is a typed backend/integrity failure, never a
    // silently short success.
    assert!(
        matches!(
            error,
            ObjectStoreError::Backend { .. }
                | ObjectStoreError::Transient { .. }
                | ObjectStoreError::RangeLengthMismatch { .. }
                | ObjectStoreError::LengthMismatch { .. }
        ),
        "unexpected {error:?}"
    );
    proxy.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires a running pinned RustFS instance"]
async fn h03_ranged_request_returning_200_is_rejected() {
    let Some(env) = env() else {
        return;
    };
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let direct = store_through(&env, &env.endpoint);
    direct.create_bucket_if_absent().await.expect("bucket");
    let key = unique_key("h03");
    let body: Vec<u8> = (0..=255).cycle().take(4096).collect();
    assert_eq!(
        put(&direct, &key, &body).await.unwrap(),
        PutOutcome::Created
    );

    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "h03".to_owned(),
        nth: 1,
        fault: Fault::ReplaceStatus200,
    });
    let store = store_through(&env, &proxy.endpoint);
    let error = store
        .get(&key, Some(ByteRange::new(0, 1024)), &limits())
        .await
        .unwrap_err();
    assert!(
        matches!(
            error,
            ObjectStoreError::Backend { .. }
                | ObjectStoreError::RangeLengthMismatch { .. }
                | ObjectStoreError::LengthMismatch { .. }
                | ObjectStoreError::LimitExceeded { .. }
        ),
        "unexpected {error:?}"
    );
    proxy.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires a running pinned RustFS instance"]
async fn h04_invalid_content_range_is_rejected() {
    let Some(env) = env() else {
        return;
    };
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let direct = store_through(&env, &env.endpoint);
    direct.create_bucket_if_absent().await.expect("bucket");
    let key = unique_key("h04");
    let body: Vec<u8> = (0..=255).cycle().take(4096).collect();
    assert_eq!(
        put(&direct, &key, &body).await.unwrap(),
        PutOutcome::Created
    );

    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "h04".to_owned(),
        nth: 1,
        fault: Fault::SetContentRange("bytes 999-1999/4096".to_owned()),
    });
    let store = store_through(&env, &proxy.endpoint);
    let error = store
        .get(&key, Some(ByteRange::new(0, 1024)), &limits())
        .await
        .unwrap_err();
    assert!(
        matches!(
            error,
            ObjectStoreError::Backend { .. } | ObjectStoreError::RangeLengthMismatch { .. }
        ),
        "unexpected {error:?}"
    );
    proxy.stop().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires a running pinned RustFS instance"]
async fn h06_transient_503_then_success() {
    // The adapter itself has retries disabled; the retry belongs to the core
    // transfer layer. This test only confirms the proxy delivers a typed
    // transient 503 to the production adapter.
    let Some(env) = env() else {
        return;
    };
    let (host, port) = parse_host_port(&env.endpoint);
    let proxy = Proxy::start(&host, port).await;
    let direct = store_through(&env, &env.endpoint);
    direct.create_bucket_if_absent().await.expect("bucket");
    let key = unique_key("h06");
    let body = b"transient".to_vec();
    assert_eq!(
        put(&direct, &key, &body).await.unwrap(),
        PutOutcome::Created
    );

    proxy.add_rule(Rule {
        method: "GET".to_owned(),
        key_contains: "h06".to_owned(),
        nth: 1,
        fault: Fault::Return503,
    });
    let store = store_through(&env, &proxy.endpoint);
    let error = store.get(&key, None, &limits()).await.unwrap_err();
    assert!(
        matches!(error, ObjectStoreError::Transient { .. }),
        "unexpected {error:?}"
    );
    // The next request is not faulted and succeeds.
    let second = store.get(&key, None, &limits()).await.unwrap();
    assert_eq!(second, body);
    assert_eq!(proxy.observed("GET", "h06"), 2);
    proxy.stop().await;
}

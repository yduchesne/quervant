//! Production S3-compatible [`ObjectStore`] adapter (opt-in `s3` feature).
//!
//! This adapter targets the **S3 REST API** as implemented by RustFS and AWS
//! S3. It is built on the audited `aws-sdk-s3` client; no S3 request signing or
//! cryptographic primitive is implemented here (see `AGENTS.md`).
//!
//! # Provider qualification
//!
//! S3-compatible services do **not** all implement conditional publication
//! atomically. The adapter therefore advertises capabilities only for an
//! endpoint the caller has explicitly qualified with a real concurrent probe
//! (see `docs/pr-artifacts/pr-13/preimplementation-correctness.md`). A
//! configuration that has not been qualified advertises
//! [`ObjectStoreCapabilities::NONE`] and every mutating call fails closed with
//! [`ObjectStoreError::UnsupportedCapability`].
//!
//! # Digest versus ETag
//!
//! [`PutPrecondition::IfMatch`] means "replace the object whose **SHA-256**
//! equals this digest". S3 `If-Match` compares the object **ETag**, which is
//! not necessarily SHA-256. The adapter therefore:
//!
//! 1. `HEAD`s the current object and captures the ETag;
//! 2. `GET`s the current bytes (bounded) and verifies their SHA-256 equals the
//!    caller digest;
//! 3. issues a conditional `PUT` with that ETag.
//!
//! The conditional `PUT` — never the preceding `HEAD`/`GET` — is the atomic
//! concurrency guard. An ETag is never interpreted as a content digest.
//!
//! # No hidden retries
//!
//! The AWS SDK retry layer is disabled. Retry policy belongs to the caller, as
//! required by the provider-neutral contract.

use std::fmt;
use std::time::Duration;

use aws_credential_types::Credentials;
use aws_sdk_s3::config::{
    BehaviorVersion, Region, RequestChecksumCalculation, ResponseChecksumValidation,
};
use aws_sdk_s3::error::SdkError;
use aws_sdk_s3::primitives::ByteStream;
use aws_smithy_runtime_api::client::orchestrator::HttpResponse;
use aws_smithy_types::retry::RetryConfig;
use aws_smithy_types::timeout::TimeoutConfig;
use tokio::io::AsyncReadExt;

use crate::capability::ObjectStoreCapabilities;
use crate::contract::ObjectStore;
use crate::digest::{ContentDescriptor, ContentDigest};
use crate::error::ObjectStoreError;
use crate::key::{ObjectKey, validate_key};
use crate::transfer::{ByteRange, ObjectMetadata, PutOutcome, PutPrecondition, TransferLimits};

/// The RustFS reference capability set, verified by a real concurrent probe.
///
/// Only use this after running the qualification probe against the exact
/// provider deployment. It is not a claim about arbitrary S3-compatible
/// services.
#[must_use]
pub const fn rustfs_reference_capabilities() -> ObjectStoreCapabilities {
    ObjectStoreCapabilities {
        atomic_create_if_absent: true,
        conditional_replace: true,
        read_after_write: true,
        range_read: true,
        list: false,
    }
}

/// Configuration for [`S3ObjectStore`].
#[derive(Clone)]
pub struct S3Config {
    endpoint: String,
    region: String,
    bucket: String,
    prefix: String,
    access_key_id: String,
    secret_access_key: String,
    session_token: Option<String>,
    force_path_style: bool,
    connect_timeout: Duration,
    request_timeout: Duration,
    capabilities: ObjectStoreCapabilities,
}

impl fmt::Debug for S3Config {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("S3Config")
            .field("endpoint", &self.endpoint)
            .field("region", &self.region)
            .field("bucket", &self.bucket)
            .field("prefix", &self.prefix)
            .field("force_path_style", &self.force_path_style)
            .field("connect_timeout", &self.connect_timeout)
            .field("request_timeout", &self.request_timeout)
            .field("capabilities", &self.capabilities)
            .finish_non_exhaustive()
    }
}

impl S3Config {
    /// Create an unqualified configuration.
    ///
    /// The endpoint starts with [`ObjectStoreCapabilities::NONE`]; the caller
    /// must call [`S3Config::with_capabilities`] after a successful concurrent
    /// qualification probe. This makes accidental use of unverified endpoint
    /// semantics fail closed.
    #[must_use]
    pub fn new(
        endpoint: impl Into<String>,
        region: impl Into<String>,
        bucket: impl Into<String>,
        access_key_id: impl Into<String>,
        secret_access_key: impl Into<String>,
    ) -> Self {
        Self {
            endpoint: endpoint.into(),
            region: region.into(),
            bucket: bucket.into(),
            prefix: String::new(),
            access_key_id: access_key_id.into(),
            secret_access_key: secret_access_key.into(),
            session_token: None,
            force_path_style: true,
            connect_timeout: Duration::from_secs(10),
            request_timeout: Duration::from_secs(30),
            capabilities: ObjectStoreCapabilities::NONE,
        }
    }

    /// Create a configuration qualified with the verified RustFS reference
    /// capability set.
    #[must_use]
    pub fn rustfs(
        endpoint: impl Into<String>,
        region: impl Into<String>,
        bucket: impl Into<String>,
        access_key_id: impl Into<String>,
        secret_access_key: impl Into<String>,
    ) -> Self {
        Self::new(endpoint, region, bucket, access_key_id, secret_access_key)
            .with_capabilities(rustfs_reference_capabilities())
    }

    /// Set the advertised capabilities (from a provider qualification probe).
    #[must_use]
    pub const fn with_capabilities(mut self, capabilities: ObjectStoreCapabilities) -> Self {
        self.capabilities = capabilities;
        self
    }

    /// Set the optional bucket namespace prefix applied to every object key.
    ///
    /// The prefix is validated as part of the combined key. It must not begin
    /// or end with `/`.
    #[must_use]
    pub fn with_prefix(mut self, prefix: impl Into<String>) -> Self {
        self.prefix = prefix.into();
        self
    }

    /// Set path-style addressing (required by most S3-compatible endpoints).
    #[must_use]
    pub const fn with_force_path_style(mut self, force_path_style: bool) -> Self {
        self.force_path_style = force_path_style;
        self
    }

    /// Override the connect and request timeouts.
    #[must_use]
    pub const fn with_timeouts(mut self, connect: Duration, request: Duration) -> Self {
        self.connect_timeout = connect;
        self.request_timeout = request;
        self
    }

    /// Set an optional session token.
    #[must_use]
    pub fn with_session_token(mut self, token: impl Into<String>) -> Self {
        self.session_token = Some(token.into());
        self
    }

    fn validate(&self) -> Result<(), ObjectStoreError> {
        if self.endpoint.trim().is_empty() {
            return Err(ObjectStoreError::Backend {
                detail: "s3 endpoint must not be empty".to_owned(),
            });
        }
        if self.bucket.trim().is_empty() {
            return Err(ObjectStoreError::Backend {
                detail: "s3 bucket must not be empty".to_owned(),
            });
        }
        if self.prefix.starts_with('/') || self.prefix.ends_with('/') {
            return Err(ObjectStoreError::InvalidKey {
                reason: crate::key::KeyError::AbsolutePath,
            });
        }
        if !self.prefix.is_empty() {
            // Validate the prefix itself as a standalone key.
            validate_key(&self.prefix).map_err(|reason| ObjectStoreError::InvalidKey { reason })?;
        }
        Ok(())
    }

    #[cfg(test)]
    fn full_key(&self, key: &ObjectKey) -> Result<String, ObjectStoreError> {
        let full = if self.prefix.is_empty() {
            key.as_str().to_owned()
        } else {
            format!("{}/{}", self.prefix, key.as_str())
        };
        validate_key(&full).map_err(|reason| ObjectStoreError::InvalidKey { reason })?;
        Ok(full)
    }
}

/// A production S3-compatible [`ObjectStore`].
pub struct S3ObjectStore {
    client: aws_sdk_s3::Client,
    bucket: String,
    prefix: String,
    capabilities: ObjectStoreCapabilities,
}

impl fmt::Debug for S3ObjectStore {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("S3ObjectStore")
            .field("bucket", &self.bucket)
            .field("prefix", &self.prefix)
            .field("capabilities", &self.capabilities)
            .finish_non_exhaustive()
    }
}

impl S3ObjectStore {
    /// Construct an adapter from configuration.
    ///
    /// Returns a typed error for an empty endpoint/bucket or an invalid prefix,
    /// before any network client is created.
    pub fn new(config: S3Config) -> Result<Self, ObjectStoreError> {
        config.validate()?;
        let credentials = match &config.session_token {
            Some(token) => Credentials::new(
                config.access_key_id.clone(),
                config.secret_access_key.clone(),
                Some(token.clone()),
                None,
                "quervant-static",
            ),
            None => Credentials::new(
                config.access_key_id.clone(),
                config.secret_access_key.clone(),
                None,
                None,
                "quervant-static",
            ),
        };
        // A plain-HTTP connector: the reference provider is a local RustFS
        // endpoint. HTTPS/TLS is a separate, explicit build feature.
        let http_client = aws_smithy_http_client::Builder::new().build_http();
        let timeout = TimeoutConfig::builder()
            .connect_timeout(config.connect_timeout)
            .operation_timeout(config.request_timeout)
            .operation_attempt_timeout(config.request_timeout)
            .build();
        let sdk_config = aws_sdk_s3::Config::builder()
            .behavior_version(BehaviorVersion::latest())
            .region(Region::new(config.region.clone()))
            .endpoint_url(config.endpoint.clone())
            .credentials_provider(credentials)
            .force_path_style(config.force_path_style)
            .http_client(http_client)
            .timeout_config(timeout)
            .retry_config(RetryConfig::disabled())
            .request_checksum_calculation(RequestChecksumCalculation::WhenRequired)
            .response_checksum_validation(ResponseChecksumValidation::WhenRequired)
            .build();
        let client = aws_sdk_s3::Client::from_conf(sdk_config);
        Ok(Self {
            client,
            bucket: config.bucket,
            prefix: config.prefix,
            capabilities: config.capabilities,
        })
    }

    /// The advertised capability set.
    #[must_use]
    pub const fn advertised_capabilities(&self) -> ObjectStoreCapabilities {
        self.capabilities
    }

    /// Create the configured bucket if it does not already exist.
    ///
    /// This is an explicit provisioning helper, never called implicitly. A
    /// bucket that already exists (HTTP 409) is treated as success.
    pub async fn create_bucket_if_absent(&self) -> Result<(), ObjectStoreError> {
        let result = self
            .client
            .create_bucket()
            .bucket(&self.bucket)
            .send()
            .await;
        match result {
            Ok(_) => Ok(()),
            Err(error) if is_status(&error, 409) => Ok(()),
            Err(error) => Err(map_sdk_error(error)),
        }
    }

    fn full_key(&self, key: &ObjectKey) -> Result<String, ObjectStoreError> {
        let full = if self.prefix.is_empty() {
            key.as_str().to_owned()
        } else {
            format!("{}/{}", self.prefix, key.as_str())
        };
        validate_key(&full).map_err(|reason| ObjectStoreError::InvalidKey { reason })?;
        Ok(full)
    }

    /// Read a whole object with a hard byte cap enforced while streaming.
    async fn get_bounded(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        max_bytes: u64,
    ) -> Result<Vec<u8>, ObjectStoreError> {
        let full = self.full_key(key)?;
        let mut request = self.client.get_object().bucket(&self.bucket).key(&full);
        if let Some(range) = range {
            let end = range
                .end()
                .ok_or(ObjectStoreError::InvalidRange {
                    offset: range.offset,
                    length: range.length,
                    object_length: None,
                })?
                .checked_sub(1)
                .ok_or(ObjectStoreError::InvalidRange {
                    offset: range.offset,
                    length: range.length,
                    object_length: None,
                })?;
            request = request.range(format!("bytes={}-{}", range.offset, end));
        }
        let output = request.send().await.map_err(map_sdk_error)?;
        let content_length = output.content_length();
        if let Some(length) = content_length {
            if length < 0 {
                return Err(ObjectStoreError::Backend {
                    detail: "negative content length".to_owned(),
                });
            }
            if length as u64 > max_bytes {
                return Err(ObjectStoreError::LimitExceeded {
                    limit: max_bytes,
                    requested: length as u64,
                });
            }
        }
        if let Some(range) = range {
            // A ranged response must be exactly the requested substring. A
            // missing/incorrect Content-Range or a short/long body is a typed
            // error, never partial success.
            let content_range =
                output
                    .content_range()
                    .ok_or_else(|| ObjectStoreError::Backend {
                        detail: "ranged GET returned no Content-Range".to_owned(),
                    })?;
            validate_content_range(content_range, range)?;
            if let Some(length) = content_length {
                if length as u64 != range.length {
                    return Err(ObjectStoreError::RangeLengthMismatch {
                        expected: range.length,
                        actual: length as u64,
                    });
                }
            }
        }
        let mut reader = output.body.into_async_read();
        let mut buffer = Vec::new();
        let mut chunk = [0u8; 64 * 1024];
        loop {
            let read =
                reader
                    .read(&mut chunk)
                    .await
                    .map_err(|error| ObjectStoreError::Backend {
                        detail: format!("response body read failed: {error}"),
                    })?;
            if read == 0 {
                break;
            }
            if buffer.len() as u64 + read as u64 > max_bytes {
                return Err(ObjectStoreError::LimitExceeded {
                    limit: max_bytes,
                    requested: buffer.len() as u64 + read as u64,
                });
            }
            buffer.extend_from_slice(&chunk[..read]);
        }
        if let Some(range) = range {
            if buffer.len() as u64 != range.length {
                return Err(ObjectStoreError::RangeLengthMismatch {
                    expected: range.length,
                    actual: buffer.len() as u64,
                });
            }
        }
        Ok(buffer)
    }
}

/// Parse and validate an S3 `Content-Range` header against the request.
///
/// Accepts `bytes <start>-<end>/<total|*>` for the exact requested range.
fn validate_content_range(header: &str, range: ByteRange) -> Result<(), ObjectStoreError> {
    let invalid = || ObjectStoreError::Backend {
        detail: "malformed Content-Range".to_owned(),
    };
    let rest = header.strip_prefix("bytes ").ok_or_else(invalid)?;
    let (span, _total) = rest.split_once('/').ok_or_else(invalid)?;
    let (start, end) = span.split_once('-').ok_or_else(invalid)?;
    let start: u64 = start.trim().parse().map_err(|_| invalid())?;
    let end: u64 = end.trim().parse().map_err(|_| invalid())?;
    let expected_end = range.end().and_then(|end| end.checked_sub(1));
    if Some(start) != Some(range.offset) || Some(end) != expected_end || end < start {
        return Err(ObjectStoreError::RangeLengthMismatch {
            expected: range.length,
            actual: end.saturating_sub(start).saturating_add(1),
        });
    }
    Ok(())
}

fn status_of<E: fmt::Debug>(error: &SdkError<E, HttpResponse>) -> Option<u16> {
    error
        .raw_response()
        .map(|response| response.status().as_u16())
}

fn map_sdk_error<E>(error: SdkError<E, HttpResponse>) -> ObjectStoreError
where
    E: fmt::Debug + fmt::Display,
{
    match &error {
        SdkError::TimeoutError(_) => ObjectStoreError::Timeout,
        SdkError::DispatchFailure(_) => ObjectStoreError::Transient {
            detail: "request dispatch failed".to_owned(),
        },
        SdkError::ConstructionFailure(_) => ObjectStoreError::Backend {
            detail: "request construction failed".to_owned(),
        },
        SdkError::ResponseError(_) => ObjectStoreError::Transient {
            detail: "unexpected service response".to_owned(),
        },
        SdkError::ServiceError(_) => match status_of(&error) {
            Some(404) => ObjectStoreError::Backend {
                detail: "not found".to_owned(),
            },
            Some(412) => ObjectStoreError::Backend {
                detail: "precondition failed".to_owned(),
            },
            Some(403) => ObjectStoreError::Backend {
                detail: "access denied".to_owned(),
            },
            Some(416) => ObjectStoreError::Backend {
                detail: "requested range not satisfiable".to_owned(),
            },
            Some(status) if (500..600).contains(&status) => ObjectStoreError::Transient {
                detail: format!("service error status {status}"),
            },
            Some(status) => ObjectStoreError::Backend {
                detail: format!("service error status {status}"),
            },
            None => ObjectStoreError::Backend {
                detail: "service error".to_owned(),
            },
        },
        _ => ObjectStoreError::Backend {
            detail: "unrecognized SDK failure".to_owned(),
        },
    }
}

fn is_status<E: fmt::Debug>(error: &SdkError<E, HttpResponse>, status: u16) -> bool {
    status_of(error) == Some(status)
}

impl ObjectStore for S3ObjectStore {
    fn capabilities(&self) -> ObjectStoreCapabilities {
        self.capabilities
    }

    async fn put(
        &self,
        key: &ObjectKey,
        expected: &ContentDescriptor,
        body: &[u8],
        precondition: PutPrecondition,
        limits: &TransferLimits,
    ) -> Result<PutOutcome, ObjectStoreError> {
        // 1. Preverify declared identity before any network I/O.
        if body.len() as u64 != expected.length {
            return Err(ObjectStoreError::LengthMismatch {
                expected: expected.length,
                actual: body.len() as u64,
            });
        }
        if body.len() as u64 > limits.max_bytes {
            return Err(ObjectStoreError::LimitExceeded {
                limit: limits.max_bytes,
                requested: body.len() as u64,
            });
        }
        let actual = ContentDigest::sha256_v1(body);
        if actual != expected.digest {
            return Err(ObjectStoreError::IntegrityMismatch {
                expected: expected.digest,
                actual,
            });
        }
        let full = self.full_key(key)?;

        match precondition {
            PutPrecondition::IfAbsent => {
                if !self.capabilities.atomic_create_if_absent {
                    return Err(ObjectStoreError::UnsupportedCapability {
                        capability: "atomic_create_if_absent",
                    });
                }
                let result = self
                    .client
                    .put_object()
                    .bucket(&self.bucket)
                    .key(&full)
                    .if_none_match("*")
                    .body(ByteStream::from(body.to_vec()))
                    .send()
                    .await;
                match result {
                    Ok(_) => Ok(PutOutcome::Created),
                    Err(error) if is_status(&error, 412) => {
                        // The object now exists. Return AlreadyPresent only for
                        // byte-identical content; otherwise a typed conflict.
                        let existing = self.get_bounded(key, None, limits.max_bytes).await?;
                        if existing == body {
                            Ok(PutOutcome::AlreadyPresent)
                        } else {
                            Err(ObjectStoreError::Conflict { key: key.clone() })
                        }
                    }
                    Err(error) => Err(map_sdk_error(error)),
                }
            }
            PutPrecondition::IfMatch(digest) => {
                if !self.capabilities.conditional_replace {
                    return Err(ObjectStoreError::UnsupportedCapability {
                        capability: "conditional_replace",
                    });
                }
                // Capture the current ETag and independently verify the current
                // bytes' SHA-256 equals the caller-supplied digest.
                let head = self
                    .client
                    .head_object()
                    .bucket(&self.bucket)
                    .key(&full)
                    .send()
                    .await
                    .map_err(|error| {
                        if is_status(&error, 404) {
                            ObjectStoreError::NotFound { key: key.clone() }
                        } else {
                            map_sdk_error(error)
                        }
                    })?;
                let etag = head.e_tag().ok_or_else(|| ObjectStoreError::Backend {
                    detail: "HEAD returned no ETag".to_owned(),
                })?;
                let current = self.get_bounded(key, None, limits.max_bytes).await?;
                if ContentDigest::sha256_v1(&current) != digest {
                    return Err(ObjectStoreError::PreconditionFailed { key: key.clone() });
                }
                let result = self
                    .client
                    .put_object()
                    .bucket(&self.bucket)
                    .key(&full)
                    .if_match(etag)
                    .body(ByteStream::from(body.to_vec()))
                    .send()
                    .await;
                match result {
                    Ok(_) => Ok(PutOutcome::Created),
                    Err(error) if is_status(&error, 412) => {
                        Err(ObjectStoreError::PreconditionFailed { key: key.clone() })
                    }
                    Err(error) => Err(map_sdk_error(error)),
                }
            }
        }
    }

    async fn get(
        &self,
        key: &ObjectKey,
        range: Option<ByteRange>,
        limits: &TransferLimits,
    ) -> Result<Vec<u8>, ObjectStoreError> {
        if let Some(range) = range {
            if range.length == 0 {
                return Err(ObjectStoreError::InvalidRange {
                    offset: range.offset,
                    length: range.length,
                    object_length: None,
                });
            }
            if range.end().is_none() {
                return Err(ObjectStoreError::InvalidRange {
                    offset: range.offset,
                    length: range.length,
                    object_length: None,
                });
            }
            if range.length > limits.max_bytes {
                return Err(ObjectStoreError::LimitExceeded {
                    limit: limits.max_bytes,
                    requested: range.length,
                });
            }
            if !self.capabilities.range_read {
                return Err(ObjectStoreError::UnsupportedCapability {
                    capability: "range_read",
                });
            }
        }
        match self.get_bounded(key, range, limits.max_bytes).await {
            Err(ObjectStoreError::Backend { detail }) if detail == "not found" => {
                Err(ObjectStoreError::NotFound { key: key.clone() })
            }
            other => other,
        }
    }

    async fn head(&self, key: &ObjectKey) -> Result<ObjectMetadata, ObjectStoreError> {
        let full = self.full_key(key)?;
        // ETag is not a content digest. Produce a real SHA-256 by reading the
        // whole object under a bounded cap.
        let head = self
            .client
            .head_object()
            .bucket(&self.bucket)
            .key(&full)
            .send()
            .await
            .map_err(|error| {
                if is_status(&error, 404) {
                    ObjectStoreError::NotFound { key: key.clone() }
                } else {
                    map_sdk_error(error)
                }
            })?;
        let length = match head.content_length() {
            Some(length) if length >= 0 => length as u64,
            _ => {
                return Err(ObjectStoreError::Backend {
                    detail: "HEAD returned no usable content length".to_owned(),
                });
            }
        };
        // A bounded whole GET both verifies length and yields the digest. The
        // transfer limit is the object length (a caller-provided cap is
        // enforced by `get`); `head` has no separate limit parameter.
        let limits = TransferLimits::new(length.max(1));
        let bytes = self.get_bounded(key, None, limits.max_bytes).await?;
        if bytes.len() as u64 != length {
            return Err(ObjectStoreError::LengthMismatch {
                expected: length,
                actual: bytes.len() as u64,
            });
        }
        Ok(ObjectMetadata::new(
            key.clone(),
            length,
            ContentDigest::sha256_v1(&bytes),
        ))
    }

    async fn delete(&self, key: &ObjectKey) -> Result<(), ObjectStoreError> {
        let full = self.full_key(key)?;
        // Deleting an absent object is idempotent.
        self.client
            .delete_object()
            .bucket(&self.bucket)
            .key(&full)
            .send()
            .await
            .map_err(map_sdk_error)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_content_range_exactly() {
        let range = ByteRange::new(10, 5);
        assert!(validate_content_range("bytes 10-14/100", range).is_ok());
        assert!(validate_content_range("bytes 10-14/*", range).is_ok());
        assert!(validate_content_range("bytes 11-15/100", range).is_err());
        assert!(validate_content_range("bytes 10-15/100", range).is_err());
        assert!(validate_content_range("10-14/100", range).is_err());
        assert!(validate_content_range("bytes 14-10/100", range).is_err());
        assert!(validate_content_range("bytes 10-14", range).is_err());
        assert!(validate_content_range("bytes x-y/100", range).is_err());
    }

    #[test]
    fn config_requires_qualification() {
        let config = S3Config::new("http://127.0.0.1:9000", "us-east-1", "b", "k", "s");
        assert_eq!(config.capabilities, ObjectStoreCapabilities::NONE);
        let qualified = config
            .clone()
            .with_capabilities(rustfs_reference_capabilities());
        assert!(qualified.capabilities.atomic_create_if_absent);
        assert!(qualified.capabilities.conditional_replace);
        assert!(qualified.capabilities.range_read);
    }

    #[test]
    fn config_rejects_bad_prefix_and_empty_fields() {
        let base = || S3Config::new("http://127.0.0.1:9000", "us-east-1", "b", "k", "s");
        assert!(base().validate().is_ok());
        assert!(base().with_prefix("/lead").validate().is_err());
        assert!(base().with_prefix("trail/").validate().is_err());
        assert!(base().with_prefix("a/../b").validate().is_err());
        assert!(base().with_prefix("a/b").validate().is_ok());
        assert!(
            S3Config::new("", "us-east-1", "b", "k", "s")
                .validate()
                .is_err()
        );
        assert!(
            S3Config::new("http://x", "us-east-1", "", "k", "s")
                .validate()
                .is_err()
        );
    }

    #[test]
    fn prefix_is_composed_and_validated() {
        let config = S3Config::new("http://x", "r", "b", "k", "s").with_prefix("idx/one");
        let key = ObjectKey::parse("index/CURRENT").unwrap();
        assert_eq!(config.full_key(&key).unwrap(), "idx/one/index/CURRENT");
        let plain = S3Config::new("http://x", "r", "b", "k", "s");
        assert_eq!(plain.full_key(&key).unwrap(), "index/CURRENT");
    }
}

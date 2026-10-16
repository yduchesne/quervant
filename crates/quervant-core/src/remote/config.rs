//! Remote-backed index configuration and key mapping (PR 13).
//!
//! A remote index stores the **same** immutable codecs as a local index under a
//! single validated object prefix `P`. The logical key grammar is unchanged:
//! the layout remains `index/CURRENT`, `index/manifests/g-<16hex>.manifest`,
//! `index/segments/<digest>.seg` and `index/state/<digest>.state`. `P` is
//! prepended at the object-store boundary, so no persisted format changes.

use std::path::PathBuf;
use std::time::Duration;

use quervant_objectstore::{ObjectKey, validate_key};

use crate::index::{IndexError, IndexResult};
use crate::storage::CacheConfig;

/// Default number of segments materialized concurrently.
pub const DEFAULT_MAX_CONCURRENT_SEGMENT_FILLS: usize = 4;
/// Hard ceiling for concurrent segment fills.
pub const HARD_MAX_CONCURRENT_SEGMENT_FILLS: usize = 32;
/// Default number of concurrent ranges within one segment.
pub const DEFAULT_MAX_CONCURRENT_RANGES: usize = 4;
/// Hard ceiling for concurrent ranges within one segment.
pub const HARD_MAX_CONCURRENT_RANGES: usize = 16;
/// Default ceiling for concurrent HTTP requests.
pub const DEFAULT_MAX_TOTAL_HTTP_REQUESTS: usize = 16;
/// Hard ceiling for concurrent HTTP requests.
pub const HARD_MAX_TOTAL_HTTP_REQUESTS: usize = 64;
/// Default aggregate live response bytes (64 MiB).
pub const DEFAULT_MAX_AGGREGATE_RESPONSE_BYTES: u64 = 64 * 1024 * 1024;
/// Hard aggregate live response byte ceiling (1 GiB).
pub const HARD_MAX_AGGREGATE_RESPONSE_BYTES: u64 = 1024 * 1024 * 1024;
/// Default byte length at or above which a ranged download is used (32 MiB).
pub const DEFAULT_RANGE_THRESHOLD: u64 = 32 * 1024 * 1024;
/// Hard range-threshold ceiling (1 GiB).
pub const HARD_RANGE_THRESHOLD: u64 = 1024 * 1024 * 1024;
/// Default ranged chunk size (8 MiB).
pub const DEFAULT_CHUNK_SIZE: u64 = 8 * 1024 * 1024;
/// Hard ranged chunk-size ceiling (64 MiB).
pub const HARD_CHUNK_SIZE: u64 = 64 * 1024 * 1024;
/// Default retries per request.
pub const DEFAULT_MAX_RETRIES: u32 = 2;
/// Hard retry ceiling.
pub const HARD_MAX_RETRIES: u32 = 5;
/// Default per-request timeout.
pub const DEFAULT_REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
/// Hard per-request timeout ceiling.
pub const HARD_REQUEST_TIMEOUT: Duration = Duration::from_secs(300);
/// Default temporary-disk ceiling (512 MiB).
pub const DEFAULT_MAX_TEMP_DISK_BYTES: u64 = 512 * 1024 * 1024;
/// Hard temporary-disk ceiling (16 GiB).
pub const HARD_MAX_TEMP_DISK_BYTES: u64 = 16 * 1024 * 1024 * 1024;

/// A validated remote index object prefix `P`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoteKeyPrefix(String);

impl RemoteKeyPrefix {
    /// Parse and validate an index prefix.
    ///
    /// The prefix must be a valid non-empty object-key component sequence so a
    /// combined key can never escape the intended namespace.
    pub fn parse(prefix: impl Into<String>) -> IndexResult<Self> {
        let prefix = prefix.into();
        if prefix.is_empty() {
            return Err(IndexError::InvalidCurrent {
                detail: "remote index prefix must not be empty".to_owned(),
            });
        }
        validate_key(&prefix).map_err(|reason| IndexError::InvalidCurrent {
            detail: format!("invalid remote index prefix: {reason}"),
        })?;
        Ok(Self(prefix))
    }

    /// The prefix as a string slice.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Map a logical storage key `K` to the physical object key `P + "/" + K`.
    pub fn object_key(&self, logical: &str) -> IndexResult<ObjectKey> {
        let full = format!("{}/{}", self.0, logical);
        ObjectKey::parse(full).map_err(|reason| IndexError::InvalidCurrent {
            detail: format!("invalid combined remote key: {reason}"),
        })
    }

    /// Map a logical [`crate::storage::StorageKey`].
    pub fn key_for(&self, logical: &crate::storage::StorageKey) -> IndexResult<ObjectKey> {
        self.object_key(logical.as_str())
    }

    /// Whether `key` begins with this prefix's namespace.
    #[must_use]
    pub fn contains(&self, key: &str) -> bool {
        key.strip_prefix(&self.0)
            .is_some_and(|rest| rest.starts_with('/'))
    }
}

/// Bounded whole-object and parallel-ranged download policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RemoteTransferConfig {
    max_concurrent_segment_fills: usize,
    max_concurrent_ranges_per_segment: usize,
    max_total_http_requests: usize,
    max_aggregate_response_bytes: u64,
    range_threshold: u64,
    chunk_size: u64,
    max_retries: u32,
    request_timeout: Duration,
    max_temp_disk_bytes: u64,
}

impl Default for RemoteTransferConfig {
    fn default() -> Self {
        Self {
            max_concurrent_segment_fills: DEFAULT_MAX_CONCURRENT_SEGMENT_FILLS,
            max_concurrent_ranges_per_segment: DEFAULT_MAX_CONCURRENT_RANGES,
            max_total_http_requests: DEFAULT_MAX_TOTAL_HTTP_REQUESTS,
            max_aggregate_response_bytes: DEFAULT_MAX_AGGREGATE_RESPONSE_BYTES,
            range_threshold: DEFAULT_RANGE_THRESHOLD,
            chunk_size: DEFAULT_CHUNK_SIZE,
            max_retries: DEFAULT_MAX_RETRIES,
            request_timeout: DEFAULT_REQUEST_TIMEOUT,
            max_temp_disk_bytes: DEFAULT_MAX_TEMP_DISK_BYTES,
        }
    }
}

/// Why a transfer configuration was rejected.
fn invalid(detail: impl Into<String>) -> IndexError {
    IndexError::InvalidConfiguration {
        detail: detail.into(),
    }
}

impl RemoteTransferConfig {
    /// The maximum number of segments materialized concurrently.
    #[must_use]
    pub const fn max_concurrent_segment_fills(&self) -> usize {
        self.max_concurrent_segment_fills
    }

    /// The maximum number of concurrent ranges within one segment.
    #[must_use]
    pub const fn max_concurrent_ranges_per_segment(&self) -> usize {
        self.max_concurrent_ranges_per_segment
    }

    /// The maximum number of concurrent HTTP requests across all segments.
    #[must_use]
    pub const fn max_total_http_requests(&self) -> usize {
        self.max_total_http_requests
    }

    /// The aggregate live response byte ceiling.
    #[must_use]
    pub const fn max_aggregate_response_bytes(&self) -> u64 {
        self.max_aggregate_response_bytes
    }

    /// The byte length at or above which ranged download is used.
    #[must_use]
    pub const fn range_threshold(&self) -> u64 {
        self.range_threshold
    }

    /// The ranged chunk size.
    #[must_use]
    pub const fn chunk_size(&self) -> u64 {
        self.chunk_size
    }

    /// The maximum retries per request.
    #[must_use]
    pub const fn max_retries(&self) -> u32 {
        self.max_retries
    }

    /// The per-request timeout.
    #[must_use]
    pub const fn request_timeout(&self) -> Duration {
        self.request_timeout
    }

    /// The temporary-disk byte ceiling.
    #[must_use]
    pub const fn max_temp_disk_bytes(&self) -> u64 {
        self.max_temp_disk_bytes
    }

    /// Replace the concurrent segment-fill ceiling.
    #[must_use]
    pub const fn with_max_concurrent_segment_fills(mut self, value: usize) -> Self {
        self.max_concurrent_segment_fills = value;
        self
    }

    /// Replace the per-segment concurrent range ceiling.
    #[must_use]
    pub const fn with_max_concurrent_ranges(mut self, value: usize) -> Self {
        self.max_concurrent_ranges_per_segment = value;
        self
    }

    /// Replace the global concurrent request ceiling.
    #[must_use]
    pub const fn with_max_total_http_requests(mut self, value: usize) -> Self {
        self.max_total_http_requests = value;
        self
    }

    /// Replace the aggregate live response byte ceiling.
    #[must_use]
    pub const fn with_max_aggregate_response_bytes(mut self, value: u64) -> Self {
        self.max_aggregate_response_bytes = value;
        self
    }

    /// Replace the ranged-download threshold.
    #[must_use]
    pub const fn with_range_threshold(mut self, value: u64) -> Self {
        self.range_threshold = value;
        self
    }

    /// Replace the ranged chunk size.
    #[must_use]
    pub const fn with_chunk_size(mut self, value: u64) -> Self {
        self.chunk_size = value;
        self
    }

    /// Replace the per-request retry ceiling.
    #[must_use]
    pub const fn with_max_retries(mut self, value: u32) -> Self {
        self.max_retries = value;
        self
    }

    /// Replace the per-request timeout.
    #[must_use]
    pub const fn with_request_timeout(mut self, value: Duration) -> Self {
        self.request_timeout = value;
        self
    }

    /// Replace the temporary-disk ceiling.
    #[must_use]
    pub const fn with_max_temp_disk_bytes(mut self, value: u64) -> Self {
        self.max_temp_disk_bytes = value;
        self
    }

    /// Validate all bounds against zero, ceilings and consistency.
    ///
    /// Rejects rather than silently clamping.
    pub fn validate(&self) -> IndexResult<()> {
        check_bounded_usize(
            "max_concurrent_segment_fills",
            self.max_concurrent_segment_fills,
            HARD_MAX_CONCURRENT_SEGMENT_FILLS,
        )?;
        check_bounded_usize(
            "max_concurrent_ranges_per_segment",
            self.max_concurrent_ranges_per_segment,
            HARD_MAX_CONCURRENT_RANGES,
        )?;
        check_bounded_usize(
            "max_total_http_requests",
            self.max_total_http_requests,
            HARD_MAX_TOTAL_HTTP_REQUESTS,
        )?;
        check_bounded_u64(
            "max_aggregate_response_bytes",
            self.max_aggregate_response_bytes,
            HARD_MAX_AGGREGATE_RESPONSE_BYTES,
        )?;
        check_bounded_u64(
            "range_threshold",
            self.range_threshold,
            HARD_RANGE_THRESHOLD,
        )?;
        check_bounded_u64("chunk_size", self.chunk_size, HARD_CHUNK_SIZE)?;
        if self.max_retries > HARD_MAX_RETRIES {
            return Err(invalid(format!(
                "max_retries {} exceeds ceiling {}",
                self.max_retries, HARD_MAX_RETRIES
            )));
        }
        if self.request_timeout.is_zero() || self.request_timeout > HARD_REQUEST_TIMEOUT {
            return Err(invalid(format!(
                "request_timeout {:?} is zero or above ceiling {:?}",
                self.request_timeout, HARD_REQUEST_TIMEOUT
            )));
        }
        check_bounded_u64(
            "max_temp_disk_bytes",
            self.max_temp_disk_bytes,
            HARD_MAX_TEMP_DISK_BYTES,
        )?;
        if self.chunk_size > self.max_aggregate_response_bytes {
            return Err(invalid(
                "chunk_size must not exceed max_aggregate_response_bytes".to_owned(),
            ));
        }
        if self.range_threshold > self.max_aggregate_response_bytes {
            return Err(invalid(
                "range_threshold must not exceed max_aggregate_response_bytes".to_owned(),
            ));
        }
        if self.max_total_http_requests
            < self
                .max_concurrent_ranges_per_segment
                .min(self.max_concurrent_segment_fills)
        {
            return Err(invalid(
                "max_total_http_requests is below the per-segment concurrency".to_owned(),
            ));
        }
        Ok(())
    }
}

fn check_bounded_usize(name: &str, value: usize, ceiling: usize) -> IndexResult<()> {
    if value == 0 || value > ceiling {
        return Err(invalid(format!(
            "{name} {value} is zero or exceeds ceiling {ceiling}"
        )));
    }
    Ok(())
}

fn check_bounded_u64(name: &str, value: u64, ceiling: u64) -> IndexResult<()> {
    if value == 0 || value > ceiling {
        return Err(invalid(format!(
            "{name} {value} is zero or exceeds ceiling {ceiling}"
        )));
    }
    Ok(())
}

/// Complete configuration for a remote-backed index.
#[derive(Debug, Clone)]
pub struct RemoteConfig {
    prefix: RemoteKeyPrefix,
    workspace_root: PathBuf,
    cache: CacheConfig,
    transfer: RemoteTransferConfig,
}

impl RemoteConfig {
    /// Construct a configuration for `prefix` rooted at `workspace_root`.
    ///
    /// `workspace_root` is the disposable private local workspace; it is
    /// overwritten/reused by [`crate::remote::RemoteIndex`] and never treated as
    /// authoritative.
    pub fn new(prefix: RemoteKeyPrefix, workspace_root: impl Into<PathBuf>) -> Self {
        Self {
            prefix,
            workspace_root: workspace_root.into(),
            cache: CacheConfig::new(512 * 1024 * 1024, 4, 256 * 1024 * 1024),
            transfer: RemoteTransferConfig::default(),
        }
    }

    /// The validated remote index prefix.
    #[must_use]
    pub const fn prefix(&self) -> &RemoteKeyPrefix {
        &self.prefix
    }

    /// The private local workspace root.
    #[must_use]
    pub fn workspace_root(&self) -> &std::path::Path {
        &self.workspace_root
    }

    /// The disposable reader workspace directory.
    #[must_use]
    pub fn reader_dir(&self) -> PathBuf {
        self.workspace_root.join("reader")
    }

    /// The disposable writer workspace directory for writer `id`.
    ///
    /// Each writer gets a distinct directory so competing writers from the same
    /// base never share local files.
    #[must_use]
    pub fn writer_dir_for(&self, id: u64) -> PathBuf {
        self.workspace_root.join(format!("writer-{id}"))
    }

    /// The segment cache configuration.
    #[must_use]
    pub const fn cache(&self) -> &CacheConfig {
        &self.cache
    }

    /// The transfer configuration.
    #[must_use]
    pub const fn transfer(&self) -> &RemoteTransferConfig {
        &self.transfer
    }

    /// Replace the segment cache configuration.
    #[must_use]
    pub const fn with_cache(mut self, cache: CacheConfig) -> Self {
        self.cache = cache;
        self
    }

    /// Replace the transfer configuration.
    #[must_use]
    pub const fn with_transfer(mut self, transfer: RemoteTransferConfig) -> Self {
        self.transfer = transfer;
        self
    }

    /// Validate the transfer policy and cross-field consistency.
    pub fn validate(&self) -> IndexResult<()> {
        self.transfer.validate()
    }

    /// The effective concurrent segment-fill ceiling: the minimum of the
    /// transfer policy, the cache policy and the hard ceilings.
    #[must_use]
    pub fn effective_max_concurrent_fills(&self) -> usize {
        self.transfer
            .max_concurrent_segment_fills
            .min(self.cache.max_concurrent_fills)
            .clamp(1, HARD_MAX_CONCURRENT_SEGMENT_FILLS)
    }

    /// The effective single-response byte ceiling for the cache fill path.
    ///
    /// The cache bounds the whole verified object, not one network response;
    /// the per-chunk network bytes are bounded separately by the transfer
    /// policy's aggregate response ceiling.
    #[must_use]
    pub const fn effective_max_response_bytes(&self) -> u64 {
        self.cache.max_response_bytes
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prefix_maps_and_validates() {
        let prefix = RemoteKeyPrefix::parse("idx/one").unwrap();
        assert_eq!(prefix.as_str(), "idx/one");
        assert_eq!(
            prefix.object_key("index/CURRENT").unwrap().as_str(),
            "idx/one/index/CURRENT"
        );
        assert!(prefix.contains("idx/one/index/CURRENT"));
        assert!(!prefix.contains("idx/two/index/CURRENT"));
        assert!(RemoteKeyPrefix::parse("").is_err());
        assert!(RemoteKeyPrefix::parse("../escape").is_err());
        assert!(RemoteKeyPrefix::parse("a//b").is_err());
    }

    #[test]
    fn default_transfer_config_is_valid() {
        RemoteTransferConfig::default().validate().unwrap();
    }

    #[test]
    fn transfer_config_rejects_zero_above_ceiling_and_inconsistent() {
        let base = RemoteTransferConfig::default();
        assert!(
            base.with_max_concurrent_segment_fills(0)
                .validate()
                .is_err()
        );
        assert!(
            base.with_max_concurrent_segment_fills(HARD_MAX_CONCURRENT_SEGMENT_FILLS + 1)
                .validate()
                .is_err()
        );
        assert!(base.with_chunk_size(0).validate().is_err());
        assert!(
            base.with_max_retries(HARD_MAX_RETRIES + 1)
                .validate()
                .is_err()
        );
        assert!(
            base.with_request_timeout(Duration::ZERO)
                .validate()
                .is_err()
        );
        assert!(
            base.with_request_timeout(HARD_REQUEST_TIMEOUT + Duration::from_secs(1))
                .validate()
                .is_err()
        );
        assert!(
            base.with_chunk_size(HARD_CHUNK_SIZE + 1)
                .validate()
                .is_err()
        );
        assert!(
            base.with_max_aggregate_response_bytes(DEFAULT_CHUNK_SIZE - 1)
                .validate()
                .is_err()
        );
        assert!(
            base.with_range_threshold(HARD_MAX_AGGREGATE_RESPONSE_BYTES + 1)
                .validate()
                .is_err()
        );
        assert!(
            base.with_max_aggregate_response_bytes(1024)
                .validate()
                .is_err()
        );
    }

    #[test]
    fn effective_bounds_use_minima() {
        let prefix = RemoteKeyPrefix::parse("p").unwrap();
        let config = RemoteConfig::new(prefix, "/tmp/ws")
            .with_cache(CacheConfig::new(1024, 2, 100))
            .with_transfer(
                RemoteTransferConfig::default()
                    .with_max_concurrent_segment_fills(8)
                    .with_range_threshold(64)
                    .with_chunk_size(32),
            );
        assert_eq!(config.effective_max_concurrent_fills(), 2);
        assert_eq!(config.effective_max_response_bytes(), 100);
    }
}

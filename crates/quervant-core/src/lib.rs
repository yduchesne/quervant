//! Standalone single-index search engine foundation.
//!
//! This crate deliberately has no dependency on distributed infrastructure.
//! Indexing and querying APIs will be introduced in subsequent changes.
//!
//! The [`analysis`] module provides deterministic, versioned, bounded text and domain
//! analysis: tokenizers, ordered normalization filters, index/search analyzer bindings,
//! term-query preparation and optional pinned domain-derived representations. It produces
//! derived tokens and never persists segments.
//!
//! The [`contract`] module defines the validated document, field, query,
//! aggregation and batch contracts. These types validate shapes and types only;
//! they do not execute queries or persist data.
//!
//! The [`storage`] module defines the local `Directory` seam, memory and
//! filesystem backends, the immutable segment identity seam, and a bounded,
//! verified local cache over the provider-neutral `quervant-objectstore`
//! contract. It introduces no segment codec, manifest, writer or query
//! executor.

#![forbid(unsafe_code)]

pub mod analysis;
pub mod contract;
pub mod index;
pub mod search;
pub mod segment;
pub mod storage;

/// Returns the crate's public project identifier.
#[must_use]
pub const fn project_name() -> &'static str {
    "quervant-core"
}

#[cfg(test)]
mod tests {
    #[test]
    fn crate_identity() {
        assert_eq!(super::project_name(), "quervant-core");
    }
}

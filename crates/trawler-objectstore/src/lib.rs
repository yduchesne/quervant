//! Provider-neutral object storage adapter foundation.
//!
//! ObjectStore traits and adapters will be introduced in later PRs.

#![forbid(unsafe_code)]

/// Returns the crate's public project identifier.
#[must_use]
pub const fn project_name() -> &'static str {
    "trawler-objectstore"
}

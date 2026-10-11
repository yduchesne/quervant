//! Standalone single-index search engine foundation.
//!
//! This crate deliberately has no dependency on distributed infrastructure.
//! Indexing and querying APIs will be introduced in subsequent changes.

#![forbid(unsafe_code)]

/// Returns the crate's public project identifier.
#[must_use]
pub const fn project_name() -> &'static str {
    "trawler-core"
}

#[cfg(test)]
mod tests {
    #[test]
    fn crate_identity() {
        assert_eq!(super::project_name(), "trawler-core");
    }
}

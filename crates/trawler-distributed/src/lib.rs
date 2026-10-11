//! Distributed Trawler foundation.
//!
//! Coordinator and Query Aggregator are distinct service boundaries.
//! No distributed functionality is implemented in this foundation PR.

#![forbid(unsafe_code)]

/// Returns the underlying core crate's project identifier.
#[must_use]
pub const fn core_project_name() -> &'static str {
    trawler_core::project_name()
}

#[cfg(test)]
mod tests {
    #[test]
    fn depends_on_standalone_core() {
        assert_eq!(super::core_project_name(), "trawler-core");
    }
}

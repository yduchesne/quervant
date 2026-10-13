//! Explicit, checked resource bounds for one lexical search (PR 7, D07-06).
//!
//! Defaults are the published operational limits. Callers may lower any bound but
//! may not exceed the approved hard ceiling. Over-ceiling configuration is a typed
//! error, never a silent clamp.

use super::error::SearchError;

/// Hard ceiling for compiled query nodes in one search.
pub const HARD_MAX_COMPILED_NODES: u64 = 65_536;
/// Hard ceiling for distinct analyzed query terms.
pub const HARD_MAX_UNIQUE_QUERY_TERMS: u64 = 16_384;
/// Hard ceiling for candidate entries materialized in one segment.
pub const HARD_MAX_SEGMENT_CANDIDATE_ENTRIES: u64 = 16_000_000;
/// Hard ceiling for total candidate bytes materialized across a search.
pub const HARD_MAX_TOTAL_CANDIDATE_BYTES: u64 = 1024 * 1024 * 1024;
/// Hard ceiling for posting occurrences scanned in one search.
pub const HARD_MAX_SCANNED_POSTING_OCCURRENCES: u64 = 2_000_000_000;
/// Hard ceiling for dictionary terms examined in one search.
pub const HARD_MAX_DICTIONARY_TERMS_EXAMINED: u64 = 500_000_000;
/// Hard ceiling for per-field document-length entries.
pub const HARD_MAX_FIELD_LENGTH_ENTRIES: u64 = 64_000_000;
/// Hard ceiling for per-field document-length bytes.
pub const HARD_MAX_FIELD_LENGTH_BYTES: u64 = 2 * 1024 * 1024 * 1024;
/// Hard ceiling for top-K heap bytes.
pub const HARD_MAX_TOPK_HEAP_BYTES: u64 = 256 * 1024 * 1024;
/// Hard ceiling for deterministic work units in one search.
pub const HARD_MAX_TOTAL_WORK_UNITS: u64 = 5_000_000_000;

/// Concrete, enforceable search limits.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SearchLimits {
    max_compiled_nodes: u64,
    max_unique_query_terms: u64,
    max_segment_candidate_entries: u64,
    max_total_candidate_bytes: u64,
    max_scanned_posting_occurrences: u64,
    max_dictionary_terms_examined: u64,
    max_field_length_entries: u64,
    max_field_length_bytes: u64,
    max_topk_heap_bytes: u64,
    max_total_work_units: u64,
}

impl Default for SearchLimits {
    fn default() -> Self {
        Self {
            max_compiled_nodes: 4_096,
            max_unique_query_terms: 16_384,
            max_segment_candidate_entries: 1_000_000,
            max_total_candidate_bytes: 64 * 1024 * 1024,
            max_scanned_posting_occurrences: 50_000_000,
            max_dictionary_terms_examined: 5_000_000,
            max_field_length_entries: 5_000_000,
            max_field_length_bytes: 128 * 1024 * 1024,
            max_topk_heap_bytes: 8 * 1024 * 1024,
            max_total_work_units: 100_000_000,
        }
    }
}

impl SearchLimits {
    /// Builds limits, rejecting any value outside the approved hard ceiling.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        max_compiled_nodes: u64,
        max_unique_query_terms: u64,
        max_segment_candidate_entries: u64,
        max_total_candidate_bytes: u64,
        max_scanned_posting_occurrences: u64,
        max_dictionary_terms_examined: u64,
        max_field_length_entries: u64,
        max_field_length_bytes: u64,
        max_topk_heap_bytes: u64,
        max_total_work_units: u64,
    ) -> Result<Self, SearchError> {
        let limits = Self {
            max_compiled_nodes,
            max_unique_query_terms,
            max_segment_candidate_entries,
            max_total_candidate_bytes,
            max_scanned_posting_occurrences,
            max_dictionary_terms_examined,
            max_field_length_entries,
            max_field_length_bytes,
            max_topk_heap_bytes,
            max_total_work_units,
        };
        limits.validate()?;
        Ok(limits)
    }

    fn validate(&self) -> Result<(), SearchError> {
        check_ceiling(
            "max_compiled_nodes",
            self.max_compiled_nodes,
            HARD_MAX_COMPILED_NODES,
        )?;
        check_ceiling(
            "max_unique_query_terms",
            self.max_unique_query_terms,
            HARD_MAX_UNIQUE_QUERY_TERMS,
        )?;
        check_ceiling(
            "max_segment_candidate_entries",
            self.max_segment_candidate_entries,
            HARD_MAX_SEGMENT_CANDIDATE_ENTRIES,
        )?;
        check_ceiling(
            "max_total_candidate_bytes",
            self.max_total_candidate_bytes,
            HARD_MAX_TOTAL_CANDIDATE_BYTES,
        )?;
        check_ceiling(
            "max_scanned_posting_occurrences",
            self.max_scanned_posting_occurrences,
            HARD_MAX_SCANNED_POSTING_OCCURRENCES,
        )?;
        check_ceiling(
            "max_dictionary_terms_examined",
            self.max_dictionary_terms_examined,
            HARD_MAX_DICTIONARY_TERMS_EXAMINED,
        )?;
        check_ceiling(
            "max_field_length_entries",
            self.max_field_length_entries,
            HARD_MAX_FIELD_LENGTH_ENTRIES,
        )?;
        check_ceiling(
            "max_field_length_bytes",
            self.max_field_length_bytes,
            HARD_MAX_FIELD_LENGTH_BYTES,
        )?;
        check_ceiling(
            "max_topk_heap_bytes",
            self.max_topk_heap_bytes,
            HARD_MAX_TOPK_HEAP_BYTES,
        )?;
        check_ceiling(
            "max_total_work_units",
            self.max_total_work_units,
            HARD_MAX_TOTAL_WORK_UNITS,
        )
    }

    /// Maximum compiled query nodes.
    #[must_use]
    pub const fn max_compiled_nodes(&self) -> u64 {
        self.max_compiled_nodes
    }

    /// Lower the compiled-node bound.
    pub fn with_max_compiled_nodes(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling("max_compiled_nodes", value, HARD_MAX_COMPILED_NODES)?;
        self.max_compiled_nodes = value;
        Ok(self)
    }

    /// Maximum distinct analyzed query terms.
    #[must_use]
    pub const fn max_unique_query_terms(&self) -> u64 {
        self.max_unique_query_terms
    }

    /// Lower the distinct-term bound.
    pub fn with_max_unique_query_terms(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling("max_unique_query_terms", value, HARD_MAX_UNIQUE_QUERY_TERMS)?;
        self.max_unique_query_terms = value;
        Ok(self)
    }

    /// Maximum candidate entries materialized in one segment.
    #[must_use]
    pub const fn max_segment_candidate_entries(&self) -> u64 {
        self.max_segment_candidate_entries
    }

    /// Lower the per-segment candidate-entry bound.
    pub fn with_max_segment_candidate_entries(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling(
            "max_segment_candidate_entries",
            value,
            HARD_MAX_SEGMENT_CANDIDATE_ENTRIES,
        )?;
        self.max_segment_candidate_entries = value;
        Ok(self)
    }

    /// Maximum total candidate bytes materialized across a search.
    #[must_use]
    pub const fn max_total_candidate_bytes(&self) -> u64 {
        self.max_total_candidate_bytes
    }

    /// Lower the total candidate-byte bound.
    pub fn with_max_total_candidate_bytes(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling(
            "max_total_candidate_bytes",
            value,
            HARD_MAX_TOTAL_CANDIDATE_BYTES,
        )?;
        self.max_total_candidate_bytes = value;
        Ok(self)
    }

    /// Maximum posting occurrences scanned in one search.
    #[must_use]
    pub const fn max_scanned_posting_occurrences(&self) -> u64 {
        self.max_scanned_posting_occurrences
    }

    /// Lower the scanned-posting-occurrence bound.
    pub fn with_max_scanned_posting_occurrences(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling(
            "max_scanned_posting_occurrences",
            value,
            HARD_MAX_SCANNED_POSTING_OCCURRENCES,
        )?;
        self.max_scanned_posting_occurrences = value;
        Ok(self)
    }

    /// Maximum dictionary terms examined in one search.
    #[must_use]
    pub const fn max_dictionary_terms_examined(&self) -> u64 {
        self.max_dictionary_terms_examined
    }

    /// Lower the dictionary-term bound.
    pub fn with_max_dictionary_terms_examined(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling(
            "max_dictionary_terms_examined",
            value,
            HARD_MAX_DICTIONARY_TERMS_EXAMINED,
        )?;
        self.max_dictionary_terms_examined = value;
        Ok(self)
    }

    /// Maximum per-field document-length entries.
    #[must_use]
    pub const fn max_field_length_entries(&self) -> u64 {
        self.max_field_length_entries
    }

    /// Lower the field-length entry bound.
    pub fn with_max_field_length_entries(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling(
            "max_field_length_entries",
            value,
            HARD_MAX_FIELD_LENGTH_ENTRIES,
        )?;
        self.max_field_length_entries = value;
        Ok(self)
    }

    /// Maximum per-field document-length bytes.
    #[must_use]
    pub const fn max_field_length_bytes(&self) -> u64 {
        self.max_field_length_bytes
    }

    /// Lower the field-length byte bound.
    pub fn with_max_field_length_bytes(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling("max_field_length_bytes", value, HARD_MAX_FIELD_LENGTH_BYTES)?;
        self.max_field_length_bytes = value;
        Ok(self)
    }

    /// Maximum top-K heap bytes.
    #[must_use]
    pub const fn max_topk_heap_bytes(&self) -> u64 {
        self.max_topk_heap_bytes
    }

    /// Lower the top-K heap byte bound.
    pub fn with_max_topk_heap_bytes(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling("max_topk_heap_bytes", value, HARD_MAX_TOPK_HEAP_BYTES)?;
        self.max_topk_heap_bytes = value;
        Ok(self)
    }

    /// Maximum deterministic work units.
    #[must_use]
    pub const fn max_total_work_units(&self) -> u64 {
        self.max_total_work_units
    }

    /// Lower the total-work bound.
    pub fn with_max_total_work_units(mut self, value: u64) -> Result<Self, SearchError> {
        check_ceiling("max_total_work_units", value, HARD_MAX_TOTAL_WORK_UNITS)?;
        self.max_total_work_units = value;
        Ok(self)
    }
}

fn check_ceiling(name: &str, value: u64, ceiling: u64) -> Result<(), SearchError> {
    if value == 0 {
        return Err(SearchError::ResourceLimit {
            limit: ceiling,
            requested: 0,
        });
    }
    if value > ceiling {
        return Err(SearchError::ResourceLimit {
            limit: ceiling,
            requested: value,
        });
    }
    let _ = name;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_are_within_ceilings() {
        let limits = SearchLimits::default();
        limits.validate().expect("defaults valid");
        assert!(limits.max_compiled_nodes() > 0);
        assert!(limits.max_total_work_units() > 0);
    }

    #[test]
    fn lowering_is_allowed_and_zero_or_over_ceiling_rejected() {
        let lowered = SearchLimits::default()
            .with_max_compiled_nodes(4)
            .expect("lowering allowed");
        assert_eq!(lowered.max_compiled_nodes(), 4);
        assert!(lowered.with_max_compiled_nodes(0).is_err());
        assert!(
            lowered
                .with_max_compiled_nodes(HARD_MAX_COMPILED_NODES + 1)
                .is_err()
        );
        assert!(SearchLimits::new(0, 1, 1, 1, 1, 1, 1, 1, 1, 1).is_err());
        assert!(
            SearchLimits::new(1, HARD_MAX_UNIQUE_QUERY_TERMS + 1, 1, 1, 1, 1, 1, 1, 1, 1).is_err()
        );
    }

    #[test]
    fn every_builder_bound_is_checkable() {
        let limits = SearchLimits::default();
        assert_eq!(
            limits
                .with_max_unique_query_terms(3)
                .unwrap()
                .max_unique_query_terms(),
            3
        );
        assert_eq!(
            limits
                .with_max_segment_candidate_entries(3)
                .unwrap()
                .max_segment_candidate_entries(),
            3
        );
        assert_eq!(
            limits
                .with_max_total_candidate_bytes(3)
                .unwrap()
                .max_total_candidate_bytes(),
            3
        );
        assert_eq!(
            limits
                .with_max_scanned_posting_occurrences(3)
                .unwrap()
                .max_scanned_posting_occurrences(),
            3
        );
        assert_eq!(
            limits
                .with_max_dictionary_terms_examined(3)
                .unwrap()
                .max_dictionary_terms_examined(),
            3
        );
        assert_eq!(
            limits
                .with_max_field_length_entries(3)
                .unwrap()
                .max_field_length_entries(),
            3
        );
        assert_eq!(
            limits
                .with_max_field_length_bytes(3)
                .unwrap()
                .max_field_length_bytes(),
            3
        );
        assert_eq!(
            limits
                .with_max_topk_heap_bytes(3)
                .unwrap()
                .max_topk_heap_bytes(),
            3
        );
        assert_eq!(
            limits
                .with_max_total_work_units(3)
                .unwrap()
                .max_total_work_units(),
            3
        );
        assert_eq!(
            limits
                .with_max_unique_query_terms(0)
                .unwrap_err()
                .to_string(),
            SearchError::ResourceLimit {
                limit: HARD_MAX_UNIQUE_QUERY_TERMS,
                requested: 0
            }
            .to_string()
        );
        assert_eq!(
            limits
                .with_max_field_length_entries(3)
                .unwrap()
                .with_max_total_work_units(3)
                .unwrap()
                .max_total_work_units(),
            3
        );
    }
}

//! Checked resource bounds for the local index lifecycle (PR 6).
//!
//! The pending-document, commit, manifest, resident-snapshot and PIT bounds are
//! operational policy: they are **not** wire-format ceilings. They are checked
//! with typed errors and never silently clamp.

use crate::analysis::AnalysisLimits;
use crate::contract::budget::{BudgetKind, Budgets};
use crate::segment::SegmentLimits;

/// Checked resource bounds for `Index`/`IndexWriter`.
#[derive(Debug, Clone)]
pub struct IndexLimits {
    max_pending_docs: u64,
    max_pending_bytes: u64,
    max_segments_per_commit: u64,
    max_manifest_bytes: u64,
    max_snapshot_bytes: u64,
    max_pinned_pits: u64,
    segment_limits: SegmentLimits,
    analysis_limits: AnalysisLimits,
    budgets: Budgets,
}

impl Default for IndexLimits {
    fn default() -> Self {
        Self {
            max_pending_docs: 10_000,
            max_pending_bytes: 64 * 1024 * 1024,
            max_segments_per_commit: 1_024,
            max_manifest_bytes: 16 * 1024 * 1024,
            max_snapshot_bytes: 256 * 1024 * 1024,
            max_pinned_pits: 128,
            segment_limits: SegmentLimits::default(),
            analysis_limits: AnalysisLimits::default(),
            budgets: default_budgets(),
        }
    }
}

fn default_budgets() -> Budgets {
    Budgets::new()
        .with(BudgetKind::Fields, 1_024)
        .expect("nonzero default budget")
        .with(BudgetKind::DocumentBytes, 16 * 1024 * 1024)
        .expect("nonzero default budget")
        .with(BudgetKind::ArrayElements, 1 << 20)
        .expect("nonzero default budget")
        .with(BudgetKind::JsonDepth, 128)
        .expect("nonzero default budget")
}

impl IndexLimits {
    /// Start from the published defaults.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Maximum accepted uncommitted documents.
    #[must_use]
    pub const fn max_pending_docs(&self) -> u64 {
        self.max_pending_docs
    }

    /// Set the pending-document bound.
    #[must_use]
    pub const fn with_max_pending_docs(mut self, value: u64) -> Self {
        self.max_pending_docs = value;
        self
    }

    /// Maximum estimated bytes of uncommitted documents.
    #[must_use]
    pub const fn max_pending_bytes(&self) -> u64 {
        self.max_pending_bytes
    }

    /// Set the pending-byte bound.
    #[must_use]
    pub const fn with_max_pending_bytes(mut self, value: u64) -> Self {
        self.max_pending_bytes = value;
        self
    }

    /// Maximum segments a single commit may add.
    #[must_use]
    pub const fn max_segments_per_commit(&self) -> u64 {
        self.max_segments_per_commit
    }

    /// Set the per-commit segment bound.
    #[must_use]
    pub const fn with_max_segments_per_commit(mut self, value: u64) -> Self {
        self.max_segments_per_commit = value;
        self
    }

    /// Maximum encoded manifest bytes.
    #[must_use]
    pub const fn max_manifest_bytes(&self) -> u64 {
        self.max_manifest_bytes
    }

    /// Set the manifest-byte bound.
    #[must_use]
    pub const fn with_max_manifest_bytes(mut self, value: u64) -> Self {
        self.max_manifest_bytes = value;
        self
    }

    /// Maximum resident snapshot segment bytes.
    #[must_use]
    pub const fn max_snapshot_bytes(&self) -> u64 {
        self.max_snapshot_bytes
    }

    /// Set the resident-snapshot byte bound.
    #[must_use]
    pub const fn with_max_snapshot_bytes(mut self, value: u64) -> Self {
        self.max_snapshot_bytes = value;
        self
    }

    /// Maximum simultaneously pinned PIT handles.
    #[must_use]
    pub const fn max_pinned_pits(&self) -> u64 {
        self.max_pinned_pits
    }

    /// Set the pinned-PIT bound.
    #[must_use]
    pub const fn with_max_pinned_pits(mut self, value: u64) -> Self {
        self.max_pinned_pits = value;
        self
    }

    /// Segment codec limits reused for reads and writes.
    #[must_use]
    pub const fn segment_limits(&self) -> &SegmentLimits {
        &self.segment_limits
    }

    /// Replace the segment codec limits.
    #[must_use]
    pub fn with_segment_limits(mut self, limits: SegmentLimits) -> Self {
        self.segment_limits = limits;
        self
    }

    /// Analyzer limits reused for index-time analysis.
    #[must_use]
    pub const fn analysis_limits(&self) -> &AnalysisLimits {
        &self.analysis_limits
    }

    /// Replace the analyzer limits.
    #[must_use]
    pub fn with_analysis_limits(mut self, limits: AnalysisLimits) -> Self {
        self.analysis_limits = limits;
        self
    }

    /// Document contract budgets reused for insert validation.
    #[must_use]
    pub const fn budgets(&self) -> &Budgets {
        &self.budgets
    }

    /// Replace the document contract budgets.
    #[must_use]
    pub fn with_budgets(mut self, budgets: Budgets) -> Self {
        self.budgets = budgets;
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_are_bounded_and_overridable() {
        let limits = IndexLimits::default();
        assert_eq!(limits.max_pending_docs(), 10_000);
        assert_eq!(limits.max_pending_bytes(), 64 * 1024 * 1024);
        assert_eq!(limits.max_segments_per_commit(), 1_024);
        assert_eq!(limits.max_manifest_bytes(), 16 * 1024 * 1024);
        assert_eq!(limits.max_snapshot_bytes(), 256 * 1024 * 1024);
        assert_eq!(limits.max_pinned_pits(), 128);
        assert!(limits.budgets().get(BudgetKind::DocumentBytes).is_some());

        let custom = IndexLimits::new()
            .with_max_pending_docs(1)
            .with_max_pending_bytes(2)
            .with_max_segments_per_commit(3)
            .with_max_manifest_bytes(4)
            .with_max_snapshot_bytes(5)
            .with_max_pinned_pits(6)
            .with_segment_limits(SegmentLimits::default())
            .with_budgets(Budgets::new());
        assert_eq!(custom.max_pending_docs(), 1);
        assert_eq!(custom.max_pending_bytes(), 2);
        assert_eq!(custom.max_segments_per_commit(), 3);
        assert_eq!(custom.max_manifest_bytes(), 4);
        assert_eq!(custom.max_snapshot_bytes(), 5);
        assert_eq!(custom.max_pinned_pits(), 6);
        assert!(custom.budgets().is_empty());
        assert_eq!(
            custom.analysis_limits().max_tokens(),
            limits.analysis_limits().max_tokens()
        );
    }
}

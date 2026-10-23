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
    max_mutation_state_bytes: u64,
    max_replay_entries: u64,
    max_replay_bytes: u64,
    max_batch_commands: u64,
    max_batch_keys: u64,
    max_batch_replay_keys: u64,
    max_batch_response_bytes: u64,
    max_query_matches: u64,
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
            max_mutation_state_bytes: 32 * 1024 * 1024,
            max_replay_entries: 100_000,
            max_replay_bytes: 16 * 1024 * 1024,
            max_batch_commands: 1_024,
            max_batch_keys: 1_024,
            max_batch_replay_keys: 1_024,
            max_batch_response_bytes: 4 * 1024 * 1024,
            max_query_matches: 1_024,
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

    /// Absolute ceiling for [`Self::max_mutation_state_bytes`].
    pub const MUTATION_STATE_BYTES_CEILING: u64 = 512 * 1024 * 1024;
    /// Absolute ceiling for [`Self::max_replay_entries`].
    pub const REPLAY_ENTRIES_CEILING: u64 = 1_000_000;
    /// Absolute ceiling for [`Self::max_replay_bytes`].
    pub const REPLAY_BYTES_CEILING: u64 = 256 * 1024 * 1024;

    /// Maximum encoded mutation-state sidecar bytes.
    #[must_use]
    pub const fn max_mutation_state_bytes(&self) -> u64 {
        self.max_mutation_state_bytes
    }

    /// Set the mutation-state byte bound, clamped to the published ceiling.
    #[must_use]
    pub const fn with_max_mutation_state_bytes(mut self, value: u64) -> Self {
        self.max_mutation_state_bytes = if value > Self::MUTATION_STATE_BYTES_CEILING {
            Self::MUTATION_STATE_BYTES_CEILING
        } else {
            value
        };
        self
    }

    /// Maximum replay-ledger entries in one generation state.
    #[must_use]
    pub const fn max_replay_entries(&self) -> u64 {
        self.max_replay_entries
    }

    /// Set the replay-entry bound, clamped to the published ceiling.
    #[must_use]
    pub const fn with_max_replay_entries(mut self, value: u64) -> Self {
        self.max_replay_entries = if value > Self::REPLAY_ENTRIES_CEILING {
            Self::REPLAY_ENTRIES_CEILING
        } else {
            value
        };
        self
    }

    /// Maximum modeled replay-ledger bytes in one generation state.
    #[must_use]
    pub const fn max_replay_bytes(&self) -> u64 {
        self.max_replay_bytes
    }

    /// Set the replay-byte bound, clamped to the published ceiling.
    #[must_use]
    pub const fn with_max_replay_bytes(mut self, value: u64) -> Self {
        self.max_replay_bytes = if value > Self::REPLAY_BYTES_CEILING {
            Self::REPLAY_BYTES_CEILING
        } else {
            value
        };
        self
    }

    /// Segment codec limits reused for reads and writes.
    #[must_use]
    pub const fn segment_limits(&self) -> &SegmentLimits {
        &self.segment_limits
    }

    /// Absolute ceiling for [`Self::max_batch_commands`].
    pub const BATCH_COMMANDS_CEILING: u64 = 65_536;
    /// Absolute ceiling for [`Self::max_batch_keys`].
    pub const BATCH_KEYS_CEILING: u64 = 65_536;
    /// Absolute ceiling for [`Self::max_batch_replay_keys`].
    pub const BATCH_REPLAY_KEYS_CEILING: u64 = 65_536;
    /// Absolute ceiling for [`Self::max_batch_response_bytes`].
    pub const BATCH_RESPONSE_BYTES_CEILING: u64 = 64 * 1024 * 1024;

    /// Maximum commands in one atomic mutation batch.
    ///
    /// A batch of zero commands is always rejected; the effective floor here is
    /// `1` so that a configured zero cannot mean "unbounded".
    #[must_use]
    pub const fn max_batch_commands(&self) -> u64 {
        self.max_batch_commands
    }

    /// Set the batch-command bound, clamped to `[1, ceiling]`.
    #[must_use]
    pub const fn with_max_batch_commands(mut self, value: u64) -> Self {
        self.max_batch_commands = clamp_batch_limit(value, Self::BATCH_COMMANDS_CEILING);
        self
    }

    /// Ceiling on explicit-key admission work in one atomic batch.
    ///
    /// The same value bounds **two** independent quantities:
    ///
    /// 1. the cumulative number of **raw** key occurrences submitted by
    ///    explicit-key targets (`MutationTarget::Key` counts as one,
    ///    `MutationTarget::Keys` as its full length **including duplicates**),
    ///    accumulated across the whole batch; and
    /// 2. the cumulative number of **resolved logical operations**, counting
    ///    repeated operations across commands.
    ///
    /// The raw-occurrence ceiling is checked first, from `Vec::len()` values
    /// only, so a highly duplicated request is rejected before any per-key
    /// deduplication, cloning or allocation proportional to the input length.
    /// Because duplicate occurrences are charged, some heavily duplicated
    /// requests that previously passed the logical-operation check are now
    /// rejected: that is a deliberate strengthening of admission resource
    /// governance, not a redefinition of quantity 2.
    #[must_use]
    pub const fn max_batch_keys(&self) -> u64 {
        self.max_batch_keys
    }

    /// Set the batch-key bound, clamped to `[1, ceiling]`.
    ///
    /// See [`Self::max_batch_keys`] for the two ceilings this value enforces.
    #[must_use]
    pub const fn with_max_batch_keys(mut self, value: u64) -> Self {
        self.max_batch_keys = clamp_batch_limit(value, Self::BATCH_KEYS_CEILING);
        self
    }

    /// Maximum per-key outcomes persisted for one batch replay record.
    #[must_use]
    pub const fn max_batch_replay_keys(&self) -> u64 {
        self.max_batch_replay_keys
    }

    /// Set the batch-replay-key bound, clamped to `[1, ceiling]`.
    #[must_use]
    pub const fn with_max_batch_replay_keys(mut self, value: u64) -> Self {
        self.max_batch_replay_keys = clamp_batch_limit(value, Self::BATCH_REPLAY_KEYS_CEILING);
        self
    }

    /// Maximum canonical encoded bytes of one batch response.
    #[must_use]
    pub const fn max_batch_response_bytes(&self) -> u64 {
        self.max_batch_response_bytes
    }

    /// Set the batch-response byte bound, clamped to `[1, ceiling]`.
    #[must_use]
    pub const fn with_max_batch_response_bytes(mut self, value: u64) -> Self {
        self.max_batch_response_bytes =
            clamp_batch_limit(value, Self::BATCH_RESPONSE_BYTES_CEILING);
        self
    }

    /// Maximum logical keys one query mutation selector may resolve.
    ///
    /// The effective per-selector bound is the minimum of this value, the
    /// selector's own `max_matches` and [`Self::max_batch_keys`]. Unlike the
    /// batch-shape builders this value is **not** clamped: a configured `0`
    /// means no query-selected key can be admitted and the first matching key
    /// fails closed with `MatchLimitExceeded { limit: 0, matched: 1 }`.
    #[must_use]
    pub const fn max_query_matches(&self) -> u64 {
        self.max_query_matches
    }

    /// Set the query-selector match bound without implicit clamping.
    #[must_use]
    pub const fn with_max_query_matches(mut self, value: u64) -> Self {
        self.max_query_matches = value;
        self
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

/// Clamp a configured batch limit into `[1, ceiling]`.
///
/// This follows the existing `IndexLimits` clamping convention rather than
/// rejecting an out-of-range builder input, but it never lets a configured `0`
/// degrade into an unbounded limit.
const fn clamp_batch_limit(value: u64, ceiling: u64) -> u64 {
    if value == 0 {
        1
    } else if value > ceiling {
        ceiling
    } else {
        value
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
        assert_eq!(limits.max_batch_commands(), 1_024);
        assert_eq!(limits.max_batch_keys(), 1_024);
        assert_eq!(limits.max_batch_replay_keys(), 1_024);
        assert_eq!(limits.max_batch_response_bytes(), 4 * 1024 * 1024);
        assert_eq!(limits.max_query_matches(), 1_024);
        assert!(limits.budgets().get(BudgetKind::DocumentBytes).is_some());

        let custom = IndexLimits::new()
            .with_max_pending_docs(1)
            .with_max_pending_bytes(2)
            .with_max_segments_per_commit(3)
            .with_max_manifest_bytes(4)
            .with_max_snapshot_bytes(5)
            .with_max_pinned_pits(6)
            .with_max_batch_commands(7)
            .with_max_batch_keys(8)
            .with_max_batch_replay_keys(9)
            .with_max_batch_response_bytes(10)
            .with_segment_limits(SegmentLimits::default())
            .with_budgets(Budgets::new());
        assert_eq!(custom.max_pending_docs(), 1);
        assert_eq!(custom.max_pending_bytes(), 2);
        assert_eq!(custom.max_segments_per_commit(), 3);
        assert_eq!(custom.max_manifest_bytes(), 4);
        assert_eq!(custom.max_snapshot_bytes(), 5);
        assert_eq!(custom.max_pinned_pits(), 6);
        assert!(custom.budgets().is_empty());
        assert_eq!(custom.max_batch_commands(), 7);
        assert_eq!(custom.max_batch_keys(), 8);
        assert_eq!(custom.max_batch_replay_keys(), 9);
        assert_eq!(custom.max_batch_response_bytes(), 10);
        assert_eq!(
            custom.analysis_limits().max_tokens(),
            limits.analysis_limits().max_tokens()
        );
    }

    #[test]
    fn batch_limits_never_allow_unbounded_zero() {
        let zeroed = IndexLimits::new()
            .with_max_batch_commands(0)
            .with_max_batch_keys(0)
            .with_max_batch_replay_keys(0)
            .with_max_batch_response_bytes(0);
        assert_eq!(zeroed.max_batch_commands(), 1);
        assert_eq!(zeroed.max_batch_keys(), 1);
        assert_eq!(zeroed.max_batch_replay_keys(), 1);
        assert_eq!(zeroed.max_batch_response_bytes(), 1);

        let clamped = IndexLimits::new()
            .with_max_batch_commands(u64::MAX)
            .with_max_batch_keys(u64::MAX)
            .with_max_batch_replay_keys(u64::MAX)
            .with_max_batch_response_bytes(u64::MAX);
        assert_eq!(
            clamped.max_batch_commands(),
            IndexLimits::BATCH_COMMANDS_CEILING
        );
        assert_eq!(clamped.max_batch_keys(), IndexLimits::BATCH_KEYS_CEILING);
        assert_eq!(
            clamped.max_batch_replay_keys(),
            IndexLimits::BATCH_REPLAY_KEYS_CEILING
        );
        assert_eq!(
            clamped.max_batch_response_bytes(),
            IndexLimits::BATCH_RESPONSE_BYTES_CEILING
        );
    }

    #[test]
    fn query_match_bound_is_exact_and_zero_fails_closed() {
        let limits = IndexLimits::new();
        assert_eq!(limits.max_query_matches(), 1_024);

        let zero = IndexLimits::new().with_max_query_matches(0);
        assert_eq!(zero.max_query_matches(), 0);

        let exact = IndexLimits::new().with_max_query_matches(7);
        assert_eq!(exact.max_query_matches(), 7);

        let large = IndexLimits::new().with_max_query_matches(u64::MAX);
        assert_eq!(large.max_query_matches(), u64::MAX);
    }
}

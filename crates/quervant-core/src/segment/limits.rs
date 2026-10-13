//! Resource limits for segment codecs (F11).
//!
//! Three classes are deliberately separated: wire representability is fixed by
//! the byte format; safety budgets are enforced by every decoder regardless of
//! file size; operational policies are configurable and are not wire ceilings.

/// Decoder safety budgets and operational policy for a segment reader.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SegmentLimits {
    max_single_allocation: u64,
    max_section_decode_bytes: u64,
    max_decoded_entries: u64,
    max_read_bytes: u64,
    max_footer_bytes: u64,
    max_sections: usize,
    max_features: usize,
    max_docs: u64,
    max_terms_total: u64,
    max_postings_per_term: u64,
    max_array_elements: u64,
    max_json_depth: u64,
    block_docs_default: u32,
    accepted_segment_bytes: u64,
}

impl Default for SegmentLimits {
    fn default() -> Self {
        Self {
            max_single_allocation: 64 * 1024 * 1024,
            max_section_decode_bytes: 256 * 1024 * 1024,
            max_decoded_entries: 8_000_000,
            max_read_bytes: 1024 * 1024,
            max_footer_bytes: 1024 * 1024,
            max_sections: 4_096,
            max_features: 1_024,
            max_docs: u64::from(u32::MAX),
            max_terms_total: 1 << 32,
            max_postings_per_term: 1 << 32,
            max_array_elements: 1 << 20,
            max_json_depth: 128,
            block_docs_default: 1_024,
            accepted_segment_bytes: 1024 * 1024 * 1024,
        }
    }
}

impl SegmentLimits {
    /// Start from the defaults.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Maximum bytes in a single allocation.
    #[must_use]
    pub const fn max_single_allocation(&self) -> u64 {
        self.max_single_allocation
    }

    /// Maximum decoded bytes for one section/block.
    #[must_use]
    pub const fn max_section_decode_bytes(&self) -> u64 {
        self.max_section_decode_bytes
    }

    /// Maximum decoded entries (postings, dictionary terms, column rows) per operation.
    #[must_use]
    pub const fn max_decoded_entries(&self) -> u64 {
        self.max_decoded_entries
    }

    /// Maximum bytes for one positional read.
    #[must_use]
    pub const fn max_read_bytes(&self) -> u64 {
        self.max_read_bytes
    }

    /// Maximum footer length.
    #[must_use]
    pub const fn max_footer_bytes(&self) -> u64 {
        self.max_footer_bytes
    }

    /// Maximum section count.
    #[must_use]
    pub const fn max_sections(&self) -> usize {
        self.max_sections
    }

    /// Maximum feature count per feature set.
    #[must_use]
    pub const fn max_features(&self) -> usize {
        self.max_features
    }

    /// Maximum documents in a segment.
    #[must_use]
    pub const fn max_docs(&self) -> u64 {
        self.max_docs
    }

    /// Maximum total terms.
    #[must_use]
    pub const fn max_terms_total(&self) -> u64 {
        self.max_terms_total
    }

    /// Maximum postings in a single term.
    #[must_use]
    pub const fn max_postings_per_term(&self) -> u64 {
        self.max_postings_per_term
    }

    /// Maximum elements in one array / list value.
    #[must_use]
    pub const fn max_array_elements(&self) -> u64 {
        self.max_array_elements
    }

    /// Maximum JSON nesting depth.
    #[must_use]
    pub const fn max_json_depth(&self) -> u64 {
        self.max_json_depth
    }

    /// Encoder policy for column block size (persisted per column).
    #[must_use]
    pub const fn block_docs_default(&self) -> u32 {
        self.block_docs_default
    }

    /// Configurable reader acceptance ceiling for a whole container.
    #[must_use]
    pub const fn accepted_segment_bytes(&self) -> u64 {
        self.accepted_segment_bytes
    }

    /// Set the single-allocation ceiling.
    #[must_use]
    pub const fn with_max_single_allocation(mut self, value: u64) -> Self {
        self.max_single_allocation = value;
        self
    }

    /// Set the decoded-entries ceiling.
    #[must_use]
    pub const fn with_max_decoded_entries(mut self, value: u64) -> Self {
        self.max_decoded_entries = value;
        self
    }

    /// Set the maximum bytes for one positional read.
    ///
    /// This is a decoder/I/O safety budget, not a wire-format change; the whole
    /// object may still be read in multiple bounded requests.
    #[must_use]
    pub const fn with_max_read_bytes(mut self, value: u64) -> Self {
        self.max_read_bytes = value;
        self
    }

    /// Set the cumulative decoded/retained byte budget for one section or
    /// logical decode operation.
    #[must_use]
    pub const fn with_max_section_decode_bytes(mut self, value: u64) -> Self {
        self.max_section_decode_bytes = value;
        self
    }

    /// Set the block-size encoder policy.
    #[must_use]
    pub const fn with_block_docs_default(mut self, value: u32) -> Self {
        self.block_docs_default = value;
        self
    }

    /// Set the accepted segment size.
    #[must_use]
    pub const fn with_accepted_segment_bytes(mut self, value: u64) -> Self {
        self.accepted_segment_bytes = value;
        self
    }

    pub(crate) fn check_entries(&self, requested: u64) -> Result<(), super::error::SegmentError> {
        if requested > self.max_decoded_entries {
            return Err(super::error::SegmentError::LimitExceeded {
                limit: self.max_decoded_entries,
                requested,
            });
        }
        Ok(())
    }

    /// Preflight a conservative upper bound on a single backing allocation.
    ///
    /// `max_single_allocation` bounds **each** allocation made from untrusted
    /// data; it is not an exact `Vec` capacity claim. `requested` must be the
    /// conservative upper bound (for example `count * size_of::<T>()`).
    pub(crate) fn check_allocation_bytes(
        &self,
        requested: u64,
    ) -> Result<(), super::error::SegmentError> {
        if requested > self.max_single_allocation {
            return Err(super::error::SegmentError::LimitExceeded {
                limit: self.max_single_allocation,
                requested,
            });
        }
        Ok(())
    }

    /// Preflight `count * size_of::<T>()` against the single-allocation budget.
    pub(crate) fn check_alloc<T>(&self, count: u64) -> Result<(), super::error::SegmentError> {
        let bytes = count.checked_mul(std::mem::size_of::<T>() as u64).ok_or(
            super::error::SegmentError::LimitExceeded {
                limit: self.max_single_allocation,
                requested: u64::MAX,
            },
        )?;
        self.check_allocation_bytes(bytes)
    }

    /// Preflight the cumulative decoded/retained byte budget for one section or
    /// logical decode operation against `max_section_decode_bytes`.
    pub(crate) fn check_decoded_bytes(
        &self,
        requested: u64,
    ) -> Result<(), super::error::SegmentError> {
        if requested > self.max_section_decode_bytes {
            return Err(super::error::SegmentError::LimitExceeded {
                limit: self.max_section_decode_bytes,
                requested,
            });
        }
        Ok(())
    }
}

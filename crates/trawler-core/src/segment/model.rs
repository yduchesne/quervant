//! Immutable input model for the fixture builder.
//!
//! This is deliberately **not** a production `IndexWriter`: it is a validated,
//! deterministic input used to exercise the codecs and to generate fixtures.

use std::collections::BTreeMap;

use crate::contract::document::{DocumentKey, FieldValues};

/// One document supplied to the segment builder.
#[derive(Debug, Clone, PartialEq)]
pub struct SegmentDocument {
    /// Stable logical key.
    pub key: DocumentKey,
    /// Writer-assigned revision reference (stored only; `0` = unassigned).
    pub revision: u64,
    /// Whether this document is live in the segment.
    pub live: bool,
    /// Validated field states by field name.
    pub fields: BTreeMap<String, FieldValues>,
}

impl SegmentDocument {
    /// Create an empty document with the given key.
    #[must_use]
    pub fn new(key: DocumentKey) -> Self {
        Self {
            key,
            revision: 0,
            live: true,
            fields: BTreeMap::new(),
        }
    }

    /// Set the stored revision reference.
    #[must_use]
    pub fn with_revision(mut self, revision: u64) -> Self {
        self.revision = revision;
        self
    }

    /// Set liveness.
    #[must_use]
    pub fn with_live(mut self, live: bool) -> Self {
        self.live = live;
        self
    }

    /// Insert a field state.
    pub fn insert(
        &mut self,
        field: impl Into<String>,
        values: FieldValues,
    ) -> Result<(), crate::contract::error::QueryError> {
        let field = field.into();
        if values.is_absent() {
            self.fields.remove(&field);
        } else {
            self.fields.insert(field, values);
        }
        Ok(())
    }
}

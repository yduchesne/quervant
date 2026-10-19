//! Stored-source projections for the unified executor (PR 14).
//!
//! A projection is compiled and validated against the schema **before** any
//! segment is opened. Only effective-live selected hits are decoded, and only
//! stored fields are ever returned: an indexed token stream is never
//! reconstructed into JSON, and an unstored field can never leak.
//!
//! The five-state [`FieldValues`] vocabulary (absent, explicit null, empty multi,
//! single, multi) and nested JSON are preserved exactly. Sources are read from
//! the immutable stored section of the already-validated segment reader.

use std::collections::BTreeSet;

use crate::contract::document::{DocumentKey, FieldValues};
use crate::contract::error::{InvalidQueryReason, QueryError};
use crate::contract::result::Projection;
use crate::contract::schema::Schema;
use crate::segment::StoredRecord;

use super::error::{SearchError, SearchResult};
use super::memory::MemoryCharge;

/// A compiled, schema-validated stored projection.
#[derive(Debug, Clone)]
pub struct ProjectionPlan {
    kind: ProjectionKind,
}

#[derive(Debug, Clone)]
enum ProjectionKind {
    /// All stored fields in schema order.
    Source(Vec<(String, u32)>),
    /// Exactly the requested stored fields in request order.
    Fields(Vec<(String, u32)>),
}

impl ProjectionPlan {
    /// Compile and validate a projection against `schema`.
    ///
    /// Unknown fields, unstored fields and duplicate field requests are rejected
    /// here, before any segment work. Field ids follow the same ascending-name
    /// assignment used by the segment codec.
    pub fn compile(projection: &Projection, schema: &Schema) -> SearchResult<Self> {
        match projection {
            Projection::Source => {
                let fields = schema
                    .fields()
                    .enumerate()
                    .filter(|(_, definition)| definition.options.stored)
                    .map(|(id, definition)| {
                        (
                            definition.name.clone(),
                            u32::try_from(id).unwrap_or(u32::MAX),
                        )
                    })
                    .collect();
                Ok(Self {
                    kind: ProjectionKind::Source(fields),
                })
            }
            Projection::Fields(requested) => {
                let mut seen = BTreeSet::new();
                let mut fields = Vec::with_capacity(requested.len());
                for name in requested {
                    if !seen.insert(name.clone()) {
                        return Err(SearchError::Query(QueryError::InvalidQuery(
                            InvalidQueryReason::UnsupportedOperator {
                                field: name.clone(),
                                operator: "duplicate_projection_field",
                            },
                        )));
                    }
                    let index = schema
                        .fields()
                        .position(|definition| &definition.name == name);
                    let Some(index) = index else {
                        return Err(SearchError::Query(QueryError::InvalidQuery(
                            InvalidQueryReason::UnknownField {
                                field: name.clone(),
                            },
                        )));
                    };
                    let definition = schema.get(name).ok_or_else(|| {
                        SearchError::Query(QueryError::InvalidQuery(
                            InvalidQueryReason::UnknownField {
                                field: name.clone(),
                            },
                        ))
                    })?;
                    if !definition.options.stored {
                        return Err(SearchError::Query(QueryError::InvalidQuery(
                            InvalidQueryReason::UnstoredProjection {
                                field: name.clone(),
                            },
                        )));
                    }
                    fields.push((name.clone(), u32::try_from(index).unwrap_or(u32::MAX)));
                }
                Ok(Self {
                    kind: ProjectionKind::Fields(fields),
                })
            }
        }
    }

    /// The requested field names in output order.
    #[must_use]
    pub fn field_names(&self) -> Vec<&str> {
        match &self.kind {
            ProjectionKind::Source(fields) | ProjectionKind::Fields(fields) => {
                fields.iter().map(|(name, _)| name.as_str()).collect()
            }
        }
    }

    /// Project one already-decoded stored record.
    ///
    /// `Source` returns every present, non-absent stored field in schema order;
    /// `Fields` returns exactly the requested fields in request order, including
    /// absent states, so the five-state vocabulary round-trips.
    #[must_use]
    pub fn project(&self, record: &StoredRecord) -> Vec<(String, FieldValues)> {
        match &self.kind {
            ProjectionKind::Source(fields) => fields
                .iter()
                .filter_map(|(name, id)| {
                    record
                        .fields
                        .get(id)
                        .map(|values| (name.clone(), values.clone()))
                })
                .collect(),
            ProjectionKind::Fields(fields) => fields
                .iter()
                .map(|(name, id)| (name.clone(), record.get(*id)))
                .collect(),
        }
    }
}

/// A bounded output ledger for projected responses.
///
/// Bytes are charged before a value is retained, mirroring the search candidate
/// ledgers. A projection that would exceed the budget fails with a typed error
/// and the caller discards the entire response.
#[derive(Debug, Clone)]
pub struct ProjectionLedger {
    budget: u64,
    used: u64,
}

impl ProjectionLedger {
    #[must_use]
    pub fn new(budget: u64) -> Self {
        Self { budget, used: 0 }
    }

    #[must_use]
    pub const fn used(&self) -> u64 {
        self.used
    }

    pub fn reserve(&mut self, bytes: u64) -> SearchResult<()> {
        self.reserve_with_memory(bytes, None)
    }

    /// Reserve `bytes` locally and against the optional batch sink.
    ///
    /// Both ceilings are preflighted before either ledger is mutated, so a
    /// rejected reservation leaves the projection ledger and batch memory
    /// unchanged. Standalone callers pass `None`.
    pub(crate) fn reserve_with_memory(
        &mut self,
        bytes: u64,
        memory: Option<&mut (dyn MemoryCharge + '_)>,
    ) -> SearchResult<()> {
        let projected = self
            .used
            .checked_add(bytes)
            .ok_or(SearchError::ResourceLimit {
                limit: self.budget,
                requested: u64::MAX,
            })?;
        if projected > self.budget {
            return Err(SearchError::ResourceLimit {
                limit: self.budget,
                requested: projected,
            });
        }
        if let Some(memory) = memory {
            memory
                .preflight(bytes)
                .map_err(|error| error.to_search_error())?;
            memory
                .commit(bytes)
                .map_err(|error| error.to_search_error())?;
        }
        self.used = projected;
        Ok(())
    }

    /// Release a previously reserved projection charge.
    ///
    /// Underflow is a corrupt-ledger invariant, never silently saturated.
    pub fn release(&mut self, bytes: u64) -> SearchResult<()> {
        if bytes > self.used {
            return Err(SearchError::CorruptIndex {
                detail: "projection ledger release exceeds its reservation".to_owned(),
            });
        }
        self.used -= bytes;
        Ok(())
    }
}

/// Logical byte charge for one projected field state.
#[must_use]
pub fn projected_field_bytes(name: &str, values: &FieldValues) -> u64 {
    let mut bytes = 32 + name.len() as u64 + std::mem::size_of::<FieldValues>() as u64;
    for value in values.values() {
        bytes = bytes.saturating_add(24);
        bytes = bytes.saturating_add(value.approx_size() as u64);
    }
    bytes
}

/// Logical byte charge for one projected hit.
#[must_use]
pub fn projected_hit_bytes(key: &DocumentKey, fields: &[(String, FieldValues)]) -> u64 {
    let mut bytes = 24 + key.as_str().len() as u64;
    for (name, values) in fields {
        bytes = bytes.saturating_add(projected_field_bytes(name, values));
    }
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::contract::value::FieldType;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "stored",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "hidden",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, false, false),
                ),
            ],
            None,
        )
        .unwrap()
    }

    #[test]
    fn source_compiles_stored_fields_only() {
        let plan = ProjectionPlan::compile(&Projection::Source, &schema()).unwrap();
        assert_eq!(plan.field_names(), ["stored"]);
    }

    #[test]
    fn fields_rejects_unstored_unknown_and_duplicates() {
        assert!(
            ProjectionPlan::compile(&Projection::Fields(vec!["hidden".into()]), &schema()).is_err()
        );
        assert!(
            ProjectionPlan::compile(&Projection::Fields(vec!["nope".into()]), &schema()).is_err()
        );
        assert!(
            ProjectionPlan::compile(
                &Projection::Fields(vec!["stored".into(), "stored".into()]),
                &schema()
            )
            .is_err()
        );
        assert!(
            ProjectionPlan::compile(&Projection::Fields(vec!["stored".into()]), &schema()).is_ok()
        );
    }

    #[test]
    fn ledger_bounds_are_checked() {
        let mut ledger = ProjectionLedger::new(10);
        assert!(ledger.reserve(10).is_ok());
        assert!(matches!(
            ledger.reserve(1),
            Err(SearchError::ResourceLimit { .. })
        ));
        ledger.release(10).unwrap();
        assert_eq!(ledger.used(), 0);
        assert!(ledger.release(1).is_err());
        assert_eq!(ledger.used(), 0);
    }
}

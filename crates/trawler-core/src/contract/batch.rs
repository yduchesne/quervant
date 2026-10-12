//! First-class ordered batch request/response contracts (A25/A25.1).
//!
//! This module defines shapes and validators only. It contains no scheduler and
//! no query executor; PR 14 owns batch execution.

use super::aggregation::Aggregation;
use super::budget::Budgets;
use super::capability::{CapabilityRequest, CapabilitySet};
use super::document::DocumentKey;
use super::error::{InvalidBatchReason, InvalidQueryReason, QueryError};
use super::query::Query;
use super::result::{Cursor, PitId, Projection, Sort, TopK};
use super::schema::Schema;
use super::value::FieldValue;

/// One ordinary, independently parameterized search request.
#[derive(Debug, Clone, PartialEq)]
pub struct QueryRequest {
    pub query: Query,
    pub sort: Sort,
    pub top_k: TopK,
    pub aggregation: Option<Aggregation>,
    pub projection: Projection,
    pub budgets: Budgets,
    pub capabilities: CapabilityRequest,
    pub pit: Option<PitId>,
    pub cursor: Option<Cursor>,
}

impl QueryRequest {
    #[must_use]
    pub fn new(query: Query) -> Self {
        Self {
            query,
            sort: Sort::default(),
            top_k: TopK { limit: 10 },
            aggregation: None,
            projection: Projection::Source,
            budgets: Budgets::new(),
            capabilities: CapabilityRequest::new(),
            pit: None,
            cursor: None,
        }
    }

    pub fn validate(&self, schema: &Schema, supported: &CapabilitySet) -> Result<(), QueryError> {
        self.query.validate(schema, &self.budgets)?;
        self.sort.validate(schema)?;
        self.top_k.validate(&self.budgets)?;
        self.projection.validate(schema)?;
        if let Some(aggregation) = &self.aggregation {
            aggregation.validate(schema, &self.budgets)?;
        }
        self.capabilities.negotiate(supported)?;
        if let Some(cursor) = &self.cursor {
            let pit = self
                .pit
                .as_ref()
                .ok_or(InvalidQueryReason::CursorPitMismatch)?;
            cursor.matches(pit, &self.sort)?;
        }
        Ok(())
    }
}

/// Batch-wide resource governance.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BatchBudget {
    pub max_queries_per_batch: usize,
    pub limits: Budgets,
}

impl BatchBudget {
    #[must_use]
    pub fn new(max_queries_per_batch: usize) -> Self {
        Self {
            max_queries_per_batch,
            limits: Budgets::new(),
        }
    }

    #[must_use]
    pub fn with_limits(mut self, limits: Budgets) -> Self {
        self.limits = limits;
        self
    }
}

/// A batch of independent logical searches.
#[derive(Debug, Clone, PartialEq)]
pub struct BatchQueryRequest {
    pub queries: Vec<QueryRequest>,
    pub shared_pit: Option<PitId>,
    pub budget: BatchBudget,
}

impl BatchQueryRequest {
    #[must_use]
    pub fn new(queries: Vec<QueryRequest>, shared_pit: Option<PitId>, budget: BatchBudget) -> Self {
        Self {
            queries,
            shared_pit,
            budget,
        }
    }

    /// Validates only the batch envelope. These failures reject the whole batch
    /// before execution and are distinct from per-query failures.
    pub fn validate_envelope(&self) -> Result<(), QueryError> {
        if self.queries.is_empty() {
            return Err(InvalidBatchReason::Empty.into());
        }
        if self.budget.max_queries_per_batch == 0 {
            return Err(InvalidBatchReason::InvalidAggregateBudget.into());
        }
        if self.queries.len() > self.budget.max_queries_per_batch {
            return Err(InvalidBatchReason::TooManyQueries {
                count: self.queries.len(),
                max: self.budget.max_queries_per_batch,
            }
            .into());
        }
        if let Some(shared) = &self.shared_pit {
            for query in &self.queries {
                if let Some(own) = &query.pit
                    && own != shared
                {
                    return Err(InvalidBatchReason::ConflictingPit.into());
                }
            }
        }
        Ok(())
    }

    /// Validates the envelope, then every query in input order.
    ///
    /// Returns an envelope error, or exactly one result per input query in the
    /// same order. Per-query failures never remove or reorder slots.
    pub fn validate(
        &self,
        schema: &Schema,
        supported: &CapabilitySet,
    ) -> Result<Vec<Result<(), QueryError>>, QueryError> {
        self.validate_envelope()?;
        Ok(self
            .queries
            .iter()
            .map(|query| query.validate(schema, supported))
            .collect())
    }

    #[must_use]
    pub fn query_count(&self) -> usize {
        self.queries.len()
    }
}

/// One search hit shape. PR 2 does not produce hits.
#[derive(Debug, Clone, PartialEq)]
pub struct SearchHit {
    pub key: DocumentKey,
    pub score: Option<f32>,
    pub fields: Vec<(String, FieldValue)>,
}

/// One search response shape. PR 2 does not execute searches.
#[derive(Debug, Clone, PartialEq)]
pub struct SearchResponse {
    pub hits: Vec<SearchHit>,
    pub total_hits: u64,
    pub next_cursor: Option<Cursor>,
}

impl SearchResponse {
    #[must_use]
    pub fn empty() -> Self {
        Self {
            hits: Vec::new(),
            total_hits: 0,
            next_cursor: None,
        }
    }
}

/// Exactly one ordered outcome per accepted query.
#[derive(Debug, Clone, PartialEq)]
pub enum PerQueryOutcome {
    Success(SearchResponse),
    Failure(QueryError),
}

/// The response for an accepted batch.
///
/// The exactly-N guarantee applies only when this response is actually
/// returned; an envelope rejection or a transport/process failure cannot
/// promise N slots.
#[derive(Debug, Clone, PartialEq)]
pub struct BatchQueryResponse {
    results: Vec<PerQueryOutcome>,
}

impl BatchQueryResponse {
    pub fn from_outcomes(results: Vec<PerQueryOutcome>) -> Result<Self, QueryError> {
        if results.is_empty() {
            return Err(InvalidBatchReason::Empty.into());
        }
        Ok(Self { results })
    }

    /// Assembles a response from one validation-or-execution result per query,
    /// preserving input order and mapping per-query errors to failure slots.
    pub fn from_validation(
        results: Vec<Result<SearchResponse, QueryError>>,
    ) -> Result<Self, QueryError> {
        let outcomes = results
            .into_iter()
            .map(|result| match result {
                Ok(response) => PerQueryOutcome::Success(response),
                Err(error) => PerQueryOutcome::Failure(error),
            })
            .collect();
        Self::from_outcomes(outcomes)
    }

    #[must_use]
    pub fn results(&self) -> &[PerQueryOutcome] {
        &self.results
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.results.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.results.is_empty()
    }

    #[must_use]
    pub fn slot(&self, index: usize) -> Option<&PerQueryOutcome> {
        self.results.get(index)
    }
}

/// Default batch limit used by examples and tests.
pub const DEFAULT_MAX_QUERIES_PER_BATCH: usize = 16;

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::contract::value::FieldType;

    fn schema() -> Schema {
        Schema::new(
            vec![FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )],
            None,
        )
        .unwrap()
    }

    fn request() -> QueryRequest {
        QueryRequest::new(Query::Term {
            field: "title".into(),
            value: FieldValue::Text("x".into()),
        })
    }

    #[test]
    fn envelope_validation() {
        let budgets = CapabilitySet::new();
        let empty = BatchQueryRequest::new(vec![], None, BatchBudget::new(4));
        assert!(empty.validate_envelope().is_err());
        let ok = BatchQueryRequest::new(vec![request()], None, BatchBudget::new(4));
        assert!(ok.validate(&schema(), &budgets).is_ok());
        let over = BatchQueryRequest::new(
            vec![request(), request(), request()],
            None,
            BatchBudget::new(2),
        );
        assert!(matches!(
            over.validate_envelope(),
            Err(QueryError::InvalidBatch(
                InvalidBatchReason::TooManyQueries { .. }
            ))
        ));
    }

    #[test]
    fn shared_pit_conflict_rejected() {
        let shared = PitId::new("pit").unwrap();
        let mut query = request();
        query.pit = Some(PitId::new("other").unwrap());
        let batch = BatchQueryRequest::new(vec![query], Some(shared), BatchBudget::new(4));
        assert!(matches!(
            batch.validate_envelope(),
            Err(QueryError::InvalidBatch(InvalidBatchReason::ConflictingPit))
        ));
    }

    #[test]
    fn ordered_mixed_outcomes() {
        let bad = Query::Term {
            field: "missing".into(),
            value: FieldValue::Text("x".into()),
        };
        let query = request();
        let batch = BatchQueryRequest::new(
            vec![query.clone(), QueryRequest::new(bad), query],
            None,
            BatchBudget::new(4),
        );
        let results = batch.validate(&schema(), &CapabilitySet::new()).unwrap();
        assert_eq!(results.len(), 3);
        assert!(results[0].is_ok());
        assert!(results[1].is_err());
        assert!(results[2].is_ok());
        // Assemble a response without executing searches: validation successes
        // map to placeholder response *shapes* only.
        let mapped: Vec<Result<SearchResponse, QueryError>> = results
            .into_iter()
            .map(|result| result.map(|()| SearchResponse::empty()))
            .collect();
        let response = BatchQueryResponse::from_validation(mapped).unwrap();
        assert_eq!(response.len(), 3);
        assert!(matches!(
            response.slot(0),
            Some(PerQueryOutcome::Success(_))
        ));
        assert!(matches!(
            response.slot(1),
            Some(PerQueryOutcome::Failure(_))
        ));
        assert!(matches!(
            response.slot(2),
            Some(PerQueryOutcome::Success(_))
        ));
    }

    #[test]
    fn empty_response_rejected() {
        assert!(BatchQueryResponse::from_outcomes(vec![]).is_err());
    }
}

#[cfg(test)]
mod coverage_tests {
    use super::*;
    use crate::contract::budget::BudgetKind;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::contract::value::FieldType;

    fn schema() -> Schema {
        Schema::new(
            vec![FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )],
            None,
        )
        .unwrap()
    }

    fn request() -> QueryRequest {
        QueryRequest::new(Query::Term {
            field: "title".into(),
            value: FieldValue::Text("x".into()),
        })
    }

    #[test]
    fn batch_budget_and_counts() {
        let budget = BatchBudget::new(4).with_limits(
            Budgets::new()
                .with(BudgetKind::BatchMemoryBytes, 1024)
                .unwrap(),
        );
        assert_eq!(budget.max_queries_per_batch, 4);
        let batch_request = BatchQueryRequest::new(vec![request(), request()], None, budget);
        assert_eq!(batch_request.query_count(), 2);

        let invalid = BatchQueryRequest::new(vec![request()], None, BatchBudget::new(0));
        assert!(matches!(
            invalid.validate_envelope(),
            Err(QueryError::InvalidBatch(
                InvalidBatchReason::InvalidAggregateBudget
            ))
        ));
    }

    #[test]
    fn per_query_capability_and_cursor_errors() {
        let schema = schema();
        let mut capability = request();
        capability.capabilities.required =
            vec![crate::contract::capability::Capability::new("x", 1)];
        let results = BatchQueryRequest::new(vec![capability], None, BatchBudget::new(4))
            .validate(&schema, &CapabilitySet::new())
            .unwrap();
        assert!(results[0].is_err());

        let mut cursor_request = request();
        cursor_request.cursor = Some(Cursor::new(
            PitId::new("pit").unwrap(),
            Sort::default(),
            DocumentKey::new("k").unwrap(),
            crate::contract::value::Timestamp::from_micros(10),
        ));
        let results = BatchQueryRequest::new(vec![cursor_request], None, BatchBudget::new(4))
            .validate(&schema, &CapabilitySet::new())
            .unwrap();
        assert!(matches!(
            results[0],
            Err(QueryError::InvalidQuery(
                InvalidQueryReason::CursorPitMismatch
            ))
        ));
    }

    #[test]
    fn response_helpers() {
        let response = BatchQueryResponse::from_outcomes(vec![PerQueryOutcome::Success(
            SearchResponse::empty(),
        )])
        .unwrap();
        assert_eq!(response.len(), 1);
        assert!(!response.is_empty());
        assert!(response.slot(5).is_none());
        assert!(response.results().len() == 1);
        assert_eq!(SearchResponse::empty().total_hits, 0);
        assert_eq!(DEFAULT_MAX_QUERIES_PER_BATCH, 16);
    }
}

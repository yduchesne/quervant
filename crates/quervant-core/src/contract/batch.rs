//! First-class ordered batch request/response contracts (A25/A25.1).
//!
//! This module defines shapes and validators only. It contains no scheduler and
//! no query executor; PR 14 owns batch execution.

use super::aggregation::{Aggregation, AggregationResult};
use super::budget::{BudgetKind, BudgetPolicy, Budgets};
use super::capability::{CapabilityRequest, CapabilitySet};
use super::document::DocumentKey;
use super::document::FieldValues;
use super::error::{InvalidBatchReason, InvalidQueryReason, QueryError};
use super::query::Query;
use super::result::{Cursor, PitId, Projection, Sort, TopK};
use super::schema::Schema;
#[cfg(test)]
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

    /// Intrinsic shape validity of the aggregate budget.
    ///
    /// This checks only representability and recognized aggregate kinds; it
    /// does not consult any policy ceiling or consume any resource.
    pub fn validate_intrinsic(&self) -> Result<(), QueryError> {
        if self.max_queries_per_batch == 0 {
            return Err(InvalidBatchReason::InvalidAggregateBudget.into());
        }
        for (kind, _) in self.limits.iter() {
            if !kind.is_batch_aggregate() {
                return Err(InvalidBatchReason::InvalidAggregateBudgetKind { kind }.into());
            }
        }
        Ok(())
    }

    /// Resolves the effective maximum query count.
    ///
    /// `max_queries_per_batch` is the authoritative count ceiling; if the
    /// aggregate limits also carry [`BudgetKind::QueriesPerBatch`], the
    /// stricter (minimum) of the two applies. Both sources must be positive.
    pub fn effective_max_queries(&self) -> Result<usize, QueryError> {
        let mut max = self.max_queries_per_batch;
        if let Some(queries) = self.limits.get(BudgetKind::QueriesPerBatch) {
            max = max.min(usize::try_from(queries).unwrap_or(usize::MAX));
        }
        if max == 0 {
            return Err(InvalidBatchReason::InvalidAggregateBudget.into());
        }
        Ok(max)
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
        self.budget.validate_intrinsic()?;
        let max = self.budget.effective_max_queries()?;
        if self.queries.len() > max {
            return Err(InvalidBatchReason::TooManyQueries {
                count: self.queries.len(),
                max,
            }
            .into());
        }
        if let Some(shared) = &self.shared_pit {
            for query in &self.queries {
                if let Some(own) = &query.pit {
                    if own != shared {
                        return Err(InvalidBatchReason::ConflictingPit.into());
                    }
                }
            }
        }
        Ok(())
    }

    /// Validates the envelope and then enforces the applicable budget policy
    /// ceilings on the aggregate batch limits.
    ///
    /// This is still contract-only: it rejects above-ceiling configuration with
    /// [`QueryError::BudgetPolicyViolation`] and never reserves, meters or
    /// consumes runtime resources. PR 14 owns runtime admission and metering.
    pub fn validate_envelope_with_policy(&self, policy: &BudgetPolicy) -> Result<(), QueryError> {
        self.validate_envelope()?;
        let max = self.budget.effective_max_queries()?;
        policy.effective(
            BudgetKind::QueriesPerBatch,
            Some(u64::try_from(max).unwrap_or(u64::MAX)),
        )?;
        for (kind, value) in self.budget.limits.iter() {
            policy.effective(kind, Some(value))?;
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

/// One search hit shape. The projected field vector preserves the full
/// five-state [`FieldValues`] vocabulary (absent, explicit null, empty multi,
/// single, multi); it never collapses states or leaks unstored fields.
#[derive(Debug, Clone, PartialEq)]
pub struct SearchHit {
    pub key: DocumentKey,
    pub score: Option<f32>,
    pub fields: Vec<(String, FieldValues)>,
}

/// One search response shape. PR 2 does not execute searches.
#[derive(Debug, Clone, PartialEq)]
pub struct SearchResponse {
    pub hits: Vec<SearchHit>,
    pub total_hits: u64,
    pub next_cursor: Option<Cursor>,
    /// Exact aggregation result when the slot requested one; `None` otherwise.
    pub aggregation: Option<AggregationResult>,
}

impl SearchResponse {
    #[must_use]
    pub fn empty() -> Self {
        Self {
            hits: Vec::new(),
            total_hits: 0,
            next_cursor: None,
            aggregation: None,
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
    /// Checked construction bound to an accepted batch request.
    ///
    /// Requires the envelope to be valid, then requires **exactly** one outcome
    /// per input query in positional order. A count mismatch is a typed
    /// [`InvalidBatchReason::CardinalityMismatch`]; outcomes are never
    /// truncated, padded, reordered or fabricated.
    pub fn from_outcomes_for(
        request: &BatchQueryRequest,
        results: Vec<PerQueryOutcome>,
    ) -> Result<Self, QueryError> {
        request.validate_envelope()?;
        let expected = request.query_count();
        if results.len() != expected {
            return Err(InvalidBatchReason::CardinalityMismatch {
                expected,
                actual: results.len(),
            }
            .into());
        }
        Ok(Self { results })
    }

    /// Checked construction from one validation-or-execution result per query,
    /// preserving input order and mapping per-query errors to failure slots.
    pub fn from_validation_for(
        request: &BatchQueryRequest,
        results: Vec<Result<SearchResponse, QueryError>>,
    ) -> Result<Self, QueryError> {
        let outcomes = results
            .into_iter()
            .map(|result| match result {
                Ok(response) => PerQueryOutcome::Success(response),
                Err(error) => PerQueryOutcome::Failure(error),
            })
            .collect();
        Self::from_outcomes_for(request, outcomes)
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
        let response = BatchQueryResponse::from_validation_for(&batch, mapped).unwrap();
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
    fn response_cardinality_is_checked() {
        let empty = BatchQueryRequest::new(vec![], None, BatchBudget::new(4));
        assert!(BatchQueryResponse::from_outcomes_for(&empty, vec![]).is_err());
        let one = BatchQueryRequest::new(vec![request()], None, BatchBudget::new(4));
        assert!(BatchQueryResponse::from_outcomes_for(&one, vec![]).is_err());
        assert!(
            BatchQueryResponse::from_outcomes_for(
                &one,
                vec![
                    PerQueryOutcome::Success(SearchResponse::empty()),
                    PerQueryOutcome::Success(SearchResponse::empty()),
                ]
            )
            .is_err()
        );
        assert!(
            BatchQueryResponse::from_outcomes_for(
                &one,
                vec![PerQueryOutcome::Success(SearchResponse::empty())]
            )
            .is_ok()
        );
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
        let query = QueryRequest::new(Query::Term {
            field: "title".into(),
            value: FieldValue::Text("x".into()),
        });
        let request = BatchQueryRequest::new(vec![query], None, BatchBudget::new(4));
        let response = BatchQueryResponse::from_outcomes_for(
            &request,
            vec![PerQueryOutcome::Success(SearchResponse::empty())],
        )
        .unwrap();
        assert_eq!(response.len(), 1);
        assert!(!response.is_empty());
        assert!(response.slot(5).is_none());
        assert!(response.results().len() == 1);
        assert_eq!(SearchResponse::empty().total_hits, 0);
        assert_eq!(DEFAULT_MAX_QUERIES_PER_BATCH, 16);
    }
}

#[cfg(test)]
mod amendment_tests {
    use super::*;
    use crate::contract::budget::BudgetPolicy;

    fn request() -> QueryRequest {
        QueryRequest::new(Query::Term {
            field: "title".into(),
            value: FieldValue::Text("x".into()),
        })
    }

    fn single() -> BatchQueryRequest {
        BatchQueryRequest::new(vec![request()], None, BatchBudget::new(4))
    }

    #[test]
    fn b_card01_single_outcome() {
        let response = BatchQueryResponse::from_outcomes_for(
            &single(),
            vec![PerQueryOutcome::Success(SearchResponse::empty())],
        )
        .unwrap();
        assert_eq!(response.len(), 1);
    }

    #[test]
    fn b_card02_ordered_success_failure_success() {
        let request = BatchQueryRequest::new(
            vec![request(), request(), request()],
            None,
            BatchBudget::new(3),
        );
        let error = QueryError::BudgetExceeded {
            kind: BudgetKind::Groups,
        };
        let response = BatchQueryResponse::from_outcomes_for(
            &request,
            vec![
                PerQueryOutcome::Success(SearchResponse::empty()),
                PerQueryOutcome::Failure(error.clone()),
                PerQueryOutcome::Success(SearchResponse::empty()),
            ],
        )
        .unwrap();
        assert_eq!(response.len(), 3);
        assert!(matches!(
            response.slot(0),
            Some(PerQueryOutcome::Success(_))
        ));
        assert_eq!(response.slot(1), Some(&PerQueryOutcome::Failure(error)));
        assert!(matches!(
            response.slot(2),
            Some(PerQueryOutcome::Success(_))
        ));
    }

    #[test]
    fn b_card03_too_few_outcomes() {
        let request = BatchQueryRequest::new(
            vec![request(), request(), request()],
            None,
            BatchBudget::new(3),
        );
        assert!(matches!(
            BatchQueryResponse::from_outcomes_for(
                &request,
                vec![
                    PerQueryOutcome::Success(SearchResponse::empty()),
                    PerQueryOutcome::Success(SearchResponse::empty()),
                ]
            ),
            Err(QueryError::InvalidBatch(
                InvalidBatchReason::CardinalityMismatch {
                    expected: 3,
                    actual: 2
                }
            ))
        ));
    }

    #[test]
    fn b_card04_too_many_outcomes() {
        let request = BatchQueryRequest::new(
            vec![request(), request(), request()],
            None,
            BatchBudget::new(3),
        );
        assert!(matches!(
            BatchQueryResponse::from_outcomes_for(
                &request,
                vec![
                    PerQueryOutcome::Success(SearchResponse::empty()),
                    PerQueryOutcome::Success(SearchResponse::empty()),
                    PerQueryOutcome::Success(SearchResponse::empty()),
                    PerQueryOutcome::Success(SearchResponse::empty()),
                ]
            ),
            Err(QueryError::InvalidBatch(
                InvalidBatchReason::CardinalityMismatch {
                    expected: 3,
                    actual: 4
                }
            ))
        ));
    }

    #[test]
    fn b_card05_empty_envelope_has_no_response() {
        let request = BatchQueryRequest::new(vec![], None, BatchBudget::new(4));
        assert!(matches!(
            BatchQueryResponse::from_outcomes_for(&request, vec![]),
            Err(QueryError::InvalidBatch(InvalidBatchReason::Empty))
        ));
    }

    #[test]
    fn b_card06_rejected_envelope_has_no_response() {
        let shared = PitId::new("pit").unwrap();
        let mut query = request();
        query.pit = Some(PitId::new("other").unwrap());
        let request = BatchQueryRequest::new(vec![query], Some(shared), BatchBudget::new(4));
        assert!(matches!(
            BatchQueryResponse::from_outcomes_for(
                &request,
                vec![PerQueryOutcome::Success(SearchResponse::empty())]
            ),
            Err(QueryError::InvalidBatch(InvalidBatchReason::ConflictingPit))
        ));
    }

    #[test]
    fn b_bud01_valid_aggregate_configuration() {
        let limits = Budgets::new()
            .with(BudgetKind::BatchMemoryBytes, 1_000)
            .unwrap()
            .with(BudgetKind::BatchResponseBytes, 1_000)
            .unwrap()
            .with(BudgetKind::BatchAggregate, 5)
            .unwrap();
        let request = BatchQueryRequest::new(
            vec![request()],
            None,
            BatchBudget::new(4).with_limits(limits),
        );
        assert!(request.validate_envelope().is_ok());
    }

    #[test]
    fn b_bud02_invalid_aggregate_kind_rejected() {
        let limits = Budgets::new().with(BudgetKind::ResultWindow, 10).unwrap();
        let request = BatchQueryRequest::new(
            vec![request()],
            None,
            BatchBudget::new(4).with_limits(limits),
        );
        assert!(matches!(
            request.validate_envelope(),
            Err(QueryError::InvalidBatch(
                InvalidBatchReason::InvalidAggregateBudgetKind {
                    kind: BudgetKind::ResultWindow
                }
            ))
        ));
    }

    fn policy_with_queries_ceiling(ceiling: u64) -> BudgetPolicy {
        BudgetPolicy::new(
            Budgets::new()
                .with(BudgetKind::QueriesPerBatch, ceiling)
                .unwrap(),
            Budgets::new(),
            Budgets::new(),
            Budgets::new(),
        )
    }

    #[test]
    fn b_bud03_above_policy_rejected() {
        let request = BatchQueryRequest::new(vec![request()], None, BatchBudget::new(5));
        assert!(matches!(
            request.validate_envelope_with_policy(&policy_with_queries_ceiling(2)),
            Err(QueryError::BudgetPolicyViolation {
                kind: BudgetKind::QueriesPerBatch,
                ..
            })
        ));
    }

    #[test]
    fn b_bud04_at_ceiling_accepted() {
        let request = BatchQueryRequest::new(vec![request(), request()], None, BatchBudget::new(2));
        assert!(
            request
                .validate_envelope_with_policy(&policy_with_queries_ceiling(2))
                .is_ok()
        );
    }

    #[test]
    fn b_bud05_conflicting_count_ceilings_use_strictest() {
        let limits = Budgets::new().with(BudgetKind::QueriesPerBatch, 3).unwrap();
        let at_limit = BatchQueryRequest::new(
            vec![request(), request(), request()],
            None,
            BatchBudget::new(5).with_limits(limits.clone()),
        );
        assert_eq!(at_limit.budget.effective_max_queries().unwrap(), 3);
        assert!(at_limit.validate_envelope().is_ok());
        let over = BatchQueryRequest::new(
            vec![request(), request(), request(), request()],
            None,
            BatchBudget::new(5).with_limits(limits),
        );
        assert!(matches!(
            over.validate_envelope(),
            Err(QueryError::InvalidBatch(
                InvalidBatchReason::TooManyQueries { max: 3, .. }
            ))
        ));
    }

    #[test]
    fn b_bud06_local_query_budget_error_is_isolated() {
        use crate::contract::document::Cardinality;
        use crate::contract::schema::{FieldDefinition, FieldOptions};
        use crate::contract::value::FieldType;
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )],
            None,
        )
        .unwrap();
        let mut over_budget = request();
        over_budget.top_k = TopK { limit: 100 };
        over_budget.budgets = Budgets::new().with(BudgetKind::ResultWindow, 5).unwrap();
        let request = BatchQueryRequest::new(
            vec![request(), over_budget, request()],
            None,
            BatchBudget::new(4),
        );
        let results = request.validate(&schema, &CapabilitySet::new()).unwrap();
        assert_eq!(results.len(), 3);
        assert!(results[0].is_ok());
        assert!(results[1].is_err());
        assert!(results[2].is_ok());
    }

    #[test]
    fn b_bud07_contract_validation_is_pure() {
        let request = BatchQueryRequest::new(vec![request()], None, BatchBudget::new(4));
        let policy = policy_with_queries_ceiling(4);
        let first = request.validate_envelope_with_policy(&policy);
        let second = request.validate_envelope_with_policy(&policy);
        assert_eq!(first, second);
        assert!(first.is_ok());
    }
}

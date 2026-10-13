//! Validated contract layer for documents, fields, queries and batches.
//!
//! This module defines the public PR 2 contracts only. It validates shapes and
//! types; it does **not** execute queries, store documents, allocate revisions,
//! read a snapshot, or freeze any on-disk format.

pub mod aggregation;
pub mod batch;
pub mod budget;
pub mod capability;
pub mod document;
pub mod error;
pub mod query;
#[cfg(test)]
pub mod reference;
pub mod result;
pub mod schema;
pub mod value;

pub use aggregation::{
    Aggregate, AggregateFunction, Aggregation, ExactDistinct, GroupBy, GroupKey, TimeBucket,
    TopKFrequency,
};
pub use batch::{
    BatchBudget, BatchQueryRequest, BatchQueryResponse, PerQueryOutcome, QueryRequest, SearchHit,
    SearchResponse,
};
pub use budget::{BudgetKind, BudgetPolicy, Budgets};
pub use capability::{Capability, CapabilityRequest, CapabilitySet};
pub use document::{
    Cardinality, Document, DocumentKey, FieldValues, IdempotencyKey, MutationIntent,
    MutationRequest, MutationResponse,
};
pub use error::{
    CancelReason, DocumentError, InvalidBatchReason, InvalidQueryReason, QueryError, SchemaError,
    ValueError,
};
pub use query::{
    Bound, ConcreteJsonPath, GeoBoundingBox, GeoPolygon, GeoRadius, JsonNodeRef, JsonPathExpr,
    JsonPathSegment, Query,
};
pub use result::{
    Cursor, MissingValuePosition, MultiValueSelector, PitId, Projection, Sort, SortDirection,
    SortField, TopK,
};
pub use schema::{FieldDefinition, FieldOptions, Schema};
pub use value::{FieldType, FieldValue, GeoPoint, IpNetwork, JsonNumber, JsonValue, Timestamp};

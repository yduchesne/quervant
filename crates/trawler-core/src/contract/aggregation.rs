//! Aggregation contracts: group-by, aggregates, distinct, top-K, time buckets
//! (A16–A19). No production aggregation engine is implemented here.

use super::budget::{BudgetKind, Budgets, checked_product};
use super::error::{InvalidQueryReason, QueryError};
use super::schema::Schema;
use super::value::FieldType;

/// A bounded aggregate function.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AggregateFunction {
    Count,
    Sum { field: String },
    Min { field: String },
    Max { field: String },
    Avg { field: String },
}

/// A single aggregate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Aggregate {
    pub function: AggregateFunction,
}

impl Aggregate {
    #[must_use]
    pub const fn count() -> Self {
        Self {
            function: AggregateFunction::Count,
        }
    }

    #[must_use]
    pub fn sum(field: impl Into<String>) -> Self {
        Self {
            function: AggregateFunction::Sum {
                field: field.into(),
            },
        }
    }

    #[must_use]
    pub fn min(field: impl Into<String>) -> Self {
        Self {
            function: AggregateFunction::Min {
                field: field.into(),
            },
        }
    }

    #[must_use]
    pub fn max(field: impl Into<String>) -> Self {
        Self {
            function: AggregateFunction::Max {
                field: field.into(),
            },
        }
    }

    #[must_use]
    pub fn avg(field: impl Into<String>) -> Self {
        Self {
            function: AggregateFunction::Avg {
                field: field.into(),
            },
        }
    }
}

/// One group-by key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GroupKey {
    Field(String),
}

/// Group-by one or more typed keys.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GroupBy {
    pub keys: Vec<GroupKey>,
}

impl GroupBy {
    #[must_use]
    pub fn new(keys: Vec<GroupKey>) -> Self {
        Self { keys }
    }
}

/// A fixed UTC time bucket width.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TimeBucket {
    pub width_micros: i64,
}

/// Exact distinct count over a field.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExactDistinct {
    pub field: String,
}

/// Top-K frequent values over a field.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TopKFrequency {
    pub field: String,
    pub k: usize,
}

/// The aggregation section of a query request.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Aggregation {
    pub group_by: Option<GroupBy>,
    pub aggregates: Vec<Aggregate>,
    pub exact_distinct: Option<ExactDistinct>,
    pub top_k: Option<TopKFrequency>,
    pub time_bucket: Option<TimeBucket>,
}

impl Aggregation {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn validate(&self, schema: &Schema, budgets: &Budgets) -> Result<(), QueryError> {
        if let Some(group_by) = &self.group_by {
            if let Some(max) = budgets.get(BudgetKind::GroupKeyFields)
                && u64::try_from(group_by.keys.len()).unwrap_or(u64::MAX) > max
            {
                return Err(QueryError::BudgetExceeded {
                    kind: BudgetKind::GroupKeyFields,
                });
            }
            for key in &group_by.keys {
                let GroupKey::Field(field) = key;
                let definition =
                    schema
                        .get(field)
                        .ok_or_else(|| InvalidQueryReason::UnknownField {
                            field: field.clone(),
                        })?;
                if matches!(definition.field_type, FieldType::Json | FieldType::Text) {
                    return Err(InvalidQueryReason::UnsupportedOperator {
                        field: field.clone(),
                        operator: "group_by",
                    }
                    .into());
                }
            }
        }
        for aggregate in &self.aggregates {
            match &aggregate.function {
                AggregateFunction::Count => {}
                AggregateFunction::Sum { field } => {
                    require_numeric(schema, field, false)?;
                }
                AggregateFunction::Avg { field } => {
                    require_numeric(schema, field, false)?;
                }
                AggregateFunction::Min { field } | AggregateFunction::Max { field } => {
                    require_numeric(schema, field, true)?;
                }
            }
        }
        if let Some(distinct) = &self.exact_distinct {
            schema
                .get(&distinct.field)
                .ok_or_else(|| InvalidQueryReason::UnknownField {
                    field: distinct.field.clone(),
                })?;
            if let Some(max) = budgets.get(BudgetKind::DistinctKeys)
                && max == 0
            {
                return Err(QueryError::InvalidQuery(InvalidQueryReason::ZeroBudget {
                    kind: BudgetKind::DistinctKeys,
                }));
            }
        }
        if let Some(top_k) = &self.top_k {
            schema
                .get(&top_k.field)
                .ok_or_else(|| InvalidQueryReason::UnknownField {
                    field: top_k.field.clone(),
                })?;
            if top_k.k == 0 {
                return Err(InvalidQueryReason::ZeroBudget {
                    kind: BudgetKind::DistinctKeys,
                }
                .into());
            }
        }
        if let Some(bucket) = &self.time_bucket
            && bucket.width_micros <= 0
        {
            return Err(InvalidQueryReason::InvalidTimeBucket.into());
        }
        Ok(())
    }
}

fn require_numeric(schema: &Schema, field: &str, allow_timestamp: bool) -> Result<(), QueryError> {
    let definition = schema
        .get(field)
        .ok_or_else(|| InvalidQueryReason::UnknownField {
            field: field.to_owned(),
        })?;
    let allowed = definition.field_type.is_numeric()
        || (allow_timestamp && definition.field_type == FieldType::Timestamp);
    if allowed {
        Ok(())
    } else {
        Err(InvalidQueryReason::UnsupportedOperator {
            field: field.to_owned(),
            operator: "aggregate",
        }
        .into())
    }
}

/// The checked per-document group expansion for a set of group keys.
///
/// Each key contributes its distinct value count (empty keys contribute zero).
/// The product is computed with checked arithmetic before any materialization.
pub fn group_expansion_count(
    distinct_values_per_key: &[usize],
    per_document_limit: u64,
) -> Result<u64, QueryError> {
    if distinct_values_per_key.contains(&0) {
        return Ok(0);
    }
    let factors: Vec<u64> = distinct_values_per_key
        .iter()
        .map(|count| u64::try_from(*count).unwrap_or(u64::MAX))
        .collect();
    let product = checked_product(&factors)?;
    if product > per_document_limit {
        return Err(QueryError::BudgetExceeded {
            kind: BudgetKind::GroupExpansions,
        });
    }
    Ok(product)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "host",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "level",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "bytes",
                    FieldType::U64,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "body",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
            ],
            None,
        )
        .unwrap()
    }

    #[test]
    fn validates_aggregations() {
        let schema = schema();
        let budgets = Budgets::new()
            .with(BudgetKind::GroupKeyFields, 4)
            .unwrap()
            .with(BudgetKind::DistinctKeys, 100)
            .unwrap();
        let ok = Aggregation {
            group_by: Some(GroupBy::new(vec![
                GroupKey::Field("host".into()),
                GroupKey::Field("level".into()),
            ])),
            aggregates: vec![
                Aggregate::count(),
                Aggregate::sum("bytes"),
                Aggregate::min("ts"),
            ],
            exact_distinct: Some(ExactDistinct {
                field: "host".into(),
            }),
            top_k: Some(TopKFrequency {
                field: "host".into(),
                k: 5,
            }),
            time_bucket: Some(TimeBucket {
                width_micros: 60_000_000,
            }),
        };
        assert!(ok.validate(&schema, &budgets).is_ok());

        let bad_group = Aggregation {
            group_by: Some(GroupBy::new(vec![GroupKey::Field("body".into())])),
            ..Aggregation::new()
        };
        assert!(bad_group.validate(&schema, &budgets).is_err());

        let bad_sum = Aggregation {
            aggregates: vec![Aggregate::sum("host")],
            ..Aggregation::new()
        };
        assert!(bad_sum.validate(&schema, &budgets).is_err());

        let bucket = Aggregation {
            time_bucket: Some(TimeBucket { width_micros: 0 }),
            ..Aggregation::new()
        };
        assert!(bucket.validate(&schema, &budgets).is_err());
    }

    #[test]
    fn group_expansion_bounds() {
        assert_eq!(group_expansion_count(&[2, 3], 10).unwrap(), 6);
        assert_eq!(group_expansion_count(&[2, 0], 10).unwrap(), 0);
        assert!(matches!(
            group_expansion_count(&[2, 3], 5),
            Err(QueryError::BudgetExceeded {
                kind: BudgetKind::GroupExpansions
            })
        ));
        assert!(matches!(
            group_expansion_count(&[u64::MAX as usize, 4], u64::MAX),
            Err(QueryError::BudgetExceeded { .. })
        ));
    }
}

#[cfg(test)]
mod coverage_tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::{FieldDefinition, FieldOptions};
    use crate::contract::value::FieldType;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "host",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "bytes",
                    FieldType::U64,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
                FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::new(true, true, true),
                ),
            ],
            None,
        )
        .unwrap()
    }

    #[test]
    fn aggregate_constructors_and_errors() {
        assert_eq!(Aggregate::count().function, AggregateFunction::Count);
        assert!(matches!(
            Aggregate::sum("bytes").function,
            AggregateFunction::Sum { .. }
        ));
        assert!(matches!(
            Aggregate::min("bytes").function,
            AggregateFunction::Min { .. }
        ));
        assert!(matches!(
            Aggregate::max("bytes").function,
            AggregateFunction::Max { .. }
        ));
        assert!(matches!(
            Aggregate::avg("bytes").function,
            AggregateFunction::Avg { .. }
        ));

        let schema = schema();
        let budgets = Budgets::new()
            .with(BudgetKind::GroupKeyFields, 1)
            .unwrap()
            .with(BudgetKind::DistinctKeys, 10)
            .unwrap();
        let too_many_keys = Aggregation {
            group_by: Some(GroupBy::new(vec![
                GroupKey::Field("host".into()),
                GroupKey::Field("bytes".into()),
            ])),
            ..Aggregation::new()
        };
        assert!(matches!(
            too_many_keys.validate(&schema, &budgets),
            Err(QueryError::BudgetExceeded {
                kind: BudgetKind::GroupKeyFields
            })
        ));

        let unknown_distinct = Aggregation {
            exact_distinct: Some(ExactDistinct {
                field: "missing".into(),
            }),
            ..Aggregation::new()
        };
        assert!(unknown_distinct.validate(&schema, &budgets).is_err());

        let zero_top_k = Aggregation {
            top_k: Some(TopKFrequency {
                field: "host".into(),
                k: 0,
            }),
            ..Aggregation::new()
        };
        assert!(zero_top_k.validate(&schema, &budgets).is_err());

        let bad_min = Aggregation {
            aggregates: vec![Aggregate::min("host")],
            ..Aggregation::new()
        };
        assert!(bad_min.validate(&schema, &budgets).is_err());

        let unknown_avg = Aggregation {
            aggregates: vec![Aggregate::avg("missing")],
            ..Aggregation::new()
        };
        assert!(unknown_avg.validate(&schema, &budgets).is_err());
    }

    #[test]
    fn group_expansion_zero_factors() {
        assert_eq!(group_expansion_count(&[], 10).unwrap(), 1);
        assert_eq!(group_expansion_count(&[1], 10).unwrap(), 1);
    }
}

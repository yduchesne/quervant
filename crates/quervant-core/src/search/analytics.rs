//! Bounded exact aggregation: group expansion, time buckets and metric state
//! (PR 10).
//!
//! Every insertion is admitted against an explicit limit **before** the entry is
//! created; overflow, over-cardinality and over-memory conditions are typed
//! errors and never silent truncation. Integer sums use checked `i128`/`u128`
//! arithmetic and float sums use Neumaier compensated accumulation.

use std::collections::{BTreeMap, BTreeSet};

use crate::contract::document::FieldValues;
use crate::contract::value::{FieldType, FieldValue};
use crate::segment::{GroupComponent, encode_group_key};

use super::error::{SearchError, SearchResult};
use super::typed::ScanGuard;
use super::typed_compare::canonical_scalar_bytes;

/// Maximum group-by fields in one request.
pub const MAX_GROUP_FIELDS: usize = 3;

/// A fixed-width UTC time bucket.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TimeBucket {
    /// Single-valued columnar `Timestamp` field.
    pub field: String,
    /// Positive bucket width in microseconds.
    pub width_micros: i64,
    /// Bucket grid origin in microseconds.
    pub origin_micros: i64,
}

/// A bounded exact aggregate function.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AggregateMetric {
    /// Documents per group.
    Count,
    /// Checked integer / compensated float sum.
    Sum { field: String },
    /// Extremum over `I64`/`U64`/`F64`/`Timestamp`.
    Min { field: String },
    /// Extremum over `I64`/`U64`/`F64`/`Timestamp`.
    Max { field: String },
    /// Arithmetic mean over contributing values.
    Avg { field: String },
    /// Exact count of distinct typed scalar values.
    ExactDistinct { field: String },
}

/// One aggregate result value.
#[derive(Debug, Clone, PartialEq)]
pub enum NumericAggregate {
    /// Checked signed integer sum.
    Signed(i128),
    /// Checked unsigned integer sum.
    Unsigned(u128),
    /// Compensated finite float sum.
    Float(f64),
}

/// One group's metric value, aligned with `AggregateRequest::metrics`.
#[derive(Debug, Clone, PartialEq)]
pub enum MetricValue {
    /// Document count.
    Count(u64),
    /// Checked numeric sum.
    Sum(NumericAggregate),
    /// Minimum value, or `None` when no value contributed.
    Min(Option<FieldValue>),
    /// Maximum value, or `None` when no value contributed.
    Max(Option<FieldValue>),
    /// Mean, or `None` when no value contributed.
    Avg(Option<f64>),
    /// Exact distinct scalar count.
    ExactDistinct(u64),
}

/// Exact field-value frequency top-K.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrequencyTopK {
    /// Columnar typed scalar field.
    pub field: String,
    /// Maximum frequencies returned, taken after all counts are exact.
    pub limit: usize,
}

/// An exact bounded analytics request.
#[derive(Debug, Clone, PartialEq)]
pub struct AggregateRequest {
    /// Typed boolean query evaluated over effective-live documents.
    pub query: crate::contract::query::Query,
    /// Zero to three typed group keys.
    pub group_fields: Vec<String>,
    /// Optional fixed-width time bucket.
    pub time_bucket: Option<TimeBucket>,
    /// Metrics in response order.
    pub metrics: Vec<AggregateMetric>,
    /// Optional exact frequency top-K.
    pub frequency_top_k: Option<FrequencyTopK>,
    /// Runtime-only default primary timestamp selector.
    pub primary_time_field: Option<String>,
}

/// One component of a group key.
#[derive(Debug, Clone, PartialEq)]
pub enum GroupValue {
    /// Field is absent.
    Missing(FieldType),
    /// Field is an explicit null.
    Null(FieldType),
    /// Field has a typed scalar value.
    Value(FieldValue),
}

/// One exact aggregate group.
#[derive(Debug, Clone, PartialEq)]
pub struct AggregateGroup {
    /// Canonical, collision-free group-key bytes.
    pub key: Vec<u8>,
    /// Typed group components, including the time bucket when requested.
    pub components: Vec<GroupValue>,
    /// Metric values in request order.
    pub metrics: Vec<MetricValue>,
    /// Exact frequency values ordered by descending count then canonical value.
    pub frequencies: Option<Vec<(FieldValue, u64)>>,
}

/// A complete exact analytics response.
#[derive(Debug, Clone, PartialEq)]
pub struct AggregateResponse {
    /// Exact groups in canonical order.
    pub groups: Vec<AggregateGroup>,
    /// Scan diagnostics.
    pub diagnostics: super::typed::TypedScanDiagnostics,
    /// Committed generation echoed from the snapshot.
    pub generation: Option<u64>,
    /// Process-local view ordinal echoed from the snapshot.
    pub view_ordinal: u64,
}

/// Compute the signed floor bucket start for a timestamp.
pub(crate) fn bucket_start(
    micros: i64,
    width_micros: i64,
    origin_micros: i64,
) -> SearchResult<i64> {
    if width_micros <= 0 {
        return Err(SearchError::ResourceLimit {
            limit: 1,
            requested: 0,
        });
    }
    let offset = i128::from(micros) - i128::from(origin_micros);
    let width = i128::from(width_micros);
    let bucket = offset.div_euclid(width);
    let start = i128::from(origin_micros)
        .checked_add(bucket.checked_mul(width).ok_or_else(bucket_overflow)?)
        .ok_or_else(bucket_overflow)?;
    i64::try_from(start).map_err(|_| bucket_overflow())
}

fn bucket_overflow() -> SearchError {
    SearchError::Query(crate::contract::error::QueryError::NumericOverflow {
        operation: "time_bucket",
    })
}

/// Expand one field's values into group components.
///
/// An empty multi-value yields zero groups (empty vector). Missing and explicit
/// null each produce exactly one distinct component. Multi values are
/// deduplicated by canonical bytes before Cartesian expansion.
pub(crate) fn expand_field_values(
    values: &FieldValues,
    field_type: FieldType,
) -> SearchResult<Vec<GroupValue>> {
    Ok(match values {
        FieldValues::Absent => vec![GroupValue::Missing(field_type)],
        FieldValues::ExplicitNull => vec![GroupValue::Null(field_type)],
        FieldValues::Empty => Vec::new(),
        FieldValues::Single(value) => vec![GroupValue::Value(value.clone())],
        FieldValues::Multi(list) => {
            let mut seen: BTreeSet<Vec<u8>> = BTreeSet::new();
            let mut components = Vec::new();
            for value in list {
                let bytes = canonical_scalar_bytes(value).map_err(SearchError::from)?;
                if seen.insert(bytes) {
                    components.push(GroupValue::Value(value.clone()));
                }
            }
            components
        }
    })
}

enum MetricSpec {
    Count,
    Sum(FieldType),
    Avg(FieldType),
    Min,
    Max,
    Distinct,
}

impl MetricSpec {
    fn from_request(metric: &AggregateMetric, schema: &crate::contract::schema::Schema) -> Self {
        match metric {
            AggregateMetric::Count => Self::Count,
            AggregateMetric::Sum { field } => Self::Sum(field_type_of(schema, field)),
            AggregateMetric::Avg { field } => Self::Avg(field_type_of(schema, field)),
            AggregateMetric::Min { .. } => Self::Min,
            AggregateMetric::Max { .. } => Self::Max,
            AggregateMetric::ExactDistinct { .. } => Self::Distinct,
        }
    }
}

fn field_type_of(schema: &crate::contract::schema::Schema, field: &str) -> FieldType {
    schema
        .get(field)
        .map(|definition| definition.field_type)
        .unwrap_or(FieldType::Keyword)
}

enum Accumulator {
    Count(u64),
    Signed {
        total: i128,
        seen: u64,
    },
    Unsigned {
        total: u128,
        seen: u64,
    },
    Float {
        sum: f64,
        compensation: f64,
        seen: u64,
    },
    Extremum {
        max: bool,
        current: Option<FieldValue>,
    },
    Distinct(BTreeSet<Vec<u8>>),
}

impl Accumulator {
    fn add(&mut self, value: &FieldValue) -> SearchResult<()> {
        match self {
            Self::Count(count) => {
                *count = count.checked_add(1).ok_or_else(count_overflow)?;
            }
            Self::Signed { total, seen } => {
                let FieldValue::I64(number) = value else {
                    return Ok(());
                };
                *total = total
                    .checked_add(i128::from(*number))
                    .ok_or_else(sum_overflow)?;
                *seen = seen.checked_add(1).ok_or_else(count_overflow)?;
            }
            Self::Unsigned { total, seen } => {
                let FieldValue::U64(number) = value else {
                    return Ok(());
                };
                *total = total
                    .checked_add(u128::from(*number))
                    .ok_or_else(sum_overflow)?;
                *seen = seen.checked_add(1).ok_or_else(count_overflow)?;
            }
            Self::Float {
                sum,
                compensation,
                seen,
            } => {
                let FieldValue::F64(number) = value else {
                    return Ok(());
                };
                if !number.is_finite() {
                    return Err(non_finite());
                }
                neumaier_add(sum, compensation, *number);
                *seen = seen.checked_add(1).ok_or_else(count_overflow)?;
            }
            Self::Extremum { max, current } => {
                let replace = match current {
                    None => true,
                    Some(existing) => {
                        let ordering = super::typed_compare::canonical_scalar_cmp(value, existing);
                        if *max {
                            ordering == std::cmp::Ordering::Greater
                        } else {
                            ordering == std::cmp::Ordering::Less
                        }
                    }
                };
                if replace {
                    *current = Some(value.clone());
                }
            }
            Self::Distinct(_) => {}
        }
        Ok(())
    }

    fn distinct_insert(&mut self, bytes: Vec<u8>) -> bool {
        match self {
            Self::Distinct(set) => set.insert(bytes),
            _ => false,
        }
    }

    fn distinct_contains(&self, bytes: &[u8]) -> bool {
        match self {
            Self::Distinct(set) => set.contains(bytes),
            _ => false,
        }
    }

    fn distinct_len(&self) -> u64 {
        match self {
            Self::Distinct(set) => u64::try_from(set.len()).unwrap_or(u64::MAX),
            _ => 0,
        }
    }

    fn finish(&self, spec: &MetricSpec) -> SearchResult<MetricValue> {
        match spec {
            MetricSpec::Count => match self {
                Self::Count(count) => Ok(MetricValue::Count(*count)),
                _ => Err(accumulator_mismatch()),
            },
            MetricSpec::Sum(_) => match self {
                Self::Signed { total, .. } => {
                    Ok(MetricValue::Sum(NumericAggregate::Signed(*total)))
                }
                Self::Unsigned { total, .. } => {
                    Ok(MetricValue::Sum(NumericAggregate::Unsigned(*total)))
                }
                Self::Float {
                    sum, compensation, ..
                } => {
                    let value = sum + compensation;
                    if !value.is_finite() {
                        return Err(non_finite());
                    }
                    Ok(MetricValue::Sum(NumericAggregate::Float(value)))
                }
                _ => Err(accumulator_mismatch()),
            },
            MetricSpec::Avg(_) => self.average(),
            MetricSpec::Min => match self {
                Self::Extremum { current, .. } => Ok(MetricValue::Min(current.clone())),
                _ => Err(accumulator_mismatch()),
            },
            MetricSpec::Max => match self {
                Self::Extremum { current, .. } => Ok(MetricValue::Max(current.clone())),
                _ => Err(accumulator_mismatch()),
            },
            MetricSpec::Distinct => Ok(MetricValue::ExactDistinct(self.distinct_len())),
        }
    }

    fn average(&self) -> SearchResult<MetricValue> {
        match self {
            Self::Signed { total, seen } => {
                if *seen == 0 {
                    Ok(MetricValue::Avg(None))
                } else {
                    Ok(MetricValue::Avg(Some(*total as f64 / *seen as f64)))
                }
            }
            Self::Unsigned { total, seen } => {
                if *seen == 0 {
                    Ok(MetricValue::Avg(None))
                } else {
                    Ok(MetricValue::Avg(Some(*total as f64 / *seen as f64)))
                }
            }
            Self::Float {
                sum,
                compensation,
                seen,
            } => {
                if *seen == 0 {
                    Ok(MetricValue::Avg(None))
                } else {
                    let value = (sum + compensation) / *seen as f64;
                    if !value.is_finite() {
                        return Err(non_finite());
                    }
                    Ok(MetricValue::Avg(Some(value)))
                }
            }
            _ => Err(accumulator_mismatch()),
        }
    }
}

fn neumaier_add(sum: &mut f64, compensation: &mut f64, value: f64) {
    let next = *sum + value;
    if sum.abs() >= value.abs() {
        *compensation += (*sum - next) + value;
    } else {
        *compensation += (value - next) + *sum;
    }
    *sum = next;
}

fn accumulator_mismatch() -> SearchError {
    SearchError::CorruptIndex {
        detail: "metric accumulator/spec mismatch".to_owned(),
    }
}

fn sum_overflow() -> SearchError {
    SearchError::Query(crate::contract::error::QueryError::NumericOverflow { operation: "sum" })
}

fn count_overflow() -> SearchError {
    SearchError::Query(crate::contract::error::QueryError::NumericOverflow { operation: "count" })
}

fn non_finite() -> SearchError {
    SearchError::InvalidScore {
        detail: "non-finite aggregate",
    }
}

/// Conservative resource bounds for one aggregation.
#[derive(Debug, Clone, Copy)]
pub(crate) struct AggregateLimits {
    pub max_groups: u64,
    pub max_state_bytes: u64,
    pub max_distinct_per_group: u64,
    pub max_frequency_per_group: u64,
    pub max_expansion_per_doc: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct GroupOrder {
    bucket_start: Option<i64>,
    key: Vec<u8>,
}

struct GroupState {
    components: Vec<GroupValue>,
    metrics: Vec<Accumulator>,
    frequency: Option<BTreeMap<Vec<u8>, (FieldValue, u64)>>,
}

/// Exact, bounded aggregation state.
pub(crate) struct AggregationEngine {
    specs: Vec<MetricSpec>,
    frequency: bool,
    limits: AggregateLimits,
    bucket: Option<TimeBucket>,
    groups: BTreeMap<GroupOrder, GroupState>,
    state_bytes: u64,
}

/// Per-document metric values, aligned with the request metrics.
pub(crate) enum MetricInput<'a> {
    Count,
    Values(&'a [FieldValue]),
}

impl AggregationEngine {
    pub(crate) fn new(
        metrics: &[AggregateMetric],
        frequency: Option<&FrequencyTopK>,
        bucket: Option<&TimeBucket>,
        schema: &crate::contract::schema::Schema,
        limits: AggregateLimits,
    ) -> Self {
        Self {
            specs: metrics
                .iter()
                .map(|metric| MetricSpec::from_request(metric, schema))
                .collect(),
            frequency: frequency.is_some(),
            limits,
            bucket: bucket.cloned(),
            groups: BTreeMap::new(),
            state_bytes: 0,
        }
    }

    fn metric_seed(spec: &MetricSpec) -> Accumulator {
        match spec {
            MetricSpec::Count => Accumulator::Count(0),
            MetricSpec::Sum(FieldType::I64) | MetricSpec::Avg(FieldType::I64) => {
                Accumulator::Signed { total: 0, seen: 0 }
            }
            MetricSpec::Sum(FieldType::U64) | MetricSpec::Avg(FieldType::U64) => {
                Accumulator::Unsigned { total: 0, seen: 0 }
            }
            MetricSpec::Sum(_) | MetricSpec::Avg(_) => Accumulator::Float {
                sum: 0.0,
                compensation: 0.0,
                seen: 0,
            },
            MetricSpec::Min => Accumulator::Extremum {
                max: false,
                current: None,
            },
            MetricSpec::Max => Accumulator::Extremum {
                max: true,
                current: None,
            },
            MetricSpec::Distinct => Accumulator::Distinct(BTreeSet::new()),
        }
    }

    /// Admit one matching document: expand its group tuples, then update exact
    /// metrics and frequencies for every distinct tuple it contributes to.
    pub(crate) fn add_document(
        &mut self,
        guard: &mut ScanGuard<'_>,
        group_lists: &[Vec<GroupValue>],
        bucket_value: Option<&FieldValue>,
        metric_inputs: &[MetricInput<'_>],
        frequency_values: &[FieldValue],
    ) -> SearchResult<()> {
        if group_lists.iter().any(Vec::is_empty) {
            return Ok(());
        }
        if self.bucket.is_some() && bucket_value.is_none() {
            return Ok(());
        }
        let mut product: u64 = 1;
        for list in group_lists {
            product = product
                .checked_mul(u64::try_from(list.len()).unwrap_or(u64::MAX))
                .ok_or_else(expansion_limit)?;
        }
        if product > self.limits.max_expansion_per_doc {
            return Err(expansion_limit());
        }

        let mut distinct_frequencies: Vec<(Vec<u8>, FieldValue)> = Vec::new();
        if self.frequency {
            let mut seen: BTreeSet<Vec<u8>> = BTreeSet::new();
            for value in frequency_values {
                let bytes = canonical_scalar_bytes(value).map_err(SearchError::from)?;
                if seen.insert(bytes.clone()) {
                    distinct_frequencies.push((bytes, value.clone()));
                }
            }
        }

        let mut components: Vec<GroupValue> = Vec::with_capacity(group_lists.len() + 1);
        let mut emitted: BTreeSet<Vec<u8>> = BTreeSet::new();
        self.expand(
            guard,
            0,
            group_lists,
            bucket_value,
            &mut components,
            &mut emitted,
            metric_inputs,
            &distinct_frequencies,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn expand(
        &mut self,
        guard: &mut ScanGuard<'_>,
        depth: usize,
        group_lists: &[Vec<GroupValue>],
        bucket_value: Option<&FieldValue>,
        components: &mut Vec<GroupValue>,
        emitted: &mut BTreeSet<Vec<u8>>,
        metric_inputs: &[MetricInput<'_>],
        distinct_frequencies: &[(Vec<u8>, FieldValue)],
    ) -> SearchResult<()> {
        if depth < group_lists.len() {
            for value in &group_lists[depth] {
                components.push(value.clone());
                self.expand(
                    guard,
                    depth + 1,
                    group_lists,
                    bucket_value,
                    components,
                    emitted,
                    metric_inputs,
                    distinct_frequencies,
                )?;
                components.pop();
            }
            return Ok(());
        }
        if let Some(bucket) = bucket_value {
            components.push(GroupValue::Value(bucket.clone()));
        }
        let key = encode_key(components).map_err(SearchError::from)?;
        if emitted.insert(key.clone()) {
            guard.charge(1)?;
            self.apply_group(guard, key, components, metric_inputs, distinct_frequencies)?;
        }
        if bucket_value.is_some() {
            components.pop();
        }
        Ok(())
    }

    fn apply_group(
        &mut self,
        guard: &mut ScanGuard<'_>,
        key: Vec<u8>,
        components: &[GroupValue],
        metric_inputs: &[MetricInput<'_>],
        distinct_frequencies: &[(Vec<u8>, FieldValue)],
    ) -> SearchResult<()> {
        let limits = self.limits;
        let bucket_start = self.bucket.as_ref().and_then(|_| match components.last() {
            Some(GroupValue::Value(FieldValue::Timestamp(timestamp))) => {
                Some(timestamp.as_micros())
            }
            _ => None,
        });
        let order = GroupOrder { bucket_start, key };
        if !self.groups.contains_key(&order) {
            if u64::try_from(self.groups.len()).unwrap_or(u64::MAX) >= limits.max_groups {
                return Err(group_limit());
            }
            let seed_bytes = account_group(&order.key, components, &self.specs);
            reserve(&mut self.state_bytes, limits.max_state_bytes, seed_bytes)?;
            let metrics = self.specs.iter().map(Self::metric_seed).collect();
            let frequency = self.frequency.then(BTreeMap::new);
            self.groups.insert(
                order.clone(),
                GroupState {
                    components: components.to_vec(),
                    metrics,
                    frequency,
                },
            );
        }
        let state = self
            .groups
            .get_mut(&order)
            .ok_or_else(|| SearchError::CorruptIndex {
                detail: "group disappeared during update".to_owned(),
            })?;
        for (index, input) in metric_inputs.iter().enumerate() {
            let MetricInput::Values(values) = input else {
                if let Some(Accumulator::Count(count)) = state.metrics.get_mut(index) {
                    *count = count.checked_add(1).ok_or_else(count_overflow)?;
                }
                continue;
            };
            let is_distinct = matches!(state.metrics.get(index), Some(Accumulator::Distinct(_)));
            if is_distinct {
                for value in *values {
                    let bytes = canonical_scalar_bytes(value).map_err(SearchError::from)?;
                    let contains = state
                        .metrics
                        .get(index)
                        .is_some_and(|accumulator| accumulator.distinct_contains(&bytes));
                    if contains {
                        continue;
                    }
                    let len = state
                        .metrics
                        .get(index)
                        .map_or(0, Accumulator::distinct_len);
                    if len >= limits.max_distinct_per_group {
                        return Err(distinct_limit());
                    }
                    guard.charge(1)?;
                    reserve(
                        &mut self.state_bytes,
                        limits.max_state_bytes,
                        64 + bytes.len() as u64,
                    )?;
                    if let Some(accumulator) = state.metrics.get_mut(index) {
                        accumulator.distinct_insert(bytes);
                    }
                }
            } else {
                for value in *values {
                    guard.charge(1)?;
                    if let Some(accumulator) = state.metrics.get_mut(index) {
                        accumulator.add(value)?;
                    }
                }
            }
        }
        if self.frequency {
            self.apply_frequency(guard, &order, distinct_frequencies)?;
        }
        Ok(())
    }

    fn apply_frequency(
        &mut self,
        guard: &mut ScanGuard<'_>,
        order: &GroupOrder,
        distinct_frequencies: &[(Vec<u8>, FieldValue)],
    ) -> SearchResult<()> {
        let limits = self.limits;
        let state = self
            .groups
            .get_mut(order)
            .ok_or_else(|| SearchError::CorruptIndex {
                detail: "group disappeared during frequency update".to_owned(),
            })?;
        let Some(map) = state.frequency.as_mut() else {
            return Ok(());
        };
        for (bytes, value) in distinct_frequencies {
            guard.charge(1)?;
            match map.get_mut(bytes) {
                Some((_, count)) => {
                    *count = count.checked_add(1).ok_or_else(count_overflow)?;
                }
                None => {
                    if u64::try_from(map.len()).unwrap_or(u64::MAX)
                        >= limits.max_frequency_per_group
                    {
                        return Err(frequency_limit());
                    }
                    let additional = 64 + bytes.len() as u64 + value.approx_size() as u64;
                    reserve(&mut self.state_bytes, limits.max_state_bytes, additional)?;
                    map.insert(bytes.clone(), (value.clone(), 1));
                }
            }
        }
        Ok(())
    }

    /// Seed the single global group for an empty grouping (including zero
    /// matches).
    pub(crate) fn ensure_global_group(&mut self) -> SearchResult<()> {
        if !self.groups.is_empty() {
            return Ok(());
        }
        let limits = self.limits;
        if limits.max_groups == 0 {
            return Err(group_limit());
        }
        let key = encode_key(&[]).map_err(SearchError::from)?;
        let seed_bytes = account_group(&key, &[], &self.specs);
        reserve(&mut self.state_bytes, limits.max_state_bytes, seed_bytes)?;
        let metrics = self.specs.iter().map(Self::metric_seed).collect();
        let frequency = self.frequency.then(BTreeMap::new);
        self.groups.insert(
            GroupOrder {
                bucket_start: None,
                key,
            },
            GroupState {
                components: Vec::new(),
                metrics,
                frequency,
            },
        );
        Ok(())
    }

    /// Finalize exact groups in canonical order.
    pub(crate) fn finish(self, top_k: Option<usize>) -> SearchResult<Vec<AggregateGroup>> {
        let mut groups = Vec::with_capacity(self.groups.len());
        for (_, state) in self.groups {
            let mut metrics = Vec::with_capacity(self.specs.len());
            for (index, spec) in self.specs.iter().enumerate() {
                let accumulator =
                    state
                        .metrics
                        .get(index)
                        .ok_or_else(|| SearchError::CorruptIndex {
                            detail: "missing metric accumulator".to_owned(),
                        })?;
                metrics.push(accumulator.finish(spec)?);
            }
            let frequencies = match state.frequency {
                Some(map) => {
                    let mut entries: Vec<(Vec<u8>, FieldValue, u64)> = map
                        .into_iter()
                        .map(|(bytes, (value, count))| (bytes, value, count))
                        .collect();
                    entries.sort_by(|a, b| b.2.cmp(&a.2).then_with(|| a.0.cmp(&b.0)));
                    if let Some(limit) = top_k {
                        entries.truncate(limit);
                    }
                    Some(
                        entries
                            .into_iter()
                            .map(|(_, value, count)| (value, count))
                            .collect(),
                    )
                }
                None => None,
            };
            groups.push(AggregateGroup {
                key: encode_key(&state.components).map_err(SearchError::from)?,
                components: state.components,
                metrics,
                frequencies,
            });
        }
        Ok(groups)
    }
}

fn encode_key(components: &[GroupValue]) -> Result<Vec<u8>, crate::segment::SegmentError> {
    let owned: Vec<GroupComponent<'_>> = components
        .iter()
        .map(|component| match component {
            GroupValue::Missing(field_type) => GroupComponent::Missing(*field_type),
            GroupValue::Null(field_type) => GroupComponent::Null(*field_type),
            GroupValue::Value(value) => GroupComponent::Value(value),
        })
        .collect();
    encode_group_key(&owned)
}

fn account_group(key: &[u8], components: &[GroupValue], specs: &[MetricSpec]) -> u64 {
    let mut bytes = 96u64 + key.len() as u64;
    for component in components {
        bytes += 32;
        if let GroupValue::Value(value) = component {
            bytes += value.approx_size() as u64;
        }
    }
    for spec in specs {
        bytes += match spec {
            MetricSpec::Distinct => 64,
            _ => 48,
        };
    }
    bytes
}

fn reserve(state_bytes: &mut u64, limit: u64, additional: u64) -> SearchResult<()> {
    let projected = state_bytes
        .checked_add(additional)
        .ok_or_else(state_limit)?;
    if projected > limit {
        return Err(state_limit());
    }
    *state_bytes = projected;
    Ok(())
}

fn expansion_limit() -> SearchError {
    SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    }
}

fn group_limit() -> SearchError {
    SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    }
}

fn state_limit() -> SearchError {
    SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    }
}

fn distinct_limit() -> SearchError {
    SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    }
}

fn frequency_limit() -> SearchError {
    SearchError::ResourceLimit {
        limit: u64::MAX,
        requested: u64::MAX,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bucket_floor_division_handles_negatives() {
        assert_eq!(bucket_start(0, 10, 0).unwrap(), 0);
        assert_eq!(bucket_start(9, 10, 0).unwrap(), 0);
        assert_eq!(bucket_start(10, 10, 0).unwrap(), 10);
        assert_eq!(bucket_start(-1, 10, 0).unwrap(), -10);
        assert_eq!(bucket_start(-10, 10, 0).unwrap(), -10);
        assert_eq!(bucket_start(-11, 10, 0).unwrap(), -20);
        assert_eq!(bucket_start(15, 10, 5).unwrap(), 15);
        assert_eq!(bucket_start(14, 10, 5).unwrap(), 5);
    }

    #[test]
    fn bucket_rejects_zero_width() {
        assert!(bucket_start(0, 0, 0).is_err());
        assert!(bucket_start(0, -5, 0).is_err());
    }

    #[test]
    fn bucket_handles_extremes_with_checked_i128() {
        // A large origin plus a large offset must not wrap.
        let start = bucket_start(i64::MAX, i64::MAX, i64::MIN);
        assert!(start.is_ok());
    }

    #[test]
    fn expand_field_values_semantics() {
        assert_eq!(
            expand_field_values(&FieldValues::Absent, FieldType::Keyword).unwrap(),
            vec![GroupValue::Missing(FieldType::Keyword)]
        );
        assert_eq!(
            expand_field_values(&FieldValues::ExplicitNull, FieldType::I64).unwrap(),
            vec![GroupValue::Null(FieldType::I64)]
        );
        assert!(
            expand_field_values(&FieldValues::Empty, FieldType::I64)
                .unwrap()
                .is_empty()
        );
        let multi = FieldValues::Multi(vec![
            FieldValue::Keyword("a".into()),
            FieldValue::Keyword("a".into()),
            FieldValue::Keyword("b".into()),
        ]);
        assert_eq!(
            expand_field_values(&multi, FieldType::Keyword).unwrap(),
            vec![
                GroupValue::Value(FieldValue::Keyword("a".into())),
                GroupValue::Value(FieldValue::Keyword("b".into()))
            ]
        );
    }

    #[test]
    fn neumaier_compensation_improves_naive_sum() {
        let mut sum = 0.0f64;
        let mut compensation = 0.0f64;
        for _ in 0..10_000 {
            neumaier_add(&mut sum, &mut compensation, 0.1);
        }
        let total = sum + compensation;
        assert!((total - 1_000.0).abs() < 1e-9, "compensated total {total}");
    }
}
